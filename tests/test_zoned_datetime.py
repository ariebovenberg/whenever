import pickle
import re
from copy import copy, deepcopy
from datetime import (
    datetime as py_datetime,
    timedelta as py_timedelta,
    timezone as py_timezone,
)
from pathlib import Path
from typing import Any, Literal, Sequence
from zoneinfo import (
    ZoneInfo,
    available_timezones as zoneinfo_available_timezones,
)

import pytest
from hypothesis import given
from hypothesis.strategies import text

from whenever import (
    Date,
    Instant,
    InvalidOffsetError,
    ItemizedDateDelta,
    ItemizedDelta,
    OffsetDateTime,
    PlainDateTime,
    PotentiallyStaleOffsetWarning,
    RepeatedTime,
    SkippedTime,
    Time,
    TimeDelta,
    TimeZoneNotFoundError,
    WheneverDeprecationWarning,
    ZonedDateTime,
    available_timezones,
    clear_tzcache,
    days,
    hours,
    milliseconds,
    minutes,
    reset_tzpath,
    weeks,
    years,
)

from .common import (
    AMS_TZ_POSIX,
    AMS_TZ_RAWFILE,
    AlwaysEqual,
    AlwaysLarger,
    AlwaysSmaller,
    NeverEqual,
    create_zdt,
    suppress,
    system_tz,
    system_tz_ams,
    system_tz_nyc,
)

try:
    import tzdata  # noqa
except ImportError:
    HAS_TZDATA = False
else:
    HAS_TZDATA = True

TEST_DIR = Path(__file__).parent

pytestmark = pytest.mark.filterwarnings(
    "ignore::whenever.WheneverDeprecationWarning"
)


class TestInit:
    def test_unambiguous(self):
        zone = "America/New_York"
        d = ZonedDateTime(2020, 8, 15, 5, 12, 30, nanosecond=450, tz=zone)

        assert d.year == 2020
        assert d.month == 8
        assert d.day == 15
        assert d.hour == 5
        assert d.minute == 12
        assert d.second == 30
        assert d.nanosecond == 450
        assert d.tz == zone

    def test_repeated_time(self):
        kwargs: dict[str, Any] = dict(
            year=2023,
            month=10,
            day=29,
            hour=2,
            minute=15,
            second=30,
            tz="Europe/Amsterdam",
        )

        assert ZonedDateTime(**kwargs).exact_eq(
            ZonedDateTime(**kwargs, disambiguate="compatible")
        )

        with pytest.raises(
            RepeatedTime,
            match="2023-10-29 02:15:30 is repeated in timezone 'Europe/Amsterdam'",
        ):
            ZonedDateTime(**kwargs, disambiguate="raise")

        assert (
            ZonedDateTime(**kwargs, disambiguate="earlier").offset
            > ZonedDateTime(**kwargs, disambiguate="later").offset
        )
        assert ZonedDateTime(**kwargs, disambiguate="compatible").exact_eq(
            ZonedDateTime(**kwargs, disambiguate="earlier")
        )

    def test_invalid_zone(self):
        with pytest.raises((TypeError, AttributeError)):
            ZonedDateTime(
                2020,
                8,
                15,
                5,
                12,
                tz=hours(34),  # type: ignore[call-overload]
            )

    @pytest.mark.parametrize(
        "key",
        [
            "America/Nowhere",  # non-existent
            "/America/New_York",  # slash at the beginning
            "America/New_York/",  # slash at the end
            "America/New\0York",  # null byte
            "America\\New_York",  # backslash
            "../America/New_York/",  # relative path
            "America/New_York/..",  # other dots
            "America//New_York",  # double slash
            "./America/New_York",  # start with dot
            "America/../America/New_York",  # not normalized
            "America/./America/New_York",  # not normalized
            "+VERSION",  # in tz path, but not a tzif file
            "leapseconds",  # in tz path, but not a tzif file
            "Europe",  # a directory
            "__init__.py",  # file in tzdata package
            "",
            ".",
            "/",
            " ",
            "Foo" * 100,  # too long
            # invalid file path characters
            "foo:bar",
            "bla*",
            "*",
            "**",
            ":",
            "&",
            # non-ascii
            "🇨🇦",
            "America/Bogotá",
            # invalid start characters
            "+B",
            "+",
            "-",
            "-foo",
        ],
    )
    def test_invalid_key(self, key: str):
        with pytest.raises(TimeZoneNotFoundError):
            ZonedDateTime(2020, 8, 15, 5, 12, tz=key)

    # This test is run last, because it modifies the tz cache
    # which can affect other tests (namely those using exact_eq)
    @pytest.mark.order(-1)
    def test_tz_cache_adjustments(self):
        nyc = "America/New_York"
        ams = "Europe/Amsterdam"
        # creating a ZDT puts it in the tz cache
        d = ZonedDateTime(2020, 8, 15, 5, 12, tz=nyc)
        ZonedDateTime(2020, 8, 15, 5, 12, tz=ams)

        assert available_timezones() == zoneinfo_available_timezones()

        from whenever import TZPATH

        prev_tzpath = TZPATH
        # We now set the TZ path to our test directory
        # (which contains some tzif files)
        reset_tzpath([TEST_DIR / "tzif"])
        from whenever import TZPATH

        assert TZPATH == (str(TEST_DIR / "tzif"),)
        try:
            # Available timezones should now be different
            assert available_timezones() != zoneinfo_available_timezones()
            # We still can find load the NYC timezone even though
            # it isn't in the new path. This is because it's cached!
            assert ZonedDateTime(1982, 8, 15, 5, 12, tz=nyc)
            assert ZonedDateTime(1982, 8, 15, 5, 12, tz=ams)
            # So let's clear the cache and check we can't find it anymore
            clear_tzcache(only_keys=[nyc])
            if not HAS_TZDATA:
                with pytest.raises(TimeZoneNotFoundError):
                    ZonedDateTime(1982, 8, 15, 5, 12, tz=nyc)

            # We can still use the old instance without problems
            d.add(hours=24)

            assert ZonedDateTime(1982, 8, 15, 5, 12, tz=ams)
            clear_tzcache()
            if not HAS_TZDATA:
                with pytest.raises(TimeZoneNotFoundError):
                    ZonedDateTime(1982, 8, 15, 5, 12, tz=ams)

            # We can still use the old instance without problems
            d.add(hours=24)

            # Ok, let's see if we can find our custom timezones
            d2 = ZonedDateTime(1982, 8, 15, 5, 12, tz="Amsterdam.tzif")
            d3 = ZonedDateTime(1982, 8, 15, 5, 12, tz="Asia/Amman")
        finally:
            # We need to reset the tzpath to the original one
            reset_tzpath()

        from whenever import TZPATH

        assert TZPATH == prev_tzpath

        # Available timezones should now be the same again
        assert available_timezones() == zoneinfo_available_timezones()

        # Our custom timezones are still in the cache
        assert ZonedDateTime(1982, 8, 15, 5, 12, tz="Amsterdam.tzif")
        # And clear the cache again
        clear_tzcache()
        # ...and now they aren't
        with pytest.raises(TimeZoneNotFoundError):
            ZonedDateTime(1982, 8, 15, 5, 12, tz="Amsterdam.tzif")

        # strict equality is impacted
        assert not d2.to_plain().assume_tz("Europe/Amsterdam").exact_eq(d2)
        # Note the "Asia/Amman" file in our tzif directory is purposefully
        # an older version, so they shouldn't compare equal
        assert not d3.to_plain().assume_tz("Asia/Amman").exact_eq(d3)
        # the NYC instance is still the same value (but a different instance/pointer)
        assert d.to_plain().assume_tz(nyc).exact_eq(d)

        # but we can still use an old instance
        d2.add(hours=24)

        # We can request proper timezones now again
        assert ZonedDateTime(2020, 8, 15, 5, 12, tz=nyc) == d
        # exact_eq() works again
        assert ZonedDateTime(2020, 8, 15, 5, 12, tz=nyc).exact_eq(d)

        # check exception handling invalid arguments
        with pytest.raises(TypeError, match="iterable"):
            reset_tzpath("/usr/share/zoneinfo")  # must be a list!
        with pytest.raises(ValueError, match="absolute"):
            reset_tzpath(["../../share/zoneinfo"])

    def test_optionality(self):
        tz = "America/New_York"
        assert ZonedDateTime(2020, 8, 15, 12, tz=tz).exact_eq(
            ZonedDateTime(
                2020,
                8,
                15,
                12,
                0,
                0,
                nanosecond=0,
                tz=tz,
                disambiguate="raise",
            )
        )

    def test_tz_required(self):
        with pytest.raises(TypeError):
            ZonedDateTime(2020, 8, 15, 12)  # type: ignore[call-overload]

    def test_out_of_range_due_to_offset(self):
        with pytest.raises((ValueError, OverflowError), match="range|year"):
            ZonedDateTime(1, 1, 1, tz="Asia/Tokyo")

        with pytest.raises((ValueError, OverflowError), match="range|year"):
            ZonedDateTime(9999, 12, 31, 23, tz="America/New_York")

    def test_invalid(self):
        with pytest.raises(ValueError):
            ZonedDateTime(
                2020,
                8,
                15,
                12,
                8,
                30,
                nanosecond=1_000_000_000,
                tz="Europe/Amsterdam",
            )

    def test_skipped(self):
        kwargs: dict[str, Any] = dict(
            year=2023,
            month=3,
            day=26,
            hour=2,
            minute=15,
            second=30,
            tz="Europe/Amsterdam",
        )

        assert ZonedDateTime(**kwargs).exact_eq(
            ZonedDateTime(**kwargs, disambiguate="compatible")
        )

        with pytest.raises(
            SkippedTime,
            match="2023-03-26 02:15:30 is skipped in timezone 'Europe/Amsterdam'",
        ):
            ZonedDateTime(**kwargs, disambiguate="raise")

        d1 = ZonedDateTime(**kwargs, disambiguate="compatible")
        assert d1.exact_eq(
            ZonedDateTime(2023, 3, 26, 3, 15, 30, tz="Europe/Amsterdam")
        )

        assert ZonedDateTime(**kwargs, disambiguate="later").exact_eq(
            ZonedDateTime(2023, 3, 26, 3, 15, 30, tz="Europe/Amsterdam")
        )
        assert ZonedDateTime(**kwargs, disambiguate="earlier").exact_eq(
            ZonedDateTime(2023, 3, 26, 1, 15, 30, tz="Europe/Amsterdam")
        )

        assert issubclass(SkippedTime, ValueError)

    def test_from_iso(self):
        assert ZonedDateTime(
            "2020-08-15T23:12:09.987654321-04:00[America/New_York]"
        ).exact_eq(
            ZonedDateTime(
                2020,
                8,
                15,
                23,
                12,
                9,
                nanosecond=987_654_321,
                tz="America/New_York",
            )
        )

    def test_leap_seconds_parsing(self):
        # Leap second (60) should be parsed and normalized to 59
        assert ZonedDateTime.parse_iso(
            "2020-08-15T05:12:60-04:00[America/New_York]"
        ).exact_eq(
            ZonedDateTime(2020, 8, 15, 5, 12, 59, tz="America/New_York")
        )

        assert ZonedDateTime.parse_iso(
            "2020-08-15T05:12:60.123456-04:00[America/New_York]"
        ).exact_eq(
            ZonedDateTime(
                2020,
                8,
                15,
                5,
                12,
                59,
                nanosecond=123_456_000,
                tz="America/New_York",
            )
        )

        # Basic format
        assert ZonedDateTime.parse_iso(
            "20200815T051260-0400[America/New_York]"
        ).exact_eq(
            ZonedDateTime(2020, 8, 15, 5, 12, 59, tz="America/New_York")
        )

        # With fractional seconds (using UTC to avoid timezone offset issues)
        assert ZonedDateTime.parse_iso(
            "2020-08-15T23:59:60.999999999+00:00[UTC]"
        ).exact_eq(
            ZonedDateTime(
                2020,
                8,
                15,
                23,
                59,
                59,
                nanosecond=999_999_999,
                tz="UTC",
            )
        )

        # Direct construction should still reject 60
        with pytest.raises(ValueError):
            ZonedDateTime(2020, 8, 15, 5, 12, 60, tz="America/New_York")

    def test_leap_seconds_comprehensive(self):
        # Test with UTC - leap second normalization works across timezones
        dt = ZonedDateTime.parse_iso("2020-08-15T12:34:60+00:00[UTC]")
        assert dt.second == 59
        assert dt.tz == "UTC"

        # Test with various timezones using their actual offsets
        # America/New_York is UTC-4 in August 2020
        dt = ZonedDateTime.parse_iso(
            "2020-08-15T12:34:60-04:00[America/New_York]"
        )
        assert dt.second == 59
        assert dt.tz == "America/New_York"

        # With comma as decimal separator
        assert ZonedDateTime.parse_iso(
            "2020-08-15T12:34:60,5+00:00[UTC]"
        ).exact_eq(
            ZonedDateTime(
                2020, 8, 15, 12, 34, 59, nanosecond=500_000_000, tz="UTC"
            )
        )

        # Invalid seconds should be rejected
        with pytest.raises(ValueError, match="Invalid format"):
            ZonedDateTime.parse_iso("2020-08-15T12:34:61+00:00[UTC]")
        with pytest.raises(ValueError, match="Invalid format"):
            ZonedDateTime.parse_iso("2020-08-15T12:34:99+00:00[UTC]")


@system_tz_ams()
def test_from_system_tz():
    d = ZonedDateTime.from_system_tz(
        2020,
        8,
        15,
        23,
        12,
        9,
        nanosecond=987_654_321,
        disambiguate="later",
    )
    assert d.tz == "Europe/Amsterdam"
    assert d.offset == hours(2)
    assert d.exact_eq(
        ZonedDateTime(
            2020,
            8,
            15,
            23,
            12,
            9,
            nanosecond=987_654_321,
            tz="Europe/Amsterdam",
        )
    )

    # check variations of the call
    assert ZonedDateTime.from_system_tz(2020, 8, 15).exact_eq(
        ZonedDateTime(2020, 8, 15, tz="Europe/Amsterdam")
    )

    with pytest.raises(TypeError):
        ZonedDateTime.from_system_tz(2020, 8, 15, tz="America/New_York")  # type: ignore[call-arg]

    with pytest.raises(ValueError):
        ZonedDateTime.from_system_tz(2020, 8, 15, nanosecond=1_000_000_000)


# NOTE: there's a separate test for changing the tzpath and
# its effect on available_timezones()
# We run this test relatively late to allow the cache to be used more
# organically throughout other tests instead of immediately loading everything
# here beforehand
@pytest.mark.order(-2)
def test_available_timezones():
    tzs = available_timezones()

    # So long as we don't mess with the configuration, these should be identical
    assert tzs == zoneinfo_available_timezones()

    d = ZonedDateTime(2025, 3, 26, 1, 15, 30, tz="UTC")

    # We should be able to load all of them
    for tz in tzs:
        d = d.to_tz(tz)


ZDT1 = create_zdt(
    2020,
    8,
    15,
    23,
    12,
    9,
    nanosecond=987_654_321,
    tz="Europe/Amsterdam",
)
ZDT2 = create_zdt(
    1900,
    1,
    1,
    tz="Europe/Dublin",
)
ZDT3 = create_zdt(
    1995,
    12,
    4,
    23,
    12,
    30,
    tz="America/New_York",
)
ZDT_POSIX = create_zdt(
    2020, 8, 15, 23, 12, 9, nanosecond=987_654_321, tz=AMS_TZ_POSIX
)
ZDT_RAWFILE = create_zdt(
    2020, 8, 15, 23, 12, 9, nanosecond=987_654_321, tz=AMS_TZ_RAWFILE
)


@pytest.mark.parametrize(
    "d, expected",
    [
        (ZDT1, hours(2)),
        (ZDT2, -TimeDelta(minutes=25, seconds=21)),
        (ZDT3, hours(-5)),
        (ZDT_POSIX, hours(2)),
        (ZDT_RAWFILE, hours(2)),
    ],
)
def test_offset(d: ZonedDateTime, expected: TimeDelta):
    assert d.offset == expected


def test_immutable():
    d = ZonedDateTime(2020, 8, 15, tz="Europe/Amsterdam")
    with pytest.raises(AttributeError):
        d.year = 2021  # type: ignore[misc]


@pytest.mark.parametrize(
    "d, expected",
    [
        (ZDT1, Date(2020, 8, 15)),
        (ZDT2, Date(1900, 1, 1)),
        (ZDT3, Date(1995, 12, 4)),
        (ZDT_POSIX, Date(2020, 8, 15)),
        (ZDT_RAWFILE, Date(2020, 8, 15)),
    ],
)
def test_date(d: ZonedDateTime, expected: Date):
    assert d.date() == expected


@pytest.mark.parametrize(
    "d, expected",
    [
        (ZDT1, Time(23, 12, 9, nanosecond=987_654_321)),
        (ZDT2, Time(0, 0, 0)),
        (ZDT3, Time(23, 12, 30)),
        (ZDT_POSIX, Time(23, 12, 9, nanosecond=987_654_321)),
        (ZDT_RAWFILE, Time(23, 12, 9, nanosecond=987_654_321)),
    ],
)
def test_time(d: ZonedDateTime, expected: Time):
    assert d.time() == expected


@pytest.mark.parametrize(
    "d",
    [
        ZDT1,
        ZDT2,
        ZDT3,
        ZDT_POSIX,
        ZDT_RAWFILE,
    ],
)
def test_to_plain(d: ZonedDateTime):
    plain = d.to_plain()
    assert isinstance(plain, PlainDateTime)
    assert plain.year == d.year
    assert plain.month == d.month
    assert plain.day == d.day
    assert plain.hour == d.hour
    assert plain.minute == d.minute
    assert plain.second == d.second
    assert plain.nanosecond == d.nanosecond


class TestReplaceDate:
    @pytest.mark.parametrize(
        "d",
        [
            ZDT1,
            ZDT2,
            ZDT3,
            ZDT_POSIX,
            ZDT_RAWFILE,
        ],
    )
    def test_unambiguous(self, d: ZonedDateTime):
        assert d.replace_date(Date(2021, 1, 2)).exact_eq(
            d.replace(year=2021, month=1, day=2)
        )

    @pytest.mark.parametrize(
        "d",
        [
            # before a fold
            create_zdt(2020, 6, 1, 2, 15, 30, tz="Europe/Amsterdam"),
            create_zdt(2020, 6, 1, 2, 15, 30, tz=AMS_TZ_POSIX),
            create_zdt(2020, 6, 1, 2, 15, 30, tz=AMS_TZ_RAWFILE),
            # after a fold
            create_zdt(2020, 11, 8, 2, 15, 30, tz="Europe/Amsterdam"),
            create_zdt(2020, 11, 8, 2, 15, 30, tz=AMS_TZ_POSIX),
            create_zdt(2020, 11, 8, 2, 15, 30, tz=AMS_TZ_RAWFILE),
            # in a fold
            create_zdt(2022, 10, 30, 2, 30, 30, tz="Europe/Amsterdam"),
            create_zdt(2022, 10, 30, 2, 30, 30, tz=AMS_TZ_POSIX),
            create_zdt(2022, 10, 30, 2, 30, 30, tz=AMS_TZ_RAWFILE),
        ],
    )
    def test_repeated_time(self, d: ZonedDateTime):
        date = Date(2023, 10, 29)

        with pytest.raises(RepeatedTime):
            assert d.replace_date(date, disambiguate="raise")

        assert d.replace_date(date).exact_eq(
            d.replace(year=2023, month=10, day=29)
        )
        assert d.replace_date(date, disambiguate="earlier").exact_eq(
            d.replace(year=2023, month=10, day=29, disambiguate="earlier")
        )
        assert d.replace_date(date, disambiguate="later").exact_eq(
            d.replace(year=2023, month=10, day=29, disambiguate="later")
        )
        assert d.replace_date(date, disambiguate="compatible").exact_eq(
            d.replace(year=2023, month=10, day=29, disambiguate="compatible")
        )

    @pytest.mark.parametrize(
        "d",
        [
            # before the gap
            create_zdt(2020, 1, 1, 2, 15, 30, tz="Europe/Amsterdam"),
            create_zdt(2020, 1, 1, 2, 15, 30, tz=AMS_TZ_POSIX),
            create_zdt(2020, 1, 1, 2, 15, 30, tz=AMS_TZ_RAWFILE),
            # after the gap
            create_zdt(2020, 6, 1, 2, 15, 30, tz="Europe/Amsterdam"),
            create_zdt(2020, 6, 1, 2, 15, 30, tz=AMS_TZ_POSIX),
            create_zdt(2020, 6, 1, 2, 15, 30, tz=AMS_TZ_RAWFILE),
        ],
    )
    def test_skipped_time(self, d: ZonedDateTime):
        date = Date(2023, 3, 26)

        with pytest.raises(SkippedTime):
            assert d.replace_date(date, disambiguate="raise")

        assert d.replace_date(date).exact_eq(
            d.replace(year=2023, month=3, day=26)
        )
        assert d.replace_date(date, disambiguate="earlier").exact_eq(
            d.replace(year=2023, month=3, day=26, disambiguate="earlier")
        )
        assert d.replace_date(date, disambiguate="later").exact_eq(
            d.replace(year=2023, month=3, day=26, disambiguate="later")
        )
        assert d.replace_date(date, disambiguate="compatible").exact_eq(
            d.replace(year=2023, month=3, day=26, disambiguate="compatible")
        )

    def test_invalid(self):
        d = ZonedDateTime(2020, 8, 15, 14, tz="Europe/Amsterdam")
        with pytest.raises((TypeError, AttributeError)):
            d.replace_date(object(), disambiguate="compatible")  # type: ignore[arg-type]

        with pytest.raises(ValueError, match="disambiguate"):
            d.replace_date(Date(2020, 8, 15), disambiguate="foo")  # type: ignore[arg-type]

        with pytest.raises(TypeError, match="got 2|foo"):
            d.replace_date(Date(2020, 8, 15), disambiguate="raise", foo=4)  # type: ignore[call-arg]

        with pytest.raises(TypeError, match="foo"):
            d.replace_date(Date(2020, 8, 15), foo="raise")  # type: ignore[call-arg]

    def test_out_of_range_due_to_offset(self):
        d = ZonedDateTime(2020, 1, 1, tz="Asia/Tokyo")
        with pytest.raises((ValueError, OverflowError), match="range|year"):
            d.replace_date(Date(1, 1, 1), disambiguate="compatible")

        d2 = ZonedDateTime(2020, 1, 1, hour=23, tz="America/New_York")
        with pytest.raises((ValueError, OverflowError), match="range|year"):
            d2.replace_date(Date(9999, 12, 31), disambiguate="compatible")


