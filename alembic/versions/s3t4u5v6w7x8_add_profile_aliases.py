"""add profile_aliases table

Revision ID: s3t4u5v6w7x8
Revises: r2s3t4u5v6w7
Create Date: 2026-05-29
"""
from alembic import op
import sqlalchemy as sa

revision = "s3t4u5v6w7x8"
down_revision = "r2s3t4u5v6w7"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "profile_aliases",
        sa.Column("id",               sa.Integer,     primary_key=True),
        sa.Column("tipo",             sa.String(100), nullable=False),
        sa.Column("profilo_distinta", sa.String(200), nullable=False),
        sa.Column("profilo_magazzino",sa.String(200), nullable=True),   # NULL = non mappato
        sa.Column("mappato",          sa.Boolean,     nullable=False, server_default="0"),
        sa.UniqueConstraint("tipo", "profilo_distinta", name="uq_profile_alias"),
    )
    op.create_index("ix_profile_aliases_tipo", "profile_aliases", ["tipo"])


def downgrade() -> None:
    op.drop_index("ix_profile_aliases_tipo", table_name="profile_aliases")
    op.drop_table("profile_aliases")
