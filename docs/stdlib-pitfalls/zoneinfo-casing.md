---
hide-toc: true
myst:
  html_meta:
    description: >-
      Why ZoneInfo timezone identifiers are case-sensitive on some filesystems
      but not others, how that breaks portability and even arithmetic, and how
      whenever normalizes casing.
---

# Time zone casing is platform-dependent

{class}`zoneinfo.ZoneInfo` does not normalize IANA time zone identifiers.
It looks up the given string as a file path, so casing follows the underlying
filesystem. For example, this typically succeeds on macOS but fails on Linux:

```python
ZoneInfo("europe/amsterdam")
```

This makes validation non-portable. A value accepted during development can
be stored in a database or pickle, then fail with
{class}`~zoneinfo.ZoneInfoNotFoundError` in production. When lookup succeeds,
{attr}`ZoneInfo.key <zoneinfo.ZoneInfo.key>` also preserves the caller's
casing instead of returning the database spelling.

Even more surprisingly, two spellings can change arithmetic on a
case-insensitive filesystem:

```python
canonical = ZoneInfo("Europe/Amsterdam")
lowercase = ZoneInfo("europe/amsterdam")

canonical is lowercase
# False—even though they loaded the same time zone file

before = datetime(2024, 3, 31, 1, 30, tzinfo=canonical)
after1 = datetime(2024, 3, 31, 3, 30, tzinfo=canonical)
after2 = datetime(2024, 3, 31, 3, 30, tzinfo=lowercase)

after1 - before
# datetime.timedelta(seconds=7200)
after2 - before
# datetime.timedelta(seconds=3600)
```

This happens because `datetime` switches subtraction rules based on whether
the two `tzinfo` objects are identical. See {ref}`datetime-ignores-dst`.

The behavior is discussed in
[CPython issue #115022](https://github.com/python/cpython/issues/115022).
The IANA reference implementation is case-sensitive, although its
[naming rules](https://data.iana.org/time-zones/theory.html#naming) forbid
identifiers that differ only in case.

## How `whenever` solves this

Whenever matches ASCII casing portably and exposes the database spelling:

```python
>>> ZonedDateTime(2024, 3, 31, 3, 30, tz="europe/amsterdam")
ZonedDateTime("2024-03-31 03:30:00+02:00[Europe/Amsterdam]")
```

All casing variants also share one cached time zone definition, so casing
cannot change comparison or arithmetic behavior.
