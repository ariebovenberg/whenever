(api)=
# Main types

```{eval-rst}
.. currentmodule:: whenever
```


The `whenever` library provides four main date-time types, each
with its own purpose and behavior:

```{eval-rst}
.. toctree::
   :maxdepth: 1

   instant
   zoned_datetime
   offset_datetime
   plain_datetime
```

The available methods differ between these types based on whether they
represent {ref}`exact time or local time <exact-vs-local>`:

| type                          | represents exact time? | represents local time? |
|-------------------------------|:----------------------:|:----------------------:|
| {class}`Instant`              |         ✅            |         ❌ 
| {class}`ZonedDateTime`       |          ✅             |    ✅            |
| {class}`OffsetDateTime`      |         ✅             |    ✅            |
| {class}`PlainDateTime`        |         ❌            |        ✅             |



## Exact time methods

The exact time classes ({class}`Instant`, {class}`ZonedDateTime`,
and {class}`OffsetDateTime`) share several methods for working with
exact points in time:


|   | {class}`Instant` | {class}`ZonedDateTime` | {class}`OffsetDateTime`  |
|----|:--------:|:-----:|:------:|
| `now()`  | {meth}`🔗 <Instant.now>`  | {meth}`🔗 <ZonedDateTime.now>` | {meth}`🔗 <OffsetDateTime.now>` |
|    |   |   |   |
|  `timestamp()` [^1] | {meth}`🔗 <Instant.timestamp>`   | {meth}`🔗 <ZonedDateTime.timestamp>` | {meth}`🔗 <OffsetDateTime.timestamp>`  |
| `from_timestamp()` [^2]  | {meth}`🔗 <Instant.from_timestamp>` | {meth}`🔗 <ZonedDateTime.from_timestamp>` | {meth}`🔗 <OffsetDateTime.from_timestamp>`  |
|    |   |   |   |
|  `to_fixed_offset()`  | {meth}`🔗 <Instant.to_fixed_offset>` | {meth}`🔗 <ZonedDateTime.to_fixed_offset>`  | {meth}`🔗 <OffsetDateTime.to_fixed_offset>`   |
|  `to_tz()`  | {meth}`🔗 <Instant.to_tz>`  | {meth}`🔗 <ZonedDateTime.to_tz>` | {meth}`🔗 <OffsetDateTime.to_tz>`                          |
|  `to_system_tz()`  | {meth}`🔗 <Instant.to_system_tz>` | {meth}`🔗 <ZonedDateTime.to_system_tz>` | {meth}`🔗 <OffsetDateTime.to_system_tz>` |
|    |   |   |   |
|  `x > other_exact` [^3]  | {meth}`🔗 <Instant.__gt__>`    | {meth}`🔗 <ZonedDateTime.__gt__>`    | {meth}`🔗 <OffsetDateTime.__gt__>`   |
|  `x - other_exact`  | {meth}`🔗 <Instant.__sub__>`        | {meth}`🔗 <ZonedDateTime.__sub__>`        | {meth}`🔗 <OffsetDateTime.__sub__>`       |
|  `x == other_exact`  | {meth}`🔗 <Instant.__eq__>`        | {meth}`🔗 <ZonedDateTime.__eq__>`        | {meth}`🔗 <OffsetDateTime.__eq__>`       |
|  `exact_eq()`  | {meth}`🔗 <Instant.exact_eq>`       | {meth}`🔗 <ZonedDateTime.exact_eq>`       | {meth}`🔗 <OffsetDateTime.exact_eq>`      |
|    |   |   |   |
|  `x + TimeDelta`  | {meth}`🔗 <Instant.__add__>` | {meth}`🔗 <ZonedDateTime.__add__>`  | {meth}`🔗 <OffsetDateTime.__add__>` |


## Local time methods

The local time classes ({class}`PlainDateTime`, {class}`ZonedDateTime`,
and {class}`OffsetDateTime`) share several methods for working with
local date and time values:


|    | {class}`PlainDateTime`                                           | {class}`ZonedDateTime`                                           | {class}`OffsetDateTime`                                            |
|----|:--------:|:-----:|:------:|
| `year`, `month`, etc.  | {attr}`🔗 <PlainDateTime.year>`  | {attr}`🔗 <ZonedDateTime.year>`  | {attr}`🔗 <OffsetDateTime.year>`  |
| `hour`, `minute`, etc. | {attr}`🔗 <PlainDateTime.hour>` | {attr}`🔗 <ZonedDateTime.hour>` | {attr}`🔗 <OffsetDateTime.hour>` |
| `date()`                                      | {meth}`🔗 <PlainDateTime.date>`                                      | {meth}`🔗 <ZonedDateTime.date>`                                      | {meth}`🔗 <OffsetDateTime.date>`                                       |
| `time()`                                      | {meth}`🔗 <PlainDateTime.time>`                                      | {meth}`🔗 <ZonedDateTime.time>`                                      | {meth}`🔗 <OffsetDateTime.time>`                                       |
|    |   |   |
| `replace()` [^4]                              | {meth}`🔗 <PlainDateTime.replace>`                              | {meth}`🔗 <ZonedDateTime.replace>`                              | {meth}`🔗 <OffsetDateTime.replace>`                               |
| `add()`, `subtract()`      | {meth}`🔗 <PlainDateTime.add>`, {meth}`🔗 <PlainDateTime.subtract>`      | {meth}`🔗 <ZonedDateTime.add>`, {meth}`🔗 <ZonedDateTime.subtract>`      | {meth}`🔗 <OffsetDateTime.add>`, {meth}`🔗 <OffsetDateTime.subtract>`      |
| `since()`, `until()`      | {meth}`🔗 <PlainDateTime.since>`, {meth}`🔗 <PlainDateTime.until>`      | {meth}`🔗 <ZonedDateTime.since>`, {meth}`🔗 <ZonedDateTime.until>`      | {meth}`🔗 <OffsetDateTime.since>`, {meth}`🔗 <OffsetDateTime.until>`      |
| `round()`                                     | {meth}`🔗 <PlainDateTime.round>`                                     | {meth}`🔗 <ZonedDateTime.round>`                                     | {meth}`🔗 <OffsetDateTime.round>`                                      |


TODO spin this off into its own paragraph in FAQ

:::{note}
Although {class}`Instant`'s debug representation is in
UTC, it does not have local time methods.

```python
>>> from whenever import Instant
>>> now = Instant.now()
Instant("2026-01-23T05:30:15.149822Z")
>>> now.year
AttributeError: 'Instant' object has no attribute 'year'
````

This is because an instant represents a specific moment in time,
which is explicitly *not* tied to any calendar system or timezone.
UTC is just a debug-friendly representation of that moment.
If you really need to treat UTC as a meaningful date and time (warning: you probably don't),
you can convert the instant to an {class}`OffsetDateTime` with a zero offset:

```python
>>> now.to_fixed_offset(0).year
2026
```

:::

## Other methods

Several other methods are unique to one or more classes:

| {class}`Instant`                           | {class}`ZonedDateTime`                  | {class}`OffsetDateTime`                | {class}`PlainDateTime`                                 |
|--------------------------------------------|-----------------------------------------|----------------------------------------|-------------------------------------------------------|
| {attr}`~Instant.MIN`, {attr}`~Instant.MAX` |                                         |                                        | {attr}`~PlainDateTime.MIN`, {attr}`~PlainDateTime.MAX` |
| {meth}`~Instant.from_utc`                  |                                         |                                        |                                                        |
| {attr}`~Instant.format_rfc2822`            |                                         | {meth}`~OffsetDateTime.format_rfc2822` |                                                        |
|                                            | {meth}`~ZonedDateTime.to_instant`       | {meth}`~OffsetDateTime.to_instant`     |                                                        |
|                                            | {meth}`~ZonedDateTime.to_plain`         | {meth}`~OffsetDateTime.to_plain`       |                                                        |
|                                            | {attr}`~ZonedDateTime.offset`           | {attr}`~OffsetDateTime.offset`         |                                                        |
|                                            |                                         |                                        | {meth}`x == other_plain <PlainDateTime.__eq__>`        |
|                                            |                                         |                                        | {meth}`x > other_plain <PlainDateTime.__gt__>`         |
|                                            |                                         |                                        | {meth}`x - other_plain <PlainDateTime.__sub__>`         |
|                                            |                                         |                                        | {meth}`~PlainDateTime.assume_utc`                      |
|                                            |                                         | {meth}`~OffsetDateTime.assume_tz`      | {meth}`~PlainDateTime.assume_tz`                       |
|                                            |                                         |                                        | {meth}`~PlainDateTime.assume_system_tz`                |
|                                            |                                         |                                        | {meth}`~PlainDateTime.assume_fixed_offset`             |
|                                            |                                         | {meth}`~OffsetDateTime.parse_strptime` | {meth}`~PlainDateTime.parse_strptime`                  |
|                                            | {attr}`~ZonedDateTime.tz`               |                                        |                                                        |
|                                            | {meth}`~ZonedDateTime.now_in_system_tz` |                                        |                                                        |
|                                            | {meth}`~ZonedDateTime.is_ambiguous`     |                                        |                                                        |
|                                            | {meth}`~ZonedDateTime.day_length`       |                                        |                                                        |
|                                            | {meth}`~ZonedDateTime.start_of_day`     |                                        |                                                        |


[^1]: `timestamp_millis()` and `timestamp_nanos()` methods are also
    available for millisecond and nanosecond precision.

[^2]: `from_timestamp_millis()` and `from_timestamp_nanos()` methods are
    also available for millisecond and nanosecond precision.

[^3]: The other comparison operators `<=`, `<`, and `>=` are also
    supported.

[^4]: `replace_date()` and `replace_time()` are also available for
    replacing only the date or time component.
