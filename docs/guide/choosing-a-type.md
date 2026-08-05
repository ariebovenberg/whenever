---
myst:
  html_meta:
    description: >-
      How to choose between Instant, PlainDateTime, ZonedDateTime, and
      OffsetDateTime, with the trade-offs and standard library analogue of each.
---

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

(offset-datetime-guidance)=
## {class}`~whenever.OffsetDateTime`

```{epigraph}
In API design, if you've got two things that are even subtly different,
it's worth having them as separate types—because you're representing the
meaning of your data more accurately.

-- Jon Skeet
```

Like {class}`~whenever.ZonedDateTime`, this type preserves both an exact
instant and its local representation. The difference is that it stores only
the observed UTC offset, not a regional timezone rule set.

### When to use it—and what to watch for

Many external formats—such as ISO 8601 payloads, RFC 2822 messages, database
records, and logs—provide a local datetime and offset but no timezone ID.
{class}`~whenever.Instant` would preserve the moment while discarding that
source representation. {class}`~whenever.ZonedDateTime` would require
attaching regional rules the source never supplied. `OffsetDateTime` preserves
the moment, local fields, and observed offset without inventing those rules.

An offset does **not** identify a timezone: many regions can share `+02:00` at
one instant and follow different rules later. Treating one observed offset as
a timezone identity invents unsupported historical and future behavior. Even
placing a fixed offset in timezone brackets does not supply regional rules; it
only obscures the distinction.

Operations that reuse an offset where regional rules might matter emit
{class}`~whenever.StaleOffsetWarning`. If the offset is deliberately fixed,
pass `stale_offset_ok=True`. If it represents a location, first associate the
value with the known region using {meth}`~whenever.OffsetDateTime.assume_tz`.

```python
>>> flight_departure = OffsetDateTime(2023, 4, 21, hour=9, offset=hours(-4))
>>> flight_arrival = OffsetDateTime(2023, 4, 21, hour=10, offset=hours(-6))
>>> (flight_arrival - flight_departure).total("hours")
3
>>> # Deliberately keep the supplied fixed offset:
>>> flight_arrival.add(hours=3, stale_offset_ok=True)
>>> # Or use regional rules when the location is known:
>>> flight_arrival.assume_tz("America/Denver").add(hours=3)
```

## Comparison of types

Here's a summary of the differences between the types:

|                              | Instant | OffsetDT|ZonedDT|PlainDT  |
|:-----------------------------|:-------:|:-------:|:-----:|:-------:|
| knows the **exact** time     |   ✅    | ✅      | ✅    |  ❌     |
| knows the **local** time     |  ❌     |  ✅     |  ✅   |  ✅     |
| knows about DST rules        |  ❌     |  ❌     |  ✅   |  ❌     |

[^1]: `java.time`, Noda Time (C#), and Temporal (JavaScript) all use a similar datamodel.
