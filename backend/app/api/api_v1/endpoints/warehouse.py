from typing import List

from fastapi import APIRouter, Depends, HTTPException
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
)
from backend.app.schemas import warehouse as warehouse_schemas

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
    if movement_in.quantity <= 0:
        raise HTTPException(status_code=422, detail="La quantità deve essere maggiore di zero")
    return crud.create_stock_movement(db=db, obj_in=movement_in)


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
