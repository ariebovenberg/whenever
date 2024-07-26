# Benchmark comparisons

## Running the benchmarks

```shell
python benchmarks/comparison/run_whenever.py
python benchmarks/comparison/run_stdlib.py
python benchmarks/comparison/run_pendulum.py
python benchmarks/comparison/run_arrow.py
```

Make sure that:
- `whenever` is built in release mode
- `time_machine` isn't installed. **Whenever** detects it and uses a slower code path if it is installed.

## Generating the graphs

- Copy the `graph-vega-config.json` into https://vega.github.io/editor/#/
- Comment-out parts to get the light and dark versions
- Export as svg
- Add `font-weight="bold"` to the first appearance of "Whenever"
- Set `width="500"` and `height="127"`

## Setup for the benchmark in the main README

The benchmarking graph in the main README was generated on
a 2021 M1 Pro Macbook, MacOS 14.5 on Python 3.12.2
