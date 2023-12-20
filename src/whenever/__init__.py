from __future__ import annotations

import re
import sys
from abc import ABC, abstractmethod
from datetime import date as _date
from datetime import datetime as _datetime
from datetime import time as _time
from datetime import timedelta
from datetime import timezone as _timezone
from datetime import tzinfo as _tzinfo
from operator import attrgetter
from typing import (
    TYPE_CHECKING,
    Callable,
    ClassVar,
    Literal,
    TypeVar,
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

_UTC = _timezone.utc

__all__ = [
    "DateTime",
    "AwareDateTime",
    "UTCDateTime",
    "OffsetDateTime",
    "ZonedDateTime",
    "LocalDateTime",
    "NaiveDateTime",
    "hours",
    "minutes",
    "DoesntExistInZone",
    "Ambiguous",
    "InvalidOffsetForZone",
    "InvalidFormat",
]


class NOT_SET:
    """Sentinel value for when no value is given"""


_as_fold: Callable[[Literal["earlier", "later", "raise"]], Literal[0, 1]] = {  # type: ignore[assignment]
    "earlier": 0,
    "later": 1,
    "raise": 0,
}.__getitem__


_T = TypeVar("_T", bound="DateTime")


class DateTime(ABC):
    """Abstract base class for all datetime types"""

    __slots__ = ("_py_dt", "__weakref__")
    _py_dt: _datetime

    if TYPE_CHECKING or SPHINX_BUILD:

        @property
        def year(self) -> int:
            """The year"""
            ...

        @property
        def month(self) -> int:
            """The month"""
            ...

        @property
        def day(self) -> int:
            """The day"""
            ...

        @property
        def hour(self) -> int:
            """The hour"""
            ...

        @property
        def minute(self) -> int:
            """The minute"""
            ...

        @property
        def second(self) -> int:
            """The second"""
            ...

        @property
        def microsecond(self) -> int:
            """The microsecond"""
            ...

        def weekday(self) -> int:
            """The day of the week as an integer (Monday=0, Sunday=6)"""
            ...

        def date(self) -> _date:
            """The :class:`~datetime.date` part of the datetime"""
            ...

        def time(self) -> _time:
            """The :class:`~datetime.time` part of the datetime"""
            ...

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
        weekday = property(attrgetter("_py_dt.weekday"))
        date = property(attrgetter("_py_dt.date"))
        time = property(attrgetter("_py_dt.time"))

    resolution: ClassVar[timedelta] = _datetime.resolution
    """Alias for :attr:`datetime.datetime.resolution`"""

    @classmethod
    @abstractmethod
    def from_py(cls: type[_T], d: _datetime, /) -> _T:
        """Create an instance from a :class:`~datetime.datetime` object.
        Inverse of :meth:`py`."""

    @property
    @abstractmethod
    def py(self) -> _datetime:
        """Get the underlying :class:`~datetime.datetime` object"""

    @classmethod
    def _from_py_unchecked(cls: type[_T], d: _datetime, /) -> _T:
        self = _object_new(cls)
        self._py_dt = d
        return self

    # We don't need to copy, because it's immutable
    def __copy__(self: _T) -> _T:
        return self

    def __deepcopy__(self: _T, _: object) -> _T:
        return self


class AwareDateTime(DateTime):
    """Abstract base class for all aware datetime types"""

    __slots__ = ()

    if TYPE_CHECKING or SPHINX_BUILD:

        @property
        def tzinfo(self) -> _tzinfo | None:
            """The tzinfo of the underlying :class:`~datetime.datetime`"""
            ...

    else:
        tzinfo = property(attrgetter("_py_dt.tzinfo"))

    @property
    @abstractmethod
    def offset(self) -> timedelta:
        """The UTC offset of the datetime"""

    @abstractmethod
    def to_utc(self) -> UTCDateTime:
        """Convert into an equivalent UTCDateTime"""

    @overload
    @abstractmethod
    def to_offset(self, /) -> OffsetDateTime:
        ...

    @overload
    @abstractmethod
    def to_offset(self, offset: timedelta, /) -> OffsetDateTime:
        ...

    @abstractmethod
    def to_offset(self, offset: timedelta | None = None, /) -> OffsetDateTime:
        """Convert into an equivalent OffsetDateTime.
        Optionally, specify the offset to use.
        The result will always represent the same moment in time.
        """

    @abstractmethod
    def to_zoned(self, zone: str, /) -> ZonedDateTime:
        """Convert into an equivalent ZonedDateTime.

        The result will always represent the same moment in time.

        Raises
        ------
        ~zoneinfo.ZoneInfoNotFoundError
            If the timezone name is not found in the IANA database.
        """

    @abstractmethod
    def to_local(self) -> LocalDateTime:
        """Convert into a UTC-equivalent LocalDateTime"""

    @abstractmethod
    def exact_eq(self: _T, other: _T, /) -> bool:
        """Compare objects by their values, instead of their UTC equivalence.

        Examples
        --------
        .. code-block:: python

           a = OffsetDateTime(2020, 8, 15, hour=12, offset=hours(1))
           b = OffsetDateTime(2020, 8, 15, hour=13, offset=hours(2))
           a == b  # True: equivalent UTC times
           a.exact_eq(b)  # False: different values (hour and offset)
        """


class UTCDateTime(AwareDateTime):
    """A UTC-only datetime. Useful for representing moments in time
    in an unambiguous way.

    In >95% of cases, you should use this class over the others. The other
    classes are most often useful at the boundaries of your application.

    Example
    -------

    .. code-block:: python

       from whenever import UTCDateTime
       py311_release_livestream = UTCDateTime(2022, 10, 24, hour=17)
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
        """Create an instance from the current time

        Note
        ----
        You can mock this method in tests with `freezegun <https://github.com/spulec/freezegun>`_.

        """
        return cls._from_py_unchecked(_datetime.now(_UTC))

    def __str__(self) -> str:
        """Format a UTCDateTime as ``YYYY-MM-DDTHH:MM:SS(.ffffff)Z``.
        This format is both RFC 3339 and ISO 8601 compliant.

        Example
        -------
        .. code-block:: python

           d = UTCDateTime(2020, 8, 15, hour=23, minute=12)
           assert str(d) == "2020-08-15T23:12:00Z"

        """
        return f"{self._py_dt.isoformat()[:-6]}Z"

    @classmethod
    def from_str(cls, s: str, /) -> UTCDateTime:
        """Create a UTCDateTime from ``YYYY-MM-DDTHH:MM:SS(.fff(fff))Z``.
        The inverse of :meth:`__str__`.

        Raises
        ------
        ValueError
            if the string does not match this exact format.

        Note
        ----
        ``T`` may be replaced with a single space

        Example
        -------

        .. code-block:: python

           d = UTCDateTime.from_str("2020-08-15T23:12:00Z")
           assert d == UTCDateTime(2020, 8, 15, hour=23, minute=12)

           # inverse of __str__
           assert UTCDateTime.from_str(str(d)) == d

           # ValueError: no Z
           UTCDateTime.from_str("2020-08-15T23:12:00")

        """
        if not _match_utc_str(s):
            raise InvalidFormat()
        return cls._from_py_unchecked(_fromisoformat_utc(s))

    if TYPE_CHECKING or SPHINX_BUILD:

        def timestamp(self) -> float:
            """The UNIX timestamp. Inverse of :meth:`from_timestamp`.

            Example
            -------

            .. code-block:: python

               assert UTCDateTime(1970, 1, 1).timestamp() == 0

               ts = 1_123_000_000
               assert UTCDateTime.from_timestamp(ts).timestamp() == ts
            """
            ...

    else:
        timestamp = property(attrgetter("_py_dt.timestamp"))

    @classmethod
    def from_timestamp(cls, i: float, /) -> UTCDateTime:
        """Create a UTCDateTime from a UNIX timestamp.
        The inverse of :meth:`timestamp`.

        Example
        -------

        .. code-block:: python

           assert UTCDateTime.from_timestamp(0) == UTCDateTime(1970, 1, 1)
           d = UTCDateTime.from_timestamp(1_123_000_000.45)
           assert d == UTCDateTime(2004, 8, 2, 16, 26, 40, 450_000)

           assert UTCDateTime.from_timestamp(d.timestamp()) == d
        """
        return cls._from_py_unchecked(_fromtimestamp(i, _UTC))

    @property
    def py(self) -> _datetime:
        """Get the underlying :class:`~datetime.datetime` object.
        Its tzinfo is always :attr:`~datetime.UTC`. Inverse of :meth:`from_py`.

        """
        return self._py_dt

    @classmethod
    def from_py(cls, d: _datetime, /) -> UTCDateTime:
        """Create an instance from a :class:`~datetime.datetime` object.
        It must be timezone-aware and have the exact :attr:`~datetime.UTC`
        timezone.
        Inverse of :meth:`py`.

        Raises
        ------
        ValueError
            If the datetime is timezone-naive or has a non-UTC timezone.


        Example
        -------

        .. code-block:: python

           from datetime import datetime, UTC
           d = datetime(2020, 8, 15, hour=23, tzinfo=UTC)
           UTCDateTime.from_py(d) == UTCDateTime(2020, 8, 15, hour=23)

           # ValueError: no UTC tzinfo
           UTCDateTime.from_py(datetime(2020, 8, 15, hour=23))
        """
        if d.tzinfo is not _UTC:
            raise ValueError(
                "Can only create UTCDateTime from UTC datetime, "
                f"got datetime with tzinfo={d.tzinfo!r}"
            )
        return cls._from_py_unchecked(d)

    tzinfo: ClassVar[_tzinfo] = _UTC

    @property
    def offset(self) -> timedelta:
        """The UTC offset, always :attr:`~datetime.timedelta(0)`"""
        return timedelta()

    if TYPE_CHECKING:
        # We could have used typing.Unpack, but that's only available
        # in Python 3.11+ or with typing_extensions.
        def replace(
            self,
            *,
            year: int | NOT_SET = NOT_SET(),
            month: int | NOT_SET = NOT_SET(),
            day: int | NOT_SET = NOT_SET(),
            hour: int | NOT_SET = NOT_SET(),
            minute: int | NOT_SET = NOT_SET(),
            second: int | NOT_SET = NOT_SET(),
            microsecond: int | NOT_SET = NOT_SET(),
        ) -> UTCDateTime:
            ...

    else:

        def replace(self, /, **kwargs) -> UTCDateTime:
            """Create a new instance with the given fields replaced

            Example
            -------

            .. code-block:: python

               d = UTCDateTime(2020, 8, 15, 23, 12)
               assert d.replace(year=2021) == UTCDateTime(2021, 8, 15, 23, 12)
            """
            if not _no_tzinfo_or_fold(kwargs):
                raise TypeError("tzinfo and fold are not allowed arguments")
            return self._from_py_unchecked(self._py_dt.replace(**kwargs))

    if TYPE_CHECKING or SPHINX_BUILD:

        def __hash__(self) -> int:
            ...

    else:
        # Defining properties this way is faster than declaring a `def`,
        # but the type checker doesn't like it.
        __hash__ = property(attrgetter("_py_dt.__hash__"))

    min: ClassVar[UTCDateTime]
    """Small possible value"""
    max: ClassVar[UTCDateTime]
    """Biggest possible value"""

    # Hiding __eq__ from mypy ensures that --strict-equality works
    if not TYPE_CHECKING:  # pragma: no branch

        def __eq__(self, other: object) -> bool:
            """Compare two :class:`AwareDateTime` objects by their UTC equivalence

            Example
            -------
            .. code-block:: python

               # True
               UTCDateTime(2020, 8, 15, 23) == UTCDateTime(2020, 8, 15, 23)

               # False
               UTCDateTime(2020, 8, 15) == UTCDateTime(2023, 1, 1)

               # True: these both evaluate to the same UTC time
               UTCDateTime(2020, 8, 15, 22) == (
                   OffsetDateTime(2020, 8, 15, 23, offset=hours(1))
                )

            """
            if not isinstance(other, (UTCDateTime, OffsetDateTime)):
                return NotImplemented
            return self._py_dt == other._py_dt

    def exact_eq(self, other: UTCDateTime, /) -> bool:
        """Exact equality, comparing objects by their values, instead of
        their UTC equivalence. Always returns False for non-UTCDateTime objects.
        """
        return self._py_dt == other._py_dt

    def __lt__(self, other: UTCDateTime) -> bool:
        """Compare two objects

        Example
        -------
        .. code-block:: python

           assert UTCDateTime(2020, 8, 15, hour=23) < UTCDateTime(2020, 8, 16)

        """
        if not isinstance(other, UTCDateTime):
            return NotImplemented
        return self._py_dt < other._py_dt

    def __le__(self, other: UTCDateTime) -> bool:
        if not isinstance(other, UTCDateTime):
            return NotImplemented
        return self._py_dt <= other._py_dt

    def __gt__(self, other: UTCDateTime) -> bool:
        if not isinstance(other, UTCDateTime):
            return NotImplemented
        return self._py_dt > other._py_dt

    def __ge__(self, other: UTCDateTime) -> bool:
        if not isinstance(other, UTCDateTime):
            return NotImplemented
        return self._py_dt >= other._py_dt

    def __add__(self, other: timedelta) -> UTCDateTime:
        """Add a timedelta to this datetime

        Example
        -------
        .. code-block:: python

           d = UTCDateTime(2020, 8, 15, hour=23, minute=12)
           assert d + timedelta(days=1, seconds=5) == UTCDateTime(
               2020, 8, 16, hour=23, minute=12, second=5
           )
        """
        if not isinstance(other, timedelta):
            return NotImplemented
        return self._from_py_unchecked(self._py_dt + other)

    if TYPE_CHECKING:

        @overload
        def __sub__(self, other: UTCDateTime) -> timedelta:
            ...

        @overload
        def __sub__(self, other: timedelta) -> UTCDateTime:
            ...

        def __sub__(
            self, other: UTCDateTime | timedelta
        ) -> UTCDateTime | timedelta:
            ...

    else:

        def __sub__(
            self, other: timedelta | UTCDateTime
        ) -> UTCDateTime | timedelta:
            """Subtract another datetime or timedelta

            Example
            -------

            .. code-block:: python

               d = UTCDateTime(2020, 8, 15, hour=23, minute=12)
               assert d - timedelta(days=1, seconds=5) == UTCDateTime(
                   2020, 8, 14, hour=23, minute=11, second=55
               )

               assert d - UTCDateTime(2020, 8, 14) > timedelta(days=1)
            """
            if isinstance(other, UTCDateTime):
                return self._py_dt - other._py_dt
            elif isinstance(other, timedelta):
                return self._from_py_unchecked(self._py_dt - other)
            return NotImplemented

    def to_utc(self) -> UTCDateTime:
        """Convert into an equivalent UTCDateTime (no-op).
        Implemented for consistency with the other classes."""
        return self

    @overload
    def to_offset(self, /) -> OffsetDateTime:
        ...

    @overload
    def to_offset(self, offset: timedelta, /) -> OffsetDateTime:
        ...

    def to_offset(self, offset: timedelta | None = None, /) -> OffsetDateTime:
        """Convert into an equivalent fixed-offset datetime.
        Optionally, specify the offset to use.
        The result will always evaluate equal to the original datetime.

        Example
        -------
        .. code-block:: python

           from whenever import hours
           a = UTCDateTime(2020, 8, 15, hour=22)
           b = a.to_offset(hours(1))  # 2020-08-15 23:00:00+01:00
           a == b  # True (same UTC time)

        """
        return OffsetDateTime._from_py_unchecked(
            self._py_dt.astimezone(
                _timezone(offset) if offset else _zero_timezone
            )
        )

    def to_zoned(self, zone: str, /) -> ZonedDateTime:
        """Convert into an equivalent ZonedDateTime.
        The result will always evaluate equal to the original datetime.

        Raises
        ------
        ~zoneinfo.ZoneInfoNotFoundError
            If the timezone name is not found in the IANA database.

        Example
        -------
        .. code-block:: python

           a = UTCDateTime(2020, 8, 15, hour=22)
           b = a.to_zoned("Europe/Amsterdam")  # 2020-08-15 23:00:00+02:00[Europe/Amsterdam]
           a == b  # True (same UTC time)
        """
        return ZonedDateTime._from_py_unchecked(
            self._py_dt.astimezone(ZoneInfo(zone))
        )

    def to_local(self) -> LocalDateTime:
        """Convert into an equivalent datetime in the local timezone.

        Example
        -------
        .. code-block:: python

           # assuming system timezone is Europe/Amsterdam
           a = UTCDateTime(2020, 8, 15, hour=21)
           b = a.to_local()  # 2020-08-15 23:00:00+02:00
           a == b  # True (same UTC time)

        """
        return LocalDateTime._from_py_unchecked(_to_local(self._py_dt))

    def __repr__(self) -> str:
        return f"whenever.UTCDateTime({self})"

    # a custom pickle implementation with a smaller payload
    def __reduce__(self) -> tuple[object, ...]:
        return (
            UTCDateTime,
            self._py_dt.timetuple()[:6] + (self._py_dt.microsecond,),
        )


class OffsetDateTime(AwareDateTime):
    """A datetime with a fixed UTC offset.

    Useful for representing the local time at a specific location.

    Example
    -------

    .. code-block:: python

       from whenever import OffsetDateTime, hours
       # 9 AM in Salt Lake City, with the UTC offset at the time
       pycon23_started = OffsetDateTime(2023, 4, 21, hour=9, offset=hours(-6))
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
        offset: timedelta,
    ) -> None:
        self._py_dt = _datetime(
            year,
            month,
            day,
            hour,
            minute,
            second,
            microsecond,
            _timezone(offset),
        )

    @classmethod
    def now(cls, offset: timedelta) -> OffsetDateTime:
        """Create an OffsetDateTime from the current time

        Example
        -------

        .. code-block:: python

           now = OffsetDateTime.now(offset=hours(2))
           later = OffsetDateTime.now(offset=hours(3))
           assert later > now

        """
        return cls._from_py_unchecked(_datetime.now(_timezone(offset)))

    def __str__(self) -> str:
        """Format an instance in the format
        ``YYYY-MM-DDTHH:MM:SS(.ffffff)±HH:MM(:SS(.ffffff))``.

        This format is both RFC 3339 and ISO 8601 compliant.

        The inverse of :meth:`from_str`.

        Example
        -------

        .. code-block:: python

           d = OffsetDateTime(2020, 8, 15, hour=23, minute=12, offset=hours(1))
           assert str(d) == "2020-08-15T23:12:00+01:00"

        """
        return self._py_dt.isoformat()

    @classmethod
    def from_str(cls, s: str, /) -> OffsetDateTime:
        """Create an instance from the format
        ``YYYY-MM-DDTHH:MM:SS(.fff(fff))±HH:MM(:SS(.ffffff))``.
        The inverse of :meth:`__str__`.

        Raises
        ------
        InvalidFormat
            If the string does not match this exact format.

        Note
        ----
        ``T`` may be replaced with a single space

        Example
        -------

        .. code-block:: python

           from whenever import hours

           d = OffsetDateTime.from_str("2020-08-15T23:12:00-06:00")
           d.year  # 2020
           d.offset  # timedelta(hours=-6)

           # inverse of __str__
           OffsetDateTime.from_str(str(d)) == d

           # InvalidFormat: no offset
           OffsetDateTime.from_str("2020-08-15T23:12:00")

        """
        if not _match_offset_str(s):
            raise InvalidFormat()
        return cls._from_py_unchecked(_fromisoformat(s))

    if TYPE_CHECKING or SPHINX_BUILD:

        def timestamp(self) -> float:
            """The UNIX timestamp. Inverse of :meth:`from_timestamp`.

            Example
            -------

            .. code-block:: python

               OffsetDateTime(1970, 1, 1, 3, offset=hours(3)).timestamp()  # 0

               ts = 1_123_000_000
               OffsetDateTime.from_timestamp(ts, offset=hours(-2)).timestamp() == ts
            """
            ...

    else:
        timestamp = property(attrgetter("_py_dt.timestamp"))

    @classmethod
    def from_timestamp(cls, i: float, /, offset: timedelta) -> OffsetDateTime:
        """Create a OffsetDateTime from a UNIX timestamp.
        The inverse of :meth:`timestamp`.

        Example
        -------

        .. code-block:: python

           assert OffsetDateTime.from_timestamp(0, offset=hours(3)) == (
               OffsetDateTime(1970, 1, 1, 3, offset=hours(3))
           )
           d = OffsetDateTime.from_timestamp(1_123_000_000.45, offset=hours(-2))
           assert d == OffsetDateTime(2004, 8, 2, 14, 26, 40, 450_000, offset=hours(-2))

           assert OffsetDateTime.from_timestamp(d.timestamp(), d.offset) == d
        """
        return cls._from_py_unchecked(_fromtimestamp(i, _timezone(offset)))

    @property
    def py(self) -> _datetime:
        """Get the underlying :class:`~datetime.datetime` object"""
        return self._py_dt

    @classmethod
    def from_py(cls, d: _datetime, /) -> OffsetDateTime:
        """Create an instance from a :class:`~datetime.datetime` object.

        It must be timezone-aware and have a fixed :class:`datetime.timezone`
        tzinfo. Inverse of :meth:`py`.

        Example
        -------

        .. code-block:: python

           from datetime import datetime, timezone, timedelta
           d = datetime(2020, 8, 15, 23, tzinfo=timezone(timedelta(hours=2)))

           OffsetDateTime.from_py(d) == OffsetDateTime(2020, 8, 15, 23, offset=hours(2))

           # ValueError: no tzinfo
           OffsetDateTime.from_py(datetime(2020, 8, 15, 23))
        """
        if not isinstance(d.tzinfo, _timezone):
            raise ValueError(
                "Datetime's tzinfo is not a datetime.timezone, "
                f"got tzinfo={d.tzinfo!r}"
            )
        return cls._from_py_unchecked(d)

    if TYPE_CHECKING or SPHINX_BUILD:

        @property
        def tzinfo(self) -> _timezone:
            "The timezone, always a :class:`datetime.timezone` (fixed offset)"
            ...

    else:
        tzinfo = property(attrgetter("_py_dt.tzinfo"))

    if TYPE_CHECKING:
        # We could have used typing.Unpack, but that's only available
        # in Python 3.11+ or with typing_extensions.
        def replace(
            self,
            *,
            year: int | NOT_SET = NOT_SET(),
            month: int | NOT_SET = NOT_SET(),
            day: int | NOT_SET = NOT_SET(),
            hour: int | NOT_SET = NOT_SET(),
            minute: int | NOT_SET = NOT_SET(),
            second: int | NOT_SET = NOT_SET(),
            microsecond: int | NOT_SET = NOT_SET(),
            offset: timedelta | NOT_SET = NOT_SET(),
        ) -> OffsetDateTime:
            ...

    else:

        def replace(self, /, **kwargs) -> OffsetDateTime:
            """Create a new instance with the given fields replaced

            Example
            -------

            .. code-block:: python

               d = OffsetDateTime(2020, 8, 15, 23, 12, offset=hours(1))
               assert d.replace(year=2021) == OffsetDateTime(2021, 8, 15, 23, 12, offset=hours(1))
            """
            if not _no_tzinfo_or_fold(kwargs):
                raise TypeError("tzinfo and fold are not allowed arguments")

            try:
                kwargs["tzinfo"] = _timezone(kwargs.pop("offset"))
            except KeyError:
                pass
            return self._from_py_unchecked(self._py_dt.replace(**kwargs))

    min: ClassVar[OffsetDateTime]
    """Small possible value"""
    max: ClassVar[OffsetDateTime]
    """Biggest possible value"""

    @property
    def offset(self) -> timedelta:
        """The UTC offset"""
        # We know that offset is never None, because we set it in __init__
        return self._py_dt.utcoffset()  # type: ignore[return-value]

    # Hiding __eq__ from mypy ensures that --strict-equality works
    if not TYPE_CHECKING:  # pragma: no branch
        __hash__ = property(attrgetter("_py_dt.__hash__"))

        def __eq__(self, other: object) -> bool:
            """Check if two datetimes represent at the same moment in time

            Example
            -------
            .. code-block:: python

               assert OffsetDateTime(
                   2020, 8, 15, 23, offset=hours(4)
               ) == OffsetDateTime(
                   2020, 8, 15, 22, offset=hours(3)
               )

            """
            if not isinstance(other, (UTCDateTime, OffsetDateTime)):
                return NotImplemented
            return self._py_dt == other._py_dt

    def exact_eq(self, other: OffsetDateTime, /) -> bool:
        """Compare objects by their values, instead of their UTC equivalence.

        Examples
        --------
        .. code-block:: python

           a = OffsetDateTime(2020, 8, 15, hour=12, offset=hours(1))
           b = OffsetDateTime(2020, 8, 15, hour=13, offset=hours(2))
           a == b  # True: they're equivalent in UTC
           a.exact_eq(b)  # False: different values (hour and offset)
        """
        # FUTURE: there's probably a faster way to do this
        return self == other and self.offset == other.offset

    def __lt__(self, other: OffsetDateTime) -> bool:
        """Compare two objects by their UTC equivalence

        Example
        -------
        .. code-block:: python

           # the first datetime is later in UTC
           assert OffsetDateTime(2020, 8, 15, hour=23, offset=hours(2)) > (
               OffsetDateTime(2020, 8, 16, offset=hours(-8))
           )

        """
        if not isinstance(other, OffsetDateTime):
            return NotImplemented
        return self._py_dt < other._py_dt

    def __le__(self, other: OffsetDateTime) -> bool:
        if not isinstance(other, OffsetDateTime):
            return NotImplemented
        return self._py_dt <= other._py_dt

    def __gt__(self, other: OffsetDateTime) -> bool:
        if not isinstance(other, OffsetDateTime):
            return NotImplemented
        return self._py_dt > other._py_dt

    def __ge__(self, other: OffsetDateTime) -> bool:
        if not isinstance(other, OffsetDateTime):
            return NotImplemented
        return self._py_dt >= other._py_dt

    def __sub__(self, other: OffsetDateTime) -> timedelta:
        """Subtract another datetime to get the timedelta between them

        Example
        -------

        .. code-block:: python

            d = OffsetDateTime(2020, 8, 15, 23, 12, offset=hours(1))
            assert d - timedelta(days=1, hours=4, seconds=5) == OffsetDateTime(
                2020, 8, 14, 23, 11, 55, offset=hours(-3)
            )

            assert d - OffsetDateTime(2020, 8, 14, offset=hours(0)) > timedelta(days=1)
        """
        if not isinstance(other, OffsetDateTime):
            return NotImplemented
        return self._py_dt - other._py_dt

    def to_utc(self) -> UTCDateTime:
        """Convert into an equivalent UTCDateTime"""
        return UTCDateTime._from_py_unchecked(self._py_dt.astimezone(_UTC))

    @overload
    def to_offset(self, /) -> OffsetDateTime:
        ...

    @overload
    def to_offset(self, offset: timedelta, /) -> OffsetDateTime:
        ...

    def to_offset(self, offset: timedelta | None = None, /) -> OffsetDateTime:
        """Convert into a UTC-equivalent OffsetDateTime"""
        return (
            self
            if offset is None
            else self._from_py_unchecked(
                self._py_dt.astimezone(_timezone(offset))
            )
        )

    def to_zoned(self, zone: str) -> ZonedDateTime:
        """Convert into a UTC-equivalent ZonedDateTime

        Raises
        ------
        ~zoneinfo.ZoneInfoNotFoundError
            If the timezone name is not found in the IANA database.

        """
        return ZonedDateTime._from_py_unchecked(
            self._py_dt.astimezone(ZoneInfo(zone))
        )

    def to_local(self) -> LocalDateTime:
        """Convert into a UTC-equivalent LocalDateTime"""
        return LocalDateTime._from_py_unchecked(_to_local(self._py_dt))

    def __repr__(self) -> str:
        return f"whenever.OffsetDateTime({self})"

    # a custom pickle implementation with a smaller payload
    def __reduce__(self) -> tuple[object, ...]:
        return (
            _offset_unpickle,
            self._py_dt.timetuple()[:6]
            + (self._py_dt.microsecond, self._py_dt.utcoffset()),
        )


