"""
Pendulum benchmarks — run with:

    uv run python run_pendulum.py --fast                    # all benchmarks
    uv run python run_pendulum.py --only now --fast         # single benchmark
    uv run python run_pendulum.py --only now,parse_iso      # multiple
"""
import argparse
import sys

_pre = argparse.ArgumentParser(add_help=False)
_pre.add_argument("--only", default=None, metavar="NAME",
                  help="comma-separated list of benchmark names to run")
_ns, _remaining = _pre.parse_known_args(sys.argv[1:])
_only = set(_ns.only.split(",")) if _ns.only else None
sys.argv = [sys.argv[0]] + _remaining

import pyperf  # noqa: E402


def _add_only(cmd, args):
    if _ns.only:
        cmd += ["--only", _ns.only]


runner = pyperf.Runner(add_cmdline_args=_add_only if _ns.only else None)


def _bench(name: str, stmt: str, setup: str = "") -> None:
    if _only is None or name in _only:
        runner.timeit(name, stmt, setup=setup)


_bench(
    "now",
    "now('UTC')",
    setup="from pendulum import now",
)

_bench(
    "parse_iso",
    "parse('2020-04-05T22:04:00-04:00')",
    setup="from pendulum import parse",
)

_bench(
    "instantiate_zdt",
    "datetime(2020, 3, 20, 12, 30, 45, tz='Europe/Amsterdam')",
    setup="from pendulum import datetime",
)

_bench(
    "shift",
    "dt.add(hours=4, minutes=30)",
    setup=(
        "import pendulum;"
        " dt = pendulum.datetime(2020, 3, 20, 12, 30, 45, tz='Europe/Amsterdam')"
    ),
)

_bench(
    "to_tz",
    "dt.in_tz('America/New_York')",
    setup=(
        "import pendulum;"
        " dt = pendulum.datetime(2020, 3, 20, 12, 30, 45, tz='Europe/Amsterdam')"
    ),
)

_bench(
    "normalize_utc",
    "dt.in_tz('UTC')",
    setup=(
        "import pendulum;"
        " dt = pendulum.datetime(2020, 3, 20, 12, 30, 45, tz='Europe/Amsterdam')"
    ),
)

_bench(
    "format_iso",
    "dt.isoformat()",
    setup=(
        "import pendulum;"
        " dt = pendulum.datetime(2020, 3, 20, 12, 30, 45, tz='Europe/Amsterdam')"
    ),
)

_bench(
    "difference",
    "p2 - p1",
    setup=(
        "import pendulum;"
        " p1 = pendulum.datetime(2020, 3, 20, 12, 0, 0, tz='UTC');"
        " p2 = pendulum.datetime(2020, 3, 21, 8, 30, 0, tz='UTC')"
    ),
)

_bench(
    "calendar_shift",
    "dt.add(years=1, months=3)",
    setup=(
        "import pendulum;"
        " dt = pendulum.datetime(2020, 3, 20, 12, 30, 45, tz='Europe/Amsterdam')"
    ),
)

# Compound benchmark — mirrors the original "various operations" comparison.
# Uncomment to include in the run.
# _bench(
#     "compound",
#     "d = pendulum.parse('2020-04-05T22:04:00-04:00')"
#     ".in_tz('UTC');"
#     "d.diff();"
#     "d.add(hours=4, minutes=30)"
#     ".in_tz('Europe/Amsterdam')"
#     ".isoformat()",
#     setup="import pendulum",
# )
