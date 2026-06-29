"""add warehouse custom fields

Revision ID: g8h9i0j1k2l3
Revises: f7g8h9i0j1k2
Create Date: 2026-06-29
"""

from alembic import op
import sqlalchemy as sa


revision = "g8h9i0j1k2l3"
down_revision = "f7g8h9i0j1k2"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "warehouse_custom_fields",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("key", sa.String(length=100), nullable=False),
        sa.Column("label", sa.String(length=200), nullable=False),
        sa.Column("value_type", sa.String(length=30), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("key"),
    )
    op.create_index("ix_warehouse_custom_fields_id", "warehouse_custom_fields", ["id"], unique=False)
    op.create_index("ix_warehouse_custom_fields_key", "warehouse_custom_fields", ["key"], unique=True)

    op.create_table(
        "warehouse_custom_values",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("material_id", sa.Integer(), nullable=False),
        sa.Column("field_id", sa.Integer(), nullable=False),
        sa.Column("value", sa.Text(), nullable=True),
        sa.ForeignKeyConstraint(["field_id"], ["warehouse_custom_fields.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["material_id"], ["materials.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("material_id", "field_id", name="uq_warehouse_custom_value"),
    )
    op.create_index("ix_warehouse_custom_values_field_id", "warehouse_custom_values", ["field_id"], unique=False)
    op.create_index("ix_warehouse_custom_values_id", "warehouse_custom_values", ["id"], unique=False)
    op.create_index("ix_warehouse_custom_values_material_id", "warehouse_custom_values", ["material_id"], unique=False)


def downgrade() -> None:
    op.drop_index("ix_warehouse_custom_values_material_id", table_name="warehouse_custom_values")
    op.drop_index("ix_warehouse_custom_values_id", table_name="warehouse_custom_values")
    op.drop_index("ix_warehouse_custom_values_field_id", table_name="warehouse_custom_values")
    op.drop_table("warehouse_custom_values")

    op.drop_index("ix_warehouse_custom_fields_key", table_name="warehouse_custom_fields")
    op.drop_index("ix_warehouse_custom_fields_id", table_name="warehouse_custom_fields")
    op.drop_table("warehouse_custom_fields")
