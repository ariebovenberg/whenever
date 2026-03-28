"""
Stdlib (+dateutil) benchmarks — run with:

    uv run python run_stdlib.py --fast                    # all benchmarks
    uv run python run_stdlib.py --only now --fast         # single benchmark
    uv run python run_stdlib.py --only now,parse_iso      # multiple

Note: calendar_shift uses dateutil.relativedelta since the stdlib has no
built-in calendar arithmetic.
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
    "datetime.now(UTC)",
    setup="from datetime import datetime, UTC",
)

_bench(
    "parse_iso",
    "datetime.fromisoformat('2020-04-05T22:04:00-04:00')",
    setup="from datetime import datetime",
)

_bench(
    "instantiate_zdt",
    "datetime(2020, 3, 20, 12, 30, 45, tzinfo=ZoneInfo('Europe/Amsterdam'))",
    setup=(
        "from datetime import datetime;"
        " from zoneinfo import ZoneInfo;"
    ),
)

_bench(
    "shift",
    "dt + timedelta(hours=4, minutes=30)",
    setup=(
        "from datetime import datetime, timedelta;"
        " from zoneinfo import ZoneInfo;"
        " dt = datetime(2020, 3, 20, 12, 30, 45, tzinfo=ZoneInfo('Europe/Amsterdam'))"
    ),
)

_bench(
    "to_tz",
    "dt.astimezone(ZoneInfo('America/New_York'))",
    setup=(
        "from datetime import datetime;"
        " from zoneinfo import ZoneInfo;"
        " dt = datetime(2020, 3, 20, 12, 30, 45, tzinfo=ZoneInfo('Europe/Amsterdam'))"
    ),
)

_bench(
    "normalize_utc",
    "dt.astimezone(UTC)",
    setup=(
        "from datetime import datetime, UTC;"
        " from zoneinfo import ZoneInfo;"
        " dt = datetime(2020, 3, 20, 12, 30, 45, tzinfo=ZoneInfo('Europe/Amsterdam'))"
    ),
)

_bench(
    "format_iso",
    "dt.isoformat()",
    setup=(
        "from datetime import datetime;"
        " from zoneinfo import ZoneInfo;"
        " dt = datetime(2020, 3, 20, 12, 30, 45, tzinfo=ZoneInfo('Europe/Amsterdam'))"
    ),
)

_bench(
    "difference",
    "dt2 - dt1",
    setup=(
        "from datetime import datetime, UTC;"
        " dt1 = datetime(2020, 3, 20, 12, 0, 0, tzinfo=UTC);"
        " dt2 = datetime(2020, 3, 21, 8, 30, 0, tzinfo=UTC)"
    ),
)

_bench(
    "calendar_shift",
    "dt + delta",
    setup=(
        "from datetime import datetime;"
        " from zoneinfo import ZoneInfo;"
        " from dateutil.relativedelta import relativedelta;"
        " dt = datetime(2020, 3, 20, 12, 30, 45, tzinfo=ZoneInfo('Europe/Amsterdam'));"
        " delta = relativedelta(years=1, months=3)"
    ),
)

# Compound benchmark — mirrors the original "various operations" comparison.
# Uncomment to include in the run.
# _bench(
#     "compound",
#     "d = datetime.fromisoformat('2020-04-05T22:04:00-04:00')"
#     ".astimezone(UTC);"
#     "d - datetime.now(UTC);"
#     "(d + timedelta(hours=4, minutes=30))"
#     ".astimezone(ZoneInfo('Europe/Amsterdam'))"
#     ".isoformat()",
#     setup="from datetime import datetime, timedelta, UTC; from zoneinfo import ZoneInfo",
# )
