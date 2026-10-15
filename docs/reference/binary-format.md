---
myst:
  html_meta:
    description: >-
      The binary format that to_bytes() writes and from_bytes() reads: the
      fixed-size little-endian layout of Date, Time, PlainDateTime, Instant,
      TimeDelta, OffsetDateTime, and ZonedDateTime, which pickles and the C
      API share.
---

(binary-format)=
# Binary format

Seven types serialize to a few bytes with `to_bytes()` and read them back
with `from_bytes()`: {class}`~whenever.Date`, {class}`~whenever.Time`,
{class}`~whenever.PlainDateTime`, {class}`~whenever.Instant`,
{class}`~whenever.TimeDelta`, {class}`~whenever.OffsetDateTime`, and
{class}`~whenever.ZonedDateTime`.

```python
>>> Date(2024, 2, 29).to_bytes()
b'\xe8\x07\x02\x1d'
>>> Date.from_bytes(b'\xe8\x07\x02\x1d')
Date(2024-02-29)
```

The bytes are the payload a pickle of the value carries, so the format is
the one pickles have used since 0.8.0. Both backends write identical bytes.
The {ref}`C API <c-api>` hands out the same fields as C structs.

The format suits what `pickle` does not: a column of a binary file, a key
in a store, a message to code in another language. A pickle names the
unpickling function and trusts whatever it loads; `from_bytes()` reads a
fixed layout and validates every field.

## Layout

Every integer is little-endian, and there is no padding.

| Type             | Bytes   | Fields                                                                      |
|------------------|---------|-----------------------------------------------------------------------------|
| `Date`           | 4       | `u16` year, `u8` month, `u8` day                                            |
| `Time`           | 7       | `u8` hour, `u8` minute, `u8` second, `u32` nanosecond                       |
| `PlainDateTime`  | 11      | `Date`, then `Time`                                                         |
| `Instant`        | 12      | `i64` seconds since the Unix epoch, `u32` nanosecond                        |
| `TimeDelta`      | 12      | `i64` seconds, `u32` nanosecond                                             |
| `OffsetDateTime` | 15      | `PlainDateTime`, then `i32` offset in seconds                               |
| `ZonedDateTime`  | 15 + ID | `OffsetDateTime`, then the time zone ID in ASCII                            |

A `TimeDelta` is `seconds * 10⁹ + nanosecond` in total, with the nanosecond
never negative: one nanosecond before zero is `-1` seconds and
`999_999_999` nanoseconds.

A `ZonedDateTime` carries its local fields and the offset it was written
with, not the instant: the same shape as its ISO 8601 string. The time zone
ID follows the fixed 15-byte prefix without a terminator or a length; it is
1 to 99 bytes long, in the spelling of the time zone database. A
`ZonedDateTime` whose system time zone has no time zone ID cannot be
written (see {ref}`systemtime`).

## Reading

`from_bytes()` raises `ValueError` for a payload of the wrong length or
with a field out of range: a 30th of February, a nanosecond of 10⁹, an
offset of 24 hours. The bytes are the format's whole contract: a payload that
parses is a valid value.

`ZonedDateTime.from_bytes()` resolves the stored offset against the time
zone rules of the reading machine, as `parse_iso()` resolves a written
offset. When the rules changed in between, the offset may identify no
occurrence of the local time, and `offset_mismatch=` decides. Under
`"keep_local"`, `disambiguation=` then settles a repeated or skipped local
time. See {ref}`offset-mismatch`. Unpickling the same payload
keeps the instant and warns instead, because `pickle.loads()` takes no
arguments (see {ref}`pickling`).

## Stability

The layouts above never change: a 1.x release reads every payload an
earlier one wrote, and writes the same bytes for the same value. A type
added later gets a format of its own. See {ref}`stability`.
