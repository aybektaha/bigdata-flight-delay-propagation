"""Load the same time-zone rules on each machine."""

from functools import lru_cache
from importlib import resources
from zoneinfo import ZoneInfo

import tzdata


@lru_cache(maxsize=None)
def load_zone(name):
    if tzdata.__version__ != '2025.2':
        raise RuntimeError('Install the versions in requirements-audit.txt')
    parts = name.split('/')
    if any(part in ('', '.', '..') for part in parts):
        raise ValueError('Invalid IANA zone name')
    package = '.'.join(['tzdata', 'zoneinfo'] + parts[:-1])
    with resources.open_binary(package, parts[-1]) as stream:
        return ZoneInfo.from_file(stream, key=name)


def timezone_version():
    return {'package': tzdata.__version__, 'iana': tzdata.IANA_VERSION,
            'source': 'tzdata package files; system time-zone files are not used'}
