import hashlib
import io
import logging
import os
import platform
import re
import shutil
import subprocess
import sys
import threading
import time
from datetime import datetime, timedelta
from pathlib import Path
from typing import Optional

_logger = logging.getLogger("stqc.admin")

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import StreamingResponse
from pydantic import BaseModel
from sqlalchemy import inspect, text
from sqlalchemy.orm import Session

from backend.app.core.auth import hash_password, validate_password_complexity, write_audit_log
from backend.app.core.config import settings
from backend.app.core.log_collector import log_collector
from backend.app.db.session import engine, get_db
from backend.app.models.user import AuditLog, Group, GroupPermission, ProfiloUtente, User, UserAttributes
from backend.app.schemas.admin import (
    AuditLogRead,
    GroupRead,
    GroupUpdate,
    MaintenanceResult,
    UserAttributesRead,
    UserAttributesUpdate,
    UserCreate,
    UserRead,
    UserUpdate,
)

INVENTARIO_PATH = Path("/Users/imacnando/Desktop/stqc-mcc/INVENTARIO_8_5_26_REL3XNANDO.xlsm")

try:
    import psutil
    _HAS_PSUTIL = True
except ImportError:
    _HAS_PSUTIL = False

router = APIRouter()

BACKUP_DIR = Path("./backups")
APP_VERSION = "1.0.0"
DEPLOY_DATE = "2026-05-28"

# Account di sviluppo protetti — non disattivabili tramite API
_PROTECTED_USERNAMES = {"admin", "direttore", "operatore", "logistica", "acquisti"}

_logger.info("Admin router loaded — log collector active")


def _postazione_to_username(postazione: str) -> str:
    s = re.sub(r"^[Pp]ostazione\s+", "", postazione).strip()
    s = re.sub(r"\s*[—–\-]+\s*", "_", s)
    s = re.sub(r"\s+(\d)", r"\1", s)
    s = s.replace(" ", "_").lower()
    s = re.sub(r"[^a-z0-9_]", "", s)
    s = re.sub(r"_+", "_", s).strip("_")
    return f"operatore_{s}"


# ── Users ─────────────────────────────────────────────────────────────────────

@router.get("/users", response_model=list[UserRead])
def list_users(db: Session = Depends(get_db)):
    return db.query(User).order_by(User.username).all()


@router.post("/users", response_model=UserRead, status_code=201)
def create_user(user_in: UserCreate, db: Session = Depends(get_db)):
    _logger.info("Creazione utente: %s [%s]", user_in.username, user_in.profilo.value)

    errors = validate_password_complexity(user_in.password)
    if errors:
        raise HTTPException(400, f"Password non valida: {', '.join(errors)}")

    if user_in.email:
        if db.query(User).filter(User.email == user_in.email).first():
            raise HTTPException(409, f"Email '{user_in.email}' già in uso")
    if db.query(User).filter(User.username == user_in.username).first():
        raise HTTPException(409, f"UserID '{user_in.username}' già in uso")

    user = User(
        nome=user_in.nome,
        cognome=user_in.cognome,
        email=user_in.email,
        username=user_in.username,
        password_hash=hash_password(user_in.password),
        profilo=user_in.profilo,
        password_changed_at=datetime.utcnow(),
    )
    db.add(user)
    db.commit()
    db.refresh(user)
    write_audit_log(db, "CREATE_USER", target_user_id=user.id, details=f"profilo={user_in.profilo.value}")
    db.commit()
    return user


@router.patch("/users/{user_id}", response_model=UserRead)
def update_user(user_id: int, user_in: UserUpdate, db: Session = Depends(get_db)):
    user = db.get(User, user_id)
    if not user:
        raise HTTPException(404, "Utente non trovato")

    data = user_in.model_dump(exclude_unset=True)
    changes = []

    for field, value in data.items():
        if field == "password":
            if value:
                errors = validate_password_complexity(value)
                if errors:
                    raise HTTPException(400, f"Password non valida: {', '.join(errors)}")
                user.password_hash       = hash_password(value)
                user.password_changed_at = datetime.utcnow()
                changes.append("password")
        elif field == "username":
            if value and value != user.username:
                if db.query(User).filter(User.username == value).first():
                    raise HTTPException(409, f"Username '{value}' già in uso")
            user.username = value
            changes.append(f"username={value}")
        else:
            setattr(user, field, value)
            changes.append(f"{field}={value}")

    db.commit()
    db.refresh(user)
    write_audit_log(db, "UPDATE_USER", target_user_id=user_id, details=", ".join(changes))
    db.commit()
    return user


