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

__version__ = "0.5.1"

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
from operator import attrgetter
from typing import (
    TYPE_CHECKING,
    Callable,
    ClassVar,
    Literal,
    TypeVar,
    Union,
    no_type_check,
    overload,
)

try:
    from typing import SPHINX_BUILD  # type: ignore[attr-defined]
except ImportError:
    SPHINX_BUILD = False

try:
    from zoneinfo import ZoneInfo
except ImportError:  # pragma: no cover
    from backports.zoneinfo import (  # type: ignore[import-not-found,no-redef]
        ZoneInfo,
    )

__all__ = [
    # Date and time
    "Date",
    "Time",
    "_DateTime",
    "_AwareDateTime",
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
    "microseconds",
    # Exceptions
    "SkippedTime",
    "AmbiguousTime",
    "InvalidOffsetForZone",
]


MONDAY, TUESDAY, WEDNESDAY, THURSDAY, FRIDAY, SATURDAY, SUNDAY = range(1, 8)


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


class Date(_ImmutableBase):
    """A date without a time component

    Example
    -------
    >>> d = Date(2021, 1, 2)
    Date(2021-01-02)
    """

    __slots__ = ("_py_date",)

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

    if not TYPE_CHECKING:  # pragma: no branch

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

        __hash__ = property(attrgetter("_py_date.__hash__"))

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
    def from_py_date(cls, d: _date, /) -> Date:
        """Create from a :class:`~datetime.date`

        Example
        -------
        >>> Date.from_py_date(date(2021, 1, 2))
        Date(2021-01-02)
        """
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
        return Date.from_py_date(
            self._add_months(12 * years + months)._py_date
            + _timedelta(days, weeks=weeks)
        )

    def __add__(self, p: DateDelta) -> Date:
        """Add a delta to a date.
        Behaves the same as :meth:`add`
        """
        return self.add(
            years=p.years, months=p.months, weeks=p.weeks, days=p.days
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

    def _add_months(self, ms: int) -> Date:
        year_overflow, month_new = divmod(self.month - 1 + ms, 12)
        month_new += 1
        year_new = self.year + year_overflow
        return Date(
            year_new,
            month_new,
            min(self.day, monthrange(year_new, month_new)[1]),
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
        DateDelta(P-9M)
        """
        if isinstance(d, DateDelta):
            return self.subtract(
                years=d.years, months=d.months, weeks=d.weeks, days=d.days
            )
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
                yrs, mos = divmod(mos, -12)
                yrs = -yrs
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

                yrs, mos = divmod(mos, 12)
            return DateDelta(years=yrs, months=mos, days=dys)
        return NotImplemented

    def day_of_week(self) -> int:
        """The day of the week, where 1 is Monday and 7 is Sunday

        Warning
        -------
        This method uses the ISO definition of the week, in contrast to
        the :meth:`~datetime.date.weekday` method.

        Example
        -------
        >>> from whenever import SATURDAY
        >>> Date(2021, 1, 2).day_of_week()
        6
        >>> Date(2021, 1, 2).day_of_week() == SATURDAY
        True
        """
        return self._py_date.isoweekday()

    def at(self, t: Time, /) -> NaiveDateTime:
        """Combine a date with a time to create a datetime

        Example
        -------
        >>> d = Date(2021, 1, 2)
        >>> d.at(Time(12, 30))
        NaiveDateTime(2021-01-02 12:30:00)

        You can use methods like :meth:`~NaiveDateTime.assume_utc`
        or :meth:`~NaiveDateTime.assume_zoned` to make the result aware.
        """
        return NaiveDateTime.from_py_datetime(
            _datetime.combine(self._py_date, t._py_time)
        )

    def canonical_format(self) -> str:
        """The date in canonical format.

        Example
        -------
        >>> d = Date(2021, 1, 2)
        >>> d.canonical_format()
        '2021-01-02'
        """
        return self._py_date.isoformat()

    @classmethod
    def from_canonical_format(cls, s: str, /) -> Date:
        """Create from the canonical string representation.

        Inverse of :meth:`canonical_format`

        Example
        -------
        >>> Date.from_canonical_format("2021-01-02")
        Date(2021-01-02)
        """
        try:
            if s[5] == "W":
                # prevent isoformat from parsing week dates
                raise ValueError("Week dates are not supported")
            return cls.from_py_date(_date.fromisoformat(s))
        except ValueError as e:
            raise ValueError(
                "Could not parse as canonical format "
                f"or common ISO 8601 string: {s!r}"
            ) from e

    __str__ = canonical_format

    def common_iso8601(self) -> str:
        """Format as the common ISO 8601 date format.

        Inverse of :meth:`from_common_iso8601`.
        Equivalent to :meth:`canonical_format`.

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
        Equivalent to :meth:`from_canonical_format`.

        Example
        -------
        >>> Date.from_common_iso8601("2021-01-02")
        Date(2021-01-02)
        """
        return cls.from_canonical_format(s)

    @no_type_check
    def __reduce__(self):
        return _unpkl_date, (self.year, self.month, self.day)


# A separate unpickling function allows us to make backwards-compatible changes
# to the pickling format in the future
@no_type_check
def _unpkl_date(*args):
    return Date(*args)


class Time(_ImmutableBase):
    """Time of day without a date component

    Example
    -------
    >>> t = Time(12, 30, 0)
    Time(12:30:00)

    Canonical format
    ----------------

    The canonical format is:

    .. code-block:: text

       HH:MM:SS(.ffffff)

    For example:

    .. code-block:: text

       12:30:11.004
    """

    __slots__ = ("_py_time",)

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
        microsecond: int = 0,
    ) -> None:
        self._py_time = _time(hour, minute, second, microsecond)

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
    def microsecond(self) -> int:
        return self._py_time.microsecond

    @classmethod
    def from_py_time(cls, t: _time, /) -> Time:
        """Create from a :class:`~datetime.time`

        Example
        -------
        >>> Time.from_py_time(time(12, 30, 0))
        Time(12:30:00)

        Raises ValueError if the time is not naive or has fold=1.
        """
        if t.tzinfo is not None:
            raise ValueError("Time must be naive")
        elif t.fold:
            raise ValueError("Time must have fold=0")
        return cls._from_py_unchecked(t)

    @classmethod
    def _from_py_unchecked(cls, t: _time, /) -> Time:
        self = _object_new(cls)
        self._py_time = t
        return self

    def __repr__(self) -> str:
        return f"Time({self})"

    if not TYPE_CHECKING:  # pragma: no branch

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
            return self._py_time == other._py_time

        __hash__ = property(attrgetter("_py_time.__hash__"))

    def __lt__(self, other: Time) -> bool:
        if not isinstance(other, Time):
            return NotImplemented
        return self._py_time < other._py_time

    def __le__(self, other: Time) -> bool:
        if not isinstance(other, Time):
            return NotImplemented
        return self._py_time <= other._py_time

    def __gt__(self, other: Time) -> bool:
        if not isinstance(other, Time):
            return NotImplemented
        return self._py_time > other._py_time

    def __ge__(self, other: Time) -> bool:
        if not isinstance(other, Time):
            return NotImplemented
        return self._py_time >= other._py_time

    def on(self, d: Date, /) -> NaiveDateTime:
        """Combine a time with a date to create a datetime

        Example
        -------
        >>> t = Time(12, 30)
        >>> t.on(Date(2021, 1, 2))
        NaiveDateTime(2021-01-02 12:30:00)

        Then, use methods like :meth:`~NaiveDateTime.assume_utc`
        or :meth:`~NaiveDateTime.assume_zoned`
        to make the result aware.
        """
        return NaiveDateTime.from_py_datetime(
            _datetime.combine(d._py_date, self._py_time)
        )

    def canonical_format(self) -> str:
        """The time in canonical format.

        Example
        -------
        >>> t = Time(12, 30, 0)
        >>> t.canonical_format()
        '12:30:00'
        """
        return (
            self._py_time.isoformat().rstrip("0")
            if self._py_time.microsecond
            else self._py_time.isoformat()
        )

    __str__ = canonical_format

    @classmethod
    def from_canonical_format(cls, s: str, /) -> Time:
        """Create from the canonical string representation.

        Inverse of :meth:`canonical_format`

        Example
        -------
        >>> Time.from_canonical_format("12:30:00")
        Time(12:30:00)

        Raises
        ------
        ValueError
            If the string does not match this exact format.
        """
        if not _match_time(s):
            raise ValueError(
                "Could not parse as canonical format "
                f"or common ISO 8601 string: {s!r}"
            )
        return cls._from_py_unchecked(_fromisoformat_time(s))

    def common_iso8601(self) -> str:
        """Format as the common ISO 8601 time format.

        Inverse of :meth:`from_common_iso8601`.
        Equivalent to :meth:`canonical_format`.

        Example
        -------
        >>> Time(12, 30, 0).common_iso8601()
        '12:30:00'
        """
        return self.canonical_format()

    @classmethod
    def from_common_iso8601(cls, s: str, /) -> Time:
        """Create from the common ISO 8601 time format ``HH:MM:SS``.
        Does not accept more "exotic" ISO 8601 formats.

        Inverse of :meth:`common_iso8601`.
        Equivalent to :meth:`from_canonical_format`.

        Example
        -------
        >>> Time.from_common_iso8601("12:30:00")
        Time(12:30:00)
        """
        return cls.from_canonical_format(s)

    @no_type_check
    def __reduce__(self):
        return (
            _unpkl_time,
            (self.hour, self.minute, self.second, self.microsecond),
        )


# A separate unpickling function allows us to make backwards-compatible changes
# to the pickling format in the future
@no_type_check
def _unpkl_time(*args):
    return Time(*args)


Time.MIDNIGHT = Time()
Time.NOON = Time(12)
Time.MAX = Time(23, 59, 59, 999_999)


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

    __slots__ = ("_total_ms",)

    def __init__(
        self,
        *,
        hours: float = 0,
        minutes: float = 0,
        seconds: float = 0,
        microseconds: int = 0,
    ) -> None:
        assert type(microseconds) is int  # catch this common mistake
        self._total_ms = (
            # Cast individual components to int to avoid floating point errors
            int(hours * 3_600_000_000)
            + int(minutes * 60_000_000)
            + int(seconds * 1_000_000)
            + microseconds
        )

    ZERO: ClassVar[TimeDelta]
    """A delta of zero"""
    _date_part: ClassVar[DateDelta]

    @property
    def _time_part(self) -> TimeDelta:
        """The time part, always equal to the delta itself"""
        return self

    def in_hours(self) -> float:
        """The total size in hours

        Example
        -------
        >>> d = TimeDelta(hours=1, minutes=30)
        >>> d.in_hours()
        1.5
        """
        return self._total_ms / 3_600_000_000

    def in_minutes(self) -> float:
        """The total size in minutes

        Example
        -------
        >>> d = TimeDelta(hours=1, minutes=30, seconds=30)
        >>> d.in_minutes()
        90.5
        """
        return self._total_ms / 60_000_000

    def in_seconds(self) -> float:
        """The total size in seconds

        Example
        -------
        >>> d = TimeDelta(minutes=2, seconds=1, microseconds=500_000)
        >>> d.in_seconds()
        121.5
        """
        return self._total_ms / 1_000_000

    def in_microseconds(self) -> int:
        """The total size in microseconds

        >>> d = TimeDelta(seconds=2, microseconds=50)
        >>> d.in_microseconds()
        2_000_050
        """
        return self._total_ms

    # Hiding __eq__ from mypy ensures that --strict-equality works
    if not TYPE_CHECKING:  # pragma: no branch

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
            return self._total_ms == other._total_ms

    def __hash__(self) -> int:
        return hash(self._total_ms)

    def __lt__(self, other: TimeDelta) -> bool:
        if not isinstance(other, TimeDelta):
            return NotImplemented
        return self._total_ms < other._total_ms

    def __le__(self, other: TimeDelta) -> bool:
        if not isinstance(other, TimeDelta):
            return NotImplemented
        return self._total_ms <= other._total_ms

    def __gt__(self, other: TimeDelta) -> bool:
        if not isinstance(other, TimeDelta):
            return NotImplemented
        return self._total_ms > other._total_ms

    def __ge__(self, other: TimeDelta) -> bool:
        if not isinstance(other, TimeDelta):
            return NotImplemented
        return self._total_ms >= other._total_ms

    def __bool__(self) -> bool:
        """True if the value is non-zero

        Example
        -------
        >>> bool(TimeDelta())
        False
        >>> bool(TimeDelta(minutes=1))
        True
        """
        return bool(self._total_ms)

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
        return TimeDelta(microseconds=self._total_ms + other._total_ms)

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
        return TimeDelta(microseconds=self._total_ms - other._total_ms)

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
        return TimeDelta(microseconds=int(self._total_ms * other))

    def __neg__(self) -> TimeDelta:
        """Negate the value

        Example
        -------
        >>> d = TimeDelta(hours=1, minutes=30)
        >>> -d
        TimeDelta(-01:30:00)
        """
        return TimeDelta(microseconds=-self._total_ms)

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
            return self._total_ms / other._total_ms
        elif isinstance(other, (int, float)):
            return TimeDelta(microseconds=int(self._total_ms / other))
        return NotImplemented

    def __abs__(self) -> TimeDelta:
        """The absolute value

        Example
        -------
        >>> d = TimeDelta(hours=-1, minutes=-30)
        >>> abs(d)
        TimeDelta(01:30:00)
        """
        return TimeDelta(microseconds=abs(self._total_ms))

    def canonical_format(self) -> str:
        """Format the delta in the canonical string format.

        The format is:

        .. code-block:: text

           HH:MM:SS(.ffffff)

        For example:

        .. code-block:: text

           01:24:45.0089
        """
        hrs, mins, secs, ms = abs(self).as_tuple()
        return (
            f"{'-'*(self._total_ms < 0)}{hrs:02}:{mins:02}:{secs:02}"
            + f".{ms:0>6}".rstrip("0") * bool(ms)
        )

    @classmethod
    def from_canonical_format(cls, s: str, /) -> TimeDelta:
        """Create from the canonical string representation.

        Inverse of :meth:`canonical_format`

        Example
        -------
        >>> TimeDelta.from_canonical_format("01:30:00")
        TimeDelta(01:30:00)

        Raises
        ------
        ValueError
            If the string does not match this exact format.
        """
        if not (match := _match_timedelta(s)):
            raise ValueError(
                f"Could not parse as canonical format string: {s!r}"
            )
        sign, hours, mins, secs = match.groups()
        return cls(
            microseconds=(-1 if sign == "-" else 1)
            * (
                int(hours) * 3_600_000_000
                + int(mins) * 60_000_000
                + round(float(secs) * 1_000_000)
            )
        )

    __str__ = canonical_format

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
        hrs, mins, secs, ms = self.as_tuple()
        seconds = f"{secs + ms / 1_000_000:f}".rstrip("0") if ms else str(secs)
        return "PT" + (
            (
                f"{hrs}H" * bool(hrs)
                + f"{mins}M" * bool(mins)
                + f"{seconds}S" * bool(secs or ms)
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
        parsed = DateTimeDelta.from_common_iso8601(s)
        if parsed._date_part:
            raise ValueError(
                "Could not parse as canonical format "
                f"or common ISO 8601 string: {s!r}"
            )
        return parsed._time_part

    def py_timedelta(self) -> _timedelta:
        """Convert to a :class:`~datetime.timedelta`

        Inverse of :meth:`from_py_timedelta`

        Example
        -------
        >>> d = TimeDelta(hours=1, minutes=30)
        >>> d.py_timedelta()
        timedelta(seconds=5400)
        """
        return _timedelta(microseconds=self._total_ms)

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

    def as_tuple(self) -> tuple[int, int, int, int]:
        """Convert to a tuple of (hours, minutes, seconds, microseconds)

        Example
        -------
        >>> d = TimeDelta(hours=1, minutes=30, microseconds=5_000_090)
        >>> d.as_tuple()
        (1, 30, 5, 90)
        """
        hours, rem = divmod(abs(self._total_ms), 3_600_000_000)
        mins, rem = divmod(rem, 60_000_000)
        secs, ms = divmod(rem, 1_000_000)
        return (
            (hours, mins, secs, ms)
            if self._total_ms >= 0
            else (-hours, -mins, -secs, -ms)
        )

    def __repr__(self) -> str:
        return f"TimeDelta({self})"

    @no_type_check
    def __reduce__(self):
        return _unpkl_tdelta, (self._total_ms,)


# A separate unpickling function allows us to make backwards-compatible changes
# to the pickling format in the future
@no_type_check
def _unpkl_tdelta(ms):
    return TimeDelta(microseconds=ms)


TimeDelta.ZERO = TimeDelta()


class DateDelta(_ImmutableBase):
    """A duration of time consisting of calendar units
    (years, months, weeks, and days)
    """

    __slots__ = ("_years", "_months", "_weeks", "_days")

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
        self._years = years
        self._months = months
        self._weeks = weeks
        self._days = days

    @property
    def years(self) -> int:
        return self._years

    @property
    def months(self) -> int:
        return self._months

    @property
    def weeks(self) -> int:
        return self._weeks

    @property
    def days(self) -> int:
        return self._days

    # Hiding __eq__ from mypy ensures that --strict-equality works
    if not TYPE_CHECKING:  # pragma: no branch

        def __eq__(self, other: object) -> bool:
            """Compare for equality of all fields

            Note
            ----
            DateDeltas are equal if they have the same values for all fields.
            No normalization is done, so "7 days" is not equal to "1 week".

            Example
            -------
            >>> p = DateDelta(weeks=1, days=11, years=0)
            >>> p == DateDelta(weeks=1, days=11)
            True
            >>> # same delta, but different field values
            >>> p == DateDelta(weeks=2, days=4)
            False
            """
            if not isinstance(other, DateDelta):
                return NotImplemented
            return (
                self._years == other._years
                and self._months == other._months
                and self._weeks == other._weeks
                and self._days == other._days
            )

    def __hash__(self) -> int:
        return hash((self._years, self._months, self._weeks, self._days))

    def __bool__(self) -> bool:
        """True if any field is non-zero

        Example
        -------
        >>> bool(DateDelta())
        False
        >>> bool(DateDelta(days=-1))
        True
        """
        return bool(self._years or self._months or self._weeks or self._days)

    if TYPE_CHECKING:

        def replace(
            self,
            *,
            years: int | _UNSET = _UNSET(),
            months: int | _UNSET = _UNSET(),
            weeks: int | _UNSET = _UNSET(),
            days: int | _UNSET = _UNSET(),
        ) -> DateDelta: ...

    else:

        def replace(self, **kwargs) -> DateDelta:
            """Create a new instance with the given fields replaced.

            Example
            -------
            >>> p = DateDelta(years=1, months=2)
            >>> p.replace(years=2)
            DateDelta(P2Y2M)
            """
            return DateDelta(
                years=kwargs.get("years", self._years),
                months=kwargs.get("months", self._months),
                weeks=kwargs.get("weeks", self._weeks),
                days=kwargs.get("days", self._days),
            )

    def __repr__(self) -> str:
        return f"DateDelta({self})"

    def __neg__(self) -> DateDelta:
        """Negate each field

        Example
        -------
        >>> p = DateDelta(weeks=2, days=-3)
        >>> -p
        DateDelta(P-2W3DT)
        """
        return DateDelta(
            years=-self._years,
            months=-self._months,
            weeks=-self._weeks,
            days=-self._days,
        )

    def __pos__(self) -> DateDelta:
        """Return the value unchanged

        Example
        -------
        >>> p = DateDelta(weeks=2, days=-3)
        >>> +p
        DateDelta(P2W-3D)
        """
        return self

    def __mul__(self, other: int) -> DateDelta:
        """Multiply each field by a round number

        Example
        -------
        >>> p = DateDelta(years=1, weeks=2)
        >>> p * 2
        DateDelta(P2Y4W)
        """
        if not isinstance(other, int):
            return NotImplemented
        return DateDelta(
            years=self._years * other,
            months=self._months * other,
            weeks=self._weeks * other,
            days=self._days * other,
        )

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
        >>> p + DateDelta(weeks=1, days=-4)
        DateDelta(P1M3W-4D)
        """
        if isinstance(other, DateDelta):
            return DateDelta(
                years=self._years + other._years,
                months=self._months + other._months,
                weeks=self._weeks + other._weeks,
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
        DateDelta(P2W1D)
        """
        if isinstance(other, DateDelta):
            return DateDelta(
                years=self._years - other._years,
                months=self._months - other._months,
                weeks=self._weeks - other._weeks,
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
        """The absolute value of each field

        Example
        -------
        >>> p = DateDelta(weeks=-2, days=3)
        >>> abs(p)
        DateDelta(P2W3D)
        """
        return DateDelta(
            years=abs(self._years),
            months=abs(self._months),
            weeks=abs(self._weeks),
            days=abs(self._days),
        )

    def canonical_format(self) -> str:
        """The delta in canonical format.

        The canonical string format is:

        .. code-block:: text

            P(nY)(nM)(nW)(nD)

        For example:

        .. code-block:: text

            P1D
            P2M
            P1Y2M-3W4D

        Example
        -------
        >>> p = DateDelta(years=1, months=2, weeks=3, days=11)
        >>> p.canonical_format()
        'P1Y2M3W11D'
        >>> DateDelta().canonical_format()
        'P0D'
        """
        date = (
            f"{self._years}Y" * bool(self._years),
            f"{self._months}M" * bool(self._months),
            f"{self._weeks}W" * bool(self._weeks),
            f"{self._days}D" * bool(self._days),
        )
        return "P" + ("".join(date) or "0D")

    @classmethod
    def from_canonical_format(cls, s: str, /) -> DateDelta:
        """Create from the canonical string representation.

        Inverse of :meth:`canonical_format`

        Example
        -------
        >>> DateDelta.from_canonical_format("1Y2M-3W4D")
        DateDelta(P1Y2M-3W4D)
        """
        return cls.from_common_iso8601(s)

    __str__ = canonical_format

    def common_iso8601(self) -> str:
        """Format as the *popular interpretation* of the ISO 8601 duration format.
        May not strictly adhere to (all versions of) the standard.
        See :ref:`here <iso8601-durations>` for more information.

        Inverse of :meth:`from_common_iso8601`

        Example
        -------
        >>> DateDelta(weeks=1, days=11).common_iso8601()
        'P1W11D'
        """
        return self.canonical_format()

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

        Note
        ----
        Any duration with a non-zero time part is considered invalid.
        ``PT0S`` is valid, but ``P3DT1H`` is not.

        """
        full_delta = DateTimeDelta.from_canonical_format(s)
        if full_delta.time_part:
            raise ValueError(
                "Could not parse as canonical format "
                f"or common ISO 8601 string: {s!r}"
            )
        return full_delta.date_part

    def as_tuple(self) -> tuple[int, int, int, int]:
        """Convert to a tuple of (years, months, weeks, days)

        Example
        -------
        >>> p = DateDelta(weeks=2, days=3)
        >>> p.as_tuple()
        (0, 0, 2, 3)
        """
        return self._years, self._months, self._weeks, self._days

    @no_type_check
    def __reduce__(self):
        return (
            _unpkl_ddelta,
            (self._years, self._months, self._weeks, self._days),
        )


# A separate unpickling function allows us to make backwards-compatible changes
# to the pickling format in the future
@no_type_check
def _unpkl_ddelta(y, m, w, d):
    return DateDelta(years=y, months=m, weeks=w, days=d)


DateDelta.ZERO = DateDelta()
TimeDelta._date_part = DateDelta.ZERO


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
        microseconds: int = 0,
    ) -> None:
        self._date_part = DateDelta(
            years=years, months=months, weeks=weeks, days=days
        )
        self._time_part = TimeDelta(
            hours=hours,
            minutes=minutes,
            seconds=seconds,
            microseconds=microseconds,
        )

    ZERO: ClassVar[DateTimeDelta]
    """A delta of zero"""

    @property
    def date_part(self) -> DateDelta:
        return self._date_part

    @property
    def time_part(self) -> TimeDelta:
        return self._time_part

    def __eq__(self, other: object) -> bool:
        """Compare for equality

        Example
        -------
        >>> d = DateTimeDelta(
        ...     weeks=1,
        ...     days=11,
        ...     hours=4,
        ... )
        >>> d == DateTimeDelta(
        ...     weeks=1,
        ...     days=11,
        ...     minutes=4 * 60,  # normalized
        ... )
        True
        >>> d == DateTimeDelta(
        ...     weeks=2,
        ...     days=4,  # not normalized
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
        new = _object_new(DateTimeDelta)
        if isinstance(other, DateTimeDelta):
            new._date_part = self._date_part - other._date_part
            new._time_part = self._time_part - other._time_part
        elif isinstance(other, TimeDelta):
            new._date_part = self._date_part
            new._time_part = self._time_part - other
        elif isinstance(other, DateDelta):
            new._date_part = self._date_part - other
            new._time_part = self._time_part
        else:
            return NotImplemented
        return new

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
        new = _object_new(DateTimeDelta)
        new._date_part = self._date_part * other
        new._time_part = self._time_part * other
        return new

    def __neg__(self) -> DateTimeDelta:
        """Negate the delta

        Example
        -------
        >>> d = DateTimeDelta(weeks=1, days=-11, hours=4)
        >>> -d
        DateTimeDelta(P-1W11DT-4H)
        """
        new = _object_new(DateTimeDelta)
        new._date_part = -self._date_part
        new._time_part = -self._time_part
        return new

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

    def canonical_format(self) -> str:
        """The delta in canonical format.

        Example
        -------
        >>> d = DateTimeDelta(
        ...     weeks=1,
        ...     days=11,
        ...     hours=4,
        ... )
        >>> d.canonical_format()
        'P1W11DT4H'
        """
        date = self._date_part.common_iso8601()[1:] * bool(self._date_part)
        time = self._time_part.common_iso8601()[1:] * bool(self._time_part)
        return "P" + ((date + time) or "0D")

    __str__ = canonical_format

    def __repr__(self) -> str:
        return f"DateTimeDelta({self})"

    @classmethod
    def from_canonical_format(cls, s: str, /) -> DateTimeDelta:
        """Create from the canonical string representation.
        Inverse of :meth:`canonical_format`

        Examples:

        .. code-block:: text

           P4D        # 4 days
           PT4H       # 4 hours
           PT3M40.5   # 3 minutes and 40.5 seconds
           P1W11DT4H  # 1 week, 11 days, and 4 hours
           PT-7H4M    # -7 hours and +4 minutes (-6:56:00)
           -PT7H4M    # -7 hours and -4 minutes (-7:04:00)
           -PT-7H+4M  # +7 hours and -4 minutes (-6:56:00)


        Example
        -------
        >>> DateTimeDelta.from_canonical_format("P1W11DT4H")
        DateTimeDelta(weeks=1, days=11, hours=4)

        Raises
        ------
        ValueError
            If the string does not match this exact format.
        """
        if not (match := _match_datetimedelta(s)) or s == "P":
            raise ValueError(
                "Could not parse as canonical format "
                f"or common ISO 8601 string: {s!r}"
            )
        sign, years, months, weeks, days, hours, minutes, seconds = (
            match.groups()
        )
        parsed = cls(
            years=int(years or 0),
            months=int(months or 0),
            weeks=int(weeks or 0),
            days=int(days or 0),
            hours=float(hours or 0),
            minutes=float(minutes or 0),
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
        return self.canonical_format()

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
        return cls.from_canonical_format(s)

    def as_tuple(self) -> tuple[int, int, int, int, int, int, int, int]:
        """Convert to a tuple of (years, months, weeks, days, hours,
        minutes, seconds, microseconds)

        Example
        -------
        >>> d = DateTimeDelta(weeks=1, days=11, hours=4)
        >>> d.as_tuple()
        (0, 0, 1, 11, 4, 0, 0, 0)
        """
        return self._date_part.as_tuple() + self._time_part.as_tuple()

    @no_type_check
    def __reduce__(self):
        return (
            _unpkl_dtdelta,
            self._date_part.as_tuple() + (self._time_part._total_ms,),
        )


# A separate unpickling function allows us to make backwards-compatible changes
# to the pickling format in the future
@no_type_check
def _unpkl_dtdelta(y, m, w, d, ms):
    new = _object_new(DateTimeDelta)
    new._date_part = DateDelta(years=y, months=m, weeks=w, days=d)
    new._time_part = TimeDelta(microseconds=ms)
    return new


DateTimeDelta.ZERO = DateTimeDelta()
Delta = Union[DateTimeDelta, TimeDelta, DateDelta]
_TDateTime = TypeVar("_TDateTime", bound="_DateTime")


class _DateTime(_ImmutableBase, ABC):
    """Encapsulates behavior common to all datetimes. Not for public use."""

    __slots__ = ("_py_dt",)
    _py_dt: _datetime

    if TYPE_CHECKING or SPHINX_BUILD:

        @property
        def year(self) -> int: ...

        @property
        def month(self) -> int: ...

        @property
        def day(self) -> int: ...

        @property
        def hour(self) -> int: ...

        @property
        def minute(self) -> int: ...

        @property
        def second(self) -> int: ...

        @property
        def microsecond(self) -> int: ...

    else:
        # Defining properties this way is faster than declaring a `def`,
        # but the type checker doesn't like it.
        year = property(attrgetter("_py_dt.year"))
        month = property(attrgetter("_py_dt.month"))
        day = property(attrgetter("_py_dt.day"))
        hour = property(attrgetter("_py_dt.hour"))
        minute = property(attrgetter("_py_dt.minute"))
        second = property(attrgetter("_py_dt.second"))
        microsecond = property(attrgetter("_py_dt.microsecond"))

    def date(self) -> Date:
        """The date part of the datetime

        Example
        -------
        >>> d = UTCDateTime(2021, 1, 2, 3, 4, 5)
        >>> d.date()
        Date(2021-01-02)

        To perform the inverse, use :meth:`Date.at` and a method
        like :meth:`~NaiveDateTime.assume_utc` or
        :meth:`~NaiveDateTime.assume_zoned`:

        >>> date.at(time).assume_zoned("Europe/London")
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
        :meth:`~NaiveDateTime.assume_zoned`:

        >>> time.on(date).assume_utc()
        """
        return Time.from_py_time(self._py_dt.time())

    @abstractmethod
    def canonical_format(self, sep: Literal[" ", "T"] = "T") -> str:
        """Format as the canonical string representation. Each
        subclass has a different format. See the documentation for
        the subclass for more information.
        Inverse of :meth:`from_canonical_format`.
        """

    def __str__(self) -> str:
        """Same as :meth:`canonical_format` with ``sep=" "``"""
        return self.canonical_format(" ")

    @classmethod
    @abstractmethod
    def from_canonical_format(cls: type[_TDateTime], s: str, /) -> _TDateTime:
        """Create an instance from the canonical string representation,
        which is different for each subclass.

        Inverse of :meth:`__str__` and :meth:`canonical_format`.

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
        """Get the underlying :class:`~datetime.datetime` object"""
        return self._py_dt

    if not TYPE_CHECKING and SPHINX_BUILD:  # pragma: no cover

        @abstractmethod
        def replace(self: _TDateTime, /, **kwargs) -> _TDateTime:
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
        cls: type[_TDateTime], d: _datetime, /
    ) -> _TDateTime:
        self = _object_new(cls)
        self._py_dt = d
        return self


class _AwareDateTime(_DateTime):
    """Common behavior for all aware datetime types (:class:`UTCDateTime`,
    :class:`OffsetDateTime`, :class:`ZonedDateTime` and :class:`LocalSystemDateTime`).

    Not for public use.
    """

    __slots__ = ()

    if TYPE_CHECKING or SPHINX_BUILD:

        def timestamp(self) -> float:
            """The UNIX timestamp for this datetime.

            Each subclass also defines an inverse ``from_timestamp`` method,
            which may require additional arguments.

            Example
            -------
            >>> UTCDateTime(1970, 1, 1).timestamp()
            0.0
            >>> ts = 1_123_000_000
            >>> UTCDateTime.from_timestamp(ts).timestamp() == ts
            True
            """
            return self._py_dt.timestamp()

    else:
        timestamp = property(attrgetter("_py_dt.timestamp"))

    @property
    @abstractmethod
    def offset(self) -> TimeDelta:
        """The UTC offset of the datetime"""

    @abstractmethod
    def as_utc(self) -> UTCDateTime:
        """Convert into an equivalent UTCDateTime.
        The result will always represent the same moment in time.
        """

    @overload
    @abstractmethod
    def as_offset(self, /) -> OffsetDateTime: ...

    @overload
    @abstractmethod
    def as_offset(self, offset: int | TimeDelta, /) -> OffsetDateTime: ...

    @abstractmethod
    def as_offset(
        self, offset: int | TimeDelta | None = None, /
    ) -> OffsetDateTime:
        """Convert into an equivalent OffsetDateTime.
        Optionally, specify the offset to use.
        The result will always represent the same moment in time.
        """

    def as_zoned(self, tz: str, /) -> ZonedDateTime:
        """Convert into an equivalent ZonedDateTime.
        The result will always represent the same moment in time.

        Raises
        ------
        ~zoneinfo.ZoneInfoNotFoundError
            If the timezone ID is not found in the IANA database.
        """
        return ZonedDateTime._from_py_unchecked(
            self._py_dt.astimezone(ZoneInfo(tz))
        )

    def as_local(self) -> LocalSystemDateTime:
        """Convert into a an equivalent LocalSystemDateTime.
        The result will always represent the same moment in time.
        """
        return LocalSystemDateTime._from_py_unchecked(self._py_dt.astimezone())

    def naive(self) -> NaiveDateTime:
        """Convert into a naive datetime, dropping all timezone information

        As an inverse, :class:`NaiveDateTime` has methods
        :meth:`~NaiveDateTime.assume_utc`, :meth:`~NaiveDateTime.assume_offset`
        , :meth:`~NaiveDateTime.assume_zoned`, and :meth:`~NaiveDateTime.assume_local`
        which may require additional arguments.
        """
        return NaiveDateTime._from_py_unchecked(
            self._py_dt.replace(tzinfo=None)
        )

    # Hiding __eq__ from mypy ensures that --strict-equality works
    if not TYPE_CHECKING:  # pragma: no branch

        @abstractmethod
        def __eq__(self, other: object) -> bool:
            """Check if two datetimes represent at the same moment in time

            ``a == b`` is equivalent to ``a.as_utc() == b.as_utc()``

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

        ``a < b`` is equivalent to ``a.as_utc() < b.as_utc()``

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

        ``a <= b`` is equivalent to ``a.as_utc() <= b.as_utc()``

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

        ``a > b`` is equivalent to ``a.as_utc() > b.as_utc()``

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

        ``a >= b`` is equivalent to ``a.as_utc() >= b.as_utc()``

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

            ``a - b`` is equivalent to ``a.as_utc() - b.as_utc()``

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
    The canonical string format is:

    .. code-block:: text

        YYYY-MM-DDTHH:MM:SS(.ffffff)Z

    This format is both RFC 3339 and ISO 8601 compliant.

    Note
    ----
    The underlying :class:`~datetime.datetime` object is always timezone-aware
    and has a fixed :attr:`~datetime.UTC` tzinfo.
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
        microsecond: int = 0,
    ) -> None:
        self._py_dt = _datetime(
            year, month, day, hour, minute, second, microsecond, _UTC
        )

    @classmethod
    def now(cls) -> UTCDateTime:
        """Create an instance from the current time"""
        return cls._from_py_unchecked(_datetime.now(_UTC))

    def canonical_format(self, sep: Literal[" ", "T"] = "T") -> str:
        if sep not in (" ", "T"):
            raise ValueError("sep must be ' ' or 'T'")
        return f"{self._py_dt.isoformat(sep)[:-6]}Z"

    @classmethod
    def from_canonical_format(cls, s: str, /) -> UTCDateTime:
        if not _match_utc_str(s):
            raise ValueError(
                f"Could not parse as canonical format string: {s!r}"
            )
        return cls._from_py_unchecked(_fromisoformat_utc(s))

    @classmethod
    def from_timestamp(cls, i: float, /) -> UTCDateTime:
        """Create an instance from a UNIX timestamp.
        The inverse of :meth:`~_AwareDateTime.timestamp`.

        Example
        -------
        >>> UTCDateTime.from_timestamp(0) == UTCDateTime(1970, 1, 1)
        >>> d = UTCDateTime.from_timestamp(1_123_000_000.45)
        UTCDateTime(2004-08-02T16:26:40.45Z)
        >>> UTCDateTime.from_timestamp(d.timestamp()) == d
        True
        """
        return cls._from_py_unchecked(_fromtimestamp(i, _UTC))

    @classmethod
    def from_py_datetime(cls, d: _datetime, /) -> UTCDateTime:
        if d.tzinfo is not _UTC:
            raise ValueError(
                "Can only create UTCDateTime from UTC datetime, "
                f"got datetime with tzinfo={d.tzinfo!r}"
            )
        return cls._from_py_unchecked(d)

    offset = TimeDelta.ZERO

    def with_date(self, date: Date, /) -> UTCDateTime:
        """Create a new instance with the date replaced

        Example
        -------
        >>> d = UTCDateTime(2020, 8, 15, hour=23)
        >>> d.with_date(Date(2021, 1, 1))
        UTCDateTime(2021-01-01T23:00:00Z)
        """
        return self._from_py_unchecked(
            _datetime.combine(date._py_date, self._py_dt.timetz())
        )

    if TYPE_CHECKING:  # pragma: no branch
        # We could have used typing.Unpack, but that's only available
        # in Python 3.11+ or with typing_extensions.
        def replace(
            self,
            *,
            year: int | _UNSET = _UNSET(),
            month: int | _UNSET = _UNSET(),
            day: int | _UNSET = _UNSET(),
            hour: int | _UNSET = _UNSET(),
            minute: int | _UNSET = _UNSET(),
            second: int | _UNSET = _UNSET(),
            microsecond: int | _UNSET = _UNSET(),
        ) -> UTCDateTime: ...

    else:

        def replace(self, /, **kwargs) -> UTCDateTime:
            if not _no_tzinfo_or_fold(kwargs):
                raise TypeError("tzinfo and fold are not allowed arguments")
            return self._from_py_unchecked(self._py_dt.replace(**kwargs))

        # Defining properties this way is faster than declaring a `def`,
        # but the type checker doesn't like it.
        __hash__ = property(attrgetter("_py_dt.__hash__"))

        # Hiding __eq__ from mypy ensures that --strict-equality works
        def __eq__(self, other: object) -> bool:
            if not isinstance(
                other, (UTCDateTime, OffsetDateTime, LocalSystemDateTime)
            ):
                return NotImplemented
            return self._py_dt == other._py_dt

    MIN: ClassVar[UTCDateTime]
    MAX: ClassVar[UTCDateTime]

    def exact_eq(self, other: UTCDateTime, /) -> bool:
        return self._py_dt == other._py_dt

    def __lt__(self, other: _AwareDateTime) -> bool:
        if not isinstance(other, _AwareDateTime):
            return NotImplemented
        return self._py_dt < other._py_dt

    def __le__(self, other: _AwareDateTime) -> bool:
        if not isinstance(other, _AwareDateTime):
            return NotImplemented
        return self._py_dt <= other._py_dt

    def __gt__(self, other: _AwareDateTime) -> bool:
        if not isinstance(other, _AwareDateTime):
            return NotImplemented
        return self._py_dt > other._py_dt

    def __ge__(self, other: _AwareDateTime) -> bool:
        if not isinstance(other, _AwareDateTime):
            return NotImplemented
        return self._py_dt >= other._py_dt

    def add(
        self,
        *,
        years: int = 0,
        months: int = 0,
        weeks: int = 0,
        days: int = 0,
        hours: int = 0,
        minutes: int = 0,
        seconds: int = 0,
        microseconds: int = 0,
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
        return self + DateTimeDelta(
            years=years,
            months=months,
            weeks=weeks,
            days=days,
            hours=hours,
            minutes=minutes,
            seconds=seconds,
            microseconds=microseconds,
        )

    def subtract(
        self,
        *,
        years: int = 0,
        months: int = 0,
        weeks: int = 0,
        days: int = 0,
        hours: int = 0,
        minutes: int = 0,
        seconds: int = 0,
        microseconds: int = 0,
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
        return self - DateTimeDelta(
            years=years,
            months=months,
            weeks=weeks,
            days=days,
            hours=hours,
            minutes=minutes,
            seconds=seconds,
            microseconds=microseconds,
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
            return self._from_py_unchecked(
                _datetime.combine(
                    (self.date() + delta._date_part)._py_date,
                    self._py_dt.timetz(),
                )
                + delta._time_part.py_timedelta()
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
            return TimeDelta.from_py_timedelta(self._py_dt - other._py_dt)
        elif isinstance(other, (TimeDelta, DateDelta, DateTimeDelta)):
            return self + -other
        return NotImplemented

    def as_utc(self) -> UTCDateTime:
        return self

    @overload
    def as_offset(self, /) -> OffsetDateTime: ...

    @overload
    def as_offset(self, offset: int | TimeDelta, /) -> OffsetDateTime: ...

    def as_offset(
        self, offset: int | TimeDelta | None = None, /
    ) -> OffsetDateTime:
        return OffsetDateTime._from_py_unchecked(
            self._py_dt
            if offset is None
            else self._py_dt.astimezone(_load_offset(offset))
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
        return cls._from_py_unchecked(parsed)

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

        >>> # Error: nonzero offset. Use OffsetDateTime.from_rfc2822() instead
        >>> UTCDateTime.from_rfc2822("Sat, 15 Aug 2020 23:12:00 +0200")


        Warning
        -------
        * Nonzero offsets will not be implicitly converted to UTC.
          Use :meth:`OffsetDateTime.from_rfc2822` if you'd like to
          parse an RFC 2822 string with a nonzero offset.
        """
        try:
            parsed = _parse_rfc2822(s)
            # Nested ifs to keep happy path fast
            if parsed.tzinfo is not _UTC:
                if parsed.tzinfo is None:
                    if "-0000" not in s:
                        raise ValueError(
                            "RFC 2822 string must have a UTC offset"
                        )
                    parsed = parsed.replace(tzinfo=_UTC)
                else:
                    raise ValueError(
                        "RFC 2822 string can't have nonzero offset to be parsed as UTC"
                    )
            return cls._from_py_unchecked(parsed)
        except ValueError as e:
            raise ValueError(f"Cannot parse as RFC 2822 string: {s!r}") from e

    def rfc3339(self) -> str:
        """Format as an RFC 3339 string

        For UTCDateTime, equivalent to :meth:`~_DateTime.canonical_format`.
        Inverse of :meth:`from_rfc3339`.

        Example
        -------
        >>> UTCDateTime(2020, 8, 15, hour=23, minute=12).rfc3339()
        "2020-08-15T23:12:00Z"
        """
        return f"{self._py_dt.isoformat()[:-6]}Z"

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
        return cls._from_py_unchecked(_parse_utc_rfc3339(s))

    def common_iso8601(self) -> str:
        """Format as a common ISO 8601 string.

        For this class, equivalent to :meth:`rfc3339`.

        Example
        -------
        >>> UTCDateTime(2020, 8, 15, hour=23, minute=12).common_iso8601()
        "2020-08-15T23:12:00Z"
        """
        return f"{self._py_dt.isoformat()[:-6]}Z"

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
        try:
            if s[10] != "T" or s.endswith(("z", "-00:00")):
                raise ValueError("Input has a nonzero offset")
            return cls._from_py_unchecked(_parse_utc_rfc3339(s))
        except ValueError as e:
            raise ValueError(
                f"Could not parse as common ISO 8601 string: {s!r}"
            ) from e

    def __repr__(self) -> str:
        return f"UTCDateTime({self})"

    # a custom pickle implementation with a smaller payload
    def __reduce__(self) -> tuple[object, ...]:
        return (
            _unpkl_utc,
            self._py_dt.timetuple()[:6] + (self._py_dt.microsecond,),
        )


# A separate unpickling function allows us to make backwards-compatible changes
# to the pickling format in the future
@no_type_check
def _unpkl_utc(*args) -> UTCDateTime:
    return UTCDateTime(*args)


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
    The canonical string format is:

    .. code-block:: text

        YYYY-MM-DDTHH:MM:SS(.ffffff)±HH:MM(:SS(.ffffff))

    For example:

    .. code-block:: text

        2020-08-15T12:08:30+01:00

    This format is both RFC 3339 and ISO 8601 compliant.

    Note
    ----
    The underlying :class:`~datetime.datetime` object is always timezone-aware
    and has a fixed :class:`datetime.timezone` tzinfo.
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
        microsecond: int = 0,
        *,
        offset: int | TimeDelta,
    ) -> None:
        self._py_dt = _datetime(
            year,
            month,
            day,
            hour,
            minute,
            second,
            microsecond,
            _load_offset(offset),
        )

    @classmethod
    def now(cls, offset: int | TimeDelta) -> OffsetDateTime:
        """Create an instance at the current time with the given offset"""
        return cls._from_py_unchecked(_datetime.now(_load_offset(offset)))

    def canonical_format(self, sep: Literal[" ", "T"] = "T") -> str:
        return self._py_dt.isoformat(sep)

    @classmethod
    def from_canonical_format(cls, s: str, /) -> OffsetDateTime:
        try:
            if not _match_offset_str(s):
                raise ValueError("Input seems malformed")
            # Catch errors thrown by _from_py_unchecked too
            return cls._from_py_unchecked(_fromisoformat(s))
        except ValueError as e:
            raise ValueError(
                f"Could not parse as canonical format string: {s!r}"
            ) from e

    @classmethod
    def from_timestamp(
        cls, i: float, /, offset: int | TimeDelta
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
        return cls._from_py_unchecked(_fromtimestamp(i, _load_offset(offset)))

    @classmethod
    def from_py_datetime(cls, d: _datetime, /) -> OffsetDateTime:
        if not isinstance(d.tzinfo, _timezone):
            raise ValueError(
                "Datetime's tzinfo is not a datetime.timezone, "
                f"got tzinfo={d.tzinfo!r}"
            )
        return cls._from_py_unchecked(d)

    if TYPE_CHECKING:
        # We could have used typing.Unpack, but that's only available
        # in Python 3.11+ or with typing_extensions.
        def replace(
            self,
            *,
            year: int | _UNSET = _UNSET(),
            month: int | _UNSET = _UNSET(),
            day: int | _UNSET = _UNSET(),
            hour: int | _UNSET = _UNSET(),
            minute: int | _UNSET = _UNSET(),
            second: int | _UNSET = _UNSET(),
            microsecond: int | _UNSET = _UNSET(),
            offset: int | TimeDelta | _UNSET = _UNSET(),
        ) -> OffsetDateTime: ...

    else:

        def replace(self, /, **kwargs) -> OffsetDateTime:
            if not _no_tzinfo_or_fold(kwargs):
                raise TypeError("tzinfo and fold are not allowed arguments")
            try:
                kwargs["tzinfo"] = _load_offset(kwargs.pop("offset"))
            except KeyError:
                pass
            return self._from_py_unchecked(self._py_dt.replace(**kwargs))

        __hash__ = property(attrgetter("_py_dt.__hash__"))

        # Hiding __eq__ from mypy ensures that --strict-equality works
        def __eq__(self, other: object) -> bool:
            if not isinstance(
                other, (UTCDateTime, OffsetDateTime, LocalSystemDateTime)
            ):
                return NotImplemented
            return self._py_dt == other._py_dt

    @property
    def offset(self) -> TimeDelta:
        # We know that offset is never None, because we set it in __init__
        return TimeDelta.from_py_timedelta(self._py_dt.utcoffset())  # type: ignore[arg-type]

    def exact_eq(self, other: OffsetDateTime, /) -> bool:
        # FUTURE: there's probably a faster way to do this
        return self == other and self.offset == other.offset

    def __lt__(self, other: _AwareDateTime) -> bool:
        if not isinstance(other, _AwareDateTime):
            return NotImplemented
        return self._py_dt < other._py_dt

    def __le__(self, other: _AwareDateTime) -> bool:
        if not isinstance(other, _AwareDateTime):
            return NotImplemented
        return self._py_dt <= other._py_dt

    def __gt__(self, other: _AwareDateTime) -> bool:
        if not isinstance(other, _AwareDateTime):
            return NotImplemented
        return self._py_dt > other._py_dt

    def __ge__(self, other: _AwareDateTime) -> bool:
        if not isinstance(other, _AwareDateTime):
            return NotImplemented
        return self._py_dt >= other._py_dt

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
            return TimeDelta.from_py_timedelta(self._py_dt - other._py_dt)
        return NotImplemented

    def as_utc(self) -> UTCDateTime:
        return UTCDateTime._from_py_unchecked(self._py_dt.astimezone(_UTC))

    @overload
    def as_offset(self, /) -> OffsetDateTime: ...

    @overload
    def as_offset(self, offset: int | TimeDelta, /) -> OffsetDateTime: ...

    def as_offset(
        self, offset: int | TimeDelta | None = None, /
    ) -> OffsetDateTime:
        return (
            self
            if offset is None
            else self._from_py_unchecked(
                self._py_dt.astimezone(_load_offset(offset))
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
        return cls._from_py_unchecked(parsed)

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
                "cannot be parsed as OffsetDateTime"
            )
        return cls._from_py_unchecked(parsed)

    def rfc3339(self) -> str:
        """Format as an RFC 3339 string

        For ``OffsetDateTime``, equivalent to
        :meth:`~_DateTime.canonical_format`
        and :meth:`~OffsetDateTime.common_iso8601`.
        Inverse of :meth:`from_rfc3339`.

        Example
        -------
        >>> OffsetDateTime(2020, 8, 15, hour=23, minute=12, offset=hours(4)).rfc3339()
        "2020-08-15T23:12:00+04:00"
        """
        return self._py_dt.isoformat()

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
        try:
            return cls._from_py_unchecked(_parse_rfc3339(s))
        except ValueError as e:
            raise ValueError(
                f"Could not parse as RFC3339 string: {s!r}"
            ) from e

    def common_iso8601(self) -> str:
        """Format in the commonly used ISO 8601 format.

        Inverse of :meth:`from_common_iso8601`.

        Note
        ----
        For ``OffsetDateTime``, equivalent to :meth:`~_DateTime.canonical_format`
        and :meth:`~OffsetDateTime.rfc3339`.

        Example
        -------
        >>> OffsetDateTime(2020, 8, 15, hour=23, offset=+3).common_iso8601()
        "2020-08-15T23:00:00+03:00"
        """
        return self._py_dt.isoformat()

    @classmethod
    def from_common_iso8601(cls, s: str, /) -> OffsetDateTime:
        """Parse a *popular version* of the ISO 8601 datetime format.

        Inverse of :meth:`common_iso8601`.

        Note
        ----
        While similar, this function behaves differently from
        :meth:`~_DateTime.from_canonical_format`
        or :meth:`~OffsetDateTime.from_rfc3339`.

        Example
        -------
        >>> OffsetDateTime.from_common_iso8601("2020-08-15T23:12:00+02:00")
        OffsetDateTime(2020-08-15 23:12:00+02:00)
        >>> # also valid:
        >>> OffsetDateTime.from_common_iso8601("2020-08-15T23:12:00Z")
        """
        try:
            if s[10] == "T" and not s.endswith(("-00:00", "z")):
                return cls.from_rfc3339(s)
            else:
                # Examine the string again to keep the above happy path fast
                if s[10] != "T":
                    raise ValueError("Input seems malformed: missing 'T' separator")
                if s.endswith("z"):
                    raise ValueError("Input has a trailing lowercase 'z'")
                if s.endswith("-00:00"):
                    raise ValueError("Input has forbidden offset '-00:00'")
        except ValueError as e:
            raise ValueError(
                f"Could not parse as common ISO 8601 string: {s!r}"
            ) from e

    def __repr__(self) -> str:
        return f"OffsetDateTime({self})"

    # a custom pickle implementation with a smaller payload
    def __reduce__(self) -> tuple[object, ...]:
        return (
            _unpkl_offset,
            self._py_dt.timetuple()[:6]
            + (
                self._py_dt.microsecond,
                self._py_dt.utcoffset().total_seconds(),  # type: ignore[union-attr]
            ),
        )


# A separate function is needed for unpickling, because the
# constructor doesn't accept positional offset argument as
# required by __reduce__.
# Also, it allows backwards-compatible changes to the pickling format.
def _unpkl_offset(
    year: int,
    month: int,
    day: int,
    hour: int,
    minute: int,
    second: int,
    microsecond: int,
    offset_secs: float,
) -> OffsetDateTime:
    return OffsetDateTime._from_py_unchecked(
        _datetime(
            year,
            month,
            day,
            hour,
            minute,
            second,
            microsecond,
            _timezone(_timedelta(seconds=offset_secs)),
        )
    )


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
    The canonical string format is:

    .. code-block:: text

       YYYY-MM-DDTHH:MM:SS(.ffffff)±HH:MM(:SS(.ffffff))[TIMEZONE ID]

    For example:

    .. code-block:: text

       2020-08-15T23:12:00+01:00[Europe/London]

    The offset is included to disambiguate cases where the same
    local time occurs twice due to DST transitions.
    If the offset is invalid for the system timezone,
    parsing will raise :class:`InvalidOffsetForZone`.

    This format is similar to those `used by other languages <https://tc39.es/proposal-temporal/docs/strings.html#iana-time-zone-names>`_,
    but it is *not* RFC 3339 or ISO 8601 compliant
    (these standards don't support timezone IDs.)
    Use :meth:`~_AwareDateTime.as_offset` first if you
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
        microsecond: int = 0,
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
                microsecond,
                zone := ZoneInfo(tz),
                fold=_as_fold(disambiguate),
            ),
            zone,
            disambiguate,
        )

    @classmethod
    def now(cls, tz: str) -> ZonedDateTime:
        """Create an instance from the current time in the given timezone"""
        return cls._from_py_unchecked(_datetime.now(ZoneInfo(tz)))

    def canonical_format(self, sep: Literal[" ", "T"] = "T") -> str:
        return (
            f"{self._py_dt.isoformat(sep)}"
            f"[{self._py_dt.tzinfo.key}]"  # type: ignore[union-attr]
        )

    @classmethod
    def from_canonical_format(cls, s: str, /) -> ZonedDateTime:
        if (match := _match_zoned_str(s)) is None:
            raise ValueError(
                f"Could not parse as canonical format string: {s!r}"
            )
        dt = _fromisoformat(match[1])
        offset = dt.utcoffset()
        dt = dt.replace(tzinfo=ZoneInfo(match[2]))
        if offset != dt.utcoffset():  # offset/zone mismatch: try other fold
            dt = dt.replace(fold=1)
            if dt.utcoffset() != offset:
                raise InvalidOffsetForZone()
        return cls._from_py_unchecked(dt)

    @classmethod
    def from_timestamp(cls, i: float, /, tz: str) -> ZonedDateTime:
        """Create an instace from a UNIX timestamp."""
        return cls._from_py_unchecked(_fromtimestamp(i, ZoneInfo(tz)))

    @classmethod
    def from_py_datetime(cls, d: _datetime, /) -> ZonedDateTime:
        if not isinstance(d.tzinfo, ZoneInfo):
            raise ValueError(
                "Can only create ZonedDateTime from ZoneInfo, "
                f"got datetime with tzinfo={d.tzinfo!r}"
            )
        if not _exists_in_tz(d):
            raise SkippedTime.for_timezone(d, d.tzinfo)
        return cls._from_py_unchecked(d)

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
            )
        )

    if TYPE_CHECKING:
        # We could have used typing.Unpack, but that's only available
        # in Python 3.11+ or with typing_extensions.
        def replace(
            self,
            *,
            year: int | _UNSET = _UNSET(),
            month: int | _UNSET = _UNSET(),
            day: int | _UNSET = _UNSET(),
            hour: int | _UNSET = _UNSET(),
            minute: int | _UNSET = _UNSET(),
            second: int | _UNSET = _UNSET(),
            microsecond: int | _UNSET = _UNSET(),
            tz: str | _UNSET = _UNSET(),
            disambiguate: Disambiguate | _UNSET = _UNSET(),
        ) -> ZonedDateTime: ...

    else:

        def replace(self, /, disambiguate="raise", **kwargs) -> ZonedDateTime:
            if not _no_tzinfo_or_fold(kwargs):
                raise TypeError("tzinfo and/or fold are not allowed arguments")
            try:
                kwargs["tzinfo"] = ZoneInfo(kwargs.pop("tz"))
            except KeyError:
                pass
            return self._from_py_unchecked(
                _resolve_ambuguity(
                    self._py_dt.replace(fold=_as_fold(disambiguate), **kwargs),
                    kwargs.get("tzinfo", self._py_dt.tzinfo),
                    disambiguate,
                )
            )

    if TYPE_CHECKING or SPHINX_BUILD:  # pragma: no cover

        @property
        def tz(self) -> str:
            """The timezone ID"""
            ...

    else:
        tz = property(attrgetter("_py_dt.tzinfo.key"))

    @property
    def offset(self) -> TimeDelta:
        return TimeDelta.from_py_timedelta(self._py_dt.utcoffset())  # type: ignore[arg-type]

    def __hash__(self) -> int:
        return hash(self._py_dt.astimezone(_UTC))

    # Hiding __eq__ from mypy ensures that --strict-equality works.
    if not TYPE_CHECKING:  # pragma: no branch

        def __eq__(self, other: object) -> bool:
            if not isinstance(other, _AwareDateTime):
                return NotImplemented

            # We can't rely on simple equality, because it isn't equal
            # between two datetimes with different timezones if one of the
            # datetimes needs fold to disambiguate it.
            # See peps.python.org/pep-0495/#aware-datetime-equality-comparison.
            # We want to avoid this legacy edge case, so we normalize to UTC.
            return self._py_dt.astimezone(_UTC) == other._py_dt.astimezone(
                _UTC
            )

    def exact_eq(self, other: ZonedDateTime, /) -> bool:
        return (
            self._py_dt.tzinfo is other._py_dt.tzinfo
            and self._py_dt.fold == other._py_dt.fold
            and self._py_dt == other._py_dt
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
            return self._from_py_unchecked(
                (
                    _datetime.combine(
                        (self.date() + delta._date_part)._py_date,
                        self._py_dt.timetz(),
                    ).astimezone(_UTC)
                    + delta._time_part.py_timedelta()
                ).astimezone(self._py_dt.tzinfo)
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
                self._py_dt.astimezone(_UTC) - other._py_dt
            )
        elif isinstance(other, (TimeDelta, DateDelta, DateTimeDelta)):
            return self + -other
        return NotImplemented

    def is_ambiguous(self) -> bool:
        """Whether the local time is ambiguous, e.g. due to a DST transition.

        Example
        -------
        >>> ZonedDateTime(2020, 8, 15, 23, tz="Europe/London", disambiguate="later").ambiguous()
        False
        >>> ZonedDateTime(2023, 10, 29, 2, 15, tz="Europe/Amsterdam", disambiguate="later").ambiguous()
        True
        """
        return self._py_dt.astimezone(_UTC) != self._py_dt

    def as_utc(self) -> UTCDateTime:
        return UTCDateTime._from_py_unchecked(self._py_dt.astimezone(_UTC))

    @overload
    def as_offset(self, /) -> OffsetDateTime: ...

    @overload
    def as_offset(self, offset: int | TimeDelta, /) -> OffsetDateTime: ...

    def as_offset(
        self, offset: int | TimeDelta | None = None, /
    ) -> OffsetDateTime:
        return OffsetDateTime._from_py_unchecked(
            self._py_dt.astimezone(
                # mypy doesn't know that offset is never None
                _timezone(self._py_dt.utcoffset())  # type: ignore[arg-type]
                if offset is None
                else _load_offset(offset)
            )
        )

    def as_zoned(self, tz: str, /) -> ZonedDateTime:
        return self._from_py_unchecked(self._py_dt.astimezone(ZoneInfo(tz)))

    def __repr__(self) -> str:
        return f"ZonedDateTime({self})"

    # a custom pickle implementation with a smaller payload
    def __reduce__(self) -> tuple[object, ...]:
        return (
            _unpkl_zoned,
            self._py_dt.timetuple()[:6]
            + (
                self._py_dt.microsecond,
                # We know that tzinfo is always a ZoneInfo, but mypy doesn't
                self._py_dt.tzinfo.key,  # type: ignore[union-attr]
                self._py_dt.fold,
            ),
        )


# A separate function is needed for unpickling, because the
# constructor doesn't accept positional tz and fold arguments as
# required by __reduce__.
# Also, it allows backwards-compatible changes to the pickling format.
def _unpkl_zoned(
    year: int,
    month: int,
    day: int,
    hour: int,
    minute: int,
    second: int,
    microsecond: int,
    tz: str,
    fold: Fold,
) -> ZonedDateTime:
    return ZonedDateTime._from_py_unchecked(
        _datetime(
            year,
            month,
            day,
            hour,
            minute,
            second,
            microsecond,
            ZoneInfo(tz),
            fold=fold,
        )
    )


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
    >>> alarm.as_utc()
    UTCDateTime(2024-03-31 04:00:00)
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
    The canonical string format is:

    .. code-block:: text

       YYYY-MM-DDTHH:MM:SS(.ffffff)±HH:MM(:SS(.ffffff))

    This format is both RFC 3339 and ISO 8601 compliant.

    Note
    ----
    The underlying :class:`~datetime.datetime` object has
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
        microsecond: int = 0,
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
                microsecond,
                fold=_as_fold(disambiguate),
            ),
            disambiguate,
        )

    @classmethod
    def now(cls) -> LocalSystemDateTime:
        """Create an instance from the current time"""
        return cls._from_py_unchecked(_datetime.now().astimezone(None))

    def canonical_format(self, sep: Literal[" ", "T"] = "T") -> str:
        return self._py_dt.isoformat(sep)

    @classmethod
    def from_canonical_format(cls, s: str, /) -> LocalSystemDateTime:
        try:
            if not _match_offset_str(s):
                raise ValueError("Input seems malformed")
            return cls._from_py_unchecked(_fromisoformat(s))
        except ValueError as e:
            raise ValueError(
                f"Could not parse as canonical format string: {s!r}"
            ) from e

    @classmethod
    def from_timestamp(cls, i: float, /) -> LocalSystemDateTime:
        """Create an instace from a UNIX timestamp.
        The inverse of :meth:`~_AwareDateTime.timestamp`.

        Example
        -------
        >>> # assuming system timezone is America/New_York
        >>> LocalSystemDateTime.from_timestamp(0)
        LocalSystemDateTime(1969-12-31T19:00:00-05:00)
        >>> LocalSystemDateTime.from_timestamp(1_123_000_000.45)
        LocalSystemDateTime(2005-08-12T12:26:40.45-04:00)
        >>> LocalSystemDateTime.from_timestamp(d.timestamp()) == d
        True
        """
        return cls._from_py_unchecked(_fromtimestamp(i).astimezone())

    @classmethod
    def from_py_datetime(cls, d: _datetime, /) -> LocalSystemDateTime:
        if not isinstance(d.tzinfo, _timezone):
            raise ValueError(
                "Can only create LocalSystemDateTime from a fixed-offset datetime, "
                f"got datetime with tzinfo={d.tzinfo!r}."
            )
        return cls._from_py_unchecked(d)

    def __repr__(self) -> str:
        return f"LocalSystemDateTime({self})"

    @property
    def offset(self) -> TimeDelta:
        return TimeDelta.from_py_timedelta(self._py_dt.utcoffset())  # type: ignore[arg-type]

    @property
    def tzname(self) -> str:
        """The name of the timezone as provided by the system, if known.
        Examples: ``"EST"`` or ``"CET"``.

        If not set, returns an empty string.

        .. attention::

           This is different from the IANA timezone ID.
           For example, ``"Europe/Paris"`` is the IANA tz ID
           that *observes* ``"CET"`` in the winter and ``"CEST"`` in the summer.
        """
        return (
            ""  # type: ignore[return-value]
            # ok, so this requires some explanation...
            # If `name` on `datetime.timezone` is not set,
            # a generic name (e.g. "UTC+2:00") is returned by tzname().
            # The only way to check if there is actually a name set
            # is to check if its repr includes a second parameter.
            # e.g. timezone(timedelta(hours=2), "CEST") has the name "CEST" and
            # timezone(timedelta(hours=2)) has no name
            if repr(self._py_dt.tzinfo).endswith("))")
            else self._py_dt.tzname()
        )

    if not TYPE_CHECKING:  # pragma: no branch

        def __eq__(self, other: object) -> bool:
            if not isinstance(
                other, (UTCDateTime, OffsetDateTime, LocalSystemDateTime)
            ):
                return NotImplemented
            return self._py_dt == other._py_dt

    def __lt__(self, other: _AwareDateTime) -> bool:
        if not isinstance(other, _AwareDateTime):
            return NotImplemented
        return self._py_dt < other._py_dt

    def __le__(self, other: _AwareDateTime) -> bool:
        if not isinstance(other, _AwareDateTime):
            return NotImplemented
        return self._py_dt <= other._py_dt

    def __gt__(self, other: _AwareDateTime) -> bool:
        if not isinstance(other, _AwareDateTime):
            return NotImplemented
        return self._py_dt > other._py_dt

    def __ge__(self, other: _AwareDateTime) -> bool:
        if not isinstance(other, _AwareDateTime):
            return NotImplemented
        return self._py_dt >= other._py_dt

    def exact_eq(self, other: LocalSystemDateTime) -> bool:
        return (
            self._py_dt == other._py_dt
            and self._py_dt.tzinfo == other._py_dt.tzinfo
        )

    if TYPE_CHECKING:
        # We could have used typing.Unpack, but that's only available
        # in Python 3.11+ or with typing_extensions.
        def replace(
            self,
            *,
            year: int | _UNSET = _UNSET(),
            month: int | _UNSET = _UNSET(),
            day: int | _UNSET = _UNSET(),
            hour: int | _UNSET = _UNSET(),
            minute: int | _UNSET = _UNSET(),
            second: int | _UNSET = _UNSET(),
            microsecond: int | _UNSET = _UNSET(),
            disambiguate: Disambiguate | _UNSET = _UNSET(),
        ) -> LocalSystemDateTime: ...

    else:

        def replace(
            self, /, disambiguate="raise", **kwargs
        ) -> LocalSystemDateTime:
            if not _no_tzinfo_or_fold(kwargs):
                raise TypeError("tzinfo and/or fold are not allowed arguments")
            return self._from_py_unchecked(
                _resolve_local_ambiguity(
                    self._py_dt.replace(
                        tzinfo=None, fold=_as_fold(disambiguate), **kwargs
                    ),
                    disambiguate,
                )
            )

        __hash__ = property(attrgetter("_py_dt.__hash__"))

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
            new_py_date = (self.date() + delta._date_part)._py_date
            return self._from_py_unchecked(
                _resolve_local_ambiguity(
                    (
                        self._py_dt
                        if new_py_date == self._py_dt.date()
                        else _datetime.combine(new_py_date, self._py_dt.time())
                    )
                    + delta._time_part.py_timedelta(),
                    "compatible",
                )
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
            return TimeDelta.from_py_timedelta(self._py_dt - other._py_dt)
        elif isinstance(other, (TimeDelta, DateDelta, DateTimeDelta)):
            return self + -other
        return NotImplemented

    def as_utc(self) -> UTCDateTime:
        return UTCDateTime._from_py_unchecked(self._py_dt.astimezone(_UTC))

    @overload
    def as_offset(self, /) -> OffsetDateTime: ...

    @overload
    def as_offset(self, offset: int | TimeDelta, /) -> OffsetDateTime: ...

    def as_offset(
        self, offset: int | TimeDelta | None = None, /
    ) -> OffsetDateTime:
        return OffsetDateTime._from_py_unchecked(
            self._py_dt
            if offset is None
            else self._py_dt.astimezone(_load_offset(offset))
        )

    def as_zoned(self, tz: str, /) -> ZonedDateTime:
        return ZonedDateTime._from_py_unchecked(
            self._py_dt.astimezone(ZoneInfo(tz))
        )

    def as_local(self) -> LocalSystemDateTime:
        return self._from_py_unchecked(self._py_dt.astimezone())

    # a custom pickle implementation with a smaller payload
    def __reduce__(self) -> tuple[object, ...]:
        return (
            _unpkl_local,
            self._py_dt.timetuple()[:6]
            + (
                self._py_dt.microsecond,
                self._py_dt.utcoffset().total_seconds(),  # type: ignore[union-attr]
                self._py_dt.tzname(),
            ),
        )


# A separate function is needed for unpickling, because the
# constructor doesn't accept positional fold arguments as
# required by __reduce__.
# Also, it allows backwards-compatible changes to the pickling format.
def _unpkl_local(
    year: int,
    month: int,
    day: int,
    hour: int,
    minute: int,
    second: int,
    microsecond: int,
    offset_secs: float,
    tzname: str,
) -> LocalSystemDateTime:
    # FUTURE: check that rounding of offset_secs doesn't cause issues
    return LocalSystemDateTime._from_py_unchecked(
        _datetime(
            year,
            month,
            day,
            hour,
            minute,
            second,
            microsecond,
            tzinfo=_timezone(_timedelta(seconds=offset_secs), tzname),
        )
    )


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
    The canonical string format is:

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
        microsecond: int = 0,
    ) -> None:
        self._py_dt = _datetime(
            year, month, day, hour, minute, second, microsecond
        )

    def canonical_format(self, sep: Literal[" ", "T"] = "T") -> str:
        return self._py_dt.isoformat(sep)

    @classmethod
    def from_canonical_format(cls, s: str, /) -> NaiveDateTime:
        if not _match_naive_str(s):
            raise ValueError(
                f"Could not parse as canonical format string: {s!r}"
            )
        return cls._from_py_unchecked(_fromisoformat(s))

    @classmethod
    def from_py_datetime(cls, d: _datetime, /) -> NaiveDateTime:
        if d.tzinfo is not None:
            raise ValueError(
                "Can only create NaiveDateTime from a naive datetime, "
                f"got datetime with tzinfo={d.tzinfo!r}"
            )
        return cls._from_py_unchecked(d)

    tzinfo: ClassVar[None] = None

    if TYPE_CHECKING:
        # We could have used typing.Unpack, but that's only available
        # in Python 3.11+ or with typing_extensions.
        def replace(
            self,
            *,
            year: int | _UNSET = _UNSET(),
            month: int | _UNSET = _UNSET(),
            day: int | _UNSET = _UNSET(),
            hour: int | _UNSET = _UNSET(),
            minute: int | _UNSET = _UNSET(),
            second: int | _UNSET = _UNSET(),
            microsecond: int | _UNSET = _UNSET(),
        ) -> NaiveDateTime: ...

    else:

        def replace(self, /, **kwargs) -> NaiveDateTime:
            if not _no_tzinfo_or_fold(kwargs):
                raise TypeError("tzinfo and fold are not allowed arguments")
            return self._from_py_unchecked(self._py_dt.replace(**kwargs))

        __hash__ = property(attrgetter("_py_dt.__hash__"))

        # Hiding __eq__ from mypy ensures that --strict-equality works
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
            return self._py_dt == other._py_dt

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
        """Add a duration to this datetime

        Example
        -------
        >>> d = NaiveDateTime(2020, 8, 15, hour=23, minute=12)
        >>> d + hours(24) + seconds(5)
        NaiveDateTime(2020-08-16 23:12:05)
        >>> d + years(3) + months(2) + days(1)
        NaiveDateTime(2023-10-16 23:12:00)
        """
        if isinstance(delta, (TimeDelta, DateDelta, DateTimeDelta)):
            return self._from_py_unchecked(
                _datetime.combine(
                    (self.date() + delta._date_part)._py_date,
                    self._py_dt.time(),
                )
                + delta._time_part.py_timedelta()
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
            return TimeDelta.from_py_timedelta(self._py_dt - other._py_dt)
        elif isinstance(other, (TimeDelta, DateDelta, DateTimeDelta)):
            return self + -other
        return NotImplemented

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
        return cls._from_py_unchecked(parsed)

    def assume_utc(self) -> UTCDateTime:
        """Assume the datetime is in UTC,
        creating a :class:`~whenever.UTCDateTime` instance.

        Example
        -------
        >>> NaiveDateTime(2020, 8, 15, 23, 12).assume_utc()
        UTCDateTime(2020-08-15 23:12:00Z)
        """
        return UTCDateTime._from_py_unchecked(self._py_dt.replace(tzinfo=_UTC))

    def assume_offset(self, offset: int | TimeDelta, /) -> OffsetDateTime:
        """Assume the datetime is in the given offset,
        creating a :class:`~whenever.OffsetDateTime` instance.

        Example
        -------
        >>> NaiveDateTime(2020, 8, 15, 23, 12).assume_offset(+2)
        OffsetDateTime(2020-08-15 23:12:00+02:00)
        """
        return OffsetDateTime._from_py_unchecked(
            self._py_dt.replace(tzinfo=_load_offset(offset))
        )

    def assume_zoned(
        self, tz: str, /, disambiguate: Disambiguate = "raise"
    ) -> ZonedDateTime:
        """Assume the datetime is in the given timezone,
        creating a :class:`~whenever.ZonedDateTime` instance.

        Example
        -------
        >>> NaiveDateTime(2020, 8, 15, 23, 12).assume_zoned("Europe/Amsterdam")
        ZonedDateTime(2020-08-15 23:12:00+02:00[Europe/Amsterdam])
        """
        return ZonedDateTime._from_py_unchecked(
            _resolve_ambuguity(
                self._py_dt.replace(
                    tzinfo=(zone := ZoneInfo(tz)), fold=_as_fold(disambiguate)
                ),
                zone,
                disambiguate,
            )
        )

    def assume_local(
        self, disambiguate: Disambiguate = "raise"
    ) -> LocalSystemDateTime:
        """Assume the datetime is in the system timezone,
        creating a :class:`~whenever.LocalSystemDateTime` instance.

        Example
        -------
        >>> # assuming system timezone is America/New_York
        >>> NaiveDateTime(2020, 8, 15, 23, 12).assume_local()
        LocalSystemDateTime(2020-08-15 23:12:00-04:00)
        """
        return LocalSystemDateTime._from_py_unchecked(
            _resolve_local_ambiguity(
                self._py_dt.replace(fold=_as_fold(disambiguate)),
                disambiguate,
            )
        )

    def __repr__(self) -> str:
        return f"NaiveDateTime({self})"

    def common_iso8601(self) -> str:
        """Format in the commonly used ISO 8601 format.

        Inverse of :meth:`from_common_iso8601`.

        Example
        -------
        >>> NaiveDateTime(2020, 8, 15, 23, 12).common_iso8601()
        '2020-08-15T23:12:00'
        """
        return self._py_dt.isoformat().rstrip("0")

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
        if len(s) > 26:
            raise ValueError(f"Not a valid common ISO 8601 string: {s!r}")
        parsed = _fromisoformat_naive(s)
        if parsed.tzinfo is not None:
            raise ValueError(
                f"Naive ISO 8601 string must not have an offset: {s!r}"
            )
        return cls._from_py_unchecked(parsed)

    # a custom pickle implementation with a smaller payload
    def __reduce__(self) -> tuple[object, ...]:
        return (
            _unpkl_naive,
            self._py_dt.timetuple()[:6] + (self._py_dt.microsecond,),
        )


# A separate unpickling function allows us to make backwards-compatible changes
# to the pickling format in the future
@no_type_check
def _unpkl_naive(*args) -> NaiveDateTime:
    return NaiveDateTime(*args)


class AmbiguousTime(Exception):
    """A datetime is unexpectedly ambiguous"""

    @staticmethod
    def for_timezone(d: _datetime, tz: ZoneInfo) -> AmbiguousTime:
        return AmbiguousTime(
            f"{d.replace(tzinfo=None)} is ambiguous " f"in timezone {tz.key}"
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
            f"{d.replace(tzinfo=None)} is skipped " f"in timezone {tz.key}"
        )

    @staticmethod
    def for_system_timezone(d: _datetime) -> SkippedTime:
        return SkippedTime(
            f"{d.replace(tzinfo=None)} is skipped in the system timezone"
        )


class InvalidOffsetForZone(ValueError):
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
    norm = dt.astimezone(_UTC).astimezone()
    # Non-existent times: they don't survive a UTC roundtrip
    if norm.replace(tzinfo=None) != dt:
        if disambiguate == "raise":
            raise SkippedTime.for_system_timezone(dt)
        elif _requires_flip(disambiguate):
            dt = dt.replace(fold=not dt.fold)
        # perform the normalisation, shifting away from non-existent times
        norm = dt.astimezone(_UTC).astimezone()
    # Ambiguous times: they're never equal to other timezones
    elif disambiguate == "raise" and norm != dt.replace(fold=1).astimezone(
        _UTC
    ):
        raise AmbiguousTime.for_system_timezone(dt)
    return norm


def _exists_in_tz(d: _datetime) -> bool:
    # non-existent datetimes don't survive a round-trip to UTC
    return d.astimezone(_UTC).astimezone(d.tzinfo) == d


def _load_offset(offset: int | TimeDelta, /) -> _timezone:
    return _timezone(
        _timedelta(hours=offset)
        if isinstance(offset, int)
        else offset.py_timedelta()
    )


# Helpers that pre-compute/lookup as much as possible
_UTC = _timezone.utc
_no_tzinfo_or_fold = {"tzinfo", "fold"}.isdisjoint
_object_new = object.__new__
_DATETIME_RE = r"\d{4}-\d{2}-\d{2}[T ]\d{2}:\d{2}:\d{2}(?:\.(?:\d{3}|\d{6}))?"
_OFFSET_RE = rf"{_DATETIME_RE}[+-]\d{{2}}:\d{{2}}(?::\d{{2}}(?:\.\d{{6}})?)?"
_match_utc_str = re.compile(rf"{_DATETIME_RE}Z").fullmatch
_match_naive_str = re.compile(_DATETIME_RE).fullmatch
_match_offset_str = re.compile(_OFFSET_RE).fullmatch
_match_zoned_str = re.compile(rf"({_OFFSET_RE})\[([^\]]+)\]").fullmatch
_fromisoformat = _datetime.fromisoformat
_fromtimestamp = _datetime.fromtimestamp
_match_utc_rfc3339 = re.compile(
    r"\d{4}-\d{2}-\d{2}.\d{2}:\d{2}:\d{2}(\.\d{1,6})?(?:[Zz]|[+-]00:00)"
).fullmatch
_match_rfc3339 = re.compile(
    r"\d{4}-\d{2}-\d{2}.\d{2}:\d{2}:\d{2}(\.\d{1,6})?(?:[Zz]|[+-]\d{2}:\d{2})"
).fullmatch
_match_datetimedelta = re.compile(
    r"([-+]?)P(?:([-+]?\d+)Y)?(?:([-+]?\d+)M)?(?:([-+]?\d+)W)?(?:([-+]?\d+)D)?"
    r"(?:T(?:([-+]?\d+)H)?(?:([-+]?\d+)M)?(?:([-+]?\d+(?:\.\d{1,6})?)?S)?)?"
).fullmatch
_match_timedelta = re.compile(
    r"([-+]?)(\d{2,}):([0-5]\d):([0-5]\d(?:\.\d{1,6})?)"
).fullmatch
_match_time = re.compile(
    r"([0-2]\d):([0-5]\d):([0-5]\d)(?:\.(\d{1,6}))?"
).fullmatch
# Before Python 3.11, fromisoformat() is less capable
if sys.version_info < (3, 11):  # pragma: no cover

    def _fromisoformat_utc(s: str) -> _datetime:
        return _fromisoformat(s[:-1]).replace(tzinfo=_UTC)

    def _fromisoformat_naive(s: str) -> _datetime:
        return _fromisoformat(s.ljust(26, "0") if len(s) > 20 else s)

    def _parse_rfc3339(s: str) -> _datetime:
        if not (m := _match_rfc3339(s)):
            raise ValueError(f"Could not parse as RFC3339 string: {s!r}")
        return _fromisoformat_extra(m, s)

    def _parse_utc_rfc3339(s: str) -> _datetime:
        if not (m := _match_utc_rfc3339(s)):
            raise ValueError(f"Could not parse as UTC RFC3339 string: {s!r}")
        return _fromisoformat_extra(m, s)

    def _fromisoformat_extra(m: re.Match[str], s: str) -> _datetime:
        # handle fractions that aren't exactly 3 or 6 digits
        if (fraction := m.group(1)) and len(fraction) not in (7, 4):
            s = (
                s[:19]
                + fraction.ljust(7, "0")
                + s[19 + len(fraction) :]  # noqa
            )
        # handle Z suffix
        if s.endswith(("Z", "z")):
            s = s[:-1] + "+00:00"
        return _fromisoformat(s)

    # assuming _match_time regex passed
    def _fromisoformat_time(s: str) -> _time:
        return (
            _time.fromisoformat(s.ljust(15, "0"))
            if "." in s
            else _time.fromisoformat(s)
        )

    def _parse_rfc2822(s: str) -> _datetime:
        try:
            return parsedate_to_datetime(s)
        except TypeError:
            if isinstance(s, str):
                raise ValueError(f"Invalid RFC2822 string: {s!r}")
            raise

else:
    _fromisoformat_utc = _fromisoformat
    _fromisoformat_time = _time.fromisoformat
    _fromisoformat_naive = _fromisoformat
    _parse_rfc2822 = parsedate_to_datetime

    def _parse_utc_rfc3339(s: str) -> _datetime:
        if not _match_utc_rfc3339(s):
            raise ValueError(f"Could not parse as UTC RFC3339 string: {s!r}")
        return _fromisoformat(s.upper())

    def _parse_rfc3339(s: str) -> _datetime:
        if not _match_rfc3339(s):
            raise ValueError(f"Could not parse as RFC3339 string: {s!r}")
        return _fromisoformat(s.upper())


UTCDateTime.MIN = UTCDateTime._from_py_unchecked(
    _datetime.min.replace(tzinfo=_UTC)
)
UTCDateTime.MAX = UTCDateTime._from_py_unchecked(
    _datetime.max.replace(tzinfo=_UTC)
)
NaiveDateTime.MIN = NaiveDateTime._from_py_unchecked(_datetime.min)
NaiveDateTime.MAX = NaiveDateTime._from_py_unchecked(_datetime.max)
Disambiguate = Literal["compatible", "earlier", "later", "raise"]
Fold = Literal[0, 1]
_as_fold: Callable[[Disambiguate], Fold] = {  # type: ignore[assignment]
    "compatible": 0,
    "earlier": 0,
    "later": 1,
    "raise": 0,
}.__getitem__


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


def microseconds(i: int, /) -> TimeDelta:
    """Create a :class:`TimeDelta` with the given number of microseconds.
    ``microseconds(1) == TimeDelta(microseconds=1)``
    """
    return TimeDelta(microseconds=i)
