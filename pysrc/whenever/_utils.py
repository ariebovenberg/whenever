"""Misc public utilities, e.g. to manage the time zone cache, or patch the time"""

from __future__ import annotations

import os.path  # NOTE: we don't use pathlib here to keep our imports light
from contextlib import contextmanager
from threading import RLock
from typing import Any, Iterable, Iterator, Protocol
from warnings import warn

from ._common import DAYS_NOT_ALWAYS_24H_MSG, UNSET
from ._core import (
    DaysAssumed24HoursWarning,
    Instant,
    OffsetDateTime,
    TimeDelta,
    ZonedDateTime,
    _clear_tz_cache,
    _clear_tz_cache_by_keys,
    _patch_time_frozen,
    _patch_time_keep_ticking,
    _set_tzpath,
    _unpatch_time,
    get_tzpath,
)

# Maintainer's notes:
# - Yes I dislike the name `utils` too, but it seems to fit OK in this case.
# - These functions are implemented in Python regardless of whether the Rust
#   extension is active. This is fine because they are not performance-critical,
#   and build upon the core API.


__all__ = [
    "TimePatch",
    "patch_current_time",
    "get_tzpath",
    "reset_tzpath",
    "clear_tzcache",
    "available_timezones",
]


class TimePatch(Protocol):  # pragma: no cover
    """The handle to an active **time patch**: move the patched clock with
    ``shift()`` or ``move_to()``.
    """

    def shift(
        self,
        delta: TimeDelta = UNSET,
        /,
        *,
        weeks: float = 0,
        days: float = 0,
        hours: float = 0,
        minutes: float = 0,
        seconds: float = 0,
        milliseconds: float = 0,
        microseconds: float = 0,
        nanoseconds: int = 0,
        days_assumed_24h_ok: bool = False,
    ) -> None:
        """Move the patched clock by an elapsed time, given as a
        ``TimeDelta`` or as the keywords of ``Instant.add()``.
        ``days=`` and ``weeks=`` count 24-hour days and warn with
        :exc:`~whenever.DaysAssumed24HoursWarning` unless
        ``days_assumed_24h_ok=True``. A ticking patch shifts from the
        current instant.
        """
        ...

    def move_to(
        self,
        value: Instant | OffsetDateTime | ZonedDateTime,
        /,
    ) -> None:
        """Move the patched clock to an exact time."""
        ...


class _TimePatch:
    _pin: Instant
    _keep_ticking: bool
    _active: bool

    def __init__(
        self,
        pin: Instant,
        keep_ticking: bool,
    ):
        self._pin = pin
        self._keep_ticking = keep_ticking
        self._active = True

    def _check_active(self) -> None:
        if not self._active:
            raise RuntimeError("time patch is no longer active")

    def _apply(self, pin: Instant, /) -> None:
        if self._keep_ticking:
            _patch_time_keep_ticking(pin)
        else:
            _patch_time_frozen(pin)
        self._pin = pin

    def shift(self, *args: Any, **kwargs: Any) -> None:
        """Move the patched clock by an elapsed time, given as a
        ``TimeDelta`` or as the keywords of ``Instant.add()``.
        ``days=`` and ``weeks=`` count 24-hour days and warn with
        :exc:`~whenever.DaysAssumed24HoursWarning` unless
        ``days_assumed_24h_ok=True``. A ticking patch shifts from the
        current instant.
        """
        if not args:
            # Build the delta here rather than in Instant.add(), so that the
            # days-are-24-hours warning points at the caller of shift().
            ok = kwargs.pop("days_assumed_24h_ok", False)
            delta = TimeDelta(**kwargs, days_assumed_24h_ok=True)
            if (kwargs.get("weeks") or kwargs.get("days")) and not ok:
                warn(
                    DAYS_NOT_ALWAYS_24H_MSG,
                    DaysAssumed24HoursWarning,
                    stacklevel=2,
                )
            args, kwargs = (delta,), {}
        with _patch_lock:
            self._check_active()
            current = Instant.now() if self._keep_ticking else self._pin
            self._apply(current.add(*args, **kwargs))

    def move_to(
        self,
        value: Instant | OffsetDateTime | ZonedDateTime,
        /,
    ) -> None:
        """Move the patched clock to an exact time."""
        with _patch_lock:
            self._check_active()
            if not isinstance(value, (Instant, OffsetDateTime, ZonedDateTime)):
                raise TypeError(
                    "move_to() argument must be an Instant, OffsetDateTime, "
                    "or ZonedDateTime"
                )
            self._apply(
                value if isinstance(value, Instant) else value.to_instant()
            )


