# Internal Rust API refactor plan

This is the canonical plan. It preserves the original recommendations and execution order while
recording decisions made during implementation. Where implementation has diverged from the original
recommendation, the difference is called out rather than silently rewriting the plan.

## Scope

Improve the private Rust API without changing the Python API or its behavior. The pure-Python
implementation remains the behavioral reference.

The refactor should:

- make FFI ownership and borrowing explicit;
- separate pure datetime behavior from CPython integration;
- normalize names, receivers, and argument order across the datetime types;
- introduce types for semantic distinctions currently carried by primitive values;
- consolidate duplicated parsing and operation plumbing only where the semantics are identical; and
- make checked operations the default while making unchecked operations conspicuous.

## Decisions made during implementation

- Keep `FromWrapped` and its automatic conversion to `T`, `&T`, or the full wrapper.
- Keep explicit `cls` and `slf` arguments. CPython supplies them, and retaining them avoids minor
  lookups.
- Keep `BinaryCall` with the field names `cls`, `slf`, and `other`.
- Reuse struct field names while destructuring where possible. Use `lhs` and `rhs` only where those
  names add meaning to the algorithm.
- Keep the short raw-pointer helpers `own()` and `borrow()`.
- Keep useful chainable methods, including Python-aware inherent methods in `classes/`; the module
  boundary is about responsibility, not method syntax.
- Prefer chainable conversions over `from_*` associated functions when the chain remains clear.
- Keep the cheap `Instant` to `OffsetDateTime` timezone projection available; do not require a
  `ZonedDateTime` and its timezone ownership overhead.
- Use `LocalSeconds` for the local-wall-time coordinate.
- Keep arithmetic checked under the short name and reserve `_unchecked` for bypassed validation.
- For known Python strings, use pointer equality followed by direct Unicode comparison rather than
  fallible Python-level equality.

## Refinements

### FFI wrappers

Keep automatic casting. The selected vocabulary is:

 Current           Selected
━━━━━━━━━━━━━━━━  ━━━━━━━━━━━━━━━━━━━
 PyWrapped         PyPayload
────────────────  ───────────────────
 PyWrap<T>         PyObjectLayout<T>
────────────────  ───────────────────
 ExtType<T>        PyClass<T>
────────────────  ───────────────────
 Wrapped<'a, T>    PyRef<'a, T>
────────────────  ───────────────────
 FromWrapped       FromWrapped

`FromWrapped` continues automatically converting to `T`, `&T`, or `PyRef<T>` according to the
callback signature.

Explicit cls and slf also stay. You’re right: although the class can be recovered
from slf, CPython already supplies it for several calling conventions, and
retaining it avoids unnecessary type lookups.

I’d revise BinaryCall accordingly:

enum BinaryCall<'a, T: PyPayload> {
    SameType {
        cls: PyClass<T>,
        slf: PyRef<'a, T>,
        other: PyRef<'a, T>,
    },
    ExtTypes {
        cls: PyClass<T>,
        slf: PyRef<'a, T>,
        other: PyObj,
    },
    OtherTypes,
}

This preserves automatic classification while replacing positional payloads with named fields.
`State` remains available through `cls.state()` without storing a second reference in the enum.

### Owned<T> effects

Removing DerefMut costs nothing today: there are no uses of it. It only removes
the ability to accidentally replace the inner pointer without adjusting refcounts.

Removing general map() is also nearly free. There are only two uses outside its
own implementation:

- OffsetDateTime::to_stdlib() can use owned.into_obj().
- new_class() can use the existing typed unchecked cast.

So I would retain convenient, pointer-preserving operations:

Owned<T>::into_obj()
Owned<T>::cast_unchecked<U>()

and remove only the unrestricted closure-based transformation. If a generic escape
hatch remains useful, call it unsafe map_unchecked().

The rest becomes:

- py_owned() → into_raw()
- unsafe Owned::from_owned_ptr(...)
- failed downcasts return Result<Owned<U>, Owned<T>>
- keep the short .own() and .borrow() pointer helpers

The ExtType::state() lifetime correction should require no call-site changes.
PyModule::state() has only a handful of initialization/traversal/cleanup uses, so
making that lifecycle access explicitly unsafe or wrapping it in ModuleStateSlot
is also modest.

