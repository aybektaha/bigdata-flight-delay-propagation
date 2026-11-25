"""Add checked UTC timestamps without dropping or changing source rows."""

import argparse
import json
import platform
import time
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path

import pyarrow as pa
import pyarrow.parquet as pq

from src.airport_zones import file_hash, load_mapping
from src.timestamps import reconstruct
from src.timezones import timezone_version


TIME_FIELDS = ['scheduled_departure_utc', 'scheduled_arrival_utc',
               'actual_departure_utc', 'actual_arrival_utc']
INPUT_FIELDS = ['FlightDate', 'Tail_Number', 'Origin', 'Dest', 'Cancelled', 'Diverted',
                'CRSDepTime', 'CRSArrTime', 'DepTime', 'ArrTime',
                'CRSElapsedTime', 'ActualElapsedTime', 'DepDelay', 'ArrDelay']


def prepare(input_path, mapping_path, output_dir, batch_size=50000):
    if batch_size <= 0:
        raise ValueError('Batch size must be positive')
    if output_dir.exists():
        raise FileExistsError('Choose a new output directory to keep earlier runs intact')
    zones = load_mapping(mapping_path)
    mapping = json.loads(mapping_path.read_text())
    input_hash = file_hash(input_path)
    if input_hash != mapping['input']['sha256']:
        raise ValueError('Input differs from the file reviewed for this airport map; rebuild the map first')
    source = pq.ParquetFile(input_path)
    missing = set(INPUT_FIELDS) - set(source.schema_arrow.names)
    if missing:
        raise ValueError(f'Missing input fields: {sorted(missing)}')
    extra_fields = [pa.field('source_row_number', pa.int64()),
                    pa.field('timestamp_status', pa.string()),
                    pa.field('timestamp_details', pa.string()),
                    pa.field('has_tail_number', pa.bool_())]
    extra_fields += [pa.field(name, pa.timestamp('us', tz='UTC')) for name in TIME_FIELDS]
    if set(source.schema_arrow.names) & {field.name for field in extra_fields}:
        raise ValueError('Input already contains output fields')
    schema = pa.schema(list(source.schema_arrow) + extra_fields)
    output_dir.mkdir(parents=True)
    partial_path = output_dir / 'flights.partial.parquet'
    final_path = output_dir / 'flights.parquet'
    counts = Counter()
    tail_counts = Counter()
    examples = defaultdict(list)
    offset = 0
    started = time.monotonic()
    with pq.ParquetWriter(partial_path, schema, compression='snappy') as writer:
        for batch in source.iter_batches(batch_size=batch_size):
            # Keep the source columns in Arrow; only inspect the fields we need.
            rows = batch.select(INPUT_FIELDS).to_pylist()
            statuses, details, has_tails = [], [], []
            utc_values = {name: [] for name in TIME_FIELDS}
            for index, row in enumerate(rows):
                result = reconstruct(row, zones)
                status = result['status']
                has_tail = bool(row['Tail_Number'] and row['Tail_Number'].strip())
                counts[status] += 1
                tail_counts[f'{status}|tail={has_tail}'] += 1
                statuses.append(status)
                has_tails.append(has_tail)
                details.append(None if status == 'consistent_candidate' else
                               json.dumps({key: value for key, value in result.items() if key != 'status'}))
                for name in TIME_FIELDS:
                    utc_values[name].append(datetime.fromisoformat(result[name])
                                            if status == 'consistent_candidate' else None)
                if status != 'consistent_candidate' and len(examples[status]) < 5:
                    examples[status].append({'source_row_number': offset + index,
                                             'input': row, 'result': result})
            arrays = list(batch.columns)
            arrays += [pa.array(range(offset, offset + len(rows)), type=pa.int64()),
                       pa.array(statuses), pa.array(details, type=pa.string()), pa.array(has_tails)]
            arrays += [pa.array(utc_values[name], type=pa.timestamp('us', tz='UTC')) for name in TIME_FIELDS]
            writer.write_batch(pa.RecordBatch.from_arrays(arrays, schema=schema))
            offset += len(rows)
            print(f'Processed {offset:,} / {source.metadata.num_rows:,} rows', flush=True)
    if offset != source.metadata.num_rows:
        raise RuntimeError('Output row count does not match input')
    if file_hash(input_path) != input_hash:
        raise RuntimeError('Input changed during processing')
    partial_path.rename(final_path)
    report = {
        'completed_at_utc': datetime.now(timezone.utc).isoformat(),
        'input': {'filename': input_path.name, 'sha256': input_hash, 'rows': offset},
        'airport_map_sha256': file_hash(mapping_path), 'timezone_data': timezone_version(),
        'environment': {'python': platform.python_version(), 'pyarrow': pa.__version__},
        'code_sha256': {name: file_hash(Path(__file__).with_name(name)) for name in
                        ['prepare_timestamps.py', 'timestamps.py', 'timezones.py', 'airport_zones.py']},
        'batch_size': batch_size, 'elapsed_seconds': round(time.monotonic() - started, 3),
        'status_counts': dict(sorted(counts.items())),
        'status_tail_counts': dict(sorted(tail_counts.items())),
        'flagged_examples': dict(examples),
        'output': {'filename': final_path.name, 'rows': offset,
                   'sha256': file_hash(final_path), 'bytes': final_path.stat().st_size},
        'note': 'One output row per input row. UTC columns are null unless status is '
                'consistent_candidate. This is not a validated flight sequence.'
    }
    # The report marks a completed run; partial files alone do not.
    (output_dir / 'report.json').write_text(json.dumps(report, indent=2, default=str) + '\n')
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('input', type=Path)
    parser.add_argument('--airport-map', type=Path, required=True)
    parser.add_argument('--output-dir', type=Path, required=True)
    parser.add_argument('--batch-size', type=int, default=50000)
    args = parser.parse_args()
    report = prepare(args.input, args.airport_map, args.output_dir, args.batch_size)
    print(json.dumps(report['status_counts'], indent=2))
    print('Output directory:', args.output_dir)


if __name__ == '__main__':
    main()
