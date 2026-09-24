import unittest

from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from backend.app.api.api_v1.endpoints.admin import list_workstation_qr_codes, list_workstations
from backend.app.db.base import Base
from backend.app.models.commessa import Workstation


class WorkstationListingTests(unittest.TestCase):
    def test_warehouse_stations_are_listed_and_inactive_filter_is_preserved(self):
        engine = create_engine("sqlite://")
        Base.metadata.create_all(engine)
        try:
            with Session(engine) as db:
                for code, active in [("MAGAZZINO", True), ("MAGAZZINO_2", True), ("MAGAZZINO_OLD", False)]:
                    db.add(Workstation(
                        code=code, name=code, fase="magazzino", active=active,
                        start_qr_code=f"STQC:WS:{code}:START",
                        end_qr_code=f"STQC:WS:{code}:END",
                    ))
                db.commit()
                items = list_workstation_qr_codes(include_inactive=False, db=db)["items"]
                self.assertEqual({row["code"] for row in items}, {"MAGAZZINO", "MAGAZZINO_2"})
                self.assertEqual({row["id"] for row in items}, {ws.id for ws in list_workstations(False, db)})
                self.assertTrue(all(len(row["codes"]) == 2 for row in items))
                self.assertEqual(len(list_workstation_qr_codes(include_inactive=True, db=db)["items"]), 3)
        finally:
            engine.dispose()
