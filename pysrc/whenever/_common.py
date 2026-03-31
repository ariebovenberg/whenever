from __future__ import annotations

from collections.abc import Callable
from datetime import (
    datetime as _datetime,
    timedelta as _timedelta,
    timezone as _timezone,
)
from functools import lru_cache
from typing import TYPE_CHECKING, Any, TypeVar, no_type_check
from warnings import warn

UTC = _timezone.utc
DUMMY_LEAP_YEAR = 4
Nanos = int  # 0-999_999_999

# A self-set variable to detect if we're being run by sphinx autodoc
try:
    from sphinx import (  # type: ignore[attr-defined, import-not-found, unused-ignore]
        SPHINX_RUNNING as SPHINX_RUNNING,
    )
except ImportError:
    SPHINX_RUNNING = False


# We cache fixed-offset tzinfo objects to avoid creating multiple identical ones.
# It's very common to only have whole-hour offsets, so this helps a lot.
@lru_cache
def mk_fixed_tzinfo(secs: int, /) -> _timezone:
    return _timezone(_timedelta(seconds=secs))


def check_utc_bounds(dt: _datetime) -> _datetime:
    try:
        dt.astimezone(UTC)
    except (OverflowError, ValueError):
        raise ValueError("Instant out of range")
    return dt


# A custom warnings class to prevent silent deprecation warnings in user code.
# See https://sethmlarson.dev/deprecations-via-warnings-dont-work-for-python-libraries
class WheneverDeprecationWarning(UserWarning):
    """Raised when a deprecated feature of the ``whenever`` library is used.

    This is a custom warning class (not a subclass of
    :class:`DeprecationWarning`) so that deprecation warnings from this
    library are visible by default—unlike standard ``DeprecationWarning``,
    which Python silences in production code.
    """


_T = TypeVar("_T")


# Basic behavior common to all classes
class _Base:
    __slots__ = ()

    # Immutable classes don't need to be copied
    @no_type_check
    def __copy__(self):
        return self

    @no_type_check
    def __deepcopy__(self, _):
        return self

    @no_type_check
    @classmethod
    def __get_pydantic_core_schema__(cls, *_, **kwargs):
        from ._utils import pydantic_schema

        return pydantic_schema(cls)

    @classmethod
    def parse_iso(cls: type[_T], s: str, /) -> _T:
        raise NotImplementedError  # pragma: no cover


if TYPE_CHECKING:
    from typing import final as final  # re-export to suppress linting errors
else:

    def final(cls):

        def init_subclass_not_allowed(cls, **kwargs):  # pragma: no cover
            raise TypeError("Subclassing not allowed")

        cls.__init_subclass__ = init_subclass_not_allowed
        return cls


_Tcall = TypeVar("_Tcall", bound=Callable[..., None])


# I'd love for this to be a decorator, but every attempt I made resulted
# in mypy getting too confused. I've tried a lot.
def add_alternate_constructors(
    init_default: _Tcall,
    py_type: type | None = None,
    deprecation_msg: str | None = None,
) -> _Tcall:
    """Add alternate constructors to a class's __init__ method."""

    def __init__(self: Any, *args: Any, **kwargs: Any) -> None:
        match args:
            case [str() as iso_string] if not kwargs:
                if deprecation_msg:
                    warn(
                        deprecation_msg,
                        WheneverDeprecationWarning,
                        stacklevel=2,
                    )
                self._init_from_iso(iso_string)
            case [obj] if (
                py_type is not None and not kwargs and isinstance(obj, py_type)
            ):
                self._init_from_py(obj)
            case _:
                init_default(self, *args, **kwargs)

    return __init__  # type: ignore[return-value]
