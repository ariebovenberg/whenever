(faq)=
# FAQ

```{eval-rst}
.. currentmodule:: whenever
```

## Does performance really matter for a datetime library?

Most of the time, datetime handling isn't the main bottleneck in Python
programs---but datetime logic is arithmetic-heavy and often applied in bulk,
making it a classic case where faster code pays off.
That's why many core Python components are
backed by optimized implementations, and why this library offers a Rust
version for speed alongside a pure-Python version for portability.

## Is free-threaded Python supported?

Yes, free-threaded Python is supported. However, this support is still
in beta. Please report any issues you encounter when using `whenever` in
a free-threaded Python environment.

(faq-why-instant)=
## Why does {class}`~whenever.Instant` exist?

Since you can also express a moment in time using
{class}`~whenever.ZonedDateTime`, you might
wonder why {class}`~whenever.Instant` exists.
The reason it exists is precisely *because* it doesn't include a
timezone. By using {class}`~whenever.Instant`,
you clearly express that you only care about *when* something happened,
not about the local time.

Consider the difference in intent:

```python
class ChatMessage:
    sent: Instant       # only the moment matters

class CalendarEvent:
    start: ZonedDateTime  # the local time matters too
```

In the first example, it's clear that you only care about the moment
a message was sent. In the second, you communicate that you
also store the user's local time. This intent is crucial for reasoning
about the code, and extending it correctly (e.g. with migrations, API
endpoints, etc).

(faq-instant-no-local)=
## Why doesn't {class}`~whenever.Instant` have `.year`, `.hour`, etc.?

An instant represents a specific moment in time,
independent of any calendar system or timezone.
Although its debug representation uses UTC,
that's just a convenient way to display it—it doesn't
mean the instant *is* a UTC datetime.

```python
>>> now = Instant.now()
Instant("2026-01-23 05:30:15Z")
>>> now.year
AttributeError: 'Instant' object has no attribute 'year'
```

If you need to access calendar fields, convert to a datetime type first:

```python
>>> now.to_tz("Europe/Amsterdam").year
2026
>>> now.to_fixed_offset(0).hour  # only if you truly need UTC fields
5
```

(faq-why-offset-dt)=
## Why does {class}`~whenever.OffsetDateTime` exist?

Most datetime formats—ISO 8601, RFC 2822, RFC 3339—only carry a fixed
UTC offset (e.g. `+02:00`), not a full timezone name.
{class}`~whenever.OffsetDateTime` represents *exactly* what these formats
contain: a local time pinned to a fixed offset.

This makes it the natural choice for:

- **Parsing and serializing** timestamps from APIs, logs, and databases.
- **Representing moments in the past**, where the offset was correct
  at the time of recording and the timezone rules no longer matter.
- **Simple contexts** where no DST transitions are involved.

The trade-off is that a fixed offset can't track DST.
If you shift or round an {class}`~whenever.OffsetDateTime`, the
library preserves the original offset verbatim—which may be wrong
for future dates if the region's rules have changed.
That's why these operations emit a
{class}`~whenever.PotentiallyStaleOffsetWarning`.
When you need DST-safe arithmetic, convert to
{class}`~whenever.ZonedDateTime` first.

See {ref}`choosing-a-type` for guidance on which type to use.

(faq-why-3-deltas)=
## Why are there three delta types?

Date and time durations have fundamentally different arithmetic rules
depending on the units involved.
Rather than papering over this with a single type,
`whenever` gives each category its own type
(see {ref}`design`):

1. **{class}`~whenever.TimeDelta`** — for exact durations
   (hours, minutes, seconds, nanoseconds).
   These normalize automatically: `90 minutes` becomes `1 hour 30 minutes`.
   They support comparison, mathematical operators, and don't need
   any context to resolve.

2. **{class}`~whenever.ItemizedDateDelta`** — for pure calendar durations
   (years, months, weeks, days).
   These keep their components *itemized*: `1 month` stays `1 month`,
   and isn't normalized to a number of days.
   Converting between calendar units requires a reference date
   (because `1 month` is 28–31 days depending on when you start).

3. **{class}`~whenever.ItemizedDelta`** — for mixed bags of calendar *and*
   exact units, such as `1 month, 3 hours, 20 minutes`.
   Useful for display and ISO 8601 round-tripping.
   Like {class}`~whenever.ItemizedDateDelta`, it keeps components itemized and
   needs a reference date for conversion.

Having three explicit types prevents subtle bugs like comparing
`1 month` to `30 days` without context,
or accidentally normalizing away important calendar semantics.

