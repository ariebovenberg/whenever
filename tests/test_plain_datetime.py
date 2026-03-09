import pickle
import re
import warnings
from datetime import datetime as py_datetime, timezone
from typing import Any, Literal, Sequence

import pytest
from hypothesis import given
from hypothesis.strategies import floats, integers, text

from whenever import (
    Date,
    Instant,
    ItemizedDelta,
    NaiveArithmeticWarning,
    OffsetDateTime,
    PlainDateTime,
    RepeatedTime,
    SkippedTime,
    Time,
    TimeDelta,
    WheneverDeprecationWarning,
    ZonedDateTime,
    days,
    hours,
    months,
    nanoseconds,
    seconds,
    weeks,
    years,
)

from .common import (
    AMS_TZ_POSIX,
    AlwaysEqual,
    AlwaysLarger,
    AlwaysSmaller,
    NeverEqual,
    suppress,
    system_tz,
    system_tz_ams,
)

pytestmark = pytest.mark.filterwarnings(
    "ignore::whenever.WheneverDeprecationWarning"
)


class TestInit:

    def test_simple(self):
        d = PlainDateTime(2020, 8, 15, 5, 12, 30, nanosecond=450)

        assert d.year == 2020
        assert d.month == 8
        assert d.day == 15
        assert d.hour == 5
        assert d.minute == 12
        assert d.second == 30
        assert d.nanosecond == 450

        assert (
            PlainDateTime(2020, 8, 15, 12)
            == PlainDateTime(2020, 8, 15, 12, 0)
            == PlainDateTime(2020, 8, 15, 12, 0, 0)
            == PlainDateTime(2020, 8, 15, 12, 0, 0, nanosecond=0)
        )

        with pytest.raises(ValueError, match="nano|time"):
            PlainDateTime(2020, 8, 15, 12, 0, 0, nanosecond=1_000_000_000)

    def test_iso(self):
        assert PlainDateTime("2020-08-15T05:12:30.000000450") == PlainDateTime(
            2020, 8, 15, 5, 12, 30, nanosecond=450
        )

    def test_leap_seconds_parsing(self):
        # Leap second (60) should be parsed and normalized to 59
        assert PlainDateTime("2020-08-15T05:12:60") == PlainDateTime(
            2020, 8, 15, 5, 12, 59
        )
        assert PlainDateTime("2020-08-15T05:12:60.123456") == PlainDateTime(
            2020, 8, 15, 5, 12, 59, nanosecond=123_456_000
        )
        # Basic format
        assert PlainDateTime("20200815T051260") == PlainDateTime(
            2020, 8, 15, 5, 12, 59
        )
        # Direct construction should still reject 60
        with pytest.raises(ValueError):
            PlainDateTime(2020, 8, 15, 5, 12, 60)


def test_components():
    d = PlainDateTime(2020, 8, 15, 23, 12, 9, nanosecond=987_654_123)
    assert d.date() == Date(2020, 8, 15)
    assert d.time() == Time(23, 12, 9, nanosecond=987_654_123)


def test_assume_utc():
    assert PlainDateTime(2020, 8, 15, 23).assume_utc() == Instant.from_utc(
        2020, 8, 15, 23
    )


def test_assume_fixed_offset():
    assert (
        PlainDateTime(2020, 8, 15, 23)
        .assume_fixed_offset(hours(5))
        .exact_eq(OffsetDateTime(2020, 8, 15, 23, offset=5))
    )
    assert (
        PlainDateTime(2020, 8, 15, 23)
        .assume_fixed_offset(-2)
        .exact_eq(OffsetDateTime(2020, 8, 15, 23, offset=-2))
    )


class TestAssumeTz:
    def test_typical(self):
        d = PlainDateTime(2020, 8, 15, 23)
        assert d.assume_tz("Asia/Tokyo", disambiguate="raise").exact_eq(
            ZonedDateTime(2020, 8, 15, 23, tz="Asia/Tokyo")
        )
        assert d.assume_tz("Asia/Tokyo").exact_eq(
            ZonedDateTime(2020, 8, 15, 23, tz="Asia/Tokyo")
        )

    def test_ambiguous(self):
        d = PlainDateTime(2023, 10, 29, 2, 15)

        with pytest.raises(RepeatedTime, match="02:15.*Europe/Amsterdam"):
            d.assume_tz("Europe/Amsterdam", disambiguate="raise")

        assert d.assume_tz(
            "Europe/Amsterdam", disambiguate="earlier"
        ).exact_eq(
            ZonedDateTime(
                2023,
                10,
                29,
                2,
                15,
                tz="Europe/Amsterdam",
                disambiguate="earlier",
            )
        )
        assert d.assume_tz("Europe/Amsterdam", disambiguate="later").exact_eq(
            ZonedDateTime(
                2023,
                10,
                29,
                2,
                15,
                tz="Europe/Amsterdam",
                disambiguate="later",
            )
        )

    def test_nonexistent(self):
        d = PlainDateTime(2023, 3, 26, 2, 15)

        with pytest.raises(SkippedTime, match="02:15.*Europe/Amsterdam"):
            d.assume_tz("Europe/Amsterdam", disambiguate="raise")

        assert d.assume_tz(
            "Europe/Amsterdam", disambiguate="earlier"
        ).exact_eq(
            ZonedDateTime(
                2023,
                3,
                26,
                2,
                15,
                tz="Europe/Amsterdam",
                disambiguate="earlier",
            )
        )


class TestAssumeSystemTz:
    @pytest.mark.parametrize(
        "tz",
        [
            "Europe/Amsterdam",
            AMS_TZ_POSIX,
        ],
    )
    def test_typical(self, tz):
        with system_tz(tz):
            dt = PlainDateTime(2020, 8, 15, 23)

            with system_tz(tz):
                zdt = dt.assume_system_tz(disambiguate="raise")
                assert isinstance(zdt, ZonedDateTime)
                assert zdt.to_plain() == dt
                assert zdt.offset == hours(2)

                if tz == "Europe/Amsterdam":
                    assert zdt.tz == "Europe/Amsterdam"

    @pytest.mark.parametrize(
        "tz",
        [
            "Europe/Amsterdam",
            AMS_TZ_POSIX,
        ],
    )
    def test_ambiguous(self, tz):
        with system_tz(tz):
            d = PlainDateTime(2023, 10, 29, 2, 15)

            with pytest.raises(RepeatedTime, match="02:15.*is repeated"):
                d.assume_system_tz(disambiguate="raise")

            zdt1 = d.assume_system_tz(disambiguate="earlier")
            assert isinstance(zdt1, ZonedDateTime)
            assert zdt1.to_plain() == d
            assert zdt1.offset == hours(2)

            # posix TZ string cannot be checked
            if tz == "Europe/Amsterdam":
                assert zdt1.tz == "Europe/Amsterdam"

            assert d.assume_system_tz(disambiguate="compatible").exact_eq(zdt1)

            zdt2 = d.assume_system_tz(disambiguate="later")
            assert isinstance(zdt2, ZonedDateTime)
            assert zdt2.to_plain() == d
            assert zdt2.offset == hours(1)

            # posix TZ string cannot be checked
            if tz == "Europe/Amsterdam":
                assert zdt2.tz == "Europe/Amsterdam"

    @pytest.mark.parametrize(
        "tz",
        [
            "Europe/Amsterdam",
            AMS_TZ_POSIX,
        ],
    )
    @suppress(NaiveArithmeticWarning)
    def test_nonexistent(self, tz):
        with system_tz(tz):
            d = PlainDateTime(2023, 3, 26, 2, 15)

            with pytest.raises(SkippedTime, match="02:15.*is skipped"):
                d.assume_system_tz(disambiguate="raise")

            zdt1 = d.assume_system_tz(disambiguate="earlier")
            assert isinstance(zdt1, ZonedDateTime)
            assert zdt1.to_plain() == d.subtract(hours=1)
            assert zdt1.offset == hours(1)
            # posix TZ string cannot be checked
            if tz == "Europe/Amsterdam":
                assert zdt1.tz == "Europe/Amsterdam"

            zdt2 = d.assume_system_tz(disambiguate="later")
            assert isinstance(zdt2, ZonedDateTime)
            assert zdt2.to_plain() == d.add(hours=1)
            assert zdt2.offset == hours(2)
            # posix TZ string cannot be checked
            if tz == "Europe/Amsterdam":
                assert zdt2.tz == "Europe/Amsterdam"

            assert d.assume_system_tz(disambiguate="compatible").exact_eq(zdt2)


