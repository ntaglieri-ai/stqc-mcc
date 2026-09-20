from datetime import datetime
from urllib.parse import unquote
from fastapi import HTTPException
from sqlalchemy import or_
from backend.app.core.config import settings
from backend.app.models.commessa import (AssemblyScanEvent, AssemblyScanSession,
    ScannerPhaseEvent, Workstation, WorkshopScanBlock, Piece, CommessaRevisione,
    CommessaPostOfficinaItem, WeldingScanEvent, WeldingScanSession)
from backend.app.services.distinta import parse_assembly_parents, parse_assembly_records
from backend.app.services.workshop_scan import _scan_value

PHASES = {'officina', 'assemblaggi', 'saldature', 'lavorazioni', 'in-cantiere'}


def _assembly_records(revision):
    if not revision or not revision.file_assemblaggi:
        raise ValueError('File Assemblaggi non disponibile')
    return parse_assembly_records(settings.upload_dir.parent / revision.file_assemblaggi)


def _assembly_event(db, session, event_type, raw_payload, outcome, message,
                    entity_code=None, piece_id=None, error_code=None, now=None):
    event = AssemblyScanEvent(
        session_id=session.id, event_type=event_type, raw_payload=raw_payload,
        entity_code=entity_code, piece_id=piece_id, outcome=outcome,
        error_code=error_code, message=message, timestamp=now or datetime.utcnow(),
    )
    db.add(event)
    return event


