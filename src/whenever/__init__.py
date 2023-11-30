from __future__ import annotations

import re
import sys
from datetime import date as _date
from datetime import datetime as _datetime
from datetime import time as _time
from datetime import timedelta, timezone, tzinfo
from operator import attrgetter
from typing import TYPE_CHECKING, ClassVar, overload

try:
    from typing import SPHINX_BUILD  # type: ignore[attr-defined]
except ImportError:
    SPHINX_BUILD = False


_UTC = timezone.utc

__all__ = ["UTCDateTime", "NaiveDateTime"]


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
        """Create a UTCDateTime from ``YYYY-MM-DDTHH:MM:SS[.ffffff]Z``,
        raising :class:`ValueError` if the string does not match this
        exact format. The inverse of :meth:`__str__`.

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
        self._py_datetime = _utc_fromisoformat(s)
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
        """Create an instance from ``YYYY-MM-DDTHH:MM:SS[.ffffff]``,
        raising :class:`ValueError` if the string does not match this
        exact format. The inverse of :meth:`__str__`.

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
        self._py_datetime = _naive_fromisoformat(s)
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


# Helpers that pre-compute/lookup as much as possible
_no_tzinfo_or_fold = {"tzinfo", "fold"}.isdisjoint
_datetime_now = _datetime.now
_object_new = object.__new__
_match_utc_str = re.compile(
    r"(\d{4})-(\d{2})-(\d{2})T(\d{2}):(\d{2}):(\d{2})(?:\.(\d{1,6}))?Z"
).fullmatch
_match_naive_str = re.compile(
    r"(\d{4})-(\d{2})-(\d{2})T(\d{2}):(\d{2}):(\d{2})(?:\.(\d{1,6}))?"
).fullmatch


# Before Python 3.11, fromisoformat() is very particular
if sys.version_info > (3, 11):  # pragma: no cover
    _utc_fromisoformat = _naive_fromisoformat = _datetime.fromisoformat
else:  # pragma: no cover

    def _utc_fromisoformat(s: str, /) -> _datetime:
        return (
            _datetime.fromisoformat(
                # Remove trailing Z, and ensure exactly 0 ot 6 ms digits
                s[:19]
                if len(s) == 20
                else s[:-1].ljust(26, "0")
            )
        ).replace(tzinfo=_UTC)

    def _naive_fromisoformat(s: str, /) -> _datetime:
        return _datetime.fromisoformat(s if len(s) == 19 else s.ljust(26, "0"))


UTCDateTime.min = UTCDateTime.from_py(_datetime.min.replace(tzinfo=_UTC))
UTCDateTime.max = UTCDateTime.from_py(_datetime.max.replace(tzinfo=_UTC))
NaiveDateTime.min = NaiveDateTime.from_py(_datetime.min)
NaiveDateTime.max = NaiveDateTime.from_py(_datetime.max)
