---
name: rust-ffi
description: "Rust FFI reference for whenever's `src/`: the `src/py/` safe wrappers (`PyObj`, `Owned`, `PyClass`, `PyReturn`), module `State`, method-registration macros, argument and kwarg parsing, binary slots and operator dispatch, error raising, and per-class gotchas. Use when writing or changing Rust code, adding a method or operator, or porting behavior from `_pywhenever.py`."
---

# Rust FFI Instructions

## FFI approach: `pyo3_ffi`, not `pyo3`

The low-level `pyo3_ffi` module is used, **not** `pyo3` directly.
This avoids overhead, complex abstractions, and gives full control over generated code.
The `src/py/` module provides safe wrappers. Key types:

| Type | Purpose |
|------|---------|
| `PyObj` | Core wrapper around `*mut PyObject`. Has `.extract()` (Copy types), `.extract_ref()` (ref types), `.type_()`, `.is_none()` |
| `Owned<T>` | RAII refcount wrapper. Use `Owned::new()` to take ownership, `.borrow()` for non-owning access |
| `PyClass<T>` | A Python class whose instances contain a Rust `T`; carries module state via `.state()` → `&State` |
| `PyRef<'a, T>` | A borrowed extension instance together with access to its `T` payload |
| `PyPayload` | Trait implemented by Rust values stored inside extension objects |
| `PyType` | A Python type object |
| `PyReturn` | Alias for `PyResult<Owned<PyObj>>` — the return type of Python-visible functions |
| `PyErrMarker` | Sentinel indicating the Python error indicator is set |

Key helpers in `src/py/`:
- `raise_value_err()`, `raise_type_err()`, `raise_key_err()` — raise Python exceptions
- `warn_with_class(cls, msg, stacklevel)` — emit a Python warning. Takes `PyObj`, not a raw pointer
- `handle_kwargs(fname, kwargs, handler)` — iterate kwargs with interned string matching
- `handle_no_args(fname, args)` — reject positional arguments
- `handle_one_arg(fname, args)` — extract exactly one positional arg, or raise TypeError
- `handle_opt_arg(fname, args)` — extract zero or one positional arg
- `handle_one_kwarg(fname, key, kwargs)` — extract a single optional kwarg by key
- `raise_mixed_args(fname)`, `raise_unexpected_kwarg(fname, key)` — keep common argument errors
  consistent in class-specific parsers
- `obj.expect_int(name)` — accept a Python int or subclass and raise
  `TypeError: {name} must be an integer` otherwise
- `find_interned(value, &[(string, value), ...])` — match a `PyObj` against an
  interned-string/value table, returning `Option`
- `match_interned_str(name, value, &[(string, value), ...])` — like `find_interned` but
  raises on no match
- `find_interned_with(value, handler)` — compose multiple interned-string matchers while
  retaining one global pointer-equality pass before Unicode comparison
- `find_interned_by(value, choices, eq)` — match one table using the equality function supplied
  by `find_interned_with`
