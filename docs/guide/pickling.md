---
myst:
  html_meta:
    description: >-
      How a pickled ZonedDateTime behaves across a timezone-data update: the
      instant is preserved, local fields and offset are recomputed, and
      PickleOffsetMismatchWarning reports the difference. Which versions
      and backends can read each other's pickles.
---

(pickling)=
# Pickling zoned datetimes

A pickled {class}`~whenever.ZonedDateTime` stores its local fields, observed
offset, and IANA timezone ID. It does not embed a snapshot of the timezone
database. Unpickling loads the rules available in the new environment, which
may differ after a timezone-data update or on another machine.

When the rules are unchanged, the round trip preserves the instant, local
representation, offset, and timezone ID without a warning:

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
`2030-06-01 11:00+01:00[Europe/Paris]` on a machine whose timezone data
records the EU abolishing summer time. It emits
{class}`~whenever.PickleOffsetMismatchWarning` describing the stored offset and
local datetime, their replacements, and that the instant was preserved.

This is an {ref}`offset mismatch <offset-mismatch>` resolved as
`keep_instant`, the same resolution `parse_iso()` offers through
`offset_mismatch=`. It warns because `pickle.loads()` has no argument to pass
the policy to.

Applications that require the exact timezone rules used when writing the
pickle should pin their timezone-data version. They can reject a mismatch with
the standard warning machinery:

```python
import warnings
from whenever import PickleOffsetMismatchWarning

warnings.filterwarnings("error", category=PickleOffsetMismatchWarning)
restored = pickle.loads(payload)
```

This behavior prevents unpickling from creating a zoned datetime whose offset
contradicts its timezone rules. Unknown timezone IDs and malformed or
out-of-range payloads still raise exceptions.

## Compatibility

Pickles are readable across the Python and Rust backends of the same version,
and across versions: 1.0 reads pickles written by 0.8.0 or later. The payload
stores a timezone ID, never the rules, so what a pickle loads as depends on
the timezone data of the machine that loads it.
