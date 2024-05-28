# ⏰ Whenever

[![](https://img.shields.io/pypi/v/whenever.svg?style=flat-square&color=blue)](https://pypi.python.org/pypi/whenever)
[![](https://img.shields.io/pypi/pyversions/whenever.svg?style=flat-square)](https://pypi.python.org/pypi/whenever)
[![](https://img.shields.io/pypi/l/whenever.svg?style=flat-square&color=blue)](https://pypi.python.org/pypi/whenever)
[![](https://img.shields.io/badge/mypy-strict-forestgreen?style=flat-square)](https://mypy.readthedocs.io/en/stable/command_line.html#cmdoption-mypy-strict)
[![](https://img.shields.io/badge/coverage-100%25-forestgreen?style=flat-square)](https://github.com/ariebovenberg/whenever)
[![](https://img.shields.io/github/actions/workflow/status/ariebovenberg/whenever/tests.yml?branch=main&style=flat-square)](https://github.com/ariebovenberg/whenever)
[![](https://img.shields.io/readthedocs/whenever.svg?style=flat-square)](http://whenever.readthedocs.io/)

**Fast and typesafe datetimes for Python, written in Rust**

Do you cross your fingers every time you work with datetimes,
hoping that you didn't mix naive and aware?
or that you converted to UTC everywhere?
or that you avoided the [many pitfalls](https://dev.arie.bovenberg.net/blog/python-datetime-pitfalls/) of the standard library?
There’s no way to be sure...

✨ Until now! ✨

Whenever is designed from the ground up to **enforce correctness**.
Mistakes become <span style="text-decoration: underline; text-decoration-color: red; text-decoration-style: wavy">red squiggles</span> in your IDE, instead of bugs in production.
It's also **way faster** than other third-party libraries—and often the standard library as well.

  <p align="center">
    <picture align="center">
        <source media="(prefers-color-scheme: dark)" srcset="https://raw.githubusercontent.com/ariebovenberg/whenever/rust/benchmarks/comparison/graph-dark.svg">
        <source media="(prefers-color-scheme: light)" srcset="https://raw.githubusercontent.com/ariebovenberg/whenever/rust/benchmarks/comparison/graph-light.svg">
        <img alt="Shows a bar chart with benchmark results." src="https://user-images.githubusercontent.com/1309177/232603516-4fb4892d-585c-4b20-b810-3db9161831e4.svg">
    </picture>
  </p>

  <p align="center" style="font-size: 14px">
    <i>RFC3339-parse, normalize, compare to now, shift, and change timezone (1M times)</i>
  </p>

## Benefits

- 🔒 Typesafe API protects you from common bugs
- ✅ Fixes pitfalls [arrow and pendulum don't](https://dev.arie.bovenberg.net/blog/python-datetime-pitfalls/#datetime-library-scorecard)
- ⚖️  Based on [familiar, proven concepts](https://www.youtube.com/watch?v=saeKBuPewcU)
- ⚡️ Unmatched performance
- 💎 Thoroughly tested and documented
- 📆 Support for date arithmetic
- ⏱️ Nanosecond precision
- 🐍 Pure-Python fallback available

<!-- TODO: mention extra features -->

<div align="center">

[📖 Docs](https://whenever.readthedocs.io) |
[🐍 PyPI](https://pypi.org/project/whenever/) |
[🐙 GitHub](https://github.com/ariebovenberg/whenever) |
[🚀 Changelog](https://whenever.readthedocs.io/en/latest/changelog.html) |
[❓ FAQ](https://whenever.readthedocs.io/en/latest/faq.html) |
[🗺️ Roadmap](#roadmap) |
[💬 Issues & discussions](https://github.com/ariebovenberg/whenever/issues)

</div>

> ⚠️ **Note**: Whenever is in pre-1.0 stage. The API may change with minor releases.
> On the plus side, this means that the API can still be influenced by your feedback!

## Quickstart

```python
>>> from whenever import (
...    # Explicit types for different use cases
...    UTCDateTime,     # -> Enforce UTC-normalization
...    OffsetDateTime,  # -> Simple localized times
...    ZonedDateTime,   # -> Full-featured timezones
...    NaiveDateTime,   # -> Without any timezone
... )

>>> py311_release = UTCDateTime(2022, 10, 24, hour=17)
UTCDateTime(2022-10-24 17:00:00Z)
>>> pycon23_start = OffsetDateTime(2023, 4, 21, hour=9, offset=-6)
OffsetDateTime(2023-04-21 09:00:00-06:00)

# Simple, explicit conversions
>>> py311_release.in_tz("Europe/Paris")
ZonedDateTime(2022-10-24 19:00:00+02:00[Europe/Paris])
>>> pycon23_start.in_local_system()  # example: system timezone in NYC
LocalSystemDateTime(2023-04-21 11:00:00-04:00)

# Comparison and equality across aware types
>>> py311_release > pycon23_start
False
>>> py311_release == py311_release.in_tz("America/Los_Angeles")
True

# Naive type that can't accidentally mix with aware types
>>> hackathon_invite = NaiveDateTime(2023, 10, 28, hour=12)
>>> # Naïve/aware mixups are caught by typechecker
>>> hackathon_invite - py311_release
>>> # Only explicit assumptions will make it aware
>>> hackathon_start = hackathon_invite.assume_in_tz("Europe/Amsterdam")
ZonedDateTime(2023-10-28 12:00:00+02:00[Europe/Amsterdam])

# DST-aware operators
>>> hackathon_end = hackathon_start.add(hours=24)
ZonedDateTime(2022-10-29 11:00:00+01:00[Europe/Amsterdam])

# Lossless round-trip to/from text (useful for JSON/serialization)
>>> str(py311_release)
'2022-10-24 17:00:00Z'
>>> ZonedDateTime.from_default_format('2022-10-24 19:00:00+02:00[Europe/Paris]')
ZonedDateTime(2022-10-24 19:00:00+02:00[Europe/Paris])

# Conversion to/from common formats
>>> py311_release.rfc2822()  # also: from_rfc2822()
"Mon, 24 Oct 2022 17:00:00 GMT"
>>> pycon23_start.rfc3339()  # also: from_rfc3339()
"2023-04-21T09:00:00-06:00"

# Basic parsing
>>> OffsetDateTime.strptime("2022-10-24+02:00", "%Y-%m-%d%z")
OffsetDateTime(2022-10-24 00:00:00+02:00)

# If you must: you can access the underlying datetime object
>>> pycon23_start.py_datetime().ctime()
'Fri Apr 21 09:00:00 2023'
```

Read more in the [feature overview](https://whenever.readthedocs.io/en/latest/overview.html)
or [API reference](https://whenever.readthedocs.io/en/latest/api.html).

## Why not...?

### The standard library

The standard library is full of quirks and pitfalls.
To summarize the detailed [blog post](https://dev.arie.bovenberg.net/blog/python-datetime-pitfalls/):

1.  Incompatible concepts of naive and aware are squeezed into one class
2.  Operators ignore Daylight Saving Time (DST)
3.  The meaning of "naive" is inconsistent (UTC, local, or unspecified?)
4.  Non-existent datetimes pass silently
5.  It guesses in the face of ambiguity
6.  False negatives on equality of ambiguous times between timezones
7.  False positives on equality of ambiguous times within the same timezone
8.  ``datetime`` inherits from ``date``, but behaves inconsistently
9.  ``datetime.timezone`` isn’t enough for full-featured timezones.
10. The local timezone is DST-unaware

### Pendulum

Pendulum is full-featured datetime library, but it's
hamstrung by the decision to inherit from the standard library ``datetime``.
This means it inherits most of the pitfalls mentioned above,
with the notable exception of DST-aware addition/subtraction.

### Arrow

Arrow is probably the most historically popular datetime library.
Pendulum did a good write-up of [the issues with Arrow](https://pendulum.eustace.io/faq/).
It addresses fewer of datetime's pitfalls than Pendulum.

### DateType

DateType mostly fixes the issue of mixing naive and aware datetimes,
and datetime/date inheritance during type-checking,
but doesn't address the other pitfalls.
The type-checker-only approach also means that it doesn't enforce correctness at runtime,
and it requires developers to be knowledgeable about
how the 'type checking reality' differs from the 'runtime reality'.

### python-dateutil

Dateutil attempts to solve some of the issues with the standard library.
However, it only *adds* functionality to work around the issues,
instead of *removing* the pitfalls themselves.
This still puts the burden on the developer to know about the issues,
and to use the correct functions to avoid them.
Without removing the pitfalls, it's still very likely to make mistakes.

### Maya

It's unmaintained, but does have an interesting approach.
By enforcing UTC, it bypasses a lot of issues with the standard library.
To do so, it sacrifices the ability to represent offset, zoned, and local datetimes.
So in order to perform any timezone-aware operations, you need to convert
to the standard library ``datetime`` first, which reintroduces the issues.

### Heliclockter

This library is a lot more explicit about the different types of datetimes,
addressing issue of naive/aware mixing with UTC, local, and zoned datetime subclasses.
It doesn't address the other datetime pitfalls though.

## Roadmap

- 🧪 **0.x**: get to feature-parity, process feedback, and tweak the API:

  - ✅ Datetime classes
  - ✅ Deltas
  - ✅ Date and time of day (separate from datetime)
  - 🚧 Interval
  - 🚧 Improved parsing and formatting
  - 🚧 Implement Rust extension for performance
- 🔒 **1.0**: API stability and backwards compatibility
- 🐍 **future**: Inspire a standard library improvement

## Versioning and compatibility policy

**Whenever** follows semantic versioning.
Until the 1.0 version, the API may change with minor releases.
Breaking changes will be avoided as much as possible,
and meticulously explained in the changelog.
Since the API is fully typed, your typechecker and/or IDE
will help you adjust to any API changes.

> ⚠️ **Note**: until 1.x, pickled objects may not be unpicklable across
> versions. After 1.0, backwards compatibility of pickles will be maintained
> as much as possible.

## Acknowledgements

This project is inspired by the following projects. Check them out!

- [Noda Time](https://nodatime.org/)
- [Temporal](https://tc39.es/proposal-temporal/docs/)
- [Chrono](https://docs.rs/chrono/latest/chrono/)

The benchmark comparison graph is based on the one from the [Ruff](https://github.com/astral-sh/ruff) project.

## Contributing

Contributions are welcome! Please open an issue or a pull request.

> ⚠️ **Note**: Non-trivial changes should be discussed in an issue first.
> This is to avoid wasted effort if the change isn't a good fit for the project.

> ⚠️ **Note**: Some tests are skipped on Windows.
> These tests use unix-specific features to set the timezone for the current process.
> As a result, Windows isn't able to run certain tests that rely on the system timezone.
> It appears that this functionality (only needed for the tests) is
> [not available on Windows](https://stackoverflow.com/questions/62004265/python-3-time-tzset-alternative-for-windows>).

## Setting up a development environment

An example of setting up things up:

```bash
# install the dependencies
make init

# build the rust extension
make build

make test  # run the tests (Python and Rust)
make format  # apply autoformatting
make ci-lint  # various static checks
make typecheck  # run mypy and typing tests
```
