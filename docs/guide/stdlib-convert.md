# Standard library conversions

```{eval-rst}
.. currentmodule:: whenever
```

Most classes have an equivalent in the Python standard library.
They have `from_py_*` and `py_*` methods for conversion to and from these classes.
Their constructors also accept the equivalent standard library class:

```python
>>> from datetime import *
>>> from whenever import *
>>> py_dt = datetime(2025, 4, 19, 15, 30, tzinfo=timezone.utc)
>>> instant = Instant(py_dt)
```

| *whenever* class                | {mod}`datetime` equivalent                                   | *from* {mod}`datetime`                   | *to* {mod}`datetime`                   |
|:--------------------------------|:-------------------------------------------------------------|------------------------------------------|----------------------------------------|
| {class}`Instant`                | {class}`~datetime.datetime` with {data}`~datetime.UTC`       | {meth}`~Instant.from_py_datetime`        | {meth}`~Instant.py_datetime`           |
| {class}`ZonedDateTime`          | {class}`~datetime.datetime` with {class}`~zoneinfo.ZoneInfo` | {meth}`~ZonedDateTime.from_py_datetime`  | {meth}`~ZonedDateTime.py_datetime`     |
| {class}`OffsetDateTime`         | {class}`~datetime.datetime` with {class}`~datetime.timezone` | {meth}`~OffsetDateTime.from_py_datetime` | {meth}`~OffsetDateTime.py_datetime`    |
| {class}`PlainDateTime`          | {class}`~datetime.datetime` (naive)                          | {meth}`~PlainDateTime.from_py_datetime`  | {meth}`~PlainDateTime.py_datetime`     |
|                                 |                                                              |                                          |                                        |
| {class}`Date`                   | {class}`~datetime.date`                                      | {meth}`~Date.from_py_date`               | {meth}`~Date.py_date`                  |
| {class}`Time`                   | {class}`~datetime.time`                                      | {meth}`~Time.from_py_time`               | {meth}`~Time.py_time`                  |
| {class}`YearMonth`              | N/A                                                          | N/A                                      | N/A                                    |
| {class}`MonthDay`               | N/A                                                          | N/A                                      | N/A                                    |
|                                 |                                                              |                                          |                                        |
| {class}`TimeDelta`              | {class}`~datetime.timedelta`                                 | {meth}`~TimeDelta.from_py_timedelta`     | {meth}`~TimeDelta.py_timedelta`        |
| {class}`ItemizedDelta`          | N/A                                                          | N/A                                      | N/A                                    |
| {class}`ItemizedDateDelta`      | N/A                                                          | N/A                                      | N/A                                    |

```{note}

* There are some exceptions where the conversion is not exact; see the individual method documentation for details.
* Converting to the standard library is not always lossless.
  Nanoseconds will be truncated to microseconds.
* `from_py_datetime` also works for subclasses, so you can also ingest types
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
