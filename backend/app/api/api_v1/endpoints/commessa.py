import logging
import csv
import json
import re
import shutil
import tempfile
import unicodedata
from collections import defaultdict
from datetime import datetime, timedelta
from pathlib import Path
from typing import List, Optional
from urllib.parse import quote

from fastapi import APIRouter, Depends, File, Form, HTTPException, Query, UploadFile
from fastapi.responses import Response
from pydantic import BaseModel, Field
from sqlalchemy import or_
from sqlalchemy.orm import Session, joinedload

from backend.app.core.config import settings
from backend.app.crud import commessa as crud
from backend.app.db.session import get_db

_logger = logging.getLogger("stqc.commessa")

from backend.app.models.commessa import (
    Commessa, CommessaBulloneria, CommessaDocumento, CommessaPostOfficinaItem, CommessaRevisione, CommessaStatus, DdtManualItem, DdtShipment, FaseOperativa, FaseStatus, Piece, PieceScanEvent, PieceWorkSession, PezzoPercorso, PezzoStato, ScannerDevice, SpedizioneAdHoc, SpedizioneAdHocItem, WorkshopScanAttempt, WorkshopScanBlock, Workstation,
)
from backend.app.models.warehouse import DistintaImport, DistintaItem, Material, MovementType, StockMovement, WarehouseItem
from backend.app.schemas.commessa import CommessaCreate, CommessaRead, CommessaUpdate
from backend.app.services.distinta import (
    ALIASES,
    _build_col_map,
    _extract_project_metadata,
    _extract_rows,
    _find_header_row,
    normalized_to_db_bulk,
    parse_commessa_files,
)
from backend.app.services.bulloneria import parse_bulloneria_file
from backend.app.services.fasi_operative import parse_fasi_operative
from backend.app.services.commessa_analysis import classify_commessa_materials
from backend.app.services.qr import generate_qr_for_payload
from backend.app.services.label import (
    commessa_display_name,
    format_piece_label_payload,
    generate_piece_label_pdf,
    generate_piece_labels_pdf,
)
from backend.app.services.preproduction_scan import process_preproduction_scan
from backend.app.services.workshop_scan import process_workshop_scan

router = APIRouter()


class PieceManualUpdate(BaseModel):
    tipo: Optional[str] = None
    profilo: Optional[str] = None
    qualita: Optional[str] = None
    assemblato: Optional[str] = None
    stato: Optional[str] = None
    nota: Optional[str] = None


class PieceLabelsRequest(BaseModel):
    piece_ids: list[int] = Field(..., min_length=1, max_length=2000)
    width_mm: float = Field(70, ge=40, le=210)
    height_mm: float = Field(120, ge=40, le=297)


class MouseScanRequest(BaseModel):
    payload: str


class SpedizioneAdHocEmptyCreate(BaseModel):
    titolo: str
    note: Optional[str] = None


class ShippingItemManualFound(BaseModel):
    source: Optional[str] = None


class DdtManualTextCreate(BaseModel):
    text: str


def _warehouse_item_mapping_read(item: WarehouseItem, pieces: list[Piece]) -> dict:
    material = item.material
    material_code = getattr(material, "code", None) or item.uuid
    return {
        "uuid": item.uuid,
        "material_code": material_code,
        "label": f"{material_code} · #{item.ordinal:04d}",
        "tipo": item.tipo or getattr(material, "tipo", None),
        "profilo": item.profilo or getattr(material, "profilo", None),
        "dimensioni": item.dimensioni or getattr(material, "dimensioni", None),
        "qualita": item.qualita or getattr(material, "qualita", None),
        "status": item.status,
        "reserved_for_commessa": item.reserved_for_commessa,
        "reserved_at": item.reserved_at,
        "pieces_count": len(pieces),
        "pieces": [
            {
                "uuid": piece.uuid,
                "qr_code": piece.qr_code,
                "marca_pos": piece.marca_pos,
                "progressivo": piece.progressivo,
                "profilo": piece.profilo,
                "materiale": piece.materiale,
                "assemblato": piece.assemblato_id,
                "stato": piece.stato_attuale,
                "assigned_at": piece.materiale_origine_assigned_at,
            }
            for piece in pieces
        ],
    }


def _piece_qr_read(item: Piece) -> dict:
    return {
        "id": item.id,
        "uuid": item.uuid,
        "distinta_item_id": item.distinta_item_id,
        "qr_code": item.qr_code,
        "part_number": item.marca_pos,
        "marca_pos": item.marca_pos,
        "instance_number": item.progressivo,
        "progressivo": item.progressivo,
        "commessa_id": item.commessa_id,
        "revisione": item.revisione_id,
        "categoria": _piece_category_from_qr_piece(item),
        "tipo": item.tipo_profilo,
        "profilo": item.profilo,
        "qualita": item.materiale,
        "materiale": item.materiale,
        "materiale_descrizione": item.materiale_descrizione,
        "assemblato": item.assemblato_id,
        "stato": item.stato_attuale,
        "lunghezza_mm": float(item.lunghezza_mm) if item.lunghezza_mm is not None else None,
        "larghezza_mm": float(item.larghezza_mm) if item.larghezza_mm is not None else None,
        "spessore_mm": float(item.spessore_mm) if item.spessore_mm is not None else None,
        "peso_kg": float(item.peso_kg) if item.peso_kg is not None else None,
        "colata": item.colata,
        "lotto": item.lotto,
        "certificato_31": item.certificato_31,
        "fornitore": item.fornitore,
        "ultima_postazione": item.ultima_postazione,
        "ultimo_evento": item.ultimo_evento,
        "ultimo_aggiornamento": item.ultimo_evento_at,
        "nota": item.note_materiale,
        "materiale_origine_status": item.materiale_origine_status,
        "materiale_origine_id": item.materiale_origine_id,
        "qr_image_url": f"/piece-qr-image/{item.uuid}.png",
        "resolve_url": f"/p/{item.uuid}",
        "qr_payload": item.qr_payload,
        "label_url": f"/api/v1/commesse/{item.commessa_id}/step-5-1/items/{item.id}/label.pdf",
    }


def _piece_category_from_qr_piece(item: Piece) -> str:
    text = " ".join(str(value or "") for value in (
        item.tipo_profilo,
        item.profilo,
        item.materiale_descrizione,
        item.marca_pos,
    )).upper()
    if any(token in text for token in ("DADO", "RONDELL", "VITE", "BULL", "BOLT", "TIRAFON", "BARRA FILETTATA", "PIOLO")):
        return "Bulloneria"
    if any(token in text for token in ("LAMIERA", "PIATTO", "PIATTI", "PL")):
        return "Lamiere / piatti"
    if any(token in text for token in ("TRAVE", "IPE", "HEA", "HEB", "UPN")):
        return "Travi"
    if any(token in text for token in ("TUBO", "RHS", "SHS", "TUBE", "SCATOL")):
        return "Tubolari / scatolati"
    profile = str(item.profilo or "").upper().strip()
    if "ANGOL" in text or profile.startswith("L"):
        return "Angolari"
    if "TONDO" in text:
        return "Tondi"
    if "QUADRO" in text:
        return "Quadri"
    return item.tipo_profilo or "Altro"


def _unique_commessa_code(db: Session, title: str, *, prefix: str = "SPED") -> str:
    base = re.sub(r"[^A-Za-z0-9_-]+", "-", (title or "").strip()).strip("-").upper()
    if not base:
        base = prefix
    if not base.startswith(prefix):
        base = f"{prefix}-{base}"
    base = base[:72].strip("-") or prefix
    candidate = base
    counter = 2
    while db.query(Commessa.id).filter(Commessa.codice == candidate).first():
        suffix = f"-{counter}"
        candidate = f"{base[:100 - len(suffix)]}{suffix}"
        counter += 1
    return candidate


def _piece_qr_code(part_number: str | None, instance_number: int | None, fallback_id: int | None = None) -> str:
    base = (part_number or "").strip()
    if not base:
        base = f"PEZZO-{fallback_id or 'SENZA-CODICE'}"
    if instance_number is not None:
        return f"{base}-{int(instance_number):03d}"
    return base


def _piece_totals(pieces: list[Piece]) -> dict[str, int]:
    totals: dict[str, int] = defaultdict(int)
    for piece in pieces:
        totals[piece.marca_pos or ""] += 1
    return totals


def _expected_piece_payload(piece: Piece, commessa: Commessa, totals: dict[str, int]) -> str:
    return format_piece_label_payload(
        commessa_display_name(commessa),
        piece.marca_pos,
        piece.progressivo,
        totals.get(piece.marca_pos or "", 1),
        float(piece.peso_kg) if piece.peso_kg is not None else None,
    )


def _create_piece_from_item(
    db: Session,
    item: DistintaItem,
    commessa_id: int,
    revisione_id: int,
) -> Piece:
    progressivo = int(item.instance_number or 1)
    qr_code = _piece_qr_code(item.part_number, item.instance_number, item.id)
    piece = Piece(
        qr_code=qr_code,
        qr_payload=qr_code,
        commessa_id=commessa_id,
        revisione_id=revisione_id,
        distinta_item_id=item.id,
        assemblato_id=item.parent_assembly,
        marca_pos=item.part_number or f"PEZZO-{item.id}",
        progressivo=progressivo,
        profilo=item.description,
        materiale=item.material_code,
        materiale_descrizione=item.material_description,
        lunghezza_mm=item.length_mm,
        larghezza_mm=item.width_mm,
        peso_kg=item.weight_kg,
        tipo_profilo=item.tipo_profilo,
        stato_attuale="NON_GENERATO",
        qr_attivo=False,
    )
    db.add(piece)
    return piece


def _generate_revision_piece_labels(db: Session, commessa: Commessa, revisione: CommessaRevisione) -> int:
    pieces = db.query(Piece).filter(
        Piece.revisione_id == revisione.id,
        Piece.distinta_item_id.isnot(None),
    ).all()
    if not pieces:
        return 0
    totals = _piece_totals(pieces)
    item_ids = [piece.distinta_item_id for piece in pieces if piece.distinta_item_id]
    items_by_id = {
        item.id: item
        for item in db.query(DistintaItem).filter(DistintaItem.id.in_(item_ids)).all()
    } if item_ids else {}
    now = datetime.utcnow()
    for piece in pieces:
        piece.qr_payload = _expected_piece_payload(piece, commessa, totals)
        piece.qr_attivo = True
        piece.qr_status = "ACTIVE"
        if not piece.stato_attuale or piece.stato_attuale == "NON_GENERATO":
            piece.stato_attuale = "DA_PRODURRE"
        piece.updated_at = now
        item = items_by_id.get(piece.distinta_item_id)
        if item:
            item.qr_attivo = True
            if not item.stato_tracciamento or item.stato_tracciamento == "NON_GENERATO":
                item.stato_tracciamento = "DA_PRODURRE"
            item.qr_code = generate_qr_for_payload(piece.qr_payload)
    if revisione.step51_completed_at is None:
        revisione.step51_completed_at = now
    return len(pieces)


def _ensure_revision_qr_consistency(db: Session, revisione: CommessaRevisione, *, force: bool = False) -> int:
    """Rende sempre coerenti i QR già generati per la revisione.

    Regola: se lo step QR è completato, ogni Piece della revisione deve avere
    QR attivo, payload scansionabile e status ACTIVE.
    """
    if revisione.step51_completed_at is None and not force:
        return 0
    now = datetime.utcnow()
    if revisione.step51_completed_at is None and force:
        revisione.step51_completed_at = now
    existing_by_item_id = {
        piece.distinta_item_id: piece
        for piece in db.query(Piece).filter(Piece.revisione_id == revisione.id).all()
        if piece.distinta_item_id
    }
    source_items = (
        db.query(DistintaItem)
        .filter(
            DistintaItem.revisione_id == revisione.id,
            DistintaItem.invalidato.is_(False),
        )
        .order_by(DistintaItem.part_number, DistintaItem.instance_number, DistintaItem.id)
        .all()
    )
    changed = 0
    for item in source_items:
        if item.id not in existing_by_item_id:
            piece = _create_piece_from_item(db, item, revisione.commessa_id, revisione.id)
            db.flush()
            existing_by_item_id[item.id] = piece
            changed += 1
    pieces = db.query(Piece).filter(
        Piece.revisione_id == revisione.id,
        Piece.distinta_item_id.isnot(None),
    ).all()
    commessa = db.get(Commessa, revisione.commessa_id)
    if commessa is None:
        raise ValueError("Commessa della revisione non trovata")
    totals = _piece_totals(pieces)
    item_ids = [piece.distinta_item_id for piece in pieces if piece.distinta_item_id]
    items_by_id = {
        item.id: item
        for item in db.query(DistintaItem).filter(DistintaItem.id.in_(item_ids)).all()
    } if item_ids else {}
    for piece in pieces:
        expected_payload = _expected_piece_payload(piece, commessa, totals)
        payload_changed = piece.qr_payload != expected_payload
        if (
            not piece.qr_attivo
            or piece.qr_status != "ACTIVE"
            or payload_changed
        ):
            piece.qr_attivo = True
            piece.qr_status = "ACTIVE"
            piece.qr_payload = expected_payload
            if not piece.stato_attuale or piece.stato_attuale == "NON_GENERATO":
                piece.stato_attuale = "DA_PRODURRE"
            piece.updated_at = now
            changed += 1
        item = items_by_id.get(piece.distinta_item_id)
        if item and (payload_changed or not item.qr_attivo or item.stato_tracciamento in (None, "NON_GENERATO") or not item.qr_code):
            item.qr_attivo = True
            if not item.stato_tracciamento or item.stato_tracciamento == "NON_GENERATO":
                item.stato_tracciamento = "DA_PRODURRE"
            item.qr_code = generate_qr_for_payload(expected_payload)
            changed += 1
    if changed:
        db.commit()
    return changed


@router.post("", response_model=CommessaRead, status_code=201)
def create_commessa(commessa_in: CommessaCreate, db: Session = Depends(get_db)):
    existing = crud.get_commessa_by_codice(db=db, codice=commessa_in.codice)
    if existing:
        raise HTTPException(status_code=409, detail=f"Commessa '{commessa_in.codice}' già esistente")
    return crud.create_commessa(db=db, obj_in=commessa_in)


@router.get("", response_model=List[CommessaRead])
def list_commesse(
    skip: int = 0,
    limit: int = 100,
    status: str | None = None,
    q: str | None = None,
    db: Session = Depends(get_db),
):
    return crud.get_commesse(db=db, skip=skip, limit=limit, status=status, q=q)


@router.get("/dashboard")
def get_dashboard_commesse(db: Session = Depends(get_db)):
    commesse = crud.get_commesse(db=db, skip=0, limit=1000)
    today_start = datetime.now().replace(hour=0, minute=0, second=0, microsecond=0)
    tomorrow_start = today_start + timedelta(days=1)
    workshop_event_types = {"PIECE_READ", "PHASE_START", "PHASE_DONE", "PHASE_END"}

    commesse_in_produzione = (
        db.query(PieceScanEvent.commessa_id)
        .filter(
            PieceScanEvent.event_type.in_(workshop_event_types),
            PieceScanEvent.commessa_id.isnot(None),
        )
        .distinct()
        .count()
    )

    summary = {
        "commesse_total": len(commesse),
        "commesse_aperte": sum(1 for c in commesse if c.status == CommessaStatus.APERTA),
        "commesse_in_produzione": commesse_in_produzione,
        "scan_officina_oggi": (
            db.query(PieceScanEvent)
            .filter(
                PieceScanEvent.event_type.in_(workshop_event_types),
                PieceScanEvent.timestamp >= today_start,
                PieceScanEvent.timestamp < tomorrow_start,
            )
            .count()
        ),
        "scan_produzione_totali": (
            db.query(PieceScanEvent)
            .filter(PieceScanEvent.event_type.in_(workshop_event_types))
            .count()
        ),
        "materiali_magazzino": db.query(Material).count(),
        "movimenti_magazzino_oggi": (
            db.query(StockMovement)
            .filter(
                StockMovement.movement_type.in_([MovementType.INCOMING, MovementType.OUTGOING]),
                StockMovement.occurred_at >= today_start,
                StockMovement.occurred_at < tomorrow_start,
            )
            .count()
        ),
    }

    return {
        "summary": summary,
        "commesse": {},
    }


@router.get("/resolve/{commessa_ref}")
def resolve_commessa_ref(commessa_ref: str, db: Session = Depends(get_db)):
    commessa = None
    if commessa_ref.isdigit():
        commessa = crud.get_commessa(db=db, commessa_id=int(commessa_ref))
    if commessa is None:
        commessa = crud.get_commessa_by_codice(db=db, codice=commessa_ref)
    if commessa is None:
        raise HTTPException(status_code=404, detail="Commessa non trovata")
    return {"id": commessa.id, "codice": commessa.codice}


