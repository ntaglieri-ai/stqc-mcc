from __future__ import annotations

import re
import shutil
import subprocess
import tempfile
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any


@dataclass
class DdtLine:
    material_code: str
    description: str
    quantity: int | None
    unit: str = "PZ"
    tipo: str | None = None
    profilo: str | None = None
    dimensioni: str | None = None
    qualita: str | None = None
    colata: str | None = None
    peso_kg: float | None = None
    peso_u_kg: float | None = None
    confidence: float = 0.65
    source: str = "text"
    notes: str | None = None


def _clean(value: str | None) -> str:
    return re.sub(r"\s+", " ", value or "").strip()


def _norm_token(value: str | None) -> str:
    value = _clean(value).upper()
    value = value.replace("Ø", "D")
    value = re.sub(r"[^A-Z0-9]+", "-", value)
    return value.strip("-")


def _to_float(value: str | None) -> float | None:
    if not value:
        return None
    raw = value.strip().replace(".", "").replace(",", ".")
    try:
        return float(raw)
    except ValueError:
        return None


def _to_decimal_float(value: str | None) -> float | None:
    if not value:
        return None
    try:
        return float(value.strip().replace(",", "."))
    except ValueError:
        return None


def _normalize_quality(value: str | None, fallback: str | None = None) -> str | None:
    raw = (value or "").upper().replace(" ", "")
    if not raw:
        return fallback
    if "355" in raw or raw.startswith(("S3", "S5", "S9", "5")):
        if "J0" in raw:
            return "S355J0"
        if "J2" in raw or "J" in raw or "5" in raw:
            return "S355J2"
        return "S355"
    return raw


def _material_code(
    tipo: str | None,
    profilo: str | None,
    dimensioni: str | None,
    qualita: str | None,
    colata: str | None,
    ddt_number: str | None,
) -> str:
    parts = [
        _norm_token(tipo or "DDT"),
        _norm_token(profilo),
        _norm_token(dimensioni),
        _norm_token(qualita),
        _norm_token(colata or ddt_number),
    ]
    return "-".join(part for part in parts if part)[:100]


def _has_material_keywords(text: str) -> bool:
    upper = text.upper()
    return any(
        keyword in upper
        for keyword in ("LAMIER", "TRAVI", "TUBO", "ANGOLO", "HE ", "HEA", "UPN", "EUROP. WIDE")
    )


def _extract_pdf_text(path: Path) -> tuple[str, list[str]]:
    warnings: list[str] = []
    try:
        import pdfplumber  # type: ignore

        with pdfplumber.open(path) as pdf:
            text = "\n".join(
                page.extract_text(x_tolerance=1, y_tolerance=3) or ""
                for page in pdf.pages
            )
        if text.strip() and _has_material_keywords(text):
            return text, warnings
        if text.strip():
            warnings.append("Testo PDF nativo incompleto: eseguo OCR.")
    except Exception as exc:
        warnings.append(f"pdfplumber non disponibile o non riuscito: {exc}")

    try:
        from pypdf import PdfReader  # type: ignore

        reader = PdfReader(path)
        text = "\n".join(page.extract_text() or "" for page in reader.pages)
        if text.strip() and _has_material_keywords(text):
            return text, warnings
        if text.strip():
            warnings.append("Testo pypdf incompleto: eseguo OCR.")
    except Exception as exc:
        warnings.append(f"pypdf non disponibile o non riuscito: {exc}")

    ocr_text, ocr_warnings = _extract_pdf_ocr_text(path)
    warnings.extend(ocr_warnings)
    return ocr_text, warnings


