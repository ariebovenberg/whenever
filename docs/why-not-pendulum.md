---
tocdepth: 3
myst:
  html_meta:
    description: >-
      A detailed comparison with Pendulum: what it improves over the standard
      library, why an API cannot be fixed by subclassing it, and how four
      further design decisions — treat naive datetimes as a mistake, redefine
      fold, put months inside timedelta, and complete the input rather than
      reject it — produce failures in equality, arithmetic, DST handling, and
      parsing that cannot be patched out.
---

# Why not Pendulum?

[**Pendulum**](https://pypi.org/project/pendulum/) arrived in 2016 with
several improvements over the standard library: a fluent API, localization, and the
main attraction — arithmetic that knows about DST.
All this delivered as a drop-in replacement:
Pendulum's classes subclass the standard library's, so existing code keeps working.

But this promise is a trap:
a drop-in replacement [can't *also* change behavior](https://en.wikipedia.org/wiki/Liskov_substitution_principle).
Fixing an API this way may work in the short term, but it invites new contradictions and footguns.
Pendulum's numerous bugs are not accidents of implementation but a result
of its fundamental design.[^versions]

Subclassing isn't the only decision that backfires.
Pendulum also {ref}`assumes UTC <pendulum-decision-naive>` when a timezone is missing,
{ref}`redefines fold <pendulum-decision-fold>`,
{ref}`puts months inside a timedelta <pendulum-decision-months>`,
and {ref}`completes input <pendulum-decision-parse>` instead of rejecting it.
None of these can be fixed without breaking existing code.

```{admonition} Pendulum 3.2.0 at a glance
:class: caution

A sample of behavior you can reproduce today:

- [`dt + timedelta` *inspects the call stack* to decide the outcome](#pendulum-add-stack)
- [The result of `parse("12:00")` depends on *when* you run it](#pendulum-parse-now)
- [`today("Africa/Cairo")` is *yesterday*](#pendulum-today-yesterday), for
  one whole day each year
- [A 3-hour interval reports `.hours == 4`](#pendulum-intervals)
- [`end - (end - start)` can land *years* before `start`](#pendulum-intervals)
- [`instance(a_datetime)` can move the instant by an
  hour](#pendulum-gap-fold)
```

(pendulum-decision-dropin)=
## An API can't be fixed by subclassing it

> It provides classes that are drop-in replacements for the native ones (they
> inherit from them).
>
> — [Pendulum's documentation](https://pendulum.eustace.io/docs/#introduction)

Drop-in compatibility is Pendulum's main selling point,
and it does this by subclassing.
Subclassing is also a well-worn trap.
While a subclass is free to *add* behavior, the moment it *changes* behavior,
every piece of code ever written against the base class can [break when handed this subclass](https://en.wikipedia.org/wiki/Liskov_substitution_principle).

Pendulum walked straight in. Its main attraction, arithmetic that
knows about DST, is exactly such a behavior change.
A subclass of `datetime` either fixes how `+` behaves,
*or* is a drop-in replacement. It cannot be both.

After all: a subclass can't predict which semantics the caller expects.

Unless it guesses.

(pendulum-add-stack)=

### Pendulum guesses which semantics the caller expects

The best *and* worst part of Python is that you can do almost anything.
Here's how Pendulum [tries to have it both ways](https://github.com/python-pendulum/pendulum/blob/aea611d7a1c15ed0da56505c3f370fe4446ba733/src/pendulum/datetime.py#L1237-L1245):

```python
# src/pendulum/datetime.py (3.2.0)
def __add__(self, other):
    ...
    caller = traceback.extract_stack(limit=2)[0].name
    if caller == "astimezone":
        return super().__add__(other)
    return self._add_timedelta_(other)
```

Pendulum walks the call stack and picks between two kinds of arithmetic based on
the *name of the function that called it*.
Name a function of your own `astimezone`, and `+` changes meaning inside it:

```python
>>> from datetime import timedelta
>>> def astimezone(x):
...     return x + timedelta(hours=24)
>>> base = pendulum.datetime(2013, 3, 30, 12, tz="Europe/Paris")
>>> base + timedelta(hours=24)
DateTime(2013, 3, 31, 13, 0, 0, tzinfo=Timezone('Europe/Paris'))
>>> astimezone(base)
DateTime(2013, 3, 31, 12, 0, 0, tzinfo=Timezone('Europe/Paris'))
```

Why do this? Why this particular name?

During a timezone conversion, the standard library's machinery
(`ZoneInfo.fromutc()`) calls `+` on whatever datetime it was
handed, expecting `datetime` semantics. On a Pendulum subclass, that
dispatches to Pendulum's redefined `+`, which would misinterpret the
value. Pendulum cannot restructure the conversion (it
belongs to the standard library), cannot un-redefine `+` (that is the main
attraction), and cannot stop being a subclass (that is the selling point).
What's left is guessing, at runtime, whose semantics the caller expects —
from the caller's name. That's why `dt + timedelta` in *your* code depends
on what your function happens to be called.

And the guess covers only the one caller it names. Any other `tzinfo` whose
`fromutc()` does arithmetic, `dateutil`'s for example, goes through the
"wrong" branch, and the timezone is lost along the way:

```python
>>> from dateutil import tz
>>> d = pendulum.datetime(2024, 7, 1, 12, tz="UTC")
>>> d.astimezone(tz.gettz("Europe/Paris"))
DateTime(2024, 7, 1, 12, 0, 0)                 # naive, and not 14:00
>>> datetime(2024, 7, 1, 12, tzinfo=pendulum.UTC).astimezone(tz.gettz("Europe/Paris"))
datetime.datetime(2024, 7, 1, 14, 0, tzinfo=tzfile('/usr/share/zoneinfo/Europe/Paris'))
```

The list of names can be extended, but it cannot be completed. Once `+` means
something different on the subclass, every caller that adds a `timedelta` —
stdlib internals, `dateutil`, any third-party `tzinfo`, your own code — is a
caller whose expectations have to be guessed. And the guessing isn't free: it
runs on every `+`, every `astimezone()` and every `in_tz()`, and inspects
the call stack every time.

(pendulum-performance)=

### Every addition pays for the guess

While Pendulum initially promised [improved performance](https://pendulum.eustace.io/faq/),
its `+` is now hundreds of times slower than the standard library's:

```python
>>> from timeit import timeit
>>> hour = timedelta(hours=1)
>>> std = datetime(2024, 1, 1, tzinfo=ZoneInfo("Europe/Paris"))
>>> pdl = pendulum.datetime(2024, 1, 1, tz="Europe/Paris")
>>> timeit("std + hour", globals=globals(), number=1_000_000)   # seconds
0.06
>>> timeit("pdl + hour", globals=globals(), number=1_000_000)
39.47
```

The hack is the cause. `ZoneInfo.fromutc()` calls `+`, so every
`astimezone()`, `in_tz()`, and `+` walks the stack.
`traceback` then consults `linecache`, which `stat()`s the source file.
That is *a system call per datetime addition*.

(pendulum-v2-v3)=

:::{admonition} Why did Pendulum use to be faster?
:class: hint

Version 2 had the same design, but paid for it differently.
It shipped its own timezone implementation, whose `fromutc()` never called `+`.
Version 3.0 replaced that implementation with a `ZoneInfo` subclass.
The standard library's conversion code, which does call `+`,
entered the path of every conversion.
The hack appears in the same release.
:::

:::{admonition} How `whenever` does it
:class: tip

`whenever`'s types don't subclass `datetime`, so `+` means one thing.
[Converting to and from the standard library](guide/stdlib-convert.md) is an explicit step.
It's also part of why `whenever`'s own types {ref}`can't be subclassed <faq-why-no-subclassing>`.
:::

(pendulum-substitutable)=

### What does drop-in buy?

The "drop-in replacement" promise also fails in a blunter way:
some code refuses a Pendulum value outright.
Many libraries check `type()` rather than `isinstance()`.
`sqlite3`, for example, binds a `datetime` and rejects its subclass:

```python
>>> con.execute("select ?", (datetime(2024, 1, 1),)).fetchone()
('2024-01-01 00:00:00',)
>>> con.execute("select ?", (pendulum.datetime(2024, 1, 1),)).fetchone()
Traceback (most recent call last):
  ...
ProgrammingError: Error binding parameter 1: type 'DateTime' is not supported
```

Pendulum's documentation [lists](https://pendulum.eustace.io/docs/#limitations)
`sqlite3`, `mysqlclient`, `PyMySQL`, and Django as known cases,
and calls its own list "non-exhaustive".
It can never be exhaustive:
checking the exact type is ordinary practice,
and no subclass can stop other people's code from doing it.
Even Pendulum's own Rust extension does it:
`precise_diff` checks the exact type of its second argument
([#906](https://github.com/python-pendulum/pendulum/issues/906)).

(pendulum-zoneinfo-cache)=

### Subclassing `ZoneInfo` forfeits its cache

`datetime` isn't the only class Pendulum subclasses.
`pendulum.Timezone` subclasses `ZoneInfo`, and `zoneinfo`'s strong cache
serves only the exact base type. When no `Timezone("Asia/Tokyo")` object
is alive, the next `tz="Asia/Tokyo"` re-reads and re-parses the tzdata file:

```python
>>> timeit('ZoneInfo("Asia/Tokyo")', globals=globals(), number=10_000)
0.003
>>> timeit('pendulum.timezone("Asia/Tokyo")', globals=globals(), number=10_000)
0.75
```

## Four more decisions that cannot be fixed

Subclassing is the biggest decision Pendulum is built on, but not the only
one. Four more decisions run just as deep and cannot be 
undone without changing what existing code computes:

- **{ref}`Treat naive datetimes as a mistake to be corrected <pendulum-decision-naive>`**
  rather than as a distinct kind of value.
- **{ref}`Redefine fold <pendulum-decision-fold>`**
  with a different default, and the opposite meaning in a gap.
- **{ref}`Put months and years inside a timedelta <pendulum-decision-months>`** 
  alongside a fixed number of seconds.
- **{ref}`Complete the input rather than reject it <pendulum-decision-parse>`** by
  filling what is missing from the clock and the machine's time zone.

(pendulum-decision-naive)=

### Treat naive datetimes as a mistake to be corrected

> Pendulum enforces timezone aware datetimes, and using them is the preferred
> and recommended way of using the library.
>
> — [Pendulum's documentation](https://pendulum.eustace.io/docs/#instantiation)

The instinct is good: naive datetimes really are a common source of bugs.
But Pendulum treats them as an error to be corrected rather than a value with
its own meaning.
Naive values still exist though, and Pendulum even gives them extra
behavior on top of the standard library's already [complex semantics](stdlib-pitfalls/naive-meaning.md).

(pendulum-utc-assumption)=

#### Missing timezone information becomes UTC

If a naive result is unacceptable, then Pendulum must invent a timezone
where one is missing. Most often, this is UTC:

```python
>>> pendulum.parse("2024-03-10T15:00")
DateTime(2024, 3, 10, 15, 0, 0, tzinfo=Timezone('UTC'))
>>> pendulum.instance(datetime(2024, 3, 10, 15))
DateTime(2024, 3, 10, 15, 0, 0, tzinfo=Timezone('UTC'))
```

UTC is a reasonable guess. It is still a guess.
A timestamp that says "15:00" and nothing else might come from a server in UTC,
or from a user in Tokyo.
Pendulum turns an honest "unknown" into a confident "UTC",
and nothing downstream can tell the difference.
If the guess is wrong, the instant is silently off by hours.

Pendulum's entry points also disagree about what a missing time zone means:

| entry point | a zoneless input becomes |
|---|---|
| `pendulum.parse(...)` | UTC |
| `pendulum.instance(...)` | UTC |
| `pendulum.strptime(...)` | UTC |
| `pendulum.from_timestamp(...)` | UTC |
| `DateTime.fromtimestamp(...)` | the system timezone |
| `DateTime.combine(...)` | naive |

Even the explicit escape hatch is inconsistent: given a `tz`, `instance()`
applies it to a standard-library naive value, but returns Pendulum's own
naive values *unchanged*:

```python
>>> pendulum.instance(datetime(2024, 1, 1), tz="Europe/Paris")
DateTime(2024, 1, 1, 0, 0, 0, tzinfo=Timezone('Europe/Paris'))
>>> pendulum.instance(pendulum.naive(2024, 1, 1), tz="Europe/Paris")
DateTime(2024, 1, 1, 0, 0, 0)
```

(pendulum-naive-meanings)=

#### Naive datetimes accumulate even more meanings

The standard library already overloads a naive datetime with three readings:
system-local time (`timestamp()`, `astimezone()`), plain calendar fields
(comparison and arithmetic), and UTC (`utcnow()`, `utcfromtimestamp()`).
Notably, the standard library has been *retiring* that third reading:
`utcnow()` and `utcfromtimestamp()` are deprecated since Python 3.12,
precisely because naive-but-actually-UTC values are a bug factory.

Pendulum keeps all three inherited readings, doubles down on the deprecated
one (`parse()`, `instance()`, and `strptime()` all assume UTC)
and adds a fourth of its own: `in_timezone()` reads a
naive value as "already in whatever zone you name".

```python
>>> n = pendulum.naive(2024, 1, 1)
>>> n.tzname()                              # inherited: no timezone
None
>>> n.astimezone(pendulum.UTC)              # inherited: local (e.g. New York)
DateTime(2024, 1, 1, 5, 0, 0, tzinfo=Timezone('UTC'))
>>> pendulum.instance(datetime(2024, 1, 1)) # doubled-down: it is UTC
DateTime(2024, 1, 1, 0, 0, 0, tzinfo=Timezone('UTC'))
>>> n.in_tz("Europe/Paris")                 # new: "it is already Paris"
DateTime(2024, 1, 1, 0, 0, 0, tzinfo=Timezone('Europe/Paris'))
```

The method, not the value, decides which reading applies: the same `n`
denotes three different instants across the five calls above. The standard
library spent a decade retiring one of a naive datetime's meanings; Pendulum
ships four.

:::{admonition} How `whenever` does it
:class: tip

`whenever` keeps naive datetimes — as {class}`~whenever.PlainDateTime` — but
makes them a separate type rather than a defective one. A `PlainDateTime` has
no timezone and never acquires one implicitly: there is no reading of it as
UTC, as system-local, or as "already in whatever zone you name". Turning one
into an instant is an explicit call —
{meth}`~whenever.PlainDateTime.assume_tz`,
{meth}`~whenever.PlainDateTime.assume_utc`, or
{meth}`~whenever.PlainDateTime.assume_fixed_offset` — whose name says which
assumption you are making. Mixing the two kinds up is a type error rather
than a silent shift of several hours.
:::

(pendulum-decision-fold)=

### Redefine `fold` rather than adopt it

> Here, 2:30 exists twice in the day so pendulum will assume that the
> transition already occurred.
>
> — [Pendulum's documentation](https://pendulum.eustace.io/docs/#normalization)

The `fold` flag (PEP 495) on `datetime` is the standard library's way to distinguish ambiguous local
times. Pendulum keeps the flag but gives it a meaning of its own:
`fold` picks which side of the transition the result lands on, `0` for before and `1` for after.
That's a deliberate and internally consistent model.
It's also not PEP 495's, and values cross between the two libraries all the time.

(pendulum-fold-default)=

#### The default is different from everything else

Pendulum defaults to `fold=1`, selecting the offset *after* a backwards
transition. Python's standard library and the convention used by most datetime
libraries default to the {ref}`offset before the transition<ambiguity-default>`.
This default is significant: moving code from `datetime` to Pendulum can change
which instant an ambiguous local time represents.
The default also has further implications.

(pendulum-gap-fold)=

#### For skipped times, `fold` means the opposite of what it means in PEP 495

When the clock jumps from 02:00 to 03:00, a time like 02:30 doesn't exist.
`fold` decides where it lands, and Pendulum decides the opposite of the standard library:

| skipped 02:30 becomes | `fold=0` | `fold=1` |
|---|---|---|
| standard library (PEP 495) | 03:30 | 01:30 |
| Pendulum | 01:30 | 03:30 |

The reversal bites when converting.
`instance()` copies the standard library's `fold`,
so a skipped time moves by an hour on its way into Pendulum.
And since `pendulum.datetime()` defaults to `fold=1`,
Pendulum's own entry points disagree about the same wall time:

```python
>>> from zoneinfo import ZoneInfo
>>> std = datetime(2013, 3, 31, 2, 30, tzinfo=ZoneInfo("Europe/Paris"))   # skipped time
>>> std.timestamp()
1364693400.0
>>> pendulum.instance(std), pendulum.instance(std).timestamp()
(DateTime(2013, 3, 31, 1, 30, 0, tzinfo=Timezone('Europe/Paris')), 1364689800.0)
>>> pendulum.instance(datetime(2013, 3, 31, 2, 30), tz="Europe/Paris")
DateTime(2013, 3, 31, 1, 30, 0, tzinfo=Timezone('Europe/Paris'))
>>> pendulum.datetime(2013, 3, 31, 2, 30, tz="Europe/Paris")
DateTime(2013, 3, 31, 3, 30, 0, tzinfo=Timezone('Europe/Paris'))
```

(pendulum-today-yesterday)=

#### `today()` can be yesterday

The choice of `fold` leaks into operations that never mention it.
`start_of()`, `replace()`, `at()`, and several other methods
re-resolve the wall time using the value's existing `fold`.
So does `today()`.

In a timezone where DST starts at midnight, midnight itself is skipped once a year.
Egypt, Chile, Cuba, Lebanon, and the Azores all do this.
On that day, `today()` resolves the skipped midnight *backwards*, into the previous day:

```python
>>> with pendulum.travel_to(pendulum.datetime(2025, 4, 25, 12, tz="Africa/Cairo"), freeze=True):
...     pendulum.today("Africa/Cairo")
DateTime(2025, 4, 24, 23, 0, 0, tzinfo=Timezone('Africa/Cairo'))
```

(pendulum-equality)=

#### Equal values can be an hour apart

The standard library's [equality quirks](stdlib-pitfalls/broken-equality.md) apply to Pendulum too:
within one timezone, `==` and `<` compare the wall clock and ignore `fold`.
The standard library is at least consistent about it, because its `-` ignores `fold` as well.
Pendulum redefines `-` to measure elapsed time, but inherits `==` and `<`.
Its operators now contradict each other:

```python
>>> f0 = pendulum.datetime(2023, 11, 5, 1, 25, tz="America/Los_Angeles", fold=0)
>>> f1 = f0.replace(fold=1)
>>> f0 == f1
True
>>> (f1 - f0).total_seconds()           # the standard library says 0
3600.0
>>> later = pendulum.datetime(2023, 11, 5, 1, 15, tz="America/Los_Angeles", fold=1)
>>> earlier = pendulum.datetime(2023, 11, 5, 1, 25, tz="America/Los_Angeles", fold=0)
>>> later < earlier
True
>>> (later - earlier).total_seconds()    # the standard library says -600
3000.0
```

Two more things differ from the standard library.
Pendulum's `repr()` omits `fold`, so `f0` and `f1` print identically.
And Pendulum's documentation [says](https://pendulum.eustace.io/docs/#comparison)
"the comparison is done in the UTC timezone".
If it were, `f0 == f1` would be `False`, and this would be `True`:

```python
>>> f0 == f0.in_tz("UTC")
False
```

First reported in
[#351](https://github.com/python-pendulum/pendulum/issues/351);
a fix is proposed in
[#985](https://github.com/python-pendulum/pendulum/pull/985).

:::{admonition} How `whenever` does it
:class: tip

Ambiguity in `whenever` is settled by an explicit
{ref}`disambiguation <ambiguity>` argument on the operation that creates the
value, defaulting to `"compatible"` — the same convention as RFC 5545,
Temporal, NodaTime, and the standard library's `fold=0` — with `"raise"`
available when you would rather be told than guessed at. The resolved offset
is part of the value, so copying, pickling, and converting it preserve the
instant.
:::

(pendulum-decision-months)=

### Put months and years inside a `timedelta`

> Even though it inherits from the `timedelta` class, its behavior is slightly
> different. The more important to notice is that the native normalization
> does not happen, this is so that it feels more intuitive.
>
> — [Pendulum's documentation](https://pendulum.eustace.io/docs/#duration)

A `Duration` has to express both "90 minutes" and "one month", and Pendulum
stores them in one object: the `timedelta` it inherits for the exact part,
extra integer fields beside it for the calendar part. Applying such an object
then requires a choice between clock and elapsed arithmetic, which
Pendulum makes for you, from context.

(pendulum-durations)=

#### Durations lose their calendar units

Pendulum's `Duration` adds years and months to `timedelta`.
That is a difficult fit: `timedelta` represents an exact elapsed duration,
while a calendar month has no fixed length.
Pendulum approximates a month as 30 days for compatibility with `timedelta`,
while applying a month to a datetime uses calendar arithmetic.
Consequently, values that compare equal are not interchangeable:

```python
>>> month = pendulum.duration(months=1)
>>> thirty_days = pendulum.duration(days=30)
>>> month == thirty_days, hash(month) == hash(thirty_days)
(True, True)
>>> jan_31 = pendulum.datetime(2024, 1, 31)
>>> jan_31 + month
DateTime(2024, 2, 29, 0, 0, 0, tzinfo=Timezone('UTC'))
>>> jan_31 + thirty_days
DateTime(2024, 3, 1, 0, 0, 0, tzinfo=Timezone('UTC'))
```

Because the calendar fields live beside the `timedelta` rather than in it,
ordinary operations erase them:

```python
>>> month + pendulum.duration()
Duration(weeks=4, days=2)
>>> month * 1.0
Duration()
>>> month / 2
Duration()
>>> pendulum.duration(years=1) / 2, pendulum.duration(years=3) / 2
(Duration(), Duration(years=2))
>>> import copy, pickle
>>> copy.copy(month), pickle.loads(pickle.dumps(month))
(Duration(weeks=4, days=2), Duration(weeks=4, days=2))
```

Operators Pendulum doesn't override fall back to `timedelta`'s and return
the base class, dropping the calendar fields the same way:

```python
>>> abs(pendulum.duration(months=-1))
datetime.timedelta(days=30)
>>> type(+pendulum.duration(days=1))
<class 'datetime.timedelta'>
```

Compatibility with the `timedelta` base class is asymmetric:
`timedelta(hours=1) / day` works, `day / timedelta(hours=1)` raises
`AttributeError: 'datetime.timedelta' object has no attribute '_to_microseconds'`,
as do floor division, modulo, and `divmod()`
([#382](https://github.com/python-pendulum/pendulum/issues/382), since 2019;
these operators ignore months altogether,
[#799](https://github.com/python-pendulum/pendulum/issues/799)).

(pendulum-implicit-arithmetic)=

#### Calendar and exact arithmetic are chosen implicitly

Pendulum's `add()` and `subtract()` are a real improvement over `datetime`:
they distinguish calendar days from elapsed hours.
The trouble is that Pendulum picks *which kind* of arithmetic to apply from incidental details:
which other units appear in the same call, and whether you wrote `+` or `-`.

If any calendar unit is present in an `add()` call,
Pendulum applies *all* units to the wall clock, hours included:

```python
>>> b = pendulum.datetime(2024, 3, 30, 1, 30, tz="Europe/Paris")
>>> b.add(days=1, hours=2)
DateTime(2024, 3, 31, 3, 30, 0, tzinfo=Timezone('Europe/Paris'))
>>> b.add(days=1).add(hours=2)
DateTime(2024, 3, 31, 4, 30, 0, tzinfo=Timezone('Europe/Paris'))
```

`+` decomposes a `Duration` into units; `-` collapses it to seconds.
So the obvious round trip fails, and `dt - delta` differs from both
`dt.subtract(...)` and `dt + -delta`:

```python
>>> d = pendulum.duration(days=1, hours=2)
>>> (b + d) - d
DateTime(2024, 3, 30, 0, 30, 0, tzinfo=Timezone('Europe/Paris'))   # not b
>>> dt = pendulum.datetime(2013, 4, 2, tz="Europe/Paris")
>>> three_days = pendulum.duration(days=3)
>>> dt.subtract(days=3)
DateTime(2013, 3, 30, 0, 0, 0, tzinfo=Timezone('Europe/Paris'))
>>> dt - three_days
DateTime(2013, 3, 29, 23, 0, 0, tzinfo=Timezone('Europe/Paris'))
>>> dt + -three_days
DateTime(2013, 3, 30, 0, 0, 0, tzinfo=Timezone('Europe/Paris'))
```

A fix for the last case is proposed in
[pull request #987](https://github.com/python-pendulum/pendulum/pull/987).

(pendulum-intervals)=

#### Intervals disagree with themselves

Subtracting two datetimes gives an `Interval`, which adds a second
representation on top of `Duration`'s: it stores the elapsed seconds *and*,
separately, a calendar decomposition (years, months, days, hours, and smaller
units) computed
from the wall-clock fields. When the two ends share a zone, that decomposition
ignores DST, so the two views disagree and the round trip fails:

```python
>>> s = pendulum.datetime(2024, 3, 30, 23, 30, tz="Europe/Paris")
>>> e = pendulum.datetime(2024, 3, 31, 3, 30, tz="Europe/Paris")   # 3 hours later
>>> iv = e - s
>>> iv.total_seconds(), iv.in_hours()
(10800.0, 3)
>>> iv.hours, iv.in_words()
(4, '4 hours')
>>> s + iv
DateTime(2024, 3, 31, 4, 30, 0, tzinfo=Timezone('Europe/Paris'))   # not e
```

Subtraction uses the decomposition *and* the total, so it double-counts
anything longer than a month:

```python
>>> s = pendulum.datetime(2020, 1, 1)
>>> e = pendulum.datetime(2024, 6, 1)
>>> s + (e - s) == e
True
>>> e - (e - s)
DateTime(2015, 8, 2, 0, 0, 0, tzinfo=Timezone('UTC'))   # expected 2020-01-01
```

(pendulum-interval-equality)=

An `Interval`'s equality semantics don't form a valid equivalence relation,
and equal objects can hash differently — a defect the base `timedelta`
doesn't have:

```python
>>> jan = pendulum.interval(pendulum.datetime(2024, 1, 1), pendulum.datetime(2024, 1, 2))
>>> feb = pendulum.interval(pendulum.datetime(2024, 2, 1), pendulum.datetime(2024, 2, 2))
>>> one_day = pendulum.duration(days=1)
>>> jan == one_day, one_day == feb, jan == feb
(True, True, False)
>>> hash(jan) == hash(one_day), len({jan, one_day})
(False, 2)
```

That combination violates Python's contract for hashable objects and can
produce incorrect behavior in dictionaries, sets, caches, and deduplication
code.

All of the above has one cause: an `Interval` stores two answers to one
question and consults them inconsistently. Its smaller oddities are
cataloged {ref}`with the other bugs <pendulum-bugs>`.

:::{admonition} How `whenever` does it
:class: tip

In `whenever` the unit decides, not the call: `hours` is always exact elapsed
time and `days` is always calendar, whichever other units appear alongside
them, and `-`, `subtract()` and adding a negated delta all take the same path.
{ref}`Deltas <guide-deltas>` keep their calendar and exact parts separately
rather than collapsing one into the other, so units survive arithmetic,
copying and pickling.
:::

(pendulum-decision-parse)=

### Complete the input rather than reject it

> If you pass a non-standard or more complicated string, it will raise an
> exception, so it is advised to use the `from_format()` helper instead.
>
> — [Pendulum's documentation](https://pendulum.eustace.io/docs/#parsing)

(pendulum-parse-now)=

When a string is *incomplete*, Pendulum's `parse()` doesn't refuse it. Even
when passing `strict=True`.
Instead, it supplies the missing fields from the clock.
A time-only string becomes a datetime on *today's* date.
"Today" is read off the machine's local clock, while the result is stamped UTC,
and any offset in the input is discarded.
On a machine in UTC+12, you'll get *tomorrow's* UTC date about half of the time.

```python
>>> pendulum.parse("12:34:56")
DateTime(2026, 8, 24, 12, 34, 56, tzinfo=Timezone('UTC'))
>>> pendulum.parse("12:34:56+05:00")     # offset dropped, too
DateTime(2026, 8, 24, 12, 34, 56, tzinfo=Timezone('UTC'))
>>> pendulum.today("UTC")
DateTime(2026, 8, 23, 0, 0, 0, tzinfo=Timezone('UTC'))
```

The date comes from the clock and the time zone
{ref}`from a guess <pendulum-utc-assumption>`, all while ignoring
the provided offset.
An implicit UTC assumption at least serves the people whose data is in UTC.
This combination serves nobody:
no program wants the local date, stamped UTC, with its offset thrown away.

The string `"now"` is special-cased (and undocumented):

```python
>>> pendulum.parse("now")
DateTime(2026, 8, 23, 14, 32, 19, 426001, tzinfo=Timezone('UTC'))
```
The result of parsing therefore depends on *when* and *where* you parse, not only on the
input. For user-controlled or externally supplied strings, that dependence is
a correctness and security concern.

:::{admonition} How `whenever` does it
:class: tip

[Parsing](guide/parsing.md) in `whenever` never consults the clock, and each
method parses one format into one type: a string that doesn't fully determine
that type is a `ValueError`.
:::

(pendulum-bugs)=

## Other notable bugs

This section highlights some of the more consequential defects in Pendulum. 
Fixing any of them takes no redesign and gives up no compatibility, 
but they have remained open, sometimes for years.

| | Issue | Open since | Proposed fix |
|---|---|---|---|
| `Timezone` and `FixedTimezone` are unhashable | [#1008](https://github.com/python-pendulum/pendulum/issues/1008) | Sep 2026 | [#1009](https://github.com/python-pendulum/pendulum/pull/1009) |
| Values carrying a non-Pendulum `tzinfo` are treated as naive | [#527](https://github.com/python-pendulum/pendulum/issues/527), [#646](https://github.com/python-pendulum/pendulum/issues/646) | Dec 2020 | — |
| `astimezone()` to a `dateutil` zone loses the timezone | [#820](https://github.com/python-pendulum/pendulum/issues/820) | Apr 2024 | [#1006](https://github.com/python-pendulum/pendulum/pull/1006) |
| A `dateutil` zone passed as `tz=` becomes `+00:00` | — | unreported | — |
| `Duration / timedelta`, `//`, `%`, and `divmod()` raise `AttributeError` | [#382](https://github.com/python-pendulum/pendulum/issues/382) | Jun 2019 | — |
| `//`, `%`, and `divmod()` ignore calendar units | [#799](https://github.com/python-pendulum/pendulum/issues/799) | Jan 2024 | — |
| Durations lose microseconds beyond ~136 years | [#332](https://github.com/python-pendulum/pendulum/issues/332) | Jan 2019 | [#1003](https://github.com/python-pendulum/pendulum/pull/1003) |
| `Time` arithmetic drops the zone and microseconds | [#362](https://github.com/python-pendulum/pendulum/issues/362), [#584](https://github.com/python-pendulum/pendulum/issues/584) | Apr 2019 | — |
| A naive value's `is_dst()` is `True` while its `dst()` is `None` | — | unreported | — |
| `is_future()` and `diff_for_humans()` raise `TypeError` on naive values | — | unreported | — |
| `Interval.in_days()` counts local calendar dates, not 24-hour periods | — | unreported | — |
| A negative `Interval` contains neither endpoint, yet `range()` iterates it | — | unreported | — |
| Pickling and `copy.copy` drop `fold` | [#908](https://github.com/python-pendulum/pendulum/issues/908) | Aug 2025 | [#909](https://github.com/python-pendulum/pendulum/pull/909) |
| `precise_diff` ignores the end's time of day | [#906](https://github.com/python-pendulum/pendulum/issues/906) | Aug 2025 | — |
| `precise_diff` month detection is not monotonic — 29 days is "1 month", 30 days is "4 weeks 2 days" | — | unreported | — |
| The two builds disagree on ISO 8601 durations | [#534](https://github.com/python-pendulum/pendulum/issues/534), [#833](https://github.com/python-pendulum/pendulum/issues/833) | Feb 2021 | [#993](https://github.com/python-pendulum/pendulum/pull/993), [#1005](https://github.com/python-pendulum/pendulum/pull/1005) |
| No parity tests between the two builds | [#907](https://github.com/python-pendulum/pendulum/issues/907) | Aug 2025 | — |
| `from_format(..., "X", tz=...)` returns the wrong instant | — | unreported | — |
| Out-of-range offsets parse, then fail on use | — | unreported | — |
| Offsets in time-only strings are silently discarded | — | unreported | — |
| Formatter tokens are recognized but not implemented | — | unreported | — |
| Locale data is wrong or missing in ~15 locales | — | unreported | [#1001](https://github.com/python-pendulum/pendulum/pull/1001) (for `zh`) |
| `TZ` is ignored on macOS | [#905](https://github.com/python-pendulum/pendulum/issues/905) | Jul 2025 | — |
| The classes declare no `__slots__` | — | unreported | — |
| `timezone(2)` means seconds, `datetime(tz=2)` means hours | — | unreported | — |
| No API reference | [#199](https://github.com/python-pendulum/pendulum/issues/199) | May 2018 | — |

(pendulum-parse-lenient)=

### Parsing accepts what it cannot represent

Guessing at missing input has a counterpart in what the parser lets through.
The parser doesn't reject out-of-range offsets; the resulting value
exists, prints, and fails on first use:

```python
>>> d = pendulum.parse("2024-01-01T10:00-99:00")
>>> d
DateTime(2024, 1, 1, 10, 0, 0, tzinfo=FixedTimezone(-356400, name="-99:00"))
>>> d.isoformat()
Traceback (most recent call last):
  ...
ValueError: offset must be a timedelta strictly between -timedelta(hours=24) and timedelta(hours=24), ...
```

### Format tokens and locale data are unreliable

The token formatter substitutes every letter that happens to be a token,
whether or not it was meant as one:

```python
>>> pendulum.datetime(2024, 1, 15).format("Today is dddd")
'To1ay i0 Monday'
```

(pendulum-time-arithmetic)=

### `Time` arithmetic can discard information

Pendulum exposes aware `Time` values, but its arithmetic converts through an
epoch datetime and returns only the clock fields. The timezone is silently
lost, subtraction drops microseconds
([#362](https://github.com/python-pendulum/pendulum/issues/362),
[#584](https://github.com/python-pendulum/pendulum/issues/584)),
and a negative `timedelta` is rejected because of `timedelta`'s own
normalization of days and seconds:

```python
>>> paris = pendulum.timezone("Europe/Paris")
>>> pendulum.Time(12, tzinfo=paris).add(hours=1)
Time(13, 0, 0)
>>> pendulum.Time(12, 0, 0, 900_000) - pendulum.Time(12, 0, 0, 100_000)
Duration()
>>> pendulum.time(12) + timedelta(hours=-1)
Traceback (most recent call last):
  ...
TypeError: Cannot add timedelta with days to Time.
```

### Durations lose precision past a century

The internal representation is a `float` of total seconds, so microseconds are
lost for spans beyond roughly 136 years, even though `==` still says the values
are equal ([#332](https://github.com/python-pendulum/pendulum/issues/332), open
since 2019):

```python
>>> pendulum.duration(days=100000, microseconds=1).microseconds
2
>>> pendulum.datetime(1, 1, 1) + (pendulum.DateTime.max - pendulum.DateTime.min)
DateTime(9999, 12, 31, 23, 59, 0, tzinfo=Timezone('UTC'))    # 59.999999 s short
```

(pendulum-foreign-tzinfo)=

### Timezones Pendulum didn't create

Pendulum's methods work through `DateTime.tz`, which is `None` for any
`tzinfo` that isn't Pendulum's own. Such values are easy to come by:
`astimezone()` with no argument or with a `ZoneInfo`, `replace(tzinfo=...)`,
or the constructor. Pendulum's methods then treat them as naive,
sometimes after shifting the fields to UTC:

```python
>>> from datetime import timezone, timedelta
>>> d = pendulum.DateTime(2024, 1, 1, 12, tzinfo=timezone(timedelta(hours=5)))
>>> d.add(hours=1)
DateTime(2024, 1, 1, 8, 0, 0)                  # naive; 13:00+05:00 expected
>>> import copy
>>> copy.deepcopy(pendulum.now("UTC").astimezone(ZoneInfo("Europe/Paris"))).tzinfo is None
True
```

Pendulum quietly turns a `dateutil` zone passed as `tz=` into a fixed offset
or UTC:

```python
>>> pendulum.datetime(2024, 7, 1, 12, tz=tz.gettz("Europe/Paris"))
DateTime(2024, 7, 1, 12, 0, 0, tzinfo=FixedTimezone(0, name="+00:00"))
```

The `tz` parameter is lenient in one further direction: it reads a bare number
as *hours*, while `pendulum.timezone()` reads the same number as *seconds*:

```python
>>> pendulum.datetime(2024, 1, 1, tz=2)
DateTime(2024, 1, 1, 0, 0, 0, tzinfo=FixedTimezone(7200, name="+02:00"))
>>> pendulum.timezone(2)
FixedTimezone(2, name="+00:00")                # two seconds; name truncated
```

### Equality contracts Pendulum breaks on its own types

Where Pendulum defines equality for its own types, it breaks contracts
the standard library keeps: `timedelta`'s equality is a sound equivalence
relation, while `Interval`'s is not
({ref}`shown above <pendulum-interval-equality>`); `zoneinfo.ZoneInfo` is
hashable, while Pendulum's subclass of it is not. `Timezone` and
`FixedTimezone` define `__eq__` but not `__hash__` — in Python, that
combination makes a class unhashable:

```python
>>> hash(pendulum.UTC)
Traceback (most recent call last):
  ...
TypeError: unhashable type: 'Timezone'
>>> {pendulum.timezone("Europe/Paris")}
Traceback (most recent call last):
  ...
TypeError: cannot use 'pendulum.tz.timezone.Timezone' as a set element (unhashable type: 'Timezone')
```

Timezones as dictionary keys, set members, or `lru_cache` arguments are routine;
none of that works.

(pendulum-serialization)=

### Serialization can change the instant

Pickling doesn't preserve `fold`. Serializing a datetime in the second
occurrence of a repeated hour and reading it back can therefore change its
timestamp:

```python
>>> original = pendulum.datetime(2024, 11, 3, 1, tz="America/Chicago", fold=1)
>>> restored = pickle.loads(pickle.dumps(original))
>>> original.fold, restored.fold
(1, 0)
>>> original.timestamp() == restored.timestamp()
False
```

(pendulum-slots)=

### The classes carry a `__dict__`

None of Pendulum's classes declares `__slots__`, so every instance carries a
dictionary the standard library's doesn't. A `DateTime` accepts
a mistyped attribute in silence:

```python
>>> d = pendulum.datetime(2024, 1, 1)
>>> d.yeaar = 3000        # no error
>>> d.__dict__
{'yeaar': 3000}
```

(pendulum-global-state)=

### Global settings change behavior at a distance

Locale, week start, and the local timezone are process-wide settings, so the
result of a call depends on state the call doesn't mention — set by an
unrelated part of the program, or by a library it happens to import.

- `week_starts_at()` and `week_ends_at()` are independent; setting only the
  first gives one-day and eight-day weeks (`pendulum.week_starts_at(SUNDAY)`;
  a Sunday's `start_of("week")` and `end_of("week")` are both itself), and
  `week_of_month` and `week_of_year` ignore the setting.
- `first_of("month", pendulum.MONDAY)` returns January 7 instead of January 1
  after the *standard library's* `calendar.setfirstweekday(calendar.SUNDAY)`.
- `set_locale()` is process-global and, as shown below, reaches the RFC
  formats.

(pendulum-formatting)=

### The global locale reaches formats that mandate English

The formatter and its locale data are one of Pendulum's attractions, and they
mostly work. But they are also where the global locale does the most damage:
the standard formats follow it, although RFC 2822 and friends mandate
English.

```python
>>> pendulum.set_locale("fr")
>>> pendulum.datetime(2024, 1, 15, 12).to_rfc2822_string()
'lun., 15 janv. 2024 12:00:00 +0000'
>>> pendulum.datetime(2024, 1, 15, 12).to_cookie_string()    # only this one is pinned
'Monday, 15-Jan-2024 12:00:00 UTC'
```

(pendulum-two-impls)=

### Two implementations that disagree

Pendulum ships a Rust extension and a pure-Python fallback
(`PENDULUM_EXTENSIONS=0`). Offering both is a good idea (`whenever` does the
same) but only if they agree. The project lacks systematic parity tests
between them, as acknowledged in
[#907](https://github.com/python-pendulum/pendulum/issues/907), and they
diverge in both parsing and arithmetic.

The compiled `precise_diff` checks the *exact* type of its second argument,
so when an `Interval`'s end was a standard-library datetime (which Pendulum
wraps in a subclass), the diff treats the end's time of day as midnight:

```python
>>> a = pendulum.datetime(2024, 1, 1)
>>> b = datetime(2024, 1, 1, 5, 30, tzinfo=timezone.utc)
>>> a.diff(b).in_seconds(), a.diff(b).hours, a.diff(b).in_words()
(19800, 0, '0 microseconds')
>>> a.diff_for_humans(b)
'a few seconds before'
>>> pendulum.interval(datetime(2025, 7, 25, 19, 26, 34),
...                   datetime(2025, 7, 29, 19, 26, 34)).in_words()
'3 days 4 hours 33 minutes'
```

The pure-Python build answers `5 hours 30 minutes` and `'4 days'`.
That bug is [#906](https://github.com/python-pendulum/pendulum/issues/906),
and the offending check is still on `master`.

The two parsers can't agree on valid and invalid input. On the compiled
build `PT4294967297M` overflows to `Duration(minutes=1)`, `P12M4M` and
`PT1H1H` are accepted, `P4294967296D` is `Duration()`, fractional durations are
rounded to whole minutes (`P0.001D` → `Duration(minutes=1)`), and
`T12:30:00` is rejected. The pure-Python parser preserves all
4,294,967,297 minutes and rejects the duplicates, but interprets every
fractional component as tenths regardless of the number of digits
([#534](https://github.com/python-pendulum/pendulum/issues/534), open since 2021)
and accepts near-anything as ISO 8601:

```python
# Compiled parser                     # Pure-Python parser
>>> pendulum.parse("P1.25D")          >>> pendulum.parse("P1.25D")
Duration(days=1, hours=6)             Duration(days=3, hours=12)
>>> pendulum.parse("PT1.25H")         >>> pendulum.parse("PT1.25H")
Duration(hours=1, minutes=15)         Duration(hours=3, minutes=30)
>>> pendulum.parse("202401")          >>> pendulum.parse("202401")
ParserError                           DateTime(2026, 8, 23, 20, 24, 1, tzinfo=Timezone('UTC'))
```

(pendulum-project)=

## The state of the project

The problems on this page come in two kinds, and neither is going away.
The design decisions would take a breaking redesign.
The bugs would take scarce maintainer time.

### The documentation is outdated and incomplete

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
- the `from_format` escaping example (`"[today] dddd"`) raises;
- the introduction claims comparisons account for time zones; the
  repeated-hour example above shows otherwise.

### Maintenance remains a concern

Pendulum's original author wrote nearly all of the library. Its last major
release, 3.0 (December 2023), broke compatibility: it renamed the `Period`
class, removed the transition-rule API, and replaced the C extension with a
Rust one. Development slowed after that release. Since 2025 the project lives under the `python-pendulum`
organization. Its new maintainers picked up a codebase they didn't write,
and have kept it going: 3.1 shipped in April 2025 and 3.2 in January 2026.

They are hamstrung, through no fault of their own.
Most of what this page describes follows from the
design decisions listed at the top, which cannot be changed without breaking
the "drop-in replacement" promise that is Pendulum's main selling point.
None of those decisions were theirs.
Meanwhile the backlog grows: reproducible correctness issues remain open across releases,
including cases where a tested fix is already available
([#909](https://github.com/python-pendulum/pendulum/pull/909),
[#968](https://github.com/python-pendulum/pendulum/pull/968),
[#975](https://github.com/python-pendulum/pendulum/pull/975),
[#985](https://github.com/python-pendulum/pendulum/pull/985),
[#987](https://github.com/python-pendulum/pendulum/pull/987)).

## In short

Pendulum's problems follow from its design.
A subclass can't fix `datetime` and stay a drop-in replacement.
And guessing (at the caller's intent, at missing timezones, at incomplete input)
can't be patched into correctness.
Reversing any of these decisions would break the code that depends on them.

`whenever` makes the opposite trade: there's no drop-in path,
and you have to decide what each value in your program actually is.
In exchange, nothing is guessed.

[^versions]: This page is up to date as of Pendulum 3.2.0. Every example was
    run against that version on CPython 3.14, unless stated otherwise.
