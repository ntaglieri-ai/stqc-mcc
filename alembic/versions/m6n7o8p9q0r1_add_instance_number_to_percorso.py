"""add instance_number to pezzo_percorso and fix unique constraint

Revision ID: m6n7o8p9q0r1
Revises: l5m6n7o8p9q0
Create Date: 2026-05-28

Old UNIQUE: (commessa_id, marca_pos, fase_id)         — 1 row per tipo-pezzo × fase
New UNIQUE: (commessa_id, marca_pos, instance_number, fase_id)
            — 1 row per istanza-fisica × fase
            — SQLite tratta i NULL come distinti, quindi instance_number=NULL
              rimane comunque univoco per pezzi senza distinta corrispondente
"""
from alembic import op
import sqlalchemy as sa

revision = "m6n7o8p9q0r1"
down_revision = "l5m6n7o8p9q0"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("pezzo_percorso", recreate="always") as batch_op:
        batch_op.add_column(sa.Column("instance_number", sa.Integer, nullable=True))
        batch_op.drop_constraint("uq_pezzo_percorso", type_="unique")
        batch_op.create_unique_constraint(
            "uq_pezzo_percorso",
            ["commessa_id", "marca_pos", "instance_number", "fase_id"],
        )


def downgrade() -> None:
    with op.batch_alter_table("pezzo_percorso", recreate="always") as batch_op:
        batch_op.drop_constraint("uq_pezzo_percorso", type_="unique")
        batch_op.drop_column("instance_number")
        batch_op.create_unique_constraint(
            "uq_pezzo_percorso",
            ["commessa_id", "marca_pos", "fase_id"],
        )
