(pattern-format)=
# Pattern format

```{eval-rst}
.. currentmodule:: whenever
```

Custom format and parse patterns allow you to format datetime values into
strings and parse strings into datetime values, using a pattern string
that describes the expected format.

## Quick example

```python
>>> from whenever import Date, Time, OffsetDateTime, hours
>>> Date(2024, 3, 15).format("YYYY/MM/DD")
'2024/03/15'
>>> Date.parse("2024/03/15", format="YYYY/MM/DD")
Date("2024-03-15")
>>> OffsetDateTime(2024, 3, 15, 14, 30, offset=+2).format(
...     "ddd, DD MMM YYYY hh:mm:ssxxx"
... )
'Fri, 15 Mar 2024 14:30:00+02:00'
```

## Specifiers

Each pattern is a string containing specifiers and literal text.
Specifiers are sequences of the same letter that are replaced by
the corresponding value.

### Date specifiers

| Pattern  | Meaning                    | Example output | Parse support |
|:---------|:---------------------------|:---------------|:--------------|
| `YYYY` | 4-digit year, zero-padded  | `2024`       | ✅            |
| `YY`   | 2-digit year               | `24`         | ❌ format only |
| `MM`   | Month number (01–12)       | `03`         | ✅            |
| `MMM`  | Abbreviated month name     | `Mar`        | ✅ (case-insensitive) |
| `MMMM` | Full month name            | `March`      | ✅ (case-insensitive) |
| `DD`   | Day of month (01–31)       | `15`         | ✅            |
| `ddd`  | Abbreviated weekday name   | `Fri`        | ✅ (validated) |
| `dddd` | Full weekday name          | `Friday`     | ✅ (validated) |

```{note}
When parsing, weekday names (`ddd`/`dddd`) are validated against the
parsed date. A mismatch raises ``ValueError``.
```

```{note}
`YY` is only supported for formatting. When parsing, use `YYYY` to
avoid ambiguity.
```

### Time specifiers

| Pattern     | Meaning                         | Example output  | Parse support |
|:------------|:--------------------------------|:----------------|:--------------|
| `hh`      | 24-hour hour (00–23)            | `14`          | ✅            |
| `ii`      | 12-hour hour (01–12)            | `02`          | ⚠️ (should pair with `aa`)
| `mm`      | Minute (00–59)                  | `30`          | ✅            |
| `ss`      | Second (00–59)                  | `05`          | ✅            |
| `f`–`fffffffff` | Fractional seconds, exact digits | `123` (`fff`) | ✅ |
| `F`–`FFFFFFFFF` | Fractional seconds, trimmed     | `12` (`FFF`) | ✅ |
| `a`       | AM/PM first character           | `P`           | ✅            |
| `aa`      | AM/PM full                      | `PM`          | ✅            |

```{important}
- `hh` is the **24-hour** format. `ii` is the **12-hour** format.
- Using `hh` with `a`/`aa` (AM/PM) raises an error—use `ii` instead.
- Using `ii` without `a`/`aa` emits a warning about ambiguity.
```

**Fractional seconds:**

- `f` specifies the *exact* number of digits. `fff` always writes 3 digits.
- `F` specifies the *maximum* digits, with trailing zeros trimmed.
  `FFF` writes 1–3 digits, or nothing if the value is zero
  (and also trims a preceding `.`).

```python
>>> Time(14, 30, 5, nanosecond=120_000_000).format("hh:mm:ss.fff")
'14:30:05.120'
>>> Time(14, 30, 5, nanosecond=120_000_000).format("hh:mm:ss.FFF")
'14:30:05.12'
>>> Time(14, 30, 5).format("hh:mm:ss.FFF")
'14:30:05'
```

### Offset and timezone specifiers

See {ref}`timezones-explained` for background on timezones, offsets, and abbreviations.

**Offset specifiers (`x`/`X`):**