### Domain/core versus binding-side impls

Having inherent impl blocks in classes/ is reasonable and preserves chaining:

// domain-or-core/instant.rs
impl Instant {
    fn to_offset_in(self, tz: &TimeZone) -> Option<OffsetDateTime> { ... }
}

// classes/instant.rs
impl Instant {
    fn to_stdlib_datetime(self, api: &PyDateTime_CAPI) ->
    PyResult<Owned<PyDateTime>> {
        ...
    }

    fn into_zoned_py(
        self,
        tz: Arc<TimeZone>,
        cls: PyClass<ZonedDateTime>,
    ) -> PyReturn {
        ...
    }
}

Rust permits inherent impls outside the module defining the type. The useful rule
is therefore about responsibility, not whether the method is inherent:

- the pure layer owns semantics, validation, arithmetic, parsing bytes, and timezone
  resolution.

- classes/ owns Python argument parsing, warnings/exceptions, allocation,
  refcounts, stdlib conversion, pickling, and thin chainable adapters.

- Binding-side inherent methods are fine when their names identify the boundary
  and they delegate semantic decisions to the pure layer.

The pure layer is named `domain`, as originally recommended, because the repository uses the
standard `core::ffi`, `core::ptr`, and `core::mem` paths extensively. The name avoids ambiguity
while the responsibility boundary keeps CPython integration in `classes/`.

Moving a type definition alone is not sufficient. Every CPython-independent inherent method should
move with it. For example, `Date` construction, calendar arithmetic, boundary calculations, ISO
parsing and formatting, and composition with `Time` belong in the pure layer. Apply the same audit
to `Time`, `PlainDateTime`, and `TimeDelta`. Only methods involving Python objects, module `State`,
the datetime C API, Python allocation, or Python error translation should remain in `classes/`.

### Chainable timezone conversions

Keep the cheap Copy projection:

Instant::to_offset_in(&TimeZone) -> Option<OffsetDateTime>

This is a better name for the current Rust to_tz() because it accurately describes
the result.

A chainable Zoned conversion can still avoid unnecessary Arc increments by
consuming the existing Arc:

Instant::in_timezone(
    self,
    tz: Arc<TimeZone>,
) -> Option<ZonedDateTime> {
    self.to_offset_in(&tz)?.into_zoned_unchecked(tz)
}

The Arc is borrowed for lookup and then moved into ZonedDateTime; no clone is
necessary. The low-level pieces remain available where returning the Copy
OffsetDateTime is preferable.

For the arithmetic helper:

- Instant::offset() → Instant::shift_by_offset()
- EpochSecs::offset() → EpochSeconds::shift_by_offset()
- saturating_offset() → saturating_shift_by_offset()

### Checked by default

Agreed. Checked arithmetic should use the short name and return Option/Result;
unchecked operations should stand out:

delta.mul(factor) -> Option<Self>
instant.shift(delta) -> Option<Self>
date.shift(months, days) -> Option<Self>

TimeDelta::from_nanos_unchecked(...)
OffsetDateTime::new_unchecked(...)

That means DateTimeDelta::checked_mul() should become mul(), rather than adding
checked_ elsewhere.

Other core naming I’d include:

 Current                           Revised
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━  ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
 internal DateTime                 PlainDateTime
────────────────────────────────  ────────────────────────────────────────────────
 utc_datetime()                    to_utc_plain()
────────────────────────────────  ────────────────────────────────────────────────
 local()                           to_plain()
────────────────────────────────  ────────────────────────────────────────────────
 instant()                         to_instant()
────────────────────────────────  ────────────────────────────────────────────────
 fixed_offset()                    to_fixed_offset()
────────────────────────────────  ────────────────────────────────────────────────
 Instant::to_tz() returning ODT    to_offset_in()
────────────────────────────────  ────────────────────────────────────────────────
 assume_tz_unchecked()             into_zoned_unchecked()
────────────────────────────────  ────────────────────────────────────────────────
 diff()                            difference()
────────────────────────────────  ────────────────────────────────────────────────
 Disambiguate                      Disambiguation
