"""The main pure-Python implementation of the whenever library."""

# Maintainer's notes:
#
# - Why is most stuff in one file?
#   - Flat is better than nested
#   - It prevents circular imports since the classes 'know' about each other
# - There is some code duplication in this file. This is intentional:
#   - It makes it easier to understand the code
#   - It's sometimes necessary for the type checker
#   - It saves some overhead
from __future__ import annotations

import enum
from abc import ABC, abstractmethod
from collections.abc import (
    Callable,
    ItemsView,
    KeysView,
    Mapping,
    ValuesView,
)
from contextvars import ContextVar
from datetime import (
    date as _date,
    datetime as _datetime,
    time as _time,
    timedelta as _timedelta,
    timezone as _timezone,
)
from math import fmod
from struct import pack, unpack
from time import time_ns
from typing import (
    TYPE_CHECKING,
    Any,
    ClassVar,
    Iterator,
    Literal,
    Optional,
    Sequence,
    TypeVar,
    Union,
    cast,
    no_type_check,
    overload,
)
from warnings import warn

from ._common import check_utc_bounds, mk_fixed_tzinfo
from ._math import (
    DATE_DELTA_UNITS,
    DELTA_UNITS,
    DIFF_FUNCS,
    EXACT_UNITS,
    NS_PER_UNIT_PLURAL,
    Sign,
    custom_round,
    date_diff,
    days_in_month,
    increment_to_ns_for_datetime,
    increment_to_ns_for_delta,
    resolve_leap_day,
)
from ._parse import (
    MONTH_TO_RFC2822,
    WEEKDAY_TO_RFC2822,
    InvalidOffsetError,
    date_from_iso,
    datetime_from_iso,
    monthday_from_iso,
    offset_dt_from_iso,
    parse_rfc2822,
    parse_timedelta_component,
    time_from_iso,
    yearmonth_from_iso,
    zdt_from_iso,
)
from ._typing import (
    DateDeltaUnitStr,
    DeltaUnitStr,
    DisambiguateStr,
    ExactDeltaUnitStr,
    OffsetMismatchStr,
    RoundModeStr,
)
from ._tz import (  # noqa: F401
    RepeatedTime,
    SkippedTime,
    TimeZone,
    TimeZoneNotFoundError,
    Unambiguous,
    _clear_tz_cache as _clear_tz_cache,
    _clear_tz_cache_by_keys as _clear_tz_cache_by_keys,
    _set_tzpath as _set_tzpath,
    get_system_tz,
    get_tz,
    reset_system_tz,
    resolve_ambiguity,
    resolve_ambiguity_using_prev_offset,
)

__all__ = [
    # Date and time
    "Date",
    "YearMonth",
    "MonthDay",
    "Time",
    "Instant",
    "OffsetDateTime",
    "ZonedDateTime",
    "PlainDateTime",
    # Deltas and time units
    "DateDelta",
    "TimeDelta",
    "DateTimeDelta",
    "ItemizedDelta",
    "ItemizedDateDelta",
    "years",
    "months",
    "weeks",
    "days",
    "hours",
    "minutes",
    "seconds",
    "milliseconds",
    "microseconds",
    "nanoseconds",
    # Exceptions/warnings
    "DaysNotAlways24HoursWarning",
    "PotentiallyStaleOffsetWarning",
    "TimeZoneUnawareArithmeticWarning",
    "PotentialDstBugWarning",
    "WheneverDeprecationWarning",
    "SkippedTime",
    "RepeatedTime",
    "InvalidOffsetError",
    "ImplicitlyIgnoringDST",
    "TimeZoneNotFoundError",
    # Other stuff
    "Weekday",
    "reset_system_tz",
]


# A self-set variable to detect if we're being run by sphinx autodoc
try:
    from sphinx import (  # type: ignore[attr-defined, import-not-found, unused-ignore]
        SPHINX_RUNNING,
    )
except ImportError:
    SPHINX_RUNNING = False


class Weekday(enum.Enum):
    """Day of the week; ``.value`` corresponds with ISO numbering
    (monday=1, sunday=7).

    All members are also available as constants in the module namespace:

    >>> from whenever import Weekday, MONDAY, SUNDAY
    >>> MONDAY is Weekday.MONDAY
    True

    :class:`~whenever.Date` and other date-carrying types return
    ``Weekday`` from their :meth:`~whenever.Date.day_of_week` method:

    >>> Date(2024, 12, 25).day_of_week()
    Weekday.WEDNESDAY
    """

    MONDAY = 1
    TUESDAY = 2
    WEDNESDAY = 3
    THURSDAY = 4
    FRIDAY = 5
    SATURDAY = 6
    SUNDAY = 7


# Helpers that pre-compute/lookup as much as possible
_UTC = _timezone.utc
_object_new = object.__new__
_MAX_DELTA_YEARS = 9999
_MAX_DELTA_MONTHS = 9999 * 12
_MAX_DELTA_WEEKS = 9999 * 53
_MAX_DELTA_DAYS = 9999 * 366
_MAX_DELTA_HOURS = _MAX_DELTA_DAYS * 24
_MAX_DELTA_MINUTES = _MAX_DELTA_HOURS * 60
_MAX_DELTA_SECONDS = _MAX_DELTA_MINUTES * 60
_MAX_DELTA_NANOS = _MAX_DELTA_SECONDS * 1_000_000_000
_MAX_SUBSEC_NANOS = 999_999_999
_Nanos = int  # type alias for subsecond nanoseconds
_T = TypeVar("_T")
# A sentinel value that looks nice in autodoc.
# Used in cases where `None` would be a valid value, or where we want to
# avoid allowing `None` to be passed in by users.
_UNSET: Any = type(
    "UNSET", (), {"__repr__": lambda _: "...", "__bool__": lambda _: False}
)()


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
    @abstractmethod
    def parse_iso(cls: type[_T], s: str, /) -> _T: ...  # pragma: no cover


if TYPE_CHECKING:
    from typing import final
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
    init_default: _Tcall, py_type: type | None = None
) -> _Tcall:
    """Add alternate constructors to a class's __init__ method."""

    def __init__(self: Any, *args: Any, **kwargs: Any) -> None:
        match args:
            case [str() as iso_string] if not kwargs:
                self._init_from_iso(iso_string)
            case [obj] if (
                py_type is not None and not kwargs and isinstance(obj, py_type)
            ):
                self._init_from_py(obj)
            case _:
                init_default(self, *args, **kwargs)

    return __init__  # type: ignore[return-value]


@final
class Date(_Base):
    """A date without a time component.

    >>> d = Date(2021, 1, 2)
    Date("2021-01-02")

    Can also be constructed from an ISO 8601 string
    or a standard library :class:`~datetime.date`:

    >>> Date("2021-01-02")
    Date("2021-01-02")
    >>> Date(date(2021, 1, 2))
    Date("2021-01-02")

    Dates support arithmetic with :class:`~whenever.ItemizedDateDelta`:

    >>> delta = Date("2021-02-28").since(Date("1994-05-15"), units=["years", "days"])
    ItemizedDateDelta("P26y289d")
    >>> Date("1994-05-15").add(delta)
    Date("2021-02-28")

    Dates can be compared and sorted:

    >>> Date(2021, 1, 2) > Date(2021, 1, 1)
    True
    """

    __slots__ = ("_py_date",)

    MIN: ClassVar[Date]
    """The minimum possible date"""
    MAX: ClassVar[Date]
    """The maximum possible date"""

    # Overloads for a nice autodoc.
    # Proper typing of the constructors is handled in the type stubs
    if not TYPE_CHECKING:

        @overload
        def __init__(self, iso_string: str, /) -> None: ...

        @overload
        def __init__(self, py_date: _date, /) -> None: ...

        @overload
        def __init__(self, year: int, month: int, day: int) -> None: ...

    def __init__(self, year: int, month: int, day: int) -> None:
        self._py_date = _date(year, month, day)

    __init__ = add_alternate_constructors(__init__, py_type=_date)

    @classmethod
    def today_in_system_tz(cls) -> Date:
        """Get the current date in the system's local timezone.

        Alias for ``Instant.now().to_system_tz().date()``.

        >>> Date.today_in_system_tz()
        Date("2021-01-02")
        """
        # Use now() so this function gets patched like the other now functions
        return Instant.now().to_system_tz().date()

    @property
    def year(self) -> int:
        """The year component of the date

        >>> Date(2021, 1, 2).year
        2021
        """
        return self._py_date.year

    @property
    def month(self) -> int:
        """The month component of the date

        >>> Date(2021, 1, 2).month
        1
        """
        return self._py_date.month

    @property
    def day(self) -> int:
        """The day component of the date

        >>> Date(2021, 1, 2).day
        2
        """
        return self._py_date.day

    def year_month(self) -> YearMonth:
        """The year and month (without a day component)

        >>> Date(2021, 1, 2).year_month()
        YearMonth("2021-01")
        """
        return YearMonth._from_py_unchecked(self._py_date.replace(day=1))

    def month_day(self) -> MonthDay:
        """The month and day (without a year component)

        >>> Date(2021, 1, 2).month_day()
        MonthDay("--01-02")
        """
        return MonthDay._from_py_unchecked(
            self._py_date.replace(year=_DUMMY_LEAP_YEAR)
        )

    def day_of_week(self) -> Weekday:
        """The day of the week

        >>> Date(2021, 1, 2).day_of_week()
        Weekday.SATURDAY
        >>> Weekday.SATURDAY.value
        6  # the ISO value
        """
        return Weekday(self._py_date.isoweekday())

    def at(self, t: Time, /) -> PlainDateTime:
        """Combine a date with a time to create a datetime

        >>> d = Date(2021, 1, 2)
        >>> d.at(Time(12, 30))
        PlainDateTime("2021-01-02 12:30:00")

        You can use methods like :meth:`~PlainDateTime.assume_utc`
        or :meth:`~PlainDateTime.assume_tz` to find the corresponding exact time.

        >>> d.at(Time(12, 30)).assume_tz("America/New_York")
        ZonedDateTime("2021-01-02 12:30:00-05:00[America/New_York]")
        """
        return PlainDateTime._from_py_unchecked(
            _datetime.combine(self._py_date, t._py), t._nanos
        )

    def py_date(self) -> _date:
        """Convert to a standard library :class:`~datetime.date`"""
        return self._py_date

    @classmethod
    def from_py_date(cls, d: _date, /) -> Date:
        """Create from a :class:`~datetime.date`

        >>> Date.from_py_date(date(2021, 1, 2))
        Date("2021-01-02")
        """
        self = _object_new(cls)
        self._init_from_py(d)
        return self

    def _init_from_py(self, d: _date) -> None:
        if type(d) is _date:
            pass
        elif type(d) is _datetime:
            d = d.date()
        elif isinstance(d, _date):
            # the only subclass-safe way to ensure we have exactly a datetime.date
            d = _date(d.year, d.month, d.day)
        else:
            raise TypeError(f"Expected date, got {type(d)!r}")
        self._py_date = d

    def format_iso(self, *, basic: bool = False) -> str:
        """Format as the ISO 8601 date format.

        Inverse of :meth:`parse_iso`.

        >>> Date(2021, 1, 2).format_iso()
        '2021-01-02'
        >>> Date(1992, 9, 4).format_iso(basic=True)
        '19920904'
        """
        return _format_date(self._py_date, basic)

    @classmethod
    def parse_iso(cls, s: str, /) -> Date:
        """Parse a date from an ISO8601 string

        The following formats are accepted:
        - ``YYYY-MM-DD`` ("extended" format)
        - ``YYYYMMDD`` ("basic" format)

        Inverse of :meth:`format_iso`

        >>> Date.parse_iso("2021-01-02")
        Date("2021-01-02")
        """
        return cls._from_py_unchecked(date_from_iso(s))

    def _init_from_iso(self, s: str) -> None:
        self._py_date = date_from_iso(s)

    if not TYPE_CHECKING:  # for a nice autodoc

        @overload
        def replace(
            self, year: int = ..., month: int = ..., day: int = ...
        ) -> Date: ...

    def replace(self, **kwargs: Any) -> Date:
        """Create a new instance with the given fields replaced

        >>> d = Date(2021, 1, 2)
        >>> d.replace(day=4)
        Date("2021-01-04")
        """
        return Date._from_py_unchecked(self._py_date.replace(**kwargs))

    @overload
    def add(self, delta: ItemizedDateDelta | DateDelta, /) -> Date: ...

    @overload
    def add(
        self,
        *,
        years: int = ...,
        months: int = ...,
        weeks: int = ...,
        days: int = ...,
    ) -> Date: ...

    @no_type_check
    def add(self, *args, **kwargs) -> Date:
        """Add a components to a date.

        See :ref:`the docs on arithmetic <arithmetic>` for more information.

        >>> d = Date(2021, 1, 2)
        >>> d.add(years=1, months=2, days=3)
        Date("2022-03-05")
        >>> Date(2020, 2, 29).add(years=1)
        Date("2021-02-28")
        """
        return self._shift(1, *args, **kwargs)

    @overload
    def subtract(self, delta: ItemizedDateDelta | DateDelta, /) -> Date: ...

    @overload
    def subtract(
        self,
        *,
        years: int = ...,
        months: int = ...,
        weeks: int = ...,
        days: int = ...,
    ) -> Date: ...

    @no_type_check
    def subtract(self, *args, **kwargs) -> Date:
        """Subtract components from a date.

        See :ref:`the docs on arithmetic <arithmetic>` for more information.

        >>> d = Date(2021, 1, 2)
        >>> d.subtract(years=1, months=2, days=3)
        Date("2019-10-30")
        >>> Date(2021, 3, 1).subtract(years=1)
        Date("2020-03-01")
        """
        return self._shift(-1, *args, **kwargs)

    @no_type_check
    def _shift(
        self,
        sign: int,
        delta: ItemizedDateDelta | DateDelta = _UNSET,
        /,
        **kwargs,
    ) -> Date:
        if kwargs:
            if delta is not _UNSET:
                raise TypeError(
                    "Cannot combine positional and keyword arguments"
                )
        elif delta is not _UNSET:
            if isinstance(delta, ItemizedDateDelta):
                kwargs = delta
            else:
                assert isinstance(delta, DateDelta)
                kwargs = {"months": delta._months, "days": delta._days}
        else:  # no arguments, just return self
            return self
        return self._shift_kwargs(sign, **kwargs)

    def _shift_kwargs(
        self,
        sign: int,
        years: int = 0,
        months: int = 0,
        weeks: int = 0,
        days: int = 0,
    ) -> Date:
        return Date._from_py_unchecked(
            self._add_months(sign * (years * 12 + months))._py_date
            + _timedelta(weeks * 7 + days) * sign
        )

    def days_since(self, other: Date, /) -> int:
        """Calculate the number of days this day is after another date.

        .. deprecated:: 0.10.0

            Use :meth:`since` with `unit="days"` instead.

        """
        warn(
            "days_since() is deprecated; use since() with unit='days' instead.",
            WheneverDeprecationWarning,
            stacklevel=2,
        )
        return (self._py_date - other._py_date).days

    def days_until(self, other: Date, /) -> int:
        """Calculate the number of days from this date to another date.

        .. deprecated:: 0.10.0

            Use :meth:`until` with `unit="days"` instead.
        """
        warn(
            "days_until() is deprecated; use until() with unit='days' instead.",
            WheneverDeprecationWarning,
            stacklevel=2,
        )
        return (other._py_date - self._py_date).days

    @overload
    def since(
        self,
        b: Date,
        /,
        *,
        unit: DateDeltaUnitStr,
        round_mode: RoundModeStr = "trunc",
        round_increment: int = 1,
    ) -> int: ...

    @overload
    def since(
        self,
        b: Date,
        /,
        *,
        units: Sequence[DateDeltaUnitStr],
        round_mode: RoundModeStr = "trunc",
        round_increment: int = 1,
    ) -> ItemizedDateDelta: ...

    def since(
        self,
        b: Date,
        /,
        *,
        unit: Optional[DateDeltaUnitStr] = None,
        units: Optional[Sequence[DateDeltaUnitStr]] = None,
        round_mode: RoundModeStr = "trunc",
        round_increment: int = 1,
    ) -> Union[ItemizedDateDelta, int]:
        """Calculate the difference between this date and another date.
        The difference is calculated in terms of the chosen calendar unit
        or units.

        Parameters
        ----------
        other
            The date to calculate the difference since.
        unit
            If specified, the difference is calculated in terms of this single
            unit. Cannot be combined with `units`.
        units
            If specified, the difference is calculated in terms of these units,
            in decreasing order of size. Cannot be combined with `unit`.
        round_mode
            The rounding mode to apply to the smallest specified unit.
            Default is "floor".
        round_increment
            The increment to round to for the smallest specified unit.
            Default is 1.

        Returns
        -------
        ItemizedDateDelta | int
            If multiple units are specified, the difference is returned
            as an :class:`ItemizedDateDelta`,
            otherwise as an integer number of the specified unit.

        >>> d1 = Date(2023, 4, 15)
        >>> d2.since(Date("2020-01-01"), units=["years", "months"])
        ItemizedDateDelta(years=3, months=3)

        """
        units, single_unit_mode = _normalize_unit_or_units(
            unit, units, valid_units=DATE_DELTA_UNITS
        )
        smallest_unit = units[-1]
        sign: Literal[1, -1] = 1 if self >= b else -1
        results, trunc, expand = date_diff(
            self._py_date,
            b._py_date,
            round_increment,
            units,
            sign,
        )

        # Round is expensive, so only do it if needed
        if round_mode != "trunc":
            trunc_date = resolve_leap_day(trunc)
            results[smallest_unit] = custom_round(
                results[smallest_unit],
                abs((self._py_date - trunc_date).days),
                abs((resolve_leap_day(expand) - trunc_date).days),
                round_mode,
                round_increment,
                sign,
            )

        if single_unit_mode:
            return results.pop(smallest_unit) * sign
        else:
            # mypy false positive: 'keywords must be strings' (but they're string literals!)
            return ItemizedDateDelta._from_signed(
                sign if any(results.values()) else 0, **results
            )  # type: ignore[misc]

    @overload
    def until(
        self,
        b: Date,
        /,
        *,
        unit: DateDeltaUnitStr,
        round_mode: RoundModeStr = "trunc",
        round_increment: int = 1,
    ) -> int: ...

    @overload
    def until(
        self,
        b: Date,
        /,
        *,
        units: Sequence[DateDeltaUnitStr],
        round_mode: RoundModeStr = "trunc",
        round_increment: int = 1,
    ) -> ItemizedDateDelta: ...

    def until(
        self,
        b: Date,
        /,
        *,
        unit: Optional[DateDeltaUnitStr] = None,
        units: Optional[Sequence[DateDeltaUnitStr]] = None,
        round_mode: RoundModeStr = "trunc",
        round_increment: int = 1,
    ) -> Union[ItemizedDateDelta, int]:
        """Companion to :meth:`since` that calculates the difference until another date.
        See :meth:`since` for more information.
        """
        return b.since(  # type: ignore[call-overload, no-any-return]
            self,
            unit=unit,
            units=units,
            round_mode=round_mode,
            round_increment=round_increment,
        )

    def _add_months(self, mos: int) -> Date:
        year_overflow, month_new = divmod(self.month - 1 + mos, 12)
        month_new += 1
        year_new = self.year + year_overflow
        return Date(
            year_new,
            month_new,
            min(self.day, days_in_month(year_new, month_new)),
        )

    def _add_days(self, days: int) -> Date:
        return Date._from_py_unchecked(self._py_date + _timedelta(days))

    def __add__(self, p: DateDelta) -> Date:
        """Add a delta to a date.
        Behaves the same as :meth:`add`

        .. deprecated:: 0.10.0

            Using the ``+`` operator on :class:`Date` is deprecated;
            use the :meth:`add` method instead.
        """
        warn(
            "Using the + operator on Date is deprecated; "
            "use the .add() method instead.",
            WheneverDeprecationWarning,
            stacklevel=2,
        )
        return (
            self.add(months=p._months, days=p._days)
            if isinstance(p, DateDelta)
            else NotImplemented
        )

    @overload
    def __sub__(self, d: DateDelta) -> Date: ...

    @overload
    def __sub__(self, d: Date) -> DateDelta: ...

    def __sub__(self, d: DateDelta | Date) -> Date | DateDelta:
        """Subtract a delta from a date, or subtract two dates

        Subtracting a delta works the same as :meth:`subtract`.

        >>> Date(2021, 1, 2) - DateDelta(weeks=1, days=3)
        Date("2020-12-26")

        The difference between two dates is calculated in months and days,
        such that:

        >>> delta = d1 - d2
        >>> d2 + delta == d1  # always

        The following is not always true:

        >>> d1 - (d1 - d2) == d2  # not always true!
        >>> -(d2 - d1) == d1 - d2  # not always true!

        >>> Date(2023, 4, 15) - Date(2011, 6, 24)
        DateDelta("P12Y9M22D")
        >>> # Truncation
        >>> Date(2024, 4, 30) - Date(2023, 5, 31)
        DateDelta("P11M")
        >>> Date(2024, 3, 31) - Date(2023, 6, 30)
        DateDelta("P9M1D")
        >>> # the other way around, the result is different
        >>> Date(2023, 6, 30) - Date(2024, 3, 31)
        DateDelta(-P9M)

        .. deprecated:: 0.10.0

            Using the ``-`` operator on :class:`Date` is deprecated;
            use the :meth:`subtract` method or the :meth:`since` method instead.
        """
        if isinstance(d, DateDelta):
            warn(
                "Using the `-` operator on Date is deprecated; "
                "use the .subtract() method instead.",
                WheneverDeprecationWarning,
                stacklevel=2,
            )
            return self.subtract(months=d._months, days=d._days)
        elif isinstance(d, Date):
            warn(
                "Using the `-` operator on Date is deprecated; "
                "use the .since() method with explicit units instead.",
                WheneverDeprecationWarning,
                stacklevel=2,
            )
            mos = self.month - d.month + 12 * (self.year - d.year)
            shifted = d._add_months(mos)

            # yes, it's a bit duplicated, but preferable to being clever.
            if d > self:
                if shifted < self:  # i.e. we've overshot
                    mos += 1
                    shifted = d._add_months(mos)
                    dys = (
                        -shifted.day
                        - days_in_month(self.year, self.month)
                        + self.day
                    )
                else:
                    dys = self.day - shifted.day
            else:
                if shifted > self:  # i.e. we've overshot
                    mos -= 1
                    shifted = d._add_months(mos)
                    dys = (
                        -shifted.day
                        + days_in_month(shifted.year, shifted.month)
                        + self.day
                    )
                else:
                    dys = self.day - shifted.day
            return DateDelta(months=mos, days=dys)
        return NotImplemented

    __str__ = format_iso

    def __repr__(self) -> str:
        return f'Date("{self}")'

    def __eq__(self, other: object) -> bool:
        """Compare for equality

        >>> d = Date(2021, 1, 2)
        >>> d == Date(2021, 1, 2)
        True
        >>> d == Date(2021, 1, 3)
        False
        """
        if not isinstance(other, Date):
            return NotImplemented
        return self._py_date == other._py_date

    def __hash__(self) -> int:
        return hash(self._py_date)

    def __lt__(self, other: Date) -> bool:
        if not isinstance(other, Date):
            return NotImplemented
        return self._py_date < other._py_date

    def __le__(self, other: Date) -> bool:
        if not isinstance(other, Date):
            return NotImplemented
        return self._py_date <= other._py_date

    def __gt__(self, other: Date) -> bool:
        if not isinstance(other, Date):
            return NotImplemented
        return self._py_date > other._py_date

    def __ge__(self, other: Date) -> bool:
        if not isinstance(other, Date):
            return NotImplemented
        return self._py_date >= other._py_date

    @classmethod
    def _from_py_unchecked(cls, d: _date, /) -> Date:
        self = _object_new(cls)
        self._init_from_inner(d)
        return self

    def _init_from_inner(self, d: _date, /) -> None:
        self._py_date = d

    @no_type_check
    def __reduce__(self):
        return _unpkl_date, (pack("<HBB", self.year, self.month, self.day),)


# A separate unpickling function allows us to make backwards-compatible changes
# to the pickling format in the future
@no_type_check
def _unpkl_date(data: bytes) -> Date:
    return Date(*unpack("<HBB", data))


Date.MIN = Date._from_py_unchecked(_date.min)
Date.MAX = Date._from_py_unchecked(_date.max)


@final
class YearMonth(_Base):
    """A year and month without a day component.

    Useful for representing recurring events, billing periods,
    or any concept that doesn't need a specific day.

    >>> ym = YearMonth(2021, 1)
    YearMonth("2021-01")

    Can also be constructed from an ISO 8601 string:

    >>> YearMonth("2021-01")
    YearMonth("2021-01")
    """

    # We store the underlying data in a datetime.date object,
    # which allows us to benefit from its functionality and performance.
    # It isn't exposed to the user, so it's not a problem.
    __slots__ = ("_py",)

    MIN: ClassVar[YearMonth]
    """The minimum possible year-month"""
    MAX: ClassVar[YearMonth]
    """The maximum possible year-month"""

    # Overloads for a nice autodoc.
    # Proper typing of the constructors is handled in the type stubs
    if not TYPE_CHECKING:

        @overload
        def __init__(self, iso_string: str, /) -> None: ...

        @overload
        def __init__(self, year: int, month: int) -> None: ...

    def __init__(self, year: int, month: int) -> None:
        self._py = _date(year, month, 1)

    __init__ = add_alternate_constructors(__init__)

    def _init_from_iso(self, s: str) -> None:
        self._py = yearmonth_from_iso(s)

    @property
    def year(self) -> int:
        """The year component of the year-month

        >>> YearMonth(2021, 1).year
        2021
        """
        return self._py.year

    @property
    def month(self) -> int:
        """The month component of the year-month

        >>> YearMonth(2021, 1).month
        1
        """
        return self._py.month

    def format_iso(self) -> str:
        """Format as the ISO 8601 year-month format.

        Inverse of :meth:`parse_iso`.

        >>> YearMonth(2021, 1).format_iso()
        '2021-01'
        """
        return self._py.isoformat()[:7]

    @classmethod
    def parse_iso(cls, s: str, /) -> YearMonth:
        """Create from the ISO 8601 format ``YYYY-MM`` or ``YYYYMM``.

        Inverse of :meth:`format_iso`

        >>> YearMonth.parse_iso("2021-01")
        YearMonth("2021-01")
        """
        return cls._from_py_unchecked(yearmonth_from_iso(s))

    if not TYPE_CHECKING:  # for a nice autodoc

        @overload
        def replace(self, year: int = ..., month: int = ...) -> YearMonth: ...

    def replace(self, **kwargs: Any) -> YearMonth:
        """Create a new instance with the given fields replaced

        >>> d = YearMonth(2021, 12)
        >>> d.replace(month=3)
        YearMonth("2021-03")
        """
        if "day" in kwargs:
            raise TypeError(
                "replace() got an unexpected keyword argument 'day'"
            )
        return YearMonth._from_py_unchecked(self._py.replace(**kwargs))

    def on_day(self, day: int, /) -> Date:
        """Create a date from this year-month with a given day

        >>> YearMonth(2021, 1).on_day(2)
        Date("2021-01-02")
        """
        return Date._from_py_unchecked(self._py.replace(day=day))

    __str__ = format_iso

    def __repr__(self) -> str:
        return f'YearMonth("{self}")'

    def __eq__(self, other: object) -> bool:
        """Compare for equality

        >>> ym = YearMonth(2021, 1)
        >>> ym == YearMonth(2021, 1)
        True
        >>> ym == YearMonth(2021, 2)
        False
        """
        if not isinstance(other, YearMonth):
            return NotImplemented
        return self._py == other._py

    def __lt__(self, other: YearMonth) -> bool:
        if not isinstance(other, YearMonth):
            return NotImplemented
        return self._py < other._py

    def __le__(self, other: YearMonth) -> bool:
        if not isinstance(other, YearMonth):
            return NotImplemented
        return self._py <= other._py

    def __gt__(self, other: YearMonth) -> bool:
        if not isinstance(other, YearMonth):
            return NotImplemented
        return self._py > other._py

    def __ge__(self, other: YearMonth) -> bool:
        if not isinstance(other, YearMonth):
            return NotImplemented
        return self._py >= other._py

    def __hash__(self) -> int:
        return hash(self._py)

    @classmethod
    def _from_py_unchecked(cls, d: _date, /) -> YearMonth:
        self = _object_new(cls)
        self._init_from_inner(d)
        return self

    def _init_from_inner(self, d: _date, /) -> None:
        assert d.day == 1
        self._py = d

    @no_type_check
    def __reduce__(self):
        return _unpkl_ym, (pack("<HB", self.year, self.month),)


# A separate unpickling function allows us to make backwards-compatible changes
# to the pickling format in the future
@no_type_check
def _unpkl_ym(data: bytes) -> YearMonth:
    return YearMonth(*unpack("<HB", data))


YearMonth.MIN = YearMonth._from_py_unchecked(_date.min)
YearMonth.MAX = YearMonth._from_py_unchecked(_date.max.replace(day=1))


_DUMMY_LEAP_YEAR = 4


@final
class MonthDay(_Base):
    """A month and day without a year component.

    Useful for representing recurring annual events such as
    birthdays, holidays, or anniversaries.

    >>> md = MonthDay(11, 23)
    MonthDay("--11-23")

    Can also be constructed from an ISO 8601 string:

    >>> MonthDay("--11-23")
    MonthDay("--11-23")
    """

    # We store the underlying data in a datetime.date object,
    # which allows us to benefit from its functionality and performance.
    # It isn't exposed to the user, so it's not a problem.
    __slots__ = ("_py",)

    MIN: ClassVar[MonthDay]
    """The minimum possible month-day"""
    MAX: ClassVar[MonthDay]
    """The maximum possible month-day"""

    # Overloads for a nice autodoc.
    # Proper typing of the constructors is handled in the type stubs
    if not TYPE_CHECKING:

        @overload
        def __init__(self, iso_string: str, /) -> None: ...

        @overload
        def __init__(self, month: int, day: int) -> None: ...

    def __init__(self, month: int, day: int) -> None:
        self._py = _date(_DUMMY_LEAP_YEAR, month, day)

    __init__ = add_alternate_constructors(__init__)

    def _init_from_iso(self, s: str) -> None:
        self._py = monthday_from_iso(s)

    @property
    def month(self) -> int:
        """The month component of the month-day

        >>> MonthDay(11, 23).month
        11
        """
        return self._py.month

    @property
    def day(self) -> int:
        """The day component of the month-day

        >>> MonthDay(11, 23).day
        23
        """
        return self._py.day

    def format_iso(self) -> str:
        """Format as the ISO 8601 month-day format.

        Inverse of ``parse_iso``.

        >>> MonthDay(10, 8).format_iso()
        '--10-08'

        Note
        ----
        This format is officially only part of the 2000 edition of the
        ISO 8601 standard. There is no alternative for month-day
        in the newer editions. However, it is still widely used in other libraries.
        """
        return f"-{self._py.isoformat()[4:]}"

    @classmethod
    def parse_iso(cls, s: str, /) -> MonthDay:
        """Create from the ISO 8601 format ``--MM-DD`` or ``--MMDD``.

        Inverse of :meth:`format_iso`

        >>> MonthDay.parse_iso("--11-23")
        MonthDay("--11-23")
        """
        return cls._from_py_unchecked(monthday_from_iso(s))

    if not TYPE_CHECKING:  # for a nice autodoc

        @overload
        def replace(self, month: int = ..., day: int = ...) -> MonthDay: ...

    def replace(self, **kwargs: Any) -> MonthDay:
        """Create a new instance with the given fields replaced

        >>> d = MonthDay(11, 23)
        >>> d.replace(month=3)
        MonthDay("--03-23")
        """
        if "year" in kwargs:
            raise TypeError(
                "replace() got an unexpected keyword argument 'year'"
            )
        return MonthDay._from_py_unchecked(self._py.replace(**kwargs))

    def in_year(self, year: int, /) -> Date:
        """Create a date from this month-day with a given day

        >>> MonthDay(8, 1).in_year(2025)
        Date("2025-08-01")

        Note
        ----
        This method will raise a ``ValueError`` if the month-day is a leap day
        and the year is not a leap year.
        """
        return Date._from_py_unchecked(self._py.replace(year=year))

    def is_leap(self) -> bool:
        """Check if the month-day is February 29th

        >>> MonthDay(2, 29).is_leap()
        True
        >>> MonthDay(3, 1).is_leap()
        False
        """
        return self._py.month == 2 and self._py.day == 29

    __str__ = format_iso

    def __repr__(self) -> str:
        return f'MonthDay("{self}")'

    def __eq__(self, other: object) -> bool:
        """Compare for equality

        >>> md = MonthDay(10, 1)
        >>> md == MonthDay(10, 1)
        True
        >>> md == MonthDay(10, 2)
        False
        """
        if not isinstance(other, MonthDay):
            return NotImplemented
        return self._py == other._py

    def __lt__(self, other: MonthDay) -> bool:
        if not isinstance(other, MonthDay):
            return NotImplemented
        return self._py < other._py

    def __le__(self, other: MonthDay) -> bool:
        if not isinstance(other, MonthDay):
            return NotImplemented
        return self._py <= other._py

    def __gt__(self, other: MonthDay) -> bool:
        if not isinstance(other, MonthDay):
            return NotImplemented
        return self._py > other._py

    def __ge__(self, other: MonthDay) -> bool:
        if not isinstance(other, MonthDay):
            return NotImplemented
        return self._py >= other._py

    def __hash__(self) -> int:
        return hash(self._py)

    @classmethod
    def _from_py_unchecked(cls, d: _date, /) -> MonthDay:
        self = _object_new(cls)
        self._init_from_inner(d)
        return self

    def _init_from_inner(self, d: _date, /) -> None:
        assert d.year == _DUMMY_LEAP_YEAR
        self._py = d

    @no_type_check
    def __reduce__(self):
        return _unpkl_md, (pack("<BB", self.month, self.day),)


# A separate unpickling function allows us to make backwards-compatible changes
# to the pickling format in the future
@no_type_check
def _unpkl_md(data: bytes) -> MonthDay:
    return MonthDay(*unpack("<BB", data))


