"""add scanner material assignment fields

Revision ID: h9i0j1k2l3m4
Revises: g8h9i0j1k2l3
Create Date: 2026-07-02
"""

from alembic import op
import sqlalchemy as sa


revision = "h9i0j1k2l3m4"
down_revision = "g8h9i0j1k2l3"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("warehouse_items") as batch:
        batch.add_column(sa.Column("reserved_at", sa.DateTime(), nullable=True))
        batch.add_column(sa.Column("reserved_by_scanner_id", sa.Integer(), nullable=True))
        batch.create_foreign_key(
            "fk_warehouse_items_reserved_by_scanner",
            "scanner_devices",
            ["reserved_by_scanner_id"],
            ["id"],
            ondelete="SET NULL",
        )
        batch.create_index("ix_warehouse_items_reserved_at", ["reserved_at"])
        batch.create_index("ix_warehouse_items_reserved_by_scanner_id", ["reserved_by_scanner_id"])

    with op.batch_alter_table("scanner_devices") as batch:
        batch.add_column(sa.Column("current_warehouse_item_id", sa.Integer(), nullable=True))
        batch.add_column(sa.Column("current_warehouse_item_set_at", sa.DateTime(), nullable=True))
        batch.create_foreign_key(
            "fk_scanner_devices_current_warehouse_item",
            "warehouse_items",
            ["current_warehouse_item_id"],
            ["id"],
            ondelete="SET NULL",
        )
        batch.create_index("ix_scanner_devices_current_warehouse_item_id", ["current_warehouse_item_id"])

    with op.batch_alter_table("pieces") as batch:
        batch.create_foreign_key(
            "fk_pieces_materiale_origine",
            "warehouse_items",
            ["materiale_origine_id"],
            ["id"],
            ondelete="SET NULL",
        )
        batch.add_column(sa.Column("materiale_origine_assigned_at", sa.DateTime(), nullable=True))
        batch.add_column(sa.Column("materiale_origine_scanner_id", sa.Integer(), nullable=True))
        batch.create_foreign_key(
            "fk_pieces_materiale_origine_scanner",
            "scanner_devices",
            ["materiale_origine_scanner_id"],
            ["id"],
            ondelete="SET NULL",
        )
        batch.create_index("ix_pieces_materiale_origine_id", ["materiale_origine_id"])
        batch.create_index("ix_pieces_materiale_origine_assigned_at", ["materiale_origine_assigned_at"])
        batch.create_index("ix_pieces_materiale_origine_scanner_id", ["materiale_origine_scanner_id"])


def downgrade() -> None:
    with op.batch_alter_table("pieces") as batch:
        batch.drop_index("ix_pieces_materiale_origine_scanner_id")
        batch.drop_index("ix_pieces_materiale_origine_assigned_at")
        batch.drop_index("ix_pieces_materiale_origine_id")
        batch.drop_constraint("fk_pieces_materiale_origine_scanner", type_="foreignkey")
        batch.drop_column("materiale_origine_scanner_id")
        batch.drop_column("materiale_origine_assigned_at")
        batch.drop_constraint("fk_pieces_materiale_origine", type_="foreignkey")

    with op.batch_alter_table("scanner_devices") as batch:
        batch.drop_index("ix_scanner_devices_current_warehouse_item_id")
        batch.drop_constraint("fk_scanner_devices_current_warehouse_item", type_="foreignkey")
        batch.drop_column("current_warehouse_item_set_at")
        batch.drop_column("current_warehouse_item_id")

    with op.batch_alter_table("warehouse_items") as batch:
        batch.drop_index("ix_warehouse_items_reserved_by_scanner_id")
        batch.drop_index("ix_warehouse_items_reserved_at")
        batch.drop_constraint("fk_warehouse_items_reserved_by_scanner", type_="foreignkey")
        batch.drop_column("reserved_by_scanner_id")
        batch.drop_column("reserved_at")
