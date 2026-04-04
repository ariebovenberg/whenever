(arithmetic)=
# Arithmetic

`whenever` supports differences, additions, and subtractions across all its
datetime and instant types. This page is a practical guide to those operations.

```{tip}
For the conceptual background on exact vs. calendar units,
see {ref}`the fundamentals <arithmetic2>`.
For working with duration objects directly,
see {ref}`delta types <durations>`.
```

## Simple examples

```python
>>> ZonedDateTime(2023, 12, 28, 11, 30, tz="Europe/Amsterdam").add(hours=5, minutes=30)
ZonedDateTime("2023-12-28 17:00:00+01:00[Europe/Amsterdam]")

>>> Instant.from_utc(2023, 12, 28, 11, 30) - ZonedDateTime(2023, 12, 28, tz="Europe/Amsterdam")
TimeDelta("PT12h30m")

>>> d1 = ZonedDateTime(2020, 1, 1, tz="Europe/Amsterdam")
>>> d2 = ZonedDateTime(2023, 6, 15, tz="Europe/Amsterdam")
>>> d2.since(d1, in_units=["years", "months", "days"])
ItemizedDelta("P3y5m14d")
```

## Overview

The table below summarizes which operations are available for each type.
Click a row heading to learn more about that kind of operation;
click a cell to jump to that type's detailed section.

|  | {ref}`Instant <arithmetic-inst>` | {ref}`ZonedDT <arithmetic-zoned>` | {ref}`OffsetDT <arithmetic-offset>` | {ref}`PlainDT <arithmetic-plain>` |
|:--|:--:|:--:|:--:|:--:|
| {ref}`Exact difference <arith-exact-diff>` (`-`) | {ref}`✅ <arithmetic-inst>` | {ref}`✅ <arithmetic-zoned>` | {ref}`✅ <arithmetic-offset>` | {ref}`⚠️ <arithmetic-plain>` |
| {ref}`Calendar difference <arith-cal-diff>` (`since`/`until`) | {ref}`❌ <arithmetic-inst>` | {ref}`✅ <arithmetic-zoned>` | {ref}`✅ <arithmetic-offset>` | {ref}`✅ <arithmetic-plain>` |
| {ref}`Add/subtract exact units <arith-add-exact>` | {ref}`✅ <arithmetic-inst>` |  {ref}`✅ <arithmetic-zoned>` | {ref}`⚠️ <arithmetic-offset>` | {ref}`⚠️ <arithmetic-plain>` |
| {ref}`Add/subtract calendar units <arith-add-cal>` | {ref}`❌ <arithmetic-inst>` |  {ref}`✅ <arithmetic-zoned>` | {ref}`⚠️ <arithmetic-offset>` | {ref}`✅ <arithmetic-plain>` |

Key: ✅ fully supported · ⚠️ supported with caveats · ❌ not supported

## Operations

This section explains what each row of the table above means.
For the specifics and caveats of each type, see the
{ref}`per-type sections <arith-per-type>` below.

(arith-exact-diff)=
### Exact difference

The `-` operator computes the exact elapsed time between two points in time.
The result is always a {class}`~whenever.TimeDelta`.
Exact and local types cannot be mixed, although exact types can be mixed
with each other:

```python
>>> Instant.from_utc(2023, 12, 28, 11, 30) - ZonedDateTime(2023, 12, 28, tz="Europe/Amsterdam")
TimeDelta("PT12h30m")
```

This measures real elapsed seconds, not calendar distance.
For differences in calendar units (years, months, days), use `since()`/`until()` instead.

(arith-cal-diff)=
### Calendar difference

The `since()` and `until()` methods compute differences in calendar units.
The result is an {class}`~whenever.ItemizedDelta` (or {class}`~whenever.ItemizedDateDelta`
for date-only types), with one component per unit:

```python
>>> d2.since(d1, in_units=["years", "months", "days"])
ItemizedDelta("P3y5m14d")
```

