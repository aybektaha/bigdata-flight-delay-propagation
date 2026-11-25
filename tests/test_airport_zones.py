"""Check explicit airport matches and historical-code overrides."""

import unittest

from src.airport_zones import build_mapping
from src.timezones import load_zone, timezone_version


class AirportZoneTests(unittest.TestCase):
    def test_direct_match_and_override(self):
        rows = [{'iata': 'JFK', 'tz': 'America/New_York'},
                {'iata': 'DJT', 'tz': 'America/New_York'}]
        overrides = {'PBI': {'source_iata': 'DJT', 'expected_bts_airport_ids': [14027]}}
        zones, applied = build_mapping({'JFK': {12478}, 'PBI': {14027}}, rows, overrides)
        self.assertEqual(zones, {'JFK': 'America/New_York', 'PBI': 'America/New_York'})
        self.assertEqual(set(applied), {'PBI'})

    def test_missing_and_duplicate_matches_fail(self):
        for rows in [[], [{'iata': 'JFK', 'tz': 'America/New_York'}] * 2]:
            with self.subTest(rows=rows), self.assertRaises(ValueError):
                build_mapping({'JFK': {12478}}, rows, {})

    def test_override_requires_expected_airport_id(self):
        rows = [{'iata': 'DJT', 'tz': 'America/New_York'}]
        override = {'PBI': {'source_iata': 'DJT', 'expected_bts_airport_ids': [14027]}}
        with self.assertRaises(ValueError):
            build_mapping({'PBI': {99999}}, rows, override)

    def test_pinned_zone_loader(self):
        self.assertEqual(timezone_version()['package'], '2025.2')
        self.assertEqual(load_zone('America/New_York').key, 'America/New_York')
        self.assertIs(load_zone('America/New_York'), load_zone('America/New_York'))
        with self.assertRaises(ValueError):
            load_zone('../UTC')


if __name__ == '__main__':
    unittest.main()
