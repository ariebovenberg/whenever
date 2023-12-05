from __future__ import annotations

import re
import sys
from datetime import date as _date
from datetime import datetime as _datetime
from datetime import time as _time
from datetime import timedelta
from datetime import timezone as _timezone
from datetime import tzinfo as _tzinfo
from operator import attrgetter
from typing import TYPE_CHECKING, ClassVar, Literal, overload

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
    "UTCDateTime",
    "OffsetDateTime",
    "ZonedDateTime",
    "PlainDateTime",
    "hours",
    "minutes",
]


class __NOTSET__:
    """Sentinel value for when no value is given"""


class UTCDateTime:
    """A UTC-only datetime. Useful for representing location-indepentent
    times in an unambiguous way.

    Example
    -------

    .. code-block:: python

       from whenever import UTCDateTime
       py311_release_livestream = UTCDateTime(2022, 10, 24, hour=17)
    """

    __slots__ = ("_py_dt", "__weakref__")
    _py_dt: _datetime

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

    @staticmethod
    def now() -> UTCDateTime:
        """Create a UTCDateTime from the current time

        Example
        -------

        .. code-block:: python

           now = UTCDateTime.now()
           later = UTCDateTime.now()
           assert later > now

        """
        self = _object_new(UTCDateTime)
        self._py_dt = _datetime_now(_UTC)
        return self

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

    @staticmethod
    def from_str(s: str, /) -> UTCDateTime:
        """Create a UTCDateTime from ``YYYY-MM-DDTHH:MM:SS(.fff(fff))Z``.
        The inverse of :meth:`__str__`.

        raises :class:`ValueError` if the string does not match this
        exact format.

        Note
        ----
        ``T`` may be replaced with a single space

        Example
        -------

        .. code-block:: python

           d = UTCDateTime.from_str("2020-08-15T23:12:00Z")
           assert d == UTCDateTime(2020, 8, 15, hour=23, minute=12)

           assert UTCDateTime.from_str(str(d)) == d

           UTCDateTime.from_str("2020-08-15T23:12")  # raises ValueError

        """
        if not _match_utc_str(s):
            raise ValueError("Invalid string")
        self = _object_new(UTCDateTime)
        self._py_dt = _fromisoformat_utc(s)
        return self

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

    @staticmethod
    def from_timestamp(i: float, /) -> UTCDateTime:
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
        self = _object_new(UTCDateTime)
        self._py_dt = _fromtimestamp(i, _UTC)
        return self

    def to_py(self) -> _datetime:
        """Get the underlying :class:`~datetime.datetime` object"""
        return self._py_dt

    @classmethod
    def from_py(cls, d: _datetime, /) -> UTCDateTime:
        """Create an instance from a :class:`~datetime.datetime` object.
        It must be timezone-aware and have the exact :attr:`~datetime.UTC`
        timezone.

        Inverse of :meth:`to_py`.

        Example
        -------

        .. code-block:: python

           from datetime import datetime, UTC
           d = datetime(2020, 8, 15, hour=23, tzinfo=UTC)

           UTCDateTime.from_py(d) == UTCDateTime(2020, 8, 15, hour=23)

           UTCDateTime.from_py(datetime(2020, 8, 15, hour=23))  # ValueError
        """
        if d.tzinfo is not _UTC:
            raise ValueError(
                "Can only create UTCDateTime from UTC datetime, "
                f"got datetime with tzinfo={d.tzinfo!r}"
            )
        self = _object_new(UTCDateTime)
        self._py_dt = d
        return self

    tzinfo: ClassVar[_tzinfo] = _UTC

    if TYPE_CHECKING:
        # We could have used typing.Unpack, but that's only available
        # in Python 3.11+ or with typing_extensions.
        def replace(
            self,
            *,
            year: int | __NOTSET__ = __NOTSET__(),
            month: int | __NOTSET__ = __NOTSET__(),
            day: int | __NOTSET__ = __NOTSET__(),
            hour: int | __NOTSET__ = __NOTSET__(),
            minute: int | __NOTSET__ = __NOTSET__(),
            second: int | __NOTSET__ = __NOTSET__(),
            microsecond: int | __NOTSET__ = __NOTSET__(),
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
            new = _object_new(UTCDateTime)
            new._py_dt = self._py_dt.replace(**kwargs)
            return new

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

        def __hash__(self) -> int:
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
        __hash__ = property(attrgetter("_py_dt.__hash__"))

    resolution: ClassVar[timedelta] = _datetime.resolution
    """Alias for :attr:`datetime.datetime.resolution`"""
    min: ClassVar[UTCDateTime]
    """Small possible value"""
    max: ClassVar[UTCDateTime]
    """Biggest possible value"""

    # Hiding __eq__ from mypy ensures that --strict-equality works
    if not TYPE_CHECKING:  # pragma: no branch

        def __eq__(self, other: object) -> bool:
            """Compare two objects

            Example
            -------
            .. code-block:: python

               assert UTCDateTime(2020, 8, 15, 23) == UTCDateTime(2020, 8, 15, 23)

            """  # noqa: E501
            if not isinstance(other, UTCDateTime):
                return NotImplemented
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
        new = _object_new(UTCDateTime)
        new._py_dt = self._py_dt + other
        return new

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
                new = _object_new(UTCDateTime)
                new._py_dt = self._py_dt - other
                return new
            return NotImplemented

    def __repr__(self) -> str:
        return f"whenever.UTCDateTime({self})"

    # a custom pickle implementation with a smaller payload
    def __reduce__(self) -> tuple[object, ...]:
        return (
            UTCDateTime,
            self._py_dt.timetuple()[:6] + (self.microsecond,),
        )


class PlainDateTime:
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
            """Format a PlainDateTime as ``YYYY-MM-DDTHH:MM:SS[.ffffff]``.
            Inverse of :meth:`from_str`.

            This format is ISO 8601 compliant, but not RFC 3339 compliant,
            as this requires a UTC offset

            Example
            -------

            .. code-block:: python

               d = PlainDateTime(2020, 8, 15, hour=23, minute=12)
               assert str(d) == "2020-08-15T23:12:00"

               assert PlainDateTime.from_str(str(d)) == d

            """
            ...

    else:
        __str__ = property(attrgetter("_py_dt.isoformat"))

    @staticmethod
    def from_str(s: str, /) -> PlainDateTime:
        """Create an instance from ``YYYY-MM-DDTHH:MM:SS[.fff[fff]]``,
        raising :class:`ValueError` if the string does not match this
        exact format. The inverse of :meth:`__str__`.

        Note
        ----
        ``T`` may be replaced with a single space

        Example
        -------

        .. code-block:: python

           d = PlainDateTime.from_str("2020-08-15T23:12:00")
           assert d == PlainDateTime(2020, 8, 15, hour=23, minute=12)

           assert PlainDateTime.from_str(str(d)) == d
           PlainDateTime.from_str("2020-08-15T23:12")  # raises ValueError

        """
        if not _match_plain_str(s):
            raise ValueError("Invalid string")
        self = _object_new(PlainDateTime)
        self._py_dt = _fromisoformat(s)
        return self

    def to_py(self) -> _datetime:
        """Get the underlying :class:`~datetime.datetime` object.
        Inverse of :meth:`from_py`.

        Example
        -------
        .. code-block:: python

           d = PlainDateTime(2020, 8, 15, hour=23, minute=12)
           assert d.to_py() == datetime(2020, 8, 15, hour=23, minute=12)

           assert PlainDateTime.from_py(d.to_py()) == d
        """
        return self._py_dt

    @classmethod
    def from_py(cls, d: _datetime, /) -> PlainDateTime:
        """Create an instance from a :class:`~datetime.datetime` object.
        It must be timezone-naive. Inverse of :meth:`to_py`.

        Example
        -------
        .. code-block:: python

           from datetime import datetime
           d = datetime(2020, 8, 15, hour=23)

           PlainDateTime.from_py(d) == PlainDateTime(2020, 8, 15, hour=23)

           # ValueError
           PlainDateTime.from_py(datetime(2020, 8, 15, hour=23, tzinfo=UTC))
        """
        if d.tzinfo is not None:
            raise ValueError(
                "Can only create PlainDateTime from a naive datetime, "
                f"got datetime with tzinfo={d.tzinfo!r}"
            )
        self = _object_new(PlainDateTime)
        self._py_dt = d
        return self

    tzinfo: ClassVar[None] = None

    if TYPE_CHECKING:
        # We could have used typing.Unpack, but that's only available
        # in Python 3.11+ or with typing_extensions.
        def replace(
            self,
            *,
            year: int | __NOTSET__ = __NOTSET__(),
            month: int | __NOTSET__ = __NOTSET__(),
            day: int | __NOTSET__ = __NOTSET__(),
            hour: int | __NOTSET__ = __NOTSET__(),
            minute: int | __NOTSET__ = __NOTSET__(),
            second: int | __NOTSET__ = __NOTSET__(),
            microsecond: int | __NOTSET__ = __NOTSET__(),
        ) -> PlainDateTime:
            ...

    else:

        def replace(self, /, **kwargs) -> PlainDateTime:
            """Create a new datetime with the given fields replaced

            Example
            -------

            .. code-block:: python

            d = PlainDateTime(2020, 8, 15, 23, 12)
            assert d.replace(year=2021) == PlainDateTime(2021, 8, 15, 23, 12)
            """
            if not _no_tzinfo_or_fold(kwargs):
                raise TypeError("tzinfo and fold are not allowed arguments")
            new = _object_new(PlainDateTime)
            new._py_dt = self._py_dt.replace(**kwargs)
            return new

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
            """The day of the week as an integer (Monday=0, Sunday=6)

            Example
            -------

            .. code-block:: python

                assert UTCDateTime(2022, 10, 25).weekday() == 1
            """
            ...

        def date(self) -> _date:
            """The :class:`~datetime.date` part of the datetime

            Example
            -------
            .. code-block:: python

                d = UTCDateTime(2020, 8, 15, hour=23, minute=12)
                assert d.date() == date(2020, 8, 15)

            """
            ...

        def time(self) -> _time:
            """The :class:`~datetime.time` part of the datetime

            Example
            -------
            .. code-block:: python

                d = UTCDateTime(2020, 8, 15, hour=23, minute=12)
                assert d.time() == time(23, 12)
            """
            ...

        def __hash__(self) -> int:
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
        __hash__ = property(attrgetter("_py_dt.__hash__"))

    resolution: ClassVar[timedelta] = _datetime.resolution
    """Alias for :attr:`datetime.datetime.resolution`"""
    min: ClassVar[PlainDateTime]
    """Small possible value"""
    max: ClassVar[PlainDateTime]
    """Biggest possible value"""

    # Hiding __eq__ from mypy ensures that --strict-equality works
    if not TYPE_CHECKING:  # pragma: no branch

        def __eq__(self, other: object) -> bool:
            """Compare two objects

            Example
            -------
            .. code-block:: python

               assert PlainDateTime(2020, 8, 15, 23) == PlainDateTime(2020, 8, 15, 23)

            """  # noqa: E501
            if not isinstance(other, PlainDateTime):
                return NotImplemented
            return self._py_dt == other._py_dt

    def __lt__(self, other: PlainDateTime) -> bool:
        """Compare two objects

        Example
        -------
        .. code-block:: python

           assert PlainDateTime(2020, 8, 15, hour=23) < PlainDateTime(2020, 8, 16)

        """  # noqa: E501
        if not isinstance(other, PlainDateTime):
            return NotImplemented
        return self._py_dt < other._py_dt

    def __le__(self, other: PlainDateTime) -> bool:
        if not isinstance(other, PlainDateTime):
            return NotImplemented
        return self._py_dt <= other._py_dt

    def __gt__(self, other: PlainDateTime) -> bool:
        if not isinstance(other, PlainDateTime):
            return NotImplemented
        return self._py_dt > other._py_dt

    def __ge__(self, other: PlainDateTime) -> bool:
        if not isinstance(other, PlainDateTime):
            return NotImplemented
        return self._py_dt >= other._py_dt

    def __add__(self, other: timedelta) -> PlainDateTime:
        """Add a timedelta to this datetime

        Example
        -------
        .. code-block:: python

           d = PlainDateTime(2020, 8, 15, hour=23, minute=12)
           assert d + timedelta(days=1, seconds=5) == PlainDateTime(
               2020, 8, 16, hour=23, minute=12, second=5
           )
        """
        if not isinstance(other, timedelta):
            return NotImplemented
        new = _object_new(PlainDateTime)
        new._py_dt = self._py_dt + other
        return new

    if TYPE_CHECKING:

        @overload
        def __sub__(self, other: PlainDateTime) -> timedelta:
            ...

        @overload
        def __sub__(self, other: timedelta) -> PlainDateTime:
            ...

        def __sub__(
            self, other: PlainDateTime | timedelta
        ) -> PlainDateTime | timedelta:
            ...

    else:

        def __sub__(
            self, other: timedelta | PlainDateTime
        ) -> PlainDateTime | timedelta:
            """Subtract another datetime or timedelta

            Example
            -------

            .. code-block:: python

               d = PlainDateTime(2020, 8, 15, hour=23, minute=12)
               assert d - timedelta(days=1, seconds=5) == PlainDateTime(
                   2020, 8, 14, hour=23, minute=11, second=55
               )

               assert d - PlainDateTime(2020, 8, 14) > timedelta(days=1)
            """
            if isinstance(other, PlainDateTime):
                return self._py_dt - other._py_dt
            elif isinstance(other, timedelta):
                new = _object_new(PlainDateTime)
                new._py_dt = self._py_dt - other
                return new
            return NotImplemented

    def __repr__(self) -> str:
        return f"whenever.PlainDateTime({self})"

    # a custom pickle implementation with a smaller payload
    def __reduce__(self) -> tuple[object, ...]:
        return (
            PlainDateTime,
            self._py_dt.timetuple()[:6] + (self.microsecond,),
        )


class OffsetDateTime:
    """A datetime with a fixed UTC offset.

    Useful for representing the local time at a specific location.

    Example
    -------

    .. code-block:: python

       from whenever import OffsetDateTime, hours
       # 9 AM in Salt Lake City, with the UTC offset at the time
       pycon23_started = OffsetDateTime(2023, 4, 21, hour=9, offset=hours(-6))
    """

    __slots__ = ("_py_dt", "__weakref__")
    _py_dt: _datetime

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

    @staticmethod
    def now(offset: timedelta) -> OffsetDateTime:
        """Create an OffsetDateTime from the current time

        Example
        -------

        .. code-block:: python

           now = OffsetDateTime.now(offset=hours(2))
           later = OffsetDateTime.now(offset=hours(3))
           assert later > now

        """
        self = _object_new(OffsetDateTime)
        self._py_dt = _datetime_now(_timezone(offset))
        return self

    def __str__(self) -> str:
        """Format a OffsetDateTime as ``YYYY-MM-DDTHH:MM:SS[.ffffff]±HH:MM``.

        This format is both RFC 3339 and ISO 8601 compliant.

        The inverse of :meth:`from_str`.

        Example
        -------

        .. code-block:: python

           d = OffsetDateTime(2020, 8, 15, hour=23, minute=12, offset=hours(1))
           assert str(d) == "2020-08-15T23:12:00+01:00"

        """
        return self._py_dt.isoformat()

    @staticmethod
    def from_str(s: str, /) -> OffsetDateTime:
        """Create a OffsetDateTime from
        ``YYYY-MM-DDTHH:MM:SS[.fff[fff]]±HH:MM[:SS[.ffffff]]``,
        raising :class:`ValueError` if the string does not match this
        exact format. The inverse of :meth:`__str__`.

        Note
        ----
        ``T`` may be replaced with a single space

        Example
        -------

        .. code-block:: python

           d = OffsetDateTime.from_str("2020-08-15T23:12:00Z")
           assert d == OffsetDateTime(2020, 8, 15, hour=23, minute=12)

           assert OffsetDateTime.from_str(str(d)) == d

           OffsetDateTime.from_str("2020-08-15T23:12")  # raises ValueError

        """
        if not _match_offset_str(s):
            raise ValueError("Invalid string")
        self = _object_new(OffsetDateTime)
        self._py_dt = _fromisoformat(s)
        return self

    if TYPE_CHECKING or SPHINX_BUILD:

        def timestamp(self) -> float:
            """The UNIX timestamp. Inverse of :meth:`from_timestamp`.

            Example
            -------

            .. code-block:: python

               assert OffsetDateTime(1970, 1, 1, 3, offset=hours(3)).timestamp() == 0

               ts = 1_123_000_000
               assert OffsetDateTime.from_timestamp(ts, offset=hours(-2)).timestamp() == ts
            """  # noqa: E501
            ...

    else:
        timestamp = property(attrgetter("_py_dt.timestamp"))

    @staticmethod
    def from_timestamp(i: float, /, offset: timedelta) -> OffsetDateTime:
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
        """  # noqa: E501
        self = _object_new(OffsetDateTime)
        self._py_dt = _fromtimestamp(i, _timezone(offset))
        return self

    def to_py(self) -> _datetime:
        """Get the underlying :class:`~datetime.datetime` object"""
        return self._py_dt

    @classmethod
    def from_py(cls, d: _datetime, /) -> OffsetDateTime:
        """Create an instance from a :class:`~datetime.datetime` object.

        It must be timezone-aware and have a fixed :class:`datetime.timezone`
        tzinfo. Inverse of :meth:`to_py`.

        Example
        -------

        .. code-block:: python

           from datetime import datetime, timezone, timedelta
           d = datetime(2020, 8, 15, 23, tzinfo=timezone(timedelta(hours=2)))

           OffsetDateTime.from_py(d) == OffsetDateTime(2020, 8, 15, 23, offset=hours(2))

           # ValueError: no tzinfo
           OffsetDateTime.from_py(datetime(2020, 8, 15, 23))
        """  # noqa: E501
        if not isinstance(d.tzinfo, _timezone):
            raise ValueError(
                "Datetime's tzinfo is not a datetime.timezone, "
                f"got tzinfo={d.tzinfo!r}"
            )
        self = _object_new(OffsetDateTime)
        self._py_dt = d
        return self

    if TYPE_CHECKING or SPHINX_BUILD:

        @property
        def tzinfo(self) -> _tzinfo:
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
            year: int | __NOTSET__ = __NOTSET__(),
            month: int | __NOTSET__ = __NOTSET__(),
            day: int | __NOTSET__ = __NOTSET__(),
            hour: int | __NOTSET__ = __NOTSET__(),
            minute: int | __NOTSET__ = __NOTSET__(),
            second: int | __NOTSET__ = __NOTSET__(),
            microsecond: int | __NOTSET__ = __NOTSET__(),
            offset: timedelta | __NOTSET__ = __NOTSET__(),
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
            """  # noqa: E501
            if not _no_tzinfo_or_fold(kwargs):
                raise TypeError("tzinfo and fold are not allowed arguments")

            try:
                kwargs["tzinfo"] = _timezone(kwargs.pop("offset"))
            except KeyError:
                pass
            new = _object_new(OffsetDateTime)
            new._py_dt = self._py_dt.replace(**kwargs)
            return new

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
            """The day of the week as an integer (Monday=0, Sunday=6)

            Example
            -------

            .. code-block:: python

                assert OffsetDateTime(2022, 10, 25, offset=hours(1)).weekday() == 1
            """  # noqa: E501
            ...

        def date(self) -> _date:
            """The :class:`~datetime.date` part of the datetime

            Example
            -------
            .. code-block:: python

                d = OffsetDateTime(2020, 8, 15, hour=23, offset=hours(1))
                assert d.date() == date(2020, 8, 15)

            """
            ...

        def time(self) -> _time:
            """The :class:`~datetime.time` part of the datetime

            Example
            -------
            .. code-block:: python

                d = OffsetDateTime(2020, 8, 15, hour=23, minute=12, offset=hours(1))
                assert d.time() == time(23, 12)
            """  # noqa: E501
            ...

        def __hash__(self) -> int:
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
        __hash__ = property(attrgetter("_py_dt.__hash__"))

    resolution: ClassVar[timedelta] = _datetime.resolution
    """Alias for :attr:`datetime.datetime.resolution`"""
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

        def __eq__(self, other: object) -> bool:
            """Compare two objects

            Example
            -------
            .. code-block:: python

               assert OffsetDateTime(
                   2020, 8, 15, 23, offset=hours(4)
               ) == OffsetDateTime(
                   2020, 8, 14, 23, offset=hours(3)
               )

            """  # noqa: E501
            if not isinstance(other, OffsetDateTime):
                return NotImplemented
            return self._py_dt == other._py_dt

    def __lt__(self, other: OffsetDateTime) -> bool:
        """Compare two objects

        Example
        -------
        .. code-block:: python

           assert OffsetDateTime(2020, 8, 15, hour=23, offset=hours(2)) < (
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
        """  # noqa: E501
        if not isinstance(other, OffsetDateTime):
            return NotImplemented
        return self._py_dt - other._py_dt

    def __repr__(self) -> str:
        return f"whenever.OffsetDateTime({self})"

    # a custom pickle implementation with a smaller payload
    def __reduce__(self) -> tuple[object, ...]:
        return (
            _offset_unpickle,
            self._py_dt.timetuple()[:6] + (self.microsecond, self.offset),
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
    self = _object_new(OffsetDateTime)
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
    return self


class ZonedDateTime:
    """A datetime associated with a timezone

    Useful for representing the local time bound to a specific location.

    Note
    ----
    The ``zone`` argument is the timezone's ID in the IANA database.

    A :class:`zoneinfo.ZoneInfoNotFoundError` is raised if the zone is
    not found.
    A :class:`DateTimeDoesntExistInZone` is raised if the datetime does
    not exist in the given timezone (e.g. due to DST transitions).

    Example
    -------

    .. code-block:: python

       from whenever import ZonedDateTime

       # always at 11:00 in London, regardless of the offset
       changing_the_guard = ZonedDateTime(
           2024, 12, 8, hour=11, zone="Europe/London", fold=0
       )

       # raises ZoneInfoNotFoundError
       ZonedDateTime(2024, 12, 8, hour=11, zone="invalid", fold=0)

       # raises DateTimeDoesntExistInZone
       ZonedDateTime(2023, 3, 26, 2, 15, zone="Europe/Amsterdam", fold=0)
    """

    __slots__ = ("_py_dt", "__weakref__")
    _py_dt: _datetime

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
        fold: Literal[0, 1],
    ) -> None:
        dt = _datetime(
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
        if not _exists_in_tz(dt):
            raise DateTimeDoesntExistInZone()
        self._py_dt = dt

    @staticmethod
    def expect_unambiguous(
        year: int,
        month: int,
        day: int,
        hour: int = 0,
        minute: int = 0,
        second: int = 0,
        microsecond: int = 0,
        *,
        zone: str,
    ) -> ZonedDateTime:
        """Create a ZonedDateTime from a datetime you expect to be unambiguous.

        raises :class:`DateTimeIsAmbiguous` if the datetime turns out ambiguous.
        or :class:`DateTimeDoesntExistInZone` if the datetime does not exist.

        Example
        -------

        .. code-block:: python

           from whenever import ZonedDateTime, DateTimeIsAmbiguous

           d = ZonedDateTime.expect_unambiguous(
                2020, 7, 25, zone="Europe/London"
           )

           # raises DateTimeIsAmbiguous
           ZonedDateTime.expect_unambiguous(
                2023, 10, 29, 2, 15, zone="Europe/Amsterdam"
           )
        """  # noqa: E501
        new = _datetime(
            year, month, day, hour, minute, second, microsecond, ZoneInfo(zone)
        )
        if not _exists_in_tz(new):
            raise DateTimeDoesntExistInZone()
        if new.astimezone(_UTC) != new.replace(fold=1).astimezone(_UTC):
            raise DateTimeIsAmbiguous()
        self = _object_new(ZonedDateTime)
        self._py_dt = new
        return self

    @staticmethod
    def now(zone: str) -> ZonedDateTime:
        """Create an instance from the current time

        raises :class:`zoneinfo.ZoneInfoNotFoundError` if the timezone
        name is not found in the IANA database.

        Example
        -------

        .. code-block:: python

           now = ZonedDateTime.now("Europe/London")
           later = ZonedDateTime.now("Asia/Tokyo")
           assert later > now

        """
        self = _object_new(ZonedDateTime)
        self._py_dt = _datetime_now(ZoneInfo(zone))
        return self

    def __str__(self) -> str:
        """Format as ``YYYY-MM-DDTHH:MM:SS(.ffffff)±HH:MM(:SS(.ffffff))[TIMEZONE]``,
        for example: ``2020-08-15T23:12:00+01:00[Europe/London]``.

        Warning
        -------
        This format is *not* RFC 3339 or ISO 8601 compliant,
        because these only allow a fixed UTC offset.
        Convert to :class:`OffsetDateTime` first if you need this.

        Example
        -------
        .. code-block:: python

           d = ZonedDateTime(2020, 8, 15, 23, 12, zone="Europe/London", fold=0)
           assert str(d) == "2020-08-15T23:12:00+01:00[Europe/London]"

        """  # noqa: E501
        return (
            f"{self._py_dt.isoformat()}"
            f"[{self._py_dt.tzinfo.key}]"  # type: ignore[union-attr]
        )

    @staticmethod
    def from_str(s: str, /) -> ZonedDateTime:
        """Create a ZonedDateTime from
        ``YYYY-MM-DDTHH:MM:SS(.fff(fff))±HH:MM(:SS(.ffffff))[TIMEZONE]``,
        for example: ``2020-08-15T23:12:00+01:00[Europe/London]``.
        The inverse of :meth:`__str__`.

        Raises :class:`ValueError` if the string does not match this
        exact format.

        Raises :class:`zoneinfo.ZoneInfoNotFoundError` if the timezone
        name is not found in the IANA database.

        Note
        ----
        ``T`` may be replaced with a single space

        Example
        -------

        .. code-block:: python

           d = ZonedDateTime.from_str("2020-08-15T23:12:00+01:00[Europe/Rome]")
           assert d == ZonedDateTime(2020, 8, 15, 23, 12, zone="Europe/Rome")

           assert ZonedDateTime.from_str(str(d)) == d

           # raises ValueError (no offset)
           ZonedDateTime.from_str("2020-08-15T23:12[Europe/Rome]")
           # raises ZoneInfoNotFoundError
           ZonedDateTime.from_str("2020-08-15T23:12:00+01:00[invalid]")

        """
        if (match := _match_zoned_str(s)) is None:
            raise ValueError("Invalid string")
        self = _object_new(ZonedDateTime)
        dt = _fromisoformat(match[1])
        offset = dt.utcoffset()
        self._py_dt = dt = dt.replace(tzinfo=ZoneInfo(match[2]))
        if offset != dt.utcoffset():  # offset/zone mismatch: try other fold
            self._py_dt = dt = dt.replace(fold=1)
            if dt.utcoffset() != offset:
                raise ValueError(f"Offset/timezone mismatch in {s!r}")
        return self

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

    @staticmethod
    def from_timestamp(i: float, /, zone: str) -> ZonedDateTime:
        """Create an instace from a UNIX timestamp.
        The inverse of :meth:`timestamp`.

        raises :class:`zoneinfo.ZoneInfoNotFoundError` if the timezone
        name is not found in the IANA database.

        Example
        -------

        .. code-block:: python

           assert ZonedDateTime.from_timestamp(
               0, zone="Iceland"
           ) == ZonedDateTime(1970, 1, 1, zone="Iceland", fold=0)
           d = ZonedDateTime.from_timestamp(1_123_000_000.45, zone="Iceland")
           assert d == UTCDateTime(2004, 8, 2, 16, 26, 40, 450_000)

           assert UTCDateTime.from_timestamp(d.timestamp()) == d

           d = ZonedDateTime.from_timestamp(1_123_000_000.45, zone="America/Nuuk")
           assert d == ZonedDateTime(
               2004, 8, 2, 14, 26, 40, 450_000, zone="America/Nuuk", fold=0
           )

           assert ZonedDateTime.from_timestamp(d.timestamp(), d.zone) == d
        """  # noqa: E501
        self = _object_new(ZonedDateTime)
        self._py_dt = _fromtimestamp(i, ZoneInfo(zone))
        return self

    def to_py(self) -> _datetime:
        """Get the underlying :class:`~datetime.datetime` object"""
        return self._py_dt

    @classmethod
    def from_py(cls, d: _datetime, /) -> ZonedDateTime:
        """Create an instance from a :class:`~datetime.datetime` object.
        It must be timezone-aware and have a :class:`~zoneinfo.ZoneInfo`
        tzinfo.

        raises :class:`ValueError` if the datetime's tzinfo is not a
        :class:`~zoneinfo.ZoneInfo`.

        raises :class:`DateTimeDoesntExistInZone` if the datetime does
        not exist in the given timezone (e.g. due to DST transitions).

        Inverse of :meth:`to_py`.

        Example
        -------

        .. code-block:: python

           from datetime import datetime, UTC
           from zoneinfo import ZoneInfo
           d = datetime(2020, 8, 15, hour=23, tzinfo=ZoneInfo("Asia/Tokyo"))

           ZonedDateTime.from_py(d) == ZonedDateTime(
               2020, 8, 15, hour=23, zone="Asia/Tokyo", fold=0
           )

           # ValueError: invalid tzinfo
           ZonedDateTime.from_py(datetime(2020, 8, 15, hour=23, tzinfo=UTC))

           # DateTimeDoesntExistInZone
           ZonedDateTime.from_py(datetime(2023, 3, 26, 2, 15,
                                          tzinfo=ZoneInfo("Europe/Amsterdam")))
        """
        if not isinstance(d.tzinfo, ZoneInfo):
            raise ValueError(
                "Can only create ZonedDateTime from ZoneInfo, "
                f"got datetime with tzinfo={d.tzinfo!r}"
            )
        if not _exists_in_tz(d):
            raise DateTimeDoesntExistInZone()
        self = _object_new(ZonedDateTime)
        self._py_dt = d
        return self

    if TYPE_CHECKING:
        # We could have used typing.Unpack, but that's only available
        # in Python 3.11+ or with typing_extensions.
        def replace(
            self,
            *,
            year: int | __NOTSET__ = __NOTSET__(),
            month: int | __NOTSET__ = __NOTSET__(),
            day: int | __NOTSET__ = __NOTSET__(),
            hour: int | __NOTSET__ = __NOTSET__(),
            minute: int | __NOTSET__ = __NOTSET__(),
            second: int | __NOTSET__ = __NOTSET__(),
            microsecond: int | __NOTSET__ = __NOTSET__(),
            zone: str | __NOTSET__ = __NOTSET__(),
            fold: Literal[0, 1] | __NOTSET__ = __NOTSET__(),
        ) -> ZonedDateTime:
            ...

    else:

        def replace(self, /, **kwargs) -> ZonedDateTime:
            """Create a new instance with the given fields replaced

            raises :class:`zoneinfo.ZoneInfoNotFoundError` if the timezone
            name is not found in the IANA database.

            raises :class:`DateTimeDoesntExistInZone` if the datetime with new values
            does not exist in the given timezone (e.g. due to DST transitions).

            Example
            -------

            .. code-block:: python

               d = ZonedDateTime(2020, 8, 15, 23, 12, zone="Iceland", fold=0)
               assert d.replace(year=2021) == ZonedDateTime(2021, 8, 15, 23, 12, zone="Iceland", fold=0)
            """  # noqa: E501
            if "tzinfo" in kwargs:
                raise TypeError("tzinfo is not an allowed argument")
            try:
                kwargs["tzinfo"] = ZoneInfo(kwargs.pop("zone"))
            except KeyError:
                pass
            new = _object_new(ZonedDateTime)
            new._py_dt = dt = self._py_dt.replace(**kwargs)
            if not _exists_in_tz(dt):
                raise DateTimeDoesntExistInZone()
            return new

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

        @property
        def zone(self) -> str:
            """The timezone's ID (in the IANA database)"""
            ...

        @property
        def fold(self) -> Literal[0, 1]:
            """The fold"""
            ...

        @property
        def tzinfo(self) -> _tzinfo:
            """The tzinfo object"""
            ...

        def weekday(self) -> int:
            """The day of the week as an integer (Monday=0, Sunday=6)"""
            ...

        def date(self) -> _date:
            """The :class:`~datetime.date` part of the datetime"""
            ...

        def time(self) -> _time:
            """The :class:`~datetime.time` part of the datetime"""  # noqa: E501
            ...

    else:
        year = property(attrgetter("_py_dt.year"))
        month = property(attrgetter("_py_dt.month"))
        day = property(attrgetter("_py_dt.day"))
        hour = property(attrgetter("_py_dt.hour"))
        minute = property(attrgetter("_py_dt.minute"))
        second = property(attrgetter("_py_dt.second"))
        microsecond = property(attrgetter("_py_dt.microsecond"))
        zone = property(attrgetter("_py_dt.tzinfo.key"))
        fold = property(attrgetter("_py_dt.fold"))
        tzinfo = property(attrgetter("_py_dt.tzinfo"))
        weekday = property(attrgetter("_py_dt.weekday"))
        date = property(attrgetter("_py_dt.date"))
        time = property(attrgetter("_py_dt.time"))

    def __hash__(self) -> int:
        # Consistent with __eq__, see comments there.
        return hash(self._py_dt.astimezone(_UTC))

    resolution: ClassVar[timedelta] = _datetime.resolution
    """Alias for :attr:`datetime.datetime.resolution`"""
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
            :meth:`structural_eq` instead.

            Example
            -------
            .. code-block:: python

               assert ZonedDateTime(
                   2020, 8, 15, 23, zone="Europe/London"
               ) == ZonedDateTime(
                   2020, 8, 16, zone="Europe/Paris"
               )

            """
            if not isinstance(other, ZonedDateTime):
                return NotImplemented

            # We can't rely on simple equality, because it isn't equal
            # between two datetimes with different timezones if one of the
            # datetimes needs fold to disambiguate it.
            # See peps.python.org/pep-0495/#aware-datetime-equality-comparison.
            # We want to avoid this legacy edge case, so we normalize to UTC.
            return self._py_dt.astimezone(_UTC) == other._py_dt.astimezone(
                _UTC
            )

    def structural_eq(self, other: ZonedDateTime) -> bool:
        """Compare if two datetimes have the exact same values.

        Note
        ----
        This does not compare the moment in time, but the exact values of the
        datetime fields. If ``a.structural_eq(b)`` is true, then
        ``a == b`` is also true, but the converse is not necessarily true.

        Example
        -------

        .. code-block:: python

           # same exact values
           assert ZonedDateTime(
               2020, 8, 15, 23, zone="Europe/London"
           ).structural_eq(
               ZonedDateTime(2020, 8, 15, 22, zone="Europe/London")
           )
           # same moment in time, but different values
           assert not ZonedDateTime(
               2020, 8, 15, 23, zone="Europe/London"
           ).structural_eq(
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

           assert ZonedDateTime(2020, 8, 15, 12, zone="Asia/Tokyo", fold=0) < (
               ZonedDateTime(2020, 8, 15, zone="America/Los_Angeles", fold=0)
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

           d = ZonedDateTime(2023, 10, 29, 23, 12, zone="Europe/Amsterdam", fold=0)
           # one hour skipped due to DST transition
           assert d + timedelta(hours=24) == ZonedDateTime(
               2023, 10, 30, 22, 12, zone="Europe/Amsterdam", fold=0
           )
        """  # noqa: E501
        if not isinstance(delta, timedelta):
            return NotImplemented
        new = _object_new(ZonedDateTime)
        new._py_dt = (self._py_dt.astimezone(_UTC) + delta).astimezone(
            self._py_dt.tzinfo
        )
        return new

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
                new = _object_new(ZonedDateTime)
                new._py_dt = (self._py_dt.astimezone(_UTC) - other).astimezone(
                    self._py_dt.tzinfo
                )
                return new
            return NotImplemented

    def is_ambiguous(self) -> bool:
        """Whether the datetime is ambiguous, i.e. ``fold`` has effect.

        Example
        -------

        .. code-block:: python

           assert not ZonedDateTime(
               2020, 8, 15, 23, zone="Europe/London"
           ).is_ambiguous()
           assert ZonedDateTime(
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
           assert d.to_utc() == UTCDateTime(2020, 8, 15, 22)
        """
        new = _object_new(UTCDateTime)
        new._py_dt = self._py_dt.astimezone(_UTC)
        return new

    def to_zoned(self, zone: str) -> ZonedDateTime:
        """Convert to a :class:`ZonedDateTime` in the given timezone

        raises :class:`zoneinfo.ZoneInfoNotFoundError` if the timezone
        name is not found in the IANA database.

        Example
        -------

        .. code-block:: python

           d = ZonedDateTime(2020, 8, 15, 23, zone="Europe/London", fold=0)
           assert d.to_zoned("Europe/Paris") == ZonedDateTime(
                2020, 8, 16, zone="Europe/Paris", fold=0
           )
        """
        new = _object_new(ZonedDateTime)
        new._py_dt = self._py_dt.astimezone(ZoneInfo(zone))
        return new

    def __repr__(self) -> str:
        return f"whenever.ZonedDateTime({self})"

    # a custom pickle implementation with a smaller payload
    def __reduce__(self) -> tuple[object, ...]:
        return (
            _zoned_unpickle,
            self._py_dt.timetuple()[:6]
            + (
                self.microsecond,
                # We know that tzinfo is always a ZoneInfo, but mypy doesn't
                self.tzinfo.key,  # type: ignore[attr-defined]
                self.fold,
            ),
        )

    # We don't need to copy, because ZonedDateTime is immutable
    def __copy__(self) -> ZonedDateTime:
        return self

    def __deepcopy__(self, _: object) -> ZonedDateTime:
        return self


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
    self = _object_new(ZonedDateTime)
    self._py_dt = _datetime(
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
    return self


class DateTimeIsAmbiguous(Exception):
    """Indicates that a datetime is ambiguous"""


class DateTimeDoesntExistInZone(Exception):
    """Indicates a datetime is nonexistent, e.g. because of DST transitions"""


def _exists_in_tz(d: _datetime) -> bool:
    # non-existent datetimes don't survive a round-trip to UTC
    return d.astimezone(_UTC).astimezone(d.tzinfo) == d


# Helpers that pre-compute/lookup as much as possible
_no_tzinfo_or_fold = {"tzinfo", "fold"}.isdisjoint
_datetime_now = _datetime.now
_object_new = object.__new__
# YYYY-MM-DD HH:MM:SS[.fff[fff]]
_DATETIME_RE = r"\d{4}-\d{2}-\d{2}[T ]\d{2}:\d{2}:\d{2}(?:\.(?:\d{3}|\d{6}))?"
# YYYY-MM-DD HH:MM:SS[.fff[fff]]±HH:MM[:SS[.ffffff]]
_OFFSET_RE = rf"{_DATETIME_RE}[+-]\d{{2}}:\d{{2}}(?::\d{{2}}(?:\.\d{{6}})?)?"
_match_utc_str = re.compile(rf"{_DATETIME_RE}Z").fullmatch
_match_plain_str = re.compile(_DATETIME_RE).fullmatch
_match_offset_str = re.compile(_OFFSET_RE).fullmatch
_match_zoned_str = re.compile(rf"({_OFFSET_RE})\[([^\]]+)\]").fullmatch
_fromisoformat = _datetime.fromisoformat
_fromtimestamp = _datetime.fromtimestamp


# Before Python 3.11, fromisoformat doesn't support the Z suffix meaning UTC.
if sys.version_info < (3, 11):  # pragma: no cover

    def _fromisoformat_utc(s: str) -> _datetime:
        return _fromisoformat(s[:-1]).replace(tzinfo=_UTC)

else:
    _fromisoformat_utc = _fromisoformat


UTCDateTime.min = UTCDateTime.from_py(_datetime.min.replace(tzinfo=_UTC))
UTCDateTime.max = UTCDateTime.from_py(_datetime.max.replace(tzinfo=_UTC))
PlainDateTime.min = PlainDateTime.from_py(_datetime.min)
PlainDateTime.max = PlainDateTime.from_py(_datetime.max)
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


def hours(i: int, /) -> timedelta:
    """Create a :class:`~datetime.timedelta` with the given number of hours

    Example
    -------

    .. code-block:: python

       from whenever import hours
       assert hours(1) == timedelta(hours=1)
    """
    return timedelta(hours=i)


def minutes(i: int, /) -> timedelta:
    """Create a :class:`~datetime.timedelta` with the given number of minutes

    Example
    -------

    .. code-block:: python

       from whenever import minutes
       assert minutes(1) == timedelta(minutes=1)
    """
    return timedelta(minutes=i)
