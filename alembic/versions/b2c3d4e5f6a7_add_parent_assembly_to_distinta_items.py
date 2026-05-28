"""add_parent_assembly_to_distinta_items

Revision ID: b2c3d4e5f6a7
Revises: a1b2c3d4e5f6
Create Date: 2026-05-28 00:01:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = 'b2c3d4e5f6a7'
down_revision: Union[str, Sequence[str], None] = 'a1b2c3d4e5f6'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    with op.batch_alter_table('distinta_items', schema=None) as batch_op:
        batch_op.add_column(sa.Column('parent_assembly', sa.String(200), nullable=True))


def downgrade() -> None:
    with op.batch_alter_table('distinta_items', schema=None) as batch_op:
        batch_op.drop_column('parent_assembly')
