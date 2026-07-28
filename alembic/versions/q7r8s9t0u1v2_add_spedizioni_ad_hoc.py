"""add spedizioni ad hoc

Revision ID: q7r8s9t0u1v2
Revises: p6q7r8s9t0u1
Create Date: 2026-07-28
"""

from alembic import op
import sqlalchemy as sa


revision = "q7r8s9t0u1v2"
down_revision = "p6q7r8s9t0u1"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "spedizioni_ad_hoc",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("commessa_id", sa.Integer(), nullable=False),
        sa.Column("revisione_id", sa.Integer(), nullable=True),
        sa.Column("titolo", sa.String(length=200), nullable=False),
        sa.Column("source_file", sa.String(length=500), nullable=True),
        sa.Column("stato", sa.String(length=40), nullable=False, server_default="APERTA"),
        sa.Column("note", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=True),
        sa.Column("updated_at", sa.DateTime(), nullable=True),
        sa.ForeignKeyConstraint(["commessa_id"], ["commesse.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["revisione_id"], ["commessa_revisioni.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_spedizioni_ad_hoc_id"), "spedizioni_ad_hoc", ["id"], unique=False)
    op.create_index(op.f("ix_spedizioni_ad_hoc_commessa_id"), "spedizioni_ad_hoc", ["commessa_id"], unique=False)
    op.create_index(op.f("ix_spedizioni_ad_hoc_revisione_id"), "spedizioni_ad_hoc", ["revisione_id"], unique=False)
    op.create_index(op.f("ix_spedizioni_ad_hoc_titolo"), "spedizioni_ad_hoc", ["titolo"], unique=False)
    op.create_index(op.f("ix_spedizioni_ad_hoc_stato"), "spedizioni_ad_hoc", ["stato"], unique=False)

    op.create_table(
        "spedizione_ad_hoc_items",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("spedizione_id", sa.Integer(), nullable=False),
        sa.Column("commessa_id", sa.Integer(), nullable=False),
        sa.Column("revisione_id", sa.Integer(), nullable=True),
        sa.Column("row_index", sa.Integer(), nullable=False),
        sa.Column("codice", sa.String(length=200), nullable=False),
        sa.Column("descrizione", sa.String(length=500), nullable=True),
        sa.Column("profilo", sa.String(length=250), nullable=True),
        sa.Column("quantita", sa.Numeric(precision=18, scale=6), nullable=False, server_default="0"),
        sa.Column("lunghezza_mm", sa.Numeric(precision=12, scale=2), nullable=True),
        sa.Column("larghezza_mm", sa.Numeric(precision=12, scale=2), nullable=True),
        sa.Column("altezza_mm", sa.Numeric(precision=12, scale=2), nullable=True),
        sa.Column("peso_unitario_kg", sa.Numeric(precision=12, scale=4), nullable=True),
        sa.Column("peso_totale_kg", sa.Numeric(precision=12, scale=4), nullable=True),
        sa.Column("area_verniciabile_mq", sa.Numeric(precision=12, scale=4), nullable=True),
        sa.Column("trattamento", sa.String(length=160), nullable=True),
        sa.Column("tipo_unita", sa.String(length=40), nullable=False, server_default="SPEDIZIONE_AD_HOC"),
        sa.Column("stato", sa.String(length=40), nullable=False, server_default="DA_TROVARE"),
        sa.Column("trovato_at", sa.DateTime(), nullable=True),
        sa.Column("scanner_device_id", sa.Integer(), nullable=True),
        sa.Column("raw_payload", sa.Text(), nullable=True),
        sa.Column("source_file", sa.String(length=500), nullable=True),
        sa.Column("note", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=True),
        sa.Column("updated_at", sa.DateTime(), nullable=True),
        sa.ForeignKeyConstraint(["commessa_id"], ["commesse.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["revisione_id"], ["commessa_revisioni.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["scanner_device_id"], ["scanner_devices.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["spedizione_id"], ["spedizioni_ad_hoc.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("spedizione_id", "row_index", name="uq_spedizione_ad_hoc_row"),
    )
    op.create_index(op.f("ix_spedizione_ad_hoc_items_id"), "spedizione_ad_hoc_items", ["id"], unique=False)
    op.create_index(op.f("ix_spedizione_ad_hoc_items_spedizione_id"), "spedizione_ad_hoc_items", ["spedizione_id"], unique=False)
    op.create_index(op.f("ix_spedizione_ad_hoc_items_commessa_id"), "spedizione_ad_hoc_items", ["commessa_id"], unique=False)
    op.create_index(op.f("ix_spedizione_ad_hoc_items_revisione_id"), "spedizione_ad_hoc_items", ["revisione_id"], unique=False)
    op.create_index(op.f("ix_spedizione_ad_hoc_items_codice"), "spedizione_ad_hoc_items", ["codice"], unique=False)
    op.create_index(op.f("ix_spedizione_ad_hoc_items_profilo"), "spedizione_ad_hoc_items", ["profilo"], unique=False)
    op.create_index(op.f("ix_spedizione_ad_hoc_items_trattamento"), "spedizione_ad_hoc_items", ["trattamento"], unique=False)
    op.create_index(op.f("ix_spedizione_ad_hoc_items_tipo_unita"), "spedizione_ad_hoc_items", ["tipo_unita"], unique=False)
    op.create_index(op.f("ix_spedizione_ad_hoc_items_stato"), "spedizione_ad_hoc_items", ["stato"], unique=False)
    op.create_index(op.f("ix_spedizione_ad_hoc_items_trovato_at"), "spedizione_ad_hoc_items", ["trovato_at"], unique=False)
    op.create_index(op.f("ix_spedizione_ad_hoc_items_scanner_device_id"), "spedizione_ad_hoc_items", ["scanner_device_id"], unique=False)


def downgrade() -> None:
    op.drop_index(op.f("ix_spedizione_ad_hoc_items_scanner_device_id"), table_name="spedizione_ad_hoc_items")
    op.drop_index(op.f("ix_spedizione_ad_hoc_items_trovato_at"), table_name="spedizione_ad_hoc_items")
    op.drop_index(op.f("ix_spedizione_ad_hoc_items_stato"), table_name="spedizione_ad_hoc_items")
    op.drop_index(op.f("ix_spedizione_ad_hoc_items_tipo_unita"), table_name="spedizione_ad_hoc_items")
    op.drop_index(op.f("ix_spedizione_ad_hoc_items_trattamento"), table_name="spedizione_ad_hoc_items")
    op.drop_index(op.f("ix_spedizione_ad_hoc_items_profilo"), table_name="spedizione_ad_hoc_items")
    op.drop_index(op.f("ix_spedizione_ad_hoc_items_codice"), table_name="spedizione_ad_hoc_items")
    op.drop_index(op.f("ix_spedizione_ad_hoc_items_revisione_id"), table_name="spedizione_ad_hoc_items")
    op.drop_index(op.f("ix_spedizione_ad_hoc_items_commessa_id"), table_name="spedizione_ad_hoc_items")
    op.drop_index(op.f("ix_spedizione_ad_hoc_items_spedizione_id"), table_name="spedizione_ad_hoc_items")
    op.drop_index(op.f("ix_spedizione_ad_hoc_items_id"), table_name="spedizione_ad_hoc_items")
    op.drop_table("spedizione_ad_hoc_items")
    op.drop_index(op.f("ix_spedizioni_ad_hoc_stato"), table_name="spedizioni_ad_hoc")
    op.drop_index(op.f("ix_spedizioni_ad_hoc_titolo"), table_name="spedizioni_ad_hoc")
    op.drop_index(op.f("ix_spedizioni_ad_hoc_revisione_id"), table_name="spedizioni_ad_hoc")
    op.drop_index(op.f("ix_spedizioni_ad_hoc_commessa_id"), table_name="spedizioni_ad_hoc")
    op.drop_index(op.f("ix_spedizioni_ad_hoc_id"), table_name="spedizioni_ad_hoc")
    op.drop_table("spedizioni_ad_hoc")
