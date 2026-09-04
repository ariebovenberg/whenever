# Strict equality

`==` on the exact-time types compares the moment in time, across `Instant`,
`OffsetDateTime`, and `ZonedDateTime`. On itemized deltas it treats an explicit
zero as a missing component. The method that also compares what `==` ignores
was called `exact_eq()`. It is renamed to `strict_eq()` in 0.11, with
`exact_eq()` deprecated and removed in 1.0, because **exact** is reserved in
this project for *exact time* and *exact units*: `exact_eq()` named the
comparison that `==` already performs.

## Semantics

`strict_eq()` refines `==`: if `a.strict_eq(b)` holds, so does `a == b`, never
the converse. It exists only on types whose `==` ignores something, and
compares exactly that in addition:

- `Instant`: the argument's type.
- `OffsetDateTime`: the type, the local datetime, and the offset.
- `ZonedDateTime`: the type, the local datetime, the offset, and the timezone,
  meaning its identifier (or the absence of one, for the system timezone) and
  its definition.
- `ItemizedDelta` and `ItemizedDateDelta`: the type, and whether each
  component was given explicitly.

Types whose `==` already compares every field (`PlainDateTime`, `Date`,
`Time`, `TimeDelta`, `YearMonth`, `MonthDay`, `IsoWeekDate`) have no
`strict_eq()`.

## Considered options

- **Return `False` for a different type**, following the `NotImplemented`
  convention of `==`. Rejected: a cross-type call is nearly always a mistake,
  such as comparing a `ZonedDateTime` to the `Instant` it was built from, and
  `strict_eq()` exists to surface subtle differences, not to hide the coarsest
  one. It raises `TypeError` instead.
- **Compare timezones by identifier only.** Rejected: after `clear_tzcache()`
  or `reset_tzpath()`, two values with the same identifier can carry different
  rules and behave differently under arithmetic. Values that behave
  differently must not be strictly equal. Jiff makes the same choice. Without
  cache clears this reduces to comparing identifiers, so the common case pays
  nothing.
- **Compare timezones by object identity.** Rejected: equality would depend
  on cache state, which cannot be read off the two values.

## Consequences

- The pure-Python `ZonedDateTime.strict_eq()` compares the instant, the
  nanoseconds and the timezone, where the Rust extension compares the local
  datetime, the offset, the nanoseconds and the timezone. Both satisfy the
  contract above, because they agree on every value that can be built: the
  offset is always resolved from the timezone, so an equal instant and an equal
  timezone imply an equal offset and therefore an equal local datetime. Only a
  value whose offset is stale relative to its own timezone would separate them,
  and no constructor produces one—the pickle reader warns and corrects. The
  Python backend keeps the cheaper comparison, and no test pins the difference,
  because none can.
- `clear_tzcache()` keeps its caveat that `strict_eq()` can become false
  between values with the same timezone identifier.
