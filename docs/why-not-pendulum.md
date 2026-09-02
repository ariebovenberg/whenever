---
myst:
  html_meta:
    description: >-
      A detailed comparison with Pendulum: what it improves over the standard
      library, why an API cannot be fixed by subclassing it, and how four
      further design decisions — treat naive datetimes as a mistake, redefine
      fold, put months inside timedelta, and complete the input rather than
      reject it — produce failures in equality, arithmetic, DST handling and
      parsing that cannot be patched out.
---

# Why not Pendulum?

[**Pendulum**](https://pypi.org/project/pendulum/) arrived in 2016 with
several improvements over the standard library: a fluent API, a
`moment.js`-style formatter, localized `diff_for_humans()`, a `Duration` free
of the {ref}`timedelta.seconds footgun <timedelta-seconds>`, and the
main attraction: arithmetic that knows about DST.
All this delivered as a drop-in replacement:
Pendulum's classes subclass the standard library's, so existing code keeps working.

The catch: those fixes introduce bugs of their own, and the worst of them are
not accidents of implementation. They follow from a handful of decisions the
rest of the library is built on. The biggest of them is the delivery
mechanism itself. Each looks sound until it has to hold in every case, and none can be
reversed without breaking the code built on top.[^versions]

```{admonition} Pendulum 3.2.0 at a glance
:class: caution

A sample of behaviour you can reproduce today, each linked to the section
that explains it:

- [`today("Africa/Cairo")` is **yesterday**](#pendulum-today-yesterday), for
  one whole day each year.
- [`parse("12:00")` is today's date on the *local* clock, stamped
  *UTC*](#pendulum-parse-now) — and `parse("now")` is the current time.
- [`dt + timedelta` runs ~400× slower than the standard
  library](#pendulum-performance) — a system call per addition.
- [A 3-hour interval reports `.hours == 4`](#pendulum-intervals) and
  `in_words() == '4 hours'`.
- [Neither round trip holds](#pendulum-intervals): `start + (end - start)` is
  not `end` across a DST transition, and `end - (end - start)` is not `start`
  for a month or more.
- [`instance(a_datetime)` can move the instant by an
  hour](#pendulum-gap-fold).
```

(pendulum-decision-dropin)=

## An API can't be fixed by subclassing it

> It provides classes that are drop-in replacements for the native ones (they
> inherit from them).
>
> — [Pendulum's documentation](https://pendulum.eustace.io/docs/#introduction)

Drop-in compatibility is Pendulum's main selling point, and subclassing is
how it is delivered. Subclassing is also a well-worn trap. A subclass is free
to *add* behavior. But the moment it *changes* what an inherited operation
means, it revises a contract it does not own: every piece of code ever
written against the base class now receives the subclass while still assuming
the base. That
contract has a name, the
[Liskov substitution principle](https://en.wikipedia.org/wiki/Liskov_substitution_principle):
code written for the base type must keep working, unchanged, with any
subclass of it. Violating it always appears to work at first, because at
first the only callers are your own.

Pendulum walked straight in, because its main attraction, arithmetic that
knows about DST, is precisely a change to what an inherited operation means.
Fixed, or drop-in: a subclass of `datetime` must pick one, and Pendulum's
`__add__` is what refusing to pick looks like. This is the code that runs on
every `dt + timedelta`:

```python
# pendulum/datetime.py
def __add__(self, other):
    ...
    caller = traceback.extract_stack(limit=2)[0].name
    if caller == "astimezone":
        return super().__add__(other)
    return self._add_timedelta_(other)
```

It walks the call stack and picks between two kinds of arithmetic based on
the *name of the function that called it*. Name a function of your own
`astimezone`, and `+` changes meaning inside it:

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

This is not a slip that code review should have caught. It is the least bad
move left inside the corner. The rest of this section traces how it was
forced, what it breaks, and what it costs.

(pendulum-add-stack)=

### Addition inspects the call stack

During a timezone conversion, the standard library's machinery
(`ZoneInfo.fromutc()`) quite reasonably calls `+` on whatever datetime it was
handed, expecting `datetime` semantics. On a Pendulum subclass, that
dispatches to Pendulum's redefined `+`, which would misinterpret the
UTC-valued intermediate. Pendulum cannot restructure the conversion (it
belongs to the standard library), cannot un-redefine `+` (that is the main
attraction), and cannot stop being a subclass (that is the selling point).
What is left is guessing, at runtime, whose semantics the caller expects —
from the caller's name. That is why `dt + timedelta` in *your* code depends
on what your function happens to be called.

And the guess only covers the one caller it names. Any other `tzinfo` whose
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
caller whose expectations have to be guessed. And the guessing is not free: it
runs on every `+`, every `astimezone()` and every `in_tz()`, touching the
filesystem each time (see {ref}`performance <pendulum-performance>`).

(pendulum-substitutable)=

### It is not substitutable

Subclassing buys exactly one thing: a Pendulum value can be passed wherever a
`datetime` is expected. It is worth asking what that is worth.

Some code refuses the value outright. `sqlite3` binds a `datetime` and rejects
its subclass:

```python
>>> con.execute("select ?", (datetime(2024, 1, 1),)).fetchone()
('2024-01-01 00:00:00',)
>>> con.execute("select ?", (pendulum.datetime(2024, 1, 1),)).fetchone()
Traceback (most recent call last):
  ...
ProgrammingError: Error binding parameter 1: type 'DateTime' is not supported
```

Pendulum's documentation
[lists this](https://pendulum.eustace.io/docs/#limitations) alongside
`mysqlclient`, `PyMySQL` and Django, and attributes it to those libraries
checking `type()` rather than `isinstance()`. That is accurate, and it is not
going to change: dispatching on the exact type is ordinary practice, and no
subclass can stop other people's code from doing it. Pendulum's own Rust
extension does it too: `precise_diff` checks the exact type of its second
argument, which is
[#906](https://github.com/python-pendulum/pendulum/issues/906).

The rest of the ecosystem accepts the value and computes something else with
it. A helper written against the standard library adds a day the standard
library's way; handed a Pendulum value, the same expression lands on a
different instant:

```python
>>> def add_a_day(dt):
...     return dt + timedelta(days=1)
>>> paris = ZoneInfo("Europe/Paris")      # clocks go forward that night
>>> add_a_day(datetime(2024, 3, 30, 12, tzinfo=paris))
datetime.datetime(2024, 3, 31, 12, 0, tzinfo=zoneinfo.ZoneInfo(key='Europe/Paris'))
>>> add_a_day(pendulum.datetime(2024, 3, 30, 12, tz="Europe/Paris"))
DateTime(2024, 3, 31, 13, 0, 0, tzinfo=Timezone('Europe/Paris'))
```

Twenty-three hours in one case, twenty-four in the other. Neither answer is
wrong on its own terms: the standard library adds to the wall clock, Pendulum
adds elapsed time. But only one of them is what the helper was written to do,
and nothing in its signature says which it will get. The type annotation reads
`datetime`; so does `isinstance`.

That is the shape of the whole decision. "Drop-in replacement" promises that a
value behaves like a `datetime`; what subclassing delivers is that it passes
for one. The gap between those two is not a list of cases that could be
closed one by one, because it is not Pendulum's list. It belongs to every
library that will ever receive one of these values. Closing it means not
subclassing.

(pendulum-performance)=

### Every addition pays for the guess

The decision also has a price in plain microseconds. Pendulum initially
promised [improved performance](https://pendulum.eustace.io/faq/), but
version 3 is markedly slower than both version 2 and the standard library:
roughly 400× on `+`, 60× on a timezone conversion. Two causes explain most
of the regression reported in
[#818](https://github.com/python-pendulum/pendulum/issues/818), and both are
this decision showing up on the clock:

1. The hack in `__add__`. `ZoneInfo.fromutc()` calls
   `+`, so every `astimezone()`, `in_tz()` and `+` walks the stack, and
   `traceback` then consults `linecache`, which `stat()`s the source file.
   That is a system call per datetime addition.
2. `pendulum.Timezone` subclasses `ZoneInfo`, and `zoneinfo`'s strong cache
   only serves the exact base type. When no `Timezone("Europe/Paris")` object
   is alive, the next `tz="Europe/Paris"` re-reads and re-parses the tzdata
   file.

| operation | Pendulum 3.2 | standard library |
|---|---|---|
| `dt + timedelta(hours=1)` | 37 µs | 0.09 µs |
| `dt.add(hours=1)` | 7 µs | — |
| `dt - dt` | 13 µs | 0.05 µs |
| `dt.in_tz(tz)` / `astimezone(tz)` | 23 µs | 0.4 µs |
| `pendulum.timezone("Europe/Paris")`, unreferenced | 107 µs | `ZoneInfo(...)`: 0.12 µs |

Correctness and predictable semantics should come first when choosing a
datetime library, and a few times the standard library's cost would be a
non-issue. Two orders of magnitude is a different category: at ~40 µs and a
system call per addition, a million datetime operations cost about forty
seconds of pure overhead (versus a tenth of a second for the standard
library), and datetime handling starts showing up in profiles of data
pipelines and schedulers as a cost of its own. In
{ref}`benchmarks <benchmarks>`, Pendulum is routinely one to two orders of
magnitude slower than the standard library and `whenever`.

(pendulum-v2-v3)=

### Version 2 dodged the corner — version 3 couldn't

The collision is as old as the design; what changed in version 3 is how
Pendulum pays for it. Version 2 never touched the standard library's
conversion machinery: its `Timezone` was a from-scratch `tzinfo` with its own
compiled transition database (shipped separately as
[`pytzdata`](https://pypi.org/project/pytzdata/)) and its own `fromutc()`,
which worked on integer timestamps and never called `+`. With the whole
pipeline in-house, none of Pendulum's own code ever invoked the redefined `+`
expecting standard-library semantics. Foreign timezones already fell into the
crack: `astimezone()` to a `dateutil` zone raised `AttributeError`
([#527](https://github.com/python-pendulum/pendulum/issues/527),
[#646](https://github.com/python-pendulum/pendulum/issues/646)). But the
default path held. The price was maintaining a parallel timezone stack, with
a package release every time IANA updated a zone.

Once PEP 615 put `zoneinfo` in the standard library, that burden looked
pointless, and version 3.0 reasonably shed it: `Timezone` became a `ZoneInfo`
subclass, the custom machinery was deleted, and the standard library's
conversion code, which calls `+`, entered the path of every conversion.
The hack appears in the very same release. (Overriding
`fromutc()` with timestamp math instead would have meant rewriting exactly
the transition code 3.0 had just deleted, and third-party timezones would
still be exposed.)

Version 3 knows whose semantics it needs, too, wherever it controls the
calling code: its fixed-offset `fromutc()` sidesteps the operator entirely,
calling `datetime.__add__` directly, with the comment "Use the stdlib
datetime's add method to avoid infinite recursion". The guess is only for
the callers it doesn't control.

:::{admonition} How `whenever` does it
:class: tip

`whenever`'s types don't subclass anything, so they inherit no contract that
then has to be patched around. `+` means one thing, and no third-party code
can be holding a `whenever` value while expecting `datetime` semantics from
it. The cost is real and worth stating: there is no drop-in path, and
[converting to and from the standard library](guide/stdlib-convert.md) is an
explicit step.
:::

## Four more decisions that cannot be fixed

Subclassing is the biggest decision Pendulum is built on, but not the only
one. Four more run just as deep — none can be removed by a bug fix, since
reversing any of them changes what existing code computes. In the two most
damaging cases it would change it silently, because the values involved stay
valid datetimes and nothing raises. That is a hard thing to ask of a library
whose selling point is that you can drop it in.

- **{ref}`Treat naive datetimes as a mistake to be corrected <pendulum-decision-naive>`** —
  rather than as a distinct kind of value.
- **{ref}`Redefine fold rather than adopt it <pendulum-decision-fold>`** —
  with a different default, and the opposite meaning in a gap.
- **{ref}`Put months and years inside a timedelta <pendulum-decision-months>`** —
  beside a fixed number of seconds.
- **{ref}`Complete the input rather than reject it <pendulum-decision-parse>`** —
  filling what is missing from the clock and the machine's time zone.

There are also more plain bugs than a library of this scope would suggest,
many of them reported years ago and still without a maintainer's reply; those
are {ref}`documented separately <pendulum-bugs>`, after the decisions.

(pendulum-decision-naive)=

### Treat naive datetimes as a mistake to be corrected

> Pendulum enforces timezone aware datetimes, and using them is the preferred
> and recommended way of using the library.
>
> — [Pendulum's documentation](https://pendulum.eustace.io/docs/#instantiation)

The instinct is sound: naive datetimes really are a common source of bugs.
But Pendulum treats them as an error to be corrected rather than a value with
its own meaning, and neither half of that works out. The correcting is done by
guessing: a missing zone becomes UTC. The enforcing does not happen at
all: `pendulum.DateTime(2020, 1, 1)` is naive, `pendulum.naive()` is a
documented helper, and naive values keep every meaning the standard library
gave them, plus one more.

(pendulum-utc-assumption)=

#### Missing timezone information becomes UTC

If a naive result is unacceptable, then something has to be supplied wherever
the input doesn't carry a zone. Pendulum's conversion entry points supply UTC:

```python
>>> pendulum.parse("2024-03-10T15:00")
DateTime(2024, 3, 10, 15, 0, 0, tzinfo=Timezone('UTC'))
>>> pendulum.instance(datetime(2024, 3, 10, 15))
DateTime(2024, 3, 10, 15, 0, 0, tzinfo=Timezone('UTC'))
```

An ISO 8601 datetime without an offset does not identify an instant.
It only supplies local date and time fields.
Treating it as UTC invents information that was absent from the input.
If the source intended another time zone, this silently shifts the
resulting instant by several hours — the original bug, now with a
plausible-looking value where the error should have been.

And the policy is only skin-deep. It is not enforced at construction:

```python
>>> pendulum.datetime(2020, 1, 1)
DateTime(2020, 1, 1, 0, 0, 0, tzinfo=Timezone('UTC'))
>>> pendulum.DateTime(2020, 1, 1)
DateTime(2020, 1, 1, 0, 0, 0)
```

and the entry points that do convert disagree about what a missing zone
means:

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
one — `parse()`, `instance()` and `strptime()` all mint naive-means-UTC
into their results — and adds a fourth of its own: `in_timezone()` reads a
naive value as "already in whatever zone you name". With the system zone set
to `America/New_York`:

```python
>>> n = pendulum.naive(2024, 1, 1)
>>> n.timestamp()                          # inherited: system local time
1704085200.0
>>> n.in_tz("UTC")                         # new: "it is already UTC"
DateTime(2024, 1, 1, 0, 0, 0, tzinfo=Timezone('UTC'))
>>> n.in_tz("Europe/Paris")                # new: "it is already Paris" — another instant
DateTime(2024, 1, 1, 0, 0, 0, tzinfo=Timezone('Europe/Paris'))
>>> n.astimezone(pendulum.UTC)             # inherited: local → UTC
DateTime(2024, 1, 1, 5, 0, 0, tzinfo=Timezone('UTC'))
>>> pendulum.instance(datetime(2024, 1, 1))   # doubled-down: it is UTC
DateTime(2024, 1, 1, 0, 0, 0, tzinfo=Timezone('UTC'))
```

Which reading applies is decided per method, not per value: the same `n`
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
{meth}`~whenever.PlainDateTime.assume_utc` or
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

`fold` (PEP 495) is the standard library's one-bit answer to ambiguous local
times, and Pendulum inherits the bit without inheriting the convention: it
defaults the bit the other way, gives it the opposite meaning in a gap, and
preserves or drops it depending on the operation. Any one of those is
arguable on its own. Together they mean the bit no longer says what it says
everywhere else, while still travelling on values that cross library
boundaries. The first two sections below are premises; the rest is what they
add up to.

(pendulum-fold-default)=

#### The default disambiguation differs from the common convention

Pendulum defaults to `fold=1`, selecting the offset *after* a backwards
transition. Python's standard library and the convention used by most datetime
libraries default to the offset before the transition; see
{ref}`the discussion of ambiguity defaults <ambiguity-default>`.
Pendulum allows callers to choose a `fold`, and
`raise_on_unknown_times=True` can reject ambiguous or nonexistent local times.
The default is significant: moving code from `datetime` to Pendulum can change
which instant an ambiguous local time represents unless the fold is chosen
explicitly.

(pendulum-gap-fold)=

#### For skipped times, `fold` means the opposite of what it means in PEP 495

For a nonexistent local time, Pendulum shifts *backward* when `fold=0` and
*forward* when `fold=1`. `zoneinfo` resolves `fold=0` with the pre-transition
offset, which corresponds to the *later* wall time. Since `instance()` copies
the standard library's `fold` (usually 0) while `pendulum.datetime()` defaults
to 1, the two entry points disagree, and converting an aware standard-library
value can move it by an hour:

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

`replace()` resolves nonexistent times the same way (the standard library
leaves them alone), so `dt.replace(hour=2)` can return 03:30 or 01:30
depending on the value's `fold`.

(pendulum-today-yesterday)=

#### `today()` can be yesterday

Put the two preceding sections together and a value's `fold` starts to matter
in places nobody chose it. The bit is not only a creation-time option:
`set()`, `at()`, `on()`, `start_of()`, `end_of()`, `first_of()` and
`replace()` all re-resolve the new wall time using the *existing* value's
`fold`. And which `fold` a value carries depends on where it came from:
literals get the `fold=1` default, while `now()` and anything that has been
through a gap carry `fold=0` — which, as just shown, resolves a nonexistent
time *backwards*. In a zone whose DST starts at midnight — Egypt, Chile,
Cuba, Lebanon and the Azores all do, every year — that combination makes
`today()` resolve midnight backwards into the previous day:

```python
>>> with pendulum.travel_to(pendulum.datetime(2025, 4, 25, 12, tz="Africa/Cairo"), freeze=True):
...     pendulum.now("Africa/Cairo")
...     pendulum.today("Africa/Cairo")
...     pendulum.tomorrow("Africa/Cairo")
...     pendulum.datetime(2025, 4, 25, 12, tz="Africa/Cairo").start_of("day")
DateTime(2025, 4, 25, 12, 0, 0, tzinfo=Timezone('Africa/Cairo'))
DateTime(2025, 4, 24, 23, 0, 0, tzinfo=Timezone('Africa/Cairo'))
DateTime(2025, 4, 25, 23, 0, 0, tzinfo=Timezone('Africa/Cairo'))
DateTime(2025, 4, 25, 1, 0, 0, tzinfo=Timezone('Africa/Cairo'))
```

The same wall time in the same zone gives a different answer depending on
where the value came from. A corner of this is reported in
[#915](https://github.com/python-pendulum/pendulum/issues/915).

(pendulum-equality)=

#### Equality and ordering contradict chronology

`datetime`'s comparison rules leak through unchanged. During a repeated hour,
two different instants compare equal, and a value is not equal to itself
converted to UTC:

```python
>>> import pendulum
>>> f0 = pendulum.datetime(2023, 11, 5, 1, 25, tz="America/Los_Angeles", fold=0)
>>> f1 = f0.replace(fold=1)
>>> f0 == f1, f0.timestamp() == f1.timestamp()
(True, False)
>>> f0 == f0.in_tz("UTC")
False
>>> f0 in {f0.in_tz("UTC")}
False
```

`repr()` omits `fold`, so `f0` and `f1` also print identically.

Ordering contradicts chronology in the same situation:

```python
>>> later = pendulum.datetime(2023, 11, 5, 1, 15, tz="America/Los_Angeles", fold=1)
>>> earlier = pendulum.datetime(2023, 11, 5, 1, 25, tz="America/Los_Angeles", fold=0)
>>> later.timestamp() > earlier.timestamp()
True
>>> later < earlier
True
```

This contradicts Pendulum's documentation, which says comparisons account for
time zones. First reported in
[#351](https://github.com/python-pendulum/pendulum/issues/351);
a fix is currently proposed in
[#985](https://github.com/python-pendulum/pendulum/pull/985).

It would be wrong to file this under "inherited from `datetime`" and move on.
PEP 495 chose these semantics deliberately, sacrificing inter-zone equality
of ambiguous times to keep hashing and ordering self-consistent, and
documents the trade-off. Pendulum inherits the edge cases, *documents the
opposite*, and hides the state that triggers them, as shown above.

:::{admonition} How `whenever` does it
:class: tip

Ambiguity in `whenever` is settled by an explicit
{ref}`disambiguate <ambiguity>` argument on the operation that creates the
value, defaulting to `"compatible"` — the same convention as RFC 5545,
Temporal, NodaTime and the standard library's `fold=0` — with `"raise"`
available when you would rather be told than guessed at. The resolved offset
is part of the value, so copying, pickling and converting it preserve the
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
Pendulum makes for you, from context. The two halves interact, and this is
where round trips stop working.

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

Operators Pendulum does not override fall back to `timedelta`'s and return
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
as does floor division, modulo, and `divmod()`
([#382](https://github.com/python-pendulum/pendulum/issues/382), since 2019;
months are ignored by these operators altogether,
[#799](https://github.com/python-pendulum/pendulum/issues/799)).

(pendulum-implicit-arithmetic)=

#### Calendar and exact arithmetic are chosen implicitly

Pendulum's named `add()` and `subtract()` methods are a useful
improvement over `datetime`. They distinguish calendar days from elapsed
hours and handle many DST transitions conveniently. Calendar arithmetic is
inherently non-associative — `Jan 31 + 1 month + 1 month` is not
`Jan 31 + 2 months` in any library — and that is not the complaint here.
The complaint is that Pendulum decides *which kind* of arithmetic to apply
based on incidental details: which other units appear in the same call, and
whether you wrote `+` or `-`.

If any calendar unit is present in an `add()` call, *all* units — including
hours — are applied to the wall clock:

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
separately, a calendar decomposition (years, months, days, hours, …) computed
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

In autumn the mirror image occurs: five elapsed hours are `'4 hours'`, and
`diff_for_humans()` says `'4 hours after'`. With `fold` involved it gets
stranger still: an interval of exactly one elapsed hour between the two
occurrences of 01:25 reports `total_seconds() == 3600.0`, `hours == 0` and
`in_words() == '0 microseconds'`.

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

Its equality semantics do not form a valid equivalence relation, and equal
objects can hash differently — a defect the base `timedelta` does not have:

```python
>>> jan = pendulum.interval(pendulum.datetime(2024, 1, 1), pendulum.datetime(2024, 1, 2))
>>> feb = pendulum.interval(pendulum.datetime(2024, 2, 1), pendulum.datetime(2024, 2, 2))
>>> one_day = pendulum.duration(days=1)
>>> jan == one_day, one_day == feb, jan == feb
(True, True, False)
>>> hash(jan) == hash(one_day), len({jan, one_day})
(False, 2)
```

This violates Python's contract for hashable objects and can produce incorrect
behavior in dictionaries, sets, caches, and deduplication code.

All of the above has one root: an `Interval` stores two answers to one
question and consults them inconsistently. Its smaller oddities are
catalogued {ref}`with the other bugs <pendulum-bugs>`.

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

Pendulum documents its parser as strict, and reserves fuzzy parsing for an
opt-in `strict=False`. The instinct behind the leniency is easy to place:
Pendulum comes from the `moment.js` school, where filling in whatever the
caller omitted was the height of ergonomics — and at a REPL, with a human
mid-sentence, it genuinely is. The trouble starts when the input is data.
In practice the default parser refuses far less than the word "strict"
suggests.

(pendulum-parse-now)=

`parse()` accepts several unrelated kinds of input, and may return a
`DateTime`, a `Duration` or an `Interval` depending on the string. More
consequential is what it does when a string is *incomplete*: rather than
refusing it, `parse()` supplies the missing fields from the wall clock.
A time-only string becomes a datetime on *today's* date. And "today" is read
off the machine's local clock, while the result is stamped UTC and any offset
in the input is discarded. On a machine in UTC+14, where it is already
August 24 local time but still August 23 in UTC:

```python
>>> pendulum.parse("12:34:56")
DateTime(2026, 8, 24, 12, 34, 56, tzinfo=Timezone('UTC'))
>>> pendulum.parse("12:34:56+05:00")     # offset dropped, too
DateTime(2026, 8, 24, 12, 34, 56, tzinfo=Timezone('UTC'))
>>> pendulum.today("UTC")
DateTime(2026, 8, 23, 0, 0, 0, tzinfo=Timezone('UTC'))
```

The date comes from one clock, the zone from
{ref}`a policy <pendulum-utc-assumption>`, and the offset from nowhere: even
taking the filled-in date for granted, the result is internally inconsistent.
Only `exact=True` returns a `Time`.
The string `"now"` is special-cased (and undocumented):

```python
>>> pendulum.parse("now")
DateTime(2026, 8, 23, 14, 32, 19, 426001, tzinfo=Timezone('UTC'))
```

`from_format()` does the same for any token that isn't in the format. The
missing parts come from "now in the target zone":

```python
>>> pendulum.from_format("10:00", "HH:mm")
DateTime(2026, 8, 23, 10, 0, 0, tzinfo=Timezone('UTC'))
>>> pendulum.from_format("15", "DD")           # the 15th of the current month
DateTime(2026, 8, 15, 0, 0, 0, tzinfo=Timezone('UTC'))
```

The result of parsing therefore depends on *when* you parse, not only on the
input. For user-controlled or externally supplied strings this is a
correctness and security concern: the same payload produces a different
value tomorrow.

:::{admonition} How `whenever` does it
:class: tip

[Parsing](guide/parsing.md) in `whenever` never consults the clock, and each
method parses one format into one type: a string that does not fully determine
that type is a `ValueError`, not a value completed from today's date. What the
input does not say, the result does not claim.
:::

(pendulum-bugs)=

## The bugs that stay

The rest are ordinary defects. Fixing any of them takes no redesign and gives
up no compatibility, and for several a tested fix is already open. What
follows is a selection, not a survey.

| | Issue | Open since | Activity |
|---|---|---|---|
| `Timezone` and `FixedTimezone` are unhashable | — | unreported | — |
| Values carrying a non-Pendulum `tzinfo` are treated as naive | [#527](https://github.com/python-pendulum/pendulum/issues/527), [#646](https://github.com/python-pendulum/pendulum/issues/646) | Dec 2020 | 8 comments, no maintainer reply |
| A `dateutil` zone passed as `tz=` becomes `+00:00` | — | unreported | — |
| `Duration / timedelta`, `//`, `%` and `divmod()` raise `AttributeError` | [#382](https://github.com/python-pendulum/pendulum/issues/382) | Jun 2019 | 3 comments, no maintainer reply |
| Calendar units are ignored by `//`, `%` and `divmod()` | [#799](https://github.com/python-pendulum/pendulum/issues/799) | Jan 2024 | 2 comments, no maintainer reply |
| Durations lose microseconds beyond ~136 years | [#332](https://github.com/python-pendulum/pendulum/issues/332) | Jan 2019 | 1 comment, no maintainer reply |
| `Time` arithmetic drops the zone and microseconds | [#362](https://github.com/python-pendulum/pendulum/issues/362), [#584](https://github.com/python-pendulum/pendulum/issues/584) | Apr 2019 | no comments |
| A naive value's `is_dst()` is `True` while its `dst()` is `None` | — | unreported | — |
| `is_future()` and `diff_for_humans()` raise `TypeError` on naive values | — | unreported | — |
| `Interval.in_days()` counts local calendar dates, not 24-hour periods | — | unreported | — |
| A negative `Interval` contains neither endpoint, yet `range()` iterates it | — | unreported | — |
| Pickling and `copy.copy` drop `fold` | [#908](https://github.com/python-pendulum/pendulum/issues/908) | Aug 2025 | fix open in [#909](https://github.com/python-pendulum/pendulum/pull/909) |
| `precise_diff` ignores the end's time of day | [#906](https://github.com/python-pendulum/pendulum/issues/906) | Aug 2025 | claimed fixed in 3.2.0; it is not |
| `precise_diff` month detection is not monotonic — 29 days is "1 month", 30 days is "4 weeks 2 days" | — | unreported | — |
| The two builds disagree on ISO 8601 durations | [#534](https://github.com/python-pendulum/pendulum/issues/534) | Feb 2021 | 1 comment, no maintainer reply |
| No parity tests between the two builds | [#907](https://github.com/python-pendulum/pendulum/issues/907) | Aug 2025 | no comments |
| `from_format(..., "X", tz=...)` returns the wrong instant | — | unreported | — |
| Out-of-range offsets parse, then fail on use | — | unreported | — |
| Offsets in time-only strings are silently discarded | — | unreported | — |
| Formatter tokens are recognised but not implemented | — | unreported | — |
| Locale data is wrong or missing in ~15 locales | — | unreported | — |
| `TZ` is ignored on macOS | [#905](https://github.com/python-pendulum/pendulum/issues/905) | Jul 2025 | 2 comments |
| The classes declare no `__slots__` | — | unreported | — |
| `timezone(2)` means seconds, `datetime(tz=2)` means hours | — | unreported | — |
| No API reference | [#199](https://github.com/python-pendulum/pendulum/issues/199) | May 2018 | last maintainer reply 2018 |

(pendulum-parse-lenient)=

### Parsing accepts what it cannot represent

Guessing at missing input has a counterpart in what the parser lets through.
Out-of-range offsets are not rejected at parse time; the resulting value
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

The rest of the leniency is a list rather than an argument. Malformed input
leaks internal exceptions instead of a parse error — `parse("12:")` raises
`TypeError`, `parse("")` complains that a year must be in 1..9999 — and
unknown keyword arguments to `parse()` are swallowed in silence.
`from_format()` has a set of its own: the bracket-escaping example from
Pendulum's own documentation raises, a `Z` token matches a literal `Z` and
then crashes, fractional seconds are scaled by the token's length rather than
by the digits matched, a weekday token silently overrides the explicit date,
and a timestamp token combined with `tz=` returns an instant an hour out. The
two builds do not agree on which inputs belong in this list at all; see
{ref}`the two implementations <pendulum-two-impls>`.

### Format tokens and locale data are unreliable

The token formatter substitutes every letter that happens to be a token,
whether or not it was meant as one:

```python
>>> pendulum.datetime(2024, 1, 15).format("Today is dddd")
'To1ay i0 Monday'
```

The rest is a catalogue. Several tokens — the ISO week-year `GGGG` and `WW`
among them — are recognised but not implemented, and are emitted literally;
the lowercase `a` (am/pm) token does nothing when formatting though it works
when parsing; `YY` is empty for years below 10. Naive values produce RFC
strings with a dangling space and no offset, and `to_iso8601_string()` emits
`Z` only for the key `"UTC"`, so `Etc/UTC` and a fixed `+00:00` print
`+00:00`.

The locale data is where this costs most, since localization is the reason to
reach for the formatter at all: `zh` raises `KeyError` from
`diff_for_humans(other)`, `nl` raises `TypeError` for the `e` token, `lt` says
"from now" about the past, several `L`/`LLLL` presets are copied from English
or Danish, and fifteen locales report "1 second ago" for two identical
instants. `diff_for_humans()` also rounds per branch rather than uniformly
(`23h59m` → `'23 hours'`, but `1d22h` → `'2 days'`) and measures wall-clock
time, so a real 24 hours across the autumn transition reads `'23 hours'`.

(pendulum-time-arithmetic)=

### `Time` arithmetic can discard information

Pendulum exposes aware `Time` values, but its arithmetic converts through an
epoch datetime and returns only the clock fields. The timezone is silently
lost, subtraction drops microseconds
([#362](https://github.com/python-pendulum/pendulum/issues/362),
[#584](https://github.com/python-pendulum/pendulum/issues/584)),
and a negative `timedelta` is rejected because of `timedelta`'s own
day/seconds normalization:

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

### Timezones Pendulum did not create

Pendulum's methods work through `DateTime.tz`, which is `None` for any
`tzinfo` that isn't Pendulum's own. Such values are easy to come by —
`astimezone()` with no argument or with a `ZoneInfo`, `replace(tzinfo=...)`,
or the constructor — and Pendulum's methods then treat them as naive,
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

(Issues [#527](https://github.com/python-pendulum/pendulum/issues/527) and
[#646](https://github.com/python-pendulum/pendulum/issues/646) report the older
`AttributeError` on this path; 3.x replaced the error with wrong values.)

Passing a `dateutil` zone to `tz=` is quietly turned into a fixed offset —
UTC if no datetime is at hand:

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
`FixedTimezone` define `__eq__` but not `__hash__`, which in Python makes
them unhashable:

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

Timezones as dictionary keys, set members or `lru_cache` arguments are routine;
none of that works.

(pendulum-serialization)=

### Serialization can change the instant

Pickling does not preserve `fold`. Serializing a datetime in the second
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

Shallow copying follows the same reconstruction path and has the same effect;
`deepcopy()` does preserve the fold.
This is tracked in [#908](https://github.com/python-pendulum/pendulum/issues/908);
an open fix is available in
[pull request #909](https://github.com/python-pendulum/pendulum/pull/909).

(pendulum-slots)=

### The classes carry a `__dict__`

None of Pendulum's classes declares `__slots__`, so every instance carries a
dictionary the standard library's does not. A `DateTime` costs 80 bytes plus a
272-byte `__dict__`, against 48 bytes for a `datetime` — and a mistyped
attribute is accepted in silence:

```python
>>> d = pendulum.datetime(2024, 1, 1)
>>> d.yeaar = 3000        # no error
>>> d.__dict__
{'yeaar': 3000}
```

(pendulum-global-state)=

### Global settings change behavior at a distance

Locale, week start and the local timezone are process-wide settings, so the
result of a call depends on state the call does not mention — set by an
unrelated part of the program, or by a library it happens to import.

- `week_starts_at()` and `week_ends_at()` are independent; setting only the
  first gives one-day and eight-day weeks (`pendulum.week_starts_at(SUNDAY)`;
  a Sunday's `start_of("week")` and `end_of("week")` are both itself), and
  `week_of_month`/`week_of_year` ignore the setting.
- `first_of("month", pendulum.MONDAY)` returns January 7 instead of January 1
  after the *standard library's* `calendar.setfirstweekday(calendar.SUNDAY)`.
- `set_locale()` is process-global and, as shown above, reaches the RFC
  formats.
- On macOS the `TZ` environment variable is ignored
  ([#905](https://github.com/python-pendulum/pendulum/issues/905)):
  with `TZ=America/New_York`, `pendulum.now()` reports the machine's zone while
  `datetime.now().astimezone()` reports New York.

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

:::{admonition} How `whenever` does it
:class: tip

`whenever` has no global settings to change: locale-dependent formatting is
out of scope, and the system timezone is read
{ref}`where it is used <systemtime>` rather than cached in a module-level
variable. Tests that need a different "now" or a different zone
[patch them explicitly](guide/testing.md), for the duration of the test.
:::

(pendulum-two-impls)=

### Two implementations that disagree

Pendulum ships a Rust extension and a pure-Python fallback
(`PENDULUM_EXTENSIONS=0`). Offering both is a good idea — `whenever` does the
same — but only if they agree. The project lacks systematic parity tests
between them, as acknowledged in
[#907](https://github.com/python-pendulum/pendulum/issues/907), and they
diverge in both parsing and arithmetic.

The compiled `precise_diff` checks the *exact* type of its second argument,
so when an `Interval`'s end was a standard-library datetime (which Pendulum
wraps in a subclass), its time of day is treated as midnight:

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
This is [#906](https://github.com/python-pendulum/pendulum/issues/906), whose
last comment claims it was fixed in 3.2.0; it wasn't, and the offending check
is still on the main branch.

The two parsers disagree on valid and invalid input alike. On the compiled
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

Even an interval with a duration resolves differently:
`parse("2024-03-30T12:00/PT24H", tz="Europe/Paris").end` is 13:00 the next
day on the compiled build (24 elapsed hours) and 12:00 on the pure-Python one
(the Python `Duration` normalises `PT24H` into one calendar day).

(pendulum-project)=

## The state of the project

Neither list above is going to get shorter, and for much the same reason. The
design decisions would take a breaking redesign. The bugs would take someone
to do them.

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
- the introduction says that comparisons account for time zones, which the
  repeated-hour example above contradicts.

### Maintenance remains a concern

Pendulum's original author wrote nearly all of the library and its last
major release, 3.0 (December 2023), which was a breaking release: the `Period`
class was renamed, the transition-rule API was removed, and the C extension was
replaced by a Rust one. Their contributions stop shortly after; 2024 saw three
commits in total. Since 2025 the project lives under the `python-pendulum`
organisation with new maintainers, who have shipped 3.1 (April 2025) and 3.2
(January 2026) and are responsive and welcoming.

They are also hamstrung. Most of what this page describes follows from the
design decisions listed at the top, which cannot be changed without breaking
the "drop-in replacement" promise that is Pendulum's main selling point.
Meanwhile, reproducible correctness issues remain open across releases,
including cases where a tested fix is already available
([#909](https://github.com/python-pendulum/pendulum/pull/909),
[#968](https://github.com/python-pendulum/pendulum/pull/968),
[#975](https://github.com/python-pendulum/pendulum/pull/975),
[#985](https://github.com/python-pendulum/pendulum/pull/985),
[#987](https://github.com/python-pendulum/pendulum/pull/987)),
and one-line fixes that nobody has needed enough to write.

## In short

One decision about the delivery mechanism — subclass the standard library and
patch around it — and four about semantics: correct naive datetimes instead
of modelling them, redefine `fold`, put months inside a `timedelta`, complete
the input rather than reject it. Each reasonable at a glance. Reversing the
naive-datetime or `fold` decisions would break silently, handing different
instants back to programs that never changed; reversing the others would
break loudly. That is why the list does not get shorter with each release,
and why the maintainers cannot make it shorter without giving up the
compatibility that made Pendulum the practical choice in 2016.

`whenever` takes the opposite decisions, and pays for them: there is no
drop-in path, and you have to decide what each value in your program actually
is. In exchange, instants, plain datetimes and zoned datetimes are separate
types rather than one class with modes; whether a unit is exact or calendar is
a property of the unit rather than an inference from the call; ambiguity is
settled by a named {ref}`disambiguate <ambiguity>` argument, the same way no
matter how the value was created; and nothing subclasses `datetime`, so there
is no inherited contract left to patch around.

[^versions]: This page is up to date as of Pendulum 3.2.0. Every example was
    run against that version on CPython 3.14, unless stated otherwise.
