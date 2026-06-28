class Unambiguous:
    __match_args__ = ("offset",)
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
    __match_args__ = ("end", "before", "after")
    end: int
    before: int
    after: int

    def __init__(self, end: int, before: int, after: int):
        self.end = end
        self.before = before
        self.after = after

    def __eq__(self, other: object) -> bool:
        if isinstance(other, Gap):
            return (
                self.end == other.end
                and self.before == other.before
                and self.after == other.after
            )
        return False  # pragma: no cover

    def __repr__(self) -> str:
        return f"Gap({self.end}, {self.before}, {self.after})"


class Fold:
    __match_args__ = ("end", "before", "after")
    end: int
    before: int
    after: int

    def __init__(self, end: int, before: int, after: int):
        self.end = end
        self.before = before
        self.after = after

    def __eq__(self, other: object) -> bool:
        if isinstance(other, Fold):
            return (
                self.end == other.end
                and self.before == other.before
                and self.after == other.after
            )
        return False  # pragma: no cover

    def __repr__(self) -> str:
        return f"Fold({self.end}, {self.before}, {self.after})"


Ambiguity = Unambiguous | Gap | Fold
