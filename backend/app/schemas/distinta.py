from datetime import datetime
from typing import List, Optional

from pydantic import BaseModel, Field


class DistintaItemBase(BaseModel):
    part_number: Optional[str] = Field(None, example="IPE200")
    description: Optional[str] = Field(None, example="Trave IPE 200")
    quantity: Optional[float] = Field(None, example=12.0)
    material_code: Optional[str] = Field(None, example="S235JR")
    material_description: Optional[str] = Field(None, example="Acciaio da carpenteria")
    commessa_reference: Optional[str] = Field(None, example="COMM-2026-001")
    qr_code: Optional[str] = None
    length_mm: Optional[float] = Field(None, example=3500.0)
    width_mm: Optional[float] = Field(None, example=250.0)
    instance_number: Optional[int] = None
    parent_assembly: Optional[str] = None


class DistintaItemCreate(DistintaItemBase):
    import_id: int


class DistintaItemRead(DistintaItemBase):
    id: int
    uuid: str
    commessa_id: Optional[int] = None
    qr_attivo: bool = False
    stato_tracciamento: str = "NON_GENERATO"

    class Config:
        from_attributes = True


class DistintaImportBase(BaseModel):
    filename: str
    source_software: Optional[str] = Field(None, example="Tekla")
    total_items: Optional[int] = None
    status: Optional[str] = Field("PENDING", example="PENDING")
    notes: Optional[str] = None


class DistintaImportCreate(DistintaImportBase):
    pass


class DistintaImportRead(DistintaImportBase):
    id: int
    imported_at: datetime
    items: List[DistintaItemRead] = []

    class Config:
        from_attributes = True


class QRScanRequest(BaseModel):
    payload: str = Field(..., description="Contenuto testuale del QR (JSON o stringa libera)")


class QRScanResult(DistintaItemRead):
    import_filename: Optional[str] = None
    import_status: Optional[str] = None
