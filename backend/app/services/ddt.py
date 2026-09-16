from __future__ import annotations

import base64
import json
import mimetypes
import os
import re
import shutil
import subprocess
import tempfile
import urllib.error
import urllib.request
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

IMAGE_SUFFIXES = {".jpg", ".jpeg", ".png", ".webp", ".bmp", ".tif", ".tiff", ".heic", ".heif"}
TEXT_SUFFIXES = {".txt", ".csv", ".tsv"}


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
            warnings.append("Testo PDF nativo incompleto: eseguo lettura avanzata.")
    except Exception as exc:
        warnings.append(f"pdfplumber non disponibile o non riuscito: {exc}")

    try:
        from pypdf import PdfReader  # type: ignore

        reader = PdfReader(path)
        text = "\n".join(page.extract_text() or "" for page in reader.pages)
        if text.strip() and _has_material_keywords(text):
            return text, warnings
        if text.strip():
            warnings.append("Testo PDF incompleto: eseguo lettura avanzata.")
    except Exception as exc:
        warnings.append(f"pypdf non disponibile o non riuscito: {exc}")

    ocr_text, ocr_warnings = _extract_pdf_ocr_text(path)
    warnings.extend(ocr_warnings)
    return ocr_text, warnings


def _tesseract_path() -> str | None:
    tesseract = shutil.which("tesseract") or "/opt/homebrew/bin/tesseract"
    return tesseract if Path(tesseract).exists() else None


def _extract_image_ocr_text(path: Path) -> tuple[str, list[str]]:
    warnings: list[str] = []
    tesseract = _tesseract_path()
    if not tesseract:
        return "", ["Lettura automatica non disponibile sul server."]

    with tempfile.TemporaryDirectory() as tmp_dir:
        try:
            from PIL import Image, ImageEnhance, ImageOps

            image = Image.open(path)
            image = ImageOps.exif_transpose(image)
            image = image.convert("L")
            image = ImageOps.autocontrast(image)
            image = ImageEnhance.Contrast(image).enhance(2.2)
            image_path = Path(tmp_dir) / "ddt-image.png"
            image.save(image_path)
        except Exception as exc:
            return "", [f"Immagine non leggibile: {exc}."]

        try:
            result = subprocess.run(
                [tesseract, image_path.as_posix(), "stdout", "-l", "ita+eng", "--psm", "6"],
                check=False,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                timeout=45,
            )
        except Exception as exc:
            return "", [f"Lettura immagine non riuscita: {exc}."]

    if result.returncode == 0 and result.stdout.strip():
        return result.stdout, warnings
    if result.stderr.strip():
        warnings.append(result.stderr.strip().splitlines()[-1])
    warnings.append("Lettura completata ma nessun testo leggibile rilevato.")
    return "", warnings


def _extract_plain_text(path: Path) -> tuple[str, list[str]]:
    for encoding in ("utf-8-sig", "utf-8", "latin-1"):
        try:
            return path.read_text(encoding=encoding), []
        except UnicodeDecodeError:
            continue
        except Exception as exc:
            return "", [f"File testo non leggibile: {exc}."]
    return "", ["File testo non leggibile con le codifiche supportate."]


def _extract_pdf_ocr_text(path: Path) -> tuple[str, list[str]]:
    warnings: list[str] = []
    tesseract = _tesseract_path()
    if not tesseract:
        return "", ["Lettura automatica non disponibile sul server."]

    try:
        import pypdfium2 as pdfium  # type: ignore
    except Exception as exc:
        return "", [f"Lettura PDF non disponibile sul server ({exc})."]

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
        warnings.append("Lettura completata ma nessun testo leggibile rilevato.")
    except Exception as exc:
        warnings.append(f"Lettura documento non riuscita: {exc}")
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
                notes="Dati parziali dal nome file: completare la review manualmente.",
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


def _analyze_ddt_text(
    text: str,
    warnings: list[str],
    filename: str,
    *,
    source_kind: str,
) -> dict[str, Any]:
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
        status = "needs_review"
        warnings.append(
            "Il documento non contiene testo leggibile: completare la review manualmente per quantità, pesi e riferimenti."
        )

    return {
        "status": status,
        "filename": filename,
        "source_kind": source_kind,
        "supplier": meta.get("supplier"),
        "ddt_number": meta.get("ddt_number"),
        "ddt_date": meta.get("ddt_date"),
        "reference": meta.get("reference"),
        "text_available": bool(text.strip()),
        "warnings": warnings,
        "items": [asdict(line) for line in lines],
    }


