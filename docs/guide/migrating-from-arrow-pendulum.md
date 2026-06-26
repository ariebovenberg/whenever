(migrating-from-arrow-pendulum)=
# Migrating from Arrow or Pendulum

```{eval-rst}
.. currentmodule:: whenever
```

This guide helps you migrate existing code from
[Arrow](https://arrow.readthedocs.io/) or [Pendulum](https://pendulum.eustace.io/)
to `whenever`.

```{tip}
The key difference: Arrow and Pendulum use a single type for everything.
`whenever` uses distinct types ({class}`Instant`, {class}`ZonedDateTime`,
{class}`PlainDateTime`) so that the type checker can catch mixing errors at
development time rather than at runtime.
```

## Choosing the right type

| If you were using Arrow/Pendulum for... | Use `whenever`'s... |
|:---|:---|
| A moment in time (UTC/timestamp) | {class}`Instant` |
| A time in a specific timezone | {class}`ZonedDateTime` |
| A local/naive datetime (no timezone) | {class}`PlainDateTime` |
| A fixed UTC offset (e.g. `+05:30`) | {class}`OffsetDateTime` |

## Common operations

### Getting the current time

```python
# Arrow
arrow.now()           # local time
arrow.utcnow()        # UTC

# Pendulum
pendulum.now()        # local time
pendulum.now("UTC")   # UTC

# whenever
ZonedDateTime.now_in_system_tz()   # local time
Instant.now()                      # UTC / exact moment
```

### Creating a datetime

```python
# Arrow
arrow.Arrow(2024, 1, 15, 10, 30, tzinfo="UTC")

# Pendulum
pendulum.datetime(2024, 1, 15, 10, 30, tz="UTC")

# whenever
ZonedDateTime(2024, 1, 15, hour=10, minute=30, tz="UTC")
Instant.from_utc(2024, 1, 15, hour=10, minute=30)
```

### Parsing

```python
# Arrow
arrow.get("2024-01-15T10:30:00+00:00")

# Pendulum
pendulum.parse("2024-01-15T10:30:00+00:00")

# whenever
ZonedDateTime.parse_common_iso("2024-01-15T10:30:00+00:00[UTC]")
Instant.parse_common_iso("2024-01-15T10:30:00Z")
OffsetDateTime.parse_common_iso("2024-01-15T10:30:00+05:30")
```

### Formatting

```python
# Arrow
dt.isoformat()
dt.format("YYYY-MM-DD HH:mm:ss")

# Pendulum
dt.isoformat()
dt.format("YYYY-MM-DD HH:mm:ss")

# whenever
dt.format_common_iso()
dt.format("YYYY-MM-DD HH:mm:ss")
```

### Adding and subtracting

```python
# Arrow
dt.shift(days=1, hours=3)

# Pendulum
dt.add(days=1, hours=3)

# whenever
dt.add(days=1, hours=3)                          # same!
dt.add(days=1, hours=3, disambiguate="raise")    # explicit DST handling
```

The key difference: `whenever` requires you to specify how to handle
DST transitions via `disambiguate`. Arrow and Pendulum silently use a
default that can produce surprising results across DST boundaries.

### Timezone conversion

```python
# Arrow
dt.to("America/New_York")

# Pendulum
dt.in_timezone("America/New_York")

# whenever
dt.to_tz("America/New_York")
```

### Getting a timestamp

```python
# Arrow
dt.timestamp()
dt.int_timestamp

# Pendulum
dt.timestamp()

# whenever
instant.timestamp()           # float (seconds)
instant.timestamp_millis()    # int (milliseconds)
instant.timestamp_nanos()     # int (nanoseconds)
```

## Key behavioral differences

### DST safety

Arrow and Pendulum silently apply a default disambiguation strategy when
arithmetic crosses a DST boundary. `whenever` is explicit:

```python
# whenever raises an error when a time is ambiguous (e.g. clocks go back)
# rather than silently picking one
dt.add(hours=1, disambiguate="raise")    # explicit
dt.add(hours=1, disambiguate="earlier")  # take the earlier option
dt.add(hours=1, disambiguate="later")    # take the later option
dt.add(hours=1, disambiguate="compatible")  # same as fold=0 in stdlib
```

### Naive vs. aware separation

Arrow and Pendulum allow mixing naive and aware datetimes, which can lead
to subtle bugs. `whenever` uses separate types:

```python
plain = PlainDateTime(2024, 1, 15, 10, 30)   # no timezone
zoned = ZonedDateTime(2024, 1, 15, tz="UTC") # has timezone

# The following won't even type-check in whenever:
# plain - zoned  ← type error
```

### No "replace timezone without converting" footgun

```python
# Arrow — silently replaces tzinfo without converting the time
dt.replace(tzinfo="US/Pacific")  # ← dangerous, changes the "meaning"

# whenever — use assume_tz() explicitly when you know what you're doing
plain_dt.assume_tz("US/Pacific", disambiguate="raise")
```

## Type mapping summary

| Arrow/Pendulum | whenever | Notes |
|:---|:---|:---|
| `arrow.Arrow` (UTC) | {class}`Instant` | Use for timestamps |
| `arrow.Arrow` (with tz) | {class}`ZonedDateTime` | IANA timezone |
| `pendulum.DateTime` (with tz) | {class}`ZonedDateTime` | IANA timezone |
| `pendulum.DateTime` (naive) | {class}`PlainDateTime` | No timezone |
| `arrow.Arrow` (fixed offset) | {class}`OffsetDateTime` | Fixed offset like +05:30 |
| `pendulum.Date` | {class}`Date` | Date only |
| `pendulum.Time` | {class}`Time` | Time only |
| `pendulum.Duration` | {class}`DateTimeDelta` / {class}`TimeDelta` | See {ref}`deltas <durations>` |