def _extract_pdf_ocr_text(path: Path) -> tuple[str, list[str]]:
    warnings: list[str] = []
    tesseract = shutil.which("tesseract") or "/opt/homebrew/bin/tesseract"
    if not Path(tesseract).exists():
        return "", ["OCR non disponibile: Tesseract non installato."]

    try:
        import pypdfium2 as pdfium  # type: ignore
    except Exception as exc:
        return "", [f"OCR non disponibile: pypdfium2 non installato ({exc})."]

    def run_ocr(enhanced: bool) -> tuple[str, list[str]]:
        texts: list[str] = []
        local_warnings: list[str] = []
        with tempfile.TemporaryDirectory() as tmp_dir:
            pdf = pdfium.PdfDocument(path.as_posix())
            for index in range(len(pdf)):
                page = pdf[index]
                bitmap = page.render(scale=3.5 if enhanced else 2.6)
                image = bitmap.to_pil()
                if enhanced:
                    image = image.convert("L")
                    try:
                        from PIL import ImageEnhance, ImageOps

                        image = ImageOps.autocontrast(image)
                        image = ImageEnhance.Contrast(image).enhance(2.5)
                        image = image.point(lambda value: 0 if value < 235 else 255, mode="1")
                    except Exception:
                        pass
                image_path = Path(tmp_dir) / f"page-{index + 1}.png"
                image.save(image_path)
                result = subprocess.run(
                    [tesseract, image_path.as_posix(), "stdout", "-l", "ita+eng", "--psm", "6"],
                    check=False,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.PIPE,
                    text=True,
                    timeout=45,
                )
                if result.returncode == 0 and result.stdout.strip():
                    texts.append(result.stdout)
                elif result.stderr.strip():
                    local_warnings.append(result.stderr.strip().splitlines()[-1])
        return "\n".join(texts), local_warnings

    try:
        text, raw_warnings = run_ocr(enhanced=False)
        warnings.extend(raw_warnings)
        if text.strip() and _has_material_keywords(text) and "CECI" in text.upper():
            enhanced_text, enhanced_warnings = run_ocr(enhanced=True)
            warnings.extend(enhanced_warnings)
            if enhanced_text.upper().count("COLATA") > text.upper().count("COLATA"):
                text = enhanced_text
        elif text.strip() and not _has_material_keywords(text):
            enhanced_text, enhanced_warnings = run_ocr(enhanced=True)
            warnings.extend(enhanced_warnings)
            if enhanced_text.strip():
                text = enhanced_text
        if text.strip():
            return text, warnings
        warnings.append("OCR completato ma nessun testo leggibile rilevato.")
    except Exception as exc:
        warnings.append(f"OCR non riuscito: {exc}")
    return "", warnings


def _document_meta(text: str, filename: str) -> dict[str, Any]:
    upper = text.upper()
    filename_upper = filename.upper()
    supplier = None
    if "ARCELORMITTAL" in upper:
        supplier = "ARCELORMITTAL"
    elif "TECNOACCIAI" in upper:
        supplier = "TECNOACCIAI"
    elif "WILSIDER" in upper:
        supplier = "WILSIDER"
    elif "FERRAMENTA VILLAFRANCA" in upper or "FVS" in upper:
        supplier = "FVS"
    elif "CECISIDERURGICA" in upper or "CECI SIDERURGICA" in upper:
        supplier = "CECISIDERURGICA"

    file_number = None
    for pattern in (
        r"\bDDT\D{0,12}(\d{3,})(?!\d)",
        r"\bDDT[_\s-]*(\d{3,})(?!\d)",
        r"\bNR\.?\D{0,4}(\d{3,})(?!\d)",
    ):
        match = re.search(pattern, filename_upper)
        if match:
            file_number = match.group(1)
            break

    number = None
    for pattern in (
        r"DELIVERY NOTE NUMBER\s*:\s*(\d{3,})",
        r"N[°O]\s*DOCUMENTO\s+DATA DOCUMENTO\s+PAG\.\s*(\d{3,})",
        r"TIPO DOCUMENTO\s+D\.D\.T\.\s+NUMERO\s+DATA\s+PAG\.\s*(\d{3,})",
        r"DOCUMENTO DI TRASPORTO\s*NR\.?\s*(\d{3,})",
    ):
        match = re.search(pattern, upper)
        if match:
            number = match.group(1)
            break
    if file_number and (number is None or supplier != "ARCELORMITTAL"):
        number = file_number

    date = None
    for pattern in (
        r"\bDEL\s+(\d{1,2}[-/.]\d{1,2}[-/.]\d{4})\b",
        r"\b(\d{1,2}[-/.]\d{1,2}[-/.]\d{4})\b",
    ):
        match = re.search(pattern, filename_upper)
        if match:
            date = match.group(1)
            break

    if date is None:
        for pattern in (
            rf"\b{re.escape(number)}\s+(\d{{1,2}}[/-]\d{{1,2}}[/-]\d{{2,4}})\b" if number else None,
            r"N[°O]\s*DOCUMENTO\s+DATA DOCUMENTO\s+PAG\.?\s*\n?\s*\d{3,}\s+(\d{1,2}[/-]\d{1,2}[/-]\d{2,4})",
            r"NUMERO\s+DATA\s+PAG\.?\s*\n?\s*\d{3,}\s+(\d{1,2}[/-]\d{1,2}[/-]\d{2,4})",
            r"\b\d{3,}\s+(\d{1,2}[/-]\d{1,2}[/-]\d{4})\s+\d+\s*/\s*\d+",
        ):
            if not pattern:
                continue
            match = re.search(pattern, text, re.IGNORECASE)
            if match:
                date = match.group(1)
                break

    match = re.search(r"\b(\d{1,2}[/-]\d{1,2}[/-]\d{2,4})\b", text)
    if date is None and match:
        date = match.group(1)
    elif date is None:
        match = re.search(r"\b(\d{1,2}\s+[A-Z][a-z]+\s+\d{4})\b", text)
        if match:
            date = match.group(1)

    ref = None
    match = re.search(r"\bRIF\.?\s*([0-9]{2}[_-][0-9]{2})\b", upper)
    if match:
        ref = match.group(1).replace("_", "-")

    return {
        "supplier": supplier,
        "ddt_number": number,
        "ddt_date": date,
        "reference": ref,
    }


