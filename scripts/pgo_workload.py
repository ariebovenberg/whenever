"""Training workload for profile-guided optimization (PGO) of the extension.

An instrumented build records which branches and functions this script
exercises; the optimized build then lays out code for those paths.
Two rules follow:

- **Breadth over weight.** A function the workload never reaches counts
  as cold: the compiler inlines less into it and moves it out of the hot
  path, so a feature missing here may get slower.
  Every public operation should appear at least once, and so should an
  argument that selects its own code path (a unit, a pattern specifier).
  To find gaps, build with `RUSTFLAGS=-Cinstrument-coverage`, run this
  script, and read the result with `llvm-cov report`.
- **Only the happy path.** Errors and warnings must stay cold, so every
  input is valid and any warning aborts the run.

The data is random but seeded, so the profile is reproducible.

    python scripts/pgo_workload.py [--iterations N]
"""

import argparse
import pickle
import random
import warnings
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

import whenever
from whenever import (
    SYSTEM_TZ,
    Date,
    Instant,
    IsoWeekDate,
    ItemizedDateDelta,
    ItemizedDelta,
    MonthDay,
    OffsetDateTime,
    PlainDateTime,
    Time,
    TimeDelta,
    Weekday,
    YearMonth,
    ZonedDateTime,
    hours,
    microseconds,
    milliseconds,
    minutes,
    nanoseconds,
    seconds,
)

TZ_IDS = sorted(whenever.available_timezones())
# A few representative zones, weighted to dominate the profile
COMMON_TZ_IDS = [
    "UTC",
    "Europe/Amsterdam",
    "Europe/London",
    "America/New_York",
    "America/Los_Angeles",
    "Asia/Tokyo",
    "Asia/Kolkata",
    "Australia/Sydney",
]


def rand_tz(r: random.Random) -> str:
    return r.choice(COMMON_TZ_IDS) if r.random() < 0.7 else r.choice(TZ_IDS)


def rand_date(r: random.Random) -> Date:
    return Date(r.randint(1900, 2100), r.randint(1, 12), r.randint(1, 28))


def rand_time(r: random.Random) -> Time:
    return Time(
        r.randint(0, 23),
        r.randint(0, 59),
        r.randint(0, 59),
        nanosecond=r.choice(
            [0, r.randint(0, 999) * 1_000_000, r.randint(0, 999_999_999)]
        ),
    )


def rand_offset(r: random.Random) -> TimeDelta:
    return minutes(15 * r.randint(-12 * 4, 14 * 4))


def rand_plain(r: random.Random) -> PlainDateTime:
    return rand_date(r).at(rand_time(r))


def rand_zoned(r: random.Random) -> ZonedDateTime:
    return rand_plain(r).assume_tz(rand_tz(r), disambiguation="compatible")


def rand_delta(r: random.Random) -> TimeDelta:
    return TimeDelta(
        hours=r.randint(-5_000, 5_000),
        minutes=r.randint(-59, 59),
        seconds=r.randint(-59, 59),
        nanoseconds=r.randint(0, 999_999_999),
    )


def rand_itemized(r: random.Random) -> ItemizedDelta:
    sign = r.choice([1, -1])
    return ItemizedDelta(
        years=sign * r.randint(0, 3),
        months=sign * r.randint(0, 11),
        days=sign * r.randint(0, 30),
        hours=sign * r.randint(0, 23),
        minutes=sign * r.randint(0, 59),
        seconds=sign * r.randint(0, 59),
    )


def rand_itemized_date(r: random.Random) -> ItemizedDateDelta:
    sign = r.choice([1, -1])
    return ItemizedDateDelta(
        years=sign * r.randint(0, 10),
        months=sign * r.randint(0, 11),
        weeks=sign * r.randint(0, 4),
        days=sign * r.randint(0, 30),
    )


def roundtrip(x: object) -> None:
    hash(x)
    str(x)
    repr(x)
    pickle.loads(pickle.dumps(x))
    if hasattr(x, "to_bytes"):
        type(x).from_bytes(x.to_bytes())


def local_fields(x: ZonedDateTime | OffsetDateTime | PlainDateTime) -> None:
    x.year, x.month, x.day, x.hour, x.minute, x.second, x.nanosecond
    x.date(), x.time(), x.day_of_week(), x.day_of_year()
    x.days_in_month(), x.days_in_year(), x.in_leap_year()
    f"{x:YYYY-MM-DD HH:mm}"


