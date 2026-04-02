(warnings)=
# Handling warnings

`whenever` emits warnings when operations may produce incorrect results
due to DST transitions or missing timezone context. This is intentional: the
operations aren't *always* wrong, and raising exceptions would be too strict.
But ignoring the warnings entirely would be a disservice.

All `whenever` warnings are subclasses of {class}`~whenever.PotentialDstBugWarning`,
which is itself a subclass of Python's built-in
{class}`UserWarning <python:UserWarning>`. They fit into Python's standard
[`warnings` infrastructure](https://docs.python.org/3/library/warnings.html)
fully, giving you several levels of control.

```{note}
For a full list of warning types and the operations that trigger them, see the
{ref}`API reference <api>`:
{class}`~whenever.PotentialDstBugWarning`,
{class}`~whenever.NaiveArithmeticWarning`,
{class}`~whenever.StaleOffsetWarning`, and
{class}`~whenever.DaysAssumed24HoursWarning`.
```

## Turn warnings into errors

The most robust approach for production code is to **turn DST warnings into
exceptions** as early as possible — typically in your module's setup or at
the top of your application entry point:

```python
import warnings
import whenever

warnings.filterwarnings("error", category=whenever.PotentialDstBugWarning)
```

Any code that triggers a DST-related warning now raises an exception
immediately, forcing you (or your CI) to address it. This is the same principle
as `PYTHONWARNINGS=error` but scoped to `whenever`'s warning hierarchy only.

To target a specific warning type instead:

```python
# Only error on timezone-unaware arithmetic (PlainDateTime):
warnings.filterwarnings("error", category=whenever.NaiveArithmeticWarning)

# Only error on potentially stale offset operations (OffsetDateTime):
warnings.filterwarnings("error", category=whenever.StaleOffsetWarning)
```

### In pytest

When running tests, it's highly recommended to turn DST warnings into errors
so that tests catch potential DST bugs. Add this to your `pytest.ini` (or the
`[tool.pytest.ini_options]` table in `pyproject.toml`):

```ini
[pytest]
filterwarnings =
    error::whenever.PotentialDstBugWarning
```

Or to target only one module of your project (leaving third-party libraries
unaffected):

```ini
[pytest]
filterwarnings =
    error::whenever.PotentialDstBugWarning:mymodule.*
```

```{admonition} Command-line filter not supported
:class: warning

Unfortunately, passing `PYTHONWARNINGS=error::whenever.PotentialDstBugWarning`
on the command line does **not** work, due to a
[limitation in CPython](https://github.com/python/cpython/issues/66733):
the command-line filter only accepts built-in warning classes by name,
not third-party ones. Use `pytest.ini`, `pyproject.toml`, or a call to
`warnings.filterwarnings()` in your code instead.
```

### In a specific module

You can also apply a filter at the top of a module, so it applies to all
code in that module without touching other modules:

```python
# mymodule/scheduling.py
import warnings
import whenever

warnings.filterwarnings(
    "error",
    category=whenever.PotentialDstBugWarning,
    module=r"mymodule\.scheduling"  # or re.escape(__name__)
)
```

## Suppress specific calls

Sometimes an operation is deliberately imprecise — and that's fine, as long as
the decision is conscious and documented. Each method that may emit a
DST-related warning accepts a boolean keyword argument that suppresses it:

| Keyword argument | Suppresses | Used on |
|---|---|---|
| `days_assumed_24h_ok=True` | {class}`~whenever.DaysAssumed24HoursWarning` | {class}`~whenever.TimeDelta` methods |
| `stale_offset_ok=True` | {class}`~whenever.StaleOffsetWarning` | {class}`~whenever.OffsetDateTime` methods |
| `naive_arithmetic_ok=True` | {class}`~whenever.NaiveArithmeticWarning` | {class}`~whenever.PlainDateTime` methods |

For example:

```python
from whenever import PlainDateTime

# Naive arithmetic is acceptable here because <insert reason>
next_departure = scheduled.add(hours=1, naive_arithmetic_ok=True)
```

The keyword argument documents the decision at the call site
while keeping the suppression limited to exactly one operation.

```{note}
These keyword arguments supersede the ``ignore_dst`` keyword argument
(deprecated in 0.10).
```

### Operators

The `+` and `-` operators always emit warnings when applicable, because
operators cannot accept keyword arguments. Use the method equivalents instead:

- `dt + delta` → `dt.add(delta, ...)`
- `dt - delta` → `dt.subtract(delta, ...)`
- `dt_a - dt_b` → `dt_a.difference(dt_b)` (for {class}`~whenever.PlainDateTime`,
  pass `naive_arithmetic_ok=True`)

Alternatively, suppress operator warnings with Python's standard
{func}`warnings.filterwarnings`.

## Using Python's warnings infrastructure

Since `whenever` warnings are standard Python warnings, you can also
suppress them with {class}`warnings.catch_warnings`:

```python
import warnings
import whenever

with warnings.catch_warnings():
    warnings.simplefilter("ignore", whenever.StaleOffsetWarning)
    # ... all stale-offset warnings suppressed inside this block
```

This is useful when you want to blanket-suppress warnings for a block of code
or for operators (which can't take keyword arguments).

```{admonition} Limitation before Python 3.14
:class: warning

Before Python 3.14, {class}`warnings.catch_warnings` is **not context-safe**:
in concurrent code (threads or async tasks) the suppression filter may leak to
other contexts, or other contexts may interfere with yours. This is a
[known CPython limitation](https://docs.python.org/3/library/warnings.html#warning-filter)
addressed by the ``PYTHON_CONTEXT_AWARE_WARNINGS`` flag introduced in
Python 3.14.

The per-method keyword arguments described above don't have this limitation —
they suppress the warning for exactly one call, regardless of concurrency.
```

## Exploratory use and scripts

When hacking around or writing a quick script, you may simply want to silence
all `whenever` warnings globally and move on:

```python
import warnings
import whenever

warnings.filterwarnings("ignore", category=whenever.PotentialDstBugWarning)
```

This is fine for exploration. If you later promote the code to production,
revisit the suppressed warnings and decide for each one whether to fix the
underlying issue or suppress it explicitly with the appropriate keyword argument.

## Choosing the right approach

| Situation | Recommended approach |
|---|---|
| Production code | `filterwarnings("error", ...)` at startup |
| CI / test suite | `filterwarnings = error::whenever.PotentialDstBugWarning` in `pytest.ini` |
| One intentional imprecision | Per-method kwarg (e.g. `naive_arithmetic_ok=True`) + a comment |
| Suppress operator warnings | `warnings.catch_warnings()` block (Python ≥ 3.14 for concurrency safety) |
| Entire module intentionally imprecise | `filterwarnings("ignore", ..., module=r"mymodule\.*")` |
| Exploratory scripts | `filterwarnings("ignore", ...)` globally |
