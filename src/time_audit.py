"""Check time relationships and reconstruct a small aircraft/date sample."""

import argparse
import json
from collections import Counter
from datetime import date
from pathlib import Path

import duckdb

from src.audit import audit
from src.quality import query_rows
from src.timestamps import reconstruct
from src.airport_zones import load_mapping, file_hash
from src.timezones import load_zone, timezone_version


def time_checks(connection):
    connection.execute('''CREATE TEMP VIEW completed AS
        SELECT * FROM flights WHERE NOT Cancelled AND NOT Diverted''')
    connection.execute('''CREATE TEMP VIEW time_flags AS
        SELECT *, ArrDelay - DepDelay - ActualElapsedTime + CRSElapsedTime AS delay_residual,
            ((floor(CRSDepTime / 100) * 60 + CRSDepTime % 100 + DepDelay) % 1440 + 1440) % 1440
            <> (floor(DepTime / 100) * 60 + DepTime % 100) % 1440 AS naive_departure_mismatch
        FROM completed''')
    counts = query_rows(connection, '''
        SELECT count(*) AS completed_rows,
            count(*) FILTER (WHERE CRSElapsedTime IS NULL) AS missing_scheduled_duration,
            count(*) FILTER (WHERE ActualElapsedTime IS NULL) AS missing_actual_duration,
            count(*) FILTER (WHERE CRSElapsedTime <= 0) AS nonpositive_scheduled_duration,
            count(*) FILTER (WHERE ActualElapsedTime <= 0) AS nonpositive_actual_duration,
            count(*) FILTER (WHERE delay_residual <> 0) AS duration_delay_mismatch,
            count(*) FILTER (WHERE naive_departure_mismatch) AS naive_departure_mismatch,
            min(DepDelay) AS min_departure_delay, max(DepDelay) AS max_departure_delay
        FROM time_flags
    ''')[0]
    sample_fields = '''FlightDate, Tail_Number, Origin, Dest, Operating_Airline,
        Flight_Number_Operating_Airline, CRSDepTime, CRSArrTime, DepTime, ArrTime,
        DepDelay, ArrDelay, CRSElapsedTime, ActualElapsedTime, delay_residual'''
    samples = {}
    for name, condition in [
        ('nonpositive_duration', 'CRSElapsedTime <= 0 OR ActualElapsedTime <= 0'),
        ('duration_delay_mismatch', 'delay_residual <> 0'),
        ('naive_departure_mismatch', 'naive_departure_mismatch')
    ]:
        samples[name] = query_rows(connection, f'''
            SELECT {sample_fields} FROM time_flags WHERE {condition}
            ORDER BY FlightDate, Tail_Number, CRSDepTime, Origin,
                Operating_Airline, Flight_Number_Operating_Airline LIMIT 25
        ''')
    airports = query_rows(connection, '''
        SELECT airport FROM (SELECT Origin AS airport FROM flights UNION SELECT Dest FROM flights)
        ORDER BY airport
    ''')
    return {'counts': counts, 'airport_codes': [row['airport'] for row in airports],
            'samples': samples,
            'note': 'Flags may overlap. The naive clock check ignores DST and is not a deletion rule.'}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('input', type=Path)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--tail', required=True)
    parser.add_argument('--date', type=date.fromisoformat, required=True)
    zone_input = parser.add_mutually_exclusive_group(required=True)
    zone_input.add_argument('--airport-zone', action='append', metavar='AIRPORT=IANA_ZONE')
    zone_input.add_argument('--airport-map', type=Path)
    args = parser.parse_args()
    if args.input.resolve() == args.output.resolve():
        parser.error('Output must not overwrite input')
    if args.airport_map and args.output.resolve() == args.airport_map.resolve():
        parser.error('Output must not overwrite the airport map')
    zones = load_mapping(args.airport_map) if args.airport_map else {}
    for item in args.airport_zone or []:
        airport, separator, zone = item.partition('=')
        if not airport or not separator or not zone:
            parser.error('Use --airport-zone AIRPORT=IANA_ZONE')
        load_zone(zone)
        if airport in zones and zones[airport] != zone:
            parser.error(f'Conflicting time zones for {airport}')
        zones[airport] = zone
    report = audit(args.input)
    with duckdb.connect() as connection:
        connection.read_parquet(str(args.input)).create_view('flights')
        report['time_checks'] = time_checks(connection)
        flagged = query_rows(connection, '''
            SELECT * FROM time_flags WHERE naive_departure_mismatch
            ORDER BY FlightDate, Tail_Number, CRSDepTime, Origin
        ''')
        report['flagged_departure_checks'] = {
            'rows': [{'input': row, 'result': reconstruct(row, zones)} for row in flagged]
        }
        report['flagged_departure_checks']['status_counts'] = dict(Counter(
            row['result']['status'] for row in report['flagged_departure_checks']['rows']))
        result = connection.execute('''
            SELECT * FROM flights WHERE Tail_Number = ? AND FlightDate = ?
            ORDER BY CRSDepTime, Origin, Dest, Operating_Airline, Flight_Number_Operating_Airline
        ''', [args.tail, args.date])
        fields = [column[0] for column in result.description]
        rows = [dict(zip(fields, row)) for row in result.fetchall()]
    report['sample'] = {
        'tail': args.tail, 'date': args.date.isoformat(), 'airport_zones': zones,
        'timezone_data': timezone_version(),
        'mapping_sha256': file_hash(args.airport_map) if args.airport_map else None,
        'rows': [{'input': row, 'result': reconstruct(row, zones)} for row in rows]
    }
    report['sample']['status_counts'] = dict(Counter(row['result']['status']
                                                    for row in report['sample']['rows']))
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, indent=2, default=str) + '\n', encoding='utf-8')
    print(json.dumps(report['time_checks']['counts'], indent=2))
    print('Sample status counts:', report['sample']['status_counts'])
    print('Flagged departure status counts:', report['flagged_departure_checks']['status_counts'])
    print('Report:', args.output)


if __name__ == '__main__':
    main()
