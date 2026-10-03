# Contributor glossary

Vocabulary for code, tests, plans, and agent instructions that a user of the
library never needs. This page is excluded from the docs build and from the
llms summaries. A term belongs in `docs/glossary.md` instead when it appears
in a warning message, a docs page, or a public name.

Same rules as the public glossary: use the headword in code, comments, and
messages; the "preferred over" words are rejected synonyms.

**compatibility shim** (public glossary)
: A deprecated pattern spelling is one too. 1.0 has none; the term stays
  for the next deprecation cycle.

**field**
: The value a specifier sets: year, month, day, weekday, hour, minute,
  second, nanoseconds, offset, or time zone ID. Category validation and
  duplicate detection reason about fields; a message shown to a user names
  the specifier instead.
  Preferred over *slot*, *component*, and *state key*.

**boundary method**
: One of `start_of()`, `end_of()`, `round()`, and `day_length()` on
  `ZonedDateTime`: a method that computes a unit boundary rather than
  resolving a caller-supplied local time, and therefore takes no
  disambiguation policy (ADR 0003).
  Preferred over *truncation method* and *snapping method*.

**omitted**
: Said of an argument the caller did not pass. Omission is distinct from
  every accepted value, including `None`; where it has its own meaning, the
  runtime default is the private sentinel spelled `UNSET`
  (`pysrc/whenever/_common.py`). `None` is accepted as a value only where
  absence is itself a value: an itemized delta component, removed with
  `replace(x=None)`.
  Preferred over *unset*, *missing*, and *not specified*.

**pin**
: The instant a time patch anchors the clock to: the whole clock for a
  frozen patch, the value at the moment it was set for a ticking one.
  Spelled `_pin` in `pysrc/whenever/_utils.py` and `pin` in the Rust
  `PatchState`.
  Preferred over *anchor*, *base*, and *origin*.
