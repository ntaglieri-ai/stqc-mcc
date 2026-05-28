"""add commessa_revisioni table

Revision ID: n1o2p3q4r5s6
Revises: m6n7o8p9q0r1
Create Date: 2026-05-28
"""
from alembic import op
import sqlalchemy as sa

revision = "n1o2p3q4r5s6"
down_revision = "m6n7o8p9q0r1"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "commessa_revisioni",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("commessa_id", sa.Integer, sa.ForeignKey("commesse.id", ondelete="CASCADE"), nullable=False, index=True),
        sa.Column("codice", sa.String(20), nullable=False),
        sa.Column("file_assemblaggi", sa.String(500), nullable=True),
        sa.Column("file_lavorazioni", sa.String(500), nullable=True),
        sa.Column("note", sa.Text, nullable=True),
        sa.Column("imported_at", sa.DateTime, nullable=False, server_default=sa.func.now()),
        sa.UniqueConstraint("commessa_id", "codice", name="uq_commessa_revisione"),
    )


def downgrade() -> None:
    op.drop_table("commessa_revisioni")
