# Partial types

Aside from the datetimes themselves, `whenever` also provides
{class}`~whenever.Date` for calendar dates and {class}`~whenever.Time` for
representing times of day.

```python
>>> from whenever import Date, Time
>>> Date(2023, 1, 1)
Date("2023-01-01")
>>> Time(12, 30)
Time("12:30:00")
```

These types can be converted to datetimes and vice versa:

```python
>>> Date(2023, 1, 1).at(Time(12, 30))
PlainDateTime("2023-01-01 12:30:00")
>>> ZonedDateTime.now("Asia/Tokyo").date()
Date("2023-07-13")
```

Dates support arithmetic and calculating differences,
with similar semantics to modern datetime libraries:

```python
>>> d = Date(2023, 1, 31)
>>> d.add(months=1)
Date("2023-02-28")
>>> d.since(Date(2022, 10, 15), in_units=["months", "days"])
ItemizedDateDelta("P3m16d")
```

There's also {class}`~whenever.YearMonth` and {class}`~whenever.MonthDay` for representing
year-month and month-day combinations, respectively.
These are useful for representing recurring events or birthdays.

{class}`~whenever.IsoWeekDate` represents a date in the ISO 8601 week date system:

```python
>>> Date(2024, 12, 30).iso_week_date()
IsoWeekDate("2025-W01-1")
```

See the {ref}`API reference <partial-api>` for more details.
