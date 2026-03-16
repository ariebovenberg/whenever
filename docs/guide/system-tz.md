(systemtime)=
# The system timezone

The system timezone is the timezone that your operating system is set to.
You can create datetimes in the system timezone by using the
{meth}`~whenever.PlainDateTime.assume_system_tz`
or {meth}`~whenever.ZonedDateTime.to_system_tz` methods:

```python
>>> from whenever import PlainDateTime, Instant
>>> plain = PlainDateTime(2020, 8, 15, hour=8)
>>> d = plain.assume_system_tz()
ZonedDateTime("2020-08-15 08:00:00-04:00[America/New_York]")
>>> Instant.now().to_system_tz()
ZonedDateTime("2023-12-28 11:30:00-05:00[America/New_York]")
```

When working with the timezone of the current system, there
are a few things to keep in mind.

## System timezone changes

It's important to be aware that the system timezone can change.
`whenever` caches the system timezone at time you access it first.
This ensures predictable and fast behavior.

In the rare case that you need to change the system timezone
while your program is running, you can use the
{meth}`~whenever.reset_system_tz` method to determine the system timezone again.
Existing datetimes will not be affected by this change,
but new datetimes will use the updated system timezone.

```python
>>> # initialization where the system timezone is America/New_York
>>> plain = PlainDateTime(2020, 8, 15, hour=8)
>>> d = plain.assume_system_tz()
ZonedDateTime("2020-08-15 08:00:00-04:00[America/New_York]")
...
>>> # we change the system timezone to Amsterdam
>>> os.environ["TZ"] = "Europe/Amsterdam"
>>> whenever.reset_system_tz()
...
>>> d  # existing objects remain unchanged
ZonedDateTime("2020-08-15 08:00:00-04:00[America/New_York]")
>>> # new objects will use the new system timezone
>>> Instant.now().to_system_tz()
ZonedDateTime("2025-08-15 15:03:28+01:00[Europe/Amsterdam]")
```

## Non-IANA system timezones

While most system timezones can be matched with a IANA timezone ID
(like `Europe/Amsterdam`),
some systems use custom timezone definitions that don't (unambiguously)
map to a IANA timezone ID.
For example, some systems may set the `TZ` environment variable to a POSIX TZ
string like `CET-1CEST,M3.5.0,M10.5.0/3`,
or specify a custom timezone file.

```python
>>> os.environ["TZ"] = "CET-1CEST,M3.5.0,M10.5.0/3"
>>> whenever.reset_system_tz()
```

These type of timezone definitions can still account for Daylight Saving Time
(DST) and other timezone changes:

```python
>>> d = plain.assume_system_tz()
ZonedDateTime("2024-06-04 12:00:00+02:00[<system timezone without ID>]")
>>> # Correct UTC offset after adding 5 months
>>> d.add(months=5)
ZonedDateTime("2024-11-04 12:00:00+01:00[<system timezone without ID>]")
```

However there are some limitations of such instances of {class}`~whenever.ZonedDateTime`:

1. Their `tz` attribute is `None`
2. They cannot be pickled
3. Their ISO 8601 string representation does not include a IANA timezone ID
4. The result of `to_stdlib()` will have a fixed offset, not a `ZoneInfo` object.
