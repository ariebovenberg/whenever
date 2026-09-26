import re
import warnings
from datetime import timedelta as py_timedelta
from fractions import Fraction
from typing import Any, cast

import pytest
from pytest import approx
from whenever import (
    Date,
    DaysAssumed24HoursWarning,
    Instant,
    ItemizedDateDelta,
    ItemizedDelta,
    NaiveArithmeticWarning,
    OffsetDateTime,
    PlainDateTime,
    StaleOffsetWarning,
    TimeDelta,
    WheneverDeprecationWarning,
    ZonedDateTime,
    hours,
    microseconds,
    milliseconds,
    minutes,
    nanoseconds,
    seconds,
)

from .common import (
    INVALID_TDELTAS,
    ROUND_MODES_AT_A_TIE,
    Idx,
    suppress,
    warns_here,
)

MAX_HOURS = 9999 * 366 * 24
RANGE_MSG = "value or calculation out of range"

VALID_TDELTAS = [
    (
        "PT1H2M3.000004S",
        TimeDelta(hours=1, minutes=2, seconds=3, microseconds=4),
    ),
    (
        "PT58M2.999996S",
        TimeDelta(hours=1, minutes=-2, seconds=3, microseconds=-4),
    ),
    (
        "PT1H2M3.05S",
        TimeDelta(hours=1, minutes=2, seconds=3, microseconds=50_000),
    ),
    ("PT3H3S", TimeDelta(hours=1, minutes=120, seconds=3)),
    ("PT0S", TimeDelta()),
    ("PT0.000000001S", TimeDelta(nanoseconds=1)),
    ("PT450.000000001S", TimeDelta(seconds=450, nanoseconds=1)),
    ("PT0.000001S", TimeDelta(microseconds=1)),
    ("-PT0.000001S", TimeDelta(microseconds=-1)),
    ("PT1.999997S", TimeDelta(seconds=2, microseconds=-3)),
    ("PT5H", hours(5)),
    ("PT400H", hours(400)),
    ("PT400H0M0.0S", hours(400)),
    ("-PT4M", TimeDelta(minutes=-4)),
    ("PT0S", TimeDelta()),
    ("PT3M", TimeDelta(minutes=3)),
    ("+PT3M", TimeDelta(minutes=3)),
    ("PT0M", TimeDelta()),
    ("PT0.000000000S", TimeDelta()),
    # extremely long but still valid
    (
        "PT0H0M000000000000000300000000000.000000000S",
        TimeDelta(seconds=300_000_000_000),
    ),
    ("PT316192377600S", TimeDelta.MAX),
    # non-uppercase
    (
        "pt58m2.999996s",
        TimeDelta(hours=1, minutes=-2, seconds=3, microseconds=-4),
    ),
    ("PT316192377600s", TimeDelta.MAX),
    ("PT400h", hours(400)),
    # comma instead of dot
    ("PT1,999997S", TimeDelta(seconds=2, microseconds=-3)),
]


class TestInit:
    @pytest.mark.parametrize(
        "kwargs, expected_nanos",
        [
            (dict(), 0),
            # simplest cases
            (dict(hours=2), 2 * 3_600_000_000_000),
            (dict(minutes=3), 3 * 60_000_000_000),
            (dict(seconds=4), 4 * 1_000_000_000),
            (dict(milliseconds=5), 5 * 1_000_000),
            (dict(microseconds=6), 6 * 1_000),
            (dict(nanoseconds=7), 7),
            # all components
            (
                dict(
                    hours=1,
                    minutes=2,
                    seconds=90,
                    microseconds=4,
                    nanoseconds=5,
                    milliseconds=9,
                ),
                3_600_000_000_000
                + 2 * 60_000_000_000
                + 90 * 1_000_000_000
                + 9 * 1_000_000
                + 4 * 1_000
                + 5,
            ),
            # mixed signs
            (
                dict(hours=1, minutes=-2),
                3_600_000_000_000 - 2 * 60_000_000_000,
            ),
            (
                dict(hours=-1, milliseconds=2),
                -3_600_000_000_000 + 2 * 1_000_000,
            ),
            (dict(nanoseconds=1 << 66), 1 << 66),  # huge value outside i64
            # precision loss for floats
            (
                dict(microseconds=MAX_HOURS * 3_600_000_000 + 0.001),
                MAX_HOURS * 3_600_000_000_000,
            ),
            # no precision loss for integers
            (
                dict(hours=MAX_HOURS - 1),
                (MAX_HOURS - 1) * 3_600_000_000_000,
            ),
            (
                dict(minutes=MAX_HOURS * 60 - 1),
                MAX_HOURS * 3_600_000_000_000 - 60_000_000_000,
            ),
            (
                dict(seconds=MAX_HOURS * 3_600 - 1),
                MAX_HOURS * 3_600_000_000_000 - 1_000_000_000,
            ),
            (
                dict(milliseconds=MAX_HOURS * 3_600_000 - 1),
                MAX_HOURS * 3_600_000_000_000 - 1_000_000,
            ),
            (
                dict(microseconds=MAX_HOURS * 3_600_000_000 - 1),
                MAX_HOURS * 3_600_000_000_000 - 1_000,
            ),
            (
                dict(microseconds=-MAX_HOURS * 3_600_000_000 + 1),
                -MAX_HOURS * 3_600_000_000_000 + 1_000,
            ),
            (
                dict(nanoseconds=-MAX_HOURS * 3_600_000_000_000 + 1),
                -MAX_HOURS * 3_600_000_000_000 + 1,
            ),
            (
                dict(nanoseconds=MAX_HOURS * 3_600_000_000_000 - 1),
                MAX_HOURS * 3_600_000_000_000 - 1,
            ),
            # fractional values
            (dict(minutes=1.5), int(1.5 * 60_000_000_000)),
            (dict(seconds=1.5), int(1.5 * 1_000_000_000)),
        ],
    )
    def test_valid(self, kwargs, expected_nanos):
        d = TimeDelta(**kwargs)

        with suppress(WheneverDeprecationWarning):
            assert d.total("nanoseconds") == expected_nanos
        # the components are not accessible directly
        assert not hasattr(d, "hours")

    @pytest.mark.parametrize(
        "kwargs",
        [
            dict(hours=MAX_HOURS + 1),
            dict(hours=-MAX_HOURS - 1),
            dict(minutes=MAX_HOURS * 60 + 1),
            dict(minutes=-MAX_HOURS * 60 - 1),
            dict(seconds=MAX_HOURS * 3_600 + 1),
            dict(seconds=-MAX_HOURS * 3_600 - 1),
            dict(milliseconds=MAX_HOURS * 3_600_000 + 1),
            dict(milliseconds=-MAX_HOURS * 3_600_000 - 1),
            dict(microseconds=MAX_HOURS * 3_600_000_000 + 1),
            dict(microseconds=-MAX_HOURS * 3_600_000_000 - 1),
            dict(nanoseconds=MAX_HOURS * 3_600_000_000_000 + 1),
            dict(nanoseconds=-MAX_HOURS * 3_600_000_000_000 - 1),
            dict(hours=float("inf")),
            dict(minutes=float("inf")),
            dict(seconds=float("-inf")),
            dict(milliseconds=float("nan")),
            dict(milliseconds=1e273),
        ],
    )
    def test_invalid_out_of_range(self, kwargs):
        with pytest.raises(
            ValueError, match="value or calculation out of range"
        ):
            TimeDelta(**kwargs)

    @pytest.mark.parametrize(
        "kwargs, expected",
        [
            (dict(minutes=5_269_873_000, hours=-87_831_216), minutes(40)),
            (dict(hours=-87_831_216, minutes=5_269_873_000), minutes(40)),
            (
                dict(nanoseconds=-(1000 << 60), microseconds=1 << 60),
                TimeDelta.ZERO,
            ),
            (
                dict(weeks=10**9, days=-(7 * 10**9), days_assumed_24h_ok=True),
                TimeDelta.ZERO,
            ),
        ],
    )
    def test_range_checks_the_sum(self, kwargs, expected):
        assert TimeDelta(**kwargs) == expected
        assert TimeDelta.ZERO.add(**kwargs) == expected
        assert (
            Instant.from_timestamp(0).add(**kwargs)
            == Instant.from_timestamp(0) + expected
        )

    def test_invalid_kwargs(self):
        with pytest.raises(TypeError, match="foo"):
            TimeDelta(foo=1)  # type: ignore[call-overload]

        with pytest.raises(TypeError):
            TimeDelta(1)  # type: ignore[call-overload]

        with pytest.raises(
            TypeError,
            match=r"^TimeDelta\(\) requires an ISO 8601 string or datetime.timedelta$",
        ):
            TimeDelta(None)  # type: ignore[call-overload]

    @pytest.mark.parametrize(
        "args, kwargs",
        [
            ((1, 2), {}),  # components are keyword-only
            ((), {"iso_string": "PT1H"}),
            ((), {"py_timedelta": py_timedelta(hours=1)}),
        ],
    )
    def test_parameter_kinds(self, args, kwargs):
        with pytest.raises(TypeError):
            TimeDelta(*args, **kwargs)

        with pytest.raises(TypeError):
            TimeDelta(**{1: 43})  # type: ignore[arg-type,call-overload]

    def test_invalid_types(self):
        # a string would be repeated by ``str * int`` instead of failing
        with pytest.raises(TypeError, match="hours"):
            TimeDelta(hours="1")  # type: ignore[call-overload]

        with pytest.raises(TypeError, match="nanoseconds"):
            TimeDelta(nanoseconds=1.5)  # type: ignore[call-overload]

        with pytest.raises(
            TypeError, match=r"^nanoseconds must be an integer$"
        ):
            TimeDelta(nanoseconds="1")  # type: ignore[call-overload]

    def test_iso(self):
        assert TimeDelta("PT1H2M3.000004S") == TimeDelta(
            hours=1, minutes=2, seconds=3, microseconds=4
        )

    def test_weeks_and_days(self):
        with warns_here(DaysAssumed24HoursWarning):
            week = TimeDelta(weeks=1)

        assert week == TimeDelta(hours=7 * 24)

        with warns_here(DaysAssumed24HoursWarning):
            day = TimeDelta(days=1)

        assert day == hours(24)

        # months and years not allowed
        with pytest.raises(TypeError, match="months"):
            TimeDelta(months=1)  # type: ignore[call-overload]

        with pytest.raises(TypeError, match="years"):
            TimeDelta(years=1)  # type: ignore[call-overload]

    def test_days_warning_message(self):
        with warns_here(DaysAssumed24HoursWarning) as w:
            TimeDelta(days=1)
        message = str(w[0].message)
        assert "using days or weeks as exact time" in message
        assert "days_assumed_24h_ok=True" in message
        assert "guide/warnings.html" in message


class TestInitFromPy:
    def test_valid(self):
        assert TimeDelta(py_timedelta(0)) == TimeDelta.ZERO
        assert TimeDelta(
            py_timedelta(
                weeks=8, hours=1, minutes=2, seconds=3, microseconds=4
            )
        ) == TimeDelta(
            hours=1 + 7 * 24 * 8, minutes=2, seconds=3, microseconds=4
        )

        class SubclassTimedelta(py_timedelta):
            pass

        assert TimeDelta(SubclassTimedelta(1)) == TimeDelta(hours=24)

        with pytest.raises(ValueError, match="range"):
            TimeDelta(py_timedelta.max)

        with pytest.raises(ValueError, match="range"):
            TimeDelta(py_timedelta.min)

    def test_bound(self):
        # The full value is checked, not only the whole seconds
        assert TimeDelta(TimeDelta.MAX.to_stdlib()) == TimeDelta.MAX
        assert TimeDelta(TimeDelta.MIN.to_stdlib()) == TimeDelta.MIN
        with pytest.raises(
            ValueError, match="value or calculation out of range"
        ):
            TimeDelta(TimeDelta.MAX.to_stdlib() + py_timedelta(microseconds=1))
        with pytest.raises(
            ValueError, match="value or calculation out of range"
        ):
            TimeDelta(TimeDelta.MIN.to_stdlib() - py_timedelta(microseconds=1))


