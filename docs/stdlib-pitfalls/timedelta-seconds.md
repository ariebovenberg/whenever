---
hide-toc: true
---

(timedelta-seconds)=
# `timedelta.seconds` footgun

After subtracting two datetimes, you get a {class}`~datetime.timedelta`.
You may want to know how many seconds it represents.

```python
delta = end - start
delta.seconds
```

This looks reasonable at first—but it's almost never what you want.
This is because the `.seconds` attribute is a **remainder, not a total**.
While the remainder looks like the total number of seconds in many cases...

```python
>>> d = timedelta(seconds=123)
>>> d.seconds
123  # looks good, right?
```

...it breaks down for negative or durations longer than one day:

```python
>>> d = timedelta(seconds=-1)
>>> d.seconds
86399  # huh?
>>> d = timedelta(hours=25)
>>> d.seconds
3600  # also huh? (25 hours is 90000 seconds)
```

This is due to the internal representation of {class}`~datetime.timedelta`,
which stores values in {attr}`~datetime.timedelta.days`, {attr}`~datetime.timedelta.seconds`,
and {attr}`~datetime.timedelta.microseconds` fields.
Only the `days` field can be negative.

If you need the duration in seconds, the correct method is
{meth}`~datetime.timedelta.total_seconds`.
Unfortunately, the attribute name `seconds` makes the wrong choice too tempting,
and the problem often only shows up with negative or large durations.

## How `whenever` solves this

Whenever's {class}`~whenever.TimeDelta` hides its internal representation
and provides a single way to get the duration in various units:

```python
>>> from whenever import TimeDelta
>>> delta = TimeDelta(hours=2)
>>> delta.total("seconds")
7200.0
>>> delta.total("minutes")
120.0
```
