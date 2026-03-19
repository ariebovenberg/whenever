#!/bin/bash
set -euo pipefail

# Test PGO locally: build baseline and PGO wheels, benchmark both.
#
# Prerequisites:
#   - Rust 1.93+ with llvm-tools component
#   - Python 3.10+ with maturin and build tools
#   - Working C compiler (gcc/clang on Unix, MSVC on Windows)
#
# Usage:
#   bash scripts/test_pgo_locally.sh [--cleanup]
#
# Options:
#   --cleanup   Remove build artifacts at the end

set -e
cleanup_at_end=0

for arg in "$@"; do
    if [ "$arg" = "--cleanup" ]; then
        cleanup_at_end=1
    fi
done

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
BLUE='\033[0;34m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

log_section() {
    echo -e "\n${BLUE}=== $1 ===${NC}\n"
}

log_success() {
    echo -e "${GREEN}✓ $1${NC}"
}

log_warning() {
    echo -e "${YELLOW}⚠ $1${NC}"
}

log_error() {
    echo -e "${RED}✗ $1${NC}"
}

# Check prerequisites
log_section "Checking prerequisites"
if ! command -v uv &>/dev/null; then
    log_error "uv not found"
    echo "Install with: pip install uv"
    exit 1
fi
log_success "uv is installed"

if ! command -v rustc &>/dev/null; then
    log_error "Rust not found"
    exit 1
fi
RUST_VERSION=$(rustc --version | cut -d' ' -f2)
log_success "Rust $RUST_VERSION"

if ! command -v python3 &>/dev/null; then
    log_error "Python 3 not found"
    exit 1
fi
PYTHON_VERSION=$(python3 --version | cut -d' ' -f2)
log_success "Python $PYTHON_VERSION (system, used for setup only)"

# Check for llvm-tools
if ! rustup component list | grep -q "llvm-tools.*installed"; then
    log_warning "llvm-tools not installed for current toolchain"
    log_section "Installing llvm-tools"
    rustup component add llvm-tools
fi
log_success "llvm-tools available"

# Setup directories
WORK_DIR="pgo-test-work"
BASELINE_DIR="$WORK_DIR/baseline"
PGO_BUILD_DIR="$WORK_DIR/pgo-build"
PGO_PROFILE_DIR="$WORK_DIR/profdata"

mkdir -p "$BASELINE_DIR" "$PGO_BUILD_DIR" "$PGO_PROFILE_DIR"

log_section "Step 1: Build baseline wheel (release mode, no PGO)"

