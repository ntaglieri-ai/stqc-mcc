"""add warehouse change requests

Revision ID: o20260916_warehouse_change_requests
Revises: n20260908_station_qr
Create Date: 2026-09-16
"""

from alembic import op
import sqlalchemy as sa


revision = "o20260916_warehouse_change_requests"
down_revision = "n20260908_station_qr"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "warehouse_change_requests",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("status", sa.Enum("PENDING", "APPLIED", "REJECTED", "FAILED", name="warehousechangerequeststatus"), nullable=False),
        sa.Column("action", sa.String(length=80), nullable=False),
        sa.Column("title", sa.String(length=240), nullable=False),
        sa.Column("summary", sa.Text(), nullable=True),
        sa.Column("payload", sa.JSON(), nullable=False),
        sa.Column("result", sa.JSON(), nullable=True),
        sa.Column("error", sa.Text(), nullable=True),
        sa.Column("created_by_user_id", sa.Integer(), nullable=True),
        sa.Column("created_by_username", sa.String(length=100), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("applied_by_user_id", sa.Integer(), nullable=True),
        sa.Column("applied_by_username", sa.String(length=100), nullable=True),
        sa.Column("applied_at", sa.DateTime(), nullable=True),
        sa.Column("rejected_by_user_id", sa.Integer(), nullable=True),
        sa.Column("rejected_by_username", sa.String(length=100), nullable=True),
        sa.Column("rejected_at", sa.DateTime(), nullable=True),
        sa.ForeignKeyConstraint(["applied_by_user_id"], ["users.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["created_by_user_id"], ["users.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["rejected_by_user_id"], ["users.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_warehouse_change_requests_action"), "warehouse_change_requests", ["action"], unique=False)
    op.create_index(op.f("ix_warehouse_change_requests_applied_at"), "warehouse_change_requests", ["applied_at"], unique=False)
    op.create_index(op.f("ix_warehouse_change_requests_applied_by_user_id"), "warehouse_change_requests", ["applied_by_user_id"], unique=False)
    op.create_index(op.f("ix_warehouse_change_requests_created_at"), "warehouse_change_requests", ["created_at"], unique=False)
    op.create_index(op.f("ix_warehouse_change_requests_created_by_user_id"), "warehouse_change_requests", ["created_by_user_id"], unique=False)
    op.create_index(op.f("ix_warehouse_change_requests_id"), "warehouse_change_requests", ["id"], unique=False)
    op.create_index(op.f("ix_warehouse_change_requests_rejected_at"), "warehouse_change_requests", ["rejected_at"], unique=False)
    op.create_index(op.f("ix_warehouse_change_requests_rejected_by_user_id"), "warehouse_change_requests", ["rejected_by_user_id"], unique=False)
    op.create_index(op.f("ix_warehouse_change_requests_status"), "warehouse_change_requests", ["status"], unique=False)


def downgrade() -> None:
    op.drop_index(op.f("ix_warehouse_change_requests_status"), table_name="warehouse_change_requests")
    op.drop_index(op.f("ix_warehouse_change_requests_rejected_by_user_id"), table_name="warehouse_change_requests")
    op.drop_index(op.f("ix_warehouse_change_requests_rejected_at"), table_name="warehouse_change_requests")
    op.drop_index(op.f("ix_warehouse_change_requests_id"), table_name="warehouse_change_requests")
    op.drop_index(op.f("ix_warehouse_change_requests_created_by_user_id"), table_name="warehouse_change_requests")
    op.drop_index(op.f("ix_warehouse_change_requests_created_at"), table_name="warehouse_change_requests")
    op.drop_index(op.f("ix_warehouse_change_requests_applied_by_user_id"), table_name="warehouse_change_requests")
    op.drop_index(op.f("ix_warehouse_change_requests_applied_at"), table_name="warehouse_change_requests")
    op.drop_index(op.f("ix_warehouse_change_requests_action"), table_name="warehouse_change_requests")
    op.drop_table("warehouse_change_requests")
