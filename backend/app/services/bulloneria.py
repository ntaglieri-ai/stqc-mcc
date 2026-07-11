from __future__ import annotations

import csv
import re
from collections import defaultdict
from pathlib import Path
from typing import Any

from backend.app.services.distinta import _extract_rows, _norm


ALIASES: dict[str, list[str]] = {
    "assemblato": ["assemblato", "assemb.", "assemb", "assembly", "assieme", "marca", "marca posizione", "marca/pos.", "posizione"],
    "codice": ["codice", "articolo", "item", "code", "part", "parte", "cod.", "codice articolo"],
    "descrizione": ["descrizione", "description", "desc", "materiale", "denominazione", "nome", "name"],
    "dimensioni_raw": ["dimensioni", "dimensions", "size"],
    "tipo": ["tipo", "type", "categoria", "famiglia"],
    "norma": ["norma", "standard", "uni", "din", "iso", "en"],
    "diametro": ["diametro", "diam.", "diam", "d", "ø", "m"],
    "lunghezza": ["lunghezza", "lungh.", "lungh", "length", "l"],
    "classe": ["classe", "classe resistenza", "class", "grade", "resistenza"],
    "trattamento": ["trattamento", "finitura", "coating", "zincatura", "finish"],
    "quantita": ["quantità", "quantita", "q.tà", "q.ta", "qta", "qty", "quantity", "n", "nr", "numero"],
    "peso_kg": ["peso (kg)", "peso(kg)", "peso kg", "peso", "weight", "weight kg"],
    "unita": ["um", "u.m.", "unità", "unita", "unit", "udm"],
    "note": ["note", "notes", "annotazioni"],
}

SECTION_LABELS = {
    "viti": "Viti",
    "vite": "Viti",
    "bulloni": "Bulloni",
    "bullone": "Bulloni",
    "bolts": "Bulloni",
    "dadi": "Dadi",
    "dado": "Dadi",
    "nuts": "Dadi",
    "rondelle": "Rondelle",
    "rondella": "Rondelle",
    "washers": "Rondelle",
    "pioli": "Pioli",
    "piolo": "Pioli",
    "tirafondi": "Tirafondi",
    "tirafondo": "Tirafondi",
}


