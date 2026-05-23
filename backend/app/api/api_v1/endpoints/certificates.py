import shutil
import uuid
from pathlib import Path
from typing import List

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile
from fastapi.responses import FileResponse
from sqlalchemy.orm import Session

from backend.app.core.config import settings
from backend.app.crud import warehouse as crud
from backend.app.db.session import get_db
from backend.app.models.warehouse import Certificate
from backend.app.schemas.warehouse import CertificateRead

router = APIRouter()

CERT_DIR = settings.upload_dir / "certificates"


def _ensure_cert_dir() -> Path:
    CERT_DIR.mkdir(parents=True, exist_ok=True)
    return CERT_DIR


@router.post("/{receipt_id}/certificates", response_model=CertificateRead, status_code=201)
async def upload_certificate(
    receipt_id: int,
    file: UploadFile = File(...),
    db: Session = Depends(get_db),
):
    receipt = crud.get_receipt(db=db, receipt_id=receipt_id)
    if receipt is None:
        raise HTTPException(status_code=404, detail="Ricezione non trovata")

    dest_dir = _ensure_cert_dir()
    ext = Path(file.filename).suffix
    stored_name = f"{uuid.uuid4().hex}{ext}"
    dest_path = dest_dir / stored_name

    with dest_path.open("wb") as out:
        shutil.copyfileobj(file.file, out)

    cert = Certificate(
        receipt_id=receipt_id,
        filename=file.filename,
        mime_type=file.content_type,
        storage_path=str(dest_path),
    )
    db.add(cert)
    db.commit()
    db.refresh(cert)
    return cert


@router.get("/{receipt_id}/certificates", response_model=List[CertificateRead])
def list_certificates(receipt_id: int, db: Session = Depends(get_db)):
    receipt = crud.get_receipt(db=db, receipt_id=receipt_id)
    if receipt is None:
        raise HTTPException(status_code=404, detail="Ricezione non trovata")
    return crud.get_certificates(db=db, receipt_id=receipt_id)


@router.get("/certificates/{cert_id}/download")
def download_certificate(cert_id: int, db: Session = Depends(get_db)):
    cert = crud.get_certificate(db=db, cert_id=cert_id)
    if cert is None:
        raise HTTPException(status_code=404, detail="Certificato non trovato")
    path = Path(cert.storage_path)
    if not path.exists():
        raise HTTPException(status_code=410, detail="File non più disponibile su disco")
    return FileResponse(path=path, filename=cert.filename, media_type=cert.mime_type or "application/octet-stream")
