import re
import warnings
from datetime import datetime as py_datetime, timezone
from fractions import Fraction
from typing import Any, Literal, Sequence, cast

import pytest
from hypothesis import given
from hypothesis.strategies import floats, integers, text
from whenever import (
    MONDAY,
    SATURDAY,
    SYSTEM_TZ,
    Date,
    ImplicitDisambiguationWarning,
    Instant,
    ItemizedDateDelta,
    ItemizedDelta,
    NaiveArithmeticWarning,
    OffsetDateTime,
    PlainDateTime,
    RepeatedTime,
    SkippedTime,
    Time,
    TimeDelta,
    TimeZoneNotFoundError,
    ZonedDateTime,
    hours,
    nanoseconds,
    seconds,
)

from .common import (
    AMS_TZ_POSIX,
    Idx,
    StrSubclass,
    suppress,
    system_tz,
    warns_here,
)

# Thursday, August 15
_THURSDAY_AFTERNOON = PlainDateTime(2024, 8, 15, 14, 30, 45, nanosecond=123)


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

    def test_single_argument_wrong_type(self):
        with pytest.raises(
            TypeError,
            match=r"^PlainDateTime\(\) requires an ISO 8601 string or datetime.datetime$",
        ):
            PlainDateTime(None)  # type: ignore[call-overload]

    def test_defaults(self):
        assert PlainDateTime(2020, 8, 15) == PlainDateTime(
            2020, 8, 15, 0, 0, 0, nanosecond=0
        )

    @pytest.mark.parametrize(
        "args, kwargs",
        [
            ((2020, 8, 15, 5, 12, 30, 450), {}),
            ((), {"iso_string": "2020-08-15T05:12:30"}),
            ((), {"py_datetime": py_datetime(2020, 8, 15)}),
        ],
    )
    def test_parameter_kinds(self, args, kwargs):
        with pytest.raises(TypeError):
            PlainDateTime(*args, **kwargs)

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


class TestInitFromPy:
    def test_valid(self):
        d = py_datetime(2020, 8, 15, 23, 12, 9, 987_654)
        assert PlainDateTime(d) == PlainDateTime(
            2020, 8, 15, 23, 12, 9, nanosecond=987_654_000
        )

        with pytest.raises(
            ValueError,
            match=r"^datetime must be naive, got tzinfo=datetime\.timezone\.utc$",
        ):
            PlainDateTime(
                py_datetime(
                    2020, 8, 15, 23, 12, 9, 987_654, tzinfo=timezone.utc
                )
            )

        class MyDateTime(py_datetime):
            pass

        assert PlainDateTime(
            MyDateTime(2020, 8, 15, 23, 12, 9, 987_654)
        ) == PlainDateTime(2020, 8, 15, 23, 12, 9, nanosecond=987_654_000)

    def test_keyword_rejected(self):
        with pytest.raises(
            TypeError,
            match=r"^PlainDateTime\(\) got an unexpected keyword argument 'nanosecond'$",
        ):
            PlainDateTime(py_datetime(2020, 8, 15), nanosecond=1)  # type: ignore[call-overload]

    def test_drops_fold(self):
        # fold means nothing without a time zone, so it isn't carried
        assert (
            PlainDateTime(py_datetime(2023, 10, 29, 2, 30, fold=1))
            .to_stdlib()
            .fold
            == 0
        )


class TestAccessors:
    def test_components(self):
        d = PlainDateTime(2020, 8, 15, 23, 12, 9, nanosecond=987_654_123)
        assert d.date() == Date(2020, 8, 15)
        assert d.time() == Time(23, 12, 9, nanosecond=987_654_123)

    def test_min_max(self):
        assert PlainDateTime.MIN == PlainDateTime(1, 1, 1)
        assert PlainDateTime.MAX == PlainDateTime(
            9999, 12, 31, 23, 59, 59, nanosecond=999_999_999
        )

    def test_day_of_week(self):
        assert PlainDateTime(2024, 3, 9, 22).day_of_week() is SATURDAY
        assert PlainDateTime(2024, 12, 30).day_of_week() is MONDAY


class TestConversion:
    def test_assume_utc(self):
        assert PlainDateTime(2020, 8, 15, 23).assume_utc() == Instant.from_utc(
            2020, 8, 15, 23
        )

    def test_assume_fixed_offset(self):
        assert (
            PlainDateTime(2020, 8, 15, 23)
            .assume_fixed_offset(hours(5))
            .strict_eq(OffsetDateTime(2020, 8, 15, 23, offset=hours(5)))
        )
        assert (
            PlainDateTime(2020, 8, 15, 23)
            .assume_fixed_offset(hours(-2))
            .strict_eq(OffsetDateTime(2020, 8, 15, 23, offset=hours(-2)))
        )

    def test_to_stdlib(self):
        d = PlainDateTime(2020, 8, 15, 23, 12, 9, nanosecond=987_654_823)
        assert d.to_stdlib() == py_datetime(2020, 8, 15, 23, 12, 9, 987_654)


