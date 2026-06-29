from datetime import datetime
from decimal import Decimal
from typing import List, Literal

import base64
import io
import json
import re

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import Response
from fpdf import FPDF
from sqlalchemy import select
from sqlalchemy.orm import Session, joinedload

from backend.app.crud import warehouse as crud
from backend.app.db.session import get_db
from backend.app.models.warehouse import (
    Batch,
    Certificate,
    Material,
    MovementType,
    Receipt,
    StockMovement,
    WarehouseItem,
)
from backend.app.schemas import warehouse as warehouse_schemas
from backend.app.services.qr import generate_qr_for_payload, generate_qr_for_uuid
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


def _material_code_from_input(material_in: warehouse_schemas.MaterialIncomingCreate) -> str:
    if material_in.code and material_in.code.strip():
        return material_in.code.strip().upper()
    parts = [
        material_in.tipo,
        material_in.profilo,
        material_in.dimensioni,
        material_in.qualita,
        material_in.colata,
    ]
    code = "-".join(str(part).strip().upper().replace(" ", "") for part in parts if part)
    if not code:
        raise HTTPException(status_code=422, detail="Codice o almeno tipo/profilo obbligatori")
    return code


@router.post("/materials/with-incoming", response_model=warehouse_schemas.MagazzinoItemRead)
def create_material_with_incoming(
    material_in: warehouse_schemas.MaterialIncomingCreate,
    db: Session = Depends(get_db),
):
    code = _material_code_from_input(material_in)
    existing = db.scalar(select(Material).where(Material.code == code))
    if existing is not None:
        raise HTTPException(status_code=409, detail="Codice materiale già presente: usa Ingresso su materiale esistente")

    description = material_in.description or " · ".join(
        part for part in [material_in.tipo, material_in.profilo, material_in.dimensioni, material_in.qualita] if part
    ) or code
    material = Material(
        code=code,
        description=description,
        unit=material_in.unit or "PZ",
        specification=material_in.specification,
        tipo=material_in.tipo,
        profilo=material_in.profilo,
        dimensioni=material_in.dimensioni,
        norma_uni=material_in.norma_uni,
        qualita=material_in.qualita,
        colata=material_in.colata,
        peso_u_kg=material_in.peso_u_kg,
        peso_1_pz=material_in.peso_1_pz,
    )
    db.add(material)
    db.flush()
    movement = StockMovement(
        material_id=material.id,
        quantity=material_in.quantity,
        movement_type=MovementType.INCOMING,
        reason=material_in.reason or "Ingresso nuovo materiale",
    )
    db.add(movement)
    db.flush()
    try:
        create_items_for_incoming(db, material.id, material_in.quantity, movement.id)
    except ValueError as exc:
        db.rollback()
        raise HTTPException(status_code=422, detail=str(exc))
    db.commit()
    row = next((r for r in crud.get_magazzino_list(db=db, limit=1, q=code) if r["material_id"] == material.id), None)
    if row is None:
        raise HTTPException(status_code=500, detail="Materiale creato ma non riletto")
    return row


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
    if commessa_id is not None:
        raise HTTPException(
            status_code=410,
            detail="Il magazzino e le commesse sono separati: i movimenti non sono filtrabili per commessa.",
        )
    return crud.get_movements(db=db, skip=skip, limit=limit, material_id=material_id, movement_type=movement_type)


@router.post("/movements", response_model=warehouse_schemas.StockMovementRead)
def create_stock_movement(
    movement_in: warehouse_schemas.StockMovementCreate,
    db: Session = Depends(get_db),
):
    if getattr(movement_in, "commessa_id", None) is not None or getattr(movement_in, "destination_commessa", None):
        raise HTTPException(
            status_code=422,
            detail="Il movimento di magazzino non può essere collegato a una commessa in questa fase.",
        )
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
    effective_status = "RESERVED" if item.reserved_for_commessa and item.status == "AVAILABLE" else item.status
    return {
        "id": item.id,
        "uuid": item.uuid,
        "material_id": item.material_id,
        "ordinal": item.ordinal,
        "status": effective_status,
        "created_at": item.created_at,
        "exited_at": item.exited_at,
        "label": f"{material.code} · #{item.ordinal:04d}",
        "reserved_for_commessa": item.reserved_for_commessa,
    }


def _decimal_or_none(value: object) -> float | None:
    return float(value) if value is not None else None


def _item_value(item: WarehouseItem, material: Material, field: str):
    value = getattr(item, field, None)
    if value is not None:
        return value
    return getattr(material, field, None)


