from pathlib import Path
import sys
import os

# ensure repo root is on sys.path so 'backend' package imports work
ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from backend.app.db.base import Base
from backend.app.db.session import engine, SessionLocal
from backend.app.crud.distinta import create_distinta_import, create_distinta_item
from backend.app.services.distinta import parse_lista_parti, parse_distinta_file


def run_import(file_path: str):
    Base.metadata.create_all(bind=engine)
    p = Path(file_path)
    # try lista parser first
    items = parse_lista_parti(p)
    if not items:
        items = parse_distinta_file(p)
    print(f"Parsed {len(items)} items from {p.name}")

    db = SessionLocal()
    try:
        import_data = {"filename": p.name, "source_software": None, "total_items": len(items), "status": "IMPORTED" if items else "EMPTY"}
        distinta = create_distinta_import(db=db, obj_in=import_data)
        for it in items:
            create_distinta_item(db=db, obj_in={"import_id": distinta.id, **it})
        print(f"Saved import id={distinta.id} with {len(items)} items")
    finally:
        db.close()


if __name__ == "__main__":
    import sys
    if len(sys.argv) < 2:
        print("Usage: python tools/import_local.py <path-to-xls-or-xlsx>")
        raise SystemExit(1)
    run_import(sys.argv[1])
