---
myst:
  html_meta:
    description: >-
      A detailed comparison with Arrow: a friendly wrapper that keeps the
      standard library's arithmetic model, resolves ambiguity by guessing, and
      predates the typing era — with concrete examples of DST arithmetic,
      fold handling, do-what-I-mean parsing, humanize edge cases, and a
      regression in how "local" time is resolved.
---

# Why not Arrow?

[**Arrow**](https://pypi.org/project/arrow/) (2013) is the most-downloaded
third-party datetime library for Python. It was closely modeled on JavaScript's
`moment.js`: one friendly `Arrow` type, a permissive `arrow.get()` that accepts
almost anything, moment-style format tokens, and localized, human-readable
differences (`humanize()`) in some eighty locales.

To its credit — and unlike Pendulum — Arrow *wraps* a `datetime` rather than
subclassing it, so it avoids an entire class of substitutability problems.
But the wrapper is thin. Arithmetic, comparison and conversion are delegated
to the standard library and `dateutil.relativedelta`, so Arrow inherits
`datetime`'s model — wall-clock arithmetic, `fold` quirks and all — while its
API works hard to hide the details that model forces you to care about.
And its central design idea, *do what I mean*, has aged badly: the same call
means different things depending on argument types, results silently depend on
the wall clock and the machine's timezone, and neither a reader nor a type
checker can tell what a given expression returns.

```{note}
This section is up to date as of Arrow version 1.4.0.
Every example below was run against that version with CPython 3.14.
```

```{admonition} Arrow 1.4.0 at a glance
:class: caution

A sample of behaviour you can reproduce today, each explained further down:

- `arrow.now().shift(months=5)` carries today's UTC offset into a month where
  it's wrong — `'local'` became a fixed-offset snapshot in 1.4.0.
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
- `arrow.utcnow().shift(days=-10).humanize(locale='uk')` raises `ValueError`.
- 15 days is `'in a month'`; "3 weeks" is unreachable.
- `arrow.get("1:00 pM", "h:mm a")` returns 01:00.
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

Numbers too large to be plausible are silently reinterpreted as milliseconds —
with a threshold computed from the *machine's local timezone*, so the same
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

This style of interface — *do what I mean*, or Postel's "be liberal in what
you accept" applied to an API — was the height of ergonomics when Arrow and
moment.js were designed. It has since fallen out of favor, for reasons the
wider ecosystem learned the hard way:

- **JavaScript itself retreated from it.** Implicit coercion (`==`) and
  `Date`'s guess-the-format parsing became the language's canonical footguns;
  moment.js is in maintenance mode and [recommends against itself for new
  projects](https://momentjs.com/docs/#/-project-status/), and its successors
  (Luxon, date-fns, the Temporal proposal) are strict about input types and
  reject fuzzy parsing outright.
- **Static typing changed what "ergonomic" means.** Since PEP 484, Python
  codebases increasingly rely on type checkers and IDE completion. A function
  whose behaviour depends on runtime types can only be approximated by
  overloads, and `Arrow.__getattr__` delegation means even `a.year` and
  `a.hour` are typed `Any` — autocompletion and type checking stop at every
  Arrow attribute access.
- **Guessing is how data corruption happens.** "In the face of ambiguity,
  refuse the temptation to guess" is in the Zen of Python for a reason; a
  parser that guesses units, fills in fields, and reinterprets offsets turns
  malformed input into confidently wrong output instead of an error. Even the
  IETF now warns against liberal acceptance in long-lived systems
  ([RFC 9413](https://www.rfc-editor.org/rfc/rfc9413)).

`whenever` sits at the other end of this trade-off: separate types for
separate concepts, one meaning per function, and mistakes that surface as type
errors or exceptions rather than as plausible values.

## The wrapper keeps `datetime`'s arithmetic

Arrow's `shift()` adds to the wall-clock fields (via `relativedelta`) and then
repairs the result only if it lands on a nonexistent time. It never *counts*
elapsed time:

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

`+` and `-` with a `timedelta` don't even get the repair, so they can *create*
times that never existed — the same instant as `shift()` would produce, yet
unequal to it:

```python
>>> a + timedelta(hours=1)
<Arrow [2024-03-31T02:30:00+01:00]>            # 02:30 doesn't exist
>>> (a + timedelta(hours=1)).imaginary
True
>>> a + timedelta(hours=1) == a.shift(hours=1)
False
```

Subtraction and `humanize()` follow the same wall-clock model whenever both
values share a `tzinfo` object (which cached zones do):

```python
>>> s = arrow.get(2024, 3, 30, 12, tzinfo="Europe/Paris")
>>> e = arrow.get(2024, 3, 31, 12, tzinfo="Europe/Paris")   # 23 hours later
>>> e - s, e.humanize(s)
(datetime.timedelta(days=1), 'in a day')
>>> e.to('UTC') - s                             # different tzinfo object
datetime.timedelta(seconds=82800)
```

So whether `b - a` measures elapsed time depends on whether two objects happen
to share a `tzinfo` instance. These are the standard library's semantics,
faithfully wrapped; issues
[#1136](https://github.com/arrow-py/arrow/issues/1136) (2022),
[#1162](https://github.com/arrow-py/arrow/issues/1162) (2023) and
[#1209](https://github.com/arrow-py/arrow/issues/1209) (2025) about them
remain open.

## `fold` is dropped by every operation

Arrow supports PEP 495's `fold` on input, but `shift()`, `+`, `span()`,
`floor()`, `ceil()` and `range()` all rebuild the value from its fields,
resetting `fold` to 0. During a repeated hour, that makes a zero-length shift
change the instant — while still comparing equal:

```python
>>> c = arrow.get(2024, 10, 27, 2, 30, tzinfo="Europe/Paris", fold=1)
>>> c.utcoffset()
datetime.timedelta(seconds=3600)               # the second 02:30
>>> c.shift(seconds=0).timestamp() - c.timestamp()
-3600.0
>>> c.shift(seconds=0) == c
True
>>> c.floor('hour')                            # 90 minutes earlier
<Arrow [2024-10-27T02:00:00+02:00]>
>>> c.is_between(*c.span('hour'), bounds='[]')
False
>>> c.humanize(c.floor('hour'))
'in 30 minutes'
```

The second occurrence of a repeated hour is unreachable by iteration — a
25-hour day yields 24 wall-clock hours, with a silent two-hour jump:

```python
>>> [str(x)[11:] for x in arrow.Arrow.range('hour',
...     arrow.get(2024,10,27,0,tzinfo="Europe/Paris"),
...     arrow.get(2024,10,27,4,tzinfo="Europe/Paris"))]
['00:00:00+02:00', '01:00:00+02:00', '02:00:00+02:00', '03:00:00+01:00', '04:00:00+01:00']
```

Nonexistent times, meanwhile, are accepted and preserved (`.imaginary` exists
to check for them, but nothing does), and wall-clock equality makes a value
unequal to its own normalization:

```python
>>> g = arrow.get(2024, 3, 10, 12, tzinfo="America/Havana").floor('day')
>>> g, g.imaginary                              # midnight was skipped
(<Arrow [2024-03-10T00:00:00-05:00]>, True)     # a time that never happened
>>> g2 = arrow.get(2024, 3, 31, 2, 30, tzinfo="Europe/Paris")
>>> g2 == g2.shift(seconds=0), g2.timestamp() == g2.shift(seconds=0).timestamp()
(False, True)
```

(See also [#1124](https://github.com/arrow-py/arrow/issues/1124) and
[#1097](https://github.com/arrow-py/arrow/issues/1097) for `ceil`/`span_range`
around midnight transitions.)

## `'local'` is a snapshot, not a timezone

Version 1.4.0 (October 2025) replaced `dateutil.tz.tzlocal()` — a real,
DST-aware zone — with `datetime.now().astimezone().tzinfo`: the machine's UTC
offset *at this moment*, frozen into a fixed-offset timezone. It is used by
`arrow.now()`, `Arrow.fromtimestamp()`, `.to('local')` and `tzinfo='local'`.
Any value that then lands in the other half of the year keeps the wrong
offset. With `TZ=America/New_York`, in August:

```python
>>> n = arrow.now()
>>> n.tzinfo
datetime.timezone(datetime.timedelta(days=-1, seconds=72000), 'EDT')
>>> n.shift(months=5)
<Arrow [2027-01-23T11:11:39.482253-04:00]>     # January in New York is -05:00
>>> n.floor('year')
<Arrow [2026-01-01T00:00:00-04:00]>
>>> arrow.get(2024, 1, 1, 12).to('local')
<Arrow [2024-01-01T08:00:00-04:00]>            # the clock on the wall read 07:00
>>> arrow.Arrow.fromtimestamp(0)
<Arrow [1969-12-31T20:00:00-04:00]>            # New York showed 19:00
```

`arrow.now()` is the library's most common constructor; everything
calendar-shaped derived from it — `floor('month')`, `span('year')`,
`shift(months=...)`, `range('month', arrow.now(), ...)` — is an hour off for
half of every year. The release that introduced this is the one that makes
Arrow look actively maintained again after a two-year gap: modernization
without the test coverage to catch an hour-sized error in the default path.

## Parsing guesses, injects, and truncates

Any whitespace other than a plain space is treated as end of input, and
whatever follows — including the time and offset — is silently dropped:

```python
>>> arrow.get("2024-01-01\t12:00+05:00")
<Arrow [2024-01-01T00:00:00+00:00]>
>>> arrow.get("2024-01-01 12:00", "YYYY-MM-DD")   # trailing text also ignored
<Arrow [2024-01-01T00:00:00+00:00]>
```

Timezone expressions are matched by an unanchored regex with an optional sign,
so junk becomes an offset:

```python
>>> arrow.get(2024, 1, 1, tzinfo="2024")
<Arrow [2024-01-01T00:00:00+20:24]>
>>> arrow.get(2024, 1, 1, tzinfo="+02:00junk")
<Arrow [2024-01-01T00:00:00+02:00]>
>>> arrow.get("2024-01-01T12:00+05:60")
<Arrow [2024-01-01T12:00:00+06:00]>            # minute 60 carried over
```

Format-based parsing has its own surprises: a mixed-case meridian matches the
(case-insensitive) regex and is then ignored by the (case-sensitive) handler;
the `Do` ordinal token crashes in ~150 of 189 locales; a list of formats
doesn't fall through when a candidate matches structurally but is out of
range; a parsed weekday that contradicts the date is discarded; day-of-year
366 rolls into the next year:

```python
>>> arrow.get("1:00 pM", "h:mm a")
<Arrow [0001-01-01T01:00:00+00:00]>            # should be 13:00
>>> arrow.get("3.", "Do", locale="de")
IndexError: no such group
>>> arrow.get("13/06/2024", ["MM/DD/YYYY", "DD/MM/YYYY"])
ValueError: month must be in 1..12, not 13     # never tries the second format
>>> arrow.get("2023-366")
<Arrow [2024-01-01T00:00:00+00:00]>
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
15-days-is-a-month behaviour was merged and then reverted
([#1240](https://github.com/arrow-py/arrow/issues/1240)). In eighteen locales
(`uk`, `ro`, `sl`, `bg`, `hi`, `is`, …) the default code path simply crashes:

```python
>>> now.shift(days=8).humanize(now, locale='uk')
ValueError: Humanization of the 'week' granularity is not currently translated in the 'uk' locale. ...
```

And the same instant can humanize differently depending on how you spell it:

```python
>>> c = arrow.Arrow(2024, 3, 31, 4, 0, tzinfo=ZoneInfo("Europe/Amsterdam"))
>>> other_arrow = arrow.Arrow(2024, 3, 31, 0, 0, tzinfo='UTC')
>>> other_dt = datetime(2024, 3, 31, 0, 0, tzinfo=timezone.utc)
>>> other_arrow == other_dt
True
>>> c.humanize(other_arrow), c.humanize(other_dt)
('in 2 hours', 'in 3 hours')
```

`dehumanize()`, the inverse, matches substrings: `"in 1.5 hours"` shifts by
five hours, `"in 1,000 hours"` by zero, `"in 5 minutes banana"` is accepted —
while `"in 1 hour"` and its own output `"instantly"` are rejected.

## Typing and legibility

Arrow predates Python's typing era, and it shows:

```python
>>> reveal_type(a.year)              # mypy: Any  (served by __getattr__)
>>> reveal_type(a.hour)              # Any
>>> type(a.astimezone(ZoneInfo("UTC")))
<class 'datetime.datetime'>          # .to() returns Arrow; .astimezone() doesn't
>>> a.timestamp                      # a method — but int_timestamp is a property
<bound method Arrow.timestamp of <Arrow [...]>>
```

The formatter consumes any letter it recognizes, anywhere:

```python
>>> arrow.get(2024, 1, 15, 12).format("Hello World")
'12ello 2024-W03-1orl1'
>>> arrow.get(2024, 1, 1).format("X")
'1704067200.0'                       # the docs show an integer
>>> arrow.FORMAT_RFC3339
'YYYY-MM-DD HH:mm:ssZZ'              # a space where RFC 3339 requires 'T'
```

## Maintenance and performance

Arrow's release cadence tells its own story: 1.2.2 (January 2022), 1.3.0
(September 2023), 1.4.0 (October 2025); three commits so far in 2026. The
open DST-arithmetic reports span 2022–2025, and the one substantive recent
release introduced the `'local'` regression above.

Performance is not Arrow's pitch, but the gap is large where it matters most:

| operation | Arrow 1.4 | standard library |
|---|---|---|
| `arrow.get("2024-01-01T12:00:00+01:00")` | 68 µs | `fromisoformat`: 0.25 µs |
| `a.shift(hours=1)` | 14 µs | `dt + timedelta`: 0.09 µs |
| `a + timedelta(hours=1)` | 3.1 µs | 0.09 µs |
| `a.to('UTC')` | 2.4 µs | `astimezone`: 0.4 µs |
| `a.year` | 0.22 µs | 0.02 µs |

In {ref}`benchmarks <benchmarks>`, `whenever` parses and converts one to two
orders of magnitude faster — while rejecting the inputs Arrow guesses about.
