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
    "_set_tzpath",
    "reset_system_tz",
]

_NOGIL = hasattr(sys, "_is_gil_enabled") and not sys._is_gil_enabled()

_TZPATH: tuple[str, ...] = ()

# Our cache for loaded tz files. The design is based off that of `zoneinfo`.
_TZCACHE_LRU_SIZE = 8
_tzcache_lru: OrderedDict[str, TimeZone] = OrderedDict()
_tzcache_lookup: WeakValueDictionary[str, TimeZone] = WeakValueDictionary()

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


def _set_tzpath(to: tuple[str, ...]) -> None:
    global _TZPATH
    _TZPATH = to


def _clear_tz_cache() -> None:
    _tzcache_lookup.clear()
    with _tzcache_lru_lock:
        _tzcache_lru.clear()


def _clear_tz_cache_by_keys(keys: tuple[str, ...]) -> None:
    with _tzcache_lru_lock:
        for k in keys:
            _tzcache_lookup.pop(k, None)
            _tzcache_lru.pop(k, None)


def get_tz(key: str) -> TimeZone:
    instance = _tzcache_lookup.get(key)
    if instance is None:
        # Concurrency note: we accept the possibility of multiple threads
        # loading the same timezone at the same time, since TimeZone instances
        # are immutable after construction. The last one to write wins.
        instance = _tzcache_lookup.setdefault(
            key, _load_tz(validate_tzid(key))
        )

    with _tzcache_lru_lock:
        _tzcache_lru[key] = _tzcache_lru.pop(key, instance)
        if len(_tzcache_lru) > _TZCACHE_LRU_SIZE:
            try:
                _tzcache_lru.popitem(last=False)
            except KeyError:  # pragma: no cover
                pass  # theoretically possible if other threads are clearing too

    return instance


def validate_tzid(key: str) -> SafeTzId:
    """Checks for invalid characters and path traversal in the key."""
    if (
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
    ):
        return SafeTzId(key)
    else:
        raise TimeZoneNotFoundError.for_key(key)


# Alias for a TZ key that has been confirmed not to be a path traversal
# or contain other "bad" characters.
SafeTzId = NewType("SafeTzId", str)


def _try_tzif_from_path(key: SafeTzId) -> bytes | None:
    for search_path in _TZPATH:
        target = os.path.join(search_path, key)
        if os.path.isfile(target):
            with open(target, "rb") as f:
                return f.read()
    return None


def _tzif_from_tzdata(key: SafeTzId) -> bytes:
    try:
        tzdata_path = __import__("tzdata.zoneinfo").zoneinfo.__path__[0]
        # We check before we read, since the resulting exceptions vary
        # on different platforms
        if os.path.isfile(
            relpath := os.path.join(tzdata_path, *key.split("/"))
        ):
            with open(relpath, "rb") as f:
                return f.read()
        else:
            raise FileNotFoundError()
    # Several exceptions amount to "can't find the key"
    except (
        ImportError,
        FileNotFoundError,
        UnicodeEncodeError,
    ):
        raise TimeZoneNotFoundError.for_key(key)


def _load_tz(key: SafeTzId) -> TimeZone:
    tzif = _try_tzif_from_path(key) or _tzif_from_tzdata(key)
    if not tzif.startswith(b"TZif"):
        # We've found a file, but doesn't look like a TZif file.
        # Stop here instead of getting a cryptic error later.
        raise TimeZoneNotFoundError.for_key(key)

    return TimeZone.parse_tzif(tzif, key)


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
    """Resets the cached system timezone to the current system timezone."""
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
