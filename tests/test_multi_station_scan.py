import unittest
from unittest.mock import patch
from sqlalchemy import create_engine
from sqlalchemy.orm import Session
from fastapi import HTTPException
from backend.app.api.api_v1.endpoints.admin import create_scanner_device
from backend.app.api.api_v1.endpoints.commessa import get_monitoring
from backend.app.api.api_v1.endpoints.officina import scanners_for_phase
from backend.app.api.api_v1.endpoints.scanner import scanner_select_station, StationSelection
from backend.app.db.base import Base
from backend.app.models.commessa import Commessa, CommessaRevisione, Piece, Workstation, ScannerPhaseEvent
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
        select_station(self.db,self.scanner,self.a.id)
        self.assertTrue(process_multi_station_scan(self.db,self.scanner,'P1','1')['ok'])
        select_station(self.db,self.scanner,self.b.id)
        self.assertTrue(process_multi_station_scan(self.db,self.scanner,'P1','2')['ok'])
        self.assertEqual(self.db.query(ScannerPhaseEvent).count(),2)
        self.a.fase='officina';self.db.commit()
        result=get_monitoring(self.job.id,self.db)
        self.assertEqual(result['assemblaggi'][0]['postazione'],'CUSTOM_A')
        self.assertEqual(result['saldature'][0]['postazione'],'CUSTOM_B')
        self.assertEqual(len(scanners_for_phase('saldature',self.db)['items']),1)
        self.assertEqual(scanners_for_phase('assemblaggi',self.db)['items'],[])
    def test_individual_assembly_and_invalid_qr(self):
        self.revision.file_assemblaggi='test.xlsx';self.db.commit()
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
        select_station(self.db,self.scanner,self.a.id)
        self.assertTrue(process_multi_station_scan(self.db,self.scanner,'P1','NETUM_DEVICE')['ok'])
        self.piece.qr_payload='P2';self.db.commit()
        self.assertTrue(process_multi_station_scan(self.db,self.scanner,'P2','NETUM_DEVICE')['ok'])
        self.assertTrue(process_multi_station_scan(self.db,self.scanner,'P2','NETUM_DEVICE')['ok'])
        self.assertEqual(self.db.query(ScannerPhaseEvent).count(),3)