class TestReplaceTime:
    @pytest.mark.parametrize(
        "d",
        [
            ZDT1,
            ZDT2,
            ZDT3,
            ZDT_POSIX,
            ZDT_RAWFILE,
        ],
    )
    def test_unambiguous(self, d):
        assert d.replace_time(Time(1, 2, 3, nanosecond=4_000)).exact_eq(
            d.replace(hour=1, minute=2, second=3, nanosecond=4_000)
        )

    @pytest.mark.parametrize(
        "d",
        [
            # before a fold
            create_zdt(2023, 10, 29, 0, 15, 30, tz="Europe/Amsterdam"),
            create_zdt(2023, 10, 29, 0, 15, 30, tz=AMS_TZ_POSIX),
            create_zdt(2023, 10, 29, 0, 15, 30, tz=AMS_TZ_RAWFILE),
            # after a fold
            create_zdt(2023, 10, 29, 4, 15, 30, tz="Europe/Amsterdam"),
            create_zdt(2023, 10, 29, 4, 15, 30, tz=AMS_TZ_POSIX),
            create_zdt(2023, 10, 29, 4, 15, 30, tz=AMS_TZ_RAWFILE),
            # in a fold
            create_zdt(2023, 10, 29, 2, 30, 30, tz="Europe/Amsterdam"),
            create_zdt(2023, 10, 29, 2, 30, 30, tz=AMS_TZ_POSIX),
            create_zdt(2023, 10, 29, 2, 30, 30, tz=AMS_TZ_RAWFILE),
        ],
    )
    def test_repeated_time(self, d: ZonedDateTime):
        time = Time(2, 15, 30)

        with pytest.raises(RepeatedTime):
            assert d.replace_time(time, disambiguate="raise")

        assert d.replace_time(time).exact_eq(
            d.replace(hour=2, minute=15, second=30)
        )
        assert d.replace_time(time, disambiguate="earlier").exact_eq(
            d.replace(hour=2, minute=15, second=30, disambiguate="earlier")
        )
        assert d.replace_time(time, disambiguate="later").exact_eq(
            d.replace(hour=2, minute=15, second=30, disambiguate="later")
        )
        assert d.replace_time(time, disambiguate="compatible").exact_eq(
            d.replace(hour=2, minute=15, second=30, disambiguate="compatible")
        )

    @pytest.mark.parametrize(
        "d",
        [
            # before a gap
            create_zdt(2023, 3, 26, 0, 15, tz="Europe/Amsterdam"),
            create_zdt(2023, 3, 26, 0, 15, tz=AMS_TZ_POSIX),
            create_zdt(2023, 3, 26, 0, 15, tz=AMS_TZ_RAWFILE),
            # after a gap
            create_zdt(2023, 3, 26, 4, 15, tz="Europe/Amsterdam"),
            create_zdt(2023, 3, 26, 4, 15, tz=AMS_TZ_POSIX),
            create_zdt(2023, 3, 26, 4, 15, tz=AMS_TZ_RAWFILE),
        ],
    )
    def test_skipped_time(self, d: ZonedDateTime):
        time = Time(2, 15)
        with pytest.raises(SkippedTime):
            assert d.replace_time(time, disambiguate="raise")

        assert d.replace_time(time).exact_eq(
            d.replace(hour=2, minute=15, second=0)
        )
        assert d.replace_time(time, disambiguate="earlier").exact_eq(
            d.replace(hour=2, minute=15, disambiguate="earlier")
        )
        assert d.replace_time(time, disambiguate="later").exact_eq(
            d.replace(hour=2, minute=15, disambiguate="later")
        )
        assert d.replace_time(time, disambiguate="compatible").exact_eq(
            d.replace(hour=2, minute=15, disambiguate="compatible")
        )

    def test_invalid(self):
        d = ZonedDateTime(2020, 8, 15, 14, tz="Europe/Amsterdam")
        with pytest.raises((TypeError, AttributeError)):
            d.replace_time(object(), disambiguate="later")  # type: ignore[arg-type]

        with pytest.raises(ValueError, match="disambiguate"):
            d.replace_time(Time(1, 2, 3), disambiguate="foo")  # type: ignore[arg-type]

        with pytest.raises(TypeError, match="got 2|foo"):
            d.replace_time(Time(1, 2, 3), disambiguate="raise", foo=4)  # type: ignore[call-arg]

        with pytest.raises(TypeError, match="foo"):
            d.replace_time(Time(1, 2, 3), foo="raise")  # type: ignore[call-arg]

    def test_out_of_range_due_to_offset(self):
        d = ZonedDateTime(1, 1, 1, hour=23, tz="Asia/Tokyo")
        with pytest.raises((ValueError, OverflowError), match="range|year"):
            d.replace_time(Time(1), disambiguate="compatible")

        d2 = ZonedDateTime(9999, 12, 31, hour=2, tz="America/New_York")
        with pytest.raises((ValueError, OverflowError), match="range|year"):
            d2.replace_time(Time(23), disambiguate="compatible")


class TestFormatIso:

    @pytest.mark.parametrize(
        "d, expected",
        [
            (
                ZonedDateTime(
                    1998,
                    11,
                    15,
                    23,
                    12,
                    9,
                    nanosecond=987_654_321,
                    tz="Europe/Amsterdam",
                ),
                "1998-11-15T23:12:09.987654321+01:00[Europe/Amsterdam]",
            ),
            (
                ZonedDateTime(
                    2023,
                    10,
                    29,
                    2,
                    15,
                    30,
                    tz="Europe/Amsterdam",
                    disambiguate="earlier",
                ),
                "2023-10-29T02:15:30+02:00[Europe/Amsterdam]",
            ),
            (
                ZonedDateTime(
                    2023,
                    10,
                    29,
                    2,
                    15,
                    30,
                    tz="Europe/Amsterdam",
                    disambiguate="later",
                ),
                "2023-10-29T02:15:30+01:00[Europe/Amsterdam]",
            ),
            (
                ZDT2,
                "1900-01-01T00:00:00-00:25:21[Europe/Dublin]",
            ),
            (
                ZDT3,
                "1995-12-04T23:12:30-05:00[America/New_York]",
            ),
        ],
    )
    def test_defaults(self, d: ZonedDateTime, expected: str):
        assert str(d) == expected
        assert d.format_iso() == expected

    @pytest.mark.parametrize("d", [ZDT_POSIX, ZDT_RAWFILE])
    def test_no_timezone_id(self, d: ZonedDateTime):
        with pytest.raises(ValueError, match="timezone ID"):
            d.format_iso()

    @pytest.mark.parametrize(
        "zdt, kwargs, expected",
        [
            (
                ZDT1,
                {"unit": "nanosecond"},
                "2020-08-15T23:12:09.987654321+02:00[Europe/Amsterdam]",
            ),
            (
                ZDT1,
                {"unit": "microsecond", "sep": " "},
                "2020-08-15 23:12:09.987654+02:00[Europe/Amsterdam]",
            ),
            (
                ZDT1,
                {"unit": "millisecond", "basic": True},
                "20200815T231209.987+0200[Europe/Amsterdam]",
            ),
            (
                ZDT1,
                {"unit": "second", "sep": "T", "basic": True},
                "20200815T231209+0200[Europe/Amsterdam]",
            ),
            (
                ZDT1,
                {"unit": "minute"},
                "2020-08-15T23:12+02:00[Europe/Amsterdam]",
            ),
            (
                ZDT1,
                {"unit": "hour", "basic": True},
                "20200815T23+0200[Europe/Amsterdam]",
            ),
            (
                ZDT1,
                {"unit": "auto", "basic": False},
                "2020-08-15T23:12:09.987654321+02:00[Europe/Amsterdam]",
            ),
            (
                ZDT2,
                {"unit": "auto"},
                "1900-01-01T00:00:00-00:25:21[Europe/Dublin]",
            ),
            (
                ZDT2,
                {"unit": "millisecond"},
                "1900-01-01T00:00:00.000-00:25:21[Europe/Dublin]",
            ),
            (
                ZDT2,
                {"unit": "millisecond", "tz": "never"},
                "1900-01-01T00:00:00.000-00:25:21",
            ),
            (
                ZDT2,
                {"unit": "microsecond", "tz": "always"},
                "1900-01-01T00:00:00.000000-00:25:21[Europe/Dublin]",
            ),
            (
                ZDT2,
                {
                    "unit": "nanosecond",
                    "basic": True,
                    "sep": " ",
                    "tz": "auto",
                },
                "19000101 000000.000000000-002521[Europe/Dublin]",
            ),
            (
                ZDT2,
                {"unit": "hour", "basic": True, "sep": "T"},
                "19000101T00-002521[Europe/Dublin]",
            ),
            (
                ZDT_POSIX,
                {
                    "unit": "nanosecond",
                    "basic": True,
                    "sep": "T",
                    "tz": "auto",
                },
                "20200815T231209.987654321+0200",
            ),
            (
                ZDT_RAWFILE,
                {"unit": "millisecond", "sep": " ", "tz": "never"},
                "2020-08-15 23:12:09.987+02:00",
            ),
        ],
    )
    def test_variations(self, zdt, kwargs, expected):
        assert zdt.format_iso(**kwargs) == expected

    def test_invalid(self):
        with pytest.raises(ValueError, match="unit"):
            ZDT1.format_iso(unit="foo")  # type: ignore[arg-type]

        with pytest.raises(
            (ValueError, TypeError, AttributeError), match="unit"
        ):
            ZDT1.format_iso(unit=True)  # type: ignore[arg-type]

        with pytest.raises(ValueError, match="sep"):
            ZDT1.format_iso(sep="_")  # type: ignore[arg-type]

        with pytest.raises(
            (ValueError, TypeError, AttributeError), match="sep"
        ):
            ZDT1.format_iso(sep=1)  # type: ignore[arg-type]

        with pytest.raises(TypeError, match="basic"):
            ZDT1.format_iso(basic=1)  # type: ignore[arg-type]


class TestEquality:
    @pytest.mark.parametrize(
        "d",
        [
            ZDT1,
            ZDT2,
            ZDT3,
            ZDT_POSIX,
            ZDT_RAWFILE,
        ],
    )
    def test_same_exact(self, d: ZonedDateTime):
        d2 = d.replace(year=d.year)  # create a new instance with same value
        assert d == d2
        assert not d != d2
        assert hash(d) == hash(d2)

    @pytest.mark.parametrize(
        "d",
        [
            ZDT1,
            ZDT2,
            ZDT3,
            ZDT_POSIX,
            ZDT_RAWFILE,
        ],
    )
    def test_different_timezone(self, d: ZonedDateTime):
        # same **wall clock** time, different timezone
        d2 = d.replace(tz="America/Los_Angeles")
        assert d != d2
        assert not d == d2
        assert hash(d) != hash(d2)

        # same moment, different timezone
        d3 = d.to_tz("America/New_York")
        assert d == d3
        assert hash(d) == hash(d3)

    @pytest.mark.parametrize(
        "d",
        [
            ZDT1,
            ZDT2,
            ZDT3,
            ZDT_POSIX,
            ZDT_RAWFILE,
        ],
    )
    def test_different_local_time(self, d: ZonedDateTime):
        d2 = d.replace(nanosecond=492_231)
        assert d != d2
        assert not d == d2
        assert hash(d) != hash(d2)

    @pytest.mark.parametrize(
        "d",
        [
            ZDT1,
            ZDT2,
            ZDT3,
            ZDT_POSIX,
            ZDT_RAWFILE,
        ],
    )
    def test_different_disambiguation(self, d: ZonedDateTime):
        d2 = d.replace(disambiguate="later")
        assert d == d2
        assert not d != d2
        assert hash(d) == hash(d2)

    @pytest.mark.parametrize(
        "tz",
        ["Europe/Amsterdam", AMS_TZ_POSIX, AMS_TZ_RAWFILE],
    )
    def test_different_fold_ambiguity(self, tz: str):
        d = create_zdt(2023, 10, 29, 2, 15, 30, tz=tz)
        d2 = d.replace(disambiguate="later")
        assert d != d2
        assert not d == d2
        assert hash(d) != hash(d2)

    @pytest.mark.parametrize(
        "tz",
        ["Europe/Amsterdam", AMS_TZ_POSIX, AMS_TZ_RAWFILE],
    )
    def test_ambiguity_between_different_timezones(self, tz: str):
        a = create_zdt(
            2023,
            10,
            29,
            2,
            15,
            30,
            tz=tz,
            disambiguate="later",
        )
        b = a.to_tz("America/New_York")
        assert a.to_instant() == b.to_instant()  # sanity check
        assert hash(a) == hash(b)
        assert a == b

    @system_tz_nyc()
    @pytest.mark.parametrize(
        "tz",
        ["Europe/Amsterdam", AMS_TZ_POSIX, AMS_TZ_RAWFILE],
    )
    def test_other_exact(self, tz: str):
        d: ZonedDateTime | OffsetDateTime = create_zdt(
            2023,
            10,
            29,
            2,
            15,
            tz=tz,
            disambiguate="earlier",
        )
        assert d == d.to_instant()  # type: ignore[comparison-overlap]
        assert hash(d) == hash(d.to_instant())
        assert d != d.to_instant() + hours(2)  # type: ignore[comparison-overlap]

        assert d == d.to_fixed_offset()
        assert hash(d) == hash(d.to_fixed_offset())
        with suppress(PotentiallyStaleOffsetWarning):
            assert d != d.to_fixed_offset().replace(hour=10)

        # important: check typing errors in case of strict-comparison mode
        d2 = create_zdt(2020, 8, 15, 12, tz=tz)
        assert d2 == d2.to_instant()  # type: ignore[comparison-overlap]

    @pytest.mark.parametrize(
        "tz",
        ["Europe/Amsterdam", AMS_TZ_POSIX, AMS_TZ_RAWFILE],
    )
    def test_not_implemented(self, tz: str):
        d = create_zdt(2020, 8, 15, 12, 8, 30, tz=tz)
        assert d == AlwaysEqual()
        assert d != NeverEqual()
        assert not d == NeverEqual()
        assert not d != AlwaysEqual()

        assert d != 42  # type: ignore[comparison-overlap]
        assert not d == 42  # type: ignore[comparison-overlap]
        assert 42 != d  # type: ignore[comparison-overlap]
        assert not 42 == d  # type: ignore[comparison-overlap]
        assert not hours(2) == d  # type: ignore[comparison-overlap]


class TestIsAmbiguous:

    @pytest.mark.parametrize(
        "tz",
        ["Europe/Amsterdam", AMS_TZ_POSIX, AMS_TZ_RAWFILE],
    )
    def test_unambiguous(self, tz: str):
        d = create_zdt(2020, 8, 15, 12, 8, 30, tz=tz)
        assert not d.is_ambiguous()

    @pytest.mark.parametrize(
        "tz",
        ["Europe/Amsterdam", AMS_TZ_POSIX, AMS_TZ_RAWFILE],
    )
    def test_fold(self, tz: str):
        d = create_zdt(
            2023,
            10,
            29,
            2,
            15,
            30,
            tz=tz,
            disambiguate="earlier",
        )
        assert d.is_ambiguous()

        d2 = d.replace(disambiguate="later")
        assert d2.is_ambiguous()

    @pytest.mark.parametrize(
        "tz",
        ["Europe/Amsterdam", AMS_TZ_POSIX, AMS_TZ_RAWFILE],
    )
    def test_gap(self, tz: str):
        d = create_zdt(2023, 3, 26, 2, 15, 30, tz=tz)
        # skipped times are shifted into non-ambiguous times
        assert not d.is_ambiguous()

        # same for different disambiguation
        d2 = create_zdt(2023, 3, 26, 2, 15, 30, tz=tz, disambiguate="earlier")
        assert not d2.is_ambiguous()


class TestNextTransition:

    @pytest.mark.parametrize(
        "tz",
        ["Europe/Amsterdam", AMS_TZ_POSIX, AMS_TZ_RAWFILE],
    )
    def test_ams_summer(self, tz: str):
        d = create_zdt(2023, 8, 15, 12, tz=tz)
        t = d.next_transition()
        assert t is not None
        # Next transition is fall-back in October 2023.
        # The returned instant is when the new offset takes effect,
        # so disambiguate="later" matches the CET offset.
        assert t.exact_eq(
            create_zdt(2023, 10, 29, 2, tz=tz, disambiguate="later")
        )

    @pytest.mark.parametrize(
        "tz",
        ["Europe/Amsterdam", AMS_TZ_POSIX, AMS_TZ_RAWFILE],
    )
    def test_ams_winter(self, tz: str):
        d = create_zdt(2024, 1, 15, 12, tz=tz)
        t = d.next_transition()
        assert t is not None
        # Next transition is spring-forward in March 2024
        assert t.exact_eq(create_zdt(2024, 3, 31, 3, tz=tz))

    def test_utc_returns_none(self):
        d = create_zdt(2024, 6, 15, 12, tz="Etc/UTC")
        assert d.next_transition() is None

    def test_no_dst_returns_none(self):
        d = create_zdt(2024, 6, 15, 12, tz="Asia/Kolkata")
        assert d.next_transition() is None

    def test_chain_nyc(self):
        d = ZonedDateTime(2024, 1, 1, tz="America/New_York")
        t1 = d.next_transition()
        assert t1 is not None
        t2 = t1.next_transition()
        assert t2 is not None
        assert t1.exact_eq(
            ZonedDateTime(2024, 3, 10, 3, tz="America/New_York")
        )
        assert t2.exact_eq(
            ZonedDateTime(
                2024, 11, 3, 1, tz="America/New_York", disambiguate="later"
            )
        )

    def test_southern_hemisphere_sydney(self):
        d = ZonedDateTime(2024, 1, 15, tz="Australia/Sydney")
        t = d.next_transition()
        assert t is not None
        # Sydney: DST ends in April (fall-back)
        assert t.exact_eq(
            ZonedDateTime(
                2024, 4, 7, 2, tz="Australia/Sydney", disambiguate="later"
            )
        )

    def test_at_exact_transition_nyc(self):
        # At the exact moment of spring-forward in NYC
        d = ZonedDateTime(2024, 3, 10, 3, tz="America/New_York")
        t = d.next_transition()
        assert t is not None
        # Should skip the current transition and find the next one
        assert t.exact_eq(
            ZonedDateTime(
                2024, 11, 3, 1, tz="America/New_York", disambiguate="later"
            )
        )

    @pytest.mark.parametrize(
        "tz",
        ["Europe/Amsterdam", AMS_TZ_POSIX, AMS_TZ_RAWFILE],
    )
    def test_far_future_posix(self, tz: str):
        d = create_zdt(2050, 6, 15, 12, tz=tz)
        t = d.next_transition()
        assert t is not None
        # Verify we get a transition in 2050
        assert t.year == 2050
        assert t.month == 10  # fall-back

    def test_return_type_and_tz(self):
        d = ZonedDateTime(2024, 1, 1, tz="America/New_York")
        t = d.next_transition()
        assert isinstance(t, ZonedDateTime)
        assert t.tz == "America/New_York"

    def test_nanosecond_is_zero(self):
        # Transitions are always on second boundaries
        d = ZonedDateTime(
            2024, 1, 1, nanosecond=123_456, tz="America/New_York"
        )
        t = d.next_transition()
        assert t is not None
        assert t.nanosecond == 0

    def test_near_max_boundary(self):
        d = ZonedDateTime(9999, 12, 1, tz="America/New_York")
        # Should not crash; result depends on POSIX rule year limits
        t = d.next_transition()
        # Year 9999 may or may not have a transition depending on implementation
        if t is not None:
            assert isinstance(t, ZonedDateTime)

    def test_near_min_boundary(self):
        d = ZonedDateTime(1, 1, 1, tz="America/New_York")
        t = d.next_transition()
        assert t is not None
        assert isinstance(t, ZonedDateTime)

    # -- First transition is into DST (America/Iqaluit, Antarctica/Palmer) --
    # These zones have no recorded transitions before their first one, and that
    # first transition is directly INTO a DST period (not a standard time).

    @pytest.mark.skipif(not HAS_TZDATA, reason="tzdata not installed")
    def test_iqaluit_before_first_transition(self):
        """America/Iqaluit: first transition at 1942-08-01 is directly into DST."""
        d = ZonedDateTime(1940, 1, 1, tz="America/Iqaluit")
        t = d.next_transition()
        assert t is not None
        # First transition: 1942-08-01 00:00:00 UTC → -04:00 (EWT, DST)
        assert t.exact_eq(
            ZonedDateTime(
                1942, 7, 31, 20, tz="America/Iqaluit", disambiguate="later"
            )
        )

    @pytest.mark.skipif(not HAS_TZDATA, reason="tzdata not installed")
    def test_iqaluit_none_before_first_transition(self):
        """No transition before the very first one."""
        d = ZonedDateTime(1940, 1, 1, tz="America/Iqaluit")
        t = d.prev_transition()
        assert t is None

    @pytest.mark.skipif(not HAS_TZDATA, reason="tzdata not installed")
    def test_palmer_before_first_transition(self):
        """Antarctica/Palmer: first transition at 1965-01-01 is directly into DST."""
        d = ZonedDateTime(1963, 1, 1, tz="Antarctica/Palmer")
        t = d.next_transition()
        assert t is not None
        # First transition: 1965-01-01 00:00:00 UTC → -03:00 (DST)
        # This is a fall-back; local time 21:00 is ambiguous, use "later"
        assert t.exact_eq(
            ZonedDateTime(
                1964, 12, 31, 21, tz="Antarctica/Palmer", disambiguate="later"
            )
        )

    # -- Array-to-POSIX TZ string handoff --
    # After the last explicitly recorded transition, the POSIX TZ string takes over.
    # These tests verify that next/prev_transition seamlessly crosses this boundary.

    @pytest.mark.parametrize(
        "tz",
        [AMS_TZ_POSIX, AMS_TZ_RAWFILE],
    )
    def test_next_transition_after_posix_boundary(self, tz: str):
        """next_transition in POSIX territory returns correct spring-forward."""
        d = create_zdt(2050, 12, 1, tz=tz)
        t = d.next_transition()
        assert t is not None
        # Last Sunday of March 2051: spring-forward to +02:00
        # 2051-03-26 01:00:00 UTC → 2051-03-26T03:00:00+02:00
        assert t.exact_eq(create_zdt(2051, 3, 26, 3, tz=tz))

    @pytest.mark.parametrize(
        "tz",
        [AMS_TZ_POSIX, AMS_TZ_RAWFILE],
    )
    def test_prev_transition_after_posix_boundary(self, tz: str):
        """prev_transition in POSIX territory returns correct spring-forward."""
        d = create_zdt(2051, 4, 1, tz=tz)
        t = d.prev_transition()
        assert t is not None
        assert t.exact_eq(create_zdt(2051, 3, 26, 3, tz=tz))


class TestPrevTransition:

    @pytest.mark.parametrize(
        "tz",
        ["Europe/Amsterdam", AMS_TZ_POSIX, AMS_TZ_RAWFILE],
    )
    def test_ams_summer(self, tz: str):
        d = create_zdt(2023, 8, 15, 12, tz=tz)
        t = d.prev_transition()
        assert t is not None
        # Previous transition is spring-forward in March 2023
        assert t.exact_eq(create_zdt(2023, 3, 26, 3, tz=tz))

    @pytest.mark.parametrize(
        "tz",
        ["Europe/Amsterdam", AMS_TZ_POSIX, AMS_TZ_RAWFILE],
    )
    def test_ams_winter(self, tz: str):
        d = create_zdt(2024, 1, 15, 12, tz=tz)
        t = d.prev_transition()
        assert t is not None
        # Previous transition is fall-back in October 2023.
        # disambiguate="later" to get the CET offset.
        assert t.exact_eq(
            create_zdt(2023, 10, 29, 2, tz=tz, disambiguate="later")
        )

    def test_utc_returns_none(self):
        d = create_zdt(2024, 6, 15, 12, tz="Etc/UTC")
        assert d.prev_transition() is None

    def test_kolkata_historical(self):
        # Asia/Kolkata has no transitions in modern times
        # but has historical transitions
        d = create_zdt(2024, 6, 15, 12, tz="Asia/Kolkata")
        t = d.prev_transition()
        # There are historical transitions, so it should return something
        assert t is not None
        assert t.year < 2024  # historical

    def test_chain_nyc(self):
        d = ZonedDateTime(2024, 12, 1, tz="America/New_York")
        t1 = d.prev_transition()
        assert t1 is not None
        t2 = t1.prev_transition()
        assert t2 is not None
        assert t1.exact_eq(
            ZonedDateTime(
                2024, 11, 3, 1, tz="America/New_York", disambiguate="later"
            )
        )
        assert t2.exact_eq(
            ZonedDateTime(2024, 3, 10, 3, tz="America/New_York")
        )

    def test_southern_hemisphere_sydney(self):
        d = ZonedDateTime(2024, 1, 15, tz="Australia/Sydney")
        t = d.prev_transition()
        assert t is not None
        # Sydney: DST started in October 2023 (spring-forward)
        assert t.exact_eq(ZonedDateTime(2023, 10, 1, 3, tz="Australia/Sydney"))

    def test_at_exact_transition_nyc(self):
        # At the exact moment of spring-forward in NYC
        d = ZonedDateTime(2024, 3, 10, 3, tz="America/New_York")
        t = d.prev_transition()
        assert t is not None
        # Should skip the current transition and find the previous one
        assert t.exact_eq(
            ZonedDateTime(
                2023, 11, 5, 1, tz="America/New_York", disambiguate="later"
            )
        )

    @pytest.mark.parametrize(
        "tz",
        ["Europe/Amsterdam", AMS_TZ_POSIX, AMS_TZ_RAWFILE],
    )
    def test_far_future_posix(self, tz: str):
        d = create_zdt(2050, 6, 15, 12, tz=tz)
        t = d.prev_transition()
        assert t is not None
        # Verify we get a transition in 2050
        assert t.year == 2050
        assert t.month == 3  # spring-forward

    def test_return_type_and_tz(self):
        d = ZonedDateTime(2024, 12, 1, tz="America/New_York")
        t = d.prev_transition()
        assert isinstance(t, ZonedDateTime)
        assert t.tz == "America/New_York"

    def test_nanosecond_is_zero(self):
        d = ZonedDateTime(
            2024, 12, 1, nanosecond=999_999, tz="America/New_York"
        )
        t = d.prev_transition()
        assert t is not None
        assert t.nanosecond == 0

    def test_near_max_boundary(self):
        d = ZonedDateTime(9999, 12, 1, tz="America/New_York")
        t = d.prev_transition()
        assert t is not None
        assert isinstance(t, ZonedDateTime)

    def test_near_min_boundary(self):
        d = ZonedDateTime(1, 1, 1, tz="America/New_York")
        # At the very beginning, there may be no previous transition
        t = d.prev_transition()
        # The result depends on whether there are transitions before year 1
        if t is not None:
            assert isinstance(t, ZonedDateTime)

    # -- First transition is into DST --

    @pytest.mark.skipif(not HAS_TZDATA, reason="tzdata not installed")
    def test_iqaluit_from_first_dst_period(self):
        """During the first DST period, prev_transition returns the entry into it."""
        d = ZonedDateTime(1943, 1, 1, tz="America/Iqaluit")
        t = d.prev_transition()
        assert t is not None
        assert t.exact_eq(
            ZonedDateTime(
                1942, 7, 31, 20, tz="America/Iqaluit", disambiguate="later"
            )
        )

    @pytest.mark.skipif(not HAS_TZDATA, reason="tzdata not installed")
    def test_palmer_from_first_dst_period(self):
        """During the first DST period, prev_transition returns the entry into it."""
        d = ZonedDateTime(1965, 2, 1, tz="Antarctica/Palmer")
        t = d.prev_transition()
        assert t is not None
        assert t.exact_eq(
            ZonedDateTime(
                1964, 12, 31, 21, tz="Antarctica/Palmer", disambiguate="later"
            )
        )

    # -- Array-to-POSIX TZ string handoff --

    @pytest.mark.parametrize(
        "tz",
        [AMS_TZ_POSIX, AMS_TZ_RAWFILE],
    )
    def test_next_transition_after_posix_boundary(self, tz: str):
        """next_transition crossing the POSIX TZ boundary returns correct result."""
        d = create_zdt(2050, 12, 1, tz=tz)
        t = d.next_transition()
        assert t is not None
        assert t.exact_eq(create_zdt(2051, 3, 26, 3, tz=tz))

    @pytest.mark.parametrize(
        "tz",
        [AMS_TZ_POSIX, AMS_TZ_RAWFILE],
    )
    def test_prev_transition_after_posix_boundary(self, tz: str):
        """prev_transition from just past the POSIX boundary."""
        d = create_zdt(2051, 4, 1, tz=tz)
        t = d.prev_transition()
        assert t is not None
        assert t.exact_eq(create_zdt(2051, 3, 26, 3, tz=tz))


