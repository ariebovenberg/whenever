# Maintainer's notes:
#
# There is some code duplication in this file. This is intentional:
# - It makes it easier to understand the code
# - It's sometimes necessary for the type checker
# - It saves some overhead
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
from email.utils import format_datetime, parsedate_to_datetime
from operator import attrgetter
from typing import (
    TYPE_CHECKING,
    Callable,
    ClassVar,
    Literal,
    TypeVar,
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
    "DateTime",
    "AwareDateTime",
    "UTCDateTime",
    "OffsetDateTime",
    "ZonedDateTime",
    "LocalDateTime",
    "NaiveDateTime",
    "days",
    "hours",
    "minutes",
    "DoesntExistInZone",
    "Ambiguous",
    "InvalidOffsetForZone",
    "InvalidFormat",
]


class NOT_SET:
    pass  # sentinel for when no value is passed


_T = TypeVar("_T", bound="DateTime")


class DateTime(ABC):
    """Abstract base class for all datetime types"""

    __slots__ = ("_py_dt", "__weakref__")
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

    @abstractmethod
    def canonical_str(self) -> str:
        """Format as the canonical string representation. Each
        subclass has a different format. See the documentation for
        the subclass for more information.
        Inverse of :meth:`from_canonical_str`.
        """

    @abstractmethod
    def __str__(self) -> str:
        """Same as :meth:`canonical_str`"""

    @classmethod
    @abstractmethod
    def from_canonical_str(cls: type[_T], s: str, /) -> _T:
        """Create an instance from the canonical string representation,
        which is different for each subclass.

        Inverse of :meth:`__str__` and :meth:`canonical_str`.

        Note
        ----
        ``T`` may be replaced with a single space

        Raises
        ------
        InvalidFormat
            If the string does not match this exact format.
        """

    resolution: ClassVar[timedelta] = _datetime.resolution
    """Alias for :attr:`datetime.datetime.resolution`"""

    @classmethod
    @abstractmethod
    def from_py(cls: type[_T], d: _datetime, /) -> _T:
        """Create an instance from a :class:`~datetime.datetime` object.
        Inverse of :attr:`py`.

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
        Its ``fold`` attribute is consulted to determine which
        the behavior on ambiguity.
        """

    @property
    def py(self) -> _datetime:
        """Get the underlying :class:`~datetime.datetime` object"""
        return self._py_dt

    if not TYPE_CHECKING and SPHINX_BUILD:  # pragma: no cover

        @abstractmethod
        def replace(self: _T, /, **kwargs) -> _T:
            """Construct a new instance with the given fields replaced.

            Arguments are the same as the constructor,
            but only keyword arguments are allowed.

            Warning
            -------
            Note that the same exceptions as the constructor may be raised
            You will need to pass ``disambiguate=`` to resolve ambiguities
            of :class:`ZonedDateTime` and :class:`LocalDateTime`.

            Example
            -------

            .. code-block:: python

                d = UTCDateTime(2020, 8, 15, 23, 12)
                d.replace(year=2021) == UTCDateTime(2021, 8, 15, 23, 12)

                z = ZonedDateTime(2020, 8, 15, 23, 12, tz="Europe/London")
                z.replace(year=2021, disambiguate="later")
            """

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
    """Abstract base class for all aware datetime types (:class:`UTCDateTime`,
    :class:`OffsetDateTime`, :class:`ZonedDateTime` and :class:`LocalDateTime`).
    """

    __slots__ = ()

    if TYPE_CHECKING or SPHINX_BUILD:

        @property
        def tzinfo(self) -> _tzinfo | None:
            """The tzinfo of the underlying :class:`~datetime.datetime`"""
            ...

        def timestamp(self) -> float:
            """The UNIX timestamp for this datetime.

            Each subclass also defines an inverse ``from_timestamp`` method,
            which may require additional arguments.

            Example
            -------

            .. code-block:: python

               UTCDateTime(1970, 1, 1).timestamp() == 0

               ts = 1_123_000_000
               UTCDateTime.from_timestamp(ts).timestamp() == ts
            """
            return self._py_dt.timestamp()

    else:
        tzinfo = property(attrgetter("_py_dt.tzinfo"))
        timestamp = property(attrgetter("_py_dt.timestamp"))

    @property
    @abstractmethod
    def offset(self) -> timedelta:
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
    def as_offset(self, offset: timedelta, /) -> OffsetDateTime: ...

    @abstractmethod
    def as_offset(self, offset: timedelta | None = None, /) -> OffsetDateTime:
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
            If the timezone name is not found in the IANA database.
        """
        return ZonedDateTime._from_py_unchecked(
            self._py_dt.astimezone(ZoneInfo(tz))
        )

    def as_local(self) -> LocalDateTime:
        """Convert into a an equivalent LocalDateTime.
        The result will always represent the same moment in time.
        """
        return LocalDateTime._from_py_unchecked(_to_local(self._py_dt))

    def naive(self) -> NaiveDateTime:
        """Convert into a naive datetime, dropping all timezone information

        Each subclass also defines an inverse ``from_naive()`` method,
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

            .. code-block:: python

               UTCDateTime(2020, 8, 15, hour=23) == UTCDateTime(2020, 8, 15, hour=23)
               OffsetDateTime(2020, 8, 15, hour=23, offset=hours(1)) == (
                   ZonedDateTime(2020, 8, 15, hour=18, tz="America/New_York")
               )
            """

    @abstractmethod
    def __lt__(self, other: AwareDateTime) -> bool:
        """Compare two datetimes by when they occur in time

        ``a < b`` is equivalent to ``a.as_utc() < b.as_utc()``

        Example
        -------
        .. code-block:: python

           OffsetDateTime(2020, 8, 15, hour=23, offset=hours(8)) < (
               ZoneDateTime(2020, 8, 15, hour=20, tz="Europe/Amsterdam")
           )
        """

    @abstractmethod
    def __le__(self, other: AwareDateTime) -> bool:
        """Compare two datetimes by when they occur in time

        ``a <= b`` is equivalent to ``a.as_utc() <= b.as_utc()``

        Example
        -------
        .. code-block:: python

           OffsetDateTime(2020, 8, 15, hour=23, offset=hours(8)) <= (
               ZoneDateTime(2020, 8, 15, hour=20, tz="Europe/Amsterdam")
           )
        """

    @abstractmethod
    def __gt__(self, other: AwareDateTime) -> bool:
        """Compare two datetimes by when they occur in time

        ``a > b`` is equivalent to ``a.as_utc() > b.as_utc()``

        Example
        -------
        .. code-block:: python

           OffsetDateTime(2020, 8, 15, hour=19, offset=hours(-8)) > (
               ZoneDateTime(2020, 8, 15, hour=20, tz="Europe/Amsterdam")
           )
        """

    @abstractmethod
    def __ge__(self, other: AwareDateTime) -> bool:
        """Compare two datetimes by when they occur in time

        ``a >= b`` is equivalent to ``a.as_utc() >= b.as_utc()``

        Example
        -------
        .. code-block:: python

           OffsetDateTime(2020, 8, 15, hour=19, offset=hours(-8)) >= (
               ZoneDateTime(2020, 8, 15, hour=20, tz="Europe/Amsterdam")
           )
        """

    # Mypy doesn't like overloaded overrides, but we'd like to document
    # this 'abstract' behaviour anyway
    if not TYPE_CHECKING:  # pragma: no branch

        @abstractmethod
        def __sub__(self, other: AwareDateTime) -> timedelta:
            """Calculate the duration between two datetimes

            ``a - b`` is equivalent to ``a.as_utc() - b.as_utc()``

            Example
            -------

            .. code-block:: python

               d = UTCDateTime(2020, 8, 15, hour=23)
               d - ZoneDateTime(2020, 8, 15, hour=20, tz="Europe/Amsterdam")  # 5 hours
            """

    @abstractmethod
    def exact_eq(self: _T, other: _T, /) -> bool:
        """Compare objects by their values (instead of their UTC equivalence).
        Different types are never equal.

        Note
        ----
        If ``a.exact_eq(b)`` is true, then
        ``a == b`` is also true, but the converse is not necessarily true.

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

    Note
    ----

    The canonical string representation is:

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

    def canonical_str(self) -> str:
        return f"{self._py_dt.isoformat()[:-6]}Z"

    __str__ = canonical_str

    @classmethod
    def from_canonical_str(cls, s: str, /) -> UTCDateTime:
        if not _match_utc_str(s):
            raise InvalidFormat()
        return cls._from_py_unchecked(_fromisoformat_utc(s))

    @classmethod
    def from_timestamp(cls, i: float, /) -> UTCDateTime:
        """Create an instance from a UNIX timestamp.
        The inverse of :meth:`~AwareDateTime.timestamp`.

        Example
        -------

        .. code-block:: python

           UTCDateTime.from_timestamp(0) == UTCDateTime(1970, 1, 1)
           d = UTCDateTime.from_timestamp(1_123_000_000.45)
           d == UTCDateTime(2004, 8, 2, 16, 26, 40, 450_000)

           UTCDateTime.from_timestamp(d.timestamp()) == d
        """
        return cls._from_py_unchecked(_fromtimestamp(i, _UTC))

    @classmethod
    def from_py(cls, d: _datetime, /) -> UTCDateTime:
        if d.tzinfo is not _UTC:
            raise ValueError(
                "Can only create UTCDateTime from UTC datetime, "
                f"got datetime with tzinfo={d.tzinfo!r}"
            )
        return cls._from_py_unchecked(d)

    tzinfo: ClassVar[_tzinfo] = _timezone.utc
    offset = timedelta()

    if TYPE_CHECKING:  # pragma: no branch
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
            if not isinstance(other, (UTCDateTime, OffsetDateTime)):
                return NotImplemented
            return self._py_dt == other._py_dt

    min: ClassVar[UTCDateTime]
    max: ClassVar[UTCDateTime]

    def exact_eq(self, other: UTCDateTime, /) -> bool:
        return self._py_dt == other._py_dt

    def __lt__(self, other: AwareDateTime) -> bool:
        if not isinstance(other, (UTCDateTime, OffsetDateTime)):
            return NotImplemented
        return self._py_dt < other._py_dt

    def __le__(self, other: AwareDateTime) -> bool:
        if not isinstance(other, (UTCDateTime, OffsetDateTime)):
            return NotImplemented
        return self._py_dt <= other._py_dt

    def __gt__(self, other: AwareDateTime) -> bool:
        if not isinstance(other, (UTCDateTime, OffsetDateTime)):
            return NotImplemented
        return self._py_dt > other._py_dt

    def __ge__(self, other: AwareDateTime) -> bool:
        if not isinstance(other, (UTCDateTime, OffsetDateTime)):
            return NotImplemented
        return self._py_dt >= other._py_dt

    def __add__(self, other: timedelta) -> UTCDateTime:
        """Add a timedelta to this datetime

        Example
        -------
        .. code-block:: python

           d = UTCDateTime(2020, 8, 15, hour=23, minute=12)
           d + timedelta(days=1, seconds=5) == UTCDateTime(
               2020, 8, 16, hour=23, minute=12, second=5
           )
        """
        if not isinstance(other, timedelta):
            return NotImplemented
        return self._from_py_unchecked(self._py_dt + other)

    if TYPE_CHECKING:

        @overload
        def __sub__(self, other: AwareDateTime) -> timedelta: ...

        @overload
        def __sub__(self, other: timedelta) -> UTCDateTime: ...

        def __sub__(
            self, other: AwareDateTime | timedelta
        ) -> AwareDateTime | timedelta: ...

    else:

        def __sub__(
            self, other: timedelta | AwareDateTime
        ) -> AwareDateTime | timedelta:
            """Subtract another datetime or timedelta

            Example
            -------

            .. code-block:: python

               d = UTCDateTime(2020, 8, 15, hour=23, minute=12)
               d - timedelta(days=1, seconds=5) == UTCDateTime(
                   2020, 8, 14, hour=23, minute=11, second=55
               )

               d - UTCDateTime(2020, 8, 14) > timedelta(days=1)
            """
            if isinstance(other, (UTCDateTime, OffsetDateTime, ZonedDateTime)):
                return self._py_dt - other._py_dt
            elif isinstance(other, LocalDateTime):
                return self._py_dt - other._py_dt.astimezone(_UTC)
            elif isinstance(other, timedelta):
                return self._from_py_unchecked(self._py_dt - other)
            return NotImplemented

    def as_utc(self) -> UTCDateTime:
        return self

    @overload
    def as_offset(self, /) -> OffsetDateTime: ...

    @overload
    def as_offset(self, offset: timedelta, /) -> OffsetDateTime: ...

    def as_offset(self, offset: timedelta | None = None, /) -> OffsetDateTime:
        return OffsetDateTime._from_py_unchecked(
            self._py_dt.astimezone(
                _timezone(offset) if offset else _zero_timezone
            )
        )

    @classmethod
    def from_naive(cls, d: NaiveDateTime, /) -> UTCDateTime:
        """Create an instance from a naive datetime."""
        return cls._from_py_unchecked(d._py_dt.replace(tzinfo=_UTC))

    @classmethod
    def strptime(cls, s: str, /, fmt: str) -> UTCDateTime:
        """Simple alias for ``UTCDateTime.from_py(datetime.strptime(s, fmt))``

        Example
        -------

        .. code-block:: python

            UTCDateTime.strptime("2020-08-15+0000", "%Y-%m-%d%z") == UTCDateTime(2020, 8, 15)
            UTCDateTime.strptime("2020-08-15", "%Y-%m-%d")

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

        .. code-block:: python

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

        .. code-block:: python

            UTCDateTime.from_rfc2822("Sat, 15 Aug 2020 23:12:00 GMT")
            # -> UTCDateTime(2020-08-15 23:12:00Z)

            # also valid:
            UTCDateTime.from_rfc2822("Sat, 15 Aug 2020 23:12:00 +0000")
            UTCDateTime.from_rfc2822("Sat, 15 Aug 2020 23:12:00 UT")

            # Error: nonzero offset. Use OffsetDateTime.from_rfc2822() instead
            UTCDateTime.from_rfc2822("Sat, 15 Aug 2020 23:12:00 +0200")


        Warning
        -------
        * Nonzero offsets will not be implicitly converted to UTC.
          Use :meth:`OffsetDateTime.from_rfc2822` if you'd like to
          parse an RFC 2822 string with a nonzero offset.
        * The offset ``-0000`` has special meaning in RFC 2822,
          and is not allowed here.
        """
        parsed = parsedate_to_datetime(s)
        # Nested ifs to keep happy path fast
        if parsed.tzinfo is not _UTC:
            if parsed.tzinfo is None:
                raise ValueError(
                    "RFC 2822 string with -0000 offset cannot be parsed as UTC"
                )
            raise ValueError(
                "RFC 2822 string can't have nonzero offset to be parsed as UTC"
            )
        return cls._from_py_unchecked(parsedate_to_datetime(s))

    def rfc3339(self) -> str:
        """Format as an RFC 3339 string

        For UTCDateTime, equivalent to :meth:`~AwareDateTime.canonical_str`.
        Inverse of :meth:`from_rfc3339`.

        Example
        -------

        .. code-block:: python

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

        .. code-block:: python

            UTCDateTime.from_rfc3339("2020-08-15T23:12:00Z")
            # -> UTCDateTime(2020-08-15 23:12:00Z)

            # also valid:
            UTCDateTime.from_rfc3339("2020-08-15T23:12:00+00:00")
            UTCDateTime.from_rfc3339("2020-08-15_23:12:00.34Z")
            UTCDateTime.from_rfc3339("2020-08-15t23:12:00z")

            # not valid (nonzero offset):
            UTCDateTime.from_rfc3339("2020-08-15T23:12:00+02:00")

        Warning
        -------
        Nonzero offsets will not be implicitly converted to UTC.
        Use :meth:`OffsetDateTime.from_rfc3339` if you'd like to
        parse an RFC 3339 string with a nonzero offset.
        """
        return cls._from_py_unchecked(_parse_utc_rfc3339(s))

    def __repr__(self) -> str:
        return f"whenever.UTCDateTime({self})"

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


