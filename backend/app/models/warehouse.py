from datetime import datetime
from enum import Enum

from sqlalchemy import (
    Column,
    Date,
    DateTime,
    Enum as SQLEnum,
    ForeignKey,
    Integer,
    Numeric,
    String,
    Text,
)
from sqlalchemy.orm import relationship

from backend.app.db.base import Base


class MovementType(str, Enum):
    INCOMING = "INCOMING"
    OUTGOING = "OUTGOING"
    ADJUSTMENT = "ADJUSTMENT"
    SFRIDO = "SFRIDO"


class Supplier(Base):
    __tablename__ = "suppliers"

    id = Column(Integer, primary_key=True, index=True)
    name = Column(String(200), nullable=False)
    tax_id = Column(String(50), nullable=True)
    address = Column(String(400), nullable=True)
    contacts = Column(String(400), nullable=True)

    receipts = relationship("Receipt", back_populates="supplier")


class Material(Base):
    __tablename__ = "materials"

    id = Column(Integer, primary_key=True, index=True)
    code = Column(String(100), nullable=False, unique=True, index=True)
    description = Column(String(400), nullable=False)
    unit = Column(String(20), nullable=False, default="PZ")
    specification = Column(String(400), nullable=True)

    # Campi strutturati (da inventario Excel)
    tipo = Column(String(100), nullable=True)
    profilo = Column(String(200), nullable=True)
    dimensioni = Column(String(200), nullable=True)
    qualita = Column(String(100), nullable=True)
    colata = Column(String(100), nullable=True)
    commessa_ref = Column(String(200), nullable=True)
    peso_u_kg = Column(Numeric(12, 4), nullable=True)
    peso_1_pz = Column(Numeric(12, 4), nullable=True)

    # Campi gestione stock avanzata
    unita_misura = Column(String(10), nullable=False, server_default="pz")
    dimensione_2 = Column(Numeric(12, 2), nullable=True)
    quantita_prenotata = Column(Numeric(18, 6), nullable=False, server_default="0")
    quantita_uscita = Column(Numeric(18, 6), nullable=False, server_default="0")

    batches = relationship("Batch", back_populates="material")
    receipts = relationship("Receipt", back_populates="material")
    movements = relationship("StockMovement", back_populates="material")
    cutting_plans = relationship("CuttingPlan", back_populates="material")
    stock_reservations = relationship("StockReservation", back_populates="material")


class Batch(Base):
    __tablename__ = "batches"

    id = Column(Integer, primary_key=True, index=True)
    batch_number = Column(String(200), nullable=False, index=True)
    material_id = Column(Integer, ForeignKey("materials.id"), nullable=False)
    heat_number = Column(String(200), nullable=True)
    produced_date = Column(Date, nullable=True)
    notes = Column(Text, nullable=True)

    material = relationship("Material", back_populates="batches")
    receipts = relationship("Receipt", back_populates="batch")
    movements = relationship("StockMovement", back_populates="batch")


class Receipt(Base):
    __tablename__ = "receipts"

    id = Column(Integer, primary_key=True, index=True)
    ddt_number = Column(String(120), nullable=False, index=True)
    ddt_date = Column(Date, nullable=False)
    supplier_id = Column(Integer, ForeignKey("suppliers.id"), nullable=False)
    material_id = Column(Integer, ForeignKey("materials.id"), nullable=False)
    batch_id = Column(Integer, ForeignKey("batches.id"), nullable=True)
    quantity = Column(Numeric(18, 6), nullable=False)
    unit = Column(String(20), nullable=False, default="PZ")
    created_at = Column(DateTime, default=datetime.utcnow)
    notes = Column(Text, nullable=True)

    supplier = relationship("Supplier", back_populates="receipts")
    material = relationship("Material", back_populates="receipts")
    batch = relationship("Batch", back_populates="receipts")
    certificates = relationship("Certificate", back_populates="receipt")


class Certificate(Base):
    __tablename__ = "certificates"

    id = Column(Integer, primary_key=True, index=True)
    receipt_id = Column(Integer, ForeignKey("receipts.id"), nullable=False)
    filename = Column(String(255), nullable=False)
    mime_type = Column(String(100), nullable=True)
    storage_path = Column(String(500), nullable=True)
    uploaded_at = Column(DateTime, default=datetime.utcnow)

    receipt = relationship("Receipt", back_populates="certificates")


