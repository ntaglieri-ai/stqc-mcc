import unittest

from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from backend.app.api.api_v1.endpoints.scanner import NetumScanRequest, netum_scan
from backend.app.db.base import Base
from backend.app.models.commessa import ScannerDevice, PieceWorkSession, WorkshopScanBlock
from backend.app.models.warehouse import Material, WarehouseItem, ScanEvento, StockMovement, WarehouseChangeRequest, WarehouseChangeRequestStatus
from backend.app.api.api_v1.endpoints.warehouse import _apply_change_request_payload


class InventoryScanTests(unittest.TestCase):
    def test_inventory_records_presence_without_mapping_or_work_sessions(self):
        engine = create_engine('sqlite://')
        Base.metadata.create_all(engine)
        try:
            with Session(engine) as db:
                material = Material(code='TEST', description='Test', unit='PZ')
                scanner = ScannerDevice(scanner_code='INV', name='Inventario', device_token='test',
                                        scan_mode='MAGAZZINO_INVENTARIO', active=True)
                db.add_all([material, scanner]); db.flush()
                item = WarehouseItem(material_id=material.id, ordinal=1)
                db.add(item); db.commit()
                result = netum_scan('test', NetumScanRequest(msg=item.uuid), db)
                self.assertTrue(result['ok'])
                self.assertEqual(db.query(ScanEvento).count(), 0)
                request = db.query(WarehouseChangeRequest).one()
                self.assertEqual(request.status, WarehouseChangeRequestStatus.PENDING)
                self.assertEqual(request.action, 'inventory_presence')
                self.assertEqual(request.payload['uuid'], item.uuid)
                _apply_change_request_payload(db, request)
                db.commit()
                event = db.query(ScanEvento).one()
                self.assertEqual(event.item_uuid, item.uuid)
                self.assertEqual(event.tipo_evento, 'INVENTARIO')
                self.assertEqual(event.postazione, 'INV')
                self.assertEqual(item.status, 'AVAILABLE')
                self.assertIsNone(item.reserved_for_commessa)
                self.assertEqual(db.query(PieceWorkSession).count(), 0)
                self.assertEqual(db.query(WorkshopScanBlock).count(), 0)
                self.assertEqual(db.query(StockMovement).count(), 0)
                result = netum_scan('test', NetumScanRequest(msg='STQC:START:MAGAZZINO'), db)
                self.assertFalse(result['ok'])
                self.assertEqual(db.query(ScanEvento).count(), 1)
                self.assertEqual(db.query(WarehouseChangeRequest).count(), 1)
        finally:
            engine.dispose()