class OffsetDateTime(AwareDateTime):
    """A datetime with a fixed UTC offset.
    Useful for representing the local time at a specific location.

    Example
    -------

    .. code-block:: python

       from whenever import hours
       # 9 AM in Salt Lake City, with the UTC offset at the time
       pycon23_started = OffsetDateTime(2023, 4, 21, hour=9, offset=hours(-6))

    Note
    ----

    The canonical string representation is:

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
        """Create an instance at the current time with the given offset"""
        return cls._from_py_unchecked(_datetime.now(_timezone(offset)))

    def canonical_str(self) -> str:
        return self._py_dt.isoformat()

    __str__ = canonical_str

    @classmethod
    def from_canonical_str(cls, s: str, /) -> OffsetDateTime:
        if not _match_offset_str(s):
            raise InvalidFormat()
        return cls._from_py_unchecked(_fromisoformat(s))

    @classmethod
    def from_timestamp(cls, i: float, /, offset: timedelta) -> OffsetDateTime:
        """Create a OffsetDateTime from a UNIX timestamp.
        The inverse of :meth:`~AwareDateTime.timestamp`.

        Example
        -------

        .. code-block:: python

           OffsetDateTime.from_timestamp(0, offset=hours(3)) == (
               OffsetDateTime(1970, 1, 1, 3, offset=hours(3))
           )
           d = OffsetDateTime.from_timestamp(1_123_000_000.45, offset=hours(-2))
           d == OffsetDateTime(2004, 8, 2, 14, 26, 40, 450_000, offset=hours(-2))

           OffsetDateTime.from_timestamp(d.timestamp(), d.offset) == d
        """
        return cls._from_py_unchecked(_fromtimestamp(i, _timezone(offset)))

    @classmethod
    def from_py(cls, d: _datetime, /) -> OffsetDateTime:
        if not isinstance(d.tzinfo, _timezone):
            raise ValueError(
                "Datetime's tzinfo is not a datetime.timezone, "
                f"got tzinfo={d.tzinfo!r}"
            )
        return cls._from_py_unchecked(d)

    if TYPE_CHECKING:

        @property
        def tzinfo(self) -> _timezone: ...

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
        ) -> OffsetDateTime: ...

    else:

        def replace(self, /, **kwargs) -> OffsetDateTime:
            if not _no_tzinfo_or_fold(kwargs):
                raise TypeError("tzinfo and fold are not allowed arguments")
            try:
                kwargs["tzinfo"] = _timezone(kwargs.pop("offset"))
            except KeyError:
                pass
            return self._from_py_unchecked(self._py_dt.replace(**kwargs))

        __hash__ = property(attrgetter("_py_dt.__hash__"))

        # Hiding __eq__ from mypy ensures that --strict-equality works
        def __eq__(self, other: object) -> bool:
            if not isinstance(other, (UTCDateTime, OffsetDateTime)):
                return NotImplemented
            return self._py_dt == other._py_dt

    @property
    def offset(self) -> timedelta:
        # We know that offset is never None, because we set it in __init__
        return self._py_dt.utcoffset()  # type: ignore[return-value]

    def exact_eq(self, other: OffsetDateTime, /) -> bool:
        # FUTURE: there's probably a faster way to do this
        return self == other and self.offset == other.offset

    def __lt__(self, other: AwareDateTime) -> bool:
        if not isinstance(other, (UTCDateTime, OffsetDateTime)):
            return NotImplemented
        return self._py_dt < other._py_dt

    def __le__(self, other: AwareDateTime) -> bool:
        if not isinstance(other, (UTCDateTime, OffsetDateTime)):
            return NotImplemented
        return self._py_dt <= other._py_dt

    def __gt__(self, other: AwareDateTime) -> bool:
        if not isinstance(other, (UTCDateTime, OffsetDateTime)):
            return NotImplemented
        return self._py_dt > other._py_dt

    def __ge__(self, other: AwareDateTime) -> bool:
        if not isinstance(other, (UTCDateTime, OffsetDateTime)):
            return NotImplemented
        return self._py_dt >= other._py_dt

    def __sub__(self, other: AwareDateTime) -> timedelta:
        """Subtract another datetime to get the timedelta between them

        Example
        -------

        .. code-block:: python

            d = OffsetDateTime(2020, 8, 15, 23, 12, offset=hours(1))
            d - timedelta(days=1, hours=4, seconds=5) == OffsetDateTime(
                2020, 8, 14, 23, 11, 55, offset=hours(-3)
            )

            d - OffsetDateTime(2020, 8, 14, offset=hours(0)) > timedelta(days=1)
        """
        if isinstance(other, (UTCDateTime, OffsetDateTime, ZonedDateTime)):
            return self._py_dt - other._py_dt
        elif isinstance(other, LocalDateTime):
            return self._py_dt - other._py_dt.astimezone()
        return NotImplemented

    def as_utc(self) -> UTCDateTime:
        return UTCDateTime._from_py_unchecked(self._py_dt.astimezone(_UTC))

    @overload
    def as_offset(self, /) -> OffsetDateTime: ...

    @overload
    def as_offset(self, offset: timedelta, /) -> OffsetDateTime: ...

    def as_offset(self, offset: timedelta | None = None, /) -> OffsetDateTime:
        return (
            self
            if offset is None
            else self._from_py_unchecked(
                self._py_dt.astimezone(_timezone(offset))
            )
        )

    @classmethod
    def from_naive(
        cls, d: NaiveDateTime, /, offset: timedelta
    ) -> OffsetDateTime:
        """Create an instance from a naive datetime."""
        return cls._from_py_unchecked(
            d._py_dt.replace(tzinfo=_timezone(offset))
        )

    @classmethod
    def strptime(cls, s: str, /, fmt: str) -> OffsetDateTime:
        """Simple alias for ``OffsetDateTime.from_py(datetime.strptime(s, fmt))``

        Example
        -------

        .. code-block:: python

            OffsetDateTime.strptime(
                "2020-08-15+0200", "%Y-%m-%d%z"
            ) == OffsetDateTime(2020, 8, 15, offset=hours(2))

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

        .. code-block:: python

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

        .. code-block:: python

            OffsetDateTime.from_rfc2822("Sat, 15 Aug 2020 23:12:00 +0200")
            # -> OffsetDateTime(2020-08-15 23:12:00+02:00)

            # also valid:
            OffsetDateTime.from_rfc2822("Sat, 15 Aug 2020 23:12:00 UT")
            OffsetDateTime.from_rfc2822("Sat, 15 Aug 2020 23:12:00 GMT")
            OffsetDateTime.from_rfc2822("Sat, 15 Aug 2020 23:12:00 MST")

        Warning
        -------
        The offset ``-0000`` has special meaning in RFC 2822,
        and is not allowed here.
        """
        parsed = parsedate_to_datetime(s)
        if parsed.tzinfo is None:
            raise ValueError(
                "RFC 2822 string with -0000 offset cannot be parsed as UTC"
            )
        return cls._from_py_unchecked(parsedate_to_datetime(s))

    def rfc3339(self) -> str:
        """Format as an RFC 3339 string

        For ``OffsetDateTime``, equivalent to :meth:`~DateTime.canonical_str`.
        Inverse of :meth:`from_rfc3339`.

        Example
        -------

        .. code-block:: python

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

        .. code-block:: python

            OffsetDateTime.from_rfc3339("2020-08-15T23:12:00+02:00")
            # -> OffsetDateTime(2020-08-15 23:12:00+02:00)

            # also valid:
            OffsetDateTime.from_rfc3339("2020-08-15T23:12:00Z")
            OffsetDateTime.from_rfc3339("2020-08-15_23:12:00.23-12:00")
            OffsetDateTime.from_rfc3339("2020-08-15t23:12:00z")
        """
        return cls._from_py_unchecked(_parse_rfc3339(s))

    def __repr__(self) -> str:
        return f"whenever.OffsetDateTime({self})"

    # a custom pickle implementation with a smaller payload
    def __reduce__(self) -> tuple[object, ...]:
        return (
            _unpkl_offset,
            self._py_dt.timetuple()[:6]
            + (self._py_dt.microsecond, self._py_dt.utcoffset()),
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

    - The ``tz`` argument is the timezone's name in the IANA database.

    - The ``disambiguate`` argument controls how ambiguous datetimes are handled:

      - ``"raise"``: ambiguous datetimes raise :class:`Ambiguous`.
        ``fold`` is set to ``0`` on the inner :class:`~datetime.datetime`.
      - ``"earlier"``: pick the earlier datetime (before the DST transition).
        ``fold`` is set to ``0`` on the inner :class:`~datetime.datetime`.
      - ``"later"``: pick the later datetime (after the DST transition).
        ``fold`` is set to ``1`` on the inner :class:`~datetime.datetime`.

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
       changing_the_guard = ZonedDateTime(2024, 12, 8, hour=11, tz="Europe/London")

       # Explicitly resolve ambiguities when clocks are set backwards.
       # Default is "raise", which raises an exception
       night_shift = ZonedDateTime(2023, 10, 29, 1, 15, tz="Europe/London", disambiguate="later")

       # ZoneInfoNotFoundError: no such timezone
       ZonedDateTime(2024, 12, 8, hour=11, tz="invalid")

       # DoesntExistInZone: 2:15 AM does not exist on this day
       ZonedDateTime(2023, 3, 26, 2, 15, tz="Europe/Amsterdam")

    Warning
    -------

    The canonical string representation is:

    .. code-block:: text

       YYYY-MM-DDTHH:MM:SS(.ffffff)±HH:MM(:SS(.ffffff))[TIMEZONE NAME]

    For example:

    .. code-block:: text

       2020-08-15T23:12:00+01:00[Europe/London]

    The offset is included to disambiguate cases where the same
    local time occurs twice due to DST transitions.
    If the offset is invalid for the system timezone,
    parsing will raise :class:`InvalidOffsetForZone`.

    This format is similar to those `used by other languages <https://tc39.es/proposal-temporal/docs/strings.html#iana-time-zone-names>`_,
    but it is *not* RFC 3339 or ISO 8601 compliant
    (these standards don't support timezone names.)
    Use :meth:`~AwareDateTime.as_offset` first if you
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
        fold = _as_fold(disambiguate)
        dt = _datetime(
            year,
            month,
            day,
            hour,
            minute,
            second,
            microsecond,
            zone_info := ZoneInfo(tz),
            fold=fold,
        )
        if not _exists_in_tz(dt):
            raise DoesntExistInZone.for_timezone(dt, zone_info)
        if disambiguate == "raise" and dt.astimezone(_UTC) != dt.replace(
            fold=1
        ).astimezone(_UTC):
            raise Ambiguous.for_timezone(dt, zone_info)
        self._py_dt = dt

    @classmethod
    def now(cls, tz: str) -> ZonedDateTime:
        """Create an instance from the current time in the given timezone"""
        return cls._from_py_unchecked(_datetime.now(ZoneInfo(tz)))

    def canonical_str(self) -> str:
        return (
            f"{self._py_dt.isoformat()}"
            f"[{self._py_dt.tzinfo.key}]"  # type: ignore[union-attr]
        )

    __str__ = canonical_str

    @classmethod
    def from_canonical_str(cls, s: str, /) -> ZonedDateTime:
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

    @classmethod
    def from_timestamp(cls, i: float, /, tz: str) -> ZonedDateTime:
        """Create an instace from a UNIX timestamp."""
        return cls._from_py_unchecked(_fromtimestamp(i, ZoneInfo(tz)))

    @classmethod
    def from_py(cls, d: _datetime, /) -> ZonedDateTime:
        if not isinstance(d.tzinfo, ZoneInfo):
            raise ValueError(
                "Can only create ZonedDateTime from ZoneInfo, "
                f"got datetime with tzinfo={d.tzinfo!r}"
            )
        if not _exists_in_tz(d):
            raise DoesntExistInZone.for_timezone(d, d.tzinfo)
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
            tz: str | NOT_SET = NOT_SET(),
            disambiguate: Disambiguate | NOT_SET = NOT_SET(),
        ) -> ZonedDateTime: ...

    else:

        def replace(self, /, **kwargs) -> ZonedDateTime:
            if not _no_tzinfo_or_fold(kwargs):
                raise TypeError("tzinfo and/or fold are not allowed arguments")
            try:
                kwargs["tzinfo"] = ZoneInfo(kwargs.pop("tz"))
            except KeyError:
                pass
            disambiguate = kwargs.pop("disambiguate", "raise")
            kwargs["fold"] = _as_fold(disambiguate)
            dt = self._py_dt.replace(**kwargs)
            as_utc = dt.astimezone(_UTC)
            if as_utc.astimezone(dt.tzinfo) != dt:
                raise DoesntExistInZone.for_timezone(dt, dt.tzinfo)
            if disambiguate == "raise" and as_utc != dt:
                raise Ambiguous.for_timezone(dt, dt.tzinfo)
            return self._from_py_unchecked(dt)

    if TYPE_CHECKING or SPHINX_BUILD:  # pragma: no cover

        @property
        def fold(self) -> Literal[0, 1]:
            """The fold value"""
            ...

        @property
        def tzinfo(self) -> ZoneInfo:
            """The timezone"""
            ...

        @property
        def tz(self) -> str:
            """The timezone name"""
            ...

    else:
        fold = property(attrgetter("_py_dt.fold"))
        tzinfo = property(attrgetter("_py_dt.tzinfo"))
        tz = property(attrgetter("_py_dt.tzinfo.key"))

    @property
    def offset(self) -> timedelta:
        return self._py_dt.utcoffset()  # type: ignore[return-value]

    def __hash__(self) -> int:
        return hash(self._py_dt.astimezone(_UTC))

    # Hiding __eq__ from mypy ensures that --strict-equality works.
    if not TYPE_CHECKING:  # pragma: no branch

        def __eq__(self, other: object) -> bool:
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
        return (
            self.tz is other.tz
            and self.fold == other.fold
            and self._py_dt == other._py_dt
        )

    def __lt__(self, other: AwareDateTime) -> bool:
        if not isinstance(other, AwareDateTime):
            return NotImplemented
        return self._py_dt.astimezone(_UTC) < other._py_dt.astimezone(_UTC)

    def __le__(self, other: AwareDateTime) -> bool:
        if not isinstance(other, AwareDateTime):
            return NotImplemented
        return self._py_dt.astimezone(_UTC) <= other._py_dt.astimezone(_UTC)

    def __gt__(self, other: AwareDateTime) -> bool:
        if not isinstance(other, AwareDateTime):
            return NotImplemented
        return self._py_dt.astimezone(_UTC) > other._py_dt.astimezone(_UTC)

    def __ge__(self, other: AwareDateTime) -> bool:
        if not isinstance(other, AwareDateTime):
            return NotImplemented
        return self._py_dt.astimezone(_UTC) >= other._py_dt.astimezone(_UTC)

    def __add__(self, delta: timedelta) -> ZonedDateTime:
        """Add a timedelta to this datetime.
        Unlike the standard library, this method accounts for DST transitions.

        Example
        -------
        .. code-block:: python

           d = ZonedDateTime(2023, 10, 28, 12, tz="Europe/Amsterdam", disambiguate="earlier")

           # one hour skipped due to DST transition
           d + timedelta(hours=24) # 2023-10-29T11:00:00+01:00[Europe/Amsterdam]
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
        def __sub__(self, other: AwareDateTime) -> timedelta: ...

        @overload
        def __sub__(self, other: timedelta) -> ZonedDateTime: ...

        def __sub__(
            self, other: AwareDateTime | timedelta
        ) -> AwareDateTime | timedelta: ...

    else:

        def __sub__(
            self, other: timedelta | AwareDateTime
        ) -> AwareDateTime | timedelta:
            """Subtract another datetime or timedelta"""
            if isinstance(other, (UTCDateTime, OffsetDateTime, ZonedDateTime)):
                return self._py_dt.astimezone(_UTC) - other._py_dt
            elif isinstance(other, LocalDateTime):
                return self._py_dt - other._py_dt.astimezone()
            elif isinstance(other, timedelta):
                return self._from_py_unchecked(
                    (self._py_dt.astimezone(_UTC) - other).astimezone(
                        self._py_dt.tzinfo
                    )
                )
            return NotImplemented

    def disambiguated(self) -> bool:
        """Whether disambiguation was needed to create this datetime.

        Example
        -------

        .. code-block:: python

           # False: no disambiguation needed
           ZonedDateTime(2020, 8, 15, 23, tz="Europe/London", disambiguate="later").disambiguated()
           # True: disambiguation needed, since 2:15 AM occurs twice
           ZonedDateTime(2023, 10, 29, 2, 15, tz="Europe/Amsterdam", disambiguate="later").disambiguated()
        """
        return self._py_dt.astimezone(_UTC) != self._py_dt

    def as_utc(self) -> UTCDateTime:
        return UTCDateTime._from_py_unchecked(self._py_dt.astimezone(_UTC))

    @overload
    def as_offset(self, /) -> OffsetDateTime: ...

    @overload
    def as_offset(self, offset: timedelta, /) -> OffsetDateTime: ...

    def as_offset(self, offset: timedelta | None = None, /) -> OffsetDateTime:
        return OffsetDateTime._from_py_unchecked(
            self._py_dt.astimezone(
                # mypy doesn't know that offset is never None
                _timezone(offset or self._py_dt.utcoffset())  # type: ignore[arg-type]
            )
        )

    def as_zoned(self, tz: str, /) -> ZonedDateTime:
        return self._from_py_unchecked(self._py_dt.astimezone(ZoneInfo(tz)))

    @classmethod
    def from_naive(
        cls,
        d: NaiveDateTime,
        /,
        tz: str,
        disambiguate: Disambiguate = "raise",
    ) -> ZonedDateTime:
        """Create an instance from a naive datetime."""
        zinfo = ZoneInfo(tz)
        zoned = d._py_dt.replace(tzinfo=zinfo, fold=_as_fold(disambiguate))
        utc = zoned.astimezone(_UTC)
        if utc.astimezone(zinfo) != zoned:
            raise DoesntExistInZone.for_timezone(d._py_dt, zinfo)
        if disambiguate == "raise" and zoned != utc:
            raise Ambiguous.for_timezone(zoned, zinfo)
        return cls._from_py_unchecked(zoned)

    def __repr__(self) -> str:
        return f"whenever.ZonedDateTime({self})"

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
            ZoneInfo(tz),
            fold=fold,
        )
    )


