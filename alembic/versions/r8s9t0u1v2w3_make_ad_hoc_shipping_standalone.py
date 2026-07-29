"""make ad hoc shipping standalone

Revision ID: r8s9t0u1v2w3
Revises: q7r8s9t0u1v2
Create Date: 2026-07-29
"""

from alembic import op
import sqlalchemy as sa


revision = "r8s9t0u1v2w3"
down_revision = "q7r8s9t0u1v2"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("spedizioni_ad_hoc") as batch_op:
        batch_op.alter_column(
            "commessa_id",
            existing_type=sa.Integer(),
            nullable=True,
        )

    with op.batch_alter_table("spedizione_ad_hoc_items") as batch_op:
        batch_op.alter_column(
            "commessa_id",
            existing_type=sa.Integer(),
            nullable=True,
        )


def downgrade() -> None:
    with op.batch_alter_table("spedizione_ad_hoc_items") as batch_op:
        batch_op.alter_column(
            "commessa_id",
            existing_type=sa.Integer(),
            nullable=False,
        )

    with op.batch_alter_table("spedizioni_ad_hoc") as batch_op:
        batch_op.alter_column(
            "commessa_id",
            existing_type=sa.Integer(),
            nullable=False,
        )
