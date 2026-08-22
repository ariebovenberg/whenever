---
myst:
  html_meta:
    description: >-
      Reference for custom format patterns: date, time, offset, and timezone
      specifiers, literal text rules, parsing requirements, migrating patterns
      in 0.11, and how it differs from strftime.
---

(pattern-format)=
# Pattern format

```{eval-rst}
.. currentmodule:: whenever
```

Custom format and parse patterns allow you to format datetime values into
strings and parse strings into datetime values, using a pattern string
that describes the expected format. The canonical full datetime pattern is
`YYYY-MM-DD HH:mm:ss`.

## Quick example

```python
>>> from whenever import Date, Time, OffsetDateTime, hours
>>> Date(2024, 3, 15).format("YYYY/MM/DD")
'2024/03/15'
>>> Date.parse("2024/03/15", pattern="YYYY/MM/DD")
Date("2024-03-15")
>>> OffsetDateTime(2024, 3, 15, 14, 30, offset=hours(2)).format(
...     "EEE, DD MMM YYYY HH:mm:ssxxx"
... )
'Fri, 15 Mar 2024 14:30:00+02:00'
```

## Specifiers

Each pattern is a string containing specifiers and literal text.
Specifiers are sequences of the same letter that are replaced by
the corresponding value.

### Date specifiers

| Symbol  | Meaning                    | Pattern | Example output |
|:---------|:---------------------------|:---------------|:--------------|
| `Y` | year  | `YY` [^1] <br/> `YYYY` | `24` <br/> `2024`       |
| `M`   | month | `M` <br/> `MM` <br/> `MMM` <br/> `MMMM` | `3` <br/> `03` <br/> `Mar` <br/> `March` |
| `D`   | day of month | `D` <br/> `DD` | `5` <br/> `05` |
| `E`   | day of week [^2] | `EEE` <br/> `EEEE` | `Fri` <br/> `Friday` |

:::{admonition} Why are Whenever's patterns different?
:class: important

Whenever deliberately avoids classic datetime-pattern footguns. `Y` is always
the calendar year, never the ISO week-numbering year. `H` is the 24-hour clock,
as in almost all other datetime libraries, while the distinct `i` is the
12-hour clock and makes a missing AM/PM field detectable. `D` is always the
day of the month; day-of-year is not supported. Familiar but unsupported
letters fail instead of silently acquiring a different meaning.
:::

### Time specifiers


| Symbol  | Meaning                    | Pattern | Example output |
|:---------|:---------------------------|:---------------|:--------------|
| `H` | hour (24-hour) | `H` <br/> `HH` | `4` <br/> `04` |
| `i`   | hour (12-hour) | `i` <br/> `ii` | `4` <br/> `04` |
| `m`   | minute | `m` <br/> `mm` | `5` <br/> `05` |
| `s`   | second | `s` <br/> `ss` | `5` <br/> `05` |
| `[...]` | optional seconds tail [^3] | `[ss]` <br/> `[:ss]` <br/> `[:ss.fff]` <br/> `[:ss.FFF]` | `05`, (omitted) <br/> `:05`, (omitted) <br/> `:05.123`, (omitted) <br/> `:05.12`, (omitted) |
| `f` | fractional seconds, exact digits | `f`<br/>`ff`<br/>`fff`<br/>...<br/>`fffffffff` | `1` <br/> `12`, `00` <br/> `123`, `400` <br/> ... <br/> `123456789`, `374930000` |
| `F` | fractional seconds, trimmed [^4] | `F`<br/>`FF`<br/>`FFF`<br/>...<br/>`FFFFFFFFF` | `1` <br/> `12`, (omitted) <br/> `123`, `4` <br/>...<br/> `123456789`, `37493` |
| `a`   | AM/PM [^5] | `a`<br/>`aa` | `P` <br/> `PM` |

:::{admonition} Optional seconds
:class: hint

Brackets have one limited use immediately after fixed-width `mm`: optional
seconds written as `[ss]` or `[:ss]`, followed optionally by `.` and 1–9 `f`
or `F` characters. They are not general-purpose optional groups, and the
colon is the only supported separator.

The whole tail is omitted when both seconds and nanoseconds are zero. Otherwise,
the separator and two zero-padded second digits are emitted. Lowercase `f`
requires exactly that many fractional digits; uppercase `F` trims trailing
zeroes and omits the decimal point when the fraction is empty.


