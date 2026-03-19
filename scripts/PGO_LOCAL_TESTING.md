# Local PGO Testing Guide

To verify the PGO performance improvement locally before committing CI changes:

```bash
bash scripts/test_pgo_locally.sh
```

This script will:
1. **Build baseline** — compile the Rust extension in **release mode** (no PGO)
2. **Build instrumented** — compile with profile-generate flags (release mode)
3. **Profile** — run `scripts/pgo_profile.py` (200 iterations) to collect branch frequencies
4. **Merge profiles** — combine raw `.profraw` files into `.profdata`
5. **Build optimized** — compile with profile-use flags (release mode)
6. **Benchmark** — measure both wheels on a representative workload

The output shows improvement percentage measured with **pyperf** (statistically rigorous microbenchmarking). Expected: **5–15% faster** (or more on longer workloads).

## Example output

```
=== Step 6: Benchmark baseline vs. PGO (pyperf) ===

⚠ Running baseline benchmark...
.....................
whenever ops: Mean +- std dev: 283 ns +- 3 ns
⚠ Running PGO benchmark...
.....................
whenever ops: Mean +- std dev: 265 ns +- 3 ns

+--------------+----------+----------------------+
| Benchmark    | baseline | pgo                  |
+==============+==========+======================+
| whenever ops | 283 ns   | 265 ns: 1.07x faster |
+--------------+----------+----------------------+
✓ Benchmark complete
```

(This shows ~7% improvement. On larger, more representative workloads, improvements are typically higher.)

## Options

```bash
bash scripts/test_pgo_locally.sh --cleanup
```

Removes `pgo-test-work/` directory after completion.

## Requirements

- Rust 1.93+ with llvm-tools component
- Python 3.10+ (system or pyenv; uv will download optimized managed Python for profiling)
- uv: `pip install uv` (for managed Python and pyperf)
- C compiler (automatically detected)

## Build times

On macOS (M1 chip, release mode):
- Baseline: ~18s
- Instrumented: ~19s
- Profiling: ~20s (200 iterations)
- Merge: <1s
- Optimized: ~18s
- **Total: ~2 minutes**

## Implementation details

- **Release mode builds**: Uses `python3 setup.py build_rust --inplace --release` to ensure fair comparison with CI
- **Benchmark approach**: Uses `pyperf.Runner()` with `bench_time_func()` for statistically rigorous microbenchmarking
  - Each run spawns subprocesses and collects multiple samples with warmup and cooldown
  - Provides mean, std dev, and significance testing (shows "not significant" if differences are too small)
- **Managed Python**: The profiling step (Step 3) uses `uv run`, which ensures optimizations from uv's managed Python
- **Extension loading**: Each benchmark run has a separate copy of the whenever package with the specific .so file
  - Prevents caching issues between baseline and PGO measurements
- Profile data is **specific to your Rust toolchain** and **reproducible** (fixed seed in pgo_profile.py)
- On Linux/Windows, the same approach works; just ensure llvm-tools is installed
