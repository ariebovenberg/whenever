(arithmetic)=
# Arithmetic

The classes in `whenever` support various arithmetic operations.

## Difference

You can get the exact duration between two datetimes or instants
with the `-` operator.
Exact and local types cannot be mixed, although exact types can be mixed
with each other:

```python
>>> # difference in exact time
>>> Instant.from_utc(2023, 12, 28, 11, 30) - ZonedDateTime(2023, 12, 28, tz="Europe/Amsterdam")
TimeDelta("PT12h30m")
>>> # difference in local time (emits TimeZoneUnawareArithmeticWarning)
>>> PlainDateTime(2023, 12, 28, 11) - PlainDateTime(2023, 12, 27, 11)
TimeDelta("PT24h")
```

```{note}
Subtracting two {class}`~whenever.PlainDateTime` values emits a
{class}`~whenever.TimeZoneUnawareArithmeticWarning`, because without
timezone context the result can't account for DST transitions.
See the warning's documentation for details.
```

The result is always a {class}`~whenever.TimeDelta`, representing the exact elapsed time.
This is intentional: the `-` operator is reserved for cases
where the result is unambiguous (see {ref}`design`).
For differences in calendar units, use `since()` / `until()` below.

### Difference in calendar units

Beyond calendar units, `since()` and `until()` also support exact time units.
This lets you express differences in whatever granularity you need—for
example, a total number of minutes without rolling over to hours.

```python
>>> d1 = Date(2020, 1, 1)
>>> d2 = Date(2023, 6, 15)
>>> d2.since(d1, units=["years", "months", "days"])
ItemizedDateDelta("P3y5m14d")
>>> d1.until(d2, units=["years", "months", "days"])
ItemizedDateDelta("P3y5m14d")
```

```{tip}
The result is a dict-like structure ordered from largest to smallest unit,
so you can unpack the values directly:

    >>> years, months, days = d2.since(d1, units=["years", "months", "days"]).values()
    >>> years, months, days
    (3, 5, 14)
```

These methods are available on {class}`~whenever.Date`,
{class}`~whenever.ZonedDateTime`, {class}`~whenever.OffsetDateTime`, and
{class}`~whenever.PlainDateTime`.
If you only need a single unit, pass the `unit` parameter to get an `int` directly:

```python
>>> d2.since(d1, unit="months")
41
```

Various rounding modes are available for the smallest unit.
See {ref}`rounding` for details.

```python
>>> d2.since(d1, unit="years", round_mode="ceil")
4
```

(add-subtract-time)=
## Adding and subtracting

You can add or subtract various units of time from a datetime instance.

```python
>>> d = ZonedDateTime(2023, 12, 28, 11, 30, tz="Europe/Amsterdam")
>>> d.add(hours=5, minutes=30)
ZonedDateTime("2023-12-28 17:00:00+01:00[Europe/Amsterdam]")
```

The arithmetic behavior is different for three categories of units:

1. Adding **years and months** may result in truncation of the date.
   For example, adding a month to August 31st results in September 31st,
   which isn't valid. In such cases, the date is truncated to the last day of the month.

   ```python

   >>> d = PlainDateTime(2023, 8, 31, hour=12)
   >>> d.add(months=1)
   PlainDateTime("2023-09-30 12:00:00")
   ```

   ```{note}

   In case of dealing with {class}`~whenever.ZonedDateTime`
   there is a rare case where the resulting date might put the datetime
   in the middle of a DST transition.
   For this reason, adding years or months to these types accepts the
   `disambiguate` argument. By default, it tries to keep the same UTC offset,
   and if that's not possible, it chooses the `"compatible"` option.

   ```python

   >>> d = ZonedDateTime(2023, 9, 29, 2, 15, tz="Europe/Amsterdam")
   >>> d.add(months=1, disambiguate="raise")
   Traceback (most recent call last):
     ...
   whenever.RepeatedTime: 2023-10-29 02:15:00 is repeated in timezone 'Europe/Amsterdam'
   ```

2. Adding **days** only affects the calendar date.
   Adding a day to a datetime will not affect the local time of day.
   This is usually same as adding 24 hours, *except* during DST transitions!

   This behavior may seem strange at first, but it's the most intuitive
   when you consider that you'd expect postponing a meeting "to tomorrow"
   should still keep the same time of day, regardless of DST changes.
   For this reason, this is the behavior of the industry standard RFC 5545
   and other modern datetime libraries.

   ```python
   >>> # on the eve of a DST transition
   >>> d = ZonedDateTime(2023, 3, 25, hour=12, tz="Europe/Amsterdam")
   >>> d.add(days=1)  # a day later, still 12 o'clock
   ZonedDateTime("2023-03-26 12:00:00+02:00[Europe/Amsterdam]")
   >>> d.add(hours=24)  # 24 hours later (we skipped an hour overnight!)
   ZonedDateTime("2023-03-26 13:00:00+02:00[Europe/Amsterdam]")
   ```

   ```{note}
   As with months and years, adding days to a {class}`~whenever.ZonedDateTime`
   accepts the `disambiguate` argument,
   since the resulting date might put the datetime in a DST transition.
   ```

3. Adding **precise time units** (hours, minutes, seconds) never results
   in ambiguity. If an hour is skipped or repeated due to a DST transition,
   precise time units will account for this.

   ```python
   >>> d = ZonedDateTime(2023, 3, 25, hour=12, tz="Europe/Amsterdam")
   >>> d.add(hours=24)  # we skipped an hour overnight!
   ZonedDateTime("2023-03-26 13:00:00+02:00[Europe/Amsterdam]")
   ```

```{seealso}
For more details on working with durations as standalone objects
(reusing, converting, or comparing them), see {ref}`delta types <durations>`.
```

(arithmetic-dst)=
## DST-safety

Date and time arithmetic can be tricky due to daylight saving time (DST)
and other timezone changes.
The API of the different classes is designed to avoid implicitly ignoring these.
The type annotations and descriptive error messages should guide you
to the correct usage.

### A day is not always 24 hours

When clocks "spring forward," a calendar day is only 23 hours;
when they "fall back," it's 25. This matters when you choose between
`add(days=1)` and `add(hours=24)`:

```python
>>> # The night before Spring Forward in Amsterdam (March 30 → 31, 2025)
>>> eve = ZonedDateTime(2025, 3, 30, hour=1, tz="Europe/Amsterdam")
>>> eve.add(days=1)       # "same time tomorrow"
ZonedDateTime("2025-03-31 01:00:00+02:00[Europe/Amsterdam]")
>>> eve.add(hours=24)     # exactly 24 hours later (but 2 AM local!)
ZonedDateTime("2025-03-31 02:00:00+02:00[Europe/Amsterdam]")
```

The two results differ by one hour because the clocks jumped forward
at 2:00 AM, making that day only 23 hours long.
Use `days` when you want "same wall-clock time tomorrow,"
and `hours` when you want an exact elapsed duration.

For background on the distinction between exact and calendar units,
see {ref}`the fundamentals <arithmetic2>`.

- {class}`~whenever.Instant` has no calendar, so it doesn't support
  adding calendar units. Precise time units can be added without any complications.
- {class}`~whenever.OffsetDateTime` has a fixed offset, so it *cannot*
  account for DST and other timezone changes.
  For example, the result of adding 24 hours to `2024-03-09 13:00:00-07:00`
  is different whether the offset corresponds to Denver or Phoenix.
  To perform DST-safe arithmetic, you should convert to a {class}`~whenever.ZonedDateTime` first.

  ```python
  >>> d = OffsetDateTime(2024, 3, 9, 13, offset=-7)
  >>> d.add(hours=24)  # emits PotentiallyStaleOffsetWarning
  OffsetDateTime("2024-03-10 13:00:00-07:00")  # offset is stale; Denver is -06:00 on this date
  >>> d.to_tz("America/Denver").add(hours=24)   # DST-safe
  ZonedDateTime("2024-03-10 14:00:00-06:00[America/Denver]")
  >>> with ignore_potentially_stale_offset_warning():  # suppress if you know what you're doing
  ...     d.add(hours=24)
  OffsetDateTime("2024-03-10 13:00:00-07:00")
  ```

  ```{attention}
  Even when working in a timezone without DST, you should still use
  {class}`~whenever.ZonedDateTime`. This is because political decisions
  in the future can also change the offset!
  ```

- {class}`~whenever.ZonedDateTime` accounts for DST and other timezone changes,
  thus adding precise time units is always correct.
  Adding calendar units is also possible, but may result in ambiguity in rare cases,
  if the resulting datetime is in the middle of a DST transition:

  ```python
  >>> d = ZonedDateTime(2024, 10, 3, 1, 15, tz="America/Denver")
  ZonedDateTime("2024-10-03 01:15:00-06:00[America/Denver]")
  >>> d.add(months=1)
  ZonedDateTime("2024-11-03 01:15:00-06:00[America/Denver]")
  >>> d.add(months=1, disambiguate="raise")
  Traceback (most recent call last):
    ...
  whenever.RepeatedTime: 2024-11-03 01:15:00 is repeated in timezone 'America/Denver'
  ```

- {class}`~whenever.PlainDateTime` doesn't have a timezone,
  so it can't account for DST or other clock changes.
  Calendar units can be added without any complications,
  but adding or subtracting exact time units, or calculating the difference
  between two plain datetimes, will emit a {class}`~whenever.TimeZoneUnawareArithmeticWarning`:

  ```python
  >>> d = PlainDateTime(2023, 10, 29, 1, 30)
  >>> d.add(hours=2)  # emits TimeZoneUnawareArithmeticWarning
  PlainDateTime("2023-10-29 03:30:00")  # 03:30 doesn't exist in Amsterdam on this date
  >>> d.assume_tz("Europe/Amsterdam").add(hours=2)   # timezone-aware
  ZonedDateTime("2023-10-29 02:30:00+01:00[Europe/Amsterdam]")
  >>> with ignore_timezone_unaware_arithmetic_warning():  # suppress if you know what you're doing
  ...     d.add(hours=2)
  PlainDateTime("2023-10-29 03:30:00")
  ```

```{attention}
Even when dealing with a timezone without DST, you should still use
{class}`~whenever.ZonedDateTime` for precise time arithmetic.
This is because political decisions in the future can also change the offset!
```

Here is a summary of the arithmetic features for each type:

|                       | Instant | OffsetDT|ZonedDT  |PlainDT  |
|:----------------------|:-------:|:-------:|:-------:|:-------:|
| Difference (`-`)      | ✅      |  ✅     |   ✅    |⚠️  [^1] |
| `since()` / `until()` | ❌      |  ✅ [^1]|   ✅    |⚠️  [^1] |
| add/subtract years, months, days   | ❌      |⚠️  [^1] |✅  [^2] |    ✅   |
| add/subtract hours, minutes, seconds  | ✅      |⚠️  [^1] |  ✅     |⚠️  [^1] |

[^1]: Emits a warning ({class}`~whenever.PotentiallyStaleOffsetWarning` for ``OffsetDateTime``,
    {class}`~whenever.TimeZoneUnawareArithmeticWarning` for ``PlainDateTime``).
    Suppress with the corresponding ``ignore_*_warning()`` context manager
    once you have confirmed the result is correct for your use case.
[^2]: The result may be ambiguous in rare cases. Accepts the ``disambiguate`` argument.


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
