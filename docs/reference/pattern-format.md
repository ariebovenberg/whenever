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
...     "EEE, DD MMM YYYY hh:mm:ssxxx"
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

### Time specifiers


| Symbol  | Meaning                    | Pattern | Example output |
|:---------|:---------------------------|:---------------|:--------------|
| `h` | hour | `h` <br/> `hh` | `4` <br/> `04` |
| `i`   | hour (12-hour) | `i` <br/> `ii` | `4` <br/> `04` |
| `m`   | minute | `m` <br/> `mm` | `5` <br/> `05` |
| `s`   | second | `s` <br/> `ss` | `5` <br/> `05` |
| `S`   | second, optional [^3] | `SS` | `05`, (omitted) |
| `f` | fractional seconds, exact digits | `f`<br/>`ff`<br/>`fff`<br/>...<br/>`fffffffff` | `1` <br/> `12`, `00` <br/> `123`, `400` <br/> ... <br/> `123456789`, `374930000` |
| `F` | fractional seconds, trimmed [^4] | `F`<br/>`FF`<br/>`FFF`<br/>...<br/>`FFFFFFFFF` | `1` <br/> `12`, (omitted) <br/> `123`, `4` <br/>...<br/> `123456789`, `37493` |
| `a`   | AM/PM [^5] | `a`<br/>`aa` | `P` <br/> `PM` |

:::{admonition} Optional seconds
:class: hint

`SS` omits the seconds component entirely when **both** seconds *and*
nanoseconds are zero, allowing compact times like `14:30` alongside full
times like `14:30:05` in the same format string.

- When seconds *or* nanoseconds are non-zero, `SS` writes two zero-padded
  digits
- When **both are zero**, nothing is written. Any preceeding colon disappears as well.


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

:::

### Offset and timezone specifiers

See {ref}`timezones-explained` for background on timezones, offsets, and abbreviations.

| Symbol  | Meaning                    | Pattern | Example output |
|:---------|:---------------------------|:---------------|:--------------|
| `x` | Offset hours and minutes | `x` <br/> `xx` <br/> `xxx` <br/> `xxxx` <br/> `xxxxx` | `+02` <br/> `+0230` <br/> `+02:30` <br/> `+023045` <br/> `+02:30:45` |
| `X` | Offset hours and minutes, with `Z` for zero offset | `X` <br/> `XX` <br/> `XXX` <br/> `XXXX` <br/> `XXXXX` | `+02` <br/> `+0230` <br/> `+02:30` <br/> `+023045` <br/> `+02:30:45` or `Z` when zero |
| `V` | IANA timezone ID | `VV` | `Europe/Paris` |
| `z` | Timezone abbreviation [^6] | `zz` | `CET`, `CEST` |

```{admonition} Choosing between x and X
:class: hint

Use uppercase `X` when you want `Z` for zero offset
(e.g. {class}`Instant` formatting).
Use lowercase `x` when you always want a numeric offset
(e.g. {class}`OffsetDateTime` formatting).
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
| `%a`   | `EEE` |       |
| `%A`   | `EEEE`|       |
| `%H`   | `hh`  | Note: `hh` = 24-hour |
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
[^3]: Omitted when both seconds and nanoseconds are zero.
[^4]: Omitted when the value is zero, with preceding `.` also omitted.
[^5]: AM/PM is determined by the hour value. Using `i`/`ii` without `a`/`aa` emits a warning about ambiguity.
[^6]: Timezone abbreviations are ambiguous and not supported for parsing. Use `VV` (IANA timezone ID) instead. See {ref}`timezones-explained` for details.
