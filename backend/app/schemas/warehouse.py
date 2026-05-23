from datetime import date, datetime
from enum import Enum
from typing import Optional

from pydantic import BaseModel, Field


class MovementType(str, Enum):
    INCOMING = "INCOMING"
    OUTGOING = "OUTGOING"
    ADJUSTMENT = "ADJUSTMENT"


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
    code: str = Field(..., example="S235JR")
    description: str = Field(..., example="Profilo IPE 200")
    unit: str = Field("PZ", example="PZ")
    specification: Optional[str] = Field(None, example="EN 10025-2")


class MaterialCreate(MaterialBase):
    pass


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
    batch_id: Optional[int]
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
    material_id: int
    batch_id: Optional[int]
    quantity: float = Field(..., example=8.0)
    movement_type: MovementType
    reason: str = Field(..., example="Prelievo commessa")
    destination_commessa: Optional[str] = None
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
