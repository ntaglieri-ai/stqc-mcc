"""add pieces table

Revision ID: a1b2c3d4e5f7
Revises: z0a1b2c3d4e5
Create Date: 2026-06-18 00:00:00.000000
"""

from alembic import op
import sqlalchemy as sa


revision = "a1b2c3d4e5f7"
down_revision = "z0a1b2c3d4e5"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "pieces",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("qr_code", sa.String(length=220), nullable=False),
        sa.Column("qr_payload", sa.String(length=220), nullable=False),
        sa.Column("commessa_id", sa.Integer(), nullable=False),
        sa.Column("revisione_id", sa.Integer(), nullable=False),
        sa.Column("distinta_item_id", sa.Integer(), nullable=True),
        sa.Column("assemblato_id", sa.String(length=200), nullable=True),
        sa.Column("marca_pos", sa.String(length=200), nullable=False),
        sa.Column("progressivo", sa.Integer(), nullable=False),
        sa.Column("profilo", sa.String(length=400), nullable=True),
        sa.Column("materiale", sa.String(length=100), nullable=True),
        sa.Column("materiale_descrizione", sa.String(length=400), nullable=True),
        sa.Column("lunghezza_mm", sa.Numeric(12, 2), nullable=True),
        sa.Column("larghezza_mm", sa.Numeric(12, 2), nullable=True),
        sa.Column("peso_kg", sa.Numeric(12, 4), nullable=True),
        sa.Column("tipo_profilo", sa.String(length=100), nullable=True),
        sa.Column("colata", sa.String(length=100), nullable=True),
        sa.Column("lotto", sa.String(length=100), nullable=True),
        sa.Column("certificato_31", sa.String(length=255), nullable=True),
        sa.Column("materiale_origine_id", sa.Integer(), nullable=True),
        sa.Column("fornitore", sa.String(length=200), nullable=True),
        sa.Column("stato_attuale", sa.String(length=30), nullable=False, server_default="NON_GENERATO"),
        sa.Column("ultima_postazione", sa.String(length=100), nullable=True),
        sa.Column("qr_attivo", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("created_at", sa.DateTime(), nullable=True),
        sa.Column("updated_at", sa.DateTime(), nullable=True),
        sa.ForeignKeyConstraint(["commessa_id"], ["commesse.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["distinta_item_id"], ["distinta_items.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["revisione_id"], ["commessa_revisioni.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("distinta_item_id", name="uq_piece_distinta_item"),
        sa.UniqueConstraint("revisione_id", "qr_code", name="uq_piece_revision_qr_code"),
    )
    op.create_index(op.f("ix_pieces_id"), "pieces", ["id"], unique=False)
    op.create_index(op.f("ix_pieces_qr_code"), "pieces", ["qr_code"], unique=False)
    op.create_index(op.f("ix_pieces_commessa_id"), "pieces", ["commessa_id"], unique=False)
    op.create_index(op.f("ix_pieces_revisione_id"), "pieces", ["revisione_id"], unique=False)
    op.create_index(op.f("ix_pieces_distinta_item_id"), "pieces", ["distinta_item_id"], unique=False)
    op.create_index(op.f("ix_pieces_assemblato_id"), "pieces", ["assemblato_id"], unique=False)
    op.create_index(op.f("ix_pieces_marca_pos"), "pieces", ["marca_pos"], unique=False)
    op.create_index(op.f("ix_pieces_stato_attuale"), "pieces", ["stato_attuale"], unique=False)
    op.create_index(op.f("ix_pieces_qr_attivo"), "pieces", ["qr_attivo"], unique=False)
    op.execute(
        """
        INSERT INTO pieces (
            qr_code, qr_payload, commessa_id, revisione_id, distinta_item_id,
            assemblato_id, marca_pos, progressivo, profilo, materiale,
            materiale_descrizione, lunghezza_mm, larghezza_mm, peso_kg,
            tipo_profilo, stato_attuale, qr_attivo, created_at, updated_at
        )
        SELECT
            CASE
                WHEN di.instance_number IS NOT NULL
                    THEN coalesce(nullif(trim(di.part_number), ''), 'PEZZO-' || di.id) || '-' || printf('%03d', di.instance_number)
                ELSE coalesce(nullif(trim(di.part_number), ''), 'PEZZO-' || di.id)
            END AS qr_code,
            CASE
                WHEN di.instance_number IS NOT NULL
                    THEN coalesce(nullif(trim(di.part_number), ''), 'PEZZO-' || di.id) || '-' || printf('%03d', di.instance_number)
                ELSE coalesce(nullif(trim(di.part_number), ''), 'PEZZO-' || di.id)
            END AS qr_payload,
            di.commessa_id,
            di.revisione_id,
            di.id,
            di.parent_assembly,
            coalesce(nullif(trim(di.part_number), ''), 'PEZZO-' || di.id),
            coalesce(di.instance_number, 1),
            di.description,
            di.material_code,
            di.material_description,
            di.length_mm,
            di.width_mm,
            di.weight_kg,
            di.tipo_profilo,
            di.stato_tracciamento,
            di.qr_attivo,
            CURRENT_TIMESTAMP,
            CURRENT_TIMESTAMP
        FROM distinta_items di
        WHERE di.revisione_id IS NOT NULL
          AND di.commessa_id IS NOT NULL
          AND di.invalidato = 0
        """
    )


def downgrade() -> None:
    op.drop_index(op.f("ix_pieces_qr_attivo"), table_name="pieces")
    op.drop_index(op.f("ix_pieces_stato_attuale"), table_name="pieces")
    op.drop_index(op.f("ix_pieces_marca_pos"), table_name="pieces")
    op.drop_index(op.f("ix_pieces_assemblato_id"), table_name="pieces")
    op.drop_index(op.f("ix_pieces_distinta_item_id"), table_name="pieces")
    op.drop_index(op.f("ix_pieces_revisione_id"), table_name="pieces")
    op.drop_index(op.f("ix_pieces_commessa_id"), table_name="pieces")
    op.drop_index(op.f("ix_pieces_qr_code"), table_name="pieces")
    op.drop_index(op.f("ix_pieces_id"), table_name="pieces")
    op.drop_table("pieces")
