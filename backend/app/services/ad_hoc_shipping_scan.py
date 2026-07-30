"""Scansioni spedizione ad hoc.

Questa modalità è separata da magazzino, officina e post-officina: la pistola
legge codici anche esterni e li confronta con l'ID dichiarato nella lista
spedizione ad hoc. Nei file spedizione l'ID operativo è di solito la colonna
"Assemb."; in alcuni flussi esterni può arrivare come "Marca".
"""
from __future__ import annotations

import json
import re
from datetime import datetime
from urllib.parse import parse_qs, urlparse

from sqlalchemy import func
from sqlalchemy.orm import Session

from backend.app.models.commessa import (
    ScannerDevice,
    SpedizioneAdHoc,
    SpedizioneAdHocItem,
    WorkshopScanAttempt,
)


ID_KEYS = ("id", "codice", "code", "assemb", "assemblato", "marca")
FIELD_ALIASES = {
    "codice": ("codice", "code", "id", "qr_code", "assemb", "assemblato", "marca"),
    "descrizione": ("descrizione", "description", "desc", "materiale_descrizione"),
    "profilo": ("profilo", "profile", "tipo_profilo"),
    "quantita": ("quantita", "qta", "qty", "quantity"),
    "lunghezza_mm": ("lunghezza_mm", "lunghezza", "length_mm", "length"),
    "larghezza_mm": ("larghezza_mm", "larghezza", "width_mm", "width"),
    "altezza_mm": ("altezza_mm", "altezza", "height_mm", "height", "spessore_mm", "spessore"),
    "peso_unitario_kg": ("peso_unitario_kg", "peso_unitario", "peso_1_pz", "unit_weight_kg"),
    "peso_totale_kg": ("peso_totale_kg", "peso_totale", "peso_kg", "weight_kg", "peso"),
    "area_verniciabile_mq": ("area_verniciabile_mq", "area_mq", "area"),
    "trattamento": ("trattamento", "treatment"),
    "tipo_unita": ("tipo_unita", "tipo", "type", "entity", "entity_label"),
}


def _norm_key(value: str) -> str:
    return re.sub(r"[^a-z0-9]+", "_", str(value or "").strip().lower()).strip("_")


def _parse_number(value):
    if value in (None, ""):
        return None
    text = str(value).strip().replace(" ", "")
    if "," in text and "." in text:
        text = text.replace(".", "").replace(",", ".")
    else:
        text = text.replace(",", ".")
    try:
        return float(text)
    except (TypeError, ValueError):
        return None


def _extract_weight_kg_from_text(value: str):
    text = str(value or "")
    patterns = (
        r"\bkg\s*[:=]?\s*(\d+(?:[.,]\d+)?)\b",
        r"\b(\d+(?:[.,]\d+)?)\s*kg\b",
    )
    for pattern in patterns:
        match = re.search(pattern, text, re.IGNORECASE)
        if match:
            return _parse_number(match.group(1))
    return None


def _extract_quantity_from_text(value: str) -> dict:
    text = str(value or "")
    sequence_patterns = (
        r"\bq\.?\s*t\.?\s*a'?\.?\s*[:=]?\s*(\d+(?:[.,]\d+)?)\s*(?:di|/)\s*(\d+(?:[.,]\d+)?)\b",
        r"\b(\d+(?:[.,]\d+)?)\s*(?:di|/)\s*(\d+(?:[.,]\d+)?)\b",
    )
    for pattern in sequence_patterns:
        match = re.search(pattern, text, re.IGNORECASE)
        if not match:
            continue
        current = _parse_number(match.group(1))
        total = _parse_number(match.group(2))
        if current is None or total is None:
            continue
        return {
            "quantita": 1,
            "scan_quantita": 1,
            "scan_progressivo": current,
            "scan_totale": total,
        }

    qty_match = re.search(
        r"\bq\.?\s*t\.?\s*a'?\.?\s*[:=]?\s*(\d+(?:[.,]\d+)?)\b",
        text,
        re.IGNORECASE,
    )
    if qty_match:
        qty = _parse_number(qty_match.group(1))
        if qty is not None:
            return {"quantita": qty, "scan_quantita": qty}
    return {}