- `match_type!(obj, type => |value| {...}, _ => {...})` — match an extension object against differently typed `PyClass<T>` values; prefix an arm with `ref` for non-`Copy` types
- `CompareOp::from_ffi(op).apply(a, b)` — apply a CPython rich-comparison operation to ordered Rust values
- `generic_alloc(cls, data)` — allocate a Python object with the given payload
- `PyAsciiStrBuilder::format()` — build a Python string without intermediate Rust `String`
- `PyTuple::with_len()` / unsafe `.init_item_unchecked()` — allocate and initialize tuple slots
- `.to_py()` via the `ToPy` trait — convert Rust values to Python objects
- `.to_tuple()` — convert a Python sequence to a tuple (prefer over `seq_len`+`seq_getitem`)
- `import(module_name)` — import a Python module (don't call `PyImport_ImportModule` directly)

## Module State pattern

`State` (in `src/pymodule/def.rs`) is a large struct stored on the Python module. It holds:
- `HeapType<T>` for each class (date_type, time_delta_type, etc.)
- Exception classes (`exc_repeated`, `exc_skipped`, etc.)
- Warning classes (`warn_deprecation`, `warn_days_not_always_24h`, etc.)
- Interned strings (`str_years`, `str_hour`, `str_units`, etc.)
- Unpickling functions

Access it via `cls.state()` from any `PyClass<T>`.

## Method registration

Methods are registered in a `static mut METHODS: &[PyMethodDef]` array using macros:
- `method0!` — no args
- `method1!` — one positional arg
- `method_vararg!` — variable positional args
- `method_kwargs!` — positional args + keyword args
- `classmethod1!`, `classmethod_kwargs!` — class methods

The function signatures must match the macro used. For `method_kwargs!`:
```rust
fn my_method(cls: PyClass<MyType>, slf: MyType, args: &[PyObj], kwargs: &mut IterKwargs) -> PyReturn
```

## Binary slots and operator dispatch

Rust binary slots that assume the first operand is their own type must not return
`NotImplemented` for another whenever class. We control all supported combinations, so
unsupported combinations should raise directly. This guarantees that those slots are never
called reflexively with whenever operands.

- Implement commutative combinations explicitly in the left operand's operator.
- Pure-Python itemized deltas own all of their datetime operator interoperability through
  reflected methods; Rust slots return `NotImplemented` for them.
- Consequently, equal owning modules in a Rust binary slot are sufficient proof that both
  operands are whenever extension types and that the left operand has the slot's declared type.
- Use `binary_operation()` for Rust binary slots that assume the first operand is their own
  type, so same-type operands, whenever extension types, unsupported combinations, and
  reflected calls from external types are handled consistently.
- Symmetric scalar slots such as `__mul__`, which explicitly inspect both operand orders,
  don't need this helper.

## Performance philosophy

- Avoid unnecessary allocations. Use helpers to build Python objects directly
  (e.g., `PyAsciiStrBuilder` instead of `format!()` → `to_py()`)
- Prefer `i32`/`i64` over `i128` when possible
- Use tuples (not lists) for immutable Python sequences
- For known strings, check pointer equality before falling back to direct Unicode comparison

## Common patterns

**Positional argument handling:**
```rust
// No positional args:
handle_no_args("method_name", args)?;
// Exactly one required arg:
let arg = handle_one_arg("method_name", args)?;
// Zero or one optional arg:
let maybe_arg = handle_opt_arg("method_name", args)?;
```

**Kwarg handling:**
```rust
handle_kwargs("method_name", kwargs, |key, value, eq| {
    if eq(key, str_some_kwarg) {
        // parse value
    } else {
        return Ok(false); // unrecognized kwarg
    }
    Ok(true)
})
```

**Single optional kwarg shortcut:**
```rust
let relative_to = handle_one_kwarg("total", state.str_relative_to, kwargs)?;
```

**Building deltas from kwargs (shift/add/subtract methods):**
Use `common::shift_args::parse_datetime_shift_kwargs()` for full datetime units or
`parse_calendar_shift_kwargs()` for calendar-only units. They return a typed
`DateTimeShift` or `CalendarShift`; the datetime parser's callback retains
class-specific kwargs such as `disambiguate` and warning suppression. For a
positional delta, use `parse_datetime_shift_arg()` or `parse_calendar_shift_arg()`;
these raise the method-specific type error if the argument is not a supported delta.

**Instant-like arguments:**
Use `common::instant::extract_instant()` when a non-Instant operand should fall through to another
operation, and `parse_instant_arg()` for a required Instant, OffsetDateTime, or ZonedDateTime
argument. Both normalize to the domain `Instant`.

**Interned string matching with custom errors:**
Use `find_interned` + manual error message when you need a specific error format.
Use `match_interned_str` when the default error format is acceptable.
For composed subsets, use `find_interned_with(value, |v, eq| ...)`, call
`find_interned_by(v, choices, eq)` for table-shaped subsets, and use `eq(v, expected)` for
individual strings. Do not call top-level `find_interned` separately for each subset: that would
perform Unicode comparison before later subsets have had their pointer-equality pass.

**Error handling:**
- `raise_value_err("msg")?` for ValueError
- `.ok_or_value_err("msg")?` on Options — for domain errors with specific messages
- `.ok_or_range_err()?` on Options — for generic out-of-range errors (preferred)
- `PyErrMarker()` (with parens) as the sentinel in `PyResult<T>`

## Type-specific gotchas

- **ZonedDateTime** doesn't implement `Ord` in Rust. Compare via `.to_instant()` for ordering.
  Non-Copy (contains `Arc<TimeZone>`). Uses `Arc::ptr_eq` + content equality for timezone comparison.
  DST-aware operations resolve `PlainDateTime::local_seconds()` through
  `TimeZone::mapping_for_local()` and `PlainDateTime::resolve_in()`.
- **LocalSeconds** is the local-wall-time coordinate; don't pass `EpochSecs` to local timezone
  lookup. `LocalMapping`, `Disambiguation`, and `ResolvePolicy` define gap/fold handling in the
  domain layer. Map `ResolveError` to Python exceptions only in binding code.
- **OffsetDateTime** compares by instant (`Instant` has `Ord`). Offset is an `Offset` scalar.
- Use `PlainDateTime::assume_offset()` when attaching a validated offset and
  `assume_offset_unchecked()` only when the represented instant is already known to be in range.
- **PlainDateTime** compares by local date+time. Has `Ord`.
- **Shift arguments** use `CalendarShift` and `DateTimeShift` in the domain layer. Prefer
  `Date::shift_by()` and `PlainDateTime::shift_by()` once a shift has been parsed. Python-facing
  component replacement starts with `PlainDateTime::components()` and uses
  `DateTimeComponents` in `classes::plain_datetime`.
- **TimeDelta** stores `secs: DeltaSeconds` + `subsec: SubSecNanos`. Use `.total_nanos() -> i128`.
  Has `.in_single_unit()` and `.in_exact_units()` for unit decomposition, and owns the pure
  `parse_iso()` implementation; map its parse errors to Python exceptions in the binding.
- Unit types name their role: `fmt::Precision`, `round::RoundUnit`, and
  `CalendarUnit`/`DifferenceUnit`/`ExactUnit` in `domain::difference`. Keep these domains distinct
  unless their parsing and behavior are demonstrably identical. Keep `common::fmt` free of Python
  argument parsing; `common::format_args` adapts Python `format_iso` arguments to its pure types.
- **ItemizedDelta/ItemizedDateDelta** use `DeltaField<T>` with the integer type's `MIN` value as
  the UNSET sentinel. `DeltaField` has custom `Debug` showing `<unset>` for sentinel values and
  `.as_option()` for checked extraction.

## Development philosophy

- **Avoid new macros** when the logic isn't complex enough to warrant them. Slightly
  repetitive code is preferred over macro abstractions that obscure intent.
- **Move logic into domain types**: put computation methods on the data type itself rather
  than in free functions. This keeps FFI glue thin.
- Use `.ok_or_range_err()` for out-of-range errors instead of custom messages.
- Use `// SAFETY:` comments for `unsafe` blocks per the Rust convention (exact casing matters).
- Don't downcast integer types without an explicit check or comment explaining why it's safe.
- `pub(crate)` not `pub` for internal visibility.
- **Leverage the type system** for safety: use distinct types to make invalid states
  unrepresentable. Prefer validated newtypes over raw primitives for constrained values.
