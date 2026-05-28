import base64
import hashlib
import hmac
import os
import re
from datetime import datetime, timedelta
from typing import Optional

import jwt
from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy.orm import Session

from backend.app.core.config import settings
from backend.app.db.session import get_db
from backend.app.models.user import User

_security = HTTPBearer(auto_error=False)
_ALGORITHM = "HS256"

_MAX_FAILED_ATTEMPTS = 5
_LOCKOUT_MINUTES = 30


def hash_password(password: str) -> str:
    salt = os.urandom(16)
    key = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, 100_000)
    return base64.b64encode(salt + key).decode("ascii")


def verify_password(plain: str, stored: str) -> bool:
    try:
        decoded = base64.b64decode(stored.encode("ascii"))
        salt, stored_key = decoded[:16], decoded[16:]
        key = hashlib.pbkdf2_hmac("sha256", plain.encode("utf-8"), salt, 100_000)
        return hmac.compare_digest(key, stored_key)
    except Exception:
        return False


def validate_password_complexity(password: str) -> list[str]:
    """Restituisce lista di errori NIS2. Lista vuota = password valida."""
    errors = []
    if len(password) < 12:
        errors.append("almeno 12 caratteri")
    if not re.search(r"[A-Z]", password):
        errors.append("almeno una lettera maiuscola")
    if not re.search(r"[a-z]", password):
        errors.append("almeno una lettera minuscola")
    if not re.search(r"\d", password):
        errors.append("almeno un numero")
    if not re.search(r"[^A-Za-z0-9]", password):
        errors.append("almeno un carattere speciale")
    return errors


def create_token(user: User) -> str:
    profilo = user.profilo.value if hasattr(user.profilo, "value") else str(user.profilo)
    payload = {
        "sub": str(user.id),
        "profilo": profilo,
        "username": user.username,
        "exp": datetime.utcnow() + timedelta(hours=settings.jwt_expire_hours),
    }
    return jwt.encode(payload, settings.jwt_secret_key, algorithm=_ALGORITHM)


def decode_token(token: str) -> dict:
    try:
        return jwt.decode(token, settings.jwt_secret_key, algorithms=[_ALGORITHM])
    except jwt.ExpiredSignatureError:
        raise HTTPException(status_code=401, detail="Sessione scaduta. Effettua nuovamente il login.")
    except jwt.InvalidTokenError:
        raise HTTPException(status_code=401, detail="Token non valido.")


def require_auth(
    credentials: Optional[HTTPAuthorizationCredentials] = Depends(_security),
    db: Session = Depends(get_db),
) -> User:
    if not credentials:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Autenticazione richiesta.")
    payload = decode_token(credentials.credentials)
    user = db.get(User, int(payload["sub"]))
    if not user or not user.attivo:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Utente non autorizzato.")
    return user


def write_audit_log(
    db: Session,
    action: str,
    user: Optional[User] = None,
    target_user_id: Optional[int] = None,
    ip: Optional[str] = None,
    details: Optional[str] = None,
) -> None:
    from backend.app.models.user import AuditLog
    entry = AuditLog(
        user_id=user.id if user else None,
        username=user.username if user else None,
        gruppo=(user.profilo.value if hasattr(user.profilo, "value") else str(user.profilo)) if user else None,
        action=action,
        target_user_id=target_user_id,
        ip_address=ip,
        details=details,
    )
    db.add(entry)