def exercise_date(r: random.Random) -> None:
    d, other = rand_date(r), rand_date(r)
    roundtrip(d)
    Date(d.year, d.month, d.day)
    Date(d.format_iso())
    Date.parse_iso(d.format_iso(basic=True))
    Date(d.to_stdlib())
    Date.today(rand_tz(r))
    Date.parse(d.format("YYYY-MM-DD"), pattern="YYYY-MM-DD")
    Date.parse(d.format("EEE, D MMM YYYY"), pattern="EEE, D MMM YYYY")
    f"{d:DD/MM/YYYY}"
    d.year, d.month, d.day
    d.day_of_week(), d.day_of_year(), d.iso_week_date()
    d.days_in_month(), d.days_in_year(), d.in_leap_year()
    d.next_day(), d.prev_day()
    d.nth_weekday(r.choice([1, -1]), r.choice(list(Weekday)))
    d.nth_weekday_of_month(r.choice([1, 2, -1]), r.choice(list(Weekday)))
    for unit in ("year", "month", "week_mon", "week_sun"):
        d.start_of(unit), d.end_of(unit)
    d == other, d < other, d >= other
    d.replace(day=1)
    d.add(years=1, months=r.randint(-12, 12), days=r.randint(-40, 40))
    d.subtract(weeks=2)
    d + rand_itemized_date(r)
    d.since(other, in_units=["years", "months", "days"])
    d.until(other, in_units=["weeks", "days"], round_mode="half_even")
    d.since(other, in_units=["months"], round_increment=3, round_mode="floor")
    d.since(other, total=r.choice(["years", "months", "weeks", "days"]))
    d.at(rand_time(r))

    ym, md = d.year_month(), d.month_day()
    roundtrip(ym)
    roundtrip(md)
    YearMonth.parse_iso(ym.format_iso())
    ym.on_day(1), ym.add(months=r.randint(-30, 30)), ym.subtract(years=1)
    ym.days_in_month(), ym.replace(month=6) < ym
    MonthDay.parse_iso(md.format_iso())
    md.in_year(d.year), md.is_leap_day(), md.replace(day=1)

    w = d.iso_week_date()
    roundtrip(w)
    IsoWeekDate.parse_iso(w.format_iso())
    w.date(), w.weeks_in_year(), w.week, w.weekday


def exercise_time(r: random.Random) -> None:
    t, other = rand_time(r), rand_time(r)
    roundtrip(t)
    Time(t.hour, t.minute, t.second, nanosecond=t.nanosecond)
    Time(t.format_iso())
    Time.parse_iso(t.format_iso(unit="second", basic=True))
    Time(t.to_stdlib())
    Time.parse(t.format("HH:mm:ss.FFFFFFFFF"), pattern="HH:mm:ss.FFFFFFFFF")
    Time.parse(t.format("i:mm[:ss] aa"), pattern="i:mm[:ss] aa")
    f"{t:HH:mm}"
    t.hour, t.minute, t.second, t.nanosecond
    t == other, t < other
    t.round()
    t.round("minute", increment=15)
    t.round(minutes(30), mode="floor")
    t.replace(hour=12)
    t.on(rand_date(r))


def exercise_time_delta(r: random.Random) -> None:
    d, other = rand_delta(r), rand_delta(r)
    roundtrip(d)
    TimeDelta(d.format_iso())
    TimeDelta(d.to_stdlib())
    TimeDelta(hours=r.random() * 100)
    hours(1.5), minutes(r.randint(0, 600)), seconds(r.random() * 1000)
    milliseconds(r.randint(0, 10_000)), microseconds(1.5), nanoseconds(500)
    d.total(r.choice(["hours", "minutes", "seconds", "milliseconds"]))
    d.total("nanoseconds")
    d.total("days", days_assumed_24h_ok=True)
    d.total("months", relative_to=rand_zoned(r))
    d.total("days", relative_to=rand_plain(r), naive_arithmetic_ok=True)
    d.in_units(["hours", "minutes", "seconds"])
    d.in_units(["days", "hours", "minutes"], days_assumed_24h_ok=True)
    d.in_units(
        ["hours", "minutes"],
        round_mode=r.choice(["floor", "ceil", "expand", "half_even"]),
    )
    d.round("minute"), d.round("second", increment=5), d.round(minutes(15))
    (
        d + other,
        d - other,
        d * 1.5,
        d * 3,
        d / 3,
        d / other,
        d // other,
        d % other,
    )
    -d, abs(d), bool(d)
    d.add(hours=1), d.subtract(other)
    d == other, d < other


