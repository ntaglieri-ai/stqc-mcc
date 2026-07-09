"""add_commessa_fk_to_items_and_movements

Revision ID: 363c854ca0ee
Revises: 0d6be0ef2364
Create Date: 2026-05-23 11:25:42.877116

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy import inspect


# revision identifiers, used by Alembic.
revision: str = '363c854ca0ee'
down_revision: Union[str, Sequence[str], None] = '0d6be0ef2364'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def _has_table(table_name: str) -> bool:
    return inspect(op.get_bind()).has_table(table_name)


def _has_column(table_name: str, column_name: str) -> bool:
    if not _has_table(table_name):
        return False
    return any(col["name"] == column_name for col in inspect(op.get_bind()).get_columns(table_name))


def _create_base_tables_if_missing() -> None:
    """Bootstrap dello schema legacy.

    La revisione iniziale 0d6be0ef2364 è vuota. Su DB già esistenti le tabelle
    ci sono, ma su DB nuovo questa migrazione è la prima che le usa davvero.
    Creiamo quindi solo le tabelle base storiche mancanti, lasciando alle
    revisioni successive l'aggiunta dei campi più recenti.
    """
    if not _has_table("commesse"):
        op.create_table(
            "commesse",
            sa.Column("id", sa.Integer(), nullable=False),
            sa.Column("codice", sa.String(length=100), nullable=False),
            sa.Column("cliente", sa.String(length=200), nullable=True),
            sa.Column("descrizione", sa.String(length=500), nullable=True),
            sa.Column("data_inizio", sa.Date(), nullable=True),
            sa.Column("data_consegna_prevista", sa.Date(), nullable=True),
            sa.Column(
                "status",
                sa.Enum("APERTA", "IN_PRODUZIONE", "SOSPESA", "CHIUSA", name="commessastatus"),
                nullable=False,
                server_default="APERTA",
            ),
            sa.Column("notes", sa.Text(), nullable=True),
            sa.Column("created_at", sa.DateTime(), nullable=True),
            sa.PrimaryKeyConstraint("id"),
            sa.UniqueConstraint("codice"),
        )
        op.create_index("ix_commesse_id", "commesse", ["id"])
        op.create_index("ix_commesse_codice", "commesse", ["codice"], unique=True)

    if not _has_table("suppliers"):
        op.create_table(
            "suppliers",
            sa.Column("id", sa.Integer(), nullable=False),
            sa.Column("name", sa.String(length=200), nullable=False),
            sa.Column("tax_id", sa.String(length=50), nullable=True),
            sa.Column("address", sa.String(length=400), nullable=True),
            sa.Column("contacts", sa.String(length=400), nullable=True),
            sa.PrimaryKeyConstraint("id"),
        )
        op.create_index("ix_suppliers_id", "suppliers", ["id"])

    if not _has_table("materials"):
        op.create_table(
            "materials",
            sa.Column("id", sa.Integer(), nullable=False),
            sa.Column("code", sa.String(length=100), nullable=False),
            sa.Column("description", sa.String(length=400), nullable=False),
            sa.Column("unit", sa.String(length=20), nullable=False, server_default="PZ"),
            sa.Column("specification", sa.String(length=400), nullable=True),
            sa.PrimaryKeyConstraint("id"),
            sa.UniqueConstraint("code"),
        )
        op.create_index("ix_materials_id", "materials", ["id"])
        op.create_index("ix_materials_code", "materials", ["code"], unique=True)

    if not _has_table("batches"):
        op.create_table(
            "batches",
            sa.Column("id", sa.Integer(), nullable=False),
            sa.Column("batch_number", sa.String(length=200), nullable=False),
            sa.Column("material_id", sa.Integer(), nullable=False),
            sa.Column("heat_number", sa.String(length=200), nullable=True),
            sa.Column("produced_date", sa.Date(), nullable=True),
            sa.Column("notes", sa.Text(), nullable=True),
            sa.ForeignKeyConstraint(["material_id"], ["materials.id"]),
            sa.PrimaryKeyConstraint("id"),
        )
        op.create_index("ix_batches_id", "batches", ["id"])
        op.create_index("ix_batches_batch_number", "batches", ["batch_number"])

    if not _has_table("receipts"):
        op.create_table(
            "receipts",
            sa.Column("id", sa.Integer(), nullable=False),
            sa.Column("ddt_number", sa.String(length=120), nullable=False),
            sa.Column("ddt_date", sa.Date(), nullable=False),
            sa.Column("supplier_id", sa.Integer(), nullable=False),
            sa.Column("material_id", sa.Integer(), nullable=False),
            sa.Column("batch_id", sa.Integer(), nullable=True),
            sa.Column("quantity", sa.Numeric(precision=18, scale=6), nullable=False),
            sa.Column("unit", sa.String(length=20), nullable=False, server_default="PZ"),
            sa.Column("created_at", sa.DateTime(), nullable=True),
            sa.Column("notes", sa.Text(), nullable=True),
            sa.ForeignKeyConstraint(["batch_id"], ["batches.id"]),
            sa.ForeignKeyConstraint(["material_id"], ["materials.id"]),
            sa.ForeignKeyConstraint(["supplier_id"], ["suppliers.id"]),
            sa.PrimaryKeyConstraint("id"),
        )
        op.create_index("ix_receipts_id", "receipts", ["id"])
        op.create_index("ix_receipts_ddt_number", "receipts", ["ddt_number"])

    if not _has_table("certificates"):
        op.create_table(
            "certificates",
            sa.Column("id", sa.Integer(), nullable=False),
            sa.Column("receipt_id", sa.Integer(), nullable=False),
            sa.Column("filename", sa.String(length=255), nullable=False),
            sa.Column("mime_type", sa.String(length=100), nullable=True),
            sa.Column("storage_path", sa.String(length=500), nullable=True),
            sa.Column("uploaded_at", sa.DateTime(), nullable=True),
            sa.ForeignKeyConstraint(["receipt_id"], ["receipts.id"]),
            sa.PrimaryKeyConstraint("id"),
        )
        op.create_index("ix_certificates_id", "certificates", ["id"])

    if not _has_table("stock_movements"):
        op.create_table(
            "stock_movements",
            sa.Column("id", sa.Integer(), nullable=False),
            sa.Column("material_id", sa.Integer(), nullable=False),
            sa.Column("batch_id", sa.Integer(), nullable=True),
            sa.Column("quantity", sa.Numeric(precision=18, scale=6), nullable=False),
            sa.Column(
                "movement_type",
                sa.Enum("INCOMING", "OUTGOING", "ADJUSTMENT", "SFRIDO", name="movementtype"),
                nullable=False,
            ),
            sa.Column("reason", sa.String(length=200), nullable=False),
            sa.Column("destination_commessa", sa.String(length=200), nullable=True),
            sa.Column("reference", sa.String(length=200), nullable=True),
            sa.Column("occurred_at", sa.DateTime(), nullable=True),
            sa.ForeignKeyConstraint(["batch_id"], ["batches.id"]),
            sa.ForeignKeyConstraint(["material_id"], ["materials.id"]),
            sa.PrimaryKeyConstraint("id"),
        )
        op.create_index("ix_stock_movements_id", "stock_movements", ["id"])

    if not _has_table("distinta_imports"):
        op.create_table(
            "distinta_imports",
            sa.Column("id", sa.Integer(), nullable=False),
            sa.Column("filename", sa.String(length=255), nullable=False),
            sa.Column("source_software", sa.String(length=100), nullable=True),
            sa.Column("imported_at", sa.DateTime(), nullable=True),
            sa.Column("total_items", sa.Integer(), nullable=True),
            sa.Column("status", sa.String(length=50), nullable=False, server_default="PENDING"),
            sa.Column("notes", sa.Text(), nullable=True),
            sa.PrimaryKeyConstraint("id"),
        )
        op.create_index("ix_distinta_imports_id", "distinta_imports", ["id"])

    if not _has_table("distinta_items"):
        op.create_table(
            "distinta_items",
            sa.Column("id", sa.Integer(), nullable=False),
            sa.Column("import_id", sa.Integer(), nullable=False),
            sa.Column("part_number", sa.String(length=200), nullable=True),
            sa.Column("description", sa.String(length=400), nullable=True),
            sa.Column("quantity", sa.Numeric(precision=18, scale=6), nullable=True),
            sa.Column("material_code", sa.String(length=100), nullable=True),
            sa.Column("material_description", sa.String(length=400), nullable=True),
            sa.Column("commessa_reference", sa.String(length=200), nullable=True),
            sa.Column("qr_code", sa.Text(), nullable=True),
            sa.Column("mapped_material_id", sa.Integer(), nullable=True),
            sa.ForeignKeyConstraint(["import_id"], ["distinta_imports.id"], ondelete="CASCADE"),
            sa.ForeignKeyConstraint(["mapped_material_id"], ["materials.id"]),
            sa.PrimaryKeyConstraint("id"),
        )
        op.create_index("ix_distinta_items_id", "distinta_items", ["id"])


def upgrade() -> None:
    """Upgrade schema."""
    _create_base_tables_if_missing()

    if not _has_column("distinta_items", "commessa_id"):
        with op.batch_alter_table('distinta_items', schema=None) as batch_op:
            batch_op.add_column(sa.Column('commessa_id', sa.Integer(), nullable=True))
            batch_op.create_index(batch_op.f('ix_distinta_items_commessa_id'), ['commessa_id'], unique=False)
            batch_op.create_foreign_key('fk_distinta_items_commessa_id', 'commesse', ['commessa_id'], ['id'])

    if not _has_column("stock_movements", "commessa_id"):
        with op.batch_alter_table('stock_movements', schema=None) as batch_op:
            batch_op.add_column(sa.Column('commessa_id', sa.Integer(), nullable=True))
            batch_op.create_index(batch_op.f('ix_stock_movements_commessa_id'), ['commessa_id'], unique=False)
            batch_op.create_foreign_key('fk_stock_movements_commessa_id', 'commesse', ['commessa_id'], ['id'])


def downgrade() -> None:
    """Downgrade schema."""
    with op.batch_alter_table('stock_movements', schema=None) as batch_op:
        batch_op.drop_constraint('fk_stock_movements_commessa_id', type_='foreignkey')
        batch_op.drop_index(batch_op.f('ix_stock_movements_commessa_id'))
        batch_op.drop_column('commessa_id')

    with op.batch_alter_table('distinta_items', schema=None) as batch_op:
        batch_op.drop_constraint('fk_distinta_items_commessa_id', type_='foreignkey')
        batch_op.drop_index(batch_op.f('ix_distinta_items_commessa_id'))
        batch_op.drop_column('commessa_id')
