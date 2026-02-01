---
hide-toc: true
---

# Equality edge cases

[PEP 495](https://peps.python.org/pep-0495/) introduced the `fold` attribute to
disambiguate local times during daylight saving time (DST) transitions.
However, to maintain backward compatibility,
the semantics of equality comparisons were not changed to account for this new attribute.

This results in two notable edge cases when comparing aware `datetime` objects:

- **Different time zones, same moment:** Two aware datetimes that represent the same
  instant in time but are associated with different time zones may compare as unequal
  during DST transitions.
- **Same time zone, different folds:** Two aware datetimes in the same time zone
  but with different `fold` values (0 vs 1) may compare as equal, even though they
  represent different moments in time during a repeated hour.

The result is equality behavior that is sometimes surprising and occasionally
incorrect from a "moment in time" perspective.

## How `whenever` solves this

`whenever` was designed from the ground up with these considerations in mind.
It defines equality for "aware" objects based on the exact instant in time they represent,
and this holds true consistenly.

```python
>>> dt1 = ZonedDateTime(2024, 10, 27, 2, 30, tz="Europe/Paris", disambiguate="earliest")
>>> dt2 = ZonedDateTime(2024, 10, 27, 2, 30, tz="Europe/Paris", disambiguate="latest")
>>> dt1 == dt2  # different instant, same zone
False
>>> dt1 == dt1.to_tz("Asia/Tokyo")  # same instant, different zone
True
```
