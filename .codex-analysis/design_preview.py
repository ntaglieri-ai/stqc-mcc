from fastapi import FastAPI, Request
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse
from sqlalchemy import create_engine
from sqlalchemy.pool import StaticPool
from sqlalchemy.orm import Session
from backend.app.api.api_v1.endpoints.commessa import router
from backend.app.db.session import get_db
from backend.app.db.base import Base
import backend.app.models.user
engine=create_engine("sqlite:///.codex-analysis/design-preview.db",connect_args={"check_same_thread":False})
Base.metadata.create_all(engine)
from backend.app.models.commessa import Commessa
with Session(engine) as seed:
    if not seed.query(Commessa).filter_by(codice="26_TEST").first():
        seed.add(Commessa(codice="26_TEST", descrizione="Commessa di verifica", cliente="Cliente prova"))
    seed.commit()
app=FastAPI()
def db():
    with Session(engine) as session: yield session
app.dependency_overrides[get_db]=db
app.include_router(router,prefix="/api/v1/commesse")
app.mount("/static",StaticFiles(directory="backend/app/static"),name="static")
@app.get("/commesse/nuova")
def new(): return FileResponse("backend/app/static/commesse-nuova.html")
@app.get("/commesse/{code}/{view}")
def page(code:str,view:str,request:Request):
    pages={"analisi":"commessa-analysis.html","progettazione":"commessa-progettazione.html"}
    return FileResponse("backend/app/static/"+(pages.get(view,"qr-registry.html") if request.query_params.get("embed")=="1" else "commessa-shell.html"))

@app.get("/dashboard")
def dashboard(): return FileResponse("backend/app/static/dashboard.html")
@app.get("/dashboard/monitoring")
@app.get("/dashboard/statistiche-reportistica")
def dashboard_section(): return FileResponse("backend/app/static/dashboard-section.html")
@app.get("/preview-dashboard")
def preview_dashboard():
    from fastapi.responses import HTMLResponse
    return HTMLResponse('<script>sessionStorage.setItem("stqc_token","preview-only");sessionStorage.setItem("stqc_profilo","Progettazione");location.replace("/dashboard")</script>')
