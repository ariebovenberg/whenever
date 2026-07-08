from __future__ import annotations


# Almost everything is lazily imported, to speed up initial import time.
def __getattr__(name: str) -> object:
    # When any name from a group is first accessed, the whole module is loaded
    # and all names from it are pre-populated, so subsequent accesses skip __getattr__.
    if src := _LAZY_NAMES.get(name):
        mod = __import__(src, fromlist=("",))
        g = globals()
        for n in _LAZY_MODULES[src]:
            g[n] = getattr(mod, n)
        return g[name]
    # TZPATH is a live view, not a cached value.
    elif name == "TZPATH":
        from ._core import _get_tzpath

        return _get_tzpath()
    elif name == "AnyDelta":
        from ._core import (
            DateDelta,
            DateTimeDelta,
            TimeDelta,
        )
        from ._ideltas import ItemizedDateDelta, ItemizedDelta

        globals()["AnyDelta"] = val = (
            DateDelta
            | TimeDelta
            | DateTimeDelta
            | ItemizedDelta
            | ItemizedDateDelta
        )
        return val
    elif name == "__version__":
        globals()["__version__"] = version = __import__(
            "importlib.metadata"
        ).metadata.version(__name__)
        return version

    raise AttributeError(f"module '{__name__}' has no attribute '{name}'")


# Ensures not-yet-imported names are still included in dir() output
def __dir__() -> list[str]:
    return sorted(
        (
            globals().keys()
            | _LAZY_NAMES.keys()
            | {"TZPATH", "AnyDelta", "__version__"}
        )
        - {"_LAZY_MODULES", "_LAZY_NAMES"}
    )


# This could be derived from the imports below, but it's easier for static
# analysis and IDEs if it's statically defined.
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
    "CalendarUnitCompositionWarning",
    "WheneverWarning",
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
    "patch_current_time",
    "reset_tzpath",
    "clear_tzcache",
    "available_timezones",
    "AnyDelta",
)


_LAZY_MODULES = {
    f"{__package__}._core": (
        # Classes
        "Date",
        "Time",
        "Instant",
        "OffsetDateTime",
        "ZonedDateTime",
        "PlainDateTime",
        "DateDelta",
        "TimeDelta",
        "DateTimeDelta",
        # Unit constructors
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
        "WheneverWarning",
        "PotentialDstBugWarning",
        "WheneverDeprecationWarning",
        "SkippedTime",
        "RepeatedTime",
        "InvalidOffsetError",
        "ImplicitlyIgnoringDST",
        "TimeZoneNotFoundError",
        # Other
        "reset_system_tz",
        "_EXTENSION_LOADED",
        # Unpickle functions
        "_unpkl_date",
        "_unpkl_ddelta",
        "_unpkl_dtdelta",
        "_unpkl_inst",
        "_unpkl_local",
        "_unpkl_offset",
        "_unpkl_tdelta",
        "_unpkl_time",
        "_unpkl_utc",
        "_unpkl_zoned",
    ),
    f"{__package__}._ideltas": (
        "CalendarUnitCompositionWarning",
        "ItemizedDelta",
        "ItemizedDateDelta",
        "_unpkl_iddelta",
        "_unpkl_idelta",
    ),
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
_LAZY_NAMES = {n: mod for mod, names in _LAZY_MODULES.items() for n in names}


# Without this, IDEs won't show proper information for our types.
# Note we don't actually import the variable from `typing`,
# as this has a runtime cost.
TYPE_CHECKING = False

if TYPE_CHECKING:
    from ._core import *
    from ._ideltas import *
    from ._shared import *
    from ._typing import *
    from ._utils import *

del TYPE_CHECKING
