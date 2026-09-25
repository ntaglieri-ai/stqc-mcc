"""Materialize legacy workshop boundaries so deleted events cannot regenerate."""
from alembic import op
import sqlalchemy as sa

revision = 'x20260925_register_events'
down_revision = 'w20260925_event_details'
branch_labels = None
depends_on = None


def upgrade():
    db = op.get_bind()
    for kind, time_column, payload_column, message in (
        ('WORKSTATION_START', 'started_at', 'start_payload', 'INIZIO registrato'),
        ('WORKSTATION_END', 'closed_at', 'end_payload', 'FINE registrata'),
    ):
        db.execute(sa.text(f"""
            INSERT INTO workshop_scan_attempts
                (scanner_device_id, workstation_id, scan_block_id, raw_payload,
                 scan_kind, outcome, message, created_at)
            SELECT b.scanner_device_id, b.workstation_id, b.id,
                   COALESCE(b.{payload_column}, ''), :kind, 'OK', :message, b.{time_column}
            FROM workshop_scan_blocks b
            WHERE b.{time_column} IS NOT NULL AND NOT EXISTS (
                SELECT 1 FROM workshop_scan_attempts a WHERE a.scan_block_id = b.id
                  AND a.scan_kind = :kind AND a.outcome = 'OK')
        """), {'kind': kind, 'message': message})


def downgrade():
    # These are historical records, not schema objects: retain them on downgrade.
    pass
