"""Date, calendar, and time arithmetic helpers."""

from __future__ import annotations

from collections.abc import Sequence
from datetime import date as _date, timedelta as _timedelta
from typing import Literal, TypeVar, cast

from ._common import INCREMENT_MSG, RANGE_MSG, UNSET, expect_int, invalid
from ._typing import (
    DateDeltaUnitStr,
    DeltaUnitStr,
    ExactDeltaUnitStr,
    RoundModeStr,
)

DATE_DELTA_UNITS = cast(
    Sequence[DateDeltaUnitStr], ["years", "months", "weeks", "days"]
)
EXACT_UNITS_STRICT = cast(
    Sequence[ExactDeltaUnitStr],
    ["hours", "minutes", "seconds", "nanoseconds"],
)
EXACT_TOTAL_UNITS = (
    *EXACT_UNITS_STRICT,
    "milliseconds",
    "microseconds",
)
EXACT_UNITS = ["weeks", "days", *EXACT_UNITS_STRICT]
DELTA_UNITS = cast(
    Sequence[DeltaUnitStr], [*DATE_DELTA_UNITS, *EXACT_UNITS_STRICT]
)
TOTAL_UNITS = (*DATE_DELTA_UNITS, *EXACT_TOTAL_UNITS)

_Tstr = TypeVar("_Tstr", bound=str)


def unit_index(u: str, units: Sequence[str]) -> int:
    try:
        return units.index(u)
    except ValueError:
        raise invalid("unit", u) from None


def normalize_units(
    units: Sequence[str],
    valid_units: Sequence[_Tstr],
) -> tuple[_Tstr, ...]:
    """The ``units``/``in_units`` argument as a tuple: any iterable of unit
    names in decreasing order, a bare string and a set excepted."""
    if isinstance(units, (str, bytes)):
        raise TypeError(
            "units must be a sequence of strings, not a single string"
        )
    if isinstance(units, (set, frozenset)):
        raise TypeError("units must be a sequence of strings, not a set")
    units = tuple(units)
    if not units:
        raise ValueError("units must not be empty")
    if sorted(units, key=lambda u: unit_index(u, valid_units)) != list(units):
        raise ValueError("units must be in decreasing order of size")
    if len(set(units)) != len(units):
        raise ValueError("units cannot contain duplicates")
    if "nanoseconds" in units and "seconds" not in units:
        raise ValueError(
            "nanoseconds can only be specified together with seconds"
        )
    return units  # type: ignore[return-value]


# A special class to represent February 29th on a year that is not a leap year.
# Used internally during date difference calculations.
class PendingLeapDay:
    __slots__ = ("resolved",)
    resolved: _date

    @property
    def year(self) -> int:
        return self.resolved.year

    # Fixed month and day for leap day. Added for duck-typing compatibility with datetime.date.
    month = 2
    day = 29

    def __init__(self, year: int) -> None:
        self.resolved = _date(year, 2, 28)


InterimDate = _date | PendingLeapDay


def resolve_leap_day(d: InterimDate) -> _date:
    if isinstance(d, PendingLeapDay):
        return d.resolved
    return d


# Type alias for various date difference functions used for rounding.
# Consists of:
# 1. The absolute difference between two dates in the given unit and increment.
# 2. The truncated date resulting from this difference.
# 3. The expanded date resulting from this difference EXPANDED with the increment.
_AbsoluteDiff = tuple[int, InterimDate, InterimDate]


def years_diff(
    _a: _date, b: InterimDate, increment: int, sign: Literal[1, -1], /
) -> _AbsoluteDiff:
    # This function has a permissive signature to match the others, but
    # only datetime.date is expected for b, since "years" is the largest
    # (and thus first) unit encountered when diffing.
    assert isinstance(b, _date)
    diff = (_a.year - b.year) // increment * increment
    shift = _replace_year(b, b.year + diff)

    # Check if we overshot
    if (diff > 0 and resolve_leap_day(shift) > _a) or (
        diff < 0 and resolve_leap_day(shift) < _a
    ):
        diff -= increment * sign
        return (abs(diff), _replace_year(b, b.year + diff), shift)
    else:
        return (
            abs(diff),
            shift,
            _replace_year(b, b.year + diff + increment * sign),
        )


def _replace_year(d: _date, year: int) -> InterimDate:
    if not _date.min.year <= year <= _date.max.year:
        raise ValueError(RANGE_MSG)
    try:
        return d.replace(year=year)
    except ValueError:  # only happens for Feb 29 on non-leap years
        return PendingLeapDay(year)


