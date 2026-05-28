from datetime import date, datetime
from enum import Enum
from typing import Optional

from pydantic import BaseModel, Field


class CommessaStatus(str, Enum):
    APERTA        = "APERTA"
    IN_PRODUZIONE = "IN_PRODUZIONE"
    SOSPESA       = "SOSPESA"
    CHIUSA        = "CHIUSA"


class CommessaBase(BaseModel):
    codice: str = Field(..., example="COMM-2026-001")
    cliente: Optional[str] = Field(None, example="MCC Srl")
    descrizione: Optional[str] = Field(None, example="Struttura acciaio capannone")
    data_inizio: Optional[date] = None
    data_consegna_prevista: Optional[date] = None
    status: CommessaStatus = CommessaStatus.APERTA
    notes: Optional[str] = None


class CommessaCreate(CommessaBase):
    pass


class CommessaUpdate(BaseModel):
    cliente: Optional[str] = None
    descrizione: Optional[str] = None
    data_inizio: Optional[date] = None
    data_consegna_prevista: Optional[date] = None
    status: Optional[CommessaStatus] = None
    notes: Optional[str] = None


class CommessaRead(CommessaBase):
    id: int
    created_at: datetime

    class Config:
        from_attributes = True