@router.post("/validate-files")
async def validate_commessa_files(
    lista_pezzi: UploadFile | None = File(None, description="Lista pezzi / Lavorazioni per posizione"),
    assemblaggi: UploadFile | None = File(None, description="Lista pezzi e assemblati"),
    spedizione: UploadFile | None = File(None, description="Lista spedizione"),
    bulloneria: UploadFile | None = File(None, description="Bulloneria / minuteria senza QR"),
):
    """Valida i file prima dell'upload definitivo, senza creare commessa o revisione."""
    result = {
        "ok": False,
        "can_upload": False,
        "files": {
            "lista_pezzi": {"required": False, "status": "missing", "message": "Non caricata"},
            "assemblaggi": {"required": False, "status": "missing", "message": "Non caricata"},
            "spedizione": {"required": False, "status": "missing", "message": "Non caricata"},
            "bulloneria": {"required": False, "status": "missing", "message": "Non caricata"},
        },
        "errors": [],
        "warnings": [],
        "summary": None,
    }
    with tempfile.TemporaryDirectory(prefix="stqc_validate_") as tmp:
        tmp_dir = Path(tmp)
        lista_dest = None
        asm_dest = None
        if lista_pezzi is not None and lista_pezzi.filename:
            suffix = Path(lista_pezzi.filename).suffix.lower() or ".xls"
            lista_dest = tmp_dir / f"lista_pezzi{suffix}"
            lista_dest.write_bytes(await lista_pezzi.read())
            result["files"]["lista_pezzi"] = {"required": False, "status": "pending", "message": "Validazione in corso"}
            try:
                lista_report = _validate_lista_pezzi_file(lista_dest)
                result["files"]["lista_pezzi"] = {
                    "required": False,
                    "status": "ok",
                    "message": f"OK · {lista_report.get('righe', 0)} posizioni · {lista_report.get('quantita', 0)} pezzi",
                }
            except Exception as exc:
                message = f"Lista pezzi non valida per questo riquadro: {exc}"
                result["files"]["lista_pezzi"] = {"required": False, "status": "error", "message": message}
                result["errors"].append(message)
        if assemblaggi is not None and assemblaggi.filename:
            suffix = Path(assemblaggi.filename).suffix.lower() or ".xls"
            asm_dest = tmp_dir / f"assemblaggi{suffix}"
            asm_dest.write_bytes(await assemblaggi.read())
            result["files"]["assemblaggi"] = {"required": False, "status": "pending", "message": "Validazione in corso"}
            try:
                asm_report = _validate_assemblaggi_file(asm_dest)
                result["files"]["assemblaggi"] = {
                    "required": False,
                    "status": "ok",
                    "message": f"OK · {asm_report.get('assemblati', 0)} assemblati · {asm_report.get('righe', 0)} righe pezzo",
                }
            except Exception as exc:
                message = f"Lista pezzi e assemblati non valida per questo riquadro: {exc}"
                result["files"]["assemblaggi"] = {"required": False, "status": "error", "message": message}
                result["errors"].append(message)

        if lista_dest is not None and result["files"]["lista_pezzi"]["status"] == "ok":
            try:
                items_normalized, report = parse_commessa_files(lista_dest, asm_dest)
                result["files"]["lista_pezzi"] = {
                    "required": False,
                    "status": "ok",
                    "message": f"OK · {report.get('unique_parts', 0)} posizioni · {report.get('total_pieces', len(items_normalized))} pezzi",
                }
                if asm_dest is not None:
                    result["files"]["assemblaggi"] = {
                        "required": False,
                        "status": "ok",
                        "message": f"OK · {report.get('assemblies', 0)} assemblati collegati",
                    }
                result["summary"] = report.get("summary")
            except Exception as exc:
                message = f"File non importabile. Verifica file/parsing: {exc}"
                result["files"]["lista_pezzi"] = {"required": False, "status": "error", "message": "Parsing fallito"}
                if asm_dest is not None:
                    result["files"]["assemblaggi"] = {"required": False, "status": "error", "message": "Parsing fallito"}
                result["errors"].append(message)

        if spedizione is not None and spedizione.filename:
            suffix = Path(spedizione.filename).suffix.lower() or ".xls"
            spedizione_dest = tmp_dir / f"spedizione{suffix}"
            spedizione_dest.write_bytes(await spedizione.read())
            try:
                sped_report = _validate_spedizione_file(spedizione_dest)
                result["files"]["spedizione"] = {
                    "required": False,
                    "status": "ok",
                    "message": f"OK · {sped_report.get('righe', 0)} righe spedizione",
                }
            except Exception as exc:
                message = f"Lista spedizione non valida: {exc}"
                result["files"]["spedizione"] = {"required": False, "status": "error", "message": message}
                result["errors"].append(message)

        if bulloneria is not None and bulloneria.filename:
            suffix = Path(bulloneria.filename).suffix.lower() or ".xlsx"
            bulloneria_dest = tmp_dir / f"bulloneria{suffix}"
            bulloneria_dest.write_bytes(await bulloneria.read())
            try:
                _, bull_report = parse_bulloneria_file(bulloneria_dest)
                result["files"]["bulloneria"] = {
                    "required": False,
                    "status": "ok",
                    "message": f"OK · {bull_report.get('righe', 0)} righe · {bull_report.get('quantita_totale', 0):g} pezzi",
                }
            except Exception as exc:
                message = f"Bulloneria non valida: {exc}"
                result["files"]["bulloneria"] = {"required": False, "status": "error", "message": message}
                result["errors"].append(message)

    has_file = any(info["status"] != "missing" for info in result["files"].values())
    has_ok_file = any(info["status"] == "ok" for info in result["files"].values())
    if not has_file:
        result["warnings"].append("Carica almeno un file per avviare la commessa.")
    result["can_upload"] = not result["errors"] and has_ok_file
    result["ok"] = result["can_upload"] and not result["warnings"]
    return result


@router.post("/spedizione-ad-hoc", status_code=201)
async def create_spedizione_ad_hoc(
    titolo: str = Form(...),
    spedizione: UploadFile = File(..., description="Lista spedizione"),
    note: Optional[str] = Form(None),
    db: Session = Depends(get_db),
):
    """Crea una spedizione libera e i QR pezzo partendo dal solo file spedizione."""
    title = (titolo or "").strip()
    if not title:
        raise HTTPException(422, "Inserisci un titolo commessa/spedizione")
    if not spedizione or not spedizione.filename:
        raise HTTPException(422, "Carica il file spedizione")

    codice = _unique_commessa_code(db, title)
    commessa = Commessa(
        codice=codice,
        descrizione=title,
        status=CommessaStatus.IN_PRODUZIONE,
        notes=note,
    )
    db.add(commessa)
    db.flush()

    existing = db.query(CommessaRevisione).filter(
        CommessaRevisione.commessa_id == commessa.id
    ).count()
    db.query(CommessaRevisione).filter(
        CommessaRevisione.commessa_id == commessa.id,
        CommessaRevisione.corrente.is_(True),
    ).update({CommessaRevisione.corrente: False}, synchronize_session=False)
    codice_rev = f"r{existing + 1:02d}"
    rev_dir = settings.upload_dir / f"commessa_{commessa.id}" / codice_rev
    rev_dir.mkdir(parents=True, exist_ok=True)
    suffix = Path(spedizione.filename or "spedizione.xls").suffix.lower() or ".xls"
    spedizione_dest = rev_dir / f"spedizione{suffix}"

    try:
        with spedizione_dest.open("wb") as f:
            f.write(await spedizione.read())
        spedizione_items, spedizione_report = _parse_spedizione_file(spedizione_dest)
        imported_name = str((spedizione_report.get("project") or {}).get("nome") or "").strip()
        if imported_name:
            commessa.descrizione = imported_name

        report = {
            "ok": True,
            "summary": f"Spedizione ad hoc importata: {len(spedizione_items)} righe",
            "spedizione_ad_hoc": True,
            "spedizione": spedizione_report,
            "file_warnings": [],
        }
        revisione = CommessaRevisione(
            commessa_id=commessa.id,
            codice=codice_rev,
            file_assemblaggi=None,
            file_lavorazioni=None,
            predistinta=False,
            corrente=True,
            stato_analisi="PRONTA",
            report_analisi=report,
            step4_completed_at=datetime.utcnow(),
            step51_completed_at=datetime.utcnow(),
            note=note,
        )
        db.add(revisione)
        db.flush()
        db.add(CommessaDocumento(
            commessa_id=commessa.id,
            revisione_id=revisione.id,
            categoria="SPEDIZIONE",
            filename=Path(spedizione.filename or spedizione_dest.name).name,
            storage_path=str(spedizione_dest.relative_to(settings.upload_dir.parent)),
            mime_type=spedizione.content_type,
        ))
        spedizione_ad_hoc = SpedizioneAdHoc(
            commessa_id=commessa.id,
            revisione_id=revisione.id,
            titolo=title,
            source_file=str(spedizione_dest.relative_to(settings.upload_dir.parent)),
            stato="APERTA",
            note=note,
        )
        db.add(spedizione_ad_hoc)
        db.flush()
        inserted = _populate_spedizione_ad_hoc_items(
            db,
            spedizione_ad_hoc.id,
            commessa.id,
            revisione.id,
            spedizione_items,
        )
        qr_created = _populate_spedizione_ad_hoc_pieces(
            db,
            commessa,
            revisione,
            spedizione_items,
        )
        db.commit()
    except HTTPException:
        db.rollback()
        shutil.rmtree(settings.upload_dir / f"commessa_{commessa.id}", ignore_errors=True)
        raise
    except Exception as exc:
        db.rollback()
        shutil.rmtree(settings.upload_dir / f"commessa_{commessa.id}", ignore_errors=True)
        _logger.exception("Import spedizione ad hoc non riuscito")
        raise HTTPException(422, f"File spedizione non importabile: {exc}")

    return {
        "commessa_id": commessa.id,
        "codice": commessa.codice,
        "titolo": title,
        "righe": inserted,
        "qr_attivi": qr_created,
        "redirect_url": f"/commesse/{quote(commessa.codice, safe='')}/in-cantiere",
    }


def _scan_fields_from_note(note: str | None) -> dict:
    if not note:
        return {}
    try:
        data = json.loads(note)
        return data if isinstance(data, dict) else {}
    except (TypeError, ValueError):
        pass
    for line in reversed(str(note).splitlines()):
        line = line.strip()
        if not line.startswith("SCAN_FIELDS "):
            continue
        try:
            data = json.loads(line.removeprefix("SCAN_FIELDS ").strip())
            return data if isinstance(data, dict) else {}
        except (TypeError, ValueError):
            return {}
    return {}


def _spedizione_ad_hoc_effective_quantity(row: SpedizioneAdHocItem, scan_fields: dict | None = None) -> float:
    return float(row.quantita or 0)


def _spedizione_ad_hoc_effective_weight(row: SpedizioneAdHocItem, scan_fields: dict | None = None) -> float:
    return float(row.peso_totale_kg or 0)


def _spedizione_ad_hoc_summary(rows: list[SpedizioneAdHocItem]) -> dict:
    return {
        "righe": len(rows),
        "quantita": sum(_spedizione_ad_hoc_effective_quantity(row) for row in rows),
        "peso_kg": sum(float(row.peso_totale_kg or 0) for row in rows),
        "peso_spedizione_kg": sum(_spedizione_ad_hoc_effective_weight(row) for row in rows if row.stato == "TROVATO"),
        "trovati": sum(1 for row in rows if row.stato == "TROVATO"),
        "da_trovare": sum(1 for row in rows if row.stato != "TROVATO"),
    }


@router.post("/spedizione-ad-hoc/create-empty", status_code=201)
def create_empty_spedizione_ad_hoc(
    payload: SpedizioneAdHocEmptyCreate,
    db: Session = Depends(get_db),
):
    title = (payload.titolo or "").strip()
    if not title:
        raise HTTPException(422, "Inserisci un titolo spedizione")
    spedizione = SpedizioneAdHoc(
        commessa_id=None,
        revisione_id=None,
        titolo=title,
        source_file=None,
        stato="APERTA",
        note=payload.note,
    )
    db.add(spedizione)
    db.commit()
    db.refresh(spedizione)
    return {
        "id": spedizione.id,
        "titolo": spedizione.titolo,
        "righe": 0,
        "redirect_url": "/spedizione-ad-hoc",
    }


@router.get("/spedizione-ad-hoc/current")
def get_current_empty_spedizione_ad_hoc(db: Session = Depends(get_db)):
    spedizione = (
        db.query(SpedizioneAdHoc)
        .filter(SpedizioneAdHoc.commessa_id.is_(None))
        .filter(SpedizioneAdHoc.stato == "APERTA")
        .order_by(SpedizioneAdHoc.id.desc())
        .first()
    )
    if not spedizione:
        return {"spedizione": None, "summary": _spedizione_ad_hoc_summary([]), "items": []}
    rows = (
        db.query(SpedizioneAdHocItem)
        .filter(SpedizioneAdHocItem.spedizione_id == spedizione.id)
        .order_by(SpedizioneAdHocItem.row_index, SpedizioneAdHocItem.id)
        .all()
    )
    return {
        "spedizione": {
            "id": spedizione.id,
            "titolo": spedizione.titolo,
            "stato": spedizione.stato,
            "note": spedizione.note,
            "source_file": spedizione.source_file,
            "empty_mode": spedizione.source_file is None,
            "created_at": spedizione.created_at,
            "updated_at": spedizione.updated_at,
        },
        "summary": _spedizione_ad_hoc_summary(rows),
        "items": [_spedizione_ad_hoc_item_read(row) for row in rows],
    }


@router.get("/{commessa_id}", response_model=CommessaRead)
def get_commessa(commessa_id: int, db: Session = Depends(get_db)):
    commessa = crud.get_commessa(db=db, commessa_id=commessa_id)
    if commessa is None:
        raise HTTPException(status_code=404, detail="Commessa non trovata")
    return commessa


@router.patch("/{commessa_id}", response_model=CommessaRead)
def update_commessa(commessa_id: int, commessa_in: CommessaUpdate, db: Session = Depends(get_db)):
    commessa = crud.get_commessa(db=db, commessa_id=commessa_id)
    if commessa is None:
        raise HTTPException(status_code=404, detail="Commessa non trovata")
    data = commessa_in.model_dump(exclude_unset=True)
    target_status = data.get("status")
    if target_status == CommessaStatus.IN_PRODUZIONE and commessa.status != CommessaStatus.IN_PRODUZIONE:
        raise HTTPException(
            status_code=409,
            detail="Usa l'endpoint /avvia-produzione per avviare la produzione",
        )
    return crud.update_commessa(db=db, commessa=commessa, obj_in=commessa_in)


@router.delete("/{commessa_id}", status_code=204)
def delete_commessa(commessa_id: int, db: Session = Depends(get_db)):
    commessa = crud.get_commessa(db=db, commessa_id=commessa_id)
    if commessa is None:
        raise HTTPException(status_code=404, detail="Commessa non trovata")
    crud.delete_commessa(db=db, commessa=commessa)


# ── Revisioni distinta ────────────────────────────────────────────────────────

