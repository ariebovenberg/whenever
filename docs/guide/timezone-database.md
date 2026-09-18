---
myst:
  html_meta:
    description: >-
      How whenever finds IANA time zone data: the time zone search path from
      PYTHONTZPATH and its tzdata fallback, case-insensitive time zone IDs,
      get_tzpath() and reset_tzpath(), and the definition cache with
      clear_tzcache().
---

(timezone-database)=
# Working with the time zone database

`whenever` loads named time zones from the IANA time zone database installed on
your system. It uses the configured **time zone search path** (see
{func}`~whenever.get_tzpath`) first and falls back to the `tzdata` package
when it is installed. {func}`~whenever.available_timezones` lists the time
zone IDs those sources provide.

## Time zone IDs

Time zone IDs are matched case-insensitively for ASCII letters.
After a successful lookup, `whenever` uses the spelling from the selected
database in `tz_id`, representations, ISO output, and pickles:

```python
>>> ZonedDateTime(2024, 1, 1, tz="europe/amsterdam").tz_id
'Europe/Amsterdam'
```

This normalizes spelling only; aliases are not replaced by the IDs they
link to.
For example, `us/eastern` becomes `US/Eastern`, not `America/New_York`.
An ID that no configured source knows raises
{exc}`~whenever.TimeZoneNotFoundError`, a `ValueError`, so the same
`except ValueError` that catches a malformed string catches an unknown ID.
This holds wherever an ID is read: `tz=`, the bracket of an ISO string, the
`VV` pattern specifier, and the {class}`~zoneinfo.ZoneInfo` of a `datetime`.

## Transitions

{meth}`~whenever.ZonedDateTime.next_transition` and
{meth}`~whenever.ZonedDateTime.prev_transition` step to the nearest change of
the time zone's rules, returned as the first instant at which the new rules
apply. A change of the UTC offset, the DST offset, or the abbreviation counts.
They return `None` where nothing changes any more: UTC and fixed offsets, and
before the first recorded change; a time zone with daylight saving has a next
transition for every year through 9999. The step is strict, so a datetime
sitting on a transition is not its own previous transition. The methods hang
off a datetime because `whenever` has no time zone type of its own.

## Choosing time zone data

Use {func}`~whenever.reset_tzpath` to replace the search path with one or more
absolute directories. Sources are searched in order, so the first source with
a matching ID wins.

```python
from whenever import reset_tzpath

reset_tzpath(["/srv/app/tzdata", "/usr/share/zoneinfo"])
```

The configured directories are trusted database locations. A database that
contains IDs differing only by ASCII case is unsupported; the selected
entry is unspecified. Lookup examines only the directory components of the
requested ID rather than indexing the complete database.

The initial search path comes from the `PYTHONTZPATH` environment variable,
falling back to the interpreter's compiled-in `TZPATH`: the same sources
{mod}`zoneinfo` reads. Entries that are not absolute paths are ignored.
Calling {func}`~whenever.reset_tzpath` with no argument reads them again.
{func}`~whenever.get_tzpath` returns a snapshot: the tuple it returned does
not change when the path is reset later.

## Cache behavior

Loaded time zone definitions are cached. Changing the time zone search path
does not change existing datetimes or discard already loaded definitions. If
you need new lookups to use the replacement database, clear the relevant
entries after changing the path:

```python
from whenever import clear_tzcache, reset_tzpath

reset_tzpath(["/srv/app/tzdata"])
clear_tzcache()
```

`clear_tzcache(only_keys=[...])` also matches IDs case-insensitively.
Clearing a cache can make otherwise identical time zone IDs refer to different
database versions, so use it only when updating time zone data deliberately.
