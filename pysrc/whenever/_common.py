from __future__ import annotations

from collections.abc import Callable

# Unused imports are necessary for sphinx autodoc due to
# scoping issues introduced by add_alternate_constructors().
from datetime import (  # noqa: F401
    date as _date,
    datetime as _datetime,
    time as _time,  # noqa: F401
    timedelta as _timedelta,
    timezone as _timezone,
)
from functools import lru_cache
from typing import TYPE_CHECKING, Any, TypeVar, no_type_check
from warnings import warn

UTC = _timezone.utc
DUMMY_LEAP_YEAR = 4
Nanos = int  # 0-999_999_999

OFFSET_SHIFT_STALE_MSG = (
    "Shifting an OffsetDateTime keeps the fixed UTC offset, which may not match the "
    "actual offset after a DST or other timezone transition "
    "(e.g. adding 1 day to 2024-03-09 12:00-07:00 gives 2024-03-10 12:00-07:00, "
    "but if this offset represents Denver, Colorado (America/Denver), "
    "the actual offset changed to -06:00 on that date). "
    "Convert to ZonedDateTime first (using .assume_tz()) for timezone-aware arithmetic. "
    "Pass `stale_offset_ok=True` to suppress this warning, "
    "or use Python's standard warning filters. "
    "See https://whenever.readthedocs.io/en/latest/guide/warnings.html"
)

PLAIN_SHIFT_UNAWARE_MSG = (
    "Shifting a PlainDateTime by exact time units does not account for timezone transitions "
    "that may occur in the interval "
    "(e.g. adding 2 hours to 2023-03-26 01:30 in Amsterdam crosses the spring-forward "
    "transition, so only 1 real hour has passed). "
    "Use .assume_tz('<tz>') + delta if you know the timezone. "
    "Pass `naive_arithmetic_ok=True` to suppress this warning, "
    "or use Python's standard warning filters. "
    "See https://whenever.readthedocs.io/en/latest/guide/warnings.html"
)

# A self-set variable to detect if we're being run by sphinx autodoc
try:
    from sphinx import (  # type: ignore[attr-defined, import-not-found, unused-ignore]
        SPHINX_RUNNING as SPHINX_RUNNING,
    )
except ImportError:
    SPHINX_RUNNING = False

# A sentinel value that looks nice in autodoc.
# Used in cases where `None` would be a valid value, or where we want to
# avoid allowing `None` to be passed in by users.
UNSET: Any = type(
    "UNSET", (), {"__repr__": lambda _: "...", "__bool__": lambda _: False}
)()


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


class WheneverWarning(UserWarning):
    """Base class for all warnings emitted by the ``whenever`` library.

    This can be used with Python's standard warning filters to suppress or
    escalate all warnings emitted by ``whenever``:

    .. code-block:: python

        import warnings, whenever
        warnings.filterwarnings("error", category=whenever.WheneverWarning)
    """


# A custom warnings class to prevent silent deprecation warnings in user code.
# See https://sethmlarson.dev/deprecations-via-warnings-dont-work-for-python-libraries
class WheneverDeprecationWarning(WheneverWarning):
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
