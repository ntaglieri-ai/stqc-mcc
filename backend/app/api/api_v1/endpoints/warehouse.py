from typing import List, Literal

import base64
import io
import json
import re

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import Response
from fpdf import FPDF
from sqlalchemy import select
from sqlalchemy import text
from sqlalchemy.orm import Session

from backend.app.crud import warehouse as crud
from backend.app.db.session import get_db
from backend.app.models.warehouse import (
    Batch,
    Certificate,
    CuttingPlan,
    Material,
    MaterialRequest,
    Receipt,
    StockMovement,
    StockReservation,
    WarehouseItem,
)
from backend.app.schemas import warehouse as warehouse_schemas
from backend.app.services.qr import generate_qr_for_uuid
from backend.app.services.warehouse_items import (
    close_items_for_outgoing,
    create_items_for_incoming,
)

router = APIRouter()


@router.post("/suppliers", response_model=warehouse_schemas.SupplierRead)
def create_supplier(
    supplier_in: warehouse_schemas.SupplierCreate,
    db: Session = Depends(get_db),
):
    return crud.create_supplier(db=db, obj_in=supplier_in)


@router.get("/suppliers", response_model=List[warehouse_schemas.SupplierRead])
def list_suppliers(skip: int = 0, limit: int = 100, q: str | None = None, db: Session = Depends(get_db)):
    return crud.get_suppliers(db=db, skip=skip, limit=limit, q=q)


@router.get("/suppliers/{supplier_id}", response_model=warehouse_schemas.SupplierRead)
def get_supplier(supplier_id: int, db: Session = Depends(get_db)):
    supplier = crud.get_supplier(db=db, supplier_id=supplier_id)
    if supplier is None:
        raise HTTPException(status_code=404, detail="Fornitore non trovato")
    return supplier


@router.post("/materials", response_model=warehouse_schemas.MaterialRead)
def create_material(
    material_in: warehouse_schemas.MaterialCreate,
    db: Session = Depends(get_db),
):
    return crud.create_material(db=db, obj_in=material_in)


@router.get("/materials", response_model=List[warehouse_schemas.MaterialRead])
def list_materials(
    skip: int = 0,
    limit: int = 100,
    q: str | None = None,
    code: str | None = None,
    db: Session = Depends(get_db),
):
    return crud.get_materials(db=db, skip=skip, limit=limit, q=q, code=code)


@router.get("/materials/{material_id}", response_model=warehouse_schemas.MaterialRead)
def get_material(material_id: int, db: Session = Depends(get_db)):
    material = crud.get_material(db=db, material_id=material_id)
    if material is None:
        raise HTTPException(status_code=404, detail="Materiale non trovato")
    return material


@router.post("/batches", response_model=warehouse_schemas.BatchRead)
def create_batch(
    batch_in: warehouse_schemas.BatchCreate,
    db: Session = Depends(get_db),
):
    return crud.create_batch(db=db, obj_in=batch_in)


@router.get("/batches", response_model=List[warehouse_schemas.BatchRead])
def list_batches(skip: int = 0, limit: int = 100, material_id: int | None = None, db: Session = Depends(get_db)):
    return crud.get_batches(db=db, skip=skip, limit=limit, material_id=material_id)


@router.get("/batches/{batch_id}", response_model=warehouse_schemas.BatchRead)
def get_batch(batch_id: int, db: Session = Depends(get_db)):
    batch = crud.get_batch(db=db, batch_id=batch_id)
    if batch is None:
        raise HTTPException(status_code=404, detail="Lotto non trovato")
    return batch


@router.post("/receipts", response_model=warehouse_schemas.ReceiptRead)
def create_receipt(
    receipt_in: warehouse_schemas.ReceiptCreate,
    db: Session = Depends(get_db),
):
    if receipt_in.quantity <= 0:
        raise HTTPException(status_code=422, detail="La quantità deve essere maggiore di zero")
    return crud.create_receipt(db=db, obj_in=receipt_in)


@router.get("/receipts", response_model=List[warehouse_schemas.ReceiptRead])
def list_receipts(
    skip: int = 0,
    limit: int = 50,
    supplier_id: int | None = None,
    material_id: int | None = None,
    db: Session = Depends(get_db),
):
    return crud.get_receipts(db=db, skip=skip, limit=limit, supplier_id=supplier_id, material_id=material_id)


