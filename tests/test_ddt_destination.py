import unittest

from pydantic import ValidationError
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session

from backend.app.api.api_v1.endpoints.inventario import DdtConfirmRequest, _apply_ddt_confirm
from backend.app.db.base import Base
from backend.app.models import commessa  # Register related tables.
from backend.app.models.warehouse import StockMovement, WarehouseItem


class DdtDestinationTests(unittest.TestCase):
    def test_legacy_requests_default_to_warehouse(self):
        self.assertEqual(DdtConfirmRequest(items=[]).material_destination, 'warehouse')

    def test_unknown_destination_is_rejected(self):
        with self.assertRaises(ValidationError):
            DdtConfirmRequest(items=[], material_destination='unknown')

    def test_destination_survives_confirmation_without_automatic_reservation(self):
        for destination, label in [
            ('warehouse', 'Per magazzino'),
            ('commessa', 'Per una commessa'),
            ('partial_commessa', 'Parzialmente per una commessa'),
        ]:
            with self.subTest(destination=destination):
                engine = create_engine('sqlite://')
                try:
                    Base.metadata.create_all(engine)
                    with Session(engine) as db:
                        payload = DdtConfirmRequest(
                            material_destination=destination,
                            items=[dict(material_code='DDT-TEST', description='Trave', quantity=2)],
                        )
                        result = _apply_ddt_confirm(db, payload)
                        db.commit()
                        self.assertEqual(result['material_destination'], destination)
                        movement = db.scalars(select(StockMovement)).one()
                        self.assertIn(label, movement.reason)
                        self.assertIsNone(movement.commessa_id)
                        items = db.scalars(select(WarehouseItem)).all()
                        self.assertEqual(len(items), 2)
                        self.assertTrue(all(item.reserved_for_commessa is None for item in items))
                finally:
                    engine.dispose()


if __name__ == '__main__':
    unittest.main()
