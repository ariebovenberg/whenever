"""Pure-Python components that are shared between the Rust extension
and the pure-Python implementation.

Types defined here are always pure Python, even when the Rust extension is active.
This prevents unnecessary duplication for these simple concepts.
They aren't performance-critical anyway.
"""

from __future__ import annotations

import enum
from datetime import date as _date
from operator import index as _index
from struct import pack, unpack
from typing import TYPE_CHECKING, Any, ClassVar, no_type_check, overload

from ._common import (
    DUMMY_LEAP_YEAR,
    SPHINX_RUNNING,
    UNSET,
    _Base,
    add_alternate_constructors,
    final,
    warn_deprecated,
)
from ._math import days_in_month, is_leap
from ._parse import _strict_int, monthday_from_iso, yearmonth_from_iso

# Avoid circular import: Date is referenced in type annotations only
if TYPE_CHECKING:
    from whenever import Date

_object_new = object.__new__


def _nth_weekday_of_month(
    year: int, month: int, n: int, weekday: Weekday
) -> int:
    """Core logic for finding the nth weekday in a month.

    ``n`` is nonzero; negative counts from the end.
    Returns the day of month, or raises ValueError if it doesn't exist.
    """
    dim = days_in_month(year, month)
    first_dow = _date(year, month, 1).isoweekday()
    first = 1 + (weekday.value - first_dow) % 7
    count = (dim - first) // 7 + 1
    if abs(n) > count:
        raise ValueError(
            f"n={n} is out of range: {weekday!r} occurs {count} times "
            f"in {year:04d}-{month:02d}"
        )
    return first + (n - 1 if n > 0 else count + n) * 7


class Weekday(enum.Enum):
    """Day of the week; ``.value`` corresponds with ISO numbering
    (monday=1, sunday=7).

    All members are also available as constants in the module namespace:

    >>> from whenever import Weekday, MONDAY, SUNDAY
    >>> MONDAY is Weekday.MONDAY
    True

    :class:`~whenever.Date` and the three datetimes with a local date
    return ``Weekday`` from their :meth:`~whenever.Date.day_of_week` method;
    :class:`~whenever.IsoWeekDate` exposes it as its
    :attr:`~whenever.IsoWeekDate.weekday` attribute:

    >>> Date(2024, 12, 25).day_of_week()
    Weekday.WEDNESDAY
    >>> IsoWeekDate("2024-W52-3").weekday
    Weekday.WEDNESDAY
    """

    MONDAY = 1
    TUESDAY = 2
    WEDNESDAY = 3
    THURSDAY = 4
    FRIDAY = 5
    SATURDAY = 6
    SUNDAY = 7

    def __repr__(self) -> str:
        return f"Weekday.{self.name}"


