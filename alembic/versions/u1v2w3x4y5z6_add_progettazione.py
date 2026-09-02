"""Add independent design checklist for each commessa."""
from alembic import op
import sqlalchemy as sa
revision = "u1v2w3x4y5z6"
down_revision = "t0u1v2w3x4y5"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table("commessa_progettazione",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("commessa_id", sa.Integer(), sa.ForeignKey("commesse.id", ondelete="CASCADE"), nullable=False),
        sa.Column("voce", sa.String(60), nullable=False),
        sa.Column("inizio", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("fine", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.UniqueConstraint("commessa_id", "voce", name="uq_progettazione_voce"))
    op.create_index("ix_commessa_progettazione_commessa_id", "commessa_progettazione", ["commessa_id"])


def downgrade():
    op.drop_table("commessa_progettazione")
