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

__version__ = "0.6.8"

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
    "Instant",
    "OffsetDateTime",
    "ZonedDateTime",
    "SystemDateTime",
    "LocalDateTime",
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
    "RepeatedTime",
    "InvalidOffset",
    "ImplicitlyIgnoringDST",
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
_UNSET = object()


class _ImmutableBase:
    __slots__ = ()

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

        def init_subclass_not_allowed(cls, **kwargs):  # pragma: no cover
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

    def at(self, t: Time, /) -> LocalDateTime:
        """Combine a date with a time to create a datetime

        Example
        -------
        >>> d = Date(2021, 1, 2)
        >>> d.at(Time(12, 30))
        LocalDateTime(2021-01-02 12:30:00)

        You can use methods like :meth:`~LocalDateTime.assume_utc`
        or :meth:`~LocalDateTime.assume_tz` to make the result aware.
        """
        return LocalDateTime._from_py_unchecked(
            _datetime.combine(self._py_date, t._py_time), t._nanos
        )

    def py_date(self) -> _date:
        """Convert to a standard library :class:`~datetime.date`"""
        return self._py_date

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

    def format_common_iso(self) -> str:
        """Format as the common ISO 8601 date format.

        Inverse of :meth:`parse_common_iso`.

        Example
        -------
        >>> Date(2021, 1, 2).format_common_iso()
        '2021-01-02'
        """
        return self._py_date.isoformat()

    @classmethod
    def parse_common_iso(cls, s: str, /) -> Date:
        """Create from the common ISO 8601 date format ``YYYY-MM-DD``.
        Does not accept more "exotic" ISO 8601 formats.

        Inverse of :meth:`format_common_iso`

        Example
        -------
        >>> Date.parse_common_iso("2021-01-02")
        Date(2021-01-02)
        """
        if s[5] == "W" or not s.isascii():
            # prevent isoformat from parsing week dates
            raise ValueError(f"Invalid format: {s!r}")
        try:
            return cls._from_py_unchecked(_date.fromisoformat(s))
        except ValueError:
            raise ValueError(f"Invalid format: {s!r}")

    def replace(self, **kwargs: Any) -> Date:
        """Create a new instance with the given fields replaced

        Example
        -------
        >>> d = Date(2021, 1, 2)
        >>> d.replace(day=3)
        Date(2021-01-03)
        """
        return Date._from_py_unchecked(self._py_date.replace(**kwargs))

    def add(
        self, *, years: int = 0, months: int = 0, weeks: int = 0, days: int = 0
    ) -> Date:
        """Add a components to a date.

        See :ref:`the docs on arithmetic <arithmetic>` for more information.

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

    def subtract(
        self, *, years: int = 0, months: int = 0, weeks: int = 0, days: int = 0
    ) -> Date:
        """Subtract a components from a date.

        See :ref:`the docs on arithmetic <arithmetic>` for more information.

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

    def __add__(self, p: DateDelta) -> Date:
        """Add a delta to a date.
        Behaves the same as :meth:`add`
        """
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
        DateDelta(-P9M)
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

    __str__ = format_common_iso

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

    @classmethod
    def _from_py_unchecked(cls, d: _date, /) -> Date:
        self = _object_new(cls)
        self._py_date = d
        return self

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
class Time(_ImmutableBase):
    """Time of day without a date component

    Example
    -------
    >>> t = Time(12, 30, 0)
    Time(12:30:00)

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
        *,
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

    def on(self, d: Date, /) -> LocalDateTime:
        """Combine a time with a date to create a datetime

        Example
        -------
        >>> t = Time(12, 30)
        >>> t.on(Date(2021, 1, 2))
        LocalDateTime(2021-01-02 12:30:00)

        Then, use methods like :meth:`~LocalDateTime.assume_utc`
        or :meth:`~LocalDateTime.assume_tz`
        to make the result aware.
        """
        return LocalDateTime._from_py_unchecked(
            _datetime.combine(d._py_date, self._py_time),
            self._nanos,
        )

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
        if type(t) is _time:
            if t.tzinfo is not None:
                raise ValueError("Time must be naive")
        elif isinstance(t, _time):
            # subclass-safe way to ensure we have exactly a datetime.time
            t = _time(t.hour, t.minute, t.second, t.microsecond)
        else:
            raise TypeError(f"Expected datetime.time, got {type(t)!r}")
        return cls._from_py_unchecked(
            t.replace(microsecond=0), t.microsecond * 1_000
        )

    def format_common_iso(self) -> str:
        """Format as the common ISO 8601 time format.

        Inverse of :meth:`parse_common_iso`.

        Example
        -------
        >>> Time(12, 30, 0).format_common_iso()
        '12:30:00'
        """
        return (
            (self._py_time.isoformat() + f".{self._nanos:09d}").rstrip("0")
            if self._nanos
            else self._py_time.isoformat()
        )

    @classmethod
    def parse_common_iso(cls, s: str, /) -> Time:
        """Create from the common ISO 8601 time format ``HH:MM:SS``.
        Does not accept more "exotic" ISO 8601 formats.

        Inverse of :meth:`format_common_iso`

        Example
        -------
        >>> Time.parse_common_iso("12:30:00")
        Time(12:30:00)
        """
        if (match := _match_time(s)) is None:
            raise ValueError(f"Invalid format: {s!r}")

        hours_str, minutes_str, seconds_str, nanos_str = match.groups()

        hours = int(hours_str)
        minutes = int(minutes_str)
        seconds = int(seconds_str)
        nanos = int(nanos_str.ljust(9, "0")) if nanos_str else 0
        return cls._from_py_unchecked(_time(hours, minutes, seconds), nanos)

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

    @classmethod
    def _from_py_unchecked(cls, t: _time, nanos: int, /) -> Time:
        assert not t.microsecond
        self = _object_new(cls)
        self._py_time = t
        self._nanos = nanos
        return self

    __str__ = format_common_iso

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
    *args, nanos = unpack("<BBBI", data)
    return Time._from_py_unchecked(_time(*args), nanos)


Time.MIDNIGHT = Time()
Time.NOON = Time(12)
Time.MAX = Time(23, 59, 59, nanosecond=999_999_999)


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

    Note
    ----
    A shorter was to instantiate a timedelta is to use the helper functions
    :func:`~whenever.hours`, :func:`~whenever.minutes`, etc.

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
        return self

    def in_days_of_24h(self) -> float:
        """The total size in days (of exactly 24 hours each)

        Note
        ----
        Note that this may not be the same as days on the calendar,
        since some days have 23 or 25 hours due to daylight saving time.
        """
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

    def py_timedelta(self) -> _timedelta:
        """Convert to a :class:`~datetime.timedelta`

        Inverse of :meth:`from_py_timedelta`

        Note
        ----
        Nanoseconds are rounded to the nearest even microsecond.

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

    def format_common_iso(self) -> str:
        """Format as the *popular interpretation* of the ISO 8601 duration format.
        May not strictly adhere to (all versions of) the standard.
        See :ref:`here <iso8601-durations>` for more information.

        Inverse of :meth:`parse_common_iso`.

        Example
        -------
        >>> TimeDelta(hours=1, minutes=30).format_common_iso()
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
    def parse_common_iso(cls, s: str, /) -> TimeDelta:
        """Parse the *popular interpretation* of the ISO 8601 duration format.
        Does not parse all possible ISO 8601 durations.
        See :ref:`here <iso8601-durations>` for more information.

        Inverse of :meth:`format_common_iso`

        Example
        -------
        >>> TimeDelta.parse_common_iso("PT1H30M")
        TimeDelta(01:30:00)

        Note
        ----
        Any duration with a date part is considered invalid.
        ``PT0S`` is valid, but ``P0D`` is not.
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

    __str__ = format_common_iso

    def __repr__(self) -> str:
        hrs, mins, secs, ns = abs(self).in_hrs_mins_secs_nanos()
        return (
            f"TimeDelta({'-'*(self._total_ns < 0)}{hrs:02}:{mins:02}:{secs:02}"
            + f".{ns:0>9}".rstrip("0") * bool(ns)
            + ")"
        )

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
    if (match := _match_next_timedelta_component(s)) is None:
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

    ZERO: ClassVar[DateDelta]
    """A delta of zero"""
    _time_part = TimeDelta.ZERO

    @property
    def _date_part(self) -> DateDelta:
        return self

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

    def format_common_iso(self) -> str:
        """Format as the *popular interpretation* of the ISO 8601 duration format.
        May not strictly adhere to (all versions of) the standard.
        See :ref:`here <iso8601-durations>` for more information.

        Inverse of :meth:`parse_common_iso`.

        The format looks like this:

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
        >>> p.common_iso()
        'P1Y2M3W11D'
        >>> DateDelta().common_iso()
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

    __str__ = format_common_iso

    @classmethod
    def parse_common_iso(cls, s: str, /) -> DateDelta:
        """Parse the *popular interpretation* of the ISO 8601 duration format.
        Does not parse all possible ISO 8601 durations.
        See :ref:`here <iso8601-durations>` for more information.

        Inverse of :meth:`format_common_iso`

        Example
        -------
        >>> DateDelta.parse_common_iso("P1W11D")
        DateDelta(P1W11D)
        >>> DateDelta.parse_common_iso("-P3M")
        DateDelta(-P3M)

        Note
        ----
        Only durations without time component are accepted.
        ``P0D`` is valid, but ``PT0S`` is not.

        Note
        ----
        The number of digits in each component is limited to 8.
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

    def __abs__(self) -> DateDelta:
        """If the contents are negative, return the positive version

        Example
        -------
        >>> p = DateDelta(months=-2, days=-3)
        >>> abs(p)
        DateDelta(P2M3D)
        """
        return DateDelta(months=abs(self._months), days=abs(self._days))

    @no_type_check
    def __reduce__(self):
        return (_unpkl_ddelta, (self._months, self._days))


# A separate unpickling function allows us to make backwards-compatible changes
# to the pickling format in the future
def _unpkl_ddelta(months: int, days: int) -> DateDelta:
    return DateDelta(months=months, days=days)