@router.post("/users/{user_id}/toggle")
def toggle_user(user_id: int, db: Session = Depends(get_db)):
    user = db.get(User, user_id)
    if not user:
        raise HTTPException(404, "Utente non trovato")
    if user.username in _PROTECTED_USERNAMES and user.attivo:
        raise HTTPException(403, f"L'account '{user.username}' è protetto e non può essere disattivato")
    user.attivo = not user.attivo
    action = "ENABLE_USER" if user.attivo else "DISABLE_USER"
    write_audit_log(db, action, target_user_id=user_id)
    db.commit()
    _logger.info("Utente %d %s: %s", user_id, user.username, "attivato" if user.attivo else "disattivato")
    return {"id": user_id, "attivo": user.attivo}


@router.post("/users/{user_id}/unlock")
def unlock_user(user_id: int, db: Session = Depends(get_db)):
    """Sblocca manualmente un account bloccato per troppi tentativi falliti."""
    user = db.get(User, user_id)
    if not user:
        raise HTTPException(404, "Utente non trovato")
    user.failed_attempts = 0
    user.locked_until    = None
    write_audit_log(db, "UNLOCK_USER", target_user_id=user_id)
    db.commit()
    return {"id": user_id, "unlocked": True}


@router.post("/users/provision-operatori")
def provision_operatori(db: Session = Depends(get_db)):
    """Crea automaticamente un utente Operatore per ogni postazione delle fasi operative."""
    from sqlalchemy import distinct, select
    from backend.app.models.commessa import FaseOperativa

    postazioni = db.scalars(
        select(distinct(FaseOperativa.postazione)).where(FaseOperativa.postazione.isnot(None))
    ).all()

    DEFAULT_PASSWORD = "Operatore@2026!"
    pwd_hash = hash_password(DEFAULT_PASSWORD)

    created: list[dict] = []
    skipped: list[dict] = []

    for postazione in sorted(postazioni):
        username = _postazione_to_username(postazione)
        if db.query(User).filter(User.username == username).first():
            skipped.append({"username": username, "postazione": postazione})
            continue

        user = User(
            username=username,
            password_hash=pwd_hash,
            profilo=ProfiloUtente.OPERATORE,
            attivo=True,
            password_changed_at=datetime.utcnow(),
        )
        db.add(user)
        created.append({"username": username, "postazione": postazione})
        _logger.info("Provisionato operatore: %s (%s)", username, postazione)

    db.commit()
    write_audit_log(db, "PROVISION_OPERATORI",
                    details=f"creati={len(created)}, saltati={len(skipped)}")
    db.commit()
    return {
        "created":       created,
        "skipped":       skipped,
        "total_created": len(created),
        "total_skipped": len(skipped),
        "default_password": DEFAULT_PASSWORD,
    }


# ── User Attributes ───────────────────────────────────────────────────────────

@router.get("/users/{user_id}/attributes", response_model=UserAttributesRead)
def get_user_attributes(user_id: int, db: Session = Depends(get_db)):
    user = db.get(User, user_id)
    if not user:
        raise HTTPException(404, "Utente non trovato")
    if not user.attributes:
        return UserAttributesRead()
    return user.attributes


@router.put("/users/{user_id}/attributes", response_model=UserAttributesRead)
def set_user_attributes(user_id: int, attrs_in: UserAttributesUpdate, db: Session = Depends(get_db)):
    user = db.get(User, user_id)
    if not user:
        raise HTTPException(404, "Utente non trovato")

    if not user.attributes:
        user.attributes = UserAttributes(user_id=user_id)

    data = attrs_in.model_dump(exclude_unset=True)
    for field, value in data.items():
        setattr(user.attributes, field, value)

    write_audit_log(db, "UPDATE_ATTRIBUTES", target_user_id=user_id,
                    details=str(list(data.keys())))
    db.commit()
    db.refresh(user)
    return user.attributes