@router.post("/{commessa_id}/analisi", status_code=201)
async def create_analisi_commessa(
    commessa_id: int,
    lista_pezzi: UploadFile | None = File(None, description="Lista pezzi / Lavorazioni per posizione"),
    assemblaggi: UploadFile | None = File(None, description="Lista pezzi e assemblati"),
    spedizione: UploadFile | None = File(None, description="Lista spedizione"),
    bulloneria: UploadFile | None = File(None, description="Bulloneria / minuteria senza QR"),
    predistinta: bool = Form(False),
    note: Optional[str] = Form(None),
    db: Session = Depends(get_db),
):
    """Salva i documenti iniziali e prepara l'analisi della commessa.

    Non genera QR, richieste di materiale o movimenti di magazzino.
    """
    commessa = crud.get_commessa(db=db, commessa_id=commessa_id)
    if commessa is None:
        raise HTTPException(404, "Commessa non trovata")

    # Calcola codice revisione (r01, r02, …)
    existing = db.query(CommessaRevisione).filter(
        CommessaRevisione.commessa_id == commessa_id
    ).count()
    codice_rev = f"r{existing + 1:02d}"
    rev_dir = settings.upload_dir / f"commessa_{commessa_id}" / codice_rev
    rev_dir.mkdir(parents=True, exist_ok=True)

    spedizione_dest = None
    bulloneria_dest = None
    lista_dest = None
    asm_dest = None
    items_normalized: list[dict] = []
    bulloneria_items: list[dict] = []
    spedizione_items: list[dict] = []
    report = {
        "ok": True,
        "summary": "Revisione creata dai file caricati singolarmente",
        "files": {},
        "file_warnings": [],
    }

    try:
        if lista_pezzi is not None and lista_pezzi.filename:
            lista_suffix = Path(lista_pezzi.filename or "lista_pezzi.xls").suffix.lower() or ".xls"
            lista_dest = rev_dir / f"lista_pezzi{lista_suffix}"
            with lista_dest.open("wb") as f:
                f.write(await lista_pezzi.read())

        if assemblaggi is not None and assemblaggi.filename:
            asm_suffix = Path(assemblaggi.filename or "assemblaggi.xls").suffix.lower() or ".xls"
            asm_dest = rev_dir / f"assemblaggi{asm_suffix}"
            with asm_dest.open("wb") as f:
                f.write(await assemblaggi.read())

        if lista_dest is not None:
            items_normalized, report = parse_commessa_files(
                lista_dest,
                asm_dest,
            )
            imported_name = str((report.get("project") or {}).get("nome") or "").strip()
            if imported_name:
                commessa.descrizione = imported_name
        elif asm_dest is not None:
            asm_report = _validate_assemblaggi_file(asm_dest)
            report["assemblaggi"] = asm_report
            report["summary"] = f"Lista assemblati caricata: {asm_report.get('assemblati', 0)} assemblati · {asm_report.get('righe', 0)} righe"

        if lista_dest is None and asm_dest is None and not (spedizione and spedizione.filename) and not (bulloneria and bulloneria.filename):
            raise ValueError("carica almeno un file")
    except Exception as exc:
        shutil.rmtree(rev_dir, ignore_errors=True)
        _logger.exception("Errore nel parsing file revisione %s commessa %d", codice_rev, commessa_id)
        raise HTTPException(
            422,
            f"File non importabile. Verifica file/parsing: {exc}",
        )

    report.setdefault("file_warnings", [])
    if spedizione is not None and spedizione.filename:
        spedizione_suffix = Path(spedizione.filename or "spedizione.xls").suffix.lower() or ".xls"
        spedizione_dest = rev_dir / f"spedizione{spedizione_suffix}"
        with spedizione_dest.open("wb") as f:
            f.write(await spedizione.read())
        try:
            spedizione_items, spedizione_report = _parse_spedizione_file(spedizione_dest)
            report["spedizione"] = spedizione_report
        except Exception as exc:
            _logger.warning("Lista spedizione non validata per revisione %s commessa %d: %s", codice_rev, commessa_id, exc)
            spedizione_items = []
            report["spedizione"] = {"ok": False, "summary": str(exc)}
            report["file_warnings"].append({
                "file": "Lista spedizione",
                "level": "warning",
                "message": f"Lista spedizione non interpretata: {exc}. Analisi commessa proseguita.",
            })
    if bulloneria is not None and bulloneria.filename:
        bulloneria_suffix = Path(bulloneria.filename or "bulloneria.xlsx").suffix.lower() or ".xlsx"
        bulloneria_dest = rev_dir / f"bulloneria{bulloneria_suffix}"
        with bulloneria_dest.open("wb") as f:
            f.write(await bulloneria.read())
        try:
            bulloneria_items, bulloneria_report = parse_bulloneria_file(bulloneria_dest)
            report["bulloneria"] = bulloneria_report
        except Exception as exc:
            _logger.warning("Bulloneria non validata per revisione %s commessa %d: %s", codice_rev, commessa_id, exc)
            bulloneria_items = []
            report["bulloneria"] = {"ok": False, "summary": str(exc)}
            report["file_warnings"].append({
                "file": "Bulloneria",
                "level": "warning",
                "message": f"Bulloneria non interpretata: {exc}. Analisi commessa proseguita senza fabbisogno bulloneria dedicato.",
            })

    revisione = CommessaRevisione(
        commessa_id=commessa_id,
        codice=codice_rev,
        file_assemblaggi=str(asm_dest.relative_to(settings.upload_dir.parent)) if asm_dest is not None else None,
        file_lavorazioni=str(lista_dest.relative_to(settings.upload_dir.parent)) if lista_dest is not None else None,
        predistinta=predistinta,
        corrente=True,
        stato_analisi="PRONTA" if report["ok"] else "DA_VERIFICARE",
        report_analisi=report,
        step4_completed_at=datetime.utcnow(),
        note=note,
    )

    revisioni_precedenti = (
        db.query(CommessaRevisione)
        .filter(
            CommessaRevisione.commessa_id == commessa_id,
            CommessaRevisione.corrente.is_(True),
        )
        .all()
    )
    for precedente in revisioni_precedenti:
        precedente.corrente = False
        (
            db.query(DistintaItem)
            .filter(DistintaItem.revisione_id == precedente.id)
            .update(
                {
                    DistintaItem.invalidato: True,
                    DistintaItem.qr_attivo: False,
                    DistintaItem.stato_tracciamento: "SUPERATO",
                },
                synchronize_session=False,
            )
        )
        (
            db.query(Piece)
            .filter(Piece.revisione_id == precedente.id)
            .update(
                {
                    Piece.qr_attivo: False,
                    Piece.qr_status: "ARCHIVED",
                    Piece.stato_attuale: "SUPERATO",
                    Piece.updated_at: datetime.utcnow(),
                },
                synchronize_session=False,
            )
        )

    db.add(revisione)
    db.flush()

    if spedizione_dest is not None:
        db.add(CommessaDocumento(
            commessa_id=commessa_id,
            revisione_id=revisione.id,
            categoria="SPEDIZIONE",
            filename=Path(spedizione.filename or spedizione_dest.name).name,
            storage_path=str(spedizione_dest.relative_to(settings.upload_dir.parent)),
            mime_type=spedizione.content_type if spedizione else None,
        ))
    if bulloneria_dest is not None:
        db.add(CommessaDocumento(
            commessa_id=commessa_id,
            revisione_id=revisione.id,
            categoria="BULLONERIA",
            filename=Path(bulloneria.filename or bulloneria_dest.name).name,
            storage_path=str(bulloneria_dest.relative_to(settings.upload_dir.parent)),
            mime_type=bulloneria.content_type,
        ))

    distinta_import = DistintaImport(
        filename=(lista_pezzi.filename if lista_pezzi and lista_pezzi.filename else f"{commessa.codice}_{codice_rev}"),
        source_software="Tekla",
        total_items=len(items_normalized),
        status=revisione.stato_analisi,
        notes=report["summary"],
    )
    db.add(distinta_import)
    db.flush()

    db_items = normalized_to_db_bulk(items_normalized)
    inserted_items: list[DistintaItem] = []
    for item_data in db_items:
        di = DistintaItem(
            import_id=distinta_import.id,
            revisione_id=revisione.id,
            commessa_id=commessa_id,
            **{k: v for k, v in item_data.items()
               if k in {c.name for c in DistintaItem.__table__.columns} - {"id", "uuid", "qr_code"}},
        )
        db.add(di)
        inserted_items.append(di)

    db.flush()
    for di in inserted_items:
        _create_piece_from_item(db, di, commessa_id, revisione.id)
    db.flush()
    qr_created = _generate_revision_piece_labels(db, commessa, revisione)

    _populate_post_officina_items(db, commessa_id, revisione.id, spedizione_items)
    shipping_qr_created = _populate_spedizione_commessa_pieces(
        db,
        commessa,
        revisione,
        spedizione_items,
    )

    for row in bulloneria_items:
        db.add(CommessaBulloneria(
            commessa_id=commessa_id,
            revisione_id=revisione.id,
            assemblato=row.get("assemblato"),
            codice=row.get("codice"),
            descrizione=row.get("descrizione"),
            categoria=row.get("categoria"),
            tipo=row.get("tipo"),
            norma=row.get("norma"),
            diametro=row.get("diametro"),
            lunghezza=row.get("lunghezza"),
            classe=row.get("classe"),
            trattamento=row.get("trattamento"),
            quantita=row.get("quantita") or 0,
            unita=row.get("unita") or "pz",
            peso_kg=row.get("peso_kg"),
            note=row.get("note"),
            source_file=row.get("source_file"),
        ))

    db.commit()
    return {
        "commessa_id":   commessa_id,
        "revisione_id":  revisione.id,
        "codice":        codice_rev,
        "import_id":     distinta_import.id,
        "stato_analisi": revisione.stato_analisi,
        "predistinta":   revisione.predistinta,
        "corrente":      revisione.corrente,
        "step4_completed_at": revisione.step4_completed_at,
        "step51_completed_at": revisione.step51_completed_at,
        "qr_attivi": qr_created,
        "qr_spedizione": shipping_qr_created,
        "validation":    report,
    }


@router.get("/{commessa_id}/revisioni")
def list_revisioni(commessa_id: int, db: Session = Depends(get_db)):
    commessa = crud.get_commessa(db=db, commessa_id=commessa_id)
    if commessa is None:
        raise HTTPException(404, "Commessa non trovata")
    revs = db.query(CommessaRevisione).filter(
        CommessaRevisione.commessa_id == commessa_id
    ).order_by(CommessaRevisione.id).all()
    return [
        {
            "id":              r.id,
            "codice":          r.codice,
            "file_assemblaggi": r.file_assemblaggi,
            "file_lista_pezzi": r.file_lavorazioni,
            "file_spedizione":  _spedizione_doc(r).storage_path if _spedizione_doc(r) else None,
            "file_bulloneria":  _doc_by_category(r, "BULLONERIA").storage_path if _doc_by_category(r, "BULLONERIA") else None,
            "predistinta":      r.predistinta,
            "corrente":         r.corrente,
            "stato_analisi":    r.stato_analisi,
            "report_analisi":   r.report_analisi,
            "step4_completed_at": r.step4_completed_at,
            "step51_completed_at": r.step51_completed_at,
            "note":            r.note,
            "imported_at":     r.imported_at,
            "n_items":         db.query(DistintaItem).filter(DistintaItem.revisione_id == r.id).count(),
            "documenti": [
                {
                    "id": d.id,
                    "categoria": d.categoria,
                    "filename": d.filename,
                    "mime_type": d.mime_type,
                }
                for d in r.documenti
            ],
        }
        for r in revs
    ]


def _latest_revision(db: Session, commessa_id: int) -> CommessaRevisione | None:
    corrente = (
        db.query(CommessaRevisione)
        .filter(
            CommessaRevisione.commessa_id == commessa_id,
            CommessaRevisione.corrente.is_(True),
        )
        .order_by(CommessaRevisione.id.desc())
        .first()
    )
    if corrente is not None:
        return corrente
    return (
        db.query(CommessaRevisione)
        .filter(CommessaRevisione.commessa_id == commessa_id)
        .order_by(CommessaRevisione.id.desc())
        .first()
    )


def _spedizione_doc(revisione: CommessaRevisione) -> CommessaDocumento | None:
    return next((doc for doc in revisione.documenti if doc.categoria == "SPEDIZIONE"), None)


def _doc_by_category(revisione: CommessaRevisione, categoria: str) -> CommessaDocumento | None:
    return next((doc for doc in revisione.documenti if doc.categoria == categoria), None)


def _num(value) -> float:
    return float(value) if value is not None else 0.0


def _fmt_dim(value) -> str | None:
    if value is None:
        return None
    number = float(value)
    return f"{number:g}"


def _item_dimension_label(item: DistintaItem) -> str | None:
    length = _fmt_dim(item.length_mm)
    width = _fmt_dim(item.width_mm)
    if length and width:
        return f"{width}×{length} mm"
    if length:
        return f"L {length} mm"
    if width:
        return f"{width} mm"
    return None


def _bolt_dimension_label(row: CommessaBulloneria) -> str | None:
    values = [row.diametro, row.lunghezza]
    values = [str(value).strip() for value in values if value]
    if values:
        return "×".join(values)
    return None


def _fabbisogno_category_from_piece(item: DistintaItem) -> str:
    text = " ".join(str(value or "") for value in (
        item.tipo_profilo,
        item.description,
        item.material_description,
        item.part_number,
    )).upper()
    if any(token in text for token in ("DADO", "RONDELL", "VITE", "BULL", "BOLT", "TIRAFON", "BARRA FILETTATA", "PIOLO")):
        return "Bulloneria"
    if any(token in text for token in ("LAMIERA", "PIATTO", "PIATTI", "PL")):
        return "Lamiere / piatti"
    if any(token in text for token in ("TRAVE", "IPE", "HEA", "HEB", "UPN")):
        return "Travi"
    if any(token in text for token in ("TUBO", "RHS", "SHS", "TUBE")):
        return "Tubolari"
    profile = str(item.description or "").upper().strip()
    if "ANGOL" in text or profile.startswith("L"):
        return "Angolari"
    if "TONDO" in text:
        return "Tondi"
    if "QUADRO" in text:
        return "Quadri"
    return item.tipo_profilo or "Altro"


def _fabbisogno_group(rows: list[dict]) -> dict:
    groups: dict[tuple, dict] = {}
    summary: dict[str, dict] = {}
    for row in rows:
        key = (
            row["categoria"],
            row.get("codice") or "",
            row.get("descrizione") or "",
            row.get("materiale_norma") or "",
            row.get("dimensioni") or "",
            row.get("origine") or "",
        )
        target = groups.setdefault(key, {
            **row,
            "righe": 0,
            "quantita": 0.0,
            "peso_kg": 0.0,
            "assemblati": set(),
        })
        target["righe"] += int(row.get("righe") or 1)
        target["quantita"] += _num(row.get("quantita"))
        target["peso_kg"] += _num(row.get("peso_kg"))
        if row.get("assemblato"):
            target["assemblati"].add(row["assemblato"])

        cat = summary.setdefault(row["categoria"], {
            "categoria": row["categoria"],
            "righe": 0,
            "quantita": 0.0,
            "peso_kg": 0.0,
            "origini": set(),
        })
        cat["righe"] += int(row.get("righe") or 1)
        cat["quantita"] += _num(row.get("quantita"))
        cat["peso_kg"] += _num(row.get("peso_kg"))
        cat["origini"].add(row.get("origine_label") or row.get("origine") or "—")

    detail = []
    for row in groups.values():
        row["assemblati"] = sorted(row["assemblati"])
        detail.append(row)
    detail.sort(key=lambda row: (row["categoria"], row.get("descrizione") or "", row.get("dimensioni") or "", row.get("origine") or ""))

    summary_rows = []
    for row in summary.values():
        row["origini"] = sorted(row["origini"])
        summary_rows.append(row)
    summary_rows.sort(key=lambda row: row["categoria"])
    return {"summary": summary_rows, "detail": detail}


def _norm_header(value) -> str:
    text = str(value or "").strip().lower()
    for src, dst in (("à", "a"), ("è", "e"), ("é", "e"), ("ì", "i"), ("ò", "o"), ("ù", "u")):
        text = text.replace(src, dst)
    text = "".join(ch for ch in unicodedata.normalize("NFKD", text) if not unicodedata.combining(ch))
    return "".join(ch for ch in text if ch.isalnum())


def _num_or_none(value):
    if value is None:
        return None
    if isinstance(value, (int, float)):
        return value
    text = str(value).strip()
    if not text or text in {"-", "—"}:
        return None
    text = text.replace(" ", "")
    if "," in text:
        text = text.replace(".", "").replace(",", ".")
    elif text.count(".") > 1:
        text = text.replace(".", "")
    try:
        return float(text)
    except ValueError:
        return None


def _find_first_col(headers: list, candidates: set[str]) -> int | None:
    normalized = [_norm_header(value) for value in headers]
    for idx, value in enumerate(normalized):
        if value in candidates:
            return idx
    for idx, value in enumerate(normalized):
        if any(candidate in value for candidate in candidates):
            return idx
    return None


def _cell(row: list, idx: int | None):
    if idx is None or idx >= len(row):
        return None
    value = row[idx]
    if value is None:
        return None
    text = str(value).strip()
    return text if text else None


def _parse_spedizione_file(path: Path) -> tuple[list[dict], dict]:
    rows = _extract_rows(path)
    if not rows:
        raise ValueError("nessuna riga leggibile trovata")

    trattamento = None
    for raw in rows[:30]:
        cells = [str(cell).strip() for cell in raw if str(cell).strip()]
        for idx, cell in enumerate(cells):
            if _norm_header(cell) == "trattamento":
                trattamento = cells[idx + 1] if idx + 1 < len(cells) else None
                break
        if trattamento:
            break

    header_idx = None
    for idx, row in enumerate(rows[:40]):
        normalized = {_norm_header(cell) for cell in row}
        if normalized.intersection({"assemb", "assemblato", "codice", "parte", "marcapos"}) and normalized.intersection({"qta", "quantita", "qty"}):
            header_idx = idx
            break
    if header_idx is None:
        raise ValueError("intestazione spedizione non riconosciuta")

    header = rows[header_idx]
    idx_code = _find_first_col(header, {"assemb", "assemblato", "codice", "parte", "marcapos"})
    idx_desc = _find_first_col(header, {"descrizione", "descr"})
    idx_profile = _find_first_col(header, {"profilo", "profile"})
    idx_qty = _find_first_col(header, {"qta", "quantita", "qty"})
    idx_length = _find_first_col(header, {"lunghmm", "lunghezzamm", "lungh", "lunghezza"})
    idx_width = _find_first_col(header, {"larghmm", "larghezzamm", "largh", "larghezza"})
    idx_height = _find_first_col(header, {"altmm", "altezzamm", "alt", "altezza"})
    idx_unit_weight = _find_first_col(header, {"pesokgun", "pesounitario", "pesounitariokg"})
    idx_total_weight = _find_first_col(header, {"pesokgtot", "pesototale", "pesototalekg"})
    idx_area = _find_first_col(header, {"areaverniciabilemq", "area"})

    if idx_code is None or idx_qty is None:
        raise ValueError("colonne codice/quantità spedizione non riconosciute")

    parsed: list[dict] = []
    for row_number, row in enumerate(rows[header_idx + 1:], start=1):
        code = _cell(row, idx_code)
        if not code or code.lower().startswith("totale"):
            continue
        parsed.append({
            "row_index": row_number,
            "codice": code,
            "descrizione": _cell(row, idx_desc),
            "profilo": _cell(row, idx_profile),
            "quantita": _num_or_none(_cell(row, idx_qty)) or 0,
            "lunghezza_mm": _num_or_none(_cell(row, idx_length)),
            "larghezza_mm": _num_or_none(_cell(row, idx_width)),
            "altezza_mm": _num_or_none(_cell(row, idx_height)),
            "peso_unitario_kg": _num_or_none(_cell(row, idx_unit_weight)),
            "peso_totale_kg": _num_or_none(_cell(row, idx_total_weight)),
            "area_verniciabile_mq": _num_or_none(_cell(row, idx_area)),
            "trattamento": trattamento,
            "source_file": path.name,
        })

    if not parsed:
        raise ValueError("nessuna riga spedizione valida trovata")
    report = {
        "ok": True,
        "summary": f"Lista spedizione leggibile: {len(parsed)} righe rilevate",
        "righe": len(parsed),
        "quantita": sum(float(row["quantita"] or 0) for row in parsed),
        "project": _extract_project_metadata(path),
    }
    return parsed, report


def _validate_spedizione_file(path: Path) -> dict:
    _, report = _parse_spedizione_file(path)
    return report


def _extract_ddt_table_rows(path: Path) -> list[list]:
    if path.suffix.lower() != ".csv":
        return _extract_rows(path)
    raw = path.read_bytes()
    for encoding in ("utf-8-sig", "cp1252", "iso-8859-1"):
        try:
            text = raw.decode(encoding)
            break
        except UnicodeDecodeError:
            continue
    else:
        text = raw.decode("utf-8", errors="replace")
    sample = text[:2048]
    try:
        dialect = csv.Sniffer().sniff(sample, delimiters=";,|\t,")
        return [row for row in csv.reader(text.splitlines(), dialect)]
    except csv.Error:
        return [row for row in csv.reader(text.splitlines(), delimiter=";")]


def _manual_ddt_rows_from_table(path: Path) -> list[dict]:
    rows = _extract_ddt_table_rows(path)
    if not rows:
        raise ValueError("nessuna riga leggibile trovata")
    header_idx = None
    for idx, row in enumerate(rows[:30]):
        normalized = {_norm_header(cell) for cell in row}
        if normalized.intersection({"codice", "descrizione", "descr", "profilo", "qta", "quantita", "peso"}):
            header_idx = idx
            break
    if header_idx is None:
        header_idx = 0
        header = ["descrizione", "quantita", "peso_totale_kg", "trattamento"]
        data_rows = rows
    else:
        header = rows[header_idx]
        data_rows = rows[header_idx + 1:]

    idx_code = _find_first_col(header, {"codice", "code", "articolo", "id"})
    idx_desc = _find_first_col(header, {"descrizione", "descr", "description", "materiale"})
    idx_profile = _find_first_col(header, {"profilo", "profile"})
    idx_qty = _find_first_col(header, {"qta", "quantita", "qty"})
    idx_weight = _find_first_col(header, {"peso", "pesokg", "pesototale", "pesototalekg", "pesokgtot"})
    idx_treatment = _find_first_col(header, {"trattamento", "finitura"})
    if idx_desc is None:
        idx_desc = idx_code if idx_code is not None else 0

    parsed: list[dict] = []
    for row_number, row in enumerate(data_rows, start=1):
        code = _cell(row, idx_code)
        desc = _cell(row, idx_desc)
        if not code and not desc:
            continue
        parsed.append({
            "row_index": row_number,
            "codice": code,
            "descrizione": desc or code,
            "profilo": _cell(row, idx_profile),
            "quantita": _num_or_none(_cell(row, idx_qty)) or 1,
            "peso_totale_kg": _num_or_none(_cell(row, idx_weight)),
            "trattamento": _cell(row, idx_treatment),
            "source_file": path.name,
        })
    if not parsed:
        raise ValueError("nessuna riga DDT manuale valida trovata")
    return parsed


