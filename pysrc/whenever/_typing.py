from __future__ import annotations

from typing import Literal

__all__ = [
    "RoundModeStr",
    "DeltaUnitStr",
    "DateDeltaUnitStr",
    "ExactDeltaUnitStr",
    "DisambiguateStr",
]


# TODO make py3.12< compatible
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