class TestDstOffset:

    @pytest.mark.parametrize(
        "tz",
        ["Europe/Amsterdam", AMS_TZ_POSIX, AMS_TZ_RAWFILE],
    )
    def test_summer(self, tz: str):
        d = create_zdt(2020, 8, 15, 12, tz=tz)
        assert d.dst_offset() == TimeDelta(hours=1)

    @pytest.mark.parametrize(
        "tz",
        ["Europe/Amsterdam", AMS_TZ_POSIX, AMS_TZ_RAWFILE],
    )
    def test_winter(self, tz: str):
        d = create_zdt(2020, 1, 15, 12, tz=tz)
        assert d.dst_offset() == TimeDelta()

    def test_utc(self):
        d = create_zdt(2020, 8, 15, 12, tz="UTC")
        assert d.dst_offset() == TimeDelta()

    def test_no_dst_zone(self):
        d = create_zdt(2020, 8, 15, 12, tz="Asia/Tokyo")
        assert d.dst_offset() == TimeDelta()

    def test_fold_earlier(self):
        d = create_zdt(
            2023, 10, 29, 2, 30, tz="Europe/Amsterdam", disambiguate="earlier"
        )
        assert d.dst_offset() == TimeDelta(hours=1)

    def test_fold_later(self):
        d = create_zdt(
            2023, 10, 29, 2, 30, tz="Europe/Amsterdam", disambiguate="later"
        )
        assert d.dst_offset() == TimeDelta()

    @pytest.mark.parametrize(
        "tz",
        ["Europe/Amsterdam", AMS_TZ_POSIX, AMS_TZ_RAWFILE],
    )
    def test_far_future(self, tz: str):
        """POSIX TZ string fallback for dates beyond transition data"""
        d = create_zdt(2100, 7, 15, 12, tz=tz)
        assert d.dst_offset() == TimeDelta(hours=1)

        d2 = create_zdt(2100, 1, 15, 12, tz=tz)
        assert d2.dst_offset() == TimeDelta()

    # -- Dublin: "negative DST" (standard=IST UTC+1, winter=GMT UTC+0 isdst=1) --

    @pytest.mark.skipif(not HAS_TZDATA, reason="tzdata not installed")
    def test_dublin_summer(self):
        d = create_zdt(2020, 7, 15, 12, tz="Europe/Dublin")
        zi = ZoneInfo("Europe/Dublin")
        py_dt = py_datetime(2020, 7, 15, 12, tzinfo=zi)
        assert d.dst_offset() == TimeDelta(
            py_dt.dst()  # type: ignore[union-attr]
        )

    @pytest.mark.skipif(not HAS_TZDATA, reason="tzdata not installed")
    def test_dublin_winter(self):
        d = create_zdt(2020, 1, 15, 12, tz="Europe/Dublin")
        zi = ZoneInfo("Europe/Dublin")
        py_dt = py_datetime(2020, 1, 15, 12, tzinfo=zi)
        assert d.dst_offset() == TimeDelta(
            py_dt.dst()  # type: ignore[union-attr]
        )

    @pytest.mark.skipif(not HAS_TZDATA, reason="tzdata not installed")
    def test_dublin_transition_spring(self):
        """Just before and after spring-forward in Dublin (last Sun of March)"""
        zi = ZoneInfo("Europe/Dublin")
        # Before transition: 2020-03-29 00:30 UTC+0 (winter)
        d_before = create_zdt(2020, 3, 29, 0, 30, tz="Europe/Dublin")
        py_before = py_datetime(2020, 3, 29, 0, 30, tzinfo=zi)
        assert d_before.dst_offset() == TimeDelta(
            seconds=int(py_before.dst().total_seconds())  # type: ignore[union-attr]
        )
        # After transition: 2020-03-29 2:30 (summer, IST)
        d_after = create_zdt(2020, 3, 29, 2, 30, tz="Europe/Dublin")
        py_after = py_datetime(2020, 3, 29, 2, 30, tzinfo=zi)
        assert d_after.dst_offset() == TimeDelta(
            seconds=int(py_after.dst().total_seconds())  # type: ignore[union-attr]
        )

    @pytest.mark.skipif(not HAS_TZDATA, reason="tzdata not installed")
    def test_dublin_transition_autumn(self):
        """Around fall-back in Dublin (last Sun of October)"""
        zi = ZoneInfo("Europe/Dublin")
        # Before transition (earlier fold): 2020-10-25 1:30 IST
        d_earlier = create_zdt(
            2020, 10, 25, 1, 30, tz="Europe/Dublin", disambiguate="earlier"
        )
        py_earlier = py_datetime(2020, 10, 25, 1, 30, tzinfo=zi, fold=0)
        assert d_earlier.dst_offset() == TimeDelta(
            seconds=int(py_earlier.dst().total_seconds())  # type: ignore[union-attr]
        )
        # After transition (later fold): 2020-10-25 1:30 GMT
        d_later = create_zdt(
            2020, 10, 25, 1, 30, tz="Europe/Dublin", disambiguate="later"
        )
        py_later = py_datetime(2020, 10, 25, 1, 30, tzinfo=zi, fold=1)
        assert d_later.dst_offset() == TimeDelta(
            seconds=int(py_later.dst().total_seconds())  # type: ignore[union-attr]
        )

    @pytest.mark.skipif(not HAS_TZDATA, reason="tzdata not installed")
    def test_dublin_far_future(self):
        d = create_zdt(2100, 7, 15, 12, tz="Europe/Dublin")
        zi = ZoneInfo("Europe/Dublin")
        py_dt = py_datetime(2100, 7, 15, 12, tzinfo=zi)
        assert d.dst_offset() == TimeDelta(
            py_dt.dst()  # type: ignore[union-attr]
        )

        d2 = create_zdt(2100, 1, 15, 12, tz="Europe/Dublin")
        py_dt2 = py_datetime(2100, 1, 15, 12, tzinfo=zi)
        assert d2.dst_offset() == TimeDelta(
            py_dt2.dst()  # type: ignore[union-attr]
        )

    # -- Australia/Sydney: southern hemisphere DST (summer in Jan) --

    @pytest.mark.skipif(not HAS_TZDATA, reason="tzdata not installed")
    def test_sydney_summer(self):
        """January is summer (DST active) in Sydney"""
        d = create_zdt(2020, 1, 15, 12, tz="Australia/Sydney")
        zi = ZoneInfo("Australia/Sydney")
        py_dt = py_datetime(2020, 1, 15, 12, tzinfo=zi)
        assert d.dst_offset() == TimeDelta(
            py_dt.dst()  # type: ignore[union-attr]
        )

    @pytest.mark.skipif(not HAS_TZDATA, reason="tzdata not installed")
    def test_sydney_winter(self):
        """July is winter (no DST) in Sydney"""
        d = create_zdt(2020, 7, 15, 12, tz="Australia/Sydney")
        zi = ZoneInfo("Australia/Sydney")
        py_dt = py_datetime(2020, 7, 15, 12, tzinfo=zi)
        assert d.dst_offset() == TimeDelta(
            py_dt.dst()  # type: ignore[union-attr]
        )

    @pytest.mark.skipif(not HAS_TZDATA, reason="tzdata not installed")
    def test_sydney_transition_start(self):
        """DST starts first Sun of October in Sydney"""
        zi = ZoneInfo("Australia/Sydney")
        # Before: 2020-10-04 1:30 AEST (no DST)
        d_before = create_zdt(2020, 10, 4, 1, 30, tz="Australia/Sydney")
        py_before = py_datetime(2020, 10, 4, 1, 30, tzinfo=zi)
        assert d_before.dst_offset() == TimeDelta(
            seconds=int(py_before.dst().total_seconds())  # type: ignore[union-attr]
        )
        # After: 2020-10-04 3:30 AEDT (DST active)
        d_after = create_zdt(2020, 10, 4, 3, 30, tz="Australia/Sydney")
        py_after = py_datetime(2020, 10, 4, 3, 30, tzinfo=zi)
        assert d_after.dst_offset() == TimeDelta(
            seconds=int(py_after.dst().total_seconds())  # type: ignore[union-attr]
        )

    @pytest.mark.skipif(not HAS_TZDATA, reason="tzdata not installed")
    def test_sydney_transition_end(self):
        """DST ends first Sun of April in Sydney"""
        zi = ZoneInfo("Australia/Sydney")
        # Earlier fold: 2020-04-05 2:30 AEDT
        d_earlier = create_zdt(
            2020, 4, 5, 2, 30, tz="Australia/Sydney", disambiguate="earlier"
        )
        py_earlier = py_datetime(2020, 4, 5, 2, 30, tzinfo=zi, fold=0)
        assert d_earlier.dst_offset() == TimeDelta(
            seconds=int(py_earlier.dst().total_seconds())  # type: ignore[union-attr]
        )
        # Later fold: 2020-04-05 2:30 AEST
        d_later = create_zdt(
            2020, 4, 5, 2, 30, tz="Australia/Sydney", disambiguate="later"
        )
        py_later = py_datetime(2020, 4, 5, 2, 30, tzinfo=zi, fold=1)
        assert d_later.dst_offset() == TimeDelta(
            seconds=int(py_later.dst().total_seconds())  # type: ignore[union-attr]
        )

    @pytest.mark.skipif(not HAS_TZDATA, reason="tzdata not installed")
    def test_sydney_far_future(self):
        d = create_zdt(2100, 1, 15, 12, tz="Australia/Sydney")
        zi = ZoneInfo("Australia/Sydney")
        py_dt = py_datetime(2100, 1, 15, 12, tzinfo=zi)
        assert d.dst_offset() == TimeDelta(
            py_dt.dst()  # type: ignore[union-attr]
        )

    # -- Pacific/Honolulu: no DST ever --

    @pytest.mark.skipif(not HAS_TZDATA, reason="tzdata not installed")
    def test_honolulu_summer(self):
        d = create_zdt(2020, 7, 15, 12, tz="Pacific/Honolulu")
        assert d.dst_offset() == TimeDelta()

    @pytest.mark.skipif(not HAS_TZDATA, reason="tzdata not installed")
    def test_honolulu_winter(self):
        d = create_zdt(2020, 1, 15, 12, tz="Pacific/Honolulu")
        assert d.dst_offset() == TimeDelta()

    @pytest.mark.skipif(not HAS_TZDATA, reason="tzdata not installed")
    def test_honolulu_far_future(self):
        d = create_zdt(2100, 6, 15, 12, tz="Pacific/Honolulu")
        assert d.dst_offset() == TimeDelta()

    # -- Africa/Casablanca: complex DST schedule --

    @pytest.mark.skipif(
        not HAS_TZDATA
        or "Africa/Casablanca" not in zoneinfo_available_timezones(),
        reason="tzdata or Africa/Casablanca not available",
    )
    def test_casablanca_summer(self):
        d = create_zdt(2019, 7, 15, 12, tz="Africa/Casablanca")
        zi = ZoneInfo("Africa/Casablanca")
        py_dt = py_datetime(2019, 7, 15, 12, tzinfo=zi)
        assert d.dst_offset() == TimeDelta(
            py_dt.dst()  # type: ignore[union-attr]
        )

    @pytest.mark.skipif(
        not HAS_TZDATA
        or "Africa/Casablanca" not in zoneinfo_available_timezones(),
        reason="tzdata or Africa/Casablanca not available",
    )
    def test_casablanca_winter(self):
        d = create_zdt(2019, 1, 15, 12, tz="Africa/Casablanca")
        zi = ZoneInfo("Africa/Casablanca")
        py_dt = py_datetime(2019, 1, 15, 12, tzinfo=zi)
        assert d.dst_offset() == TimeDelta(
            py_dt.dst()  # type: ignore[union-attr]
        )

    @pytest.mark.skipif(
        not HAS_TZDATA
        or "Africa/Casablanca" not in zoneinfo_available_timezones(),
        reason="tzdata or Africa/Casablanca not available",
    )
    def test_casablanca_far_future(self):
        d = create_zdt(2100, 7, 15, 12, tz="Africa/Casablanca")
        zi = ZoneInfo("Africa/Casablanca")
        py_dt = py_datetime(2100, 7, 15, 12, tzinfo=zi)
        assert d.dst_offset() == TimeDelta(
            py_dt.dst()  # type: ignore[union-attr]
        )

    # -- America/New_York: standard US DST --

    def test_new_york_summer(self):
        d = create_zdt(2020, 7, 15, 12, tz="America/New_York")
        zi = ZoneInfo("America/New_York")
        py_dt = py_datetime(2020, 7, 15, 12, tzinfo=zi)
        assert d.dst_offset() == TimeDelta(
            py_dt.dst()  # type: ignore[union-attr]
        )

    def test_new_york_winter(self):
        d = create_zdt(2020, 1, 15, 12, tz="America/New_York")
        zi = ZoneInfo("America/New_York")
        py_dt = py_datetime(2020, 1, 15, 12, tzinfo=zi)
        assert d.dst_offset() == TimeDelta(
            py_dt.dst()  # type: ignore[union-attr]
        )

    def test_new_york_spring_forward(self):
        """Second Sunday of March: 2:00 AM springs to 3:00 AM"""
        zi = ZoneInfo("America/New_York")
        # Before: 2020-03-08 1:30 EST
        d_before = create_zdt(2020, 3, 8, 1, 30, tz="America/New_York")
        py_before = py_datetime(2020, 3, 8, 1, 30, tzinfo=zi)
        assert d_before.dst_offset() == TimeDelta(
            seconds=int(py_before.dst().total_seconds())  # type: ignore[union-attr]
        )
        # After: 2020-03-08 3:30 EDT
        d_after = create_zdt(2020, 3, 8, 3, 30, tz="America/New_York")
        py_after = py_datetime(2020, 3, 8, 3, 30, tzinfo=zi)
        assert d_after.dst_offset() == TimeDelta(
            seconds=int(py_after.dst().total_seconds())  # type: ignore[union-attr]
        )

    def test_new_york_fall_back(self):
        """First Sunday of November: 2:00 AM falls back to 1:00 AM"""
        zi = ZoneInfo("America/New_York")
        # Earlier fold: 2020-11-01 1:30 EDT
        d_earlier = create_zdt(
            2020, 11, 1, 1, 30, tz="America/New_York", disambiguate="earlier"
        )
        py_earlier = py_datetime(2020, 11, 1, 1, 30, tzinfo=zi, fold=0)
        assert d_earlier.dst_offset() == TimeDelta(
            seconds=int(py_earlier.dst().total_seconds())  # type: ignore[union-attr]
        )
        # Later fold: 2020-11-01 1:30 EST
        d_later = create_zdt(
            2020, 11, 1, 1, 30, tz="America/New_York", disambiguate="later"
        )
        py_later = py_datetime(2020, 11, 1, 1, 30, tzinfo=zi, fold=1)
        assert d_later.dst_offset() == TimeDelta(
            seconds=int(py_later.dst().total_seconds())  # type: ignore[union-attr]
        )

    def test_new_york_far_future(self):
        d = create_zdt(2100, 7, 15, 12, tz="America/New_York")
        zi = ZoneInfo("America/New_York")
        py_dt = py_datetime(2100, 7, 15, 12, tzinfo=zi)
        assert d.dst_offset() == TimeDelta(
            py_dt.dst()  # type: ignore[union-attr]
        )

        d2 = create_zdt(2100, 1, 15, 12, tz="America/New_York")
        py_dt2 = py_datetime(2100, 1, 15, 12, tzinfo=zi)
        assert d2.dst_offset() == TimeDelta(
            py_dt2.dst()  # type: ignore[union-attr]
        )

    # -- UTC: no DST --

    def test_utc_summer_cross_validate(self):
        d = create_zdt(2020, 7, 15, 12, tz="UTC")
        zi = ZoneInfo("UTC")
        py_dt = py_datetime(2020, 7, 15, 12, tzinfo=zi)
        assert d.dst_offset() == TimeDelta(
            py_dt.dst()  # type: ignore[union-attr]
        )

    def test_utc_far_future(self):
        d = create_zdt(2100, 7, 15, 12, tz="UTC")
        assert d.dst_offset() == TimeDelta()

    # -- Asia/Tokyo: no DST --

    def test_tokyo_summer(self):
        d = create_zdt(2020, 7, 15, 12, tz="Asia/Tokyo")
        zi = ZoneInfo("Asia/Tokyo")
        py_dt = py_datetime(2020, 7, 15, 12, tzinfo=zi)
        assert d.dst_offset() == TimeDelta(
            py_dt.dst()  # type: ignore[union-attr]
        )

    def test_tokyo_winter(self):
        d = create_zdt(2020, 1, 15, 12, tz="Asia/Tokyo")
        assert d.dst_offset() == TimeDelta()

    def test_tokyo_far_future(self):
        d = create_zdt(2100, 7, 15, 12, tz="Asia/Tokyo")
        assert d.dst_offset() == TimeDelta()

    # -- First transition is into DST --
    # Zones where the very first recorded transition is INTO a DST state.
    # The initial period (before first transition) has no DST.

    @pytest.mark.skipif(not HAS_TZDATA, reason="tzdata not installed")
    def test_iqaluit_initial_period(self):
        """Before the first transition, Iqaluit has no DST (it was UTC+0)."""
        d = ZonedDateTime(1940, 1, 1, 12, tz="America/Iqaluit")
        zi = ZoneInfo("America/Iqaluit")
        py_dt = py_datetime(1940, 1, 1, 12, tzinfo=zi)
        assert d.dst_offset() == TimeDelta(
            py_dt.dst()  # type: ignore[union-attr]
        )

    @pytest.mark.skipif(not HAS_TZDATA, reason="tzdata not installed")
    def test_iqaluit_first_dst_period(self):
        """After the first transition, Iqaluit is in EWT (DST = +1h vs EST)."""
        d = ZonedDateTime(1942, 9, 1, 12, tz="America/Iqaluit")
        zi = ZoneInfo("America/Iqaluit")
        py_dt = py_datetime(1942, 9, 1, 12, tzinfo=zi)
        assert d.dst_offset() == TimeDelta(
            py_dt.dst()  # type: ignore[union-attr]
        )

    @pytest.mark.skipif(not HAS_TZDATA, reason="tzdata not installed")
    def test_iqaluit_after_first_dst_period(self):
        """After returning to standard time, Iqaluit has no DST."""
        d = ZonedDateTime(1946, 1, 1, 12, tz="America/Iqaluit")
        zi = ZoneInfo("America/Iqaluit")
        py_dt = py_datetime(1946, 1, 1, 12, tzinfo=zi)
        assert d.dst_offset() == TimeDelta(
            py_dt.dst()  # type: ignore[union-attr]
        )

    @pytest.mark.skipif(not HAS_TZDATA, reason="tzdata not installed")
    def test_palmer_initial_period(self):
        """Before the first transition, Palmer has no DST (it was UTC+0)."""
        d = ZonedDateTime(1963, 6, 15, 12, tz="Antarctica/Palmer")
        zi = ZoneInfo("Antarctica/Palmer")
        py_dt = py_datetime(1963, 6, 15, 12, tzinfo=zi)
        assert d.dst_offset() == TimeDelta(
            py_dt.dst()  # type: ignore[union-attr]
        )

    @pytest.mark.skipif(not HAS_TZDATA, reason="tzdata not installed")
    def test_palmer_first_dst_period(self):
        """After the first transition (1965-01-01), Palmer is in DST (+1h vs -04)."""
        d = ZonedDateTime(1965, 2, 15, 12, tz="Antarctica/Palmer")
        zi = ZoneInfo("Antarctica/Palmer")
        py_dt = py_datetime(1965, 2, 15, 12, tzinfo=zi)
        assert d.dst_offset() == TimeDelta(
            py_dt.dst()  # type: ignore[union-attr]
        )


