from __future__ import annotations

from typing import Literal, TypeAlias

__all__ = [
    "RoundModeStr",
    "DeltaUnitStr",
    "DateDeltaUnitStr",
    "ExactDeltaUnitStr",
    "DisambiguateStr",
    "OffsetMismatchStr",
]

RoundModeStr: TypeAlias = Literal[
    "ceil",
    "expand",
    "floor",
    "trunc",
    "half_ceil",
    "half_expand",
    "half_floor",
    "half_trunc",
    "half_even",
]
DeltaUnitStr: TypeAlias = Literal[
    "years",
    "months",
    "weeks",
    "days",
    "hours",
    "minutes",
    "seconds",
    "nanoseconds",
]
DateDeltaUnitStr: TypeAlias = Literal["years", "months", "weeks", "days"]
ExactDeltaUnitStr: TypeAlias = Literal[
    "weeks", "days", "hours", "minutes", "seconds", "nanoseconds"
]
DisambiguateStr: TypeAlias = Literal["compatible", "earlier", "later", "raise"]
OffsetMismatchStr: TypeAlias = Literal["raise", "keep_instant", "keep_local"]

try:
    from ._typing_312 import *
except ImportError:
    pass
