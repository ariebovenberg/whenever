# Boundary methods use one resolution rule

`start_of()`, `end_of()`, `round()`, and `day_length()` on `ZonedDateTime`
take no `disambiguation` and never emit `ImplicitDisambiguationWarning`, even
when the boundary they compute falls in a repeated or skipped local time.

## Semantics

- A skipped boundary, of any unit, snaps to the edge of the gap:
  `start_of()` to the first instant after it, `end_of()` to the last instant
  before it. It is never extrapolated across the gap.
- A repeated calendar-unit boundary (`year`, `month`, `week_mon`,
  `week_sun`, `day`) resolves to the earlier occurrence. A repeated
  time-unit boundary (`hour`, `minute`, `second`) keeps the value's current
  offset when that is one of the two, and otherwise takes the earlier
  occurrence.
- `end_of()` is the next `start_of()` minus one nanosecond, and
  `day_length()` is the difference between consecutive `start_of("day")`
  results.
- `round()` resolves its result with the time-unit rule, so `floor` never
  returns an instant after its input. Rounding to a day compares the time
  elapsed since `start_of("day")` with `day_length()`, as Temporal does.
- For every unit, every instant lies in exactly one interval: the boundaries
  partition the timeline.

## Considered options

- **A `disambiguation` keyword.** Rejected: the caller supplied no local
  time, so there is no choice to make explicit, and two calls with different
  policies would produce intervals that overlap or leave a gap.
- **Warn without a keyword.** Rejected: a warning with no escape is not
  actionable.
- **Extrapolate a skipped boundary as `"compatible"` does.** Rejected: an
  `end_of()` pushed across a gap lands past the next interval's start, and
  when a gap contains midnight (Toronto, 1919-03-31, 23:30 to 00:30) the day
  would start half an hour into the next local date.
- **Let the value's offset pick a repeated calendar boundary.** Rejected:
  two values on the same date would get different day intervals.
- **Round a day by the clock reading.** Rejected: on a 23-hour day 11:31
  would round up with less than half the day elapsed.

## Consequences

- In a fold that straddles midnight (Goose Bay, 2010-11-07, 00:01 back to
  23:01), the day interval is not the set of instants with that local date:
  the second occurrence of Nov 6 23:30 lies inside day Nov 7. No choice of
  midnight avoids this; the earlier one is the convention.
- The gap snapping is documented on `start_of()` and `end_of()` only; the
  resolution guide covers the caller-supplied cases.
- A future policy keyword on these methods is additive, and must keep the
  partition.
