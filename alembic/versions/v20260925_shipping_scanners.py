"""Use the unified shipping name for scanner configuration and events."""
from alembic import op

revision = 'v20260925_shipping_scanners'
down_revision = 'u20260924_scanner_activation'
branch_labels = None
depends_on = None


def upgrade():
    op.execute("UPDATE scanner_devices SET scan_mode='SPEDIZIONE' WHERE scan_mode='SPEDIZIONE_AD_HOC'")
    op.execute("UPDATE workshop_scan_attempts SET scan_kind='SHIPPING' WHERE scan_kind='AD_HOC_SHIPPING'")
    op.execute("UPDATE spedizione_ad_hoc_items SET tipo_unita='SPEDIZIONE' WHERE tipo_unita='SPEDIZIONE_AD_HOC'")


def downgrade():
    op.execute("UPDATE scanner_devices SET scan_mode='SPEDIZIONE_AD_HOC' WHERE scan_mode='SPEDIZIONE'")
    op.execute("UPDATE workshop_scan_attempts SET scan_kind='AD_HOC_SHIPPING' WHERE scan_kind='SHIPPING'")
    op.execute("UPDATE spedizione_ad_hoc_items SET tipo_unita='SPEDIZIONE_AD_HOC' WHERE tipo_unita='SPEDIZIONE'")
