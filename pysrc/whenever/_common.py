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

from ._typing import TimestampUnitStr

UTC = _timezone.utc
DUMMY_LEAP_YEAR = 4
Nanos = int  # 0-999_999_999

_NANOSECONDS_PER_TIMESTAMP_UNIT: dict[TimestampUnitStr, int] = {
    "second": 1_000_000_000,
    "millisecond": 1_000_000,
    "microsecond": 1_000,
    "nanosecond": 1,
}

WARNING_HANDLING_DOCS_MSG = (
    "For project-wide warning configuration, see "
    "https://whenever.readthedocs.io/en/latest/guide/warnings.html"
)

OFFSET_SHIFT_STALE_MSG = (
    "Shifting an OffsetDateTime keeps its fixed UTC offset. If the operation "
    "crosses a DST or other timezone transition, that offset may become stale—"
    "no longer matching the region's actual offset "
    "(e.g. adding 1 day to 2024-03-09 12:00-07:00 gives 2024-03-10 12:00-07:00, "
    "but if this offset represents Denver, Colorado (America/Denver), "
    "the actual offset changed to -06:00 on that date). "
    "Convert to ZonedDateTime first (using .assume_tz()) for timezone-aware arithmetic. "
    "If the fixed offset is intentional, pass `stale_offset_ok=True`. "
    + WARNING_HANDLING_DOCS_MSG
)

PLAIN_SHIFT_UNAWARE_MSG = (
    "Shifting a PlainDateTime by exact time units does not account for timezone transitions "
    "that may occur in the interval "
    "(e.g. adding 2 hours to 2023-03-26 01:30 in Amsterdam crosses the spring-forward "
    "transition, so only 1 real hour has passed). "
    "Use .assume_tz('<tz>') + delta if you know the timezone. "
    "If timezone transitions are intentionally irrelevant here, pass "
    "`naive_arithmetic_ok=True`. " + WARNING_HANDLING_DOCS_MSG
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


class _SystemTZ:
    __slots__ = ()
    __module__ = "whenever"

    def __repr__(self) -> str:
        return "SYSTEM_TZ"

    def __copy__(self) -> _SystemTZ:
        return self

    def __deepcopy__(self, memo: object, /) -> _SystemTZ:
        return self

    def __reduce__(self) -> str:
        return "SYSTEM_TZ"


SYSTEM_TZ = _SystemTZ()


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


def warn_deprecated(message: str, /, *, stacklevel: int) -> None:
    warn(
        message,
        WheneverDeprecationWarning,
        stacklevel=stacklevel + 1,
    )


def normalize_renamed_keyword(
    new_value: Any,
    kwargs: dict[str, Any],
    /,
    *,
    function_name: str,
    new_name: str,
    old_name: str,
    warning_stacklevel: int,
) -> Any:
    old_value = kwargs.pop(old_name, UNSET)
    if old_value is UNSET:
        return new_value
    if new_value is not UNSET:
        raise TypeError(
            f"{function_name}() received both '{new_name}' "
            f"and deprecated '{old_name}'"
        )
    warn_deprecated(
        f"'{old_name}' is deprecated; use '{new_name}' instead",
        stacklevel=warning_stacklevel,
    )
    return old_value


def check_no_kwargs(
    kwargs: dict[str, Any],
    function_name: str,
    /,
) -> None:
    if kwargs:
        raise TypeError(
            f"{function_name}() got an unexpected keyword argument "
            f"{next(iter(kwargs))!r}"
        )


def split_timestamp(
    value: int | float,
    unit: Any,
    /,
) -> tuple[int, int]:
    try:
        nanoseconds_per_unit = _NANOSECONDS_PER_TIMESTAMP_UNIT[unit]
    except (KeyError, TypeError):
        raise ValueError(f"invalid timestamp unit: {unit!r}") from None

    if unit == "second":
        if not isinstance(value, (int, float)):
            raise TypeError("timestamp must be an integer or float")
        seconds, fraction = divmod(value, 1)
        return int(seconds), int(fraction * 1_000_000_000)

    if not isinstance(value, int):
        raise TypeError(f"timestamp in {unit}s must be an integer")
    units_per_second = 1_000_000_000 // nanoseconds_per_unit
    seconds, remainder = divmod(value, units_per_second)
    return seconds, remainder * nanoseconds_per_unit


def timestamp_from_parts(
    seconds: int,
    nanosecond: int,
    unit: Any,
    /,
) -> int:
    try:
        nanoseconds_per_unit = _NANOSECONDS_PER_TIMESTAMP_UNIT[unit]
    except (KeyError, TypeError):
        raise ValueError(f"invalid timestamp unit: {unit!r}") from None
    units_per_second = 1_000_000_000 // nanoseconds_per_unit
    return seconds * units_per_second + nanosecond // nanoseconds_per_unit


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
) -> _Tcall:
    """Add alternate constructors to a class's __init__ method."""

    def __init__(self: Any, *args: Any, **kwargs: Any) -> None:
        match args:
            case [str() as iso_string]:
                self._init_from_iso(iso_string, **kwargs)
            case [obj] if (
                py_type is not None and not kwargs and isinstance(obj, py_type)
            ):
                self._init_from_py(obj)
            case _:
                init_default(self, *args, **kwargs)

    return __init__  # type: ignore[return-value]