def _item_detail_read(item: WarehouseItem, db: Session) -> dict:
    material = item.material
    peso_1_pz = _item_value(item, material, "peso_1_pz")
    manual_fields = [
        field
        for field in (
            "tipo",
            "profilo",
            "dimensioni",
            "norma_uni",
            "qualita",
            "colata",
            "commessa_ref",
            "reserved_for_commessa",
            "peso_u_kg",
            "peso_1_pz",
            "notes",
        )
        if getattr(item, field, None) is not None
    ]
    return {
        **_physical_item_read(item),
        "material_code": material.code,
        "description": material.description,
        "tipo": _item_value(item, material, "tipo"),
        "profilo": _item_value(item, material, "profilo"),
        "dimensioni": _item_value(item, material, "dimensioni"),
        "norma_uni": _item_value(item, material, "norma_uni"),
        "qualita": _item_value(item, material, "qualita"),
        "colata": _item_value(item, material, "colata"),
        "commessa_ref": _item_value(item, material, "commessa_ref"),
        "reserved_for_commessa": item.reserved_for_commessa,
        "peso_u_kg": _decimal_or_none(_item_value(item, material, "peso_u_kg")),
        "peso_1_pz": _decimal_or_none(peso_1_pz),
        "peso_kg": _decimal_or_none(peso_1_pz),
        "unit": material.unit,
        "source_movement_id": item.source_movement_id,
        "exit_movement_id": item.exit_movement_id,
        "notes": item.notes,
        "manual_overrides": manual_fields,
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
        stmt = stmt.where(WarehouseItem.status.in_(["AVAILABLE", "RESERVED"]))
    items = db.scalars(stmt.order_by(WarehouseItem.ordinal)).all()
    return [_physical_item_read(item) for item in items]


@router.get(
    "/items",
    response_model=List[warehouse_schemas.WarehouseItemDetailRead],
)
def list_warehouse_items(
    skip: int = 0,
    limit: int = 5000,
    include_closed: bool = False,
    q: str | None = None,
    db: Session = Depends(get_db),
):
    stmt = (
        select(WarehouseItem)
        .join(WarehouseItem.material)
        .options(joinedload(WarehouseItem.material))
        .order_by(Material.tipo, Material.profilo, Material.code, WarehouseItem.ordinal)
    )
    if not include_closed:
        stmt = stmt.where(WarehouseItem.status.in_(["AVAILABLE", "RESERVED"]))
    if q:
        like = f"%{q}%"
        stmt = stmt.where(
            Material.code.ilike(like)
            | Material.tipo.ilike(like)
            | Material.profilo.ilike(like)
            | Material.qualita.ilike(like)
            | WarehouseItem.uuid.ilike(like)
            | WarehouseItem.reserved_for_commessa.ilike(like)
        )
    items = db.scalars(stmt.offset(skip).limit(limit)).all()
    return [_item_detail_read(item, db) for item in items]


@router.get(
    "/items/{item_uuid}",
    response_model=warehouse_schemas.WarehouseItemDetailRead,
)
def get_warehouse_item(item_uuid: str, db: Session = Depends(get_db)):
    item = db.scalar(
        select(WarehouseItem)
        .options(joinedload(WarehouseItem.material))
        .where(WarehouseItem.uuid == item_uuid.lower())
    )
    if item is None:
        raise HTTPException(status_code=404, detail="Elemento di magazzino non trovato")
    return _item_detail_read(item, db)


@router.patch(
    "/items/{item_uuid}",
    response_model=warehouse_schemas.WarehouseItemDetailRead,
)
def update_warehouse_item(
    item_uuid: str,
    item_in: warehouse_schemas.WarehouseItemUpdate,
    db: Session = Depends(get_db),
):
    item = db.scalar(
        select(WarehouseItem)
        .options(joinedload(WarehouseItem.material))
        .where(WarehouseItem.uuid == item_uuid.lower())
    )
    if item is None:
        raise HTTPException(status_code=404, detail="Elemento di magazzino non trovato")
    data = item_in.model_dump(exclude_unset=True)
    for field, value in data.items():
        if isinstance(value, str):
            value = value.strip() or None
        if field in {"peso_u_kg", "peso_1_pz"} and value is not None:
            value = Decimal(str(value))
        setattr(item, field, value)
    if "reserved_for_commessa" in data:
        if item.reserved_for_commessa and item.status == "AVAILABLE":
            item.status = "RESERVED"
        elif not item.reserved_for_commessa and item.status == "RESERVED":
            item.status = "AVAILABLE"
    item.updated_at = datetime.utcnow()
    db.add(item)
    db.commit()
    db.refresh(item)
    return _item_detail_read(item, db)


@router.delete("/items/{item_uuid}", status_code=204)
def delete_warehouse_item(item_uuid: str, db: Session = Depends(get_db)):
    item = db.scalar(select(WarehouseItem).where(WarehouseItem.uuid == item_uuid.lower()))
    if item is None:
        raise HTTPException(status_code=404, detail="Elemento di magazzino non trovato")
    db.delete(item)
    db.commit()
    return Response(status_code=204)


@router.post("/items/bulk-delete", response_model=warehouse_schemas.WarehouseItemBulkDeleteResult)
def delete_warehouse_items(
    request: warehouse_schemas.WarehouseItemBulkRequest,
    db: Session = Depends(get_db),
):
    requested = [str(uuid).strip().lower() for uuid in request.uuids if str(uuid).strip()]
    requested = list(dict.fromkeys(requested))
    if not requested:
        raise HTTPException(status_code=422, detail="Nessun elemento selezionato")
    items = db.scalars(select(WarehouseItem).where(WarehouseItem.uuid.in_(requested))).all()
    found = {item.uuid for item in items}
    for item in items:
        db.delete(item)
    db.commit()
    return {
        "deleted": len(items),
        "requested": len(requested),
        "missing": [uuid for uuid in requested if uuid not in found],
    }


def _warehouse_qr_payload(item: WarehouseItem, material: Material, qr_encoding: str) -> str:
    if qr_encoding == "uuid":
        return item.uuid
    if qr_encoding == "json":
        return json.dumps(
            {
                "domain": "warehouse",
                "uuid": item.uuid,
                "material_code": material.code,
                "ordinal": item.ordinal,
            },
            ensure_ascii=False,
            separators=(",", ":"),
        )
    return f"https://stqc.mcc.eu/p/{item.uuid}"


@router.get("/items/{item_uuid}/qr.png")
def warehouse_item_qr(
    item_uuid: str,
    qr_encoding: Literal["link", "uuid", "json"] = Query("link", alias="encoding"),
    db: Session = Depends(get_db),
):
    item = db.scalar(
        select(WarehouseItem)
        .options(joinedload(WarehouseItem.material))
        .where(WarehouseItem.uuid == item_uuid.lower())
    )
    if item is None:
        raise HTTPException(status_code=404, detail="Elemento di magazzino non trovato")
    payload = _warehouse_qr_payload(item, item.material, qr_encoding)
    png = base64.b64decode(generate_qr_for_payload(payload))
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
    qr_encoding: str = "link",
    qr_size_mm: float | None = None,
    content_fields: list[str] | None = None,
) -> bytes:
    formats = {
        "a6": ("P", (105, 148)),
        "rect": ("L", (50, 100)),
        "compact": ("L", (35, 70)),
        "badge": ("L", (60, 90)),
    }
    if label_format not in formats:
        raise ValueError("Formato etichetta non valido")
    allowed_field_names = {
        "tipo",
        "profilo",
        "dimensioni",
        "norma_uni",
        "qualita",
        "colata",
        "commessa_ref",
        "reserved_for_commessa",
        "uuid",
    }
    selected_fields = [
        field for field in (content_fields or ["tipo", "profilo", "dimensioni", "qualita"])
        if field in allowed_field_names
    ][:7]
    orientation, page_format = formats[label_format]
    pdf = FPDF(orientation=orientation, unit="mm", format=page_format)
    pdf.set_margins(5, 5, 5)
    pdf.set_auto_page_break(False)
    for item in items:
        item_material = item.material or material
        allowed_fields = {
            "tipo": ("Tipo", item_material.tipo),
            "profilo": ("Profilo", item_material.profilo),
            "dimensioni": ("Dimensioni", item_material.dimensioni),
            "norma_uni": ("Norma", item_material.norma_uni),
            "qualita": ("Qualita", item_material.qualita),
            "colata": ("Colata", item_material.colata),
            "commessa_ref": ("Commessa", None),
            "reserved_for_commessa": ("Riservato", None),
            "uuid": ("UUID", None),
        }
        pdf.add_page()
        qr_payload = _warehouse_qr_payload(item, item_material, qr_encoding)
        qr_bytes = base64.b64decode(generate_qr_for_payload(qr_payload))
        item_code = _pdf_text(f"{item_material.code} - #{item.ordinal:04d}")
        note = _pdf_text((custom_text or "").strip()[:80])
        field_values = []
        for field in selected_fields:
            label, material_value = allowed_fields[field]
            value = getattr(item, field, None) if material_value is None else material_value
            if field == "uuid":
                value = item.uuid
            if value:
                field_values.append((label, value))

        if label_format == "a6":
            qr_size = qr_size_mm or 54
            qr_x = (105 - qr_size) / 2
            pdf.image(io.BytesIO(qr_bytes), x=qr_x, y=8, w=qr_size, h=qr_size)
            pdf.set_y(8 + qr_size + 5)
            pdf.set_font("Helvetica", "B", 14)
            pdf.cell(0, 8, "STQC - MAGAZZINO", align="C", new_x="LMARGIN", new_y="NEXT")
            pdf.set_font("Helvetica", "B", 12)
            pdf.cell(0, 8, item_code, align="C", new_x="LMARGIN", new_y="NEXT")
            pdf.set_font("Helvetica", "", 9)
            for label, value in field_values:
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
            is_badge = label_format == "badge"
            qr_size = qr_size_mm or (27 if is_compact else 36 if is_badge else 40)
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
            details = " | ".join(_pdf_text(value) for _, value in field_values[:5])
            pdf.multi_cell(0, 3.5 if is_compact else 4, details)
            if note:
                pdf.set_x(text_x)
                pdf.set_font("Helvetica", "B", 6 if is_compact else 8)
                pdf.multi_cell(0, 3.5 if is_compact else 4, note)

    return bytes(pdf.output())


