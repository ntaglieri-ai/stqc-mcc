"""add_commessa_fk_to_items_and_movements

Revision ID: 363c854ca0ee
Revises: 0d6be0ef2364
Create Date: 2026-05-23 11:25:42.877116

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '363c854ca0ee'
down_revision: Union[str, Sequence[str], None] = '0d6be0ef2364'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    with op.batch_alter_table('distinta_items', schema=None) as batch_op:
        batch_op.add_column(sa.Column('commessa_id', sa.Integer(), nullable=True))
        batch_op.create_index(batch_op.f('ix_distinta_items_commessa_id'), ['commessa_id'], unique=False)
        batch_op.create_foreign_key('fk_distinta_items_commessa_id', 'commesse', ['commessa_id'], ['id'])

    with op.batch_alter_table('stock_movements', schema=None) as batch_op:
        batch_op.add_column(sa.Column('commessa_id', sa.Integer(), nullable=True))
        batch_op.create_index(batch_op.f('ix_stock_movements_commessa_id'), ['commessa_id'], unique=False)
        batch_op.create_foreign_key('fk_stock_movements_commessa_id', 'commesse', ['commessa_id'], ['id'])


def downgrade() -> None:
    """Downgrade schema."""
    with op.batch_alter_table('stock_movements', schema=None) as batch_op:
        batch_op.drop_constraint('fk_stock_movements_commessa_id', type_='foreignkey')
        batch_op.drop_index(batch_op.f('ix_stock_movements_commessa_id'))
        batch_op.drop_column('commessa_id')

    with op.batch_alter_table('distinta_items', schema=None) as batch_op:
        batch_op.drop_constraint('fk_distinta_items_commessa_id', type_='foreignkey')
        batch_op.drop_index(batch_op.f('ix_distinta_items_commessa_id'))
        batch_op.drop_column('commessa_id')
