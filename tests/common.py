import os
import shutil
import warnings
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import datetime as py_datetime, timezone as py_timezone
from pathlib import Path
from sys import _getframe
from typing import Literal
from unittest.mock import patch

import pytest
from whenever import (
    MONDAY,
    SYSTEM_TZ,
    Date,
    Instant,
    IsoWeekDate,
    ItemizedDateDelta,
    ItemizedDelta,
    MonthDay,
    OffsetDateTime,
    PlainDateTime,
    Time,
    TimeDelta,
    YearMonth,
    ZonedDateTime,
    clear_tzcache,
    get_tzpath,
    hours,
    minutes,
    reset_system_tz,
    reset_tzpath,
    seconds,
)

# The first integer that no longer fits a signed 64-bit machine word
MAX_I64 = 1 << 63

INVALID_DDELTAS = [
    "P3D7Y",  # components out of order
    "P3M7Y",  # components out of order
    "P\U0001d7d9Y",  # non-ASCII
    "P--2D",
    "P++2D",
    "P+-2D",
    "--P2D",
    "++P2D",
    "1P2",
    f"P{MAX_I64 + 2}Y",
    f"P-{MAX_I64 + 2}Y",
    "P3R",  # invalid unit
    "PT3M",  # time component
    "P3.4Y",  # decimal
    "P1,5D",  # comma
    "P1Y2M3W4DT1H2M3S",  # time component
    "P1YT0S",  # zero time component still invalid
    "P99999Y",  # too large
    # incomplete
    "",
    "P",  # no components
    "P34m4",
    "P34",
    "P-D",
    "P+D",
    "P-",
    "P+",
    "Y",
    "5Y",
    "-5Y",
    "P8",
    "P8M3",
]


@contextmanager
def warns_here(warning_class, *, match=None):
    """Like ``pytest.warns``, but also assert the warning points at this very
    ``with`` block instead of at whenever's own internals.

    ``pytest.warns`` matches only the category and the message, so it happily
    accepts a warning whose ``stacklevel`` is off—even though the file and line
    are the only part a user actually sees. Use this wherever the call site
    attribution matters, i.e. nearly everywhere::

        with warns_here(ImplicitDisambiguationWarning):
            ZonedDateTime(2023, 10, 29, 2, 30, tz="Europe/Amsterdam")

    Must be used directly in a test function: 2 frames up is this generator,
    then contextlib's __enter__, then the caller.
    """
    caller_file = _getframe(2).f_code.co_filename
    with pytest.warns(warning_class, match=match) as caught:
        yield caught
    for w in caught:
        assert w.filename == caller_file, (
            f"{warning_class.__name__} has a wrong stacklevel: it points at "
            f"{w.filename}:{w.lineno}, not at the caller in {caller_file}"
        )


@contextmanager
def suppress(*warning_classes):
    """Suppress specific warning classes in a block.

    Usage::

        with suppress(StaleOffsetWarning):
            ...

    Can also be used as a decorator::

        @suppress(StaleOffsetWarning)
        def test_something():
            ...
    """
    with warnings.catch_warnings():
        for cls in warning_classes:
            warnings.simplefilter("ignore", cls)
        yield


# The POSIX TZ string for the Amsterdam time zone.
AMS_TZ_POSIX = "CET-1CEST,M3.5.0,M10.5.0/3"
# A non-standard path to the Amsterdam time zone file, that can't be traced
# back to the zoneinfo database.
AMS_TZ_RAWFILE = str(Path(__file__).parent / "tzif" / "Amsterdam.tzif")
# The same file, with the 2020 DST end moved from October 25 to November 1
# (transition epoch 1603587600 -> 1604192400, rewritten in both the v1 and the
# v2 block). Nothing else differs, so the two definitions agree on every
# instant outside that week.
AMS_TZ_RAWFILE_DST_LATE = str(
    Path(__file__).parent / "tzif" / "Amsterdam_dst_ends_a_week_late.tzif"
)


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


