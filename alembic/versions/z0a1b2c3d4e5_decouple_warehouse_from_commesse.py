"""decouple warehouse from commesse

Revision ID: z0a1b2c3d4e5
Revises: y9z0a1b2c3d4
Create Date: 2026-06-16 00:00:00.000000
"""

from alembic import op


revision = "z0a1b2c3d4e5"
down_revision = "y9z0a1b2c3d4"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Legacy links created before the warehouse/commessa boundary was frozen.
    # Keep the tables/columns for compatibility, but remove operational coupling.
    op.execute("UPDATE materials SET commessa_ref = NULL, quantita_prenotata = 0, quantita_uscita = 0")
    op.execute("UPDATE stock_movements SET destination_commessa = NULL, commessa_id = NULL")
    op.execute("UPDATE distinta_items SET mapped_material_id = NULL")
    op.execute("DELETE FROM stock_reservations")
    op.execute("DELETE FROM material_requests")
    op.execute("DELETE FROM cutting_plans")


def downgrade() -> None:
    # Data cleanup is intentionally not reversible.
    pass
