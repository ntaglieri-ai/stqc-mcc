"""Motore scan per pre-produzione: mapping grezzi di magazzino ↔ pezzi distinta.

Questo modulo è volutamente separato da workshop_scan:
- qui si lavora solo su origine materiale / grezzi / pezzi;
- nessuna postazione, fase o tempo officina viene aperto o chiuso.
"""
from __future__ import annotations

import json
import re
from datetime import datetime, timedelta

from sqlalchemy import or_
from sqlalchemy.orm import Session

from backend.app.models.commessa import Commessa, Piece, PieceScanEvent, ScannerDevice, WorkshopScanAttempt
from backend.app.models.warehouse import WarehouseItem

CURRENT_WAREHOUSE_TTL = timedelta(minutes=2)


def _scan_value(raw: str) -> str:
    value = (raw or "").strip()
    match = re.search(r"/p/([^/?#]+)", value, re.IGNORECASE)
    if match:
        return match.group(1).strip()
    try:
        data = json.loads(value)
        for key in ("qr_code", "id", "uuid"):
            if data.get(key):
                return str(data[key]).strip()
    except (json.JSONDecodeError, TypeError, AttributeError):
        pass
    return value


def _response(ply: int, message: str, **details) -> dict:
    return {"ply": ply, "msg": message, **details}


def _attempt(
    db: Session,
    scanner: ScannerDevice,
    external_id: str | None,
    raw_payload: str,
    scan_kind: str,
    outcome: str,
    message: str,
    *,
    error_code: str | None = None,
    piece: Piece | None = None,
) -> WorkshopScanAttempt:
    row = WorkshopScanAttempt(
        scanner_device_id=scanner.id,
        scanner_external_id=(external_id or "")[:120] or None,
        piece_id=piece.id if piece else None,
        raw_payload=raw_payload,
        scan_kind=scan_kind,
        outcome=outcome,
        error_code=error_code,
        message=message,
        created_at=datetime.utcnow(),
    )
    db.add(row)
    return row


def _failure(
    db: Session,
    scanner: ScannerDevice,
    external_id: str | None,
    raw_payload: str,
    scan_kind: str,
    error_code: str,
    message: str,
    *,
    piece: Piece | None = None,
) -> dict:
    _attempt(
        db,
        scanner,
        external_id,
        raw_payload,
        scan_kind,
        "ERROR",
        message,
        error_code=error_code,
        piece=piece,
    )
    scanner.last_seen_at = datetime.utcnow()
    db.commit()
    return _response(3, message, ok=False, error_code=error_code, scan_kind=scan_kind)


def _pending_mapping_pieces(db: Session, scanner: ScannerDevice) -> list[Piece]:
    return (
        db.query(Piece)
        .filter(
            Piece.materiale_origine_status == "IN_ATTESA_GREZZO",
            Piece.materiale_origine_scanner_id == scanner.id,
        )
        .order_by(Piece.ultimo_evento_at, Piece.id)
        .all()
    )


def _current_warehouse_item(db: Session, scanner: ScannerDevice, now: datetime) -> WarehouseItem | None:
    if not scanner.current_warehouse_item_id:
        return None
    if scanner.current_warehouse_item_set_at and now - scanner.current_warehouse_item_set_at > CURRENT_WAREHOUSE_TTL:
        scanner.current_warehouse_item_id = None
        scanner.current_warehouse_item_set_at = None
        return None
    return db.get(WarehouseItem, scanner.current_warehouse_item_id)


