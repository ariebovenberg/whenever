"""Run the ``>>>`` examples in every public docstring and report failures.

Not wired into the test suite: most examples are written as illustrations
rather than literal transcripts (an assignment shown with its repr, output
omitted, errors written without a ``Traceback`` header), so a large number
"fail" without being wrong. Only the ones that raise, or that print something
other than what's documented, indicate a real problem.

Two things to know when reading the output:

* whenever rewrites ``__module__`` to ``"whenever"`` so classes read as
  ``whenever.Date``. Doctest therefore reports line numbers into
  ``__init__.py``, which contains none of these docstrings -- search for the
  example text in ``_pywhenever.py`` or ``_ideltas.py`` instead.
* Examples run against whichever implementation is installed, so this covers
  the Rust docstrings too when the extension is built.

Usage: python scripts/check_docstring_examples.py [--verbose]
"""

import doctest
import os
import sys
import warnings
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

import whenever

OPTIONFLAGS = doctest.ELLIPSIS | doctest.NORMALIZE_WHITESPACE


def _globals() -> dict[str, object]:
    ns: dict[str, object] = {n: getattr(whenever, n) for n in whenever.__all__}
    # stdlib names used by interop examples. NOTE: `date` and `time` are
    # deliberately absent -- examples bind those as locals.
    ns.update(datetime=datetime, timedelta=timedelta, os=os, ZoneInfo=ZoneInfo)
    return ns


def collect() -> list[doctest.DocTest]:
    finder = doctest.DocTestFinder(exclude_empty=True)
    # Collect re-exported objects too, then de-duplicate by name.
    finder._from_module = lambda module, object: True  # type: ignore[method-assign]
    with warnings.catch_warnings():
        warnings.simplefilter("ignore", whenever.WheneverWarning)
        found = finder.find(whenever, "whenever", globs=_globals())
    return sorted(
        {t.name: t for t in found if t.examples}.values(), key=lambda t: t.name
    )


def main() -> int:
    verbose = "--verbose" in sys.argv
    tests = collect()
    failed = examples = 0
    for test in tests:
        out: list[str] = []
        # Examples illustrate what an API *does*; the warnings it emits are
        # described in the prose around them.
        with warnings.catch_warnings():
            warnings.simplefilter("ignore", whenever.WheneverWarning)
            runner = doctest.DocTestRunner(optionflags=OPTIONFLAGS)
            runner.run(test, out=out.append)
        examples += len(test.examples)
        if runner.failures:
            failed += runner.failures
            print(f"--- {test.name} ({runner.failures} failing)")
            if verbose:
                print("".join(out))
    print(
        f"\n{len(tests)} docstrings, {examples} examples, "
        f"{failed} failing. Run with --verbose for the diffs."
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
