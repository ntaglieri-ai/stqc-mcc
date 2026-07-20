import logging
import base64
import re
from datetime import datetime
from pathlib import Path
from urllib.parse import quote

from fastapi import FastAPI, Request
from fastapi.responses import FileResponse, RedirectResponse, Response
from fastapi.staticfiles import StaticFiles

import backend.app.models.commessa   # noqa: F401
import backend.app.models.settings   # noqa: F401
import backend.app.models.user       # noqa: F401
import backend.app.models.warehouse  # noqa: F401
from backend.app.models.user import GROUP_DEFAULTS, GROUP_POSTAZIONI_DEFAULTS
from backend.app.api.api_v1.api import api_router, public_router
from backend.app.core.log_collector import log_collector  # noqa: F401 — initialises log capture
from backend.app.db.session import SessionLocal
from backend.app.models.commessa import Commessa, CommessaPostOfficinaItem, Piece
from backend.app.services.qr import generate_qr_for_payload, generate_qr_for_uuid
from backend.app.services.workstations import ensure_default_workstations, normalize_existing_workstation_qr_codes

STATIC_DIR = Path(__file__).parent / "static"
_NO_CACHE = {"Cache-Control": "no-cache, no-store, must-revalidate", "Pragma": "no-cache"}
_logger = logging.getLogger("stqc.main")


def _find_commessa_by_ref(ref: str) -> Commessa | None:
    db = SessionLocal()
    try:
        commessa = None
        if str(ref).isdigit():
            commessa = db.get(Commessa, int(ref))
        if commessa is None:
            commessa = db.query(Commessa).filter(Commessa.codice == ref).first()
        if commessa is not None:
            db.expunge(commessa)
        return commessa
    finally:
        db.close()


def _commessa_path(commessa: Commessa, page: str = "analisi") -> str:
    code = quote(str(commessa.codice), safe="")
    return f"/commesse/{code}/{page}"


