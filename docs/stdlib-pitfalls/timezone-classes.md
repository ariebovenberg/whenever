---
hide-toc: true
---

# `timezone` isn't enough

Python offers multiple time zone-related classes, and choosing the right one is not obvious.

Your first instinct might be **{class}`datetime.timezone`**. After all, its name suggests it represents time zones.
However, this class only supports fixed offsets from UTC. This is not nearly enough to
represent real-world time zones, which have complex rules for daylight saving time and historical changes.

Perhaps you should use the **`pytz.timezone`** class from the popular third-party library `pytz`?
You could, but it has a [notoriously tricky API](https://blog.ganssle.io/articles/2018/03/pytz-fastest-footgun.html)
that can lead to mistakes if not used carefully.

In the end, what you probably want is the slightly jargon-y **{class}`zoneinfo.ZoneInfo`** class from the standard library,
introduced in Python 3.9. This class provides access to the IANA time zone database,
allowing you to work with real-world time zones accurately.

The reason for this confusion is historical:
when `datetime` was designed, the IANA time zone database was not as widely adopted as it is today.
In the meantime, third-party libraries like `pytz` filled the gap.
Today, `zoneinfo` is the correct choice for most applications—but the older
names remain, and `pytz` is still widely used, adding to the confusion.

## How `whenever` solves this

Whenever uses the IANA time zone database by default:

```python
>>> from whenever import ZonedDateTime
>>> zdt = ZonedDateTime(2024, 3, 10, 15, tz="America/New_York")
ZonedDateTime("2024-03-10 15:00:00-04:00[America/New_York]")
```

Additionally, fixed-offset datetimes are explicitly represented with a separate class,
so there's no confusion which class to use for full-featured time zones versus fixed offsets:

```python
>>> from whenever import OffsetDateTime
>>> odt = OffsetDateTime(2024, 3, 10, 15, offset=-4)
OffsetDateTime("2024-03-10 15:00:00-04:00")
```