```python
>>> Time(14, 30, 0).format("HH:mm[:ss]")
'14:30'
>>> Time(14, 30, 5).format("HH:mm[:ss]")
'14:30:05'
>>> Time(14, 30, 0, nanosecond=500_000_000).format("HH:mm[:ss]")
'14:30:00'
>>> Time(14, 30, 0).format("HH:mm[:ss.FFF]")
'14:30'
>>> Time(14, 30, 0, nanosecond=500_000_000).format("HH:mm[:ss.FFF]")
'14:30:00.5'
>>> Time(14, 30, 5).format("HH:mm[ss]")
'14:3005'
```

The group boundary must remain unambiguous without backtracking.
Separator-free `[ss...]` therefore cannot be followed by an element that
starts with a digit, and `[:ss...]` cannot be followed by another colon.
Fields that may be empty are also rejected as followers when they make the
boundary ambiguous. A trimmed optional fraction cannot be followed by a
literal period.

:::

### Offset and timezone specifiers

See {ref}`timezones-explained` for background on timezones, offsets, and abbreviations.

| Symbol  | Meaning                    | Pattern | Example output |
|:---------|:---------------------------|:---------------|:--------------|
| `x` | Numeric offset; precision depends on width | `x` <br/> `xx` <br/> `xxx` <br/> `xxxx` <br/> `xxxxx` | `+02` <br/> `+0230` <br/> `+02:30` <br/> `+023045` <br/> `+02:30:45` |
| `X` | Numeric offset, with `Z` for zero offset; precision depends on width | `X` <br/> `XX` <br/> `XXX` <br/> `XXXX` <br/> `XXXXX` | `+02` <br/> `+0230` <br/> `+02:30` <br/> `+023045` <br/> `+02:30:45` or `Z` when zero |
| `V` | IANA timezone ID | `VV` | `Europe/Paris` |
| `z` | Timezone abbreviation [^6] | `zz` | `CET`, `CEST` |

For `x` and `X`, widths `xx` and `xxx` round offset seconds to the nearest
minute, with half values rounded away from zero. Widths `x` and `X` apply the
same rounding but require the result to be a whole number of hours; otherwise
formatting raises {class}`ValueError`. Widths `xxxx` and `xxxxx` include offset
seconds when nonzero and therefore preserve them exactly.

When parsing a {class}`ZonedDateTime`, an offset without seconds is matched
against the timezone offset rounded in the same way. An offset that includes
seconds, and `Z`, must match exactly.

`VV` requires an IANA timezone ID. Formatting a timezone without one raises
{class}`ValueError`.

```{admonition} Choosing between x and X
:class: hint

Use uppercase `X` when you want `Z` for zero offset
(e.g. {class}`Instant` formatting).
Use lowercase `x` when you always want a numeric offset
(e.g. {class}`OffsetDateTime` formatting).
```

```python
>>> ZonedDateTime(2024, 7, 15, 14, 30, tz="Europe/Paris").format(
...     "YYYY-MM-DD HH:mm zz"
... )
'2024-07-15 14:30 CEST'
>>> ZonedDateTime.parse(
...     "2024-07-15 14:30+02:00[Europe/Paris]",
...     pattern="YYYY-MM-DD HH:mmxxx'['VV']'",
... )
ZonedDateTime("2024-07-15 14:30:00+02:00[Europe/Paris]")
```

### Supported specifiers per type

| Type              | Date | Time | `x`/`X` | `VV`/`zz` |
|:------------------|:----:|:----:|:--------:|:----:|
| {class}`Date`          |  ✅  |  ❌  |    ❌    |  ❌  |
| {class}`Time`          |  ❌  |  ✅  |    ❌    |  ❌  |
| {class}`PlainDateTime` |  ✅  |  ✅  |    ❌    |  ❌  |
| {class}`OffsetDateTime`|  ✅  |  ✅  |    ✅    |  ❌  |
| {class}`ZonedDateTime` |  ✅  |  ✅  |    ✅    |  ✅  |
| {class}`Instant`       |  ✅  |  ✅  |    ✅    |  ❌  |

## Literal text

Common non-letter characters (`:`, `-`, `/`, `.`, `,`, `;`,
`_`, `(`, `)`, digits, spaces, and other ASCII
punctuation) are treated as literals by default:

```python
>>> Date(2024, 3, 15).format("YYYY/MM/DD")
'2024/03/15'
```

