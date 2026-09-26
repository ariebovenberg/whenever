"""
This tests the internal math utilities of the pure-Python version of Whenever.
These are not intended to be used directly by users,
but they are important for the correct functioning of the library,
so they deserve tests.

It also holds the rounding law, which every ``round()`` follows.
"""

import math
import re
import warnings
from fractions import Fraction
from typing import Any

import pytest
from whenever import (
    Date,
    Instant,
    OffsetDateTime,
    PlainDateTime,
    Time,
    TimeDelta,
    ZonedDateTime,
    hours,
)
from whenever._math import rounds_up

MODES = [
    "ceil",
    "expand",
    "floor",
    "trunc",
    "half_ceil",
    "half_expand",
    "half_floor",
    "half_trunc",
    "half_even",
]
NS_PER_DAY = 86_400 * 10**9


def exact_round(value: int, increment: int, mode: str, *, signed: bool) -> int:
    """Rounding by exact fractions. Only a signed quantity, a ``TimeDelta``,
    tells ``trunc`` from ``floor``: a point on the timeline counts as positive."""
    q = Fraction(value, increment)
    lo, hi = math.floor(q), math.ceil(q)
    toward_zero, away = (hi, lo) if signed and value < 0 else (lo, hi)
    nearest = lo if q - lo < Fraction(1, 2) else hi
    is_tie = q - lo == Fraction(1, 2)
    return (
        increment
        * {
            "floor": lo,
            "ceil": hi,
            "trunc": toward_zero,
            "expand": away,
            "half_floor": lo if is_tie else nearest,
            "half_ceil": hi if is_tie else nearest,
            "half_trunc": toward_zero if is_tie else nearest,
            "half_expand": away if is_tie else nearest,
            "half_even": (lo if lo % 2 == 0 else hi) if is_tie else nearest,
        }[mode]
    )


def time_of(ns: int) -> Time:
    return Time(
        ns // (3_600 * 10**9),
        ns // (60 * 10**9) % 60,
        ns // 10**9 % 60,
        nanosecond=ns % 10**9,
    )


class TestRoundsUp:
    @pytest.mark.parametrize("span", [1, 2, 3, 8, 9])
    @pytest.mark.parametrize("sign", [1, -1])
    def test_agrees_with_exact_fractions(self, span, sign):
        for mode in MODES:
            for quotient in (4, 7):
                for remainder in range(span):
                    magnitude = quotient * span + remainder
                    expected = exact_round(
                        sign * magnitude, span, mode, signed=True
                    )
                    assert rounds_up(
                        mode, remainder, span, quotient % 2 == 1, sign
                    ) == (abs(expected) > quotient * span), (
                        mode,
                        quotient,
                        remainder,
                    )

    def test_invalid_mode(self):
        with pytest.raises(ValueError, match="invalid mode: 'foo'"):
            rounds_up("foo", 3, 5, False, 1)


