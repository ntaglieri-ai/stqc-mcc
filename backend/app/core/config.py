import os
from pathlib import Path

from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    project_name: str = "STQC MCC Backend"
    api_v1_prefix: str = "/api/v1"
    database_url: str = os.getenv("DATABASE_URL", "sqlite:///./backend/app.db")
    upload_dir: Path = Path(os.getenv("UPLOAD_DIR", "./uploads"))
    # Credenziali HTTP Basic — cambiarle via env var in produzione
    api_username: str = os.getenv("API_USERNAME", "mcc")
    api_password: str = os.getenv("API_PASSWORD", "stqc2026")


settings = Settings()
