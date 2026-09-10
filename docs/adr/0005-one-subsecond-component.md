# Seconds and nanoseconds are one quantity in two components

`ItemizedDelta` carries subseconds in a single `nanoseconds` component,
bounded to 999,999,999, and a present `nanoseconds` brings a present
`seconds` with it. There are no `milliseconds` or `microseconds` components;
those units exist only as scalar totals. The reason is that seconds and
nanoseconds are one quantity written as two integers, the way ISO 8601
writes `PT1.5S` as one decimal number. Keeping minutes unbalanced against
hours preserves something a reader asked for (`90 minutes` is not
`1 hour 30 minutes` on a label); keeping nanoseconds unbalanced against
seconds preserves nothing.

## Semantics

- `nanoseconds` lies within ±999,999,999 under the delta's single sign. The
  `ValueError` names the bound and the remedy: put whole seconds in
  `seconds=`.
- `ItemizedDelta(nanoseconds=5)` carries `seconds=0`, so `dict()` shows both.
  It is the only component that is present by implication rather than
  because the caller gave it.
- Presence still round-trips: `seconds=0` formats as `PT0S`, while
  `nanoseconds=0` formats as `PT0.0S`, and `parse_iso()` reads the fraction
  back as a present `nanoseconds`.
- `total("milliseconds")` and `total("microseconds")` return a `float`;
  `total("nanoseconds")` returns an `int`. `in_units()` offers no unit below
  `nanoseconds` and none between it and `seconds`.

## Considered options

- **Temporal-style `milliseconds`, `microseconds`, and `nanoseconds`
  components**, as Jiff's `Span` also has. Rejected: three names for one
  quantity, each a mapping key that `==`, iteration, and `strict_eq()` would
  have to account for, and ISO 8601 cannot record which one was given, so a
  round trip would lose presence. No display case wants `1500 microseconds`
  kept as such the way it wants `90 minutes`. It would also break with the
  datetime types, whose only subsecond field is `nanosecond`.
- **An unbounded `nanoseconds`**, like `seconds` is unbounded against
  minutes. Rejected: `ItemizedDelta(nanoseconds=1_500_000_000)` would format
  as `PT1.5S` and parse back as a different value, so the bound is what
  keeps one representation per formatted string.
- **A float or `Decimal` `seconds` and no `nanoseconds`.** Rejected:
  nanoseconds do not survive a float; `Decimal` is not mainstream in Python
  and is two integers in one object anyway. Either would make one component
  a different type, where the design as chosen keeps every value an `int`,
  so an itemized delta is a `Mapping[DeltaUnitStr, int]` with no odd one
  out.

## Consequences

- The mapping contract ("iteration yields the present components, largest
  unit first") has exactly one implied component, documented next to the
  bound on the reference page.
- Milliseconds and microseconds appear as `TimeDelta` constructor arguments
  and as `total=` units on `since()`, `until()`, and `total()`, and nowhere
  as an itemized component. `DeltaUnitStr` and `DeltaTotalUnitStr` stay two
  aliases for that reason.
- `ItemizedDelta` is one Python class on both backends, so the bound and its
  message live in one place. `java.time.Duration` makes the same split:
  seconds plus a nanosecond adjustment in `0..999,999,999`.
- Normalizing `nanoseconds` alone, so that `1_500_000_000` splits its whole
  seconds off into `seconds`, stays open as an additive change: it would be
  the only normalization an itemized delta performs, and it is justified by
  the same reasoning, since nothing is preserved by refusing it.
