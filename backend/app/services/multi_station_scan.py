from datetime import datetime
from urllib.parse import unquote
from fastapi import HTTPException
from sqlalchemy import or_
from backend.app.core.config import settings
from backend.app.models.commessa import ScannerPhaseEvent, Workstation, WorkshopScanBlock, Piece, CommessaRevisione, CommessaPostOfficinaItem
from backend.app.services.distinta import parse_assembly_parents
from backend.app.services.workshop_scan import _scan_value

PHASES = {'officina', 'assemblaggi', 'saldature', 'lavorazioni', 'in-cantiere'}

def select_station(db, scanner, station_id):
    if scanner.scan_mode != 'MULTI_POSTAZIONE':
        raise HTTPException(409, 'Questo scanner non usa la scelta multi-postazione')
    station = db.get(Workstation, station_id)
    if not station or not station.active or station.fase not in PHASES:
        raise HTTPException(422, 'Postazione non disponibile')
    if db.query(WorkshopScanBlock).filter_by(scanner_device_id=scanner.id, status='OPEN').first():
        raise HTTPException(409, 'Chiudi la lavorazione aperta prima di cambiare postazione')
    scanner.postazione_id = station.id
    scanner.fase = station.fase
    scanner.updated_at = datetime.utcnow()
    db.commit()
    return station


def process_multi_station_scan(db, scanner, raw_payload, external_id=None):
    def failure(message):
        return {'ply': 3, 'ok': False, 'msg': message, 'error_code': 'SCAN_NOT_RECORDED'}
    if not scanner.active:
        return failure('Scanner non attivo')
    station = db.get(Workstation, scanner.postazione_id) if scanner.postazione_id else None
    if not station or not station.active or station.fase not in PHASES:
        return failure('Seleziona una postazione attiva nella pagina dello scanner')
    value = _scan_value(raw_payload)
    if external_id:
        previous = db.query(ScannerPhaseEvent).filter_by(scanner_device_id=scanner.id, external_id=external_id).first()
        if previous:
            if previous.raw_payload != raw_payload:
                return failure('Identificativo scansione gia utilizzato per un altro QR')
            return {'ply': 1, 'ok': True, 'msg': 'Scansione gia registrata', 'workstation': previous.workstation_code}
    revision_id = commessa_id = None
    if value.startswith('STQC:ASM:'):
        try:
            _, _, job, encoded, instance = value.split(':')
            commessa_id, instance = int(job), int(instance)
            code = unquote(encoded)
            revision = db.query(CommessaRevisione).filter_by(commessa_id=commessa_id, corrente=True).order_by(CommessaRevisione.id.desc()).first()
            if not revision or not revision.file_assemblaggi:
                return failure('File Assemblaggi non disponibile')
            records = parse_assembly_parents(settings.upload_dir.parent / revision.file_assemblaggi)
            parent = next((r for r in records if r['codice'] == code), None)
            if not parent or not 1 <= instance <= parent['quantita']:
                return failure('Assemblato non presente nella revisione corrente')
            revision_id, entity, label = revision.id, 'assemblato', f'{code} / {instance}'
        except (ValueError, OSError):
            return failure('QR assemblato o file non valido')
    elif value.startswith('STQC:POST:'):
        try:
            _, _, job, revision, code = value.split(':', 4)
            commessa_id, revision_id = int(job), int(revision)
        except ValueError:
            return failure('QR spedizione non valido')
        item = db.query(CommessaPostOfficinaItem).filter_by(commessa_id=commessa_id, revisione_id=revision_id, codice=code).first()
        if not item:
            return failure('Unita non presente nella lista spedizione')
        entity, label = 'unita_spedizione', item.codice
    else:
        pieces = db.query(Piece).filter(or_(Piece.uuid == value.lower(), Piece.qr_payload == value, Piece.qr_code == value), Piece.qr_attivo.is_(True)).all()
        exact = [p for p in pieces if p.uuid == value.lower() or p.qr_payload == value]
        matches = exact or pieces
        if len(matches) != 1:
            return failure('QR non riconosciuto o non univoco')
        piece = matches[0]
        commessa_id, revision_id, entity, label = piece.commessa_id, piece.revisione_id, 'pezzo', piece.qr_code
    now = datetime.utcnow()
    event = ScannerPhaseEvent(scanner_device_id=scanner.id, commessa_id=commessa_id, revisione_id=revision_id,
        workstation_id=station.id, workstation_code=station.code, fase=station.fase, entity=entity,
        entity_code=label, raw_payload=raw_payload, external_id=external_id, timestamp=now)
    db.add(event)
    scanner.last_seen_at = now
    scanner.fase = station.fase
    db.commit()
    return {'ply': 1, 'ok': True, 'msg': f'{label} registrato - {station.name}', 'scan_kind': 'PHASE_READ', 'workstation': station.code, 'qr_code': label}
