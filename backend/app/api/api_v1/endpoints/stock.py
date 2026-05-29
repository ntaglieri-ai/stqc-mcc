"""Stock reservations, cutting-stock analysis, and material request endpoints."""
from __future__ import annotations

import logging
import re
from collections import defaultdict
from datetime import datetime
from pathlib import Path
from typing import Any, List, Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, model_validator
from sqlalchemy import or_
from sqlalchemy.orm import Session

from backend.app.crud import stock as crud
from backend.app.crud.warehouse import get_magazzino_list
from backend.app.db.session import get_db
from backend.app.models.warehouse import (
    DistintaItem,
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
from backend.app.services.cutting_stock import analyze_material, ffd_1d
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


# ── Compare distinta vs magazzino ────────────────────────────────────────────

class DistintaCompareItem(BaseModel):
    profilo: str
    length_mm: Optional[float] = None
    qty: int = 1
    qualita: Optional[str] = None


class DistintaCompareRequest(BaseModel):
    commessa_id: Optional[int] = None
    import_id: Optional[int] = None
    items: Optional[List[DistintaCompareItem]] = None

    @model_validator(mode="after")
    def _at_least_one_source(self) -> "DistintaCompareRequest":
        if not self.commessa_id and not self.import_id and not self.items:
            raise ValueError("Fornire commessa_id, import_id o items")
        return self


class ProfileCompareResult(BaseModel):
    profilo_norm: str
    profilo_raw: str
    n_pezzi_richiesti: int
    mm_richiesti: float
    mm_disponibili: float
    stato: str                          # disponibile | parziale | mancante | nd
    sfrido_pct: Optional[float] = None
    barre_necessarie: Optional[int] = None
    inventory_rows: List[Any] = []


class DistintaCompareResult(BaseModel):
    profiles: List[ProfileCompareResult]
    inventory_source: str               # xlsm | db
    n_disponibili: int
    n_parziali: int
    n_mancanti: int
    n_nd: int                           # profili senza mm (lamiere, pezzi 0D)


def _parse_dim_linear(dimensioni: Any) -> float | None:
    """Restituisce la lunghezza in mm se è un profilato lineare, None altrimenti.
    Lineare = dimensioni è un numero o una stringa numerica pura (es. 12100, '6000').
    NON lineare = '3000*1500', None, stringa mista.
    """
    if dimensioni is None:
        return None
    s = str(dimensioni).strip()
    if '*' in s or 'x' in s.lower():
        return None
    try:
        v = float(s)
        return v if v > 0 else None
    except ValueError:
        return None


def _load_inventory_xlsm() -> tuple[list[dict], str] | None:
    """Cerca INVENTARIO*.xlsm nella directory di lavoro.
    Restituisce (rows, path_str) oppure None se non trovato.
    """
    from backend.app.services.inventario import parse_inventario
    candidates = sorted(Path(".").glob("INVENTARIO*.xlsm"))
    if not candidates:
        return None
    path = candidates[-1]           # usa la versione più recente (alfabeticamente)
    try:
        rows = parse_inventario(path)
        return rows, str(path)
    except Exception as exc:
        _logger.warning("Impossibile leggere inventario XLSM %s: %s", path, exc)
        return None


def _inventory_index(rows: list[dict]) -> dict[str, list[dict]]:
    """Costruisce indice {profilo_normalizzato → [righe]} dall'inventario."""
    idx: dict[str, list[dict]] = defaultdict(list)
    for r in rows:
        # Profilo può essere stringa o numero (lamiere con spessore numerico)
        raw = r.get("profilo")
        if raw is None:
            continue
        norm = normalize_profile(str(raw))
        idx[norm].append(r)
    return idx


def _compute_mm_disponibili(inv_rows: list[dict]) -> float:
    """Somma mm lineari disponibili: n_pezzi × dim_mm (solo righe lineari)."""
    total = 0.0
    for r in inv_rows:
        n = float(r.get("quantity") or r.get("n_pezzi") or 0)
        dim = _parse_dim_linear(r.get("dimensioni"))
        if dim and n > 0:
            total += n * dim
    return total


def _dominant_bar_length(inv_rows: list[dict]) -> float | None:
    """Lunghezza barra più comune tra le righe lineari dell'inventario."""
    from collections import Counter
    lengths = []
    for r in inv_rows:
        dim = _parse_dim_linear(r.get("dimensioni"))
        if dim:
            n = int(max(1, round(float(r.get("quantity") or r.get("n_pezzi") or 1))))
            lengths.extend([dim] * n)
    if not lengths:
        return None
    return Counter(lengths).most_common(1)[0][0]


def _compute_sfrido(piece_lengths_mm: list[float], bar_length_mm: float) -> tuple[float, int]:
    """Esegue FFD 1D e restituisce (sfrido_pct, n_barre_necessarie)."""
    if not piece_lengths_mm or not bar_length_mm:
        return 0.0, 0
    feasible = [p for p in piece_lengths_mm if p <= bar_length_mm]
    if not feasible:
        return 0.0, 0
    bins = ffd_1d(feasible, bar_length_mm)
    n_barre = len(bins)
    totale = n_barre * bar_length_mm
    usato = sum(p for b in bins for p in b.pieces)
    sfrido = (totale - usato) / totale * 100 if totale > 0 else 0.0
    return round(sfrido, 2), n_barre


@router.post("/compare-distinta", response_model=DistintaCompareResult)
def compare_distinta_magazzino(
    req: DistintaCompareRequest,
    db: Session = Depends(get_db),
):
    """Confronta i profili della distinta con il magazzino disponibile.

    Carica l'inventario dal file XLSM se presente nella directory di lavoro,
    altrimenti usa i dati in DB. Per ogni profilo normalizzato:
    - Somma i mm richiesti (n_pezzi × length_mm)
    - Calcola i mm disponibili in magazzino (n_barre × dim_barra)
    - Determina stato: disponibile / parziale / mancante / nd
    - Calcola sfrido FFD 1D per profilati lineari
    """
    # ── 1. Carica inventario ──────────────────────────────────────────────────
    inv_source = "db"
    xlsm_result = _load_inventory_xlsm()
    if xlsm_result:
        inv_rows, xlsm_path = xlsm_result
        inv_source = f"xlsm:{xlsm_path}"
        _logger.info("Inventario da XLSM: %s (%d righe)", xlsm_path, len(inv_rows))
    else:
        raw_db = get_magazzino_list(db=db, limit=10_000)
        # Normalizza il formato: get_magazzino_list usa 'n_pezzi', parse_inventario usa 'quantity'
        inv_rows = [{**r, "quantity": r["n_pezzi"]} for r in raw_db]
        _logger.info("Inventario da DB: %d righe", len(inv_rows))

    inv_idx = _inventory_index(inv_rows)

    # ── 2. Carica pezzi distinta ──────────────────────────────────────────────
    items_raw: list[DistintaCompareItem] = []

    if req.items:
        items_raw = req.items
    elif req.import_id:
        db_items = db.query(DistintaItem).filter(
            DistintaItem.import_id == req.import_id,
            DistintaItem.invalidato.is_(False),
        ).all()
        items_raw = [
            DistintaCompareItem(
                profilo=it.description or "",
                length_mm=float(it.length_mm) if it.length_mm else None,
                qty=1,
                qualita=it.material_code,
            )
            for it in db_items if it.description
        ]
    elif req.commessa_id:
        from backend.app.models.commessa import Commessa
        commessa = db.get(Commessa, req.commessa_id)
        codice = commessa.codice if commessa else None
        db_items = db.query(DistintaItem).filter(
            or_(
                DistintaItem.commessa_id == req.commessa_id,
                DistintaItem.commessa_reference == codice,
            ),
            DistintaItem.invalidato.is_(False),
        ).all()
        items_raw = [
            DistintaCompareItem(
                profilo=it.description or "",
                length_mm=float(it.length_mm) if it.length_mm else None,
                qty=1,
                qualita=it.material_code,
            )
            for it in db_items if it.description
        ]

    if not items_raw:
        raise HTTPException(422, "Nessun pezzo trovato per il confronto")

    # ── 3. Aggrega distinta per profilo normalizzato ──────────────────────────
    # {profilo_norm: {raw, n_pezzi, mm_tot, lunghezze_mm}}
    agg: dict[str, dict] = {}
    for it in items_raw:
        norm = normalize_profile(it.profilo)
        if not norm:
            continue
        if norm not in agg:
            agg[norm] = {"profilo_raw": it.profilo, "n_pezzi": 0, "mm_tot": 0.0, "lunghezze": []}
        agg[norm]["n_pezzi"] += it.qty
        if it.length_mm and it.length_mm > 0:
            agg[norm]["mm_tot"] += it.length_mm * it.qty
            agg[norm]["lunghezze"].extend([it.length_mm] * it.qty)

    # ── 4. Confronta profilo per profilo ─────────────────────────────────────
    results: list[ProfileCompareResult] = []

    for norm, data in sorted(agg.items()):
        matching_inv = inv_idx.get(norm, [])
        mm_req  = data["mm_tot"]
        mm_disp = _compute_mm_disponibili(matching_inv)

        # Profili senza lunghezze richieste (lamiere, pezzi singoli) → nd
        if mm_req == 0:
            stato = "nd"
            sfrido_pct = None
            n_barre = None
        elif mm_disp == 0:
            stato = "mancante"
            sfrido_pct = None
            n_barre = None
        elif mm_disp >= mm_req:
            stato = "disponibile"
            bar_len = _dominant_bar_length(matching_inv)
            if bar_len:
                sfrido_pct, n_barre = _compute_sfrido(data["lunghezze"], bar_len)
            else:
                sfrido_pct, n_barre = None, None
        else:
            stato = "parziale"
            bar_len = _dominant_bar_length(matching_inv)
            if bar_len:
                sfrido_pct, n_barre = _compute_sfrido(data["lunghezze"], bar_len)
            else:
                sfrido_pct, n_barre = None, None

        inv_summary = [
            {
                "profilo": r.get("profilo"),
                "n_pezzi": r.get("quantity") or r.get("n_pezzi"),
                "dim_mm": _parse_dim_linear(r.get("dimensioni")),
                "dimensioni_raw": r.get("dimensioni"),
                "qualita": r.get("qualita"),
            }
            for r in matching_inv
        ]

        results.append(ProfileCompareResult(
            profilo_norm=norm,
            profilo_raw=data["profilo_raw"],
            n_pezzi_richiesti=data["n_pezzi"],
            mm_richiesti=round(mm_req, 1),
            mm_disponibili=round(mm_disp, 1),
            stato=stato,
            sfrido_pct=sfrido_pct,
            barre_necessarie=n_barre,
            inventory_rows=inv_summary,
        ))

    # ── 5. Sommario ───────────────────────────────────────────────────────────
    stati = [r.stato for r in results]
    return DistintaCompareResult(
        profiles=results,
        inventory_source=inv_source,
        n_disponibili=stati.count("disponibile"),
        n_parziali=stati.count("parziale"),
        n_mancanti=stati.count("mancante"),
        n_nd=stati.count("nd"),
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