def test_immutable():
    d = PlainDateTime(2020, 8, 15)
    with pytest.raises(AttributeError):
        d.year = 2021  # type: ignore[misc]


class TestParseIso:
    @pytest.mark.parametrize(
        "s, expected",
        [
            # typical ISO format, perhaps with fractions
            ("2020-08-15T12:08:30", (2020, 8, 15, 12, 8, 30, 0)),
            (
                "2020-08-15T12:08:30.349",
                (2020, 8, 15, 12, 8, 30, 349_000_000),
            ),
            (
                "2020-08-15T12:08:30.3491239",
                (2020, 8, 15, 12, 8, 30, 349_123_900),
            ),
            # "Basic" ISO format
            (
                "20200815T120830.3491239",
                (2020, 8, 15, 12, 8, 30, 349_123_900),
            ),
            # other separators
            ("2020-08-15 120830", (2020, 8, 15, 12, 8, 30, 0)),
            ("20200815t120830", (2020, 8, 15, 12, 8, 30, 0)),
            # basic/mixed formats
            ("12340815T12:08:30", (1234, 8, 15, 12, 8, 30, 0)),
            ("1234-08-15T120830", (1234, 8, 15, 12, 8, 30, 0)),
            ("12340815 120830", (1234, 8, 15, 12, 8, 30, 0)),
            # Partial time component
            ("2020-08-15T12:08", (2020, 8, 15, 12, 8, 0, 0)),
            ("20200815T02", (2020, 8, 15, 2, 0, 0, 0)),
            ("20200815T0215", (2020, 8, 15, 2, 15, 0, 0)),
            ("1234-01-03T23", (1234, 1, 3, 23, 0, 0, 0)),
            # leap second cases: 60 is normalized to 59
            ("2020-08-15T23:59:60", (2020, 8, 15, 23, 59, 59, 0)),
            (
                "2020-08-15T23:59:60.999999999",
                (2020, 8, 15, 23, 59, 59, 999_999_999),
            ),
            ("2020-08-15T12:34:60.5", (2020, 8, 15, 12, 34, 59, 500_000_000)),
            (
                "20200815T123460.123456",
                (2020, 8, 15, 12, 34, 59, 123_456_000),
            ),
            ("2020-08-15T12:34:60,5", (2020, 8, 15, 12, 34, 59, 500_000_000)),
        ],
    )
    def test_valid(self, s, expected):
        assert PlainDateTime.parse_iso(s) == PlainDateTime(
            *expected[:6], nanosecond=expected[6]
        )

    @pytest.mark.parametrize(
        "s",
        [
            # decimal issues
            "2020-08-15T12:08:30.1234567890",  # too many
            "2020-08-15T12:08:30.1234 ",
            "2020-08-15T12:08:30.123_5",
            "2020-08-15T12:08:30.123.5",
            "2020-08-15T12:08:30.",
            "2020-08-15T12:08:300",
            "2020-08-15T12:08:30:00",
            "2020-08-15T12:08.28",
            # incomplete date
            "2020-11",
            "-020-08-15T12:08",
            # invalid separators
            "2020-03-13T12:08.30",
            "2020-03-14Z12:08",
            "20200314\xc3120830",
            "2020-03-14112:08:30",
            "2020-03-14+12:08",
            "2020-03-1412:08",
            # no date
            "12:08:30.1234567890",
            "T12:08:30",
            "2020-11   T12:08:30.1234567890",
            # offsets not allowed
            "2020-08-15T12:08:30Z",
            "2020-08-15T12:08:30.45+0500",
            "2020-08-15T12:08:30+05:00",
            # incorrect padding
            "2020-08-15T12:8:30",
            "2020-08-15T2",
            # garbage strings
            "",
            "*",
            "garbage",  # garbage
            # non-ascii
            "2020-08-15T12:08:30.349𝟙239",
            # separator, but incomplete time
            "2020-08-15T",
            "2020-08-15T1",
            # invalid component values
            "0000-12-15T12:08:30",
            "2020-18-15T12:08:30",
            "2020-11-31T12:08:30",
            "2020-11-21T24:08:30",
            "2020-11-21T22:68:30",
            "2020-11-21T22:48:62",
            # ordinal and week days
            "2020-W08-1T12:08:30",
            "2020W081T12:08:30",
            "2020081T12:08:30",
            "2020-081T12:08:30",
            # invalid leap second cases
            "2020-08-15T12:34:61",
            "2020-08-15T12:34:99",
        ],
    )
    def test_invalid(self, s):
        with pytest.raises(ValueError, match=re.escape(repr(s))):
            PlainDateTime.parse_iso(s)

    @given(text())
    def test_fuzzing(self, s: str):
        with pytest.raises(ValueError, match=re.escape(repr(s))):
            PlainDateTime.parse_iso(s)


def test_equality():
    d = PlainDateTime(2020, 8, 15)
    different = PlainDateTime(2020, 8, 16)
    different2 = PlainDateTime(2020, 8, 15, nanosecond=1)
    same = PlainDateTime(2020, 8, 15)
    assert d == same
    assert d != different
    assert not d == different
    assert d != different2
    assert not d == different2
    assert not d != same

    assert hash(d) == hash(same)
    assert hash(d) != hash(different)
    assert hash(d) != hash(different2)

    assert d == AlwaysEqual()
    assert d != NeverEqual()
    assert not d == NeverEqual()
    assert not d != AlwaysEqual()

    assert d != 42  # type: ignore[comparison-overlap]
    assert not d == 42  # type: ignore[comparison-overlap]

    # no mixing with aware types:
    assert d != d.assume_utc()  # type: ignore[comparison-overlap]
    assert d != d.assume_fixed_offset(+3)  # type: ignore[comparison-overlap]

    # Ambiguity in system timezone doesn't affect equality
    with system_tz_ams():
        assert PlainDateTime(2023, 10, 29, 2, 15) == PlainDateTime(
            py_datetime(2023, 10, 29, 2, 15, fold=1)
        )


def test_repr():
    d = PlainDateTime(2020, 8, 15, 23, 12, 9, nanosecond=987_654)
    assert repr(d) == 'PlainDateTime("2020-08-15 23:12:09.000987654")'
    # no fractional seconds
    assert (
        repr(PlainDateTime(2020, 8, 15, 23, 12))
        == 'PlainDateTime("2020-08-15 23:12:00")'
    )