def create_app() -> FastAPI:
    app = FastAPI(
        title="STQC MCC Backend",
        version="0.1.0",
        description="Modulo F1 Magazzino e importazione distinta per STQC",
    )
    app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")

    @app.get("/api/v1/warehouse/items/{item_uuid}/qr.png", include_in_schema=False)
    def legacy_public_warehouse_qr_image(item_uuid: str):
        """Compatibilità per immagini QR già referenziate dal frontend.

        Le pagine HTML non possono inviare l'header Authorization dentro <img>,
        quindi questa immagine deve restare pubblica come /qr-image.
        """
        if not re.fullmatch(r"[0-9a-f-]{36}", item_uuid, re.IGNORECASE):
            return Response(status_code=404)
        png = base64.b64decode(generate_qr_for_uuid(item_uuid.lower()))
        return Response(
            content=png,
            media_type="image/png",
            headers={"Cache-Control": "public, max-age=31536000, immutable"},
        )

    @app.get("/piece-qr-image/{piece_uuid}.png", include_in_schema=False)
    def piece_qr_image(piece_uuid: str):
        if not re.fullmatch(r"[0-9a-f-]{36}", piece_uuid, re.IGNORECASE):
            return Response(status_code=404)
        db = SessionLocal()
        try:
            piece = db.query(Piece).filter(Piece.uuid == piece_uuid.lower()).first()
            if piece is None or not piece.qr_payload:
                return Response(status_code=404)
            png = base64.b64decode(generate_qr_for_payload(piece.qr_payload))
            return Response(
                content=png,
                media_type="image/png",
                headers={"Cache-Control": "public, max-age=31536000, immutable"},
            )
        finally:
            db.close()

    @app.get("/assembly-qr-image/{commessa_id:int}/{assembly_code}.png", include_in_schema=False)
    def assembly_qr_image(commessa_id: int, assembly_code: str):
        png = base64.b64decode(generate_qr_for_payload(f"STQC:ASM:{commessa_id}:{assembly_code}"))
        return Response(
            content=png,
            media_type="image/png",
            headers={"Cache-Control": "public, max-age=31536000, immutable"},
        )

    @app.get("/post-officina-qr-image/{commessa_id:int}/{codice}.png", include_in_schema=False)
    def post_officina_qr_image(commessa_id: int, codice: str):
        db = SessionLocal()
        try:
            row = (
                db.query(CommessaPostOfficinaItem)
                .filter(
                    CommessaPostOfficinaItem.commessa_id == commessa_id,
                    CommessaPostOfficinaItem.codice == codice,
                )
                .order_by(CommessaPostOfficinaItem.revisione_id.desc(), CommessaPostOfficinaItem.id.desc())
                .first()
            )
            payload = f"STQC:POST:{commessa_id}:{row.revisione_id if row else 'NA'}:{codice}"
            png = base64.b64decode(generate_qr_for_payload(payload))
            return Response(
                content=png,
                media_type="image/png",
                headers={"Cache-Control": "public, max-age=31536000, immutable"},
            )
        finally:
            db.close()

    app.include_router(public_router, prefix="/api/v1")
    app.include_router(api_router, prefix="/api/v1")

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
            ("capoofficina",  "capoofficina",  ProfiloUtente.CAPO_OFFICINA, None),
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
                group = db.query(Group).filter(Group.name == group_name).first()
                if not group:
                    g = Group(
                        name=group_name,
                        postazioni=GROUP_POSTAZIONI_DEFAULTS.get(group_name, []),
                    )
                    db.add(g)
                    db.flush()
                    for sezione, livello in perms.items():
                        db.add(GroupPermission(group_name=group_name, sezione=sezione, livello=livello))
                    _logger.info("Gruppo '%s' creato", group_name)
                else:
                    existing_perms = {p.sezione: p for p in group.permissions}
                    for sezione, livello in perms.items():
                        perm = existing_perms.get(sezione)
                        if perm is None:
                            db.add(GroupPermission(group_name=group_name, sezione=sezione, livello=livello))
                            _logger.info("Permesso '%s/%s' creato a %s", group_name, sezione, livello)
                        elif perm.livello != livello:
                            perm.livello = livello
                            _logger.info("Permesso '%s/%s' aggiornato a %s", group_name, sezione, livello)

            for username, pwd, profilo, email in DEV_ACCOUNTS:
                user = db.query(User).filter(User.username == username).first()
                if not user:
                    # Recupera record legacy creati dalle vecchie migrazioni, es.
                    # admin@mcc.local senza username/password_hash. Questo rende
                    # il bootstrap affidabile anche su DB appena migrati da zero.
                    user = db.query(User).filter(User.email == email).first() if email else None

                if not user:
                    db.add(User(
                        username=username,
                        email=email,
                        password_hash=hash_password(pwd),
                        profilo=profilo, attivo=True,
                        password_changed_at=datetime.utcnow(),
                    ))
                    _logger.info("Account dev '%s' creato", username)
                else:
                    if user.username != username:
                        user.username = username
                        _logger.info("Username account base aggiornato a '%s'", username)
                    if email and user.email != email:
                        user.email = email
                    if not user.password_hash:
                        user.password_hash = hash_password(pwd)
                        user.password_changed_at = datetime.utcnow()
                        user.failed_attempts = 0
                        user.locked_until = None
                        user.attivo = True
                        _logger.info("Password iniziale account base '%s' impostata", username)
                    # aggiorna il profilo se è cambiato, senza toccare password già personalizzate
                    if user.profilo != profilo:
                        user.profilo = profilo
                        _logger.info("Profilo account '%s' aggiornato a %s", username, profilo.value)
            changed_workstations = ensure_default_workstations(db)
            changed_workstations += normalize_existing_workstation_qr_codes(db)
            if changed_workstations:
                _logger.info("Postazioni officina allineate: %s", changed_workstations)
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

    @app.get("/dashboard", include_in_schema=False)
    def dashboard_page():
        return FileResponse(STATIC_DIR / "commesse-lista.html", headers=_NO_CACHE)

    @app.get("/commesse/nuova", include_in_schema=False)
    def commesse_nuova_page():
        return FileResponse(STATIC_DIR / "commesse-nuova.html", headers=_NO_CACHE)

    @app.get("/commesse/{commessa_ref}/analisi", include_in_schema=False)
    def commessa_analysis_page(commessa_ref: str, request: Request):
        commessa = _find_commessa_by_ref(commessa_ref)
        if commessa and str(commessa_ref).isdigit():
            return RedirectResponse(url=_commessa_path(commessa, "analisi"), status_code=307, headers=_NO_CACHE)
        page = "commessa-analysis.html" if request.query_params.get("embed") == "1" else "commessa-shell.html"
        return FileResponse(STATIC_DIR / page, headers=_NO_CACHE)

    @app.get("/commesse/{commessa_id:int}/qr-registry", include_in_schema=False)
    def legacy_commessa_qr_registry_page(commessa_id: int):
        commessa = _find_commessa_by_ref(str(commessa_id))
        if commessa:
            return RedirectResponse(url=_commessa_path(commessa, "officina"), status_code=307, headers=_NO_CACHE)
        return RedirectResponse(url="/commesse", status_code=307, headers=_NO_CACHE)

    @app.get("/commesse/{commessa_ref}/officina", include_in_schema=False)
    def commessa_officina_page(commessa_ref: str, request: Request):
        commessa = _find_commessa_by_ref(commessa_ref)
        if commessa and str(commessa_ref).isdigit():
            return RedirectResponse(url=_commessa_path(commessa, "officina"), status_code=307, headers=_NO_CACHE)
        page = "qr-registry.html" if request.query_params.get("embed") == "1" else "commessa-shell.html"
        return FileResponse(STATIC_DIR / page, headers=_NO_CACHE)

    @app.get("/commesse/{commessa_ref}/assemblaggi", include_in_schema=False)
    def commessa_assemblaggi_page(commessa_ref: str, request: Request):
        commessa = _find_commessa_by_ref(commessa_ref)
        if commessa and str(commessa_ref).isdigit():
            return RedirectResponse(url=_commessa_path(commessa, "assemblaggi"), status_code=307, headers=_NO_CACHE)
        page = "assemblaggi.html" if request.query_params.get("embed") == "1" else "commessa-shell.html"
        return FileResponse(STATIC_DIR / page, headers=_NO_CACHE)

    @app.get("/commesse/{commessa_ref}/lavorazioni", include_in_schema=False)
    def commessa_lavorazioni_page(commessa_ref: str, request: Request):
        commessa = _find_commessa_by_ref(commessa_ref)
        if commessa and str(commessa_ref).isdigit():
            return RedirectResponse(url=_commessa_path(commessa, "lavorazioni"), status_code=307, headers=_NO_CACHE)
        page = "lavorazioni.html" if request.query_params.get("embed") == "1" else "commessa-shell.html"
        return FileResponse(STATIC_DIR / page, headers=_NO_CACHE)

    @app.get("/commesse/{commessa_ref}/in-cantiere", include_in_schema=False)
    def commessa_in_cantiere_page(commessa_ref: str, request: Request):
        commessa = _find_commessa_by_ref(commessa_ref)
        if commessa and str(commessa_ref).isdigit():
            return RedirectResponse(url=_commessa_path(commessa, "in-cantiere"), status_code=307, headers=_NO_CACHE)
        page = "in-cantiere.html" if request.query_params.get("embed") == "1" else "commessa-shell.html"
        return FileResponse(STATIC_DIR / page, headers=_NO_CACHE)

    @app.get("/commesse/{commessa_ref}", include_in_schema=False)
    def commessa_detail_page(commessa_ref: str):
        commessa = _find_commessa_by_ref(commessa_ref)
        if commessa:
            return RedirectResponse(url=_commessa_path(commessa, "analisi"), status_code=307, headers=_NO_CACHE)
        return RedirectResponse(url="/commesse", status_code=307, headers=_NO_CACHE)

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

    @app.get("/scanner-view/{device_token}", include_in_schema=False)
    def scanner_read_page(device_token: str):
        return FileResponse(STATIC_DIR / "scanner-read.html", headers=_NO_CACHE)

    @app.get("/admin", include_in_schema=False)
    def admin_page():
        return FileResponse(STATIC_DIR / "admin.html", headers=_NO_CACHE)

    return app


app = create_app()