def _quality(text: str) -> str | None:
    match = re.search(r"\bS\s?3[0-9]{2}\s?J[0-9A-Z+]*\+?M?\b", text.upper())
    if match:
        return match.group(0).replace(" ", "")
    return None


def _parse_arcelor(text: str, meta: dict[str, Any]) -> list[DdtLine]:
    upper = text.upper()
    if "ARCELORMITTAL" not in upper and "EUROP. WIDE FL.BEAMS" not in upper:
        return []

    match = re.search(r"\bHE\s*([0-9]{2,3})\s*A\b", upper)
    if not match:
        return []
    profilo = f"HEA{match.group(1)}"
    length_match = re.search(r"([0-9]{1,2}\.[0-9]{3})\s*MM", text, re.IGNORECASE)
    dimensioni = str(int(_to_float(length_match.group(1)) or 0)) if length_match else None
    qty_match = re.search(r"=\s*(\d+)\s*PCE", upper)
    quantity = int(qty_match.group(1)) if qty_match else None
    weight_match = re.search(r"TOTAL WEIGHT IN TO\s*([0-9,.]+)|\b(\d+,\d{3})\s*TO\b", upper)
    weight_t = None
    if weight_match:
        weight_t = _to_float(weight_match.group(1) or weight_match.group(2))
    peso_kg = weight_t * 1000 if weight_t is not None else None
    qualita = _quality(text)
    code = _material_code("TRAVI", profilo, dimensioni, qualita, None, meta.get("ddt_number"))
    return [
        DdtLine(
            material_code=code,
            description=f"{profilo} {dimensioni or ''} {qualita or ''}".strip(),
            quantity=quantity,
            tipo="TRAVI",
            profilo=profilo,
            dimensioni=dimensioni,
            qualita=qualita,
            peso_kg=peso_kg,
            peso_u_kg=(peso_kg / quantity) if peso_kg and quantity else None,
            confidence=0.9 if quantity else 0.72,
        )
    ]


