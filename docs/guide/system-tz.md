---
myst:
  html_meta:
    description: >-
      Using the system timezone via to_system_tz() and assume_system_tz(), how
      whenever caches it, reset_system_tz(), and non-IANA system timezones.
---

(systemtime)=
# The system timezone

The system timezone is the timezone that your operating system is set to.
Pass {data}`~whenever.SYSTEM_TZ` anywhere a named timezone is accepted to
resolve the system timezone at call time:

```python
>>> from whenever import PlainDateTime, Instant, SYSTEM_TZ
>>> plain = PlainDateTime(2020, 8, 15, hour=8)
>>> d = plain.assume_tz(SYSTEM_TZ)
ZonedDateTime("2020-08-15 08:00:00-04:00[America/New_York]")
>>> Instant.now().to_tz(SYSTEM_TZ)
ZonedDateTime("2023-12-28 11:30:00-05:00[America/New_York]")
```

When working with the timezone of the current system, there
are a few things to keep in mind.

## System timezone changes

The system timezone isn't necessarily fixed for the lifetime of a process.
`whenever` caches it the first time you access it,
which keeps behavior predictable and fast.

In the rare case that you need to change the system timezone
while your program is running, you can use the
{meth}`~whenever.reset_system_tz` method to determine the system timezone again.
Existing datetimes will not be affected by this change,
but new datetimes will use the updated system timezone.

```python
>>> # initialization where the system timezone is America/New_York
>>> plain = PlainDateTime(2020, 8, 15, hour=8)
>>> d = plain.assume_tz(SYSTEM_TZ)
ZonedDateTime("2020-08-15 08:00:00-04:00[America/New_York]")
...
>>> # we change the system timezone to Amsterdam
>>> os.environ["TZ"] = "Europe/Amsterdam"
>>> whenever.reset_system_tz()
...
>>> d  # existing objects remain unchanged
ZonedDateTime("2020-08-15 08:00:00-04:00[America/New_York]")
>>> # new objects will use the new system timezone
>>> Instant.now().to_tz(SYSTEM_TZ)
ZonedDateTime("2025-08-15 15:03:28+02:00[Europe/Amsterdam]")
```

## Non-IANA system timezones

This is uncommon: most system timezones can be matched with an IANA timezone
ID (like `Europe/Amsterdam`). However, some systems use custom timezone
definitions that don't unambiguously map to an IANA timezone ID.
For example, some systems may set the `TZ` environment variable to a POSIX TZ
string like `CET-1CEST,M3.5.0,M10.5.0/3`,
or specify a custom timezone file.

```python
>>> os.environ["TZ"] = "CET-1CEST,M3.5.0,M10.5.0/3"
>>> whenever.reset_system_tz()
```

These types of timezone definitions can still account for Daylight Saving Time
(DST) and other timezone changes:

```python
>>> d = plain.assume_tz(SYSTEM_TZ)
ZonedDateTime("2024-06-04 12:00:00+02:00[<system timezone without ID>]")
>>> # Correct UTC offset after adding 5 months
>>> d.add(months=5)
ZonedDateTime("2024-11-04 12:00:00+01:00[<system timezone without ID>]")
```

However there are some limitations of such instances of {class}`~whenever.ZonedDateTime`:

1. Their `tz_id` attribute is `None`
2. They cannot be pickled
3. Their string representation cannot preserve the timezone rules and is not
   round-trippable. {meth}`~whenever.ZonedDateTime.format_iso` requires an IANA
   identifier by default; `tz_id_display="never"` or `"auto"` produces only the
   local fields and current offset.
4. The result of `to_stdlib()` will have a fixed offset, not a `ZoneInfo` object.
