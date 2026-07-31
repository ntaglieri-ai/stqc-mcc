"""add ddt manual items and shipments

Revision ID: s9t0u1v2w3x4
Revises: r8s9t0u1v2w3
Create Date: 2026-07-31
"""

from alembic import op
import sqlalchemy as sa


revision = "s9t0u1v2w3x4"
down_revision = "r8s9t0u1v2w3"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "ddt_manual_items",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("commessa_id", sa.Integer(), nullable=False),
        sa.Column("revisione_id", sa.Integer(), nullable=True),
        sa.Column("spedizione_ad_hoc_id", sa.Integer(), nullable=True),
        sa.Column("row_index", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("codice", sa.String(length=200), nullable=True),
        sa.Column("descrizione", sa.String(length=500), nullable=False),
        sa.Column("profilo", sa.String(length=250), nullable=True),
        sa.Column("quantita", sa.Numeric(precision=18, scale=6), nullable=False, server_default="1"),
        sa.Column("peso_totale_kg", sa.Numeric(precision=12, scale=4), nullable=True),
        sa.Column("trattamento", sa.String(length=160), nullable=True),
        sa.Column("note", sa.Text(), nullable=True),
        sa.Column("source_file", sa.String(length=500), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=True),
        sa.Column("updated_at", sa.DateTime(), nullable=True),
        sa.ForeignKeyConstraint(["commessa_id"], ["commesse.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["revisione_id"], ["commessa_revisioni.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["spedizione_ad_hoc_id"], ["spedizioni_ad_hoc.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_ddt_manual_items_id"), "ddt_manual_items", ["id"], unique=False)
    op.create_index(op.f("ix_ddt_manual_items_commessa_id"), "ddt_manual_items", ["commessa_id"], unique=False)
    op.create_index(op.f("ix_ddt_manual_items_revisione_id"), "ddt_manual_items", ["revisione_id"], unique=False)
    op.create_index(op.f("ix_ddt_manual_items_spedizione_ad_hoc_id"), "ddt_manual_items", ["spedizione_ad_hoc_id"], unique=False)
    op.create_index(op.f("ix_ddt_manual_items_codice"), "ddt_manual_items", ["codice"], unique=False)
    op.create_index(op.f("ix_ddt_manual_items_profilo"), "ddt_manual_items", ["profilo"], unique=False)
    op.create_index(op.f("ix_ddt_manual_items_trattamento"), "ddt_manual_items", ["trattamento"], unique=False)

    op.create_table(
        "ddt_shipments",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("commessa_id", sa.Integer(), nullable=False),
        sa.Column("revisione_id", sa.Integer(), nullable=True),
        sa.Column("spedizione_ad_hoc_id", sa.Integer(), nullable=True),
        sa.Column("numero", sa.Integer(), nullable=False),
        sa.Column("titolo", sa.String(length=200), nullable=False),
        sa.Column("righe_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("materiali_snapshot", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=True),
        sa.ForeignKeyConstraint(["commessa_id"], ["commesse.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["revisione_id"], ["commessa_revisioni.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["spedizione_ad_hoc_id"], ["spedizioni_ad_hoc.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_ddt_shipments_id"), "ddt_shipments", ["id"], unique=False)
    op.create_index(op.f("ix_ddt_shipments_commessa_id"), "ddt_shipments", ["commessa_id"], unique=False)
    op.create_index(op.f("ix_ddt_shipments_revisione_id"), "ddt_shipments", ["revisione_id"], unique=False)
    op.create_index(op.f("ix_ddt_shipments_spedizione_ad_hoc_id"), "ddt_shipments", ["spedizione_ad_hoc_id"], unique=False)
    op.create_index(op.f("ix_ddt_shipments_created_at"), "ddt_shipments", ["created_at"], unique=False)


def downgrade() -> None:
    op.drop_index(op.f("ix_ddt_shipments_created_at"), table_name="ddt_shipments")
    op.drop_index(op.f("ix_ddt_shipments_spedizione_ad_hoc_id"), table_name="ddt_shipments")
    op.drop_index(op.f("ix_ddt_shipments_revisione_id"), table_name="ddt_shipments")
    op.drop_index(op.f("ix_ddt_shipments_commessa_id"), table_name="ddt_shipments")
    op.drop_index(op.f("ix_ddt_shipments_id"), table_name="ddt_shipments")
    op.drop_table("ddt_shipments")

    op.drop_index(op.f("ix_ddt_manual_items_trattamento"), table_name="ddt_manual_items")
    op.drop_index(op.f("ix_ddt_manual_items_profilo"), table_name="ddt_manual_items")
    op.drop_index(op.f("ix_ddt_manual_items_codice"), table_name="ddt_manual_items")
    op.drop_index(op.f("ix_ddt_manual_items_spedizione_ad_hoc_id"), table_name="ddt_manual_items")
    op.drop_index(op.f("ix_ddt_manual_items_revisione_id"), table_name="ddt_manual_items")
    op.drop_index(op.f("ix_ddt_manual_items_commessa_id"), table_name="ddt_manual_items")
    op.drop_index(op.f("ix_ddt_manual_items_id"), table_name="ddt_manual_items")
    op.drop_table("ddt_manual_items")
