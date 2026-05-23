from __future__ import annotations

from typing import TypeAlias

from ._core import *
from ._core import (  # The unpickle functions must be findable at module-level
    _EXTENSION_LOADED,
    _unpkl_date,
    _unpkl_ddelta,
    _unpkl_dtdelta,
    _unpkl_iddelta,
    _unpkl_idelta,
    _unpkl_inst,
    _unpkl_local,
    _unpkl_offset,
    _unpkl_tdelta,
    _unpkl_time,
    _unpkl_utc,
    _unpkl_zoned,
)

# Yes, we could get the version with importlib.metadata,
# but we try to keep our import time as low as possible.
__version__ = "0.10.1"

__all__ = (
    # Date and time
    "Date",
    "YearMonth",
    "MonthDay",
    "IsoWeekDate",
    "Time",
    "Instant",
    "OffsetDateTime",
    "ZonedDateTime",
    "PlainDateTime",
    # Deltas and time units
    "DateDelta",
    "TimeDelta",
    "DateTimeDelta",
    "ItemizedDelta",
    "ItemizedDateDelta",
    "years",
    "months",
    "weeks",
    "days",
    "hours",
    "minutes",
    "seconds",
    "milliseconds",
    "microseconds",
    "nanoseconds",
    # Exceptions/warnings
    "DaysAssumed24HoursWarning",
    "StaleOffsetWarning",
    "NaiveArithmeticWarning",
    "PotentialDstBugWarning",
    "WheneverDeprecationWarning",
    "SkippedTime",
    "RepeatedTime",
    "InvalidOffsetError",
    "ImplicitlyIgnoringDST",
    "TimeZoneNotFoundError",
    # Enums/constants
    "Weekday",
    "MONDAY",
    "TUESDAY",
    "WEDNESDAY",
    "THURSDAY",
    "FRIDAY",
    "SATURDAY",
    "SUNDAY",
    # Other
    "reset_system_tz",
    "AnyDelta",
)

# In pure Python mode, populate TZPATH eagerly (the Rust extension defers
# this to first timezone lookup for faster import time).
if not _EXTENSION_LOADED:  # pragma: no cover
    from ._utils import reset_tzpath

    reset_tzpath()

# Names lazily imported from submodules.
# When any name from a group is first accessed, the whole module is loaded
# and all names from it are pre-populated, so subsequent accesses skip __getattr__.
_LAZY_MODULES = {
    f"{__package__}._utils": (
        "patch_current_time",
        "reset_tzpath",
        "clear_tzcache",
        "available_timezones",
    ),
    f"{__package__}._typing": (
        "RoundModeStr",
        "DeltaUnitStr",
        "DateDeltaUnitStr",
        "ExactDeltaUnitStr",
        "DisambiguateStr",
        "OffsetMismatchStr",
    ),
    f"{__package__}._shared": (
        "YearMonth",
        "MonthDay",
        "Weekday",
        "IsoWeekDate",
        "_unpkl_iwd",
        "_unpkl_md",
        "_unpkl_ym",
        "MONDAY",
        "TUESDAY",
        "WEDNESDAY",
        "THURSDAY",
        "FRIDAY",
        "SATURDAY",
        "SUNDAY",
    ),
}
_LAZY_NAMES = {
    n: module for module, names in _LAZY_MODULES.items() for n in names
}


def __getattr__(name: str) -> object:
    # TZPATH is a live view, not a cached value.
    if name == "TZPATH":
        from ._core import _get_tzpath

        return _get_tzpath()
    if src := _LAZY_NAMES.get(name):
        mod = __import__(src, fromlist=("",))
        g = globals()
        for n in _LAZY_MODULES[src]:
            g[n] = getattr(mod, n)
        return g[name]
    raise AttributeError(f"module '{__name__}' has no attribute '{name}'")


AnyDelta: TypeAlias = (
    DateDelta | TimeDelta | DateTimeDelta | ItemizedDelta | ItemizedDateDelta
)
