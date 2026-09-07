# System timezone is requested by a sentinel

`SYSTEM_TZ` is a public sentinel accepted wherever a timezone ID is:
`ZonedDateTime(..., tz=SYSTEM_TZ)`, `now()`, `to_tz()`, `assume_tz()`,
`replace()`, and `Date.today()`. It is resolved when the call is made, and
the result stores the resolved timezone, never the sentinel. In 0.11 it
replaces the system-specific method family (`to_system_tz()`,
`assume_system_tz()`, `from_system_tz()`, `now_in_system_tz()`,
`today_in_system_tz()`), which is deprecated and removed in 1.0. The
user-facing reasons for making the system timezone explicit at all are in
`docs/design.md` and the stdlib-pitfalls pages; this record covers only the
choice of spelling.

## Semantics

- `SYSTEM_TZ` is a singleton whose repr is `SYSTEM_TZ`. It compares by
  identity, and `copy`, `deepcopy`, and pickle return the same object. The
  stub types it as a PEP 661 sentinel and writes `str | SYSTEM_TZ` in
  signatures.
- Resolution reads a cache that only `reset_system_tz()` refreshes. A value
  built earlier keeps the timezone it was built with.
- A system timezone with no timezone ID (a POSIX TZ string, a TZif file
  outside a zoneinfo directory) yields a `ZonedDateTime` whose `tz_id` is
  `None`.
- When the system timezone cannot be resolved (missing or invalid file,
  unknown key, invalid POSIX string), both backends raise
  `TimeZoneNotFoundError`. A failed `reset_system_tz()` leaves the cache as
  it was.

## Considered options

- **`tz=None` means the system timezone.** Rejected: the system timezone
  becoming implicit is the standard-library behavior the library exists to
  avoid, and `None` reads as "no timezone" rather than "this machine's".
  `None` is also invalid everywhere else it is not an accepted value.
- **A reserved string** such as `"local"` or `"system"`. Rejected: a
  timezone ID is a string too, so the reserved word could collide with a
  real or future ID, and `tz_id`, `parse_iso()`, and `format_iso()` would
  each need a carve-out for a string that is not an ID. It would also invite
  writing `[local]` in an ISO string, which nothing else can read.
- **A timezone object** holding the resolved rules, passable where an ID is.
  Deferred, not rejected: a public timezone type is a larger API than 1.0
  wants to commit to. The sentinel does not preclude adding one later.
- **The dedicated method family** (the pre-0.11 state). Rejected: every
  operation that takes a timezone needs a system-specific twin, and the
  twins are the only place where the timezone is not an argument.

## Consequences

- No signature has a system-timezone default. A dependency on the machine's
  configuration is visible at the call site as `SYSTEM_TZ`.
- The `valid-type` ignores on `str | SYSTEM_TZ` in the stub stay until a mypy
  release accepts a PEP 661 sentinel as a type.
- `reset_system_tz()` is the only way to observe a changed system timezone.
  A test helper that sets the cache directly is additive, post-1.0 work.
