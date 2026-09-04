---
myst:
  html_meta:
    description: >-
      The canonical vocabulary of whenever: one line per term, the words it is
      preferred over, and a link to the page that explains the concept.
---

(glossary)=
# Glossary

The words this project uses, and the ones it does not. Each entry links to
the page that explains the concept; this page only settles the name.

```{glossary}
exact time
  A single moment on the global timeline, independent of any time zone.
  `Instant`, `OffsetDateTime`, and `ZonedDateTime` represent one.
  Preferred over *absolute time* and *UTC time*.
  See {ref}`Exact time vs local time <exact-vs-local>`.

local time
  A clock and calendar reading as seen in a particular place.
  `PlainDateTime`, `Date`, and `Time` represent one.
  Preferred over *civil time* and *wall-clock time*.
  See {ref}`Exact time vs local time <exact-vs-local>`.

exact units
  Units of fixed duration: hours, minutes, seconds, and smaller.
  See {ref}`Date-time arithmetic <arithmetic2>`.

calendar units
  Units defined by the calendar and the local clock, with no fixed duration:
  days, weeks, months, and years.
  See {ref}`Date-time arithmetic <arithmetic2>`.

strict equality
  Equality that also compares what `==` deliberately ignores: the argument's
  type, the offset, the timezone, or a component given explicitly as zero.
  Provided by `strict_eq()` on exactly the types whose `==` ignores something.
  Preferred over *exact equality*.
  See {doc}`guide/comparison`.

timestamp
  A count of whole units since the UNIX epoch (1970-01-01 00:00 UTC):
  seconds by default, or milliseconds, microseconds, or nanoseconds via
  `unit=`. Floored at the unit, so it labels the bucket containing the
  instant. An ISO 8601 string is not a timestamp.
  Preferred over *UNIX time*, *epoch time*, and *POSIX time*.
  See {ref}`timestamps`.

ISO 8601 string
  The text form of a value, as produced by `format_iso()` and accepted by
  `parse_iso()`. "ISO 8601 format" names the format itself.
  Preferred over *ISO timestamp* and *ISO datetime*; *ISO string* is the
  short form.
  See {ref}`iso8601`.
```