@router.get("/movements", response_model=List[warehouse_schemas.StockMovementRead])
def list_movements(
    skip: int = 0,
    limit: int = 50,
    material_id: int | None = None,
    commessa_id: int | None = None,
    movement_type: str | None = None,
    db: Session = Depends(get_db),
):
    return crud.get_movements(db=db, skip=skip, limit=limit, material_id=material_id, commessa_id=commessa_id, movement_type=movement_type)


@router.post("/movements", response_model=warehouse_schemas.StockMovementRead)
def create_stock_movement(
    movement_in: warehouse_schemas.StockMovementCreate,
    db: Session = Depends(get_db),
):
    if (
        movement_in.movement_type == warehouse_schemas.MovementType.ADJUSTMENT
        and movement_in.quantity == 0
    ):
        raise HTTPException(status_code=422, detail="La rettifica non può essere zero")
    if (
        movement_in.movement_type != warehouse_schemas.MovementType.ADJUSTMENT
        and movement_in.quantity <= 0
    ):
        raise HTTPException(status_code=422, detail="La quantità deve essere maggiore di zero")
    movement = StockMovement(**movement_in.model_dump())
    db.add(movement)
    db.flush()
    try:
        if movement_in.movement_type == warehouse_schemas.MovementType.INCOMING:
            create_items_for_incoming(db, movement.material_id, movement.quantity, movement.id)
        elif movement_in.movement_type in (
            warehouse_schemas.MovementType.OUTGOING,
            warehouse_schemas.MovementType.SFRIDO,
        ):
            close_items_for_outgoing(db, movement.material_id, movement.quantity, movement.id)
        elif movement_in.movement_type == warehouse_schemas.MovementType.ADJUSTMENT:
            if movement.quantity > 0:
                create_items_for_incoming(db, movement.material_id, movement.quantity, movement.id)
            elif movement.quantity < 0:
                close_items_for_outgoing(db, movement.material_id, abs(movement.quantity), movement.id)
    except ValueError as exc:
        db.rollback()
        raise HTTPException(status_code=422, detail=str(exc))
    db.commit()
    db.refresh(movement)
    return movement


@router.get("/stock/{material_id}", response_model=warehouse_schemas.StockBalanceRead)
def read_stock_balance(material_id: int, db: Session = Depends(get_db)):
    balance = crud.get_stock_balance(db=db, material_id=material_id)
    if balance is None:
        raise HTTPException(status_code=404, detail="Materiale non trovato")
    return balance


@router.get("/magazzino", response_model=List[warehouse_schemas.MagazzinoItemRead])
def list_magazzino(
    skip: int = 0,
    limit: int = 200,
    q: str | None = None,
    db: Session = Depends(get_db),
):
    return crud.get_magazzino_list(db=db, skip=skip, limit=limit, q=q)


def _physical_item_read(item: WarehouseItem) -> dict:
    material = item.material
    return {
        "id": item.id,
        "uuid": item.uuid,
        "material_id": item.material_id,
        "ordinal": item.ordinal,
        "status": item.status,
        "created_at": item.created_at,
        "exited_at": item.exited_at,
        "label": f"{material.code} · #{item.ordinal:04d}",
    }


@router.get(
    "/materials/{material_id}/items",
    response_model=List[warehouse_schemas.WarehousePhysicalItemRead],
)
def list_material_items(
    material_id: int,
    include_closed: bool = False,
    db: Session = Depends(get_db),
):
    if db.get(Material, material_id) is None:
        raise HTTPException(status_code=404, detail="Materiale non trovato")
    stmt = select(WarehouseItem).where(WarehouseItem.material_id == material_id)
    if not include_closed:
        stmt = stmt.where(WarehouseItem.status == "AVAILABLE")
    items = db.scalars(stmt.order_by(WarehouseItem.ordinal)).all()
    return [_physical_item_read(item) for item in items]


@router.get("/items/{item_uuid}/qr.png")
def warehouse_item_qr(item_uuid: str, db: Session = Depends(get_db)):
    item = db.scalar(select(WarehouseItem).where(WarehouseItem.uuid == item_uuid.lower()))
    if item is None:
        raise HTTPException(status_code=404, detail="Elemento di magazzino non trovato")
    png = base64.b64decode(generate_qr_for_uuid(item.uuid))
    return Response(content=png, media_type="image/png", headers={"Cache-Control": "public, max-age=31536000"})


