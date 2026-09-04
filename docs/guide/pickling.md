---
myst:
  html_meta:
    description: >-
      How a pickled ZonedDateTime behaves across a timezone-data update: the
      instant is preserved, local fields and offset are recomputed, and
      PickleOffsetMismatchWarning reports the difference.
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
rules. For example, a stored `2030-06-01 12:00+02:00[Example/City]` might load
as `2030-06-01 11:00+01:00[Example/City]`. It emits
{class}`~whenever.PickleOffsetMismatchWarning` describing the stored offset and
local datetime, their replacements, and that the instant was preserved.

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
