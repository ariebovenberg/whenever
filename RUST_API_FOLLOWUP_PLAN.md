# Follow-up internal Rust API refactor plan

This plan follows [`ORIGINAL_PLAN.md`](ORIGINAL_PLAN.md). It targets the remaining internal API
inconsistencies and meaningful duplication discovered after completing that plan. The Python API
and the pure-Python implementation remain the behavioral reference.

## Goals

- Make pickle encoding and decoding modular, validated, compatible between the Rust and
  pure-Python implementations, and backwards compatible with existing pickle fixtures.
- Finish separating pure date/time and difference behavior from CPython argument parsing.
- Standardize internal Python-conversion names and parser argument order.
- Consolidate repeated pattern parsing, timestamp parsing, date-derived properties, and datetime
  C-API construction.
- Evaluate nested datetime representations based on their actual effect on code, layout,
  performance, and binary size.
- Preserve the current low-level FFI ownership model, exact-versus-subclass distinctions, and
  optimized interned-string matching.

## Guardrails

- Do not change public Python method names or signatures as part of an internal cleanup.
- Match the pure-Python implementation unless a deliberate behavior correction is separately
  approved and covered in both implementations.
- Preserve all currently accepted pickle payloads and the legacy pre-0.8 Instant decoder.
- Keep serialized field order, widths, signedness, endianness, and unpickler names stable unless a
  versioned backwards-compatible decoder is introduced.
- Treat pickle bytes as untrusted input. Never feed decoded primitives into unchecked constructors
  before validating them.
- Preserve a ZonedDateTime pickle's stored offset even if current timezone data disagrees. This is
  necessary for historical compatibility; decoding should validate domain ranges, not reinterpret
  the value under the current timezone database.
- Keep checked domain operations under the short name and make unchecked construction conspicuous.
- Avoid new macros and generic frameworks when a typed function or small value type is clearer.
- Do not build new abstractions around deprecated DateDelta and DateTimeDelta beyond compatibility
  or safety work required to keep their existing behavior.
- Use the Makefile workflows for verification.
- Make each completed phase a short, SSH-signed commit and verify its signature before continuing.

## Baseline

Before implementation:

1. Record the current release-extension size after `make QUIET=1 build-release`.
2. Record `size_of` and `align_of` for Date, Time, PlainDateTime, OffsetDateTime,
   ZonedDateTime, Instant, and their Python object layouts in a Rust test or diagnostic.
3. Record representative benchmark results for:
   - keyword-heavy `format_iso`;
   - pattern `format` and `parse`;
   - timestamp construction;
   - pickling and unpickling; and
   - common datetime arithmetic.
4. Run the authoritative test and lint workflows to establish the pre-refactor state.

Release size comparisons must use the same toolchain and build flags. Source-line reduction alone
does not count as a binary-size improvement because the release profile already uses fat LTO and a
single codegen unit.

## Phase 1: validated modular pickle codecs

### 1.1 Document the wire formats

Add a concise format table next to the codec implementation. The current layouts are:

| Type | Little-endian fields | Bytes |
| --- | --- | ---: |
| Date | `u16 year, u8 month, u8 day` | 4 |
| Time | `u8 hour, u8 minute, u8 second, u32 nanos` | 7 |
| PlainDateTime | Date + Time | 11 |
| Instant | `i64 epoch seconds, u32 nanos` | 12 |
| TimeDelta | `i64 seconds, u32 nanos` | 12 |
| OffsetDateTime | PlainDateTime + `i32 offset seconds` | 15 |
| ZonedDateTime | OffsetDateTime payload + separate timezone ID argument | 15 + ID |

Rust currently stores subseconds as a nonnegative `i32`; its encoded bytes must remain compatible
with Python's unsigned `I`/`L` fields.

Retain the current unpickler names, including `_unpkl_date`, `_unpkl_time`, `_unpkl_local`,
`_unpkl_inst`, `_unpkl_tdelta`, `_unpkl_offset`, `_unpkl_zoned`, and legacy `_unpkl_utc`.

### 1.2 Introduce a pure codec module

Create `src/common/pickle.rs`. It may depend on domain types but must not depend on `PyObj`,
`State`, or the CPython API.

Prefer explicit typed functions over a new macro:

```rust
fn encode_date(value: Date) -> [u8; 4];
fn decode_date(data: [u8; 4]) -> Option<Date>;

fn encode_time(value: Time) -> [u8; 7];
fn decode_time(data: [u8; 7]) -> Option<Time>;

fn encode_plain(value: PlainDateTime) -> [u8; 11];
fn decode_plain(data: [u8; 11]) -> Option<PlainDateTime>;
```

