"""add piece qr tracking db

Revision ID: b3c4d5e6f7g8
Revises: a2b3c4d5e6f7
Create Date: 2026-06-23
"""

from alembic import op
import sqlalchemy as sa


revision = "b3c4d5e6f7g8"
down_revision = "a2b3c4d5e6f7"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("pieces") as batch:
        batch.add_column(sa.Column("uuid", sa.String(length=36), nullable=True))
        batch.add_column(sa.Column("qr_status", sa.String(length=20), nullable=False, server_default="DRAFT"))
        batch.add_column(sa.Column("spessore_mm", sa.Numeric(12, 2), nullable=True))
        batch.add_column(sa.Column("materiale_origine_status", sa.String(length=20), nullable=False, server_default="VUOTO"))
        batch.add_column(sa.Column("note_materiale", sa.Text(), nullable=True))
        batch.add_column(sa.Column("ultimo_lavoro", sa.String(length=100), nullable=True))
        batch.add_column(sa.Column("ultimo_evento", sa.String(length=30), nullable=True))
        batch.add_column(sa.Column("ultimo_evento_at", sa.DateTime(), nullable=True))
        batch.add_column(sa.Column("lavorazione_aperta_id", sa.Integer(), nullable=True))
        batch.create_index("ix_pieces_uuid", ["uuid"], unique=True)
        batch.create_index("ix_pieces_qr_status", ["qr_status"])
        batch.create_index("ix_pieces_materiale_origine_status", ["materiale_origine_status"])
        batch.create_index("ix_pieces_ultimo_evento_at", ["ultimo_evento_at"])
        batch.create_index("ix_pieces_lavorazione_aperta_id", ["lavorazione_aperta_id"])

    op.execute(
        """
        UPDATE pieces
        SET uuid = lower(hex(randomblob(4))) || '-' ||
                   lower(hex(randomblob(2))) || '-' ||
                   lower(hex(randomblob(2))) || '-' ||
                   lower(hex(randomblob(2))) || '-' ||
                   lower(hex(randomblob(6)))
        WHERE uuid IS NULL
        """
    )
    op.execute("UPDATE pieces SET qr_status='ACTIVE' WHERE qr_attivo=1")
    op.execute("UPDATE pieces SET qr_status='DRAFT' WHERE qr_attivo=0 AND stato_attuale!='SUPERATO'")
    op.execute("UPDATE pieces SET qr_status='ARCHIVED' WHERE stato_attuale='SUPERATO'")

    with op.batch_alter_table("pieces") as batch:
        batch.alter_column("uuid", nullable=False)

    op.create_table(
        "workstations",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("code", sa.String(length=80), nullable=False),
        sa.Column("name", sa.String(length=160), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("active", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("start_qr_code", sa.String(length=120), nullable=False),
        sa.Column("end_qr_code", sa.String(length=120), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=True),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("code"),
        sa.UniqueConstraint("start_qr_code"),
        sa.UniqueConstraint("end_qr_code"),
    )
    op.create_index("ix_workstations_id", "workstations", ["id"])
    op.create_index("ix_workstations_code", "workstations", ["code"], unique=True)
    op.create_index("ix_workstations_active", "workstations", ["active"])
    op.create_index("ix_workstations_start_qr_code", "workstations", ["start_qr_code"], unique=True)
    op.create_index("ix_workstations_end_qr_code", "workstations", ["end_qr_code"], unique=True)

    op.create_table(
        "work_types",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("code", sa.String(length=80), nullable=False),
        sa.Column("name", sa.String(length=160), nullable=False),
        sa.Column("category", sa.String(length=100), nullable=True),
        sa.Column("active", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("created_at", sa.DateTime(), nullable=True),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("code"),
    )
    op.create_index("ix_work_types_id", "work_types", ["id"])
    op.create_index("ix_work_types_code", "work_types", ["code"], unique=True)
    op.create_index("ix_work_types_category", "work_types", ["category"])
    op.create_index("ix_work_types_active", "work_types", ["active"])

    op.create_table(
        "piece_work_sessions",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("piece_id", sa.Integer(), nullable=False),
        sa.Column("commessa_id", sa.Integer(), nullable=False),
        sa.Column("revisione_id", sa.Integer(), nullable=False),
        sa.Column("assemblato_id", sa.String(length=200), nullable=True),
        sa.Column("postazione_id", sa.Integer(), nullable=True),
        sa.Column("postazione_code", sa.String(length=80), nullable=False),
        sa.Column("lavoro_id", sa.Integer(), nullable=True),
        sa.Column("lavoro_code", sa.String(length=80), nullable=True),
        sa.Column("started_at", sa.DateTime(), nullable=False),
        sa.Column("expected_close_at", sa.DateTime(), nullable=False),
        sa.Column("closed_at", sa.DateTime(), nullable=True),
        sa.Column("duration_seconds", sa.Integer(), nullable=True),
        sa.Column("status", sa.String(length=30), nullable=False, server_default="OPEN"),
        sa.Column("opened_by_id", sa.Integer(), nullable=True),
        sa.Column("closed_by_id", sa.Integer(), nullable=True),
        sa.Column("open_event_id", sa.Integer(), nullable=True),
        sa.Column("close_event_id", sa.Integer(), nullable=True),
        sa.Column("note", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=True),
        sa.Column("updated_at", sa.DateTime(), nullable=True),
        sa.ForeignKeyConstraint(["closed_by_id"], ["users.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["commessa_id"], ["commesse.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["lavoro_id"], ["work_types.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["opened_by_id"], ["users.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["piece_id"], ["pieces.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["postazione_id"], ["workstations.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["revisione_id"], ["commessa_revisioni.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    for col in (
        "id", "piece_id", "commessa_id", "revisione_id", "assemblato_id",
        "postazione_id", "postazione_code", "lavoro_id", "lavoro_code",
        "started_at", "expected_close_at", "closed_at", "status",
        "opened_by_id", "closed_by_id", "open_event_id", "close_event_id",
    ):
        op.create_index(f"ix_piece_work_sessions_{col}", "piece_work_sessions", [col])

    op.create_table(
        "piece_scan_events",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("piece_id", sa.Integer(), nullable=False),
        sa.Column("qr_code", sa.String(length=220), nullable=False),
        sa.Column("commessa_id", sa.Integer(), nullable=False),
        sa.Column("revisione_id", sa.Integer(), nullable=False),
        sa.Column("assemblato_id", sa.String(length=200), nullable=True),
        sa.Column("postazione_id", sa.Integer(), nullable=True),
        sa.Column("postazione_code", sa.String(length=80), nullable=True),
        sa.Column("lavoro_id", sa.Integer(), nullable=True),
        sa.Column("lavoro_code", sa.String(length=80), nullable=True),
        sa.Column("event_type", sa.String(length=40), nullable=False),
        sa.Column("timestamp", sa.DateTime(), nullable=False),
        sa.Column("operatore_id", sa.Integer(), nullable=True),
        sa.Column("session_id", sa.Integer(), nullable=True),
        sa.Column("metadata_json", sa.JSON(), nullable=True),
        sa.Column("note", sa.Text(), nullable=True),
        sa.ForeignKeyConstraint(["commessa_id"], ["commesse.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["lavoro_id"], ["work_types.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["operatore_id"], ["users.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["piece_id"], ["pieces.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["postazione_id"], ["workstations.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["revisione_id"], ["commessa_revisioni.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["session_id"], ["piece_work_sessions.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
    )
    for col in (
        "id", "piece_id", "qr_code", "commessa_id", "revisione_id",
        "assemblato_id", "postazione_id", "postazione_code", "lavoro_id",
        "lavoro_code", "event_type", "timestamp", "operatore_id", "session_id",
    ):
        op.create_index(f"ix_piece_scan_events_{col}", "piece_scan_events", [col])

    _seed_workstations()
    _seed_work_types()


def downgrade() -> None:
    op.drop_table("piece_scan_events")
    op.drop_table("piece_work_sessions")
    op.drop_table("work_types")
    op.drop_table("workstations")
    with op.batch_alter_table("pieces") as batch:
        batch.drop_index("ix_pieces_lavorazione_aperta_id")
        batch.drop_index("ix_pieces_ultimo_evento_at")
        batch.drop_index("ix_pieces_materiale_origine_status")
        batch.drop_index("ix_pieces_qr_status")
        batch.drop_index("ix_pieces_uuid")
        batch.drop_column("lavorazione_aperta_id")
        batch.drop_column("ultimo_evento_at")
        batch.drop_column("ultimo_evento")
        batch.drop_column("ultimo_lavoro")
        batch.drop_column("note_materiale")
        batch.drop_column("materiale_origine_status")
        batch.drop_column("spessore_mm")
        batch.drop_column("qr_status")
        batch.drop_column("uuid")


def _seed_workstations() -> None:
    rows = [
        ("TAGLIO01", "Taglio 01"),
        ("FORATURA01", "Foratura 01"),
        ("SALDATURA01", "Saldatura 01"),
        ("ASS01", "Assemblaggio 01"),
        ("VERNICIATURA01", "Verniciatura 01"),
        ("SPEDIZIONE01", "Spedizione 01"),
    ]
    for code, name in rows:
        op.execute(
            f"""
            INSERT INTO workstations (code, name, active, start_qr_code, end_qr_code, created_at)
            SELECT '{code}', '{name}', 1, '{code}_START', '{code}_END', CURRENT_TIMESTAMP
            WHERE NOT EXISTS (SELECT 1 FROM workstations WHERE code='{code}')
            """
        )


def _seed_work_types() -> None:
    rows = [
        ("TAGLIO", "Taglio", "OFFICINA"),
        ("FORATURA", "Foratura", "OFFICINA"),
        ("SALDATURA", "Saldatura", "OFFICINA"),
        ("ASSEMBLAGGIO", "Assemblaggio", "OFFICINA"),
        ("VERNICIATURA", "Verniciatura", "FINITURA"),
        ("SPEDIZIONE", "Spedizione", "LOGISTICA"),
    ]
    for code, name, category in rows:
        op.execute(
            f"""
            INSERT INTO work_types (code, name, category, active, created_at)
            SELECT '{code}', '{name}', '{category}', 1, CURRENT_TIMESTAMP
            WHERE NOT EXISTS (SELECT 1 FROM work_types WHERE code='{code}')
            """
        )