def _process_assembly_scan(db, scanner, station, raw_payload):
    value = _scan_value(raw_payload)
    now = datetime.utcnow()
    session = (db.query(AssemblyScanSession)
               .filter(AssemblyScanSession.scanner_device_id == scanner.id,
                       AssemblyScanSession.workstation_id == station.id,
                       AssemblyScanSession.status.in_(['AWAITING_PARENT', 'OPEN']))
               .order_by(AssemblyScanSession.id.desc()).first())

    def rejected(code, message, event_type='ERROR', entity_code=None, piece_id=None):
        nonlocal session
        if session is None:
            session = AssemblyScanSession(
                scanner_device_id=scanner.id, workstation_id=station.id,
                workstation_code=station.code, status='REJECTED', started_at=now, closed_at=now,
            )
            db.add(session)
            db.flush()
        _assembly_event(db, session, event_type, raw_payload, 'ERROR', message,
                        entity_code=entity_code, piece_id=piece_id, error_code=code, now=now)
        scanner.last_seen_at = now
        db.commit()
        return {'ply': 3, 'ok': False, 'msg': message, 'error_code': code}

    if value == station.start_qr_code:
        if session is not None:
            return rejected('ASSEMBLY_SESSION_ALREADY_OPEN', 'Assemblaggio già iniziato', 'STATION_START')
        session = AssemblyScanSession(
            scanner_device_id=scanner.id, workstation_id=station.id,
            workstation_code=station.code, status='AWAITING_PARENT', started_at=now,
        )
        db.add(session)
        db.flush()
        _assembly_event(db, session, 'STATION_START', raw_payload, 'OK',
                        f'INIZIO registrato · {station.name}', now=now)
        scanner.last_seen_at = now
        db.commit()
        return {'ply': 1, 'ok': True, 'msg': f'INIZIO registrato · {station.name}',
                'scan_kind': 'ASSEMBLY_START', 'workstation': station.code}

    if value == station.end_qr_code:
        if session is None:
            return rejected('ASSEMBLY_SESSION_NOT_OPEN', 'Nessun assemblaggio aperto', 'STATION_END')
        session.status = 'CLOSED'
        session.closed_at = now
        _assembly_event(db, session, 'STATION_END', raw_payload, 'OK',
                        'FINE registrata', entity_code=session.assembly_code, now=now)
        scanner.last_seen_at = now
        db.commit()
        return {'ply': 1, 'ok': True, 'msg': 'FINE registrata',
                'scan_kind': 'ASSEMBLY_END', 'workstation': station.code}

    if value.startswith('STQC:ASM:'):
        if session is None:
            return rejected('ASSEMBLY_SESSION_NOT_OPEN', 'Scansiona prima il codice INIZIO postazione', 'PARENT')
        if session.assembly_code:
            return rejected('ASSEMBLY_PARENT_ALREADY_SET', 'Assemblato padre già acquisito', 'PARENT')
        try:
            _, _, job, encoded, instance = value.split(':')
            commessa_id, instance = int(job), int(instance)
            code = unquote(encoded)
            revision = (db.query(CommessaRevisione).filter_by(commessa_id=commessa_id, corrente=True)
                        .order_by(CommessaRevisione.id.desc()).first())
            parent = next(row for row in _assembly_records(revision) if row['codice'] == code)
            if not 1 <= instance <= int(parent['quantita']):
                raise ValueError
        except (OSError, ValueError, StopIteration):
            return rejected('ASSEMBLY_PARENT_INVALID', 'QR assemblato non valido per la revisione corrente', 'PARENT')
        session.commessa_id = commessa_id
        session.revisione_id = revision.id
        session.assembly_code = code
        session.assembly_instance = instance
        session.status = 'OPEN'
        label = f'{code} / {instance}'
        _assembly_event(db, session, 'PARENT', raw_payload, 'OK',
                        f'Assemblato {label} acquisito', entity_code=label, now=now)
        scanner.last_seen_at = now
        db.commit()
        return {'ply': 1, 'ok': True, 'msg': f'Assemblato {label} acquisito',
                'scan_kind': 'ASSEMBLY_PARENT', 'workstation': station.code, 'qr_code': label}

    pieces = db.query(Piece).filter(
        or_(Piece.uuid == value.lower(), Piece.qr_payload == value, Piece.qr_code == value),
        Piece.qr_attivo.is_(True)).all()
    exact = [piece for piece in pieces if piece.uuid == value.lower() or piece.qr_payload == value]
    matches = exact or pieces
    if len(matches) != 1:
        return rejected('ASSEMBLY_CHILD_NOT_RECOGNIZED', 'QR pezzo non riconosciuto', 'CHILD')
    piece = matches[0]
    if session is None or not session.assembly_code:
        return rejected('ASSEMBLY_PARENT_MISSING', 'Scansiona prima il codice assemblato', 'CHILD',
                        entity_code=piece.qr_code, piece_id=piece.id)
    revision = db.get(CommessaRevisione, session.revisione_id)
    try:
        parent = next(row for row in _assembly_records(revision) if row['codice'] == session.assembly_code)
    except (OSError, ValueError, StopIteration):
        return rejected('ASSEMBLY_SOURCE_UNAVAILABLE', 'Gerarchia assemblato non disponibile', 'CHILD',
                        entity_code=piece.qr_code, piece_id=piece.id)
    expected_by_code = {child['codice']: int(child.get('quantita') or 0) for child in parent['children']}
    child_code = piece.marca_pos or piece.qr_code
    if child_code not in expected_by_code:
        return rejected('ASSEMBLY_CHILD_NOT_EXPECTED',
                        f'Pezzo {child_code} non previsto per assemblato {session.assembly_code}', 'CHILD',
                        entity_code=child_code, piece_id=piece.id)
    _assembly_event(db, session, 'CHILD', raw_payload, 'OK',
                    f'Pezzo {child_code} acquisito', entity_code=child_code, piece_id=piece.id, now=now)
    scanner.last_seen_at = now
    db.commit()
    return {'ply': 1, 'ok': True, 'msg': f'Pezzo {child_code} acquisito',
            'scan_kind': 'ASSEMBLY_CHILD', 'workstation': station.code, 'qr_code': piece.qr_code}