class TestTzAbbrev:

    @pytest.mark.parametrize(
        "tz",
        ["Europe/Amsterdam", AMS_TZ_POSIX, AMS_TZ_RAWFILE],
    )
    def test_summer(self, tz: str):
        d = create_zdt(2020, 8, 15, 12, tz=tz)
        assert d.tz_abbrev() == "CEST"

    @pytest.mark.parametrize(
        "tz",
        ["Europe/Amsterdam", AMS_TZ_POSIX, AMS_TZ_RAWFILE],
    )
    def test_winter(self, tz: str):
        d = create_zdt(2020, 1, 15, 12, tz=tz)
        assert d.tz_abbrev() == "CET"

    def test_utc(self):
        d = create_zdt(2020, 8, 15, 12, tz="UTC")
        assert d.tz_abbrev() == "UTC"

    def test_us_eastern(self):
        d = create_zdt(2020, 8, 15, 12, tz="America/New_York")
        assert d.tz_abbrev() == "EDT"

        d2 = create_zdt(2020, 1, 15, 12, tz="America/New_York")
        assert d2.tz_abbrev() == "EST"

    def test_japan(self):
        d = create_zdt(2020, 8, 15, 12, tz="Asia/Tokyo")
        assert d.tz_abbrev() == "JST"

    @pytest.mark.parametrize(
        "tz",
        ["Europe/Amsterdam", AMS_TZ_POSIX, AMS_TZ_RAWFILE],
    )
    def test_far_future(self, tz: str):
        d = create_zdt(2100, 7, 15, 12, tz=tz)
        assert d.tz_abbrev() == "CEST"

        d2 = create_zdt(2100, 1, 15, 12, tz=tz)
        assert d2.tz_abbrev() == "CET"

    def test_returns_str(self):
        d = create_zdt(2020, 8, 15, 12, tz="Europe/Amsterdam")
        assert type(d.tz_abbrev()) is str

    # -- Dublin: "negative DST" (IST in summer, GMT in winter) --

    @pytest.mark.skipif(not HAS_TZDATA, reason="tzdata not installed")
    def test_dublin_summer(self):
        d = create_zdt(2020, 7, 15, 12, tz="Europe/Dublin")
        zi = ZoneInfo("Europe/Dublin")
        py_dt = py_datetime(2020, 7, 15, 12, tzinfo=zi)
        assert d.tz_abbrev() == py_dt.tzname()

    @pytest.mark.skipif(not HAS_TZDATA, reason="tzdata not installed")
    def test_dublin_winter(self):
        d = create_zdt(2020, 1, 15, 12, tz="Europe/Dublin")
        zi = ZoneInfo("Europe/Dublin")
        py_dt = py_datetime(2020, 1, 15, 12, tzinfo=zi)
        assert d.tz_abbrev() == py_dt.tzname()

    @pytest.mark.skipif(not HAS_TZDATA, reason="tzdata not installed")
    def test_dublin_transition_spring(self):
        zi = ZoneInfo("Europe/Dublin")
        # Before spring-forward: 2020-03-29 0:30 (winter, GMT)
        d_before = create_zdt(2020, 3, 29, 0, 30, tz="Europe/Dublin")
        py_before = py_datetime(2020, 3, 29, 0, 30, tzinfo=zi)
        assert d_before.tz_abbrev() == py_before.tzname()
        # After spring-forward: 2020-03-29 2:30 (summer, IST)
        d_after = create_zdt(2020, 3, 29, 2, 30, tz="Europe/Dublin")
        py_after = py_datetime(2020, 3, 29, 2, 30, tzinfo=zi)
        assert d_after.tz_abbrev() == py_after.tzname()

    @pytest.mark.skipif(not HAS_TZDATA, reason="tzdata not installed")
    def test_dublin_transition_autumn(self):
        zi = ZoneInfo("Europe/Dublin")
        # Earlier fold: 2020-10-25 1:30 IST
        d_earlier = create_zdt(
            2020, 10, 25, 1, 30, tz="Europe/Dublin", disambiguate="earlier"
        )
        py_earlier = py_datetime(2020, 10, 25, 1, 30, tzinfo=zi, fold=0)
        assert d_earlier.tz_abbrev() == py_earlier.tzname()
        # Later fold: 2020-10-25 1:30 GMT
        d_later = create_zdt(
            2020, 10, 25, 1, 30, tz="Europe/Dublin", disambiguate="later"
        )
        py_later = py_datetime(2020, 10, 25, 1, 30, tzinfo=zi, fold=1)
        assert d_later.tz_abbrev() == py_later.tzname()

    @pytest.mark.skipif(not HAS_TZDATA, reason="tzdata not installed")
    def test_dublin_far_future(self):
        d = create_zdt(2100, 7, 15, 12, tz="Europe/Dublin")
        zi = ZoneInfo("Europe/Dublin")
        py_dt = py_datetime(2100, 7, 15, 12, tzinfo=zi)
        assert d.tz_abbrev() == py_dt.tzname()

        d2 = create_zdt(2100, 1, 15, 12, tz="Europe/Dublin")
        py_dt2 = py_datetime(2100, 1, 15, 12, tzinfo=zi)
        assert d2.tz_abbrev() == py_dt2.tzname()

    # -- Australia/Sydney: southern hemisphere DST --

    @pytest.mark.skipif(not HAS_TZDATA, reason="tzdata not installed")
    def test_sydney_summer(self):
        d = create_zdt(2020, 1, 15, 12, tz="Australia/Sydney")
        zi = ZoneInfo("Australia/Sydney")
        py_dt = py_datetime(2020, 1, 15, 12, tzinfo=zi)
        assert d.tz_abbrev() == py_dt.tzname()

    @pytest.mark.skipif(not HAS_TZDATA, reason="tzdata not installed")
    def test_sydney_winter(self):
        d = create_zdt(2020, 7, 15, 12, tz="Australia/Sydney")
        zi = ZoneInfo("Australia/Sydney")
        py_dt = py_datetime(2020, 7, 15, 12, tzinfo=zi)
        assert d.tz_abbrev() == py_dt.tzname()

    @pytest.mark.skipif(not HAS_TZDATA, reason="tzdata not installed")
    def test_sydney_transition_start(self):
        zi = ZoneInfo("Australia/Sydney")
        # Before DST starts: 2020-10-04 1:30 AEST
        d_before = create_zdt(2020, 10, 4, 1, 30, tz="Australia/Sydney")
        py_before = py_datetime(2020, 10, 4, 1, 30, tzinfo=zi)
        assert d_before.tz_abbrev() == py_before.tzname()
        # After DST starts: 2020-10-04 3:30 AEDT
        d_after = create_zdt(2020, 10, 4, 3, 30, tz="Australia/Sydney")
        py_after = py_datetime(2020, 10, 4, 3, 30, tzinfo=zi)
        assert d_after.tz_abbrev() == py_after.tzname()

    @pytest.mark.skipif(not HAS_TZDATA, reason="tzdata not installed")
    def test_sydney_transition_end(self):
        zi = ZoneInfo("Australia/Sydney")
        # Earlier fold: 2020-04-05 2:30 AEDT
        d_earlier = create_zdt(
            2020, 4, 5, 2, 30, tz="Australia/Sydney", disambiguate="earlier"
        )
        py_earlier = py_datetime(2020, 4, 5, 2, 30, tzinfo=zi, fold=0)
        assert d_earlier.tz_abbrev() == py_earlier.tzname()
        # Later fold: 2020-04-05 2:30 AEST
        d_later = create_zdt(
            2020, 4, 5, 2, 30, tz="Australia/Sydney", disambiguate="later"
        )
        py_later = py_datetime(2020, 4, 5, 2, 30, tzinfo=zi, fold=1)
        assert d_later.tz_abbrev() == py_later.tzname()

    @pytest.mark.skipif(not HAS_TZDATA, reason="tzdata not installed")
    def test_sydney_far_future(self):
        d = create_zdt(2100, 1, 15, 12, tz="Australia/Sydney")
        zi = ZoneInfo("Australia/Sydney")
        py_dt = py_datetime(2100, 1, 15, 12, tzinfo=zi)
        assert d.tz_abbrev() == py_dt.tzname()

    # -- Pacific/Honolulu: no DST --

    @pytest.mark.skipif(not HAS_TZDATA, reason="tzdata not installed")
    def test_honolulu_summer(self):
        d = create_zdt(2020, 7, 15, 12, tz="Pacific/Honolulu")
        zi = ZoneInfo("Pacific/Honolulu")
        py_dt = py_datetime(2020, 7, 15, 12, tzinfo=zi)
        assert d.tz_abbrev() == py_dt.tzname()

    @pytest.mark.skipif(not HAS_TZDATA, reason="tzdata not installed")
    def test_honolulu_winter(self):
        d = create_zdt(2020, 1, 15, 12, tz="Pacific/Honolulu")
        zi = ZoneInfo("Pacific/Honolulu")
        py_dt = py_datetime(2020, 1, 15, 12, tzinfo=zi)
        assert d.tz_abbrev() == py_dt.tzname()

    @pytest.mark.skipif(not HAS_TZDATA, reason="tzdata not installed")
    def test_honolulu_far_future(self):
        d = create_zdt(2100, 6, 15, 12, tz="Pacific/Honolulu")
        zi = ZoneInfo("Pacific/Honolulu")
        py_dt = py_datetime(2100, 6, 15, 12, tzinfo=zi)
        assert d.tz_abbrev() == py_dt.tzname()

    # -- Africa/Casablanca: complex DST --

    @pytest.mark.skipif(
        not HAS_TZDATA
        or "Africa/Casablanca" not in zoneinfo_available_timezones(),
        reason="tzdata or Africa/Casablanca not available",
    )
    def test_casablanca_summer(self):
        d = create_zdt(2019, 7, 15, 12, tz="Africa/Casablanca")
        zi = ZoneInfo("Africa/Casablanca")
        py_dt = py_datetime(2019, 7, 15, 12, tzinfo=zi)
        assert d.tz_abbrev() == py_dt.tzname()

    @pytest.mark.skipif(
        not HAS_TZDATA
        or "Africa/Casablanca" not in zoneinfo_available_timezones(),
        reason="tzdata or Africa/Casablanca not available",
    )
    def test_casablanca_winter(self):
        d = create_zdt(2019, 1, 15, 12, tz="Africa/Casablanca")
        zi = ZoneInfo("Africa/Casablanca")
        py_dt = py_datetime(2019, 1, 15, 12, tzinfo=zi)
        assert d.tz_abbrev() == py_dt.tzname()

    @pytest.mark.skipif(
        not HAS_TZDATA
        or "Africa/Casablanca" not in zoneinfo_available_timezones(),
        reason="tzdata or Africa/Casablanca not available",
    )
    def test_casablanca_far_future(self):
        d = create_zdt(2100, 7, 15, 12, tz="Africa/Casablanca")
        zi = ZoneInfo("Africa/Casablanca")
        py_dt = py_datetime(2100, 7, 15, 12, tzinfo=zi)
        assert d.tz_abbrev() == py_dt.tzname()

    # -- America/New_York: standard US DST --

    def test_new_york_summer(self):
        d = create_zdt(2020, 7, 15, 12, tz="America/New_York")
        zi = ZoneInfo("America/New_York")
        py_dt = py_datetime(2020, 7, 15, 12, tzinfo=zi)
        assert d.tz_abbrev() == py_dt.tzname()

    def test_new_york_winter(self):
        d = create_zdt(2020, 1, 15, 12, tz="America/New_York")
        zi = ZoneInfo("America/New_York")
        py_dt = py_datetime(2020, 1, 15, 12, tzinfo=zi)
        assert d.tz_abbrev() == py_dt.tzname()

    def test_new_york_spring_forward(self):
        zi = ZoneInfo("America/New_York")
        # Before: 2020-03-08 1:30 EST
        d_before = create_zdt(2020, 3, 8, 1, 30, tz="America/New_York")
        py_before = py_datetime(2020, 3, 8, 1, 30, tzinfo=zi)
        assert d_before.tz_abbrev() == py_before.tzname()
        # After: 2020-03-08 3:30 EDT
        d_after = create_zdt(2020, 3, 8, 3, 30, tz="America/New_York")
        py_after = py_datetime(2020, 3, 8, 3, 30, tzinfo=zi)
        assert d_after.tz_abbrev() == py_after.tzname()

    def test_new_york_fall_back(self):
        zi = ZoneInfo("America/New_York")
        # Earlier fold: 2020-11-01 1:30 EDT
        d_earlier = create_zdt(
            2020, 11, 1, 1, 30, tz="America/New_York", disambiguate="earlier"
        )
        py_earlier = py_datetime(2020, 11, 1, 1, 30, tzinfo=zi, fold=0)
        assert d_earlier.tz_abbrev() == py_earlier.tzname()
        # Later fold: 2020-11-01 1:30 EST
        d_later = create_zdt(
            2020, 11, 1, 1, 30, tz="America/New_York", disambiguate="later"
        )
        py_later = py_datetime(2020, 11, 1, 1, 30, tzinfo=zi, fold=1)
        assert d_later.tz_abbrev() == py_later.tzname()

    def test_new_york_far_future(self):
        d = create_zdt(2100, 7, 15, 12, tz="America/New_York")
        zi = ZoneInfo("America/New_York")
        py_dt = py_datetime(2100, 7, 15, 12, tzinfo=zi)
        assert d.tz_abbrev() == py_dt.tzname()

        d2 = create_zdt(2100, 1, 15, 12, tz="America/New_York")
        py_dt2 = py_datetime(2100, 1, 15, 12, tzinfo=zi)
        assert d2.tz_abbrev() == py_dt2.tzname()

    # -- UTC: always UTC --

    def test_utc_cross_validate(self):
        d = create_zdt(2020, 7, 15, 12, tz="UTC")
        zi = ZoneInfo("UTC")
        py_dt = py_datetime(2020, 7, 15, 12, tzinfo=zi)
        assert d.tz_abbrev() == py_dt.tzname()

    def test_utc_far_future(self):
        d = create_zdt(2100, 7, 15, 12, tz="UTC")
        assert d.tz_abbrev() == "UTC"

    # -- Asia/Tokyo: no DST, always JST --

    def test_tokyo_summer(self):
        d = create_zdt(2020, 7, 15, 12, tz="Asia/Tokyo")
        zi = ZoneInfo("Asia/Tokyo")
        py_dt = py_datetime(2020, 7, 15, 12, tzinfo=zi)
        assert d.tz_abbrev() == py_dt.tzname()

    def test_tokyo_winter(self):
        d = create_zdt(2020, 1, 15, 12, tz="Asia/Tokyo")
        zi = ZoneInfo("Asia/Tokyo")
        py_dt = py_datetime(2020, 1, 15, 12, tzinfo=zi)
        assert d.tz_abbrev() == py_dt.tzname()

    def test_tokyo_far_future(self):
        d = create_zdt(2100, 7, 15, 12, tz="Asia/Tokyo")
        zi = ZoneInfo("Asia/Tokyo")
        py_dt = py_datetime(2100, 7, 15, 12, tzinfo=zi)
        assert d.tz_abbrev() == py_dt.tzname()


class TestDayLength:
    @pytest.mark.parametrize(
        "d, expect",
        [
            # no special day
            (
                ZonedDateTime(2020, 8, 15, 12, 8, 30, tz="Europe/Amsterdam"),
                hours(24),
            ),
            (ZonedDateTime(1832, 12, 15, 12, 1, 30, tz="UTC"), hours(24)),
            # Longer day
            (
                ZonedDateTime(2023, 10, 29, 12, 8, 30, tz="Europe/Amsterdam"),
                hours(25),
            ),
            (
                create_zdt(2023, 10, 29, 12, 8, 30, tz=AMS_TZ_POSIX),
                hours(25),
            ),
            (ZonedDateTime(2023, 10, 29, tz="Europe/Amsterdam"), hours(25)),
            (
                ZonedDateTime(2023, 10, 30, tz="Europe/Amsterdam").subtract(
                    nanoseconds=1
                ),
                hours(25),
            ),
            # Shorter day
            (
                ZonedDateTime(2023, 3, 26, 12, 8, 30, tz="Europe/Amsterdam"),
                hours(23),
            ),
            (ZonedDateTime(2023, 3, 26, tz="Europe/Amsterdam"), hours(23)),
            (
                ZonedDateTime(2023, 3, 27, tz="Europe/Amsterdam").subtract(
                    nanoseconds=1
                ),
                hours(23),
            ),
            # non-hour DST change
            (
                ZonedDateTime(2024, 10, 6, 1, tz="Australia/Lord_Howe"),
                hours(23.5),
            ),
            (
                ZonedDateTime(2024, 4, 7, 1, tz="Australia/Lord_Howe"),
                hours(24.5),
            ),
            # Non-regular transition
            (
                ZonedDateTime(1894, 6, 1, 1, tz="Europe/Zurich"),
                TimeDelta(hours=24, minutes=-30, seconds=-14),
            ),
            # DST starts at midnight
            (ZonedDateTime(2016, 2, 20, tz="America/Sao_Paulo"), hours(25)),
            (ZonedDateTime(2016, 2, 21, tz="America/Sao_Paulo"), hours(24)),
            (ZonedDateTime(2016, 10, 16, tz="America/Sao_Paulo"), hours(23)),
            (ZonedDateTime(2016, 10, 17, tz="America/Sao_Paulo"), hours(24)),
            # Samoa skipped a day
            (ZonedDateTime(2011, 12, 31, 21, tz="Pacific/Apia"), hours(24)),
            (ZonedDateTime(2011, 12, 29, 21, tz="Pacific/Apia"), hours(24)),
            # A day that starts twice
            (
                ZonedDateTime(
                    2016,
                    2,
                    20,
                    23,
                    45,
                    disambiguate="later",
                    tz="America/Sao_Paulo",
                ),
                hours(25),
            ),
            (
                ZonedDateTime(
                    2016,
                    2,
                    20,
                    23,
                    45,
                    disambiguate="earlier",
                    tz="America/Sao_Paulo",
                ),
                hours(25),
            ),
        ],
    )
    def test_typical(self, d: ZonedDateTime, expect: TimeDelta):
        assert d.day_length() == expect

    def test_extreme_bounds(self):
        # Negative UTC offsets at lower bound are fine
        d_min_neg = ZonedDateTime(1, 1, 1, 2, tz="America/New_York")
        assert d_min_neg.day_length() == hours(24)

        # Positive UTC offsets at lower bound are NOT fine
        d_min_pos = ZonedDateTime(1, 1, 1, 12, tz="Asia/Tokyo")
        with pytest.raises((ValueError, OverflowError), match="range|year"):
            d_min_pos.day_length()

        # upper bound is NOT fine
        d_max_pos = ZonedDateTime(9999, 12, 31, 4, tz="Asia/Tokyo")
        with pytest.raises((ValueError, OverflowError), match="range|year"):
            d_max_pos.day_length()

        d_max_neg = ZonedDateTime(9999, 12, 31, 12, tz="America/New_York")
        with pytest.raises((ValueError, OverflowError), match="range|year"):
            d_max_neg.day_length()


class TestStartOfDay:

    @pytest.mark.parametrize(
        "d, expect",
        [
            # no special day
            (
                ZonedDateTime(2020, 8, 15, 12, 8, 30, tz="Europe/Amsterdam"),
                ZonedDateTime(2020, 8, 15, tz="Europe/Amsterdam"),
            ),
            (
                create_zdt(2020, 8, 15, 12, 8, 30, tz=AMS_TZ_POSIX),
                create_zdt(2020, 8, 15, tz=AMS_TZ_POSIX),
            ),
            (
                ZonedDateTime(1832, 12, 15, 12, 1, 30, tz="UTC"),
                ZonedDateTime(1832, 12, 15, tz="UTC"),
            ),
            # DST at non-midnight
            (
                ZonedDateTime(2023, 10, 29, 12, 8, 30, tz="Europe/Amsterdam"),
                ZonedDateTime(2023, 10, 29, tz="Europe/Amsterdam"),
            ),
            (
                ZonedDateTime(2023, 3, 26, 12, 8, 30, tz="Europe/Amsterdam"),
                ZonedDateTime(2023, 3, 26, tz="Europe/Amsterdam"),
            ),
            (
                create_zdt(2023, 3, 26, 12, 8, 30, tz=AMS_TZ_RAWFILE),
                create_zdt(2023, 3, 26, tz=AMS_TZ_RAWFILE),
            ),
            (
                ZonedDateTime(2024, 4, 7, 1, tz="Australia/Lord_Howe"),
                ZonedDateTime(2024, 4, 7, tz="Australia/Lord_Howe"),
            ),
            # Non-regular transition
            (
                ZonedDateTime(1894, 6, 1, 1, tz="Europe/Zurich"),
                ZonedDateTime(1894, 6, 1, 0, 30, 14, tz="Europe/Zurich"),
            ),
            # DST starts at midnight
            (
                ZonedDateTime(2016, 2, 20, 8, tz="America/Sao_Paulo"),
                ZonedDateTime(2016, 2, 20, tz="America/Sao_Paulo"),
            ),
            (
                ZonedDateTime(2016, 2, 21, 2, tz="America/Sao_Paulo"),
                ZonedDateTime(2016, 2, 21, tz="America/Sao_Paulo"),
            ),
            (
                ZonedDateTime(2016, 10, 16, 15, tz="America/Sao_Paulo"),
                ZonedDateTime(2016, 10, 16, 1, tz="America/Sao_Paulo"),
            ),
            (
                ZonedDateTime(2016, 10, 17, 19, tz="America/Sao_Paulo"),
                ZonedDateTime(2016, 10, 17, tz="America/Sao_Paulo"),
            ),
            # Samoa skipped a day
            (
                ZonedDateTime(2011, 12, 31, 21, tz="Pacific/Apia"),
                ZonedDateTime(2011, 12, 31, tz="Pacific/Apia"),
            ),
            (
                ZonedDateTime(2011, 12, 29, 21, tz="Pacific/Apia"),
                ZonedDateTime(2011, 12, 29, tz="Pacific/Apia"),
            ),
            # Another edge case
            (
                ZonedDateTime(2010, 11, 7, 23, tz="America/St_Johns"),
                ZonedDateTime(
                    2010, 11, 7, tz="America/St_Johns", disambiguate="earlier"
                ),
            ),
            # a day that starts twice
            (
                ZonedDateTime(
                    2016,
                    2,
                    20,
                    23,
                    45,
                    disambiguate="later",
                    tz="America/Sao_Paulo",
                ),
                ZonedDateTime(
                    2016, 2, 20, tz="America/Sao_Paulo", disambiguate="raise"
                ),
            ),
        ],
    )
    def test_examples(self, d: ZonedDateTime, expect):
        assert d.start_of_day().exact_eq(expect)

    def test_extreme_boundaries(self):
        # Negative UTC offsets at lower bound are fine
        assert (
            ZonedDateTime(1, 1, 1, 2, tz="America/New_York")
            .start_of_day()
            .exact_eq(ZonedDateTime(1, 1, 1, tz="America/New_York"))
        )

        # Positive UTC offsets at lower bound are NOT fine
        d_max_pos = ZonedDateTime(1, 1, 1, 12, tz="Asia/Tokyo")
        with pytest.raises((ValueError, OverflowError), match="range"):
            d_max_pos.start_of_day()

        # Upper bound is always fine
        assert (
            ZonedDateTime(9999, 12, 31, 23, tz="Asia/Tokyo")
            .start_of_day()
            .exact_eq(ZonedDateTime(9999, 12, 31, tz="Asia/Tokyo"))
        )

        assert (
            ZonedDateTime(9999, 12, 31, 12, tz="America/New_York")
            .start_of_day()
            .exact_eq(ZonedDateTime(9999, 12, 31, tz="America/New_York"))
        )

    def test_deprecation_warning(self):
        zdt = ZonedDateTime(2024, 8, 15, 14, tz="America/New_York")
        with pytest.warns(WheneverDeprecationWarning, match="start_of_day"):
            zdt.start_of_day()


@pytest.mark.parametrize(
    "tz",
    ["Europe/Amsterdam", AMS_TZ_POSIX, AMS_TZ_RAWFILE],
)
def test_instant(tz: str):
    assert (
        create_zdt(2020, 8, 15, 12, 8, 30, tz=tz)
        .to_instant()
        .exact_eq(Instant.from_utc(2020, 8, 15, 10, 8, 30))
    )
    d = create_zdt(
        2023,
        10,
        29,
        2,
        15,
        30,
        tz=tz,
        disambiguate="earlier",
    )
    assert d.to_instant().exact_eq(Instant.from_utc(2023, 10, 29, 0, 15, 30))
    assert (
        create_zdt(
            2023,
            10,
            29,
            2,
            15,
            30,
            tz=tz,
            disambiguate="later",
        )
        .to_instant()
        .exact_eq(Instant.from_utc(2023, 10, 29, 1, 15, 30))
    )


@pytest.mark.parametrize(
    "ams_tz",
    ["Europe/Amsterdam", AMS_TZ_POSIX, AMS_TZ_RAWFILE],
)
def test_to_tz(ams_tz: str):
    # unambiguous time
    assert (
        create_zdt(2020, 8, 15, 12, 8, 30, tz=ams_tz)
        .to_tz("America/New_York")
        .exact_eq(ZonedDateTime(2020, 8, 15, 6, 8, 30, tz="America/New_York"))
    )
    ams = ZonedDateTime(
        2023, 10, 29, 2, 15, 30, tz="Europe/Paris", disambiguate="earlier"
    )
    nyc = ZonedDateTime(2023, 10, 28, 20, 15, 30, tz="America/New_York")
    assert ams.to_tz("America/New_York").exact_eq(nyc)
    assert (
        ams.replace(disambiguate="later")
        .to_tz("America/New_York")
        .exact_eq(nyc.replace(hour=21, disambiguate="raise"))
    )
    assert nyc.to_tz("Europe/Paris").exact_eq(ams)
    assert (
        nyc.replace(hour=21, disambiguate="raise")
        .to_tz("Europe/Paris")
        .exact_eq(ams.replace(disambiguate="later"))
    )
    # disambiguation doesn't affect NYC time because there's no ambiguity
    assert (
        nyc.replace(disambiguate="later").to_tz("Europe/Paris").exact_eq(ams)
    )

    # catch local time sliding out of range
    small_zdt = ZonedDateTime(1, 1, 1, tz="Etc/UTC")
    with pytest.raises((ValueError, OverflowError, OSError)):
        small_zdt.to_tz("America/New_York")

    big_zdt = ZonedDateTime(9999, 12, 31, 23, tz="Etc/UTC")
    with pytest.raises((ValueError, OverflowError, OSError)):
        big_zdt.to_tz("Asia/Tokyo")