def exercise_instant(r: random.Random) -> None:
    i = Instant.from_timestamp(r.randint(-2_208_988_800, 4_102_444_800))
    other = i + rand_delta(r)
    roundtrip(i)
    Instant.now()
    Instant.from_utc(2024, r.randint(1, 12), 15, r.randint(0, 23), 30)
    Instant.from_timestamp(i.timestamp(unit="millisecond"), unit="millisecond")
    Instant.from_timestamp(i.timestamp(unit="nanosecond"), unit="nanosecond")
    Instant.from_timestamp(r.random() * 2e9)
    i.timestamp(), i.timestamp(unit="microsecond")
    Instant(i.format_iso())
    Instant.parse_iso(i.format_iso(unit="millisecond", sep=" "))
    Instant.parse_rfc2822(i.format_rfc2822())
    Instant.parse(
        i.format("YYYY-MM-DD'T'HH:mm:ssXXX"),
        pattern="YYYY-MM-DD'T'HH:mm:ssXXX",
    )
    f"{i:YYYY-MM-DD HH:mm}"
    Instant(i.to_stdlib())
    Instant(datetime(2024, 1, 1, tzinfo=timezone.utc))
    i == other, i < other, i.strict_eq(other)
    i - other, i.difference(other)
    i + rand_delta(r), i.add(hours=3), i.subtract(minutes=15)
    i.round("minute", increment=5), i.round(hours(1), mode="floor")
    i.to_tz(rand_tz(r)), i.to_tz(SYSTEM_TZ)
    i.to_fixed_offset(), i.to_fixed_offset(rand_offset(r))


def exercise_zoned(r: random.Random) -> None:
    z, other = rand_zoned(r), rand_zoned(r)
    tz = z.tz_id
    assert tz is not None
    roundtrip(z)
    ZonedDateTime.now(tz)
    ZonedDateTime(
        z.year,
        z.month,
        z.day,
        z.hour,
        z.minute,
        tz=tz,
        disambiguation="compatible",
    )
    ZonedDateTime(z.format_iso())
    ZonedDateTime.parse_iso(z.format_iso(unit="second", sep=" "))
    ZonedDateTime.parse(
        z.format("YYYY-MM-DD HH:mm:ss.fffffffffxxx'['VV']'"),
        pattern="YYYY-MM-DD HH:mm:ss.fffffffffxxx'['VV']'",
    )
    z.format("EEEE D MMMM YYYY, HH:mm zz")
    ZonedDateTime(z.to_stdlib())
    ZonedDateTime(datetime(2024, 7, 1, 12, tzinfo=ZoneInfo(tz)))
    local_fields(z)
    z.offset, z.tz_id, z.timestamp(), z.timestamp(unit="nanosecond")
    z.is_repeated(), z.dst_offset(), z.tz_abbrev(), z.day_length()
    z.next_transition(), z.prev_transition()
    z == other, z < other, z.strict_eq(other)
    z - other, z.difference(other)
    z + rand_delta(r), z - hours(2)
    z.add(hours=r.randint(-48, 48), minutes=30)
    z.add(days=r.randint(-400, 400), disambiguation="compatible")
    z.subtract(months=1, disambiguation="compatible")
    z.add(rand_itemized_date(r), disambiguation="compatible")
    z.subtract(rand_itemized(r), disambiguation="compatible")
    z.since(other, total=r.choice(["hours", "seconds", "minutes"]))
    z.until(
        z.add(days=r.randint(0, 900), disambiguation="compatible"),
        in_units=["years", "months", "weeks", "days"],
    )
    z.since(other, in_units=["hours", "minutes"], round_mode="half_even")
    z.since(other, in_units=["hours"], round_increment=6, round_mode="expand")
    z.replace(hour=12, disambiguation="compatible")
    z.replace_date(rand_date(r), disambiguation="compatible")
    z.replace_time(Time(9), disambiguation="compatible")
    z.start_of(r.choice(["day", "month", "hour"]))
    z.end_of(r.choice(["day", "week_mon", "hour"]))
    z.round("day"), z.round("hour"), z.round("minute", increment=15)
    z.round(minutes(30), mode="floor")
    z.to_instant(), z.to_plain(), z.to_fixed_offset()
    z.to_tz(rand_tz(r)), z.to_tz(SYSTEM_TZ), z.to_stdlib()


