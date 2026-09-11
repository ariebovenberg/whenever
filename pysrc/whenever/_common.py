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
from functools import lru_cache, wraps
from math import isfinite as _isfinite
from operator import index as _index
from typing import TYPE_CHECKING, Any, TypeVar, no_type_check
from warnings import warn

from ._typing import TimestampUnitStr

UTC = _timezone.utc
DUMMY_LEAP_YEAR = 4
Nanos = int  # 0-999_999_999

# unit -> (nanoseconds per unit, units per second)
_TIMESTAMP_UNITS: dict[TimestampUnitStr, tuple[int, int]] = {
    "second": (1_000_000_000, 1),
    "millisecond": (1_000_000, 1_000),
    "microsecond": (1_000, 1_000_000),
    "nanosecond": (1, 1_000_000_000),
}

WARNING_HANDLING_DOCS_MSG = (
    "For project-wide warning configuration, see "
    "https://whenever.readthedocs.io/en/latest/guide/warnings.html"
)

OFFSET_DATETIME_DOCS_MSG = (
    "For comprehensive OffsetDateTime guidance, see "
    "https://whenever.readthedocs.io/en/latest/guide/choosing-a-type.html"
    "#offset-datetime-guidance for details and examples."
)

OFFSET_SHIFT_STALE_MSG = (
    "An OffsetDateTime's offset is usually an observation, not a time zone rule. "
    "The arithmetic is mathematically valid and preserves that fixed offset, "
    "but OffsetDateTime does not retain regional time zone rules. The result's "
    "offset may therefore be stale relative to the source time zone, even after "
    "an exact shift. If the originating time zone is known, convert to "
    "ZonedDateTime first using .assume_tz(). If fixed-offset arithmetic is "
    "intentional or the risk is accepted, pass `stale_offset_ok=True`. For "
    "an entirely fixed-offset domain, configure StaleOffsetWarning globally. "
    + OFFSET_DATETIME_DOCS_MSG
    + " "
    + WARNING_HANDLING_DOCS_MSG
)

PLAIN_SHIFT_UNAWARE_MSG = (
    "Shifting a PlainDateTime by exact time units does not account for time zone transitions "
    "that may occur in the interval "
    "(e.g. adding 2 hours to 2023-03-26 01:30 in Amsterdam crosses the spring-forward "
    "transition, so only 1 real hour has passed). "
    "Use .assume_tz('<tz>') + delta if you know the time zone. "
    "If time zone transitions are intentionally irrelevant here, pass "
    "`naive_arithmetic_ok=True`. " + WARNING_HANDLING_DOCS_MSG
)

