# Why not pendulum?

[**Pendulum**](https://pypi.org/project/pendulum/)
is a popular third-party datetime library that
arrived on the scene in 2016, promising better DST-handling.
While it improves on some aspects of the standard library,
it falls short in others. Here's an overview:

```{note}
This section is up-to-date as of Pendulum version 3.2.0
```

## It doesn't address *most* `datetime` pitfalls

Of the {ref}`pitfalls <datetime-pitfalls>` in the standard library's `datetime` module,
Pendulum only really addresses two: the {ref}`DST arithmetic issue <datetime-ignores-dst>`
and the `timedelta.seconds` {ref}`footgun <timedelta-seconds>`.
The remaining issues—ambiguous types, equality edge cases,
inheritance issues—are left unresolved.

## It's behind on maintenance

After a long period of inactivity, Pendulum is now slowly receiving updates again.
However, many serious and long-standing issues remain unaddressed.
See the [issue tracker](https://github.com/python-pendulum/pendulum/issues) for details.

## It assumes UTC by default

Pendulum emphasizes working with aware datetimes, but makes dubious choices
to facilitate this. For example, it assumes UTC when no time zone is specified:

```python
>>> import pendulum
>>> pendulum.parse("2024-03-10T15:00")
DateTime(2024, 3, 10, 15, 0, 0, tzinfo=Timezone('UTC'))
```

This seems handy at first, until you realize that it's a silent assumption
that may not align with your intentions.
In fact, ISO8601 datetimes without time zone information are explicitly *not* UTC,
but rather *local time*.
This means that Pendulum's default behavior is likely to introduce subtle bugs
when parsing user input or data from other systems.

Here's another confusing example:

```python
>>> pendulum.datetime(2020, 1, 1)
DateTime(2020, 1, 1, 0, 0, 0, tzinfo=Timezone('UTC'))
>>> pendulum.DateTime(2020, 1, 1)
DateTime(2020, 1, 1, 0, 0, 0)
```

## Outdated and missing documentation

Pendulum's documentation is outdated in several places,
with examples that no longer work as intended.
For example, the `dst_rule` parameter is mentioned in the documentation for
disambiguating ambiguous times, but has been silently removed in version 3.0.

These issues are compounded by the lack of API reference documentation,
making it difficult to understand the full capabilities of the library,
and what can be relied upon.

## The `Duration` class is broken

Pendulum's `Duration` class extends `timedelta` to support
months and years. However, dubious design choices lead to surprising behavior.
For example, it assumes months are always 30 days:

```python
>>> Duration(months=1) + Duration()
Duration(weeks=4, days=2)
```

Arithmetic with `Duration` also has issues:

```python
>>> Duration(months=1) * 1.0
Duration()
>>> Duration(months=1) * 1
Duration(months=1)
```

Parsing durations also has issues:

```python
>>> parse("PT4294967297M")
Duration(minutes=1)  # integer overflow not handled correctly
>>> parse("P12M4M")
Duration(months=4)  # should be an error, but takes the last one
```

## `parse('now')`

For undocumented reasons, Pendulum's `parse` function treats the
string `'now'` specially, returning the current date and time:

```python
>>> pendulum.parse("now")
DateTime(2025, 12, 2, 20, 16, 31, tzinfo=Timezone('Europe/Amsterdam'))
```

This is unexpected behavior for a parsing function,
and can lead to confusing bugs if the input string is user-provided
(or comes from an external source).

## It's quite slow

While Pendulum initially promised [improved performance](https://pendulum.eustace.io/faq/),
its performance has significantly [degraded over time](https://github.com/sdispater/pendulum/issues/818).
In benchmarks, Pendulum is often an order of magnitude slower than both the standard library
and `whenever`.

## It disambiguates differently by default

Pendulum's default behavior for disambiguating ambiguous local times
runs counter to {ref}`industry conventions <ambiguity-default>`.
Specifically, it uses the offset *after* the transition
for repeated times, instead of the offset before.
This makes its behavior different from most other libraries.
There is no reason given for this choice.

## It's a drop-in replacement—until it isn't

By inheriting from {class}`~datetime.datetime`, Pendulum *mostly* works as a drop-in replacement
for `datetime`.
However, there are still [cases where this breaks down](https://github.com/python-pendulum/pendulum?tab=readme-ov-file#limitations),
making it risky to 'drop in' to an existing codebase—subtle bugs may be introduced.
