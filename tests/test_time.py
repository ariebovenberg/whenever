import re
from datetime import (
    time as py_time,
    timezone as py_timezone,
)
from fractions import Fraction
from typing import cast

import pytest
from whenever import (
    Date,
    PlainDateTime,
    Time,
    TimeDelta,
)

from .common import Idx


class TestInit:
    def test_all_args(self):
        t = Time(1, 2, 3, nanosecond=4_000)
        assert t.hour == 1
        assert t.minute == 2
        assert t.second == 3
        assert t.nanosecond == 4_000

    def test_all_kwargs(self):
        assert Time(hour=1, minute=2, second=3, nanosecond=4_000) == Time(
            1, 2, 3, nanosecond=4_000
        )

    def test_defaults(self):
        assert Time() == Time(0, 0, 0, nanosecond=0)

    @pytest.mark.parametrize(
        "args, kwargs",
        [
            ((1, 2, 3, 4), {}),  # nanosecond is keyword-only
            ((), {"iso_string": "01:02:03"}),
            ((), {"py_time": py_time(1, 2, 3)}),
        ],
    )
    def test_parameter_kinds(self, args, kwargs):
        with pytest.raises(TypeError):
            Time(*args, **kwargs)

    def test_out_of_range(self):
        with pytest.raises(ValueError):
            Time(24, 0, 0, nanosecond=0)
        with pytest.raises(ValueError):
            Time(0, 60, 0, nanosecond=0)
        with pytest.raises(ValueError):
            Time(0, 0, 60, nanosecond=0)
        with pytest.raises(ValueError):
            Time(0, 0, 0, nanosecond=1_000_000_000)

    def test_single_argument_wrong_type(self):
        with pytest.raises(
            TypeError,
            match=r"^Time\(\) requires an ISO 8601 string or datetime.time$",
        ):
            Time(b"x")  # type: ignore[call-overload]

    def test_iso(self):
        assert Time("01:02:03.000004") == Time(1, 2, 3, nanosecond=4_000)

    def test_leap_seconds_parsing(self):
        # Leap second (60) should be parsed and normalized to 59
        assert Time("01:02:60") == Time(1, 2, 59)
        assert Time("01:02:60.123456") == Time(
            1, 2, 59, nanosecond=123_456_000
        )
        # Basic format
        assert Time("010260") == Time(1, 2, 59)


class TestInitFromPy:
    def test_valid(self):
        assert Time(py_time(1, 2, 3, 4)) == Time(1, 2, 3, nanosecond=4_000)

    def test_tzinfo(self):
        with pytest.raises(
            ValueError,
            match=r"^time must be naive, got tzinfo=datetime\.timezone\.utc$",
        ):
            Time(py_time(1, tzinfo=py_timezone.utc))

    def test_fold_ignored(self):
        assert Time(py_time(1, 2, 3, 4, fold=1)) == Time(
            1, 2, 3, nanosecond=4_000
        )

    def test_subclass(self):
        class SubclassTime(py_time):
            pass

        assert Time(SubclassTime(1, 2, 3, 4)) == Time(
            1, 2, 3, nanosecond=4_000
        )


class TestAccessors:
    def test_constants(self):
        assert Time.MIN == Time()
        assert Time.MIDNIGHT == Time()
        assert Time.NOON == Time(12)
        assert Time.MAX == Time(23, 59, 59, nanosecond=999_999_999)


