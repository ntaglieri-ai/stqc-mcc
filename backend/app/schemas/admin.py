from datetime import datetime, timedelta
from typing import Any, Optional

from pydantic import BaseModel, computed_field

from backend.app.models.user import ProfiloUtente

PASSWORD_EXPIRE_DAYS = 90


# ── User ──────────────────────────────────────────────────────────────────────

class UserCreate(BaseModel):
    username: str
    password: str
    profilo:  ProfiloUtente = ProfiloUtente.PROGETTAZIONE
    nome:     Optional[str] = None
    cognome:  Optional[str] = None
    email:    Optional[str] = None


class UserUpdate(BaseModel):
    username: Optional[str] = None
    password: Optional[str] = None
    profilo:  Optional[ProfiloUtente] = None
    nome:     Optional[str] = None
    cognome:  Optional[str] = None
    email:    Optional[str] = None


class UserRead(BaseModel):
    id:                  int
    username:            Optional[str]
    nome:                Optional[str]
    cognome:             Optional[str]
    email:               Optional[str]
    profilo:             ProfiloUtente
    attivo:              bool
    ultimo_accesso:      Optional[datetime]
    created_at:          datetime
    failed_attempts:     int = 0
    locked_until:        Optional[datetime] = None
    password_changed_at: Optional[datetime] = None

    @computed_field
    @property
    def password_expires_at(self) -> Optional[datetime]:
        if self.password_changed_at:
            return self.password_changed_at + timedelta(days=PASSWORD_EXPIRE_DAYS)
        return None

    @computed_field
    @property
    def password_status(self) -> str:
        """'ok' | 'warning' (≤30gg) | 'expired' | 'never_set'"""
        if not self.password_changed_at:
            return "never_set"
        expires = self.password_changed_at + timedelta(days=PASSWORD_EXPIRE_DAYS)
        now = datetime.utcnow()
        if now > expires:
            return "expired"
        if (expires - now).days <= 30:
            return "warning"
        return "ok"

    model_config = {"from_attributes": True}


# ── User Attributes ───────────────────────────────────────────────────────────

class UserAttributesRead(BaseModel):
    postazioni_assegnate: Optional[list[str]] = None
    commesse_visibili:    Optional[Any] = None       # list[int] | "all"
    permessi:             Optional[dict] = None

    model_config = {"from_attributes": True}


class UserAttributesUpdate(BaseModel):
    postazioni_assegnate: Optional[list[str]] = None
    commesse_visibili:    Optional[Any] = None
    permessi:             Optional[dict] = None


# ── Audit Log ─────────────────────────────────────────────────────────────────

class AuditLogRead(BaseModel):
    id:             int
    timestamp:      datetime
    user_id:        Optional[int]
    username:       Optional[str]
    gruppo:         Optional[str]
    action:         str
    target_user_id: Optional[int]
    ip_address:     Optional[str]
    details:        Optional[str]

    model_config = {"from_attributes": True}


# ── Groups ────────────────────────────────────────────────────────────────────

class GroupPermissionRead(BaseModel):
    sezione: str
    livello: str   # 'none' | 'read' | 'write'

    model_config = {"from_attributes": True}


class GroupPermissionUpdate(BaseModel):
    sezione: str
    livello: str


class GroupRead(BaseModel):
    id:          int
    name:        str
    descrizione: Optional[str]
    postazioni:  Optional[list[str]]
    permissions: list[GroupPermissionRead]
    user_count:  int = 0

    model_config = {"from_attributes": True}


class GroupUpdate(BaseModel):
    descrizione: Optional[str] = None
    postazioni:  Optional[list[str]] = None
    permissions: Optional[list[GroupPermissionUpdate]] = None


# ── Workstations / Scanner devices ───────────────────────────────────────────

class WorkstationRead(BaseModel):
    id: int
    code: str
    name: str
    description: Optional[str]
    active: bool
    start_qr_code: str
    end_qr_code: str
    created_at: Optional[datetime]

    model_config = {"from_attributes": True}


class WorkstationCreate(BaseModel):
    code: str
    name: str
    description: Optional[str] = None
    active: bool = True


class WorkstationUpdate(BaseModel):
    code: Optional[str] = None
    name: Optional[str] = None
    description: Optional[str] = None
    active: Optional[bool] = None


class ScannerDeviceRead(BaseModel):
    id: int
    scanner_code: str
    name: str
    description: Optional[str]
    scan_mode: str = "OFFICINA"
    postazione_id: Optional[int]
    ip_address: Optional[str]
    serial_number: Optional[str]
    device_token: Optional[str]
    active: bool
    last_seen_at: Optional[datetime]
    created_at: Optional[datetime]
    updated_at: Optional[datetime]

    model_config = {"from_attributes": True}


class ScannerDeviceCreate(BaseModel):
    scanner_code: str
    name: str
    description: Optional[str] = None
    scan_mode: str = "OFFICINA"
    postazione_id: Optional[int] = None
    ip_address: Optional[str] = None
    serial_number: Optional[str] = None
    device_token: Optional[str] = None
    active: bool = True


class ScannerDeviceUpdate(BaseModel):
    scanner_code: Optional[str] = None
    name: Optional[str] = None
    description: Optional[str] = None
    scan_mode: Optional[str] = None
    postazione_id: Optional[int] = None
    ip_address: Optional[str] = None
    serial_number: Optional[str] = None
    device_token: Optional[str] = None
    active: Optional[bool] = None


# ── Maintenance ───────────────────────────────────────────────────────────────

class MaintenanceResult(BaseModel):
    success: bool
    message: str
    detail:  Optional[str] = None
