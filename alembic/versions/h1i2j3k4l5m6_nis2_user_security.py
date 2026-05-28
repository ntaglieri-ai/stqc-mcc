"""nis2_user_security — gruppi, lockout, attributi, audit log

Revision ID: h1i2j3k4l5m6
Revises: b2c3d4e5f6a7
Create Date: 2026-05-28 00:00:00.000000
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "h1i2j3k4l5m6"
down_revision: Union[str, Sequence[str], None] = "b2c3d4e5f6a7"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # 1. Nuovi campi di sicurezza su users
    with op.batch_alter_table("users", schema=None) as batch_op:
        batch_op.add_column(sa.Column("failed_attempts", sa.Integer(), nullable=False, server_default="0"))
        batch_op.add_column(sa.Column("locked_until", sa.DateTime(), nullable=True))

    # 2. Migrazione valori enum: Responsabile → Direttore, Operaio → Operatore
    op.execute("UPDATE users SET profilo='Direttore' WHERE profilo='Responsabile'")
    op.execute("UPDATE users SET profilo='Operatore' WHERE profilo='Operaio'")

    # 3. Tabella attributi utente
    op.create_table(
        "user_attributes",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("user_id", sa.Integer(), sa.ForeignKey("users.id", ondelete="CASCADE"), unique=True, nullable=False),
        sa.Column("postazioni_assegnate", sa.JSON(), nullable=True),
        sa.Column("commesse_visibili", sa.JSON(), nullable=True),
        sa.Column("permessi", sa.JSON(), nullable=True),
    )

    # 4. Tabella audit log (append-only)
    op.create_table(
        "audit_logs",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("timestamp", sa.DateTime(), nullable=False),
        sa.Column("user_id", sa.Integer(), sa.ForeignKey("users.id", ondelete="SET NULL"), nullable=True),
        sa.Column("username", sa.String(100), nullable=True),
        sa.Column("gruppo", sa.String(50), nullable=True),
        sa.Column("action", sa.String(50), nullable=False),
        sa.Column("target_user_id", sa.Integer(), nullable=True),
        sa.Column("ip_address", sa.String(50), nullable=True),
        sa.Column("details", sa.Text(), nullable=True),
    )
    op.create_index("ix_audit_logs_timestamp", "audit_logs", ["timestamp"])
    op.create_index("ix_audit_logs_action", "audit_logs", ["action"])


def downgrade() -> None:
    op.drop_table("audit_logs")
    op.drop_table("user_attributes")
    with op.batch_alter_table("users", schema=None) as batch_op:
        batch_op.drop_column("locked_until")
        batch_op.drop_column("failed_attempts")
    op.execute("UPDATE users SET profilo='Responsabile' WHERE profilo='Direttore'")
    op.execute("UPDATE users SET profilo='Operaio' WHERE profilo='Operatore'")
