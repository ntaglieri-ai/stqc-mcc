import unittest
from datetime import datetime

from fastapi import HTTPException
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from backend.app.api.api_v1.endpoints.commessa import get_monitoring
from backend.app.db.base import Base
from backend.app.models.commessa import (
    Commessa, CommessaRevisione, CommessaPostOfficinaItem, Piece, PieceScanEvent,
    WorkshopScanAttempt,
)


class MonitoringTests(unittest.TestCase):
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
        self.assertTrue(all(r['stato'] == 'NON_INIZIATA' for r in result['progettazione']))
        with self.assertRaises(HTTPException) as error:
            get_monitoring(999, self.db)
        self.assertEqual(error.exception.status_code, 404)

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
        self.assertEqual(len(result['officina']), 1)
        self.assertEqual(len(result['assemblaggi']), 1)
        self.assertEqual(result['officina'][0]['marca'], 'M1')
        self.assertIsNone(result['officina'][0]['durata_secondi'])
        self.assertFalse(self.db.new)
        self.assertFalse(self.db.dirty)


if __name__ == '__main__':
    unittest.main()
