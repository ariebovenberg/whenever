---
myst:
  html_meta:
    description: >-
      API reference for whenever's delta types: TimeDelta, ItemizedDelta, and
      ItemizedDateDelta, and how to construct and operate on them.
---

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

```{tip}
For the motivation behind the three types and help choosing one, start with
{ref}`guide-deltas`. This page documents their complete behavior.
```

## Overview

| Feature |     {class}`TimeDelta`     | {class}`ItemizedDateDelta` | {class}`ItemizedDelta`   |
|:---------------|:--------------------------:|:---------------------------:|:------------------------:|
| {ref}`Supported units <delta-units>`  | exact units              | calendar units | exact *and* calendar units |
| {ref}`Normalized <delta-norm>`       | yes                      | no                          | no                       |
| {ref}`Equality <delta-eq>`          | {meth}`normalized <TimeDelta.__eq__>`     | {meth}`itemwise <ItemizedDateDelta.__eq__>`     | {meth}`itemwise <ItemizedDelta.__eq__>`     |
| {ref}`Convert to units <delta-in-units>`     | {meth}`~TimeDelta.in_units` | {meth}`~ItemizedDateDelta.in_units` [^1] | {meth}`~ItemizedDelta.in_units` [^1] |
| {ref}`Summing into one unit <delta-total>`     | {meth}`~TimeDelta.total` | {meth}`~ItemizedDateDelta.total` [^1] | {meth}`~ItemizedDelta.total` [^1] |
| {ref}`Comparison <delta-cmp>`           | {meth}`> <TimeDelta.__gt__>` , {meth}`< <TimeDelta.__lt__>` , {meth}`>= <TimeDelta.__ge__>` , {meth}`<= <TimeDelta.__le__>` | n/a                   | n/a                    |
| {ref}`Addition/subtraction <delta-add-sub>`  | {meth}`~TimeDelta.add` / {meth}`~TimeDelta.subtract` | {meth}`~ItemizedDateDelta.add` / {meth}`~ItemizedDateDelta.subtract` | {meth}`~ItemizedDelta.add` / {meth}`~ItemizedDelta.subtract` |
| {ref}`Operators <delta-operators>` | {meth}`+ <TimeDelta.__add__>` , {meth}`- <TimeDelta.__sub__>` , {meth}`* <TimeDelta.__mul__>` , {meth}`/ <TimeDelta.__truediv__>` , {meth}`// <TimeDelta.__floordiv__>` , {meth}`% <TimeDelta.__mod__>` , unary {meth}`- <TimeDelta.__neg__>` and {meth}`+ <TimeDelta.__pos__>` , {meth}`abs() <TimeDelta.__abs__>` | {meth}`+ <ItemizedDateDelta.__add__>` , {meth}`- <ItemizedDateDelta.__sub__>` , unary {meth}`- <ItemizedDateDelta.__neg__>` , {meth}`abs() <ItemizedDateDelta.__abs__>` | {meth}`+ <ItemizedDelta.__add__>` , {meth}`- <ItemizedDelta.__sub__>` , unary {meth}`- <ItemizedDelta.__neg__>` , {meth}`abs() <ItemizedDelta.__abs__>` |
| {ref}`Rounding <delta-rounding>` | {meth}`~TimeDelta.round`  | with {meth}`~ItemizedDateDelta.in_units`          | with {meth}`~ItemizedDelta.in_units`          |
| {ref}`Replace components <delta-norm>` | n/a | {meth}`~ItemizedDateDelta.replace` | {meth}`~ItemizedDelta.replace` |
| Applies to...     | {class}`ZonedDateTime` <br> {class}`OffsetDateTime` <br> {class}`PlainDateTime` <br> {class}`Instant` | {class}`ZonedDateTime` <br> {class}`OffsetDateTime` <br> {class}`PlainDateTime` <br> {class}`Date` | {class}`ZonedDateTime` <br> {class}`OffsetDateTime` <br> {class}`PlainDateTime` |
| Similar to... | {class}`~datetime.timedelta` | {class}`~collections.Counter` | {class}`~collections.Counter` |

(delta-units)=
## Exact and calendar units

The delta types accept these unit categories:

- **Exact units** (hours, minutes, seconds) have a fixed duration.
- **Calendar units** (years, months, weeks, days) have a variable duration
  depending on context (e.g. leap years, DST).

See {ref}`the fundamentals <arithmetic2>` for exact versus calendar semantics
and {ref}`guide-deltas` for choosing a delta type.

(delta-norm)=
## Normalized or "itemized"

{class}`ItemizedDateDelta` and {class}`ItemizedDelta` store their individual
components
(years, months, weeks, days, hours, minutes, seconds, nanoseconds) separately,
without normalizing them into each other.

You can imagine this working like a `dict` or {class}`~collections.Counter` of components,
where each unit is a key and its value is the corresponding amount:

