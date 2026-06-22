import os
from pathlib import Path
from tempfile import NamedTemporaryFile
from typing import Optional

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from backend.app.crud import warehouse as crud
from backend.app.db.session import get_db
from backend.app.models.warehouse import Material, MovementType, StockMovement
from backend.app.services.ddt import analyze_ddt_pdf
from backend.app.services.inventario import parse_inventario
from backend.app.services.warehouse_items import create_items_for_incoming, reconcile_available_items

router = APIRouter()


class DdtConfirmItem(BaseModel):
    material_code: str = Field(..., min_length=1, max_length=100)
    description: str = Field(..., min_length=1, max_length=400)
    quantity: int = Field(..., gt=0)
    unit: str = "PZ"
    tipo: Optional[str] = None
    profilo: Optional[str] = None
    dimensioni: Optional[str] = None
    qualita: Optional[str] = None
    colata: Optional[str] = None
    peso_kg: Optional[float] = None
    peso_u_kg: Optional[float] = None


class DdtConfirmRequest(BaseModel):
    filename: Optional[str] = None
    supplier: Optional[str] = None
    ddt_number: Optional[str] = None
    ddt_date: Optional[str] = None
    reference: Optional[str] = None
    items: list[DdtConfirmItem]


def _upsert_material_from_ddt(db: Session, item: DdtConfirmItem) -> Material:
    material = db.scalars(
        select(Material).where(Material.code == item.material_code)
    ).first()
    if material is None:
        material = Material(
            code=item.material_code,
            description=item.description,
            unit=item.unit or "PZ",
            specification=item.qualita,
            tipo=item.tipo,
            profilo=item.profilo,
            dimensioni=item.dimensioni,
            qualita=item.qualita,
            colata=item.colata,
            commessa_ref=None,
            peso_u_kg=item.peso_u_kg,
            peso_1_pz=item.peso_u_kg,
        )
        db.add(material)
        db.flush()
        return material

    material.description = item.description or material.description
    material.unit = item.unit or material.unit
    material.specification = item.qualita or material.specification
    material.tipo = item.tipo or material.tipo
    material.profilo = item.profilo or material.profilo
    material.dimensioni = item.dimensioni or material.dimensioni
    material.qualita = item.qualita or material.qualita
    material.colata = item.colata or material.colata
    material.commessa_ref = None
    material.peso_u_kg = item.peso_u_kg or material.peso_u_kg
    material.peso_1_pz = item.peso_u_kg or material.peso_1_pz
    return material


