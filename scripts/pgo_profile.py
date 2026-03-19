#!/usr/bin/env python3
"""
Profile-Guided Optimization workload for the ``whenever`` library.

Exercises common code paths across all public types with randomized but
reproducible data. Designed to give the PGO compiler accurate
branch-frequency information for real-world workloads rather than
worst-case or error-handling paths.

The script covers:
  - Date, Time, YearMonth, MonthDay
  - Instant, OffsetDateTime, ZonedDateTime, PlainDateTime
  - TimeDelta, ItemizedDelta, ItemizedDateDelta

Data ranges:
  - Dates: 1900–2100
  - Timezones: all IANA zones available in the environment
  - UTC offsets: -12..+14 hours

Usage::

    python scripts/pgo_profile.py               # 200 iterations (default)
    python scripts/pgo_profile.py --iterations 500
    python scripts/pgo_profile.py --seed 42
"""

from __future__ import annotations

import argparse
import random
import zoneinfo

import whenever
from whenever import (
    Date,
    Instant,
    ItemizedDateDelta,
    ItemizedDelta,
    MonthDay,
    OffsetDateTime,
    PlainDateTime,
    Time,
    TimeDelta,
    YearMonth,
    ZonedDateTime,
)

# ---------------------------------------------------------------------------
# Setup: timezone pool, helpers
# ---------------------------------------------------------------------------

_TZNAMES: list[str] = sorted(zoneinfo.available_timezones())

# Days per month (non-leap year)
_MONTH_DAYS = [31, 28, 31, 30, 31, 30, 31, 31, 30, 31, 30, 31]


def _is_leap(year: int) -> bool:
    return year % 4 == 0 and (year % 100 != 0 or year % 400 == 0)


# ---------------------------------------------------------------------------
# Random value factories
# ---------------------------------------------------------------------------


def _rand_date(rng: random.Random) -> Date:
    year = rng.randint(1900, 2100)
    month = rng.randint(1, 12)
    max_day = _MONTH_DAYS[month - 1]
    if month == 2 and _is_leap(year):
        max_day = 29
    return Date(year, month, rng.randint(1, max_day))


def _rand_time(rng: random.Random) -> Time:
    return Time(
        rng.randint(0, 23),
        rng.randint(0, 59),
        rng.randint(0, 59),
        nanosecond=rng.randint(0, 999_999_999),
    )


def _rand_timedelta(rng: random.Random) -> TimeDelta:
    return TimeDelta(
        hours=rng.randint(-500, 500),
        minutes=rng.randint(-59, 59),
        seconds=rng.randint(-59, 59),
        nanoseconds=rng.randint(0, 999_999_999),
    )


def _rand_tz(rng: random.Random) -> str:
    return rng.choice(_TZNAMES)


def _rand_offset(rng: random.Random) -> int:
    return rng.randint(-12, 14)


def _rand_instant(rng: random.Random) -> Instant:
    # Unix timestamps for 1900-01-01 .. 2100-01-01
    ts = rng.randint(-2_208_988_800, 4_102_444_800)
    return Instant.from_timestamp(ts)


def _rand_zdt(rng: random.Random) -> ZonedDateTime:
    d = _rand_date(rng)
    t = _rand_time(rng)
    return ZonedDateTime(
        d.year, d.month, d.day,
        t.hour, t.minute, t.second,
        nanosecond=t.nanosecond,
        tz=_rand_tz(rng),
        disambiguate="compatible",
    )


def _rand_odt(rng: random.Random) -> OffsetDateTime:
    d = _rand_date(rng)
    t = _rand_time(rng)
    return OffsetDateTime(
        d.year, d.month, d.day,
        t.hour, t.minute, t.second,
        nanosecond=t.nanosecond,
        offset=_rand_offset(rng),
    )


def _rand_pdt(rng: random.Random) -> PlainDateTime:
    d = _rand_date(rng)
    t = _rand_time(rng)
    return PlainDateTime(
        d.year, d.month, d.day,
        t.hour, t.minute, t.second,
        nanosecond=t.nanosecond,
    )