def _manual_ddt_rows_from_text(text: str) -> list[dict]:
    parsed: list[dict] = []
    for row_number, raw_line in enumerate(str(text or "").splitlines(), start=1):
        line = raw_line.strip()
        if not line:
            continue
        parts = [part.strip() for part in re.split(r"[;\t|]", line)]
        if len(parts) >= 2:
            code = parts[0] or None
            desc = parts[1] or code
            qty = _num_or_none(parts[2]) if len(parts) >= 3 else None
            weight = _num_or_none(parts[3]) if len(parts) >= 4 else None
            treatment = parts[4] if len(parts) >= 5 and parts[4] else None
        else:
            code = None
            desc = line
            qty = None
            weight = None
            treatment = None
        if not desc:
            continue
        parsed.append({
            "row_index": row_number,
            "codice": code,
            "descrizione": desc,
            "profilo": None,
            "quantita": qty or 1,
            "peso_totale_kg": weight,
            "trattamento": treatment,
            "source_file": "manuale",
        })
    if not parsed:
        raise ValueError("inserisci almeno una riga manuale")
    return parsed


def _populate_post_officina_items(
    db: Session,
    commessa_id: int,
    revisione_id: int,
    spedizione_items: list[dict],
    *,
    classify: bool = True,
    default_tipo_unita: str = "NON_CLASSIFICATO",
) -> int:
    if not spedizione_items:
        return 0

    db.query(CommessaPostOfficinaItem).filter(
        CommessaPostOfficinaItem.revisione_id == revisione_id
    ).delete(synchronize_session=False)

    assembly_codes: set[str] = set()
    loose_piece_codes: set[str] = set()
    if classify:
        distinta_items = (
            db.query(DistintaItem)
            .filter(DistintaItem.revisione_id == revisione_id)
            .all()
        )
        assembly_codes = {
            str(item.parent_assembly).strip()
            for item in distinta_items
            if item.parent_assembly and str(item.parent_assembly).strip()
        }
        loose_piece_codes = {
            str(item.part_number).strip()
            for item in distinta_items
            if item.part_number and str(item.part_number).strip()
        }

    inserted = 0
    for idx, row in enumerate(spedizione_items, start=1):
        code = str(row.get("codice") or "").strip()
        if not code:
            continue
        tipo_unita = default_tipo_unita
        if classify:
            if code in assembly_codes:
                tipo_unita = "ASSEMBLATO"
            elif code in loose_piece_codes:
                tipo_unita = "PEZZO_SCIOLTO"
            else:
                tipo_unita = "NON_CLASSIFICATO"
        db.add(CommessaPostOfficinaItem(
            commessa_id=commessa_id,
            revisione_id=revisione_id,
            row_index=int(row.get("row_index") or idx),
            codice=code,
            descrizione=row.get("descrizione"),
            profilo=row.get("profilo"),
            quantita=row.get("quantita") or 0,
            lunghezza_mm=row.get("lunghezza_mm"),
            larghezza_mm=row.get("larghezza_mm"),
            altezza_mm=row.get("altezza_mm"),
            peso_unitario_kg=row.get("peso_unitario_kg"),
            peso_totale_kg=row.get("peso_totale_kg"),
            area_verniciabile_mq=row.get("area_verniciabile_mq"),
            trattamento=row.get("trattamento"),
            tipo_unita=tipo_unita,
            source_file=row.get("source_file"),
        ))
        inserted += 1
    return inserted


def _populate_spedizione_ad_hoc_items(
    db: Session,
    spedizione_id: int,
    commessa_id: int | None,
    revisione_id: int | None,
    spedizione_items: list[dict],
) -> int:
    if not spedizione_items:
        return 0

    db.query(SpedizioneAdHocItem).filter(
        SpedizioneAdHocItem.spedizione_id == spedizione_id
    ).delete(synchronize_session=False)

    inserted = 0
    for idx, row in enumerate(spedizione_items, start=1):
        code = str(row.get("codice") or "").strip()
        if not code:
            continue
        db.add(SpedizioneAdHocItem(
            spedizione_id=spedizione_id,
            commessa_id=commessa_id,
            revisione_id=revisione_id,
            row_index=int(row.get("row_index") or idx),
            codice=code,
            descrizione=row.get("descrizione"),
            profilo=row.get("profilo"),
            quantita=row.get("quantita") or 0,
            lunghezza_mm=row.get("lunghezza_mm"),
            larghezza_mm=row.get("larghezza_mm"),
            altezza_mm=row.get("altezza_mm"),
            peso_unitario_kg=row.get("peso_unitario_kg"),
            peso_totale_kg=row.get("peso_totale_kg"),
            area_verniciabile_mq=row.get("area_verniciabile_mq"),
            trattamento=row.get("trattamento"),
            tipo_unita="SPEDIZIONE_AD_HOC",
            stato="DA_TROVARE",
            source_file=row.get("source_file"),
        ))
        inserted += 1
    return inserted


def _populate_spedizione_commessa_pieces(
    db: Session,
    commessa: Commessa,
    revisione: CommessaRevisione,
    spedizione_items: list[dict],
) -> int:
    """Espande le righe spedizione in QR pezzo, senza usare il magazzino."""
    totals: dict[str, int] = defaultdict(int)
    for row in spedizione_items:
        code = str(row.get("codice") or "").strip()
        if code:
            totals[code] += max(0, int(round(float(row.get("quantita") or 0))))

    counters: dict[str, int] = defaultdict(int)
    created = 0
    for row in spedizione_items:
        code = str(row.get("codice") or "").strip()
        quantity = max(0, int(round(float(row.get("quantita") or 0))))
        if not code or quantity <= 0:
            continue
        unit_weight = row.get("peso_unitario_kg")
        if unit_weight is None and row.get("peso_totale_kg") is not None:
            unit_weight = float(row["peso_totale_kg"]) / quantity
        for _ in range(quantity):
            counters[code] += 1
            progressivo = counters[code]
            payload = format_piece_label_payload(
                commessa_display_name(commessa),
                code,
                progressivo,
                totals[code],
                float(unit_weight) if unit_weight is not None else None,
            )
            db.add(Piece(
                qr_code=_piece_qr_code(code, progressivo),
                qr_payload=payload,
                qr_status="ACTIVE",
                qr_attivo=True,
                commessa_id=commessa.id,
                revisione_id=revisione.id,
                distinta_item_id=None,
                assemblato_id=code,
                marca_pos=code,
                progressivo=progressivo,
                profilo=row.get("profilo") or row.get("descrizione"),
                peso_kg=unit_weight,
                stato_attuale="DA_PRODURRE",
            ))
            created += 1
    return created


def _populate_spedizione_ad_hoc_pieces(
    db: Session,
    commessa: Commessa,
    revisione: CommessaRevisione,
    spedizione_items: list[dict],
) -> int:
    return _populate_spedizione_commessa_pieces(db, commessa, revisione, spedizione_items)


def _shipping_piece_query(db: Session, revisione_id: int):
    return db.query(Piece).filter(
        Piece.revisione_id == revisione_id,
        Piece.distinta_item_id.is_(None),
        Piece.qr_attivo.is_(True),
    )


def _ensure_spedizione_qr_pieces(db: Session, commessa: Commessa, revisione: CommessaRevisione) -> int:
    existing = _shipping_piece_query(db, revisione.id).count()
    if existing:
        return existing

    rows = (
        db.query(CommessaPostOfficinaItem)
        .filter(CommessaPostOfficinaItem.revisione_id == revisione.id)
        .order_by(CommessaPostOfficinaItem.row_index, CommessaPostOfficinaItem.id)
        .all()
    )
    if not rows:
        spedizione_doc = _spedizione_doc(revisione)
        if spedizione_doc and spedizione_doc.storage_path:
            spedizione_path = settings.upload_dir.parent / spedizione_doc.storage_path
            if spedizione_path.exists():
                try:
                    spedizione_items, _ = _parse_spedizione_file(spedizione_path)
                    _populate_post_officina_items(
                        db,
                        commessa.id,
                        revisione.id,
                        spedizione_items,
                        classify=False,
                        default_tipo_unita="SPEDIZIONE",
                    )
                    db.flush()
                    rows = (
                        db.query(CommessaPostOfficinaItem)
                        .filter(CommessaPostOfficinaItem.revisione_id == revisione.id)
                        .order_by(CommessaPostOfficinaItem.row_index, CommessaPostOfficinaItem.id)
                        .all()
                    )
                except Exception as exc:
                    _logger.warning(
                        "Backfill QR spedizione non riuscito per revisione %s commessa %d: %s",
                        revisione.codice,
                        commessa.id,
                        exc,
                    )
    if not rows:
        return 0

    spedizione_items = [
        {
            "row_index": row.row_index,
            "codice": row.codice,
            "descrizione": row.descrizione,
            "profilo": row.profilo,
            "quantita": row.quantita,
            "peso_unitario_kg": row.peso_unitario_kg,
            "peso_totale_kg": row.peso_totale_kg,
            "trattamento": row.trattamento,
            "source_file": row.source_file,
        }
        for row in rows
    ]
    created = _populate_spedizione_commessa_pieces(db, commessa, revisione, spedizione_items)
    if created:
        db.commit()
    return created


def _validate_lista_pezzi_file(path: Path) -> dict:
    rows = _extract_rows(path)
    if not rows:
        raise ValueError("file vuoto o non leggibile")
    header_idx = _find_header_row(rows, ALIASES["part_code"] + ALIASES["profile"] + ALIASES["qty"])
    col_map = _build_col_map(rows[header_idx])
    required = {"part_code", "profile", "qty"}
    missing = sorted(required - set(col_map))
    if missing:
        raise ValueError("colonne lista pezzi non riconosciute")
    valid_rows = 0
    total_qty = 0
    for row in rows[header_idx + 1:]:
        if not row or col_map["part_code"] >= len(row):
            continue
        code = str(row[col_map["part_code"]] or "").strip()
        if not code or code.lower().startswith("totale"):
            continue
        valid_rows += 1
        try:
            total_qty += int(round(float(str(row[col_map["qty"]]).replace(",", ".") or "0")))
        except (ValueError, TypeError):
            pass
    if valid_rows == 0:
        raise ValueError("nessuna riga lista pezzi valida trovata")
    return {"ok": True, "righe": valid_rows, "quantita": total_qty}


def _validate_assemblaggi_file(path: Path) -> dict:
    rows = _extract_rows(path)
    if not rows:
        raise ValueError("file vuoto o non leggibile")
    header_idx = _find_header_row(rows, ALIASES["assembly"] + ALIASES["part_code"] + ALIASES["qty"])
    col_map = _build_col_map(rows[header_idx])
    required = {"assembly", "part_code", "qty"}
    missing = sorted(required - set(col_map))
    if missing:
        raise ValueError("colonne assemblaggi non riconosciute")
    assemblies = set()
    parts = 0
    current_assembly = None
    for row in rows[header_idx + 1:]:
        asm = str(row[col_map["assembly"]] if col_map["assembly"] < len(row) else "").strip()
        part = str(row[col_map["part_code"]] if col_map["part_code"] < len(row) else "").strip()
        if asm.lower().startswith("totale") or part.lower().startswith("totale"):
            continue
        if asm and not part:
            current_assembly = asm
            assemblies.add(asm)
        elif part:
            parts += 1
            if current_assembly:
                assemblies.add(current_assembly)
            elif asm:
                assemblies.add(asm)
    if not assemblies or parts == 0:
        raise ValueError("nessun collegamento assemblato/pezzo valido trovato")
    return {"ok": True, "assemblati": len(assemblies), "righe": parts}


def _build_fabbisogno_commessa(items: list[DistintaItem], bulloneria_rows: list[CommessaBulloneria]) -> dict:
    rows: list[dict] = []
    for item in items:
        rows.append({
            "categoria": _fabbisogno_category_from_piece(item),
            "codice": item.part_number,
            "descrizione": item.description or item.part_number,
            "materiale_norma": item.material_code,
            "dimensioni": _item_dimension_label(item),
            "quantita": 1,
            "unita": "pz",
            "peso_kg": _num(item.weight_kg),
            "origine": "FILE_PEZZI",
            "origine_label": "File pezzi",
            "qr_scope": "PEZZO",
            "assemblato": item.parent_assembly,
            "righe": 1,
        })
    for row in bulloneria_rows:
        rows.append({
            "categoria": "Bulloneria",
            "codice": row.codice,
            "descrizione": row.descrizione or row.codice or row.tipo or row.categoria,
            "materiale_norma": " · ".join(str(value) for value in (row.norma, row.classe) if value),
            "dimensioni": _bolt_dimension_label(row),
            "quantita": _num(row.quantita),
            "unita": row.unita or "pz",
            "peso_kg": _num(row.peso_kg),
            "origine": "FILE_BULLONERIA",
            "origine_label": "File bulloneria",
            "qr_scope": "NESSUN_QR",
            "assemblato": row.assemblato,
            "righe": 1,
            "tipo": row.tipo,
            "sottocategoria": row.categoria,
        })
    grouped = _fabbisogno_group(rows)
    total_qty = sum(_num(row["quantita"]) for row in grouped["detail"])
    total_weight = sum(_num(row["peso_kg"]) for row in grouped["detail"])
    return {
        "summary": grouped["summary"],
        "detail": grouped["detail"],
        "totals": {
            "righe": len(grouped["detail"]),
            "quantita": total_qty,
            "peso_kg": total_weight,
        },
        "note": "Vista materiali/fabbisogno derivata dai file caricati. Non modifica la logica QR.",
    }


@router.get("/{commessa_id}/analisi")
def get_analisi_commessa(commessa_id: int, db: Session = Depends(get_db)):
    commessa = crud.get_commessa(db=db, commessa_id=commessa_id)
    if commessa is None:
        raise HTTPException(404, "Commessa non trovata")
    revisione = _latest_revision(db, commessa_id)
    if revisione is None:
        raise HTTPException(404, "Nessuna analisi caricata per la commessa")

    items = (
        db.query(DistintaItem)
        .filter(
            DistintaItem.revisione_id == revisione.id,
            DistintaItem.invalidato.is_(False),
        )
        .order_by(DistintaItem.part_number, DistintaItem.instance_number)
        .all()
    )
    pieces = (
        db.query(Piece)
        .filter(Piece.revisione_id == revisione.id)
        .order_by(Piece.marca_pos, Piece.progressivo, Piece.id)
        .all()
    )
    positions: dict[str, dict] = {}
    for item in items:
        code = item.part_number or "SENZA CODICE"
        row = positions.setdefault(code, {
            "part_number": code,
            "profilo": item.description,
            "qualita": item.material_code,
            "tipo": item.tipo_profilo,
            "quantita": 0,
            "length_mm": item.length_mm,
            "width_mm": item.width_mm,
            "weight_kg": item.weight_kg,
            "assemblati": set(),
        })
        row["quantita"] += 1
        if item.parent_assembly:
            row["assemblati"].add(item.parent_assembly)

    position_rows = []
    for row in positions.values():
        row["assemblati"] = sorted(row["assemblati"])
        position_rows.append(row)

    spedizione_doc = _spedizione_doc(revisione)
    bulloneria_doc = _doc_by_category(revisione, "BULLONERIA")
    bulloneria_rows = (
        db.query(CommessaBulloneria)
        .filter(CommessaBulloneria.revisione_id == revisione.id)
        .order_by(CommessaBulloneria.assemblato, CommessaBulloneria.tipo, CommessaBulloneria.codice, CommessaBulloneria.id)
        .all()
    )
    bulloneria_totale = sum(float(row.quantita or 0) for row in bulloneria_rows)
    bulloneria_tipologie: dict[str, float] = defaultdict(float)
    for row in bulloneria_rows:
        bulloneria_tipologie[row.tipo or "Altro"] += float(row.quantita or 0)

    return {
        "commessa": {
            "id": commessa.id,
            "codice": commessa.codice,
            "cliente": commessa.cliente,
            "data_consegna_prevista": commessa.data_consegna_prevista,
            "status": commessa.status,
        },
        "revisione": {
            "id": revisione.id,
            "codice": revisione.codice,
            "predistinta": revisione.predistinta,
            "corrente": revisione.corrente,
            "stato_analisi": revisione.stato_analisi,
            "report": revisione.report_analisi,
            "imported_at": revisione.imported_at,
            "step4_completed_at": revisione.step4_completed_at,
            "step51_completed_at": revisione.step51_completed_at,
            "step51_completato": revisione.step51_completed_at is not None,
            "files": {
                "lista_pezzi": revisione.file_lavorazioni,
                "assemblaggi": revisione.file_assemblaggi,
                "spedizione": spedizione_doc.storage_path if spedizione_doc else None,
                "bulloneria": bulloneria_doc.storage_path if bulloneria_doc else None,
                "documenti": [
                    {
                        "id": doc.id,
                        "filename": doc.filename,
                        "categoria": doc.categoria,
                        "mime_type": doc.mime_type,
                    }
                    for doc in revisione.documenti
                ],
            },
        },
        "summary": {
            "n_pezzi": len(pieces) if pieces else len(items),
            "n_qr_attivi": sum(1 for piece in pieces if piece.qr_attivo),
            "n_codici_pezzo": len(position_rows),
            "n_assemblati": len({
                piece.assemblato_id for piece in pieces if piece.assemblato_id
            }),
            "n_profili": len({
                (item.description, item.material_code)
                for item in items if item.description
            }),
            "n_bulloneria_righe": len(bulloneria_rows),
            "n_bulloneria_totale": bulloneria_totale,
            "n_bulloneria_tipologie": len(bulloneria_tipologie),
        },
        "bulloneria": [
            {
                "id": row.id,
                "assemblato": row.assemblato,
                "codice": row.codice,
                "descrizione": row.descrizione,
                "categoria": row.categoria,
                "tipo": row.tipo,
                "norma": row.norma,
                "diametro": row.diametro,
                "lunghezza": row.lunghezza,
                "classe": row.classe,
                "trattamento": row.trattamento,
                "quantita": float(row.quantita or 0),
                "unita": row.unita,
                "peso_kg": float(row.peso_kg or 0),
                "note": row.note,
            }
            for row in bulloneria_rows
        ],
        "bulloneria_summary": {
            "righe": len(bulloneria_rows),
            "quantita_totale": bulloneria_totale,
            "tipologie": dict(sorted(bulloneria_tipologie.items())),
        },
        "fabbisogno": _build_fabbisogno_commessa(items, bulloneria_rows),
        "positions": position_rows,
    }


