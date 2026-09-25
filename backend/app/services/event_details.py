"""Capture historical details on the existing event rows, in the same transaction."""
from datetime import date, datetime
from decimal import Decimal
from enum import Enum
from urllib.parse import unquote

from sqlalchemy import event, inspect, or_
from sqlalchemy.orm import Session


def scalar(value):
    if isinstance(value, Enum):
        return value.value
    if isinstance(value, (date, datetime)):
        return value.isoformat()
    if isinstance(value, Decimal):
        return str(value)
    if isinstance(value, dict):
        return {k: scalar(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [scalar(v) for v in value]
    return value


def record(row, exclude=()):
    if row is None:
        return None
    return {col.key: scalar(getattr(row, col.key)) for col in inspect(type(row)).columns
            if col.key not in {'details_snapshot', 'device_token', *exclude}}


def capture_details(db, source):
    from backend.app.models.commessa import (Piece, Commessa, CommessaRevisione, ScannerDevice,
        Workstation, WorkshopScanAttempt, AssemblyScanEvent, AssemblyScanSession,
        WeldingScanEvent, WeldingScanSession, SpedizioneAdHocItem, CommessaPostOfficinaItem)
    from backend.app.models.warehouse import (WarehouseItem, WarehouseCustomValue,
        WarehouseCustomField, DistintaItem, StockMovement, Material, Batch, Receipt, Certificate, Supplier)
    from backend.app.services.preproduction_scan import _scan_value
    from backend.app.services.material_origin import piece_origin_attributes

    pieces, raws, shipments, assemblies = {}, {}, {}, []
    missing = []

    def add_piece(piece):
        if piece is not None:
            pieces[piece.id] = piece
            if piece.materiale_origine_id:
                raw = db.get(WarehouseItem, piece.materiale_origine_id)
                if raw is not None:
                    raws[raw.id] = raw

    def add_assembly(job, revision, code, instance):
        if not job or not code:
            return
        key = (job, revision, code, instance)
        if any(a['_key'] == key for a in assemblies):
            return
        sessions = db.query(AssemblyScanSession).filter_by(commessa_id=job,
            revisione_id=revision, assembly_code=code, assembly_instance=instance).all()
        children = db.query(AssemblyScanEvent).filter(
            AssemblyScanEvent.session_id.in_([s.id for s in sessions]),
            AssemblyScanEvent.event_type == 'CHILD', AssemblyScanEvent.outcome == 'OK').all() if sessions else []
        ids = sorted({e.piece_id for e in children if e.piece_id})
        for pid in ids:
            add_piece(db.get(Piece, pid))
        assemblies.append({'_key': key, 'commessa_id': job, 'revisione_id': revision,
            'codice': code, 'esemplare': instance, 'piece_ids': ids,
            'composizione': 'pezzi effettivamente acquisiti'})
        rev = db.get(CommessaRevisione, revision) if revision else None
        if rev and rev.file_assemblaggi:
            from backend.app.services.multi_station_scan import _assembly_records
            try:
                assemblies[-1]['distinta_assemblato'] = scalar(next(
                    (row for row in _assembly_records(rev) if row['codice'] == code), None))
            except (OSError, ValueError):
                missing.append('Distinta assemblato non disponibile per ' + code)
        if not ids:
            missing.append('Componenti non ancora acquisiti per ' + code)

    add_piece(db.get(Piece, source.piece_id) if getattr(source, 'piece_id', None) else None)
    block = getattr(source, 'scan_block_id', None)
    if block and not getattr(source, 'piece_id', None):
        for attempt in db.query(WorkshopScanAttempt).filter_by(scan_block_id=block, outcome='OK').all():
            if attempt.piece_id:
                add_piece(db.get(Piece, attempt.piece_id))
    session = None
    if isinstance(source, AssemblyScanEvent):
        session = db.get(AssemblyScanSession, source.session_id)
        if session:
            add_assembly(session.commessa_id, session.revisione_id, session.assembly_code, session.assembly_instance)
    if isinstance(source, WeldingScanEvent):
        session = db.get(WeldingScanSession, source.session_id)
        events = [source] if source.assembly_code else db.query(WeldingScanEvent).filter_by(
            session_id=source.session_id, outcome='OK').all()
        for row in events:
            add_assembly(row.commessa_id, row.revisione_id, row.assembly_code, row.assembly_instance)

    payload = getattr(source, 'payload', None) or {}
    raw_value = _scan_value(getattr(source, 'raw_payload', '') or '')
    uuid = payload.get('uuid') or getattr(source, 'item_uuid', None) or raw_value
    if uuid:
        raw = db.query(WarehouseItem).filter_by(uuid=uuid.lower()).first()
        if raw:
            raws[raw.id] = raw
            for piece in db.query(Piece).filter_by(materiale_origine_id=raw.id).all():
                add_piece(piece)
        matches = db.query(Piece).filter(or_(Piece.uuid == uuid.lower(), Piece.qr_payload == uuid, Piece.qr_code == uuid)).all()
        if len(matches) == 1:
            add_piece(matches[0])
    for pid in payload.get('piece_ids', []):
        add_piece(db.get(Piece, pid))
    if raw_value.startswith('STQC:ASM:') and getattr(source, 'outcome', 'OK') == 'OK':
        try:
            _, _, job, code, instance = raw_value.split(':')
            revision = getattr(source, 'revisione_id', None) or getattr(session, 'revisione_id', None)
            add_assembly(int(job), revision, unquote(code), int(instance))
        except ValueError:
            missing.append('Riferimento assemblato non valido')
    if raw_value.startswith('STQC:POST:'):
        try:
            _, _, job, revision, code = raw_value.split(':', 4)
            for row in db.query(CommessaPostOfficinaItem).filter_by(commessa_id=int(job), revisione_id=int(revision), codice=code).all():
                shipments['post:' + str(row.id)] = record(row)
                if row.tipo_unita == 'ASSEMBLATO':
                    missing.append('Esemplare assemblato non identificato dal QR spedizione')
        except ValueError:
            missing.append('Riferimento spedizione non valido')
    scanner_id = getattr(source, 'scanner_device_id', None) or getattr(session, 'scanner_device_id', None) or payload.get('scanner_id')
    if getattr(source, 'scan_kind', '') in {'SHIPPING', 'AD_HOC_SHIPPING'}:
        # Shipping reads create a physical row for each accepted read in this transaction.
        for row in db.info.get('event_details_shipping', []):
            if row.scanner_device_id != scanner_id or row.raw_payload != getattr(source, 'raw_payload', ''):
                continue
            shipments['shipping:' + str(row.id)] = record(row)
    if getattr(source, 'item_uuid', None):
        item = db.query(DistintaItem).filter_by(uuid=source.item_uuid).first()
        if item:
            for piece in db.query(Piece).filter_by(distinta_item_id=item.id).all():
                add_piece(piece)
            shipments['distinta:' + str(item.id)] = record(item)
    if isinstance(source, StockMovement):
        for raw in db.query(WarehouseItem).filter(or_(WarehouseItem.source_movement_id == source.id,
                WarehouseItem.exit_movement_id == source.id)).all():
            raws[raw.id] = raw
            for piece in db.query(Piece).filter_by(materiale_origine_id=raw.id).all():
                add_piece(piece)
    for shipping in shipments.values():
        if shipping.get('commessa_id') and shipping.get('revisione_id') and shipping.get('codice'):
            matches = db.query(Piece).filter_by(commessa_id=shipping['commessa_id'],
                revisione_id=shipping['revisione_id']).filter(or_(
                    Piece.qr_code == shipping['codice'], Piece.uuid == shipping['codice'])).all()
            if len(matches) == 1:
                add_piece(matches[0])
            else:
                missing.append('Collegamento al pezzo fisico non univoco per ' + shipping['codice'])
    raw_details = []
    for raw in raws.values():
        values = db.query(WarehouseCustomField, WarehouseCustomValue).join(WarehouseCustomValue,
            WarehouseCustomValue.field_id == WarehouseCustomField.id).filter(WarehouseCustomValue.material_id == raw.material_id).all()
        movement = db.get(StockMovement, raw.source_movement_id) if raw.source_movement_id else None
        batch = db.get(Batch, movement.batch_id) if movement and movement.batch_id else None
        receipts = db.query(Receipt).filter_by(batch_id=batch.id).all() if batch else []
        raw_details.append({'grezzo': record(raw), 'materiale': record(raw.material),
            'campi_personalizzati': {field.label: value.value for field, value in values},
            'movimento_origine': record(movement), 'lotto': record(batch),
            'ricezioni': [record(r) for r in receipts],
            'fornitori': [record(db.get(Supplier, sid)) for sid in sorted({r.supplier_id for r in receipts})],
            'certificati': [record(c) for r in receipts for c in db.query(Certificate).filter_by(receipt_id=r.id).all()]})
    piece_details = [{'pezzo': record(p), 'distinta': record(db.get(DistintaItem, p.distinta_item_id)) if p.distinta_item_id else None,
                     'attributi_origine_mappati': piece_origin_attributes(p), 'grezzo_id': p.materiale_origine_id} for p in pieces.values()]
    missing.extend('Grezzo non mappato per ' + p.qr_code for p in pieces.values() if not p.materiale_origine_id)
    jobs = {p.commessa_id for p in pieces.values()} | {a['commessa_id'] for a in assemblies}
    job = getattr(source, 'commessa_id', None) or getattr(session, 'commessa_id', None)
    jobs.update(row['commessa_id'] for row in shipments.values() if row.get('commessa_id'))
    if job:
        jobs.add(job)
    station_id = getattr(source, 'postazione_id', None) or getattr(source, 'workstation_id', None) or getattr(session, 'workstation_id', None)
    return {'version': 1, 'captured_at': datetime.utcnow().isoformat(), 'evento': record(source),
        'scanner': record(db.get(ScannerDevice, scanner_id)) if scanner_id else None,
        'postazione': record(db.get(Workstation, station_id)) if station_id else None,
        'commesse': [record(db.get(Commessa, jid)) for jid in sorted(jobs)],
        'revisioni': [record(db.get(CommessaRevisione, rid)) for rid in sorted(
            {p.revisione_id for p in pieces.values()} | {a['revisione_id'] for a in assemblies if a['revisione_id']})],
        'pezzi': piece_details, 'grezzi': raw_details,
        'assemblati': [{k: v for k, v in a.items() if k != '_key'} for a in assemblies],
        'unita_spedizione': list(shipments.values()), 'dati_non_disponibili': missing,
        'materiale_movimento': record(db.get(Material, source.material_id)) if isinstance(source, StockMovement) else None}


@event.listens_for(Session, 'before_flush')
def queue_snapshots(db, flush_context, instances):
    pending = []
    for row in db.new:
        if getattr(row, '__tablename__', '') == 'spedizione_ad_hoc_items':
            db.info.setdefault('event_details_shipping', []).append(row)
        if hasattr(row, 'details_snapshot') and row.details_snapshot is None:
            pending.append((row, 'creation'))
            if row.__tablename__ == 'warehouse_change_requests' and (row.applied_at or row.rejected_at):
                pending.append((row, 'decision'))
    for row in db.dirty:
        if getattr(row, '__tablename__', '') == 'warehouse_change_requests':
            state = inspect(row)
            if any(state.attrs[key].history.has_changes() and getattr(row, key) for key in ('applied_at', 'rejected_at')):
                pending.append((row, 'decision'))
    db.info['event_details_pending'] = pending


@event.listens_for(Session, 'after_flush_postexec')
def save_snapshots(db, flush_context):
    for row, kind in db.info.pop('event_details_pending', []):
        db.info.setdefault('event_details_transaction', {})[(id(row), kind)] = (row, kind)
        snapshot = capture_details(db, row)
        if row.__tablename__ == 'warehouse_change_requests':
            row.details_snapshot = {**(row.details_snapshot or {}), kind: snapshot}
        else:
            row.details_snapshot = snapshot


@event.listens_for(Session, 'before_commit')
def complete_snapshots(db):
    # Some writers flush the event before assigning the final piece state or
    # inserting physical movement items. Complete its snapshot before commit.
    db.flush()
    for row, kind in db.info.get('event_details_transaction', {}).values():
        if row in db.deleted:
            continue
        snapshot = capture_details(db, row)
        if row.__tablename__ == 'warehouse_change_requests':
            row.details_snapshot = {**(row.details_snapshot or {}), kind: snapshot}
        else:
            row.details_snapshot = snapshot


@event.listens_for(Session, 'after_rollback')
@event.listens_for(Session, 'after_commit')
def clear_snapshots(db):
    db.info.pop('event_details_pending', None)
    db.info.pop('event_details_transaction', None)
    db.info.pop('event_details_shipping', None)
