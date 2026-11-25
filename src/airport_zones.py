"""Build a small airport-zone lookup from a pinned reference file."""

import argparse
import csv
import hashlib
import json
import urllib.request
from collections import defaultdict
from pathlib import Path

import duckdb

from src.timezones import load_zone, timezone_version


def file_hash(path):
    digest = hashlib.sha256()
    with path.open('rb') as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b''):
            digest.update(chunk)
    return digest.hexdigest()


def build_mapping(airport_ids, source_rows, overrides):
    by_iata = defaultdict(list)
    for row in source_rows:
        if row['iata']:
            by_iata[row['iata']].append(row)
    zones, applied = {}, {}
    for airport, ids in sorted(airport_ids.items()):
        override = overrides.get(airport)
        source_code = override['source_iata'] if override else airport
        if override and sorted(ids) != sorted(override['expected_bts_airport_ids']):
            raise ValueError(f'Airport ID changed for override {airport}')
        matches = by_iata.get(source_code, [])
        if len(matches) != 1:
            raise ValueError(f'{airport}: expected one source record, found {len(matches)}')
        zone = matches[0]['tz']
        load_zone(zone)
        zones[airport] = zone
        if override:
            applied[airport] = override
    return zones, applied


def load_mapping(path):
    document = json.loads(path.read_text())
    if document['timezone_data'] != timezone_version():
        raise ValueError('Mapping and installed time-zone data versions differ')
    for zone in set(document['zones'].values()):
        load_zone(zone)
    return document['zones']


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('input', type=Path)
    parser.add_argument('--source-manifest', type=Path, default=Path('reference/airports_source.json'))
    parser.add_argument('--source-dir', type=Path, default=Path('data/reference/airportsdata'))
    parser.add_argument('--overrides', type=Path, default=Path('reference/airport_code_overrides.json'))
    parser.add_argument('--output', type=Path, default=Path('reference/airport_timezones.json'))
    parser.add_argument('--download', action='store_true')
    args = parser.parse_args()
    source = json.loads(args.source_manifest.read_text())
    protected = [args.input, args.source_manifest, args.overrides,
                 args.source_dir / 'airports.csv', args.source_dir / 'LICENSE']
    if args.output.resolve() in [path.resolve() for path in protected]:
        parser.error('Output must not overwrite an input file')
    for name, info in source['files'].items():
        if name not in ('airports.csv', 'LICENSE'):
            parser.error('Unexpected file in source manifest')
        path = args.source_dir / name
        if args.download:
            with urllib.request.urlopen(info['url'], timeout=30) as response:
                content = response.read()
            if hashlib.sha256(content).hexdigest() != info['sha256']:
                raise ValueError(f'Download hash mismatch: {name}')
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(content)
        if file_hash(path) != info['sha256']:
            raise ValueError(f'Source hash mismatch: {name}')
    with (args.source_dir / 'airports.csv').open(newline='', encoding='utf-8') as stream:
        rows = list(csv.DictReader(stream))
    with duckdb.connect() as connection:
        connection.read_parquet(str(args.input)).create_view('flights')
        records = connection.execute('''
            SELECT Origin, OriginAirportID FROM flights
            UNION SELECT Dest, DestAirportID FROM flights
        ''').fetchall()
        dates = connection.execute('SELECT min(FlightDate), max(FlightDate) FROM flights').fetchone()
    airport_ids = defaultdict(set)
    for code, airport_id in records:
        if not code or airport_id is None:
            raise ValueError('Missing airport code or ID')
        airport_ids[code].add(airport_id)
    zones, applied = build_mapping(airport_ids, rows, json.loads(args.overrides.read_text()))
    document = {
        'source': source, 'source_license': 'airportsdata-LICENSE.txt',
        'timezone_data': timezone_version(),
        'input': {'filename': args.input.name, 'sha256': file_hash(args.input),
                  'date_start': str(dates[0]), 'date_end': str(dates[1])},
        'coverage': {'airport_codes': len(airport_ids), 'mapped': len(zones),
                     'direct_matches': len(zones) - len(applied), 'overrides': len(applied)},
        'limitations': 'Current reference with an explicit historical-code override. '
                       'Coverage is not independent historical validation of every airport.',
        'applied_overrides': applied,
        'bts_airport_ids': {code: sorted(ids) for code, ids in sorted(airport_ids.items())},
        'zones': zones
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(document, indent=2) + '\n')
    (args.output.parent / 'airportsdata-LICENSE.txt').write_bytes((args.source_dir / 'LICENSE').read_bytes())
    print(json.dumps(document['coverage'], indent=2))
    print('Time-zone data:', timezone_version())
    print('Lookup:', args.output)


if __name__ == '__main__':
    main()
