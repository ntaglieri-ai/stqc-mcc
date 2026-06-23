"""add scanner devices and workstation seed

Revision ID: c4d5e6f7g8h9
Revises: b3c4d5e6f7g8
Create Date: 2026-06-23
"""

from alembic import op
import sqlalchemy as sa


revision = "c4d5e6f7g8h9"
down_revision = "b3c4d5e6f7g8"
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

LEGACY_WORKSTATIONS = (
    "TAGLIO01",
    "FORATURA01",
    "SALDATURA01",
    "ASS01",
    "VERNICIATURA01",
    "SPEDIZIONE01",
)


def upgrade() -> None:
    op.create_table(
        "scanner_devices",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("scanner_code", sa.String(length=80), nullable=False),
        sa.Column("name", sa.String(length=160), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("postazione_id", sa.Integer(), nullable=True),
        sa.Column("ip_address", sa.String(length=80), nullable=True),
        sa.Column("serial_number", sa.String(length=120), nullable=True),
        sa.Column("device_token", sa.String(length=160), nullable=True),
        sa.Column("active", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("last_seen_at", sa.DateTime(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=True),
        sa.Column("updated_at", sa.DateTime(), nullable=True),
        sa.ForeignKeyConstraint(["postazione_id"], ["workstations.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("scanner_code"),
        sa.UniqueConstraint("device_token"),
    )
    op.create_index("ix_scanner_devices_id", "scanner_devices", ["id"])
    op.create_index("ix_scanner_devices_scanner_code", "scanner_devices", ["scanner_code"], unique=True)
    op.create_index("ix_scanner_devices_postazione_id", "scanner_devices", ["postazione_id"])
    op.create_index("ix_scanner_devices_ip_address", "scanner_devices", ["ip_address"])
    op.create_index("ix_scanner_devices_serial_number", "scanner_devices", ["serial_number"])
    op.create_index("ix_scanner_devices_device_token", "scanner_devices", ["device_token"], unique=True)
    op.create_index("ix_scanner_devices_active", "scanner_devices", ["active"])
    op.create_index("ix_scanner_devices_last_seen_at", "scanner_devices", ["last_seen_at"])

    _seed_workstations()
    _deactivate_legacy_workstations()


def downgrade() -> None:
    op.drop_table("scanner_devices")


def _seed_workstations() -> None:
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
                start_qr_code=f"{code}_START",
                end_qr_code=f"{code}_END",
            )
        )
        op.execute(
            sa.text(
                """
                UPDATE workstations
                SET name = :name,
                    description = :description,
                    active = 1,
                    start_qr_code = :start_qr_code,
                    end_qr_code = :end_qr_code
                WHERE code = :code
                """
            ).bindparams(
                code=code,
                name=name,
                description=description,
                start_qr_code=f"{code}_START",
                end_qr_code=f"{code}_END",
            )
        )


def _deactivate_legacy_workstations() -> None:
    for code in LEGACY_WORKSTATIONS:
        op.execute(
            sa.text("UPDATE workstations SET active = 0 WHERE code = :code").bindparams(code=code)
        )
