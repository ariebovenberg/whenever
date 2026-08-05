---
myst:
  html_meta:
    description: >-
      Testing code that uses whenever: patch_current_time, the time-machine
      package, dependency injection instead of patching, and setting the system
      timezone via TZ.
---

# Testing

## Patching the current time

Sometimes you need to 'fake' the output of `.now()` functions, typically for testing.
`whenever` supports various ways to do this, depending on your needs:

1. With {class}`whenever.patch_current_time`. This patcher
   only affects `whenever`, not the standard library or other libraries.
   See its documentation for more details.
2. With the [`time-machine`](https://github.com/adamchainz/time-machine) package.
   Using `time-machine` *does* affect the standard library and other libraries,
   which can lead to unintended side effects.
   Note that `time-machine` doesn't support PyPy.

```{note}

It's also possible to use the
[freezegun](https://github.com/spulec/freezegun) library,
but it will *only work on the Pure-Python version* of `whenever`.
```

The context manager yields a {class}`~whenever.TimePatch` handle. Use
{meth}`~whenever.TimePatch.shift` for exact elapsed-time movement and
{meth}`~whenever.TimePatch.move_to` to set a new exact time:

```python
>>> with patch_current_time(Instant("2024-01-01T00:00:00Z"), keep_ticking=False) as p:
...     p.shift(hours=2)
...     assert Instant.now() == Instant("2024-01-01T02:00:00Z")
...     p.move_to(Instant("2024-06-01T12:00:00Z"))
...     assert Instant.now() == Instant("2024-06-01T12:00:00Z")
```

`shift()` accepts exact units only. To perform calendar arithmetic, calculate
the target explicitly and pass it to `move_to()`. With `keep_ticking=True`,
shifts apply to the patched current instant at the moment of the call and the
clock then continues ticking from the result.

The patch affects only Whenever's current-time functions. Its state is global
to the interpreter/module and therefore visible to every thread. Overlapping
or nested patches raise {exc}`RuntimeError`, as does using a handle after its
context exits. Decorator use does not inject the handle into the decorated
function; use a `with` statement when you need it. In free-threaded builds,
Whenever synchronizes access to this global state.

:::{tip}

Instead of relying on patching, consider using dependency injection
instead. This is less error-prone and more explicit.

You can do this by adding `now` argument to your function,
like this:

```python
def greet(name, now=Instant.now):
    current_time = now()
    # more code here...

# in normal use, you don't notice the difference:
greet('bob')

# to test it, pass a custom function:
greet('alice', now=lambda: Instant.from_utc(2023, 1, 1))
```
:::


## Patching the system timezone

For changing the system timezone in tests, set the `TZ` environment variable
and use the {func}`~whenever.reset_system_tz` helper function to update the timezone cache.
Do note that this function only affects `whenever`, and not the standard library's
behavior.

Below is an example of a testing helper that can be used with `pytest`:

```python
import os
import pytest
from contextlib import contextmanager
from unittest.mock import patch
from whenever import reset_system_tz

@contextmanager
def system_tz_ams():
    try:
        with patch.dict(os.environ, {"TZ": "Europe/Amsterdam"}):
            reset_system_tz()  # update the timezone cache
            yield
    finally:
        reset_system_tz()  # don't forget to set the old timezone back!
```
