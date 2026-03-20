---
hide-toc: true
---

# Inconsistent role of "naive"

In various parts of the standard library, "naive" datetimes are interpreted differently.
Ostensibly, "naive" means "detached from the real world",
but in the datetime library it is often implicitly treated as the system timezone.
Confusingly, it is sometimes treated as UTC, while in other places it is treated as neither!

```python

# a naive datetime
d = datetime(2024, 1, 1)

# here: treated as in the system timezone
d.timestamp()
d.astimezone(UTC)

# here: assumed to be UTC
d.utctimetuple()
email.utils.format_datetime(d)
datetime.utcnow()

# here: neither! (error)
d >= datetime.now(UTC)
```

This inconsistency leads to subtle bugs when naive datetimes are used in different contexts.
Since neither the type system nor runtime checks can know the intended meaning of a naive datetime,
it's easy to accidentally mix interpretations.

Thankfully, methods like {meth}`~datetime.datetime.utcnow()` are being deprecated, slowly making "system timezone"
the only implicit meaning of naive datetimes in the standard library.
But this behavior {ref}`also has drawbacks <stdlib-system-tz>`.

## How `whenever` solves this

Whenever's `PlainDateTime` type is always explicitly detached from any timezone.
It never assumes any implicit meaning, and cannot be mixed with timezone-aware types
without explicit conversion:

```python
>>> d = PlainDateTime("2024-07-04 12:36:56")
>>> d.assume_utc()
Instant("2024-07-04 12:36:56Z")
>>> d.assume_system_tz()
ZonedDateTime("2024-07-04 12:36:56+02:00[Europe/Berlin]")
```
