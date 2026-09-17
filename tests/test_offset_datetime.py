import re
import warnings
from datetime import datetime as py_datetime, timedelta, timezone, tzinfo
from fractions import Fraction
from typing import Any, Literal, Sequence, cast
from zoneinfo import ZoneInfo

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
    InvalidOffsetError,
    ItemizedDateDelta,
    ItemizedDelta,
    OffsetDateTime,
    PlainDateTime,
    RepeatedTime,
    SkippedTime,
    StaleOffsetWarning,
    Time,
    TimeDelta,
    TimeZoneNotFoundError,
    ZonedDateTime,
    hours,
    milliseconds,
    minutes,
    nanoseconds,
    patch_current_time,
    seconds,
)

from .common import (
    INVALID_ISO_STRINGS,
    VALID_ISO_STRINGS,
    DatetimeSubclass,
    Idx,
    suppress,
    system_tz,
    warns_here,
)


class TestInit:
    def test_init_and_attributes(self):
        d = OffsetDateTime(
            2020, 8, 15, 5, 12, 30, nanosecond=450, offset=hours(5)
        )
        assert d.year == 2020
        assert d.month == 8
        assert d.day == 15
        assert d.hour == 5
        assert d.minute == 12
        assert d.second == 30
        assert d.nanosecond == 450
        assert d.offset == hours(5)

    def test_offset_missing(self):
        with pytest.raises(
            TypeError,
            match=r"missing 1 required keyword-only argument: 'offset'$",
        ):
            OffsetDateTime(2020, 8, 15, 5, 12, 30, nanosecond=450)  # type: ignore[call-overload]

    def test_single_argument_wrong_type(self):
        with pytest.raises(
            TypeError,
            match=r"^OffsetDateTime\(\) requires an ISO 8601 string or datetime.datetime$",
        ):
            OffsetDateTime(1.5)  # type: ignore[call-overload]

    @pytest.mark.parametrize(
        "args, kwargs",
        [
            ((2020, 8, 15, 5, 12, 30, 450), {"offset": hours(5)}),
            ((2020, 8, 15, 5, 12, 30, hours(5)), {}),
            ((), {"iso_string": "2020-08-15T05:12:30+05:00"}),
            (
                (),
                {"py_datetime": py_datetime(2020, 8, 15, tzinfo=timezone.utc)},
            ),
        ],
    )
    def test_parameter_kinds(self, args, kwargs):
        with pytest.raises(TypeError):
            OffsetDateTime(*args, **kwargs)

    def test_invalid_offset_delta(self):
        # too large
        with pytest.raises(
            ValueError, match="offset must be between -24 and 24 hours"
        ):
            OffsetDateTime(2020, 8, 15, 5, 12, offset=hours(34))

        # too precise
        with pytest.raises(ValueError, match="(o|O)ffset.*whole.*seconds"):
            OffsetDateTime(
                2020, 8, 15, 5, 12, offset=hours(34) + milliseconds(1)
            )

        with pytest.raises(TypeError, match="offset must be"):
            OffsetDateTime(  # type: ignore[call-overload]
                2020, 8, 15, offset="+02:00"
            )

    def test_init_optionality(self):
        assert (
            OffsetDateTime(2020, 8, 15, 12, offset=hours(5))
            == OffsetDateTime(2020, 8, 15, 12, 0, offset=hours(5))
            == OffsetDateTime(2020, 8, 15, 12, 0, 0, offset=hours(5))
        )

    def test_kwargs(self):
        d = OffsetDateTime(
            year=2020,
            month=8,
            day=15,
            hour=5,
            minute=12,
            second=30,
            offset=hours(5),
        )
        assert d == OffsetDateTime(
            2020, 8, 15, 5, 12, 30, nanosecond=0, offset=hours(5)
        )

    def test_invalid(self):
        with pytest.raises(ValueError, match="date|day"):
            OffsetDateTime(2020, 2, 30, 5, 12, offset=hours(5))

        with pytest.raises(ValueError, match="time|minute"):
            OffsetDateTime(2020, 2, 28, 5, 64, offset=hours(5))

        with pytest.raises(ValueError, match="nano|time"):
            OffsetDateTime(
                2020,
                2,
                28,
                5,
                12,
                nanosecond=1_000_000_000,
                offset=hours(5),
            )

    def test_bounds(self):
        with pytest.raises(ValueError, match="range"):
            OffsetDateTime(1, 1, 1, 0, offset=hours(1))

    def test_iso_format(self):
        assert OffsetDateTime("2020-08-15T12:30:00+05:00").strict_eq(
            OffsetDateTime(2020, 8, 15, 12, 30, offset=hours(5))
        )


class TestInitFromPy:
    @pytest.mark.parametrize(
        "d, expect",
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
                    tzinfo=timezone(timedelta(hours=2)),
                ),
                OffsetDateTime(
                    2020,
                    8,
                    15,
                    23,
                    12,
                    9,
                    nanosecond=987_654_000,
                    offset=hours(2),
                ),
            ),
            # zoneinfo
            (
                py_datetime(
                    2020,
                    8,
                    15,
                    23,
                    12,
                    9,
                    987_654,
                    tzinfo=ZoneInfo("Europe/Amsterdam"),
                ),
                OffsetDateTime(
                    2020,
                    8,
                    15,
                    23,
                    12,
                    9,
                    nanosecond=987_654_000,
                    offset=hours(2),
                ),
            ),
            # subclass of datetime should work
            (
                DatetimeSubclass(
                    2020, 8, 15, 23, 12, 9, 987_654, tzinfo=timezone.utc
                ),
                OffsetDateTime(
                    2020,
                    8,
                    15,
                    23,
                    12,
                    9,
                    nanosecond=987_654_000,
                    offset=hours(0),
                ),
            ),
        ],
    )
    def test_valid(self, d: py_datetime, expect: OffsetDateTime):
        assert OffsetDateTime(d).strict_eq(expect)

    @pytest.mark.parametrize("fold, offset", [(0, 2), (1, 1)])
    def test_fold(self, fold, offset):
        # within a repeated local time, `fold` selects the occurrence through
        # the offset
        d = py_datetime(
            2023, 10, 29, 2, 30, fold=fold, tzinfo=ZoneInfo("Europe/Amsterdam")
        )
        assert OffsetDateTime(d).strict_eq(
            OffsetDateTime(2023, 10, 29, 2, 30, offset=hours(offset))
        )

    def test_naive(self):
        with pytest.raises(
            ValueError,
            match=r"^datetime is naive; use PlainDateTime\(\) instead$",
        ):
            OffsetDateTime(py_datetime(12, 3, 4, 12))

    def test_out_of_range(self):
        d = py_datetime(1, 1, 1, tzinfo=timezone(timedelta(hours=5)))
        with pytest.raises(ValueError, match="range"):
            OffsetDateTime(d)

    def test_utcoffset_none(self):

        class MyTz(tzinfo):
            def utcoffset(self, _):
                return None

        with pytest.raises(ValueError, match="naive"):
            OffsetDateTime(
                py_datetime(2020, 8, 15, tzinfo=MyTz())  # type: ignore[abstract]
            )

    def test_keyword_rejected(self):
        d = py_datetime(2020, 8, 15, tzinfo=timezone.utc)
        with pytest.raises(
            TypeError,
            match=r"^OffsetDateTime\(\) got an unexpected keyword argument 'offset'$",
        ):
            OffsetDateTime(d, offset=hours(1))  # type: ignore[call-overload]

    def test_subsecond_offset(self):
        py_dt = py_datetime(
            2020,
            8,
            15,
            23,
            12,
            9,
            987_654,
            tzinfo=timezone(timedelta(hours=2, microseconds=30)),
        )
        with pytest.raises(
            ValueError, match="^offset must be a whole number of seconds$"
        ):
            OffsetDateTime(py_dt)


class TestNow:
    @suppress(StaleOffsetWarning)
    def test_typical(self):
        now = OffsetDateTime.now(hours(-5))
        assert now.offset == hours(-5)
        py_now = py_datetime.now(timezone.utc)
        assert py_now - now.to_stdlib() < timedelta(seconds=1)

    def test_warns_by_default(self):
        with warns_here(StaleOffsetWarning):
            OffsetDateTime.now(hours(5))
        with warnings.catch_warnings():
            warnings.simplefilter("error")
            OffsetDateTime.now(hours(5), stale_offset_ok=True)

    def test_patched(self):
        instant = Instant.from_utc(2020, 8, 15, 12, 30, 45, nanosecond=5)
        with patch_current_time(instant, keep_ticking=False):
            assert OffsetDateTime.now(
                hours(1), stale_offset_ok=True
            ).strict_eq(instant.to_fixed_offset(hours(1)))


class TestAccessors:
    def test_date_and_time(self):
        d = OffsetDateTime(2020, 8, 15, 3, 12, 9, offset=hours(5))
        assert d.date() == Date(2020, 8, 15)
        assert d.time() == Time(3, 12, 9)
        assert d.offset == hours(5)


