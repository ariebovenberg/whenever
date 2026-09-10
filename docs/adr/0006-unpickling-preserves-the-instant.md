# Unpickling preserves the instant

A `ZonedDateTime` pickle stores the local fields, the nanoseconds, the
offset that was observed, and the timezone ID. It does not store the
timezone's rules. When the pickle is loaded, the stored offset may no longer
be what the rules in the loading environment give for that local time: the
timezone database was updated, or the pickle crossed machines. That is an
**offset mismatch** in the glossary's sense, arriving through `pickle.loads()`
instead of `parse_iso()`. The unpickler resolves it as `keep_instant`: it
recovers the instant from the stored local fields and offset, resolves that
instant with the current rules, and emits `PickleOffsetMismatchWarning` when
the resulting offset differs from the stored one. The value that comes back
never carries an offset its own timezone rules contradict.

## Semantics

- Decode the stored local fields, nanoseconds, offset, and timezone ID;
  reject malformed payloads, unknown timezone IDs, and out-of-range values
  with the exceptions that already apply.
- Recover the original instant from the stored local fields and offset.
- Resolve that instant with the current rules for the timezone ID. No
  disambiguation policy is consulted: an instant identifies one occurrence.
- Emit `PickleOffsetMismatchWarning` after the value is built, only when the
  resolved offset differs from the stored one. The message names the
  timezone ID, the stored and current offsets, the stored and resulting
  local datetimes, and states that the instant was preserved.
- Unchanged rules give no warning and a value that is `strict_eq()` to the
  one pickled. Python and Rust pickles are mutually readable.
- `PickleOffsetMismatchWarning` subclasses `WheneverWarning` directly, not
  `PotentialDstBugWarning`: it reports drift between two environments'
  timezone data, not a mistake in the user's code. A test suite that turns
  the DST-bug family into errors must not fail every unpickle after a
  timezone-data update.

## Considered options

- **Raise on mismatch.** Rejected: most callers want the sensible default,
  and the warning already gives the strict callers what they want by
  turning it into an error with a warnings filter.
- **`keep_local`**: keep the stored local time and take whatever offset the
  current rules give it. Rejected: a pickle records a moment that happened
  or is scheduled; the local reading was derived from it under the rules of
  the time. Silently moving the moment to keep the reading is the failure
  mode `ZonedDateTime` exists to prevent.
- **A configurable policy.** Rejected: `pickle.loads()` is not a call site
  the library owns, so there is nowhere to pass `offset_mismatch=`. A
  process-wide setting (a `ContextVar`) would be needed only to support
  `keep_local`, which the option above rejects.
- **Embed a snapshot of the rules in the payload.** Rejected: it makes every
  pickle carry a copy of the timezone data, the loaded value would then
  disagree under arithmetic with values built in the same process, and
  `strict_eq()` compares timezone definitions, so the copy would never be
  strictly equal to anything.
- **Store the instant instead of the local fields and offset.** Rejected: a
  new payload format for no gain, since the instant is recoverable from the
  current payload, and every pickle written by 0.8 through 0.10 would need
  a second reader kept alongside.

## Consequences

- The reconciliation is a bug fix, not a format change: the 0.11 reader
  loads every payload the 0.10 reader did. Before 0.11 the reader could
  produce a value whose stored offset contradicted its rules, which is the
  one case that would separate the Python and Rust `strict_eq()` (ADR 0001).
- The `ZonedDateTime` payload fields are retained. That is not a general
  promise about historical formats: 1.0 reads pickles written by 0.8.0 or
  later and drops the pre-0.8 `Instant` reader (`_unpkl_utc`).
- The warning is attributed to the frame that called `pickle.loads()`: the
  pure-Python unpickler uses `stacklevel=2` and the Rust one level 1,
  because the C pickle machinery adds no Python frame.
- A `ContextVar`-based policy remains possible as additive, post-1.0 work
  if `keep_local` is ever wanted; nothing in the payload or the reader
  precludes it.
