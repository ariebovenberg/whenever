"""Timezone database access and caching."""

from __future__ import annotations

import os.path
import sys
from collections import OrderedDict
from typing import TYPE_CHECKING, NewType
from weakref import WeakValueDictionary

from . import system
from .tzif import TimeZone

__all__ = [
    "TimeZoneNotFoundError",
    "get_tz",
    "get_system_tz",
    "_clear_tz_cache",
    "_clear_tz_cache_by_keys",
    "_get_tzpath",
    "get_tzpath",
    "_set_tzpath",
    "reset_system_tz",
]

_NOGIL = hasattr(sys, "_is_gil_enabled") and not sys._is_gil_enabled()

_TZPATH: tuple[str, ...] = ()

# Our cache for loaded tz files. The design is based off that of `zoneinfo`.
_TZCACHE_LRU_SIZE = 32
_tzcache_lru: OrderedDict[str, TimeZone] = OrderedDict()
_tzcache_lookup: WeakValueDictionary[str, TimeZone] = WeakValueDictionary()

_TzDirIndex = dict[str, str]
_TzDirCache = dict[str, _TzDirIndex]

# Maps each scanned directory path to its ASCII-lowercase entry names and
# their spelling on disk. Published only after a successful TZif load.
_tzdir_cache: _TzDirCache = {}

# OrderedDict is thread-unsafe in Python < 3.14 under free-threading.
# Thus we need an extra lock to ensure thread-safety of our LRU cache.
if TYPE_CHECKING or (
    _NOGIL and sys.version_info < (3, 14)
):  # pragma: no cover
    from threading import Lock as _Lock
else:

    class _Lock:
        def __enter__(self) -> None:
            pass

        def __exit__(self, *args) -> None:
            pass


_tzcache_lru_lock = _Lock()
_tzdir_cache_lock = _Lock()

# One-entry fast path: skips LRU update for repeated lookups of the same zone.
# Thread-safe for GIL Python (atomic assignment); under free-threading the
# worst case is a benign missed cache-hit, which falls back to the normal path.
_last_tz_key: str | None = None
_last_tz_val: TimeZone | None = None


def _set_tzpath(to: tuple[str, ...]) -> None:
    global _TZPATH
    _TZPATH = to
    _clear_tzdir_cache()


def get_tzpath() -> tuple[str, ...]:
    """Return a snapshot of the current timezone search path."""
    return _TZPATH


_get_tzpath = get_tzpath


def _clear_tz_cache() -> None:
    global _last_tz_key, _last_tz_val
    _last_tz_key = None
    _last_tz_val = None
    _tzcache_lookup.clear()
    with _tzcache_lru_lock:
        _tzcache_lru.clear()
    _clear_tzdir_cache()


def _clear_tz_cache_by_keys(keys: tuple[str, ...]) -> None:
    global _last_tz_key, _last_tz_val
    for k in keys:
        if not isinstance(k, str):
            raise TypeError("key must be a string")
    normalized_keys = tuple(k.lower() for k in keys)
    if _last_tz_key in normalized_keys:
        _last_tz_key = None
        _last_tz_val = None
    with _tzcache_lru_lock:
        for key in normalized_keys:
            _tzcache_lookup.pop(key, None)
            _tzcache_lru.pop(key, None)
    # Directory indices are shared by many keys, so selective invalidation
    # would be both more complex and less predictable than clearing them all.
    _clear_tzdir_cache()


def get_tz(key: str) -> TimeZone:
    global _last_tz_key, _last_tz_val
    cache_key = _normalize_tzid(key)
    if cache_key == _last_tz_key:
        return _last_tz_val  # type: ignore[return-value]

    if (instance := _tzcache_lookup.get(cache_key)) is None:
        # Concurrency note: we accept the possibility of multiple threads
        # loading the same timezone at the same time, since TimeZone instances
        # are immutable after construction. The last one to write wins.
        tzif, canonical_key, updates = _load_tz(cache_key, key)
        loaded = TimeZone.parse_tzif(tzif, canonical_key)
        _publish_tzdir_cache(updates)
        instance = _tzcache_lookup.setdefault(cache_key, loaded)

    with _tzcache_lru_lock:
        _tzcache_lru[cache_key] = _tzcache_lru.pop(cache_key, instance)
        if len(_tzcache_lru) > _TZCACHE_LRU_SIZE:
            try:
                _tzcache_lru.popitem(last=False)
            except KeyError:  # pragma: no cover
                pass  # theoretically possible if other threads are clearing too

    _last_tz_key = cache_key
    _last_tz_val = instance
    return instance