class Idx:
    """An integer-like object: what CPython's own parser accepts for a field."""

    def __index__(self):
        return 5


class DatetimeSubclass(py_datetime):
    pass


class StrSubclass(str):
    pass


def ymdhms(
    year: int,
    month: int,
    day: int,
    hour: int = 0,
    minute: int = 0,
    second: int = 0,
) -> int:
    """The Unix timestamp of a UTC wall time."""
    return int(
        py_datetime(
            year, month, day, hour, minute, second, tzinfo=py_timezone.utc
        ).timestamp()
    )


def hhmm(hours: int, minutes: int = 0) -> int:
    """An offset in seconds."""
    return hours * 3600 + minutes * 60


@contextmanager
def system_tz(name):
    try:
        with patch.dict(os.environ, {"TZ": name}):
            reset_system_tz()
            yield
    finally:
        reset_system_tz()  # don't forget to reset the time zone after the patch!


@contextmanager
def tz_rules_from_file(tz_id: str, path: str, tmp_dir: Path) -> Iterator[None]:
    """Serve ``path`` as the rules for ``tz_id`` until the block exits.

    The file is copied under ``tz_id`` into ``tmp_dir``, which becomes the
    only entry of the time zone search path; the cache is cleared on entry
    and on exit so lookups before and after the block see their own rules.
    """
    zone = tmp_dir / tz_id
    zone.parent.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(path, zone)

    previous = get_tzpath()
    reset_tzpath([tmp_dir])
    clear_tzcache()
    try:
        yield
    finally:
        clear_tzcache()
        reset_tzpath(previous)


with system_tz(AMS_TZ_POSIX):
    _AMS_POSIX_DT = PlainDateTime(2023, 3, 26, 2, 30).assume_tz(
        SYSTEM_TZ, disambiguation="compatible"
    )

with system_tz(AMS_TZ_RAWFILE):
    _AMS_RAWFILE_DT = PlainDateTime(2023, 3, 26, 2, 30).assume_tz(
        SYSTEM_TZ, disambiguation="compatible"
    )


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
    disambiguation: Literal[
        "compatible", "earlier", "later", "raise"
    ] = "compatible",
) -> ZonedDateTime:
    """Convenience method to create a ZonedDateTime object, potentially
    with system time zone."""
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
            disambiguation=disambiguation,
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
            disambiguation=disambiguation,
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
            disambiguation=disambiguation,
        )


# One instance per public value type, in the order of the API reference.
SAMPLE_VALUES = [
    Date(2020, 1, 1),
    YearMonth(2020, 1),
    MonthDay(1, 1),
    IsoWeekDate(2020, 1, MONDAY),
    Time(),
    Instant.from_utc(2020, 1, 1),
    OffsetDateTime(2020, 1, 1, offset=hours(1)),
    ZonedDateTime(2020, 1, 1, tz="Europe/Amsterdam"),
    PlainDateTime(2020, 1, 1),
    TimeDelta(hours=1),
    ItemizedDelta(months=1),
    ItemizedDateDelta(months=1),
]
ALL_TYPES = [type(v) for v in SAMPLE_VALUES]


def type_name(value: object) -> str:
    """A parametrize ID for a value: its type."""
    return type(value).__name__


