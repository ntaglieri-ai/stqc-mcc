import json

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from backend.app.crud.distinta import get_distinta_item
from backend.app.db.session import get_db
from backend.app.schemas.distinta import QRScanRequest, QRScanResult

router = APIRouter()


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
