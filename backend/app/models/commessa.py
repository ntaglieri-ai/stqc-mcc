import uuid as _uuid
from datetime import datetime
from enum import Enum

from sqlalchemy import Boolean, Column, Date, DateTime, Enum as SQLEnum, ForeignKey, Integer, JSON, Numeric, String, Text, UniqueConstraint
from sqlalchemy.orm import relationship

from backend.app.db.base import Base


def _gen_uuid() -> str:
    return str(_uuid.uuid4())


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
    corrente         = Column(Boolean, nullable=False, default=True, index=True)
    stato_analisi    = Column(String(30), nullable=False, default="PRONTA")
    report_analisi   = Column(JSON, nullable=True)
    step4_completed_at = Column(DateTime, nullable=True)
    step51_completed_at = Column(DateTime, nullable=True)
    note             = Column(Text, nullable=True)
    imported_at      = Column(DateTime, default=datetime.utcnow)

    commessa = relationship("Commessa", back_populates="revisioni")
    items    = relationship("DistintaItem", back_populates="revisione", cascade="all, delete-orphan", passive_deletes=True)
    documenti = relationship("CommessaDocumento", back_populates="revisione", cascade="all, delete-orphan", passive_deletes=True)
    pieces = relationship("Piece", back_populates="revisione", cascade="all, delete-orphan", passive_deletes=True)


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


class Piece(Base):
    """Pezzo fisico tracciabile generato dall'analisi commessa."""
    __tablename__ = "pieces"
    __table_args__ = (
        UniqueConstraint("revisione_id", "qr_code", name="uq_piece_revision_qr_code"),
        UniqueConstraint("distinta_item_id", name="uq_piece_distinta_item"),
    )

    id = Column(Integer, primary_key=True, index=True)
    uuid = Column(String(36), nullable=False, default=_gen_uuid, unique=True, index=True)
    qr_code = Column(String(220), nullable=False, index=True)
    qr_payload = Column(String(220), nullable=False)
    qr_status = Column(String(20), nullable=False, default="DRAFT", index=True)

    commessa_id = Column(Integer, ForeignKey("commesse.id", ondelete="CASCADE"), nullable=False, index=True)
    revisione_id = Column(Integer, ForeignKey("commessa_revisioni.id", ondelete="CASCADE"), nullable=False, index=True)
    distinta_item_id = Column(Integer, ForeignKey("distinta_items.id", ondelete="SET NULL"), nullable=True, index=True)

    assemblato_id = Column(String(200), nullable=True, index=True)
    marca_pos = Column(String(200), nullable=False, index=True)
    progressivo = Column(Integer, nullable=False)

    profilo = Column(String(400), nullable=True)
    materiale = Column(String(100), nullable=True)
    materiale_descrizione = Column(String(400), nullable=True)
    lunghezza_mm = Column(Numeric(12, 2), nullable=True)
    larghezza_mm = Column(Numeric(12, 2), nullable=True)
    spessore_mm = Column(Numeric(12, 2), nullable=True)
    peso_kg = Column(Numeric(12, 4), nullable=True)
    tipo_profilo = Column(String(100), nullable=True)

    materiale_origine_status = Column(String(20), nullable=False, default="VUOTO", index=True)
    colata = Column(String(100), nullable=True)
    lotto = Column(String(100), nullable=True)
    certificato_31 = Column(String(255), nullable=True)
    materiale_origine_id = Column(Integer, nullable=True)
    fornitore = Column(String(200), nullable=True)
    note_materiale = Column(Text, nullable=True)

    stato_attuale = Column(String(30), nullable=False, default="NON_GENERATO", index=True)
    ultima_postazione = Column(String(100), nullable=True)
    ultimo_lavoro = Column(String(100), nullable=True)
    ultimo_evento = Column(String(30), nullable=True)
    ultimo_evento_at = Column(DateTime, nullable=True, index=True)
    lavorazione_aperta_id = Column(Integer, nullable=True, index=True)
    qr_attivo = Column(Boolean, nullable=False, default=False, index=True)
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow)

    revisione = relationship("CommessaRevisione", back_populates="pieces")
    scan_events = relationship("PieceScanEvent", back_populates="piece", cascade="all, delete-orphan", passive_deletes=True, order_by="PieceScanEvent.timestamp")
    work_sessions = relationship("PieceWorkSession", back_populates="piece", cascade="all, delete-orphan", passive_deletes=True, order_by="PieceWorkSession.started_at")


class Workstation(Base):
    """Postazione fisica o logica scansionabile in officina."""
    __tablename__ = "workstations"

    id = Column(Integer, primary_key=True, index=True)
    code = Column(String(80), nullable=False, unique=True, index=True)
    name = Column(String(160), nullable=False)
    description = Column(Text, nullable=True)
    active = Column(Boolean, nullable=False, default=True, index=True)
    start_qr_code = Column(String(120), nullable=False, unique=True, index=True)
    end_qr_code = Column(String(120), nullable=False, unique=True, index=True)
    created_at = Column(DateTime, default=datetime.utcnow)

    scanner_devices = relationship("ScannerDevice", back_populates="postazione")


