from datetime import datetime
from enum import Enum

from sqlalchemy import Boolean, Column, DateTime, Enum as SQLEnum, ForeignKey, Integer, JSON, String, Text
from sqlalchemy.orm import relationship

from backend.app.db.base import Base


class ProfiloUtente(str, Enum):
    ADMIN      = "Admin"
    DIRETTORE  = "Direttore"
    PROGETTAZIONE = "Progettazione"
    LOGISTICA  = "Logistica"
    ACQUISTI   = "Acquisti"


_SEZIONI = ("commesse", "magazzino", "admin")
_LIVELLI = ("none", "read", "write")

# Default permissions per group — used to seed the groups table
GROUP_DEFAULTS: dict[str, dict] = {
    "Admin":         {"commesse": "write", "magazzino": "write", "admin": "write"},
    "Direttore":     {"commesse": "write", "magazzino": "read",  "admin": "none"},
    "Progettazione": {"commesse": "write", "magazzino": "read",  "admin": "none"},
    "Logistica":     {"commesse": "read",  "magazzino": "write", "admin": "none"},
    "Acquisti":      {"commesse": "read",  "magazzino": "read",  "admin": "none"},
}

GROUP_POSTAZIONI_DEFAULTS: dict[str, list[str]] = {
    "Admin":         [],
    "Direttore":     [],
    "Progettazione": [],
    "Logistica":     ["Magazzino"],
    "Acquisti":      [],
}


class User(Base):
    __tablename__ = "users"

    id              = Column(Integer, primary_key=True, index=True)
    nome            = Column(String(100), nullable=True)
    cognome         = Column(String(100), nullable=True)
    email           = Column(String(200), unique=True, index=True, nullable=True)
    profilo         = Column(
        SQLEnum(ProfiloUtente, values_callable=lambda x: [e.value for e in x]),
        nullable=False,
        default=ProfiloUtente.PROGETTAZIONE,
    )
    username        = Column(String(100), unique=True, index=True, nullable=True)
    password_hash   = Column(String(255), nullable=True)
    attivo          = Column(Boolean, nullable=False, default=True)
    ultimo_accesso  = Column(DateTime, nullable=True)
    pin_hash        = Column(String(255), nullable=True)   # legacy, non più usato
    created_at      = Column(DateTime, default=datetime.utcnow)
    failed_attempts = Column(Integer, nullable=False, default=0)
    locked_until    = Column(DateTime, nullable=True)
    password_changed_at = Column(DateTime, nullable=True)  # NIS2: tracciamento scadenza

    attributes = relationship(
        "UserAttributes",
        uselist=False,
        back_populates="user",
        cascade="all, delete-orphan",
    )
    audit_logs = relationship(
        "AuditLog",
        back_populates="user",
        foreign_keys="AuditLog.user_id",
    )


class UserAttributes(Base):
    __tablename__ = "user_attributes"

    id                    = Column(Integer, primary_key=True, index=True)
    user_id               = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"), unique=True, nullable=False)
    postazioni_assegnate  = Column(JSON, nullable=True)   # list[str]
    commesse_visibili     = Column(JSON, nullable=True)   # list[int] | "all"
    permessi              = Column(JSON, nullable=True)   # {"section": {"read": bool, "write": bool}}

    user = relationship("User", back_populates="attributes")


class AuditLog(Base):
    __tablename__ = "audit_logs"

    id             = Column(Integer, primary_key=True, index=True)
    timestamp      = Column(DateTime, default=datetime.utcnow, nullable=False, index=True)
    user_id        = Column(Integer, ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    username       = Column(String(100), nullable=True)    # denormalizzato per immutabilità
    gruppo         = Column(String(50),  nullable=True)
    action         = Column(String(50),  nullable=False, index=True)
    target_user_id = Column(Integer, nullable=True)
    ip_address     = Column(String(50),  nullable=True)
    details        = Column(Text, nullable=True)

    user = relationship("User", foreign_keys=[user_id], back_populates="audit_logs")


class Group(Base):
    """Profilo/gruppo con permessi e postazioni associabili. Una riga per ProfiloUtente."""
    __tablename__ = "groups"

    id           = Column(Integer, primary_key=True, index=True)
    name         = Column(String(50), unique=True, nullable=False, index=True)  # == ProfiloUtente.value
    descrizione  = Column(Text, nullable=True)
    postazioni   = Column(JSON, nullable=True)   # list[str] — postazioni assegnabili a questo gruppo

    permissions  = relationship(
        "GroupPermission",
        back_populates="group",
        cascade="all, delete-orphan",
    )


class GroupPermission(Base):
    """Permesso per sezione per un gruppo. Una riga per (group, sezione)."""
    __tablename__ = "group_permissions"

    id         = Column(Integer, primary_key=True, index=True)
    group_name = Column(String(50), ForeignKey("groups.name", ondelete="CASCADE"), nullable=False, index=True)
    sezione    = Column(String(50), nullable=False)   # 'commesse' | 'magazzino' | 'admin'
    livello    = Column(String(10), nullable=False, default="none")  # 'none' | 'read' | 'write'

    group = relationship("Group", back_populates="permissions")
