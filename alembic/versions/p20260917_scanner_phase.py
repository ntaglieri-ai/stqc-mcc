"""Assign an explicit phase to each scanner."""
from alembic import op
import sqlalchemy as sa

revision = 'p20260917_scanner_phase'
down_revision = 'o20260916_warehouse_change_requests'
branch_labels = None
depends_on = None


def upgrade():
    op.add_column('scanner_devices', sa.Column('fase', sa.String(30), nullable=False, server_default='officina'))
    op.create_index('ix_scanner_devices_fase', 'scanner_devices', ['fase'])
    db = op.get_bind()
    rows = db.execute(sa.text('SELECT s.id, s.scan_mode, w.code FROM scanner_devices s LEFT JOIN workstations w ON w.id = s.postazione_id')).mappings()
    for row in list(rows):
        mode = (row['scan_mode'] or 'OFFICINA').upper()
        code = (row['code'] or '').upper()
        if mode == 'MAGAZZINO_INVENTARIO':
            phase = 'magazzino'
        elif mode == 'MAGAZZINO':
            phase = 'officina'
        elif mode == 'ASSEMBLAGGI':
            phase = 'assemblaggi'
        elif mode == 'SPEDIZIONE_AD_HOC':
            phase = 'in-cantiere'
        elif code.startswith(('SALDAT', 'WELD')):
            phase = 'saldature'
        elif code.startswith(('ASSEMBL', 'ASS')):
            phase = 'assemblaggi'
        elif code.startswith(('SPED', 'CANTIERE')):
            phase = 'in-cantiere'
        elif code.startswith(('VERNIC', 'ZINCAT', 'SABBIAT', 'LAVORAZ')):
            phase = 'lavorazioni'
        else:
            phase = 'officina'
        db.execute(sa.text('UPDATE scanner_devices SET fase = :phase WHERE id = :id'), {'phase': phase, 'id': row['id']})


def downgrade():
    op.drop_index('ix_scanner_devices_fase', table_name='scanner_devices')
    op.drop_column('scanner_devices', 'fase')
