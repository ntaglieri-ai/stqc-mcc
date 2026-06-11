"""Analisi read-only della distinta rispetto al magazzino."""
from __future__ import annotations

import re
from collections import defaultdict
from typing import Any

from backend.app.services.distinta import normalize_profile


def _float(value: Any) -> float | None:
    try:
        result = float(str(value).strip())
        return result if result > 0 else None
    except (TypeError, ValueError):
        return None


def _sheet_dimensions(value: Any) -> tuple[float, float] | None:
    if not value:
        return None
    parts = re.split(r"[*xX×]", str(value).strip())
    if len(parts) < 2:
        return None
    d1, d2 = _float(parts[0]), _float(parts[1])
    return (max(d1, d2), min(d1, d2)) if d1 and d2 else None


def _plate_data(profile: str) -> tuple[float, float | None] | None:
    """PL10*139.4 → (spessore 10, larghezza 139.4)."""
    match = re.match(r"^PL(\d+(?:\.\d+)?)(?:[*X](\d+(?:\.\d+)?))?", normalize_profile(profile))
    if not match:
        return None
    return float(match.group(1)), float(match.group(2)) if match.group(2) else None


def _stock_plate_thickness(profile: Any) -> float | None:
    value = str(profile or "").strip().upper().replace(",", ".")
    if not value:
        return None
    if "/" in value:
        left, right = value.split("/", 1)
        try:
            denominator = float(right)
            return float(left) / denominator if denominator else None
        except ValueError:
            return None
    match = re.search(r"\d+(?:\.\d+)?", value)
    return float(match.group()) if match else None


def _same_quality(required: str | None, available: str | None) -> bool:
    if not required:
        return True
    return required.upper().strip() == (available or "").upper().strip()


def _analyze_linear(items: list[Any], stock: list[dict]) -> dict:
    bars: list[dict] = []
    for row in stock:
        length = _float(row.get("dimensioni"))
        quantity = max(0, int(float(row.get("n_pezzi") or 0)))
        if not length:
            continue
        bars.extend(
            {"remaining": length, "original": length, "material_id": row.get("material_id")}
            for _ in range(quantity)
        )

    requested = sorted(
        [float(item.length_mm) for item in items if item.length_mm],
        reverse=True,
    )
    missing_dimensions = len(items) - len(requested)
    covered = 0
    used_indices: set[int] = set()

    for piece in requested:
        fitting = [
            (index, bar["remaining"] - piece)
            for index, bar in enumerate(bars)
            if bar["remaining"] >= piece
        ]
        if not fitting:
            continue
        index, _ = min(fitting, key=lambda pair: pair[1])
        bars[index]["remaining"] -= piece
        used_indices.add(index)
        covered += 1

    consumed = sum(bars[index]["original"] for index in used_indices)
    used = sum(bars[index]["original"] - bars[index]["remaining"] for index in used_indices)
    return {
        "n_richiesti": len(items),
        "n_coperti": covered,
        "n_mancanti": len(items) - covered - missing_dimensions,
        "n_da_verificare": missing_dimensions,
        "dimensione_richiesta": round(sum(requested), 1),
        "dimensione_consumata": round(consumed, 1),
        "sfrido_pct": round((consumed - used) / consumed * 100, 2) if consumed else None,
    }


def _fits_on_sheet(sheet: dict, width: float, height: float) -> bool:
    for pw, ph in ((width, height), (height, width)):
        for shelf in sheet["shelves"]:
            if shelf["height"] >= ph and shelf["remaining"] >= pw:
                shelf["remaining"] -= pw
                return True
        used_height = sum(shelf["height"] for shelf in sheet["shelves"])
        if used_height + ph <= sheet["height"] and pw <= sheet["width"]:
            sheet["shelves"].append({"height": ph, "remaining": sheet["width"] - pw})
            return True
    return False


