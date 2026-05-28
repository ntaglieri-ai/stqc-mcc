"""Stock reservations, cutting-stock analysis, and material request endpoints."""
from __future__ import annotations

import logging
from datetime import datetime
from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session

from backend.app.crud import stock as crud
from backend.app.db.session import get_db
from backend.app.models.warehouse import (
    Material,
    MaterialRequest,
    MovementType,
    RichiestaStatus,
    StockMovement,
)
from backend.app.schemas.warehouse import (
    DistintaAnalysisRequest,
    DistintaAnalysisResult,
    StockReservationCreate,
    StockReservationRead,
)
from backend.app.services.cutting_stock import analyze_material
from backend.app.services.distinta import normalize_profile

_logger = logging.getLogger("stqc.stock")

router = APIRouter()


# ── Existing endpoints ────────────────────────────────────────────────────────

@router.post("/reservations", response_model=StockReservationRead, status_code=201)
def create_reservation(
    reservation_in: StockReservationCreate,
    db: Session = Depends(get_db),
):
    return crud.create_reservation(db=db, obj_in=reservation_in)


@router.post("/analyze", response_model=DistintaAnalysisResult)
def analyze_distinta(
    req: DistintaAnalysisRequest,
    db: Session = Depends(get_db),
):
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
            profilo=normalize_profile(item.profilo),
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

    sfrido_values = [r["sfrido_pct"] for r in results if r.get("sfrido_pct") is not None]
    sfrido_totale = sum(sfrido_values) / len(sfrido_values) if sfrido_values else 0.0

    return DistintaAnalysisResult(
        cutting_plans=results,
        sfrido_totale_percentuale=round(sfrido_totale, 2),
        warning_sfrido=sfrido_totale > 20.0,
    )


# ── Material request schemas ──────────────────────────────────────────────────

class MaterialRequestCreate(BaseModel):
    commessa_id: int
    commessa_codice: Optional[str] = None
    material_id: int
    material_description: Optional[str] = None
    material_code: Optional[str] = None
    quantity: float
    movement_type: str = "OUTGOING"
    reason: Optional[str] = None
    reference: Optional[str] = None


class MaterialRequestRead(BaseModel):
    id: int
    commessa_id: int
    commessa_codice: Optional[str]
    material_id: int
    material_description: Optional[str]
    material_code: Optional[str]
    quantity: float
    movement_type: str
    reason: Optional[str]
    status: str
    note_rifiuto: Optional[str]
    created_at: datetime

    model_config = {"from_attributes": True}


class RefuseBody(BaseModel):
    note: str


# ── Material request endpoints ────────────────────────────────────────────────

@router.post("/requests", response_model=MaterialRequestRead, status_code=201)
def create_request(req: MaterialRequestCreate, db: Session = Depends(get_db)):
    mat = db.get(Material, req.material_id)
    obj = MaterialRequest(
        commessa_id=req.commessa_id,
        commessa_codice=req.commessa_codice,
        material_id=req.material_id,
        material_description=req.material_description or (mat.description if mat else None),
        material_code=req.material_code or (mat.code if mat else None),
        quantity=req.quantity,
        movement_type=req.movement_type,
        reason=req.reason,
        reference=req.reference,
        status=RichiestaStatus.IN_ATTESA,
    )
    db.add(obj)
    db.commit()
    db.refresh(obj)
    _logger.info("Richiesta prelievo creata: commessa=%s mat=%s qty=%s", req.commessa_codice, req.material_id, req.quantity)
    return obj


@router.get("/requests", response_model=List[MaterialRequestRead])
def list_requests(
    status: Optional[str] = None,
    commessa_id: Optional[int] = None,
    db: Session = Depends(get_db),
):
    q = db.query(MaterialRequest)
    if status:
        try:
            q = q.filter(MaterialRequest.status == RichiestaStatus(status))
        except ValueError:
            raise HTTPException(400, f"Status non valido: {status}")
    if commessa_id:
        q = q.filter(MaterialRequest.commessa_id == commessa_id)
    return q.order_by(MaterialRequest.created_at.desc()).all()


@router.post("/requests/{req_id}/confirm", response_model=MaterialRequestRead)
def confirm_request(req_id: int, db: Session = Depends(get_db)):
    req = db.get(MaterialRequest, req_id)
    if not req:
        raise HTTPException(404, "Richiesta non trovata")
    if req.status != RichiestaStatus.IN_ATTESA:
        raise HTTPException(409, f"Richiesta già in stato {req.status.value}")

    try:
        mv_type = MovementType(req.movement_type)
    except ValueError:
        mv_type = MovementType.OUTGOING

    movement = StockMovement(
        material_id=req.material_id,
        quantity=req.quantity,
        movement_type=mv_type,
        reason=req.reason or f"Prelievo confermato — commessa {req.commessa_codice}",
        destination_commessa=req.commessa_codice,
        commessa_id=req.commessa_id,
        reference=req.reference,
    )
    db.add(movement)

    req.status = RichiestaStatus.CONFERMATO
    req.confirmed_at = datetime.utcnow()
    db.commit()
    db.refresh(req)
    _logger.info("Richiesta %d confermata → movimento creato", req_id)
    return req


@router.post("/requests/{req_id}/refuse", response_model=MaterialRequestRead)
def refuse_request(req_id: int, body: RefuseBody, db: Session = Depends(get_db)):
    req = db.get(MaterialRequest, req_id)
    if not req:
        raise HTTPException(404, "Richiesta non trovata")
    if req.status != RichiestaStatus.IN_ATTESA:
        raise HTTPException(409, f"Richiesta già in stato {req.status.value}")
    if not body.note or not body.note.strip():
        raise HTTPException(400, "Note obbligatorie per il rifiuto")

    req.status = RichiestaStatus.RIFIUTATO
    req.note_rifiuto = body.note.strip()
    db.commit()
    db.refresh(req)
    _logger.info("Richiesta %d rifiutata: %s", req_id, body.note)
    return req


@router.delete("/requests/{req_id}", status_code=204)
def delete_request(req_id: int, db: Session = Depends(get_db)):
    req = db.get(MaterialRequest, req_id)
    if not req:
        raise HTTPException(404, "Richiesta non trovata")
    db.delete(req)
    db.commit()
