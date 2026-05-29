"""add profile_types table and tipo_profilo on distinta_items

Revision ID: q1r2s3t4u5v6
Revises: p3q4r5s6t7u8
Create Date: 2026-05-29
"""
from alembic import op
import sqlalchemy as sa

revision = "q1r2s3t4u5v6"
down_revision = "p3q4r5s6t7u8"
branch_labels = None
depends_on = None

DEFAULTS = [
    ("HEA",   "TRAVI"),
    ("HEB",   "TRAVI"),
    ("HEM",   "TRAVI"),
    ("IPE",   "TRAVI"),
    ("UPN",   "TRAVI"),
    ("PL",    "LAMIERA"),
    ("FL",    "PIATTI"),
    ("L",     "SCATOLATI/ANGOLARI"),
    ("TUBE",  "SCATOLATI/ANGOLARI"),
    ("ANG",   "SCATOLATI/ANGOLARI"),
    ("RD",    "TONDO"),
    ("TONDO", "TONDO"),
    ("SQ",    "QUADRI"),
    ("QUADRO","QUADRI"),
]


def upgrade() -> None:
    op.create_table(
        "profile_types",
        sa.Column("id",       sa.Integer,     primary_key=True),
        sa.Column("prefisso", sa.String(50),  nullable=False, unique=True),
        sa.Column("tipo",     sa.String(100), nullable=False),
    )
    op.create_index("ix_profile_types_prefisso", "profile_types", ["prefisso"])

    # Seed valori standard
    pt = sa.table("profile_types",
                  sa.column("prefisso", sa.String),
                  sa.column("tipo",     sa.String))
    op.bulk_insert(pt, [{"prefisso": p, "tipo": t} for p, t in DEFAULTS])

    # Aggiunge tipo_profilo a distinta_items
    with op.batch_alter_table("distinta_items") as batch_op:
        batch_op.add_column(sa.Column("tipo_profilo", sa.String(100), nullable=True))


def downgrade() -> None:
    with op.batch_alter_table("distinta_items") as batch_op:
        batch_op.drop_column("tipo_profilo")

    op.drop_index("ix_profile_types_prefisso", table_name="profile_types")
    op.drop_table("profile_types")
