# The MIT License (MIT)
#
# Copyright (c) Arie Bovenberg
#
# Permission is hereby granted, free of charge, to any person obtaining a copy
# of this software and associated documentation files (the "Software"), to deal
# in the Software without restriction, including without limitation the rights
# to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
# copies of the Software, and to permit persons to whom the Software is
# furnished to do so, subject to the following conditions:
#
# The above copyright notice and this permission notice shall be included in all
# copies or substantial portions of the Software.
#
# THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
# IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
# FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
# AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
# LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
# OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE
# SOFTWARE.

# Maintainer's notes:
#
# - Why is everything in one file?
#   - Flat is better than nested
#   - It prevents circular imports since the classes 'know' about each other
#   - It's easier to vendor (i.e. copy-paste) this library if needed
# - There is some code duplication in this file. This is intentional:
#   - It makes it easier to understand the code
#   - It's sometimes necessary for the type checker
#   - It saves some overhead
from __future__ import annotations

__version__ = "0.6.0rc0"

import enum
import re
import sys
from abc import ABC, abstractmethod
from calendar import monthrange
from datetime import (
    date as _date,
    datetime as _datetime,
    time as _time,
    timedelta as _timedelta,
    timezone as _timezone,
)
from email.utils import format_datetime, parsedate_to_datetime
from math import fmod
from struct import pack, unpack
from time import time_ns
from typing import (
    TYPE_CHECKING,
    Any,
    Callable,
    ClassVar,
    Literal,
    Mapping,
    TypeVar,
    Union,
    no_type_check,
    overload,
)
from zoneinfo import ZoneInfo

__all__ = [
    # Date and time
    "Date",
    "Time",
    "UTCDateTime",
    "OffsetDateTime",
    "ZonedDateTime",
    "LocalSystemDateTime",
    "NaiveDateTime",
    # Deltas and time units
    "DateDelta",
    "TimeDelta",
    "DateTimeDelta",
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
    # Exceptions
    "SkippedTime",
    "AmbiguousTime",
    "InvalidOffset",
    # Constants
    "MONDAY",
    "TUESDAY",
    "WEDNESDAY",
    "THURSDAY",
    "FRIDAY",
    "SATURDAY",
    "SUNDAY",
    "Weekday",
]


class Weekday(enum.Enum):
    """The days of the week; ``.value`` corresponds with ISO numbering."""

    MONDAY = 1
    TUESDAY = 2
    WEDNESDAY = 3
    THURSDAY = 4
    FRIDAY = 5
    SATURDAY = 6
    SUNDAY = 7


MONDAY = Weekday.MONDAY
TUESDAY = Weekday.TUESDAY
WEDNESDAY = Weekday.WEDNESDAY
THURSDAY = Weekday.THURSDAY
FRIDAY = Weekday.FRIDAY
SATURDAY = Weekday.SATURDAY
SUNDAY = Weekday.SUNDAY

# Helpers that pre-compute/lookup as much as possible
_UTC = _timezone.utc
_object_new = object.__new__

_MAX_DELTA_MONTHS = 9999 * 12
_MAX_DELTA_DAYS = 9999 * 366
_MAX_DELTA_NANOS = _MAX_DELTA_DAYS * 24 * 3_600_000_000_000


def _make_default_format_parse_error(s: str) -> ValueError:
    return ValueError(f"Could not parse as default format string: {s!r}")


def _make_common_iso8601_parse_error(s: str) -> ValueError:
    return ValueError(f"Could not parse as common ISO 8601 string: {s!r}")


def _make_rfc3339_parse_error(s: str) -> ValueError:
    return ValueError(f"Could not parse as RFC 3339 string: {s!r}")


def _make_rfc2822_parse_error(s: str) -> ValueError:
    return ValueError(f"Could not parse as RFC 2822 string: {s!r}")


class _UNSET:
    pass  # sentinel for when no value is passed


class _ImmutableBase:
    __slots__ = ("__weakref__",)

    # Immutable classes don't need to be copied
    @no_type_check
    def __copy__(self):
        return self

    @no_type_check
    def __deepcopy__(self, _):
        return self


if TYPE_CHECKING:
    from typing import final
else:

    def final(cls):

        def init_subclass_not_allowed(cls, **kwargs):
            raise TypeError("Subclassing not allowed")

        cls.__init_subclass__ = init_subclass_not_allowed
        return cls


@final
class Date(_ImmutableBase):
    """A date without a time component

    Example
    -------
    >>> d = Date(2021, 1, 2)
    Date(2021-01-02)
    """

    __slots__ = ("_py_date",)

    MIN: ClassVar[Date]
    """The minimum possible date"""
    MAX: ClassVar[Date]
    """The maximum possible date"""

    def __init__(self, year: int, month: int, day: int) -> None:
        self._py_date = _date(year, month, day)

    @property
    def year(self) -> int:
        return self._py_date.year

    @property
    def month(self) -> int:
        return self._py_date.month

    @property
    def day(self) -> int:
        return self._py_date.day

    def __repr__(self) -> str:
        return f"Date({self})"

    def __eq__(self, other: object) -> bool:
        """Compare for equality

        Example
        -------
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

    def replace(self, **kwargs: Any) -> Date:
        """Create a new instance with the given fields replaced

        Example
        -------
        >>> d = Date(2021, 1, 2)
        >>> d.replace(day=3)
        Date(2021-01-03)

        """
        return Date.from_py_date(self._py_date.replace(**kwargs))

    def py_date(self) -> _date:
        """Convert to a standard library :class:`~datetime.date`"""
        return self._py_date

    # TODO: unchecked version
    # TODO: make other from_* methods just as strict
    @classmethod
    def from_py_date(cls, d: _date, /) -> Date:
        """Create from a :class:`~datetime.date`

        Example
        -------
        >>> Date.from_py_date(date(2021, 1, 2))
        Date(2021-01-02)
        """
        self = _object_new(cls)
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
        return self

    @classmethod
    def _from_py_unchecked(cls, d: _date, /) -> Date:
        self = _object_new(cls)
        self._py_date = d
        return self

    def add(
        self, *, years: int = 0, months: int = 0, weeks: int = 0, days: int = 0
    ) -> Date:
        """Add a components to a date.

        Components are added from largest to smallest.
        Trucation and wrapping is done after each step.

        Example
        -------
        >>> d = Date(2021, 1, 2)
        >>> d.add(years=1, months=2, days=3)
        Date(2022-03-05)
        >>> Date(2020, 2, 29).add(years=1)
        Date(2021-02-28)
        """
        return Date._from_py_unchecked(
            self._add_months(12 * years + months)._py_date
            + _timedelta(days, weeks=weeks)
        )

    def __add__(self, p: DateDelta) -> Date:
        """Add a delta to a date.
        Behaves the same as :meth:`add`
        """
        return (
            self.add(months=p._months, days=p._days)
            if isinstance(p, DateDelta)
            else NotImplemented
        )

    def subtract(
        self, *, years: int = 0, months: int = 0, weeks: int = 0, days: int = 0
    ) -> Date:
        """Subtract a components from a date.

        Components are subtracted from largest to smallest.
        Trucation and wrapping is done after each step.

        Example
        -------
        >>> d = Date(2021, 1, 2)
        >>> d.subtract(years=1, months=2, days=3)
        Date(2019-10-30)
        >>> Date(2021, 3, 1).subtract(years=1)
        Date(2020-03-01)
        """
        return self.add(years=-years, months=-months, weeks=-weeks, days=-days)

    def _add_months(self, mos: int) -> Date:
        year_overflow, month_new = divmod(self.month - 1 + mos, 12)
        month_new += 1
        year_new = self.year + year_overflow
        return Date(
            year_new,
            month_new,
            min(self.day, monthrange(year_new, month_new)[1]),
        )

    def _add_days(self, days: int) -> Date:
        return Date._from_py_unchecked(self._py_date + _timedelta(days))

    @overload
    def __sub__(self, d: DateDelta) -> Date: ...

    @overload
    def __sub__(self, d: Date) -> DateDelta: ...

    def __sub__(self, d: DateDelta | Date) -> Date | DateDelta:
        """Subtract a delta from a date, or subtract two dates

        Subtracting a delta works the same as :meth:`subtract`.

        >>> Date(2021, 1, 2) - DateDelta(weeks=1, days=3)
        Date(2020-12-26)

        The difference between two dates is calculated such that:

        >>> delta = d1 - d2
        >>> d2 + delta == d1  # always

        The following is not always true:

        >>> d1 - (d1 - d2) == d2  # not always true!
        >>> -(d2 - d1) == d1 - d2  # not always true!

        Examples:

        >>> Date(2023, 4, 15) - Date(2011, 6, 24)
        DateDelta(P12Y9M22D)
        >>> # Truncation
        >>> Date(2024, 4, 30) - Date(2023, 5, 31)
        DateDelta(P11M)
        >>> Date(2024, 3, 31) - Date(2023, 6, 30)
        DateDelta(P9M1D)
        >>> # the other way around, the result is different
        >>> Date(2023, 6, 30) - Date(2024, 3, 31)
        DateDelta(P-9M)
        """
        if isinstance(d, DateDelta):
            return self.subtract(months=d._months, days=d._days)
        elif isinstance(d, Date):
            mos = self.month - d.month + 12 * (self.year - d.year)
            shifted = d._add_months(mos)

            # yes, it's a bit duplicated, but preferable to being clever.
            if d > self:
                if shifted < self:  # i.e. we've overshot
                    mos += 1
                    shifted = d._add_months(mos)
                    dys = (
                        -shifted.day
                        - monthrange(self.year, self.month)[1]
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
                        + monthrange(shifted.year, shifted.month)[1]
                        + self.day
                    )
                else:
                    dys = self.day - shifted.day
            return DateDelta(months=mos, days=dys)
        return NotImplemented

    def day_of_week(self) -> Weekday:
        """The day of the week

        Example
        -------
        >>> Date(2021, 1, 2).day_of_week()
        Weekday.SATURDAY
        >>> Weekday.SATURDAY.value
        6  # the ISO value
        """
        return Weekday(self._py_date.isoweekday())

    def at(self, t: Time, /) -> NaiveDateTime:
        """Combine a date with a time to create a datetime

        Example
        -------
        >>> d = Date(2021, 1, 2)
        >>> d.at(Time(12, 30))
        NaiveDateTime(2021-01-02 12:30:00)

        You can use methods like :meth:`~NaiveDateTime.assume_utc`
        or :meth:`~NaiveDateTime.assume_in_tz` to make the result aware.
        """
        return NaiveDateTime.from_py_datetime(
            _datetime.combine(self._py_date, t._py_time)
        )

    def default_format(self) -> str:
        """The date in default format.

        Example
        -------
        >>> d = Date(2021, 1, 2)
        >>> d.default_format()
        '2021-01-02'
        """
        return self._py_date.isoformat()

    @classmethod
    def from_default_format(cls, s: str, /) -> Date:
        """Create from the default string representation.

        Inverse of :meth:`default_format`

        Example
        -------
        >>> Date.from_default_format("2021-01-02")
        Date(2021-01-02)
        """
        if s[5] == "W":
            # prevent isoformat from parsing week dates
            raise _make_default_format_parse_error(s)
        try:
            return cls.from_py_date(_date.fromisoformat(s))
        except ValueError:
            raise _make_default_format_parse_error(s)

    __str__ = default_format

    def common_iso8601(self) -> str:
        """Format as the common ISO 8601 date format.

        Inverse of :meth:`from_common_iso8601`.
        Equivalent to :meth:`default_format`.

        Example
        -------
        >>> Date(2021, 1, 2).common_iso8601()
        '2021-01-02'
        """
        return self._py_date.isoformat()

    @classmethod
    def from_common_iso8601(cls, s: str, /) -> Date:
        """Create from the common ISO 8601 date format ``YYYY-MM-DD``.
        Does not accept more "exotic" ISO 8601 formats.

        Inverse of :meth:`common_iso8601`.
        Equivalent to :meth:`from_default_format`.

        Example
        -------
        >>> Date.from_common_iso8601("2021-01-02")
        Date(2021-01-02)
        """
        try:
            return cls.from_default_format(s)
        except ValueError:
            raise _make_common_iso8601_parse_error(s)

    @no_type_check
    def __reduce__(self):
        return _unpkl_date, (pack("<HBB", self.year, self.month, self.day),)


# A separate unpickling function allows us to make backwards-compatible changes
# to the pickling format in the future
@no_type_check
def _unpkl_date(data: bytes) -> Date:
    return Date(*unpack("<HBB", data))


Date.MIN = Date.from_py_date(_date.min)
Date.MAX = Date.from_py_date(_date.max)


@final
class Time(_ImmutableBase):
    """Time of day without a date component

    Example
    -------
    >>> t = Time(12, 30, 0)
    Time(12:30:00)

    Default format
    --------------

    The default format is:

    .. code-block:: text

       HH:MM:SS(.ffffff)

    For example:

    .. code-block:: text

       12:30:11.004
    """

    __slots__ = ("_py_time", "_nanos")

    MIDNIGHT: ClassVar[Time]
    """The time at midnight"""
    NOON: ClassVar[Time]
    """The time at noon"""
    MAX: ClassVar[Time]
    """The maximum time, just before midnight"""

    def __init__(
        self,
        hour: int = 0,
        minute: int = 0,
        second: int = 0,
        nanosecond: int = 0,
    ) -> None:
        self._py_time = _time(hour, minute, second)
        if nanosecond < 0 or nanosecond >= 1_000_000_000:
            raise ValueError("Nanosecond out of range")
        self._nanos = nanosecond

    @property
    def hour(self) -> int:
        return self._py_time.hour

    @property
    def minute(self) -> int:
        return self._py_time.minute

    @property
    def second(self) -> int:
        return self._py_time.second

    @property
    def nanosecond(self) -> int:
        return self._nanos

    def py_time(self) -> _time:
        """Convert to a standard library :class:`~datetime.time`"""
        return self._py_time.replace(microsecond=self._nanos // 1_000)

    @classmethod
    def from_py_time(cls, t: _time, /) -> Time:
        """Create from a :class:`~datetime.time`

        Example
        -------
        >>> Time.from_py_time(time(12, 30, 0))
        Time(12:30:00)

        `fold` value is ignored.
        """
        if t.tzinfo is not None:
            raise ValueError("Time must be naive")
        elif type(t) is _time:
            pass
        elif isinstance(t, _time):
            # the only subclass-safe way to ensure we have exactly a datetime.time
            t = _time(t.hour, t.minute, t.second, t.microsecond)
        else:
            raise TypeError(f"Expected datetime.time, got {type(t)!r}")
        return cls._from_py_unchecked(
            t.replace(microsecond=0), t.microsecond * 1_000
        )

    @classmethod
    def _from_py_unchecked(cls, t: _time, nanos: int, /) -> Time:
        assert not t.microsecond
        self = _object_new(cls)
        self._py_time = t
        self._nanos = nanos
        return self

    def __repr__(self) -> str:
        return f"Time({self})"

    def __eq__(self, other: object) -> bool:
        """Compare for equality

        Example
        -------
        >>> t = Time(12, 30, 0)
        >>> t == Time(12, 30, 0)
        True
        >>> t == Time(12, 30, 1)
        False
        """
        if not isinstance(other, Time):
            return NotImplemented
        return (self._py_time, self._nanos) == (other._py_time, other._nanos)

    def __hash__(self) -> int:
        return hash((self._py_time, self._nanos))

    def __lt__(self, other: Time) -> bool:
        if not isinstance(other, Time):
            return NotImplemented
        return (self._py_time, self._nanos) < (other._py_time, self._nanos)

    def __le__(self, other: Time) -> bool:
        if not isinstance(other, Time):
            return NotImplemented
        return (self._py_time, self._nanos) <= (other._py_time, other._nanos)

    def __gt__(self, other: Time) -> bool:
        if not isinstance(other, Time):
            return NotImplemented
        return (self._py_time, self._nanos) > (other._py_time, other._nanos)

    def __ge__(self, other: Time) -> bool:
        if not isinstance(other, Time):
            return NotImplemented
        return (self._py_time, self._nanos) >= (other._py_time, other._nanos)

    def on(self, d: Date, /) -> NaiveDateTime:
        """Combine a time with a date to create a datetime

        Example
        -------
        >>> t = Time(12, 30)
        >>> t.on(Date(2021, 1, 2))
        NaiveDateTime(2021-01-02 12:30:00)

        Then, use methods like :meth:`~NaiveDateTime.assume_utc`
        or :meth:`~NaiveDateTime.assume_in_tz`
        to make the result aware.
        """
        return NaiveDateTime._from_py_unchecked(
            _datetime.combine(d._py_date, self._py_time),
            self._nanos,
        )

    def default_format(self) -> str:
        """The time in default format.

        Example
        -------
        >>> t = Time(12, 30, 0)
        >>> t.default_format()
        '12:30:00'
        """
        return (
            (self._py_time.isoformat() + f".{self._nanos:09d}").rstrip("0")
            if self._nanos
            else self._py_time.isoformat()
        )

    __str__ = default_format

    @classmethod
    def from_default_format(cls, s: str, /) -> Time:
        """Create from the default string representation.

        Inverse of :meth:`default_format`

        Example
        -------
        >>> Time.from_default_format("12:30:00")
        Time(12:30:00)

        Raises
        ------
        ValueError
            If the string does not match this exact format.
        """
        if (match := _match_time(s)) is None:
            raise ValueError(f"Invalid format: {s!r}")

        hours_str, minutes_str, seconds_str, nanos_str = match.groups()

        hours = int(hours_str)
        minutes = int(minutes_str)
        seconds = int(seconds_str)
        nanos = int(nanos_str.ljust(9, "0")) if nanos_str else 0
        return cls(hours, minutes, seconds, nanos)

    def common_iso8601(self) -> str:
        """Format as the common ISO 8601 time format.

        Inverse of :meth:`from_common_iso8601`.
        Equivalent to :meth:`default_format`.

        Example
        -------
        >>> Time(12, 30, 0).common_iso8601()
        '12:30:00'
        """
        return self.default_format()

    @classmethod
    def from_common_iso8601(cls, s: str, /) -> Time:
        """Create from the common ISO 8601 time format ``HH:MM:SS``.
        Does not accept more "exotic" ISO 8601 formats.

        Inverse of :meth:`common_iso8601`.
        Equivalent to :meth:`from_default_format`.

        Example
        -------
        >>> Time.from_common_iso8601("12:30:00")
        Time(12:30:00)
        """
        return cls.from_default_format(s)

    def replace(self, **kwargs: Any) -> Time:
        """Create a new instance with the given fields replaced

        Example
        -------
        >>> t = Time(12, 30, 0)
        >>> d.replace(minute=3, nanosecond=4_000)
        Time(12:03:00.000004)

        """
        _check_invalid_replace_kwargs(kwargs)
        nanos = _pop_nanos_kwarg(kwargs, self._nanos)
        return Time._from_py_unchecked(self._py_time.replace(**kwargs), nanos)

    @no_type_check
    def __reduce__(self):
        return (
            _unpkl_time,
            (
                pack(
                    "<BBBI",
                    self._py_time.hour,
                    self._py_time.minute,
                    self._py_time.second,
                    self._nanos,
                ),
            ),
        )


# A separate unpickling function allows us to make backwards-compatible changes
# to the pickling format in the future
def _unpkl_time(data: bytes) -> Time:
    h, m, s, ns = unpack("<BBBI", data)
    return Time(h, m, s, ns)


Time.MIDNIGHT = Time()
Time.NOON = Time(12)
Time.MAX = Time(23, 59, 59, 999_999_999)


@final
class TimeDelta(_ImmutableBase):
    """A duration consisting of a precise time: hours, minutes, (micro)seconds

    The inputs are normalized, so 90 minutes becomes 1 hour and 30 minutes,
    for example.

    Examples
    --------
    >>> d = TimeDelta(hours=1, minutes=30)
    TimeDelta(01:30:00)
    >>> d.in_minutes()
    90.0
    """

    __slots__ = ("_total_ns",)

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

    ZERO: ClassVar[TimeDelta]
    """A delta of zero"""
    MAX: ClassVar[TimeDelta]
    """The maximum possible delta"""
    MIN: ClassVar[TimeDelta]
    """The minimum possible delta"""
    _date_part: ClassVar[DateDelta]

    @property
    def _time_part(self) -> TimeDelta:
        """The time part, always equal to the delta itself"""
        return self

    def in_days_of_24h(self) -> float:
        return self._total_ns / 86_400_000_000_000

    def in_hours(self) -> float:
        """The total size in hours

        Example
        -------
        >>> d = TimeDelta(hours=1, minutes=30)
        >>> d.in_hours()
        1.5
        """
        return self._total_ns / 3_600_000_000_000

    def in_minutes(self) -> float:
        """The total size in minutes

        Example
        -------
        >>> d = TimeDelta(hours=1, minutes=30, seconds=30)
        >>> d.in_minutes()
        90.5
        """
        return self._total_ns / 60_000_000_000

    def in_seconds(self) -> float:
        """The total size in seconds

        Example
        -------
        >>> d = TimeDelta(minutes=2, seconds=1, microseconds=500_000)
        >>> d.in_seconds()
        121.5
        """
        return self._total_ns / 1_000_000_000

    def in_milliseconds(self) -> float:
        """The total size in milliseconds

        >>> d = TimeDelta(seconds=2, microseconds=50)
        >>> d.in_milliseconds()
        2_000.05
        """
        return self._total_ns / 1_000_000

    def in_microseconds(self) -> float:
        """The total size in microseconds

        >>> d = TimeDelta(seconds=2, nanoseconds=50)
        >>> d.in_microseconds()
        2_000_000.05
        """
        return self._total_ns / 1_000

    def in_nanoseconds(self) -> int:
        """The total size in nanoseconds

        >>> d = TimeDelta(seconds=2, nanoseconds=50)
        >>> d.in_nanoseconds()
        2_000_000_050
        """
        return self._total_ns

    def __eq__(self, other: object) -> bool:
        """Compare for equality

        Example
        -------
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

        Example
        -------
        >>> bool(TimeDelta())
        False
        >>> bool(TimeDelta(minutes=1))
        True
        """
        return bool(self._total_ns)

    def __add__(self, other: TimeDelta) -> TimeDelta:
        """Add two deltas together

        Example
        -------
        >>> d = TimeDelta(hours=1, minutes=30)
        >>> d + TimeDelta(minutes=30)
        TimeDelta(02:00:00)
        """
        if not isinstance(other, TimeDelta):
            return NotImplemented
        return TimeDelta(nanoseconds=self._total_ns + other._total_ns)

    def __sub__(self, other: TimeDelta) -> TimeDelta:
        """Subtract two deltas

        Example
        -------
        >>> d = TimeDelta(hours=1, minutes=30)
        >>> d - TimeDelta(minutes=30)
        TimeDelta(01:00:00)
        """
        if not isinstance(other, TimeDelta):
            return NotImplemented
        return TimeDelta(nanoseconds=self._total_ns - other._total_ns)

    def __mul__(self, other: float) -> TimeDelta:
        """Multiply by a number

        Example
        -------
        >>> d = TimeDelta(hours=1, minutes=30)
        >>> d * 2.5
        TimeDelta(03:45:00)
        """
        if not isinstance(other, (int, float)):
            return NotImplemented
        return TimeDelta(nanoseconds=int(self._total_ns * other))

    def __rmul__(self, other: float) -> TimeDelta:
        return self * other

    def __neg__(self) -> TimeDelta:
        """Negate the value

        Example
        -------
        >>> d = TimeDelta(hours=1, minutes=30)
        >>> -d
        TimeDelta(-01:30:00)
        """
        return TimeDelta(nanoseconds=-self._total_ns)

    def __pos__(self) -> TimeDelta:
        """Return the value unchanged

        Example
        -------
        >>> d = TimeDelta(hours=1, minutes=30)
        >>> +d
        TimeDelta(01:30:00)
        """
        return self

    @overload
    def __truediv__(self, other: float) -> TimeDelta: ...

    @overload
    def __truediv__(self, other: TimeDelta) -> float: ...

    def __truediv__(self, other: float | TimeDelta) -> TimeDelta | float:
        """Divide by a number or another delta

        Example
        -------
        >>> d = TimeDelta(hours=1, minutes=30)
        >>> d / 2.5
        TimeDelta(00:36:00)
        >>> d / TimeDelta(minutes=30)
        3.0
        """
        if isinstance(other, TimeDelta):
            return self._total_ns / other._total_ns
        elif isinstance(other, (int, float)):
            return TimeDelta(nanoseconds=int(self._total_ns / other))
        return NotImplemented

    def __abs__(self) -> TimeDelta:
        """The absolute value

        Example
        -------
        >>> d = TimeDelta(hours=-1, minutes=-30)
        >>> abs(d)
        TimeDelta(01:30:00)
        """
        return TimeDelta._from_nanos_unchecked(abs(self._total_ns))

    def default_format(self) -> str:
        """Format the delta in the default string format.

        The format is:

        .. code-block:: text

           HH:MM:SS(.ffffff)

        For example:

        .. code-block:: text

           01:24:45.0089
        """
        hrs, mins, secs, ns = abs(self).in_hrs_mins_secs_nanos()
        return (
            f"{'-'*(self._total_ns < 0)}PT{hrs:02}:{mins:02}:{secs:02}"
            + f".{ns:0>9}".rstrip("0") * bool(ns)
        )

    @classmethod
    def from_default_format(cls, s: str, /) -> TimeDelta:
        """Create from the default string representation.

        Inverse of :meth:`default_format`

        Example
        -------
        >>> TimeDelta.from_default_format("PT01:30:00")
        TimeDelta(01:30:00)

        Raises
        ------
        ValueError
            If the string does not match this exact format.
        """
        if not (match := _match_timedelta(s)):
            raise ValueError(f"Invalid time delta format: {s!r}")
        sign, hours, mins, secs = match.groups()
        # TODO check, remove this anyway
        return cls._from_nanos_unchecked(
            (-1 if sign == "-" else 1)
            * (
                int(hours) * 3_600_000_000_000
                + int(mins) * 60_000_000_000
                + round(float(secs) * 1_000_000_000)
            )
        )

    __str__ = default_format

    def common_iso8601(self) -> str:
        """Format as the *popular interpretation* of the ISO 8601 duration format.
        May not strictly adhere to (all versions of) the standard.
        See :ref:`here <iso8601-durations>` for more information.

        Inverse of :meth:`from_common_iso8601`

        Example
        -------
        >>> TimeDelta(hours=1, minutes=30).common_iso8601()
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

    @classmethod
    def from_common_iso8601(cls, s: str, /) -> TimeDelta:
        """Parse the *popular interpretation* of the ISO 8601 duration format.
        Does not parse all possible ISO 8601 durations.
        See :ref:`here <iso8601-durations>` for more information.

        Inverse of :meth:`common_iso8601`

        Example
        -------
        >>> TimeDelta.from_common_iso8601("PT1H30M")
        TimeDelta(01:30:00)

        Note
        ----
        Any duration with a non-zero date part is considered invalid.
        ``P0D`` is valid, but ``P1DT1H`` is not.
        """
        exc = ValueError(f"Invalid format: {s!r}")
        prev_unit = ""
        nanos = 0

        if len(s) < 4:
            raise exc

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
            rest, value, unit = _parse_timedelta_component(rest, exc)

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

        return TimeDelta._from_nanos_unchecked(sign * nanos)

    def py_timedelta(self) -> _timedelta:
        """Convert to a :class:`~datetime.timedelta`

        Inverse of :meth:`from_py_timedelta`

        Example
        -------
        >>> d = TimeDelta(hours=1, minutes=30)
        >>> d.py_timedelta()
        timedelta(seconds=5400)
        """
        return _timedelta(microseconds=round(self._total_ns / 1_000))

    @classmethod
    def from_py_timedelta(cls, td: _timedelta, /) -> TimeDelta:
        """Create from a :class:`~datetime.timedelta`

        Inverse of :meth:`py_timedelta`

        Example
        -------
        >>> TimeDelta.from_py_timedelta(timedelta(seconds=5400))
        TimeDelta(01:30:00)
        """
        return TimeDelta(
            microseconds=td.microseconds,
            seconds=td.seconds,
            hours=td.days * 24,
        )

    def in_hrs_mins_secs_nanos(self) -> tuple[int, int, int, int]:
        """Convert to a tuple of (hours, minutes, seconds, nanoseconds)

        Example
        -------
        >>> d = TimeDelta(hours=1, minutes=30, microseconds=5_000_090)
        >>> d.in_hrs_mins_secs_nanos()
        (1, 30, 5, 90_000)
        """
        hours, rem = divmod(abs(self._total_ns), 3_600_000_000_000)
        mins, rem = divmod(rem, 60_000_000_000)
        secs, ms = divmod(rem, 1_000_000_000)
        return (
            (hours, mins, secs, ms)
            if self._total_ns >= 0
            else (-hours, -mins, -secs, -ms)
        )

    def __repr__(self) -> str:
        return f"TimeDelta({self})"

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


