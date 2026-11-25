"""Read-only Parquet audit. Run with python -m src.audit INPUT --output OUTPUT."""

import argparse
import hashlib
import json
import platform
from datetime import datetime, timezone
from pathlib import Path

import duckdb
import pyarrow
import pyarrow.parquet as pq


def audit(path):
    parquet = pq.ParquetFile(path)
    digest = hashlib.sha256()
    with path.open('rb') as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b''):
            digest.update(chunk)
    connection = duckdb.connect()
    try:
        connection.read_parquet(str(path)).create_view('flights')
        summary = connection.execute('''
            SELECT count(*) AS rows, min(FlightDate) AS first_date,
                max(FlightDate) AS last_date,
                count(*) FILTER (WHERE Tail_Number IS NULL OR trim(Tail_Number) = '') AS missing_tail,
                count(*) FILTER (WHERE Cancelled) AS cancelled,
                count(*) FILTER (WHERE Diverted) AS diverted
            FROM flights
        ''')
        counts = dict(zip([c[0] for c in summary.description], summary.fetchone()))
        nulls = {}
        for name in parquet.schema_arrow.names:
            identifier = '"' + name.replace('"', '""') + '"'
            nulls[name] = connection.execute(
                f'SELECT count(*) FROM flights WHERE {identifier} IS NULL'
            ).fetchone()[0]
        months = connection.execute('''
            SELECT Year, Month, count(*) FROM flights
            GROUP BY Year, Month ORDER BY Year, Month
        ''').fetchall()
        ties = connection.execute('''
            SELECT count(*), coalesce(sum(n - 1), 0) FROM (
                SELECT count(*) AS n FROM flights
                WHERE NOT Cancelled AND NOT Diverted
                    AND Tail_Number IS NOT NULL AND trim(Tail_Number) <> ''
                GROUP BY Tail_Number, FlightDate, CRSDepTime HAVING count(*) > 1
            )
        ''').fetchone()
        pairs, matches = connection.execute('''
            WITH ordered AS (
                SELECT FlightDate, Dest,
                    lead(Origin) OVER w AS next_origin,
                    lead(FlightDate) OVER w AS next_date
                FROM flights WHERE NOT Cancelled AND NOT Diverted
                    AND Tail_Number IS NOT NULL AND trim(Tail_Number) <> ''
                WINDOW w AS (PARTITION BY Tail_Number ORDER BY FlightDate, CRSDepTime)
            )
            SELECT count(*), count(*) FILTER (WHERE Dest = next_origin)
            FROM ordered WHERE FlightDate = next_date
        ''').fetchone()
        return {
            'generated_at_utc': datetime.now(timezone.utc).isoformat(),
            'input': str(path), 'bytes': path.stat().st_size,
            'sha256': digest.hexdigest(),
            'environment': {'python': platform.python_version(), 'duckdb': duckdb.__version__,
                            'pyarrow': pyarrow.__version__},
            'counts': counts, 'physical_columns': parquet.metadata.num_columns,
            'row_groups': parquet.metadata.num_row_groups,
            'schema': [{'name': field.name, 'type': str(field.type)} for field in parquet.schema_arrow],
            'null_counts': nulls,
            'monthly_counts': [{'year': y, 'month': m, 'rows': n} for y, m, n in months],
            'preliminary_same_day_continuity': {
                'pairs': pairs, 'matching_pairs': matches,
                'percent': 100 * matches / pairs if pairs else None,
                'tied_ordering_groups': ties[0], 'excess_rows_in_tied_groups': ties[1],
                'method': 'Exclude cancelled/diverted and missing/blank tails; partition by tail; '
                          'order by FlightDate, CRSDepTime; retain same-date consecutive pairs.',
                'limitations': 'Preliminary heuristic, not validated rotations. Tied ordering is '
                               'ambiguous. Filtering before pairing can bridge excluded flights. '
                               'No UTC conversion, overnight linking or ground-time validation.'
            }
        }
    finally:
        connection.close()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('input', type=Path)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    if args.input.resolve() == args.output.resolve():
        parser.error('Output must not overwrite input')
    result = audit(args.input)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, indent=2, default=str) + '\n', encoding='utf-8')
    print(json.dumps({'counts': result['counts'],
                      'continuity': result['preliminary_same_day_continuity']}, indent=2, default=str))


if __name__ == '__main__':
    main()
