(ambiguity2)=
# Ambiguity

Time zones describe how the offset from UTC *changes* over time.
When such a change occurs, local time can become ambiguous:
a given local clock reading may correspond to more than one exact time, or to none at all.

There are two ways this ambiguity appears:

- **Repeated time (a local time occurs twice).**
  When clocks move backward, a range of local times is repeated.
  For example, if the clock goes from `02:00` back to `01:00`, then `01:30` occurs twice:
  once before the offset change and once after.
  The local time alone does not tell you which exact moment is intended.
- **Skipped time (a local time does not occur).**
  When clocks move forward, a range of local times is skipped entirely.
  For example, if the clock jumps from `01:59` to `03:00`,
  then `02:30` never occurs on that date.

Still, software must decide how to interpret such a time if it is requested.

In software, resolving the ambiguity generally comes down to a choice between two options:
should the local time be interpreted using the offset before the change,
or the offset after the change?
Even in gaps, one can extrapolate the missing local times using either side of the transition.

(ambiguity-default)=
## The default convention

There is no natural law that dictates which choice is correct.
However, calendar standards like iCal (RFC 5545) and most mainstream date-time
libraries have converged on the same default:
ambiguous local times are resolved using the offset before the change.
This convention is not perfect, but it is consistent and predictable,
which allows higher-level operations—such as arithmetic—to behave sensibly across time zone transitions.

## Ambiguity in `whenever`

In `whenever`, ambiguous local times are by default resolved using the same convention
as most libraries: the offset before the change is used.
However, `whenever` also provides explicit options to handle ambiguity:

```python
>>> from whenever import ZonedDateTime, PlainDateTime
>>> local = PlainDateTime(2024, 10, 27, 2, 30)
>>> local.assume_tz("Europe/Amsterdam", disambiguate="earlier")
ZonedDateTime("2024-10-27 02:30:00+02:00[Europe/Amsterdam]")
>>> local.assume_tz("Europe/Amsterdam", disambiguate="later")
ZonedDateTime("2024-10-27 02:30:00+01:00[Europe/Amsterdam]")
>>> local.assume_tz("Europe/Amsterdam", disambiguate="compatible")  # the default
ZonedDateTime("2024-10-27 02:30:00+02:00[Europe/Amsterdam]")
```
