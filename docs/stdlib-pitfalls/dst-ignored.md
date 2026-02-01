---
hide-toc: true
---

(datetime-ignores-dst)=
# Operators ignore DST

Arithmetic with `datetime` usually ignores daylight saving time (DST) transitions,
operating as if the local clock runs uniformly throughout the year.

Here's an example:

```python
bedtime = datetime(2023, 3, 25, 22, tzinfo=ZoneInfo("Europe/Paris"))
full_rest = bedtime + timedelta(hours=8)
# It returns 6am, but should be 7am—because we skipped an hour due to DST!
```

You'd expect that going through all the effort of specifying a time zone
would yield correct results around DST transitions.
However, arithmetic is always performed in terms of *local time*,
not *exact (elapsed) time*.

This behavior has surprised many users over the years,
as evidenced by repeated discussions in Python's issue tracker.
Unfortunately, it cannot be changed without breaking existing code.

What's more surprising, is that DST *is* considered in some cases.
When subtracting two aware datetimes **with different time zones**:

```python
dt1 - dt2  # DST-aware *only if* time zones differ
```

This means that DST handling depends not just on the operation,
but on whether the time zones involved are the same—an extremely subtle rule.
As a result, a common recommendation is to perform all arithmetic in UTC
and convert to local time only for display.

## How `whenever` solves this

Whenever performs arithmetic in an intuitive, {ref}`DST-safe <arithmetic2>`, manner by default:

```python
>>> bedtime = ZonedDateTime(2023, 3, 25, 22, tz="Europe/Paris")
>>> bedtime.add(hours=8)
ZonedDateTime("2023-03-26 07:00:00+02:00[Europe/Paris]")  # correct!
```
