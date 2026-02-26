"""This module contains Python 3.12+ type aliases,
which raise SyntaxError if imported in earlier versions."""
from typing import Literal

type RoundModeStr = Literal[
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
type DeltaUnitStr = Literal[
    "years",
    "months",
    "weeks",
    "days",
    "hours",
    "minutes",
    "seconds",
    "nanoseconds",
]
type DateDeltaUnitStr = Literal["years", "months", "weeks", "days"]
type ExactDeltaUnitStr = Literal[
    "weeks", "days", "hours", "minutes", "seconds", "nanoseconds"
]
type DisambiguateStr = Literal["compatible", "earlier", "later", "raise"]
type OffsetMismatchStr = Literal["raise", "keep_instant", "keep_local"]