def _parse_timedelta_component(s: str, exc: Exception) -> tuple[str, int, str]:
    if (
        match := re.match(r"^(\d{1,35}(?:\.\d{1,9})?)([HMS])", s, re.ASCII)
    ) is None:
        raise exc
    digits_maybe_fractional, unit = match.groups()
    if unit == "S":
        value = int(float(digits_maybe_fractional) * 1_000_000_000)
    else:
        try:
            value = int(digits_maybe_fractional)
        except ValueError:
            raise exc
    return s[len(digits_maybe_fractional) + 1 :], value, unit  # noqa[E203]


TimeDelta.ZERO = TimeDelta()
TimeDelta.MAX = TimeDelta(seconds=9999 * 366 * 24 * 3_600)
TimeDelta.MIN = TimeDelta(seconds=-9999 * 366 * 24 * 3_600)


@final
class DateDelta(_ImmutableBase):
    """A duration of time consisting of calendar units
    (years, months, weeks, and days)
    """

    __slots__ = ("_months", "_days")

    ZERO: ClassVar[DateDelta]
    """A delta of zero"""

    _time_part = TimeDelta.ZERO

    @property
    def _date_part(self) -> DateDelta:
        """The date part of the delta, always equal to itself"""
        return self

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

    def __eq__(self, other: object) -> bool:
        """Compare for equality, normalized to months and days.

        `a == b` is equivalent to `a.in_months_days() == b.in_months_days()`

        Example
        -------
        >>> p = DateDelta(weeks=4, days=2)
        DateDelta(P30D)
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

        Example
        -------
        >>> bool(DateDelta())
        False
        >>> bool(DateDelta(days=-1))
        True
        """
        return bool(self._months or self._days)

    def __repr__(self) -> str:
        return f"DateDelta({self})"

    def __neg__(self) -> DateDelta:
        """Negate the contents

        Example
        -------
        >>> p = DateDelta(weeks=2, days=3)
        >>> -p
        DateDelta(-P17D)
        """
        return DateDelta(months=-self._months, days=-self._days)

    def __pos__(self) -> DateDelta:
        """Return the value unchanged

        Example
        -------
        >>> p = DateDelta(weeks=2, days=-3)
        DateDelta(P11D)
        >>> +p
        DateDelta(P11D)
        """
        return self

    def __mul__(self, other: int) -> DateDelta:
        """Multiply the contents by a round number

        Example
        -------
        >>> p = DateDelta(years=1, weeks=2)
        >>> p * 2
        DateDelta(P2Y28D)
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

    @overload
    def __add__(self, other: DateDelta) -> DateDelta: ...

    @overload
    def __add__(self, other: TimeDelta) -> DateTimeDelta: ...

    def __add__(
        self, other: DateDelta | TimeDelta
    ) -> DateDelta | DateTimeDelta:
        """Add the fields of another delta to this one

        Example
        -------
        >>> p = DateDelta(weeks=2, months=1)
        >>> p + DateDelta(weeks=1, days=4)
        DateDelta(P1M25D)
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

        Example
        -------
        >>> p = DateDelta(weeks=2, days=3)
        >>> p - DateDelta(days=2)
        DateDelta(P15D)
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

    def __abs__(self) -> DateDelta:
        """If the contents are negative, return the positive version

        Example
        -------
        >>> p = DateDelta(months=-2, days=-3)
        >>> abs(p)
        DateDelta(P2M3D)
        """
        return DateDelta(months=abs(self._months), days=abs(self._days))

    def default_format(self) -> str:
        """The delta in default format.

        The default string format is:

        .. code-block:: text

            P(nY)(nM)(nD)

        For example:

        .. code-block:: text

            P1D
            P2M
            P1Y2M3W4D

        Example
        -------
        >>> p = DateDelta(years=1, months=2, weeks=3, days=11)
        >>> p.default_format()
        'P1Y2M3W11D'
        >>> DateDelta().default_format()
        'P0D'
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

    @classmethod
    def from_default_format(cls, s: str, /) -> DateDelta:
        """Create from the default string representation.

        Inverse of :meth:`default_format`

        Example
        -------
        >>> DateDelta.from_default_format("P1Y2M3W4D")
        DateDelta(P1Y2M25D)
        """
        return cls.from_common_iso8601(s)

    __str__ = default_format

    def common_iso8601(self) -> str:
        """Format as the *popular interpretation* of the ISO 8601 duration format.
        May not strictly adhere to (all versions of) the standard.
        See :ref:`here <iso8601-durations>` for more information.

        Inverse of :meth:`from_common_iso8601`

        Example
        -------
        >>> DateDelta(weeks=1, days=11).common_iso8601()
        'P18D'
        """
        return self.default_format()

    @classmethod
    def from_common_iso8601(cls, s: str, /) -> DateDelta:
        """Parse the *popular interpretation* of the ISO 8601 duration format.
        Does not parse all possible ISO 8601 durations.
        See :ref:`here <iso8601-durations>` for more information.

        Inverse of :meth:`common_iso8601`.

        Example
        -------
        >>> DateDelta.from_common_iso8601("P1W11D")
        DateDelta(P1W11D)
        >>> DateDelta.from_common_iso8601("-P3M")
        DateDelta(-P3M)

        Note
        ----
        Only durations without time component are accepted.
        ``P0D`` is valid, but ``P3DT1H`` is not.
        """
        exc = ValueError(f"Invalid format: {s!r}")
        prev_unit = ""
        months = 0
        days = 0

        if len(s) < 3 or not s.isascii():
            raise exc

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

        try:
            return DateDelta(months=sign * months, days=sign * days)
        except ValueError:
            raise exc

    def in_months_days(self) -> tuple[int, int]:
        """Convert to a tuple of months and days.

        Example
        -------
        >>> p = DateDelta(months=25, days=9)
        >>> p.in_months_days()
        (25, 9)
        >>> DateDelta(months=-13, weeks=-5)
        (-13, -35)
        """
        return self._months, self._days

    def in_years_months_days(self) -> tuple[int, int, int]:
        """Convert to a tuple of years, months, and days.

        Example
        -------
        >>> p = DateDelta(years=1, months=2, days=11)
        >>> p.in_years_months_days()
        (1, 2, 11)
        """
        years = int(self._months / 12)
        months = int(fmod(self._months, 12))
        return years, months, self._days

    @no_type_check
    def __reduce__(self):
        return (_unpkl_ddelta, (self._months, self._days))


# A separate unpickling function allows us to make backwards-compatible changes
# to the pickling format in the future
def _unpkl_ddelta(months: int, days: int) -> DateDelta:
    return DateDelta(months=months, days=days)


def _parse_datedelta_component(s: str, exc: Exception) -> tuple[str, int, str]:
    if (match := re.match(r"^(\d{1,8})([YMWD])", s, re.ASCII)) is None:
        raise exc
    digits, unit = match.groups()
    return s[len(digits) + 1 :], int(digits), unit  # noqa[E203]


DateDelta.ZERO = DateDelta()
TimeDelta._date_part = DateDelta.ZERO


@final
class DateTimeDelta(_ImmutableBase):
    """A duration with both a date and time component."""

    __slots__ = ("_date_part", "_time_part")

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

    ZERO: ClassVar[DateTimeDelta]
    """A delta of zero"""

    def date_part(self) -> DateDelta:
        return self._date_part

    def time_part(self) -> TimeDelta:
        return self._time_part

    def __eq__(self, other: object) -> bool:
        """Compare for equality

        Example
        -------
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

        Example
        -------
        >>> bool(DateTimeDelta())
        False
        >>> bool(DateTimeDelta(minutes=1))
        True
        """
        return bool(self._date_part or self._time_part)

    def __add__(self, other: Delta) -> DateTimeDelta:
        """Add two deltas together

        Example
        -------
        >>> d = DateTimeDelta(weeks=1, days=11, hours=4)
        >>> d + DateTimeDelta(months=2, days=3, minutes=90)
        DateTimeDelta(P1M1W14DT5H30M)
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

        Example
        -------
        >>> d = DateTimeDelta(weeks=1, days=11, hours=4)
        >>> d - DateTimeDelta(months=2, days=3, minutes=90)
        DateTimeDelta(P-2M1W8DT2H30M)
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

    def __mul__(self, other: int) -> DateTimeDelta:
        """Multiply by a number

        Example
        -------
        >>> d = DateTimeDelta(weeks=1, days=11, hours=4)
        >>> d * 2
        DateTimeDelta(P2W22DT8H)
        """
        # OPTIMIZE: use unchecked constructor
        return self._from_parts(
            self._date_part * other, self._time_part * other
        )

    def __rmul__(self, other: int) -> DateTimeDelta:
        return self * other

    def __neg__(self) -> DateTimeDelta:
        """Negate the delta

        Example
        -------
        >>> d = DateTimeDelta(days=11, hours=4)
        >>> -d
        DateTimeDelta(-P11DT4H)
        """
        # OPTIMIZE: use unchecked constructor
        return self._from_parts(-self._date_part, -self._time_part)

    def __pos__(self) -> DateTimeDelta:
        """Return the delta unchanged

        Example
        -------
        >>> d = DateTimeDelta(weeks=1, days=-11, hours=4)
        >>> +d
        DateTimeDelta(P1W11DT4H)
        """
        return self

    def __abs__(self) -> DateTimeDelta:
        """The absolute value of the delta

        Example
        -------
        >>> d = DateTimeDelta(weeks=1, days=-11, hours=4)
        >>> abs(d)
        DateTimeDelta(P1W11DT4H)
        """
        new = _object_new(DateTimeDelta)
        new._date_part = abs(self._date_part)
        new._time_part = abs(self._time_part)
        return new

    def default_format(self) -> str:
        """The delta in default format.

        Example
        -------
        >>> d = DateTimeDelta(
        ...     weeks=1,
        ...     days=11,
        ...     hours=4,
        ... )
        >>> d.default_format()
        'P1W11DT4H'
        """
        sign = (
            self._date_part._months < 0
            or self._date_part._days < 0
            or self._time_part._total_ns < 0
        ) * "-"
        date = abs(self._date_part).common_iso8601()[1:] * bool(
            self._date_part
        )
        time = abs(self._time_part).common_iso8601()[1:] * bool(
            self._time_part
        )
        return sign + "P" + ((date + time) or "0D")

    __str__ = default_format

    def __repr__(self) -> str:
        return f"DateTimeDelta({self})"

    @classmethod
    def from_default_format(cls, s: str, /) -> DateTimeDelta:
        """Create from the default string representation.
        Inverse of :meth:`default_format`

        Examples:

        .. code-block:: text

           P4D        # 4 days
           PT4H       # 4 hours
           PT3M40.5S  # 3 minutes and 40.5 seconds
           P1W11DT4H  # 1 week, 11 days, and 4 hours
           -PT7H4M    # -7 hours and -4 minutes (-7:04:00)
           +PT7H4M    # 7 hours and 4 minutes (7:04:00)


        Example
        -------
        >>> DateTimeDelta.from_default_format("P1W11DT4H")
        DateTimeDelta(P18DT4H)

        Raises
        ------
        ValueError
            If the string does not match this exact format.
        """
        if (
            not (match := _match_datetimedelta(s))
            or len(s) < 3
            or s.endswith("T")
        ):
            raise ValueError(f"Invalid format: {s!r}")
        sign, years, months, weeks, days, hours, minutes, seconds = (
            match.groups()
        )
        parsed = cls(
            years=int(years or 0),
            months=int(months or 0),
            weeks=int(weeks or 0),
            days=int(days or 0),
            hours=int(hours or 0),
            minutes=int(minutes or 0),
            seconds=float(seconds or 0),
        )
        return -parsed if sign == "-" else parsed

    def common_iso8601(self) -> str:
        """Format as the *popular interpretation* of the ISO 8601 duration format.
        May not strictly adhere to (all versions of) the standard.
        See :ref:`here <iso8601-durations>` for more information.

        Example
        -------
        >>> DateTimeDelta(weeks=1, days=-11, hours=4).common_iso8601()
        'P1W-11DT4H'
        """
        return self.default_format()

    @classmethod
    def from_common_iso8601(cls, s: str, /) -> DateTimeDelta:
        """Parse the *popular interpretation* of the ISO 8601 duration format.
        Does not parse all possible ISO 8601 durations.
        See :ref:`here <iso8601-durations>` for more information.

        Example
        -------
        >>> DateTimeDelta.from_common_iso8601("-P1W11DT4H")
        DateTimeDelta(P-1W-11DT-4H)

        """
        try:
            return cls.from_default_format(s)
        except ValueError:
            raise _make_common_iso8601_parse_error(s)

    def in_months_days_secs_nanos(self) -> tuple[int, int, int, int]:
        """Convert to a tuple of (months, days, seconds, nanoseconds)

        Example
        -------
        >>> d = DateTimeDelta(weeks=1, days=11, hours=4, microseconds=2)
        >>> d.in_months_days_secs_nanos()
        (0, 18, 14_400, 2000)
        """
        subsec_nanos = int(fmod(self._time_part._total_ns, 1_000_000_000))
        whole_seconds = int(self._time_part._total_ns / 1_000_000_000)
        return self._date_part.in_months_days() + (whole_seconds, subsec_nanos)

    @classmethod
    def _from_parts(cls, d: DateDelta, t: TimeDelta) -> DateTimeDelta:
        new = _object_new(cls)
        new._date_part = d
        new._time_part = t
        if ((d._months < 0 or d._days < 0) and t._total_ns > 0) or (
            (d._months > 0 or d._days > 0) and t._total_ns < 0
        ):
            raise ValueError("Mixed sign in date-time delta")
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
Delta = Union[DateTimeDelta, TimeDelta, DateDelta]
_TDateTime = TypeVar("_TDateTime", bound="_DateTime")


