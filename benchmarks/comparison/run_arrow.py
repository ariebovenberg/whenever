"""
Arrow benchmarks — run with:

    uv run python run_arrow.py --fast                    # all benchmarks
    uv run python run_arrow.py --only now --fast         # single benchmark
    uv run python run_arrow.py --only now,parse_iso      # multiple
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
    "arrow.utcnow()",
    setup="import arrow",
)

_bench(
    "parse_iso",
    "arrow.get('2020-04-05T22:04:00-04:00')",
    setup="import arrow",
)

_bench(
    "instantiate_zdt",
    "arrow.Arrow(2020, 3, 20, 12, 30, 45, tzinfo='Europe/Amsterdam')",
    setup="import arrow",
)

_bench(
    "shift",
    "dt.shift(hours=4, minutes=30)",
    setup=(
        "import arrow;"
        " dt = arrow.Arrow(2020, 3, 20, 12, 30, 45, tzinfo='Europe/Amsterdam')"
    ),
)

_bench(
    "to_tz",
    "dt.to('America/New_York')",
    setup=(
        "import arrow;"
        " dt = arrow.Arrow(2020, 3, 20, 12, 30, 45, tzinfo='Europe/Amsterdam')"
    ),
)

_bench(
    "normalize_utc",
    "dt.to('utc')",
    setup=(
        "import arrow;"
        " dt = arrow.Arrow(2020, 3, 20, 12, 30, 45, tzinfo='Europe/Amsterdam')"
    ),
)

_bench(
    "format_iso",
    "dt.isoformat()",
    setup=(
        "import arrow;"
        " dt = arrow.Arrow(2020, 3, 20, 12, 30, 45, tzinfo='Europe/Amsterdam')"
    ),
)

_bench(
    "difference",
    "a2 - a1",
    setup=(
        "import arrow;"
        " a1 = arrow.Arrow(2020, 3, 20, 12, 0, 0, tzinfo='UTC');"
        " a2 = arrow.Arrow(2020, 3, 21, 8, 30, 0, tzinfo='UTC')"
    ),
)

_bench(
    "calendar_shift",
    "dt.shift(years=1, months=3)",
    setup=(
        "import arrow;"
        " dt = arrow.Arrow(2020, 3, 20, 12, 30, 45, tzinfo='Europe/Amsterdam')"
    ),
)

# Compound benchmark — mirrors the original "various operations" comparison.
# Uncomment to include in the run.
# _bench(
#     "compound",
#     "d = arrow.get('2020-04-05T22:04:00-04:00')"
#     ".to('utc');"
#     "d - arrow.utcnow();"
#     "d.shift(hours=4, minutes=30)"
#     ".to('Europe/Amsterdam')"
#     ".isoformat()",
#     setup="import arrow",
# )
