from typing import List

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from backend.app.crud import commessa as crud
from backend.app.db.session import get_db
from backend.app.schemas.commessa import CommessaCreate, CommessaRead, CommessaUpdate

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
