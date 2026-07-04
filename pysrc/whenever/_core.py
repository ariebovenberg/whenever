"""This makes the core API importable (internally) whether or not the Rust
extension is available."""

try:  # pragma: no cover
    from ._whenever import *
    from ._whenever import (
        _clear_tz_cache as _clear_tz_cache,
        _clear_tz_cache_by_keys as _clear_tz_cache_by_keys,
        _get_tzpath as _get_tzpath,
        _patch_time_frozen as _patch_time_frozen,
        _patch_time_keep_ticking as _patch_time_keep_ticking,
        _set_tzpath as _set_tzpath,
        _unpatch_time as _unpatch_time,
        _unpkl_date,
        _unpkl_ddelta,
        _unpkl_dtdelta,
        _unpkl_inst,
        _unpkl_local,
        _unpkl_offset,
        _unpkl_tdelta,
        _unpkl_time,
        _unpkl_utc,
        _unpkl_zoned,
    )

    _EXTENSION_LOADED = True

except ModuleNotFoundError as e:
    # Ensure we don't silence other ModuleNotFoundErrors!
    if e.name != "whenever._whenever":  # pragma: no cover
        raise e
    from ._pywhenever import *
    from ._pywhenever import (
        _clear_tz_cache,
        _clear_tz_cache_by_keys,
        _get_tzpath,
        _patch_time_frozen,
        _patch_time_keep_ticking,
        _set_tzpath,
        _unpatch_time,
        _unpkl_date,
        _unpkl_ddelta,
        _unpkl_dtdelta,
        _unpkl_inst,
        _unpkl_local,
        _unpkl_offset,
        _unpkl_tdelta,
        _unpkl_time,
        _unpkl_utc,
        _unpkl_zoned,
    )

    _EXTENSION_LOADED = False

    # In pure Python mode, populate TZPATH eagerly (the Rust extension defers
    # this to first timezone lookup for faster import time).
    from ._utils import reset_tzpath

    reset_tzpath()

from ._ideltas import (
    ItemizedDateDelta,
    ItemizedDelta,
    _unpkl_iddelta,
    _unpkl_idelta,
)
