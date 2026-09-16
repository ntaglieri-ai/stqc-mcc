from __future__ import annotations

from typing import Any

from fastapi.encoders import jsonable_encoder
from sqlalchemy.orm import Session

from backend.app.models.user import User
from backend.app.models.warehouse import WarehouseChangeRequest, WarehouseChangeRequestStatus


def create_warehouse_change_request(
    db: Session,
    *,
    action: str,
    title: str,
    summary: str | None,
    payload: dict[str, Any],
    user: User | None = None,
) -> WarehouseChangeRequest:
    request = WarehouseChangeRequest(
        status=WarehouseChangeRequestStatus.PENDING,
        action=action,
        title=title,
        summary=summary,
        payload=jsonable_encoder(payload),
        created_by_user_id=user.id if user else None,
        created_by_username=user.username if user else None,
    )
    db.add(request)
    db.commit()
    db.refresh(request)
    return request