def _process_welding_scan(db, scanner, station, raw_payload):
    value = _scan_value(raw_payload)
    now = datetime.utcnow()
    session = (db.query(WeldingScanSession)
               .filter_by(scanner_device_id=scanner.id, workstation_id=station.id, status='OPEN')
               .order_by(WeldingScanSession.id.desc()).first())

    def add_event(event_type, outcome, message, commessa_id=None, revisione_id=None,
                  assembly_code=None, assembly_instance=None, error_code=None):
        event = WeldingScanEvent(
            session_id=session.id, commessa_id=commessa_id, revisione_id=revisione_id,
            event_type=event_type, assembly_code=assembly_code,
            assembly_instance=assembly_instance, raw_payload=raw_payload,
            outcome=outcome, error_code=error_code, message=message, timestamp=now,
        )
        db.add(event)
        scanner.last_seen_at = now

    if value == station.start_qr_code:
        if session:
            add_event('STATION_START', 'ERROR', 'Sessione saldatura già aperta',
                      error_code='WELDING_SESSION_ALREADY_OPEN')
            db.commit()
            return {'ply': 3, 'ok': False, 'msg': 'Sessione saldatura già aperta',
                    'error_code': 'WELDING_SESSION_ALREADY_OPEN'}
        session = WeldingScanSession(
            scanner_device_id=scanner.id, workstation_id=station.id,
            workstation_code=station.code, status='OPEN', started_at=now,
        )
        db.add(session)
        db.flush()
        add_event('STATION_START', 'OK', f'INIZIO registrato · {station.name}')
        db.commit()
        return {'ply': 1, 'ok': True, 'msg': f'INIZIO registrato · {station.name}',
                'scan_kind': 'WELDING_START', 'workstation': station.code}

    if session is None:
        return {'ply': 3, 'ok': False, 'msg': 'Scansiona prima il codice INIZIO postazione',
                'error_code': 'WELDING_SESSION_NOT_OPEN'}

    if value == station.end_qr_code:
        session.status = 'CLOSED'
        session.closed_at = now
        add_event('STATION_END', 'OK', 'FINE registrata')
        db.commit()
        return {'ply': 1, 'ok': True, 'msg': 'FINE registrata',
                'scan_kind': 'WELDING_END', 'workstation': station.code}

    if not value.startswith('STQC:ASM:'):
        add_event('ASSEMBLY', 'ERROR', 'In saldatura è richiesto il QR assemblato padre',
                  error_code='WELDING_ASSEMBLY_REQUIRED')
        db.commit()
        return {'ply': 3, 'ok': False, 'msg': 'In saldatura è richiesto il QR assemblato padre',
                'error_code': 'WELDING_ASSEMBLY_REQUIRED'}
    try:
        _, _, job, encoded, instance = value.split(':')
        commessa_id, instance = int(job), int(instance)
        code = unquote(encoded)
        revision = (db.query(CommessaRevisione).filter_by(commessa_id=commessa_id, corrente=True)
                    .order_by(CommessaRevisione.id.desc()).first())
        parents = parse_assembly_parents(settings.upload_dir.parent / revision.file_assemblaggi)
        parent = next(row for row in parents if row['codice'] == code)
        if not 1 <= instance <= int(parent['quantita']):
            raise ValueError
    except (AttributeError, OSError, ValueError, StopIteration):
        add_event('ASSEMBLY', 'ERROR', 'QR assemblato padre non valido',
                  error_code='WELDING_ASSEMBLY_INVALID')
        db.commit()
        return {'ply': 3, 'ok': False, 'msg': 'QR assemblato padre non valido',
                'error_code': 'WELDING_ASSEMBLY_INVALID'}
    label = f'{code} / {instance}'
    add_event('ASSEMBLY', 'OK', f'Assemblato {label} registrato',
              commessa_id=commessa_id, revisione_id=revision.id,
              assembly_code=code, assembly_instance=instance)
    db.commit()
    return {'ply': 1, 'ok': True, 'msg': f'Assemblato {label} registrato',
            'scan_kind': 'WELDING_ASSEMBLY', 'workstation': station.code, 'qr_code': label}

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
    if station.fase == 'assemblaggi':
        return _process_assembly_scan(db, scanner, station, raw_payload)
    if station.fase == 'saldature':
        return _process_welding_scan(db, scanner, station, raw_payload)
    value = _scan_value(raw_payload)
    # NETUM id identifies the device, not a unique scan request.
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
