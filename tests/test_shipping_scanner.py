import unittest
from unittest.mock import patch
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from backend.app.db.base import Base
from backend.app.api.api_v1.endpoints.admin import create_scanner_device
from backend.app.api.api_v1.endpoints.scanner import netum_scan, NetumScanRequest
from backend.app.schemas.admin import ScannerDeviceCreate


class ShippingScannerTests(unittest.TestCase):
    def test_shipping_mode_and_legacy_configuration_use_shipping_handler(self):
        engine = create_engine('sqlite://')
        Base.metadata.create_all(engine)
        try:
            with Session(engine) as db:
                for index, mode in enumerate(('SPEDIZIONE', 'SPEDIZIONE_AD_HOC')):
                    scanner = create_scanner_device(ScannerDeviceCreate(
                        scanner_code=f'SHIP-{index}', name='Spedizioni',
                        fase='in-cantiere', scan_mode=mode), db)
                    self.assertEqual(scanner.scan_mode, 'SPEDIZIONE')
                    with patch('backend.app.api.api_v1.endpoints.scanner.process_ad_hoc_shipping_scan') as handler:
                        handler.return_value = {'ok': True, 'ply': 1, 'msg': 'Trovato'}
                        result = netum_scan(scanner.device_token, NetumScanRequest(msg='CODE'), db)
                        self.assertTrue(result['ok'])
                        handler.assert_called_once_with(db, scanner, 'CODE', None)
        finally:
            engine.dispose()
