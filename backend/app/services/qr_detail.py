"""Scheda unificata, read-only, per ogni QR fisico."""
from __future__ import annotations

import json
import re
from decimal import Decimal

from sqlalchemy import or_
from sqlalchemy.orm import Session

from backend.app.models.commessa import Commessa, Piece, PieceScanEvent, PieceWorkSession, Workstation
from backend.app.models.warehouse import WarehouseItem
from backend.app.services.qr import generate_qr_for_payload


def _value(raw: str) -> str:
    value = (raw or "").strip()
    match = re.search(r"/p/([^/?#]+)", value, re.IGNORECASE)
    if match:
        return match.group(1).strip()
    try:
        data = json.loads(value)
        return str(data.get("uuid") or data.get("id") or data.get("qr_code") or value).strip()
    except (json.JSONDecodeError, TypeError, AttributeError):
        return value


def _plain(value):
    if isinstance(value, Decimal):
        return float(value)
    return value


def build_qr_detail(db: Session, raw: str) -> dict:
    value = _value(raw)
    warehouse = db.query(WarehouseItem).filter(WarehouseItem.uuid == value.lower()).first()
    if warehouse:
        material = warehouse.material
        derived = (
            db.query(Piece)
            .filter(Piece.materiale_origine_id == warehouse.id)
            .order_by(Piece.qr_code)
            .all()
        )
        fields = {
            "UUID": warehouse.uuid,
            "Codice": material.code,
            "Tipo": warehouse.tipo or material.tipo,
            "Profilo": warehouse.profilo or material.profilo,
            "Dimensioni": warehouse.dimensioni or material.dimensioni,
            "Norma": warehouse.norma_uni or material.norma_uni,
            "Qualità": warehouse.qualita or material.qualita,
            "Colata": warehouse.colata or material.colata,
            "Uso": warehouse.uso_materiale or material.uso_materiale,
            "Posizione": warehouse.posizione or material.posizione,
            "Stato": warehouse.status,
            "Prenotato per": warehouse.reserved_for_commessa,
            "Prenotato il": warehouse.reserved_at,
            "Peso unitario kg": warehouse.peso_1_pz or material.peso_1_pz,
            "Note": warehouse.notes,
        }
        return {
            "entity": "WAREHOUSE_ITEM",
            "entity_label": "Grezzo di magazzino",
            "id": warehouse.id,
            "uuid": warehouse.uuid,
            "code": f"{material.code} · #{warehouse.ordinal:04d}",
            "status": warehouse.status,
            "qr_image_url": f"/qr-image/{warehouse.uuid}.png",
            "fields": {key: _plain(val) for key, val in fields.items()},
            "origin": None,
            "dependencies": [
                {"uuid": row.uuid, "code": row.qr_code, "type": "PIECE", "status": row.stato_attuale}
                for row in derived
            ],
            "timeline": [],
        }

    matches = db.query(Piece).filter(
        or_(Piece.uuid == value.lower(), Piece.qr_payload == value, Piece.qr_code == value),
        Piece.qr_attivo.is_(True),
    ).all()
    exact = [row for row in matches if row.uuid.lower() == value.lower()]
    candidates = exact or matches
    if len(candidates) != 1:
        if len(candidates) > 1:
            raise ValueError("QR associato a più pezzi attivi")
        raise LookupError("QR non riconosciuto")
    piece = candidates[0]
    commessa = db.get(Commessa, piece.commessa_id)
    origin = db.get(WarehouseItem, piece.materiale_origine_id) if piece.materiale_origine_id else None
    events = (
        db.query(PieceScanEvent)
        .filter(PieceScanEvent.piece_id == piece.id)
        .order_by(PieceScanEvent.timestamp.desc(), PieceScanEvent.id.desc())
        .all()
    )
    sessions = {
        row.id: row
        for row in db.query(PieceWorkSession).filter(PieceWorkSession.piece_id == piece.id).all()
    }
    workstation_codes = sorted({row.postazione_code for row in events if row.postazione_code})
    workstation_names = {
        row.code: row.name
        for row in db.query(Workstation).filter(Workstation.code.in_(workstation_codes)).all()
    } if workstation_codes else {}
    fields = {
        "UUID": piece.uuid,
        "Codice pezzo": piece.qr_code,
        "Marca posizione": piece.marca_pos,
        "Progressivo": piece.progressivo,
        "Commessa": commessa.codice if commessa else piece.commessa_id,
        "Revisione": piece.revisione_id,
        "Assemblato": piece.assemblato_id,
        "Tipo profilo": piece.tipo_profilo,
        "Profilo": piece.profilo,
        "Materiale": piece.materiale,
        "Descrizione materiale": piece.materiale_descrizione,
        "Lunghezza mm": piece.lunghezza_mm,
        "Larghezza mm": piece.larghezza_mm,
        "Spessore mm": piece.spessore_mm,
        "Peso kg": piece.peso_kg,
        "Colata": piece.colata,
        "Lotto": piece.lotto,
        "Certificato 3.1": piece.certificato_31,
        "Fornitore": piece.fornitore,
        "Stato": piece.stato_attuale,
        "Ultima postazione": piece.ultima_postazione,
        "Ultimo evento": piece.ultimo_evento,
        "Ultimo aggiornamento": piece.ultimo_evento_at,
    }
    return {
        "entity": "PIECE",
        "entity_label": "Pezzo da distinta",
        "id": piece.id,
        "uuid": piece.uuid,
        "code": piece.qr_code,
        "status": piece.stato_attuale,
        "qr_image_url": f"data:image/png;base64,{generate_qr_for_payload(piece.qr_payload)}",
        "fields": {key: _plain(val) for key, val in fields.items()},
        "origin": (
            {"uuid": origin.uuid, "code": origin.material.code, "status": origin.status}
            if origin else None
        ),
        "dependencies": [],
        "timeline": [
            {
                "event": row.event_type,
                "timestamp": row.timestamp,
                "workstation": row.postazione_code,
                "workstation_label": workstation_names.get(row.postazione_code) or row.postazione_code,
                "duration_seconds": (
                    sessions[row.session_id].duration_seconds
                    if row.session_id in sessions and row.event_type == "PHASE_END" else None
                ),
            }
            for row in events
        ],
    }