class TestAssumeTz:
    def test_typical(self):
        d = PlainDateTime(2020, 8, 15, 23)
        assert d.assume_tz("Asia/Tokyo", disambiguation="raise").strict_eq(
            ZonedDateTime(2020, 8, 15, 23, tz="Asia/Tokyo")
        )
        assert d.assume_tz("Asia/Tokyo").strict_eq(
            ZonedDateTime(2020, 8, 15, 23, tz="Asia/Tokyo")
        )

    def test_repeated_time(self):
        d = PlainDateTime(2023, 10, 29, 2, 15)

        with pytest.raises(RepeatedTime, match="02:15.*Europe/Amsterdam"):
            d.assume_tz("Europe/Amsterdam", disambiguation="raise")

        assert d.assume_tz(
            "Europe/Amsterdam", disambiguation="earlier"
        ).strict_eq(
            ZonedDateTime(
                2023,
                10,
                29,
                2,
                15,
                tz="Europe/Amsterdam",
                disambiguation="earlier",
            )
        )
        assert d.assume_tz(
            "Europe/Amsterdam", disambiguation="later"
        ).strict_eq(
            ZonedDateTime(
                2023,
                10,
                29,
                2,
                15,
                tz="Europe/Amsterdam",
                disambiguation="later",
            )
        )

    @pytest.mark.parametrize(
        "d",
        [
            PlainDateTime(2023, 10, 29, 2, 15),  # repeated
            PlainDateTime(2023, 3, 26, 2, 15),  # skipped
        ],
    )
    def test_implicit_disambiguation_warns(self, d):
        with warns_here(ImplicitDisambiguationWarning):
            implicit = d.assume_tz("Europe/Amsterdam")
        with warnings.catch_warnings():
            warnings.simplefilter("error")
            explicit = d.assume_tz(
                "Europe/Amsterdam", disambiguation="compatible"
            )
        assert implicit.strict_eq(explicit)

    def test_wrong_type(self):
        with pytest.raises(
            TypeError, match="^tz must be a string or SYSTEM_TZ$"
        ):
            PlainDateTime(2020, 8, 15).assume_tz(3)

    def test_unknown_tz_id(self):
        with pytest.raises(TimeZoneNotFoundError):
            PlainDateTime(2020, 8, 15).assume_tz("Europe/Nowhere")

    def test_skipped_time(self):
        d = PlainDateTime(2023, 3, 26, 2, 15)

        with pytest.raises(SkippedTime, match="02:15.*Europe/Amsterdam"):
            d.assume_tz("Europe/Amsterdam", disambiguation="raise")

        assert d.assume_tz(
            "Europe/Amsterdam", disambiguation="earlier"
        ).strict_eq(
            ZonedDateTime(
                2023,
                3,
                26,
                2,
                15,
                tz="Europe/Amsterdam",
                disambiguation="earlier",
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
                zdt = dt.assume_tz(SYSTEM_TZ, disambiguation="raise")
                assert isinstance(zdt, ZonedDateTime)
                assert zdt.to_plain() == dt
                assert zdt.offset == hours(2)

                if tz == "Europe/Amsterdam":
                    assert zdt.tz_id == "Europe/Amsterdam"

    @pytest.mark.parametrize(
        "tz",
        [
            "Europe/Amsterdam",
            AMS_TZ_POSIX,
        ],
    )
    def test_repeated_time(self, tz):
        with system_tz(tz):
            d = PlainDateTime(2023, 10, 29, 2, 15)

            with pytest.raises(RepeatedTime, match="02:15.*is repeated"):
                d.assume_tz(SYSTEM_TZ, disambiguation="raise")

            zdt1 = d.assume_tz(SYSTEM_TZ, disambiguation="earlier")
            assert isinstance(zdt1, ZonedDateTime)
            assert zdt1.to_plain() == d
            assert zdt1.offset == hours(2)

            # posix TZ string cannot be checked
            if tz == "Europe/Amsterdam":
                assert zdt1.tz_id == "Europe/Amsterdam"

            assert d.assume_tz(
                SYSTEM_TZ, disambiguation="compatible"
            ).strict_eq(zdt1)

            zdt2 = d.assume_tz(SYSTEM_TZ, disambiguation="later")
            assert isinstance(zdt2, ZonedDateTime)
            assert zdt2.to_plain() == d
            assert zdt2.offset == hours(1)

            # posix TZ string cannot be checked
            if tz == "Europe/Amsterdam":
                assert zdt2.tz_id == "Europe/Amsterdam"

    @pytest.mark.parametrize(
        "tz",
        [
            "Europe/Amsterdam",
            AMS_TZ_POSIX,
        ],
    )
    @suppress(NaiveArithmeticWarning)
    def test_skipped_time(self, tz):
        with system_tz(tz):
            d = PlainDateTime(2023, 3, 26, 2, 15)

            with pytest.raises(SkippedTime, match="02:15.*is skipped"):
                d.assume_tz(SYSTEM_TZ, disambiguation="raise")

            zdt1 = d.assume_tz(SYSTEM_TZ, disambiguation="earlier")
            assert isinstance(zdt1, ZonedDateTime)
            assert zdt1.to_plain() == d.subtract(hours=1)
            assert zdt1.offset == hours(1)
            # posix TZ string cannot be checked
            if tz == "Europe/Amsterdam":
                assert zdt1.tz_id == "Europe/Amsterdam"

            zdt2 = d.assume_tz(SYSTEM_TZ, disambiguation="later")
            assert isinstance(zdt2, ZonedDateTime)
            assert zdt2.to_plain() == d.add(hours=1)
            assert zdt2.offset == hours(2)
            # posix TZ string cannot be checked
            if tz == "Europe/Amsterdam":
                assert zdt2.tz_id == "Europe/Amsterdam"

            assert d.assume_tz(
                SYSTEM_TZ, disambiguation="compatible"
            ).strict_eq(zdt2)


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
            (
                PlainDateTime(2020, 8, 15, 23, 45),
                {"unit": "hour"},
                "2020-08-15T23",
            ),
        ],
    )
    def test_variations(self, dt, kwargs, expected):
        assert dt.format_iso(**kwargs) == expected

    @pytest.mark.parametrize(
        "kwargs",
        [{}, {"basic": True}, {"sep": " "}, {"unit": "hour"}],
    )
    def test_round_trip(self, kwargs):
        d = PlainDateTime(2020, 8, 15, 23)
        assert PlainDateTime.parse_iso(d.format_iso(**kwargs)) == d

    def test_invalid(self):
        dt = PlainDateTime(2020, 4, 9, 13)
        with pytest.raises(ValueError, match="unit"):
            dt.format_iso(unit="foo")  # type: ignore[arg-type]

        with pytest.raises(ValueError, match="invalid unit"):
            dt.format_iso(unit=True)  # type: ignore[arg-type]

        with pytest.raises(ValueError, match="sep"):
            dt.format_iso(sep="_")  # type: ignore[arg-type]

        with pytest.raises(ValueError, match="invalid sep"):
            dt.format_iso(sep=1)  # type: ignore[arg-type]

        # tz is a valid kwarg for ZonedDateTime.format_iso(), but not here
        with pytest.raises(TypeError, match="tz"):
            dt.format_iso(tz="always")  # type: ignore[call-arg]

    def test_repr(self):
        d = PlainDateTime(2020, 8, 15, 23, 12, 9, nanosecond=987_654)
        assert repr(d) == 'PlainDateTime("2020-08-15 23:12:09.000987654")'
        # no fractional seconds
        assert (
            repr(PlainDateTime(2020, 8, 15, 23, 12))
            == 'PlainDateTime("2020-08-15 23:12:00")'
        )


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
            "20200815XXT12:30",  # junk after a basic-format date
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
            # basic-format time is HH/HHMM/HHMMSS, not a separatorless fraction
            "20200815T12083000",
            "2020-08-15T120830123",
            "2020-08-15T120830.",
        ],
    )
    def test_invalid(self, s):
        with pytest.raises(
            ValueError,
            match=r"^invalid ISO 8601 string: " + re.escape(repr(s)) + "$",
        ):
            PlainDateTime.parse_iso(s)

    @given(text())
    def test_fuzzing(self, s: str):
        with pytest.raises(
            ValueError,
            match=r"^invalid ISO 8601 string: " + re.escape(repr(s)) + "$",
        ):
            PlainDateTime.parse_iso(s)


