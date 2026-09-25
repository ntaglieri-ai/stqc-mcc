"""Persist the selected scanner activation device."""
from alembic import op
import sqlalchemy as sa

revision = 'u20260924_scanner_activation'
down_revision = 't20260920_assembly_scans'
branch_labels = None
depends_on = None


def upgrade():
    op.add_column('scanner_devices', sa.Column('activation_type', sa.String(10), nullable=True))


def downgrade():
    op.drop_column('scanner_devices', 'activation_type')
