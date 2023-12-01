from __future__ import annotations

import re
import sys
from datetime import date as _date
from datetime import datetime as _datetime
from datetime import time as _time
from datetime import timedelta
from datetime import timezone as _timezone
from datetime import tzinfo
from operator import attrgetter
from typing import TYPE_CHECKING, Any, ClassVar, overload

try:
    from typing import SPHINX_BUILD  # type: ignore[attr-defined]
except ImportError:
    SPHINX_BUILD = False


_UTC = _timezone.utc

__all__ = [
    "UTCDateTime",
    "OffsetDateTime",
    "NaiveDateTime",
    "hours",
    "minutes",
]


class __NOTSET__:
    """Sentinel value for when no value is given"""


class UTCDateTime:
    """A UTC-only datetime. Useful for representing location-indepentent
    times en an unambiguous way.

    Example
    -------

    .. code-block:: python

       from whenever import UTCDateTime
       py311_release_livestream = UTCDateTime(2022, 10, 24, hour=17)
    """

    __slots__ = ("_py_datetime", "__weakref__")
    _py_datetime: _datetime

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
        self._py_datetime = _datetime(
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
        self._py_datetime = _datetime_now(_UTC)
        return self

    def __str__(self) -> str:
        """Format a UTCDateTime as ``YYYY-MM-DDTHH:MM:SS[.ffffff]Z``.
        This format is both RFC 3339 and ISO 8601 compliant.

        Example
        -------
        .. code-block:: python

           d = UTCDateTime(2020, 8, 15, hour=23, minute=12)
           assert str(d) == "2020-08-15T23:12:00Z"

        """
        return f"{self._py_datetime.isoformat()[:-6]}Z"

    @staticmethod
    def fromstr(s: str, /) -> UTCDateTime:
        """Create a UTCDateTime from ``YYYY-MM-DDTHH:MM:SS[.fff[fff]]Z``,
        raising :class:`ValueError` if the string does not match this
        exact format. The inverse of :meth:`__str__`.

        Note
        ----
        ``T`` may be replaced with a single space

        Example
        -------

        .. code-block:: python

           d = UTCDateTime.fromstr("2020-08-15T23:12:00Z")
           assert d == UTCDateTime(2020, 8, 15, hour=23, minute=12)

           assert UTCDateTime.fromstr(str(d)) == d

           UTCDateTime.fromstr("2020-08-15T23:12")  # raises ValueError

        """
        if not _match_utc_str(s):
            raise ValueError("Invalid string")
        self = _object_new(UTCDateTime)
        self._py_datetime = _fromisoformat(s)
        return self

    if TYPE_CHECKING or SPHINX_BUILD:

        def timestamp(self) -> float:
            """The UNIX timestamp. Inverse of :meth:`fromtimestamp`.

            Example
            -------

            .. code-block:: python

               assert UTCDateTime(1970, 1, 1).timestamp() == 0

               ts = 1_123_000_000
               assert UTCDateTime.fromtimestamp(ts).timestamp() == ts
            """
            ...

    else:
        timestamp = property(attrgetter("_py_datetime.timestamp"))

    @staticmethod
    def fromtimestamp(i: float, /) -> UTCDateTime:
        """Create a UTCDateTime from a UNIX timestamp.
        The inverse of :meth:`timestamp`.

        Example
        -------

        .. code-block:: python

           assert UTCDateTime.fromtimestamp(0) == UTCDateTime(1970, 1, 1)
           d = UTCDateTime.fromtimestamp(1_123_000_000.45)
           assert d == UTCDateTime(2004, 8, 2, 16, 26, 40, 450_000)

           assert UTCDateTime.fromtimestamp(d.timestamp()) == d
        """
        self = _object_new(UTCDateTime)
        self._py_datetime = _datetime.fromtimestamp(i, _UTC)
        return self

    def to_py(self) -> _datetime:
        """Get the underlying :class:`~datetime.datetime` object"""
        return self._py_datetime

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
        self._py_datetime = d
        return self

    def tz(self) -> tzinfo:
        """The timezone, always :attr:`~datetime.UTC`"""
        return _UTC

    if TYPE_CHECKING:
        # We could have used typing.Unpack, but that's only available
        # in Python 3.11+ or with typing_extensions.
        def replace(
            self,
            *,
            year: int | None = None,
            month: int | None = None,
            day: int | None = None,
            hour: int | None = None,
            minute: int | None = None,
            second: int | None = None,
            microsecond: int | None = None,
        ) -> UTCDateTime:
            ...

    else:

        def replace(self, /, **kwargs) -> UTCDateTime:
            """Create a new UTCDateTime with the given fields replaced

            Example
            -------

            .. code-block:: python

               d = UTCDateTime(2020, 8, 15, 23, 12)
               assert d.replace(year=2021) == UTCDateTime(2021, 8, 15, 23, 12)
            """
            if not _no_tzinfo_or_fold(kwargs):
                raise TypeError("tzinfo and fold are not allowed arguments")
            new = _object_new(UTCDateTime)
            new._py_datetime = self._py_datetime.replace(**kwargs)
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
        year = property(attrgetter("_py_datetime.year"))
        month = property(attrgetter("_py_datetime.month"))
        day = property(attrgetter("_py_datetime.day"))
        hour = property(attrgetter("_py_datetime.hour"))
        minute = property(attrgetter("_py_datetime.minute"))
        second = property(attrgetter("_py_datetime.second"))
        microsecond = property(attrgetter("_py_datetime.microsecond"))
        weekday = property(attrgetter("_py_datetime.weekday"))
        date = property(attrgetter("_py_datetime.date"))
        time = property(attrgetter("_py_datetime.time"))
        __hash__ = property(attrgetter("_py_datetime.__hash__"))

    resolution: ClassVar[timedelta] = _datetime.resolution
    """Alias for :attr:`datetime.datetime.resolution`"""
    min: ClassVar[UTCDateTime]
    """Small possible value"""
    max: ClassVar[UTCDateTime]
    """Biggest possible value"""

    # This ensures mypy's --strict-equalty works
    if not TYPE_CHECKING:  # pragma: no branch

        def __eq__(self, other: UTCDateTime) -> bool:
            """Compare two objects

            Example
            -------
            .. code-block:: python

               assert UTCDateTime(2020, 8, 15, 23) == UTCDateTime(2020, 8, 15, 23)

            """  # noqa: E501
            if not isinstance(other, UTCDateTime):
                return NotImplemented
            return self._py_datetime == other._py_datetime

    def __lt__(self, other: UTCDateTime) -> bool:
        """Compare two objects

        Example
        -------
        .. code-block:: python

           assert UTCDateTime(2020, 8, 15, hour=23) < UTCDateTime(2020, 8, 16)

        """
        if not isinstance(other, UTCDateTime):
            return NotImplemented
        return self._py_datetime < other._py_datetime

    def __le__(self, other: UTCDateTime) -> bool:
        if not isinstance(other, UTCDateTime):
            return NotImplemented
        return self._py_datetime <= other._py_datetime

    def __gt__(self, other: UTCDateTime) -> bool:
        if not isinstance(other, UTCDateTime):
            return NotImplemented
        return self._py_datetime > other._py_datetime

    def __ge__(self, other: UTCDateTime) -> bool:
        if not isinstance(other, UTCDateTime):
            return NotImplemented
        return self._py_datetime >= other._py_datetime

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
        new._py_datetime = self._py_datetime + other
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
                return self._py_datetime - other._py_datetime
            elif isinstance(other, timedelta):
                new = _object_new(UTCDateTime)
                new._py_datetime = self._py_datetime - other
                return new
            return NotImplemented

    def __repr__(self) -> str:
        return f"whenever.UTCDateTime({self})"

    # a custom pickle implementation with a smaller payload
    def __reduce__(self) -> tuple[object, ...]:
        return (
            UTCDateTime,
            self._py_datetime.timetuple()[:6] + (self.microsecond,),
        )


class NaiveDateTime:
    """A naive datetime. Useful when you need date and time, but without
    any of the real-world complexities of timeszones."""

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
        self._py_datetime = _datetime(
            year, month, day, hour, minute, second, microsecond
        )

    if TYPE_CHECKING or SPHINX_BUILD:

        def __str__(self) -> str:
            """Format a NaiveDateTime as ``YYYY-MM-DDTHH:MM:SS[.ffffff]``.
            Inverse of :meth:`fromstr`.

            This format is ISO 8601 compliant, but not RFC 3339 compliant,
            as this requires a UTC offset

            Example
            -------

            .. code-block:: python

               d = NaiveDateTime(2020, 8, 15, hour=23, minute=12)
               assert str(d) == "2020-08-15T23:12:00"

               assert NaiveDateTime.fromstr(str(d)) == d

            """
            ...

    else:
        __str__ = property(attrgetter("_py_datetime.isoformat"))

    @staticmethod
    def fromstr(s: str, /) -> NaiveDateTime:
        """Create an instance from ``YYYY-MM-DDTHH:MM:SS[.fff[fff]]``,
        raising :class:`ValueError` if the string does not match this
        exact format. The inverse of :meth:`__str__`.

        Note
        ----
        ``T`` may be replaced with a single space

        Example
        -------

        .. code-block:: python

           d = NaiveDateTime.fromstr("2020-08-15T23:12:00")
           assert d == NaiveDateTime(2020, 8, 15, hour=23, minute=12)

           assert NaiveDateTime.fromstr(str(d)) == d
           NaiveDateTime.fromstr("2020-08-15T23:12")  # raises ValueError

        """
        if not _match_naive_str(s):
            raise ValueError("Invalid string")
        self = _object_new(NaiveDateTime)
        self._py_datetime = _fromisoformat(s)
        return self

    def to_py(self) -> _datetime:
        """Get the underlying :class:`~datetime.datetime` object.
        Inverse of :meth:`from_py`.

        Example
        -------
        .. code-block:: python

           d = NaiveDateTime(2020, 8, 15, hour=23, minute=12)
           assert d.to_py() == datetime(2020, 8, 15, hour=23, minute=12)

           assert NaiveDateTime.from_py(d.to_py()) == d
        """
        return self._py_datetime

    @classmethod
    def from_py(cls, d: _datetime, /) -> NaiveDateTime:
        """Create an instance from a :class:`~datetime.datetime` object.
        It must be timezone-naive. Inverse of :meth:`to_py`.

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
        self._py_datetime = d
        return self

    def tz(self) -> tzinfo | None:
        """The timezone, always :obj:`None`"""
        return None

    if TYPE_CHECKING:
        # We could have used typing.Unpack, but that's only available
        # in Python 3.11+ or with typing_extensions.
        def replace(
            self,
            *,
            year: int | None = None,
            month: int | None = None,
            day: int | None = None,
            hour: int | None = None,
            minute: int | None = None,
            second: int | None = None,
            microsecond: int | None = None,
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
            new._py_datetime = self._py_datetime.replace(**kwargs)
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
        year = property(attrgetter("_py_datetime.year"))
        month = property(attrgetter("_py_datetime.month"))
        day = property(attrgetter("_py_datetime.day"))
        hour = property(attrgetter("_py_datetime.hour"))
        minute = property(attrgetter("_py_datetime.minute"))
        second = property(attrgetter("_py_datetime.second"))
        microsecond = property(attrgetter("_py_datetime.microsecond"))
        weekday = property(attrgetter("_py_datetime.weekday"))
        date = property(attrgetter("_py_datetime.date"))
        time = property(attrgetter("_py_datetime.time"))
        __hash__ = property(attrgetter("_py_datetime.__hash__"))

    resolution: ClassVar[timedelta] = _datetime.resolution
    """Alias for :attr:`datetime.datetime.resolution`"""
    min: ClassVar[NaiveDateTime]
    """Small possible value"""
    max: ClassVar[NaiveDateTime]
    """Biggest possible value"""

    # This ensures mypy's --strict-equalty works
    if not TYPE_CHECKING:  # pragma: no branch

        def __eq__(self, other: NaiveDateTime) -> bool:
            """Compare two objects

            Example
            -------
            .. code-block:: python

               assert NaiveDateTime(2020, 8, 15, 23) == NaiveDateTime(2020, 8, 15, 23)

            """  # noqa: E501
            if not isinstance(other, NaiveDateTime):
                return NotImplemented
            return self._py_datetime == other._py_datetime

    def __lt__(self, other: NaiveDateTime) -> bool:
        """Compare two objects

        Example
        -------
        .. code-block:: python

           assert NaiveDateTime(2020, 8, 15, hour=23) < NaiveDateTime(2020, 8, 16)

        """  # noqa: E501
        if not isinstance(other, NaiveDateTime):
            return NotImplemented
        return self._py_datetime < other._py_datetime

    def __le__(self, other: NaiveDateTime) -> bool:
        if not isinstance(other, NaiveDateTime):
            return NotImplemented
        return self._py_datetime <= other._py_datetime

    def __gt__(self, other: NaiveDateTime) -> bool:
        if not isinstance(other, NaiveDateTime):
            return NotImplemented
        return self._py_datetime > other._py_datetime

    def __ge__(self, other: NaiveDateTime) -> bool:
        if not isinstance(other, NaiveDateTime):
            return NotImplemented
        return self._py_datetime >= other._py_datetime

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
        new._py_datetime = self._py_datetime + other
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
                return self._py_datetime - other._py_datetime
            elif isinstance(other, timedelta):
                new = _object_new(NaiveDateTime)
                new._py_datetime = self._py_datetime - other
                return new
            return NotImplemented

    def __repr__(self) -> str:
        return f"whenever.NaiveDateTime({self})"

    # a custom pickle implementation with a smaller payload
    def __reduce__(self) -> tuple[object, ...]:
        return (
            NaiveDateTime,
            self._py_datetime.timetuple()[:6] + (self.microsecond,),
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

    __slots__ = ("_py_datetime", "__weakref__")
    _py_datetime: _datetime

    # These overloads allow 'offset' to be both keyword and positional,
    # even at the end of the argument list.
    @overload
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
        ...

    @overload
    def __init__(
        self,
        year: int,
        month: int,
        day: int,
        hour: int,
        minute: int,
        second: int,
        microsecond: int,
        offset: timedelta,
    ) -> None:
        ...

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        if len(args) == 8:
            self._py_datetime = _datetime(*args[:7], _timezone(args[7]))
        else:
            try:
                kwargs["tzinfo"] = _timezone(kwargs.pop("offset"))
            except KeyError:
                raise TypeError(
                    "OffsetDateTime() missing 1 required argument: 'offset'"
                ) from None
            self._py_datetime = _datetime(*args, **kwargs)

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
        self._py_datetime = _datetime_now(_timezone(offset))
        return self

    def __str__(self) -> str:
        """Format a OffsetDateTime as ``YYYY-MM-DDTHH:MM:SS[.ffffff]±HH:MM``.

        This format is both RFC 3339 and ISO 8601 compliant.

        The inverse of :meth:`fromstr`.

        Example
        -------

        .. code-block:: python

           d = OffsetDateTime(2020, 8, 15, hour=23, minute=12, offset=hours(1))
           assert str(d) == "2020-08-15T23:12:00+01:00"

        """
        return self._py_datetime.isoformat()

    @staticmethod
    def fromstr(s: str, /) -> OffsetDateTime:
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

           d = OffsetDateTime.fromstr("2020-08-15T23:12:00Z")
           assert d == OffsetDateTime(2020, 8, 15, hour=23, minute=12)

           assert OffsetDateTime.fromstr(str(d)) == d

           OffsetDateTime.fromstr("2020-08-15T23:12")  # raises ValueError

        """
        if not _match_offset_str(s):
            raise ValueError("Invalid string")
        self = _object_new(OffsetDateTime)
        self._py_datetime = _fromisoformat(s)
        return self

    if TYPE_CHECKING or SPHINX_BUILD:

        def timestamp(self) -> float:
            """The UNIX timestamp. Inverse of :meth:`fromtimestamp`.

            Example
            -------

            .. code-block:: python

               assert OffsetDateTime(1970, 1, 1, 3, offset=hours(3)).timestamp() == 0

               ts = 1_123_000_000
               assert OffsetDateTime.fromtimestamp(ts, offset=hours(-2)).timestamp() == ts
            """  # noqa: E501
            ...

    else:
        timestamp = property(attrgetter("_py_datetime.timestamp"))

    @staticmethod
    def fromtimestamp(i: float, /, offset: timedelta) -> OffsetDateTime:
        """Create a OffsetDateTime from a UNIX timestamp.
        The inverse of :meth:`timestamp`.

        Example
        -------

        .. code-block:: python

           assert OffsetDateTime.fromtimestamp(0, offset=hours(3)) == (
               OffsetDateTime(1970, 1, 1, 3, offset=hours(3))
           )
           d = OffsetDateTime.fromtimestamp(1_123_000_000.45, offset=hours(-2))
           assert d == OffsetDateTime(2004, 8, 2, 14, 26, 40, 450_000, offset=hours(-2))

           assert OffsetDateTime.fromtimestamp(d.timestamp(), d.offset) == d
        """  # noqa: E501
        self = _object_new(OffsetDateTime)
        self._py_datetime = _datetime.fromtimestamp(i, _timezone(offset))
        return self

    def to_py(self) -> _datetime:
        """Get the underlying :class:`~datetime.datetime` object"""
        return self._py_datetime

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
        self._py_datetime = d
        return self

    def tz(self) -> tzinfo:
        """The timezone, always a :class:`datetime.timezone` (fixed offset)"""
        # We know that we set a fixed offset, but mypy doesn't
        return self._py_datetime.tzinfo  # type: ignore[return-value]

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
            new._py_datetime = self._py_datetime.replace(**kwargs)
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
        year = property(attrgetter("_py_datetime.year"))
        month = property(attrgetter("_py_datetime.month"))
        day = property(attrgetter("_py_datetime.day"))
        hour = property(attrgetter("_py_datetime.hour"))
        minute = property(attrgetter("_py_datetime.minute"))
        second = property(attrgetter("_py_datetime.second"))
        microsecond = property(attrgetter("_py_datetime.microsecond"))
        weekday = property(attrgetter("_py_datetime.weekday"))
        date = property(attrgetter("_py_datetime.date"))
        time = property(attrgetter("_py_datetime.time"))
        __hash__ = property(attrgetter("_py_datetime.__hash__"))

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
        return self._py_datetime.utcoffset()  # type: ignore[return-value]

    # This ensures mypy's --strict-equalty works
    if not TYPE_CHECKING:  # pragma: no branch
        # TODO: structural or value equality?
        def __eq__(self, other: OffsetDateTime) -> bool:
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
            return self._py_datetime == other._py_datetime

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
        return self._py_datetime < other._py_datetime

    def __le__(self, other: OffsetDateTime) -> bool:
        if not isinstance(other, OffsetDateTime):
            return NotImplemented
        return self._py_datetime <= other._py_datetime

    def __gt__(self, other: OffsetDateTime) -> bool:
        if not isinstance(other, OffsetDateTime):
            return NotImplemented
        return self._py_datetime > other._py_datetime

    def __ge__(self, other: OffsetDateTime) -> bool:
        if not isinstance(other, OffsetDateTime):
            return NotImplemented
        return self._py_datetime >= other._py_datetime

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
        return self._py_datetime - other._py_datetime

    def __repr__(self) -> str:
        return f"whenever.OffsetDateTime({self})"

    # a custom pickle implementation with a smaller payload
    def __reduce__(self) -> tuple[object, ...]:
        return (
            OffsetDateTime,
            self._py_datetime.timetuple()[:6]
            + (self.microsecond, self.offset),
        )


# Helpers that pre-compute/lookup as much as possible
_no_tzinfo_or_fold = {"tzinfo", "fold"}.isdisjoint
_datetime_now = _datetime.now
_object_new = object.__new__
_DATETIME_RE = r"\d{4}-\d{2}-\d{2}[T ]\d{2}:\d{2}:\d{2}(\.(\d{3}|\d{6}))?"
_match_utc_str = re.compile(rf"{_DATETIME_RE}Z").fullmatch
_match_naive_str = re.compile(_DATETIME_RE).fullmatch
_match_offset_str = re.compile(
    rf"{_DATETIME_RE}[+-]\d{{2}}:\d{{2}}(?::\d{{2}}(?:\.\d{{6}})?)?"
).fullmatch
_fromisoformat = _datetime.fromisoformat


UTCDateTime.min = UTCDateTime.from_py(_datetime.min.replace(tzinfo=_UTC))
UTCDateTime.max = UTCDateTime.from_py(_datetime.max.replace(tzinfo=_UTC))
NaiveDateTime.min = NaiveDateTime.from_py(_datetime.min)
NaiveDateTime.max = NaiveDateTime.from_py(_datetime.max)
OffsetDateTime.min = OffsetDateTime.from_py(
    _datetime.min.replace(
        tzinfo=_timezone(timedelta(hours=24) - timedelta.resolution)
    )
)
OffsetDateTime.max = OffsetDateTime.from_py(
    _datetime.max.replace(
        tzinfo=_timezone(timedelta(hours=-24) + timedelta.resolution)
    )
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