class TestFormatIso:
    @pytest.mark.parametrize(
        "d, expected",
        [
            (
                OffsetDateTime(2020, 8, 15, 23, 12, 9, offset=hours(5)),
                "2020-08-15T23:12:09+05:00",
            ),
            (
                OffsetDateTime(
                    2020,
                    8,
                    15,
                    23,
                    12,
                    9,
                    nanosecond=987_654,
                    offset=hours(5),
                ),
                "2020-08-15T23:12:09.000987654+05:00",
            ),
            (
                OffsetDateTime(2020, 8, 15, 23, 12, 9, offset=minutes(73)),
                "2020-08-15T23:12:09+01:13",
            ),
            (
                OffsetDateTime(2020, 8, 15, 23, 12, 9, offset=-minutes(73)),
                "2020-08-15T23:12:09-01:13",
            ),
            (
                OffsetDateTime(
                    2020,
                    8,
                    15,
                    23,
                    12,
                    9,
                    nanosecond=1,
                    offset=minutes(73) + seconds(32),
                ),
                "2020-08-15T23:12:09.000000001+01:13:32",
            ),
        ],
    )
    def test_default(self, d: OffsetDateTime, expected: str):
        assert str(d) == expected
        assert d.format_iso() == expected

    @pytest.mark.parametrize(
        "dt, kwargs, expected",
        [
            (
                OffsetDateTime(
                    2020,
                    8,
                    15,
                    23,
                    12,
                    9,
                    nanosecond=1_234,
                    offset=hours(5),
                ),
                {"unit": "nanosecond", "basic": False},
                "2020-08-15T23:12:09.000001234+05:00",
            ),
            (
                OffsetDateTime(
                    2020,
                    8,
                    15,
                    23,
                    12,
                    9,
                    nanosecond=1_230,
                    offset=TimeDelta(seconds=-5),
                ),
                {"unit": "auto"},
                "2020-08-15T23:12:09.00000123-00:00:05",
            ),
            (
                OffsetDateTime(
                    1993,
                    12,
                    3,
                    offset=hours(0),
                ),
                {"unit": "auto", "basic": True, "sep": " "},
                "19931203 000000+0000",
            ),
            (
                OffsetDateTime(
                    1993,
                    12,
                    3,
                    0,
                    15,
                    offset=hours(-19),
                ),
                {"unit": "hour", "basic": True, "sep": " "},
                "19931203 00-1900",
            ),
        ],
    )
    def test_variations(self, dt, kwargs, expected):
        assert dt.format_iso(**kwargs) == expected

    @pytest.mark.parametrize(
        "dt, kwargs",
        [
            (OffsetDateTime(2020, 8, 15, 23, 12, 9, offset=hours(-3)), {}),
            (
                OffsetDateTime(2020, 8, 15, 23, 12, 9, offset=hours(5)),
                {"basic": True},
            ),
            (
                OffsetDateTime(2020, 8, 15, 23, 12, 9, offset=hours(5)),
                {"sep": " "},
            ),
            (
                OffsetDateTime(2020, 8, 15, 23, offset=hours(5)),
                {"unit": "hour"},
            ),
        ],
    )
    def test_round_trip(self, dt, kwargs):
        assert OffsetDateTime.parse_iso(dt.format_iso(**kwargs)).strict_eq(dt)

    def test_invalid(self):
        dt = OffsetDateTime(2020, 4, 9, 13, offset=hours(-4))
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
        d = OffsetDateTime(
            2020,
            8,
            15,
            23,
            12,
            9,
            nanosecond=1_987_654,
            offset=hours(5) + minutes(22),
        )
        assert (
            repr(d) == 'OffsetDateTime("2020-08-15 23:12:09.001987654+05:22")'
        )
        assert (
            repr(OffsetDateTime(2020, 8, 15, 23, 12, offset=hours(0)))
            == 'OffsetDateTime("2020-08-15 23:12:00+00:00")'
        )


class TestParseIso:
    @pytest.mark.parametrize("s, expect", VALID_ISO_STRINGS)
    def test_valid(self, s, expect):
        assert OffsetDateTime.parse_iso(s).strict_eq(expect)

    def test_direct_construction_rejects_leap_second(self):
        # Direct construction should still reject 60
        with pytest.raises(ValueError):
            OffsetDateTime(2020, 8, 15, 5, 12, 60, offset=hours(5))

    @pytest.mark.parametrize("s", INVALID_ISO_STRINGS)
    def test_invalid(self, s):
        with pytest.raises(
            ValueError,
            match=r"^invalid ISO 8601 string: " + re.escape(repr(s)) + "$",
        ):
            OffsetDateTime.parse_iso(s)

    @pytest.mark.parametrize(
        "s",
        [
            "0001-01-01T02:08:30+05:00",
            "9999-12-31T22:08:30-05:00",
        ],
    )
    def test_bounds(self, s):
        with pytest.raises(ValueError):
            OffsetDateTime.parse_iso(s)

    @given(text())
    def test_fuzzing(self, s: str):
        with pytest.raises(
            ValueError,
            match=r"^invalid ISO 8601 string: " + re.escape(repr(s)) + "$",
        ):
            OffsetDateTime.parse_iso(s)


class TestEquality:
    @suppress(StaleOffsetWarning)
    def test_strict_eq(self):
        d = OffsetDateTime(2020, 8, 15, 12, offset=hours(5))
        same = d.replace()
        utc_same = d.replace(hour=13, offset=hours(6))
        different = d.replace(offset=hours(6))
        assert d.strict_eq(same)
        assert not d.strict_eq(utc_same)
        assert not d.strict_eq(different)
        assert not d.strict_eq(d.replace(nanosecond=1))

        with pytest.raises(
            TypeError,
            match=r"^strict_eq\(\) argument must be an OffsetDateTime$",
        ):
            d.strict_eq(d.to_instant())  # type: ignore[arg-type]

    @suppress(StaleOffsetWarning)
    def test_same_exact(self):
        d = OffsetDateTime(2020, 8, 15, 12, offset=hours(5))
        same = d.replace()
        assert d == same
        assert not d != same
        assert hash(d) == hash(same)

    @suppress(StaleOffsetWarning)
    def test_different(self):
        d = OffsetDateTime(2020, 8, 15, 12, offset=hours(5))
        different = d.replace(offset=hours(6))
        assert d != different
        assert not d == different
        assert hash(d) != hash(different)

    @suppress(StaleOffsetWarning)
    def test_same_time(self):
        d = OffsetDateTime(2020, 8, 15, 12, offset=hours(5))
        same_time = d.replace(hour=11, offset=hours(4))
        assert d == same_time
        assert not d != same_time
        assert hash(d) == hash(same_time)


class TestComparison:
    @suppress(StaleOffsetWarning)
    def test_offset(self):
        d = OffsetDateTime(2020, 8, 15, 12, 30, offset=hours(5))
        later = d.replace(nanosecond=13)
        assert d < later
        assert d <= later
        assert later > d
        assert later >= d


class TestReplace:
    @pytest.mark.parametrize(
        "field, value",
        [
            ("year", 2021),
            ("month", 9),
            ("day", 16),
            ("hour", 0),
            ("minute", 0),
            ("second", 0),
            ("nanosecond", 0),
        ],
    )
    def test_fields(self, field, value):
        d = OffsetDateTime(
            2020, 8, 15, 23, 12, 9, nanosecond=987_654, offset=hours(5)
        )
        kwargs: dict[str, Any] = {field: value}
        with warns_here(StaleOffsetWarning):
            result = d.replace(**kwargs)
        assert getattr(result, field) == value
        assert result.offset == hours(5)
        assert result.to_plain() == d.to_plain().replace(**kwargs)

    def test_offset_keeps_fields_and_moves_instant(self):
        d = OffsetDateTime(2020, 8, 15, 23, 12, 9, offset=hours(5))
        result = d.replace(offset=hours(2))
        assert result.offset == hours(2)
        assert result.to_plain() == d.to_plain()
        assert result.to_instant() == d.to_instant() + hours(3)

    def test_nanosecond(self):
        d = OffsetDateTime(2020, 8, 15, 23, 12, 9, offset=hours(5))
        with warns_here(StaleOffsetWarning):
            assert d.replace(nanosecond=999_999_999).nanosecond == 999_999_999
        with pytest.raises(ValueError, match="nano|time"):
            d.replace(nanosecond=1_000_000_000, stale_offset_ok=True)

    def test_invalid(self):
        d = OffsetDateTime(2020, 8, 15, 23, 12, 9, offset=hours(5))
        with pytest.raises(ValueError, match="date|day"):
            d.replace(month=2, day=30, stale_offset_ok=True)

        with pytest.raises(
            ValueError, match="value or calculation out of range"
        ):
            d.replace(year=9999, month=12, day=31, offset=hours(-5))

        with pytest.raises(TypeError, match="tzinfo"):
            d.replace(tzinfo=timezone.utc, stale_offset_ok=True)  # type: ignore[call-overload]

    def test_replace_date(self):
        d = OffsetDateTime(
            2020, 8, 15, 23, 12, 9, nanosecond=987_654, offset=hours(5)
        )
        with warns_here(StaleOffsetWarning):
            result = d.replace_date(Date(2021, 1, 2))
        assert result == OffsetDateTime(
            2021, 1, 2, 23, 12, 9, nanosecond=987_654, offset=hours(5)
        )
        assert result.offset == hours(5)
        assert result.nanosecond == 987_654

        with pytest.raises(
            ValueError, match="value or calculation out of range"
        ):
            OffsetDateTime(2020, 1, 1, offset=hours(5)).replace_date(
                Date.MIN, stale_offset_ok=True
            )

    def test_replace_time(self):
        d = OffsetDateTime(
            2020, 8, 15, 23, 12, 9, nanosecond=987_654, offset=hours(5)
        )
        with warns_here(StaleOffsetWarning):
            result = d.replace_time(Time(1, 2, 3, nanosecond=4))
        assert result == OffsetDateTime(
            2020, 8, 15, 1, 2, 3, nanosecond=4, offset=hours(5)
        )
        assert result.offset == hours(5)
        assert result.nanosecond == 4

        with pytest.raises(
            ValueError, match="value or calculation out of range"
        ):
            OffsetDateTime(9999, 12, 31, offset=hours(-5)).replace_time(
                Time.MAX, stale_offset_ok=True
            )


