"""F2 Officina — endpoints per l'app mobile operatore."""
from __future__ import annotations

import re
from datetime import datetime
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session

from backend.app.core.auth import require_auth
from backend.app.db.session import get_db
from backend.app.models.commessa import Commessa, CommessaStatus
from backend.app.models.user import User
from backend.app.models.warehouse import DistintaItem, ScanEvento

router = APIRouter()

# Postazioni fisse per gruppo
GRUPPI_POSTAZIONI: list[dict] = [
    {
        "gruppo": "Officina",
        "postazioni": [
            "Taglio Laser",
            "Taglio Standard",
            "Forature",
            "Puntature",
            "Saldature Finali / Assemblaggio",
        ],
    },
    {
        "gruppo": "Preparazione Esterno",
        "postazioni": ["Verniciatura", "Zincatura"],
    },
    {
        "gruppo": "Cantiere",
        "postazioni": ["Consegna cantiere"],
    },
]

ALL_POSTAZIONI: set[str] = {
    p for g in GRUPPI_POSTAZIONI for p in g["postazioni"]
}


def _is_lamiera(description: str | None) -> bool:
    """True se il profilo normalizzato è una lamiera (inizia con PL o FL)."""
    return bool(description and re.match(r'^(PL|FL)\d', description.upper()))


# ── Commesse IN_PRODUZIONE ────────────────────────────────────────────────────

@router.get("/commesse")
def list_commesse(
    db: Session = Depends(get_db),
    _: User = Depends(require_auth),
):
    rows = (
        db.query(Commessa)
        .filter(Commessa.status == CommessaStatus.IN_PRODUZIONE)
        .order_by(Commessa.codice)
        .all()
    )
    return [
        {
            "id":                    c.id,
            "codice":                c.codice,
            "cliente":               c.cliente,
            "data_consegna_prevista": str(c.data_consegna_prevista) if c.data_consegna_prevista else None,
        }
        for c in rows
    ]


# ── Postazioni della commessa ─────────────────────────────────────────────────

@router.get("/{commessa_id}/postazioni")
def list_postazioni(
    commessa_id: int,
    db: Session = Depends(get_db),
    _: User = Depends(require_auth),
):
    commessa = db.get(Commessa, commessa_id)
    if not commessa:
        raise HTTPException(404, "Commessa non trovata")

    n_lamiera = (
        db.query(DistintaItem)
        .filter(DistintaItem.commessa_id == commessa_id)
        .count()
    )
    # Verifica se ci sono lamiere per decidere se mostrare Taglio Laser
    lamiere = (
        db.query(DistintaItem)
        .filter(
            DistintaItem.commessa_id == commessa_id,
            DistintaItem.description.op("GLOB")("PL*"),
        )
        .count()
    )

    # Carica tutti i pezzi della commessa con uuid
    all_items = (
        db.query(DistintaItem)
        .filter(
            DistintaItem.commessa_id == commessa_id,
            DistintaItem.invalidato.is_(False),
            DistintaItem.description.isnot(None),
        )
        .all()
    )
    uuids = [it.uuid for it in all_items if it.uuid]

    # Ultimi eventi per postazione per ogni uuid
    eventi = (
        db.query(ScanEvento)
        .filter(ScanEvento.item_uuid.in_(uuids))
        .order_by(ScanEvento.timestamp.desc())
        .all()
    ) if uuids else []

    # {(uuid, postazione) → tipo_evento più recente}
    last_event: dict[tuple, str] = {}
    for e in eventi:
        key = (e.item_uuid, e.postazione)
        if key not in last_event:
            last_event[key] = e.tipo_evento

    def _counts(pezzi_ids: list[str], pst: str) -> dict:
        attesa = in_corso = completati = 0
        for uuid in pezzi_ids:
            ev = last_event.get((uuid, pst))
            if ev == "FINE_LAVORO":
                completati += 1
            elif ev == "INIZIO_LAVORO":
                in_corso += 1
            else:
                attesa += 1
        return {"attesa": attesa, "in_corso": in_corso, "completati": completati}

    laser_uuids = [it.uuid for it in all_items if it.uuid and _is_lamiera(it.description)]
    std_uuids   = [it.uuid for it in all_items if it.uuid and not _is_lamiera(it.description)]
    all_uuids   = [it.uuid for it in all_items if it.uuid]

    def _pst_uuids(pst: str) -> list[str]:
        if pst == "Taglio Laser":   return laser_uuids
        if pst == "Taglio Standard": return std_uuids
        return all_uuids

    result = []
    for g in GRUPPI_POSTAZIONI:
        postazioni_out = []
        for p in g["postazioni"]:
            if p == "Taglio Laser" and not laser_uuids:
                continue
            counts = _counts(_pst_uuids(p), p)
            postazioni_out.append({
                "nome":       p,
                "attesa":     counts["attesa"],
                "in_corso":   counts["in_corso"],
                "completati": counts["completati"],
            })
        if postazioni_out:
            result.append({"gruppo": g["gruppo"], "postazioni": postazioni_out})
    return result


