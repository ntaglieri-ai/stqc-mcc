"""Cutting Stock optimization — FFD per 1D, 2D, 0D, kg."""
from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Optional


# ── helpers ─────────────────────────────────────────────────────────────────

def _to_float(val) -> Optional[float]:
    if val is None:
        return None
    try:
        return float(str(val).strip())
    except (ValueError, TypeError):
        return None


def _det_type(unita: str, dim1: Optional[float], dim2: Optional[float]) -> str:
    u = (unita or "pz").lower()
    if u in ("m2",) or (dim1 and dim2):
        return "2d"
    if u in ("ml", "m") or (dim1 and not dim2):
        return "1d"
    if u == "kg":
        return "kg"
    return "0d"


# ── 1D FFD ──────────────────────────────────────────────────────────────────

@dataclass
class Bin1D:
    bar_length: float
    remaining: float
    pieces: list = field(default_factory=list)


def ffd_1d(piece_lengths: list[float], bar_length: float) -> list[Bin1D]:
    bins: list[Bin1D] = []
    for p in sorted(piece_lengths, reverse=True):
        placed = False
        for b in bins:
            if b.remaining >= p - 1e-6:
                b.remaining -= p
                b.pieces.append(p)
                placed = True
                break
        if not placed:
            bins.append(Bin1D(bar_length=bar_length, remaining=bar_length - p, pieces=[p]))
    return bins


def _analyze_1d(
    profilo: str,
    qualita: Optional[str],
    pieces_mm: list[float],
    bar_length: float,
    n_available: float,
) -> dict:
    # Pieces longer than bar cannot be cut — mark them as oversized
    feasible = [p for p in pieces_mm if p <= bar_length]
    oversized = len(pieces_mm) - len(feasible)

    if not feasible:
        return {
            "profilo": profilo, "qualita": qualita, "dimensione_type": "1d",
            "bar_length_mm": bar_length, "n_bars_available": n_available,
            "n_bars_needed": 0, "sfrido_mm": 0.0, "sfrido_pct": 0.0,
            "pezzi_per_barra": [], "stato": "missing" if oversized else "ok",
            "note": f"{oversized} pezzi più lunghi della barra" if oversized else None,
        }

    bins = ffd_1d(feasible, bar_length)
    n_needed = len(bins)
    total_consumed = n_needed * bar_length
    total_used = sum(p for b in bins for p in b.pieces)
    sfrido = total_consumed - total_used
    sfrido_pct = sfrido / total_consumed * 100 if total_consumed > 0 else 0.0

    return {
        "profilo": profilo, "qualita": qualita, "dimensione_type": "1d",
        "bar_length_mm": bar_length, "n_bars_available": n_available,
        "n_bars_needed": n_needed,
        "sfrido_mm": round(sfrido, 2),
        "sfrido_pct": round(sfrido_pct, 2),
        "pezzi_per_barra": [b.pieces for b in bins],
        "stato": "ok" if n_available >= n_needed else "partial",
        "note": f"{oversized} pezzi sovradimensionati esclusi" if oversized else None,
    }


# ── 2D FFD (shelf packing) ───────────────────────────────────────────────────

@dataclass
class Shelf:
    height: float
    remaining_width: float
    pieces: list = field(default_factory=list)


@dataclass
class Sheet2D:
    w: float
    h: float
    shelves: list[Shelf] = field(default_factory=list)

    @property
    def used_height(self) -> float:
        return sum(s.height for s in self.shelves)


def ffd_2d(pieces: list[tuple[float, float]], sw: float, sh: float) -> list[Sheet2D]:
    sheets: list[Sheet2D] = []
    for pw, ph in sorted(pieces, key=lambda p: p[1], reverse=True):
        placed = False
        for sheet in sheets:
            for shelf in sheet.shelves:
                if shelf.remaining_width >= pw - 1e-6 and shelf.height >= ph - 1e-6:
                    shelf.remaining_width -= pw
                    shelf.pieces.append((pw, ph))
                    placed = True
                    break
            if placed:
                break
            rem_h = sh - sheet.used_height
            if rem_h >= ph - 1e-6:
                shelf = Shelf(height=ph, remaining_width=sw - pw, pieces=[(pw, ph)])
                sheet.shelves.append(shelf)
                placed = True
                break
        if not placed:
            shelf = Shelf(height=ph, remaining_width=sw - pw, pieces=[(pw, ph)])
            sheets.append(Sheet2D(w=sw, h=sh, shelves=[shelf]))
    return sheets


