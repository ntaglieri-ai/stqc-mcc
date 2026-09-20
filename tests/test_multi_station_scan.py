import unittest
from unittest.mock import patch
from sqlalchemy import create_engine
from sqlalchemy.orm import Session
from fastapi import HTTPException
from backend.app.api.api_v1.endpoints.admin import create_scanner_device
from backend.app.api.api_v1.endpoints.commessa import get_dashboard_monitoring, get_monitoring
from backend.app.api.api_v1.endpoints.officina import scanners_for_phase
from backend.app.api.api_v1.endpoints.scanner import scanner_select_station, StationSelection
from backend.app.db.base import Base
from backend.app.models.commessa import (AssemblyScanEvent, AssemblyScanSession, Commessa,
    CommessaRevisione, Piece, Workstation, ScannerPhaseEvent, WeldingScanEvent,
    WeldingScanSession)
from backend.app.schemas.admin import ScannerDeviceCreate
from backend.app.services.multi_station_scan import select_station, process_multi_station_scan

class MultiStationTests(unittest.TestCase):
    def setUp(self):
        self.engine=create_engine('sqlite://')
        Base.metadata.create_all(self.engine)
        self.db=Session(self.engine)
        self.job=Commessa(codice='MULTI')
        self.db.add(self.job);self.db.flush()
        self.revision=CommessaRevisione(commessa_id=self.job.id,codice='r01',corrente=True)
        self.db.add(self.revision);self.db.flush()
        self.piece=Piece(commessa_id=self.job.id,revisione_id=self.revision.id,qr_code='P1',qr_payload='P1',marca_pos='P1',progressivo=1,qr_attivo=True)
        self.a=Workstation(code='CUSTOM_A',name='A',fase='assemblaggi',start_qr_code='A_START',end_qr_code='A_END')
        self.b=Workstation(code='CUSTOM_B',name='B',fase='saldature',start_qr_code='B_START',end_qr_code='B_END')
        self.db.add_all([self.piece,self.a,self.b]);self.db.commit()
        self.scanner=create_scanner_device(ScannerDeviceCreate(scanner_code='MULTI',name='Multi',scan_mode='MULTI_POSTAZIONE'),self.db)
    def tearDown(self):
        self.db.close();self.engine.dispose()
    def test_selection_routes_scans_and_preserves_history(self):
        self.assertFalse(process_multi_station_scan(self.db,self.scanner,'P1')['ok'])
        self.a.fase='lavorazioni';self.db.commit()
        select_station(self.db,self.scanner,self.a.id)
        self.assertTrue(process_multi_station_scan(self.db,self.scanner,'P1','1')['ok'])
        self.b.fase='in-cantiere';self.db.commit()
        select_station(self.db,self.scanner,self.b.id)
        self.assertTrue(process_multi_station_scan(self.db,self.scanner,'P1','2')['ok'])
        self.assertEqual(self.db.query(ScannerPhaseEvent).count(),2)
        self.a.fase='officina';self.db.commit()
        result=get_monitoring(self.job.id,self.db)
        self.assertEqual(result['lavorazioni'][0]['postazione'],'CUSTOM_A')
        self.assertEqual(result['in-cantiere'][0]['postazione'],'CUSTOM_B')
        self.assertEqual(len(scanners_for_phase('in-cantiere',self.db)['items']),1)
        self.assertEqual(scanners_for_phase('assemblaggi',self.db)['items'],[])
    def test_individual_assembly_and_invalid_qr(self):
        self.revision.file_assemblaggi='test.xlsx';self.db.commit()
        self.b.fase='lavorazioni';self.db.commit()
        select_station(self.db,self.scanner,self.b.id)
        with patch('backend.app.services.multi_station_scan.parse_assembly_parents',return_value=[{'codice':'A1','quantita':2}]):
            self.assertTrue(process_multi_station_scan(self.db,self.scanner,f'STQC:ASM:{self.job.id}:A1:2')['ok'])
            self.assertFalse(process_multi_station_scan(self.db,self.scanner,f'STQC:ASM:{self.job.id}:A1:3')['ok'])
        self.assertEqual(self.db.query(ScannerPhaseEvent).one().entity_code,'A1 / 2')
    def test_inactive_station_and_invalid_token(self):
        self.b.active=False;self.db.commit()
        with self.assertRaises(HTTPException):select_station(self.db,self.scanner,self.b.id)
        with self.assertRaises(HTTPException):scanner_select_station('invalid',StationSelection(postazione_id=self.a.id),self.db)

    def test_device_id_can_repeat_across_different_scans(self):
        self.b.fase='lavorazioni';self.db.commit()
        select_station(self.db,self.scanner,self.b.id)
        self.assertTrue(process_multi_station_scan(self.db,self.scanner,'P1','NETUM_DEVICE')['ok'])
        self.piece.qr_payload='P2';self.db.commit()
        self.assertTrue(process_multi_station_scan(self.db,self.scanner,'P2','NETUM_DEVICE')['ok'])
        self.assertTrue(process_multi_station_scan(self.db,self.scanner,'P2','NETUM_DEVICE')['ok'])
        self.assertEqual(self.db.query(ScannerPhaseEvent).count(),3)

    def test_assembly_hierarchy_records_wrong_child_as_error(self):
        wrong = Piece(commessa_id=self.job.id, revisione_id=self.revision.id, qr_code='X1',
                      qr_payload='X1', marca_pos='X1', progressivo=1, qr_attivo=True)
        self.revision.file_assemblaggi = 'test.xlsx'
        self.db.add(wrong)
        self.db.commit()
        select_station(self.db, self.scanner, self.a.id)
        hierarchy = [{
            'codice': 'A1', 'quantita': 1,
            'children': [{'codice': 'P1', 'quantita': 1}],
        }]
        with patch('backend.app.services.multi_station_scan.parse_assembly_records', return_value=hierarchy):
            self.assertTrue(process_multi_station_scan(self.db, self.scanner, 'A_START')['ok'])
            self.assertTrue(process_multi_station_scan(
                self.db, self.scanner, f'STQC:ASM:{self.job.id}:A1:1')['ok'])
            wrong_result = process_multi_station_scan(self.db, self.scanner, 'X1')
            self.assertFalse(wrong_result['ok'])
            self.assertEqual(wrong_result['error_code'], 'ASSEMBLY_CHILD_NOT_EXPECTED')
            self.assertTrue(process_multi_station_scan(self.db, self.scanner, 'P1')['ok'])
            self.assertTrue(process_multi_station_scan(self.db, self.scanner, 'A_END')['ok'])

        session = self.db.query(AssemblyScanSession).one()
        self.assertEqual(session.status, 'CLOSED')
        self.assertEqual(session.assembly_code, 'A1')
        self.assertEqual(self.db.query(AssemblyScanEvent).count(), 5)
        error = self.db.query(AssemblyScanEvent).filter_by(outcome='ERROR').one()
        self.assertEqual(error.piece_id, wrong.id)

        detail = get_monitoring(self.job.id, self.db)
        self.assertEqual(detail['errori_assemblaggio'], 1)
        child_rows = [row for row in detail['assemblaggi'] if row['evento'] == 'CHILD']
        self.assertEqual(len(child_rows), 2)
        self.assertTrue(all(row['assemblato'] == 'A1' for row in child_rows))
        self.assertTrue(any(row['errore'] for row in child_rows))

        daily = get_dashboard_monitoring(self.db)
        self.assertEqual(daily['giornaliera']['errori_assemblaggio'], 1)
        error_rows = [row for row in daily['giornaliera']['timeline'] if row.get('errore')]
        self.assertEqual(len(error_rows), 1)
        self.assertIn('X1 → A1', error_rows[0]['dettaglio'])

    def test_assembly_end_only_closes_and_records_time(self):
        self.revision.file_assemblaggi = 'test.xlsx'
        self.db.commit()
        select_station(self.db, self.scanner, self.a.id)
        hierarchy = [{
            'codice': 'A1', 'quantita': 1,
            'children': [{'codice': 'P1', 'quantita': 10}],
        }]
        with patch('backend.app.services.multi_station_scan.parse_assembly_records', return_value=hierarchy):
            self.assertTrue(process_multi_station_scan(self.db, self.scanner, 'A_START')['ok'])
            self.assertTrue(process_multi_station_scan(
                self.db, self.scanner, f'STQC:ASM:{self.job.id}:A1:1')['ok'])
            self.assertTrue(process_multi_station_scan(self.db, self.scanner, 'A_END')['ok'])
            self.assertTrue(process_multi_station_scan(self.db, self.scanner, 'A_START')['ok'])
            self.assertTrue(process_multi_station_scan(
                self.db, self.scanner, f'STQC:ASM:{self.job.id}:A1:1')['ok'])
            self.assertTrue(process_multi_station_scan(self.db, self.scanner, 'A_END')['ok'])
        sessions = self.db.query(AssemblyScanSession).all()
        self.assertEqual(len(sessions), 2)
        self.assertTrue(all(session.status == 'CLOSED' for session in sessions))
        self.assertTrue(all(session.closed_at is not None for session in sessions))
        self.assertEqual(self.db.query(AssemblyScanEvent).filter_by(outcome='ERROR').count(), 0)
        progress = get_monitoring(self.job.id, self.db)['assemblaggi_progress']
        self.assertEqual(len(progress), 1)
        self.assertEqual(progress[0]['assemblato'], 'A1')
        self.assertEqual(progress[0]['progressivo'], 1)
        self.assertEqual(progress[0]['sessioni'], 2)

    def test_welding_session_accepts_many_assembly_parents(self):
        self.revision.file_assemblaggi = 'test.xlsx'
        self.db.commit()
        select_station(self.db, self.scanner, self.b.id)
        parents = [{'codice': 'A1', 'quantita': 2}]
        with patch('backend.app.services.multi_station_scan.parse_assembly_parents', return_value=parents):
            self.assertTrue(process_multi_station_scan(self.db, self.scanner, 'B_START')['ok'])
            self.assertTrue(process_multi_station_scan(
                self.db, self.scanner, f'STQC:ASM:{self.job.id}:A1:1')['ok'])
            self.assertTrue(process_multi_station_scan(
                self.db, self.scanner, f'STQC:ASM:{self.job.id}:A1:2')['ok'])
            self.assertTrue(process_multi_station_scan(self.db, self.scanner, 'B_END')['ok'])

        session = self.db.query(WeldingScanSession).one()
        self.assertEqual(session.status, 'CLOSED')
        self.assertIsNotNone(session.closed_at)
        self.assertEqual(self.db.query(WeldingScanEvent).count(), 4)
        self.assertEqual(self.db.query(WeldingScanEvent).filter_by(event_type='ASSEMBLY').count(), 2)

        detail = get_monitoring(self.job.id, self.db)
        self.assertEqual(len(detail['saldature']), 2)
        self.assertEqual(detail['saldature_sessioni'][0]['assemblati_scansionati'], 2)
        daily = get_dashboard_monitoring(self.db)
        self.assertEqual(daily['giornaliera']['scan_saldature'], 2)