def _extract_text_code_fields(value: str) -> dict:
    text = str(value or "").strip()
    if not text:
        return {}
    match = re.search(r"(?<![A-Z0-9])([A-Z]{1,4}[\s._/\-]*\d{2,5})(?![A-Z0-9])", text, re.IGNORECASE)
    if not match:
        return {}
    raw_code = match.group(1).strip()
    code = re.sub(r"[^A-Z0-9]+", "", raw_code.upper())
    before = text[: match.start()].strip(" -_./;:,")
    after = text[match.end() :].strip(" -_./;:,")
    fields = {"codice": code, "codice_raw": raw_code}
    if before:
        fields["descrizione"] = before
    if after:
        fields["testo_dopo_codice"] = after
    return fields


def _same_weight(left, right) -> bool:
    if left is None or right is None:
        return False
    return abs(float(left) - float(right)) < 0.01


def _normalize_shipping_code(value: str | None) -> str:
    return str(value or "").strip().upper()


def _compact_shipping_code(value: str | None) -> str:
    return re.sub(r"[^A-Z0-9]+", "", str(value or "").upper())


def _payload_contains_shipping_code(raw_payload: str, code: str | None) -> bool:
    clean_code = _normalize_shipping_code(code)
    compact_code = _compact_shipping_code(code)
    if len(compact_code) < 2:
        return False
    pattern = rf"(?<![A-Z0-9]){re.escape(clean_code)}(?![A-Z0-9])"
    if clean_code and bool(re.search(pattern, str(raw_payload or ""), re.IGNORECASE)):
        return True
    flexible_pattern = r"(?<![A-Z0-9])" + r"[^A-Z0-9]*".join(re.escape(ch) for ch in compact_code) + r"(?![A-Z0-9])"
    if bool(re.search(flexible_pattern, str(raw_payload or ""), re.IGNORECASE)):
        return True
    payload_tokens = {
        _compact_shipping_code(token)
        for token in re.findall(r"[A-Z0-9][A-Z0-9._/\-\s]{1,40}[A-Z0-9]", str(raw_payload or "").upper())
    }
    payload_tokens.update(_compact_shipping_code(token) for token in re.findall(r"[A-Z0-9]+", str(raw_payload or "").upper()))
    return compact_code in payload_tokens


def _flatten_payload(data: dict) -> dict:
    result = {}
    for key, value in data.items():
        if isinstance(value, dict) and _norm_key(key) in {"fields", "dati", "info"}:
            result.update(_flatten_payload(value))
        elif isinstance(value, (str, int, float, bool)) or value is None:
            result[str(key)] = value
    return result


def parse_ad_hoc_scan_payload(raw_payload: str) -> dict:
    value = (raw_payload or "").strip()
    if not value:
        return {}

    parsed_fields = {}
    try:
        data = json.loads(value)
        if isinstance(data, dict):
            if data.get("msg") and len(data) <= 2:
                return parse_ad_hoc_scan_payload(str(data["msg"]))
            parsed_fields.update(_flatten_payload(data))
    except (json.JSONDecodeError, TypeError, ValueError):
        pass

    parsed = urlparse(value)
    if parsed.query:
        for key, values in parse_qs(parsed.query).items():
            if values:
                parsed_fields[key] = values[0]

    for key, val in re.findall(r"([A-Za-z0-9_. /\-]+)\s*[:=]\s*([^|;\n\r]+)", value):
        parsed_fields.setdefault(key.strip(), val.strip())

    text_code_fields = _extract_text_code_fields(value)
    if text_code_fields:
        parsed_fields.update(text_code_fields)
    if not parsed_fields:
        parsed_fields["codice"] = _extract_shipping_id(value)

    norm = {_norm_key(key): val for key, val in parsed_fields.items()}
    mapped = {"scan_fields": parsed_fields}
    for target, aliases in FIELD_ALIASES.items():
        for alias in aliases:
            alias_key = _norm_key(alias)
            if alias_key in norm and norm[alias_key] not in (None, ""):
                mapped[target] = norm[alias_key]
                break

    mapped["codice"] = str(mapped.get("codice") or _extract_shipping_id(value) or "").strip()
    for key in ("quantita", "lunghezza_mm", "larghezza_mm", "altezza_mm", "peso_unitario_kg", "peso_totale_kg", "area_verniciabile_mq"):
        mapped[key] = _parse_number(mapped.get(key))
    if mapped.get("peso_totale_kg") is None:
        mapped["peso_totale_kg"] = _extract_weight_kg_from_text(value)
    quantity_from_text = _extract_quantity_from_text(value)
    if quantity_from_text:
        mapped.update(quantity_from_text)
        mapped["scan_fields"].update(quantity_from_text)
    mapped["quantita"] = mapped["quantita"] if mapped.get("quantita") is not None else 1
    return mapped


