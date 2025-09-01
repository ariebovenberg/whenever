import os
from contextlib import contextmanager
from pathlib import Path
from typing import Literal
from unittest.mock import patch

from whenever import PlainDateTime, ZonedDateTime, reset_system_tz

# The POSIX TZ string for the Amsterdam timezone.
AMS_TZ_POSIX = "CET-1CEST,M3.5.0,M10.5.0/3"
# A non-standard path to the Amsterdam timezone file, that can't be traced
# back to the zoneinfo database.
AMS_TZ_RAWFILE = str(Path(__file__).parent / "tzif" / "Amsterdam.tzif")


class AlwaysEqual:
    def __eq__(self, _):
        return True


class NeverEqual:
    def __eq__(self, _):
        return False


class AlwaysLarger:
    def __lt__(self, _):
        return False

    def __le__(self, _):
        return False

    def __gt__(self, _):
        return True

    def __ge__(self, _):
        return True


class AlwaysSmaller:
    def __lt__(self, _):
        return True

    def __le__(self, _):
        return True

    def __gt__(self, _):
        return False

    def __ge__(self, _):
        return False


@contextmanager
def system_tz_ams():
    try:
        with patch.dict(os.environ, {"TZ": "Europe/Amsterdam"}):
            reset_system_tz()
            yield
    finally:
        reset_system_tz()  # don't forget to reset the timezone after the patch!


@contextmanager
def system_tz(name):
    try:
        with patch.dict(os.environ, {"TZ": name}):
            reset_system_tz()
            yield
    finally:
        reset_system_tz()  # don't forget to reset the timezone after the patch!


@contextmanager
def system_tz_nyc():
    try:
        with patch.dict(os.environ, {"TZ": "America/New_York"}):
            reset_system_tz()
            yield
    finally:
        reset_system_tz()  # don't forget to reset the timezone after the patch!


with system_tz(AMS_TZ_POSIX):
    _AMS_POSIX_DT = PlainDateTime(2023, 3, 26, 2, 30).assume_system_tz()

with system_tz(AMS_TZ_RAWFILE):
    _AMS_RAWFILE_DT = PlainDateTime(2023, 3, 26, 2, 30).assume_system_tz()


# TODO: we can do this without patching every single time
def create_zdt(
    year: int,
    month: int,
    day: int,
    hour: int = 0,
    minute: int = 0,
    second: int = 0,
    nanosecond: int = 0,
    *,
    tz: str = "",
    disambiguate: Literal[
        "compatible", "earlier", "later", "raise"
    ] = "compatible",
) -> ZonedDateTime:
    """Convenience method to create a ZonedDateTime object, potentially
    with system timezone."""
    # A special check that is only useful in tests of course
    if tz == AMS_TZ_POSIX:
        return _AMS_POSIX_DT.replace(
            year=year,
            month=month,
            day=day,
            hour=hour,
            minute=minute,
            second=second,
            nanosecond=nanosecond,
            disambiguate=disambiguate,
        )
    elif tz == AMS_TZ_RAWFILE:
        return _AMS_RAWFILE_DT.replace(
            year=year,
            month=month,
            day=day,
            hour=hour,
            minute=minute,
            second=second,
            nanosecond=nanosecond,
            disambiguate=disambiguate,
        )
    else:
        return ZonedDateTime(
            year,
            month,
            day,
            hour,
            minute,
            second,
            nanosecond=nanosecond,
            tz=tz,
            disambiguate=disambiguate,
        )
