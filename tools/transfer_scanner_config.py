"""Export scanner configuration; import atomically, refusing conflicting identities."""
import argparse
import json
import sys
import os
from uuid import uuid4
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from sqlalchemy import MetaData, Table, select, inspect, func
from backend.app.db.session import engine

FIELDS = {
    'workstations': 'code name description active progress_mode fase start_qr_code end_qr_code'.split(),
    'workstation_qr_codes': 'label actions description behavior payload active'.split(),
    'scanner_devices': 'scanner_code name description scan_mode fase ip_address serial_number device_token active'.split(),
}


def tables():
    metadata = MetaData()
    return {name: Table(name, metadata, autoload_with=engine) for name in FIELDS}


def export_config():
    ts = tables()
    with engine.connect() as conn:
        stations = conn.execute(select(ts['workstations'])).mappings().all()
        codes = {row['id']: row['code'] for row in stations}
        data = {'version': 1}
        for name, fields in FIELDS.items():
            data[name] = []
            for row in conn.execute(select(ts[name])).mappings():
                item = {key: row[key] for key in fields}
                if name != 'workstations':
                    fk = 'workstation_id' if name == 'workstation_qr_codes' else 'postazione_id'
                    item['station_code'] = codes[row[fk]] if row[fk] is not None else None
                data[name].append(item)
        return data


def import_config(data, apply=False):
    if data['version'] != 1:
        raise ValueError('Unsupported format')
    ts = tables()
    with engine.connect() as conn:
        tx = conn.begin()
        try:
            ids = {}
            counts = {}
            for name, fields in FIELDS.items():
                table = ts[name]
                key = {'workstations': 'code', 'workstation_qr_codes': 'payload', 'scanner_devices': 'scanner_code'}[name]
                added = matched = 0
                for item in data[name]:
                    values = {field: item[field] for field in fields}
                    if name != 'workstations':
                        fk = 'workstation_id' if name == 'workstation_qr_codes' else 'postazione_id'
                        values[fk] = ids[item['station_code']] if item['station_code'] is not None else None
                    old = conn.execute(select(table).where(table.c[key] == item[key])).mappings().first()
                    if old:
                        differences = [field for field, value in values.items() if old[field] != value]
                        if differences:
                            # Never print token or QR payload values.
                            raise ValueError(f'Conflict in {name}, row {old["id"]}: {", ".join(differences)}')
                        row_id = old['id']
                        matched += 1
                    else:
                        row_id = conn.execute(table.insert().values(**values)).inserted_primary_key[0]
                        added += 1
                    if name == 'workstations':
                        ids[item['code']] = row_id
                counts[name] = {'added': added, 'unchanged': matched}
            if apply:
                tx.commit()
            else:
                tx.rollback()
            return counts
        except Exception:
            tx.rollback()
            raise


def replace_config(data, apply=False):
    """Replace configuration only, retaining existing row IDs for historical references."""
    if data['version'] != 1:
        raise ValueError('Unsupported format')
    ts = tables()
    with engine.connect() as conn:
        tx = conn.begin()
        try:
            keys = {'workstations': 'code', 'scanner_devices': 'scanner_code', 'workstation_qr_codes': 'payload'}
            existing = {name: {r[keys[name]]: dict(r) for r in conn.execute(select(table)).mappings()} for name, table in ts.items()}
            extras = {}
            for name in ts:
                incoming = {r[keys[name]] for r in data[name]}
                if len(incoming) != len(data[name]):
                    raise ValueError(f'Duplicate identities in {name}')
                extras[name] = [row['id'] for key, row in existing[name].items() if key not in incoming]
            inspector = inspect(conn)
            for other_name in inspector.get_table_names():
                if other_name in ts:
                    continue
                for fk in inspector.get_foreign_keys(other_name):
                    target = fk['referred_table']
                    if target in extras and extras[target]:
                        other = Table(other_name, MetaData(), autoload_with=conn)
                        column = other.c[fk['constrained_columns'][0]]
                        if conn.scalar(select(func.count()).select_from(other).where(column.in_(extras[target]))):
                            raise ValueError(f'Historical references in {other_name}; cannot remove {target}')
            # Free unique fields before reassignment (including renamed stations).
            for row in existing['workstations'].values():
                conn.execute(ts['workstations'].update().where(ts['workstations'].c.id == row['id']).values(
                    start_qr_code='TRANSFER:' + uuid4().hex, end_qr_code='TRANSFER:' + uuid4().hex))
            for row in existing['scanner_devices'].values():
                conn.execute(ts['scanner_devices'].update().where(ts['scanner_devices'].c.id == row['id']).values(device_token=None))
            station_ids = {}
            counts = {}
            for name, fields in FIELDS.items():
                table = ts[name]
                for item in data[name]:
                    values = {field: item[field] for field in fields}
                    if name != 'workstations':
                        fk = 'workstation_id' if name == 'workstation_qr_codes' else 'postazione_id'
                        values[fk] = station_ids[item['station_code']] if item['station_code'] is not None else None
                    old = existing[name].get(item[keys[name]])
                    if old:
                        row_id = old['id']
                        conn.execute(table.update().where(table.c.id == row_id).values(**values))
                    else:
                        row_id = conn.execute(table.insert().values(**values)).inserted_primary_key[0]
                    if name == 'workstations':
                        station_ids[item['code']] = row_id
                counts[name] = len(data[name])
            for name in ['workstation_qr_codes', 'scanner_devices', 'workstations']:
                if extras[name]:
                    conn.execute(ts[name].delete().where(ts[name].c.id.in_(extras[name])))
            codes_by_id = {v: k for k, v in station_ids.items()}
            for name, fields in FIELDS.items():
                actual = []
                for row in conn.execute(select(ts[name])).mappings():
                    item = {field: row[field] for field in fields}
                    if name != 'workstations':
                        fk = 'workstation_id' if name == 'workstation_qr_codes' else 'postazione_id'
                        item['station_code'] = codes_by_id[row[fk]] if row[fk] is not None else None
                    actual.append(item)
                if sorted(actual, key=lambda r: r[keys[name]]) != sorted(data[name], key=lambda r: r[keys[name]]):
                    raise ValueError(f'Verification failed: {name}')
            if apply:
                tx.commit()
            else:
                tx.rollback()
            return counts
        except Exception:
            tx.rollback()
            raise


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('mode', choices=['export', 'import', 'replace'])
    parser.add_argument('file')
    parser.add_argument('--apply', action='store_true')
    parser.add_argument('--backup')
    args = parser.parse_args()
    if args.mode == 'export':
        data = export_config()
        with open(args.file, 'x', encoding='utf-8') as output:
            json.dump(data, output, ensure_ascii=False, indent=2)
        print(json.dumps({name: len(data[name]) for name in FIELDS}))
    elif args.mode == 'replace':
        if args.apply:
            if not args.backup:
                parser.error('--backup required for replacement')
            with os.fdopen(os.open(args.backup, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600), 'w', encoding='utf-8') as output:
                json.dump(export_config(), output, ensure_ascii=False, indent=2)
        print(json.dumps(replace_config(json.loads(Path(args.file).read_text(encoding='utf-8')), args.apply)))
    else:
        print(json.dumps(import_config(json.loads(Path(args.file).read_text(encoding='utf-8')), args.apply)))