MonthDay.MIN = MonthDay._from_py_unchecked(
    _date.min.replace(year=_DUMMY_LEAP_YEAR)
)
MonthDay.MAX = MonthDay._from_py_unchecked(
    _date.max.replace(year=_DUMMY_LEAP_YEAR)
)


@final
class Time(_Base):
    """Time of day without a date component.

    >>> t = Time(12, 30, 0)
    Time("12:30:00")

    Can also be constructed from an ISO 8601 string:

    >>> Time("12:30:00")
    Time("12:30:00")

    Or a standard library :class:`~datetime.time`:

    >>> Time(time(12, 30, 0))
    Time("12:30:00")

    Sub-second precision up to nanoseconds is supported:

    >>> Time(12, 30, 0, nanosecond=1)
    Time("12:30:00.000000001")

    Times can be compared and sorted:

    >>> Time(12, 30) > Time(8, 0)
    True
    """

    __slots__ = ("_py", "_nanos")

    MIN: ClassVar[Time]
    """The minimum time, at midnight"""
    MIDNIGHT: ClassVar[Time]
    """Alias for :attr:`MIN`"""
    NOON: ClassVar[Time]
    """The time at noon"""
    MAX: ClassVar[Time]
    """The maximum time, just before midnight"""

    # Overloads for a nice autodoc.
    # Proper typing of the constructors is handled in the type stubs
    if not TYPE_CHECKING:

        @overload
        def __init__(self, iso_string: str, /) -> None: ...

        @overload
        def __init__(
            self,
            hour: int = 0,
            minute: int = 0,
            second: int = 0,
            *,
            nanosecond: int = 0,
        ) -> None: ...

    def __init__(
        self,
        hour: int = 0,
        minute: int = 0,
        second: int = 0,
        *,
        nanosecond: int = 0,
    ) -> None:
        self._py = _time(hour, minute, second)
        if nanosecond < 0 or nanosecond >= 1_000_000_000:
            raise ValueError("Nanosecond out of range")
        self._nanos = nanosecond

    __init__ = add_alternate_constructors(__init__, py_type=_time)

    def _init_from_iso(self, s: str) -> None:
        self._py, self._nanos = time_from_iso(s)

    @property
    def hour(self) -> int:
        """The hour component of the time

        >>> Time(12, 30, 0).hour
        12
        """
        return self._py.hour

    @property
    def minute(self) -> int:
        """The minute component of the time

        >>> Time(12, 30, 0).minute
        30
        """
        return self._py.minute

    @property
    def second(self) -> int:
        """The second component of the time
        >>> Time(12, 30, 0).second
        0
        """
        return self._py.second

    @property
    def nanosecond(self) -> int:
        """The nanosecond component of the time

        >>> Time("12:30:00.003).nanosecond
        3000000
        """
        return self._nanos

    def on(self, d: Date, /) -> PlainDateTime:
        """Combine a time with a date to create a datetime

        >>> t = Time(12, 30)
        >>> t.on(Date(2021, 1, 2))
        PlainDateTime("2021-01-02 12:30:00")

        Then, use methods like :meth:`~PlainDateTime.assume_utc`
        or :meth:`~PlainDateTime.assume_tz`
        to find the corresponding exact time:

        >>> t.on(Date(2021, 1, 2)).assume_tz("America/New_York")
        ExactDateTime("2021-01-02 12:30:00-05:00[America/New_York]")
        """
        return PlainDateTime._from_py_unchecked(
            _datetime.combine(d._py_date, self._py),
            self._nanos,
        )

    def py_time(self) -> _time:
        """Convert to a standard library :class:`~datetime.time`"""
        return self._py.replace(microsecond=self._nanos // 1_000)

    @classmethod
    def from_py_time(cls, t: _time, /) -> Time:
        """Create from a :class:`~datetime.time`

        >>> Time.from_py_time(time(12, 30, 0))
        Time(12:30:00)

        `fold` value is ignored.
        """
        self = _object_new(cls)
        self._init_from_py(t)
        return self

    def _init_from_py(self, t: _time, /) -> None:
        if type(t) is _time:
            t = t.replace(tzinfo=None, fold=0)
        elif isinstance(t, _time):
            # subclass-safe way to ensure we have exactly a datetime.time
            t = _time(t.hour, t.minute, t.second, t.microsecond)
        else:
            raise TypeError(f"Expected datetime.time, got {type(t)!r}")
        return self._init_from_inner(
            (t.replace(microsecond=0), t.microsecond * 1_000)
        )

    def format_iso(
        self,
        *,
        unit: Literal[
            "hour",
            "minute",
            "second",
            "millisecond",
            "microsecond",
            "nanosecond",
            "auto",
        ] = "auto",
        basic: bool = False,
    ) -> str:
        """Format as the ISO 8601 time format.

        Inverse of :meth:`parse_iso`.

        >>> Time(12, 30, 0).format_iso(unit='millisecond')
        '12:30:00.000'
        >>> Time(4, 0, 59, nanosecond=40_000).format_iso(basic=True)
        '040059.00004'
        """
        return _format_time(self._py, self._nanos, unit, basic)

    @classmethod
    def parse_iso(cls, s: str, /) -> Time:
        """Create from the ISO 8601 time format

        Inverse of :meth:`format_iso`

        >>> Time.parse_iso("12:30:00")
        Time(12:30:00)
        """
        return cls._from_py_unchecked(*time_from_iso(s))

    if not TYPE_CHECKING:  # for a nice autodoc

        @overload
        def replace(
            self,
            hour: int = ...,
            minute: int = ...,
            second: int = ...,
            nanosecond: int = ...,
        ) -> Time: ...

    def replace(self, **kwargs: Any) -> Time:
        """Create a new instance with the given fields replaced

        >>> t = Time(12, 30, 0)
        >>> d.replace(minute=3, nanosecond=4_000)
        Time(12:03:00.000004)

        """
        _check_invalid_replace_kwargs(kwargs)
        nanos = _pop_nanos_kwarg(kwargs, self._nanos)
        return Time._from_py_unchecked(self._py.replace(**kwargs), nanos)

    def _to_ns_since_midnight(self) -> int:
        return (
            self._py.hour * 3_600_000_000_000
            + self._py.minute * 60_000_000_000
            + self._py.second * 1_000_000_000
            + self._nanos
        )

    @classmethod
    def _from_ns_since_midnight(cls, ns: int) -> Time:
        assert 0 <= ns < 86_400_000_000_000
        (hours, ns) = divmod(ns, 3_600_000_000_000)
        (minutes, ns) = divmod(ns, 60_000_000_000)
        (seconds, ns) = divmod(ns, 1_000_000_000)
        return cls._from_py_unchecked(_time(hours, minutes, seconds), ns)

    def round(
        self,
        unit: Literal[
            "hour",
            "minute",
            "second",
            "millisecond",
            "microsecond",
            "nanosecond",
        ] = "second",
        increment: int = 1,
        mode: RoundModeStr = "half_even",
    ) -> Time:
        """Round the time to the specified unit and increment.
        Various rounding modes are available.

        >>> Time(12, 39, 59).round("minute", 15)
        Time(12:45:00)
        >>> Time(8, 9, 13).round("second", 5, mode="floor")
        Time(08:09:10)
        """
        if unit == "day":  # type: ignore[comparison-overlap]
            raise ValueError("Cannot round Time to day")
        return self._round_unchecked(
            increment_to_ns_for_datetime(unit, increment),
            mode,
            86_400_000_000_000,
        )[0]

    def _round_unchecked(
        self,
        increment_ns: int,
        mode: str,
        day_in_ns: int,
    ) -> tuple[Time, int]:  # the time, and whether the result is "next day"

        quotient, remainder_ns = divmod(
            self._to_ns_since_midnight(), increment_ns
        )
        floor = quotient * increment_ns
        if mode not in ("floor", "trunc"):
            floor = custom_round(
                floor,
                remainder_ns,
                increment_ns,
                mode,
                increment_ns,
                1,
            )
        next_day, ns_since_midnight = divmod(floor, day_in_ns)
        return self._from_ns_since_midnight(ns_since_midnight), next_day

    @classmethod
    def _from_py_unchecked(cls, t: _time, nanos: int, /) -> Time:
        self = _object_new(cls)
        self._init_from_inner((t, nanos))
        return self

    def _init_from_inner(self, inner: tuple[_time, int]) -> None:
        t, nanos = inner
        assert not t.microsecond
        self._py = t
        self._nanos = nanos

    __str__ = format_iso

    def __repr__(self) -> str:
        return f'Time("{self}")'

    def __eq__(self, other: object) -> bool:
        """Compare for equality

        >>> t = Time(12, 30, 0)
        >>> t == Time(12, 30, 0)
        True
        >>> t == Time(12, 30, 1)
        False
        """
        if not isinstance(other, Time):
            return NotImplemented
        return (self._py, self._nanos) == (other._py, other._nanos)

    def __hash__(self) -> int:
        return hash((self._py, self._nanos))

    def __lt__(self, other: Time) -> bool:
        if not isinstance(other, Time):
            return NotImplemented
        return (self._py, self._nanos) < (other._py, other._nanos)

    def __le__(self, other: Time) -> bool:
        if not isinstance(other, Time):
            return NotImplemented
        return (self._py, self._nanos) <= (other._py, other._nanos)

    def __gt__(self, other: Time) -> bool:
        if not isinstance(other, Time):
            return NotImplemented
        return (self._py, self._nanos) > (other._py, other._nanos)

    def __ge__(self, other: Time) -> bool:
        if not isinstance(other, Time):
            return NotImplemented
        return (self._py, self._nanos) >= (other._py, other._nanos)

    @no_type_check
    def __reduce__(self):
        return (
            _unpkl_time,
            (
                pack(
                    "<BBBI",
                    self._py.hour,
                    self._py.minute,
                    self._py.second,
                    self._nanos,
                ),
            ),
        )


# A separate unpickling function allows us to make backwards-compatible changes
# to the pickling format in the future
def _unpkl_time(data: bytes) -> Time:
    *args, nanos = unpack("<BBBI", data)
    return Time._from_py_unchecked(_time(*args), nanos)


Time.MIN = Time()
Time.MIDNIGHT = Time()
Time.NOON = Time(12)
Time.MAX = Time(23, 59, 59, nanosecond=999_999_999)


@final
class TimeDelta(_Base):
    """A duration consisting of a precise time: hours, minutes, (nano)seconds.
    For durations including months or days, use :class:`~ItemizedDelta`,
    or :class:`~whenever.ItemizedDateDelta` for date-only durations.

    The inputs are normalized, so 90 minutes becomes 1 hour and 30 minutes,
    for example.

    >>> d = TimeDelta(hours=1, minutes=90)
    TimeDelta("PT2h30m")
    >>> d.total("minutes")
    150.0

    Can also be constructed from an ISO 8601 duration string
    or a standard library :class:`~datetime.timedelta`:

    >>> TimeDelta("PT2h30m")
    TimeDelta("PT2h30m")

    ``TimeDelta`` can be added to or subtracted from datetime types
    to shift them by an exact amount of time:

    >>> Instant("2022-10-24 00:00Z") + TimeDelta(hours=3)
    Instant("2022-10-24 03:00:00Z")

    Note
    ----
    A shorter way to instantiate a timedelta is to use the helper functions
    :func:`~whenever.hours`, :func:`~whenever.minutes`, etc.
    """

    __slots__ = ("_total_ns",)

    # FUTURE: allow weeks and days (with 24 hour warning)?

    # Overloads for a nice autodoc.
    # Proper typing of the constructors is handled in the type stubs
    if not TYPE_CHECKING:

        @overload
        def __init__(self, iso_string: str, /) -> None: ...

        @overload
        def __init__(self, py_timedelta: _timedelta, /) -> None: ...

        @overload
        def __init__(
            self,
            *,
            hours: float = 0,
            minutes: float = 0,
            seconds: float = 0,
            milliseconds: float = 0,
            microseconds: float = 0,
            nanoseconds: int = 0,
        ) -> None: ...

    def __init__(
        self,
        *,
        hours: float = 0,
        minutes: float = 0,
        seconds: float = 0,
        milliseconds: float = 0,
        microseconds: float = 0,
        nanoseconds: int = 0,
    ) -> None:
        assert type(nanoseconds) is int  # catch this common mistake
        ns = self._total_ns = (
            # Cast individual components to int to avoid floating point errors
            int(hours * 3_600_000_000_000)
            + int(minutes * 60_000_000_000)
            + int(seconds * 1_000_000_000)
            + int(milliseconds * 1_000_000)
            + int(microseconds * 1_000)
            + nanoseconds
        )
        if abs(ns) > _MAX_DELTA_NANOS:
            raise ValueError("TimeDelta out of range")

    __init__ = add_alternate_constructors(__init__, py_type=_timedelta)

    ZERO: ClassVar[TimeDelta]
    """A delta of zero"""
    MAX: ClassVar[TimeDelta]
    """The maximum possible delta"""
    MIN: ClassVar[TimeDelta]
    """The minimum possible delta"""
    _date_part: ClassVar[DateDelta]

    @property
    def _time_part(self) -> TimeDelta:
        return self

    def total(
        self,
        unit: Literal[
            "years",
            "months",
            "weeks",
            "days",
            "hours",
            "minutes",
            "seconds",
            "milliseconds",
            "microseconds",
            "nanoseconds",
        ],
        # FUTURE: allow other local time types?
        relative_to: ZonedDateTime = _UNSET,
    ) -> float | int:
        """The total size in the given unit, as a float (or int for nanoseconds)

        >>> d = TimeDelta(hours=1, minutes=30)
        >>> d.total('minutes')
        90.0
        """
        if unit in ("days", "weeks", "years", "months"):
            if relative_to is not _UNSET:
                shifted = relative_to + self
                sign: Literal[1, -1] = 1 if self._total_ns >= 0 else -1

                target_date = shifted.date()
                cal_shifted = relative_to.replace_date(target_date)
                if sign == 1 and cal_shifted > shifted:
                    target_date = target_date.subtract(days=1)
                elif sign == -1 and cal_shifted < shifted:
                    target_date = target_date.add(days=1)

                trunc_amount, trunc_date, expanded_date = DIFF_FUNCS[unit](
                    target_date._py_date,
                    relative_to._py_dt.date(),
                    1,
                    sign,
                )
                trunc_zdt = relative_to.replace_date(
                    Date._from_py_unchecked(resolve_leap_day(trunc_date))
                )

                return (
                    trunc_amount
                    + (shifted - trunc_zdt)
                    / (
                        relative_to.replace_date(
                            Date._from_py_unchecked(
                                resolve_leap_day(expanded_date)
                            )
                        )
                        - trunc_zdt
                    )
                ) * sign
            elif unit in ("days", "weeks"):
                if not _ignore_days_not_always_24h_warning.get():
                    warn(DaysNotAlways24HoursWarning(DAYS_NOT_ALWAYS_24H_MSG))
            else:
                raise ValueError(
                    f"Cannot convert TimeDelta to {unit!r} without a `relative_to` parameter"
                )
        elif unit == "nanoseconds":
            return self._total_ns
        try:
            return self._total_ns / NS_PER_UNIT_PLURAL[unit]
        except KeyError:
            raise ValueError(f"Invalid unit: {unit!r}")

    def in_days_of_24h(self) -> float:
        """The total size in days (of exactly 24 hours each)

        Note
        ----
        Note that this may not be the same as days on the calendar,
        since some days have 23 or 25 hours due to daylight saving time.

        .. deprecated:: 0.10.0

            Use :meth:`total` with ``'days'`` instead.
        """
        warn(
            "in_days_of_24h is deprecated, use total('days') instead",
            WheneverDeprecationWarning,
            stacklevel=2,
        )
        return self._total_ns / 86_400_000_000_000

    def in_hours(self) -> float:
        """The total size in hours

        >>> d = TimeDelta(hours=1, minutes=30)
        >>> d.in_hours()
        1.5

        .. deprecated:: 0.10.0

            Use :meth:`total` with ``'hours'`` instead.
        """
        warn(
            "in_hours is deprecated, use total('hours') instead",
            WheneverDeprecationWarning,
            stacklevel=2,
        )
        return self._total_ns / 3_600_000_000_000

    def in_minutes(self) -> float:
        """The total size in minutes

        >>> d = TimeDelta(hours=1, minutes=30, seconds=30)
        >>> d.in_minutes()
        90.5

        .. deprecated:: 0.10.0

            Use :meth:`total` with ``'minutes'`` instead.
        """
        warn(
            "in_minutes is deprecated, use total('minutes') instead",
            WheneverDeprecationWarning,
            stacklevel=2,
        )
        return self._total_ns / 60_000_000_000

    def in_seconds(self) -> float:
        """The total size in seconds

        >>> d = TimeDelta(minutes=2, seconds=1, microseconds=500_000)
        >>> d.in_seconds()
        121.5

        .. deprecated:: 0.10.0

            Use :meth:`total` with ``'seconds'`` instead.
        """
        warn(
            "in_seconds is deprecated, use total('seconds') instead",
            WheneverDeprecationWarning,
            stacklevel=2,
        )
        return self._total_ns / 1_000_000_000

    def in_milliseconds(self) -> float:
        """The total size in milliseconds

        >>> d = TimeDelta(seconds=2, microseconds=50)
        >>> d.in_milliseconds()
        2_000.05

        .. deprecated:: 0.10.0

            Use :meth:`total` with ``'milliseconds'`` instead.
        """
        warn(
            "in_milliseconds is deprecated, use total('milliseconds') instead",
            WheneverDeprecationWarning,
            stacklevel=2,
        )
        return self._total_ns / 1_000_000

    def in_microseconds(self) -> float:
        """The total size in microseconds

        >>> d = TimeDelta(seconds=2, nanoseconds=50)
        >>> d.in_microseconds()
        2_000_000.05

        .. deprecated:: 0.10.0

            Use :meth:`total` with ``'microseconds'`` instead.
        """
        warn(
            "in_microseconds is deprecated, use total('microseconds') instead",
            WheneverDeprecationWarning,
            stacklevel=2,
        )
        return self._total_ns / 1_000

    def in_nanoseconds(self) -> int:
        """The total size in nanoseconds

        >>> d = TimeDelta(seconds=2, nanoseconds=50)
        >>> d.in_nanoseconds()
        2_000_000_050

        .. deprecated:: 0.10.0

            Use :meth:`total` with ``'nanoseconds'`` instead.
        """
        warn(
            "in_nanoseconds is deprecated, use total('nanoseconds') instead",
            WheneverDeprecationWarning,
            stacklevel=2,
        )
        return self._total_ns

    def in_hrs_mins_secs_nanos(self) -> tuple[int, int, int, int]:
        """Convert to a tuple of (hours, minutes, seconds, nanoseconds)

        >>> d = TimeDelta(hours=1, minutes=30, microseconds=5_000_090)
        >>> d.in_hrs_mins_secs_nanos()
        (1, 30, 5, 90_000)

        ... deprecated:: 0.10.0

            Use :meth:`in_units` with ``['hours', 'minutes', 'seconds', 'nanoseconds']`` instead.
        """
        hours, rem = divmod(abs(self._total_ns), 3_600_000_000_000)
        mins, rem = divmod(rem, 60_000_000_000)
        secs, ns = divmod(rem, 1_000_000_000)
        return (
            (hours, mins, secs, ns)
            if self._total_ns >= 0
            else (-hours, -mins, -secs, -ns)
        )

    def in_units(
        self,
        units: Sequence[ExactDeltaUnitStr],
        /,
        *,
        round_unit: Literal[
            "millisecond",
            "microsecond",
            "nanosecond",
        ] = _UNSET,
        round_mode: RoundModeStr = "trunc",
        round_increment: int = 1,
    ) -> ItemizedDelta:
        """Convert to a :class:`ItemizedDelta` with the specified units

        >>> d = TimeDelta(hours=2, minutes=30, seconds=23, milliseconds=500)
        >>> d.in_units(['minutes', 'seconds'])
        ItemizedDelta("PT150m24s")
        >>> (hrs, mins) = d.in_units(('hours', 'minutes'), round_mode='ceil').values()
        (2, 31)

        Parameters
        ----------
        units
            A sequence of plural unit names, in descending order.
            Valid unit names are: ``weeks``, ``days``, ``hours``,
            ``minutes``, ``seconds``, ``nanoseconds``.
        round_unit
            The unit to round to before conversion.
            If omitted, the smallest unit in ``units`` is used.
            See :meth:`round` for details.
        round_mode
            The rounding mode to use when rounding before conversion.
            See :meth:`round` for details.
        round_increment
            The rounding increment to use when rounding before conversion.
            See :meth:`round` for details.
        """
        if not units:
            raise ValueError("At least one unit must be specified")
        elif isinstance(units, str):  # Hard to debug if not caught here
            raise TypeError("Units must be a sequence, not a string")
        elif any(u and not u.endswith("s") for u in units):
            raise ValueError("All units must be plural")
        elif sorted(units, key=lambda u: _unit_index(u, EXACT_UNITS)) != list(
            units
        ):
            raise ValueError(
                "Units must be specified from largest to smallest"
            )
        elif len(set(units)) != len(units):
            raise ValueError("Duplicate units are not allowed")
        elif units[-1] == "nanoseconds" and (
            len(units) == 1 or units[-2] != "seconds"
        ):
            raise ValueError(
                "Nanoseconds can only be specified together with seconds"
            )
        elif (
            "days" in units or "weeks" in units
        ) and not _ignore_days_not_always_24h_warning.get():
            warn(
                DAYS_NOT_ALWAYS_24H_MSG,
                DaysNotAlways24HoursWarning,
                stacklevel=2,
            )

        result = self._in_units(units, round_unit, round_mode, round_increment)
        sign: Sign = 1 if self._total_ns >= 0 else -1
        if not any(result.values()):
            sign = 0  # due to rounding, the result may be zero even if self is not zero
        # mypy false positive: 'keywords must be strings' (but they're string literals!)
        return ItemizedDelta._from_signed(sign, **result)  # type: ignore[misc]

    # Private version of in_units() without validation and afterprocessing
    def _in_units(
        self,
        units: Sequence[ExactDeltaUnitStr],
        round_unit: Literal["millisecond", "microsecond", "nanosecond"],
        round_mode: RoundModeStr,
        round_increment: int,
    ) -> dict[ExactDeltaUnitStr, int]:

        self = self.round(
            unit=(
                # trim the last 's' from the smallest unit to get the singular form
                units[-1][:-1]  # type: ignore[arg-type]
                if round_unit is _UNSET
                else round_unit
            ),
            increment=round_increment,
            mode=round_mode,
        )
        remaining_ns = abs(self._total_ns)
        values = {}
        for u in units:
            values[u], remaining_ns = divmod(remaining_ns, _DELTA_ITEMS_NS[u])

        return values

    def py_timedelta(self) -> _timedelta:
        """Convert to a :class:`~datetime.timedelta`

        Inverse of :meth:`from_py_timedelta`

        >>> d = TimeDelta(hours=1, minutes=30)
        >>> d.py_timedelta()
        timedelta(seconds=5400)

        Note
        ----
        Nanoseconds are truncated to microseconds.
        If you need more control over rounding, use :meth:`round` first.
        """
        return _timedelta(microseconds=self._total_ns // 1_000)

    def _init_from_py(self, td: _timedelta, /) -> None:
        if type(td) is not _timedelta:
            raise TypeError("Expected datetime.timedelta exactly")
        self._total_ns = ns = (
            td.microseconds * 1_000
            + td.seconds * 1_000_000_000
            + td.days * 24 * 3_600_000_000_000
        )
        if abs(ns) > _MAX_DELTA_NANOS:
            raise ValueError("TimeDelta out of range")

    @classmethod
    def from_py_timedelta(cls, td: _timedelta, /) -> TimeDelta:
        """Create from a :class:`~datetime.timedelta`

        Inverse of :meth:`py_timedelta`

        >>> TimeDelta.from_py_timedelta(timedelta(seconds=5400))
        TimeDelta("PT1h30m")

        Note
        ----
        Subclasses of :class:`~datetime.timedelta` are not accepted
        because they often add additional state that cannot be represented
        in a :class:`TimeDelta`.
        """
        self = _object_new(cls)
        self._init_from_py(td)
        return self

    def format_iso(self) -> str:
        """Format as the *popular interpretation* of the ISO 8601 duration format.
        May not strictly adhere to (all versions of) the standard.
        See :ref:`here <iso8601-durations>` for more information.

        Inverse of :meth:`parse_iso`.

        >>> TimeDelta(hours=1, minutes=30).format_iso()
        'PT1H30M'
        """
        hrs, mins, secs, ns = abs(self).in_hrs_mins_secs_nanos()
        seconds = (
            f"{secs + ns / 1_000_000_000:.9f}".rstrip("0") if ns else str(secs)
        )
        return f"{(self._total_ns < 0) * '-'}PT" + (
            (
                f"{hrs}H" * bool(hrs)
                + f"{mins}M" * bool(mins)
                + f"{seconds}S" * bool(secs or ns)
            )
            or "0S"
        )

    def _init_from_iso(self, s: str) -> None:
        exc = ValueError(f"Invalid format: {s!r}")
        prev_unit = ""
        nanos = 0

        if len(s) < 4 or not s.isascii():
            raise exc

        s = s.upper()
        if s.startswith("PT"):
            sign = 1
            rest = s[2:]
        elif s.startswith("-PT"):
            sign = -1
            rest = s[3:]
        elif s.startswith("+PT"):
            sign = 1
            rest = s[3:]
        else:
            raise exc

        while rest:
            rest, value, unit = parse_timedelta_component(rest, exc)

            if unit == "H" and prev_unit == "":
                nanos += value * 3_600_000_000_000
            elif unit == "M" and prev_unit in "H":
                nanos += value * 60_000_000_000
            elif unit == "S":
                nanos += value
                if rest:
                    raise exc
                break
            else:
                raise exc  # components out of order

            prev_unit = unit

        if nanos > _MAX_DELTA_NANOS:
            raise ValueError("TimeDelta out of range")

        self._total_ns = sign * nanos

    @classmethod
    def parse_iso(cls, s: str, /) -> TimeDelta:
        """Parse the *popular interpretation* of the ISO 8601 duration format.
        Does not parse all possible ISO 8601 durations.
        See :ref:`here <iso8601-durations>` for more information.

        Inverse of :meth:`format_iso`

        >>> TimeDelta.parse_iso("PT1H80M")
        TimeDelta("PT2h20m")

        Note
        ----
        Any duration with a date part is considered invalid.
        ``PT0S`` is valid, but ``P0D`` is not.
        """
        self = _object_new(cls)
        self._init_from_iso(s)
        return self

    def round(
        self,
        unit: Literal[
            "week",
            "day",
            "hour",
            "minute",
            "second",
            "millisecond",
            "microsecond",
            "nanosecond",
        ] = "second",
        increment: int = 1,
        mode: RoundModeStr = "half_even",
    ) -> TimeDelta:
        """Round the delta to the specified unit and increment.
        Various rounding modes are available.

        >>> t = TimeDelta(seconds=12345)
        TimeDelta("PT3h25m45s")
        >>> t.round("minute")
        TimeDelta("PT3h26m")
        >>> t.round("second", increment=10, mode="floor")
        TimeDelta("PT3h25m40s")
        """
        if (
            unit in ("day", "week")
            and not _ignore_days_not_always_24h_warning.get()
        ):
            warn(
                DAYS_NOT_ALWAYS_24H_MSG,
                DaysNotAlways24HoursWarning,
                stacklevel=2,
            )
        increment_ns = increment_to_ns_for_delta(unit, increment)
        quotient, remainder_ns = divmod(abs(self._total_ns), increment_ns)
        sign: Literal[1, -1] = 1 if self._total_ns >= 0 else -1

        abs_result = quotient * increment_ns
        if mode != "trunc":
            abs_result = custom_round(
                abs_result,
                remainder_ns,
                increment_ns,
                mode,
                increment_ns,
                sign,
            )

        if abs_result > _MAX_DELTA_NANOS:
            raise ValueError("Resulting TimeDelta out of range")
        return self._from_nanos_unchecked(abs_result * sign)

    @overload
    def add(self, other: TimeDelta, /) -> TimeDelta: ...

    @overload
    def add(
        self,
        /,
        *,
        hours: float = ...,
        minutes: float = ...,
        seconds: float = ...,
        milliseconds: float = ...,
        microseconds: float = ...,
        nanoseconds: int = ...,
    ) -> TimeDelta: ...

    def add(self, arg: TimeDelta = _UNSET, /, **kwargs: Any) -> TimeDelta:
        """Add time to this delta, returning a new delta"""
        if kwargs:
            if arg is not _UNSET:
                raise TypeError("Cannot mix positional and keyword arguments")
            return self + TimeDelta(**kwargs)
        elif arg is not _UNSET:
            return self + arg
        else:
            return self

    @overload
    def subtract(self, other: TimeDelta, /) -> TimeDelta: ...

    @overload
    def subtract(
        self,
        /,
        *,
        hours: float = ...,
        minutes: float = ...,
        seconds: float = ...,
        milliseconds: float = ...,
        microseconds: float = ...,
        nanoseconds: int = ...,
    ) -> TimeDelta: ...

    def subtract(self, arg: TimeDelta = _UNSET, /, **kwargs: Any) -> TimeDelta:
        """Subtract time from this delta, returning a new delta"""
        if kwargs:
            if arg is not _UNSET:
                raise TypeError("Cannot mix positional and keyword arguments")
            return self - TimeDelta(**kwargs)
        elif arg is not _UNSET:
            return self - arg
        else:
            return self

    def __add__(self, other: TimeDelta) -> TimeDelta:
        """Add two deltas together

        >>> d = TimeDelta(hours=1, minutes=30)
        >>> d + TimeDelta(minutes=30)
        TimeDelta("PT2h")
        """
        if not isinstance(other, TimeDelta):
            return NotImplemented
        return TimeDelta(nanoseconds=self._total_ns + other._total_ns)

    def __sub__(self, other: TimeDelta) -> TimeDelta:
        """Subtract two deltas

        >>> d = TimeDelta(hours=1, minutes=30)
        >>> d - TimeDelta(minutes=30)
        TimeDelta("PT1h")
        """
        if not isinstance(other, TimeDelta):
            return NotImplemented
        return TimeDelta(nanoseconds=self._total_ns - other._total_ns)

    def __eq__(self, other: object) -> bool:
        """Compare for equality

        >>> d = TimeDelta(hours=1, minutes=30)
        >>> d == TimeDelta(minutes=90)
        True
        >>> d == TimeDelta(hours=2)
        False
        """
        if not isinstance(other, TimeDelta):
            return NotImplemented
        return self._total_ns == other._total_ns

    def __hash__(self) -> int:
        return hash(self._total_ns)

    def __lt__(self, other: TimeDelta) -> bool:
        if not isinstance(other, TimeDelta):
            return NotImplemented
        return self._total_ns < other._total_ns

    def __le__(self, other: TimeDelta) -> bool:
        if not isinstance(other, TimeDelta):
            return NotImplemented
        return self._total_ns <= other._total_ns

    def __gt__(self, other: TimeDelta) -> bool:
        if not isinstance(other, TimeDelta):
            return NotImplemented
        return self._total_ns > other._total_ns

    def __ge__(self, other: TimeDelta) -> bool:
        if not isinstance(other, TimeDelta):
            return NotImplemented
        return self._total_ns >= other._total_ns

    def __bool__(self) -> bool:
        """True if the value is non-zero

        >>> bool(TimeDelta())
        False
        >>> bool(TimeDelta(minutes=1))
        True
        """
        return bool(self._total_ns)

    def __mul__(self, other: float) -> TimeDelta:
        """Multiply by a number

        >>> d = TimeDelta(hours=1, minutes=30)
        >>> d * 2.5
        TimeDelta("PT3h45m")
        """
        if not isinstance(other, (int, float)):
            return NotImplemented
        return TimeDelta(nanoseconds=int(self._total_ns * other))

    def __rmul__(self, other: float) -> TimeDelta:
        return self * other

    def __neg__(self) -> TimeDelta:
        """Negate the value

        >>> d = TimeDelta(hours=1, minutes=30)
        >>> -d
        TimeDelta(-PT1h30m)
        """
        return TimeDelta(nanoseconds=-self._total_ns)

    def __pos__(self) -> TimeDelta:
        """Return the value unchanged

        >>> d = TimeDelta(hours=1, minutes=30)
        >>> +d
        TimeDelta("PT1h30m")
        """
        return self

    @overload
    def __truediv__(self, other: float) -> TimeDelta: ...

    @overload
    def __truediv__(self, other: TimeDelta) -> float: ...

    def __truediv__(self, other: float | TimeDelta) -> TimeDelta | float:
        """Divide by a number or another delta

        >>> d = TimeDelta(hours=1, minutes=30)
        >>> d / 2.5
        TimeDelta("PT36m")
        >>> d / TimeDelta(minutes=30)
        3.0

        Note
        ----
        Because TimeDelta is limited to nanosecond precision, the result of
        division may not be exact.
        """
        if isinstance(other, TimeDelta):
            return self._total_ns / other._total_ns
        elif isinstance(other, (int, float)):
            return TimeDelta(nanoseconds=int(self._total_ns / other))
        return NotImplemented

    def __floordiv__(self, other: TimeDelta) -> int:
        """Floor division by another delta

        >>> d = TimeDelta(hours=1, minutes=39)
        >>> d // time_delta(minutes=15)
        6
        """
        if not isinstance(other, TimeDelta):
            return NotImplemented
        return self._total_ns // other._total_ns

    def __mod__(self, other: TimeDelta) -> TimeDelta:
        """Modulo by another delta

        >>> d = TimeDelta(hours=1, minutes=39)
        >>> d % TimeDelta(minutes=15)
        TimeDelta("PT9m")
        """
        if not isinstance(other, TimeDelta):
            return NotImplemented
        return TimeDelta(nanoseconds=self._total_ns % other._total_ns)

    def __abs__(self) -> TimeDelta:
        """The absolute value

        >>> d = TimeDelta(hours=-1, minutes=-30)
        >>> abs(d)
        TimeDelta("PT1h30m")
        """
        return TimeDelta._from_nanos_unchecked(abs(self._total_ns))

    __str__ = format_iso

    def __repr__(self) -> str:
        iso = self.format_iso()
        # lowercase everything besides the prefix (don't forget the sign!)
        cased = iso[:3] + iso[3:].lower()
        return f'TimeDelta("{cased}")'

    @no_type_check
    def __reduce__(self):
        return _unpkl_tdelta, (
            pack("<qI", *divmod(self._total_ns, 1_000_000_000)),
        )

    @classmethod
    def _from_nanos_unchecked(cls, ns: int) -> TimeDelta:
        new = _object_new(cls)
        new._total_ns = ns
        return new


# A separate unpickling function allows us to make backwards-compatible changes
# to the pickling format in the future
@no_type_check
def _unpkl_tdelta(data: bytes) -> TimeDelta:
    s, ns = unpack("<qI", data)
    return TimeDelta(seconds=s, nanoseconds=ns)


_DELTA_ITEMS_NS = {
    "weeks": 1_000_000_000 * 60 * 60 * 24 * 7,
    "days": 1_000_000_000 * 60 * 60 * 24,
    "hours": 1_000_000_000 * 60 * 60,
    "minutes": 1_000_000_000 * 60,
    "seconds": 1_000_000_000,
    "nanoseconds": 1,
}


TimeDelta.ZERO = TimeDelta()
TimeDelta.MAX = TimeDelta(seconds=9999 * 366 * 24 * 3_600)
TimeDelta.MIN = TimeDelta(seconds=-9999 * 366 * 24 * 3_600)


@final
class DateDelta(_Base):
    """A duration of time consisting of calendar units
    (years, months, weeks, and days).

    .. deprecated:: 0.10.0

        Use :class:`ItemizedDateDelta` instead.
        ``DateDelta`` normalizes its inputs (e.g. 14 months becomes
        1 year and 2 months), losing the original fields.
        ``ItemizedDateDelta`` preserves the exact fields it was created with.
    """

    __slots__ = ("_months", "_days")

    # Overloads for a nice autodoc.
    # Proper typing of the constructors is handled in the type stubs
    if not TYPE_CHECKING:

        @overload
        def __init__(self, iso_string: str, /) -> None: ...

        @overload
        def __init__(
            self,
            *,
            years: int = ...,
            months: int = ...,
            weeks: int = ...,
            days: int = ...,
        ) -> None: ...

    def __init__(
        self, *, years: int = 0, months: int = 0, weeks: int = 0, days: int = 0
    ) -> None:
        months = self._months = months + 12 * years
        days = self._days = days + 7 * weeks
        if (months > 0 and days < 0) or (months < 0 and days > 0):
            raise ValueError("Mixed sign in date delta")
        elif (
            abs(self._months) > _MAX_DELTA_MONTHS
            or abs(self._days) > _MAX_DELTA_DAYS
        ):
            raise ValueError("Date delta months out of range")

    __init__ = add_alternate_constructors(__init__)

    ZERO: ClassVar[DateDelta]
    """A delta of zero"""
    _time_part = TimeDelta.ZERO

    @property
    def _date_part(self) -> DateDelta:
        return self

    def in_months_days(self) -> tuple[int, int]:
        """Convert to a tuple of months and days.

        >>> p = DateDelta(months=25, days=9)
        >>> p.in_months_days()
        (25, 9)
        >>> DateDelta(months=-13, weeks=-5)
        (-13, -35)
        """
        return self._months, self._days

    def in_years_months_days(self) -> tuple[int, int, int]:
        """Convert to a tuple of years, months, and days.

        >>> p = DateDelta(years=1, months=2, days=11)
        >>> p.in_years_months_days()
        (1, 2, 11)
        """
        years = int(self._months / 12)
        months = int(fmod(self._months, 12))
        return years, months, self._days

    def format_iso(self) -> str:
        """Format as the *popular interpretation* of the ISO 8601 duration format.
        May not strictly adhere to (all versions of) the standard.
        See :ref:`here <iso8601-durations>` for more information.

        Inverse of :meth:`parse_iso`.

        >>> p = DateDelta(years=1, months=2, weeks=3, days=11)
        >>> p.format_iso()
        'P1Y2M3W11D'
        >>> DateDelta().format_iso()
        'P0D'

        The format looks like this:

        .. code-block:: text

            P(nY)(nM)(nD)

        For example:

        .. code-block:: text

            P1D
            P2M
            P1Y2M3W4D

        """
        if self._months < 0 or self._days < 0:
            sign = "-"
            months, days = -self._months, -self._days
        else:
            sign = ""
            months, days = self._months, self._days

        years = months // 12
        months %= 12

        date = (
            f"{years}Y" * bool(years),
            f"{months}M" * bool(months),
            f"{days}D" * bool(days),
        )
        return sign + "P" + ("".join(date) or "0D")

    __str__ = format_iso

    def _init_from_iso(self, s: str) -> None:
        exc = ValueError(f"Invalid format: {s!r}")
        prev_unit = ""
        months = 0
        days = 0

        if len(s) < 3 or not s.isascii():
            raise exc

        s = s.upper()
        if s[0] == "P":
            sign = 1
            rest = s[1:]
        elif s.startswith("-P"):
            sign = -1
            rest = s[2:]
        elif s.startswith("+P"):
            sign = 1
            rest = s[2:]
        else:
            raise exc

        while rest:
            rest, value, unit = _parse_datedelta_component(rest, exc)

            if unit == "Y" and prev_unit == "":
                months += value * 12
            elif unit == "M" and prev_unit in "Y":
                months += value
            elif unit == "W" and prev_unit in "YM":
                days += value * 7
            elif unit == "D" and prev_unit in "YMW":
                days += value
                if rest:
                    raise exc  # leftover characters
                break
            else:
                raise exc  # components out of order

            prev_unit = unit

        if months > _MAX_DELTA_MONTHS or days > _MAX_DELTA_DAYS:
            raise ValueError("DateDelta out of range")

        self._months = sign * months
        self._days = sign * days

    @classmethod
    def parse_iso(cls, s: str, /) -> DateDelta:
        """Parse the *popular interpretation* of the ISO 8601 duration format.
        Does not parse all possible ISO 8601 durations.
        See :ref:`here <iso8601-durations>` for more information.

        Inverse of :meth:`format_iso`

        >>> DateDelta.parse_iso("P1W11D")
        DateDelta("P1w11d")
        >>> DateDelta.parse_iso("-P3m")
        DateDelta(-P3m)

        Note
        ----
        Only durations without time component are accepted.
        ``P0D`` is valid, but ``PT0S`` is not.

        Note
        ----
        The number of digits in each component is limited to 8.
        """
        self = _object_new(cls)
        self._init_from_iso(s)
        return self

    @overload
    def __add__(self, other: DateDelta) -> DateDelta: ...

    @overload
    def __add__(self, other: TimeDelta) -> DateTimeDelta: ...

    def __add__(
        self, other: DateDelta | TimeDelta
    ) -> DateDelta | DateTimeDelta:
        """Add the fields of another delta to this one

        >>> p = DateDelta(weeks=2, months=1)
        >>> p + DateDelta(weeks=1, days=4)
        DateDelta("P1m25d")
        """
        if isinstance(other, DateDelta):
            return DateDelta(
                months=self._months + other._months,
                days=self._days + other._days,
            )
        elif isinstance(other, TimeDelta):
            new = _object_new(DateTimeDelta)
            new._date_part = self
            new._time_part = other
            return new
        else:
            return NotImplemented

    def __radd__(self, other: TimeDelta) -> DateTimeDelta:
        if isinstance(other, TimeDelta):
            new = _object_new(DateTimeDelta)
            new._date_part = self
            new._time_part = other
            return new
        return NotImplemented

    @overload
    def __sub__(self, other: DateDelta) -> DateDelta: ...

    @overload
    def __sub__(self, other: TimeDelta) -> DateTimeDelta: ...

    def __sub__(
        self, other: DateDelta | TimeDelta
    ) -> DateDelta | DateTimeDelta:
        """Subtract the fields of another delta from this one

        >>> p = DateDelta(weeks=2, days=3)
        >>> p - DateDelta(days=2)
        DateDelta("P15d")
        """
        if isinstance(other, DateDelta):
            return DateDelta(
                months=self._months - other._months,
                days=self._days - other._days,
            )
        elif isinstance(other, TimeDelta):
            return self + (-other)
        else:
            return NotImplemented

    def __rsub__(self, other: TimeDelta) -> DateTimeDelta:
        if isinstance(other, TimeDelta):
            return -self + other
        return NotImplemented

    def __eq__(self, other: object) -> bool:
        """Compare for equality, normalized to months and days.

        `a == b` is equivalent to `a.in_months_days() == b.in_months_days()`

        >>> p = DateDelta(weeks=4, days=2)
        DateDelta("P30d")
        >>> p == DateDelta(weeks=3, days=9)
        True
        >>> p == DateDelta(weeks=2, days=4)
        True  # same number of days
        >>> p == DateDelta(months=1)
        False  # months and days cannot be compared directly
        """
        if not isinstance(other, DateDelta):
            return NotImplemented
        return self._months == other._months and self._days == other._days

    def __hash__(self) -> int:
        return hash((self._months, self._days))

    def __bool__(self) -> bool:
        """True if any contains any non-zero data

        >>> bool(DateDelta())
        False
        >>> bool(DateDelta(days=-1))
        True
        """
        return bool(self._months or self._days)

    def __repr__(self) -> str:
        iso = self.format_iso()
        # lowercase everything besides the prefix (don't forget the sign!)
        cased = iso[:2] + iso[2:].lower()
        return f'DateDelta("{cased}")'

    def __neg__(self) -> DateDelta:
        """Negate the contents

        >>> p = DateDelta(weeks=2, days=3)
        >>> -p
        DateDelta(-P17d)
        """
        return DateDelta(months=-self._months, days=-self._days)

    def __pos__(self) -> DateDelta:
        """Return the value unchanged

        >>> p = DateDelta(weeks=2, days=-3)
        DateDelta("P11d")
        >>> +p
        DateDelta("P11d")
        """
        return self

    def __mul__(self, other: int) -> DateDelta:
        """Multiply the contents by a round number

        >>> p = DateDelta(years=1, weeks=2)
        >>> p * 2
        DateDelta("P2y28d")
        """
        if not isinstance(other, int):
            return NotImplemented
        return DateDelta(
            months=self._months * other,
            days=self._days * other,
        )

    def __rmul__(self, other: int) -> DateDelta:
        if isinstance(other, int):
            return self * other
        return NotImplemented

    def __abs__(self) -> DateDelta:
        """If the contents are negative, return the positive version

        >>> p = DateDelta(months=-2, days=-3)
        >>> abs(p)
        DateDelta("P2m3d")
        """
        return DateDelta(months=abs(self._months), days=abs(self._days))

    @no_type_check
    def __reduce__(self):
        return (_unpkl_ddelta, (self._months, self._days))


# A separate unpickling function allows us to make backwards-compatible changes
# to the pickling format in the future
def _unpkl_ddelta(months: int, days: int) -> DateDelta:
    return DateDelta(months=months, days=days)


_MAX_DDELTA_DIGITS = 8  # consistent with Rust extension


# Returns (rest_of_string, value, unit), e.g. ("3D", 2, "Y")
def _parse_datedelta_component(s: str, exc: Exception) -> tuple[str, int, str]:
    try:
        split_index, unit = next(
            (i, c) for i, c in enumerate(s) if c in "YMWD"
        )
    except StopIteration:
        raise exc

    raw, rest = s[:split_index], s[split_index + 1 :]

    if not raw.isdigit() or len(raw) > _MAX_DDELTA_DIGITS:
        raise exc

    return rest, int(raw), unit


DateDelta.ZERO = DateDelta()
TimeDelta._date_part = DateDelta.ZERO


@final
class ItemizedDelta(_Base, Mapping[DeltaUnitStr, int]):
    """A duration that preserves the exact fields it was created with.
    It closely models the ISO 8601 duration format for durations.

    >>> d = ItemizedDelta(weeks=2, days=3, hours=14)
    ItemizedDelta("P2w3dT14h")
    >>> d = ItemizedDelta("P2w3dT14h")
    >>> str(d)
    'P2w3dT14h'

    It behaves like a mapping where the keys are
    the unit names and the values are the amounts:

    >>> d['weeks']
    2
    >>> d.get('minutes')
    None
    >>> dict(d)
    {"weeks": 2, "days": 3, "hours": 14}
    >>> list(d.keys())
    ["weeks", "days", "hours"]
    >>> weeks, days, hours = d.values()
    (2, 3, 14)

    ``ItemizedDelta`` also supports other dictionary-like operations:

    >>> "months" in d  # check for presence of a field
    False
    >>> len(d)  # number of fields set
    3

    Zero values are considered distinct from "missing" values:

    >>> d2 = ItemizedDelta(years=2, weeks=3, hours=0)
    >>> dict(d2)
    {"years": 2, "weeks": 3, "hours": 0}

    Additionally, no normalization is performed.
    Months are not rolled into years, minutes into hours, etc.

    >>> d3 = ItemizedDelta(months=24, minutes=90)
    ItemizedDelta("P24mT90m")

    Empty durations are not allowed. At least one field must be set (but it can be zero):

    >>> ItemizedDelta()
    ValueError: At least one field must be set
    >>> ItemizedDelta(seconds=0)
    ItemizedDelta("PT0s")

    Negative durations are supported, but all fields must have the same sign:

    >>> d4 = ItemizedDelta(years=-1, weeks=-2, days=0)
    ItemizedDelta("-P1y2w0d")
    >>> ItemizedDelta(years=1, days=-3)
    ValueError: All fields must have the same sign

    Note
    ----
    Unlike :class:`TimeDelta`, ``ItemizedDelta`` does not normalize
    its fields. This means that ``ItemizedDelta(hours=90)`` and
    ``ItemizedDelta(days=3, hours=18)`` are considered different values.
    To convert to a normalized form, use :meth:`in_units`.
    See also the `delta documentation <https://whenever.rtfd.io/en/latest/guide/deltas.html>`_.
    """

    __slots__ = (
        "_sign",
        # Values are stored as positive integers or None. The sign
        # is stored separately (all fields must have the same sign).
        "_years",
        "_months",
        "_weeks",
        "_days",
        "_hours",
        "_minutes",
        "_seconds",
        # FUTURE: allow nanoseconds to exceed 999,999,999?
        "_nanoseconds",
    )

    def __init__(
        self,
        *,
        years: int = _UNSET,
        months: int = _UNSET,
        weeks: int = _UNSET,
        days: int = _UNSET,
        hours: int = _UNSET,
        minutes: int = _UNSET,
        seconds: int = _UNSET,
        nanoseconds: int = _UNSET,
    ) -> None:
        sign: Sign = 0
        if nanoseconds is not _UNSET and seconds is _UNSET:
            seconds = 0

        self._years, sign = _check_component(years, sign, _MAX_DELTA_YEARS)
        self._months, sign = _check_component(months, sign, _MAX_DELTA_MONTHS)
        self._weeks, sign = _check_component(weeks, sign, _MAX_DELTA_WEEKS)
        self._days, sign = _check_component(days, sign, _MAX_DELTA_DAYS)
        self._hours, sign = _check_component(hours, sign, _MAX_DELTA_HOURS)
        self._minutes, sign = _check_component(
            minutes, sign, _MAX_DELTA_MINUTES
        )
        self._seconds, sign = _check_component(
            seconds, sign, _MAX_DELTA_SECONDS
        )
        self._nanoseconds, sign = _check_component(
            nanoseconds, sign, _MAX_SUBSEC_NANOS
        )
        self._sign: Sign = sign
        if (
            self._sign == 0
            and years is _UNSET
            and months is _UNSET
            and weeks is _UNSET
            and days is _UNSET
            and hours is _UNSET
            and minutes is _UNSET
            and seconds is _UNSET
            and nanoseconds is _UNSET
        ):
            # This is to ensure ISO8601 formatting/parsing is round-trip safe.
            # There is no "empty" duration in ISO8601; at least one field must be present.
            raise ValueError(
                "At least one field of a ItemizedDelta must be set"
            )

    @property
    def sign(self) -> Sign:
        """The sign of the delta, 1, 0, or -1"""
        return self._sign

    # FUTURE: a float_seconds method that combines seconds and nanoseconds into a single float value?

    def __iter__(self) -> Iterator[DeltaUnitStr]:
        """Iterate over all non-missing fields, ordered from largest to smallest unit."""
        if self._years is not None:
            yield "years"
        if self._months is not None:
            yield "months"
        if self._weeks is not None:
            yield "weeks"
        if self._days is not None:
            yield "days"
        if self._hours is not None:
            yield "hours"
        if self._minutes is not None:
            yield "minutes"
        if self._seconds is not None:
            yield "seconds"
        if self._nanoseconds is not None:
            yield "nanoseconds"

    # These methods defer to the base class implementations, but need to be
    # documented here for the API docs.
    if not TYPE_CHECKING:  # pragma: no cover
        if SPHINX_RUNNING:

            def keys(self) -> KeysView[DeltaUnitStr]:
                """The names of all defined fields, in order of largest to smallest unit.

                Part of the mapping protocol
                """
                ...

            # FUTURE: an optimized ValuesView class that defers to the internal
            # fields directly instead of going through __getitem__
            def values(self) -> ValuesView[int]:
                """Return all defined field values, in order
                of largest to smallest unit.

                >>> d = ItemizedDelta(years=3, hours=12, days=0)
                >>> years, days, hours = d.values()
                (3, 0, 12)
                >>> list(d.values())
                [3, 0, 12]

                Part of the mapping protocol
                """
                ...

            def items(self) -> ItemsView[DeltaUnitStr, int]:
                """Return all defined fields as (unit, value) pairs
                ordered from largest to smallest unit.

                >>> d = ItemizedDelta(years=3, hours=12, days=0)
                >>> list(d.items())
                [('years', 3), ('days', 0), ('hours', 12)]

                Part of the mapping protocol
                """
                ...

            @overload
            def get(self, key: DeltaUnitStr, /) -> Optional[int]: ...

            @overload
            def get(self, key: DeltaUnitStr, default: int, /) -> int: ...

            def get(
                self, key: DeltaUnitStr, default: object = None, /
            ) -> object:
                """Get the value of a specific field by name, or return default if not set.

                Part of the mapping protocol
                """
                ...

    def __getitem__(self, key: str) -> int:
        """Get the value of a specific field by name.

        >>> d = ItemizedDelta(weeks=1, days=3)
        >>> d["weeks"]
        1
        >>> d["days"]
        3
        >>> d["hours"]
        KeyError: 'hours'
        """
        match key:
            case "years":
                value = self._years
            case "months":
                value = self._months
            case "weeks":
                value = self._weeks
            case "days":
                value = self._days
            case "hours":
                value = self._hours
            case "minutes":
                value = self._minutes
            case "seconds":
                value = self._seconds
            case "nanoseconds":
                value = self._nanoseconds
            case _:
                raise KeyError(key)

        if value is not None:
            return self._sign * value

        raise KeyError(key)

    def __len__(self) -> int:
        """Get the number of fields that are set.

        >>> d = ItemizedDelta(weeks=1, days=3)
        >>> len(d)
        2
        """
        return (
            (self._years is not None)
            + (self._months is not None)
            + (self._weeks is not None)
            + (self._days is not None)
            + (self._hours is not None)
            + (self._minutes is not None)
            + (self._seconds is not None)
            + (self._nanoseconds is not None)
        )

    def __contains__(self, key: object) -> bool:
        """Check if a specific field is set.

        >>> d = ItemizedDelta(weeks=1, days=3)
        >>> "weeks" in d
        True
        >>> "hours" in d
        False
        """
        if key == "years":
            return self._years is not None
        elif key == "months":
            return self._months is not None
        elif key == "weeks":
            return self._weeks is not None
        elif key == "days":
            return self._days is not None
        elif key == "hours":
            return self._hours is not None
        elif key == "minutes":
            return self._minutes is not None
        elif key == "seconds":
            return self._seconds is not None
        elif key == "nanoseconds":
            return self._nanoseconds is not None
        return False

    def __bool__(self) -> bool:
        """An ItemizedDelta is considered False if its sign is 0.

        >>> bool(ItemizedDelta(weeks=0))
        False
        >>> bool(ItemizedDelta(weeks=1))
        True
        """
        return bool(self._sign)

    def format_iso(self, *, lowercase_units: bool = False) -> str:
        """Format as the *popular interpretation* of the ISO 8601 duration format.
        May not strictly adhere to (all versions of) the standard.
        See :ref:`here <iso8601-durations>` for more information.

        Inverse of :meth:`parse_iso`.

        The format is:

        .. code-block:: text

            P(nY)(nM)(nW)(nD)T(nH)(nM)(nS)

        >>> d = ItemizedDelta(
        ...     weeks=1,
        ...     days=11,
        ...     hours=4,
        ...     seconds=1,
        ...     nanoseconds=12_000,
        ... )
        >>> d.format_iso()
        'P1W11DT4H1.000012S'
        """
        # Mypy complains about string unpacking. But it's valid here. See mypy/issues/13823
        y, m, w, d, h, s = "ymwdhs" if lowercase_units else "YMWDHS"  # type: ignore[misc]

        parts = ["-" * (self._sign == -1), "P"]
        if self._years is not None:
            parts.append(f"{self._years}{y}")
        if self._months is not None:
            parts.append(f"{self._months}{m}")
        if self._weeks is not None:
            parts.append(f"{self._weeks}{w}")
        if self._days is not None:
            parts.append(f"{self._days}{d}")

        parts.append("T")

        if self._hours is not None:
            parts.append(f"{self._hours}{h}")
        if self._minutes is not None:
            parts.append(f"{self._minutes}{m}")
        if self._seconds is not None:
            if self._nanoseconds is None:
                parts.append(f"{self._seconds}{s}")
            elif self._nanoseconds:
                parts.append(
                    f"{self._seconds}.{self._nanoseconds:09d}".rstrip("0") + s
                )
            else:
                parts.append(f"{self._seconds}.0{s}")

        joined = "".join(parts)
        if joined.endswith("T"):  # skip the T if no time fields
            return joined[:-1]
        # NOTE: we always have at least one field,
        # so we don't need to check for "empty" durations.
        return joined

    @classmethod
    def parse_iso(cls, s: str, /) -> ItemizedDelta:
        """Parse the *popular interpretation* of the ISO 8601 duration format.
        Does not parse all possible ISO 8601 durations.
        See :ref:`here <iso8601-durations>` for more information.

        .. code-block:: text

           P4D        # 4 days
           PT4H       # 4 hours
           PT0M       # 0 minutes
           PT3M40.5S  # 3 minutes and 40.5 seconds
           P1W11DT90M # 1 week, 11 days, and 90 minutes
           -PT7H400M  # -7 hours and -400 minutes
           +PT7H4M    # 7 hours and 4 minutes (7:04:00)

        Inverse of :meth:`format_iso`

        >>> ItemizeDelta.parse_iso("-P1W11DT4H")
        ItemizeDelta("-P1w11dT4h")
        """
        exc = ValueError(f"Invalid format: {s!r}")
        prev_unit = ""
        years, months, weeks, days, hours, minutes, seconds, nanos = (
            None,
        ) * 8

        # Catch certain invalid strings early, making parsing easier
        if len(s) < 3 or not s.isascii() or s.endswith("T"):
            raise exc

        sign: Sign
        s = s.upper()
        if s[0] == "P":
            sign = 1
            rest = s[1:]
        elif s.startswith("-P"):
            sign = -1
            rest = s[2:]
        elif s.startswith("+P"):
            sign = 1
            rest = s[2:]
        else:
            raise exc

        # parse the date part
        while rest and not rest.startswith("T"):
            rest, value, unit = _parse_datedelta_component(rest, exc)

            if unit == "Y" and prev_unit == "":
                years = value
            elif unit == "M" and prev_unit in "Y":
                months = value
            elif unit == "W" and prev_unit in "YM":
                weeks = value
            elif unit == "D" and prev_unit in "YMW":
                days = value
                break
            else:
                raise exc  # components out of order

            prev_unit = unit

        prev_unit = ""
        if rest and not rest.startswith("T"):
            raise exc

        # skip the "T" separator
        rest = rest[1:]

        while rest:
            rest_new, value, unit = parse_timedelta_component(rest, exc)

            if unit == "H" and prev_unit == "":
                hours = value
            elif unit == "M" and prev_unit in "H":
                minutes = value
            elif unit == "S":
                seconds = value // 1_000_000_000
                # Only set nanos if there are fractional digits
                if "," in rest or "." in rest:
                    nanos = value % 1_000_000_000
                if rest_new:
                    raise exc
                break
            else:
                raise exc

            rest = rest_new
            prev_unit = unit

        if not (
            years
            or months
            or weeks
            or days
            or hours
            or minutes
            or seconds
            or nanos
        ):
            sign = 0

        # NOTE: we've implicitly validated that at least one field is set
        return cls._from_signed(
            sign,
            years,
            months,
            weeks,
            days,
            hours,
            minutes,
            seconds,
            nanos,
        )

    def parts(self) -> tuple[Optional[ItemizedDateDelta], Optional[TimeDelta]]:
        """Split into date and time parts.

        Either part may be None if no fields were set of that type.
        At least one part will be non-None, since at least one field must be set.

        >>> d = ItemizedDelta(
        ...     years=1,
        ...     months=2,
        ...     weeks=3,
        ...     days=4,
        ...     hours=5,
        ...     minutes=6,
        ...     seconds=7,
        ...     nanoseconds=8,
        ... )
        >>> date_part, time_part = d.parts()
        >>> date_part
        ItemizedDateDelta("P1y2m3w4d")
        >>> time_part
        TimeDelta("P5h6m7.000000008s")
        >>> ItemizedDelta(weeks=2).parts()
        (ItemizedDateDelta("P2w"), None)

        """
        years, months, weeks, days = date_values = (
            self._years,
            self._months,
            self._weeks,
            self._days,
        )
        if all(v is None for v in date_values):
            date_part = None
        else:
            date_part = ItemizedDateDelta._from_signed(
                self._sign if any(date_values) else 0,
                years=years,
                months=months,
                weeks=weeks,
                days=days,
            )

        hours, minutes, seconds, nanoseconds = time_values = (
            self._hours,
            self._minutes,
            self._seconds,
            self._nanoseconds,
        )
        if all(v is None for v in time_values):
            time_part = None
        else:
            time_part = TimeDelta(
                hours=hours or 0,
                minutes=minutes or 0,
                seconds=seconds or 0,
                nanoseconds=nanoseconds or 0,
            )
            if self._sign == -1:
                time_part = -time_part
        return date_part, time_part

    # A private constructor. Checks bounds but *not* signs or presence of > 0 fields.
    @classmethod
    def _from_signed(
        cls,
        sign: Sign,
        years: int | None = None,
        months: int | None = None,
        weeks: int | None = None,
        days: int | None = None,
        hours: int | None = None,
        minutes: int | None = None,
        seconds: int | None = None,
        nanoseconds: int | None = None,
    ) -> ItemizedDelta:
        self = _object_new(cls)
        self._sign = sign
        self._years = _check_bound(years, _MAX_DELTA_YEARS)
        self._months = _check_bound(months, _MAX_DELTA_MONTHS)
        self._weeks = _check_bound(weeks, _MAX_DELTA_WEEKS)
        self._days = _check_bound(days, _MAX_DELTA_DAYS)
        self._hours = _check_bound(hours, _MAX_DELTA_HOURS)
        self._minutes = _check_bound(minutes, _MAX_DELTA_MINUTES)
        self._seconds = _check_bound(seconds, _MAX_DELTA_SECONDS)
        self._nanoseconds = _check_bound(nanoseconds, _MAX_SUBSEC_NANOS)
        # Sanity check: if the sign is 0, all fields must be 0 or None
        if (
            years
            or months
            or weeks
            or days
            or hours
            or minutes
            or seconds
            or nanoseconds
        ):
            assert sign != 0
        else:
            assert sign == 0
        return self

    def __eq__(self, other: object) -> bool:
        """Compare for equality. Each field is individually compared.
        No normalization is performed. Zero values are considered equivalent
        to missing values.

        Thus, ``ItemizedDelta(weeks=1, seconds=0) == ItemizedDelta(weeks=1)``

        >>> d = ItemizedDelta(weeks=2, minutes=90)
        >>> d == ItemizedDelta(weeks=2, minutes=90)
        True
        >>> d == ItemizedDelta(weeks=2, minutes=91)
        False

        If you want strict equality (including presence of fields),
        use :meth:`exact_eq`.

        """
        if not isinstance(other, ItemizedDelta):
            return NotImplemented
        return (
            self._sign == other._sign
            and (self._years or 0) == (other._years or 0)
            and (self._months or 0) == (other._months or 0)
            and (self._weeks or 0) == (other._weeks or 0)
            and (self._days or 0) == (other._days or 0)
            and (self._hours or 0) == (other._hours or 0)
            and (self._minutes or 0) == (other._minutes or 0)
            and (self._seconds or 0) == (other._seconds or 0)
            and (self._nanoseconds or 0) == (other._nanoseconds or 0)
        )

    def exact_eq(self, other: ItemizedDelta, /) -> bool:
        """Check for strict equality. All fields *and their presence* must match."""
        return (
            self._sign == other._sign
            and self._years == other._years
            and self._months == other._months
            and self._weeks == other._weeks
            and self._days == other._days
            and self._hours == other._hours
            and self._minutes == other._minutes
            and self._seconds == other._seconds
            and self._nanoseconds == other._nanoseconds
        )

    def __abs__(self) -> ItemizedDelta:
        """If the contents are negative, return the positive version

        >>> d = ItemizedDelta(weeks=-2, days=-3)
        >>> abs(d)
        ItemizedDelta("P2w3d")
        """
        if self._sign >= 0:
            return self
        return ItemizedDelta._from_signed(
            1,
            self._years,
            self._months,
            self._weeks,
            self._days,
            self._hours,
            self._minutes,
            self._seconds,
            self._nanoseconds,
        )

    def __neg__(self) -> ItemizedDelta:
        """Invert the sign of the contents

        >>> d = ItemizedDelta(weeks=2, days=3)
        >>> -d
        ItemizedDelta("-P2w3d")
        >>> --d
        ItemizedDelta("P2w3d")
        """
        if self._sign == 0:
            return self
        return ItemizedDelta._from_signed(
            -self._sign,
            self._years,
            self._months,
            self._weeks,
            self._days,
            self._hours,
            self._minutes,
            self._seconds,
            self._nanoseconds,
        )

    @overload
    def add(
        self,
        other: ItemizedDelta,
        /,
        *,
        relative_to: ZonedDateTime,
        units: Sequence[DeltaUnitStr] = ...,
        round_mode: RoundModeStr = ...,
        round_increment: int = ...,
    ) -> ItemizedDelta: ...

    @overload
    def add(
        self,
        /,
        *,
        years: int = ...,
        months: int = ...,
        weeks: int = ...,
        days: int = ...,
        hours: int = ...,
        minutes: int = ...,
        seconds: int = ...,
        nanoseconds: int = ...,
        relative_to: ZonedDateTime,
        units: Sequence[DeltaUnitStr] = ...,
        round_mode: RoundModeStr = ...,
        round_increment: int = ...,
    ) -> ItemizedDelta: ...

    def add(
        self,
        arg: ItemizedDelta = _UNSET,
        /,
        *,
        relative_to: ZonedDateTime,
        units: Sequence[DeltaUnitStr] = _UNSET,
        round_mode: RoundModeStr = "trunc",
        round_increment: int = 1,
        **kwargs: Any,
    ) -> ItemizedDelta:
        """Add time to this delta, returning a new delta"""
        if kwargs:
            if arg is not _UNSET:
                raise TypeError("Cannot mix positional and keyword arguments")
        elif arg is not _UNSET:
            # In this case the mapping types are interchangeable
            kwargs = arg  # type: ignore[assignment]
        else:
            return self

        units = cast(
            Sequence[DeltaUnitStr],
            (
                sorted(
                    kwargs.keys() | self.keys(),
                    key=lambda u: _unit_index(u, DELTA_UNITS),
                )
                if units is _UNSET
                else units
            ),
        )

        return (
            relative_to.add(self)
            .add(**kwargs)
            .since(
                relative_to,
                units=units,
                round_mode=round_mode,
                round_increment=round_increment,
            )
        )

    @overload
    def subtract(
        self,
        other: ItemizedDelta,
        /,
        *,
        relative_to: ZonedDateTime,
        units: Sequence[DeltaUnitStr] = ...,
        round_mode: RoundModeStr = ...,
        round_increment: int = ...,
    ) -> ItemizedDelta: ...

    @overload
    def subtract(
        self,
        /,
        *,
        years: int = ...,
        months: int = ...,
        weeks: int = ...,
        days: int = ...,
        hours: int = ...,
        minutes: int = ...,
        seconds: int = ...,
        nanoseconds: int = ...,
        relative_to: ZonedDateTime,
        units: Sequence[DeltaUnitStr] = ...,
        round_mode: RoundModeStr = ...,
        round_increment: int = ...,
    ) -> ItemizedDelta: ...

    def subtract(
        self,
        arg: ItemizedDelta = _UNSET,
        /,
        *,
        relative_to: ZonedDateTime,
        units: Sequence[DeltaUnitStr] = _UNSET,
        round_mode: RoundModeStr = "trunc",
        round_increment: int = 1,
        **kwargs: Any,
    ) -> ItemizedDelta:
        """Inverse of :meth:`add`."""
        arg = -arg if arg is not _UNSET else _UNSET
        return self.add(
            arg,
            **{k: -v for k, v in kwargs.items()},
            relative_to=relative_to,
            units=units,
            round_mode=round_mode,
            round_increment=round_increment,
        )

    def in_units(
        self,
        units: Sequence[DeltaUnitStr],
        /,
        *,
        relative_to: ZonedDateTime,
        round_mode: RoundModeStr = "trunc",
        round_increment: int = 1,
    ) -> ItemizedDelta:
        """Convert this delta into the specified units. A `relative_to` datetime
        is required to resolve calendar units.

        >>> d = ItemizedDelta(years=1, months=8, minutes=1000)
        >>> d.in_units(["weeks", "hours"], relative_to=ZonedDateTime(2020, 6, 30, 12, tz="Asia/Tokyo"))
        ItemizedDelta("P86w160h")
        """
        return relative_to.add(self).since(
            relative_to,
            units=units,
            round_mode=round_mode,
            round_increment=round_increment,
        )

    def total(
        self, unit: DeltaUnitStr, /, *, relative_to: ZonedDateTime
    ) -> float:
        """Return the total duration expressed in the specified unit as a float"""
        return (relative_to.add(self) - relative_to).total(
            unit, relative_to=relative_to
        )

    if not TYPE_CHECKING:
        # This overload ensures it shows up nicely in the API docs, not just as "kwargs"
        @overload
        def replace(
            self,
            *,
            years: int | None = ...,
            months: int | None = ...,
            weeks: int | None = ...,
            days: int | None = ...,
            hours: int | None = ...,
            minutes: int | None = ...,
            seconds: int | None = ...,
            nanoseconds: int | None = ...,
        ) -> ItemizedDelta: ...

    def replace(self, **kwargs: int | None) -> ItemizedDelta:
        """Return a new delta with specific fields replaced.
        Fields set to ``None`` will be removed.

        All normal validation rules apply.

        >>> d = ItemizedDelta(years=1, months=2, hours=3)
        >>> d.replace(months=None, hours=2)
        ItemizedDelta("P1yT2h")
        """
        kwargs_w_sentinel = {
            k: _UNSET if v is None else v for k, v in kwargs.items()
        }
        fields = {**self, **kwargs_w_sentinel}
        return ItemizedDelta(**fields)

    @no_type_check
    def __reduce__(self):
        return (
            _unpkl_idelta,
            (
                self._sign,
                self._years,
                self._months,
                self._weeks,
                self._days,
                self._hours,
                self._minutes,
                self._seconds,
                self._nanoseconds,
            ),
        )

    def __repr__(self) -> str:
        return f'ItemizedDelta("{self.format_iso(lowercase_units=True)}")'


# A separate unpickling function allows us to make backwards-compatible changes
# to the pickling format in the future
def _unpkl_idelta(
    sign: Sign,
    years: Optional[int],
    months: Optional[int],
    weeks: Optional[int],
    days: Optional[int],
    hours: Optional[int],
    minutes: Optional[int],
    seconds: Optional[int],
    nanoseconds: Optional[int],
) -> ItemizedDelta:
    self = _object_new(ItemizedDelta)
    self._sign = sign
    self._years = years
    self._months = months
    self._weeks = weeks
    self._days = days
    self._hours = hours
    self._minutes = minutes
    self._seconds = seconds
    self._nanoseconds = nanoseconds
    return self


@final
class ItemizedDateDelta(_Base, Mapping[DateDeltaUnitStr, int]):
    """A date duration that preserves the exact fields it was created with.
    It closely models the ISO 8601 duration format for date-only durations.

    >>> d = ItemizedDateDelta(years=2, weeks=3)
    ItemizedDateDelta("P2Y3W")
    >>> d = ItemizedDateDelta("P22W")
    >>> str(d)
    'P22W'

    It behaves like a mapping where the keys are
    the unit names and the values are the amounts:

    >>> d['weeks']
    22
    >>> d.get('days')
    None
    >>> dict(d)
    {"years": 2, "weeks": 3}
    >>> list(d.keys())
    ["years", "weeks"]
    >>> years, weeks = d.values()
    (2, 3)

    ``ItemizedDateDelta`` also supports other dictionary-like operations:

    >>> "days" in d  # check for presence of a field
    False
    >>> len(d)  # number of fields set
    2

    Zero values are considered distinct from "missing" values:

    >>> d2 = ItemizedDateDelta(years=2, weeks=3, days=0)
    >>> dict(d2)
    {"years": 2, "weeks": 3, "days": 0}

    Additionally, no normalization is performed.
    Months are not rolled into years, weeks into days, etc.

    >>> d3 = ItemizedDateDelta(months=24, days=100)
    ItemizedDateDelta("P24m100d")

    Empty durations are not allowed. At least one field must be set (but it can be zero):

    >>> ItemizedDateDelta()
    ValueError: At least one field must be set
    >>> ItemizedDateDelta(days=0)
    ItemizedDateDelta("P0d")

    Negative durations are supported, but all fields must have the same sign:

    >>> d4 = ItemizedDateDelta(years=-1, weeks=-2, days=0)
    ItemizedDateDelta("-P1y2w0d")
    >>> ItemizedDateDelta(years=1, days=-3)
    ValueError: All fields must have the same sign

    Note
    ----
    Unlike :class:`DateDelta`, ``ItemizedDateDelta`` does not normalize
    its fields. This means that ``ItemizedDateDelta(months=14)`` and
    ``ItemizedDateDelta(years=1, months=2)`` are considered different values.
    To convert to a normalized form, use :meth:`in_units`.
    See also the `delta documentation <https://whenever.rtfd.io/en/latest/guide/deltas.html>`_.
    """

    __slots__ = (
        "_sign",
        # Values are stored as positive integers or None. The sign
        # is stored separately (all fields must have the same sign).
        "_years",
        "_months",
        "_weeks",
        "_days",
    )

    def __init__(
        self,
        *,
        years: int = _UNSET,
        months: int = _UNSET,
        weeks: int = _UNSET,
        days: int = _UNSET,
    ) -> None:
        sign: Sign = 0
        self._years, sign = _check_component(years, sign, _MAX_DELTA_YEARS)
        self._months, sign = _check_component(months, sign, _MAX_DELTA_MONTHS)
        self._weeks, sign = _check_component(weeks, sign, _MAX_DELTA_WEEKS)
        self._days, sign = _check_component(days, sign, _MAX_DELTA_DAYS)
        self._sign: Sign = sign
        if (
            self._sign == 0
            and years is _UNSET
            and months is _UNSET
            and weeks is _UNSET
            and days is _UNSET
        ):
            # This is to ensure ISO8601 formatting/parsing is round-trip safe.
            # There is no "empty" duration in ISO8601; at least one field must be present.
            raise ValueError("At least one field must be set")

    @property
    def sign(self) -> Sign:
        """The sign of the delta, whether it's positive, negative, or zero.

        >>> ItemizedDateDelta(weeks=2).sign
        1
        >>> ItemizedDateDelta(days=-3).sign
        -1
        >>> ItemizedDateDelta(weeks=0).sign
        0
        """
        return self._sign

    def in_units(
        self,
        units: Sequence[DateDeltaUnitStr],
        /,
        *,
        relative_to: Date,
        round_mode: RoundModeStr = "trunc",
        round_increment: int = 1,
    ) -> ItemizedDateDelta:
        """Convert this delta into the specified units. A `relative_to` date
        is required to resolve variable-length units (years and months).

        >>> d = ItemizedDateDelta(years=1, months=8)
        >>> d.in_units(["weeks", "days"], relative_to=Date(2020, 6, 30))
        ItemizedDateDelta("P86w6d")
        """
        return relative_to.add(self).since(
            relative_to,
            units=units,
            round_mode=round_mode,
            round_increment=round_increment,
        )

    if not TYPE_CHECKING:
        # This overload ensures it shows up nicely in the API docs, not just as "kwargs"
        @overload
        def replace(
            self,
            *,
            years: int | None = ...,
            months: int | None = ...,
            weeks: int | None = ...,
            days: int | None = ...,
        ) -> ItemizedDateDelta: ...

    def replace(self, **kwargs: int | None) -> ItemizedDateDelta:
        """Return a new delta with specific fields replaced.
        Fields set to ``None`` will be removed.

        All normal validation rules apply.

        >>> d = ItemizedDateDelta(years=1, months=2, weeks=3)
        >>> d.replace(months=None, weeks=4)
        ItemizedDateDelta("P1y4w")
        """
        kwargs_w_sentinel = {
            k: _UNSET if v is None else v for k, v in kwargs.items()
        }
        # Keys may be invalid here, but the constructor will catch that.
        fields = {**self, **kwargs_w_sentinel}  # type: ignore[misc]
        return ItemizedDateDelta(**fields)

    def format_iso(self, *, lowercase_units: bool = False) -> str:
        """Convert to the canionical ISO 8601 string representation:

        .. code-block:: text

            P(nY)(nM)(nW)(nD)

        You can also use ``str(d)`` which is equivalent to ``d.format_iso()``.

        Inverse of :meth:`parse_iso`.

        >>> d = ItemizedDateDelta(weeks=1, days=11)
        >>> d.format_iso()
        'P1W11D'

        Note
        ----
        Negative durations are prefixed with a minus sign,
        which is not part of the ISO 8601 standard, but is a common extension.
        See :ref:`here <iso8601-durations>` for more information.
        """
        # Mypy complains about string unpacking. But it's valid here. See mypy/issues/13823
        y, m, w, d = "ymwd" if lowercase_units else "YMWD"  # type: ignore[misc]

        parts = ["-" * (self._sign == -1), "P"]
        if self._years is not None:
            parts.append(f"{self._years}{y}")
        if self._months is not None:
            parts.append(f"{self._months}{m}")
        if self._weeks is not None:
            parts.append(f"{self._weeks}{w}")
        if self._days is not None:
            parts.append(f"{self._days}{d}")

        # NOTE: we always have at least one field,
        # so we don't need to check for "empty" durations.
        return "".join(parts)

    @classmethod
    def parse_iso(cls, s: str, /) -> ItemizedDateDelta:
        """Parse the *popular interpretation* of the ISO 8601 duration format.
        Inverse of :meth:`format_iso`

        >>> ItemizedDateDelta.parse_iso("-P1W11D")
        ItemizedDateDelta("-P1w11d")

        You can also use the constructor ``ItemizedDateDelta(s)`` which is
        equivalent to ``ItemizedDateDelta.parse_iso(s)``.

        Note
        ----
        Does not parse all possible ISO 8601 durations. In particular,
        it doesn't allow fractional values.
        See :ref:`here <iso8601-durations>` for more information.
        """
        exc = ValueError(f"Invalid format: {s!r}")

        # Catch certain invalid strings early, making parsing easier
        if len(s) < 3 or not s.isascii():
            raise exc

        sign: Sign
        s = s.upper()  # normalize to uppercase for parsing
        if s[0] == "P":
            sign = 1
            rest = s[1:]
        elif s.startswith("-P"):
            sign = -1
            rest = s[2:]
        elif s.startswith("+P"):
            sign = 1
            rest = s[2:]
        else:
            raise exc

        years, months, weeks, days = (None,) * 4
        prev_unit = ""
        while rest:
            rest, value, unit = _parse_datedelta_component(rest, exc)

            if unit == "Y" and prev_unit == "":
                years = value
            elif unit == "M" and prev_unit in "Y":
                months = value
            elif unit == "W" and prev_unit in "YM":
                weeks = value
            elif unit == "D" and prev_unit in "YMW":
                days = value
                break
            else:
                raise exc  # components out of order

            prev_unit = unit

        if rest:
            raise exc

        if not (years or months or weeks or days):
            sign = 0

        # NOTE: we've implicitly validated that at least one field is set
        return cls._from_signed(sign, years, months, weeks, days)

    # These methods defer to the base class implementations, but need to be
    # documented here for the API docs.
    if not TYPE_CHECKING:  # pragma: no cover
        if SPHINX_RUNNING:

            def keys(self) -> KeysView[DateDeltaUnitStr]:
                """The names of all defined fields, ordered from largest to smallest unit.

                Part of the mapping protocol
                """
                ...

            # FUTURE: an optimized ValuesView class that defers to the internal
            # fields directly instead of going through __getitem__
            def values(self) -> ValuesView[int]:
                """Return all defined field values, in order
                of largest to smallest unit.

                >>> d = ItemizedDateDelta(years=3, days=12, months=0)
                >>> years, months, days = d.values()
                (3, 0, 12)
                >>> list(d.values())
                [3, 0, 12]
                """
                ...

            def items(self) -> ItemsView[DateDeltaUnitStr, int]:
                """Return all defined fields as (unit, value) pairs
                ordered from largest to smallest unit.

                >>> d = ItemizedDateDelta(years=3, days=12, months=0)
                >>> list(d.items())
                [('years', 3), ('months', 0), ('days', 12)]
                """
                ...

            @overload
            def get(self, key: DateDeltaUnitStr, /) -> Optional[int]: ...

            @overload
            def get(self, key: DateDeltaUnitStr, default: int, /) -> int: ...

            def get(
                self, key: DateDeltaUnitStr, default: object = None, /
            ) -> object:
                """Get the value of a specific field by name, or return default if not set.

                Part of the mapping protocol
                """
                ...

    def __iter__(self) -> Iterator[DateDeltaUnitStr]:
        """Iterate over all unit names for fields that are set, ordered from largest to smallest unit."""
        if self._years is not None:
            yield "years"
        if self._months is not None:
            yield "months"
        if self._weeks is not None:
            yield "weeks"
        if self._days is not None:
            yield "days"

    def __getitem__(self, key: DateDeltaUnitStr) -> int:
        """Get the value of a specific field by name.

        >>> d = ItemizedDateDelta(weeks=1, days=0)
        >>> d["weeks"]
        1
        >>> d["days"]
        0
        >>> d["years"]
        KeyError: 'years'
        """
        match key:
            case "years":
                value = self._years
            case "months":
                value = self._months
            case "weeks":
                value = self._weeks
            case "days":
                value = self._days
            case _:
                raise KeyError(key)

        if value is not None:
            return self._sign * value

        raise KeyError(key)

    def __len__(self) -> int:
        """Get the number of fields that are set.

        >>> d = ItemizedDateDelta(weeks=1, days=0)
        >>> len(d)
        2
        """
        return (
            (self._years is not None)
            + (self._months is not None)
            + (self._weeks is not None)
            + (self._days is not None)
        )

    def __contains__(self, key: object) -> bool:
        """Check if a specific field is set.

        >>> d = ItemizedDateDelta(weeks=1, days=0)
        >>> "weeks" in d
        True
        >>> "days" in d
        True
        >>> "months" in d
        False
        """
        if key == "years":
            return self._years is not None
        elif key == "months":
            return self._months is not None
        elif key == "weeks":
            return self._weeks is not None
        elif key == "days":
            return self._days is not None
        return False

    def __bool__(self) -> bool:
        """An ItemizedDateDelta is considered False if its sign is 0.

        >>> d = ItemizedDateDelta(weeks=0)
        >>> bool(d)
        False
        >>> d = ItemizedDateDelta(weeks=1)
        >>> bool(d)
        True
        """
        return bool(self._sign)

    def __eq__(self, other: object) -> bool:
        """Compare each field for equality, under the following rules:

        - No normalization is performed. 1 hour is not equal to 60 minutes, etc.
        - Zero values are considered equivalent to missing values.

        If you want strict equality (including presence of fields),
        use :meth:`exact_eq`.

        >>> d = ItemizedDateDelta(weeks=2, minutes=90)
        >>> d == ItemizedDateDelta(weeks=2, minutes=90, seconds=0)
        True
        >>> d == ItemizedDateDelta(weeks=2, hour=1, minutes=30)
        False
        """
        if not isinstance(other, ItemizedDateDelta):
            return NotImplemented
        return (
            self._sign == other._sign
            and (self._years or 0) == (other._years or 0)
            and (self._months or 0) == (other._months or 0)
            and (self._weeks or 0) == (other._weeks or 0)
            and (self._days or 0) == (other._days or 0)
        )

    def exact_eq(self, other: ItemizedDateDelta, /) -> bool:
        """Check for strict equality. All fields *and their presence* must match.

        >>> d = ItemizedDateDelta(weeks=2, minutes=90)
        >>> d == ItemizedDateDelta(weeks=2, minutes=90)
        True
        >>> d == ItemizedDateDelta(weeks=2, minutes=90, seconds=0)
        False
        """
        return (
            self._sign == other._sign
            and self._years == other._years
            and self._months == other._months
            and self._weeks == other._weeks
            and self._days == other._days
        )

    def __abs__(self) -> ItemizedDateDelta:
        """If the contents are negative, return the positive version

        >>> d = ItemizedDateDelta(weeks=-2, days=-3)
        >>> abs(d)
        ItemizedDateDelta("P2w3d")
        """
        if self._sign >= 0:
            return self
        return ItemizedDateDelta._from_signed(
            1, self._years, self._months, self._weeks, self._days
        )

    def __neg__(self) -> ItemizedDateDelta:
        """Invert the sign of the contents

        >>> d = ItemizedDateDelta(weeks=2, days=3)
        >>> -d
        ItemizedDateDelta("-P2w3d")
        >>> --d
        ItemizedDateDelta("P2w3d")
        """
        if self._sign == 0:
            return self
        return ItemizedDateDelta._from_signed(
            -self._sign, self._years, self._months, self._weeks, self._days
        )

    @overload
    def add(
        self,
        other: ItemizedDateDelta,
        /,
        *,
        relative_to: Date,
        units: Sequence[DateDeltaUnitStr] = ...,
        round_mode: RoundModeStr = "trunc",
        round_increment: int = 1,
    ) -> ItemizedDateDelta: ...

    @overload
    def add(
        self,
        /,
        *,
        years: int = ...,
        months: int = ...,
        weeks: int = ...,
        days: int = ...,
        relative_to: Date,
        units: Sequence[DateDeltaUnitStr] = ...,
        round_mode: RoundModeStr = "trunc",
        round_increment: int = 1,
    ) -> ItemizedDateDelta: ...

    def add(
        self,
        arg: ItemizedDateDelta = _UNSET,
        /,
        *,
        relative_to: Date,
        units: Sequence[DateDeltaUnitStr] = _UNSET,
        round_mode: RoundModeStr = "trunc",
        round_increment: int = 1,
        **kwargs: int,
    ) -> ItemizedDateDelta:
        """Add time to this delta, returning a new delta"""
        if kwargs:
            if arg is not _UNSET:
                raise TypeError("Cannot mix positional and keyword arguments")
        elif arg is not _UNSET:
            # In this case the mapping types are interchangeable
            kwargs = arg  # type: ignore[assignment]
        else:
            return self

        units = cast(
            Sequence[DateDeltaUnitStr],
            (
                sorted(
                    kwargs.keys() | self.keys(),
                    key=lambda u: _unit_index(u, DATE_DELTA_UNITS),
                )
                if units is _UNSET
                else units
            ),
        )

        return (
            relative_to.add(self)
            .add(**kwargs)
            .since(
                relative_to,
                units=units,
                round_mode=round_mode,
                round_increment=round_increment,
            )
        )

    @overload
    def subtract(
        self,
        other: ItemizedDateDelta,
        /,
        *,
        relative_to: Date,
        units: Sequence[DateDeltaUnitStr] = ...,
        round_mode: RoundModeStr = "trunc",
        round_increment: int = 1,
    ) -> ItemizedDateDelta: ...

    @overload
    def subtract(
        self,
        /,
        *,
        years: int = ...,
        months: int = ...,
        weeks: int = ...,
        days: int = ...,
        relative_to: Date,
        units: Sequence[DateDeltaUnitStr] = ...,
        round_mode: RoundModeStr = "trunc",
        round_increment: int = 1,
    ) -> ItemizedDateDelta: ...

    def subtract(
        self,
        arg: ItemizedDateDelta = _UNSET,
        /,
        *,
        relative_to: Date,
        units: Sequence[DateDeltaUnitStr] = _UNSET,
        round_mode: RoundModeStr = "trunc",
        round_increment: int = 1,
        **kwargs: Any,
    ) -> ItemizedDateDelta:
        """Subtract time from this delta, returning a new delta"""
        arg = -arg if arg is not _UNSET else _UNSET
        return self.add(
            arg,
            **{k: -v for k, v in kwargs.items()},
            relative_to=relative_to,
            units=units,
            round_mode=round_mode,
            round_increment=round_increment,
        )

    def total(self, unit: DateDeltaUnitStr, /, *, relative_to: Date) -> float:
        """Return the total duration expressed in the specified unit as a float

        >>> ItemizedDateDelta(years=1, months=6).total("months", relative_to=Date(2020, 1, 31))
        18.0
        >>> ItemizedDateDelta(days=1000).total("years", relative_to=Date(2020, 4, 10))
        2.73972602739726
        """
        shifted = relative_to.add(self)
        try:
            trunc_amount, trunc_date_interim, expand_date_interim = DIFF_FUNCS[
                unit
            ](shifted._py_date, relative_to._py_date, 1, self._sign or 1)
        except KeyError:
            raise ValueError(f"Unsupported unit: {unit!r}") from None

        trunc_date = resolve_leap_day(trunc_date_interim)
        expand_date = resolve_leap_day(expand_date_interim)

        return (
            trunc_amount
            + ((shifted._py_date - trunc_date) / (expand_date - trunc_date))
        ) * self._sign

    # A private constructor. Checks bounds but *not* signs or presence of > 0 fields.
    @classmethod
    def _from_signed(
        cls,
        sign: Sign,
        years: int | None = None,
        months: int | None = None,
        weeks: int | None = None,
        days: int | None = None,
    ) -> ItemizedDateDelta:
        self = _object_new(cls)
        self._sign = sign
        self._years = _check_bound(years, _MAX_DELTA_YEARS)
        self._months = _check_bound(months, _MAX_DELTA_MONTHS)
        self._weeks = _check_bound(weeks, _MAX_DELTA_WEEKS)
        self._days = _check_bound(days, _MAX_DELTA_DAYS)
        return self

    @no_type_check
    def __reduce__(self):
        return (
            _unpkl_iddelta,
            (self._sign, self._years, self._months, self._weeks, self._days),
        )

    def __repr__(self) -> str:
        return f'ItemizedDateDelta("{self.format_iso(lowercase_units=True)}")'


# A separate unpickling function allows us to make backwards-compatible changes
# to the pickling format in the future
def _unpkl_iddelta(
    sign: Sign,
    years: Optional[int],
    months: Optional[int],
    weeks: Optional[int],
    days: Optional[int],
) -> ItemizedDateDelta:
    self = _object_new(ItemizedDateDelta)
    self._sign = sign
    self._years = years
    self._months = months
    self._weeks = weeks
    self._days = days
    return self


def _check_bound(i: int | None, max_value: int) -> int | None:
    if i and i > max_value:
        raise ValueError("Delta out of range")
    return i


def _check_component(
    value: int, sign: Sign, max_value: int  # may also be _UNSET
) -> tuple[Optional[int], Sign]:
    if value is _UNSET:
        return None, sign
    elif value == 0:
        return 0, sign
    elif value < 0:
        if sign == 1:
            raise ValueError("Mixed sign in delta")
        value = -value
        sign = -1
    else:  # value > 0
        if sign == -1:
            raise ValueError("Mixed sign in delta")
        sign = 1

    if value > max_value:
        raise ValueError("Delta out of range")
    return value, sign


@final
class DateTimeDelta(_Base):
    """A duration with both a date and time component.

    .. deprecated:: 0.10.0

        Use :class:`ItemizedDelta` instead.
        ``DateTimeDelta`` normalizes its inputs separately for the date
        and time parts, losing the original fields.
        ``ItemizedDelta`` preserves the exact fields it was created with.
    """

    __slots__ = ("_date_part", "_time_part")

    # Overloads for a nice autodoc.
    # Proper typing of the constructors is handled in the type stubs
    if not TYPE_CHECKING:

        @overload
        def __init__(self, iso_string: str, /) -> None: ...

        @overload
        def __init__(
            self,
            *,
            years: int = ...,
            months: int = ...,
            weeks: int = ...,
            days: int = ...,
            hours: float = ...,
            minutes: float = ...,
            seconds: float = ...,
            milliseconds: float = ...,
            microseconds: float = ...,
            nanoseconds: int = ...,
        ) -> None: ...

    def __init__(
        self,
        *,
        years: int = 0,
        months: int = 0,
        weeks: int = 0,
        days: int = 0,
        hours: float = 0,
        minutes: float = 0,
        seconds: float = 0,
        milliseconds: float = 0,
        microseconds: float = 0,
        nanoseconds: int = 0,
    ) -> None:
        self._date_part = DateDelta(
            years=years, months=months, weeks=weeks, days=days
        )
        self._time_part = TimeDelta(
            hours=hours,
            minutes=minutes,
            seconds=seconds,
            milliseconds=milliseconds,
            microseconds=microseconds,
            nanoseconds=nanoseconds,
        )
        if (
            (self._date_part._months < 0 or self._date_part._days < 0)
            and self._time_part._total_ns > 0
        ) or (
            (self._date_part._months > 0 or self._date_part._days > 0)
            and self._time_part._total_ns < 0
        ):
            raise ValueError("Mixed sign in date-time delta")

    __init__ = add_alternate_constructors(__init__)

    ZERO: ClassVar[DateTimeDelta]
    """A delta of zero"""

    def date_part(self) -> DateDelta:
        """The date part of the delta"""
        return self._date_part

    def time_part(self) -> TimeDelta:
        """The time part of the delta"""
        return self._time_part

    def in_months_days_secs_nanos(self) -> tuple[int, int, int, int]:
        """Convert to a tuple of (months, days, seconds, nanoseconds)

        >>> d = DateTimeDelta(weeks=1, days=11, hours=4, microseconds=2)
        >>> d.in_months_days_secs_nanos()
        (0, 18, 14_400, 2000)
        """
        subsec_nanos = int(fmod(self._time_part._total_ns, 1_000_000_000))
        whole_seconds = int(self._time_part._total_ns / 1_000_000_000)
        return self._date_part.in_months_days() + (whole_seconds, subsec_nanos)

    def format_iso(self) -> str:
        """Format as the *popular interpretation* of the ISO 8601 duration format.
        May not strictly adhere to (all versions of) the standard.
        See :ref:`here <iso8601-durations>` for more information.

        Inverse of :meth:`parse_iso`.

        The format is:

        .. code-block:: text

            P(nY)(nM)(nD)T(nH)(nM)(nS)

        >>> d = DateTimeDelta(
        ...     weeks=1,
        ...     days=11,
        ...     hours=4,
        ...     milliseconds=12,
        ... )
        >>> d.format_iso()
        'P1W11DT4H0.012S'
        """
        sign = (
            self._date_part._months < 0
            or self._date_part._days < 0
            or self._time_part._total_ns < 0
        ) * "-"
        date = abs(self._date_part).format_iso()[1:] * bool(self._date_part)
        time = abs(self._time_part).format_iso()[1:] * bool(self._time_part)
        return sign + "P" + ((date + time) or "0D")

    def _init_from_iso(self, s: str) -> None:
        exc = ValueError(f"Invalid format: {s!r}")
        prev_unit = ""
        months = 0
        days = 0
        nanos = 0

        if len(s) < 3 or not s.isascii() or s.endswith("T"):
            raise exc

        s = s.upper()
        if s[0] == "P":
            sign = 1
            rest = s[1:]
        elif s.startswith("-P"):
            sign = -1
            rest = s[2:]
        elif s.startswith("+P"):
            sign = 1
            rest = s[2:]
        else:
            raise exc

        while rest and not rest.startswith("T"):
            rest, value, unit = _parse_datedelta_component(rest, exc)

            if unit == "Y" and prev_unit == "":
                months += value * 12
            elif unit == "M" and prev_unit in "Y":
                months += value
            elif unit == "W" and prev_unit in "YM":
                days += value * 7
            elif unit == "D" and prev_unit in "YMW":
                days += value
                break
            else:
                raise exc  # components out of order

            prev_unit = unit

        prev_unit = ""
        if rest and not rest.startswith("T"):
            raise exc

        # skip the "T" separator
        rest = rest[1:]

        while rest:
            rest, value, unit = parse_timedelta_component(rest, exc)

            if unit == "H" and prev_unit == "":
                nanos += value * 3_600_000_000_000
            elif unit == "M" and prev_unit in "H":
                nanos += value * 60_000_000_000
            elif unit == "S":
                nanos += value
                if rest:
                    raise exc
                break
            else:
                raise exc

            prev_unit = unit

        if nanos > _MAX_DELTA_NANOS:
            raise exc

        try:
            ddelta = DateDelta(months=sign * months, days=sign * days)
        except ValueError:
            raise exc

        tdelta = TimeDelta._from_nanos_unchecked(sign * nanos)
        return self._init_from_parts(ddelta, tdelta)

    @classmethod
    def parse_iso(cls, s: str, /) -> DateTimeDelta:
        """Parse the *popular interpretation* of the ISO 8601 duration format.
        Does not parse all possible ISO 8601 durations.
        See :ref:`here <iso8601-durations>` for more information.

        .. code-block:: text

           P4D        # 4 days
           PT4H       # 4 hours
           PT3M40.5S  # 3 minutes and 40.5 seconds
           P1W11DT4H  # 1 week, 11 days, and 4 hours
           -PT7H4M    # -7 hours and -4 minutes (-7:04:00)
           +PT7H4M    # 7 hours and 4 minutes (7:04:00)

        Inverse of :meth:`format_iso`

        >>> DateTimeDelta.parse_iso("-P1W11DT4H")
        DateTimeDelta(-P1w11dT4h)
        """
        self = _object_new(cls)
        self._init_from_iso(s)
        return self

    def __add__(
        self, other: DateTimeDelta | DateDelta | TimeDelta
    ) -> DateTimeDelta:
        """Add two deltas together

        >>> d = DateTimeDelta(weeks=1, days=11, hours=4)
        >>> d + DateTimeDelta(months=2, days=3, minutes=90)
        DateTimeDelta("P1m1w14dT5h30m")
        """
        new = _object_new(DateTimeDelta)
        if isinstance(other, DateTimeDelta):
            new._date_part = self._date_part + other._date_part
            new._time_part = self._time_part + other._time_part
        elif isinstance(other, TimeDelta):
            new._date_part = self._date_part
            new._time_part = self._time_part + other
        elif isinstance(other, DateDelta):
            new._date_part = self._date_part + other
            new._time_part = self._time_part
        else:
            return NotImplemented
        return new

    def __radd__(self, other: TimeDelta | DateDelta) -> DateTimeDelta:
        if isinstance(other, (TimeDelta, DateDelta)):
            return self + other
        return NotImplemented

    def __sub__(
        self, other: DateTimeDelta | TimeDelta | DateDelta
    ) -> DateTimeDelta:
        """Subtract two deltas

        >>> d = DateTimeDelta(weeks=1, days=11, hours=4)
        >>> d - DateTimeDelta(months=2, days=3, minutes=90)
        DateTimeDelta(-P2m1w8dT2h30m)
        """
        if isinstance(other, DateTimeDelta):
            d = self._date_part - other._date_part
            t = self._time_part - other._time_part
        elif isinstance(other, TimeDelta):
            d = self._date_part
            t = self._time_part - other
        elif isinstance(other, DateDelta):
            d = self._date_part - other
            t = self._time_part
        else:
            return NotImplemented
        return self._from_parts(d, t)

    def __rsub__(self, other: TimeDelta | DateDelta) -> DateTimeDelta:
        new = _object_new(DateTimeDelta)
        if isinstance(other, TimeDelta):
            new._date_part = -self._date_part
            new._time_part = other - self._time_part
        elif isinstance(other, DateDelta):
            new._date_part = other - self._date_part
            new._time_part = -self._time_part
        else:
            return NotImplemented
        return new

    def __eq__(self, other: object) -> bool:
        """Compare for equality

        >>> d = DateTimeDelta(
        ...     weeks=1,
        ...     days=23,
        ...     hours=4,
        ... )
        >>> d == DateTimeDelta(
        ...     weeks=1,
        ...     days=23,
        ...     minutes=4 * 60,  # normalized
        ... )
        True
        >>> d == DateTimeDelta(
        ...     weeks=4,
        ...     days=2,  # days/weeks are normalized
        ...     hours=4,
        ... )
        True
        >>> d == DateTimeDelta(
        ...     months=1,  # months/days cannot be compared directly
        ...     hours=4,
        ... )
        False
        """
        if not isinstance(other, DateTimeDelta):
            return NotImplemented
        return (
            self._date_part == other._date_part
            and self._time_part == other._time_part
        )

    def __hash__(self) -> int:
        return hash((self._date_part, self._time_part))

    def __bool__(self) -> bool:
        """True if any field is non-zero

        >>> bool(DateTimeDelta())
        False
        >>> bool(DateTimeDelta(minutes=1))
        True
        """
        return bool(self._date_part or self._time_part)

    def __mul__(self, other: int) -> DateTimeDelta:
        """Multiply by a number

        >>> d = DateTimeDelta(weeks=1, days=11, hours=4)
        >>> d * 2
        DateTimeDelta("P2w22dT8h")
        """
        # OPTIMIZE: use unchecked constructor
        return self._from_parts(
            self._date_part * other, self._time_part * other
        )

    def __rmul__(self, other: int) -> DateTimeDelta:
        return self * other

    def __neg__(self) -> DateTimeDelta:
        """Negate the delta

        >>> d = DateTimeDelta(days=11, hours=4)
        >>> -d
        DateTimeDelta(-P11dT4h)
        """
        # OPTIMIZE: use unchecked constructor
        return self._from_parts(-self._date_part, -self._time_part)

    def __pos__(self) -> DateTimeDelta:
        """Return the delta unchanged

        >>> d = DateTimeDelta(weeks=1, days=-11, hours=4)
        >>> +d
        DateTimeDelta("P1W11DT4H")
        """
        return self

    def __abs__(self) -> DateTimeDelta:
        """The absolute value of the delta

        >>> d = DateTimeDelta(weeks=1, days=-11, hours=4)
        >>> abs(d)
        DateTimeDelta("P1w11dT4h")
        """
        new = _object_new(DateTimeDelta)
        new._date_part = abs(self._date_part)
        new._time_part = abs(self._time_part)
        return new

    __str__ = format_iso

    def __repr__(self) -> str:
        iso = self.format_iso()
        # lowercase everything besides the prefix and separator
        cased = "".join(c if c in "PT" else c.lower() for c in iso)
        return f'DateTimeDelta("{cased}")'

    def _init_from_parts(self, d: DateDelta, t: TimeDelta) -> None:
        self._date_part = d
        self._time_part = t
        if ((d._months < 0 or d._days < 0) and t._total_ns > 0) or (
            (d._months > 0 or d._days > 0) and t._total_ns < 0
        ):
            raise ValueError("Mixed sign in date-time delta")

    @classmethod
    def _from_parts(cls, d: DateDelta, t: TimeDelta) -> DateTimeDelta:
        new = _object_new(cls)
        new._init_from_parts(d, t)
        return new

    @no_type_check
    def __reduce__(self):
        secs, nanos = divmod(self._time_part._total_ns, 1_000_000_000)
        return (
            _unpkl_dtdelta,
            (self._date_part._months, self._date_part._days, secs, nanos),
        )


# A separate unpickling function allows us to make backwards-compatible changes
# to the pickling format in the future
@no_type_check
def _unpkl_dtdelta(
    months: int, days: int, secs: int, nanos: int
) -> DateTimeDelta:
    new = _object_new(DateTimeDelta)
    new._date_part = DateDelta(months=months, days=days)
    new._time_part = TimeDelta(seconds=secs, nanoseconds=nanos)
    return new


DateTimeDelta.ZERO = DateTimeDelta()
AnyDelta = Union[
    DateTimeDelta, TimeDelta, DateDelta, ItemizedDelta, ItemizedDateDelta
]


# Methods for types converting to/from the standard library and ISO8601:
#
# - Instant
# - PlainDateTime
# - ZonedDateTime
# - OffsetDateTime
#
# (This base class class itself is not for public use.)
class _BasicConversions(_Base, ABC):
    __slots__ = ("_py_dt", "_nanos")
    _py_dt: _datetime
    _nanos: int

    @classmethod
    @abstractmethod
    def from_py_datetime(cls: type[_T], d: _datetime, /) -> _T:
        """Create an instance from a :class:`~datetime.datetime` object.
        Inverse of :meth:`py_datetime`.

        Note
        ----
        The datetime is checked for validity, raising similar exceptions
        to the constructor.
        ``ValueError`` is raised if the datetime doesn't have the correct
        tzinfo matching the class. For example, :class:`ZonedDateTime`
        requires a :class:`~zoneinfo.ZoneInfo` tzinfo.

        Warning
        -------
        No exceptions are raised if the datetime is ambiguous.
        Its ``fold`` attribute is used to disambiguate.
        """

    def py_datetime(self) -> _datetime:
        """Convert to a standard library :class:`~datetime.datetime`

        Note
        ----
        - Nanoseconds are truncated to microseconds.
          If you wish to customize the rounding behavior, use
          the ``round()`` method first.
        - In case of a ZonedDateTime linked to a system timezone without a
          IANA timezone ID, the returned Python datetime will have
          a fixed offset (:class:`~datetime.timezone` tzinfo)
        """
        return self._py_dt.replace(microsecond=self._nanos // 1_000)

    @abstractmethod
    def format_iso(self) -> str:
        """Format an ISO8601 string representation. Each
        subclass has a different format.

        Where applicable, keyword arguments ``unit``, ``basic``, ``sep``,
        and ``tz`` are supported to customize the output.

        See :ref:`here <iso8601>` for more information.
        """

    @classmethod
    @abstractmethod
    def parse_iso(cls: type[_T], s: str, /) -> _T:
        """Create an instance from an ISO 8601 representation,
        which is different for each subclass.

        See :ref:`here <iso8601>` for more information.
        """

    def __str__(self) -> str:
        return self.format_iso()

    @classmethod
    def _from_py_unchecked(cls: type[_T], d: _datetime, nanos: int, /) -> _T:
        assert not d.microsecond
        assert 0 <= nanos < 1_000_000_000
        self = _object_new(cls)
        self._py_dt = d  # type: ignore[attr-defined]
        self._nanos = nanos  # type: ignore[attr-defined]
        return self

    @abstractmethod
    def _init_from_py(self, d: _datetime) -> None:
        raise NotImplementedError()


# Methods for types that know a local date and time-of-day:
# - PlainDateTime
# - ZonedDateTime
# - OffsetDateTime
# (The class itself is not for public use.)
class _LocalTime(_BasicConversions, ABC):
    __slots__ = ()

    @property
    def year(self) -> int:
        """The year component of the datetime"""
        return self._py_dt.year

    @property
    def month(self) -> int:
        """The month component of the datetime"""
        return self._py_dt.month

    @property
    def day(self) -> int:
        """The day component of the datetime"""
        return self._py_dt.day

    @property
    def hour(self) -> int:
        """The hour component of the datetime"""
        return self._py_dt.hour

    @property
    def minute(self) -> int:
        """The minute component of the datetime"""
        return self._py_dt.minute

    @property
    def second(self) -> int:
        """The second component of the datetime"""
        return self._py_dt.second

    @property
    def nanosecond(self) -> int:
        """The nanosecond component of the datetime"""
        return self._nanos

    def date(self) -> Date:
        """The date part of the datetime

        >>> d = PlaineDateTime("2020-01-02 03:04:05")
        >>> d.date()
        Date("2021-01-02")

        To perform the inverse, use :meth:`Date.at` and a method
        like :meth:`~PlainDateTime.assume_utc` or
        :meth:`~PlainDateTime.assume_tz`:

        >>> date.at(time).assume_tz("Europe/London")
        ZonedDateTime("2021-01-02T03:04:05+00:00[Europe/London]")
        """
        return Date._from_py_unchecked(self._py_dt.date())

    def time(self) -> Time:
        """The time-of-day part of the datetime

        >>> d = ZonedDateTime("2021-01-02T03:04:05+01:00[Europe/Paris])"
        >>> d.time()
        Time(03:04:05)

        To perform the inverse, use :meth:`Time.on` and a method
        like :meth:`~PlainDateTime.assume_utc` or
        :meth:`~PlainDateTime.assume_tz`:

        >>> time.on(date).assume_tz("Europe/Paris")
        ZonedDateTime("2021-01-02T03:04:05+01:00[Europe/Paris]")
        """
        return Time._from_py_unchecked(self._py_dt.time(), self._nanos)

    # We document these methods as abstract,
    # but they are actually implemented slightly different per subclass
    if not TYPE_CHECKING:  # pragma: no cover

        @abstractmethod
        def add(
            self: _T,
            *,
            years: int = 0,
            months: int = 0,
            weeks: int = 0,
            days: int = 0,
            hours: float = 0,
            minutes: float = 0,
            seconds: float = 0,
            milliseconds: float = 0,
            microseconds: float = 0,
            nanoseconds: int = 0,
            **kwargs,
        ) -> _T:
            """Add date and time units to this datetime.

            Arithmetic on datetimes is complicated.
            For ``OffsetDateTime`` and ``PlainDateTime``, adding exact time units
            may emit a warning about DST safety.
            See :ref:`the docs on arithmetic <arithmetic>` for more information
            and the reasoning behind it.
            """

        @abstractmethod
        def subtract(
            self: _T,
            *,
            years: int = 0,
            months: int = 0,
            weeks: int = 0,
            days: int = 0,
            hours: float = 0,
            minutes: float = 0,
            seconds: float = 0,
            milliseconds: float = 0,
            microseconds: float = 0,
            nanoseconds: int = 0,
            **kwargs,
        ) -> _T:
            """Inverse of :meth:`add`."""

        def round(
            self: _T,
            unit: Literal[
                "day",
                "hour",
                "minute",
                "second",
                "millisecond",
                "microsecond",
                "nanosecond",
            ] = "second",
            increment: int = 1,
            mode: RoundModeStr = "half_even",
        ) -> _T:
            """Round the datetime to the specified unit and increment.
            Different rounding modes are available.

            >>> d = ZonedDateTime(2020, 8, 15, 23, 24, 18, tz="Europe/Paris")
            >>> d.round("day")
            ZonedDateTime("2020-08-16 00:00:00+02:00[Europe/Paris]")
            >>> d.round("minute", increment=15, mode="floor")
            ZonedDateTime("2020-08-15 23:15:00+02:00[Europe/Paris]")

            Notes
            -----
            * In the rare case that rounding results in an ambiguous time,
              the offset is preserved if possible.
              Otherwise, the time is resolved according to the "compatible" strategy.
            * Rounding in "day" mode may be affected by DST transitions.
              i.e. on 23-hour days, 11:31 AM is rounded up.
            * For ``OffsetDateTime``, rounding may result in a datetime with a
              stale UTC offset if the rounded time crosses a DST boundary.
              See :class:`~whenever.PotentiallyStaleOffsetWarning`.
            * This method has similar behavior to the ``round()`` method of
              Temporal objects in JavaScript.
            """


# Methods for types that represent a specific moment in time.
# Implemented by:
# - Instant
# - ZonedDateTime
# - OffsetDateTime
# (This base class class itself is not for public use.)
class _ExactTime(_BasicConversions):

    __slots__ = ()

    def timestamp(self) -> int:
        """The UNIX timestamp for this datetime. Inverse of :meth:`from_timestamp`.

        >>> Instant.from_utc(1970, 1, 1).timestamp()
        0
        >>> ts = 1_123_000_000
        >>> Instant.from_timestamp(ts).timestamp() == ts
        True

        Note
        ----
        In contrast to the standard library, this method always returns an integer,
        not a float. This is because floating point timestamps are not precise
        enough to represent all instants to nanosecond precision.
        This decision is consistent with other modern date-time libraries.
        """
        return int(self._py_dt.timestamp())

    def timestamp_millis(self) -> int:
        """Like :meth:`timestamp`, but with millisecond precision."""
        return int(self._py_dt.timestamp()) * 1_000 + self._nanos // 1_000_000

    def timestamp_nanos(self) -> int:
        """Like :meth:`timestamp`, but with nanosecond precision."""
        return int(self._py_dt.timestamp()) * 1_000_000_000 + self._nanos

    @overload
    def to_fixed_offset(self, /) -> OffsetDateTime: ...

    @overload
    def to_fixed_offset(
        self, offset: int | TimeDelta, /
    ) -> OffsetDateTime: ...

    def to_fixed_offset(
        self, offset: int | TimeDelta = _UNSET, /
    ) -> OffsetDateTime:
        """Convert to an OffsetDateTime that represents the same moment in time.

        If not offset is given, the offset is taken from the original datetime.
        """
        return OffsetDateTime._from_py_unchecked(
            self._py_dt.astimezone(
                # mypy doesn't know that offset is never None
                _timezone(self._py_dt.utcoffset())  # type: ignore[arg-type]
                if offset is _UNSET
                else _load_offset(offset)
            ),
            self._nanos,
        )

    def to_tz(self, tz: str, /) -> ZonedDateTime:
        """Convert to a ZonedDateTime that represents the same moment in time.

        Raises
        ------
        ~whenever.TimeZoneNotFoundError
            If the timezone ID is not found in the timezone database.
        """
        _tz = get_tz(tz)
        return ZonedDateTime._from_py_unchecked(
            _to_tz(self._py_dt, _tz), self._nanos, _tz
        )

    def to_system_tz(self) -> ZonedDateTime:
        """Convert to a ZonedDateTime of the system's timezone."""
        tz = get_system_tz()
        return ZonedDateTime._from_py_unchecked(
            _to_tz(self._py_dt, tz), self._nanos, tz
        )

    def exact_eq(self: _T, other: _T, /) -> bool:
        """Compare objects by their values
        (instead of whether they represent the same instant).
        Different types are never equal.

        >>> a = OffsetDateTime(2020, 8, 15, hour=12, offset=1)
        >>> b = OffsetDateTime(2020, 8, 15, hour=13, offset=2)
        >>> a == b
        True  # equivalent instants
        >>> a.exact_eq(b)
        False  # different values (hour and offset)
        >>> a.exact_eq(Instant.now())
        TypeError  # different types

        Note
        ----
        If ``a.exact_eq(b)`` is true, then
        ``a == b`` is also true, but the converse is not necessarily true.
        """
        if type(self) is not type(other):
            raise TypeError("Cannot compare different types")
        return (
            self._py_dt,  # type: ignore[attr-defined]
            self._py_dt.utcoffset(),  # type: ignore[attr-defined]
            self._nanos,  # type: ignore[attr-defined]
        ) == (
            other._py_dt,  # type: ignore[attr-defined]
            other._py_dt.utcoffset(),  # type: ignore[attr-defined]
            other._nanos,  # type: ignore[attr-defined]
        )

    def difference(
        self,
        other: Instant | OffsetDateTime | ZonedDateTime,
        /,
    ) -> TimeDelta:
        """Calculate the difference between two instants in time.

        .. deprecated:: 0.10.0

           Use the subtraction operator instead
        """
        warn(
            "The difference() method is deprecated. Use the subtraction operator instead.",
            WheneverDeprecationWarning,
            stacklevel=2,
        )
        return self - other  # type: ignore[operator, no-any-return]

    def __eq__(self, other: object) -> bool:
        """Check if two datetimes represent at the same moment in time

        ``a == b`` is equivalent to ``a.to_instant() == b.to_instant()``

        Note
        ----
        If you want to exactly compare the values on their values
        instead, use :meth:`exact_eq`.

        >>> Instant.from_utc(2020, 8, 15, hour=23) == Instant.from_utc(2020, 8, 15, hour=23)
        True
        >>> OffsetDateTime(2020, 8, 15, hour=23, offset=1) == (
        ...     ZonedDateTime(2020, 8, 15, hour=18, tz="America/New_York")
        ... )
        True
        """
        if not isinstance(other, _ExactTime):
            return NotImplemented
        # We can't rely on simple equality, because it isn't equal
        # between two datetimes with different timezones if one of the
        # datetimes needs fold to disambiguate it.
        # See peps.python.org/pep-0495/#aware-datetime-equality-comparison.
        # We want to avoid this legacy edge case, so we normalize to UTC.
        return (self._py_dt.astimezone(_UTC), self._nanos) == (
            other._py_dt.astimezone(_UTC),
            other._nanos,
        )

    def __lt__(self, other: _ExactTimeAlias) -> bool:
        """Compare two datetimes by when they occur in time

        ``a < b`` is equivalent to ``a.to_instant() < b.to_instant()``

        >>> OffsetDateTime(2020, 8, 15, hour=23, offset=8) < (
        ...     ZoneDateTime(2020, 8, 15, hour=20, tz="Europe/Amsterdam")
        ... )
        True
        """
        if not isinstance(other, _ExactTime):
            return NotImplemented
        return (self._py_dt.astimezone(_UTC), self._nanos) < (
            other._py_dt.astimezone(_UTC),
            other._nanos,
        )

    def __le__(self, other: _ExactTimeAlias) -> bool:
        """Compare two datetimes by when they occur in time

        ``a <= b`` is equivalent to ``a.to_instant() <= b.to_instant()``

        >>> OffsetDateTime(2020, 8, 15, hour=23, offset=8) <= (
        ...     ZoneDateTime(2020, 8, 15, hour=20, tz="Europe/Amsterdam")
        ... )
        True
        """
        if not isinstance(other, _ExactTime):
            return NotImplemented
        return (self._py_dt.astimezone(_UTC), self._nanos) <= (
            other._py_dt.astimezone(_UTC),
            other._nanos,
        )

    def __gt__(self, other: _ExactTimeAlias) -> bool:
        """Compare two datetimes by when they occur in time

        ``a > b`` is equivalent to ``a.to_instant() > b.to_instant()``

        >>> OffsetDateTime(2020, 8, 15, hour=19, offset=-8) > (
        ...     ZoneDateTime(2020, 8, 15, hour=20, tz="Europe/Amsterdam")
        ... )
        True
        """
        if not isinstance(other, _ExactTime):
            return NotImplemented
        return (self._py_dt.astimezone(_UTC), self._nanos) > (
            other._py_dt.astimezone(_UTC),
            other._nanos,
        )

    def __ge__(self, other: _ExactTimeAlias) -> bool:
        """Compare two datetimes by when they occur in time

        ``a >= b`` is equivalent to ``a.to_instant() >= b.to_instant()``

        >>> OffsetDateTime(2020, 8, 15, hour=19, offset=-8) >= (
        ...     ZoneDateTime(2020, 8, 15, hour=20, tz="Europe/Amsterdam")
        ... )
        True
        """
        if not isinstance(other, _ExactTime):
            return NotImplemented
        return (self._py_dt.astimezone(_UTC), self._nanos) >= (
            other._py_dt.astimezone(_UTC),
            other._nanos,
        )

    def _subtract_operator(self, other: _ExactTimeAlias) -> TimeDelta:
        if isinstance(other, _ExactTime):
            py_delta = self._py_dt.astimezone(_UTC) - other._py_dt
            return TimeDelta(
                seconds=py_delta.days * 86_400 + py_delta.seconds,
                nanoseconds=self._nanos - other._nanos,
            )
        return NotImplemented


# Common behavior for all types that know an exact time and
# corresponding local date and time-of-day.
# - ZonedDateTime
# - OffsetDateTime
# (The class itself it not for public use.)
class _ExactAndLocalTime(_LocalTime, _ExactTime):

    __slots__ = ()

    @property
    def offset(self) -> TimeDelta:
        """The UTC offset of the datetime"""
        return TimeDelta._from_nanos_unchecked(
            int(
                self._py_dt.utcoffset().total_seconds()  # type: ignore[union-attr]
                * 1_000_000_000
            )
        )

    def to_instant(self) -> Instant:
        """Get the underlying instant in time

        >>> d = ZonedDateTime(2020, 8, 15, hour=23, tz="Europe/Amsterdam")
        >>> d.to_instant()
        Instant("2020-08-15 21:00:00Z")
        """
        return Instant._from_py_unchecked(
            self._py_dt.astimezone(_UTC), self._nanos
        )

    def to_plain(self) -> PlainDateTime:
        """Get the underlying date and time without offset or timezone

        As an inverse, :class:`PlainDateTime` has methods
        :meth:`~PlainDateTime.assume_utc`, :meth:`~PlainDateTime.assume_fixed_offset`
        , :meth:`~PlainDateTime.assume_tz`, and :meth:`~PlainDateTime.assume_system_tz`.
        """
        return PlainDateTime._from_py_unchecked(
            self._py_dt.replace(tzinfo=None),
            self._nanos,
        )


@final
class Instant(_ExactTime):
    """A moment in time, independent of any timezone or calendar.

    This is the right type when you only care about *when* something happened,
    not the local date or time. It maps 1:1 to a UNIX timestamp.

    >>> from whenever import Instant
    >>> py311_release = Instant.from_utc(2022, 10, 24, hour=17)
    Instant("2022-10-24 17:00:00Z")
    >>> py311_release.add(hours=3).timestamp()
    1666641600

    Can also be constructed from an ISO 8601 string, a UNIX timestamp,
    or a standard library :class:`~datetime.datetime`:

    >>> Instant("2022-10-24T17:00:00Z")
    Instant("2022-10-24 17:00:00Z")

    Convert to other types for local date/time information:

    >>> py311_release.to_tz("US/Pacific")
    ZonedDateTime("2022-10-24 10:00:00-07:00[US/Pacific]")

    Note
    ----
    Although the debug representation uses UTC, ``Instant`` does *not* have
    ``.year``, ``.hour``, or other calendar attributes—it is not a UTC datetime.
    See the `FAQ <https://whenever.rtfd.io/en/latest/faq.html#why-doesn-t-instant-have-year-hour-etc>`_.
    """

    __slots__ = ()

    MIN: ClassVar[Instant]
    """The minimum representable instant."""

    MAX: ClassVar[Instant]
    """The maximum representable instant."""

    def __init__(self, arg: str | _datetime, /) -> None:
        """Create an Instant from an ISO 8601 string or a standard library datetime."""
        if isinstance(arg, str):
            self._init_from_iso(arg)
        elif isinstance(arg, _datetime):
            self._init_from_py(arg)
        else:
            raise TypeError(
                "Instant constructor requires an ISO string or stdlib datetime"
            )

    @classmethod
    def from_utc(
        cls,
        year: int,
        month: int,
        day: int,
        hour: int = 0,
        minute: int = 0,
        second: int = 0,
        *,
        nanosecond: int = 0,
    ) -> Instant:
        """Create an Instant defined by a UTC date and time."""
        if nanosecond < 0 or nanosecond >= 1_000_000_000:
            raise ValueError(f"nanosecond out of range: {nanosecond}")
        return cls._from_py_unchecked(
            _datetime(year, month, day, hour, minute, second, 0, _UTC),
            nanosecond,
        )

    @classmethod
    def now(cls) -> Instant:
        """Create an Instant from the current time.

        >>> Instant.now()
        Instant("2024-06-15 12:34:56.789123456Z")
        """
        secs, nanos = divmod(time_ns(), 1_000_000_000)
        return cls._from_py_unchecked(_fromtimestamp(secs, _UTC), nanos)

    @classmethod
    def from_timestamp(cls, i: int | float, /) -> Instant:
        """Create an Instant from a UNIX timestamp (in seconds).

        The inverse of the ``timestamp()`` method.
        """
        secs, fract = divmod(i, 1)
        return cls._from_py_unchecked(
            _fromtimestamp(secs, _UTC), int(fract * 1_000_000_000)
        )

    @classmethod
    def from_timestamp_millis(cls, i: int, /) -> Instant:
        """Create an Instant from a UNIX timestamp (in milliseconds).

        The inverse of the ``timestamp_millis()`` method.
        """
        if not isinstance(i, int):
            raise TypeError("method requires an integer")
        secs, millis = divmod(i, 1_000)
        return cls._from_py_unchecked(
            _fromtimestamp(secs, _UTC), millis * 1_000_000
        )

    @classmethod
    def from_timestamp_nanos(cls, i: int, /) -> Instant:
        """Create an Instant from a UNIX timestamp (in nanoseconds).

        The inverse of the ``timestamp_nanos()`` method.
        """
        if not isinstance(i, int):
            raise TypeError("method requires an integer")
        secs, nanos = divmod(i, 1_000_000_000)
        return cls._from_py_unchecked(_fromtimestamp(secs, _UTC), nanos)

    @classmethod
    def from_py_datetime(cls, d: _datetime, /) -> Instant:
        """Create an ``Instant`` from any *aware* ``datetime`` object.

        The inverse of the ``py_datetime()`` method.
        """
        self = _object_new(cls)
        self._init_from_py(d)
        return self

    def _init_from_py(self, d: _datetime) -> None:
        if d.tzinfo is None or d.utcoffset() is None:
            raise ValueError(
                "Cannot create Instant from a naive datetime. "
                "Use PlainDateTime() instead."
            )
        as_utc = d.astimezone(_UTC)
        self._py_dt = _strip_subclasses(as_utc.replace(microsecond=0))
        self._nanos = as_utc.microsecond * 1_000

    @classmethod
    def parse_iso(cls, s: str, /) -> Instant:
        """Parse an ISO 8601 string. Supports basic and extended formats,
        but not week dates or ordinal dates.

        See the `docs on ISO8601 support <https://whenever.rtfd.io/en/latest/reference/iso8601.html>`__ for more information.

        The inverse of the ``format_iso()`` method.
        """
        self = _object_new(cls)
        self._init_from_iso(s)
        return self

    def _init_from_iso(self, s: str) -> None:
        dt, nanos = offset_dt_from_iso(s)
        self._py_dt = dt.astimezone(_UTC)
        self._nanos = nanos

    def format_iso(
        self,
        *,
        unit: Literal[
            "hour",
            "minute",
            "second",
            "millisecond",
            "microsecond",
            "nanosecond",
            "auto",
        ] = "auto",
        basic: bool = False,
        sep: Literal["T", " "] = "T",
    ) -> str:
        """Convert to the ISO 8601 string representation.

        The inverse of the ``parse_iso()`` method.
        """
        return _format_dt(self._py_dt, self._nanos, "Z", unit, sep, basic)

    def format_rfc2822(self) -> str:
        """Format as an RFC 2822 string.
        The inverse of the ``parse_rfc2822()`` method.

        >>> Instant.from_utc(2020, 8, 8, hour=23, minute=12).format_rfc2822()
        "Sat, 08 Aug 2020 23:12:00 GMT"

        Note
        ----
        The output is also compatible with the (stricter) RFC 9110 standard.

        """
        return (
            f"{WEEKDAY_TO_RFC2822[self._py_dt.weekday()]}, "
            f"{self._py_dt.day:02} "
            f"{MONTH_TO_RFC2822[self._py_dt.month]} {self._py_dt.year:04} "
            f"{self._py_dt.time()} GMT"
        )

    @classmethod
    def parse_rfc2822(cls, s: str, /) -> Instant:
        """Parse a UTC datetime in RFC 2822 format.

        The inverse of the ``format_rfc2822()`` method.

        >>> Instant.parse_rfc2822("Sat, 15 Aug 2020 23:12:00 GMT")
        Instant("2020-08-15 23:12:00Z")

        >>> # also valid:
        >>> Instant.parse_rfc2822("Sat, 15 Aug 2020 23:12:00 +0000")
        >>> Instant.parse_rfc2822("Sat, 15 Aug 2020 23:12:00 +0800")
        >>> Instant.parse_rfc2822("Sat, 15 Aug 2020 23:12:00 -0000")
        >>> Instant.parse_rfc2822("Sat, 15 Aug 2020 23:12:00 UT")
        >>> Instant.parse_rfc2822("Sat, 15 Aug 2020 23:12:00 MST")

        Note
        ----
        - Although technically part of the RFC 2822 standard,
          comments within folding whitespace are not supported.
        """
        return cls._from_py_unchecked(parse_rfc2822(s).astimezone(_UTC), 0)

    def add(
        self,
        *,
        hours: float = 0,
        minutes: float = 0,
        seconds: float = 0,
        milliseconds: float = 0,
        microseconds: float = 0,
        nanoseconds: int = 0,
    ) -> Instant:
        """Add a time amount to this instant.

        See the `docs on arithmetic <https://whenever.rtfd.io/en/latest/guide/arithmetic.html>`__ for more information.
        """
        return self + TimeDelta(
            hours=hours,
            minutes=minutes,
            seconds=seconds,
            milliseconds=milliseconds,
            microseconds=microseconds,
            nanoseconds=nanoseconds,
        )

    def subtract(
        self,
        *,
        hours: float = 0,
        minutes: float = 0,
        seconds: float = 0,
        milliseconds: float = 0,
        microseconds: float = 0,
        nanoseconds: int = 0,
    ) -> Instant:
        """Subtract a time amount from this instant.

        See the `docs on arithmetic <https://whenever.rtfd.io/en/latest/guide/arithmetic.html>`__ for more information.
        """
        return self.add(
            hours=-hours,
            minutes=-minutes,
            seconds=-seconds,
            milliseconds=-milliseconds,
            microseconds=-microseconds,
            nanoseconds=-nanoseconds,
        )

    def round(
        self,
        unit: Literal[
            "hour",
            "minute",
            "second",
            "millisecond",
            "microsecond",
            "nanosecond",
        ] = "second",
        increment: int = 1,
        mode: RoundModeStr = "half_even",
    ) -> Instant:
        """Round the instant to the specified unit and increment.
        Various rounding modes are available.

        >>> Instant.from_utc(2020, 1, 1, 12, 39, 59).round("minute", 15)
        Instant("2020-01-01 12:45:00Z")
        >>> Instant.from_utc(2020, 1, 1, 8, 9, 13).round("second", 5, mode="floor")
        Instant("2020-01-01 08:09:10Z")
        """
        if unit == "day":  # type: ignore[comparison-overlap]
            raise ValueError(CANNOT_ROUND_DAY_MSG)
        rounded_time, next_day = Time._from_py_unchecked(
            self._py_dt.time(), self._nanos
        )._round_unchecked(
            increment_to_ns_for_datetime(unit, increment),
            mode,
            86_400_000_000_000,
        )
        return self._from_py_unchecked(
            _datetime.combine(
                self._py_dt.date() + _timedelta(days=next_day),
                rounded_time._py,
                tzinfo=_UTC,
            ),
            rounded_time._nanos,
        )

    def __add__(self, delta: TimeDelta) -> Instant:
        """Add a time amount to this datetime.

        See the `docs on arithmetic <https://whenever.rtfd.io/en/latest/guide/arithmetic.html>`__ for more information.
        """
        if isinstance(delta, TimeDelta):
            delta_secs, nanos = divmod(
                self._nanos + delta._time_part._total_ns,
                1_000_000_000,
            )
            return self._from_py_unchecked(
                self._py_dt + _timedelta(seconds=delta_secs),
                nanos,
            )
        return NotImplemented

    @overload
    def __sub__(self, other: _ExactTimeAlias) -> TimeDelta: ...

    @overload
    def __sub__(self, other: TimeDelta) -> Instant: ...

    def __sub__(
        self, other: TimeDelta | _ExactTimeAlias
    ) -> Instant | TimeDelta:
        """Subtract another exact time or timedelta

        See the `docs on arithmetic <https://whenever.rtfd.io/en/latest/guide/arithmetic.html>`__ for more information.

        >>> d = Instant.from_utc(2020, 8, 15, hour=23, minute=12)
        >>> d - hours(24) - seconds(5)
        Instant("2020-08-14 23:11:55Z")
        >>> d - Instant.from_utc(2020, 8, 14)
        TimeDelta(47:12:00)
        """
        if isinstance(other, _ExactTime):
            return self._subtract_operator(other)
        elif isinstance(other, TimeDelta):
            return self + -other
        return NotImplemented

    def __hash__(self) -> int:
        return hash((self._py_dt, self._nanos))

    def __repr__(self) -> str:
        return f"Instant(\"{str(self).replace('T', ' ')}\")"

    # a custom pickle implementation with a smaller payload
    def __reduce__(self) -> tuple[object, ...]:
        return (
            _unpkl_inst,
            (pack("<qL", int(self._py_dt.timestamp()), self._nanos),),
        )


# Backwards compatibility for instances pickled before 0.8.0
def _unpkl_utc(data: bytes) -> Instant:
    secs, nanos = unpack("<qL", data)
    return Instant._from_py_unchecked(
        _fromtimestamp(secs - 62_135_683_200, _UTC), nanos
    )


# A separate unpickling function allows us to make backwards-compatible changes
# to the pickling format in the future
def _unpkl_inst(data: bytes) -> Instant:
    secs, nanos = unpack("<qL", data)
    return Instant._from_py_unchecked(_fromtimestamp(secs, _UTC), nanos)


@final
class OffsetDateTime(_ExactAndLocalTime):
    """A datetime with a fixed UTC offset.

    Useful for representing a moment in time together with the local
    date and time as observed at that offset. The offset is fixed and
    does not account for DST transitions.

    >>> # Midnight in Salt Lake City
    >>> OffsetDateTime(2023, 4, 21, offset=-6)
    OffsetDateTime("2023-04-21 00:00:00-06:00")

    Can also be constructed from an ISO 8601 string
    or a standard library :class:`~datetime.datetime`:

    >>> OffsetDateTime("2023-04-21T00:00:00-06:00")
    OffsetDateTime("2023-04-21 00:00:00-06:00")

    Convert to :class:`~whenever.ZonedDateTime` for DST-aware operations:

    >>> dt = OffsetDateTime(2023, 4, 21, offset=-6)
    >>> dt.assume_tz("US/Mountain")
    ZonedDateTime("2023-04-21 00:00:00-06:00[US/Mountain]")

    Important
    ---------
    Operations that shift, round, or replace fields of this type keep the
    original offset, which may become stale if DST rules have changed.
    Use :meth:`assume_tz` to convert to a ``ZonedDateTime`` first if you
    need DST-aware arithmetic.
    """

    __slots__ = ()

    # Overloads are for a nicer autodoc
    # Typing is arranged in the stubs
    if not TYPE_CHECKING:

        @overload
        def __init__(self, iso_string: str, /) -> None: ...

        @overload
        def __init__(self, py_dt: _datetime, /) -> None: ...

        @overload
        def __init__(
            self,
            year: int,
            month: int,
            day: int,
            hour: int = 0,
            minute: int = 0,
            second: int = 0,
            *,
            nanosecond: int = 0,
            offset: int | TimeDelta,
        ) -> None: ...

    def __init__(
        self,
        year: int,
        month: int,
        day: int,
        hour: int = 0,
        minute: int = 0,
        second: int = 0,
        *,
        nanosecond: int = 0,
        offset: int | TimeDelta,
    ) -> None:
        self._py_dt = check_utc_bounds(
            _datetime(
                year,
                month,
                day,
                hour,
                minute,
                second,
                0,
                _load_offset(offset),
            )
        )
        if nanosecond < 0 or nanosecond >= 1_000_000_000:
            raise ValueError(f"nanosecond out of range: {nanosecond}")
        self._nanos = nanosecond

    __init__ = add_alternate_constructors(__init__, py_type=_datetime)

    @classmethod
    def now(
        cls, offset: int | TimeDelta, /, *, ignore_dst: bool = _UNSET
    ) -> OffsetDateTime:
        """Create an instance from the current time.

        Warning
        -------
        Getting the current time as an ``OffsetDateTime`` with a fixed UTC offset
        may be incorrect: the offset doesn't update when DST or other timezone
        rules change. Use ``ZonedDateTime.now('<tz>')`` if you know the timezone,
        or ``Instant.now()`` for timezone-agnostic exact time.
        Suppress with :func:`~whenever.ignore_potentially_stale_offset_warning`.
        """
        if ignore_dst is not _UNSET:
            warn(
                "The `ignore_dst` parameter is deprecated and replaced with a warning.",
                WheneverDeprecationWarning,
                stacklevel=2,
            )
        if not _ignore_potentially_stale_offset_warning.get():
            warn(
                OFFSET_NOW_STALE_MSG,
                PotentiallyStaleOffsetWarning,
                stacklevel=2,
            )
        secs, nanos = divmod(time_ns(), 1_000_000_000)
        return cls._from_py_unchecked(
            _fromtimestamp(secs, _load_offset(offset)), nanos
        )

    def format_iso(
        self,
        *,
        unit: Literal[
            "hour",
            "minute",
            "second",
            "millisecond",
            "microsecond",
            "nanosecond",
            "auto",
        ] = "auto",
        basic: bool = False,
        sep: Literal["T", " "] = "T",
    ) -> str:
        """Convert to the popular ISO format ``YYYY-MM-DDTHH:MM:SS±HH:MM``

        The inverse of the ``parse_iso()`` method.
        """
        return _format_dt(
            self._py_dt,
            self._nanos,
            self._py_dt.utcoffset(),  # type: ignore[arg-type]
            unit,
            sep,
            basic,
        )

    @classmethod
    def parse_iso(cls, s: str, /) -> OffsetDateTime:
        """Parse the popular ISO format ``YYYY-MM-DDTHH:MM:SS±HH:MM``

        The inverse of the ``format_iso()`` method.

        >>> OffsetDateTime.parse_iso("2020-08-15T23:12:00+02:00")
        OffsetDateTime("2020-08-15 23:12:00+02:00")
        """
        self = _object_new(cls)
        self._init_from_iso(s)
        return self

    def _init_from_iso(self, s: str) -> None:
        self._py_dt, self._nanos = offset_dt_from_iso(s)

    @classmethod
    def from_timestamp(
        cls,
        i: int | float,
        /,
        *,
        offset: int | TimeDelta,
        ignore_dst: bool = _UNSET,
    ) -> OffsetDateTime:
        """Create an instance from a UNIX timestamp (in seconds).

        The inverse of the ``timestamp()`` method.

        Warning
        -------
        Converting a UNIX timestamp to ``OffsetDateTime`` with a fixed UTC offset
        may produce an incorrect result: you can't know from the offset alone
        whether DST applies to this timestamp. Use
        ``ZonedDateTime.from_timestamp(ts, tz='<tz>')`` if you know the timezone,
        or ``Instant.from_timestamp()`` for timezone-agnostic exact time.
        Suppress with :func:`~whenever.ignore_potentially_stale_offset_warning`.
        """
        if ignore_dst is not _UNSET:
            warn(
                "The `ignore_dst` parameter is deprecated and replaced with a warning.",
                WheneverDeprecationWarning,
                stacklevel=2,
            )
        if not _ignore_potentially_stale_offset_warning.get():
            warn(
                OFFSET_FROM_TIMESTAMP_STALE_MSG,
                PotentiallyStaleOffsetWarning,
                stacklevel=2,
            )
        secs, fract = divmod(i, 1)
        return cls._from_py_unchecked(
            _fromtimestamp(secs, _load_offset(offset)),
            int(fract * 1_000_000_000),
        )

    @classmethod
    def from_timestamp_millis(
        cls, i: int, /, *, offset: int | TimeDelta, ignore_dst: bool = _UNSET
    ) -> OffsetDateTime:
        """Create an instance from a UNIX timestamp (in milliseconds).

        The inverse of the ``timestamp_millis()`` method.

        See :meth:`from_timestamp` for more information.
        """
        if ignore_dst is not _UNSET:
            warn(
                "The `ignore_dst` parameter is deprecated and replaced with a warning.",
                WheneverDeprecationWarning,
                stacklevel=2,
            )
        if not _ignore_potentially_stale_offset_warning.get():
            warn(
                OFFSET_FROM_TIMESTAMP_STALE_MSG,
                PotentiallyStaleOffsetWarning,
                stacklevel=2,
            )
        if not isinstance(i, int):
            raise TypeError("method requires an integer")
        secs, millis = divmod(i, 1_000)
        return cls._from_py_unchecked(
            _fromtimestamp(secs, _load_offset(offset)), millis * 1_000_000
        )

    @classmethod
    def from_timestamp_nanos(
        cls, i: int, /, *, offset: int | TimeDelta, ignore_dst: bool = _UNSET
    ) -> OffsetDateTime:
        """Create an instance from a UNIX timestamp (in nanoseconds).

        The inverse of the ``timestamp_nanos()`` method.

        See :meth:`from_timestamp` for more information.
        """
        if ignore_dst is not _UNSET:
            warn(
                "The `ignore_dst` parameter is deprecated and replaced with a warning.",
                WheneverDeprecationWarning,
                stacklevel=2,
            )
        if not _ignore_potentially_stale_offset_warning.get():
            warn(
                OFFSET_FROM_TIMESTAMP_STALE_MSG,
                PotentiallyStaleOffsetWarning,
                stacklevel=2,
            )
        if not isinstance(i, int):
            raise TypeError("method requires an integer")
        secs, nanos = divmod(i, 1_000_000_000)
        return cls._from_py_unchecked(
            _fromtimestamp(secs, _load_offset(offset)), nanos
        )

    @classmethod
    def from_py_datetime(cls, d: _datetime, /) -> OffsetDateTime:
        """Create an instance from any *aware* ``datetime`` object.
        The datetime must be aware.

        The inverse of the ``py_datetime()`` method.

        """
        self = _object_new(cls)
        self._init_from_py(d)
        return self

    def _init_from_py(self, d: _datetime) -> None:
        if d.tzinfo is None or (offset := d.utcoffset()) is None:
            raise ValueError(
                "Cannot create from a naive datetime. "
                "Use PlainDateTime.from_py_datetime() for this."
            )
        elif offset.microseconds:
            raise ValueError("Sub-second offsets are not supported")
        self._py_dt = check_utc_bounds(
            _strip_subclasses(
                d.replace(microsecond=0, tzinfo=_timezone(offset))
            )
        )
        self._nanos = d.microsecond * 1_000

    if not TYPE_CHECKING:  # for a nicer autodoc

        @overload
        def replace(
            self,
            year: int = ...,
            month: int = ...,
            day: int = ...,
            hour: int = ...,
            minute: int = ...,
            second: int = ...,
            *,
            nanosecond: int = ...,
            offset: int | TimeDelta = ...,
            ignore_dst: bool = ...,
        ) -> OffsetDateTime: ...

    def replace(
        self, /, ignore_dst: bool = _UNSET, **kwargs: Any
    ) -> OffsetDateTime:
        """Construct a new instance with the given fields replaced.

        Warning
        -------
        Replacing fields of an ``OffsetDateTime`` keeps the fixed UTC offset,
        which may no longer be correct after the change (e.g. replacing the month
        on a European-timezone datetime may move it into a different DST period).
        Convert to ``ZonedDateTime`` first for timezone-aware field replacement
        using :meth:`assume_tz`.
        Suppress with :func:`~whenever.ignore_potentially_stale_offset_warning`.
        """
        if ignore_dst is not _UNSET:
            warn(
                "The `ignore_dst` parameter is deprecated and replaced with a warning.",
                WheneverDeprecationWarning,
                stacklevel=2,
            )
        if not _ignore_potentially_stale_offset_warning.get():
            warn(
                OFFSET_REPLACE_STALE_MSG,
                PotentiallyStaleOffsetWarning,
                stacklevel=2,
            )
        _check_invalid_replace_kwargs(kwargs)
        try:
            kwargs["tzinfo"] = _load_offset(kwargs.pop("offset"))
        except KeyError:
            pass
        nanos = _pop_nanos_kwarg(kwargs, self._nanos)
        return self._from_py_unchecked(
            check_utc_bounds(self._py_dt.replace(**kwargs)), nanos
        )

    def replace_date(
        self, date: Date, /, *, ignore_dst: bool = _UNSET
    ) -> OffsetDateTime:
        """Construct a new instance with the date replaced.

        See :meth:`replace` for more information.
        """
        if ignore_dst is not _UNSET:
            warn(
                "The `ignore_dst` parameter is deprecated and replaced with a warning.",
                WheneverDeprecationWarning,
                stacklevel=2,
            )
        if not _ignore_potentially_stale_offset_warning.get():
            warn(
                OFFSET_REPLACE_STALE_MSG,
                PotentiallyStaleOffsetWarning,
                stacklevel=2,
            )
        return self._from_py_unchecked(
            check_utc_bounds(
                _datetime.combine(date._py_date, self._py_dt.timetz())
            ),
            self._nanos,
        )

    def replace_time(
        self, time: Time, /, *, ignore_dst: bool = _UNSET
    ) -> OffsetDateTime:
        """Construct a new instance with the time replaced.

        See :meth:`replace` for more information.
        """
        if ignore_dst is not _UNSET:
            warn(
                "The `ignore_dst` parameter is deprecated and replaced with a warning.",
                WheneverDeprecationWarning,
                stacklevel=2,
            )
        if not _ignore_potentially_stale_offset_warning.get():
            warn(
                OFFSET_REPLACE_STALE_MSG,
                PotentiallyStaleOffsetWarning,
                stacklevel=2,
            )
        return self._from_py_unchecked(
            check_utc_bounds(
                _datetime.combine(
                    self._py_dt.date(), time._py, self._py_dt.tzinfo
                )
            ),
            time._nanos,
        )

    def __hash__(self) -> int:
        return hash((self._py_dt, self._nanos))

    def __add__(self, delta: TimeDelta) -> OffsetDateTime:
        """Add a time delta to this datetime.

        Warning
        -------
        Shifting an ``OffsetDateTime`` keeps the fixed UTC offset, which may not
        match the actual offset after a DST or other timezone transition.
        For example, adding 1 day to ``2024-03-09 12:00-07:00`` gives
        ``2024-03-10 12:00-07:00``, but if this offset represents Denver,
        Colorado (America/Denver), the actual offset changed to ``-06:00`` that day.
        Convert to a ``ZonedDateTime`` first for timezone-aware arithmetic
        using :meth:`assume_tz`.
        Suppress with the
        :func:`~whenever.ignore_potentially_stale_offset_warning` context manager;
        Python's standard warning filters also apply.
        """
        if isinstance(delta, TimeDelta):
            if not _ignore_potentially_stale_offset_warning.get():
                warn(
                    OFFSET_SHIFT_STALE_MSG,
                    PotentiallyStaleOffsetWarning,
                    stacklevel=2,
                )
            delta_secs, nanos = divmod(
                delta._total_ns + self._nanos, 1_000_000_000
            )
            return self._from_py_unchecked(
                check_utc_bounds(self._py_dt + _timedelta(seconds=delta_secs)),
                nanos,
            )
        return NotImplemented

    @overload
    def __sub__(self, other: _ExactTimeAlias) -> TimeDelta: ...

    @overload
    def __sub__(self, other: TimeDelta) -> OffsetDateTime: ...

    def __sub__(
        self, other: _ExactTimeAlias | TimeDelta
    ) -> TimeDelta | OffsetDateTime:
        """Subtract a time delta or calculate the duration to another exact time."""
        if isinstance(other, TimeDelta):
            if not _ignore_potentially_stale_offset_warning.get():
                warn(
                    OFFSET_SHIFT_STALE_MSG,
                    PotentiallyStaleOffsetWarning,
                    stacklevel=2,
                )
            delta_secs, nanos = divmod(
                -other._total_ns + self._nanos, 1_000_000_000
            )
            return self._from_py_unchecked(
                check_utc_bounds(self._py_dt + _timedelta(seconds=delta_secs)),
                nanos,
            )
        return super()._subtract_operator(other)

    @classmethod
    def parse_strptime(cls, s: str, /, *, format: str) -> OffsetDateTime:
        """Parse a datetime with offset using the standard library ``strptime()`` method.

        >>> OffsetDateTime.parse_strptime("2020-08-15+0200", format="%Y-%m-%d%z")
        OffsetDateTime("2020-08-15 00:00:00+02:00")

        Note
        ----
        This method defers to the standard library ``strptime()`` method,
        which may behave differently in different Python versions.
        It also only supports up to microsecond precision.

        Important
        ---------
        An offset *must* be present in the format string.
        This means you MUST include the directive ``%z``, ``%Z``, or ``%:z``.
        To parse a datetime without an offset, use ``PlainDateTime`` instead.
        """
        parsed = _datetime.strptime(s, format)
        if (offset := parsed.utcoffset()) is None:
            raise ValueError(
                "Parsed datetime must have an offset. "
                "Use %z, %Z, or %:z in the format string"
            )
        if offset.microseconds:
            raise ValueError("Sub-second offsets are not supported")
        return cls._from_py_unchecked(
            check_utc_bounds(parsed.replace(microsecond=0)),
            parsed.microsecond * 1_000,
        )

    def format_rfc2822(self) -> str:
        """Format as an RFC 2822 string.

        The inverse of the ``parse_rfc2822()`` method.

        >>> OffsetDateTime(2020, 8, 15, 23, 12, offset=hours(2)).format_rfc2822()
        "Sat, 15 Aug 2020 23:12:00 +0200"
        """
        offset = int(self._py_dt.utcoffset().total_seconds())  # type: ignore[union-attr]
        offset_sign = "-" if offset < 0 else "+"
        offset = abs(offset)
        offset_h = offset // 3600
        offset_m = (offset % 3600) // 60
        return (
            f"{WEEKDAY_TO_RFC2822[self._py_dt.weekday()]}, "
            f"{self._py_dt.day:02} "
            f"{MONTH_TO_RFC2822[self._py_dt.month]} {self._py_dt.year:04} "
            f"{self._py_dt.time()} "
            f"{offset_sign}{offset_h:02}{offset_m:02}"
        )

    @classmethod
    def parse_rfc2822(cls, s: str, /) -> OffsetDateTime:
        """Parse an offset datetime in RFC 2822 format.

        The inverse of the ``format_rfc2822()`` method.

        >>> OffsetDateTime.parse_rfc2822("Sat, 15 Aug 2020 23:12:00 +0200")
        OffsetDateTime("2020-08-15 23:12:00+02:00")
        >>> # also valid:
        >>> OffsetDateTime.parse_rfc2822("Sat, 15 Aug 2020 23:12:00 UT")
        >>> OffsetDateTime.parse_rfc2822("Sat, 15 Aug 2020 23:12:00 GMT")
        >>> OffsetDateTime.parse_rfc2822("Sat, 15 Aug 2020 23:12:00 MST")

        Note
        ----
        - Strictly speaking, an offset of ``-0000`` means that the offset
          is "unknown". Here, we treat it the same as +0000.
        - Although technically part of the RFC 2822 standard,
          comments within folding whitespace are not supported.
        """
        return cls._from_py_unchecked(parse_rfc2822(s), 0)

    if not TYPE_CHECKING:  # for a nicer autodoc

        @overload
        def add(self, delta: AnyDelta, /) -> OffsetDateTime: ...

        @overload
        def add(
            self,
            *,
            years: int = 0,
            months: int = 0,
            weeks: int = 0,
            days: int = 0,
            hours: float = 0,
            minutes: float = 0,
            seconds: float = 0,
            milliseconds: float = 0,
            microseconds: float = 0,
            nanoseconds: int = 0,
            ignore_dst: bool = ...,
        ) -> OffsetDateTime: ...

    @no_type_check
    def add(self, *args, **kwargs) -> OffsetDateTime:
        """Add a time amount to this datetime.

        Warning
        -------
        Shifting an ``OffsetDateTime`` keeps the fixed UTC offset, which may not
        match the actual offset after a DST or other timezone transition.
        Convert to a ``ZonedDateTime`` first for timezone-aware arithmetic
        using :meth:`assume_tz`.
        Suppress with the
        :func:`~whenever.ignore_potentially_stale_offset_warning` context manager;
        Python's standard warning filters also apply.
        """
        return self._shift(1, *args, **kwargs)

    if not TYPE_CHECKING:  # for a nicer autodoc

        @overload
        def subtract(self, delta: AnyDelta, /) -> OffsetDateTime: ...

        @overload
        def subtract(
            self,
            *,
            years: int = 0,
            months: int = 0,
            weeks: int = 0,
            days: int = 0,
            hours: float = 0,
            minutes: float = 0,
            seconds: float = 0,
            milliseconds: float = 0,
            microseconds: float = 0,
            nanoseconds: int = 0,
            ignore_dst: bool = ...,
        ) -> OffsetDateTime: ...

    @no_type_check
    def subtract(self, *args, **kwargs) -> OffsetDateTime:
        """Subtract a time amount from this datetime.

        See :meth:`add` for more information.
        """
        return self._shift(-1, *args, **kwargs)

    @no_type_check
    def _shift(
        self,
        sign: int,
        arg: AnyDelta | _UNSET = _UNSET,
        /,
        *,
        ignore_dst: bool = _UNSET,
        **kwargs,
    ) -> OffsetDateTime:
        if ignore_dst is not _UNSET:
            warn(
                "The `ignore_dst` parameter is deprecated and replaced with a warning.",
                WheneverDeprecationWarning,
                stacklevel=3,
            )
        if not _ignore_potentially_stale_offset_warning.get():
            warn(
                OFFSET_SHIFT_STALE_MSG,
                PotentiallyStaleOffsetWarning,
                stacklevel=3,
            )
        if kwargs:
            if arg is _UNSET:
                return self._shift_kwargs(sign, **kwargs)
            raise TypeError("Cannot mix positional and keyword arguments")

        elif arg is not _UNSET:
            return self._shift_kwargs(
                sign,
                months=arg._date_part._months,
                days=arg._date_part._days,
                nanoseconds=arg._time_part._total_ns,
            )
        else:
            return self

    def _shift_kwargs(
        self,
        sign: int,
        *,
        years: int = 0,
        months: int = 0,
        weeks: int = 0,
        days: int = 0,
        hours: float = 0,
        minutes: float = 0,
        seconds: float = 0,
        milliseconds: float = 0,
        microseconds: float = 0,
        nanoseconds: int = 0,
    ) -> OffsetDateTime:
        py_dt_with_new_date = _datetime.combine(
            (
                self.date()
                ._add_months(sign * (years * 12 + months))
                ._add_days(sign * (weeks * 7 + days))
            )._py_date,
            self._py_dt.timetz(),
        )

        tdelta = sign * TimeDelta(
            hours=hours,
            minutes=minutes,
            seconds=seconds,
            milliseconds=milliseconds,
            microseconds=microseconds,
            nanoseconds=nanoseconds,
        )

        delta_secs, nanos = divmod(
            tdelta._total_ns + self._nanos, 1_000_000_000
        )
        return self._from_py_unchecked(
            check_utc_bounds(
                py_dt_with_new_date + _timedelta(seconds=delta_secs)
            ),
            nanos,
        )

    def round(
        self,
        unit: Literal[
            "day",
            "hour",
            "minute",
            "second",
            "millisecond",
            "microsecond",
            "nanosecond",
        ] = "second",
        increment: int = 1,
        mode: RoundModeStr = "half_even",
        *,
        ignore_dst: bool = _UNSET,
    ) -> OffsetDateTime:
        """Round the datetime to the specified unit and increment.
        Different rounding modes are available.

        >>> d = OffsetDateTime(2020, 8, 15, 23, 24, 18, offset=+4)
        >>> d.round("day")
        OffsetDateTime("2020-08-16 00:00:00[+04:00]")
        >>> d.round("minute", increment=15, mode="floor")
        OffsetDateTime("2020-08-15 23:15:00[+04:00]")

        Note
        ----
        * This method has similar behavior to the ``round()`` method of
          Temporal objects in JavaScript.

        Warning
        -------
        Rounding an ``OffsetDateTime`` keeps the fixed UTC offset, which may not
        be accurate if the rounded datetime crosses into a different DST period.
        Convert to a ``ZonedDateTime`` first for timezone-aware rounding
        using :meth:`assume_tz`.
        Suppress with :func:`~whenever.ignore_potentially_stale_offset_warning`.
        """
        if ignore_dst is not _UNSET:
            warn(
                "The `ignore_dst` parameter is deprecated and replaced with a warning.",
                WheneverDeprecationWarning,
                stacklevel=2,
            )
        if not _ignore_potentially_stale_offset_warning.get():
            warn(
                OFFSET_ROUND_STALE_MSG,
                PotentiallyStaleOffsetWarning,
                stacklevel=2,
            )
        return (
            self.to_plain()
            ._round_unchecked(
                increment_to_ns_for_datetime(unit, increment),
                mode,
                86_400_000_000_000,
            )
            .assume_fixed_offset(self.offset)
        )

    def assume_tz(
        self, tz: str, *, offset_mismatch: OffsetMismatchStr = "raise"
    ) -> ZonedDateTime:
        """Associate this offset datetime with a timezone, returning a ZonedDateTime.

        This is the inverse of :meth:`ZonedDateTime.to_fixed_offset`.

        By default, if the offset of this datetime doesn't match the actual
        offset of the timezone at this datetime, an error is raised.
        Using the ``offset_mismatch`` parameter, you can choose to ignore
        the mismatch, keeping either the instant or the local time the same.
        """
        if offset_mismatch not in ("raise", "keep_instant", "keep_local"):
            raise ValueError(
                f"Invalid value for offset_mismatch: {offset_mismatch!r}"
            )
        result = self.to_tz(tz)
        if (
            offset_mismatch == "keep_instant"
            or result._py_dt.utcoffset() == self._py_dt.utcoffset()
        ):
            return result
        elif offset_mismatch == "raise":
            offset_expected = _format_offset(
                self._py_dt.utcoffset(), basic=False  # type: ignore[arg-type]
            )
            offset_actual = _format_offset(
                result._py_dt.utcoffset(), basic=False  # type: ignore[arg-type]
            )
            raise InvalidOffsetError(
                f"Offset mismatch: timezone {tz!r} has offset {offset_actual}, "
                f"but offset {offset_expected} was expected"
            )
        else:  # offset_mismatch == "keep_local":
            return self.to_plain().assume_tz(tz)

    @overload
    def since(
        self,
        b: OffsetDateTime,
        /,
        *,
        unit: DeltaUnitStr,
        round_mode: RoundModeStr = ...,
        round_increment: int = ...,
    ) -> int: ...

    @overload
    def since(
        self,
        b: OffsetDateTime,
        /,
        *,
        units: Sequence[DeltaUnitStr],
        round_mode: RoundModeStr = ...,
        round_increment: int = ...,
    ) -> ItemizedDelta: ...

    def since(
        self,
        b: OffsetDateTime,
        /,
        *,
        unit: DeltaUnitStr | None = None,
        units: Sequence[DeltaUnitStr] | None = None,
        round_mode: RoundModeStr = "trunc",
        round_increment: int = 1,
    ) -> ItemizedDelta | int:
        """Calculate the duration since another OffsetDateTime,
        in terms of the specified units.

        >>> d1 = OffsetDateTime(2020, 8, 15, 23, 12, offset=2)
        >>> d2 = OffsetDateTime(2020, 8, 14, 22, offset=2)
        >>> d1.since(d2, units=["hours", "minutes"],
        ...          round_increment=15,
        ...          round_mode="ceil")
        ItemizedDelta("PT25h15m")

        When calculating calendar units (years, months, weeks, days),
        both datetimes must have the same offset.
        """
        return _offset_since(self, b, unit, units, round_mode, round_increment)

    @overload
    def until(
        self,
        b: OffsetDateTime,
        /,
        *,
        unit: DeltaUnitStr,
        round_mode: RoundModeStr = ...,
        round_increment: int = ...,
    ) -> int: ...

    @overload
    def until(
        self,
        b: OffsetDateTime,
        /,
        *,
        units: Sequence[DeltaUnitStr],
        round_mode: RoundModeStr = ...,
        round_increment: int = ...,
    ) -> ItemizedDelta: ...

    def until(
        self,
        b: OffsetDateTime,
        /,
        *,
        unit: DeltaUnitStr | None = None,
        units: Sequence[DeltaUnitStr] | None = None,
        round_mode: RoundModeStr = "trunc",
        round_increment: int = 1,
    ) -> ItemizedDelta | int:
        """Inverse of the ``since()`` method. See :meth:`since` for more information."""
        return b.since(  # type: ignore[call-overload, no-any-return]
            self,
            unit=unit,
            units=units,
            round_mode=round_mode,
            round_increment=round_increment,
        )

    def __repr__(self) -> str:
        return f"OffsetDateTime(\"{str(self).replace('T', ' ')}\")"

    # a custom pickle implementation with a smaller payload
    def __reduce__(self) -> tuple[object, ...]:
        return (
            _unpkl_offset,
            (
                pack(
                    "<HBBBBBil",
                    *self._py_dt.timetuple()[:6],
                    self._nanos,
                    int(self._py_dt.utcoffset().total_seconds()),  # type: ignore[union-attr]
                ),
            ),
        )


# A separate function is needed for unpickling, because the
# constructor doesn't accept positional offset argument as
# required by __reduce__.
# Also, it allows backwards-compatible changes to the pickling format.
def _unpkl_offset(data: bytes) -> OffsetDateTime:
    *args, nanos, offset_secs = unpack("<HBBBBBil", data)
    args += (0, _timezone(_timedelta(seconds=offset_secs)))
    return OffsetDateTime._from_py_unchecked(_datetime(*args), nanos)


@final
class ZonedDateTime(_ExactAndLocalTime):
    """A datetime associated with a timezone from the IANA database.

    This is the right type when you need both the exact moment *and*
    the local date/time at a specific location. Arithmetic is fully
    DST-aware: the offset is always kept in sync with the timezone rules.

    >>> ZonedDateTime("2024-12-08T11[Europe/Paris]")
    ZonedDateTime("2024-12-08 11:00:00+01:00[Europe/Paris]")
    >>> # Explicitly resolve ambiguities during DST transitions
    >>> ZonedDateTime(2023, 10, 29, 1, 15, tz="Europe/London", disambiguate="earlier")
    ZonedDateTime("2023-10-29 01:15:00+01:00[Europe/London]")
    >>> # From a standard library datetime (must have a ZoneInfo tzinfo)
    >>> ZonedDateTime(datetime(2020, 8, 15, 23, 12, tzinfo=ZoneInfo("Europe/London")))
    ZonedDateTime("2020-08-15 23:12:00+01:00[Europe/London]")

    Convert to other types to discard timezone information:

    >>> d = ZonedDateTime(2024, 7, 1, 12, tz="Europe/Amsterdam")
    >>> d.to_instant()
    Instant("2024-07-01 10:00:00Z")
    >>> d.to_plain()
    PlainDateTime("2024-07-01 12:00:00")

    Important
    ---------
    To use this type properly, read more about
    `ambiguity in timezones <https://whenever.rtfd.io/en/latest/guide/ambiguity.html>`_.
    """

    __slots__ = ("_tz",)

    # Overloads are for a nicer autodoc
    # Typing is arranged in the stubs
    if not TYPE_CHECKING:

        @overload
        def __init__(self, iso_string: str, /) -> None: ...

        @overload
        def __init__(self, py_dt: _datetime, /) -> None: ...

        @overload
        def __init__(
            self,
            year: int,
            month: int,
            day: int,
            hour: int = 0,
            minute: int = 0,
            second: int = 0,
            *,
            nanosecond: int = 0,
            tz: str,
            disambiguate: DisambiguateStr = "compatible",
        ) -> None: ...

    def __init__(
        self,
        year: int,
        month: int,
        day: int,
        hour: int = 0,
        minute: int = 0,
        second: int = 0,
        *,
        nanosecond: int = 0,
        tz: str,
        disambiguate: DisambiguateStr = "compatible",
    ) -> None:
        self._py_dt = resolve_ambiguity(
            _datetime(
                year,
                month,
                day,
                hour,
                minute,
                second,
                0,
            ),
            (_tz := get_tz(tz)),
            disambiguate,
        )
        if nanosecond < 0 or nanosecond >= 1_000_000_000:
            raise ValueError(f"nanosecond out of range: {nanosecond}")
        self._nanos = nanosecond
        self._tz = _tz

    __init__ = add_alternate_constructors(__init__, py_type=_datetime)

    @classmethod
    def from_system_tz(
        cls,
        year: int,
        month: int,
        day: int,
        hour: int = 0,
        minute: int = 0,
        second: int = 0,
        *,
        nanosecond: int = 0,
        disambiguate: DisambiguateStr = "compatible",
    ) -> ZonedDateTime:
        """Create an instance in the system timezone.

        Equivalent to ``ZonedDateTime(..., tz=<the system timezone>)``,
        except it also works for system timezones whose corresponding
        IANA timezone ID is unknown.

        >>> ZonedDateTime.from_system_tz(2020, 8, 15, hour=23, minute=12)
        ZonedDateTime("2020-08-15 23:12:00+02:00[Europe/Berlin]")
        """
        tz = get_system_tz()
        dt = resolve_ambiguity(
            _datetime(
                year,
                month,
                day,
                hour,
                minute,
                second,
                0,
            ),
            tz,
            disambiguate,
        )
        if nanosecond < 0 or nanosecond >= 1_000_000_000:
            raise ValueError(f"nanosecond out of range: {nanosecond}")
        return cls._from_py_unchecked(dt, nanosecond, tz)

    @classmethod
    def now(cls, tz: str, /) -> ZonedDateTime:
        """Create an instance from the current time in the given timezone."""
        secs, nanos = divmod(time_ns(), 1_000_000_000)
        _tz = get_tz(tz)
        return cls._from_py_unchecked(_from_epoch(secs, _tz), nanos, _tz)

    @classmethod
    def now_in_system_tz(cls) -> ZonedDateTime:
        """Create an instance from the current time in the system timezone.

        Equivalent to ``Instant.now().to_system_tz()``.
        """
        tz = get_system_tz()
        secs, nanos = divmod(time_ns(), 1_000_000_000)
        return cls._from_py_unchecked(_from_epoch(secs, tz), nanos, tz)

    def format_iso(
        self,
        *,
        unit: Literal[
            "hour",
            "minute",
            "second",
            "millisecond",
            "microsecond",
            "nanosecond",
            "auto",
        ] = "auto",
        basic: bool = False,
        sep: Literal["T", " "] = "T",
        tz: Literal["always", "never", "auto"] = "always",
    ) -> str:
        """Convert to the popular ISO format ``YYYY-MM-DDTHH:MM:SS±HH:MM[TZ_ID]``.

        The inverse of the ``parse_iso()`` method.

        Parameters
        ----------
        unit
            The smallest unit to include in the output.
            ``"auto"`` is the same as ``"nanosecond"``,
            except that trailing zeroes are omitted from the time part.
        basic
            Whether to use the basic ISO format (without separators) instead of the extended one.
        sep
            The separator between the date and time parts.
        tz
            Whether to include the timezone ID in the output.
            ``"always"`` (default) raises an error if the timezone ID is not available
            (in practice, this should only happen for some system timezones without a corresponding IANA timezone ID).
            ``"auto"`` includes the ID if available, and omits it otherwise.
            ``"never"`` always omits the ID.

        >>> zdt = ZonedDateTime(2020, 8, 15, hour=23, minute=12, tz="Europe/London")
        >>> zdt.format_iso(unit="minute", basic=True)
        "20200815T2312+0100[Europe/London]"

        Important
        ---------
        The timezone ID is a recent extension to the ISO 8601 format (RFC 9557).
        Although it is gaining popularity, it is not yet widely supported
        by ISO 8601 parsers.
        """
        if tz == "always":
            if self._tz.key is None:
                raise ValueError(FORMAT_ISO_NO_TZ_MSG)
            suffix = f"[{self._tz.key}]"
        elif tz == "auto" and self._tz.key is not None:
            suffix = f"[{self._tz.key}]"
        else:  # never
            suffix = ""

        return (
            _format_dt(
                self._py_dt,
                self._nanos,
                self._py_dt.utcoffset(),  # type: ignore[arg-type]
                unit,
                sep,
                basic,
            )
            + suffix
        )

    # FUTURE: allow handling offset mismatches
    @classmethod
    def parse_iso(cls, s: str, /) -> ZonedDateTime:
        """Parse from the popular ISO format ``YYYY-MM-DDTHH:MM:SS±HH:MM[TZ_ID]``

        The inverse of the ``format_iso()`` method.

        >>> ZonedDateTime.parse_iso("2020-08-15T23:12:00+01:00[Europe/London]")
        ZonedDateTime("2020-08-15 23:12:00+01:00[Europe/London]")

        Important
        ---------
        The timezone ID is a recent extension to the ISO 8601 format (RFC 9557).
        Although it is gaining popularity, it is not yet widely supported.
        """
        self = _object_new(cls)
        self._init_from_iso(s)
        return self

    def _init_from_iso(self, s: str) -> None:
        self._py_dt, self._nanos, self._tz = zdt_from_iso(s)

    @classmethod
    def from_timestamp(
        cls, i: Union[int, float], /, *, tz: str
    ) -> ZonedDateTime:
        """Create an instance from a UNIX timestamp (in seconds).

        The inverse of the ``timestamp()`` method.
        """
        secs, fract = divmod(i, 1)
        _tz = get_tz(tz)
        return cls._from_py_unchecked(
            _from_epoch(int(secs), _tz), int(fract * 1_000_000_000), _tz
        )

    @classmethod
    def from_timestamp_millis(cls, i: int, /, *, tz: str) -> ZonedDateTime:
        """Create an instance from a UNIX timestamp (in milliseconds).

        The inverse of the ``timestamp_millis()`` method.
        """
        if not isinstance(i, int):
            raise TypeError("method requires an integer")
        secs, millis = divmod(i, 1_000)
        _tz = get_tz(tz)
        return cls._from_py_unchecked(
            _from_epoch(secs, _tz), millis * 1_000_000, _tz
        )

    @classmethod
    def from_timestamp_nanos(cls, i: int, /, *, tz: str) -> ZonedDateTime:
        """Create an instance from a UNIX timestamp (in nanoseconds).

        The inverse of the ``timestamp_nanos()`` method.
        """
        if not isinstance(i, int):
            raise TypeError("method requires an integer")
        secs, nanos = divmod(i, 1_000_000_000)
        _tz = get_tz(tz)
        return cls._from_py_unchecked(_from_epoch(secs, _tz), nanos, _tz)

    @classmethod
    def from_py_datetime(cls, d: _datetime, /) -> ZonedDateTime:
        """Create an instance from a standard library ``datetime`` object
        with a ``ZoneInfo`` tzinfo.

        The inverse of the ``py_datetime()`` method.

        """
        self = _object_new(cls)
        self._init_from_py(d)
        return self

    def _init_from_py(self, d: _datetime) -> None:
        from zoneinfo import ZoneInfo

        if type(d.tzinfo) is not ZoneInfo:
            raise ValueError(
                "Can only create ZonedDateTime from tzinfo=ZoneInfo (exactly), "
                f"got datetime with tzinfo={d.tzinfo!r}"
            )
        if d.tzinfo.key is None:
            raise ValueError(ZONEINFO_NO_KEY_MSG)

        # We go through the epoch to ensure the result represents the same instant.
        # If we'd use the local time, ZoneInfo could theoretically pick a different
        # offset than we get from our database.
        epoch = int(d.timestamp())
        _tz = get_tz(d.tzinfo.key)
        offset = _tz.offset_for_instant(int(epoch))
        # Recalculating from epoch ensures we shift times within a gap
        self._py_dt = _from_epoch(int(epoch), _tz).astimezone(
            mk_fixed_tzinfo(offset)
        )
        self._nanos = d.microsecond * 1_000
        self._tz = _tz

    def replace_date(
        self, date: Date, /, disambiguate: DisambiguateStr = _UNSET
    ) -> ZonedDateTime:
        """Construct a new instance with the date replaced.

        See the ``replace()`` method for more information.
        """
        return self._from_py_unchecked(
            resolve_ambiguity(
                _datetime.combine(date._py_date, self._py_dt.time()),
                self._tz,
                disambiguate or self._py_dt.utcoffset(),
            ),
            self._nanos,
            self._tz,
        )

    def replace_time(
        self, time: Time, /, disambiguate: DisambiguateStr = _UNSET
    ) -> ZonedDateTime:
        """Construct a new instance with the time replaced.

        See the ``replace()`` method for more information.
        """
        return self._from_py_unchecked(
            resolve_ambiguity(
                _datetime.combine(self._py_dt, time._py),
                self._tz,
                disambiguate or self._py_dt.utcoffset(),
            ),
            time._nanos,
            self._tz,
        )

    if not TYPE_CHECKING:  # for a nicer autodoc

        @overload
        def replace(
            self,
            year: int = ...,
            month: int = ...,
            day: int = ...,
            hour: int = ...,
            minute: int = ...,
            second: int = ...,
            *,
            nanosecond: int = ...,
            tz: str = ...,
            disambiguate: DisambiguateStr = ...,
        ) -> ZonedDateTime: ...

    def replace(
        self, /, disambiguate: DisambiguateStr = _UNSET, **kwargs: Any
    ) -> ZonedDateTime:
        """Construct a new instance with the given fields replaced.

        Important
        ---------
        Replacing fields of a ZonedDateTime may result in an ambiguous time
        (e.g. during a DST transition). Therefore, it's recommended to
        specify how to handle such a situation using the ``disambiguate`` argument.

        By default, if the tz remains the same, the offset is used to disambiguate
        if possible, falling back to the "compatible" strategy if needed.

        See `the documentation <https://whenever.rtfd.io/en/latest/guide/ambiguity.html>`__
        for more information.
        """

        _check_invalid_replace_kwargs(kwargs)
        try:
            tzid = kwargs.pop("tz")
        except KeyError:
            tz = self._tz
        else:
            tz = get_tz(tzid)
            # Don't attempt to preserve offset when changing tz
            if tz is not self._tz:
                disambiguate = disambiguate or "compatible"
        nanos = _pop_nanos_kwarg(kwargs, self._nanos)

        return self._from_py_unchecked(
            resolve_ambiguity(
                self._py_dt.replace(**kwargs, tzinfo=None),
                tz,
                disambiguate or self._py_dt.utcoffset(),
            ),
            nanos,
            tz,
        )

    @property
    def tz(self) -> Optional[str]:
        """The timezone ID. In rare cases, this may be ``None``,
        if the ``ZonedDateTime`` was created from a system timezone
        without a known IANA key.
        """
        return self._tz.key

    def __hash__(self) -> int:
        return hash((self._py_dt, self._nanos))

    def __add__(
        self, delta: TimeDelta | DateDelta | DateTimeDelta
    ) -> ZonedDateTime:
        """Add an amount of time, accounting for timezone changes (e.g. DST).

        See `the docs <https://whenever.rtfd.io/en/latest/guide/arithmetic.html>`__
        for more information.
        """
        if isinstance(delta, TimeDelta):
            delta_secs, nanos = divmod(
                delta._time_part._total_ns + self._nanos, 1_000_000_000
            )
            new_epoch = int(self._py_dt.timestamp()) + delta_secs
            return self._from_py_unchecked(
                _from_epoch(new_epoch, self._tz),
                nanos,
                self._tz,
            )
        elif isinstance(delta, DateDelta):
            return self.replace_date(self.date() + delta)
        elif isinstance(delta, DateTimeDelta):
            return (
                self.replace_date(self.date() + delta._date_part)
                + delta._time_part
            )
        return NotImplemented

    @overload
    def __sub__(self, other: _ExactTimeAlias) -> TimeDelta: ...

    @overload
    def __sub__(self, other: TimeDelta) -> ZonedDateTime: ...

    def __sub__(
        self, other: TimeDelta | _ExactTimeAlias
    ) -> _ExactTimeAlias | TimeDelta:
        """Subtract another datetime or duration.

        See `the docs <https://whenever.rtfd.io/en/latest/guide/arithmetic.html>`__
        for more information.
        """
        if isinstance(other, _ExactTime):
            return self._subtract_operator(other)
        elif isinstance(other, (TimeDelta, DateDelta, DateTimeDelta)):
            return self + -other
        return NotImplemented

    @overload
    def add(
        self,
        d: AnyDelta,
        /,
        *,
        disambiguate: DisambiguateStr = ...,
    ) -> ZonedDateTime: ...

    @overload
    def add(
        self,
        *,
        years: int = ...,
        months: int = ...,
        weeks: int = ...,
        days: int = ...,
        hours: float = ...,
        minutes: float = ...,
        seconds: float = ...,
        milliseconds: float = ...,
        microseconds: float = ...,
        nanoseconds: int = ...,
        disambiguate: DisambiguateStr = ...,
    ) -> ZonedDateTime: ...

    @no_type_check
    def add(self, *args, **kwargs) -> ZonedDateTime:
        """Return a new ``ZonedDateTime`` shifted by the given time amounts

        Important
        ---------
        Shifting by **calendar units** (e.g. months, weeks)
        may result in an ambiguous time (e.g. during a DST transition).
        Therefore, when adding calendar units, it's recommended to
        specify how to handle such a situation using the ``disambiguate`` argument.

        See `the documentation <https://whenever.rtfd.io/en/latest/guide/arithmetic.html>`__
        for more information.
        """
        return self._shift(1, *args, **kwargs)

    @overload
    def subtract(
        self,
        d: AnyDelta,
        /,
        *,
        disambiguate: DisambiguateStr = ...,
    ) -> ZonedDateTime: ...

    @overload
    def subtract(
        self,
        *,
        years: int = ...,
        months: int = ...,
        weeks: int = ...,
        days: int = ...,
        hours: float = ...,
        minutes: float = ...,
        seconds: float = ...,
        milliseconds: float = ...,
        microseconds: float = ...,
        nanoseconds: int = ...,
        disambiguate: DisambiguateStr = ...,
    ) -> ZonedDateTime: ...

    @no_type_check
    def subtract(self, *args, **kwargs) -> ZonedDateTime:
        """The inverse of the ``add()`` method. See :meth:`add` for more information."""
        return self._shift(-1, *args, **kwargs)

    @no_type_check
    def _shift(
        self,
        sign: int,
        delta: AnyDelta | _UNSET = _UNSET,
        /,
        *,
        disambiguate: DisambiguateStr = _UNSET,
        **kwargs,
    ) -> ZonedDateTime:
        if kwargs:
            if delta is _UNSET:
                return self._shift_kwargs(
                    sign, disambiguate=disambiguate, **kwargs
                )
            raise TypeError("Cannot mix positional and keyword arguments")
        elif delta is _UNSET:
            return self
        elif isinstance(delta, (ItemizedDelta, ItemizedDateDelta)):
            return self._shift_kwargs(sign, **delta, disambiguate=disambiguate)
        elif isinstance(delta, (TimeDelta, DateDelta, DateTimeDelta)):
            return self._shift_kwargs(
                sign,
                months=delta._date_part._months,
                days=delta._date_part._days,
                nanoseconds=delta._time_part._total_ns,
                disambiguate=disambiguate,
            )
        else:
            raise TypeError("argument must be a delta, got {delta!r}")

    def _shift_kwargs(
        self,
        sign: int,
        *,
        years: int = 0,
        months: int = 0,
        weeks: int = 0,
        days: int = 0,
        hours: float = 0,
        minutes: float = 0,
        seconds: float = 0,
        milliseconds: float = 0,
        microseconds: float = 0,
        nanoseconds: int = 0,
        disambiguate: DisambiguateStr = _UNSET,
    ) -> ZonedDateTime:
        months_total = sign * (years * 12 + months)
        days_total = sign * (weeks * 7 + days)
        if months_total or days_total:
            self = self.replace_date(
                self.date()._add_months(months_total)._add_days(days_total),
                disambiguate=disambiguate,
            )
        return self + sign * TimeDelta(
            hours=hours,
            minutes=minutes,
            seconds=seconds,
            milliseconds=milliseconds,
            microseconds=microseconds,
            nanoseconds=nanoseconds,
        )

    @overload
    def since(
        self,
        b: ZonedDateTime,
        /,
        *,
        unit: DeltaUnitStr,
        round_mode: RoundModeStr = ...,
        round_increment: int = ...,
    ) -> int: ...

    @overload
    def since(
        self,
        b: ZonedDateTime,
        /,
        *,
        units: Sequence[DeltaUnitStr],
        round_mode: RoundModeStr = ...,
        round_increment: int = ...,
    ) -> ItemizedDelta: ...

    # FUTURE: add round_unit to the signature,
    # in order to allow rounding to millis, micros, and nanos
    def since(
        self,
        b: ZonedDateTime,
        /,
        *,
        unit: DeltaUnitStr | None = None,
        units: Sequence[DeltaUnitStr] | None = None,
        round_mode: RoundModeStr = "trunc",
        round_increment: int = 1,
    ) -> ItemizedDelta | int:
        """Calculate the duration since another ZonedDateTime,
        in terms of the specified units.

        >>> d1 = ZonedDateTime("2020-08-15T23:12:00+01:00[Europe/London]")
        >>> d2 = ZonedDateTime("2020-08-14T22:00:00+09:00[Asia/Tokyo]")
        >>> d1.since(d2, units=["hours", "minutes"],
        ...          round_increment=15,
        ...          round_mode="ceil")
        ItemizedDelta("PT33h15m")

        When calculating calendar units (years, months, weeks, days),
        both datetimes must have the same timezone.
        """
        units, single_unit_mode = _normalize_unit_or_units(
            unit, units, valid_units=DELTA_UNITS
        )
        cal_units, exact_units = _split_calendar_and_exact_units(units)
        if cal_units and self.tz != b.tz:
            raise ValueError(
                "Calendar units can only be used to compare ZonedDateTimes "
                "with the same timezone"
            )

        sign: Literal[1, -1] = 1 if self >= b else -1

        # Adjust target_date so the exact remainder has the same sign
        # as the overall difference. The while loop handles the rare case
        # of a 24h+ gap, e.g. Samoa in 2011.
        target_date = self.date()
        if sign == 1:
            while b.replace_date(target_date) > self:
                target_date = target_date.subtract(days=1)
        else:
            while b.replace_date(target_date) < self:
                target_date = target_date.add(days=1)
        cal_results, trunc_date, expand_date = date_diff(
            target_date._py_date,
            b._py_dt.date(),
            # Rounding only applies to the smallest unit.
            # Thus if there are any exact units, calendar units aren't rounded.
            1 if exact_units else round_increment,
            cal_units,
            sign,
        )
        trunc = b.replace_date(
            Date._from_py_unchecked(resolve_leap_day(trunc_date)),
        )
        expand = b.replace_date(
            Date._from_py_unchecked(resolve_leap_day(expand_date)),
        )

        # Rounding is very different for exact units than calendar units
        smallest_unit = units[-1]
        result = cast(dict[DeltaUnitStr, int], cal_results)
        if exact_units:
            result.update(
                (self - trunc)._in_units(  # type: ignore[arg-type]
                    exact_units,
                    round_increment=round_increment,
                    round_mode=round_mode,
                    round_unit=_UNSET,
                )
            )
        else:
            # Round is expensive, so only do it if needed
            if round_mode != "trunc":
                result[smallest_unit] = custom_round(
                    result[smallest_unit],
                    abs((self - trunc)._total_ns),
                    abs((expand - trunc)._total_ns),
                    round_mode,
                    round_increment,
                    sign,
                )

        if single_unit_mode:
            return result.pop(smallest_unit) * sign

        # mypy false positive: 'keywords must be strings' (but they're string literals!)
        return ItemizedDelta._from_signed(
            sign if any(result.values()) else 0, **result
        )  # type: ignore[misc]

    @overload
    def until(
        self,
        b: ZonedDateTime,
        /,
        *,
        unit: DeltaUnitStr,
        round_mode: RoundModeStr = ...,
        round_increment: int = ...,
    ) -> int: ...

    @overload
    def until(
        self,
        b: ZonedDateTime,
        /,
        *,
        units: Sequence[DeltaUnitStr],
        round_mode: RoundModeStr = ...,
        round_increment: int = ...,
    ) -> ItemizedDelta: ...

    def until(
        self,
        b: ZonedDateTime,
        /,
        *,
        unit: DeltaUnitStr | None = None,
        units: Sequence[DeltaUnitStr] | None = None,
        round_mode: RoundModeStr = "trunc",
        round_increment: int = 1,
    ) -> ItemizedDelta | int:
        """Inverse of the ``since()`` method. See :meth:`since` for more information."""
        return b.since(  # type: ignore[call-overload, no-any-return]
            self,
            unit=unit,
            units=units,
            round_mode=round_mode,
            round_increment=round_increment,
        )

    def is_ambiguous(self) -> bool:
        """Whether the date and time-of-day are ambiguous, e.g. due to a DST transition.

        >>> ZonedDateTime(2020, 8, 15, 23, tz="Europe/London").is_ambiguous()
        False
        >>> ZonedDateTime(2023, 10, 29, 2, 15, tz="Europe/Amsterdam").is_ambiguous()
        True
        """
        return (
            type(
                self._tz.ambiguity_for_local(
                    int(self._py_dt.replace(tzinfo=_UTC).timestamp())
                )
            )
            is not Unambiguous
        )

    def day_length(self) -> TimeDelta:
        """The duration between the start of the current day and the next.
        This is usually 24 hours, but may be different due to timezone transitions.

        >>> ZonedDateTime(2020, 8, 15, tz="Europe/London").day_length()
        TimeDelta(24:00:00)
        >>> ZonedDateTime(2023, 10, 29, tz="Europe/Amsterdam").day_length()
        TimeDelta(25:00:00)
        """
        midnight_naive = _datetime.combine(self._py_dt.date(), _time.min)
        midnight = resolve_ambiguity(
            midnight_naive,
            self._tz,
            "compatible",
        )
        next_midnight = resolve_ambiguity(
            midnight_naive + _timedelta(days=1),
            self._tz,
            "compatible",
        )
        return TimeDelta.from_py_timedelta(next_midnight - midnight)

    def start_of_day(self) -> ZonedDateTime:
        """The start of the current calendar day.

        This is almost always at midnight the same day, but may be different
        for timezones which transition at—and thus skip over—midnight.
        """
        return self._from_py_unchecked(
            resolve_ambiguity(
                _datetime.combine(self._py_dt.date(), _time.min),
                self._tz,
                "compatible",
            ),
            0,
            self._tz,
        )

    def round(
        self,
        unit: Literal[
            "day",
            "hour",
            "minute",
            "second",
            "millisecond",
            "microsecond",
            "nanosecond",
        ] = "second",
        increment: int = 1,
        mode: RoundModeStr = "half_even",
    ) -> ZonedDateTime:
        """Round the datetime to the specified unit and increment.
        Different rounding modes are available.

        >>> d = ZonedDateTime("2020-08-15 23:24:18+02:00[Europe/Paris]")
        >>> d.round("day")
        ZonedDateTime("2020-08-16 00:00:00+02:00[Europe/Paris]")
        >>> d.round("minute", increment=15, mode="floor")
        ZonedDateTime("2020-08-15 23:15:00+02:00[Europe/Paris]")

        Notes
        -----
        * In the rare case that rounding results in a repeated time,
          the offset is preserved if possible.
          Otherwise, ambiguity is resolved according to the "compatible" strategy.
        * Rounding in "day" mode may be affected by DST transitions.
          i.e. on 23-hour days, 11:31 AM is rounded up.
        * This method has similar behavior to the ``round()`` method of
          Temporal objects in JavaScript.
        """
        increment_ns = increment_to_ns_for_datetime(unit, increment)
        if unit == "day":
            increment_ns = day_ns = self.day_length()._total_ns
        else:
            day_ns = 86_400_000_000_000

        rounded_local = self.to_plain()._round_unchecked(
            increment_ns, mode, day_ns
        )
        return self._from_py_unchecked(
            resolve_ambiguity_using_prev_offset(
                rounded_local._py_dt,
                self._py_dt.utcoffset(),  # type: ignore[arg-type]
                self._tz,
            ),
            rounded_local._nanos,
            self._tz,
        )

    def py_datetime(self) -> _datetime:
        if (key := self._tz.key) is None:
            # For system timezoned datetimes without a key,
            # there's nothing else we can do. This is documented behavior.
            return self._py_dt.replace(microsecond=self._nanos // 1_000)

        from zoneinfo import ZoneInfo

        # We go through astimezone because, in theory, ZoneInfo could disagree
        # with our offset. This ensures we keep the same moment in time.
        # FUTURE: add a test case for this.
        return self._py_dt.astimezone(ZoneInfo(key)).replace(
            microsecond=self._nanos // 1_000,
        )

    # This override is technically incompatible, but it's very convenient
    # and it's not part of the public API
    @classmethod
    def _from_py_unchecked(  # type: ignore[override]
        cls, d: _datetime, nanos: int, tz: TimeZone, /
    ) -> ZonedDateTime:
        assert not d.microsecond
        assert 0 <= nanos < 1_000_000_000
        self = _object_new(cls)
        self._py_dt = d
        self._nanos = nanos
        self._tz = tz
        return self

    def exact_eq(self, other: ZonedDateTime, /) -> bool:
        if type(other) is not type(self):
            raise TypeError("exact_eq() requires same-type arguments")
        return (
            self._py_dt == other._py_dt  # same moment in time
            and self._nanos == other._nanos
            and self._tz == other._tz  # same timezone
            # don't need to check the offset, it's implied by the above
        )

    # An override with shortcut for efficiency if the timezone stays the same
    def to_tz(self, tz: str, /) -> ZonedDateTime:
        if (_tz := get_tz(tz)) == self._tz:
            return self
        return self._from_py_unchecked(
            _to_tz(self._py_dt, _tz), self._nanos, _tz
        )

    def __repr__(self) -> str:
        return (
            f'ZonedDateTime("{_format_date(self._py_dt, False)} '
            f"{_format_time(self._py_dt, self._nanos, 'auto', False)}"
            f"{_format_offset(self._py_dt.utcoffset(), False)}"  # type: ignore[arg-type]
            f"[{self._tz.key or '<system timezone without ID>'}]\")"
        )

    # a custom pickle implementation with a smaller payload
    def __reduce__(self) -> tuple[object, ...]:
        if (key := self._tz.key) is None:
            raise ValueError(
                "ZonedDateTime with unknown timezone ID cannot be pickled"
            )
        return (
            _unpkl_zoned,
            (
                pack(
                    "<HBBBBBil",
                    *self._py_dt.timetuple()[:6],
                    self._nanos,
                    int(self._py_dt.utcoffset().total_seconds()),  # type: ignore[union-attr]
                ),
                key,
            ),
        )


# A separate function is needed for unpickling, because the
# constructor doesn't accept positional tz and fold arguments as
# required by __reduce__.
# Also, it allows backwards-compatible changes to the pickling format.
def _unpkl_zoned(data: bytes, tzid: str) -> ZonedDateTime:
    *args, nanos, offset_secs = unpack("<HBBBBBil", data)
    return ZonedDateTime._from_py_unchecked(
        # mypy thinks tzinfo is passed twice. We know it's not.
        _datetime(*args, tzinfo=mk_fixed_tzinfo(offset_secs)),  # type: ignore[misc]
        nanos,
        get_tz(tzid),
    )


@final
class PlainDateTime(_LocalTime):
    """A date and time-of-day without any timezone information.

    Represents "wall clock" time as people observe it locally.
    It can't be mixed with exact-time types (e.g. ``Instant``,
    ``ZonedDateTime``) without explicitly assuming a timezone or offset.

    >>> PlainDateTime(2024, 3, 10, 15, 30)
    PlainDateTime("2024-03-10 15:30:00")

    Can also be constructed from an ISO 8601 string
    or a standard library :class:`~datetime.datetime`:

    >>> PlainDateTime("2024-03-10T15:30:00")
    PlainDateTime("2024-03-10 15:30:00")

    Convert to an exact time type by supplying a timezone or offset:

    >>> dt = PlainDateTime(2024, 3, 10, 15, 30)
    >>> dt.assume_tz("Europe/Amsterdam")
    ZonedDateTime("2024-03-10 15:30:00+01:00[Europe/Amsterdam]")
    >>> dt.assume_fixed_offset(5)
    OffsetDateTime("2024-03-10 15:30:00+05:00")

    When to use this type:

    - You need to express a date and time as it would appear on a
      wall clock, independent of timezone.
    - You receive a datetime without timezone information and need
      to represent this lack of information in the type system.
    - You're working in a context where timezones and DST
      transitions truly don't apply (e.g. a simulation).
    """

    # Overloads are for a nice autodoc
    # Proper typing is done in the stubs
    if not TYPE_CHECKING:

        @overload
        def __init__(self, iso_string: str, /) -> None: ...

        @overload
        def __init__(self, py_dt: _datetime, /) -> None: ...

        @overload
        def __init__(
            self,
            year: int,
            month: int,
            day: int,
            hour: int = 0,
            minute: int = 0,
            second: int = 0,
            *,
            nanosecond: int = 0,
        ) -> None: ...

    def __init__(
        self,
        year: int,
        month: int,
        day: int,
        hour: int = 0,
        minute: int = 0,
        second: int = 0,
        *,
        nanosecond: int = 0,
    ) -> None:
        if nanosecond < 0 or nanosecond >= 1_000_000_000:
            raise ValueError(f"nanosecond out of range: {nanosecond}")
        self._py_dt = _datetime(year, month, day, hour, minute, second)
        self._nanos = nanosecond

    __init__ = add_alternate_constructors(__init__, py_type=_datetime)

    def format_iso(
        self,
        *,
        unit: Literal[
            "hour",
            "minute",
            "second",
            "millisecond",
            "microsecond",
            "nanosecond",
            "auto",
        ] = "auto",
        basic: bool = False,
        sep: Literal["T", " "] = "T",
    ) -> str:
        """Convert to the popular ISO format ``YYYY-MM-DDTHH:MM:SS``

        The inverse of the ``parse_iso()`` method.
        """
        return _format_dt(self._py_dt, self._nanos, "", unit, sep, basic)

    @classmethod
    def parse_iso(cls, s: str, /) -> PlainDateTime:
        """Parse the popular ISO format ``YYYY-MM-DDTHH:MM:SS``

        The inverse of the ``format_iso()`` method.

        >>> PlainDateTime.parse_iso("2020-08-15T23:12:00")
        PlainDateTime("2020-08-15 23:12:00")
        """
        self = _object_new(cls)
        self._init_from_iso(s)
        return self

    def _init_from_iso(self, s: str) -> None:
        self._py_dt, self._nanos = datetime_from_iso(s)

    @classmethod
    def from_py_datetime(cls, d: _datetime, /) -> PlainDateTime:
        """Create an instance from a "naive" standard library ``datetime`` object"""
        self = _object_new(cls)
        self._init_from_py(d)
        return self

    def _init_from_py(self, d: _datetime) -> None:
        if d.tzinfo is not None:
            raise ValueError(
                "Can only create PlainDateTime from a naive datetime, "
                f"got datetime with tzinfo={d.tzinfo!r}"
            )
        self._py_dt = _strip_subclasses(d.replace(microsecond=0))
        self._nanos = d.microsecond * 1_000

    if not TYPE_CHECKING:  # for a nicer autodoc

        @overload
        def replace(
            self,
            *,
            year: int = ...,
            month: int = ...,
            day: int = ...,
            hour: int = ...,
            minute: int = ...,
            second: int = ...,
            nanosecond: int = ...,
        ) -> PlainDateTime: ...

    def replace(self, /, **kwargs: Any) -> PlainDateTime:
        """Construct a new instance with the given fields replaced."""
        _check_invalid_replace_kwargs(kwargs)
        nanos = _pop_nanos_kwarg(kwargs, self._nanos)
        return self._from_py_unchecked(self._py_dt.replace(**kwargs), nanos)

    def replace_date(self, d: Date, /) -> PlainDateTime:
        """Construct a new instance with the date replaced."""
        return self._from_py_unchecked(
            _datetime.combine(d._py_date, self._py_dt.time()), self._nanos
        )

    def replace_time(self, t: Time, /) -> PlainDateTime:
        """Construct a new instance with the time replaced."""
        return self._from_py_unchecked(
            _datetime.combine(self._py_dt.date(), t._py), t._nanos
        )

    def __hash__(self) -> int:
        return hash((self._py_dt, self._nanos))

    def __eq__(self, other: object) -> bool:
        """Compare objects for equality.
        Only ever equal to other :class:`PlainDateTime` instances with the
        same values.

        Warning
        -------
        To comply with the Python data model, this method can't
        raise a :exc:`TypeError` when comparing with other types.
        Although it seems to be the sensible response, it would result in
        `surprising behavior <https://stackoverflow.com/a/33417512>`__
        when using values as dictionary keys.

        Use mypy's ``--strict-equality`` flag to detect and prevent this.

        >>> PlainDateTime(2020, 8, 15, 23) == PlainDateTime(2020, 8, 15, 23)
        True
        >>> PlainDateTime(2020, 8, 15, 23, 1) == PlainDateTime(2020, 8, 15, 23)
        False
        >>> PlainDateTime(2020, 8, 15) == Instant.from_utc(2020, 8, 15)
        False  # Use mypy's --strict-equality flag to detect this.
        """
        if not isinstance(other, PlainDateTime):
            return NotImplemented
        return (self._py_dt, self._nanos) == (other._py_dt, other._nanos)

    MIN: ClassVar[PlainDateTime]
    """The minimum representable value of this type."""
    MAX: ClassVar[PlainDateTime]
    """The maximum representable value of this type."""

    def __lt__(self, other: PlainDateTime) -> bool:
        if not isinstance(other, PlainDateTime):
            return NotImplemented
        return (self._py_dt, self._nanos) < (other._py_dt, other._nanos)

    def __le__(self, other: PlainDateTime) -> bool:
        if not isinstance(other, PlainDateTime):
            return NotImplemented
        return (self._py_dt, self._nanos) <= (other._py_dt, other._nanos)

    def __gt__(self, other: PlainDateTime) -> bool:
        if not isinstance(other, PlainDateTime):
            return NotImplemented
        return (self._py_dt, self._nanos) > (other._py_dt, other._nanos)

    def __ge__(self, other: PlainDateTime) -> bool:
        if not isinstance(other, PlainDateTime):
            return NotImplemented
        return (self._py_dt, self._nanos) >= (other._py_dt, other._nanos)

    def __add__(self, delta: DateDelta | TimeDelta) -> PlainDateTime:
        """Add a delta to this datetime.

        Warning
        -------
        Adding exact time units (a ``TimeDelta``) to a ``PlainDateTime`` does
        not account for timezone transitions that may occur in the interval.
        Use ``.assume_tz('<tz>') + delta`` if you know the timezone.
        Suppress with the
        :func:`~whenever.ignore_timezone_unaware_arithmetic_warning` context manager;
        Python's standard warning filters also apply.
        """
        if isinstance(delta, DateDelta):
            return self._from_py_unchecked(
                _datetime.combine(
                    (self.date() + delta._date_part)._py_date,
                    self._py_dt.time(),
                ),
                self._nanos,
            )
        elif isinstance(delta, TimeDelta):
            if not _ignore_timezone_unaware_arithmetic_warning.get():
                warn(
                    PLAIN_SHIFT_UNAWARE_MSG,
                    TimeZoneUnawareArithmeticWarning,
                    stacklevel=2,
                )
            delta_secs, nanos = divmod(
                delta._total_ns + self._nanos, 1_000_000_000
            )
            return self._from_py_unchecked(
                self._py_dt + _timedelta(seconds=delta_secs), nanos
            )
        return NotImplemented

    @overload
    def __sub__(self, other: PlainDateTime) -> TimeDelta: ...

    @overload
    def __sub__(self, other: TimeDelta | DateDelta) -> PlainDateTime: ...

    def __sub__(
        self, other: PlainDateTime | TimeDelta | DateDelta
    ) -> TimeDelta | PlainDateTime:
        """Subtract a delta or calculate the duration to another plain datetime.

        Warning
        -------
        Subtracting a ``TimeDelta`` or measuring the difference between two
        ``PlainDateTime`` values does not account for timezone transitions that
        may occur in the interval. Use :meth:`~whenever.PlainDateTime.assume_tz`
        to convert to a ``ZonedDateTime`` first for accurate results.
        Suppress with the
        :func:`~whenever.ignore_timezone_unaware_arithmetic_warning` context manager;
        Python's standard warning filters also apply.
        """
        if isinstance(other, TimeDelta):
            if not _ignore_timezone_unaware_arithmetic_warning.get():
                warn(
                    PLAIN_SHIFT_UNAWARE_MSG,
                    TimeZoneUnawareArithmeticWarning,
                    stacklevel=2,
                )
            delta_secs, nanos = divmod(
                -other._total_ns + self._nanos, 1_000_000_000
            )
            return self._from_py_unchecked(
                self._py_dt + _timedelta(seconds=delta_secs), nanos
            )
        elif isinstance(other, PlainDateTime):
            if not _ignore_timezone_unaware_arithmetic_warning.get():
                warn(
                    PLAIN_DIFF_UNAWARE_MSG,
                    TimeZoneUnawareArithmeticWarning,
                    stacklevel=2,
                )
            py_delta = self._py_dt - other._py_dt
            return TimeDelta(
                seconds=py_delta.days * 86_400 + py_delta.seconds,
                nanoseconds=self._nanos - other._nanos,
            )
        elif isinstance(other, (DateDelta, DateTimeDelta)):
            return self + -other
        else:
            return NotImplemented

    def difference(
        self, other: PlainDateTime, /, *, ignore_dst: bool = _UNSET
    ) -> TimeDelta:
        """Calculate the difference between two times without a timezone.

        .. deprecated:: 0.10.0

            The ``difference()`` method is deprecated, use the subtraction operator or
            :meth:`since` method instead.
        """
        warn(
            "The difference() method is deprecated, use the subtraction operator or since() method instead. ",
            WheneverDeprecationWarning,
            stacklevel=2,
        )
        py_delta = self._py_dt - other._py_dt
        return TimeDelta(
            seconds=py_delta.days * 86_400 + py_delta.seconds,
            nanoseconds=self._nanos - other._nanos,
        )

    @overload
    def since(
        self,
        b: PlainDateTime,
        /,
        *,
        unit: DeltaUnitStr,
        round_mode: RoundModeStr = ...,
        round_increment: int = ...,
    ) -> int: ...

    @overload
    def since(
        self,
        b: PlainDateTime,
        /,
        *,
        units: Sequence[DeltaUnitStr],
        round_mode: RoundModeStr = ...,
        round_increment: int = ...,
    ) -> ItemizedDelta: ...

    def since(
        self,
        b: PlainDateTime,
        /,
        *,
        unit: DeltaUnitStr | None = None,
        units: Sequence[DeltaUnitStr] | None = None,
        round_mode: RoundModeStr = "trunc",
        round_increment: int = 1,
    ) -> ItemizedDelta | int:
        """Calculate the duration since another PlainDateTime,
        in terms of the specified units.

        >>> d1 = PlainDateTime(2020, 8, 15, 23, 12)
        >>> d2 = PlainDateTime(2020, 8, 14, 22)
        >>> d1.since(d2, units=["hours", "minutes"],
        ...          round_increment=15,
        ...          round_mode="ceil")
        ItemizedDelta("PT25h15m")
        """
        return _plain_since(self, b, unit, units, round_mode, round_increment)

    @overload
    def until(
        self,
        b: PlainDateTime,
        /,
        *,
        unit: DeltaUnitStr,
        round_mode: RoundModeStr = ...,
        round_increment: int = ...,
    ) -> int: ...

    @overload
    def until(
        self,
        b: PlainDateTime,
        /,
        *,
        units: Sequence[DeltaUnitStr],
        round_mode: RoundModeStr = ...,
        round_increment: int = ...,
    ) -> ItemizedDelta: ...

    def until(
        self,
        b: PlainDateTime,
        /,
        *,
        unit: DeltaUnitStr | None = None,
        units: Sequence[DeltaUnitStr] | None = None,
        round_mode: RoundModeStr = "trunc",
        round_increment: int = 1,
    ) -> ItemizedDelta | int:
        """Inverse of the ``since()`` method. See :meth:`since` for more information."""
        return b.since(  # type: ignore[call-overload, no-any-return]
            self,
            unit=unit,
            units=units,
            round_mode=round_mode,
            round_increment=round_increment,
        )

    @overload
    def add(
        self, d: AnyDelta, /, *, ignore_dst: bool = ...
    ) -> PlainDateTime: ...

    @overload
    def add(
        self,
        *,
        years: int = ...,
        months: int = ...,
        weeks: int = ...,
        days: int = ...,
        hours: float = ...,
        minutes: float = ...,
        seconds: float = ...,
        milliseconds: float = ...,
        microseconds: float = ...,
        nanoseconds: int = ...,
        ignore_dst: bool = ...,
    ) -> PlainDateTime: ...

    @no_type_check
    def add(self, *args, **kwargs) -> PlainDateTime:
        """Add a time amount to this datetime.

        Warning
        -------
        Adding **exact time units** (e.g. hours, seconds) to a ``PlainDateTime``
        does not account for timezone transitions that may occur in the interval.
        Use ``.assume_tz('<tz>') + delta`` if you know the timezone.
        Suppress with the
        :func:`~whenever.ignore_timezone_unaware_arithmetic_warning` context manager;
        Python's standard warning filters also apply.
        """
        return self._shift(1, *args, **kwargs)

    @overload
    def subtract(
        self, d: AnyDelta, /, *, ignore_dst: bool = ...
    ) -> PlainDateTime: ...

    @overload
    def subtract(
        self,
        *,
        years: int = ...,
        months: int = ...,
        weeks: int = ...,
        days: int = ...,
        hours: float = ...,
        minutes: float = ...,
        seconds: float = ...,
        milliseconds: float = ...,
        microseconds: float = ...,
        nanoseconds: int = ...,
        ignore_dst: bool = ...,
    ) -> PlainDateTime: ...

    @no_type_check
    def subtract(self, *args, **kwargs) -> PlainDateTime:
        """Subtract a time amount from this datetime.

        See :meth:`add` for more information.
        """
        return self._shift(-1, *args, **kwargs)

    @no_type_check
    def _shift(
        self,
        sign: int,
        arg: AnyDelta | _UNSET = _UNSET,
        /,
        *,
        ignore_dst: bool = _UNSET,
        **kwargs,
    ) -> PlainDateTime:
        if ignore_dst is not _UNSET:
            warn(
                "The `ignore_dst` argument is deprecated and replaced with warnings.",
                WheneverDeprecationWarning,
                stacklevel=3,
            )

        if kwargs:
            if arg is _UNSET:
                return self._shift_kwargs(sign, **kwargs)
            raise TypeError("Cannot mix positional and keyword arguments")

        elif arg is not _UNSET:
            return self._shift_kwargs(
                sign,
                months=arg._date_part._months,
                days=arg._date_part._days,
                nanoseconds=arg._time_part._total_ns,
            )
        else:
            return self

    def _shift_kwargs(
        self,
        sign: int,
        *,
        years: int = 0,
        months: int = 0,
        weeks: int = 0,
        days: int = 0,
        hours: float = 0,
        minutes: float = 0,
        seconds: float = 0,
        milliseconds: float = 0,
        microseconds: float = 0,
        nanoseconds: int = 0,
    ) -> PlainDateTime:
        py_dt_with_new_date = self.replace_date(
            self.date()
            ._add_months(sign * (years * 12 + months))
            ._add_days(sign * (weeks * 7 + days)),
        )._py_dt

        tdelta = sign * TimeDelta(
            hours=hours,
            minutes=minutes,
            seconds=seconds,
            milliseconds=milliseconds,
            microseconds=microseconds,
            nanoseconds=nanoseconds,
        )
        if tdelta and not _ignore_timezone_unaware_arithmetic_warning.get():
            warn(
                PLAIN_SHIFT_UNAWARE_MSG,
                TimeZoneUnawareArithmeticWarning,
                stacklevel=4,
            )

        delta_secs, nanos = divmod(
            tdelta._total_ns + self._nanos, 1_000_000_000
        )
        return self._from_py_unchecked(
            (py_dt_with_new_date + _timedelta(seconds=delta_secs)),
            nanos,
        )

    @classmethod
    def parse_strptime(cls, s: str, /, *, format: str) -> PlainDateTime:
        """Parse a plain datetime using the standard library ``strptime()`` method.

        >>> PlainDateTime.parse_strptime("2020-08-15", format="%d/%m/%Y_%H:%M")
        PlainDateTime("2020-08-15 00:00:00")

        Note
        ----
        This method defers to the standard library ``strptime()`` method,
        which may behave differently in different Python versions.
        It also only supports up to microsecond precision.

        Important
        ---------
        There may not be an offset in the format string.
        This means you CANNOT use the directives ``%z``, ``%Z``, or ``%:z``.
        Use ``OffsetDateTime`` to parse datetimes with an offset.
        """
        parsed = _datetime.strptime(s, format)
        if parsed.tzinfo is not None:
            raise ValueError(
                "Parsed datetime can't have an offset. "
                "Do not use %z, %Z, or %:z in the format string"
            )
        return cls._from_py_unchecked(
            parsed.replace(microsecond=0), parsed.microsecond * 1_000
        )

    def assume_utc(self) -> Instant:
        """Assume the datetime is in UTC, creating an ``Instant``.

        >>> PlainDateTime(2020, 8, 15, 23, 12).assume_utc()
        Instant("2020-08-15 23:12:00Z")
        """
        return Instant._from_py_unchecked(
            self._py_dt.replace(tzinfo=_UTC), self._nanos
        )

    def assume_fixed_offset(
        self, offset: int | TimeDelta, /
    ) -> OffsetDateTime:
        """Assume the datetime has the given offset, creating an ``OffsetDateTime``.

        >>> PlainDateTime(2020, 8, 15, 23, 12).assume_fixed_offset(+2)
        OffsetDateTime("2020-08-15 23:12:00+02:00")
        """
        return OffsetDateTime._from_py_unchecked(
            self._py_dt.replace(tzinfo=_load_offset(offset)), self._nanos
        )

    def assume_tz(
        self, tz: str, /, disambiguate: DisambiguateStr = "compatible"
    ) -> ZonedDateTime:
        """Assume the datetime is in the given timezone,
        creating a ``ZonedDateTime``.

        Note
        ----
        The local time may be ambiguous in the given timezone
        (e.g. during a DST transition). You can explicitly
        specify how to handle such a situation using the ``disambiguate`` argument.
        See `the documentation <https://whenever.rtfd.io/en/latest/guide/ambiguity.html>`__
        for more information.

        >>> d = PlainDateTime(2020, 8, 15, 23, 12)
        >>> d.assume_tz("Europe/Amsterdam", disambiguate="raise")
        ZonedDateTime("2020-08-15 23:12:00+02:00[Europe/Amsterdam]")
        """
        return ZonedDateTime._from_py_unchecked(
            resolve_ambiguity(self._py_dt, _tz := get_tz(tz), disambiguate),
            self._nanos,
            _tz,
        )

    def assume_system_tz(
        self, disambiguate: DisambiguateStr = "compatible"
    ) -> ZonedDateTime:
        """Assume the datetime is in the system timezone,
        creating a ``ZonedDateTime``.

        Note
        ----
        The local time may be ambiguous in the system timezone
        (e.g. during a DST transition). You can explicitly
        specify how to handle such a situation using the ``disambiguate`` argument.
        See `the documentation <https://whenever.rtfd.io/en/latest/guide/ambiguity.html>`__
        for more information.

        >>> d = PlainDateTime(2020, 8, 15, 23, 12)
        >>> # assuming system timezone is America/New_York
        >>> d.assume_system_tz(disambiguate="raise")
        ZonedDateTime("2020-08-15 23:12:00-04:00[America/New_York]")
        """
        return ZonedDateTime._from_py_unchecked(
            resolve_ambiguity(
                self._py_dt, tz := get_system_tz(), disambiguate
            ),
            self._nanos,
            tz,
        )

    def round(
        self,
        unit: Literal[
            "day",
            "hour",
            "minute",
            "second",
            "millisecond",
            "microsecond",
            "nanosecond",
        ] = "second",
        increment: int = 1,
        mode: RoundModeStr = "half_even",
    ) -> PlainDateTime:
        """Round the datetime to the specified unit and increment.
        Different rounding modes are available.

        >>> d = PlainDateTime(2020, 8, 15, 23, 24, 18)
        >>> d.round("day")
        PlainDateTime("2020-08-16 00:00:00")
        >>> d.round("minute", increment=15, mode="floor")
        PlainDateTime("2020-08-15 23:15:00")

        Note
        ----
        This method has similar behavior to the ``round()`` method of
        Temporal objects in JavaScript.
        """
        return self._round_unchecked(
            increment_to_ns_for_datetime(unit, increment),
            mode,
            86_400_000_000_000,
        )

    def _round_unchecked(
        self, increment_ns: int, mode: str, day_ns: int
    ) -> PlainDateTime:
        rounded_time, next_day = self.time()._round_unchecked(
            increment_ns, mode, day_ns
        )
        return self.date()._add_days(next_day).at(rounded_time)

    def __repr__(self) -> str:
        return f"PlainDateTime(\"{str(self).replace('T', ' ')}\")"

    # a custom pickle implementation with a smaller payload
    def __reduce__(self) -> tuple[object, ...]:
        return (
            _unpkl_local,
            (pack("<HBBBBBi", *self._py_dt.timetuple()[:6], self._nanos),),
        )


# A separate unpickling function allows us to make backwards-compatible changes
# to the pickling format in the future
@no_type_check
def _unpkl_local(data: bytes) -> PlainDateTime:
    *args, nanos = unpack("<HBBBBBi", data)
    return PlainDateTime._from_py_unchecked(_datetime(*args), nanos)


_ignore_days_not_always_24h_warning: ContextVar[bool] = ContextVar(
    "_ignore_days_not_always_24h_warning", default=False
)

_ignore_potentially_stale_offset_warning: ContextVar[bool] = ContextVar(
    "_ignore_potentially_stale_offset_warning", default=False
)

_ignore_timezone_unaware_arithmetic_warning: ContextVar[bool] = ContextVar(
    "_ignore_timezone_unaware_arithmetic_warning", default=False
)


class PotentialDstBugWarning(UserWarning):
    """Base class for warnings about potential DST-related bugs in user code.

    This is not raised directly, but serves as the parent for
    :class:`~whenever.DaysNotAlways24HoursWarning`,
    :class:`~whenever.PotentiallyStaleOffsetWarning`, and
    :class:`~whenever.TimeZoneUnawareArithmeticWarning`.
    You can catch or filter all DST-related warnings at once
    by targeting this class.
    """


class DaysNotAlways24HoursWarning(PotentialDstBugWarning):
    """Raised when a :class:`~whenever.TimeDelta` operation assumes
    that calendar days are always exactly 24 hours long.

    Due to DST transitions, a calendar day in a specific timezone
    can be 23 or 25 hours (or even other lengths in rare cases).
    When you add days using exact-time arithmetic (i.e. treating
    each day as 86,400 seconds), the result may be off by the
    length of the DST transition.

    The typical fix is to use calendar-based arithmetic
    (e.g. :class:`~whenever.ItemizedDelta`) instead of exact-time
    shifts when the number of calendar days matters.
    Suppress this warning with the
    :func:`~whenever.ignore_days_not_always_24h_warning` context
    manager (or Python's standard warning filters) if 24-hour days are
    intentional.
    """


# A custom warnings class to prevent silent deprecation warnings in user code.
# See https://sethmlarson.dev/deprecations-via-warnings-dont-work-for-python-libraries
class WheneverDeprecationWarning(UserWarning):
    """Raised when a deprecated feature of the ``whenever`` library is used.

    This is a custom warning class (not a subclass of
    :class:`DeprecationWarning`) so that deprecation warnings from this
    library are visible by default—unlike standard ``DeprecationWarning``,
    which Python silences in production code.
    """


# TODO: can the names be a bit shorter? Everything related (e.g. context managers) have also looooong names
class PotentiallyStaleOffsetWarning(PotentialDstBugWarning):
    """Raised when an operation on an :class:`~whenever.OffsetDateTime` may
    result in a datetime with an incorrect UTC offset.

    A fixed UTC offset (e.g. ``+02:00``) carries no timezone rules--it doesn't
    know about DST, historical offset changes, or future policy decisions that
    could change which offset a region observes. After shifting, rounding, or
    replacing fields of an ``OffsetDateTime``, the original offset is preserved
    verbatim. If the region has since changed its rules, the preserved offset
    may be wrong, silently producing a timestamp that is off by the difference.

    The typical fix is to work with :class:`~whenever.ZonedDateTime` instead,
    which always keeps the offset in sync with the timezone rules.
    Alternatively, suppress this warning with the
    :func:`~whenever.ignore_potentially_stale_offset_warning` context manager
    (or Python's standard warning filters) when the fixed offset is intentional
    and correct.
    """


class TimeZoneUnawareArithmeticWarning(PotentialDstBugWarning):
    """Raised when exact-time arithmetic is performed on a
    :class:`~whenever.PlainDateTime` without timezone context.

    A :class:`~whenever.PlainDateTime` carries no timezone information.
    When you add or subtract exact time units (hours, minutes, seconds) or
    measure the difference between two :class:`~whenever.PlainDateTime` values,
    the computation treats every hour as equal. This warning is always emitted
    because there is no way to know whether a timezone transition falls in the
    interval--if one does, the result may be off by an hour or more.

    For example, adding 2 hours to ``2023-03-26 01:30`` (Amsterdam) gives
    ``03:30``, but clocks jumped from 02:00 to 03:00 that morning, so only
    1 real hour has passed.

    The typical fix is to call :meth:`~whenever.PlainDateTime.assume_tz` first
    so the timezone is known, then perform the arithmetic on the resulting
    :class:`~whenever.ZonedDateTime`.
    Suppress this warning with the
    :func:`~whenever.ignore_timezone_unaware_arithmetic_warning` context manager
    (or Python's standard warning filters) if you: (a) explicitly accept
    potentially incorrect results, (b) know no transitions occur in the
    interval, or (c) are working with clock times not representing a real-world
    timezone (e.g. a simulation).
    """


class ImplicitlyIgnoringDST(TypeError):
    """Raised when an operation would silently ignore DST transitions.

    .. deprecated:: 0.10.0

       This exception is deprecated and will be removed in a future version.
    """


OFFSET_NOW_STALE_MSG = (
    "Getting the current time as an OffsetDateTime with a fixed UTC offset may be incorrect: "
    "the offset doesn't update when DST or other timezone rules change. "
    "Use ZonedDateTime.now('<tz>') if you know the timezone, or "
    "Instant.now() for timezone-agnostic exact time. "
    "Suppress with the whenever.ignore_potentially_stale_offset_warning() context manager, "
    "or with Python's standard warning filters."
)

OFFSET_FROM_TIMESTAMP_STALE_MSG = (
    "Converting a UNIX timestamp to OffsetDateTime with a fixed UTC offset may produce "
    "an incorrect result: you can't know from the offset alone whether DST "
    "is in effect at this timestamp. "
    "Use ZonedDateTime.from_timestamp(ts, tz='<tz>') if you know the timezone, or "
    "Instant.from_timestamp() for timezone-agnostic exact time. "
    "Suppress with the whenever.ignore_potentially_stale_offset_warning() context manager, "
    "or with Python's standard warning filters."
)

OFFSET_REPLACE_STALE_MSG = (
    "Replacing fields of an OffsetDateTime keeps the fixed UTC offset, which may no longer "
    "be correct after the change (e.g. replacing the month on a European-timezone datetime "
    "may move it into a different DST period). "
    "Convert to ZonedDateTime first (using .assume_tz()) for timezone-aware field replacement. "
    "Suppress with the whenever.ignore_potentially_stale_offset_warning() context manager, "
    "or with Python's standard warning filters."
)

OFFSET_SHIFT_STALE_MSG = (
    "Shifting an OffsetDateTime keeps the fixed UTC offset, which may not match the "
    "actual offset after a DST or other timezone transition "
    "(e.g. adding 1 day to 2024-03-09 12:00-07:00 gives 2024-03-10 12:00-07:00, "
    "but if this offset represents Denver, Colorado (America/Denver), "
    "the actual offset changed to -06:00 on that date). "
    "Convert to ZonedDateTime first (using .assume_tz()) for timezone-aware arithmetic. "
    "Suppress with the whenever.ignore_potentially_stale_offset_warning() context manager, "
    "or with Python's standard warning filters."
)

OFFSET_ROUND_STALE_MSG = (
    "Rounding an OffsetDateTime keeps the fixed UTC offset, which may not be accurate "
    "in the rare case that the rounded time crosses a DST or other timezone boundary. "
    "Convert to a ZonedDateTime first (using .assume_tz()) for timezone-aware rounding. "
    "Suppress with the whenever.ignore_potentially_stale_offset_warning() context manager, "
    "or with Python's standard warning filters."
)

PLAIN_SHIFT_UNAWARE_MSG = (
    "Shifting a PlainDateTime by exact time units does not account for timezone transitions "
    "that may occur in the interval "
    "(e.g. adding 2 hours to 2023-03-26 01:30 in Amsterdam crosses the spring-forward "
    "transition, so only 1 real hour has passed). "
    "Use .assume_tz('<tz>') + delta if you know the timezone. "
    "Suppress with the whenever.ignore_timezone_unaware_arithmetic_warning() context manager, "
    "or with Python's standard warning filters."
)

PLAIN_DIFF_UNAWARE_MSG = (
    "Calculating the difference between two PlainDateTime values does not account for "
    "timezone transitions that may have occurred between them: "
    "for example, PlainDateTime(2023, 3, 26, 3, 0) - PlainDateTime(2023, 3, 26, 1, 0) "
    "gives 2h, but in Amsterdam clocks jumped from 2:00 to 3:00 that morning, "
    "so only 1 real hour elapsed. "
    "Use .assume_tz('<tz>') for both values if you know the timezone. "
    "Suppress with the whenever.ignore_timezone_unaware_arithmetic_warning() context manager, "
    "or with Python's standard warning filters."
)

CANNOT_ROUND_DAY_MSG = (
    "Cannot round to day, because days do not have a fixed length. "
    "Due to daylight saving time, some days have 23 or 25 hours."
    "If you wish to round to exaxtly 24 hours, use `round('hour', increment=24)`."
)

ZONEINFO_NO_KEY_MSG = (
    "Can't determine the IANA timezone ID of the given datetime: "
    "The 'key' attribute of the datetime's ZoneInfo object is None. \n"
    "This typically means the ZoneInfo object represents the system timezone with "
    "an unknown ID. As an alternative, you can use OffsetDateTime.from_py_datetime(), "
    "but be aware this is a lossy conversion that only preserves "
    "the current UTC offset and discards future daylight saving rules. "
    "Please note that a timezone abbreviation like 'CEST' from datetime.tzname() "
    "is not a valid IANA timezone ID and cannot be used here."
)

FORMAT_ISO_NO_TZ_MSG = (
    "This ZonedDateTime has no timezone ID and cannot be formatted in the "
    "standard ISO format, which requires it. "
    "This typically means the ZonedDateTime was created from a system timezone "
    "with an unknown ID. To format without the timezone designator, set the "
    "`tz=` argument to 'never' or 'auto'."
)

DAYS_NOT_ALWAYS_24H_MSG = (
    "This operation assumes days are exactly 24 hours. "
    "Calendar days may be 23 or 25 hours long during DST transitions. "
    "If you're working with UTC, or deliberately want fixed-length days, this is correct. "
    "For DST-aware operations, consider using ZonedDateTime arithmetic instead. "
    "Suppress this warning with `with whenever.ignore_days_not_always_24h_warning():`."
)

IGNORE_DST_DEPRECATED_MSG = (
    "The `ignore_dst` parameter is deprecated and replaced with a warning."
)

# Deprecated ignore_dst-era messages, kept only so that
# generate_docstrings.py emits them for the Rust extension
# (which still references them). Remove once Rust is migrated.
ADJUST_LOCAL_DATETIME_MSG = "deprecated: ignore_dst-era message"
DIFF_LOCAL_MSG = "deprecated: ignore_dst-era message"
DIFF_OPERATOR_LOCAL_MSG = "deprecated: ignore_dst-era message"
SHIFT_LOCAL_MSG = "deprecated: ignore_dst-era message"


def _to_tz(dt: _datetime, tz: TimeZone) -> _datetime:
    return dt.astimezone(
        mk_fixed_tzinfo(tz.offset_for_instant(int(dt.timestamp())))
    )


_MAX_ORDINAL = _date.max.toordinal()


def _from_epoch(ts: int, tz: TimeZone) -> _datetime:
    # NOTE: we can't use the obvious datetime.fromtimestamp() here, because it
    # may give errors on extreme values on some platforms.
    if (ordinal := ts // 86_400 + 719_163) < 1 or ordinal > _MAX_ORDINAL:
        raise OverflowError("Time out of range")
    return _to_tz(
        (
            _datetime.fromordinal(ordinal) + _timedelta(seconds=ts % 86_400)
        ).replace(tzinfo=_UTC),
        tz,
    )


def _load_offset(offset: int | TimeDelta, /) -> _timezone:
    if isinstance(offset, int):
        return _timezone(_timedelta(hours=offset))
    elif isinstance(offset, TimeDelta):
        if offset._total_ns % 1_000_000_000:
            raise ValueError("Offset must be a whole number of seconds")
        return _timezone(offset.py_timedelta())
    else:
        raise TypeError(
            "offset must be an int or TimeDelta, e.g. `hours(2.5)`"
        )


# Helpers that pre-compute/lookup as much as possible
_no_tzinfo_fold_or_ms = {"tzinfo", "fold", "microsecond"}.isdisjoint
_fromtimestamp = _datetime.fromtimestamp


def _format_date(d: _date, basic: bool) -> str:
    sep = "" if basic else "-"
    return f"{d.year:04d}{sep}{d.month:02d}{sep}{d.day:02d}"


def _format_time(
    t: Union[_time, _datetime], ns: _Nanos, precision: str, basic: bool
) -> str:
    sep = "" if basic else ":"
    if precision == "hour":
        return f"{t.hour:02d}"
    elif precision == "minute":
        return f"{t.hour:02d}{sep}{t.minute:02d}"
    else:
        return (
            f"{t.hour:02d}{sep}{t.minute:02d}{sep}{t.second:02d}"
            + _format_nanos(ns, precision)
        )


def _format_offset(offset: _timedelta | Literal["Z", ""], basic: bool) -> str:
    if isinstance(offset, str):
        return offset
    sep = "" if basic else ":"
    sign = "-" if offset.days == -1 else "+"
    hours, remainder = divmod(abs(int(offset.total_seconds())), 3600)
    minutes, seconds = divmod(remainder, 60)
    if seconds:
        return f"{sign}{int(hours):02d}{sep}{int(minutes):02d}{sep}{int(seconds):02d}"
    else:
        return f"{sign}{int(hours):02d}{sep}{int(minutes):02d}"


def _format_nanos(ns: _Nanos, precision: str) -> str:
    ns_str = f".{ns:09d}"
    if precision == "auto":
        return bool(ns) * ns_str.rstrip("0")
    elif precision == "nanosecond":
        return ns_str
    elif precision == "microsecond":
        return ns_str[:7]
    elif precision == "millisecond":
        return ns_str[:4]
    elif precision in ("second", "hour", "minute"):
        return ""
    else:
        raise ValueError(f"Invalid precision unit: {precision!r}. ")


def _format_dt(
    dt: _datetime,
    ns: _Nanos,
    offset: _timedelta | Literal["Z", ""],
    unit: str,
    sep: Literal["T", " "] = "T",
    basic: bool = False,
) -> str:
    if sep not in ("T", " "):
        raise ValueError("sep must be either 'T' or ' '")
    elif type(basic) is not bool:
        raise TypeError("basic must be a boolean")

    return (
        f"{_format_date(dt, basic)}{sep}"
        f"{_format_time(dt, ns, unit, basic)}"
        f"{_format_offset(offset, basic)}"
    )


def _check_invalid_replace_kwargs(kwargs: Any) -> None:
    if not _no_tzinfo_fold_or_ms(kwargs):
        raise TypeError(
            "tzinfo, fold, or microsecond are not allowed arguments"
        )


def _pop_nanos_kwarg(kwargs: Any, default: int) -> int:
    nanos = kwargs.pop("nanosecond", default)
    if type(nanos) is not int:
        raise TypeError("nanosecond must be an int")
    elif not 0 <= nanos < 1_000_000_000:
        raise ValueError("Invalid nanosecond value")
    return nanos


def _unit_index(u: str, units: Sequence[str]) -> int:
    try:
        return units.index(u)
    except ValueError:
        raise ValueError(
            f"Invalid unit {u!r}. Unit must be one of "
            + ", ".join(repr(u) for u in units)
        )


def _plain_since(
    self: PlainDateTime,
    b: PlainDateTime,
    unit: DeltaUnitStr | None,
    units: Sequence[DeltaUnitStr] | None,
    round_mode: RoundModeStr,
    round_increment: int,
    warn_msg: str | None = PLAIN_DIFF_UNAWARE_MSG,
    warn_cls: type[Warning] = TimeZoneUnawareArithmeticWarning,
    warn_check: ContextVar[bool] = _ignore_timezone_unaware_arithmetic_warning,
) -> ItemizedDelta | int:
    """Shared since() implementation for PlainDateTime and OffsetDateTime.
    Days are always 24 hours (no DST adjustments).
    """
    units, single_unit_mode = _normalize_unit_or_units(
        unit, units, valid_units=DELTA_UNITS
    )
    cal_units, exact_units = _split_calendar_and_exact_units(units)

    if warn_msg and exact_units and not warn_check.get():
        warn(
            warn_msg,
            warn_cls,
            stacklevel=3,
        )

    sign: Literal[1, -1] = 1 if self >= b else -1

    target_date = self.date()._py_date
    # Adjust target_date so the exact remainder has the same sign
    # as the overall difference.
    if sign == 1:
        while b.replace_date(Date._from_py_unchecked(target_date)) > self:
            target_date -= _timedelta(days=1)
    else:
        while b.replace_date(Date._from_py_unchecked(target_date)) < self:
            target_date += _timedelta(days=1)

    cal_results, trunc_date, expand_date = date_diff(
        target_date,
        b._py_dt.date(),
        1 if exact_units else round_increment,
        cal_units,
        sign,
    )
    trunc = b.replace_date(
        Date._from_py_unchecked(resolve_leap_day(trunc_date)),
    )
    expand = b.replace_date(
        Date._from_py_unchecked(resolve_leap_day(expand_date)),
    )

    smallest_unit = units[-1]
    result = cast(dict[DeltaUnitStr, int], cal_results)
    if exact_units:
        diff_td = TimeDelta(
            seconds=(self._py_dt - trunc._py_dt).days * 86_400
            + (self._py_dt - trunc._py_dt).seconds,
            nanoseconds=self._nanos - trunc._nanos,
        )
        result.update(
            diff_td._in_units(  # type: ignore[arg-type]
                exact_units,
                round_increment=round_increment,
                round_mode=round_mode,
                round_unit=_UNSET,
            )
        )
    else:
        if round_mode != "trunc":
            self_ns = (
                (self._py_dt - trunc._py_dt).days * 86_400_000_000_000
                + (self._py_dt - trunc._py_dt).seconds * 1_000_000_000
                + self._nanos
                - trunc._nanos
            )
            expand_ns = (
                (expand._py_dt - trunc._py_dt).days * 86_400_000_000_000
                + (expand._py_dt - trunc._py_dt).seconds * 1_000_000_000
                + expand._nanos
                - trunc._nanos
            )
            result[smallest_unit] = custom_round(
                result[smallest_unit],
                abs(self_ns),
                abs(expand_ns),
                round_mode,
                round_increment,
                sign,
            )

    if single_unit_mode:
        return result.pop(smallest_unit) * sign

    # mypy false positive: 'keywords must be strings' (but they're string literals!)
    return ItemizedDelta._from_signed(  # type: ignore[misc]
        sign if any(result.values()) else 0, **result
    )


def _offset_since(
    self: OffsetDateTime,
    b: OffsetDateTime,
    unit: DeltaUnitStr | None,
    units: Sequence[DeltaUnitStr] | None,
    round_mode: RoundModeStr,
    round_increment: int,
) -> ItemizedDelta | int:
    """since() implementation for OffsetDateTime.
    Calendar units require both datetimes to have the same offset.
    """
    resolved_units, single_unit_mode = _normalize_unit_or_units(
        unit, units, valid_units=DELTA_UNITS
    )
    cal_units, exact_units = _split_calendar_and_exact_units(resolved_units)
    same_offset = self._py_dt.utcoffset() == b._py_dt.utcoffset()

    if cal_units and not same_offset:
        raise ValueError(
            "Calendar units can only be used to compare OffsetDateTimes "
            "with the same offset"
        )

    if same_offset:
        # Same offset: delegate to the plain implementation
        return _plain_since(
            self.to_plain(),
            b.to_plain(),
            unit,
            units,
            round_mode,
            round_increment,
            warn_msg=None,
        )
    else:
        # Different offsets, exact units only: compute via TimeDelta
        diff = self._subtract_operator(b)
        sign: Sign = 1 if diff._total_ns >= 0 else -1
        result = diff._in_units(
            exact_units,
            round_increment=round_increment,
            round_mode=round_mode,
            round_unit=_UNSET,
        )
        if single_unit_mode:
            return result.pop(exact_units[-1]) * sign

        return ItemizedDelta._from_signed(  # type: ignore[misc]
            sign if any(result.values()) else 0, **result
        )


_Tstr = TypeVar("_Tstr", bound=str)


def _normalize_unit_or_units(
    unit: str | None,
    units: Sequence[str] | None,
    valid_units: Sequence[_Tstr],
) -> tuple[Sequence[_Tstr], bool]:
    if unit is not None and units is not None:
        raise TypeError("Cannot specify both 'unit' and 'units'")
    elif unit:
        _unit_index(unit, valid_units)  # validate unit
        return [unit], True  # type: ignore[list-item]
    elif units is None:
        raise TypeError("Must specify either 'unit' or 'units'")
    elif not units:
        raise ValueError("'units' cannot be an empty sequence")
    else:
        if sorted(units, key=lambda u: _unit_index(u, valid_units)) != list(
            units
        ):
            raise ValueError("units must be in decreasing order of size")
        elif len(set(units)) != len(units):
            raise ValueError("units cannot contain duplicates")
        return units, False  # type: ignore[return-value]


def _split_calendar_and_exact_units(
    units: Sequence[DeltaUnitStr],
) -> tuple[Sequence[DateDeltaUnitStr], Sequence[ExactDeltaUnitStr]]:
    split_index = next(
        (i for i, u in enumerate(units) if u not in DATE_DELTA_UNITS),
        len(units),
    )
    return units[:split_index], units[split_index:]  # type: ignore[return-value]


# Use this to strip any incoming datetime classes down to instances
# of the datetime.datetime class exactly.
def _strip_subclasses(dt: _datetime) -> _datetime:
    if type(dt) is _datetime:
        return dt
    else:
        return _datetime(
            dt.year,
            dt.month,
            dt.day,
            dt.hour,
            dt.minute,
            dt.second,
            dt.microsecond,
            dt.tzinfo,
            fold=dt.fold,
        )


Instant.MIN = Instant._from_py_unchecked(
    _datetime.min.replace(tzinfo=_UTC),
    0,
)
Instant.MAX = Instant._from_py_unchecked(
    _datetime.max.replace(tzinfo=_UTC, microsecond=0),
    999_999_999,
)
PlainDateTime.MIN = PlainDateTime._from_py_unchecked(_datetime.min, 0)
PlainDateTime.MAX = PlainDateTime._from_py_unchecked(
    _datetime.max.replace(microsecond=0), 999_999_999
)


def years(i: int, /) -> DateDelta:
    """Create a :class:`~DateDelta` with the given number of years.
    ``years(1) == DateDelta(years=1)``

    .. deprecated:: 0.10.0

        Use :class:`~whenever.ItemizedDateDelta` instead
    """
    return DateDelta(years=i)


def months(i: int, /) -> DateDelta:
    """Create a :class:`~DateDelta` with the given number of months.
    ``months(1) == DateDelta(months=1)``

    .. deprecated:: 0.10.0

        Use :class:`~whenever.ItemizedDateDelta` instead
    """
    return DateDelta(months=i)


def weeks(i: int, /) -> DateDelta:
    """Create a :class:`~DateDelta` with the given number of weeks.
    ``weeks(1) == DateDelta(weeks=1)``

    .. deprecated:: 0.10.0

        Use :class:`~whenever.ItemizedDateDelta` instead
    """
    return DateDelta(weeks=i)


def days(i: int, /) -> DateDelta:
    """Create a :class:`~DateDelta` with the given number of days.
    ``days(1) == DateDelta(days=1)``

    .. deprecated:: 0.10.0

        Use :class:`~whenever.ItemizedDateDelta` instead
    """
    return DateDelta(days=i)


def hours(i: float, /) -> TimeDelta:
    """Create a :class:`~TimeDelta` with the given number of hours.
    ``hours(1) == TimeDelta(hours=1)``
    """
    return TimeDelta(hours=i)


def minutes(i: float, /) -> TimeDelta:
    """Create a :class:`TimeDelta` with the given number of minutes.
    ``minutes(1) == TimeDelta(minutes=1)``
    """
    return TimeDelta(minutes=i)


def seconds(i: float, /) -> TimeDelta:
    """Create a :class:`TimeDelta` with the given number of seconds.
    ``seconds(1) == TimeDelta(seconds=1)``
    """
    return TimeDelta(seconds=i)


def milliseconds(i: float, /) -> TimeDelta:
    """Create a :class:`TimeDelta` with the given number of milliseconds.
    ``milliseconds(1) == TimeDelta(milliseconds=1)``
    """
    return TimeDelta(milliseconds=i)


def microseconds(i: float, /) -> TimeDelta:
    """Create a :class:`TimeDelta` with the given number of microseconds.
    ``microseconds(1) == TimeDelta(microseconds=1)``
    """
    return TimeDelta(microseconds=i)


def nanoseconds(i: int, /) -> TimeDelta:
    """Create a :class:`TimeDelta` with the given number of nanoseconds.
    ``nanoseconds(1) == TimeDelta(nanoseconds=1)``
    """
    return TimeDelta(nanoseconds=i)


def _patch_time_frozen(inst: Instant) -> None:
    global time_ns

    def time_ns() -> int:
        return inst.timestamp_nanos()


def _patch_time_keep_ticking(inst: Instant) -> None:
    global time_ns

    _patched_at = time_ns()
    _time_ns = time_ns

    def time_ns() -> int:
        return inst.timestamp_nanos() + _time_ns() - _patched_at


def _unpatch_time() -> None:
    global time_ns

    from time import time_ns


# This alias exists because we don't want to expose the _ExactTime abstract class
# in the public API, but we do want to use it in type annotations.
_ExactTimeAlias = Union[Instant, OffsetDateTime, ZonedDateTime]


# We expose the public members in the root of the module.
# For clarity, we remove the "_pywhenever" part from the names,
# since this is an implementation detail.
# This is important for usability, as users would otherwise
# be directed to an internal module they shouldn't use directly,
# also because these internal modules aren't available in the Rust version!
# This does mess up sphinx autodoc's introspection a bit, so we fix that below.
# see https://github.com/sphinx-doc/sphinx/issues/3673
if not SPHINX_RUNNING:  # pragma: no branch
    for name in __all__ + "_LocalTime _ExactTime _ExactAndLocalTime".split():
        member = locals()[name]
        if (
            getattr(member, "__module__", "").startswith("whenever")
        ):  # pragma: no branch
            member.__module__ = "whenever"

    # clear up loop variables so they don't leak into the namespace
    del name
    del member


for _unpkl in (
    _unpkl_date,
    _unpkl_ym,
    _unpkl_md,
    _unpkl_time,
    _unpkl_tdelta,
    _unpkl_dtdelta,
    _unpkl_idelta,
    _unpkl_iddelta,
    _unpkl_ddelta,
    _unpkl_utc,
    _unpkl_offset,
    _unpkl_zoned,
    _unpkl_local,
):
    _unpkl.__module__ = "whenever"


# disable further subclassing
final(_Base)
final(_ExactTime)
final(_LocalTime)
final(_ExactAndLocalTime)
final(_BasicConversions)