class TestFormatIso:

    def test_default(self):
        d = PlainDateTime(2020, 8, 15, 23, 12, 9, nanosecond=987_650)
        assert str(d) == "2020-08-15T23:12:09.00098765"
        assert d.format_iso() == "2020-08-15T23:12:09.00098765"

    @pytest.mark.parametrize(
        "dt, kwargs, expected",
        [
            (
                PlainDateTime(1993, 4, 1, 14),
                {"unit": "nanosecond"},
                "1993-04-01T14:00:00.000000000",
            ),
            (
                PlainDateTime(2025, 11, 1, 14, nanosecond=40_000),
                {"unit": "microsecond", "sep": " "},
                "2025-11-01 14:00:00.000040",
            ),
            (
                PlainDateTime(2025, 11, 1, 14, 59, 42, nanosecond=40_000),
                {"unit": "millisecond", "basic": True},
                "20251101T145942.000",
            ),
            (
                PlainDateTime(2020, 8, 15, 23, 12, 9, nanosecond=987_654_321),
                {"unit": "second", "sep": "T", "basic": True},
                "20200815T231209",
            ),
            (
                PlainDateTime(2020, 8, 15, 23, 12, 49),
                {"unit": "minute"},
                "2020-08-15T23:12",
            ),
            (
                PlainDateTime(2020, 8, 15, 23, 45),
                {"unit": "hour", "basic": True},
                "20200815T23",
            ),
            (
                PlainDateTime(2020, 8, 15, nanosecond=40_000),
                {"unit": "auto", "basic": False},
                "2020-08-15T00:00:00.00004",
            ),
        ],
    )
    def test_variations(self, dt, kwargs, expected):
        assert dt.format_iso(**kwargs) == expected

    def test_invalid(self):
        dt = PlainDateTime(2020, 4, 9, 13)
        with pytest.raises(ValueError, match="unit"):
            dt.format_iso(unit="foo")  # type: ignore[arg-type]

        with pytest.raises(
            (ValueError, TypeError, AttributeError), match="unit"
        ):
            dt.format_iso(unit=True)  # type: ignore[arg-type]

        with pytest.raises(ValueError, match="sep"):
            dt.format_iso(sep="_")  # type: ignore[arg-type]

        with pytest.raises(
            (ValueError, TypeError, AttributeError), match="sep"
        ):
            dt.format_iso(sep=1)  # type: ignore[arg-type]

        with pytest.raises(TypeError, match="basic"):
            dt.format_iso(basic=1)  # type: ignore[arg-type]

        # tz is a valid kwarg for ZonedDateTime.format_iso(), but not here
        with pytest.raises(TypeError, match="tz"):
            dt.format_iso(tz="always")  # type: ignore[call-arg]


def test_comparison():
    d = PlainDateTime(2020, 8, 15, 23, 12, 9)
    later = PlainDateTime(2020, 8, 16, 0, 0, 0)
    later2 = d.replace(nanosecond=1)
    assert d < later
    assert d <= later
    assert later > d
    assert later >= d

    assert d < later2
    assert d <= later2
    assert later2 > d
    assert later2 >= d

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


def test_to_stdlib():
    d = PlainDateTime(2020, 8, 15, 23, 12, 9, nanosecond=987_654_823)
    assert d.to_stdlib() == py_datetime(2020, 8, 15, 23, 12, 9, 987_654)


def test_init_from_py_datetime():
    d = py_datetime(2020, 8, 15, 23, 12, 9, 987_654)
    assert PlainDateTime(d) == PlainDateTime(
        2020, 8, 15, 23, 12, 9, nanosecond=987_654_000
    )

    with pytest.raises(ValueError, match="utc"):
        PlainDateTime(
            py_datetime(2020, 8, 15, 23, 12, 9, 987_654, tzinfo=timezone.utc)
        )

    class MyDateTime(py_datetime):
        pass

    assert PlainDateTime(
        MyDateTime(2020, 8, 15, 23, 12, 9, 987_654)
    ) == PlainDateTime(2020, 8, 15, 23, 12, 9, nanosecond=987_654_000)


def test_min_max():
    assert PlainDateTime.MIN == PlainDateTime(1, 1, 1)
    assert PlainDateTime.MAX == PlainDateTime(
        9999, 12, 31, 23, 59, 59, nanosecond=999_999_999
    )


def test_replace():
    d = PlainDateTime(2020, 8, 15, 23, 12, 9, nanosecond=987_654)
    assert d.replace(year=2021) == PlainDateTime(
        2021, 8, 15, 23, 12, 9, nanosecond=987_654
    )
    assert d.replace(month=9) == PlainDateTime(
        2020, 9, 15, 23, 12, 9, nanosecond=987_654
    )
    assert d.replace(day=16) == PlainDateTime(
        2020, 8, 16, 23, 12, 9, nanosecond=987_654
    )
    assert d.replace(hour=0) == PlainDateTime(
        2020, 8, 15, 0, 12, 9, nanosecond=987_654
    )
    assert d.replace(minute=0) == PlainDateTime(
        2020, 8, 15, 23, 0, 9, nanosecond=987_654
    )
    assert d.replace(second=0) == PlainDateTime(
        2020, 8, 15, 23, 12, 0, nanosecond=987_654
    )
    assert d.replace(nanosecond=0) == PlainDateTime(
        2020, 8, 15, 23, 12, 9, nanosecond=0
    )

    with pytest.raises(ValueError, match="nano|time"):
        d.replace(nanosecond=1_000_000_000)

    with pytest.raises(ValueError, match="nano|time"):
        d.replace(nanosecond=-4)

    with pytest.raises(TypeError, match="tzinfo"):
        d.replace(tzinfo=timezone.utc)  # type: ignore[call-arg]


class TestShiftMethods:

    def test_warnings(self):
        d = PlainDateTime(2020, 8, 15, 23, 12, 9, nanosecond=987_654)
        with pytest.warns(NaiveArithmeticWarning) as w:
            d.add(months=2, hours=48, seconds=5, nanoseconds=3)
        assert len(w) == 1

        with pytest.warns(NaiveArithmeticWarning) as w:
            d.subtract(months=2, hours=48, seconds=5, nanoseconds=3)
        assert len(w) == 1

        # calendar units don't trigger warning
        d.subtract(days=10, months=3, years=1)
        d.add(days=10, months=3, years=1)

        # ignore_dst deprecated
        with suppress(NaiveArithmeticWarning):
            with pytest.warns(WheneverDeprecationWarning, match="ignore_dst"):
                d.add(hours=48, seconds=5, nanoseconds=3, ignore_dst=True)

            with pytest.warns(WheneverDeprecationWarning, match="ignore_dst"):
                d.subtract(hours=48, seconds=5, nanoseconds=3, ignore_dst=True)

    @suppress(NaiveArithmeticWarning)
    def test_valid(self):
        d = PlainDateTime(2020, 8, 15, 23, 12, 9, nanosecond=987_654)
        shifted = PlainDateTime(2020, 5, 27, 23, 12, 14, nanosecond=987_651)

        assert d.add() == d

        assert (
            d.add(
                months=-3,
                days=10,
                hours=48,
                seconds=5,
                nanoseconds=-3,
            )
            == shifted
        )

        # same result with deltas
        assert (
            d.add(hours(48) + seconds(5) + nanoseconds(-3))
            .add(months(-3))
            .add(days(10))
        ) == shifted

        # same result with subtract()
        assert (
            d.subtract(
                months=3,
                days=-10,
                hours=-48,
                seconds=-5,
                nanoseconds=3,
            )
            == shifted
        )

        # same result with deltas
        assert (
            d.subtract(hours(-48) + seconds(-5) + nanoseconds(3))
            .subtract(months(3))
            .subtract(days(-10))
        ) == shifted

        assert d.subtract(months=3) == d.add(months=-3)

    @suppress(NaiveArithmeticWarning)
    def test_invalid(self):
        d = PlainDateTime(2020, 8, 15, 23, 12, 9, nanosecond=987_654)
        with pytest.raises((ValueError, OverflowError), match="range|year"):
            d.add(hours=24 * 365 * 8000)

        with pytest.raises((ValueError, OverflowError), match="range|year"):
            d.add(hours=-24 * 365 * 3000)

        with pytest.raises((TypeError, AttributeError)):
            d.add(4)  # type: ignore[call-overload]

        # mixing args/kwargs
        with pytest.raises(TypeError):
            d.add(hours(48), seconds=5)  # type: ignore[call-overload]

        # tempt an i128 overflow
        with pytest.raises((ValueError, OverflowError), match="range|year"):
            d.add(nanoseconds=1 << 127 - 1)

    @given(
        years=integers(),
        months=integers(),
        days=integers(),
        hours=floats(),
        minutes=floats(),
        seconds=floats(),
        milliseconds=floats(),
        microseconds=floats(),
        nanoseconds=integers(),
    )
    @suppress(NaiveArithmeticWarning)
    def test_fuzzing(self, **kwargs):
        d = PlainDateTime(2020, 8, 15, 23, 12, 9, nanosecond=987_654_321)
        try:
            d.add(**kwargs)
        except (ValueError, OverflowError):
            pass


