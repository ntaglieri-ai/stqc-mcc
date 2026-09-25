"""Endpoint pubblico autenticato dal token del dispositivo NETUM."""
from pydantic import BaseModel, Field
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import func
from sqlalchemy.orm import Session

from backend.app.db.session import get_db
from datetime import datetime

from backend.app.models.commessa import ScannerDevice, ScannerReadState
from backend.app.services.ad_hoc_shipping_scan import process_ad_hoc_shipping_scan
from backend.app.services.preproduction_scan import process_preproduction_scan
from backend.app.services.inventory_scan import process_inventory_scan
from backend.app.services.qr_detail import build_qr_detail
from backend.app.services.workshop_scan import process_workshop_scan


router = APIRouter()


class NetumScanRequest(BaseModel):
    id: str | None = Field(None, max_length=120)
    msg: str = Field(..., max_length=2000)


class NetumScanResponse(BaseModel):
    ply: int
    msg: str
    ok: bool
    error_code: str | None = None
    scan_kind: str | None = None
    block_id: int | None = None
    workstation: str | None = None
    piece_id: int | None = None
    qr_code: str | None = None
    closed_pieces: int | None = None


@router.post("/netum/{device_token}/scan", response_model=NetumScanResponse)
def netum_scan(
    device_token: str,
    body: NetumScanRequest,
    db: Session = Depends(get_db),
):
    scanner = db.query(ScannerDevice).filter(ScannerDevice.device_token == device_token).first()
    if not scanner:
        raise HTTPException(404, "Scanner non configurato")
    scan_mode = (scanner.scan_mode or "OFFICINA").upper()
    if scan_mode in {"MULTI_POSTAZIONE", "ASSEMBLAGGI"}:
        from backend.app.services.multi_station_scan import process_multi_station_scan
        return process_multi_station_scan(db, scanner, body.msg, body.id)
    if scan_mode == "MAGAZZINO_INVENTARIO":
        return process_inventory_scan(db, scanner, body.msg, body.id)
    if scan_mode == "MAGAZZINO":
        return process_preproduction_scan(db, scanner, body.msg, body.id)
    if scan_mode in {"SPEDIZIONE", "SPEDIZIONE_AD_HOC"}:
        return process_ad_hoc_shipping_scan(db, scanner, body.msg, body.id)
    return process_workshop_scan(db, scanner, body.msg, body.id)


@router.post("/netum/{device_token}/preproduction-scan", response_model=NetumScanResponse)
def netum_preproduction_scan(
    device_token: str,
    body: NetumScanRequest,
    db: Session = Depends(get_db),
):
    scanner = db.query(ScannerDevice).filter(ScannerDevice.device_token == device_token).first()
    if not scanner:
        raise HTTPException(404, "Scanner non configurato")
    if scanner.scan_mode == "MAGAZZINO_INVENTARIO":
        return process_inventory_scan(db, scanner, body.msg, body.id)
    return process_preproduction_scan(db, scanner, body.msg, body.id)


@router.post("/netum/{device_token}/read")
def netum_read(
    device_token: str,
    body: NetumScanRequest,
    db: Session = Depends(get_db),
):
    scanner = db.query(ScannerDevice).filter(
        ScannerDevice.device_token == device_token,
        ScannerDevice.active.is_(True),
    ).first()
    if not scanner:
        raise HTTPException(404, "Scanner non configurato o non attivo")
    try:
        detail = build_qr_detail(db, body.msg)
    except LookupError as exc:
        return {"ply": 3, "msg": str(exc), "ok": False, "error_code": "QR_NOT_RECOGNIZED"}
    except ValueError as exc:
        return {"ply": 3, "msg": str(exc), "ok": False, "error_code": "AMBIGUOUS_QR"}
    state = db.query(ScannerReadState).filter(ScannerReadState.scanner_device_id == scanner.id).first()
    if not state:
        state = ScannerReadState(scanner_device_id=scanner.id)
        db.add(state)
    state.qr_value = detail["uuid"]
    state.entity_type = detail["entity"]
    state.read_at = datetime.utcnow()
    scanner.last_seen_at = state.read_at
    db.commit()
    return {"ply": 1, "msg": detail["code"], "ok": True, "entity": detail["entity"], "uuid": detail["uuid"]}


@router.get("/netum/{device_token}/latest-read")
def netum_latest_read(device_token: str, db: Session = Depends(get_db)):
    scanner = db.query(ScannerDevice).filter(
        ScannerDevice.device_token == device_token,
        ScannerDevice.active.is_(True),
    ).first()
    if not scanner:
        raise HTTPException(404, "Scanner non configurato o non attivo")
    state = db.query(ScannerReadState).filter(ScannerReadState.scanner_device_id == scanner.id).first()
    if not state:
        return {"scanner": scanner.scanner_code, "read_at": None, "detail": None}
    try:
        detail = build_qr_detail(db, state.qr_value)
    except (LookupError, ValueError):
        detail = None
    return {"scanner": scanner.scanner_code, "read_at": state.read_at, "detail": detail}


class StationSelection(BaseModel):
    postazione_id: int


def _active_scanner(db, device_token):
    scanner = db.query(ScannerDevice).filter_by(device_token=device_token, active=True).first()
    if not scanner:
        raise HTTPException(404, 'Scanner non disponibile')
    return scanner


@router.get('/netum/{device_token}/context')
def scanner_context(device_token: str, db: Session = Depends(get_db)):
    from backend.app.models.commessa import Workstation, ScannerPhaseEvent
    from backend.app.services.multi_station_scan import PHASES
    scanner = _active_scanner(db, device_token)
    stations = db.query(Workstation).filter(Workstation.active.is_(True), Workstation.fase.in_(PHASES)).order_by(Workstation.fase, Workstation.name).all()
    events = db.query(ScannerPhaseEvent).filter_by(scanner_device_id=scanner.id).order_by(ScannerPhaseEvent.id.desc()).limit(20).all()
    return {'name': scanner.name, 'code': scanner.scanner_code, 'mode': scanner.scan_mode,
        'postazione_id': scanner.postazione_id,
        'stations': [{'id': s.id, 'name': s.name, 'fase': s.fase} for s in stations],
        'events': [{'code': e.entity_code, 'fase': e.fase, 'station': e.workstation_code, 'timestamp': e.timestamp} for e in events]}


@router.get('/netum/{device_token}/pulse')
def scanner_pulse(device_token: str, db: Session = Depends(get_db)):
    """Firma minimale della console: ultimo evento + postazione selezionata."""
    from backend.app.models.commessa import ScannerPhaseEvent
    scanner = _active_scanner(db, device_token)
    last_id = db.query(func.max(ScannerPhaseEvent.id)).filter(
        ScannerPhaseEvent.scanner_device_id == scanner.id).scalar()
    return {'last_event_id': int(last_id or 0),
            'postazione_id': scanner.postazione_id,
            'mode': scanner.scan_mode}


@router.put('/netum/{device_token}/station')
def scanner_select_station(device_token: str, body: StationSelection, db: Session = Depends(get_db)):
    from backend.app.services.multi_station_scan import select_station
    scanner = _active_scanner(db, device_token)
    station = select_station(db, scanner, body.postazione_id)
    return {'postazione_id': station.id, 'fase': station.fase, 'name': station.name}
