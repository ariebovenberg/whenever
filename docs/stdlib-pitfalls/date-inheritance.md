---
hide-toc: true
---

# `datetime` inherits from `date`

You may be surprised to know that `datetime` is a subclass of `date`.
This doesn't seem problematic at first, but it leads to odd behavior.
Most notably, the fact that `date` and `datetime` cannot be compared violates
[basic assumptions](https://en.wikipedia.org/wiki/Liskov_substitution_principle) of how subclasses should work.
The `datetime/date` inheritance is now [widely considered](https://discuss.python.org/t/renaming-datetime-datetime-to-datetime-datetime/26279/2)
to be a [design flaw](https://github.com/python/typeshed/issues/4802) in the standard library.

```python
# Breaks on a datetime, even though it's a subclass
def is_future(d: date) -> bool:
    return d > date.today()

# Some methods inherited from `date` don't make sense
datetime.today()  # fun exercise: what does this return?
```

## How `whenever` solves this

Whenever separates the concepts of date and datetime completely.
There is no inheritance relationship between `Date` and `PlainDateTime`/`ZonedDateTime`.
This means you can catch mistakes at compile time, and all comparisons behave intuitively:

```python
>>> from whenever import Date, PlainDateTime
>>> d = Date(2024, 7, 4)
>>> dt = PlainDateTime(2024, 7, 4, 12, 0, 0)
>>> d > dt  # type checker will catch this
```
