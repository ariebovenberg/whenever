"""Date, calendar, and time arithmetic helpers."""

from datetime import date as _date, timedelta as _timedelta

# Type alias for various date difference functions used for rounding.
# Consists of:
# 1. The absolute difference between two dates in the given unit and increment.
# 2. The truncated date resulting from this difference.
# 3. The expanded date resulting from this difference EXPANDED with the increment.
_AbsoluteDiff = tuple[int, _date, _date]


def years_diff(a: _date, b: _date, increment: int) -> _AbsoluteDiff:
    diff = (a.year - b.year) // increment * increment
    shift = _replace_year_saturating(b, b.year + diff)

    # Check if we overshot
    if (diff > 0 and shift > a) or (diff < 0 and shift < a):
        diff -= increment * (-1 if diff < 0 else 1)
        return (
            abs(diff),
            _replace_year_saturating(b, b.year + diff),
            shift,
        )
    else:
        return (
            abs(diff),
            shift,
            _replace_year_saturating(b, b.year + diff + increment),
        )


def months_diff(a: _date, b: _date, increment: int) -> _AbsoluteDiff:
    diff = (
        ((a.year - b.year) * 12 + (a.month - b.month)) // increment
    ) * increment
    shift = _add_months(b, diff)

    # Check if we overshot
    if (diff > 0 and shift > a) or (diff < 0 and shift < a):
        diff -= increment * (1 if diff > 0 else -1)
        return (abs(diff), _add_months(b, diff), shift)
    else:
        return (abs(diff), shift, _add_months(b, diff + increment))


def weeks_diff(a: _date, b: _date, increment: int) -> _AbsoluteDiff:
    days, trunc, expand = days_diff(a, b, increment * 7)
    return days // 7, trunc, expand


def days_diff(a: _date, b: _date, increment: int) -> _AbsoluteDiff:
    diff = abs((a - b).days) // increment * increment
    sign = 1 if a > b else -1

    return (
        diff,
        b + _timedelta(diff * sign),
        b + _timedelta((diff + increment) * sign),
    )


def _replace_year_saturating(d: _date, year: int, /) -> _date:
    try:
        return d.replace(year=year)
    except ValueError:
        # only happens when we move Feb 29 to a non-leap year
        return d.replace(year=year, day=28)


def _add_months(d: _date, months: int) -> _date:
    year_delta, month0_new = divmod(d.month - 1 + months, 12)
    year_new = d.year + year_delta
    month_new = month0_new + 1
    try:
        return d.replace(year=year_new, month=month_new)
    except ValueError:
        # only happens when we move to a month with fewer days
        return d.replace(
            year=year_new,
            month=month_new,
            day=days_in_month(year_new, month_new),
        )


def is_leap(year: int) -> bool:
    return year % 4 == 0 and (year % 100 != 0 or year % 400 == 0)


# 1-indexed days per month
_MONTHDAYS = [0, 31, 28, 31, 30, 31, 30, 31, 31, 30, 31, 30, 31]


def days_in_month(year: int, month: int) -> int:
    return _MONTHDAYS[month] + (month == 2 and is_leap(year))


_UNIT_NANOS_AND_MAX_DIVISOR = {
    "week": (604_800_000_000_000, 0),
    "day": (86_400_000_000_000, 0),
    "hour": (3_600_000_000_000, 24),
    "minute": (60_000_000_000, 60),
    "second": (1_000_000_000, 60),
    "millisecond": (1_000_000, 1_000),
    "microsecond": (1_000, 1_000),
    "nanosecond": (1, 1_000),
}


def increment_to_ns_for_delta(unit: str, increment: int) -> int:
    if increment < 1 or increment != int(increment):
        raise ValueError("Invalid increment")
    try:
        ns_per_unit, _ = _UNIT_NANOS_AND_MAX_DIVISOR[unit]
    except KeyError:
        raise ValueError(f"Invalid unit: {unit}")
    return ns_per_unit * increment


def increment_to_ns_for_datetime(unit: str, increment: int) -> int:
    if increment < 1 or increment > 1_000 or increment != int(increment):
        raise ValueError("Invalid increment")

    if unit == "day" and increment != 1:
        raise ValueError(
            "Rounding increment for day can only be 1"
        )  # TODO reason

    try:
        ns_per_unit, max_divisor = _UNIT_NANOS_AND_MAX_DIVISOR[unit]
    except KeyError:
        raise ValueError(f"Invalid unit: {unit}")

    if max_divisor % increment:
        raise ValueError(
            f"Invalid increment for {unit}. Must divide {max_divisor}."
        )
    return ns_per_unit * increment