class StockMovement(Base):
    __tablename__ = "stock_movements"

    id = Column(Integer, primary_key=True, index=True)
    material_id = Column(Integer, ForeignKey("materials.id"), nullable=False)
    batch_id = Column(Integer, ForeignKey("batches.id"), nullable=True)
    quantity = Column(Numeric(18, 6), nullable=False)
    movement_type = Column(SQLEnum(MovementType), nullable=False)
    reason = Column(String(200), nullable=False)
    destination_commessa = Column(String(200), nullable=True)
    commessa_id = Column(Integer, ForeignKey("commesse.id"), nullable=True, index=True)
    reference = Column(String(200), nullable=True)
    occurred_at = Column(DateTime, default=datetime.utcnow)

    material = relationship("Material", back_populates="movements")
    batch = relationship("Batch", back_populates="movements")
    commessa = relationship("Commessa", foreign_keys=[commessa_id])


class DistintaImport(Base):
    __tablename__ = "distinta_imports"

    id = Column(Integer, primary_key=True, index=True)
    filename = Column(String(255), nullable=False)
    source_software = Column(String(100), nullable=True)
    imported_at = Column(DateTime, default=datetime.utcnow)
    total_items = Column(Integer, nullable=True)
    status = Column(String(50), nullable=False, default="PENDING")
    notes = Column(Text, nullable=True)

    items = relationship(
        "DistintaItem",
        back_populates="distinta_import",
        cascade="all, delete-orphan",
        passive_deletes=True,
    )


class DistintaItem(Base):
    __tablename__ = "distinta_items"

    id = Column(Integer, primary_key=True, index=True)
    import_id = Column(Integer, ForeignKey("distinta_imports.id", ondelete="CASCADE"), nullable=False)
    part_number = Column(String(200), nullable=True)
    description = Column(String(400), nullable=True)
    quantity = Column(Numeric(18, 6), nullable=True)
    material_code = Column(String(100), nullable=True)
    material_description = Column(String(400), nullable=True)
    commessa_reference = Column(String(200), nullable=True)
    commessa_id = Column(Integer, ForeignKey("commesse.id"), nullable=True, index=True)
    qr_code = Column(String(255), nullable=True)
    mapped_material_id = Column(Integer, ForeignKey("materials.id"), nullable=True)
    length_mm = Column(Numeric(12, 2), nullable=True)

    distinta_import = relationship("DistintaImport", back_populates="items")
    mapped_material = relationship("Material", primaryjoin="Material.id==DistintaItem.mapped_material_id")
    commessa = relationship("Commessa", foreign_keys=[commessa_id])


class TipoMovimentoRiserva(str, Enum):
    PRENOTAZIONE = "PRENOTAZIONE"
    CONFERMA_USCITA = "CONFERMA_USCITA"
    RIENTRO_SFRIDO = "RIENTRO_SFRIDO"


class CuttingPlan(Base):
    __tablename__ = "cutting_plans"

    id = Column(Integer, primary_key=True, index=True)
    commessa_id = Column(Integer, ForeignKey("commesse.id"), nullable=False, index=True)
    material_id = Column(Integer, ForeignKey("materials.id"), nullable=False, index=True)
    pezzi_ricavati = Column(Text, nullable=True)  # JSON
    sfrido_dim1 = Column(Numeric(12, 2), nullable=True)
    sfrido_dim2 = Column(Numeric(12, 2), nullable=True)
    sfrido_percentuale = Column(Numeric(8, 4), nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)

    material = relationship("Material", back_populates="cutting_plans")
    commessa = relationship("Commessa", foreign_keys=[commessa_id])


class StockReservation(Base):
    __tablename__ = "stock_reservations"

    id = Column(Integer, primary_key=True, index=True)
    material_id = Column(Integer, ForeignKey("materials.id"), nullable=False, index=True)
    commessa_id = Column(Integer, ForeignKey("commesse.id"), nullable=False, index=True)
    tipo_movimento = Column(SQLEnum(TipoMovimentoRiserva), nullable=False)
    quantita = Column(Numeric(18, 6), nullable=False)
    dimensione_1 = Column(Numeric(12, 2), nullable=True)
    dimensione_2 = Column(Numeric(12, 2), nullable=True)
    note = Column(Text, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)

    material = relationship("Material", back_populates="stock_reservations")
    commessa = relationship("Commessa", foreign_keys=[commessa_id])
