---
myst:
  html_meta:
    description: >-
      A detailed comparison with Pendulum: what it improves over the standard
      library, and where it still inherits datetime's model — UTC assumptions,
      calendar arithmetic, DST edge cases, permissive parsing, maintenance, and
      performance.
---

# Why not Pendulum?

[**Pendulum**](https://pypi.org/project/pendulum/)
is a popular third-party datetime library that
arrived on the scene in 2016, promising better DST handling.
It offers a convenient API, useful formatting and localization features,
and more intuitive arithmetic than the standard library in several common cases.

However, Pendulum is best understood as an extension of `datetime`,
not a redesign of it. Because it subclasses `datetime` and `timedelta`,
it inherits their shortcomings along with their compatibility.
It then adds calendar units and implicit policies that these base classes
cannot always preserve consistently.
As a result, equality, hashing, arithmetic, parsing, and serialization can
disagree about what a value means.

```{note}
This section is up to date as of Pendulum version 3.2.0.
```

## It improves ergonomics, but retains `datetime`'s model

Pendulum does address some of the standard library's
{ref}`pitfalls <datetime-pitfalls>`.
In particular, its named arithmetic methods distinguish calendar units from
elapsed units across DST transitions, and `Duration.seconds` avoids the
{ref}`timedelta.seconds footgun <timedelta-seconds>`.

Most of the underlying model remains unchanged, though:

- naive and aware datetimes use the same class;
- `DateTime` inherits from `date`;
- equality and ordering retain `datetime`'s DST edge cases.

Pendulum's description of its classes as
["drop-in replacements"](https://pendulum.eustace.io/docs/#introduction)
therefore needs qualification. The same documentation acknowledges a
[non-exhaustive list of incompatibilities](https://pendulum.eustace.io/docs/#limitations)
with libraries that distinguish types exactly, including database drivers.

Pendulum's policy of preferring aware datetimes is not consistently enforced
throughout the API:

```python
>>> import pendulum
>>> pendulum.datetime(2020, 1, 1)
DateTime(2020, 1, 1, 0, 0, 0, tzinfo=Timezone('UTC'))
>>> pendulum.DateTime(2020, 1, 1)
DateTime(2020, 1, 1, 0, 0, 0)
```

Some inherited states are not handled consistently either.
For example, a naive `DateTime` reports that it is in daylight saving time,
even though `dst()` correctly reports that DST is undefined:

```python
>>> naive = pendulum.DateTime(2024, 1, 1)
>>> naive.dst() is None
True
>>> naive.is_dst()
True
```

## Missing timezone information becomes UTC

When parsing a datetime without an offset, Pendulum assumes UTC:

```python
>>> import pendulum
>>> pendulum.parse("2024-03-10T15:00")
DateTime(2024, 3, 10, 15, 0, 0, tzinfo=Timezone('UTC'))
```

An ISO 8601 datetime without an offset does not identify an instant.
It only supplies local date and time fields.
Treating it as UTC invents information that was absent from the input.
If the source intended another time zone, this can silently shift the
resulting instant by several hours.

The same policy is used when converting a naive standard-library datetime:

```python
>>> from datetime import datetime
>>> pendulum.instance(datetime(2024, 3, 10, 15))
DateTime(2024, 3, 10, 15, 0, 0, tzinfo=Timezone('UTC'))
```

## Calendar arithmetic violates basic invariants

Pendulum's `Duration` adds years and months to `timedelta`.
That is a difficult fit: `timedelta` represents an exact elapsed duration,
while a calendar month has no fixed length.

Pendulum approximates a month as 30 days for compatibility with `timedelta`.
At the same time, applying a month to a datetime uses calendar arithmetic.
Consequently, values that compare equal are not interchangeable:

```python
>>> import pendulum
>>> month = pendulum.duration(months=1)
>>> thirty_days = pendulum.duration(days=30)
>>> month == thirty_days
True
>>> hash(month) == hash(thirty_days)
True

>>> jan_31 = pendulum.datetime(2024, 1, 31)
>>> jan_31 + month
DateTime(2024, 2, 29, 0, 0, 0, tzinfo=Timezone('UTC'))
>>> jan_31 + thirty_days
DateTime(2024, 3, 1, 0, 0, 0, tzinfo=Timezone('UTC'))
```

Even identity operations can erase calendar information:

```python
>>> month + pendulum.duration()
Duration(weeks=4, days=2)
>>> month * 1
Duration(months=1)
>>> month * 1.0
Duration()
```

So can ordinary serialization and shallow copying:

```python
>>> import copy
>>> import pickle
>>> copy.copy(month)
Duration(weeks=4, days=2)
>>> pickle.loads(pickle.dumps(month))
Duration(weeks=4, days=2)
```

Compatibility with the `timedelta` base class is also asymmetric:

```python
>>> from datetime import timedelta
>>> day = pendulum.duration(days=1)
>>> timedelta(hours=1) / day
0.041666666666666664
>>> day / timedelta(hours=1)
Traceback (most recent call last):
  ...
AttributeError: 'datetime.timedelta' object has no attribute '_to_microseconds'
```

The same private-method assumption affects floor division, modulo, and
`divmod()`. This has been reported for `Interval` since 2019
([#382](https://github.com/python-pendulum/pendulum/issues/382)).

### `Interval` violates equality and hashing contracts

`Interval`, the result of subtracting two Pendulum datetimes,
is itself a subclass of `Duration`.
Its equality semantics do not form a valid equivalence relation:

```python
>>> jan = pendulum.interval(
...     pendulum.datetime(2024, 1, 1),
...     pendulum.datetime(2024, 1, 2),
... )
>>> one_day = pendulum.duration(days=1)
>>> feb = pendulum.interval(
...     pendulum.datetime(2024, 2, 1),
...     pendulum.datetime(2024, 2, 2),
... )
>>> jan == one_day
True
>>> one_day == feb
True
>>> jan == feb
False
```

Equality is therefore not transitive.
Equal objects can also have different hashes:

```python
>>> jan == one_day
True
>>> hash(jan) == hash(one_day)
False
>>> len({jan, one_day})
2
```

This violates Python's contract for hashable objects and can produce incorrect
behavior in dictionaries, sets, caches, and deduplication code.

## `Time` arithmetic can discard information

Pendulum exposes aware `Time` values, but its arithmetic converts through an
epoch datetime and returns only the clock fields. The timezone is silently
lost:

```python
>>> paris = pendulum.timezone("Europe/Paris")
>>> noon = pendulum.Time(12, tzinfo=paris)
>>> noon.add(hours=1)
Time(13, 0, 0)
>>> noon.add(hours=1).tzinfo is None
True
```

Subtracting two times has a separate precision problem:

```python
>>> late = pendulum.Time(12, 0, 0, 900_000)
>>> early = pendulum.Time(12, 0, 0, 100_000)
>>> late - early
Duration()
```

The expected difference is 800,000 microseconds. The implementation calculates
whole seconds and omits both operands' microseconds, an issue reported in
[#362](https://github.com/python-pendulum/pendulum/issues/362) and
[#584](https://github.com/python-pendulum/pendulum/issues/584).

## DST handling remains inconsistent

Pendulum's named `add()` and `subtract()` methods are a useful
improvement over `datetime`.
They distinguish calendar days from elapsed hours and handle many DST
transitions conveniently.
Equivalent-looking operations do not always take the same path:

```python
>>> import pendulum
>>> dt = pendulum.datetime(2013, 4, 2, tz="Europe/Paris")
>>> three_days = pendulum.duration(days=3)
>>> dt.subtract(days=3)
DateTime(2013, 3, 30, 0, 0, 0, tzinfo=Timezone('Europe/Paris'))
>>> dt - three_days
DateTime(2013, 3, 29, 23, 0, 0, tzinfo=Timezone('Europe/Paris'))
>>> dt + -three_days
DateTime(2013, 3, 30, 0, 0, 0, tzinfo=Timezone('Europe/Paris'))
```

Here, `dt - delta` differs from both `dt.subtract(...)` and `dt + -delta`.
A fix is proposed in
[pull request #987](https://github.com/python-pendulum/pendulum/pull/987).

### Comparisons can contradict chronological order

During a repeated hour, ordering compares local fields instead of instants:

```python
>>> later = pendulum.datetime(
...     2023, 11, 5, 1, 15,
...     tz="America/Los_Angeles",
...     fold=1,
... )
>>> earlier = pendulum.datetime(
...     2023, 11, 5, 1, 25,
...     tz="America/Los_Angeles",
...     fold=0,
... )
>>> later.timestamp() > earlier.timestamp()
True
>>> later < earlier
True
```

This contradicts Pendulum's documentation, which says comparisons account for
time zones.
The problem was first reported in
[#351](https://github.com/python-pendulum/pendulum/issues/351);
another fix is currently proposed in
[#985](https://github.com/python-pendulum/pendulum/pull/985).

Intervals spanning the repeated hour are internally inconsistent as well.
For an interval of exactly one elapsed hour, Pendulum 3.2.0 can report:

```python
>>> first = pendulum.datetime(
...     2023, 11, 5, 1, 25,
...     tz="America/Los_Angeles",
...     fold=0,
... )
>>> second = pendulum.datetime(
...     2023, 11, 5, 1, 25,
...     tz="America/Los_Angeles",
...     fold=1,
... )
>>> interval = second - first
>>> interval.total_seconds()
3600.0
>>> interval.in_seconds()
3600
>>> interval.hours
0
>>> interval.in_words()
'0 microseconds'
```

### Serialization can change the instant

Pickling does not preserve `fold`.
Serializing a datetime in the second occurrence of a repeated hour
and reading it back can therefore change its timestamp:

```python
>>> import pickle
>>> original = pendulum.datetime(
...     2024, 11, 3, 1,
...     tz="America/Chicago",
...     fold=1,
... )
>>> restored = pickle.loads(pickle.dumps(original))
>>> original.fold, restored.fold
(1, 0)
>>> original.timestamp() == restored.timestamp()
False
```

Shallow copying follows the same reconstruction path and has the same effect;
`deepcopy()` does preserve the fold.
This is tracked in [#908](https://github.com/python-pendulum/pendulum/issues/908).
An open fix is available in
[pull request #909](https://github.com/python-pendulum/pendulum/pull/909).

### Its default disambiguation differs from the common convention

Pendulum defaults to `fold=1`, selecting the offset *after* a backwards
transition.
Python's standard library and the convention used by most datetime libraries
default to the offset before the transition; see
{ref}`the discussion of ambiguity defaults <ambiguity-default>`.

Pendulum allows callers to choose a `fold`, and
`raise_on_unknown_times=True` can reject ambiguous or nonexistent local times.
The default is significant: moving code from `datetime` to Pendulum can change
which instant an ambiguous local time represents unless the fold is chosen
explicitly.

## Parsing is permissive and implementation-dependent

`parse()` handles several unrelated kinds of input.
Depending on the string, it may return a `DateTime`, `Duration`, or `Interval`.
Time-only input is particularly surprising:

```python
>>> type(pendulum.parse("12:34:56")).__name__
'DateTime'
>>> type(pendulum.parse("12:34:56", exact=True)).__name__
'Time'
```

Without `exact=True`, Pendulum supplies the current date.
The same parser also gives the string `"now"` special, undocumented,
time-dependent behavior:

```python
>>> pendulum.parse("now").timezone_name
'UTC'
```

This makes the result depend on the wall clock rather than only on the input.
It can therefore be risky when parsing user-controlled or externally supplied
strings.

Parsing behavior also depends on whether Pendulum's Rust extension is loaded.
On the normal compiled build:

```python
>>> pendulum.parse("PT4294967297M")
Duration(minutes=1)
>>> pendulum.parse("P12M4M")
Duration(months=4)
```

The first value has overflowed, while the second is not a valid ISO 8601
duration.
With `PENDULUM_EXTENSIONS=0`, the pure-Python parser preserves all
4,294,967,297 minutes and rejects the duplicated month component.

The implementations can also assign different values to valid input:

```python
# Compiled parser
>>> pendulum.parse("P1.25D")
Duration(days=1, hours=6)

# Pure-Python parser
>>> pendulum.parse("P1.25D")
Duration(days=3, hours=12)
```

The pure parser divides the fractional digits by ten regardless of their
length, so `1.25` days is interpreted as `3.5` days. This parser bug has
remained open since 2021
([#534](https://github.com/python-pendulum/pendulum/issues/534)).
The project currently lacks systematic parity tests between the two
implementations, as acknowledged in
[#907](https://github.com/python-pendulum/pendulum/issues/907).

## The documentation is outdated and incomplete

Pendulum's documentation is primarily a guide, rather than a complete API
reference. A request for a usable reference has remained open since 2018
([#199](https://github.com/python-pendulum/pendulum/issues/199)).

Several published examples no longer match version 3.2.0:

- the timezone guide still recommends `dst_rule`, `PRE_TRANSITION`,
  `POST_TRANSITION`, and `TRANSITION_ERROR`, all removed in 3.0
  ([#789](https://github.com/python-pendulum/pendulum/issues/789));
- parts of the documentation still call the result of `diff()` a `Period`,
  although the public class is now `Interval`;
- examples for `Duration.total_days()` disagree with the actual result;
- the introduction says that comparisons account for time zones, which the
  repeated-hour example above contradicts.

## Maintenance remains a concern

Pendulum is active again after a long period of limited maintenance, and recent
releases and contributions are welcome signs.
However, reproducible correctness issues remain unresolved across releases,
including cases where a tested fix is already available.
Examples include the pending fixes for pickling, naive datetime differences,
floating-point `Duration` multiplication, fold ordering, and DST subtraction
([#909](https://github.com/python-pendulum/pendulum/pull/909),
[#968](https://github.com/python-pendulum/pendulum/pull/968),
[#975](https://github.com/python-pendulum/pendulum/pull/975),
[#985](https://github.com/python-pendulum/pendulum/pull/985),
and [#987](https://github.com/python-pendulum/pendulum/pull/987)).

## Performance has regressed

While Pendulum initially promised
[improved performance](https://pendulum.eustace.io/faq/),
users have reported a version 3
[`in_tz()` performance regression](https://github.com/python-pendulum/pendulum/issues/818).
In {ref}`benchmarks <benchmarks>`, Pendulum is often an order of magnitude
slower than both the standard library and `whenever`.

Correctness and predictable semantics matter more than speed for datetime
code. The additional overhead may nevertheless matter to applications
performing large volumes of datetime operations.