class TestShift:
    @suppress(StaleOffsetWarning)
    def test_operators_same_as_methods(self):
        d = OffsetDateTime(
            2020,
            8,
            15,
            23,
            12,
            9,
            nanosecond=987_654,
            offset=hours(5),
        )

        assert d + hours(4) == d.add(hours=4)
        assert d + milliseconds(500) == d.subtract(milliseconds=-500)

        assert d - hours(4) == d.subtract(hours=4)
        assert d - milliseconds(500) == d.add(milliseconds=-500)

    def test_operators_warn(self):
        d = OffsetDateTime(
            2020,
            8,
            15,
            23,
            12,
            9,
            nanosecond=987_654,
            offset=hours(5),
        )
        with warns_here(StaleOffsetWarning) as w:
            d + hours(4)
        assert len(w) == 1
        assert "usually an observation, not a time zone rule" in str(
            w[0].message
        )
        assert "mathematically valid" in str(w[0].message)
        assert "stale relative to the source time zone" in str(w[0].message)
        assert "even after an exact shift" in str(w[0].message)
        assert (
            "pass `stale_offset_ok=True` to `add()` or `subtract()`; "
            "`+` and `-` take no keyword" in str(w[0].message)
        )
        assert "choosing-a-type.html#offset-datetime-guidance" in str(
            w[0].message
        )

        with warns_here(StaleOffsetWarning) as w:
            d - hours(4)
        assert len(w) == 1

    @suppress(StaleOffsetWarning)
    def test_operators_out_of_range(self):
        # UTC equivalent must stay within bounds even when local time is in range
        with pytest.raises(ValueError, match="range"):
            OffsetDateTime(9999, 12, 31, 19, 0, offset=hours(-4)) + hours(2)
        with pytest.raises(ValueError, match="range"):
            OffsetDateTime(1, 1, 1, 5, 0, offset=hours(5)) - hours(2)

    def test_no_arguments(self):
        d = OffsetDateTime(2020, 8, 15, offset=hours(2))
        assert d.add(stale_offset_ok=True).strict_eq(d)

    @pytest.mark.parametrize(
        "delta, kwargs",
        [
            (ItemizedDateDelta(days=1), {"days": 1}),
            (ItemizedDelta(days=1, hours=2), {"days": 1, "hours": 2}),
        ],
    )
    @suppress(StaleOffsetWarning)
    def test_itemized_delta_arguments(self, delta, kwargs):
        d = OffsetDateTime(2020, 8, 15, 23, 12, 9, offset=hours(2))
        assert d.add(delta).strict_eq(d.add(**kwargs))

    @pytest.mark.parametrize(
        ("call", "exc", "message"),
        [
            (
                lambda d: d.add(1),
                TypeError,
                "add() argument must be a TimeDelta, ItemizedDelta, or ItemizedDateDelta",
            ),
            (
                lambda d: d.add(hours(1), days=1),
                TypeError,
                "add() cannot mix positional and keyword arguments",
            ),
            (
                lambda d: d.subtract(hours(1), hours(1)),
                TypeError,
                "subtract() takes at most one positional argument (2 given)",
            ),
            (
                lambda d: d.add(bogus=1),
                TypeError,
                "add() got an unexpected keyword argument 'bogus'",
            ),
            (
                lambda d: d.add(hours="x"),
                TypeError,
                "hours must be an integer or float",
            ),
            (
                lambda d: d.add(years=1.5),
                TypeError,
                "years must be an integer",
            ),
            (
                lambda d: d.subtract(weeks=float("nan")),
                TypeError,
                "weeks must be an integer",
            ),
            (
                lambda d: d.add(days=1, hours=float("nan")),
                ValueError,
                "value or calculation out of range",
            ),
            (lambda d: d.round("bogus"), ValueError, "invalid unit: 'bogus'"),
            (
                lambda d: d.round("minute", increment=7),
                ValueError,
                "increment must divide a 24-hour day evenly",
            ),
            (
                lambda d: d.round("minute", increment=0),
                ValueError,
                "increment must be a positive integer",
            ),
            (
                lambda d: d.round("minute", mode="bogus"),
                ValueError,
                "invalid mode: 'bogus'",
            ),
            (
                lambda d: d.round(TimeDelta(seconds=7)),
                ValueError,
                "unit must divide a 24-hour day evenly",
            ),
            (
                lambda d: d.start_of("bogus"),
                ValueError,
                "invalid unit: 'bogus'",
            ),
            (
                lambda d: d.start_of("week"),
                ValueError,
                "invalid unit: 'week', use 'week_mon' or 'week_sun'",
            ),
            (lambda d: d.end_of("bogus"), ValueError, "invalid unit: 'bogus'"),
        ],
    )
    def test_rejected_argument_does_not_warn(self, call, exc, message):
        # the suite escalates warnings, so a warning before the error would
        # surface as the wrong exception type
        d = OffsetDateTime(2020, 8, 15, 23, 12, 9, offset=hours(4))
        with pytest.raises(exc, match="^" + re.escape(message) + "$"):
            call(d)

    @pytest.mark.parametrize(
        "call",
        [
            lambda d: d.add(),
            lambda d: d.add(hours=1),
            lambda d: d.subtract(hours=1),
            lambda d: d.add(days=1),
            lambda d: d.add(hours(1)),
            lambda d: d.subtract(hours(1)),
            lambda d: d.add(ItemizedDelta(hours=1)),
            lambda d: d.add(ItemizedDateDelta(days=1)),
            lambda d: d.subtract(ItemizedDateDelta(days=1)),
        ],
    )
    def test_every_form_warns_at_the_caller(self, call):
        d = OffsetDateTime(2020, 8, 15, 23, 12, 9, offset=hours(4))
        with warns_here(StaleOffsetWarning) as w:
            call(d)
        assert len(w) == 1

    @suppress(StaleOffsetWarning)
    def test_invalid(self):
        d = OffsetDateTime(
            2020,
            8,
            15,
            23,
            12,
            9,
            nanosecond=987_654,
            offset=hours(4),
        )
        with pytest.raises((ValueError, OverflowError), match="range|year"):
            d.add(hours=24 * 365 * 8000)

        with pytest.raises((ValueError, OverflowError), match="range|year"):
            d.add(hours=-24 * 365 * 3000)

        with pytest.raises(TypeError, match="argument must be"):
            d.add(4)  # type: ignore[call-overload]

        # no mixing args/kwargs
        with pytest.raises(TypeError):
            d.add(seconds(4), hours=48, seconds=5)  # type: ignore[call-overload]

        # tempt a i128 overflow
        with pytest.raises((ValueError, OverflowError), match="range|year"):
            d.add(nanoseconds=1 << 127 - 1)

        # UTC equivalent must stay within bounds even when local time is in range
        with pytest.raises(ValueError, match="out of range"):
            OffsetDateTime(9999, 12, 31, 19, 0, offset=hours(-4)).add(hours=2)
        with pytest.raises(ValueError, match="out of range"):
            OffsetDateTime(1, 1, 1, 5, 0, offset=hours(5)).subtract(hours=2)

        # the operators say the same, not the stdlib's OverflowError
        with pytest.raises(
            ValueError, match="^value or calculation out of range$"
        ):
            OffsetDateTime(9999, 12, 31, 23, offset=hours(0)) + hours(2)
        with pytest.raises(
            ValueError, match="^value or calculation out of range$"
        ):
            OffsetDateTime(1, 1, 1, offset=hours(0)) - hours(2)

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
    @suppress(StaleOffsetWarning)
    def test_fuzzing(self, **kwargs):
        d = OffsetDateTime(
            2020,
            8,
            15,
            23,
            12,
            9,
            nanosecond=987_654_321,
            offset=hours(2),
        )
        try:
            d.add(**kwargs)
        except (ValueError, OverflowError):
            pass


class TestDifference:
    def test_rejects_a_delta(self):
        d = OffsetDateTime(2020, 8, 15, offset=hours(5))
        with pytest.raises(
            TypeError,
            match="^difference\\(\\) argument must be an Instant, "
            "OffsetDateTime, or ZonedDateTime$",
        ):
            d.difference(hours(1))  # type: ignore[arg-type]

    def test_offset(self):
        d = OffsetDateTime(
            2020, 8, 15, 23, 12, 9, nanosecond=3, offset=hours(5)
        )
        other = OffsetDateTime(
            2020, 8, 14, 23, 12, 4, nanosecond=4, offset=hours(-3)
        )
        assert d - other == hours(16) + seconds(5) - nanoseconds(1)

        # same result with method
        assert d.difference(other) == d - other

    def test_instant(self):
        d = OffsetDateTime(2020, 8, 15, 20, offset=hours(5))
        other = Instant.from_utc(2020, 8, 15, 20)
        assert d - other == -hours(5)

        # same result with method
        assert d.difference(other) == d - other

    def test_zoned(self):
        d = OffsetDateTime(2023, 10, 29, 6, offset=hours(2))
        other = ZonedDateTime(
            2023,
            10,
            29,
            3,
            tz="Europe/Paris",
        )
        assert d - other == hours(2)
        assert d - ZonedDateTime(
            2023, 10, 29, 2, tz="Europe/Paris", disambiguation="later"
        ) == hours(3)
        assert d - ZonedDateTime(
            2023, 10, 29, 2, tz="Europe/Paris", disambiguation="earlier"
        ) == hours(4)
        assert d - ZonedDateTime(2023, 10, 29, 1, tz="Europe/Paris") == hours(
            5
        )

        # same result with method
        assert d.difference(other) == d - other

    def test_invalid(self):
        d = OffsetDateTime(
            2020,
            8,
            15,
            23,
            12,
            9,
            nanosecond=987_654,
            offset=hours(5),
        )
        with pytest.raises(TypeError, match="unsupported operand type"):
            d - 42  # type: ignore[operator]


