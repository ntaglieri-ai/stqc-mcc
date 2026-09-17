"""Material origin attributes appended to pieces, without raw-material weights."""
from sqlalchemy.orm import object_session
from backend.app.models.warehouse import WarehouseItem, WarehouseCustomField, WarehouseCustomValue


def origin_attributes(db, item):
    material = item.material
    fields = {'UUID grezzo': item.uuid, 'Codice materiale': material.code,
              'Descrizione': material.description, 'Unità': material.unit,
              'Specifica': material.specification, 'Note': item.notes}
    for key, label in [('tipo', 'Tipo'), ('profilo', 'Profilo'), ('dimensioni', 'Dimensioni'),
                       ('norma_uni', 'Norma'), ('qualita', 'Qualità'), ('colata', 'Colata'),
                       ('commessa_ref', 'Riferimento'), ('uso_materiale', 'Uso materiale'),
                       ('posizione', 'Posizione')]:
        value = getattr(item, key, None)
        fields[label] = value if value is not None else getattr(material, key, None)
    for field, value in (db.query(WarehouseCustomField, WarehouseCustomValue)
                         .join(WarehouseCustomValue, WarehouseCustomValue.field_id == WarehouseCustomField.id)
                         .filter(WarehouseCustomValue.material_id == item.material_id).all()):
        if any(word in (field.key + ' ' + field.label).lower() for word in ('peso', 'weight', 'massa', 'mass')):
            continue
        fields['Extra · ' + field.label] = value.value
    return fields


def piece_origin_attributes(piece):
    if not piece.materiale_origine_id:
        return {}
    for event in sorted(piece.scan_events, key=lambda row: (row.timestamp, row.id or 0), reverse=True):
        if event.event_type == 'MATERIAL_ASSIGNED':
            fields = (event.metadata_json or {}).get('origin_attributes')
            if fields is not None:
                return fields
            break
    db = object_session(piece)
    item = db.get(WarehouseItem, piece.materiale_origine_id) if db else None
    return origin_attributes(db, item) if item else {}