def exercise_offset(r: random.Random) -> None:
    p = rand_plain(r)
    o = p.assume_fixed_offset(rand_offset(r))
    other = rand_plain(r).assume_fixed_offset(rand_offset(r))
    roundtrip(o)
    OffsetDateTime.now(rand_offset(r), stale_offset_ok=True)
    OffsetDateTime(
        p.year, p.month, p.day, p.hour, offset=hours(r.randint(-12, 14))
    )
    OffsetDateTime(o.format_iso())
    OffsetDateTime.parse_iso(o.format_iso(unit="minute", basic=True))
    OffsetDateTime("2024-03-15T10:30:00Z")
    OffsetDateTime.parse_rfc2822(o.format_rfc2822())
    OffsetDateTime.parse(
        o.format("YYYY-MM-DD HH:mm:ssxxx"), pattern="YYYY-MM-DD HH:mm:ssxxx"
    )
    OffsetDateTime(o.to_stdlib())
    OffsetDateTime(datetime(2024, 1, 1, tzinfo=timezone(timedelta(hours=2))))
    local_fields(o)
    o.offset, o.timestamp(), o.timestamp(unit="millisecond")
    o == other, o < other, o.strict_eq(other), o - other, o.difference(other)
    o.add(hours=2, stale_offset_ok=True)
    o.subtract(days=1, stale_offset_ok=True)
    o.since(other, total="minutes")
    o.until(
        o.add(hours=r.randint(0, 900), stale_offset_ok=True),
        in_units=["days", "hours"],
        stale_offset_ok=True,
    )
    o.replace(hour=0, stale_offset_ok=True), o.replace(offset=rand_offset(r))
    o.round("hour", stale_offset_ok=True)
    o.start_of("day", stale_offset_ok=True)
    o.end_of("month", stale_offset_ok=True)
    o.replace_date(rand_date(r), stale_offset_ok=True)
    o.replace_time(rand_time(r), stale_offset_ok=True)
    o.to_instant()
    o.to_plain()
    o.to_tz(rand_tz(r))
    o.to_fixed_offset(hours(0))
    o.assume_tz(rand_tz(r), offset_mismatch="keep_instant")


def exercise_plain(r: random.Random) -> None:
    p, other = rand_plain(r), rand_plain(r)
    roundtrip(p)
    PlainDateTime(
        p.year,
        p.month,
        p.day,
        p.hour,
        p.minute,
        p.second,
        nanosecond=p.nanosecond,
    )
    PlainDateTime(p.format_iso())
    PlainDateTime.parse_iso(p.format_iso(sep=" ", unit="millisecond"))
    PlainDateTime.parse(
        p.format("YYYY-MM-DD HH:mm:ss"), pattern="YYYY-MM-DD HH:mm:ss"
    )
    PlainDateTime.parse(
        p.format("YYYY-MM-DD'T'HH:mm[:ss]"), pattern="YYYY-MM-DD'T'HH:mm[:ss]"
    )
    p.format("DD/MM/YYYY ii:mm aa")
    PlainDateTime(p.to_stdlib())
    local_fields(p)
    p == other, p < other
    p.add(days=r.randint(-100, 100), hours=5, naive_arithmetic_ok=True)
    p.subtract(rand_delta(r), naive_arithmetic_ok=True)
    p.add(months=1), p + rand_itemized_date(r)
    p.difference(other, naive_arithmetic_ok=True)
    p.since(
        other, in_units=["days", "hours", "minutes"], naive_arithmetic_ok=True
    )
    p.until(other, total="days", naive_arithmetic_ok=True)
    p.replace(minute=0)
    p.replace_date(rand_date(r))
    p.replace_time(Time.NOON)
    p.start_of("month"), p.end_of("week_sun"), p.round("minute")
    p.assume_utc(), p.assume_fixed_offset(rand_offset(r))
    p.assume_tz(rand_tz(r), disambiguation="compatible")


EXERCISES = [
    exercise_date,
    exercise_time,
    exercise_time_delta,
    exercise_instant,
    exercise_zoned,
    exercise_offset,
    exercise_plain,
]


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--iterations", type=int, default=2_000)
    args = parser.parse_args()
    assert whenever._EXTENSION_LOADED, "profiling needs the Rust extension"
    print(f"whenever {whenever.__version__} from {whenever.__file__}")

    warnings.simplefilter("error")
    r = random.Random(1)
    for _ in range(args.iterations):
        for exercise in EXERCISES:
            exercise(r)


if __name__ == "__main__":
    main()