def _parse_datedelta_component(s: str, exc: Exception) -> tuple[str, int, str]:
    if (match := _match_next_datedelta_component(s)) is None:
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

    def format_common_iso(self) -> str:
        """Format as the *popular interpretation* of the ISO 8601 duration format.
        May not strictly adhere to (all versions of) the standard.
        See :ref:`here <iso8601-durations>` for more information.

        Inverse of :meth:`parse_common_iso`.

        The format is:

        .. code-block:: text

            P(nY)(nM)(nD)T(nH)(nM)(nS)

        Example
        -------
        >>> d = DateTimeDelta(
        ...     weeks=1,
        ...     days=11,
        ...     hours=4,
        ...     milliseconds=12,
        ... )
        >>> d.format_common_iso()
        'P1W11DT4H0.012S'
        """
        sign = (
            self._date_part._months < 0
            or self._date_part._days < 0
            or self._time_part._total_ns < 0
        ) * "-"
        date = abs(self._date_part).format_common_iso()[1:] * bool(
            self._date_part
        )
        time = abs(self._time_part).format_common_iso()[1:] * bool(
            self._time_part
        )
        return sign + "P" + ((date + time) or "0D")

    @classmethod
    def parse_common_iso(cls, s: str, /) -> DateTimeDelta:
        """Parse the *popular interpretation* of the ISO 8601 duration format.
        Does not parse all possible ISO 8601 durations.
        See :ref:`here <iso8601-durations>` for more information.

        Examples:

        .. code-block:: text

           P4D        # 4 days
           PT4H       # 4 hours
           PT3M40.5S  # 3 minutes and 40.5 seconds
           P1W11DT4H  # 1 week, 11 days, and 4 hours
           -PT7H4M    # -7 hours and -4 minutes (-7:04:00)
           +PT7H4M    # 7 hours and 4 minutes (7:04:00)

        Inverse of :meth:`format_common_iso`

        Example
        -------
        >>> DateTimeDelta.parse_common_iso("-P1W11DT4H")
        DateTimeDelta(-P1W11DT4H)
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
        DateTimeDelta(-P2M1W8DT2H30M)
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

    __str__ = format_common_iso

    def __repr__(self) -> str:
        return f"DateTimeDelta({self})"

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
_T = TypeVar("_T")


class _BasicConversions(_ImmutableBase, ABC):
    """Methods for types converting to/from the standard library and ISO8601:

    - :class:`Instant`
    - :class:`LocalDateTime`
    - :class:`ZonedDateTime`
    - :class:`OffsetDateTime`
    - :class:`SystemDateTime`

    (This base class class itself is not for public use.)
    """

    __slots__ = ("_py_dt", "_nanos")
    _py_dt: _datetime
    _nanos: int

    @classmethod
    @abstractmethod
    def from_py_datetime(cls: type[_T], d: _datetime, /) -> _T:
        """Create an instance from a :class:`~datetime.datetime` object.
        Inverse of :meth:`~_BasicConversions.py_datetime`.

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
        Nanoseconds are truncated to microseconds.
        """
        return self._py_dt.replace(microsecond=self._nanos // 1_000)

    @abstractmethod
    def format_common_iso(self) -> str:
        """Format as common ISO string representation. Each
        subclass has a different format.

        See :ref:`here <iso8601>` for more information.
        """

    @classmethod
    @abstractmethod
    def parse_common_iso(cls: type[_T], s: str, /) -> _T:
        """Create an instance from common ISO 8601 representation,
        which is different for each subclass.

        See :ref:`here <iso8601>` for more information.
        """

    def __str__(self) -> str:
        """Same as :meth:`format_common_iso`"""
        return self.format_common_iso()

    @classmethod
    def _from_py_unchecked(cls: type[_T], d: _datetime, nanos: int, /) -> _T:
        assert not d.microsecond
        assert 0 <= nanos < 1_000_000_000
        self = _object_new(cls)
        self._py_dt = d  # type: ignore[attr-defined]
        self._nanos = nanos  # type: ignore[attr-defined]
        return self


class _KnowsLocal(_BasicConversions, ABC):
    """Methods for types that know a local date and time:

    - :class:`LocalDateTime`
    - :class:`ZonedDateTime`
    - :class:`OffsetDateTime`
    - :class:`SystemDateTime`

    (The class itself is not for public use.)
    """

    __slots__ = ()

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
        >>> d = Instant.from_utc(2021, 1, 2, 3, 4, 5)
        >>> d.date()
        Date(2021-01-02)

        To perform the inverse, use :meth:`Date.at` and a method
        like :meth:`~LocalDateTime.assume_utc` or
        :meth:`~LocalDateTime.assume_tz`:

        >>> date.at(time).assume_tz("Europe/London", disambiguate="compatible")
        """
        return Date._from_py_unchecked(self._py_dt.date())

    def time(self) -> Time:
        """The time-of-day part of the datetime

        Example
        -------
        >>> d = ZonedDateTime(2021, 1, 2, 3, 4, 5, tz="Europe/Paris")
        ZonedDateTime(2021-01-02T03:04:05+01:00[Europe/Paris])
        >>> d.time()
        Time(03:04:05)

        To perform the inverse, use :meth:`Time.on` and a method
        like :meth:`~LocalDateTime.assume_utc` or
        :meth:`~LocalDateTime.assume_tz`:

        >>> time.on(date).assume_tz("Europe/Paris", disambiguate="compatible")
        """
        return Time._from_py_unchecked(self._py_dt.time(), self._nanos)

    # We document these methods as abtract,
    # but they are actually implemented slightly different per subclass
    if not TYPE_CHECKING:  # pragma: no cover

        @abstractmethod
        def replace(self: _T, /, **kwargs: Any) -> _T:
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
            For system and zoned datetimes,
            The ``disambiguate=`` keyword argument is **required** to
            resolve ambiguities.

            Example
            -------
            >>> d = LocalDateTime(2020, 8, 15, 23, 12)
            >>> d.replace(year=2021)
            LocalDateTime(2021-08-15 23:12:00)
            >>>
            >>> z = ZonedDateTime(2020, 8, 15, 23, 12, tz="Europe/London")
            >>> z.replace(year=2021, disambiguate="raise")
            ZonedDateTime(2021-08-15T23:12:00+01:00)
            """

        def replace_date(self: _T, date: Date, /, **kwargs) -> _T:
            """Create a new instance with the date replaced

            Example
            -------
            >>> d = LocalDateTime(2020, 8, 15, hour=4)
            >>> d.replace_date(Date(2021, 1, 1))
            LocalDateTime(2021-01-01T04:00:00)
            >>> zdt = ZonedDateTime.now("Europe/London")
            >>> zdt.replace_date(Date(2021, 1, 1), disambiguate="raise"))
            ZonedDateTime(2021-01-01T13:00:00.23439+00:00[Europe/London])

            Warning
            -------
            The same exceptions as the constructor may be raised.
            For system and zoned datetimes,
            you will need to pass ``disambiguate=`` to resolve ambiguities.
            """

        def replace_time(self: _T, time: Time, /, **kwargs) -> _T:
            """Create a new instance with the time replaced

            Example
            -------
            >>> d = LocalDateTime(2020, 8, 15, hour=4)
            >>> d.replace_time(Time(12, 30))
            LocalDateTime(2020-08-15T12:30:00)
            >>> zdt = ZonedDateTime.now("Europe/London")
            >>> zdt.replace_time(Time(12, 30), disambiguate="raise")
            ZonedDateTime(2024-06-15T12:30:00+01:00[Europe/London])

            Warning
            -------
            The same exceptions as the constructor may be raised.
            For system and zoned datetimes,
            you will need to pass ``disambiguate=`` to resolve ambiguities.
            """

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

            See :ref:`the docs on arithmetic <arithmetic>` for more information.
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
            """Subtract date and time units to this datetime.

            See :ref:`the docs on arithmetic <arithmetic>` for more information.
            """


class _KnowsInstant(_BasicConversions):
    """Methods for types that represent a specific moment in time.

    Implemented by:

    - :class:`Instant`
    - :class:`ZonedDateTime`
    - :class:`OffsetDateTime`
    - :class:`SystemDateTime`

    (This base class class itself is not for public use.)
    """

    __slots__ = ()

    # These methods aren't strictly abstract (they don't follow LSP),
    # but we do document them here.
    if not TYPE_CHECKING:  # pragma: no cover

        @classmethod
        def now(cls: type[_T], **kwargs) -> _T:
            """Create an instance from the current time.

            This method on :class:`~ZonedDateTime` and :class:`~OffsetDateTime` requires
            a ``tz=`` and ``offset=`` kwarg, respectively.

            Example
            -------

            >>> Instant.now()
            Instant(2021-08-15T22:12:00.49821Z)
            >>> ZonedDateTime.now(tz="Europe/London")
            ZonedDateTime(2021-08-15 23:12:00.50332+01:00[Europe/London])

            """

    def timestamp(self) -> int:
        """The UNIX timestamp for this datetime. Inverse of :meth:`from_timestamp`.

        Note
        ----
        In contrast to the standard library, this method always returns an integer,
        not a float. This is because floating point timestamps are not precise
        enough to represent all instants to nanosecond precision.
        This decision is consistent with other modern date-time libraries.

        Example
        -------
        >>> Instant.from_utc(1970, 1, 1).timestamp()
        0
        >>> ts = 1_123_000_000
        >>> Instant.from_timestamp(ts).timestamp() == ts
        True
        """
        return int(self._py_dt.timestamp())

    def timestamp_millis(self) -> int:
        """Like :meth:`timestamp`, but with millisecond precision."""
        return int(self._py_dt.timestamp()) * 1_000 + self._nanos // 1_000_000

    def timestamp_nanos(self) -> int:
        """Like :meth:`timestamp`, but with nanosecond precision."""
        return int(self._py_dt.timestamp()) * 1_000_000_000 + self._nanos

    if not TYPE_CHECKING:

        @classmethod
        def from_timestamp(cls: type[_T], i: int | float, /, **kwargs) -> _T:
            """Create an instance from a UNIX timestamp.
            The inverse of :meth:`~_KnowsInstant.timestamp`.

            :class:`~ZonedDateTime` and :class:`~OffsetDateTime` require
            a ``tz=`` and ``offset=`` kwarg, respectively.

            Note
            ----
            ``from_timestamp()`` also accepts floats, in order to ease
            migration from the standard library.
            Note however that ``timestamp()`` only returns integers.
            The reason is that floating point timestamps are not precise
            enough to represent all instants to nanosecond precision.

            Example
            -------
            >>> Instant.from_timestamp(0)
            Instant(1970-01-01T00:00:00Z)
            >>> ZonedDateTime.from_timestamp(1_123_000_000, tz="America/New_York")
            ZonedDateTime(2005-08-02 12:26:40-04:00[America/New_York])

            """

        @classmethod
        def from_timestamp_millis(cls: type[_T], i: int, /, **kwargs) -> _T:
            """Like :meth:`from_timestamp`, but for milliseconds."""

        @classmethod
        def from_timestamp_nanos(cls: type[_T], i: int, /, **kwargs) -> _T:
            """Like :meth:`from_timestamp`, but for nanoseconds."""

    @overload
    def to_fixed_offset(self, /) -> OffsetDateTime: ...

    @overload
    def to_fixed_offset(
        self, offset: int | TimeDelta, /
    ) -> OffsetDateTime: ...

    def to_fixed_offset(
        self, offset: int | TimeDelta | None = None, /
    ) -> OffsetDateTime:
        """Convert to an OffsetDateTime that represents the same moment in time.

        If not offset is given, the offset is taken from the original datetime.
        """
        return OffsetDateTime._from_py_unchecked(
            self._py_dt.astimezone(
                # mypy doesn't know that offset is never None
                _timezone(self._py_dt.utcoffset())  # type: ignore[arg-type]
                if offset is None
                else _load_offset(offset)
            ),
            self._nanos,
        )

    def to_tz(self, tz: str, /) -> ZonedDateTime:
        """Convert to a ZonedDateTime that represents the same moment in time.

        Raises
        ------
        ~zoneinfo.ZoneInfoNotFoundError
            If the timezone ID is not found in the IANA database.
        """
        return ZonedDateTime._from_py_unchecked(
            self._py_dt.astimezone(ZoneInfo(tz)), self._nanos
        )

    def to_system_tz(self) -> SystemDateTime:
        """Convert to a SystemDateTime that represents the same moment in time."""
        return SystemDateTime._from_py_unchecked(
            self._py_dt.astimezone(), self._nanos
        )

    def exact_eq(self: _T, other: _T, /) -> bool:
        """Compare objects by their values
        (instead of whether they represent the same instant).
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
        True  # equivalent instants
        >>> a.exact_eq(b)
        False  # different values (hour and offset)
        """
        return (
            self._py_dt,  # type: ignore[attr-defined]
            self._py_dt.utcoffset(),  # type: ignore[attr-defined]
            self._nanos,  # type: ignore[attr-defined]
            type(self._py_dt.tzinfo),  # type: ignore[attr-defined]
        ) == (
            other._py_dt,  # type: ignore[attr-defined]
            other._py_dt.utcoffset(),  # type: ignore[attr-defined]
            other._nanos,  # type: ignore[attr-defined]
            type(other._py_dt.tzinfo),  # type: ignore[attr-defined]
        )

    def difference(
        self,
        other: Instant | OffsetDateTime | ZonedDateTime | SystemDateTime,
        /,
    ) -> TimeDelta:
        """Calculate the difference between two instants in time.

        Equivalent to :meth:`__sub__`.

        See :ref:`the docs on arithmetic <arithmetic>` for more information.
        """
        return self - other  # type: ignore[operator, no-any-return]

    def __eq__(self, other: object) -> bool:
        """Check if two datetimes represent at the same moment in time

        ``a == b`` is equivalent to ``a.instant() == b.instant()``

        Note
        ----
        If you want to exactly compare the values on their values
        instead, use :meth:`exact_eq`.

        Example
        -------
        >>> Instant.from_utc(2020, 8, 15, hour=23) == Instant.from_utc(2020, 8, 15, hour=23)
        True
        >>> OffsetDateTime(2020, 8, 15, hour=23, offset=1) == (
        ...     ZonedDateTime(2020, 8, 15, hour=18, tz="America/New_York")
        ... )
        True
        """
        if not isinstance(other, _KnowsInstant):
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

    def __lt__(self, other: _KnowsInstant) -> bool:
        """Compare two datetimes by when they occur in time

        ``a < b`` is equivalent to ``a.instant() < b.instant()``

        Example
        -------
        >>> OffsetDateTime(2020, 8, 15, hour=23, offset=8) < (
        ...     ZoneDateTime(2020, 8, 15, hour=20, tz="Europe/Amsterdam")
        ... )
        True
        """
        if not isinstance(other, _KnowsInstant):
            return NotImplemented
        return (self._py_dt.astimezone(_UTC), self._nanos) < (
            other._py_dt.astimezone(_UTC),
            other._nanos,
        )

    def __le__(self, other: _KnowsInstant) -> bool:
        """Compare two datetimes by when they occur in time

        ``a <= b`` is equivalent to ``a.instant() <= b.instant()``

        Example
        -------
        >>> OffsetDateTime(2020, 8, 15, hour=23, offset=8) <= (
        ...     ZoneDateTime(2020, 8, 15, hour=20, tz="Europe/Amsterdam")
        ... )
        True
        """
        if not isinstance(other, _KnowsInstant):
            return NotImplemented
        return (self._py_dt.astimezone(_UTC), self._nanos) <= (
            other._py_dt.astimezone(_UTC),
            other._nanos,
        )

    def __gt__(self, other: _KnowsInstant) -> bool:
        """Compare two datetimes by when they occur in time

        ``a > b`` is equivalent to ``a.instant() > b.instant()``

        Example
        -------
        >>> OffsetDateTime(2020, 8, 15, hour=19, offset=-8) > (
        ...     ZoneDateTime(2020, 8, 15, hour=20, tz="Europe/Amsterdam")
        ... )
        True
        """
        if not isinstance(other, _KnowsInstant):
            return NotImplemented
        return (self._py_dt.astimezone(_UTC), self._nanos) > (
            other._py_dt.astimezone(_UTC),
            other._nanos,
        )

    def __ge__(self, other: _KnowsInstant) -> bool:
        """Compare two datetimes by when they occur in time

        ``a >= b`` is equivalent to ``a.instant() >= b.instant()``

        Example
        -------
        >>> OffsetDateTime(2020, 8, 15, hour=19, offset=-8) >= (
        ...     ZoneDateTime(2020, 8, 15, hour=20, tz="Europe/Amsterdam")
        ... )
        True
        """
        if not isinstance(other, _KnowsInstant):
            return NotImplemented
        return (self._py_dt.astimezone(_UTC), self._nanos) >= (
            other._py_dt.astimezone(_UTC),
            other._nanos,
        )

    # Mypy doesn't like overloaded overrides, but we'd like to document
    # this 'abstract' behaviour anyway
    if not TYPE_CHECKING:  # pragma: no branch

        @abstractmethod
        def __sub__(self, other: _KnowsInstant) -> TimeDelta:
            """Calculate the duration between two datetimes

            ``a - b`` is equivalent to ``a.instant() - b.instant()``

            Equivalent to :meth:`difference`.

            See :ref:`the docs on arithmetic <arithmetic>` for more information.

            Example
            -------
            >>> d = Instant.from_utc(2020, 8, 15, hour=23)
            >>> d - ZonedDateTime(2020, 8, 15, hour=20, tz="Europe/Amsterdam")
            TimeDelta(05:00:00)
            """
            if isinstance(other, _KnowsInstant):
                py_delta = self._py_dt.astimezone(_UTC) - other._py_dt
                return TimeDelta(
                    seconds=py_delta.days * 86_400 + py_delta.seconds,
                    nanoseconds=self._nanos - other._nanos,
                )
            return NotImplemented


class _KnowsInstantAndLocal(_KnowsLocal, _KnowsInstant):
    """Common behavior for all types that know both a local time and an instant:

    - :class:`ZonedDateTime`
    - :class:`OffsetDateTime`
    - :class:`SystemDateTime`

    (The class itself it not for public use.)
    """

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

    def instant(self) -> Instant:
        """Get the underlying instant

        Example
        -------

        >>> d = ZonedDateTime(2020, 8, 15, hour=23, tz="Europe/Amsterdam")
        >>> d.instant()
        Instant(2020-08-15 21:00:00Z)
        """
        return Instant._from_py_unchecked(
            self._py_dt.astimezone(_UTC), self._nanos
        )

    def local(self) -> LocalDateTime:
        """Get the underlying local date and time

        As an inverse, :class:`LocalDateTime` has methods
        :meth:`~LocalDateTime.assume_utc`, :meth:`~LocalDateTime.assume_fixed_offset`
        , :meth:`~LocalDateTime.assume_tz`, and :meth:`~LocalDateTime.assume_system_tz`
        which may require additional arguments.
        """
        return LocalDateTime._from_py_unchecked(
            self._py_dt.replace(tzinfo=None),
            self._nanos,
        )


@final
class Instant(_KnowsInstant):
    """Represents a moment in time with nanosecond precision.

    This class is great for representing a specific point in time independent
    of location. It maps 1:1 to UTC or a UNIX timestamp.

    Example
    -------
    >>> from whenever import Instant
    >>> py311_release_livestream = Instant.from_utc(2022, 10, 24, hour=17)
    Instant(2022-10-24 17:00:00Z)
    >>> py311_release_livestream.add(hours=3).timestamp()
    1666641600

    Note
    ----
    The corresponding :class:`~datetime.datetime` object is always
    timezone-aware and has a fixed :attr:`~datetime.UTC` tzinfo.
    """

    __slots__ = ()

    def __init__(self) -> None:
        raise TypeError("Instant instances cannot be created")

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
        if nanosecond < 0 or nanosecond >= 1_000_000_000:
            raise ValueError(f"nanosecond out of range: {nanosecond}")
        return cls._from_py_unchecked(
            _datetime(year, month, day, hour, minute, second, 0, _UTC),
            nanosecond,
        )

    offset = TimeDelta.ZERO

    MIN: ClassVar[Instant]
    MAX: ClassVar[Instant]

    @classmethod
    def now(cls) -> Instant:
        secs, nanos = divmod(time_ns(), 1_000_000_000)
        return cls._from_py_unchecked(_fromtimestamp(secs, _UTC), nanos)

    @classmethod
    def from_timestamp(cls, i: int | float, /) -> Instant:
        secs, fract = divmod(i, 1)
        return cls._from_py_unchecked(
            _fromtimestamp(secs, _UTC), int(fract * 1_000_000_000)
        )

    @classmethod
    def from_timestamp_millis(cls, i: int, /) -> Instant:
        if not isinstance(i, int):
            raise TypeError("method requires an integer")
        secs, millis = divmod(i, 1_000)
        return cls._from_py_unchecked(
            _fromtimestamp(secs, _UTC), millis * 1_000_000
        )

    @classmethod
    def from_timestamp_nanos(cls, i: int, /) -> Instant:
        if not isinstance(i, int):
            raise TypeError("method requires an integer")
        secs, nanos = divmod(i, 1_000_000_000)
        return cls._from_py_unchecked(_fromtimestamp(secs, _UTC), nanos)

    @classmethod
    def from_py_datetime(cls, d: _datetime, /) -> Instant:
        if d.tzinfo is not _UTC:
            raise ValueError(
                "Can only create Instant from UTC datetime, "
                f"got datetime with tzinfo={d.tzinfo!r}"
            )
        return cls._from_py_unchecked(
            _strip_subclasses(d.replace(microsecond=0)), d.microsecond * 1_000
        )

    def format_common_iso(self) -> str:
        return (
            self._py_dt.isoformat()[:-6]
            + bool(self._nanos) * f".{self._nanos:09d}".rstrip("0")
            + "Z"
        )

    @classmethod
    def parse_common_iso(cls, s: str, /) -> Instant:
        """Parse a UTC datetime in common ISO 8601 format.

        Inverse of :meth:`~_DateTime.format_common_iso`

        Example
        -------
        >>> Instant.parse_common_iso("2020-08-15T23:12:00Z")
        Instant(2020-08-15 23:12:00Z)
        >>>
        >>> # also valid:
        >>> Instant.parse_common_iso("2020-08-15T23:12:00+00:00")
        >>> Instant.parse_common_iso("2020-08-15T23:12:00.34Z")
        >>>
        >>> # not valid
        >>> Instant.parse_common_iso("2020-08-15T23:12:00+02:00")
        >>> Instant.parse_common_iso("2020-08-15 23:12:00Z")
        >>> Instant.parse_common_iso("2020-08-15T23:12:00-00:00")

        Warning
        -------
        Nonzero offsets will not be implicitly converted to UTC.
        Use :meth:`OffsetDateTime.parse_common_iso` if you'd like to
        parse an ISO 8601 string with a nonzero offset.
        """
        if (
            (match := _match_utc_rfc3339(s)) is None
            or s[10] != "T"
            or s.endswith(("z", "-00:00"))
        ):
            raise ValueError(f"Invalid format: {s!r}")
        nanos = int(match[7].ljust(9, "0")) if match[7] else 0
        return cls._from_py_unchecked(
            _fromisoformat(s[:19]).replace(tzinfo=_UTC), nanos
        )

    def format_rfc2822(self) -> str:
        """Format as an RFC 2822 string.

        The inverse of :meth:`parse_rfc2822`.

        Example
        -------
        >>> Instant.from_utc(2020, 8, 15, hour=23, minute=12).format_rfc2822()
        "Sat, 15 Aug 2020 23:12:00 GMT"
        """
        return format_datetime(self._py_dt, usegmt=True)

    @classmethod
    def parse_rfc2822(cls, s: str, /) -> Instant:
        """Parse a UTC datetime in RFC 2822 format.

        The inverse of :meth:`format_rfc2822`.

        Example
        -------
        >>> Instant.parse_rfc2822("Sat, 15 Aug 2020 23:12:00 GMT")
        Instant(2020-08-15 23:12:00Z)

        >>> # also valid:
        >>> Instant.parse_rfc2822("Sat, 15 Aug 2020 23:12:00 +0000")
        >>> Instant.parse_rfc2822("Sat, 15 Aug 2020 23:12:00 -0000")
        >>> Instant.parse_rfc2822("Sat, 15 Aug 2020 23:12:00 UT")
        >>> Instant.parse_rfc2822("Sat, 15 Aug 2020 23:12:00 UTC")

        >>> # Error: includes offset. Use OffsetDateTime.parse_rfc2822() instead
        >>> Instant.parse_rfc2822("Sat, 15 Aug 2020 23:12:00 +0200")

        Warning
        -------
        * Nonzero offsets will not be implicitly converted to UTC.
          Use :meth:`OffsetDateTime.parse_rfc2822` if you'd like to
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

    def format_rfc3339(self) -> str:
        """Format as an RFC 3339 string

        Inverse of :meth:`parse_rfc3339`.

        Example
        -------
        >>> Instant.from_utc(2020, 8, 15, hour=23, minute=12).format_rfc3339()
        "2020-08-15T23:12:00Z"
        """
        return (
            self._py_dt.isoformat(sep=" ")[:-6]
            + bool(self._nanos) * f".{self._nanos:09d}".rstrip("0")
            + "Z"
        )

    @classmethod
    def parse_rfc3339(cls, s: str, /) -> Instant:
        """Parse a UTC datetime in RFC 3339 format.

        Inverse of :meth:`format_rfc3339`.

        Example
        -------
        >>> Instant.parse_rfc3339("2020-08-15T23:12:00Z")
        Instant(2020-08-15 23:12:00Z)
        >>>
        >>> # also valid:
        >>> Instant.parse_rfc3339("2020-08-15T23:12:00+00:00")
        >>> Instant.parse_rfc3339("2020-08-15_23:12:00.34Z")
        >>> Instant.parse_rfc3339("2020-08-15t23:12:00z")
        >>>
        >>> # not valid (nonzero offset):
        >>> Instant.parse_rfc3339("2020-08-15T23:12:00+02:00")

        Warning
        -------
        Nonzero offsets will not be implicitly converted to UTC.
        Use :meth:`OffsetDateTime.parse_rfc3339` if you'd like to
        parse an RFC 3339 string with a nonzero offset.
        """
        if (match := _match_utc_rfc3339(s)) is None:
            raise ValueError(f"Invalid RFC 3339 format: {s!r}")
        year, month, day, hour, minute, second = map(int, match.groups()[:6])
        nanos = int(match.group(7).ljust(9, "0")) if match.group(7) else 0
        return cls._from_py_unchecked(
            _datetime(year, month, day, hour, minute, second, 0, _UTC),
            nanos,
        )

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

        See :ref:`the docs on arithmetic <arithmetic>` for more information.
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

        See :ref:`the docs on arithmetic <arithmetic>` for more information.
        """
        return self.add(
            hours=-hours,
            minutes=-minutes,
            seconds=-seconds,
            milliseconds=-milliseconds,
            microseconds=-microseconds,
            nanoseconds=-nanoseconds,
        )

    def __add__(self, delta: TimeDelta) -> Instant:
        """Add a time amount to this datetime.

        See :ref:`the docs on arithmetic <arithmetic>` for more information.
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
    def __sub__(self, other: _KnowsInstant) -> TimeDelta: ...

    @overload
    def __sub__(self, other: TimeDelta) -> Instant: ...

    def __sub__(self, other: TimeDelta | _KnowsInstant) -> Instant | TimeDelta:
        """Subtract another exact time or timedelta

        Subtraction of deltas happens in the same way as :meth:`subtract`.
        Subtraction of instants happens the same way as :meth:`~_KnowsInstant.difference`.

        Example
        -------
        >>> d = Instant.from_utc(2020, 8, 15, hour=23, minute=12)
        >>> d - hours(24) - seconds(5)
        Instant(2020-08-14 23:11:55Z)
        >>> d - Instant.from_utc(2020, 8, 14)
        TimeDelta(47:12:00)
        """
        if isinstance(other, _KnowsInstant):
            return super().__sub__(other)  # type: ignore[misc, no-any-return]
        elif isinstance(other, TimeDelta):
            return self + -other
        return NotImplemented

    def __hash__(self) -> int:
        return hash((self._py_dt, self._nanos))

    def __repr__(self) -> str:
        return f"Instant({str(self).replace('T', ' ')})"

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
def _unpkl_utc(data: bytes) -> Instant:
    secs, nanos = unpack("<qL", data)
    return Instant._from_py_unchecked(
        _fromtimestamp(secs - _UNIX_INSTANT, _UTC), nanos
    )


