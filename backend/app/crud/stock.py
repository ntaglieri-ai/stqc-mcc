"""CRUD for stock reservations and cutting plans."""
from __future__ import annotations

import json

from sqlalchemy.orm import Session

from backend.app.models.warehouse import (
    CuttingPlan,
    Material,
    MovementType,
    StockMovement,
    StockReservation,
    TipoMovimentoRiserva,
)
from backend.app.schemas.warehouse import StockReservationCreate


def create_reservation(db: Session, obj_in: StockReservationCreate) -> StockReservation:
    data = obj_in.model_dump()
    reservation = StockReservation(**data)
    db.add(reservation)

    material: Material | None = db.get(Material, obj_in.material_id)
    if material is not None:
        tipo = obj_in.tipo_movimento
        qty  = float(obj_in.quantita)

        if tipo == TipoMovimentoRiserva.PRENOTAZIONE:
            material.quantita_prenotata = float(material.quantita_prenotata or 0) + qty

        elif tipo == TipoMovimentoRiserva.CONFERMA_USCITA:
            material.quantita_prenotata = max(0.0, float(material.quantita_prenotata or 0) - qty)
            material.quantita_uscita    = float(material.quantita_uscita or 0) + qty

        elif tipo == TipoMovimentoRiserva.RIENTRO_SFRIDO:
            note = obj_in.note or f"Rientro sfrido commessa {obj_in.commessa_id}"
            sm = StockMovement(
                material_id=obj_in.material_id,
                quantity=qty,
                movement_type=MovementType.INCOMING,
                reason=note,
                commessa_id=obj_in.commessa_id,
            )
            db.add(sm)

    db.commit()
    db.refresh(reservation)
    return reservation


def create_cutting_plan(
    db: Session,
    commessa_id: int,
    material_id: int,
    plan_data: dict,
) -> CuttingPlan:
    pezzi_json = plan_data.get("pezzi_per_barra") or plan_data.get("pezzi_per_foglio")
    cp = CuttingPlan(
        commessa_id=commessa_id,
        material_id=material_id,
        pezzi_ricavati=json.dumps(pezzi_json) if pezzi_json is not None else None,
        sfrido_dim1=plan_data.get("sfrido_mm"),
        sfrido_dim2=plan_data.get("sfrido_mm2"),
        sfrido_percentuale=plan_data.get("sfrido_pct"),
    )
    db.add(cp)
    db.commit()
    db.refresh(cp)
    return cp