def months_diff(
    a: _date, b: InterimDate, increment: int, sign: Literal[1, -1], /
) -> _AbsoluteDiff:
    diff = (
        ((a.year - b.year) * 12 + (a.month - b.month)) // increment
    ) * increment
    shift = _add_months(b, diff)

    # Check if we overshot
    if (diff > 0 and shift > a) or (diff < 0 and shift < a):
        diff -= increment * sign
        return (abs(diff), _add_months(b, diff), shift)
    else:
        return (abs(diff), shift, _add_months(b, diff + increment * sign))


def _add_months(d: InterimDate, delta: int, /) -> _date:
    year_delta, month0_new = divmod(d.month - 1 + delta, 12)
    year_new = d.year + year_delta
    month_new = month0_new + 1
    if not _date.min.year <= year_new <= _date.max.year:
        raise ValueError(RANGE_MSG)
    day_new = min(d.day, days_in_month(year_new, month_new))
    return _date(year_new, month_new, day_new)


def weeks_diff(
    a: _date, b: InterimDate, increment: int, sign: Literal[1, -1], /
) -> _AbsoluteDiff:
    days, trunc, expand = days_diff(a, b, increment * 7, sign)
    return days // 7, trunc, expand


def days_diff(
    a: _date, _b: InterimDate, increment: int, sign: Literal[1, -1], /
) -> _AbsoluteDiff:
    b = resolve_leap_day(_b)
    diff = abs((a - b).days) // increment * increment
    try:
        return (
            diff,
            b + _timedelta(diff * sign),
            b + _timedelta((diff + increment) * sign),
        )
    except OverflowError:
        raise ValueError(RANGE_MSG) from None


DIFF_FUNCS = {
    "years": years_diff,
    "months": months_diff,
    "weeks": weeks_diff,
    "days": days_diff,
}


def date_diff(
    a: _date,
    b: _date,
    round_increment: int,
    units: Sequence[DateDeltaUnitStr],
    sign: Literal[1, -1],
) -> tuple[dict[DateDeltaUnitStr, int], InterimDate, InterimDate]:
    # Because years and months are variable length, the calculation is done
    # by progressively adding each unit to `b` until we reach the target date (`a`).
    # We keep track of two dates: one that is truncated (not exceeding `a`)
    # and one that is expanded (equal to or exceeding `a`).
    trunc: InterimDate = b
    expand: InterimDate = a

    # We only apply the increment logic to the last unit.
    # The other units get increment 1.
    increments = [*[1] * (len(units) - 1), round_increment]
    results = {}
    for u, increment in zip(units, increments):
        results[u], trunc, expand = DIFF_FUNCS[u](a, trunc, increment, sign)

    return results, trunc, expand


def is_leap(year: int) -> bool:
    return year % 4 == 0 and (year % 100 != 0 or year % 400 == 0)


# 1-indexed days per month
_MONTHDAYS = [0, 31, 28, 31, 30, 31, 30, 31, 31, 30, 31, 30, 31]


def days_in_month(year: int, month: int) -> int:
    return _MONTHDAYS[month] + (month == 2 and is_leap(year))


NS_PER_UNIT_SINGULAR = {
    "week": 604_800_000_000_000,
    "day": 86_400_000_000_000,
    "hour": 3_600_000_000_000,
    "minute": 60_000_000_000,
    "second": 1_000_000_000,
    "millisecond": 1_000_000,
    "microsecond": 1_000,
    "nanosecond": 1,
}
NS_PER_UNIT_PLURAL = {
    "weeks": 604_800_000_000_000,
    "days": 86_400_000_000_000,
    "hours": 3_600_000_000_000,
    "minutes": 60_000_000_000,
    "seconds": 1_000_000_000,
    "milliseconds": 1_000_000,
    "microseconds": 1_000,
    "nanoseconds": 1,
}


ROUND_MODES: frozenset[RoundModeStr] = frozenset(
    (
        "ceil",
        "expand",
        "floor",
        "trunc",
        "half_ceil",
        "half_expand",
        "half_floor",
        "half_trunc",
        "half_even",
    )
)


def resolve_rounding(
    mode: RoundModeStr, increment: int
) -> tuple[RoundModeStr, int]:
    """Validate the ``round_mode``/``round_increment`` pair of ``in_units()``,
    ``since()``/``until()``, and calendar-aware composition, applying the
    defaults for ``UNSET``."""
    if mode is UNSET:
        mode = "trunc"
    if increment is UNSET:
        increment = 1
    if mode not in ROUND_MODES:
        raise invalid("round_mode", mode)
    increment = expect_int("round_increment", increment)
    if increment <= 0:
        raise ValueError("round_increment must be a positive integer in range")
    return mode, increment


# The widest day count a calendar increment can span, as the Rust extension
# bounds it.
MAX_CALENDAR_INCREMENT = (_date.max - _date.min).days + 1


