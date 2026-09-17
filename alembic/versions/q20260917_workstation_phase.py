"""Explicit phase for workstations."""
from alembic import op
import sqlalchemy as sa

revision = 'q20260917_workstation_phase'
down_revision = 'p20260917_scanner_phase'
branch_labels = None
depends_on = None


def upgrade():
    op.add_column('workstations', sa.Column('fase', sa.String(30), nullable=False, server_default='officina'))
    op.create_index('ix_workstations_fase', 'workstations', ['fase'])
    db = op.get_bind()
    for row in list(db.execute(sa.text('SELECT id, code FROM workstations')).mappings()):
        code = (row['code'] or '').upper()
        phase = 'officina'
        for prefixes, candidate in [(('MAGAZZINO',), 'magazzino'), (('SALDAT', 'WELD'), 'saldature'),
                                    (('ASSEMBL', 'ASS'), 'assemblaggi'), (('SPED', 'CANTIERE'), 'in-cantiere'),
                                    (('VERNIC', 'ZINCAT', 'SABBIAT', 'LAVORAZ'), 'lavorazioni')]:
            if code.startswith(prefixes):
                phase = candidate
                break
        db.execute(sa.text('UPDATE workstations SET fase=:phase WHERE id=:id'), {'phase': phase, 'id': row['id']})


def downgrade():
    op.drop_index('ix_workstations_fase', table_name='workstations')
    op.drop_column('workstations', 'fase')
