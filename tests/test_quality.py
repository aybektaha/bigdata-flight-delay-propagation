"""Small examples for duplicate and clock checks."""

import unittest

import duckdb
import pyarrow as pa

from src.quality import check_quality


class QualityTests(unittest.TestCase):
    def test_duplicates_and_clock_boundaries(self):
        base = {
            'Tail_Number': 'TEST1', 'FlightDate': '2022-01-01',
            'CRSDepTime': 900, 'CRSArrTime': 1000,
            'Origin': 'AAA', 'Dest': 'BBB', 'Operating_Airline': 'XX',
            'Flight_Number_Operating_Airline': 1,
            'DepTime': 900.0, 'ArrTime': 1000.0,
            'DepDelay': 0.0, 'ArrDelay': 0.0,
            'Cancelled': False, 'Diverted': False
        }
        rows = []
        for i, time in enumerate([900.0, 900.0, 2400.0, 0.0, 1260.0,
                                  -1.0, 1230.5, None, float('inf'), float('nan')]):
            row = dict(base, __index_level_0__=i, DepTime=time)
            if i >= 2:
                row['Tail_Number'] = f'TEST{i}'
                row['Flight_Number_Operating_Airline'] = i
            rows.append(row)
        # Same clock and tail, but a different flight must not be dropped.
        rows.append(dict(base, __index_level_0__=10, Dest='CCC',
                         Flight_Number_Operating_Airline=99))
        # Cancelled flights do not enter the preliminary tie check.
        rows.append(dict(base, __index_level_0__=11, Tail_Number='TEST2',
                         Flight_Number_Operating_Airline=100, Cancelled=True))
        with duckdb.connect() as connection:
            connection.register('flights', pa.Table.from_pylist(rows))
            result = check_quality(connection)
        self.assertEqual(result['duplicates']['all_data_fields']['extra_rows'], 1)
        self.assertEqual(result['duplicates']['candidate_flight_key']['extra_rows'], 1)
        ties = result['tied_departures']
        self.assertEqual(ties['groups'], 1)
        self.assertEqual(ties['rows_in_groups'], 3)
        self.assertEqual(ties['different_destinations'], 1)
        self.assertEqual(len(ties['sample']), 3)
        clocks = result['time_fields']['DepTime']
        self.assertEqual(clocks['missing'], 1)
        self.assertEqual(clocks['invalid'], 5)
        self.assertEqual(clocks['valid_including_2400'], 6)
        self.assertEqual(clocks['midnight_2400'], 1)
        self.assertEqual(clocks['midnight_zero'], 1)
        self.assertEqual(result['completed_flights']['rows'], 11)
        self.assertEqual(result['completed_flights']['missing_departure_time'], 1)


if __name__ == '__main__':
    unittest.main()