```
>>> dict(d)
{'hours': 1, 'minutes': 90}
```

Unlike a `Counter`, an absent component raises `KeyError` rather than
counting as zero, and `+` keeps zero components instead of dropping them.

Iteration always runs from the largest unit to the smallest and includes only
the components you gave. Explicit zeroes remain present:

```python
>>> list(ItemizedDelta(seconds=0, hours=2))
['hours', 'seconds']
```

The one exception is `seconds`, which `nanoseconds` brings with it; see
{ref}`delta-subsecond`.

{class}`TimeDelta` instead normalizes all its components into one exact
duration. See {ref}`guide-deltas` for a side-by-side example.

For the same reason, {class}`TimeDelta` has no `replace()`: a normalized
delta is one quantity, so build a new one or add to it. The itemized deltas
replace and remove components with {meth}`~ItemizedDelta.replace`:

```python
>>> ItemizedDelta(hours=1, minutes=90).replace(minutes=None, seconds=30)
ItemizedDelta("PT1h30s")
```

(delta-subsecond)=
### Seconds and nanoseconds

Seconds and nanoseconds are one quantity written as two components, the way
ISO 8601 writes `PT1.5S` as one number. Keeping `90 minutes` unbalanced
against hours preserves something you asked for; keeping nanoseconds
unbalanced against seconds would preserve nothing. Five rules follow:

- There are no `milliseconds` or `microseconds` components. Use
  {meth}`~ItemizedDelta.total` for a scalar in those units. It returns a
  `float`, except for `"nanoseconds"`, which returns an `int`:

  ```python
  >>> d = ItemizedDelta(seconds=1, nanoseconds=234_567_890)
  >>> reference = PlainDateTime(2024, 1, 1)
  >>> d.total("milliseconds", relative_to=reference)
  1234.56789
  >>> d.total("microseconds", relative_to=reference)
  1234567.89
  >>> d.total("nanoseconds", relative_to=reference)
  1234567890
  ```

- `nanoseconds` is bounded to 999,999,999, under the delta's single sign.
  Whole seconds go in `seconds`:

  ```python
  >>> ItemizedDelta(nanoseconds=1_500_000_000)
  ValueError: nanoseconds must be within ±999,999,999; put whole seconds in seconds=
  ```

- A present `nanoseconds` brings a present `seconds`, because the ISO 8601
  fraction needs a seconds value to attach to:

  ```python
  >>> dict(ItemizedDelta(nanoseconds=5))
  {'seconds': 0, 'nanoseconds': 5}
  ```

- Presence survives the ISO 8601 round trip. `seconds=0` formats as `PT0S`,
  while `nanoseconds=0` formats as `PT0.0S`, and parsing reads the fraction
  back as a present `nanoseconds`:

  ```python
  >>> ItemizedDelta(seconds=0).format_iso()
  'PT0S'
  >>> ItemizedDelta(nanoseconds=0).format_iso()
  'PT0.0S'
  >>> dict(ItemizedDelta.parse_iso("PT0.0S"))
  {'seconds': 0, 'nanoseconds': 0}
  ```

- Component-wise composition carries and borrows between `seconds` and
  `nanoseconds`, and between those two only:

  ```python
  >>> ItemizedDelta(nanoseconds=999_999_999).add(nanoseconds=1)
  ItemizedDelta("PT1.0s")
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
True  # normalized deltas are the same
```

The two itemized types compare equal when their components are, so a date
delta equals the same delta with its exact components zero or absent:

```python
>>> ItemizedDelta(days=3, hours=0) == ItemizedDateDelta(days=3)
True
```

Use {meth}`~ItemizedDelta.strict_eq` when explicit component presence
matters (see {ref}`strict-equality`); it takes only a delta of its own type,
and raises {exc}`TypeError` for the other. `hash()` follows `==`, so an
explicit zero hashes like a missing component, and equal deltas of the two
types hash alike.
Constructors currently require at least one component, so construct an
itemized zero with an explicit component such as `ItemizedDelta(seconds=0)` or
`ItemizedDateDelta(days=0)`. Allowing empty constructors may be considered as
an additive change after 1.0.

(delta-sign)=
## Sign

All delta types carry a single sign that applies to every component
uniformly—there are no mixed-sign deltas.

```python
>>> ItemizedDelta(months=-3, days=-10, hours=-5)
ItemizedDelta("-P3m10dT5h")
>>> -ItemizedDateDelta(years=1, months=6)
ItemizedDateDelta("-P1y6m")
```

Negating a delta flips the sign of all components at once:

```python
>>> d = ItemizedDelta(hours=2, minutes=30)
>>> -d
ItemizedDelta("-PT2h30m")
```

{class}`TimeDelta` also has a single sign, but may be constructed
with mixed-sign components, as they will be normalized into a single sign automatically:

