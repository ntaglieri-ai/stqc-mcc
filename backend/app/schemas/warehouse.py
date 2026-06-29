from datetime import date, datetime
from enum import Enum
from typing import Any, List, Optional

from pydantic import BaseModel, ConfigDict, Field


class MovementType(str, Enum):
    INCOMING = "INCOMING"
    OUTGOING = "OUTGOING"
    ADJUSTMENT = "ADJUSTMENT"
    SFRIDO = "SFRIDO"


class SupplierBase(BaseModel):
    name: str = Field(..., example="Fornitore S.r.l.")
    tax_id: Optional[str] = Field(None, example="IT12345678901")
    address: Optional[str] = Field(None, example="Via Roma 1, 20090 Milano")
    contacts: Optional[str] = Field(None, example="+39 02 1234567")


class SupplierCreate(SupplierBase):
    pass


class SupplierRead(SupplierBase):
    id: int

    class Config:
        from_attributes = True


class MaterialBase(BaseModel):
    code: str = Field(..., example="HEA-200-S275")
    description: str = Field(..., example="HEA 200 | S275")
    unit: str = Field("PZ", example="PZ")
    specification: Optional[str] = Field(None, example="S275")
    tipo: Optional[str] = Field(None, example="HEA")
    profilo: Optional[str] = Field(None, example="200")
    dimensioni: Optional[str] = Field(None, example="6000")
    qualita: Optional[str] = Field(None, example="S275")
    colata: Optional[str] = Field(None, example="C-2026-001")
    peso_u_kg: Optional[float] = Field(None, example=42.3)
    peso_1_pz: Optional[float] = Field(None, example=253.8)


class MaterialCreate(MaterialBase):
    pass


class MaterialIncomingCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    code: Optional[str] = None
    description: Optional[str] = None
    unit: str = "PZ"
    specification: Optional[str] = None
    tipo: Optional[str] = None
    profilo: Optional[str] = None
    dimensioni: Optional[str] = None
    norma_uni: Optional[str] = None
    qualita: Optional[str] = None
    colata: Optional[str] = None
    peso_u_kg: Optional[float] = None
    peso_1_pz: Optional[float] = None
    quantity: float = Field(..., gt=0)
    reason: str = "Ingresso nuovo materiale"


class MaterialRead(MaterialBase):
    id: int

    class Config:
        from_attributes = True


class BatchBase(BaseModel):
    batch_number: str = Field(..., example="LOTTO-2026-001")
    material_id: int
    heat_number: Optional[str] = Field(None, example="HN-1345")
    produced_date: Optional[date] = None
    notes: Optional[str] = None


class BatchCreate(BatchBase):
    pass


class BatchRead(BatchBase):
    id: int

    class Config:
        from_attributes = True


class ReceiptBase(BaseModel):
    ddt_number: str = Field(..., example="DDT-00123")
    ddt_date: date
    supplier_id: int
    material_id: int
    batch_id: Optional[int] = None
    quantity: float = Field(..., example=100.0)
    unit: str = Field("PZ", example="KG")
    notes: Optional[str] = None


class ReceiptCreate(ReceiptBase):
    pass


class ReceiptRead(ReceiptBase):
    id: int
    created_at: datetime

    class Config:
        from_attributes = True


class CertificateBase(BaseModel):
    receipt_id: int
    filename: str
    mime_type: Optional[str] = None
    storage_path: Optional[str] = None


class CertificateCreate(CertificateBase):
    pass


class CertificateRead(CertificateBase):
    id: int
    uploaded_at: datetime

    class Config:
        from_attributes = True


class StockMovementBase(BaseModel):
    model_config = ConfigDict(extra="forbid")

    material_id: int
    batch_id: Optional[int] = None
    quantity: float = Field(..., example=8.0)
    movement_type: MovementType
    reason: str = Field(..., example="Ingresso manuale")
    reference: Optional[str] = None


class StockMovementCreate(StockMovementBase):
    pass


class StockMovementRead(StockMovementBase):
    id: int
    occurred_at: datetime

    class Config:
        from_attributes = True


class StockBalanceRead(BaseModel):
    material_id: int
    material_code: str
    material_description: str
    total_incoming: float
    total_outgoing: float
    current_stock: float

    class Config:
        from_attributes = True