@router.get("/materials/{material_id}/labels.pdf")
def warehouse_item_labels(
    material_id: int,
    label_format: Literal["a6", "rect", "compact", "badge"] = Query("a6", alias="format"),
    text: str | None = Query(None, max_length=80),
    qr_encoding: Literal["link", "uuid", "json"] = Query("link", alias="encoding"),
    qr_size_mm: float | None = Query(None, ge=18, le=90, alias="qr_size"),
    fields: str | None = Query(None),
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
        content=_warehouse_labels_pdf(
            material,
            items,
            label_format,
            text,
            qr_encoding,
            qr_size_mm,
            fields.split(",") if fields else None,
        ),
        media_type="application/pdf",
        headers={"Content-Disposition": f'inline; filename="etichette_{material.code}.pdf"'},
    )


@router.get("/items/{item_uuid}/label.pdf")
def warehouse_single_item_label(
    item_uuid: str,
    label_format: Literal["a6", "rect", "compact", "badge"] = Query("a6", alias="format"),
    text: str | None = Query(None, max_length=80),
    qr_encoding: Literal["link", "uuid", "json"] = Query("link", alias="encoding"),
    qr_size_mm: float | None = Query(None, ge=18, le=90, alias="qr_size"),
    fields: str | None = Query(None),
    db: Session = Depends(get_db),
):
    item = db.scalar(select(WarehouseItem).where(WarehouseItem.uuid == item_uuid.lower()))
    if item is None:
        raise HTTPException(status_code=404, detail="Elemento di magazzino non trovato")
    return Response(
        content=_warehouse_labels_pdf(
            item.material,
            [item],
            label_format,
            text,
            qr_encoding,
            qr_size_mm,
            fields.split(",") if fields else None,
        ),
        media_type="application/pdf",
        headers={"Content-Disposition": f'inline; filename="etichetta_{item.material.code}_{item.ordinal:04d}.pdf"'},
    )