**Letters must be quoted** with single quotes to be used as literals.
This prevents accidental use of reserved characters and keeps options
open for future specifiers:

```python
>>> Date(2024, 3, 15).format("YYYY'xx'MM")
'2024xx03'
```

To include a literal single quote, use `''`:

```python
>>> Date(2024, 3, 15).format("YYYY''MM")
"2024'03"
```

### Restrictions

- **ASCII-only**: Pattern strings must contain only ASCII characters.
  Non-ASCII characters raise ``ValueError``.
- **Reserved characters**: `<`, `>`, `[`, `]`, `{`, `}`, and `#` cannot
  appear unquoted, except for brackets used by the optional-seconds syntax.
- **No duplicate fields**: A pattern cannot contain two specifiers that
  set the same value. For example, `MM` and `MMM` both set the month,
  so `"DD MM MMM YYYY"` is invalid.

## Parsing requirements

Parsed input strings must contain only ASCII characters.

Variable-width numeric fields must be separated from following digits. The
same rule applies to fields that omit optional digits, such as trimmed
fractions and the seconds component of `xxxx`/`xxxxx` offsets. `VV` must be
the final field or be followed by a literal delimiter that cannot occur in an
IANA timezone ID. A dotted trimmed fraction cannot be followed by another
dot. Ambiguous patterns raise {class}`ValueError` when compiled.

Some types require specific fields in the parse pattern:

- {meth}`OffsetDateTime.parse() <OffsetDateTime.parse>` requires an offset (`x`/`X`)
- {meth}`ZonedDateTime.parse() <ZonedDateTime.parse>` requires `VV` (timezone ID).
  An offset (`x`/`X`) is optional but recommended for DST disambiguation.
- {meth}`Instant.parse() <Instant.parse>` requires an offset (`x`/`X`)

All types that include date fields require `YYYY`, `MM`, and `DD`.

A second value of ``60`` (leap second) is accepted and normalized to ``59``.
See [](faq-leap-seconds) for details.

## Migrating patterns in 0.11

Version 0.11 accepts both the final spellings and the previous forms. Previous
forms emit {class}`WheneverDeprecationWarning` on every `format()` or `parse()`
call and will be rejected in 1.0.

| Previous pattern | Replacement |
|:-----------------|:------------|
| `h` | `H` |
| `hh` | `HH` |
| `:SS` | `[:ss]` |
| `:SS.FFF` | `[:ss.FFF]` |
| separator-free `SS` | `[ss]` |

The same bracketed spelling applies to exact fractions, such as replacing
`:SS.fff` with `[:ss.fff]`. Keeping the separator inside the brackets makes
it disappear with the seconds tail.

## Comparison with strftime

The following table maps common `strftime` directives to Whenever patterns:

| strftime | Pattern | Notes |
|:---------|:--------|:------|
| `%Y`   | `YYYY`|       |
| `%y`   | `YY`  | Format only |
| `%m`   | `MM`  |       |
| `%b`   | `MMM` |       |
| `%B`   | `MMMM`|       |
| `%d`   | `DD`  |       |
| `%a`   | `EEE` |       |
| `%A`   | `EEEE`|       |
| `%H`   | `HH`  | 24-hour clock |
| `%I`   | `ii`  | Note: `ii` = 12-hour |
| `%M`   | `mm`  |       |
| `%S`   | `ss`  |       |
| `%f`   | `ffffff`| microseconds (6 digits) |
| `%p`   | `aa`  |       |
| `%z`   | `xxxx` | `XXXX` for Z-style |
| `%:z`   | `xxxxx` | `XXXXX` for Z-style |
| `%Z`   | —     | Abbreviations are not supported for parsing. See {ref}`timezones-explained`. |

[^1]: `YY` is only supported for formatting. When parsing, use `YYYY` to avoid ambiguity.
[^2]: During parsing, weekday names are validated against the parsed date. A mismatch raises ``ValueError``.
[^3]: The complete bracketed tail is omitted when both seconds and nanoseconds are zero.
[^4]: Omitted when the value is zero, with preceding `.` also omitted.
[^5]: AM/PM is determined by the hour value. Using `i`/`ii` without `a`/`aa` emits a warning about ambiguity.
[^6]: Timezone abbreviations are ambiguous and not supported for parsing. Use `VV` (IANA timezone ID) instead. See {ref}`timezones-explained` for details.