def _extract_shipping_id(raw_payload: str) -> str:
    value = (raw_payload or "").strip()
    if not value:
        return ""

    try:
        data = json.loads(value)
        if isinstance(data, dict):
            lowered = {str(k).strip().lower(): v for k, v in data.items()}
            for key in ID_KEYS:
                if lowered.get(key) not in (None, ""):
                    return str(lowered[key]).strip()
            if lowered.get("msg") not in (None, ""):
                return _extract_shipping_id(str(lowered["msg"]))
    except (json.JSONDecodeError, TypeError, ValueError):
        pass

    parsed = urlparse(value)
    if parsed.query:
        query = {k.lower(): v for k, v in parse_qs(parsed.query).items()}
        for key in ID_KEYS:
            values = query.get(key)
            if values and values[0]:
                return values[0].strip()
    if parsed.scheme and parsed.netloc and parsed.path:
        tail = parsed.path.rstrip("/").rsplit("/", 1)[-1].strip()
        if tail:
            return tail

    marker = re.search(
        r"\b(?:id|codice|code|assemb|assemblato|marca)\s*[:=]\s*([A-Za-z0-9._/\-]+)",
        value,
        re.IGNORECASE,
    )
    if marker:
        return marker.group(1).strip()

    if value.upper().startswith("STQC:") and ":" in value:
        tail = value.rsplit(":", 1)[-1].strip()
        if tail:
            return tail

    return value


def _attempt(
    db: Session,
    scanner: ScannerDevice,
    external_id: str | None,
    raw_payload: str,
    outcome: str,
    message: str,
    *,
    error_code: str | None = None,
) -> None:
    db.add(
        WorkshopScanAttempt(
            scanner_device_id=scanner.id,
            scanner_external_id=(external_id or "")[:120] or None,
            raw_payload=(raw_payload or "")[:2000],
            scan_kind="AD_HOC_SHIPPING",
            outcome=outcome,
            error_code=error_code,
            message=message,
            created_at=datetime.utcnow(),
        )
    )


