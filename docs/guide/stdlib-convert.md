---
myst:
  html_meta:
    description: >-
      Converting between whenever types and their standard library equivalents
      with to_stdlib() and the constructors, how a datetime with a ZoneInfo is
      resolved, and which types have no stdlib counterpart.
---

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

| *whenever* class           | {mod}`datetime` equivalent                                   | *to* {mod}`datetime`              | *from* {mod}`datetime`                                              |
|:---------------------------|:-------------------------------------------------------------|:----------------------------------|:--------------------------------------------------------------------|
| {class}`Instant`           | {class}`~datetime.datetime` with {data}`~datetime.UTC`       | {meth}`~Instant.to_stdlib`        | `Instant(py_datetime)`                                              |
| {class}`ZonedDateTime`     | {class}`~datetime.datetime` with {class}`~zoneinfo.ZoneInfo` | {meth}`~ZonedDateTime.to_stdlib` [^system-tz] | `ZonedDateTime(py_datetime, disambiguation=, offset_mismatch=)` |
| {class}`OffsetDateTime`    | {class}`~datetime.datetime` with {class}`~datetime.timezone` | {meth}`~OffsetDateTime.to_stdlib` | `OffsetDateTime(py_datetime)`                                       |
| {class}`PlainDateTime`     | {class}`~datetime.datetime` (naive)                          | {meth}`~PlainDateTime.to_stdlib`  | `PlainDateTime(py_datetime)`                                        |
|                            |                                                              |                                   |                                                                     |
| {class}`Date`              | {class}`~datetime.date`                                      | {meth}`~Date.to_stdlib`           | `Date(py_date)`                                                     |
| {class}`Time`              | {class}`~datetime.time`                                      | {meth}`~Time.to_stdlib`           | `Time(py_time)`                                                     |
| {class}`YearMonth`         | N/A                                                          | N/A                               | N/A                                                                 |
| {class}`MonthDay`          | N/A                                                          | N/A                               | N/A                                                                 |
| {class}`IsoWeekDate`       | the {meth}`~datetime.date.isocalendar` result, a named tuple, not a type | via {meth}`~IsoWeekDate.date` | via `Date(py_date)`                                          |
|                            |                                                              |                                   |                                                                     |
| {class}`TimeDelta`         | {class}`~datetime.timedelta`                                 | {meth}`~TimeDelta.to_stdlib`      | `TimeDelta(py_timedelta)`                                           |
| {class}`ItemizedDelta`     | N/A                                                          | N/A                               | N/A                                                                 |
| {class}`ItemizedDateDelta` | N/A                                                          | N/A                               | N/A                                                                 |

[^system-tz]: A system time zone without a time zone ID converts to a
    fixed-offset `datetime`; see the admonition below.

```{note}

* There are some exceptions where the conversion is not exact; see the individual method documentation for details.
* Converting to the standard library is not always lossless.
  Nanoseconds are **floored** to microseconds.
```

```{warning}
Subclasses of the standard library types are accepted and read through the
standard library attributes, so data those attributes cannot represent is
lost. `pandas.Timestamp` and `pandas.Timedelta` carry nanoseconds;
`pendulum.Duration` carries months and years (and folds them into 30-day
days). Passing one of these emits a {class}`~whenever.WheneverWarning`.
Convert explicitly instead:
`Instant.from_timestamp(ts.value, unit="nanosecond")` for a
`pandas.Timestamp`, `TimeDelta(nanoseconds=td.value)` for a
`pandas.Timedelta`, and an {class}`~whenever.ItemizedDelta` built from the
`pendulum.Duration`'s components. A `datetime` given to {class}`Date` is the
same case: it is a `date` subclass whose time is dropped, so it warns; call
`.date()` first. A subclass that adds no data, such as freezegun's
`FakeDatetime`, passes silently.
```

```{admonition} Converting a datetime with a ZoneInfo
:class: note

{class}`~whenever.ZonedDateTime` reads such a datetime as local fields, the
offset its {class}`~zoneinfo.ZoneInfo` computes for them, and a time zone ID.
An ISO string with an offset and a time zone ID carries the same three things,
so both go through the same
{ref}`resolution flow <resolving-local-times>`. The constructor accepts
`offset_mismatch=` and `disambiguation=`, and raises
{exc}`~whenever.InvalidOffsetError` by default when the standard library's
rules and *whenever*'s own rules disagree.

{class}`~zoneinfo.ZoneInfo` subclasses are accepted. `timezone.utc`, pytz,
and dateutil tzinfos are rejected with {exc}`ValueError`, because they carry
no time zone ID: use `OffsetDateTime()` or `Instant()` for those.

`fold` is read through the offset on aware datetimes and set by
`to_stdlib()`, so both occurrences of a repeated local time round-trip. On
naive datetimes and on `time`, `fold` is ignored.

`to_stdlib()` hands the time zone ID to the standard library, which resolves
it on its own search path. A system time zone without a time zone ID gives a
fixed-offset {class}`~datetime.timezone` instead.
```

```{admonition} FAQ
:class: hint

{ref}`faq-why-not-dropin`
```

There are no Python equivalents for the following classes:

- {class}`ItemizedDelta` and {class}`ItemizedDateDelta` cannot be converted to {class}`~datetime.timedelta`
  because they may contain calendar units,
  and because they store their components in unnormalized form, unlike {class}`~datetime.timedelta`.
- {class}`YearMonth` and {class}`MonthDay` cannot be converted because there
  is no direct equivalent in the standard library. {class}`IsoWeekDate` has a
  named tuple, not a type, in the standard library: go through `.date()`.
