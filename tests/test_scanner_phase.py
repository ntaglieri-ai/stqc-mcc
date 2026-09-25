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
    def test_activation_choice_persists_and_can_switch(self):
        from backend.app.models.commessa import ScannerDevice
        from backend.app.schemas.admin import ScannerDeviceRead
        engine = create_engine('sqlite://')
        Base.metadata.create_all(engine)
        try:
            with Session(engine) as db:
                scanner = create_scanner_device(ScannerDeviceCreate(
                    scanner_code='ACTIVATION', name='Test', active=False), db)
                scanner_id, token = scanner.id, scanner.device_token
                for activation_type in ('NETUM', 'MOBILE'):
                    update_scanner_device(scanner_id, ScannerDeviceUpdate(
                        activation_type=activation_type, active=True), db)
                    db.expire_all()
                    saved = db.get(ScannerDevice, scanner_id)
                    self.assertEqual(ScannerDeviceRead.model_validate(saved).activation_type, activation_type)
                    self.assertTrue(saved.active)
                    self.assertEqual(saved.device_token, token)
                update_scanner_device(scanner_id, ScannerDeviceUpdate(name='Updated'), db)
                self.assertEqual(saved.activation_type, 'MOBILE')
                update_scanner_device(scanner_id, ScannerDeviceUpdate(active=False), db)
                self.assertFalse(saved.active)
                self.assertEqual(saved.activation_type, 'MOBILE')
        finally:
            engine.dispose()

    def test_unknown_activation_type_rejected(self):
        with self.assertRaises(ValidationError):
            ScannerDeviceUpdate(activation_type='unknown')

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