# ── Audit Log ─────────────────────────────────────────────────────────────────

@router.get("/audit-logs", response_model=list[AuditLogRead])
def list_audit_logs(
    user_id: Optional[int] = None,
    action:  Optional[str] = None,
    limit:   int = 200,
    db: Session = Depends(get_db),
):
    q = db.query(AuditLog).order_by(AuditLog.timestamp.desc())
    if user_id:
        q = q.filter(AuditLog.user_id == user_id)
    if action:
        q = q.filter(AuditLog.action == action)
    # NIS2: conservazione 12 mesi
    cutoff = datetime.utcnow() - timedelta(days=365)
    q = q.filter(AuditLog.timestamp >= cutoff)
    return q.limit(limit).all()


@router.get("/users/{user_id}/audit-log", response_model=list[AuditLogRead])
def user_audit_log(user_id: int, limit: int = 50, db: Session = Depends(get_db)):
    if not db.get(User, user_id):
        raise HTTPException(404, "Utente non trovato")
    cutoff = datetime.utcnow() - timedelta(days=365)
    return (
        db.query(AuditLog)
        .filter(AuditLog.user_id == user_id, AuditLog.timestamp >= cutoff)
        .order_by(AuditLog.timestamp.desc())
        .limit(limit)
        .all()
    )


# ── Reset Password ────────────────────────────────────────────────────────────

@router.post("/users/{user_id}/reset-password")
def reset_password(user_id: int, db: Session = Depends(get_db)):
    """Genera una password temporanea NIS2-compliant e la imposta sull'account."""
    import secrets, string
    user = db.get(User, user_id)
    if not user:
        raise HTTPException(404, "Utente non trovato")

    alphabet = string.ascii_letters + string.digits + "!@#$%^&*"
    while True:
        pwd = "".join(secrets.choice(alphabet) for _ in range(16))
        if (
            any(c.isupper() for c in pwd)
            and any(c.islower() for c in pwd)
            and any(c.isdigit() for c in pwd)
            and any(c in "!@#$%^&*" for c in pwd)
        ):
            break

    user.password_hash       = hash_password(pwd)
    user.password_changed_at = datetime.utcnow()
    user.failed_attempts     = 0
    user.locked_until        = None
    write_audit_log(db, "RESET_PASSWORD", target_user_id=user_id)
    db.commit()
    _logger.info("Password resettata per utente %d (%s)", user_id, user.username)
    return {"id": user_id, "temporary_password": pwd}


# ── Groups ────────────────────────────────────────────────────────────────────

def _group_to_read(g: Group, db: Session) -> GroupRead:
    user_count = db.query(User).filter(
        User.profilo == g.name, User.attivo == True
    ).count()
    return GroupRead(
        id=g.id,
        name=g.name,
        descrizione=g.descrizione,
        postazioni=g.postazioni or [],
        permissions=[{"sezione": p.sezione, "livello": p.livello} for p in g.permissions],
        user_count=user_count,
    )


@router.get("/groups", response_model=list[GroupRead])
def list_groups(db: Session = Depends(get_db)):
    groups = db.query(Group).order_by(Group.name).all()
    return [_group_to_read(g, db) for g in groups]


@router.get("/groups/{name}", response_model=GroupRead)
def get_group(name: str, db: Session = Depends(get_db)):
    g = db.query(Group).filter(Group.name == name).first()
    if not g:
        raise HTTPException(404, f"Gruppo '{name}' non trovato")
    return _group_to_read(g, db)


