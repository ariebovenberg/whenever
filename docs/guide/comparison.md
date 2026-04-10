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
>>> as_5hr_offset = OffsetDateTime(2023, 12, 28, 16, 30, offset=5)
>>> as_8hr_offset = OffsetDateTime(2023, 12, 28, 19, 30, offset=8)
>>> in_nyc = ZonedDateTime(2023, 12, 28, 6, 30, tz="America/New_York")
>>> # all equal
>>> inst == as_5hr_offset == as_8hr_offset == in_nyc
True
>>> # comparison
>>> in_nyc > OffsetDateTime(2023, 12, 28, 11, 30, offset=5)
True
```

Note that if you want to compare for exact equality on the values
(i.e. exactly the same year, month, day, hour, minute, etc.), you can use
the {meth}`~whenever.ZonedDateTime.exact_eq` method.

```python
>>> d = OffsetDateTime(2023, 12, 28, 11, 30, offset=5)
>>> same = OffsetDateTime(2023, 12, 28, 11, 30, offset=5)
>>> same_moment = OffsetDateTime(2023, 12, 28, 12, 30, offset=6)
>>> d == same_moment
True
>>> d.exact_eq(same_moment)
False
>>> d.exact_eq(same)
True
```

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

## Sub-second precision and equality

When using the equality operator (`==`), `whenever` compares all components of
a datetime, including its sub-second precision down to nanoseconds.

This can cause unexpected results. For example, PostgreSQL stores datetimes with
microsecond precision (6 digits), not nanosecond precision (9 digits).
If you save an {class}`~whenever.Instant` with nanosecond precision to
PostgreSQL and then retrieve it, the retrieved value will not be equal
to the original value.

```python
>>> # An original instant with nanosecond precision
>>> i = Instant.now()
>>> i
Instant("2026-04-10 12:34:56.789123456Z")
>>> # After being saved to and retrieved from a microsecond-only database:
>>> retrieved = Instant.from_utc(2026, 4, 10, 12, 34, 56, nanosecond=789123000)
>>> i == retrieved
False
```

macOS does not support nanosecond precision, so this error may not appear in development.

To work around this, you can use the {meth}`~whenever.ZonedDateTime.round`
method to explicitly normalize the precision before comparing:

```python
>>> # Explicitly round to microsecond precision
>>> i = Instant.now().round("microsecond")
>>> # now it will match what's stored in a microsecond-only database
>>> i == retrieved_from_db
True
```

## Strict equality

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
x == OffsetDateTime(2023, 12, 28, 11, offset=1)
```

To work around this, you can either convert explicitly:

```python
x == OffsetDateTime(2023, 12, 28, 11, offset=1).to_instant()
```

Or annotate with a union:

```python
x: OffsetDateTime | Instant == OffsetDateTime(2023, 12, 28, 11, offset=1)
```
