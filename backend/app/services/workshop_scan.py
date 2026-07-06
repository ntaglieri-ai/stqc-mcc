"""Motore append-only per le scansioni di officina."""
from __future__ import annotations

import json
import re
from datetime import datetime, timedelta

from sqlalchemy import or_
from sqlalchemy.orm import Session

from backend.app.models.commessa import (
    Piece,
    PieceScanEvent,
    PieceWorkSession,
    ScannerDevice,
    WorkshopScanAttempt,
    WorkshopScanBlock,
    Workstation,
)
from backend.app.models.warehouse import DistintaItem


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
    workstation: Workstation | None = None,
    block: WorkshopScanBlock | None = None,
    piece: Piece | None = None,
) -> WorkshopScanAttempt:
    row = WorkshopScanAttempt(
        scanner_device_id=scanner.id,
        scanner_external_id=(external_id or "")[:120] or None,
        workstation_id=workstation.id if workstation else scanner.postazione_id,
        scan_block_id=block.id if block else None,
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


def _response(ply: int, message: str, **details) -> dict:
    return {"ply": ply, "msg": message, **details}


def _failure(
    db: Session,
    scanner: ScannerDevice,
    external_id: str | None,
    raw_payload: str,
    scan_kind: str,
    error_code: str,
    message: str,
    *,
    workstation: Workstation | None = None,
    block: WorkshopScanBlock | None = None,
    piece: Piece | None = None,
    warning: bool = False,
) -> dict:
    _attempt(
        db,
        scanner,
        external_id,
        raw_payload,
        scan_kind,
        "WARNING" if warning else "ERROR",
        message,
        error_code=error_code,
        workstation=workstation,
        block=block,
        piece=piece,
    )
    scanner.last_seen_at = datetime.utcnow()
    db.commit()
    return _response(
        2 if warning else 3,
        message,
        ok=False,
        error_code=error_code,
        scan_kind=scan_kind,
    )


def process_workshop_scan(
    db: Session,
    scanner: ScannerDevice,
    raw_payload: str,
    external_id: str | None = None,
) -> dict:
    """Applica la sequenza POSTAZIONE_START → PEZZI → POSTAZIONE_END."""
    raw_payload = (raw_payload or "").strip()
    scanner.last_seen_at = datetime.utcnow()
    assigned_workstation = db.get(Workstation, scanner.postazione_id) if scanner.postazione_id else None
    if not scanner.active:
        return _failure(
            db, scanner, external_id, raw_payload, "UNKNOWN",
            "SCANNER_INACTIVE", "Scanner non attivo",
        )
    if not assigned_workstation:
        return _failure(
            db, scanner, external_id, raw_payload, "UNKNOWN",
            "SCANNER_WITHOUT_WORKSTATION", "Scanner senza postazione",
        )
    if not assigned_workstation.active:
        return _failure(
            db, scanner, external_id, raw_payload, "UNKNOWN",
            "WORKSTATION_INACTIVE", "Postazione assegnata non attiva",
            workstation=assigned_workstation,
        )
    if not raw_payload:
        return _failure(db, scanner, external_id, "", "UNKNOWN", "EMPTY_PAYLOAD", "QR vuoto")

    value = _scan_value(raw_payload)
    workstation = db.query(Workstation).filter(
        or_(Workstation.start_qr_code == value, Workstation.end_qr_code == value)
    ).first()
    open_block = (
        db.query(WorkshopScanBlock)
        .filter(
            WorkshopScanBlock.scanner_device_id == scanner.id,
            WorkshopScanBlock.status == "OPEN",
        )
        .order_by(WorkshopScanBlock.started_at.desc(), WorkshopScanBlock.id.desc())
        .first()
    )

    if workstation:
        is_start = value == workstation.start_qr_code
        kind = "WORKSTATION_START" if is_start else "WORKSTATION_END"
        if not workstation.active:
            return _failure(
                db, scanner, external_id, raw_payload, kind,
                "WORKSTATION_INACTIVE", "Postazione non attiva", workstation=workstation, block=open_block,
            )
        if scanner.postazione_id != workstation.id:
            return _failure(
                db, scanner, external_id, raw_payload, kind,
                "WRONG_WORKSTATION", "QR di una postazione diversa", workstation=workstation, block=open_block,
            )

        if is_start:
            if open_block:
                return _failure(
                    db, scanner, external_id, raw_payload, kind,
                    "BLOCK_ALREADY_OPEN", "Lavorazione già aperta", workstation=workstation, block=open_block,
                    warning=True,
                )
            now = datetime.utcnow()
            block = WorkshopScanBlock(
                scanner_device_id=scanner.id,
                workstation_id=workstation.id,
                workstation_code=workstation.code,
                status="OPEN",
                started_at=now,
                start_payload=raw_payload,
                piece_count=0,
            )
            db.add(block)
            db.flush()
            _attempt(
                db, scanner, external_id, raw_payload, kind, "OK",
                f"Inizio {workstation.name}", workstation=workstation, block=block,
            )
            db.commit()
            return _response(
                1, f"Inizio {workstation.name}", ok=True, scan_kind=kind,
                block_id=block.id, workstation=workstation.code,
            )

        if not open_block:
            return _failure(
                db, scanner, external_id, raw_payload, kind,
                "NO_OPEN_BLOCK", "Nessuna lavorazione aperta", workstation=workstation,
            )
        if open_block.workstation_id != workstation.id:
            return _failure(
                db, scanner, external_id, raw_payload, kind,
                "WRONG_BLOCK_WORKSTATION", "Fine di una postazione diversa",
                workstation=workstation, block=open_block,
            )

        sessions = (
            db.query(PieceWorkSession)
            .filter(
                PieceWorkSession.scan_block_id == open_block.id,
                PieceWorkSession.status == "OPEN",
            )
            .order_by(PieceWorkSession.id)
            .all()
        )
        if not sessions:
            return _failure(
                db, scanner, external_id, raw_payload, kind,
                "EMPTY_BLOCK", "Nessun pezzo nel blocco", workstation=workstation, block=open_block,
            )

        now = datetime.utcnow()
        for session in sessions:
            piece = db.get(Piece, session.piece_id)
            session.closed_at = now
            session.duration_seconds = max(0, int((now - session.started_at).total_seconds()))
            session.status = "CLOSED"
            session.updated_at = now
            event = PieceScanEvent(
                piece_id=session.piece_id,
                qr_code=piece.qr_code,
                commessa_id=session.commessa_id,
                revisione_id=session.revisione_id,
                assemblato_id=session.assemblato_id,
                postazione_id=workstation.id,
                postazione_code=workstation.code,
                event_type="PHASE_END",
                timestamp=now,
                session_id=session.id,
                scanner_device_id=scanner.id,
                scan_block_id=open_block.id,
                metadata_json={"source": "NETUM", "duration_seconds": session.duration_seconds},
            )
            db.add(event)
            db.flush()
            session.close_event_id = event.id
            piece.stato_attuale = "FASE_COMPLETATA"
            piece.ultima_postazione = workstation.code
            piece.ultimo_evento = "PHASE_END"
            piece.ultimo_evento_at = now
            piece.lavorazione_aperta_id = None
            piece.updated_at = now
            if piece.distinta_item_id:
                distinta_item = db.get(DistintaItem, piece.distinta_item_id)
                if distinta_item:
                    distinta_item.stato_tracciamento = "FASE_COMPLETATA"

        open_block.status = "CLOSED"
        open_block.closed_at = now
        open_block.end_payload = raw_payload
        _attempt(
            db, scanner, external_id, raw_payload, kind, "OK",
            f"Fine {workstation.name}: {len(sessions)} pezzi",
            workstation=workstation, block=open_block,
        )
        db.commit()
        return _response(
            1, f"Fine {workstation.name}: {len(sessions)} pezzi",
            ok=True, scan_kind=kind, block_id=open_block.id,
            workstation=workstation.code, closed_pieces=len(sessions),
        )

    piece_matches = db.query(Piece).filter(
        or_(Piece.qr_code == value, Piece.qr_payload == value, Piece.uuid == value.lower()),
        Piece.qr_attivo.is_(True),
        Piece.qr_status == "ACTIVE",
    ).all()
    if not piece_matches:
        return _failure(
            db, scanner, external_id, raw_payload, "UNKNOWN",
            "QR_NOT_RECOGNIZED", "QR non riconosciuto", block=open_block,
        )
    exact_uuid = [row for row in piece_matches if row.uuid.lower() == value.lower()]
    exact_payload = [row for row in piece_matches if row.qr_payload == value]
    candidates = exact_uuid or exact_payload or piece_matches
    if len(candidates) != 1:
        return _failure(
            db, scanner, external_id, raw_payload, "PIECE",
            "AMBIGUOUS_PIECE_QR", "QR associato a più pezzi attivi", block=open_block,
        )
    piece = candidates[0]
    if not open_block:
        return _failure(
            db, scanner, external_id, raw_payload, "PIECE",
            "NO_OPEN_BLOCK", "Scansionare prima INIZIO postazione", piece=piece,
        )

    workstation = db.get(Workstation, open_block.workstation_id)
    duplicate = db.query(PieceWorkSession).filter(
        PieceWorkSession.scan_block_id == open_block.id,
        PieceWorkSession.piece_id == piece.id,
    ).first()
    if duplicate:
        return _failure(
            db, scanner, external_id, raw_payload, "PIECE",
            "PIECE_ALREADY_IN_BLOCK", "Pezzo già acquisito",
            workstation=workstation, block=open_block, piece=piece, warning=True,
        )
    other_open = db.query(PieceWorkSession).filter(
        PieceWorkSession.piece_id == piece.id,
        PieceWorkSession.status == "OPEN",
    ).first()
    if other_open:
        return _failure(
            db, scanner, external_id, raw_payload, "PIECE",
            "PIECE_ALREADY_IN_PROGRESS", "Pezzo già in lavorazione",
            workstation=workstation, block=open_block, piece=piece,
        )

    now = datetime.utcnow()
    session = PieceWorkSession(
        piece_id=piece.id,
        commessa_id=piece.commessa_id,
        revisione_id=piece.revisione_id,
        assemblato_id=piece.assemblato_id,
        postazione_id=workstation.id,
        postazione_code=workstation.code,
        started_at=now,
        expected_close_at=now + timedelta(hours=24),
        status="OPEN",
        scanner_device_id=scanner.id,
        scan_block_id=open_block.id,
        created_at=now,
        updated_at=now,
    )
    db.add(session)
    db.flush()
    event = PieceScanEvent(
        piece_id=piece.id,
        qr_code=piece.qr_code,
        commessa_id=piece.commessa_id,
        revisione_id=piece.revisione_id,
        assemblato_id=piece.assemblato_id,
        postazione_id=workstation.id,
        postazione_code=workstation.code,
        event_type="PHASE_START",
        timestamp=now,
        session_id=session.id,
        scanner_device_id=scanner.id,
        scan_block_id=open_block.id,
        metadata_json={"source": "NETUM"},
    )
    db.add(event)
    db.flush()
    session.open_event_id = event.id
    open_block.piece_count = int(open_block.piece_count or 0) + 1
    piece.stato_attuale = "IN_LAVORAZIONE"
    piece.ultima_postazione = workstation.code
    piece.ultimo_evento = "PHASE_START"
    piece.ultimo_evento_at = now
    piece.lavorazione_aperta_id = session.id
    piece.updated_at = now
    if piece.distinta_item_id:
        distinta_item = db.get(DistintaItem, piece.distinta_item_id)
        if distinta_item:
            distinta_item.stato_tracciamento = "IN_LAVORAZIONE"
    _attempt(
        db, scanner, external_id, raw_payload, "PIECE", "OK",
        f"Pezzo {piece.qr_code} acquisito",
        workstation=workstation, block=open_block, piece=piece,
    )
    db.commit()
    return _response(
        1, f"Pezzo {piece.qr_code} acquisito", ok=True, scan_kind="PIECE",
        block_id=open_block.id, piece_id=piece.id, qr_code=piece.qr_code,
        workstation=workstation.code,
    )
