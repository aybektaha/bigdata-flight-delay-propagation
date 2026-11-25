"""Check batch output, row preservation, and input safeguards."""

import json
import tempfile
import unittest
from pathlib import Path

import pyarrow as pa
import pyarrow.parquet as pq

from src.airport_zones import file_hash
from src.prepare_timestamps import prepare
from src.timezones import timezone_version
from src.validate_timestamps import validate


class PrepareTimestampTests(unittest.TestCase):
    def test_batches_preserve_rows_and_flag_failures(self):
        base = {'FlightDate': '2022-01-04', 'Tail_Number': 'TEST',
                'Origin': 'JFK', 'Dest': 'LAX', 'Cancelled': False, 'Diverted': False,
                'CRSDepTime': 730, 'CRSArrTime': 1104, 'DepTime': 727, 'ArrTime': 1051,
                'CRSElapsedTime': 394, 'ActualElapsedTime': 384, 'DepDelay': -3, 'ArrDelay': -13,
                'extra_source_field': 'keep me'}
        rows = [base, dict(base, Cancelled=True), dict(base, ArrTime=1100),
                dict(base, Tail_Number=None), dict(base, Origin='UNKNOWN')]
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            source = root / 'input.parquet'
            mapping = root / 'map.json'
            table = pa.Table.from_pylist(rows)
            pq.write_table(table, source)
            manifest = {'input': {'sha256': file_hash(source)}, 'timezone_data': timezone_version(),
                        'zones': {'JFK': 'America/New_York', 'LAX': 'America/Los_Angeles'}}
            mapping.write_text(json.dumps(manifest))
            report = prepare(source, mapping, root / 'output', batch_size=2)
            result = pq.read_table(root / 'output' / 'flights.parquet')
            self.assertTrue(result.select(table.column_names).equals(table))
            self.assertEqual(result['source_row_number'].to_pylist(), [0, 1, 2, 3, 4])
            self.assertEqual(result['timestamp_status'].to_pylist(),
                             ['consistent_candidate', 'excluded', 'clock_mismatch',
                              'consistent_candidate', 'unmapped_airport'])
            self.assertEqual(result['has_tail_number'].to_pylist(), [True, True, True, False, True])
            self.assertEqual(result['actual_arrival_utc'].null_count, 3)
            self.assertEqual(result.schema.field('actual_arrival_utc').type, pa.timestamp('us', tz='UTC'))
            self.assertEqual(sum(report['status_counts'].values()), 5)
            self.assertEqual(file_hash(source), manifest['input']['sha256'])
            self.assertTrue((root / 'output' / 'report.json').exists())
            self.assertFalse((root / 'output' / 'flights.partial.parquet').exists())
            self.assertEqual(validate(source, root / 'output')['validated_rows'], 5)
            with self.assertRaises(FileExistsError):
                prepare(source, mapping, root / 'output')
            manifest['input']['sha256'] = 'wrong'
            mapping.write_text(json.dumps(manifest))
            with self.assertRaises(ValueError):
                prepare(source, mapping, root / 'wrong-input')
            self.assertFalse((root / 'wrong-input').exists())
            pq.write_table(table.slice(0, 1), root / 'output' / 'flights.parquet')
            with self.assertRaises(ValueError):
                validate(source, root / 'output')


if __name__ == '__main__':
    unittest.main()