INVALID_ISO_STRINGS = [
    # padding issues
    "2020-08-15T2:08:30+05:00:01",
    "2020-8-15T12:8:30+05:00",
    # fraction issues
    "2020-08-15T12:08:30.0000000001+05:00",
    "2020-08-15T12:08:30.+05:00",
    "2020-08-15T12:08:30+05:00:21.0",
    "2020-08-15T12:08:30+05:00:21.",
    # separators
    "2020-08-15T12:08.30+05:00",
    "2020-08-15T12:08.30+05.00",
    "2020-08-15T12:08.30+05 00",
    # invalid offset
    "2020-08-15T12:08:30+24:00",
    "2020-08-15T12:08:30-24:00",
    "2020-08-15T12:08:30+09:80",
    "2020-08-15T12:08:30-09:30:60",
    "2020-08-15T12:08:30-99:00",
    "2020-08-15T12:08:30+ 1:23",
    "2020-08-15T12:08:30+01:+3",
    "2020-08-15T12:08:30+-1:23",
    # other
    "2020-08-15T12:08:30+05:00stuff",  # trailing stuff
    "2020-08-15T12:𝟘8:30+00:00",  # non-ASCII
    "2020-08-15T12:08:30.0034+05:𝟙0",  # non-ASCII
    "2020-08-15T12:08:30[Iceland]",  # time zone ID but no offset
    # not enough content
    "",
    "T",
    "2020",
    "2020-08-15",
    "2020-08-15T",
    "20200815XXT12:30+01:00",  # junk after a basic-format date
    "garbage",
    # out-of-bounds
    "9999-12-31T22:08:30-05:00",
    "0001-01-01 02:08:30+05:00",
    # invalid time zone ID format
    "2020-08-15T12:08:30+05:00[",
    "2020-08-15T12:08:30+05:00[[]",
    "2020-08-15T12:08:30+05:00[sdf[]",
    "2020-08-15T12:08:30+05:00[]",
    "2020-08-15T12:08:30+05:00]",
    "2020-08-15T12:08:30+05:00[abc]foo",
    # unsupported ISO features (weekdays, ordinal dates)
    "2020-W08-1T23:12:09-01",
    "2020-123T23:12:09-01",
    # invalid seconds (61 and above should be rejected)
    "2020-08-15T12:34:61+00:00",
    "2020-08-15T12:34:99+00:00",
    # basic-format time is HH/HHMM/HHMMSS, not a separatorless fraction
    "2020-08-15T12083000+05:00",
    "2020-08-15T120830123+05:00",
    "2020-08-15T120830.+05:00",
]

