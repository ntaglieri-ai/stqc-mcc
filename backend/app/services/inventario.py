from pathlib import Path
from typing import Any, List


def parse_inventario(file_path: Path) -> List[dict]:
    """Legge il foglio 'Inventario ...' dal file .xlsm e restituisce le righe
    con stock attuale > 0 come lista di dizionari pronti per l'import."""
    from openpyxl import load_workbook

    wb = load_workbook(filename=file_path, data_only=True, keep_vba=False)

    # Trova il foglio inventario (il primo che non è PIVOT/NOTE)
    sheet = None
    for name in wb.sheetnames:
        if name.upper() not in ("PIVOT", "NOTE"):
            sheet = wb[name]
            break
    if sheet is None:
        return []

    # Colonne attese (indice 0-based):
    # 0=TIPO  1=PROFILO  2=N°PEZZI  3=DIMENSIONI  4=QUALITA'  5=COLATA
    # 6=COMMESSA  7=PESO[KG]  8=PESO/U  9=PESO1PZ  10=PAGINA
    # 11=DATA_PREL  12=QTA_PREL  13=DDT/RESIDUO  14=DATA_ARRIVO
    # 15=QTA_ARRIVATA  16=N°PEZZI_ATTUALE

    items: List[dict] = []
    for row in sheet.iter_rows(min_row=2, values_only=True):
        tipo = row[0]
        if not tipo or not isinstance(tipo, str):
            continue

        profilo = row[1]
        pezzi_attuale = row[16]

        try:
            qty = float(pezzi_attuale) if pezzi_attuale not in (None, "") else 0.0
        except (TypeError, ValueError):
            qty = 0.0

        if qty <= 0:
            continue

        profilo_str = str(profilo).strip() if profilo is not None else ""
        qualita = str(row[4]).strip() if row[4] not in (None, "") else ""
        colata = str(row[5]).strip() if row[5] not in (None, "") else None
        commessa = str(row[6]).strip() if row[6] not in (None, "") else None
        dimensioni = str(row[3]).strip() if row[3] not in (None, "") else None
        peso_kg = row[7]

        # Codice materiale univoco: TIPO-PROFILO[-QUALITA'] troncato a 100 char
        parts = [tipo.upper().replace(" ", "_"), profilo_str.replace(" ", "_")]
        if qualita:
            parts.append(qualita.replace(" ", "_"))
        material_code = "-".join(parts)[:100]

        # Descrizione leggibile
        desc_parts = [f"{tipo} {profilo_str}"]
        if qualita:
            desc_parts.append(qualita)
        if dimensioni:
            desc_parts.append(f"L={dimensioni}mm")
        description = " | ".join(desc_parts)[:400]

        notes_parts = []
        if colata:
            notes_parts.append(f"colata={colata}")
        if commessa:
            notes_parts.append(f"commessa={commessa}")
        if peso_kg:
            notes_parts.append(f"peso_tot={peso_kg}kg")

        items.append({
            "material_code": material_code,
            "description": description,
            "specification": qualita or None,
            "quantity": qty,
            "colata": colata,
            "commessa_reference": commessa,
            "notes": "; ".join(notes_parts) or None,
        })

    return items