DDT_AI_SCHEMA: dict[str, Any] = {
    "type": "object",
    "additionalProperties": False,
    "properties": {
        "supplier": {"type": ["string", "null"]},
        "ddt_number": {"type": ["string", "null"]},
        "ddt_date": {"type": ["string", "null"]},
        "reference": {"type": ["string", "null"]},
        "warnings": {
            "type": "array",
            "items": {"type": "string"},
        },
        "items": {
            "type": "array",
            "items": {
                "type": "object",
                "additionalProperties": False,
                "properties": {
                    "material_code": {"type": ["string", "null"]},
                    "description": {"type": ["string", "null"]},
                    "quantity": {"type": ["integer", "null"]},
                    "unit": {"type": ["string", "null"]},
                    "tipo": {"type": ["string", "null"]},
                    "profilo": {"type": ["string", "null"]},
                    "dimensioni": {"type": ["string", "null"]},
                    "qualita": {"type": ["string", "null"]},
                    "colata": {"type": ["string", "null"]},
                    "peso_kg": {"type": ["number", "null"]},
                    "peso_u_kg": {"type": ["number", "null"]},
                    "confidence": {"type": "number"},
                    "notes": {"type": ["string", "null"]},
                },
                "required": [
                    "material_code",
                    "description",
                    "quantity",
                    "unit",
                    "tipo",
                    "profilo",
                    "dimensioni",
                    "qualita",
                    "colata",
                    "peso_kg",
                    "peso_u_kg",
                    "confidence",
                    "notes",
                ],
            },
        },
    },
    "required": ["supplier", "ddt_number", "ddt_date", "reference", "warnings", "items"],
}


def _env_bool(name: str, default: bool = False) -> bool:
    raw = os.getenv(name)
    if raw is None:
        return default
    return raw.strip().lower() in {"1", "true", "yes", "on"}


def _ddt_ai_key() -> str | None:
    if os.getenv("DDT_AI_PROVIDER", "openai").strip().lower() != "openai":
        return None
    return os.getenv("OPENAI_API_KEY") or os.getenv("DDT_OPENAI_API_KEY")


def _ddt_ai_enabled() -> bool:
    return bool(_ddt_ai_key()) and not _env_bool("DDT_AI_DISABLED", False)


def _ddt_ai_model() -> str:
    return os.getenv("DDT_AI_MODEL", "gpt-5.6-terra").strip() or "gpt-5.6-terra"


def _ddt_ai_detail() -> str:
    detail = os.getenv("DDT_AI_DETAIL", "high").strip().lower()
    return detail if detail in {"low", "high", "original", "auto"} else "high"


def _ddt_ai_max_pages() -> int:
    try:
        return max(1, min(20, int(os.getenv("DDT_AI_MAX_PAGES", "5"))))
    except ValueError:
        return 5


def _result_ready(result: dict[str, Any]) -> bool:
    items = result.get("items") or []
    return bool(items) and all((item.get("quantity") or 0) > 0 for item in items)


def _should_use_ddt_ai(result: dict[str, Any]) -> bool:
    if not _ddt_ai_enabled():
        return False
    if _env_bool("DDT_AI_ALWAYS", False):
        return True
    source_kind = result.get("source_kind")
    if source_kind in {"image", "batch"}:
        return True
    return not _result_ready(result)


def _image_data_url(path: Path, filename: str | None = None) -> str | None:
    suffix = Path(filename or path.name).suffix.lower() or path.suffix.lower()
    supported_direct = {".jpg", ".jpeg", ".png", ".webp", ".gif"}
    if suffix in supported_direct:
        mime = mimetypes.guess_type(filename or path.name)[0] or "image/jpeg"
        data = path.read_bytes()
    else:
        try:
            from PIL import Image, ImageOps

            with Image.open(path) as image:
                image = ImageOps.exif_transpose(image)
                if image.mode not in {"RGB", "L"}:
                    image = image.convert("RGB")
                with tempfile.NamedTemporaryFile(suffix=".jpg") as tmp:
                    image.save(tmp.name, format="JPEG", quality=90)
                    data = Path(tmp.name).read_bytes()
            mime = "image/jpeg"
        except Exception:
            return None
    return f"data:{mime};base64,{base64.b64encode(data).decode('ascii')}"