See {ref}`durations` for the full reference.

(faq-why-warnings)=
## Why warnings instead of errors?

Operations that *could* introduce DST bugs—such as arithmetic on
{class}`~whenever.OffsetDateTime` or {class}`~whenever.PlainDateTime`—emit
a warning rather than raising an exception.
This is a deliberate choice, because these operations aren't always wrong
(see {ref}`design`).

The warning approach gives you four levels of control:

1. **Learn by default** — if you're scripting quickly, the warning appears
   in the console and teaches you about the pitfall. If you're in a hurry,
   the library doesn't get in your way and you can fix the issue later.
2. **Ban project-wide** — in production code, convert warnings to errors
   with Python's standard {mod}`warnings` filter:
   ```python
   import warnings
   warnings.filterwarnings("error", category=whenever.PotentialDstBugWarning)
   ```
3. **Escape hatch** — when the operation is intentional, silence it with
   a keyword argument (e.g. ``stale_offset_ok=True``),
   documenting the decision in code.
4. **Fine-grained** — configure at the module or function level, using
   Python's existing warning infrastructure.

(faq-to-vs-assume)=
## Why are conversions called `to_*` and `assume_*`?

When converting between types, `whenever` uses two naming conventions:

- **`to_*`** methods convert between types that already carry enough
  information to determine the result unambiguously.
  For example, {meth}`ZonedDateTime.to_instant`
  can compute the exact moment because the timezone is known.
- **`assume_*`** methods convert from types that *lack* information.
  The developer must supply the missing piece (a timezone, an offset).
  For example, {meth}`~whenever.PlainDateTime.assume_tz` requires you to
  specify which timezone the plain datetime is in.

The `assume_*` naming is intentional: it signals that you're making
an assumption that the library can't verify for you.

## Why the name `PlainDateTime`?

This has been an oft-discussed topic. Several names were considered for
the concept of a "datetime without a timezone".

Each option had its pros and cons.

- Why not `NaiveDateTime`? This name is already used in the standard
  library, which does give it recognition. However, "naive" is a
  decidedly negative term. While datetimes without a timezone *can* be
  used in a naive way by developers who don\'t understand the
  implications, they are not inherently wrong to use.
