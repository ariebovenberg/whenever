---
myst:
  html_meta:
    description: >-
      Adding, subtracting, and diffing datetimes in whenever: the - operator
      versus since() and until(), exact versus calendar units, and what each type
      supports.
---

(arithmetic)=
# Arithmetic

```{eval-rst}
.. currentmodule:: whenever
```

`whenever` supports differences, additions, and subtractions across all its
datetime and instant types. This page is a practical guide to those operations.

```{tip}
For the conceptual background on exact vs. calendar units,
see {ref}`the fundamentals <arithmetic2>`.
For working with the delta types directly,
see {ref}`delta types <durations>`.
```

## Simple examples

```python
>>> ZonedDateTime("2023-12-28 11:30[Europe/Amsterdam]").add(hours=5, minutes=30)
ZonedDateTime("2023-12-28 17:00:00+01:00[Europe/Amsterdam]")

>>> Instant("2023-12-28 11:30Z") - ZonedDateTime(2023, 12, 28, tz="Europe/Amsterdam")
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
| {ref}`Exact arithmetic (difference) <arith-exact-diff>` | {ref}`✅ <arithmetic-inst>` | {ref}`✅ <arithmetic-zoned>` | {ref}`✅ <arithmetic-offset>` | {ref}`⚠️ <arithmetic-plain>` |
| {ref}`Calendar arithmetic (difference) <arith-cal-diff>` | {ref}`❌ <arithmetic-inst>` | {ref}`✅ <arithmetic-zoned>` | {ref}`⚠️ <arithmetic-offset>` | {ref}`✅ <arithmetic-plain>` |
| {ref}`Exact arithmetic (add/subtract) <arith-add-exact>` | {ref}`✅ <arithmetic-inst>` |  {ref}`✅ <arithmetic-zoned>` | {ref}`⚠️ <arithmetic-offset>` | {ref}`⚠️ <arithmetic-plain>` |
| {ref}`Calendar arithmetic (add/subtract) <arith-add-cal>` | {ref}`❌ <arithmetic-inst>`[^instant-days] |  {ref}`✅ <arithmetic-zoned>` | {ref}`⚠️ <arithmetic-offset>` | {ref}`✅ <arithmetic-plain>` |

Key: ✅ fully supported · ⚠️ supported with caveats · ❌ not supported

[^instant-days]: `days` and `weeks` are accepted as exact 24-hour units,
    with {class}`DaysAssumed24HoursWarning`.

## `-`/`difference()` vs. `since()`/`until()`

The `-` operator (and its method equivalent, `difference()`) always returns the
**exact elapsed time** as a {class}`TimeDelta`. It works between any two
exact-time types ({class}`Instant`, {class}`ZonedDateTime`,
{class}`OffsetDateTime`), which may be mixed freely:

```python
>>> d1 = ZonedDateTime(2020, 1, 1, tz="Europe/Amsterdam")
>>> d2 = ZonedDateTime(2023, 6, 15, tz="Europe/Amsterdam")
>>> d2 - d1
TimeDelta("PT30263h")
```

`since()` and `until()` are more flexible: you choose the **units** and get back
either a `float` (with `total=`) or an {class}`ItemizedDelta`
(with `in_units=`):

```python
>>> d2.since(d1, total="days")                          # float: calendar days
1261.0
>>> d2.since(d1, in_units=["years", "months", "days"])  # ItemizedDelta
ItemizedDelta("P3y5m14d")
```

`until()` is the direction-reversed counterpart of `since()`:
`a.until(b)` is equivalent to `b.since(a)`.

Both methods work with exact units (`hours`, `minutes`, `seconds`, `nanoseconds`)
*and* calendar units (`years`, `months`, `weeks`, `days`).
The `-` operator only returns exact elapsed time.

{class}`Instant` has no `since()`/`until()`: it has no calendar, and
`(a - b).total("hours")` already spells an exact total.
{class}`Date` has no `difference()`: two dates have no single exact
difference, only a difference in the calendar units you choose.

## Exact vs. calendar units

This section explains what the rows in the overview table mean.
For the specifics and caveats of each type, see the
{ref}`per-type sections <arith-per-type>` below.

(arith-exact-diff)=
(arith-add-exact)=
(add-subtract-time)=
### Exact units

*Exact units* — `hours`, `minutes`, `seconds`, `milliseconds`, `microseconds`,
and `nanoseconds` — represent fixed durations on the global timeline.
DST transitions never affect them: two hours is always two hours of real elapsed time:

```python
>>> d = ZonedDateTime(2023, 3, 25, hour=12, tz="Europe/Amsterdam")
>>> d.add(hours=24)   # clocks spring forward overnight—local time shifts by 1 h
ZonedDateTime("2023-03-26 13:00:00+02:00[Europe/Amsterdam]")
```

{class}`PlainDateTime` has no time zone context, so exact-unit operations
emit a {class}`NaiveArithmeticWarning`.
The `+` and `-` operators warn as the methods do but take no escape:
to accept a warning for one call, use `add()`, `subtract()`, or
`difference()` with its `_ok` keyword.

(arith-cal-diff)=
(arith-add-cal)=
### Calendar units

*Calendar units* — `years`, `months`, `weeks`, `days` — measure calendar distance
and preserve the local time of day. By convention (RFC 5545), adding a day keeps the
clock at the same time, even across a DST transition:

```python
>>> d = ZonedDateTime(2023, 3, 25, hour=12, tz="Europe/Amsterdam")
>>> d.add(days=1)    # "same time tomorrow"—only 23 h elapsed due to DST
ZonedDateTime("2023-03-26 12:00:00+02:00[Europe/Amsterdam]")
>>> d.add(hours=24)  # exactly 24 hours later—local time shifts
ZonedDateTime("2023-03-26 13:00:00+02:00[Europe/Amsterdam]")
>>> d1 = ZonedDateTime(2020, 1, 1, tz="Europe/Amsterdam")
>>> d2 = ZonedDateTime(2023, 6, 15, tz="Europe/Amsterdam")
>>> d2.since(d1, in_units=["years", "months", "days"])
ItemizedDelta("P3y5m14d")
```

**Clamping.** If the result falls on a day that doesn't exist in a month,
it is {term}`clamped <clamping>` to the last valid day:

```python
>>> PlainDateTime(2023, 8, 31).add(months=1)
PlainDateTime("2023-09-30 00:00:00")   # September has 30 days
```

**Unit order.** `add()` and `subtract()` apply years and months first
(clamped), then weeks and days, all in local time; then the exact units
move the instant. `subtract()` is `add()` of the negated components.
One consequence: across a transition,
`x.add(days=1, hours=24).subtract(days=1, hours=24)` is not `x`.

Various rounding modes are available for the smallest unit in `since()`/`until()`.
See {ref}`rounding` for details.

```{seealso}
{ref}`the fundamentals <arithmetic2>` for the full conceptual background on exact
vs. calendar units.
```

(arith-per-type)=
## Per type

(arithmetic-inst)=
### Instant

{class}`Instant` represents a single point in time with no calendar or
time zone context. It only supports exact units: `hours`, `minutes`, `seconds`,
`milliseconds`, `microseconds`, and `nanoseconds`.

```python
>>> i = Instant("2023-03-25T12:00Z")
>>> i.add(hours=24)
Instant("2023-03-26 12:00:00Z")
>>> i2 = Instant("2023-03-28 06:00Z")
>>> i2 - i
TimeDelta("PT66h")
```

`years` and `months` are not available. `weeks` and `days` can be converted to
exact units, but emit a {class}`DaysAssumed24HoursWarning`:

```python
>>> i.add(days=1)                                # emits DaysAssumed24HoursWarning
Instant("2023-03-26 12:00:00Z")
>>> i.add(days=1, days_assumed_24h_ok=True)      # explicitly means 24 hours
Instant("2023-03-26 12:00:00Z")
```

Exact weeks are acknowledged with the same `days_assumed_24h_ok`. See
{ref}`the rounding distinction <rounding-instant-day>`.

Because {class}`Instant` has no calendar or time zone context,
it doesn't support `since()`/`until()`.
Use {meth}`~TimeDelta.in_units`/{meth}`~TimeDelta.total` 
on the result of `-`/`difference()` instead:

```python
>>> i2.difference(i).total("hours")
66.0
>>> i2.difference(i).in_units(["days", "hours"], days_assumed_24h_ok=True)
ItemizedDelta("P2dT18h")
```

(arithmetic-zoned)=
### ZonedDateTime

{class}`ZonedDateTime` is the recommended type for all arithmetic. It carries
full time zone rules and handles DST correctly — all four arithmetic operations are
fully supported.

```python
>>> d1 = ZonedDateTime(2020, 1, 1, tz="Europe/Amsterdam")
>>> d2 = ZonedDateTime(2023, 6, 15, tz="Europe/Amsterdam")
>>> d1.add(hours=5, minutes=30)
ZonedDateTime("2020-01-01 05:30:00+01:00[Europe/Amsterdam]")
>>> d2.since(d1, total="days")
1261.0
>>> d2.since(d1, in_units=["years", "months", "days"])
ItemizedDelta("P3y5m14d")
```

When using `since()`/`until()` with calendar units (`years`, `months`, `weeks`,
`days`), both datetimes must share the same time zone — or a {exc}`ValueError` is
raised. Exact units work freely across different time zones:

```python
>>> tokyo = ZonedDateTime(2023, 6, 15, tz="Asia/Tokyo")
>>> d2.since(tokyo, total="hours")         # exact units: works across time zones
7.0
>>> d2.since(tokyo, total="days")          # calendar units: raises ValueError
Traceback (most recent call last):
  ...