class TestShiftOperators:

    def test_date_delta(self):
        d = PlainDateTime(2020, 8, 15, 23, 12, 9, nanosecond=987_654)
        shifted = d.replace(year=2021, day=19)
        assert d + (years(1) + weeks(1) + days(-3)) == shifted

        # same results with subtraction
        assert d - (years(-1) + weeks(-1) + days(3)) == shifted

        with pytest.raises((ValueError, OverflowError), match="range|year"):
            d + years(8_000)

        with pytest.raises((ValueError, OverflowError), match="range|year"):
            d + days(366 * 8_000)

        with pytest.raises((ValueError, OverflowError), match="range|year"):
            d + years(-3_000)

        with pytest.raises((ValueError, OverflowError), match="range|year"):
            d + days(-366 * 8_000)

    def test_timedelta(self):
        d = PlainDateTime(2020, 8, 15, 23, 12, 9, nanosecond=987_654)
        with suppress(NaiveArithmeticWarning):
            assert d.add(hours=48, seconds=5, nanoseconds=3) == d + TimeDelta(
                hours=48, seconds=5, nanoseconds=3
            )
            assert d.subtract(
                hours=48, seconds=5, nanoseconds=3
            ) == d - TimeDelta(hours=48, seconds=5, nanoseconds=3)

        # operators trigger warning (exactly one warning each)
        with pytest.warns(NaiveArithmeticWarning) as w:
            d + TimeDelta(hours=48, seconds=5, nanoseconds=3)
        assert len(w) == 1

        # operators trigger warning (exactly one warning each)
        with pytest.warns(NaiveArithmeticWarning) as w:
            d - TimeDelta(hours=48, seconds=5, nanoseconds=3)
        assert len(w) == 1

    def test_invalid(self):
        d = PlainDateTime(2020, 8, 15, 23, 12, 9, nanosecond=987_654)
        with pytest.raises(TypeError, match="unsupported operand type"):
            d + 42  # type: ignore[operator]
        with pytest.raises(TypeError, match="unsupported operand type"):
            42 + d  # type: ignore[operator]
        with pytest.raises(TypeError, match="unsupported operand type"):
            seconds(4) + d  # type: ignore[operator]


class TestDifference:
    def test_method(self):
        d = PlainDateTime(2020, 8, 15, 23, 12, 9, nanosecond=987_654_000)
        other = PlainDateTime(2020, 8, 14, 23, 12, 4, nanosecond=987_654_321)
        with suppress(NaiveArithmeticWarning):
            assert d.difference(d) == hours(0)
            assert d.difference(other) == hours(24) + seconds(5) - nanoseconds(
                321
            )

    def test_operator(self):
        d = PlainDateTime(2020, 8, 15, 23, 12, 9, nanosecond=987_654_000)
        other = PlainDateTime(2020, 8, 14, 23, 12, 4, nanosecond=987_654_321)
        with suppress(NaiveArithmeticWarning):
            assert d - d == hours(0)
            assert d - other == hours(24) + seconds(5) - nanoseconds(321)

        with pytest.warns(NaiveArithmeticWarning) as w:
            d - other
        assert len(w) == 1

    def test_invalid(self):
        d = PlainDateTime(2020, 8, 15, 23, 12, 9, nanosecond=987_654)

        with pytest.raises(TypeError):
            d - 43  # type: ignore[operator]


