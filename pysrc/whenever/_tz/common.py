from typing import Literal, Union

Disambiguate = Literal["compatible", "earlier", "later", "raise"]


class Unambiguous:
    offset: int

    def __init__(self, offset: int):
        self.offset = offset

    def __eq__(self, other: object) -> bool:
        if isinstance(other, Unambiguous):
            return self.offset == other.offset
        return False  # pragma: no cover

    def __repr__(self) -> str:
        return f"Unambiguous({self.offset})"


class Gap:
    before: int
    after: int

    def __init__(self, before: int, after: int):
        self.before = before
        self.after = after

    def __eq__(self, other: object) -> bool:
        if isinstance(other, Gap):
            return self.before == other.before and self.after == other.after
        return False  # pragma: no cover

    def __repr__(self) -> str:
        return f"Gap({self.before}, {self.after})"


class Fold:
    before: int
    after: int

    def __init__(self, before: int, after: int):
        self.before = before
        self.after = after

    def __eq__(self, other: object) -> bool:
        if isinstance(other, Fold):
            return self.before == other.before and self.after == other.after
        return False  # pragma: no cover

    def __repr__(self) -> str:
        return f"Fold({self.before}, {self.after})"


Ambiguity = Union[Unambiguous, Gap, Fold]