def _pdf_page_data_urls(path: Path, max_pages: int) -> list[str]:
    try:
        import pypdfium2 as pdfium  # type: ignore
    except Exception:
        return []

    urls: list[str] = []
    with tempfile.TemporaryDirectory() as tmp_dir:
        pdf = pdfium.PdfDocument(path.as_posix())
        for index in range(min(len(pdf), max_pages)):
            page = pdf[index]
            bitmap = page.render(scale=2.4)
            image = bitmap.to_pil().convert("RGB")
            image_path = Path(tmp_dir) / f"page-{index + 1}.jpg"
            image.save(image_path, format="JPEG", quality=88)
            url = _image_data_url(image_path, image_path.name)
            if url:
                urls.append(url)
    return urls


def _input_images_for_ai(files: list[tuple[Path, str]]) -> list[str]:
    urls: list[str] = []
    max_pages = _ddt_ai_max_pages()
    for path, filename in files:
        suffix = Path(filename).suffix.lower() or path.suffix.lower()
        if suffix == ".pdf":
            urls.extend(_pdf_page_data_urls(path, max_pages - len(urls)))
        elif suffix in IMAGE_SUFFIXES:
            url = _image_data_url(path, filename)
            if url:
                urls.append(url)
        if len(urls) >= max_pages:
            break
    return urls[:max_pages]


def _extract_response_text(payload: dict[str, Any]) -> str:
    if isinstance(payload.get("output_text"), str):
        return payload["output_text"]
    chunks: list[str] = []

    def walk(value: Any) -> None:
        if isinstance(value, dict):
            if value.get("type") in {"output_text", "text"} and isinstance(value.get("text"), str):
                chunks.append(value["text"])
            for child in value.values():
                walk(child)
        elif isinstance(value, list):
            for child in value:
                walk(child)

    walk(payload.get("output"))
    return "\n".join(chunks).strip()


def _openai_ddt_extract(
    *,
    files: list[tuple[Path, str]],
    local_result: dict[str, Any],
    text_excerpt: str,
) -> dict[str, Any] | None:
    key = _ddt_ai_key()
    if not key:
        return None

    images = _input_images_for_ai(files)
    if not images and not text_excerpt.strip():
        return None

    system_prompt = (
        "Leggi documenti di trasporto italiani per materiali metallici e restituisci solo JSON conforme allo schema. "
        "Non inventare dati: usa null quando un campo non e' leggibile. "
        "Normalizza materiali per magazzino: tipo, profilo, dimensioni, qualita, colata, quantita e pesi. "
        "Per lamiere usa tipo LAMIERA, profilo come spessore, dimensioni come lunghezza*larghezza. "
        "Per travi usa profili come HEA200, HEB, IPE, UPN. Per tubi/angolari usa profili compatti. "
        "material_code deve essere breve, mai vuoto se la riga materiale e' valida."
    )
    user_content: list[dict[str, Any]] = [
        {
            "type": "input_text",
            "text": (
                "Estrai il DDT per preparare una proposta di ingresso magazzino. "
                f"File: {', '.join(name for _path, name in files)}\n"
                f"Dati letti localmente, se presenti:\n{text_excerpt[:12000]}\n"
                f"Proposta locale precedente:\n{json.dumps(local_result, ensure_ascii=False)[:8000]}"
            ),
        }
    ]
    for image_url in images:
        user_content.append({"type": "input_image", "image_url": image_url, "detail": _ddt_ai_detail()})

    request_payload = {
        "model": _ddt_ai_model(),
        "input": [
            {"role": "system", "content": [{"type": "input_text", "text": system_prompt}]},
            {"role": "user", "content": user_content},
        ],
        "text": {
            "format": {
                "type": "json_schema",
                "name": "ddt_extraction",
                "schema": DDT_AI_SCHEMA,
                "strict": True,
            }
        },
        "max_output_tokens": 5000,
    }
    req = urllib.request.Request(
        "https://api.openai.com/v1/responses",
        data=json.dumps(request_payload).encode("utf-8"),
        headers={
            "Authorization": f"Bearer {key}",
            "Content-Type": "application/json",
        },
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=75) as response:
            response_payload = json.loads(response.read().decode("utf-8"))
    except (urllib.error.URLError, TimeoutError, json.JSONDecodeError):
        return None

    raw_text = _extract_response_text(response_payload)
    if not raw_text:
        return None
    try:
        return json.loads(raw_text)
    except json.JSONDecodeError:
        match = re.search(r"\{.*\}", raw_text, flags=re.DOTALL)
        if not match:
            return None
        try:
            return json.loads(match.group(0))
        except json.JSONDecodeError:
            return None


