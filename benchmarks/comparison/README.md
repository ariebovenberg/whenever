# Comparison benchmarks

Compares `whenever` against `stdlib` (+ `dateutil`), `whenever` (pure Python),
`arrow`, and `pendulum` across 9 individual operations, plus a
memory-per-instance report.

## Setup

The suite has its own isolated environment managed by `uv`, pinning
`whenever==0.9.5` from PyPI (the latest stable optimized Rust wheel) so that
the local dev version is not accidentally used.

```shell
cd benchmarks/comparison
uv sync          # creates .venv with Python 3.14 and all dependencies
```

## Running benchmarks

### Proper run (final results)

```shell
./run.sh              # full pyperf run — slow but reliable
./run.sh --fast       # faster run, fewer samples — good for quick checks
./run.sh --update-docs   # also write SVG charts to docs/_static/benchmarks/
./run.sh --fast --update-docs
```

Results land in `results/` and a comparison table is printed at the end,
followed by a memory-per-instance report and chart generation.

### Individual benchmarks

Each script can be run directly.  Use `--fast` while iterating and
`--only NAME` to run a single benchmark (or `--only a,b,c` for multiple):

```shell
uv run python run_whenever.py --fast
uv run python run_whenever.py --only now --fast
uv run python run_whenever.py --only now,parse_iso
```

Available benchmark names (identical across all five scripts):

| Name              | Operation                                       |
|-------------------|-------------------------------------------------|
| `now`             | Get current UTC/instant time                    |
| `parse_iso`       | Parse an ISO 8601 offset datetime string        |
| `instantiate_zdt` | Construct a timezone-aware datetime             |
| `shift`           | Add hours + minutes (exact/DST-safe arithmetic) |
| `to_tz`           | Convert between timezones                       |
| `normalize_utc`   | Normalize to UTC / instant                      |
| `format_iso`      | Format to ISO 8601 string                       |
| `difference`      | Subtract two UTC instants                       |
| `calendar_shift`  | Add years + months (calendar arithmetic)        |

Scripts:

| Script                  | Library                       |
|-------------------------|-------------------------------|
| `run_whenever.py`       | whenever (Rust extension)     |
| `run_whenever_pure.py`  | whenever (pure Python)        |
| `run_stdlib.py`         | stdlib + dateutil             |
| `run_arrow.py`          | Arrow                         |
| `run_pendulum.py`       | Pendulum                      |

Each script also contains a commented-out `compound` benchmark that chains
several operations (parse → normalize → shift → format), mirroring the
original "various operations" comparison used for the README graph.
Uncomment the relevant block in each file to include it.

> **Note on `shift`:** `stdlib`'s `+ timedelta` is DST-*unsafe*, so it
> has an unfair speed advantage there.  `whenever`'s `add()` is DST-safe.

### Memory per instance

```shell
uv run python memory.py
uv run python memory.py -o results/memory.json   # also write JSON
```

### Generating charts

Reads `results/result_*.json` and `results/memory.json`, writes
`timing-light.svg`, `timing-dark.svg`, `memory-light.svg`, `memory-dark.svg`:

```shell
uv run python charts.py                                    # to charts/
uv run python charts.py --output ../../docs/_static/benchmarks/  # update docs
```

## Verifying the Python build

pyperf spawns worker processes using `sys.executable`, which is the `.venv`
Python resolved by `uv run`.  `run.sh` prints build flags at startup to
confirm the interpreter was built with PGO (Profile-Guided Optimisation).

If you see a warning, install the python-build-standalone interpreter, which
ships with PGO+LTO enabled:

```shell
uv python install cpython-3.14
```

## Caveats

- Make sure `time_machine` is **not** installed — `whenever` detects it and
  uses a slower code path.
- For the most reliable numbers, run on a quiet machine and consider
  `python -m pyperf system tune` first.

## Generating the README graph

- Copy `graph-vega-config.json` into <https://vega.github.io/editor/#/>
- Comment-out parts to get the light and dark versions
- Export as SVG, add `font-weight="bold"` to the first "Whenever" label
- Set `width="500"` and `height="125"`

The graph in the main README was generated on a 2021 M1 Pro MacBook,
macOS 15.6.1, Python 3.13.3 (optimized build).
