(arithmetic)=
# Arithmetic

The classes in `whenever` support various arithmetic operations.

## Difference

You can get the duration between two datetimes or instants with the ``-`` operator or
the {meth}`~whenever.ZonedDateTime.difference` method.
Exact and local types cannot be mixed, although exact types can be mixed with each other:

```python
>>> # difference in exact time
>>> Instant.from_utc(2023, 12, 28, 11, 30) - ZonedDateTime(2023, 12, 28, tz="Europe/Amsterdam")
TimeDelta("PT12h30m")
>>> # difference in local time
>>> PlainDateTime(2023, 12, 28, 11).difference(
...     PlainDateTime(2023, 12, 27, 11),
...     ignore_dst=True
... )
TimeDelta("PT24h")
```

(add-subtract-time)=
## Units of time

You can add or subtract various units of time from a datetime instance.

```python
>>> d = ZonedDateTime(2023, 12, 28, 11, 30, tz="Europe/Amsterdam")
>>> d.add(hours=5, minutes=30)
ZonedDateTime("2023-12-28 17:00:00+01:00[Europe/Amsterdam]")
```

The behavior arithmetic behavior is different for three categories of units:

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
Have a look at the documentation on {ref}`deltas <durations>` for more details
on arithmetic operations, as well as more advanced features.
```

(arithmetic-dst)=
## DST-safety

Date and time arithmetic can be tricky due to daylight saving time (DST)
and other timezone changes.
The API of the different classes is designed to avoid implicitly ignoring these.
The type annotations and descriptive error messages should guide you
to the correct usage.

- {class}`~whenever.Instant` has no calendar, so it doesn't support
  adding calendar units. Precise time units can be added without any complications.
- {class}`~whenever.OffsetDateTime` has a fixed offset, so it *cannot*
  account for DST and other timezone changes.
  For example, the result of adding 24 hours to `2024-03-09 13:00:00-07:00`
  is different whether the offset corresponds to Denver or Phoenix.
  To perform DST-safe arithmetic, you should convert to a {class}`~whenever.ZonedDateTime` first.
  Or, if you don't know the timezone and accept potentially incorrect results
  during DST transitions, pass `ignore_dst=True`.

  ```python
  >>> d = OffsetDateTime(2024, 3, 9, 13, offset=-7)
  >>> d.add(hours=24)
  Traceback (most recent call last):
    ...
  ImplicitlyIgnoringDST: Adjusting a fixed offset datetime implicitly ignores DST [...]
  >>> d.to_tz("America/Denver").add(hours=24)
  ZonedDateTime("2024-03-10 14:00:00-06:00[America/Denver]")
  >>> d.add(hours=24, ignore_dst=True)  # NOT recommended
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
  but, adding precise time units is only possible with explicit `ignore_dst=True`,
  because it doesn't know about DST or other timezone changes:

  ```python
  >>> d = PlainDateTime(2023, 10, 29, 1, 30)
  >>> d.add(hours=2)  # There could be a DST transition for all we know!
  Traceback (most recent call last):
    ...
  whenever.ImplicitlyIgnoringDST: Adjusting a plain datetime by time units
  ignores DST and other timezone changes. [...]
  >>> d.assume_tz("Europe/Amsterdam").add(hours=2)
  ZonedDateTime("2023-10-29 02:30:00+01:00[Europe/Amsterdam]")
  >>> d.add(hours=2, ignore_dst=True)  # NOT recommended
  PlainDateTime("2024-10-03 03:30:00")
  ```

```{attention}
Even when dealing with a timezone without DST, you should still use
{class}`~whenever.ZonedDateTime` for precise time arithmetic.
This is because political decisions in the future can also change the offset!
```

Here is a summary of the arithmetic features for each type:

|                       | Instant | OffsetDT|ZonedDT  |LocalDT  |
|:----------------------|:-------:|:-------:|:-------:|:-------:|
| Difference            | ✅      |  ✅     |   ✅    |⚠️  [^1] |
| add/subtract years, months, days   | ❌      |⚠️  [^1] |✅  [^2] |    ✅   |
| add/subtract hours, minutes, seconds  | ✅      |⚠️  [^1] |  ✅     |⚠️  [^1] |

[^1]: Only possible by passing `ignore_dst=True` to the method.
[^2]: The result by be ambiguous in rare cases. Accepts the `disambiguate` argument.


:::{admonition} Why even have `ignore_dst`? Isn't it dangerous?
:class: hint

While DST-safe arithmetic is certainly the way to go, there are cases where
it's simply not possible due to lack of information.
Because there's no way to to stop users from working around
restrictions to get the result they want, `whenever` provides the
`ignore_dst` option to at least make it explicit when this is happening.
:::


## Rounding

```{note}
The API for rounding is largely inspired by that of Temporal (JavaScript)
```

It's often useful to truncate or round a datetime to a specific unit.
For example, you might want to round a datetime to the nearest hour,
or truncate it into 15-minute intervals.

The {class}`~whenever.ZonedDateTime.round` method allows you to do this:

```python
>>> d = PlainDateTime(2023, 12, 28, 11, 32, 8)
PlainDateTime("2023-12-28 11:32:08")
>>> d.round("hour")
PlainDateTime("2023-12-28 12:00:00")
>>> d.round("minute", increment=15, mode="ceil")
PlainDateTime("2023-12-28 11:45:00")
```

See the method documentation for more details on the available options.
