(arithmetic2)=
# Arithmetic

```{tip}
This page explains the *concepts* behind date-time arithmetic.
For how `whenever` implements these, see the {ref}`arithmetic guide <arithmetic>`.
```

Arithmetic answers questions like "how many hours passed between these two events?",
"how long ago did this happen?", or "reschedule this event three days later."
These operations seem simple, but their behavior depends on what the units involved actually mean.

## Two kinds of units

Date-time arithmetic uses two fundamentally different kinds of units:

* **Exact units**, such as *hours*, *minutes*, and *seconds*.
  These represent fixed durations. An hour is always an hour.

* **Calendar units**, such as *days*, *weeks*, *months*, and *years*.
  These are defined in terms of local dates and local clock times, not a fixed number of seconds.

This distinction is the key to understanding how arithmetic behaves around daylight saving time and other time zone transitions.

## Conventions and standards

There is no universal law that dictates how date-time arithmetic must work.
Instead, practice across many systems and applications has converged on a set
of behaviors that users find least surprising.
These expectations are captured in standards such as RFC 5545 (iCalendar)
and are followed, with minor variations, by most modern date-time libraries.

## How arithmetic is applied

Under these shared semantics:

* **Exact units are added as exact durations**

  Adding two hours always advances the underlying moment by exactly two hours on the global timeline.
  Daylight saving time transitions do not change the amount of time that passes.
  If you ask to meet a friend "in two hours," you expect that to mean two real hours
  later—not one, and not three if a DST transition occurs in between.

* **Calendar units are added in local time**

  Adding one day advances the date while keeping the local clock time the same.
  If a meeting scheduled for 9:00 is moved "one day later," it should still be at 9:00,
  even if the intervening night was shorter or longer due to a daylight saving transition.

## Summary

| Unit type      | Examples                   | What is preserved         | Duration affected<br> by DST |
|:-------------- |:--------------------------:|:-------------------------:|:---------------:|
| Exact units    | hours, minutes, seconds    | Elapsed time              | No              |
| Calendar units | days, weeks, months, years | Local date and clock time | Yes             |

Taken together, these rules are sometimes described as **DST-safe arithmetic**.
They aim to preserve the intent behind an operation—whether that intent is about
elapsed time or about the structure of the calendar—so that arithmetic behaves in a way that matches how people reason about time.