@pytest.mark.parametrize(
    "tz",
    ["Europe/Amsterdam", AMS_TZ_POSIX, AMS_TZ_RAWFILE],
)
def test_to_fixed_offset(tz: str):
    d = create_zdt(2020, 8, 15, 12, 8, 30, tz=tz)

    assert d.to_fixed_offset().exact_eq(
        OffsetDateTime(2020, 8, 15, 12, 8, 30, offset=hours(2))
    )
    assert (
        d.replace(month=1, disambiguate="raise")
        .to_fixed_offset()
        .exact_eq(OffsetDateTime(2020, 1, 15, 12, 8, 30, offset=hours(1)))
    )
    assert (
        d.replace(month=1, disambiguate="raise")
        .to_fixed_offset(hours(4))
        .exact_eq(OffsetDateTime(2020, 1, 15, 15, 8, 30, offset=hours(4)))
    )
    assert d.to_fixed_offset(hours(0)).exact_eq(
        OffsetDateTime(2020, 8, 15, 10, 8, 30, offset=hours(0))
    )
    assert d.to_fixed_offset(-4).exact_eq(
        OffsetDateTime(2020, 8, 15, 6, 8, 30, offset=hours(-4))
    )

    # catch local time sliding out of range
    small_zdt = ZonedDateTime(1, 1, 1, tz="Etc/UTC")
    with pytest.raises((ValueError, OverflowError), match="range|year"):
        small_zdt.to_fixed_offset(-3)

    big_zdt = ZonedDateTime(9999, 12, 31, 23, tz="Etc/UTC")
    with pytest.raises((ValueError, OverflowError), match="range|year"):
        big_zdt.to_fixed_offset(4)


@system_tz_ams()
def test_to_system_tz():
    d = ZonedDateTime(2023, 10, 28, 2, 15, tz="Europe/Amsterdam")
    assert d.to_system_tz().exact_eq(
        ZonedDateTime(2023, 10, 28, 2, 15, tz="Europe/Amsterdam")
    )
    assert (
        d.replace(day=29, disambiguate="later")
        .to_system_tz()
        .exact_eq(
            ZonedDateTime(
                2023,
                10,
                29,
                2,
                15,
                disambiguate="later",
                tz="Europe/Amsterdam",
            )
        )
    )

    # posix tz
    with system_tz(AMS_TZ_POSIX):
        assert d.to_system_tz().exact_eq(
            create_zdt(2023, 10, 28, 2, 15, tz=AMS_TZ_POSIX)
        )

    # filepath
    with system_tz(AMS_TZ_RAWFILE):
        assert d.to_system_tz().exact_eq(
            create_zdt(2023, 10, 28, 2, 15, tz=AMS_TZ_RAWFILE)
        )

    # colon prefix
    with system_tz(":America/New_York"):
        assert d.to_system_tz().exact_eq(
            ZonedDateTime(2023, 10, 27, 20, 15, tz="America/New_York")
        )

    # catch local time sliding out of range
    small_zdt = ZonedDateTime(1, 1, 1, tz="Etc/UTC")
    with system_tz_nyc():
        with pytest.raises((ValueError, OverflowError), match="range|year"):
            small_zdt.to_system_tz()

    big_zdt = ZonedDateTime(9999, 12, 31, 23, tz="Etc/UTC")
    with pytest.raises((ValueError, OverflowError), match="range|year"):
        big_zdt.to_system_tz()


class TestParseIso:
    @pytest.mark.parametrize(
        "s, expect",
        [
            (
                "2020-08-15T12:08:30+02:00[Europe/Amsterdam]",
                ZonedDateTime(2020, 8, 15, 12, 8, 30, tz="Europe/Amsterdam"),
            ),
            (
                "2020-08-15T12:08:30Z[Iceland]",
                ZonedDateTime(2020, 8, 15, 12, 8, 30, tz="Iceland"),
            ),
            # fractions
            (
                "2020-08-15T12:08:30.02320+02:00[Europe/Amsterdam]",
                ZonedDateTime(
                    2020,
                    8,
                    15,
                    12,
                    8,
                    30,
                    nanosecond=23_200_000,
                    tz="Europe/Amsterdam",
                ),
            ),
            (
                "2020-08-15T12:08:30,02320+02:00[Europe/Amsterdam]",
                ZonedDateTime(
                    2020,
                    8,
                    15,
                    12,
                    8,
                    30,
                    nanosecond=23_200_000,
                    tz="Europe/Amsterdam",
                ),
            ),
            (
                "2020-08-15T12:08:30.000000001+02:00[Europe/Berlin]",
                ZonedDateTime(
                    2020, 8, 15, 12, 8, 30, nanosecond=1, tz="Europe/Berlin"
                ),
            ),
            # second-level offset
            (
                "1900-01-01T23:34:39.01-00:25:21[Europe/Dublin]",
                ZonedDateTime(
                    1900,
                    1,
                    1,
                    23,
                    34,
                    39,
                    nanosecond=10_000_000,
                    tz="Europe/Dublin",
                ),
            ),
            (
                "2020-08-15T12:08:30+02:00:00[Europe/Berlin]",
                ZonedDateTime(2020, 8, 15, 12, 8, 30, tz="Europe/Berlin"),
            ),
            # offset disambiguates
            (
                "2023-10-29T02:15:30+01:00[Europe/Amsterdam]",
                ZonedDateTime(
                    2023,
                    10,
                    29,
                    2,
                    15,
                    30,
                    tz="Europe/Amsterdam",
                    disambiguate="later",
                ),
            ),
            (
                "2023-10-29T02:15:30+02:00[Europe/Amsterdam]",
                ZonedDateTime(
                    2023,
                    10,
                    29,
                    2,
                    15,
                    30,
                    tz="Europe/Amsterdam",
                    disambiguate="earlier",
                ),
            ),
            # Offsets are optional
            (
                "2023-08-25T12:15:30[Europe/Amsterdam]",
                ZonedDateTime(2023, 8, 25, 12, 15, 30, tz="Europe/Amsterdam"),
            ),
            # no offset for skipped time
            (
                "2023-03-26T02:15:30[Europe/Amsterdam]",
                ZonedDateTime(
                    2023,
                    3,
                    26,
                    2,
                    15,
                    30,
                    tz="Europe/Amsterdam",
                    disambiguate="compatible",
                ),
            ),
            # Alternate formats
            (
                "20200815 12:08:30+02:00[Europe/Amsterdam]",
                ZonedDateTime(2020, 8, 15, 12, 8, 30, tz="Europe/Amsterdam"),
            ),
            (
                "2020-02-15t120830z[Europe/London]",
                ZonedDateTime(2020, 2, 15, 12, 8, 30, tz="Europe/London"),
            ),
            (
                "2020-08-15T12:08:30+02[Europe/Amsterdam]",
                ZonedDateTime(2020, 8, 15, 12, 8, 30, tz="Europe/Amsterdam"),
            ),
            # Z is also valid for non-0 offset timezones!
            (
                "2020-02-15t120830z[America/New_York]",
                ZonedDateTime(2020, 2, 15, 7, 8, 30, tz="America/New_York"),
            ),
            (
                "19000101 00-002521[Europe/Dublin]",
                ZDT2,
            ),
        ],
    )
    def test_valid(self, s, expect):
        assert ZonedDateTime.parse_iso(s).exact_eq(expect)

    @pytest.mark.parametrize(
        "s",
        [
            "2020-08-15T12:08:30+02:00",  # no tz
            # bracket problems
            "2020-08-15T12:08:30+02:00[Europe/Amsterdam",
            "2020-08-15T12:08:30+02:00[Europe][Amsterdam]",
            "2020-08-15T12:08:30+02:00Europe/Amsterdam]",
            "2023-10-29T02:15:30+02:00(Europe/Amsterdam)",
            # separator problems
            "2020-08-15_12:08:30+02:00[Europe/Amsterdam]",
            "2020-08-15T12.08:30+02:00[Europe/Amsterdam]",
            "2020_08-15T12:08:30+02:00[Europe/Amsterdam]",
            # padding problems
            "2020-08-15T12:8:30+02:00[Europe/Amsterdam]",
            # invalid values
            "2020-08-32T12:08:30+02:00[Europe/Amsterdam]",
            "2020-08-12T12:68:30+02:00[Europe/Amsterdam]",
            "2020-08-12T12:68:30+99:00[Europe/Amsterdam]",
            "2020-08-12T12:68:30+14:89[Europe/Amsterdam]",
            "2020-08-12T12:68:30+01:00[Europe/Amsterdam]",
            "2020-08-12T12:68:30+14:29:60[Europe/Amsterdam]",
            "2023-10-29T02:15:30>02:00[Europe/Amsterdam]",
            "2020-08-15T12:08:30+015960[Europe/Amsterdam]",
            # trailing/leading space
            " 2023-10-29T02:15:30+02:00[Europe/Amsterdam]",
            "2023-10-29T02:15:30+02:00[Europe/Amsterdam] ",
            # invalid offsets
            "1900-01-01T23:34:39.01-00:24:81[Europe/Dublin]",
            "2020-01-01T00:00:00+04:90[Asia/Calcutta]",
            "2023-10-29",  # only date
            "02:15:30",  # only time
            "2023-10-29T02:15:30",  # no offset
            "",  # empty
            "garbage",  # garbage
            "2023-10-29T02:15:30.0000000001+02:00[Europe/Amsterdam]",  # overly precise fraction
            "2023-10-29T02:15:30+02:00:00.00[Europe/Amsterdam]",  # subsecond offset
            "2023-10-29T02:15:30+0𝟙:00[Europe/Amsterdam]",
            "2020-08-15T12:08:30.000000001+29:00[Europe/Berlin]",  # out of range offset
            # decimal problems
            "2020-08-15T12:08:30.+02:00[Europe/Paris]",
            "2020-08-15T12:08:30. +02:00[Europe/Paris]",
            "2020-08-15T12:08:30,+02:00[Europe/Paris]",
            "2020-08-15T12:08:30,Z[Europe/Paris]",
        ],
    )
    def test_invalid(self, s):
        with pytest.raises(ValueError, match="format.*" + re.escape(s)):
            ZonedDateTime.parse_iso(s)

    def test_invalid_tz(self):
        with pytest.raises(TimeZoneNotFoundError):
            ZonedDateTime.parse_iso(
                "2020-08-15T12:08:30+02:00[Europe/Nowhere]"
            )

        with pytest.raises(TimeZoneNotFoundError):
            ZonedDateTime.parse_iso("2020-08-15T12:08:30Z[X]")

        with pytest.raises((TimeZoneNotFoundError, ValueError)):
            ZonedDateTime.parse_iso(f"2023-10-29T02:15:30+02:00[{'X'*9999}]")

        with pytest.raises((TimeZoneNotFoundError, ValueError)):
            ZonedDateTime.parse_iso(
                f"2023-10-29T02:15:30+02:00[{chr(1600)}]",
            )

        assert issubclass(TimeZoneNotFoundError, ValueError)

    @pytest.mark.parametrize(
        "s",
        [
            "0001-01-01T00:15:30+09:00[Etc/GMT-9]",
            "9999-12-31T20:15:30-09:00[Etc/GMT+9]",
            "9999-12-31T20:15:30Z[Asia/Tokyo]",
            "0001-01-01T00:15:30Z[America/New_York]",
        ],
    )
    def test_out_of_range(self, s):
        with pytest.raises((ValueError, OverflowError), match="range|year"):
            ZonedDateTime.parse_iso(s)

    def test_offset_timezone_mismatch(self):
        with pytest.raises(InvalidOffsetError):
            # at the exact DST transition
            ZonedDateTime.parse_iso(
                "2023-10-29T02:15:30+03:00[Europe/Amsterdam]"
            )
        with pytest.raises(InvalidOffsetError):
            # some other time in the year
            ZonedDateTime.parse_iso(
                "2020-08-15T12:08:30+01:00:01[Europe/Amsterdam]"
            )

        with pytest.raises(InvalidOffsetError):
            # some other time in the year
            ZonedDateTime.parse_iso(
                "2020-08-15T12:08:30+00:00[Europe/Amsterdam]"
            )

        assert issubclass(InvalidOffsetError, ValueError)

    def test_skipped_time(self):
        with pytest.raises(InvalidOffsetError):
            ZonedDateTime.parse_iso(
                "2023-03-26T02:15:30+01:00[Europe/Amsterdam]"
            )

    @given(text())
    def test_fuzzing(self, s: str):
        with pytest.raises(
            ValueError,
            match=r"Invalid format.*" + re.escape(repr(s)),
        ):
            ZonedDateTime.parse_iso(s)


class TestTimestamp:

    def test_default_seconds(self):
        assert ZonedDateTime(1970, 1, 1, tz="Iceland").timestamp() == 0
        assert (
            ZonedDateTime(
                2020, 8, 15, 8, 8, 30, nanosecond=45_123, tz="America/New_York"
            ).timestamp()
            == 1_597_493_310
        )

        ambiguous = ZonedDateTime(
            2023,
            10,
            29,
            2,
            15,
            30,
            tz="Europe/Amsterdam",
            disambiguate="earlier",
        )
        assert (
            ambiguous.timestamp()
            != ambiguous.replace(disambiguate="later").timestamp()
        )

    def test_millis(self):
        assert ZonedDateTime(1970, 1, 1, tz="Iceland").timestamp_millis() == 0
        assert (
            ZonedDateTime(
                2020,
                8,
                15,
                8,
                8,
                30,
                nanosecond=45_923_789,
                tz="America/New_York",
            ).timestamp_millis()
            == 1_597_493_310_045
        )

        ambiguous = ZonedDateTime(
            2023,
            10,
            29,
            2,
            15,
            30,
            tz="Europe/Amsterdam",
            disambiguate="earlier",
        )
        assert (
            ambiguous.timestamp_millis()
            != ambiguous.replace(disambiguate="later").timestamp_millis()
        )

    def test_nanos(self):
        assert ZonedDateTime(1970, 1, 1, tz="Iceland").timestamp_nanos() == 0
        assert (
            ZonedDateTime(
                2020,
                8,
                15,
                8,
                8,
                30,
                nanosecond=45_123_789,
                tz="America/New_York",
            ).timestamp_nanos()
            == 1_597_493_310_045_123_789
        )

        ambiguous = ZonedDateTime(
            2023,
            10,
            29,
            2,
            15,
            30,
            tz="Europe/Amsterdam",
            disambiguate="earlier",
        )
        assert (
            ambiguous.timestamp_nanos()
            != ambiguous.replace(disambiguate="later").timestamp_nanos()
        )


class TestFromTimestamp:

    @pytest.mark.parametrize(
        "method, factor",
        [
            (ZonedDateTime.from_timestamp, 1),
            (ZonedDateTime.from_timestamp_millis, 1_000),
            (ZonedDateTime.from_timestamp_nanos, 1_000_000_000),
        ],
    )
    def test_all(self, method, factor):
        assert method(0, tz="Iceland").exact_eq(
            ZonedDateTime(1970, 1, 1, tz="Iceland")
        )
        assert method(1_597_493_310 * factor, tz="America/Nuuk").exact_eq(
            ZonedDateTime(2020, 8, 15, 10, 8, 30, tz="America/Nuuk")
        )
        with pytest.raises((OSError, OverflowError, ValueError)):
            method(1_000_000_000_000_000_000 * factor, tz="America/Nuuk")

        with pytest.raises((OSError, OverflowError, ValueError)):
            method(-1_000_000_000_000_000_000 * factor, tz="America/Nuuk")

        with pytest.raises((TypeError, AttributeError)):
            method(0, tz=3)

        with pytest.raises(TypeError):
            method("0", tz="America/New_York")

        with pytest.raises(TimeZoneNotFoundError):
            method(0, tz="America/Nowhere")

        with pytest.raises(TypeError, match="got 3|foo"):
            method(0, tz="America/New_York", foo="bar")

        with pytest.raises(TypeError, match="positional|ts"):
            method(ts=0, tz="America/New_York")

        with pytest.raises(TypeError):
            method(0, foo="bar")

        with pytest.raises(TypeError):
            method(0)

        with pytest.raises(TypeError):
            method(0, "bar")

        assert ZonedDateTime.from_timestamp_millis(
            -4, tz="America/Nuuk"
        ).to_instant() == Instant.from_timestamp(0) - milliseconds(4)

        assert ZonedDateTime.from_timestamp_nanos(
            -4, tz="America/Nuuk"
        ).to_instant() == Instant.from_timestamp(0).subtract(nanoseconds=4)

    def test_nanos(self):
        assert ZonedDateTime.from_timestamp_nanos(
            1_597_493_310_123_456_789, tz="America/Nuuk"
        ).exact_eq(
            ZonedDateTime(
                2020,
                8,
                15,
                10,
                8,
                30,
                nanosecond=123_456_789,
                tz="America/Nuuk",
            )
        )

    def test_millis(self):
        assert ZonedDateTime.from_timestamp_millis(
            1_597_493_310_123, tz="America/Nuuk"
        ).exact_eq(
            ZonedDateTime(
                2020,
                8,
                15,
                10,
                8,
                30,
                nanosecond=123_000_000,
                tz="America/Nuuk",
            )
        )

    def test_float(self):
        assert ZonedDateTime.from_timestamp(
            1.0,
            tz="America/New_York",
        ).exact_eq(
            ZonedDateTime.from_timestamp(
                1,
                tz="America/New_York",
            )
        )

        assert ZonedDateTime.from_timestamp(
            1.000_000_001,
            tz="America/New_York",
        ).exact_eq(
            ZonedDateTime.from_timestamp(
                1,
                tz="America/New_York",
            ).add(
                nanoseconds=1,
            )
        )

        assert ZonedDateTime.from_timestamp(
            -9.000_000_100,
            tz="America/New_York",
        ).exact_eq(
            ZonedDateTime.from_timestamp(
                -9,
                tz="America/New_York",
            ).subtract(
                nanoseconds=100,
            )
        )

        with pytest.raises((ValueError, OverflowError)):
            ZonedDateTime.from_timestamp(9e200, tz="America/New_York")

        with pytest.raises((ValueError, OverflowError, OSError)):
            ZonedDateTime.from_timestamp(
                float(Instant.MAX.timestamp()) + 0.99999999,
                tz="America/New_York",
            )

        with pytest.raises((ValueError, OverflowError)):
            ZonedDateTime.from_timestamp(float("inf"), tz="America/New_York")

        with pytest.raises((ValueError, OverflowError)):
            ZonedDateTime.from_timestamp(float("nan"), tz="America/New_York")


@pytest.mark.parametrize(
    "d, expect",
    [
        (
            ZonedDateTime(
                2020,
                8,
                15,
                23,
                12,
                9,
                nanosecond=9_876_543,
                tz="Australia/Darwin",
            ),
            'ZonedDateTime("2020-08-15 23:12:09.009876543+09:30[Australia/Darwin]")',
        ),
        (
            ZonedDateTime(2020, 8, 15, 23, 12, tz="Iceland"),
            'ZonedDateTime("2020-08-15 23:12:00+00:00[Iceland]")',
        ),
        (
            ZonedDateTime(2020, 8, 15, 23, 12, tz="UTC"),
            'ZonedDateTime("2020-08-15 23:12:00+00:00[UTC]")',
        ),
        (
            create_zdt(2020, 8, 15, 12, 8, 30, tz=AMS_TZ_POSIX),
            'ZonedDateTime("2020-08-15 12:08:30+02:00[<system timezone without ID>]")',
        ),
        (
            create_zdt(2020, 8, 15, 12, 8, 30, tz=AMS_TZ_RAWFILE),
            'ZonedDateTime("2020-08-15 12:08:30+02:00[<system timezone without ID>]")',
        ),
    ],
)
def test_repr(d: ZonedDateTime, expect: str):
    assert repr(d) == expect


class TestComparison:
    @pytest.mark.parametrize(
        "tz",
        ["Europe/Amsterdam", AMS_TZ_POSIX, AMS_TZ_RAWFILE],
    )
    def test_different_timezones(self, tz: str):
        d = ZonedDateTime(2020, 8, 15, 15, 12, 9, tz="Asia/Kolkata")
        later = create_zdt(2020, 8, 15, 14, tz=tz)

        assert d < later
        assert d <= later
        assert later > d
        assert later >= d
        assert not d > later
        assert not d >= later
        assert not later < d
        assert not later <= d

    @pytest.mark.parametrize(
        "tz",
        ["Europe/Amsterdam", AMS_TZ_POSIX, AMS_TZ_RAWFILE],
    )
    def test_same_timezone_ambiguity(self, tz: str):
        d = create_zdt(
            2023,
            10,
            29,
            2,
            15,
            30,
            tz=tz,
            disambiguate="earlier",
        )
        later = create_zdt(
            2023,
            10,
            29,
            2,
            15,
            30,
            tz=tz,
            disambiguate="later",
        )
        assert d < later
        assert d <= later
        assert later > d
        assert later >= d
        assert not d > later
        assert not d >= later
        assert not later < d
        assert not later <= d

    @pytest.mark.parametrize(
        "tz",
        ["Europe/Amsterdam", AMS_TZ_POSIX, AMS_TZ_RAWFILE],
    )
    def test_different_timezone_same_time(self, tz: str):
        d = create_zdt(
            2023,
            10,
            29,
            2,
            15,
            30,
            tz=tz,
            disambiguate="earlier",
        )
        other = d.to_tz("America/New_York")
        assert not d < other
        assert d <= other
        assert not other > d
        assert other >= d
        assert not d > other
        assert d >= other
        assert not other < d
        assert other <= d

    @pytest.mark.parametrize(
        "tz",
        ["Europe/Amsterdam", AMS_TZ_POSIX, AMS_TZ_RAWFILE],
    )
    def test_instant(self, tz: str):
        d = create_zdt(2023, 10, 29, 2, 30, tz=tz, disambiguate="later")

        inst_eq = d.to_instant()
        inst_lt = inst_eq - minutes(1)
        inst_gt = inst_eq + minutes(1)

        assert d >= inst_eq
        assert d <= inst_eq
        assert not d > inst_eq
        assert not d < inst_eq

        assert d > inst_lt
        assert d >= inst_lt
        assert not d < inst_lt
        assert not d <= inst_lt

        assert d < inst_gt
        assert d <= inst_gt
        assert not d > inst_gt
        assert not d >= inst_gt

    @pytest.mark.parametrize(
        "tz",
        ["Europe/Amsterdam", AMS_TZ_POSIX, AMS_TZ_RAWFILE],
    )
    def test_offset(self, tz: str):
        d = create_zdt(2023, 10, 29, 2, 30, tz=tz, disambiguate="later")

        offset_eq = d.to_fixed_offset()
        with suppress(PotentiallyStaleOffsetWarning):
            offset_lt = offset_eq.replace(minute=29)
            offset_gt = offset_eq.replace(minute=31)

        assert d >= offset_eq
        assert d <= offset_eq
        assert not d > offset_eq
        assert not d < offset_eq

        assert d > offset_lt
        assert d >= offset_lt
        assert not d < offset_lt
        assert not d <= offset_lt

        assert d < offset_gt
        assert d <= offset_gt
        assert not d > offset_gt
        assert not d >= offset_gt

    @pytest.mark.parametrize(
        "tz",
        ["Europe/Amsterdam", AMS_TZ_POSIX, AMS_TZ_RAWFILE],
    )
    def test_system_tz(self, tz: str):
        d = create_zdt(2023, 10, 29, 2, 30, tz=tz, disambiguate="earlier")

        sys_eq = d.to_system_tz()
        sys_lt = sys_eq.replace(minute=29, disambiguate="earlier")
        sys_gt = sys_eq.replace(minute=31, disambiguate="earlier")

        assert d >= sys_eq
        assert d <= sys_eq
        assert not d > sys_eq
        assert not d < sys_eq

        assert d > sys_lt
        assert d >= sys_lt
        assert not d < sys_lt
        assert not d <= sys_lt

        assert d < sys_gt
        assert d <= sys_gt
        assert not d > sys_gt
        assert not d >= sys_gt

    @pytest.mark.parametrize(
        "tz",
        ["Europe/Amsterdam", AMS_TZ_POSIX, AMS_TZ_RAWFILE],
    )
    def test_notimplemented(self, tz: str):
        d = create_zdt(2020, 8, 15, tz=tz)
        assert d < AlwaysLarger()
        assert d <= AlwaysLarger()
        assert not d > AlwaysLarger()
        assert not d >= AlwaysLarger()
        assert not d < AlwaysSmaller()
        assert not d <= AlwaysSmaller()
        assert d > AlwaysSmaller()
        assert d >= AlwaysSmaller()

        with pytest.raises(TypeError):
            d < 42  # type: ignore[operator]
        with pytest.raises(TypeError):
            d <= 42  # type: ignore[operator]
        with pytest.raises(TypeError):
            d > 42  # type: ignore[operator]
        with pytest.raises(TypeError):
            d >= 42  # type: ignore[operator]
        with pytest.raises(TypeError):
            42 < d  # type: ignore[operator]
        with pytest.raises(TypeError):
            42 <= d  # type: ignore[operator]
        with pytest.raises(TypeError):
            42 > d  # type: ignore[operator]
        with pytest.raises(TypeError):
            42 >= d  # type: ignore[operator]


