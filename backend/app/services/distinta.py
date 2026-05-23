import os
from pathlib import Path
from typing import Any, List

import xlrd
from openpyxl import load_workbook


def _normalize_header(value: Any) -> str:
    return str(value).strip().lower() if value is not None else ""


def _extract_rows(file_path: Path) -> List[List[Any]]:
    suffix = file_path.suffix.lower()
    if suffix == ".xls":
        workbook = xlrd.open_workbook(file_path.as_posix(), formatting_info=False)
        sheet = workbook.sheet_by_index(0)
        return [sheet.row_values(rowx) for rowx in range(sheet.nrows)]

    workbook = load_workbook(filename=file_path, data_only=True, read_only=True)
    sheet = workbook.active
    return [list(row) for row in sheet.iter_rows(values_only=True)]


def _find_commessa(rows: List[List[Any]]) -> str | None:
    for row in rows[:12]:
        for cell_index, cell in enumerate(row):
            if isinstance(cell, str) and "commessa" in cell.lower():
                next_cell = row[cell_index + 1] if cell_index + 1 < len(row) else None
                if next_cell not in (None, ""):
                    return str(next_cell).strip()
    return None


def _find_header_row(rows: List[List[Any]]) -> int:
    for index, row in enumerate(rows[:15]):
        normalized = [_normalize_header(cell) for cell in row]
        if any(key in normalized for key in ["q.tà", "qta", "quantita", "quantity"]) and any(
            key in normalized for key in ["profilo", "materiale", "descrizione", "parte", "part"]
        ):
            return index
    for index, row in enumerate(rows[:15]):
        if any(cell is not None for cell in row):
            return index
    return 0


def _build_field_map(header_row: List[Any]) -> dict:
    fields = {
        "part_number": None,
        "description": None,
        "quantity": None,
        "material_code": None,
        "material_description": None,
        "commessa_reference": None,
    }
    for ix, header in enumerate(header_row):
        header_text = _normalize_header(header)
        if header_text in ["marca/pos.", "marca/pos", "parte", "part", "position", "design", "n°disegno", "codice"]:
            fields["part_number"] = ix
        elif header_text in ["profilo", "description", "descrizione", "desc"]:
            fields["description"] = ix
        elif header_text in ["q.tà", "qta", "quantita", "quantity", "qty", "n°"]:
            fields["quantity"] = ix
        elif header_text in ["materiale", "material", "material_code", "codice_materiale"]:
            fields["material_code"] = ix
        elif header_text in ["descrizione_materiale", "material_description"]:
            fields["material_description"] = ix
        elif header_text in ["commessa", "commessa_reference", "commessa_ref", "order"]:
            fields["commessa_reference"] = ix
    return fields


def parse_distinta_file(file_path: Path) -> List[dict]:
    rows = _extract_rows(file_path)
    if not rows:
        return []

    header_index = _find_header_row(rows)
    header_row = rows[header_index]
    fields = _build_field_map(header_row)
    commessa_value = _find_commessa(rows)

    items: List[dict] = []
    for row in rows[header_index + 1:]:
        if not row or all(cell is None for cell in row):
            continue

        part_number = None
        description = None
        material_code = None
        material_description = None

        if fields["part_number"] is not None:
            part_cell = row[fields["part_number"]] if fields["part_number"] < len(row) else None
            part_number = str(part_cell).strip() if part_cell not in (None, "") else None
        if fields["description"] is not None:
            desc_cell = row[fields["description"]] if fields["description"] < len(row) else None
            description = str(desc_cell).strip() if desc_cell not in (None, "") else None
        if fields["material_code"] is not None:
            material_cell = row[fields["material_code"]] if fields["material_code"] < len(row) else None
            material_code = str(material_cell).strip() if material_cell not in (None, "") else None
        if fields["material_description"] is not None:
            mat_desc_cell = row[fields["material_description"]] if fields["material_description"] < len(row) else None
            material_description = str(mat_desc_cell).strip() if mat_desc_cell not in (None, "") else None

        quantity = None
        if fields["quantity"] is not None:
            quantity_cell = row[fields["quantity"]] if fields["quantity"] < len(row) else None
            try:
                quantity = float(quantity_cell) if quantity_cell not in (None, "") else None
            except (TypeError, ValueError):
                try:
                    quantity = float(str(quantity_cell).strip())
                except Exception:
                    quantity = None

        item = {
            "part_number": part_number,
            "description": description,
            "quantity": quantity,
            "material_code": material_code,
            "material_description": material_description,
            "commessa_reference": commessa_value,
        }

        if any(value is not None for value in item.values()):
            items.append(item)

    return items


def parse_lista_parti(file_path: Path) -> List[dict]:
    """Parser specifico per file 'Lista parti assemblaggi' spesso generati da Tekla/Advanced Steel.

    Cerca l'intestazione con colonne tipo 'Assemb.', 'Parte', 'Q.tà', 'Profilo', 'Materiale'.
    """
    rows = _extract_rows(file_path)
    if not rows:
        return []

    # Trova la riga header che contiene 'Parte' o 'Assemb.'
    header_index = None
    for i, row in enumerate(rows[:20]):
        normalized = [_normalize_header(c) for c in row]
        if any(k in normalized for k in ["parte", "assemb", "asemb", "asemb."]):
            header_index = i
            break
    if header_index is None:
        header_index = _find_header_row(rows)

    header = rows[header_index]
    # mappa colonne attese
    col_map = {}
    for ix, h in enumerate(header):
        hnorm = _normalize_header(h)
        if "parte" in hnorm or "assemb" in hnorm or "asemb" in hnorm:
            col_map["part_number"] = ix
        elif "q.t" in hnorm or "qta" in hnorm or "quant" in hnorm or "q.tà" in hnorm:
            col_map["quantity"] = ix
        elif "profilo" in hnorm or "profil" in hnorm:
            col_map["description"] = ix
        elif "materiale" in hnorm or "material" in hnorm:
            col_map["material_code"] = ix
        elif "lungh" in hnorm or "lung" in hnorm or "length" in hnorm:
            col_map["length_mm"] = ix

    items: List[dict] = []
    for row in rows[header_index + 1:]:
        if not row or all(cell is None for cell in row):
            continue
        part = None
        qty = None
        desc = None
        mat = None
        length = None

        if "part_number" in col_map:
            val = row[col_map["part_number"]] if col_map["part_number"] < len(row) else None
            part = str(val).strip() if val not in (None, "") else None
        if "quantity" in col_map:
            val = row[col_map["quantity"]] if col_map["quantity"] < len(row) else None
            try:
                qty = float(val) if val not in (None, "") else None
            except Exception:
                try:
                    qty = float(str(val).strip())
                except Exception:
                    qty = None
        if "description" in col_map:
            val = row[col_map["description"]] if col_map["description"] < len(row) else None
            desc = str(val).strip() if val not in (None, "") else None
        if "material_code" in col_map:
            val = row[col_map["material_code"]] if col_map["material_code"] < len(row) else None
            mat = str(val).strip() if val not in (None, "") else None
        if "length_mm" in col_map:
            val = row[col_map["length_mm"]] if col_map["length_mm"] < len(row) else None
            length = str(val).strip() if val not in (None, "") else None

        item = {
            "part_number": part,
            "description": desc,
            "quantity": qty,
            "material_code": mat,
            "material_description": None,
            "commessa_reference": None,
            "length_mm": length,
        }
        if any(v is not None for v in item.values()):
            items.append(item)

    return items
