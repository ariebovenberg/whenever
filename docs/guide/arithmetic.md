(arithmetic)=
# Arithmetic

The classes in `whenever` support various arithmetic operations.

## Difference

### Exact time

You can get the exact duration between two datetimes or instants
with the `-` operator.
Exact and local types cannot be mixed, although exact types can be mixed
with each other:

```python
>>> # difference in exact time
>>> Instant.from_utc(2023, 12, 28, 11, 30) - ZonedDateTime(2023, 12, 28, tz="Europe/Amsterdam")
TimeDelta("PT12h30m")
>>> # difference in local time (emits NaiveArithmeticWarning)
>>> PlainDateTime(2023, 12, 28, 11) - PlainDateTime(2023, 12, 27, 11)
TimeDelta("PT24h")
```

```{note}
Subtracting two {class}`~whenever.PlainDateTime` values emits a
{class}`~whenever.NaiveArithmeticWarning`, because without
timezone context the result can't account for DST transitions.
See {ref}`arithmetic-dst` for details.
```

The result is always a {class}`~whenever.TimeDelta`, representing the exact elapsed time.
This is intentional: the `-` operator is reserved for cases
where the result is unambiguous (see {ref}`design`).
For differences in calendar units, use `since()` / `until()` below.

### In specific (calendar) units

For calendar differences, the `since()` and `until()` methods are available.
These methods can express the difference in various calendar units,
such as years, months, and days, while accounting for the varying lengths of these units.

```python
>>> d1 = Date(2020, 1, 1)
>>> d2 = Date(2023, 6, 15)
>>> d2.since(d1, in_units=["years", "months", "days"])
ItemizedDateDelta("P3y5m14d")
>>> d1.until(d2, in_units=["years", "months", "days"])
ItemizedDateDelta("P3y5m14d")
```

Beyond calendar units, `since()` and `until()` also support exact time units.
This lets you express differences in whatever granularity you need—for
example, a total number of minutes without rolling over to hours:

```python
>>> d1 = OffsetDateTime(2020, 1, 1, 12, offset=-7)
>>> d2 = OffsetDateTime(2020, 1, 3, 15, 30, offset=-7)
>>> d2.since(d1, in_units=["days", "hours"])
ItemizedDelta("P2d3h")
```

:::{tip}
The result is a dict-like structure ordered from largest to smallest unit,
so you can unpack the values directly:

```python
>>> years, months, days = d2.since(d1, in_units=["years", "months", "days"]).values()
>>> years, months, days
(3, 5, 14)
```
:::

These methods are available on {class}`~whenever.Date`,
{class}`~whenever.ZonedDateTime`, {class}`~whenever.OffsetDateTime`, and
{class}`~whenever.PlainDateTime`.
If you only need a single unit, pass the `total` parameter to get a `float` directly:

```python
>>> d2.since(d1, total="months")
41.46666666667
```

```{note}
For calendar units (years, months), the fractional part is based on
the number of days in the surrounding period, not a fixed conversion factor.
For example, 6 months starting from January 1 covers 181 days out of a
365-day year, giving approximately 0.496 years — not exactly 0.5.
```

Various rounding modes are available for the smallest unit when using `in_units`.
See {ref}`rounding` for details.

(add-subtract-time)=
## Adding and subtracting

You can add or subtract various units of time from a datetime instance.

```python
>>> d = ZonedDateTime(2023, 12, 28, 11, 30, tz="Europe/Amsterdam")
>>> d.add(hours=5, minutes=30)
ZonedDateTime("2023-12-28 17:00:00+01:00[Europe/Amsterdam]")
```

The arithmetic behavior differs across three categories of units:

1. Adding **years and months** adjusts the calendar date. If the resulting day
   doesn't exist, it's truncated to the last valid day of the month:

   ```python
   >>> d = PlainDateTime(2023, 8, 31, hour=12)
   >>> d.add(months=1)
   PlainDateTime("2023-09-30 12:00:00")
   ```

   ```{note}
   On {class}`~whenever.ZonedDateTime`, the result may land in a DST transition.
   Use the `disambiguate` argument to control how this is resolved
   (default: `"compatible"`). See {ref}`arithmetic-dst`.
   ```

2. Adding **days** advances the calendar date, keeping the local time of day intact.
   This is the behavior you'd expect when postponing something "to tomorrow"—
   the time stays the same regardless of DST changes (following RFC 5545).
   It is *not* the same as adding 24 hours during a DST transition—see
   {ref}`arithmetic-dst` for the distinction.

   ```python
   >>> d = ZonedDateTime(2023, 3, 25, hour=12, tz="Europe/Amsterdam")
   >>> d.add(days=1)  # a day later, still 12 o'clock
   ZonedDateTime("2023-03-26 12:00:00+02:00[Europe/Amsterdam]")
   ```

   ```{note}
   As with months and years, adding days to a {class}`~whenever.ZonedDateTime`
   accepts the `disambiguate` argument,
   since the resulting date might fall in a DST transition.
   ```

3. Adding **hours, minutes, seconds** (and smaller) shifts the datetime by
   the exact elapsed duration:

   ```python
   >>> d = ZonedDateTime(2023, 3, 25, hour=12, tz="Europe/Amsterdam")
   >>> d.add(hours=24)  # clocks sprang forward overnight
   ZonedDateTime("2023-03-26 13:00:00+02:00[Europe/Amsterdam]")
   ```

```{seealso}
For more details on working with durations as standalone objects
(reusing, converting, or comparing them), see {ref}`delta types <durations>`.
```