class TestToStdlib:
    def test_iana_tz_id(self):
        d = ZonedDateTime(
            2020,
            8,
            15,
            23,
            12,
            9,
            nanosecond=987_654_999,
            tz="Europe/Amsterdam",
        )
        py_dt = d.to_stdlib()
        assert py_dt == py_datetime(
            2020,
            8,
            15,
            23,
            12,
            9,
            987_654,
            tzinfo=ZoneInfo("Europe/Amsterdam"),
        )
        # This isn't checked by the comparison above!
        assert py_dt.tzinfo is ZoneInfo("Europe/Amsterdam")

        # ambiguous time
        d2 = ZonedDateTime(
            2023,
            10,
            29,
            2,
            15,
            tz="Europe/Amsterdam",
            disambiguate="earlier",
        )
        assert d2.to_stdlib().fold == 0
        assert d2.replace(disambiguate="later").to_stdlib().fold == 1

        # ensure the ZoneInfo isn't file-based, and can thus be pickled
        pickle.dumps(d2)

        # negative offset
        d3 = ZonedDateTime(
            2020,
            8,
            15,
            12,
            8,
            30,
            tz="America/New_York",
        )
        assert d3.to_stdlib().timestamp() == d3.timestamp()

    @pytest.mark.parametrize(
        "tz",
        [AMS_TZ_POSIX, AMS_TZ_RAWFILE],
    )
    def test_system_tz(self, tz: str):
        d = create_zdt(
            2020,
            8,
            15,
            12,
            8,
            30,
            nanosecond=123_456_789,
            tz=tz,
        )
        py_dt = d.to_stdlib()
        assert py_dt == py_datetime(
            2020, 8, 15, 10, 8, 30, 123_456, tzinfo=py_timezone.utc
        )
        # Ensure the offset is correct (the check above only checks UTC equality)
        assert py_dt.utcoffset() == py_timedelta(hours=2)


class _MyDatetime(py_datetime):
    pass


class TestInitFromPy:

    @pytest.mark.parametrize(
        "pydt, expect",
        [
            (
                py_datetime(
                    2020,
                    8,
                    15,
                    23,
                    12,
                    9,
                    987_654,
                    tzinfo=ZoneInfo("Europe/Paris"),
                ),
                ZonedDateTime(
                    2020,
                    8,
                    15,
                    23,
                    12,
                    9,
                    nanosecond=987_654_000,
                    tz="Europe/Paris",
                ),
            ),
            # subclass of datetime
            (
                _MyDatetime(
                    2020,
                    8,
                    15,
                    23,
                    12,
                    9,
                    987_654,
                    tzinfo=ZoneInfo("Europe/Paris"),
                ),
                ZonedDateTime(
                    2020,
                    8,
                    15,
                    23,
                    12,
                    9,
                    nanosecond=987_654_000,
                    tz="Europe/Paris",
                ),
            ),
            # skipped time
            (
                py_datetime(
                    2023,
                    3,
                    26,
                    2,
                    15,
                    30,
                    tzinfo=ZoneInfo("Europe/Amsterdam"),
                ),
                ZonedDateTime(
                    2023,
                    3,
                    26,
                    3,
                    15,
                    30,
                    tz="Europe/Amsterdam",
                ),
            ),
            (
                py_datetime(
                    2023,
                    3,
                    26,
                    2,
                    15,
                    30,
                    fold=1,
                    tzinfo=ZoneInfo("Europe/Amsterdam"),
                ),
                ZonedDateTime(
                    2023,
                    3,
                    26,
                    1,
                    15,
                    30,
                    tz="Europe/Amsterdam",
                ),
            ),
            # repeated time
            (
                py_datetime(
                    2023,
                    10,
                    29,
                    2,
                    15,
                    30,
                    tzinfo=ZoneInfo("Europe/Amsterdam"),
                ),
                ZonedDateTime(
                    2023,
                    10,
                    29,
                    2,
                    15,
                    30,
                    tz="Europe/Amsterdam",
                    disambiguate="earlier",
                ),
            ),
            (
                py_datetime(
                    2023,
                    10,
                    29,
                    2,
                    15,
                    30,
                    fold=1,
                    tzinfo=ZoneInfo("Europe/Amsterdam"),
                ),
                ZonedDateTime(
                    2023,
                    10,
                    29,
                    2,
                    15,
                    30,
                    tz="Europe/Amsterdam",
                    disambiguate="later",
                ),
            ),
        ],
    )
    def test_valid(self, pydt: py_datetime, expect: ZonedDateTime):
        assert ZonedDateTime(pydt).exact_eq(expect)

    def test_wrong_tzinfo(self):
        d = py_datetime(
            2020, 8, 15, 23, 12, 9, 987_654, tzinfo=py_timezone.utc
        )
        with pytest.raises(ValueError, match="datetime.timezone"):
            ZonedDateTime(d)

    def test_zoneinfo_subclass(self):

        # ZoneInfo subclass also not allowed
        class MyZoneInfo(ZoneInfo):
            pass

        dt = py_datetime(
            2020,
            8,
            15,
            23,
            12,
            9,
            987_654,
            tzinfo=MyZoneInfo("Europe/Paris"),
        )

        with pytest.raises(ValueError, match="ZoneInfo.*MyZoneInfo"):
            ZonedDateTime(dt)

    def test_naive(self):

        with pytest.raises(ValueError, match="None"):
            ZonedDateTime(py_datetime(2020, 3, 4))

    def test_out_of_range(self):
        min_pydt = py_datetime(1, 1, 1, tzinfo=ZoneInfo("Asia/Kolkata"))
        with pytest.raises((ValueError, OverflowError), match="range|year"):
            ZonedDateTime(min_pydt)

        max_pydt = py_datetime(
            9999, 12, 31, 22, tzinfo=ZoneInfo("America/New_York")
        )

        with pytest.raises((ValueError, OverflowError), match="range|year"):
            ZonedDateTime(max_pydt)

    def test_zoneinfo_key_is_none(self):
        with TEST_DIR.joinpath("tzif/Amsterdam.tzif").open("rb") as f:
            tz = ZoneInfo.from_file(f)

        py_dt = py_datetime(2020, 8, 15, 12, 8, 30, tzinfo=tz)

        with pytest.raises(ValueError, match="key"):
            ZonedDateTime(py_dt)


def test_now():
    now = ZonedDateTime.now("Iceland")
    assert now.tz == "Iceland"
    py_now = py_datetime.now(ZoneInfo("Iceland"))
    assert py_now - now.to_stdlib() < py_timedelta(seconds=1)


@system_tz_ams()
def test_now_in_system_tz():
    now = ZonedDateTime.now_in_system_tz()
    py_now = py_datetime.now().astimezone()
    assert now.tz == "Europe/Amsterdam"
    assert py_now - now.to_stdlib() < py_timedelta(seconds=1)


class TestExactEquality:
    def test_same_exact(self):
        a = ZonedDateTime(2020, 8, 15, 12, 8, 30, tz="Europe/Amsterdam")
        b = ZonedDateTime(2020, 8, 15, 12, 8, 30, tz="Europe/Amsterdam")
        assert a.exact_eq(b)

    def test_same_but_without_key(self):
        a = ZonedDateTime(2020, 8, 15, 12, 8, 30, tz="Europe/Amsterdam")
        b = create_zdt(2020, 8, 15, 12, 8, 30, tz=AMS_TZ_RAWFILE)
        assert not a.exact_eq(b)

    def test_different_zones(self):
        a = ZonedDateTime(
            2020, 8, 15, 12, 43, nanosecond=1, tz="Europe/Amsterdam"
        )
        b = a.to_tz("America/New_York")
        assert a == b
        assert not a.exact_eq(b)

        # Different zone but same offset
        c = a.to_tz("Europe/Paris")
        assert a == c
        assert not a.exact_eq(c)

    def test_same_timezone_ambiguity(self):
        a = ZonedDateTime(
            2023,
            10,
            29,
            2,
            15,
            nanosecond=1,
            tz="Europe/Amsterdam",
            disambiguate="earlier",
        )
        b = a.replace(disambiguate="later")
        assert a != b
        assert not a.exact_eq(b)

    def test_same_ambiguous(self):
        a = ZonedDateTime(
            2023,
            10,
            29,
            2,
            15,
            nanosecond=1,
            tz="Europe/Amsterdam",
            disambiguate="earlier",
        )
        b = a.replace(disambiguate="earlier")
        assert a.exact_eq(b)

    def test_same_unambiguous(self):
        a = ZonedDateTime(
            2020, 8, 15, 12, 43, nanosecond=1, tz="Europe/Amsterdam"
        )
        b = a.replace(disambiguate="later")
        assert a.exact_eq(b)
        assert a.exact_eq(b.replace(disambiguate="later"))

    def test_invalid(self):
        a = ZonedDateTime(2020, 8, 15, 12, 8, 30, tz="Europe/Amsterdam")
        with pytest.raises(TypeError):
            a.exact_eq(42)  # type: ignore[arg-type]

        with pytest.raises(TypeError):
            a.exact_eq(a.to_instant())  # type: ignore[arg-type]


class TestReplace:
    @pytest.mark.parametrize(
        "tz",
        ["Europe/Amsterdam", AMS_TZ_POSIX, AMS_TZ_RAWFILE],
    )
    def test_basics(self, tz: str):
        d = create_zdt(2020, 8, 15, 23, 12, 9, nanosecond=987_654, tz=tz)
        assert d.replace(year=2021).exact_eq(
            create_zdt(
                2021,
                8,
                15,
                23,
                12,
                9,
                nanosecond=987_654,
                tz=tz,
            )
        )
        assert d.replace(month=9, disambiguate="raise").exact_eq(
            create_zdt(
                2020,
                9,
                15,
                23,
                12,
                9,
                nanosecond=987_654,
                tz=tz,
            )
        )
        assert d.replace(day=16, disambiguate="raise").exact_eq(
            create_zdt(
                2020,
                8,
                16,
                23,
                12,
                9,
                nanosecond=987_654,
                tz=tz,
            )
        )
        assert d.replace(hour=0, disambiguate="raise").exact_eq(
            create_zdt(
                2020,
                8,
                15,
                0,
                12,
                9,
                nanosecond=987_654,
                tz=tz,
            )
        )
        assert d.replace(minute=0, disambiguate="raise").exact_eq(
            create_zdt(
                2020,
                8,
                15,
                23,
                0,
                9,
                nanosecond=987_654,
                tz=tz,
            )
        )
        assert d.replace(second=0, disambiguate="raise").exact_eq(
            create_zdt(
                2020,
                8,
                15,
                23,
                12,
                0,
                nanosecond=987_654,
                tz=tz,
            )
        )
        assert d.replace(nanosecond=0, disambiguate="raise").exact_eq(
            create_zdt(2020, 8, 15, 23, 12, 9, nanosecond=0, tz=tz)
        )
        assert d.replace(tz="Iceland", disambiguate="raise").exact_eq(
            ZonedDateTime(
                2020, 8, 15, 23, 12, 9, nanosecond=987_654, tz="Iceland"
            )
        )

    def test_invalid(self):
        d = ZonedDateTime(2020, 8, 15, tz="Europe/Amsterdam")

        with pytest.raises(TypeError, match="tzinfo"):
            d.replace(tzinfo=py_timezone.utc, disambiguate="compatible")  # type: ignore[call-arg]

        with pytest.raises(TypeError, match="fold"):
            d.replace(fold=1, disambiguate="compatible")  # type: ignore[call-arg]

        with pytest.raises(TypeError, match="foo"):
            d.replace(foo="bar", disambiguate="compatible")  # type: ignore[call-arg]

        with pytest.raises(TimeZoneNotFoundError, match="Nowhere"):
            d.replace(tz="Nowhere", disambiguate="compatible")

        with pytest.raises(ValueError, match="date|day"):
            d.replace(year=2023, month=2, day=29, disambiguate="compatible")

        with pytest.raises(ValueError, match="nano|time"):
            d.replace(nanosecond=1_000_000_000, disambiguate="compatible")

    @pytest.mark.parametrize(
        "tz",
        ["Europe/Amsterdam", AMS_TZ_POSIX, AMS_TZ_RAWFILE],
    )
    def test_repeated_time(self, tz: str):
        d = create_zdt(
            2023,
            10,
            29,
            2,
            15,
            30,
            tz=tz,
            disambiguate="earlier",
        )
        d_later = create_zdt(
            2023,
            10,
            29,
            2,
            15,
            30,
            tz=tz,
            disambiguate="later",
        )
        with pytest.raises(
            RepeatedTime,
            match="2023-10-29 02:15:30 is repeated in",
        ):
            d.replace(disambiguate="raise")

        assert d.replace(disambiguate="later").exact_eq(d_later)
        assert d.replace(disambiguate="earlier").exact_eq(d)
        assert d.replace(disambiguate="compatible").exact_eq(d)

        # earlier offset is reused if possible
        assert d.replace().exact_eq(d)
        assert d_later.replace().exact_eq(d_later)
        assert d.replace(minute=30).exact_eq(
            d.replace(minute=30, disambiguate="earlier")
        )
        assert d_later.replace(minute=30).exact_eq(
            d_later.replace(minute=30, disambiguate="later")
        )

        # Disambiguation may differ depending on whether we change tz
        # Note that only a named tz is relevant here
        if tz == "Europe/Amsterdam":
            assert d_later.replace(minute=30, tz=tz).exact_eq(
                d_later.replace(minute=30)
            )
        assert not d_later.replace(minute=30, tz="Europe/Paris").exact_eq(
            d_later.replace(minute=30)
        )

        # don't reuse offset per se when changing timezone
        assert d.replace(hour=3, tz="Europe/Athens").exact_eq(
            ZonedDateTime(
                2023,
                10,
                29,
                3,
                15,
                30,
                tz="Europe/Athens",
                disambiguate="earlier",
            )
        )
        assert d_later.replace(hour=1, tz="Europe/London").exact_eq(
            ZonedDateTime(
                2023,
                10,
                29,
                1,
                15,
                30,
                tz="Europe/London",
                disambiguate="earlier",
            )
        )
        assert d.replace(hour=1, tz="Europe/London").exact_eq(
            ZonedDateTime(
                2023,
                10,
                29,
                1,
                15,
                30,
                tz="Europe/London",
            )
        )
        assert d_later.replace(hour=3, tz="Europe/Athens").exact_eq(
            ZonedDateTime(
                2023,
                10,
                29,
                3,
                15,
                30,
                tz="Europe/Athens",
            )
        )

    @pytest.mark.parametrize(
        "tz",
        ["Europe/Amsterdam", AMS_TZ_POSIX, AMS_TZ_RAWFILE],
    )
    def test_skipped_time(self, tz: str):
        d = create_zdt(2023, 3, 26, 1, 15, 30, tz=tz)
        d_later = create_zdt(2023, 3, 26, 3, 15, 30, tz=tz)
        with pytest.raises(
            SkippedTime,
            match="2023-03-26 02:15:30 is skipped",
        ):
            d.replace(hour=2, disambiguate="raise")

        # default behavior without explicit disambiguation. Unlike in folds,
        # we *don't* reuse the offset here, since the time doesn't exist at all.
        # Instead, we go to the later time (same as disambiguate="compatible").
        assert d.replace(hour=2).exact_eq(d_later)

        # Disambiguation may differ depending on whether we change tz.
        # Note that only a named tz is relevant here
        if tz == "Europe/Amsterdam":
            assert d.replace(hour=2, disambiguate="earlier", tz=tz).exact_eq(d)
        assert not d.replace(hour=2, tz="Europe/Paris").exact_eq(d)

        assert d.replace(hour=2, disambiguate="earlier").exact_eq(
            create_zdt(
                2023,
                3,
                26,
                2,
                15,
                30,
                tz=tz,
                disambiguate="earlier",
            )
        )

        assert d.replace(hour=2, disambiguate="later").exact_eq(
            create_zdt(
                2023,
                3,
                26,
                2,
                15,
                30,
                tz=tz,
                disambiguate="later",
            )
        )

        assert d.replace(hour=2, disambiguate="compatible").exact_eq(
            create_zdt(
                2023,
                3,
                26,
                2,
                15,
                30,
                tz=tz,
                disambiguate="compatible",
            )
        )
        # Don't per se reuse the offset when changing timezone
        assert d.replace(tz="Europe/London").exact_eq(
            ZonedDateTime(
                2023,
                3,
                26,
                1,
                15,
                30,
                tz="Europe/London",
                disambiguate="later",
            )
        )
        assert d_later.replace(tz="Europe/Athens").exact_eq(
            ZonedDateTime(
                2023,
                3,
                26,
                4,
                15,
                30,
                tz="Europe/Athens",
            )
        )
        # can't reuse offset
        assert d.replace(hour=3, tz="Europe/Athens").exact_eq(
            ZonedDateTime(
                2023,
                3,
                26,
                4,
                15,
                30,
                tz="Europe/Athens",
            )
        )
        assert d_later.replace(hour=1, tz="Europe/London").exact_eq(
            ZonedDateTime(
                2023,
                3,
                26,
                2,
                15,
                30,
                tz="Europe/London",
            )
        )

    def test_out_of_range(self):
        d = ZonedDateTime(1, 1, 1, tz="America/New_York")

        with pytest.raises((ValueError, OverflowError), match="range|year"):
            d.replace(tz="Europe/Amsterdam", disambiguate="compatible")

        with pytest.raises((ValueError, OverflowError), match="range|year"):
            d.replace(
                year=9999, month=12, day=31, hour=23, disambiguate="compatible"
            )


class TestAddSubtractTimeUnits:
    @pytest.mark.parametrize(
        "tz",
        ["Europe/Amsterdam", AMS_TZ_POSIX, AMS_TZ_RAWFILE],
    )
    def test_zero(self, tz: str):
        d = create_zdt(2020, 8, 15, 23, 12, 9, nanosecond=987_654, tz=tz)
        assert (d + hours(0)).exact_eq(d)

        # the same with the method
        assert d.add().exact_eq(d)

        # the same with subtraction
        assert (d - hours(0)).exact_eq(d)
        assert d.subtract().exact_eq(d)

    @pytest.mark.parametrize(
        "tz",
        ["Europe/Amsterdam", AMS_TZ_POSIX, AMS_TZ_RAWFILE],
    )
    def test_ambiguous_plus_zero(self, tz: str):
        d = create_zdt(
            2023,
            10,
            29,
            2,
            15,
            30,
            disambiguate="earlier",
            tz=tz,
        )
        assert (d + hours(0)).exact_eq(d)
        assert (d.replace(disambiguate="later") + hours(0)).exact_eq(
            d.replace(disambiguate="later")
        )

        # the equivalent with the method
        assert d.add(hours=0).exact_eq(d)
        assert (
            d.replace(disambiguate="later")
            .add(hours=0)
            .exact_eq(d.replace(disambiguate="later"))
        )
        assert (
            d.replace(disambiguate="later")
            .add(ItemizedDelta(hours=0))
            .exact_eq(d.replace(disambiguate="later"))
        )

        # equivalent with subtraction
        assert (d - hours(0)).exact_eq(d)
        assert d.subtract(hours=0).exact_eq(d)
        assert d.subtract(ItemizedDelta(hours=0)).exact_eq(d)

    @pytest.mark.parametrize(
        "tz", ["Europe/Amsterdam", AMS_TZ_POSIX, AMS_TZ_RAWFILE]
    )
    def test_accounts_for_dst(self, tz: str):
        d = create_zdt(
            2023,
            10,
            29,
            2,
            15,
            30,
            disambiguate="earlier",
            tz=tz,
        )
        assert (d + hours(24)).exact_eq(
            create_zdt(2023, 10, 30, 1, 15, 30, tz=tz)
        )
        assert (d.replace(disambiguate="later") + hours(24)).exact_eq(
            create_zdt(2023, 10, 30, 2, 15, 30, tz=tz)
        )

        # the equivalent with the method (kwargs)
        assert d.add(hours=24).exact_eq(d + hours(24))
        assert (
            d.replace(disambiguate="later")
            .add(hours=24)
            .exact_eq(d.replace(disambiguate="later") + hours(24))
        )

        # equivalent with method (arg)
        assert d.add(hours(24)).exact_eq(d + hours(24))
        assert d.add(ItemizedDelta(minutes=24 * 60)).exact_eq(d + hours(24))
        assert (
            d.replace(disambiguate="later")
            .add(hours(24))
            .exact_eq(d.replace(disambiguate="later") + hours(24))
        )
        assert (
            d.replace(disambiguate="later")
            .add(ItemizedDelta(hours=24))
            .exact_eq(d.replace(disambiguate="later") + hours(24))
        )

        # equivalent with subtraction
        assert (d - hours(-24)).exact_eq(
            create_zdt(2023, 10, 30, 1, 15, 30, tz=tz)
        )
        assert d.subtract(hours=-24).exact_eq(d + hours(24))
        assert (
            d.replace(disambiguate="later")
            .subtract(hours=-24)
            .exact_eq(d.replace(disambiguate="later") + hours(24))
        )

    def test_out_of_range(self):
        d = ZonedDateTime(2020, 8, 15, tz="Africa/Abidjan")

        with pytest.raises((ValueError, OverflowError), match="range|year"):
            d + hours(24 * 366 * 8_000)

        # the equivalent with the method
        with pytest.raises((ValueError, OverflowError), match="range|year"):
            d.add(hours=24 * 366 * 8_000)

    def test_not_implemented(self):
        d = ZonedDateTime(2020, 8, 15, tz="Asia/Tokyo")
        with pytest.raises(TypeError, match="unsupported operand type"):
            d + 42  # type: ignore[operator]

        with pytest.raises(TypeError, match="unsupported operand type"):
            d - 42  # type: ignore[operator]

        with pytest.raises(TypeError, match="unsupported operand type"):
            42 + d  # type: ignore[operator]

        with pytest.raises(TypeError, match="unsupported operand type"):
            42 - d  # type: ignore[operator]

        with pytest.raises(TypeError, match="unsupported operand type"):
            years(1) + d  # type: ignore[operator]

        with pytest.raises(TypeError, match="unsupported operand type"):
            years(1) - d  # type: ignore[operator]

        with pytest.raises(TypeError, match="unsupported operand type"):
            d + d  # type: ignore[operator]

        with pytest.raises((TypeError, AttributeError)):
            d.add(4)  # type: ignore[call-overload]

        # mix args/kwargs
        with pytest.raises(TypeError):
            d.add(hours(34), seconds=3)  # type: ignore[call-overload]


