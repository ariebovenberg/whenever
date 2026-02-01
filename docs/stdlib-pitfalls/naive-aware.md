---
hide-toc: true
---

# One type for everything

Python uses a single `datetime` type to represent two fundamentally different concepts:

* **Naive datetimes**, which have no time zone information
* **Aware datetimes**, which are associated with a time zone

These two behave differently, are interpreted differently,
and should never be mixed.
Yet the type system makes no distinction between them.

This becomes especially frustrating in typed code.
There is no way to express, using type annotations,
whether a function expects a naive or an aware `datetime`.

```python
def schedule_at(dt: datetime) -> None:
    ...
```

Does `dt` represent a local wall-clock time? A UTC timestamp? A zoned time?
The type gives you no way to say.

This makes it impossible to statically enforce one of the most important
invariants in date-time code.
As a result, mistakes that should be caught early often surface only
at runtime—or worse, much later.

## How `whenever` solves this

`whenever` strictly separates datetimes with and without time zone information:

* {class}`~whenever.PlainDateTime` is the equivalent of a "naive" time
* {class}`~whenever.ZonedDateTime` is the equivalent of an "aware" time with
  `ZoneInfo` attached
* {class}`~whenever.Instant` is the equivalent of an "aware" time with `UTC` attached

This makes type annotations precise and self-documenting:

```python
def schedule_at(dt: ZonedDateTime) -> None:
    ...
```