# ── Pezzi per postazione ──────────────────────────────────────────────────────

@router.get("/{commessa_id}/postazioni/{postazione}/pezzi")
def list_pezzi(
    commessa_id: int,
    postazione: str,
    db: Session = Depends(get_db),
    _: User = Depends(require_auth),
):
    commessa = db.get(Commessa, commessa_id)
    if not commessa:
        raise HTTPException(404, "Commessa non trovata")

    # Recupera pezzi della commessa assegnati a questa postazione
    query = db.query(DistintaItem).filter(
        DistintaItem.commessa_id == commessa_id,
        DistintaItem.invalidato.is_(False),
        DistintaItem.description.isnot(None),
    )

    if postazione == "Taglio Laser":
        all_items = [it for it in query.all() if _is_lamiera(it.description)]
    elif postazione == "Taglio Standard":
        all_items = [it for it in query.all() if not _is_lamiera(it.description)]
    else:
        # Postazioni successive: pezzi che hanno FINE_LAVORO alla postazione precedente
        # Per ora mostra tutti — in futuro si aggiungerà la progressione
        all_items = query.all()

    if not all_items:
        return []

    # Legge ultimi eventi per ogni uuid
    uuids = [it.uuid for it in all_items if it.uuid]
    eventi = (
        db.query(ScanEvento)
        .filter(
            ScanEvento.item_uuid.in_(uuids),
            ScanEvento.postazione == postazione,
        )
        .order_by(ScanEvento.timestamp.desc())
        .all()
    )
    # Mappa uuid → ultimo evento
    ultimo_per_uuid: dict[str, ScanEvento] = {}
    for e in eventi:
        if e.item_uuid not in ultimo_per_uuid:
            ultimo_per_uuid[e.item_uuid] = e

    def _stato(uuid: str) -> str:
        ev = ultimo_per_uuid.get(uuid)
        if not ev:
            return "in_attesa"
        return "in_corso" if ev.tipo_evento == "INIZIO_LAVORO" else "completato"

    def _ts(uuid: str) -> str | None:
        ev = ultimo_per_uuid.get(uuid)
        return ev.timestamp.isoformat() if ev else None

    pezzi = [
        {
            "id":          it.id,
            "uuid":        it.uuid,
            "part_number": it.part_number,
            "description": it.description,
            "length_mm":   float(it.length_mm) if it.length_mm else None,
            "stato":       _stato(it.uuid or ""),
            "timestamp":   _ts(it.uuid or ""),
        }
        for it in all_items
        if it.uuid
    ]

    # Ordine: in_corso → in_attesa → completato
    order = {"in_corso": 0, "in_attesa": 1, "completato": 2}
    pezzi.sort(key=lambda p: order.get(p["stato"], 99))
    return pezzi


# ── Scan evento ───────────────────────────────────────────────────────────────

class ScanRequest(BaseModel):
    uuid: str
    postazione: str


@router.post("/scan")
def scan(
    req: ScanRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_auth),
):
    """Toggle scan su un pezzo per una postazione specifica.

    INIZIO_LAVORO → FINE_LAVORO (pezzo completato a questa postazione)
    Se già FINE_LAVORO → errore 409.
    """
    import re as _re
    # Estrai UUID da URL o raw
    raw = req.uuid.strip()
    m = _re.search(r'/p/([0-9a-f-]{36})', raw, _re.IGNORECASE)
    uuid = m.group(1).lower() if m else raw.lower()

    item = db.query(DistintaItem).filter(DistintaItem.uuid == uuid).first()
    if not item:
        raise HTTPException(404, f"Pezzo non trovato (uuid={uuid})")

    if req.postazione not in ALL_POSTAZIONI:
        raise HTTPException(422, f"Postazione non valida: {req.postazione}")

    # Ultimo evento per questo pezzo+postazione
    ultimo = (
        db.query(ScanEvento)
        .filter(ScanEvento.item_uuid == uuid, ScanEvento.postazione == req.postazione)
        .order_by(ScanEvento.timestamp.desc())
        .first()
    )

    if ultimo and ultimo.tipo_evento == "FINE_LAVORO":
        raise HTTPException(409, "Pezzo già completato a questa postazione.")

    tipo = "FINE_LAVORO" if (ultimo and ultimo.tipo_evento == "INIZIO_LAVORO") else "INIZIO_LAVORO"

    evento = ScanEvento(
        item_uuid   = uuid,
        utente_id   = current_user.id,
        postazione  = req.postazione,
        timestamp   = datetime.utcnow(),
        tipo_evento = tipo,
    )
    db.add(evento)
    db.commit()

    return {
        "tipo_evento": tipo,
        "uuid":        uuid,
        "part_number": item.part_number,
        "description": item.description,
        "postazione":  req.postazione,
        "timestamp":   evento.timestamp.isoformat(),
        "completato":  tipo == "FINE_LAVORO",
        "messaggio":   "🏁 Completato" if tipo == "FINE_LAVORO" else "▶ Iniziato",
    }