# ---------------------------------------------------------------------------
# Per-type profile functions
# ---------------------------------------------------------------------------


def _profile_dates(rng: random.Random) -> None:
    d1 = _rand_date(rng)
    d2 = _rand_date(rng)

    # Construction: positional args and ISO string
    Date(d1.year, d1.month, d1.day)
    Date(d1.format_iso())

    # Attribute access
    _ = d1.year, d1.month, d1.day
    _ = d1.day_of_week()
    _ = d1.year_month()
    _ = d1.month_day()

    # Comparisons
    _ = d1 == d2
    _ = d1 < d2
    _ = min(d1, d2), max(d1, d2)

    # ISO round-trip (common path)
    Date.parse_iso(d1.format_iso())

    # Pattern round-trip (YYYY-MM-DD uses correct specifiers)
    Date.parse(d1.format("YYYY-MM-DD"), format="YYYY-MM-DD")
    # Month name variant
    d1.format("YYYY-MMM-DD")

    # Arithmetic — varied units hit different branches
    d3 = d1.add(years=1, months=3, days=15)
    d4 = d1.subtract(weeks=2)
    _ = d3.add(months=1)
    _ = d4.subtract(days=10)

    # since/until: multi-unit (in_units) and single-unit (total)
    _ = d1.since(d2, in_units=["years", "months", "days"])
    _ = d1.until(d2, in_units=["months", "days"])
    _ = d1.since(d2, total="days")
    _ = d1.until(d2, total="weeks")

    # replace (keep day ≤ 28 to stay valid across any month)
    _ = d1.replace(day=1)
    _ = d1.replace(month=6, day=min(d1.day, 30))

    # at() → PlainDateTime
    _ = d1.at(_rand_time(rng))

    # Stdlib interop
    _ = d1.to_stdlib()

    # YearMonth
    ym = YearMonth(d1.year, d1.month)
    YearMonth.parse_iso(ym.format_iso())

    # MonthDay (day ≤ 28 to stay valid in any year)
    day = min(d1.day, 28)
    md = MonthDay(d1.month, day)
    MonthDay.parse_iso(md.format_iso())
    _ = md.in_year(d1.year)


def _profile_times(rng: random.Random) -> None:
    t1 = _rand_time(rng)
    t2 = _rand_time(rng)

    # Construction
    Time(t1.hour, t1.minute, t1.second, nanosecond=t1.nanosecond)
    Time(t1.format_iso())

    # Attribute access
    _ = t1.hour, t1.minute, t1.second, t1.nanosecond

    # Comparisons
    _ = t1 == t2
    _ = t1 < t2

    # ISO round-trip
    Time.parse_iso(t1.format_iso())

    # Pattern round-trip — hh:mm:ss (correct specifiers)
    Time.parse(t1.format("hh:mm:ss"), format="hh:mm:ss")
    # With nanoseconds
    t1.format("hh:mm:ss.FFFFFFFFF")

    # Rounding at various granularities
    _ = t1.round("hour")
    _ = t1.round("minute")
    _ = t1.round("second")
    _ = t1.round("millisecond")

    # replace
    _ = t1.replace(hour=12)
    _ = t1.replace(minute=30, second=0)

    # Stdlib interop
    _ = t1.to_stdlib()