DAYS_NOT_ALWAYS_24H_MSG = (
    "You are using days or weeks as exact time, so Whenever will treat each day "
    "as exactly 24 hours. A calendar day can be 23 or 25 hours during a DST "
    "transition, so this may differ from calendar arithmetic. If you mean "
    "calendar days, perform the operation on a ZonedDateTime or pass "
    "`relative_to=...` where supported. If fixed 24-hour periods are "
    "intentional, pass `days_assumed_24h_ok=True`. "
    + WARNING_HANDLING_DOCS_MSG
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


def round_offset_to_minute(offset: int, /) -> int:
    sign = 1 if offset >= 0 else -1
    return sign * ((abs(offset) + 30) // 60 * 60)


def check_utc_bounds(dt: _datetime) -> _datetime:
    try:
        dt.astimezone(UTC)
    except (OverflowError, ValueError):
        raise ValueError(RANGE_MSG) from None
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
    """Emitted when a deprecated feature of the ``whenever`` library is used.

    This is a custom warning class (not a subclass of
    :class:`DeprecationWarning`) so that deprecation warnings from this
    library are visible by default—unlike standard ``DeprecationWarning``,
    which Python silences in application code.
    """


# Stdlib subclasses known to carry more than the stdlib fields, keyed on the
# top-level package. A subclass that adds nothing (freezegun) passes silently.
_LOSSY_STDLIB_SUBCLASSES = frozenset(
    [("pandas", _datetime), ("pandas", _timedelta), ("pendulum", _timedelta)]
)


def warn_lossy_stdlib_subclass(
    obj: Any, base: type, /, *, stacklevel: int
) -> None:
    cls = type(obj)
    if cls is base:
        return
    package = cls.__module__.partition(".")[0]
    if (package, base) in _LOSSY_STDLIB_SUBCLASSES:
        warn(
            f"{package}.{cls.__qualname__} contains data that cannot be "
            f"reliably read through the datetime.{base.__name__} fields; "
            "convert it explicitly",
            WheneverWarning,
            stacklevel=stacklevel + 1,
        )


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


# The message templates of docs/reference/exceptions.rst. One template per
# condition, identical on both backends; tests/test_rejections.py pins them.
RANGE_MSG = "value or calculation out of range"
INCREMENT_MSG = (
    "invalid increment: must be positive and divide a 24-hour day evenly"
)


def invalid(name: str, value: Any, /) -> ValueError:
    """A parameter with a fixed set of values got something else."""
    return ValueError(f"invalid {name}: {value!r}")


def check_nanos(nanosecond: Any, /) -> int:
    try:
        nanos: int = _index(nanosecond)
    except TypeError:
        raise TypeError("nanosecond must be an integer") from None
    if not 0 <= nanos < 1_000_000_000:
        raise ValueError("invalid time")
    return nanos


def tzid_display(tzid: str | None, /) -> str:
    """How messages name a time zone."""
    if tzid is None:
        return "the system time zone (with unknown ID)"
    return f"time zone '{tzid}'"


def format_offset_secs(secs: int, /) -> str:
    """``+05:00``, with seconds only when nonzero."""
    sign = "-" if secs < 0 else "+"
    hours, rem = divmod(abs(secs), 3_600)
    minutes, seconds = divmod(rem, 60)
    return f"{sign}{hours:02d}:{minutes:02d}" + (
        f":{seconds:02d}" if seconds else ""
    )


def split_timestamp(
    value: int | float,
    unit: Any,
    /,
) -> tuple[int, int]:
    try:
        nanoseconds_per_unit, units_per_second = _TIMESTAMP_UNITS[unit]
    except (KeyError, TypeError):
        raise invalid("unit", unit) from None

    if unit == "second":
        if not isinstance(value, (int, float)):
            raise TypeError("timestamp must be an integer or float")
        if isinstance(value, float) and not _isfinite(value):
            raise ValueError(RANGE_MSG)
        seconds, fraction = divmod(value, 1)
        seconds, nanos = int(seconds), int(fraction * 1_000_000_000)
    else:
        if not isinstance(value, int):
            raise TypeError(f"timestamp in {unit}s must be an integer")
        seconds, remainder = divmod(value, units_per_second)
        nanos = remainder * nanoseconds_per_unit
    # Check the instant range here, before any time zone arithmetic can
    # overflow on a value far outside it.
    if not _MIN_TIMESTAMP <= seconds <= _MAX_TIMESTAMP:
        raise ValueError(RANGE_MSG)
    return seconds, nanos


# Instant.MIN and Instant.MAX in seconds since the epoch
_MIN_TIMESTAMP = -62_135_596_800
_MAX_TIMESTAMP = 253_402_300_799


def timestamp_from_parts(
    seconds: int,
    nanosecond: int,
    unit: Any,
    /,
) -> int:
    try:
        nanoseconds_per_unit, units_per_second = _TIMESTAMP_UNITS[unit]
    except (KeyError, TypeError):
        raise invalid("unit", unit) from None
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

        def init_subclass_not_allowed(subcls, **kwargs):
            raise TypeError(
                f"type '{cls.__module__}.{cls.__qualname__}' "
                "is not an acceptable base type"
            )

        cls.__init_subclass__ = classmethod(init_subclass_not_allowed)
        return cls


_Tcall = TypeVar("_Tcall", bound=Callable[..., None])


# I'd love for this to be a decorator, but every attempt I made resulted
# in mypy getting too confused. I've tried a lot.
def add_alternate_constructors(
    init_default: _Tcall,
    py_type: type | None,
) -> _Tcall:
    """Add alternate constructors to a class's __init__ method."""
    accepted = "an ISO 8601 string" + (
        "" if py_type is None else f" or datetime.{py_type.__name__}"
    )

    @wraps(init_default)
    def __init__(self: Any, *args: Any, **kwargs: Any) -> None:
        match args:
            case [str() as iso_string]:
                self._init_from_iso(iso_string, **kwargs)
            case [obj] if py_type is not None and isinstance(obj, py_type):
                self._init_from_py(obj, **kwargs)
            case [obj] if not isinstance(obj, int):
                raise TypeError(f"{type(self).__name__}() requires {accepted}")
            case _:
                init_default(self, *args, **kwargs)

    return __init__  # type: ignore[return-value]
