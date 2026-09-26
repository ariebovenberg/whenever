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
  time-unit boundary (`hour`, `minute`, `second`, and a `round()`
  increment) is a boundary at both occurrences when the fold is at least
  as long as the unit, and at the earlier one otherwise, because a shorter
  fold lies inside one unit interval.
- These rules define a sorted set of boundary instants. `floor()` and
  `start_of()` take the latest boundary at or before the value, `ceil()`
  the earliest at or after it, and `end_of()` is the next boundary minus
  one nanosecond. The value's clock reading never picks the boundary.
  `day_length()` is the difference between consecutive `start_of("day")`
  results.
- `round()` to a time unit chooses between the boundary at or before the
  value and the one after it, so `floor` never returns an instant after
  its input and `ceil` never one before it. Rounding to a day compares the
  time elapsed since `start_of("day")` with `day_length()`, as Temporal
  does.
- For every unit, every instant lies in exactly one interval: the boundaries
  partition the timeline. A day is chosen by the instant, not by the local
  date: with `S(d)` the start of local date `d`, the day of an instant with
  local date `d` is `d + 1` when it is at or after `S(d + 1)`, and `d`
  otherwise. Every calendar unit takes its day from that rule, and so do
  the calendar units of `since()` and `until()`.
- Examples. Colombo, 2006-04-15, fell back 30 minutes from 00:30+06:00 to
  00:00+05:30, a fold shorter than an hour: one 90-minute hour runs from
  00:00+06:00 (18:00Z) to 01:00+05:30 (19:30Z), and `ceil` of
  00:00+05:30 is 01:00+05:30. Goose Bay, 2010-11-07, fell back an hour
  from 00:01-03:00 to 23:01-04:00, a fold as long as the unit: its hours
  start at 02:00Z, 03:00Z, 04:00Z, and 05:00Z, and midnight starts two of
  them.

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
- `round("day")` and `round(hours(24))` differ only in a fold of a whole
  day (Sitka, 1867-10-18): the repeated date is one 48-hour day, while the
  24-hour increment, a unit no longer than the fold, starts at both
  midnights.
- The gap snapping is documented on `start_of()`, `end_of()`, and `round()`
  only; the resolution guide covers the caller-supplied cases.
- A future policy keyword on these methods is additive, and must keep the
  partition.