Build the larger formats compositionally from the smaller codecs. Fixed arrays avoid the current
temporary `Vec` allocation and can be passed directly to `ToPy`.

Decoders must use checked constructors:

- `Year::new`;
- `Month::new`;
- `Date::new`;
- `Time::new`;
- a new checked `SubSecNanos::new`;
- `EpochSecs::new`;
- `DeltaSeconds::new`;
- `Offset::new`; and
- `PlainDateTime::assume_offset` where an instant-range check is required.

Do not validate a ZonedDateTime's offset against current timezone rules while unpickling.

### 1.3 Harden unchecked scalar construction

Audit unchecked constructors after the decoders no longer depend on them.

- Constructors that can create an invalid Rust value, notably the `NonZeroU16`-backed Year and
  transmuted Month/Weekday enums, should either become `unsafe fn` or be replaced with a checked
  implementation at call sites.
- Keep numeric-wrapper unchecked constructors safe only where invalid values cannot violate Rust
  validity and every caller has a documented proof of the domain invariant.
- Add `// SAFETY:` comments at every remaining unsafe call.

### 1.4 Compatibility and malformed-input tests

Add focused tests without duplicating all existing class test matrices:

- Current embedded historical pickle fixtures continue to load.
- The legacy pre-0.8 Instant fixture continues to load.
- The Rust implementation loads payloads emitted by the pure-Python implementation.
- The pure-Python implementation loads payloads emitted by the Rust implementation.
- `__reduce__` payload bytes match between implementations for representative values and all
  boundary values.
- Wrong byte lengths are rejected.
- Zero/out-of-range years, invalid months and days, invalid clock fields, invalid subseconds,
  invalid offsets, and out-of-range instants/deltas are rejected without panic or undefined
  behavior.
- Non-`bytes` arguments retain the current exact-type policy unless compatibility evidence
  requires otherwise.

If malformed-input exception types differ today, first preserve accepted inputs and safe rejection.
Standardize the exception type only if the pure-Python reference and existing compatibility tests
can be aligned deliberately.

### Verification

- Rust unit tests for every codec and boundary.
- Existing pickle tests for all datetime and delta classes.
- Cross-backend pickle compatibility tests.
- `make QUIET=1 build`
- `make QUIET=1 ci-lint`
- `make QUIET=1 test-rs`
- Focused Python tests for affected classes.

## Phase 2: conversion helpers, naming, and parser arguments

### 2.1 Add strict boolean extraction

Add:

```rust
PyObj::expect_bool(name: &str) -> PyResult<bool>
```

It accepts only the `True` and `False` singletons and raises `TypeError` otherwise.
`is_truthy()` remains the API for intentionally truthy values and must continue propagating
`__bool__` failures.

Decision gate: the current Rust sites disagree on `TypeError` versus `ValueError`, while the
pure-Python Date and Time formatting paths are less strict than the datetime path. Before applying
the helper everywhere, add parity tests and choose one policy. The recommended policy is exact
booleans with `TypeError` for every `basic` argument, implemented identically in Python and Rust.
If that behavior change is not desired, use the helper only where strictness is already part of the
reference behavior.

Do not introduce generic `expect<T>`, `expect_str`, `expect_bytes`, or `expect_number` helpers in
this phase. Preserve exact-versus-subclass decisions explicitly.

Use `expect_int` at remaining required-integer sites only where `TypeError` is the intended public
exception. Optional operator probes should continue using casts.

### 2.2 Normalize conversion vocabulary

Apply:

| Current | Selected |
| --- | --- |
| `Offset::from_obj` | `Offset::from_py` |
| `TimeDelta::from_py` | `from_stdlib_timedelta` |
| `TimeDelta::from_py_unchecked` | `from_stdlib_timedelta_unchecked` |
| `DeltaField::from_py_opt` | `from_optional_py` |
| `PlainDateTime::resolve_in_py` | `resolve_or_raise` |
| `Instant::into_zoned_py` | `into_zoned_obj` |
| `OffsetDateTime::into_zoned_py_unchecked` | `into_zoned_obj_unchecked` |
| binding-side `hash` / `pyhash` | `python_hash` |
| domain lazy `format_iso` | `iso_format` |

Use these rules:

- `from_py(obj, context)` converts one required generic Python value.
- `from_stdlib_*` converts a typed stdlib wrapper.
- `extract` optionally recognizes a value.
- `to_obj` allocates a whenever extension object.
- `to_py` converts a primitive, string, or collection.
- `_or_raise` returns a Rust domain value while translating failure to a Python exception.

Keep low-level `PyRef::from_obj_unchecked`; it constructs an FFI wrapper from an object pointer and
is not a semantic Python-to-domain conversion.