# Convenience constants, also available as top-level whenever.MONDAY etc.
MONDAY = Weekday.MONDAY
TUESDAY = Weekday.TUESDAY
WEDNESDAY = Weekday.WEDNESDAY
THURSDAY = Weekday.THURSDAY
FRIDAY = Weekday.FRIDAY
SATURDAY = Weekday.SATURDAY
SUNDAY = Weekday.SUNDAY


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
    """The minimum possible value of this type."""
    MAX: ClassVar[YearMonth]
    """The maximum possible value of this type."""

    # Overloads for a nice autodoc.
    # Proper typing of the constructors is handled in the type stubs
    if not TYPE_CHECKING:

        @overload
        def __init__(self, iso_string: str, /) -> None: ...

        @overload
        def __init__(self, year: int, month: int) -> None: ...

    def __init__(self, year: int, month: int) -> None:
        self._py = _date(year, month, 1)

    __init__ = add_alternate_constructors(__init__, None)

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
        def replace(
            self, *, year: int = ..., month: int = ...
        ) -> YearMonth: ...

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

    def add(self, *, years: int = 0, months: int = 0) -> YearMonth:
        """Shift this year-month by a number of years and months.

        >>> YearMonth(2021, 11).add(months=3)
        YearMonth("2022-02")
        >>> YearMonth(2021, 1).add(years=-1, months=-1)
        YearMonth("2019-12")

        An :class:`ItemizedDateDelta` is a mapping, so it unpacks into the
        keyword arguments:

        >>> YearMonth(2024, 3).add(**ItemizedDateDelta(years=1, months=2))
        YearMonth("2025-05")

        Raises ``ValueError`` if the result falls outside ``MIN``..``MAX``.
        """
        year, month = divmod(
            self.year * 12 + self.month - 1 + years * 12 + months,
            12,
        )
        return YearMonth._from_py_unchecked(
            self._py.replace(year=year, month=month + 1)
        )

    def subtract(self, *, years: int = 0, months: int = 0) -> YearMonth:
        """Shift this year-month backwards by a number of years and months.
        Equivalent to :meth:`add` with negated arguments.

        >>> YearMonth(2021, 1).subtract(months=1)
        YearMonth("2020-12")
        """
        return self.add(years=-years, months=-months)

    def on_day(self, day: int, /) -> Date:
        """Create a date from this year-month with a given day

        >>> YearMonth(2021, 1).on_day(2)
        Date("2021-01-02")

        Note
        ----
        This method will raise a ``ValueError`` if the day does not exist
        in that month.
        """
        from whenever import Date

        return Date(self._py.replace(day=day))

    def __str__(self) -> str:
        return self.format_iso()

    def __repr__(self) -> str:
        return f'YearMonth("{self}")'

    def __eq__(self, other: object, /) -> bool:
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

    def __lt__(self, other: YearMonth, /) -> bool:
        if not isinstance(other, YearMonth):
            return NotImplemented
        return self._py < other._py

    def __le__(self, other: YearMonth, /) -> bool:
        if not isinstance(other, YearMonth):
            return NotImplemented
        return self._py <= other._py

    def __gt__(self, other: YearMonth, /) -> bool:
        if not isinstance(other, YearMonth):
            return NotImplemented
        return self._py > other._py

    def __ge__(self, other: YearMonth, /) -> bool:
        if not isinstance(other, YearMonth):
            return NotImplemented
        return self._py >= other._py

    def __hash__(self) -> int:
        return hash(self._py)

    def days_in_month(self) -> int:
        """Number of days in this year-month (28--31)

        >>> YearMonth(2024, 2).days_in_month()
        29
        >>> YearMonth(2023, 2).days_in_month()
        28
        """
        return days_in_month(self._py.year, self._py.month)

    def days_in_year(self) -> int:
        """Number of days in this year (365 or 366)

        >>> YearMonth(2024, 1).days_in_year()
        366
        """
        return 366 if is_leap(self._py.year) else 365

    def in_leap_year(self) -> bool:
        """Whether this year-month's year is a leap year

        >>> YearMonth(2024, 1).in_leap_year()
        True
        >>> YearMonth(2023, 1).in_leap_year()
        False
        """
        return is_leap(self._py.year)

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