def _clean(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    if not text:
        return None
    if text.lower() in {"nan", "none", "-", "—"}:
        return None
    return re.sub(r"\s+", " ", text)


def _to_float(value: Any) -> float:
    text = _clean(value)
    if not text:
        return 0.0
    text = text.replace(".", "").replace(",", ".") if "," in text else text
    match = re.search(r"-?\d+(?:\.\d+)?", text)
    if not match:
        return 0.0
    try:
        return float(match.group(0))
    except ValueError:
        return 0.0


def _find_header_row(rows: list[list[Any]]) -> int:
    wanted = {alias for aliases in ALIASES.values() for alias in aliases}
    best_idx = 0
    best_score = 0
    for idx, row in enumerate(rows[:30]):
        cells = {_norm(cell) for cell in row}
        score = sum(1 for cell in cells if cell in wanted)
        if score > best_score:
            best_idx = idx
            best_score = score
    return best_idx


def _build_col_map(header: list[Any]) -> dict[str, int]:
    normalized = [_norm(cell) for cell in header]
    col_map: dict[str, int] = {}
    for target, aliases in ALIASES.items():
        for alias in aliases:
            if alias in normalized:
                col_map[target] = normalized.index(alias)
                break
    return col_map


def _is_header_row(row: list[Any]) -> bool:
    normalized = {_norm(cell) for cell in row if _clean(cell)}
    wanted = {alias for aliases in ALIASES.values() for alias in aliases}
    return len(normalized & wanted) >= 2


def _section_from_row(row: list[Any]) -> str | None:
    cells = [_clean(cell) for cell in row]
    nonempty = [cell for cell in cells if cell]
    if len(nonempty) != 1:
        return None
    return SECTION_LABELS.get(nonempty[0].strip().lower())


def _read_csv(path: Path) -> list[list[Any]]:
    raw = path.read_bytes()
    text = raw.decode("utf-8-sig", errors="replace")
    sample = text[:4096]
    try:
        dialect = csv.Sniffer().sniff(sample, delimiters=";,|\t,")
    except csv.Error:
        dialect = csv.excel
        dialect.delimiter = ";"
    return [row for row in csv.reader(text.splitlines(), dialect)]


def _read_pdf(path: Path) -> list[list[Any]]:
    try:
        import pdfplumber
    except ImportError as exc:
        raise ValueError("Per leggere PDF bulloneria serve pdfplumber installato") from exc

    rows: list[list[Any]] = []
    with pdfplumber.open(path) as pdf:
        for page in pdf.pages:
            for table in page.extract_tables() or []:
                rows.extend(table)
            if not rows:
                text = page.extract_text() or ""
                for line in text.splitlines():
                    parts = re.split(r"\s{2,}|\t", line.strip())
                    if len(parts) > 1:
                        rows.append(parts)
    return rows


def _extract_any_rows(path: Path) -> list[list[Any]]:
    suffix = path.suffix.lower()
    if suffix == ".csv":
        return _read_csv(path)
    if suffix == ".pdf":
        return _read_pdf(path)
    return _extract_rows(path)


def _cell(row: list[Any], col_map: dict[str, int], key: str) -> Any:
    idx = col_map.get(key)
    if idx is None or idx >= len(row):
        return None
    return row[idx]


def _infer_tipo(descrizione: str | None, codice: str | None) -> str | None:
    text = f"{descrizione or ''} {codice or ''}".lower()
    rules = [
        ("rondella", "Rondella"),
        ("washer", "Rondella"),
        ("dado", "Dado"),
        ("nut", "Dado"),
        ("vite", "Vite"),
        ("screw", "Vite"),
        ("bullone", "Bullone"),
        ("bolt", "Bullone"),
        ("tirafondo", "Tirafondo"),
        ("ancorante", "Ancorante"),
        ("barra", "Barra filettata"),
    ]
    for needle, label in rules:
        if needle in text:
            return label
    return None


def _tipo_from_categoria(categoria: str | None) -> str | None:
    return {
        "Viti": "Vite",
        "Bulloni": "Bullone",
        "Dadi": "Dado",
        "Rondelle": "Rondella",
        "Pioli": "Piolo",
        "Tirafondi": "Tirafondo",
    }.get(categoria or "")


def _infer_specs(item: dict[str, Any]) -> None:
    text = " ".join(str(item.get(key) or "") for key in ("codice", "descrizione", "dimensioni_raw", "norma", "classe"))
    if not item.get("diametro"):
        match = re.search(r"\bM\s*(\d{1,3})\b", text, re.I)
        if match:
            item["diametro"] = f"M{match.group(1)}"
    if not item.get("diametro"):
        match = re.search(r"\b(?:DADO|RONDELLA|NUT)\s*[- ]\s*(\d{1,3})(?:[,.]0)?\b", text, re.I)
        if match:
            item["diametro"] = f"M{match.group(1)}"
    if not item.get("diametro"):
        washer = re.search(r"\bWASHER\s+(\d{1,3})(?:[,.]\d+)?\b", text, re.I)
        if washer:
            diameter = int(washer.group(1))
            nominal = {11: 10, 13: 12, 17: 16}.get(diameter, diameter)
            item["diametro"] = f"M{nominal}"
    if not item.get("lunghezza"):
        match = re.search(r"(?:x|×)\s*(\d{1,4}(?:[,.]\d+)?)\b", text, re.I)
        if match:
            item["lunghezza"] = match.group(1).replace(",", ".")
    if not item.get("classe"):
        match = re.search(r"\b(?:classe\s*)?(\d{1,2}[,.]\d)\b", text, re.I)
        if match:
            item["classe"] = match.group(1).replace(",", ".")


def _row_to_item(row: list[Any], col_map: dict[str, int], source_file: str, categoria: str | None = None) -> dict[str, Any] | None:
    descrizione = _clean(_cell(row, col_map, "descrizione"))
    codice = _clean(_cell(row, col_map, "codice"))
    assemblato = _clean(_cell(row, col_map, "assemblato"))
    quantita = _to_float(_cell(row, col_map, "quantita")) or 1.0
    if not any([descrizione, codice, assemblato]):
        return None
    if descrizione and descrizione.lower() in {"descrizione", "description"}:
        return None

    item = {
        "assemblato": assemblato,
        "codice": codice,
        "descrizione": descrizione,
        "categoria": categoria,
        "tipo": _clean(_cell(row, col_map, "tipo")),
        "dimensioni_raw": _clean(_cell(row, col_map, "dimensioni_raw")),
        "norma": _clean(_cell(row, col_map, "norma")),
        "diametro": _clean(_cell(row, col_map, "diametro")),
        "lunghezza": _clean(_cell(row, col_map, "lunghezza")),
        "classe": _clean(_cell(row, col_map, "classe")),
        "trattamento": _clean(_cell(row, col_map, "trattamento")),
        "quantita": quantita,
        "unita": _clean(_cell(row, col_map, "unita")) or "pz",
        "peso_kg": _to_float(_cell(row, col_map, "peso_kg")) or None,
        "note": _clean(_cell(row, col_map, "note")),
        "source_file": source_file,
    }
    if not item["tipo"]:
        item["tipo"] = _infer_tipo(descrizione, codice) or _tipo_from_categoria(categoria)
    _infer_specs(item)
    return item


def parse_bulloneria_file(path: Path) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    rows = _extract_any_rows(path)
    if not rows:
        return [], {"ok": True, "summary": "File bulloneria vuoto", "righe": 0, "quantita_totale": 0}

    items: list[dict[str, Any]] = []
    current_category: str | None = None
    current_col_map: dict[str, int] | None = None

    for row in rows:
        section = _section_from_row(row)
        if section:
            current_category = section
            current_col_map = None
            continue
        if _is_header_row(row):
            current_col_map = _build_col_map(row)
            if "quantita" not in current_col_map:
                current_col_map["quantita"] = len(row) - 1
            if "descrizione" not in current_col_map and "codice" not in current_col_map:
                current_col_map["descrizione"] = 0
            continue
        if not current_col_map:
            continue
        parsed = _row_to_item(row, current_col_map, path.name, current_category)
        if parsed:
            items.append(parsed)

    by_tipo: dict[str, float] = defaultdict(float)
    by_categoria: dict[str, float] = defaultdict(float)
    by_assemblato: dict[str, float] = defaultdict(float)
    for item in items:
        by_tipo[item.get("tipo") or "Altro"] += float(item.get("quantita") or 0)
        by_categoria[item.get("categoria") or item.get("tipo") or "Altro"] += float(item.get("quantita") or 0)
        if item.get("assemblato"):
            by_assemblato[item["assemblato"]] += float(item.get("quantita") or 0)

    total_qty = sum(float(item.get("quantita") or 0) for item in items)
    total_weight = sum(float(item.get("peso_kg") or 0) for item in items)
    return items, {
        "ok": True,
        "summary": f"Importate {len(items)} righe bulloneria per {total_qty:g} pezzi complessivi",
        "righe": len(items),
        "quantita_totale": total_qty,
        "peso_kg_totale": total_weight,
        "categorie": dict(sorted(by_categoria.items())),
        "tipologie": dict(sorted(by_tipo.items())),
        "assemblati": dict(sorted(by_assemblato.items())),
    }