# A separate function is needed for unpickling, because the
# constructor doesn't accept positional offset argument as
# required by __reduce__.
def _offset_unpickle(
    year: int,
    month: int,
    day: int,
    hour: int,
    minute: int,
    second: int,
    microsecond: int,
    offset: timedelta,
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
            _timezone(offset),
        )
    )


class ZonedDateTime(AwareDateTime):
    """A datetime associated with a timezone.
    Useful for representing the local time bound to a specific location.

    The ``zone`` argument is the timezone's ID in the IANA database.
    The ``disambiguate`` argument controls how ambiguous datetimes are handled:

    - ``"raise"``: ambiguous datetimes raise :class:`Ambiguous`.
    - ``"earlier"``: pick the earlier datetime (before the DST transition).
    - ``"later"``: pick the later datetime (after the DST transition).

    Raises
    ------
    ~zoneinfo.ZoneInfoNotFoundError
        If the timezone name is not found in the IANA database.
    DoesntExistInZone
        If the datetime does not exist in the given timezone
        (i.e. the clock was set forward, "skipping" this time).
    Ambiguous
        If ``disambiguate`` is ``"raise"`` and the datetime is ambiguous

    Example
    -------

    .. code-block:: python

       from whenever import ZonedDateTime

       # always at 11:00 in London, regardless of the offset
       changing_the_guard = ZonedDateTime(
           2024, 12, 8, hour=11, zone="Europe/London"
       )

       # Explicitly resolve ambiguities when clocks are set backwards.
       # Default is "raise", which raises an exception
       night_shift = ZonedDateTime(2023, 10, 29, 1, 15, zone=london, disambiguate="later")

       # ZoneInfoNotFoundError: no such timezone
       ZonedDateTime(2024, 12, 8, hour=11, zone="invalid")

       # DoesntExistInZone: 2:15 AM does not exist on this day
       ZonedDateTime(2023, 3, 26, 2, 15, zone="Europe/Amsterdam")
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
        zone: str,
        disambiguate: Literal["earlier", "later", "raise"] = "raise",
    ) -> None:
        fold = _as_fold(disambiguate)
        dt = _datetime(
            year,
            month,
            day,
            hour,
            minute,
            second,
            microsecond,
            ZoneInfo(zone),
            fold=fold or 0,
        )
        if not _exists_in_tz(dt):
            raise DoesntExistInZone()
        if disambiguate == "raise" and dt.astimezone(_UTC) != dt.replace(
            fold=1
        ).astimezone(_UTC):
            raise Ambiguous()
        self._py_dt = dt

    @classmethod
    def now(cls, zone: str) -> ZonedDateTime:
        """Create an instance from the current time

        Raises
        ------
        ~zoneinfo.ZoneInfoNotFoundError
            If the timezone name is not found in the IANA database.
        """
        return cls._from_py_unchecked(_datetime.now(ZoneInfo(zone)))

    def __str__(self) -> str:
        """Format as ``YYYY-MM-DDTHH:MM:SS(.ffffff)±HH:MM(:SS(.ffffff))[TIMEZONE NAME]``,
        for example: ``2020-08-15T23:12:00+01:00[Europe/London]``.

        Warning
        -------
        This format is similar to those `used by other languages <https://tc39.es/proposal-temporal/docs/strings.html#iana-time-zone-names>`_,
        but it is *not* RFC 3339 or ISO 8601 compliant.
        These standards don't support timezone names.
        Convert to :class:`OffsetDateTime` (:meth:`to_offset`)
        first if you need RFC 3339 compliance.

        Example
        -------
        .. code-block:: python

           d = ZonedDateTime(2020, 8, 15, 23, 12, zone="Europe/London")
           str(d)  # "2020-08-15T23:12:00+01:00[Europe/London]"

        """
        return (
            f"{self._py_dt.isoformat()}"
            f"[{self._py_dt.tzinfo.key}]"  # type: ignore[union-attr]
        )

    @classmethod
    def from_str(cls, s: str, /) -> ZonedDateTime:
        """Create a ZonedDateTime from
        ``YYYY-MM-DDTHH:MM:SS(.fff(fff))±HH:MM(:SS(.ffffff))[TIMEZONE]``,
        for example: ``2020-08-15T23:12:00+01:00[Europe/London]``.
        The inverse of :meth:`__str__`.

        Raises
        ------
        ValueError
            If the string does not match this exact format.
        ~zoneinfo.ZoneInfoNotFoundError
            If the timezone name is not found in the IANA database.

        Note
        ----
        ``T`` may be replaced with a single space

        Example
        -------

        .. code-block:: python

           d = ZonedDateTime.from_str("2020-08-15T23:12:00+01:00[Europe/Rome]")
           d.zone  # "Europe/Rome"
           d.hour  # 23

           # Inverse of __str__
           ZonedDateTime.from_str(str(d)) == d

           # ValueError: no offset
           ZonedDateTime.from_str("2020-08-15T23:12[Europe/Rome]")
           # ZoneInfoNotFoundError
           ZonedDateTime.from_str("2020-08-15T23:12:00+01:00[invalid]")
        """
        if (match := _match_zoned_str(s)) is None:
            raise InvalidFormat()
        dt = _fromisoformat(match[1])
        offset = dt.utcoffset()
        dt = dt.replace(tzinfo=ZoneInfo(match[2]))
        if offset != dt.utcoffset():  # offset/zone mismatch: try other fold
            dt = dt.replace(fold=1)
            if dt.utcoffset() != offset:
                raise InvalidOffsetForZone()
        return cls._from_py_unchecked(dt)

    if TYPE_CHECKING or SPHINX_BUILD:

        def timestamp(self) -> float:
            """The UNIX timestamp. Inverse of :meth:`from_timestamp`.

            Example
            -------

            .. code-block:: python

               assert UTCDateTime(1970, 1, 1).timestamp() == 0

               ts = 1_123_000_000
               assert UTCDateTime.from_timestamp(ts).timestamp() == ts
            """
            ...

    else:
        timestamp = property(attrgetter("_py_dt.timestamp"))

    @classmethod
    def from_timestamp(cls, i: float, /, zone: str) -> ZonedDateTime:
        """Create an instace from a UNIX timestamp.
        The inverse of :meth:`timestamp`.

        Raises
        ------
        ~zoneinfo.ZoneInfoNotFoundError
            If the timezone name is not found in the IANA database.

        Example
        -------

        .. code-block:: python

           ZonedDateTime.from_timestamp(0, zone="Iceland")  # 1970-01-01T00:00:00+00:00[Iceland]
           d = ZonedDateTime.from_timestamp(1_123_000_000.45, zone="Iceland")
           d  # 2004-08-02T16:26:40.450000+00:00[Iceland]

           # Inverse of timestamp()
           ZonedDateTime.from_timestamp(d.timestamp(), "Iceland") == d
        """
        return cls._from_py_unchecked(_fromtimestamp(i, ZoneInfo(zone)))

    @property
    def py(self) -> _datetime:
        """Get the underlying :class:`~datetime.datetime`.
        It will always have a :class:`~zoneinfo.ZoneInfo` tzinfo.
        """
        return self._py_dt

    @classmethod
    def from_py(cls, d: _datetime, /) -> ZonedDateTime:
        """Create an instance from a :class:`~datetime.datetime` object.
        It must be timezone-aware and have a :class:`~zoneinfo.ZoneInfo`
        tzinfo.
        Inverse of :meth:`py`.

        Raises
        ------
        ValueError
            If the datetime's tzinfo is not a :class:`~zoneinfo.ZoneInfo`.
        DoesntExistInZone
            If the datetime does not exist in the given timezone
            (i.e. the clock was set forward, "skipping" this time).

        Example
        -------

        .. code-block:: python

           from datetime import datetime, UTC
           from zoneinfo import ZoneInfo
           d = datetime(2020, 8, 15, hour=23, tzinfo=ZoneInfo("Asia/Tokyo"))

           ZonedDateTime.from_py(d)  # 2020-08-15T23:00:00+09:00[Asia/Tokyo]

           # ValueError: invalid tzinfo
           ZonedDateTime.from_py(datetime(2020, 8, 15, hour=23, tzinfo=UTC))

           # DoesntExistInZone: 2:15 AM does not exist on this day
           ZonedDateTime.from_py(datetime(2023, 3, 26, 2, 15, tzinfo=ZoneInfo("Europe/Amsterdam")))
        """
        if not isinstance(d.tzinfo, ZoneInfo):
            raise ValueError(
                "Can only create ZonedDateTime from ZoneInfo, "
                f"got datetime with tzinfo={d.tzinfo!r}"
            )
        if not _exists_in_tz(d):
            raise DoesntExistInZone()
        return cls._from_py_unchecked(d)

    if TYPE_CHECKING:
        # We could have used typing.Unpack, but that's only available
        # in Python 3.11+ or with typing_extensions.
        def replace(
            self,
            *,
            year: int | NOT_SET = NOT_SET(),
            month: int | NOT_SET = NOT_SET(),
            day: int | NOT_SET = NOT_SET(),
            hour: int | NOT_SET = NOT_SET(),
            minute: int | NOT_SET = NOT_SET(),
            second: int | NOT_SET = NOT_SET(),
            microsecond: int | NOT_SET = NOT_SET(),
            zone: str | NOT_SET = NOT_SET(),
            fold: Literal[0, 1] | NOT_SET = NOT_SET(),
        ) -> ZonedDateTime:
            ...

    else:

        def replace(self, /, **kwargs) -> ZonedDateTime:
            """Create a new instance with the given fields replaced

            Raises
            ------
            ~zoneinfo.ZoneInfoNotFoundError
                If the timezone name is not found in the IANA database.
            DoesntExistInZone
                If the datetime does not exist in the given timezone
                (i.e. the clock was set forward, "skipping" this time).

            Example
            -------

            .. code-block:: python

               d = ZonedDateTime(2020, 8, 15, 23, 12, zone="Iceland")
               d.replace(year=2021)  # 2021-08-15T23:12:00+00:00[Iceland]
            """
            if "tzinfo" in kwargs:
                raise TypeError("tzinfo is not an allowed argument")
            try:
                kwargs["tzinfo"] = ZoneInfo(kwargs.pop("zone"))
            except KeyError:
                pass
            dt = self._py_dt.replace(**kwargs)
            if not _exists_in_tz(dt):
                raise DoesntExistInZone()
            return self._from_py_unchecked(dt)

    if TYPE_CHECKING:

        @property
        def fold(self) -> Literal[0, 1]:
            """The fold value"""
            ...

        @property
        def tzinfo(self) -> ZoneInfo:
            """The timezone"""
            ...

        @property
        def zone(self) -> str:
            """The timezone name"""
            ...

    else:
        fold = property(attrgetter("_py_dt.fold"))
        tzinfo = property(attrgetter("_py_dt.tzinfo"))
        zone = property(attrgetter("_py_dt.tzinfo.key"))

    @property
    def offset(self) -> timedelta:
        """The UTC offset"""
        return self._py_dt.utcoffset()  # type: ignore[return-value]

    def __hash__(self) -> int:
        return hash(self._py_dt.astimezone(_UTC))

    min: ClassVar[ZonedDateTime]
    """Small possible value"""
    max: ClassVar[ZonedDateTime]
    """Biggest possible value"""

    # Hiding __eq__ from mypy ensures that --strict-equality works.
    if not TYPE_CHECKING:  # pragma: no branch

        def __eq__(self, other: object) -> bool:
            """Compare if two datatimes occur at the same moment in time.

            Equivalent to ``self.to_uct() == other.to_utc()``.

            Note
            ----

            If you want to exactly compare the values of the datetimes, use
            :meth:`exact_eq` instead.

            Example
            -------
            .. code-block:: python

               ZonedDateTime(
                   2020, 8, 15, 23, zone="Europe/London"
               ) == ZonedDateTime(
                   2020, 8, 16, zone="Europe/Paris"
               )  # True, same moment in time

            """
            if not isinstance(other, AwareDateTime):
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
        """Compare if two datetimes have the exact same values.

        Note
        ----
        This does not compare the moment in time, but the exact values of the
        datetime fields. If ``a.exact_eq(b)`` is true, then
        ``a == b`` is also true, but the converse is not necessarily true.

        Example
        -------

        .. code-block:: python

           # same exact values
           ZonedDateTime(
               2020, 8, 15, 23, zone="Europe/London"
           ).exact_eq(
               ZonedDateTime(2020, 8, 15, 22, zone="Europe/London")
           )

           # same moment in time, but different values
           assert not ZonedDateTime(
               2020, 8, 15, 23, zone="Europe/London"
           ).exact_eq(
               ZonedDateTime(2020, 8, 15, 22, zone="Europe/Paris")
           )
        """
        return (
            self.zone is other.zone
            and self.fold == other.fold
            and self._py_dt == other._py_dt
        )

    def __lt__(self, other: ZonedDateTime) -> bool:
        """Compare two datetimes by when they occur in time.

        Equivalent to ``self.to_utc() < other.to_utc()``.

        Note
        ----
        The standard library compares datetimes differently depending on
        whether they have the same timezone or not.
        We choose one consistent way, for fewer surprises.

        Example
        -------
        .. code-block:: python

           assert ZonedDateTime(2020, 8, 15, 12, zone="Asia/Tokyo") < (
               ZonedDateTime(2020, 8, 15, zone="America/Los_Angeles")
           )

        """
        if not isinstance(other, ZonedDateTime):
            return NotImplemented
        return self._py_dt.astimezone(_UTC) < other._py_dt.astimezone(_UTC)

    def __le__(self, other: ZonedDateTime) -> bool:
        if not isinstance(other, ZonedDateTime):
            return NotImplemented
        return self._py_dt.astimezone(_UTC) <= other._py_dt.astimezone(_UTC)

    def __gt__(self, other: ZonedDateTime) -> bool:
        if not isinstance(other, ZonedDateTime):
            return NotImplemented
        return self._py_dt.astimezone(_UTC) > other._py_dt.astimezone(_UTC)

    def __ge__(self, other: ZonedDateTime) -> bool:
        if not isinstance(other, ZonedDateTime):
            return NotImplemented
        return self._py_dt.astimezone(_UTC) >= other._py_dt.astimezone(_UTC)

    def __add__(self, delta: timedelta) -> ZonedDateTime:
        """Add a timedelta to this datetime.
        Unlike the standard library, this method accounts for DST transitions.

        Example
        -------
        .. code-block:: python

           d = ZonedDateTime(2023, 10, 29, 23, 12, zone="Europe/Amsterdam", disambiguate="earlier")

           # one hour skipped due to DST transition
           d + timedelta(hours=24) # 2023-10-30T22:12:00+01:00[Europe/Amsterdam]
        """
        if not isinstance(delta, timedelta):
            return NotImplemented
        return self._from_py_unchecked(
            (self._py_dt.astimezone(_UTC) + delta).astimezone(
                self._py_dt.tzinfo
            )
        )

    if TYPE_CHECKING:

        @overload
        def __sub__(self, other: ZonedDateTime) -> timedelta:
            ...

        @overload
        def __sub__(self, other: timedelta) -> ZonedDateTime:
            ...

        def __sub__(
            self, other: ZonedDateTime | timedelta
        ) -> ZonedDateTime | timedelta:
            ...

    else:

        def __sub__(
            self, other: timedelta | ZonedDateTime
        ) -> ZonedDateTime | timedelta:
            """Subtract another datetime or timedelta"""
            if isinstance(other, ZonedDateTime):
                return self._py_dt.astimezone(_UTC) - other._py_dt
            elif isinstance(other, timedelta):
                return self._from_py_unchecked(
                    (self._py_dt.astimezone(_UTC) - other).astimezone(
                        self._py_dt.tzinfo
                    )
                )
            return NotImplemented

    def is_ambiguous(self) -> bool:
        """Whether the datetime is ambiguous, i.e. ``fold`` has effect.

        Example
        -------

        .. code-block:: python

           # False
           ZonedDateTime(
               2020, 8, 15, 23, zone="Europe/London"
           ).is_ambiguous()

           # True
           ZonedDateTime(
               2023, 10, 29, 2, 15, zone="Europe/Amsterdam"
           ).is_ambiguous()
        """
        return self._py_dt.astimezone(_UTC) != self._py_dt.replace(
            fold=not self._py_dt.fold
        ).astimezone(_UTC)

    def to_utc(self) -> UTCDateTime:
        """Convert to a :class:`UTCDateTime`

        Example
        -------

        .. code-block:: python

           d = ZonedDateTime(2020, 8, 15, 23, zone="Europe/London")
           d.to_utc()  # 2020-08-15T22:00:00Z
        """
        return UTCDateTime._from_py_unchecked(self._py_dt.astimezone(_UTC))

    @overload
    def to_offset(self, /) -> OffsetDateTime:
        ...

    @overload
    def to_offset(self, offset: timedelta, /) -> OffsetDateTime:
        ...

    def to_offset(self, offset: timedelta | None = None, /) -> OffsetDateTime:
        """Convert to an :class:`OffsetDateTime`,
        optionally with a different offset.
        The result always evaluates to the same moment in time.

        Example
        -------
        .. code-block:: python

           d = ZonedDateTime(2020, 8, 15, 23, zone="Europe/London")
           d.to_offset()  # 2020-08-15T23:00:00+01:00
           d.to_offset(hours(-2))  # 2020-08-15T23:00:00-02:00
        """
        return OffsetDateTime._from_py_unchecked(
            self._py_dt.astimezone(
                # mypy doesn't know that offset is never None
                _timezone(offset or self._py_dt.utcoffset())  # type: ignore[arg-type]
            )
        )

    def to_zoned(self, zone: str) -> ZonedDateTime:
        """Convert to a :class:`ZonedDateTime` in the given timezone

        Raises
        ------
        ~zoneinfo.ZoneInfoNotFoundError
            If the timezone name is not found in the IANA database.

        Example
        -------

        .. code-block:: python

           d = ZonedDateTime(2020, 8, 15, 10, zone="Europe/London")
           d.to_zoned("Europe/Paris")  # 2020-08-16T11:00:00+02:00[Europe/Paris]
        """
        return self._from_py_unchecked(self._py_dt.astimezone(ZoneInfo(zone)))

    def to_local(self) -> LocalDateTime:
        """Convert to a :class:`LocalDateTime` (in the system timezone)

        Example
        -------

        .. code-block:: python

           # assumes system timezone is Europe/Amsterdam
           d = ZonedDateTime(2020, 8, 15, 23, zone="Europe/London")
           d.to_local()  # LocalDateTime(2020-08-16T00:00:00+02:00)
        """
        return LocalDateTime._from_py_unchecked(_to_local(self._py_dt))

    def __repr__(self) -> str:
        return f"whenever.ZonedDateTime({self})"

    # a custom pickle implementation with a smaller payload
    def __reduce__(self) -> tuple[object, ...]:
        return (
            _zoned_unpickle,
            self._py_dt.timetuple()[:6]
            + (
                self._py_dt.microsecond,
                # We know that tzinfo is always a ZoneInfo, but mypy doesn't
                self._py_dt.tzinfo.key,  # type: ignore[union-attr]
                self._py_dt.fold,
            ),
        )


# A separate function is needed for unpickling, because the
# constructor doesn't accept positional zone and fold arguments as
# required by __reduce__.
def _zoned_unpickle(
    year: int,
    month: int,
    day: int,
    hour: int,
    minute: int,
    second: int,
    microsecond: int,
    zone: str,
    fold: Literal[0, 1],
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
            ZoneInfo(zone),
            fold=fold,
        )
    )


class LocalDateTime(AwareDateTime):
    """A datetime associated with the system timezone

    Useful for representing the local time bound to the system timezone.

    Note
    ----
    What makes this type different from :class:`ZonedDateTime` is that
    the zone is linked to the system timezone, not a specific location.
    The offset may change if the system timezone changes.

    Warning
    -------
    This type is *not* hashable, because its value depends on the
    system timezone, which may change.

    Example
    -------

    .. code-block:: python

       from whenever import LocalDateTime

       # always at 8:00 in the system timezone (e.g. America/Los_Angeles)
       wake_up = LocalDateTime(2020, 8, 15, hour=8, fold=0)

       # Conversion based on Los Angeles' offset
       wake_up.to_utc() == UTCDateTime(2020, 8, 15, hour=15)

       # If we change the system timezone, the result changes
       os.environ["TZ"] = "Europe/Amsterdam"
       wake_up.to_utc() == UTCDateTime(2020, 8, 15, hour=6)
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
        fold: Literal[0, 1],
    ) -> None:
        dt = _datetime(
            year, month, day, hour, minute, second, microsecond, fold=fold
        )
        # If it doesn't survive the UTC roundtrip, it doesn't exist
        if dt.astimezone(_UTC).astimezone(None).replace(tzinfo=None) != dt:
            raise DoesntExistInZone()
        self._py_dt = dt

    @classmethod
    def now(cls) -> LocalDateTime:
        """Create an instance from the current time"""
        return cls._from_py_unchecked(_datetime.now())

    def __str__(self) -> str:
        """Format as ``YYYY-MM-DDTHH:MM:SS(.ffffff)±HH:MM(:SS(.ffffff))``.
        The inverse of :meth:`from_str`.
        This format is both RFC 3339 and ISO 8601 compliant.

        Raises
        ------
        DoesntExistInZone
            In the rare case that the datetime does not exist in the
            system timezone (e.g. due to DST transitions). This is only
            possible if the system timezone is changed after initialization.

        Example
        -------

        .. code-block:: python

           # assuming system timezone is America/New_York
           d = LocalDateTime(2020, 8, 15, hour=23, minute=12, fold=0)
           assert str(d) == "2020-08-15T23:12:00-04:00"
        """
        if not self.exists():
            raise DoesntExistInZone()
        return self._py_dt.astimezone(None).isoformat()

    @classmethod
    def from_str(cls, s: str, /) -> LocalDateTime:
        """Create an instance from the format
        ``YYYY-MM-DDTHH:MM:SS(.fff(fff))±HH:MM(:SS(.ffffff))``.
        The inverse of :meth:`__str__`.


        Note
        ----
        ``T`` may be replaced with a single space

        Note
        ----
        The offset is needed to disambiguate cases where the same
        local time occurs twice due to DST transitions.

        Raises
        ------
        InvalidFormat
            If the string does not match the expected format.
        InvalidOffsetForZone
            If the given offset is not valid for the system timezone.

        Example
        -------
        .. code-block:: python

           # assuming system timezone is America/New_York
           d = LocalDateTime.from_str("2020-08-15T23:12:00-04:00")
           assert d == LocalDateTime(2020, 8, 15, 23, 12, fold=0)

           assert LocalDateTime.from_str(str(d)) == d

           # ValueError: no offset
           LocalDateTime.from_str("2020-08-15T23:12:00")
        """
        if not _match_offset_str(s):
            raise InvalidFormat()
        dt = _fromisoformat(s)
        # Determine `fold` from the offset
        offset = dt.utcoffset()
        dt = dt.replace(tzinfo=None)
        if offset != dt.astimezone(None).utcoffset():
            dt = dt.replace(fold=1)
            if dt.astimezone(None).utcoffset() != offset:
                raise InvalidOffsetForZone()
        return cls._from_py_unchecked(dt)

    if TYPE_CHECKING or SPHINX_BUILD:

        def timestamp(self) -> float:
            """The UNIX timestamp. Inverse of :meth:`from_timestamp`.

            Example
            -------

            .. code-block:: python

               # assuming system timezone is America/New_York
               assert LocalDateTime(1969, 12, 31, 19).timestamp() == 0

               ts = 1_123_000_000
               assert LocalDateTime.from_timestamp(ts).timestamp() == ts
            """
            return self._py_dt.timestamp()

    else:
        # This is slightly faster than a manual def
        timestamp = property(attrgetter("_py_dt.timestamp"))

    @classmethod
    def from_timestamp(cls, i: float, /) -> LocalDateTime:
        """Create an instace from a UNIX timestamp.
        The inverse of :meth:`timestamp`.

        Example
        -------

        .. code-block:: python

           # assuming system timezone is America/New_York
           assert LocalDateTime.from_timestamp(0) == LocalDateTime(1969, 12, 31, 19)
           d = LocalDateTime.from_timestamp(1_123_000_000.45)
           assert d == LocalDateTime(2004, 8, 2, 16, 26, 40, 450_000)

           assert LocalDateTime.from_timestamp(d.timestamp()) == d
        """
        return cls._from_py_unchecked(_fromtimestamp(i))

    @property
    def py(self) -> _datetime:
        """Get the underlying :class:`~datetime.datetime` object. Naive."""
        return self._py_dt

    @classmethod
    def from_py(cls, d: _datetime, /) -> LocalDateTime:
        """Create an instance from a :class:`~datetime.datetime` object.
        It must be a naive datetime (with ``tzinfo=None``).

        Inverse of :meth:`py`.

        Raises
        ------
        ValueError
            if the datetime is not naive.

        Example
        -------

        .. code-block:: python

           from datetime import datetime
           d = datetime(2020, 8, 15, hour=23)

           LocalDateTime.from_py(d) == LocalDateTime(2020, 8, 15, hour=23)

           # ValueError: not a naive datetime
           LocalDateTime.from_py(datetime(2020, 8, 15, hour=23, tzinfo=...))
        """
        if d.tzinfo is not None:
            raise ValueError(
                "Can only create LocalDateTime from a naive datetime, "
                f"got datetime with tzinfo={d.tzinfo!r}"
            )
        return cls._from_py_unchecked(d)

    def __repr__(self) -> str:
        try:
            return f"whenever.LocalDateTime({self})"
        except DoesntExistInZone:
            return f"whenever.LocalDateTime({self._py_dt.isoformat()}[nonexistent])"

    @property
    def offset(self) -> timedelta:
        """The UTC offset"""
        return self._py_dt.astimezone(None).utcoffset()  # type: ignore[return-value]

    if TYPE_CHECKING:

        @property
        def fold(self) -> Literal[0, 1]:
            """The fold value"""
            ...

    else:
        fold = property(attrgetter("_py_dt.fold"))

        def __eq__(self, other: object) -> bool:
            """Check if two datetimes occur at the same moment in time.

            Example
            -------
            .. code-block:: python

               # Same UTC time
               assert LocalDateTime(
                   2020, 8, 15, 23, fold=0
               ) == LocalDateTime(
                   2020, 8, 15, 23, fold=1
               )
            """
            if not isinstance(other, AwareDateTime):
                return NotImplemented
            return self._py_dt.astimezone(_UTC) == other._py_dt.astimezone(
                _UTC
            )

    def exact_eq(self, other: LocalDateTime) -> bool:
        """Compare if two datetimes have the exact same values.

        Note
        ----
        This does not compare the moment in time, but the exact values of the
        datetime fields. If ``a.exact_eq(b)`` is true, then
        ``a == b`` is also true, but the converse is not necessarily true.

        Example
        -------
        .. code-block:: python

           # same exact values
           assert LocalDateTime(
               2020, 8, 15, 23, fold=0
           ).exact_eq(
               LocalDateTime(2020, 8, 15, 23, fold=0)
           )
           # same moment in time, but different values
           assert not LocalDateTime(
               2020, 8, 15, 23, fold=0
           ).exact_eq(
               LocalDateTime(2020, 8, 15, 23, fold=1)
           )
        """
        return (
            self._py_dt == other._py_dt
            and self._py_dt.fold == other._py_dt.fold
        )

    min: ClassVar[LocalDateTime]
    """Small possible value"""
    max: ClassVar[LocalDateTime]
    """Biggest possible value"""

    tzinfo: ClassVar[None] = None

    if TYPE_CHECKING:
        # We could have used typing.Unpack, but that's only available
        # in Python 3.11+ or with typing_extensions.
        def replace(
            self,
            *,
            year: int | NOT_SET = NOT_SET(),
            month: int | NOT_SET = NOT_SET(),
            day: int | NOT_SET = NOT_SET(),
            hour: int | NOT_SET = NOT_SET(),
            minute: int | NOT_SET = NOT_SET(),
            second: int | NOT_SET = NOT_SET(),
            microsecond: int | NOT_SET = NOT_SET(),
            fold: Literal[0, 1] | NOT_SET = NOT_SET(),
        ) -> LocalDateTime:
            ...

    else:

        def replace(self, /, **kwargs) -> LocalDateTime:
            """Create a new instance with the given fields replaced

            Example
            -------

            .. code-block:: python

               d = LocalDateTime(2020, 8, 15, 23, 12, fold=0)
               assert d.replace(year=2021) == LocalDateTime(2021, 8, 15, 23, 12, fold=0)
            """
            if "tzinfo" in kwargs:
                raise TypeError("tzinfo is not an allowed argument")
            return self._from_py_unchecked(self._py_dt.replace(**kwargs))

    def __add__(self, other: timedelta) -> LocalDateTime:
        """Add a timedelta to this datetime

        Raises
        ------
        DateTimeDoesntExistInZone
            In the rare case that the datetime doesn't exist in the system
            timezone (e.g. due to DST transitions). This can only happen if
            the system timezone is changed since the datetime was created.
        ValueError
            If the result is outside the min/max range.
        OverflowError
            If the result lies far outside the supported range.

        Example
        -------
        .. code-block:: python

           d = LocalDateTime(2020, 8, 15, hour=23, minute=12, fold=0)
           assert d + timedelta(days=1, seconds=5) == LocalDateTime(
               2020, 8, 16, hour=23, minute=12, second=5, fold=0
           )
        """
        if not isinstance(other, timedelta):
            return NotImplemented
        return (self.to_utc() + other).to_local()

    if TYPE_CHECKING:

        @overload
        def __sub__(self, other: LocalDateTime) -> timedelta:
            ...

        @overload
        def __sub__(self, other: timedelta) -> LocalDateTime:
            ...

        def __sub__(
            self, other: LocalDateTime | timedelta
        ) -> LocalDateTime | timedelta:
            ...

    else:

        def __sub__(
            self, other: timedelta | LocalDateTime
        ) -> LocalDateTime | timedelta:
            """Subtract another datetime or timedelta

            Raises
            ------
            DateTimeDoesntExistInZone
                In the rare case that the datetime doesn't exist in the system
                timezone (e.g. due to DST transitions). This can only happen
                if the system timezone is changed since the datetime was created.

            Example
            -------
            .. code-block:: python

               d = LocalDateTime(2020, 8, 15, hour=23, minute=12, fold=0)
               assert d - timedelta(days=1, seconds=5) == LocalDateTime(
                   2020, 8, 14, hour=23, minute=11, second=55, fold=0
               )

            """
            if isinstance(other, LocalDateTime):
                as_utc = self._py_dt.astimezone(_UTC)
                if as_utc.astimezone(None).replace(tzinfo=None) != self._py_dt:
                    raise DoesntExistInZone()
                return as_utc - other._py_dt.astimezone(_UTC)
            elif isinstance(other, timedelta):
                return (self.to_utc() - other).to_local()
            return NotImplemented

    def is_ambiguous(self) -> bool:
        """Whether the datetime is ambiguous, i.e. ``fold`` has effect.

        Note
        ----
        Non-existent datetimes are not considered ambiguous.

        Example
        -------

        .. code-block:: python

           # assuming system timezone is Europe/Amsterdam
           assert not LocalDateTime(2020, 8, 15, 23, fold=0).is_ambiguous()
           assert LocalDateTime(2023, 10, 29, 2, 15, fold=0).is_ambiguous()
        """
        return (
            self._py_dt.astimezone(_UTC)
            != self._py_dt.replace(fold=not self._py_dt.fold).astimezone(_UTC)
            and self.exists()
        )

    def exists(self) -> bool:
        """Whether the datetime exists in the system timezone.
        This is only false in the rare case that the system timezone is
        changed since the datetime was created.

        Example
        -------

        .. code-block:: python

           os.environ["TZ"] = "America/New_York"
           d = LocalDateTime(2023, 3, 26, 2, 15, fold=0)
           assert d.exists()
           os.environ["TZ"] = "Europe/Amsterdam"
           assert not d.exists()
        """
        return (
            self._py_dt.astimezone(_UTC).astimezone(None).replace(tzinfo=None)
            == self._py_dt
        )

    def to_utc(self) -> UTCDateTime:
        """Convert to a :class:`UTCDateTime`

        Raises
        ------
        DateTimeDoesntExistInZone
            In the rare case that the datetime doesn't exist in the system
            timezone (e.g. due to DST transitions). This can only happen if
            the system timezone is changed since the datetime was created.

        Example
        -------

        .. code-block:: python

           # Assuming system timezone is Europe/Amsterdam
           d = LocalDateTime(2020, 8, 15, 23, fold=0)
           assert d.to_utc() == UTCDateTime(2020, 8, 15, 21)
        """
        dt = self._py_dt.astimezone(_UTC)
        # If the UTC round-trip fails, it means the datetime doesn't exist
        if dt.astimezone(None).replace(tzinfo=None) != self._py_dt:
            raise DoesntExistInZone()
        return UTCDateTime._from_py_unchecked(dt)

    @overload
    def to_offset(self, /) -> OffsetDateTime:
        ...

    @overload
    def to_offset(self, offset: timedelta, /) -> OffsetDateTime:
        ...

    def to_offset(self, offset: timedelta | None = None, /) -> OffsetDateTime:
        """Convert to a :class:`OffsetDateTime`.
        The result always evaluates to the same moment in time.

        Raises
        ------
        DateTimeDoesntExistInZone
            In the rare case that the datetime doesn't exist in the system
            timezone (e.g. due to DST transitions). This can only happen if
            the system timezone is changed since the datetime was created.

        Example
        -------

        .. code-block:: python

           from whenever import hours

           # Assuming system timezone is Europe/Amsterdam
           d = LocalDateTime(2020, 8, 15, 23, fold=0)
           assert d.to_offset()  # 2020-08-15T21:00:00+02:00
        """
        if not self.exists():
            raise DoesntExistInZone()
        return OffsetDateTime._from_py_unchecked(
            self._py_dt.astimezone(
                None if offset is None else _timezone(offset)
            )
        )

    def to_zoned(self, zone: str) -> ZonedDateTime:
        """Convert to a :class:`ZonedDateTime` in the given timezone.
        The result always evaluates to the same moment in time.

        Raises
        ------
        ~zoneinfo.ZoneInfoNotFoundError
            If the timezone name is not found in the IANA database.
        DoesntExistInZone
            In the rare case that the datetime doesn't exist in the system
            timezone (e.g. due to DST transitions). This can only happen if
            the system timezone is changed since the datetime was created.

        Example
        -------

        .. code-block:: python

           # Assuming system timezone is Europe/London
           d = LocalDateTime(2020, 8, 15, 23, fold=0)
           d.to_zoned("Europe/Paris") # 2020-08-16T00:00:00+02:00[Europe/Paris]
        """
        return ZonedDateTime._from_py_unchecked(
            self._py_dt.astimezone(ZoneInfo(zone))
        )

    def to_local(self) -> LocalDateTime:
        """Convert to an equivalent :class:`LocalDateTime` (no-op).
        Implemented for consistency with the other classes."""
        return self

    # a custom pickle implementation with a smaller payload
    def __reduce__(self) -> tuple[object, ...]:
        return (
            _local_unpickle,
            self._py_dt.timetuple()[:6]
            + (
                self._py_dt.microsecond,
                self._py_dt.fold,
            ),
        )


