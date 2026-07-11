import logging
import shutil
import tempfile
from collections import defaultdict
from datetime import datetime
from pathlib import Path
from typing import List, Optional

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile
from pydantic import BaseModel
from sqlalchemy import or_
from sqlalchemy.orm import Session, joinedload

from backend.app.core.config import settings
from backend.app.crud import commessa as crud
from backend.app.db.session import get_db

_logger = logging.getLogger("stqc.commessa")

from backend.app.models.commessa import (
    Commessa, CommessaBulloneria, CommessaDocumento, CommessaRevisione, CommessaStatus, FaseOperativa, FaseStatus, Piece, PezzoPercorso, PezzoStato,
)
from backend.app.models.warehouse import DistintaImport, DistintaItem
from backend.app.schemas.commessa import CommessaCreate, CommessaRead, CommessaUpdate
from backend.app.services.distinta import (
    ALIASES,
    _build_col_map,
    _extract_rows,
    _find_header_row,
    normalized_to_db_bulk,
    parse_commessa_files,
)
from backend.app.services.bulloneria import parse_bulloneria_file
from backend.app.services.fasi_operative import parse_fasi_operative
from backend.app.services.commessa_analysis import classify_commessa_materials
from backend.app.services.qr import generate_qr_for_payload

router = APIRouter()


class PieceManualUpdate(BaseModel):
    tipo: Optional[str] = None
    profilo: Optional[str] = None
    qualita: Optional[str] = None
    assemblato: Optional[str] = None
    stato: Optional[str] = None
    nota: Optional[str] = None


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
        "qr_image_url": f"data:image/png;base64,{generate_qr_for_payload(item.qr_payload)}",
        "resolve_url": f"/p/{item.uuid}",
        "label_url": f"/api/v1/warehouse/distinta/items/{item.distinta_item_id}/label.pdf" if item.distinta_item_id else "#",
    }


