"""add postazione to scan_eventi

Revision ID: u5v6w7x8y9z0
Revises: t4u5v6w7x8y9
Create Date: 2026-05-29
"""
from alembic import op
import sqlalchemy as sa

revision = "u5v6w7x8y9z0"
down_revision = "t4u5v6w7x8y9"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("scan_eventi") as batch_op:
        batch_op.add_column(sa.Column("postazione", sa.String(100), nullable=True))
        batch_op.create_index("ix_scan_eventi_postazione", ["postazione"])


def downgrade() -> None:
    with op.batch_alter_table("scan_eventi", recreate="always") as batch_op:
        batch_op.drop_index("ix_scan_eventi_postazione")
        batch_op.drop_column("postazione")
