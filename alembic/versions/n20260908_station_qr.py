"""Configurable station QR codes."""
from alembic import op
import sqlalchemy as sa
revision = 'n20260908_station_qr'
down_revision = 'm20260904_design_times'
branch_labels = None
depends_on = None

def upgrade():
    op.create_table('workstation_qr_codes',
        sa.Column('id', sa.Integer(), primary_key=True),
        sa.Column('workstation_id', sa.Integer(), sa.ForeignKey('workstations.id'), nullable=False),
        sa.Column('label', sa.String(160), nullable=False),
        sa.Column('actions', sa.JSON(), nullable=False),
        sa.Column('description', sa.Text()),
        sa.Column('behavior', sa.String(20), nullable=False),
        sa.Column('payload', sa.String(160), nullable=False),
        sa.Column('active', sa.Boolean(), nullable=False),
        sa.Column('created_at', sa.DateTime()))
    op.create_index('ix_workstation_qr_codes_workstation_id', 'workstation_qr_codes', ['workstation_id'])
    op.create_index('ix_workstation_qr_codes_payload', 'workstation_qr_codes', ['payload'], unique=True)

def downgrade():
    op.drop_table('workstation_qr_codes')