def _piece_qr_code(part_number: str | None, instance_number: int | None, fallback_id: int | None = None) -> str:
    base = (part_number or "").strip()
    if not base:
        base = f"PEZZO-{fallback_id or 'SENZA-CODICE'}"
    if instance_number is not None:
        return f"{base}-{int(instance_number):03d}"
    return base


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
            "lista_pezzi": {"required": True, "status": "missing", "message": "Lista pezzi obbligatoria"},
            "assemblaggi": {"required": True, "status": "missing", "message": "Lista pezzi e assemblati obbligatoria"},
            "spedizione": {"required": False, "status": "missing", "message": "Non caricata · non bloccante"},
            "bulloneria": {"required": False, "status": "missing", "message": "Non caricata · opzionale"},
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
            result["files"]["lista_pezzi"] = {"required": True, "status": "pending", "message": "Validazione in corso"}
            try:
                lista_report = _validate_lista_pezzi_file(lista_dest)
                result["files"]["lista_pezzi"] = {
                    "required": True,
                    "status": "ok",
                    "message": f"OK · {lista_report.get('righe', 0)} posizioni · {lista_report.get('quantita', 0)} pezzi",
                }
            except Exception as exc:
                message = f"Lista pezzi non valida per questo riquadro: {exc}"
                result["files"]["lista_pezzi"] = {"required": True, "status": "error", "message": message}
                result["errors"].append(message)
        if assemblaggi is not None and assemblaggi.filename:
            suffix = Path(assemblaggi.filename).suffix.lower() or ".xls"
            asm_dest = tmp_dir / f"assemblaggi{suffix}"
            asm_dest.write_bytes(await assemblaggi.read())
            result["files"]["assemblaggi"] = {"required": True, "status": "pending", "message": "Validazione in corso"}
            try:
                asm_report = _validate_assemblaggi_file(asm_dest)
                result["files"]["assemblaggi"] = {
                    "required": True,
                    "status": "ok",
                    "message": f"OK · {asm_report.get('assemblati', 0)} assemblati · {asm_report.get('righe', 0)} righe pezzo",
                }
            except Exception as exc:
                message = f"Lista pezzi e assemblati non valida per questo riquadro: {exc}"
                result["files"]["assemblaggi"] = {"required": True, "status": "error", "message": message}
                result["errors"].append(message)

        mandatory_files_ok = (
            result["files"]["lista_pezzi"]["status"] == "ok"
            and result["files"]["assemblaggi"]["status"] == "ok"
        )
        if lista_dest is not None and asm_dest is not None and mandatory_files_ok:
            try:
                items_normalized, report = parse_commessa_files(lista_dest, asm_dest)
                result["files"]["lista_pezzi"] = {
                    "required": True,
                    "status": "ok",
                    "message": f"OK · {report.get('unique_parts', 0)} posizioni · {report.get('total_pieces', len(items_normalized))} pezzi",
                }
                result["files"]["assemblaggi"] = {
                    "required": True,
                    "status": "ok",
                    "message": f"OK · {report.get('assemblies', 0)} assemblati collegati",
                }
                result["summary"] = report.get("summary")
            except Exception as exc:
                message = f"File non importabile. Verifica file/parsing sui file obbligatori: {exc}"
                result["files"]["lista_pezzi"] = {"required": True, "status": "error", "message": "Parsing obbligatorio fallito"}
                result["files"]["assemblaggi"] = {"required": True, "status": "error", "message": "Parsing obbligatorio fallito"}
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
                message = f"Lista spedizione non interpretata: {exc}. Non bloccante."
                result["files"]["spedizione"] = {"required": False, "status": "warning", "message": message}
                result["warnings"].append(message)

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
                message = f"Bulloneria non interpretata: {exc}. Non bloccante."
                result["files"]["bulloneria"] = {"required": False, "status": "warning", "message": message}
                result["warnings"].append(message)

    result["can_upload"] = not result["errors"] and result["files"]["lista_pezzi"]["status"] == "ok" and result["files"]["assemblaggi"]["status"] == "ok"
    result["ok"] = result["can_upload"] and not result["warnings"]
    return result


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
    lista_pezzi: UploadFile = File(..., description="Lista pezzi / Lavorazioni per posizione"),
    assemblaggi: UploadFile = File(..., description="Lista pezzi e assemblati"),
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
    bulloneria_items: list[dict] = []

    try:
        lista_suffix = Path(lista_pezzi.filename or "lista_pezzi.xls").suffix.lower() or ".xls"
        lista_dest = rev_dir / f"lista_pezzi{lista_suffix}"
        with lista_dest.open("wb") as f:
            f.write(await lista_pezzi.read())

        asm_suffix = Path(assemblaggi.filename or "assemblaggi.xls").suffix.lower() or ".xls"
        asm_dest = rev_dir / f"assemblaggi{asm_suffix}"
        with asm_dest.open("wb") as f:
            f.write(await assemblaggi.read())

        items_normalized, report = parse_commessa_files(
            lista_dest,
            asm_dest,
        )
    except Exception as exc:
        shutil.rmtree(rev_dir, ignore_errors=True)
        _logger.exception("Errore nel parsing file obbligatori revisione %s commessa %d", codice_rev, commessa_id)
        raise HTTPException(
            422,
            f"File non importabile. Verifica file/parsing sui file obbligatori Lista pezzi e Assemblaggi: {exc}",
        )

    report.setdefault("file_warnings", [])
    if spedizione is not None and spedizione.filename:
        spedizione_suffix = Path(spedizione.filename or "spedizione.xls").suffix.lower() or ".xls"
        spedizione_dest = rev_dir / f"spedizione{spedizione_suffix}"
        with spedizione_dest.open("wb") as f:
            f.write(await spedizione.read())
        try:
            report["spedizione"] = _validate_spedizione_file(spedizione_dest)
        except Exception as exc:
            _logger.warning("Lista spedizione non validata per revisione %s commessa %d: %s", codice_rev, commessa_id, exc)
            report["spedizione"] = {"ok": False, "summary": str(exc)}
            report["file_warnings"].append({
                "file": "Lista spedizione",
                "level": "warning",
                "message": f"Lista spedizione non interpretata: {exc}. Analisi commessa proseguita.",
            })
    else:
        report["file_warnings"].append({
            "file": "Lista spedizione",
            "level": "warning",
            "message": "Lista spedizione non caricata. Analisi commessa proseguita.",
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
        file_assemblaggi=str(asm_dest.relative_to(settings.upload_dir.parent)),
        file_lavorazioni=str(lista_dest.relative_to(settings.upload_dir.parent)),
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
        filename=lista_pezzi.filename or f"{commessa.codice}_{codice_rev}",
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


def _validate_spedizione_file(path: Path) -> dict:
    rows = _extract_rows(path)
    nonempty = [
        [str(cell).strip() for cell in row if str(cell).strip()]
        for row in rows
        if any(str(cell).strip() for cell in row)
    ]
    if not nonempty:
        raise ValueError("nessuna riga leggibile trovata")
    header_idx = None
    for idx, row in enumerate(nonempty[:30]):
        normalized = {cell.lower() for cell in row}
        if any(cell in normalized for cell in {"assemb.", "assemb", "assemblato"}) and any("q.t" in cell or cell in {"qty", "quantita", "quantità"} for cell in normalized):
            header_idx = idx
            break
    if header_idx is None:
        raise ValueError("intestazione spedizione non riconosciuta")
    data_rows = [
        row for row in nonempty[header_idx + 1:]
        if row and row[0] and not row[0].lower().startswith("totale")
    ]
    if not data_rows:
        raise ValueError("nessuna riga spedizione valida trovata")
    return {
        "ok": True,
        "summary": f"Lista spedizione leggibile: {len(data_rows)} righe rilevate",
        "righe": len(data_rows),
    }


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

    pieces = db.query(Piece).filter(Piece.revisione_id == revisione.id).all()
    total = len(pieces)
    if total == 0:
        raise HTTPException(409, "La revisione non contiene pezzi fisici")

    item_ids = [piece.distinta_item_id for piece in pieces if piece.distinta_item_id]
    items_by_id = {
        item.id: item
        for item in db.query(DistintaItem).filter(DistintaItem.id.in_(item_ids)).all()
    } if item_ids else {}
    now = datetime.utcnow()
    for piece in pieces:
        piece.qr_payload = piece.uuid
        piece.qr_attivo = True
        piece.qr_status = "ACTIVE"
        piece.stato_attuale = "DA_PRODURRE"
        piece.updated_at = now
        item = items_by_id.get(piece.distinta_item_id)
        if item:
            item.qr_attivo = True
            item.stato_tracciamento = "DA_PRODURRE"
            item.qr_code = generate_qr_for_payload(piece.uuid)
    if revisione.step51_completed_at is None:
        revisione.step51_completed_at = now
    db.commit()
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

    query = db.query(Piece).filter(
        Piece.revisione_id == revisione.id,
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
        .options(joinedload(Piece.work_sessions))
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
        entered = bool(assembly_sessions) or _is_assembly_station(piece.ultima_postazione)
        completed = any(session.closed_at for session in assembly_sessions)
        if entered:
            row["pezzi_entrati"] += 1
        if completed:
            row["pezzi_completati"] += 1

        timestamps = [session.started_at for session in assembly_sessions if session.started_at]
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
