#!/usr/bin/env bash
# Measure what profile-guided optimization (PGO) buys: build the extension
# plain and with PGO, and compare both on the comparison benchmarks, which
# the training workload does not share. Run it through `make bench-pgo`.
# The PGO build stays in place afterwards.
set -euo pipefail
work="$PWD/target/pgo"
rm -rf "$work"
mkdir -p "$work/profiles"

bench() {
    python benchmarks/comparison/run_whenever.py --fast --quiet -o "$work/$1.json"
}

make build-release
bench plain

RUSTFLAGS="-Cprofile-generate=$work/profiles" make build-release
python scripts/pgo_workload.py
host=$(rustc -vV | sed -n 's/^host: //p')
"$(rustc --print sysroot)/lib/rustlib/$host/bin/llvm-profdata" \
    merge -o "$work/merged.profdata" "$work/profiles"

RUSTFLAGS="-Cprofile-use=$work/merged.profdata" make build-release
bench pgo

python -m pyperf compare_to "$work/plain.json" "$work/pgo.json" --table
