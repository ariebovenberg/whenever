Changelog
=========

0.2.0 (202?-??-??)
------------------

**Breaking changes**

- 📐Disambiguation is now consistent in local and zoned datetimes,
    and is also run on ``replace()``.
- 👌Renames: ``from_str``-> ``from_canonical_str`` and
  ``to_utc/offset/zoned/local``-> ``as_utc/offset/zoned/local``.

**Added**

- ⚖️ Support comparison between all aware datetimes
- ⏱️ Support subtraction between all aware datetimes
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
