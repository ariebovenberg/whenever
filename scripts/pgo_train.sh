#!/bin/sh
# Run the PGO training workload against the instrumented wheel in pgo-wheel/
# that matches PYTHON, installed into a fresh environment. The wheel writes
# its profiles to the directory it was built with.
#
#   pgo_train.sh PYTHON
set -eu
python=$1

venv=$(mktemp -d)
"$python" -m venv "$venv"
if [ -x "$venv/bin/python" ]; then
    py="$venv/bin/python"
else
    py="$venv/Scripts/python.exe"
fi

"$py" -m pip install --no-index --no-deps --only-binary :all: --find-links pgo-wheel whenever
# The runtime dependencies of the platforms that have them, and the time
# zone database Alpine lacks
"$py" -m pip install tzdata tzlocal
"$py" scripts/pgo_workload.py