def _assign_warehouse_origin(
    db: Session,
    scanner: ScannerDevice,
    piece: Piece,
    warehouse_item: WarehouseItem,
    now: datetime,
    *,
    raw_payload: str,
    external_id: str | None,
) -> dict:
    material = warehouse_item.material
    commessa = db.get(Commessa, piece.commessa_id)
    material_code = getattr(material, "code", None) or warehouse_item.uuid

    if piece.materiale_origine_id == warehouse_item.id and piece.materiale_origine_status == "ASSEGNATO":
        message = f"Pezzo {piece.qr_code} già collegato a questo grezzo"
        _attempt(
            db,
            scanner,
            external_id,
            raw_payload,
            "PREPROD_PIECE_ALREADY_ASSIGNED",
            "OK",
            message,
            piece=piece,
        )
        return {"material": material_code, "assigned": False, "message": message, "already": True}

    piece.materiale_origine_id = warehouse_item.id
    piece.materiale_origine_status = "ASSEGNATO"
    piece.materiale_origine_assigned_at = now
    piece.materiale_origine_scanner_id = scanner.id
    piece.colata = warehouse_item.colata or getattr(material, "colata", None)
    piece.lotto = warehouse_item.commessa_ref or piece.lotto
    piece.materiale = piece.materiale or getattr(material, "qualita", None)
    piece.materiale_descrizione = piece.materiale_descrizione or getattr(material, "code", None)
    piece.ultimo_evento = "MATERIAL_ASSIGNED"
    piece.ultimo_evento_at = now
    piece.updated_at = now

    warehouse_item.status = "RESERVED"
    warehouse_item.reserved_at = warehouse_item.reserved_at or now
    warehouse_item.reserved_by_scanner_id = scanner.id
    if commessa and not warehouse_item.reserved_for_commessa:
        warehouse_item.reserved_for_commessa = commessa.codice

    event = PieceScanEvent(
        piece_id=piece.id,
        qr_code=piece.qr_code,
        commessa_id=piece.commessa_id,
        revisione_id=piece.revisione_id,
        assemblato_id=piece.assemblato_id,
        event_type="MATERIAL_ASSIGNED",
        timestamp=now,
        scanner_device_id=scanner.id,
        metadata_json={
            "source": "PRE_PRODUZIONE",
            "warehouse_item_uuid": warehouse_item.uuid,
            "warehouse_material_code": getattr(material, "code", None),
        },
    )
    db.add(event)
    _attempt(
        db,
        scanner,
        external_id,
        raw_payload,
        "PREPROD_PIECE_ASSIGNED",
        "OK",
        f"Pezzo {piece.qr_code} associato a grezzo",
        piece=piece,
    )
    return {
        "material": material_code,
        "assigned": True,
        "message": f"Pezzo {piece.qr_code} associato a grezzo",
        "already": False,
    }


def _mark_piece_pending(
    db: Session,
    scanner: ScannerDevice,
    piece: Piece,
    now: datetime,
    *,
    raw_payload: str,
    external_id: str | None,
) -> None:
    event = PieceScanEvent(
        piece_id=piece.id,
        qr_code=piece.qr_code,
        commessa_id=piece.commessa_id,
        revisione_id=piece.revisione_id,
        assemblato_id=piece.assemblato_id,
        event_type="MATERIAL_PENDING",
        timestamp=now,
        scanner_device_id=scanner.id,
        metadata_json={"source": "PRE_PRODUZIONE", "state": "WAITING_WAREHOUSE_ORIGIN"},
    )
    db.add(event)
    piece.materiale_origine_status = "IN_ATTESA_GREZZO"
    piece.materiale_origine_scanner_id = scanner.id
    piece.ultimo_evento = "MATERIAL_PENDING"
    piece.ultimo_evento_at = now
    piece.updated_at = now
    _attempt(
        db,
        scanner,
        external_id,
        raw_payload,
        "PREPROD_PIECE_PENDING",
        "OK",
        f"Pezzo {piece.qr_code} in attesa grezzo",
        piece=piece,
    )