class _DateTime(_ImmutableBase, ABC):
    """Encapsulates behavior common to all datetimes. Not for public use."""

    __slots__ = ("_py_dt", "_nanos")
    _py_dt: _datetime
    _nanos: int

    @property
    def year(self) -> int:
        return self._py_dt.year

    @property
    def month(self) -> int:
        return self._py_dt.month

    @property
    def day(self) -> int:
        return self._py_dt.day

    @property
    def hour(self) -> int:
        return self._py_dt.hour

    @property
    def minute(self) -> int:
        return self._py_dt.minute

    @property
    def second(self) -> int:
        return self._py_dt.second

    @property
    def nanosecond(self) -> int:
        return self._nanos

    def date(self) -> Date:
        """The date part of the datetime

        Example
        -------
        >>> d = UTCDateTime(2021, 1, 2, 3, 4, 5)
        >>> d.date()
        Date(2021-01-02)

        To perform the inverse, use :meth:`Date.at` and a method
        like :meth:`~NaiveDateTime.assume_utc` or
        :meth:`~NaiveDateTime.assume_in_tz`:

        >>> date.at(time).assume_in_tz("Europe/London")
        """
        return Date.from_py_date(self._py_dt.date())

    def time(self) -> Time:
        """The time-of-day part of the datetime

        Example
        -------
        >>> d = UTCDateTime(2021, 1, 2, 3, 4, 5)
        UTCDateTime(2021-01-02T03:04:05Z)
        >>> d.time()
        Time(03:04:05)

        To perform the inverse, use :meth:`Time.on` and a method
        like :meth:`~NaiveDateTime.assume_utc` or
        :meth:`~NaiveDateTime.assume_in_tz`:

        >>> time.on(date).assume_utc()
        """
        return Time._from_py_unchecked(self._py_dt.time(), self._nanos)

    @abstractmethod
    def default_format(self) -> str:
        """Format as the default string representation. Each
        subclass has a different format. See the documentation for
        the subclass for more information.
        Inverse of :meth:`from_default_format`.
        """

    def __str__(self) -> str:
        """Same as :meth:`default_format` with ``sep=" "``"""
        return self.default_format()

    @classmethod
    @abstractmethod
    def from_default_format(cls: type[_TDateTime], s: str, /) -> _TDateTime:
        """Create an instance from the default string representation,
        which is different for each subclass.

        Inverse of :meth:`__str__` and :meth:`default_format`.

        Note
        ----
        ``T`` may be replaced with a single space

        Raises
        ------
        ValueError
            If the string does not match this exact format.
        """

    @classmethod
    @abstractmethod
    def from_py_datetime(cls: type[_TDateTime], d: _datetime, /) -> _TDateTime:
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
        Its ``fold`` attribute is consulted to determine
        the behavior on ambiguity.
        """

    def py_datetime(self) -> _datetime:
        """Convert to a standard library :class:`~datetime.datetime`"""
        return self._py_dt.replace(microsecond=self._nanos // 1_000)

    @abstractmethod
    def replace(self: _TDateTime, /, **kwargs: Any) -> _TDateTime:
        """Construct a new instance with the given fields replaced.

        Arguments are the same as the constructor,
        but only keyword arguments are allowed.

        Note
        ----
        If you need to shift the datetime by a duration,
        use the addition and subtraction operators instead.
        These account for daylight saving time and other complications.

        Warning
        -------
        The same exceptions as the constructor may be raised.
        For local and zoned datetimes,
        you will need to pass ``disambiguate=`` to resolve ambiguities.

        Example
        -------
        >>> d = UTCDateTime(2020, 8, 15, 23, 12)
        >>> d.replace(year=2021)
        UTCDateTime(2021-08-15T23:12:00)
        >>>
        >>> z = ZonedDateTime(2020, 8, 15, 23, 12, tz="Europe/London")
        >>> z.replace(year=2021, disambiguate="later")
        ZonedDateTime(2021-08-15T23:12:00+01:00)
        """

    @classmethod
    def _from_py_unchecked(
        cls: type[_TDateTime], d: _datetime, nanos: int, /
    ) -> _TDateTime:
        assert not d.microsecond
        assert 0 <= nanos < 1_000_000_000
        self = _object_new(cls)
        self._py_dt = d
        self._nanos = nanos
        return self


class _AwareDateTime(_DateTime):
    """Common behavior for all aware datetime types (:class:`UTCDateTime`,
    :class:`OffsetDateTime`, :class:`ZonedDateTime` and :class:`LocalSystemDateTime`).

    Not for public use.
    """

    __slots__ = ()

    def timestamp(self) -> int:
        """The UNIX timestamp for this datetime.

        Each subclass also defines an inverse ``from_timestamp`` method,
        which may require additional arguments.

        Example
        -------
        >>> UTCDateTime(1970, 1, 1).timestamp()
        0
        >>> ts = 1_123_000_000
        >>> UTCDateTime.from_timestamp(ts).timestamp() == ts
        True
        """
        return int(self._py_dt.timestamp())

    def timestamp_millis(self) -> int:
        """The UNIX timestamp for this datetime, in milliseconds.

        Each subclass also defines an inverse ``from_timestamp_millis`` method,
        which may require additional arguments.

        Example
        -------
        >>> UTCDateTime(1970, 1, 1).timestamp_millis()
        0
        >>> ts = 1_123_000_000_000
        >>> UTCDateTime.from_timestamp(ts).timestamp() == ts
        True
        """
        return int(self._py_dt.timestamp()) * 1_000 + self._nanos // 1_000_000

    def timestamp_nanos(self) -> int:
        """The UNIX timestamp for this datetime, in nanoseconds.

        Each subclass also defines an inverse ``from_timestamp_nanos`` method,
        which may require additional arguments.

        Example
        -------
        >>> UTCDateTime(1970, 1, 1).timestamp_nanos()
        0
        >>> ts = 1_123_000_000_000_000
        >>> UTCDateTime.from_timestamp(ts).timestamp() == ts
        True
        """
        return int(self._py_dt.timestamp()) * 1_000_000_000 + self._nanos

    @property
    @abstractmethod
    def offset(self) -> TimeDelta:
        """The UTC offset of the datetime"""

    @abstractmethod
    def in_utc(self) -> UTCDateTime:
        """Convert into an equivalent UTCDateTime.
        The result will always represent the same moment in time.
        """

    @overload
    @abstractmethod
    def in_fixed_offset(self, /) -> OffsetDateTime: ...

    @overload
    @abstractmethod
    def in_fixed_offset(
        self, offset: int | TimeDelta, /
    ) -> OffsetDateTime: ...

    @abstractmethod
    def in_fixed_offset(
        self, offset: int | TimeDelta | None = None, /
    ) -> OffsetDateTime:
        """Convert into an equivalent OffsetDateTime.
        Optionally, specify the offset to use.
        The result will always represent the same moment in time.
        """

    def in_tz(self, tz: str, /) -> ZonedDateTime:
        """Convert into an equivalent ZonedDateTime.
        The result will always represent the same moment in time.

        Raises
        ------
        ~zoneinfo.ZoneInfoNotFoundError
            If the timezone ID is not found in the IANA database.
        """
        return ZonedDateTime._from_py_unchecked(
            self._py_dt.astimezone(ZoneInfo(tz)), self._nanos
        )

    def in_local_system(self) -> LocalSystemDateTime:
        """Convert into a an equivalent LocalSystemDateTime.
        The result will always represent the same moment in time.
        """
        return LocalSystemDateTime._from_py_unchecked(
            self._py_dt.astimezone(), self._nanos
        )

    def naive(self) -> NaiveDateTime:
        """Convert into a naive datetime, dropping all timezone information

        As an inverse, :class:`NaiveDateTime` has methods
        :meth:`~NaiveDateTime.assume_utc`, :meth:`~NaiveDateTime.assume_fixed_offset`
        , :meth:`~NaiveDateTime.assume_in_tz`, and :meth:`~NaiveDateTime.assume_in_local_system`
        which may require additional arguments.
        """
        return NaiveDateTime._from_py_unchecked(
            self._py_dt.replace(tzinfo=None),
            self._nanos,
        )

    @abstractmethod
    def __eq__(self, other: object) -> bool:
        """Check if two datetimes represent at the same moment in time

        ``a == b`` is equivalent to ``a.in_utc() == b.in_utc()``

        Note
        ----
        If you want to exactly compare the values on their values
        instead of UTC equivalence, use :meth:`exact_eq` instead.

        Example
        -------
        >>> UTCDateTime(2020, 8, 15, hour=23) == UTCDateTime(2020, 8, 15, hour=23)
        True
        >>> OffsetDateTime(2020, 8, 15, hour=23, offset=1) == (
        ...     ZonedDateTime(2020, 8, 15, hour=18, tz="America/New_York")
        ... )
        True
        """

    @abstractmethod
    def __lt__(self, other: _AwareDateTime) -> bool:
        """Compare two datetimes by when they occur in time

        ``a < b`` is equivalent to ``a.in_utc() < b.in_utc()``

        Example
        -------
        >>> OffsetDateTime(2020, 8, 15, hour=23, offset=8) < (
        ...     ZoneDateTime(2020, 8, 15, hour=20, tz="Europe/Amsterdam")
        ... )
        True
        """

    @abstractmethod
    def __le__(self, other: _AwareDateTime) -> bool:
        """Compare two datetimes by when they occur in time

        ``a <= b`` is equivalent to ``a.in_utc() <= b.in_utc()``

        Example
        -------
        >>> OffsetDateTime(2020, 8, 15, hour=23, offset=8) <= (
        ...     ZoneDateTime(2020, 8, 15, hour=20, tz="Europe/Amsterdam")
        ... )
        True
        """

    @abstractmethod
    def __gt__(self, other: _AwareDateTime) -> bool:
        """Compare two datetimes by when they occur in time

        ``a > b`` is equivalent to ``a.in_utc() > b.in_utc()``

        Example
        -------
        >>> OffsetDateTime(2020, 8, 15, hour=19, offset=-8) > (
        ...     ZoneDateTime(2020, 8, 15, hour=20, tz="Europe/Amsterdam")
        ... )
        True
        """

    @abstractmethod
    def __ge__(self, other: _AwareDateTime) -> bool:
        """Compare two datetimes by when they occur in time

        ``a >= b`` is equivalent to ``a.in_utc() >= b.in_utc()``

        Example
        -------
        >>> OffsetDateTime(2020, 8, 15, hour=19, offset=-8) >= (
        ...     ZoneDateTime(2020, 8, 15, hour=20, tz="Europe/Amsterdam")
        ... )
        True
        """

    # Mypy doesn't like overloaded overrides, but we'd like to document
    # this 'abstract' behaviour anyway
    if not TYPE_CHECKING:  # pragma: no branch

        @abstractmethod
        def __sub__(self, other: _AwareDateTime) -> TimeDelta:
            """Calculate the duration between two datetimes

            ``a - b`` is equivalent to ``a.in_utc() - b.in_utc()``

            Example
            -------
            >>> d = UTCDateTime(2020, 8, 15, hour=23)
            >>> d - ZonedDateTime(2020, 8, 15, hour=20, tz="Europe/Amsterdam")
            TimeDelta(05:00:00)
            """

    @abstractmethod
    def exact_eq(self: _TDateTime, other: _TDateTime, /) -> bool:
        """Compare objects by their values (instead of their UTC equivalence).
        Different types are never equal.

        Note
        ----
        If ``a.exact_eq(b)`` is true, then
        ``a == b`` is also true, but the converse is not necessarily true.

        Examples
        --------

        >>> a = OffsetDateTime(2020, 8, 15, hour=12, offset=1)
        >>> b = OffsetDateTime(2020, 8, 15, hour=13, offset=2)
        >>> a == b
        True  # equivalent UTC times
        >>> a.exact_eq(b)
        False  # different values (hour and offset)
        """


@final
class UTCDateTime(_AwareDateTime):
    """A UTC-only datetime. Useful for representing moments in time
    in an unambiguous way.

    In >95% of cases, you should use this class over the others. The other
    classes are most often useful at the boundaries of your application.

    Example
    -------
    >>> from whenever import UTCDateTime
    >>> py311_release_livestream = UTCDateTime(2022, 10, 24, hour=17)
    UTCDateTime(2022-10-24 17:00:00Z)

    Note
    ----
    The default string format is:

    .. code-block:: text

        YYYY-MM-DDTHH:MM:SS(.ffffff)Z

    This format is both RFC 3339 and ISO 8601 compliant.

    Note
    ----
    The corresponding :class:`~datetime.datetime` object is always
    timezone-aware and has a fixed :attr:`~datetime.UTC` tzinfo.
    """

    __slots__ = ()

    def __init__(
        self,
        year: int,
        month: int,
        day: int,
        hour: int = 0,
        minute: int = 0,
        second: int = 0,
        nanosecond: int = 0,
    ) -> None:
        self._py_dt = _datetime(
            year, month, day, hour, minute, second, 0, _UTC
        )
        if nanosecond < 0 or nanosecond >= 1_000_000_000:
            raise ValueError(f"nanosecond out of range: {nanosecond}")
        self._nanos = nanosecond

    @classmethod
    def now(cls) -> UTCDateTime:
        """Create an instance from the current time"""
        secs, nanos = divmod(time_ns(), 1_000_000_000)
        return cls._from_py_unchecked(
            _datetime.fromtimestamp(secs, _UTC), nanos
        )

    def default_format(self) -> str:
        return (
            self._py_dt.isoformat()[:-6]
            + bool(self._nanos) * f".{self._nanos:09d}".rstrip("0")
            + "Z"
        )

    @classmethod
    def from_default_format(cls, s: str, /) -> UTCDateTime:
        if (match := _match_utc_str(s)) is None:
            raise ValueError(f"Invalid format: {s!r}")
        year, month, day, hour, minute, second = map(int, match.groups()[:6])
        nanos = int(match.group(7).ljust(9, "0")) if match.group(7) else 0
        return cls._from_py_unchecked(
            _datetime(year, month, day, hour, minute, second, 0, _UTC), nanos
        )

    @classmethod
    def from_timestamp(cls, i: int, /) -> UTCDateTime:
        """Create an instance from a UNIX timestamp.
        The inverse of :meth:`~_AwareDateTime.timestamp`.

        Example
        -------
        >>> UTCDateTime.from_timestamp(0) == UTCDateTime(1970, 1, 1)
        >>> d = UTCDateTime.from_timestamp(1_123_000_000)
        UTCDateTime(2004-08-02T16:26:40Z)
        >>> UTCDateTime.from_timestamp(d.timestamp()) == d
        True
        """
        return cls._from_py_unchecked(_fromtimestamp(i, _UTC), 0)

    @classmethod
    def from_timestamp_millis(cls, i: int, /) -> UTCDateTime:
        """Create an instace from a UNIX timestamp in milliseconds."""
        secs, millis = divmod(i, 1_000)
        return cls._from_py_unchecked(
            _fromtimestamp(secs, _UTC), millis * 1_000_000
        )

    @classmethod
    def from_timestamp_nanos(cls, i: int, /) -> UTCDateTime:
        """Create an instace from a UNIX timestamp in milliseconds."""
        secs, nanos = divmod(i, 1_000_000_000)
        return cls._from_py_unchecked(_fromtimestamp(secs, _UTC), nanos)

    @classmethod
    def from_py_datetime(cls, d: _datetime, /) -> UTCDateTime:
        if d.tzinfo is not _UTC:
            raise ValueError(
                "Can only create UTCDateTime from UTC datetime, "
                f"got datetime with tzinfo={d.tzinfo!r}"
            )
        return cls._from_py_unchecked(
            d.replace(microsecond=0), d.microsecond * 1_000
        )

    offset = TimeDelta.ZERO

    # TODO: rename to replace_date, replace_time
    def with_date(self, date: Date, /) -> UTCDateTime:
        """Create a new instance with the date replaced

        Example
        -------
        >>> d = UTCDateTime(2020, 8, 15, hour=23)
        >>> d.with_date(Date(2021, 1, 1))
        UTCDateTime(2021-01-01T23:00:00Z)
        """
        return self._from_py_unchecked(
            _datetime.combine(date._py_date, self._py_dt.timetz()),
            self._nanos,
        )

    def with_time(self, time: Time, /) -> UTCDateTime:
        """Create a new instance with the time replaced

        Example
        -------
        >>> d = UTCDateTime(2020, 8, 15, hour=23)
        >>> d.with_time(Time(12, 30))
        UTCDateTime(2020-08-15T12:30:00Z)
        """
        return self._from_py_unchecked(
            _datetime.combine(self._py_dt.date(), time._py_time, _UTC),
            time._nanos,
        )

    def replace(self, /, **kwargs: Any) -> UTCDateTime:
        _check_invalid_replace_kwargs(kwargs)
        nanos = _pop_nanos_kwarg(kwargs, self._nanos)
        return self._from_py_unchecked(self._py_dt.replace(**kwargs), nanos)

    def __hash__(self) -> int:
        return hash((self._py_dt, self._nanos))

    def __eq__(self, other: object) -> bool:
        if not isinstance(
            other, (UTCDateTime, OffsetDateTime, LocalSystemDateTime)
        ):
            return NotImplemented
        return (self._py_dt, self._nanos) == (other._py_dt, other._nanos)

    MIN: ClassVar[UTCDateTime]
    MAX: ClassVar[UTCDateTime]

    def exact_eq(self, other: UTCDateTime, /) -> bool:
        return (self._py_dt, self._nanos) == (other._py_dt, other._nanos)

    def __lt__(self, other: _AwareDateTime) -> bool:
        if not isinstance(other, _AwareDateTime):
            return NotImplemented
        return (self._py_dt, self._nanos) < (other._py_dt, other._nanos)

    def __le__(self, other: _AwareDateTime) -> bool:
        if not isinstance(other, _AwareDateTime):
            return NotImplemented
        return (self._py_dt, self._nanos) <= (other._py_dt, other._nanos)

    def __gt__(self, other: _AwareDateTime) -> bool:
        if not isinstance(other, _AwareDateTime):
            return NotImplemented
        return (self._py_dt, self._nanos) > (other._py_dt, other._nanos)

    def __ge__(self, other: _AwareDateTime) -> bool:
        if not isinstance(other, _AwareDateTime):
            return NotImplemented
        return (self._py_dt, self._nanos) >= (other._py_dt, other._nanos)

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
    ) -> UTCDateTime:
        """Add a time amount to this datetime.

        Units are added from largest to smallest,
        truncating and/or wrapping after each step.

        Example
        -------
        >>> d = UTCDateTime(2020, 8, 15, hour=23, minute=12)
        >>> d.add(hours=24, seconds=5)
        UTCDateTime(2020-08-16 23:12:05Z)
        >>> d.add(years=1, days=2, minutes=5)
        UTCDateTime(2021-08-17 23:17:00Z)
        """
        return self.with_date(
            self.date()
            ._add_months(years * 12 + months)
            ._add_days(weeks * 7 + days)
        ) + TimeDelta(
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
    ) -> UTCDateTime:
        """Subtract a time amount from this datetime.

        Units are subtracted from largest to smallest,
        wrapping and/or truncating after each step.

        Example
        -------
        >>> d = UTCDateTime(2020, 8, 15, hour=23, minute=12)
        >>> d.subtract(hours=24, seconds=5)
        UTCDateTime(2020-08-14 23:11:55Z)
        >>> d.subtract(years=1, days=2, minutes=5)
        UTCDateTime(2019-08-13 23:06:00Z)
        """
        return self.add(
            years=-years,
            months=-months,
            weeks=-weeks,
            days=-days,
            hours=-hours,
            minutes=-minutes,
            seconds=-seconds,
            milliseconds=-milliseconds,
            microseconds=-microseconds,
            nanoseconds=-nanoseconds,
        )

    def __add__(self, delta: Delta) -> UTCDateTime:
        """Add a time amount to this datetime.

        Behaves the same as :meth:`add`.

        Example
        -------
        >>> d = UTCDateTime(2020, 8, 15, hour=23, minute=12)
        >>> d + hours(24) + seconds(5)
        UTCDateTime(2020-08-16 23:12:05Z)
        >>> d + years(1) + days(2) + minutes(5)
        UTCDateTime(2021-08-17 23:17:00Z)
        """
        if isinstance(delta, (TimeDelta, DateDelta, DateTimeDelta)):
            delta_secs, nanos = divmod(
                self._nanos + delta._time_part._total_ns,
                1_000_000_000,
            )
            return self._from_py_unchecked(
                _datetime.combine(
                    (self.date() + delta._date_part)._py_date,
                    self._py_dt.time(),
                    _UTC,
                )
                + _timedelta(seconds=delta_secs),
                nanos,
            )
        return NotImplemented

    @overload
    def __sub__(self, other: _AwareDateTime) -> TimeDelta: ...

    @overload
    def __sub__(self, other: Delta) -> UTCDateTime: ...

    def __sub__(
        self, other: Delta | _AwareDateTime
    ) -> UTCDateTime | TimeDelta:
        """Subtract another datetime or delta

        Subtraction of deltas happens in the same way as :meth:`subtract`.

        Example
        -------
        >>> d = UTCDateTime(2020, 8, 15, hour=23, minute=12)
        >>> d - hours(24) - seconds(5)
        UTCDateTime(2020-08-14 23:11:55Z)
        >>> d - UTCDateTime(2020, 8, 14)
        TimeDelta(47:12:00)
        >>> d - months(2) - days(2) - minutes(5)
        UTCDateTime(2020-06-12 23:06:00Z)
        """
        if isinstance(other, _AwareDateTime):
            return TimeDelta.from_py_timedelta(self._py_dt - other._py_dt) + (
                TimeDelta._from_nanos_unchecked(self._nanos - other._nanos)
            )
        elif isinstance(other, (TimeDelta, DateDelta, DateTimeDelta)):
            return self + -other
        return NotImplemented

    def in_utc(self) -> UTCDateTime:
        return self

    @overload
    def in_fixed_offset(self, /) -> OffsetDateTime: ...

    @overload
    def in_fixed_offset(
        self, offset: int | TimeDelta, /
    ) -> OffsetDateTime: ...

    def in_fixed_offset(
        self, offset: int | TimeDelta | None = None, /
    ) -> OffsetDateTime:
        return OffsetDateTime._from_py_unchecked(
            (
                self._py_dt
                if offset is None
                else self._py_dt.astimezone(_load_offset(offset))
            ),
            self._nanos,
        )

    @classmethod
    def strptime(cls, s: str, /, fmt: str) -> UTCDateTime:
        """Simple alias for
        ``UTCDateTime.from_py_datetime(datetime.strptime(s, fmt))``

        Example
        -------
        >>> UTCDateTime.strptime("2020-08-15+0000", "%Y-%m-%d%z")
        UTCDateTime(2020-08-15 00:00:00Z)
        >>> UTCDateTime.strptime("2020-08-15", "%Y-%m-%d")
        UTCDateTime(2020-08-15 00:00:00Z)

        Note
        ----
        The parsed ``tzinfo`` must be either :attr:`datetime.UTC`
        or ``None`` (in which case it's set to :attr:`datetime.UTC`).
        """
        parsed = _datetime.strptime(s, fmt)
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=_UTC)
        elif parsed.tzinfo is not _UTC:
            raise ValueError(
                "Parsed datetime must have tzinfo=UTC or None, "
                f"got {parsed.tzinfo!r}"
            )
        return cls._from_py_unchecked(
            parsed.replace(microsecond=0), parsed.microsecond * 1_000
        )

    def rfc2822(self) -> str:
        """Format as an RFC 2822 string.

        The inverse of :meth:`from_rfc2822`.

        Example
        -------
        >>> UTCDateTime(2020, 8, 15, hour=23, minute=12).rfc2822()
        "Sat, 15 Aug 2020 23:12:00 GMT"
        """
        return format_datetime(self._py_dt, usegmt=True)

    @classmethod
    def from_rfc2822(cls, s: str, /) -> UTCDateTime:
        """Parse a UTC datetime in RFC 2822 format.

        The inverse of :meth:`rfc2822`.

        Example
        -------
        >>> UTCDateTime.from_rfc2822("Sat, 15 Aug 2020 23:12:00 GMT")
        UTCDateTime(2020-08-15 23:12:00Z)

        >>> # also valid:
        >>> UTCDateTime.from_rfc2822("Sat, 15 Aug 2020 23:12:00 +0000")
        >>> UTCDateTime.from_rfc2822("Sat, 15 Aug 2020 23:12:00 -0000")
        >>> UTCDateTime.from_rfc2822("Sat, 15 Aug 2020 23:12:00 UT")
        >>> UTCDateTime.from_rfc2822("Sat, 15 Aug 2020 23:12:00 UTC")

        >>> # Error: includes offset. Use OffsetDateTime.from_rfc2822() instead
        >>> UTCDateTime.from_rfc2822("Sat, 15 Aug 2020 23:12:00 +0200")

        Warning
        -------
        * Nonzero offsets will not be implicitly converted to UTC.
          Use :meth:`OffsetDateTime.from_rfc2822` if you'd like to
          parse an RFC 2822 string with a nonzero offset.
        """
        # FUTURE: disallow +0000
        parsed = _parse_rfc2822(s)
        # Nested ifs to keep happy path fast
        if parsed.tzinfo is not _UTC:
            if parsed.tzinfo is None:
                if "-0000" not in s:
                    raise ValueError(
                        "Could not parse RFC 2822 string as UTC; missing "
                        f"offset/zone: {s!r}"
                    )
                parsed = parsed.replace(tzinfo=_UTC)
            else:
                raise ValueError(
                    "Could not parse RFC 2822 string as UTC; nonzero"
                    f"offset: {s!r}"
                )
        return cls._from_py_unchecked(parsed, 0)

    def rfc3339(self) -> str:
        """Format as an RFC 3339 string

        For UTCDateTime, equivalent to :meth:`~_DateTime.default_format`.
        Inverse of :meth:`from_rfc3339`.

        Example
        -------
        >>> UTCDateTime(2020, 8, 15, hour=23, minute=12).rfc3339()
        "2020-08-15T23:12:00Z"
        """
        return (
            self._py_dt.isoformat(sep=" ")[:-6]
            + bool(self._nanos) * f".{self._nanos:09d}".rstrip("0")
            + "Z"
        )

    @classmethod
    def from_rfc3339(cls, s: str, /) -> UTCDateTime:
        """Parse a UTC datetime in RFC 3339 format.

        Inverse of :meth:`rfc3339`.

        Example
        -------
        >>> UTCDateTime.from_rfc3339("2020-08-15T23:12:00Z")
        UTCDateTime(2020-08-15 23:12:00Z)
        >>>
        >>> # also valid:
        >>> UTCDateTime.from_rfc3339("2020-08-15T23:12:00+00:00")
        >>> UTCDateTime.from_rfc3339("2020-08-15_23:12:00.34Z")
        >>> UTCDateTime.from_rfc3339("2020-08-15t23:12:00z")
        >>>
        >>> # not valid (nonzero offset):
        >>> UTCDateTime.from_rfc3339("2020-08-15T23:12:00+02:00")

        Warning
        -------
        Nonzero offsets will not be implicitly converted to UTC.
        Use :meth:`OffsetDateTime.from_rfc3339` if you'd like to
        parse an RFC 3339 string with a nonzero offset.
        """
        if (match := _match_utc_rfc3339(s)) is None:
            raise ValueError(f"Invalid RFC 3339 format: {s!r}")
        year, month, day, hour, minute, second = map(int, match.groups()[:6])
        nanos = int(match.group(7).ljust(9, "0")) if match.group(7) else 0
        return cls(year, month, day, hour, minute, second, nanosecond=nanos)

    def common_iso8601(self) -> str:
        """Format as a common ISO 8601 string.

        For this class, equivalent to :meth:`rfc3339`.

        Example
        -------
        >>> UTCDateTime(2020, 8, 15, hour=23, minute=12).common_iso8601()
        "2020-08-15T23:12:00Z"
        """
        return (
            self._py_dt.isoformat()[:-6]
            + bool(self._nanos) * f".{self._nanos:09d}".rstrip("0")
            + "Z"
        )

    @classmethod
    def from_common_iso8601(cls, s: str, /) -> UTCDateTime:
        """Parse a UTC datetime in common ISO 8601 format.

        Inverse of :meth:`common_iso8601`.

        Example
        -------
        >>> UTCDateTime.from_common_iso8601("2020-08-15T23:12:00Z")
        UTCDateTime(2020-08-15 23:12:00Z)
        >>>
        >>> # also valid:
        >>> UTCDateTime.from_common_iso8601("2020-08-15T23:12:00+00:00")
        >>> UTCDateTime.from_common_iso8601("2020-08-15T23:12:00.34Z")
        >>>
        >>> # not valid
        >>> UTCDateTime.from_common_iso8601("2020-08-15T23:12:00+02:00")
        >>> UTCDateTime.from_common_iso8601("2020-08-15 23:12:00+00:00")
        >>> UTCDateTime.from_common_iso8601("2020-08-15T23:12:00-00:00")

        Warning
        -------
        Nonzero offsets will not be implicitly converted to UTC.
        Use :meth:`OffsetDateTime.from_common_iso8601` if you'd like to
        parse an ISO 8601 string with a nonzero offset.
        """
        if (
            (match := _match_utc_rfc3339(s)) is None
            or s[10] != "T"
            or s.endswith(("z", "-00:00"))
        ):
            raise ValueError(f"Invalid common ISO 8601 format: {s!r}")
        year, month, day, hour, minute, second = map(int, match.groups()[:6])
        nanos = int(match.group(7).ljust(9, "0")) if match.group(7) else 0
        return cls(year, month, day, hour, minute, second, nanosecond=nanos)

    def __repr__(self) -> str:
        return f"UTCDateTime({str(self).replace('T', ' ')})"

    # a custom pickle implementation with a smaller payload
    def __reduce__(self) -> tuple[object, ...]:
        return (
            _unpkl_utc,
            (
                pack(
                    "<qL",
                    int(self._py_dt.timestamp()) + _UNIX_INSTANT,
                    self._nanos,
                ),
            ),
        )


_UNIX_INSTANT = -int(_datetime(1, 1, 1, tzinfo=_UTC).timestamp()) + 86_400


# A separate unpickling function allows us to make backwards-compatible changes
# to the pickling format in the future
def _unpkl_utc(data: bytes) -> UTCDateTime:
    secs, nanos = unpack("<qL", data)
    return UTCDateTime._from_py_unchecked(
        _fromtimestamp(secs - _UNIX_INSTANT, _UTC), nanos
    )


@final
class OffsetDateTime(_AwareDateTime):
    """A datetime with a fixed UTC offset.
    Useful for representing the local time at a specific location.

    Example
    -------
    >>> # 9 AM in Salt Lake City, with the UTC offset at the time
    >>> pycon23_start = OffsetDateTime(2023, 4, 21, hour=9, offset=-6)
    OffsetDateTime(2023-04-21 09:00:00-06:00)

    Note
    ----
    The default string format is:

    .. code-block:: text

        YYYY-MM-DDTHH:MM:SS(.ffffff)±HH:MM(:SS(.ffffff))

    For example:

    .. code-block:: text

        2020-08-15T12:08:30+01:00

    This format is both RFC 3339 and ISO 8601 compliant.

    Note
    ----
    The corresponding :class:`~datetime.datetime` object is always
    timezone-aware and has a fixed :class:`datetime.timezone` tzinfo.
    """

    __slots__ = ()

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
        self._py_dt = _check_utc_bounds(
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

    # TODO: remove?
    @classmethod
    def now(cls, offset: int | TimeDelta) -> OffsetDateTime:
        """Create an instance at the current time with the given offset"""
        secs, nanos = divmod(time_ns(), 1_000_000_000)
        return cls._from_py_unchecked(
            _fromtimestamp(secs, _load_offset(offset)), nanos
        )

    def default_format(self) -> str:
        iso_without_fracs = self._py_dt.isoformat()
        return (
            iso_without_fracs[:19]
            + bool(self._nanos) * f".{self._nanos:09d}".rstrip("0")
            + iso_without_fracs[19:]
        )

    @classmethod
    def from_default_format(cls, s: str, /) -> OffsetDateTime:
        if (match := _match_offset_str(s)) is None:
            raise ValueError(f"Invalid format: {s!r}")
        nanos = int(match.group(7).ljust(9, "0")) if match.group(7) else 0
        sign = -1 if match.group(8) == "-" else 1

        offset_hrs_str, offset_mins_str, offset_secs_str = match.groups()[8:]
        offset = 0
        if offset_hrs_str:
            offset += int(offset_hrs_str) * 3600 + int(offset_mins_str) * 60
        if offset_secs_str:
            offset += int(offset_secs_str)

        if not -86400 < offset < 86400:
            raise ValueError(f"Invalid format: {s!r}")

        return cls._from_py_unchecked(
            _check_utc_bounds(
                _fromisoformat(s[:19]).replace(
                    tzinfo=_timezone(_timedelta(seconds=offset * sign)),
                )
            ),
            nanos,
        )

    @classmethod
    def from_timestamp(
        cls, i: int, /, *, offset: int | TimeDelta
    ) -> OffsetDateTime:
        """Create a OffsetDateTime from a UNIX timestamp.
        The inverse of :meth:`~_AwareDateTime.timestamp`.

        Example
        -------
        >>> OffsetDateTime.from_timestamp(0, offset=hours(3))
        OffsetDateTime(1970-01-01 03:00:00+03:00)
        >>> d = OffsetDateTime.from_timestamp(1_123_000_000.45, offset=-2)
        OffsetDateTime(2004-08-02 14:26:40.45-02:00)
        >>> OffsetDateTime.from_timestamp(d.timestamp(), d.offset) == d
        True
        """
        return cls._from_py_unchecked(
            _fromtimestamp(i, _load_offset(offset)), 0
        )

    @classmethod
    def from_timestamp_millis(
        cls, i: int, /, *, offset: int | TimeDelta
    ) -> OffsetDateTime:
        """Create an instace from a UNIX timestamp in milliseconds."""
        secs, millis = divmod(i, 1_000)
        return cls._from_py_unchecked(
            _fromtimestamp(secs, _load_offset(offset)), millis * 1_000_000
        )

    @classmethod
    def from_timestamp_nanos(
        cls, i: int, /, *, offset: int | TimeDelta
    ) -> OffsetDateTime:
        """Create an instace from a UNIX timestamp in milliseconds."""
        secs, nanos = divmod(i, 1_000_000_000)
        return cls._from_py_unchecked(
            _fromtimestamp(secs, _load_offset(offset)), nanos
        )

    @classmethod
    def from_py_datetime(cls, d: _datetime, /) -> OffsetDateTime:
        if not isinstance(d.tzinfo, _timezone):
            raise ValueError(
                "Datetime's tzinfo is not a datetime.timezone, "
                f"got tzinfo={d.tzinfo!r}"
            )
        return cls._from_py_unchecked(
            _check_utc_bounds(d.replace(microsecond=0)), d.microsecond * 1_000
        )

    def replace(self, /, **kwargs: Any) -> OffsetDateTime:
        _check_invalid_replace_kwargs(kwargs)
        try:
            kwargs["tzinfo"] = _load_offset(kwargs.pop("offset"))
        except KeyError:
            pass
        nanos = _pop_nanos_kwarg(kwargs, self._nanos)
        return self._from_py_unchecked(
            _check_utc_bounds(self._py_dt.replace(**kwargs)), nanos
        )

    # TODO: replace_date, replace_time
    def with_date(self, date: Date, /) -> OffsetDateTime:
        """Create a new instance with the date replaced

        Example
        -------
        >>> d = OffsetDateTime(2020, 8, 15, offset=-4)
        >>> d.with_date(Date(2021, 1, 1))
        OffsetDateTime(2021-01-01T00:00:00-04:00)
        """
        return self._from_py_unchecked(
            _check_utc_bounds(
                _datetime.combine(date._py_date, self._py_dt.timetz())
            ),
            self._nanos,
        )

    def with_time(self, time: Time, /) -> OffsetDateTime:
        """Create a new instance with the time replaced

        Example
        -------
        >>> d = OffsetDateTime(2020, 8, 15, offset=-12)
        >>> d.with_time(Time(12, 30))
        OffsetDateTime(2020-08-15T12:30:00-12:00)
        """
        return self._from_py_unchecked(
            _check_utc_bounds(
                _datetime.combine(
                    self._py_dt.date(), time._py_time, self._py_dt.tzinfo
                )
            ),
            time._nanos,
        )

    def __hash__(self) -> int:
        return hash((self._py_dt, self._nanos))

    def __eq__(self, other: object) -> bool:
        if not isinstance(
            other, (UTCDateTime, OffsetDateTime, LocalSystemDateTime)
        ):
            return NotImplemented
        return (self._py_dt, self._nanos) == (other._py_dt, other._nanos)

    # TODO: remove from UTC class
    @property
    def offset(self) -> TimeDelta:
        return TimeDelta._from_nanos_unchecked(
            int(
                self._py_dt.utcoffset().total_seconds()  # type: ignore[union-attr]
                * 1_000_000_000
            )
        )

    def exact_eq(self, other: OffsetDateTime, /) -> bool:
        return (self._py_dt, self._py_dt.utcoffset(), self._nanos) == (
            other._py_dt,
            other._py_dt.utcoffset(),
            other._nanos,
        )

    def __lt__(self, other: _AwareDateTime) -> bool:
        if not isinstance(other, _AwareDateTime):
            return NotImplemented
        return (self._py_dt, self._nanos) < (other._py_dt, other._nanos)

    def __le__(self, other: _AwareDateTime) -> bool:
        if not isinstance(other, _AwareDateTime):
            return NotImplemented
        return (self._py_dt, self._nanos) <= (other._py_dt, other._nanos)

    def __gt__(self, other: _AwareDateTime) -> bool:
        if not isinstance(other, _AwareDateTime):
            return NotImplemented
        return (self._py_dt, self._nanos) > (other._py_dt, other._nanos)

    def __ge__(self, other: _AwareDateTime) -> bool:
        if not isinstance(other, _AwareDateTime):
            return NotImplemented
        return (self._py_dt, self._nanos) >= (other._py_dt, other._nanos)

    def __sub__(self, other: _AwareDateTime) -> TimeDelta:
        """Subtract another datetime to get the duration between them

        Example
        -------
        >>> d = UTCDateTime(2020, 8, 15, 23, 12)
        >>> d - hours(28) - seconds(5)
        UTCDateTime(2020-08-14 19:11:55Z)

        >>> d - OffsetDateTime(2020, 8, 15, offset=hours(-5))
        TimeDelta(18:12:00)
        """
        if isinstance(other, _AwareDateTime):
            # TODO incorrect
            return TimeDelta.from_py_timedelta(self._py_dt - other._py_dt)
        return NotImplemented

    def in_utc(self) -> UTCDateTime:
        return UTCDateTime._from_py_unchecked(
            self._py_dt.astimezone(_UTC), self._nanos
        )

    @overload
    def in_fixed_offset(self, /) -> OffsetDateTime: ...

    @overload
    def in_fixed_offset(
        self, offset: int | TimeDelta, /
    ) -> OffsetDateTime: ...

    def in_fixed_offset(
        self, offset: int | TimeDelta | None = None, /
    ) -> OffsetDateTime:
        return (
            self
            if offset is None
            else self._from_py_unchecked(
                self._py_dt.astimezone(_load_offset(offset)),
                self._nanos,
            )
        )

    @classmethod
    def strptime(cls, s: str, /, fmt: str) -> OffsetDateTime:
        """Simple alias for
        ``OffsetDateTime.from_py_datetime(datetime.strptime(s, fmt))``

        Example
        -------
        >>> OffsetDateTime.strptime("2020-08-15+0200", "%Y-%m-%d%z")
        OffsetDateTime(2020-08-15 00:00:00+02:00)

        Note
        ----
        The parsed ``tzinfo`` must be a fixed offset
        (:class:`~datetime.timezone` instance).
        This means you need to include the directive ``%z``, ``%Z``, or ``%:z``
        in the format string.
        """
        parsed = _datetime.strptime(s, fmt)
        # We only need to check for None, because the only other tzinfo
        # returned from strptime is a fixed offset
        if parsed.tzinfo is None:
            raise ValueError(
                "Parsed datetime must have an offset. "
                "Use %z, %Z, or %:z in the format string"
            )
        return cls._from_py_unchecked(_check_utc_bounds(parsed), 0)

    def rfc2822(self) -> str:
        """Format as an RFC 2822 string.

        Inverse of :meth:`from_rfc2822`.

        Example
        -------
        >>> OffsetDateTime(2020, 8, 15, 23, 12, offset=hours(2)).rfc2822()
        "Sat, 15 Aug 2020 23:12:00 +0200"
        """
        return format_datetime(self._py_dt)

    @classmethod
    def from_rfc2822(cls, s: str, /) -> OffsetDateTime:
        """Parse an offset datetime in RFC 2822 format.

        Inverse of :meth:`rfc2822`.

        Example
        -------
        >>> OffsetDateTime.from_rfc2822("Sat, 15 Aug 2020 23:12:00 +0200")
        OffsetDateTime(2020-08-15 23:12:00+02:00)
        >>> # also valid:
        >>> OffsetDateTime.from_rfc2822("Sat, 15 Aug 2020 23:12:00 UT")
        >>> OffsetDateTime.from_rfc2822("Sat, 15 Aug 2020 23:12:00 GMT")
        >>> OffsetDateTime.from_rfc2822("Sat, 15 Aug 2020 23:12:00 MST")

        Warning
        -------
        The offset ``-0000`` has special meaning in RFC 2822,
        indicating a UTC time with unknown local offset.
        Thus, it cannot be parsed to an :class:`OffsetDateTime`.
        """
        parsed = _parse_rfc2822(s)
        if parsed.tzinfo is None:
            raise ValueError(
                "RFC 2822 string with missing or -0000 offset "
                f"cannot be parsed as OffsetDateTime: {s!r}"
            )
        return cls._from_py_unchecked(parsed, 0)

    def rfc3339(self) -> str:
        """Format as an RFC 3339 string

        For ``OffsetDateTime``, equivalent to
        :meth:`~_DateTime.default_format`
        and :meth:`~OffsetDateTime.common_iso8601`.
        Inverse of :meth:`from_rfc3339`.

        Example
        -------
        >>> OffsetDateTime(2020, 8, 15, hour=23, minute=12, offset=hours(4)).rfc3339()
        "2020-08-15T23:12:00+04:00"
        """
        py_isofmt = self._py_dt.isoformat(" ")
        return (
            py_isofmt[:19]  # without the offset
            + bool(self._nanos) * f".{self._nanos:09d}".rstrip("0")
            + py_isofmt[19:25]  # limit offset to minutes
        )

    @classmethod
    def from_rfc3339(cls, s: str, /) -> OffsetDateTime:
        """Parse a UTC datetime in RFC 3339 format.

        Inverse of :meth:`rfc3339`.

        Example
        -------
        >>> OffsetDateTime.from_rfc3339("2020-08-15T23:12:00+02:00")
        OffsetDateTime(2020-08-15 23:12:00+02:00)
        >>> # also valid:
        >>> OffsetDateTime.from_rfc3339("2020-08-15T23:12:00Z")
        >>> OffsetDateTime.from_rfc3339("2020-08-15_23:12:00.23-12:00")
        >>> OffsetDateTime.from_rfc3339("2020-08-15t23:12:00z")
        """
        if (match := _match_rfc3339(s)) is None:
            raise ValueError(f"Invalid RFC 3339 format: {s!r}")
        nanos = int(match.group(7).ljust(9, "0")) if match.group(7) else 0
        offset_hrs_str, offset_mins_str = match.groups()[8:]

        sign = -1 if match.group(8) == "-" else 1
        offset = 0
        if offset_hrs_str:
            offset += int(offset_hrs_str) * 3600 + int(offset_mins_str) * 60

        if not -86400 < offset < 86400:
            raise ValueError(f"Invalid RFC 3339 format: {s!r}")

        try:
            py_dt = _check_utc_bounds(
                _fromisoformat(s[:19]).replace(
                    tzinfo=_timezone(_timedelta(seconds=offset * sign)),
                )
            )
        except ValueError:
            raise ValueError(f"Invalid RFC 3339 format: {s!r}")

        return cls._from_py_unchecked(py_dt, nanos)

    def common_iso8601(self) -> str:
        """Format in the commonly used ISO 8601 format.

        Inverse of :meth:`from_common_iso8601`.

        Note
        ----
        For ``OffsetDateTime``, equivalent to :meth:`~_DateTime.default_format`
        and :meth:`~OffsetDateTime.rfc3339`.

        Example
        -------
        >>> OffsetDateTime(2020, 8, 15, hour=23, offset=+3).common_iso8601()
        "2020-08-15T23:00:00+03:00"
        """
        py_isofmt = self._py_dt.isoformat()  # still missing nanos
        return (
            py_isofmt[:19]  # without the offset
            + bool(self._nanos) * f".{self._nanos:09d}".rstrip("0")
            + py_isofmt[19:]
        )

    @classmethod
    def from_common_iso8601(cls, s: str, /) -> OffsetDateTime:
        """Parse a *popular version* of the ISO 8601 datetime format.

        Inverse of :meth:`common_iso8601`.

        Note
        ----
        While similar, this function behaves differently from
        :meth:`~_DateTime.from_default_format`
        or :meth:`~OffsetDateTime.from_rfc3339`.

        Example
        -------
        >>> OffsetDateTime.from_common_iso8601("2020-08-15T23:12:00+02:00")
        OffsetDateTime(2020-08-15 23:12:00+02:00)
        >>> # also valid:
        >>> OffsetDateTime.from_common_iso8601("2020-08-15T23:12:00Z")
        """
        return cls.from_default_format(s)

    def __repr__(self) -> str:
        return f"OffsetDateTime({str(self).replace('T', ' ')})"

    # a custom pickle implementation with a smaller payload
    def __reduce__(self) -> tuple[object, ...]:
        return (
            _unpkl_offset,
            (
                pack(
                    "<HBBBBBIl",
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
    year, month, day, hour, minute, second, nanos, offset_secs = unpack(
        "<HBBBBBIl", data
    )
    return OffsetDateTime._from_py_unchecked(
        _datetime(
            year,
            month,
            day,
            hour,
            minute,
            second,
            0,
            _timezone(_timedelta(seconds=offset_secs)),
        ),
        nanos,
    )


@final
class ZonedDateTime(_AwareDateTime):
    """A datetime associated with a IANA timezone ID.
    Useful for representing the local time bound to a specific location.

    Example
    -------
    >>> from whenever import ZonedDateTime
    >>>
    >>> # always at 11:00 in London, regardless of the offset
    >>> changing_the_guard = ZonedDateTime(2024, 12, 8, hour=11, tz="Europe/London")
    >>>
    >>> # Explicitly resolve ambiguities when clocks are set backwards.
    >>> night_shift = ZonedDateTime(2023, 10, 29, 1, 15, tz="Europe/London", disambiguate="later")
    >>>
    >>> # ZoneInfoNotFoundError: no such timezone
    >>> ZonedDateTime(2024, 12, 8, hour=11, tz="invalid")
    >>>
    >>> # SkippedTime: 2:15 AM does not exist on this day
    >>> ZonedDateTime(2023, 3, 26, 2, 15, tz="Europe/Amsterdam")

    Disambiguation
    --------------

    The ``disambiguate`` argument controls how ambiguous datetimes are handled:

    +------------------+-------------------------------------------------+
    | ``disambiguate`` | Behavior in case of ambiguity                   |
    +==================+=================================================+
    | ``"raise"``      | (default) Refuse to guess:                      |
    |                  | raise :exc:`~whenever.AmbiguousTime`            |
    |                  | or :exc:`~whenever.SkippedTime` exception.      |
    +------------------+-------------------------------------------------+
    | ``"earlier"``    | Choose the earlier of the two options           |
    +------------------+-------------------------------------------------+
    | ``"later"``      | Choose the later of the two options             |
    +------------------+-------------------------------------------------+
    | ``"compatible"`` | Choose "earlier" for backward transitions and   |
    |                  | "later" for forward transitions. This matches   |
    |                  | the behavior of other established libraries,    |
    |                  | and the industry standard RFC 5545.             |
    |                  | It corresponds to setting ``fold=0`` in the     |
    |                  | standard library.                               |
    +------------------+-------------------------------------------------+

    Warning
    -------
    The default string format is:

    .. code-block:: text

       YYYY-MM-DDTHH:MM:SS(.ffffff)±HH:MM(:SS(.ffffff))[TIMEZONE ID]

    For example:

    .. code-block:: text

       2020-08-15T23:12:00+01:00[Europe/London]

    The offset is included to disambiguate cases where the same
    local time occurs twice due to DST transitions.
    If the offset is invalid for the system timezone,
    parsing will raise :class:`InvalidOffset`.

    This format is similar to those `used by other languages <https://tc39.es/proposal-temporal/docs/strings.html#iana-time-zone-names>`_,
    but it is *not* RFC 3339 or ISO 8601 compliant
    (these standards don't support timezone IDs.)
    Use :meth:`~_AwareDateTime.in_fixed_offset` first if you
    need RFC 3339 or ISO 8601 compliance.
    """

    __slots__ = ()

    def __init__(
        self,
        year: int,
        month: int,
        day: int,
        hour: int = 0,
        minute: int = 0,
        second: int = 0,
        nanosecond: int = 0,  # TODO: kwarg only
        *,
        tz: str,
        disambiguate: Disambiguate = "raise",
    ) -> None:
        self._py_dt = _resolve_ambuguity(
            _datetime(
                year,
                month,
                day,
                hour,
                minute,
                second,
                0,
                zone := ZoneInfo(tz),
                fold=_as_fold(disambiguate),
            ),
            zone,
            disambiguate,
        )
        if nanosecond < 0 or nanosecond >= 1_000_000_000:
            raise ValueError(f"nanosecond out of range: {nanosecond}")
        self._nanos = nanosecond

    @classmethod
    def now(cls, tz: str) -> ZonedDateTime:
        """Create an instance from the current time in the given timezone"""
        secs, nanos = divmod(time_ns(), 1_000_000_000)
        return cls._from_py_unchecked(
            _fromtimestamp(secs, ZoneInfo(tz)), nanos
        )

    def default_format(self) -> str:
        py_isofmt = self._py_dt.isoformat()
        return (
            py_isofmt[:19]  # without the offset
            + bool(self._nanos) * f".{self._nanos:09d}".rstrip("0")
            + py_isofmt[19:]
            + f"[{self._py_dt.tzinfo.key}]"  # type: ignore[union-attr]
        )

    @classmethod
    def from_default_format(cls, s: str, /) -> ZonedDateTime:
        if (match := _match_zoned_str(s)) is None:
            raise ValueError(f"Invalid format: {s!r}")

        nanos = int(match.group(7).ljust(9, "0")) if match[7] else 0
        sign = -1 if match[8] == "-" else 1

        offset_hrs_str, offset_mins_str, offset_secs_str = match.groups()[8:11]
        offset_secs = 0
        if offset_hrs_str:
            offset_secs += (
                int(offset_hrs_str) * 3600 + int(offset_mins_str) * 60
            )
        if offset_secs_str:
            offset_secs += int(offset_secs_str)

        if not -86400 < offset_secs < 86400:
            raise ValueError(f"Invalid format: {s!r}")

        offset = _timedelta(seconds=offset_secs * sign)
        try:
            naive_dt = _fromisoformat(s[:19])
        except ValueError:
            raise ValueError(f"Invalid format: {s!r}")
        dt = _check_utc_bounds(naive_dt.replace(tzinfo=ZoneInfo(match[12])))
        return cls._from_py_unchecked(
            _adjust_fold_to_offset(dt, offset), nanos
        )

    @classmethod
    def from_timestamp(cls, i: int, /, *, tz: str) -> ZonedDateTime:
        """Create an instace from a UNIX timestamp."""
        return cls._from_py_unchecked(_fromtimestamp(i, ZoneInfo(tz)), 0)

    @classmethod
    def from_timestamp_millis(cls, i: int, /, *, tz: str) -> ZonedDateTime:
        """Create an instace from a UNIX timestamp in milliseconds."""
        secs, millis = divmod(i, 1_000)
        return cls._from_py_unchecked(
            _fromtimestamp(secs, ZoneInfo(tz)), millis * 1_000_000
        )

    @classmethod
    def from_timestamp_nanos(cls, i: int, /, *, tz: str) -> ZonedDateTime:
        """Create an instace from a UNIX timestamp in milliseconds."""
        secs, nanos = divmod(i, 1_000_000_000)
        return cls._from_py_unchecked(
            _fromtimestamp(secs, ZoneInfo(tz)), nanos
        )

    @classmethod
    def from_py_datetime(cls, d: _datetime, /) -> ZonedDateTime:
        if type(d.tzinfo) is not ZoneInfo:
            raise ValueError(
                "Can only create ZonedDateTime from tzinfo=ZoneInfo (exactly), "
                f"got datetime with tzinfo={d.tzinfo!r}"
            )

        # round-trip to UTC ensures skipped times are disambiguated
        d = d.astimezone(_UTC).astimezone(d.tzinfo)
        return cls._from_py_unchecked(
            d.replace(microsecond=0), d.microsecond * 1_000
        )

    def with_date(
        self, date: Date, /, disambiguate: Disambiguate = "raise"
    ) -> ZonedDateTime:
        """Create a new ZonedDateTime with the same time, but a different date.

        Example
        -------
        >>> d = ZonedDateTime(2020, 3, 28, 12, tz="Europe/Amsterdam")
        >>> d.with_date(Date(2023, 10, 29))
        ZonedDateTime(2023-10-29T12:00:00+02:00[Europe/Amsterdam])
        """
        return self._from_py_unchecked(
            _resolve_ambuguity(
                _datetime.combine(date._py_date, self._py_dt.timetz()).replace(
                    fold=_as_fold(disambiguate)
                ),
                # mypy doesn't know that tzinfo is always a ZoneInfo here
                self._py_dt.tzinfo,  # type: ignore[arg-type]
                disambiguate,
            ),
            self._nanos,
        )

    def with_time(
        self, time: Time, /, disambiguate: Disambiguate = "raise"
    ) -> ZonedDateTime:
        """Create a new ZonedDateTime with the same date, but a different time.

        Example
        -------
        >>> d = ZonedDateTime(2020, 2, 3, 12, tz="Europe/Amsterdam")
        >>> d.with_time(Time(15, 30))
        ZonedDateTime(2020-02-03T15:30:00+02:00[Europe/Amsterdam])
        """
        return self._from_py_unchecked(
            _resolve_ambuguity(
                _datetime.combine(
                    self._py_dt, time._py_time, self._py_dt.tzinfo
                ).replace(fold=_as_fold(disambiguate)),
                # mypy doesn't know that tzinfo is always a ZoneInfo here
                self._py_dt.tzinfo,  # type: ignore[arg-type]
                disambiguate,
            ),
            time._nanos,
        )

    def replace(
        self, /, disambiguate: Disambiguate = "raise", **kwargs: Any
    ) -> ZonedDateTime:
        _check_invalid_replace_kwargs(kwargs)
        try:
            tz = kwargs.pop("tz")
        except KeyError:
            pass
        else:
            kwargs["tzinfo"] = ZoneInfo(tz)
        nanos = _pop_nanos_kwarg(kwargs, self._nanos)
        return self._from_py_unchecked(
            _resolve_ambuguity(
                self._py_dt.replace(fold=_as_fold(disambiguate), **kwargs),
                kwargs.get("tzinfo", self._py_dt.tzinfo),
                disambiguate,
            ),
            nanos,
        )

    @property
    def tz(self) -> str:
        """The timezone ID"""
        return self._py_dt.tzinfo.key  # type: ignore[union-attr,no-any-return]

    @property
    def offset(self) -> TimeDelta:
        return TimeDelta.from_py_timedelta(self._py_dt.utcoffset())  # type: ignore[arg-type]

    def __hash__(self) -> int:
        return hash((self._py_dt.astimezone(_UTC), self._nanos))

    def __eq__(self, other: object) -> bool:
        if not isinstance(other, _AwareDateTime):
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

    def exact_eq(self, other: ZonedDateTime, /) -> bool:
        return (
            self._py_dt.tzinfo is other._py_dt.tzinfo
            and self._py_dt == other._py_dt
            and self._py_dt.utcoffset() == other._py_dt.utcoffset()
        )

    def __lt__(self, other: _AwareDateTime) -> bool:
        if not isinstance(other, _AwareDateTime):
            return NotImplemented
        return self._py_dt.astimezone(_UTC) < other._py_dt

    def __le__(self, other: _AwareDateTime) -> bool:
        if not isinstance(other, _AwareDateTime):
            return NotImplemented
        return self._py_dt.astimezone(_UTC) <= other._py_dt

    def __gt__(self, other: _AwareDateTime) -> bool:
        if not isinstance(other, _AwareDateTime):
            return NotImplemented
        return self._py_dt.astimezone(_UTC) > other._py_dt

    def __ge__(self, other: _AwareDateTime) -> bool:
        if not isinstance(other, _AwareDateTime):
            return NotImplemented
        return self._py_dt.astimezone(_UTC) >= other._py_dt

    def __add__(self, delta: Delta) -> ZonedDateTime:
        """Add an amount of time, accounting for timezone changes (e.g. DST).

        Example
        -------
        >>> d = ZonedDateTime(2023, 10, 28, 12, tz="Europe/Amsterdam", disambiguate="earlier")
        >>> # adding exact units accounts for the DST transition
        >>> d + hours(24)
        ZonedDateTime(2023-10-29T11:00:00+01:00[Europe/Amsterdam])
        >>> # adding date units keeps the same local time
        >>> d + days(1)
        ZonedDateTime(2023-10-29T12:00:00+01:00[Europe/Amsterdam])

        Note
        ----
        Addition of calendar units follows RFC 5545
        (iCalendar) and the behavior of other established libraries:

        - Units are added from largest to smallest,
          truncating and/or wrapping after each step.
        - Adding days keeps the same local time. For example,
          scheduling a 11am event "a days later" will result in
          11am local time the next day, even if there was a DST transition.
          Scheduling it exactly 24 hours would have resulted in
          a different local time.
        - If the resulting time is amgiuous after shifting the date,
          the "compatible" disambiguation is used.
          This means that for gaps, time is skipped forward.
        """
        if isinstance(delta, (TimeDelta, DateDelta, DateTimeDelta)):
            py_dt = self._py_dt
            if delta._date_part:
                py_dt = self.with_date(
                    self.date() + delta._date_part,
                    disambiguate="compatible",
                )._py_dt

            delta_secs, nanos = divmod(
                delta._time_part._total_ns + self._nanos, 1_000_000_000
            )
            return self._from_py_unchecked(
                (
                    py_dt.astimezone(_UTC) + _timedelta(seconds=delta_secs)
                ).astimezone(self._py_dt.tzinfo),
                nanos,
            )
        else:
            return NotImplemented

    @overload
    def __sub__(self, other: _AwareDateTime) -> TimeDelta: ...

    @overload
    def __sub__(self, other: Delta) -> ZonedDateTime: ...

    def __sub__(
        self, other: Delta | _AwareDateTime
    ) -> _AwareDateTime | TimeDelta:
        """Subtract another datetime or duration"""
        if isinstance(other, _AwareDateTime):
            return TimeDelta.from_py_timedelta(
                # TODO incorrect
                self._py_dt.astimezone(_UTC)
                - other._py_dt
            )
        elif isinstance(other, (TimeDelta, DateDelta, DateTimeDelta)):
            return self + -other
        return NotImplemented

    def add(
        self,
        *,
        years: int = 0,
        months: int = 0,
        weeks: int = 0,
        # TODO: helpful error when giving days over calendar days?
        days: int = 0,
        hours: float = 0,
        minutes: float = 0,
        seconds: float = 0,
        milliseconds: float = 0,
        microseconds: float = 0,
        nanoseconds: int = 0,
        disambiguate: Disambiguate = "raise",
    ) -> ZonedDateTime:
        """Add a time amount to this datetime.

        Units are added from largest to smallest,
        truncating and/or wrapping after each step.

        Example
        -------
        >>> d = ZonedDateTime(2020, 8, 15, hour=23, minute=12, tz="Europe/London")
        >>> d.add(hours=24, seconds=5)
        ZonedDateTime(2020-08-16 23:12:05+01:00[Europe/London])
        >>> d.add(years=1, days=2, minutes=5)
        ZonedDateTime(2021-08-17 23:17:00+01:00[Europe/London])
        """
        if years or months or weeks or days:
            self = self.with_date(
                self.date()
                ._add_months(years * 12 + months)
                ._add_days(weeks * 7 + days),
                disambiguate=disambiguate,
            )
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
        # TODO disambiguate
    ) -> ZonedDateTime:
        """Subtract a time amount from this datetime.

        Units are subtracted from largest to smallest,
        wrapping and/or truncating after each step.

        Example
        -------
        >>> d = ZonedDateTime(2020, 8, 15, hour=23, minute=12, tz="Europe/London")
        >>> d.subtract(hours=24, seconds=5)
        ZonedDateTime(2020-08-14 23:11:55+01:00[Europe/London])
        >>> d.subtract(years=1, days=2, minutes=5)
        ZonedDateTime(2019-08-13 23:06:00+01:00[Europe/London])
        """
        return self.add(
            years=-years,
            months=-months,
            weeks=-weeks,
            days=-days,
            hours=-hours,
            minutes=-minutes,
            seconds=-seconds,
            milliseconds=-milliseconds,
            microseconds=-microseconds,
            nanoseconds=-nanoseconds,
        )

    def is_ambiguous(self) -> bool:
        """Whether the local time is ambiguous, e.g. due to a DST transition.

        Example
        -------
        >>> ZonedDateTime(2020, 8, 15, 23, tz="Europe/London", disambiguate="later").ambiguous()
        False
        >>> ZonedDateTime(2023, 10, 29, 2, 15, tz="Europe/Amsterdam", disambiguate="later").ambiguous()
        True
        """
        # we make use of a quirk of the standard library here:
        # ambiguous datetimes are never equal across timezones
        return self._py_dt.astimezone(_UTC) != self._py_dt

    def in_utc(self) -> UTCDateTime:
        return UTCDateTime._from_py_unchecked(
            self._py_dt.astimezone(_UTC), self._nanos
        )

    @overload
    def in_fixed_offset(self, /) -> OffsetDateTime: ...

    @overload
    def in_fixed_offset(
        self, offset: int | TimeDelta, /
    ) -> OffsetDateTime: ...

    def in_fixed_offset(
        self, offset: int | TimeDelta | None = None, /
    ) -> OffsetDateTime:
        return OffsetDateTime._from_py_unchecked(
            self._py_dt.astimezone(
                # mypy doesn't know that offset is never None
                _timezone(self._py_dt.utcoffset())  # type: ignore[arg-type]
                if offset is None
                else _load_offset(offset)
            ),
            self._nanos,
        )

    def in_tz(self, tz: str, /) -> ZonedDateTime:
        return self._from_py_unchecked(
            self._py_dt.astimezone(ZoneInfo(tz)), self._nanos
        )

    def __repr__(self) -> str:
        return f"ZonedDateTime({str(self).replace('T', ' ')})"

    # a custom pickle implementation with a smaller payload
    def __reduce__(self) -> tuple[object, ...]:
        return (
            _unpkl_zoned,
            (
                pack(
                    "<HBBBBBIl",
                    *self._py_dt.timetuple()[:6],
                    self._nanos,
                    int(self._py_dt.utcoffset().total_seconds()),  # type: ignore[union-attr]
                ),
                self._py_dt.tzinfo.key,  # type: ignore[union-attr]
            ),
        )


# A separate function is needed for unpickling, because the
# constructor doesn't accept positional tz and fold arguments as
# required by __reduce__.
# Also, it allows backwards-compatible changes to the pickling format.
def _unpkl_zoned(
    data: bytes,
    tz: str,
) -> ZonedDateTime:
    year, month, day, hour, minute, second, nanos, offset_secs = unpack(
        "<HBBBBBIl", data
    )
    return ZonedDateTime._from_py_unchecked(
        _adjust_fold_to_offset(
            _datetime(
                year,
                month,
                day,
                hour,
                minute,
                second,
                0,
                ZoneInfo(tz),
            ),
            _timedelta(seconds=offset_secs),
        ),
        nanos,
    )


@final
class LocalSystemDateTime(_AwareDateTime):
    """Represents a time in the system timezone. Unlike OffsetDateTime,
    it knows about the system timezone and its DST transitions.

    Instances have the fixed offset of the system timezone
    at the time of initialization.
    The system timezone may change afterwards,
    but instances of this type will not reflect that change.

    Example
    -------
    >>> # 8:00 in the system timezone—Paris in this case
    >>> alarm = LocalSystemDateTime(2024, 3, 31, hour=6)
    LocalSystemDateTime(2024-03-31 06:00:00+02:00)
    ...
    >>> # Conversion based on Paris' offset
    >>> alarm.in_utc()
    UTCDateTime(2024-03-31 04:00:00Z)
    ...
    >>> # unlike OffsetDateTime, it knows about DST transitions
    >>> bedtime = alarm - hours(8)
    LocalSystemDateTime(2024-03-30 21:00:00+01:00)

    Handling ambiguity
    ------------------

    The system timezone may have ambiguous datetimes,
    such as during a DST transition.
    The ``disambiguate`` argument controls how ambiguous datetimes are handled:

    +------------------+-------------------------------------------------+
    | ``disambiguate`` | Behavior in case of ambiguity                   |
    +==================+=================================================+
    | ``"raise"``      | (default) Refuse to guess:                      |
    |                  | raise :exc:`~whenever.AmbiguousTime`            |
    |                  | or :exc:`~whenever.SkippedTime` exception.      |
    +------------------+-------------------------------------------------+
    | ``"earlier"``    | Choose the earlier of the two options           |
    +------------------+-------------------------------------------------+
    | ``"later"``      | Choose the later of the two options             |
    +------------------+-------------------------------------------------+
    | ``"compatible"`` | Choose "earlier" for backward transitions and   |
    |                  | "later" for forward transitions. This matches   |
    |                  | the behavior of other established libraries,    |
    |                  | and the industry standard RFC 5545.             |
    |                  | It corresponds to setting ``fold=0`` in the     |
    |                  | standard library.                               |
    +------------------+-------------------------------------------------+

    Note
    ----
    The default string format is:

    .. code-block:: text

       YYYY-MM-DDTHH:MM:SS(.ffffff)±HH:MM(:SS(.ffffff))

    This format is both RFC 3339 and ISO 8601 compliant.

    Note
    ----
    The corresponding :class:`~datetime.datetime` object has
    a fixed :class:`~datetime.timezone` tzinfo.
    """

    __slots__ = ()

    def __init__(
        self,
        year: int,
        month: int,
        day: int,
        hour: int = 0,
        minute: int = 0,
        second: int = 0,
        nanosecond: int = 0,
        *,
        disambiguate: Disambiguate = "raise",
    ) -> None:
        self._py_dt = _resolve_local_ambiguity(
            _datetime(
                year,
                month,
                day,
                hour,
                minute,
                second,
                0,
                fold=_as_fold(disambiguate),
            ),
            disambiguate,
        )
        if nanosecond < 0 or nanosecond >= 1_000_000_000:
            raise ValueError("nanosecond out of range")
        self._nanos = nanosecond

    @classmethod
    def now(cls) -> LocalSystemDateTime:
        """Create an instance from the current time"""
        secs, nanos = divmod(time_ns(), 1_000_000_000)
        # TODO: does now go well in rust with fromtimestamp() not working to aware dt?
        return cls._from_py_unchecked(
            _datetime.fromtimestamp(secs, _UTC).astimezone(None), nanos
        )

    default_format = OffsetDateTime.default_format

    @classmethod
    def from_default_format(cls, s: str, /) -> LocalSystemDateTime:
        odt = OffsetDateTime.from_default_format(s)
        return cls._from_py_unchecked(odt._py_dt, odt._nanos)

    @classmethod
    def from_timestamp(cls, i: int, /) -> LocalSystemDateTime:
        """Create an instace from a UNIX timestamp.
        The inverse of :meth:`~_AwareDateTime.timestamp`.

        Example
        -------
        >>> # assuming system timezone is America/New_York
        >>> LocalSystemDateTime.from_timestamp(0)
        LocalSystemDateTime(1969-12-31T19:00:00-05:00)
        >>> LocalSystemDateTime.from_timestamp(1_123_000_000)
        LocalSystemDateTime(2005-08-12T12:26:40-04:00)
        >>> LocalSystemDateTime.from_timestamp(d.timestamp()) == d
        True
        """
        return cls._from_py_unchecked(_fromtimestamp(i, _UTC).astimezone(), 0)

    @classmethod
    def from_timestamp_millis(cls, i: int, /) -> LocalSystemDateTime:
        """Create an instace from a UNIX timestamp in milliseconds."""
        secs, millis = divmod(i, 1_000)
        return cls._from_py_unchecked(
            _fromtimestamp(secs, _UTC).astimezone(), millis * 1_000_000
        )

    @classmethod
    def from_timestamp_nanos(cls, i: int, /) -> LocalSystemDateTime:
        """Create an instace from a UNIX timestamp in milliseconds."""
        secs, nanos = divmod(i, 1_000_000_000)
        return cls._from_py_unchecked(
            _fromtimestamp(secs, _UTC).astimezone(), nanos
        )

    @classmethod
    def from_py_datetime(cls, d: _datetime, /) -> LocalSystemDateTime:
        odt = OffsetDateTime.from_py_datetime(d)
        return cls._from_py_unchecked(odt._py_dt, odt._nanos)

    def __repr__(self) -> str:
        return f"LocalSystemDateTime({str(self).replace('T', ' ')})"

    @property
    def offset(self) -> TimeDelta:
        return TimeDelta.from_py_timedelta(self._py_dt.utcoffset())  # type: ignore[arg-type]

    # FUTURE: expose the tzname?

    def __eq__(self, other: object) -> bool:
        if not isinstance(
            other, (UTCDateTime, OffsetDateTime, LocalSystemDateTime)
        ):
            return NotImplemented
        return (self._py_dt, self._nanos) == (other._py_dt, other._nanos)

    def __lt__(self, other: _AwareDateTime) -> bool:
        if not isinstance(other, _AwareDateTime):
            return NotImplemented
        return (self._py_dt, self._nanos) < (other._py_dt, other._nanos)

    def __le__(self, other: _AwareDateTime) -> bool:
        if not isinstance(other, _AwareDateTime):
            return NotImplemented
        return (self._py_dt, self._nanos) <= (other._py_dt, other._nanos)

    def __gt__(self, other: _AwareDateTime) -> bool:
        if not isinstance(other, _AwareDateTime):
            return NotImplemented
        return (self._py_dt, self._nanos) > (other._py_dt, other._nanos)

    def __ge__(self, other: _AwareDateTime) -> bool:
        if not isinstance(other, _AwareDateTime):
            return NotImplemented
        return (self._py_dt, self._nanos) >= (other._py_dt, other._nanos)

    def exact_eq(self, other: LocalSystemDateTime) -> bool:
        return (
            self._py_dt == other._py_dt
            and self._nanos == other._nanos
            and self._py_dt.tzinfo == other._py_dt.tzinfo
        )

    def with_date(
        self, date: Date, /, disambiguate: Disambiguate = "raise"
    ) -> LocalSystemDateTime:
        """Create a new instance with the same time, but a different date.

        Example
        -------
        >>> d = LocalSystemDateTime(2020, 3, 28, 12)
        >>> d.with_date(Date(2023, 10, 29))
        LocalSystemDateTime(2023-10-29T12:00:00+02:00)
        """
        return self._from_py_unchecked(
            _resolve_local_ambiguity(
                _datetime.combine(date._py_date, self._py_dt.time()).replace(
                    fold=_as_fold(disambiguate)
                ),
                disambiguate,
            ),
            self._nanos,
        )

    def with_time(
        self, time: Time, /, disambiguate: Disambiguate = "raise"
    ) -> LocalSystemDateTime:
        """Create a new instance with the same date, but a different time.

        Example
        -------
        >>> d = LocalSystemDateTime(2020, 2, 3, 12)
        >>> d.with_time(Time(15, 30))
        LocalSystemDateTime(2020-02-03T15:30:00+02:00)
        """
        return self._from_py_unchecked(
            _resolve_local_ambiguity(
                _datetime.combine(self._py_dt, time._py_time).replace(
                    fold=_as_fold(disambiguate)
                ),
                disambiguate,
            ),
            time._nanos,
        )

    def replace(
        self, /, disambiguate: Disambiguate = "raise", **kwargs: Any
    ) -> LocalSystemDateTime:
        _check_invalid_replace_kwargs(kwargs)
        nanos = _pop_nanos_kwarg(kwargs, self._nanos)
        return self._from_py_unchecked(
            _resolve_local_ambiguity(
                self._py_dt.replace(
                    tzinfo=None, fold=_as_fold(disambiguate), **kwargs
                ),
                disambiguate,
            ),
            nanos,
        )

    def __hash__(self) -> int:
        return hash((self._py_dt, self._nanos))

    def __add__(self, delta: Delta) -> LocalSystemDateTime:
        """Add a duration to this datetime

        Example
        -------
        >>> # assuming system local TZ=Europe/Amsterdam
        >>> d = LocalSystemDateTime(2023, 10, 28, 12, disambiguate="earlier")
        >>> # adding exact units accounts for the DST transition
        >>> d + hours(24)
        LocalSystemDateTime(2023-10-29T11:00:00+01:00)
        >>> # adding date units keeps the same local time
        >>> d + days(1)
        LocalSystemDateTime(2023-10-29T12:00:00+01:00)

        Note
        ----
        Addition of calendar units follows RFC 5545
        (iCalendar) and the behavior of other established libraries:

        - Units are added from largest to smallest,
          truncating and/or wrapping after each step.
        - Adding days keeps the same local time. For example,
          scheduling a 11am event "a days later" will result in
          11am local time the next day, even if there was a DST transition.
          Scheduling it exactly 24 hours would have resulted in
          a different local time.
        - If the resulting time is amgiuous after shifting the date,
          the "compatible" disambiguation is used.
          This means that for gaps, time is skipped forward.
        """
        if isinstance(delta, (TimeDelta, DateDelta, DateTimeDelta)):
            py_dt = self._py_dt
            if delta._date_part:
                py_dt = self.with_date(
                    self.date() + delta._date_part,
                    disambiguate="compatible",
                )._py_dt

            delta_secs, nanos = divmod(
                delta._time_part._total_ns + self._nanos, 1_000_000_000
            )

            return self._from_py_unchecked(
                (py_dt + _timedelta(seconds=delta_secs)).astimezone(), nanos
            )
        return NotImplemented

    @overload
    def __sub__(self, other: _AwareDateTime) -> TimeDelta: ...

    @overload
    def __sub__(self, other: Delta) -> LocalSystemDateTime: ...

    def __sub__(self, other: Delta | _AwareDateTime) -> _AwareDateTime | Delta:
        """Subtract another datetime or duration

        Example
        -------
        >>> d = LocalSystemDateTime(2020, 8, 15, hour=23, minute=12)
        >>> d - hours(24) - seconds(5)
        LocalSystemDateTime(2020-08-14 23:11:55)
        """
        if isinstance(other, _AwareDateTime):
            # TODO incorrect
            return TimeDelta.from_py_timedelta(self._py_dt - other._py_dt)
        elif isinstance(other, (TimeDelta, DateDelta, DateTimeDelta)):
            return self + -other
        return NotImplemented

    def add(
        self,
        *,
        years: int = 0,
        months: int = 0,
        weeks: int = 0,
        # TODO: helpful error when giving days over calendar days?
        days: int = 0,
        hours: float = 0,
        minutes: float = 0,
        seconds: float = 0,
        milliseconds: float = 0,
        microseconds: float = 0,
        nanoseconds: int = 0,
        disambiguate: Disambiguate = "raise",
    ) -> LocalSystemDateTime:
        """Add a time amount to this datetime.

        Units are added from largest to smallest,
        truncating and/or wrapping after each step.

        Example
        -------
        >>> d = LocalSystemDateTime(2020, 8, 15, hour=23, minute=12)
        >>> d.add(hours=24, seconds=5)
        LocalSystemDateTime(2020-08-16 23:12:05+01:00)
        >>> d.add(years=1, days=2, minutes=5)
        LocalSystemDateTime(2021-08-17 23:17:00+01:00)
        """
        # TODO: also in ZonedDateTime
        months_total = years * 12 + months
        days_total = weeks * 7 + days
        if months_total or days_total:
            self = self.with_date(
                self.date()._add_months(months_total)._add_days(days_total),
                disambiguate=disambiguate,
            )
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
        disambiguate: Disambiguate = "raise",
    ) -> LocalSystemDateTime:
        """Subtract a time amount from this datetime.

        Units are subtracted from largest to smallest,
        wrapping and/or truncating after each step.

        Example
        -------
        >>> d = LocalSystemDateTime(2020, 8, 15, hour=23, minute=12)
        >>> d.subtract(hours=24, seconds=5)
        LocalSystemDateTime(2020-08-14 23:11:55+01:00)
        >>> d.subtract(years=1, days=2, minutes=5)
        LocalSystemDateTime(2019-08-13 23:06:00+01:00)
        """
        return self.add(
            years=-years,
            months=-months,
            weeks=-weeks,
            days=-days,
            hours=-hours,
            minutes=-minutes,
            seconds=-seconds,
            milliseconds=-milliseconds,
            microseconds=-microseconds,
            nanoseconds=-nanoseconds,
            disambiguate=disambiguate,
        )

    def in_utc(self) -> UTCDateTime:
        return UTCDateTime._from_py_unchecked(
            self._py_dt.astimezone(_UTC), self._nanos
        )

    @overload
    def in_fixed_offset(self, /) -> OffsetDateTime: ...

    @overload
    def in_fixed_offset(
        self, offset: int | TimeDelta, /
    ) -> OffsetDateTime: ...

    def in_fixed_offset(
        self, offset: int | TimeDelta | None = None, /
    ) -> OffsetDateTime:
        return OffsetDateTime._from_py_unchecked(
            (
                self._py_dt
                if offset is None
                else self._py_dt.astimezone(_load_offset(offset))
            ),
            self._nanos,
        )

    def in_tz(self, tz: str, /) -> ZonedDateTime:
        return ZonedDateTime._from_py_unchecked(
            self._py_dt.astimezone(ZoneInfo(tz)), self._nanos
        )

    def in_local_system(self) -> LocalSystemDateTime:
        return self._from_py_unchecked(self._py_dt.astimezone(), self._nanos)

    # a custom pickle implementation with a smaller payload
    def __reduce__(self) -> tuple[object, ...]:
        return (
            _unpkl_local,
            (
                pack(
                    "<HBBBBBIl",
                    *self._py_dt.timetuple()[:6],
                    self._nanos,
                    int(self._py_dt.utcoffset().total_seconds()),  # type: ignore[union-attr]
                ),
            ),
        )


# A separate function is needed for unpickling, because the
# constructor doesn't accept positional fold arguments as
# required by __reduce__.
# Also, it allows backwards-compatible changes to the pickling format.
def _unpkl_local(data: bytes) -> LocalSystemDateTime:
    year, month, day, hour, minute, second, nanos, offset_secs = unpack(
        "<HBBBBBIl", data
    )
    return LocalSystemDateTime._from_py_unchecked(
        _datetime(
            year,
            month,
            day,
            hour,
            minute,
            second,
            0,
            _timezone(_timedelta(seconds=offset_secs)),
        ),
        nanos,
    )


@final
class NaiveDateTime(_DateTime):
    """A plain datetime without timezone or offset.

    It can't be mixed with aware datetimes.
    Conversion to aware datetimes can only be done by
    explicitly assuming a timezone or offset.

    Examples of when to use this type:

    - You need to express a date and time as it would be observed locally
      on the "wall clock" or calendar.
    - You receive a date and time without any timezone information,
      and you need a type to represent this lack of information.
    - In the rare case you truly don't need to account for timezones,
      or Daylight Saving Time transitions. For example, when modeling
      time in a simulation game.

    Note
    ----
    The default string format is:

    .. code-block:: text

       YYYY-MM-DDTHH:MM:SS(.fff(fff))

    This format is ISO 8601 compliant, but not RFC 3339 compliant,
    because this requires a UTC offset.
    """

    def __init__(
        self,
        year: int,
        month: int,
        day: int,
        hour: int = 0,
        minute: int = 0,
        second: int = 0,
        nanosecond: int = 0,
    ) -> None:
        self._py_dt = _datetime(year, month, day, hour, minute, second)
        self._nanos = nanosecond

    def default_format(self) -> str:
        return (
            (self._py_dt.isoformat() + f".{self._nanos:09d}").rstrip("0")
            if self._nanos
            else self._py_dt.isoformat()
        )

    @classmethod
    def from_default_format(cls, s: str, /) -> NaiveDateTime:
        if (match := _match_naive_str(s)) is None:
            raise ValueError(f"Invalid format: {s!r}")
        year, month, day, hour, minute, second = map(int, match.groups()[:6])
        nanos = int(match.group(7).ljust(9, "0")) if match.group(7) else 0
        return cls._from_py_unchecked(
            _datetime(year, month, day, hour, minute, second), nanos
        )

    @classmethod
    def from_py_datetime(cls, d: _datetime, /) -> NaiveDateTime:
        if d.tzinfo is not None:
            raise ValueError(
                "Can only create NaiveDateTime from a naive datetime, "
                f"got datetime with tzinfo={d.tzinfo!r}"
            )
        return cls._from_py_unchecked(
            d.replace(microsecond=0), d.microsecond * 1_000
        )

    def replace(self, /, **kwargs: Any) -> NaiveDateTime:
        if not _no_tzinfo_fold_or_ms(kwargs):
            raise TypeError(
                "tzinfo, fold, or microsecond are not allowed arguments"
            )
        nanos = kwargs.pop("nanosecond", self._nanos)
        if not 0 <= nanos < 1_000_000_000:
            raise ValueError("Invalid nanosecond value")
        return self._from_py_unchecked(self._py_dt.replace(**kwargs), nanos)

    def with_date(self, d: Date, /) -> NaiveDateTime:
        return self._from_py_unchecked(
            _datetime.combine(d._py_date, self._py_dt.time()), self._nanos
        )

    def with_time(self, t: Time, /) -> NaiveDateTime:
        return self._from_py_unchecked(
            _datetime.combine(self._py_dt.date(), t._py_time), t._nanos
        )

    def __hash__(self) -> int:
        return hash((self._py_dt, self._nanos))

    def __eq__(self, other: object) -> bool:
        """Compare objects for equality.
        Only ever equal to other :class:`NaiveDateTime` instances with the
        same values.

        Warning
        -------
        To comply with the Python data model, this method can't
        raise a :exc:`TypeError` when comparing with other types.
        Although it seems to be the sensible response, it would result in
        `surprising behavior <https://stackoverflow.com/a/33417512>`_
        when using values as dictionary keys.

        Use mypy's ``--strict-equality`` flag to detect and prevent this.

        Example
        -------
        >>> NaiveDateTime(2020, 8, 15, 23) == NaiveDateTime(2020, 8, 15, 23)
        True
        >>> NaiveDateTime(2020, 8, 15, 23, 1) == NaiveDateTime(2020, 8, 15, 23)
        False
        >>> NaiveDateTime(2020, 8, 15) == UTCDateTime(2020, 8, 15)
        False  # Use mypy's --strict-equality flag to detect this.
        """
        if not isinstance(other, NaiveDateTime):
            return NotImplemented
        return (self._py_dt, self._nanos) == (other._py_dt, other._nanos)

    MIN: ClassVar[NaiveDateTime]
    MAX: ClassVar[NaiveDateTime]

    def __lt__(self, other: NaiveDateTime) -> bool:
        if not isinstance(other, NaiveDateTime):
            return NotImplemented
        return self._py_dt < other._py_dt

    def __le__(self, other: NaiveDateTime) -> bool:
        if not isinstance(other, NaiveDateTime):
            return NotImplemented
        return self._py_dt <= other._py_dt

    def __gt__(self, other: NaiveDateTime) -> bool:
        if not isinstance(other, NaiveDateTime):
            return NotImplemented
        return self._py_dt > other._py_dt

    def __ge__(self, other: NaiveDateTime) -> bool:
        if not isinstance(other, NaiveDateTime):
            return NotImplemented
        return self._py_dt >= other._py_dt

    def __add__(self, delta: Delta) -> NaiveDateTime:
        """Add a delta to this datetime

        Example
        -------
        >>> d = NaiveDateTime(2020, 8, 15, hour=23, minute=12)
        >>> d + hours(24) + seconds(5)
        NaiveDateTime(2020-08-16 23:12:05)
        >>> d + years(3) + months(2) + days(1)
        NaiveDateTime(2023-10-16 23:12:00)
        """
        if isinstance(delta, (TimeDelta, DateDelta, DateTimeDelta)):
            delta_secs, nanos = divmod(
                self._nanos + delta._time_part._total_ns,
                1_000_000_000,
            )
            return self._from_py_unchecked(
                _datetime.combine(
                    (self.date() + delta._date_part)._py_date,
                    self._py_dt.time(),
                )
                + _timedelta(seconds=delta_secs),
                nanos,
            )
        return NotImplemented

    @overload
    def __sub__(self, other: NaiveDateTime) -> TimeDelta: ...

    @overload
    def __sub__(self, other: Delta) -> NaiveDateTime: ...

    def __sub__(
        self, other: Delta | NaiveDateTime
    ) -> NaiveDateTime | TimeDelta:
        """Subtract another datetime or time amount

        Example
        -------
        >>> d = NaiveDateTime(2020, 8, 15, hour=23, minute=12)
        >>> d - hours(24) - seconds(5)
        NaiveDateTime(2020-08-14 23:11:55)
        >>> d - NaiveDateTime(2020, 8, 14)
        TimeDelta(47:12:00)
        >>> d - years(3) - months(2) - days(1) - minutes(5)
        NaiveDateTime(2017-06-14 23:07:00)
        """
        if isinstance(other, NaiveDateTime):
            py_delta = self._py_dt - other._py_dt
            return TimeDelta(
                seconds=py_delta.days * 86_400 + py_delta.seconds,
                nanoseconds=self._nanos - other._nanos,
            )
        elif isinstance(other, (TimeDelta, DateDelta, DateTimeDelta)):
            return self + -other
        return NotImplemented

    def add(
        self,
        *,
        years: int = 0,
        months: int = 0,
        weeks: int = 0,
        # TODO: helpful error when giving days over calendar days?
        days: int = 0,
        hours: float = 0,
        minutes: float = 0,
        seconds: float = 0,
        milliseconds: float = 0,
        microseconds: float = 0,
        nanoseconds: int = 0,
    ) -> NaiveDateTime:
        """Add a time amount to this datetime.

        Units are added from largest to smallest,
        truncating and/or wrapping after each step.

        Example
        -------
        >>> d = NaiveDateTime(2020, 8, 15, hour=23, minute=12)
        >>> d.add(hours=24, seconds=5)
        NaiveDateTime(2020-08-16 23:12:05)
        >>> d.add(years=1, days=2, minutes=5)
        NaiveDateTime(2021-08-17 23:17:00)
        """
        return self.with_date(
            self.date()
            ._add_months(years * 12 + months)
            ._add_days(weeks * 7 + days)
        ) + TimeDelta(
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
    ) -> NaiveDateTime:
        """Subtract a time amount from this datetime.

        Units are subtracted from largest to smallest,
        wrapping and/or truncating after each step.

        Example
        -------
        >>> d = NaiveDateTime(2020, 8, 15, hour=23, minute=12)
        >>> d.subtract(hours=24, seconds=5)
        NaiveDateTime(2020-08-14 23:11:55)
        >>> d.subtract(years=1, days=2, minutes=5)
        NaiveDateTime(2019-08-13 23:06:00)
        """
        return self.add(
            years=-years,
            months=-months,
            weeks=-weeks,
            days=-days,
            hours=-hours,
            minutes=-minutes,
            seconds=-seconds,
            milliseconds=-milliseconds,
            microseconds=-microseconds,
            nanoseconds=-nanoseconds,
        )

    @classmethod
    def strptime(cls, s: str, /, fmt: str) -> NaiveDateTime:
        """Simple alias for
        ``NaiveDateTime.from_py_datetime(datetime.strptime(s, fmt))``

        Example
        -------
        >>> NaiveDateTime.strptime("2020-08-15", "%Y-%m-%d")
        NaiveDateTime(2020-08-15 00:00:00)

        Note
        ----
        The parsed ``tzinfo`` must be be ``None``.
        This means you can't include the directives ``%z``, ``%Z``, or ``%:z``
        in the format string.
        """
        parsed = _datetime.strptime(s, fmt)
        if parsed.tzinfo is not None:
            raise ValueError(
                "Parsed datetime can't have an offset. "
                "Do not use %z, %Z, or %:z in the format string"
            )
        return cls._from_py_unchecked(
            parsed.replace(microsecond=0), parsed.microsecond * 1_000
        )

    def assume_utc(self) -> UTCDateTime:
        """Assume the datetime is in UTC,
        creating a :class:`~whenever.UTCDateTime` instance.

        Example
        -------
        >>> NaiveDateTime(2020, 8, 15, 23, 12).assume_utc()
        UTCDateTime(2020-08-15 23:12:00Z)
        """
        return UTCDateTime._from_py_unchecked(
            self._py_dt.replace(tzinfo=_UTC), self._nanos
        )

    def assume_fixed_offset(
        self, offset: int | TimeDelta, /
    ) -> OffsetDateTime:
        """Assume the datetime is in the given offset,
        creating a :class:`~whenever.OffsetDateTime` instance.

        Example
        -------
        >>> NaiveDateTime(2020, 8, 15, 23, 12).assume_fixed_offset(+2)
        OffsetDateTime(2020-08-15 23:12:00+02:00)
        """
        return OffsetDateTime._from_py_unchecked(
            self._py_dt.replace(tzinfo=_load_offset(offset)), self._nanos
        )

    def assume_in_tz(
        self, tz: str, /, disambiguate: Disambiguate = "raise"
    ) -> ZonedDateTime:
        """Assume the datetime is in the given timezone,
        creating a :class:`~whenever.ZonedDateTime` instance.

        Example
        -------
        >>> NaiveDateTime(2020, 8, 15, 23, 12).assume_in_tz("Europe/Amsterdam")
        ZonedDateTime(2020-08-15 23:12:00+02:00[Europe/Amsterdam])
        """
        return ZonedDateTime._from_py_unchecked(
            _resolve_ambuguity(
                self._py_dt.replace(
                    tzinfo=(zone := ZoneInfo(tz)), fold=_as_fold(disambiguate)
                ),
                zone,
                disambiguate,
            ),
            self._nanos,
        )

    def assume_in_local_system(
        self, disambiguate: Disambiguate = "raise"
    ) -> LocalSystemDateTime:
        """Assume the datetime is in the system timezone,
        creating a :class:`~whenever.LocalSystemDateTime` instance.

        Example
        -------
        >>> # assuming system timezone is America/New_York
        >>> NaiveDateTime(2020, 8, 15, 23, 12).assume_in_local_system()
        LocalSystemDateTime(2020-08-15 23:12:00-04:00)
        """
        return LocalSystemDateTime._from_py_unchecked(
            _resolve_local_ambiguity(
                self._py_dt.replace(fold=_as_fold(disambiguate)),
                disambiguate,
            ),
            self._nanos,
        )

    def __repr__(self) -> str:
        return f"NaiveDateTime({str(self).replace('T', ' ')})"

    def common_iso8601(self) -> str:
        """Format in the commonly used ISO 8601 format.

        Inverse of :meth:`from_common_iso8601`.

        Example
        -------
        >>> NaiveDateTime(2020, 8, 15, 23, 12).common_iso8601()
        '2020-08-15T23:12:00'
        """
        return self.default_format()

    @classmethod
    def from_common_iso8601(cls, s: str, /) -> NaiveDateTime:
        """Parse from the commonly used ISO 8601 format
        ``YYYY-MM-DDTHH:MM:SS``, where seconds may be fractional.

        Inverse of :meth:`common_iso8601`.

        Example
        -------
        >>> NaiveDateTime.from_common_iso8601("2020-08-15T23:12:00")
        NaiveDateTime(2020-08-15 23:12:00)
        """
        return cls.from_default_format(s)

    # a custom pickle implementation with a smaller payload
    def __reduce__(self) -> tuple[object, ...]:
        return (
            _unpkl_naive,
            (pack("<HBBBBBI", *self._py_dt.timetuple()[:6], self._nanos),),
        )


# A separate unpickling function allows us to make backwards-compatible changes
# to the pickling format in the future
@no_type_check
def _unpkl_naive(data: bytes) -> NaiveDateTime:
    return NaiveDateTime(*unpack("<HBBBBBI", data))


class AmbiguousTime(Exception):
    """A datetime is unexpectedly ambiguous"""

    @staticmethod
    def for_timezone(d: _datetime, tz: ZoneInfo) -> AmbiguousTime:
        return AmbiguousTime(
            f"{d.replace(tzinfo=None)} is ambiguous " f"in timezone {tz.key!r}"
        )

    @staticmethod
    def for_system_timezone(d: _datetime) -> AmbiguousTime:
        return AmbiguousTime(
            f"{d.replace(tzinfo=None)} is ambiguous in the system timezone"
        )


class SkippedTime(Exception):
    """A datetime is skipped in a timezone, e.g. because of DST"""

    @staticmethod
    def for_timezone(d: _datetime, tz: ZoneInfo) -> SkippedTime:
        return SkippedTime(
            f"{d.replace(tzinfo=None)} is skipped " f"in timezone {tz.key!r}"
        )

    @staticmethod
    def for_system_timezone(d: _datetime) -> SkippedTime:
        return SkippedTime(
            f"{d.replace(tzinfo=None)} is skipped in the system timezone"
        )


class InvalidOffset(ValueError):
    """A string has an invalid offset for the given zone"""


def _resolve_ambuguity(
    dt: _datetime, zone: ZoneInfo, disambiguate: Disambiguate
) -> _datetime:
    dt_utc = dt.astimezone(_UTC)
    # Non-existent times: they don't survive a UTC roundtrip
    if dt_utc.astimezone(zone) != dt:
        if disambiguate == "raise":
            raise SkippedTime.for_timezone(dt, zone)
        elif disambiguate != "compatible":  # i.e. "earlier" or "later"
            # In gaps, the relationship between
            # fold and earlier/later is reversed
            dt = dt.replace(fold=not dt.fold)
        # perform the normalisation, shifting away from non-existent times
        dt = dt.astimezone(_UTC).astimezone(zone)
    # Ambiguous times: they're never equal to other timezones
    elif disambiguate == "raise" and dt_utc != dt:
        raise AmbiguousTime.for_timezone(dt, zone)
    return dt


# Whether the fold of a local time needs to be flipped in a gap
# was changed (fixed) in Python 3.12. See cpython/issues/83861
_requires_flip: Callable[[Disambiguate], bool] = (
    "compatible".__ne__ if sys.version_info > (3, 12) else "compatible".__eq__
)


def _resolve_local_ambiguity(
    dt: _datetime, disambiguate: Disambiguate
) -> _datetime:
    assert dt.tzinfo is None
    norm = dt.astimezone(_UTC).astimezone()
    # Non-existent times: they don't survive a UTC roundtrip
    if norm.replace(tzinfo=None) != dt:
        if disambiguate == "raise":
            raise SkippedTime.for_system_timezone(dt)
        elif _requires_flip(disambiguate):
            dt = dt.replace(fold=not dt.fold)
        # perform the normalisation, shifting away from non-existent times
        norm = dt.astimezone(_UTC).astimezone()
    # Ambiguous times: their UTC depends on the fold
    elif disambiguate == "raise" and norm != dt.replace(fold=1).astimezone(
        _UTC
    ):
        raise AmbiguousTime.for_system_timezone(dt)
    return norm


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
_DT_RE_GROUPED = r"(\d{4})-([0-2]\d)-([0-3]\d)T([0-2]\d):([0-5]\d):([0-5]\d)(?:\.(\d{1,9}))?"
_OFFSET_DATETIME_RE = (
    _DT_RE_GROUPED + r"(?:([+-])(\d{2}):(\d{2})(?::(\d{2}))?|Z)"
)
_match_utc_str = re.compile(rf"{_DT_RE_GROUPED}Z", re.ASCII).fullmatch
_match_naive_str = re.compile(_DT_RE_GROUPED, re.ASCII).fullmatch
_match_offset_str = re.compile(_OFFSET_DATETIME_RE, re.ASCII).fullmatch
_match_zoned_str = re.compile(
    _OFFSET_DATETIME_RE + r"\[([^\]]+)\]", re.ASCII
).fullmatch
_fromisoformat = _datetime.fromisoformat
_fromtimestamp = _datetime.fromtimestamp
# TODO ensure only ASCII
_match_utc_rfc3339 = re.compile(
    r"(\d{4})-([0-1]\d)-([0-3]\d)[ _Tt]([0-2]\d):([0-5]\d):([0-6]\d)(?:\.(\d{1,9}))?(?:[Zz]|[+-]00:00)",
    re.ASCII,
).fullmatch
_match_rfc3339 = re.compile(
    r"(\d{4})-([0-2]\d)-([0-3]\d)[Tt_ ]([0-2]\d):([0-5]\d):([0-5]\d)(?:\.(\d{1,9}))?"
    r"(?:[Zz]|([+-])(\d{2}):(\d{2}))",
    re.ASCII,
).fullmatch
_match_datetimedelta = re.compile(
    r"([-+]?)P(?:(\d+)Y)?(?:(\d+)M)?(?:(\d+)W)?(?:(\d+)D)?"
    r"(?:T(?:(\d+)H)?(?:(\d+)M)?(?:(\d+(?:\.\d{1,9})?)?S)?)?",
    re.ASCII,
).fullmatch
_match_timedelta = re.compile(
    r"([-+]?)PT(\d{1,}):([0-5]\d):([0-5]\d(?:\.\d{1,9})?)", re.ASCII
).fullmatch
_match_time = re.compile(
    r"([0-2]\d):([0-5]\d):([0-5]\d)(?:\.(\d{1,9}))?", re.ASCII
).fullmatch


def _check_utc_bounds(dt: _datetime) -> _datetime:
    try:
        dt.astimezone(_UTC)
    except (OverflowError, ValueError):
        raise ValueError("datetime out of range for UTC")
    return dt


def _check_invalid_replace_kwargs(kwargs: Any) -> None:
    if not _no_tzinfo_fold_or_ms(kwargs):
        raise TypeError(
            "tzinfo, fold, or microsecond are not allowed arguments"
        )


def _pop_nanos_kwarg(kwargs: Any, default: int) -> int:
    nanos = kwargs.pop("nanosecond", default)
    if not 0 <= nanos < 1_000_000_000:
        raise ValueError("Invalid nanosecond value")
    elif type(nanos) is not int:
        raise TypeError("nanosecond must be an int")
    return nanos


# Before Python 3.11, fromisoformat() is less capable
if sys.version_info < (3, 11):  # pragma: no cover

    def _parse_rfc2822(s: str) -> _datetime:
        try:
            return parsedate_to_datetime(s)
        except TypeError:
            if isinstance(s, str):
                raise ValueError(f"Invalid RFC2822 string: {s!r}")
            raise

else:
    _parse_rfc2822 = parsedate_to_datetime

UTCDateTime.MIN = UTCDateTime._from_py_unchecked(
    _datetime.min.replace(tzinfo=_UTC),
    0,
)
UTCDateTime.MAX = UTCDateTime._from_py_unchecked(
    _datetime.max.replace(tzinfo=_UTC, microsecond=0),
    999_999_999,
)
NaiveDateTime.MIN = NaiveDateTime._from_py_unchecked(_datetime.min, 0)
NaiveDateTime.MAX = NaiveDateTime._from_py_unchecked(
    _datetime.max.replace(microsecond=0), 999_999_999
)
Disambiguate = Literal["compatible", "earlier", "later", "raise"]
Fold = Literal[0, 1]
_disambiguate_to_fold: Mapping[str, Fold] = {
    "compatible": 0,
    "earlier": 0,
    "later": 1,
    "raise": 0,
}


def _adjust_fold_to_offset(dt: _datetime, offset: _timedelta) -> _datetime:
    if offset != dt.utcoffset():  # offset/zone mismatch: try other fold
        dt = dt.replace(fold=1)
        if dt.utcoffset() != offset:
            raise InvalidOffset()
    return dt


def _as_fold(s: str) -> Fold:
    try:
        return _disambiguate_to_fold[s]
    except KeyError:
        raise ValueError(f"Invalid disambiguate setting: {s!r}")


def years(i: int, /) -> DateDelta:
    """Create a :class:`~DateDelta` with the given number of years.
    ``years(1) == DateDelta(years=1)``
    """
    return DateDelta(years=i)


def months(i: int, /) -> DateDelta:
    """Create a :class:`~DateDelta` with the given number of months.
    ``months(1) == DateDelta(months=1)``
    """
    return DateDelta(months=i)


def weeks(i: int, /) -> DateDelta:
    """Create a :class:`~DateDelta` with the given number of weeks.
    ``weeks(1) == DateDelta(weeks=1)``
    """
    return DateDelta(weeks=i)


def days(i: int, /) -> DateDelta:
    """Create a :class:`~DateDelta` with the given number of days.
    ``days(1) == DateDelta(days=1)``
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


def milliseconds(i: int, /) -> TimeDelta:
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


for name in __all__:
    member = locals()[name]
    if not isinstance(member, int):
        member.__module__ = "whenever"

for _unpkl in (
    _unpkl_date,
    _unpkl_time,
    _unpkl_tdelta,
    _unpkl_dtdelta,
    _unpkl_ddelta,
    _unpkl_utc,
    _unpkl_offset,
    _unpkl_zoned,
    _unpkl_local,
    _unpkl_naive,
):
    _unpkl.__module__ = "whenever"
