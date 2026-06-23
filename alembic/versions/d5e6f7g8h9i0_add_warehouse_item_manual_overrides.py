"""add warehouse item manual overrides

Revision ID: d5e6f7g8h9i0
Revises: c4d5e6f7g8h9
Create Date: 2026-06-23
"""

from alembic import op
import sqlalchemy as sa


revision = "d5e6f7g8h9i0"
down_revision = "c4d5e6f7g8h9"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("warehouse_items", sa.Column("tipo", sa.String(length=100), nullable=True))
    op.add_column("warehouse_items", sa.Column("profilo", sa.String(length=200), nullable=True))
    op.add_column("warehouse_items", sa.Column("dimensioni", sa.String(length=200), nullable=True))
    op.add_column("warehouse_items", sa.Column("norma_uni", sa.String(length=50), nullable=True))
    op.add_column("warehouse_items", sa.Column("qualita", sa.String(length=100), nullable=True))
    op.add_column("warehouse_items", sa.Column("colata", sa.String(length=100), nullable=True))
    op.add_column("warehouse_items", sa.Column("commessa_ref", sa.String(length=200), nullable=True))
    op.add_column("warehouse_items", sa.Column("peso_u_kg", sa.Numeric(12, 4), nullable=True))
    op.add_column("warehouse_items", sa.Column("peso_1_pz", sa.Numeric(12, 4), nullable=True))
    op.add_column("warehouse_items", sa.Column("notes", sa.Text(), nullable=True))
    op.add_column("warehouse_items", sa.Column("updated_at", sa.DateTime(), nullable=True))


def downgrade() -> None:
    op.drop_column("warehouse_items", "updated_at")
    op.drop_column("warehouse_items", "notes")
    op.drop_column("warehouse_items", "peso_1_pz")
    op.drop_column("warehouse_items", "peso_u_kg")
    op.drop_column("warehouse_items", "commessa_ref")
    op.drop_column("warehouse_items", "colata")
    op.drop_column("warehouse_items", "qualita")
    op.drop_column("warehouse_items", "norma_uni")
    op.drop_column("warehouse_items", "dimensioni")
    op.drop_column("warehouse_items", "profilo")
    op.drop_column("warehouse_items", "tipo")
