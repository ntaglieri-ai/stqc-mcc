"""add workshop scan blocks and attempts

Revision ID: i0j1k2l3m4n5
Revises: h9i0j1k2l3m4
Create Date: 2026-07-06
"""

from alembic import op
import sqlalchemy as sa


revision = "i0j1k2l3m4n5"
down_revision = "h9i0j1k2l3m4"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "workshop_scan_blocks",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("scanner_device_id", sa.Integer(), nullable=True),
        sa.Column("workstation_id", sa.Integer(), nullable=True),
        sa.Column("workstation_code", sa.String(length=80), nullable=False),
        sa.Column("status", sa.String(length=20), nullable=False, server_default="OPEN"),
        sa.Column("started_at", sa.DateTime(), nullable=False),
        sa.Column("closed_at", sa.DateTime(), nullable=True),
        sa.Column("start_payload", sa.String(length=220), nullable=False),
        sa.Column("end_payload", sa.String(length=220), nullable=True),
        sa.Column("piece_count", sa.Integer(), nullable=False, server_default="0"),
        sa.ForeignKeyConstraint(["scanner_device_id"], ["scanner_devices.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["workstation_id"], ["workstations.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
    )
    for column in (
        "id",
        "scanner_device_id",
        "workstation_id",
        "workstation_code",
        "status",
        "started_at",
        "closed_at",
    ):
        op.create_index(f"ix_workshop_scan_blocks_{column}", "workshop_scan_blocks", [column])
    op.create_index(
        "uq_workshop_scan_blocks_open_scanner",
        "workshop_scan_blocks",
        ["scanner_device_id"],
        unique=True,
        sqlite_where=sa.text("status = 'OPEN'"),
        postgresql_where=sa.text("status = 'OPEN'"),
    )

    op.create_table(
        "workshop_scan_attempts",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("scanner_device_id", sa.Integer(), nullable=True),
        sa.Column("scanner_external_id", sa.String(length=120), nullable=True),
        sa.Column("workstation_id", sa.Integer(), nullable=True),
        sa.Column("scan_block_id", sa.Integer(), nullable=True),
        sa.Column("piece_id", sa.Integer(), nullable=True),
        sa.Column("raw_payload", sa.Text(), nullable=False),
        sa.Column("scan_kind", sa.String(length=30), nullable=False),
        sa.Column("outcome", sa.String(length=20), nullable=False),
        sa.Column("error_code", sa.String(length=60), nullable=True),
        sa.Column("message", sa.String(length=500), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(["piece_id"], ["pieces.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["scan_block_id"], ["workshop_scan_blocks.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["scanner_device_id"], ["scanner_devices.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["workstation_id"], ["workstations.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
    )
    for column in (
        "id",
        "scanner_device_id",
        "scanner_external_id",
        "workstation_id",
        "scan_block_id",
        "piece_id",
        "scan_kind",
        "outcome",
        "error_code",
        "created_at",
    ):
        op.create_index(f"ix_workshop_scan_attempts_{column}", "workshop_scan_attempts", [column])

    with op.batch_alter_table("piece_work_sessions") as batch:
        batch.add_column(sa.Column("scanner_device_id", sa.Integer(), nullable=True))
        batch.add_column(sa.Column("scan_block_id", sa.Integer(), nullable=True))
        batch.create_foreign_key(
            "fk_piece_work_sessions_scanner_device",
            "scanner_devices",
            ["scanner_device_id"],
            ["id"],
            ondelete="SET NULL",
        )
        batch.create_foreign_key(
            "fk_piece_work_sessions_scan_block",
            "workshop_scan_blocks",
            ["scan_block_id"],
            ["id"],
            ondelete="SET NULL",
        )
        batch.create_index("ix_piece_work_sessions_scanner_device_id", ["scanner_device_id"])
        batch.create_index("ix_piece_work_sessions_scan_block_id", ["scan_block_id"])

    with op.batch_alter_table("piece_scan_events") as batch:
        batch.add_column(sa.Column("scanner_device_id", sa.Integer(), nullable=True))
        batch.add_column(sa.Column("scan_block_id", sa.Integer(), nullable=True))
        batch.create_foreign_key(
            "fk_piece_scan_events_scanner_device",
            "scanner_devices",
            ["scanner_device_id"],
            ["id"],
            ondelete="SET NULL",
        )
        batch.create_foreign_key(
            "fk_piece_scan_events_scan_block",
            "workshop_scan_blocks",
            ["scan_block_id"],
            ["id"],
            ondelete="SET NULL",
        )
        batch.create_index("ix_piece_scan_events_scanner_device_id", ["scanner_device_id"])
        batch.create_index("ix_piece_scan_events_scan_block_id", ["scan_block_id"])


def downgrade() -> None:
    with op.batch_alter_table("piece_scan_events") as batch:
        batch.drop_index("ix_piece_scan_events_scan_block_id")
        batch.drop_index("ix_piece_scan_events_scanner_device_id")
        batch.drop_constraint("fk_piece_scan_events_scan_block", type_="foreignkey")
        batch.drop_constraint("fk_piece_scan_events_scanner_device", type_="foreignkey")
        batch.drop_column("scan_block_id")
        batch.drop_column("scanner_device_id")

    with op.batch_alter_table("piece_work_sessions") as batch:
        batch.drop_index("ix_piece_work_sessions_scan_block_id")
        batch.drop_index("ix_piece_work_sessions_scanner_device_id")
        batch.drop_constraint("fk_piece_work_sessions_scan_block", type_="foreignkey")
        batch.drop_constraint("fk_piece_work_sessions_scanner_device", type_="foreignkey")
        batch.drop_column("scan_block_id")
        batch.drop_column("scanner_device_id")

    op.drop_table("workshop_scan_attempts")
    op.drop_table("workshop_scan_blocks")
