"""Build candidate UTC timestamps and check them against reported clocks."""

import math
from datetime import date, datetime, time, timedelta, timezone
from src.timezones import load_zone


def whole_minutes(value, name):
    if value is None or not math.isfinite(value) or value != int(value):
        raise ValueError(f'{name} must be a finite whole number')
    return int(value)


def clock_minutes(value):
    value = whole_minutes(value, 'clock')
    if value == 2400:
        return 1440
    hour, minute = divmod(value, 100)
    if not (0 <= hour < 24 and 0 <= minute < 60):
        raise ValueError('invalid HHMM clock')
    return hour * 60 + minute


def utc_candidates(local_time, zone):
    # A clock can occur twice, or not at all, during a DST change.
    candidates = set()
    for fold in (0, 1):
        utc_time = local_time.replace(tzinfo=zone, fold=fold).astimezone(timezone.utc)
        if utc_time.astimezone(zone).replace(tzinfo=None) == local_time:
            candidates.add(utc_time)
    return sorted(candidates)


def reconstruct(row, airport_zones):
    if row['Cancelled'] or row['Diverted']:
        return {'status': 'excluded', 'reason': 'cancelled_or_diverted'}
    missing = sorted(airport for airport in {row['Origin'], row['Dest']}
                     if airport not in airport_zones)
    if missing:
        return {'status': 'unmapped_airport', 'airports': missing}
    origin_zone = load_zone(airport_zones[row['Origin']])
    destination_zone = load_zone(airport_zones[row['Dest']])
    try:
        clocks = {name: clock_minutes(row[name]) for name in
                  ['CRSDepTime', 'CRSArrTime', 'DepTime', 'ArrTime']}
        values = {name: whole_minutes(row[name], name) for name in
                  ['CRSElapsedTime', 'ActualElapsedTime', 'DepDelay', 'ArrDelay']}
        flight_date = date.fromisoformat(str(row['FlightDate'])[:10])
    except (ValueError, TypeError) as error:
        return {'status': 'invalid_input', 'reason': str(error)}
    if values['CRSElapsedTime'] <= 0 or values['ActualElapsedTime'] <= 0:
        return {'status': 'invalid_duration'}
    residual = (values['ArrDelay'] - values['DepDelay']
                - values['ActualElapsedTime'] + values['CRSElapsedTime'])
    if residual != 0:
        return {'status': 'duration_delay_mismatch', 'residual_minutes': residual}

    local_departure = datetime.combine(flight_date, time()) + timedelta(minutes=clocks['CRSDepTime'])
    starts = utc_candidates(local_departure, origin_zone)
    if not starts:
        return {'status': 'nonexistent_local_departure'}
    accepted = []
    rejected = []
    for scheduled_departure in starts:
        scheduled_arrival = scheduled_departure + timedelta(minutes=values['CRSElapsedTime'])
        actual_departure = scheduled_departure + timedelta(minutes=values['DepDelay'])
        actual_arrival = actual_departure + timedelta(minutes=values['ActualElapsedTime'])
        checks = [('CRSArrTime', scheduled_arrival, destination_zone),
                  ('DepTime', actual_departure, origin_zone),
                  ('ArrTime', actual_arrival, destination_zone)]
        mismatches = []
        for field, instant, zone in checks:
            local = instant.astimezone(zone)
            if local.hour * 60 + local.minute != clocks[field] % 1440:
                mismatches.append(field)
        timestamps = {
            'scheduled_departure_utc': scheduled_departure.isoformat(),
            'scheduled_arrival_utc': scheduled_arrival.isoformat(),
            'actual_departure_utc': actual_departure.isoformat(),
            'actual_arrival_utc': actual_arrival.isoformat()
        }
        if mismatches:
            rejected.append({'scheduled_departure_utc': scheduled_departure.isoformat(),
                             'mismatched_fields': mismatches})
        else:
            accepted.append(timestamps)
    if not accepted:
        return {'status': 'clock_mismatch', 'rejected_candidates': rejected}
    if len(accepted) > 1:
        return {'status': 'ambiguous_local_departure', 'candidates': accepted}
    return {'status': 'consistent_candidate', **accepted[0]}