ValueError: calendar units require the same time zone, got 'Europe/Amsterdam' and 'Asia/Tokyo'
```

When adding calendar units, the result may land in a DST transition.
Pass `disambiguation` explicitly to control how this is resolved:

```python
>>> d = ZonedDateTime(2024, 10, 3, 1, 15, tz="America/Denver")
>>> d.add(months=1, disambiguation="compatible")
ZonedDateTime("2024-11-03 01:15:00-06:00[America/Denver]")
>>> d.add(months=1, disambiguation="raise")
Traceback (most recent call last):
  ...
whenever.RepeatedTime: 2024-11-03 01:15:00 is repeated in time zone 'America/Denver'
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

Arithmetic is defined, but an {class}`OffsetDateTime` has no regional rules
with which to update its stored offset. Operations that preserve an offset
which may no longer apply in its original regional context emit
{class}`StaleOffsetWarning`. See
{ref}`offset-datetime-guidance` for the complete explanation, examples, and
how to suppress it.

For `since()`/`until()`, calendar units (`years`, `months`, `weeks`, `days`) require
both datetimes to carry the same UTC offset — or a {exc}`ValueError` is raised.
Exact units work freely across different offsets.
Whole calendar units are correct in any time zone, but a remainder in exact
units after them (`in_units` mixing the two kinds, or `total=` of a calendar
unit) is computed with the offset held fixed, so those forms emit
{class}`StaleOffsetWarning`; whole-unit `in_units`, an exact `total=`, `-`,
and `difference()` stay silent.
Pass `stale_offset_ok=True` when the fixed offset is intentional:

