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
    ProfileAlias,
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


# ── Compare distinta vs magazzino ────────────────────────────────────────────

# Tipi lineari: confronto su lunghezza barra
_TIPI_LINEARI = {"TRAVI", "SCATOLATI/ANGOLARI", "PIATTI", "TONDO", "QUADRI"}


class DistintaCompareItem(BaseModel):
    profilo: str
    length_mm: Optional[float] = None
    qty: int = 1
    qualita: Optional[str] = None
    tipo_profilo: Optional[str] = None


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
    """Una riga nel risultato: un profilo specifico con qualità, aggregato su tutti i pezzi fisici."""
    profilo_norm: str
    qualita: Optional[str] = None
    tipo_profilo: str = "SCONOSCIUTO"
    n_pezzi_richiesti: int
    n_pezzi_coperti: int = 0
    n_pezzi_mancanti: int = 0
    dim_richieste: float = 0.0     # mm lineari | mm² LAMIERA — tutti i pezzi
    dim_coperti: float = 0.0       # mm lineari | mm² — solo pezzi coperti
    dim_consumate: float = 0.0     # mm/mm² elementi inventario usati (solo pezzi coperti)
    stato: str                      # disponibile | parziale | mancante | nd
    sfrido_pct: Optional[float] = None   # (dim_consumate − dim_coperti) / dim_consumate


class DistintaCompareResult(BaseModel):
    profiles: List[ProfileCompareResult]
    inventory_source: str
    n_disponibili: int
    n_parziali: int
    n_mancanti: int
    n_nd: int


def _parse_dim_linear(dimensioni: Any) -> float | None:
    """Lunghezza barra in mm (solo se dimensioni è un numero scalare, es. 12100).
    Restituisce None per dimensioni 2D come '3000*1500'.
    """
    if dimensioni is None:
        return None
    s = str(dimensioni).strip()
    if re.search(r'[*xX×]', s):
        return None
    try:
        v = float(s)
        return v if v > 0 else None
    except ValueError:
        return None


def _parse_sheet_dims(dimensioni: Any) -> tuple[float, float] | None:
    """Parsa dimensioni 2D: '3000*1500' → (3000.0, 1500.0).
    Accetta separatori *, x, X, ×.
    """
    if not dimensioni:
        return None
    parts = re.split(r'[*xX×]', str(dimensioni).strip())
    if len(parts) >= 2:
        try:
            d1, d2 = float(parts[0].strip()), float(parts[1].strip())
            return (d1, d2) if d1 > 0 and d2 > 0 else None
        except (ValueError, TypeError):
            pass
    return None


def _parse_plate_width(profile_norm: str) -> float | None:
    """Estrae la larghezza da un profilo lamiera normalizzato.
    'PL10*140' → 140.0   (spessore*larghezza)
    Restituisce None se il profilo non segue il formato PL<spessore>*<larghezza>.
    """
    m = re.match(r'^PL\d+(?:\.\d+)?\*(\d+(?:\.\d+)?)', profile_norm.upper())
    return float(m.group(1)) if m else None


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


def _inventory_pool_by_profile(inv_rows: list[dict]) -> dict[str, list[dict]]:
    """Raggruppa inventario per profilo normalizzato.

    Match industriale corretto:
        HEB240 → solo HEB240
        IPE270 → solo IPE270
    """
    pool: dict[str, list[dict]] = defaultdict(list)
    for r in inv_rows:
        profilo = normalize_profile(r.get("profilo") or "")
        if profilo:
            pool[profilo].append(r)
    return pool


def _match_linear_per_piece(
    pieces: list[tuple],      # (profilo_norm, qualita, length_mm)
    inv_rows: list[dict],
) -> list[dict]:
    """Greedy per-piece: abbina ogni pezzo lineare a una barra del pool inventario.

    Ogni elemento restituito:
        profilo_norm, qualita, length_mm, covered (bool), bar_mm (float|None)

    covered=True  → pezzo assegnato a una barra (bar_mm = lunghezza barra usata)
    covered=False → nessuna barra disponibile con lunghezza ≥ richiesta
    Sfrido = 0 sui pezzi mancanti (non consumano barre).
    """
    bar_pool: dict[float, int] = {}
    for r in inv_rows:
        dim = _parse_dim_linear(r.get("dimensioni"))
        n   = int(float(r.get("quantity") or r.get("n_pezzi") or 0))
        if dim and n > 0:
            bar_pool[dim] = bar_pool.get(dim, 0) + n

    available = dict(bar_pool)
    # Ordina per lunghezza decrescente — prima i pezzi più difficili da soddisfare
    sorted_pieces = sorted(pieces, key=lambda x: x[2], reverse=True)
    results = []

    for prof, qual, lmm in sorted_pieces:
        fitting = [(blen, cnt) for blen, cnt in available.items()
                   if blen >= lmm and cnt > 0]
        if fitting:
            best = min(fitting, key=lambda x: x[0])
            available[best[0]] -= 1
            results.append({"profilo_norm": prof, "qualita": qual,
                             "length_mm": lmm, "covered": True, "bar_mm": best[0]})
        else:
            results.append({"profilo_norm": prof, "qualita": qual,
                             "length_mm": lmm, "covered": False, "bar_mm": None})
    return results


