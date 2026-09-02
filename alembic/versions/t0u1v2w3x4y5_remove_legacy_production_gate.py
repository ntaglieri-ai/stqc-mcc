"""Remove the obsolete manual production prerequisite.

Revision ID: t0u1v2w3x4y5
Revises: s9t0u1v2w3x4
"""
from alembic import op
import sqlalchemy as sa

revision = "t0u1v2w3x4y5"
down_revision = "s9t0u1v2w3x4"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("commessa_revisioni") as batch:
        batch.drop_column("step51_completed_at")


def downgrade() -> None:
    with op.batch_alter_table("commessa_revisioni") as batch:
        batch.add_column(sa.Column("step51_completed_at", sa.DateTime(), nullable=True))
