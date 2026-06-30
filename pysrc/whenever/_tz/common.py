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
    # In a gap, the later_offset is numerically the offset after the jump and
    # the earlier_offset is the offset before it.
    __match_args__ = ("end", "later_offset", "earlier_offset")
    end: int
    later_offset: int
    earlier_offset: int

    def __init__(self, end: int, later_offset: int, earlier_offset: int):
        self.end = end
        self.later_offset = later_offset
        self.earlier_offset = earlier_offset

    def __eq__(self, other: object) -> bool:
        if isinstance(other, Gap):
            return (
                self.end == other.end
                and self.later_offset == other.later_offset
                and self.earlier_offset == other.earlier_offset
            )
        return False  # pragma: no cover

    def __repr__(self) -> str:
        return (
            f"Gap(end={self.end}, later_offset={self.later_offset}, "
            f"earlier_offset={self.earlier_offset})"
        )


class Fold:
    # In a fold, the earlier_offset is the offset before the clock goes back
    # and the later_offset is the offset after it.
    __match_args__ = ("end", "earlier_offset", "later_offset")
    end: int
    earlier_offset: int
    later_offset: int

    def __init__(self, end: int, earlier_offset: int, later_offset: int):
        self.end = end
        self.earlier_offset = earlier_offset
        self.later_offset = later_offset

    def __eq__(self, other: object) -> bool:
        if isinstance(other, Fold):
            return (
                self.end == other.end
                and self.earlier_offset == other.earlier_offset
                and self.later_offset == other.later_offset
            )
        return False  # pragma: no cover

    def __repr__(self) -> str:
        return (
            f"Fold(end={self.end}, earlier_offset={self.earlier_offset}, "
            f"later_offset={self.later_offset})"
        )


Ambiguity = Unambiguous | Gap | Fold
