"""add post officina items

Revision ID: p6q7r8s9t0u1
Revises: o6p7q8r9s0t1
Create Date: 2026-07-19
"""

from alembic import op
import sqlalchemy as sa


revision = "p6q7r8s9t0u1"
down_revision = "o6p7q8r9s0t1"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "commessa_post_officina_items",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("commessa_id", sa.Integer(), nullable=False),
        sa.Column("revisione_id", sa.Integer(), nullable=False),
        sa.Column("row_index", sa.Integer(), nullable=False),
        sa.Column("codice", sa.String(length=200), nullable=False),
        sa.Column("descrizione", sa.String(length=500), nullable=True),
        sa.Column("profilo", sa.String(length=250), nullable=True),
        sa.Column("quantita", sa.Numeric(precision=18, scale=6), nullable=False),
        sa.Column("lunghezza_mm", sa.Numeric(precision=12, scale=2), nullable=True),
        sa.Column("larghezza_mm", sa.Numeric(precision=12, scale=2), nullable=True),
        sa.Column("altezza_mm", sa.Numeric(precision=12, scale=2), nullable=True),
        sa.Column("peso_unitario_kg", sa.Numeric(precision=12, scale=4), nullable=True),
        sa.Column("peso_totale_kg", sa.Numeric(precision=12, scale=4), nullable=True),
        sa.Column("area_verniciabile_mq", sa.Numeric(precision=12, scale=4), nullable=True),
        sa.Column("trattamento", sa.String(length=160), nullable=True),
        sa.Column("tipo_unita", sa.String(length=40), nullable=False, server_default="NON_CLASSIFICATO"),
        sa.Column("lavorazioni_status", sa.String(length=40), nullable=False, server_default="NON_PRONTO"),
        sa.Column("cantiere_status", sa.String(length=40), nullable=False, server_default="NON_PRONTO"),
        sa.Column("source_file", sa.String(length=500), nullable=True),
        sa.Column("note", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=True),
        sa.Column("updated_at", sa.DateTime(), nullable=True),
        sa.ForeignKeyConstraint(["commessa_id"], ["commesse.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["revisione_id"], ["commessa_revisioni.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("revisione_id", "row_index", name="uq_post_officina_revision_row"),
    )
    op.create_index(op.f("ix_commessa_post_officina_items_id"), "commessa_post_officina_items", ["id"], unique=False)
    op.create_index(op.f("ix_commessa_post_officina_items_commessa_id"), "commessa_post_officina_items", ["commessa_id"], unique=False)
    op.create_index(op.f("ix_commessa_post_officina_items_revisione_id"), "commessa_post_officina_items", ["revisione_id"], unique=False)
    op.create_index(op.f("ix_commessa_post_officina_items_codice"), "commessa_post_officina_items", ["codice"], unique=False)
    op.create_index(op.f("ix_commessa_post_officina_items_profilo"), "commessa_post_officina_items", ["profilo"], unique=False)
    op.create_index(op.f("ix_commessa_post_officina_items_trattamento"), "commessa_post_officina_items", ["trattamento"], unique=False)
    op.create_index(op.f("ix_commessa_post_officina_items_tipo_unita"), "commessa_post_officina_items", ["tipo_unita"], unique=False)
    op.create_index(op.f("ix_commessa_post_officina_items_lavorazioni_status"), "commessa_post_officina_items", ["lavorazioni_status"], unique=False)
    op.create_index(op.f("ix_commessa_post_officina_items_cantiere_status"), "commessa_post_officina_items", ["cantiere_status"], unique=False)


def downgrade() -> None:
    op.drop_index(op.f("ix_commessa_post_officina_items_cantiere_status"), table_name="commessa_post_officina_items")
    op.drop_index(op.f("ix_commessa_post_officina_items_lavorazioni_status"), table_name="commessa_post_officina_items")
    op.drop_index(op.f("ix_commessa_post_officina_items_tipo_unita"), table_name="commessa_post_officina_items")
    op.drop_index(op.f("ix_commessa_post_officina_items_trattamento"), table_name="commessa_post_officina_items")
    op.drop_index(op.f("ix_commessa_post_officina_items_profilo"), table_name="commessa_post_officina_items")
    op.drop_index(op.f("ix_commessa_post_officina_items_codice"), table_name="commessa_post_officina_items")
    op.drop_index(op.f("ix_commessa_post_officina_items_revisione_id"), table_name="commessa_post_officina_items")
    op.drop_index(op.f("ix_commessa_post_officina_items_commessa_id"), table_name="commessa_post_officina_items")
    op.drop_index(op.f("ix_commessa_post_officina_items_id"), table_name="commessa_post_officina_items")
    op.drop_table("commessa_post_officina_items")
