"""normalize workstation qr codes

Revision ID: k2l3m4n5o6p7
Revises: j1k2l3m4n5o6
Create Date: 2026-07-07
"""

from alembic import op
import sqlalchemy as sa


revision = "k2l3m4n5o6p7"
down_revision = "j1k2l3m4n5o6"
branch_labels = None
depends_on = None


WORKSTATIONS = [
    ("TAGLIO_LASER01", "Taglio Laser 01", "Taglio lamiere - laser 1"),
    ("TAGLIO_LASER02", "Taglio Laser 02", "Taglio lamiere - laser 2"),
    ("TRANCIATURA01", "Tranciatura 01", "Tranciatura lamiera"),
    ("PRESSOPIEGA01", "Pressopiega 01", "Pressopiegatura lamiere"),
    ("TAGLIO_FICEP01", "Taglio Ficep 01", "Taglio profili con sega Ficep"),
    ("FORATURA_FICEP01", "Foratura Ficep 01", "Foratura profili con Ficep"),
    ("TAGLIO_MANUALE01", "Taglio Manuale 01", "Taglio profili manuale"),
    ("ASSEMBLAGGIO_A1", "Assemblaggio A1", "Postazione assemblaggio A1"),
    ("ASSEMBLAGGIO_A2", "Assemblaggio A2", "Postazione assemblaggio A2"),
    ("ASSEMBLAGGIO_A3", "Assemblaggio A3", "Postazione assemblaggio A3"),
    ("SALDATURA_S1", "Saldatura S1", "Postazione saldatura S1"),
    ("SALDATURA_S2", "Saldatura S2", "Postazione saldatura S2"),
    ("SALDATURA_S3", "Saldatura S3", "Postazione saldatura S3"),
    ("SALDATURA_S4", "Saldatura S4", "Postazione saldatura S4"),
    ("SALDATURA_S5", "Saldatura S5", "Postazione saldatura S5"),
]


def _start(code: str) -> str:
    return f"STQC:WS:{code}:START"


def _end(code: str) -> str:
    return f"STQC:WS:{code}:END"


def upgrade() -> None:
    for code, name, description in WORKSTATIONS:
        op.execute(
            sa.text(
                """
                INSERT INTO workstations (code, name, description, active, start_qr_code, end_qr_code, created_at)
                SELECT :code, :name, :description, 1, :start_qr_code, :end_qr_code, CURRENT_TIMESTAMP
                WHERE NOT EXISTS (SELECT 1 FROM workstations WHERE code = :code)
                """
            ).bindparams(
                code=code,
                name=name,
                description=description,
                start_qr_code=_start(code),
                end_qr_code=_end(code),
            )
        )

    rows = op.get_bind().execute(sa.text("SELECT id, code FROM workstations")).fetchall()
    for row in rows:
        code = str(row.code).strip().upper().replace(" ", "_")
        op.execute(
            sa.text(
                """
                UPDATE workstations
                SET code = :code,
                    start_qr_code = :start_qr_code,
                    end_qr_code = :end_qr_code
                WHERE id = :id
                """
            ).bindparams(
                id=row.id,
                code=code,
                start_qr_code=_start(code),
                end_qr_code=_end(code),
            )
        )


def downgrade() -> None:
    rows = op.get_bind().execute(sa.text("SELECT id, code FROM workstations")).fetchall()
    for row in rows:
        code = str(row.code).strip().upper().replace(" ", "_")
        op.execute(
            sa.text(
                """
                UPDATE workstations
                SET start_qr_code = :start_qr_code,
                    end_qr_code = :end_qr_code
                WHERE id = :id
                """
            ).bindparams(
                id=row.id,
                start_qr_code=f"{code}_START",
                end_qr_code=f"{code}_END",
            )
        )