class ScannerDevice(Base):
    """Scanner fisico associabile a una postazione configurabile."""
    __tablename__ = "scanner_devices"

    id = Column(Integer, primary_key=True, index=True)
    scanner_code = Column(String(80), nullable=False, unique=True, index=True)
    name = Column(String(160), nullable=False)
    description = Column(Text, nullable=True)
    postazione_id = Column(Integer, ForeignKey("workstations.id", ondelete="SET NULL"), nullable=True, index=True)
    ip_address = Column(String(80), nullable=True, index=True)
    serial_number = Column(String(120), nullable=True, index=True)
    device_token = Column(String(160), nullable=True, unique=True, index=True)
    active = Column(Boolean, nullable=False, default=True, index=True)
    last_seen_at = Column(DateTime, nullable=True, index=True)
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow)

    postazione = relationship("Workstation", back_populates="scanner_devices")


class WorkType(Base):
    """Tipo lavoro registrabile su una postazione, senza imporre percorsi teorici."""
    __tablename__ = "work_types"

    id = Column(Integer, primary_key=True, index=True)
    code = Column(String(80), nullable=False, unique=True, index=True)
    name = Column(String(160), nullable=False)
    category = Column(String(100), nullable=True, index=True)
    active = Column(Boolean, nullable=False, default=True, index=True)
    created_at = Column(DateTime, default=datetime.utcnow)


class PieceScanEvent(Base):
    """Log append-only degli scan e degli eventi operativi del singolo pezzo."""
    __tablename__ = "piece_scan_events"

    id = Column(Integer, primary_key=True, index=True)
    piece_id = Column(Integer, ForeignKey("pieces.id", ondelete="CASCADE"), nullable=False, index=True)
    qr_code = Column(String(220), nullable=False, index=True)
    commessa_id = Column(Integer, ForeignKey("commesse.id", ondelete="CASCADE"), nullable=False, index=True)
    revisione_id = Column(Integer, ForeignKey("commessa_revisioni.id", ondelete="CASCADE"), nullable=False, index=True)
    assemblato_id = Column(String(200), nullable=True, index=True)

    postazione_id = Column(Integer, ForeignKey("workstations.id", ondelete="SET NULL"), nullable=True, index=True)
    postazione_code = Column(String(80), nullable=True, index=True)
    lavoro_id = Column(Integer, ForeignKey("work_types.id", ondelete="SET NULL"), nullable=True, index=True)
    lavoro_code = Column(String(80), nullable=True, index=True)

    event_type = Column(String(40), nullable=False, index=True)
    timestamp = Column(DateTime, nullable=False, default=datetime.utcnow, index=True)
    operatore_id = Column(Integer, ForeignKey("users.id", ondelete="SET NULL"), nullable=True, index=True)
    session_id = Column(Integer, ForeignKey("piece_work_sessions.id", ondelete="SET NULL"), nullable=True, index=True)
    metadata_json = Column(JSON, nullable=True)
    note = Column(Text, nullable=True)

    piece = relationship("Piece", back_populates="scan_events")


class PieceWorkSession(Base):
    """Sessione lavoro aperta/chiusa su un pezzo, con timer operativo a 24h."""
    __tablename__ = "piece_work_sessions"

    id = Column(Integer, primary_key=True, index=True)
    piece_id = Column(Integer, ForeignKey("pieces.id", ondelete="CASCADE"), nullable=False, index=True)
    commessa_id = Column(Integer, ForeignKey("commesse.id", ondelete="CASCADE"), nullable=False, index=True)
    revisione_id = Column(Integer, ForeignKey("commessa_revisioni.id", ondelete="CASCADE"), nullable=False, index=True)
    assemblato_id = Column(String(200), nullable=True, index=True)

    postazione_id = Column(Integer, ForeignKey("workstations.id", ondelete="SET NULL"), nullable=True, index=True)
    postazione_code = Column(String(80), nullable=False, index=True)
    lavoro_id = Column(Integer, ForeignKey("work_types.id", ondelete="SET NULL"), nullable=True, index=True)
    lavoro_code = Column(String(80), nullable=True, index=True)

    started_at = Column(DateTime, nullable=False, default=datetime.utcnow, index=True)
    expected_close_at = Column(DateTime, nullable=False, index=True)
    closed_at = Column(DateTime, nullable=True, index=True)
    duration_seconds = Column(Integer, nullable=True)
    status = Column(String(30), nullable=False, default="OPEN", index=True)
    opened_by_id = Column(Integer, ForeignKey("users.id", ondelete="SET NULL"), nullable=True, index=True)
    closed_by_id = Column(Integer, ForeignKey("users.id", ondelete="SET NULL"), nullable=True, index=True)
    open_event_id = Column(Integer, nullable=True, index=True)
    close_event_id = Column(Integer, nullable=True, index=True)
    note = Column(Text, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow)

    piece = relationship("Piece", back_populates="work_sessions")


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
    __table_args__ = (UniqueConstraint("commessa_id", "marca_pos", "instance_number", "fase_id", name="uq_pezzo_percorso"),)

    id              = Column(Integer, primary_key=True, index=True)
    commessa_id     = Column(Integer, ForeignKey("commesse.id", ondelete="CASCADE"), nullable=False, index=True)
    item_id         = Column(Integer, ForeignKey("distinta_items.id", ondelete="SET NULL"), nullable=True, index=True)
    fase_id         = Column(Integer, ForeignKey("fasi_operative.id", ondelete="CASCADE"), nullable=False, index=True)
    marca_pos       = Column(String(100), nullable=False)
    instance_number = Column(Integer, nullable=True)   # numero istanza fisica del pezzo
    sequenza        = Column(Integer, nullable=True)
    stato           = Column(String(20), nullable=False, default=PezzoStato.BLOCCATA)
    postazione      = Column(String(100), nullable=True)