class TestFormatIso:
    @pytest.mark.parametrize(
        "t, expect",
        [
            (Time(1, 2, 3, nanosecond=40_000_000), "01:02:03.04"),
            (Time(1, 2, 3), "01:02:03"),
            (Time(1, 2), "01:02:00"),
            (Time(1), "01:00:00"),
        ],
    )
    def test_defaults(self, t, expect):
        assert str(t) == expect
        assert t.format_iso() == expect

    @pytest.mark.parametrize(
        "t, kwargs, expect",
        [
            (
                Time(1, 2, 3, nanosecond=40_000_000),
                {},
                "01:02:03.04",
            ),
            (
                Time(1, 2, 3, nanosecond=40_000000),
                {"unit": "millisecond"},
                "01:02:03.040",
            ),
            (
                Time(1, 2, 3, nanosecond=40_000000),
                {"unit": "minute", "basic": True},
                "0102",
            ),
            (
                Time(0, 0, 59, nanosecond=40_000000),
                {"unit": "second", "basic": False},
                "00:00:59",
            ),
            (
                Time(0, 0, 59, nanosecond=40),
                {"unit": "auto", "basic": False},
                "00:00:59.00000004",
            ),
            (
                Time(0, 0, 0),
                {"unit": "auto", "basic": True},
                "000000",
            ),
            (Time(23, 12, 9), {"unit": "hour"}, "23"),
        ],
    )
    def test_with_kwargs(self, t, kwargs, expect):
        assert t.format_iso(**kwargs) == expect

    @pytest.mark.parametrize(
        "t, kwargs",
        [
            (Time(1, 2, 3, nanosecond=40_000_000), {"basic": True}),
            (Time(23), {"unit": "hour"}),
        ],
    )
    def test_round_trip(self, t, kwargs):
        assert Time.parse_iso(t.format_iso(**kwargs)) == t

    def test_invalid(self):
        t = Time(1, 2, 3, nanosecond=40_000_000)
        with pytest.raises(ValueError, match="invalid unit: 'foo'"):
            t.format_iso(unit="foo")  # type: ignore[arg-type]

        with pytest.raises(ValueError, match="unit"):
            t.format_iso(unit="month", basic=True)  # type: ignore[arg-type]

        with pytest.raises(TypeError, match="sep"):
            t.format_iso(sep="T")  # type: ignore[call-arg]

    def test_repr(self):
        t = Time(1, 2, 3, nanosecond=40_000_000)
        assert repr(t) == 'Time("01:02:03.04")'


class TestParseIso:
    @pytest.mark.parametrize(
        "input, expect",
        [
            # extended format
            ("00:00:00.000000", Time()),
            ("01:02:03.004000", Time(1, 2, 3, nanosecond=4_000_000)),
            ("23:59:59.999999", Time(23, 59, 59, nanosecond=999_999_000)),
            ("23:59:59.99", Time(23, 59, 59, nanosecond=990_000_000)),
            ("23:59:59,123456789", Time(23, 59, 59, nanosecond=123_456_789)),
            ("23:59:59", Time(23, 59, 59)),
            ("23:59", Time(23, 59)),
            # basic format
            ("235959", Time(23, 59, 59)),
            ("235959.123456789", Time(23, 59, 59, nanosecond=123_456_789)),
            ("010203.004000", Time(1, 2, 3, nanosecond=4_000_000)),
            ("010203.0", Time(1, 2, 3)),
            ("010203,03", Time(1, 2, 3, nanosecond=30_000_000)),
            ("0102", Time(1, 2)),
            ("13", Time(13)),
            # leap second cases: 60 is normalized to 59
            ("01:02:60", Time(1, 2, 59)),
            ("23:59:60", Time(23, 59, 59)),
            ("00:00:60", Time(0, 0, 59)),
            ("23:59:60.999999999", Time(23, 59, 59, nanosecond=999_999_999)),
            ("12:34:60.123456", Time(12, 34, 59, nanosecond=123_456_000)),
            ("12:34:60.5", Time(12, 34, 59, nanosecond=500_000_000)),
            ("12:34:60,5", Time(12, 34, 59, nanosecond=500_000_000)),
            ("12:34:60,123456789", Time(12, 34, 59, nanosecond=123_456_789)),
            ("010260", Time(1, 2, 59)),
            ("235960.999999999", Time(23, 59, 59, nanosecond=999_999_999)),
            ("123460.123456", Time(12, 34, 59, nanosecond=123_456_000)),
            ("123460.5", Time(12, 34, 59, nanosecond=500_000_000)),
            ("123460,5", Time(12, 34, 59, nanosecond=500_000_000)),
        ],
    )
    def test_valid(self, input, expect):
        assert Time.parse_iso(input) == expect

    @pytest.mark.parametrize(
        "input",
        [
            # invalid values
            "32:02:03",
            "22:72:03",
            "22:32:63",
            "320203",
            "227203",
            "223263",
            # separator issues
            "2212:23",
            "22:1223.123",
            "22:12|23",
            "01:02:03.004.0",
            "22:12:23:34",
            # invalid fractional units
            "22:12.0",
            "2212.0",
            "22.2",
            # fractional issues
            "22:12:23, 23",
            "22:12:23.-23",
            "12:02:03.1234567890",
            "12:02:03;123456789",
            "12:34:56.",
            "123456,",
            # offset
            "01:02:03+00:00",
            "010203Z",
            # trailing/padding
            "01:02:034",
            "01:02:03 ",
            "010203 ",
            " 010203",
            # too short
            "01023",
            "011",
            "2",
            # basic format is HH/HHMM/HHMMSS only; trailing digits that CPython
            # reads as a separatorless fraction must be rejected
            "20103000",
            "20200101",
            "2010300",
            "123045678",
            "1230456789",
            # 24:00 can't be represented as a time without a date rollover
            "24",
            "2400",
            "24:00:00",
            "240000.0",
            # other
            "garbage",
            "",
            "**",
            # non-ascii
            "23:59:59.99999𝟙",
            "2𝟙:23",
            # invalid leap second cases
            "01:02:61",
            "010261",
            "23:60",
            "12:60:00",
            "0160",
        ],
    )
    def test_invalid(self, input):
        with pytest.raises(
            ValueError,
            match=r"^invalid ISO 8601 string: " + re.escape(repr(input)) + "$",
        ):
            Time.parse_iso(input)


