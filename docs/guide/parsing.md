---
myst:
  html_meta:
    description: >-
      Formatting and parsing in whenever: ISO 8601 as the canonical
      round-trippable format, RFC 2822, patterns, and Pydantic integration.
---

# Formatting and parsing

`whenever` reads and writes the standard formats: ISO 8601 as the canonical,
round-trippable representation, plus RFC 2822 for email and HTTP, and
patterns for everything else.

## ISO 8601

All types in *whenever* use ISO 8601 as their canonical string representation.
This representation is round-trippable except in the uncommon case of a zoned
datetime backed by a system time zone without a time zone ID (see
{ref}`systemtime`).
You can even instantiate objects directly from their ISO 8601 string representation:

```python
>>> Instant("2023-12-28T11Z")
Instant("2023-12-28 11:00:00Z")
>>> PlainDateTime("20231228T1130")
PlainDateTime("2023-12-28 11:30:00")
```

Below are the default ISO string formats produced by each type:

| Type                                    | ISO 8601 string                                |
|:----------------------------------------|:-----------------------------------------------|
| {class}`~whenever.Instant`              | `2023-12-28T11:30:00Z`                         |
| {class}`~whenever.PlainDateTime`        | `2023-12-28T11:30:00`                          |
| {class}`~whenever.ZonedDateTime`        | `2023-12-28T11:30:00+01:00[Europe/Paris]` [^1] |
| {class}`~whenever.OffsetDateTime`       | `2023-12-28T11:30:00+01:00`                    |

[^1]: The time zone ID is not part of the core ISO 8601 standard,
      but is part of the RFC 9557 extension.
      This format is commonly used by datetime libraries in other languages as well.

See the {ref}`reference documentation <iso8601>` for more details on formatting and parsing ISO 8601 strings.


## RFC 2822

[RFC 2822](https://datatracker.ietf.org/doc/html/rfc2822.html#section-3.3) is
another common format for representing datetimes, used in email headers and
HTTP headers. It looks like `Tue, 13 Jul 2021 09:45:00 -0900`: a weekday,
a date, a time, and a numeric offset.

{meth}`~whenever.OffsetDateTime.format_rfc2822` and
{meth}`~whenever.OffsetDateTime.parse_rfc2822` convert to and from
this format:

```python
>>> d = OffsetDateTime(2023, 12, 28, 11, 30, offset=hours(5))
>>> d.format_rfc2822()
'Thu, 28 Dec 2023 11:30:00 +0500'
>>> OffsetDateTime.parse_rfc2822('Tue, 13 Jul 2021 09:45:00 -0900')
OffsetDateTime("2021-07-13 09:45:00-09:00")
```

{meth}`~whenever.Instant.format_rfc2822` writes the GMT form, which is also
the HTTP date (IMF-fixdate, RFC 9110), and
{meth}`~whenever.Instant.parse_rfc2822` applies the offset and gives the
UTC instant:

```python
>>> Instant.from_utc(2023, 12, 28, 11, 30).format_rfc2822()
'Thu, 28 Dec 2023 11:30:00 GMT'
>>> Instant.parse_rfc2822('Tue, 13 Jul 2021 09:45:00 -0900')
Instant("2021-07-13 18:45:00Z")
```

Both parsers accept the RFC 2822 zone names `UT` and `GMT` and the North American
abbreviations `EST` through `PDT`; any other name, including a military
letter, is read as `+0000`, and comments in folding whitespace are rejected.

{class}`~whenever.ZonedDateTime` has neither method: the format carries a
numeric offset and no time zone ID, so a parse can never yield a
`ZonedDateTime`, and formatting one is `to_fixed_offset()` first.
{class}`~whenever.PlainDateTime` has no offset to write.

RFC 2822 only represents whole seconds and minute-precision offsets.
Formatting therefore discards nanoseconds and any seconds in the offset; use
ISO 8601 when those values must round-trip exactly.

## Patterns

{class}`~whenever.Date`, {class}`~whenever.Time`, {class}`~whenever.Instant`,
{class}`~whenever.OffsetDateTime`, {class}`~whenever.ZonedDateTime`, and
{class}`~whenever.PlainDateTime` format and parse with patterns via
their `format()` and `parse()` methods—for example,
{meth}`~whenever.OffsetDateTime.format` and
{meth}`~whenever.OffsetDateTime.parse`.
Patterns use specifiers like `YYYY`, `MM`, `DD`, `HH`, `mm`, `ss`.

```python
>>> OffsetDateTime(2024, 3, 15, 14, 30, offset=hours(2)).format(
...     "EEE, DD MMM YYYY HH:mm:ssxxx"
... )
'Fri, 15 Mar 2024 14:30:00+02:00'
>>> Date.parse("15 Mar 2024", pattern="DD MMM YYYY")
Date("2024-03-15")
>>> ZonedDateTime.parse(
...     "2024-03-15 14:30+01:00[Europe/Paris]",
...     pattern="YYYY-MM-DD HH:mmxxx'['VV']'",
... )
ZonedDateTime("2024-03-15 14:30:00+01:00[Europe/Paris]")
```

See the {ref}`pattern format reference <pattern-format>` for the
full list of specifiers and details.

### Zoned parsing policies

The {class}`~whenever.ZonedDateTime` ISO-string constructor,
{meth}`~whenever.ZonedDateTime.parse_iso`, and patterned
{meth}`~whenever.ZonedDateTime.parse` accept `disambiguation=` and
`offset_mismatch=`. See
{ref}`resolving-local-times` for the complete decision flow, including
matching offsets, conflicts, `Z`, repeated and skipped local times, and
offset precision.

## Pydantic integration

`whenever` types support serialization and deserialization with
[Pydantic](https://docs.pydantic.dev) 2. Existing instances are preserved;
strings are validated with each type's `parse_iso()` method and serialized as
its **ISO 8601 string**. Other input types and invalid strings raise
Pydantic's `ValidationError`. The JSON schema of every `whenever` field is a
string.

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

Parsing is ISO 8601 only, stricter than Pydantic's own `datetime` parsing.
```
