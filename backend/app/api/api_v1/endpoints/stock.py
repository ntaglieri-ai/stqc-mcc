"""Stock reservations and cutting-stock analysis endpoints."""
from __future__ import annotations

from typing import List

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from backend.app.crud import stock as crud
from backend.app.db.session import get_db
from backend.app.models.warehouse import Material
from backend.app.schemas.warehouse import (
    DistintaAnalysisRequest,
    DistintaAnalysisResult,
    StockReservationCreate,
    StockReservationRead,
)
from backend.app.services.cutting_stock import analyze_material

router = APIRouter()


@router.post("/reservations", response_model=StockReservationRead, status_code=201)
def create_reservation(
    reservation_in: StockReservationCreate,
    db: Session = Depends(get_db),
):
    """Crea una prenotazione / conferma uscita / rientro sfrido sul magazzino."""
    return crud.create_reservation(db=db, obj_in=reservation_in)


@router.post("/analyze", response_model=DistintaAnalysisResult)
def analyze_distinta(
    req: DistintaAnalysisRequest,
    db: Session = Depends(get_db),
):
    """Esegui analisi FFD cutting-stock per tutti i materiali della distinta.

    Salva i piani di taglio in cutting_plans se commessa_id è fornito.
    """
    results: list[dict] = []

    for item in req.items:
        material: Material | None = db.get(Material, item.material_id)

        stock_item = {
            "n_pezzi":        item.n_available,
            "dimensioni":     item.dim1_stock,
            "dimensione_2":   item.dim2_stock,
            "unita_misura":   item.unita_misura or (material.unita_misura if material else "pz"),
            "peso_1_pz":      item.peso_1_pz or (float(material.peso_1_pz) if material and material.peso_1_pz else None),
            "peso_kg":        item.peso_kg,
        }

        required_pieces = [{
            "length_mm": item.length_mm,
            "width_mm":  item.width_mm,
            "quantity":  item.quantity,
        }]

        plan = analyze_material(
            profilo=item.profilo,
            qualita=item.qualita,
            required_pieces=required_pieces,
            stock_item=stock_item,
        )

        if req.commessa_id and material is not None:
            crud.create_cutting_plan(
                db=db,
                commessa_id=req.commessa_id,
                material_id=item.material_id,
                plan_data=plan,
            )

        results.append(plan)

    # Sfrido totale = media pesata sulle voci con sfrido calcolabile
    sfrido_values = [r["sfrido_pct"] for r in results if r.get("sfrido_pct") is not None]
    sfrido_totale = sum(sfrido_values) / len(sfrido_values) if sfrido_values else 0.0

    return DistintaAnalysisResult(
        cutting_plans=results,
        sfrido_totale_percentuale=round(sfrido_totale, 2),
        warning_sfrido=sfrido_totale > 20.0,
    )
