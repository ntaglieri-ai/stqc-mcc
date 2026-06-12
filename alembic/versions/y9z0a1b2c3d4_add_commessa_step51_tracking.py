"""add commessa revision and step 5.1 tracking

Revision ID: y9z0a1b2c3d4
Revises: x8y9z0a1b2c3
Create Date: 2026-06-12
"""
from alembic import op
import sqlalchemy as sa


revision = "y9z0a1b2c3d4"
down_revision = "x8y9z0a1b2c3"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("commessa_revisioni") as batch:
        batch.add_column(sa.Column("corrente", sa.Boolean(), nullable=False, server_default=sa.false()))
        batch.add_column(sa.Column("step4_completed_at", sa.DateTime(), nullable=True))
        batch.add_column(sa.Column("step51_completed_at", sa.DateTime(), nullable=True))
        batch.create_index("ix_commessa_revisioni_corrente", ["corrente"])

    # La revisione più recente di ogni commessa diventa quella corrente.
    op.execute(
        """
        UPDATE commessa_revisioni
        SET corrente = 1,
            step4_completed_at = imported_at
        WHERE id IN (
            SELECT MAX(id)
            FROM commessa_revisioni
            GROUP BY commessa_id
        )
        """
    )

    with op.batch_alter_table("distinta_items") as batch:
        batch.add_column(sa.Column("qr_attivo", sa.Boolean(), nullable=False, server_default=sa.false()))
        batch.add_column(sa.Column("stato_tracciamento", sa.String(length=30), nullable=False, server_default="NON_GENERATO"))
        batch.create_index("ix_distinta_items_qr_attivo", ["qr_attivo"])


def downgrade() -> None:
    with op.batch_alter_table("distinta_items") as batch:
        batch.drop_index("ix_distinta_items_qr_attivo")
        batch.drop_column("stato_tracciamento")
        batch.drop_column("qr_attivo")

    with op.batch_alter_table("commessa_revisioni") as batch:
        batch.drop_index("ix_commessa_revisioni_corrente")
        batch.drop_column("step51_completed_at")
        batch.drop_column("step4_completed_at")
        batch.drop_column("corrente")
