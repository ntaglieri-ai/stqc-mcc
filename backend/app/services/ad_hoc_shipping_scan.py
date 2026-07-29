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


def _same_weight(left, right) -> bool:
    if left is None or right is None:
        return False
    return abs(float(left) - float(right)) < 0.01


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

    matches = (
        db.query(SpedizioneAdHocItem)
        .join(SpedizioneAdHoc, SpedizioneAdHoc.id == SpedizioneAdHocItem.spedizione_id)
        .filter(func.upper(func.trim(SpedizioneAdHocItem.codice)) == shipping_id.strip().upper())
        .filter(SpedizioneAdHoc.stato != "CHIUSA")
        .order_by(
            SpedizioneAdHocItem.stato.asc(),
            SpedizioneAdHocItem.created_at.desc(),
            SpedizioneAdHocItem.id.desc(),
        )
        .all()
    )

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
        message = f"ID spedizione non trovato: {shipping_id}"
        _attempt(db, scanner, external_id, raw_payload, "ERROR", message, error_code="SHIPPING_ID_NOT_FOUND")
        db.commit()
        return {"ply": 3, "msg": message, "ok": False, "error_code": "SHIPPING_ID_NOT_FOUND", "scan_kind": "AD_HOC_SHIPPING"}

    preferred = next((row for row in matches if row.stato != "TROVATO"), matches[0])
    target_rows = [
        row for row in matches
        if row.spedizione_id == preferred.spedizione_id and str(row.codice or "").strip().upper() == shipping_id.strip().upper()
    ]
    spedizione = preferred.spedizione
    already_found = all(row.stato == "TROVATO" for row in target_rows)
    parsed_scan = parsed_payload
    scan_weight = parsed_scan.get("peso_totale_kg")
    scan_fields = dict(parsed_scan.get("scan_fields") or {})
    if scan_weight is not None:
        scan_fields["peso_scan_kg"] = scan_weight
    note_line = f"[{now.isoformat()}] Spedizione ad hoc: ID {shipping_id} letto da {scanner.scanner_code}."
    for row in target_rows:
        file_weight = float(row.peso_totale_kg) if row.peso_totale_kg is not None else None
        mismatch = scan_weight is not None and file_weight is not None and not _same_weight(scan_weight, file_weight)
        row_scan_fields = dict(scan_fields)
        row_scan_fields["peso_file_kg"] = file_weight
        row_scan_fields["peso_mismatch"] = mismatch
        row.stato = "TROVATO"
        row.trovato_at = row.trovato_at or now
        row.scanner_device_id = scanner.id
        row.raw_payload = raw_payload[:2000]
        row.updated_at = now
        scan_line = "SCAN_FIELDS " + json.dumps(row_scan_fields, ensure_ascii=False, default=str)
        row.note = "\n".join(part for part in (row.note, note_line, scan_line) if part)

    message = (
        f"ID già trovato · {shipping_id}"
        if already_found
        else f"Trovato · {shipping_id} · {spedizione.titolo if spedizione else 'spedizione'} · {len(target_rows)} riga/e"
    )
    _attempt(db, scanner, external_id, raw_payload, "OK", message)
    db.commit()
    return {"ply": 1, "msg": message, "ok": True, "scan_kind": "AD_HOC_SHIPPING"}
