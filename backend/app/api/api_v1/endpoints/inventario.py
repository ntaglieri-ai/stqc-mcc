import os
from datetime import date
from pathlib import Path
from tempfile import NamedTemporaryFile

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile
from sqlalchemy import select
from sqlalchemy.orm import Session

from backend.app.db.session import get_db
from backend.app.models.warehouse import Material, MovementType, StockMovement
from backend.app.services.inventario import parse_inventario

router = APIRouter()


@router.post("/import")
async def import_inventario(
    file: UploadFile = File(...),
    db: Session = Depends(get_db),
):
    """Importa il file inventario .xlsm e crea materiali + movimenti INCOMING
    per lo stock attuale. Idempotente: i materiali già presenti non vengono
    duplicati; i movimenti di inventario già esistenti per la stessa data vengono saltati."""
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

    today = date.today().isoformat()
    reason = f"Inventario iniziale {today}"

    created_materials = 0
    existing_materials = 0
    created_movements = 0

    for row in rows:
        # get_or_create material
        material = db.scalars(
            select(Material).where(Material.code == row["material_code"])
        ).first()

        if material is None:
            material = Material(
                code=row["material_code"],
                description=row["description"],
                unit="PZ",
                specification=row.get("specification"),
            )
            db.add(material)
            db.flush()
            created_materials += 1
        else:
            existing_materials += 1

        # Evita duplicati: salta se esiste già un movimento con stesso reason + material
        existing_movement = db.scalars(
            select(StockMovement).where(
                StockMovement.material_id == material.id,
                StockMovement.reason == reason,
                StockMovement.movement_type == MovementType.INCOMING,
            )
        ).first()

        if existing_movement:
            continue

        movement = StockMovement(
            material_id=material.id,
            quantity=row["quantity"],
            movement_type=MovementType.INCOMING,
            reason=reason,
            destination_commessa=row.get("commessa_reference"),
            reference=file.filename,
        )
        db.add(movement)
        created_movements += 1

    db.commit()

    return {
        "status": "ok",
        "rows_parsed": len(rows),
        "materials_created": created_materials,
        "materials_existing": existing_materials,
        "movements_created": created_movements,
    }