### 2.3 Normalize parser argument order

For one-value conversions:

```rust
Type::from_py(obj, context)
```

Change DateBoundaryUnit and DateTimeBoundaryUnit to match this order.

For complete Python call parsers:

```rust
parse(fname, args, kwargs, state)
```

Eliminate opaque or redundant boolean controls where practical:

- Collapse the two warning booleans in `resolve_local_relative_to`; all current callers pass the
  same value for both.
- Replace `round::Args::parse(..., true/false)` with an explicit context enum or two clearly named
  constructors.
- Leave very local add/subtract flags alone unless a direction enum demonstrably improves several
  call sites.

### Verification

- Compile-driven call-site migration.
- Focused tests for boolean, integer, offset, stdlib timedelta, and disambiguation parsing.
- Confirm no change to subclass acceptance.
- Build, lint, and Rust tests.

## Phase 3: complete the domain boundary

### 3.1 Split difference semantics from Python parsing

Move pure types and algorithms from `common::math` to `domain::difference`:

- InterimDate;
- CalendarUnit, DifferenceUnit, ExactUnit, and TotalUnit;
- CalendarUnitSet, DifferenceUnitSet, and ExactUnitSet;
- CalendarIncrement and DifferenceIncrement;
- date/datetime difference and rounding calculations; and
- semantic difference specifications used by domain operations.

Keep Python adapters in `common::difference_args`:

- `from_py` implementations;
- unit-sequence parsing;
- Python-number conversion;
- `since`/`until` kwarg parsing; and
- warning and Python-exception behavior.

Rename `SinceUntilKwargs` to `DifferenceArgs` or `DifferenceSpec`. Prefer named fields:

```rust
enum DifferenceSpec {
    Total(DifferenceUnit),
    InUnits {
        units: DifferenceUnitSet,
        mode: round::Mode,
        increment: DifferenceIncrement,
    },
}
```

Add checked domain constructors for increments. Domain invariants must not rely on construction
through a Python parser.

### 3.2 Remove compatibility import paths

- Remove `common::scalar`'s re-export and import `domain::scalar` directly.
- Import `domain::round` directly from domain modules instead of passing through
  `common::round`.
- Rename Python-aware modules where it clarifies their role:
  `common::shift` to `shift_args`, and `common::round` to `round_args`.

### 3.3 Move behavior to its owning value

Add pure Date methods:

- `day_of_year`;
- `days_in_month`;
- `days_in_year`; and
- `is_in_leap_year`.

Then delegate Date, PlainDateTime, OffsetDateTime, and ZonedDateTime properties through their Date.

Finish the receiver-oriented composition pass:

- use `date.at(time)` instead of rebuilding PlainDateTime;
- use `odt.to_plain()` instead of destructuring and rebuilding it;
- use `PlainDateTime::with_date`;
- add and use `PlainDateTime::with_time`;
- use `assume_offset` and `into_zoned_unchecked` at the corresponding abstraction boundaries.

Do not introduce a generic bounded-scalar framework. LocalSeconds wrapping EpochSecs is the useful
model: semantic composition without erasing type-specific invariants.

### Verification

- Domain modules no longer import modules that themselves require `PyObj` or `State` for the moved
  behavior.
- Rust unit tests for moved difference and Date behavior.
- Focused `since`, `until`, `total`, rounding, and Date-property tests.
- Build and lint.

## Phase 4: consolidate pattern formatting and parsing

### 4.1 Introduce a compiled-pattern value

Wrap compiled elements in a `CompiledPattern<'a>` with methods for:

- compilation;
- category validation;
- checking the ambiguous 12-hour format;
- formatting; and
- parsing into ParseState.

Keep the strict string policy explicit in the Python adapter. ISO parsing continues accepting
string subclasses according to its existing policy.

### 4.2 Add ParseState component methods

Move repeated component construction behind receiver methods:

```rust
parsed.date(required_fields_message)?;
parsed.time()?;
parsed.validate_weekday(date)?;
```

Make the required-date message explicit because existing classes intentionally differ. Do not
validate weekday for Instant unless the pure-Python reference changes; it currently does not.

Keep class-specific finalization in the class modules:

- required offset checks;
- required timezone-ID checks;
- offset/timezone agreement;
- gap/fold handling and disambiguation; and
- Python object allocation.

### 4.3 Consolidate formatting values

Provide receiver-oriented construction for pattern values, for example:

```rust
slf.to_plain()
    .pattern_values()
    .with_offset(slf.offset)
```

Hide dummy values for unavailable categories inside the pattern abstraction rather than repeating
large struct literals in six class modules. Preserve the existing flat representation if changing
it would introduce branches in the formatting hot path.

