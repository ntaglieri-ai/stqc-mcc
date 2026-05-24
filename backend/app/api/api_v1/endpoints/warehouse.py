from typing import List

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from backend.app.crud import warehouse as crud
from backend.app.db.session import get_db
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
