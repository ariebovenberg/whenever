(durations)=
# Delta types

```{eval-rst}
.. currentmodule:: whenever

.. toctree::
    :maxdepth: 1
    :hidden:

    time_delta
    itemized_delta
    itemized_date_delta
```

As we've seen {ref}`earlier <add-subtract-time>`, you can add and subtract
time units from datetimes:

```python
dt.add(hours=5, minutes=30)
```

However, sometimes you want to operate on these durations directly.
For example, you might want to reuse a particular duration,
or perform arithmetic on it.
For this, `whenever` provides an API
designed to help you avoid common pitfalls.
The key concept is that there are **three different delta types**,
each suited for different use cases:

- Use {class}`TimeDelta` if you're working with {class}`Instant`
  or exact time units (hours, minutes, seconds). Similar to {class}`datetime.timedelta`.
- Use {class}`ItemizedDateDelta` if you're working {class}`Date` or
  only with calendar units (years, months, days).
- Use {class}`ItemizedDelta` if you need to work with *both* with calendar units
  (years, months, days) and exact time units (hours, minutes, seconds).

```{note}
{class}`ItemizedDelta` and {class}`ItemizedDateDelta` were introduced in version 0.10,
and replace the (now deprecated) {class}`DateTimeDelta` and {class}`DateDelta` classes.
```


Here is a summary of the three delta types provided,
and their key differences. Click on the features to learn more about them.

## Overview

| Feature |     {class}`TimeDelta`     | {class}`ItemizedDateDelta` | {class}`ItemizedDelta`   |
|:---------------|:--------------------------:|:---------------------------:|:------------------------:|
| {ref}`Supported units <delta-units>`  | exact units              | calendar units | exact *and* calendar units |         |
| {ref}`Normalized <delta-norm>`       | yes                      | no                          | no                       |
| {ref}`Equality <delta-eq>`          | {meth}`normalized <TimeDelta.__eq__>`     | {meth}`itemwise <ItemizedDateDelta.__eq__>`     | {meth}`itemwise <ItemizedDelta.__eq__>`     |
| {ref}`Convert to units <delta-in-units>`     | {meth}`~TimeDelta.in_units` | {meth}`~ItemizedDateDelta.in_units` [^1] | {meth}`~ItemizedDelta.in_units` [^1] |
| {ref}`Summing into one unit <delta-total>`     | {meth}`~TimeDelta.total` | {meth}`~ItemizedDateDelta.total` [^1] | {meth}`~ItemizedDelta.total` [^1] |
| {ref}`Comparison <delta-cmp>`           | {meth}`> <TimeDelta.__gt__>` , {meth}`< <TimeDelta.__lt__>` , {meth}`>= <TimeDelta.__ge__>` , {meth}`<= <TimeDelta.__le__>` | n/a                   | n/a                    |
| {ref}`Addition/subtraction <delta-add-sub>`  | {meth}`~TimeDelta.add` / {meth}`~TimeDelta.subtract` | {meth}`~ItemizedDateDelta.add` / {meth}`~ItemizedDateDelta.subtract` [^1] | {meth}`~ItemizedDelta.add` / {meth}`~ItemizedDelta.subtract` [^1] |
| {ref}`Operators <delta-operators>` | {meth}`+ <TimeDelta.__add__>` , {meth}`- <TimeDelta.__sub__>` , {meth}`* <TimeDelta.__mul__>` , {meth}`/ <TimeDelta.__truediv__>` , {meth}`// <TimeDelta.__floordiv__>` , {meth}`% <TimeDelta.__mod__>` | n/a                   | n/a                    |
| {ref}`Rounding <delta-rounding>` | {meth}`~TimeDelta.round`  | with {meth}`~ItemizedDateDelta.in_units`          | with {meth}`~ItemizedDelta.in_units`          |
| Applies to...     | {class}`ZonedDateTime` <br> {class}`OffsetDateTime` <br> {class}`PlainDateTime` <br> {class}`Instant` | {class}`ZonedDateTime` <br> {class}`OffsetDateTime` <br> {class}`PlainDateTime` <br> {class}`Date` | {class}`ZonedDateTime` <br> {class}`OffsetDateTime` <br> {class}`PlainDateTime` |

(delta-units)=
## Exact and calendar units

A key distinction when working with durations
is between {ref}`exact time units and calendar units <arithmetic2>`.

Exact time units are hours, minutes, and seconds.
These units have a fixed duration that doesn't change depending on context.
For example, an hour is always 60 minutes, and a minute is always 60 seconds.

Calendar units are years, months, weeks, and days.
These units can have a variable duration depending on context.
For example, a year can be 365 or 366 days, and a month can be 28, 29, 30, or 31 days.
More subtly, a day isn't always have 24 hours, as this can change
depending on Daylight Saving Time, for example.

