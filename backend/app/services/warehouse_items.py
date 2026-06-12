"""Gestione dell'identità dei singoli elementi fisici di magazzino."""
from __future__ import annotations

from datetime import datetime

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from backend.app.models.warehouse import Material, WarehouseItem


def _whole_quantity(value: float, field: str = "quantity") -> int:
    number = float(value)
    rounded = round(number)
    if number <= 0 or abs(number - rounded) > 1e-9:
        raise ValueError(f"{field} deve essere un numero intero positivo")
    return int(rounded)


def create_items_for_incoming(
    db: Session,
    material_id: int,
    quantity: float,
    movement_id: int | None = None,
) -> list[WarehouseItem]:
    count = _whole_quantity(quantity)
    last_ordinal = db.scalar(
        select(func.coalesce(func.max(WarehouseItem.ordinal), 0))
        .where(WarehouseItem.material_id == material_id)
    ) or 0
    items = [
        WarehouseItem(
            material_id=material_id,
            ordinal=last_ordinal + index,
            status="AVAILABLE",
            source_movement_id=movement_id,
        )
        for index in range(1, count + 1)
    ]
    db.add_all(items)
    return items


def close_items_for_outgoing(
    db: Session,
    material_id: int,
    quantity: float,
    movement_id: int | None = None,
) -> list[WarehouseItem]:
    count = _whole_quantity(quantity)
    items = db.scalars(
        select(WarehouseItem)
        .where(
            WarehouseItem.material_id == material_id,
            WarehouseItem.status == "AVAILABLE",
        )
        .order_by(WarehouseItem.ordinal)
        .limit(count)
    ).all()
    if len(items) != count:
        raise ValueError(
            f"Elementi fisici disponibili insufficienti: richiesti {count}, disponibili {len(items)}"
        )
    now = datetime.utcnow()
    for item in items:
        item.status = "OUT"
        item.exit_movement_id = movement_id
        item.exited_at = now
    return items


def reconcile_available_items(
    db: Session,
    material: Material,
    target_quantity: float,
) -> dict:
    target = max(0, int(float(target_quantity or 0)))
    available = db.scalars(
        select(WarehouseItem)
        .where(
            WarehouseItem.material_id == material.id,
            WarehouseItem.status == "AVAILABLE",
        )
        .order_by(WarehouseItem.ordinal)
    ).all()
    created = 0
    closed = 0
    if len(available) < target:
        created = target - len(available)
        create_items_for_incoming(db, material.id, created)
    elif len(available) > target:
        closed = len(available) - target
        now = datetime.utcnow()
        for item in reversed(available[-closed:]):
            item.status = "RECONCILED_OUT"
            item.exited_at = now
    return {"created": created, "closed": closed}
