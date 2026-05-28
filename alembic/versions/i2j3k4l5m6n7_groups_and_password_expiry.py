"""groups_and_password_expiry — tabella groups, group_permissions, password_changed_at

Revision ID: i2j3k4l5m6n7
Revises: h1i2j3k4l5m6
Create Date: 2026-05-28 00:00:00.000000
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "i2j3k4l5m6n7"
down_revision: Union[str, Sequence[str], None] = "h1i2j3k4l5m6"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

_GROUPS = [
    ("Admin",     "Amministratori di sistema"),
    ("Direttore", "Direzione e supervisione"),
    ("Operatore", "Operatori di produzione"),
    ("Logistica", "Magazzino e logistica"),
    ("Acquisti",  "Ufficio acquisti"),
]

_PERMISSIONS = {
    "Admin":     {"commesse": "write", "magazzino": "write",  "admin": "write"},
    "Direttore": {"commesse": "write", "magazzino": "read",   "admin": "none"},
    "Operatore": {"commesse": "read",  "magazzino": "write",  "admin": "none"},
    "Logistica": {"commesse": "read",  "magazzino": "write",  "admin": "none"},
    "Acquisti":  {"commesse": "read",  "magazzino": "read",   "admin": "none"},
}

_POSTAZIONI = {
    "Admin":     [],
    "Direttore": [],
    "Operatore": ["Taglio", "Saldatura", "Montaggio", "Collaudo", "Verniciatura"],
    "Logistica": ["Magazzino"],
    "Acquisti":  [],
}


def upgrade() -> None:
    import json

    # 1. password_changed_at on users
    with op.batch_alter_table("users", schema=None) as batch_op:
        batch_op.add_column(sa.Column("password_changed_at", sa.DateTime(), nullable=True))

    # 2. groups table
    op.create_table(
        "groups",
        sa.Column("id",          sa.Integer(),     primary_key=True),
        sa.Column("name",        sa.String(50),    unique=True, nullable=False),
        sa.Column("descrizione", sa.Text(),         nullable=True),
        sa.Column("postazioni",  sa.JSON(),         nullable=True),
    )
    op.create_index("ix_groups_name", "groups", ["name"])

    # 3. group_permissions table
    op.create_table(
        "group_permissions",
        sa.Column("id",         sa.Integer(),    primary_key=True),
        sa.Column("group_name", sa.String(50),   sa.ForeignKey("groups.name", ondelete="CASCADE"), nullable=False),
        sa.Column("sezione",    sa.String(50),   nullable=False),
        sa.Column("livello",    sa.String(10),   nullable=False, server_default="none"),
    )
    op.create_index("ix_group_permissions_group_name", "group_permissions", ["group_name"])

    # 4. Seed groups + permissions
    conn = op.get_bind()
    group_ins = sa.text(
        "INSERT INTO groups (name, descrizione, postazioni) VALUES (:name, :desc, :post)"
    )
    perm_ins = sa.text(
        "INSERT INTO group_permissions (group_name, sezione, livello) VALUES (:gname, :sez, :liv)"
    )
    for name, desc in _GROUPS:
        conn.execute(group_ins, {"name": name, "desc": desc, "post": json.dumps(_POSTAZIONI[name])})
        for sezione, livello in _PERMISSIONS[name].items():
            conn.execute(perm_ins, {"gname": name, "sez": sezione, "liv": livello})


def downgrade() -> None:
    op.drop_table("group_permissions")
    op.drop_table("groups")
    with op.batch_alter_table("users", schema=None) as batch_op:
        batch_op.drop_column("password_changed_at")
