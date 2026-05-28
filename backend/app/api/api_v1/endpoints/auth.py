import logging
from datetime import datetime, timedelta

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel
from sqlalchemy.orm import Session

from backend.app.core.auth import (
    _LOCKOUT_MINUTES,
    _MAX_FAILED_ATTEMPTS,
    create_token,
    require_auth,
    verify_password,
    write_audit_log,
)
from backend.app.db.session import get_db
from backend.app.models.user import User

_logger = logging.getLogger("stqc.auth")

router = APIRouter()


class LoginRequest(BaseModel):
    username: str
    password: str


class TokenResponse(BaseModel):
    access_token: str
    token_type:   str = "bearer"
    profilo:      str
    username:     str
    id:           int


def _profilo_str(user: User) -> str:
    return user.profilo.value if hasattr(user.profilo, "value") else str(user.profilo)


def _client_ip(request: Request) -> str:
    xff = request.headers.get("x-forwarded-for")
    return xff.split(",")[0].strip() if xff else (request.client.host if request.client else "unknown")


@router.post("/login", response_model=TokenResponse)
def login(req: LoginRequest, request: Request, db: Session = Depends(get_db)):
    ip = _client_ip(request)

    user = db.query(User).filter(User.username == req.username).first()

    # Account bloccato
    if user and user.locked_until and user.locked_until > datetime.utcnow():
        remaining = max(1, int((user.locked_until - datetime.utcnow()).total_seconds() / 60) + 1)
        write_audit_log(db, "LOGIN_BLOCKED", user=user, ip=ip,
                        details=f"Account bloccato per altri {remaining} min")
        db.commit()
        raise HTTPException(423, f"Account bloccato. Riprovare tra {remaining} minuti.")

    # Credenziali errate
    if not user or not user.password_hash or not verify_password(req.password, user.password_hash):
        if user:
            user.failed_attempts = (user.failed_attempts or 0) + 1
            if user.failed_attempts >= _MAX_FAILED_ATTEMPTS:
                user.locked_until = datetime.utcnow() + timedelta(minutes=_LOCKOUT_MINUTES)
                write_audit_log(db, "ACCOUNT_LOCKED", user=user, ip=ip,
                                details=f"Bloccato dopo {user.failed_attempts} tentativi falliti")
            else:
                write_audit_log(db, "LOGIN_FAIL", user=user, ip=ip,
                                details=f"Tentativo {user.failed_attempts}/{_MAX_FAILED_ATTEMPTS}")
            db.commit()
        else:
            _logger.warning("Login fallito per username sconosciuto '%s' da %s", req.username, ip)
        raise HTTPException(401, "Username o password non corretti")

    if not user.attivo:
        write_audit_log(db, "LOGIN_DISABLED", user=user, ip=ip)
        db.commit()
        raise HTTPException(403, "Account disattivato")

    # Login riuscito — reset tentativi
    user.failed_attempts = 0
    user.locked_until    = None
    user.ultimo_accesso  = datetime.utcnow()
    if not user.password_changed_at:
        user.password_changed_at = datetime.utcnow()
    write_audit_log(db, "LOGIN_OK", user=user, ip=ip)
    db.commit()

    _logger.info("Login: %s [%s] da %s", user.username, _profilo_str(user), ip)
    return TokenResponse(
        access_token=create_token(user),
        profilo=_profilo_str(user),
        username=user.username or user.profilo.value,
        id=user.id,
    )


@router.get("/me")
def me(current_user: User = Depends(require_auth)):
    return {
        "id":       current_user.id,
        "username": current_user.username,
        "profilo":  _profilo_str(current_user),
        "attivo":   current_user.attivo,
    }