class TestRound:

    @pytest.mark.parametrize(
        "d, increment, unit, floor, ceil, half_floor, half_ceil, half_even",
        [
            (
                PlainDateTime(2023, 7, 14, 1, 2, 3, nanosecond=459_999_999),
                1,
                "nanosecond",
                PlainDateTime(2023, 7, 14, 1, 2, 3, nanosecond=459_999_999),
                PlainDateTime(2023, 7, 14, 1, 2, 3, nanosecond=459_999_999),
                PlainDateTime(2023, 7, 14, 1, 2, 3, nanosecond=459_999_999),
                PlainDateTime(2023, 7, 14, 1, 2, 3, nanosecond=459_999_999),
                PlainDateTime(2023, 7, 14, 1, 2, 3, nanosecond=459_999_999),
            ),
            (
                PlainDateTime(2023, 7, 14, 1, 2, 3, nanosecond=459_999_999),
                1,
                "second",
                PlainDateTime(2023, 7, 14, 1, 2, 3),
                PlainDateTime(2023, 7, 14, 1, 2, 4),
                PlainDateTime(2023, 7, 14, 1, 2, 3),
                PlainDateTime(2023, 7, 14, 1, 2, 3),
                PlainDateTime(2023, 7, 14, 1, 2, 3),
            ),
            (
                PlainDateTime(2023, 7, 14, 1, 2, 21, nanosecond=459_999_999),
                4,
                "second",
                PlainDateTime(2023, 7, 14, 1, 2, 20),
                PlainDateTime(2023, 7, 14, 1, 2, 24),
                PlainDateTime(2023, 7, 14, 1, 2, 20),
                PlainDateTime(2023, 7, 14, 1, 2, 20),
                PlainDateTime(2023, 7, 14, 1, 2, 20),
            ),
            (
                PlainDateTime(2023, 7, 14, 23, 52, 29, nanosecond=999_999_999),
                10,
                "minute",
                PlainDateTime(2023, 7, 14, 23, 50, 0),
                PlainDateTime(2023, 7, 15),
                PlainDateTime(2023, 7, 14, 23, 50, 0),
                PlainDateTime(2023, 7, 14, 23, 50, 0),
                PlainDateTime(2023, 7, 14, 23, 50, 0),
            ),
            (
                PlainDateTime(2023, 7, 14, 23, 52, 29, nanosecond=999_999_999),
                60,
                "minute",
                PlainDateTime(2023, 7, 14, 23),
                PlainDateTime(2023, 7, 15),
                PlainDateTime(2023, 7, 15),
                PlainDateTime(2023, 7, 15),
                PlainDateTime(2023, 7, 15),
            ),
            (
                PlainDateTime(2023, 7, 14, 11, 59, 29, nanosecond=999_999_999),
                12,
                "hour",
                PlainDateTime(2023, 7, 14),
                PlainDateTime(2023, 7, 14, 12, 0, 0),
                PlainDateTime(2023, 7, 14, 12, 0, 0),
                PlainDateTime(2023, 7, 14, 12, 0, 0),
                PlainDateTime(2023, 7, 14, 12, 0, 0),
            ),
            (
                PlainDateTime(2023, 7, 14, 12),
                1,
                "day",
                PlainDateTime(2023, 7, 14),
                PlainDateTime(2023, 7, 15),
                PlainDateTime(2023, 7, 14),
                PlainDateTime(2023, 7, 15),
                PlainDateTime(2023, 7, 14),
            ),
            (
                PlainDateTime(2023, 7, 14),
                1,
                "day",
                PlainDateTime(2023, 7, 14),
                PlainDateTime(2023, 7, 14),
                PlainDateTime(2023, 7, 14),
                PlainDateTime(2023, 7, 14),
                PlainDateTime(2023, 7, 14),
            ),
        ],
    )
    def test_round(
        self,
        d: PlainDateTime,
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
        d = PlainDateTime(2023, 7, 14, 1, 2, 3, nanosecond=500_000_000)
        assert d.round() == PlainDateTime(2023, 7, 14, 1, 2, 4)
        assert d.replace(second=8).round() == PlainDateTime(
            2023, 7, 14, 1, 2, 8
        )

    def test_invalid_mode(self):
        d = PlainDateTime(2023, 7, 14, 1, 2, 3, nanosecond=4_000)
        with pytest.raises(ValueError, match="Invalid.*mode.*foo"):
            d.round("second", mode="foo")  # type: ignore[call-overload]

    @pytest.mark.parametrize(
        "unit, increment",
        [
            ("minute", 21),
            ("second", 14),
            ("millisecond", 534),
            ("day", 2),
            ("hour", 48),
            ("microsecond", 2001),
        ],
    )
    def test_invalid_increment(self, unit, increment):
        d = PlainDateTime(2023, 7, 14, 1, 2, 3, nanosecond=4_000)
        with pytest.raises(ValueError, match="[Ii]ncrement"):
            d.round(unit, increment=increment)

    def test_default_increment(self):
        d = PlainDateTime(2023, 7, 14, 1, 2, 3, nanosecond=800_000)
        assert d.round("millisecond") == PlainDateTime(
            2023, 7, 14, 1, 2, 3, nanosecond=1_000_000
        )

    def test_invalid_unit(self):
        d = PlainDateTime(2023, 7, 14, 1, 2, 3, nanosecond=4_000)
        with pytest.raises(ValueError, match="Invalid.*unit.*foo"):
            d.round("foo")  # type: ignore[call-overload]

    def test_out_of_range(self):
        d = PlainDateTime.MAX.replace(nanosecond=0)
        with pytest.raises((ValueError, OverflowError), match="range"):
            d.round("second", increment=5)

    def test_round_by_timedelta(self):
        d = PlainDateTime(2020, 8, 15, 23, 24, 18)
        assert d.round(TimeDelta(minutes=15)) == PlainDateTime(
            2020, 8, 15, 23, 30
        )
        assert d.round(TimeDelta(hours=1)) == PlainDateTime(2020, 8, 15, 23)
        assert d.round(TimeDelta(minutes=15), mode="floor") == PlainDateTime(
            2020, 8, 15, 23, 15
        )

    def test_round_by_timedelta_wraps_to_next_day(self):
        d = PlainDateTime(2020, 8, 15, 23, 50)
        assert d.round(TimeDelta(hours=1)) == PlainDateTime(2020, 8, 16)

    def test_round_by_timedelta_invalid_not_divides_day(self):
        d = PlainDateTime(2020, 8, 15, 12)
        with pytest.raises(ValueError, match="24.hour"):
            d.round(TimeDelta(hours=7))

    def test_round_by_timedelta_negative(self):
        d = PlainDateTime(2020, 8, 15, 12)
        with pytest.raises(ValueError, match="positive"):
            d.round(TimeDelta(hours=-1))

    def test_round_by_timedelta_with_increment(self):
        d = PlainDateTime(2020, 8, 15, 12)
        with pytest.raises(TypeError):
            d.round(TimeDelta(hours=1), increment=2)  # type: ignore[call-overload]


def test_replace_date():
    d = PlainDateTime(2020, 8, 15, 3, 12, 9)
    assert d.replace_date(Date(1996, 2, 19)) == PlainDateTime(
        1996, 2, 19, 3, 12, 9
    )
    with pytest.raises((TypeError, AttributeError)):
        d.replace_date(42)  # type: ignore[arg-type]


def test_replace_time():
    d = PlainDateTime(2020, 8, 15, 3, 12, 9)
    assert d.replace_time(Time(1, 2, 3)) == PlainDateTime(2020, 8, 15, 1, 2, 3)
    with pytest.raises((TypeError, AttributeError)):
        d.replace_time(42)  # type: ignore[arg-type]


def test_pickle():
    d = PlainDateTime(2020, 8, 15, 23, 12, 9, nanosecond=987_654)
    dumped = pickle.dumps(d)
    assert len(dumped) <= len(pickle.dumps(d.to_stdlib())) + 10
    assert pickle.loads(pickle.dumps(d)) == d


def test_old_pickle_data_remains_unpicklable():
    # Don't update this value -- the whole idea is that it's a pickle at
    # a specific version of the library.
    dumped = (
        b"\x80\x04\x95/\x00\x00\x00\x00\x00\x00\x00\x8c\x08whenever\x94\x8c\x0c_unp"
        b"kl_local\x94\x93\x94C\x0b\xe4\x07\x08\x0f\x17\x0c\t\x06\x12\x0f\x00"
        b"\x94\x85\x94R\x94."
    )
    assert pickle.loads(dumped) == PlainDateTime(
        2020, 8, 15, 23, 12, 9, nanosecond=987_654
    )


class TestParseStrptime:

    def test_strptime(self):
        assert PlainDateTime.parse_strptime(
            "2020-08-15 23:12", format="%Y-%m-%d %H:%M"
        ) == PlainDateTime(2020, 8, 15, 23, 12)

    def test_strptime_invalid(self):
        # offset now allowed
        with pytest.raises(ValueError):
            PlainDateTime.parse_strptime(
                "2020-08-15 23:12:09+0500", format="%Y-%m-%d %H:%M:%S%z"
            )

        # format is keyword-only
        with pytest.raises(TypeError, match="format|argument"):
            OffsetDateTime.parse_strptime(
                "2020-08-15 23:12:09", "%Y-%m-%d %H:%M:%S"  # type: ignore[misc]
            )


class TestSince:

    @pytest.mark.parametrize(
        "a, b, units, kwargs, expect",
        [
            # simple cases involving only calendar units
            (
                PlainDateTime(2023, 10, 29, hour=11),
                PlainDateTime(2023, 10, 28, hour=11),
                ["days"],
                {},
                ItemizedDelta(days=1),
            ),
            (
                PlainDateTime(2023, 10, 29, hour=11),
                PlainDateTime(2023, 10, 28, hour=10),
                ["days"],
                {},
                ItemizedDelta(days=1),
            ),
            (
                PlainDateTime(2025, 5, 31, hour=23),
                PlainDateTime(2023, 1, 28, hour=1),
                ["years", "months", "days"],
                {},
                ItemizedDelta(years=2, months=4, days=3),
            ),
            # Negative delta date truncation handled correctly
            (
                PlainDateTime(2022, 2, 2),
                PlainDateTime(2022, 2, 5),
                ["days"],
                {},
                ItemizedDelta(days=-3),
            ),
            (
                PlainDateTime(2022, 2, 2, hour=3),
                PlainDateTime(2022, 2, 5, hour=2),
                ["days", "hours"],
                {},
                ItemizedDelta(days=-2, hours=-23),
            ),
            (
                PlainDateTime(2022, 2, 2, hour=3),
                PlainDateTime(2022, 2, 5, hour=2),
                ["days"],
                {},
                ItemizedDelta(days=-2),
            ),
            (
                PlainDateTime(2022, 2, 2, hour=3),
                PlainDateTime(2022, 2, 5, hour=2),
                ["days"],
                {"round_mode": "floor"},
                ItemizedDelta(days=-3),
            ),
            # calendar units only--but with time-of-day differences
            # that affect rounding
            (
                PlainDateTime(2025, 5, 31, hour=4),
                PlainDateTime(2023, 1, 28, hour=4, nanosecond=1),
                ["years", "months", "days"],
                {},
                ItemizedDelta(years=2, months=4, days=2),
            ),
            # same but with rounding
            (
                PlainDateTime(2025, 5, 31, hour=4),
                PlainDateTime(2023, 1, 28, hour=4, nanosecond=1),
                ["years", "months", "days"],
                {"round_increment": 3, "round_mode": "half_ceil"},
                ItemizedDelta(years=2, months=4, days=3),
            ),
            (
                PlainDateTime(2025, 5, 31, hour=4),
                PlainDateTime(2025, 5, 1, hour=4, nanosecond=1),
                ["years", "months", "days"],
                {"round_increment": 40, "round_mode": "floor"},
                ItemizedDelta(years=0, months=0, days=0),
            ),
            # Rounding affected by time-of-day
            (
                PlainDateTime(2023, 2, 15, hour=13, minute=25),
                PlainDateTime(2021, 7, 3, hour=1),
                ["years", "days"],
                {"round_mode": "floor"},
                ItemizedDelta(years=1, days=227),
            ),
            (
                PlainDateTime(2023, 2, 15, hour=13, minute=25),
                PlainDateTime(2021, 7, 3, hour=1),
                ["years", "days"],
                {"round_mode": "half_even"},
                ItemizedDelta(years=1, days=228),
            ),
            # Beyond calendar units
            (
                PlainDateTime(2023, 2, 15, hour=13, minute=25),
                PlainDateTime(2021, 7, 3, hour=1),
                ["years", "weeks", "hours"],
                {"round_mode": "floor"},
                ItemizedDelta(years=1, weeks=32, hours=84),
            ),
            (
                PlainDateTime(2023, 2, 15, hour=13, minute=25),
                PlainDateTime(2021, 7, 3, hour=1),
                ["years", "weeks", "minutes"],
                {"round_mode": "ceil", "round_increment": 12},
                ItemizedDelta(years=1, weeks=32, minutes=5076),
            ),
            (
                PlainDateTime(2020, 2, 15, hour=13, minute=25),
                PlainDateTime(2021, 7, 3, hour=1),
                ["hours", "minutes"],
                {"round_mode": "ceil", "round_increment": 12},
                ItemizedDelta(hours=-12083, minutes=-24),
            ),
            # Zero situations
            (
                PlainDateTime(2020, 2, 15, hour=13, minute=25),
                PlainDateTime(2021, 7, 3, hour=1),
                ["years"],
                {"round_mode": "trunc", "round_increment": 4},
                ItemizedDelta(years=0),
            ),
            (
                PlainDateTime(2023, 2, 15, hour=13, minute=25),
                PlainDateTime(2021, 7, 3, hour=1),
                ["months"],
                {"round_mode": "trunc", "round_increment": 50},
                ItemizedDelta(months=0),
            ),
            (
                PlainDateTime(2023, 2, 15, hour=13, minute=25),
                PlainDateTime(2023, 2, 15, hour=13, minute=25),
                ["weeks"],
                {},
                ItemizedDelta(weeks=0),
            ),
            (
                PlainDateTime(2023, 2, 15, hour=13, minute=25),
                PlainDateTime(2023, 2, 15, hour=13, minute=25),
                ["seconds"],
                {},
                ItemizedDelta(seconds=0),
            ),
            # single unit cases
            (
                PlainDateTime(2023, 2, 15, hour=13, minute=25),
                PlainDateTime(2023, 2, 15, hour=13, minute=25, nanosecond=1),
                ["seconds"],
                {},
                ItemizedDelta(seconds=0),
            ),
            (
                PlainDateTime(2023, 2, 15, hour=13, minute=25),
                PlainDateTime(2023, 2, 15, hour=13, minute=25, second=1),
                ["seconds"],
                {},
                ItemizedDelta(seconds=-1),
            ),
            # multi-unit with time precision
            (
                PlainDateTime(2025, 6, 15, hour=14, minute=30, second=45),
                PlainDateTime(2025, 6, 15, hour=10, minute=15, second=20),
                ["hours", "minutes", "seconds"],
                {},
                ItemizedDelta(hours=4, minutes=15, seconds=25),
            ),
            # negative result across date boundary
            (
                PlainDateTime(2020, 1, 1),
                PlainDateTime(2020, 12, 31, hour=23, minute=59),
                ["days", "hours", "minutes"],
                {},
                ItemizedDelta(days=-365, hours=-23, minutes=-59),
            ),
            # years, months, days, hours, minutes, seconds
            (
                PlainDateTime(2025, 3, 15, hour=14, minute=30, second=45),
                PlainDateTime(2023, 1, 10, hour=8, minute=15, second=20),
                ["years", "months", "days", "hours", "minutes", "seconds"],
                {},
                ItemizedDelta(
                    years=2, months=2, days=5, hours=6, minutes=15, seconds=25
                ),
            ),
            # months and hours
            (
                PlainDateTime(2025, 3, 15, hour=14),
                PlainDateTime(2025, 1, 15, hour=10),
                ["months", "hours"],
                {},
                ItemizedDelta(months=2, hours=4),
            ),
            # seconds and nanoseconds
            (
                PlainDateTime(2025, 3, 15, hour=12, second=5, nanosecond=500),
                PlainDateTime(2025, 3, 15, hour=12, nanosecond=100),
                ["seconds", "nanoseconds"],
                {},
                ItemizedDelta(seconds=5, nanoseconds=400),
            ),
            # rounding with exact units at the smallest position
            (
                PlainDateTime(2025, 3, 15, hour=14, minute=37),
                PlainDateTime(2025, 3, 1, hour=10, minute=22),
                ["days", "hours", "minutes"],
                {"round_increment": 15, "round_mode": "ceil"},
                ItemizedDelta(days=14, hours=4, minutes=15),
            ),
            # day boundary: time of day causes day adjustment
            (
                PlainDateTime(2025, 3, 15, hour=2),
                PlainDateTime(2025, 3, 14, hour=22),
                ["days", "hours"],
                {},
                ItemizedDelta(days=0, hours=4),
            ),
            # leap year boundary
            (
                PlainDateTime(2024, 2, 29, hour=12),
                PlainDateTime(2023, 2, 28, hour=12),
                ["years", "days"],
                {},
                ItemizedDelta(years=1, days=1),
            ),
            (
                PlainDateTime(2024, 3, 1),
                PlainDateTime(2023, 3, 1),
                ["years", "months", "days"],
                {},
                ItemizedDelta(years=1, months=0, days=0),
            ),
            # end of month edge case
            (
                PlainDateTime(2025, 3, 31, hour=12),
                PlainDateTime(2025, 2, 28, hour=12),
                ["months", "days"],
                {},
                ItemizedDelta(months=1, days=3),
            ),
        ],
    )
    def test_examples(
        self,
        a: PlainDateTime,
        b: PlainDateTime,
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
        with suppress(NaiveArithmeticWarning):
            assert a.since(b, in_units=units, **kwargs).exact_eq(expect)

    def test_warnings(self):
        a = PlainDateTime(2023, 2, 15, hour=13, minute=25)
        b = PlainDateTime(2021, 7, 3, hour=1)

        # exact output units trigger the warning
        with pytest.warns(NaiveArithmeticWarning) as w:
            a.since(b, in_units=["hours", "minutes"])
        assert len(w) == 1

        with pytest.warns(NaiveArithmeticWarning) as w:
            a.until(b, in_units=["hours", "minutes"])
        assert len(w) == 1

        # mixed calendar+exact output also triggers (has exact)
        with pytest.warns(NaiveArithmeticWarning) as w:
            a.since(b, in_units=["days", "hours"])
        assert len(w) == 1

        # total with exact unit triggers the warning
        with pytest.warns(NaiveArithmeticWarning) as w:
            a.since(b, total="hours")
        assert len(w) == 1

        # calendar-only output: no warning (counting calendar units needs no clock awareness)
        with warnings.catch_warnings():
            warnings.simplefilter("error")
            a.since(b, in_units=["months", "weeks"])
            a.until(b, in_units=["months", "weeks"])
            a.since(b, total="days")
            a.since(b, total="years")

        # suppression works
        with suppress(NaiveArithmeticWarning):
            a.since(b, in_units=["hours", "minutes"])
            a.until(b, total="hours")

    def test_invalid_units(self):
        with pytest.raises(ValueError, match="[Ii]nvalid unit.*foos"):
            PlainDateTime(2023, 2, 15).since(
                PlainDateTime(2023, 2, 15),
                in_units=["foos"],  # type: ignore[list-item]
            )

        with pytest.raises(ValueError, match="[Ii]nvalid unit.*foos"):
            PlainDateTime(2023, 2, 15).since(
                PlainDateTime(2023, 2, 15),
                total="foos",  # type: ignore[call-overload]
            )

    def test_empty_units(self):
        with pytest.raises(ValueError, match="[Aa]t least one unit"):
            PlainDateTime(2023, 2, 15).since(
                PlainDateTime(2023, 2, 15),
                in_units=(),
            )

    @suppress(NaiveArithmeticWarning)
    def test_no_other_class_supported(self):
        with pytest.raises(TypeError):
            PlainDateTime(2023, 2, 15).since(
                ZonedDateTime(2023, 2, 15, tz="Europe/London"),  # type: ignore[call-overload]
                in_units=["days"],
            )

    def test_neither_unit_nor_units(self):
        with pytest.raises(
            TypeError, match="Must specify|total.*or.*in_units"
        ):
            PlainDateTime(2023, 2, 15).since(
                PlainDateTime(2023, 2, 15),
            )  # type: ignore[call-overload]

    def test_both_unit_and_units(self):
        with pytest.raises(TypeError, match="both"):
            PlainDateTime(2023, 2, 15).since(
                PlainDateTime(2023, 2, 15),
                total="years",
                in_units=("days",),
            )  # type: ignore[call-overload]

    def test_duplicate_units(self):
        with pytest.raises(ValueError, match="duplicate"):
            PlainDateTime(2023, 2, 15).since(
                PlainDateTime(2023, 2, 15),
                in_units=["years", "days", "days"],
            )

    def test_invalid_unit_order(self):
        with pytest.raises(ValueError, match="order"):
            PlainDateTime(2021, 1, 1).since(
                PlainDateTime(2020, 1, 1), in_units=["hours", "days"]
            )

    @suppress(NaiveArithmeticWarning)
    def test_invalid_round_mode(self):
        # round_mode and round_increment are not supported with total=
        with pytest.raises(TypeError, match="round_mode.*total|total.*round"):
            PlainDateTime(2021, 1, 1).since(
                PlainDateTime(2020, 1, 1),
                total="years",
                round_mode="floor",
            )  # type: ignore[call-overload]

        # even round_increment=1 is rejected (no default magic)
        with pytest.raises(TypeError, match="round_mode.*total|total.*round"):
            PlainDateTime(2021, 1, 1).since(
                PlainDateTime(2020, 1, 1),
                total="years",
                round_increment=1,
            )  # type: ignore[call-overload]

        # round_mode is still valid with in_units
        with pytest.raises(ValueError, match="round.*mode.*foobar"):
            PlainDateTime(2021, 1, 1).since(
                PlainDateTime(2020, 1, 1),
                in_units=["years"],
                round_mode="foobar",
            )  # type: ignore[call-overload]

    @suppress(NaiveArithmeticWarning)
    def test_until_is_inverse(self):
        a = PlainDateTime(2023, 2, 15, hour=3)
        b = PlainDateTime(2021, 7, 3)
        assert a.since(
            b, in_units=["years", "months", "days", "hours"]
        ).exact_eq(b.until(a, in_units=["years", "months", "days", "hours"]))
        # floor rounding works correctly
        assert a.since(
            b,
            in_units=["years", "months", "days", "hours"],
            round_increment=2,
            round_mode="floor",
        ).exact_eq(
            b.until(
                a,
                in_units=["years", "months", "days", "hours"],
                round_increment=2,
                round_mode="floor",
            )
        )

    @suppress(NaiveArithmeticWarning)
    def test_until_rounding_symmetry(self):
        a = PlainDateTime(2019, 1, 30, hour=5)
        b = PlainDateTime(2020, 2, 1, hour=12)
        # until with trunc
        result_trunc = a.until(
            b, in_units=["years", "months"], round_mode="trunc"
        )
        assert result_trunc == ItemizedDelta(years=1, months=0)
        # until with floor
        result_floor = a.until(
            b, in_units=["years", "months"], round_mode="floor"
        )
        assert result_floor == ItemizedDelta(years=1, months=0)
        # until with ceil
        result_ceil = a.until(
            b, in_units=["years", "months"], round_mode="ceil"
        )
        assert result_ceil == ItemizedDelta(years=1, months=1)

    @suppress(NaiveArithmeticWarning)
    def test_single_unit_returns_float(self):
        a = PlainDateTime(2025, 3, 15)
        b = PlainDateTime(2023, 3, 15)
        result = a.since(b, total="years")
        assert isinstance(result, float)
        assert result == 2.0

    def test_roundtrip_add_back(self):
        """Verify that adding the since() result back gives the original datetime."""
        with suppress(NaiveArithmeticWarning):
            a = PlainDateTime(2025, 6, 15, hour=14, minute=30, second=45)
            b = PlainDateTime(2023, 1, 10, hour=8, minute=15, second=20)
            result = a.since(
                b,
                in_units=[
                    "years",
                    "months",
                    "days",
                    "hours",
                    "minutes",
                    "seconds",
                ],
            )
            assert (
                b.add(
                    years=result["years"],
                    months=result["months"],
                    days=result["days"],
                    hours=result["hours"],
                    minutes=result["minutes"],
                    seconds=result["seconds"],
                )
                == a
            )

    def test_roundtrip_negative(self):
        """Verify roundtrip for negative results."""
        with suppress(NaiveArithmeticWarning):
            a = PlainDateTime(2020, 1, 1)
            b = PlainDateTime(2025, 6, 15, hour=14)
            result = a.since(b, in_units=["years", "months", "days", "hours"])
            assert (
                b.add(
                    years=result["years"],
                    months=result["months"],
                    days=result["days"],
                    hours=result["hours"],
                )
                == a
            )

    @suppress(NaiveArithmeticWarning)
    def test_nanoseconds_dont_overflow(self):
        a = PlainDateTime(9000, 1, 1)
        b = PlainDateTime(23, 3, 15)
        assert a.since(b, total="nanoseconds") == 283280457600000000000

    @suppress(NaiveArithmeticWarning)
    def test_very_large_increment(self):
        a = PlainDateTime(2023, 2, 15)
        b = PlainDateTime(2021, 7, 3)
        # round_increment=1<<65 ns exceeds i64::MAX; ceil mode rounds up to 1*(1<<65)
        assert a.since(
            b,
            in_units=["seconds", "nanoseconds"],
            round_increment=1 << 65,
            round_mode="ceil",
        ) == ItemizedDelta(seconds=36_893_488_147, nanoseconds=419_103_232)


class TestDeprecations:
    def test_py_datetime(self):
        d = PlainDateTime(2020, 8, 15, 23, 12, 9, nanosecond=987_654_823)
        with pytest.warns(WheneverDeprecationWarning):
            result = d.py_datetime()
        assert result == py_datetime(2020, 8, 15, 23, 12, 9, 987_654)

    def test_from_py_datetime(self):
        with pytest.warns(WheneverDeprecationWarning):
            result = PlainDateTime.from_py_datetime(
                py_datetime(2020, 8, 15, 23, 12, 9, 987_654)
            )
        assert result == PlainDateTime(
            2020, 8, 15, 23, 12, 9, nanosecond=987_654_000
        )


def test_cannot_subclass():
    with pytest.raises(TypeError):

        class Subclass(PlainDateTime):  # type: ignore[misc]
            pass


class TestDayOfYear:

    def test_basic(self):
        assert PlainDateTime(2024, 2, 29, 12, 30).day_of_year() == 60

    def test_jan1(self):
        assert PlainDateTime(2023, 1, 1, 0, 0).day_of_year() == 1

    def test_dec31_nonleap(self):
        assert PlainDateTime(2023, 12, 31, 23, 59).day_of_year() == 365


class TestDaysInMonth:

    def test_feb_leap(self):
        assert PlainDateTime(2024, 2, 29, 12, 30).days_in_month() == 29

    def test_feb_nonleap(self):
        assert PlainDateTime(2023, 2, 15, 12, 30).days_in_month() == 28

    def test_january(self):
        assert PlainDateTime(2023, 1, 15, 12, 30).days_in_month() == 31


class TestDaysInYear:

    def test_leap(self):
        assert PlainDateTime(2024, 2, 29, 12, 30).days_in_year() == 366

    def test_nonleap(self):
        assert PlainDateTime(2023, 6, 15, 12, 30).days_in_year() == 365


class TestInLeapYear:

    def test_leap(self):
        assert PlainDateTime(2024, 2, 29, 12, 30).in_leap_year() is True

    def test_nonleap(self):
        assert PlainDateTime(2023, 6, 15, 12, 30).in_leap_year() is False


class TestStartOf:

    def test_year(self):
        dt = PlainDateTime(2024, 8, 15, 14, 30, 45, nanosecond=123)
        result = dt.start_of("year")
        assert result == PlainDateTime(2024, 1, 1)
        assert result.nanosecond == 0

    def test_month(self):
        dt = PlainDateTime(2024, 8, 15, 14, 30, 45, nanosecond=123)
        result = dt.start_of("month")
        assert result == PlainDateTime(2024, 8, 1)
        assert result.nanosecond == 0

    def test_day(self):
        dt = PlainDateTime(2024, 8, 15, 14, 30, 45, nanosecond=123)
        result = dt.start_of("day")
        assert result == PlainDateTime(2024, 8, 15)
        assert result.nanosecond == 0

    def test_hour(self):
        dt = PlainDateTime(2024, 8, 15, 14, 30, 45, nanosecond=123)
        result = dt.start_of("hour")
        assert result == PlainDateTime(2024, 8, 15, 14)
        assert result.nanosecond == 0

    def test_minute(self):
        dt = PlainDateTime(2024, 8, 15, 14, 30, 45, nanosecond=123)
        result = dt.start_of("minute")
        assert result == PlainDateTime(2024, 8, 15, 14, 30)
        assert result.nanosecond == 0

    def test_second(self):
        dt = PlainDateTime(2024, 8, 15, 14, 30, 45, nanosecond=123)
        result = dt.start_of("second")
        assert result == PlainDateTime(2024, 8, 15, 14, 30, 45)
        assert result.nanosecond == 0

    def test_invalid_unit(self):
        with pytest.raises(ValueError, match="Invalid (unit|value for unit)"):
            PlainDateTime(2024, 8, 15, 14, 30).start_of("week")  # type: ignore[arg-type]


class TestEndOf:

    def test_year(self):
        dt = PlainDateTime(2024, 8, 15, 14, 30, 45, nanosecond=123)
        result = dt.end_of("year")
        assert result == PlainDateTime(
            2024, 12, 31, 23, 59, 59, nanosecond=999_999_999
        )

    def test_month_31_days(self):
        dt = PlainDateTime(2024, 8, 15, 14, 30)
        result = dt.end_of("month")
        assert result == PlainDateTime(
            2024, 8, 31, 23, 59, 59, nanosecond=999_999_999
        )

    def test_month_feb_leap(self):
        dt = PlainDateTime(2024, 2, 10, 12)
        result = dt.end_of("month")
        assert result == PlainDateTime(
            2024, 2, 29, 23, 59, 59, nanosecond=999_999_999
        )

    def test_month_feb_non_leap(self):
        dt = PlainDateTime(2023, 2, 10, 12)
        result = dt.end_of("month")
        assert result == PlainDateTime(
            2023, 2, 28, 23, 59, 59, nanosecond=999_999_999
        )

    def test_day(self):
        dt = PlainDateTime(2024, 8, 15, 14, 30, 45, nanosecond=123)
        result = dt.end_of("day")
        assert result == PlainDateTime(
            2024, 8, 15, 23, 59, 59, nanosecond=999_999_999
        )

    def test_hour(self):
        dt = PlainDateTime(2024, 8, 15, 14, 30, 45, nanosecond=123)
        result = dt.end_of("hour")
        assert result == PlainDateTime(
            2024, 8, 15, 14, 59, 59, nanosecond=999_999_999
        )

    def test_minute(self):
        dt = PlainDateTime(2024, 8, 15, 14, 30, 45, nanosecond=123)
        result = dt.end_of("minute")
        assert result == PlainDateTime(
            2024, 8, 15, 14, 30, 59, nanosecond=999_999_999
        )

    def test_second(self):
        dt = PlainDateTime(2024, 8, 15, 14, 30, 45, nanosecond=123)
        result = dt.end_of("second")
        assert result == PlainDateTime(
            2024, 8, 15, 14, 30, 45, nanosecond=999_999_999
        )

    def test_invalid_unit(self):
        with pytest.raises(ValueError, match="Invalid (unit|value for unit)"):
            PlainDateTime(2024, 8, 15, 14, 30).end_of("week")  # type: ignore[arg-type]
