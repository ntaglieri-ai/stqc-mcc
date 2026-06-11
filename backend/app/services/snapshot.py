"""Backup pre-commessa e file outcome per prelievi di magazzino."""
from __future__ import annotations

import json
import logging
import re
from datetime import datetime
from pathlib import Path

from sqlalchemy import case, func, select
from sqlalchemy.orm import Session

_logger = logging.getLogger("stqc.snapshot")

_DEFAULT_BACKUP_DIR  = "./backups/precommessa"
_DEFAULT_OUTCOME_DIR = "./outcomes"


def _get_setting(db: Session, key: str, default: str = "") -> str:
    try:
        from backend.app.models.settings import AppSettings
        row = db.get(AppSettings, key)
        return row.value if row and row.value else default
    except Exception:
        return default


def _safe_codice(codice: str) -> str:
    return re.sub(r"[^\w\-]", "_", codice)


def _n_pezzi(db: Session, material_id: int) -> float:
    from backend.app.models.warehouse import MovementType, StockMovement
    val = db.scalar(
        select(
            func.coalesce(
                func.sum(
                    case(
                        (StockMovement.movement_type == MovementType.INCOMING, StockMovement.quantity),
                        else_=0,
                    )
                ),
                0,
            )
            - func.coalesce(
                func.sum(
                    case(
                        (StockMovement.movement_type == MovementType.OUTGOING, StockMovement.quantity),
                        else_=0,
                    )
                ),
                0,
            )
        ).where(StockMovement.material_id == material_id)
    )
    return float(val or 0)


def save_backup_snapshot(db: Session, commessa_codice: str) -> str | None:
    """Salva snapshot JSON di tutti i materiali + giacenze prima di un prelievo.
    Restituisce il path del file o None se il percorso non è configurato o la scrittura fallisce.
    """
    backup_dir = _get_setting(db, "backup_precommessa_path", _DEFAULT_BACKUP_DIR)
    dest = Path(backup_dir)
    dest.mkdir(parents=True, exist_ok=True)

    ts      = datetime.utcnow().strftime("%Y%m%d_%H%M%S")
    fname   = dest / f"backup_{_safe_codice(commessa_codice)}_{ts}.json"

    from backend.app.crud.warehouse import get_magazzino_list
    items = get_magazzino_list(db, limit=10_000)

    payload = {
        "type":      "backup_pre_commessa",
        "timestamp": datetime.utcnow().isoformat(),
        "commessa":  commessa_codice,
        "n_materiali": len(items),
        "materials": items,
    }

    try:
        fname.write_text(json.dumps(payload, ensure_ascii=False, indent=2, default=str), encoding="utf-8")
        _logger.info("Backup pre-commessa salvato: %s", fname)
        return str(fname)
    except Exception as exc:
        _logger.warning("Impossibile salvare backup pre-commessa: %s", exc)
        return None


def save_outcome(db: Session, commessa_codice: str) -> str | None:
    """Genera file JSON con tutti i materiali prelevati per la commessa (righe con commessa_ref).
    Aggiorna il file ad ogni prelievo aggiuntivo (timestamp nel nome garantisce unicità per sessione).
    """
    outcome_dir = _get_setting(db, "outcome_path", _DEFAULT_OUTCOME_DIR)
    dest = Path(outcome_dir)
    dest.mkdir(parents=True, exist_ok=True)

    ts    = datetime.utcnow().strftime("%Y%m%d_%H%M%S")
    fname = dest / f"outcome_{_safe_codice(commessa_codice)}_{ts}.json"

    from backend.app.models.warehouse import Material
    materials = db.scalars(
        select(Material).where(Material.commessa_ref == commessa_codice)
    ).all()

    records = []
    for mat in materials:
        n = _n_pezzi(db, mat.id)
        peso_kg = round(float(mat.peso_1_pz) * n, 3) if mat.peso_1_pz else None
        records.append({
            "material_code": mat.code,
            "tipo":          mat.tipo,
            "profilo":       mat.profilo,
            "dimensioni":    mat.dimensioni,
            "qualita":       mat.qualita,
            "colata":        mat.colata,
            "n_pezzi":       n,
            "peso_kg":       peso_kg,
            "norma_uni":     mat.norma_uni,
            "commessa":      commessa_codice,
            "timestamp":     datetime.utcnow().isoformat(),
        })

    payload = {
        "type":             "outcome",
        "timestamp":        datetime.utcnow().isoformat(),
        "commessa":         commessa_codice,
        "totale_voci":      len(records),
        "materiali_prelevati": records,
    }

    try:
        fname.write_text(json.dumps(payload, ensure_ascii=False, indent=2, default=str), encoding="utf-8")
        _logger.info("Outcome commessa %s salvato: %s", commessa_codice, fname)
        return str(fname)
    except Exception as exc:
        _logger.warning("Impossibile salvare outcome: %s", exc)
        return None
