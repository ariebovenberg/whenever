# Formatting and parsing

`Whenever` supports formatting and parsing standardized formats

## ISO 8601

All types in *whenever* use ISO8601 as their canonical, round-trippable, string representation.
You can even instantiate objects directly from their ISO 8601 string representation:

```python
>>> Instant("2023-12-28T11Z")
Instant("2023-12-28 11:00:00Z")
>>> PlainDateTime("20231228T1130")
PlainDateTime("2023-12-28 11:30:00")
```

Below are the default string formats you get for calling each type's
`format_iso()` method:

| Type                                    | Default string format                          |
|:----------------------------------------|:-----------------------------------------------|
| {class}`~whenever.Instant`              | `YYYY-MM-DDTHH:MM:SSZ`                       |
| {class}`~whenever.PlainDateTime`        | `YYYY-MM-DDTHH:MM:SS`                        |
| {class}`~whenever.ZonedDateTime`        | `YYYY-MM-DDTHH:MM:SS±HH:MM[IANA TZ ID]` [^1] |
| {class}`~whenever.OffsetDateTime`       | `YYYY-MM-DDTHH:MM:SS±HH:MM`                  |

[^1]: The timezone ID is not part of the core ISO 8601 standard,
      but is part of the RFC 9557 extension.
      This format is commonly used by datetime libraries in other languages as well.

See the {ref}`reference documentation <iso8601>` for more details on formatting and parsing ISO 8601 strings.


## RFC 2822

[RFC 2822](https://datatracker.ietf.org/doc/html/rfc2822.html#section-3.3) is 
another common format for representing datetimes. 
It's used in email headers and HTTP headers. The format is:

```text
Weekday, DD Mon YYYY HH:MM:SS ±HHMM
```

For example: `Tue, 13 Jul 2021 09:45:00 -0900`

Use the methods {meth}`~whenever.OffsetDateTime.format_rfc2822` and
{meth}`~whenever.OffsetDateTime.parse_rfc2822` to format and parse
to this format, respectively:

```python
>>> d = OffsetDateTime(2023, 12, 28, 11, 30, offset=+5)
>>> d.format_rfc2822()
'Thu, 28 Dec 2023 11:30:00 +0500'
>>> OffsetDateTime.parse_rfc2822('Tue, 13 Jul 2021 09:45:00 -0900')
OffsetDateTime("2021-07-13 09:45:00-09:00")
```

## Custom formats

```{admonition} Future plans
:class: hint

Python's builtin `strptime` has its limitations, so a more full-featured
parsing API may be added in the future.
```

For now, basic customized parsing functionality is implemented in the ``parse_strptime()`` methods
of {class}`~whenever.OffsetDateTime` and {class}`~whenever.PlainDateTime`.
As the name suggests, these methods are thin wrappers around the standard library
{meth}`~datetime.datetime.strptime` function.
The same `formatting rules <https://docs.python.org/3/library/datetime.html#format-codes>`_ apply.

```python
>>> OffsetDateTime.parse_strptime("2023-01-01+05:00", "%Y-%m-%d%z")
OffsetDateTime("2023-01-01 00:00:00+05:00")
>>> PlainDateTime.parse_strptime("2023-01-01 15:00", "%Y-%m-%d %H:%M")
PlainDateTime("2023-01-01 15:00:00")
```

{class}`~whenever.ZonedDateTime` does not (yet)
implement ``parse_strptime()`` methods, because they require disambiguation.
If you'd like to parse into these types,
use {meth}`PlainDateTime.parse_strptime() <whenever.PlainDateTime.parse_strptime>`
to parse them, and then use the {meth}`~whenever.PlainDateTime.assume_utc`,
{meth}`~whenever.PlainDateTime.assume_fixed_offset`,
{meth}`~whenever.PlainDateTime.assume_tz`,
or {meth}`~whenever.PlainDateTime.assume_system_tz`
methods to convert them.
This makes it explicit what information is being assumed.

```python
>>> d = PlainDateTime.parse_strptime("2023-10-29 02:30:00", "%Y-%m-%d %H:%M:%S")
>>> d.assume_tz("Europe/Amsterdam")
ZonedDateTime("2023-10-29 02:30:00+02:00[Europe/Amsterdam]")
```

## Pydantic integration

```{warning}
Pydantic support is still in beta and may change in the future.
```

`whenever` types support basic serialization and deserialization
with [Pydantic](https://docs.pydantic.dev). The behavior is identical to
the `parse_iso()` and `format_iso()` methods.

```python
>>> from pydantic import BaseModel
>>> from whenever import ZonedDateTime, TimeDelta
...
>>> class Event(BaseModel):
...     start: ZonedDateTime
...     duration: TimeDelta
...
>>> event = Event(
...     start=ZonedDateTime(2023, 2, 23, hour=20, tz="Europe/Amsterdam"),
...     duration=TimeDelta(hours=2, minutes=30),
... )
>>> d = event.model_dump_json()
'{"start":"2023-02-23T20:00:00+01:00[Europe/Amsterdam]","duration":"PT2H30M"}'
```

```{note}

Whenever's parsing is stricter then Pydantic's default `datetime` parsing
behavior. More flexible parsing may be added in the future.
```
