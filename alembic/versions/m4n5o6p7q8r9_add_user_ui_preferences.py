"""add user UI preferences

Revision ID: m4n5o6p7q8r9
Revises: l3m4n5o6p7q8
Create Date: 2026-07-11
"""

from alembic import op
import sqlalchemy as sa


revision = "m4n5o6p7q8r9"
down_revision = "l3m4n5o6p7q8"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("user_attributes", schema=None) as batch_op:
        batch_op.add_column(sa.Column("preferences", sa.JSON(), nullable=True))


def downgrade() -> None:
    with op.batch_alter_table("user_attributes", schema=None) as batch_op:
        batch_op.drop_column("preferences")