class TestEquality:
    def test_eq(self):
        t = Time(1, 2, 3, nanosecond=4_000)
        same = Time(1, 2, 3, nanosecond=4_000)
        different = Time(1, 2, 3, nanosecond=5_000)

        assert t == same
        assert not t == different

        assert not t != same
        assert t != different

        assert hash(t) == hash(same)
        assert hash(t) != hash(different)


class TestComparison:
    def test_comparison(self):
        t = Time(1, 2, 3, nanosecond=4_000)
        same = Time(1, 2, 3, nanosecond=4_000)
        bigger1 = Time(2, 2, 3, nanosecond=4_000)
        bigger2 = Time(1, 2, 3, nanosecond=4_001)
        smaller1 = Time(1, 2, 3, nanosecond=3_999)
        smaller2 = Time(1, 2, 2, nanosecond=999_999_999)

        assert t <= same
        assert t <= bigger1
        assert t <= bigger2
        assert not t <= smaller1
        assert not t <= smaller2

        assert not t < same
        assert t < bigger1
        assert t < bigger2
        assert not t < smaller1
        assert not t < smaller2

        assert t >= same
        assert not t >= bigger1
        assert not t >= bigger2
        assert t >= smaller1
        assert t >= smaller2

        assert not t > same
        assert not t > bigger1
        assert not t > bigger2
        assert t > smaller1
        assert t > smaller2


class TestReplace:
    def test_replace(self):
        t = Time(1, 2, 3, nanosecond=4_000)
        assert t.replace() == t
        assert t.replace(hour=5) == Time(5, 2, 3, nanosecond=4_000)
        assert t.replace(minute=5) == Time(1, 5, 3, nanosecond=4_000)
        assert t.replace(second=5) == Time(1, 2, 5, nanosecond=4_000)
        assert t.replace(nanosecond=5) == Time(1, 2, 3, nanosecond=5)

        with pytest.raises(ValueError):
            t.replace(hour=24)

        with pytest.raises(TypeError):
            t.replace(tzinfo=None)  # type: ignore[call-arg]

        with pytest.raises(TypeError):
            t.replace(fold=0)  # type: ignore[call-arg]


