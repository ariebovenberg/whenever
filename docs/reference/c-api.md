---
myst:
  html_meta:
    description: >-
      The whenever C API for extension modules: the C_API_v1 capsule, its
      records and functions, the threading and versioning contract, and the
      include/whenever.h header.
---

(c-api)=
# C API

The C API lets an **extension module** read and build `whenever` values
without a Python call per value. An extension module is compiled code that
Python imports, in C, Rust, or another language: a dataframe library that
converts a column of `ZonedDateTime`s, or a Rust crate that converts to
[jiff](https://docs.rs/jiff) types.

If you write Python, you don't need this page. The methods of each type are
your API, and {ref}`to_bytes() <binary-format>` covers a compact,
language-neutral payload.

If you maintain such an extension, read on. The API is a table of function
pointers, published as the capsule `whenever.C_API_v1`. Through it, each
of the seven core types converts to and from a plain C record. Only the
**Rust extension** publishes the table. The **pure-Python backend** has no
such attribute, so a consumer falls back to `to_bytes()` and
`from_bytes()`, which both backends provide and which carry the same
fields.

Rust consumers use the [`pyo3-whenever`](https://github.com/ariebovenberg/pyo3-whenever)
crate, which wraps the table and the fallback behind one API and converts
to and from jiff types.

## Importing the table

```c
#include "whenever.h"

const Whenever_CAPI *api =
    (const Whenever_CAPI *)PyCapsule_Import(WHENEVER_CAPSULE_NAME, 0);
if (api == NULL) {
    /* AttributeError: the pure-Python backend is installed */
}
if (strcmp(api->magic, WHENEVER_CAPSULE_NAME) != 0
    || api->struct_size < (int32_t)sizeof(Whenever_CAPI)) {
    /* not the table this header describes */
}
```

`PyCapsule_Import` imports `whenever` and reads the attribute, so a module
that imports per interpreter gets that interpreter's table. Every function
takes the table as its first argument; pass the pointer the capsule handed
out, never a copy of the struct.

The table and the type objects belong to the `whenever._whenever` module.
A consumer that keeps the pointer past the import holds a reference to that
module alongside it, so that an unload of `whenever` cannot free the table
under it. `pyo3-whenever` does.

## Records

Each record holds the fields of the {ref}`binary format <binary-format>` by
value, in host byte order: `Whenever_Date`, `Whenever_Time`,
`Whenever_PlainDateTime`, `Whenever_Instant`, `Whenever_OffsetDateTime`,
`Whenever_ZonedDateTime`, and `Whenever_TimeDelta`. The header lists each
field's range.

A `Whenever_ZonedDateTime` carries its time zone ID as a byte range the
record never owns: a pointer and a length, not NUL-terminated. Extracted,
the pointer leads into the object and stays valid while the caller holds a
reference to it. Passed to a constructor, it is the caller's memory, read
during the call only; `whenever` keeps its own copy of the ID, so a `&str`
borrowed from a jiff time zone, a Rust `String`, or a C literal all serve.
A system time zone without a time zone ID extracts with a null pointer and
cannot be constructed.

`SYSTEM_TZ` has no counterpart in the API. It names a time zone at call
time, in Python; the `ZonedDateTime` it produces carries the resolved time
zone and extracts like any other.

## Functions

**Extractors** such as `date_extract` fill a record from an object. They
return `0` when the object is exactly the type, and `1` otherwise, writing
nothing and setting no exception, so trying each type in turn costs no
more than the type checks. The table's type slots (`DateType` and the others)
serve a consumer that dispatches on `Py_TYPE(obj)` first; the types have no
subclasses.

**Constructors** such as `date_new` build an object from a record, returning
a new reference, or NULL with `ValueError` set for a field out of range.
A `ZonedDateTime` has two: `zoned_datetime_from_instant`, which places an
instant in a named time zone using `whenever`'s own time zone data, and
`zoned_datetime_new`, which takes a record as written. `zoned_datetime_new`
resolves the stored offset against the time zone rules the way
`ZonedDateTime.from_bytes()` does, with the `offset_mismatch` and
`disambiguation` policies passed as the integers the header's enums define.
Both are required; there is no implicit default.

## Threads

Constructors require an attached thread state (the GIL, on default builds),
like any C API call that creates objects.

Extractors do not. They make no CPython call: the type check reads the
object's type pointer, and the payload is immutable for the object's
lifetime. A consumer may run them on any thread, with the GIL released.
It must hold a strong reference to the object during the call, and for as
long as it reads the time zone ID the record points into.

## Versioning

The records never change, and within v1 the table only grows at the end.
`struct_size` says how far the providing build's table goes, and
`version_minor` is bumped when fields are appended; check both before using
a field this header did not list when the consumer was built. A breaking
change would ship as a second capsule next to this one, under a new name,
with v1 kept for a deprecation window. See {ref}`stability`.

## The header

The header is not shipped in the wheel: copy it from the repository, or
declare the structs in the consumer's own language, as `pyo3-whenever`
does.

```{literalinclude} ../../include/whenever.h
:language: c
```
