import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

from fastapi import HTTPException
from openpyxl import Workbook
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from backend.app.api.api_v1.endpoints.commessa import get_saldature
from backend.app.db.base import Base
from backend.app.models.commessa import Commessa, CommessaRevisione, Piece
from backend.app.services.distinta import parse_assembly_parents


class SaldatureTests(unittest.TestCase):
    def setUp(self):
        self.temp = TemporaryDirectory()
        self.source = Path(self.temp.name) / 'assemblaggi.xlsx'
        workbook = Workbook()
        sheet = workbook.active
        sheet.append(['Assemb.', 'Parte', 'Q.tà', 'Profilo'])
        sheet.append(['A100', None, 2, 'Telaio'])
        sheet.append([None, 'P100', 30, 'HEA100'])
        sheet.append(['A100', 'P200', 40, 'HEA200'])
        sheet.append(['A200', None, 3, 'Trave'])
        sheet.append([None, 'P300', 50, 'IPE100'])
        workbook.save(self.source)
        workbook.close()
        self.engine = create_engine('sqlite://')
        Base.metadata.create_all(self.engine)
        self.db = Session(self.engine)
        self.commessa = Commessa(codice='TEST-SALDATURE')
        self.db.add(self.commessa)
        self.db.flush()

    def tearDown(self):
        self.db.close()
        self.engine.dispose()
        self.temp.cleanup()

    def test_only_parent_headers_and_parent_quantities(self):
        rows = parse_assembly_parents(self.source)
        self.assertEqual([row['codice'] for row in rows], ['A100', 'A200'])
        self.assertEqual([row['quantita'] for row in rows], [2, 3])

    def test_current_revision_and_parent_qr_without_child_records(self):
        self.db.add(CommessaRevisione(commessa_id=self.commessa.id, codice='r01', corrente=False, file_assemblaggi='missing-old.xls'))
        revision = CommessaRevisione(commessa_id=self.commessa.id, codice='r02', corrente=True, file_assemblaggi=str(self.source))
        self.db.add(revision)
        self.db.flush()
        result = get_saldature(self.commessa.id, self.db)
        self.assertEqual(result['revisione_id'], revision.id)
        self.assertEqual(result['summary'], {'assemblati': 2, 'quantita': 5})
        self.assertEqual(result['items'][0]['qr_payload'], f'STQC:ASM:{self.commessa.id}:A100')
        self.assertEqual(self.db.query(Piece).count(), 0)

    def test_missing_upload_is_empty_and_missing_file_is_explicit(self):
        revision = CommessaRevisione(commessa_id=self.commessa.id, codice='r01', corrente=True)
        self.db.add(revision)
        self.db.flush()
        result = get_saldature(self.commessa.id, self.db)
        self.assertFalse(result['source_available'])
        self.assertEqual(result['items'], [])
        revision.file_assemblaggi = str(self.source.parent / 'missing.xls')
        with self.assertRaises(HTTPException) as error:
            get_saldature(self.commessa.id, self.db)
        self.assertEqual(error.exception.status_code, 404)

    def test_ambiguous_columns_are_rejected(self):
        with patch('backend.app.services.distinta._extract_rows', return_value=[['Codice', 'Q.tà'], ['P100', 100]]):
            with self.assertRaises(ValueError):
                parse_assembly_parents(self.source)


if __name__ == '__main__':
    unittest.main()