def _sanitize_ai_item(item: dict[str, Any], meta: dict[str, Any]) -> dict[str, Any] | None:
    description = _clean(item.get("description"))
    tipo = _clean(item.get("tipo")).upper() or None
    profilo = _clean(item.get("profilo")).upper() or None
    dimensioni = _clean(item.get("dimensioni")).replace(" x ", "*").replace("X", "*") or None
    qualita = _normalize_quality(item.get("qualita"))
    colata = _clean(item.get("colata")) or None
    quantity_raw = item.get("quantity")
    try:
        quantity = int(quantity_raw) if quantity_raw not in (None, "") else None
    except (TypeError, ValueError):
        quantity = None
    peso_kg = item.get("peso_kg")
    peso_u_kg = item.get("peso_u_kg")
    try:
        peso_kg = float(peso_kg) if peso_kg not in (None, "") else None
    except (TypeError, ValueError):
        peso_kg = None
    try:
        peso_u_kg = float(peso_u_kg) if peso_u_kg not in (None, "") else None
    except (TypeError, ValueError):
        peso_u_kg = None
    if peso_u_kg is None and peso_kg is not None and quantity:
        peso_u_kg = round(peso_kg / quantity, 3)

    material_code = _clean(item.get("material_code"))
    if not material_code:
        material_code = _material_code(tipo, profilo, dimensioni, qualita, colata, meta.get("ddt_number"))
    if not description:
        description = " ".join(part for part in [tipo, profilo, dimensioni, qualita, colata] if part)
    if not material_code or not description:
        return None

    confidence = item.get("confidence")
    try:
        confidence = max(0.0, min(1.0, float(confidence)))
    except (TypeError, ValueError):
        confidence = 0.65

    return {
        "material_code": material_code[:100],
        "description": description[:400],
        "quantity": quantity,
        "unit": _clean(item.get("unit")).upper() or "PZ",
        "tipo": tipo,
        "profilo": profilo,
        "dimensioni": dimensioni,
        "qualita": qualita,
        "colata": colata,
        "peso_kg": peso_kg,
        "peso_u_kg": peso_u_kg,
        "confidence": confidence,
        "source": "document",
        "notes": _clean(item.get("notes")) or None,
    }


def _merge_ai_result(
    local_result: dict[str, Any],
    ai_result: dict[str, Any] | None,
    *,
    filename: str,
    source_kind: str,
) -> dict[str, Any]:
    if not ai_result:
        if not local_result.get("items"):
            local_result["warnings"] = [
                warning
                for warning in (local_result.get("warnings") or [])
                if "OCR" not in warning.upper()
            ]
            local_result["warnings"].append("Lettura documento non riuscita: completa la review manualmente o riprova con un file piu' leggibile.")
        return local_result

    meta = {
        "supplier": ai_result.get("supplier") or local_result.get("supplier"),
        "ddt_number": ai_result.get("ddt_number") or local_result.get("ddt_number"),
        "ddt_date": ai_result.get("ddt_date") or local_result.get("ddt_date"),
        "reference": ai_result.get("reference") or local_result.get("reference"),
    }
    items = [
        clean
        for clean in (_sanitize_ai_item(item, meta) for item in (ai_result.get("items") or []))
        if clean
    ]
    if not items:
        return local_result
    warnings = [
        _clean(warning)
        for warning in (ai_result.get("warnings") or [])
        if _clean(warning)
    ]
    low_confidence = any(float(item.get("confidence") or 0) < 0.72 for item in items)
    status = "ready" if all((item.get("quantity") or 0) > 0 for item in items) and not low_confidence else "needs_review"
    if low_confidence:
        warnings.append("Alcuni campi sono da verificare in review.")
    return {
        "status": status,
        "filename": filename,
        "source_kind": source_kind,
        "supplier": meta.get("supplier"),
        "ddt_number": meta.get("ddt_number"),
        "ddt_date": meta.get("ddt_date"),
        "reference": meta.get("reference"),
        "text_available": bool(local_result.get("text_available")),
        "warnings": warnings,
        "items": items,
    }


