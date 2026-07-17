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


def _event_label(value: str | None) -> str | None:
    labels = {
        "PIECE_READ": "Pezzo letto",
        "PHASE_START": "Fase iniziata",
        "PHASE_DONE": "Fase completata",
        "PHASE_END": "Fase finita",
        "MATERIAL_ASSIGNED": "Grezzo collegato",
        "MATERIAL_PENDING": "Pezzo in attesa grezzo",
    }
    return labels.get(value or "", value)


def _status_label(value: str | None) -> str:
    labels = {
        "DA_PRODURRE": "Da produrre",
        "IN_LAVORAZIONE": "In lavorazione",
        "COMPLETATO": "Completato",
        "AVAILABLE": "Disponibile",
        "RESERVED": "Prenotato",
        "OUT": "Uscito",
        "CONSUMED": "Consumato",
    }
    return labels.get(value or "", value or "—")


def _join_parts(*parts) -> str:
    return " · ".join(str(part) for part in parts if part not in (None, ""))


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
        derived_commesse = {
            row.id: row
            for row in db.query(Commessa).filter(Commessa.id.in_({piece.commessa_id for piece in derived})).all()
        } if derived else {}
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
        warehouse_subtitle = _join_parts(
            "Grezzo magazzino",
            _status_label(warehouse.status),
            warehouse.tipo or material.tipo,
            warehouse.profilo or material.profilo,
            warehouse.qualita or material.qualita,
        )
        return {
            "entity": "WAREHOUSE_ITEM",
            "entity_label": "Grezzo di magazzino",
            "id": warehouse.id,
            "uuid": warehouse.uuid,
            "code": f"{material.code} · #{warehouse.ordinal:04d}",
            "status": warehouse.status,
            "status_label": _status_label(warehouse.status),
            "subtitle": warehouse_subtitle,
            "qr_image_url": f"/qr-image/{warehouse.uuid}.png",
            "fields": {key: _plain(val) for key, val in fields.items()},
            "origin": None,
            "dependencies": [
                {
                    "uuid": row.uuid,
                    "code": row.qr_code,
                    "status": row.stato_attuale,
                    "status_label": _status_label(row.stato_attuale),
                    "subtitle": _join_parts(
                        _status_label(row.stato_attuale),
                        derived_commesse.get(row.commessa_id).codice if derived_commesse.get(row.commessa_id) else None,
                        row.assemblato_id,
                        row.profilo,
                    ),
                }
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
    workshop_events = [row for row in events if row.event_type not in ("MATERIAL_ASSIGNED", "MATERIAL_PENDING")]
    sessions = {
        row.id: row
        for row in db.query(PieceWorkSession).filter(PieceWorkSession.piece_id == piece.id).all()
    }
    workstation_codes = sorted({row.postazione_code for row in workshop_events if row.postazione_code})
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
        "Ultimo evento": _event_label(piece.ultimo_evento),
        "Ultimo aggiornamento": piece.ultimo_evento_at,
    }
    piece_subtitle = _join_parts(
        _status_label(piece.stato_attuale),
        commessa.codice if commessa else None,
        piece.assemblato_id,
        piece.profilo,
    )
    return {
        "entity": "PIECE",
        "entity_label": "Pezzo da distinta",
        "id": piece.id,
        "uuid": piece.uuid,
        "code": piece.qr_code,
        "status": piece.stato_attuale,
        "status_label": _status_label(piece.stato_attuale),
        "subtitle": piece_subtitle,
        "qr_image_url": f"data:image/png;base64,{generate_qr_for_payload(piece.qr_payload)}",
        "fields": {key: _plain(val) for key, val in fields.items()},
        "origin": (
            {
                "uuid": origin.uuid,
                "code": origin.material.code,
                "status": origin.status,
                "status_label": _status_label(origin.status),
                "commessa": origin.reserved_for_commessa,
                "reserved_at": origin.reserved_at,
                "subtitle": _join_parts("Grezzo collegato", origin.material.code, _status_label(origin.status), origin.reserved_for_commessa),
            }
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
            for row in workshop_events
        ],
    }
