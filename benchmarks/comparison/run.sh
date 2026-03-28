#!/usr/bin/env bash
# Proper benchmark run for whenever vs stdlib, arrow, and pendulum.
#
# Usage:
#   ./run.sh              # full benchmark run (slow—use for final results)
#   ./run.sh --fast       # fast mode (fewer samples, good for quick checks)
#
# Prerequisites:
#   - uv installed with Python 3.14 available (optimized/PGO build recommended)
#   - time_machine must NOT be installed (whenever detects it and slows down)
#
# Results are written to results/ and a comparison table is printed at the end,
# followed by a memory report and updated SVG charts in charts/.
#
# To update the documentation charts, pass --update-docs:
#   ./run.sh --update-docs
#   ./run.sh --fast --update-docs

set -euo pipefail
cd "$(dirname "$0")"

FAST_FLAG=""
UPDATE_DOCS=0
for arg in "$@"; do
    case "$arg" in
        --fast)        FAST_FLAG="--fast" ;;
        --update-docs) UPDATE_DOCS=1 ;;
    esac
done

OUT="results"
mkdir -p "$OUT"

echo "==> Syncing dependencies (whenever==0.9.5 from PyPI)..."
uv sync --quiet

echo ""
echo "==> Environment"
echo "    Python:   $(uv run python --version)"
echo "    whenever: $(uv run python -c 'import whenever; print(whenever.__version__)')"
echo "    arrow:    $(uv run python -c 'import arrow; print(arrow.__version__)')"
echo "    pendulum: $(uv run python -c 'import pendulum; print(pendulum.__version__)')"

# Check that pyperf workers use the same optimized Python that uv resolved.
# pyperf spawns workers via sys.executable, which is the .venv Python —
# the same interpreter used by 'uv run'. Verify it was built with PGO:
echo ""
echo "==> Python build flags"
uv run python -c "
import sysconfig, sys
exe = sys.executable
pgo_flag = sysconfig.get_config_var('PGO_PROF_USE_FLAG') or ''
config_args = sysconfig.get_config_var('CONFIG_ARGS') or ''
lto = '-flto' in (sysconfig.get_config_var('LDFLAGS') or '') \
   or '-flto' in (sysconfig.get_config_var('CFLAGS') or '')
pgo = bool(pgo_flag) or '--enable-optimizations' in config_args
status = []
if pgo: status.append('PGO')
if lto: status.append('LTO')
flag_str = '+'.join(status) if status else 'unknown (may not be optimized)'
print(f'    Executable: {exe}')
print(f'    Optimizations: {flag_str}')
if not pgo:
    print('    WARNING: Could not confirm PGO build.')
    print('    For best results use: uv python install cpython-3.14')
    print('    (python-build-standalone ships PGO+LTO builds)')
"
echo ""

run_bench() {
    local script="$1"
    local out_file="$2"
    echo "==> Running $script..."
    uv run python "$script" $FAST_FLAG -o "$out_file"
}

run_bench run_stdlib.py        "$OUT/result_stdlib.json"
run_bench run_arrow.py         "$OUT/result_arrow.json"
run_bench run_pendulum.py      "$OUT/result_pendulum.json"
run_bench run_whenever.py      "$OUT/result_whenever.json"
run_bench run_whenever_pure.py "$OUT/result_whenever_pure.json"

echo ""
echo "==> Memory per instance:"
uv run python memory.py -o "$OUT/memory.json"

echo ""
echo "==> Timing comparison (lower is better):"
uv run python -m pyperf compare_to \
    "$OUT/result_stdlib.json" \
    "$OUT/result_arrow.json" \
    "$OUT/result_pendulum.json" \
    "$OUT/result_whenever.json" \
    "$OUT/result_whenever_pure.json" \
    --table

echo ""
echo "==> Generating charts..."
if [ "$UPDATE_DOCS" -eq 1 ]; then
    CHART_OUT="../../docs/_static/benchmarks"
    echo "    Writing to $CHART_OUT (docs update)"
else
    CHART_OUT="charts"
fi
uv run python charts.py --results-dir "$OUT" --memory-file "$OUT/memory.json" --output "$CHART_OUT"