class MagazzinoItemRead(BaseModel):
    material_id: int
    material_code: str
    tipo: Optional[str] = None
    profilo: Optional[str] = None
    n_pezzi: float
    dimensioni: Optional[str] = None
    qualita: Optional[str] = None
    colata: Optional[str] = None
    peso_kg: Optional[float] = None
    peso_u_kg: Optional[float] = None
    peso_1_pz: Optional[float] = None
    norma_uni: Optional[str] = None
    unita_misura: Optional[str] = "pz"
    dimensione_2: Optional[float] = None
    physical_items_count: int = 0
    reserved_items_count: int = 0
    reserved_commesse: List[str] = Field(default_factory=list)

    class Config:
        from_attributes = True


class WarehousePhysicalItemRead(BaseModel):
    id: int
    uuid: str
    material_id: int
    ordinal: int
    status: str
    created_at: datetime
    exited_at: Optional[datetime] = None
    label: str
    reserved_for_commessa: Optional[str] = None


class WarehouseItemDetailRead(WarehousePhysicalItemRead):
    material_code: str
    description: Optional[str] = None
    tipo: Optional[str] = None
    profilo: Optional[str] = None
    dimensioni: Optional[str] = None
    norma_uni: Optional[str] = None
    qualita: Optional[str] = None
    colata: Optional[str] = None
    commessa_ref: Optional[str] = None
    reserved_for_commessa: Optional[str] = None
    peso_u_kg: Optional[float] = None
    peso_1_pz: Optional[float] = None
    peso_kg: Optional[float] = None
    unit: Optional[str] = None
    source_movement_id: Optional[int] = None
    exit_movement_id: Optional[int] = None
    notes: Optional[str] = None
    manual_overrides: List[str] = Field(default_factory=list)


class WarehouseItemUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    tipo: Optional[str] = None
    profilo: Optional[str] = None
    dimensioni: Optional[str] = None
    norma_uni: Optional[str] = None
    qualita: Optional[str] = None
    colata: Optional[str] = None
    commessa_ref: Optional[str] = None
    reserved_for_commessa: Optional[str] = None
    peso_u_kg: Optional[float] = None
    peso_1_pz: Optional[float] = None
    notes: Optional[str] = None


class WarehouseItemBulkRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    uuids: List[str] = Field(..., min_length=1, max_length=500)


class WarehouseItemBulkDeleteResult(BaseModel):
    deleted: int
    requested: int
    missing: List[str] = Field(default_factory=list)


class WarehouseLabelPrintRequest(WarehouseItemBulkRequest):
    label_format: str = Field("rect", pattern="^(a6|rect|compact|badge)$")
    text: Optional[str] = Field(None, max_length=80)
    qr_encoding: str = Field("link", pattern="^(link|uuid|json)$")
    qr_size_mm: Optional[float] = Field(None, ge=18, le=90)
    content_fields: List[str] = Field(default_factory=lambda: ["tipo", "profilo", "dimensioni", "qualita"])


class WarehouseScanRequest(BaseModel):
    payload: str


class WarehouseScanResult(BaseModel):
    item: WarehousePhysicalItemRead
    material: MagazzinoItemRead


# ── Stock Reservations ──────────────────────────────────────────────────────

class TipoMovimentoRiserva(str, Enum):
    PRENOTAZIONE = "PRENOTAZIONE"
    CONFERMA_USCITA = "CONFERMA_USCITA"
    RIENTRO_SFRIDO = "RIENTRO_SFRIDO"


class StockReservationCreate(BaseModel):
    material_id: int
    commessa_id: int
    tipo_movimento: TipoMovimentoRiserva
    quantita: float
    dimensione_1: Optional[float] = None
    dimensione_2: Optional[float] = None
    note: Optional[str] = None


class StockReservationRead(StockReservationCreate):
    id: int
    created_at: datetime

    class Config:
        from_attributes = True


# ── Cutting Stock Analysis ───────────────────────────────────────────────────

class DistintaAnalysisItem(BaseModel):
    material_id: int
    profilo: str
    qualita: Optional[str] = None
    length_mm: Optional[float] = None
    width_mm: Optional[float] = None
    quantity: int
    n_available: float
    dim1_stock: Optional[float] = None
    dim2_stock: Optional[float] = None
    unita_misura: Optional[str] = "pz"
    peso_1_pz: Optional[float] = None
    peso_kg: Optional[float] = None


class DistintaAnalysisRequest(BaseModel):
    commessa_id: Optional[int] = None
    items: List[DistintaAnalysisItem]


class DistintaAnalysisResult(BaseModel):
    cutting_plans: List[Any]
    sfrido_totale_percentuale: float
    warning_sfrido: bool
