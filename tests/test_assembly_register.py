import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

from openpyxl import Workbook
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from backend.app.api.api_v1.endpoints.commessa import get_assembly_register, get_saldature, _assembly_instances
from backend.app.db.base import Base
from backend.app.models.commessa import Commessa, CommessaRevisione, Piece
from backend.app.services.distinta import parse_assembly_records


class AssemblyRegisterTests(unittest.TestCase):
    def setUp(self):
        self.temp = TemporaryDirectory()
        self.source = Path(self.temp.name) / "assemblaggi.xlsx"
        book = Workbook()
        sheet = book.active
        sheet.append(["Assemb.", "Parte", "Q.tà", "Profilo"])
        sheet.append(["A100", None, 2, "Telaio"])
        sheet.append([None, "P100", 3, "HEA100"])
        sheet.append(["A100", "P200", 4, "HEA200"])
        sheet.append(["A200", None, 1, "Trave"])
        sheet.append([None, "P100", 5, "HEA100"])
        book.save(self.source)
        book.close()

    def tearDown(self):
        self.temp.cleanup()

    def test_children_preserve_file_quantities_and_parent_boundaries(self):
        rows = parse_assembly_records(self.source)
        self.assertEqual([row["codice"] for row in rows], ["A100", "A200"])
        self.assertEqual(rows[0]["quantita"], 2)
        self.assertEqual([(row["codice"], row["quantita"]) for row in rows[0]["children"]], [("P100", 3), ("P200", 4)])
        self.assertEqual(rows[1]["children"][0]["quantita"], 5)

    def test_register_without_workshop_records_and_without_uploaded_file(self):
        engine = create_engine("sqlite://")
        Base.metadata.create_all(engine)
        with Session(engine) as db:
            commessa = Commessa(codice="TEST-ASSEMBLY")
            db.add(commessa)
            db.flush()
            self.assertFalse(get_assembly_register(commessa.id, db)["source_available"])
            revision = CommessaRevisione(commessa_id=commessa.id, codice="r01", corrente=True, file_assemblaggi=str(self.source))
            db.add(revision)
            db.flush()
            result = get_assembly_register(commessa.id, db)
            self.assertEqual(db.query(Piece).count(), 0)
            self.assertEqual(len(result["items"]), 3)
            self.assertEqual(result["items"][0]["qr_payload"], f"STQC:ASM:{commessa.id}:A100:1")
            self.assertEqual(len(result["items"][0]["children"]), 2)
            welding = get_saldature(commessa.id, db)
            self.assertEqual([r["id"] for r in result["items"]], [r["id"] for r in welding["items"]])
            self.assertEqual(len({r["qr_image_url"] for r in result["items"]}), 3)
            self.assertEqual([r["progressivo"] for r in result["items"]], [1, 2, 1])
            self.assertTrue(all(r["quantita"] == 1 for r in result["items"]))
            self.assertEqual(result["items"][1]["children"][0]["quantita"], 3)
            revision.file_assemblaggi = None
            self.assertEqual(get_assembly_register(commessa.id, db)["items"], [])
        engine.dispose()

    def test_explicit_unknown_parent_is_not_attached_to_previous_parent(self):
        rows = [["Assemb.", "Parte", "Q.tà"], ["A100", None, 1], ["A999", "P100", 2]]
        with patch("backend.app.services.distinta._extract_rows", return_value=rows):
            with self.assertRaises(ValueError):
                parse_assembly_records(self.source)

    def test_eighty_assemblies_have_eighty_stable_distinct_qr(self):
        records = [{"codice": "2553-B100", "quantita": 80, "children": [{"codice": "P1", "quantita": 2}]}]
        items = _assembly_instances(records, 1)
        self.assertEqual(len(items), 80)
        self.assertEqual(len({r["id"] for r in items}), 80)
        self.assertEqual(items[-1]["progressivo"], 80)
        self.assertTrue(all(r["children"][0]["quantita"] == 2 for r in items))
        self.assertEqual(items, _assembly_instances(records, 1))

    def test_repeated_headers_keep_their_own_components(self):
        rows = [["Assemb.", "Parte", "Q.tà"], ["A100", None, 2], [None, "P100", 3], ["A100", None, 1], [None, "P200", 4]]
        with patch("backend.app.services.distinta._extract_rows", return_value=rows):
            items = _assembly_instances(parse_assembly_records(self.source), 1)
        self.assertEqual([r["progressivo"] for r in items], [1, 2, 3])
        self.assertEqual([r["children"][0]["codice"] for r in items], ["P100", "P100", "P200"])
