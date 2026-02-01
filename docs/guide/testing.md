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
Do note that this function only affects *whenever*, and not the standard library's
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