class TestEquality:
    def test_same_and_different(self):
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

        # no mixing with aware types:
        assert d != d.assume_utc()  # type: ignore[comparison-overlap]
        assert d != d.assume_fixed_offset(hours(3))  # type: ignore[comparison-overlap]

        # A repeated local time in the system time zone doesn't affect equality
        with system_tz("Europe/Amsterdam"):
            assert PlainDateTime(2023, 10, 29, 2, 15) == PlainDateTime(
                py_datetime(2023, 10, 29, 2, 15, fold=1)
            )


class TestComparison:
    def test_ordering(self):
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

        with pytest.raises(TypeError):
            d < 42  # type: ignore[operator]


class TestReplace:
    def test_fields(self):
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
        assert d.replace(day=31).replace(month=10) == PlainDateTime(
            2020, 10, 31, 23, 12, 9, nanosecond=987_654
        )

        # a result that is not a valid date
        with pytest.raises(ValueError, match="date|day"):
            d.replace(day=31).replace(month=4)

        with pytest.raises(ValueError, match="date|day"):
            d.replace(year=2023, month=2, day=29)

        with pytest.raises(ValueError, match="nano|time"):
            d.replace(nanosecond=1_000_000_000)

        with pytest.raises(ValueError, match="nano|time"):
            d.replace(nanosecond=-4)

        with pytest.raises(TypeError, match="nanosecond"):
            d.replace(nanosecond=1.5)  # type: ignore[arg-type]

        with pytest.raises(TypeError, match="tzinfo"):
            d.replace(tzinfo=timezone.utc)  # type: ignore[call-arg]

    def test_date(self):
        d = PlainDateTime(2020, 8, 15, 3, 12, 9, nanosecond=987_654)
        # the datetime's nanoseconds are kept
        assert d.replace_date(Date(1996, 2, 19)) == PlainDateTime(
            1996, 2, 19, 3, 12, 9, nanosecond=987_654
        )
        with pytest.raises((TypeError, AttributeError)):
            d.replace_date(42)  # type: ignore[arg-type]

    def test_time(self):
        d = PlainDateTime(2020, 8, 15, 3, 12, 9, nanosecond=987_654)
        # the time's nanoseconds replace the datetime's
        assert d.replace_time(Time(1, 2, 3, nanosecond=4)) == PlainDateTime(
            2020, 8, 15, 1, 2, 3, nanosecond=4
        )
        with pytest.raises((TypeError, AttributeError)):
            d.replace_time(42)  # type: ignore[arg-type]