def _analyze_plates(items: list[Any], stock: list[dict], profile_width: float | None) -> dict:
    sheets: list[dict] = []
    for row in stock:
        dims = _sheet_dimensions(row.get("dimensioni"))
        quantity = max(0, int(float(row.get("n_pezzi") or 0)))
        if not dims:
            continue
        sheets.extend(
            {
                "width": dims[0],
                "height": dims[1],
                "area": dims[0] * dims[1],
                "shelves": [],
                "used": False,
            }
            for _ in range(quantity)
        )

    pieces = []
    missing_dimensions = 0
    for item in items:
        length = _float(item.length_mm)
        width = _float(getattr(item, "width_mm", None)) or profile_width
        if not length or not width:
            missing_dimensions += 1
            continue
        pieces.append((max(length, width), min(length, width)))
    pieces.sort(key=lambda pair: pair[0] * pair[1], reverse=True)

    covered = 0
    used_area = 0.0
    for width, height in pieces:
        placed = False
        for sheet in sorted(sheets, key=lambda candidate: candidate["area"]):
            if _fits_on_sheet(sheet, width, height):
                sheet["used"] = True
                covered += 1
                used_area += width * height
                placed = True
                break
        if not placed:
            continue

    consumed = sum(sheet["area"] for sheet in sheets if sheet["used"])
    return {
        "n_richiesti": len(items),
        "n_coperti": covered,
        "n_mancanti": len(items) - covered - missing_dimensions,
        "n_da_verificare": missing_dimensions,
        "dimensione_richiesta": round(sum(w * h for w, h in pieces), 1),
        "dimensione_consumata": round(consumed, 1),
        "sfrido_pct": round((consumed - used_area) / consumed * 100, 2) if consumed else None,
    }


def analyze_commessa_stock(items: list[Any], inventory: list[dict]) -> dict:
    """Confronta i pezzi fisici con una copia virtuale dello stock.

    Non crea prenotazioni, movimenti, richieste o piani di taglio persistenti.
    """
    groups: dict[tuple[str, str], list[Any]] = defaultdict(list)
    for item in items:
        if item.description:
            groups[(normalize_profile(item.description), (item.material_code or "").upper().strip())].append(item)

    results = []
    for (profile, quality), group_items in sorted(groups.items()):
        plate = _plate_data(profile)
        if plate:
            thickness, plate_width = plate
            profile_stock = [
                row for row in inventory
                if (row.get("tipo") or "").upper() == "LAMIERA"
                and _stock_plate_thickness(row.get("profilo")) == thickness
            ]
        else:
            profile_stock = [
                row for row in inventory
                if normalize_profile(row.get("profilo")) == profile
            ]

        quality_stock = [row for row in profile_stock if _same_quality(quality, row.get("qualita"))]
        unspecified_quality = [
            row for row in profile_stock if not str(row.get("qualita") or "").strip()
        ]
        if not profile_stock:
            analysis = {
                "n_richiesti": len(group_items), "n_coperti": 0,
                "n_mancanti": 0, "n_da_verificare": len(group_items),
                "dimensione_richiesta": 0, "dimensione_consumata": 0,
                "sfrido_pct": None,
            }
            stato, motivo = "non_associato", "Profilo non presente nel catalogo magazzino"
        elif not quality_stock and unspecified_quality:
            analysis = {
                "n_richiesti": len(group_items), "n_coperti": 0,
                "n_mancanti": 0, "n_da_verificare": len(group_items),
                "dimensione_richiesta": 0, "dimensione_consumata": 0,
                "sfrido_pct": None,
            }
            stato, motivo = "da_verificare", "Materiale presente ma qualità non indicata in magazzino"
        elif not quality_stock:
            analysis = {
                "n_richiesti": len(group_items), "n_coperti": 0,
                "n_mancanti": len(group_items), "n_da_verificare": 0,
                "dimensione_richiesta": 0, "dimensione_consumata": 0,
                "sfrido_pct": None,
            }
            stato, motivo = "mancante", "Qualità richiesta non disponibile"
        else:
            analysis = (
                _analyze_plates(group_items, quality_stock, plate[1])
                if plate else _analyze_linear(group_items, quality_stock)
            )
            if analysis["n_da_verificare"]:
                stato, motivo = "da_verificare", "Dimensioni insufficienti per il calcolo automatico"
            elif analysis["n_coperti"] == analysis["n_richiesti"]:
                stato, motivo = "disponibile", None
            elif analysis["n_coperti"] == 0:
                stato, motivo = "mancante", "Stock insufficiente"
            else:
                stato, motivo = "parziale", "Stock sufficiente solo per una parte dei pezzi"

        results.append({
            "profilo": profile,
            "qualita": quality or None,
            "tipo": "LAMIERA" if plate else (group_items[0].tipo_profilo or "SCONOSCIUTO"),
            "stato": stato,
            "motivo": motivo,
            **analysis,
        })

    counts = {
        key: sum(1 for row in results if row["stato"] == key)
        for key in ("disponibile", "parziale", "mancante", "non_associato", "da_verificare")
    }
    return {
        "profiles": results,
        "counts": counts,
        "n_profili": len(results),
        "n_pezzi": len(items),
        "sola_analisi": True,
    }
