from sqlalchemy import select
from sqlalchemy.orm import Session

from backend.app.models.commessa import Commessa
from backend.app.schemas.commessa import CommessaCreate, CommessaUpdate


def create_commessa(db: Session, obj_in: CommessaCreate) -> Commessa:
    commessa = Commessa(**obj_in.model_dump())
    db.add(commessa)
    db.commit()
    db.refresh(commessa)
    return commessa


def get_commessa(db: Session, commessa_id: int) -> Commessa | None:
    return db.get(Commessa, commessa_id)


def get_commessa_by_codice(db: Session, codice: str) -> Commessa | None:
    return db.scalars(select(Commessa).where(Commessa.codice == codice)).first()


def get_commesse(
    db: Session,
    skip: int = 0,
    limit: int = 100,
    status: str | None = None,
    q: str | None = None,
) -> list[Commessa]:
    stmt = select(Commessa)
    if status:
        stmt = stmt.where(Commessa.status == status)
    if q:
        stmt = stmt.where(
            Commessa.codice.ilike(f"%{q}%") | Commessa.cliente.ilike(f"%{q}%")
        )
    return db.scalars(stmt.order_by(Commessa.codice).offset(skip).limit(limit)).all()


def update_commessa(db: Session, commessa: Commessa, obj_in: CommessaUpdate) -> Commessa:
    for field, value in obj_in.model_dump(exclude_unset=True).items():
        setattr(commessa, field, value)
    db.commit()
    db.refresh(commessa)
    return commessa


def delete_commessa(db: Session, commessa: Commessa) -> None:
    db.delete(commessa)
    db.commit()