def process_preproduction_scan(
    db: Session,
    scanner: ScannerDevice,
    raw_payload: str,
    external_id: str | None = None,
) -> dict:
    """Applica solo mapping pre-produzione: pezzi pending ↔ grezzo magazzino."""
    raw_payload = (raw_payload or "").strip()
    scanner.last_seen_at = datetime.utcnow()
    if not scanner.active:
        return _failure(db, scanner, external_id, raw_payload, "PREPROD_UNKNOWN", "SCANNER_INACTIVE", "Scanner non attivo")
    if not raw_payload:
        return _failure(db, scanner, external_id, "", "PREPROD_UNKNOWN", "EMPTY_PAYLOAD", "QR vuoto")

    value = _scan_value(raw_payload)
    now = datetime.utcnow()

    warehouse_item = db.query(WarehouseItem).filter(WarehouseItem.uuid == value.lower()).first()
    if warehouse_item:
        if warehouse_item.status not in ("AVAILABLE", "RESERVED"):
            return _failure(
                db,
                scanner,
                external_id,
                raw_payload,
                "PREPROD_WAREHOUSE_ITEM",
                "WAREHOUSE_ITEM_NOT_AVAILABLE",
                f"Grezzo magazzino non disponibile: {warehouse_item.status}",
            )
        pending_pieces = _pending_mapping_pieces(db, scanner)
        warehouse_item.status = "RESERVED"
        warehouse_item.reserved_at = warehouse_item.reserved_at or now
        warehouse_item.reserved_by_scanner_id = scanner.id
        linked_pieces = 0
        for piece in pending_pieces:
            result = _assign_warehouse_origin(
                db,
                scanner,
                piece,
                warehouse_item,
                now,
                raw_payload=raw_payload,
                external_id=external_id,
            )
            if result.get("assigned"):
                linked_pieces += 1
        if pending_pieces:
            scanner.current_warehouse_item_id = None
            scanner.current_warehouse_item_set_at = None
            message = f"Grezzo collegato a {linked_pieces} pezzi"
        else:
            scanner.current_warehouse_item_id = warehouse_item.id
            scanner.current_warehouse_item_set_at = now
            message = "Grezzo selezionato: ora scansiona i pezzi da collegare"
        _attempt(
            db,
            scanner,
            external_id,
            raw_payload,
            "PREPROD_WAREHOUSE_ITEM",
            "OK",
            message,
        )
        db.commit()
        return _response(
            1,
            message,
            ok=True,
            scan_kind="PREPROD_WAREHOUSE_ITEM",
            warehouse_item_id=warehouse_item.id,
            warehouse_item_uuid=warehouse_item.uuid,
            linked_pieces=linked_pieces,
        )

    piece_matches = db.query(Piece).filter(
        or_(Piece.qr_code == value, Piece.qr_payload == value, Piece.uuid == value.lower()),
        Piece.qr_attivo.is_(True),
    ).all()
    exact_uuid = [row for row in piece_matches if row.uuid.lower() == value.lower()]
    exact_payload = [row for row in piece_matches if row.qr_payload == value]
    candidates = exact_uuid or exact_payload or piece_matches
    if not candidates:
        return _failure(db, scanner, external_id, raw_payload, "PREPROD_UNKNOWN", "QR_NOT_RECOGNIZED", "QR non riconosciuto")
    if len(candidates) != 1:
        return _failure(db, scanner, external_id, raw_payload, "PREPROD_PIECE", "AMBIGUOUS_PIECE_QR", "QR associato a più pezzi attivi")

    piece = candidates[0]
    current_warehouse_item = _current_warehouse_item(db, scanner, now)
    if current_warehouse_item and current_warehouse_item.status in ("AVAILABLE", "RESERVED"):
        if piece.materiale_origine_id and piece.materiale_origine_id != current_warehouse_item.id:
            return _failure(
                db,
                scanner,
                external_id,
                raw_payload,
                "PREPROD_PIECE",
                "PIECE_ALREADY_MAPPED",
                f"Pezzo {piece.qr_code} già collegato a un altro grezzo",
                piece=piece,
            )
        result = _assign_warehouse_origin(
            db,
            scanner,
            piece,
            current_warehouse_item,
            now,
            raw_payload=raw_payload,
            external_id=external_id,
        )
        db.commit()
        return _response(
            1,
            result["message"],
            ok=True,
            scan_kind="PREPROD_PIECE_ASSIGNED" if result.get("assigned") else "PREPROD_PIECE_ALREADY_ASSIGNED",
            piece_id=piece.id,
            qr_code=piece.qr_code,
            warehouse_material=result["material"],
        )

    if piece.materiale_origine_id:
        return _failure(
            db,
            scanner,
            external_id,
            raw_payload,
            "PREPROD_PIECE",
            "PIECE_ALREADY_MAPPED",
            f"Pezzo {piece.qr_code} già collegato a un grezzo",
            piece=piece,
        )
    if piece.materiale_origine_status == "IN_ATTESA_GREZZO" and piece.materiale_origine_scanner_id == scanner.id:
        message = f"Pezzo {piece.qr_code} già in attesa grezzo"
        _attempt(
            db,
            scanner,
            external_id,
            raw_payload,
            "PREPROD_PIECE_ALREADY_PENDING",
            "OK",
            message,
            piece=piece,
        )
        db.commit()
        return _response(
            1,
            message,
            ok=True,
            scan_kind="PREPROD_PIECE_ALREADY_PENDING",
            piece_id=piece.id,
            qr_code=piece.qr_code,
        )

    _mark_piece_pending(db, scanner, piece, now, raw_payload=raw_payload, external_id=external_id)
    db.commit()
    return _response(
        1,
        f"Pezzo {piece.qr_code} in attesa grezzo",
        ok=True,
        scan_kind="PREPROD_PIECE_PENDING",
        piece_id=piece.id,
        qr_code=piece.qr_code,
    )
