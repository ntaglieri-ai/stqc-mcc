"""add workstation progress mode

Revision ID: o6p7q8r9s0t1
Revises: n5o6p7q8r9s0
Create Date: 2026-07-17
"""

from alembic import op
import sqlalchemy as sa


revision = "o6p7q8r9s0t1"
down_revision = "n5o6p7q8r9s0"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "workstations",
        sa.Column("progress_mode", sa.String(length=30), nullable=False, server_default="BLOCCO"),
    )
    op.create_index(op.f("ix_workstations_progress_mode"), "workstations", ["progress_mode"], unique=False)


def downgrade() -> None:
    op.drop_index(op.f("ix_workstations_progress_mode"), table_name="workstations")
    op.drop_column("workstations", "progress_mode")
