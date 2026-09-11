---
myst:
  html_meta:
    description: >-
      Turning local fields into an instant in a named time zone: the
      offset_mismatch policy for conflicting offsets, the disambiguation policy
      for repeated and skipped times, the order in which they apply, and how
      derived local times keep the offset they already had.
---

(resolving-local-times)=
# Resolving local times in a time zone

A named time zone contains rules that map exact instants to local clock
readings and UTC offsets. Going the other way—from local fields to an
instant—sometimes requires more information:

- A local time may be {ref}`repeated or skipped <ambiguity>` by a time zone
  transition. The `disambiguation` policy resolves that ambiguity.
- Input may contain both a numeric offset and a named time zone. If they
  conflict, the `offset_mismatch` policy decides which part is authoritative.

These rules apply to the {class}`~whenever.ZonedDateTime` constructor,
whether you pass it an ISO string or a standard library datetime, and to
{meth}`~whenever.ZonedDateTime.parse_iso`, patterned
{meth}`~whenever.ZonedDateTime.parse`, and
{meth}`~whenever.OffsetDateTime.assume_tz`. A local time derived from an
existing value follows a related rule, described in
{ref}`offset-preserving resolution <offset-preserving>`.

(offset-mismatch)=
## The complete resolution flow

```text
INPUT: local fields + named time zone
       e.g. 2023-10-29 02:15 [Europe/Amsterdam]
       │
       ├─ no offset, e.g. 02:15[Europe/Amsterdam] ───────────────┐
       │                                                         │
       ├─ Z, e.g. 02:15Z[Europe/Amsterdam]                       │
       │  └─► use exact UTC instant; recalculate local ─► DONE   │
       │                                                         │
       └─ numeric offset, e.g. +02:00                            │
          │                                                      │
          ├─ matches a possible time zone offset                 │
          │  e.g. +02:00 during the repeated hour                │
          │  └─► offset identifies instant;                      │
          │      ignore both policies ────────────────► DONE     │
          │                                                      │
          └─ mismatch, e.g. +03:00                               │
             └─ offset_mismatch                                  │
                ├─ "raise" ──────────────────────────► ERROR     │
                ├─ "keep_instant"                                │
                │  └─► offset identifies instant;                │
                │      recalculate local fields ──────► DONE     │
                └─ "keep_local"                                  │
                   └─► discard offset ───────────────────────────┤
                                                                 │
                                                                 ▼
                    DISAMBIGUATE THE LOCAL TIME IN THE NAMED TIMEZONE
                    ├─ local time is unique ──────────────► DONE
                    ├─ repeated or skipped + explicit policy
                    │                         └───────────► DONE or ERROR
                    └─ repeated or skipped + omitted policy
                          └─► warn, then use "compatible" ─► DONE

```

In other words, `offset_mismatch` determines which input is authoritative
*before* `disambiguation` can apply:

| Input situation | Result |
|---|---|
| No numeric offset | Resolve the written local fields in the time zone. Consult `disambiguation` only for a repeated or skipped local time. |
| `Z` suffix | Treat the input as an exact UTC instant and recalculate its local fields in the time zone. |
| Numeric offset matches | The offset identifies the instant, including which occurrence of a repeated time was written. Neither policy is consulted. |
| Mismatch + `"raise"` | Raise {exc}`~whenever.InvalidOffsetError`. |
| Mismatch + `"keep_instant"` | Treat the numeric offset as authoritative. Preserve the instant and recalculate local fields in the time zone. `disambiguation` is not consulted. |
| Mismatch + `"keep_local"` | Discard the numeric offset. Preserve the written local fields and consult `disambiguation` only if they are repeated or skipped. |

For example, both numeric offsets below are valid in Amsterdam's repeated
hour, so each identifies a different instant without requiring a policy:

```python
>>> ZonedDateTime("2023-10-29T02:15+02:00[Europe/Amsterdam]")
ZonedDateTime("2023-10-29 02:15:00+02:00[Europe/Amsterdam]")
>>> ZonedDateTime("2023-10-29T02:15+01:00[Europe/Amsterdam]")
ZonedDateTime("2023-10-29 02:15:00+01:00[Europe/Amsterdam]")
```

When the offset conflicts, the policy changes the meaning of the input:

```python
>>> s = "2023-05-01T12:00+03:00[Europe/Amsterdam]"
>>> ZonedDateTime(s, offset_mismatch="keep_instant")
ZonedDateTime("2023-05-01 11:00:00+02:00[Europe/Amsterdam]")
>>> ZonedDateTime(s, offset_mismatch="keep_local")
ZonedDateTime("2023-05-01 12:00:00+02:00[Europe/Amsterdam]")
```

{meth}`~whenever.OffsetDateTime.assume_tz` follows the same model: its local fields and
offset are the input, and the named time zone supplies the rules. A matching
offset preserves the represented instant. On a mismatch, `"keep_instant"`
preserves that instant while `"keep_local"` reinterprets the local fields.

### Offset precision

