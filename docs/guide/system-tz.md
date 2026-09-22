---
myst:
  html_meta:
    description: >-
      Using the system time zone via the SYSTEM_TZ sentinel, how whenever caches
      it, reset_system_tz(), and the limits of system time zones without a
      time zone ID.
---

(systemtime)=
# The system time zone

The system time zone is the time zone that your operating system is set to.
Pass {data}`~whenever.SYSTEM_TZ` anywhere a named time zone is accepted to
resolve the system time zone at call time:

```python
>>> from whenever import Date, PlainDateTime, Instant, SYSTEM_TZ
>>> plain = PlainDateTime(2020, 8, 15, hour=8)
>>> d = plain.assume_tz(SYSTEM_TZ)
ZonedDateTime("2020-08-15 08:00:00-04:00[America/New_York]")
>>> Instant.now().to_tz(SYSTEM_TZ)
ZonedDateTime("2023-12-28 11:30:00-05:00[America/New_York]")
>>> Date.today(SYSTEM_TZ)
Date("2023-12-28")
```

An empty `TZ` environment variable means UTC, as the C library reads it,
and so does a Unix system with no `TZ` and no `/etc/localtime`. A
system time zone that cannot be resolved raises
{exc}`~whenever.TimeZoneNotFoundError` when it is first needed or on
{func}`~whenever.reset_system_tz`.

When working with the time zone of the current system, there
are a few things to keep in mind.

## System time zone changes

The system time zone isn't necessarily fixed for the lifetime of a process.
`whenever` caches it the first time you access it,
which keeps behavior predictable and fast.

In the rare case that you need to change the system time zone
while your program is running, you can use the
{meth}`~whenever.reset_system_tz` method to determine the system time zone again.
Existing datetimes will not be affected by this change,
but new datetimes will use the updated system time zone.

```python
>>> # initialization where the system time zone is America/New_York
>>> plain = PlainDateTime(2020, 8, 15, hour=8)
>>> d = plain.assume_tz(SYSTEM_TZ)
ZonedDateTime("2020-08-15 08:00:00-04:00[America/New_York]")
...
>>> # we change the system time zone to Amsterdam
>>> os.environ["TZ"] = "Europe/Amsterdam"
>>> whenever.reset_system_tz()
...
>>> d  # existing objects remain unchanged
ZonedDateTime("2020-08-15 08:00:00-04:00[America/New_York]")
>>> # new objects will use the new system time zone
>>> Instant.now().to_tz(SYSTEM_TZ)
ZonedDateTime("2025-08-15 15:03:28+02:00[Europe/Amsterdam]")
```

## System time zones without a time zone ID

This is uncommon: most system time zones can be matched with a time zone ID
(like `Europe/Amsterdam`). On Unix, the ID comes from where `/etc/localtime`
points into the time zone database, or from `/etc/timezone` when
`/etc/localtime` is a copy of the file it names; on Windows, from the
`tzlocal` package. However, some systems use custom time zone
definitions that don't unambiguously map to a time zone ID.
For example, some systems may set the `TZ` environment variable to a POSIX TZ
string like `CET-1CEST,M3.5.0,M10.5.0/3`,
or specify a custom time zone file.

```python
>>> os.environ["TZ"] = "CET-1CEST,M3.5.0,M10.5.0/3"
>>> whenever.reset_system_tz()
```

These types of time zone definitions can still account for daylight saving time
(DST) and other time zone changes:

```python
>>> d = PlainDateTime(2024, 6, 4, hour=12).assume_tz(SYSTEM_TZ)
ZonedDateTime("2024-06-04 12:00:00+02:00[<system time zone without ID>]")
>>> # Correct UTC offset after adding 5 months
>>> d.add(months=5)
ZonedDateTime("2024-11-04 12:00:00+01:00[<system time zone without ID>]")
```

However there are some limitations of such instances of {class}`~whenever.ZonedDateTime`:

1. Their `tz_id` attribute is `None`
2. They cannot be pickled
3. Their string representation cannot preserve the time zone rules and is not
   round-trippable. {meth}`~whenever.ZonedDateTime.format_iso` requires a time zone
   ID by default; `tz_id_display="omit"` or `"if_available"` produces only
   the local fields and current offset. `str()` gives that offset form and
   never raises. The `repr()` marks the missing ID as
   `<system time zone without ID>`; it is the one repr in the library that
   cannot be evaluated back into a value.
4. The result of `to_stdlib()` will have a fixed offset, not a `ZoneInfo` object.
5. Formatting with `VV` raises {class}`ValueError`.
