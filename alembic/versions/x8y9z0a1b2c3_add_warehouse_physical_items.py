"""add warehouse physical items

Revision ID: x8y9z0a1b2c3
Revises: w7x8y9z0a1b2
Create Date: 2026-06-12
"""
from datetime import datetime
import uuid

from alembic import op
import sqlalchemy as sa


revision = "x8y9z0a1b2c3"
down_revision = "w7x8y9z0a1b2"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "warehouse_items",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("uuid", sa.String(length=36), nullable=False),
        sa.Column("material_id", sa.Integer(), nullable=False),
        sa.Column("ordinal", sa.Integer(), nullable=False),
        sa.Column("status", sa.String(length=20), nullable=False, server_default="AVAILABLE"),
        sa.Column("source_movement_id", sa.Integer(), nullable=True),
        sa.Column("exit_movement_id", sa.Integer(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("exited_at", sa.DateTime(), nullable=True),
        sa.ForeignKeyConstraint(["exit_movement_id"], ["stock_movements.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["material_id"], ["materials.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["source_movement_id"], ["stock_movements.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("material_id", "ordinal", name="uq_warehouse_item_ordinal"),
        sa.UniqueConstraint("uuid"),
    )
    op.create_index(op.f("ix_warehouse_items_exit_movement_id"), "warehouse_items", ["exit_movement_id"])
    op.create_index(op.f("ix_warehouse_items_id"), "warehouse_items", ["id"])
    op.create_index(op.f("ix_warehouse_items_material_id"), "warehouse_items", ["material_id"])
    op.create_index(op.f("ix_warehouse_items_source_movement_id"), "warehouse_items", ["source_movement_id"])
    op.create_index(op.f("ix_warehouse_items_status"), "warehouse_items", ["status"])
    op.create_index(op.f("ix_warehouse_items_uuid"), "warehouse_items", ["uuid"], unique=True)

    bind = op.get_bind()
    rows = bind.execute(sa.text("""
        SELECT m.id AS material_id,
               COALESCE(SUM(CASE
                   WHEN sm.movement_type = 'INCOMING' THEN sm.quantity
                   WHEN sm.movement_type IN ('OUTGOING', 'SFRIDO') THEN -sm.quantity
                   WHEN sm.movement_type = 'ADJUSTMENT' THEN sm.quantity
                   ELSE 0 END), 0) AS balance
        FROM materials m
        LEFT JOIN stock_movements sm ON sm.material_id = m.id
        GROUP BY m.id
    """)).mappings().all()
    now = datetime.utcnow()
    for row in rows:
        quantity = max(0, int(float(row["balance"] or 0)))
        if quantity == 0:
            continue
        bind.execute(
            sa.text("""
                INSERT INTO warehouse_items
                    (uuid, material_id, ordinal, status, created_at)
                VALUES
                    (:uuid, :material_id, :ordinal, 'AVAILABLE', :created_at)
            """),
            [
                {
                    "uuid": str(uuid.uuid4()),
                    "material_id": row["material_id"],
                    "ordinal": ordinal,
                    "created_at": now,
                }
                for ordinal in range(1, quantity + 1)
            ],
        )


def downgrade() -> None:
    op.drop_index(op.f("ix_warehouse_items_uuid"), table_name="warehouse_items")
    op.drop_index(op.f("ix_warehouse_items_status"), table_name="warehouse_items")
    op.drop_index(op.f("ix_warehouse_items_source_movement_id"), table_name="warehouse_items")
    op.drop_index(op.f("ix_warehouse_items_material_id"), table_name="warehouse_items")
    op.drop_index(op.f("ix_warehouse_items_id"), table_name="warehouse_items")
    op.drop_index(op.f("ix_warehouse_items_exit_movement_id"), table_name="warehouse_items")
    op.drop_table("warehouse_items")