# A separate function is needed for unpickling, because the
# constructor doesn't accept positional fold arguments as
# required by __reduce__.
def _local_unpickle(
    year: int,
    month: int,
    day: int,
    hour: int,
    minute: int,
    second: int,
    microsecond: int,
    fold: Literal[0, 1],
) -> LocalDateTime:
    return LocalDateTime._from_py_unchecked(
        _datetime(
            year, month, day, hour, minute, second, microsecond, fold=fold
        )
    )


class NaiveDateTime(DateTime):
    """A plain datetime without timezone or offset.
    Useful when you need date and time, but without
    any of the real-world complexities."""

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

    if TYPE_CHECKING or SPHINX_BUILD:

        def __str__(self) -> str:
            """Format a NaiveDateTime as ``YYYY-MM-DDTHH:MM:SS[.ffffff]``.
            Inverse of :meth:`from_str`.

            This format is ISO 8601 compliant, but not RFC 3339 compliant,
            as this requires a UTC offset

            Example
            -------

            .. code-block:: python

               d = NaiveDateTime(2020, 8, 15, hour=23, minute=12)
               assert str(d) == "2020-08-15T23:12:00"

               assert NaiveDateTime.from_str(str(d)) == d

            """
            ...

    else:
        __str__ = property(attrgetter("_py_dt.isoformat"))

    @classmethod
    def from_str(cls, s: str, /) -> NaiveDateTime:
        """Create an instance from ``YYYY-MM-DDTHH:MM:SS(.fff(fff))``,
        raising :class:`ValueError` if the string does not match this
        exact format. The inverse of :meth:`__str__`.

        Note
        ----
        ``T`` may be replaced with a single space

        Example
        -------

        .. code-block:: python

           d = NaiveDateTime.from_str("2020-08-15T23:12:00")
           assert d == NaiveDateTime(2020, 8, 15, hour=23, minute=12)

           assert NaiveDateTime.from_str(str(d)) == d
           NaiveDateTime.from_str("2020-08-15T23:12")  # raises ValueError

        """
        if not _match_naive_str(s):
            raise ValueError("Invalid string")
        return cls._from_py_unchecked(_fromisoformat(s))

    @property
    def py(self) -> _datetime:
        """Get the underlying :class:`~datetime.datetime` object.
        Always timezone-naive. Inverse of :meth:`from_py`.

        Example
        -------
        .. code-block:: python

           d = NaiveDateTime(2020, 8, 15, hour=23, minute=12)
           d.py == datetime(2020, 8, 15, hour=23, minute=12)

           # inverse of from_py
           assert NaiveDateTime.from_py(d.py) == d
        """
        return self._py_dt

    @classmethod
    def from_py(cls, d: _datetime, /) -> NaiveDateTime:
        """Create an instance from a :class:`~datetime.datetime` object.
        It must be timezone-naive. Inverse of :meth:`py`.

        Raises
        ------
        ValueError
            if the datetime is timezone-aware.

        Example
        -------
        .. code-block:: python

           from datetime import datetime
           d = datetime(2020, 8, 15, hour=23)

           NaiveDateTime.from_py(d) == NaiveDateTime(2020, 8, 15, hour=23)

           # ValueError
           NaiveDateTime.from_py(datetime(2020, 8, 15, hour=23, tzinfo=UTC))
        """
        if d.tzinfo is not None:
            raise ValueError(
                "Can only create NaiveDateTime from a naive datetime, "
                f"got datetime with tzinfo={d.tzinfo!r}"
            )
        self = _object_new(NaiveDateTime)
        self._py_dt = d
        return self

    tzinfo: ClassVar[None] = None

    if TYPE_CHECKING:
        # We could have used typing.Unpack, but that's only available
        # in Python 3.11+ or with typing_extensions.
        def replace(
            self,
            *,
            year: int | NOT_SET = NOT_SET(),
            month: int | NOT_SET = NOT_SET(),
            day: int | NOT_SET = NOT_SET(),
            hour: int | NOT_SET = NOT_SET(),
            minute: int | NOT_SET = NOT_SET(),
            second: int | NOT_SET = NOT_SET(),
            microsecond: int | NOT_SET = NOT_SET(),
        ) -> NaiveDateTime:
            ...

    else:

        def replace(self, /, **kwargs) -> NaiveDateTime:
            """Create a new datetime with the given fields replaced

            Example
            -------

            .. code-block:: python

            d = NaiveDateTime(2020, 8, 15, 23, 12)
            assert d.replace(year=2021) == NaiveDateTime(2021, 8, 15, 23, 12)
            """
            if not _no_tzinfo_or_fold(kwargs):
                raise TypeError("tzinfo and fold are not allowed arguments")
            new = _object_new(NaiveDateTime)
            new._py_dt = self._py_dt.replace(**kwargs)
            return new

    min: ClassVar[NaiveDateTime]
    """Small possible value"""
    max: ClassVar[NaiveDateTime]
    """Biggest possible value"""

    # Hiding __eq__ from mypy ensures that --strict-equality works
    if not TYPE_CHECKING:  # pragma: no branch
        __hash__ = property(attrgetter("_py_dt.__hash__"))

        def __eq__(self, other: object) -> bool:
            """Compare two objects

            Example
            -------
            .. code-block:: python

               assert NaiveDateTime(2020, 8, 15, 23) == NaiveDateTime(2020, 8, 15, 23)

            """
            if not isinstance(other, NaiveDateTime):
                return NotImplemented
            return self._py_dt == other._py_dt

    def __lt__(self, other: NaiveDateTime) -> bool:
        """Compare two objects

        Example
        -------
        .. code-block:: python

           assert NaiveDateTime(2020, 8, 15, hour=23) < NaiveDateTime(2020, 8, 16)

        """
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

    def __add__(self, other: timedelta) -> NaiveDateTime:
        """Add a timedelta to this datetime

        Example
        -------
        .. code-block:: python

           d = NaiveDateTime(2020, 8, 15, hour=23, minute=12)
           assert d + timedelta(days=1, seconds=5) == NaiveDateTime(
               2020, 8, 16, hour=23, minute=12, second=5
           )
        """
        if not isinstance(other, timedelta):
            return NotImplemented
        new = _object_new(NaiveDateTime)
        new._py_dt = self._py_dt + other
        return new

    if TYPE_CHECKING:

        @overload
        def __sub__(self, other: NaiveDateTime) -> timedelta:
            ...

        @overload
        def __sub__(self, other: timedelta) -> NaiveDateTime:
            ...

        def __sub__(
            self, other: NaiveDateTime | timedelta
        ) -> NaiveDateTime | timedelta:
            ...

    else:

        def __sub__(
            self, other: timedelta | NaiveDateTime
        ) -> NaiveDateTime | timedelta:
            """Subtract another datetime or timedelta

            Example
            -------

            .. code-block:: python

               d = NaiveDateTime(2020, 8, 15, hour=23, minute=12)
               assert d - timedelta(days=1, seconds=5) == NaiveDateTime(
                   2020, 8, 14, hour=23, minute=11, second=55
               )

               assert d - NaiveDateTime(2020, 8, 14) > timedelta(days=1)
            """
            if isinstance(other, NaiveDateTime):
                return self._py_dt - other._py_dt
            elif isinstance(other, timedelta):
                new = _object_new(NaiveDateTime)
                new._py_dt = self._py_dt - other
                return new
            return NotImplemented

    def __repr__(self) -> str:
        return f"whenever.NaiveDateTime({self})"

    # a custom pickle implementation with a smaller payload
    def __reduce__(self) -> tuple[object, ...]:
        return (
            NaiveDateTime,
            self._py_dt.timetuple()[:6] + (self._py_dt.microsecond,),
        )


