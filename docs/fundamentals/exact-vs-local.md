(exact-vs-local)=
# Exact time vs local time

Many surprising behaviors in date-time code come from treating different kinds
of time as if they were the same.
Before looking at time zones, arithmetic, or edge cases,
it helps to be clear about what a time value actually represents.

The most fundamental distinction is between **exact time** and **local time**.

```{tip}
If you prefer a video explanation, [here is an excellent explanation of these concepts](https://www.youtube.com/watch?v=saeKBuPewcU).
```

## Exact time

An **exact time** (also called "absolute time" or "UTC time") represents a single,
precise moment on the global timeline.
It refers to an instant that exists independently of where you are,
what time zone you are in, or how clocks are configured.
Exact time can simply be defined as time elapsed since a standard reference point, 
such as the **Unix epoch**.

Examples of exact time include:

- "2026-01-15 12:00 UTC"
- "1.673.779.200 seconds since the Unix epoch"
- "The moment this database record was created"

Exact time is what you use when you care about *when something actually happened*.
It is ideal for logging, ordering events, measuring durations, and comparing timestamps.
Two exact times can always be compared, subtracted, or ordered, and the result is unambiguous.

Importantly, exact time does **not** depend on civil conventions like daylight saving time.
An hour is always an hour. If you wait two hours, two hours pass—no more, no less.

## Local time

A **local time** (also called "civil time" or "wall-clock time") represents a clock
reading as people experience it in a particular place.
It answers questions like "What time does the clock and calendar on the wall show?"

Examples of local time include:

- "9:00 AM in Amsterdam"
- "Office hours are from 10:00 to 18:00"
- "Let’s meet tomorrow at noon"

Local time is how humans plan their days.
It aligns with calendars, business hours, and social expectations.

But local time is not inherently a single moment on the global timeline
because clocks can shift due to daylight saving time, or political decisions.
This means that "2 hours later" on the clock does not always correspond to "2 hours later" of elapsed "exact" time,
since the clock might have jumped forward or backward in the meantime.

Also, during such a jump, a local time might occur twice or not at all, creating ambiguity.
Local time only becomes meaningful when interpreted *in the context of a time zone*.

## Why this distinction matters

Many problems with date-time code come from treating exact and local time as interchangeable. They are not.

- Exact time is about *physics*: elapsed time, ordering, duration.
- Local time is about *conventions*: calendars, clocks, and human schedules.

Both are necessary. Both are useful. But they answer different kinds of questions,
and they behave differently under operations like comparison and arithmetic.

A useful mental model is this:
**exact time is what happened; local time is how we talk about it.**


## Exact and local time in `whenever`

In `whenever`, the distinction between exact and local time is made explicit through different types:

- {class}`~whenever.Instant` represents an exact moment on the global timeline (UTC).
- {class}`~whenever.PlainDateTime` represents a local clock reading without time zone context.
- {class}`~whenever.ZonedDateTime` represents a *both* an exact moment and its local representation in a specific time zone.
  More on that in the next section.

## Summary

| Concept              | Exact time                               | Local time                     |
| -------------------- |:----------------------------------------:|:------------------------------:|
| Represents           | A precise instant on the global timeline | A human clock reading          |
| Depends on time zone | No                                       | Yes                            |
| Affected by DST      | No                                       | Yes                            |
| Typical uses         | Logging, ordering, durations             | Scheduling, calendars, display |
| Example              | `2026-01-15T12:00:00Z`                   | "9:00 AM tomorrow"             |
| `whenever` class     | {class}`~whenever.Instant`               | {class}`~whenever.PlainDateTime` |


## How time zones fit in

Exact and local time are two different ways of describing when something happens,
but they do not exist in isolation.
In real programs, we often need to move between them:
to interpret a local clock reading as a precise moment,
or to present an exact moment in a human-meaningful way.

That translation is where **time zones** come in.
Time zones define how local time relates to the global timeline—and, crucially,
how that relationship changes over time.
Understanding time zones is the next step.
