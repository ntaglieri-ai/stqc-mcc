"""Record design phase transitions without fabricating historical timestamps."""
from alembic import op
import sqlalchemy as sa

revision = 'm20260904_design_times'
down_revision = 'u1v2w3x4y5z6'
branch_labels = None
depends_on = None


def upgrade():
    op.add_column('commessa_progettazione', sa.Column('iniziata_at', sa.DateTime(), nullable=True))
    op.add_column('commessa_progettazione', sa.Column('completata_at', sa.DateTime(), nullable=True))


def downgrade():
    with op.batch_alter_table('commessa_progettazione') as batch:
        batch.drop_column('completata_at')
        batch.drop_column('iniziata_at')