def _analyze_2d(
    profilo: str,
    qualita: Optional[str],
    pieces: list[tuple[float, float]],
    sw: float, sh: float,
    n_available: float,
) -> dict:
    feasible = [(pw, ph) for pw, ph in pieces if pw <= sw and ph <= sh]
    oversized = len(pieces) - len(feasible)

    sheets = ffd_2d(feasible, sw, sh)
    n_needed = len(sheets)
    total_area = n_needed * sw * sh
    used_area = sum(pw * ph for s in sheets for shelf in s.shelves for pw, ph in shelf.pieces)
    sfrido_area = total_area - used_area
    sfrido_pct = sfrido_area / total_area * 100 if total_area > 0 else 0.0

    pezzi_per_foglio = [
        [[pw, ph] for shelf in s.shelves for pw, ph in shelf.pieces]
        for s in sheets
    ]

    return {
        "profilo": profilo, "qualita": qualita, "dimensione_type": "2d",
        "sheet_dim1_mm": sw, "sheet_dim2_mm": sh,
        "n_sheets_available": n_available, "n_sheets_needed": n_needed,
        "sfrido_mm2": round(sfrido_area, 2),
        "sfrido_pct": round(sfrido_pct, 2),
        "pezzi_per_foglio": pezzi_per_foglio,
        "stato": "ok" if n_available >= n_needed else "partial",
        "note": f"{oversized} pezzi sovradimensionati esclusi" if oversized else None,
    }


# ── 0D (pz) ─────────────────────────────────────────────────────────────────

def _analyze_0d(profilo: str, qualita: Optional[str], n_required: int, n_available: float) -> dict:
    return {
        "profilo": profilo, "qualita": qualita, "dimensione_type": "0d",
        "n_required": n_required, "n_available": n_available,
        "sfrido_pct": 0.0,
        "stato": "ok" if n_available >= n_required else "partial",
    }


# ── kg ───────────────────────────────────────────────────────────────────────

def _analyze_kg(
    profilo: str,
    qualita: Optional[str],
    n_required: int,
    peso_1_pz: Optional[float],
    peso_kg_available: Optional[float],
) -> dict:
    req_kg = (peso_1_pz or 0) * n_required
    avail_kg = peso_kg_available or 0
    sfrido_pct = 0.0
    return {
        "profilo": profilo, "qualita": qualita, "dimensione_type": "kg",
        "required_kg": round(req_kg, 3), "available_kg": round(avail_kg, 3),
        "sfrido_pct": sfrido_pct,
        "stato": "ok" if avail_kg >= req_kg else "partial",
    }


# ── public entry point ───────────────────────────────────────────────────────

def analyze_material(
    profilo: str,
    qualita: Optional[str],
    required_pieces: list[dict],
    stock_item: dict,
) -> dict:
    """Run cutting-stock analysis for one material.

    required_pieces: [{"length_mm": float|None, "width_mm": float|None, "quantity": int}]
    stock_item: MagazzinoItemRead-compatible dict
    """
    unita     = (stock_item.get("unita_misura") or "pz").lower()
    dim1      = _to_float(stock_item.get("dimensioni"))
    dim2      = _to_float(stock_item.get("dimensione_2"))
    n_avail   = float(stock_item.get("n_pezzi") or 0)
    peso_1_pz = _to_float(stock_item.get("peso_1_pz"))
    peso_kg   = _to_float(stock_item.get("peso_kg"))

    dim_type  = _det_type(unita, dim1, dim2)

    # Flatten pieces
    flat: list[tuple[Optional[float], Optional[float]]] = []
    for p in required_pieces:
        qty = max(1, int(p.get("quantity") or 1))
        l   = _to_float(p.get("length_mm"))
        w   = _to_float(p.get("width_mm"))
        flat.extend([(l, w)] * qty)

    n_required = len(flat)

    if dim_type == "1d":
        lengths = [p[0] for p in flat if p[0] is not None]
        if not lengths or not dim1:
            return _analyze_0d(profilo, qualita, n_required, n_avail)
        return _analyze_1d(profilo, qualita, lengths, dim1, n_avail)

    if dim_type == "2d":
        dims = [(p[0] or 0, p[1] or 0) for p in flat]
        if not dims or not dim1 or not dim2:
            return _analyze_0d(profilo, qualita, n_required, n_avail)
        return _analyze_2d(profilo, qualita, dims, dim1, dim2, n_avail)

    if dim_type == "kg":
        return _analyze_kg(profilo, qualita, n_required, peso_1_pz, peso_kg)

    return _analyze_0d(profilo, qualita, n_required, n_avail)
