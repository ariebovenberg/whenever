# Examples

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
>>> today.since(birth_date, unit="years")
2
>>> years, months = today.since(birth_date, units=("years", "months"))
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
>>> i = Instant.from_py_datetime(py_dt)
Instant("2025-04-19 19:02:56.39569Z")
>>> zdt = i.to_tz("America/New_York")
ZonedDateTime("2025-04-19 15:02:56.39569-04:00[America/New_York]")
>>> # convert back to the standard library
>>> zdt.py_datetime()
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
