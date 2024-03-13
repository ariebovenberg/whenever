🚀 Changelog
============

0.4.0rc0 (2024-02-??)
---------------------

A big release with many small breaking changes, and a few new features.

**Breaking changes**

- ``LocalDateTime`` no longer adjusts automatically to changes in the system
  timezone. Now, ``LocalDateTime`` reflects the system timezone at the moment
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

- Rename ``ZonedDateTime.disambiguated()`` to ``.ambiguous()``.

  **Rationale**: The new name distinguishes it from the ``disambiguate=``
  argument, which also affects non-existent times.

- Made ``.py()`` a method instead of a property.

  **Rationale**: Although it currently works fine as a property, this
  may be changed in the future if the library no longer wraps a ``datetime``,
  or arguments are needed.

- Removed properties that simply delegated to the underlying ``datetime`` object:
  ``tzinfo``, ``date``, ``time``, ``weekday``, and ``fold``.

  **Rationale**: Removing these properties makes it possible to create improved
  versions in the future. If needed, these properties can be accessed from the
  underlying datetime object with ``.py()``: ``.weekday`` becomes ``.py().weekday``.


**Improved**

- Added a ``disambiguation="compatible"`` option that matches the behavior of
  other languages and the RFC5545 standard.
- Shortened the ``repr()`` of all types, use space separator instead of ``T``.
- Added ``sep="T" or " "`` option to ``canonical_str()``

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
