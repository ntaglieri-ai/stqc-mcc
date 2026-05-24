from pathlib import Path

from fastapi import FastAPI
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

import backend.app.models.commessa  # noqa: F401
import backend.app.models.warehouse  # noqa: F401
from backend.app.api.api_v1.api import api_router

STATIC_DIR = Path(__file__).parent / "static"
_NO_CACHE = {"Cache-Control": "no-cache, no-store, must-revalidate", "Pragma": "no-cache"}


def create_app() -> FastAPI:
    app = FastAPI(
        title="STQC MCC Backend",
        version="0.1.0",
        description="Modulo F1 Magazzino e importazione distinta per STQC",
    )
    app.include_router(api_router, prefix="/api/v1")
    app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")

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

    return app


app = create_app()