```python
>>> d = TimeDelta(hours=1, minutes=-15)
>>> d
TimeDelta("PT45m")
```

(delta-in-units)=
## Convert into specific units

All delta types can be converted into specific units using their
{meth}`~TimeDelta.in_units` method (and its itemized-delta equivalents).
This is sometimes called "balancing"—redistributing the value
across the requested units:

```python
>>> delta = TimeDelta(hours=3, minutes=2, seconds=5)
>>> delta.in_units(["minutes", "seconds"])
ItemizedDelta("PT182m5s")
>>> # deltas can also be unpacked directly:
>>> hours, minutes = delta.in_units(["hours", "minutes"]).values()
(3, 2)
```

For example, 150 minutes balanced into hours and minutes:

```python
>>> hours, minutes = TimeDelta(minutes=150).in_units(["hours", "minutes"]).values()
(2, 30)
```

Rounding applies to the smallest unit and carries into the larger ones:
23.5 hours rounded up in days and hours is 1 day and 0 hours, never 24 hours.
With `round_increment=`, the smallest unit is a multiple of the increment,
and rounding it up to the next unit carries: 5 hours 20 minutes in hours and
minutes with an increment of 90 is `PT5h0m`, or `PT6h0m` with
`round_mode="ceil"`.

`"nanoseconds"` is accepted only together with `"seconds"`:
the component is bounded, so it cannot hold a difference on its own
(see {ref}`delta-subsecond`).

```{tip}
If you need the difference between two datetimes in specific units,
use {meth}`~ZonedDateTime.since` / {meth}`~ZonedDateTime.until`
instead of computing a delta and converting it.
See {ref}`arithmetic`.
```

If you'd like to convert into a single unit instead, see the next section.

(delta-total)=
## Summing into a single unit

All delta types can also be summed into a single unit using their
{meth}`~TimeDelta.total` method (and its itemized-delta equivalents), which
returns a `float`, or an `int` for `"nanoseconds"`.

```python
>>> d = TimeDelta(hours=2, minutes=30, seconds=6)
>>> d.total("minutes")
150.1
```

When the total duration is requested in `"nanoseconds"` (the smallest
supported unit), {meth}`~TimeDelta.total` returns an `int` instead of a `float`
to avoid precision issues. {meth}`~ItemizedDelta.total` also accepts
`"milliseconds"` and `"microseconds"`, which have no itemized component; see
{ref}`delta-subsecond`.

```{note}
For {class}`ItemizedDelta` and {class}`ItemizedDateDelta`,
both `in_units()` and `total()` require a `relative_to` parameter to
resolve calendar units.
This is because calendar units have variable lengths—``1 month`` is
28, 29, 30, or 31 days depending on the starting date—so the conversion
can only be performed with a concrete reference point.
See the individual class reference pages for details.
```

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

The itemized deltas compose **component-wise**: like components add up,
and the result stays itemized, so `1 month` plus `30 days` is
`1 month 30 days` whatever the month. To balance the result, call
{meth}`~ItemizedDelta.in_units` on it with a reference:

```python
>>> summed = ItemizedDateDelta(months=1).add(days=30, month_composition_ok=True)
>>> summed
ItemizedDateDelta("P1m30d")
>>> summed.in_units(["months", "days"], relative_to=Date(2023, 1, 1))
ItemizedDateDelta("P2m2d")
>>> summed.in_units(["months", "days"], relative_to=Date(2023, 2, 28))
ItemizedDateDelta("P1m30d")
```

The operands decide the result type: two {class}`ItemizedDateDelta`
operands give an {class}`ItemizedDateDelta`, and any {class}`ItemizedDelta`
operand gives an {class}`ItemizedDelta`.

Composing years or months emits {class}`~whenever.MonthCompositionWarning`,
which `month_composition_ok=True` accepts. A month clamps at the end of the
month, so the composed delta can land on a different day than the deltas
applied in turn; {ref}`delta-composition` shows an example. Days, weeks, and
exact units never clamp, and compose without a warning.

Each reference type on {meth}`~ItemizedDelta.in_units`,
{meth}`~ItemizedDelta.total`, {meth}`~TimeDelta.in_units`, and
{meth}`~TimeDelta.total` has its own warning:

- A {class}`ZonedDateTime` resolves calendar units in its time zone and
  emits no warning.
- A {class}`PlainDateTime` ignores time zone transitions. It emits
  {class}`~whenever.NaiveArithmeticWarning` when the computation crosses the
  calendar/exact boundary, which `naive_arithmetic_ok=True` accepts.
- An {class}`OffsetDateTime` holds its offset fixed for the whole
  calculation. It emits {class}`~whenever.StaleOffsetWarning` when calendar
  units are involved, which `stale_offset_ok=True` accepts.

