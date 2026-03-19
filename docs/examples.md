# Examples

```{eval-rst}
.. currentmodule:: whenever
```

This page contains small, practical examples of using `whenever`.
For more in-depth information, refer to the {ref}`guide`.

## Get the current time in UTC

```python
>>> from whenever import Instant
>>> Instant.now()
Instant("2025-04-19 19:02:56.39569Z")
```

## Convert UTC to the system timezone

```python
>>> from whenever import Instant
>>> i = Instant.now()
>>> i.to_system_tz()
ZonedDateTime("2025-04-19 21:02:56.39569+02:00[Europe/Berlin]")
```

## Convert from one timezone to another

```python
>>> from whenever import ZonedDateTime
>>> d = ZonedDateTime(2025, 4, 19, hour=15, tz="America/New_York")
>>> d.to_tz("Europe/Berlin")
ZonedDateTime("2025-04-19 21:00:00+02:00[Europe/Berlin]")
```

## Convert a date to datetime

```python
>>> from whenever import Date, Time
>>> date = Date(2023, 10, 1)
>>> date.at(Time(12, 30))
PlainDateTime("2023-10-01 12:30:00")
```

## Calculate somebody's age

```python
>>> from whenever import Date
>>> birth_date = Date(2023, 11, 2)
>>> today = Date.today_in_system_tz()
>>> today.since(birth_date, total="years")
2.3753424657534246
>>> years, months = today.since(birth_date, in_units=("years", "months")).values()
(2, 4)
```

## Assign a timezone to a datetime

```python
>>> from whenever import PlainDateTime
>>> datetime = PlainDateTime(2023, 10, 1, 12, 30)
>>> datetime.assume_tz("America/New_York")
ZonedDateTime("2023-10-01 12:30:00-04:00[America/New_York]")
```

## Integrate with the standard library

```python
>>> import datetime
>>> py_dt = datetime.datetime.now(datetime.UTC)
>>> from whenever import Instant
>>> # create an Instant from any aware datetime
>>> i = Instant(py_dt)
Instant("2025-04-19 19:02:56.39569Z")
>>> zdt = i.to_tz("America/New_York")
ZonedDateTime("2025-04-19 15:02:56.39569-04:00[America/New_York]")
>>> # convert back to the standard library
>>> zdt.to_stdlib()
datetime.datetime(2025, 4, 19, 15, 2, 56, 395690, tzinfo=ZoneInfo('America/New_York'))
```

## Parse an ISO8601 datetime string

```python
>>> from whenever import Instant
>>> Instant("2025-04-19T19:02+04:00")
Instant("2025-04-19 15:02:00Z")
```

Or, if you want to keep the offset value:

```python
>>> from whenever import OffsetDateTime
>>> OffsetDateTime("2025-04-19T19:02+04:00")
OffsetDateTime("2025-04-19 19:02:00+04:00")
```

## Determine the start of the hour

```python
>>> d = ZonedDateTime.now("America/New_York")
ZonedDateTime("2025-04-19 15:46:41-04:00[America/New_York]")
>>> d.round("hour", mode="floor")
ZonedDateTime("2025-04-19 15:00:00-04:00[America/New_York]")
```

The {meth}`~whenever.ZonedDateTime.round` method can be used for so much more!
See its documentation for more details.

## Get the current unix timestamp

```python
>>> from whenever import Instant
>>> i = Instant.now()
>>> i.timestamp()
1745090505
```

Note that this is always in whole seconds.
If you need additional precision:

```python
>>> i.timestamp_millis()
1745090505629
>>> i.timestamp_nanos()
1745090505629346833
```

## Get a date and time from a timestamp

```python
>>> from whenever import ZonedDateTime
>>> ZonedDateTime.from_timestamp(1745090505, tz="America/New_York")
ZonedDateTime("2025-04-19 15:21:45-04:00[America/New_York]")
```

## Find the duration between two datetimes

```python
>>> from whenever import ZonedDateTime
>>> d = ZonedDateTime(2025, 1, 3, hour=15, tz="America/New_York")
>>> d2 = ZonedDateTime(2025, 1, 5, hour=8, minute=24, tz="Europe/Paris")
>>> d2 - d
TimeDelta("PT35h24m")
```

## Move a date by six months

```python
>>> from whenever import Date
>>> date = Date(2023, 10, 31)
>>> date.add(months=6)
Date("2024-04-30")
```

## Discard fractional seconds

```python
>>> from whenever import Instant
>>> i = Instant.now()
Instant("2025-04-19 19:02:56.39569Z")
>>> i.round()
Instant("2025-04-19 19:02:56Z")
```

Use the arguments of {meth}`~whenever.Instant.round` to customize the rounding behavior.

## Handling ambiguous datetimes

Due to daylight saving time, some date and time values don't exist,
or occur twice in a given timezone.
In the example below, the clock was set forward by one hour at 2:00 AM,
so the time 2:30 AM doesn't exist.

```python
>>> from whenever import ZonedDateTime
>>> # set up the date and time for the example
>>> dt = PlainDateTime(2023, 2, 26, hour=2, minute=30)
```