@router.put("/groups/{name}", response_model=GroupRead)
def update_group(name: str, body: GroupUpdate, db: Session = Depends(get_db)):
    g = db.query(Group).filter(Group.name == name).first()
    if not g:
        raise HTTPException(404, f"Gruppo '{name}' non trovato")

    if body.descrizione is not None:
        g.descrizione = body.descrizione
    if body.postazioni is not None:
        g.postazioni = body.postazioni
    if body.permissions is not None:
        allowed_sezioni = {"commesse", "magazzino", "admin"}
        allowed_livelli = {"none", "read", "write"}
        for perm_in in body.permissions:
            if perm_in.sezione not in allowed_sezioni:
                raise HTTPException(400, f"Sezione non valida: {perm_in.sezione}")
            if perm_in.livello not in allowed_livelli:
                raise HTTPException(400, f"Livello non valido: {perm_in.livello}")
            existing = next((p for p in g.permissions if p.sezione == perm_in.sezione), None)
            if existing:
                existing.livello = perm_in.livello
            else:
                db.add(GroupPermission(group_name=name, sezione=perm_in.sezione, livello=perm_in.livello))

    write_audit_log(db, "UPDATE_GROUP", details=f"group={name}")
    db.commit()
    db.refresh(g)
    return _group_to_read(g, db)


@router.get("/groups/{name}/users", response_model=list[UserRead])
def group_users(name: str, db: Session = Depends(get_db)):
    if not db.query(Group).filter(Group.name == name).first():
        raise HTTPException(404, f"Gruppo '{name}' non trovato")
    return db.query(User).filter(User.profilo == name).order_by(User.username).all()


# ── System Status ─────────────────────────────────────────────────────────────

@router.get("/system/status")
def system_status():
    uptime_s = cpu = mem_total = mem_used = mem_pct = 0.0
    disk_total = disk_used = disk_pct = 0.0

    if _HAS_PSUTIL:
        try:
            uptime_s = time.time() - psutil.boot_time()
            cpu = psutil.cpu_percent(interval=0.2)
            mem = psutil.virtual_memory()
            mem_total = mem.total / 1024 / 1024
            mem_used = mem.used / 1024 / 1024
            mem_pct = mem.percent
            disk = psutil.disk_usage("/")
            disk_total = disk.total / 1024 / 1024 / 1024
            disk_used = disk.used / 1024 / 1024 / 1024
            disk_pct = disk.percent
        except Exception:
            pass

    db_path = settings.database_url.replace("sqlite:///./", "./").replace("sqlite:///", "")
    db_size = 0.0
    try:
        db_size = os.path.getsize(db_path) / 1024 / 1024
    except Exception:
        pass

    db_tables = 0
    try:
        insp = inspect(engine)
        db_tables = len(insp.get_table_names())
    except Exception:
        pass

    cloudflare_ok = False
    try:
        result = subprocess.run(["pgrep", "-x", "cloudflared"], capture_output=True, timeout=2)
        cloudflare_ok = result.returncode == 0
    except Exception:
        pass

    last_backup = None
    try:
        BACKUP_DIR.mkdir(exist_ok=True)
        backups = sorted(BACKUP_DIR.glob("*.db"), key=os.path.getmtime, reverse=True)
        if backups:
            ts = os.path.getmtime(backups[0])
            last_backup = datetime.utcfromtimestamp(ts).isoformat()
    except Exception:
        pass

    return {
        "uptime_seconds": round(uptime_s, 0),
        "uptime_human": _uptime_human(uptime_s),
        "cpu_percent": round(cpu, 1),
        "memory_total_mb": round(mem_total, 1),
        "memory_used_mb": round(mem_used, 1),
        "memory_percent": round(mem_pct, 1),
        "disk_total_gb": round(disk_total, 2),
        "disk_used_gb": round(disk_used, 2),
        "disk_percent": round(disk_pct, 1),
        "db_size_mb": round(db_size, 3),
        "db_tables": db_tables,
        "db_path": db_path,
        "cloudflare_tunnel": cloudflare_ok,
        "last_backup": last_backup,
    }


