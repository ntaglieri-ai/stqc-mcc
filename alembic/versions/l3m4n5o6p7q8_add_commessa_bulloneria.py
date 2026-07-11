"""add commessa bulloneria

Revision ID: l3m4n5o6p7q8
Revises: k2l3m4n5o6p7
Create Date: 2026-07-11
"""

from alembic import op
import sqlalchemy as sa


revision = "l3m4n5o6p7q8"
down_revision = "k2l3m4n5o6p7"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "commessa_bulloneria",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("commessa_id", sa.Integer(), nullable=False),
        sa.Column("revisione_id", sa.Integer(), nullable=False),
        sa.Column("assemblato", sa.String(length=200), nullable=True),
        sa.Column("codice", sa.String(length=200), nullable=True),
        sa.Column("descrizione", sa.String(length=500), nullable=True),
        sa.Column("categoria", sa.String(length=100), nullable=True),
        sa.Column("tipo", sa.String(length=100), nullable=True),
        sa.Column("norma", sa.String(length=120), nullable=True),
        sa.Column("diametro", sa.String(length=80), nullable=True),
        sa.Column("lunghezza", sa.String(length=80), nullable=True),
        sa.Column("classe", sa.String(length=80), nullable=True),
        sa.Column("trattamento", sa.String(length=160), nullable=True),
        sa.Column("quantita", sa.Numeric(18, 6), nullable=False, server_default="0"),
        sa.Column("unita", sa.String(length=20), nullable=False, server_default="pz"),
        sa.Column("peso_kg", sa.Numeric(12, 4), nullable=True),
        sa.Column("note", sa.Text(), nullable=True),
        sa.Column("source_file", sa.String(length=500), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=True),
        sa.ForeignKeyConstraint(["commessa_id"], ["commesse.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["revisione_id"], ["commessa_revisioni.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_commessa_bulloneria_id"), "commessa_bulloneria", ["id"], unique=False)
    op.create_index(op.f("ix_commessa_bulloneria_commessa_id"), "commessa_bulloneria", ["commessa_id"], unique=False)
    op.create_index(op.f("ix_commessa_bulloneria_revisione_id"), "commessa_bulloneria", ["revisione_id"], unique=False)
    op.create_index(op.f("ix_commessa_bulloneria_assemblato"), "commessa_bulloneria", ["assemblato"], unique=False)
    op.create_index(op.f("ix_commessa_bulloneria_codice"), "commessa_bulloneria", ["codice"], unique=False)
    op.create_index(op.f("ix_commessa_bulloneria_categoria"), "commessa_bulloneria", ["categoria"], unique=False)
    op.create_index(op.f("ix_commessa_bulloneria_tipo"), "commessa_bulloneria", ["tipo"], unique=False)


def downgrade() -> None:
    op.drop_index(op.f("ix_commessa_bulloneria_tipo"), table_name="commessa_bulloneria")
    op.drop_index(op.f("ix_commessa_bulloneria_categoria"), table_name="commessa_bulloneria")
    op.drop_index(op.f("ix_commessa_bulloneria_codice"), table_name="commessa_bulloneria")
    op.drop_index(op.f("ix_commessa_bulloneria_assemblato"), table_name="commessa_bulloneria")
    op.drop_index(op.f("ix_commessa_bulloneria_revisione_id"), table_name="commessa_bulloneria")
    op.drop_index(op.f("ix_commessa_bulloneria_commessa_id"), table_name="commessa_bulloneria")
    op.drop_index(op.f("ix_commessa_bulloneria_id"), table_name="commessa_bulloneria")
    op.drop_table("commessa_bulloneria")
