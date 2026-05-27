(benchmarks)=
(performance)=
# Performance

`whenever` optimizes for three goals that are sometimes in tension:

1. **Runtime speed** — operations should be as fast as possible
2. **Import time** — `import whenever` should feel instant
3. **Binary size** — the wheel should stay small for fast installs

These goals can conflict: aggressive inlining improves runtime speed but
increases binary size, which in turn inflates import time (more pages to
fault in from disk on first load). `whenever` targets a balance that
prioritizes runtime speed—since it dominates real-world workloads—while
keeping the binary compact enough that cold-start imports stay under 10 ms
on modern hardware.

---

## Runtime benchmarks

`whenever` is compared against Python's standard library (+ `dateutil`),
[Arrow](https://pypi.org/project/arrow/), and [Pendulum](https://pypi.org/project/pendulum/)
across nine common datetime operations.

Benchmarks are run with [pyperf](https://pyperf.readthedocs.io/) on an
Apple M1 Pro (32 GB, macOS 26.3) using Python 3.14.3 (PGO+LTO),
whenever 0.9.5, Arrow 1.4.0, and Pendulum 3.2.0.

### Timing

*Lower is better.  Bars exceeding the axis cutoff are annotated with `>`.*

```{raw} html
<picture>
  <source media="(prefers-color-scheme: dark)"
          srcset="_static/benchmarks/timing-dark.svg">
  <img src="_static/benchmarks/timing-light.svg"
       alt="Timing comparison — whenever vs stdlib, Arrow, Pendulum"
       width="100%">
</picture>
```

### Why is whenever faster?

- **No layering.** Arrow and Pendulum wrap Python's `datetime.datetime` rather
  than replacing it. Every operation pays the overhead of crossing extra Python
  abstraction layers that `whenever` avoids entirely.

- **Optimised parsing and formatting.** The Rust extension uses hand-written,
  single-pass byte-level parsers and formatters: no regex, no intermediate string
  objects, no `strptime`/`strftime` round-trips.

- **Front-loaded computation.** Every `ZonedDateTime` stores its UTC offset at
  construction time. Operations like "normalize to UTC" or "subtract two instants"
  become simple integer arithmetic with no timezone database lookup at operation
  time. This also makes timezone conversion and arithmetic consistently fast.

- **Compiled core.** The default wheel is a Rust CPython extension, giving
  C-level performance with safe, auditable code. The pure-Python fallback still
  benefits from the front-loaded computation model and outperforms Arrow on most
  simple operations.

```{admonition} What about the pure-Python version of whenever?
:class: hint

For simple operations — `now()`, ISO parsing,
UTC normalization — it is noticeably faster than Arrow and Pendulum. For
timezone-heavy operations such as `ZonedDateTime` construction or timezone
conversion it is slower, as those use pure-Python timezone code instead
of the C-optimized `zoneinfo` module.
Overall it is in the same ballpark as Arrow and Pendulum.
```

---

## Import time

A cold `import whenever` takes approximately 7–8 ms on an Apple M1.
The breakdown:

| Phase | Time |
|-------|------|
| Dynamic library loading (page faults) | ~5 ms |
| `PyDateTime_IMPORT` (imports `datetime`) | ~1.3 ms |
| Class and exception creation | ~0.5 ms |
| Python import machinery overhead | ~0.2 ms |

Dynamic library loading dominates. The OS must page-fault the `.so`/`.dylib`
into memory from disk on the first access after boot or cache eviction.
Subsequent imports in the same process are effectively free (~125 ns via
`sys.modules` lookup).

Strategies used to keep import time low:

- **LTO + strip** — `lto = "fat"` and `strip = true` reduce the binary to
  essentials, minimizing the number of pages that must be faulted in.
- **Lazy imports** — heavy standard library modules (`zoneinfo`, `strptime`,
  `pydantic`) are imported on first use via `OncePyObj`, not at module load.
- **Minimal module_exec** — the module initialization function does only
  what is strictly necessary: create types, intern strings, cache a few
  constants.

---

## Binary size

The release wheel's native extension is approximately 850 KB (macOS arm64).
Key contributors:

| Component | Size | Notes |
|-----------|------|-------|
| Method/slot wrapper functions | ~163 KB | 351 FFI entry points with `catch_unwind` |
| Standard library (backtrace, panic) | ~103 KB | Linked unconditionally by `std` |
| Class implementations | ~90 KB | Largest: `ZonedDateTime` (48 KB) |
| Interned strings and docstrings | ~96 KB | Stored in `__cstring` section |

Build settings that minimize size without sacrificing runtime speed:

- `lto = "fat"` — enables cross-crate dead code elimination
- `codegen-units = 1` — gives the optimizer a global view
- `strip = true` — removes symbol tables and debug info
- `#[inline(never)]` on large cold functions — prevents code duplication

---

## Running the benchmarks yourself

See `benchmarks/comparison/README.md` for setup instructions.

```shell
cd benchmarks/comparison
./run.sh --fast --update-docs   # quick run, update these charts
uv run python run_whenever.py --only now --fast   # single benchmark
```
