---
myst:
  html_meta:
    description: >-
      The API design principles behind whenever: separate types for separate
      meanings, footguns flagged rather than forbidden, and no implicit system
      timezone.
---

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

For the information tradeoff and arithmetic risk of a fixed offset, see
{ref}`offset-datetime-guidance`.

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

Whenever allows these operations and emits a
{class}`warning <whenever.PotentialDstBugWarning>` instead, because three
audiences need three different things from the same call:

- A strict codebase turns the whole category into an error with one filter,
  and still allows the deliberate exception through a call-local escape such
  as `naive_arithmetic_ok=True`.
- A codebase that has weighed the risk and accepted it leaves the default
  filters alone.
- A newcomer who did not know the pitfall existed is told once per call site,
  with the fix in the message.

Raising would serve only the first audience. Staying silent would serve only
the second. See {ref}`the guide to handling warnings <warnings>` for the
filters.

## No system timezone by default

Many datetime libraries silently use the system timezone as a default,
but this couples your code to the machine's configuration—a
common source of surprises, especially in servers and containers
where the system timezone is often UTC or undefined.
In `whenever`, the system timezone is never used implicitly;
you must pass {data}`~whenever.SYSTEM_TZ` explicitly
(for example to {meth}`~whenever.Instant.to_tz` or
{meth}`~whenever.PlainDateTime.assume_tz`)
so the dependency is visible in the code.
