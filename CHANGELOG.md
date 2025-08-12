# 🚀 Changelog

## 0.9.0 (2025-??-??)

**Breaking Changes**

- `SystemDateTime` has been removed and its functionality is now integrated into `ZonedDateTime`.
  **Migration:**
  - `SystemDateTime.now()` can be replaced with `Instant.now().to_system_tz()`.
  - `to_system_tz()` and `assume_system_tz()` now return a `ZonedDateTime` instead of a `SystemDateTime`.

  **Rationale:** The `SystemDateTime` class was an awkward corner of the API, 
  creating inconsistencies and overlapping with `ZonedDateTime`. 
  This change unifies the API, providing a single, consistent way to handle 
  all timezone-aware datetimes. The original use cases are fully supported 
  by the improved `ZonedDateTime`.

**Added**

- Customizable ISO 8601 Formatting: The `format_common_iso()` methods on all 
  datetime objects now accept parameters to customize the output. 
  You can control the `separator` (e.g., `'T'` or `' '`), 
  the smallest second `unit` (from `hour` to `nanosecond`), 
  and toggle the `basic` (compact) or `extended` format.

**Fixed**

- Resolved a memory leak in the Rust extension where timezone objects that 
  were no longer in use were not properly evicted from the cache.

## 0.8.9 (2025-09-21)