These methods also accept exact time units (e.g. `in_units=["days", "hours"]`),
which measures elapsed time in those units.
Pass `total=` to get a single `float` directly:

```python
>>> d2.since(d1, total="days")
1261.0
```

Various rounding modes are available for the smallest unit. See {ref}`rounding` for details.

(arith-add-exact)=
(add-subtract-time)=
### Add/subtract exact units

Adding or subtracting hours, minutes, seconds, milliseconds, microseconds, or nanoseconds
shifts the datetime by an exact elapsed duration.
DST transitions do not affect the result—a shift of two hours always means two hours of
real elapsed time:

```python
>>> d = ZonedDateTime(2023, 3, 25, hour=12, tz="Europe/Amsterdam")
>>> d.add(hours=24)   # clocks spring forward overnight
ZonedDateTime("2023-03-26 13:00:00+02:00[Europe/Amsterdam]")
```

(arith-add-cal)=
### Add/subtract calendar units

Adding or subtracting years, months, weeks, or days adjusts the calendar date while
keeping the local time of day intact. This follows RFC 5545 (iCalendar) and matches
the intuitive meaning of "reschedule to tomorrow" or "move to next month."

**Month truncation.** If the result would land on a day that doesn't exist
(e.g. February 31st), it is truncated to the last valid day of the month:

```python
>>> PlainDateTime(2023, 8, 31).add(months=1)
PlainDateTime("2023-09-30 00:00:00")   # September has 30 days
```

**Days: calendar or exact?** The industry standard—and `whenever`'s default—treats days
and weeks as *calendar* units: adding a day preserves the local clock time,
not an exact 24-hour span. The difference matters during DST transitions:

```python
>>> d = ZonedDateTime(2023, 3, 25, hour=12, tz="Europe/Amsterdam")
>>> d.add(days=1)    # "same time tomorrow"—only 23 h elapsed
ZonedDateTime("2023-03-26 12:00:00+02:00[Europe/Amsterdam]")
>>> d.add(hours=24)  # exactly 24 hours later—local time shifts
ZonedDateTime("2023-03-26 13:00:00+02:00[Europe/Amsterdam]")
```

In contexts where there is no local time to preserve (e.g. {class}`~whenever.Instant`
or {class}`~whenever.TimeDelta`), days can still be used but are treated as exactly
24 hours each. A {class}`~whenever.DaysAssumed24HoursWarning` is emitted as a reminder;
pass `days_assumed_24h_ok=True` to suppress it.

```{seealso}
{ref}`the fundamentals <arithmetic2>` for the full conceptual background on exact
vs. calendar units.
```

(arith-per-type)=
## Per type

(arithmetic-inst)=
### Instant

{class}`~whenever.Instant` represents a single point in time with no calendar or
timezone context. It therefore only natively supports exact-time operations.

| Operation | Support |
| --------- | ------- |
| Exact difference (`-`) | ✅ returns {class}`~whenever.TimeDelta` |
| Calendar difference (`since`/`until`) | ❌ not available |
| Add/subtract hours, minutes, seconds, … | ✅ always unambiguous |
| Add/subtract days, weeks | ⚠️ treated as exactly 24 hours ({class}`~whenever.DaysAssumed24HoursWarning`) |
| Add/subtract years, months | ❌ not supported |

```python
>>> i = Instant.from_utc(2023, 3, 25, 12)
>>> i.add(hours=24)                           # exact—unambiguous
Instant("2023-03-26 12:00:00Z")
>>> i.add(days=1)                             # emits DaysAssumed24HoursWarning
Instant("2023-03-26 12:00:00Z")
>>> i.add(days=1, days_assumed_24h_ok=True)   # suppress
Instant("2023-03-26 12:00:00Z")
```

(arithmetic-zoned)=
### ZonedDateTime

{class}`~whenever.ZonedDateTime` is the recommended type for all arithmetic. It carries
full timezone rules and handles DST correctly — all four arithmetic operations are
fully supported.

