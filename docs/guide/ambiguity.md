(ambiguity)=
# Ambiguity in timezones

```{note}
The API for handling ambiguity is largely inspired by that of
[Temporal](https://tc39.es/proposal-temporal/docs/ambiguity.html),
the redesigned date and time API for JavaScript.
```

In timezones, local clocks are often moved backwards and forwards
due to Daylight Saving Time (DST) or political decisions.
This makes it complicated to map a local time to a point on the timeline.
Two common situations arise:

- When the clock moves backwards, there is a period of time that repeats.
  For example, Sunday October 29th 2023 2:30am occurred twice in Paris.
  When you specify this time, you need to specify whether you want the earlier
  or later occurrence.
- When the clock moves forwards, a period of time is skipped.
  For example, Sunday March 26th 2023 2:30am didn't happen in Paris.
  When you specify this time, you need to specify how you want to handle this non-existent time.
  Common approaches are to extrapolate the time forward or backwards
  to 1:30am or 3:30am.

  ```{admonition} Why extrapolate skipped time?
  :class: tip
  You may wonder why skipped time is "extrapolated" like this,
  and not truncated. Why turn 2:30am into 3:30am and not cut
  it off at 1:59am when the gap occurs?

  The reason for the "extrapolation" approach is:

  * It fits the most likely reason the time is skipped: we forgot to adjust the clock, or adjusted it too early
  * This is how other datetime libraries do it (e.g. JavaScript (Temporal), C# (Nodatime), Java, Python itself)
  * It corresponds with the iCalendar (RFC5545) standard of handling gaps

  The figure in the Python docs [here](https://peps.python.org/pep-0495/#mind-the-gap) 
  also shows how this "extrapolation" makes sense graphically.
  ```

`whenever` allows you to customize how to handle these situations
using the `disambiguate` argument:

```{eval-rst}
+------------------+-------------------------------------------------+
| ``disambiguate`` | Behavior in case of ambiguity                   |
+==================+=================================================+
| ``"raise"``      | Raise :exc:`~whenever.RepeatedTime`             |
|                  | or :exc:`~whenever.SkippedTime` exception.      |
+------------------+-------------------------------------------------+
| ``"earlier"``    | Choose the earlier of the two options           |
+------------------+-------------------------------------------------+
| ``"later"``      | Choose the later of the two options             |
+------------------+-------------------------------------------------+
| ``"compatible"`` | Choose "earlier" for backward transitions and   |
| (default)        | "later" for forward transitions. This matches   |
|                  | the behavior of other established libraries,    |
|                  | and the industry standard RFC 5545.             |
|                  | It corresponds to setting ``fold=0`` in the     |
|                  | standard library.                               |
+------------------+-------------------------------------------------+
```

```python
>>> paris = "Europe/Paris"

>>> # Not ambiguous: everything is fine
>>> ZonedDateTime(2023, 1, 1, tz=paris)
ZonedDateTime("2023-01-01 00:00:00+01:00[Europe/Paris]")

>>> # --- Fold: 2:30am occurs TWICE (clocks fall back) ---

>>> # Reject ambiguous times outright
>>> ZonedDateTime(2023, 10, 29, 2, 30, tz=paris, disambiguate="raise")
Traceback (most recent call last):
    ...
whenever.RepeatedTime: 2023-10-29 02:30:00 is repeated in timezone Europe/Paris

>>> # Explicitly choose the earlier occurrence (summer time, +02:00)
>>> ZonedDateTime(2023, 10, 29, 2, 30, tz=paris, disambiguate="earlier")
ZonedDateTime("2023-10-29 02:30:00+02:00[Europe/Paris]")

>>> # Explicitly choose the later occurrence (winter time, +01:00)
>>> ZonedDateTime(2023, 10, 29, 2, 30, tz=paris, disambiguate="later")
ZonedDateTime("2023-10-29 02:30:00+01:00[Europe/Paris]")

>>> # Default ("compatible") picks "earlier" for folds — matching RFC 5545
>>> ZonedDateTime(2023, 10, 29, 2, 30, tz=paris)
ZonedDateTime("2023-10-29 02:30:00+02:00[Europe/Paris]")

>>> # The two occurrences are exactly 1 hour apart in real time:
>>> earlier = ZonedDateTime(2023, 10, 29, 2, 30, tz=paris, disambiguate="earlier")
>>> later   = ZonedDateTime(2023, 10, 29, 2, 30, tz=paris, disambiguate="later")
>>> later - earlier
TimeDelta("PT1h")

>>> # --- Gap: 2:30am DOESN'T EXIST (clocks spring forward) ---

>>> ZonedDateTime(2023, 3, 26, 2, 30, tz=paris, disambiguate="raise")
Traceback (most recent call last):
    ...
whenever.SkippedTime: 2023-03-26 02:30:00 is skipped in timezone Europe/Paris

>>> # "earlier" extrapolates backward → 1:30 AM (before the gap)
>>> ZonedDateTime(2023, 3, 26, 2, 30, tz=paris, disambiguate="earlier")
ZonedDateTime("2023-03-26 01:30:00+01:00[Europe/Paris]")

>>> # "later" extrapolates forward → 3:30 AM (after the gap)
>>> ZonedDateTime(2023, 3, 26, 2, 30, tz=paris, disambiguate="later")
ZonedDateTime("2023-03-26 03:30:00+02:00[Europe/Paris]")

>>> # Default ("compatible") picks "later" for gaps — matching RFC 5545
>>> ZonedDateTime(2023, 3, 26, 2, 30, tz=paris)
ZonedDateTime("2023-03-26 03:30:00+02:00[Europe/Paris]")
```