Hour-and-minute offsets in parsed text are compared with candidate historical
time zone offsets rounded to the nearest minute, half away from zero. An offset
that includes seconds must match exactly. {meth}`~whenever.OffsetDateTime.assume_tz` always
compares its exact offset.

Matching at the written precision is what lets a formatted value parse back.
Historical offsets often carry seconds—Dublin ran on `-00:25:21` until
1916—so an offset written to the minute would match nothing at all.

`Z` is not an offset in this sense. ISO 8601 and RFC 3339 both read `Z` as the
UTC designator: it says the time is written in UTC, not which offset the named
time zone was applying. `Z` therefore leaves the flow before either policy
applies, which is why `offset_mismatch="keep_local"` on a `Z` input behaves
like `"keep_instant"`.

(ambiguity)=
## Repeated and skipped local times

Local clocks sometimes move backward or forward because of daylight-saving
or political changes:

- When the clock moves backward, a range of local times is repeated (a
  *fold*, in the vocabulary of PEP 495). For example, 02:30 occurred twice in
  Paris on 29 October 2023.
- When the clock moves forward, a range is skipped (a *gap*). For example,
  02:30 did not occur in Paris on 26 March 2023.

`disambiguation` controls how a local time in one of these transitions is
resolved:

| `disambiguation` | Repeated time | Skipped time |
|---|---|---|
| `"raise"` | Raise {exc}`~whenever.RepeatedTime` | Raise {exc}`~whenever.SkippedTime` |
| `"earlier"` | Choose the earlier instant | Extrapolate backward across the gap |
| `"later"` | Choose the later instant | Extrapolate forward across the gap |
| `"compatible"` | Choose `"earlier"` | Choose `"later"` |

`"compatible"` follows the convention used by almost all other datetime
libraries and RFC 5545.

```python
>>> paris = "Europe/Paris"

>>> # Repeated: 02:30 occurs twice
>>> ZonedDateTime(2023, 10, 29, 2, 30, tz=paris, disambiguation="earlier")
ZonedDateTime("2023-10-29 02:30:00+02:00[Europe/Paris]")
>>> ZonedDateTime(2023, 10, 29, 2, 30, tz=paris, disambiguation="later")
ZonedDateTime("2023-10-29 02:30:00+01:00[Europe/Paris]")

>>> # Skipped: 02:30 does not exist
>>> ZonedDateTime(2023, 3, 26, 2, 30, tz=paris, disambiguation="earlier")
ZonedDateTime("2023-03-26 01:30:00+01:00[Europe/Paris]")
>>> ZonedDateTime(2023, 3, 26, 2, 30, tz=paris, disambiguation="later")
ZonedDateTime("2023-03-26 03:30:00+02:00[Europe/Paris]")
```

```{admonition} Why extrapolate a skipped time instead of truncating it?
:class: tip

A skipped wall time cannot retain identical final local fields: those fields
do not exist in that time zone. Extrapolating by the size of the gap preserves
the intended minute and second, which fits the common case where a clock was
not adjusted—or was adjusted too early. It also matches almost all other
datetime libraries and the iCalendar standard (RFC 5545).

The diagram in [PEP 495](https://peps.python.org/pep-0495/#mind-the-gap)
illustrates why extrapolating across the gap is useful.
```

If `disambiguation` is omitted, Whenever uses `"compatible"` but emits
{class}`~whenever.ImplicitDisambiguationWarning` only when a repeated or
skipped local time is actually encountered. Passing
`disambiguation="compatible"` explicitly makes that choice without a warning.
An ordinary, unambiguous local time never emits this warning.

(offset-preserving)=
## Offset-preserving resolution

`disambiguation` answers a question about written input. An operation that
derives a new local time from an existing {class}`~whenever.ZonedDateTime`
already has half the answer: the offset the value carries.
{meth}`~whenever.ZonedDateTime.replace`,
{meth}`~whenever.ZonedDateTime.replace_date`,
{meth}`~whenever.ZonedDateTime.replace_time`, and calendar arithmetic
(`add()` and `subtract()` with days, weeks, months, or years) keep that offset
while it is still valid for the new local time.

A repeated local time is the case that needs the rule. The current offset is
one of the two the time zone offers, so the value stays on the side of the
transition it was already on, and no policy applies:

```python
>>> d = ZonedDateTime(2023, 10, 29, 2, 30, tz="Europe/Paris", disambiguation="later")
>>> d
ZonedDateTime("2023-10-29 02:30:00+01:00[Europe/Paris]")
>>> d.replace(minute=45)  # still the second occurrence
ZonedDateTime("2023-10-29 02:45:00+01:00[Europe/Paris]")
```

`disambiguation` decides every other case. It defaults to `"compatible"` and
emits an {class}`~whenever.ImplicitDisambiguationWarning` when omitted. A
skipped local time always falls to `disambiguation`, because no earlier offset
is valid inside a gap. A repeated local time falls to it as well when the
operation changes the time zone, since neither offset of the new time zone need
match the current one.

```python
>>> d.replace(minute=45, disambiguation="earlier")  # explicit policy wins
ZonedDateTime("2023-10-29 02:45:00+02:00[Europe/Paris]")
```