def analyze_ddt_pdf(path: Path, original_filename: str | None = None) -> dict[str, Any]:
    filename = original_filename or path.name
    text, warnings = _extract_pdf_text(path)
    local_result = _analyze_ddt_text(text, warnings, filename, source_kind="pdf")
    if _should_use_ddt_ai(local_result):
        ai_result = _openai_ddt_extract(files=[(path, filename)], local_result=local_result, text_excerpt=text)
        return _merge_ai_result(local_result, ai_result, filename=filename, source_kind="pdf")
    return local_result


def _extract_ddt_file_text(path: Path, filename: str) -> tuple[str, list[str], str]:
    suffix = Path(filename).suffix.lower() or path.suffix.lower()
    if suffix == ".pdf":
        text, warnings = _extract_pdf_text(path)
        return text, warnings, "pdf"
    if suffix in IMAGE_SUFFIXES:
        text, warnings = _extract_image_ocr_text(path)
        return text, warnings, "image"
    if suffix in TEXT_SUFFIXES:
        text, warnings = _extract_plain_text(path)
        return text, warnings, "text"

    warnings = [
        f"Formato {suffix or 'senza estensione'} accettato ma non leggibile automaticamente. "
        "Carica PDF, immagini o testo per estrazione automatica; puoi comunque completare la review manualmente."
    ]
    return "", warnings, "unsupported"


def analyze_ddt_file(path: Path, original_filename: str | None = None) -> dict[str, Any]:
    filename = original_filename or path.name
    text, warnings, source_kind = _extract_ddt_file_text(path, filename)
    local_result = _analyze_ddt_text(text, warnings, filename, source_kind=source_kind)
    if _should_use_ddt_ai(local_result):
        ai_result = _openai_ddt_extract(files=[(path, filename)], local_result=local_result, text_excerpt=text)
        return _merge_ai_result(local_result, ai_result, filename=filename, source_kind=source_kind)
    return local_result


def analyze_ddt_files(files: list[tuple[Path, str]]) -> dict[str, Any]:
    if not files:
        return _analyze_ddt_text(
            "",
            ["Nessun file caricato."],
            "DDT multipagina",
            source_kind="batch",
        )

    chunks: list[str] = []
    warnings: list[str] = []
    source_kinds: set[str] = set()
    filenames: list[str] = []

    for index, (path, filename) in enumerate(files, start=1):
        filenames.append(filename)
        text, file_warnings, source_kind = _extract_ddt_file_text(path, filename)
        source_kinds.add(source_kind)
        warnings.extend(f"Pagina {index} ({filename}): {warning}" for warning in file_warnings)
        if text.strip():
            chunks.append(f"\n--- PAGINA {index}: {filename} ---\n{text}")

    batch_name = " + ".join(filenames[:3])
    if len(filenames) > 3:
        batch_name += f" + {len(filenames) - 3} altri"
    result = _analyze_ddt_text(
        "\n".join(chunks),
        warnings,
        batch_name,
        source_kind="batch",
    )
    result["files"] = filenames
    result["page_count"] = len(files)
    result["source_kinds"] = sorted(source_kinds)
    if _should_use_ddt_ai(result):
        ai_result = _openai_ddt_extract(files=files, local_result=result, text_excerpt="\n".join(chunks))
        result = _merge_ai_result(result, ai_result, filename=batch_name, source_kind="batch")
        result["files"] = filenames
        result["page_count"] = len(files)
        result["source_kinds"] = sorted(source_kinds)
    return result
