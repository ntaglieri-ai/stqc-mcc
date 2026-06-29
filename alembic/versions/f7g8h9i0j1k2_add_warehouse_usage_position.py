"""add warehouse usage and position fields

Revision ID: f7g8h9i0j1k2
Revises: e6f7g8h9i0j1
Create Date: 2026-06-29
"""

from alembic import op
import sqlalchemy as sa


revision = "f7g8h9i0j1k2"
down_revision = "e6f7g8h9i0j1"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("materials", sa.Column("uso_materiale", sa.String(length=100), nullable=True))
    op.add_column("materials", sa.Column("posizione", sa.String(length=200), nullable=True))
    op.create_index("ix_materials_uso_materiale", "materials", ["uso_materiale"], unique=False)
    op.create_index("ix_materials_posizione", "materials", ["posizione"], unique=False)

    op.add_column("warehouse_items", sa.Column("uso_materiale", sa.String(length=100), nullable=True))
    op.add_column("warehouse_items", sa.Column("posizione", sa.String(length=200), nullable=True))
    op.create_index("ix_warehouse_items_uso_materiale", "warehouse_items", ["uso_materiale"], unique=False)
    op.create_index("ix_warehouse_items_posizione", "warehouse_items", ["posizione"], unique=False)


def downgrade() -> None:
    op.drop_index("ix_warehouse_items_posizione", table_name="warehouse_items")
    op.drop_index("ix_warehouse_items_uso_materiale", table_name="warehouse_items")
    op.drop_column("warehouse_items", "posizione")
    op.drop_column("warehouse_items", "uso_materiale")

    op.drop_index("ix_materials_posizione", table_name="materials")
    op.drop_index("ix_materials_uso_materiale", table_name="materials")
    op.drop_column("materials", "posizione")
    op.drop_column("materials", "uso_materiale")