_active_patch: _TimePatch | None = None
_patch_lock = RLock()


@contextmanager
def patch_current_time(
    dt: Instant | ZonedDateTime | OffsetDateTime,
    /,
    *,
    keep_ticking: bool,
) -> Iterator[TimePatch]:
    """Patch the current time as whenever sees it, for testing.
    A **frozen** patch (``keep_ticking=False``) holds one instant; a
    **ticking** patch (``keep_ticking=True``) advances from it.
    Works as a context manager or as a decorator. Patches do not nest:
    creating one while another is active raises :exc:`RuntimeError`.
    The decorator form does not pass the handle to the decorated function.

    Important
    ---------

    * This function should be used only for testing purposes.
    * This function only affects whenever's ``now`` functions. It does not
      affect the standard library's time functions or any other libraries.
      Use the ``time_machine`` package if you also want to patch other libraries.
    * It doesn't affect the system time zone.
      If you need to patch the system time zone, set the ``TZ`` environment
      variable in combination with :func:`~whenever.reset_system_tz`.

    Example
    -------

    >>> from whenever import Instant, patch_current_time, seconds
    >>> i = Instant.from_utc(1980, 3, 2, hour=2)
    >>> with patch_current_time(i, keep_ticking=False) as p:
    ...     assert Instant.now() == i
    ...     p.shift(hours=4)
    ...     assert i.now() == i.add(hours=4)
    ...
    >>> assert Instant.now() != i
    ...
    >>> @patch_current_time(i, keep_ticking=True)
    ... def test_thing():
    ...     assert (Instant.now() - i) < seconds(1)
    """
    global _active_patch

    if not isinstance(dt, (Instant, OffsetDateTime, ZonedDateTime)):
        raise TypeError(
            "patch_current_time() argument must be an Instant, "
            "OffsetDateTime, or ZonedDateTime"
        )
    with _patch_lock:
        if _active_patch is not None:
            raise RuntimeError("a time patch is already active")
        instant = dt if isinstance(dt, Instant) else dt.to_instant()
        if keep_ticking:
            _patch_time_keep_ticking(instant)
        else:
            _patch_time_frozen(instant)
        patch = _active_patch = _TimePatch(instant, keep_ticking)
    try:
        yield patch
    finally:
        with _patch_lock:
            try:
                _unpatch_time()
            finally:
                patch._active = False
                _active_patch = None


def reset_tzpath(
    target: Iterable[str | os.PathLike[str]] | None = None, /
) -> None:
    """Set the time zone search path: the directories in which ``whenever``
    looks for time zone data, in order. Each entry is an absolute path, as a
    ``str`` or a path-like object. Without an argument, the path is read
    again from the ``PYTHONTZPATH`` environment variable, falling back to the
    interpreter's compiled-in default, as :func:`zoneinfo.reset_tzpath` does.

    It does not affect the :mod:`zoneinfo` module or other libraries.

    Note
    ----
    Due to caching, looking up a time zone after changing the search path may
    continue to use the already loaded definition. Call :func:`clear_tzcache`
    to make subsequent lookups load from the new path.

    Raises
    ------
    TypeError
        If the argument is a single string or not an iterable of paths.
    ValueError
        If an entry is not an absolute path.
    """
    if target is None:
        from ._shared import _tzpath_from_env

        _set_tzpath(_tzpath_from_env())
        return
    # A string is iterable too, so this common mistake needs its own check.
    if isinstance(target, (str, bytes)):
        raise TypeError(_TZPATH_ARG_MSG)
    try:
        # Read once: an iterator is consumed by the first pass.
        entries = tuple(target)
    except TypeError:
        raise TypeError(_TZPATH_ARG_MSG) from None
    paths = []
    for e in entries:
        try:
            path = os.fspath(e)
        except TypeError:
            raise TypeError(_TZPATH_ARG_MSG) from None
        if not isinstance(path, str):
            raise TypeError(_TZPATH_ARG_MSG)
        if not os.path.isabs(path):
            raise ValueError(
                "time zone search path entries must be absolute paths, "
                f"got {e!r}"
            )
        paths.append(path)
    _set_tzpath(tuple(paths))


