(partial-api)=
# Partial types

```{eval-rst}
.. module:: whenever
   :no-index:

.. toctree::
   :maxdepth: 1
   :hidden:

   date
   time
   yearmonth
   monthday
   isoweekdate
```

This section describes the "smaller" date & time types provided by
`whenever`: {class}`Date`, {class}`Time`, {class}`YearMonth`, {class}`MonthDay`,
and {class}`IsoWeekDate`.

## Overview

| Type | Represents | Example |
|------|-----------|---------|
| {class}`Date` | A calendar date (year, month, day) | `Date(2024, 3, 15)` |
| {class}`Time` | A time of day (hour, minute, second…) | `Time(14, 30)` |
| {class}`YearMonth` | A year and month without a day | `YearMonth(2024, 3)` |
| {class}`MonthDay` | A month and day without a year | `MonthDay(3, 15)` |
| {class}`IsoWeekDate` | An ISO 8601 week date (year, week, weekday) | `IsoWeekDate(2024, 1, Weekday.MONDAY)` |

## Date

{class}`Date` represents a calendar date. It supports arithmetic with
{class}`ItemizedDateDelta` and calculating the difference between two dates:

```python
>>> d = Date(2023, 1, 31)
>>> d.add(months=1)         # End-of-month pinning
Date("2023-02-28")
>>> d.since(Date(2022, 10, 15), in_units=["months", "days"])
ItemizedDateDelta("P3m16d")
```

You can combine a {class}`Date` with a {class}`Time` to get a {class}`PlainDateTime`:

```python
>>> Date(2023, 6, 15).at(Time(9, 0))
PlainDateTime("2023-06-15T09:00:00")
```

## Time

{class}`Time` represents a time of day, independent of any date or timezone.
Sub-second precision is supported down to nanoseconds.

```python
>>> Time(14, 30, nanosecond=500_000_000)
Time("14:30:00.5")
```

## YearMonth and MonthDay

{class}`YearMonth` and {class}`MonthDay` are useful for recurring events or
partial date specifications (e.g. a birthday or an annual deadline):

```python
>>> YearMonth(2024, 3).on_day(22)
Date("2024-03-22")
>>> MonthDay(2, 29).in_year(2024)
Date("2024-02-29")
```
