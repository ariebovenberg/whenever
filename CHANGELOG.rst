🚀 Changelog
============

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