def process_ad_hoc_shipping_scan(
    db: Session,
    scanner: ScannerDevice,
    raw_payload: str,
    external_id: str | None = None,
) -> dict:
    raw_payload = (raw_payload or "").strip()
    now = datetime.utcnow()
    scanner.last_seen_at = now

    if not scanner.active:
        _attempt(db, scanner, external_id, raw_payload, "ERROR", "Scanner non attivo", error_code="SCANNER_INACTIVE")
        db.commit()
        return {"ply": 3, "msg": "Scanner non attivo", "ok": False, "error_code": "SCANNER_INACTIVE", "scan_kind": "AD_HOC_SHIPPING"}

    parsed_payload = parse_ad_hoc_scan_payload(raw_payload)
    shipping_id = str(parsed_payload.get("codice") or _extract_shipping_id(raw_payload)).strip()
    if not shipping_id:
        _attempt(db, scanner, external_id, raw_payload, "ERROR", "QR senza ID spedizione", error_code="EMPTY_SHIPPING_ID")
        db.commit()
        return {"ply": 3, "msg": "QR senza ID spedizione", "ok": False, "error_code": "EMPTY_SHIPPING_ID", "scan_kind": "AD_HOC_SHIPPING"}

    exact_shipping_id = _normalize_shipping_code(shipping_id)
    matches = (
        db.query(SpedizioneAdHocItem)
        .join(SpedizioneAdHoc, SpedizioneAdHoc.id == SpedizioneAdHocItem.spedizione_id)
        .filter(func.upper(func.trim(SpedizioneAdHocItem.codice)) == exact_shipping_id)
        .filter(SpedizioneAdHoc.stato != "CHIUSA")
        .order_by(
            SpedizioneAdHocItem.stato.asc(),
            SpedizioneAdHocItem.created_at.desc(),
            SpedizioneAdHocItem.id.desc(),
        )
        .all()
    )
    matched_shipping_id = exact_shipping_id

    if not matches:
        candidates = (
            db.query(SpedizioneAdHocItem)
            .join(SpedizioneAdHoc, SpedizioneAdHoc.id == SpedizioneAdHocItem.spedizione_id)
            .filter(SpedizioneAdHoc.stato != "CHIUSA")
            .filter(SpedizioneAdHocItem.codice.isnot(None))
            .order_by(
                SpedizioneAdHocItem.stato.asc(),
                SpedizioneAdHocItem.created_at.desc(),
                SpedizioneAdHocItem.id.desc(),
            )
            .all()
        )
        contained_codes = {}
        for row in candidates:
            normalized_code = _normalize_shipping_code(row.codice)
            compact_code = _compact_shipping_code(row.codice)
            if compact_code and _payload_contains_shipping_code(raw_payload, row.codice):
                contained_codes[compact_code] = normalized_code
        if contained_codes:
            matched_shipping_id = sorted(contained_codes.values(), key=lambda value: (-len(_compact_shipping_code(value)), value))[0]
            matched_compact_id = _compact_shipping_code(matched_shipping_id)
            matches = [
                row
                for row in candidates
                if _compact_shipping_code(row.codice) == matched_compact_id
            ]

    empty_spedizione = (
        db.query(SpedizioneAdHoc)
        .filter(SpedizioneAdHoc.commessa_id.is_(None))
        .filter(SpedizioneAdHoc.source_file.is_(None))
        .filter(SpedizioneAdHoc.stato == "APERTA")
        .order_by(SpedizioneAdHoc.id.desc())
        .first()
    )
    if empty_spedizione and not matches:
        parsed = parsed_payload
        code = str(parsed.get("codice") or shipping_id).strip()
        if not code:
            _attempt(db, scanner, external_id, raw_payload, "ERROR", "QR senza codice", error_code="EMPTY_SHIPPING_ID")
            db.commit()
            return {"ply": 3, "msg": "QR senza codice", "ok": False, "error_code": "EMPTY_SHIPPING_ID", "scan_kind": "AD_HOC_SHIPPING"}
        next_row_index = (
            db.query(func.max(SpedizioneAdHocItem.row_index))
            .filter(SpedizioneAdHocItem.spedizione_id == empty_spedizione.id)
            .scalar()
            or 0
        ) + 1
        note = json.dumps(parsed.get("scan_fields") or {}, ensure_ascii=False, default=str)
        db.add(SpedizioneAdHocItem(
            spedizione_id=empty_spedizione.id,
            commessa_id=None,
            revisione_id=None,
            row_index=next_row_index,
            codice=code,
            descrizione=parsed.get("descrizione"),
            profilo=parsed.get("profilo"),
            quantita=parsed.get("quantita") or 1,
            lunghezza_mm=parsed.get("lunghezza_mm"),
            larghezza_mm=parsed.get("larghezza_mm"),
            altezza_mm=parsed.get("altezza_mm"),
            peso_unitario_kg=parsed.get("peso_unitario_kg"),
            peso_totale_kg=parsed.get("peso_totale_kg"),
            area_verniciabile_mq=parsed.get("area_verniciabile_mq"),
            trattamento=parsed.get("trattamento"),
            tipo_unita=str(parsed.get("tipo_unita") or "SPEDIZIONE_AD_HOC")[:40],
            stato="TROVATO",
            trovato_at=now,
            scanner_device_id=scanner.id,
            raw_payload=raw_payload[:2000],
            note=note,
        ))
        empty_spedizione.updated_at = now
        message = f"Aggiunto a spedizione ad hoc · {code}"
        _attempt(db, scanner, external_id, raw_payload, "OK", message)
        db.commit()
        return {"ply": 1, "msg": message, "ok": True, "scan_kind": "AD_HOC_SHIPPING"}

    if not matches:
        message = f"ID spedizione non trovato: {matched_shipping_id}"
        _attempt(db, scanner, external_id, raw_payload, "ERROR", message, error_code="SHIPPING_ID_NOT_FOUND")
        db.commit()
        return {"ply": 3, "msg": message, "ok": False, "error_code": "SHIPPING_ID_NOT_FOUND", "scan_kind": "AD_HOC_SHIPPING"}

    preferred = next((row for row in matches if row.stato != "TROVATO"), matches[0])
    spedizione = preferred.spedizione
    parsed_scan = parsed_payload
    scan_fields = dict(parsed_scan.get("scan_fields") or {})
    scan_fields["codice_trovato"] = matched_shipping_id
    scan_fields["raw_payload"] = raw_payload
    scan_fields["peso_mismatch"] = False
    next_row_index = (
        db.query(func.max(SpedizioneAdHocItem.row_index))
        .filter(SpedizioneAdHocItem.spedizione_id == preferred.spedizione_id)
        .scalar()
        or 0
    ) + 1
    file_qty = float(preferred.quantita or 0)
    file_weight = float(preferred.peso_totale_kg or 0) if preferred.peso_totale_kg is not None else None
    unit_weight = float(preferred.peso_unitario_kg) if preferred.peso_unitario_kg is not None else None
    if unit_weight is None and file_weight is not None and file_qty > 0:
        unit_weight = file_weight / file_qty
    note = "SCAN_FIELDS " + json.dumps(scan_fields, ensure_ascii=False, default=str)
    db.add(SpedizioneAdHocItem(
        spedizione_id=preferred.spedizione_id,
        commessa_id=preferred.commessa_id,
        revisione_id=preferred.revisione_id,
        row_index=next_row_index,
        codice=matched_shipping_id,
        descrizione=parsed_scan.get("descrizione") or preferred.descrizione,
        profilo=parsed_scan.get("profilo") or preferred.profilo,
        quantita=1,
        lunghezza_mm=parsed_scan.get("lunghezza_mm") or preferred.lunghezza_mm,
        larghezza_mm=parsed_scan.get("larghezza_mm") or preferred.larghezza_mm,
        altezza_mm=parsed_scan.get("altezza_mm") or preferred.altezza_mm,
        peso_unitario_kg=parsed_scan.get("peso_unitario_kg") or unit_weight,
        peso_totale_kg=parsed_scan.get("peso_totale_kg") or unit_weight,
        area_verniciabile_mq=parsed_scan.get("area_verniciabile_mq"),
        trattamento=parsed_scan.get("trattamento") or preferred.trattamento,
        tipo_unita=str(parsed_scan.get("tipo_unita") or "SPEDIZIONE_AD_HOC")[:40],
        stato="TROVATO",
        trovato_at=now,
        scanner_device_id=scanner.id,
        raw_payload=raw_payload[:2000],
        source_file=preferred.source_file,
        note=note,
    ))
    if spedizione:
        spedizione.updated_at = now

    message = f"Trovato - {matched_shipping_id} - scan aggiunto"
    _attempt(db, scanner, external_id, raw_payload, "OK", message)
    db.commit()
    return {"ply": 1, "msg": message, "ok": True, "scan_kind": "AD_HOC_SHIPPING"}
