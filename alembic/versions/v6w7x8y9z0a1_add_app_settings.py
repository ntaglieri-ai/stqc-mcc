"""add app_settings table

Revision ID: v6w7x8y9z0a1
Revises: u5v6w7x8y9z0
Create Date: 2026-06-11
"""
from alembic import op
import sqlalchemy as sa

revision = "v6w7x8y9z0a1"
down_revision = "u5v6w7x8y9z0"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "app_settings",
        sa.Column("key",   sa.String(100), primary_key=True),
        sa.Column("value", sa.Text,        nullable=True),
    )


def downgrade() -> None:
    op.drop_table("app_settings")