rm -rf build dist target pysrc/whenever/*.so pysrc/whenever/*.dylib pysrc/whenever/*.pyd
python3 setup.py build_rust --inplace --release -q

# The build process creates _whenever.*.so; find it and save a copy
SO_FILE=$(ls pysrc/whenever/_whenever*.so 2>/dev/null | head -1)
if [ -n "$SO_FILE" ]; then
    # Save with a consistent name
    cp "$SO_FILE" "$BASELINE_DIR/_whenever_baseline.so"
    log_success "Baseline extension (release): $(basename "$SO_FILE")"
else
    log_error "No compiled extension found for baseline"
    exit 1
fi

log_section "Step 2: Build instrumented wheel (PGO profile-generate, release mode)"
rm -rf build dist target pysrc/whenever/*.so pysrc/whenever/*.dylib pysrc/whenever/*.pyd
export RUSTFLAGS="-Cprofile-generate=$(pwd)/$PGO_PROFILE_DIR -Cllvm-args=-pgo-warn-missing-function"
python3 setup.py build_rust --inplace --release -q
unset RUSTFLAGS
log_success "Instrumented wheel built (release mode)"

log_section "Step 3: Run profiling workload"
log_warning "Running 200 iterations of pgo_profile.py (using uv Python)..."
uv run -q --no-cache python scripts/pgo_profile.py --iterations 200 2>&1 | tail -5
log_success "Profiling complete"

# Find llvm-profdata — need to strip the patch version (1.93.1 -> 1.93)
RUST_HOST=$(rustc --version --verbose | grep '^host:' | cut -d' ' -f2)
RUST_VERSION=$(rustc --version --verbose | grep '^release:' | cut -d' ' -f2)
RUST_VERSION_MAJOR_MINOR=$(echo "$RUST_VERSION" | cut -d'.' -f1,2)  # 1.93.1 -> 1.93
RUSTUP_HOME="${RUSTUP_HOME:-$HOME/.rustup}"
LLVM_PROFDATA="$RUSTUP_HOME/toolchains/$RUST_VERSION_MAJOR_MINOR-$RUST_HOST/lib/rustlib/$RUST_HOST/bin/llvm-profdata"

if [ ! -x "$LLVM_PROFDATA" ]; then
    log_error "Could not find llvm-profdata"
    exit 1
fi
log_success "Found llvm-profdata"

log_section "Step 4: Merge profiling data"
"$LLVM_PROFDATA" merge "$PGO_PROFILE_DIR"/*.profraw -o "$PGO_PROFILE_DIR/merged.profdata" 2>/dev/null || \
    "$LLVM_PROFDATA" merge -o "$PGO_PROFILE_DIR/merged.profdata" "$PGO_PROFILE_DIR"/*.profraw
log_success "Merged: $PGO_PROFILE_DIR/merged.profdata"

log_section "Step 5: Build PGO-optimized wheel (profile-use, release mode)"
rm -rf build dist target pysrc/whenever/*.so pysrc/whenever/*.dylib pysrc/whenever/*.pyd
export RUSTFLAGS="-Cprofile-use=$(pwd)/$PGO_PROFILE_DIR/merged.profdata"
python3 setup.py build_rust --inplace --release -q
unset RUSTFLAGS

# Save the PGO-optimized extension
SO_FILE_PGO=$(ls pysrc/whenever/_whenever*.so 2>/dev/null | head -1)
if [ -n "$SO_FILE_PGO" ]; then
    cp "$SO_FILE_PGO" "$PGO_BUILD_DIR/_whenever_pgo.so"
    log_success "PGO extension (release): $(basename "$SO_FILE_PGO")"
else
    log_error "No compiled extension found for PGO"
    exit 1
fi

log_section "Step 6: Benchmark baseline vs. PGO (pyperf)"

# Create extension wrapper directories for both baseline and PGO
# We copy the entire pysrc/whenever package and replace the .so
mkdir -p "$WORK_DIR/baseline_ext" "$WORK_DIR/pgo_ext"
cp -r pysrc/whenever "$WORK_DIR/baseline_ext/whenever"
cp -r pysrc/whenever "$WORK_DIR/pgo_ext/whenever"

# Get the current Python's extension name
EXT_NAME=$(ls pysrc/whenever/_whenever*.so 2>/dev/null | xargs basename)
if [ -z "$EXT_NAME" ]; then
    EXT_NAME="_whenever.cpython-313-darwin.so"
fi

# Copy the saved .so files over the ones we just copied
cp "$BASELINE_DIR/_whenever_baseline.so" "$WORK_DIR/baseline_ext/whenever/$EXT_NAME"
cp "$PGO_BUILD_DIR/_whenever_pgo.so" "$WORK_DIR/pgo_ext/whenever/$EXT_NAME"

# We'll create separate benchmark scripts for each version,
# with the extension path hardcoded in each script
BASELINE_BENCH="$WORK_DIR/bench_baseline.py"
PGO_BENCH="$WORK_DIR/bench_pgo.py"

# Create baseline benchmark script with hardcoded path
cat > "$BASELINE_BENCH" << "BENCH_BASELINE_EOF"
import pyperf
import sys
import os
import time

# Add the baseline extension directory to the path
sys.path.insert(0, 'BASELINE_EXT_DIR_PLACEHOLDER')

import whenever

# Warm-up
for _ in range(100):
    whenever.Date(2024, 3, 15)
    whenever.Instant.from_utc(2024, 1, 1)

def bench_whenever_ops(loops):
    range_it = range(loops)
    t0 = time.perf_counter()
    
    for _ in range_it:
        d = whenever.Date(2024, 3, 15)
        d2 = d.add(days=10)
        _ = d.since(d2, total='days')
        _ = d.format('YYYY-MM-DD')
        
        td = whenever.TimeDelta(hours=2, minutes=30)
        _ = td.total('hours')
        _ = td.total('seconds')
        _ = td + whenever.TimeDelta(hours=1)
        
        i = whenever.Instant.from_utc(2024, 1, 1)
        i2 = i + whenever.TimeDelta(hours=5)
        _ = i.to_tz('Europe/Amsterdam')
        
        z = whenever.ZonedDateTime(2024, 3, 15, 10, 0, tz='UTC')
        z2 = z.add(days=1)
        _ = z.since(z2, total='hours')
    
    return time.perf_counter() - t0

runner = pyperf.Runner()
runner.bench_time_func("whenever ops", bench_whenever_ops, inner_loops=5)
BENCH_BASELINE_EOF

# Replace the placeholder with actual path
sed -i '' "s|BASELINE_EXT_DIR_PLACEHOLDER|$(cd "$WORK_DIR/baseline_ext" && pwd)|g" "$BASELINE_BENCH"

# Create PGO benchmark script
cat > "$PGO_BENCH" << "BENCH_PGO_EOF"
import pyperf
import sys
import os
import time

# Add the PGO extension directory to the path
sys.path.insert(0, 'PGO_EXT_DIR_PLACEHOLDER')

import whenever

# Warm-up
for _ in range(100):
    whenever.Date(2024, 3, 15)
    whenever.Instant.from_utc(2024, 1, 1)

def bench_whenever_ops(loops):
    range_it = range(loops)
    t0 = time.perf_counter()
    
    for _ in range_it:
        d = whenever.Date(2024, 3, 15)
        d2 = d.add(days=10)
        _ = d.since(d2, total='days')
        _ = d.format('YYYY-MM-DD')
        
        td = whenever.TimeDelta(hours=2, minutes=30)
        _ = td.total('hours')
        _ = td.total('seconds')
        _ = td + whenever.TimeDelta(hours=1)
        
        i = whenever.Instant.from_utc(2024, 1, 1)
        i2 = i + whenever.TimeDelta(hours=5)
        _ = i.to_tz('Europe/Amsterdam')
        
        z = whenever.ZonedDateTime(2024, 3, 15, 10, 0, tz='UTC')
        z2 = z.add(days=1)
        _ = z.since(z2, total='hours')
    
    return time.perf_counter() - t0

runner = pyperf.Runner()
runner.bench_time_func("whenever ops", bench_whenever_ops, inner_loops=5)
BENCH_PGO_EOF

# Replace the placeholder with actual path
sed -i '' "s|PGO_EXT_DIR_PLACEHOLDER|$(cd "$WORK_DIR/pgo_ext" && pwd)|g" "$PGO_BENCH"

# Run benchmarks
log_warning "Running baseline benchmark..."
uv run -q --no-cache python "$BASELINE_BENCH" \
    -o "$WORK_DIR/baseline.json" 2>&1 | tail -5

log_warning "Running PGO benchmark..."
uv run -q --no-cache python "$PGO_BENCH" \
    -o "$WORK_DIR/pgo.json" 2>&1 | tail -5

# Compare results
if [ -f "$WORK_DIR/baseline.json" ] && [ -f "$WORK_DIR/pgo.json" ]; then
    echo ""
    uv run -q pyperf compare_to "$WORK_DIR/baseline.json" "$WORK_DIR/pgo.json" --table 2>&1
    log_success "Benchmark complete"
else
    log_warning "Benchmark JSON files not created"
fi

# Summary
log_section "Summary"
echo "Artifacts:"
echo "  Baseline wheel: $BASELINE_DIR"
echo "  PGO wheel:      $PGO_BUILD_DIR"
echo "  Profile data:   $PGO_PROFILE_DIR"
echo ""
echo "Next steps:"
echo "  1. Check the improvement percentage above."
echo "  2. If good, you're ready to commit the PGO CI changes."
echo "  3. The actual CI will use larger workloads and measure end-to-end."
echo ""

if [ $cleanup_at_end -eq 1 ]; then
    log_section "Cleanup"
    rm -rf "$WORK_DIR"
    log_success "Cleaned up $WORK_DIR"
else
    log_warning "Pass --cleanup to remove build artifacts"
fi