Depending on the units you need to work with, you should choose the appropriate delta type:

- {class}`TimeDelta` for exact time units
- {class}`ItemizedDateDelta` for calendar units
- {class}`ItemizedDelta` for a combination of the two

(delta-norm)=
## Normalized or "itemized"

These delta classes also differ in how their components are stored.
"Itemized" deltas keep track of their individual components
(years, months, days, hours, minutes, seconds) separately, without normalizing them
into each other.

For example, an {class}`ItemizedDelta` of "1 hour and 90 minutes" will keep its components
as "1 hour" and "90 minutes", without converting the 90 minutes into 1 hour and 30 minutes.
This is essential when working with calendar units,
and sometimes useful when working with exact time units.

```python
>>> d = ItemizedDelta(hours=1, minutes=90)
ItemizedDelta("PT1h90m")
```

You can imagine this working like a `dict` of components, where each unit is a key and its value is the corresponding amount:

```
>>> dict(d)
{'hours': 1, 'minutes': 90}
```

{class}`TimeDelta`, on the other hand, normalizes all its components into each other.
So "1 hour and 90 minutes" becomes "2 hours and 30 minutes".
This enables easier arithmetic and comparisons,
as their duration is always the same.

```python
>>> d = TimeDelta(hours=1, minutes=90)
TimeDelta("PT2h30m")
```

You can imagine this working like a big `int` of nanoseconds internally, which is then converted back into the appropriate units when needed:

```python
>>> d.total("minutes")
150.0
>>> d.total("nanoseconds")
9000000000000
```

(delta-eq)=
## Equality

The difference between "itemized" and "normalized" is reflected in equality checks.
Itemized deltas are considered equal
only if all their individual components are the same:

```python
>>> ItemizedDelta(hours=1, minutes=90) == ItemizedDelta(hours=2, minutes=30)
False  # items are not the same
```

Normalized deltas are considered equal
if their total duration is the same, regardless of how their components are represented:

```python
>>> TimeDelta(hours=1, minutes=90) == TimeDelta(hours=2, minutes=30)
True  # normalized durations are the same
```


(delta-in-units)=
## Convert into specific units

All delta types can be converted into specific units using
their `in_units()` method. The output type is always {class}`ItemizedDelta`.
Its fields are guaranteed to be normalized, i.e. values will always "roll over"
into larger units where possible.

```python
>>> delta = TimeDelta(hours=3, minutes=2, seconds=5)
>>> delta.in_units(["minutes", "seconds"])
ItemizedDelta("PT182m5s")
>>> # deltas can also be unpacked directly:
>>> hours, minutes = delta.in_units(["hours", "minutes"])
(3, 2)
```

If you'd like to convert into a single unit instead, see the next section.

(delta-total)=
## Summing into a single unit

All delta types can also be summed into a single unit using
their `total()` method, which returns a `float`.

```python
>>> d = TimeDelta(hours=2, minutes=30, seconds=6)
>>> d.total("minutes")
150.1
```

When the total duration is requested in `"nanoseconds"` (the smallest supported unit),
`total()` returns an `int` instead of a `float` to avoid precision issues.

(delta-cmp)=
## Comparison

Only {class}`TimeDelta` supports comparison operators
(such as `>`, `<`, `>=`, and `<=`),
as these operations only make sense when exclusively working with exact time units:

```python
>>> TimeDelta(minutes=90) > TimeDelta(hours=1)
True
```

{class}`ItemizedDateDelta` and {class}`ItemizedDelta` do not support comparison operators,
as they may contain calendar units, which have variable durations depending on context.
For example, it's not possible to say whether "1 month" is greater than "30 days" in general.

```python
>>> a = ItemizedDateDelta(months=1)
>>> b = ItemizedDateDelta(days=30)
>>> a > b # TypeError
```

One way to compare itemized deltas is to convert them into one specific unit first,
using their `total()` method and a relative date or datetime context:

```python
>>> date = Date(2023, 1, 1)
>>> a.total("days", relative_to=date) > b.total("days", relative_to=date)
True
```

(delta-add-sub)=
## Addition and subtraction

All three delta types support addition and subtraction
using the {meth}`~ItemizedDelta.add` and {meth}`~ItemizedDelta.subtract` methods.
These methods return a new delta representing the sum or difference
of the two deltas:

```python
>>> TimeDelta(hours=2, minutes=30).add(hours=1)
TimeDelta("PT3h30m")
```

"Itemized" deltas do require a relative date or datetime context
to resolve calendar units when adding or subtracting.
For example, adding "1 month" to "30 days" requires knowing the starting date
to determine the resulting duration:

