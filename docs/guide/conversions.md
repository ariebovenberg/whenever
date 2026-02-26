# Converting between types

## Between exact types

You can convert between exact types with the {meth}`~whenever.ZonedDateTime.to_instant`,
{meth}`~whenever.ZonedDateTime.to_fixed_offset`, {meth}`~whenever.ZonedDateTime.to_tz`,
and {meth}`~whenever.ZonedDateTime.to_system_tz` methods. These methods return a new
instance of the appropriate type, representing the same moment in time.
This means the results will always compare equal to the original datetime.

```python
>>> d = ZonedDateTime(2023, 12, 28, 11, 30, tz="Europe/Amsterdam")
>>> d.to_instant()  # The underlying moment in time
Instant("2023-12-28 10:30:00Z")
>>> d.to_fixed_offset(5)  # same moment with a +5:00 offset
OffsetDateTime("2023-12-28 15:30:00+05:00")
>>> d.to_tz("America/New_York")  # same moment in New York
ZonedDateTime("2023-12-28 05:30:00-05:00[America/New_York]")
>>> d.to_system_tz()  # same moment in the system timezone (e.g. Europe/Paris)
ZonedDateTime("2023-12-28 11:30:00+01:00[Europe/Paris]")
>>> d.to_fixed_offset(4) == d
True  # always the same moment in time
```

## To and from local time

Conversion to a "plain" datetime is easy: calling
{meth}`~whenever.ZonedDateTime.to_plain` simply
retrieves the date and time part of the datetime, and discards the any timezone
or offset information.

```python
>>> d = ZonedDateTime(2023, 12, 28, 11, 30, tz="Europe/Amsterdam")
>>> n = d.to_plain()
PlainDateTime("2023-12-28 11:30:00")
```

You can convert from plain datetimes with the {meth}`~whenever.PlainDateTime.assume_utc`,
{meth}`~whenever.PlainDateTime.assume_fixed_offset`, and
{meth}`~whenever.PlainDateTime.assume_tz`, and
{meth}`~whenever.PlainDateTime.assume_system_tz` methods.

```python
>>> n = PlainDateTime(2023, 12, 28, 11, 30)
>>> n.assume_utc()
Instant("2023-12-28 11:30:00Z")
>>> n.assume_tz("Europe/Amsterdam")
ZonedDateTime("2023-12-28 11:30:00+01:00[Europe/Amsterdam]")
```

```{tip}
The naming difference between `to_*` and `assume_*` methods is intentional.
See the {ref}`FAQ <faq-to-vs-assume>` for the rationale.
```
