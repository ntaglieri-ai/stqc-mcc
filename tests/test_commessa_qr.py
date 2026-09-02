import unittest

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

    def test_status_update_does_not_require_separate_activation(self):
        result = api.update_commessa(
            self.commessa.id, CommessaUpdate(status=CommessaStatus.IN_PRODUZIONE), db=self.db,
        )
        self.assertEqual(result.status, CommessaStatus.IN_PRODUZIONE)


if __name__ == "__main__":
    unittest.main()
