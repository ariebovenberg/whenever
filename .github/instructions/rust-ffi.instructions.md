---
applyTo:
  - "src/**"
---

# Rust FFI Instructions

## FFI approach: `pyo3_ffi`, not `pyo3`

The low-level `pyo3_ffi` module is used, **not** `pyo3` directly.
This avoids overhead, complex abstractions, and gives full control over generated code.
The `src/py/` module provides safe wrappers. Key types:

| Type | Purpose |
|------|---------|
| `PyObj` | Core wrapper around `*mut PyObject`. Has `.extract()`, `.type_()`, `.is_none()` |
| `Owned<T>` | RAII refcount wrapper. Use `Owned::new()` to take ownership, `.borrow()` for non-owning access |
| `HeapType<T>` | A Python heap type that carries module state via `.state()` → `&State` |
| `PyType` | A Python type object. `.same_module()` checks if two types belong to the same module |
| `PyReturn` | Alias for `PyResult<Owned<PyObj>>` — the return type of Python-visible functions |
| `PyErrMarker` | Sentinel indicating the Python error indicator is set |
| `ContextVarBool` | `Copy` wrapper for a context variable. Has `.get() -> PyResult<bool>` |

Key helpers in `src/py/`:
- `raise_value_err()`, `raise_type_err()`, `raise_key_err()` — raise Python exceptions
- `warn_with_class(cls, msg, stacklevel)` — emit a Python warning. Takes `PyObj`, not a raw pointer
- `handle_kwargs(fname, kwargs, handler)` — iterate kwargs with interned string matching
- `handle_one_arg(fname, args)` — extract exactly one positional arg, or raise TypeError
- `handle_opt_arg(fname, args)` — extract zero or one positional arg
- `handle_one_kwarg(fname, key, kwargs)` — extract a single optional kwarg by key
- `find_interned(value, handler)` — match a PyObj against interned strings, returns `Option`
- `match_interned_str(name, value, handler)` — like `find_interned` but raises on no match
- `generic_alloc(type_, data)` — allocate a Python object with given data
- `PyAsciiStrBuilder::format()` — build a Python string without intermediate Rust `String`
- `PyTuple::with_len()` / `.init_item()` — safe tuple construction
- `.to_py()` via the `ToPy` trait — convert Rust values to Python objects
- `.to_tuple()` — convert a Python sequence to a tuple (prefer over `seq_len`+`seq_getitem`)
- `import(module_name)` — import a Python module (don't call `PyImport_ImportModule` directly)

## Module State pattern

`State` (in `src/pymodule/def.rs`) is a large struct stored on the Python module. It holds:
- `HeapType<T>` for each class (date_type, time_delta_type, etc.)
- Exception classes (`exc_repeated`, `exc_skipped`, etc.)
- Warning classes (`warn_deprecation`, `warn_days_not_always_24h`, etc.)
- `ContextVarBool`s for suppressing warnings
- Interned strings (`str_years`, `str_hour`, `str_units`, etc.)
- Unpickling functions

Access it via `cls.state()` from any `HeapType<T>`. **Unpack needed fields at the top
of the function** to avoid repeated `state.` access:
```rust
let &State {
    date_type,
    str_disambiguate,
    exc_skipped,
    time_delta_type,
    ..
} = cls.state();
```

When adding new fields to State, update **three** places: the struct definition,
the initialization in `init_module`, and `Py_CLEAR` in the traverse/clear functions.

## Method registration

Methods are registered in a `static mut METHODS: &[PyMethodDef]` array using macros:
- `method0!` — no args
- `method1!` — one positional arg
- `method_vararg!` — variable positional args
- `method_kwargs!` — positional args + keyword args
- `classmethod1!`, `classmethod_kwargs!` — class methods

The function signatures must match the macro used. For `method_kwargs!`:
```rust
fn my_method(cls: HeapType<MyType>, slf: MyType, args: &[PyObj], kwargs: &mut IterKwargs) -> PyReturn
```

## Performance philosophy

- Avoid unnecessary allocations. Use helpers to build Python objects directly
  (e.g., `PyAsciiStrBuilder` instead of `format!()` → `to_py()`)
- Prefer `i32`/`i64` over `i128` when possible
- Use `u8::eq_ignore_ascii_case()` instead of manual case checks
- Use tuples (not lists) for immutable Python sequences
- Check pointer equality before falling back to `py_eq` for comparisons

## Common patterns

**Positional argument handling:**
```rust
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
Use `handle_delta_unit_kwargs()` for full datetime units, or
`handle_date_delta_unit_kwargs()` for calendar-only units. These build typed
`DeltaMonths`/`DeltaDays`/`TimeDelta` directly from kwargs.

**Structured since/until kwarg parsing:**
```rust
let SinceUntilKwargs { units, round_mode, round_increment } =
    SinceUntilKwargs::parse(fname, state, kwargs)?;
```

**Unit sets:** Use the appropriate bitfield type:
- `CalUnitSet` — calendar units only (years, months, weeks, days)
- `ExactUnitSet` — exact units only (weeks through nanoseconds)
- `DeltaUnitSet` — all delta units (calendar + exact)

Each has `from_py()` for parsing from Python, `.iter()`, `.smallest()`, `.contains()`.

**Interned string matching with custom errors:**
Use `find_interned` + manual error message when you need a specific error format.
Use `match_interned_str` when the default error format is acceptable.

**Error handling:**
- `raise_value_err("msg")?` for ValueError
- `.ok_or_value_err("msg")?` on Options — for domain errors with specific messages
- `.ok_or_range_err()?` on Options — for generic out-of-range errors (preferred)
- `PyErrMarker()` (with parens) as the sentinel in `PyResult<T>`

## Type-specific gotchas

- **ZonedDateTime** doesn't implement `Ord` in Rust. Compare via `.instant()` for ordering.
  Uses `TzPtr::is_same_tz()` for timezone comparison (not `==`).
  DST-aware operations need `ambiguity_for_local()` resolution.
- **OffsetDateTime** compares by instant (`Instant` has `Ord`). Offset is an `Offset` scalar.
- **PlainDateTime** (`DateTime` in Rust) compares by local date+time. Has `Ord`.
- **TimeDelta** stores `secs: DeltaSeconds` + `subsec: SubSecNanos`. Use `.total_nanos() -> i128`.
  Has `.in_single_unit()` and `.in_exact_units()` for unit decomposition.
- **ItemizedDelta/ItemizedDateDelta** use `DeltaField<T>` with `i32::MAX` as the UNSET sentinel.
  `DeltaField` has custom `Debug` showing `<unset>` for sentinel values.

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
