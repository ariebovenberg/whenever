🚀 Changelog
============

0.6.14 (2024-11-27)
-------------------

**Fixed**

- Ensure docstrings and error messages are consistent in Rust extension
  as well as the pure-Python version
- Remove ondocumented properties ``hour/minute/etc`` from ``Instant``
  that were accidentally left in the Rust extension.
- ``exact_eq()`` now also raises ``TypeError`` in the pure Python version
  when comparing different types.

0.6.13 (2024-11-17)
-------------------

**Added**

- Make ``from_py_datetime()`` on ``Instant``/``OffsetDateTime`` less pedantic.
  They now accept any aware datetime
- New ``Date.today_in_system_tz()`` convenience method

**Fixed**

- Parsing UTC offsets with out-of-range minute components (e.g. ``06:79``)
  now raises the expected parsing failure.
- Note in ``parse_rfc2822()`` docstring that it doesn't (yet) validate the input,
  due to limitations in the underlying parser.

0.6.12 (2024-11-08)
-------------------

- Fixed ``format_rfc3339()`` docstrings that incorrectly included a ``T`` separator.
  Clarified that ``T`` can be added by using the ``format_common_iso()`` method instead. (#185)

0.6.11 (2024-11-04)
-------------------

**Added**

- Added ``YearMonth`` and ``MonthDay`` classes for working with year-month and month-day pairs

**Fixed**

- ``whenever.__version__`` is now also accessible when Rust extension is used

0.6.10 (2024-10-30)
-------------------

**Improved**

- Improve method documentation and autocomplete support (#172, #173, #176)

**Fixed**

- Remove lingering undocumented ``offset`` on ``Instant``
- Fix incorrect ``LocalDateTime.difference`` return type annotation

0.6.9 (2024-09-12)
------------------

- Clarify DST-related error messages (#169)

0.6.8 (2024-09-05)
------------------

- Fix object deallocation bug that caused a crash in rare cases (#167)

0.6.7 (2024-08-06)
------------------

- Add Python 3.13 binary wheels, now that its ABI is stable
- Small improvements to import speed

0.6.6 (2024-07-27)
------------------

- Fix potential memory leak in ``.now()`` if ``time-machine`` is used

0.6.5 (2024-07-27)
------------------

- ``from_timestamp`` now also accepts floats, to ease porting code from ``datetime`` (#159)
- Fixed incorrect fractional seconds when parsing negative values in ``from_timestamp`` methods.
- Fix some places where ``ValueError`` was raised instead of ``TypeError``

0.6.4 (2024-07-26)
------------------

- Add helper ``patch_current_time`` for patching current time in whenever (only) (#147)
- Support patching the current time with `time-machine <https://github.com/adamchainz/time-machine>`_ (#147)
- Remove undocumented ``year``/``month``/``day``/``offset`` properties from ``Instant``
- Reduce size of binary distributions
- Clarify contribution guidelines

0.6.3 (2024-07-13)
------------------

- Improve robustness and speed of keyword argument parsing in Rust extension (#149)
- Add more answers to common questions in the docs and FAQ (#148, #150)

0.6.2 (2024-07-04)
------------------

- Add third-party licenses to distributions

0.6.1 (2024-07-04)
------------------

- Small updates to project metadata

0.6.0 (2024-07-04)
------------------

A big release touting a Rust extension module
and an API more consistent with other modern libraries.

**Added or improved**

- Implement as a Rust extension module, leading to a big speedup
- Add ``replace_date`` and ``replace_time`` methods to datetimes.
- Add ``Date.MIN`` and ``Date.MAX`` constants.
- ``from_py_*`` methods are more robust.
- The pickle format for most types is now more efficient.

**Breaking changes**

- ``UTCDateTime`` is now ``Instant``. Removed methods that were specific to UTC.

  **Rationale**: ``Instant`` is simpler and more conceptually clear.
  It also avoids the mistake of performing calendar arithmetic in UTC.

- ``NaiveDateTime`` is now ``LocalDateTime``

  **Rationale**: "Local" is more descriptive for describing the concept of
  "wall clock" time observed locally by humans. It's also consistent with
  other libraries and standards.

- Nanosecond precision is now the default for all datetimes and deltas.
  ``nanosecond`` is a keyword-only argument for all constructors,
  to prevent mistakes porting code from ``datetime`` (which uses microseconds).

  **Rationale**: Nanosecond precision is the standard for modern datetime libraries.

- Unified ``[from_]canonical_format`` methods with ``[from_]common_iso8601`` methods
  into ``[format|parse]_common_iso`` methods.

  **Rationale**: This cuts down on the number of methods; the performance benefits
  of separate methods aren't worth the clutter.

- Timestamp methods now use integers instead of floats. There
  are now separate methods for seconds, milliseconds, and nanoseconds.

  **Rationale**: This prevents loss of precision when converting to floats,
  and is more in line with other modern libraries.

- Renamed ``[from_][rfc3339|rfc2822]`` methods to ``[format|parse]_[rfc3339|rfc2822]``.

  **Rationale**: Consistency with other methods.

- Added explicit ``ignore_dst=True`` flag to DST-unsafe operations such as
  shifting an offset datetime.

  **Rationale**: Previously, DST-unsafe operations were completely disallowed,
  but to a frustrating degree. This flag is a better alternative than having
  users resort to workarounds.

- Renamed ``as_utc``, ``as_offset``, ``as_zoned``, ``as_local`` to
  ``to_utc``, ``to_fixed_offset``, ``to_tz``, ``to_system_tz``,
  and the ``NaiveDateTime.assume_*`` methods accordingly

  **Rationale**: "to" better clarifies a conversion is being made (not a replacement),
  and "fixed offset" and "tz" are more descriptive than "offset" and "zoned".

- ``disambiguate=`` is non-optional for all relevant methods.
  The only exception is the constructor, which defaults to "raise".

  **Rationale**: This makes it explicit how ambiguous and non-existent times are handled.

- Removed weakref support.

  **Rationale**: The overhead of weakrefs was too high for
  such primitive objects, and the use case was not clear.

- Weekdays are now an enum instead of an integer.

  **Rationale**: Enums are more descriptive and less error-prone,
  especially since ISO weekdays start at 1 and Python weekdays at 0.

- Calendar units in ``Date[Time]Delta`` can now only be retrieved together.
  For example, there is no ``delta.months`` or ``delta.days`` anymore,
  ``delta.in_months_days()`` should be used in this case.

  **Rationale**: This safeguards against mistakes like ``(date1 - date2).days``
  which would only return the *days component* of the delta, excluding months.
  Having to call ``in_months_days()`` is more explicit that both parts are needed.

- Units in delta cannot be different signs anymore (after normalization).

  **Rationale**: The use case for mixed sign deltas (e.g. 2 months and -15 days) is unclear,
  and having a consistent sign makes it easier to reason about.
  It also aligns with the most well-known version of the ISO format.

- Calendar units are normalized, but only in so far as they can be converted
  strictly. For example, 1 year is always equal to 12 months, but 1 month
  isn't equal to a fixed number of days. Refer to the delta docs for more information.

  **Rationale**: This is more in line with ``TimeDelta`` which also normalizes.

- Renamed ``AmbiguousTime`` to ``RepeatedTime``.

  **Rationale**: The new name is more descriptive for repeated times
  occurring twice due to DST. It also clarifies the difference between
  "repeated" times and "ambiguous" times (which can also refer to non-existent times).

- Dropped Python 3.8 support

  **Rationale**: Rust extension relies on C API features added in Python 3.9.
  Python 3.8 will be EOL later this year.

0.5.1 (2024-04-02)
------------------

- Fix ``LocalSystemDateTime.now()`` not setting the correct offset (#104)

0.5.0 (2024-03-21)
------------------

**Breaking changes**

- Fix handling of ``-0000`` offset in RFC2822 format, which was not according
  to the standard. ``NaiveDateTime`` can now no longer be created from this format.
- ``DateDelta`` canonical format now uses ``P`` prefix.

**Improved**

- Add explicit ISO8601 formatting/parsing methods to datetimes, date, time, and deltas.
- Add missing ``Date.from_canonical_format`` method.
- Separate docs for deltas and datetimes.
- ``NaiveDateTime.assume_offset`` now also accepts integers as hour offsets.

0.4.0 (2024-03-13)
------------------

A big release with the main feature being the addition of date/time deltas.
I've also tried to bundle as many small breaking changes as possible into
this release, to avoid having to do them in the future.

**Breaking changes**

- ``LocalDateTime`` renamed to ``LocalSystemDateTime``.

  **Rationale**: The ``LocalDateTime`` name is used in other libraries for
  naive datetimes, and the new name is more explicit.

- ``LocalSystemDateTime`` no longer adjusts automatically to changes in the system
  timezone. Now, ``LocalSystemDateTime`` reflects the system timezone at the moment
  of instantiation. It can be updated explicitly.

  **Rationale**: The old behavior was dependent on too many assumptions, and
  behaved unintuitively in some cases. It also made the class dependent on
  shared mutable state, which made it hard to reason about.

- The ``disambiguate=`` argument now also determines how non-existent times
  are handled.

  **Rationale**: This makes it possible to handle both ambiguous and
  non-existent times gracefully and in a consistent way.
  This behavior is also more in line with the RFC5545 standard,
  and Temporal.

- ``from_naive()`` removed in favor of methods on ``NaiveDateTime``.
  For example, ``UTCDateTime.from_naive(n)`` becomes ``n.assume_utc()``.

  **Rationale**: It's shorter, and more explicit about assumptions.

- Renamed ``ZonedDateTime.disambiguated()`` to ``.is_ambiguous()``.

  **Rationale**: The new name distinguishes it from the ``disambiguate=``
  argument, which also affects non-existent times.

- Replaced ``.py`` property with ``.py_datetime()`` method.

  **Rationale**: Although it currently works fine as a property, this
  may be changed in the future if the library no longer contains
  a ``datetime`` internally.

- Removed properties that simply delegated to the underlying ``datetime`` object:
  ``tzinfo``, ``weekday``, and ``fold``. ``date`` and ``time`` now
  return ``whenever.Date`` and ``whenever.Time`` objects.

  **Rationale**: Removing these properties makes it possible to create improved
  versions. If needed, these properties can be accessed from the
  underlying datetime object with ``.py_datetime()``.

- Renamed ``.canonical_str()`` to ``.canonical_format()``.

  **Rationale**: A more descriptive name.

- Renamed ``DoesntExistInZone`` to ``SkippedTime``, ``Ambiguous`` to
  ``AmbiguousTime``.

  **Rationale**: The new names are shorter and more consistent.

- Renamed ``min`` and ``max`` to ``MIN`` and ``MAX``.

  **Rationale**: Consistency with other uppercase class constants

**Improved**

- Added a ``disambiguation="compatible"`` option that matches the behavior of
  other languages and the RFC5545 standard.
- Shortened the ``repr()`` of all types, use space separator instead of ``T``.
- Added ``sep="T" or " "`` option to ``canonical_format()``
- ``OffsetDateTime`` constructor and methods creating offset datetimes now accept
  integers as hour offsets.
- Added ``Date`` and ``Time`` classes for working with dates and times separately.

0.3.4 (2024-02-07)
------------------

- 🏷️ Improved exception messages for ambiguous or non-existent times (#26)

0.3.3 (2024-02-04)
------------------

- 💾 Add CPython-maintained ``tzdata`` package as Windows dependency (#32)

0.3.2 (2024-02-03)
------------------

- 🔓 Relax overly strict Python version constraint in package metadata (#33)

0.3.1 (2024-02-01)
------------------

- 📦 Fix packaging metadata issue involving README and CHANGELOG being
  installed in the wrong place (#23)

0.3.0 (2024-01-23)
------------------

**Breaking changes**

- 🥒 Change pickle format so that backwards-compatible unpickling is possible
  in the future.

**Added**

- 🔨 Added ``strptime()`` to ``UTCDateTime``, ``OffsetDateTime`` and
  ``NaiveDateTime``.
- 📋 Added ``rfc2822()``/``from_rfc2822()`` to ``UTCDateTime``,
  ``OffsetDateTime`` and ``NaiveDateTime``.
- ⚙️ Added ``rfc3339()``/``from_rfc3339()`` to ``UTCDateTime`` and ``OffsetDateTime``

0.2.1 (2024-01-20)
------------------

- added ``days()`` timedelta alias
- Improvements to README, other docs

0.2.0 (2024-01-10)
------------------

**Breaking changes**

- 📐Disambiguation of local datetimes is now consistent with zoned datetimes,
  and is also run on ``replace()``.
- 👌Renamed:

  - ``from_str`` → ``from_canonical_str``
  - ``to_utc/offset/zoned/local`` → ``as_utc/offset/zoned/local``.
  - ``ZonedDateTime.zone`` → ``ZonedDateTime.tz``

**Added**

- ⚖️ Support comparison between all aware datetimes
- 🧮Support subtraction between all aware datetimes
- 🍩 Convenience methods for converting between aware/naive
- 💪 More robust handling of zoned/local edge cases

**Docs**

- Cleaned up API reference
- Added high-level overview

0.1.0 (2023-12-20)
------------------

- 🚀 Implement ``OffsetDateTime``, ``ZonedDateTime`` and ``LocalDateTime``

0.0.4 (2023-11-30)
------------------

- 🐍 Revert to pure Python implementation, as Rust extension disadvantages
  outweigh its advantages
- ☀️ Implement ``NaiveDateTime``

0.0.3 (2023-11-16)
------------------

- 🌐 Implement basic ``UTCDateTime``

0.0.2 (2023-11-10)
------------------

- ⚙️ Empty release with Rust extension module

0.0.1
-----

- 📦 Dummy release
