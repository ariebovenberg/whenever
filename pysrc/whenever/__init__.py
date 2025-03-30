from __future__ import annotations

try:  # pragma: no cover
    from ._whenever import *
    from ._whenever import (
        _clear_tz_cache,
        _clear_tz_cache_by_keys,
        _patch_time_frozen,
        _patch_time_keep_ticking,
        _set_tzpath,
        _unpatch_time,
        _unpkl_date,
        _unpkl_ddelta,
        _unpkl_dtdelta,
        _unpkl_inst,
        _unpkl_local,
        _unpkl_md,
        _unpkl_offset,
        _unpkl_system,
        _unpkl_tdelta,
        _unpkl_time,
        _unpkl_utc,
        _unpkl_ym,
        _unpkl_zoned,
    )

    _EXTENSION_LOADED = True

except ModuleNotFoundError as e:
    if e.name != "whenever._whenever":  # pragma: no cover
        raise e
    from ._pywhenever import *
    from ._pywhenever import (  # for the docs
        __all__,
        _BasicConversions,
        _clear_tz_cache,
        _clear_tz_cache_by_keys,
        _KnowsInstant,
        _KnowsInstantAndLocal,
        _KnowsLocal,
        _patch_time_frozen,
        _patch_time_keep_ticking,
        _set_tzpath,
        _unpatch_time,
        _unpkl_date,
        _unpkl_ddelta,
        _unpkl_dtdelta,
        _unpkl_inst,
        _unpkl_local,
        _unpkl_md,
        _unpkl_offset,
        _unpkl_system,
        _unpkl_tdelta,
        _unpkl_time,
        _unpkl_utc,
        _unpkl_ym,
        _unpkl_zoned,
    )

    _EXTENSION_LOADED = False

import os as _os
import sysconfig as _sysconfig
from contextlib import contextmanager as _contextmanager
from dataclasses import dataclass as _dataclass
from importlib.resources import open_text as _open_resource
from itertools import chain as _chain
from pathlib import Path as _Path
from typing import Iterable as _Iterable, Iterator as _Iterator

from ._pywhenever import __version__


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


TZPATH: tuple[str, ...] = ()
"""The paths in which ``whenever`` will search for timezone data.
By default, this determined the same way as :data:`zoneinfo.TZPATH`,
although you can override it using :func:`whenever.reset_tzpath` for ``whenever`` specifically.
"""


def reset_tzpath(target: _Iterable[str | _os.PathLike[str]] | None = None, /):
    """Reset or set the paths in which ``whenever`` will search for timezone data.

    It does not affect the :mod:`zoneinfo` module or other libraries.

    Note
    ----
    Due to caching, you may find that looking up a timezone after setting the tzpath
    doesn't load the timezone data from the new path. You may need to call
    :func:`clear_tzcache` if you want to force loading *all* timezones from the new path.
    Note that clearing the cache may have unexpected side effects, however.

    Behaves similarly to :func:`zoneinfo.reset_tzpath`
    """
    global TZPATH

    if target is not None:
        # This is such a common mistake, that we raise a descriptive error
        if isinstance(target, (str, bytes)):
            raise TypeError("tzpath must be an iterable of paths")

        if not all(map(_os.path.isabs, target)):
            raise ValueError("tzpaths must be absolute paths")
        TZPATH = tuple(str(_Path(p)) for p in target)
    else:
        TZPATH = _tzpath_from_env()
    _set_tzpath(TZPATH)


def _tzpath_from_env() -> tuple[str, ...]:
    try:
        env_var = _os.environ["PYTHONTZPATH"]
    except KeyError:
        env_var = _sysconfig.get_config_var("TZPATH")

    if not env_var:
        return ()

    raw_tzpath = env_var.split(_os.pathsep)
    # according to spec, we're allowed to silently ignore invalid paths
    new_tzpath = tuple(filter(_os.path.isabs, raw_tzpath))
    return new_tzpath


def clear_tzcache(*, only_keys: _Iterable[str] | None = None) -> None:
    """Clear the timezone cache. If ``only_keys`` is provided, only the cache for those
    keys will be cleared.

    Caution
    -------
    Calling this function may change the behavior of existing ``ZonedDateTime``
    instances in surprising ways. Most significantly, the
    ``exact_eq()`` method will return ``False`` between instances created before and after clearing the cache.

    **Use this function only if you know that you need to.**

    Behaves similarly to :meth:`zoneinfo.ZoneInfo.clear_cache`.
    """
    if only_keys is None:
        _clear_tz_cache()
    else:
        _clear_tz_cache_by_keys(tuple(only_keys))


def available_timezones() -> set[str]:
    """Gather the set of all available timezones.

    Each call to this function will recalculate the available timezone names
    depending on the currently configured ``TZPATH``, and the
    presence of the ``tzdata`` package.

    Warning
    -------
    This function may open a large number of files, since the first few bytes
    of timezone files must be read to determine if they are valid.

    Note
    ----

    This function behaves similarly to :func:`zoneinfo.available_timezones`,
    which means it ignores the "special" zones (e.g. posixrules, right/posix, etc.)

    It should give the same result as :func:`zoneinfo.available_timezones`,
    unless ``whenever`` was configured to use a different tzpath
    using :func:`reset_tzpath`.

    """
    zones = set()
    # Get the zones from the tzdata package, if available
    try:
        with _open_resource("tzdata", "zones") as f:
            zones.update(map(str.strip, f))
    except (ImportError, FileNotFoundError):
        pass

    # Get the zones from the tzpath directories
    for base in TZPATH:
        zones.update(_find_all_tznames(_Path(base)))

    zones.discard("posixrules")  # a special file that shouldn't be included
    return zones


# Recursively find all tzfiles in the tzpath directories.
# Recursion is safe here since the file tree is trusted, and nesting doesn't
# even approach the recursion limit.
def _find_all_tznames(base: _Path) -> _Iterator[str]:
    if not base.is_dir():
        return
    for entry in base.iterdir():
        if entry.is_dir():
            if entry.name in ("right", "posix"):
                # These directories contain special files that shouldn't be included
                continue
            else:
                for p in _find_nested_tzfiles(entry):
                    yield p.relative_to(base).as_posix()
        elif _is_tzifile(entry):
            yield entry.name


def _find_nested_tzfiles(path: _Path) -> _Iterator[_Path]:
    assert path.is_dir()
    for entry in path.iterdir():
        if entry.is_dir():
            yield from _find_nested_tzfiles(entry)
        elif _is_tzifile(entry):
            yield entry


def _is_tzifile(p: _Path) -> bool:
    """Check if the file is a tzifile."""
    try:
        with p.open("rb") as f:
            return f.read(4) == b"TZif"
    except OSError:
        return False


reset_tzpath()  # populate the tzpath once at startup
