import os
from pathlib import Path

from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    project_name: str = "STQC MCC Backend"
    api_v1_prefix: str = "/api/v1"
    database_url: str = os.getenv("DATABASE_URL", "sqlite:///./backend/app.db")
    upload_dir: Path = Path(os.getenv("UPLOAD_DIR", "./uploads"))
    jwt_secret_key: str = os.getenv("JWT_SECRET_KEY", "stqc-mcc-jwt-secret-change-in-production")
    jwt_expire_hours: int = int(os.getenv("JWT_EXPIRE_HOURS", "8"))


settings = Settings()