def _is_valid_tzid(key: str) -> bool:
    return (
        key.isascii()
        # There's no standard limit on IANA tz IDs, but we have to draw
        # the line somewhere to prevent abuse.
        and 0 < len(key) < 100
        and all(b.isalnum() or b in "-_+/." for b in key)
        # specific sequences not allowed
        and ".." not in key
        and "//" not in key
        and "/./" not in key
        # specific restrictions on the first and list characters
        and key[0] not in ".-+/"
        and key[-1] != "/"
    )


def _normalize_tzid(key: str) -> NormalizedTzId:
    # Not a redundant check on an annotated argument: this is the boundary
    # where untyped callers arrive, and without it the validation below
    # fails with a leaked AttributeError (or, for bytes, passes silently).
    if not isinstance(key, str):
        raise TypeError("tz must be a string")
    if not _is_valid_tzid(key):
        raise TimeZoneNotFoundError.for_key(key)
    return NormalizedTzId(key.lower())


NormalizedTzId = NewType("NormalizedTzId", str)
SafeTzId = NewType("SafeTzId", str)


def validate_tzid(key: str) -> SafeTzId:
    if _is_valid_tzid(key):
        return SafeTzId(key)
    raise TimeZoneNotFoundError.for_key(key)


# A successful (path, database-spelled ID, pending directory indices) and
# cached directory paths to invalidate before retrying.
_ResolvedPath = tuple[str, str, _TzDirCache]
_ResolveAttempt = tuple[_ResolvedPath | None, list[str]]


def _clear_tzdir_cache() -> None:
    with _tzdir_cache_lock:
        _tzdir_cache.clear()


def _publish_tzdir_cache(updates: _TzDirCache) -> None:
    with _tzdir_cache_lock:
        _tzdir_cache.update(updates)


def _discard_tzdir_cache(paths: list[str]) -> None:
    with _tzdir_cache_lock:
        for p in paths:
            _tzdir_cache.pop(p, None)


def _cached_tzdir(path: str) -> _TzDirIndex | None:
    with _tzdir_cache_lock:
        return _tzdir_cache.get(path)


def _scan_tzdir(path: str) -> _TzDirIndex | None:
    try:
        index: _TzDirIndex = {}
        with os.scandir(path) as entries:
            for e in entries:
                n = e.name
                if n.isascii():
                    # Case collisions are unsupported; retain whichever entry
                    # the filesystem enumerates first.
                    index.setdefault(n.lower(), n)
        return index
    except OSError:
        return None


def _resolve_path_once(base: str, key: NormalizedTzId) -> _ResolveAttempt:
    path = base
    updates: _TzDirCache = {}
    cached_paths: list[str] = []
    for c in key.split("/"):
        if (index := _cached_tzdir(path)) is not None and (
            name := index.get(c)
        ) is not None:
            cached_paths.append(path)
        else:
            if (index := _scan_tzdir(path)) is None:
                return None, cached_paths
            if (name := index.get(c)) is None:
                return None, []
            updates[path] = index
        path = os.path.join(path, name)

    if os.path.isfile(path):
        return (
            path,
            os.path.relpath(path, base).replace(os.sep, "/"),
            updates,
        ), []
    return None, cached_paths


def _resolve_path(base: str, key: NormalizedTzId) -> _ResolvedPath | None:
    resolved, cached_paths = _resolve_path_once(base, key)
    if resolved is not None or not cached_paths:
        return resolved

    # A cached positive may have been removed or renamed. Invalidate the
    # contributing indices and retry once from the filesystem.
    _discard_tzdir_cache(cached_paths)
    resolved, _ = _resolve_path_once(base, key)
    return resolved


