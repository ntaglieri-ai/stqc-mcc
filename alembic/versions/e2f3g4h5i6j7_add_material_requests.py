"""add_material_requests

Revision ID: e2f3g4h5i6j7
Revises: d1e2f3a4b5c6
Create Date: 2026-05-27 00:00:00.000000

"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "e2f3g4h5i6j7"
down_revision: Union[str, Sequence[str], None] = "d1e2f3a4b5c6"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "material_requests",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("commessa_id", sa.Integer(), nullable=False),
        sa.Column("commessa_codice", sa.String(100), nullable=True),
        sa.Column("material_id", sa.Integer(), nullable=False),
        sa.Column("material_description", sa.String(400), nullable=True),
        sa.Column("material_code", sa.String(100), nullable=True),
        sa.Column("quantity", sa.Numeric(18, 6), nullable=False),
        sa.Column("movement_type", sa.String(20), nullable=False),
        sa.Column("reason", sa.String(200), nullable=True),
        sa.Column("reference", sa.String(200), nullable=True),
        sa.Column(
            "status",
            sa.Enum("IN_ATTESA", "CONFERMATO", "RIFIUTATO", name="richiestastatustype"),
            nullable=False,
            server_default="IN_ATTESA",
        ),
        sa.Column("note_rifiuto", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=True),
        sa.Column("confirmed_at", sa.DateTime(), nullable=True),
        sa.ForeignKeyConstraint(["commessa_id"], ["commesse.id"]),
        sa.ForeignKeyConstraint(["material_id"], ["materials.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_material_requests_id", "material_requests", ["id"])
    op.create_index("ix_material_requests_commessa_id", "material_requests", ["commessa_id"])
    op.create_index("ix_material_requests_material_id", "material_requests", ["material_id"])


def downgrade() -> None:
    op.drop_index("ix_material_requests_material_id", table_name="material_requests")
    op.drop_index("ix_material_requests_commessa_id", table_name="material_requests")
    op.drop_index("ix_material_requests_id", table_name="material_requests")
    op.drop_table("material_requests")
