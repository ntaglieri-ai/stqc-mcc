"""Add hierarchical assembly scan sessions and append-only events."""
from alembic import op
import sqlalchemy as sa

revision = "t20260920_assembly_scans"
down_revision = "s20260920_design_events"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "assembly_scan_sessions",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("scanner_device_id", sa.Integer(), sa.ForeignKey("scanner_devices.id", ondelete="SET NULL")),
        sa.Column("workstation_id", sa.Integer(), sa.ForeignKey("workstations.id", ondelete="SET NULL")),
        sa.Column("workstation_code", sa.String(80), nullable=False),
        sa.Column("commessa_id", sa.Integer(), sa.ForeignKey("commesse.id", ondelete="CASCADE")),
        sa.Column("revisione_id", sa.Integer(), sa.ForeignKey("commessa_revisioni.id", ondelete="CASCADE")),
        sa.Column("assembly_code", sa.String(220)),
        sa.Column("assembly_instance", sa.Integer()),
        sa.Column("status", sa.String(30), nullable=False),
        sa.Column("started_at", sa.DateTime(), nullable=False),
        sa.Column("closed_at", sa.DateTime()),
    )
    for field in ("scanner_device_id", "workstation_id", "commessa_id", "assembly_code", "status", "started_at", "closed_at"):
        op.create_index(f"ix_assembly_scan_sessions_{field}", "assembly_scan_sessions", [field])
    op.create_table(
        "assembly_scan_events",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("session_id", sa.Integer(), sa.ForeignKey("assembly_scan_sessions.id", ondelete="CASCADE"), nullable=False),
        sa.Column("event_type", sa.String(30), nullable=False),
        sa.Column("raw_payload", sa.Text(), nullable=False),
        sa.Column("entity_code", sa.String(220)),
        sa.Column("piece_id", sa.Integer(), sa.ForeignKey("pieces.id", ondelete="SET NULL")),
        sa.Column("outcome", sa.String(20), nullable=False),
        sa.Column("error_code", sa.String(60)),
        sa.Column("message", sa.String(500), nullable=False),
        sa.Column("timestamp", sa.DateTime(), nullable=False),
    )
    for field in ("session_id", "event_type", "piece_id", "outcome", "error_code", "timestamp"):
        op.create_index(f"ix_assembly_scan_events_{field}", "assembly_scan_events", [field])
    op.create_table(
        "welding_scan_sessions",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("scanner_device_id", sa.Integer(), sa.ForeignKey("scanner_devices.id", ondelete="SET NULL")),
        sa.Column("workstation_id", sa.Integer(), sa.ForeignKey("workstations.id", ondelete="SET NULL")),
        sa.Column("workstation_code", sa.String(80), nullable=False),
        sa.Column("status", sa.String(20), nullable=False),
        sa.Column("started_at", sa.DateTime(), nullable=False),
        sa.Column("closed_at", sa.DateTime()),
    )
    for field in ("scanner_device_id", "workstation_id", "status", "started_at", "closed_at"):
        op.create_index(f"ix_welding_scan_sessions_{field}", "welding_scan_sessions", [field])
    op.create_table(
        "welding_scan_events",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("session_id", sa.Integer(), sa.ForeignKey("welding_scan_sessions.id", ondelete="CASCADE"), nullable=False),
        sa.Column("commessa_id", sa.Integer(), sa.ForeignKey("commesse.id", ondelete="CASCADE")),
        sa.Column("revisione_id", sa.Integer(), sa.ForeignKey("commessa_revisioni.id", ondelete="CASCADE")),
        sa.Column("event_type", sa.String(30), nullable=False),
        sa.Column("assembly_code", sa.String(220)),
        sa.Column("assembly_instance", sa.Integer()),
        sa.Column("raw_payload", sa.Text(), nullable=False),
        sa.Column("outcome", sa.String(20), nullable=False),
        sa.Column("error_code", sa.String(60)),
        sa.Column("message", sa.String(500), nullable=False),
        sa.Column("timestamp", sa.DateTime(), nullable=False),
    )
    for field in ("session_id", "commessa_id", "event_type", "assembly_code", "outcome", "timestamp"):
        op.create_index(f"ix_welding_scan_events_{field}", "welding_scan_events", [field])


def downgrade():
    op.drop_table("welding_scan_events")
    op.drop_table("welding_scan_sessions")
    op.drop_table("assembly_scan_events")
    op.drop_table("assembly_scan_sessions")
