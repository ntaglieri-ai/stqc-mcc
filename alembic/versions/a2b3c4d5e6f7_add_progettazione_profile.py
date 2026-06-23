"""add progettazione profile

Revision ID: a2b3c4d5e6f7
Revises: z0a1b2c3d4e5
Create Date: 2026-06-23
"""

from alembic import op


revision = "a2b3c4d5e6f7"
down_revision = "a1b2c3d4e5f7"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("UPDATE users SET profilo='Direttore' WHERE profilo='Responsabile'")
    op.execute(
        "UPDATE users SET profilo='Logistica', attivo=0 "
        "WHERE profilo IN ('Operaio', 'Operatore') OR username='operatore'"
    )
    op.execute("DELETE FROM group_permissions WHERE group_name='Operatore'")
    op.execute("DELETE FROM groups WHERE name='Operatore'")
    op.execute(
        "INSERT INTO groups (name, postazioni) "
        "SELECT 'Progettazione', '[]' "
        "WHERE NOT EXISTS (SELECT 1 FROM groups WHERE name='Progettazione')"
    )
    op.execute(
        "INSERT INTO group_permissions (group_name, sezione, livello) "
        "SELECT 'Progettazione', 'commesse', 'write' "
        "WHERE NOT EXISTS (SELECT 1 FROM group_permissions WHERE group_name='Progettazione' AND sezione='commesse')"
    )
    op.execute(
        "INSERT INTO group_permissions (group_name, sezione, livello) "
        "SELECT 'Progettazione', 'magazzino', 'read' "
        "WHERE NOT EXISTS (SELECT 1 FROM group_permissions WHERE group_name='Progettazione' AND sezione='magazzino')"
    )
    op.execute(
        "INSERT INTO group_permissions (group_name, sezione, livello) "
        "SELECT 'Progettazione', 'admin', 'none' "
        "WHERE NOT EXISTS (SELECT 1 FROM group_permissions WHERE group_name='Progettazione' AND sezione='admin')"
    )


def downgrade() -> None:
    op.execute("DELETE FROM group_permissions WHERE group_name='Progettazione'")
    op.execute("DELETE FROM groups WHERE name='Progettazione'")
