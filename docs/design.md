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

## Operators only where mathematically intuitive

Operators like ``+``, ``-``, ``*``, and ``/`` are only defined
when they obey the mathematical properties you'd expect—associativity,
reversibility, and so on.

For instance, ``a + (b + c) == (a + b) + c`` doesn't hold
when ``b`` or ``c`` involve months (because months have variable lengths).
Instead of silently breaking those expectations,
`whenever` omits the operator and provides explicit methods
({meth}`~whenever.Date.add`, {meth}`~whenever.Date.subtract`)
that don't carry the same mathematical connotations.

Similarly, the ``-`` operator between two datetimes
always returns a {class}`~whenever.TimeDelta` (an exact duration),
because that's the only type where subtraction is always reversible.
For calendar-unit differences, use {meth}`~whenever.ZonedDateTime.since`
/ {meth}`~whenever.ZonedDateTime.until`.

## Lossless round-tripping

Every `whenever` object's {func}`str` and {func}`repr` can be used
to reconstruct the value:

```python
>>> d = ZonedDateTime(2024, 3, 15, 12, tz="Europe/Amsterdam")
ZonedDateTime("2024-03-15 12:00:00+01:00[Europe/Amsterdam]")
>>> ZonedDateTime(str(d)) == d
True
>>> eval(repr(d)) == d
True
```

This makes debugging and logging straightforward—you always know
exactly what value you're looking at, and can copy-paste it into a REPL.

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