```python
>>> d1 = OffsetDateTime("2024-06-01 10:00+00")    # 10:00 UTC
>>> d2 = OffsetDateTime("2024-06-01 14:00+02")    # 12:00 UTC
>>> d2.since(d1, total="hours")                   # exact units: works
2.0
>>> d2.since(d1, total="days")                    # calendar units: raises ValueError
Traceback (most recent call last):
  ...
ValueError: calendar units require the same offset, got +02:00 and +00:00
```

```{attention}
Even in a time zone without DST, prefer {class}`ZonedDateTime` for arithmetic.
Political decisions can change a region's UTC offset in the future.
```

:::{admonition} Why allow operations that can be wrong?
:class: hint

DST-safe arithmetic requires full time zone rules. When you have an
{class}`OffsetDateTime` or {class}`PlainDateTime`, that context
isn't available.

Rather than making these operations impossible—frustrating when you genuinely don't
have a time zone or know there is no DST—`whenever` allows them but emits a warning.
The warning points to the safer alternative ({class}`ZonedDateTime`) while
leaving a {term}`call-local escape` for cases where you understand the trade-off.
:::


(arithmetic-plain)=
### PlainDateTime

{class}`PlainDateTime` has no time zone, so it cannot account for DST
in exact-time operations. Calendar units (`years`, `months`, `weeks`, `days`) are
fully supported without any caveats. Exact units — including the `-` operator and
`since()`/`until()` with time-of-day units — emit
{class}`NaiveArithmeticWarning`:

```python
>>> d1 = PlainDateTime(2023, 1, 1)
>>> d2 = PlainDateTime(2023, 4, 15)
>>> d2.since(d1, in_units=["months", "days"])           # calendar: no warning
ItemizedDelta("P3m14d")
>>> d2.since(d1, total="hours")                         # exact: NaiveArithmeticWarning
2496.0
>>> d2.since(d1, total="hours", naive_arithmetic_ok=True)  # suppress
2496.0
```

```python
>>> d = PlainDateTime(2023, 10, 29, 1, 30)
>>> d.add(hours=2)                                # emits NaiveArithmeticWarning
PlainDateTime("2023-10-29 03:30:00")              # may not exist in your time zone
>>> d.assume_tz("Europe/Amsterdam").add(hours=2)  # alternative that respects the time zone
ZonedDateTime("2023-10-29 02:30:00+01:00[Europe/Amsterdam]")
>>> d.add(hours=2, naive_arithmetic_ok=True)      # suppress if intentional
PlainDateTime("2023-10-29 03:30:00")
```
