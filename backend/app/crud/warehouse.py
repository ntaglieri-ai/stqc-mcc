from sqlalchemy import func, select
from sqlalchemy.orm import Session

from backend.app.models.warehouse import (
    Batch,
    Certificate,
    Material,
    MovementType,
    Receipt,
    StockMovement,
    Supplier,
)
from backend.app.schemas import warehouse as warehouse_schemas


def create_supplier(db: Session, obj_in: warehouse_schemas.SupplierCreate) -> Supplier:
    supplier = Supplier(**obj_in.model_dump())
    db.add(supplier)
    db.commit()
    db.refresh(supplier)
    return supplier


def create_material(db: Session, obj_in: warehouse_schemas.MaterialCreate) -> Material:
    material = Material(**obj_in.model_dump())
    db.add(material)
    db.commit()
    db.refresh(material)
    return material


def create_batch(db: Session, obj_in: warehouse_schemas.BatchCreate) -> Batch:
    batch = Batch(**obj_in.model_dump())
    db.add(batch)
    db.commit()
    db.refresh(batch)
    return batch


def create_receipt(db: Session, obj_in: warehouse_schemas.ReceiptCreate) -> Receipt:
    receipt = Receipt(**obj_in.model_dump())
    db.add(receipt)
    db.commit()
    db.refresh(receipt)
    return receipt


def create_certificate(db: Session, obj_in: warehouse_schemas.CertificateCreate) -> Certificate:
    certificate = Certificate(**obj_in.model_dump())
    db.add(certificate)
    db.commit()
    db.refresh(certificate)
    return certificate


def create_stock_movement(db: Session, obj_in: warehouse_schemas.StockMovementCreate) -> StockMovement:
    movement_data = obj_in.model_dump()
    movement = StockMovement(**movement_data)
    db.add(movement)
    db.commit()
    db.refresh(movement)
    return movement


def get_stock_balance(db: Session, material_id: int) -> dict | None:
    material = db.get(Material, material_id)
    if material is None:
        return None

    total_incoming = db.scalar(
        select(func.coalesce(func.sum(StockMovement.quantity), 0))
        .where(StockMovement.material_id == material_id)
        .where(StockMovement.movement_type == MovementType.INCOMING)
    )
    total_outgoing = db.scalar(
        select(func.coalesce(func.sum(StockMovement.quantity), 0))
        .where(StockMovement.material_id == material_id)
        .where(StockMovement.movement_type == MovementType.OUTGOING)
    )
    return {
        "material_id": material.id,
        "material_code": material.code,
        "material_description": material.description,
        "total_incoming": float(total_incoming or 0),
        "total_outgoing": float(total_outgoing or 0),
        "current_stock": float((total_incoming or 0) - (total_outgoing or 0)),
    }


def get_supplier(db: Session, supplier_id: int) -> Supplier | None:
    return db.get(Supplier, supplier_id)


def get_suppliers(db: Session, skip: int = 0, limit: int = 100, q: str | None = None) -> list[Supplier]:
    stmt = select(Supplier)
    if q:
        stmt = stmt.where(Supplier.name.ilike(f"%{q}%"))
    return db.scalars(stmt.offset(skip).limit(limit)).all()


def get_material(db: Session, material_id: int) -> Material | None:
    return db.get(Material, material_id)


def get_materials(
    db: Session,
    skip: int = 0,
    limit: int = 100,
    q: str | None = None,
    code: str | None = None,
) -> list[Material]:
    stmt = select(Material)
    if code:
        stmt = stmt.where(Material.code.ilike(f"%{code}%"))
    elif q:
        stmt = stmt.where(
            Material.code.ilike(f"%{q}%") | Material.description.ilike(f"%{q}%")
        )
    return db.scalars(stmt.order_by(Material.code).offset(skip).limit(limit)).all()


def get_batch(db: Session, batch_id: int) -> Batch | None:
    return db.get(Batch, batch_id)


def get_batches(db: Session, skip: int = 0, limit: int = 100, material_id: int | None = None) -> list[Batch]:
    stmt = select(Batch)
    if material_id:
        stmt = stmt.where(Batch.material_id == material_id)
    return db.scalars(stmt.offset(skip).limit(limit)).all()


def get_receipts(
    db: Session,
    skip: int = 0,
    limit: int = 100,
    supplier_id: int | None = None,
    material_id: int | None = None,
) -> list[Receipt]:
    stmt = select(Receipt)
    if supplier_id:
        stmt = stmt.where(Receipt.supplier_id == supplier_id)
    if material_id:
        stmt = stmt.where(Receipt.material_id == material_id)
    return db.scalars(stmt.order_by(Receipt.ddt_date.desc()).offset(skip).limit(limit)).all()


def get_movements(
    db: Session,
    skip: int = 0,
    limit: int = 100,
    material_id: int | None = None,
    commessa_id: int | None = None,
    movement_type: str | None = None,
) -> list[StockMovement]:
    stmt = select(StockMovement)
    if material_id:
        stmt = stmt.where(StockMovement.material_id == material_id)
    if commessa_id:
        stmt = stmt.where(StockMovement.commessa_id == commessa_id)
    if movement_type:
        stmt = stmt.where(StockMovement.movement_type == movement_type)
    return db.scalars(stmt.order_by(StockMovement.occurred_at.desc()).offset(skip).limit(limit)).all()


def get_receipt(db: Session, receipt_id: int) -> Receipt | None:
    return db.get(Receipt, receipt_id)


def get_certificates(db: Session, receipt_id: int) -> list[Certificate]:
    return db.scalars(select(Certificate).where(Certificate.receipt_id == receipt_id)).all()


def get_certificate(db: Session, cert_id: int) -> Certificate | None:
    return db.get(Certificate, cert_id)