class TestFactories:
    @pytest.mark.parametrize(
        "f, arg, expected",
        [
            (hours, 3.5, TimeDelta(hours=3.5)),
            (minutes, 3.5, TimeDelta(minutes=3.5)),
            (seconds, 3.5, TimeDelta(seconds=3.5)),
            (microseconds, 3.5, TimeDelta(microseconds=3.5)),
            (milliseconds, 3.5, TimeDelta(milliseconds=3.5)),
            (nanoseconds, 3, TimeDelta(nanoseconds=3)),
        ],
    )
    def test_valid(self, f, arg, expected):
        assert f(arg) == expected

    @pytest.mark.parametrize(
        "factory, value",
        [
            (hours, 24 * 366 * 9999 + 1),
            (hours, -24 * 366 * 9999 - 1),
            (minutes, 60 * 24 * 366 * 9999 + 1),
            (minutes, -60 * 24 * 366 * 9999 - 1),
            (seconds, 3_600 * 24 * 366 * 9999 + 1),
            (seconds, -3_600 * 24 * 366 * 9999 - 1),
            (milliseconds, 3_600_000 * 24 * 366 * 9999 + 1),
            (milliseconds, -3_600_000 * 24 * 366 * 9999 - 1),
            (microseconds, 3_600_000_000 * 24 * 366 * 9999 + 1),
            (microseconds, -3_600_000_000 * 24 * 366 * 9999 - 1),
            (nanoseconds, 3_600_000_000_000 * 24 * 366 * 9999 + 1),
            (nanoseconds, -3_600_000_000_000 * 24 * 366 * 9999 - 1),
        ],
    )
    def test_bounds(self, factory, value):
        with pytest.raises(
            ValueError, match="value or calculation out of range"
        ):
            factory(value)

    @pytest.mark.parametrize(
        "f", [hours, minutes, seconds, milliseconds, microseconds, nanoseconds]
    )
    def test_module(self, f):
        assert f.__module__ == "whenever"

    @pytest.mark.parametrize(
        "f", [hours, minutes, seconds, milliseconds, microseconds]
    )
    def test_special_values(self, f):
        assert f(True) == f(1)
        with pytest.raises(ValueError, match=RANGE_MSG):
            f(float("nan"))
        with pytest.raises(ValueError, match=RANGE_MSG):
            f(float("inf"))
        with pytest.raises(
            TypeError, match=f"^{f.__name__} must be an integer or float$"
        ):
            f("1")
        with pytest.raises(
            TypeError, match=f"^{f.__name__} must be an integer or float$"
        ):
            f(None)

    @pytest.mark.parametrize("value", [float("nan"), float("inf"), "1", None])
    def test_nanoseconds_special_values(self, value):
        with pytest.raises(
            TypeError, match="^nanoseconds must be an integer$"
        ):
            nanoseconds(value)

    def test_nanoseconds_index_protocol(self):
        with pytest.raises(
            TypeError, match=r"^nanoseconds must be an integer$"
        ):
            nanoseconds(1.5)  # type: ignore[arg-type]
        with pytest.raises(
            TypeError, match=r"^nanoseconds must be an integer$"
        ):
            TimeDelta.ZERO.add(nanoseconds=1.5)  # type: ignore[call-overload]
        with pytest.raises(
            TypeError, match=r"^nanoseconds must be an integer$"
        ):
            TimeDelta.ZERO.subtract(nanoseconds="1")  # type: ignore[call-overload]
        five = cast(int, Idx())
        assert nanoseconds(five) == nanoseconds(5)
        assert nanoseconds(True) == nanoseconds(1)
        assert TimeDelta(nanoseconds=five) == nanoseconds(5)
        assert TimeDelta.ZERO.add(nanoseconds=five) == nanoseconds(5)


class TestExtremes:
    def test_constants(self):
        assert TimeDelta.ZERO == TimeDelta()
        assert TimeDelta.MAX == TimeDelta(
            nanoseconds=9999 * 366 * 24 * 60 * 60 * 1_000_000_000
        )
        assert TimeDelta.MIN == -TimeDelta.MAX

    def test_total(self):
        assert TimeDelta.MAX.total("hours") == MAX_HOURS
        assert TimeDelta.MIN.total("hours") == -MAX_HOURS
        assert (
            TimeDelta.MAX.total("nanoseconds") == MAX_HOURS * 3_600_000_000_000
        )
        assert (
            TimeDelta.MIN.total("nanoseconds")
            == -MAX_HOURS * 3_600_000_000_000
        )

    def test_in_units(self):
        assert TimeDelta.MAX.in_units(["hours"]).strict_eq(
            ItemizedDelta(hours=MAX_HOURS)
        )
        assert TimeDelta.MIN.in_units(["hours", "minutes"]).strict_eq(
            ItemizedDelta(hours=-MAX_HOURS, minutes=0)
        )

    def test_sign_operators(self):
        assert abs(TimeDelta.MIN) == TimeDelta.MAX
        assert abs(TimeDelta.MAX) == TimeDelta.MAX
        assert -TimeDelta.MIN == TimeDelta.MAX
        assert -TimeDelta.MAX == TimeDelta.MIN
        assert bool(TimeDelta.MIN) and bool(TimeDelta.MAX)
        assert not TimeDelta.ZERO


class TestConversion:
    @pytest.mark.parametrize(
        "d, expected",
        [
            (TimeDelta(), py_timedelta(0)),
            (
                TimeDelta(hours=1, minutes=2, seconds=3, microseconds=4),
                py_timedelta(hours=1, minutes=2, seconds=3, microseconds=4),
            ),
            (TimeDelta(nanoseconds=-42_865), py_timedelta(microseconds=-43)),
            (TimeDelta(nanoseconds=1), py_timedelta()),
            (TimeDelta(nanoseconds=1_000), py_timedelta(microseconds=1)),
            (TimeDelta(nanoseconds=1_000_000), py_timedelta(milliseconds=1)),
            (TimeDelta(nanoseconds=987), py_timedelta()),
            (TimeDelta(nanoseconds=12987), py_timedelta(microseconds=12)),
            (TimeDelta(hours=48, nanoseconds=800), py_timedelta(days=2)),
            (
                TimeDelta(hours=48, nanoseconds=-800),
                py_timedelta(days=2, microseconds=-1),
            ),
        ],
    )
    def test_to_stdlib(self, d, expected):
        assert d.to_stdlib() == expected

    @pytest.mark.parametrize(
        "nanos, micros",
        [(-1, -1), (-1_001, -2), (1_999, 1)],
    )
    def test_to_stdlib_floors(self, nanos, micros):
        assert TimeDelta(nanoseconds=nanos).to_stdlib() == py_timedelta(
            microseconds=micros
        )


class TestFormatIso:
    @pytest.mark.parametrize(
        "d, expected",
        [
            (
                TimeDelta(hours=1, minutes=2, seconds=3, microseconds=4),
                "PT1H2M3.000004S",
            ),
            (
                TimeDelta(hours=1, minutes=-2, seconds=3, microseconds=-4),
                "PT58M2.999996S",
            ),
            (
                TimeDelta(hours=1, minutes=2, seconds=3, microseconds=50_000),
                "PT1H2M3.05S",
            ),
            (TimeDelta(hours=1, minutes=120, seconds=3), "PT3H3S"),
            (TimeDelta(), "PT0S"),
            (TimeDelta(microseconds=1), "PT0.000001S"),
            (TimeDelta(microseconds=-1), "-PT0.000001S"),
            (TimeDelta(hours=4, nanoseconds=40), "PT4H0.00000004S"),
            (TimeDelta(seconds=2, microseconds=-3), "PT1.999997S"),
            (hours(5), "PT5H"),
            (hours(400), "PT400H"),
            (TimeDelta(minutes=-4), "-PT4M"),
        ],
    )
    def test_examples(self, d, expected):
        assert d.format_iso() == expected

    def test_repr(self):
        assert (
            repr(TimeDelta(hours=1, minutes=2, seconds=3, microseconds=4))
            == 'TimeDelta("PT1h2m3.000004s")'
        )
        assert repr(TimeDelta()) == 'TimeDelta("PT0s")'
        assert repr(TimeDelta(minutes=23, seconds=1)) == 'TimeDelta("PT23m1s")'

    def test_str(self):
        d = TimeDelta(hours=1, minutes=2, seconds=3, microseconds=4)
        assert str(d) == d.format_iso() == "PT1H2M3.000004S"
        assert str(TimeDelta()) == "PT0S"
        assert TimeDelta.parse_iso(d.format_iso()) == d


class TestParseIso:
    @pytest.mark.parametrize("s, expected", VALID_TDELTAS)
    def test_valid(self, s, expected):
        assert TimeDelta.parse_iso(s) == expected

    @pytest.mark.parametrize("s", INVALID_TDELTAS)
    def test_invalid(self, s) -> None:
        with pytest.raises(
            ValueError,
            match=r"^invalid ISO 8601 string: " + re.escape(repr(s)) + "$",
        ):
            TimeDelta.parse_iso(s)

    @pytest.mark.parametrize(
        "s",
        [
            "PT90000000H",
            "-PT90000000H",
            "PT5500000000M",
            "-PT5500000000M",
            "PT400000000000.00S",
            "-PT400000000000.00S",
            f"PT{10_000 * 366 * 24}H",
            f"PT{10_000 * 366 * 24 * 3600}S",
            "PT340282366920938463463374607431S",
            # a component that overflows before the range check
            "PT999999999999999999999999999H",
            "PT" + "9" * 35 + "H",
            "PT" + "9" * 35 + "M",
            "PT" + "9" * 35 + "S",
            "PT" + "9" * 35 + ".5S",
            "PT1H" + "9" * 35 + "M",
        ],
    )
    def test_too_large(self, s) -> None:
        with pytest.raises(ValueError, match=f"^{RANGE_MSG}$"):
            TimeDelta.parse_iso(s)

    def test_digit_limit(self) -> None:
        assert TimeDelta.parse_iso("PT" + "0" * 34 + "1H") == hours(1)
        s = "PT" + "0" * 35 + "1H"
        with pytest.raises(
            ValueError, match=f"^invalid ISO 8601 string: {s!r}$"
        ):
            TimeDelta.parse_iso(s)


class TestEquality:
    def test_same_and_different(self):
        d = TimeDelta(hours=1, minutes=2, seconds=3, microseconds=4)
        same = TimeDelta(hours=1, minutes=2, seconds=3, microseconds=4)
        same_total = TimeDelta(hours=0, minutes=62, seconds=3, microseconds=4)
        different = TimeDelta(hours=1, minutes=2, seconds=3, microseconds=5)
        assert d == same
        assert d == same_total
        assert not d == different
        assert not d != same
        assert not d != same_total
        assert d != different

        assert hash(d) == hash(same)
        assert hash(d) == hash(same_total)
        assert hash(d) != hash(different)


