import os
from pathlib import Path
from tempfile import NamedTemporaryFile

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile
from sqlalchemy import select
from sqlalchemy.orm import Session

from backend.app.crud import warehouse as crud
from backend.app.db.session import get_db
from backend.app.models.warehouse import Material, MovementType, StockMovement
from backend.app.services.inventario import parse_inventario
from backend.app.services.warehouse_items import reconcile_available_items

router = APIRouter()


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
