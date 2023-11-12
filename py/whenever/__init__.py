from abc import ABC
from typing import Generic, TypeVar

from ._whenever import _common, utc

__all__ = ["utc", "Option", "Some", "Nothing"]

T = TypeVar("T")


class Option(Generic[T], ABC):
    pass


Some = _common.Some
Nothing = _common.Nothing
Option.register(Some)
Option.register(Nothing)