class TestComparison:
    def test_ordering(self):
        d = TimeDelta(hours=1, minutes=2, seconds=3, microseconds=4)
        same = TimeDelta(hours=1, minutes=2, seconds=3, microseconds=4)
        same_total = TimeDelta(hours=0, minutes=62, seconds=3, microseconds=4)
        bigger = TimeDelta(hours=1, minutes=2, seconds=3, microseconds=5)
        smaller = TimeDelta(hours=1, minutes=2, seconds=3, microseconds=3)

        assert d <= same
        assert d <= same_total
        assert d <= bigger
        assert not d <= smaller

        assert not d < same
        assert not d < same_total
        assert d < bigger
        assert not d < smaller

        assert d >= same
        assert d >= same_total
        assert not d >= bigger
        assert d >= smaller

        assert not d > same
        assert not d > same_total
        assert not d > bigger
        assert d > smaller


class TestAddSubtract:
    @pytest.mark.parametrize(
        "kwargs, expected",
        [
            (
                {},
                TimeDelta(hours=1, minutes=2, seconds=3, microseconds=4),
            ),
            (
                dict(minutes=60),
                TimeDelta(hours=2, minutes=2, seconds=3, microseconds=4),
            ),
            (
                dict(minutes=-120),
                TimeDelta(hours=-1, minutes=2, seconds=3, microseconds=4),
            ),
        ],
    )
    def test_valid(self, kwargs, expected: TimeDelta):
        d = TimeDelta(hours=1, minutes=2, seconds=3, microseconds=4)
        assert d + TimeDelta(**kwargs) == expected
        assert d.add(**kwargs) == expected
        assert d.add(TimeDelta(**kwargs)) == expected

        negated_kwargs = {k: -v for k, v in kwargs.items()}
        assert d - TimeDelta(**negated_kwargs) == expected
        assert d.subtract(**negated_kwargs) == expected
        assert d.subtract(TimeDelta(**negated_kwargs)) == expected

    def test_days_and_weeks(self):
        d = TimeDelta(seconds=1.5)
        with warns_here(DaysAssumed24HoursWarning):
            assert d.add(weeks=4) == d.add(hours=4 * 7 * 24)

        with warns_here(DaysAssumed24HoursWarning):
            assert d.add(days=-9) == d.add(hours=-9 * 24)

    def test_out_of_range(self):
        d = TimeDelta(hours=1, minutes=2, seconds=3, microseconds=4)
        ns = TimeDelta(nanoseconds=1)
        with pytest.raises(ValueError, match="range"):
            TimeDelta.MAX + ns

        with pytest.raises(ValueError, match="range"):
            TimeDelta.MIN - ns

        with pytest.raises(ValueError, match="range"):
            d.add(hours=366 * 24 * 10000)

        with pytest.raises(ValueError, match="range"):
            d.subtract(hours=-366 * 24 * 10000)

    def test_no_positional_arg_and_kwargs(self):
        d = TimeDelta(hours=1, minutes=2, seconds=3, microseconds=4)

        with pytest.raises(TypeError, match="mix"):
            d.add(hours(1), minutes=2)  # type: ignore[call-overload]

        with pytest.raises(TypeError, match="mix"):
            d.subtract(hours(1), minutes=2)  # type: ignore[call-overload]

    def test_operator_not_supported(self):
        d = TimeDelta(hours=1, minutes=2, seconds=3, microseconds=4)

        with pytest.raises(TypeError, match="unsupported operand"):
            d + Ellipsis  # type: ignore[operator]

        with pytest.raises(TypeError, match="unsupported operand"):
            d - Ellipsis  # type: ignore[operator]

        with pytest.raises(TypeError, match="unsupported operand"):
            Ellipsis + d  # type: ignore[operator]

        with pytest.raises(TypeError, match="unsupported operand"):
            Ellipsis - d  # type: ignore[operator]


class TestMultiply:
    def test_examples(self):
        d = TimeDelta(hours=1, minutes=2, seconds=3, microseconds=4)
        assert d * 2 == TimeDelta(
            hours=2, minutes=4, seconds=6, microseconds=8
        )
        assert d * 0.5 == TimeDelta(
            hours=0, minutes=31, seconds=1, microseconds=500_002
        )
        assert d * 0.5 == 0.5 * d
        assert d * 2 == 2 * d

        # allow very big ints if there's no overflow
        assert TimeDelta(nanoseconds=1) * (1 << 66) == TimeDelta(
            nanoseconds=1 << 66
        )
        assert TimeDelta(nanoseconds=1) * float(1 << 66) == TimeDelta(
            nanoseconds=1 << 66
        )

        # overflow
        with pytest.raises(ValueError, match="range"):
            d * 1_000_000_000

        with pytest.raises(TypeError, match="unsupported operand"):
            d * Ellipsis  # type: ignore[operator]

        with pytest.raises(TypeError, match="unsupported operand"):
            Ellipsis * d  # type: ignore[operator]

    def test_float_rounds_half_even(self):
        assert nanoseconds(7) * 0.5 == nanoseconds(4)
        assert nanoseconds(5) * 0.5 == nanoseconds(2)
        assert nanoseconds(-7) * 0.5 == nanoseconds(-4)
        assert nanoseconds(3) * 0.5 == nanoseconds(2)
        assert 0.5 * nanoseconds(7) == nanoseconds(4)
        # the float product of the whole nanosecond count, on long deltas too
        assert nanoseconds(
            -163_204_499_416_938_994_927
        ) * 0.001 == nanoseconds(-163_204_499_416_939_008)

    def test_bool_is_int(self):
        d = TimeDelta(hours=1, minutes=2, seconds=3, microseconds=4)
        assert d * True == d
        assert d * False == TimeDelta.ZERO
        assert True * d == d

    @pytest.mark.parametrize("factor", [float("nan"), float("inf")])
    def test_nan_and_inf(self, factor):
        d = TimeDelta(hours=1)
        with pytest.raises(
            ValueError, match="value or calculation out of range"
        ):
            d * factor
        with pytest.raises(
            ValueError, match="value or calculation out of range"
        ):
            factor * d