class TestShift:
    @suppress(NaiveArithmeticWarning)
    def test_no_arguments(self):
        d = PlainDateTime(2020, 8, 15)
        assert d.add(naive_arithmetic_ok=True) == d

    @pytest.mark.parametrize(
        "delta, kwargs",
        [
            (ItemizedDateDelta(days=1), {"days": 1}),
            (ItemizedDelta(days=1, hours=2), {"days": 1, "hours": 2}),
        ],
    )
    @suppress(NaiveArithmeticWarning)
    def test_itemized_delta_arguments(self, delta, kwargs):
        d = PlainDateTime(2020, 8, 15, 23, 12, 9)
        assert d.add(delta) == d.add(**kwargs)

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

    @pytest.mark.parametrize(
        ("call", "exc", "message"),
        [
            (
                lambda d: d.add(hours="x"),
                TypeError,
                "hours must be an integer or float",
            ),
            (
                lambda d: d.add(hours=1, days=1.5),
                TypeError,
                "days must be an integer",
            ),
            (
                lambda d: d.subtract(hours=float("nan")),
                ValueError,
                "value or calculation out of range",
            ),
            (
                lambda d: d.add(hours=1, bogus=1),
                TypeError,
                "add() got an unexpected keyword argument 'bogus'",
            ),
            (
                lambda d: d.add(hours(1), hours=1),
                TypeError,
                "add() cannot mix positional and keyword arguments",
            ),
            (
                lambda d: d.subtract(hours(1), hours(1)),
                TypeError,
                "subtract() takes at most one positional argument (2 given)",
            ),
            (
                lambda d: d.add(4),
                TypeError,
                "add() argument must be a TimeDelta, ItemizedDelta, or ItemizedDateDelta",
            ),
        ],
    )
    def test_rejected_argument_does_not_warn(self, call, exc, message):
        d = PlainDateTime(2020, 8, 15, 23, 12, 9)
        with pytest.raises(exc, match="^" + re.escape(message) + "$"):
            call(d)

    def test_operator_out_of_range(self):
        with suppress(NaiveArithmeticWarning):
            with pytest.raises(
                ValueError, match="^value or calculation out of range$"
            ):
                PlainDateTime.MAX + hours(1)
            with pytest.raises(
                ValueError, match="^value or calculation out of range$"
            ):
                PlainDateTime.MIN - hours(1)

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

    def test_operators(self):
        d = PlainDateTime(2020, 8, 15, 23, 12, 9, nanosecond=987_654)
        with suppress(NaiveArithmeticWarning):
            assert d.add(hours=48, seconds=5, nanoseconds=3) == d + TimeDelta(
                hours=48, seconds=5, nanoseconds=3
            )
            assert d.subtract(
                hours=48, seconds=5, nanoseconds=3
            ) == d - TimeDelta(hours=48, seconds=5, nanoseconds=3)

        # operators trigger warning (exactly one warning each)
        with warns_here(NaiveArithmeticWarning) as w:
            d + TimeDelta(hours=48, seconds=5, nanoseconds=3)
        assert len(w) == 1
        assert (
            "pass `naive_arithmetic_ok=True` to `add()`, `subtract()`, "
            "`difference()`, `since()`, or `until()`; `+` and `-` take no "
            "keyword" in str(w[0].message)
        )

        # operators trigger warning (exactly one warning each)
        with warns_here(NaiveArithmeticWarning) as w:
            d - TimeDelta(hours=48, seconds=5, nanoseconds=3)
        assert len(w) == 1

    def test_operators_invalid(self):
        d = PlainDateTime(2020, 8, 15, 23, 12, 9, nanosecond=987_654)
        with pytest.raises(TypeError, match="unsupported operand type"):
            d + 42  # type: ignore[operator]
        with pytest.raises(TypeError, match="unsupported operand type"):
            42 + d  # type: ignore[operator]


class TestNaiveArithmeticOkKwarg:
    def test_truthiness_error_propagates(self):
        class BadBool:
            def __bool__(self):
                raise RuntimeError("bool failed")

        d = PlainDateTime(2020, 8, 15, 23, 12, 9)
        with pytest.raises(RuntimeError, match="bool failed"):
            d.add(  # type: ignore[call-overload]
                hours=1,
                naive_arithmetic_ok=BadBool(),
            )

    def test_add(self):
        d = PlainDateTime(2020, 8, 15, 23, 12, 9, nanosecond=987_654)
        with warnings.catch_warnings():
            warnings.simplefilter("error")
            d.add(hours=1, naive_arithmetic_ok=True)

    def test_subtract(self):
        d = PlainDateTime(2020, 8, 15, 23, 12, 9, nanosecond=987_654)
        with warnings.catch_warnings():
            warnings.simplefilter("error")
            d.subtract(hours=1, naive_arithmetic_ok=True)

    def test_difference(self):
        d = PlainDateTime(2020, 8, 15, 23, 12, 9, nanosecond=987_654)
        other = PlainDateTime(2020, 8, 14, 23, 12, 4, nanosecond=987_654)
        with warnings.catch_warnings():
            warnings.simplefilter("error")
            d.difference(other, naive_arithmetic_ok=True)
        with warns_here(NaiveArithmeticWarning) as w:
            d.difference(other)
        assert len(w) == 1

    @pytest.mark.parametrize(
        "call",
        [
            lambda d, **kw: d.add(hours=1, **kw),
            lambda d, **kw: d.subtract(hours=1, **kw),
            lambda d, **kw: d.add(hours(1), **kw),
            lambda d, **kw: d.subtract(hours(1), **kw),
            lambda d, **kw: d.add(ItemizedDelta(hours=1), **kw),
            lambda d, **kw: d.add(months=1, hours=1, **kw),
        ],
    )
    def test_every_exact_form_warns_once(self, call):
        d = PlainDateTime(2020, 8, 15, 23, 12, 9)
        with warns_here(NaiveArithmeticWarning) as w:
            call(d)
        assert len(w) == 1
        with warnings.catch_warnings():
            warnings.simplefilter("error")
            call(d, naive_arithmetic_ok=True)

    def test_read_by_truthiness(self):
        d = PlainDateTime(2020, 8, 15, 23, 12, 9)
        with warnings.catch_warnings():
            warnings.simplefilter("error")
            d.add(hours=1, naive_arithmetic_ok=1)  # type: ignore[call-overload]
        with warns_here(NaiveArithmeticWarning):
            d.add(hours=1, naive_arithmetic_ok="")  # type: ignore[call-overload]

    def test_since(self):
        a = PlainDateTime(2023, 2, 15, hour=13, minute=25)
        b = PlainDateTime(2021, 7, 3, hour=1)
        with warnings.catch_warnings():
            warnings.simplefilter("error")
            a.since(b, total="hours", naive_arithmetic_ok=True)

    def test_since_in_units(self):
        a = PlainDateTime(2023, 2, 15, hour=13, minute=25)
        b = PlainDateTime(2021, 7, 3, hour=1)
        with warnings.catch_warnings():
            warnings.simplefilter("error")
            a.since(
                b,
                in_units=["hours", "minutes"],
                naive_arithmetic_ok=True,
            )

    def test_until(self):
        a = PlainDateTime(2023, 2, 15, hour=13, minute=25)
        b = PlainDateTime(2021, 7, 3, hour=1)
        with warnings.catch_warnings():
            warnings.simplefilter("error")
            a.until(b, total="hours", naive_arithmetic_ok=True)

    def test_until_in_units(self):
        a = PlainDateTime(2023, 2, 15, hour=13, minute=25)
        b = PlainDateTime(2021, 7, 3, hour=1)
        with warnings.catch_warnings():
            warnings.simplefilter("error")
            a.until(
                b,
                in_units=["hours", "minutes"],
                naive_arithmetic_ok=True,
            )


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

        with warns_here(NaiveArithmeticWarning) as w:
            d - other
        assert len(w) == 1

    def test_invalid(self):
        d = PlainDateTime(2020, 8, 15, 23, 12, 9, nanosecond=987_654)

        with pytest.raises(TypeError):
            d - 43  # type: ignore[operator]

    @pytest.mark.parametrize(
        "other",
        [43, hours(1), OffsetDateTime(2020, 8, 15, offset=hours(1))],
    )
    def test_rejects_other_types_without_warning(self, other):
        d = PlainDateTime(2020, 8, 15, 23, 12, 9)
        with pytest.raises(
            TypeError,
            match="^difference\\(\\) argument must be a PlainDateTime$",
        ):
            d.difference(other)


