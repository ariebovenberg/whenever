"""Date, calendar, and time arithmetic helpers."""

from __future__ import annotations

from collections.abc import Sequence
from datetime import date as _date, timedelta as _timedelta
from typing import Literal, Union, cast

from ._typing import DateDeltaUnitStr, DeltaUnitStr

# TODO: rationalize
DATE_DELTA_UNITS = cast(
    Sequence[DateDeltaUnitStr], ["years", "months", "weeks", "days"]
)
_EXACT_UNITS_STRICT = ["hours", "minutes", "seconds", "nanoseconds"]
EXACT_UNITS = ["weeks", "days", *_EXACT_UNITS_STRICT]
DELTA_UNITS = cast(
    Sequence[DeltaUnitStr], [*DATE_DELTA_UNITS, *_EXACT_UNITS_STRICT]
)


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


InterimDate = Union[_date, PendingLeapDay]


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

    return (
        diff,
        b + _timedelta(diff * sign),
        b + _timedelta((diff + increment) * sign),
    )


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


def increment_to_ns_for_delta(unit: str, increment: int) -> int:
    if increment < 1 or increment != int(increment):
        raise ValueError("Invalid increment. Must be a positive integer.")
    try:
        ns_per_unit = NS_PER_UNIT_SINGULAR[unit]
    except KeyError:
        raise ValueError(f"Invalid unit: {unit}")
    return ns_per_unit * increment


def increment_to_ns_for_datetime(unit: str, increment: int) -> int:
    increment_ns = increment_to_ns_for_delta(unit, increment)
    if 86_400_000_000_000 % increment_ns:
        raise ValueError(
            f"Invalid increment. Must divide a 24-hour day evenly."
        )
    return increment_ns


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

    # DROP-PY39: match-case
    if mode == "half_even":  # check this mode first, since it's common.
        do_expand = remainder * 2 > expanded or (
            remainder * 2 == expanded and (trunc_value // increment) % 2 == 1
        )
    elif mode == "expand":
        do_expand = remainder > 0
    elif mode == "ceil":
        do_expand = remainder * sign > 0
    elif mode == "floor":
        do_expand = remainder * sign < 0
    elif mode == "half_ceil":
        do_expand = remainder * 2 >= (expanded - sign or 1)
    elif mode == "half_floor":
        do_expand = remainder * 2 >= (expanded + sign or 1)
    elif mode == "half_trunc":
        do_expand = remainder * 2 > expanded
    elif mode == "half_expand":
        do_expand = remainder * 2 >= expanded
    else:
        raise ValueError(f"Invalid rounding mode: {mode!r}")

    return trunc_value + (increment * do_expand)
