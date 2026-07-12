"""add scanner scan mode

Revision ID: n5o6p7q8r9s0
Revises: m4n5o6p7q8r9
Create Date: 2026-07-12
"""

from alembic import op
import sqlalchemy as sa


revision = "n5o6p7q8r9s0"
down_revision = "m4n5o6p7q8r9"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "scanner_devices",
        sa.Column("scan_mode", sa.String(length=30), nullable=False, server_default="OFFICINA"),
    )
    op.execute("UPDATE scanner_devices SET scan_mode = 'OFFICINA' WHERE scan_mode IS NULL")
    op.create_index("ix_scanner_devices_scan_mode", "scanner_devices", ["scan_mode"], unique=False)


def downgrade() -> None:
    op.drop_index("ix_scanner_devices_scan_mode", table_name="scanner_devices")
    op.drop_column("scanner_devices", "scan_mode")
