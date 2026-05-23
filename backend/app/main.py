from pathlib import Path

from fastapi import FastAPI
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

import backend.app.models.commessa  # noqa: F401
import backend.app.models.warehouse  # noqa: F401
from backend.app.api.api_v1.api import api_router

STATIC_DIR = Path(__file__).parent / "static"


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
        return FileResponse(STATIC_DIR / "index.html")

    return app


app = create_app()