class TestSince:
    # The underlying calendar/exact diff logic is thoroughly tested
    # in PlainDateTime. Here we only test OffsetDateTime-specific behavior:
    # offset validation, the stale-remainder warning, and cross-offset
    # exact diffs.
    @pytest.mark.parametrize(
        "a, b, units, kwargs, expect",
        [
            # same offset, calendar units
            (
                OffsetDateTime(2023, 10, 29, hour=11, offset=hours(2)),
                OffsetDateTime(2023, 10, 28, hour=11, offset=hours(2)),
                ["days"],
                {},
                ItemizedDelta(days=1),
            ),
            # same offset, mixed calendar + exact
            (
                OffsetDateTime(
                    2025, 3, 15, hour=14, minute=30, offset=hours(-5)
                ),
                OffsetDateTime(
                    2023, 1, 10, hour=8, minute=15, offset=hours(-5)
                ),
                ["years", "months", "days", "hours", "minutes"],
                {},
                ItemizedDelta(years=2, months=2, days=5, hours=6, minutes=15),
            ),
            # same offset, exact units only
            (
                OffsetDateTime(2025, 3, 15, hour=14, offset=hours(0)),
                OffsetDateTime(2025, 3, 15, hour=10, offset=hours(0)),
                ["hours", "minutes"],
                {},
                ItemizedDelta(hours=4, minutes=0),
            ),
            # negative result
            (
                OffsetDateTime(2022, 2, 2, offset=hours(1)),
                OffsetDateTime(2022, 2, 5, offset=hours(1)),
                ["days"],
                {},
                ItemizedDelta(days=-3),
            ),
            # different offset, exact units only
            (
                OffsetDateTime(2020, 1, 1, hour=12, offset=hours(2)),
                OffsetDateTime(2020, 1, 1, hour=12, offset=hours(5)),
                ["hours", "minutes"],
                {},
                ItemizedDelta(hours=3, minutes=0),
            ),
            # different offset, exact units with rounding
            (
                OffsetDateTime(
                    2020, 1, 1, hour=12, minute=37, offset=hours(0)
                ),
                OffsetDateTime(2020, 1, 1, hour=12, offset=hours(3)),
                ["hours", "minutes"],
                {"round_increment": 15, "round_mode": "ceil"},
                ItemizedDelta(hours=3, minutes=45),
            ),
        ],
    )
    def test_examples(
        self,
        a: OffsetDateTime,
        b: OffsetDateTime,
        units: Sequence[
            Literal[
                "years",
                "months",
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
        assert a.since(
            b, in_units=units, stale_offset_ok=True, **kwargs
        ).strict_eq(expect)

    @pytest.mark.parametrize(
        "call",
        [
            lambda a, b: a.since(b, in_units=["days"]),
            lambda a, b: a.until(b, total="months"),
            lambda a, b: a.since(b, total="weeks"),
            lambda a, b: a.since(b, total="days", stale_offset_ok=True),
        ],
    )
    def test_calendar_units_different_offset_raises(self, call):
        a = OffsetDateTime(2023, 10, 29, offset=hours(2))
        b = OffsetDateTime(2023, 10, 28, offset=hours(5))
        with pytest.raises(
            ValueError,
            match="^calendar units require the same offset, "
            "got \\+02:00 and \\+05:00$",
        ):
            call(a, b)

    @pytest.mark.parametrize(
        "call",
        [
            lambda a, b: a.since(b, in_units=["days", "hours"]),
            lambda a, b: a.until(b, in_units=["months", "days", "minutes"]),
            lambda a, b: a.since(b, total="days"),
            lambda a, b: a.until(b, total="years"),
        ],
    )
    def test_exact_remainder_warns(self, call):
        a = OffsetDateTime(2023, 2, 15, hour=13, offset=hours(2))
        b = OffsetDateTime(2021, 7, 3, hour=1, offset=hours(2))
        with warns_here(StaleOffsetWarning) as w:
            call(a, b)
        assert len(w) == 1
        assert "pass `stale_offset_ok=True` to `since()` or `until()`" in str(
            w[0].message
        )

    @pytest.mark.parametrize(
        "call",
        [
            lambda a, b: a.since(b, in_units=["years", "months", "days"]),
            lambda a, b: a.since(b, in_units=["hours", "minutes"]),
            lambda a, b: a.until(b, total="hours"),
            lambda a, b: a.since(b, total="nanoseconds"),
            lambda a, b: a.since(b, total="days", stale_offset_ok=True),
            lambda a, b: a.until(
                b, in_units=["days", "hours"], stale_offset_ok=True
            ),
        ],
    )
    def test_whole_units_and_exact_units_are_silent(self, call):
        a = OffsetDateTime(2023, 2, 15, hour=13, offset=hours(2))
        b = OffsetDateTime(2021, 7, 3, hour=1, offset=hours(2))
        with warnings.catch_warnings():
            warnings.simplefilter("error")
            call(a, b)

    def test_remainder_is_computed_under_the_fixed_offset(self):
        # In Europe/Amsterdam the same instants are 273 days and 23 hours
        # apart: the transition on 2024-10-27 falls in the final partial day.
        a = OffsetDateTime(2024, 10, 27, 12, offset=hours(1))
        b = OffsetDateTime(2024, 1, 27, 14, offset=hours(1))
        assert a.since(
            b, in_units=["days", "hours"], stale_offset_ok=True
        ).strict_eq(ItemizedDelta(days=273, hours=22))

    @pytest.mark.parametrize("method", ["since", "until"])
    @pytest.mark.parametrize(
        "other",
        [
            ZonedDateTime(2021, 7, 3, tz="Europe/Amsterdam"),
            Instant.from_utc(2021, 7, 3),
            PlainDateTime(2021, 7, 3),
            hours(1),
        ],
    )
    def test_rejects_other_types(self, method, other):
        a = OffsetDateTime(2023, 2, 15, offset=hours(2))
        with pytest.raises(
            TypeError,
            match=f"^{method}\\(\\) argument must be an OffsetDateTime$",
        ):
            getattr(a, method)(other, total="hours")

    def test_units_may_be_any_iterable(self):
        a = OffsetDateTime(2023, 2, 15, offset=hours(2))
        b = OffsetDateTime(2023, 2, 14, offset=hours(2))
        assert a.since(b, in_units=iter(["hours"])) == ItemizedDelta(hours=24)  # type: ignore[call-overload]

    @pytest.mark.parametrize(
        ("kwargs", "message"),
        [
            ({"in_units": []}, "units must not be empty"),
            (
                {"in_units": ["hours", "hours"]},
                "units cannot contain duplicates",
            ),
            ({"in_units": ["foo"]}, "invalid unit: 'foo'"),
            (
                {"in_units": ["minutes", "hours"]},
                "units must be in decreasing order of size",
            ),
            (
                {"in_units": "hours"},
                "units must be a sequence of strings, not a single string",
            ),
            (
                {"in_units": ["hours", "nanoseconds"]},
                "nanoseconds can only be specified together with seconds",
            ),
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
                {"in_units": ["hours"], "round_increment": "1"},
                "round_increment must be an integer",
            ),
            (
                {"in_units": ["hours"], "round_increment": None},
                "round_increment must be an integer",
            ),
            (
                {"in_units": ["hours"], "round_increment": 2**63},
                "value or calculation out of range",
            ),
            ({"total": "foo"}, "invalid unit: 'foo'"),
        ],
    )
    @pytest.mark.parametrize("method", ["since", "until"])
    def test_invalid_units_and_rounding(self, method, kwargs, message):
        a = OffsetDateTime(2023, 2, 15, offset=hours(2))
        b = OffsetDateTime(2023, 2, 14, offset=hours(2))
        with pytest.raises(
            (TypeError, ValueError), match="^" + re.escape(message) + "$"
        ):
            getattr(a, method)(b, **kwargs)

    def test_until_is_inverse(self):
        a = OffsetDateTime(2023, 2, 15, hour=3, offset=hours(-5))
        b = OffsetDateTime(2021, 7, 3, offset=hours(-5))
        assert a.since(
            b,
            in_units=["years", "months", "days", "hours"],
            stale_offset_ok=True,
        ).strict_eq(
            b.until(
                a,
                in_units=["years", "months", "days", "hours"],
                stale_offset_ok=True,
            )
        )

    def test_single_unit_returns_float(self):
        a = OffsetDateTime(2025, 3, 15, offset=hours(1))
        b = OffsetDateTime(2023, 3, 15, offset=hours(1))
        with warns_here(StaleOffsetWarning):
            result = a.since(b, total="years")
        assert isinstance(result, float)
        assert result == 2.0
        with warnings.catch_warnings():
            warnings.simplefilter("error")
            assert a.since(b, total="hours") == 17_544.0

    @pytest.mark.parametrize(
        ("unit", "expected"),
        [
            ("months", 1 / 28),
            ("weeks", 1 / 7),
            ("days", 1.0),
            ("minutes", 1440.0),
            ("seconds", 86_400.0),
        ],
    )
    def test_total_per_unit(self, unit, expected):
        a = OffsetDateTime(2023, 2, 15, 9, offset=hours(9))
        b = OffsetDateTime(2023, 2, 14, 9, offset=hours(9))
        assert a.since(b, total=unit, stale_offset_ok=True) == pytest.approx(
            expected
        )

    def test_exact_total_across_offsets(self):
        a = OffsetDateTime(2024, 6, 1, 14, offset=hours(2))
        b = OffsetDateTime(2024, 6, 1, 10, offset=hours(0))
        assert a.since(b, total="hours") == 2.0
        assert b.until(a, total="minutes") == 120.0

    def test_very_large_increment(self):
        a = OffsetDateTime(2023, 2, 15, offset=hours(9))
        b = OffsetDateTime(2021, 7, 3, offset=hours(9))
        # round_increment=1<<65 ns exceeds i64::MAX; ceil mode rounds up to 1*(1<<65)
        assert a.since(
            b,
            in_units=["seconds", "nanoseconds"],
            round_increment=1 << 65,
            round_mode="ceil",
        ) == ItemizedDelta(seconds=36_893_488_147, nanoseconds=419_103_232)

    def test_total_nanoseconds_returns_int(self):
        a = OffsetDateTime(2023, 2, 15, offset=hours(9))
        b = OffsetDateTime(2023, 2, 14, offset=hours(9))
        result = a.since(b, total="nanoseconds")
        assert isinstance(result, int)
        assert result == 86_400_000_000_000

    @pytest.mark.parametrize(
        ("unit", "expected"),
        [
            ("milliseconds", 86_400_000.0),
            ("microseconds", 86_400_000_000.0),
        ],
    )
    def test_total_subsecond_units(self, unit, expected):
        a = OffsetDateTime(2023, 2, 15, offset=hours(9))
        b = OffsetDateTime(2023, 2, 14, offset=hours(9))
        assert a.since(b, total=unit) == expected

    @pytest.mark.parametrize(
        "kwargs, match",
        [
            ({}, "in_units"),
            (
                {"total": "hours", "in_units": ["hours"]},
                "total.*in_units|in_units.*total",
            ),
            (
                {"total": "hours", "round_mode": "floor"},
                "round_mode.*total|total.*round",
            ),
        ],
    )
    def test_rejected_keyword_combinations(self, kwargs, match):
        a = OffsetDateTime(2023, 2, 15, offset=hours(2))
        b = OffsetDateTime(2021, 7, 3, offset=hours(2))
        with pytest.raises(TypeError, match=match):
            a.since(b, **kwargs)


# receivers for the rounding rejections: on and off a whole second
_ON_INCREMENT = OffsetDateTime(2023, 7, 14, 1, 2, 3, offset=hours(2))
_OFF_INCREMENT = _ON_INCREMENT.replace(nanosecond=4_000, stale_offset_ok=True)
_NOON = OffsetDateTime(2020, 8, 15, 12, offset=hours(4))


class TestRound:
    @pytest.mark.parametrize(
        "d, increment, unit, floor, ceil, half_floor, half_ceil, half_even",
        [
            (
                OffsetDateTime(
                    2023,
                    7,
                    14,
                    1,
                    2,
                    3,
                    nanosecond=459_999_999,
                    offset=hours(2),
                ),
                1,
                "nanosecond",
                OffsetDateTime(
                    2023,
                    7,
                    14,
                    1,
                    2,
                    3,
                    nanosecond=459_999_999,
                    offset=hours(2),
                ),
                OffsetDateTime(
                    2023,
                    7,
                    14,
                    1,
                    2,
                    3,
                    nanosecond=459_999_999,
                    offset=hours(2),
                ),
                OffsetDateTime(
                    2023,
                    7,
                    14,
                    1,
                    2,
                    3,
                    nanosecond=459_999_999,
                    offset=hours(2),
                ),
                OffsetDateTime(
                    2023,
                    7,
                    14,
                    1,
                    2,
                    3,
                    nanosecond=459_999_999,
                    offset=hours(2),
                ),
                OffsetDateTime(
                    2023,
                    7,
                    14,
                    1,
                    2,
                    3,
                    nanosecond=459_999_999,
                    offset=hours(2),
                ),
            ),
            (
                OffsetDateTime(
                    2023,
                    7,
                    14,
                    1,
                    2,
                    3,
                    nanosecond=459_999_999,
                    offset=hours(2),
                ),
                1,
                "second",
                OffsetDateTime(2023, 7, 14, 1, 2, 3, offset=hours(2)),
                OffsetDateTime(2023, 7, 14, 1, 2, 4, offset=hours(2)),
                OffsetDateTime(2023, 7, 14, 1, 2, 3, offset=hours(2)),
                OffsetDateTime(2023, 7, 14, 1, 2, 3, offset=hours(2)),
                OffsetDateTime(2023, 7, 14, 1, 2, 3, offset=hours(2)),
            ),
            (
                OffsetDateTime(
                    2023,
                    7,
                    14,
                    1,
                    2,
                    21,
                    nanosecond=459_999_999,
                    offset=hours(2),
                ),
                4,
                "second",
                OffsetDateTime(2023, 7, 14, 1, 2, 20, offset=hours(2)),
                OffsetDateTime(2023, 7, 14, 1, 2, 24, offset=hours(2)),
                OffsetDateTime(2023, 7, 14, 1, 2, 20, offset=hours(2)),
                OffsetDateTime(2023, 7, 14, 1, 2, 20, offset=hours(2)),
                OffsetDateTime(2023, 7, 14, 1, 2, 20, offset=hours(2)),
            ),
            (
                OffsetDateTime(
                    2023,
                    7,
                    14,
                    23,
                    52,
                    29,
                    nanosecond=999_999_999,
                    offset=hours(2),
                ),
                10,
                "minute",
                OffsetDateTime(2023, 7, 14, 23, 50, 0, offset=hours(2)),
                OffsetDateTime(2023, 7, 15, offset=hours(2)),
                OffsetDateTime(2023, 7, 14, 23, 50, 0, offset=hours(2)),
                OffsetDateTime(2023, 7, 14, 23, 50, 0, offset=hours(2)),
                OffsetDateTime(2023, 7, 14, 23, 50, 0, offset=hours(2)),
            ),
            (
                OffsetDateTime(
                    2023,
                    7,
                    14,
                    11,
                    59,
                    29,
                    nanosecond=999_999_999,
                    offset=hours(2),
                ),
                12,
                "hour",
                OffsetDateTime(2023, 7, 14, offset=hours(2)),
                OffsetDateTime(2023, 7, 14, 12, 0, 0, offset=hours(2)),
                OffsetDateTime(2023, 7, 14, 12, 0, 0, offset=hours(2)),
                OffsetDateTime(2023, 7, 14, 12, 0, 0, offset=hours(2)),
                OffsetDateTime(2023, 7, 14, 12, 0, 0, offset=hours(2)),
            ),
            (
                OffsetDateTime(2023, 7, 14, 12, offset=hours(2)),
                1,
                "day",
                OffsetDateTime(2023, 7, 14, offset=hours(2)),
                OffsetDateTime(2023, 7, 15, offset=hours(2)),
                OffsetDateTime(2023, 7, 14, offset=hours(2)),
                OffsetDateTime(2023, 7, 15, offset=hours(2)),
                OffsetDateTime(2023, 7, 14, offset=hours(2)),
            ),
            (
                OffsetDateTime(2023, 7, 14, offset=hours(2)),
                1,
                "day",
                OffsetDateTime(2023, 7, 14, offset=hours(2)),
                OffsetDateTime(2023, 7, 14, offset=hours(2)),
                OffsetDateTime(2023, 7, 14, offset=hours(2)),
                OffsetDateTime(2023, 7, 14, offset=hours(2)),
                OffsetDateTime(2023, 7, 14, offset=hours(2)),
            ),
        ],
    )
    def test_valid(
        self,
        d: OffsetDateTime,
        increment,
        unit,
        floor,
        ceil,
        half_floor,
        half_ceil,
        half_even,
    ):
        with suppress(StaleOffsetWarning):
            assert d.round(unit, increment=increment) == half_even
            assert d.round(unit, increment=increment, mode="floor") == floor
            assert d.round(unit, increment=increment, mode="trunc") == floor
            assert d.round(unit, increment=increment, mode="ceil") == ceil
            assert d.round(unit, increment=increment, mode="expand") == ceil
            assert (
                d.round(unit, increment=increment, mode="half_floor")
                == half_floor
            )
            assert (
                d.round(unit, increment=increment, mode="half_trunc")
                == half_floor
            )
            assert (
                d.round(unit, increment=increment, mode="half_ceil")
                == half_ceil
            )
            assert (
                d.round(unit, increment=increment, mode="half_expand")
                == half_ceil
            )
            assert (
                d.round(unit, increment=increment, mode="half_even")
                == half_even
            )

    @suppress(StaleOffsetWarning)
    def test_default(self):
        d = OffsetDateTime(
            2023,
            7,
            14,
            1,
            2,
            3,
            nanosecond=500_000_000,
            offset=hours(2),
        )
        assert d.round() == OffsetDateTime(
            2023, 7, 14, 1, 2, 4, offset=hours(2)
        )
        assert d.replace(second=8).round() == OffsetDateTime(
            2023, 7, 14, 1, 2, 8, offset=hours(2)
        )

    @pytest.mark.parametrize(
        "d, args, kwargs, exc, message",
        [
            # a value already on the increment validates the mode too
            *(
                (
                    d,
                    ("second",),
                    {"mode": m},
                    ValueError,
                    f"invalid mode: {m!r}",
                )
                for d in (_OFF_INCREMENT, _ON_INCREMENT)
                for m in ("foo", "TRUNC", None, 3)
            ),
            *(
                (
                    _OFF_INCREMENT,
                    (u,),
                    {"increment": i},
                    ValueError,
                    "increment must divide a 24-hour day evenly",
                )
                for u, i in [
                    ("minute", 21),
                    ("second", 14),
                    ("millisecond", 5432),
                    ("day", 2),
                    ("hour", 48),
                    ("microsecond", 2001),
                    ("second", 1 << 62),
                ]
            ),
            *(
                (
                    _ON_INCREMENT,
                    ("second",),
                    {"increment": i},
                    ValueError,
                    "increment must be a positive integer",
                )
                for i in (0, -1)
            ),
            *(
                (
                    _ON_INCREMENT,
                    ("second",),
                    {"increment": i},
                    TypeError,
                    "increment must be an integer",
                )
                for i in (1.5, float("nan"), "5", Fraction(3, 2))
            ),
            *(
                (_OFF_INCREMENT, (u,), {}, ValueError, f"invalid unit: {u!r}")
                for u in ("foo", "week", "minutes", None, 5)
            ),
            *(
                (
                    _NOON,
                    (u,),
                    {},
                    ValueError,
                    "unit must divide a 24-hour day evenly",
                )
                for u in (hours(7), hours(25))
            ),
            *(
                (
                    _NOON,
                    (u,),
                    {},
                    ValueError,
                    "unit must be a positive TimeDelta",
                )
                for u in (hours(-1), TimeDelta.ZERO)
            ),
            *(
                (
                    _NOON,
                    (hours(1),),
                    {"increment": i},
                    TypeError,
                    "cannot specify an increment with a TimeDelta argument",
                )
                for i in (1, 2)
            ),
        ],
    )
    def test_rejected(self, d, args, kwargs, exc, message):
        with pytest.raises(exc, match="^" + re.escape(message) + "$"):
            d.round(*args, **kwargs)

    @suppress(StaleOffsetWarning)
    def test_increment_read_through_index(self):
        d = OffsetDateTime(2023, 7, 14, 12, 39, 59, offset=hours(2))
        assert d.round("minute", increment=True) == d.round("minute")
        assert d.round("minute", increment=cast(int, Idx())) == d.round(
            "minute", increment=5
        )

    @pytest.mark.parametrize("hour, expect", [(12, 12), (13, 14)])
    @suppress(StaleOffsetWarning)
    def test_half_even_tie(self, hour, expect):
        d = OffsetDateTime(2023, 7, 14, hour, 30, offset=hours(2))
        assert d.round("hour").strict_eq(
            OffsetDateTime(2023, 7, 14, expect, offset=hours(2))
        )

    @suppress(StaleOffsetWarning)
    def test_default_increment(self):
        d = OffsetDateTime(
            2023,
            7,
            14,
            1,
            2,
            3,
            nanosecond=800_000,
            offset=hours(-9),
        )
        assert d.round("millisecond").strict_eq(
            OffsetDateTime(
                2023,
                7,
                14,
                1,
                2,
                3,
                nanosecond=1_000_000,
                offset=hours(-9),
            )
        )

    @suppress(StaleOffsetWarning)
    def test_range_edges(self):
        last = PlainDateTime.MAX.assume_fixed_offset(hours(0))
        assert last.round("hour", mode="floor").strict_eq(
            OffsetDateTime(9999, 12, 31, 23, offset=hours(0))
        )
        with pytest.raises(
            ValueError, match="^value or calculation out of range$"
        ):
            last.round("hour", mode="ceil")
        with pytest.raises(
            ValueError, match="^value or calculation out of range$"
        ):
            last.replace(nanosecond=0).round("second", increment=5)

        first = PlainDateTime.MIN.assume_fixed_offset(hours(0))
        just_after = first.add(seconds=1)
        assert just_after.round("hour", mode="floor").strict_eq(first)
        assert just_after.round("hour", mode="ceil").strict_eq(
            OffsetDateTime(1, 1, 1, 1, offset=hours(0))
        )

    @suppress(StaleOffsetWarning)
    def test_round_by_timedelta(self):
        d = OffsetDateTime(2020, 8, 15, 23, 24, 18, offset=hours(4))
        assert d.round(TimeDelta(minutes=15)) == OffsetDateTime(
            2020, 8, 15, 23, 30, offset=hours(4)
        )
        assert d.round(hours(1)) == OffsetDateTime(
            2020, 8, 15, 23, offset=hours(4)
        )

    # every unit warns: a minute rounding can cross a transition too
    @pytest.mark.parametrize(
        "unit", ["nanosecond", "day", TimeDelta(minutes=15)]
    )
    def test_emits_stale_offset_warning(self, unit):
        d = OffsetDateTime(2020, 8, 15, 23, 24, 18, offset=hours(4))
        with warns_here(StaleOffsetWarning) as w:
            d.round(unit)
        assert len(w) == 1

    def test_stale_offset_ok_suppresses_warning(self):
        d = OffsetDateTime(2020, 8, 15, 23, 24, 18, offset=hours(4))
        with warnings.catch_warnings():
            warnings.simplefilter("error")
            d.round("hour", stale_offset_ok=True)
            d.round(TimeDelta(minutes=15), stale_offset_ok=True)


class TestStartOf:
    @pytest.mark.parametrize(
        "unit, expected",
        [
            ("year", OffsetDateTime(2024, 1, 1, offset=hours(5))),
            ("month", OffsetDateTime(2024, 8, 1, offset=hours(5))),
            # Thursday Aug 15 -> Monday Aug 12, or Sunday Aug 11
            ("week_mon", OffsetDateTime(2024, 8, 12, offset=hours(5))),
            ("week_sun", OffsetDateTime(2024, 8, 11, offset=hours(5))),
            ("day", OffsetDateTime(2024, 8, 15, offset=hours(5))),
            ("hour", OffsetDateTime(2024, 8, 15, 14, offset=hours(5))),
            ("minute", OffsetDateTime(2024, 8, 15, 14, 30, offset=hours(5))),
            (
                "second",
                OffsetDateTime(2024, 8, 15, 14, 30, 45, offset=hours(5)),
            ),
        ],
    )
    @suppress(StaleOffsetWarning)
    def test_units(self, unit, expected):
        odt = OffsetDateTime(
            2024, 8, 15, 14, 30, 45, nanosecond=123, offset=hours(5)
        )
        assert odt.start_of(unit).strict_eq(expected)

    @suppress(StaleOffsetWarning)
    def test_offset_preserved(self):
        odt = OffsetDateTime(2024, 8, 15, 14, 30, 45, offset=hours(-7))
        result = odt.start_of("day")
        assert result.offset == hours(-7)

    def test_invalid_unit(self):
        with pytest.raises(ValueError, match="^invalid unit: 'invalid'$"):
            OffsetDateTime(2024, 8, 15, 14, 30, offset=hours(5)).start_of(
                "invalid"  # type: ignore[arg-type]
            )

    def test_week_value_error(self):
        with pytest.raises(
            ValueError,
            match="^invalid unit: 'week', use 'week_mon' or 'week_sun'$",
        ):
            OffsetDateTime(2024, 8, 15, 14, 30, offset=hours(5)).start_of(
                "week"  # type: ignore[arg-type]
            )

    @suppress(StaleOffsetWarning)
    def test_range_edges(self):
        # 0001-01-01 is a Monday, 9999-12-31 a Friday
        first = OffsetDateTime(1, 1, 1, offset=hours(0))
        assert first.start_of("week_mon").strict_eq(first)
        with pytest.raises(
            ValueError, match="^value or calculation out of range$"
        ):
            first.start_of("week_sun")

        last = OffsetDateTime(9999, 12, 31, 23, 59, 59, offset=hours(0))
        assert last.start_of("week_mon").strict_eq(
            OffsetDateTime(9999, 12, 27, offset=hours(0))
        )
        assert last.start_of("week_sun").strict_eq(
            OffsetDateTime(9999, 12, 26, offset=hours(0))
        )

    def test_emits_stale_offset_warning(self):
        odt = OffsetDateTime(2024, 8, 15, 14, 30, offset=hours(5))
        with warns_here(StaleOffsetWarning):
            odt.start_of("day")

    def test_stale_offset_ok_suppresses_warning(self):
        odt = OffsetDateTime(2024, 8, 15, 14, 30, offset=hours(5))
        with warnings.catch_warnings():
            warnings.simplefilter("error")
            odt.start_of("day", stale_offset_ok=True)


_SAMPLE = OffsetDateTime(
    2024, 8, 15, 14, 30, 45, nanosecond=123, offset=hours(5)
)


class TestEndOf:
    @pytest.mark.parametrize(
        "d, unit, expected",
        [
            (
                _SAMPLE,
                "year",
                OffsetDateTime(
                    2024,
                    12,
                    31,
                    23,
                    59,
                    59,
                    nanosecond=999_999_999,
                    offset=hours(5),
                ),
            ),
            (
                OffsetDateTime(2024, 8, 15, 14, 30, offset=hours(5)),
                "month",
                OffsetDateTime(
                    2024,
                    8,
                    31,
                    23,
                    59,
                    59,
                    nanosecond=999_999_999,
                    offset=hours(5),
                ),
            ),
            (
                OffsetDateTime(2024, 2, 10, 12, offset=hours(5)),
                "month",
                OffsetDateTime(
                    2024,
                    2,
                    29,
                    23,
                    59,
                    59,
                    nanosecond=999_999_999,
                    offset=hours(5),
                ),
            ),
            (
                OffsetDateTime(2023, 2, 10, 12, offset=hours(5)),
                "month",
                OffsetDateTime(
                    2023,
                    2,
                    28,
                    23,
                    59,
                    59,
                    nanosecond=999_999_999,
                    offset=hours(5),
                ),
            ),
            # Thursday Aug 15 -> Sunday Aug 18, or Saturday Aug 17
            (
                _SAMPLE,
                "week_mon",
                OffsetDateTime(
                    2024,
                    8,
                    18,
                    23,
                    59,
                    59,
                    nanosecond=999_999_999,
                    offset=hours(5),
                ),
            ),
            (
                _SAMPLE,
                "week_sun",
                OffsetDateTime(
                    2024,
                    8,
                    17,
                    23,
                    59,
                    59,
                    nanosecond=999_999_999,
                    offset=hours(5),
                ),
            ),
            (
                _SAMPLE,
                "day",
                OffsetDateTime(
                    2024,
                    8,
                    15,
                    23,
                    59,
                    59,
                    nanosecond=999_999_999,
                    offset=hours(5),
                ),
            ),
            (
                _SAMPLE,
                "hour",
                OffsetDateTime(
                    2024,
                    8,
                    15,
                    14,
                    59,
                    59,
                    nanosecond=999_999_999,
                    offset=hours(5),
                ),
            ),
            (
                _SAMPLE,
                "minute",
                OffsetDateTime(
                    2024,
                    8,
                    15,
                    14,
                    30,
                    59,
                    nanosecond=999_999_999,
                    offset=hours(5),
                ),
            ),
            (
                _SAMPLE,
                "second",
                OffsetDateTime(
                    2024,
                    8,
                    15,
                    14,
                    30,
                    45,
                    nanosecond=999_999_999,
                    offset=hours(5),
                ),
            ),
        ],
    )
    @suppress(StaleOffsetWarning)
    def test_units(self, d, unit, expected):
        assert d.end_of(unit).strict_eq(expected)

    @pytest.mark.parametrize(
        ("unit", "next_start"),
        [
            ("year", OffsetDateTime(2025, 1, 1, offset=hours(5))),
            ("month", OffsetDateTime(2024, 9, 1, offset=hours(5))),
            ("week_mon", OffsetDateTime(2024, 8, 19, offset=hours(5))),
            ("week_sun", OffsetDateTime(2024, 8, 18, offset=hours(5))),
            ("day", OffsetDateTime(2024, 8, 16, offset=hours(5))),
            ("hour", OffsetDateTime(2024, 8, 15, 15, offset=hours(5))),
            ("minute", OffsetDateTime(2024, 8, 15, 14, 31, offset=hours(5))),
            (
                "second",
                OffsetDateTime(2024, 8, 15, 14, 30, 46, offset=hours(5)),
            ),
        ],
    )
    def test_adjacent_to_next_start(self, unit, next_start):
        odt = OffsetDateTime(
            2024, 8, 15, 14, 30, 45, nanosecond=123, offset=hours(5)
        )
        assert (
            odt.end_of(unit, stale_offset_ok=True)
            .add(nanoseconds=1, stale_offset_ok=True)
            .strict_eq(next_start)
        )

    @suppress(StaleOffsetWarning)
    def test_offset_preserved(self):
        odt = OffsetDateTime(2024, 8, 15, 14, 30, 45, offset=hours(-7))
        result = odt.end_of("day")
        assert result.offset == hours(-7)

    def test_invalid_unit(self):
        with pytest.raises(ValueError, match="^invalid unit: 'invalid'$"):
            OffsetDateTime(2024, 8, 15, 14, 30, offset=hours(5)).end_of(
                "invalid"  # type: ignore[arg-type]
            )

    def test_week_value_error(self):
        with pytest.raises(
            ValueError,
            match="^invalid unit: 'week', use 'week_mon' or 'week_sun'$",
        ):
            OffsetDateTime(2024, 8, 15, 14, 30, offset=hours(5)).end_of("week")  # type: ignore[arg-type]

    @suppress(StaleOffsetWarning)
    def test_range_edges(self):
        # 0001-01-01 is a Monday, 9999-12-31 a Friday
        first = OffsetDateTime(1, 1, 1, offset=hours(0))
        assert first.end_of("week_mon").strict_eq(
            OffsetDateTime(
                1, 1, 7, 23, 59, 59, nanosecond=999_999_999, offset=hours(0)
            )
        )
        assert first.end_of("week_sun").strict_eq(
            OffsetDateTime(
                1, 1, 6, 23, 59, 59, nanosecond=999_999_999, offset=hours(0)
            )
        )

        last = OffsetDateTime(9999, 12, 31, 23, 59, 59, offset=hours(0))
        assert last.end_of("year").strict_eq(
            last.replace(nanosecond=999_999_999)
        )
        assert last.end_of("day").strict_eq(
            last.replace(nanosecond=999_999_999)
        )

    @pytest.mark.parametrize("unit", ["week_mon", "week_sun"])
    @suppress(StaleOffsetWarning)
    def test_last_week_is_out_of_range(self, unit):
        last = OffsetDateTime(9999, 12, 31, 23, 59, 59, offset=hours(0))
        with pytest.raises(
            ValueError, match="^value or calculation out of range$"
        ):
            last.end_of(unit)

    def test_emits_stale_offset_warning(self):
        odt = OffsetDateTime(2024, 8, 15, 14, 30, offset=hours(5))
        with warns_here(StaleOffsetWarning):
            odt.end_of("day")

    def test_stale_offset_ok_suppresses_warning(self):
        odt = OffsetDateTime(2024, 8, 15, 14, 30, offset=hours(5))
        with warnings.catch_warnings():
            warnings.simplefilter("error")
            odt.end_of("day", stale_offset_ok=True)


class TestCalendarProperties:
    @pytest.mark.parametrize(
        "d, expected",
        [
            (OffsetDateTime(2024, 3, 9, 22, offset=hours(-5)), SATURDAY),
            (OffsetDateTime(2024, 12, 30, offset=hours(5)), MONDAY),
        ],
    )
    def test_day_of_week(self, d, expected):
        assert d.day_of_week() is expected

    @pytest.mark.parametrize(
        "d, expected",
        [
            (OffsetDateTime(2024, 2, 29, 12, offset=hours(5)), 60),
            (OffsetDateTime(2023, 1, 1, 0, offset=hours(5)), 1),
            (OffsetDateTime(2023, 12, 31, 12, offset=hours(5)), 365),
            (OffsetDateTime(2024, 12, 31, 12, offset=hours(5)), 366),
        ],
    )
    def test_day_of_year(self, d, expected):
        assert d.day_of_year() == expected

    @pytest.mark.parametrize(
        "d, expected",
        [
            (OffsetDateTime(2024, 2, 29, 12, offset=hours(5)), 29),
            (OffsetDateTime(2023, 2, 15, 12, offset=hours(5)), 28),
            (OffsetDateTime(2023, 1, 15, 12, offset=hours(5)), 31),
            (OffsetDateTime(1900, 2, 15, 12, offset=hours(5)), 28),
            (OffsetDateTime(2000, 2, 15, 12, offset=hours(5)), 29),
        ],
    )
    def test_days_in_month(self, d, expected):
        assert d.days_in_month() == expected

    @pytest.mark.parametrize(
        "d, days, leap",
        [
            (OffsetDateTime(2024, 2, 29, 12, offset=hours(5)), 366, True),
            (OffsetDateTime(2023, 6, 15, 12, offset=hours(5)), 365, False),
            (OffsetDateTime(1900, 6, 15, 12, offset=hours(5)), 365, False),
            (OffsetDateTime(2000, 6, 15, 12, offset=hours(5)), 366, True),
        ],
    )
    def test_days_in_year_and_in_leap_year(self, d, days, leap):
        assert d.days_in_year() == days
        assert d.in_leap_year() is leap


class TestTimestamp:
    def test_default_seconds(self):
        assert OffsetDateTime(1970, 1, 1, 3, offset=hours(3)).timestamp() == 0
        assert (
            OffsetDateTime(
                2020,
                8,
                15,
                8,
                8,
                30,
                nanosecond=45,
                offset=hours(-4),
            ).timestamp()
            == 1_597_493_310
        )

    @pytest.mark.parametrize(
        ("unit", "expected"),
        [
            ("second", 1_597_493_310),
            ("millisecond", 1_597_493_310_045),
            ("microsecond", 1_597_493_310_045_123),
            ("nanosecond", 1_597_493_310_045_123_987),
        ],
    )
    def test_unit(self, unit, expected):
        value = OffsetDateTime(
            2020,
            8,
            15,
            8,
            8,
            30,
            nanosecond=45_123_987,
            offset=hours(-4),
        )

        assert value.timestamp(unit=unit) == expected

    @pytest.mark.parametrize(
        # One nanosecond after the epoch floors to 0 in every unit that
        # cannot resolve it; in nanoseconds it is the exact value 1.
        ("unit", "after_epoch"),
        [
            ("second", 0),
            ("millisecond", 0),
            ("microsecond", 0),
            ("nanosecond", 1),
        ],
    )
    def test_unit_floors_around_epoch(self, unit, after_epoch):
        before = Instant.from_utc(
            1969, 12, 31, 23, 59, 59, nanosecond=999_999_999
        )
        after = Instant.from_utc(1970, 1, 1, nanosecond=1)

        assert before.to_fixed_offset(hours(-3)).timestamp(unit=unit) == -1
        assert (
            after.to_fixed_offset(hours(5)).timestamp(unit=unit) == after_epoch
        )


class TestAssumeTz:
    @pytest.mark.parametrize(
        "dt, tz, kwargs, expect",
        [
            # no DST
            (
                "2020-08-15 23:12:09.987654321+02:00",
                "Europe/Paris",
                {},
                ZonedDateTime(
                    "2020-08-15 23:12:09.987654321+02:00[Europe/Paris]"
                ),
            ),
            # DST
            (
                "2020-01-15 23:12:09.987654321+01:00",
                "Europe/Berlin",
                {},
                ZonedDateTime(
                    "2020-01-15 23:12:09.987654321+01:00[Europe/Berlin]"
                ),
            ),
            # the offset disambiguates
            (
                "2023-10-29 02:30:00+02:00",
                "Europe/Paris",
                {},
                ZonedDateTime("2023-10-29 02:30:00+02:00[Europe/Paris]"),
            ),
            (
                "2023-10-29 02:30:00+01:00",
                "Europe/Paris",
                {},
                ZonedDateTime("2023-10-29 02:30:00+01:00[Europe/Paris]"),
            ),
            # the offset is incorrect
            (
                "2023-05-01 12:30:00+03:00",
                "Europe/Paris",
                {"offset_mismatch": "keep_instant"},
                ZonedDateTime("2023-05-01 11:30:00+02:00[Europe/Paris]"),
            ),
            (
                "2023-05-01 12:30:00+03:00",
                "Europe/Paris",
                {"offset_mismatch": "keep_local"},
                ZonedDateTime("2023-05-01 12:30:00+02:00[Europe/Paris]"),
            ),
            # incorrect offset, during a DST transition
            (
                "2023-10-29 02:30:00-09:00",
                "Europe/Paris",
                {
                    "offset_mismatch": "keep_local",
                    "disambiguation": "compatible",
                },
                ZonedDateTime("2023-10-29 02:30:00+02:00[Europe/Paris]"),
            ),
            (
                "2023-03-26 02:30:00-09:00",
                "Europe/Paris",
                {
                    "offset_mismatch": "keep_local",
                    "disambiguation": "compatible",
                },
                ZonedDateTime("2023-03-26 03:30:00+02:00[Europe/Paris]"),
            ),
        ],
    )
    def test_valid(
        self, dt: str, tz: str, kwargs: dict[str, Any], expect: ZonedDateTime
    ):
        d = OffsetDateTime(dt)
        assert d.assume_tz(tz, **kwargs).strict_eq(expect)

    def test_invalid_offset_raises(self):
        with pytest.raises(
            InvalidOffsetError, match="offset -09:00 does not match"
        ):
            OffsetDateTime("2023-05-01 12:30:00-09:00").assume_tz(
                "America/New_York"
            )

    @system_tz("Europe/Amsterdam")
    def test_system_tz(self):
        assert (
            OffsetDateTime(2020, 8, 15, 12, offset=hours(2))
            .assume_tz(SYSTEM_TZ)
            .strict_eq(ZonedDateTime(2020, 8, 15, 12, tz="Europe/Amsterdam"))
        )

    def test_wrong_type(self):
        with pytest.raises(
            TypeError, match="^tz must be a string or SYSTEM_TZ$"
        ):
            OffsetDateTime(2020, 8, 15, offset=hours(2)).assume_tz(3)

    @pytest.mark.parametrize("offset", [hours(1), hours(2)])
    def test_invalid_disambiguation(self, offset):
        # validated up front, whether or not the offset matches
        with pytest.raises(
            ValueError, match="^invalid disambiguation: 'foo'$"
        ):
            OffsetDateTime(2023, 1, 1, offset=offset).assume_tz(
                "Europe/Amsterdam",
                disambiguation="foo",  # type: ignore[arg-type]
            )

    def test_invalid_offset_message_uses_canonical_tz_id(self):
        # not the spelling that was passed in
        with pytest.raises(
            InvalidOffsetError, match="time zone 'America/New_York'"
        ):
            OffsetDateTime("2023-05-01 12:30:00-09:00").assume_tz(
                "america/new_york"
            )

    @pytest.mark.parametrize(
        "offset_mismatch", ["raise", "keep_instant", "keep_local"]
    )
    def test_matching_offset_ignores_policies(self, offset_mismatch):
        d = OffsetDateTime("2023-10-29 02:30:00+02:00")
        result = d.assume_tz(
            "Europe/Paris",
            offset_mismatch=offset_mismatch,
            disambiguation="raise",
        )
        assert result.strict_eq(
            ZonedDateTime(
                2023,
                10,
                29,
                2,
                30,
                tz="Europe/Paris",
                disambiguation="earlier",
            )
        )

    @pytest.mark.parametrize(
        ("value", "disambiguation", "expected"),
        [
            (
                "2023-10-29 02:30:00+03:00",
                "compatible",
                "2023-10-29 02:30:00+02:00[Europe/Paris]",
            ),
            (
                "2023-10-29 02:30:00+03:00",
                "earlier",
                "2023-10-29 02:30:00+02:00[Europe/Paris]",
            ),
            (
                "2023-10-29 02:30:00+03:00",
                "later",
                "2023-10-29 02:30:00+01:00[Europe/Paris]",
            ),
            (
                "2023-03-26 02:30:00+03:00",
                "compatible",
                "2023-03-26 03:30:00+02:00[Europe/Paris]",
            ),
            (
                "2023-03-26 02:30:00+03:00",
                "earlier",
                "2023-03-26 01:30:00+01:00[Europe/Paris]",
            ),
            (
                "2023-03-26 02:30:00+03:00",
                "later",
                "2023-03-26 03:30:00+02:00[Europe/Paris]",
            ),
        ],
    )
    def test_keep_local_uses_disambiguation(
        self, value, disambiguation, expected
    ):
        result = OffsetDateTime(value).assume_tz(
            "Europe/Paris",
            offset_mismatch="keep_local",
            disambiguation=disambiguation,
        )
        assert result.strict_eq(ZonedDateTime(expected))

    @pytest.mark.parametrize(
        ("value", "error"),
        [
            ("2023-10-29 02:30:00+03:00", RepeatedTime),
            ("2023-03-26 02:30:00+03:00", SkippedTime),
        ],
    )
    def test_keep_local_raise(self, value, error):
        with pytest.raises(error):
            OffsetDateTime(value).assume_tz(
                "Europe/Paris",
                offset_mismatch="keep_local",
                disambiguation="raise",
            )

    @pytest.mark.parametrize(
        "value",
        [
            "2023-10-29 02:30:00+03:00",
            "2023-03-26 02:30:00+03:00",
        ],
    )
    def test_keep_local_implicit_disambiguation_warns(self, value):
        with warns_here(ImplicitDisambiguationWarning):
            OffsetDateTime(value).assume_tz(
                "Europe/Paris", offset_mismatch="keep_local"
            )

    def test_ordinary_mismatch_does_not_disambiguate(self):
        d = OffsetDateTime("2023-05-01 12:30:00+03:00")
        with warnings.catch_warnings():
            warnings.simplefilter("error", ImplicitDisambiguationWarning)
            result = d.assume_tz("Europe/Paris", offset_mismatch="keep_local")
        assert (result.hour, result.minute) == (12, 30)

    @pytest.mark.parametrize(
        "value",
        [
            "2023-10-29 02:30:00+03:00",
            "2023-03-26 02:30:00+03:00",
        ],
    )
    def test_keep_instant_ignores_disambiguation(self, value):
        d = OffsetDateTime(value)
        result = d.assume_tz(
            "Europe/Paris",
            offset_mismatch="keep_instant",
            disambiguation="raise",
        )
        assert result.to_instant() == d.to_instant()

    def test_skipped_time(self):
        with pytest.raises(InvalidOffsetError):
            OffsetDateTime("2023-03-26 02:30:00+01:00").assume_tz(
                "Europe/Paris"
            )

        with pytest.raises(InvalidOffsetError):
            OffsetDateTime("2023-03-26 02:30:00+02:00").assume_tz(
                "Europe/Paris"
            )

    def test_invalid_arguments(self):

        with pytest.raises(ValueError, match="foo"):
            OffsetDateTime("2020-08-15 23:12:09+02:00").assume_tz(
                "Europe/Paris",
                offset_mismatch="foo",  # type: ignore[arg-type]
            )

        with pytest.raises(TimeZoneNotFoundError, match="Foo"):
            OffsetDateTime("2020-08-15 23:12:09+02:00").assume_tz("Europe/Foo")


class TestConversion:
    def test_to_instant(self):
        d = OffsetDateTime(
            2020,
            8,
            15,
            23,
            12,
            9,
            nanosecond=987_654_321,
            offset=hours(3),
        )
        assert d.to_instant() == Instant.from_utc(
            2020, 8, 15, 20, 12, 9, nanosecond=987_654_321
        )

    def test_to_fixed_offset(self):
        d = OffsetDateTime(
            2020,
            8,
            15,
            23,
            12,
            9,
            nanosecond=987_654_321,
            offset=hours(3),
        )
        assert d.to_fixed_offset(hours(5)).strict_eq(
            OffsetDateTime(
                2020,
                8,
                16,
                1,
                12,
                9,
                nanosecond=987_654_321,
                offset=hours(5),
            )
        )
        assert d.to_fixed_offset().strict_eq(d)
        assert d.to_fixed_offset(hours(-3)).strict_eq(
            OffsetDateTime(
                2020,
                8,
                15,
                17,
                12,
                9,
                nanosecond=987_654_321,
                offset=hours(-3),
            )
        )

        with pytest.raises(ValueError):
            OffsetDateTime(
                1, 1, 1, hour=3, minute=59, offset=hours(0)
            ).to_fixed_offset(hours(-4))

        with pytest.raises(ValueError):
            OffsetDateTime(
                9999, 12, 31, hour=23, offset=hours(0)
            ).to_fixed_offset(hours(1))

    def test_to_tz(self):
        d = OffsetDateTime(
            2020,
            8,
            15,
            20,
            12,
            9,
            nanosecond=987_654_321,
            offset=hours(3),
        )
        assert d.to_tz("America/New_York").strict_eq(
            ZonedDateTime(
                2020,
                8,
                15,
                13,
                12,
                9,
                nanosecond=987_654_321,
                tz="America/New_York",
            )
        )
        with pytest.raises(TimeZoneNotFoundError):
            d.to_tz("America/Not_A_Real_Zone")

        small_dt = OffsetDateTime(1, 1, 1, offset=hours(0))
        with pytest.raises(ValueError, match="out of range"):
            small_dt.to_tz("America/New_York")

        big_dt = OffsetDateTime(9999, 12, 31, hour=23, offset=hours(0))
        with pytest.raises(ValueError, match="out of range"):
            big_dt.to_tz("Asia/Tokyo")

    @system_tz("America/New_York")
    def test_to_system_tz(self):
        d = OffsetDateTime(
            2020,
            8,
            15,
            20,
            12,
            9,
            nanosecond=987_654_321,
            offset=hours(3),
        )
        assert d.to_tz(SYSTEM_TZ).strict_eq(
            ZonedDateTime(
                2020,
                8,
                15,
                13,
                12,
                9,
                nanosecond=987_654_321,
                tz="America/New_York",
            )
        )

        small_dt = OffsetDateTime(1, 1, 1, offset=hours(0))
        with pytest.raises(ValueError):
            small_dt.to_tz(SYSTEM_TZ)

        big_dt = OffsetDateTime(9999, 12, 31, hour=23, offset=hours(0))
        with system_tz("Europe/Amsterdam"):
            with pytest.raises(ValueError):
                big_dt.to_tz(SYSTEM_TZ)

    def test_to_plain(self):
        d = OffsetDateTime(2020, 8, 15, 20, nanosecond=1, offset=hours(3))
        assert d.to_plain() == PlainDateTime(2020, 8, 15, 20, nanosecond=1)

    @pytest.mark.parametrize(
        "d, expect",
        [
            (
                OffsetDateTime(
                    2020,
                    8,
                    15,
                    23,
                    12,
                    9,
                    nanosecond=987_654_999,
                    offset=hours(5),
                ),
                py_datetime(
                    2020,
                    8,
                    15,
                    23,
                    12,
                    9,
                    987_654,
                    tzinfo=timezone(timedelta(hours=5)),
                ),
            ),
            (
                OffsetDateTime(
                    2020,
                    8,
                    15,
                    23,
                    12,
                    9,
                    nanosecond=987_654_999,
                    offset=minutes(-73),
                ),
                py_datetime(
                    2020,
                    8,
                    15,
                    23,
                    12,
                    9,
                    987_654,
                    tzinfo=timezone(timedelta(minutes=-73)),
                ),
            ),
        ],
    )
    def test_to_stdlib(self, d: OffsetDateTime, expect: py_datetime):
        assert d.to_stdlib() == expect


class TestStaleOffsetOkKwarg:
    def test_now(self):
        with warnings.catch_warnings():
            warnings.simplefilter("error")
            OffsetDateTime.now(hours(5), stale_offset_ok=True)

    def test_add(self):
        odt = OffsetDateTime(2024, 8, 15, 14, 30, offset=hours(5))
        with warnings.catch_warnings():
            warnings.simplefilter("error")
            odt.add(hours=1, stale_offset_ok=True)

    @pytest.mark.parametrize(
        ("method", "delta"),
        [
            ("add", hours(1)),
            ("subtract", hours(1)),
            ("add", ItemizedDelta(hours=1)),
            ("subtract", ItemizedDelta(hours=1)),
        ],
    )
    def test_positional_delta(self, method, delta):
        odt = OffsetDateTime(2024, 8, 15, 14, 30, offset=hours(5))
        with warnings.catch_warnings():
            warnings.simplefilter("error")
            getattr(odt, method)(delta, stale_offset_ok=True)

    def test_subtract(self):
        odt = OffsetDateTime(2024, 8, 15, 14, 30, offset=hours(5))
        with warnings.catch_warnings():
            warnings.simplefilter("error")
            odt.subtract(hours=1, stale_offset_ok=True)

    def test_since_until(self):
        a = OffsetDateTime(2024, 8, 15, 14, 30, offset=hours(5))
        b = OffsetDateTime(2024, 1, 15, 14, offset=hours(5))
        with warnings.catch_warnings():
            warnings.simplefilter("error")
            a.since(b, total="months", stale_offset_ok=True)
            a.until(b, in_units=["months", "hours"], stale_offset_ok=True)

    def test_read_by_truthiness(self):
        odt = OffsetDateTime(2024, 8, 15, 14, 30, offset=hours(5))
        with warnings.catch_warnings():
            warnings.simplefilter("error")
            odt.add(hours=1, stale_offset_ok=1)  # type: ignore[call-overload]
        with warns_here(StaleOffsetWarning):
            odt.add(hours=1, stale_offset_ok="")  # type: ignore[call-overload]

    def test_replace(self):
        odt = OffsetDateTime(2024, 8, 15, 14, 30, offset=hours(5))
        with warnings.catch_warnings():
            warnings.simplefilter("error")
            odt.replace(year=2025, stale_offset_ok=True)

    def test_replace_date(self):
        odt = OffsetDateTime(2024, 8, 15, 14, 30, offset=hours(5))
        with warnings.catch_warnings():
            warnings.simplefilter("error")
            odt.replace_date(Date(2025, 1, 1), stale_offset_ok=True)

    def test_replace_time(self):
        odt = OffsetDateTime(2024, 8, 15, 14, 30, offset=hours(5))
        with warnings.catch_warnings():
            warnings.simplefilter("error")
            odt.replace_time(Time(12, 0), stale_offset_ok=True)

    @pytest.mark.parametrize(
        "replace",
        [
            lambda d: d.replace(day=2),
            lambda d: d.replace_date(Date(2025, 1, 1)),
            lambda d: d.replace_time(Time(12, 0)),
        ],
    )
    def test_replace_emits_warning(self, replace):
        d = OffsetDateTime(2024, 8, 15, 14, 30, offset=hours(5))
        with warns_here(StaleOffsetWarning):
            replace(d)

    def test_replace_offset_is_silent(self):
        # A stated offset is not carried, so it cannot go stale
        d = OffsetDateTime(2024, 8, 15, 14, 30, offset=hours(5))
        with warnings.catch_warnings():
            warnings.simplefilter("error")
            moved = d.replace(offset=hours(3))
            assert d.replace(offset=hours(3), day=2) == OffsetDateTime(
                2024, 8, 2, 14, 30, offset=hours(3)
            )
        assert moved == OffsetDateTime(2024, 8, 15, 14, 30, offset=hours(3))
        assert moved.to_instant() == d.to_instant() + hours(2)

    def test_failing_replace_does_not_warn(self):
        d = OffsetDateTime(2024, 8, 15, 14, 30, offset=hours(5))
        with warnings.catch_warnings(record=True) as caught:
            warnings.simplefilter("always")
            with pytest.raises(ValueError):
                d.replace(month=13)
        assert caught == []

    def test_round(self):
        odt = OffsetDateTime(2024, 8, 15, 14, 30, offset=hours(5))
        with warnings.catch_warnings():
            warnings.simplefilter("error")
            odt.round("hour", stale_offset_ok=True)
