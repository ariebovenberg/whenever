"""
Whenever benchmarks — run with:

    uv run python run_whenever.py --fast                    # all benchmarks
    uv run python run_whenever.py --only now --fast         # single benchmark
    uv run python run_whenever.py --only now,parse_iso      # multiple

Uses whenever 0.9.5 (optimized Rust wheel from PyPI).
"""

import argparse
import sys

_pre = argparse.ArgumentParser(add_help=False)
_pre.add_argument(
    "--only",
    default=None,
    metavar="NAME",
    help="comma-separated list of benchmark names to run",
)
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
    "Instant.now()",
    setup="from whenever import Instant",
)

_bench(
    "parse_iso",
    "OffsetDateTime('2020-04-05T22:04:00-04:00')",
    setup="from whenever import OffsetDateTime",
)

_bench(
    "instantiate_zdt",
    "ZonedDateTime(2020, 3, 20, 12, 30, 45, tz='Europe/Amsterdam')",
    setup="from whenever import ZonedDateTime",
)

_bench(
    "shift",
    "dt.add(hours=4, minutes=30)",
    setup=(
        "from whenever import ZonedDateTime;"
        " dt = ZonedDateTime(2020, 3, 20, 12, 30, 45, tz='Europe/Amsterdam')"
    ),
)

_bench(
    "to_tz",
    "dt.to_tz('America/New_York')",
    setup=(
        "from whenever import ZonedDateTime;"
        " dt = ZonedDateTime(2020, 3, 20, 12, 30, 45, tz='Europe/Amsterdam')"
    ),
)

_bench(
    "normalize_utc",
    "dt.to_instant()",
    setup=(
        "from whenever import ZonedDateTime;"
        " dt = ZonedDateTime(2020, 3, 20, 12, 30, 45, tz='Europe/Amsterdam')"
    ),
)

_bench(
    "format_iso",
    "dt.format_iso()",
    setup=(
        "from whenever import ZonedDateTime;"
        " dt = ZonedDateTime(2020, 3, 20, 12, 30, 45, tz='Europe/Amsterdam')"
    ),
)

_bench(
    "difference",
    "i2 - i1",
    setup=(
        "from whenever import Instant;"
        " i1 = Instant.from_utc(2020, 3, 20, 12, 0, 0);"
        " i2 = Instant.from_utc(2020, 3, 21, 8, 30, 0)"
    ),
)

_bench(
    "calendar_shift",
    "dt.add(years=1, months=3)",
    setup=(
        "from whenever import ZonedDateTime;"
        " dt = ZonedDateTime(2020, 3, 20, 12, 30, 45, tz='Europe/Amsterdam')"
    ),
)

# Compound benchmark — mirrors the original "various operations" comparison.
# Uncomment to include in the run.
# _bench(
#     "compound",
#     "d = OffsetDateTime.parse_iso('2020-04-05T22:04:00-04:00')"
#     ".to_instant();"
#     "d - Instant.now();"
#     "d.add(hours=4, minutes=30)"
#     ".to_tz('Europe/Amsterdam')"
#     ".format_iso()",
#     setup="from whenever import OffsetDateTime, Instant",
# )