### Verification

- Existing Date, Time, PlainDateTime, Instant, OffsetDateTime, and ZonedDateTime pattern tests.
- Tests for required fields, invalid time/date values, weekday policy, required offsets/timezones,
  and the 12-hour warning.
- Compare representative pattern benchmarks and release binary size against the baseline.

## Phase 5: remaining shared adapters

### 5.1 Timestamp parsing

Add semantic helpers returning a domain Instant:

- `parse_timestamp`;
- `parse_timestamp_millis`; and
- `parse_timestamp_nanos`.

Reuse them from Instant, OffsetDateTime, and ZonedDateTime. Keep seconds accepting integer or float,
and keep millis/nanos integer-only. This is preferable to a generic `expect_number`.

### 5.2 Unit lexemes and ordered unit sequences

Use TotalUnit as the canonical parser for the complete plural-unit vocabulary, then narrow with
checked conversions to CalendarUnit or DifferenceUnit. Retain separate semantic enums.

Share ordered-sequence validation between CalendarUnitSet and DifferenceUnitSet:

- reject a bare string;
- reject empty input;
- reject duplicates;
- require decreasing unit size; and
- retain set-specific restrictions such as nanoseconds requiring seconds.

Avoid a generic UnitSet solely for source-line reduction. Benchmark any generic implementation
before keeping it.

Compose DateTime boundary parsing from non-raising Date and Time boundary matchers, with Day handled
by DateTimeBoundaryUnit. Preserve the special ambiguous `week` error.

### 5.3 Datetime C-API construction

Add safe extension methods or a small wrapper in `py::datetime` for:

- constructing a stdlib datetime from PlainDateTime and an explicit tzinfo;
- constructing a stdlib timedelta from TimeDelta; and
- constructing a fixed-offset stdlib timezone from Offset.

All parameters remain explicit. Return typed Owned wrappers where useful and centralize unsafe
C-API calls, normalization, and safety comments.

### Verification

- Focused timestamp, unit, boundary, and stdlib conversion tests.
- Verify timestamp error types and integer-subclass acceptance.
- Compare timestamp and stdlib conversion benchmarks.
- Build, lint, and Rust tests.

## Phase 6: nested datetime representation experiment

This phase is exploratory and must be kept only if it improves the code measurably.

Prototype:

```rust
struct OffsetDateTime {
    plain: PlainDateTime,
    offset: Offset,
}

struct ZonedDateTime {
    fixed: OffsetDateTime,
    tz: Arc<TimeZone>,
}
```

Alternative field names may be selected after inspecting destructuring and call sites. Prefer names
that make nesting readable without requiring aliases.

Expected benefits:

- the representation directly expresses “plain datetime + offset” and “fixed-offset datetime +
  timezone”;
- `to_plain` and `to_fixed_offset` become field projections;
- `to_instant`, checked construction, and zoned construction delegate through existing types;
- duplicated date/time/offset reconstruction disappears; and
- pickling and pattern-value construction compose naturally.

Possible costs:

- widespread `.plain.date` or `.fixed.plain.date` access;
- forwarding accessors that merely replace field duplication with method duplication;
- more cumbersome destructuring in binding code;
- changed layout, alignment, generated code, or debug output; and
- no binary-size benefit after optimization.

Measure before and after:

- `size_of` and `align_of` for domain and Python object-layout types;
- release-extension size;
- focused arithmetic, formatting, conversion, and allocation benchmarks;
- number and readability of direct record constructions;
- number of forwarding accessors required; and
- the complete call-site diff.

Keep the nested representation only if:

- domain and Python object sizes do not regress materially;
- benchmarks do not regress;
- construction and conversion code becomes simpler;
- nested field access remains tolerable; and
- forwarding boilerplate does not offset the removed duplication.

Otherwise discard or defer the experiment while keeping the receiver-oriented methods introduced
in earlier phases.

## Phase 7: final verification and documentation

Run:

```text
make QUIET=1 build
make QUIET=1 ci-lint
make QUIET=1 typecheck
make QUIET=1 test-rs
make QUIET=1 test-py
```

Then:

1. Run the pure-Python suite after `make QUIET=1 clean-ext`.
2. Rebuild the extension.
3. Run the cross-backend pickle compatibility matrix.
4. Rebuild in release mode and compare binary size and selected benchmarks with the baseline.
5. Check that generated docstrings are unchanged unless a deliberate Python behavior correction
   required a reference documentation change.
6. Verify every new commit is SSH-signed.

Update the changelog only for deliberate externally observable behavior changes, such as a newly
enforced strict-boolean policy. Pure internal refactoring and malformed-pickle safety hardening do
not otherwise require public API documentation changes.

