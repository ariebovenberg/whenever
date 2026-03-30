"""This makes the core API importable (internally) whether or not the Rust
extension is available."""

try:  # pragma: no cover
    from ._whenever import *
    from ._whenever import (
        _clear_tz_cache as _clear_tz_cache,
        _clear_tz_cache_by_keys as _clear_tz_cache_by_keys,
        _patch_time_frozen as _patch_time_frozen,
        _patch_time_keep_ticking as _patch_time_keep_ticking,
        _set_tzpath as _set_tzpath,
        _unpatch_time as _unpatch_time,
        _unpkl_date,
        _unpkl_ddelta,
        _unpkl_dtdelta,
        _unpkl_inst,
        _unpkl_local,
        _unpkl_md,
        _unpkl_offset,
        _unpkl_tdelta,
        _unpkl_time,
        _unpkl_utc,
        _unpkl_ym,
        _unpkl_zoned,
    )

    # Backfill symbols not yet in the Rust extension (temporary)
    try:
        from ._whenever import _unpkl_idelta as _unpkl_idelta
    except ImportError:
        from ._pywhenever import _unpkl_idelta as _unpkl_idelta
    try:
        from ._whenever import _unpkl_iddelta as _unpkl_iddelta
    except ImportError:
        from ._pywhenever import _unpkl_iddelta as _unpkl_iddelta
    try:
        from ._whenever import ItemizedDelta as ItemizedDelta
    except ImportError:
        from ._pywhenever import ItemizedDelta as ItemizedDelta
    try:
        from ._whenever import ItemizedDateDelta as ItemizedDateDelta
    except ImportError:
        from ._pywhenever import ItemizedDateDelta as ItemizedDateDelta

    _EXTENSION_LOADED = True

except ModuleNotFoundError as e:
    # Ensure we don't silence other ModuleNotFoundErrors!
    if e.name != "whenever._whenever":  # pragma: no cover
        raise e
    from ._pywhenever import *
    from ._pywhenever import (
        _clear_tz_cache,
        _clear_tz_cache_by_keys,
        _patch_time_frozen,
        _patch_time_keep_ticking,
        _set_tzpath,
        _unpatch_time,
        _unpkl_date,
        _unpkl_ddelta,
        _unpkl_dtdelta,
        _unpkl_iddelta,
        _unpkl_idelta,
        _unpkl_inst,
        _unpkl_local,
        _unpkl_md,
        _unpkl_offset,
        _unpkl_tdelta,
        _unpkl_time,
        _unpkl_utc,
        _unpkl_ym,
        _unpkl_zoned,
    )

    _EXTENSION_LOADED = False

from ._typing import *

MONDAY = Weekday.MONDAY
TUESDAY = Weekday.TUESDAY
WEDNESDAY = Weekday.WEDNESDAY
THURSDAY = Weekday.THURSDAY
FRIDAY = Weekday.FRIDAY
SATURDAY = Weekday.SATURDAY
SUNDAY = Weekday.SUNDAY
