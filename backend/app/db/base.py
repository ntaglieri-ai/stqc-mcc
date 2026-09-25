from sqlalchemy.orm import declarative_base

Base = declarative_base()

# Register shared capture for the existing event models, including non-HTTP writers.
from backend.app.services import event_details  # noqa: E402,F401