def _profile_timedelta(rng: random.Random) -> None:
    td1 = _rand_timedelta(rng)
    td2 = _rand_timedelta(rng)

    # Scalar extractors via total() — each unit hits a different branch
    _ = td1.total("nanoseconds")  # → int (exact)
    _ = td1.total("microseconds")
    _ = td1.total("milliseconds")
    _ = td1.total("seconds")
    _ = td1.total("minutes")
    _ = td1.total("hours")
    with whenever.ignore_days_not_always_24h_warning():
        _ = td1.total("days")
    _ = td1.in_hrs_mins_secs_nanos()

    # in_units() — decompose into multiple units
    # Valid exact units: weeks, days, hours, minutes, seconds, nanoseconds
    # "days" units require suppressing the 24h-day warning
    _ = td1.in_units(["hours", "minutes", "seconds"])
    with whenever.ignore_days_not_always_24h_warning():
        _ = td1.in_units(["days", "hours", "minutes", "seconds", "nanoseconds"])

    # Arithmetic operators
    _ = td1 + td2
    _ = td1 - td2
    _ = td1 * 3
    _ = td1 / 2.0
    _ = abs(td1)
    _ = -td1

    # ISO round-trip
    TimeDelta.parse_iso(td1.format_iso())

    # Rounding
    _ = td1.round("second")
    _ = td1.round("minute")
    _ = td1.round("hour")

    # Comparisons
    _ = td1 == td2
    _ = td1 < td2

    # Stdlib interop
    _ = td1.to_stdlib()


def _profile_itemized_delta(rng: random.Random) -> None:
    # All non-zero fields must share the same sign — generate a consistent set
    sign = rng.choice([1, -1])
    id1 = ItemizedDelta(
        weeks=sign * rng.randint(0, 5),
        hours=sign * rng.randint(0, 100),
        minutes=sign * rng.randint(0, 59),
        seconds=sign * rng.randint(0, 59),
        nanoseconds=sign * rng.randint(0, 999_999_999),
    )
    sign2 = rng.choice([1, -1])
    id2 = ItemizedDelta(
        hours=sign2 * rng.randint(0, 10),
        minutes=sign2 * rng.randint(0, 59),
    )
    z = ZonedDateTime(2000, 1, 1, tz="UTC")

    # Mapping access
    _ = dict(id1)
    _ = list(id1.keys())

    # sign()
    _ = id1.sign()

    # in_units / total (relative_to required)
    _ = id1.in_units(["hours", "minutes", "seconds"], relative_to=z)
    _ = id1.total("hours", relative_to=z)
    _ = id1.total("seconds", relative_to=z)

    # date_and_time_parts
    _ = id1.date_and_time_parts()

    # ISO round-trip
    ItemizedDelta.parse_iso(id1.format_iso())

    # Arithmetic (add/subtract need relative_to + in_units)
    _ = id1.add(id2, relative_to=z, in_units=["hours", "minutes", "seconds"])
    _ = id1.subtract(id2, relative_to=z, in_units=["hours", "minutes"])
    _ = id1.add(hours=1, minutes=30, relative_to=z, in_units=["hours", "minutes"])
    _ = -id1
    _ = abs(id1)

    # replace
    _ = id1.replace(minutes=0)

    # Comparisons
    _ = id1 == id2
    _ = id1.exact_eq(id2)


def _profile_itemized_date_delta(rng: random.Random) -> None:
    # All non-zero fields must share the same sign
    sign = rng.choice([1, -1])
    idd1 = ItemizedDateDelta(
        years=sign * rng.randint(0, 10),
        months=sign * rng.randint(0, 11),
        weeks=sign * rng.randint(0, 4),
        days=sign * rng.randint(0, 30),
    )
    sign2 = rng.choice([1, -1])
    idd2 = ItemizedDateDelta(
        months=sign2 * rng.randint(0, 6),
        days=sign2 * rng.randint(0, 30),
    )
    d = _rand_date(rng)

    # Mapping access
    _ = dict(idd1)
    _ = list(idd1.keys())

    # sign()
    _ = idd1.sign()

    # in_units / total
    _ = idd1.in_units(["years", "months", "days"], relative_to=d)
    _ = idd1.total("days", relative_to=d)
    _ = idd1.total("months", relative_to=d)

    # ISO round-trip
    ItemizedDateDelta.parse_iso(idd1.format_iso())

    # Arithmetic (add/subtract need relative_to + in_units)
    _ = idd1.add(idd2, relative_to=d, in_units=["years", "months", "days"])
    _ = idd1.subtract(idd2, relative_to=d, in_units=["months", "days"])
    _ = idd1.add(years=1, months=3, relative_to=d, in_units=["years", "months"])
    _ = -idd1
    _ = abs(idd1)

    # replace
    _ = idd1.replace(days=0)

    # Comparisons
    _ = idd1 == idd2
    _ = idd1.exact_eq(idd2)


