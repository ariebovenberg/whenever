#!/bin/sh
# Test what was built in dist/ the way a user gets it: installed into a fresh
# environment, with the full suite run against site-packages.
#
#   test_wheel.sh PYTHON wheel|sdist True|False REQUIREMENTS
#
# The third argument is the expected value of `_EXTENSION_LOADED`.
set -eu
python=$1
kind=$2
extension_loaded=$3
requirements=$4

venv=$(mktemp -d)
"$python" -m venv "$venv"
if [ -x "$venv/bin/python" ]; then
    py="$venv/bin/python"
else
    py="$venv/Scripts/python.exe"
fi

if [ "$kind" = wheel ]; then
    # Nothing but dist/ can provide it, and no sdist can stand in for a wheel
    "$py" -m pip install --no-index --no-deps --only-binary :all: --find-links dist whenever
else
    "$py" -m pip install --no-deps dist/*.tar.gz
fi
# The runtime dependencies of the platforms that have them, and the test group
"$py" -m pip install tzdata tzlocal -r "$requirements"

"$py" -c "
import whenever
assert 'site-packages' in whenever.__file__, whenever.__file__
assert whenever._EXTENSION_LOADED is $extension_loaded, whenever._EXTENSION_LOADED
"
"$py" -m pytest tests/ -q
