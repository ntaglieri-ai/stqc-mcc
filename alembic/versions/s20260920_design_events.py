"""Add append-only design phase events."""
from alembic import op
import sqlalchemy as sa

revision = "s20260920_design_events"
down_revision = "r20260918_scanner_events"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "commessa_progettazione_eventi",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("commessa_id", sa.Integer(), sa.ForeignKey("commesse.id", ondelete="CASCADE"), nullable=False),
        sa.Column("voce", sa.String(60), nullable=False),
        sa.Column("tipo_evento", sa.String(20), nullable=False),
        sa.Column("timestamp", sa.DateTime(), nullable=False),
    )
    for field in ("commessa_id", "voce", "tipo_evento", "timestamp"):
        op.create_index(f"ix_commessa_progettazione_eventi_{field}", "commessa_progettazione_eventi", [field])
    op.execute(sa.text(
        "INSERT INTO commessa_progettazione_eventi (commessa_id, voce, tipo_evento, timestamp) "
        "SELECT commessa_id, voce, 'INIZIO', iniziata_at FROM commessa_progettazione WHERE iniziata_at IS NOT NULL"
    ))
    op.execute(sa.text(
        "INSERT INTO commessa_progettazione_eventi (commessa_id, voce, tipo_evento, timestamp) "
        "SELECT commessa_id, voce, 'FINE', completata_at FROM commessa_progettazione WHERE completata_at IS NOT NULL"
    ))


def downgrade():
    op.drop_table("commessa_progettazione_eventi")