def _post_officina_item_read(row: CommessaPostOfficinaItem) -> dict:
    return {
        "id": row.id,
        "commessa_id": row.commessa_id,
        "revisione_id": row.revisione_id,
        "row_index": row.row_index,
        "codice": row.codice,
        "descrizione": row.descrizione,
        "profilo": row.profilo,
        "quantita": float(row.quantita or 0),
        "lunghezza_mm": float(row.lunghezza_mm) if row.lunghezza_mm is not None else None,
        "larghezza_mm": float(row.larghezza_mm) if row.larghezza_mm is not None else None,
        "altezza_mm": float(row.altezza_mm) if row.altezza_mm is not None else None,
        "peso_unitario_kg": float(row.peso_unitario_kg) if row.peso_unitario_kg is not None else None,
        "peso_totale_kg": float(row.peso_totale_kg) if row.peso_totale_kg is not None else None,
        "area_verniciabile_mq": float(row.area_verniciabile_mq) if row.area_verniciabile_mq is not None else None,
        "trattamento": row.trattamento,
        "tipo_unita": row.tipo_unita,
        "lavorazioni_status": row.lavorazioni_status,
        "cantiere_status": row.cantiere_status,
        "trovato_at": row.updated_at if row.cantiere_status == "TROVATO" else None,
        "source_file": row.source_file,
        "qr_image_url": f"/post-officina-qr-image/{row.commessa_id}/{quote(row.codice, safe='')}.png",
        "qr_payload": f"STQC:POST:{row.commessa_id}:{row.revisione_id}:{row.codice}",
    }


def _spedizione_ad_hoc_item_read(row: SpedizioneAdHocItem) -> dict:
    scan_fields = _scan_fields_from_note(row.note)
    effective_quantity = _spedizione_ad_hoc_effective_quantity(row, scan_fields)
    effective_weight = _spedizione_ad_hoc_effective_weight(row, scan_fields)
    quantita_scan_label = ""
    if scan_fields.get("scan_progressivo") is not None and scan_fields.get("scan_totale") is not None:
        quantita_scan_label = f"{scan_fields.get('scan_progressivo'):g} di {scan_fields.get('scan_totale'):g}"
    return {
        "id": row.id,
        "commessa_id": row.commessa_id,
        "revisione_id": row.revisione_id,
        "spedizione_id": row.spedizione_id,
        "row_index": row.row_index,
        "codice": row.codice,
        "descrizione": row.descrizione,
        "profilo": row.profilo,
        "quantita": effective_quantity,
        "quantita_scan_label": quantita_scan_label,
        "quantita_file": float(row.quantita or 0),
        "lunghezza_mm": float(row.lunghezza_mm) if row.lunghezza_mm is not None else None,
        "larghezza_mm": float(row.larghezza_mm) if row.larghezza_mm is not None else None,
        "altezza_mm": float(row.altezza_mm) if row.altezza_mm is not None else None,
        "peso_unitario_kg": float(row.peso_unitario_kg) if row.peso_unitario_kg is not None else None,
        "peso_totale_kg": effective_weight,
        "peso_file_kg": float(row.peso_totale_kg) if row.peso_totale_kg is not None else None,
        "area_verniciabile_mq": float(row.area_verniciabile_mq) if row.area_verniciabile_mq is not None else None,
        "trattamento": row.trattamento,
        "tipo_unita": row.tipo_unita,
        "lavorazioni_status": None,
        "cantiere_status": row.stato,
        "trovato_at": row.trovato_at,
        "source_file": row.source_file,
        "scan_fields": scan_fields,
        "peso_scan_kg": scan_fields.get("peso_scan_kg"),
        "peso_mismatch": bool(scan_fields.get("peso_mismatch")),
        "qr_image_url": "",
        "qr_payload": "",
        "spedizione_ad_hoc": True,
    }


def _ddt_manual_item_read(row: DdtManualItem) -> dict:
    return {
        "id": row.id,
        "commessa_id": row.commessa_id,
        "revisione_id": row.revisione_id,
        "spedizione_ad_hoc_id": row.spedizione_ad_hoc_id,
        "row_index": row.row_index,
        "codice": row.codice or "",
        "descrizione": row.descrizione,
        "profilo": row.profilo,
        "quantita": float(row.quantita or 0),
        "peso_totale_kg": float(row.peso_totale_kg) if row.peso_totale_kg is not None else None,
        "trattamento": row.trattamento,
        "tipo_unita": "DDT_MANUALE",
        "cantiere_status": "DDT_MANUALE",
        "source_file": row.source_file,
        "note": row.note,
        "created_at": row.created_at,
    }


def _ddt_shipment_read(row: DdtShipment) -> dict:
    return {
        "id": row.id,
        "numero": row.numero,
        "titolo": row.titolo,
        "created_at": row.created_at,
        "righe_count": row.righe_count,
        "materiali": row.materiali_snapshot or [],
    }


def _ddt_context_filters(commessa_id: int, revisione_id: int | None, spedizione_ad_hoc_id: int | None) -> list:
    filters = [DdtManualItem.commessa_id == commessa_id]
    if spedizione_ad_hoc_id is not None:
        filters.append(DdtManualItem.spedizione_ad_hoc_id == spedizione_ad_hoc_id)
    else:
        filters.append(DdtManualItem.spedizione_ad_hoc_id.is_(None))
        filters.append(DdtManualItem.revisione_id == revisione_id)
    return filters


def _ddt_shipment_filters(commessa_id: int, revisione_id: int | None, spedizione_ad_hoc_id: int | None) -> list:
    filters = [DdtShipment.commessa_id == commessa_id]
    if spedizione_ad_hoc_id is not None:
        filters.append(DdtShipment.spedizione_ad_hoc_id == spedizione_ad_hoc_id)
    else:
        filters.append(DdtShipment.spedizione_ad_hoc_id.is_(None))
        filters.append(DdtShipment.revisione_id == revisione_id)
    return filters


def _load_ddt_manual_items(db: Session, commessa_id: int, revisione_id: int | None, spedizione_ad_hoc_id: int | None) -> list[DdtManualItem]:
    return (
        db.query(DdtManualItem)
        .filter(*_ddt_context_filters(commessa_id, revisione_id, spedizione_ad_hoc_id))
        .order_by(DdtManualItem.row_index, DdtManualItem.id)
        .all()
    )


def _load_ddt_shipments(db: Session, commessa_id: int, revisione_id: int | None, spedizione_ad_hoc_id: int | None) -> list[DdtShipment]:
    return (
        db.query(DdtShipment)
        .filter(*_ddt_shipment_filters(commessa_id, revisione_id, spedizione_ad_hoc_id))
        .order_by(DdtShipment.numero, DdtShipment.id)
        .all()
    )


def _current_ddt_context(db: Session, commessa_id: int) -> tuple[Commessa, CommessaRevisione, SpedizioneAdHoc | None]:
    commessa = crud.get_commessa(db=db, commessa_id=commessa_id)
    if commessa is None:
        raise HTTPException(404, "Commessa non trovata")
    revisione = _latest_revision(db, commessa_id)
    if revisione is None:
        raise HTTPException(404, "Nessuna analisi caricata per la commessa")
    spedizione_ad_hoc = None
    if bool((revisione.report_analisi or {}).get("spedizione_ad_hoc")):
        spedizione_ad_hoc = (
            db.query(SpedizioneAdHoc)
            .filter(
                SpedizioneAdHoc.commessa_id == commessa_id,
                SpedizioneAdHoc.revisione_id == revisione.id,
            )
            .order_by(SpedizioneAdHoc.id.desc())
            .first()
        )
    return commessa, revisione, spedizione_ad_hoc


def _insert_ddt_manual_rows(
    db: Session,
    commessa_id: int,
    revisione_id: int | None,
    spedizione_ad_hoc_id: int | None,
    rows: list[dict],
) -> list[DdtManualItem]:
    latest = (
        db.query(DdtManualItem)
        .filter(*_ddt_context_filters(commessa_id, revisione_id, spedizione_ad_hoc_id))
        .order_by(DdtManualItem.row_index.desc(), DdtManualItem.id.desc())
        .first()
    )
    row_index = int(latest.row_index if latest else 0)
    inserted: list[DdtManualItem] = []
    now = datetime.utcnow()
    for row in rows:
        desc = str(row.get("descrizione") or row.get("codice") or "").strip()
        if not desc:
            continue
        row_index += 1
        item = DdtManualItem(
            commessa_id=commessa_id,
            revisione_id=revisione_id,
            spedizione_ad_hoc_id=spedizione_ad_hoc_id,
            row_index=row_index,
            codice=(str(row.get("codice")).strip() if row.get("codice") else None),
            descrizione=desc,
            profilo=row.get("profilo"),
            quantita=row.get("quantita") or 1,
            peso_totale_kg=row.get("peso_totale_kg"),
            trattamento=row.get("trattamento"),
            source_file=row.get("source_file"),
            created_at=now,
            updated_at=now,
        )
        db.add(item)
        inserted.append(item)
    if not inserted:
        raise HTTPException(422, "Nessuna riga DDT manuale valida")
    db.commit()
    for item in inserted:
        db.refresh(item)
    return inserted


def _ddt_snapshot_row(row: dict, *, source: str) -> dict:
    trovato_at = row.get("trovato_at")
    if isinstance(trovato_at, datetime):
        trovato_at = trovato_at.isoformat()
    return {
        "source": source,
        "codice": row.get("codice") or "",
        "tipo_unita": row.get("tipo_unita") or source,
        "descrizione": row.get("descrizione") or "",
        "profilo": row.get("profilo") or "",
        "quantita": row.get("quantita") or 0,
        "quantita_scan_label": row.get("quantita_scan_label") or "",
        "peso_totale_kg": row.get("peso_totale_kg") or 0,
        "trattamento": row.get("trattamento") or "",
        "cantiere_status": row.get("cantiere_status") or "",
        "trovato_at": trovato_at,
        "source_file": row.get("source_file") or "",
    }


def _ddt_snapshot_key(row: dict) -> tuple:
    weight = row.get("peso_totale_kg") or 0
    try:
        weight_key = round(float(weight), 4)
    except (TypeError, ValueError):
        weight_key = 0.0
    return (
        str(row.get("codice") or "").strip().upper(),
        str(row.get("descrizione") or "").strip().upper(),
        str(row.get("profilo") or "").strip().upper(),
        weight_key,
        str(row.get("trattamento") or "").strip().upper(),
    )


def _snapshot_counts(ddt_shipments: list[DdtShipment], source: str) -> dict[tuple, int]:
    counts: dict[tuple, int] = defaultdict(int)
    for shipment in ddt_shipments:
        for material in shipment.materiali_snapshot or []:
            if str(material.get("source") or "").upper() == source:
                counts[_ddt_snapshot_key(material)] += 1
    return counts


def _close_scans_already_in_ddt(
    db: Session,
    ddt_shipments: list[DdtShipment],
    rows: list[CommessaPostOfficinaItem] | list[SpedizioneAdHocItem],
) -> int:
    counts = _snapshot_counts(ddt_shipments, "SCAN")
    if not counts:
        return 0
    changed = 0
    now = datetime.utcnow()
    for row in rows:
        current_status = row.stato if isinstance(row, SpedizioneAdHocItem) else row.cantiere_status
        if current_status != "TROVATO":
            continue
        data = _spedizione_ad_hoc_item_read(row) if isinstance(row, SpedizioneAdHocItem) else _post_officina_item_read(row)
        key = _ddt_snapshot_key(data)
        if counts.get(key, 0) <= 0:
            continue
        if isinstance(row, SpedizioneAdHocItem):
            row.stato = "SPEDITO"
        else:
            row.cantiere_status = "SPEDITO"
        row.updated_at = now
        counts[key] -= 1
        changed += 1
    if changed:
        db.commit()
    return changed


def _delete_manual_items_already_in_ddt(
    db: Session,
    ddt_shipments: list[DdtShipment],
    manual_rows: list[DdtManualItem],
) -> int:
    counts = _snapshot_counts(ddt_shipments, "MANUALE_DDT")
    if not counts:
        return 0
    deleted = 0
    for row in manual_rows:
        key = _ddt_snapshot_key(_ddt_manual_item_read(row))
        if counts.get(key, 0) <= 0:
            continue
        db.delete(row)
        counts[key] -= 1
        deleted += 1
    if deleted:
        db.commit()
    return deleted


@router.get("/{commessa_id}/post-officina")
def get_post_officina(commessa_id: int, db: Session = Depends(get_db)):
    commessa = crud.get_commessa(db=db, commessa_id=commessa_id)
    if commessa is None:
        raise HTTPException(404, "Commessa non trovata")
    revisione = _latest_revision(db, commessa_id)
    if revisione is None:
        raise HTTPException(404, "Nessuna analisi caricata per la commessa")
    is_ad_hoc_spedizione = bool((revisione.report_analisi or {}).get("spedizione_ad_hoc"))
    spedizione_ad_hoc = None
    if is_ad_hoc_spedizione:
        spedizione_ad_hoc = (
            db.query(SpedizioneAdHoc)
            .filter(
                SpedizioneAdHoc.commessa_id == commessa_id,
                SpedizioneAdHoc.revisione_id == revisione.id,
            )
            .order_by(SpedizioneAdHoc.id.desc())
            .first()
        )
    if spedizione_ad_hoc:
        ad_hoc_rows = (
            db.query(SpedizioneAdHocItem)
            .filter(SpedizioneAdHocItem.spedizione_id == spedizione_ad_hoc.id)
            .order_by(SpedizioneAdHocItem.row_index, SpedizioneAdHocItem.id)
            .all()
        )
        manual_rows = _load_ddt_manual_items(db, commessa_id, revisione.id, spedizione_ad_hoc.id)
        ddt_shipments = _load_ddt_shipments(db, commessa_id, revisione.id, spedizione_ad_hoc.id)
        if _close_scans_already_in_ddt(db, ddt_shipments, ad_hoc_rows):
            ad_hoc_rows = (
                db.query(SpedizioneAdHocItem)
                .filter(SpedizioneAdHocItem.spedizione_id == spedizione_ad_hoc.id)
                .order_by(SpedizioneAdHocItem.row_index, SpedizioneAdHocItem.id)
                .all()
            )
        if _delete_manual_items_already_in_ddt(db, ddt_shipments, manual_rows):
            manual_rows = _load_ddt_manual_items(db, commessa_id, revisione.id, spedizione_ad_hoc.id)
        master_rows = [row for row in ad_hoc_rows if row.stato not in {"TROVATO", "SPEDITO"}]
        scan_rows = [row for row in ad_hoc_rows if row.stato == "TROVATO"]
        summary_by_type: dict[str, dict] = {}
        summary_by_treatment: dict[str, dict] = {}
        for row in master_rows:
            scan_fields = _scan_fields_from_note(row.note)
            effective_quantity = _spedizione_ad_hoc_effective_quantity(row, scan_fields)
            effective_weight = _spedizione_ad_hoc_effective_weight(row, scan_fields)
            tipo = row.tipo_unita or "SPEDIZIONE_AD_HOC"
            type_bucket = summary_by_type.setdefault(tipo, {"tipo": tipo, "righe": 0, "quantita": 0.0, "peso_kg": 0.0})
            type_bucket["righe"] += 1
            type_bucket["quantita"] += effective_quantity
            type_bucket["peso_kg"] += effective_weight

            trattamento = row.trattamento or "Non indicato"
            treatment_bucket = summary_by_treatment.setdefault(trattamento, {"trattamento": trattamento, "righe": 0, "quantita": 0.0, "peso_kg": 0.0})
            treatment_bucket["righe"] += 1
            treatment_bucket["quantita"] += effective_quantity
            treatment_bucket["peso_kg"] += effective_weight

        return {
            "commessa": {
                "id": commessa.id,
                "codice": commessa.codice,
                "descrizione": commessa.descrizione,
                "cliente": commessa.cliente,
                "status": commessa.status,
            },
            "revisione": {
                "id": revisione.id,
                "codice": revisione.codice,
                "imported_at": revisione.imported_at,
                "spedizione_ad_hoc": True,
                "spedizione_ad_hoc_id": spedizione_ad_hoc.id,
            },
            "summary": {
                "righe": len(master_rows),
                "quantita": sum(_spedizione_ad_hoc_effective_quantity(row) for row in master_rows),
                "peso_kg": sum(float(row.peso_totale_kg or 0) for row in master_rows),
                "peso_spedizione_kg": sum(
                    _spedizione_ad_hoc_effective_weight(row)
                    for row in scan_rows
                ),
                "assemblati": 0,
                "pezzi_sciolti": 0,
                "spedizione": len(master_rows),
                "non_classificati": 0,
                "trovati": len(scan_rows),
                "da_trovare": len(master_rows),
                "by_type": sorted(summary_by_type.values(), key=lambda item: item["tipo"]),
                "by_treatment": sorted(summary_by_treatment.values(), key=lambda item: item["trattamento"]),
            },
            "items": [_spedizione_ad_hoc_item_read(row) for row in master_rows],
            "scan_items": [_spedizione_ad_hoc_item_read(row) for row in scan_rows],
            "manual_items": [_ddt_manual_item_read(row) for row in manual_rows],
            "ddt_shipments": [_ddt_shipment_read(row) for row in ddt_shipments],
        }
    rows = (
        db.query(CommessaPostOfficinaItem)
        .filter(CommessaPostOfficinaItem.revisione_id == revisione.id)
        .order_by(CommessaPostOfficinaItem.row_index, CommessaPostOfficinaItem.id)
        .all()
    )
    if not rows:
        spedizione_doc = _spedizione_doc(revisione)
        if spedizione_doc and spedizione_doc.storage_path:
            spedizione_path = settings.upload_dir.parent / spedizione_doc.storage_path
            if spedizione_path.exists():
                try:
                    spedizione_items, _ = _parse_spedizione_file(spedizione_path)
                    _populate_post_officina_items(
                        db,
                        commessa.id,
                        revisione.id,
                        spedizione_items,
                        classify=not is_ad_hoc_spedizione,
                        default_tipo_unita="SPEDIZIONE" if is_ad_hoc_spedizione else "NON_CLASSIFICATO",
                    )
                    db.commit()
                    rows = (
                        db.query(CommessaPostOfficinaItem)
                        .filter(CommessaPostOfficinaItem.revisione_id == revisione.id)
                        .order_by(CommessaPostOfficinaItem.row_index, CommessaPostOfficinaItem.id)
                        .all()
                    )
                except Exception as exc:
                    _logger.warning(
                        "Backfill post-officina non riuscito per revisione %s commessa %d: %s",
                        revisione.codice,
                        commessa_id,
                        exc,
                    )
    summary_by_type: dict[str, dict] = {}
    summary_by_treatment: dict[str, dict] = {}
    manual_rows = _load_ddt_manual_items(db, commessa_id, revisione.id, None)
    ddt_shipments = _load_ddt_shipments(db, commessa_id, revisione.id, None)
    if _close_scans_already_in_ddt(db, ddt_shipments, rows):
        rows = (
            db.query(CommessaPostOfficinaItem)
            .filter(CommessaPostOfficinaItem.revisione_id == revisione.id)
            .order_by(CommessaPostOfficinaItem.row_index, CommessaPostOfficinaItem.id)
            .all()
        )
    if _delete_manual_items_already_in_ddt(db, ddt_shipments, manual_rows):
        manual_rows = _load_ddt_manual_items(db, commessa_id, revisione.id, None)
    for row in rows:
        tipo = row.tipo_unita or "NON_CLASSIFICATO"
        type_bucket = summary_by_type.setdefault(tipo, {"tipo": tipo, "righe": 0, "quantita": 0.0, "peso_kg": 0.0})
        type_bucket["righe"] += 1
        type_bucket["quantita"] += float(row.quantita or 0)
        type_bucket["peso_kg"] += float(row.peso_totale_kg or 0)

        trattamento = row.trattamento or "Non indicato"
        treatment_bucket = summary_by_treatment.setdefault(trattamento, {"trattamento": trattamento, "righe": 0, "quantita": 0.0, "peso_kg": 0.0})
        treatment_bucket["righe"] += 1
        treatment_bucket["quantita"] += float(row.quantita or 0)
        treatment_bucket["peso_kg"] += float(row.peso_totale_kg or 0)

    return {
        "commessa": {
            "id": commessa.id,
            "codice": commessa.codice,
            "descrizione": commessa.descrizione,
            "cliente": commessa.cliente,
            "status": commessa.status,
        },
        "revisione": {
            "id": revisione.id,
            "codice": revisione.codice,
            "imported_at": revisione.imported_at,
            "spedizione_ad_hoc": is_ad_hoc_spedizione,
        },
        "summary": {
            "righe": len(rows),
            "quantita": sum(float(row.quantita or 0) for row in rows),
            "peso_kg": sum(float(row.peso_totale_kg or 0) for row in rows),
            "peso_spedizione_kg": sum(float(row.peso_totale_kg or 0) for row in rows if row.cantiere_status == "TROVATO"),
            "assemblati": sum(1 for row in rows if row.tipo_unita == "ASSEMBLATO"),
            "pezzi_sciolti": sum(1 for row in rows if row.tipo_unita == "PEZZO_SCIOLTO"),
            "spedizione": sum(1 for row in rows if row.tipo_unita == "SPEDIZIONE"),
            "non_classificati": sum(1 for row in rows if row.tipo_unita == "NON_CLASSIFICATO"),
            "trovati": sum(1 for row in rows if row.cantiere_status == "TROVATO"),
            "da_trovare": sum(1 for row in rows if row.cantiere_status != "TROVATO"),
            "by_type": sorted(summary_by_type.values(), key=lambda item: item["tipo"]),
            "by_treatment": sorted(summary_by_treatment.values(), key=lambda item: item["trattamento"]),
        },
            "items": [_post_officina_item_read(row) for row in rows],
            "scan_items": [_post_officina_item_read(row) for row in rows if row.cantiere_status == "TROVATO"],
            "manual_items": [_ddt_manual_item_read(row) for row in manual_rows],
            "ddt_shipments": [_ddt_shipment_read(row) for row in ddt_shipments],
        }


