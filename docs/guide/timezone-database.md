(timezone-database)=
# Working with the timezone database

`whenever` loads named timezones from the IANA timezone database installed on
your system. It uses the configured timezone search path (`TZPATH`) first and
falls back to the `tzdata` package when it is installed.

## Timezone identifiers

IANA timezone identifiers are matched case-insensitively for ASCII letters.
After a successful lookup, `whenever` uses the spelling from the selected
database in `tz_id`, representations, ISO output, and pickles:

```python
>>> ZonedDateTime(2024, 1, 1, tz="europe/amsterdam").tz_id
'Europe/Amsterdam'
```

This normalizes spelling only; it does not replace aliases with primary zones.
For example, `us/eastern` becomes `US/Eastern`, not `America/New_York`.

## Choosing timezone data

Use {func}`~whenever.reset_tzpath` to replace the search path with one or more
absolute directories. Sources are searched in order, so the first source with
a matching identifier wins.

```python
from whenever import reset_tzpath

reset_tzpath(["/srv/app/tzdata", "/usr/share/zoneinfo"])
```

The configured directories are trusted database locations. A database that
contains identifiers differing only by ASCII case is unsupported; the selected
entry is unspecified. Lookup examines only the directory components of the
requested identifier rather than indexing the complete database.

## Cache behavior

Loaded timezone definitions are cached. Changing `TZPATH` does not change
existing datetimes or discard already loaded definitions. If you need new
lookups to use the replacement database, clear the relevant entries after
changing the path:

```python
from whenever import clear_tzcache, reset_tzpath

reset_tzpath(["/srv/app/tzdata"])
clear_tzcache()
```

`clear_tzcache(only_keys=[...])` also matches identifiers case-insensitively.
Clearing a cache can make otherwise identical timezone IDs refer to different
database versions, so use it only when updating timezone data deliberately.