def _read_tzif_from_path(
    base: str, key: NormalizedTzId
) -> tuple[bytes, str, _TzDirCache] | None:
    if (resolved := _resolve_path(base, key)) is None:
        return None
    path, canonical_key, updates = resolved
    with open(path, "rb") as f:
        return f.read(), canonical_key, updates


def _try_tzif_from_path(
    key: NormalizedTzId, original_key: str
) -> tuple[bytes, str, _TzDirCache] | None:
    try:
        for search_path in _TZPATH:
            if (tzif := _read_tzif_from_path(search_path, key)) is not None:
                return tzif
    except OSError:
        raise TimeZoneNotFoundError.for_key(original_key) from None
    return None


def _tzif_from_tzdata(
    key: NormalizedTzId, original_key: str
) -> tuple[bytes, str, _TzDirCache]:
    try:
        tzdata_path = __import__("tzdata.zoneinfo").zoneinfo.__path__[0]
        if (tzif := _read_tzif_from_path(tzdata_path, key)) is None:
            raise FileNotFoundError()
        return tzif
    # Several exceptions amount to "can't find the key"
    except (
        ImportError,
        FileNotFoundError,
        OSError,
        UnicodeEncodeError,
    ):
        raise TimeZoneNotFoundError.for_key(original_key)


def _load_tz(
    key: NormalizedTzId, original_key: str
) -> tuple[bytes, str, _TzDirCache]:
    tzif = _try_tzif_from_path(key, original_key) or _tzif_from_tzdata(
        key, original_key
    )
    if not tzif[0].startswith(b"TZif"):
        # We've found a file, but doesn't look like a TZif file.
        # Stop here instead of getting a cryptic error later.
        raise TimeZoneNotFoundError.for_key(original_key)
    return tzif


_CACHED_SYSTEM_TZ: TimeZone | None = None


def get_system_tz() -> TimeZone:
    global _CACHED_SYSTEM_TZ
    # This lookup is intentionally lock-free for performance reasons.
    # This is valid because:
    # - TimeZone instances are immutable after construction
    # - loading the system timezone is side-effect free
    # - Last writer wins; all outcomes are acceptable.
    # - Python guarantees atomic assignment to the module global variables
    #   since it's a `dict`. This guarantee may change in the future, but for now
    #   it's safe enough. See docs.python.org/3/howto/free-threading-python.html#thread-safety
    if _CACHED_SYSTEM_TZ is None:
        _CACHED_SYSTEM_TZ = _read_system_tz()  # pragma: no cover
    return _CACHED_SYSTEM_TZ


def reset_system_tz() -> None:
    """Resets the cached system timezone to the currently set system timezone.

    >>> os.environ["TZ"] = "America/New_York"
    >>> reset_system_tz()  # system tz is now New York
    >>> os.environ["TZ"] = "Europe/London"
    >>> ZonedDateTime.now(SYSTEM_TZ)  # still uses cached New York tz
    ZonedDateTime(2025-06-18 15:11:08-04:00[America/New_York])
    >>> reset_system_tz()  # system tz is now London
    >>> ZonedDateTime.now(SYSTEM_TZ)
    ZonedDateTime(2025-06-18 20:11:08+01:00[Europe/London])
    """
    global _CACHED_SYSTEM_TZ
    _CACHED_SYSTEM_TZ = _read_system_tz()


def _read_system_tz() -> TimeZone:
    tz_type, tz_value = system.get_tz()
    if tz_type == 0:  # IANA TZID
        return get_tz(tz_value)
    elif tz_type == 2:  # IANA TZID or Posix string (we don't know which)
        try:
            return get_tz(tz_value)
        except TimeZoneNotFoundError:
            # If the key is not found, it might be a PosixTz string
            return TimeZone.parse_posix(tz_value)
    else:  # file-based timezone (no key)
        assert tz_type == 1, "Unknown system timezone type"
        with open(tz_value, "rb") as f:
            return TimeZone.parse_tzif(f.read())


class TimeZoneNotFoundError(ValueError):
    """A timezone with the given ID was not found"""

    @classmethod
    def for_key(cls, key: str) -> TimeZoneNotFoundError:
        return cls(f"No time zone found for key: {key!r}")
