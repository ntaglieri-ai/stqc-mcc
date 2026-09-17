import unittest
from pydantic import ValidationError
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from backend.app.api.api_v1.endpoints.admin import create_scanner_device, update_scanner_device
from backend.app.api.api_v1.endpoints.officina import scanners_for_phase
from backend.app.db.base import Base
from backend.app.schemas.admin import ScannerDeviceCreate, ScannerDeviceUpdate
from backend.app.schemas.admin import WorkstationCreate, WorkstationUpdate
from backend.app.api.api_v1.endpoints.admin import create_workstation, update_workstation, list_workstation_qr_codes


class ScannerPhaseTests(unittest.TestCase):
    def test_workstation_phase_is_saved_and_exposed_without_changing_scanner(self):
        engine = create_engine('sqlite://')
        Base.metadata.create_all(engine)
        try:
            with Session(engine) as db:
                station = create_workstation(WorkstationCreate(code='TEST', name='Test', fase='saldature'), db)
                scanner = create_scanner_device(ScannerDeviceCreate(scanner_code='TEST', name='Test',
                    postazione_id=station.id, fase='officina'), db)
                self.assertEqual(list_workstation_qr_codes(False, db)['items'][0]['fase'], 'saldature')
                update_workstation(station.id, WorkstationUpdate(fase='assemblaggi'), db)
                self.assertEqual(station.fase, 'assemblaggi')
                self.assertEqual(scanner.fase, 'officina')
                update_workstation(station.id, WorkstationUpdate(name='Rinominata'), db)
                self.assertEqual(station.fase, 'assemblaggi')
        finally:
            engine.dispose()

    def test_explicit_phase_controls_lists_and_can_be_changed(self):
        engine = create_engine('sqlite://')
        Base.metadata.create_all(engine)
        try:
            with Session(engine) as db:
                scanner = create_scanner_device(ScannerDeviceCreate(
                    scanner_code='TEST', name='Test', scan_mode='OFFICINA', fase='saldature'), db)
                self.assertEqual(len(scanners_for_phase('saldature', db)['items']), 1)
                self.assertEqual(scanners_for_phase('officina', db)['items'], [])
                update_scanner_device(scanner.id, ScannerDeviceUpdate(fase='assemblaggi'), db)
                self.assertEqual(scanners_for_phase('saldature', db)['items'], [])
                self.assertEqual(len(scanners_for_phase('assemblaggi', db)['items']), 1)
                self.assertEqual(scanner.scan_mode, 'OFFICINA')
                update_scanner_device(scanner.id, ScannerDeviceUpdate(name='Nuovo nome'), db)
                self.assertEqual(scanner.fase, 'assemblaggi')
        finally:
            engine.dispose()

    def test_unknown_phase_rejected(self):
        with self.assertRaises(ValidationError):
            ScannerDeviceUpdate(fase='unknown')