class TestSince:
    @pytest.mark.parametrize(
        ("unit", "expected"),
        [
            ("milliseconds", 86_400_000.0),
            ("microseconds", 86_400_000_000.0),
        ],
    )
    def test_total_subsecond_units(self, unit, expected):
        a = PlainDateTime(2023, 2, 15)
        b = PlainDateTime(2023, 2, 14)
        with warns_here(NaiveArithmeticWarning):
            assert a.since(b, total=unit) == expected

    @pytest.mark.parametrize(
        ("kwargs", "message"),
        [
            (
                {"in_units": ["hours"], "round_mode": "bad"},
                "invalid round_mode: 'bad'",
            ),
            (
                {"in_units": ["days"], "round_increment": 0},
                "round_increment must be a positive integer in range",
            ),
            (
                {"in_units": ["hours"], "round_increment": -1},
                "round_increment must be a positive integer in range",
            ),
            (
                {"in_units": ["hours"], "round_increment": 1.5},
                "round_increment must be an integer",
            ),
            (
                {"in_units": ["hours"], "round_increment": None},
                "round_increment must be an integer",
            ),
            (
                {"in_units": ["hours", "nanoseconds"]},
                "nanoseconds can only be specified together with seconds",
            ),
            ({"total": "foo"}, "invalid unit: 'foo'"),
            ({"in_units": ["foos"]}, "invalid unit: 'foos'"),
            ({"in_units": ()}, "units must not be empty"),
            ({}, "must specify either 'total' or 'in_units'"),
            (
                {"total": "years", "in_units": ("days",)},
                "cannot specify both 'total' and 'in_units'",
            ),
            (
                {"in_units": ["years", "days", "days"]},
                "units cannot contain duplicates",
            ),
            (
                {"in_units": ["hours", "days"]},
                "units must be in decreasing order of size",
            ),
            # round_mode and round_increment are not supported with total=,
            # not even round_increment=1
            (
                {"total": "years", "round_mode": "floor"},
                "'round_mode' and 'round_increment' cannot be used with "
                "'total'",
            ),
            (
                {"total": "years", "round_increment": 1},
                "'round_mode' and 'round_increment' cannot be used with "
                "'total'",
            ),
            (
                {"in_units": ["years"], "round_mode": "foobar"},
                "invalid round_mode: 'foobar'",
            ),
        ],
    )
    @pytest.mark.parametrize("method", ["since", "until"])
    def test_rejected_argument_does_not_warn(self, method, kwargs, message):
        a = PlainDateTime(2023, 2, 15)
        b = PlainDateTime(2023, 2, 14)
        with pytest.raises(
            (TypeError, ValueError), match="^" + re.escape(message) + "$"
        ):
            getattr(a, method)(b, **kwargs)

    @pytest.mark.parametrize(
        "other",
        [
            OffsetDateTime(2023, 2, 14, offset=hours(1)),
            ZonedDateTime(2023, 2, 15, tz="Europe/London"),
        ],
    )
    @pytest.mark.parametrize("method", ["since", "until"])
    def test_rejects_other_types(self, method, other):
        a = PlainDateTime(2023, 2, 15)
        with pytest.raises(
            TypeError,
            match=f"^{method}\\(\\) argument must be a PlainDateTime$",
        ):
            getattr(a, method)(other, total="hours")

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
            assert a.since(b, in_units=units, **kwargs).strict_eq(expect)

    def test_warnings(self):
        a = PlainDateTime(2023, 2, 15, hour=13, minute=25)
        b = PlainDateTime(2021, 7, 3, hour=1)

        # exact output units trigger the warning
        with warns_here(NaiveArithmeticWarning) as w:
            a.since(b, in_units=["hours", "minutes"])
        assert len(w) == 1

        with warns_here(NaiveArithmeticWarning) as w:
            a.until(b, in_units=["hours", "minutes"])
        assert len(w) == 1

        # mixed calendar+exact output also triggers (has exact)
        with warns_here(NaiveArithmeticWarning) as w:
            a.since(b, in_units=["days", "hours"])
        assert len(w) == 1

        # total with exact unit triggers the warning
        with warns_here(NaiveArithmeticWarning) as w:
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

    @suppress(NaiveArithmeticWarning)
    def test_until_is_inverse(self):
        a = PlainDateTime(2023, 2, 15, hour=3)
        b = PlainDateTime(2021, 7, 3)
        assert a.since(
            b, in_units=["years", "months", "days", "hours"]
        ).strict_eq(b.until(a, in_units=["years", "months", "days", "hours"]))
        # floor rounding works correctly
        assert a.since(
            b,
            in_units=["years", "months", "days", "hours"],
            round_increment=2,
            round_mode="floor",
        ).strict_eq(
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
    def test_rounding_up_carries_into_larger_units(self):
        assert PlainDateTime(2024, 1, 1).until(
            PlainDateTime(2024, 3, 1, 23, 30),
            in_units=["months", "days", "hours"],
            round_mode="ceil",
        ) == ItemizedDelta(months=2, days=1, hours=0)
        assert PlainDateTime(2027, 4, 30, 2, 0, 25).until(
            PlainDateTime(1992, 3, 16, 2, 0, 57, nanosecond=112_130_543),
            in_units=["months", "days", "hours"],
            round_mode="floor",
        ) == ItemizedDelta(months=-421, days=-14, hours=0)

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

    def test_increment_read_through_index(self):
        d = PlainDateTime(2023, 7, 14, 12, 39, 59)
        assert d.round("minute", increment=True) == d.round("minute")
        assert d.round("minute", increment=cast(int, Idx())) == d.round(
            "minute", increment=5
        )

    @pytest.mark.parametrize("hour, expect", [(12, 12), (13, 14)])
    def test_half_even_tie(self, hour, expect):
        d = PlainDateTime(2023, 7, 14, hour, 30)
        assert d.round("hour") == PlainDateTime(2023, 7, 14, expect)

    def test_default_increment(self):
        d = PlainDateTime(2023, 7, 14, 1, 2, 3, nanosecond=800_000)
        assert d.round("millisecond") == PlainDateTime(
            2023, 7, 14, 1, 2, 3, nanosecond=1_000_000
        )

    def test_range_edges(self):
        assert PlainDateTime.MAX.round("hour", mode="floor") == PlainDateTime(
            9999, 12, 31, 23
        )
        with pytest.raises(
            ValueError, match="^value or calculation out of range$"
        ):
            PlainDateTime.MAX.round("hour", mode="ceil")
        with pytest.raises(
            ValueError, match="^value or calculation out of range$"
        ):
            PlainDateTime.MAX.replace(nanosecond=0).round(
                "second", increment=5
            )

        just_after_min = PlainDateTime.MIN.replace(second=1)
        assert just_after_min.round("hour", mode="floor") == PlainDateTime.MIN
        assert just_after_min.round("hour", mode="ceil") == PlainDateTime(
            1, 1, 1, 1
        )

    def test_round_by_timedelta(self):
        d = PlainDateTime(2020, 8, 15, 23, 24, 18)
        assert d.round(TimeDelta(minutes=15)) == PlainDateTime(
            2020, 8, 15, 23, 30
        )
        assert d.round(hours(1)) == PlainDateTime(2020, 8, 15, 23)
        assert d.round(TimeDelta(minutes=15), mode="floor") == PlainDateTime(
            2020, 8, 15, 23, 15
        )

    def test_round_by_timedelta_wraps_to_next_day(self):
        d = PlainDateTime(2020, 8, 15, 23, 50)
        assert d.round(hours(1)) == PlainDateTime(2020, 8, 16)

    @pytest.mark.parametrize(
        "d, unit, kwargs, exc, message",
        [
            # a value already on the increment validates the mode too
            *(
                (d, "second", {"mode": m}, ValueError, f"invalid mode: {m!r}")
                for d in (
                    PlainDateTime(2023, 7, 14, 1, 2, 3, nanosecond=4_000),
                    PlainDateTime(2023, 7, 14, 1, 2, 3),
                )
                for m in ("foo", "TRUNC", None, 3)
            ),
            *(
                (
                    PlainDateTime(2023, 7, 14, 1, 2, 3, nanosecond=4_000),
                    u,
                    {"increment": i},
                    ValueError,
                    "increment must divide a 24-hour day evenly",
                )
                for u, i in (
                    ("minute", 21),
                    ("second", 14),
                    ("millisecond", 534),
                    ("day", 2),
                    ("hour", 48),
                    ("microsecond", 2001),
                    ("second", 1 << 62),
                )
            ),
            *(
                (
                    PlainDateTime(2023, 7, 14, 1, 2, 3),
                    "second",
                    {"increment": i},
                    ValueError,
                    "increment must be a positive integer",
                )
                for i in (0, -1)
            ),
            *(
                (
                    PlainDateTime(2023, 7, 14, 1, 2, 3),
                    "second",
                    {"increment": i},
                    TypeError,
                    "increment must be an integer",
                )
                for i in (1.5, float("nan"), "5", Fraction(3, 2))
            ),
            *(
                (
                    PlainDateTime(2023, 7, 14, 1, 2, 3, nanosecond=4_000),
                    u,
                    {},
                    ValueError,
                    f"invalid unit: {u!r}",
                )
                for u in ("foo", "week", "minutes", None, 5)
            ),
            *(
                (
                    PlainDateTime(2020, 8, 15, 12),
                    u,
                    {},
                    ValueError,
                    "unit must divide a 24-hour day evenly",
                )
                for u in (hours(7), hours(25))
            ),
            *(
                (
                    PlainDateTime(2020, 8, 15, 12),
                    u,
                    {},
                    ValueError,
                    "unit must be a positive TimeDelta",
                )
                for u in (hours(-1), TimeDelta.ZERO)
            ),
            *(
                (
                    PlainDateTime(2020, 8, 15, 12),
                    hours(1),
                    {"increment": i},
                    TypeError,
                    "cannot specify an increment with a TimeDelta argument",
                )
                for i in (1, 2)
            ),
        ],
    )
    def test_rejected(self, d, unit, kwargs, exc, message):
        with pytest.raises(exc, match="^" + re.escape(message) + "$"):
            d.round(unit, **kwargs)


class TestStartOf:
    @pytest.mark.parametrize(
        ("unit", "expected"),
        [
            ("year", PlainDateTime(2024, 1, 1)),
            ("day", PlainDateTime(2024, 8, 15)),
            ("hour", PlainDateTime(2024, 8, 15, 14)),
        ],
    )
    def test_str_subclass(self, unit, expected):
        dt = PlainDateTime(2024, 8, 15, 14, 30, 45, nanosecond=123)
        assert dt.start_of(StrSubclass(unit)) == expected  # type: ignore[arg-type]

    @pytest.mark.parametrize(
        "d, unit, expected",
        [
            (_THURSDAY_AFTERNOON, "year", PlainDateTime(2024, 1, 1)),
            (_THURSDAY_AFTERNOON, "month", PlainDateTime(2024, 8, 1)),
            (_THURSDAY_AFTERNOON, "day", PlainDateTime(2024, 8, 15)),
            (_THURSDAY_AFTERNOON, "hour", PlainDateTime(2024, 8, 15, 14)),
            (
                _THURSDAY_AFTERNOON,
                "minute",
                PlainDateTime(2024, 8, 15, 14, 30),
            ),
            (
                _THURSDAY_AFTERNOON,
                "second",
                PlainDateTime(2024, 8, 15, 14, 30, 45),
            ),
            (_THURSDAY_AFTERNOON, "week_mon", PlainDateTime(2024, 8, 12)),
            (_THURSDAY_AFTERNOON, "week_sun", PlainDateTime(2024, 8, 11)),
            # already at the start of the week
            (
                PlainDateTime(2024, 8, 12, 10),
                "week_mon",
                PlainDateTime(2024, 8, 12),
            ),
            (
                PlainDateTime(2024, 8, 11, 10),
                "week_sun",
                PlainDateTime(2024, 8, 11),
            ),
        ],
    )
    def test_unit(self, d, unit, expected):
        assert d.start_of(unit) == expected

    def test_invalid_unit(self):
        with pytest.raises(ValueError, match="^invalid unit: 'invalid'$"):
            PlainDateTime(2024, 8, 15, 14, 30).start_of("invalid")  # type: ignore[arg-type]

    def test_week_value_error(self):
        with pytest.raises(
            ValueError,
            match="^invalid unit: 'week', use 'week_mon' or 'week_sun'$",
        ):
            PlainDateTime(2024, 8, 15, 14, 30).start_of("week")  # type: ignore[arg-type]

    def test_range_edges(self):
        # 0001-01-01 is a Monday, 9999-12-31 a Friday
        assert PlainDateTime.MIN.start_of("week_mon") == PlainDateTime.MIN
        with pytest.raises(
            ValueError, match="^value or calculation out of range$"
        ):
            PlainDateTime.MIN.start_of("week_sun")
        assert PlainDateTime.MAX.start_of("week_mon") == PlainDateTime(
            9999, 12, 27
        )
        assert PlainDateTime.MAX.start_of("week_sun") == PlainDateTime(
            9999, 12, 26
        )


class TestEndOf:
    @pytest.mark.parametrize(
        ("unit", "next_start"),
        [
            ("year", PlainDateTime(2025, 1, 1)),
            ("month", PlainDateTime(2024, 9, 1)),
            ("week_mon", PlainDateTime(2024, 8, 19)),
            ("week_sun", PlainDateTime(2024, 8, 18)),
            ("day", PlainDateTime(2024, 8, 16)),
            ("hour", PlainDateTime(2024, 8, 15, 15)),
            ("minute", PlainDateTime(2024, 8, 15, 14, 31)),
            ("second", PlainDateTime(2024, 8, 15, 14, 30, 46)),
        ],
    )
    def test_adjacent_to_next_start(self, unit, next_start):
        dt = PlainDateTime(2024, 8, 15, 14, 30, 45, nanosecond=123)
        assert (
            dt.end_of(unit).add(nanoseconds=1, naive_arithmetic_ok=True)
            == next_start
        )

    @pytest.mark.parametrize(
        "d, unit, expected",
        [
            (
                _THURSDAY_AFTERNOON,
                "year",
                PlainDateTime(
                    2024, 12, 31, 23, 59, 59, nanosecond=999_999_999
                ),
            ),
            (
                PlainDateTime(2024, 8, 15, 14, 30),
                "month",
                PlainDateTime(2024, 8, 31, 23, 59, 59, nanosecond=999_999_999),
            ),
            (
                PlainDateTime(2024, 2, 10, 12),
                "month",
                PlainDateTime(2024, 2, 29, 23, 59, 59, nanosecond=999_999_999),
            ),
            (
                PlainDateTime(2023, 2, 10, 12),
                "month",
                PlainDateTime(2023, 2, 28, 23, 59, 59, nanosecond=999_999_999),
            ),
            (
                _THURSDAY_AFTERNOON,
                "day",
                PlainDateTime(2024, 8, 15, 23, 59, 59, nanosecond=999_999_999),
            ),
            (
                _THURSDAY_AFTERNOON,
                "hour",
                PlainDateTime(2024, 8, 15, 14, 59, 59, nanosecond=999_999_999),
            ),
            (
                _THURSDAY_AFTERNOON,
                "minute",
                PlainDateTime(2024, 8, 15, 14, 30, 59, nanosecond=999_999_999),
            ),
            (
                _THURSDAY_AFTERNOON,
                "second",
                PlainDateTime(2024, 8, 15, 14, 30, 45, nanosecond=999_999_999),
            ),
            (
                _THURSDAY_AFTERNOON,
                "week_mon",
                PlainDateTime(2024, 8, 18, 23, 59, 59, nanosecond=999_999_999),
            ),
            (
                _THURSDAY_AFTERNOON,
                "week_sun",
                PlainDateTime(2024, 8, 17, 23, 59, 59, nanosecond=999_999_999),
            ),
            # already at the end of the week
            (
                PlainDateTime(2024, 8, 18, 10),
                "week_mon",
                PlainDateTime(2024, 8, 18, 23, 59, 59, nanosecond=999_999_999),
            ),
            (
                PlainDateTime(2024, 8, 17, 10),
                "week_sun",
                PlainDateTime(2024, 8, 17, 23, 59, 59, nanosecond=999_999_999),
            ),
        ],
    )
    def test_unit(self, d, unit, expected):
        assert d.end_of(unit) == expected

    def test_invalid_unit(self):
        with pytest.raises(ValueError, match="^invalid unit: 'invalid'$"):
            PlainDateTime(2024, 8, 15, 14, 30).end_of("invalid")  # type: ignore[arg-type]

    def test_week_value_error(self):
        with pytest.raises(
            ValueError,
            match="^invalid unit: 'week', use 'week_mon' or 'week_sun'$",
        ):
            PlainDateTime(2024, 8, 15, 14, 30).end_of("week")  # type: ignore[arg-type]

    def test_range_edges(self):
        # 0001-01-01 is a Monday, 9999-12-31 a Friday
        assert PlainDateTime.MIN.end_of("week_mon") == PlainDateTime(
            1, 1, 7, 23, 59, 59, nanosecond=999_999_999
        )
        assert PlainDateTime.MIN.end_of("week_sun") == PlainDateTime(
            1, 1, 6, 23, 59, 59, nanosecond=999_999_999
        )
        assert PlainDateTime.MAX.end_of("day") == PlainDateTime.MAX
        assert PlainDateTime.MAX.end_of("year") == PlainDateTime.MAX

    @pytest.mark.parametrize("unit", ["week_mon", "week_sun"])
    def test_week_beyond_max(self, unit):
        with pytest.raises(
            ValueError, match="^value or calculation out of range$"
        ):
            PlainDateTime.MAX.end_of(unit)


class TestCalendarProperties:
    @pytest.mark.parametrize(
        "d, expected",
        [
            (PlainDateTime(2024, 2, 29, 12, 30), 60),
            (PlainDateTime(2023, 1, 1, 0, 0), 1),
            (PlainDateTime(2023, 12, 31, 23, 59), 365),
            (PlainDateTime(2024, 12, 31, 23, 59), 366),
        ],
    )
    def test_day_of_year(self, d, expected):
        assert d.day_of_year() == expected

    @pytest.mark.parametrize(
        "d, expected",
        [
            (PlainDateTime(2024, 2, 29, 12, 30), 29),
            (PlainDateTime(2023, 2, 15, 12, 30), 28),
            (PlainDateTime(2023, 1, 15, 12, 30), 31),
            # 1900 is not a leap year (divisible by 100, not by 400)
            (PlainDateTime(1900, 2, 15, 12, 30), 28),
            # 2000 is a leap year (divisible by 400)
            (PlainDateTime(2000, 2, 15, 12, 30), 29),
        ],
    )
    def test_days_in_month(self, d, expected):
        assert d.days_in_month() == expected

    @pytest.mark.parametrize(
        "d, expected",
        [
            (PlainDateTime(2024, 2, 29, 12, 30), 366),
            (PlainDateTime(2023, 6, 15, 12, 30), 365),
            (PlainDateTime(1900, 6, 15, 12, 30), 365),
            (PlainDateTime(2000, 6, 15, 12, 30), 366),
        ],
    )
    def test_days_in_year(self, d, expected):
        assert d.days_in_year() == expected

    @pytest.mark.parametrize(
        "d, expected",
        [
            (PlainDateTime(2024, 2, 29, 12, 30), True),
            (PlainDateTime(2023, 6, 15, 12, 30), False),
            (PlainDateTime(1900, 6, 15, 12, 30), False),
            (PlainDateTime(2000, 6, 15, 12, 30), True),
        ],
    )
    def test_in_leap_year(self, d, expected):
        assert d.in_leap_year() is expected