class TestRound:
    @pytest.mark.parametrize(
        "t, increment, unit, floor, ceil, half_floor, half_ceil, half_even",
        [
            (
                Time.MIDNIGHT,
                1,
                "nanosecond",
                Time.MIDNIGHT,
                Time.MIDNIGHT,
                Time.MIDNIGHT,
                Time.MIDNIGHT,
                Time.MIDNIGHT,
            ),
            (
                Time(1, 2, 3, nanosecond=459_999_999),
                1,
                "nanosecond",
                Time(1, 2, 3, nanosecond=459_999_999),
                Time(1, 2, 3, nanosecond=459_999_999),
                Time(1, 2, 3, nanosecond=459_999_999),
                Time(1, 2, 3, nanosecond=459_999_999),
                Time(1, 2, 3, nanosecond=459_999_999),
            ),
            (
                Time(1, 2, 3, nanosecond=459_999_999),
                1,
                "second",
                Time(1, 2, 3),
                Time(1, 2, 4),
                Time(1, 2, 3),
                Time(1, 2, 3),
                Time(1, 2, 3),
            ),
            (
                Time(1, 2, 3, nanosecond=859_979_999),
                1,
                "second",
                Time(1, 2, 3),
                Time(1, 2, 4),
                Time(1, 2, 4),
                Time(1, 2, 4),
                Time(1, 2, 4),
            ),
            (
                Time(1, 2, 3, nanosecond=500_000_000),
                1,
                "second",
                Time(1, 2, 3),
                Time(1, 2, 4),
                Time(1, 2, 3),
                Time(1, 2, 4),
                Time(1, 2, 4),
            ),
            (
                Time(1, 2, 8, nanosecond=500_000_000),
                1,
                "second",
                Time(1, 2, 8),
                Time(1, 2, 9),
                Time(1, 2, 8),
                Time(1, 2, 9),
                Time(1, 2, 8),
            ),
            (
                Time(23, 59, 59, nanosecond=4_000),
                1,
                "second",
                Time(23, 59, 59),
                Time(0, 0, 0),
                Time(23, 59, 59),
                Time(23, 59, 59),
                Time(23, 59, 59),
            ),
            (
                Time(1, 2, 11, nanosecond=459_999_999),
                4,
                "second",
                Time(1, 2, 8),
                Time(1, 2, 12),
                Time(1, 2, 12),
                Time(1, 2, 12),
                Time(1, 2, 12),
            ),
            (
                Time(1, 2, 21, nanosecond=459_999_999),
                4,
                "second",
                Time(1, 2, 20),
                Time(1, 2, 24),
                Time(1, 2, 20),
                Time(1, 2, 20),
                Time(1, 2, 20),
            ),
            (
                Time(1, 2, 32),
                4,
                "second",
                Time(1, 2, 32),
                Time(1, 2, 32),
                Time(1, 2, 32),
                Time(1, 2, 32),
                Time(1, 2, 32),
            ),
            (
                Time(23, 2, 30),
                1,
                "minute",
                Time(23, 2, 0),
                Time(23, 3, 0),
                Time(23, 2, 0),
                Time(23, 3, 0),
                Time(23, 2, 0),
            ),
            (
                Time(23, 2, 30),
                1,
                "minute",
                Time(23, 2, 0),
                Time(23, 3, 0),
                Time(23, 2, 0),
                Time(23, 3, 0),
                Time(23, 2, 0),
            ),
            (
                Time(23, 52, 29, nanosecond=999_999_999),
                10,
                "minute",
                Time(23, 50, 0),
                Time(0, 0, 0),
                Time(23, 50, 0),
                Time(23, 50, 0),
                Time(23, 50, 0),
            ),
            (
                Time(11, 59, 29, nanosecond=999_999_999),
                12,
                "hour",
                Time(0, 0, 0),
                Time(12, 0, 0),
                Time(12, 0, 0),
                Time(12, 0, 0),
                Time(12, 0, 0),
            ),
        ],
    )
    def test_round(
        self, t, increment, unit, floor, ceil, half_floor, half_ceil, half_even
    ):
        assert t.round(unit, increment=increment) == half_even
        assert t.round(unit, increment=increment, mode="floor") == floor
        assert t.round(unit, increment=increment, mode="trunc") == floor
        assert t.round(unit, increment=increment, mode="ceil") == ceil
        assert t.round(unit, increment=increment, mode="expand") == ceil
        assert (
            t.round(unit, increment=increment, mode="half_floor") == half_floor
        )
        assert (
            t.round(unit, increment=increment, mode="half_trunc") == half_floor
        )
        assert (
            t.round(unit, increment=increment, mode="half_ceil") == half_ceil
        )
        assert (
            t.round(unit, increment=increment, mode="half_expand") == half_ceil
        )
        assert (
            t.round(unit, increment=increment, mode="half_even") == half_even
        )

    def test_default(self):
        assert Time(1, 2, 3, nanosecond=500_000_000).round() == Time(1, 2, 4)
        assert Time(1, 2, 8, nanosecond=500_000_000).round() == Time(1, 2, 8)

    def test_increment_read_through_index(self):
        t = Time(12, 39, 59)
        assert t.round("minute", increment=True) == t.round("minute")
        assert t.round("minute", increment=cast(int, Idx())) == t.round(
            "minute", increment=5
        )

    def test_round_by_timedelta(self):
        t = Time(12, 39, 59)
        assert t.round(TimeDelta(minutes=15)) == Time(12, 45)
        assert t.round(TimeDelta(hours=1)) == Time(13)
        assert t.round(TimeDelta(minutes=15), mode="floor") == Time(12, 30)

    def test_round_by_timedelta_half_even(self):
        assert Time(12, 30).round(TimeDelta(hours=1)) == Time(12)
        assert Time(13, 30).round(TimeDelta(hours=1)) == Time(14)

    @pytest.mark.parametrize(
        "t, unit, kwargs, exc, message",
        [
            # a value already on the increment validates the mode too
            *(
                (t, "second", {"mode": m}, ValueError, f"invalid mode: {m!r}")
                for t in (Time(1, 2, 3, nanosecond=4_000), Time(1, 2, 3))
                for m in ("foo", "TRUNC", None, 3)
            ),
            *(
                (
                    Time(1, 2, 3, nanosecond=4_000),
                    u,
                    {"increment": i},
                    ValueError,
                    "increment must divide a 24-hour day evenly",
                )
                for u, i in (
                    ("minute", 7),
                    ("second", 14),
                    ("millisecond", 17),
                    ("millisecond", 2001),
                    ("hour", 48),
                    ("hour", 20),
                    ("hour", (1 << 63) - 1),
                    ("second", 1 << 62),
                )
            ),
            *(
                (
                    Time(1, 2, 3),
                    "second",
                    {"increment": i},
                    ValueError,
                    "increment must be a positive integer",
                )
                for i in (0, -1)
            ),
            *(
                (
                    Time(1, 2, 3),
                    "second",
                    {"increment": i},
                    TypeError,
                    "increment must be an integer",
                )
                for i in (1.5, float("nan"), "5", Fraction(3, 2))
            ),
            # 'day' has nothing below it on a Time; 'week' has no fixed
            # increment
            *(
                (
                    Time(1, 2, 3, nanosecond=4_000),
                    u,
                    {},
                    ValueError,
                    f"invalid unit: {u!r}",
                )
                for u in ("foo", "day", "week", "minutes", None, 5)
            ),
            *(
                (
                    Time(12, 0),
                    u,
                    {},
                    ValueError,
                    "unit must divide a 24-hour day evenly",
                )
                for u in (TimeDelta(hours=7), TimeDelta(hours=25))
            ),
            *(
                (
                    Time(12, 0),
                    u,
                    {},
                    ValueError,
                    "unit must be a positive TimeDelta",
                )
                for u in (TimeDelta(hours=-1), TimeDelta.ZERO)
            ),
            *(
                (
                    Time(12, 0),
                    TimeDelta(hours=1),
                    {"increment": i},
                    TypeError,
                    "cannot specify an increment with a TimeDelta argument",
                )
                for i in (1, 2)
            ),
        ],
    )
    def test_rejections(self, t, unit, kwargs, exc, message):
        with pytest.raises(exc, match="^" + re.escape(message) + "$"):
            t.round(unit, **kwargs)


class TestConversion:
    def test_to_stdlib(self):
        t = Time(1, 2, 3, nanosecond=4_000_000)
        assert t.to_stdlib() == py_time(1, 2, 3, 4_000)
        # truncation
        assert Time(nanosecond=999).to_stdlib() == py_time(0)

    def test_on(self):
        t = Time(1, 2, 3, nanosecond=4_000)
        assert t.on(Date(2021, 1, 2)) == PlainDateTime(
            2021, 1, 2, 1, 2, 3, nanosecond=4_000
        )
