"""Verify a timestamp run against its source file and saved report."""

import argparse
import json
from itertools import zip_longest
from pathlib import Path

import duckdb
import pyarrow as pa
import pyarrow.parquet as pq

from src.airport_zones import file_hash
from src.prepare_timestamps import TIME_FIELDS


def validate(input_path, output_dir):
    report = json.loads((output_dir / 'report.json').read_text())
    output_path = output_dir / report['output']['filename']
    if file_hash(input_path) != report['input']['sha256']:
        raise ValueError('Source file hash changed')
    if file_hash(output_path) != report['output']['sha256']:
        raise ValueError('Output file hash changed')
    source = pq.ParquetFile(input_path)
    output = pq.ParquetFile(output_path)
    if not (source.metadata.num_rows == output.metadata.num_rows == report['output']['rows']
            == report['input']['rows']):
        raise ValueError('Row counts do not match')
    offset = 0
    for original, prepared in zip_longest(source.iter_batches(batch_size=50000),
                                         output.iter_batches(batch_size=50000)):
        if original is None or prepared is None:
            raise ValueError('Batch counts do not match')
        if not original.equals(prepared.select(source.schema_arrow.names)):
            raise ValueError(f'Source values changed near row {offset}')
        expected_ids = pa.array(range(offset, offset + original.num_rows), type=pa.int64())
        if not prepared.column('source_row_number').equals(expected_ids):
            raise ValueError('Source row numbers do not match')
        offset += original.num_rows
    for field in TIME_FIELDS:
        if output.schema_arrow.field(field).type != pa.timestamp('us', tz='UTC'):
            raise ValueError(f'Wrong timestamp type: {field}')
    with duckdb.connect() as connection:
        connection.read_parquet(str(output_path)).create_view('prepared')
        counts = dict(connection.execute('''
            SELECT timestamp_status, count(*) FROM prepared GROUP BY timestamp_status
        ''').fetchall())
        if counts != report['status_counts']:
            raise ValueError('Status counts differ from the report')
        nonnull = ' AND '.join(f'{field} IS NOT NULL' for field in TIME_FIELDS)
        any_nonnull = ' OR '.join(f'{field} IS NOT NULL' for field in TIME_FIELDS)
        null_errors = connection.execute(f'''
            SELECT count(*) FROM prepared
            WHERE (timestamp_status = 'consistent_candidate' AND NOT ({nonnull}))
               OR (timestamp_status <> 'consistent_candidate' AND ({any_nonnull}))
        ''').fetchone()[0]
        arithmetic_errors = connection.execute('''
            SELECT count(*) FROM prepared WHERE timestamp_status = 'consistent_candidate' AND (
                date_diff('minute', scheduled_departure_utc, actual_departure_utc) <> DepDelay OR
                date_diff('minute', scheduled_departure_utc, scheduled_arrival_utc) <> CRSElapsedTime OR
                date_diff('minute', actual_departure_utc, actual_arrival_utc) <> ActualElapsedTime OR
                date_diff('minute', scheduled_arrival_utc, actual_arrival_utc) <> ArrDelay)
        ''').fetchone()[0]
        if null_errors or arithmetic_errors:
            raise ValueError(f'UTC validation failed: nulls={null_errors}, arithmetic={arithmetic_errors}')
    return {'validated_rows': offset, 'source_values_unchanged': True,
            'source_row_numbers_valid': True, 'utc_nullability_errors': null_errors,
            'utc_arithmetic_errors': arithmetic_errors, 'status_counts': counts}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('input', type=Path)
    parser.add_argument('--output-dir', type=Path, required=True)
    args = parser.parse_args()
    print(json.dumps(validate(args.input, args.output_dir), indent=2))


if __name__ == '__main__':
    main()