class TestAddSubtractCalendarUnits:

    def test_zero(self):
        d = ZonedDateTime(
            2020, 8, 15, 23, 12, 9, nanosecond=987_654_321, tz="Asia/Tokyo"
        )
        assert d.add(days=0, disambiguate="raise").exact_eq(d)
        assert d.add(days=0).exact_eq(d)
        assert d.add(weeks=0).exact_eq(d)
        assert d.add(months=0).exact_eq(d)
        assert d.add(years=0, weeks=0).exact_eq(d)
        assert d.add().exact_eq(d)

        # same with operators
        assert (d + days(0)).exact_eq(d)
        assert (d + weeks(0)).exact_eq(d)
        assert (d + years(0)).exact_eq(d)

        # same with subtraction
        assert d.subtract(days=0, disambiguate="raise").exact_eq(d)
        assert d.subtract(days=0).exact_eq(d)

        assert (d - days(0)).exact_eq(d)
        assert (d - weeks(0)).exact_eq(d)
        assert (d - years(0)).exact_eq(d)

    def test_simple_date(self):
        d = ZonedDateTime(
            2020,
            8,
            15,
            23,
            12,
            9,
            nanosecond=987_654_321,
            tz="Australia/Sydney",
        )
        assert d.add(days=1).exact_eq(d.replace(day=16))
        assert d.add(years=1, weeks=2, days=-2).exact_eq(
            d.replace(year=2021, day=27)
        )

        # same with subtraction
        assert d.subtract(days=1).exact_eq(d.replace(day=14))
        assert d.subtract(years=1, weeks=2, days=-2).exact_eq(
            d.replace(year=2019, day=3)
        )

        assert d.add(years=1, weeks=2, days=-2).exact_eq(
            d.replace(year=2021, day=27)
        )
        # same with arg
        assert d.add(ItemizedDateDelta(years=8, months=2, days=9)).exact_eq(
            d.add(years=8, months=2, days=9)
        )
        assert d.add(ItemizedDelta(years=1, weeks=2, hours=2)).exact_eq(
            d.add(years=1, weeks=2, hours=2)
        )
        # same with operators
        assert (d + (years(1) + weeks(2) + days(-2))).exact_eq(
            d.add(years=1, weeks=2, days=-2)
        )
        assert (d + (years(1) + weeks(2) + hours(2))).exact_eq(
            d.add(years=1, weeks=2, hours=2)
        )
        assert (d - (years(1) + weeks(2) + days(-2))).exact_eq(
            d.subtract(years=1, weeks=2, days=-2)
        )
        assert (d - (years(1) + weeks(2) + hours(2))).exact_eq(
            d.subtract(years=1, weeks=2, hours=2)
        )

    def test_ambiguity(self):
        d = ZonedDateTime(
            2023,
            10,
            29,
            2,
            15,
            30,
            disambiguate="later",
            tz="Europe/Berlin",
        )
        assert d.add(days=0).exact_eq(d)
        assert d.add(days=7, weeks=-1).exact_eq(d)
        assert d.add(days=1).exact_eq(d.replace(day=30))
        assert d.add(days=6).exact_eq(d.replace(month=11, day=4))
        assert d.replace(disambiguate="earlier").add(hours=1).exact_eq(d)

        # transition to another fold
        assert d.add(years=1, days=-2, disambiguate="compatible").exact_eq(
            d.replace(year=2024, day=27, disambiguate="earlier")
        )
        # check operators too
        assert (d + years(1) - days(2)).exact_eq(d.add(years=1, days=-2))

        # transition to a gap
        assert d.add(months=5, days=2, disambiguate="compatible").exact_eq(
            d.replace(year=2024, month=3, day=31, disambiguate="later")
        )

        # transition over a gap
        assert d.add(
            months=5, days=2, hours=2, disambiguate="compatible"
        ).exact_eq(
            d.replace(year=2024, month=3, day=31, hour=5, disambiguate="raise")
        )
        assert d.add(
            months=5, days=2, hours=-1, disambiguate="compatible"
        ).exact_eq(
            d.replace(year=2024, month=3, day=31, disambiguate="earlier")
        )

        # same with subtraction
        assert d.subtract(days=0, disambiguate="raise").exact_eq(d)
        assert d.subtract(days=7, weeks=-1, disambiguate="raise").exact_eq(d)
        assert d.subtract(days=1, disambiguate="raise").exact_eq(
            d.replace(day=28, disambiguate="raise")
        )

    def test_out_of_bounds_min(self):
        d = ZonedDateTime(2000, 1, 1, tz="Europe/Amsterdam")
        with pytest.raises((ValueError, OverflowError), match="range|year"):
            d.add(years=-1999, disambiguate="compatible")

    def test_out_of_bounds_max(self):
        d = ZonedDateTime(2000, 12, 31, hour=23, tz="America/New_York")
        with pytest.raises((ValueError, OverflowError), match="range|year"):
            d.add(years=7999, disambiguate="compatible")

    def test_skipped_day(self):
        zdt = ZonedDateTime("2011-12-29T12-10:00[Pacific/Apia]")
        assert zdt.add(days=1).exact_eq(
            ZonedDateTime("2011-12-31 12:00:00+14:00[Pacific/Apia]")
        )


class TestDifference:

    @pytest.mark.parametrize(
        "tz", ["Europe/Amsterdam", AMS_TZ_POSIX, AMS_TZ_RAWFILE]
    )
    def test_simple(self, tz: str):
        d = create_zdt(2023, 10, 29, 5, tz=tz, disambiguate="earlier")
        other = create_zdt(2023, 10, 28, 3, nanosecond=4_000_000, tz=tz)
        assert d - other == (hours(27) - milliseconds(4))
        assert other - d == (hours(-27) + milliseconds(4))

        # same with the method
        assert d.difference(other) == d - other
        assert other.difference(d) == other - d

    @pytest.mark.parametrize(
        "tz", ["Europe/Amsterdam", AMS_TZ_POSIX, AMS_TZ_RAWFILE]
    )
    def test_amibiguous(self, tz: str):
        d = create_zdt(
            2023,
            10,
            29,
            2,
            15,
            tz=tz,
            disambiguate="earlier",
        )
        other = create_zdt(2023, 10, 28, 3, 15, tz=tz)
        assert d - other == hours(23)
        assert d.replace(disambiguate="later") - other == hours(24)
        assert other - d == hours(-23)
        assert other - d.replace(disambiguate="later") == hours(-24)

        # same with the method
        assert d.difference(other) == d - other

    def test_instant(self):
        d = ZonedDateTime(
            2023, 10, 29, 2, tz="Europe/Amsterdam", disambiguate="earlier"
        )
        other = Instant.from_utc(2023, 10, 28, 20)
        assert d - other == hours(4)
        assert d.replace(disambiguate="later") - other == hours(5)

        # same with the method
        assert d.difference(other) == d - other

    def test_offset(self):
        d = ZonedDateTime(
            2023, 10, 29, 2, tz="Europe/Amsterdam", disambiguate="earlier"
        )
        other = OffsetDateTime(2023, 10, 28, 20, offset=hours(1))
        assert d - other == hours(5)
        assert d.replace(disambiguate="later") - other == hours(6)

        # same with the method
        assert d.difference(other) == d - other


class TestSince:

    @pytest.mark.parametrize(
        "a, b, units, kwargs, expect",
        [
            # simple cases involving only calendar units
            (
                ZonedDateTime(
                    2023,
                    10,
                    29,
                    hour=11,
                    tz="Europe/Amsterdam",
                    disambiguate="earlier",
                ),
                ZonedDateTime(
                    2023,
                    10,
                    28,
                    hour=11,
                    tz="Europe/Amsterdam",
                    disambiguate="earlier",
                ),
                ["days"],
                {},
                ItemizedDelta(days=1),
            ),
            (
                ZonedDateTime(
                    2023,
                    10,
                    29,
                    hour=11,
                    tz="Europe/Amsterdam",
                    disambiguate="earlier",
                ),
                ZonedDateTime(
                    2023,
                    10,
                    28,
                    hour=10,
                    tz="Europe/Amsterdam",
                    disambiguate="earlier",
                ),
                ["days"],
                {},
                ItemizedDelta(days=1),
            ),
            (
                ZonedDateTime(
                    2025,
                    5,
                    31,
                    hour=23,
                    tz="Europe/Amsterdam",
                ),
                ZonedDateTime(
                    2023,
                    1,
                    28,
                    hour=1,
                    tz="Europe/Amsterdam",
                ),
                ["years", "months", "days"],
                {"round_increment": 2},
                ItemizedDelta(years=2, months=4, days=2),
            ),
            # calendar units only--but with time-of-day differences that affect rounding
            (
                ZonedDateTime(
                    2025,
                    5,
                    31,
                    hour=4,
                    tz="Europe/Amsterdam",
                ),
                ZonedDateTime(
                    2023,
                    1,
                    28,
                    hour=4,
                    nanosecond=1,
                    tz="Europe/Amsterdam",
                ),
                ["years", "months", "days"],
                {},
                ItemizedDelta(years=2, months=4, days=2),
            ),
            # same but with rounding
            (
                ZonedDateTime(
                    2025,
                    5,
                    31,
                    hour=4,
                    tz="Europe/Amsterdam",
                ),
                ZonedDateTime(
                    2023,
                    1,
                    28,
                    hour=4,
                    nanosecond=1,
                    tz="Europe/Amsterdam",
                ),
                ["years", "months", "days"],
                {"round_increment": 3, "round_mode": "half_ceil"},
                ItemizedDelta(years=2, months=4, days=3),
            ),
            (
                ZonedDateTime(
                    2025,
                    5,
                    31,
                    hour=4,
                    tz="Europe/Amsterdam",
                ),
                ZonedDateTime(
                    2025,
                    5,
                    1,
                    hour=4,
                    nanosecond=1,
                    tz="Europe/Amsterdam",
                ),
                ["years", "months", "days"],
                {"round_increment": 40, "round_mode": "floor"},
                ItemizedDelta(years=0, months=0, days=0),
            ),
            # Rounding affected by time-of-day
            (
                ZonedDateTime(
                    2023,
                    2,
                    15,
                    hour=13,
                    minute=25,
                    tz="Europe/Berlin",
                ),
                ZonedDateTime(
                    2021,
                    7,
                    3,
                    hour=1,
                    tz="Europe/Berlin",
                ),
                ["years", "days"],
                {"round_mode": "floor"},
                ItemizedDelta(years=1, days=227),
            ),
            (
                ZonedDateTime(
                    2023,
                    2,
                    15,
                    hour=13,
                    minute=25,
                    tz="Europe/Berlin",
                ),
                ZonedDateTime(
                    2021,
                    7,
                    3,
                    hour=1,
                    tz="Europe/Berlin",
                ),
                ["years", "days"],
                {"round_mode": "half_even"},
                ItemizedDelta(years=1, days=228),
            ),
            # Rounding affected by shorter days (due to DST)
            (
                ZonedDateTime(
                    2023,
                    10,
                    29,
                    hour=12,
                    minute=35,
                    tz="Europe/Berlin",
                ),
                ZonedDateTime(
                    2021,
                    7,
                    3,
                    hour=1,
                    tz="Europe/Berlin",
                ),
                ["years", "days"],
                {"round_mode": "half_even"},
                ItemizedDelta(years=2, days=119),
            ),
            (
                ZonedDateTime(
                    2023,
                    3,
                    26,
                    hour=13,
                    minute=25,
                    tz="Europe/Berlin",
                ),
                ZonedDateTime(
                    2021,
                    7,
                    3,
                    hour=1,
                    tz="Europe/Berlin",
                ),
                ["years", "days"],
                {"round_mode": "half_even"},
                ItemizedDelta(years=1, days=266),
            ),
            (
                ZonedDateTime(
                    2023,
                    3,
                    26,
                    hour=1,
                    minute=35,
                    tz="Europe/Berlin",
                ),
                ZonedDateTime(
                    2021,
                    7,
                    3,
                    hour=14,
                    tz="Europe/Berlin",
                ),
                ["years", "days"],
                {"round_mode": "half_even"},
                ItemizedDelta(years=1, days=266),
            ),
            # Rounding affected by disambiguation
            (
                ZonedDateTime(
                    2023,
                    3,
                    31,
                    hour=19,
                    minute=35,
                    tz="Europe/Berlin",
                ),
                ZonedDateTime(
                    2021,
                    1,
                    26,
                    hour=2,
                    minute=25,
                    tz="Europe/Berlin",
                ),
                ["years", "months"],
                {"round_mode": "half_even"},
                ItemizedDelta(years=2, months=2),
            ),
            (
                ZonedDateTime(
                    2023,
                    3,
                    20,
                    hour=19,
                    minute=35,
                    tz="Europe/Berlin",
                ),
                ZonedDateTime(
                    2820,
                    1,
                    26,
                    hour=2,
                    minute=25,
                    tz="Europe/Berlin",
                ),
                ["years", "months"],
                {"round_mode": "half_even"},
                ItemizedDelta(years=-796, months=-10),
            ),
            # Beyond calendar units
            (
                ZonedDateTime(
                    2023,
                    2,
                    15,
                    hour=13,
                    minute=25,
                    tz="Europe/Berlin",
                ),
                ZonedDateTime(
                    2021,
                    7,
                    3,
                    hour=1,
                    tz="Europe/Berlin",
                ),
                ["years", "weeks", "hours"],
                {"round_mode": "floor"},
                ItemizedDelta(years=1, weeks=32, hours=84),
            ),
            (
                ZonedDateTime(
                    2023,
                    2,
                    15,
                    hour=13,
                    minute=25,
                    tz="Europe/Berlin",
                ),
                ZonedDateTime(
                    2021,
                    7,
                    3,
                    hour=1,
                    tz="Europe/Berlin",
                ),
                ["years", "weeks", "minutes"],
                {"round_mode": "ceil", "round_increment": 12},
                ItemizedDelta(years=1, weeks=32, minutes=5076),
            ),
            (
                ZonedDateTime(
                    2020,
                    2,
                    15,
                    hour=13,
                    minute=25,
                    tz="Europe/Berlin",
                ),
                ZonedDateTime(
                    2021,
                    7,
                    3,
                    hour=1,
                    tz="Europe/Berlin",
                ),
                ["hours", "minutes"],
                {"round_mode": "ceil", "round_increment": 12},
                ItemizedDelta(hours=-12082, minutes=-24),
            ),
            # Handling skipped days (rare case involved international date line crossing)
            (
                ZonedDateTime("2011-12-31T21+14:00[Pacific/Apia]"),
                ZonedDateTime("2011-12-29T20-10:00[Pacific/Apia]"),
                ["days", "hours"],
                {},
                ItemizedDelta(days=2, hours=1),
            ),
            (
                ZonedDateTime("2011-12-31T21+14:00[Pacific/Apia]"),
                ZonedDateTime("2011-12-29T20:50-10:00[Pacific/Apia]"),
                ["hours", "minutes"],
                {},
                ItemizedDelta(hours=24, minutes=10),
            ),
            (
                ZonedDateTime("2011-12-31T17+14:00[Pacific/Apia]"),
                ZonedDateTime("2011-12-29T17-10:00[Pacific/Apia]"),
                ["days", "hours"],
                {},
                ItemizedDelta(days=2, hours=0),
            ),
            (
                ZonedDateTime("2011-12-31T17+14:00[Pacific/Apia]"),
                ZonedDateTime("2011-12-29T17-10:00[Pacific/Apia]"),
                ["hours"],
                {},
                ItemizedDelta(hours=24),
            ),
            (
                ZonedDateTime("2011-12-31T17+14:00[Pacific/Apia]"),
                ZonedDateTime("2011-12-29T18-10:00[Pacific/Apia]"),
                ["days", "hours"],
                {},
                ItemizedDelta(days=0, hours=23),
            ),
            (
                ZonedDateTime("2011-12-31T17+14:00[Pacific/Apia]"),
                ZonedDateTime("2011-12-29T16-10:00[Pacific/Apia]"),
                ["days", "hours"],
                {},
                ItemizedDelta(days=2, hours=1),
            ),
            (
                ZonedDateTime("2011-12-31T17+14:00[Pacific/Apia]"),
                ZonedDateTime("2011-12-29T16-10:00[Pacific/Apia]"),
                ["hours"],
                {},
                ItemizedDelta(hours=25),
            ),
            # DST-at-midnight case
            (
                ZonedDateTime(
                    2016,
                    2,
                    20,
                    hour=23,
                    minute=29,
                    tz="America/Sao_Paulo",
                    disambiguate="later",
                ),
                ZonedDateTime(
                    2016, 2, 19, hour=23, minute=45, tz="America/Sao_Paulo"
                ),
                ["days", "minutes"],
                {},
                ItemizedDelta(days=1, minutes=44),
            ),
            # Negative delta date truncation handled correctly
            (
                ZonedDateTime(2022, 2, 2, tz="Asia/Kolkata"),
                ZonedDateTime(2022, 2, 5, tz="Asia/Kolkata"),
                ["days"],
                {},
                ItemizedDelta(days=-3),
            ),
            (
                ZonedDateTime(2022, 2, 2, hour=3, tz="Asia/Kolkata"),
                ZonedDateTime(2022, 2, 5, hour=2, tz="Asia/Kolkata"),
                ["days", "hours"],
                {},
                ItemizedDelta(days=-2, hours=-23),
            ),
            (
                ZonedDateTime(2022, 2, 2, hour=3, tz="Asia/Kolkata"),
                ZonedDateTime(2022, 2, 5, hour=2, tz="Asia/Kolkata"),
                ["days"],
                {},
                ItemizedDelta(days=-2),
            ),
            (
                ZonedDateTime(2022, 2, 2, hour=3, tz="Asia/Kolkata"),
                ZonedDateTime(2022, 2, 5, hour=2, tz="Asia/Kolkata"),
                ["days"],
                {"round_mode": "floor"},
                ItemizedDelta(days=-3),
            ),
            # Zero situations
            (
                ZonedDateTime(
                    2020,
                    2,
                    15,
                    hour=13,
                    minute=25,
                    tz="Europe/Berlin",
                ),
                ZonedDateTime(
                    2021,
                    7,
                    3,
                    hour=1,
                    tz="Europe/Berlin",
                ),
                ["years"],
                {"round_mode": "trunc", "round_increment": 4},
                ItemizedDelta(years=0),
            ),
            (
                ZonedDateTime(
                    2023,
                    2,
                    15,
                    hour=13,
                    minute=25,
                    tz="Europe/Berlin",
                ),
                ZonedDateTime(
                    2021,
                    7,
                    3,
                    hour=1,
                    tz="Europe/Berlin",
                ),
                ["months"],
                {"round_mode": "trunc", "round_increment": 50},
                ItemizedDelta(months=0),
            ),
            (
                ZonedDateTime(
                    2023,
                    2,
                    15,
                    hour=13,
                    minute=25,
                    tz="Asia/Tokyo",
                ),
                ZonedDateTime(
                    2023,
                    2,
                    15,
                    hour=13,
                    minute=25,
                    tz="Asia/Tokyo",
                ),
                ["weeks"],
                {},
                ItemizedDelta(weeks=0),
            ),
            (
                ZonedDateTime(
                    2023,
                    2,
                    15,
                    hour=13,
                    minute=25,
                    tz="Asia/Tokyo",
                ),
                ZonedDateTime(
                    2023,
                    2,
                    15,
                    hour=13,
                    minute=25,
                    tz="Asia/Tokyo",
                ),
                ["seconds"],
                {},
                ItemizedDelta(seconds=0),
            ),
            # single unit cases
            (
                ZonedDateTime(
                    2023,
                    2,
                    15,
                    hour=13,
                    minute=25,
                    tz="Asia/Tokyo",
                ),
                ZonedDateTime(
                    2023,
                    2,
                    15,
                    hour=13,
                    minute=25,
                    nanosecond=1,
                    tz="Asia/Tokyo",
                ),
                ["seconds"],
                {},
                ItemizedDelta(seconds=0),
            ),
            (
                ZonedDateTime(
                    2023,
                    2,
                    15,
                    hour=13,
                    minute=25,
                    tz="Asia/Tokyo",
                ),
                ZonedDateTime(
                    2023,
                    2,
                    15,
                    hour=13,
                    minute=25,
                    second=1,
                    tz="Asia/Tokyo",
                ),
                ["seconds"],
                {},
                ItemizedDelta(seconds=-1),
            ),
            # different timezone
            (
                ZonedDateTime(
                    2023,
                    2,
                    15,
                    hour=13,
                    minute=25,
                    tz="Asia/Tokyo",
                ),
                ZonedDateTime(
                    2023,
                    2,
                    15,
                    hour=13,
                    minute=25,
                    second=1,
                    tz="America/Los_Angeles",
                ),
                ["hours", "minutes"],
                {},
                ItemizedDelta(hours=-17, minutes=0),
            ),
        ],
    )
    def test_examples(
        self,
        a: ZonedDateTime,
        b: ZonedDateTime,
        units: Sequence[
            Literal[
                "years",
                "months",
                "weeks",
                "days",
                "hours",
                "minutes",
                "seconds",
                "nanoseconds",
            ]
        ],
        kwargs: dict[str, Any],
        expect: ItemizedDelta,
    ):
        assert a.since(b, in_units=units, **kwargs).exact_eq(expect)

    def test_cal_units_with_different_tz_not_supported(self):
        with pytest.raises(ValueError, match="same timezone"):
            ZonedDateTime(2023, 2, 15, tz="Asia/Tokyo").since(
                ZonedDateTime(2023, 2, 15, tz="America/Los_Angeles"),
                in_units=["days"],
            )

    def test_invalid_units(self):
        with pytest.raises(ValueError, match="[Ii]nvalid unit.*foos"):
            ZonedDateTime(2023, 2, 15, tz="Asia/Tokyo").since(
                ZonedDateTime(2023, 2, 15, tz="Asia/Tokyo"),
                in_units=["foos"],  # type: ignore[list-item]
            )

        with pytest.raises(ValueError, match="[Ii]nvalid unit.*foos"):
            ZonedDateTime(2023, 2, 15, tz="Asia/Tokyo").since(
                ZonedDateTime(2023, 2, 15, tz="Asia/Tokyo"),
                total="foos",  # type: ignore[call-overload]
            )

    def test_very_large_increment(self):
        a = ZonedDateTime(2023, 2, 15, tz="Asia/Tokyo")
        b = ZonedDateTime(2021, 7, 3, tz="Asia/Tokyo")
        # round_increment=1<<65 ns exceeds i64::MAX; ceil mode rounds up to 1*(1<<65)
        assert a.since(
            b,
            in_units=["seconds", "nanoseconds"],
            round_increment=1 << 65,
            round_mode="ceil",
        ) == ItemizedDelta(seconds=36_893_488_147, nanoseconds=419_103_232)

    def test_until_is_inverse(self):
        a = ZonedDateTime(2023, 2, 15, hour=3, tz="Asia/Tokyo")
        b = ZonedDateTime(2021, 7, 3, tz="Asia/Tokyo")
        assert a.since(
            b, in_units=["years", "months", "days", "hours"]
        ) == b.until(a, in_units=["years", "months", "days", "hours"])
        # floor rounding works correctly
        assert a.since(
            b,
            in_units=["years", "months", "days", "hours"],
            round_increment=2,
            round_mode="floor",
        ) == b.until(
            a,
            in_units=["years", "months", "days", "hours"],
            round_increment=2,
            round_mode="floor",
        )

    def test_nanoseconds_dont_overflow(self):
        a = ZonedDateTime(9000, 1, 1, tz="UTC")
        b = ZonedDateTime(23, 3, 15, tz="UTC")
        assert a.since(b, total="nanoseconds") == 283280457600000000000

    def test_total_and_in_units_both_raises(self):
        a = ZonedDateTime(2023, 2, 15, tz="Asia/Tokyo")
        b = ZonedDateTime(2021, 7, 3, tz="Asia/Tokyo")
        with pytest.raises(TypeError, match="total.*in_units|in_units.*total"):
            a.since(
                b,
                total="hours",  # type: ignore[call-overload]
                in_units=["hours"],
            )

    def test_total_with_round_mode_raises(self):
        a = ZonedDateTime(2023, 2, 15, tz="Asia/Tokyo")
        b = ZonedDateTime(2021, 7, 3, tz="Asia/Tokyo")
        with pytest.raises(TypeError, match="round_mode.*total|total.*round"):
            a.since(
                b,
                total="hours",
                round_mode="floor",  # type: ignore[call-overload]
            )

    def test_total_calendar_unit_same_tz(self):
        a = ZonedDateTime(2025, 3, 15, tz="Asia/Tokyo")
        b = ZonedDateTime(2023, 3, 15, tz="Asia/Tokyo")
        result = a.since(b, total="years")
        assert isinstance(result, float)
        assert result == 2.0

    def test_total_calendar_unit_different_tz_raises(self):
        a = ZonedDateTime(2023, 2, 15, tz="Asia/Tokyo")
        b = ZonedDateTime(2021, 7, 3, tz="Europe/Paris")
        with pytest.raises(ValueError, match="[Cc]alendar.*same.*timezone"):
            a.since(b, total="days")

    def test_no_units_raises(self):
        a = ZonedDateTime(2023, 2, 15, tz="Asia/Tokyo")
        b = ZonedDateTime(2021, 7, 3, tz="Asia/Tokyo")
        with pytest.raises(TypeError, match="total.*in_units|in_units.*total"):
            a.since(b)  # type: ignore[call-overload]


