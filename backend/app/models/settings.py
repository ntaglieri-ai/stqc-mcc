from sqlalchemy import Column, String, Text

from backend.app.db.base import Base


class AppSettings(Base):
    """Tabella chiave-valore per configurazione applicazione."""
    __tablename__ = "app_settings"

    key   = Column(String(100), primary_key=True)
    value = Column(Text, nullable=True)