class Ambiguous(Exception):
    """A datetime is unexpectedly ambiguous"""


class DoesntExistInZone(Exception):
    """A datetime doesnt exist in a timezone, e.g. because of DST"""


class InvalidOffsetForZone(ValueError):
    """A string has an invalid offset for the given zone"""


class InvalidFormat(ValueError):
    """A string has an invalid format"""


def _exists_in_tz(d: _datetime) -> bool:
    # non-existent datetimes don't survive a round-trip to UTC
    return d.astimezone(_UTC).astimezone(d.tzinfo) == d


def _to_local(d: _datetime) -> _datetime:
    # Converting to local time results in a datetime with a fixed UTC
    # offset. To find the equivelant naive datetime, removing the
    # tzinfo is not enough, we need to make sure the fold is correct.
    offset = d.astimezone(None)
    naive = offset.replace(tzinfo=None)
    if naive.astimezone(_UTC) != offset.astimezone(_UTC):
        naive = naive.replace(fold=1)
    return naive


# Helpers that pre-compute/lookup as much as possible
_no_tzinfo_or_fold = {"tzinfo", "fold"}.isdisjoint
_object_new = object.__new__
# YYYY-MM-DD HH:MM:SS[.fff[fff]]
_DATETIME_RE = r"\d{4}-\d{2}-\d{2}[T ]\d{2}:\d{2}:\d{2}(?:\.(?:\d{3}|\d{6}))?"
# YYYY-MM-DD HH:MM:SS[.fff[fff]]±HH:MM[:SS[.ffffff]]
_OFFSET_RE = rf"{_DATETIME_RE}[+-]\d{{2}}:\d{{2}}(?::\d{{2}}(?:\.\d{{6}})?)?"
_match_utc_str = re.compile(rf"{_DATETIME_RE}Z").fullmatch
_match_naive_str = re.compile(_DATETIME_RE).fullmatch
_match_offset_str = re.compile(_OFFSET_RE).fullmatch
_match_zoned_str = re.compile(rf"({_OFFSET_RE})\[([^\]]+)\]").fullmatch
_fromisoformat = _datetime.fromisoformat
_fromtimestamp = _datetime.fromtimestamp
_zero_timezone = _timezone(timedelta())