class TestRound:

    @pytest.mark.parametrize(
        "d, increment, unit, floor, ceil, half_floor, half_ceil, half_even",
        [
            (
                ZonedDateTime(
                    2023, 7, 14, 1, nanosecond=459_999_999, tz="Europe/Paris"
                ),
                1,
                "nanosecond",
                ZonedDateTime(
                    2023, 7, 14, 1, nanosecond=459_999_999, tz="Europe/Paris"
                ),
                ZonedDateTime(
                    2023, 7, 14, 1, nanosecond=459_999_999, tz="Europe/Paris"
                ),
                ZonedDateTime(
                    2023, 7, 14, 1, nanosecond=459_999_999, tz="Europe/Paris"
                ),
                ZonedDateTime(
                    2023, 7, 14, 1, nanosecond=459_999_999, tz="Europe/Paris"
                ),
                ZonedDateTime(
                    2023, 7, 14, 1, nanosecond=459_999_999, tz="Europe/Paris"
                ),
            ),
            (
                ZonedDateTime(
                    2023,
                    7,
                    14,
                    1,
                    2,
                    21,
                    nanosecond=459_999_999,
                    tz="Europe/Paris",
                ),
                4,
                "second",
                ZonedDateTime(2023, 7, 14, 1, 2, 20, tz="Europe/Paris"),
                ZonedDateTime(2023, 7, 14, 1, 2, 24, tz="Europe/Paris"),
                ZonedDateTime(2023, 7, 14, 1, 2, 20, tz="Europe/Paris"),
                ZonedDateTime(2023, 7, 14, 1, 2, 20, tz="Europe/Paris"),
                ZonedDateTime(2023, 7, 14, 1, 2, 20, tz="Europe/Paris"),
            ),
            (
                ZonedDateTime(
                    2023,
                    7,
                    14,
                    23,
                    52,
                    29,
                    nanosecond=999_999_999,
                    tz="Europe/Paris",
                ),
                10,
                "minute",
                ZonedDateTime(2023, 7, 14, 23, 50, 0, tz="Europe/Paris"),
                ZonedDateTime(2023, 7, 15, tz="Europe/Paris"),
                ZonedDateTime(2023, 7, 14, 23, 50, 0, tz="Europe/Paris"),
                ZonedDateTime(2023, 7, 14, 23, 50, 0, tz="Europe/Paris"),
                ZonedDateTime(2023, 7, 14, 23, 50, 0, tz="Europe/Paris"),
            ),
            (
                ZonedDateTime(
                    2023,
                    7,
                    14,
                    11,
                    59,
                    29,
                    nanosecond=999_999_999,
                    tz="Europe/Paris",
                ),
                12,
                "hour",
                ZonedDateTime(2023, 7, 14, tz="Europe/Paris"),
                ZonedDateTime(2023, 7, 14, 12, 0, 0, tz="Europe/Paris"),
                ZonedDateTime(2023, 7, 14, 12, 0, 0, tz="Europe/Paris"),
                ZonedDateTime(2023, 7, 14, 12, 0, 0, tz="Europe/Paris"),
                ZonedDateTime(2023, 7, 14, 12, 0, 0, tz="Europe/Paris"),
            ),
            # Unusual increment, but still divides a day evenly
            (
                ZonedDateTime(
                    2023,
                    7,
                    14,
                    11,
                    59,
                    29,
                    nanosecond=999_999_999,
                    tz="Europe/Paris",
                ),
                90,
                "minute",
                ZonedDateTime(2023, 7, 14, 10, 30, tz="Europe/Paris"),
                ZonedDateTime(2023, 7, 14, 12, 0, 0, tz="Europe/Paris"),
                ZonedDateTime(2023, 7, 14, 12, 0, 0, tz="Europe/Paris"),
                ZonedDateTime(2023, 7, 14, 12, 0, 0, tz="Europe/Paris"),
                ZonedDateTime(2023, 7, 14, 12, 0, 0, tz="Europe/Paris"),
            ),
            # normal, 24-hour day at midnight
            (
                ZonedDateTime(2023, 7, 14, tz="Europe/Paris"),
                1,
                "day",
                ZonedDateTime(2023, 7, 14, tz="Europe/Paris"),
                ZonedDateTime(2023, 7, 14, tz="Europe/Paris"),
                ZonedDateTime(2023, 7, 14, tz="Europe/Paris"),
                ZonedDateTime(2023, 7, 14, tz="Europe/Paris"),
                ZonedDateTime(2023, 7, 14, tz="Europe/Paris"),
            ),
            # normal, 24-hour day
            (
                ZonedDateTime(2023, 7, 14, 12, tz="Europe/Paris"),
                1,
                "day",
                ZonedDateTime(2023, 7, 14, tz="Europe/Paris"),
                ZonedDateTime(2023, 7, 15, tz="Europe/Paris"),
                ZonedDateTime(2023, 7, 14, tz="Europe/Paris"),
                ZonedDateTime(2023, 7, 15, tz="Europe/Paris"),
                ZonedDateTime(2023, 7, 14, tz="Europe/Paris"),
            ),
            # shorter day
            (
                ZonedDateTime(2023, 3, 26, 11, 30, tz="Europe/Paris"),
                1,
                "day",
                ZonedDateTime(2023, 3, 26, tz="Europe/Paris"),
                ZonedDateTime(2023, 3, 27, tz="Europe/Paris"),
                ZonedDateTime(2023, 3, 26, tz="Europe/Paris"),
                ZonedDateTime(2023, 3, 27, tz="Europe/Paris"),
                ZonedDateTime(2023, 3, 26, tz="Europe/Paris"),
            ),
            # shorter day (23 hours)
            (
                ZonedDateTime(2023, 3, 26, 11, 30, tz="Europe/Paris"),
                1,
                "day",
                ZonedDateTime(2023, 3, 26, tz="Europe/Paris"),
                ZonedDateTime(2023, 3, 27, tz="Europe/Paris"),
                ZonedDateTime(2023, 3, 26, tz="Europe/Paris"),
                ZonedDateTime(2023, 3, 27, tz="Europe/Paris"),
                ZonedDateTime(2023, 3, 26, tz="Europe/Paris"),
            ),
            # longer day (24.5 hours)
            (
                ZonedDateTime(2024, 4, 7, 12, 15, tz="Australia/Lord_Howe"),
                1,
                "day",
                ZonedDateTime(2024, 4, 7, tz="Australia/Lord_Howe"),
                ZonedDateTime(2024, 4, 8, tz="Australia/Lord_Howe"),
                ZonedDateTime(2024, 4, 7, tz="Australia/Lord_Howe"),
                ZonedDateTime(2024, 4, 8, tz="Australia/Lord_Howe"),
                ZonedDateTime(2024, 4, 7, tz="Australia/Lord_Howe"),
            ),
            # keeps the offset if possible
            (
                ZonedDateTime(
                    2023,
                    10,
                    29,
                    2,
                    15,
                    tz="Europe/Paris",
                    disambiguate="later",
                ),
                30,
                "minute",
                ZonedDateTime(
                    2023, 10, 29, 2, 0, tz="Europe/Paris", disambiguate="later"
                ),
                ZonedDateTime(
                    2023,
                    10,
                    29,
                    2,
                    30,
                    tz="Europe/Paris",
                    disambiguate="later",
                ),
                ZonedDateTime(
                    2023, 10, 29, 2, 0, tz="Europe/Paris", disambiguate="later"
                ),
                ZonedDateTime(
                    2023,
                    10,
                    29,
                    2,
                    30,
                    tz="Europe/Paris",
                    disambiguate="later",
                ),
                ZonedDateTime(
                    2023, 10, 29, 2, 0, tz="Europe/Paris", disambiguate="later"
                ),
            ),
        ],
    )
    def test_round(
        self,
        d: ZonedDateTime,
        increment,
        unit,
        floor,
        ceil,
        half_floor,
        half_ceil,
        half_even,
    ):
        assert d.round(unit, increment=increment) == half_even
        assert d.round(unit, increment=increment, mode="floor") == floor
        assert d.round(unit, increment=increment, mode="trunc") == floor
        assert d.round(unit, increment=increment, mode="ceil") == ceil
        assert d.round(unit, increment=increment, mode="expand") == ceil
        assert (
            d.round(unit, increment=increment, mode="half_floor") == half_floor
        )
        assert (
            d.round(unit, increment=increment, mode="half_trunc") == half_floor
        )
        assert (
            d.round(unit, increment=increment, mode="half_ceil") == half_ceil
        )
        assert (
            d.round(unit, increment=increment, mode="half_expand") == half_ceil
        )
        assert (
            d.round(unit, increment=increment, mode="half_even") == half_even
        )

    def test_default(self):
        d = ZonedDateTime(
            2023, 7, 14, 1, 2, 3, nanosecond=500_000_000, tz="Europe/Paris"
        )
        assert d.round() == ZonedDateTime(
            2023, 7, 14, 1, 2, 4, tz="Europe/Paris"
        )
        assert d.replace(second=8).round() == ZonedDateTime(
            2023, 7, 14, 1, 2, 8, tz="Europe/Paris"
        )

    def test_default_increment(self):
        d = ZonedDateTime(
            2023, 7, 14, 1, 2, 3, nanosecond=800_000, tz="Europe/Paris"
        )
        assert d.round("millisecond").exact_eq(
            ZonedDateTime(
                2023, 7, 14, 1, 2, 3, nanosecond=1_000_000, tz="Europe/Paris"
            )
        )

    def test_invalid_mode(self):
        d = ZonedDateTime(
            2023, 7, 14, 1, 2, 3, nanosecond=4_000, tz="Europe/Paris"
        )
        with pytest.raises(ValueError, match="mode.*foo"):
            d.round("second", mode="foo")  # type: ignore[call-overload]

    @pytest.mark.parametrize(
        "unit, increment",
        [
            ("minute", 21),
            ("second", 14),
            ("millisecond", 13),
            ("day", 2),
            ("hour", 48),
            ("microsecond", 1542),
            ("microsecond", 7),
        ],
    )
    def test_increment_doesnt_evenly_divide_day(self, unit, increment):
        d = ZonedDateTime(
            2023, 7, 14, 1, 2, 3, nanosecond=4_000, tz="Europe/Paris"
        )
        with pytest.raises(ValueError, match="24.hour"):
            d.round(unit, increment=increment)

    @pytest.mark.parametrize(
        "unit, increment",
        [
            ("minute", 0),
            ("minute", -5),
            ("second", 4.1),
        ],
    )
    def test_increment_invalid(self, unit, increment):
        d = ZonedDateTime(
            2023, 7, 14, 1, 2, 3, nanosecond=4_000, tz="Europe/Paris"
        )
        with pytest.raises(ValueError, match="[Ii]ncrement"):
            d.round(unit, increment=increment)

    def test_invalid_unit(self):
        d = ZonedDateTime(
            2023, 7, 14, 1, 2, 3, nanosecond=4_000, tz="Europe/Paris"
        )
        with pytest.raises(ValueError, match="Invalid.*unit.*foo"):
            d.round("foo")  # type: ignore[call-overload]

    def test_out_of_range(self):
        d = ZonedDateTime(9999, 12, 31, 23, tz="Etc/UTC")

        with pytest.raises((ValueError, OverflowError), match="range"):
            d.round("hour", increment=4)

        with pytest.raises((ValueError, OverflowError), match="range"):
            d.round("day")

    def test_round_by_timedelta(self):
        d = ZonedDateTime(2020, 8, 15, 23, 24, 18, tz="Europe/Amsterdam")
        assert d.round(TimeDelta(minutes=15)) == ZonedDateTime(
            2020, 8, 15, 23, 30, tz="Europe/Amsterdam"
        )
        assert d.round(TimeDelta(hours=1)) == ZonedDateTime(
            2020, 8, 15, 23, tz="Europe/Amsterdam"
        )
        assert d.round(TimeDelta(minutes=15), mode="floor") == ZonedDateTime(
            2020, 8, 15, 23, 15, tz="Europe/Amsterdam"
        )

    def test_round_by_timedelta_invalid_not_divides_day(self):
        d = ZonedDateTime(2020, 8, 15, 12, tz="Europe/Amsterdam")
        with pytest.raises(ValueError, match="24.hour"):
            d.round(TimeDelta(hours=7))

    def test_round_by_timedelta_negative(self):
        d = ZonedDateTime(2020, 8, 15, 12, tz="Europe/Amsterdam")
        with pytest.raises(ValueError, match="positive"):
            d.round(TimeDelta(hours=-1))

    def test_round_by_timedelta_with_increment(self):
        d = ZonedDateTime(2020, 8, 15, 12, tz="Europe/Amsterdam")
        with pytest.raises(TypeError):
            d.round(TimeDelta(hours=1), increment=2)  # type: ignore[call-overload]


class TestPickle:
    def test_simple(self):
        d = ZonedDateTime(
            2020, 8, 15, 23, 12, 9, nanosecond=987_654, tz="Europe/Amsterdam"
        )
        dumped = pickle.dumps(d)
        assert len(dumped) <= len(pickle.dumps(d.to_stdlib()))
        assert pickle.loads(pickle.dumps(d)).exact_eq(d)

    def test_ambiguous(self):
        d1 = ZonedDateTime(
            2023,
            10,
            29,
            2,
            15,
            30,
            tz="Europe/Amsterdam",
            disambiguate="earlier",
        )
        d2 = d1.replace(disambiguate="later")
        assert pickle.loads(pickle.dumps(d1)).exact_eq(d1)
        assert pickle.loads(pickle.dumps(d2)).exact_eq(d2)

    @pytest.mark.parametrize("tz", [AMS_TZ_POSIX, AMS_TZ_RAWFILE])
    def test_no_tzid(self, tz: str):
        d = create_zdt(2023, 12, 3, 9, 15, tz=tz)
        with pytest.raises(ValueError, match="unknown timezone ID"):
            pickle.dumps(d)


def test_old_pickle_data_remains_unpicklable():
    # Don't update this value after 1.x release: the whole idea is that
    # it's a pickle at a specific version of the library,
    # and it should remain unpicklable even in later versions.
    dumped = (
        b"\x80\x04\x95F\x00\x00\x00\x00\x00\x00\x00\x8c\x08whenever\x94\x8c\x0c_unp"
        b"kl_zoned\x94\x93\x94C\x0f\xe4\x07\x08\x0f\x17\x0c\t\x06\x12\x0f\x00"
        b" \x1c\x00\x00\x94\x8c\x10Europe/Amsterdam\x94\x86\x94R\x94."
    )
    assert pickle.loads(dumped).exact_eq(
        ZonedDateTime(
            2020, 8, 15, 23, 12, 9, nanosecond=987_654, tz="Europe/Amsterdam"
        )
    )


@pytest.mark.parametrize(
    "tz", ["Europe/Amsterdam", AMS_TZ_POSIX, AMS_TZ_RAWFILE]
)
def test_copy(tz: str):
    d = create_zdt(2020, 8, 15, 23, 12, 9, nanosecond=987_654, tz=tz)
    assert copy(d) is d
    assert deepcopy(d) is d


class TestDeprecations:
    def test_py_datetime(self):
        d = ZonedDateTime(
            2020,
            8,
            15,
            23,
            12,
            9,
            nanosecond=987_654_999,
            tz="Europe/Amsterdam",
        )
        with pytest.warns(WheneverDeprecationWarning):
            result = d.py_datetime()
        assert result == py_datetime(
            2020,
            8,
            15,
            23,
            12,
            9,
            987_654,
            tzinfo=ZoneInfo("Europe/Amsterdam"),
        )

    def test_from_py_datetime(self):
        with pytest.warns(WheneverDeprecationWarning):
            result = ZonedDateTime.from_py_datetime(
                py_datetime(
                    2020,
                    8,
                    15,
                    23,
                    12,
                    9,
                    987_654,
                    tzinfo=ZoneInfo("Europe/Paris"),
                )
            )
        assert result.exact_eq(
            ZonedDateTime(
                2020,
                8,
                15,
                23,
                12,
                9,
                nanosecond=987_654_000,
                tz="Europe/Paris",
            )
        )


def test_cannot_subclass():
    with pytest.raises(TypeError):

        class Subclass(ZonedDateTime):  # type: ignore[misc]
            pass


class TestDayOfYear:

    def test_basic(self):
        zdt = ZonedDateTime(2024, 2, 29, 12, tz="America/New_York")
        assert zdt.day_of_year() == 60

    def test_jan1(self):
        zdt = ZonedDateTime(2023, 1, 1, 0, tz="America/New_York")
        assert zdt.day_of_year() == 1


class TestDaysInMonth:

    def test_feb_leap(self):
        zdt = ZonedDateTime(2024, 2, 29, 12, tz="America/New_York")
        assert zdt.days_in_month() == 29

    def test_feb_nonleap(self):
        zdt = ZonedDateTime(2023, 2, 15, 12, tz="America/New_York")
        assert zdt.days_in_month() == 28


class TestDaysInYear:

    def test_leap(self):
        zdt = ZonedDateTime(2024, 2, 29, 12, tz="America/New_York")
        assert zdt.days_in_year() == 366

    def test_nonleap(self):
        zdt = ZonedDateTime(2023, 6, 15, 12, tz="America/New_York")
        assert zdt.days_in_year() == 365


class TestInLeapYear:

    def test_leap(self):
        zdt = ZonedDateTime(2024, 2, 29, 12, tz="America/New_York")
        assert zdt.in_leap_year() is True

    def test_nonleap(self):
        zdt = ZonedDateTime(2023, 6, 15, 12, tz="America/New_York")
        assert zdt.in_leap_year() is False


class TestStartOf:

    def test_year(self):
        zdt = ZonedDateTime(
            2024, 8, 15, 14, 30, 45, nanosecond=123, tz="America/New_York"
        )
        result = zdt.start_of("year")
        assert result.exact_eq(
            ZonedDateTime(2024, 1, 1, tz="America/New_York")
        )

    def test_month(self):
        zdt = ZonedDateTime(
            2024, 8, 15, 14, 30, 45, nanosecond=123, tz="America/New_York"
        )
        result = zdt.start_of("month")
        assert result.exact_eq(
            ZonedDateTime(2024, 8, 1, tz="America/New_York")
        )

    def test_day(self):
        zdt = ZonedDateTime(
            2024, 8, 15, 14, 30, 45, nanosecond=123, tz="America/New_York"
        )
        result = zdt.start_of("day")
        assert result.exact_eq(
            ZonedDateTime(2024, 8, 15, tz="America/New_York")
        )

    def test_day_matches_start_of_day(self):
        zdt = ZonedDateTime(
            2024, 8, 15, 14, 30, 45, nanosecond=123, tz="America/New_York"
        )
        assert zdt.start_of("day").exact_eq(zdt.start_of_day())

    def test_hour(self):
        zdt = ZonedDateTime(
            2024, 8, 15, 14, 30, 45, nanosecond=123, tz="America/New_York"
        )
        result = zdt.start_of("hour")
        assert result.exact_eq(
            ZonedDateTime(2024, 8, 15, 14, tz="America/New_York")
        )

    def test_minute(self):
        zdt = ZonedDateTime(
            2024, 8, 15, 14, 30, 45, nanosecond=123, tz="America/New_York"
        )
        result = zdt.start_of("minute")
        assert result.exact_eq(
            ZonedDateTime(2024, 8, 15, 14, 30, tz="America/New_York")
        )

    def test_second(self):
        zdt = ZonedDateTime(
            2024, 8, 15, 14, 30, 45, nanosecond=123, tz="America/New_York"
        )
        result = zdt.start_of("second")
        assert result.exact_eq(
            ZonedDateTime(2024, 8, 15, 14, 30, 45, tz="America/New_York")
        )

    def test_invalid_unit(self):
        with pytest.raises(ValueError, match="Invalid (unit|value for unit)"):
            ZonedDateTime(2024, 8, 15, 14, 30, tz="America/New_York").start_of(
                "week"  # type: ignore[arg-type]
            )

    def test_hour_gap_transition(self):
        # Lord Howe: at 2:00 AM Oct 6, clocks spring forward 30min
        # to 2:30 AM. Times 2:00-2:29 don't exist.
        # At 2:45+11:00, start_of("hour") should resolve the gap.
        zdt = ZonedDateTime(2024, 10, 6, 2, 45, tz="Australia/Lord_Howe")
        result = zdt.start_of("hour")
        assert result.exact_eq(
            ZonedDateTime(2024, 10, 6, 2, 30, tz="Australia/Lord_Howe")
        )

    def test_hour_fold_earlier(self):
        # Lord Howe end of DST: Apr 7, 1:30-1:59 occurs twice.
        # At 1:45+11:00 (first occurrence), start_of("hour") => 1:00+11:00
        zdt = ZonedDateTime(
            2024,
            4,
            7,
            1,
            45,
            tz="Australia/Lord_Howe",
            disambiguate="earlier",
        )
        result = zdt.start_of("hour")
        assert result.offset == hours(11)

    def test_hour_fold_later(self):
        # At 1:45+10:30 (second occurrence), start_of("hour") => 1:00+11:00
        # because 1:00 is not in the fold (fold is 1:30-1:59),
        # so it's unambiguous at +11:00
        zdt = ZonedDateTime(
            2024,
            4,
            7,
            1,
            45,
            tz="Australia/Lord_Howe",
            disambiguate="later",
        )
        result = zdt.start_of("hour")
        assert result.offset == hours(11)


class TestEndOf:

    def test_year(self):
        zdt = ZonedDateTime(
            2024, 8, 15, 14, 30, 45, nanosecond=123, tz="America/New_York"
        )
        result = zdt.end_of("year")
        assert result.exact_eq(
            ZonedDateTime(
                2024,
                12,
                31,
                23,
                59,
                59,
                nanosecond=999_999_999,
                tz="America/New_York",
            )
        )

    def test_month_31_days(self):
        zdt = ZonedDateTime(2024, 8, 15, 14, 30, tz="America/New_York")
        result = zdt.end_of("month")
        assert result.exact_eq(
            ZonedDateTime(
                2024,
                8,
                31,
                23,
                59,
                59,
                nanosecond=999_999_999,
                tz="America/New_York",
            )
        )

    def test_month_feb_leap(self):
        zdt = ZonedDateTime(2024, 2, 10, 12, tz="America/New_York")
        result = zdt.end_of("month")
        assert result.exact_eq(
            ZonedDateTime(
                2024,
                2,
                29,
                23,
                59,
                59,
                nanosecond=999_999_999,
                tz="America/New_York",
            )
        )

    def test_day(self):
        zdt = ZonedDateTime(
            2024, 8, 15, 14, 30, 45, nanosecond=123, tz="America/New_York"
        )
        result = zdt.end_of("day")
        assert result.exact_eq(
            ZonedDateTime(
                2024,
                8,
                15,
                23,
                59,
                59,
                nanosecond=999_999_999,
                tz="America/New_York",
            )
        )

    def test_hour(self):
        zdt = ZonedDateTime(
            2024, 8, 15, 14, 30, 45, nanosecond=123, tz="America/New_York"
        )
        result = zdt.end_of("hour")
        assert result.exact_eq(
            ZonedDateTime(
                2024,
                8,
                15,
                14,
                59,
                59,
                nanosecond=999_999_999,
                tz="America/New_York",
            )
        )

    def test_minute(self):
        zdt = ZonedDateTime(
            2024, 8, 15, 14, 30, 45, nanosecond=123, tz="America/New_York"
        )
        result = zdt.end_of("minute")
        assert result.exact_eq(
            ZonedDateTime(
                2024,
                8,
                15,
                14,
                30,
                59,
                nanosecond=999_999_999,
                tz="America/New_York",
            )
        )

    def test_second(self):
        zdt = ZonedDateTime(
            2024, 8, 15, 14, 30, 45, nanosecond=123, tz="America/New_York"
        )
        result = zdt.end_of("second")
        assert result.exact_eq(
            ZonedDateTime(
                2024,
                8,
                15,
                14,
                30,
                45,
                nanosecond=999_999_999,
                tz="America/New_York",
            )
        )

    def test_invalid_unit(self):
        with pytest.raises(ValueError, match="Invalid (unit|value for unit)"):
            ZonedDateTime(2024, 8, 15, 14, 30, tz="America/New_York").end_of(
                "week"  # type: ignore[arg-type]
            )

    def test_hour_gap_transition(self):
        # Lord Howe: at 2:00 AM Oct 6, clocks spring forward 30min.
        # At 2:45+11:00, end_of("hour") should be 2:59:59.999999999+11:00
        zdt = ZonedDateTime(2024, 10, 6, 2, 45, tz="Australia/Lord_Howe")
        result = zdt.end_of("hour")
        assert result.exact_eq(
            ZonedDateTime(
                2024,
                10,
                6,
                2,
                59,
                59,
                nanosecond=999_999_999,
                tz="Australia/Lord_Howe",
            )
        )

    def test_hour_fold_preserves_offset(self):
        # Lord Howe end of DST: 1:30-1:59 occurs twice.
        # At 1:45+11:00, end_of("hour") => 1:59+11:00 (earlier offset preserved)
        zdt_e = ZonedDateTime(
            2024,
            4,
            7,
            1,
            45,
            tz="Australia/Lord_Howe",
            disambiguate="earlier",
        )
        result_e = zdt_e.end_of("hour")
        assert result_e.offset == hours(11)

        # At 1:45+10:30, end_of("hour") => 1:59+10:30 (later offset preserved)
        zdt_l = ZonedDateTime(
            2024,
            4,
            7,
            1,
            45,
            tz="Australia/Lord_Howe",
            disambiguate="later",
        )
        result_l = zdt_l.end_of("hour")
        assert result_l.offset == TimeDelta(hours=10, minutes=30)

        # They represent different instants
        assert result_e != result_l