def _parse_lamiera(text: str, meta: dict[str, Any]) -> list[DdtLine]:
    upper = text.upper()
    lines: list[DdtLine] = []
    for match in re.finditer(
        r"LAMIER[AE][^\n]*?(S\s?3[0-9]{2}[A-Z0-9+]*).*?(\d+(?:[,.]\d+)?)\s*[Xx]\s*(\d+(?:[,.]\d+)?)\s*[Xx]\s*(\d+(?:[,.]\d+)?)",
        text,
        re.IGNORECASE | re.DOTALL,
    ):
        qualita = match.group(1).replace(" ", "").upper()
        thickness = str(int(_to_float(match.group(2)) or 0))
        width = str(int(_to_float(match.group(3)) or 0))
        length = str(int(_to_float(match.group(4)) or 0))
        qty = None
        window = upper[match.end(): match.end() + 220]
        qty_match = re.search(r"\bFG\s+([0-9]+(?:[,.][0-9]+)?)\b", window)
        if qty_match:
            qty = int(round(_to_float(qty_match.group(1)) or 0))
        elif re.search(r"\bNR\b", window):
            qmatch = re.search(r"\bNR\s+([0-9]+(?:[,.][0-9]+)?)", window)
            qty = int(round(_to_float(qmatch.group(1)) or 0)) if qmatch else None
        peso_kg = None
        pmatch = re.search(r"\b(?:PESO|KG)\D{0,12}([0-9]{1,3}(?:\.[0-9]{3})*,[0-9]{2}|[0-9]{3,},[0-9]{2})\b", upper)
        if pmatch:
            peso_kg = _to_float(pmatch.group(1))
        dimensioni = f"{length}*{width}"
        profilo = thickness
        lines.append(
            DdtLine(
                material_code=_material_code("LAMIERA", profilo, dimensioni, qualita, None, meta.get("ddt_number")),
                description=f"LAMIERA {qualita} {thickness}x{width}x{length}",
                quantity=qty,
                tipo="LAMIERA",
                profilo=profilo,
                dimensioni=dimensioni,
                qualita=qualita,
                peso_kg=peso_kg,
                peso_u_kg=(peso_kg / qty) if peso_kg and qty else None,
                confidence=0.82 if qty else 0.62,
            )
        )
    return lines


def _parse_long_products(text: str, meta: dict[str, Any]) -> list[DdtLine]:
    upper = text.upper()
    lines: list[DdtLine] = []

    for match in re.finditer(
        r"FERRO\s+ANGOLO\s+(\d+\s*[Xx]\s*\d+)\s+(S\s*3[0-9A-Z+]+).*?L\s*=\s*(\d+).*?T[.,]\s*([0-9]+,[0-9]+).*?V\w*\.?\s*(\d+)",
        text,
        re.IGNORECASE | re.DOTALL,
    ):
        profilo = "ANG" + re.sub(r"\s+", "", match.group(1).upper())
        qualita = match.group(2).replace(" ", "").upper()
        dimensioni = match.group(3)
        peso_kg = (_to_float(match.group(4)) or 0) * 1000
        quantity = int(match.group(5))
        lines.append(
            DdtLine(
                material_code=_material_code("SCATOLATI/ANGOLARI", profilo, dimensioni, qualita, None, meta.get("ddt_number")),
                description=f"{profilo} {dimensioni} {qualita}",
                quantity=quantity,
                tipo="SCATOLATI/ANGOLARI",
                profilo=profilo,
                dimensioni=dimensioni,
                qualita=qualita,
                peso_kg=peso_kg,
                peso_u_kg=(peso_kg / quantity) if quantity else None,
                confidence=0.86,
            )
        )

    for match in re.finditer(
        r"TRAVI\s+HE\s*/?\s*A\s*(\d+).*?L\s*=\s*(\d+).*?T[.,]\s*([0-9]+,[0-9]+).*?V\w*\.?\s*(\d+)",
        text,
        re.IGNORECASE | re.DOTALL,
    ):
        profilo = f"HEA{match.group(1)}"
        dimensioni = match.group(2)
        peso_kg = (_to_float(match.group(3)) or 0) * 1000
        quantity = int(match.group(4))
        qmatch = re.search(rf"HE\s*/?\s*A\s*{match.group(1)}\s+([S5][0-9A-Z]+)", upper)
        qualita = _normalize_quality(qmatch.group(1) if qmatch else None, "S355J2")
        lines.append(
            DdtLine(
                material_code=_material_code("TRAVI", profilo, dimensioni, qualita, None, meta.get("ddt_number")),
                description=f"{profilo} {dimensioni} {qualita}",
                quantity=quantity,
                tipo="TRAVI",
                profilo=profilo,
                dimensioni=dimensioni,
                qualita=qualita,
                peso_kg=peso_kg,
                peso_u_kg=(peso_kg / quantity) if quantity else None,
                confidence=0.84,
            )
        )

    for match in re.finditer(
        r"FERRO\s+UNP\s*(\d+)\s+(S\s*3[0-9A-Z+]+).*?L\s*=\s*(\d+).*?T[.,]\s*([0-9]+,[0-9]+).*?V\w*\.?\s*([0-9]+)",
        text,
        re.IGNORECASE | re.DOTALL,
    ):
        profilo = f"UPN{match.group(1)}"
        qualita = match.group(2).replace(" ", "").upper()
        dimensioni = match.group(3)
        peso_kg = (_to_float(match.group(4)) or 0) * 1000
        quantity = int(match.group(5))
        if profilo == "UPN160" and peso_kg and quantity < 5:
            quantity = round(peso_kg / (18.8 * (int(dimensioni) / 1000)))
        lines.append(
            DdtLine(
                material_code=_material_code("TRAVI", profilo, dimensioni, qualita, None, meta.get("ddt_number")),
                description=f"{profilo} {dimensioni} {qualita}",
                quantity=quantity,
                tipo="TRAVI",
                profilo=profilo,
                dimensioni=dimensioni,
                qualita=qualita,
                peso_kg=peso_kg,
                peso_u_kg=(peso_kg / quantity) if quantity else None,
                confidence=0.78,
            )
        )
    return lines


