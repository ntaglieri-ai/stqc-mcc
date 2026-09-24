"""Physical inventory readings, without workshop sessions or material mapping."""
from datetime import datetime

from backend.app.models.warehouse import ScanEvento, WarehouseItem
from backend.app.services.preproduction_scan import _attempt, _scan_value
from backend.app.services.warehouse_notifications import create_warehouse_change_request
from fastapi import HTTPException


def process_inventory_scan(db, scanner, raw_payload, external_id=None):
    value = _scan_value(raw_payload).lower()
    item = db.query(WarehouseItem).filter(WarehouseItem.uuid == value).first() if scanner.active else None
    error = None if item else ('QR_NOT_RECOGNIZED' if scanner.active else 'SCANNER_INACTIVE')
    label = f'{item.material.code} · pezzo #{item.ordinal}' if item else None
    message = f'{label}: notifica inviata al magazzino' if item else ('Materiale non trovato in questo magazzino' if scanner.active else 'Scanner disattivato')
    attempt = _attempt(db, scanner, external_id, raw_payload, 'INVENTORY_CHECK',
             'OK' if item else 'ERROR', message, error_code=error)
    scanner.last_seen_at = datetime.utcnow()
    if item:
        db.flush()
        create_warehouse_change_request(
            db, action='inventory_presence', title='Scansione inventario',
            summary=f'{item.material.code} · pezzo #{item.ordinal} · scanner {scanner.scanner_code}. Scegli Ingresso, Uscita, Modifica o Check.',
            payload={'uuid': item.uuid, 'scanner_code': scanner.scanner_code,
                     'scanner_id': scanner.id, 'scanned_at': scanner.last_seen_at,
                     'scan_attempt_id': attempt.id, 'material_label': label},
        )
    else:
        db.commit()
    return {'ply': 1 if item else 3, 'ok': bool(item), 'msg': message,
            'error_code': error, 'scan_kind': 'INVENTORY_CHECK'}


def apply_inventory_presence(db, payload):
    item = db.query(WarehouseItem).filter(WarehouseItem.uuid == payload.get('uuid')).first()
    if item is None:
        raise HTTPException(404, 'Materiale della notifica non più disponibile')
    event = ScanEvento(item_uuid=item.uuid, tipo_evento='INVENTARIO',
                       postazione=payload.get('scanner_code'),
                       timestamp=datetime.fromisoformat(payload['scanned_at']))
    db.add(event)
    db.flush()
    return {'uuid': item.uuid, 'presence_event_id': event.id}
