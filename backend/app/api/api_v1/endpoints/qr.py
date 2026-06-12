import json
import re
from datetime import datetime
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session

from backend.app.core.auth import require_auth
from backend.app.crud.distinta import get_distinta_item
from backend.app.db.session import get_db
from backend.app.models.user import User
from backend.app.models.warehouse import DistintaItem, ScanEvento, WarehouseItem
from backend.app.schemas.distinta import QRScanRequest, QRScanResult

router = APIRouter()


@router.get("/resolve/{item_uuid}")
def resolve_uuid(item_uuid: str, db: Session = Depends(get_db)):
    """Risolve un UUID stampato, distinguendo magazzino e pezzo commessa."""
    value = item_uuid.lower().strip()
    warehouse_item = db.query(WarehouseItem).filter(WarehouseItem.uuid == value).first()
    if warehouse_item:
        material = warehouse_item.material
        return {
            "entity": "WAREHOUSE_ITEM",
            "uuid": warehouse_item.uuid,
            "status": warehouse_item.status,
            "ordinal": warehouse_item.ordinal,
            "material": {
                "id": material.id,
                "code": material.code,
                "tipo": material.tipo,
                "profilo": material.profilo,
                "dimensioni": material.dimensioni,
                "qualita": material.qualita,
                "colata": material.colata,
            },
        }
    commessa_item = db.query(DistintaItem).filter(DistintaItem.uuid == value).first()
    if commessa_item:
        return {
            "entity": "COMMESSA_ITEM",
            "uuid": commessa_item.uuid,
            "part_number": commessa_item.part_number,
            "profilo": commessa_item.description,
            "commessa_id": commessa_item.commessa_id,
        }
    raise HTTPException(status_code=404, detail="QR non riconosciuto")


# ── Scan evento (F2 Officina) ─────────────────────────────────────────────────

class ScanEventoRequest(BaseModel):
    uuid: str
    fase_id: Optional[int] = None


def _extract_uuid(raw: str) -> str:
    """Estrae l'UUID dal payload QR: URL https://.../p/{uuid}, JSON {"id":"..."}, o UUID grezzo."""
    m = re.search(r'/p/([0-9a-f-]{36})', raw, re.IGNORECASE)
    if m:
        return m.group(1).lower()
    try:
        data = json.loads(raw)
        if "id" in data:
            return str(data["id"]).lower()
    except (json.JSONDecodeError, TypeError):
        pass
    raw = raw.strip()
    if re.fullmatch(r'[0-9a-f-]{36}', raw, re.IGNORECASE):
        return raw.lower()
    raise ValueError(f"UUID non riconoscibile nel payload: {raw!r}")


@router.post("/scan-evento")
def scan_evento(
    req: ScanEventoRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_auth),
):
    """Toggle scan su un pezzo fisico (F2 Officina).

    Nessun evento o ultimo=FINE_LAVORO → INIZIO_LAVORO
    Ultimo=INIZIO_LAVORO → FINE_LAVORO (pezzo completato, non più scannable)
    """
    try:
        item_uuid = _extract_uuid(req.uuid)
    except ValueError as exc:
        raise HTTPException(422, str(exc))

    item = db.query(DistintaItem).filter(DistintaItem.uuid == item_uuid).first()
    if item is None:
        raise HTTPException(404, f"Nessun pezzo trovato per uuid={item_uuid}")

    ultimo = (
        db.query(ScanEvento)
        .filter(ScanEvento.item_uuid == item_uuid)
        .order_by(ScanEvento.timestamp.desc())
        .first()
    )

    if ultimo and ultimo.tipo_evento == "FINE_LAVORO":
        raise HTTPException(409, "Pezzo già completato — nessun ulteriore scan consentito.")

    tipo_evento = "FINE_LAVORO" if (ultimo and ultimo.tipo_evento == "INIZIO_LAVORO") else "INIZIO_LAVORO"
    messaggio   = "🏁 Fine lavoro — pezzo completato" if tipo_evento == "FINE_LAVORO" else "▶ Inizio lavoro registrato"

    evento = ScanEvento(
        item_uuid   = item_uuid,
        utente_id   = current_user.id,
        fase_id     = req.fase_id,
        timestamp   = datetime.utcnow(),
        tipo_evento = tipo_evento,
    )
    db.add(evento)
    db.commit()

    return {
        "tipo_evento": tipo_evento,
        "item_uuid":   item_uuid,
        "part_number": item.part_number,
        "profilo":     item.description,
        "timestamp":   evento.timestamp.isoformat(),
        "messaggio":   messaggio,
        "completato":  tipo_evento == "FINE_LAVORO",
    }


@router.post("/scan", response_model=QRScanResult)
def scan_qr(request: QRScanRequest, db: Session = Depends(get_db)):
    """Riceve il payload testuale di un QR, lo decodifica e restituisce i dettagli del pezzo."""
    item_id: int | None = None

    try:
        data = json.loads(request.payload)
        item_id = int(data.get("item_id"))
    except (json.JSONDecodeError, TypeError, ValueError):
        # payload non-JSON: prova a interpretarlo come item_id diretto
        try:
            item_id = int(request.payload.strip())
        except ValueError:
            raise HTTPException(status_code=422, detail="Payload QR non riconosciuto")

    if item_id is None:
        raise HTTPException(status_code=422, detail="item_id non trovato nel payload QR")

    item = get_distinta_item(db=db, item_id=item_id)
    if item is None:
        raise HTTPException(status_code=404, detail=f"Nessun pezzo trovato per item_id={item_id}")

    result = QRScanResult(
        id=item.id,
        part_number=item.part_number,
        description=item.description,
        quantity=item.quantity,
        material_code=item.material_code,
        material_description=item.material_description,
        commessa_reference=item.commessa_reference,
        qr_code=item.qr_code,
        import_filename=item.distinta_import.filename if item.distinta_import else None,
        import_status=item.distinta_import.status if item.distinta_import else None,
    )
    return result


@router.get("/item/{item_id}", response_model=QRScanResult)
def get_item_by_id(item_id: int, db: Session = Depends(get_db)):
    """Recupera un pezzo direttamente per ID (utile per link da etichetta)."""
    item = get_distinta_item(db=db, item_id=item_id)
    if item is None:
        raise HTTPException(status_code=404, detail="Pezzo non trovato")

    return QRScanResult(
        id=item.id,
        part_number=item.part_number,
        description=item.description,
        quantity=item.quantity,
        material_code=item.material_code,
        material_description=item.material_description,
        commessa_reference=item.commessa_reference,
        qr_code=item.qr_code,
        import_filename=item.distinta_import.filename if item.distinta_import else None,
        import_status=item.distinta_import.status if item.distinta_import else None,
    )