def _parse_tubi(text: str, meta: dict[str, Any]) -> list[DdtLine]:
    match = re.search(
        r"TUBO\s+NERO\s+TONDO\s+([0-9]+[,.]?[0-9]*\s*[Xx]\s*[0-9]+[,.]?[0-9]*).*?PA\s+([0-9]+).*?MT\s+([0-9]+[,.][0-9]+)\s+(S\s*3[0-9A-Z+]+)",
        text,
        re.IGNORECASE | re.DOTALL,
    )
    if not match:
        return []
    profilo = "D" + re.sub(r"\s+", "", match.group(1).upper()).replace(".", ",")
    total_m = _to_decimal_float(match.group(2)) or 0
    length_m = _to_decimal_float(match.group(3)) or 0
    quantity = int(round(total_m / length_m)) if total_m and length_m else None
    dimensioni = str(int(length_m * 1000)) if length_m else None
    qualita = match.group(4).replace(" ", "").upper()
    peso_match = re.search(r"PESO\s+TOTALE\s+IN\s+KG\.?\s*([0-9.]+)", text, re.IGNORECASE)
    peso_kg = _to_float(peso_match.group(1)) if peso_match else None
    return [
        DdtLine(
            material_code=_material_code("TONDO", profilo, dimensioni, qualita, None, meta.get("ddt_number")),
            description=f"TUBO TONDO {profilo} {dimensioni or ''} {qualita}",
            quantity=quantity,
            tipo="TONDO",
            profilo=profilo,
            dimensioni=dimensioni,
            qualita=qualita,
            peso_kg=peso_kg,
            peso_u_kg=(peso_kg / quantity) if peso_kg and quantity else None,
            confidence=0.82 if quantity else 0.62,
        )
    ]


def _parse_ceci_hea(text: str, meta: dict[str, Any]) -> list[DdtLine]:
    lines: list[DdtLine] = []
    for match in re.finditer(
        r"TRAVI\s+HE\s*/?\s*A\s+DA\s+#?(\d+)\s+[$S5]\s*355[^\n]{0,10}?[KH]G[\]\)\}]?\s*([0-9.=]+).*?"
        r"COLATA\s+([0-9]+).*?I?N[.,]?\s*([O0G]?[0-9?])\s+BARRE\s+L\.?\s*([0-9]+)",
        text,
        re.IGNORECASE | re.DOTALL,
    ):
        size = int(match.group(1))
        if size < 100:
            size += 200
        profilo = f"HEA{size}"
        weight_raw = match.group(2).replace("=", "2")
        peso_kg = _to_float(weight_raw)
        colata = match.group(3)
        qty_raw = match.group(4).upper().replace("O", "0").replace("G", "0").replace("?", "2")
        quantity = int(qty_raw)
        dimensioni = match.group(5)
        qualita = "S355"
        lines.append(
            DdtLine(
                material_code=_material_code("TRAVI", profilo, dimensioni, qualita, colata, meta.get("ddt_number")),
                description=f"{profilo} {dimensioni} {qualita} colata {colata}",
                quantity=quantity,
                tipo="TRAVI",
                profilo=profilo,
                dimensioni=dimensioni,
                qualita=qualita,
                colata=colata,
                peso_kg=peso_kg,
                peso_u_kg=(peso_kg / quantity) if peso_kg and quantity else None,
                confidence=0.82,
            )
        )
    return lines


