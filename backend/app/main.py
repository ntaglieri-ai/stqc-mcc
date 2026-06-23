import logging
import base64
import re
from pathlib import Path

from fastapi import FastAPI
from fastapi.responses import FileResponse, Response
from fastapi.staticfiles import StaticFiles

import backend.app.models.commessa   # noqa: F401
import backend.app.models.settings   # noqa: F401
import backend.app.models.user       # noqa: F401
import backend.app.models.warehouse  # noqa: F401
from backend.app.models.user import GROUP_DEFAULTS, GROUP_POSTAZIONI_DEFAULTS
from backend.app.api.api_v1.api import api_router, public_router
from backend.app.core.log_collector import log_collector  # noqa: F401 — initialises log capture
from backend.app.services.qr import generate_qr_for_uuid

STATIC_DIR = Path(__file__).parent / "static"
_NO_CACHE = {"Cache-Control": "no-cache, no-store, must-revalidate", "Pragma": "no-cache"}
_logger = logging.getLogger("stqc.main")


def create_app() -> FastAPI:
    app = FastAPI(
        title="STQC MCC Backend",
        version="0.1.0",
        description="Modulo F1 Magazzino e importazione distinta per STQC",
    )
    app.include_router(public_router, prefix="/api/v1")
    app.include_router(api_router, prefix="/api/v1")
    app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")

    @app.on_event("startup")
    async def seed_default_users() -> None:
        from backend.app.core.auth import hash_password
        from backend.app.db.session import SessionLocal
        from backend.app.models.user import Group, GroupPermission, ProfiloUtente, User
        from sqlalchemy import text

        # Account di sviluppo: username / password / profilo
        DEV_ACCOUNTS = [
            ("admin",         "admin",         ProfiloUtente.ADMIN,         "admin@mcc.local"),
            ("direttore",     "direttore",     ProfiloUtente.DIRETTORE,     None),
            ("progettazione", "progettazione", ProfiloUtente.PROGETTAZIONE, None),
            ("logistica",     "logistica",     ProfiloUtente.LOGISTICA,     None),
            ("acquisti",      "acquisti",      ProfiloUtente.ACQUISTI,      None),
        ]

        db = SessionLocal()
        try:
            # Bonifica profili legacy prima che SQLAlchemy validi l'enum.
            db.execute(text("UPDATE users SET profilo='Direttore' WHERE profilo='Responsabile'"))
            db.execute(text("UPDATE users SET profilo='Logistica', attivo=0 WHERE profilo IN ('Operaio', 'Operatore') OR username='operatore'"))
            db.execute(text("DELETE FROM group_permissions WHERE group_name='Operatore'"))
            db.execute(text("DELETE FROM groups WHERE name='Operatore'"))
            db.commit()

            # Seed groups se non esistono
            for group_name, perms in GROUP_DEFAULTS.items():
                if not db.query(Group).filter(Group.name == group_name).first():
                    g = Group(
                        name=group_name,
                        postazioni=GROUP_POSTAZIONI_DEFAULTS.get(group_name, []),
                    )
                    db.add(g)
                    db.flush()
                    for sezione, livello in perms.items():
                        db.add(GroupPermission(group_name=group_name, sezione=sezione, livello=livello))
                    _logger.info("Gruppo '%s' creato", group_name)

            for username, pwd, profilo, email in DEV_ACCOUNTS:
                user = db.query(User).filter(User.username == username).first()
                if not user:
                    db.add(User(
                        username=username,
                        email=email,
                        password_hash=hash_password(pwd),
                        profilo=profilo, attivo=True,
                    ))
                    _logger.info("Account dev '%s' creato", username)
                else:
                    # aggiorna il profilo se è cambiato
                    if user.profilo != profilo:
                        user.profilo = profilo
                        _logger.info("Profilo account '%s' aggiornato a %s", username, profilo.value)
            db.commit()
        except Exception as exc:
            _logger.error("Errore nel seeding utenti: %s", exc)
            db.rollback()
        finally:
            db.close()

    @app.get("/login", include_in_schema=False)
    def login_page():
        return FileResponse(STATIC_DIR / "login.html", headers=_NO_CACHE)

    @app.get("/", include_in_schema=False)
    def root():
        return FileResponse(STATIC_DIR / "home.html", headers=_NO_CACHE)

    @app.get("/app", include_in_schema=False)
    def app_page():
        return FileResponse(STATIC_DIR / "index.html", headers=_NO_CACHE)

    @app.get("/commesse", include_in_schema=False)
    def commesse_lista_page():
        return FileResponse(STATIC_DIR / "commesse-lista.html", headers=_NO_CACHE)

    @app.get("/commesse/nuova", include_in_schema=False)
    def commesse_nuova_page():
        return FileResponse(STATIC_DIR / "commesse-nuova.html", headers=_NO_CACHE)

    @app.get("/commesse/{commessa_id}/analisi", include_in_schema=False)
    def commessa_analysis_page(commessa_id: int):
        return FileResponse(STATIC_DIR / "commessa-analysis.html", headers=_NO_CACHE)

    @app.get("/commesse/{commessa_id}", include_in_schema=False)
    def commessa_detail_page(commessa_id: int):
        return FileResponse(STATIC_DIR / "commessa-detail.html", headers=_NO_CACHE)

    @app.get("/magazzino", include_in_schema=False)
    def magazzino_page():
        return FileResponse(STATIC_DIR / "magazzino.html", headers=_NO_CACHE)

    @app.get("/p/{item_uuid}", include_in_schema=False)
    def qr_resolve_page(item_uuid: str):
        return FileResponse(STATIC_DIR / "qr-item.html", headers=_NO_CACHE)

    @app.get("/qr-image/{item_uuid}.png", include_in_schema=False)
    def qr_image(item_uuid: str):
        if not re.fullmatch(r"[0-9a-f-]{36}", item_uuid, re.IGNORECASE):
            return Response(status_code=404)
        png = base64.b64decode(generate_qr_for_uuid(item_uuid.lower()))
        return Response(
            content=png,
            media_type="image/png",
            headers={"Cache-Control": "public, max-age=31536000, immutable"},
        )

    @app.get("/officina", include_in_schema=False)
    def officina_page():
        return FileResponse(STATIC_DIR / "officina.html", headers=_NO_CACHE)

    @app.get("/admin", include_in_schema=False)
    def admin_page():
        return FileResponse(STATIC_DIR / "admin.html", headers=_NO_CACHE)

    return app


app = create_app()