@router.post("/{commessa_id}/post-officina/ddt-manual-items", status_code=201)
def add_ddt_manual_items(
    commessa_id: int,
    payload: DdtManualTextCreate,
    db: Session = Depends(get_db),
):
    _, revisione, spedizione_ad_hoc = _current_ddt_context(db, commessa_id)
    try:
        rows = _manual_ddt_rows_from_text(payload.text)
    except ValueError as exc:
        raise HTTPException(422, str(exc))
    inserted = _insert_ddt_manual_rows(
        db,
        commessa_id,
        revisione.id,
        spedizione_ad_hoc.id if spedizione_ad_hoc else None,
        rows,
    )
    return {"inserted": len(inserted), "items": [_ddt_manual_item_read(row) for row in inserted]}


@router.post("/{commessa_id}/post-officina/ddt-manual-items/import", status_code=201)
def import_ddt_manual_items(
    commessa_id: int,
    file: UploadFile = File(...),
    db: Session = Depends(get_db),
):
    _, revisione, spedizione_ad_hoc = _current_ddt_context(db, commessa_id)
    suffix = Path(file.filename or "").suffix.lower() or ".xlsx"
    if suffix not in {".xlsx", ".xls", ".xlsm", ".csv"}:
        raise HTTPException(422, "Formato file non supportato: usa Excel o CSV")
    with tempfile.NamedTemporaryFile(delete=False, suffix=suffix) as tmp:
        shutil.copyfileobj(file.file, tmp)
        tmp_path = Path(tmp.name)
    try:
        try:
            rows = _manual_ddt_rows_from_table(tmp_path)
        except Exception as exc:
            raise HTTPException(422, f"File DDT manuale non importabile: {exc}")
        inserted = _insert_ddt_manual_rows(
            db,
            commessa_id,
            revisione.id,
            spedizione_ad_hoc.id if spedizione_ad_hoc else None,
            rows,
        )
        return {"inserted": len(inserted), "items": [_ddt_manual_item_read(row) for row in inserted]}
    finally:
        tmp_path.unlink(missing_ok=True)


@router.delete("/{commessa_id}/post-officina/ddt-manual-items/{item_id}", status_code=204)
def delete_ddt_manual_item(
    commessa_id: int,
    item_id: int,
    db: Session = Depends(get_db),
):
    row = (
        db.query(DdtManualItem)
        .filter(DdtManualItem.id == item_id, DdtManualItem.commessa_id == commessa_id)
        .first()
    )
    if row is None:
        raise HTTPException(404, "Riga manuale DDT non trovata")
    db.delete(row)
    db.commit()


@router.post("/{commessa_id}/post-officina/ddt-shipments", status_code=201)
def create_ddt_shipment(
    commessa_id: int,
    db: Session = Depends(get_db),
):
    commessa, revisione, spedizione_ad_hoc = _current_ddt_context(db, commessa_id)
    now = datetime.utcnow()
    if spedizione_ad_hoc:
        rows = (
            db.query(SpedizioneAdHocItem)
            .filter(SpedizioneAdHocItem.spedizione_id == spedizione_ad_hoc.id)
            .order_by(SpedizioneAdHocItem.row_index, SpedizioneAdHocItem.id)
            .all()
        )
        scanned_rows = [row for row in rows if row.stato == "TROVATO"]
        scanned = [
            _ddt_snapshot_row(_spedizione_ad_hoc_item_read(row), source="SCAN")
            for row in scanned_rows
        ]
        spedizione_ad_hoc_id = spedizione_ad_hoc.id
    else:
        rows = (
            db.query(CommessaPostOfficinaItem)
            .filter(CommessaPostOfficinaItem.revisione_id == revisione.id)
            .order_by(CommessaPostOfficinaItem.row_index, CommessaPostOfficinaItem.id)
            .all()
        )
        scanned_rows = [row for row in rows if row.cantiere_status == "TROVATO"]
        scanned = [
            _ddt_snapshot_row(_post_officina_item_read(row), source="SCAN")
            for row in scanned_rows
        ]
        spedizione_ad_hoc_id = None

    manual_rows = _load_ddt_manual_items(db, commessa_id, revisione.id, spedizione_ad_hoc_id)
    manual = [_ddt_snapshot_row(_ddt_manual_item_read(row), source="MANUALE_DDT") for row in manual_rows]
    materials = scanned + manual
    if not materials:
        raise HTTPException(409, "Nessuna riga trovata o aggiunta manuale da inserire nel DDT")

    latest = (
        db.query(DdtShipment)
        .filter(*_ddt_shipment_filters(commessa_id, revisione.id, spedizione_ad_hoc_id))
        .order_by(DdtShipment.numero.desc(), DdtShipment.id.desc())
        .first()
    )
    numero = int(latest.numero if latest else 0) + 1
    shipment = DdtShipment(
        commessa_id=commessa_id,
        revisione_id=revisione.id,
        spedizione_ad_hoc_id=spedizione_ad_hoc_id,
        numero=numero,
        titolo=f"Spedizione #{numero}",
        righe_count=len(materials),
        materiali_snapshot=materials,
        created_at=now,
    )
    db.add(shipment)
    for row in scanned_rows:
        if isinstance(row, SpedizioneAdHocItem):
            row.stato = "SPEDITO"
            row.updated_at = now
        else:
            row.cantiere_status = "SPEDITO"
            row.updated_at = now
    for row in manual_rows:
        db.delete(row)
    if spedizione_ad_hoc:
        spedizione_ad_hoc.updated_at = now
    db.commit()
    db.refresh(shipment)
    result = _ddt_shipment_read(shipment)
    result["commessa"] = {"codice": commessa.codice, "descrizione": commessa.descrizione}
    return result


@router.patch("/{commessa_id}/post-officina/items/{item_id}/mark-found")
def mark_post_officina_item_found(
    commessa_id: int,
    item_id: int,
    payload: ShippingItemManualFound,
    db: Session = Depends(get_db),
):
    commessa = crud.get_commessa(db=db, commessa_id=commessa_id)
    if commessa is None:
        raise HTTPException(404, "Commessa non trovata")

    source = (payload.source or "").strip().upper()
    now = datetime.utcnow()
    if source == "AD_HOC":
        row = (
            db.query(SpedizioneAdHocItem)
            .filter(
                SpedizioneAdHocItem.id == item_id,
                SpedizioneAdHocItem.commessa_id == commessa_id,
            )
            .first()
        )
        if row is None:
            raise HTTPException(404, "Riga spedizione ad hoc non trovata")
        previous_scans = (
            db.query(SpedizioneAdHocItem)
            .filter(
                SpedizioneAdHocItem.spedizione_id == row.spedizione_id,
                SpedizioneAdHocItem.codice == row.codice,
                SpedizioneAdHocItem.stato == "TROVATO",
            )
            .count()
        )
        scan_total = float(row.quantita or 0)
        if scan_total > 0 and previous_scans >= scan_total:
            raise HTTPException(409, f"Quantità già completata per {row.codice}")
        next_row_index = (
            db.query(SpedizioneAdHocItem.row_index)
            .filter(SpedizioneAdHocItem.spedizione_id == row.spedizione_id)
            .order_by(SpedizioneAdHocItem.row_index.desc(), SpedizioneAdHocItem.id.desc())
            .first()
        )
        unit_weight = float(row.peso_unitario_kg) if row.peso_unitario_kg is not None else None
        if unit_weight is None and row.peso_totale_kg is not None and scan_total > 0:
            unit_weight = float(row.peso_totale_kg) / scan_total
        scan_fields = {
            "manuale": True,
            "codice_trovato": row.codice,
            "raw_payload": "MANUALE",
            "peso_mismatch": False,
            "scan_progressivo": previous_scans + 1,
            "scan_totale": scan_total,
        }
        scan_row = SpedizioneAdHocItem(
            spedizione_id=row.spedizione_id,
            commessa_id=row.commessa_id,
            revisione_id=row.revisione_id,
            row_index=(int(next_row_index[0]) if next_row_index else 0) + 1,
            codice=row.codice,
            descrizione=row.descrizione,
            profilo=row.profilo,
            quantita=1,
            lunghezza_mm=row.lunghezza_mm,
            larghezza_mm=row.larghezza_mm,
            altezza_mm=row.altezza_mm,
            peso_unitario_kg=row.peso_unitario_kg,
            peso_totale_kg=unit_weight,
            area_verniciabile_mq=row.area_verniciabile_mq,
            trattamento=row.trattamento,
            tipo_unita=row.tipo_unita,
            stato="TROVATO",
            trovato_at=now,
            raw_payload="MANUALE",
            source_file=row.source_file,
            note="SCAN_FIELDS " + json.dumps(scan_fields, ensure_ascii=False, default=str),
        )
        db.add(scan_row)
        if row.spedizione:
            row.spedizione.updated_at = now
        db.commit()
        db.refresh(scan_row)
        return _spedizione_ad_hoc_item_read(scan_row)

    row = (
        db.query(CommessaPostOfficinaItem)
        .filter(
            CommessaPostOfficinaItem.id == item_id,
            CommessaPostOfficinaItem.commessa_id == commessa_id,
        )
        .first()
    )
    if row is None:
        raise HTTPException(404, "Riga spedizione non trovata")
    row.cantiere_status = "TROVATO"
    row.updated_at = now
    db.commit()
    db.refresh(row)
    return _post_officina_item_read(row)


@router.post("/{commessa_id}/step-5-1")
def activate_commessa_item_qr(commessa_id: int, db: Session = Depends(get_db)):
    """Attiva record e QR dei pezzi della revisione corrente.

    Non associa materiali, non prenota e non movimenta il magazzino.
    """
    commessa = crud.get_commessa(db=db, commessa_id=commessa_id)
    if commessa is None:
        raise HTTPException(404, "Commessa non trovata")
    revisione = _latest_revision(db, commessa_id)
    if revisione is None:
        raise HTTPException(404, "Nessuna analisi caricata per la commessa")
    if not revisione.corrente:
        raise HTTPException(409, "La revisione non è più corrente")
    if revisione.stato_analisi != "PRONTA":
        raise HTTPException(409, "L'analisi file non è pronta: verifica i dati base prima di generare i QR")

    pieces = db.query(Piece).filter(
        Piece.revisione_id == revisione.id,
        Piece.distinta_item_id.isnot(None),
    ).all()
    total = len(pieces)
    if total == 0:
        raise HTTPException(409, "La revisione non contiene pezzi fisici")

    item_ids = [piece.distinta_item_id for piece in pieces if piece.distinta_item_id]
    items_by_id = {
        item.id: item
        for item in db.query(DistintaItem).filter(DistintaItem.id.in_(item_ids)).all()
    } if item_ids else {}
    totals = _piece_totals(pieces)
    now = datetime.utcnow()
    for piece in pieces:
        piece.qr_payload = _expected_piece_payload(piece, commessa, totals)
        piece.qr_attivo = True
        piece.qr_status = "ACTIVE"
        piece.stato_attuale = "DA_PRODURRE"
        piece.updated_at = now
        item = items_by_id.get(piece.distinta_item_id)
        if item:
            item.qr_attivo = True
            item.stato_tracciamento = "DA_PRODURRE"
            item.qr_code = generate_qr_for_payload(piece.qr_payload)
    if revisione.step51_completed_at is None:
        revisione.step51_completed_at = now
    db.commit()
    _ensure_revision_qr_consistency(db, revisione)
    return {
        "commessa_id": commessa_id,
        "revisione_id": revisione.id,
        "step": "5.1",
        "stato": "COMPLETATO",
        "qr_attivi": total,
        "predistinta": revisione.predistinta,
        "step51_completed_at": revisione.step51_completed_at,
    }


@router.get("/{commessa_id}/step-5-1/items")
def list_commessa_item_qr(
    commessa_id: int,
    skip: int = 0,
    limit: int = 60,
    q: str | None = None,
    db: Session = Depends(get_db),
):
    revisione = _latest_revision(db, commessa_id)
    if revisione is None:
        raise HTTPException(404, "Nessuna analisi caricata per la commessa")
    if revisione.step51_completed_at is None:
        raise HTTPException(409, "Lo Step 5.1 non è ancora stato completato")
    _ensure_revision_qr_consistency(db, revisione)

    query = db.query(Piece).filter(
        Piece.revisione_id == revisione.id,
        Piece.distinta_item_id.isnot(None),
        Piece.qr_attivo.is_(True),
    )
    if q:
        pattern = f"%{q.strip()}%"
        query = query.filter(or_(
            Piece.qr_code.ilike(pattern),
            Piece.marca_pos.ilike(pattern),
            Piece.tipo_profilo.ilike(pattern),
            Piece.profilo.ilike(pattern),
            Piece.materiale.ilike(pattern),
            Piece.assemblato_id.ilike(pattern),
            Piece.note_materiale.ilike(pattern),
        ))
    total = query.count()
    safe_limit = min(max(limit, 1), 5000)
    items = (
        query.order_by(Piece.marca_pos, Piece.progressivo, Piece.id)
        .offset(max(skip, 0))
        .limit(safe_limit)
        .all()
    )
    commessa = db.get(Commessa, commessa_id)
    return {
        "commessa_id": commessa_id,
        "revisione_id": revisione.id,
        "total": total,
        "skip": max(skip, 0),
        "limit": safe_limit,
        "items": [
            {**_piece_qr_read(item), "commessa": commessa.codice if commessa else str(commessa_id)}
            for item in items
        ],
    }


@router.get("/{commessa_id}/spedizione-qr/items")
def list_commessa_spedizione_qr(
    commessa_id: int,
    skip: int = 0,
    limit: int = 60,
    q: str | None = None,
    db: Session = Depends(get_db),
):
    commessa = crud.get_commessa(db=db, commessa_id=commessa_id)
    if commessa is None:
        raise HTTPException(404, "Commessa non trovata")
    revisione = _latest_revision(db, commessa_id)
    if revisione is None:
        raise HTTPException(404, "Nessuna analisi caricata per la commessa")

    _ensure_spedizione_qr_pieces(db, commessa, revisione)
    query = _shipping_piece_query(db, revisione.id)
    if q:
        pattern = f"%{q.strip()}%"
        query = query.filter(or_(
            Piece.qr_code.ilike(pattern),
            Piece.marca_pos.ilike(pattern),
            Piece.tipo_profilo.ilike(pattern),
            Piece.profilo.ilike(pattern),
            Piece.materiale.ilike(pattern),
            Piece.assemblato_id.ilike(pattern),
            Piece.note_materiale.ilike(pattern),
            Piece.qr_payload.ilike(pattern),
        ))
    total = query.count()
    safe_limit = min(max(limit, 1), 5000)
    items = (
        query.order_by(Piece.marca_pos, Piece.progressivo, Piece.id)
        .offset(max(skip, 0))
        .limit(safe_limit)
        .all()
    )
    return {
        "commessa_id": commessa_id,
        "revisione_id": revisione.id,
        "total": total,
        "skip": max(skip, 0),
        "limit": safe_limit,
        "items": [
            {**_piece_qr_read(item), "commessa": commessa.codice}
            for item in items
        ],
    }


