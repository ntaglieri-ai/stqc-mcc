"""Disabled warehouse/commessa link endpoints.

The warehouse is intentionally isolated from commesse until the new step 5.2
link workflow is designed and implemented.
"""
from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException

router = APIRouter()


def _link_disabled() -> None:
    raise HTTPException(
        status_code=410,
        detail=(
            "Funzione sospesa: il magazzino e le commesse sono separati. "
            "Il collegamento operativo sarà reintrodotto nello step 5.2."
        ),
    )


@router.post("/reservations", status_code=410)
def create_reservation(_: dict[str, Any] | None = None):
    _link_disabled()


@router.post("/analyze", status_code=410)
def analyze_distinta(_: dict[str, Any] | None = None):
    _link_disabled()


@router.post("/compare-distinta", status_code=410)
def compare_distinta_magazzino(_: dict[str, Any] | None = None):
    _link_disabled()


@router.post("/requests", status_code=410)
def create_request(_: dict[str, Any] | None = None):
    _link_disabled()


@router.get("/requests", status_code=410)
def list_requests():
    _link_disabled()


@router.post("/requests/{req_id}/confirm", status_code=410)
def confirm_request(req_id: int):
    _link_disabled()


@router.post("/requests/{req_id}/refuse", status_code=410)
def refuse_request(req_id: int, _: dict[str, Any] | None = None):
    _link_disabled()


@router.delete("/requests/{req_id}", status_code=410)
def delete_request(req_id: int):
    _link_disabled()
