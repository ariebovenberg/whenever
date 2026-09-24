---
myst:
  html_meta:
    description: >-
      A detailed comparison with Arrow: a friendly wrapper that keeps the
      standard library's arithmetic model, resolves ambiguity by guessing, and
      predates the typing era — with concrete examples of DST arithmetic, a
      fold that every operation drops, do-what-I-mean parsing, humanize edge
      cases, and a regression in how 'local' time is resolved.
---

# Why not Arrow?

[**Arrow**](https://pypi.org/project/arrow/) (2013) is one of the most
popular third-party datetime libraries for Python. It was closely modeled on JavaScript's
`moment.js`: one friendly `Arrow` type, a permissive `arrow.get()` that accepts
almost anything, moment-style format tokens, and localized, human-readable
differences (`humanize()`).

Unlike Pendulum, Arrow *wraps* `datetime` instead of subclassing it,
so it avoids the {ref}`drop-in trap <pendulum-decision-dropin>`.
However, the wrapper is mostly about *convenience*:
it still inherits all the pitfalls from the standard library.
The convenience itself has also aged poorly.
Arrow's *'do what I mean'* approach makes the same call mean different things
depending on the types of its arguments, the current time, or the system time zone,
making it hard to say what the code does before running it.

```{note}
This section is up to date as of Arrow version 1.4.0.
Every example below was run against that version with CPython 3.14.
```

```{admonition} Arrow 1.4.0 at a glance
:class: caution

A sample of behaviour you can reproduce today, each explained further down:

- `a.shift(hours=2)` across a DST transition advances the clock 2 hours but
  the *instant* by 1 or 3.
- `x.shift(seconds=0)` can change the instant by an hour, while still
  comparing equal to `x`.
- `arrow.get((2013, 5, 5))` is **February 1**, 2013; `arrow.get(2013, 5, 5)`
  is May 5.
- `arrow.get(40_000_000_000)` is the year **1971** on a machine east of UTC
  and **3237** on a UTC machine.
- `arrow.get(2024, 1, 1, tz="Europe/Paris")` silently ignores the typo'd
  keyword and returns UTC.
- `arrow.get("2024-01-01\t12:00+05:00")` silently drops the time and offset.
- `arrow.now().shift(months=5)` carries today's UTC offset into a month where
  it's wrong.
```

## Do-what-I-mean, a decade later

`arrow.get()` accepts timestamps, `Decimal`s, strings, format
strings, lists of format strings, `datetime`s, `date`s, tzinfo objects,
`struct_time`s, ISO-calendar tuples, combinations of these, or none at all — and decides
what you meant from the types and count:

```python
>>> arrow.get(2013, 5, 5)
<Arrow [2013-05-05T00:00:00+00:00]>
>>> arrow.get((2013, 5, 5))          # a 3-tuple is an ISO *week* date
<Arrow [2013-02-01T00:00:00+00:00]>
>>> arrow.get(time.localtime())      # struct_time assumed UTC
<Arrow [2026-08-23T22:06:53+00:00]>  # arrow.now() was 22:06+07:00
>>> arrow.get("1700000000")
ParserError: Could not match input '1700000000' to any of the following formats: ...
>>> arrow.Arrow.fromtimestamp("1700000000")   # but here a string is fine
<Arrow [2023-11-15T05:13:20+07:00]>
```

Numbers too large to be plausible are silently reinterpreted as milliseconds,
with a threshold computed from the *system time zone*, so the same
program parses the same data differently on different machines:

```python
>>> arrow.get(40_000_000_000)        # TZ=Asia/Bangkok
<Arrow [1971-04-08T23:06:40+00:00]>
>>> arrow.get(40_000_000_000)        # TZ=UTC
<Arrow [3237-07-19T23:06:40+00:00]>
```

The `tzinfo=` keyword *reinterprets* the wall time for strings (discarding an
explicit offset!), `datetime`s and `Arrow`s — but *converts* for timestamps:

```python
>>> arrow.get("2024-01-01T12:00:00+02:00", tzinfo="America/Los_Angeles")
<Arrow [2024-01-01T12:00:00-08:00]>            # the +02:00 is discarded
>>> arrow.get(1704110400, tzinfo="America/Los_Angeles")
<Arrow [2024-01-01T04:00:00-08:00]>            # converted
```

And the constructor accepts unknown keyword arguments without complaint:

```python
>>> arrow.get(2024, 1, 1, tz="Europe/Paris")   # typo for tzinfo=
<Arrow [2024-01-01T00:00:00+00:00]>
>>> arrow.Arrow(2024, 1, 1, timezone="Europe/Paris")
<Arrow [2024-01-01T00:00:00+00:00]>
```

*"Do what I mean"* and [*"be liberal in what you accept"*](https://en.wikipedia.org/wiki/Robustness_principle)
was the height of API ergonomics when Arrow and moment.js were designed,
and has fallen out of favor since:

- **JavaScript itself retreated from it.** Implicit coercion (`==`) and
  `Date`'s guess-the-format parsing became the language's famous footguns;
  moment.js is in maintenance mode and [recommends against itself for new
  projects](https://momentjs.com/news/#2020-09-14-project-status), and its successors
  are strict about their input.
- **Static typing changed what "ergonomic" means.** Since PEP 484, Python
  codebases increasingly rely on type checkers and IDE completion. A function
  whose behaviour depends on runtime types can only be approximated by
  overloads, and `Arrow.__getattr__` delegation means even `a.year` and
  `a.hour` are typed `Any`.
- **Guessing breeds data corruption.** "In the face of ambiguity,
  refuse the temptation to guess" is in the Zen of Python for a reason; a
  parser that guesses units, fills in fields, and reinterprets offsets turns
  malformed input into confidently wrong output instead of an error.

`whenever` sits at the other end of this trade-off: separate types for
separate concepts, one meaning per function, and mistakes that surface as type
errors or exceptions rather than as plausible values.

## Arrow keeps `datetime`'s arithmetic

Arrow's `shift()` adds to the local clock fields and then
repairs the result only if it lands on a skipped local time.
Like `datetime`, it {ref}`doesn't count <datetime-ignores-dst>` *elapsed* time:

```python
>>> a = arrow.get(2024, 3, 31, 1, 30, tzinfo="Europe/Paris")
>>> a.shift(hours=2)
<Arrow [2024-03-31T03:30:00+02:00]>
>>> (a.shift(hours=2).timestamp() - a.timestamp()) / 3600
1.0                                            # "2 hours" later is 1 hour later
>>> b = arrow.get(2024, 10, 27, 0, 30, tzinfo="Europe/Paris")
>>> (b.shift(hours=3).timestamp() - b.timestamp()) / 3600
4.0
```

Subtraction inherits the same model.
`b - a` counts elapsed time only if the two values carry different `tzinfo`
objects.

## Every operation drops `fold`

Arrow supports PEP 495's `fold` on input, but `shift()`, `+`, `span()`,
`floor()`, `ceil()` and `range()` all rebuild the value from its fields,
resetting `fold` to 0. During a repeated hour, that makes a zero-length shift
change the instant---while still comparing equal:

```python
>>> c = arrow.get(2024, 10, 27, 2, 30, tzinfo="Europe/Paris", fold=1)
>>> c.utcoffset()
datetime.timedelta(seconds=3600)               # the second 02:30
>>> c.shift(seconds=0).timestamp() - c.timestamp()
-3600.0
>>> c.shift(seconds=0) == c
True
```

## `'local'` is a snapshot, not a time zone

Version 1.4.0 replaced `dateutil.tz.tzlocal()` (a real,
DST-aware zone) with `datetime.now().astimezone().tzinfo`: the machine's UTC
offset *at this moment*, frozen into a fixed-offset time zone. It is used by
`arrow.now()`, `Arrow.fromtimestamp()`, `.to('local')` and `tzinfo='local'`.
Any value that lands in the other half of the year gets the wrong time:

```python
>>> # with TZ=America/New_York, in August
>>> n = arrow.now()
>>> n.tzinfo
datetime.timezone(..., 'EDT')  # -04:00
>>> n.shift(months=5)
<Arrow [2027-01-23T11:11:39.482253-04:00]>     # January in New York is -05:00
>>> arrow.get(2024, 1, 1, 12).to('local')
<Arrow [2024-01-01T08:00:00-04:00]>            # off by an hour!
>>> arrow.Arrow.fromtimestamp(0)
<Arrow [1969-12-31T20:00:00-04:00]>            # Should be 19:00
```

## Parsing guesses, injects, and truncates

Any whitespace other than a plain space is treated as end of input, and
whatever follows---including the time and offset---is silently dropped:

```python
>>> arrow.get("2024-01-01\t12:00+05:00")
<Arrow [2024-01-01T00:00:00+00:00]>
>>> arrow.get("2024-01-01 12:00", "YYYY-MM-DD")   # trailing text also ignored
<Arrow [2024-01-01T00:00:00+00:00]>
```

Time zone expressions are matched by an unanchored regex with an optional sign,
so junk becomes an offset:

```python
>>> arrow.get(2024, 1, 1, tzinfo="2024")
<Arrow [2024-01-01T00:00:00+20:24]>
>>> arrow.get(2024, 1, 1, tzinfo="+02:00junk")
<Arrow [2024-01-01T00:00:00+02:00]>
>>> arrow.get("2024-01-01T12:00+05:60")
<Arrow [2024-01-01T12:00:00+06:00]>            # minute 60 carried over
```

Round trips fail in both directions: `arrow.get(x.isoformat()) != x` for any
value in a repeated hour, the default `format()` output drops microseconds,
and the `ZZZ` token emits names (`'CEST'`, `'UTC+01:00'`) that the parser
rejects — while accepting `'CET'` as a DST-observing *zone*.

## `humanize()` has bands nobody would draw

```python
>>> now = arrow.get(2024, 1, 15, 12)
>>> [now.shift(days=d).humanize(now) for d in (13, 14, 15, 45, 46)]
['in a week', 'in 2 weeks', 'in a month', 'in a month', 'in 2 months']
```

Fifteen days is "a month"; "3 weeks" can never be produced; 44 days is
`'in 2 months'` when counted from January 31 but `'in a month'` from March 1;
364 days is `'in 12 months'` and 729 days `'in a year'`. A fix for the
fifteen-days case was merged and then reverted
([#1240](https://github.com/arrow-py/arrow/issues/1240)).

`dehumanize()`, the inverse, matches substrings: `"in 1.5 hours"` shifts by
five hours, `"in 1,000 hours"` by zero, `"in 5 minutes banana"` is accepted —
while `"in 1 hour"` and its own output `"instantly"` are rejected.

## Types stop at the wrapper

Arrow predates Python's typing era, and it shows.
`Arrow` declares no attributes for the datetime fields it exposes:
`year`, `month`, `hour` and the rest are served by `__getattr__`,
which makes every one of them `Any`.
The same delegation lets the wrapped `datetime` back out through inherited
methods, and the API disagrees with itself about what is a method and what is
a property:

```python
>>> reveal_type(a.year)              # mypy: Any  (served by __getattr__)
>>> reveal_type(a.hour)              # Any
>>> type(a.astimezone(ZoneInfo("UTC")))
<class 'datetime.datetime'>          # .to() returns Arrow; .astimezone() doesn't
>>> a.timestamp                      # a method — but int_timestamp is a property
<bound method Arrow.timestamp of <Arrow [...]>>
```

## Maintenance and performance

Releases are infrequent: 1.2.2 (January 2022), 1.3.0 (September 2023), 1.4.0
(October 2025), and three commits so far in 2026. The open DST-arithmetic
reports span 2022–2025, and the one substantive recent release introduced the
`'local'` regression above.

Performance is not Arrow's pitch, but the gap with the standard library is
wide for everyday operations:

| operation | Arrow 1.4 | standard library |
|---|---|---|
| `arrow.get("2024-01-01T12:00:00+01:00")` | 68 µs | `fromisoformat`: 0.25 µs |
| `a.shift(hours=1)` | 14 µs | `dt + timedelta`: 0.09 µs |
| `a + timedelta(hours=1)` | 3.1 µs | 0.09 µs |
| `a.to('UTC')` | 2.4 µs | `astimezone`: 0.4 µs |
| `a.year` | 0.22 µs | 0.02 µs |

In {ref}`benchmarks <benchmarks>`, `whenever` parses and converts one to two
orders of magnitude faster, while rejecting the inputs Arrow guesses about.
