"""Check duplicate records, tied flight times, and HHMM fields."""

import argparse
import json
import tempfile
from pathlib import Path

import duckdb

from src.audit import audit


def query_rows(connection, sql):
    result = connection.execute(sql)
    names = [column[0] for column in result.description]
    return [dict(zip(names, row)) for row in result.fetchall()]


def duplicate_summary(connection, columns):
    # Count extra rows, not every row in a repeated group.
    names = ', '.join('"' + name.replace('"', '""') + '"' for name in columns)
    return query_rows(connection, f'''
        SELECT count(*) AS groups, coalesce(sum(n), 0) AS rows_in_groups,
            coalesce(sum(n - 1), 0) AS extra_rows
        FROM (SELECT count(*) AS n FROM flights GROUP BY {names} HAVING count(*) > 1)
    ''')[0]


def check_quality(connection):
    columns = [row[0] for row in connection.execute('DESCRIBE flights').fetchall()]
    data_columns = [name for name in columns if name != '__index_level_0__']
    flight_key = ['FlightDate', 'Operating_Airline', 'Flight_Number_Operating_Airline',
                  'Origin', 'Dest', 'CRSDepTime']
    duplicates = {
        'all_data_fields': duplicate_summary(connection, data_columns),
        'candidate_flight_key': duplicate_summary(connection, flight_key),
        'candidate_key_fields': flight_key,
        'note': 'The saved pandas index is excluded. A repeated key is not proof of a duplicate.'
    }

    connection.execute('''
        CREATE TEMP VIEW eligible AS SELECT * FROM flights
        WHERE NOT Cancelled AND NOT Diverted
            AND Tail_Number IS NOT NULL AND trim(Tail_Number) <> ''
    ''')
    connection.execute('''
        CREATE TEMP VIEW tied_groups AS
        SELECT Tail_Number, FlightDate, CRSDepTime, count(*) AS n,
            count(DISTINCT Origin) AS origins, count(DISTINCT Dest) AS destinations,
            count(DISTINCT (Operating_Airline, Flight_Number_Operating_Airline)) AS flight_numbers
        FROM eligible GROUP BY Tail_Number, FlightDate, CRSDepTime HAVING count(*) > 1
    ''')
    ties = query_rows(connection, '''
        SELECT count(*) AS groups, coalesce(sum(n), 0) AS rows_in_groups,
            count(*) FILTER (WHERE origins > 1) AS different_origins,
            count(*) FILTER (WHERE destinations > 1) AS different_destinations,
            count(*) FILTER (WHERE flight_numbers > 1) AS different_flight_numbers
        FROM tied_groups
    ''')[0]
    # Select whole groups so the sample contains both flights.
    ties['sample'] = query_rows(connection, '''
        WITH sample_groups AS (
            SELECT * FROM tied_groups ORDER BY Tail_Number, FlightDate, CRSDepTime LIMIT 10
        )
        SELECT e.Tail_Number, e.FlightDate, e.CRSDepTime, e.Origin, e.Dest,
            e.Operating_Airline, e.Flight_Number_Operating_Airline,
            e.DepTime, e.ArrTime, e.DepDelay, e.ArrDelay, e.Cancelled, e.Diverted
        FROM eligible e JOIN sample_groups t USING (Tail_Number, FlightDate, CRSDepTime)
        ORDER BY e.Tail_Number, e.FlightDate, e.CRSDepTime,
            e.Origin, e.Dest, e.Operating_Airline, e.Flight_Number_Operating_Airline
    ''')

    times = {}
    for field in ['CRSDepTime', 'CRSArrTime', 'DepTime', 'ArrTime']:
        # Accept 2400 as a separate midnight case; do not convert dates here.
        valid = f'''isfinite({field}) AND {field} = floor({field}) AND
            (({field} BETWEEN 0 AND 2359 AND {field} % 100 < 60) OR {field} = 2400)'''
        times[field] = query_rows(connection, f'''
            SELECT count(*) FILTER (WHERE {field} IS NULL) AS missing,
                count(*) FILTER (WHERE {valid}) AS valid_including_2400,
                count(*) FILTER (WHERE {field} IS NOT NULL AND NOT ({valid})) AS invalid,
                count(*) FILTER (WHERE {field} = 2400) AS midnight_2400,
                count(*) FILTER (WHERE {field} = 0) AS midnight_zero
            FROM flights
        ''')[0]
    times['note'] = 'Clock-format checks only. Dates, time zones and flight order are not validated.'
    completed = query_rows(connection, '''
        SELECT count(*) AS rows,
            count(*) FILTER (WHERE DepTime IS NULL) AS missing_departure_time,
            count(*) FILTER (WHERE ArrTime IS NULL) AS missing_arrival_time,
            count(*) FILTER (WHERE DepDelay IS NULL) AS missing_departure_delay,
            count(*) FILTER (WHERE ArrDelay IS NULL) AS missing_arrival_delay
        FROM flights WHERE NOT Cancelled AND NOT Diverted
    ''')[0]
    return {'duplicates': duplicates, 'tied_departures': ties,
            'time_fields': times, 'completed_flights': completed}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('input', type=Path)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    if args.input.resolve() == args.output.resolve():
        parser.error('Output must not overwrite input')
    report = audit(args.input)
    # Let DuckDB spill to a temporary folder during the wide duplicate check.
    with tempfile.TemporaryDirectory(prefix='flight-quality-') as temp:
        connection = duckdb.connect(config={'memory_limit': '1GB', 'temp_directory': temp})
        try:
            connection.read_parquet(str(args.input)).create_view('flights')
            report['quality'] = check_quality(connection)
        finally:
            connection.close()
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, indent=2, default=str) + '\n', encoding='utf-8')
    print(json.dumps({key: value for key, value in report['quality'].items()
                      if key != 'tied_departures'}, indent=2, default=str))
    print('Tied groups:', report['quality']['tied_departures']['groups'])
    print('Report:', args.output)


if __name__ == '__main__':
    main()