- Why not `CivilDateTime`? This is the most "technically correct"
  name, as it refers to the [time as used in civilian
  life](https://en.wikipedia.org/wiki/Civil_time). This name is most
  notably used in Jiff (Rust) and Abseil (C++) libraries. While this
  niche name is a boon to these languages, Python tends to favor more
  common, non-jargon names: "dict" over "hashmap", "list" over
  "array", etc.
- Why not `LocalDateTime`? This is the name that ISO8601 gives to the
  concept, also making it a "technically correct" name. However, the
  term "local" has become overloaded in the Python world where it
  often refers to the system timezone.

While `PlainDateTime` is not perfect, it has the following advantages:

- Javascript's new Temporal API uses this name. There's significant
  overlap between Python and Javascript developers, so this name is
  likely to be familiar as its popularity grows.
- It's a name that is easy to understand and remember, also for
  non-native speakers.

Common critiques of `PlainDateTime` are:

- *The name doesn't convey any meaning in itself.* This is also a
  strength. It *is* simply a date+time. Yes, it can be used to represent
  a local time, but it doesn't have to be.
- *The name is defined by what it is not.* Actually, it's really common
  to name things in opposition to something else. Think of:
  "*stainless* steel", "*plain* text", or "*serverless*
  computing".

(faq-leap-seconds)=
## Are leap seconds supported?

Leap seconds are not fully supported. Taking leap seconds into account
is a complex and niche feature, which is not needed for the vast majority
of applications. This decision is consistent with other modern libraries
(e.g. NodaTime, Temporal) and standards (RFC 5545, Unix time) which do
not support leap seconds.

However, *whenever* does accept leap seconds during parsing, normalizing
them to the previous second (59). This applies to ISO 8601, RFC 2822, and
[custom format strings](pattern-format).

(faq-why-not-dropin)=
## Why no drop-in replacement for `datetime`?

Fixing the issues with the standard library requires a different API.
Keeping the same API would mean that the same issues would remain. Also,
inheriting from the standard library would result in brittle code: many
popular libraries expect `datetime` *exactly*, and [don\'t
work](https://github.com/sdispater/pendulum/issues/289#issue-371964426)
with
[subclasses](https://github.com/sdispater/pendulum/issues/131#issue-241088629).

(faq-production-ready)=
## Is it production-ready?

The core functionality is complete and mostly stable. The goal is to
reach 1.0 soon, but the API may change until then. Of course, it's
still a relatively young project, so the stability relies on you to try
it out and report any issues!

## Where do the benchmarks come from?

More information about the benchmarks can be found in the `benchmarks`
directory of the repository.

## How can I use the pure-Python version?

`whenever` is implemented both in Rust and in pure Python. By default,
the Rust extension is used, as it's faster and more memory-efficient.
But you can opt out of it if you prefer the pure-Python version, which
has a smaller disk footprint and works on all platforms.

```{note}
On PyPy and GraalVM, the Python implementation is automatically used. No
need to configure anything.
```

To opt out of the Rust extension and use the pure-Python version,
install from the source distribution with the
`WHENEVER_NO_BUILD_RUST_EXT` environment variable set:

```bash
WHENEVER_NO_BUILD_RUST_EXT=1 pip install whenever --no-binary whenever
```

You can check if the Rust extension is being used by running:

```bash
python -c "import whenever; print(whenever._EXTENSION_LOADED)"
```

```{note}
If you're using Poetry or another third-party package manager, you
should consult its documentation on opting out of binary wheels.
```

## What about `dateutil`?

`dateutil` is more of an *extension* to `datetime` than a replacement,
so it isn't included in the comparison with Pendulum and Arrow.

That said, while dateutil certainly provides useful helpers
(especially for parsing and arithmetic), it doesn't address
the most fundamental issues with the standard library:
DST-safety and type-level distinction between naive and aware datetimes.
These are issues that only a full replacement can solve.

## Why not simply wrap Rust's `jiff` library?

Jiff is a modern Rust datetime library with similar goals and
inspiration as `whenever`. There are several reasons `whenever`
doesn't wrap it:

1.  Jiff didn't exist when `whenever` was created. Wrapping it was
    only an option after most functionality was already implemented.
2.  Providing a pure-Python version of `whenever` would require
    re-implementing jiff's logic in Python and keeping them in sync.
3.  Jiff has a slightly different design philosophy, most notably
    de-emphasizing the difference between offset and zoned datetimes.
4.  Jiff can't make use of Python's bundled timezone database
    (`tzdata`) if present.
5.  Writing a Rust library with Python bindings primarily in mind allows
    for some optimizations.

If you're interested in a straightforward wrapper around jiff, check
out [Ry](https://pypi.org/project/ry/).

## Why aren't all operators supported for all types?

Some operators may be conspicuously missing for certain types, even
though they could be implemented. For example:

```python
>>> Date(2024, 1, 31) + ItemizedDateDelta(months=1) # Error
```

This is because operators are only implemented where they are *mathematically
intuitive*. For example, when `a + (b + c) = (a + b) + c` and `(a + b) - b = a`.
This isn't the case when working with months
or years, since adding a month to January 31st gives a different result
than adding a month to February 28th. To avoid confusion, these
operators are simply not implemented. There are methods like
`add()` and `subtract()` that can be used
instead, which don't come with the same mathematical expectations:

```python
>>> Date(2024, 1, 31).add(months=1)
>>> Date(2024, 1, 31).add(ItemizedDateDelta(months=1))
```

For the same reason, the `-` operator between two datetimes always
returns a {class}`~whenever.TimeDelta`—an exact elapsed duration where
subtraction is unambiguous.
If you need a difference in calendar units like years, months, or days,
use the {meth}`~whenever.ZonedDateTime.since` /
{meth}`~whenever.ZonedDateTime.until` methods instead:

```python
>>> d1 = ZonedDateTime(2020, 1, 1, tz="Europe/Amsterdam")
>>> d2 = ZonedDateTime(2023, 6, 15, tz="Europe/Amsterdam")
>>> d2 - d1  # exact elapsed time
TimeDelta("PT30263h")
>>> d2.since(d1, units=["years", "months", "days"])  # calendar units
ItemizedDateDelta("P3y5m14d")
```

See {ref}`design` for the full rationale.

## Why can't I subclass `whenever` classes?

`whenever` classes are marked `final` and aren't designed for subclassing.
This is for several reasons:

1.  Composition is a better way to extend the classes. Python's dynamic
    features also make it easy to create something that behaves like
    a subclass.
2.  Properly supporting subclassing requires a lot of extra work, and
    adds subtle ways to misuse the API.
3.  Enabling subclassing would undo some performance optimizations.
