# ⏰ Whenever

[![](https://img.shields.io/pypi/v/whenever.svg?style=flat-square&color=blue)](https://pypi.python.org/pypi/whenever)
[![](https://img.shields.io/pypi/pyversions/whenever.svg?style=flat-square)](https://pypi.python.org/pypi/whenever)
[![](https://img.shields.io/pypi/l/whenever.svg?style=flat-square&color=blue)](https://pypi.python.org/pypi/whenever)
[![](https://img.shields.io/badge/mypy-strict-forestgreen?style=flat-square)](https://mypy.readthedocs.io/en/stable/command_line.html#cmdoption-mypy-strict)
[![](https://img.shields.io/badge/coverage-100%25-forestgreen?style=flat-square)](https://github.com/ariebovenberg/whenever)
[![](https://img.shields.io/github/actions/workflow/status/ariebovenberg/whenever/checks.yml?branch=main&style=flat-square)](https://github.com/ariebovenberg/whenever)
[![](https://img.shields.io/readthedocs/whenever.svg?style=flat-square)](http://whenever.readthedocs.io/)

**Typed and DST-safe datetimes for Python, available in speedy Rust or pure Python.**

Do you cross your fingers every time you work with Python's datetime—hoping that you didn't mix naive and aware?
or that you avoided its [other pitfalls](https://dev.arie.bovenberg.net/blog/python-datetime-pitfalls/)?
or that you properly accounted for Daylight Saving Time (DST)?
There’s no way to be sure...

✨ Until now! ✨

*Whenever* helps you write **correct** and **type checked** datetime code.
Mistakes become <span style="text-decoration: underline; text-decoration-color: red; text-decoration-style: wavy">red squiggles</span> in your IDE, instead of bugs in production.
It's also **way faster** than other third-party libraries—and usually the standard library as well.
If performance isn't your top priority, a **pure Python** version is available as well.


  <p align="center">
    <picture align="center">
        <source media="(prefers-color-scheme: dark)" srcset="https://raw.githubusercontent.com/ariebovenberg/whenever/main/benchmarks/comparison/graph-dark.svg">
        <source media="(prefers-color-scheme: light)" srcset="https://raw.githubusercontent.com/ariebovenberg/whenever/main/benchmarks/comparison/graph-light.svg">
        <img alt="Shows a bar chart with benchmark results." src="https://raw.githubusercontent.com/ariebovenberg/whenever/main/benchmarks/comparison/graph-light.svg">
    </picture>
  </p>

  <p align="center" style="font-size: 14px">
    <i>RFC3339-parse, normalize, compare to now, shift, and change timezone (1M times)</i>
  </p>


<div align="center">

[📖 Docs](https://whenever.readthedocs.io) |
[🐍 PyPI](https://pypi.org/project/whenever/) |
[🐙 GitHub](https://github.com/ariebovenberg/whenever) |
[🚀 Changelog](https://whenever.readthedocs.io/en/latest/changelog.html) |
[❓ FAQ](https://whenever.readthedocs.io/en/latest/faq.html) |
[🗺️ Roadmap](#roadmap) |
[💬 Issues & feedback](https://github.com/ariebovenberg/whenever/issues)

</div>

> ⚠️ **Note**: Whenever is in pre-1.0 beta. The API may change
> as we gather feedback and improve the library.
> Leave a ⭐️ on github if you'd like to see how this project develops!

## Why not the standard library?

Over 20+ years, Python's `datetime` has grown
out of step with what you'd expect from a modern datetime library.
Two points stand out:

1. **It doesn't always account for Daylight Saving Time (DST)**.
   Here is a simple example:

   ```python
   bedtime = datetime(2023, 3, 25, 22, tzinfo=ZoneInfo("Europe/Paris"))
   full_rest = bedtime + timedelta(hours=8)
   # It returns 6am, but should be 7am—because we skipped an hour due to DST!
   ```

   Note this isn't a bug, but a design decision that DST is only considered
   when calculations involve *two* timezones.
   If you think this is surprising, you
   [are](https://github.com/python/cpython/issues/91618)
   [not](https://github.com/python/cpython/issues/116035)
   [alone](https://github.com/python/cpython/issues/112638).

2. **Typing can't distinguish between naive and aware datetimes**.
   Your code probably only works with one or the other,
   but there's no way to enforce this in the type system!

   ```python
   # Does this expect naive or aware? Can't tell!
   def schedule_meeting(at: datetime) -> None: ...
   ```

## Why not other libraries?

There are two other popular third-party libraries, but they don't (fully)
address these issues. Here's how they compare to *whenever* and the standard library:

<div align="center">

|                   | Whenever | datetime | Arrow | Pendulum |
|-------------------|:--------:|:--------:|:-----:|:--------:|
|      DST-safe     |     ✅    |     ❌    |   ❌   |     ⚠️    |
| Typed aware/naive |     ✅    |     ❌    |   ❌   |     ❌    |
|        Fast       |     ✅    |     ✅    |   ❌   |     ❌    |

</div>

[**Arrow**](https://pypi.org/project/arrow/)
is probably the most historically popular 3rd party datetime library.
It attempts to provide a more "friendly" API than the standard library,
but doesn't address the core issues:
it keeps the same footguns, and its decision to reduce the number
of types to just one (``arrow.Arrow``) means that it's even harder
for typecheckers to catch mistakes.

[**Pendulum**](https://pypi.org/project/pendulum/)
arrived on the scene in 2016, promising better DST-handling,
as well as improved performance.
However, it only fixes [*some* DST-related pitfalls](https://dev.arie.bovenberg.net/blog/python-datetime-pitfalls/#datetime-library-scorecard),
and its performance has significantly [degraded over time](https://github.com/sdispater/pendulum/issues/818).
Additionally, it hasn't been actively maintained since a breaking 3.0 release last year.

## Why use whenever?

- 🌐 DST-safe arithmetic
- 🛡️ Typesafe API prevents common bugs
- ✅ Fixes issues [arrow/pendulum don't](https://dev.arie.bovenberg.net/blog/python-datetime-pitfalls/#datetime-library-scorecard)
- ⚖️  Based on proven and [familiar concepts](https://www.youtube.com/watch?v=saeKBuPewcU)
- ⚡️ Unmatched performance
- 💎 Thoroughly tested and documented
- 📆 Support for date arithmetic
- ⏱️ Nanosecond precision
- 🦀 Rust!—but with a [pure-Python option](https://whenever.readthedocs.io/en/latest/faq.html#how-can-i-use-the-pure-python-version)
- 🚀 Support for the latest GIL-related improvements (experimental)

## Quickstart

```python
>>> from whenever import (
...    # Explicit types for different use cases
...    Instant,
...    ZonedDateTime,
...    LocalDateTime,
... )

# Identify moments in time, without timezone/calendar complexity
>>> now = Instant.now()
Instant(2024-07-04 10:36:56Z)

# Simple, explicit conversions
>>> now.to_tz("Europe/Paris")
ZonedDateTime(2024-07-04 12:36:56+02:00[Europe/Paris])

# A 'naive' local time can't accidentally mix with other types.
# You need to explicitly convert it and handle ambiguity.
>>> party_invite = LocalDateTime(2023, 10, 28, hour=22)
>>> party_invite.add(hours=6)
Traceback (most recent call last):
  ImplicitlyIgnoringDST: Adjusting a local datetime implicitly ignores DST [...]
>>> party_starts = party_invite.assume_tz("Europe/Amsterdam", disambiguate="earlier")
ZonedDateTime(2023-10-28 22:00:00+02:00[Europe/Amsterdam])

# DST-safe arithmetic
>>> party_starts.add(hours=6)
ZonedDateTime(2022-10-29 03:00:00+01:00[Europe/Amsterdam])

# Comparison and equality
>>> now > party_starts
True

# Formatting & parsing common formats (ISO8601, RFC3339, RFC2822)
>>> now.format_rfc2822()
"Thu, 04 Jul 2024 10:36:56 GMT"

# If you must: you can convert to/from the standard lib
>>> now.py_datetime()
datetime.datetime(2024, 7, 4, 10, 36, 56, tzinfo=datetime.timezone.utc)
```

Read more in the [feature overview](https://whenever.readthedocs.io/en/latest/overview.html)
or [API reference](https://whenever.readthedocs.io/en/latest/api.html).

## Roadmap

- 🧪 **0.x**: get to feature-parity, process feedback, and tweak the API:

  - ✅ Datetime classes
  - ✅ Deltas
  - ✅ Date and time of day (separate from datetime)
  - ✅ Implement Rust extension for performance
  - 🚧 Parsing leap seconds
  - 🚧 Improved parsing and formatting
  - 🚧 More helpful error messages
  - 🚧 Intervals
- 🔒 **1.0**: API stability and backwards compatibility

## Limitations

- Supports the proleptic Gregorian calendar between 1 and 9999 AD
- Timezone offsets are limited to whole seconds (consistent with IANA TZ DB)
- No support for leap seconds (consistent with industry standards and other modern libraries)

## Versioning and compatibility policy

**Whenever** follows semantic versioning.
Until the 1.0 version, the API may change with minor releases.
Breaking changes will be meticulously explained in the changelog.
Since the API is fully typed, your typechecker and/or IDE
will help you adjust to any API changes.

> ⚠️ **Note**: until 1.x, pickled objects may not be unpicklable across
> versions. After 1.0, backwards compatibility of pickles will be maintained
> as much as possible.

## License

**Whenever** is licensed under the MIT License.
The binary wheels contain Rust dependencies which are licensed under
similarly permissive licenses (MIT, Apache-2.0, and others).
For more details, see the licenses included in the distribution.

## Acknowledgements

This project is inspired by the following projects. Check them out!

- [Noda Time](https://nodatime.org/) and [Joda Time](https://www.joda.org/joda-time/)
- [Temporal](https://tc39.es/proposal-temporal/docs/)

The benchmark comparison graph is based on the one from the [Ruff](https://github.com/astral-sh/ruff) project.
