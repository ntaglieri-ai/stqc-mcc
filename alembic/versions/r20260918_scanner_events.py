"""Collect scans by selected station and phase."""
from alembic import op
import sqlalchemy as sa
revision = 'r20260918_scanner_events'
down_revision = 'q20260917_workstation_phase'
branch_labels = None
depends_on = None

def upgrade():
    op.create_table('scanner_phase_events',
        sa.Column('id', sa.Integer(), primary_key=True),
        sa.Column('scanner_device_id', sa.Integer(), sa.ForeignKey('scanner_devices.id', ondelete='SET NULL')),
        sa.Column('commessa_id', sa.Integer(), sa.ForeignKey('commesse.id', ondelete='CASCADE'), nullable=False),
        sa.Column('revisione_id', sa.Integer(), sa.ForeignKey('commessa_revisioni.id', ondelete='CASCADE'), nullable=False),
        sa.Column('workstation_id', sa.Integer(), sa.ForeignKey('workstations.id', ondelete='SET NULL')),
        sa.Column('workstation_code', sa.String(80), nullable=False),
        sa.Column('fase', sa.String(30), nullable=False),
        sa.Column('entity', sa.String(30), nullable=False),
        sa.Column('entity_code', sa.String(220), nullable=False),
        sa.Column('raw_payload', sa.Text(), nullable=False),
        sa.Column('external_id', sa.String(120)),
        sa.Column('timestamp', sa.DateTime(), nullable=False))
    for field in ('scanner_device_id', 'commessa_id', 'fase'):
        op.create_index('ix_scanner_phase_events_'+field, 'scanner_phase_events', [field])

def downgrade():
    op.drop_table('scanner_phase_events')