When adding calendar units, the result may land in a DST transition.
Use `disambiguate` to control how this is resolved (default: `"compatible"`):

```python
>>> d = ZonedDateTime(2024, 10, 3, 1, 15, tz="America/Denver")
>>> d.add(months=1)                          # default: compatible
ZonedDateTime("2024-11-03 01:15:00-06:00[America/Denver]")
>>> d.add(months=1, disambiguate="raise")
Traceback (most recent call last):
  ...
whenever.RepeatedTime: 2024-11-03 01:15:00 is repeated in timezone 'America/Denver'
```

The difference between `days` and `hours` is most visible during a DST transition:

```python
>>> eve = ZonedDateTime(2025, 3, 30, hour=1, tz="Europe/Amsterdam")
>>> eve.add(days=1)    # "same time tomorrow"
ZonedDateTime("2025-03-31 01:00:00+02:00[Europe/Amsterdam]")
>>> eve.add(hours=24)  # exactly 24 hours later
ZonedDateTime("2025-03-31 02:00:00+02:00[Europe/Amsterdam]")
```

(arithmetic-offset)=
### OffsetDateTime

{class}`~whenever.OffsetDateTime` carries a fixed UTC offset, not the full timezone
rules needed to determine whether DST applies at a future point. All arithmetic
operations are supported, but any operation that crosses a DST boundary may silently
carry a stale offset. These operations emit a {class}`~whenever.StaleOffsetWarning`:

```python
>>> d = OffsetDateTime(2024, 3, 9, 13, offset=-7)
>>> d.add(hours=24)                           # emits StaleOffsetWarning
OffsetDateTime("2024-03-10 13:00:00-07:00")   # offset is stale; Denver is -06:00 here
>>> d.to_tz("America/Denver").add(hours=24)   # DST-safe alternative
ZonedDateTime("2024-03-10 14:00:00-06:00[America/Denver]")
>>> d.add(hours=24, stale_offset_ok=True)     # suppress if intentional
OffsetDateTime("2024-03-10 13:00:00-07:00")
```

```{attention}
Even in a timezone without DST, prefer {class}`~whenever.ZonedDateTime` for arithmetic.
Political decisions can change a region's UTC offset in the future.
```

:::{admonition} Why allow operations that can be wrong?
:class: hint

DST-safe arithmetic requires full timezone rules. When you have an
{class}`~whenever.OffsetDateTime` or {class}`~whenever.PlainDateTime`, that context
isn't available.

Rather than making these operations impossible—frustrating when you genuinely don't
have a timezone or know there is no DST—`whenever` allows them but emits a warning.
The warning points to the safer alternative ({class}`~whenever.ZonedDateTime`) while
leaving an escape hatch for cases where you understand the trade-off.
:::


(arithmetic-plain)=
### PlainDateTime

{class}`~whenever.PlainDateTime` has no timezone, so it cannot account for DST
in exact-time operations.

| Operation | Support |
| --------- | ------- |
| Exact difference (`-`) | ⚠️ {class}`~whenever.NaiveArithmeticWarning` |
| Calendar difference with calendar units | ✅ |
| Calendar difference with exact units (e.g. `total="hours"`) | ⚠️ {class}`~whenever.NaiveArithmeticWarning` |
| Add/subtract exact units | ⚠️ {class}`~whenever.NaiveArithmeticWarning` |
| Add/subtract calendar units | ✅ |

```python
>>> d = PlainDateTime(2023, 10, 29, 1, 30)
>>> d.add(hours=2)                                # emits NaiveArithmeticWarning
PlainDateTime("2023-10-29 03:30:00")              # may not exist in your timezone
>>> d.assume_tz("Europe/Amsterdam").add(hours=2)  # timezone-aware alternative
ZonedDateTime("2023-10-29 02:30:00+01:00[Europe/Amsterdam]")
>>> d.add(hours=2, naive_arithmetic_ok=True)      # suppress if intentional
PlainDateTime("2023-10-29 03:30:00")
```
