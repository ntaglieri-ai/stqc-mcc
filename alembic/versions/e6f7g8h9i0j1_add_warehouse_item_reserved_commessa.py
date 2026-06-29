"""add warehouse item reserved commessa

Revision ID: e6f7g8h9i0j1
Revises: d5e6f7g8h9i0
Create Date: 2026-06-24
"""

from alembic import op
import sqlalchemy as sa


revision = "e6f7g8h9i0j1"
down_revision = "d5e6f7g8h9i0"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("warehouse_items", sa.Column("reserved_for_commessa", sa.String(length=200), nullable=True))
    op.create_index(
        "ix_warehouse_items_reserved_for_commessa",
        "warehouse_items",
        ["reserved_for_commessa"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index("ix_warehouse_items_reserved_for_commessa", table_name="warehouse_items")
    op.drop_column("warehouse_items", "reserved_for_commessa")
