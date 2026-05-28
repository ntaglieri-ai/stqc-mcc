"""rebuild pezzo_percorso as tracking table

Revision ID: l5m6n7o8p9q0
Revises: k4l5m6n7o8p9
Create Date: 2026-05-28

Old structure: (commessa_id, marca_pos, percorso JSON)
New structure:  per-item × per-fase tracking rows with stato
"""
from alembic import op
import sqlalchemy as sa

revision = "l5m6n7o8p9q0"
down_revision = "k4l5m6n7o8p9"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.drop_table("pezzo_percorso")

    op.create_table(
        "pezzo_percorso",
        sa.Column("id",          sa.Integer,     primary_key=True),
        sa.Column("commessa_id", sa.Integer,     sa.ForeignKey("commesse.id", ondelete="CASCADE"), nullable=False),
        sa.Column("item_id",     sa.Integer,     sa.ForeignKey("distinta_items.id", ondelete="SET NULL"), nullable=True),
        sa.Column("fase_id",     sa.Integer,     sa.ForeignKey("fasi_operative.id", ondelete="CASCADE"), nullable=False),
        sa.Column("marca_pos",   sa.String(100), nullable=False),
        sa.Column("sequenza",    sa.Integer,     nullable=True),
        sa.Column("stato",       sa.String(20),  nullable=False, server_default="BLOCCATA"),
        sa.Column("postazione",  sa.String(100), nullable=True),
        sa.UniqueConstraint("commessa_id", "marca_pos", "fase_id", name="uq_pezzo_percorso"),
    )
    op.create_index("ix_pezzo_percorso_commessa_id", "pezzo_percorso", ["commessa_id"])
    op.create_index("ix_pezzo_percorso_item_id",     "pezzo_percorso", ["item_id"])
    op.create_index("ix_pezzo_percorso_fase_id",     "pezzo_percorso", ["fase_id"])


def downgrade() -> None:
    op.drop_index("ix_pezzo_percorso_fase_id",     table_name="pezzo_percorso")
    op.drop_index("ix_pezzo_percorso_item_id",     table_name="pezzo_percorso")
    op.drop_index("ix_pezzo_percorso_commessa_id", table_name="pezzo_percorso")
    op.drop_table("pezzo_percorso")

    op.create_table(
        "pezzo_percorso",
        sa.Column("id",          sa.Integer,     primary_key=True),
        sa.Column("commessa_id", sa.Integer,     sa.ForeignKey("commesse.id", ondelete="CASCADE"), nullable=False),
        sa.Column("marca_pos",   sa.String(100), nullable=False),
        sa.Column("percorso",    sa.Text,        nullable=False),
        sa.Column("updated_at",  sa.DateTime,    nullable=True),
        sa.UniqueConstraint("commessa_id", "marca_pos", name="uq_pezzo_percorso"),
    )