def _profile_instants(rng: random.Random) -> None:
    i1 = _rand_instant(rng)
    i2 = _rand_instant(rng)
    td = _rand_timedelta(rng)

    # Construction variants
    Instant.from_timestamp(i1.timestamp())
    Instant.from_timestamp_millis(i1.timestamp_millis())
    Instant.from_timestamp_nanos(i1.timestamp_nanos())
    odt = i1.to_fixed_offset()
    Instant.from_utc(odt.year, odt.month, odt.day, odt.hour, odt.minute, odt.second)
    Instant(i1.format_iso())

    # Timestamp accessors
    _ = i1.timestamp()
    _ = i1.timestamp_millis()
    _ = i1.timestamp_nanos()

    # Comparisons
    _ = i1 == i2
    _ = i1 < i2
    _ = min(i1, i2)

    # ISO and RFC 2822 round-trips
    Instant.parse_iso(i1.format_iso())
    Instant.parse_rfc2822(i1.format_rfc2822())

    # Arithmetic
    _ = i1 + td
    _ = i1 - td
    _ = i2 - i1
    _ = i1 + whenever.TimeDelta(hours=3, minutes=15)

    # Instant has no since/until; use subtraction to get a TimeDelta
    diff = i2 - i1
    _ = diff.total("hours")
    _ = diff.in_units(["hours", "minutes", "seconds"])

    # Conversions
    tz = _rand_tz(rng)
    _ = i1.to_tz(tz)
    _ = i1.to_system_tz()
    _ = i1.to_fixed_offset(_rand_offset(rng))
    _ = i1.to_fixed_offset()

    # Stdlib interop
    _ = i1.to_stdlib()


def _profile_zoned(rng: random.Random) -> None:
    z1 = _rand_zdt(rng)
    z2 = _rand_zdt(rng)
    td = _rand_timedelta(rng)

    # Attribute access
    _ = z1.year, z1.month, z1.day
    _ = z1.hour, z1.minute, z1.second, z1.nanosecond
    _ = z1.tz, z1.offset

    # ISO round-trip
    ZonedDateTime.parse_iso(z1.format_iso())

    # Pattern format/parse (YYYY-MM-DD hh:mm:ss VV)
    z1.format("YYYY-MM-DD hh:mm:ss VV")

    # Arithmetic
    _ = z1.add(td)
    _ = z1.subtract(td)
    _ = z1.add(hours=2, minutes=30)
    _ = z1.subtract(days=1, hours=3)

    # since/until — exact units work across timezones; calendar units need same tz
    _ = z1.since(z2, total="hours")
    _ = z1.until(z2, total="seconds")
    _ = z1.since(z2, in_units=["hours", "minutes"])

    # Comparisons
    _ = z1.exact_eq(z2)

    # Conversions
    _ = z1.to_instant()
    _ = z1.to_fixed_offset()
    _ = z1.to_tz(_rand_tz(rng))
    _ = z1.to_plain()

    # replace
    _ = z1.replace(hour=12, disambiguate="compatible")

    # round
    _ = z1.round("hour")
    _ = z1.round("minute")

    # Stdlib interop
    _ = z1.to_stdlib()


