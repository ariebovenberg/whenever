"""
This tests the internal math utilities of the pure-Python version of Whenever.
These are not intended to be used directly by users,
but they are important for the correct functioning of the library,
so they deserve tests.

It also holds the rounding law, which every ``round()`` follows.
"""

import math
from fractions import Fraction
from typing import Any

import pytest
from whenever import Date, Time, TimeDelta, hours
from whenever._math import custom_round


class TestCustomRound:
    @pytest.mark.parametrize(
        "value, remainder, expanded, mode, increment, sign, expected",
        [
            # positive sign, one removed from the next increment
            (1_234, 4, 5, "floor", 8, 1, 1_234),
            (1_234, 4, 5, "ceil", 8, 1, 1_234 + 8),
            (1_234, 4, 5, "expand", 8, 1, 1_234 + 8),
            (1_234, 4, 5, "half_ceil", 8, 1, 1_234 + 8),
            (1_234, 4, 5, "half_floor", 8, 1, 1_234 + 8),
            (1_234, 4, 5, "half_expand", 8, 1, 1_234 + 8),
            (1_234, 4, 5, "half_trunc", 8, 1, 1_234 + 8),
            (1_234, 5, 6, "floor", 8, 1, 1_234),
            (1_234, 5, 6, "ceil", 8, 1, 1_234 + 8),
            (1_234, 5, 6, "expand", 8, 1, 1_234 + 8),
            (1_234, 5, 6, "half_ceil", 8, 1, 1_234 + 8),
            (1_234, 5, 6, "half_floor", 8, 1, 1_234 + 8),
            (1_234, 5, 6, "half_expand", 8, 1, 1_234 + 8),
            (1_234, 5, 6, "half_trunc", 8, 1, 1_234 + 8),
            # positive sign, closer to the next increment
            (1_234, 3, 5, "floor", 8, 1, 1_234),
            (1_234, 3, 5, "ceil", 8, 1, 1_234 + 8),
            (1_234, 3, 5, "expand", 8, 1, 1_234 + 8),
            (1_234, 3, 5, "half_ceil", 8, 1, 1_234 + 8),
            (1_234, 3, 5, "half_floor", 8, 1, 1_234 + 8),
            (1_234, 3, 5, "half_expand", 8, 1, 1_234 + 8),
            (1_234, 3, 5, "half_trunc", 8, 1, 1_234 + 8),
            (1_234, 3, 5, "half_even", 8, 1, 1_234 + 8),
            # positive sign, one over halfway to the next increment
            (456, 10, 18, "floor", 3, 1, 456),
            (456, 10, 18, "ceil", 3, 1, 456 + 3),
            (456, 10, 18, "expand", 3, 1, 456 + 3),
            (456, 10, 18, "half_ceil", 3, 1, 456 + 3),
            (456, 10, 18, "half_floor", 3, 1, 456 + 3),
            (456, 10, 18, "half_expand", 3, 1, 456 + 3),
            (456, 10, 18, "half_trunc", 3, 1, 456 + 3),
            (456, 10, 18, "half_even", 3, 1, 456 + 3),
            (456, 10, 19, "floor", 3, 1, 456),
            (456, 10, 19, "ceil", 3, 1, 456 + 3),
            (456, 10, 19, "expand", 3, 1, 456 + 3),
            (456, 10, 19, "half_ceil", 3, 1, 456 + 3),
            (456, 10, 19, "half_floor", 3, 1, 456 + 3),
            (456, 10, 19, "half_expand", 3, 1, 456 + 3),
            (456, 10, 19, "half_trunc", 3, 1, 456 + 3),
            (456, 10, 19, "half_even", 3, 1, 456 + 3),
            # positive sign, exactly halfway to the next increment
            (456, 9, 18, "floor", 3, 1, 456),
            (456, 9, 18, "ceil", 3, 1, 456 + 3),
            (456, 9, 18, "expand", 3, 1, 456 + 3),
            (456, 9, 18, "half_ceil", 3, 1, 456 + 3),
            (456, 9, 18, "half_floor", 3, 1, 456),
            (456, 9, 18, "half_expand", 3, 1, 456 + 3),
            (456, 9, 18, "half_trunc", 3, 1, 456),
            # Check ties are rounded to even while accounting for "increment"
            (456, 9, 18, "half_even", 3, 1, 456),
            (457, 9, 18, "half_even", 3, 1, 457),
            (458, 9, 18, "half_even", 3, 1, 458),
            (459, 9, 18, "half_even", 3, 1, 459 + 3),
            # positive sign, one away from halfway to the next increment
            (456, 8, 18, "floor", 3, 1, 456),
            (456, 8, 18, "ceil", 3, 1, 456 + 3),
            (456, 8, 18, "expand", 3, 1, 456 + 3),
            (456, 8, 18, "half_ceil", 3, 1, 456),
            (456, 8, 18, "half_floor", 3, 1, 456),
            (456, 8, 18, "half_expand", 3, 1, 456),
            (456, 8, 18, "half_trunc", 3, 1, 456),
            (456, 8, 19, "floor", 3, 1, 456),
            (456, 8, 19, "ceil", 3, 1, 456 + 3),
            (456, 8, 19, "expand", 3, 1, 456 + 3),
            (456, 8, 19, "half_ceil", 3, 1, 456),
            (456, 8, 19, "half_floor", 3, 1, 456),
            (456, 8, 19, "half_expand", 3, 1, 456),
            (456, 8, 19, "half_trunc", 3, 1, 456),
            # positive sign, closer to the previous increment
            (0, 432, 1_002, "floor", 7, 1, 0),
            (0, 432, 1_002, "ceil", 7, 1, 0 + 7),
            (0, 432, 1_002, "expand", 7, 1, 0 + 7),
            (0, 432, 1_002, "half_ceil", 7, 1, 0),
            (0, 432, 1_002, "half_floor", 7, 1, 0),
            (0, 432, 1_002, "half_expand", 7, 1, 0),
            (0, 432, 1_002, "half_trunc", 7, 1, 0),
            (0, 432, 1_002, "half_even", 7, 1, 0),
            # positive sign, one remainder
            (772, 1, 9, "floor", 100, 1, 772),
            (772, 1, 9, "ceil", 100, 1, 772 + 100),
            (772, 1, 9, "expand", 100, 1, 772 + 100),
            (772, 1, 9, "half_ceil", 100, 1, 772),
            (772, 1, 9, "half_floor", 100, 1, 772),
            (772, 1, 9, "half_expand", 100, 1, 772),
            (772, 1, 9, "half_trunc", 100, 1, 772),
            (772, 1, 9, "half_even", 100, 1, 772),
            # positive sign, zero remainder
            (772, 0, 1, "floor", 100, 1, 772),
            (772, 0, 1, "ceil", 100, 1, 772),
            (772, 0, 1, "expand", 100, 1, 772),
            (772, 0, 1, "half_ceil", 100, 1, 772),
            (772, 0, 1, "half_floor", 100, 1, 772),
            (772, 0, 1, "half_expand", 100, 1, 772),
            (772, 0, 1, "half_trunc", 100, 1, 772),
            (772, 0, 1, "half_even", 100, 1, 772),
            (772, 0, 2, "floor", 100, 1, 772),
            (772, 0, 2, "ceil", 100, 1, 772),
            (772, 0, 2, "expand", 100, 1, 772),
            (772, 0, 2, "half_ceil", 100, 1, 772),
            (772, 0, 2, "half_floor", 100, 1, 772),
            (772, 0, 2, "half_expand", 100, 1, 772),
            (772, 0, 2, "half_trunc", 100, 1, 772),
            (772, 0, 2, "half_even", 100, 1, 772),
            (772, 0, 3, "floor", 100, 1, 772),
            (772, 0, 3, "ceil", 100, 1, 772),
            (772, 0, 3, "expand", 100, 1, 772),
            (772, 0, 3, "half_ceil", 100, 1, 772),
            (772, 0, 3, "half_floor", 100, 1, 772),
            (772, 0, 3, "half_expand", 100, 1, 772),
            (772, 0, 3, "half_trunc", 100, 1, 772),
            (772, 0, 3, "half_even", 100, 1, 772),
            # negative sign, one removed from the next increment
            (1_234, 4, 5, "floor", 8, -1, 1_234 + 8),
            (1_234, 4, 5, "ceil", 8, -1, 1_234),
            (1_234, 4, 5, "expand", 8, -1, 1_234 + 8),
            (1_234, 4, 5, "half_ceil", 8, -1, 1_234 + 8),
            (1_234, 4, 5, "half_floor", 8, -1, 1_234 + 8),
            (1_234, 4, 5, "half_expand", 8, -1, 1_234 + 8),
            (1_234, 4, 5, "half_trunc", 8, -1, 1_234 + 8),
            (1_234, 5, 6, "floor", 8, -1, 1_234 + 8),
            (1_234, 5, 6, "ceil", 8, -1, 1_234),
            (1_234, 5, 6, "expand", 8, -1, 1_234 + 8),
            (1_234, 5, 6, "half_ceil", 8, -1, 1_234 + 8),
            (1_234, 5, 6, "half_floor", 8, -1, 1_234 + 8),
            (1_234, 5, 6, "half_expand", 8, -1, 1_234 + 8),
            (1_234, 5, 6, "half_trunc", 8, -1, 1_234 + 8),
            # negative sign, closer to the next increment
            (1_234, 3, 5, "floor", 8, -1, 1_234 + 8),
            (1_234, 3, 5, "ceil", 8, -1, 1_234),
            (1_234, 3, 5, "expand", 8, -1, 1_234 + 8),
            (1_234, 3, 5, "half_ceil", 8, -1, 1_234 + 8),
            (1_234, 3, 5, "half_floor", 8, -1, 1_234 + 8),
            (1_234, 3, 5, "half_expand", 8, -1, 1_234 + 8),
            (1_234, 3, 5, "half_trunc", 8, -1, 1_234 + 8),
            (1_234, 3, 5, "half_even", 8, -1, 1_234 + 8),
            # negative sign, one over halfway to the next increment
            (456, 10, 18, "floor", 3, -1, 456 + 3),
            (456, 10, 18, "ceil", 3, -1, 456),
            (456, 10, 18, "expand", 3, -1, 456 + 3),
            (456, 10, 18, "half_ceil", 3, -1, 456 + 3),
            (456, 10, 18, "half_floor", 3, -1, 456 + 3),
            (456, 10, 18, "half_expand", 3, -1, 456 + 3),
            (456, 10, 18, "half_trunc", 3, -1, 456 + 3),
            (456, 10, 18, "half_even", 3, -1, 456 + 3),
            (456, 10, 17, "floor", 3, -1, 456 + 3),
            (456, 10, 17, "ceil", 3, -1, 456),
            (456, 10, 17, "expand", 3, -1, 456 + 3),
            (456, 10, 17, "half_ceil", 3, -1, 456 + 3),
            (456, 10, 17, "half_floor", 3, -1, 456 + 3),
            (456, 10, 17, "half_expand", 3, -1, 456 + 3),
            (456, 10, 17, "half_trunc", 3, -1, 456 + 3),
            (456, 10, 17, "half_even", 3, -1, 456 + 3),
            # negative sign, exactly halfway to the next increment
            (456, 9, 18, "floor", 3, -1, 456 + 3),
            (456, 9, 18, "ceil", 3, -1, 456),
            (456, 9, 18, "expand", 3, -1, 456 + 3),
            (456, 9, 18, "half_ceil", 3, -1, 456),
            (456, 9, 18, "half_floor", 3, -1, 456 + 3),
            (456, 9, 18, "half_expand", 3, -1, 456 + 3),
            (456, 9, 18, "half_trunc", 3, -1, 456),
            # negative sign, one away from halfway to the next increment
            (456, 8, 18, "floor", 3, -1, 456 + 3),
            (456, 8, 18, "ceil", 3, -1, 456),
            (456, 8, 18, "expand", 3, -1, 456 + 3),
            (456, 8, 18, "half_ceil", 3, -1, 456),
            (456, 8, 18, "half_floor", 3, -1, 456),
            (456, 8, 18, "half_expand", 3, -1, 456),
            (456, 8, 18, "half_trunc", 3, -1, 456),
            (456, 8, 18, "half_even", 3, -1, 456),
            (456, 8, 19, "floor", 3, -1, 456 + 3),
            (456, 8, 19, "ceil", 3, -1, 456),
            (456, 8, 19, "expand", 3, -1, 456 + 3),
            (456, 8, 19, "half_ceil", 3, -1, 456),
            (456, 8, 19, "half_floor", 3, -1, 456),
            (456, 8, 19, "half_expand", 3, -1, 456),
            (456, 8, 19, "half_trunc", 3, -1, 456),
            (456, 8, 19, "half_even", 3, -1, 456),
            # negative sign, closer to the previous increment
            (0, 432, 1_002, "floor", 7, -1, 0 + 7),
            (0, 432, 1_002, "ceil", 7, -1, 0),
            (0, 432, 1_002, "expand", 7, -1, 0 + 7),
            (0, 432, 1_002, "half_ceil", 7, -1, 0),
            (0, 432, 1_002, "half_floor", 7, -1, 0),
            (0, 432, 1_002, "half_expand", 7, -1, 0),
            (0, 432, 1_002, "half_trunc", 7, -1, 0),
            (0, 432, 1_002, "half_even", 7, -1, 0),
            # negative sign, one remainder
            (772, 1, 9, "floor", 100, -1, 772 + 100),
            (772, 1, 9, "ceil", 100, -1, 772),
            (772, 1, 9, "expand", 100, -1, 772 + 100),
            (772, 1, 9, "half_ceil", 100, -1, 772),
            (772, 1, 9, "half_floor", 100, -1, 772),
            (772, 1, 9, "half_expand", 100, -1, 772),
            (772, 1, 9, "half_trunc", 100, -1, 772),
            (772, 1, 9, "half_even", 100, -1, 772),
            # negative sign, zero remainder
            (772, 0, 1, "floor", 100, -1, 772),
            (772, 0, 1, "ceil", 100, -1, 772),
            (772, 0, 1, "expand", 100, -1, 772),
            (772, 0, 1, "half_ceil", 100, -1, 772),
            (772, 0, 1, "half_floor", 100, -1, 772),
            (772, 0, 1, "half_expand", 100, -1, 772),
            (772, 0, 1, "half_trunc", 100, -1, 772),
            (772, 0, 1, "half_even", 100, -1, 772),
            (772, 0, 2, "floor", 100, -1, 772),
            (772, 0, 2, "ceil", 100, -1, 772),
            (772, 0, 2, "expand", 100, -1, 772),
            (772, 0, 2, "half_ceil", 100, -1, 772),
            (772, 0, 2, "half_floor", 100, -1, 772),
            (772, 0, 2, "half_expand", 100, -1, 772),
            (772, 0, 2, "half_trunc", 100, -1, 772),
            (772, 0, 2, "half_even", 100, -1, 772),
            (772, 0, 3, "floor", 100, -1, 772),
            (772, 0, 3, "ceil", 100, -1, 772),
            (772, 0, 3, "expand", 100, -1, 772),
            (772, 0, 3, "half_ceil", 100, -1, 772),
            (772, 0, 3, "half_floor", 100, -1, 772),
            (772, 0, 3, "half_expand", 100, -1, 772),
            (772, 0, 3, "half_trunc", 100, -1, 772),
            (772, 0, 3, "half_even", 100, -1, 772),
        ],
    )
    def test_valid(
        self, value, remainder, expanded, mode, increment, sign, expected
    ):
        assert (
            custom_round(value, remainder, expanded, mode, increment, sign)
            == expected
        )

    def test_invalid_mode(self):
        with pytest.raises(ValueError, match="invalid mode: 'foo'"):
            custom_round(1_234, 3, 5, "foo", 8, 1)


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
        with pytest.raises(ValueError):
            TimeDelta.MAX.round(TimeDelta(nanoseconds=97), mode="half_trunc")
