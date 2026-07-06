"""add scanner read state

Revision ID: j1k2l3m4n5o6
Revises: i0j1k2l3m4n5
Create Date: 2026-07-06
"""

from alembic import op
import sqlalchemy as sa


revision = "j1k2l3m4n5o6"
down_revision = "i0j1k2l3m4n5"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "scanner_read_states",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("scanner_device_id", sa.Integer(), nullable=False),
        sa.Column("qr_value", sa.String(length=220), nullable=False),
        sa.Column("entity_type", sa.String(length=30), nullable=False),
        sa.Column("read_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(["scanner_device_id"], ["scanner_devices.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("scanner_device_id"),
    )
    op.create_index("ix_scanner_read_states_id", "scanner_read_states", ["id"])
    op.create_index("ix_scanner_read_states_scanner_device_id", "scanner_read_states", ["scanner_device_id"], unique=True)
    op.create_index("ix_scanner_read_states_entity_type", "scanner_read_states", ["entity_type"])
    op.create_index("ix_scanner_read_states_read_at", "scanner_read_states", ["read_at"])


def downgrade() -> None:
    op.drop_table("scanner_read_states")
