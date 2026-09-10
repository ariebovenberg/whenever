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

timezone ID
  The IANA name of a timezone's rules, such as `Europe/Paris`. Exposed as
  `tz_id` and written in brackets in an ISO 8601 string. The system timezone
  may lack one.
  Preferred over *IANA identifier*, *timezone name*, *timezone key*, and
  *tz*.
  See {ref}`timezone-database`.

system timezone
  The timezone the operating system is configured with. Requested with
  `SYSTEM_TZ` wherever a timezone ID is accepted. Each call resolves it and
  stores the result in the returned value, which keeps that timezone for
  good; `reset_system_tz()` changes only what later calls resolve to. It may
  have no timezone ID.
  Preferred over *local timezone*, *local zone*, *machine timezone*, and
  *OS timezone*.
  See {ref}`systemtime`.

repeated local time
  A local time that occurs twice in a timezone because the clock moved
  backward. Resolved by a disambiguation policy.
  Preferred over *fold* and *ambiguous time*.
  See {ref}`ambiguity`.

skipped local time
  A local time that does not occur in a timezone because the clock moved
  forward. Resolved by a disambiguation policy.
  Preferred over *gap* and *non-existent time*.
  See {ref}`ambiguity`.

disambiguation
  The policy that picks the instant for a repeated or skipped local time in
  a named timezone: `"compatible"`, `"earlier"`, `"later"`, or `"raise"`.
  Passed as `disambiguation=`; when omitted, `"compatible"` applies with an
  `ImplicitDisambiguationWarning`.
  Preferred over *disambiguate*, *ambiguity policy*, and *fold handling*.
  See {ref}`ambiguity`.

offset mismatch
  A numeric offset in the input that identifies no occurrence of the written
  local time in the named timezone. Resolved by `offset_mismatch=`, before
  disambiguation can apply.
  Preferred over *offset conflict* and *offset disagreement*.
  See {ref}`offset-mismatch`.

offset-preserving resolution
  How `replace()` and calendar arithmetic on a `ZonedDateTime` resolve their
  result: the current offset is kept when it is still valid for the new local
  time, and disambiguation applies otherwise.
  Preferred over *keep offset* and *sticky offset*.
  See {ref}`offset-preserving`.

stale offset
  The offset an `OffsetDateTime` carries after an operation moved the value:
  still the observed offset, but no longer certain to be the one the source
  timezone would apply. Flagged by `StaleOffsetWarning`.
  Preferred over *wrong offset* and *outdated offset*.
  See {ref}`offset-datetime-guidance`.

time patch
  A test-only override of the current time as Whenever sees it, created by
  `patch_current_time()` and driven through its `TimePatch` handle. Either
  frozen (holds one instant) or ticking (advances from it).
  Preferred over *mocked time*, *fake clock*, and *frozen time* as the
  general term.
  See {doc}`guide/testing`.

pattern
  A string of specifiers and literal text that `format()` writes and
  `parse()` reads, passed as `pattern=`. The canonical full pattern is
  `YYYY-MM-DD HH:mm:ss`.
  Preferred over *format string*, *format*, and *custom format*.
  See {ref}`pattern-format`.

specifier
  A run of one letter in a pattern that stands for one value, such as `HH`
  or `MMM`. Two specifiers cannot set the same value.
  Preferred over *pattern letter*, *token*, *directive*, and *format code*.
  See {ref}`pattern-format`.

optional seconds
  The bracketed group after the minutes in a pattern, `[ss]` or `[:ss]` with
  an optional fraction, written only when seconds or nanoseconds are nonzero.
  Brackets have no other use in a pattern.
  Preferred over *optional group*, *bracket group*, and *seconds tail*.
  See {ref}`pattern-format`.

24-hour clock
  Hours 0 through 23, written with the `H`/`HH` specifiers.
  Preferred over *24-hour format* and *24-hour time*.
  See {ref}`pattern-format`.

12-hour clock
  Hours 1 through 12 together with an AM/PM specifier, written with `i`/`ii`
  and `a`/`aa`. A pattern with one but not the other warns.
  Preferred over *12-hour format*, *12-hour time*, and *AM/PM time*.
  See {ref}`pattern-format`.

itemized delta
  A delta that keeps every component as it was given: `ItemizedDelta` and
  `ItemizedDateDelta`. Ninety minutes stays ninety minutes.
  Preferred over *unnormalized delta*, *period*, and *span*.
  See {ref}`delta-norm`.

normalized delta
  A delta reduced to one exact duration, whatever components built it:
  `TimeDelta`. Ninety minutes and an hour and a half are the same value.
  Preferred over *duration* as a type name.
  See {ref}`delta-norm`.

component
  One unit's value in an itemized delta, such as `months` or `nanoseconds`.
  A component is present when the delta was given it, an explicit zero
  included; `==` ignores presence, iteration and `strict_eq()` do not.
  Preferred over *field* and *part*.
  See {ref}`delta-norm`.

balancing
  Redistributing a delta over a chosen set of units with `in_units()`, such
  as 150 minutes into 2 hours and 30 minutes. Calendar units need a
  `relative_to` reference.
  Preferred over *normalizing into units* and *rebalancing*.
  See {ref}`delta-in-units`.

component-wise composition
  Adding or subtracting two itemized deltas by combining like components,
  which is what `+`, `-`, and `add()`/`subtract()` without `relative_to`
  do. Flagged by `CalendarUnitCompositionWarning` when a calendar unit is
  involved. Passing `relative_to=` gives calendar-aware composition instead.
  Preferred over *field-wise composition* and *literal addition*.
  See {ref}`delta-add-sub`.

partial type
  A type that holds part of a datetime: `Date`, `Time`, `YearMonth`,
  `MonthDay`, and `IsoWeekDate`. *Partial* is the short form.
  Preferred over *smaller types*, *date-only types*, and *component types*.
  See {ref}`partial-api`.
```