_DUMMY_LEAP_YEAR = DUMMY_LEAP_YEAR


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
    """The minimum possible value of this type."""
    MAX: ClassVar[MonthDay]
    """The maximum possible value of this type."""

    # Overloads for a nice autodoc.
    # Proper typing of the constructors is handled in the type stubs
    if not TYPE_CHECKING:

        @overload
        def __init__(self, iso_string: str, /) -> None: ...

        @overload
        def __init__(self, month: int, day: int) -> None: ...

    def __init__(self, month: int, day: int) -> None:
        try:
            self._py = _date(_DUMMY_LEAP_YEAR, month, day)
        except ValueError:
            raise ValueError("invalid date") from None

    __init__ = add_alternate_constructors(__init__, None)

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
        def replace(self, *, month: int = ..., day: int = ...) -> MonthDay: ...

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
        try:
            py = self._py.replace(**kwargs)
        except ValueError:
            # the stdlib message would name the dummy leap year
            raise ValueError("invalid date") from None
        return MonthDay._from_py_unchecked(py)

    def in_year(self, year: int, /) -> Date:
        """Create a date from this month-day in a given year

        >>> MonthDay(8, 1).in_year(2025)
        Date("2025-08-01")

        Note
        ----
        This method will raise a ``ValueError`` if the month-day is a leap day
        and the year is not a leap year.
        """
        from whenever import Date

        return Date(self._py.replace(year=year))

    def is_leap_day(self) -> bool:
        """Whether the month-day is February 29th

        >>> MonthDay(2, 29).is_leap_day()
        True
        >>> MonthDay(3, 1).is_leap_day()
        False
        """
        return self._py.month == 2 and self._py.day == 29

    def is_leap(self) -> bool:
        """Check if the month-day is February 29th.

        .. deprecated:: 0.11
           Use :meth:`is_leap_day` instead.
        """
        warn_deprecated(
            "is_leap() is deprecated; use is_leap_day() instead",
            stacklevel=2,
        )
        return self.is_leap_day()

    def __str__(self) -> str:
        return self.format_iso()

    def __repr__(self) -> str:
        return f'MonthDay("{self}")'

    def __eq__(self, other: object, /) -> bool:
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

    def __lt__(self, other: MonthDay, /) -> bool:
        if not isinstance(other, MonthDay):
            return NotImplemented
        return self._py < other._py

    def __le__(self, other: MonthDay, /) -> bool:
        if not isinstance(other, MonthDay):
            return NotImplemented
        return self._py <= other._py

    def __gt__(self, other: MonthDay, /) -> bool:
        if not isinstance(other, MonthDay):
            return NotImplemented
        return self._py > other._py

    def __ge__(self, other: MonthDay, /) -> bool:
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


def _iso_week_int(value: Any, name: str, /) -> int:
    try:
        result: int = _index(value)
    except TypeError:
        raise TypeError(f"{name} must be an integer") from None
    return result


def _is_long_year(year: int) -> bool:
    """Whether an ISO week year has 53 weeks.

    A year has 53 weeks if January 1 is a Thursday,
    or December 31 is a Thursday (which is equivalent to:
    Jan 1 is Thursday, or the year is a leap year and Jan 1 is Wednesday).
    """
    jan1_dow = _date(year, 1, 1).isoweekday()
    return jan1_dow == 4 or (jan1_dow == 3 and is_leap(year))


