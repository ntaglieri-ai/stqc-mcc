"""add norma_uni peso_kg_m dimensioni_std to materials

Revision ID: r2s3t4u5v6w7
Revises: q1r2s3t4u5v6
Create Date: 2026-05-29
"""
from alembic import op
import sqlalchemy as sa

revision = "r2s3t4u5v6w7"
down_revision = "q1r2s3t4u5v6"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("materials") as batch_op:
        batch_op.add_column(sa.Column("norma_uni",     sa.String(50),       nullable=True))
        batch_op.add_column(sa.Column("peso_kg_m",     sa.Numeric(10, 4),   nullable=True))
        batch_op.add_column(sa.Column("dimensioni_std", sa.Numeric(12, 2),  nullable=True))


def downgrade() -> None:
    with op.batch_alter_table("materials") as batch_op:
        batch_op.drop_column("norma_uni")
        batch_op.drop_column("peso_kg_m")
        batch_op.drop_column("dimensioni_std")
