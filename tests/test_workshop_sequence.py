import unittest
from datetime import datetime
from sqlalchemy import create_engine
from sqlalchemy.orm import Session
from backend.app.db.base import Base
from backend.app.models.commessa import (Commessa, CommessaRevisione, Piece, Workstation,
    ScannerDevice, PieceScanEvent, WorkshopScanAttempt, WorkshopScanBlock, PieceWorkSession)
from backend.app.services.workshop_scan import process_workshop_scan
from backend.app.api.api_v1.endpoints.commessa import get_dashboard_monitoring


class WorkshopSequenceTests(unittest.TestCase):
    def setUp(self):
        self.engine = create_engine('sqlite://')
        Base.metadata.create_all(self.engine)
        self.db = Session(self.engine)
        self.job = Commessa(codice='TEST')
        self.station = Workstation(code='TAGLIO',name='Taglio-Foratura',fase='officina',start_qr_code='START',end_qr_code='END')
        self.db.add_all([self.job,self.station]); self.db.flush()
        self.rev = CommessaRevisione(commessa_id=self.job.id,codice='r1')
        self.scanner = ScannerDevice(scanner_code='SCAN',name='Scanner',postazione_id=self.station.id,scan_mode='OFFICINA')
        self.db.add_all([self.rev,self.scanner]); self.db.flush()
        self.piece = Piece(commessa_id=self.job.id,revisione_id=self.rev.id,qr_code='P1',qr_payload='P1',marca_pos='P1',progressivo=1,qr_attivo=True)
        self.db.add(self.piece); self.db.commit()
    def tearDown(self):
        self.db.close(); self.engine.dispose()
    def scan(self,value):
        return process_workshop_scan(self.db,self.scanner,value)
    def test_missing_start_is_rejected_without_changing_piece(self):
        result=self.scan('P1')
        self.assertFalse(result['ok']); self.assertEqual(result['error_code'],'NO_OPEN_BLOCK')
        self.assertEqual(self.db.query(PieceWorkSession).count(),0)
        self.assertEqual(self.db.query(PieceScanEvent).count(),0)
        attempt=self.db.query(WorkshopScanAttempt).one()
        self.assertEqual(attempt.outcome,'ERROR')
        self.assertIsNone(self.piece.ultimo_evento)
        data=get_dashboard_monitoring(self.db)
        self.assertTrue(data['giornaliera']['timeline'][0]['errore'])
    def test_legacy_reads_cannot_be_completed_by_end_without_start(self):
        self.db.add(PieceScanEvent(piece_id=self.piece.id,qr_code='P1',commessa_id=self.job.id,
            revisione_id=self.rev.id,event_type='PIECE_READ',scanner_device_id=self.scanner.id,timestamp=datetime.utcnow()))
        self.db.add(WorkshopScanAttempt(scanner_device_id=self.scanner.id,workstation_id=self.station.id,
            piece_id=self.piece.id,raw_payload='P1',scan_kind='PIECE_READ',outcome='OK',message='Pezzo letto'))
        self.db.commit()
        self.assertFalse(self.scan('END')['ok'])
        self.assertEqual(self.db.query(WorkshopScanBlock).count(),0)
        row=next(r for r in get_dashboard_monitoring(self.db)['giornaliera']['timeline'] if r['origine']=='Scansione pezzo')
        self.assertTrue(row['errore']); self.assertIn('INIZIO mancante',row['esito'])
    def test_valid_cycle_and_unfinished_cycle_are_visible(self):
        self.assertTrue(self.scan('START')['ok'])
        rows=get_dashboard_monitoring(self.db)['giornaliera']['timeline']
        self.assertIn('FINE non registrata',rows[0]['esito'])
        self.assertTrue(self.scan('P1')['ok'])
        self.assertIn('FINE non registrata',get_dashboard_monitoring(self.db)['giornaliera']['timeline'][0]['esito'])
        self.assertTrue(self.scan('END')['ok'])
        self.assertEqual(self.db.query(WorkshopScanBlock).one().status,'CLOSED')
    def test_active_jobs_are_listed_without_daily_events(self):
        data=get_dashboard_monitoring(self.db)
        self.assertEqual(data['commesse_in_corso'][0]['codice'],'TEST')
        self.assertEqual(data['giornaliera']['timeline'],[])
