try:  # pragma: no cover
    from ._whenever import *
    from ._whenever import (
        _patch_time_frozen,
        _patch_time_keep_ticking,
        _unpatch_time,
        _unpkl_date,
        _unpkl_ddelta,
        _unpkl_dtdelta,
        _unpkl_local,
        _unpkl_offset,
        _unpkl_system,
        _unpkl_tdelta,
        _unpkl_time,
        _unpkl_utc,
        _unpkl_zoned,
    )

    _EXTENSION_LOADED = True

except ModuleNotFoundError as e:
    if e.name != "whenever._whenever":  # pragma: no cover
        raise e
    from ._pywhenever import *
    from ._pywhenever import (  # for the docs
        __all__,
        __version__,
        _BasicConversions,
        _KnowsInstant,
        _KnowsInstantAndLocal,
        _KnowsLocal,
        _patch_time_frozen,
        _patch_time_keep_ticking,
        _unpatch_time,
        _unpkl_date,
        _unpkl_ddelta,
        _unpkl_dtdelta,
        _unpkl_local,
        _unpkl_offset,
        _unpkl_system,
        _unpkl_tdelta,
        _unpkl_time,
        _unpkl_utc,
        _unpkl_zoned,
    )

    _EXTENSION_LOADED = False


from contextlib import contextmanager as _contextmanager
from dataclasses import dataclass as _dataclass
from typing import Iterator as _Iterator


@_dataclass
class _TimePatch:
    _pin: "Instant | ZonedDateTime | OffsetDateTime | SystemDateTime"
    _keep_ticking: bool

    def shift(self, *args, **kwargs):
        if self._keep_ticking:
            self._pin = new = (self._pin + (Instant.now() - self._pin)).add(
                *args, **kwargs
            )
            _patch_time_keep_ticking(
                new if isinstance(new, Instant) else new.instant()
            )
        else:
            self._pin = new = self._pin.add(*args, **kwargs)
            _patch_time_frozen(
                new if isinstance(new, Instant) else new.instant()
            )


@_contextmanager
def patch_current_time(
    dt: "Instant | ZonedDateTime | OffsetDateTime | SystemDateTime",
    /,
    *,
    keep_ticking: bool,
) -> _Iterator[_TimePatch]:
    """Patch the current time to a fixed value (for testing purposes).
    Behaves as a context manager or decorator, with similar semantics to
    ``unittest.mock.patch``.

    Important
    ---------

    * This function should be used only for testing purposes. It is not
      thread-safe or part of the stable API.
    * This function only affects whenever's ``now`` functions. It does not
      affect the standard library's time functions or any other libraries.
      Use the ``time_machine`` package if you also want to patch other libraries.
    * It doesn't affect the system timezone.
      If you need to patch the system timezone, set the ``TZ`` environment
      variable in combination with ``time.tzset``. Be aware that this only
      works on Unix-like systems.

    Example
    -------

    >>> from whenever import Instant, patch_current_time
    >>> i = Instant.from_utc(1980, 3, 2, hour=2)
    >>> with patch_current_time(i, keep_ticking=False) as p:
    ...     assert Instant.now() == i
    ...     p.shift(hours=4)
    ...     assert i.now() == i.add(hours=4)
    ...
    >>> assert Instant.now() != i
    ...
    >>> @patch_current_time(i, keep_ticking=True)
    ... def test_thing(p):
    ...     assert (Instant.now() - i) < seconds(1)
    ...     p.shift(hours=8)
    ...     sleep(0.000001)
    ...     assert hours(8) < (Instant.now() - i) < hours(8.1)
    """
    instant = dt if isinstance(dt, Instant) else dt.instant()
    if keep_ticking:
        _patch_time_keep_ticking(instant)
    else:
        _patch_time_frozen(instant)

    try:
        yield _TimePatch(dt, keep_ticking)
    finally:
        _unpatch_time()
