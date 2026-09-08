from uuid import uuid4
from backend.app.models.commessa import WorkstationQr


def seed_station_qr(db, ws):
    if db.query(WorkstationQr).filter_by(workstation_id=ws.id).first():
        return
    for label, behavior, payload in [('Inizio', 'START', ws.start_qr_code), ('Fine', 'END', ws.end_qr_code)]:
        db.add(WorkstationQr(workstation_id=ws.id, label=label, actions=[label], behavior=behavior, payload=payload, active=True))
    db.flush()


def new_payload():
    return 'STQC:ACTION:' + uuid4().hex
