import unittest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session
from backend.app.db.base import Base
import backend.app.models.user
import backend.app.models.warehouse
from backend.app.models.commessa import Workstation, WorkstationQr
from backend.app.services.station_qr import seed_station_qr


class StationQrSeedTests(unittest.TestCase):
    def test_existing_printed_payload_is_preserved_for_renamed_station(self):
        engine = create_engine("sqlite://")
        Base.metadata.create_all(engine)
        with Session(engine) as db:
            old = Workstation(code="FORATURA_FICEP01", name="Old", start_qr_code="STQC:WS:FORATURA_FICEP01:START", end_qr_code="STQC:WS:FORATURA_FICEP01:END")
            db.add(old)
            db.flush()
            seed_station_qr(db, old)
            old_qrs = db.query(WorkstationQr).all()
            original = [(q.id, q.payload, q.workstation_id) for q in old_qrs]
            old.code = "RENAMED"
            old.start_qr_code = "STQC:WS:RENAMED:START"
            old.end_qr_code = "STQC:WS:RENAMED:END"
            old_qrs[1].active = False
            db.flush()
            new = Workstation(code="FORATURA_FICEP01", name="New", start_qr_code=original[0][1], end_qr_code=original[1][1])
            db.add(new)
            db.flush()
            seed_station_qr(db, new)
            db.commit()
            seed_station_qr(db, new)
            self.assertEqual(db.query(WorkstationQr).count(), 4)
            self.assertEqual([(q.id, q.payload, q.workstation_id) for q in old_qrs], original)
            new_qrs = db.query(WorkstationQr).filter_by(workstation_id=new.id).all()
            self.assertEqual({q.behavior for q in new_qrs}, {"START", "END"})
            self.assertTrue(all(q.payload.startswith("STQC:ACTION:") for q in new_qrs))
        engine.dispose()
