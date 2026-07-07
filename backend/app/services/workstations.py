from __future__ import annotations

from dataclasses import dataclass

from sqlalchemy.orm import Session

from backend.app.models.commessa import Workstation


QR_PREFIX = "STQC:WS"


@dataclass(frozen=True)
class DefaultWorkstation:
    code: str
    name: str
    description: str


DEFAULT_WORKSTATIONS: tuple[DefaultWorkstation, ...] = (
    DefaultWorkstation("TAGLIO_LASER01", "Taglio Laser 01", "Taglio lamiere - laser 1"),
    DefaultWorkstation("TAGLIO_LASER02", "Taglio Laser 02", "Taglio lamiere - laser 2"),
    DefaultWorkstation("TRANCIATURA01", "Tranciatura 01", "Tranciatura lamiera"),
    DefaultWorkstation("PRESSOPIEGA01", "Pressopiega 01", "Pressopiegatura lamiere"),
    DefaultWorkstation("TAGLIO_FICEP01", "Taglio Ficep 01", "Taglio profili con sega Ficep"),
    DefaultWorkstation("FORATURA_FICEP01", "Foratura Ficep 01", "Foratura profili con Ficep"),
    DefaultWorkstation("TAGLIO_MANUALE01", "Taglio Manuale 01", "Taglio profili manuale"),
    DefaultWorkstation("ASSEMBLAGGIO_A1", "Assemblaggio A1", "Postazione assemblaggio A1"),
    DefaultWorkstation("ASSEMBLAGGIO_A2", "Assemblaggio A2", "Postazione assemblaggio A2"),
    DefaultWorkstation("ASSEMBLAGGIO_A3", "Assemblaggio A3", "Postazione assemblaggio A3"),
    DefaultWorkstation("SALDATURA_S1", "Saldatura S1", "Postazione saldatura S1"),
    DefaultWorkstation("SALDATURA_S2", "Saldatura S2", "Postazione saldatura S2"),
    DefaultWorkstation("SALDATURA_S3", "Saldatura S3", "Postazione saldatura S3"),
    DefaultWorkstation("SALDATURA_S4", "Saldatura S4", "Postazione saldatura S4"),
    DefaultWorkstation("SALDATURA_S5", "Saldatura S5", "Postazione saldatura S5"),
)


def normalize_workstation_code(code: str) -> str:
    return (code or "").strip().upper().replace(" ", "_")


def workstation_qr_codes(code: str) -> tuple[str, str]:
    clean = normalize_workstation_code(code)
    return f"{QR_PREFIX}:{clean}:START", f"{QR_PREFIX}:{clean}:END"


def ensure_default_workstations(db: Session) -> int:
    """Seed/configura le postazioni base e allinea i payload QR canonici.

    Ritorna il numero di righe create o aggiornate.
    """
    changed = 0
    for item in DEFAULT_WORKSTATIONS:
        start_qr_code, end_qr_code = workstation_qr_codes(item.code)
        ws = db.query(Workstation).filter(Workstation.code == item.code).first()
        if not ws:
            db.add(
                Workstation(
                    code=item.code,
                    name=item.name,
                    description=item.description,
                    active=True,
                    start_qr_code=start_qr_code,
                    end_qr_code=end_qr_code,
                )
            )
            changed += 1
            continue

        if ws.start_qr_code != start_qr_code or ws.end_qr_code != end_qr_code:
            ws.start_qr_code = start_qr_code
            ws.end_qr_code = end_qr_code
            changed += 1
    return changed


def normalize_existing_workstation_qr_codes(db: Session) -> int:
    changed = 0
    for ws in db.query(Workstation).all():
        start_qr_code, end_qr_code = workstation_qr_codes(ws.code)
        if ws.start_qr_code != start_qr_code or ws.end_qr_code != end_qr_code:
            ws.start_qr_code = start_qr_code
            ws.end_qr_code = end_qr_code
            changed += 1
    return changed