def _extract_uuid(payload: str) -> str:
    match = re.search(r"/p/([0-9a-f-]{36})", payload, re.IGNORECASE)
    if match:
        return match.group(1).lower()
    try:
        data = json.loads(payload)
        value = data.get("uuid") or data.get("id")
        if value:
            return str(value).lower()
    except (json.JSONDecodeError, TypeError):
        pass
    value = payload.strip().lower()
    if re.fullmatch(r"[0-9a-f-]{36}", value, re.IGNORECASE):
        return value
    raise ValueError("QR non riconosciuto")


@router.post("/items/scan", response_model=warehouse_schemas.WarehouseScanResult)
def scan_warehouse_item(
    request: warehouse_schemas.WarehouseScanRequest,
    db: Session = Depends(get_db),
):
    try:
        item_uuid = _extract_uuid(request.payload)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc))
    item = db.scalar(select(WarehouseItem).where(WarehouseItem.uuid == item_uuid))
    if item is None:
        raise HTTPException(status_code=404, detail="QR non associato a un elemento di magazzino")
    material_row = next(
        (row for row in crud.get_magazzino_list(db=db, limit=10000) if row["material_id"] == item.material_id),
        None,
    )
    if material_row is None:
        raise HTTPException(status_code=404, detail="Materiale collegato non trovato")
    return {"item": _physical_item_read(item), "material": material_row}


def _pdf_text(value: object) -> str:
    return str(value or "-").encode("latin-1", "replace").decode("latin-1")


def _warehouse_labels_pdf(
    material: Material,
    items: list[WarehouseItem],
    label_format: str = "a6",
    custom_text: str | None = None,
) -> bytes:
    formats = {
        "a6": ("P", (105, 148)),
        "rect": ("L", (50, 100)),
        "compact": ("L", (35, 70)),
    }
    if label_format not in formats:
        raise ValueError("Formato etichetta non valido")
    orientation, page_format = formats[label_format]
    pdf = FPDF(orientation=orientation, unit="mm", format=page_format)
    pdf.set_margins(5, 5, 5)
    pdf.set_auto_page_break(False)
    for item in items:
        pdf.add_page()
        qr_bytes = base64.b64decode(generate_qr_for_uuid(item.uuid))
        item_code = _pdf_text(f"{material.code} - #{item.ordinal:04d}")
        note = _pdf_text((custom_text or "").strip()[:80])

        if label_format == "a6":
            pdf.image(io.BytesIO(qr_bytes), x=29, y=8, w=48, h=48)
            pdf.set_y(60)
            pdf.set_font("Helvetica", "B", 14)
            pdf.cell(0, 8, "STQC - MAGAZZINO", align="C", new_x="LMARGIN", new_y="NEXT")
            pdf.set_font("Helvetica", "B", 12)
            pdf.cell(0, 8, item_code, align="C", new_x="LMARGIN", new_y="NEXT")
            pdf.set_font("Helvetica", "", 9)
            for label, value in (
                ("Tipo", material.tipo),
                ("Profilo", material.profilo),
                ("Dimensioni", material.dimensioni),
                ("Qualita", material.qualita),
                ("Colata", material.colata),
            ):
                pdf.set_font("Helvetica", "B", 9)
                pdf.cell(28, 6, f"{label}:", new_x="END", new_y="LAST")
                pdf.set_font("Helvetica", "", 9)
                pdf.cell(0, 6, _pdf_text(value), new_x="LMARGIN", new_y="NEXT")
            if note:
                pdf.ln(2)
                pdf.set_font("Helvetica", "B", 9)
                pdf.multi_cell(0, 5, note, align="C")
            pdf.set_y(-12)
            pdf.set_font("Helvetica", "", 6)
            pdf.cell(0, 4, item.uuid, align="C")
        else:
            is_compact = label_format == "compact"
            qr_size = 27 if is_compact else 40
            qr_x = 4
            qr_y = 4 if is_compact else 5
            text_x = qr_x + qr_size + 4
            pdf.image(io.BytesIO(qr_bytes), x=qr_x, y=qr_y, w=qr_size, h=qr_size)
            pdf.set_xy(text_x, qr_y)
            pdf.set_font("Helvetica", "B", 8 if is_compact else 10)
            pdf.cell(0, 5, "STQC - MAGAZZINO", new_x="LMARGIN", new_y="NEXT")
            pdf.set_x(text_x)
            pdf.set_font("Helvetica", "B", 8 if is_compact else 11)
            pdf.multi_cell(0, 4 if is_compact else 5, item_code)
            pdf.set_x(text_x)
            pdf.set_font("Helvetica", "", 6 if is_compact else 8)
            details = " | ".join(filter(None, [
                _pdf_text(material.tipo),
                _pdf_text(material.profilo),
                _pdf_text(material.dimensioni),
                _pdf_text(material.qualita),
            ]))
            pdf.multi_cell(0, 3.5 if is_compact else 4, details)
            if note:
                pdf.set_x(text_x)
                pdf.set_font("Helvetica", "B", 6 if is_compact else 8)
                pdf.multi_cell(0, 3.5 if is_compact else 4, note)

    return bytes(pdf.output())


