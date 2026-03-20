---
hide-toc: true
---

# Ambiguity passes silently

When time zone offsets change—most commonly due to daylight saving time—a local
clock time may occur **twice** or **not at all**.

Python resolves these ambiguities with the `fold` parameter, which defaults to `0`.
That's not inherently wrong: having a deterministic default {ref}`is often useful <ambiguity-default>`.

The problem is that it’s difficult to handle ambiguity *explicitly*:

* There is no option to raise an error (instead of picking a default)
* The `fold` parameter is subtle and poorly discoverable
* Many users are unaware ambiguity exists at all

```python
# does `fold` matter here? Hard to tell!
datetime(2024, 10, 27, 2, 30, tzinfo=ZoneInfo("Europe/Amsterdam"), fold=1)
```

Without careful handling, code may interpret an ambiguous local time
differently than intended.

## How `whenever` solves this

While `whenever` also defaults to the same convention as Python (as do most libraries),
it provides explicit tools to handle ambiguity:

```python
>>> dt = ZonedDateTime(2024, 10, 27, 2, 30, tz="Europe/Amsterdam", disambiguate="raise")
Traceback (most recent call last):
  ...
RepeatedTime: 2024-10-27 02:30:00 is repeated in timezone 'Europe/Amsterdam'
```
