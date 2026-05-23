from sqlalchemy import select
from sqlalchemy.orm import Session

from backend.app.models.warehouse import DistintaImport, DistintaItem
from typing import Any


def create_distinta_import(db: Session, obj_in: Any | dict) -> DistintaImport:
    data = obj_in.model_dump() if hasattr(obj_in, "model_dump") else obj_in
    distinta_import = DistintaImport(**data)
    db.add(distinta_import)
    db.commit()
    db.refresh(distinta_import)
    return distinta_import


def create_distinta_item(db: Session, obj_in: Any | dict) -> DistintaItem:
    data = obj_in.model_dump() if hasattr(obj_in, "model_dump") else obj_in
    # filter only columns that belong to DistintaItem
    valid_keys = set(c.name for c in DistintaItem.__table__.columns)
    filtered = {k: v for k, v in (data or {}).items() if k in valid_keys}
    distinta_item = DistintaItem(**filtered)
    db.add(distinta_item)
    db.commit()
    db.refresh(distinta_item)
    return distinta_item


def get_distinta_import(db: Session, import_id: int) -> DistintaImport | None:
    return db.get(DistintaImport, import_id)


def get_distinta_imports(db: Session, skip: int = 0, limit: int = 50) -> list[DistintaImport]:
    return db.scalars(select(DistintaImport).offset(skip).limit(limit)).all()


def get_distinta_item(db: Session, item_id: int) -> DistintaItem | None:
    return db.get(DistintaItem, item_id)
