"""add_fasi_operative

Revision ID: f1g2h3i4j5k6
Revises: e2f3g4h5i6j7
Create Date: 2026-05-27 00:00:00.000000

"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "f1g2h3i4j5k6"
down_revision: Union[str, Sequence[str], None] = "e2f3g4h5i6j7"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "fasi_operative",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("commessa_id", sa.Integer(), nullable=False),
        sa.Column("marca_pos", sa.String(100), nullable=True),
        sa.Column("profilo", sa.String(200), nullable=True),
        sa.Column("quantita", sa.Numeric(12, 3), nullable=True),
        sa.Column("fase", sa.String(200), nullable=True),
        sa.Column("postazione", sa.String(100), nullable=True),
        sa.Column("tempo_prev_minpz", sa.Numeric(10, 2), nullable=True),
        sa.Column("tempo_tot_min", sa.Numeric(10, 2), nullable=True),
        sa.Column("sequenza", sa.Integer(), nullable=True),
        sa.Column("dipende_da", sa.String(200), nullable=True),
        sa.Column("note_operative", sa.Text(), nullable=True),
        sa.Column(
            "status",
            sa.Enum("DA_INIZIARE", "IN_CORSO", "COMPLETATA", name="fasestatustype"),
            nullable=False,
            server_default="DA_INIZIARE",
        ),
        sa.Column("created_at", sa.DateTime(), nullable=True),
        sa.ForeignKeyConstraint(["commessa_id"], ["commesse.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_fasi_operative_id", "fasi_operative", ["id"])
    op.create_index("ix_fasi_operative_commessa_id", "fasi_operative", ["commessa_id"])


def downgrade() -> None:
    op.drop_index("ix_fasi_operative_commessa_id", table_name="fasi_operative")
    op.drop_index("ix_fasi_operative_id", table_name="fasi_operative")
    op.drop_table("fasi_operative")