def _profile_offset(rng: random.Random) -> None:
    o1 = _rand_odt(rng)
    o2 = _rand_odt(rng)
    td = _rand_timedelta(rng)

    # Attribute access
    _ = o1.year, o1.month, o1.day
    _ = o1.hour, o1.minute, o1.second, o1.nanosecond
    _ = o1.offset

    # ISO round-trip
    OffsetDateTime.parse_iso(o1.format_iso())

    # Pattern format (YYYY-MM-DD hh:mm:ss xxxxx)
    o1.format("YYYY-MM-DD hh:mm:ss xxxxx")

    # Arithmetic (suppress stale-offset warnings; these are expected in profiling)
    with whenever.ignore_potentially_stale_offset_warning():
        _ = o1.add(td)
        _ = o1.subtract(td)
        _ = o1.add(hours=1)
        _ = o1.subtract(minutes=30)

    # since/until
    _ = o1.since(o2, total="hours")
    _ = o1.until(o2, total="minutes")
    _ = o1.since(o2, in_units=["hours", "minutes", "seconds"])

    # Comparisons (compares by instant)
    _ = o1 == o2
    _ = o1 < o2

    # Conversions
    _ = o1.to_instant()
    _ = o1.to_tz(_rand_tz(rng))
    _ = o1.to_fixed_offset(_rand_offset(rng))
    _ = o1.to_plain()

    # replace (suppress stale-offset warning)
    with whenever.ignore_potentially_stale_offset_warning():
        _ = o1.replace(offset=_rand_offset(rng))

    # round (suppress stale-offset warning)
    with whenever.ignore_potentially_stale_offset_warning():
        _ = o1.round("hour")

    # Assume constructors (from PlainDateTime)
    p = PlainDateTime(o1.year, o1.month, o1.day, o1.hour, o1.minute, o1.second)
    _ = p.assume_fixed_offset(_rand_offset(rng))

    # Stdlib interop
    _ = o1.to_stdlib()


def _profile_plain(rng: random.Random) -> None:
    p1 = _rand_pdt(rng)
    p2 = _rand_pdt(rng)
    td = _rand_timedelta(rng)

    # Attribute access
    _ = p1.year, p1.month, p1.day
    _ = p1.hour, p1.minute, p1.second, p1.nanosecond

    # ISO round-trip
    PlainDateTime.parse_iso(p1.format_iso())

    # Pattern round-trip (YYYY-MM-DD hh:mm:ss)
    PlainDateTime.parse(
        p1.format("YYYY-MM-DD hh:mm:ss"),
        format="YYYY-MM-DD hh:mm:ss",
    )
    p1.format("YYYY-MM-DD hh:mm:ss.FFFFFFFFF")

    # Arithmetic (suppress timezone-unaware warnings; expected in profiling)
    with whenever.ignore_timezone_unaware_arithmetic_warning():
        _ = p1.add(td)
        _ = p1.subtract(td)
        _ = p1.add(days=1, hours=2)
        _ = p1.subtract(months=1, days=5)

    # since/until (suppress timezone-unaware warning)
    with whenever.ignore_timezone_unaware_arithmetic_warning():
        _ = p1.since(p2, total="hours")
        _ = p1.until(p2, total="days")
        _ = p1.since(p2, in_units=["days", "hours", "minutes", "seconds"])

    # Comparisons
    _ = p1 == p2
    _ = p1 < p2

    # Conversions
    _ = p1.assume_utc()
    _ = p1.assume_fixed_offset(_rand_offset(rng))
    _ = p1.assume_tz(_rand_tz(rng), disambiguate="compatible")
    _ = p1.date(), p1.time()

    # replace
    _ = p1.replace(hour=0, minute=0, second=0)

    # round
    _ = p1.round("hour")

    # Stdlib interop
    _ = p1.to_stdlib()


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--iterations",
        type=int,
        default=200,
        help="Number of iterations per profile function (default: 200)",
    )
    parser.add_argument(
        "--seed",
        type=int,
        default=12345,
        help="Random seed for reproducibility (default: 12345)",
    )
    args = parser.parse_args()

    rng = random.Random(args.seed)
    n = args.iterations

    print(
        f"whenever {whenever.__version__} | "
        f"extension loaded: {whenever._EXTENSION_LOADED}"
    )
    print(f"Iterations: {n} | seed: {args.seed} | timezones: {len(_TZNAMES)}")

    for _ in range(n):
        _profile_dates(rng)
        _profile_times(rng)
        _profile_timedelta(rng)
        _profile_itemized_delta(rng)
        _profile_itemized_date_delta(rng)
        _profile_instants(rng)
        _profile_offset(rng)
        _profile_plain(rng)
        _profile_zoned(rng)

    print("Done.")


if __name__ == "__main__":
    main()