@final
class IsoWeekDate(_Base):
    """An ISO 8601 week date—a year, week number, and weekday.

    The ISO week year may differ from the Gregorian year at year boundaries.

    >>> iwd = IsoWeekDate(2024, 1, Weekday.MONDAY)
    IsoWeekDate("2024-W01-1")

    Can also be constructed from an ISO 8601 string:

    >>> IsoWeekDate("2024-W01-1")
    IsoWeekDate("2024-W01-1")
    """

    __slots__ = ("_year", "_week", "_weekday")

    MIN: ClassVar[IsoWeekDate]
    """The minimum possible value of this type."""
    MAX: ClassVar[IsoWeekDate]
    """The maximum possible value of this type."""

    if not TYPE_CHECKING:

        @overload
        def __init__(self, iso_string: str, /) -> None: ...

        @overload
        def __init__(self, year: int, week: int, weekday: Weekday) -> None: ...

    def __init__(self, year: int, week: int, weekday: Weekday) -> None:
        year = _iso_week_int(year, "year")
        week = _iso_week_int(week, "week")
        if not isinstance(weekday, Weekday):
            raise TypeError("weekday must be a Weekday")
        try:
            max_weeks = 53 if _is_long_year(year) else 52
        except ValueError:
            raise ValueError("invalid date") from None
        if not 1 <= week <= max_weeks:
            raise ValueError(f"week must be between 1 and {max_weeks}")
        # Validate by round-tripping through the stdlib. Its message would
        # name the derived Gregorian year, which the caller never passed.
        try:
            _date.fromisocalendar(year, week, weekday.value)
        except ValueError:
            raise ValueError("invalid date") from None
        self._year = year
        self._week = week
        self._weekday = weekday

    __init__ = add_alternate_constructors(__init__, None)

    def _init_from_iso(self, s: str) -> None:
        year, week, day = _parse_iso_week_date(s)
        self._year = year
        self._week = week
        self._weekday = Weekday(day)

    @classmethod
    def _from_parts_unchecked(
        cls, year: int, week: int, weekday: Weekday
    ) -> IsoWeekDate:
        self = _object_new(cls)
        self._year = year
        self._week = week
        self._weekday = weekday
        return self

    @property
    def year(self) -> int:
        """The ISO week year

        >>> IsoWeekDate(2024, 1, Weekday.MONDAY).year
        2024
        """
        return self._year

    @property
    def week(self) -> int:
        """The ISO week number (1--53)

        >>> IsoWeekDate(2024, 1, Weekday.MONDAY).week
        1
        """
        return self._week

    @property
    def weekday(self) -> Weekday:
        """The day of the week

        >>> IsoWeekDate(2024, 1, Weekday.MONDAY).weekday
        Weekday.MONDAY
        """
        return self._weekday

    def date(self) -> Date:
        """Convert to the corresponding Gregorian :class:`~whenever.Date`

        >>> IsoWeekDate(2025, 1, Weekday.MONDAY).date()
        Date("2024-12-30")
        """
        from whenever import Date

        return Date(
            _date.fromisocalendar(self._year, self._week, self._weekday.value)
        )

    def weeks_in_year(self) -> int:
        """Number of weeks in this ISO week year (52 or 53)

        >>> IsoWeekDate(2004, 53, Weekday.FRIDAY).weeks_in_year()
        53
        >>> IsoWeekDate(2024, 1, Weekday.MONDAY).weeks_in_year()
        52
        """
        return 53 if _is_long_year(self._year) else 52

    def replace(
        self,
        *,
        year: int = UNSET,
        week: int = UNSET,
        weekday: Weekday = UNSET,
    ) -> IsoWeekDate:
        """Create a new instance with the given fields replaced

        A week beyond the year's count raises :class:`ValueError`.

        >>> IsoWeekDate(2024, 1, Weekday.MONDAY).replace(week=10)
        IsoWeekDate("2024-W10-1")
        """
        return IsoWeekDate(
            self._year if year is UNSET else year,
            self._week if week is UNSET else week,
            self._weekday if weekday is UNSET else weekday,
        )

    def format_iso(self, *, basic: bool = False) -> str:
        """Format as an ISO 8601 week date string

        >>> IsoWeekDate(2024, 1, Weekday.MONDAY).format_iso()
        '2024-W01-1'
        >>> IsoWeekDate(2024, 1, Weekday.MONDAY).format_iso(basic=True)
        '2024W011'
        """
        if basic:
            return f"{self._year:04d}W{self._week:02d}{self._weekday.value}"
        return f"{self._year:04d}-W{self._week:02d}-{self._weekday.value}"

    @classmethod
    def parse_iso(cls, s: str, /) -> IsoWeekDate:
        """Parse an ISO 8601 week date string

        >>> IsoWeekDate.parse_iso("2024-W01-1")
        IsoWeekDate("2024-W01-1")
        """
        obj = _object_new(cls)
        obj._init_from_iso(s)
        return obj

    def __str__(self) -> str:
        return self.format_iso()

    def __repr__(self) -> str:
        return f'IsoWeekDate("{self}")'

    def __eq__(self, other: object, /) -> bool:
        """Compare for equality

        >>> IsoWeekDate(2024, 1, Weekday.MONDAY) == IsoWeekDate(2024, 1, Weekday.MONDAY)
        True
        """
        if not isinstance(other, IsoWeekDate):
            return NotImplemented
        return (
            self._year == other._year
            and self._week == other._week
            and self._weekday is other._weekday
        )

    def __lt__(self, other: IsoWeekDate, /) -> bool:
        if not isinstance(other, IsoWeekDate):
            return NotImplemented
        return (self._year, self._week, self._weekday.value) < (
            other._year,
            other._week,
            other._weekday.value,
        )

    def __le__(self, other: IsoWeekDate, /) -> bool:
        if not isinstance(other, IsoWeekDate):
            return NotImplemented
        return (self._year, self._week, self._weekday.value) <= (
            other._year,
            other._week,
            other._weekday.value,
        )

    def __gt__(self, other: IsoWeekDate, /) -> bool:
        if not isinstance(other, IsoWeekDate):
            return NotImplemented
        return (self._year, self._week, self._weekday.value) > (
            other._year,
            other._week,
            other._weekday.value,
        )

    def __ge__(self, other: IsoWeekDate, /) -> bool:
        if not isinstance(other, IsoWeekDate):
            return NotImplemented
        return (self._year, self._week, self._weekday.value) >= (
            other._year,
            other._week,
            other._weekday.value,
        )

    def __hash__(self) -> int:
        return hash((self._year, self._week, self._weekday))

    @no_type_check
    def __reduce__(self):
        return _unpkl_iwd, (
            pack("<hBB", self._year, self._week, self._weekday.value),
        )


