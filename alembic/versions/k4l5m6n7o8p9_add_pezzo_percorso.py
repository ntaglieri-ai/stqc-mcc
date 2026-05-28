"""add pezzo_percorso table

Revision ID: k4l5m6n7o8p9
Revises: j3k4l5m6n7o8
Create Date: 2026-05-28

"""
from alembic import op
import sqlalchemy as sa

revision = "k4l5m6n7o8p9"
down_revision = "j3k4l5m6n7o8"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "pezzo_percorso",
        sa.Column("id",          sa.Integer,     primary_key=True),
        sa.Column("commessa_id", sa.Integer,     sa.ForeignKey("commesse.id", ondelete="CASCADE"), nullable=False),
        sa.Column("marca_pos",   sa.String(100), nullable=False),
        sa.Column("percorso",    sa.Text,        nullable=False),
        sa.Column("updated_at",  sa.DateTime,    nullable=True),
        sa.UniqueConstraint("commessa_id", "marca_pos", name="uq_pezzo_percorso"),
    )
    op.create_index("ix_pezzo_percorso_commessa_id", "pezzo_percorso", ["commessa_id"])


def downgrade() -> None:
    op.drop_index("ix_pezzo_percorso_commessa_id", table_name="pezzo_percorso")
    op.drop_table("pezzo_percorso")