An {class}`ItemizedDateDelta` reads only the date of a datetime reference,
without a warning.

(delta-operators)=
## Operators

{class}`TimeDelta` follows the numeric protocol, as
{class}`~datetime.timedelta` does: `*`, `/`, `//`, `%`, and unary `+` exist
on it alone, since scaling only makes sense for one exact duration.
Multiplying or dividing by a number rounds half-even to the nearest
nanosecond; an integer operand is exact, a `float` operand carries float
precision. A float keyword to the constructor or `add()` is multiplied
into nanoseconds in double precision, then truncated toward zero:
`TimeDelta(seconds=1.5e-9)` is 1 nanosecond, where
`TimeDelta(seconds=1) * 1.5e-9` rounds to 2. Dividing by another `TimeDelta` gives a `float`; `//` and `%`
take a `TimeDelta` divisor only.

```python
>>> delta = TimeDelta(hours=2, minutes=30)
>>> delta * 2
TimeDelta("PT5h")
>>> delta / 2
TimeDelta("PT1h15m")
>>> delta / TimeDelta(minutes=30)
5.0
>>> delta // TimeDelta(hours=1), delta % TimeDelta(hours=1)
(2, TimeDelta("PT30m"))
```

The itemized deltas are mappings, not numbers: they have `+`, `-`, unary
`-`, and `abs()`. The binary operators compose component-wise, with the
same {class}`~whenever.MonthCompositionWarning` as the methods; only the
methods take `month_composition_ok=True`. An itemized
delta has one sign, so a composition that leaves components of both signs
raises {class}`ValueError`: `ItemizedDelta(hours=1) + ItemizedDelta(minutes=-90)`
is rejected with "mixed sign in delta". To split a delta into its date and
time halves, use {meth}`~ItemizedDelta.date_and_time_parts`.

`sign()` exists where ordering does not: the itemized deltas cannot be
compared, so it is how you read their sign, whereas a `TimeDelta` compares
with `TimeDelta.ZERO`.

Dates and datetimes support applying an itemized delta with `+` and `-`.
Addition is also commutative in spelling, so both `datetime + delta` and
`delta + datetime` are supported. Applying one delta composes nothing, so
these operations never emit `MonthCompositionWarning`.
As with the equivalent `add()` and `subtract()` methods, calendar units are
applied before exact units, and years and months clamp; so adding and then
subtracting the same delta is not always reversible.

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
>>> delta.in_units(
...     ["days", "hours"],
...     relative_to=ZonedDateTime(2020, 1, 1, tz="UTC"),
...     round_mode="ceil",
...     round_increment=4
... )
ItemizedDelta("P7dT4h")
```

See {ref}`rounding` for more information on rounding modes and increments.

(iso8601-durations)=
## ISO 8601 format

The ISO 8601 standard defines formats for specifying durations,
the [most common](https://en.wikipedia.org/wiki/ISO_8601#Durations) being:

```text
±P nY nM nW nD T nH nM nS     (spaces added for clarity)
```

Where:

- ``P`` is the period designator, and ``T`` separates date and time components.
- ``nY`` is the number of years, ``nM`` is the number of months, ``nW`` the
  number of weeks, etc.
- Only seconds may have a fractional part.
- At least one component must be present (it may be zero).

For example:

- ``P3Y4DT12H30M`` is 3 years, 4 days, 12 hours, and 30 minutes.
- ``-P2M5D`` is -2 months, and -5 days.
- ``P0D`` is zero for the itemized deltas. {meth}`TimeDelta.parse_iso` rejects
  it, with ``P1D`` and ``P1W``, since days and weeks are calendar units.
- ``+PT5M4.25S`` is 5 minutes and 4.25 seconds.

All deltas can be converted to and from this format using the methods:

| Delta Type            | Format Method                     | Parse Method                      |
|-----------------------|----------------------------------|----------------------------------|
| {class}`TimeDelta`         | {meth}`~TimeDelta.format_iso`       | {meth}`~TimeDelta.parse_iso`       |
| {class}`ItemizedDateDelta` | {meth}`~ItemizedDateDelta.format_iso` | {meth}`~ItemizedDateDelta.parse_iso` |
| {class}`ItemizedDelta`     | {meth}`~ItemizedDelta.format_iso`     | {meth}`~ItemizedDelta.parse_iso`     |


```python
>>> TimeDelta(hours=3).format_iso()
'PT3H'
>>> ItemizedDelta(years=-1, months=-3, seconds=-15).format_iso()
'-P1Y3MT15S'
>>> ItemizedDateDelta.parse_iso('-P2M')
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
[^2]: The author of NodaTime has been tempted to [include it](https://github.com/nodatime/nodatime/issues/1435#issuecomment-547855819) though
[^3]: Part of the [ThreeTen-Extra](https://www.threeten.org/threeten-extra/) library by the same author.
