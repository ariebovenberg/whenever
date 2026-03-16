# Standard library conversions

```{eval-rst}
.. currentmodule:: whenever
```

Most classes have an equivalent in the Python standard library.
Use the `to_stdlib()` method to convert to the standard library equivalent,
or pass the standard library object directly to the constructor:

```python
>>> from datetime import *
>>> from whenever import *
>>> py_dt = datetime(2025, 4, 19, 15, 30, tzinfo=timezone.utc)
>>> instant = Instant(py_dt)
>>> instant.to_stdlib()
datetime.datetime(2025, 4, 19, 15, 30, tzinfo=datetime.timezone.utc)
```

| *whenever* class                | {mod}`datetime` equivalent                                   | *to* {mod}`datetime`                     |
|:--------------------------------|:-------------------------------------------------------------|------------------------------------------|
| {class}`Instant`                | {class}`~datetime.datetime` with {data}`~datetime.UTC`       | {meth}`~Instant.to_stdlib`               |
| {class}`ZonedDateTime`          | {class}`~datetime.datetime` with {class}`~zoneinfo.ZoneInfo` | {meth}`~ZonedDateTime.to_stdlib`    |
| {class}`OffsetDateTime`         | {class}`~datetime.datetime` with {class}`~datetime.timezone` | {meth}`~OffsetDateTime.to_stdlib`  |
| {class}`PlainDateTime`          | {class}`~datetime.datetime` (naive)                          | {meth}`~PlainDateTime.to_stdlib`    |
|                                 |                                                              |                                          |
| {class}`Date`                   | {class}`~datetime.date`                                      | {meth}`~Date.to_stdlib`                  |
| {class}`Time`                   | {class}`~datetime.time`                                      | {meth}`~Time.to_stdlib`                  |
| {class}`YearMonth`              | N/A                                                          | N/A                                      |
| {class}`MonthDay`               | N/A                                                          | N/A                                      |
|                                 |                                                              |                                          |
| {class}`TimeDelta`              | {class}`~datetime.timedelta`                                 | {meth}`~TimeDelta.to_stdlib`            |
| {class}`ItemizedDelta`          | N/A                                                          | N/A                                      |
| {class}`ItemizedDateDelta`      | N/A                                                          | N/A                                      |

```{note}

* There are some exceptions where the conversion is not exact; see the individual method documentation for details.
* Converting to the standard library is not always lossless.
  Nanoseconds will be truncated to microseconds.
* The constructor also accepts subclasses, so you can also ingest types
  from `pendulum` and `arrow` libraries.
```

```{admonition} FAQ
:class: hint

{ref}`faq-why-not-dropin`
```

There are no Python equivalents for the following classes:

- {class}`ItemizedDelta` and {class}`ItemizedDateDelta` cannot be converted to {class}`~datetime.timedelta`
  because they may contain calendar units,
  and because they store their components in unnormalized form, unlike {class}`~datetime.timedelta`.
- {class}`YearMonth` and {class}`MonthDay` cannot be converted
  because there is no direct equivalent in the standard library.
