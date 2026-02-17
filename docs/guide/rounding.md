(rounding)=
# Rounding

```{note}
The API for rounding is largely inspired by that of Temporal (JavaScript)
```

It's often useful to truncate or round a datetime to a specific unit.
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
## Rounding modes

Different rounding modes are available. They differ on two axes:

- Do they round towards/away from zero ("trunc"/"expand") or up/down ("ceil"/"floor")?
- How do they handle ties?

This results in the following modes:

| Mode       | Rounding direction | Tie-breaking behavior | Examples |
|------------|--------------------|-----------------------|----------|
| `ceil`     | up                 | N/A                   | 3.1→4, -3.1→-3 |
| `floor`    | down               | N/A                   | 3.1→3, -3.1→-4 |
| `trunc`    | towards zero       | N/A                   | 3.1→3, -3.1→-3 |
| `expand`   | away from zero     | N/A                   | 3.1→4, -3.1→-4 |
| `half-ceil`  | nearest increment  | up    | 3.5→4, -3.5→-3 |
| `half-floor` | nearest increment  | down  | 3.5→3, -3.5→-4 |
| `half-trunc` | nearest increment  | towards zero  |  3.5→3, -3.5→-3 |
| `half-expand` | nearest increment  | away from zero |  3.5→4, -3.5→-4 |
| `half-even` | nearest increment  | to even | 3.5→4, 4.5→4, -3.5→-4, -4.5→-4 |

For positive values, the behavior of `ceil`/`floor` and `trunc`/`expand` is the same.
The difference is only visible for negative values.