@no_type_check
def _unpkl_iwd(data: bytes) -> IsoWeekDate:
    year, week, day = unpack("<hBB", data)
    return IsoWeekDate._from_parts_unchecked(year, week, Weekday(day))


def _parse_iso_week_date(s: str) -> tuple[int, int, int]:
    """Parse an ISO 8601 week date string like '2024-W01-1' or '2024W011'"""
    if not s.isascii():
        raise ValueError(f"invalid format: {s!r}")
    if len(s) == 10 and s[4] == "-" and s[5] == "W" and s[8] == "-":
        # Extended format: YYYY-Www-D
        year = _strict_int(s[:4])
        week = _strict_int(s[6:8])
        day = _strict_int(s[9])
    elif len(s) == 8 and s[4] == "W":
        # Basic format: YYYYWwwD
        year = _strict_int(s[:4])
        week = _strict_int(s[5:7])
        day = _strict_int(s[7])
    else:
        raise ValueError(f"invalid format: {s!r}")
    if not 1 <= day <= 7:
        raise ValueError(f"Invalid ISO weekday: {day}")
    max_weeks = 53 if _is_long_year(year) else 52
    if not 1 <= week <= max_weeks:
        raise ValueError(f"Invalid ISO week: {week}")
    return year, week, day


IsoWeekDate.MIN = IsoWeekDate._from_parts_unchecked(
    *_date.min.isocalendar()[:2], Weekday(_date.min.isocalendar()[2])
)
IsoWeekDate.MAX = IsoWeekDate._from_parts_unchecked(
    *_date.max.isocalendar()[:2], Weekday(_date.max.isocalendar()[2])
)

# Set __module__ so these types and unpickle functions appear as 'whenever.X'
# regardless of which backend (Rust or pure Python) loaded them.
if not SPHINX_RUNNING:  # pragma: no branch
    for _obj in (
        Weekday,
        YearMonth,
        MonthDay,
        IsoWeekDate,
        _unpkl_ym,
        _unpkl_md,
        _unpkl_iwd,
    ):
        _obj.__module__ = "whenever"
    del _obj


def _tzpath_from_env() -> tuple[str, ...]:
    import os

    try:
        env_var = os.environ["PYTHONTZPATH"]
    except KeyError:
        import sysconfig

        env_var = sysconfig.get_config_var("TZPATH")

    # FUTURE: include in test coverage
    if not env_var:
        return ()  # pragma: no cover

    raw_tzpath = env_var.split(os.pathsep)
    # according to spec, we're allowed to silently ignore invalid paths
    return tuple(filter(os.path.isabs, raw_tzpath))