class LocalDateTime(AwareDateTime):
    """Represents local time bound to the system timezone.

    The ``disambiguate`` argument controls how ambiguous datetimes are handled:

    - ``"raise"``: ambiguous datetimes raise :class:`Ambiguous`.
      This will set ``fold=0`` on the inner :class:`~datetime.datetime`.
    - ``"earlier"``: pick the earlier datetime (before the DST transition).
      This will set ``fold=0`` on the inner :class:`~datetime.datetime`.
    - ``"later"``: pick the later datetime (after the DST transition).
      This will set ``fold=1`` on the inner :class:`~datetime.datetime`.

    Raises
    ------
    Ambiguous
        If ``disambiguate`` is ``"raise"`` and the datetime is ambiguous
    DoesntExistInZone
        If the datetime does not exist in the system timezone

    Example
    -------

    .. code-block:: python

       from whenever import LocalDateTime

       # always at 8:00 in the system timezone (e.g. America/Los_Angeles)
       wake_up = LocalDateTime(2020, 8, 15, hour=8)

       # Conversion based on Los Angeles' offset
       wake_up.as_utc()  # 2020-08-15T15:00:00Z

       # If we change the system timezone, the result changes
       os.environ["TZ"] = "Europe/Amsterdam"
       wake_up.as_utc()  # 2020-08-15T06:00:00Z

    Note
    ----

    The canonical string representation is:

    .. code-block:: text

       YYYY-MM-DDTHH:MM:SS(.ffffff)±HH:MM(:SS(.ffffff))

    This format is both RFC 3339 and ISO 8601 compliant.
    The offset is included to disambiguate cases where the same
    local time occurs twice due to DST transitions.
    If the offset is invalid for the system timezone,
    parsing will raise :class:`InvalidOffsetForZone`.

    Note
    ----
    The underlying :class:`~datetime.datetime` object is always timezone-naive.

    Warning
    -------
    The meaning of this type changes if the system timezone changes.
    This means that instances are *not* hashable.
    It isn't recommended to use this type for long-term storage,
    or to change the system timezone after initialization.
    If you do, be aware of the following:

    - Ambiguities are resolved at initialization time against the system
      timezone. Ambiguities arising from later changes in the system
      timezone are **undefined**.
    - Non-existance is resolved at initialization time against the system
      timezone. Non-existance arising from later changes in the system
      timezone will raise :class:`DoesntExistInZone` when methods are called.

    Use :meth:`exists` to check whether a datetime (still) exists in the
    system timezone.
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
        fold = _as_fold(disambiguate)
        dt = _datetime(
            year, month, day, hour, minute, second, microsecond, fold=fold
        )
        # If it doesn't survive the UTC roundtrip, it doesn't exist
        if dt.astimezone(_UTC).astimezone().replace(tzinfo=None) != dt:
            raise DoesntExistInZone.for_system_timezone(dt)
        if disambiguate == "raise" and dt.astimezone(_UTC) != dt.replace(
            fold=1
        ).astimezone(_UTC):
            raise Ambiguous.for_system_timezone(dt)
        self._py_dt = dt

    @classmethod
    def now(cls) -> LocalDateTime:
        """Create an instance from the current time"""
        return cls._from_py_unchecked(_datetime.now())

    def canonical_str(self) -> str:
        if not self.exists():
            raise DoesntExistInZone.for_system_timezone(self._py_dt)
        return self._py_dt.astimezone().isoformat()

    __str__ = canonical_str

    @classmethod
    def from_canonical_str(cls, s: str, /) -> LocalDateTime:
        if not _match_offset_str(s):
            raise InvalidFormat()
        dt = _fromisoformat(s)
        # Determine `fold` from the offset
        offset = dt.utcoffset()
        dt = dt.replace(tzinfo=None)
        if offset != dt.astimezone().utcoffset():
            dt = dt.replace(fold=1)
            if dt.astimezone().utcoffset() != offset:
                raise InvalidOffsetForZone()
        return cls._from_py_unchecked(dt)

    @classmethod
    def from_timestamp(cls, i: float, /) -> LocalDateTime:
        """Create an instace from a UNIX timestamp.
        The inverse of :meth:`~AwareDateTime.timestamp`.

        Example
        -------

        .. code-block:: python

           # assuming system timezone is America/New_York
           LocalDateTime.from_timestamp(0) == LocalDateTime(1969, 12, 31, 19)
           d = LocalDateTime.from_timestamp(1_123_000_000.45)
           d == LocalDateTime(2004, 8, 2, 16, 26, 40, 450_000)

           LocalDateTime.from_timestamp(d.timestamp()) == d
        """
        return cls._from_py_unchecked(_fromtimestamp(i))

    @classmethod
    def from_py(cls, d: _datetime, /) -> LocalDateTime:
        if d.tzinfo is not None:
            raise ValueError(
                "Can only create LocalDateTime from a naive datetime, "
                f"got datetime with tzinfo={d.tzinfo!r}"
            )
        if d.astimezone(_UTC).astimezone().replace(tzinfo=None) != d:
            raise DoesntExistInZone.for_system_timezone(d)
        return cls._from_py_unchecked(d)

    def __repr__(self) -> str:
        try:
            return f"whenever.LocalDateTime({self})"
        except DoesntExistInZone:
            return f"whenever.LocalDateTime({self._py_dt.isoformat()}[nonexistent])"

    @property
    def offset(self) -> timedelta:
        if not self.exists():
            raise DoesntExistInZone.for_system_timezone(self._py_dt)
        return self._py_dt.astimezone().utcoffset()  # type: ignore[return-value]

    if TYPE_CHECKING:

        @property
        def fold(self) -> Literal[0, 1]:
            """The fold value"""
            ...

    else:
        fold = property(attrgetter("_py_dt.fold"))

        def __eq__(self, other: object) -> bool:
            if not isinstance(other, AwareDateTime):
                return NotImplemented
            return self._py_dt.astimezone(_UTC) == other._py_dt.astimezone(
                _UTC
            )

    def __lt__(self, other: AwareDateTime) -> bool:
        if not isinstance(other, AwareDateTime):
            return NotImplemented
        return self._py_dt.astimezone(_UTC) < other._py_dt.astimezone(_UTC)

    def __le__(self, other: AwareDateTime) -> bool:
        if not isinstance(other, AwareDateTime):
            return NotImplemented
        return self._py_dt.astimezone(_UTC) <= other._py_dt.astimezone(_UTC)

    def __gt__(self, other: AwareDateTime) -> bool:
        if not isinstance(other, AwareDateTime):
            return NotImplemented
        return self._py_dt.astimezone(_UTC) > other._py_dt.astimezone(_UTC)

    def __ge__(self, other: AwareDateTime) -> bool:
        if not isinstance(other, AwareDateTime):
            return NotImplemented
        return self._py_dt.astimezone(_UTC) >= other._py_dt.astimezone(_UTC)

    def exact_eq(self, other: LocalDateTime) -> bool:
        return (
            self._py_dt == other._py_dt
            and self._py_dt.fold == other._py_dt.fold
        )

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
            disambiguate: Disambiguate | NOT_SET = NOT_SET(),
        ) -> LocalDateTime: ...

    else:

        def replace(self, /, **kwargs) -> LocalDateTime:
            if not _no_tzinfo_or_fold(kwargs):
                raise TypeError("tzinfo and/or fold are not allowed arguments")
            disambiguate = kwargs.pop("disambiguate", "raise")
            fold = kwargs["fold"] = _as_fold(disambiguate)
            d = self._py_dt.replace(**kwargs)
            utc = d.astimezone(_UTC)
            if utc.astimezone().replace(tzinfo=None) != d:
                raise DoesntExistInZone.for_system_timezone(d)
            if disambiguate == "raise" and utc != d.replace(
                fold=not fold
            ).astimezone(_UTC):
                raise Ambiguous.for_system_timezone(d)
            return self._from_py_unchecked(self._py_dt.replace(**kwargs))

    def __add__(self, other: timedelta) -> LocalDateTime:
        """Add a timedelta to this datetime

        Example
        -------
        .. code-block:: python

           d = LocalDateTime(2020, 8, 15, hour=23, minute=12, fold=0)
           d + timedelta(days=1, seconds=5) == LocalDateTime(
               2020, 8, 16, hour=23, minute=12, second=5, fold=0
           )
        """
        if not isinstance(other, timedelta):
            return NotImplemented
        return (self.as_utc() + other).as_local()

    if TYPE_CHECKING:

        @overload
        def __sub__(self, other: AwareDateTime) -> timedelta: ...

        @overload
        def __sub__(self, other: timedelta) -> LocalDateTime: ...

        def __sub__(
            self, other: AwareDateTime | timedelta
        ) -> AwareDateTime | timedelta: ...

    else:

        def __sub__(
            self, other: timedelta | AwareDateTime
        ) -> AwareDateTime | timedelta:
            """Subtract another datetime or timedelta

            Example
            -------
            .. code-block:: python

               d = LocalDateTime(2020, 8, 15, hour=23, minute=12, fold=0)
               d - timedelta(days=1, seconds=5) == LocalDateTime(
                   2020, 8, 14, hour=23, minute=11, second=55, fold=0
               )

            """
            utc = self._py_dt.astimezone(_UTC)
            if utc.astimezone().replace(tzinfo=None) != self._py_dt:
                raise DoesntExistInZone.for_system_timezone(self._py_dt)
            if isinstance(other, LocalDateTime):
                return utc - other._py_dt.astimezone(_UTC)
            elif isinstance(
                other, (UTCDateTime, OffsetDateTime, ZonedDateTime)
            ):
                return utc - other._py_dt
            elif isinstance(other, timedelta):
                return (self.as_utc() - other).as_local()
            return NotImplemented

    def disambiguated(self) -> bool:
        """Whether the disambiguation has an effect.

        Note
        ----
        Non-existent datetimes are not considered ambiguous.

        Example
        -------

        .. code-block:: python

           # (assuming system timezone is Europe/Amsterdam)
           # False: disambiguating has no effect
           LocalDateTime(2020, 8, 15, 23, disambiguate="later").disambiguated()
           # True: disambiguating has an effect, since 2:15 AM occurs twice
           LocalDateTime(2023, 10, 29, 2, 15, disambiguate="later").disambiguated()
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
           d.exists()  # True
           os.environ["TZ"] = "Europe/Amsterdam"
           d.exists()  # False
        """
        return (
            self._py_dt.astimezone(_UTC).astimezone().replace(tzinfo=None)
            == self._py_dt
        )

    def as_utc(self) -> UTCDateTime:
        d = self._py_dt.astimezone(_UTC)
        # If the UTC round-trip fails, it means the datetime doesn't exist
        if d.astimezone().replace(tzinfo=None) != self._py_dt:
            raise DoesntExistInZone.for_system_timezone(self._py_dt)
        return UTCDateTime._from_py_unchecked(d)

    @overload
    def as_offset(self, /) -> OffsetDateTime: ...

    @overload
    def as_offset(self, offset: timedelta, /) -> OffsetDateTime: ...

    def as_offset(self, offset: timedelta | None = None, /) -> OffsetDateTime:
        if not self.exists():
            raise DoesntExistInZone.for_system_timezone(self._py_dt)
        return OffsetDateTime._from_py_unchecked(
            self._py_dt.astimezone(
                None if offset is None else _timezone(offset)
            )
        )

    def as_zoned(self, tz: str, /) -> ZonedDateTime:
        if not self.exists():
            raise DoesntExistInZone.for_system_timezone(self._py_dt)
        return ZonedDateTime._from_py_unchecked(
            self._py_dt.astimezone(ZoneInfo(tz))
        )

    def as_local(self) -> LocalDateTime:
        return self

    @classmethod
    def from_naive(
        cls, d: NaiveDateTime, /, disambiguate: Disambiguate = "raise"
    ) -> LocalDateTime:
        """Create an instance from a naive datetime."""
        fold = _as_fold(disambiguate)
        local = d._py_dt.replace(fold=fold)
        utc = local.astimezone(_UTC)
        if utc.astimezone().replace(tzinfo=None) != local:
            raise DoesntExistInZone.for_system_timezone(d._py_dt)
        if disambiguate == "raise" and utc != local.replace(
            fold=not fold
        ).astimezone(_UTC):
            raise Ambiguous.for_system_timezone(d._py_dt)
        return cls._from_py_unchecked(local)

    def naive(self) -> NaiveDateTime:
        return NaiveDateTime._from_py_unchecked(self._py_dt)

    # a custom pickle implementation with a smaller payload
    def __reduce__(self) -> tuple[object, ...]:
        return (
            _unpkl_local,
            self._py_dt.timetuple()[:6]
            + (self._py_dt.microsecond, self._py_dt.fold),
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
    any of the real-world complexities.

    Note
    ----

    The canonical string representation is:

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

    def canonical_str(self) -> str:
        return self._py_dt.isoformat()

    __str__ = canonical_str

    @classmethod
    def from_canonical_str(cls, s: str, /) -> NaiveDateTime:
        if not _match_naive_str(s):
            raise InvalidFormat()
        return cls._from_py_unchecked(_fromisoformat(s))

    @classmethod
    def from_py(cls, d: _datetime, /) -> NaiveDateTime:
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
            year: int | NOT_SET = NOT_SET(),
            month: int | NOT_SET = NOT_SET(),
            day: int | NOT_SET = NOT_SET(),
            hour: int | NOT_SET = NOT_SET(),
            minute: int | NOT_SET = NOT_SET(),
            second: int | NOT_SET = NOT_SET(),
            microsecond: int | NOT_SET = NOT_SET(),
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
            .. code-block:: python

               # True
               NaiveDateTime(2020, 8, 15, 23) == NaiveDateTime(2020, 8, 15, 23)
               # False
               NaiveDateTime(2020, 8, 15, 23, 1) == NaiveDateTime(2020, 8, 15, 23)
               # False. Use mypy's --strict-equality flag to detect this.
               NaiveDateTime(2020, 8, 15) == UTCDateTime(2020, 8, 15)

            """
            if not isinstance(other, NaiveDateTime):
                return NotImplemented
            return self._py_dt == other._py_dt

    min: ClassVar[NaiveDateTime]
    max: ClassVar[NaiveDateTime]

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

    def __add__(self, other: timedelta) -> NaiveDateTime:
        """Add a timedelta to this datetime

        Example
        -------
        .. code-block:: python

           d = NaiveDateTime(2020, 8, 15, hour=23, minute=12)
           d + timedelta(days=1, seconds=5)  # 2020-08-16T23:12:05
        """
        if not isinstance(other, timedelta):
            return NotImplemented
        return self._from_py_unchecked(self._py_dt + other)

    if TYPE_CHECKING:

        @overload
        def __sub__(self, other: NaiveDateTime) -> timedelta: ...

        @overload
        def __sub__(self, other: timedelta) -> NaiveDateTime: ...

        def __sub__(
            self, other: NaiveDateTime | timedelta
        ) -> NaiveDateTime | timedelta: ...

    else:

        def __sub__(
            self, other: timedelta | NaiveDateTime
        ) -> NaiveDateTime | timedelta:
            """Subtract another datetime or timedelta

            Example
            -------

            .. code-block:: python

               d = NaiveDateTime(2020, 8, 15, hour=23, minute=12)
               d - timedelta(days=1, seconds=5)  # 2020-08-14T23:11:55

               d - NaiveDateTime(2020, 8, 14)
            """
            if isinstance(other, NaiveDateTime):
                return self._py_dt - other._py_dt
            elif isinstance(other, timedelta):
                return self._from_py_unchecked(self._py_dt - other)
            return NotImplemented

    @classmethod
    def strptime(cls, s: str, /, fmt: str) -> NaiveDateTime:
        """Simple alias for ``NaiveDateTime.from_py(datetime.strptime(s, fmt))``

        Example
        -------

        .. code-block:: python

            NaiveDateTime.strptime(
                "2020-08-15", "%Y-%m-%d"
            ) == NaiveDateTime(2020, 8, 15)

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

    def rfc2822(self) -> str:
        """Format as an RFC 2822 string

        Example
        -------

        .. code-block:: python

            >>> NaiveDateTime(2020, 8, 15, 23, 12).rfc2822()
            "Sat, 15 Aug 2020 23:12:00 -0000"
        """
        return format_datetime(self._py_dt)

    @classmethod
    def from_rfc2822(cls, s: str, /) -> NaiveDateTime:
        """Parse an naive datetime in RFC 2822 format.

        Example
        -------

        .. code-block:: python

            NaiveDateTime.from_rfc2822("Sat, 15 Aug 2020 23:12:00 -0000")
            # -> NaiveDateTime(2020-08-15 23:12:00)

            # Error: non-0000 offset
            NaiveDateTime.from_rfc2822("Sat, 15 Aug 2020 23:12:00 GMT")
            NaiveDateTime.from_rfc2822("Sat, 15 Aug 2020 23:12:00 +0000")
            NaiveDateTime.from_rfc2822("Sat, 15 Aug 2020 23:12:00 -0100")

        Warning
        -------
        Only the offset ``-0000`` is allowed, since this has special meaning
        in RFC 2822.
        """
        parsed = parsedate_to_datetime(s)
        if parsed.tzinfo is not None:
            raise ValueError(
                "Only an RFC 2822 string with -0000 offset can be "
                "parsed as NaiveDateTime"
            )
        return cls._from_py_unchecked(parsedate_to_datetime(s))

    def __repr__(self) -> str:
        return f"whenever.NaiveDateTime({self})"

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


class Ambiguous(Exception):
    """A datetime is unexpectedly ambiguous"""

    @staticmethod
    def for_timezone(d: _datetime, tz: _tzinfo) -> Ambiguous:
        return Ambiguous(
            f"{d.replace(tzinfo=None)} is ambiguous "
            f"in timezone {tz.key}"  # type:ignore[attr-defined]
        )

    @staticmethod
    def for_system_timezone(d: _datetime) -> Ambiguous:
        return Ambiguous(
            f"{d.replace(tzinfo=None)} is ambiguous in the system timezone"
        )


class DoesntExistInZone(Exception):
    """A datetime doesnt exist in a timezone, e.g. because of DST"""

    @staticmethod
    def for_timezone(d: _datetime, tz: _tzinfo) -> DoesntExistInZone:
        return DoesntExistInZone(
            f"{d.replace(tzinfo=None)} doesn't exist "
            f"in timezone {tz.key}"  # type:ignore[attr-defined]
        )

    @staticmethod
    def for_system_timezone(d: _datetime) -> DoesntExistInZone:
        return DoesntExistInZone(
            f"{d.replace(tzinfo=None)} doesn't exist in the system timezone"
        )


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
    # tzinfo is not enough, we need to determine the ``fold`` value.
    offset = d.astimezone()
    naive = offset.replace(tzinfo=None)
    if naive.astimezone(_UTC) != offset.astimezone(_UTC):
        naive = naive.replace(fold=1)
    return naive


# Helpers that pre-compute/lookup as much as possible
_UTC = _timezone.utc
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
_match_utc_rfc3339 = re.compile(
    r"\d{4}-\d{2}-\d{2}.\d{2}:\d{2}:\d{2}(\.\d{1,6})?(?:[Zz]|[+-]00:00)"
).fullmatch
_match_rfc3339 = re.compile(
    r"\d{4}-\d{2}-\d{2}.\d{2}:\d{2}:\d{2}(\.\d{1,6})?(?:[Zz]|[+-]\d{2}:\d{2})"
).fullmatch
# Before Python 3.11, fromisoformat() is less capable
if sys.version_info < (3, 11):  # pragma: no cover

    def _fromisoformat_utc(s: str) -> _datetime:
        return _fromisoformat(s[:-1]).replace(tzinfo=_UTC)

    def _parse_rfc3339(s: str) -> _datetime:
        if not (m := _match_rfc3339(s)):
            raise ValueError()
        return _fromisoformat_extra(m, s)

    def _parse_utc_rfc3339(s: str) -> _datetime:
        if not (m := _match_utc_rfc3339(s)):
            raise ValueError()
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

else:
    _fromisoformat_utc = _fromisoformat

    def _parse_utc_rfc3339(s: str) -> _datetime:
        if not _match_utc_rfc3339(s):
            raise ValueError()
        return _fromisoformat(s.upper())

    def _parse_rfc3339(s: str) -> _datetime:
        if not _match_rfc3339(s):
            raise ValueError()
        return _fromisoformat(s.upper())


UTCDateTime.min = UTCDateTime._from_py_unchecked(
    _datetime.min.replace(tzinfo=_UTC)
)
UTCDateTime.max = UTCDateTime._from_py_unchecked(
    _datetime.max.replace(tzinfo=_UTC)
)
NaiveDateTime.min = NaiveDateTime._from_py_unchecked(_datetime.min)
NaiveDateTime.max = NaiveDateTime._from_py_unchecked(_datetime.max)
Disambiguate = Literal["earlier", "later", "raise"]
Fold = Literal[0, 1]
_as_fold: Callable[[Disambiguate], Fold] = {  # type: ignore[assignment]
    "earlier": 0,
    "later": 1,
    "raise": 0,
}.__getitem__


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


def days(i: int, /) -> timedelta:
    """Create a :class:`~datetime.timedelta` with the given number of days.
    ``days(1) == timedelta(days=1)``
    """
    return timedelta(i)
