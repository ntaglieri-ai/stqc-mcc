"""make nome cognome nullable

Revision ID: j3k4l5m6n7o8
Revises: i2j3k4l5m6n7
Create Date: 2026-05-28

"""
from alembic import op
import sqlalchemy as sa

revision = "j3k4l5m6n7o8"
down_revision = "i2j3k4l5m6n7"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("users") as batch_op:
        batch_op.alter_column("nome",    existing_type=sa.String(100), nullable=True)
        batch_op.alter_column("cognome", existing_type=sa.String(100), nullable=True)


def downgrade() -> None:
    # Set empty string before restoring NOT NULL
    op.execute("UPDATE users SET nome = '' WHERE nome IS NULL")
    op.execute("UPDATE users SET cognome = '' WHERE cognome IS NULL")
    with op.batch_alter_table("users") as batch_op:
        batch_op.alter_column("nome",    existing_type=sa.String(100), nullable=False)
        batch_op.alter_column("cognome", existing_type=sa.String(100), nullable=False)