```python
>>> one_month = ItemizedDateDelta(months=1)
>>> one_month.add(days=30, relative_to=Date(2023, 1, 1))
ItemizedDateDelta("P2m2d")
>>> one_month.add(days=30, relative_to=Date(2023, 2, 28))
ItemizedDateDelta("P1m30d")
```

(delta-operators)=
## Operators

Mathematical operators such as `+`, `-`, `*`, and `/`
are only supported for {class}`TimeDelta`, as these operations
only make sense for exact time units.

```python
>>> delta = TimeDelta(hours=2, minutes=30)
>>> delta * 2
TimeDelta("PT5h")
>>> delta / 2
TimeDelta("PT1h15m")
```

Operators are not supported for itemized deltas,
as they may contain calendar units,
which have variable durations depending on context.

(delta-rounding)=
## Rounding

Only {class}`TimeDelta` has a {meth}`~TimeDelta.round` method for rounding to a specific unit:

```python
>>> delta = TimeDelta(hours=2, minutes=30, seconds=3)
>>> delta.round("hour")
TimeDelta("PT3h")
```

Rounding an itemized delta can only be done by also normalizing it,
using the {meth}`~ItemizedDelta.in_units` method:

```python
>>> delta = ItemizedDelta(days=7, hours=2, minutes=84)
>>> delta.in_units(["days", "hours"], rounding_mode="ceil", round_increment=4)
ItemizedDelta("P7dT4h")
```

See {ref}`rounding` for more information on rounding modes and increments.

(iso8601-durations)=
## ISO 8601 format

The ISO 8601 standard defines formats for specifying durations,
the [most common](https://en.wikipedia.org/wiki/ISO_8601#Durations) being:

```text
±P nY nM nD T nH nM nS     (spaces added for clarity)
```

Where:

- ``P`` is the period designator, and ``T`` separates date and time components.
- ``nY`` is the number of years, ``nM`` is the number of months, etc.
- Only seconds may have a fractional part.
- At least one component must be present (it may be zero).

For example:

- ``P3Y4DT12H30M`` is 3 years, 4 days, 12 hours, and 30 minutes.
- ``-P2M5D`` is -2 months, and -5 days.
- ``P0D`` is zero.
- ``+PT5M4.25S`` is 5 minutes and 4.25 seconds.

All deltas can be converted to and from this format using the methods:

| Delta Type            | Format Method                     | Parse Method                      |
|-----------------------|----------------------------------|----------------------------------|
| {class}`TimeDelta`         | {meth}`~TimeDelta.format_iso`       | {meth}`~TimeDelta.parse_iso`       |
| {class}`ItemizedDateDelta` | {meth}`~ItemizedDateDelta.format_iso` | {meth}`~ItemizedDateDelta.parse_iso` |
| {class}`ItemizedDelta`     | {meth}`~ItemizedDelta.format_iso`     | {meth}`~ItemizedDelta.parse_iso`     |


```python
>>> hours(3).format_iso()
'PT3H'
>>> ItemizedDelta(years=-1, months=-3, minutes=-30.25).format_iso()
'-P1Y3MT30M15S'
>>> ItemizedDateDelta('-P2M')
ItemizedDateDelta("-P2m")
>>> ItemizedDelta.parse_iso('P3YT90M')
ItemizedDelta("P3yT90m")
```

```{admonition} Why not support the full ISO 8601 standard?
:class: hint

Full conformance to the ISO 8601 standard is not provided, because:

- It allows for a lot of unnecessary flexibility
    (e.g. fractional components other than seconds)
- There are different revisions with different rules
- The full specification is not freely available

Supporting a commonly used subset is more practical.
This is also what all established libraries do.
```

## Equivalents in other languages

The three delta types in `whenever` are similar to those in other languages:

| Library          | {class}`TimeDelta`   | {class}`ItemizedDateDelta`   | {class}`ItemizedDelta`  |
|------------------|----------------------|------------------------------|-------------------------|
| NodaTime (C#)    | `Duration`           | [^2]                         | `Period`                |
| java.time (Java) | `Duration`           | `Period`                     | `PeriodDuration` [^3]   |
| Jiff (Rust)      | `SignedDuration`     |                              | `Span`                  |
| Temporal (JS)    |                      |                              | `Duration`              |


[^1]: These operations require a relative date or datetime context to resolve
      calendar units.
[^2]: The autor of NodaTime has been tempted to [include it](https://github.com/nodatime/nodatime/issues/1435#issuecomment-547855819) though
[^3]: Part of the [ThreeTen-Extra](https://www.threeten.org/threeten-extra/) library by the same author.