────────────────────────────────  ────────────────────────────────────────────────
 Disambiguate::Raise               Disambiguation::Reject
────────────────────────────────  ────────────────────────────────────────────────
 Ambiguity                         LocalMapping
────────────────────────────────  ────────────────────────────────────────────────
 new_clamp_days()                  new_clamped()
────────────────────────────────  ────────────────────────────────────────────────
 from_longs()                      remove from domain; validate in component
                                   parsing
────────────────────────────────  ────────────────────────────────────────────────
 pyhash()                          python_hash() in binding code
────────────────────────────────  ────────────────────────────────────────────────
 lazy format_iso()                 iso_format()
────────────────────────────────  ────────────────────────────────────────────────
 allocated fmt_iso()               to_iso_string()
────────────────────────────────  ────────────────────────────────────────────────
 scanner read_iso()                parse_prefix()
────────────────────────────────  ────────────────────────────────────────────────
 whole-input parse()               parse_exact()

## Execution plan

### 1. FFI correctness and ownership hardening — complete

Commit: `e43466c Harden Rust FFI helpers`

Make the behavior changes before broad file movement:

- Change is_truthy() to PyResult<bool> and update its call sites.
- For general Python equality, propagate exceptions instead of treating them as false. For keyword
  and interned-string matching, both operands known to be strings use pointer equality followed by
  direct Unicode comparison, which is infallible and avoids Python-level dispatch.

- Remove unused DerefMut.
- Replace unrestricted Owned::map() with into_obj() and existing typed casts.

- Rename py_owned() to into_raw().
- Add unsafe Owned::from_owned_ptr().
- Make failed owned downcasts return the original owner.
- Tie PyClass::state() to &self.
- Replace PyModule::state()’s manufactured mutable lifetime with explicit
  lifecycle access.
- Keep active module state shared and read-only. Fields requiring mutation provide their own
  internal-mutability synchronization.
- Provide the same raising convenience for relevant `Result` values that `Option` has.

Verification:

- Add tests for fallible Python operations where applicable.
- Run focused Python tests, make QUIET=1 build, and make QUIET=1 ci-lint.

### 2. Rename the FFI types — complete

Commit: `b701121 Clarify Rust FFI type APIs`

Apply the coherent naming together:

- PyWrapped → PyPayload
- PyWrap → PyObjectLayout
- ExtType → PyClass
- Wrapped → PyRef
- retain FromWrapped
- BinaryOperands → BinaryCall

Keep automatic callback casting and explicit cls/slf.

Convert the binary enum to named fields without changing its classification or
lookup behavior. Prefer its field names `cls`, `slf`, and `other` at destructuring sites.

The internal rust-ffi skill uses the selected vocabulary.

Verification:

- Build and lint.
- Run Rust tests plus representative operator tests for every datetime/delta
  class.

### 3. Establish the domain boundary — complete

Create:

src/domain/
    mod.rs
    scalar.rs
    date.rs
    time.rs
    plain_datetime.rs
    instant.rs
    offset_datetime.rs
    zoned_datetime.rs
    delta.rs
    local.rs
    shift.rs

Initially use re-exports so moves can happen one type at a time.

Enforce this dependency rule:

> The pure layer must not import crate::classes, crate::py, crate::pymodule, docstrings, or
> pyo3_ffi.

Move in dependency order:

1. Scalar newtypes and constants.
2. Date and Time.
3. Delta value types.
4. PlainDateTime and Instant.
5. OffsetDateTime.
6. ZonedDateTime.

Move Python-specific DeltaField conversion impls out of scalar.rs. Split mixed
common modules only where necessary:

- pure rounding modes/calculations versus Python round-argument parsing;
- pure difference calculations versus Python unit parsing;
- pure formatting chunks versus Python string construction.

Leave thin, chainable Python adapter impls in classes/.

Move complete pure implementations, not only type definitions. In particular, move `Date`'s
constructors, calendar arithmetic, boundary calculations, ISO parsing and formatting, and
composition with `Time`. Apply the same dependency-based audit to `Time`, `PlainDateTime`, and
`TimeDelta`. Binding-side inherent methods remain appropriate when they require Python objects,
module state, the datetime C API, allocation, or Python error translation.

Verification after each moved type:

- Build and lint.
- Run that class’s Python test file.
- Run Rust unit tests for the moved domain code.

### 4. Normalize pure-layer names and arithmetic — complete

Once definitions live in the pure layer, rename:

- DateTime → PlainDateTime
- projections such as to_plain(), to_instant(), to_utc_plain()
- Instant::offset() → shift_by_offset()
- Instant::to_tz() → to_offset_in()
- DateTimeDelta::checked_mul() → mul()
- stdlib adapters to to_stdlib_date/time/datetime() and from_stdlib_*()

The Python callbacks retain the public `to_stdlib` spelling, while their internal adapters now use
the type-specific names above.

Keep checked operations unmarked and reserve _unchecked for bypassed validation.

Also standardize receivers:

- Copy values take self.
- ZonedDateTime generally takes &self unless consuming it intentionally.

Verification:

- Compile-driven call-site migration.
- Full focused tests for Date, Time, PlainDateTime, Instant, OffsetDateTime, and
  ZonedDateTime.

Completed with all 79 Rust tests, build and lint, and 2,130 focused Python tests passing (one
skipped).

### 5. Introduce the local-time model — planned

Add:

struct LocalSeconds(...);

enum LocalMapping {
    Unique { offset: Offset },
    Gap {
        transition: LocalSeconds,
        before: Offset,
        after: Offset,
    },
    Fold {
        transition: LocalSeconds,
        before: Offset,
        after: Offset,
    },
}

enum Disambiguation {
    Compatible,
    Earlier,
    Later,
    Reject,
}

enum ResolvePolicy {
    Disambiguate(Disambiguation),
    PreserveOffset(Offset),
}

Then:

- Change timezone local lookup from EpochSeconds to LocalSeconds.
- Consolidate the four localization implementations into one domain resolver.
- Introduce a domain error enum for gap, fold, and range failures.
- Map those errors to Python exceptions in classes/zoned_datetime.rs.
- Add chainable to_offset_in(), in_timezone(), and into_zoned_unchecked() without
  unnecessary Arc::clone() calls.

Verification:

- Rust tests around every gap/fold strategy and range edge.
- tests/test_zoned_datetime.py, timezone parsing tests, and relevant TimeDelta
  since/until tests.

### 6. Consolidate component and shift arguments — planned

Introduce:

DateTimeComponents
CalendarShift
DateTimeShift

Then:

- Replace set_components_from_kwargs()’s mutable output parameters.
- Make ItemizedDelta::to_components() return DateTimeShift.
- Add shared extract_datetime_shift() and calendar-only extraction.
- Add shared keyword-unit parsing returning a value rather than mutating three
  outputs.

- Retain class-specific parsing for disambiguate, stale-offset suppression, and
  naive-arithmetic warnings.

- Replace boolean parser controls with small enums such as AllowedSubsecondUnits.

Verification:

- Parameterized tests covering every accepted delta representation for
  PlainDateTime, OffsetDateTime, and ZonedDateTime.

- Tests for mixed positional/keyword errors and warning-suppression kwargs.

### 7. Consolidate instant-like and unit logic — planned

Add one shared extraction function for Instant, OffsetDateTime, and ZonedDateTime,
then use it in:

- rich comparisons;
- difference();
- binary subtraction.

Add a small comparison-operation abstraction to remove repeated Py_EQ through
Py_GE matching.

Then do the lower-priority naming pass:

- boundary units;
- formatting precision;
- rounding units;
- calendar/exact unit names;
- rounding-increment types;
- ddelta/tdelta fields.

Avoid merging all unit enums immediately; first rename them according to their
semantic role, then consolidate only demonstrably duplicated parsing.

### 8. Final verification — planned

Run the authoritative workflows:

make QUIET=1 build
make QUIET=1 ci-lint
make QUIET=1 typecheck
make QUIET=1 test-rs
make QUIET=1 test-py

Also run pure-Python tests after make QUIET=1 clean-ext, then rebuild, because
moving domain logic must not accidentally change Rust/Python parity.

This sequence keeps each stage independently reviewable: correctness first,
mechanical FFI naming second, architectural movement third, and semantic
abstractions only after the dependency boundary is visible.