@router.get("/{commessa_id}/step-5-1/items/{piece_id}/label.pdf")
def download_commessa_piece_label(
    commessa_id: int,
    piece_id: int,
    width_mm: float = Query(70, ge=40, le=210),
    height_mm: float = Query(120, ge=40, le=297),
    db: Session = Depends(get_db),
):
    """Stampa il QR commessa nel formato MCC; non riguarda il magazzino."""
    piece = db.query(Piece).filter(
        Piece.id == piece_id,
        Piece.commessa_id == commessa_id,
        Piece.qr_attivo.is_(True),
    ).first()
    if piece is None:
        raise HTTPException(404, "Pezzo commessa non trovato o QR non attivo")
    commessa = db.get(Commessa, commessa_id)
    if commessa is None:
        raise HTTPException(404, "Commessa non trovata")
    same_registry_filter = Piece.distinta_item_id.is_(None) if piece.distinta_item_id is None else Piece.distinta_item_id.isnot(None)
    totale = db.query(Piece).filter(
        Piece.revisione_id == piece.revisione_id,
        Piece.marca_pos == piece.marca_pos,
        same_registry_filter,
    ).count()
    pdf_bytes = generate_piece_label_pdf(
        piece,
        commessa,
        totale,
        width_mm=width_mm,
        height_mm=height_mm,
    )
    filename = f"etichetta_{piece.qr_code}.pdf"
    return Response(
        content=pdf_bytes,
        media_type="application/pdf",
        headers={"Content-Disposition": f'inline; filename="{filename}"'},
    )


@router.post("/{commessa_id}/step-5-1/labels.pdf")
def download_commessa_piece_labels(
    commessa_id: int,
    body: PieceLabelsRequest,
    db: Session = Depends(get_db),
):
    """PDF multipagina delle etichette Piece selezionate, anche ad hoc."""
    commessa = db.get(Commessa, commessa_id)
    if commessa is None:
        raise HTTPException(404, "Commessa non trovata")
    requested_ids = list(dict.fromkeys(body.piece_ids))
    pieces = db.query(Piece).filter(
        Piece.commessa_id == commessa_id,
        Piece.id.in_(requested_ids),
        Piece.qr_attivo.is_(True),
    ).all()
    by_id = {piece.id: piece for piece in pieces}
    missing = [piece_id for piece_id in requested_ids if piece_id not in by_id]
    if missing:
        raise HTTPException(404, f"{len(missing)} QR selezionati non sono disponibili")

    revision_ids = {piece.revisione_id for piece in pieces}
    all_revision_pieces = db.query(Piece).filter(
        Piece.revisione_id.in_(revision_ids),
    ).all()
    totals: dict[tuple[int, str, bool], int] = defaultdict(int)
    for piece in all_revision_pieces:
        totals[(piece.revisione_id, piece.marca_pos or "", piece.distinta_item_id is None)] += 1
    ordered_labels = [
        (
            by_id[piece_id],
            commessa,
            totals[(
                by_id[piece_id].revisione_id,
                by_id[piece_id].marca_pos or "",
                by_id[piece_id].distinta_item_id is None,
            )],
        )
        for piece_id in requested_ids
    ]
    pdf_bytes = generate_piece_labels_pdf(
        ordered_labels,
        width_mm=body.width_mm,
        height_mm=body.height_mm,
    )
    return Response(
        content=pdf_bytes,
        media_type="application/pdf",
        headers={"Content-Disposition": 'inline; filename="etichette_selezionate.pdf"'},
    )


@router.get("/{commessa_id}/step-5-1/warehouse-mapping")
def get_commessa_warehouse_mapping(
    commessa_id: int,
    db: Session = Depends(get_db),
):
    revisione = _latest_revision(db, commessa_id)
    if revisione is None:
        raise HTTPException(404, "Nessuna analisi caricata per la commessa")

    pieces = (
        db.query(Piece)
        .filter(
            Piece.commessa_id == commessa_id,
            Piece.revisione_id == revisione.id,
            Piece.materiale_origine_id.isnot(None),
        )
        .order_by(Piece.materiale_origine_id, Piece.qr_code)
        .all()
    )
    item_ids = sorted({piece.materiale_origine_id for piece in pieces if piece.materiale_origine_id})
    if not item_ids:
        return {"count": 0, "items": []}

    warehouse_items = (
        db.query(WarehouseItem)
        .options(joinedload(WarehouseItem.material))
        .filter(WarehouseItem.id.in_(item_ids))
        .all()
    )
    warehouse_by_id = {item.id: item for item in warehouse_items}
    pieces_by_item: dict[int, list[Piece]] = defaultdict(list)
    for piece in pieces:
        if piece.materiale_origine_id in warehouse_by_id:
            pieces_by_item[piece.materiale_origine_id].append(piece)

    items = [
        _warehouse_item_mapping_read(item, pieces_by_item[item_id])
        for item_id, item in sorted(
            warehouse_by_id.items(),
            key=lambda pair: (
                getattr(pair[1].material, "code", "") or "",
                pair[1].ordinal or 0,
            ),
        )
    ]
    return {"count": len(items), "items": items}


@router.get("/{commessa_id}/scan-test-kit")
def commessa_scan_test_kit(
    commessa_id: int,
    db: Session = Depends(get_db),
):
    revisione = _latest_revision(db, commessa_id)
    if revisione is None:
        raise HTTPException(404, "Nessuna analisi caricata per la commessa")
    _ensure_revision_qr_consistency(db, revisione, force=True)

    workstations = (
        db.query(Workstation)
        .filter(Workstation.active.is_(True))
        .order_by(Workstation.code)
        .all()
    )
    workstation = next(
        (
            row for row in workstations
            if not row.code.upper().startswith(("ASSEMBLAGGIO", "SALDATURA"))
        ),
        workstations[0] if workstations else None,
    )
    warehouse_item = (
        db.query(WarehouseItem)
        .filter(WarehouseItem.status.in_(["AVAILABLE", "RESERVED"]))
        .order_by(WarehouseItem.status, WarehouseItem.id)
        .first()
    )
    pieces = (
        db.query(Piece)
        .filter(
            Piece.revisione_id == revisione.id,
            Piece.qr_attivo.is_(True),
        )
        .order_by(Piece.marca_pos, Piece.progressivo, Piece.id)
        .limit(3)
        .all()
    )
    return {
        "commessa_id": commessa_id,
        "revisione_id": revisione.id,
        "workstation": None if not workstation else {
            "id": workstation.id,
            "code": workstation.code,
            "name": workstation.name,
            "start_payload": workstation.start_qr_code,
            "start_qr_image_url": f"data:image/png;base64,{generate_qr_for_payload(workstation.start_qr_code)}",
            "end_payload": workstation.end_qr_code,
            "end_qr_image_url": f"data:image/png;base64,{generate_qr_for_payload(workstation.end_qr_code)}",
        },
        "warehouse_item": None if not warehouse_item else {
            "id": warehouse_item.id,
            "uuid": warehouse_item.uuid,
            "payload": warehouse_item.uuid,
            "qr_image_url": f"/qr-image/{warehouse_item.uuid}.png",
            "label": getattr(warehouse_item.material, "code", None) or warehouse_item.uuid,
            "status": warehouse_item.status,
        },
        "pieces": [
            {
                "id": piece.id,
                "uuid": piece.uuid,
                "payload": piece.qr_payload,
                "qr_code": piece.qr_code,
                "qr_image_url": f"/piece-qr-image/{piece.uuid}.png",
                "profilo": piece.profilo,
                "stato": piece.stato_attuale,
            }
            for piece in pieces
        ],
    }


@router.post("/{commessa_id}/scan-test")
def commessa_mouse_scan_test(
    commessa_id: int,
    body: MouseScanRequest,
    db: Session = Depends(get_db),
):
    revisione = _latest_revision(db, commessa_id)
    if revisione is None:
        raise HTTPException(404, "Nessuna analisi caricata per la commessa")
    _ensure_revision_qr_consistency(db, revisione)

    scanner = db.query(ScannerDevice).filter(ScannerDevice.scanner_code == "MOUSE_TEST").first()
    if scanner is None:
        scanner = ScannerDevice(
            scanner_code="MOUSE_TEST",
            name="Test mouse",
            scan_mode="OFFICINA",
            device_token="mouse-test",
            active=True,
        )
        db.add(scanner)
        db.flush()
    scanner.active = True

    payload = (body.payload or "").strip()
    workstation = db.query(Workstation).filter(
        or_(Workstation.start_qr_code == payload, Workstation.end_qr_code == payload)
    ).first()
    if workstation:
        scanner.postazione_id = workstation.id
    elif scanner.postazione_id is None:
        first_workstation = db.query(Workstation).filter(Workstation.active.is_(True)).order_by(Workstation.code).first()
        if first_workstation:
            scanner.postazione_id = first_workstation.id
    db.flush()
    return process_workshop_scan(db, scanner, payload, f"MOUSE-{datetime.utcnow().timestamp()}")


@router.post("/{commessa_id}/preproduction-scan-test")
def commessa_mouse_preproduction_scan_test(
    commessa_id: int,
    body: MouseScanRequest,
    db: Session = Depends(get_db),
):
    revisione = _latest_revision(db, commessa_id)
    if revisione is None:
        raise HTTPException(404, "Nessuna analisi caricata per la commessa")
    _ensure_revision_qr_consistency(db, revisione)

    scanner = db.query(ScannerDevice).filter(ScannerDevice.scanner_code == "MOUSE_PREPROD_TEST").first()
    if scanner is None:
        scanner = ScannerDevice(
            scanner_code="MOUSE_PREPROD_TEST",
            name="Test mouse pre-produzione",
            scan_mode="MAGAZZINO",
            device_token="mouse-preprod-test",
            active=True,
        )
        db.add(scanner)
        db.flush()
    scanner.active = True
    payload = (body.payload or "").strip()
    db.flush()
    return process_preproduction_scan(db, scanner, payload, f"MOUSE-PREPROD-{datetime.utcnow().timestamp()}")


@router.post("/{commessa_id}/scan-test/reset")
def reset_commessa_mouse_scan_test(
    commessa_id: int,
    db: Session = Depends(get_db),
):
    revisione = _latest_revision(db, commessa_id)
    if revisione is None:
        raise HTTPException(404, "Nessuna analisi caricata per la commessa")
    scanners = db.query(ScannerDevice).filter(
        ScannerDevice.scanner_code.in_(["MOUSE_TEST", "MOUSE_PREPROD_TEST"])
    ).all()
    scanner_ids = [scanner.id for scanner in scanners]

    pieces = db.query(Piece).filter(Piece.revisione_id == revisione.id).all()
    piece_ids = [piece.id for piece in pieces]

    deleted_events = 0
    deleted_sessions = 0
    if piece_ids:
        deleted_events = (
            db.query(PieceScanEvent)
            .filter(PieceScanEvent.piece_id.in_(piece_ids))
            .delete(synchronize_session=False)
        )
        deleted_sessions = (
            db.query(PieceWorkSession)
            .filter(PieceWorkSession.piece_id.in_(piece_ids))
            .delete(synchronize_session=False)
        )

    deleted_attempts = deleted_blocks = 0
    if scanner_ids:
        warehouse_items = (
            db.query(WarehouseItem)
            .filter(WarehouseItem.reserved_by_scanner_id.in_(scanner_ids))
            .all()
        )
        for item in warehouse_items:
            item.status = "AVAILABLE"
            item.reserved_at = None
            item.reserved_by_scanner_id = None
            item.reserved_for_commessa = None
        deleted_attempts = (
            db.query(WorkshopScanAttempt)
            .filter(WorkshopScanAttempt.scanner_device_id.in_(scanner_ids))
            .delete(synchronize_session=False)
        )
        deleted_blocks = (
            db.query(WorkshopScanBlock)
            .filter(WorkshopScanBlock.scanner_device_id.in_(scanner_ids))
            .delete(synchronize_session=False)
        )
    for scanner in scanners:
        scanner.current_warehouse_item_id = None
        scanner.current_warehouse_item_set_at = None
        scanner.postazione_id = None

    for piece in pieces:
        piece.materiale_origine_status = "VUOTO"
        piece.materiale_origine_id = None
        piece.materiale_origine_assigned_at = None
        piece.materiale_origine_scanner_id = None
        piece.stato_attuale = "DA_PRODURRE"
        piece.ultima_postazione = None
        piece.ultimo_lavoro = None
        piece.ultimo_evento = None
        piece.ultimo_evento_at = None
        piece.lavorazione_aperta_id = None
        piece.updated_at = datetime.utcnow()
        if piece.distinta_item_id:
            item = db.get(DistintaItem, piece.distinta_item_id)
            if item:
                item.stato_tracciamento = "DA_PRODURRE"

    db.commit()
    return {
        "ok": True,
        "pieces_reset": len(pieces),
        "events_deleted": deleted_events,
        "sessions_deleted": deleted_sessions,
        "attempts_deleted": deleted_attempts,
        "blocks_deleted": deleted_blocks,
    }


@router.patch("/{commessa_id}/step-5-1/items/{piece_id}")
def update_commessa_piece_qr(
    commessa_id: int,
    piece_id: int,
    payload: PieceManualUpdate,
    db: Session = Depends(get_db),
):
    piece = db.get(Piece, piece_id)
    if piece is None or piece.commessa_id != commessa_id:
        raise HTTPException(404, "Pezzo QR non trovato")
    field_map = {
        "tipo": "tipo_profilo",
        "profilo": "profilo",
        "qualita": "materiale",
        "assemblato": "assemblato_id",
        "stato": "stato_attuale",
        "nota": "note_materiale",
    }
    data = payload.model_dump(exclude_unset=True)
    for public_field, model_field in field_map.items():
        if public_field in data:
            value = data[public_field]
            if public_field == "stato" and (value is None or not str(value).strip()):
                continue
            setattr(piece, model_field, value.strip() if isinstance(value, str) and value.strip() else None)
    piece.updated_at = datetime.utcnow()
    db.commit()
    db.refresh(piece)
    return _piece_qr_read(piece)


def _is_assembly_station(value: str | None) -> bool:
    code = (value or "").strip().upper()
    return code.startswith("ASSEMBLAGGIO") or code.startswith("ASS")