def _match_plate_per_piece(
    pieces: list[tuple],      # (profilo_norm, qualita, length_mm, width_mm)
    inv_rows: list[dict],
) -> list[dict]:
    """Greedy per-piece: abbina ogni lamiera a un foglio del pool inventario."""
    sheet_pool: dict[tuple[float, float], int] = {}
    for r in inv_rows:
        dims = _parse_sheet_dims(r.get("dimensioni"))
        n    = int(float(r.get("quantity") or r.get("n_pezzi") or 0))
        if dims and n > 0:
            key = (max(dims), min(dims))
            sheet_pool[key] = sheet_pool.get(key, 0) + n

    available = dict(sheet_pool)
    sorted_pieces = sorted(pieces, key=lambda x: x[2] * x[3], reverse=True)
    results = []

    for prof, qual, lmm, wmm in sorted_pieces:
        p_max, p_min = max(lmm, wmm), min(lmm, wmm)
        fitting = [(sdims, cnt) for sdims, cnt in available.items()
                   if sdims[0] >= p_max and sdims[1] >= p_min and cnt > 0]
        if fitting:
            best = min(fitting, key=lambda x: x[0][0] * x[0][1])
            available[best[0]] -= 1
            results.append({"profilo_norm": prof, "qualita": qual,
                             "lmm": lmm, "wmm": wmm,
                             "covered": True, "sheet_area": best[0][0] * best[0][1]})
        else:
            results.append({"profilo_norm": prof, "qualita": qual,
                             "lmm": lmm, "wmm": wmm,
                             "covered": False, "sheet_area": None})
    return results


def _aggregate_per_profile(
    piece_results: list[dict],
    tipo: str,
    is_lamiera: bool = False,
) -> list[ProfileCompareResult]:
    """Aggrega i risultati per-pezzo in righe per (profilo_norm, qualita).

    Sfrido calcolato SOLO sui pezzi coperti:
        sfrido = (dim_consumate − dim_coperti) / dim_consumate × 100
    I pezzi mancanti non consumano barre → sfrido_pct = None se tutti mancanti.
    """
    from collections import defaultdict
    buckets: dict[tuple, dict] = defaultdict(lambda: {
        "n_richiesti": 0, "n_coperti": 0, "n_mancanti": 0,
        "dim_richieste": 0.0, "dim_coperti": 0.0, "dim_consumate": 0.0,
    })

    for r in piece_results:
        key = (r["profilo_norm"], r.get("qualita") or "")
        b = buckets[key]
        b["n_richiesti"] += 1
        if is_lamiera:
            b["dim_richieste"] += r["lmm"] * r["wmm"]
            if r["covered"]:
                b["n_coperti"]    += 1
                b["dim_coperti"]  += r["lmm"] * r["wmm"]
                b["dim_consumate"] += r["sheet_area"]
            else:
                b["n_mancanti"] += 1
        else:
            b["dim_richieste"] += r["length_mm"]
            if r["covered"]:
                b["n_coperti"]    += 1
                b["dim_coperti"]  += r["length_mm"]
                b["dim_consumate"] += r["bar_mm"]
            else:
                b["n_mancanti"] += 1

    out = []
    for (prof, qual), b in sorted(buckets.items()):
        dc = b["dim_consumate"]
        dp = b["dim_coperti"]
        sfrido = round((dc - dp) / dc * 100, 2) if dc > 0 else None
        n_cop, n_man = b["n_coperti"], b["n_mancanti"]
        if n_man == 0:
            stato = "disponibile"
        elif n_cop == 0:
            stato = "mancante"
        else:
            stato = "parziale"
        out.append(ProfileCompareResult(
            profilo_norm=prof,
            qualita=qual or None,
            tipo_profilo=tipo,
            n_pezzi_richiesti=b["n_richiesti"],
            n_pezzi_coperti=n_cop,
            n_pezzi_mancanti=n_man,
            dim_richieste=round(b["dim_richieste"], 1),
            dim_coperti=round(dp, 1),
            dim_consumate=round(dc, 1),
            stato=stato,
            sfrido_pct=sfrido,
        ))
    return out