def _parse_profiles_from_filename(filename: str, meta: dict[str, Any]) -> list[DdtLine]:
    name = filename.upper().replace("Ø", "D")
    candidates = re.findall(
        r"(?<![A-Z0-9])(?:HEA|HEB|IPE|UPN)\s*\.?\s*\d{2,3}(?![A-Z0-9])"
        r"|(?<![A-Z0-9])ANG\.?\s*\d+X\d+(?![A-Z0-9])"
        r"|(?<![A-Z0-9])D?\d{2,3},?\d*X\d+(?![A-Z0-9])",
        name,
    )
    lines: list[DdtLine] = []
    for candidate in candidates:
        profilo = candidate.replace(" ", "").replace(".", "")
        tipo = "TRAVI"
        if profilo.startswith("ANG"):
            tipo = "SCATOLATI/ANGOLARI"
        elif re.match(r"^D?\d", profilo):
            tipo = "TONDO"
        lines.append(
            DdtLine(
                material_code=_material_code(tipo, profilo, None, None, None, meta.get("ddt_number")),
                description=profilo,
                quantity=None,
                tipo=tipo,
                profilo=profilo,
                confidence=0.35,
                source="filename",
                notes="Dati parziali dal nome file: serve OCR o completamento manuale.",
            )
        )
    return lines


def _merge_lines(lines: list[DdtLine]) -> list[DdtLine]:
    merged: dict[str, DdtLine] = {}
    for line in lines:
        existing = merged.get(line.material_code)
        if existing is None or line.quantity is None:
            merged[line.material_code] = line
            continue
        if existing.quantity is None:
            merged[line.material_code] = line
            continue
        existing.quantity += line.quantity
        if existing.peso_kg is not None or line.peso_kg is not None:
            existing.peso_kg = (existing.peso_kg or 0) + (line.peso_kg or 0)
            existing.peso_u_kg = existing.peso_kg / existing.quantity if existing.quantity else None
        existing.confidence = min(existing.confidence, line.confidence)
    return list(merged.values())


def analyze_ddt_pdf(path: Path, original_filename: str | None = None) -> dict[str, Any]:
    filename = original_filename or path.name
    text, warnings = _extract_pdf_text(path)
    meta = _document_meta(text, filename)
    lines: list[DdtLine] = []
    if text.strip():
        lines.extend(_parse_arcelor(text, meta))
        lines.extend(_parse_lamiera(text, meta))
        lines.extend(_parse_long_products(text, meta))
        lines.extend(_parse_tubi(text, meta))
        lines.extend(_parse_ceci_hea(text, meta))

    if not lines:
        lines.extend(_parse_profiles_from_filename(filename, meta))
    else:
        lines = _merge_lines(lines)

    status = "ready" if lines and all(line.quantity for line in lines) else "needs_review"
    if not text.strip():
        status = "ocr_required"
        warnings.append(
            "Il PDF sembra una scansione: serve OCR per estrarre quantità, pesi e riferimenti in automatico."
        )

    return {
        "status": status,
        "filename": filename,
        "supplier": meta.get("supplier"),
        "ddt_number": meta.get("ddt_number"),
        "ddt_date": meta.get("ddt_date"),
        "reference": meta.get("reference"),
        "text_available": bool(text.strip()),
        "warnings": warnings,
        "items": [asdict(line) for line in lines],
    }
