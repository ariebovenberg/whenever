---
myst:
  html_meta:
    description: >-
      Rounding datetimes and TimeDeltas with round(): the available rounding
      modes, supported units, and custom increments. Finding unit boundaries
      with start_of(), end_of(), and day_length().
---

(rounding)=
# Rounding and boundaries

It's often useful to truncate or round a datetime or {class}`~whenever.TimeDelta` to a specific unit.
For example, you might want to round a datetime to the nearest hour,
or truncate it into 15-minute intervals.

The `round()` method allows you to do this:

```python
>>> d = PlainDateTime(2023, 12, 28, 11, 32, 8)
PlainDateTime("2023-12-28 11:32:08")
>>> d.round("hour")
PlainDateTime("2023-12-28 12:00:00")
>>> d.round("minute", increment=15, mode="ceil")
PlainDateTime("2023-12-28 11:45:00")
```

The API for rounding is largely inspired by that of Temporal (JavaScript).

(rounding-modes)=
## Modes

Different rounding modes are available. They differ on two axes:

- Whether they round towards/away from zero (`trunc`/`expand`) or up/down (`ceil`/`floor`)
- How they break ties

This results in the following modes:

| Mode       | Rounding direction | Tie-breaking  | Examples | stdlib equivalent |
|------------|--------------------|-----------------------|----------|----------|
| `ceil`     | up                 | n/a                   | 3.1→4, -3.1→-3 |  {func}`~math.ceil`  |
| `floor`    | down               | n/a                   | 3.1→3, -3.1→-4 | {func}`~math.floor` |
| `trunc`    | towards zero       | n/a                   | 3.1→3, -3.1→-3 | {func}`~math.trunc`, {class}`int` |
| `expand`   | away from zero     | n/a                   | 3.1→4, -3.1→-4 | n/a |
| `half_ceil`  | nearest increment  | up    | 3.5→4, -3.5→-3 |n/a  |
| `half_floor` | nearest increment  | down  | 3.5→3, -3.5→-4 |n/a  |
| `half_trunc` | nearest increment  | towards zero  |  3.5→3, -3.5→-3 |n/a  |
| `half_expand` | nearest increment  | away from zero |  3.5→4, -3.5→-4 |n/a  |
| `half_even` | nearest increment  | to even | 3.5→4, 4.5→4, -3.5→-4 | {func}`round` |

For positive values, the behavior of `ceil` is identical to `expand` and the behavior of `floor` is identical to `trunc`.
The difference is only visible for negative values.
A datetime, a {class}`~whenever.Time`, and an {class}`~whenever.Instant` count as positive,
also before 1970,
so only a {class}`~whenever.TimeDelta` shows the difference between `trunc` and `floor`.

The default mode is `half_even`, and the default unit is `"second"`,
so `round()` with no arguments does what Python's own {func}`round` does.
The delta methods `in_units()`, `since()`, and `until()` default to `"trunc"` instead:
a difference in whole units is counted, not rounded,
so `since()` says how many whole hours have passed, as a clock would.

## Supported units

The `unit` argument allows you to specify the unit to round to.
Allowed values depend on the type of the object being rounded:

| Type | weeks | days | hours<br> and smaller |
|------|:-----:|:----:|:-------:|
| {class}`~whenever.TimeDelta` | ✅ [^1] | ✅ [^1] | ✅ |
| {class}`~whenever.ZonedDateTime`, | ❌ | ✅ | ✅ |
| {class}`~whenever.PlainDateTime`, | ❌ | ✅ | ✅ |
| {class}`~whenever.OffsetDateTime`, | ❌ | ✅ | ✅ |
| {class}`~whenever.Instant` | ❌ | ❌ [^2] | ✅ |
| {class}`~whenever.Time` | ❌ | ❌ | ✅ [^3] |

A {class}`~whenever.TimeDelta` can be passed as the unit itself,
on every type that has `round()`:

```python
>>> d.round(TimeDelta(minutes=15))
PlainDateTime("2023-12-28 11:30:00")
```

Such a unit must divide a 24-hour day evenly everywhere
except on {meth}`TimeDelta.round() <whenever.TimeDelta.round>`, where it may be any positive delta.
It cannot be combined with `increment=`.
It never emits {class}`~whenever.DaysAssumed24HoursWarning`,
since a delta claims no calendar, while the named `"day"` and `"week"` units do.
Suppress that warning by passing `days_assumed_24h_ok=True`
if you know the assumption is acceptable for your use case:

```python
>>> d = TimeDelta(hours=50)
>>> d.round("day", days_assumed_24h_ok=True)
TimeDelta("PT48h")
```

(rounding-instant-day)=
`Instant.round("day")` is rejected: an {class}`~whenever.Instant` has no calendar,
so a day has no midnight to start at.
To round to periods of exactly 24 hours, pass `"hour"` with `increment=24`, or `hours(24)`.
As with every increment on an {class}`~whenever.Instant`,
the periods are counted from midnight UTC,
and `half_even` breaks a tie toward the even multiple counted from that midnight,
not from the epoch.

## Increment

The `increment` argument sets the {term}`rounding increment`:
the step the value is rounded to, as a count of the unit.
For example, you can round to the nearest 15 minutes by setting `increment=15`
and `unit="minute"`.

There are some restrictions on the allowed increments:

- The increment must be a positive, non-zero integer.
- On a datetime, a {class}`~whenever.Time`, or an {class}`~whenever.Instant`,
  the increment must divide a 24-hour day evenly.
  For example, you can round to the nearest 90 minutes (16 increments per day),
  but not to the nearest 7 seconds.
  {meth}`TimeDelta.round() <whenever.TimeDelta.round>` has no such rule.

In `in_units()`, `since()`, and `until()`, `round_increment=` applies to the
smallest component, and the `half_*` modes measure nearness to that
component's multiples before any carry: 5 hours 59 minutes in hours and
minutes with `round_increment=7` and `round_mode="half_expand"` is `PT5h56m`
(3 minutes away), not the carried `PT6h0m` (1 minute away).

## Boundaries

Where `round()` moves a value to the nearest increment of a unit,
`start_of()` and `end_of()` move it to the edges of the unit it lies in.
They exist on {class}`~whenever.Date`, {class}`~whenever.PlainDateTime`,
{class}`~whenever.OffsetDateTime`, and {class}`~whenever.ZonedDateTime`:

```python
>>> d = PlainDateTime(2023, 12, 28, 11, 32, 8)
>>> d.start_of("month")
PlainDateTime("2023-12-01 00:00:00")
>>> d.end_of("hour")
PlainDateTime("2023-12-28 11:59:59.999999999")
>>> Date(2023, 12, 28).start_of("week_mon")
Date("2023-12-25")
```

The units are `"year"`, `"month"`, `"week_mon"`, `"week_sun"`, `"day"`,
`"hour"`, `"minute"`, and `"second"`; a {class}`~whenever.Date` takes the first four.
A week can start on Monday (ISO) or on Sunday, so the unit says which:
a bare `"week"` is rejected.
`start_of()` on a time unit is `round()` with `mode="floor"`,
and {class}`~whenever.Date` has no `round()`, since it has nothing below a day to round.

`end_of()` returns the last nanosecond of the unit,
so that the `end_of()` of one unit is one nanosecond before the `start_of()` of the next.

A {class}`~whenever.ZonedDateTime` day is not always 24 hours long.
`day_length()` gives the difference between consecutive day starts:

```python
>>> ZonedDateTime(2023, 3, 26, 12, tz="Europe/Amsterdam").day_length()
TimeDelta("PT23h")
>>> ZonedDateTime(2023, 10, 29, 12, tz="Europe/Amsterdam").day_length()
TimeDelta("PT25h")
```

For values near a time zone transition,
see the {meth}`~whenever.ZonedDateTime.start_of` and {meth}`~whenever.ZonedDateTime.end_of` docstrings.

On an {class}`~whenever.OffsetDateTime`, `round()`, `start_of()`, and `end_of()`
keep the offset, which may be stale at the new time,
so they emit {class}`~whenever.StaleOffsetWarning`;
pass `stale_offset_ok=True` to accept it.
To stay correct across transitions, round a {class}`~whenever.ZonedDateTime` instead.

[^1]: This assumes days are always 24 hours long, which is not always the case in practice due to daylight saving time changes.
      Thus, a {class}`~whenever.DaysAssumed24HoursWarning` is issued
      when rounding a TimeDelta to days or weeks.
[^2]: See {ref}`the note above <rounding-instant-day>` for the distinction
      between calendar-day rounding and exact 24-hour periods.
[^3]: A {class}`~whenever.Time` has no date to carry into,
      so rounding up past 23:59:59 wraps around to 00:00.
