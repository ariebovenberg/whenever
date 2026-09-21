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
  offset when that is one of the two and the fold is at least as long as
  the unit, and otherwise takes the earlier occurrence. That rule is stated
  for `start_of()`; `end_of()` inherits whatever the next `start_of()`
  resolves to, which in a fall-back shorter than the unit is the later
  offset, because the whole fold lies inside one unit (Lord Howe,
  2024-04-07: `end_of("hour")` of 01:15+11:00 is 01:59:59.999999999+10:30).
- `end_of()` is the next `start_of()` minus one nanosecond, and
  `day_length()` is the difference between consecutive `start_of("day")`
  results.
- `round()` resolves its result with the time-unit rule, so `floor` never
  returns an instant after its input. Rounding to a day compares the time
  elapsed since `start_of("day")` with `day_length()`, as Temporal does.
- For every unit, every instant lies in exactly one interval: the boundaries
  partition the timeline. A day is chosen by the instant, not by the local
  date: with `S(d)` the start of local date `d`, the day of an instant with
  local date `d` is `d + 1` when it is at or after `S(d + 1)`, and `d`
  otherwise. Every calendar unit takes its day from that rule. A fall-back shorter than the unit that begins on
  a boundary of that unit (Colombo, 2006-04-15: 00:30+06:00 back to
  00:00+05:30) would break this if the later occurrence kept its offset,
  since the two occurrences of 00:15 would then start different hours. So
  `start_of()`, `end_of()`, and `round()` all resolve a fold shorter than
  the unit (the increment, for `round()`) to the first occurrence, and
  both occurrences share the hour that starts at 00:00+06:00.

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
  midnight avoids this; the earlier one is the convention. Temporal has no
  answer there: `round()` raises `RangeError` for the second pass, while
  `startOfDay()` and `hoursInDay` answer for Nov 6.
- The gap snapping is documented on `start_of()`, `end_of()`, and `round()`
  only; the resolution guide covers the caller-supplied cases.
- A future policy keyword on these methods is additive, and must keep the
  partition.