class TestDivision:
    def test_by_number(self):
        d = TimeDelta(hours=1, minutes=2, seconds=3, microseconds=4)
        assert d / 2 == TimeDelta(
            hours=0, minutes=31, seconds=1, microseconds=500_002
        )
        assert d / 0.5 == TimeDelta(
            hours=2, minutes=4, seconds=6, microseconds=8
        )
        assert TimeDelta.MAX / 1.0 == TimeDelta.MAX
        assert TimeDelta.MIN / 1.0 == TimeDelta.MIN

    @pytest.mark.parametrize(
        "nanos, divisor, expected",
        [
            (7, 2, 4),
            (-7, 2, -4),
            (7, -2, -4),
            (-7, -2, 4),
            (5, 2, 2),
            (3, 2, 2),
            (1, 3, 0),
            (10**18, 3, 333_333_333_333_333_333),
            (0, 7, 0),
        ],
    )
    def test_by_int_rounds_half_even(self, nanos, divisor, expected):
        assert nanoseconds(nanos) / divisor == nanoseconds(expected)

    def test_by_int_is_exact_on_long_deltas(self):
        third = TimeDelta.MAX / 3
        assert third == nanoseconds(TimeDelta.MAX.total("nanoseconds") // 3)
        assert TimeDelta.MAX / 1 == TimeDelta.MAX
        assert TimeDelta.MIN / -1 == TimeDelta.MAX
        # a huge divisor is not narrowed to a float
        assert TimeDelta.MAX / (1 << 80) == TimeDelta.ZERO
        # nor is a divisor beyond 128 bits rejected
        assert hours(1) / (1 << 200) == TimeDelta.ZERO
        assert hours(-1) / -(1 << 200) == TimeDelta.ZERO

    def test_by_float_rounds_half_even(self):
        assert nanoseconds(7) / 2.0 == nanoseconds(4)
        assert nanoseconds(5) / 2.0 == nanoseconds(2)
        assert nanoseconds(-7) / 2.0 == nanoseconds(-4)
        assert nanoseconds(7) / 0.5 == nanoseconds(14)

    def test_bool_is_int(self):
        d = TimeDelta(hours=1, minutes=2, seconds=3, microseconds=4)
        assert d / True == d

    def test_nan_and_inf(self):
        d = TimeDelta(hours=1)
        with pytest.raises(
            ValueError, match="value or calculation out of range"
        ):
            d / float("nan")
        with pytest.raises(
            ValueError, match="value or calculation out of range"
        ):
            d / 1e-300
        assert d / float("inf") == TimeDelta.ZERO
        # a finite result beyond the bound
        with pytest.raises(
            ValueError, match="value or calculation out of range"
        ):
            TimeDelta.MAX / 0.5

    def test_divide_by_timedelta(self):
        d = TimeDelta(hours=1, minutes=2, seconds=3, microseconds=4)
        assert d / hours(1) == approx(
            1 + 2 / 60 + 3 / 3_600 + 4 / 3_600_000_000
        )
        assert TimeDelta.ZERO / TimeDelta.MAX == 0.0
        assert TimeDelta.ZERO / TimeDelta.MIN == 0.0
        assert TimeDelta.MAX / TimeDelta.MAX == 1.0
        assert TimeDelta.MIN / TimeDelta.MIN == 1.0
        assert TimeDelta.MAX / TimeDelta.MIN == -1.0
        assert TimeDelta.MIN / TimeDelta.MAX == -1.0

    def test_divide_by_zero(self):
        d = TimeDelta(hours=1, minutes=2, seconds=3, microseconds=4)
        with pytest.raises(ZeroDivisionError, match="^division by zero$"):
            d / TimeDelta()

        with pytest.raises(ZeroDivisionError, match="^division by zero$"):
            d / 0

        with pytest.raises(ZeroDivisionError, match="^division by zero$"):
            d / 0.0

    def test_invalid_type(self):
        with pytest.raises(TypeError, match="unsupported operand"):
            TimeDelta(hours=1) / Ellipsis  # type: ignore[operator]


class TestFloorDiv:
    def test_examples(self):
        d = TimeDelta(hours=3, minutes=40, seconds=3, microseconds=4)
        assert d // hours(1) == 3
        assert d // TimeDelta(minutes=5) == 44
        assert d // TimeDelta(minutes=-5) == -45
        assert -d // TimeDelta(minutes=5) == -45
        assert -d // TimeDelta(minutes=-5) == 44

        # sub-second dividend
        assert d // TimeDelta(microseconds=-9) == -1467000001
        assert -d // TimeDelta(microseconds=9) == -1467000001
        assert -d // TimeDelta(microseconds=-9) == 1467000000
        assert d // TimeDelta(microseconds=9) == 1467000000

        # extreme cases
        assert TimeDelta.ZERO // TimeDelta.MAX == 0
        assert TimeDelta.ZERO // TimeDelta.MIN == 0
        assert TimeDelta.MAX // TimeDelta.MAX == 1
        assert TimeDelta.MIN // TimeDelta.MIN == 1
        assert TimeDelta.MAX // TimeDelta.MIN == -1
        assert TimeDelta.MIN // TimeDelta.MAX == -1
        # result larger than i64
        assert (
            TimeDelta.MAX // TimeDelta(nanoseconds=1)
            == 316192377600_000_000_000
        )

    def test_divide_by_zero(self):
        d = TimeDelta(hours=1, minutes=2, seconds=3, microseconds=4)
        with pytest.raises(ZeroDivisionError, match="^division by zero$"):
            d // TimeDelta()

    def test_invalid(self):
        d = TimeDelta(hours=1, minutes=2, seconds=3, microseconds=4)
        with pytest.raises(TypeError):
            d // "invalid"  # type: ignore[operator]

        with pytest.raises(TypeError):
            "invalid" // d  # type: ignore[operator]


class TestRemainder:
    def test_examples(self):
        d = TimeDelta(hours=3, minutes=40, seconds=3, microseconds=4)
        assert d % hours(1) == TimeDelta(minutes=40, seconds=3, microseconds=4)
        assert d % TimeDelta(minutes=5) == TimeDelta(seconds=3, microseconds=4)
        assert d % TimeDelta(minutes=-5) == TimeDelta(
            minutes=-5, seconds=3, microseconds=4
        )
        assert -d % TimeDelta(minutes=5) == TimeDelta(
            minutes=5, seconds=-3, microseconds=-4
        )
        assert -d % TimeDelta(minutes=-5) == TimeDelta(
            seconds=-3, microseconds=-4
        )

        # sub-second dividend
        assert d % TimeDelta(microseconds=-9) == TimeDelta(microseconds=-5)
        assert -d % TimeDelta(microseconds=9) == TimeDelta(microseconds=5)
        assert -d % TimeDelta(microseconds=-9) == TimeDelta(microseconds=-4)
        assert d % TimeDelta(microseconds=9) == TimeDelta(microseconds=4)

        # extreme cases
        assert TimeDelta.ZERO % TimeDelta.MAX == TimeDelta.ZERO
        assert TimeDelta.ZERO % TimeDelta.MIN == TimeDelta.ZERO
        assert TimeDelta.MAX % TimeDelta.MAX == TimeDelta.ZERO
        assert TimeDelta.MIN % TimeDelta.MIN == TimeDelta.ZERO
        assert TimeDelta.MAX % TimeDelta.MIN == TimeDelta.ZERO
        assert TimeDelta.MIN % TimeDelta.MAX == TimeDelta.ZERO
        # result larger than i64
        assert (TimeDelta.MAX - TimeDelta(nanoseconds=1)) % TimeDelta.MAX == (
            TimeDelta.MAX - TimeDelta(nanoseconds=1)
        )

    def test_divide_by_zero(self):
        d = TimeDelta(hours=1, minutes=2, seconds=3, microseconds=4)
        with pytest.raises(ZeroDivisionError, match="^division by zero$"):
            d % TimeDelta()

    def test_invalid(self):
        d = TimeDelta(hours=1, minutes=2, seconds=3, microseconds=4)
        with pytest.raises(TypeError):
            d % "invalid"  # type: ignore[operator]

        with pytest.raises(TypeError):
            5.9 % d  # type: ignore[operator]


class TestUnaryOperators:
    def test_boolean(self):
        assert not TimeDelta(hours=0, minutes=0, seconds=0, microseconds=0)
        assert not TimeDelta(hours=1, minutes=-60)
        assert TimeDelta(microseconds=1)

    def test_negate(self):
        assert TimeDelta.ZERO == -TimeDelta.ZERO
        assert TimeDelta(
            hours=-1, minutes=2, seconds=-3, microseconds=4
        ) == -TimeDelta(hours=1, minutes=-2, seconds=3, microseconds=-4)
        assert -TimeDelta.MAX == TimeDelta.MIN

    @pytest.mark.parametrize(
        "d",
        [
            TimeDelta(hours=1, minutes=2, seconds=3, microseconds=4),
            TimeDelta.ZERO,
            TimeDelta(hours=-2, minutes=-15),
        ],
    )
    def test_pos(self, d):
        assert d is +d

    def test_abs(self):
        assert abs(TimeDelta()) == TimeDelta()
        assert abs(
            TimeDelta(hours=-1, minutes=-2, seconds=-3, microseconds=-4)
        ) == TimeDelta(hours=1, minutes=2, seconds=3, microseconds=4)
        assert abs(hours(1)) == hours(1)


class TestOtherOperands:
    """A TimeDelta composes with a TimeDelta alone, and shifts a datetime
    only from the left of ``+``."""

    @pytest.mark.parametrize(
        "other",
        [
            ItemizedDelta(hours=1),
            ItemizedDateDelta(days=1),
            Date(2023, 1, 1),
        ],
    )
    def test_add_sub_wrong_operand(self, other):
        with pytest.raises(TypeError):
            hours(1) + other
        with pytest.raises(TypeError):
            hours(1) - other
        with pytest.raises(TypeError):
            other - hours(1)

    @pytest.mark.parametrize(
        "dt",
        [
            Instant.from_utc(2023, 1, 1),
            PlainDateTime(2023, 1, 1),
            OffsetDateTime(2023, 1, 1, offset=hours(2)),
            ZonedDateTime(2023, 1, 1, tz="Europe/Amsterdam"),
        ],
    )
    def test_delta_minus_datetime(self, dt):
        with pytest.raises(TypeError):
            hours(1) - dt

    def test_number_divisors(self):
        with pytest.raises(TypeError):
            hours(1) // 2  # type: ignore[operator]
        with pytest.raises(TypeError):
            hours(1) % 2  # type: ignore[operator]
        with pytest.raises(TypeError):
            divmod(hours(1), 2)  # type: ignore[operator]
        with pytest.raises(TypeError):
            divmod(hours(1), hours(1))  # type: ignore[operator]

    def test_plain_datetime_addition_warns_from_both_sides(self):
        dt = PlainDateTime(2021, 1, 31)
        with pytest.warns(NaiveArithmeticWarning):
            dt + hours(1)
        with pytest.warns(NaiveArithmeticWarning):
            hours(1) + dt

    def test_zero_delta_plain_datetime_arithmetic_does_not_warn(self):
        # A zero shift assumes nothing, as add() and subtract() have it
        dt = PlainDateTime(2021, 1, 31)
        with warnings.catch_warnings():
            warnings.simplefilter("error")
            assert dt + TimeDelta.ZERO == dt
            assert TimeDelta.ZERO + dt == dt
            assert dt - TimeDelta.ZERO == dt

    @pytest.mark.parametrize(
        "dt",
        [
            PlainDateTime(2021, 1, 31),
            OffsetDateTime(2021, 1, 31, offset=hours(0)),
            ZonedDateTime(2021, 1, 31, tz="UTC"),
            Instant.from_utc(2021, 1, 31),
        ],
    )
    def test_reflected_datetime_addition(self, dt):
        delta = hours(2)
        with warnings.catch_warnings():
            warnings.simplefilter("ignore")
            expected = dt + delta
        with warnings.catch_warnings():
            warnings.simplefilter("ignore")
            assert delta + dt == expected


class TestRound:
    @pytest.mark.parametrize(
        "t, increment, unit, floor, ceil, half_floor, half_ceil, half_even",
        [
            (
                TimeDelta.ZERO,
                1,
                "nanosecond",
                TimeDelta.ZERO,
                TimeDelta.ZERO,
                TimeDelta.ZERO,
                TimeDelta.ZERO,
                TimeDelta.ZERO,
            ),
            (
                TimeDelta(nanoseconds=5),
                10,
                "nanosecond",
                TimeDelta.ZERO,
                TimeDelta(nanoseconds=10),
                TimeDelta.ZERO,
                TimeDelta(nanoseconds=10),
                TimeDelta.ZERO,
            ),
            (
                TimeDelta(nanoseconds=-5),
                10,
                "nanosecond",
                TimeDelta(nanoseconds=-10),
                TimeDelta.ZERO,
                TimeDelta(nanoseconds=-10),
                TimeDelta.ZERO,
                TimeDelta.ZERO,
            ),
            (
                TimeDelta(nanoseconds=-105),
                10,
                "nanosecond",
                TimeDelta(nanoseconds=-110),
                TimeDelta(nanoseconds=-100),
                TimeDelta(nanoseconds=-110),
                TimeDelta(nanoseconds=-100),
                TimeDelta(nanoseconds=-100),
            ),
            (
                hours(-107),
                10,
                "hour",
                hours(-110),
                hours(-100),
                hours(-110),
                hours(-110),
                hours(-110),
            ),
            (
                TimeDelta(hours=1, minutes=2, seconds=3, nanoseconds=4),
                1,
                "nanosecond",
                TimeDelta(hours=1, minutes=2, seconds=3, nanoseconds=4),
                TimeDelta(hours=1, minutes=2, seconds=3, nanoseconds=4),
                TimeDelta(hours=1, minutes=2, seconds=3, nanoseconds=4),
                TimeDelta(hours=1, minutes=2, seconds=3, nanoseconds=4),
                TimeDelta(hours=1, minutes=2, seconds=3, nanoseconds=4),
            ),
            (
                -TimeDelta(hours=1, minutes=2, seconds=3, nanoseconds=4),
                1,
                "nanosecond",
                -TimeDelta(hours=1, minutes=2, seconds=3, nanoseconds=4),
                -TimeDelta(hours=1, minutes=2, seconds=3, nanoseconds=4),
                -TimeDelta(hours=1, minutes=2, seconds=3, nanoseconds=4),
                -TimeDelta(hours=1, minutes=2, seconds=3, nanoseconds=4),
                -TimeDelta(hours=1, minutes=2, seconds=3, nanoseconds=4),
            ),
            # nanoseconds avoids a tie
            (
                TimeDelta(hours=1, minutes=2, seconds=3, nanoseconds=4),
                2,
                "second",
                TimeDelta(hours=1, minutes=2, seconds=2),
                TimeDelta(hours=1, minutes=2, seconds=4),
                TimeDelta(hours=1, minutes=2, seconds=4),
                TimeDelta(hours=1, minutes=2, seconds=4),
                TimeDelta(hours=1, minutes=2, seconds=4),
            ),
            # nanoseconds results in a tie
            (
                TimeDelta(hours=1, minutes=2, seconds=7, milliseconds=500),
                3,
                "second",
                TimeDelta(hours=1, minutes=2, seconds=6),
                TimeDelta(hours=1, minutes=2, seconds=9),
                TimeDelta(hours=1, minutes=2, seconds=6),
                TimeDelta(hours=1, minutes=2, seconds=9),
                TimeDelta(hours=1, minutes=2, seconds=6),
            ),
            (
                TimeDelta(hours=1, minutes=2, seconds=3),
                2,
                "second",
                TimeDelta(hours=1, minutes=2, seconds=2),
                TimeDelta(hours=1, minutes=2, seconds=4),
                TimeDelta(hours=1, minutes=2, seconds=2),
                TimeDelta(hours=1, minutes=2, seconds=4),
                TimeDelta(hours=1, minutes=2, seconds=4),
            ),
            (
                TimeDelta(hours=1, minutes=7.5),
                15,
                "minute",
                TimeDelta(hours=1, minutes=0),
                TimeDelta(hours=1, minutes=15),
                TimeDelta(hours=1, minutes=0),
                TimeDelta(hours=1, minutes=15),
                TimeDelta(hours=1, minutes=0),
            ),
            (
                -TimeDelta(hours=4, minutes=43),
                30,
                "minute",
                -hours(5),
                -TimeDelta(hours=4.5),
                -TimeDelta(hours=4.5),
                -TimeDelta(hours=4.5),
                -TimeDelta(hours=4.5),
            ),
            (
                TimeDelta(hours=10, minutes=30),
                10,
                "hour",
                hours(10),
                hours(20),
                hours(10),
                hours(10),
                hours(10),
            ),
            # irregular increments are fine for deltas (in contrast to datetimes)
            (
                # an odd increment: 2ns is nearer 0 than 5, so no half-mode expands
                TimeDelta(nanoseconds=2),
                5,
                "nanosecond",
                TimeDelta.ZERO,
                TimeDelta(nanoseconds=5),
                TimeDelta.ZERO,
                TimeDelta.ZERO,
                TimeDelta.ZERO,
            ),
            (
                TimeDelta(nanoseconds=7),
                5,
                "nanosecond",
                TimeDelta(nanoseconds=5),
                TimeDelta(nanoseconds=10),
                TimeDelta(nanoseconds=5),
                TimeDelta(nanoseconds=5),
                TimeDelta(nanoseconds=5),
            ),
            (
                -TimeDelta(nanoseconds=2),
                5,
                "nanosecond",
                -TimeDelta(nanoseconds=5),
                TimeDelta.ZERO,
                TimeDelta.ZERO,
                TimeDelta.ZERO,
                TimeDelta.ZERO,
            ),
            (
                TimeDelta(hours=10, minutes=30),
                23439118,
                "millisecond",
                TimeDelta(hours=6, minutes=30, seconds=39.118),
                TimeDelta(hours=13, minutes=1, seconds=18.236),
                TimeDelta(hours=13, minutes=1, seconds=18.236),
                TimeDelta(hours=13, minutes=1, seconds=18.236),
                TimeDelta(hours=13, minutes=1, seconds=18.236),
            ),
            (
                TimeDelta(hours=321, minutes=30),
                2,
                "day",
                hours(288),
                hours(336),
                hours(336),
                hours(336),
                hours(336),
            ),
            (
                TimeDelta(hours=321, minutes=30),
                1,
                "week",
                hours(168),
                hours(336),
                hours(336),
                hours(336),
                hours(336),
            ),
        ],
    )
    def test_valid(
        self, t, increment, unit, floor, ceil, half_floor, half_ceil, half_even
    ):
        with suppress(DaysAssumed24HoursWarning):
            assert t.round(unit, increment=increment) == half_even
            assert t.round(unit, increment=increment, mode="ceil") == ceil
            assert t.round(unit, increment=increment, mode="expand") == (
                ceil if t > TimeDelta.ZERO else floor
            )
            assert t.round(unit, increment=increment, mode="floor") == floor
            assert t.round(unit, increment=increment, mode="trunc") == (
                floor if t > TimeDelta.ZERO else ceil
            )
            assert (
                t.round(unit, increment=increment, mode="half_floor")
                == half_floor
            )
            assert t.round(unit, increment=increment, mode="half_expand") == (
                half_ceil if t > TimeDelta.ZERO else half_floor
            )
            assert (
                t.round(unit, increment=increment, mode="half_ceil")
                == half_ceil
            )
            assert t.round(unit, increment=increment, mode="half_trunc") == (
                half_floor if t > TimeDelta.ZERO else half_ceil
            )
            assert (
                t.round(unit, increment=increment, mode="half_even")
                == half_even
            )

    def test_increment_read_through_index(self):
        t = TimeDelta(minutes=39, seconds=59)
        assert t.round("minute", increment=True) == t.round("minute")
        assert t.round("minute", increment=cast(int, Idx())) == t.round(
            "minute", increment=5
        )

    def test_increment_beyond_range(self):
        # the widest increment is a 64-bit count of seconds
        t = TimeDelta(hours=1)
        assert t.round("second", increment=2**64 - 1) == TimeDelta.ZERO
        with pytest.raises(
            ValueError, match="^value or calculation out of range$"
        ):
            t.round("second", increment=2**64)

    def test_default_half_even_seconds(self):
        assert TimeDelta(seconds=2, milliseconds=500).round() == TimeDelta(
            seconds=2
        )
        assert TimeDelta(seconds=3, milliseconds=500).round() == TimeDelta(
            seconds=4
        )

    def test_default_increment(self):
        d = TimeDelta(seconds=2, nanoseconds=800)
        assert d.round("microsecond") == TimeDelta(seconds=2, microseconds=1)

    def test_24h_day_warning(self):
        t = TimeDelta.ZERO
        with warns_here(DaysAssumed24HoursWarning):
            t.round("day")

        with warns_here(DaysAssumed24HoursWarning):
            t.round("week")

    def test_timedelta_unit_does_not_warn(self):
        # the named unit claims a calendar; a TimeDelta unit does not
        t = TimeDelta(hours=50)
        with warnings.catch_warnings():
            warnings.simplefilter("error")
            assert t.round(hours(24)) == hours(48)
            assert t.round(TimeDelta(seconds=7)) == TimeDelta(
                hours=49, minutes=59, seconds=58
            )
            assert t.round(
                TimeDelta(seconds=7), days_assumed_24h_ok=True
            ) == TimeDelta(hours=49, minutes=59, seconds=58)

    def test_extremes(self):
        assert TimeDelta.MAX.round(mode="floor") == TimeDelta.MAX
        assert TimeDelta.MIN.round(mode="ceil") == TimeDelta.MIN
        assert TimeDelta.MIN.round(
            "hour", increment=10, mode="ceil"
        ) == TimeDelta.MIN.add(hours=6)

        with pytest.raises(
            ValueError, match="^value or calculation out of range$"
        ):
            TimeDelta.MAX.round("hour", increment=10)
        with pytest.raises(
            ValueError, match="^value or calculation out of range$"
        ):
            TimeDelta.MIN.round("hour", increment=10, mode="floor")

    def test_by_timedelta(self):
        t = TimeDelta(hours=1, minutes=23, seconds=45)
        assert t.round(TimeDelta(minutes=15)) == TimeDelta(hours=1, minutes=30)
        assert t.round(TimeDelta(minutes=15), mode="floor") == TimeDelta(
            hours=1, minutes=15
        )

    def test_by_timedelta_negative_value(self):
        t = -TimeDelta(hours=1, minutes=23, seconds=45)
        assert t.round(TimeDelta(minutes=15)) == -TimeDelta(
            hours=1, minutes=30
        )

    def test_by_timedelta_huge(self):
        t = TimeDelta(nanoseconds=1)
        assert t.round(
            TimeDelta(hours=24 * 9999 * 365, nanoseconds=1), mode="ceil"
        ) == TimeDelta(hours=24 * 9999 * 365, nanoseconds=1)

    def test_by_huge_increment(self):
        t = TimeDelta(nanoseconds=1)
        assert t.round(
            "nanosecond",
            increment=TimeDelta(hours=24 * 9999 * 365, nanoseconds=1).total(
                "nanoseconds"
            ),
            mode="ceil",
        ) == TimeDelta(hours=24 * 9999 * 365, nanoseconds=1)

    def test_by_timedelta_with_mode(self):
        t = TimeDelta(minutes=45)
        assert t.round(hours(1), mode="ceil") == hours(1)
        assert t.round(hours(1), mode="floor") == TimeDelta.ZERO

    @pytest.mark.parametrize(
        "t, unit, kwargs, exc, message",
        [
            *(
                (
                    TimeDelta.ZERO,
                    u,
                    {"increment": i},
                    ValueError,
                    "increment must be a positive integer",
                )
                for u, i in (
                    ("second", -1),
                    ("hour", 0),
                    ("millisecond", -100),
                )
            ),
            *(
                (
                    TimeDelta.ZERO,
                    "second",
                    {"increment": i},
                    TypeError,
                    "increment must be an integer",
                )
                for i in (1.5, float("nan"), "5", Fraction(3, 2))
            ),
            *(
                (TimeDelta.ZERO, u, {}, ValueError, f"invalid unit: {u!r}")
                for u in ("foo", "minutes", None, 5)
            ),
            # a value already on the increment validates the mode too
            *(
                (t, "hour", {"mode": m}, ValueError, f"invalid mode: {m!r}")
                for t in (
                    TimeDelta(hours=12, nanoseconds=4),
                    TimeDelta(hours=12),
                )
                for m in ("foo", "TRUNC", None, 3)
            ),
            *(
                (
                    TimeDelta(hours=1, minutes=23, seconds=45),
                    u,
                    {},
                    ValueError,
                    "unit must be a positive TimeDelta",
                )
                for u in (-TimeDelta(minutes=15), TimeDelta.ZERO)
            ),
            *(
                (
                    hours(1),
                    TimeDelta(minutes=15),
                    {"increment": i},
                    TypeError,
                    "cannot specify an increment with a TimeDelta argument",
                )
                for i in (1, 2)
            ),
        ],
    )
    def test_rejected(self, t, unit, kwargs, exc, message):
        with pytest.raises(exc, match="^" + re.escape(message) + "$"):
            t.round(unit, **kwargs)


class TestTotal:
    @pytest.mark.parametrize(
        "unit", ["hours", "nanoseconds", "days", "months"]
    )
    @pytest.mark.parametrize(
        "relative_to", [None, "2020-01-01", 3, Instant.from_timestamp(0)]
    )
    def test_relative_to_checked_for_every_unit(self, unit, relative_to):
        with pytest.raises(
            TypeError,
            match="relative_to must be a ZonedDateTime, PlainDateTime, or OffsetDateTime",
        ):
            hours(1).total(unit, relative_to=relative_to)

    def test_exact_units(self):
        d = TimeDelta(hours=1, minutes=2, seconds=0.003, nanoseconds=4)
        assert d.total("nanoseconds") == approx(
            3_600_000_000_000 + 2 * 60_000_000_000 + 3_000_000 + 4
        )
        assert d.total("microseconds") == approx(
            3_600_000_000 + 2 * 60_000_000 + 3 * 1_000 + 0.004
        )
        assert d.total("milliseconds") == approx(
            d.total("microseconds") / 1_000
        )
        assert d.total("seconds") == approx(d.total("milliseconds") / 1_000)
        assert d.total("minutes") == approx(d.total("seconds") / 60)
        assert d.total("hours") == approx(d.total("minutes") / 60)

        # relative_to parameter has no effect. Exact units aren't affected by DST.
        assert d.total(
            "seconds",
            relative_to=ZonedDateTime(
                2023,
                3,
                26,
                hour=2,
                tz="Europe/Paris",
                disambiguation="compatible",
            ),
        ) == d.total("seconds")

    def test_days_and_weeks(self):
        d = TimeDelta(hours=1, minutes=2, seconds=0.003, nanoseconds=4)

        with warns_here(DaysAssumed24HoursWarning):
            assert d.total("days") == approx(d.total("hours") / 24)

        # Silencing the warnings
        with suppress(DaysAssumed24HoursWarning):
            assert d.total("days")

        # relative to a regular date
        assert d.total(
            "days",
            relative_to=ZonedDateTime(2023, 7, 1, hour=14, tz="Europe/Paris"),
        ) == approx(d.total("hours") / 24)
        # negative
        assert (-d).total(
            "days",
            relative_to=ZonedDateTime(2023, 7, 1, hour=14, tz="Europe/Paris"),
        ) == approx(-d.total("hours") / 24)

        # relative to skipped time, round down
        assert hours(30).total(
            "days",
            relative_to=ZonedDateTime(2023, 3, 25, hour=10, tz="Europe/Paris"),
        ) == approx(1.2916666666666667)
        # relative to skipped time, round up
        assert TimeDelta(hours=48 + 18).total(
            "days",
            relative_to=ZonedDateTime(2023, 3, 24, hour=10, tz="Europe/Paris"),
        ) == approx(2.7916666666666665)
        # negative, round down
        assert hours(-30).total(
            "days",
            relative_to=ZonedDateTime(2023, 3, 27, hour=10, tz="Europe/Paris"),
        ) == approx(-1.2608695652173914)
        # negative, round up
        assert TimeDelta(hours=-24 - 18).total(
            "days",
            relative_to=ZonedDateTime(
                2023, 3, 27, hour=11, minute=34, tz="Europe/Paris"
            ),
        ) == approx(-1.7826086956521738)
        # exactly 2 days
        assert hours(47).total(
            "days",
            relative_to=ZonedDateTime(2023, 3, 25, hour=10, tz="Europe/Paris"),
        ) == approx(2.0)
        # example -5 days
        assert TimeDelta(hours=-5 * 24 + 1).total(
            "days",
            relative_to=ZonedDateTime(2023, 3, 28, hour=10, tz="Europe/Paris"),
        ) == approx(-5.0)

    def test_weeks(self):
        d = hours(2000)

        with warns_here(DaysAssumed24HoursWarning):
            assert d.total("weeks") == approx(d.total("hours") / (24 * 7))

        # Silencing the warnings
        with suppress(DaysAssumed24HoursWarning):
            assert d.total("weeks")

        # non DST date
        assert hours(1000).total(
            "weeks",
            relative_to=ZonedDateTime(
                2023, 11, 29, hour=22, tz="Europe/Paris"
            ),
        ) == approx(1000 / (24 * 7))

        # relative to DST date, round up
        assert hours(3358).total(
            "weeks",
            relative_to=ZonedDateTime(
                2023, 12, 29, hour=22, tz="America/Anchorage"
            ),
        ) == approx(19.99404761904762)
        # relative to DST date, round down
        assert hours(3360).total(
            "weeks",
            relative_to=ZonedDateTime(
                2023, 12, 29, hour=22, tz="America/Anchorage"
            ),
        ) == approx(20.00595238095238)
        # negative, round down
        assert hours(-5881).total(
            "weeks",
            relative_to=ZonedDateTime(
                2023, 7, 22, hour=0, tz="America/Anchorage"
            ),
        ) == approx(-35.01190476190476)
        # # negative, round up
        assert hours(-5871).total(
            "weeks",
            relative_to=ZonedDateTime(
                2023, 7, 22, hour=0, tz="America/Anchorage"
            ),
        ) == approx(-34.95238095238095)

    def test_months_and_years(self):
        d = hours(2000)

        with pytest.raises(
            TypeError, match="^relative_to is required for years and months$"
        ):
            d.total("months")  # type: ignore[call-overload]

        # positive cases
        assert hours(3360).total(
            "months",
            relative_to=ZonedDateTime(
                2024, 2, 29, hour=12, minute=1, tz="Europe/Athens"
            ),
        ) == approx(4.634722222222222)
        assert hours(360).total(
            "months",
            relative_to=ZonedDateTime(
                2024, 3, 23, hour=12, minute=1, tz="Europe/Athens"
            ),
        ) == approx(0.4845222072678331)

        # negative cases
        assert hours(-5871).total(
            "months",
            relative_to=ZonedDateTime(2023, 1, 31, hour=1, tz="Europe/Athens"),
        ) == approx(-7.986111111111111)
        assert hours(-5910).total(
            "months",
            relative_to=ZonedDateTime(2023, 1, 31, hour=1, tz="Europe/Athens"),
        ) == approx(-8.038978494623656)

        with pytest.raises(
            TypeError, match="^relative_to is required for years and months$"
        ):
            d.total("years")  # type: ignore[call-overload]

        # positive cases
        assert hours(14360).total(
            "years",
            relative_to=ZonedDateTime(
                2024, 3, 23, hour=12, minute=1, tz="Europe/Athens"
            ),
        ) == approx(1.639269406392694)
        assert hours(88360).total(
            "years",
            relative_to=ZonedDateTime(
                2024, 3, 23, hour=12, minute=1, tz="Europe/Athens"
            ),
        ) == approx(10.081278538812786)

        # negative cases
        assert hours(-43421).total(
            "years",
            relative_to=ZonedDateTime(
                2024, 11, 3, hour=12, tz="Europe/Athens"
            ),
        ) == approx(-4.951388888888889)
        assert hours(-57421).total(
            "years",
            relative_to=ZonedDateTime(
                2024, 11, 3, hour=12, tz="Europe/Athens"
            ),
        ) == approx(-6.549429223744292)

    def test_zero(self):
        d = TimeDelta()
        ref = ZonedDateTime(2023, 3, 26, hour=4, tz="Europe/Paris")
        assert d.total("nanoseconds") == 0
        assert d.total("microseconds") == 0
        assert d.total("milliseconds") == 0
        assert d.total("seconds") == 0
        assert d.total("minutes") == 0
        assert d.total("hours") == 0
        assert d.total("days", relative_to=ref) == 0
        assert d.total("weeks", relative_to=ref) == 0
        assert d.total("months", relative_to=ref) == 0
        assert d.total("years", relative_to=ref) == 0

    def test_skipped_day_in_samoa(self):
        zdt = ZonedDateTime(
            "2011-12-29T12-10:00[Pacific/Apia]"
        )  # just before a day skip
        assert hours(48).total("days", relative_to=zdt) == approx(3.0)
        assert hours(24).total("days", relative_to=zdt) == approx(2.0)
        assert hours(47).total("days", relative_to=zdt) == approx(
            (3 * 24 - 1) / 24
        )
        assert hours(49).total("days", relative_to=zdt) == approx(
            (3 * 24 + 1) / 24
        )

        zdt = ZonedDateTime(
            "2011-12-31T12+14:00[Pacific/Apia]"
        )  # just after day skip
        assert hours(-48).total("days", relative_to=zdt) == approx(-3.0)
        assert hours(-47).total("days", relative_to=zdt) == approx(
            -(3 * 24 - 1) / 24
        )
        assert hours(-49).total("days", relative_to=zdt) == approx(
            -(3 * 24 + 1) / 24
        )
        assert hours(-24).total("days", relative_to=zdt) == approx(-2.0)

    def test_skipped_day_in_samoa_two_iterations(self):
        # With time component 23:00, replace_date(Dec 30) == replace_date(Dec 31)
        # because Dec 30 is entirely skipped. A single if-check is insufficient—
        # two while-loop iterations are needed to arrive at Dec 29.
        zdt = ZonedDateTime(2011, 12, 28, 23, tz="Pacific/Apia")
        assert hours(25).total("days", relative_to=zdt) == approx(25 / 24)

    def test_repeated_time(self):
        before = ZonedDateTime("2016-02-20T23:33:00-02:00[America/Sao_Paulo]")
        after = ZonedDateTime("2016-02-20T23:29:00-03:00[America/Sao_Paulo]")
        assert after > before

        assert TimeDelta(minutes=45).total(
            "days", relative_to=before
        ) == approx(0.75 / 25)
        assert TimeDelta(minutes=60).total(
            "days", relative_to=before
        ) == approx(1 / 25)
        assert TimeDelta(minutes=60).total("hours", relative_to=before) == 1.0

        assert TimeDelta(minutes=-30).total(
            "days", relative_to=after
        ) == approx(-0.5 / 25)

        before = ZonedDateTime("2023-10-29T02:15:00+02:00[Europe/Amsterdam]")
        assert TimeDelta(minutes=45).total(
            "days", relative_to=before
        ) == approx(0.75 / 25)
        assert TimeDelta(minutes=60).total(
            "days", relative_to=before
        ) == approx(1 / 25)
        assert TimeDelta(minutes=60).total("hours", relative_to=before) == 1.0

    def test_invalid_unit(self):
        d = hours(1)
        with pytest.raises(ValueError, match="invalid unit: 'foobars'"):
            d.total("foobars")  # type: ignore[call-overload]

        with pytest.raises(ValueError, match="invalid unit"):
            d.total("")  # type: ignore[call-overload]

    def test_range_error(self):
        d = TimeDelta(hours=78_840_000)
        with pytest.raises(
            ValueError, match="value or calculation out of range"
        ):
            d.total(
                "days",
                relative_to=ZonedDateTime(3000, 1, 1, hour=0, tz="UTC"),
            )

        d = TimeDelta(hours=-48_840_000)
        with pytest.raises(
            ValueError, match="value or calculation out of range"
        ):
            d.total(
                "days",
                relative_to=ZonedDateTime(3000, 1, 1, hour=0, tz="UTC"),
            )

    def test_nanoseconds_are_int(self):
        d = TimeDelta(hours=1, minutes=2, seconds=3, microseconds=4)
        assert isinstance(d.total("nanoseconds"), int)

    def test_subsecond_totals_are_float(self):
        d = seconds(1)
        assert d.total("milliseconds") == 1_000.0
        assert isinstance(d.total("milliseconds"), float)
        assert d.total("microseconds") == 1_000_000.0
        assert isinstance(d.total("microseconds"), float)

    def test_relative_to_plain_datetime(self):
        td = hours(360)  # 15 days
        pdt = PlainDateTime(2023, 3, 1, 2)
        with warns_here(NaiveArithmeticWarning):
            result = td.total("months", relative_to=pdt)
        assert result == approx(15 / 31)

        # suppression works
        with suppress(NaiveArithmeticWarning):
            result_sup = td.total("months", relative_to=pdt)
        assert result_sup == approx(15 / 31)

        # years
        td_yr = TimeDelta(hours=24 * 365)  # 365 days
        pdt_yr = PlainDateTime(2023, 1, 1)
        with suppress(NaiveArithmeticWarning):
            result_yr = td_yr.total("years", relative_to=pdt_yr)
        assert result_yr == approx(1.0)

        # negative delta: reference March 16 → shifted March 1
        # backward: March 16 → Feb 16 = 28 days (Feb 2023)
        td_neg = hours(-360)
        pdt_neg = PlainDateTime(2023, 3, 16, 2)
        with suppress(NaiveArithmeticWarning):
            result_neg = td_neg.total("months", relative_to=pdt_neg)
        assert result_neg == approx(-15 / 28)

    def test_relative_to_offset_datetime(self):
        # TimeDelta.total() with relative_to=OffsetDateTime:
        # the *local* datetime (offset stripped) is used as the calendar anchor.
        td = hours(360)  # 15 days
        odt = OffsetDateTime(2023, 3, 1, 2, offset=hours(5))
        with warns_here(StaleOffsetWarning):
            result = td.total("months", relative_to=odt)
        # same reference date as PlainDateTime(2023, 3, 1, 2)
        assert result == approx(15 / 31)

        # suppression works
        with suppress(StaleOffsetWarning):
            result_sup = td.total("months", relative_to=odt)
        assert result_sup == approx(15 / 31)

    def test_relative_to_odt_uses_local_not_utc(self):
        td = hours(360)  # 15 days
        odt = OffsetDateTime(2023, 3, 1, 2, offset=hours(5))
        with suppress(StaleOffsetWarning):
            result_correct = td.total("months", relative_to=odt)
        assert result_correct == approx(15 / 31)  # March anchor

    def test_relative_to_invalid_type(self):
        d = hours(1)
        with pytest.raises(TypeError):
            d.total("months", relative_to=42)  # type: ignore[call-overload]


class TestInUnits:
    @pytest.mark.parametrize("mode, up, down", ROUND_MODES_AT_A_TIE)
    def test_every_round_mode_at_a_tie(self, mode, up, down):
        delta = TimeDelta(hours=2, minutes=30)
        assert delta.in_units(["hours"], round_mode=mode) == ItemizedDelta(
            hours=up
        )
        assert (-delta).in_units(["hours"], round_mode=mode) == ItemizedDelta(
            hours=down
        )

    @pytest.mark.parametrize(
        "delta, units, increment, trunc, ceil",
        [
            (
                TimeDelta(minutes=5, seconds=20),
                ["minutes", "seconds"],
                61,
                ItemizedDelta(minutes=5, seconds=0),
                ItemizedDelta(minutes=6, seconds=0),
            ),
            (
                TimeDelta(hours=5, minutes=20),
                ["hours", "minutes"],
                90,
                ItemizedDelta(hours=5, minutes=0),
                ItemizedDelta(hours=6, minutes=0),
            ),
            # an increment equal to the next unit
            (
                TimeDelta(hours=5, minutes=20),
                ["hours", "minutes"],
                60,
                ItemizedDelta(hours=5, minutes=0),
                ItemizedDelta(hours=6, minutes=0),
            ),
            # rounding up carries into every larger unit at once
            (
                TimeDelta(hours=47, minutes=59),
                ["days", "hours", "minutes"],
                15,
                ItemizedDelta(days=1, hours=23, minutes=45),
                ItemizedDelta(days=2, hours=0, minutes=0),
            ),
            # the next requested unit need not be adjacent
            (
                TimeDelta(hours=2, minutes=59, seconds=59),
                ["hours", "seconds"],
                7,
                ItemizedDelta(hours=2, seconds=3598),
                ItemizedDelta(hours=3, seconds=0),
            ),
            # a single unit rounds its total
            (
                TimeDelta(hours=5, minutes=20),
                ["minutes"],
                90,
                ItemizedDelta(minutes=270),
                ItemizedDelta(minutes=360),
            ),
        ],
    )
    def test_smallest_component_is_the_multiple(
        self, delta, units, increment, trunc, ceil
    ):
        kwargs: dict[str, Any] = dict(
            round_increment=increment, days_assumed_24h_ok=True
        )
        assert delta.in_units(units, round_mode="trunc", **kwargs) == trunc
        assert delta.in_units(units, round_mode="ceil", **kwargs) == ceil
        assert (-delta).in_units(units, round_mode="trunc", **kwargs) == -trunc
        assert (-delta).in_units(units, round_mode="floor", **kwargs) == -ceil

    # Where the increment divides the next unit, a tie goes to the even
    # multiple of the total, not of the component
    @pytest.mark.parametrize(
        "delta, units, increment, expected",
        [
            (
                TimeDelta(hours=252),  # 10 days and 12 hours
                ["weeks", "days"],
                1,
                ItemizedDelta(weeks=1, days=3),
            ),
            (
                TimeDelta(minutes=1, seconds=10),
                ["minutes", "seconds"],
                20,
                ItemizedDelta(minutes=1, seconds=20),
            ),
            (
                TimeDelta(hours=1, minutes=30),
                ["hours", "minutes"],
                60,
                ItemizedDelta(hours=2, minutes=0),
            ),
            (
                TimeDelta(hours=1, minutes=2, seconds=30),
                ["hours", "minutes"],
                1,
                ItemizedDelta(hours=1, minutes=2),
            ),
        ],
    )
    def test_half_even_ties_to_an_even_total(
        self, delta, units, increment, expected
    ):
        kwargs: dict[str, Any] = dict(
            round_mode="half_even",
            round_increment=increment,
            days_assumed_24h_ok=True,
        )
        assert delta.in_units(units, **kwargs) == expected
        assert (-delta).in_units(units, **kwargs) == -expected

    @pytest.mark.parametrize(
        "delta, units, kwargs, expected",
        [
            # ---
            # Basic cases
            # ---
            (
                TimeDelta(minutes=90),
                ("hours", "minutes", "seconds"),
                {},
                ItemizedDelta(hours=1, minutes=30, seconds=0),
            ),
            (
                TimeDelta(),
                ("minutes", "seconds"),
                {},
                ItemizedDelta(minutes=0, seconds=0),
            ),
            (
                TimeDelta(hours=3, minutes=1),
                ("minutes", "seconds"),
                {},
                ItemizedDelta(minutes=181, seconds=0),
            ),
            (
                TimeDelta(
                    hours=-1, minutes=-30, seconds=-15, microseconds=-500
                ),
                ("minutes", "seconds", "nanoseconds"),
                {},
                ItemizedDelta(minutes=-90, seconds=-15, nanoseconds=-500_000),
            ),
            # list instead of tuple argument
            (
                TimeDelta(nanoseconds=1),
                ["seconds", "nanoseconds"],
                {},
                ItemizedDelta(seconds=0, nanoseconds=1),
            ),
            # ---
            # Rounding
            # ---
            (
                TimeDelta(hours=2, minutes=30),
                ("hours",),
                {},
                ItemizedDelta(hours=2),
            ),
            (
                TimeDelta(hours=2, minutes=51, seconds=30),
                ("hours", "minutes"),
                {},
                ItemizedDelta(hours=2, minutes=51),
            ),
            (
                TimeDelta(seconds=90),
                ("minutes",),
                {"round_mode": "half_even"},
                ItemizedDelta(minutes=2),
            ),
            (
                TimeDelta(seconds=150),
                ("minutes",),
                {"round_mode": "half_even"},
                ItemizedDelta(minutes=2),
            ),
            (
                TimeDelta(seconds=-150),
                ("minutes",),
                {"round_mode": "half_even"},
                ItemizedDelta(minutes=-2),
            ),
            (
                TimeDelta(hours=2, minutes=51, seconds=30),
                ("hours", "minutes"),
                {"round_mode": "floor"},
                ItemizedDelta(hours=2, minutes=51),
            ),
            (
                TimeDelta(hours=2, minutes=50, seconds=30),
                ("hours", "minutes"),
                {"round_mode": "half_ceil"},
                ItemizedDelta(hours=2, minutes=51),
            ),
            (
                TimeDelta(hours=2, minutes=50, seconds=30),
                ("hours", "minutes"),
                {"round_mode": "half_expand"},
                ItemizedDelta(hours=2, minutes=51),
            ),
            (
                TimeDelta(hours=2, minutes=50, seconds=30),
                ("hours", "minutes"),
                {"round_mode": "half_floor"},
                ItemizedDelta(hours=2, minutes=50),
            ),
            (
                TimeDelta(hours=2, minutes=50, seconds=30),
                ("hours", "minutes"),
                {"round_mode": "half_trunc"},
                ItemizedDelta(hours=2, minutes=50),
            ),
            (
                TimeDelta(hours=2, minutes=50, seconds=1),
                ("hours", "minutes"),
                {"round_mode": "ceil"},
                ItemizedDelta(hours=2, minutes=51),
            ),
            (
                hours(2),
                ("hours",),
                {"round_mode": "ceil"},
                ItemizedDelta(hours=2),
            ),
            (
                TimeDelta(seconds=1),
                ("hours", "minutes"),
                {"round_mode": "floor"},
                ItemizedDelta(hours=0, minutes=0),
            ),
            (
                TimeDelta(seconds=-1),
                ("hours", "minutes"),
                {"round_mode": "floor"},
                ItemizedDelta(hours=0, minutes=-1),
            ),
            # ---
            # larger units
            # ---
            (
                TimeDelta(hours=49, minutes=121),
                ("days", "hours"),
                {},
                ItemizedDelta(days=2, hours=3),
            ),
            (
                TimeDelta(hours=49, minutes=121),
                ("days", "hours"),
                {"round_mode": "ceil"},
                ItemizedDelta(days=2, hours=4),
            ),
            (
                TimeDelta(hours=49, minutes=121),
                ("days", "hours"),
                {"round_mode": "expand"},
                ItemizedDelta(days=2, hours=4),
            ),
            (
                TimeDelta(hours=49, minutes=121),
                ("days", "hours"),
                {"round_mode": "trunc"},
                ItemizedDelta(days=2, hours=3),
            ),
            (
                TimeDelta(hours=49, minutes=121),
                ("days", "hours"),
                {"round_mode": "floor"},
                ItemizedDelta(days=2, hours=3),
            ),
            (
                TimeDelta(hours=-50 * 24, minutes=-121),
                ("weeks", "hours"),
                {},
                ItemizedDelta(weeks=-7, hours=-26),
            ),
            (
                TimeDelta(hours=-50 * 24, minutes=-121),
                ("weeks", "hours"),
                {"round_mode": "ceil"},
                ItemizedDelta(weeks=-7, hours=-26),
            ),
            (
                TimeDelta(hours=-50 * 24, minutes=-121),
                ("weeks", "hours"),
                {"round_mode": "trunc"},
                ItemizedDelta(weeks=-7, hours=-26),
            ),
            (
                TimeDelta(hours=-50 * 24, minutes=-121),
                ("weeks", "hours"),
                {"round_mode": "expand"},
                ItemizedDelta(weeks=-7, hours=-27),
            ),
            (
                TimeDelta(hours=-50 * 24, minutes=-121),
                ("weeks", "hours"),
                {"round_mode": "floor"},
                ItemizedDelta(weeks=-7, hours=-27),
            ),
            (
                TimeDelta(hours=-50 * 24, minutes=-121),
                ("weeks",),
                {"round_mode": "floor"},
                ItemizedDelta(weeks=-8),
            ),
            (
                TimeDelta(hours=-50 * 24, minutes=-121),
                ("days",),
                {},
                ItemizedDelta(days=-50),
            ),
            (
                TimeDelta(hours=-5000 * 24, minutes=-121),
                ("days",),
                {},
                ItemizedDelta(days=-5000),
            ),
            # Strange set of units and increment, but should work
            (
                TimeDelta(hours=49, minutes=121),
                ("days", "seconds", "nanoseconds"),
                {"round_increment": 826549200},
                ItemizedDelta(days=2, seconds=10860, nanoseconds=0),
            ),
            # TEST round single units with large values
        ],
    )
    @suppress(DaysAssumed24HoursWarning)
    def test_valid(self, delta, units, kwargs, expected):
        assert delta.in_units(units, **kwargs) == expected

    def test_invalid_unit(self):
        d = hours(1)
        with pytest.raises(ValueError, match="invalid unit"):
            d.in_units(["foo"])  # type: ignore[list-item]

        with pytest.raises(ValueError, match="invalid unit"):
            d.in_units(["foos"])  # type: ignore[list-item]

        with pytest.raises(ValueError, match="invalid unit"):
            d.in_units([""])  # type: ignore[list-item]

        # DOC: make this error clearer
        with pytest.raises(ValueError, match="invalid unit"):
            d.in_units(["milliseconds"])  # type: ignore[list-item]

    def test_missing_units(self):
        d = hours(1)
        with pytest.raises(ValueError, match="^in_units must not be empty$"):
            d.in_units([])

    def test_units_out_of_order(self):
        d = hours(1)
        with pytest.raises(ValueError, match="decreasing order of size"):
            d.in_units(["seconds", "hours"])

    def test_units_repeated(self):
        d = hours(1)
        # DOC: clarify error message
        with pytest.raises(ValueError, match="cannot contain duplicates"):
            d.in_units(["hours", "hours", "minutes"])

    def test_nanoseconds_but_no_seconds(self):
        d = hours(1)
        with pytest.raises(
            ValueError,
            match="^nanoseconds can only be specified together with seconds$",
        ):
            d.in_units(["hours", "nanoseconds"])

    def test_invalid_round_mode(self):
        d = hours(1)
        with pytest.raises(ValueError, match="^invalid round_mode: 'foo'$"):
            d.in_units(["hours"], round_mode="foo")  # type: ignore[call-overload]

    def test_24h_days_warning(self):
        d = hours(49)
        with warns_here(DaysAssumed24HoursWarning):
            d.in_units(["days", "hours"])

        with warns_here(DaysAssumed24HoursWarning):
            d.in_units(["weeks", "hours"])

        # test warnings suppression
        with suppress(DaysAssumed24HoursWarning):
            d.in_units(["days"])

    def test_non_sequence_units(self):
        d = hours(1)
        with pytest.raises(TypeError, match="sequence"):
            d.in_units("hours")  # type: ignore[arg-type]
        with pytest.raises(TypeError, match="sequence"):
            d.in_units({"hours"})  # type: ignore[call-overload]

    def test_calendar_units_require_relative_to(self):
        d = hours(2000)
        with pytest.raises(
            TypeError, match="^relative_to is required for years and months$"
        ):
            d.in_units(["years", "months"])  # type: ignore[list-item]

    def test_calendar_units_with_relative_to(self):
        d = hours(3360)
        ref = ZonedDateTime(2024, 2, 29, hour=12, minute=1, tz="Europe/Athens")
        result = d.in_units(["months", "days"], relative_to=ref)
        # 3360 h = 140 days. From 2024-02-29, ~4 months 20 days.
        assert isinstance(result, ItemizedDelta)
        assert result["months"] == 4

    def test_carry_past_the_range(self):
        with pytest.raises(
            ValueError, match="^value or calculation out of range$"
        ):
            # MAX is 522804 weeks and 6 days; the days round up to 8
            TimeDelta.MAX.in_units(
                ["weeks", "days"],
                round_increment=4,
                round_mode="ceil",
                days_assumed_24h_ok=True,
            )

    def test_very_large_increment(self):
        # round_increment=1<<65 ns exceeds i64::MAX; should not OverflowError
        with suppress(DaysAssumed24HoursWarning):
            d = TimeDelta(days=592, nanoseconds=1)
        # trunc mode: the nanoseconds component rounds down to zero
        assert d.in_units(
            ["seconds", "nanoseconds"],
            round_increment=1 << 65,
            round_mode="trunc",
        ) == ItemizedDelta(seconds=51_148_800, nanoseconds=0)
        # ceil mode: 1<<65 ns (36_893_488_147.419103232s) carries into the
        # seconds, and the nanoseconds stay a multiple of the increment
        assert d.in_units(
            ["seconds", "nanoseconds"],
            round_increment=1 << 65,
            round_mode="ceil",
        ) == ItemizedDelta(seconds=36_944_636_947, nanoseconds=0)

    def test_relative_to_plain_datetime(self):
        # 140 days from 2024-02-29 = 4 months + 20 days
        d = hours(3360)
        ref = PlainDateTime(2024, 2, 29, 12, 1)
        with warns_here(NaiveArithmeticWarning):
            result = d.in_units(["months", "days"], relative_to=ref)
        assert result["months"] == 4

    def test_relative_to_offset_datetime(self):
        # Same arithmetic as plain, but uses OffsetDateTime
        d = hours(3360)
        ref = OffsetDateTime(2024, 2, 29, 12, 1, offset=hours(2))
        with warns_here(StaleOffsetWarning):
            result = d.in_units(["months", "days"], relative_to=ref)
        assert result["months"] == 4

    def test_relative_to_plain_no_warning_for_exact_units(self):
        # Exact-only units: no warning since relative_to doesn't affect result
        d = TimeDelta(hours=5, minutes=30)
        ref = PlainDateTime(2024, 1, 1)
        result = d.in_units(["hours", "minutes"], relative_to=ref)
        assert result == ItemizedDelta(hours=5, minutes=30)

    def test_relative_to_offset_no_warning_for_exact_units(self):
        # Exact-only units: no warning since relative_to doesn't affect result
        d = TimeDelta(hours=5, minutes=30)
        ref = OffsetDateTime(2024, 1, 1, offset=hours(3))
        result = d.in_units(["hours", "minutes"], relative_to=ref)
        assert result == ItemizedDelta(hours=5, minutes=30)

    def test_warns_once_for_weeks(self):
        with warns_here(DaysAssumed24HoursWarning) as caught:
            TimeDelta(hours=30).in_units(["weeks", "hours"])
        assert len(caught) == 1


_H: Any = hours(1)


class TestMessages:
    """One template per condition, identical on both backends."""

    @pytest.mark.parametrize(
        "call, error, message",
        [
            (
                lambda: _H.in_units([]),
                ValueError,
                "in_units must not be empty",
            ),
            (
                lambda: _H.total("months"),
                TypeError,
                "relative_to is required for years and months",
            ),
            (
                lambda: _H.in_units(["years", "days"]),
                TypeError,
                "relative_to is required for years and months",
            ),
            (lambda: _H.total("foo"), ValueError, "invalid unit: 'foo'"),
            (
                lambda: _H.in_units(["foo"]),
                ValueError,
                "invalid unit: 'foo'",
            ),
            (
                lambda: _H.in_units(["hours", "nanoseconds"]),
                ValueError,
                "nanoseconds can only be specified together with seconds",
            ),
            (
                lambda: _H.in_units(["hours"], round_mode="foo"),
                ValueError,
                "invalid round_mode: 'foo'",
            ),
            (
                lambda: _H.in_units(["hours"], round_increment=1.5),
                TypeError,
                "round_increment must be an integer",
            ),
            (
                lambda: _H.in_units(["hours"], round_increment=0),
                ValueError,
                "round_increment must be a positive integer in range",
            ),
            (
                lambda: _H.in_units(["hours"], round_increment=-2),
                ValueError,
                "round_increment must be a positive integer in range",
            ),
            (lambda: _H / 0, ZeroDivisionError, "division by zero"),
            (
                lambda: _H // TimeDelta.ZERO,
                ZeroDivisionError,
                "division by zero",
            ),
            (
                lambda: _H % TimeDelta.ZERO,
                ZeroDivisionError,
                "division by zero",
            ),
            (
                lambda: _H.add(1),
                TypeError,
                "add() argument must be a TimeDelta",
            ),
            (
                lambda: _H.subtract(1),
                TypeError,
                "subtract() argument must be a TimeDelta",
            ),
            (
                lambda: _H.add(foo=1),
                TypeError,
                "add() got an unexpected keyword argument 'foo'",
            ),
            (
                lambda: _H.subtract(foo=1),
                TypeError,
                "subtract() got an unexpected keyword argument 'foo'",
            ),
            (
                lambda: _H.add(_H, hours=1),
                TypeError,
                "add() cannot mix positional and keyword arguments",
            ),
            (
                lambda: _H.subtract(_H, hours=1),
                TypeError,
                "subtract() cannot mix positional and keyword arguments",
            ),
            (
                lambda: _H.total(
                    "days", relative_to=ZonedDateTime(9999, 12, 31, tz="UTC")
                ),
                ValueError,
                RANGE_MSG,
            ),
            (
                lambda: _H.in_units(
                    ["days", "hours"],
                    relative_to=ZonedDateTime(9999, 12, 31, 23, tz="UTC"),
                ),
                ValueError,
                RANGE_MSG,
            ),
        ],
    )
    def test_messages(self, call, error, message):
        with pytest.raises(error, match=f"^{re.escape(message)}$"):
            call()

    def test_units_is_any_iterable(self):
        d: Any = TimeDelta(hours=1, minutes=30)
        assert d.in_units(iter(["hours", "minutes"])) == ItemizedDelta(
            hours=1, minutes=30
        )
        assert d.in_units({"hours": 0, "minutes": 0}) == ItemizedDelta(
            hours=1, minutes=30
        )
        with pytest.raises(TypeError):
            d.in_units(None)

    def test_raising_calls_do_not_warn(self):
        with warnings.catch_warnings(record=True) as record:
            warnings.simplefilter("always")
            with pytest.raises(ValueError, match=RANGE_MSG):
                _H.add(weeks=float("inf"))
            with pytest.raises(TypeError):
                _H.in_units(["years", "days"])
            with pytest.raises(TypeError):
                _H.add(days=1, foo=2)
            with pytest.raises(
                ValueError, match="increment must be a positive integer"
            ):
                _H.round("day", increment=0)
            with pytest.raises(TypeError):
                _H.round("day", increment=1.5)
            with pytest.raises(ValueError, match="invalid mode"):
                _H.round("day", mode="bogus")
            with pytest.raises(TypeError):
                _H.round(TimeDelta(seconds=7), increment=2)
        assert record == []


class TestReferenceEscapes:
    """Each escape suppresses exactly its own warning; a ``ZonedDateTime``
    reference ignores both."""

    def test_total_plain(self):
        td = hours(360)
        pdt = PlainDateTime(2023, 3, 1, 2)
        with warnings.catch_warnings():
            warnings.simplefilter("error")
            result = td.total(
                "months", relative_to=pdt, naive_arithmetic_ok=True
            )
        assert result == approx(15 / 31)
        with warns_here(NaiveArithmeticWarning):
            td.total("months", relative_to=pdt, stale_offset_ok=True)  # type: ignore[call-overload]

    def test_total_offset(self):
        td = hours(360)
        odt = OffsetDateTime(2023, 3, 1, 2, offset=hours(5))
        with warnings.catch_warnings():
            warnings.simplefilter("error")
            result = td.total("months", relative_to=odt, stale_offset_ok=True)
        assert result == approx(15 / 31)
        with warns_here(StaleOffsetWarning):
            td.total("months", relative_to=odt, naive_arithmetic_ok=True)  # type: ignore[call-overload]

    def test_in_units_plain(self):
        td = hours(49)
        pdt = PlainDateTime(2023, 3, 1)
        with warnings.catch_warnings():
            warnings.simplefilter("error")
            result = td.in_units(
                ["days", "hours"], relative_to=pdt, naive_arithmetic_ok=True
            )
        assert result == ItemizedDelta(days=2, hours=1)
        with warns_here(NaiveArithmeticWarning):
            td.in_units(
                ["days", "hours"], relative_to=pdt, stale_offset_ok=True
            )  # type: ignore[call-overload]

    def test_in_units_offset(self):
        td = hours(49)
        odt = OffsetDateTime(2023, 3, 1, offset=hours(5))
        with warnings.catch_warnings():
            warnings.simplefilter("error")
            result = td.in_units(
                ["days", "hours"], relative_to=odt, stale_offset_ok=True
            )
        assert result == ItemizedDelta(days=2, hours=1)
        with warns_here(StaleOffsetWarning):
            td.in_units(
                ["days", "hours"], relative_to=odt, naive_arithmetic_ok=True
            )  # type: ignore[call-overload]

    def test_ignored_with_zoned(self):
        td = hours(49)
        zdt = ZonedDateTime(2023, 3, 1, tz="Europe/Amsterdam")
        with warnings.catch_warnings():
            warnings.simplefilter("error")
            assert td.total(
                "days",
                relative_to=zdt,
                naive_arithmetic_ok=True,  # type: ignore[call-overload]
                stale_offset_ok=True,
            ) == approx(49 / 24)
            assert td.in_units(
                ["days", "hours"],
                relative_to=zdt,
                naive_arithmetic_ok=True,  # type: ignore[call-overload]
                stale_offset_ok=True,
            ) == ItemizedDelta(days=2, hours=1)

    def test_escapes_read_by_truthiness(self):
        td = hours(360)
        pdt = PlainDateTime(2023, 3, 1, 2)
        with warnings.catch_warnings():
            warnings.simplefilter("error")
            td.total("months", relative_to=pdt, naive_arithmetic_ok=1)  # type: ignore[call-overload]
        with warns_here(NaiveArithmeticWarning):
            td.total("months", relative_to=pdt, naive_arithmetic_ok="")  # type: ignore[call-overload]


class TestAssume24hDaysKwarg:
    @pytest.mark.parametrize(
        "call",
        [
            lambda: TimeDelta(days=0),
            lambda: TimeDelta(weeks=0, hours=1),
            lambda: TimeDelta(days=0.0),
            lambda: hours(1).add(days=0),
            lambda: hours(1).subtract(weeks=0),
            lambda: Instant.from_timestamp(0).add(days=0),
        ],
    )
    def test_zero_days_assume_nothing(self, call):
        with warnings.catch_warnings():
            warnings.simplefilter("error")
            call()

    def test_init(self):
        with warnings.catch_warnings():
            warnings.simplefilter("error")
            TimeDelta(days=1, days_assumed_24h_ok=True)

    def test_total(self):
        td = hours(48)
        with warnings.catch_warnings():
            warnings.simplefilter("error")
            result = td.total("days", days_assumed_24h_ok=True)
            assert result == approx(2.0)

    def test_in_units(self):
        td = hours(48)
        with warnings.catch_warnings():
            warnings.simplefilter("error")
            td.in_units(["days", "hours"], days_assumed_24h_ok=True)

    def test_round(self):
        td = hours(25)
        with warnings.catch_warnings():
            warnings.simplefilter("error")
            td.round("day", days_assumed_24h_ok=True)
