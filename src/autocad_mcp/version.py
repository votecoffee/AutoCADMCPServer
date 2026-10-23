"""Fixed release identity; timestamps are chosen once, never at application startup."""

import re
from datetime import datetime

DISPLAY_VERSION = "26.1023.072735"
VERSION_TIMEZONE = "America/New_York"
_TIMESTAMP = re.compile(r"([0-9]{1,2})\.([0-9]{1,4})\.([0-9]{1,6})\Z")


def display_timestamp_version(value: str) -> str:
    """Restore fixed-width YY.MMDD.HHmmss and reject invalid dates/times."""
    match = _TIMESTAMP.fullmatch(value)
    if not match:
        raise ValueError("Expected timestamp version YY.MMDD.HHmmss")
    year, day, clock = (int(part) for part in match.groups())
    datetime(2000 + year, day // 100, day % 100, clock // 10000, clock // 100 % 100, clock % 100)
    return f"{year:02d}.{day:04d}.{clock:06d}"


def canonical_timestamp_version(value: str) -> str:
    """PEP 440 and strict SemVer require numeric components without leading zeros."""
    return ".".join(str(int(part)) for part in display_timestamp_version(value).split("."))


PACKAGE_VERSION = canonical_timestamp_version(DISPLAY_VERSION)
