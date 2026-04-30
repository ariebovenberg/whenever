from __future__ import annotations

from typing import TypeAlias

from ._core import *
from ._core import (  # The unpickle functions must be findable at module-level
    _EXTENSION_LOADED,
    _unpkl_date,
    _unpkl_iddelta,
    _unpkl_idelta,
    _unpkl_inst,
    _unpkl_iwd,
    _unpkl_local,
    _unpkl_md,
    _unpkl_offset,
    _unpkl_tdelta,
    _unpkl_time,
    _unpkl_utc,
    _unpkl_ym,
    _unpkl_zoned,
)
from ._typing import *
from ._utils import *

# These imports are only needed for the doc generation, which only
# runs in pure Python mode.
if not _EXTENSION_LOADED:  # pragma: no cover
    from ._pywhenever import __all__

# Yes, we could get the version with importlib.metadata,
# but we try to keep our import time as low as possible.
__version__ = "0.11.0"

# We expose these at module-level for convenience
MONDAY = Weekday.MONDAY
TUESDAY = Weekday.TUESDAY
WEDNESDAY = Weekday.WEDNESDAY
THURSDAY = Weekday.THURSDAY
FRIDAY = Weekday.FRIDAY
SATURDAY = Weekday.SATURDAY
SUNDAY = Weekday.SUNDAY

reset_tzpath()  # populate the tzpath once at startup


def __getattr__(name: str) -> object:
    # This ensures we get the most up-to-date TZPATH.
    if name == "TZPATH":
        from ._utils import TZPATH

        return TZPATH
    raise AttributeError(f"module '{__name__}' has no attribute '{name}'")


AnyDelta: TypeAlias = TimeDelta | ItemizedDelta | ItemizedDateDelta
