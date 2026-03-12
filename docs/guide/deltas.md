(guide-deltas)=
# Working with deltas

```{eval-rst}
.. currentmodule:: whenever
```

This page gives a conceptual overview of the delta types in `whenever`.
For the full API reference, see {ref}`durations`.

## Three types for three use cases

`whenever` provides three delta types because durations
have fundamentally different arithmetic rules depending on the units involved
(see the {ref}`FAQ <faq-why-3-deltas>` for the reasoning):

| Type | Units | When to use |
|---|---|---|
| {class}`TimeDelta` | hours, minutes, seconds, … | Measuring exact elapsed time |
| {class}`ItemizedDateDelta` | years, months, weeks, days | Calendar arithmetic (e.g. "3 months from now") |
| {class}`ItemizedDelta` | all of the above | Display, ISO 8601 round-tripping, mixed durations |

Most of the time you won't create delta objects directly—you'll use
`add()`, `subtract()`, `since()`, and `until()` on datetime and date objects.
But deltas become useful when you need to *reuse* a duration, pass it around,
or inspect its components.

## Normalized vs. itemized

{class}`TimeDelta` **normalizes** its components: `90 minutes` automatically
becomes `1 hour 30 minutes`.
This makes comparison and arithmetic straightforward.

{class}`ItemizedDateDelta` and {class}`ItemizedDelta` keep their components
**itemized**: `1 month` stays `1 month`, not `30 days`.
This is essential because calendar units have variable lengths—a month can be
28, 29, 30, or 31 days depending on when you start.

```python
>>> TimeDelta(hours=1, minutes=90)
TimeDelta("PT2h30m")          # normalized: 2 hours 30 minutes
>>> ItemizedDelta(hours=1, minutes=90)
ItemizedDelta("PT1h90m")      # itemized: components kept as-is
```

## Calendar units need context

Because `1 month` has a variable number of days,
operations that convert between calendar and exact units require a
**reference date** (the `relative_to` parameter).

```python
>>> d = ItemizedDateDelta(months=1)
>>> d.total("days", relative_to=Date(2024, 1, 15))   # January → February
31
>>> d.total("days", relative_to=Date(2024, 2, 15))   # February → March
29   # 2024 is a leap year
```

The same applies to {meth}`~ItemizedDateDelta.in_units`,
{meth}`~ItemizedDateDelta.add`, and {meth}`~ItemizedDateDelta.subtract`
when calendar units are involved.

## Balancing into different units

"Balancing" means redistributing a delta's value across a new set of units.
Use `in_units()`:

```python
>>> td = TimeDelta(minutes=150)
>>> td.in_units(["hours", "minutes"]).values()
(2, 30)
```

For itemized deltas with calendar units, balancing requires a reference date:

```python
>>> d = ItemizedDateDelta(days=400)
>>> d.in_units(["years", "months", "days"], relative_to=Date(2024, 1, 1)).values()
(1, 1, 3)
```

## Sign

All deltas carry a single sign that applies to every component.
There are no mixed-sign deltas:

```python
>>> -ItemizedDateDelta(years=1, months=6)
ItemizedDateDelta("-P1y6m")
```

See {ref}`delta-sign` for more details.

## Next steps

- {ref}`arithmetic` — adding and subtracting time from datetimes
- {ref}`durations` — full API reference for all three delta types
