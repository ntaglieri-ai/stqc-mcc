import tempfile
import unittest
from pathlib import Path
from backend.app.services.scanner_links import scanner_origin


class ScannerLinkTests(unittest.TestCase):
    def test_localhost_and_wifi_use_configured_https_gateway(self):
        with tempfile.TemporaryDirectory() as folder:
            config = Path(folder) / 'origin.txt'
            config.write_text('https://192.168.0.120:8443', encoding='utf-8')
            for origin in ('http://localhost:8000', 'http://127.0.0.1:8000', 'http://192.168.0.120:8000'):
                self.assertEqual(scanner_origin(origin, config), 'https://192.168.0.120:8443')

    def test_public_site_never_uses_local_config(self):
        with tempfile.TemporaryDirectory() as folder:
            config = Path(folder) / 'origin.txt'
            config.write_text('https://192.168.0.120:8443', encoding='utf-8')
            self.assertEqual(scanner_origin('http://stqc.stqcmcc.it/', config), 'https://stqc.stqcmcc.it')

    def test_missing_local_gateway_does_not_generate_unusable_phone_link(self):
        with tempfile.TemporaryDirectory() as folder:
            config = Path(folder) / 'missing.txt'
            with self.assertRaises(ValueError):
                scanner_origin('http://localhost:8000', config)
            self.assertEqual(scanner_origin('https://192.168.0.120:8443', config), 'https://192.168.0.120:8443')
