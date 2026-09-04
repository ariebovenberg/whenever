---
myst:
  html_meta:
    description: >-
      How equality and ordering work in whenever: exact types compare by moment in
      time, PlainDateTime never mixes with them, plus strict_eq() and nanosecond
      precision caveats.
---

# Comparison and equality

All types support equality and comparison.
However, {class}`~whenever.PlainDateTime` instances are
never equal or comparable to the "exact" types.

## Exact time

For exact types ({class}`~whenever.Instant`, {class}`~whenever.OffsetDateTime`,
{class}`~whenever.ZonedDateTime`),
comparison and equality are based on whether they represent the same moment in
time. This means that two objects with different values can be equal:

```python
>>> # different ways of representing the same moment in time
>>> inst = Instant.from_utc(2023, 12, 28, 11, 30)
>>> as_5hr_offset = OffsetDateTime(2023, 12, 28, 16, 30, offset=hours(5))
>>> as_8hr_offset = OffsetDateTime(2023, 12, 28, 19, 30, offset=hours(8))
>>> in_nyc = ZonedDateTime(2023, 12, 28, 6, 30, tz="America/New_York")
>>> # all equal
>>> inst == as_5hr_offset == as_8hr_offset == in_nyc
True
>>> # comparison
>>> in_nyc > OffsetDateTime(2023, 12, 28, 11, 30, offset=hours(5))
True
```

To also compare what `==` leaves out—here the local datetime and the
offset—use {meth}`~whenever.ZonedDateTime.strict_eq`. See
{ref}`strict-equality` below.

## Local time

For {class}`~whenever.PlainDateTime`, equality is simply based on
whether the values are the same, since there is no concept of timezones or UTC offset:

```python
>>> d = PlainDateTime(2023, 12, 28, 11, 30)
>>> same = PlainDateTime(2023, 12, 28, 11, 30)
>>> different = PlainDateTime(2023, 12, 28, 11, 31)
>>> d == same
True
>>> d == different
False
```

```{seealso}
See the documentation of {meth}`__eq__ (exact) <whenever.ZonedDateTime.__eq__>`
and {meth}`PlainDateTime.__eq__ <whenever.PlainDateTime.__eq__>` for more details.
```

(strict-equality)=
## Strict equality

Some types deliberately leave part of their value out of `==`. For those,
{term}`strict equality`—the `strict_eq()` method—compares that part as well.
It **refines** `==`: if `a.strict_eq(b)` holds, then `a == b` holds, but never
the other way around. An argument of a different type raises a
{exc}`TypeError`, because a cross-type call is nearly always a mistake.

The method exists on exactly the types whose `==` ignores something, and
compares exactly that in addition:

- {class}`~whenever.Instant`: the argument's type.
- {class}`~whenever.OffsetDateTime`: the type, the local datetime, and the
  offset.
- {class}`~whenever.ZonedDateTime`: the type, the local datetime, the offset,
  and the timezone—meaning its identifier (or the absence of one, for the
  system timezone) and its definition. Two values with the same timezone ID
  can carry different rules after a {func}`~whenever.clear_tzcache` or a
  {func}`~whenever.reset_tzpath`, and they are then not strictly equal.
- {class}`~whenever.ItemizedDelta` and {class}`~whenever.ItemizedDateDelta`:
  the type, and whether each component was given explicitly. An explicit zero
  is a component; `==` treats it as a missing one.

```python
>>> d = OffsetDateTime(2023, 12, 28, 11, 30, offset=hours(5))
>>> same = OffsetDateTime(2023, 12, 28, 11, 30, offset=hours(5))
>>> same_moment = OffsetDateTime(2023, 12, 28, 12, 30, offset=hours(6))
>>> d == same_moment
True
>>> d.strict_eq(same_moment)
False
>>> d.strict_eq(same)
True
```

The types whose `==` already compares every field—{class}`~whenever.PlainDateTime`,
{class}`~whenever.Date`, {class}`~whenever.Time`, {class}`~whenever.TimeDelta`,
{class}`~whenever.YearMonth`, {class}`~whenever.MonthDay`, and
{class}`~whenever.IsoWeekDate`—have no `strict_eq()`.

## Nanosecond precision and interoperability

Take care when comparing datetimes after interoperating with databases,
the Python standard library, or other systems that may not support nanosecond precision.
Since equality is based on full nanosecond precision,
two datetimes may no longer be equal after a round-trip that loses precision.

This may not be apparent in development if your system's clock only supports microsecond
precision (such as MacOS).

Use `.round('microsecond')` to explicitly round values to microsecond precision.

## Mixing local and exact types

Local and exact types are never equal or comparable to each other.
However, to comply with the Python data model, the equality operator
won't prevent you from using `==` to compare them.
To prevent these mix-ups, use mypy's [`--strict-equality` flag](https://mypy.readthedocs.io/en/stable/command_line.html#cmdoption-mypy-strict-equality).

```python
>>> # These are never equal, but Python won't stop you from comparing them.
>>> # Mypy will catch this mix-up if you use enable --strict-equality flag.
>>> Instant.from_utc(2023, 12, 28) == PlainDateTime(2023, 12, 28)
False
```

```{admonition} Why not raise a TypeError?
:class: hint

It may *seem* like the equality operator should raise a {exc}`TypeError`
in these cases, but this would result in
[surprising behavior](https://stackoverflow.com/a/33417512)
when using values as dictionary keys.
```

Unfortunately, mypy's `--strict-equality` is *very* strict,
forcing you to match exact types exactly.

```python

x = Instant.from_utc(2023, 12, 28, 10)

# mypy: ✅
x == Instant.from_utc(2023, 12, 28, 10)

# mypy: ❌ (too strict, this should be allowed)
x == OffsetDateTime(2023, 12, 28, 11, offset=hours(1))
```

To work around this, you can either convert explicitly:

```python
x == OffsetDateTime(2023, 12, 28, 11, offset=hours(1)).to_instant()
```

Or annotate the other value with a union:

```python
other: OffsetDateTime | Instant = OffsetDateTime(
    2023, 12, 28, 11, offset=hours(1)
)
x == other
```
