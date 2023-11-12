from typing import Generic, TypeVar

T = TypeVar("T")

class Option(Generic[T]):
    def unwrap(self) -> T: ...

class Some(Option[T]):
    __match_args__ = ("value",)
    value: T
    def __init__(self, value: T, /): ...

class Nothing(Option[T]):
    pass