VALID_ISO_STRINGS = [
    (
        "2020-08-15T12:08:30+05:00",
        OffsetDateTime(2020, 8, 15, 12, 8, 30, offset=hours(5)),
    ),
    (
        "2020-08-15 12:08:30+05:00",  # space separator
        OffsetDateTime(2020, 8, 15, 12, 8, 30, offset=hours(5)),
    ),
    (
        "2020-08-15T12:08:30+20:00",
        OffsetDateTime(2020, 8, 15, 12, 8, 30, offset=hours(20)),
    ),
    (
        "2020-08-15T12:08:30.0034+05:00",
        OffsetDateTime(
            2020,
            8,
            15,
            12,
            8,
            30,
            nanosecond=3_400_000,
            offset=hours(5),
        ),
    ),
    (
        "2020-08-15T12:08:30.000000010+05:00",
        OffsetDateTime(2020, 8, 15, 12, 8, 30, nanosecond=10, offset=hours(5)),
    ),
    (
        "2020-08-15T12:08:30.0034-05:00:01",
        OffsetDateTime(
            2020,
            8,
            15,
            12,
            8,
            30,
            nanosecond=3_400_000,
            offset=-hours(5) - seconds(1),
        ),
    ),
    (
        "2020-08-15T12:08:30+00:00",
        OffsetDateTime(2020, 8, 15, 12, 8, 30, offset=hours(0)),
    ),
    (
        "2020-08-15T12:08:30-00:00",
        OffsetDateTime(2020, 8, 15, 12, 8, 30, offset=hours(0)),
    ),
    (
        "2020-08-15T12:08:30Z",
        OffsetDateTime(2020, 8, 15, 12, 8, 30, offset=hours(0)),
    ),
    (
        "2020-08-15T12:08:30z",
        OffsetDateTime(2020, 8, 15, 12, 8, 30, offset=hours(0)),
    ),
    # Shorter and alternative time formats
    (
        "1924-12-02T12+00",
        OffsetDateTime(1924, 12, 2, 12, offset=hours(0)),
    ),
    (
        "1924-12-02T12+01:00",
        OffsetDateTime(1924, 12, 2, 12, offset=hours(1)),
    ),
    (
        "19241203t12:00:12+003059",
        OffsetDateTime(
            1924,
            12,
            3,
            12,
            0,
            12,
            offset=minutes(30) + seconds(59),
        ),
    ),
    (
        "1924-08-15T120012-0030",
        OffsetDateTime(1924, 8, 15, 12, 0, 12, offset=minutes(-30)),
    ),
    (
        "2020-08-15T120012-0030[Foo]",
        OffsetDateTime(2020, 8, 15, 12, 0, 12, offset=minutes(-30)),
    ),
    # Decimals
    (
        "2020-08-15T120012,3-00:30[Foo]",
        OffsetDateTime(
            2020, 8, 15, 12, 0, 12, nanosecond=300_000_000, offset=minutes(-30)
        ),
    ),
    (
        "2020-08-15T120012.3112-00:30[Foo]",
        OffsetDateTime(
            2020, 8, 15, 12, 0, 12, nanosecond=311_200_000, offset=minutes(-30)
        ),
    ),
    # Leap second (60) should be parsed and normalized to 59
    (
        "2020-08-15T05:12:60+05:00",
        OffsetDateTime(2020, 8, 15, 5, 12, 59, offset=hours(5)),
    ),
    (
        "2020-08-15T05:12:60.123456+05:00",
        OffsetDateTime(
            2020,
            8,
            15,
            5,
            12,
            59,
            nanosecond=123_456_000,
            offset=hours(5),
        ),
    ),
    # Leap second with basic format
    (
        "20200815T051260+0500",
        OffsetDateTime(2020, 8, 15, 5, 12, 59, offset=hours(5)),
    ),
    # Leap second with negative offset
    (
        "2020-08-15T23:59:60-08:00",
        OffsetDateTime(2020, 8, 15, 23, 59, 59, offset=hours(-8)),
    ),
    # Leap second with fractional seconds and various offsets
    (
        "2020-08-15T12:34:60.5+00:00",
        OffsetDateTime(
            2020,
            8,
            15,
            12,
            34,
            59,
            nanosecond=500_000_000,
            offset=hours(0),
        ),
    ),
    # Leap second with comma as decimal separator
    (
        "2020-08-15T12:34:60,5+00:00",
        OffsetDateTime(
            2020,
            8,
            15,
            12,
            34,
            59,
            nanosecond=500_000_000,
            offset=hours(0),
        ),
    ),
]


INVALID_TDELTAS = [
    "P1D",  # calendar units
    "P1W",  # calendar units
    "P0D",  # zero, but still a calendar unit
    "P1YT4M",  # calendar units
    "T1H",  # wrong prefix
    "PT4M3H",  # wrong order
    "PT1.5H",  # fractional hours
    "PT1H2M3.000004S9H",  # stuff after nanoseconds
    "PT1H2M3.000004S ",  # stuff after nanoseconds
    "PT34.S",  # missing fractions
    "PTS",  # no digits
    "PT4HS",  # no digits
    "PT-3M",  # sign not at the beginning
    "PT5H.9S",  # wrong fraction
    "PT5H13.S",  # wrong fraction
    "PT𝟙H",  # non-ascii
    "PT0.0001",
    "PT.0001",
    "PT.S",
    "PT0.0000",
    "PT0.123456789",
    "PT0.123456789Sbla",
    "PT4M0.",
    "PT4M0.S",
    # spacing
    "PT 3M",
    "PT-3M",
    "PT3 M",
    "PT3M4 S",
    "PTH0S",  # missing hour value
    "PT48HM4S",  # missing minute value
    # too precise
    "PT1.0000000001S",
    # too small
    "",
    "P",
    "PTM",
    # way too many digits (there's a limit...)
    "PT000000000000000000000000000000000000000000000000000000000001S",
    # intermediate arithmetic and integer conversion must not overflow
]
