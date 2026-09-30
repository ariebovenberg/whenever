# Composition takes no reference

`add()` and `subtract()` on the itemized deltas compose component-wise.
They take a delta or its components, and one escape,
`month_composition_ok=`. A reference belongs to a measurement: `in_units()`,
`total()`, and `since()`/`until()` take `relative_to=`, composition doesn't.

A composed delta can land on a different day than its parts applied in
turn. Composition drops the order of application, and a shift by years or
months clamps, so `date + (a ⊕ b)` and `date + a + b` can differ. In
algebraic terms, `⊕` breaks the action law `(a ⊕ b) · d == b · (a · d)`.
`MonthCompositionWarning` flags exactly this.

## Semantics

- `+`, `-`, `add()`, and `subtract()` add like components and keep the
  result itemized. Only seconds and nanoseconds carry (ADR 0005).
- The warning fires when either operand has nonzero `years` or `months`.
  Days, weeks, and exact units never clamp and don't warn. Around a gap,
  `dt + 1 day + 1 hour` and `dt + P1DT1H` can still differ by how the gap
  resolves; disambiguation covers that.
- The message names the hazard, one example, the fix (add each delta to the
  date in turn), and the escape.
- To balance a composed delta, call `in_units()` on it.

## Considered options

- **Sum, then balance at the reference**, as `add(relative_to=, in_units=)`
  did in 0.10. Rejected: it summed before applying, as plain composition
  does, yet silenced the warning. It was also `add().in_units()` in one
  call, at the cost of six keywords, three `TypeError` guards, and the
  date-or-datetime reference rules on two method pairs.
- **Apply in turn at the reference**, as jiff's `Span::checked_add` does and
  Temporal's `Duration.add(relativeTo)` once did. This restores the action
  law at that date. Rejected: addition stops commuting, and from January 31
  a month forward plus a month back is minus three days in jiff. Temporal
  removed it and now refuses calendar composition outright.
- **Refuse composition with years or months**, as Temporal and jiff do.
  Rejected: Temporal's `Duration` balances on `add()`, which needs a
  reference. whenever's deltas stay itemized, so `P1M + P1M = P2M` is well
  defined and often wanted: the second monthly renewal after January 31 is
  `start + 2 months`. See the design page's "flagged, not forbidden".
- **No warning**, as java.time's `Period.plus()`, Joda, Noda, and
  `relativedelta`. Rejected: the result is plausible and occasionally off by
  days, the same shape as `NaiveArithmeticWarning`.
- **Keep the reference form, and warn anyway.** Rejected: it would keep six
  keywords that only repeat `in_units()`.
- **Warn on any calendar unit**, as 0.10.4 did. Rejected: `P1W + P2D` loses
  nothing, and warning on it teaches users to silence the warning.

## Consequences

- The reference keywords on itemized `add()` and `subtract()` are deprecated
  with their 0.10 behaviour, and go in 1.0. `CalendarUnitCompositionWarning`
  and `cal_unit_composition_ok=` are deprecated aliases of
  `MonthCompositionWarning` and `month_composition_ok=`. The stub gives the
  old keywords one permissive deprecated overload per method.
- Future composition sugar, such as scaling, takes no `relative_to=`.
- Every escapable warning names one call-local escape again.
