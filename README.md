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
or that you avoided the [pitfalls](https://dev.arie.bovenberg.net/blog/python-datetime-pitfalls/) of the standard library?
There’s no way to be sure...

✨ Until now! ✨

Whenever is designed from the ground up to **enforce correctness**.
Mistakes become <span style="text-decoration: underline; text-decoration-color: red; text-decoration-style: wavy">red squiggles</span> in your IDE, instead of bugs in production.
It's also **way faster** than other third-party libraries—and usually the standard library as well.

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

- 🔒 Typesafe API prevents common bugs
- ✅ Fixes pitfalls [arrow and pendulum don't](https://dev.arie.bovenberg.net/blog/python-datetime-pitfalls/#datetime-library-scorecard)
- ⚖️  Based on proven and [familiar concepts](https://www.youtube.com/watch?v=saeKBuPewcU)
- ⚡️ Unmatched performance
- 💎 Thoroughly tested and documented
- 📆 Support for date arithmetic
- ⏱️ Nanosecond precision
- 🦀 Rust!—but with a pure-Python fallback
- 🚀 Support for subinterpreters and disabling GIL (experimental)

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
>>> py311_release.to_tz("Europe/Paris")
ZonedDateTime(2022-10-24 19:00:00+02:00[Europe/Paris])
>>> pycon23_start.to_local_system()  # example: system timezone in NYC
LocalSystemDateTime(2023-04-21 11:00:00-04:00)

# Comparison and equality across aware types
>>> py311_release > pycon23_start
False
>>> py311_release == py311_release.to_tz("America/Los_Angeles")
True

# Naive type that can't accidentally mix with aware types
>>> hackathon_invite = NaiveDateTime(2023, 10, 28, hour=12)
>>> # Naïve/aware mixups are caught by typechecker
>>> hackathon_invite - py311_release  # error flagged here
>>> # Only explicit assumptions will make it aware
>>> hackathon_start = hackathon_invite.assume_tz("Europe/Amsterdam")
ZonedDateTime(2023-10-28 12:00:00+02:00[Europe/Amsterdam])

# DST-safe arithmetic
>>> hackathon_end = hackathon_start.add(hours=24)
ZonedDateTime(2022-10-29 11:00:00+01:00[Europe/Amsterdam])

# Lossless round-trip to/from text (useful for JSON/serialization)
>>> str(py311_release)
'2022-10-24T17:00:00Z'
>>> ZonedDateTime.parse_common_iso('2022-10-24T19:00:00+02:00[Europe/Paris]')
ZonedDateTime(2022-10-24 19:00:00+02:00[Europe/Paris])

# Conversion to/from common formats
>>> py311_release.format_rfc2822()  # also: parse_rfc2822()
"Mon, 24 Oct 2022 17:00:00 GMT"
>>> pycon23_start.format_rfc3339()  # also: parse_rfc3339()
"2023-04-21 09:00:00-06:00"

# Basic parsing (to be extended)
>>> OffsetDateTime.strptime("2022-10-24+02:00", "%Y-%m-%d%z")
OffsetDateTime(2022-10-24 00:00:00+02:00)

# If you must: you can convert to and from the standard lib
>>> pycon23_start.py_datetime().ctime()
'Fri Apr 21 09:00:00 2023'
```

Read more in the [feature overview](https://whenever.readthedocs.io/en/latest/overview.html)
or [API reference](https://whenever.readthedocs.io/en/latest/api.html).

## Limitations

- Supports the proleptic Gregorian calendar between 1 and 9999 AD
- Timezone offsets are limited to whole seconds
- No support for leap seconds

## Why not...?

### The standard library

Given it's over 20 years old, Python's `datetime` library has actually held up remarkably well.
When it was designed in 2002, timezones weren't standardized like they are now,
and the influential java.time library was still a few years away.
It's been able to adapt to changes, but it's showing its age.
There are many pitfalls that are hard to avoid—even for experienced developers.

Most notably:

- Naive and aware datetimes are incompatible, but easy to mix up with disastrous results
- Accounting for Daylight Saving Time (DST) is surprisingly hard and error-prone

I wrote a more detailed [blog post](https://dev.arie.bovenberg.net/blog/python-datetime-pitfalls/)
going into more details—and how third party libraries don't (fully) solve these issues.

### Arrow

Arrow is probably the most historically popular 3rd party datetime library.
It attempts to provide a more *friendly* API than the standard library,
but doesn't address the core issues with the standard library:
DST-handling is still easy to get wrong, and its decision to reduce the number
of types to just one (``arrow.Arrow``) means that it's even harder
for typecheckers to catch mistakes.

### Pendulum

Pendulum came in the scene in 2016, promising better DST-handling,
as well as improved performance.
However, it only fixes [*some* DST-related pitfalls](https://dev.arie.bovenberg.net/blog/python-datetime-pitfalls/),
and its performance has significantly [degraded over time](https://github.com/sdispater/pendulum/issues/818).
Additionally, maintenance seems inactive since the breaking 3.0 release in 2023: 
Serious issues have remained answered and no PRs have been merged since then.

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

## Roadmap

- 🧪 **0.x**: get to feature-parity, process feedback, and tweak the API:

  - ✅ Datetime classes
  - ✅ Deltas
  - ✅ Date and time of day (separate from datetime)
  - ✅ Implement Rust extension for performance
  - 🚧 Interval
  - 🚧 Improved parsing and formatting
- 🔒 **1.0**: API stability and backwards compatibility

## Versioning and compatibility policy

**Whenever** follows semantic versioning.
Until the 1.0 version, the API may change with minor releases.
Breaking changes will be meticulously explained in the changelog.
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