@final
class OffsetDateTime(_KnowsInstantAndLocal):
    """A datetime with a fixed UTC offset.
    Useful for representing the local time at a specific location.

    Example
    -------
    >>> # 9 AM in Salt Lake City, with the UTC offset at the time
    >>> pycon23_start = OffsetDateTime(2023, 4, 21, hour=9, offset=-6)
    OffsetDateTime(2023-04-21 09:00:00-06:00)

    Warning
    -------
    This class does *not* account for daylight saving time.
    If you need to adjust an offset datetime and account for DST,
    convert to a :class:`~ZonedDateTime`.

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

    @classmethod
    def now(
        cls, offset: int | TimeDelta, /, *, ignore_dst: bool = False
    ) -> OffsetDateTime:
        if ignore_dst is not True:
            raise ImplicitlyIgnoringDST(
                "Getting the current time with a fixed offset implicitly ignores DST "
                "and other timezone changes. Instead, use `Instant.now()` or "
                "`ZonedDateTime.now(<tz name>)` if you know the timezone. "
                "Or, if you want to ignore DST and accept potentially incorrect offsets, "
                "pass `ignore_dst=True` to this method."
            )
        secs, nanos = divmod(time_ns(), 1_000_000_000)
        return cls._from_py_unchecked(
            _fromtimestamp(secs, _load_offset(offset)), nanos
        )

    def format_common_iso(self) -> str:
        iso_without_fracs = self._py_dt.isoformat()
        return (
            iso_without_fracs[:19]
            + bool(self._nanos) * f".{self._nanos:09d}".rstrip("0")
            + iso_without_fracs[19:]
        )

    @classmethod
    def parse_common_iso(cls, s: str, /) -> OffsetDateTime:
        """Parse a *popular version* of the ISO 8601 datetime format.

        Inverse of :meth:`~_DateTime.format_common_iso`

        Example
        -------
        >>> OffsetDateTime.parse_common_iso("2020-08-15T23:12:00+02:00")
        OffsetDateTime(2020-08-15 23:12:00+02:00)
        >>> # also valid:
        >>> OffsetDateTime.parse_common_iso("2020-08-15T23:12:00Z")
        """
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
        cls, i: int, /, *, offset: int | TimeDelta, ignore_dst: bool = False
    ) -> OffsetDateTime:
        if ignore_dst is not True:
            raise _EXC_TIMESTAMP_DST
        secs, fract = divmod(i, 1)
        return cls._from_py_unchecked(
            _fromtimestamp(secs, _load_offset(offset)),
            int(fract * 1_000_000_000),
        )

    @classmethod
    def from_timestamp_millis(
        cls, i: int, /, *, offset: int | TimeDelta, ignore_dst: bool = False
    ) -> OffsetDateTime:
        if ignore_dst is not True:
            raise _EXC_TIMESTAMP_DST
        if not isinstance(i, int):
            raise TypeError("method requires an integer")
        secs, millis = divmod(i, 1_000)
        return cls._from_py_unchecked(
            _fromtimestamp(secs, _load_offset(offset)), millis * 1_000_000
        )

    @classmethod
    def from_timestamp_nanos(
        cls, i: int, /, *, offset: int | TimeDelta, ignore_dst: bool = False
    ) -> OffsetDateTime:
        if ignore_dst is not True:
            raise _EXC_TIMESTAMP_DST
        if not isinstance(i, int):
            raise TypeError("method requires an integer")
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
            _check_utc_bounds(_strip_subclasses(d.replace(microsecond=0))),
            d.microsecond * 1_000,
        )

    def replace(
        self, /, ignore_dst: bool = False, **kwargs: Any
    ) -> OffsetDateTime:
        _check_invalid_replace_kwargs(kwargs)
        if ignore_dst is not True:
            raise _EXC_ADJUST_OFFSET_DATETIME
        try:
            kwargs["tzinfo"] = _load_offset(kwargs.pop("offset"))
        except KeyError:
            pass
        nanos = _pop_nanos_kwarg(kwargs, self._nanos)
        return self._from_py_unchecked(
            _check_utc_bounds(self._py_dt.replace(**kwargs)), nanos
        )

    def replace_date(
        self, date: Date, /, *, ignore_dst: bool = False
    ) -> OffsetDateTime:
        if ignore_dst is not True:
            raise _EXC_ADJUST_OFFSET_DATETIME
        return self._from_py_unchecked(
            _check_utc_bounds(
                _datetime.combine(date._py_date, self._py_dt.timetz())
            ),
            self._nanos,
        )

    def replace_time(
        self, time: Time, /, *, ignore_dst: bool = False
    ) -> OffsetDateTime:
        if ignore_dst is not True:
            raise _EXC_ADJUST_OFFSET_DATETIME
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

    def __sub__(self, other: _KnowsInstant) -> TimeDelta:
        if isinstance(other, (TimeDelta, DateDelta, DateTimeDelta)):
            raise _EXC_ADJUST_OFFSET_DATETIME
        return super().__sub__(other)  # type: ignore[misc, no-any-return]

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
        return cls._from_py_unchecked(
            _check_utc_bounds(parsed.replace(microsecond=0)),
            parsed.microsecond * 1_000,
        )

    def format_rfc2822(self) -> str:
        """Format as an RFC 2822 string.

        Inverse of :meth:`parse_rfc2822`.

        Example
        -------
        >>> OffsetDateTime(2020, 8, 15, 23, 12, offset=hours(2)).format_rfc2822()
        "Sat, 15 Aug 2020 23:12:00 +0200"
        """
        return format_datetime(self._py_dt)

    @classmethod
    def parse_rfc2822(cls, s: str, /) -> OffsetDateTime:
        """Parse an offset datetime in RFC 2822 format.

        Inverse of :meth:`format_rfc2822`.

        Example
        -------
        >>> OffsetDateTime.parse_rfc2822("Sat, 15 Aug 2020 23:12:00 +0200")
        OffsetDateTime(2020-08-15 23:12:00+02:00)
        >>> # also valid:
        >>> OffsetDateTime.parse_rfc2822("Sat, 15 Aug 2020 23:12:00 UT")
        >>> OffsetDateTime.parse_rfc2822("Sat, 15 Aug 2020 23:12:00 GMT")
        >>> OffsetDateTime.parse_rfc2822("Sat, 15 Aug 2020 23:12:00 MST")

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

    def format_rfc3339(self) -> str:
        """Format as an RFC 3339 string

        Inverse of :meth:`parse_rfc3339`.

        Example
        -------
        >>> OffsetDateTime(2020, 8, 15, hour=23, minute=12, offset=hours(4)).format_rfc3339()
        "2020-08-15T23:12:00+04:00"
        """
        py_isofmt = self._py_dt.isoformat(" ")
        return (
            py_isofmt[:19]  # without the offset
            + bool(self._nanos) * f".{self._nanos:09d}".rstrip("0")
            + py_isofmt[19:25]  # limit offset to minutes
        )

    @classmethod
    def parse_rfc3339(cls, s: str, /) -> OffsetDateTime:
        """Parse a UTC datetime in RFC 3339 format.

        Inverse of :meth:`format_rfc3339`.

        Example
        -------
        >>> OffsetDateTime.parse_rfc3339("2020-08-15T23:12:00+02:00")
        OffsetDateTime(2020-08-15 23:12:00+02:00)
        >>> # also valid:
        >>> OffsetDateTime.parse_rfc3339("2020-08-15T23:12:00Z")
        >>> OffsetDateTime.parse_rfc3339("2020-08-15_23:12:00.23-12:00")
        >>> OffsetDateTime.parse_rfc3339("2020-08-15t23:12:00z")
        """
        if (match := _match_rfc3339(s)) is None:
            raise ValueError(f"Invalid RFC 3339 format: {s!r}")
        nanos = int(match[7].ljust(9, "0")) if match[7] else 0
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

    @no_type_check
    def add(self, *args, **kwargs) -> OffsetDateTime:
        return self._shift(1, *args, **kwargs)

    @no_type_check
    def subtract(self, *args, **kwargs) -> OffsetDateTime:
        return self._shift(-1, *args, **kwargs)

    @no_type_check
    def _shift(
        self,
        sign: int,
        arg: Delta | _UNSET = _UNSET,
        /,
        *,
        ignore_dst: bool = False,
        **kwargs,
    ) -> OffsetDateTime:
        if ignore_dst is not True:
            raise _EXC_ADJUST_OFFSET_DATETIME
        elif kwargs:
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

        py_dt_with_new_date = self.replace_date(
            self.date()
            ._add_months(sign * (years * 12 + months))
            ._add_days(sign * (weeks * 7 + days)),
            ignore_dst=True,
        )._py_dt

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
            (py_dt_with_new_date + _timedelta(seconds=delta_secs)),
            nanos,
        )

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
    *args, nanos, offset_secs = unpack("<HBBBBBIl", data)
    args += (0, _timezone(_timedelta(seconds=offset_secs)))
    return OffsetDateTime._from_py_unchecked(_datetime(*args), nanos)