@router.post("/import")
async def import_inventario(
    file: UploadFile = File(...),
    db: Session = Depends(get_db),
):
    """Importa il file inventario .xlsm e crea materiali + movimenti INCOMING
    per lo stock attuale. Idempotente: i materiali già presenti vengono aggiornati
    con i campi strutturati; i movimenti di inventario già esistenti per la stessa
    data vengono saltati."""
    suffix = Path(file.filename).suffix or ".xlsm"
    with NamedTemporaryFile(delete=False, suffix=suffix) as tmp:
        tmp.write(await file.read())
        tmp_path = Path(tmp.name)

    try:
        rows = parse_inventario(tmp_path)
    except Exception as exc:
        raise HTTPException(status_code=400, detail=f"Impossibile leggere il file: {exc}")
    finally:
        try:
            os.remove(tmp_path)
        except OSError:
            pass

    if not rows:
        raise HTTPException(status_code=422, detail="Nessuna riga di stock trovata nel file")

    created_materials = 0
    existing_materials = 0
    created_movements = 0
    physical_items_created = 0
    physical_items_closed = 0

    for row in rows:
        material = db.scalars(
            select(Material).where(Material.code == row["material_code"])
        ).first()

        if material is None:
            material = Material(
                code=row["material_code"],
                description=row["description"],
                unit="PZ",
                specification=row.get("specification"),
                tipo=row.get("tipo"),
                profilo=row.get("profilo"),
                dimensioni=row.get("dimensioni"),
                qualita=row.get("qualita"),
                colata=row.get("colata"),
                commessa_ref=None,
                peso_u_kg=row.get("peso_u_kg"),
                peso_1_pz=row.get("peso_1_pz"),
                norma_uni=row.get("norma_uni"),
            )
            db.add(material)
            db.flush()
            created_materials += 1
        else:
            # Aggiorna sempre i campi strutturati (possono essere stati arricchiti).
            # Per le dimensioni lineari (lunghezza barra) teniamo il valore MASSIMO:
            # più bar lunghe sono più utili per i tagli.
            material.tipo = row.get("tipo") or material.tipo
            material.profilo = row.get("profilo") or material.profilo
            new_dim = row.get("dimensioni")
            if new_dim:
                try:
                    if not material.dimensioni or float(new_dim) > float(material.dimensioni):
                        material.dimensioni = new_dim
                except (TypeError, ValueError):
                    material.dimensioni = material.dimensioni or new_dim
            material.qualita = row.get("qualita") or material.qualita
            material.colata = row.get("colata") or material.colata
            material.commessa_ref = None
            material.peso_u_kg  = row.get("peso_u_kg")  or material.peso_u_kg
            material.peso_1_pz  = row.get("peso_1_pz")  or material.peso_1_pz
            material.norma_uni  = row.get("norma_uni")  or material.norma_uni
            existing_materials += 1

        balance = crud.get_stock_balance(db=db, material_id=material.id)
        current_stock = float(balance["current_stock"] if balance else 0)
        target_stock = float(row["quantity"])
        delta = target_stock - current_stock
        if abs(delta) > 1e-9:
            movement = StockMovement(
                material_id=material.id,
                quantity=delta,
                movement_type=MovementType.ADJUSTMENT,
                reason="Riconciliazione inventario",
                reference=file.filename,
            )
            db.add(movement)
            created_movements += 1

        try:
            sync = reconcile_available_items(db, material, target_stock)
        except ValueError as exc:
            db.rollback()
            raise HTTPException(status_code=422, detail=f"{material.code}: {exc}")
        physical_items_created += sync["created"]
        physical_items_closed += sync["closed"]

    db.commit()

    return {
        "status": "ok",
        "rows_parsed": len(rows),
        "materials_created": created_materials,
        "materials_existing": existing_materials,
        "movements_created": created_movements,
        "physical_items_created": physical_items_created,
        "physical_items_closed": physical_items_closed,
    }


@router.post("/ddt/analyze")
async def analyze_ddt(
    file: UploadFile = File(...),
):
    suffix = Path(file.filename or "").suffix or ".pdf"
    with NamedTemporaryFile(delete=False, suffix=suffix) as tmp:
        tmp.write(await file.read())
        tmp_path = Path(tmp.name)

    try:
        return analyze_ddt_pdf(tmp_path, file.filename)
    except Exception as exc:
        raise HTTPException(status_code=400, detail=f"Impossibile analizzare il DDT: {exc}")
    finally:
        try:
            os.remove(tmp_path)
        except OSError:
            pass


@router.post("/ddt/confirm")
def confirm_ddt(
    payload: DdtConfirmRequest,
    db: Session = Depends(get_db),
):
    if not payload.items:
        raise HTTPException(status_code=422, detail="Nessun materiale da inserire")

    created_movements = 0
    physical_items_created = 0
    materials: list[dict] = []
    reference_bits = [
        part for part in [payload.filename, payload.ddt_number, payload.supplier] if part
    ]
    reference = " · ".join(reference_bits)[:255] if reference_bits else "DDT"

    try:
        for item in payload.items:
            material = _upsert_material_from_ddt(db, item)
            movement = StockMovement(
                material_id=material.id,
                quantity=item.quantity,
                movement_type=MovementType.INCOMING,
                reason="Ingresso da DDT",
                reference=reference,
            )
            db.add(movement)
            db.flush()
            created_movements += 1
            created_items = create_items_for_incoming(db, material.id, item.quantity, movement.id)
            physical_items_created += len(created_items)
            materials.append(
                {
                    "material_id": material.id,
                    "material_code": material.code,
                    "quantity": item.quantity,
                    "physical_items_created": len(created_items),
                }
            )
        db.commit()
    except ValueError as exc:
        db.rollback()
        raise HTTPException(status_code=422, detail=str(exc))
    except Exception:
        db.rollback()
        raise

    return {
        "status": "ok",
        "materials": materials,
        "movements_created": created_movements,
        "physical_items_created": physical_items_created,
    }
