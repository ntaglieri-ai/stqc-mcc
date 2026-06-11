from sqlalchemy import case, func, select
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

    # INCOMING aumenta la giacenza
    total_incoming = db.scalar(
        select(func.coalesce(func.sum(StockMovement.quantity), 0))
        .where(StockMovement.material_id == material_id)
        .where(StockMovement.movement_type == MovementType.INCOMING)
    )
    # OUTGOING e SFRIDO riducono la giacenza
    total_outgoing = db.scalar(
        select(func.coalesce(func.sum(StockMovement.quantity), 0))
        .where(StockMovement.material_id == material_id)
        .where(StockMovement.movement_type.in_([MovementType.OUTGOING, MovementType.SFRIDO]))
    )
    # ADJUSTMENT è firmato: positivo = rettifica in aumento, negativo = rettifica in riduzione
    total_adjustment = db.scalar(
        select(func.coalesce(func.sum(StockMovement.quantity), 0))
        .where(StockMovement.material_id == material_id)
        .where(StockMovement.movement_type == MovementType.ADJUSTMENT)
    )
    inc  = float(total_incoming   or 0)
    out  = float(total_outgoing   or 0)
    adj  = float(total_adjustment or 0)
    return {
        "material_id": material.id,
        "material_code": material.code,
        "material_description": material.description,
        "total_incoming": inc,
        "total_outgoing": out,
        "current_stock": inc - out + adj,
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


def get_magazzino_list(
    db: Session,
    skip: int = 0,
    limit: int = 200,
    q: str | None = None,
) -> list[dict]:
    stmt = (
        select(
            Material.id,
            Material.code,
            Material.tipo,
            Material.profilo,
            Material.dimensioni,
            Material.qualita,
            Material.colata,
            Material.commessa_ref,
            Material.peso_u_kg,
            Material.peso_1_pz,
            Material.norma_uni,
            # INCOMING aumenta la giacenza
            func.coalesce(
                func.sum(
                    case(
                        (StockMovement.movement_type == MovementType.INCOMING, StockMovement.quantity),
                        else_=0,
                    )
                ),
                0,
            ).label("total_incoming"),
            # OUTGOING e SFRIDO riducono la giacenza
            func.coalesce(
                func.sum(
                    case(
                        (StockMovement.movement_type.in_([MovementType.OUTGOING, MovementType.SFRIDO]), StockMovement.quantity),
                        else_=0,
                    )
                ),
                0,
            ).label("total_outgoing"),
            # ADJUSTMENT è firmato (positivo = rettifica +, negativo = rettifica -)
            func.coalesce(
                func.sum(
                    case(
                        (StockMovement.movement_type == MovementType.ADJUSTMENT, StockMovement.quantity),
                        else_=0,
                    )
                ),
                0,
            ).label("total_adjustment"),
        )
        .outerjoin(StockMovement, StockMovement.material_id == Material.id)
        .group_by(Material.id)
        .order_by(Material.tipo, Material.profilo, Material.code)
    )
    if q:
        stmt = stmt.where(
            Material.code.ilike(f"%{q}%")
            | Material.tipo.ilike(f"%{q}%")
            | Material.profilo.ilike(f"%{q}%")
            | Material.qualita.ilike(f"%{q}%")
        )
    rows = db.execute(stmt.offset(skip).limit(limit)).all()
    result = []
    for r in rows:
        n_pezzi   = float(r.total_incoming - r.total_outgoing + r.total_adjustment)
        peso_1_pz = float(r.peso_1_pz) if r.peso_1_pz is not None else None
        peso_kg   = round(n_pezzi * peso_1_pz, 3) if peso_1_pz is not None else None
        result.append({
            "material_id": r.id,
            "material_code": r.code,
            "tipo": r.tipo,
            "profilo": r.profilo,
            "n_pezzi": n_pezzi,
            "dimensioni": r.dimensioni,
            "qualita": r.qualita,
            "colata": r.colata,
            "commessa_ref": r.commessa_ref,
            "peso_kg":   peso_kg,
            "peso_u_kg": float(r.peso_u_kg) if r.peso_u_kg is not None else None,
            "peso_1_pz": peso_1_pz,
            "norma_uni": r.norma_uni,
        })
    return result
