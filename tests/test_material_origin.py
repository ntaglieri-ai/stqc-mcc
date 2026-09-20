import unittest
from datetime import datetime
from sqlalchemy import create_engine
from sqlalchemy.orm import Session
from backend.app.db.base import Base
from backend.app.models.user import User
from backend.app.models.commessa import Commessa, CommessaRevisione, Piece, ScannerDevice
from backend.app.models.warehouse import (
    Material, WarehouseChangeRequest, WarehouseItem, WarehouseCustomField, WarehouseCustomValue,
)
from backend.app.services.preproduction_scan import _assign_warehouse_origin
from backend.app.services.material_origin import piece_origin_attributes


class MaterialOriginTests(unittest.TestCase):
    def test_mapping_appends_snapshot_without_raw_weights(self):
        engine = create_engine('sqlite://')
        Base.metadata.create_all(engine)
        try:
            with Session(engine) as db:
                commessa = Commessa(codice='TEST')
                material = Material(code='RAW', description='Grezzo', qualita='S355', norma_uni='EN10025', peso_1_pz=500)
                scanner = ScannerDevice(scanner_code='MAP', name='Mapping', device_token='map', scan_mode='MAGAZZINO')
                db.add_all([commessa, material, scanner]); db.flush()
                revision = CommessaRevisione(commessa_id=commessa.id, codice='r01')
                raw = WarehouseItem(material_id=material.id, ordinal=1, colata='COLATA-OVERRIDE', peso_1_pz=600)
                cert = WarehouseCustomField(key='certificato', label='Certificato')
                weight = WarehouseCustomField(key='peso_grezzo', label='Peso grezzo')
                db.add_all([revision, raw, cert, weight]); db.flush()
                db.add_all([WarehouseCustomValue(material_id=material.id, field_id=cert.id, value='CERT-31'),
                            WarehouseCustomValue(material_id=material.id, field_id=weight.id, value='600')])
                piece = Piece(commessa_id=commessa.id, revisione_id=revision.id, qr_code='P1', qr_payload='P1',
                              marca_pos='P1', progressivo=1, peso_kg=12, lunghezza_mm=120)
                db.add(piece); db.flush()
                _assign_warehouse_origin(db, scanner, piece, raw, datetime.utcnow(), raw_payload='P1', external_id=None)
                db.commit()
                fields = piece_origin_attributes(piece)
                self.assertEqual(fields['Colata'], 'COLATA-OVERRIDE')
                self.assertEqual(fields['Norma'], 'EN10025')
                self.assertEqual(fields['Extra · Certificato'], 'CERT-31')
                self.assertFalse(any('peso' in key.lower() for key in fields))
                self.assertEqual(piece.peso_kg, 12)
                self.assertEqual(piece.lunghezza_mm, 120)
                request = db.query(WarehouseChangeRequest).one()
                self.assertEqual(request.action, 'mapped_grezzo_outgoing')
                self.assertEqual(request.payload['uuid'], raw.uuid)
                self.assertEqual(request.payload['piece_ids'], [piece.id])
                raw.colata = 'CHANGED'; db.commit()
                self.assertEqual(piece_origin_attributes(piece)['Colata'], 'COLATA-OVERRIDE')
        finally:
            engine.dispose()
