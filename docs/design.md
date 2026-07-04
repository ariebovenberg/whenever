(design)=
# Design philosophy

This page describes the guiding principles behind `whenever`'s API.
For concrete questions, see the {ref}`FAQ <faq>`.

## Separate types for separate meanings

If two concepts carry different semantics,
they get different types—even when they look similar on the surface.
For example, a datetime with a timezone ({class}`~whenever.ZonedDateTime`)
and one with a fixed offset ({class}`~whenever.OffsetDateTime`) both
represent a moment in time with a local clock reading,
but only the former can track DST transitions.
Encoding this distinction in the type system makes bugs that would
otherwise surface at runtime visible at development time.

This principle also extends to deltas:
an exact duration ({class}`~whenever.TimeDelta`),
a bag of calendar units ({class}`~whenever.ItemizedDateDelta`),
and a mixed bag ({class}`~whenever.ItemizedDelta`) each have
different arithmetic rules.
Keeping them as separate types prevents mixing operations
that don't make sense together.

## Footguns are flagged, not forbidden

Some operations are potential footguns—but not *always* wrong.
For example, doing arithmetic on a {class}`~whenever.PlainDateTime` can't
account for DST, but may be acceptable if the user knows
DST isn't relevant for their use case, or accepts the possibility
of an incorrect result some of the time.

Outright forbidding these operations would push users toward workarounds
that would obscure their intention. Whenever allows them but emits a
{class}`warning <whenever.PotentialDstBugWarning>`,
which can then explicitly and selectively be silenced.

## Operators with explicit warnings

`whenever` prefers explicit methods where semantics are ambiguous,
but operators are still allowed when their behavior is clear and guarded.
For example, itemized-delta composition is field-wise and therefore may not
preserve the order of sequential application when calendar units are involved.
Rather than hiding that operation, `whenever` exposes it and emits a targeted
warning so callers can opt in deliberately or silence it explicitly.

This keeps the API practical without pretending the operation is fully
algebraic. When you need calendar-aware composition, pass a
``relative_to`` reference. When you need exact-duration arithmetic,
use {class}`~whenever.TimeDelta`.

## No system timezone by default

Many datetime libraries silently use the system timezone as a default,
but this couples your code to the machine's configuration—a
common source of surprises, especially in servers and containers
where the system timezone is often UTC or undefined.
In `whenever`, the system timezone is never used implicitly;
you must opt in with a dedicated method
(e.g. {meth}`~whenever.Instant.to_system_tz`,
{meth}`~whenever.PlainDateTime.assume_system_tz`)
so the dependency is visible in the code.

<!-- FUTURE: something about .to_* and .assume_* APIs -->