(arithmetic-dst)=
## Days aren't always 24 hours

Due to DST transitions, a calendar day can be 23 or 25 hours long[^1].
`whenever`'s API surfaces this where it matters—operations that may silently
produce incorrect results emit a warning instead.

The difference is most visible when choosing between `add(days=1)` and
`add(hours=24)`. When clocks spring forward:

```python
>>> # The night before Spring Forward in Amsterdam (March 30 → 31, 2025)
>>> eve = ZonedDateTime(2025, 3, 30, hour=1, tz="Europe/Amsterdam")
>>> eve.add(days=1)       # "same time tomorrow"
ZonedDateTime("2025-03-31 01:00:00+02:00[Europe/Amsterdam]")
>>> eve.add(hours=24)     # exactly 24 hours later (but 2 AM local!)
ZonedDateTime("2025-03-31 02:00:00+02:00[Europe/Amsterdam]")
```

Use `days` when you want "same wall-clock time tomorrow,"
and `hours` when you want an exact elapsed duration.

For background on the distinction between exact and calendar units,
see {ref}`the fundamentals <arithmetic2>`.

**ZonedDateTime** always handles DST correctly. Adding days preserves
the local time of day; adding hours/minutes/seconds advances by exact
elapsed time. When adding years, months, or days, the result may land
in a DST transition — use `disambiguate` to control resolution
(default: `"compatible"`):

```python
>>> d = ZonedDateTime(2024, 10, 3, 1, 15, tz="America/Denver")
>>> d.add(months=1, disambiguate="raise")
Traceback (most recent call last):
  ...
whenever.RepeatedTime: 2024-11-03 01:15:00 is repeated in timezone 'America/Denver'
```

**OffsetDateTime** carries a fixed UTC offset, not full timezone rules.
It can't know whether DST applies after a shift, so arithmetic that crosses
a DST boundary may silently preserve an incorrect offset.
These operations emit a {class}`~whenever.StaleOffsetWarning`:

```python
>>> d = OffsetDateTime(2024, 3, 9, 13, offset=-7)
>>> d.add(hours=24)  # emits StaleOffsetWarning
OffsetDateTime("2024-03-10 13:00:00-07:00")  # offset is stale; Denver is -06:00 on this date
>>> d.to_tz("America/Denver").add(hours=24)   # DST-safe
ZonedDateTime("2024-03-10 14:00:00-06:00[America/Denver]")
>>> d.add(hours=24, stale_offset_ok=True)  # suppress if intentional
OffsetDateTime("2024-03-10 13:00:00-07:00")
```

{class}`~whenever.Instant` has no calendar, so it only supports exact time units,
which always work correctly.

```{attention}
Even in a timezone without DST, prefer {class}`~whenever.ZonedDateTime` over
{class}`~whenever.OffsetDateTime` for arithmetic. Political decisions can change
a region's offset in the future.
```

**PlainDateTime** has no timezone, so exact-time arithmetic can't account for
DST transitions. Adding or subtracting hours/minutes/seconds—or measuring an
exact difference—emits a {class}`~whenever.NaiveArithmeticWarning`:

```python
>>> d = PlainDateTime(2023, 10, 29, 1, 30)
>>> d.add(hours=2)  # emits NaiveArithmeticWarning
PlainDateTime("2023-10-29 03:30:00")  # 03:30 doesn't exist in Amsterdam on this date
>>> d.assume_tz("Europe/Amsterdam").add(hours=2)   # timezone-aware
ZonedDateTime("2023-10-29 02:30:00+01:00[Europe/Amsterdam]")
>>> d.add(hours=2, naive_arithmetic_ok=True)  # suppress if intentional
PlainDateTime("2023-10-29 03:30:00")
```

When using `since()` / `until()` on a `PlainDateTime`, the warning is
emitted only for exact time units (e.g. ``total="hours"``).
Calendar units (e.g. ``total="days"``) are always safe.

### Summary

|                       | Instant | OffsetDT|ZonedDT  |PlainDT  |
|:----------------------|:-------:|:-------:|:-------:|:-------:|
| Difference (`-`)      | ✅      |  ✅     |   ✅    |⚠️  [^4] |
| `since()` / `until()` (calendar units) | ❌      |  ✅  |   ✅    |    ✅   |
| `since()` / `until()` (exact units)    | ❌      |  ✅  |   ✅    |⚠️  [^4] |
| add/subtract years, months, days       | ❌      |⚠️  [^2] |✅  [^3] |    ✅   |
| add/subtract hours, minutes, seconds   | ✅      |⚠️  [^2] |  ✅     |⚠️  [^4] |

[^2]: Emits a {class}`~whenever.StaleOffsetWarning`
[^3]: The result may be ambiguous in rare cases. Accepts the ``disambiguate`` argument.
[^4]: Emits a {class}`~whenever.NaiveArithmeticWarning`


:::{admonition} Why are these operations allowed at all if they can be wrong?
:class: hint

DST-safe arithmetic requires a timezone. When you work with
{class}`~whenever.OffsetDateTime` or {class}`~whenever.PlainDateTime`,
that timezone context is simply not available.

Rather than making these operations impossible (which would be frustrating
when you genuinely don't have a timezone, or when you *know* there is no DST),
`whenever` allows them but emits a warning. The warning points you to the
safer alternative—using {class}`~whenever.ZonedDateTime`—while still giving
you an escape hatch if you understand the trade-off.
:::

[^1]: In rare cases, timezone changes like DST can even result in day lengths
      with non-integer hour counts.
