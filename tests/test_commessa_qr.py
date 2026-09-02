import unittest
import asyncio
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch
from fastapi import HTTPException

from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from backend.app.api.api_v1.endpoints import commessa as api
from backend.app.db.base import Base
from backend.app.models.commessa import Commessa, CommessaRevisione, CommessaStatus, Piece
from backend.app.models.warehouse import DistintaImport, DistintaItem
from backend.app.models import user  # noqa: F401 - register referenced tables
from backend.app.schemas.commessa import CommessaUpdate


class CommessaQrTests(unittest.TestCase):
    def setUp(self):
        self.engine = create_engine("sqlite://")
        Base.metadata.create_all(self.engine)
        self.db = Session(self.engine)
        self.commessa = Commessa(codice="TEST-QR")
        self.db.add(self.commessa)
        self.db.flush()
        self.revision = CommessaRevisione(commessa_id=self.commessa.id, codice="r01")
        imported = DistintaImport(filename="test.xlsx")
        self.db.add_all([self.revision, imported])
        self.db.flush()
        self.item = DistintaItem(
            import_id=imported.id, revisione_id=self.revision.id,
            commessa_id=self.commessa.id, part_number="P1", instance_number=1,
            quantity=1, description="IPE 100",
        )
        self.db.add(self.item)
        self.db.commit()

    def tearDown(self):
        self.db.close()
        self.engine.dispose()

    def test_registry_creates_qr_without_manual_activation_and_preserves_progress(self):
        result = api.list_commessa_item_qr(self.commessa.id, db=self.db)
        self.assertEqual(result["total"], 1)
        piece = self.db.query(Piece).one()
        self.assertTrue(piece.qr_attivo)
        self.assertTrue(self.item.qr_attivo)
        self.assertIn("/qr/items/", result["items"][0]["label_url"])
        piece.stato_attuale = "FASE_COMPLETATA"
        self.db.commit()
        api.list_commessa_item_qr(self.commessa.id, db=self.db)
        self.assertEqual(self.db.query(Piece).count(), 1)
        self.assertEqual(piece.stato_attuale, "FASE_COMPLETATA")
        pdf = api.download_commessa_piece_label(
            self.commessa.id, piece.id, width_mm=70, height_mm=50, db=self.db,
        )
        self.assertTrue(pdf.body.startswith(b"%PDF"))
        batch = api.download_commessa_piece_labels(
            self.commessa.id, api.PieceLabelsRequest(piece_ids=[piece.id]), db=self.db,
        )
        self.assertTrue(batch.body.startswith(b"%PDF"))

    def test_design_checklist_persists_and_is_independent(self):
        initial = api.get_progettazione(self.commessa.id, db=self.db)
        self.assertEqual(len(initial), 9)
        self.assertTrue(all(not x["inizio"] and not x["fine"] for x in initial))
        result = api.update_progettazione(self.commessa.id, "modello_ifc", api.ProgettazioneUpdate(inizio=False, fine=True), db=self.db)
        self.assertTrue(result["inizio"])
        self.assertEqual(result["stato"], "COMPLETATA")
        self.db.expire_all()
        saved = api.get_progettazione(self.commessa.id, db=self.db)
        self.assertTrue(saved[0]["fine"])
        self.assertFalse(saved[1]["inizio"])
        other = Commessa(codice="OTHER")
        self.db.add(other)
        self.db.commit()
        self.assertFalse(api.get_progettazione(other.id, db=self.db)[0]["fine"])
        reset = api.update_progettazione(self.commessa.id, "modello_ifc", api.ProgettazioneUpdate(inizio=False, fine=False), db=self.db)
        self.assertEqual(reset["stato"], "NON_INIZIATA")
        self.assertEqual(self.commessa.status, CommessaStatus.APERTA)

    def test_upload_requires_distinte_started_for_same_commessa(self):
        def upload():
            return asyncio.run(api.create_analisi_commessa(
                self.commessa.id, lista_pezzi=None, assemblaggi=None,
                spedizione=None, bulloneria=None, predistinta=False, note=None, db=self.db,
            ))

        with TemporaryDirectory() as directory, patch.object(api.settings, "upload_dir", Path(directory)):
            with self.assertRaises(HTTPException) as blocked:
                upload()
            self.assertEqual(blocked.exception.status_code, 409)
            self.assertEqual(list(Path(directory).iterdir()), [])
            api.update_progettazione(self.commessa.id, "modello_ifc", api.ProgettazioneUpdate(inizio=True, fine=True), db=self.db)
            other = Commessa(codice="OTHER-UPLOAD")
            self.db.add(other)
            self.db.commit()
            api.update_progettazione(other.id, "distinte", api.ProgettazioneUpdate(inizio=True, fine=False), db=self.db)
            with self.assertRaises(HTTPException) as still_blocked:
                upload()
            self.assertEqual(still_blocked.exception.status_code, 409)
            api.update_progettazione(self.commessa.id, "distinte", api.ProgettazioneUpdate(inizio=True, fine=False), db=self.db)
            with self.assertRaises(HTTPException) as missing_files:
                upload()
            self.assertEqual(missing_files.exception.status_code, 422)
            api.update_progettazione(self.commessa.id, "distinte", api.ProgettazioneUpdate(inizio=False, fine=False), db=self.db)
            with self.assertRaises(HTTPException) as blocked_again:
                upload()
            self.assertEqual(blocked_again.exception.status_code, 409)

    def test_status_update_does_not_require_separate_activation(self):
        result = api.update_commessa(
            self.commessa.id, CommessaUpdate(status=CommessaStatus.IN_PRODUZIONE), db=self.db,
        )
        self.assertEqual(result.status, CommessaStatus.IN_PRODUZIONE)


if __name__ == "__main__":
    unittest.main()
