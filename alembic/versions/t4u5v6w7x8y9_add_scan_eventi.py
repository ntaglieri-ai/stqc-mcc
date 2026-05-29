"""add scan_eventi table

Revision ID: t4u5v6w7x8y9
Revises: s3t4u5v6w7x8
Create Date: 2026-05-29
"""
from alembic import op
import sqlalchemy as sa

revision = "t4u5v6w7x8y9"
down_revision = "s3t4u5v6w7x8"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "scan_eventi",
        sa.Column("id",          sa.Integer,    primary_key=True),
        sa.Column("item_uuid",   sa.String(36), nullable=False),
        sa.Column("utente_id",   sa.Integer,    sa.ForeignKey("users.id",          ondelete="SET NULL"), nullable=True),
        sa.Column("fase_id",     sa.Integer,    sa.ForeignKey("fasi_operative.id", ondelete="SET NULL"), nullable=True),
        sa.Column("timestamp",   sa.DateTime,   nullable=False, server_default=sa.func.now()),
        sa.Column("tipo_evento", sa.String(20), nullable=False),
    )
    op.create_index("ix_scan_eventi_item_uuid", "scan_eventi", ["item_uuid"])
    op.create_index("ix_scan_eventi_utente",    "scan_eventi", ["utente_id"])


def downgrade() -> None:
    op.drop_index("ix_scan_eventi_utente",    table_name="scan_eventi")
    op.drop_index("ix_scan_eventi_item_uuid", table_name="scan_eventi")
    op.drop_table("scan_eventi")