def _stato_from_match(match: dict) -> str:
    n_cop = match["n_coperti"]
    n_man = match["n_mancanti"]
    if n_man == 0:
        return "disponibile"
    if n_cop == 0:
        return "mancante"
    return "parziale"


@router.post("/compare-distinta")
def compare_distinta_magazzino(
    req: DistintaCompareRequest,
    db: Session = Depends(get_db),
):
    """Compare distinta vs magazzino in 5 step.

    Step 1 — diagnostico per pezzo: tipo_profilo + presenza tipo in materials.
    Step 2 — mapping profili: normalizza e allinea profili distinta ↔ magazzino per tipo;
              auto-mappa dove c'è corrispondenza esatta, inserisce i non mappati in
              profile_aliases (profilo_magazzino=NULL) per associazione manuale.
    Step 3 — match dimensionale greedy: per ogni pezzo usa il mapping di step 2,
              cerca nel pool del profilo magazzino corrispondente una barra/foglio
              con dimensioni >= distinta_items.length_mm; non somma mai.
    Step 4 — risultato per pezzo: disponibile | mancante | non_mappato.
    Step 5 — aggregato per (tipo, profilo_distinta): conta disponibili e mancanti.
    """
    # ── Carica DistintaItem della commessa/import ─────────────────────────────
    if req.import_id:
        db_items = db.query(DistintaItem).filter(
            DistintaItem.import_id == req.import_id,
            DistintaItem.invalidato.is_(False),
        ).all()
    elif req.commessa_id:
        from backend.app.models.commessa import Commessa
        commessa = db.get(Commessa, req.commessa_id)
        codice   = commessa.codice if commessa else None
        db_items = db.query(DistintaItem).filter(
            or_(
                DistintaItem.commessa_id == req.commessa_id,
                DistintaItem.commessa_reference == codice,
            ),
            DistintaItem.invalidato.is_(False),
        ).all()
    else:
        raise HTTPException(422, "Fornire import_id o commessa_id")

    if not db_items:
        raise HTTPException(422, "Nessun pezzo trovato")

    # ── STEP 1 — diagnostico per pezzo ───────────────────────────────────────
    tipi_in_mag: set[str] = {
        (t or "").upper()
        for (t,) in db.query(Material.tipo).filter(Material.tipo.isnot(None)).distinct().all()
    }
    step1 = [
        {
            "part_number":       it.part_number,
            "profilo":           it.description,
            "tipo":              it.tipo_profilo or "SCONOSCIUTO",
            "tipo_in_magazzino": (it.tipo_profilo or "").upper() in tipi_in_mag,
        }
        for it in db_items if it.description
    ]

    # ── STEP 2 — mapping profili per tipo ─────────────────────────────────────
    # Profili distinta: {tipo → set di profili normalizzati}
    dist_by_tipo: dict[str, set[str]] = {}
    for it in db_items:
        if not it.description:
            continue
        tipo = (it.tipo_profilo or "SCONOSCIUTO").upper()
        norm = normalize_profile(it.description)
        dist_by_tipo.setdefault(tipo, set()).add(norm)

    # Profili magazzino: {tipo → {norm_profilo → rows}}
    mag_rows_all = db.query(Material).filter(
        Material.tipo.isnot(None),
        Material.profilo.isnot(None),
    ).all()
    mag_by_tipo: dict[str, dict[str, list]] = {}
    for m in mag_rows_all:
        tipo = (m.tipo or "").upper()
        norm = normalize_profile(m.profilo or "")
        if norm:
            mag_by_tipo.setdefault(tipo, {}).setdefault(norm, []).append(m)

    # Upsert profile_aliases: auto-mappa corrispondenze esatte, marca non mappati
    mapping_result = []
    for tipo, dist_profili in sorted(dist_by_tipo.items()):
        mag_profili: set[str] = set(mag_by_tipo.get(tipo, {}).keys())
        for pd in sorted(dist_profili):
            auto_match = pd if pd in mag_profili else None
            row = db.query(ProfileAlias).filter(
                ProfileAlias.tipo == tipo,
                ProfileAlias.profilo_distinta == pd,
            ).first()
            if row is None:
                row = ProfileAlias(
                    tipo=tipo,
                    profilo_distinta=pd,
                    profilo_magazzino=auto_match,
                    mappato=auto_match is not None,
                )
                db.add(row)
            elif not row.mappato and auto_match:
                # Promuove a mappato se ora esiste corrispondenza
                row.profilo_magazzino = auto_match
                row.mappato = True
            mapping_result.append({
                "tipo":              tipo,
                "profilo_distinta":  pd,
                "profilo_magazzino": row.profilo_magazzino if row.mappato else auto_match or row.profilo_magazzino,
                "mappato":           row.mappato or (auto_match is not None),
            })
    db.commit()

    # Alias mappati: {(tipo, profilo_distinta) → profilo_magazzino}
    alias_map: dict[tuple[str, str], str] = {
        (r["tipo"], r["profilo_distinta"]): r["profilo_magazzino"]
        for r in mapping_result
        if r["mappato"] and r["profilo_magazzino"]
    }

    # ── STEP 3 — match dimensionale (pool virtuale per profilo magazzino) ─────
    # Pool: {profilo_mag_norm → {dim_mm → count}}
    virtual_pool: dict[str, dict[float, int]] = {}
    for m in mag_rows_all:
        tipo = (m.tipo or "").upper()
        norm_mag = normalize_profile(m.profilo or "")
        dim = _parse_dim_linear(m.dimensioni)
        if not norm_mag or not dim:
            continue
        # Calcola n_pezzi dal DB magazzino (movimenti)
        from sqlalchemy import func, case as sa_case
        n_res = db.query(
            func.coalesce(func.sum(sa_case(
                (StockMovement.movement_type == MovementType.INCOMING, StockMovement.quantity),
                else_=0,
            )), 0).label("inc"),
            func.coalesce(func.sum(sa_case(
                (StockMovement.movement_type == MovementType.OUTGOING, StockMovement.quantity),
                else_=0,
            )), 0).label("out"),
        ).filter(StockMovement.material_id == m.id).one()
        n = int(float(n_res.inc) - float(n_res.out))
        if n > 0:
            virtual_pool.setdefault(norm_mag, {})
            virtual_pool[norm_mag][dim] = virtual_pool[norm_mag].get(dim, 0) + n

    def _consume_bar(pool: dict[float, int], length_mm: float) -> float | None:
        """Trova e rimuove dal pool la barra più corta >= length_mm. Ritorna dim usata o None."""
        fitting = [(d, c) for d, c in pool.items() if d >= length_mm and c > 0]
        if not fitting:
            return None
        best = min(fitting, key=lambda x: x[0])
        pool[best[0]] -= 1
        return best[0]

    # Step 4 — risultato per pezzo
    step4: list[dict] = []
    for it in db_items:
        if not it.description:
            continue
        tipo      = (it.tipo_profilo or "SCONOSCIUTO").upper()
        norm_dist = normalize_profile(it.description)
        key       = (tipo, norm_dist)
        norm_mag  = alias_map.get(key)
        lmm       = float(it.length_mm) if it.length_mm else None

        if norm_mag is None:
            stato = "non_mappato"
            bar_usata = None
        elif lmm is None:
            stato = "nd"
            bar_usata = None
        else:
            bar_usata = _consume_bar(virtual_pool.get(norm_mag, {}), lmm)
            stato = "disponibile" if bar_usata else "mancante"

        step4.append({
            "part_number":       it.part_number,
            "profilo":           it.description,
            "tipo":              tipo,
            "profilo_magazzino": norm_mag,
            "length_mm":         lmm,
            "stato":             stato,
            "bar_usata_mm":      bar_usata,
        })

    # ── STEP 5 — aggregato per (tipo, profilo_distinta) ───────────────────────
    from collections import Counter
    agg: dict[tuple, Counter] = {}
    for r in step4:
        key = (r["tipo"], r["profilo"], r["profilo_magazzino"])
        agg.setdefault(key, Counter())
        agg[key][r["stato"]] += 1

    step5 = [
        {
            "tipo":              k[0],
            "profilo_distinta":  k[1],
            "profilo_magazzino": k[2],
            "n_disponibili":     c.get("disponibile", 0),
            "n_mancanti":        c.get("mancante", 0),
            "n_non_mappati":     c.get("non_mappato", 0),
            "n_nd":              c.get("nd", 0),
            "stato": (
                "disponibile" if c.get("mancante", 0) == 0 and c.get("non_mappato", 0) == 0
                else "mancante"  if c.get("disponibile", 0) == 0
                else "parziale"
            ),
        }
        for k, c in sorted(agg.items())
    ]

    return {
        "step1_per_pezzo":    step1,
        "step2_mapping":      mapping_result,
        "step4_per_pezzo":    step4,
        "step5_per_profilo":  step5,
    }


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