@final
class ZonedDateTime(_KnowsInstantAndLocal):
    """A datetime associated with a IANA timezone ID.
    Useful for representing the local time bound to a specific location.

    Example
    -------
    >>> changing_the_guard = ZonedDateTime(2024, 12, 8, hour=11, tz="Europe/London")
    >>> # Explicitly resolve ambiguities when clocks are set backwards.
    >>> night_shift = ZonedDateTime(2023, 10, 29, 1, 15, tz="Europe/London", disambiguate="later")


    Attention
    ---------
    To use this type properly, read more about :ref:`ambiguity <ambiguity>`.
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
        tz: str,
        disambiguate: Disambiguate = "raise",
    ) -> None:
        self._py_dt = _resolve_ambiguity(
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
    def now(cls, tz: str, /) -> ZonedDateTime:
        secs, nanos = divmod(time_ns(), 1_000_000_000)
        return cls._from_py_unchecked(
            _fromtimestamp(secs, ZoneInfo(tz)), nanos
        )

    def format_common_iso(self) -> str:
        py_isofmt = self._py_dt.isoformat()
        return (
            py_isofmt[:19]  # without the offset
            + bool(self._nanos) * f".{self._nanos:09d}".rstrip("0")
            + py_isofmt[19:]
            + f"[{self._py_dt.tzinfo.key}]"  # type: ignore[union-attr]
        )

    @classmethod
    def parse_common_iso(cls, s: str, /) -> ZonedDateTime:
        """Parse from the common ISO 8601 format.

        Inverse of :meth:`~_DateTime.format_common_iso`.

        Example
        -------

        >>> ZonedDateTime.parse_common_iso("2020-08-15T23:12:00+01:00[Europe/London]")
        ZonedDateTime(2020-08-15 23:12:00+01:00[Europe/London])
        """
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
        secs, fract = divmod(i, 1)
        return cls._from_py_unchecked(
            _fromtimestamp(secs, ZoneInfo(tz)), int(fract * 1_000_000_000)
        )

    @classmethod
    def from_timestamp_millis(cls, i: int, /, *, tz: str) -> ZonedDateTime:
        if not isinstance(i, int):
            raise TypeError("method requires an integer")
        secs, millis = divmod(i, 1_000)
        return cls._from_py_unchecked(
            _fromtimestamp(secs, ZoneInfo(tz)), millis * 1_000_000
        )

    @classmethod
    def from_timestamp_nanos(cls, i: int, /, *, tz: str) -> ZonedDateTime:
        if not isinstance(i, int):
            raise TypeError("method requires an integer")
        secs, nanos = divmod(i, 1_000_000_000)
        return cls._from_py_unchecked(
            _fromtimestamp(secs, ZoneInfo(tz)), nanos
        )

    # FUTURE: optional `disambiguate` to override fold?
    @classmethod
    def from_py_datetime(cls, d: _datetime, /) -> ZonedDateTime:
        if type(d.tzinfo) is not ZoneInfo:
            raise ValueError(
                "Can only create ZonedDateTime from tzinfo=ZoneInfo (exactly), "
                f"got datetime with tzinfo={d.tzinfo!r}"
            )

        # This ensures skipped times are disambiguated according to the fold.
        d = d.astimezone(_UTC).astimezone(d.tzinfo)
        return cls._from_py_unchecked(
            _strip_subclasses(d.replace(microsecond=0)), d.microsecond * 1_000
        )

    def replace_date(
        self, date: Date, /, disambiguate: Disambiguate
    ) -> ZonedDateTime:
        return self._from_py_unchecked(
            _resolve_ambiguity(
                _datetime.combine(date._py_date, self._py_dt.timetz()).replace(
                    fold=_as_fold(disambiguate)
                ),
                # mypy doesn't know that tzinfo is always a ZoneInfo here
                self._py_dt.tzinfo,  # type: ignore[arg-type]
                disambiguate,
            ),
            self._nanos,
        )

    def replace_time(
        self, time: Time, /, disambiguate: Disambiguate
    ) -> ZonedDateTime:
        return self._from_py_unchecked(
            _resolve_ambiguity(
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
        self, /, disambiguate: Disambiguate, **kwargs: Any
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
            _resolve_ambiguity(
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

    def __hash__(self) -> int:
        return hash((self._py_dt.astimezone(_UTC), self._nanos))

    def __add__(self, delta: TimeDelta) -> ZonedDateTime:
        """Add an amount of time, accounting for timezone changes (e.g. DST).

        See :ref:`the docs on arithmetic <arithmetic>` for more information.
        """
        if isinstance(delta, TimeDelta):
            delta_secs, nanos = divmod(
                delta._time_part._total_ns + self._nanos, 1_000_000_000
            )
            return self._from_py_unchecked(
                (
                    self._py_dt.astimezone(_UTC)
                    + _timedelta(seconds=delta_secs)
                ).astimezone(self._py_dt.tzinfo),
                nanos,
            )
        elif isinstance(delta, (DateDelta, DateTimeDelta)):
            raise TypeError(
                "Addition/subtraction of calendar units on a ZonedDateTime requires "
                "explicit disambiguation. Use the `add`/`subtract` methods instead. "
                "For example, instead of `dt + delta` use `dt.add(delta, disambiguate=...)`."
            )
        return NotImplemented

    @overload
    def __sub__(self, other: _KnowsInstant) -> TimeDelta: ...

    @overload
    def __sub__(self, other: TimeDelta) -> ZonedDateTime: ...

    def __sub__(
        self, other: TimeDelta | _KnowsInstant
    ) -> _KnowsInstant | TimeDelta:
        """Subtract another datetime or duration.

        See :ref:`the docs on arithmetic <arithmetic>` for more information.
        """
        if isinstance(other, _KnowsInstant):
            return super().__sub__(other)  # type: ignore[misc, no-any-return]
        elif isinstance(other, (TimeDelta, DateDelta, DateTimeDelta)):
            return self + -other
        return NotImplemented

    @no_type_check
    def add(self, *args, **kwargs) -> ZonedDateTime:
        return self._shift(1, *args, **kwargs)

    @no_type_check
    def subtract(self, *args, **kwargs) -> ZonedDateTime:
        return self._shift(-1, *args, **kwargs)

    @no_type_check
    def _shift(
        self,
        sign: int,
        delta: Delta | _UNSET = _UNSET,
        /,
        *,
        disambiguate: Disambiguate | _UNSET = _UNSET,
        **kwargs,
    ) -> ZonedDateTime:
        if kwargs:
            if delta is _UNSET:
                return self._shift_kwargs(
                    sign, disambiguate=disambiguate, **kwargs
                )
            raise TypeError("Cannot mix positional and keyword arguments")

        elif delta is not _UNSET:
            return self._shift_kwargs(
                sign,
                months=delta._date_part._months,
                days=delta._date_part._days,
                nanoseconds=delta._time_part._total_ns,
                disambiguate=disambiguate,
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
        disambiguate: Disambiguate,  # may be _UNSET sentinel
    ) -> ZonedDateTime:
        months_total = sign * (years * 12 + months)
        days_total = sign * (weeks * 7 + days)
        if months_total or days_total:
            if disambiguate is _UNSET:
                raise TypeError(
                    "'disambiguate' keyword argument must be provided when "
                    "adding/subtracting calendar units"
                )
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

    def is_ambiguous(self) -> bool:
        """Whether the local time is ambiguous, e.g. due to a DST transition.

        Example
        -------
        >>> ZonedDateTime(2020, 8, 15, 23, tz="Europe/London", disambiguate="later").ambiguous()
        False
        >>> ZonedDateTime(2023, 10, 29, 2, 15, tz="Europe/Amsterdam", disambiguate="later").ambiguous()
        True
        """
        # We make use of a quirk of the standard library here:
        # ambiguous datetimes are never equal across timezones
        return self._py_dt.astimezone(_UTC) != self._py_dt

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
    *args, nanos, offset_secs = unpack("<HBBBBBIl", data)
    args += (0, ZoneInfo(tz))
    return ZonedDateTime._from_py_unchecked(
        _adjust_fold_to_offset(
            _datetime(*args), _timedelta(seconds=offset_secs)
        ),
        nanos,
    )


@final
class SystemDateTime(_KnowsInstantAndLocal):
    """Represents a time in the system timezone.
    Unlike :class:`~OffsetDateTime`,
    it knows about the system timezone and its DST transitions.

    Example
    -------
    >>> # 8:00 in the system timezone—Paris in this case
    >>> alarm = SystemDateTime(2024, 3, 31, hour=6)
    SystemDateTime(2024-03-31 06:00:00+02:00)
    >>> # Conversion based on Paris' offset
    >>> alarm.instant()
    Instant(2024-03-31 04:00:00Z)
    >>> # DST-safe arithmetic
    >>> bedtime = alarm - hours(8)
    SystemDateTime(2024-03-30 21:00:00+01:00)

    Attention
    ---------
    To use this type properly, read more about :ref:`ambiguity <ambiguity>` and
    :ref:`working with the system timezone <systemtime>`.

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
        *,
        nanosecond: int = 0,
        disambiguate: Disambiguate = "raise",
    ) -> None:
        self._py_dt = _resolve_system_ambiguity(
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
    def now(cls) -> SystemDateTime:
        secs, nanos = divmod(time_ns(), 1_000_000_000)
        return cls._from_py_unchecked(
            _fromtimestamp(secs, _UTC).astimezone(None), nanos
        )

    format_common_iso = OffsetDateTime.format_common_iso

    @classmethod
    def parse_common_iso(cls, s: str, /) -> SystemDateTime:
        """Parse from the common ISO 8601 format,

        similar to that of ``OffsetDateTime``."""
        odt = OffsetDateTime.parse_common_iso(s)
        return cls._from_py_unchecked(odt._py_dt, odt._nanos)

    @classmethod
    def from_timestamp(cls, i: int | float, /) -> SystemDateTime:
        secs, fract = divmod(i, 1)
        return cls._from_py_unchecked(
            _fromtimestamp(secs, _UTC).astimezone(), int(fract * 1_000_000_000)
        )

    @classmethod
    def from_timestamp_millis(cls, i: int, /) -> SystemDateTime:
        if not isinstance(i, int):
            raise TypeError("method requires an integer")
        secs, millis = divmod(i, 1_000)
        return cls._from_py_unchecked(
            _fromtimestamp(secs, _UTC).astimezone(), millis * 1_000_000
        )

    @classmethod
    def from_timestamp_nanos(cls, i: int, /) -> SystemDateTime:
        if not isinstance(i, int):
            raise TypeError("method requires an integer")
        secs, nanos = divmod(i, 1_000_000_000)
        return cls._from_py_unchecked(
            _fromtimestamp(secs, _UTC).astimezone(), nanos
        )

    @classmethod
    def from_py_datetime(cls, d: _datetime, /) -> SystemDateTime:
        odt = OffsetDateTime.from_py_datetime(d)
        return cls._from_py_unchecked(odt._py_dt, odt._nanos)

    def __repr__(self) -> str:
        return f"SystemDateTime({str(self).replace('T', ' ')})"

    # FUTURE: expose the tzname?

    def replace_date(
        self, date: Date, /, disambiguate: Disambiguate
    ) -> SystemDateTime:
        return self._from_py_unchecked(
            _resolve_system_ambiguity(
                _datetime.combine(date._py_date, self._py_dt.time()).replace(
                    fold=_as_fold(disambiguate)
                ),
                disambiguate,
            ),
            self._nanos,
        )

    def replace_time(
        self, time: Time, /, disambiguate: Disambiguate
    ) -> SystemDateTime:
        return self._from_py_unchecked(
            _resolve_system_ambiguity(
                _datetime.combine(self._py_dt, time._py_time).replace(
                    fold=_as_fold(disambiguate)
                ),
                disambiguate,
            ),
            time._nanos,
        )

    def replace(
        self, /, disambiguate: Disambiguate, **kwargs: Any
    ) -> SystemDateTime:
        _check_invalid_replace_kwargs(kwargs)
        nanos = _pop_nanos_kwarg(kwargs, self._nanos)
        return self._from_py_unchecked(
            _resolve_system_ambiguity(
                self._py_dt.replace(
                    tzinfo=None, fold=_as_fold(disambiguate), **kwargs
                ),
                disambiguate,
            ),
            nanos,
        )

    def __hash__(self) -> int:
        return hash((self._py_dt, self._nanos))

    def __add__(self, delta: TimeDelta) -> SystemDateTime:
        """Add an amount of time, accounting for timezone changes (e.g. DST).

        See :ref:`the docs on arithmetic <arithmetic>` for more information.
        """
        if isinstance(delta, TimeDelta):
            py_dt = self._py_dt
            delta_secs, nanos = divmod(
                delta._time_part._total_ns + self._nanos, 1_000_000_000
            )
            return self._from_py_unchecked(
                (py_dt + _timedelta(seconds=delta_secs)).astimezone(), nanos
            )
        elif isinstance(delta, (DateDelta, DateTimeDelta)):
            raise TypeError(
                "Addition/subtraction of calendar units on a SystemDateTime requires "
                "explicit disambiguation. Use the `add`/`subtract` methods instead. "
                "For example, instead of `dt + delta` use `dt.add(delta, disambiguate=...)`."
            )
        return NotImplemented

    @overload
    def __sub__(self, other: _KnowsInstant) -> TimeDelta: ...

    @overload
    def __sub__(self, other: TimeDelta) -> SystemDateTime: ...

    def __sub__(
        self, other: TimeDelta | _KnowsInstant
    ) -> _KnowsInstant | Delta:
        """Subtract another datetime or duration

        See :ref:`the docs on arithmetic <arithmetic>` for more information.
        """
        if isinstance(other, _KnowsInstant):
            return super().__sub__(other)  # type: ignore[misc, no-any-return]
        elif isinstance(other, (TimeDelta, DateDelta, DateTimeDelta)):
            return self + -other
        return NotImplemented

    @no_type_check
    def add(self, *args, **kwargs) -> SystemDateTime:
        return self._shift(1, *args, **kwargs)

    @no_type_check
    def subtract(self, *args, **kwargs) -> SystemDateTime:
        return self._shift(-1, *args, **kwargs)

    @no_type_check
    def _shift(
        self,
        sign: int,
        delta: Delta | _UNSET = _UNSET,
        /,
        *,
        disambiguate: Disambiguate | _UNSET = _UNSET,
        **kwargs,
    ) -> SystemDateTime:
        if kwargs:
            if delta is _UNSET:
                return self._shift_kwargs(
                    sign, disambiguate=disambiguate, **kwargs
                )
            raise TypeError("Cannot mix positional and keyword arguments")

        elif delta is not _UNSET:
            return self._shift_kwargs(
                sign,
                months=delta._date_part._months,
                days=delta._date_part._days,
                nanoseconds=delta._time_part._total_ns,
                disambiguate=disambiguate,
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
        disambiguate: Disambiguate,  # may be _UNSET sentinel
    ) -> SystemDateTime:
        months_total = sign * (years * 12 + months)
        days_total = sign * (weeks * 7 + days)
        if months_total or days_total:
            if disambiguate is _UNSET:
                raise TypeError(
                    "'disambiguate' keyword argument must be provided when "
                    "adding/subtracting calendar units"
                )
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

    # a custom pickle implementation with a smaller payload
    def __reduce__(self) -> tuple[object, ...]:
        return (
            _unpkl_system,
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
def _unpkl_system(data: bytes) -> SystemDateTime:
    *args, nanos, offset_secs = unpack("<HBBBBBIl", data)
    args += (0, _timezone(_timedelta(seconds=offset_secs)))
    return SystemDateTime._from_py_unchecked(_datetime(*args), nanos)


@final
class LocalDateTime(_KnowsLocal):
    """A local date and time, i.e. it would appear to people on a wall clock.

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
    """

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
        self._py_dt = _datetime(year, month, day, hour, minute, second)
        self._nanos = nanosecond

    def format_common_iso(self) -> str:
        return (
            (self._py_dt.isoformat() + f".{self._nanos:09d}").rstrip("0")
            if self._nanos
            else self._py_dt.isoformat()
        )

    @classmethod
    def parse_common_iso(cls, s: str, /) -> LocalDateTime:
        """Parse from the commonly used ISO 8601 format
        ``YYYY-MM-DDTHH:MM:SS``, where seconds may be fractional.

        Inverse of :meth:`~_DateTime.format_common_iso`.

        Example
        -------
        >>> LocalDateTime.parse_common_iso("2020-08-15T23:12:00")
        LocalDateTime(2020-08-15 23:12:00)
        """
        if (match := _match_local_str(s)) is None:
            raise ValueError(f"Invalid format: {s!r}")
        year, month, day, hour, minute, second = map(int, match.groups()[:6])
        nanos = int(match.group(7).ljust(9, "0")) if match.group(7) else 0
        return cls._from_py_unchecked(
            _datetime(year, month, day, hour, minute, second), nanos
        )

    @classmethod
    def from_py_datetime(cls, d: _datetime, /) -> LocalDateTime:
        if d.tzinfo is not None:
            raise ValueError(
                "Can only create LocalDateTime from a naive datetime, "
                f"got datetime with tzinfo={d.tzinfo!r}"
            )
        return cls._from_py_unchecked(
            _strip_subclasses(d.replace(microsecond=0)), d.microsecond * 1_000
        )

    def replace(self, /, **kwargs: Any) -> LocalDateTime:
        if not _no_tzinfo_fold_or_ms(kwargs):
            raise TypeError(
                "tzinfo, fold, or microsecond are not allowed arguments"
            )
        nanos = _pop_nanos_kwarg(kwargs, self._nanos)
        return self._from_py_unchecked(self._py_dt.replace(**kwargs), nanos)

    def replace_date(self, d: Date, /) -> LocalDateTime:
        return self._from_py_unchecked(
            _datetime.combine(d._py_date, self._py_dt.time()), self._nanos
        )

    def replace_time(self, t: Time, /) -> LocalDateTime:
        return self._from_py_unchecked(
            _datetime.combine(self._py_dt.date(), t._py_time), t._nanos
        )

    def __hash__(self) -> int:
        return hash((self._py_dt, self._nanos))

    def __eq__(self, other: object) -> bool:
        """Compare objects for equality.
        Only ever equal to other :class:`LocalDateTime` instances with the
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
        >>> LocalDateTime(2020, 8, 15, 23) == LocalDateTime(2020, 8, 15, 23)
        True
        >>> LocalDateTime(2020, 8, 15, 23, 1) == LocalDateTime(2020, 8, 15, 23)
        False
        >>> LocalDateTime(2020, 8, 15) == Instant.from_utc(2020, 8, 15)
        False  # Use mypy's --strict-equality flag to detect this.
        """
        if not isinstance(other, LocalDateTime):
            return NotImplemented
        return (self._py_dt, self._nanos) == (other._py_dt, other._nanos)

    MIN: ClassVar[LocalDateTime]
    MAX: ClassVar[LocalDateTime]

    def __lt__(self, other: LocalDateTime) -> bool:
        if not isinstance(other, LocalDateTime):
            return NotImplemented
        return (self._py_dt, self._nanos) < (other._py_dt, other._nanos)

    def __le__(self, other: LocalDateTime) -> bool:
        if not isinstance(other, LocalDateTime):
            return NotImplemented
        return (self._py_dt, self._nanos) <= (other._py_dt, other._nanos)

    def __gt__(self, other: LocalDateTime) -> bool:
        if not isinstance(other, LocalDateTime):
            return NotImplemented
        return (self._py_dt, self._nanos) > (other._py_dt, other._nanos)

    def __ge__(self, other: LocalDateTime) -> bool:
        if not isinstance(other, LocalDateTime):
            return NotImplemented
        return (self._py_dt, self._nanos) >= (other._py_dt, other._nanos)

    def __add__(self, delta: DateDelta) -> LocalDateTime:
        """Add a delta to this datetime.

        See :ref:`the docs on arithmetic <arithmetic>` for more information.
        """
        if isinstance(delta, DateDelta):
            return self._from_py_unchecked(
                _datetime.combine(
                    (self.date() + delta._date_part)._py_date,
                    self._py_dt.time(),
                ),
                self._nanos,
            )
        elif isinstance(delta, (TimeDelta, DateTimeDelta)):
            raise ImplicitlyIgnoringDST(
                "Adding or subtracting a (date)time delta to a local datetime "
                "implicitly ignores DST transitions and other timezone "
                "changes. Instead, use the `add` or `subtract` method."
            )
        return NotImplemented

    def __sub__(self, other: DateDelta) -> LocalDateTime:
        """Subtract another datetime or delta

        See :ref:`the docs on arithmetic <arithmetic>` for more information.
        """
        # Handling these extra types allows for descriptive error messages
        if isinstance(other, (DateDelta, TimeDelta, DateTimeDelta)):
            return self + -other
        elif isinstance(other, LocalDateTime):
            raise ImplicitlyIgnoringDST(
                "The difference between two local datetimes implicitly ignores "
                "DST transitions and other timezone changes. "
                "Use the `difference` method instead."
            )
        return NotImplemented

    def difference(
        self, other: LocalDateTime, /, *, ignore_dst: bool = False
    ) -> TimeDelta:
        """Calculate the difference between two local datetimes.

        See :ref:`the docs on arithmetic <arithmetic>` for more information.
        """
        if ignore_dst is not True:
            raise ImplicitlyIgnoringDST(
                "The difference between two local datetimes implicitly ignores "
                "DST transitions and other timezone changes. "
                + _IGNORE_DST_SUGGESTION
            )

        py_delta = self._py_dt - other._py_dt
        return TimeDelta(
            seconds=py_delta.days * 86_400 + py_delta.seconds,
            nanoseconds=self._nanos - other._nanos,
        )

    @no_type_check
    def add(self, *args, **kwargs) -> LocalDateTime:
        return self._shift(1, *args, **kwargs)

    @no_type_check
    def subtract(self, *args, **kwargs) -> LocalDateTime:
        return self._shift(-1, *args, **kwargs)

    @no_type_check
    def _shift(
        self,
        sign: int,
        arg: Delta | _UNSET = _UNSET,
        /,
        *,
        ignore_dst: bool = False,
        **kwargs,
    ) -> LocalDateTime:
        if kwargs:
            if arg is _UNSET:
                return self._shift_kwargs(sign, ignore_dst, **kwargs)
            raise TypeError("Cannot mix positional and keyword arguments")

        elif arg is not _UNSET:
            return self._shift_kwargs(
                sign,
                ignore_dst,
                months=arg._date_part._months,
                days=arg._date_part._days,
                nanoseconds=arg._time_part._total_ns,
            )
        else:
            return self

    def _shift_kwargs(
        self,
        sign: int,
        ignore_dst: bool,
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
    ) -> LocalDateTime:
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
        if tdelta and ignore_dst is not True:
            raise _EXC_ADJUST_LOCAL_DATETIME

        delta_secs, nanos = divmod(
            tdelta._total_ns + self._nanos, 1_000_000_000
        )
        return self._from_py_unchecked(
            (py_dt_with_new_date + _timedelta(seconds=delta_secs)),
            nanos,
        )

    @classmethod
    def strptime(cls, s: str, /, fmt: str) -> LocalDateTime:
        """Simple alias for
        ``LocalDateTime.from_py_datetime(datetime.strptime(s, fmt))``

        Example
        -------
        >>> LocalDateTime.strptime("2020-08-15", "%Y-%m-%d")
        LocalDateTime(2020-08-15 00:00:00)

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

    def assume_utc(self) -> Instant:
        """Assume the datetime is in UTC,
        creating a :class:`~whenever.Instant` instance.

        Example
        -------
        >>> LocalDateTime(2020, 8, 15, 23, 12).assume_utc()
        Instant(2020-08-15 23:12:00Z)
        """
        return Instant._from_py_unchecked(
            self._py_dt.replace(tzinfo=_UTC), self._nanos
        )

    def assume_fixed_offset(
        self, offset: int | TimeDelta, /
    ) -> OffsetDateTime:
        """Assume the datetime is in the given offset,
        creating a :class:`~whenever.OffsetDateTime` instance.

        Example
        -------
        >>> LocalDateTime(2020, 8, 15, 23, 12).assume_fixed_offset(+2)
        OffsetDateTime(2020-08-15 23:12:00+02:00)
        """
        return OffsetDateTime._from_py_unchecked(
            self._py_dt.replace(tzinfo=_load_offset(offset)), self._nanos
        )

    def assume_tz(
        self, tz: str, /, disambiguate: Disambiguate
    ) -> ZonedDateTime:
        """Assume the datetime is in the given timezone,
        creating a :class:`~whenever.ZonedDateTime` instance.

        Example
        -------
        >>> d = LocalDateTime(2020, 8, 15, 23, 12)
        >>> d.assume_tz("Europe/Amsterdam", disambiguate="raise")
        ZonedDateTime(2020-08-15 23:12:00+02:00[Europe/Amsterdam])
        """
        return ZonedDateTime._from_py_unchecked(
            _resolve_ambiguity(
                self._py_dt.replace(
                    tzinfo=(zone := ZoneInfo(tz)), fold=_as_fold(disambiguate)
                ),
                zone,
                disambiguate,
            ),
            self._nanos,
        )

    def assume_system_tz(self, disambiguate: Disambiguate) -> SystemDateTime:
        """Assume the datetime is in the system timezone,
        creating a :class:`~whenever.SystemDateTime` instance.

        Example
        -------
        >>> d = LocalDateTime(2020, 8, 15, 23, 12)
        >>> # assuming system timezone is America/New_York
        >>> d.assume_system_tz(disambiguate="raise")
        SystemDateTime(2020-08-15 23:12:00-04:00)
        """
        return SystemDateTime._from_py_unchecked(
            _resolve_system_ambiguity(
                self._py_dt.replace(fold=_as_fold(disambiguate)),
                disambiguate,
            ),
            self._nanos,
        )

    def __repr__(self) -> str:
        return f"LocalDateTime({str(self).replace('T', ' ')})"

    # a custom pickle implementation with a smaller payload
    def __reduce__(self) -> tuple[object, ...]:
        return (
            _unpkl_local,
            (pack("<HBBBBBI", *self._py_dt.timetuple()[:6], self._nanos),),
        )


# A separate unpickling function allows us to make backwards-compatible changes
# to the pickling format in the future
@no_type_check
def _unpkl_local(data: bytes) -> LocalDateTime:
    *args, nanos = unpack("<HBBBBBI", data)
    return LocalDateTime._from_py_unchecked(_datetime(*args), nanos)


# RepeatedTime
class RepeatedTime(Exception):
    """A datetime is repeated in a timezone, e.g. because of DST"""

    @classmethod
    def _for_tz(cls, d: _datetime, tz: ZoneInfo) -> RepeatedTime:
        return cls(
            f"{d.replace(tzinfo=None)} is repeated " f"in timezone {tz.key!r}"
        )

    @classmethod
    def _for_system_tz(cls, d: _datetime) -> RepeatedTime:
        return cls(
            f"{d.replace(tzinfo=None)} is repeated in the system timezone"
        )


class SkippedTime(Exception):
    """A datetime is skipped in a timezone, e.g. because of DST"""

    @classmethod
    def _for_tz(cls, d: _datetime, tz: ZoneInfo) -> SkippedTime:
        return cls(
            f"{d.replace(tzinfo=None)} is skipped " f"in timezone {tz.key!r}"
        )

    @classmethod
    def _for_system_tz(cls, d: _datetime) -> SkippedTime:
        return cls(
            f"{d.replace(tzinfo=None)} is skipped in the system timezone"
        )


class InvalidOffset(ValueError):
    """A string has an invalid offset for the given zone"""


class ImplicitlyIgnoringDST(TypeError):
    """A calculation was performed that implicitly ignored DST"""


_EXC_TIMESTAMP_DST = ImplicitlyIgnoringDST(
    "Converting from a timestamp with a fixed offset implicitly ignores DST "
    "and other timezone changes. To perform a DST-safe conversion, use "
    "ZonedDateTime.from_timestamp() instead. "
    "Or, if you don't know the timezone and accept potentially incorrect results "
    "during DST transitions, pass `ignore_dst=True`."
)


# FUTURE: docs link
_IGNORE_DST_SUGGESTION = """\
To perform DST-safe operations, convert to a ZonedDateTime first. \
Or, if you don't know the timezone and accept potentially incorrect results \
during DST transitions, pass `ignore_dst=True`."""


_EXC_ADJUST_OFFSET_DATETIME = ImplicitlyIgnoringDST(
    "Adjusting a fixed offset datetime implicitly ignores DST and other timezone changes. "
    + _IGNORE_DST_SUGGESTION
)

_EXC_ADJUST_LOCAL_DATETIME = ImplicitlyIgnoringDST(
    "Adjusting a local datetime by time units (e.g. hours and minutess) ignores "
    "DST and other timezone changes. " + _IGNORE_DST_SUGGESTION
)


def _resolve_ambiguity(
    dt: _datetime, zone: ZoneInfo, disambiguate: Disambiguate
) -> _datetime:
    dt_utc = dt.astimezone(_UTC)
    # Non-existent times: they don't survive a UTC roundtrip
    if dt_utc.astimezone(zone) != dt:
        if disambiguate == "raise":
            raise SkippedTime._for_tz(dt, zone)
        elif disambiguate != "compatible":  # i.e. "earlier" or "later"
            # In gaps, the relationship between
            # fold and earlier/later is reversed
            dt = dt.replace(fold=not dt.fold)
        # perform the normalisation, shifting away from non-existent times
        dt = dt.astimezone(_UTC).astimezone(zone)
    # Ambiguous times: they're never equal to other timezones
    elif disambiguate == "raise" and dt_utc != dt:
        raise RepeatedTime._for_tz(dt, zone)
    return dt


# Whether the fold of a system time needs to be flipped in a gap
# was changed (fixed) in Python 3.12. See cpython/issues/83861
_requires_flip: Callable[[Disambiguate], bool] = (
    "compatible".__ne__ if sys.version_info > (3, 12) else "compatible".__eq__
)


def _resolve_system_ambiguity(
    dt: _datetime, disambiguate: Disambiguate
) -> _datetime:
    assert dt.tzinfo is None
    norm = dt.astimezone(_UTC).astimezone()
    # Non-existent times: they don't survive a UTC roundtrip
    if norm.replace(tzinfo=None) != dt:
        if disambiguate == "raise":
            raise SkippedTime._for_system_tz(dt)
        elif _requires_flip(disambiguate):
            dt = dt.replace(fold=not dt.fold)
        # perform the normalisation, shifting away from non-existent times
        norm = dt.astimezone(_UTC).astimezone()
    # Ambiguous times: their UTC depends on the fold
    elif disambiguate == "raise" and norm != dt.replace(fold=1).astimezone(
        _UTC
    ):
        raise RepeatedTime._for_system_tz(dt)
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
_fromisoformat = _datetime.fromisoformat
_fromtimestamp = _datetime.fromtimestamp
_DT_RE_GROUPED = r"(\d{4})-([0-2]\d)-([0-3]\d)T([0-2]\d):([0-5]\d):([0-5]\d)(?:\.(\d{1,9}))?"
_OFFSET_DATETIME_RE = (
    _DT_RE_GROUPED + r"(?:([+-])(\d{2}):(\d{2})(?::(\d{2}))?|Z)"
)
_match_local_str = re.compile(_DT_RE_GROUPED, re.ASCII).fullmatch
_match_offset_str = re.compile(_OFFSET_DATETIME_RE, re.ASCII).fullmatch
_match_zoned_str = re.compile(
    _OFFSET_DATETIME_RE + r"\[([^\]]{1,255})\]", re.ASCII
).fullmatch
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
_match_time = re.compile(
    r"([0-2]\d):([0-5]\d):([0-5]\d)(?:\.(\d{1,9}))?", re.ASCII
).fullmatch
_match_next_timedelta_component = re.compile(
    r"^(\d{1,35}(?:\.\d{1,9})?)([HMS])", re.ASCII
).match
_match_next_datedelta_component = re.compile(
    r"^(\d{1,8})([YMWD])", re.ASCII
).match


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
    if type(nanos) is not int:
        raise TypeError("nanosecond must be an int")
    elif not 0 <= nanos < 1_000_000_000:
        raise ValueError("Invalid nanosecond value")
    return nanos


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

Instant.MIN = Instant._from_py_unchecked(
    _datetime.min.replace(tzinfo=_UTC),
    0,
)
Instant.MAX = Instant._from_py_unchecked(
    _datetime.max.replace(tzinfo=_UTC, microsecond=0),
    999_999_999,
)
LocalDateTime.MIN = LocalDateTime._from_py_unchecked(_datetime.min, 0)
LocalDateTime.MAX = LocalDateTime._from_py_unchecked(
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
    if getattr(member, "__module__", None) == __name__:  # pragma: no branch
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
    _unpkl_system,
    _unpkl_local,
):
    _unpkl.__module__ = "whenever"


# disable further subclassing
final(_ImmutableBase)
final(_KnowsInstant)
final(_KnowsLocal)
final(_KnowsInstantAndLocal)
final(_BasicConversions)


_time_patch = None


def _patch_time_frozen(inst: Instant) -> None:
    global _time_patch
    global time_ns

    def time_ns() -> int:
        return inst.timestamp_nanos()


def _patch_time_keep_ticking(inst: Instant) -> None:
    global _time_patch
    global time_ns

    _patched_at = time_ns()
    _time_ns = time_ns

    def time_ns() -> int:
        return inst.timestamp_nanos() + _time_ns() - _patched_at


def _unpatch_time() -> None:
    global _time_patch
    global time_ns

    from time import time_ns
