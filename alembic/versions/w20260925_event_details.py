"""Historical details on existing operational event records."""
from alembic import op
import sqlalchemy as sa

revision = 'w20260925_event_details'
down_revision = 'v20260925_shipping_scanners'
branch_labels = None
depends_on = None
TABLES = ('piece_scan_events', 'workshop_scan_attempts', 'scanner_phase_events',
          'assembly_scan_events', 'welding_scan_events', 'commessa_progettazione_eventi',
          'stock_movements', 'warehouse_change_requests', 'scan_eventi')


def upgrade():
    for table in TABLES:
        op.add_column(table, sa.Column('details_snapshot', sa.JSON(), nullable=True))


def downgrade():
    for table in reversed(TABLES):
        op.drop_column(table, 'details_snapshot')
