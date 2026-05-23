from datetime import datetime
from enum import Enum

from sqlalchemy import Column, Date, DateTime, Enum as SQLEnum, Integer, String, Text
from sqlalchemy.orm import relationship

from backend.app.db.base import Base


class CommessaStatus(str, Enum):
    APERTA = "APERTA"
    SOSPESA = "SOSPESA"
    CHIUSA = "CHIUSA"


class Commessa(Base):
    __tablename__ = "commesse"

    id = Column(Integer, primary_key=True, index=True)
    codice = Column(String(100), nullable=False, unique=True, index=True)
    cliente = Column(String(200), nullable=True)
    descrizione = Column(String(500), nullable=True)
    data_inizio = Column(Date, nullable=True)
    data_consegna_prevista = Column(Date, nullable=True)
    status = Column(SQLEnum(CommessaStatus), nullable=False, default=CommessaStatus.APERTA)
    notes = Column(Text, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)