# Before Python 3.11, fromisoformat doesn't support the Z suffix meaning UTC.
if sys.version_info < (3, 11):  # pragma: no cover

    def _fromisoformat_utc(s: str) -> _datetime:
        return _fromisoformat(s[:-1]).replace(tzinfo=_UTC)

else:
    _fromisoformat_utc = _fromisoformat


UTCDateTime.min = UTCDateTime.from_py(_datetime.min.replace(tzinfo=_UTC))
UTCDateTime.max = UTCDateTime.from_py(_datetime.max.replace(tzinfo=_UTC))
NaiveDateTime.min = NaiveDateTime.from_py(_datetime.min)
NaiveDateTime.max = NaiveDateTime.from_py(_datetime.max)
# Technically, we can further min/max by using almost 24 hour offset,
# but they'd overflow when converting to UTC.
OffsetDateTime.min = OffsetDateTime.from_py(
    _datetime.min.replace(tzinfo=_timezone(timedelta()))
)
OffsetDateTime.max = OffsetDateTime.from_py(
    _datetime.max.replace(tzinfo=_timezone(timedelta()))
)
# Technically, we can further min/max by using GMT+14 and GMT-12, but
# they'd overflow when converting to UTC.
ZonedDateTime.min = ZonedDateTime.from_py(
    _datetime.min.replace(tzinfo=ZoneInfo("UTC"))
)
ZonedDateTime.max = ZonedDateTime.from_py(
    _datetime.max.replace(tzinfo=ZoneInfo("UTC"))
)
# We buffer the min/max times by one day, to account for the possible
# system timezones.
LocalDateTime.min = LocalDateTime.from_py(_datetime.min + timedelta(1))
LocalDateTime.max = LocalDateTime.from_py(_datetime.max - timedelta(1))


def hours(i: int, /) -> timedelta:
    """Create a :class:`~datetime.timedelta` with the given number of hours.
    ``hours(1) == timedelta(hours=1)``
    """
    return timedelta(hours=i)


def minutes(i: int, /) -> timedelta:
    """Create a :class:`~datetime.timedelta` with the given number of minutes.
    ``minutes(1) == timedelta(minutes=1)``
    """
    return timedelta(minutes=i)