| Pattern     | Meaning                                    | Example output | Parse support |
|:------------|:-------------------------------------------|:---------------|:--------------|
| `x`       | Offset hours only                          | `+02`        | ✅            |
| `xx`      | Offset hours+minutes, compact              | `+0230`      | ✅            |
| `xxx`     | Offset hours:minutes                       | `+02:30`     | ✅            |
| `xxxx`    | Compact, optional seconds                  | `+023045`    | ✅            |
| `xxxxx`   | With colons, optional seconds              | `+02:30:45`  | ✅            |
| `X`–`XXXXX` | Same as `x`–`xxxxx`, but `Z` for zero offset | `+02:30`, `Z`     | ✅            |

Lowercase `x` always produces a numeric offset.
Uppercase `X` substitutes `Z` when the offset is exactly zero.
For widths 4 and 5, seconds are only displayed when non-zero.

**Timezone specifiers:**

| Pattern | Meaning              | Example output   | Parse support |
|:--------|:---------------------|:-----------------|:--------------|
| `VV`  | IANA timezone ID       | `Europe/Paris` | ✅            |
| `zz`  | Timezone abbreviation  | `CET`, `CEST`  | ❌ format only |

```{admonition} Choosing between x and X
:class: hint

Use uppercase `X` when you want `Z` for zero offset
(e.g. {class}`Instant` formatting).
Use lowercase `x` when you always want a numeric offset
(e.g. {class}`OffsetDateTime` formatting).
Both accept `Z` when parsing with uppercase `X`.
```

```{note}
`zz` (timezone abbreviation) is only supported for formatting—abbreviations
are ambiguous and cannot be reliably used for parsing. Use `VV` (IANA timezone
ID) instead. See {ref}`timezones-explained` for why abbreviations are unreliable.
```

```python
>>> ZonedDateTime(2024, 7, 15, 14, 30, tz="Europe/Paris").format(
...     "YYYY-MM-DD hh:mm zz"
... )
'2024-07-15 14:30 CEST'
>>> ZonedDateTime.parse(
...     "2024-07-15 14:30+02:00[Europe/Paris]",
...     format="YYYY-MM-DD hh:mmxxx'['VV']'",
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
- **Reserved characters**: `<`, `>`, `[`, `]`, `{`, `}`, and `#`
  are reserved for future use and cannot appear unquoted.
- **No duplicate fields**: A pattern cannot contain two specifiers that
  set the same value. For example, `MM` and `MMM` both set the month,
  so `"DD MM MMM YYYY"` is invalid.

## Parsing requirements

Some types require specific fields in the parse pattern:

- {meth}`OffsetDateTime.parse() <OffsetDateTime.parse>` requires an offset (`x`/`X`)
- {meth}`ZonedDateTime.parse() <ZonedDateTime.parse>` requires `VV` (timezone ID).
  An offset (`x`/`X`) is optional but recommended for DST disambiguation.
- {meth}`Instant.parse() <Instant.parse>` requires an offset (`x`/`X`)

All types that include date fields require `YYYY`, `MM`, and `DD`.

## Comparison with strftime

The {meth}`~OffsetDateTime.parse_strptime` methods on {class}`OffsetDateTime` and
{class}`PlainDateTime` are deprecated in favor of
{meth}`~OffsetDateTime.parse`. Here's a migration guide:

| strftime | Pattern | Notes |
|:---------|:--------|:------|
| `%Y`   | `YYYY`|       |
| `%y`   | `YY`  | Format only |
| `%m`   | `MM`  |       |
| `%b`   | `MMM` |       |
| `%B`   | `MMMM`|       |
| `%d`   | `DD`  |       |
| `%a`   | `ddd` |       |
| `%A`   | `dddd`|       |
| `%H`   | `hh`  | Note: `hh` = 24-hour |
| `%I`   | `ii`  | Note: `ii` = 12-hour |
| `%M`   | `mm`  |       |
| `%S`   | `ss`  |       |
| `%f`   | `ffffff`| microseconds (6 digits) |
| `%p`   | `aa`  |       |
| `%z`   | `xxx` | `XXX` for Z-style |
| `%Z`   | —     | Abbreviations are not supported for parsing. See {ref}`timezones-explained`. |