_TZPATH_ARG_MSG = "reset_tzpath() argument must be an iterable of paths"


def clear_tzcache(*, only_keys: Iterable[str] | None = None) -> None:
    """Clear the time zone cache. With ``only_keys``, clear only the entries
    for those time zone IDs, matched case-insensitively; an ID that is not
    cached is a no-op.

    Caution
    -------
    Calling this function may change the behavior of existing ``ZonedDateTime``
    instances in surprising ways. Most significantly, ``strict_eq()`` may
    return ``False`` between two time zone instances with the same time zone
    ID, if this time zone definition was changed on disk.

    **Use this function only if you know that you need to.**

    Behaves similarly to :meth:`zoneinfo.ZoneInfo.clear_cache`.

    Raises
    ------
    TypeError
        If ``only_keys`` is a single string or not an iterable of strings.
    """
    if only_keys is None:
        _clear_tz_cache()
    else:
        # This is such a common mistake, that we raise a descriptive error
        if isinstance(only_keys, (str, bytes)):
            raise TypeError("only_keys must be an iterable of time zone IDs")
        _clear_tz_cache_by_keys(tuple(only_keys))


def available_timezones() -> set[str]:
    """Gather the set of all available time zone IDs.

    Each call recalculates the set from the current time zone search path
    (see :func:`get_tzpath`) and the ``tzdata`` package, when it is installed.
    The special entries ``posixrules`` and ``localtime`` are excluded, as are
    the ``posix/`` and ``right/`` directories.

    Warning
    -------
    This function may open a large number of files, since the first few bytes
    of time zone files must be read to determine if they are valid.

    Note
    ----
    On the same time zone search path, the result equals
    :func:`zoneinfo.available_timezones` minus ``localtime``.
    """
    zones: set[str] = set()
    # Get the zones from the tzdata package, if available
    try:
        # NOTE: we don't use importlib.resources here,
        # to keep our imports lighter
        tzdata = __import__("tzdata").__path__[0]
        with open(os.path.join(tzdata, "zones")) as f:
            zones.update(map(str.strip, f))
    # coverage note: we *do* test tzdata and non-tzdata installs in CI
    except (ImportError, FileNotFoundError):  # pragma: no cover
        pass

    # Get the zones from the tzpath directories
    for base in get_tzpath():
        zones.update(_find_all_tznames(base))

    # special files that shouldn't be included
    zones.discard("posixrules")
    zones.discard("localtime")
    return zones


# Recursively find all tzfiles in the tzpath directories.
# Recursion is safe here since the file tree is trusted, and nesting doesn't
# even approach the recursion limit.
# NOTE: we don't use pathlib here, since we want to keep our imports light
def _find_all_tznames(base: str) -> Iterator[str]:
    if not os.path.isdir(base):
        return
    for name in os.listdir(base):
        entry = os.path.join(base, name)
        if os.path.isdir(entry):
            # These directories contain special files that shouldn't be included
            if name in ("right", "posix"):
                continue
            else:
                for path in _find_nested_tzfiles(entry):
                    yield os.path.relpath(path, base).replace("\\", "/")
        elif _is_tzifile(entry):
            yield name


def _find_nested_tzfiles(path: str) -> Iterator[str]:
    assert os.path.isdir(path)
    for name in os.listdir(path):
        entry = os.path.join(path, name)
        if os.path.isdir(entry):
            yield from _find_nested_tzfiles(entry)
        elif _is_tzifile(entry):
            yield entry


def _is_tzifile(p: str) -> bool:
    """Check if the file is a tzifile."""
    try:
        with open(p, "rb") as f:
            return f.read(4) == b"TZif"
    except OSError:  # pragma: no cover
        return False
