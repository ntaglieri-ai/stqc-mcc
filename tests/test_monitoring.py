import unittest
from datetime import datetime

from fastapi import HTTPException
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from backend.app.api.api_v1.endpoints.commessa import get_dashboard_monitoring, get_monitoring
from backend.app.db.base import Base
from backend.app.models.commessa import (
    Commessa, CommessaRevisione, CommessaPostOfficinaItem, Piece, PieceScanEvent,
    ProgettazioneEvento, ScannerDevice, WorkshopScanAttempt, WorkshopScanBlock,
    ProgettazioneItem, Workstation,
)
from backend.app.models.warehouse import Material, MovementType, StockMovement, WarehouseItem


class MonitoringTests(unittest.TestCase):
    def test_inventory_scan_and_decision_are_distinct_readable_events(self):
        from backend.app.models.warehouse import WarehouseChangeRequest, WarehouseChangeRequestStatus
        scanner = ScannerDevice(scanner_code='INV', name='Scanner inventario', scan_mode='MAGAZZINO_INVENTARIO', active=True)
        material = Material(code='LAMIERA-ZINCATA', description='Lamiera', unit='PZ')
        self.db.add_all([scanner, material]); self.db.flush()
        item = WarehouseItem(material_id=material.id, ordinal=1)
        self.db.add(item); self.db.flush()
        scanned = datetime.utcnow().replace(hour=8, minute=0, second=0)
        decided = scanned.replace(hour=9)
        self.db.add(WorkshopScanAttempt(scanner_device_id=scanner.id, raw_payload=item.uuid,
            scan_kind='INVENTORY_PRESENCE', outcome='OK', message=f'Notifica inviata: {item.uuid}', created_at=scanned))
        self.db.add(WarehouseChangeRequest(action='inventory_presence', title='Inventario',
            status=WarehouseChangeRequestStatus.APPLIED, payload={'uuid':item.uuid},
            result={'operation':'uscita'}, created_at=scanned, applied_at=decided, applied_by_username='Mario'))
        self.db.commit()
        rows = get_dashboard_monitoring(self.db)['giornaliera']['timeline']
        scan = next(r for r in rows if r['origine'] == 'Scan inventario')
        decision = next(r for r in rows if r['origine'] == 'Esito notifica inventario')
        self.assertEqual(scan['data'], scanned)
        self.assertEqual(decision['data'], decided)
        self.assertIn('Uscita registrata', decision['esito'])
        self.assertIn('Mario', decision['esito'])
        for row in [scan, decision]:
            self.assertIn('LAMIERA-ZINCATA', row['dettaglio'])
            visible = {key: value for key, value in row.items() if key != 'details_snapshots'}
            self.assertNotIn(item.uuid, str(visible))
            self.assertNotIn('INVENTORY_PRESENCE', str(visible))
        from backend.app.api.api_v1.endpoints.commessa import cleanup_monitoring, MonitoringCleanupRequest
        day = scanned.date().isoformat()
        result = cleanup_monitoring(MonitoringCleanupRequest(day=day, event_keys=[scan['event_key']]), self.db)
        self.assertEqual(result['deleted'], 1)
        self.assertEqual(self.db.query(WorkshopScanAttempt).count(), 0)
        self.assertEqual(self.db.query(WarehouseChangeRequest).count(), 1)
        remaining = get_dashboard_monitoring(self.db, day)['giornaliera']['timeline']
        self.assertEqual([r['event_key'] for r in remaining], [decision['event_key']])
        self.assertTrue(remaining[0]['details_snapshots'])
        with self.assertRaises(HTTPException):
            cleanup_monitoring(MonitoringCleanupRequest(day=day, event_keys=[decision['event_key'], 'stale']), self.db)
        self.assertEqual(self.db.query(WarehouseChangeRequest).count(), 1)
        cleanup_monitoring(MonitoringCleanupRequest(day=day, event_keys=[decision['event_key']]), self.db)
        self.assertEqual(self.db.query(WarehouseChangeRequest).count(), 0)
        self.assertEqual(get_dashboard_monitoring(self.db, day)['giornaliera']['timeline'], [])
        self.assertEqual(item.status, 'AVAILABLE')
        self.assertIsNotNone(self.db.get(WarehouseItem, item.id))

    def test_delete_identical_looking_events_uses_distinct_sources(self):
        from backend.app.api.api_v1.endpoints.commessa import cleanup_monitoring, MonitoringCleanupRequest
        moment = datetime.utcnow()
        self.db.add_all([ProgettazioneEvento(commessa_id=self.commessa.id,
            voce='disegni', tipo_evento='INIZIO', timestamp=moment) for _ in range(2)])
        self.db.commit()
        day = moment.date().isoformat()
        rows = get_dashboard_monitoring(self.db, day)['giornaliera']['timeline']
        self.assertEqual(len({r['event_key'] for r in rows}), 2)
        cleanup_monitoring(MonitoringCleanupRequest(day=day, event_keys=[rows[0]['event_key']]), self.db)
        self.assertEqual(self.db.query(ProgettazioneEvento).count(), 1)
        self.assertTrue(self.db.query(ProgettazioneEvento).one().details_snapshot)
        self.assertEqual(len(get_dashboard_monitoring(self.db, day)['giornaliera']['timeline']), 1)

    def test_deletion_failure_rolls_back_events_and_snapshots(self):
        from unittest.mock import patch
        from backend.app.api.api_v1.endpoints.commessa import cleanup_monitoring, MonitoringCleanupRequest
        from backend.app.services.monitoring_delete import delete_event
        moment = datetime.utcnow()
        self.db.add_all([ProgettazioneEvento(commessa_id=self.commessa.id,
            voce='disegni', tipo_evento='INIZIO', timestamp=moment) for _ in range(2)])
        self.db.commit()
        rows = get_dashboard_monitoring(self.db)['giornaliera']['timeline']
        calls = []
        def fail_second(db, source):
            calls.append(source)
            if len(calls) == 2:
                raise RuntimeError('simulated failure')
            delete_event(db, source)
        with patch('backend.app.services.monitoring_delete.delete_event', side_effect=fail_second):
            with self.assertRaises(RuntimeError):
                cleanup_monitoring(MonitoringCleanupRequest(day=moment.date().isoformat(),
                    event_keys=[r['event_key'] for r in rows]), self.db)
        self.assertEqual(self.db.query(ProgettazioneEvento).count(), 2)
        self.assertTrue(all(e.details_snapshot for e in self.db.query(ProgettazioneEvento)))

    def test_delete_movement_removes_snapshot_without_deleting_material(self):
        from backend.app.api.api_v1.endpoints.commessa import cleanup_monitoring, MonitoringCleanupRequest
        material = Material(code='DELETE-MOVE', description='Materiale', unit='PZ')
        self.db.add(material); self.db.flush()
        movement = StockMovement(material_id=material.id, quantity=1,
            movement_type=MovementType.INCOMING, reason='Test', occurred_at=datetime.utcnow())
        self.db.add(movement); self.db.flush()
        item = WarehouseItem(material_id=material.id, ordinal=1, source_movement_id=movement.id)
        self.db.add(item); self.db.commit()
        row = next(r for r in get_dashboard_monitoring(self.db)['giornaliera']['timeline']
                   if r['origine'] == 'Ingresso magazzino')
        self.assertTrue(row['details_snapshots'])
        cleanup_monitoring(MonitoringCleanupRequest(day=movement.occurred_at.date().isoformat(),
            event_keys=[row['event_key']]), self.db)
        self.assertEqual(self.db.query(StockMovement).count(), 0)
        self.db.refresh(item)
        self.assertIsNone(item.source_movement_id)
        self.assertIsNotNone(self.db.get(Material, material.id))
        self.assertIsNotNone(self.db.get(WarehouseItem, item.id))

    def setUp(self):
        self.engine = create_engine('sqlite://')
        Base.metadata.create_all(self.engine)
        self.db = Session(self.engine)
        self.commessa = Commessa(codice='MONITOR')
        self.db.add(self.commessa)
        self.db.flush()

    def tearDown(self):
        self.db.close()
        self.engine.dispose()

    def test_empty_and_missing_commessa(self):
        result = get_monitoring(self.commessa.id, self.db)
        self.assertIsNone(result['spedizione']['previsti'])
        self.assertEqual(result['officina'], [])
        self.assertNotIn('analisi_distinta', result)
        self.assertEqual(result['progettazione_tempi'], {'inizio_generale': None, 'fine_generale': None})
        self.assertTrue(all(r['stato'] == 'NON_INIZIATA' for r in result['progettazione']))
        with self.assertRaises(HTTPException) as error:
            get_monitoring(999, self.db)
        self.assertEqual(error.exception.status_code, 404)

    def test_design_phase_times_are_per_commessa_with_open_tasks(self):
        other = Commessa(codice='OTHER')
        self.db.add(other)
        self.db.flush()
        self.db.add_all([
            ProgettazioneItem(commessa_id=self.commessa.id, voce='modello_ifc', inizio=True, fine=True,
                              iniziata_at=datetime(2026, 1, 3), completata_at=datetime(2026, 1, 5)),
            ProgettazioneItem(commessa_id=self.commessa.id, voce='distinte', inizio=True, fine=True,
                              iniziata_at=datetime(2026, 1, 2), completata_at=datetime(2026, 1, 7)),
            ProgettazioneItem(commessa_id=self.commessa.id, voce='etichette', inizio=True, fine=False,
                              iniziata_at=datetime(2026, 1, 8)),
            ProgettazioneItem(commessa_id=other.id, voce='modello_ifc', inizio=True, fine=True,
                              iniziata_at=datetime(2025, 1, 1), completata_at=datetime(2027, 1, 1)),
        ])
        self.db.commit()
        result = get_monitoring(self.commessa.id, self.db)
        self.assertEqual(result['progettazione_tempi'], {
            'inizio_generale': datetime(2026, 1, 2), 'fine_generale': datetime(2026, 1, 7),
        })
        self.assertFalse(self.db.dirty)

    def test_analysis_data_is_not_exposed_in_monitoring(self):
        old = CommessaRevisione(commessa_id=self.commessa.id, codice='r01', corrente=False,
                               report_analisi={'assemblies': 999})
        current = CommessaRevisione(commessa_id=self.commessa.id, codice='r02', corrente=True,
                                   file_lavorazioni='lista.xls', file_assemblaggi='assemblaggi.xls',
                                   report_analisi={'assemblaggi': {'assemblati': 12, 'righe': 25},
                                                   'spedizione': {'righe': 8, 'quantita': 30},
                                                   'bulloneria': {'righe': 4, 'quantita_totale': 120}})
        self.db.add_all([old, current])
        self.db.flush()
        self.db.add(Piece(commessa_id=self.commessa.id, revisione_id=old.id,
                          qr_code='OLD', qr_payload='OLD', marca_pos='OLD', progressivo=1))
        self.db.add(Piece(commessa_id=self.commessa.id, revisione_id=current.id,
                          qr_code='NEW', qr_payload='NEW', marca_pos='NEW', progressivo=1))
        self.db.commit()
        result = get_monitoring(self.commessa.id, self.db)
        self.assertNotIn('analisi_distinta', result)
        self.assertFalse(self.db.new)
        self.assertFalse(self.db.dirty)

    def test_current_revision_quantities_and_scan_separation(self):
        old = CommessaRevisione(commessa_id=self.commessa.id, codice='r01', corrente=False)
        current = CommessaRevisione(commessa_id=self.commessa.id, codice='r02', corrente=True)
        self.db.add_all([old, current])
        self.db.flush()
        for revision, qty, state in [(old, 100, 'SPEDITO'), (current, 3, 'SPEDITO'), (current, 7, 'TROVATO')]:
            self.db.add(CommessaPostOfficinaItem(commessa_id=self.commessa.id, revisione_id=revision.id, row_index=qty, codice=str(qty), quantita=qty, cantiere_status=state))
        piece = Piece(commessa_id=self.commessa.id, revisione_id=current.id, qr_code='P1', qr_payload='P1', marca_pos='M1', progressivo=1)
        self.db.add(piece)
        self.db.flush()
        for station in ['TAGLIO', 'ASSEMBLAGGIO_A1']:
            self.db.add(PieceScanEvent(piece_id=piece.id, commessa_id=self.commessa.id, revisione_id=current.id, qr_code='P1', postazione_code=station, event_type='PIECE_READ', timestamp=datetime(2026, 1, 1)))
        self.db.commit()
        for outcome in ['OK', 'WARNING']:
            self.db.add(WorkshopScanAttempt(piece_id=piece.id, raw_payload='P1', scan_kind='PIECE', outcome=outcome, message='Test'))
        self.db.commit()
        result = get_monitoring(self.commessa.id, self.db)
        self.assertEqual(len(result['officina_letture']), 2)
        self.assertEqual(result['officina_letture'][0]['piece_id'], piece.id)
        self.assertNotEqual(result['officina_letture'][0]['scan_id'], result['officina_letture'][1]['scan_id'])
        self.assertEqual(result['spedizione']['previsti'], 10)
        self.assertEqual(result['spedizione']['spediti'], 3)
        self.assertEqual(len(result['officina']), 0)
        self.assertEqual(len(result['assemblaggi']), 1)
        self.assertFalse(self.db.new)
        self.assertFalse(self.db.dirty)

    def test_monitoring_exposes_collection_views(self):
        revision = CommessaRevisione(commessa_id=self.commessa.id, codice='r01', corrente=True)
        material = Material(code='HEA100', description='Profilo HEA', unit='PZ')
        self.db.add_all([revision, material])
        self.db.flush()
        item = WarehouseItem(material_id=material.id, ordinal=1, reserved_for_commessa='MONITOR')
        self.db.add(item)
        self.db.flush()
        piece = Piece(commessa_id=self.commessa.id, revisione_id=revision.id, qr_code='P1',
                      qr_payload='P1', marca_pos='M1', progressivo=1, materiale_origine_id=item.id,
                      qr_attivo=True)
        self.db.add(piece)
        self.db.flush()
        self.db.add_all([
            PieceScanEvent(piece_id=piece.id, commessa_id=self.commessa.id, revisione_id=revision.id,
                           qr_code='P1', postazione_code='TAGLIO', event_type='PIECE_READ',
                           timestamp=datetime.now()),
            StockMovement(material_id=material.id, quantity=1, movement_type=MovementType.OUTGOING,
                          reason='Prelievo commessa', destination_commessa='MONITOR',
                          commessa_id=self.commessa.id, occurred_at=datetime.now()),
        ])
        self.db.commit()
        result = get_monitoring(self.commessa.id, self.db)['raccolta_dati']
        self.assertEqual(result['commessa']['pezzi_correnti'], 1)
        self.assertEqual(result['commessa']['scan_operativi'], 1)
        self.assertEqual(result['magazzino']['grezzi_collegati'], 1)
        self.assertEqual(result['magazzino']['grezzi_prenotati'], 1)
        self.assertEqual(result['magazzino']['movimenti'], 1)
        self.assertGreaterEqual(result['giornaliera']['totale'], 2)
        self.assertFalse(self.db.new)
        self.assertFalse(self.db.dirty)

    def test_dashboard_monitoring_has_warehouse_and_daily_views(self):
        material = Material(code='IPE200', description='Profilo IPE', unit='PZ')
        self.db.add(material)
        self.db.flush()
        self.db.add_all([
            WarehouseItem(material_id=material.id, ordinal=1),
            WarehouseItem(material_id=material.id, ordinal=2, reserved_for_commessa='MONITOR',
                          reserved_at=datetime.now()),
            StockMovement(material_id=material.id, quantity=2, movement_type=MovementType.INCOMING,
                          reason='Carico test', occurred_at=datetime.now()),
        ])
        scanner = ScannerDevice(scanner_code='MAP-01', name='Mapping', device_token='map-01', scan_mode='MAGAZZINO')
        self.db.add(scanner)
        self.db.flush()
        self.db.add(WorkshopScanAttempt(
            scanner_device_id=scanner.id,
            raw_payload='RAW-QR',
            scan_kind='PREPROD_WAREHOUSE_ITEM',
            outcome='OK',
            message='Grezzo acquisito',
            created_at=datetime.now(),
        ))
        self.db.add(ProgettazioneEvento(
            commessa_id=self.commessa.id,
            voce='distinte',
            tipo_evento='INIZIO',
            timestamp=datetime.now(),
        ))
        self.db.commit()
        result = get_dashboard_monitoring(self.db)
        self.assertEqual(result['summary']['commesse_total'], 1)
        self.assertEqual(result['summary']['pezzi_magazzino'], 2)
        self.assertEqual(result['summary']['pezzi_prenotati'], 1)
        self.assertEqual(result['magazzino']['movimenti_oggi'], 1)
        self.assertEqual(result['magazzino']['prenotazioni'][0]['commessa'], 'MONITOR')
        self.assertEqual(result['giornaliera']['movimenti_magazzino'], 1)
        self.assertEqual(result['giornaliera']['scan_magazzino'], 1)
        self.assertEqual(result['giornaliera']['eventi_progettazione'], 1)
        warehouse_events = [row for row in result['giornaliera']['timeline'] if row['vista'] == 'magazzino']
        self.assertTrue(any(row['origine'] == 'Scan mappatura' for row in warehouse_events))
        self.assertTrue(any(row['origine'] == 'Inizio progettazione' for row in result['giornaliera']['timeline']))

    def test_workshop_events_have_separate_rows(self):
        revision = CommessaRevisione(commessa_id=self.commessa.id, codice='r01', corrente=True)
        station = Workstation(
            code='TAGLIO', name='Taglio', fase='officina',
            start_qr_code='WS:TAGLIO:START', end_qr_code='WS:TAGLIO:END',
        )
        scanner = ScannerDevice(scanner_code='OFF-01', name='Officina', device_token='off-01')
        self.db.add_all([revision, station, scanner])
        self.db.flush()
        piece = Piece(
            commessa_id=self.commessa.id, revisione_id=revision.id,
            qr_code='P1', qr_payload='P1', marca_pos='M1', progressivo=1,
        )
        self.db.add(piece)
        self.db.flush()
        moment = datetime.now().replace(hour=10, minute=30, second=0, microsecond=0)
        block = WorkshopScanBlock(
            scanner_device_id=scanner.id, workstation_id=station.id, workstation_code=station.code,
            status='CLOSED', started_at=moment, closed_at=moment.replace(hour=12),
            start_payload='WS:TAGLIO:START', end_payload='WS:TAGLIO:END', piece_count=1,
        )
        self.db.add(block)
        self.db.flush()
        self.db.add_all([
            WorkshopScanAttempt(scanner_device_id=scanner.id, workstation_id=station.id,
                scan_block_id=block.id, raw_payload='WS:TAGLIO:START', scan_kind='WORKSTATION_START',
                outcome='OK', message='INIZIO registrato', created_at=moment),
            WorkshopScanAttempt(scanner_device_id=scanner.id, workstation_id=station.id,
                scan_block_id=block.id, raw_payload='WS:TAGLIO:END', scan_kind='WORKSTATION_END',
                outcome='OK', message='FINE registrata', created_at=moment.replace(hour=12)),
            WorkshopScanAttempt(
                scanner_device_id=scanner.id, workstation_id=station.id, scan_block_id=block.id,
                piece_id=piece.id, raw_payload='P1', scan_kind='PIECE', outcome='OK',
                message='Pezzo acquisito', created_at=moment.replace(hour=11),
            ),
            PieceScanEvent(
                piece_id=piece.id, commessa_id=self.commessa.id, revisione_id=revision.id,
                qr_code='P1', postazione_id=station.id, postazione_code=station.code,
                event_type='PHASE_START', timestamp=moment.replace(hour=11), scan_block_id=block.id,
            ),
            PieceScanEvent(
                piece_id=piece.id, commessa_id=self.commessa.id, revisione_id=revision.id,
                qr_code='P1', postazione_id=station.id, postazione_code=station.code,
                event_type='PHASE_END', timestamp=moment.replace(hour=12), scan_block_id=block.id,
            ),
        ])
        self.db.commit()

        result = get_dashboard_monitoring(self.db)
        rows = [row for row in result['giornaliera']['timeline'] if row['commessa'] == 'MONITOR']
        self.assertEqual(len(rows), 3)
        self.assertEqual([row['origine'] for row in rows],
                         ['Fine lavorazione', 'Scansione pezzo', 'Inizio lavorazione'])
        self.assertEqual([row['data'] for row in rows],
                         [moment.replace(hour=12), moment.replace(hour=11), moment])
        self.assertIn('M1 · pezzo 1', rows[1]['dettaglio'])
        self.assertEqual(result['giornaliera']['scan_pezzi'], 1)

        commessa_result = get_monitoring(self.commessa.id, self.db)
        self.assertEqual(commessa_result['officina'], [{
            'blocco_id': block.id,
            'postazione': 'TAGLIO',
            'inizio': moment,
            'fine': moment.replace(hour=12),
            'stato': 'CLOSED',
            'numero_scan': 1,
        }])

        from backend.app.api.api_v1.endpoints.commessa import cleanup_monitoring, MonitoringCleanupRequest
        day = moment.date().isoformat()
        # Delete only the middle scan, including its secondary piece log and snapshot.
        cleanup_monitoring(MonitoringCleanupRequest(day=day, event_keys=[rows[1]['event_key']]), self.db)
        self.assertEqual(self.db.query(WorkshopScanAttempt).filter_by(scan_kind='PIECE').count(), 0)
        self.assertEqual(self.db.query(PieceScanEvent).filter_by(event_type='PHASE_START').count(), 0)
        self.assertEqual(self.db.query(PieceScanEvent).filter_by(event_type='PHASE_END').count(), 1)
        remaining = get_dashboard_monitoring(self.db, day)['giornaliera']['timeline']
        self.assertEqual(len(remaining), 2)
        # Stable source identifiers survive changed job labels and details.
        self.assertEqual({r['event_key'] for r in remaining}, {rows[0]['event_key'], rows[2]['event_key']})
        cleanup_monitoring(MonitoringCleanupRequest(day=day, event_keys=[r['event_key'] for r in remaining]), self.db)
        self.assertEqual(self.db.query(WorkshopScanAttempt).count(), 0)
        self.assertEqual(self.db.query(PieceScanEvent).count(), 0)
        self.assertEqual(get_dashboard_monitoring(self.db, day)['giornaliera']['timeline'], [])
        self.assertIsNotNone(self.db.get(Piece, piece.id))
        self.assertIsNotNone(self.db.get(Commessa, self.commessa.id))


if __name__ == '__main__':
    unittest.main()
