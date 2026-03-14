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

# we override the above type aliases with proper type aliases in Python 3.12
try:
    from ._typing_312 import *  # noqa
except ImportError:  # pragma: no cover
    pass
