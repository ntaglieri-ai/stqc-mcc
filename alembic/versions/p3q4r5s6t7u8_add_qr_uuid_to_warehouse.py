"""add qr_uuid and qr_code to materials and batches

Revision ID: p3q4r5s6t7u8
Revises: o2p3q4r5s6t7
Create Date: 2026-05-28
"""
from alembic import op
import sqlalchemy as sa

revision = "p3q4r5s6t7u8"
down_revision = "o2p3q4r5s6t7"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("materials") as batch_op:
        batch_op.add_column(sa.Column("qr_uuid", sa.String(36), nullable=True))
        batch_op.add_column(sa.Column("qr_code", sa.Text, nullable=True))

    with op.batch_alter_table("batches") as batch_op:
        batch_op.add_column(sa.Column("qr_uuid", sa.String(36), nullable=True))
        batch_op.add_column(sa.Column("qr_code", sa.Text, nullable=True))


def downgrade() -> None:
    with op.batch_alter_table("materials") as batch_op:
        batch_op.drop_column("qr_uuid")
        batch_op.drop_column("qr_code")

    with op.batch_alter_table("batches") as batch_op:
        batch_op.drop_column("qr_uuid")
        batch_op.drop_column("qr_code")