The default behavior (take the first offset) is consistent with other
modern libraries and industry standards:

```python
>>> zoned = dt.assume_tz("Europe/Berlin")
ZonedDateTime("2023-02-26 03:30:00+02:00[Europe/Berlin]")
```

But it's also possible to "refuse to guess" and choose the "earlier"
or "later" occurrence explicitly:

```python
>>> zoned = dt.assume_tz("Europe/Berlin", disambiguate="earlier")
ZonedDateTime("2023-02-26 01:30:00+02:00[Europe/Berlin]")
```

Or, you can even reject ambiguous datetimes altogether:

```python
>>> zoned = dt.assume_tz("Europe/Berlin", disambiguate="raise")
```

## "Same time tomorrow" across DST

Adding a day keeps the wall-clock time, even when a DST transition
makes the day shorter or longer than 24 hours:

```python
>>> from whenever import ZonedDateTime
>>> # The night before Spring Forward in Amsterdam
>>> eve = ZonedDateTime(2025, 3, 30, hour=1, tz="Europe/Amsterdam")
>>> eve.add(days=1)     # same wall-clock time
ZonedDateTime("2025-03-31 01:00:00+02:00[Europe/Amsterdam]")
>>> eve.add(hours=24)   # exactly 24 hours — one hour later on the clock
ZonedDateTime("2025-03-31 02:00:00+02:00[Europe/Amsterdam]")
```

## Countdown to New Year's

```python
>>> from whenever import ZonedDateTime
>>> now = ZonedDateTime(2025, 12, 28, hour=14, tz="America/New_York")
>>> new_year = ZonedDateTime(2026, 1, 1, tz="America/New_York")
>>> days, hours = new_year.since(now, in_units=("days", "hours")).values()
(3, 10)
```

## Flight itinerary across time zones

```python
>>> from whenever import OffsetDateTime
>>> departure = OffsetDateTime(2025, 7, 1, hour=9, offset=-4)   # New York
>>> arrival = OffsetDateTime(2025, 7, 1, hour=22, offset=2)     # Amsterdam
>>> flight_time = arrival - departure
>>> flight_time.total("hours")
7.0
```

## Recurring monthly event

When a monthly recurrence lands on a day that doesn't exist in the
target month, the date is truncated to the last valid day:

```python
>>> from whenever import Date
>>> meeting = Date(2025, 1, 31)
>>> meeting.add(months=1)  # February doesn't have 31 days
Date("2025-02-28")
>>> meeting.add(months=2)
Date("2025-03-31")
```

## Sort a list of datetimes

All *exact types* can be compared and sorted amongst each other:

```python
>>> from whenever import Instant, ZonedDateTime, OffsetDateTime
>>> times = [
...     ZonedDateTime(2025, 6, 1, hour=12, tz="Asia/Tokyo"),
...     Instant.from_utc(2025, 6, 1, hour=2),
...     OffsetDateTime(2025, 6, 1, hour=6, offset=4),
... ]
>>> sorted(times)  # all represent the same moment—sorted by the underlying instant
[...]
```

"Plain" datetimes cannot be mixed with exact types. 
This will be flagged by type checking.

## Custom format patterns

For formats beyond ISO 8601, use pattern strings:

```python
>>> from whenever import Date, PlainDateTime, OffsetDateTime
>>> Date.parse("15 Mar 2024", format="DD MMM YYYY")
Date("2024-03-15")
>>> PlainDateTime.parse("03/15/2024 02:30 PM", format="MM/DD/YYYY ii:mm aa")
PlainDateTime("2024-03-15 14:30:00")
>>> OffsetDateTime.parse("2024-03-15 14:30+02:00", format="YYYY-MM-DD hh:mmxxx")
OffsetDateTime("2024-03-15 14:30:00+02:00")
```

If your input doesn't include an offset or timezone, parse with
{meth}`PlainDateTime.parse` and convert:

```python
>>> from whenever import PlainDateTime
>>> pdt = PlainDateTime.parse("2024-03-15 14:30", format="YYYY-MM-DD hh:mm")
>>> pdt.assume_utc()
Instant("2024-03-15 14:30:00Z")
```

It also integrates nicely with the standard library's formatting protocol
(`__format__`), so you can use pattern strings in f-strings:

```python
>>> from whenever import Date
>>> d = Date(2024, 3, 15)
>>> f"{d:DD/MM/YYYY}"
'15/03/2024'
>>> f"{d}"  # empty spec falls back to str()
'2024-03-15'
```

## Roundtrip: datetime → string → datetime

Every `whenever` type has a reversible string representation:

```python
>>> from whenever import ZonedDateTime
>>> d = ZonedDateTime(2025, 6, 15, hour=14, minute=30, tz="Europe/Amsterdam")
>>> s = str(d)
>>> s
'2025-06-15 14:30:00+02:00[Europe/Amsterdam]'
>>> ZonedDateTime(s) == d
True
```

For ISO 8601 exchange:

```python
>>> iso = d.format_iso()
>>> ZonedDateTime.parse_iso(iso) == d
True
```
