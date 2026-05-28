"""add_users_table

Revision ID: c9f1a2b3d4e5
Revises: 76d3be77f4e5
Create Date: 2026-05-25 00:00:00.000000

"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "c9f1a2b3d4e5"
down_revision: Union[str, Sequence[str], None] = "76d3be77f4e5"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "users",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("nome", sa.String(100), nullable=False),
        sa.Column("cognome", sa.String(100), nullable=False),
        sa.Column("email", sa.String(200), nullable=True),
        sa.Column(
            "profilo",
            sa.Enum("Admin", "Responsabile", "Operaio", "Logistica", "Acquisti", name="profiloutente"),
            nullable=False,
        ),
        sa.Column("attivo", sa.Boolean(), nullable=False, server_default=sa.text("1")),
        sa.Column("ultimo_accesso", sa.DateTime(), nullable=True),
        sa.Column("pin_hash", sa.String(255), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=True),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_users_id", "users", ["id"])
    op.create_index("ix_users_email", "users", ["email"], unique=True)

    # Seed default admin user
    op.execute(
        "INSERT INTO users (nome, cognome, email, profilo, attivo, created_at) "
        "VALUES ('Admin', 'Sistema', 'admin@mcc.local', 'Admin', 1, datetime('now'))"
    )


def downgrade() -> None:
    op.drop_index("ix_users_email", table_name="users")
    op.drop_index("ix_users_id", table_name="users")
    op.drop_table("users")