- Fixed not all test files included in source distribution (#266)
- Uploaded missing Python 3.14 wheels

## 0.8.8 (2025-07-24)

- Add wheels for Python 3.14 now that its ABI is stable.
- Add a pure Python wheel so platforms without binary wheels can use
  `whenever`'s pure Python version without having to go through the source
  build process (#256)

## 0.8.7 (2025-07-18)

- Fix some `MIN` and `MAX` constants not documented in the API reference.
- Add `Time.MIN` alias for `Time.MIDNIGHT` for consistency (#245)
- Fix bug in rounding of midnight ``ZonedDateTime`` values in "ceil"/day mode (#249)

## 0.8.6 (2025-06-23)

- Improve error message of `ZonedDateTime.from_py_datetime()` in case
  the datetime's `ZoneInfo.key` is `None`.
- Fix performance regression in `Date.day_of_week()` (#244)

## 0.8.5 (2025-06-09)

- Relax build requirements. It now only depends on `setuptools_rust` if opting
  to build the Rust extension (#240)
- Fixed not all Rust files included in source distribution.
- Update some outdated docstrings.

## 0.8.4 (2025-05-28)

- Fix Pydantic JSON schema generation in certain contexts,
  which affected FastAPI doc generation.

## 0.8.3 (2025-05-22)

- Ensure Pydantic parsing failures of `whenever` types always result in
  a proper `ValidationError`, not a `TypeError`.

## 0.8.2 (2025-05-21)

- Allow Pydantic to generate JSON schema for `whenever` types. This is
  particularly useful for generating OpenAPI schemas for FastAPI.

## 0.8.1 (2025-05-21)

**New**

- Added support for Pydantic serialization/deserialization of
  `whenever` types in the ISO 8601 format. This functionality is in
  preview, and may be subject to change in the future. (#175)

**Fixed**

- ``Weekday`` enum values from the Rust extension are now pickleable.
- Solve crash if Python's garbage collection occurs while the Rust
  extension is still initializing.
- Fixed a crash in parsing malformed fractional ``TimeDelta`` seconds (#234)

**Improved**

- `Time.from_py()` now ignores any `tzinfo`, instead of raising an error.
- A comprehensive refactor of the Rust extension module eliminates
  most unnecessary `unsafe` code, making it safer and more idiomatic.

## 0.8.0 (2025-05-01)

A big release with several improvements and breaking changes that lay
the groundwork for the eventual 1.0 release.

**Improved**

- Timezone operations in the Rust extension are now a lot faster (5-8x),
  due to a new implementation replacing the use of the standard library
  `zoneinfo` module. (#202)
- The `parse_common_iso()` methods support a wider range of ISO 8601
  formats. See the [updated documentation](https://whenever.readthedocs.io/en/latest/overview.html#iso-8601) for details.
  (#204)
- Added an "examples" page to the documentation with practical snippets. (#198)
- RFC2822 parsing is now more robust and faster. (#200)
- Import speed is improved significantly for both the Rust and pure
  Python versions (#228)

**Breaking changes**

- `LocalDateTime` has been renamed to `PlainDateTime`, and the `local()`
  method has been renamed to `to_plain()`. The old names are still
  available (but deprecated) to ease the transition.

  **Rationale**: In observing adoption of the library, the term
  "local" causes confusion for a number of users, since the term
  "local" is so overloaded in the Python world. `PlainDateTime` is
  used in Javascript's Temporal API, and seems to resonate better with
  users. See the [FAQ](https://whenever.readthedocs.io/en/latest/faq.html#why-the-name-plaindatetime)
  for a detailed discussion on the name.

- Rename `instant()` method to `to_instant()`

  **Rationale**: The new name is more consistent with the rest of the
  API.

- Removed the `[format|parse]_rfc3339` method.

  **Rationale**: The improved ISO 8601 parsing method is now RFC 3339
  compatible, making this method unnecessary.
  Strict RFC 3339 parsing can still be done with ``strptime``, if desired

- Passing invalid timezone names now raise a
  `whenever.TimeZoneNotFoundError` (subclass of `ValueError`) instead of
  `zoneinfo.ZoneInfoNotFoundError` (subclass of `KeyError`).

  **Rationale**: This ensures whenever is independent of the `zoneinfo`
  module, and its particularities don't leak into the `whenever` API.

- `TimeDelta.from_py_timedelta` no longer accepts `timedelta`
  subclasses.

  **Rationale**: timedelta subclasses (like pendulum.Duration) often add
  other time components, which cannot be guaranteed to be handled
  correctly.

- The `strptime` methods have been renamed `parse_strptime`,
  and its ``format`` argument is now a keyword-only argument.

  **Rationale**: This ensures all parsing methods have the `parse_` prefix,
  helping in API consistency and discoverability. The keyword-only argument
  helps distinguish between the format string and the string to parse.

- The `InvalidOffset` exception has been renamed `InvalidOffsetError`

  **Rationale**: this more clearly indicates that this is an error condition.
  See #154 for discussion.

- `SkippedTime` and `RepeatedTime` are now subclasses of `ValueError`.

  **Rationale**: it ensures these exceptions can be caught together with
  other exceptions like `InvalidOffsetError` and `TimeZoneNotFoundError`
  during parsing.

- Whenever is no longer affected by `ZoneInfo.clear_cache()` or
  `zoneinfo.reset_tzpath()`, since it now uses its own cache with
  corresponding methods.

  **Rationale**: This ensures whenever is independent of `zoneinfo` in
  both Rust and pure Python implementations.

**Fixed**

- Improved robustness of date calculations at extreme boundaries. (#219)
- Fixed a bug in the pure-Python version of `ZonedDateTime.exact_eq()`
  that could cause false positives in some cases.
- Fixed incorrect type stubs for `day_length()` and `start_of_day()`
  methods.
- Corrected the description of parameters accepted by `now()`. (#213)

## 0.7.3 (2025-03-19)

- Fixed type annotations of `Weekday` enum values, so they are properly
  marked as `int`.

## 0.7.2 (2025-02-25)

- Fixed `round()` method behaving incorrectly when `increment` argument
  is not passed explicitly (#209)

## 0.7.1 (2025-02-24)

- `Date.add` and `Date.subtract` now support `DateDelta` to be passed as
  sole positional argument. This is consistent with the behavior of
  datetime classes.
- Improved performance and robustness of date calculations at extreme
  boundaries
- Minor fixes to docstrings

## 0.7.0 (2025-02-20)

This release adds rounding functionality, along with a small breaking
change (see below).

**Breaking changes**

- `TimeDelta.py_timedelta()` now truncates nanoseconds to microseconds
  instead of rounding them. Use the new `round()` method to customize
  rounding behavior.

**Added**

- Added `round()` to all datetime, `Instant`, and `TimeDelta` classes
- Add floor division and modulo operators to `TimeDelta`
- Add `is_ambiguous()`, `day_length()` and `start_of_day()` to
  `SystemDateTime`, for consistency with `ZonedDateTime`.
- Improvements to documentation

## 0.6.17 (2025-01-30)

- Added `day_length()` and `start_of_day()` methods to `ZonedDateTime`
  to make it easier to work with edge cases around DST transitions, and
  prepare for implementing rounding methods in the future.
- Fix cases in type stubs where positional-only arguments weren\'t
  marked as such

## 0.6.16 (2024-12-22)

- Fix bug in `ZonedDateTime` `repr()` that would mangle some timezone
  names

- Make `disambiguate` argument optional, defaulting to `"compatible"`.

  **Rationale**: This required parameter was a frequent source of
  irritation for users. Although "explicit is better than implicit",
  other modern libraries and standards also choose an (implicit)
  default. For those that do want to enforce explicit handling of
  ambiguous times, a special stubs file or other plugin may be
  introduced in the future.

- Various small fixes to the docs

## 0.6.15 (2024-12-11)

- Add `Date.days_[since|until]` methods for calculating the difference
  between two dates in days only (no months or years)
- Improve docs about arithmetic rules for calendar and time units.

## 0.6.14 (2024-11-27)

- Ensure docstrings and error messages are consistent in Rust extension
  as well as the pure-Python version
- Remove undocumented properties `hour/minute/etc` from `Instant` that
  were accidentally left in the Rust extension.
- `exact_eq()` now also raises `TypeError` in the pure Python version
  when comparing different types.

## 0.6.13 (2024-11-17)

**Added**

- Make `from_py_datetime()` on `Instant`/`OffsetDateTime` less pedantic.
  They now accept any aware datetime
- New `Date.today_in_system_tz()` convenience method

**Fixed**

- Parsing UTC offsets with out-of-range minute components (e.g. `06:79`)
  now raises the expected parsing failure.
- Note in `parse_rfc2822()` docstring that it doesn\'t (yet) validate
  the input, due to limitations in the underlying parser.

## 0.6.12 (2024-11-08)

- Fixed `format_rfc3339()` docstrings that incorrectly included a `T`
  separator. Clarified that `T` can be added by using the
  `format_common_iso()` method instead. (#185)

## 0.6.11 (2024-11-04)

**Added**

- Added `YearMonth` and `MonthDay` classes for working with year-month
  and month-day pairs

**Fixed**

- `whenever.__version__` is now also accessible when Rust extension is
  used

## 0.6.10 (2024-10-30)

**Improved**

- Improve method documentation and autocomplete support (#172, #173,
  #176)

**Fixed**

- Remove lingering undocumented `offset` on `Instant`
- Fix incorrect `LocalDateTime.difference` return type annotation

## 0.6.9 (2024-09-12)

- Clarify DST-related error messages (#169)

## 0.6.8 (2024-09-05)

- Fix object deallocation bug that caused a crash in rare cases (#167)

## 0.6.7 (2024-08-06)

- Add Python 3.13 binary wheels, now that its ABI is stable
- Small improvements to import speed

## 0.6.6 (2024-07-27)

- Fix potential memory leak in `.now()` if `time-machine` is used

## 0.6.5 (2024-07-27)

- `from_timestamp` now also accepts floats, to ease porting code from
  `datetime` (#159)
- Fixed incorrect fractional seconds when parsing negative values in
  `from_timestamp` methods.
- Fix some places where `ValueError` was raised instead of `TypeError`

## 0.6.4 (2024-07-26)

- Add helper `patch_current_time` for patching current time in whenever
  (only) (#147)
- Support patching the current time with
  [time-machine](https://github.com/adamchainz/time-machine) (#147)
- Remove undocumented `year`/`month`/`day`/`offset` properties from
  `Instant`
- Reduce size of binary distributions
- Clarify contribution guidelines

## 0.6.3 (2024-07-13)

- Improve robustness and speed of keyword argument parsing in Rust
  extension (#149)
- Add more answers to common questions in the docs and FAQ (#148, #150)

## 0.6.2 (2024-07-04)

- Add third-party licenses to distributions

## 0.6.1 (2024-07-04)

- Small updates to project metadata

## 0.6.0 (2024-07-04)

A big release touting a Rust extension module and an API more consistent
with other modern libraries.

**Added or improved**

- Implement as a Rust extension module, leading to a big speedup
- Add `replace_date` and `replace_time` methods to datetimes.
- Add `Date.MIN` and `Date.MAX` constants.
- `from_py_*` methods are more robust.
- The pickle format for most types is now more efficient.

**Breaking changes**

- `UTCDateTime` is now `Instant`. Removed methods that were specific to
  UTC.

  **Rationale**: `Instant` is simpler and more conceptually clear. It
  also avoids the mistake of performing calendar arithmetic in UTC.

- `NaiveDateTime` is now `LocalDateTime`

  **Rationale**: "Local" is more descriptive for describing the
  concept of "wall clock" time observed locally by humans. It\'s also
  consistent with other libraries and standards.

- Nanosecond precision is now the default for all datetimes and deltas.
  `nanosecond` is a keyword-only argument for all constructors, to
  prevent mistakes porting code from `datetime` (which uses
  microseconds).

  **Rationale**: Nanosecond precision is the standard for modern
  datetime libraries.

- Unified `[from_]canonical_format` methods with `[from_]common_iso8601`
  methods into `[format|parse]_common_iso` methods.

  **Rationale**: This cuts down on the number of methods; the
  performance benefits of separate methods aren\'t worth the clutter.

- Timestamp methods now use integers instead of floats. There are now
  separate methods for seconds, milliseconds, and nanoseconds.

  **Rationale**: This prevents loss of precision when converting to
  floats, and is more in line with other modern libraries.

- Renamed `[from_][rfc3339|rfc2822]` methods to
  `[format|parse]_[rfc3339|rfc2822]`.

  **Rationale**: Consistency with other methods.

- Added explicit `ignore_dst=True` flag to DST-unsafe operations such as
  shifting an offset datetime.

  **Rationale**: Previously, DST-unsafe operations were completely
  disallowed, but to a frustrating degree. This flag is a better
  alternative than having users resort to workarounds.

- Renamed `as_utc`, `as_offset`, `as_zoned`, `as_local` to `to_utc`,
  `to_fixed_offset`, `to_tz`, `to_system_tz`, and the
  `NaiveDateTime.assume_*` methods accordingly

  **Rationale**: "to" better clarifies a conversion is being made (not
  a replacement), and "fixed offset" and "tz" are more descriptive
  than "offset" and "zoned".

- `disambiguate=` is non-optional for all relevant methods. The only
  exception is the constructor, which defaults to "raise".

  **Rationale**: This makes it explicit how ambiguous and non-existent
  times are handled.

- Removed weakref support.

  **Rationale**: The overhead of weakrefs was too high for such
  primitive objects, and the use case was not clear.

- Weekdays are now an enum instead of an integer.

  **Rationale**: Enums are more descriptive and less error-prone,
  especially since ISO weekdays start at 1 and Python weekdays at 0.

- Calendar units in `Date[Time]Delta` can now only be retrieved
  together. For example, there is no `delta.months` or `delta.days`
  anymore, `delta.in_months_days()` should be used in this case.

  **Rationale**: This safeguards against mistakes like
  `(date1 - date2).days` which would only return the *days component* of
  the delta, excluding months. Having to call `in_months_days()` is more
  explicit that both parts are needed.

- Units in delta cannot be different signs anymore (after
  normalization).

  **Rationale**: The use case for mixed sign deltas (e.g. 2 months and
  -15 days) is unclear, and having a consistent sign makes it easier to
  reason about. It also aligns with the most well-known version of the
  ISO format.

- Calendar units are normalized, but only in so far as they can be
  converted strictly. For example, 1 year is always equal to 12 months,
  but 1 month isn\'t equal to a fixed number of days. Refer to the delta
  docs for more information.

  **Rationale**: This is more in line with `TimeDelta` which also
  normalizes.

- Renamed `AmbiguousTime` to `RepeatedTime`.

  **Rationale**: The new name is more descriptive for repeated times
  occurring twice due to DST. It also clarifies the difference between
  "repeated" times and "ambiguous" times (which can also refer to
  non-existent times).

- Dropped Python 3.8 support

  **Rationale**: Rust extension relies on C API features added in Python
  3.9. Python 3.8 will be EOL later this year.

## 0.5.1 (2024-04-02)

- Fix `LocalSystemDateTime.now()` not setting the correct offset (#104)

## 0.5.0 (2024-03-21)

**Breaking changes**

- Fix handling of `-0000` offset in RFC2822 format, which was not
  according to the standard. `NaiveDateTime` can now no longer be
  created from this format.
- `DateDelta` canonical format now uses `P` prefix.

**Improved**

- Add explicit ISO8601 formatting/parsing methods to datetimes, date,
  time, and deltas.
- Add missing `Date.from_canonical_format` method.
- Separate docs for deltas and datetimes.
- `NaiveDateTime.assume_offset` now also accepts integers as hour
  offsets.

## 0.4.0 (2024-03-13)

A big release with the main feature being the addition of date/time
deltas. I\'ve also tried to bundle as many small breaking changes as
possible into this release, to avoid having to do them in the future.

**Breaking changes**

- `LocalDateTime` renamed to `LocalSystemDateTime`.

  **Rationale**: The `LocalDateTime` name is used in other libraries for
  naive datetimes, and the new name is more explicit.

- `LocalSystemDateTime` no longer adjusts automatically to changes in
  the system timezone. Now, `LocalSystemDateTime` reflects the system
  timezone at the moment of instantiation. It can be updated explicitly.

  **Rationale**: The old behavior was dependent on too many assumptions,
  and behaved unintuitively in some cases. It also made the class
  dependent on shared mutable state, which made it hard to reason about.

- The `disambiguate=` argument now also determines how non-existent
  times are handled.

  **Rationale**: This makes it possible to handle both ambiguous and
  non-existent times gracefully and in a consistent way. This behavior
  is also more in line with the RFC5545 standard, and Temporal.

- `from_naive()` removed in favor of methods on `NaiveDateTime`. For
  example, `UTCDateTime.from_naive(n)` becomes `n.assume_utc()`.

  **Rationale**: It\'s shorter, and more explicit about assumptions.

- Renamed `ZonedDateTime.disambiguated()` to `.is_ambiguous()`.

  **Rationale**: The new name distinguishes it from the `disambiguate=`
  argument, which also affects non-existent times.

- Replaced `.py` property with `.py_datetime()` method.

  **Rationale**: Although it currently works fine as a property, this
  may be changed in the future if the library no longer contains a
  `datetime` internally.

- Removed properties that simply delegated to the underlying `datetime`
  object: `tzinfo`, `weekday`, and `fold`. `date` and `time` now return
  `whenever.Date` and `whenever.Time` objects.

  **Rationale**: Removing these properties makes it possible to create
  improved versions. If needed, these properties can be accessed from
  the underlying datetime object with `.py_datetime()`.

- Renamed `.canonical_str()` to `.canonical_format()`.

  **Rationale**: A more descriptive name.

- Renamed `DoesntExistInZone` to `SkippedTime`, `Ambiguous` to
  `AmbiguousTime`.

  **Rationale**: The new names are shorter and more consistent.

- Renamed `min` and `max` to `MIN` and `MAX`.

  **Rationale**: Consistency with other uppercase class constants

**Improved**

- Added a `disambiguation="compatible"` option that matches the behavior
  of other languages and the RFC5545 standard.
- Shortened the `repr()` of all types, use space separator instead of
  `T`.
- Added `sep="T" or " "` option to `canonical_format()`
- `OffsetDateTime` constructor and methods creating offset datetimes now
  accept integers as hour offsets.
- Added `Date` and `Time` classes for working with dates and times
  separately.

## 0.3.4 (2024-02-07)

- Improved exception messages for ambiguous or non-existent times
  (#26)

## 0.3.3 (2024-02-04)

- Add CPython-maintained `tzdata` package as Windows dependency (#32)

## 0.3.2 (2024-02-03)

- Relax overly strict Python version constraint in package metadata
  (#33)

## 0.3.1 (2024-02-01)

- Fix packaging metadata issue involving README and CHANGELOG being
  installed in the wrong place (#23)

## 0.3.0 (2024-01-23)

**Breaking changes**

- Change pickle format so that backwards-compatible unpickling is
  possible in the future.

**Added**

- Added `strptime()` to `UTCDateTime`, `OffsetDateTime` and
  `NaiveDateTime`.
- Added `rfc2822()`/`from_rfc2822()` to `UTCDateTime`,
  `OffsetDateTime` and `NaiveDateTime`.
- Added `rfc3339()`/`from_rfc3339()` to `UTCDateTime` and
  `OffsetDateTime`

## 0.2.1 (2024-01-20)

- added `days()` timedelta alias
- Improvements to README, other docs

## 0.2.0 (2024-01-10)

**Breaking changes**

- Disambiguation of local datetimes is now consistent with zoned
  datetimes, and is also run on `replace()`.
- Renamed:
  - `from_str` → `from_canonical_str`
  - `to_utc/offset/zoned/local` → `as_utc/offset/zoned/local`.
  - `ZonedDateTime.zone` → `ZonedDateTime.tz`

**Added**

- Support comparison between all aware datetimes
- upport subtraction between all aware datetimes
- Convenience methods for converting between aware/naive
- More robust handling of zoned/local edge cases

**Docs**

- Cleaned up API reference
- Added high-level overview

## 0.1.0 (2023-12-20)

- Implement `OffsetDateTime`, `ZonedDateTime` and `LocalDateTime`

## 0.0.4 (2023-11-30)

- Revert to pure Python implementation, as Rust extension
  disadvantages outweigh its advantages
- Implement `NaiveDateTime`

## 0.0.3 (2023-11-16)

- Implement basic `UTCDateTime`

## 0.0.2 (2023-11-10)

- Empty release with Rust extension module

## 0.0.1

- Dummy release
