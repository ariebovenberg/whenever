(choosing-a-type)=
# Choosing the right type

While the standard library has a single {class}`~datetime.datetime` type
for all use cases, `whenever` provides distinct types[^1].
This ensures {ref}`different kinds of time <exact-vs-local>` are distinguished clearly,
which helps to avoid common pitfalls when working with dates and times.

The main types are:

- {class}`~whenever.Instant`—the simplest way to unambiguously represent a point on the timeline,
  also known as **"exact time"**.
  This type is analogous to a UNIX timestamp or UTC.
- {class}`~whenever.PlainDateTime`—how humans represent time (e.g. *"January 23rd, 2023, 3:30pm"*),
  also known as **"local time"**.
  This type is analogous to an "naive" datetime in the standard library.
- {class}`~whenever.ZonedDateTime`—A combination of the two concepts above:
  an exact time paired with a local time at a specific location.
  This type is analogous to an "aware" standard library datetime with `tzinfo` set to a `ZoneInfo` instance.

## {class}`~whenever.Instant`

This is the simplest way to represent a moment on the timeline,
independent of human complexities like timezones or calendars.
An `Instant` maps 1:1 to UTC or a UNIX timestamp.
It's great for storing when something happened (or will happen)
regardless of location.

```python
>>> livestream_start = Instant("2022-10-24 17:00Z")
Instant("2022-10-24 17:00:00Z")
>>> Instant.now() > livestream_start
True
>>> livestream_start.add(hours=3).timestamp()
1666641600
```

The value of this type is in its simplicity. It's straightforward to compare,
add, and subtract. It's always clear what moment in time
you're referring to—without having to worry about timezones,
Daylight Saving Time (DST), or the calendar.

## {class}`~whenever.PlainDateTime`

Humans typically represent time as a combination of date and time-of-day.
For example: *January 23rd, 2023, 3:30pm*.
While this information makes sense to people within a certain context,
it doesn't by itself refer to a moment on the timeline.
This is because this date and time-of-day occur at different moments
depending on whether you're in Australia or Mexico, for example.

Another limitation is that you can't account for Daylight Saving Time
if you only have a date and time-of-day without a timezone.
Therefore, adding exact time units to "plain" datetimes will emit a
`NaiveArithmeticWarning` to prevent you from accidentally introducing DST bugs.
This is because—strictly speaking—you don't know what the
local time will be in 3 hours:
perhaps the clock will be moved forward or back due to Daylight Saving Time.

```python
>>> bus_departs = PlainDateTime(2020, 3, 14, hour=15)
PlainDateTime("2020-03-14 15:00:00")
# NOT possible:
>>> Instant.now() > bus_departs                 # comparison with exact time
# possible, but emits a warning:
>>> bus_departs.add(hours=3)                    # adding exact time units
# IS possible:
>>> bus_departs.add(hours=3, naive_arithmetic_ok=True)  # explicitly suppress
>>> PlainDateTime(2020, 3, 15) > bus_departs    # comparison with other plain datetimes
>>> bus_departs.add(days=2)                     # calendar operations are OK
```

So how do you account for daylight saving time?
Or find the corresponding exact time for a date and time-of-day?
That's what the next type is for.

## {class}`~whenever.ZonedDateTime`

This is a combination of an exact *and* a local time at a specific location,
with rules about Daylight Saving Time and other timezone changes.

```python
>>> bedtime = ZonedDateTime(2024, 3, 9, 22, tz="America/New_York")
ZonedDateTime("2024-03-09 22:00:00-05:00[America/New_York]")
# accounts for the DST transition overnight:
>>> bedtime.add(hours=8)
ZonedDateTime("2024-03-10 07:00:00-04:00[America/New_York]")
```

A timezone defines a UTC offset for each point on the timeline.
As a result, any {class}`~whenever.Instant` can
be converted to a {class}`~whenever.ZonedDateTime`.
Converting from a {class}`~whenever.PlainDateTime`, however,
may be {ref}`ambiguous <ambiguity>`,
because changes to the offset can result in local times
occurring twice or not at all.

```python
>>> # Instant->Zoned is always straightforward
>>> livestream_starts.to_tz("America/New_York")
ZonedDateTime("2022-10-24 13:00:00-04:00[America/New_York]")
>>> # Local->Zoned may be ambiguous
>>> bus_departs.assume_tz("America/New_York")
ZonedDateTime("2020-03-14 15:00:00-04:00[America/New_York]")
```

## {class}`~whenever.OffsetDateTime`


```{epigraph}
In API design, if you've got two things that are even subtly different,
it's worth having them as separate types—because you're representing the
meaning of your data more accurately.

-- Jon Skeet
```

Like {class}`~whenever.ZonedDateTime`, this type represents an exact time
*and* a local time. The difference is that {class}`~whenever.OffsetDateTime`
has a *fixed* offset from UTC rather than a timezone.
As a result, it doesn't know about Daylight Saving Time or other timezone changes.
Many operations will emit a {class}`~whenever.PotentiallyStaleOffsetWarning`
to prevent you from accidentally introducing DST bugs.

Then why use it? Firstly, most datetime formats (e.g. ISO 8601 and RFC 2822) only have fixed offsets,
making {class}`~whenever.OffsetDateTime` ideal for representing datetimes in these formats.
Second, a {class}`~whenever.OffsetDateTime` is simpler—so long as you
don't need the ability to shift it. This makes {class}`~whenever.OffsetDateTime`
an efficient and compatible choice for representing times in the past.

```python
>>> flight_departure = OffsetDateTime(2023, 4, 21, hour=9, offset=-4)
>>> flight_arrival = OffsetDateTime(2023, 4, 21, hour=10, offset=-6)
>>> (flight_arrival - flight_departure).in_hours()
3
>>> # This will emit a warning!
>>> flight_arrival.add(hours=3)  # a DST-bug waiting to happen!
>>> # instead:
>>> flight_arrival.add(hours=3, stale_offset_ok=True)  # explicitly suppress
>>> flight_arrival.in_tz("America/New_York").add(hours=3)  # use the full timezone
```

## Comparison of types

Here's a summary of the differences between the types:

|                              | Instant | OffsetDT|ZonedDT|PlainDT  |
|:-----------------------------|:-------:|:-------:|:-----:|:-------:|
| knows the **exact** time     |   ✅    | ✅      | ✅    |  ❌     |
| knows the **local** time     |  ❌     |  ✅     |  ✅   |  ✅     |
| knows about DST rules        |  ❌     |  ❌     |  ✅   |  ❌     |

[^1]: `java.time`, Noda Time (C#), and Temporal (JavaScript) all use a similar datamodel.
