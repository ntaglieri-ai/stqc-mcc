"""add commessa analysis fields and documents

Revision ID: w7x8y9z0a1b2
Revises: v6w7x8y9z0a1
Create Date: 2026-06-11
"""
from alembic import op
import sqlalchemy as sa


revision = "w7x8y9z0a1b2"
down_revision = "v6w7x8y9z0a1"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("commessa_revisioni") as batch:
        batch.add_column(sa.Column("predistinta", sa.Boolean(), nullable=False, server_default=sa.false()))
        batch.add_column(sa.Column("stato_analisi", sa.String(length=30), nullable=False, server_default="PRONTA"))
        batch.add_column(sa.Column("report_analisi", sa.JSON(), nullable=True))
    with op.batch_alter_table("distinta_items") as batch:
        batch.add_column(sa.Column("width_mm", sa.Numeric(12, 2), nullable=True))

    op.create_table(
        "commessa_documenti",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("commessa_id", sa.Integer(), nullable=False),
        sa.Column("revisione_id", sa.Integer(), nullable=False),
        sa.Column("categoria", sa.String(length=50), nullable=False, server_default="DISEGNO"),
        sa.Column("filename", sa.String(length=255), nullable=False),
        sa.Column("storage_path", sa.String(length=500), nullable=False),
        sa.Column("mime_type", sa.String(length=150), nullable=True),
        sa.Column("uploaded_at", sa.DateTime(), nullable=True),
        sa.ForeignKeyConstraint(["commessa_id"], ["commesse.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["revisione_id"], ["commessa_revisioni.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_commessa_documenti_commessa_id"), "commessa_documenti", ["commessa_id"])
    op.create_index(op.f("ix_commessa_documenti_revisione_id"), "commessa_documenti", ["revisione_id"])


def downgrade() -> None:
    op.drop_index(op.f("ix_commessa_documenti_revisione_id"), table_name="commessa_documenti")
    op.drop_index(op.f("ix_commessa_documenti_commessa_id"), table_name="commessa_documenti")
    op.drop_table("commessa_documenti")
    with op.batch_alter_table("distinta_items") as batch:
        batch.drop_column("width_mm")
    with op.batch_alter_table("commessa_revisioni") as batch:
        batch.drop_column("report_analisi")
        batch.drop_column("stato_analisi")
        batch.drop_column("predistinta")
