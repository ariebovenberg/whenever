---
myst:
  html_meta:
    description: >-
      Pickling and copying whenever values: every type pickles on both
      backends, copy() and deepcopy() return the value itself, and a pickled
      ZonedDateTime across a time zone data update keeps its instant while
      PickleOffsetMismatchWarning reports the recomputed offset. Which
      versions can read each other's pickles.
---

(pickling)=
# Pickling and copying

Every `whenever` value pickles, on the Rust extension and on the pure-Python
backend alike, and a pickle written by one backend loads on the other. The one
exception is a {class}`~whenever.ZonedDateTime` whose system time zone has no
time zone ID: pickling it raises `ValueError` (see {ref}`systemtime`).
`copy.copy()` and `copy.deepcopy()` return the value itself, because values
are immutable.

## Zoned datetimes across time zone data updates

A pickled {class}`~whenever.ZonedDateTime` stores its local fields, observed
offset, and time zone ID. It does not embed a snapshot of the time zone
database. Unpickling loads the rules available in the new environment, which
may differ after a time zone data update or on another machine.

When the rules are unchanged, the round trip preserves the instant, local
representation, offset, and time zone ID without a warning:

```python
>>> import pickle
>>> original = ZonedDateTime(2024, 7, 1, 12, tz="Europe/Paris")
>>> restored = pickle.loads(pickle.dumps(original))
>>> restored.strict_eq(original)
True
```

If a political decision changes the applicable offset, Whenever preserves the
original instant and rebuilds the local representation using the current
rules. A hypothetical example: a pickle of
`2030-06-01 12:00+02:00[Europe/Paris]` written today would load as
`2030-06-01 11:00+01:00[Europe/Paris]` on a machine whose time zone data
records the EU abolishing summer time. It emits
{class}`~whenever.PickleOffsetMismatchWarning` describing the stored offset and
local datetime, their replacements, and that the instant was preserved.

This is an {ref}`offset mismatch <offset-mismatch>` resolved as
`keep_instant`, the same resolution `parse_iso()` offers through
`offset_mismatch=`. It warns because `pickle.loads()` has no argument to pass
the policy to.

Applications that require the exact time zone rules used when writing the
pickle should pin their time zone data version. They can reject a mismatch with
the standard warning machinery:

```python
import warnings
from whenever import PickleOffsetMismatchWarning

warnings.filterwarnings("error", category=PickleOffsetMismatchWarning)
restored = pickle.loads(payload)
```

This behavior prevents unpickling from creating a zoned datetime whose offset
contradicts its time zone rules. Unknown time zone IDs and malformed or
out-of-range payloads still raise exceptions.

## Compatibility

Every pickle written by 0.8.0 or later loads, as long as its type still
exists. 0.11 also loads `Instant` pickles written before 0.8.0; 1.0 won't.
`DateDelta` and `DateTimeDelta` pickles stopped loading in 0.11 with their
types; `SystemDateTime` pickles in 0.9.0. The payload stores a time zone ID,
never the rules, so what a pickle loads as depends on the time zone data of
the machine that loads it.