def _uptime_human(seconds: float) -> str:
    days = int(seconds // 86400)
    hours = int((seconds % 86400) // 3600)
    minutes = int((seconds % 3600) // 60)
    if days > 0:
        return f"{days}g {hours}h {minutes}m"
    if hours > 0:
        return f"{hours}h {minutes}m"
    return f"{minutes}m"


# ── Logs ──────────────────────────────────────────────────────────────────────

@router.get("/logs")
def get_logs(level: Optional[str] = None, limit: int = 500):
    return {"entries": log_collector.get(level=level, limit=limit)}


@router.get("/logs/export")
def export_logs(level: Optional[str] = None):
    csv_data = log_collector.to_csv(level=level)
    filename = f"logs_{datetime.utcnow().strftime('%Y%m%d_%H%M%S')}.csv"
    return StreamingResponse(
        io.BytesIO(csv_data.encode()),
        media_type="text/csv",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


# ── Maintenance ───────────────────────────────────────────────────────────────

@router.post("/maintenance/backup")
def backup_database():
    db_path = Path(settings.database_url.replace("sqlite:///./", "./").replace("sqlite:///", ""))
    if not db_path.exists():
        raise HTTPException(400, "Database non trovato")

    BACKUP_DIR.mkdir(exist_ok=True)
    ts = datetime.utcnow().strftime("%Y%m%d_%H%M%S")
    backup_path = BACKUP_DIR / f"app_{ts}.db"

    try:
        shutil.copy2(db_path, backup_path)
    except Exception as e:
        _logger.error("Backup fallito: %s", e)
        raise HTTPException(500, f"Errore durante il backup: {e}")

    _logger.info("Backup database creato: %s", backup_path.name)

    backup_data = backup_path.read_bytes()
    return StreamingResponse(
        io.BytesIO(backup_data),
        media_type="application/octet-stream",
        headers={"Content-Disposition": f'attachment; filename="{backup_path.name}"'},
    )


@router.post("/maintenance/verify-db")
def verify_database(db: Session = Depends(get_db)):
    try:
        rows = db.execute(text("PRAGMA integrity_check")).fetchall()
        ok = all(row[0] == "ok" for row in rows)
        detail = "\n".join(row[0] for row in rows)
        return {"success": ok, "message": "Database integro" if ok else "Problemi rilevati", "detail": detail}
    except Exception as e:
        return {"success": False, "message": "Errore verifica", "detail": str(e)}


@router.post("/maintenance/cleanup-logs")
def cleanup_logs(keep_last: int = 200):
    removed = log_collector.clear_old(keep_last=keep_last)
    return {"success": True, "message": f"Rimossi {removed} log vecchi", "removed": removed}


@router.post("/maintenance/restart")
def restart_app():
    _logger.warning("Riavvio applicazione richiesto dall'admin")

    def _do_restart():
        time.sleep(0.8)
        os.execv(sys.executable, [sys.executable] + sys.argv)

    threading.Thread(target=_do_restart, daemon=True).start()
    return {"success": True, "message": "Riavvio in corso…"}


@router.get("/version")
def get_version():
    return {
        "version": APP_VERSION,
        "deploy_date": DEPLOY_DATE,
        "python_version": platform.python_version(),
        "platform": platform.system(),
    }


@router.get("/current-role")
def current_role():
    return {"profilo": "Admin"}


# ── Reset Inventario ──────────────────────────────────────────────────────────

@router.post("/maintenance/reset-inventario")
def reset_inventario(db: Session = Depends(get_db)):
    from backend.app.models.warehouse import (
        Material, StockMovement, WarehouseItem,
    )
    from backend.app.services.inventario import parse_inventario
    from backend.app.services.warehouse_items import reconcile_available_items

    _logger.warning("Reset inventario avviato")

    if not INVENTARIO_PATH.exists():
        raise HTTPException(404, f"File inventario non trovato: {INVENTARIO_PATH}")

    rows = parse_inventario(INVENTARIO_PATH)

    deleted = {}
    deleted["warehouse_items"]    = db.query(WarehouseItem).delete()
    deleted["stock_movements"]    = db.query(StockMovement).delete()
    deleted["materials"] = db.query(Material).delete()
    db.commit()
    _logger.info("Tabelle svuotate: %s", deleted)

    materials_created = movements_created = 0
    physical_items_created = 0

    merged: dict = {}
    for item in rows:
        code = item["material_code"]
        if code in merged:
            merged[code]["quantity"] = (merged[code].get("quantity") or 0) + (item.get("quantity") or 0)
        else:
            merged[code] = dict(item)

    for item in merged.values():
        mat = Material(
            code=item["material_code"],
            description=item["description"],
            unit="PZ",
            specification=item.get("specification"),
            tipo=item.get("tipo"),
            profilo=item.get("profilo"),
            dimensioni=item.get("dimensioni"),
            qualita=item.get("qualita"),
            colata=item.get("colata"),
            commessa_ref=None,
            peso_u_kg=item.get("peso_u_kg"),
            peso_1_pz=item.get("peso_1_pz"),
            norma_uni=item.get("norma_uni"),
            unita_misura="pz",
        )
        db.add(mat)
        db.flush()
        materials_created += 1

        qty = item.get("quantity", 0)
        if qty and qty > 0:
            db.add(StockMovement(
                material_id=mat.id,
                quantity=qty,
                movement_type="INCOMING",
                reason="Carico iniziale da inventario Excel",
            ))
            movements_created += 1
            sync = reconcile_available_items(db, mat, qty)
            physical_items_created += sync["created"]

    db.commit()
    _logger.info("Reset inventario completato: %d materiali, %d movimenti", materials_created, movements_created)

    return {
        "success": True,
        "message": f"Inventario resettato: {materials_created} materiali importati, {movements_created} movimenti creati.",
        "deleted": deleted,
        "materials_created": materials_created,
        "movements_created": movements_created,
        "physical_items_created": physical_items_created,
    }


# ── Profile Types CRUD ────────────────────────────────────────────────────────

class ProfileTypeBody(BaseModel):
    prefisso: str
    tipo: str


class ProfileTypeRead(BaseModel):
    id: int
    prefisso: str
    tipo: str
    model_config = {"from_attributes": True}


@router.get("/profile-types", response_model=list[ProfileTypeRead])
def list_profile_types(db: Session = Depends(get_db)):
    from backend.app.models.warehouse import ProfileType
    return db.query(ProfileType).order_by(ProfileType.prefisso).all()


@router.post("/profile-types", response_model=ProfileTypeRead, status_code=201)
def create_profile_type(body: ProfileTypeBody, db: Session = Depends(get_db)):
    from backend.app.models.warehouse import ProfileType
    existing = db.query(ProfileType).filter(ProfileType.prefisso == body.prefisso.upper()).first()
    if existing:
        raise HTTPException(409, f"Prefisso '{body.prefisso}' già presente")
    pt = ProfileType(prefisso=body.prefisso.upper().strip(), tipo=body.tipo.strip())
    db.add(pt)
    db.commit()
    db.refresh(pt)
    return pt


@router.patch("/profile-types/{pt_id}", response_model=ProfileTypeRead)
def update_profile_type(pt_id: int, body: ProfileTypeBody, db: Session = Depends(get_db)):
    from backend.app.models.warehouse import ProfileType
    pt = db.get(ProfileType, pt_id)
    if not pt:
        raise HTTPException(404, "Tipo profilo non trovato")
    pt.prefisso = body.prefisso.upper().strip()
    pt.tipo     = body.tipo.strip()
    db.commit()
    db.refresh(pt)
    return pt


@router.delete("/profile-types/{pt_id}", status_code=204)
def delete_profile_type(pt_id: int, db: Session = Depends(get_db)):
    from backend.app.models.warehouse import ProfileType
    pt = db.get(ProfileType, pt_id)
    if not pt:
        raise HTTPException(404, "Tipo profilo non trovato")
    db.delete(pt)
    db.commit()


# ── App Settings ──────────────────────────────────────────────────────────────

_ALLOWED_SETTINGS = {"backup_precommessa_path", "outcome_path"}


class SettingsBody(BaseModel):
    backup_precommessa_path: Optional[str] = None
    outcome_path: Optional[str] = None


@router.get("/settings")
def get_settings(db: Session = Depends(get_db)):
    from backend.app.models.settings import AppSettings
    rows = db.query(AppSettings).all()
    return {r.key: r.value for r in rows}


@router.put("/settings")
def update_settings(body: SettingsBody, db: Session = Depends(get_db)):
    from backend.app.models.settings import AppSettings
    data = {k: v for k, v in body.model_dump().items() if k in _ALLOWED_SETTINGS and v is not None}
    for key, value in data.items():
        row = db.get(AppSettings, key)
        if row:
            row.value = value
        else:
            db.add(AppSettings(key=key, value=value))
    db.commit()
    rows = db.query(AppSettings).all()
    return {r.key: r.value for r in rows}
