import unittest
from types import SimpleNamespace
from fastapi import HTTPException
from backend.app.api.api_v1.endpoints.warehouse import decide_inventory_scan
from backend.app.schemas.warehouse import InventoryScanDecision

from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from backend.app.api.api_v1.endpoints.scanner import NetumScanRequest, netum_scan
from backend.app.db.base import Base
from backend.app.models.commessa import ScannerDevice, PieceWorkSession, WorkshopScanBlock
from backend.app.models.warehouse import Material, WarehouseItem, ScanEvento, StockMovement, WarehouseChangeRequest, WarehouseChangeRequestStatus
from backend.app.api.api_v1.endpoints.warehouse import _apply_change_request_payload
from backend.app.api.api_v1.endpoints.warehouse import _apply_stock_movement_payload


class InventoryScanTests(unittest.TestCase):
    def test_scan_choices_movements_check_edit_and_repeat_protection(self):
        engine = create_engine('sqlite://')
        Base.metadata.create_all(engine)
        try:
            with Session(engine) as db:
                material = Material(code='CHOICES', description='Test', unit='PZ')
                scanner = ScannerDevice(scanner_code='INV', name='Inventario', device_token='choices',
                                        scan_mode='MAGAZZINO_INVENTARIO', active=True)
                db.add_all([material, scanner]); db.flush()
                item = WarehouseItem(material_id=material.id, ordinal=1)
                db.add(item); db.commit()
                user = SimpleNamespace(id=None, username='test')
                def scan():
                    netum_scan('choices', NetumScanRequest(msg=item.uuid), db)
                    return db.query(WarehouseChangeRequest).order_by(WarehouseChangeRequest.id.desc()).first()
                request = scan()
                with self.assertRaises(HTTPException):
                    decide_inventory_scan(request.id, InventoryScanDecision(operation='ingresso'), db, user)
                self.assertEqual(db.get(WarehouseChangeRequest, request.id).status, WarehouseChangeRequestStatus.PENDING)
                decide_inventory_scan(request.id, InventoryScanDecision(operation='uscita'), db, user)
                self.assertEqual(item.status, 'OUT')
                with self.assertRaises(HTTPException):
                    decide_inventory_scan(request.id, InventoryScanDecision(operation='uscita'), db, user)
                self.assertEqual(db.query(StockMovement).count(), 1)
                request = scan()
                decide_inventory_scan(request.id, InventoryScanDecision(operation='ingresso'), db, user)
                self.assertEqual(item.status, 'AVAILABLE')
                self.assertIsNone(item.exit_movement_id)
                self.assertEqual(db.query(WarehouseItem).count(), 1)
                self.assertEqual(db.query(StockMovement).count(), 2)
                request = scan()
                decide_inventory_scan(request.id, InventoryScanDecision(operation='check'), db, user)
                self.assertEqual(db.query(ScanEvento).count(), 1)
                self.assertEqual(db.query(StockMovement).count(), 2)
                request = scan()
                decide_inventory_scan(request.id, InventoryScanDecision(operation='modifica', changes={'notes':'Verificato'}), db, user)
                self.assertEqual(item.notes, 'Verificato')
                self.assertEqual(db.query(StockMovement).count(), 2)
        finally:
            engine.dispose()

    def test_manual_incoming_can_reserve_created_items_for_commessa(self):
        engine = create_engine('sqlite://')
        Base.metadata.create_all(engine)
        try:
            with Session(engine) as db:
                material = Material(code='RESERVED', description='Prenotato', unit='PZ')
                db.add(material)
                db.flush()
                movement = _apply_stock_movement_payload(db, {
                    'material_id': material.id,
                    'quantity': 2,
                    'movement_type': 'INCOMING',
                    'reason': 'Ingresso manuale',
                    'reserved_for_commessa': 'C-100',
                })
                db.commit()
                items = db.query(WarehouseItem).order_by(WarehouseItem.ordinal).all()
                self.assertEqual(len(items), 2)
                self.assertTrue(all(item.status == 'RESERVED' for item in items))
                self.assertTrue(all(item.reserved_for_commessa == 'C-100' for item in items))
                self.assertEqual(movement.destination_commessa, 'C-100')
        finally:
            engine.dispose()

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
                self.assertEqual(result['scan_kind'], 'INVENTORY_CHECK')
                self.assertNotIn(item.uuid, result['msg'])
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
