import unittest
from datetime import datetime, timedelta
from sqlalchemy import create_engine
from sqlalchemy.orm import Session
from backend.app.db.base import Base
from backend.app.models.commessa import (Commessa, CommessaRevisione, Piece, ScannerDevice,
    WorkshopScanAttempt, ScannerPhaseEvent, AssemblyScanSession, AssemblyScanEvent,
    WeldingScanSession, WeldingScanEvent, SpedizioneAdHoc, SpedizioneAdHocItem)
from backend.app.models.warehouse import (Material, WarehouseItem, WarehouseChangeRequest,
    StockMovement, MovementType, ScanEvento)
from backend.app.services.preproduction_scan import process_preproduction_scan


class EventDetailsTests(unittest.TestCase):
    def setUp(self):
        self.engine = create_engine('sqlite://')
        Base.metadata.create_all(self.engine)
        self.db = Session(self.engine)
        self.job = Commessa(codice='TEST')
        self.material = Material(code='GREZZO', description='Barra', peso_1_pz=500)
        self.scanner = ScannerDevice(scanner_code='MAP', name='Mappa', device_token='secret', scan_mode='MAGAZZINO')
        self.db.add_all([self.job, self.material, self.scanner]); self.db.flush()
        self.rev = CommessaRevisione(commessa_id=self.job.id, codice='r1')
        self.raw = WarehouseItem(material_id=self.material.id, ordinal=1, colata='ORIGINALE', peso_1_pz=600)
        self.db.add_all([self.rev, self.raw]); self.db.flush()
        self.pieces = [Piece(commessa_id=self.job.id, revisione_id=self.rev.id, qr_code=f'P{i}',
            qr_payload=f'P{i}', marca_pos=f'P{i}', progressivo=1, qr_attivo=True, peso_kg=12) for i in range(3)]
        self.db.add_all(self.pieces); self.db.commit()

    def tearDown(self):
        self.db.close(); self.engine.dispose()

    def map_piece(self, piece):
        self.assertTrue(process_preproduction_scan(self.db, self.scanner, self.raw.uuid)['ok'])
        self.assertTrue(process_preproduction_scan(self.db, self.scanner, piece.qr_code)['ok'])

    def test_piece_and_raw_are_frozen_on_later_phase_and_rollback_is_atomic(self):
        self.map_piece(self.pieces[0])
        row = ScannerPhaseEvent(scanner_device_id=self.scanner.id, commessa_id=self.job.id,
            revisione_id=self.rev.id, workstation_code='TAGLIO', fase='officina',
            entity='pezzo', entity_code='P0', raw_payload='P0')
        self.db.add(row); self.db.commit()
        original = row.details_snapshot
        self.assertEqual(original['pezzi'][0]['pezzo']['peso_kg'], '12.0000')
        self.assertEqual(original['grezzi'][0]['grezzo']['colata'], 'ORIGINALE')
        self.assertEqual(original['grezzi'][0]['grezzo']['peso_1_pz'], '600.0000')
        self.assertNotIn('device_token', original['scanner'])
        self.pieces[0].peso_kg = 99; self.raw.colata = 'CAMBIATA'; self.db.commit()
        self.db.expire_all()
        self.assertEqual(row.details_snapshot, original)
        attempt = WorkshopScanAttempt(scanner_device_id=self.scanner.id, piece_id=self.pieces[0].id,
            raw_payload='P0', scan_kind='PIECE', outcome='OK', message='ok')
        self.db.add(attempt); self.db.flush(); aid = attempt.id
        self.assertTrue(attempt.details_snapshot['grezzi'])
        self.db.rollback()
        self.assertIsNone(self.db.get(WorkshopScanAttempt, aid))

    def test_raw_selection_survives_days_and_pending_mapping_until_next_raw(self):
        self.assertTrue(process_preproduction_scan(self.db, self.scanner, 'P0')['ok'])
        self.assertTrue(process_preproduction_scan(self.db, self.scanner, self.raw.uuid)['ok'])
        self.scanner.current_warehouse_item_set_at = datetime.utcnow() - timedelta(days=3)
        self.db.commit()
        self.assertTrue(process_preproduction_scan(self.db, self.scanner, 'P1')['ok'])
        self.assertEqual(self.pieces[1].materiale_origine_id, self.raw.id)
        other = WarehouseItem(material_id=self.material.id, ordinal=2)
        self.db.add(other); self.db.commit()
        self.assertTrue(process_preproduction_scan(self.db, self.scanner, other.uuid)['ok'])
        self.assertTrue(process_preproduction_scan(self.db, self.scanner, 'P2')['ok'])
        self.assertEqual(self.pieces[2].materiale_origine_id, other.id)

    def test_assembly_and_welding_include_actual_components_and_shared_raw_once(self):
        for piece in self.pieces[:2]:
            self.map_piece(piece)
        session = AssemblyScanSession(scanner_device_id=self.scanner.id, workstation_code='A1',
            commessa_id=self.job.id, revisione_id=self.rev.id, assembly_code='ASS', assembly_instance=1)
        self.db.add(session); self.db.flush()
        for piece in self.pieces[:2]:
            self.db.add(AssemblyScanEvent(session_id=session.id, event_type='CHILD',
                raw_payload=piece.qr_code, piece_id=piece.id, outcome='OK', message='ok'))
        self.db.commit()
        welding = WeldingScanSession(workstation_code='S1', scanner_device_id=self.scanner.id)
        self.db.add(welding); self.db.flush()
        row = WeldingScanEvent(session_id=welding.id, commessa_id=self.job.id, revisione_id=self.rev.id,
            assembly_code='ASS', assembly_instance=1, event_type='ASSEMBLY', outcome='OK', message='ok',
            raw_payload=f'STQC:ASM:{self.job.id}:ASS:1')
        self.db.add(row); self.db.commit()
        self.assertEqual(len(row.details_snapshot['pezzi']), 2)
        self.assertEqual(len(row.details_snapshot['grezzi']), 1)

    def test_notification_keeps_creation_and_decision_details_separate(self):
        request = WarehouseChangeRequest(action='inventory_presence', title='Inventario', payload={'uuid': self.raw.uuid})
        self.db.add(request); self.db.commit()
        creation = request.details_snapshot['creation']
        self.raw.colata = 'NUOVA'
        request.applied_at = datetime.utcnow(); request.result = {'operation': 'check'}
        self.db.commit()
        self.assertEqual(request.details_snapshot['creation'], creation)
        self.assertEqual(request.details_snapshot['decision']['grezzi'][0]['grezzo']['colata'], 'NUOVA')

    def test_shipping_row_snapshot_matches_transaction_not_equal_timestamps(self):
        shipping = SpedizioneAdHoc(commessa_id=self.job.id, revisione_id=self.rev.id, titolo='Spedizione')
        self.db.add(shipping); self.db.flush()
        row = SpedizioneAdHocItem(spedizione_id=shipping.id, commessa_id=self.job.id, revisione_id=self.rev.id,
            row_index=1, codice='X', scanner_device_id=self.scanner.id, raw_payload='X', trovato_at=datetime.utcnow())
        attempt = WorkshopScanAttempt(scanner_device_id=self.scanner.id, raw_payload='X',
            scan_kind='SHIPPING', outcome='OK', message='Trovato')
        self.db.add_all([row, attempt]); self.db.commit()
        self.assertEqual(attempt.details_snapshot['unita_spedizione'][0]['codice'], 'X')

    def test_movement_captures_items_linked_after_initial_flush(self):
        movement = StockMovement(material_id=self.material.id, quantity=1,
            movement_type=MovementType.INCOMING, reason='Ingresso')
        self.db.add(movement); self.db.flush()
        self.raw.source_movement_id = movement.id
        self.db.commit()
        self.assertEqual(movement.details_snapshot['grezzi'][0]['grezzo']['id'], self.raw.id)

    def test_inventory_presence_carries_raw_details(self):
        row = ScanEvento(item_uuid=self.raw.uuid, tipo_evento='INVENTARIO')
        self.db.add(row); self.db.commit()
        self.assertEqual(row.details_snapshot['grezzi'][0]['grezzo']['colata'], 'ORIGINALE')

    def test_selected_unavailable_raw_does_not_queue_piece_for_another_raw(self):
        process_preproduction_scan(self.db, self.scanner, self.raw.uuid)
        self.raw.status = 'OUT'; self.db.commit()
        result = process_preproduction_scan(self.db, self.scanner, 'P0')
        self.assertEqual(result['error_code'], 'WAREHOUSE_ITEM_NOT_AVAILABLE')
        self.assertNotEqual(self.pieces[0].materiale_origine_status, 'IN_ATTESA_GREZZO')
