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
| `MM`   | Month number (01–12), zero-padded | `03`  | ✅ (exactly 2 digits) |
| `M`    | Month number (1–12), no padding   | `3`   | ✅ (1–2 digits) |
| `MMM`  | Abbreviated month name     | `Mar`        | ✅ (case-insensitive) |
| `MMMM` | Full month name            | `March`      | ✅ (case-insensitive) |
| `DD`   | Day of month (01–31), zero-padded | `05`  | ✅ (exactly 2 digits) |
| `D`    | Day of month (1–31), no padding   | `5`   | ✅ (1–2 digits) |
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
| `hh`      | 24-hour (00–23), zero-padded    | `04`, `14`    | ✅ (exactly 2 digits) |
| `h`       | 24-hour (0–23), no padding      | `4`, `14`     | ✅ (1–2 digits)  |
| `ii`      | 12-hour (01–12), zero-padded    | `04`, `12`    | ⚠️ (should pair with `aa`) |
| `i`       | 12-hour (1–12), no padding      | `4`, `12`     | ⚠️ (should pair with `aa`) |
| `mm`      | Minute (00–59), zero-padded     | `05`, `30`    | ✅ (exactly 2 digits) |
| `m`       | Minute (0–59), no padding       | `5`, `30`     | ✅ (1–2 digits)  |
| `ss`      | Second (00–59), zero-padded     | `05`, `45`    | ✅ (exactly 2 digits) |
| `s`       | Second (0–59), no padding       | `5`, `45`     | ✅ (1–2 digits)  |
| `SS`      | Second, optional (see below)    | `05`, `` (omitted) | ✅ |
| `f`–`fffffffff` | Fractional seconds, exact digits | `123` (`fff`) | ✅ |
| `F`–`FFFFFFFFF` | Fractional seconds, trimmed     | `12` (`FFF`) | ✅ |
| `a`       | AM/PM first character           | `P`           | ✅            |
| `aa`      | AM/PM full                      | `PM`          | ✅            |

```{important}
- `hh`/`h` are the **24-hour** formats. `ii`/`i` are the **12-hour** formats.
- Using `h`/`hh` with `a`/`aa` (AM/PM) raises an error—use `i`/`ii` instead.
- Using `i`/`ii` without `a`/`aa` emits a warning about ambiguity.
- The double-letter forms (`hh`, `ii`, `mm`, `ss`) always zero-pad and require
  exactly 2 digits when parsing. The single-letter forms (`h`, `i`, `m`, `s`)
  skip zero-padding and accept 1–2 digits when parsing.
```

**Optional seconds (`SS`):**

`SS` omits the seconds component entirely when **both** seconds *and*
nanoseconds are zero, allowing compact times like `14:30` alongside full
times like `14:30:05` in the same format string.

- When seconds *or* nanoseconds are non-zero, `SS` writes two zero-padded
  digits; `:SS` additionally writes the preceding colon.
- When **both are zero**, nothing is written. The colon disappears with `:SS`
  (unlike a bare `:` literal, which would always be written).
- During parsing, `SS` reads two digits if the next character is a digit;
  `:SS` reads `:` followed by two digits if the next character is `:`.
  In both cases, if the expected character is absent, seconds is set to zero.

```{important}
Omission requires *both* seconds **and** nanoseconds to be zero. If you have
fractional seconds (e.g. `14:30:00.5`), `SS` will write `00` (not omit).
If you want compact times and don't need fractional seconds, call
{meth}`~whenever.Time.round` first.
```

```python
>>> Time(14, 30, 0).format("hh:mm:SS")
'14:30'
>>> Time(14, 30, 5).format("hh:mm:SS")
'14:30:05'
>>> Time(14, 30, 0, nanosecond=500_000_000).format("hh:mm:SS")
'14:30:00'
>>> Time(14, 30, 0).format("hh:mm:SS.FFF")
'14:30'
>>> Time(14, 30, 0, nanosecond=500_000_000).format("hh:mm:SS.FFF")
'14:30:00.5'
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
| `%z`   | `xxxx` | `XXXX` for Z-style |
| `%:z`   | `xxxxx` | `XXXXX` for Z-style |
| `%Z`   | —     | Abbreviations are not supported for parsing. See {ref}`timezones-explained`. |
