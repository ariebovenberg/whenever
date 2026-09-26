---
myst:
  html_meta:
    description: >-
      Working with Date, Time, YearMonth, MonthDay, and IsoWeekDate: date
      arithmetic, combining them into datetimes and splitting them again,
      and finding nearby dates.
---

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

## Combining and splitting

{meth}`Date.at() <whenever.Date.at>` and {meth}`Time.on() <whenever.Time.on>`
combine a date and a time into a {class}`~whenever.PlainDateTime`. That is a
local time without a time zone, so reaching an exact type takes a second step:
{meth}`~whenever.PlainDateTime.assume_tz` (or
{meth}`~whenever.PlainDateTime.assume_utc`,
{meth}`~whenever.PlainDateTime.assume_fixed_offset`):

```python
>>> Date(2023, 1, 1).at(Time(12, 30))
PlainDateTime("2023-01-01 12:30:00")
>>> Time(12, 30).on(Date(2023, 1, 1)).assume_tz("Europe/Paris")
ZonedDateTime("2023-01-01 12:30:00+01:00[Europe/Paris]")
```

`date()` and `time()` split a datetime the other way:

```python
>>> dt = ZonedDateTime(2023, 7, 13, 9, 0, tz="Asia/Tokyo")
>>> dt.date()
Date("2023-07-13")
>>> dt.time()
Time("09:00:00")
```

{meth}`~whenever.Date.year_month` and {meth}`~whenever.Date.month_day`
project a date onto its parts, and {meth}`~whenever.YearMonth.on_day` and
{meth}`~whenever.MonthDay.in_year` complete them again.
{meth}`~whenever.Date.iso_week_date` and
{meth}`IsoWeekDate.date() <whenever.IsoWeekDate.date>` round-trip:

```python
>>> d = Date(2024, 12, 30)
>>> d.year_month().on_day(15)
Date("2024-12-15")
>>> d.month_day().in_year(2025)
Date("2025-12-30")
>>> d.iso_week_date().date() == d
True
```

Every partial type has `replace()`, which swaps fields and raises
`ValueError` for a result that is not a valid date or time:

```python
>>> Date(2024, 1, 31).replace(month=3)
Date("2024-03-31")
>>> Time(12, 30).replace(hour=8)
Time("08:30:00")
```

## Nearby dates

{class}`~whenever.Date` steps and searches from a date:

```python
>>> d = Date(2024, 8, 15)  # a Thursday
>>> d.next_day()
Date("2024-08-16")
>>> d.prev_day()
Date("2024-08-14")
>>> d.nth_weekday(1, Weekday.FRIDAY)
Date("2024-08-16")
>>> d.nth_weekday(-2, Weekday.THURSDAY)  # exclusive: not the date itself
Date("2024-08-01")
>>> d.nth_weekday_of_month(-1, Weekday.MONDAY)
Date("2024-08-26")
```

{meth}`~whenever.Date.nth_weekday` counts from the date exclusively, unlike
dateutil's `FR(+1)`, which counts the date itself when it matches; negative
`n` searches backward. {meth}`~whenever.Date.nth_weekday_of_month` counts
occurrences within the date's month and raises `ValueError` for one the
month does not have, such as a fifth Monday in a month with four. A
datetime navigates through its date:
`dt.replace_date(dt.date().nth_weekday(1, Weekday.FRIDAY))`.

See the {ref}`API reference <partial-api>` for more details.
