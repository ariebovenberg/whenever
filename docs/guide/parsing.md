---
myst:
  html_meta:
    description: >-
      Formatting and parsing in whenever: ISO 8601 as the canonical
      round-trippable format, RFC 2822, custom format patterns, and Pydantic
      integration.
---

# Formatting and parsing

`whenever` reads and writes the standard formats: ISO 8601 as the canonical,
round-trippable representation, plus RFC 2822 for email and HTTP, and custom
patterns for everything else.

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

All datetime types support custom format and parse patterns via
the `format()` and `parse()` methods.
Patterns use specifiers like `YYYY`, `MM`, `DD`, `hh`, `mm`, `ss`.

```python
>>> OffsetDateTime(2024, 3, 15, 14, 30, offset=+2).format(
...     "EEE, DD MMM YYYY hh:mm:ssxxx"
... )
'Fri, 15 Mar 2024 14:30:00+02:00'
>>> Date.parse("15 Mar 2024", pattern="DD MMM YYYY")
Date("2024-03-15")
>>> ZonedDateTime.parse(
...     "2024-03-15 14:30+01:00[Europe/Paris]",
...     pattern="YYYY-MM-DD hh:mmxxx'['VV']'",
... )
ZonedDateTime("2024-03-15 14:30:00+01:00[Europe/Paris]")
```

See the {ref}`pattern format reference <pattern-format>` for the
full list of specifiers and details.

### Zoned parsing policies

The `ZonedDateTime` ISO-string constructor, `parse_iso()`, and patterned
`parse()` accept `disambiguation=` and `offset_mismatch=`. A matching numeric
offset identifies the occurrence of a repeated local time. If the input omits
an offset, `disambiguation` selects how a fold or gap is resolved. If a numeric
offset conflicts with the named timezone, `offset_mismatch` can `"raise"`,
`"keep_instant"`, or `"keep_local"`. `"keep_instant"` treats the numeric
offset as authoritative and changes the local fields to match the timezone.
`"keep_local"` discards the conflicting offset and resolves the written local
time in the named timezone; if that local time is repeated or skipped,
`disambiguation` determines which instant is selected.

Hour-and-minute offsets are compared with candidate timezone offsets rounded
to the nearest minute, half away from zero. Offsets containing seconds match
exactly. A `Z` suffix is different: it always identifies an exact UTC instant
and is not treated as a numeric `+00:00` assertion about local time.

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
