import logging
import shutil
import tempfile
from collections import defaultdict
from pathlib import Path
from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException, UploadFile, File
from pydantic import BaseModel
from sqlalchemy import or_
from sqlalchemy.orm import Session

from backend.app.core.config import settings
from backend.app.crud import commessa as crud
from backend.app.db.session import get_db

_logger = logging.getLogger("stqc.commessa")

from backend.app.models.commessa import (
    CommessaRevisione, CommessaStatus, FaseOperativa, FaseStatus, PezzoPercorso, PezzoStato,
)
from backend.app.models.user import ProfiloUtente, User, UserAttributes
from backend.app.models.warehouse import DistintaImport, DistintaItem
from backend.app.schemas.commessa import CommessaCreate, CommessaRead, CommessaUpdate
from backend.app.services.distinta import (
    load_prefixes_from_db,
    normalized_to_db_bulk,
    parse_two_files,
)
from backend.app.services.fasi_operative import parse_fasi_operative
from backend.app.services.qr import generate_qr_for_uuid

router = APIRouter()


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
    return crud.update_commessa(db=db, commessa=commessa, obj_in=commessa_in)


@router.delete("/{commessa_id}", status_code=204)
def delete_commessa(commessa_id: int, db: Session = Depends(get_db)):
    commessa = crud.get_commessa(db=db, commessa_id=commessa_id)
    if commessa is None:
        raise HTTPException(status_code=404, detail="Commessa non trovata")
    crud.delete_commessa(db=db, commessa=commessa)


# ── Revisioni distinta ────────────────────────────────────────────────────────

@router.post("/{commessa_id}/revisioni", status_code=201)
async def upload_revisione(
    commessa_id: int,
    assemblaggi: UploadFile = File(..., description="Lista parti assemblaggi (.xls/.xlsx)"),
    lavorazioni: UploadFile = File(..., description="Lavorazioni per posizione (.xls/.xlsx)"),
    note: Optional[str] = None,
    db: Session = Depends(get_db),
):
    """Carica due file Tekla, salva gli originali su disco, esegue il parser unificato
    e crea i record DistintaItem con UUID e QR per ogni pezzo fisico."""
    commessa = crud.get_commessa(db=db, commessa_id=commessa_id)
    if commessa is None:
        raise HTTPException(404, "Commessa non trovata")

    # Calcola codice revisione (r01, r02, …)
    existing = db.query(CommessaRevisione).filter(
        CommessaRevisione.commessa_id == commessa_id
    ).count()
    codice_rev = f"r{existing + 1:02d}"

    # Crea la directory di destinazione
    rev_dir = settings.upload_dir / f"commessa_{commessa_id}" / codice_rev
    rev_dir.mkdir(parents=True, exist_ok=True)

    asm_suffix = Path(assemblaggi.filename or "assemblaggi.xls").suffix or ".xls"
    lav_suffix = Path(lavorazioni.filename or "lavorazioni.xls").suffix or ".xls"
    asm_dest = rev_dir / f"assemblaggi{asm_suffix}"
    lav_dest = rev_dir / f"lavorazioni{lav_suffix}"

    # Salva i file originali (mai lavorare sul file uploadato direttamente)
    with asm_dest.open("wb") as f:
        f.write(await assemblaggi.read())
    with lav_dest.open("wb") as f:
        f.write(await lavorazioni.read())

    # Carica i tipi profilo dal DB per la classificazione
    prefixes = load_prefixes_from_db(db)

    # Parser su copie su disco
    try:
        items_normalized, report = parse_two_files(asm_dest, lav_dest, prefixes=prefixes)
    except Exception as exc:
        _logger.exception("Errore nel parsing revisione %s commessa %d", codice_rev, commessa_id)
        raise HTTPException(422, f"Errore parser: {exc}")

    # Crea record CommessaRevisione
    revisione = CommessaRevisione(
        commessa_id=commessa_id,
        codice=codice_rev,
        file_assemblaggi=str(asm_dest.relative_to(settings.upload_dir.parent)),
        file_lavorazioni=str(lav_dest.relative_to(settings.upload_dir.parent)),
        note=note,
    )
    db.add(revisione)
    db.flush()  # ottieni l'id prima del commit

    # Crea un DistintaImport "ombra" per backward compat con la UI esistente
    distinta_import = DistintaImport(
        filename=f"{commessa.codice}_{codice_rev}",
        source_software="Tekla",
        total_items=len(items_normalized),
        status="IMPORTED" if items_normalized else "EMPTY",
    )
    db.add(distinta_import)
    db.flush()

    # Crea i DistintaItem — uno per pezzo fisico
    db_items = normalized_to_db_bulk(items_normalized)
    for item_data in db_items:
        di = DistintaItem(
            import_id=distinta_import.id,
            revisione_id=revisione.id,
            commessa_id=commessa_id,
            **{k: v for k, v in item_data.items()
               if k in {c.name for c in DistintaItem.__table__.columns} - {"id", "uuid", "qr_code"}},
        )
        # Genera QR con UUID interno
        try:
            di.qr_code = generate_qr_for_uuid(di.uuid)
        except Exception:
            pass
        db.add(di)

    db.commit()

    return {
        "revisione_id":  revisione.id,
        "codice":        codice_rev,
        "import_id":     distinta_import.id,
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
            "file_lavorazioni": r.file_lavorazioni,
            "note":            r.note,
            "imported_at":     r.imported_at,
            "n_items":         db.query(DistintaItem).filter(DistintaItem.revisione_id == r.id).count(),
        }
        for r in revs
    ]


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

    # ── 6. Sblocca commesse_visibili per operatori delle prime fasi ───────────
    first_postazioni: set = set()
    for marca_pos, fase_list in by_marca.items():
        first_fase = min(fase_list, key=lambda f: (f.sequenza if f.sequenza is not None else 9999, f.id))
        if first_fase.postazione:
            first_postazioni.add(first_fase.postazione)

    _logger.info("[avvia] prime postazioni: %s", sorted(first_postazioni))
    unlocked_count = 0
    if first_postazioni:
        operatori = (
            db.query(User)
            .filter(User.profilo == ProfiloUtente.OPERATORE, User.attivo == True)
            .all()
        )
        for op in operatori:
            attrs = db.query(UserAttributes).filter(UserAttributes.user_id == op.id).first()
            if not attrs or not attrs.postazioni_assegnate:
                continue
            if any(p in first_postazioni for p in attrs.postazioni_assegnate):
                cv = attrs.commesse_visibili
                if cv == "all":
                    continue
                if not isinstance(cv, list):
                    cv = []
                if commessa_id not in cv:
                    attrs.commesse_visibili = cv + [commessa_id]
                    unlocked_count += 1

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
