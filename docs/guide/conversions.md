---
myst:
  html_meta:
    description: >-
      Converting between whenever's types with to_instant(), to_tz(), to_plain(),
      and the assume_*() methods, including how offset mismatches are handled.
---

# Converting between types

## Between exact types

You can convert between exact types with the {meth}`~whenever.ZonedDateTime.to_instant`,
{meth}`~whenever.ZonedDateTime.to_fixed_offset`, and
{meth}`~whenever.ZonedDateTime.to_tz` methods. These methods return a new
instance of the appropriate type, representing the same moment in time.
This means the results will always compare equal to the original datetime.

```python
>>> d = ZonedDateTime(2023, 12, 28, 11, 30, tz="Europe/Amsterdam")
>>> d.to_instant()  # The underlying moment in time
Instant("2023-12-28 10:30:00Z")
>>> d.to_fixed_offset(hours(5))  # same moment with a +5:00 offset
OffsetDateTime("2023-12-28 15:30:00+05:00")
>>> d.to_tz("America/New_York")  # same moment in New York
ZonedDateTime("2023-12-28 05:30:00-05:00[America/New_York]")
>>> d.to_tz(SYSTEM_TZ)  # same moment in the system timezone (e.g. Europe/Paris)
ZonedDateTime("2023-12-28 11:30:00+01:00[Europe/Paris]")
>>> d.to_fixed_offset(hours(4)) == d
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
{meth}`~whenever.PlainDateTime.assume_fixed_offset`,
and {meth}`~whenever.PlainDateTime.assume_tz` methods.

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


Similarly, you can associate an {class}`~whenever.OffsetDateTime`
with a timezone using {meth}`~whenever.OffsetDateTime.assume_tz`:

```python
>>> o = OffsetDateTime(2023, 12, 28, 11, 30, offset=hours(1))
>>> o.assume_tz("Europe/Amsterdam")
ZonedDateTime("2023-12-28 11:30:00+01:00[Europe/Amsterdam]")
```

By default, this raises an error if the offset doesn't match the timezone.
The `offset_mismatch` argument can instead preserve either the instant or the
local fields:

```python
>>> o = OffsetDateTime(2023, 12, 28, 11, 30, offset=hours(5))
>>> o.assume_tz("Europe/Amsterdam", offset_mismatch="keep_instant")
ZonedDateTime("2023-12-28 07:30:00+01:00[Europe/Amsterdam]")
>>> o.assume_tz("Europe/Amsterdam", offset_mismatch="keep_local")
ZonedDateTime("2023-12-28 11:30:00+01:00[Europe/Amsterdam]")
```

See {ref}`offset-mismatch` for how matching and conflicting offsets interact
with `disambiguation`.

:::{admonition} When is `assume_tz` useful?
:class: hint

A common scenario is receiving timestamps from an external source that only
carries a fixed offset. If the originating timezone is known,
{meth}`~whenever.OffsetDateTime.assume_tz` associates its rules before further
arithmetic. See {ref}`offset-datetime-guidance` for why doing this before
moving the value matters.
:::
