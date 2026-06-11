from datetime import datetime
from enum import Enum

from sqlalchemy import Boolean, Column, Date, DateTime, Enum as SQLEnum, ForeignKey, Integer, JSON, Numeric, String, Text, UniqueConstraint
from sqlalchemy.orm import relationship

from backend.app.db.base import Base


class CommessaStatus(str, Enum):
    APERTA        = "APERTA"
    IN_PRODUZIONE = "IN_PRODUZIONE"
    SOSPESA       = "SOSPESA"
    CHIUSA        = "CHIUSA"


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

    fasi      = relationship("FaseOperativa", back_populates="commessa", cascade="all, delete-orphan", passive_deletes=True)
    revisioni = relationship("CommessaRevisione", back_populates="commessa", cascade="all, delete-orphan", passive_deletes=True, order_by="CommessaRevisione.id")


class CommessaRevisione(Base):
    """Una revisione della distinta (r01, r02, …) con i file originali salvati su disco."""
    __tablename__ = "commessa_revisioni"
    __table_args__ = (UniqueConstraint("commessa_id", "codice", name="uq_commessa_revisione"),)

    id               = Column(Integer, primary_key=True, index=True)
    commessa_id      = Column(Integer, ForeignKey("commesse.id", ondelete="CASCADE"), nullable=False, index=True)
    codice           = Column(String(20), nullable=False)       # r01, r02, …
    file_assemblaggi = Column(String(500), nullable=True)       # path relativo su disco
    file_lavorazioni = Column(String(500), nullable=True)       # lista pezzi / lavorazioni per posizione
    predistinta      = Column(Boolean, nullable=False, default=False)
    stato_analisi    = Column(String(30), nullable=False, default="PRONTA")
    report_analisi   = Column(JSON, nullable=True)
    note             = Column(Text, nullable=True)
    imported_at      = Column(DateTime, default=datetime.utcnow)

    commessa = relationship("Commessa", back_populates="revisioni")
    items    = relationship("DistintaItem", back_populates="revisione", cascade="all, delete-orphan", passive_deletes=True)
    documenti = relationship("CommessaDocumento", back_populates="revisione", cascade="all, delete-orphan", passive_deletes=True)


class CommessaDocumento(Base):
    """Allegato originale caricato insieme a una revisione della commessa."""
    __tablename__ = "commessa_documenti"

    id           = Column(Integer, primary_key=True, index=True)
    commessa_id  = Column(Integer, ForeignKey("commesse.id", ondelete="CASCADE"), nullable=False, index=True)
    revisione_id = Column(Integer, ForeignKey("commessa_revisioni.id", ondelete="CASCADE"), nullable=False, index=True)
    categoria    = Column(String(50), nullable=False, default="DISEGNO")
    filename     = Column(String(255), nullable=False)
    storage_path = Column(String(500), nullable=False)
    mime_type    = Column(String(150), nullable=True)
    uploaded_at  = Column(DateTime, default=datetime.utcnow)

    revisione = relationship("CommessaRevisione", back_populates="documenti")


class FaseStatus(str, Enum):
    DA_INIZIARE = "DA_INIZIARE"
    IN_CORSO = "IN_CORSO"
    COMPLETATA = "COMPLETATA"


class FaseOperativa(Base):
    __tablename__ = "fasi_operative"

    id = Column(Integer, primary_key=True, index=True)
    commessa_id = Column(Integer, ForeignKey("commesse.id", ondelete="CASCADE"), nullable=False, index=True)
    marca_pos = Column(String(100), nullable=True)
    profilo = Column(String(200), nullable=True)
    quantita = Column(Numeric(12, 3), nullable=True)
    fase = Column(String(200), nullable=True)
    postazione = Column(String(100), nullable=True)
    tempo_prev_minpz = Column(Numeric(10, 2), nullable=True)
    tempo_tot_min = Column(Numeric(10, 2), nullable=True)
    sequenza = Column(Integer, nullable=True)
    dipende_da = Column(String(200), nullable=True)
    note_operative = Column(Text, nullable=True)
    status = Column(
        SQLEnum(FaseStatus, values_callable=lambda x: [e.value for e in x]),
        nullable=False,
        default=FaseStatus.DA_INIZIARE,
    )
    created_at = Column(DateTime, default=datetime.utcnow)

    commessa = relationship("Commessa", back_populates="fasi")


class PezzoStato(str, Enum):
    BLOCCATA   = "BLOCCATA"    # fase non ancora raggiungibile
    SBLOCCATA  = "SBLOCCATA"   # prima fase disponibile, pronta per iniziare
    IN_CORSO   = "IN_CORSO"
    COMPLETATA = "COMPLETATA"


class PezzoPercorso(Base):
    """Tracking per-item × per-fase: uno row per ogni (pezzo, fase) della commessa."""
    __tablename__ = "pezzo_percorso"
    __table_args__ = (UniqueConstraint("commessa_id", "marca_pos", "fase_id", name="uq_pezzo_percorso"),)

    id              = Column(Integer, primary_key=True, index=True)
    commessa_id     = Column(Integer, ForeignKey("commesse.id", ondelete="CASCADE"), nullable=False, index=True)
    item_id         = Column(Integer, ForeignKey("distinta_items.id", ondelete="SET NULL"), nullable=True, index=True)
    fase_id         = Column(Integer, ForeignKey("fasi_operative.id", ondelete="CASCADE"), nullable=False, index=True)
    marca_pos       = Column(String(100), nullable=False)
    instance_number = Column(Integer, nullable=True)   # numero istanza fisica del pezzo
    sequenza        = Column(Integer, nullable=True)
    stato           = Column(String(20), nullable=False, default=PezzoStato.BLOCCATA)
    postazione      = Column(String(100), nullable=True)