@router.get("/{commessa_id}/analisi/assemblati")
def get_assemblati_progress(commessa_id: int, db: Session = Depends(get_db)):
    commessa = crud.get_commessa(db=db, commessa_id=commessa_id)
    if commessa is None:
        raise HTTPException(404, "Commessa non trovata")
    revisione = _latest_revision(db, commessa_id)
    if revisione is None:
        raise HTTPException(404, "Nessuna analisi caricata per la commessa")

    pieces = (
        db.query(Piece)
        .options(joinedload(Piece.work_sessions), joinedload(Piece.scan_events))
        .filter(Piece.revisione_id == revisione.id)
        .order_by(Piece.assemblato_id, Piece.marca_pos, Piece.progressivo, Piece.id)
        .all()
    )
    bulloneria_rows = (
        db.query(CommessaBulloneria)
        .filter(CommessaBulloneria.revisione_id == revisione.id)
        .order_by(CommessaBulloneria.assemblato, CommessaBulloneria.tipo, CommessaBulloneria.codice, CommessaBulloneria.id)
        .all()
    )
    groups: dict[str, dict] = {}
    unassigned = 0
    for piece in pieces:
        if not piece.assemblato_id:
            unassigned += 1
            continue
        row = groups.setdefault(piece.assemblato_id, {
            "assemblato": piece.assemblato_id,
            "qr_image_url": f"/assembly-qr-image/{commessa_id}/{quote(str(piece.assemblato_id), safe='')}.png",
            "pezzi_previsti": 0,
            "qr_attivi": 0,
            "pezzi_entrati": 0,
            "pezzi_completati": 0,
            "started_at": None,
            "last_event_at": None,
            "last_event": None,
            "last_postazione": None,
            "pieces": [],
            "bulloneria": [],
            "bulloneria_righe": 0,
            "bulloneria_quantita": 0,
        })
        row["pezzi_previsti"] += 1
        if piece.qr_attivo:
            row["qr_attivi"] += 1

        assembly_sessions = [
            session for session in piece.work_sessions
            if _is_assembly_station(session.postazione_code)
        ]
        assembly_events = [
            event for event in piece.scan_events
            if _is_assembly_station(event.postazione_code)
            and event.event_type in {"PHASE_START", "PHASE_DONE", "PHASE_END"}
        ]
        entered = bool(assembly_sessions) or bool(assembly_events) or _is_assembly_station(piece.ultima_postazione)
        completed = any(session.closed_at for session in assembly_sessions) or any(
            event.event_type in {"PHASE_DONE", "PHASE_END"}
            for event in assembly_events
        )
        if entered:
            row["pezzi_entrati"] += 1
        if completed:
            row["pezzi_completati"] += 1

        timestamps = [session.started_at for session in assembly_sessions if session.started_at] + [
            event.timestamp for event in assembly_events if event.timestamp
        ]
        if timestamps:
            first_start = min(timestamps)
            if row["started_at"] is None or first_start < row["started_at"]:
                row["started_at"] = first_start
        if piece.ultimo_evento_at and (row["last_event_at"] is None or piece.ultimo_evento_at > row["last_event_at"]):
            row["last_event_at"] = piece.ultimo_evento_at
            row["last_event"] = piece.ultimo_evento
            row["last_postazione"] = piece.ultima_postazione

        row["pieces"].append({
            "id": piece.id,
            "uuid": piece.uuid,
            "qr_code": piece.qr_code,
            "marca_pos": piece.marca_pos,
            "progressivo": piece.progressivo,
            "profilo": piece.profilo,
            "qualita": piece.materiale,
            "stato": piece.stato_attuale,
            "ultima_postazione": piece.ultima_postazione,
            "ultimo_evento": piece.ultimo_evento,
            "ultimo_evento_at": piece.ultimo_evento_at,
            "entered_assembly": entered,
            "completed_assembly": completed,
        })

    bulloneria_senza_assemblato = 0
    for bolt in bulloneria_rows:
        if not bolt.assemblato:
            bulloneria_senza_assemblato += 1
            continue
        row = groups.setdefault(bolt.assemblato, {
            "assemblato": bolt.assemblato,
            "qr_image_url": f"/assembly-qr-image/{commessa_id}/{quote(str(bolt.assemblato), safe='')}.png",
            "pezzi_previsti": 0,
            "qr_attivi": 0,
            "pezzi_entrati": 0,
            "pezzi_completati": 0,
            "started_at": None,
            "last_event_at": None,
            "last_event": None,
            "last_postazione": None,
            "pieces": [],
            "bulloneria": [],
            "bulloneria_righe": 0,
            "bulloneria_quantita": 0,
        })
        qty = float(bolt.quantita or 0)
        row["bulloneria_righe"] += 1
        row["bulloneria_quantita"] += qty
        row["bulloneria"].append({
            "id": bolt.id,
            "codice": bolt.codice,
            "descrizione": bolt.descrizione,
            "categoria": bolt.categoria,
            "tipo": bolt.tipo,
            "norma": bolt.norma,
            "diametro": bolt.diametro,
            "lunghezza": bolt.lunghezza,
            "classe": bolt.classe,
            "trattamento": bolt.trattamento,
            "quantita": qty,
            "unita": bolt.unita,
            "peso_kg": float(bolt.peso_kg or 0),
            "note": bolt.note,
        })

    assemblati = []
    for row in groups.values():
        total = row["pezzi_previsti"] or 0
        completed = row["pezzi_completati"] or 0
        entered = row["pezzi_entrati"] or 0
        if total and completed >= total:
            stato = "COMPLETO"
        elif entered > 0:
            stato = "IN_ASSEMBLAGGIO"
        else:
            stato = "DA_PRODURRE"
        row["stato"] = stato
        row["progress"] = round((completed / total) * 100, 1) if total else 0
        row["narrative"] = (
            f"{row['assemblato']} richiede {row['pezzi_previsti']} pezzi strutturali"
            f" e {row['bulloneria_quantita']:g} componenti di bulloneria"
            f" su {row['bulloneria_righe']} righe dedicate."
        )
        assemblati.append(row)

    assemblati.sort(key=lambda row: row["assemblato"])
    totals = {
        "totali": len(assemblati),
        "da_produrre": sum(1 for row in assemblati if row["stato"] == "DA_PRODURRE"),
        "in_assemblaggio": sum(1 for row in assemblati if row["stato"] == "IN_ASSEMBLAGGIO"),
        "completi": sum(1 for row in assemblati if row["stato"] == "COMPLETO"),
        "pezzi_previsti": sum(row["pezzi_previsti"] for row in assemblati),
        "pezzi_entrati": sum(row["pezzi_entrati"] for row in assemblati),
        "pezzi_completati": sum(row["pezzi_completati"] for row in assemblati),
        "pezzi_senza_assemblato": unassigned,
        "bulloneria_righe": sum(row["bulloneria_righe"] for row in assemblati),
        "bulloneria_quantita": sum(row["bulloneria_quantita"] for row in assemblati),
        "assemblati_con_bulloneria": sum(1 for row in assemblati if row["bulloneria_righe"] > 0),
        "bulloneria_senza_assemblato": bulloneria_senza_assemblato,
    }
    totals["progress"] = round((totals["pezzi_completati"] / totals["pezzi_previsti"]) * 100, 1) if totals["pezzi_previsti"] else 0
    return {
        "commessa_id": commessa_id,
        "revisione_id": revisione.id,
        "summary": totals,
        "assemblati": assemblati,
    }


@router.get("/{commessa_id}/analisi/materiali")
def get_classificazione_materiali(commessa_id: int, db: Session = Depends(get_db)):
    commessa = crud.get_commessa(db=db, commessa_id=commessa_id)
    if commessa is None:
        raise HTTPException(404, "Commessa non trovata")
    revisione = _latest_revision(db, commessa_id)
    if revisione is None:
        raise HTTPException(404, "Nessuna analisi caricata per la commessa")

    items = (
        db.query(DistintaItem)
        .filter(
            DistintaItem.revisione_id == revisione.id,
            DistintaItem.invalidato.is_(False),
        )
        .all()
    )
    result = classify_commessa_materials(items)
    result["commessa_id"] = commessa_id
    result["revisione_id"] = revisione.id
    return result


# ── Fasi Operative ────────────────────────────────────────────────────────────

class FaseOperativaRead(BaseModel):
    id: int
    commessa_id: int
    marca_pos: Optional[str]
    profilo: Optional[str]
    quantita: Optional[float]
    fase: Optional[str]
    postazione: Optional[str]
    tempo_prev_minpz: Optional[float]
    tempo_tot_min: Optional[float]
    sequenza: Optional[int]
    dipende_da: Optional[str]
    note_operative: Optional[str]
    status: str

    model_config = {"from_attributes": True}


@router.post("/{commessa_id}/fasi/import", status_code=201)
def import_fasi(
    commessa_id: int,
    file: UploadFile = File(...),
    db: Session = Depends(get_db),
):
    commessa = crud.get_commessa(db=db, commessa_id=commessa_id)
    if commessa is None:
        raise HTTPException(404, "Commessa non trovata")

    suffix = Path(file.filename).suffix if file.filename else ".xlsx"
    with tempfile.NamedTemporaryFile(suffix=suffix, delete=False) as tmp:
        tmp.write(file.file.read())
        tmp_path = Path(tmp.name)

    try:
        rows = parse_fasi_operative(tmp_path)
    finally:
        tmp_path.unlink(missing_ok=True)

    if not rows:
        raise HTTPException(422, "Nessuna fase trovata nel file. Verifica che l'intestazione sia alla riga 4.")

    # Cancella fasi e percorsi precedenti (produzione non ancora avviata)
    db.query(PezzoPercorso).filter(PezzoPercorso.commessa_id == commessa_id).delete()
    db.query(FaseOperativa).filter(FaseOperativa.commessa_id == commessa_id).delete()

    for r in rows:
        db.add(FaseOperativa(
            commessa_id=commessa_id,
            marca_pos=r.get("marca_pos"),
            profilo=r.get("profilo"),
            quantita=r.get("quantita"),
            fase=r.get("fase"),
            postazione=r.get("postazione"),
            tempo_prev_minpz=r.get("tempo_prev_minpz"),
            tempo_tot_min=r.get("tempo_tot_min"),
            sequenza=r.get("sequenza"),
            dipende_da=r.get("dipende_da"),
            note_operative=r.get("note_operative"),
            status=FaseStatus.DA_INIZIARE,
        ))

    db.commit()
    return {"rows_imported": len(rows)}


@router.get("/{commessa_id}/fasi", response_model=List[FaseOperativaRead])
def list_fasi(commessa_id: int, db: Session = Depends(get_db)):
    commessa = crud.get_commessa(db=db, commessa_id=commessa_id)
    if commessa is None:
        raise HTTPException(404, "Commessa non trovata")
    return (
        db.query(FaseOperativa)
        .filter(FaseOperativa.commessa_id == commessa_id)
        .order_by(FaseOperativa.sequenza.nullslast(), FaseOperativa.id)
        .all()
    )


@router.patch("/{commessa_id}/fasi/{fase_id}", response_model=FaseOperativaRead)
def update_fase(
    commessa_id: int,
    fase_id: int,
    body: dict,
    db: Session = Depends(get_db),
):
    fase = db.get(FaseOperativa, fase_id)
    if not fase or fase.commessa_id != commessa_id:
        raise HTTPException(404, "Fase non trovata")
    if "status" in body:
        try:
            fase.status = FaseStatus(body["status"])
        except ValueError:
            raise HTTPException(400, f"Status non valido: {body['status']}")
    for field in ("postazione", "note_operative", "dipende_da"):
        if field in body:
            setattr(fase, field, body[field] or None)
    if "tempo_tot_min" in body:
        try:
            v = body["tempo_tot_min"]
            fase.tempo_tot_min = float(v) if v not in (None, "", 0) else None
        except (TypeError, ValueError):
            raise HTTPException(400, "tempo_tot_min deve essere un numero")
    db.commit()
    db.refresh(fase)
    return fase


# ── Avvia Produzione ──────────────────────────────────────────────────────────

@router.post("/{commessa_id}/avvia-produzione", status_code=201)
def avvia_produzione(commessa_id: int, db: Session = Depends(get_db)):
    _logger.info("[avvia] START commessa_id=%d", commessa_id)

    commessa = crud.get_commessa(db=db, commessa_id=commessa_id)
    if commessa is None:
        _logger.warning("[avvia] commessa %d non trovata", commessa_id)
        raise HTTPException(404, "Commessa non trovata")
    if commessa.status != CommessaStatus.APERTA:
        raise HTTPException(409, f"Commessa non è APERTA (stato attuale: {commessa.status})")

    revisione = _latest_revision(db, commessa_id)
    if revisione is None:
        raise HTTPException(404, "Nessuna analisi caricata per la commessa")
    if revisione.predistinta:
        raise HTTPException(409, "Produzione bloccata: la revisione corrente è una pre-distinta")
    if revisione.step51_completed_at is None:
        raise HTTPException(409, "Completa lo Step 5.1 prima di avviare la produzione")

    existing = db.query(PezzoPercorso).filter(PezzoPercorso.commessa_id == commessa_id).first()
    if existing:
        raise HTTPException(409, "Produzione già avviata per questa commessa")

    # ── 1. Fasi operative ──────────────────────────────────────────────────────
    fasi = (
        db.query(FaseOperativa)
        .filter(FaseOperativa.commessa_id == commessa_id)
        .all()
    )
    _logger.info("[avvia] fasi trovate: %d (distinct marca_pos: %d)",
                 len(fasi), len({f.marca_pos for f in fasi if f.marca_pos}))
    if not fasi:
        raise HTTPException(422, "Nessuna fase operativa importata. Importa prima le fasi.")

    # ── 2. Distinta items — cerca per commessa_id O per commessa_reference ────
    # Alcuni items hanno commessa_id=NULL ma commessa_reference=codice commessa
    items = (
        db.query(DistintaItem)
        .filter(
            or_(
                DistintaItem.commessa_id == commessa_id,
                DistintaItem.commessa_reference == commessa.codice,
            )
        )
        .all()
    )
    _logger.info("[avvia] distinta items trovati: %d (per commessa_id=%d OR ref='%s')",
                 len(items), commessa_id, commessa.codice)

    # ── 3. Raggruppa per (marca_pos, instance_number) — un row per istanza fisica
    # Struttura: instances_by_part[marca_pos] = list of (instance_number, first_item)
    # Un'istanza = la prima distinta_item con quella (part_number, instance_number)
    instances_by_part: dict[str, list] = defaultdict(list)
    seen_keys: set = set()
    for item in sorted(items, key=lambda x: (x.part_number or "", x.instance_number or 0, x.id)):
        if not item.part_number:
            continue
        if item.instance_number is None:
            # Riga riepilogativa (qty totale) — skippa, non è un'istanza fisica
            continue
        key = (item.part_number, item.instance_number)
        if key not in seen_keys:
            seen_keys.add(key)
            instances_by_part[item.part_number].append(item)

    _logger.info("[avvia] istanze fisiche distinte: %d", sum(len(v) for v in instances_by_part.values()))
    for part, inst_list in sorted(instances_by_part.items()):
        _logger.info("[avvia]   %-12s → %d istanze", part, len(inst_list))

    # ── 4. Raggruppa fasi per marca_pos ───────────────────────────────────────
    by_marca: dict = defaultdict(list)
    for f in fasi:
        if f.marca_pos:
            by_marca[f.marca_pos].append(f)

    _logger.info("[avvia] marca_pos con fasi: %s", sorted(by_marca.keys()))

    # Controlla quale marca_pos ha corrispondenza in distinta
    matched = [mp for mp in by_marca if mp in instances_by_part]
    unmatched = [mp for mp in by_marca if mp not in instances_by_part]
    _logger.info("[avvia] marca_pos con match distinta: %s", matched)
    _logger.info("[avvia] marca_pos SENZA match distinta (verranno tracciati senza item_id): %s", unmatched)

    # ── 5. Crea righe pezzo_percorso ───────────────────────────────────────────
    percorso_rows = []
    for marca_pos, fase_list in by_marca.items():
        sorted_fasi = sorted(fase_list, key=lambda f: (f.sequenza if f.sequenza is not None else 9999, f.id))
        instances = instances_by_part.get(marca_pos, [])

        if instances:
            # Un row per (istanza fisica × fase)
            for item in instances:
                for idx, fase in enumerate(sorted_fasi):
                    percorso_rows.append(PezzoPercorso(
                        commessa_id=commessa_id,
                        item_id=item.id,
                        fase_id=fase.id,
                        marca_pos=marca_pos,
                        instance_number=item.instance_number,
                        sequenza=fase.sequenza,
                        stato=PezzoStato.SBLOCCATA if idx == 0 else PezzoStato.BLOCCATA,
                        postazione=fase.postazione,
                    ))
        else:
            # Nessun item in distinta — crea tracking generico senza item_id
            for idx, fase in enumerate(sorted_fasi):
                percorso_rows.append(PezzoPercorso(
                    commessa_id=commessa_id,
                    item_id=None,
                    fase_id=fase.id,
                    marca_pos=marca_pos,
                    instance_number=None,
                    sequenza=fase.sequenza,
                    stato=PezzoStato.SBLOCCATA if idx == 0 else PezzoStato.BLOCCATA,
                    postazione=fase.postazione,
                ))

    _logger.info("[avvia] pezzo_percorso rows da inserire: %d", len(percorso_rows))
    db.add_all(percorso_rows)

    # ── 6. Visibilità postazioni ──────────────────────────────────────────────
    # Il vecchio sblocco automatico per utenti di postazione è stato disattivato:
    # l'avanzamento produzione sarà guidato dagli eventi QR reali di postazione.
    unlocked_count = 0
    first_postazioni = {
        row.postazione
        for row in percorso_rows
        if row.stato == PezzoStato.SBLOCCATA and row.postazione
    }

    # ── 7. Porta commessa in produzione ───────────────────────────────────────
    commessa.status = CommessaStatus.IN_PRODUZIONE
    db.commit()

    _logger.info("[avvia] DONE — %d righe percorso, %d operatori sbloccati", len(percorso_rows), unlocked_count)
    return {
        "pezzi_tipo":          len(by_marca),
        "istanze_fisiche":     len(seen_keys),
        "percorsi_creati":     len(percorso_rows),
        "prime_postazioni":    sorted(first_postazioni),
        "operatori_sbloccati": unlocked_count,
    }


@router.get("/{commessa_id}/percorso")
def get_percorso(commessa_id: int, db: Session = Depends(get_db)):
    """Restituisce i record pezzo_percorso per la commessa, usati dalla UI per mostrare lo stato."""
    rows = (
        db.query(PezzoPercorso)
        .filter(PezzoPercorso.commessa_id == commessa_id)
        .order_by(PezzoPercorso.marca_pos, PezzoPercorso.sequenza)
        .all()
    )
    return [
        {
            "id":         r.id,
            "item_id":    r.item_id,
            "fase_id":    r.fase_id,
            "marca_pos":  r.marca_pos,
            "sequenza":   r.sequenza,
            "stato":      r.stato,
            "postazione": r.postazione,
        }
        for r in rows
    ]


@router.get("/{commessa_id}/pezzi")
def get_pezzi(commessa_id: int, db: Session = Depends(get_db)):
    """Per ogni pezzo fisico: marca_pos, instance_number, profilo, QR e percorso fasi con stati."""
    commessa = crud.get_commessa(db=db, commessa_id=commessa_id)
    if commessa is None:
        raise HTTPException(404, "Commessa non trovata")

    rows = (
        db.query(PezzoPercorso, FaseOperativa)
        .join(FaseOperativa, PezzoPercorso.fase_id == FaseOperativa.id)
        .filter(PezzoPercorso.commessa_id == commessa_id)
        .order_by(
            PezzoPercorso.marca_pos,
            PezzoPercorso.instance_number.nullslast(),
            PezzoPercorso.sequenza.nullslast(),
            PezzoPercorso.id,
        )
        .all()
    )

    item_ids = {pp.item_id for pp, _ in rows if pp.item_id}
    items_map: dict[int, DistintaItem] = {}
    if item_ids:
        for it in db.query(DistintaItem).filter(DistintaItem.id.in_(item_ids)).all():
            items_map[it.id] = it

    grouped: dict[tuple, list] = defaultdict(list)
    for pp, fase in rows:
        grouped[(pp.marca_pos, pp.instance_number)].append((pp, fase))

    result = []
    for (marca_pos, instance_number), steps in sorted(
        grouped.items(),
        key=lambda x: (x[0][0] or '', x[0][1] if x[0][1] is not None else -1),
    ):
        item_id = next((pp.item_id for pp, _ in steps if pp.item_id), None)
        item = items_map.get(item_id) if item_id else None

        all_done = all(pp.stato == PezzoStato.COMPLETATA for pp, _ in steps)
        current = next(
            ((pp, f) for pp, f in steps if pp.stato in (PezzoStato.SBLOCCATA, PezzoStato.IN_CORSO)),
            None,
        )

        if current:
            stato_corrente = current[0].stato
            fase_corrente = current[1].fase
        elif all_done:
            stato_corrente = PezzoStato.COMPLETATA
            fase_corrente = None
        else:
            stato_corrente = PezzoStato.BLOCCATA
            fase_corrente = steps[0][1].fase if steps else None

        result.append({
            "marca_pos":       marca_pos,
            "instance_number": instance_number,
            "item_id":         item_id,
            "profilo":         item.description if item else None,
            "parent_assembly": item.parent_assembly if item else None,
            "qr_code":         item.qr_code if item else None,
            "stato_corrente":  stato_corrente,
            "fase_corrente":   fase_corrente,
            "percorso": [
                {
                    "percorso_id": pp.id,
                    "fase_id":     pp.fase_id,
                    "fase_name":   f.fase,
                    "sequenza":    pp.sequenza,
                    "postazione":  pp.postazione,
                    "stato":       pp.stato,
                }
                for pp, f in steps
            ],
        })

    return result