@router.get("/materials/{material_id}/labels.pdf")
def warehouse_item_labels(
    material_id: int,
    label_format: Literal["a6", "rect", "compact"] = Query("a6", alias="format"),
    text: str | None = Query(None, max_length=80),
    db: Session = Depends(get_db),
):
    material = db.get(Material, material_id)
    if material is None:
        raise HTTPException(status_code=404, detail="Materiale non trovato")
    items = db.scalars(
        select(WarehouseItem)
        .where(WarehouseItem.material_id == material_id, WarehouseItem.status == "AVAILABLE")
        .order_by(WarehouseItem.ordinal)
    ).all()
    if not items:
        raise HTTPException(status_code=404, detail="Nessun elemento fisico disponibile")
    return Response(
        content=_warehouse_labels_pdf(material, items, label_format, text),
        media_type="application/pdf",
        headers={"Content-Disposition": f'inline; filename="etichette_{material.code}.pdf"'},
    )


@router.get("/items/{item_uuid}/label.pdf")
def warehouse_single_item_label(
    item_uuid: str,
    label_format: Literal["a6", "rect", "compact"] = Query("a6", alias="format"),
    text: str | None = Query(None, max_length=80),
    db: Session = Depends(get_db),
):
    item = db.scalar(select(WarehouseItem).where(WarehouseItem.uuid == item_uuid.lower()))
    if item is None:
        raise HTTPException(status_code=404, detail="Elemento di magazzino non trovato")
    return Response(
        content=_warehouse_labels_pdf(item.material, [item], label_format, text),
        media_type="application/pdf",
        headers={"Content-Disposition": f'inline; filename="etichetta_{item.material.code}_{item.ordinal:04d}.pdf"'},
    )


@router.delete("/materials/{material_id}", status_code=204)
def delete_material(material_id: int, db: Session = Depends(get_db)):
    """Rimozione fisica di un materiale con cascade manuale.

    Ordine di eliminazione (rispetta i vincoli FK anche con SQLite foreign_keys=OFF):
      1. Certificati → dipendono da Receipt
      2. MaterialRequest → dipende da Material
      3. StockMovement → dipende da Material e Batch
      4. CuttingPlan → dipende da Material
      5. StockReservation → dipende da Material
      6. Receipt → dipende da Material e Batch
      7. Batch → dipende da Material
      8. DistintaItem.mapped_material_id → SET NULL
      9. Material
    """
    material = db.get(Material, material_id)
    if material is None:
        raise HTTPException(status_code=404, detail="Materiale non trovato")

    # 1. Certificati (tramite receipts di questo materiale)
    receipt_ids = [r.id for r in db.query(Receipt.id).filter(Receipt.material_id == material_id)]
    if receipt_ids:
        db.query(Certificate).filter(Certificate.receipt_id.in_(receipt_ids)).delete(synchronize_session=False)

    # 2–7. Dipendenze dirette
    db.query(MaterialRequest).filter(MaterialRequest.material_id == material_id).delete(synchronize_session=False)
    db.query(StockMovement).filter(StockMovement.material_id == material_id).delete(synchronize_session=False)
    db.query(CuttingPlan).filter(CuttingPlan.material_id == material_id).delete(synchronize_session=False)
    db.query(StockReservation).filter(StockReservation.material_id == material_id).delete(synchronize_session=False)
    db.query(Receipt).filter(Receipt.material_id == material_id).delete(synchronize_session=False)
    db.query(Batch).filter(Batch.material_id == material_id).delete(synchronize_session=False)

    # 8. DistintaItem: NULL out FK (non cancella il pezzo, solo scollega il materiale)
    db.execute(
        text("UPDATE distinta_items SET mapped_material_id = NULL WHERE mapped_material_id = :mid"),
        {"mid": material_id},
    )

    # 9. Materiale
    db.delete(material)
    db.commit()