class TestRoundingLaw:
    @pytest.mark.parametrize(
        "unit, unit_ns, max_increment",
        [
            ("nanosecond", 1, 1_000),
            ("microsecond", 10**3, 1_000),
            ("millisecond", 10**6, 1_000),
            ("second", 10**9, 60),
            ("minute", 60 * 10**9, 60),
            ("hour", 3_600 * 10**9, 24),
        ],
    )
    def test_around_the_tie(self, unit, unit_ns, max_increment):
        # Before 1970: an instant rounds as a positive number there too
        date = Date(1960, 2, 10)
        for n in range(1, max_increment + 1):
            increment = n * unit_ns
            if NS_PER_DAY % increment:
                continue
            half = increment // 2
            # An odd increment has no tie: both neighbours of the half count
            offsets = {half - 1, half, half + 1, (increment + 1) // 2}
            # A quotient of each parity, for the half_even tie
            starts = [
                (NS_PER_DAY // 3 // increment + k) * increment for k in (0, 1)
            ]
            for v in {(b + o) % NS_PER_DAY for b in starts for o in offsets}:
                time = time_of(v)
                for mode in MODES:
                    kwargs: dict[str, Any] = {"increment": n, "mode": mode}
                    wall = exact_round(v, increment, mode, signed=False)
                    days, ns = divmod(wall, NS_PER_DAY)
                    assert time.round(unit, **kwargs) == time_of(ns)
                    plain = date.at(time)
                    expected = date.add(days=days).at(time_of(ns))
                    assert plain.round(unit, **kwargs) == expected
                    assert plain.assume_fixed_offset(hours(2)).round(
                        unit, stale_offset_ok=True, **kwargs
                    ) == expected.assume_fixed_offset(hours(2))
                    assert plain.assume_tz("Asia/Tokyo").round(
                        unit, **kwargs
                    ) == expected.assume_tz("Asia/Tokyo")
                    assert (
                        plain.assume_utc().round(unit, **kwargs)
                        == expected.assume_utc()
                    )
                    for d in (v, -v):
                        assert TimeDelta(nanoseconds=d).round(
                            unit, **kwargs
                        ) == TimeDelta(
                            nanoseconds=exact_round(
                                d, increment, mode, signed=True
                            )
                        )

    def test_largest_delta_does_not_escape_its_range(self):
        with pytest.raises(ValueError, match="out of range"):
            TimeDelta.MAX.round(TimeDelta(nanoseconds=97), mode="half_trunc")


_ROUNDABLE = [
    Time(13, 45, 7),
    PlainDateTime(2024, 1, 1, 13, 45, 7),
    OffsetDateTime(2024, 1, 1, 13, 45, 7, offset=hours(2)),
    ZonedDateTime(2024, 1, 1, 13, 45, 7, tz="Europe/Paris"),
    Instant.from_utc(2024, 1, 1, 13, 45, 7),
    TimeDelta(hours=13, minutes=45, seconds=7),
]


def _round(value: Any, *args: Any, **kwargs: Any) -> Any:
    if isinstance(value, OffsetDateTime):
        kwargs["stale_offset_ok"] = True
    return value.round(*args, **kwargs)


class TestRoundArguments:
    @pytest.mark.parametrize(
        "value", _ROUNDABLE, ids=lambda v: type(v).__name__
    )
    def test_increment_without_unit_counts_seconds(self, value):
        assert _round(value, increment=15) == _round(
            value, "second", increment=15
        )
        assert _round(value, increment=15) != value

    @pytest.mark.parametrize(
        "value", _ROUNDABLE[:-1], ids=lambda v: type(v).__name__
    )
    def test_increment_without_unit_is_validated(self, value):
        with pytest.raises(
            ValueError, match="^increment must divide a 24-hour day evenly$"
        ):
            _round(value, increment=7)

    @pytest.mark.parametrize(
        "call, message",
        [
            # the unit is checked before the increment
            (
                lambda: Time(1).round("day", increment=30),  # type: ignore[call-overload]
                "invalid unit: 'day'",
            ),
            (
                lambda: Instant.from_timestamp(0).round("day", increment=2),  # type: ignore[call-overload]
                "cannot round an Instant to a day: an Instant has no calendar; "
                "use 'hour' with increment=24 for exactly 24 hours",
            ),
            (
                lambda: Time(1).round("foo", increment=0),  # type: ignore[call-overload]
                "invalid unit: 'foo'",
            ),
            (
                lambda: TimeDelta.ZERO.round("foo", increment=0),  # type: ignore[call-overload]
                "invalid unit: 'foo'",
            ),
            # both are checked before a warning
            (
                lambda: TimeDelta.ZERO.round("day", increment=2**62),
                "value or calculation out of range",
            ),
            (
                lambda: TimeDelta.ZERO.round("week", increment=0),
                "increment must be a positive integer",
            ),
        ],
    )
    def test_validation_order(self, call, message):
        with warnings.catch_warnings():
            warnings.simplefilter("error")
            with pytest.raises(
                ValueError, match="^" + re.escape(message) + "$"
            ):
                call()