def resolve_date_rounding(
    mode: RoundModeStr, increment: int
) -> tuple[RoundModeStr, int]:
    """``resolve_rounding`` for a date-only computation, whose increment is
    a count of calendar units."""
    mode, increment = resolve_rounding(mode, increment)
    if increment > MAX_CALENDAR_INCREMENT:
        raise ValueError("round_increment must be a positive integer in range")
    return mode, increment


# The widest increment the Rust extension represents: whole seconds in 64 bits.
_MAX_INCREMENT_SECS = 2**64 - 1


def _increment_to_ns(unit: str, increment: int) -> int:
    increment = expect_int("increment", increment)
    if increment < 1:
        raise ValueError(INCREMENT_MSG)
    try:
        ns_per_unit = NS_PER_UNIT_SINGULAR[unit]
    except KeyError:
        raise invalid("unit", unit) from None
    return ns_per_unit * increment


def increment_to_ns_for_delta(unit: str, increment: int) -> int:
    increment_ns = _increment_to_ns(unit, increment)
    if increment_ns // 1_000_000_000 > _MAX_INCREMENT_SECS:
        raise ValueError(RANGE_MSG)
    return increment_ns


def increment_to_ns_for_datetime(unit: str, increment: int) -> int:
    increment_ns = _increment_to_ns(unit, increment)
    if 86_400_000_000_000 % increment_ns:
        raise ValueError(INCREMENT_MSG)
    return increment_ns


_FRACTIONAL_UNITS = (
    "weeks",
    "days",
    "hours",
    "minutes",
    "seconds",
    "milliseconds",
    "microseconds",
)


def exact_units_to_nanos(
    weeks: float = 0,
    days: float = 0,
    hours: float = 0,
    minutes: float = 0,
    seconds: float = 0,
    milliseconds: float = 0,
    microseconds: float = 0,
    nanoseconds: int = 0,
) -> int:
    """The nanoseconds in the given exact time units.

    The types are checked up front: multiplying a ``str`` would repeat it
    instead of raising, and a float ``nanoseconds`` would leak into the sum.
    """
    fractional = (
        weeks,
        days,
        hours,
        minutes,
        seconds,
        milliseconds,
        microseconds,
    )
    if not all(isinstance(v, (int, float)) for v in fractional):
        name = next(
            n
            for n, v in zip(_FRACTIONAL_UNITS, fractional)
            if not isinstance(v, (int, float))
        )
        raise TypeError(f"{name} must be an integer or float")
    nanoseconds = expect_int("nanoseconds", nanoseconds)
    try:
        return (
            int(weeks * 604_800_000_000_000)
            + int(days * 86_400_000_000_000)
            + int(hours * 3_600_000_000_000)
            + int(minutes * 60_000_000_000)
            + int(seconds * 1_000_000_000)
            + int(milliseconds * 1_000_000)
            + int(microseconds * 1_000)
            + nanoseconds
        )
    except (OverflowError, ValueError):  # infinity or NaN
        raise ValueError(RANGE_MSG) from None


Sign = Literal[1, 0, -1]


# This rounding function has a bit of a strange signature, due to the fact
# that it needs to run with calendar units. For example, it needs to be able
# to round *months* using the difference in *days* to determine whether
# to round up or down.
# Hopefully you won't have to come back to this function to make changes.
# If necessary, read the tests and usage in the main code to understand how this function is used.
def custom_round(
    trunc_value: int,
    remainder: int,
    expanded: int,
    mode: str,
    increment: int,
    sign: Literal[1, -1],
) -> int:
    do_expand = False  # 'expand' means round away from 0

    # Some internal sanity checks (Should not be triggered by user input, since the main code should guarantee these)
    assert mode != "trunc"  # should be handled by caller

    # All values are absolute values, and the sign is handled separately.
    assert expanded > 0
    assert remainder >= 0
    assert trunc_value >= 0

    # Rounding should always be done to a different value
    assert increment > 0
    assert expanded != remainder

    match mode:
        case "half_even":
            do_expand = remainder * 2 > expanded or (
                remainder * 2 == expanded
                and (trunc_value // increment) % 2 == 1
            )
        case "expand":
            do_expand = remainder > 0
        case "ceil":
            do_expand = remainder * sign > 0
        case "floor":
            do_expand = remainder * sign < 0
        case "half_ceil":
            do_expand = (
                remainder * 2 >= expanded
                if sign > 0
                else remainder * 2 > expanded
            )
        case "half_floor":
            do_expand = (
                remainder * 2 > expanded
                if sign > 0
                else remainder * 2 >= expanded
            )
        case "half_trunc":
            do_expand = remainder * 2 > expanded
        case "half_expand":
            do_expand = remainder * 2 >= expanded
        case _:
            raise invalid("mode", mode)

    return trunc_value + (increment * do_expand)
