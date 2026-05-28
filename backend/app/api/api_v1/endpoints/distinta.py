import os
from pathlib import Path
from tempfile import NamedTemporaryFile
from typing import List

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile
from fastapi.responses import Response
from sqlalchemy.orm import Session

from backend.app.crud.distinta import (
    create_distinta_import,
    create_distinta_item,
    get_distinta_import,
    get_distinta_imports,
    get_distinta_item,
)
from backend.app.db.session import get_db
from backend.app.schemas.distinta import DistintaImportRead
from backend.app.services.distinta import parse_distinta_file, parse_lista_parti
from backend.app.services.label import generate_label_pdf

router = APIRouter()

@router.post("/import", response_model=DistintaImportRead)
async def import_distinta_file(
    file: UploadFile = File(...),
    source_software: str | None = None,
    generate_qr: bool = False,
    db: Session = Depends(get_db),
):
    suffix = Path(file.filename).suffix or ".xlsx"
    with NamedTemporaryFile(delete=False, suffix=suffix) as tmp:
        tmp.write(await file.read())
        tmp_path = Path(tmp.name)

    try:
        # prova a parsare con il parser specifico per 'Lista parti assemblaggi'
        items = parse_lista_parti(tmp_path)
        # se il parser specifico non trova nulla, fallback al parser generico
        if not items:
            items = parse_distinta_file(tmp_path)
    except Exception as exc:
        raise HTTPException(status_code=400, detail=f"Impossibile leggere il file: {exc}")
    finally:
        try:
            os.remove(tmp_path)
        except OSError:
            pass

    import_data = {
        "filename": file.filename,
        "source_software": source_software,
        "total_items": len(items),
        "status": "IMPORTED" if items else "EMPTY",
    }
    distinta_import = create_distinta_import(db=db, obj_in=import_data)

    for item_data in items:
        create_distinta_item(db=db, obj_in={"import_id": distinta_import.id, **item_data})

    # mapping materiale <-> pezzo (sempre) e generazione QR (solo se richiesto)
    from backend.app.models.warehouse import DistintaItem, Material
    from backend.app.services.qr import generate_qr_for_uuid
    from sqlalchemy import select

    saved_items = db.scalars(select(DistintaItem).where(DistintaItem.import_id == distinta_import.id)).all()
    for si in saved_items:
        mapped_material = None
        if si.material_code:
            mapped_material = db.scalars(select(Material).where(Material.code == si.material_code)).first()
        if mapped_material:
            si.mapped_material_id = mapped_material.id
        if generate_qr:
            try:
                si.qr_code = generate_qr_for_uuid(si.uuid)
            except Exception:
                pass
    db.commit()

    distinta_import = get_distinta_import(db=db, import_id=distinta_import.id)
    if distinta_import is None:
        raise HTTPException(status_code=500, detail="Impossibile recuperare l'importazione dopo il salvataggio")
    return distinta_import

@router.get("/imports", response_model=List[DistintaImportRead])
def list_distinta_imports(skip: int = 0, limit: int = 50, db: Session = Depends(get_db)):
    return get_distinta_imports(db=db, skip=skip, limit=limit)


@router.get("/imports/{import_id}", response_model=DistintaImportRead)
def get_distinta_import_by_id(import_id: int, db: Session = Depends(get_db)):
    record = get_distinta_import(db=db, import_id=import_id)
    if record is None:
        raise HTTPException(status_code=404, detail="Importazione non trovata")
    return record


@router.post("/imports/{import_id}/generate-qr")
def generate_qr_for_import(
    import_id: int,
    commessa_id: int | None = None,
    db: Session = Depends(get_db),
):
    from sqlalchemy import select
    from backend.app.models.warehouse import DistintaItem
    from backend.app.services.qr import generate_qr_for_uuid

    record = get_distinta_import(db=db, import_id=import_id)
    if record is None:
        raise HTTPException(status_code=404, detail="Importazione non trovata")

    items = db.scalars(select(DistintaItem).where(DistintaItem.import_id == import_id)).all()

    count = 0
    failed: list[dict] = []
    for item in items:
        try:
            item.qr_code = generate_qr_for_uuid(item.uuid)
            if commessa_id:
                item.commessa_id = commessa_id
            count += 1
        except Exception as exc:
            failed.append({"item_id": item.id, "part_number": item.part_number, "error": str(exc)})

    db.commit()
    return {"qr_count": count, "import_id": import_id, "failed": failed}


@router.patch("/items/{item_id}")
def patch_distinta_item(item_id: int, body: dict, db: Session = Depends(get_db)):
    from backend.app.models.warehouse import DistintaItem
    item = db.get(DistintaItem, item_id)
    if item is None:
        raise HTTPException(status_code=404, detail="Pezzo non trovato")
    allowed = {"part_number", "description", "quantity", "material_code", "material_description", "commessa_reference", "length_mm", "parent_assembly", "instance_number"}
    for key, val in body.items():
        if key in allowed:
            setattr(item, key, val if val not in ("", None) else None)
    db.commit()
    db.refresh(item)
    return {"id": item.id, "part_number": item.part_number, "description": item.description}


@router.post("/imports/{import_id}/delta", status_code=201)
def delta_update_distinta(
    import_id: int,
    file: UploadFile = File(...),
    db: Session = Depends(get_db),
):
    # TODO: delta parser — update only the rows present in the file without full reimport
    raise HTTPException(status_code=501, detail="Delta parser non ancora implementato")


@router.get("/items/{item_id}/label.pdf")
def download_item_label(item_id: int, db: Session = Depends(get_db)):
    """Restituisce un PDF etichetta A6 per il pezzo indicato."""
    item = get_distinta_item(db=db, item_id=item_id)
    if item is None:
        raise HTTPException(status_code=404, detail="Pezzo non trovato")
    pdf_bytes = generate_label_pdf(item)
    filename = f"etichetta_{item.part_number or item_id}.pdf"
    return Response(
        content=pdf_bytes,
        media_type="application/pdf",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


@router.post("/bulk-qr-init")
def bulk_qr_init(db: Session = Depends(get_db)):
    """Genera UUID e QR per tutti i materials e batches del magazzino che ne sono privi.
    Da eseguire una sola volta al primo avvio dopo la migrazione."""
    import uuid as _uuid
    from sqlalchemy import select
    from backend.app.models.warehouse import Batch, Material
    from backend.app.services.qr import generate_qr_for_uuid

    mat_count = 0
    for mat in db.scalars(select(Material).where(Material.qr_uuid.is_(None))).all():
        mat.qr_uuid = str(_uuid.uuid4())
        try:
            mat.qr_code = generate_qr_for_uuid(mat.qr_uuid)
        except Exception:
            pass
        mat_count += 1

    batch_count = 0
    for batch in db.scalars(select(Batch).where(Batch.qr_uuid.is_(None))).all():
        batch.qr_uuid = str(_uuid.uuid4())
        try:
            batch.qr_code = generate_qr_for_uuid(batch.qr_uuid)
        except Exception:
            pass
        batch_count += 1

    db.commit()
    return {"materials_updated": mat_count, "batches_updated": batch_count}