@router.post("/items/labels.pdf")
def warehouse_selected_item_labels(
    request: warehouse_schemas.WarehouseLabelPrintRequest,
    db: Session = Depends(get_db),
):
    requested = [str(uuid).strip().lower() for uuid in request.uuids if str(uuid).strip()]
    requested = list(dict.fromkeys(requested))
    if not requested:
        raise HTTPException(status_code=422, detail="Nessun elemento selezionato")
    items = db.scalars(
        select(WarehouseItem)
        .options(joinedload(WarehouseItem.material))
        .where(WarehouseItem.uuid.in_(requested))
        .order_by(WarehouseItem.material_id, WarehouseItem.ordinal)
    ).all()
    if not items:
        raise HTTPException(status_code=404, detail="Nessun elemento fisico trovato")
    return Response(
        content=_warehouse_labels_pdf(
            items[0].material,
            items,
            request.label_format,
            request.text,
            request.qr_encoding,
            request.qr_size_mm,
            request.content_fields,
        ),
        media_type="application/pdf",
        headers={"Content-Disposition": 'inline; filename="etichette_selezione_magazzino.pdf"'},
    )


@router.delete("/materials/{material_id}", status_code=204)
def delete_material(material_id: int, db: Session = Depends(get_db)):
    """Rimozione fisica di un materiale dal solo dominio magazzino."""
    material = db.get(Material, material_id)
    if material is None:
        raise HTTPException(status_code=404, detail="Materiale non trovato")

    # Certificati (tramite receipts di questo materiale)
    receipt_ids = [r.id for r in db.query(Receipt.id).filter(Receipt.material_id == material_id)]
    if receipt_ids:
        db.query(Certificate).filter(Certificate.receipt_id.in_(receipt_ids)).delete(synchronize_session=False)

    db.query(WarehouseItem).filter(WarehouseItem.material_id == material_id).delete(synchronize_session=False)
    db.query(StockMovement).filter(StockMovement.material_id == material_id).delete(synchronize_session=False)
    db.query(Receipt).filter(Receipt.material_id == material_id).delete(synchronize_session=False)
    db.query(Batch).filter(Batch.material_id == material_id).delete(synchronize_session=False)

    db.delete(material)
    db.commit()
