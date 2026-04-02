(rounding)=
# Rounding

```{note}
The API for rounding is largely inspired by that of Temporal (JavaScript)
```

It's often useful to truncate or round a datetime or {class}`~whenever.TimeDelta` to a specific unit.
For example, you might want to round a datetime to the nearest hour,
or truncate it into 15-minute intervals.

The {class}`~whenever.ZonedDateTime.round` method allows you to do this:

```python
>>> d = PlainDateTime(2023, 12, 28, 11, 32, 8)
PlainDateTime("2023-12-28 11:32:08")
>>> d.round("hour")
PlainDateTime("2023-12-28 12:00:00")
>>> d.round("minute", increment=15, mode="ceil")
PlainDateTime("2023-12-28 11:45:00")
```

(rounding-modes)=
## Modes

Different rounding modes are available. They differ on two axes:

- Whether they round towards/away from zero (`trunc`/`expand`) or up/down (`ceil`/`floor`)
- How they break ties

This results in the following modes:

| Mode       | Rounding direction | Tie-breaking  | Examples | stdlib equivalent |
|------------|--------------------|-----------------------|----------|----------|
| `ceil`     | up                 | n/a                   | 3.1→4, -3.1→-3 |  {func}`~math.ceil`  |
| `floor`    | down               | n/a                   | 3.1→3, -3.1→-4 | {func}`~math.floor` |
| `trunc`    | towards zero       | n/a                   | 3.1→3, -3.1→-3 | {func}`~math.trunc`, {class}`int` |
| `expand`   | away from zero     | n/a                   | 3.1→4, -3.1→-4 | n/a |
| `half_ceil`  | nearest increment  | up    | 3.5→4, -3.5→-3 |n/a  |
| `half_floor` | nearest increment  | down  | 3.5→3, -3.5→-4 |n/a  |
| `half_trunc` | nearest increment  | towards zero  |  3.5→3, -3.5→-3 |n/a  |
| `half_expand` | nearest increment  | away from zero |  3.5→4, -3.5→-4 |n/a  |
| `half_even` | nearest increment  | to even | 3.5→4, 4.5→4, | {func}`round` |

For positive values, the behavior of `ceil`/`floor` and `trunc`/`expand` is the same.
The difference is only visible for negative values.

## Supported units

The `unit` argument allows you to specify the unit to round to.
Allowed values depend on the type of the object being rounded:

| Type | weeks | days | hours<br> and smaller |
|------|:-----:|:----:|:-------:|
| {class}`~whenever.TimeDelta` | ✅ [^1] | ✅ [^1] | ✅ |
| {class}`~whenever.ZonedDateTime`, | ❌ | ✅ | ✅ |
| {class}`~whenever.PlainDateTime`, | ❌ | ✅ | ✅ |
| {class}`~whenever.OffsetDateTime`, | ❌ | ✅ | ✅ |
| {class}`~whenever.Instant` | ❌ | ❌ [^2] | ✅ |

## Increment

The `increment` argument allows you to specify the rounding increment.
For example, you can round to the nearest 15 minutes by setting `increment=15`
and `unit="minute"`.

There are some restrictions on the allowed increments:

- The increment must be a positive, non-zero integer.
- In case of rounding datetimes, the increment must be a divide a 24-hour day evenly.
  For example, you can round to the nearest 90 minutes (16 increments per day),
  but not to the nearest 7 seconds.

[^1]: This assumes days are always 24 hours long, which is not always the case in practice due to daylight saving time changes.
      Thus, a {class}`~whenever.DaysAssumed24HoursWarning` is issued
      when rounding a TimeDelta to days or weeks.
      Suppress it by passing ``days_assumed_24h_ok=True``
      if you know this is acceptable for your use case:

      ```python
      >>> d = TimeDelta(hours=50)
      >>> d.round("day", days_assumed_24h_ok=True)
      TimeDelta("PT48h")
      ```
[^2]: This is explicitly disallowed because an Instant has no concept of days.
      Treating a UTC "day" as a locally meaningful concept is a common source of bugs,
      so it's better to disallow it entirely.
      You can still round to the nearest 24 hours by setting `unit="hour"` and `increment=24`.

