"""add uuid weight_kg invalidato revisione_id to distinta_items

Revision ID: o2p3q4r5s6t7
Revises: n1o2p3q4r5s6
Create Date: 2026-05-28
"""
from alembic import op
import sqlalchemy as sa

revision = "o2p3q4r5s6t7"
down_revision = "n1o2p3q4r5s6"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Fase 1: aggiungi colonne nullable
    # Nota: in SQLite i FK non sono enforced — aggiungiamo revisione_id come Integer semplice
    with op.batch_alter_table("distinta_items") as batch_op:
        batch_op.add_column(sa.Column("uuid", sa.String(36), nullable=True))
        batch_op.add_column(sa.Column("weight_kg", sa.Numeric(12, 4), nullable=True))
        batch_op.add_column(sa.Column("invalidato", sa.Boolean, nullable=False, server_default="0"))
        batch_op.add_column(sa.Column("revisione_id", sa.Integer, nullable=True))

    # Fase 2: backfill UUID v4 per righe esistenti (SQLite)
    op.execute(
        "UPDATE distinta_items SET uuid = lower(hex(randomblob(4))) || '-' || "
        "lower(hex(randomblob(2))) || '-4' || lower(substr(hex(randomblob(2)),2)) || '-' || "
        "lower(substr('89ab', (abs(random()) % 4) + 1, 1)) || "
        "lower(substr(hex(randomblob(2)),2)) || '-' || lower(hex(randomblob(6))) "
        "WHERE uuid IS NULL"
    )

    # Fase 3: rende uuid NOT NULL e aggiunge vincolo univoco
    with op.batch_alter_table("distinta_items", recreate="always") as batch_op:
        batch_op.alter_column("uuid", nullable=False)
        batch_op.create_unique_constraint("uq_distinta_item_uuid", ["uuid"])
        batch_op.create_index("ix_distinta_item_uuid", ["uuid"])


def downgrade() -> None:
    with op.batch_alter_table("distinta_items", recreate="always") as batch_op:
        batch_op.drop_index("ix_distinta_item_uuid")
        batch_op.drop_constraint("uq_distinta_item_uuid", type_="unique")
        batch_op.drop_column("uuid")
        batch_op.drop_column("weight_kg")
        batch_op.drop_column("invalidato")
        batch_op.drop_column("revisione_id")
