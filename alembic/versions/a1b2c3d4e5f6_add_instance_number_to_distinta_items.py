"""add_instance_number_to_distinta_items

Revision ID: a1b2c3d4e5f6
Revises: f1g2h3i4j5k6
Create Date: 2026-05-28 00:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = 'a1b2c3d4e5f6'
down_revision: Union[str, Sequence[str], None] = 'f1g2h3i4j5k6'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    with op.batch_alter_table('distinta_items', schema=None) as batch_op:
        batch_op.add_column(sa.Column('instance_number', sa.Integer(), nullable=True))


def downgrade() -> None:
    with op.batch_alter_table('distinta_items', schema=None) as batch_op:
        batch_op.drop_column('instance_number')
