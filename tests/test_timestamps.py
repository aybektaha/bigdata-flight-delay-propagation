"""Check time zones, midnight, and inconsistent flight records."""

import unittest
from datetime import datetime

import duckdb
import pyarrow as pa

from src.time_audit import time_checks
from src.timestamps import clock_minutes, reconstruct, utc_candidates
from src.timezones import load_zone


def flight(**changes):
    row = {
        'FlightDate': '2022-01-04', 'Tail_Number': 'TEST',
        'Origin': 'JFK', 'Dest': 'LAX', 'Operating_Airline': 'AA',
        'Flight_Number_Operating_Airline': 1,
        'Cancelled': False, 'Diverted': False,
        'CRSDepTime': 730, 'CRSArrTime': 1104, 'DepTime': 727, 'ArrTime': 1051,
        'CRSElapsedTime': 394, 'ActualElapsedTime': 384, 'DepDelay': -3, 'ArrDelay': -13
    }
    row.update(changes)
    return row


class TimestampTests(unittest.TestCase):
    zones = {'JFK': 'America/New_York', 'LAX': 'America/Los_Angeles'}

    def test_real_jfk_lax_example(self):
        result = reconstruct(flight(), self.zones)
        self.assertEqual(result['status'], 'consistent_candidate')
        self.assertEqual(result['scheduled_departure_utc'], '2022-01-04T12:30:00+00:00')
        self.assertEqual(result['actual_arrival_utc'], '2022-01-04T18:51:00+00:00')

    def test_overnight_and_multiday_delay(self):
        row = flight(Origin='AAA', Dest='BBB', CRSDepTime=2300, CRSArrTime=100,
                     DepTime=2400, ArrTime=200, CRSElapsedTime=120,
                     ActualElapsedTime=120, DepDelay=1500, ArrDelay=1500)
        result = reconstruct(row, {'AAA': 'UTC', 'BBB': 'UTC'})
        self.assertEqual(result['status'], 'consistent_candidate')
        self.assertEqual(result['scheduled_arrival_utc'], '2022-01-05T01:00:00+00:00')
        self.assertEqual(result['actual_departure_utc'], '2022-01-06T00:00:00+00:00')

    def test_scheduled_2400_and_early_departure(self):
        row = flight(Origin='AAA', Dest='BBB', CRSDepTime=2400, CRSArrTime=100,
                     DepTime=2350, ArrTime=50, CRSElapsedTime=60,
                     ActualElapsedTime=60, DepDelay=-10, ArrDelay=-10)
        result = reconstruct(row, {'AAA': 'UTC', 'BBB': 'UTC'})
        self.assertEqual(result['status'], 'consistent_candidate')
        self.assertEqual(result['scheduled_departure_utc'], '2022-01-05T00:00:00+00:00')
        self.assertEqual(result['actual_departure_utc'], '2022-01-04T23:50:00+00:00')

    def test_spring_dst_jump(self):
        row = flight(FlightDate='2022-03-13', Origin='AAA', Dest='BBB',
                     CRSDepTime=130, CRSArrTime=430, DepTime=330, ArrTime=530,
                     CRSElapsedTime=120, ActualElapsedTime=120, DepDelay=60, ArrDelay=60)
        zones = {'AAA': 'America/New_York', 'BBB': 'America/New_York'}
        self.assertEqual(reconstruct(row, zones)['status'], 'consistent_candidate')
        self.assertEqual(utc_candidates(datetime(2022, 3, 13, 2, 30),
                                        load_zone('America/New_York')), [])
        row.update(CRSDepTime=230)
        self.assertEqual(reconstruct(row, zones)['status'], 'nonexistent_local_departure')

    def test_fall_dst_ambiguity(self):
        row = flight(FlightDate='2022-11-06', Origin='AAA', Dest='BBB',
                     CRSDepTime=130, CRSArrTime=140, DepTime=130, ArrTime=140,
                     CRSElapsedTime=10, ActualElapsedTime=10, DepDelay=0, ArrDelay=0)
        result = reconstruct(row, {'AAA': 'America/New_York', 'BBB': 'America/New_York'})
        self.assertEqual(result['status'], 'ambiguous_local_departure')
        self.assertEqual(len(result['candidates']), 2)

    def test_real_delayed_flight_across_dst(self):
        row = flight(FlightDate='2022-03-12', Origin='ATL', Dest='TYS',
                     CRSDepTime=2248, CRSArrTime=2341, DepTime=409, ArrTime=454,
                     CRSElapsedTime=53, ActualElapsedTime=45, DepDelay=261, ArrDelay=253)
        result = reconstruct(row, {'ATL': 'America/New_York', 'TYS': 'America/New_York'})
        self.assertEqual(result['status'], 'consistent_candidate')
        self.assertEqual(result['actual_departure_utc'], '2022-03-13T08:09:00+00:00')

    def test_rejected_inputs(self):
        for changes, expected in [
            ({'Cancelled': True}, 'excluded'),
            ({'Origin': 'UNKNOWN'}, 'unmapped_airport'),
            ({'DepTime': 1260}, 'invalid_input'),
            ({'DepTime': None}, 'invalid_input'),
            ({'CRSElapsedTime': -48}, 'invalid_duration'),
            ({'ArrDelay': 0}, 'duration_delay_mismatch'),
            ({'ArrTime': 1100}, 'clock_mismatch')
        ]:
            with self.subTest(changes=changes):
                self.assertEqual(reconstruct(flight(**changes), self.zones)['status'], expected)
        with self.assertRaises(ValueError):
            clock_minutes(float('nan'))

    def test_sql_flags(self):
        rows = [flight(), flight(CRSElapsedTime=-48), flight(DepTime=728),
                flight(Cancelled=True, CRSElapsedTime=-48)]
        with duckdb.connect() as connection:
            connection.register('flights', pa.Table.from_pylist(rows))
            result = time_checks(connection)
        self.assertEqual(result['counts']['completed_rows'], 3)
        self.assertEqual(result['counts']['nonpositive_scheduled_duration'], 1)
        self.assertEqual(result['counts']['duration_delay_mismatch'], 1)
        self.assertEqual(result['counts']['naive_departure_mismatch'], 1)


if __name__ == '__main__':
    unittest.main()
