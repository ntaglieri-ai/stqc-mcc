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

    shipping_id = _extract_shipping_id(raw_payload)
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
    note_line = f"[{now.isoformat()}] Spedizione ad hoc: ID {shipping_id} letto da {scanner.scanner_code}."
    for row in target_rows:
        row.stato = "TROVATO"
        row.trovato_at = row.trovato_at or now
        row.scanner_device_id = scanner.id
        row.raw_payload = raw_payload[:2000]
        row.updated_at = now
        row.note = f"{row.note}\n{note_line}" if row.note else note_line

    message = (
        f"ID già trovato · {shipping_id}"
        if already_found
        else f"Trovato · {shipping_id} · {spedizione.titolo if spedizione else 'spedizione'} · {len(target_rows)} riga/e"
    )
    _attempt(db, scanner, external_id, raw_payload, "OK", message)
    db.commit()
    return {"ply": 1, "msg": message, "ok": True, "scan_kind": "AD_HOC_SHIPPING"}
