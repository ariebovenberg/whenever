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
{class}`~whenever.TimeZoneUnawareArithmeticWarning`,
{class}`~whenever.PotentiallyStaleOffsetWarning`, and
{class}`~whenever.DaysNotAlways24HoursWarning`.
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
warnings.filterwarnings("error", category=whenever.TimeZoneUnawareArithmeticWarning)

# Only error on potentially stale offset operations (OffsetDateTime):
warnings.filterwarnings("error", category=whenever.PotentiallyStaleOffsetWarning)
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
the decision is conscious and documented. Use the context managers provided by
`whenever` to suppress the warning for specific operations:

```python
from whenever import PlainDateTime, ignore_timezone_unaware_arithmetic_warning

# Naive arithmetic is acceptable here: these buses don't run across
# DST boundaries (all departures are between 06:00 and 22:00).
with ignore_timezone_unaware_arithmetic_warning():
    next_departure = scheduled.add(hours=1)
```


The context manager documents the decision at the call site and keeps the
suppression local — code outside the `with` block still sees the warning
normally.

The three context managers, one per warning type:

| Context manager | Suppresses |
|---|---|
| {func}`~whenever.ignore_timezone_unaware_arithmetic_warning` | {class}`~whenever.TimeZoneUnawareArithmeticWarning` |
| {func}`~whenever.ignore_potentially_stale_offset_warning` | {class}`~whenever.PotentiallyStaleOffsetWarning` |
| {func}`~whenever.ignore_days_not_always_24h_warning` | {class}`~whenever.DaysNotAlways24HoursWarning` |

:::{tip}

Thes context managers can also be used as a decorator if you want to suppress
warnings for an entire function:

```python
@ignore_timezone_unaware_arithmetic_warning()
def next_departure(scheduled: PlainDateTime) -> PlainDateTime:
    ...
```

:::

There is no combined context manager for {class}`~whenever.PotentialDstBugWarning`
as a whole; if you need to suppress all DST warnings in a block,
use a {class}`warnings.catch_warnings` block:

```python
import warnings
import whenever

with warnings.catch_warnings():
    warnings.simplefilter("ignore", whenever.PotentialDstBugWarning)
    # ... all DST warnings suppressed here
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
underlying issue or document it with a context manager.

## Choosing the right approach

| Situation | Recommended approach |
|---|---|
| Production code | `filterwarnings("error", ...)` at startup |
| CI / test suite | `filterwarnings = error::whenever.PotentialDstBugWarning` in `pytest.ini` |
| One intentional imprecision | `with ignore_..._warning():` + a comment |
| Entire module intentionally imprecise | `filterwarnings("ignore", ..., module=r"mymodule\.*")` |
| Exploratory scripts | `filterwarnings("ignore", ...)` globally |
