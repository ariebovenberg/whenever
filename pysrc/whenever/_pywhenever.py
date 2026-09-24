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

from datetime import (
    date as _date,
    datetime as _datetime,
    time as _time,
    timedelta as _timedelta,
    timezone as _timezone,
)
from struct import pack
from time import time_ns as _physical_time_ns
from types import UnionType
from typing import (
    TYPE_CHECKING,
    Any,
    ClassVar,
    Collection,
    Literal,
    Mapping,
    Sequence,
    TypeVar,
    cast,
    no_type_check,
    overload,
)
from warnings import warn

from . import _ideltas
from ._common import (
    _MAX_DELTA_NANOS,
    _MAX_DELTA_SECONDS,
    _MAX_SUBSEC_NANOS,
    DAYS_NOT_ALWAYS_24H_MSG,
    DUMMY_LEAP_YEAR,
    EPOCH_SECS_MAX,
    EPOCH_SECS_MIN,
    NS_PER_DAY,
    OFFSET_DATETIME_DOCS_MSG,
    OFFSET_SHIFT_STALE_MSG,
    # The Rust extension takes its copy of the two reference messages from
    # this module's namespace (scripts/generate_docstrings.py).
    PLAIN_RELATIVE_TO_UNAWARE_MSG,  # noqa: F401
    PLAIN_SHIFT_UNAWARE_MSG,
    RANGE_MSG,
    S_PER_DAY,
    S_PER_HOUR,
    S_PER_MINUTE,
    SPHINX_RUNNING,
    STALE_OFFSET_CALENDAR_MSG,  # noqa: F401
    SYSTEM_TZ,
    UNSET,
    WARNING_HANDLING_DOCS_MSG,
    WheneverDeprecationWarning,
    WheneverWarning,
    _Base,
    _SystemTZ,
    add_alternate_constructors,
    check_nanos,
    check_no_kwargs,
    check_utc_bounds,
    expect_int,
    final,
    format_offset_secs,
    invalid,
    mk_fixed_tzinfo,
    normalize_renamed_keyword,
    replace_fields,
    split_timestamp,
    timestamp_from_parts,
    tzid_display,
    unpack_pickle,
    warn_deprecated,
    warn_lossy_stdlib_subclass,
    warn_renamed_keyword,
)
from ._format import (
    compile_pattern,
    format_fields,
    parse_fields,
    validate_fields,
    warn_pattern,
)
from ._math import (
    DATE_DELTA_UNITS,
    DELTA_UNITS,
    DIFF_FUNCS,
    EXACT_TOTAL_UNITS,
    NS_PER_UNIT_PLURAL,
    TOTAL_UNITS,
    Sign,
    date_diff,
    days_in_month,
    exact_units_to_nanos,
    increment_to_ns_for_datetime,
    increment_to_ns_for_delta,
    is_leap,
    normalize_units,
    resolve_date_rounding,
    resolve_leap_day,
    resolve_rounding,
    rounds_up,
    unit_index,
)
from ._parse import (
    MONTH_TO_RFC2822,
    WEEKDAY_TO_RFC2822,
    InvalidOffsetError,
    ZonedInput,
    date_from_iso,
    datetime_from_iso,
    instant_at_offset,
    matching_local_offset,
    offset_dt_from_iso,
    parse_rfc2822,
    parse_timedelta_component,
    time_from_iso,
    zdt_parts_from_iso,
)
from ._shared import (
    IsoWeekDate,
    MonthDay,
    Weekday,
    YearMonth,
    _nth_weekday_of_month,
)
from ._typing import (
    DateDeltaUnitStr,
    DeltaTotalUnitStr,
    DeltaUnitStr,
    DisambiguationStr,
    ExactDeltaUnitStr,
    OffsetMismatchStr,
    RoundModeStr,
    TimestampUnitStr,
)
from ._tz import (  # noqa: F401
    Fold,
    Gap,
    RepeatedTime,
    SkippedTime,
    TimeZone,
    TimeZoneNotFoundError,
    Unique,
    _clear_tz_cache as _clear_tz_cache,
    _clear_tz_cache_by_keys as _clear_tz_cache_by_keys,
    _set_tzpath as _set_tzpath,
    get_system_tz,
    get_tz,
    get_tzpath as get_tzpath,
    reset_system_tz,
    resolve_ambiguity,
)
from ._tz.ambiguity import check_disambiguation

CalendarUnitCompositionWarning = _ideltas.CalendarUnitCompositionWarning

__all__ = (
    # Date and time
    "Date",
    "YearMonth",
    "MonthDay",
    "IsoWeekDate",
    "Time",
    "Instant",
    "OffsetDateTime",
    "ZonedDateTime",
    "PlainDateTime",
    # Deltas and time units
    "TimeDelta",
    "ItemizedDelta",
    "ItemizedDateDelta",
    "hours",
    "minutes",
    "seconds",
    "milliseconds",
    "microseconds",
    "nanoseconds",
    # Exceptions/warnings
    "DaysAssumed24HoursWarning",
    "StaleOffsetWarning",
    "NaiveArithmeticWarning",
    "CalendarUnitCompositionWarning",
    "WheneverWarning",
    "PotentialDstBugWarning",
    "PickleOffsetMismatchWarning",
    "ImplicitDisambiguationWarning",
    "WheneverDeprecationWarning",
    "SkippedTime",
    "RepeatedTime",
    "InvalidOffsetError",
    "TimeZoneNotFoundError",
    # Other
    "SYSTEM_TZ",
    "reset_system_tz",
    "get_tzpath",
    "_unpkl_date",
    "_unpkl_iddelta",
    "_unpkl_idelta",
    "_unpkl_inst",
    "_unpkl_local",
    "_unpkl_offset",
    "_unpkl_tdelta",
    "_unpkl_time",
    "_unpkl_utc",
    "_unpkl_zoned",
)

# Helpers that pre-compute/lookup as much as possible
_UTC = _timezone.utc
_object_new = object.__new__
_TIME_UNIT_SECS = {"hour": S_PER_HOUR, "minute": S_PER_MINUTE, "second": 1}
_Nanos = int  # type alias for subsecond nanoseconds
_T = TypeVar("_T")
time_ns = _physical_time_ns
IMPLICIT_DISAMBIGUATION_MSG = (
    "resolving a local datetime that is repeated or skipped by a time zone "
    "transition without an explicit disambiguation policy can silently select "
    "the wrong instant; pass disambiguation='compatible', 'earlier', 'later', "
    "or 'raise'. See "
    "https://whenever.readthedocs.io/en/latest/guide/"
    "resolving-local-times.html"
)
INTEGER_OFFSET_DEPRECATION_MSG = (
    "integer offsets are deprecated because their unit is implicit; "
    "pass a TimeDelta instead, for example hours(2)"
)


def _load_tz(tz: Any, /) -> TimeZone:
    return get_system_tz() if tz is SYSTEM_TZ else get_tz(tz)


def _normalize_disambiguation(
    value: Any,
    kwargs: dict[str, Any],
    /,
    *,
    function_name: str,
) -> tuple[Any, bool]:
    """The policy, and whether it came as ``disambiguate=``: the caller
    validates, computes, then warns with ``_warn_disambiguate``.
    """
    return normalize_renamed_keyword(
        value,
        kwargs,
        function_name=function_name,
        new_name="disambiguation",
        old_name="disambiguate",
    )


def _warn_disambiguate(*, stacklevel: int) -> None:
    warn_renamed_keyword(
        "disambiguation", "disambiguate", stacklevel=stacklevel + 1
    )


def _normalize_pattern(
    value: Any,
    kwargs: dict[str, Any],
    /,
) -> tuple[str, bool]:
    """The pattern, and whether it came as ``format=``: the caller parses,
    then warns with ``_warn_format``.
    """
    value, renamed = normalize_renamed_keyword(
        value,
        kwargs,
        function_name="parse",
        new_name="pattern",
        old_name="format",
    )
    check_no_kwargs(kwargs, "parse")
    if value is UNSET:
        raise TypeError(
            "parse() missing 1 required keyword-only argument: 'pattern'"
        )
    return cast(str, value), renamed


def _warn_format(*, stacklevel: int) -> None:
    warn_renamed_keyword("pattern", "format", stacklevel=stacklevel + 1)


def _warn_implicit_disambiguation(*, stacklevel: int) -> None:
    warn(
        IMPLICIT_DISAMBIGUATION_MSG,
        ImplicitDisambiguationWarning,
        stacklevel=stacklevel + 1,
    )


def _resolve_disambiguation(
    dt: _datetime,
    tz: TimeZone,
    disambiguation: Any,
    nanos: int,
    /,
    *,
    preferred_offset: int | None,
) -> tuple[_datetime, bool]:
    """Resolve the naive ``dt`` in ``tz``, and whether the default decided.

    A repeated local time keeps ``preferred_offset`` (the value's current
    offset) while it still applies, whatever ``disambiguation`` says; only
    otherwise does ``disambiguation`` decide, and an omitted one is
    ``"compatible"``. The flag is set where that default had to choose: the
    public method then emits ``ImplicitDisambiguationWarning`` from its own
    frame, and a derived value's caller ignores it.
    """
    ambiguity = tz.ambiguity_for_local(dt)
    implicit = False
    if disambiguation is UNSET:
        disambiguation = "compatible"
        implicit = not isinstance(ambiguity, Unique)
    else:
        check_disambiguation(disambiguation)
    match ambiguity:
        case Fold(_, earlier_offset, later_offset) if preferred_offset in (
            earlier_offset,
            later_offset,
        ):
            disambiguation = (
                "later" if preferred_offset == later_offset else "earlier"
            )
            implicit = False
    return resolve_ambiguity(
        dt, tz, disambiguation, ambiguity, nanos
    ), implicit


def _resolve_zoned_local(
    written: ZonedInput,
    gap_extrapolates: bool,
    disambiguation: DisambiguationStr,
    offset_mismatch: str,
    /,
) -> tuple[_datetime, bool]:
    """Resolve a written local time in a time zone to an exact time, and
    whether the default disambiguation decided (see
    ``_resolve_disambiguation``).

    Shared by the ISO, pattern, and stdlib-datetime constructors. An offset
    that identifies an occurrence of the local time wins outright, ``Z``
    names an exact time rather than an offset, and otherwise
    ``offset_mismatch`` decides between raising, keeping the exact time, and
    keeping the local time and consulting ``disambiguation``.
    """
    if offset_mismatch not in ("raise", "keep_instant", "keep_local"):
        raise invalid("offset_mismatch", offset_mismatch)

    local, nanos, tz, offset, offset_exact = written
    if offset == "Z":
        return instant_at_offset(local, tz, 0), False
    elif offset is not None:
        parsed_offset = int(offset.utcoffset(None).total_seconds())
        matching = matching_local_offset(
            local, tz, parsed_offset, offset_exact, gap_extrapolates
        )
        if matching is not None:
            return matching, False
        elif offset_mismatch == "raise":
            # the database spelling of the ID, not the string as written
            raise InvalidOffsetError._for_tz(parsed_offset, tz.key)
        elif offset_mismatch == "keep_instant":
            return instant_at_offset(local, tz, parsed_offset), False
    return _resolve_disambiguation(
        local, tz, disambiguation, nanos, preferred_offset=None
    )


def _time_units_to_nanos(
    sign: int,
    hours: float,
    minutes: float,
    seconds: float,
    milliseconds: float,
    microseconds: float,
    nanoseconds: int,
) -> int:
    delta_ns = sign * exact_units_to_nanos(
        hours=hours,
        minutes=minutes,
        seconds=seconds,
        milliseconds=milliseconds,
        microseconds=microseconds,
        nanoseconds=nanoseconds,
    )
    if abs(delta_ns) > _MAX_DELTA_NANOS:
        raise ValueError(RANGE_MSG)
    return delta_ns


def _add_seconds(dt: _datetime, secs: int, /) -> _datetime:
    try:
        return dt + _timedelta(seconds=secs)
    except OverflowError:
        raise ValueError(RANGE_MSG) from None


def _shift_date(
    d: Date, sign: int, years: int, months: int, weeks: int, days: int, /
) -> Date:
    months_total = expect_int("years", years) * 12 + expect_int(
        "months", months
    )
    days_total = expect_int("weeks", weeks) * 7 + expect_int("days", days)
    try:
        return d._add_months(sign * months_total)._add_days(sign * days_total)
    except (OverflowError, ValueError):
        raise ValueError(RANGE_MSG) from None


def _shift_components(
    fname: str,
    args: tuple[Any, ...],
    kwargs: dict[str, Any],
    /,
    *,
    units: Collection[str],
    delta_types: type | UnionType,
    expected: str,
) -> Mapping[str, Any]:
    """The components of an ``add()``/``subtract()`` call: its keywords, or
    its positional delta as a mapping.

    Everything else is rejected here, before the caller can warn.
    """
    if len(args) > 1:
        raise TypeError(
            f"{fname}() takes at most one positional argument "
            f"({len(args)} given)"
        )
    if not args:
        for k in kwargs:
            if k not in units:
                raise TypeError(
                    f"{fname}() got an unexpected keyword argument {k!r}"
                )
        return kwargs
    if kwargs:
        raise TypeError(
            f"{fname}() cannot mix positional and keyword arguments"
        )
    [delta] = args
    if not isinstance(delta, delta_types):
        raise TypeError(f"{fname}() argument must be {expected}")
    if isinstance(delta, TimeDelta):
        return {"nanoseconds": delta._total_ns}
    return cast(Mapping[str, Any], delta)


_ANY_DELTA_EXPECTED = "a TimeDelta, ItemizedDelta, or ItemizedDateDelta"


_UNITS_FOR_START_END_OF = (
    "year",
    "month",
    "week_mon",
    "week_sun",
    "day",
    "hour",
    "minute",
    "second",
)


WEEK_UNIT_MSG = "invalid unit: 'week', use 'week_mon' or 'week_sun'"


def _shift_days(dt: _datetime, days: int) -> _datetime:
    return _add_seconds(dt, days * S_PER_DAY)


def _start_of_dt(dt: _datetime, unit: str) -> _datetime:
    if unit == "hour":
        return dt.replace(minute=0, second=0)
    elif unit == "minute":
        return dt.replace(second=0)
    elif unit == "second":
        return dt
    d = (
        dt.date()
        if unit == "day"
        else Date._from_py_unchecked(dt.date())
        .start_of(unit)  # type: ignore[arg-type]
        ._py_date
    )
    return dt.replace(
        year=d.year, month=d.month, day=d.day, hour=0, minute=0, second=0
    )


def _end_of_dt(dt: _datetime, unit: str) -> _datetime:
    if unit == "hour":
        return dt.replace(minute=59, second=59)
    elif unit == "minute":
        return dt.replace(second=59)
    elif unit == "second":
        return dt
    d = (
        dt.date()
        if unit == "day"
        else Date._from_py_unchecked(dt.date())
        .end_of(unit)  # type: ignore[arg-type]
        ._py_date
    )
    return dt.replace(
        year=d.year, month=d.month, day=d.day, hour=23, minute=59, second=59
    )


def _start_of_next_dt(dt: _datetime, unit: str) -> _datetime:
    """The start of the calendar unit after the one containing ``dt``."""
    last_day = _end_of_dt(dt, unit).replace(hour=0, minute=0, second=0)
    return _shift_days(last_day, 1)


def _round_increment_ns(
    unit: str | TimeDelta, increment: int, for_delta: bool
) -> int:
    """The nanoseconds of a ``round()`` increment: a count of a named unit,
    or a ``TimeDelta`` passed as the unit itself."""
    if isinstance(unit, TimeDelta):
        if increment is not UNSET:
            raise TypeError(
                "cannot specify an increment with a TimeDelta argument"
            )
        return unit._to_round_increment_ns(for_delta)
    if increment is UNSET:
        increment = 1
    if for_delta:
        return increment_to_ns_for_delta(unit, increment)
    return increment_to_ns_for_datetime(unit, increment)


@final
class Date(_Base):
    """A date without a time component.

    >>> d = Date(2021, 1, 2)
    Date("2021-01-02")

    Can also be constructed from an ISO 8601 string
    or a standard library :class:`~datetime.date`
    (a :class:`~datetime.datetime` is read as its date, and warns):

    >>> Date("2021-01-02")
    Date("2021-01-02")
    >>> from datetime import date
    >>> Date(date(2021, 1, 2))
    Date("2021-01-02")

    Dates support arithmetic with :class:`~whenever.ItemizedDateDelta`:

    >>> delta = Date("2021-02-28").since(Date("1994-05-15"), in_units=["years", "days"])
    ItemizedDateDelta("P26y289d")
    >>> Date("1994-05-15").add(delta)
    Date("2021-02-28")

    Dates can be compared and sorted:

    >>> Date(2021, 1, 2) > Date(2021, 1, 1)
    True
    """

    __slots__ = ("_py_date",)

    MIN: ClassVar[Date]
    """The minimum possible value of this type."""
    MAX: ClassVar[Date]
    """The maximum possible value of this type."""

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

    __init__ = add_alternate_constructors(__init__, _date)

    @classmethod
    def today_in_system_tz(cls) -> Date:
        """Get the current date in the system time zone.

        .. deprecated:: 0.11
           Use ``Date.today(SYSTEM_TZ)`` instead.

        Equivalent to ``today(SYSTEM_TZ)``.

        >>> Date.today_in_system_tz()
        Date("2021-01-02")
        """
        warn_deprecated(
            "today_in_system_tz() is deprecated; use today(SYSTEM_TZ) instead",
            stacklevel=2,
        )
        return cls.today(SYSTEM_TZ)

    @classmethod
    def today(cls, tz: str | _SystemTZ, /) -> Date:
        """Get the current date in the given time zone.
        Pass ``SYSTEM_TZ`` for the system time zone.

        Raises
        ------
        ~whenever.TimeZoneNotFoundError
            If the time zone ID is not found in the time zone database.
        """
        return Instant.now().to_tz(tz).date()

    @property
    def year(self) -> int:
        """The year component of the date"""
        return self._py_date.year

    @property
    def month(self) -> int:
        """The month component of the date"""
        return self._py_date.month

    @property
    def day(self) -> int:
        """The day component of the date"""
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
            self._py_date.replace(year=DUMMY_LEAP_YEAR)
        )

    def day_of_week(self) -> Weekday:
        """The day of the week

        >>> Date(2021, 1, 2).day_of_week()
        Weekday.SATURDAY
        >>> Weekday.SATURDAY.value
        6  # the ISO value
        """
        return Weekday(self._py_date.isoweekday())

    def iso_week_date(self) -> IsoWeekDate:
        """The ISO week date for this date

        >>> Date(2024, 12, 30).iso_week_date()
        IsoWeekDate("2025-W01-1")
        """
        y, w, d = self._py_date.isocalendar()
        return IsoWeekDate._from_parts_unchecked(y, w, Weekday(d))

    def day_of_year(self) -> int:
        """Ordinal day in the year (1--366)

        >>> Date(2021, 1, 2).day_of_year()
        2
        >>> Date(2021, 12, 31).day_of_year()
        365
        """
        return self._py_date.timetuple().tm_yday

    def days_in_month(self) -> int:
        """Number of days in the current month (28--31)

        >>> Date(2024, 2, 1).days_in_month()
        29
        >>> Date(2023, 2, 1).days_in_month()
        28
        """
        return days_in_month(self._py_date.year, self._py_date.month)

    def days_in_year(self) -> int:
        """Number of days in the current year (365 or 366)

        >>> Date(2024, 1, 1).days_in_year()
        366
        >>> Date(2023, 1, 1).days_in_year()
        365
        """
        return 366 if is_leap(self._py_date.year) else 365

    def in_leap_year(self) -> bool:
        """Whether this date's year is a leap year

        >>> Date(2024, 1, 1).in_leap_year()
        True
        >>> Date(2023, 1, 1).in_leap_year()
        False
        """
        return is_leap(self._py_date.year)

    def next_day(self) -> Date:
        """The date immediately following

        >>> Date(2021, 1, 2).next_day()
        Date("2021-01-03")
        """
        return self._add_days(1)

    def prev_day(self) -> Date:
        """The date immediately preceding

        >>> Date(2021, 1, 2).prev_day()
        Date("2021-01-01")
        """
        return self._add_days(-1)

    def start_of(
        self, unit: Literal["year", "month", "week_mon", "week_sun"], /
    ) -> Date:
        """The start of the given calendar unit

        >>> Date(2024, 8, 15).start_of("year")
        Date("2024-01-01")
        >>> Date(2024, 8, 15).start_of("month")
        Date("2024-08-01")
        >>> Date(2024, 8, 15).start_of("week_mon")
        Date("2024-08-12")
        """
        if unit == "year":
            return Date._from_py_unchecked(
                self._py_date.replace(month=1, day=1)
            )
        elif unit == "month":
            return Date._from_py_unchecked(self._py_date.replace(day=1))
        elif unit == "week_mon":
            return self._add_days(1 - self._py_date.isoweekday())
        elif unit == "week_sun":
            return self._add_days(-(self._py_date.isoweekday() % 7))
        elif unit == "week":
            raise ValueError(WEEK_UNIT_MSG)
        else:
            raise invalid("unit", unit)

    def end_of(
        self, unit: Literal["year", "month", "week_mon", "week_sun"], /
    ) -> Date:
        """The end of the given calendar unit

        >>> Date(2024, 8, 15).end_of("year")
        Date("2024-12-31")
        >>> Date(2024, 8, 15).end_of("month")
        Date("2024-08-31")
        >>> Date(2024, 8, 15).end_of("week_mon")
        Date("2024-08-18")

        See also :meth:`start_of`
        """
        if unit == "year":
            return Date._from_py_unchecked(
                self._py_date.replace(month=12, day=31)
            )
        elif unit == "month":
            return Date._from_py_unchecked(
                self._py_date.replace(
                    day=days_in_month(self._py_date.year, self._py_date.month)
                )
            )
        elif unit == "week_mon":
            return self._add_days(7 - self._py_date.isoweekday())
        elif unit == "week_sun":
            return self._add_days((6 - self._py_date.isoweekday()) % 7)
        elif unit == "week":
            raise ValueError(WEEK_UNIT_MSG)
        else:
            raise invalid("unit", unit)

    def nth_weekday_of_month(self, n: int, weekday: Weekday, /) -> Date:
        """The n-th occurrence of a weekday in this date's month.

        Negative ``n`` counts from the end.
        ``n=0`` raises :class:`ValueError`, as does an occurrence the month
        does not have, such as a fifth Monday in a month with four.

        >>> Date(2024, 8, 1).nth_weekday_of_month(2, Weekday.FRIDAY)
        Date("2024-08-09")
        >>> Date(2024, 8, 1).nth_weekday_of_month(-1, Weekday.FRIDAY)
        Date("2024-08-30")
        """
        n = _weekday_ordinal(n)
        if not isinstance(weekday, Weekday):
            raise TypeError("weekday must be a Weekday")
        year, month = self._py_date.year, self._py_date.month
        day = _nth_weekday_of_month(year, month, n, weekday)
        return Date._from_py_unchecked(_date(year, month, day))

    def nth_weekday(self, n: int, weekday: Weekday, /) -> Date:
        """The n-th occurrence of a weekday from this date (exclusive).

        Negative ``n`` searches backward.
        ``n=0`` raises :class:`ValueError`, as does a result outside
        ``Date.MIN``..``Date.MAX``.

        >>> Date(2024, 8, 1).nth_weekday(1, Weekday.FRIDAY)
        Date("2024-08-02")
        >>> Date(2024, 8, 1).nth_weekday(-1, Weekday.WEDNESDAY)
        Date("2024-07-31")
        """
        n = _weekday_ordinal(n)
        if not isinstance(weekday, Weekday):
            raise TypeError("weekday must be a Weekday")
        target_dow = weekday.value
        self_dow = self._py_date.isoweekday()

        if n > 0:
            offset = (target_dow - self_dow) % 7
            if offset == 0:
                offset = 7
            delta = offset + (n - 1) * 7
        else:
            offset = (self_dow - target_dow) % 7
            if offset == 0:
                offset = 7
            delta = -(offset + (-n - 1) * 7)

        return self._add_days(delta)

    def at(self, time: Time, /) -> PlainDateTime:
        """Combine a date with a time to create a datetime

        >>> d = Date(2021, 1, 2)
        >>> d.at(Time(12, 30))
        PlainDateTime("2021-01-02 12:30:00")

        You can use methods like :meth:`~PlainDateTime.assume_utc`
        or :meth:`~PlainDateTime.assume_tz` to find the corresponding exact time.
        """
        if not isinstance(time, Time):
            raise TypeError("at() argument must be a Time")
        return PlainDateTime._from_py_unchecked(
            _datetime.combine(self._py_date, time._py), time._nanos
        )

    def to_stdlib(self) -> _date:
        """Convert to a standard library :class:`~datetime.date`"""
        return self._py_date

    def _init_from_py(self, d: _date) -> None:
        # Rebuilding from the fields drops a subclass (and a datetime's time)
        self._py_date = (
            d
            if type(d) is _date
            else _date(*_base_fields(d, _date, ("year", "month", "day")))
        )
        warn_lossy_stdlib_subclass(d, _date)

    def format_iso(self, *, basic: bool = False) -> str:
        """Format as an ISO 8601 string, such as ``2021-01-02``.

        Inverse of :meth:`parse_iso`.

        >>> Date(2021, 1, 2).format_iso()
        '2021-01-02'
        >>> Date(1992, 9, 4).format_iso(basic=True)
        '19920904'

        Parameters
        ----------
        basic
            Whether to use the basic ISO format (without separators) instead of the extended one.
        """
        return _format_date(self._py_date, basic)

    @classmethod
    def parse_iso(cls, s: str, /) -> Date:
        """Parse a date from an ISO 8601 string

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

    _PATTERN_CATS = frozenset({"date"})

    def format(self, pattern: str, /) -> str:
        """Format as a custom pattern string.

        See :ref:`pattern-format` for details.

        >>> Date(2024, 3, 15).format("YYYY/MM/DD")
        '2024/03/15'
        >>> Date(2024, 3, 15).format("DD MMM YYYY")
        '15 Mar 2024'
        """
        return self._format(pattern)

    def _format(self, pattern: str, /) -> str:
        # Shared by format() and __format__(); the stack level counts
        # from warn_pattern() through here to the caller of either.
        elements = compile_pattern(pattern)
        validate_fields(elements, self._PATTERN_CATS, "Date")
        d = self._py_date
        result = format_fields(
            elements,
            year=d.year,
            month=d.month,
            day=d.day,
            weekday=d.weekday(),
        )
        warn_pattern(elements, stacklevel=4)
        return result

    def __format__(self, spec: str, /) -> str:
        return str(self) if not spec else self._format(spec)

    @classmethod
    def parse(cls, s: str, /, *, pattern: str = UNSET, **kwargs: Any) -> Date:
        """Parse a date from a custom pattern string.

        See :ref:`pattern-format` for details.

        >>> Date.parse("2024/03/15", pattern="YYYY/MM/DD")
        Date("2024-03-15")
        >>> Date.parse("15 Mar 2024", pattern="DD MMM YYYY")
        Date("2024-03-15")
        """
        pattern, renamed = _normalize_pattern(pattern, kwargs)
        elements = compile_pattern(pattern)
        validate_fields(elements, cls._PATTERN_CATS, "Date")
        state = parse_fields(elements, s)
        if state.year is None or state.month is None or state.day is None:
            raise ValueError("pattern must include a year, a month, and a day")
        result = cls(state.year, state.month, state.day)
        if (
            state.weekday is not None
            and result._py_date.weekday() != state.weekday
        ):
            raise ValueError("weekday does not match the date")
        warn_pattern(elements, stacklevel=3)
        if renamed:
            _warn_format(stacklevel=2)
        return result

    if not TYPE_CHECKING:  # for a nice autodoc

        @overload
        def replace(
            self, *, year: int = ..., month: int = ..., day: int = ...
        ) -> Date: ...

    def replace(self, **kwargs: Any) -> Date:
        """Create a new instance with the given fields replaced

        A result that is not a valid date raises :class:`ValueError`.

        >>> d = Date(2021, 1, 2)
        >>> d.replace(day=4)
        Date("2021-01-04")
        """
        return Date._from_py_unchecked(replace_fields(self._py_date, **kwargs))

    @overload
    def add(self, delta: ItemizedDateDelta, /) -> Date: ...

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
        """Add components to a date.

        Years and months are applied first, clamped to the last day of the
        resulting month, then weeks and days.
        See :ref:`the docs on arithmetic <arithmetic>` for more information.

        >>> d = Date(2021, 1, 2)
        >>> d.add(years=1, months=2, days=3)
        Date("2022-03-05")
        >>> Date(2020, 2, 29).add(years=1)
        Date("2021-02-28")
        """
        return self._shift(1, *args, **kwargs)

    @overload
    def subtract(self, delta: ItemizedDateDelta, /) -> Date: ...

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
    def _shift(self, sign: int, *args, **kwargs) -> Date:
        return self._shift_kwargs(
            sign,
            **_shift_components(
                "add" if sign == 1 else "subtract",
                args,
                kwargs,
                units=DATE_DELTA_UNITS,
                delta_types=(ItemizedDateDelta,),
                expected="an ItemizedDateDelta",
            ),
        )

    def _shift_kwargs(
        self,
        sign: int,
        years: int = 0,
        months: int = 0,
        weeks: int = 0,
        days: int = 0,
    ) -> Date:
        return _shift_date(self, sign, years, months, weeks, days)

    @overload
    def since(
        self,
        other: Date,
        /,
        *,
        total: DateDeltaUnitStr,
    ) -> float: ...

    @overload
    def since(
        self,
        other: Date,
        /,
        *,
        in_units: Sequence[DateDeltaUnitStr],
        round_mode: RoundModeStr = "trunc",
        round_increment: int = ...,
    ) -> ItemizedDateDelta: ...

    def since(
        self,
        other: Date,
        /,
        *,
        total: DateDeltaUnitStr = UNSET,
        in_units: Sequence[DateDeltaUnitStr] = UNSET,
        round_mode: RoundModeStr = UNSET,
        round_increment: int = UNSET,
    ) -> ItemizedDateDelta | float:
        """Calculate the difference between this date and another date.
        The difference is calculated in terms of the chosen calendar unit
        or units.

        >>> d = Date(2023, 4, 15)
        >>> d.since(Date("2020-01-01"), in_units=["years", "months"])
        ItemizedDateDelta("P3y3m")

        >>> d.since(Date("2020-01-01"), total="weeks")
        171.42857142857142

        Parameters
        ----------
        other
            The date to calculate the difference since.
        total
            If specified, the difference is returned as a float in terms
            of this single unit. Cannot be combined with ``in_units``.

            The fractional part is based on the number of days in the
            surrounding calendar period — not a fixed conversion factor.
            For example, 6 months from January 1 spans 181 days of a
            365-day year, giving approximately 0.496 years, not 0.5.
        in_units
            If specified, the difference is calculated in terms of these units,
            in decreasing order of size. Cannot be combined with ``total``.
        round_mode
            The rounding mode to apply to the smallest specified unit.
            Only valid with ``in_units``.
        round_increment
            The increment to round to for the smallest specified unit.
            Only valid with ``in_units``.

        Returns
        -------
        ItemizedDateDelta | float
            If ``in_units`` is specified, the difference is returned
            as an :class:`ItemizedDateDelta`,
            If ``total`` is specified, as a float number of the specified unit.

        """
        if not isinstance(other, Date):
            raise TypeError("since() argument must be a Date")
        total, units, effective_round_mode, effective_increment = (
            _parse_difference_kwargs(
                total, in_units, round_mode, round_increment, date_only=True
            )
        )
        if total is not None:
            sign: Literal[1, -1] = 1 if self._py_date >= other._py_date else -1
            trunc_amount, trunc_date_interim, expand_date_interim = DIFF_FUNCS[
                total
            ](self._py_date, other._py_date, 1, sign)
            trunc_date = resolve_leap_day(trunc_date_interim)
            expand_date = resolve_leap_day(expand_date_interim)
            denom = float((expand_date - trunc_date).days)
            num = float((self._py_date - trunc_date).days)
            return (trunc_amount + num / denom) * sign

        sign = 1 if self >= other else -1
        results = _date_difference(
            self._py_date,
            other._py_date,
            units,
            effective_round_mode,
            effective_increment,
            sign,
        )
        return ItemizedDateDelta._from_signed(
            sign if any(results.values()) else 0, **results
        )

    @overload
    def until(
        self,
        other: Date,
        /,
        *,
        total: DateDeltaUnitStr,
    ) -> float: ...

    @overload
    def until(
        self,
        other: Date,
        /,
        *,
        in_units: Sequence[DateDeltaUnitStr],
        round_mode: RoundModeStr = "trunc",
        round_increment: int = ...,
    ) -> ItemizedDateDelta: ...

    def until(
        self,
        other: Date,
        /,
        *,
        total: DateDeltaUnitStr = UNSET,
        in_units: Sequence[DateDeltaUnitStr] = UNSET,
        round_mode: RoundModeStr = UNSET,
        round_increment: int = UNSET,
    ) -> ItemizedDateDelta | float:
        """Companion to :meth:`since` that calculates the difference until another date.
        See :meth:`since` for more information.
        """
        if not isinstance(other, Date):
            raise TypeError("until() argument must be a Date")
        return other.since(  # type: ignore[call-overload, no-any-return]
            self,
            total=total,
            in_units=in_units,
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
        try:
            shifted = self._py_date + _timedelta(days)
        except OverflowError:
            raise ValueError(RANGE_MSG) from None
        return Date._from_py_unchecked(shifted)

    def __str__(self) -> str:
        return self.format_iso()

    def __repr__(self) -> str:
        return f'Date("{self}")'

    def __eq__(self, other: object, /) -> bool:
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

    def __lt__(self, other: Date, /) -> bool:
        if not isinstance(other, Date):
            return NotImplemented
        return self._py_date < other._py_date

    def __le__(self, other: Date, /) -> bool:
        if not isinstance(other, Date):
            return NotImplemented
        return self._py_date <= other._py_date

    def __gt__(self, other: Date, /) -> bool:
        if not isinstance(other, Date):
            return NotImplemented
        return self._py_date > other._py_date

    def __ge__(self, other: Date, /) -> bool:
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
    try:
        return Date(*unpack_pickle("<HBB", data))
    except ValueError:
        raise ValueError("invalid pickle data") from None


Date.MIN = Date._from_py_unchecked(_date.min)
Date.MAX = Date._from_py_unchecked(_date.max)


@final
class Time(_Base):
    """Time of day without a date component.

    >>> t = Time(12, 30, 0)
    Time("12:30:00")

    Can also be constructed from an ISO 8601 string:

    >>> Time("12:30:00")
    Time("12:30:00")

    Or a standard library :class:`~datetime.time`:

    >>> from datetime import time
    >>> Time(time(12, 30, 0))
    Time("12:30:00")

    Note
    ----
    A :class:`~datetime.time` with a ``tzinfo`` raises :exc:`ValueError`;
    its ``fold`` is ignored.

    Sub-second precision up to nanoseconds is supported:

    >>> Time(12, 30, 0, nanosecond=1)
    Time("12:30:00.000000001")

    Times can be compared and sorted:

    >>> Time(12, 30) > Time(8, 0)
    True
    """

    __slots__ = ("_py", "_nanos")

    MIN: ClassVar[Time]
    """The minimum possible value of this type."""
    MIDNIGHT: ClassVar[Time]
    """Another name for :attr:`MIN`: the same value, at midnight."""
    NOON: ClassVar[Time]
    """Twelve o'clock."""
    MAX: ClassVar[Time]
    """The maximum possible value of this type."""

    # Overloads for a nice autodoc.
    # Proper typing of the constructors is handled in the type stubs
    if not TYPE_CHECKING:

        @overload
        def __init__(self, iso_string: str, /) -> None: ...

        @overload
        def __init__(self, py_time: _time, /) -> None: ...

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
        self._nanos = check_nanos(nanosecond)

    __init__ = add_alternate_constructors(__init__, _time)

    def _init_from_iso(self, s: str) -> None:
        self._py, self._nanos = time_from_iso(s)

    @property
    def hour(self) -> int:
        """The hour component of the time"""
        return self._py.hour

    @property
    def minute(self) -> int:
        """The minute component of the time"""
        return self._py.minute

    @property
    def second(self) -> int:
        """The second component of the time"""
        return self._py.second

    @property
    def nanosecond(self) -> int:
        """The nanosecond component of the time"""
        return self._nanos

    def on(self, date: Date, /) -> PlainDateTime:
        """Combine a time with a date to create a datetime

        >>> t = Time(12, 30)
        >>> t.on(Date(2021, 1, 2))
        PlainDateTime("2021-01-02 12:30:00")

        Then, use methods like :meth:`~PlainDateTime.assume_utc`
        or :meth:`~PlainDateTime.assume_tz`
        to find the corresponding exact time:

        >>> t.on(Date(2021, 1, 2)).assume_tz("America/New_York")
        ZonedDateTime("2021-01-02 12:30:00-05:00[America/New_York]")
        """
        if not isinstance(date, Date):
            raise TypeError("on() argument must be a Date")
        return PlainDateTime._from_py_unchecked(
            _datetime.combine(date._py_date, self._py),
            self._nanos,
        )

    def to_stdlib(self) -> _time:
        """Convert to a standard library :class:`~datetime.time`

        Note
        ----
        Nanoseconds are floored to microseconds.
        If you need more control over rounding, use :meth:`round` first.
        """
        return self._py.replace(microsecond=self._nanos // 1_000)

    def _init_from_py(self, t: _time, /) -> None:
        hour, minute, second, us, tzinfo = _base_fields(
            t, _time, ("hour", "minute", "second", "microsecond", "tzinfo")
        )
        if tzinfo is not None:
            raise ValueError(f"time must be naive, got tzinfo={tzinfo!r}")
        # Rebuilding from the fields drops a subclass and the fold
        return self._init_from_inner((_time(hour, minute, second), us * 1_000))

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
        """Format as an ISO 8601 string, such as ``23:12:00``.

        Inverse of :meth:`parse_iso`.

        >>> Time(12, 30, 0).format_iso(unit='millisecond')
        '12:30:00.000'
        >>> Time(4, 0, 59, nanosecond=40_000).format_iso(basic=True)
        '040059.00004'

        Parameters
        ----------
        unit
            The smallest unit to include in the output.
            ``"auto"`` is the same as ``"nanosecond"``,
            except that trailing zeroes are omitted from the time part.
            A unit above ``"second"`` drops the smaller fields:
            ``unit="hour"`` writes ``23``.
        basic
            Whether to use the basic ISO format (without separators) instead of the extended one.
        """
        return _format_time(self._py, self._nanos, unit, basic)

    @classmethod
    def parse_iso(cls, s: str, /) -> Time:
        """Create from the ISO 8601 time format

        Inverse of :meth:`format_iso`

        >>> Time.parse_iso("12:30:00")
        Time("12:30:00")
        """
        return cls._from_py_unchecked(*time_from_iso(s))

    _PATTERN_CATS = frozenset({"time"})

    def format(self, pattern: str, /) -> str:
        """Format as a custom pattern string.

        See :ref:`pattern-format` for details.

        >>> Time(14, 30, 5).format("HH:mm:ss")
        '14:30:05'
        >>> Time(14, 30).format("ii:mm aa")
        '02:30 PM'
        """
        return self._format(pattern)

    def _format(self, pattern: str, /) -> str:
        # Shared by format() and __format__(); the stack level counts
        # from warn_pattern() through here to the caller of either.
        elements = compile_pattern(pattern)
        validate_fields(elements, self._PATTERN_CATS, "Time")
        t = self._py
        result = format_fields(
            elements,
            hour=t.hour,
            minute=t.minute,
            second=t.second,
            nanos=self._nanos,
        )
        warn_pattern(elements, stacklevel=4)
        return result

    def __format__(self, spec: str, /) -> str:
        return str(self) if not spec else self._format(spec)

    @classmethod
    def parse(cls, s: str, /, *, pattern: str = UNSET, **kwargs: Any) -> Time:
        """Parse a time from a custom pattern string.

        See :ref:`pattern-format` for details.

        >>> Time.parse("14:30:05", pattern="HH:mm:ss")
        Time("14:30:05")
        >>> Time.parse("02:30 PM", pattern="ii:mm aa")
        Time("14:30:00")
        """
        pattern, renamed = _normalize_pattern(pattern, kwargs)
        elements = compile_pattern(pattern)
        validate_fields(elements, cls._PATTERN_CATS, "Time")
        state = parse_fields(elements, s)
        result = cls(
            hour=state.hour or 0,
            minute=state.minute or 0,
            second=state.second or 0,
            nanosecond=state.nanos,
        )
        warn_pattern(elements, stacklevel=3)
        if renamed:
            _warn_format(stacklevel=2)
        return result

    if not TYPE_CHECKING:  # for a nice autodoc

        @overload
        def replace(
            self,
            *,
            hour: int = ...,
            minute: int = ...,
            second: int = ...,
            nanosecond: int = ...,
        ) -> Time: ...

    def replace(self, **kwargs: Any) -> Time:
        """Create a new instance with the given fields replaced

        A result that is not a valid time raises :class:`ValueError`.

        >>> t = Time(12, 30, 0)
        >>> t.replace(minute=3, nanosecond=4_000)
        Time("12:03:00.000004")
        """
        nanos = _pop_replace_nanos(kwargs, self._nanos)
        return Time._from_py_unchecked(
            replace_fields(self._py, **kwargs), nanos
        )

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
        hours, ns = divmod(ns, 3_600_000_000_000)
        minutes, ns = divmod(ns, 60_000_000_000)
        seconds, ns = divmod(ns, 1_000_000_000)
        return cls._from_py_unchecked(_time(hours, minutes, seconds), ns)

    def round(
        self,
        unit: (
            Literal[
                "hour",
                "minute",
                "second",
                "millisecond",
                "microsecond",
                "nanosecond",
            ]
            | TimeDelta
        ) = "second",
        /,
        *,
        increment: int = UNSET,
        mode: RoundModeStr = "half_even",
    ) -> Time:
        """Round the time to the specified unit and increment,
        or to a multiple of a :class:`TimeDelta`.
        Different rounding modes are available.

        >>> Time(12, 39, 59).round("minute", increment=15)
        Time("12:45:00")
        >>> Time(8, 9, 13).round("second", increment=5, mode="floor")
        Time("08:09:10")
        >>> Time(12, 39, 59).round(TimeDelta(minutes=15))
        Time("12:45:00")

        A :class:`Time` has no date to carry into, so rounding past the end of
        the day wraps around to midnight:

        >>> Time(23, 59, 59).round("minute", mode="ceil")
        Time("00:00:00")
        """
        if unit == "day":
            raise invalid("unit", unit)
        return self._round_unchecked(
            _round_increment_ns(unit, increment, False), mode
        )[0]

    def _round_unchecked(
        self, increment_ns: int, mode: str
    ) -> tuple[Time, int]:  # the time, and whether the result is "next day"

        quotient, remainder_ns = divmod(
            self._to_ns_since_midnight(), increment_ns
        )
        quotient += rounds_up(
            mode, remainder_ns, increment_ns, quotient % 2 == 1, 1
        )
        next_day, ns_since_midnight = divmod(
            quotient * increment_ns, NS_PER_DAY
        )
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

    def __str__(self) -> str:
        return self.format_iso()

    def __repr__(self) -> str:
        return f'Time("{self}")'

    def __eq__(self, other: object, /) -> bool:
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

    def __lt__(self, other: Time, /) -> bool:
        if not isinstance(other, Time):
            return NotImplemented
        return (self._py, self._nanos) < (other._py, other._nanos)

    def __le__(self, other: Time, /) -> bool:
        if not isinstance(other, Time):
            return NotImplemented
        return (self._py, self._nanos) <= (other._py, other._nanos)

    def __gt__(self, other: Time, /) -> bool:
        if not isinstance(other, Time):
            return NotImplemented
        return (self._py, self._nanos) > (other._py, other._nanos)

    def __ge__(self, other: Time, /) -> bool:
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
    *args, nanos = unpack_pickle("<BBBI", data)
    try:
        return Time(*args, nanosecond=nanos)
    except ValueError:
        raise ValueError("invalid pickle data") from None


Time.MIN = Time()
Time.MIDNIGHT = Time()
Time.NOON = Time(12)
Time.MAX = Time(23, 59, 59, nanosecond=_MAX_SUBSEC_NANOS)


def _round_float_nanos(value: float, /) -> int:
    """Round half-even to a whole nanosecond count; ``nan`` and infinity
    are out of range."""
    try:
        return round(value)
    except (ValueError, OverflowError):
        raise ValueError(RANGE_MSG) from None


def _div_round_half_even(n: int, d: int, /) -> int:
    quotient, remainder = divmod(abs(n), abs(d))
    quotient += rounds_up("half_even", remainder, abs(d), quotient % 2 == 1, 1)
    return -quotient if (n < 0) != (d < 0) else quotient


_TIMEDELTA_SHIFT_KWARGS = frozenset(
    (
        "weeks",
        "days",
        "hours",
        "minutes",
        "seconds",
        "milliseconds",
        "microseconds",
        "nanoseconds",
        "days_assumed_24h_ok",
    )
)


def _timedelta_from_shift_kwargs(
    kwargs: Mapping[str, Any], fname: str, /
) -> tuple[TimeDelta, bool]:
    """The TimeDelta of ``add()``/``subtract()`` keywords, and whether days
    or weeks were read as 24-hour units without ``days_assumed_24h_ok``:
    the caller warns from its own frame once the shift has succeeded."""
    check_no_kwargs(
        {k: v for k, v in kwargs.items() if k not in _TIMEDELTA_SHIFT_KWARGS},
        fname,
    )
    return (
        TimeDelta(**{**kwargs, "days_assumed_24h_ok": True}),
        bool(
            (kwargs.get("weeks") or kwargs.get("days"))
            and not kwargs.get("days_assumed_24h_ok")
        ),
    )


_ExactShiftable = TypeVar("_ExactShiftable", "TimeDelta", "Instant")


def _shift_exact(
    self: _ExactShiftable, sign: int, args: Any, kwargs: Any, /
) -> _ExactShiftable:
    """``add()``/``subtract()`` of TimeDelta and Instant: a shift by exact
    units only."""
    fname = "add" if sign == 1 else "subtract"
    delta, days_assumed = _timedelta_from_shift_kwargs(
        _shift_components(
            fname,
            args,
            kwargs,
            units=_TIMEDELTA_SHIFT_KWARGS,
            delta_types=TimeDelta,
            expected="a TimeDelta",
        ),
        fname,
    )
    result = self + (delta if sign == 1 else -delta)
    if days_assumed:
        warn(
            DAYS_NOT_ALWAYS_24H_MSG,
            DaysAssumed24HoursWarning,
            stacklevel=3,
        )
    return result


@final
class TimeDelta(_Base):
    """A delta consisting of a precise time: hours, minutes, (nano)seconds.
    For deltas including months or days, use :class:`~ItemizedDelta`,
    or :class:`~whenever.ItemizedDateDelta` for date-only deltas.

    The inputs are normalized, so 90 minutes becomes 1 hour and 30 minutes,
    for example. Float inputs convert exactly down to the nanosecond, and
    a fraction below one nanosecond is truncated toward zero:
    ``seconds=1.5e-9`` is 1 nanosecond.

    >>> d = TimeDelta(hours=1, minutes=90)
    TimeDelta("PT2h30m")
    >>> d.total("minutes")
    150.0

    Can also be constructed from an ISO 8601 duration string
    or a standard library :class:`~datetime.timedelta`:

    >>> TimeDelta("PT2h30m")
    TimeDelta("PT2h30m")
    >>> from datetime import timedelta
    >>> TimeDelta(timedelta(hours=2, minutes=30))
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
            weeks: float = 0,
            days: float = 0,
            hours: float = 0,
            minutes: float = 0,
            seconds: float = 0,
            milliseconds: float = 0,
            microseconds: float = 0,
            nanoseconds: int = 0,
            days_assumed_24h_ok: bool = UNSET,
        ) -> None: ...

    def __init__(
        self,
        *,
        weeks: float = 0,
        days: float = 0,
        hours: float = 0,
        minutes: float = 0,
        seconds: float = 0,
        milliseconds: float = 0,
        microseconds: float = 0,
        nanoseconds: int = 0,
        days_assumed_24h_ok: bool = UNSET,
    ) -> None:
        ns = self._total_ns = exact_units_to_nanos(
            weeks=weeks,
            days=days,
            hours=hours,
            minutes=minutes,
            seconds=seconds,
            milliseconds=milliseconds,
            microseconds=microseconds,
            nanoseconds=nanoseconds,
        )
        if abs(ns) > _MAX_DELTA_NANOS:
            raise ValueError(RANGE_MSG)
        if (weeks or days) and not days_assumed_24h_ok:
            warn(
                DAYS_NOT_ALWAYS_24H_MSG,
                DaysAssumed24HoursWarning,
                stacklevel=3,  # extra frame from add_alternate_constructors
            )

    __init__ = add_alternate_constructors(__init__, _timedelta)

    ZERO: ClassVar[TimeDelta]
    """A delta of zero"""
    MAX: ClassVar[TimeDelta]
    """The maximum possible value of this type."""
    MIN: ClassVar[TimeDelta]
    """The minimum possible value of this type."""

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
        /,
        *,
        relative_to: ZonedDateTime | PlainDateTime | OffsetDateTime = UNSET,
        days_assumed_24h_ok: bool = UNSET,
        naive_arithmetic_ok: bool = UNSET,
        stale_offset_ok: bool = UNSET,
    ) -> float | int:
        """The total duration in the given unit.

        >>> d = TimeDelta(hours=1, minutes=30)
        >>> d.total('minutes')
        90.0

        Parameters
        ----------
        unit
            The unit to sum into. ``"nanoseconds"`` gives an ``int``, any
            other unit a ``float``.
        relative_to
            The reference the calendar units are resolved against. Required
            for years and months, whose length depends on the date. Without
            it, days and weeks are taken as 24 and 168 hours. A
            :class:`ZonedDateTime` emits no warning. A :class:`PlainDateTime`
            ignores time zone transitions, and emits
            :class:`NaiveArithmeticWarning` for a calendar unit. An
            :class:`OffsetDateTime` holds its offset fixed for the whole
            calculation, and emits :class:`StaleOffsetWarning` for a
            calendar unit. An exact unit doesn't use the reference.
        days_assumed_24h_ok
            Accepts the :class:`~whenever.DaysAssumed24HoursWarning` of a
            day or week total without a reference.
        naive_arithmetic_ok
            Accepts the :class:`NaiveArithmeticWarning` of a
            :class:`PlainDateTime` reference.
        stale_offset_ok
            Accepts the :class:`StaleOffsetWarning` of an
            :class:`OffsetDateTime` reference.
        """
        if unit in ("days", "weeks", "years", "months"):
            if relative_to is not UNSET:
                # A TimeDelta is exact and the unit is a calendar unit, so
                # the conversion always crosses the boundary.
                relative_to, warning = _ideltas._reference_and_warning(
                    relative_to,
                    True,
                    True,
                    naive_arithmetic_ok,
                    stale_offset_ok,
                )
                shifted = relative_to + self
                sign: Literal[1, -1] = 1 if self._total_ns >= 0 else -1

                target_date = _zoned_target_date(shifted, relative_to, sign)
                trunc_amount, trunc_date, expanded_date = DIFF_FUNCS[unit](
                    target_date._py_date,
                    relative_to._py_dt.date(),
                    1,
                    sign,
                )
                trunc_zdt = relative_to._with_date(
                    Date._from_py_unchecked(resolve_leap_day(trunc_date))
                )
                span = (
                    relative_to._with_date(
                        Date._from_py_unchecked(
                            resolve_leap_day(expanded_date)
                        )
                    )
                    - trunc_zdt
                )
                # A skipped day can make the two endpoints coincide. The
                # truncated amount is then the whole total.
                result = (
                    trunc_amount
                    + ((shifted - trunc_zdt) / span if span else 0.0)
                ) * sign
                if warning is not None:
                    warn(warning, stacklevel=2)
                return result
            elif unit in ("days", "weeks"):
                if not days_assumed_24h_ok:
                    warn(
                        DAYS_NOT_ALWAYS_24H_MSG,
                        DaysAssumed24HoursWarning,
                        stacklevel=2,
                    )
            else:
                raise TypeError("relative_to is required for years and months")
        elif relative_to is not UNSET:
            # An exact unit doesn't need the reference, but checks it as
            # in_units() does.
            _ideltas._reference_and_warning(
                relative_to, True, False, naive_arithmetic_ok, stale_offset_ok
            )
        if unit == "nanoseconds":
            return self._total_ns
        try:
            return self._total_ns / NS_PER_UNIT_PLURAL[unit]
        except KeyError:
            raise invalid("unit", unit)

    def _in_hrs_mins_secs_nanos(self) -> tuple[int, int, int, int]:
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
        units: Sequence[DeltaUnitStr],
        /,
        *,
        round_mode: RoundModeStr = "trunc",
        round_increment: int = 1,
        relative_to: ZonedDateTime | PlainDateTime | OffsetDateTime = UNSET,
        days_assumed_24h_ok: bool = UNSET,
        naive_arithmetic_ok: bool = UNSET,
        stale_offset_ok: bool = UNSET,
    ) -> ItemizedDelta:
        """Convert to an :class:`ItemizedDelta` in the given units.

        >>> d = TimeDelta(hours=2, minutes=30, seconds=23, milliseconds=500)
        >>> d.in_units(['minutes', 'seconds'])
        ItemizedDelta("PT150m23s")
        >>> hrs, mins = d.in_units(('hours', 'minutes'), round_mode='ceil').values()
        (2, 31)

        Parameters
        ----------
        units
            The units of the result, largest first.
        round_mode
            The rounding mode for the smallest unit in ``units``, as on
            :meth:`round`.
        round_increment
            The rounding increment for that unit.
        relative_to
            The reference the calendar units are resolved against. Required
            for years and months, whose length depends on the date. Without
            it, days and weeks are taken as 24 and 168 hours. A
            :class:`ZonedDateTime` emits no warning. A :class:`PlainDateTime`
            ignores time zone transitions, and emits
            :class:`NaiveArithmeticWarning` when the units include a
            calendar unit. An :class:`OffsetDateTime` holds its offset fixed
            for the whole calculation, and emits :class:`StaleOffsetWarning`
            when the units include a calendar unit.
        days_assumed_24h_ok
            Accepts the :class:`~whenever.DaysAssumed24HoursWarning` of days
            or weeks without a reference.
        naive_arithmetic_ok
            Accepts the :class:`NaiveArithmeticWarning` of a
            :class:`PlainDateTime` reference.
        stale_offset_ok
            Accepts the :class:`StaleOffsetWarning` of an
            :class:`OffsetDateTime` reference.
        """
        units = normalize_units(units, DELTA_UNITS)
        round_mode, round_increment = resolve_rounding(
            round_mode, round_increment
        )
        has_years_months = "years" in units or "months" in units
        if has_years_months and relative_to is UNSET:
            raise TypeError("relative_to is required for years and months")

        if relative_to is not UNSET:
            # A TimeDelta is exact: the conversion crosses the boundary
            # exactly when the target units include a calendar unit.
            relative_to, warning = _ideltas._reference_and_warning(
                relative_to,
                True,
                has_years_months or "days" in units or "weeks" in units,
                naive_arithmetic_ok,
                stale_offset_ok,
            )
            delta = (relative_to + self).since(
                relative_to,
                in_units=units,
                round_mode=round_mode,
                round_increment=round_increment,
            )
            if warning is not None:
                warn(warning, stacklevel=2)
            return delta

        if ("days" in units or "weeks" in units) and not days_assumed_24h_ok:
            warn(
                DAYS_NOT_ALWAYS_24H_MSG,
                DaysAssumed24HoursWarning,
                stacklevel=2,
            )

        result = self._in_exact_units(
            # NOTE: this case is safe because we cannot reach here if there
            # are years or months, and the other units are all valid
            cast(Sequence[ExactDeltaUnitStr], units),
            round_mode,
            round_increment,
        )
        sign: Sign = 1 if self._total_ns >= 0 else -1
        if not any(result.values()):
            sign = 0  # due to rounding, the result may be zero even if self is not zero
        return ItemizedDelta._from_signed(sign, **result)

    def _in_exact_units(
        self,
        units: Sequence[ExactDeltaUnitStr],
        round_mode: RoundModeStr,
        round_increment: int,
    ) -> dict[ExactDeltaUnitStr, int]:
        """Split into the units, rounding the smallest to the increment.
        Below a larger unit, only the component under that unit is rounded,
        and rounding up carries into it: the smallest component stays a
        multiple of the increment, below the next unit."""
        # trim the last 's' from the smallest unit to get the singular form
        smallest = units[-1][:-1]
        if len(units) == 1:
            remaining_ns = abs(
                self.round(
                    smallest,  # type: ignore[arg-type]
                    increment=round_increment,
                    mode=round_mode,
                    days_assumed_24h_ok=True,
                )._total_ns
            )
        else:
            increment_ns = increment_to_ns_for_delta(smallest, round_increment)
            next_ns = NS_PER_UNIT_PLURAL[units[-2]]
            magnitude = abs(self._total_ns)
            component = magnitude % next_ns
            quotient, remainder = divmod(component, increment_ns)
            remaining_ns = magnitude - remainder
            if rounds_up(
                round_mode,
                remainder,
                increment_ns,
                quotient % 2 == 1,
                1 if self._total_ns >= 0 else -1,
            ):
                remaining_ns += increment_ns
                remaining_ns -= remaining_ns % next_ns % increment_ns
            if remaining_ns > _MAX_DELTA_NANOS:
                raise ValueError(RANGE_MSG)
        values = {}
        for u in units:
            values[u], remaining_ns = divmod(
                remaining_ns, NS_PER_UNIT_PLURAL[u]
            )

        return values

    def to_stdlib(self) -> _timedelta:
        """Convert to a :class:`~datetime.timedelta`

        >>> d = TimeDelta(hours=1, minutes=30)
        >>> d.to_stdlib()
        datetime.timedelta(seconds=5400)

        Note
        ----
        Nanoseconds are floored to microseconds.
        If you need more control over rounding, use :meth:`round` first.
        """
        return _timedelta(microseconds=self._total_ns // 1_000)

    def _init_from_py(self, td: _timedelta, /) -> None:
        days, secs, us = _base_fields(
            td, _timedelta, ("days", "seconds", "microseconds")
        )
        self._total_ns = ns = (
            us * 1_000 + secs * 1_000_000_000 + days * 24 * 3_600_000_000_000
        )
        if abs(ns) > _MAX_DELTA_NANOS:
            raise ValueError(RANGE_MSG)
        warn_lossy_stdlib_subclass(td, _timedelta)

    def format_iso(self) -> str:
        """Format as the *popular interpretation* of the ISO 8601 duration format.
        May not strictly adhere to (all versions of) the standard.
        See :ref:`here <iso8601-durations>` for more information.

        Inverse of :meth:`parse_iso`.

        >>> TimeDelta(hours=1, minutes=30).format_iso()
        'PT1H30M'
        """
        hrs, mins, secs, ns = abs(self)._in_hrs_mins_secs_nanos()
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
        exc = ValueError(f"invalid ISO 8601 string: {s!r}")
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
            raise ValueError(RANGE_MSG)

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
        unit: (
            Literal[
                "week",
                "day",
                "hour",
                "minute",
                "second",
                "millisecond",
                "microsecond",
                "nanosecond",
            ]
            | TimeDelta
        ) = "second",
        /,
        *,
        increment: int = UNSET,
        mode: RoundModeStr = "half_even",
        days_assumed_24h_ok: bool = UNSET,
    ) -> TimeDelta:
        """Round the delta to the specified unit and increment,
        or to a multiple of another :class:`TimeDelta`.
        Different rounding modes are available.

        >>> t = TimeDelta(seconds=12345)
        >>> t.round("minute")
        TimeDelta("PT3h26m")
        >>> t.round("second", increment=10, mode="floor")
        TimeDelta("PT3h25m40s")
        >>> t.round(TimeDelta(minutes=15))
        TimeDelta("PT3h30m")
        >>> TimeDelta(hours=50).round("day", days_assumed_24h_ok=True)
        TimeDelta("PT48h")

        Warning
        -------
        ``"day"`` and ``"week"`` are exact 24-hour and 168-hour units here,
        which emits :class:`~whenever.DaysAssumed24HoursWarning`.
        Pass ``days_assumed_24h_ok=True`` when that is intentional.
        A :class:`TimeDelta` unit claims no calendar and never warns.
        """
        increment_ns = _round_increment_ns(unit, increment, True)
        quotient, remainder_ns = divmod(abs(self._total_ns), increment_ns)
        sign: Literal[1, -1] = 1 if self._total_ns >= 0 else -1

        quotient += rounds_up(
            mode, remainder_ns, increment_ns, quotient % 2 == 1, sign
        )
        abs_result = quotient * increment_ns

        if abs_result > _MAX_DELTA_NANOS:
            raise ValueError(RANGE_MSG)
        # The named unit claims a calendar; a TimeDelta unit does not.
        if unit in ("day", "week") and not days_assumed_24h_ok:
            warn(
                DAYS_NOT_ALWAYS_24H_MSG,
                DaysAssumed24HoursWarning,
                stacklevel=2,
            )
        return self._from_nanos_unchecked(abs_result * sign)

    @overload
    def add(self, delta: TimeDelta, /) -> TimeDelta: ...

    @overload
    def add(
        self,
        /,
        *,
        weeks: float = ...,
        days: float = ...,
        hours: float = ...,
        minutes: float = ...,
        seconds: float = ...,
        milliseconds: float = ...,
        microseconds: float = ...,
        nanoseconds: int = ...,
        days_assumed_24h_ok: bool = ...,
    ) -> TimeDelta: ...

    def add(self, *args: Any, **kwargs: Any) -> TimeDelta:
        """Add time to this delta, returning a new delta.

        Days and weeks are treated as exact 24-hour and 168-hour units,
        which emits a :class:`~whenever.DaysAssumed24HoursWarning` unless
        ``days_assumed_24h_ok=True``.

        >>> TimeDelta(hours=1).add(minutes=30)
        TimeDelta("PT1h30m")
        >>> TimeDelta(hours=1).add(TimeDelta(minutes=30))
        TimeDelta("PT1h30m")
        """
        return _shift_exact(self, 1, args, kwargs)

    @overload
    def subtract(self, delta: TimeDelta, /) -> TimeDelta: ...

    @overload
    def subtract(
        self,
        /,
        *,
        weeks: float = ...,
        days: float = ...,
        hours: float = ...,
        minutes: float = ...,
        seconds: float = ...,
        milliseconds: float = ...,
        microseconds: float = ...,
        nanoseconds: int = ...,
        days_assumed_24h_ok: bool = ...,
    ) -> TimeDelta: ...

    def subtract(self, *args: Any, **kwargs: Any) -> TimeDelta:
        """Subtract time from this delta, returning a new delta.

        Days and weeks are treated as exact 24-hour and 168-hour units,
        which emits a :class:`~whenever.DaysAssumed24HoursWarning` unless
        ``days_assumed_24h_ok=True``.

        >>> TimeDelta(hours=1).subtract(minutes=30)
        TimeDelta("PT30m")
        """
        return _shift_exact(self, -1, args, kwargs)

    @overload
    def __add__(self, other: TimeDelta, /) -> TimeDelta: ...

    @overload
    def __add__(self, other: Instant, /) -> Instant: ...

    @overload
    def __add__(self, other: PlainDateTime, /) -> PlainDateTime: ...

    @overload
    def __add__(self, other: OffsetDateTime, /) -> OffsetDateTime: ...

    @overload
    def __add__(self, other: ZonedDateTime, /) -> ZonedDateTime: ...

    def __add__(
        self,
        other: TimeDelta
        | Instant
        | PlainDateTime
        | OffsetDateTime
        | ZonedDateTime,
        /,
    ) -> TimeDelta | Instant | PlainDateTime | OffsetDateTime | ZonedDateTime:
        """Add two deltas together, or shift a datetime by this delta

        >>> d = TimeDelta(hours=1, minutes=30)
        >>> d + TimeDelta(minutes=30)
        TimeDelta("PT2h")
        >>> d + Instant.from_utc(2022, 10, 24)
        Instant("2022-10-24 01:30:00Z")

        Shifting a :class:`PlainDateTime` emits
        :class:`~whenever.NaiveArithmeticWarning` and an
        :class:`OffsetDateTime` :class:`~whenever.StaleOffsetWarning`, as
        their ``add()`` methods do; use those to pass the escape.
        """
        if isinstance(
            other, (Instant, PlainDateTime, OffsetDateTime, ZonedDateTime)
        ):
            return _ideltas._shift_datetime_operator(other, self, False)
        if isinstance(other, TimeDelta):
            return TimeDelta(nanoseconds=self._total_ns + other._total_ns)
        return NotImplemented

    def __sub__(self, other: TimeDelta, /) -> TimeDelta:
        """Subtract two deltas

        >>> d = TimeDelta(hours=1, minutes=30)
        >>> d - TimeDelta(minutes=30)
        TimeDelta("PT1h")
        """
        if not isinstance(other, TimeDelta):
            return NotImplemented
        return TimeDelta(nanoseconds=self._total_ns - other._total_ns)

    def __eq__(self, other: object, /) -> bool:
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

    def __lt__(self, other: TimeDelta, /) -> bool:
        if not isinstance(other, TimeDelta):
            return NotImplemented
        return self._total_ns < other._total_ns

    def __le__(self, other: TimeDelta, /) -> bool:
        if not isinstance(other, TimeDelta):
            return NotImplemented
        return self._total_ns <= other._total_ns

    def __gt__(self, other: TimeDelta, /) -> bool:
        if not isinstance(other, TimeDelta):
            return NotImplemented
        return self._total_ns > other._total_ns

    def __ge__(self, other: TimeDelta, /) -> bool:
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

    def __mul__(self, other: float, /) -> TimeDelta:
        """Multiply by a number, as ``d * 2`` or ``2 * d``

        The result is rounded half-even to the nearest nanosecond; an
        integer operand is exact, a ``float`` operand carries float
        precision. Float keywords, as in ``TimeDelta(seconds=1.5e-9)``,
        truncate below the nanosecond instead.

        >>> d = TimeDelta(hours=1, minutes=30)
        >>> d * 2.5
        TimeDelta("PT3h45m")
        """
        if isinstance(other, int):
            result = self._total_ns * other
        elif isinstance(other, float):
            result = _round_float_nanos(self._total_ns * other)
        else:
            return NotImplemented
        if abs(result) > _MAX_DELTA_NANOS:
            raise ValueError(RANGE_MSG)
        return TimeDelta._from_nanos_unchecked(result)

    def __rmul__(self, other: float, /) -> TimeDelta:
        return self * other

    def __neg__(self) -> TimeDelta:
        """Negate the value

        >>> d = TimeDelta(hours=1, minutes=30)
        >>> -d
        TimeDelta("-PT1h30m")
        """
        # No range check needed: negating a valid TimeDelta always stays in range
        return TimeDelta._from_nanos_unchecked(-self._total_ns)

    def __pos__(self) -> TimeDelta:
        """Return the value unchanged

        >>> d = TimeDelta(hours=1, minutes=30)
        >>> +d
        TimeDelta("PT1h30m")
        """
        return self

    @overload
    def __truediv__(self, other: float, /) -> TimeDelta: ...

    @overload
    def __truediv__(self, other: TimeDelta, /) -> float: ...

    def __truediv__(self, other: float | TimeDelta, /) -> TimeDelta | float:
        """Divide by a number or another delta

        Dividing by a number rounds half-even to the nearest nanosecond; an
        integer operand is exact, a ``float`` operand carries float
        precision. Dividing by another delta gives a ``float``.

        >>> d = TimeDelta(hours=1, minutes=30)
        >>> d / 2.5
        TimeDelta("PT36m")
        >>> d / TimeDelta(minutes=30)
        3.0
        """
        if isinstance(other, TimeDelta):
            if not other._total_ns:
                raise ZeroDivisionError("division by zero")
            return self._total_ns / other._total_ns
        elif isinstance(other, int):
            if not other:
                raise ZeroDivisionError("division by zero")
            result = _div_round_half_even(self._total_ns, other)
        elif isinstance(other, float):
            if not other:
                raise ZeroDivisionError("division by zero")
            result = _round_float_nanos(self._total_ns / other)
        else:
            return NotImplemented
        if abs(result) > _MAX_DELTA_NANOS:
            raise ValueError(RANGE_MSG)
        return TimeDelta._from_nanos_unchecked(result)

    def __floordiv__(self, other: TimeDelta, /) -> int:
        """Floor division by another delta

        >>> d = TimeDelta(hours=1, minutes=39)
        >>> d // TimeDelta(minutes=15)
        6
        """
        if not isinstance(other, TimeDelta):
            return NotImplemented
        if not other._total_ns:
            raise ZeroDivisionError("division by zero")
        return self._total_ns // other._total_ns

    def __mod__(self, other: TimeDelta, /) -> TimeDelta:
        """Modulo by another delta

        >>> d = TimeDelta(hours=1, minutes=39)
        >>> d % TimeDelta(minutes=15)
        TimeDelta("PT9m")
        """
        if not isinstance(other, TimeDelta):
            return NotImplemented
        if not other._total_ns:
            raise ZeroDivisionError("division by zero")
        return TimeDelta(nanoseconds=self._total_ns % other._total_ns)

    def __abs__(self) -> TimeDelta:
        """The absolute value

        >>> d = TimeDelta(hours=-1, minutes=-30)
        >>> abs(d)
        TimeDelta("PT1h30m")
        """
        return TimeDelta._from_nanos_unchecked(abs(self._total_ns))

    def __str__(self) -> str:
        return self.format_iso()

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

    def _to_round_increment_ns(self, for_delta: bool) -> int:
        if (increment_ns := self._total_ns) <= 0:
            raise ValueError("unit must be a positive TimeDelta")
        if not for_delta and 86_400_000_000_000 % increment_ns:
            raise ValueError("unit must divide a 24-hour day evenly")
        return increment_ns


# A separate unpickling function allows us to make backwards-compatible changes
# to the pickling format in the future
@no_type_check
def _unpkl_tdelta(data: bytes) -> TimeDelta:
    s, ns = unpack_pickle("<qI", data)
    if ns >= 1_000_000_000:
        raise ValueError("invalid pickle data")
    try:
        return TimeDelta(seconds=s, nanoseconds=ns)
    except ValueError:
        raise ValueError("invalid pickle data") from None


TimeDelta.ZERO = TimeDelta()
TimeDelta.MAX = TimeDelta(seconds=_MAX_DELTA_SECONDS)
TimeDelta.MIN = TimeDelta(seconds=-_MAX_DELTA_SECONDS)


# Methods for types converting to/from the standard library and ISO 8601:
#
# - Instant
# - PlainDateTime
# - ZonedDateTime
# - OffsetDateTime
#
# (This base class class itself is not for public use.)
class _BasicConversions(_Base):
    __slots__ = ("_py_dt", "_nanos")
    _py_dt: _datetime
    _nanos: int

    def to_stdlib(self) -> _datetime:
        """Convert to a standard library :class:`~datetime.datetime`

        Note
        ----
        Nanoseconds are floored to microseconds.
        If you need more control over rounding, use :meth:`round` first.
        """
        return self._py_dt.replace(microsecond=self._nanos // 1_000)

    def format_iso(self) -> str:
        raise NotImplementedError  # pragma: no cover

    @classmethod
    def parse_iso(cls: type[_T], s: str, /) -> _T:
        raise NotImplementedError  # pragma: no cover

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

    def _init_from_py(self, d: _datetime) -> None:
        raise NotImplementedError  # pragma: no cover


# Methods for types that know a local date and time-of-day:
# - PlainDateTime
# - ZonedDateTime
# - OffsetDateTime
# (The class itself is not for public use.)
class _LocalTime(_BasicConversions):
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

        >>> d = PlainDateTime("2020-01-02 03:04:05")
        >>> date = d.date()
        >>> date
        Date("2020-01-02")

        To perform the inverse, use :meth:`Date.at` and a method
        like :meth:`~PlainDateTime.assume_utc` or
        :meth:`~PlainDateTime.assume_tz`:

        >>> date.at(d.time()).assume_tz("Europe/London")
        ZonedDateTime("2020-01-02 03:04:05+00:00[Europe/London]")
        """
        return Date._from_py_unchecked(self._py_dt.date())

    def time(self) -> Time:
        """The time-of-day part of the datetime

        >>> d = ZonedDateTime("2021-01-02T03:04:05+01:00[Europe/Paris]")
        >>> time = d.time()
        >>> time
        Time("03:04:05")

        To perform the inverse, use :meth:`Time.on` and a method
        like :meth:`~PlainDateTime.assume_utc` or
        :meth:`~PlainDateTime.assume_tz`:

        >>> time.on(d.date()).assume_tz("Europe/Paris")
        ZonedDateTime("2021-01-02 03:04:05+01:00[Europe/Paris]")
        """
        return Time._from_py_unchecked(self._py_dt.time(), self._nanos)

    def day_of_week(self) -> Weekday:
        """The day of the week

        >>> PlainDateTime(2021, 1, 2, 12).day_of_week()
        Weekday.SATURDAY
        """
        return self.date().day_of_week()

    def day_of_year(self) -> int:
        """Ordinal day in the year (1--366)

        >>> PlainDateTime(2021, 1, 2).day_of_year()
        2
        """
        return self._py_dt.timetuple().tm_yday

    def days_in_month(self) -> int:
        """Number of days in the current month (28--31)

        >>> PlainDateTime(2024, 2, 1).days_in_month()
        29
        """
        return days_in_month(self._py_dt.year, self._py_dt.month)

    def days_in_year(self) -> int:
        """Number of days in the current year (365 or 366)

        >>> PlainDateTime(2024, 1, 1).days_in_year()
        366
        """
        return 366 if is_leap(self._py_dt.year) else 365

    def in_leap_year(self) -> bool:
        """Whether the year of this datetime is a leap year

        >>> PlainDateTime(2024, 1, 1).in_leap_year()
        True
        """
        return is_leap(self._py_dt.year)


# Methods for types that represent a specific moment in time.
# Implemented by:
# - Instant
# - ZonedDateTime
# - OffsetDateTime
# (This base class class itself is not for public use.)
class _ExactTime(_BasicConversions):
    __slots__ = ()
    _py_dt: _datetime
    _nanos: int
    _STRICT_EQ_TYPE_MSG: ClassVar[str]

    def timestamp(self, *, unit: TimestampUnitStr = "second") -> int:
        """The UNIX timestamp in the requested unit. Inverse of :meth:`from_timestamp`.

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

        Values before the epoch are floored at the requested unit. For example,
        ``1969-12-31T23:59:59.999999999Z`` has timestamp ``-1`` in seconds,
        milliseconds, microseconds, and nanoseconds. This differs from applying
        ``int()`` to a negative float, which truncates toward zero.
        """
        return timestamp_from_parts(
            int(self._py_dt.timestamp()),
            self._nanos,
            unit,
        )

    def timestamp_millis(self) -> int:
        """Like :meth:`timestamp`, but with millisecond precision.

        .. deprecated:: 0.11
           Use ``timestamp(unit="millisecond")`` instead.
        """
        warn_deprecated(
            "timestamp_millis() is deprecated; use timestamp(unit='millisecond') instead",
            stacklevel=2,
        )
        return self.timestamp(unit="millisecond")

    def timestamp_nanos(self) -> int:
        """Like :meth:`timestamp`, but with nanosecond precision.

        .. deprecated:: 0.11
           Use ``timestamp(unit="nanosecond")`` instead.
        """
        warn_deprecated(
            "timestamp_nanos() is deprecated; use timestamp(unit='nanosecond') instead",
            stacklevel=2,
        )
        return self.timestamp(unit="nanosecond")

    @overload
    def to_fixed_offset(self, /) -> OffsetDateTime: ...

    @overload
    def to_fixed_offset(self, offset: TimeDelta, /) -> OffsetDateTime: ...

    def to_fixed_offset(self, offset: TimeDelta = UNSET, /) -> OffsetDateTime:
        """Convert to an OffsetDateTime that represents the same moment in time.

        With no offset, the value's own offset is kept; an ``Instant``
        gives ``+00:00``.
        """
        tzinfo = (
            # mypy doesn't know that offset is never None
            _timezone(self._py_dt.utcoffset())  # type: ignore[arg-type]
            if offset is UNSET
            else _load_offset(offset)
        )
        try:
            shifted = self._py_dt.astimezone(tzinfo)
        except OverflowError:
            raise ValueError(RANGE_MSG) from None
        _warn_integer_offset(offset, stacklevel=3)
        return OffsetDateTime._from_py_unchecked(shifted, self._nanos)

    def to_tz(self, tz: str | _SystemTZ, /) -> ZonedDateTime:
        """Convert to a ZonedDateTime that represents the same moment in time.
        Pass ``SYSTEM_TZ`` for the system time zone.

        Raises
        ------
        ~whenever.TimeZoneNotFoundError
            If the time zone ID is not found in the time zone database.
        """
        _tz = _load_tz(tz)
        return ZonedDateTime._from_py_unchecked(
            _tz.convert(self._py_dt), self._nanos, _tz
        )

    def to_system_tz(self) -> ZonedDateTime:
        """Convert to a ZonedDateTime of the system time zone.

        .. deprecated:: 0.11
           Use ``to_tz(SYSTEM_TZ)`` instead.
        """
        warn_deprecated(
            "to_system_tz() is deprecated; use to_tz(SYSTEM_TZ) instead",
            stacklevel=2,
        )
        return self.to_tz(SYSTEM_TZ)

    def strict_eq(self, other: Any, /) -> bool:
        """Compare two values, including what ``==`` ignores.

        ``Instant.__eq__`` ignores nothing but the argument's type, while
        ``OffsetDateTime.__eq__`` also ignores the local datetime and the
        offset. An argument of a different type raises :exc:`TypeError`.
        The example uses ``OffsetDateTime``, where ``==`` ignores the offset.

        >>> a = OffsetDateTime(2020, 8, 15, hour=12, offset=hours(1))
        >>> b = OffsetDateTime(2020, 8, 15, hour=13, offset=hours(2))
        >>> a == b
        True  # equivalent instants
        >>> a.strict_eq(b)
        False  # different local datetime and offset
        >>> a.strict_eq(Instant.now())
        TypeError  # different types

        See :ref:`strict-equality` for the rules on every type.
        """
        if type(self) is not type(other):
            raise TypeError(self._STRICT_EQ_TYPE_MSG)
        return (
            self._py_dt,
            self._py_dt.utcoffset(),
            self._nanos,
        ) == (
            other._py_dt,
            other._py_dt.utcoffset(),
            other._nanos,
        )

    def exact_eq(self, other: Any, /) -> bool:
        """Deprecated alias for :meth:`strict_eq`.

        .. deprecated:: 0.11
           Use :meth:`strict_eq` instead.
        """
        result = self.strict_eq(other)
        warn_deprecated(
            "exact_eq() is deprecated; use strict_eq() instead",
            stacklevel=2,
        )
        return result

    def difference(
        self,
        other: Instant | OffsetDateTime | ZonedDateTime,
        /,
    ) -> TimeDelta:
        """Calculate the exact time difference between two datetimes.

        This method returns the exact elapsed :class:`TimeDelta` between
        two instants in time. Equivalent to the subtraction operator (``-``).

        Use :meth:`~whenever.ZonedDateTime.since` or
        :meth:`~whenever.ZonedDateTime.until` on the local datetimes for
        calendar units, unit decomposition, and rounding.
        """
        if not isinstance(other, _EXACT_TIME_TYPES):
            raise TypeError(
                "difference() argument must be an Instant, OffsetDateTime, "
                "or ZonedDateTime"
            )
        return self._subtract_operator(other)

    # Keep the mixin's name out of CPython's own argument errors, which
    # name the function by its __qualname__.
    difference.__qualname__ = "difference"

    def __eq__(self, other: object, /) -> bool:
        """Check if two datetimes represent at the same moment in time

        ``a == b`` is equivalent to ``a.to_instant() == b.to_instant()``

        Note
        ----
        To also compare what ``==`` ignores, use :meth:`strict_eq`.

        >>> Instant.from_utc(2020, 8, 15, hour=23) == Instant.from_utc(2020, 8, 15, hour=23)
        True
        >>> OffsetDateTime(2020, 8, 15, hour=23, offset=hours(1)) == (
        ...     ZonedDateTime(2020, 8, 15, hour=18, tz="America/New_York")
        ... )
        True
        """
        if not isinstance(other, _EXACT_TIME_TYPES):
            return NotImplemented
        # We can't rely on simple equality, because it isn't equal
        # between two datetimes with different time zones if one of the
        # datetimes needs fold to disambiguate it.
        # See peps.python.org/pep-0495/#aware-datetime-equality-comparison.
        # We want to avoid this legacy edge case, so we normalize to UTC.
        return (self._py_dt.astimezone(_UTC), self._nanos) == (
            other._py_dt.astimezone(_UTC),
            other._nanos,
        )

    def __lt__(self, other: _ExactTimeAlias, /) -> bool:
        """Compare two datetimes by when they occur in time

        ``a < b`` is equivalent to ``a.to_instant() < b.to_instant()``

        >>> OffsetDateTime(2020, 8, 15, hour=23, offset=hours(8)) < (
        ...     ZonedDateTime(2020, 8, 15, hour=20, tz="Europe/Amsterdam")
        ... )
        True
        """
        if not isinstance(other, _EXACT_TIME_TYPES):
            return NotImplemented
        return (self._py_dt.astimezone(_UTC), self._nanos) < (
            other._py_dt.astimezone(_UTC),
            other._nanos,
        )

    def __le__(self, other: _ExactTimeAlias, /) -> bool:
        """Compare two datetimes by when they occur in time

        ``a <= b`` is equivalent to ``a.to_instant() <= b.to_instant()``

        >>> OffsetDateTime(2020, 8, 15, hour=23, offset=hours(8)) <= (
        ...     ZonedDateTime(2020, 8, 15, hour=20, tz="Europe/Amsterdam")
        ... )
        True
        """
        if not isinstance(other, _EXACT_TIME_TYPES):
            return NotImplemented
        return (self._py_dt.astimezone(_UTC), self._nanos) <= (
            other._py_dt.astimezone(_UTC),
            other._nanos,
        )

    def __gt__(self, other: _ExactTimeAlias, /) -> bool:
        """Compare two datetimes by when they occur in time

        ``a > b`` is equivalent to ``a.to_instant() > b.to_instant()``

        >>> OffsetDateTime(2020, 8, 15, hour=19, offset=-hours(8)) > (
        ...     ZonedDateTime(2020, 8, 15, hour=20, tz="Europe/Amsterdam")
        ... )
        True
        """
        if not isinstance(other, _EXACT_TIME_TYPES):
            return NotImplemented
        return (self._py_dt.astimezone(_UTC), self._nanos) > (
            other._py_dt.astimezone(_UTC),
            other._nanos,
        )

    def __ge__(self, other: _ExactTimeAlias, /) -> bool:
        """Compare two datetimes by when they occur in time

        ``a >= b`` is equivalent to ``a.to_instant() >= b.to_instant()``

        >>> OffsetDateTime(2020, 8, 15, hour=19, offset=-hours(8)) >= (
        ...     ZonedDateTime(2020, 8, 15, hour=20, tz="Europe/Amsterdam")
        ... )
        True
        """
        if not isinstance(other, _EXACT_TIME_TYPES):
            return NotImplemented
        return (self._py_dt.astimezone(_UTC), self._nanos) >= (
            other._py_dt.astimezone(_UTC),
            other._nanos,
        )

    def _subtract_operator(self, other: _ExactTimeAlias) -> TimeDelta:
        if isinstance(other, _EXACT_TIME_TYPES):
            py_delta = self._py_dt.astimezone(_UTC) - other._py_dt
            total_ns = (
                (py_delta.days * 86_400 + py_delta.seconds) * 1_000_000_000
                + self._nanos
                - other._nanos
            )
            return TimeDelta._from_nanos_unchecked(total_ns)
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
            self._current_offset_secs() * 1_000_000_000
        )

    def _current_offset_secs(self) -> int:
        return int(
            self._py_dt.utcoffset().total_seconds()  # type: ignore[union-attr]
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
        """Get the underlying date and time without offset or time zone

        As an inverse, :class:`PlainDateTime` has methods
        :meth:`~PlainDateTime.assume_utc`, :meth:`~PlainDateTime.assume_fixed_offset`,
        and :meth:`~PlainDateTime.assume_tz`.
        """
        return PlainDateTime._from_py_unchecked(
            self._py_dt.replace(tzinfo=None),
            self._nanos,
        )


@final
class Instant(_ExactTime):
    """A moment in time, independent of any time zone or calendar.

    This is the right type when you only care about *when* something happened,
    not the local date or time. It maps 1:1 to a UNIX timestamp.

    >>> from whenever import Instant
    >>> py311_release = Instant.from_utc(2022, 10, 24, hour=17)
    Instant("2022-10-24 17:00:00Z")
    >>> py311_release.add(hours=3).timestamp()
    1666641600

    Can also be constructed from an ISO 8601 string
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
    See the :ref:`FAQ <faq-instant-no-local>`.
    """

    __slots__ = ()
    _STRICT_EQ_TYPE_MSG = "strict_eq() argument must be an Instant"

    MIN: ClassVar[Instant]
    """The minimum possible value of this type."""

    MAX: ClassVar[Instant]
    """The maximum possible value of this type."""

    # Overloads for a nice autodoc.
    # Proper typing of the constructors is handled in the type stubs
    if not TYPE_CHECKING:

        @overload
        def __init__(self, iso_string: str, /) -> None: ...

        @overload
        def __init__(self, py_datetime: _datetime, /) -> None: ...

    def __init__(self, arg: str | _datetime, /) -> None:
        if isinstance(arg, str):
            self._init_from_iso(arg)
        elif isinstance(arg, _datetime):
            self._init_from_py(arg)
        else:
            raise TypeError(
                "Instant() requires an ISO 8601 string or datetime.datetime"
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
        """Create an Instant from a date and time-of-day in UTC.
        This is the field constructor of ``Instant``; see the
        :ref:`FAQ <faq-instant-no-local>` for why ``Instant(...)`` takes no fields.

        >>> Instant.from_utc(2022, 10, 24, hour=17)
        Instant("2022-10-24 17:00:00Z")
        """
        try:
            py_dt = _datetime(year, month, day, hour, minute, second, 0, _UTC)
        except OverflowError:  # a field beyond a C int
            raise ValueError(RANGE_MSG) from None
        return cls._from_py_unchecked(py_dt, check_nanos(nanosecond))

    @classmethod
    def now(cls) -> Instant:
        """Create an Instant from the current time.

        >>> Instant.now()
        Instant("2024-06-15 12:34:56.789123456Z")
        """
        secs, nanos = divmod(time_ns(), 1_000_000_000)
        return cls._from_py_unchecked(_from_epoch_utc(secs), nanos)

    @classmethod
    def from_timestamp(
        cls,
        value: int | float,
        /,
        *,
        unit: TimestampUnitStr = "second",
    ) -> Instant:
        """Create an Instant from a UNIX timestamp in the requested unit.

        The inverse of the ``timestamp()`` method.

        Seconds accept integers and floats, which are floored to whole
        nanoseconds; milliseconds, microseconds, and nanoseconds require
        integers. A value outside ``Instant.MIN..MAX`` raises ``ValueError``.
        """
        secs, nanos = split_timestamp(value, unit)
        return cls._from_py_unchecked(_from_epoch_utc(secs), nanos)

    @classmethod
    def from_timestamp_millis(cls, value: int, /) -> Instant:
        """Create an Instant from a UNIX timestamp (in milliseconds).

        .. deprecated:: 0.11
           Use ``from_timestamp(..., unit="millisecond")`` instead.

        The inverse of the ``timestamp_millis()`` method.
        """
        result = cls.from_timestamp(value, unit="millisecond")
        warn_deprecated(
            "from_timestamp_millis() is deprecated; use from_timestamp(..., unit='millisecond') instead",
            stacklevel=2,
        )
        return result

    @classmethod
    def from_timestamp_nanos(cls, value: int, /) -> Instant:
        """Create an Instant from a UNIX timestamp (in nanoseconds).

        .. deprecated:: 0.11
           Use ``from_timestamp(..., unit="nanosecond")`` instead.

        The inverse of the ``timestamp_nanos()`` method.
        """
        result = cls.from_timestamp(value, unit="nanosecond")
        warn_deprecated(
            "from_timestamp_nanos() is deprecated; use from_timestamp(..., unit='nanosecond') instead",
            stacklevel=2,
        )
        return result

    def _init_from_py(self, d: _datetime) -> None:
        py_dt = _strip_subclasses(d)
        if py_dt.utcoffset() is None:
            raise ValueError("datetime is naive; use PlainDateTime() instead")
        as_utc = check_utc_bounds(py_dt).astimezone(_UTC)
        self._py_dt = as_utc.replace(microsecond=0, fold=0)
        self._nanos = as_utc.microsecond * 1_000
        warn_lossy_stdlib_subclass(d, _datetime)

    @classmethod
    def parse_iso(cls, s: str, /) -> Instant:
        """Parse an ISO 8601 string, such as ``2020-08-15T23:12:00Z``.

        The basic and extended formats are accepted, but not week dates or
        ordinal dates. ``Z`` or an offset is required, and a non-zero offset
        is converted to UTC. A bracketed time zone ID is accepted and
        ignored. See :ref:`iso8601` for details.

        Inverse of :meth:`format_iso`.

        >>> Instant.parse_iso("2020-08-15T23:12:00+02:00")
        Instant("2020-08-15 21:12:00Z")
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
        """Format as an ISO 8601 string, such as ``2020-08-15T23:12:00Z``.

        Inverse of :meth:`parse_iso`.

        >>> Instant.from_utc(2020, 8, 15, hour=23, minute=12).format_iso()
        '2020-08-15T23:12:00Z'

        ``unit``, ``basic``, and ``sep`` are as on
        :meth:`ZonedDateTime.format_iso`.
        """
        return _format_dt(self._py_dt, self._nanos, "Z", unit, sep, basic)

    def format_rfc2822(self) -> str:
        """Format as an RFC 2822 string in the fixed UTC/GMT subset.

        RFC 2822 has whole-second precision, so nanoseconds are discarded.

        >>> Instant.from_utc(2020, 8, 8, hour=23, minute=12).format_rfc2822()
        "Sat, 08 Aug 2020 23:12:00 GMT"

        Note
        ----
        This is also the IMF-fixdate representation used to generate HTTP dates
        under the stricter RFC 9110 standard.

        """
        return (
            f"{WEEKDAY_TO_RFC2822[self._py_dt.weekday()]}, "
            f"{self._py_dt.day:02} "
            f"{MONTH_TO_RFC2822[self._py_dt.month]} {self._py_dt.year:04} "
            f"{self._py_dt.time()} GMT"
        )

    @classmethod
    def parse_rfc2822(cls, s: str, /) -> Instant:
        """Parse an RFC 2822 string; the offset is applied and the result is UTC.

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

    _PATTERN_CATS = frozenset({"date", "time", "offset"})

    def format(self, pattern: str, /) -> str:
        """Format as a custom pattern string.

        Instant formats as UTC; See :ref:`pattern-format` for details.

        >>> Instant.from_utc(2024, 3, 15, 14, 30).format("YYYY-MM-DD HH:mm:ssXXX")
        '2024-03-15 14:30:00Z'
        """
        return self._format(pattern)

    def _format(self, pattern: str, /) -> str:
        # Shared by format() and __format__(); the stack level counts
        # from warn_pattern() through here to the caller of either.
        elements = compile_pattern(pattern)
        validate_fields(elements, self._PATTERN_CATS, "Instant")
        d = self._py_dt
        result = format_fields(
            elements,
            year=d.year,
            month=d.month,
            day=d.day,
            weekday=d.weekday(),
            hour=d.hour,
            minute=d.minute,
            second=d.second,
            nanos=self._nanos,
            offset_secs=0,
        )
        warn_pattern(elements, stacklevel=4)
        return result

    def __format__(self, spec: str, /) -> str:
        return str(self) if not spec else self._format(spec)

    @classmethod
    def parse(
        cls, s: str, /, *, pattern: str = UNSET, **kwargs: Any
    ) -> Instant:
        """Parse an instant from a custom pattern string.

        The pattern **must** include an offset specifier (``x``/``X``)
        to unambiguously identify the instant.
        See :ref:`pattern-format` for details.

        .. tip::

            If your input string doesn't include an offset, parse it with
            :meth:`PlainDateTime.parse` first, then convert using
            :meth:`~PlainDateTime.assume_utc` or
            :meth:`~PlainDateTime.assume_tz`.

        >>> Instant.parse("2024-03-15 14:30Z", pattern="YYYY-MM-DD HH:mmXXX")
        Instant("2024-03-15 14:30:00Z")
        >>> Instant.parse("2024-03-15 14:30+05:30", pattern="YYYY-MM-DD HH:mmxxx")
        Instant("2024-03-15 09:00:00Z")
        """
        pattern, renamed = _normalize_pattern(pattern, kwargs)
        elements = compile_pattern(pattern)
        validate_fields(elements, cls._PATTERN_CATS, "Instant")
        state = parse_fields(elements, s)
        if state.offset_secs is None:
            raise ValueError("pattern must include an offset specifier (x/X)")
        if state.year is None or state.month is None or state.day is None:
            raise ValueError("pattern must include a year, a month, and a day")
        local = _datetime(
            state.year,
            state.month,
            state.day,
            state.hour or 0,
            state.minute or 0,
            state.second or 0,
            tzinfo=mk_fixed_tzinfo(state.offset_secs),
        )
        if state.weekday is not None and local.weekday() != state.weekday:
            raise ValueError("weekday does not match the date")
        dt = check_utc_bounds(local).astimezone(_UTC)
        warn_pattern(elements, stacklevel=3)
        if renamed:
            _warn_format(stacklevel=2)
        return cls._from_py_unchecked(dt, state.nanos)

    if not TYPE_CHECKING:  # for a nicer autodoc

        @overload
        def add(self, d: TimeDelta, /) -> Instant: ...

        @overload
        def add(
            self,
            *,
            weeks: float = 0,
            days: float = 0,
            hours: float = 0,
            minutes: float = 0,
            seconds: float = 0,
            milliseconds: float = 0,
            microseconds: float = 0,
            nanoseconds: int = 0,
            days_assumed_24h_ok: bool = UNSET,
        ) -> Instant: ...

    @no_type_check
    def add(self, *args, **kwargs) -> Instant:
        """Add a time amount to this instant.

        See the `docs on arithmetic <https://whenever.rtfd.io/en/latest/guide/arithmetic.html>`__ for more information.

        Warning
        -------
        ``days`` and ``weeks`` are exact 24-hour and 168-hour units here,
        which emits :class:`~whenever.DaysAssumed24HoursWarning`.
        Pass ``days_assumed_24h_ok=True`` when that is intentional.
        """
        return _shift_exact(self, 1, args, kwargs)

    if not TYPE_CHECKING:  # for a nicer autodoc

        @overload
        def subtract(self, d: TimeDelta, /) -> Instant: ...

        @overload
        def subtract(
            self,
            *,
            weeks: float = 0,
            days: float = 0,
            hours: float = 0,
            minutes: float = 0,
            seconds: float = 0,
            milliseconds: float = 0,
            microseconds: float = 0,
            nanoseconds: int = 0,
            days_assumed_24h_ok: bool = UNSET,
        ) -> Instant: ...

    @no_type_check
    def subtract(self, *args, **kwargs) -> Instant:
        """Subtract a time amount from this instant.

        See the `docs on arithmetic <https://whenever.rtfd.io/en/latest/guide/arithmetic.html>`__ for more information.

        Warning
        -------
        ``days`` and ``weeks`` are exact 24-hour and 168-hour units here,
        which emits :class:`~whenever.DaysAssumed24HoursWarning`.
        Pass ``days_assumed_24h_ok=True`` when that is intentional.
        """
        return _shift_exact(self, -1, args, kwargs)

    def round(
        self,
        unit: (
            Literal[
                "hour",
                "minute",
                "second",
                "millisecond",
                "microsecond",
                "nanosecond",
            ]
            | TimeDelta
        ) = "second",
        /,
        *,
        increment: int = UNSET,
        mode: RoundModeStr = "half_even",
    ) -> Instant:
        """Round the instant to the specified unit and increment,
        or to a multiple of a :class:`TimeDelta`.
        Different rounding modes are available.

        >>> Instant.from_utc(2020, 1, 1, 12, 39, 59).round("minute", increment=15)
        Instant("2020-01-01 12:45:00Z")
        >>> Instant.from_utc(2020, 1, 1, 8, 9, 13).round("second", increment=5, mode="floor")
        Instant("2020-01-01 08:09:10Z")
        >>> Instant.from_utc(2020, 1, 1, 12, 39, 59).round(TimeDelta(minutes=15))
        Instant("2020-01-01 12:45:00Z")

        ``"day"`` is rejected: an instant has no calendar, so a day has no
        midnight to start at. ``round("hour", increment=24)`` gives periods
        of exactly 24 hours, counted from midnight UTC like every increment
        on an :class:`Instant`. ``"half_even"`` also breaks a tie toward
        the even multiple counted from that midnight, not from the epoch.
        """
        if unit == "day":
            raise ValueError(CANNOT_ROUND_DAY_MSG)
        rounded = PlainDateTime._from_py_unchecked(
            self._py_dt.replace(tzinfo=None), self._nanos
        )._round_unchecked(_round_increment_ns(unit, increment, False), mode)
        return self._from_py_unchecked(
            rounded._py_dt.replace(tzinfo=_UTC), rounded._nanos
        )

    def __add__(self, delta: TimeDelta, /) -> Instant:
        """Add a time amount to this datetime.

        See the `docs on arithmetic <https://whenever.rtfd.io/en/latest/guide/arithmetic.html>`__ for more information.
        """
        if isinstance(delta, TimeDelta):
            delta_secs, nanos = divmod(
                self._nanos + delta._total_ns,
                1_000_000_000,
            )
            return self._from_py_unchecked(
                _add_seconds(self._py_dt, delta_secs), nanos
            )
        return NotImplemented

    @overload
    def __sub__(self, other: _ExactTimeAlias, /) -> TimeDelta: ...

    @overload
    def __sub__(self, other: TimeDelta, /) -> Instant: ...

    def __sub__(
        self, other: TimeDelta | _ExactTimeAlias, /
    ) -> Instant | TimeDelta:
        """Subtract another exact time or ``TimeDelta``

        See the `docs on arithmetic <https://whenever.rtfd.io/en/latest/guide/arithmetic.html>`__ for more information.

        >>> d = Instant.from_utc(2020, 8, 15, hour=23, minute=12)
        >>> d - hours(24) - seconds(5)
        Instant("2020-08-14 23:11:55Z")
        >>> d - Instant.from_utc(2020, 8, 14)
        TimeDelta("PT47h12m")
        """
        if isinstance(other, _EXACT_TIME_TYPES):
            return self._subtract_operator(other)
        elif isinstance(other, TimeDelta):
            return self + -other
        return NotImplemented

    def __hash__(self) -> int:
        return hash((self._py_dt, self._nanos))

    def __repr__(self) -> str:
        return f'Instant("{str(self).replace("T", " ")}")'

    # a custom pickle implementation with a smaller payload
    def __reduce__(self) -> tuple[object, ...]:
        return (
            _unpkl_inst,
            (pack("<qL", int(self._py_dt.timestamp()), self._nanos),),
        )


# Backwards compatibility for instances pickled before 0.8.0
def _unpkl_utc(data: bytes) -> Instant:
    secs, nanos = unpack_pickle("<qL", data)
    if nanos >= 1_000_000_000:
        raise ValueError("invalid pickle data")
    try:
        return Instant._from_py_unchecked(
            _from_epoch_utc(secs - 62_135_683_200), nanos
        )
    except ValueError:
        raise ValueError("invalid pickle data") from None


# A separate unpickling function allows us to make backwards-compatible changes
# to the pickling format in the future
def _unpkl_inst(data: bytes) -> Instant:
    secs, nanos = unpack_pickle("<qL", data)
    if nanos >= 1_000_000_000:
        raise ValueError("invalid pickle data")
    try:
        return Instant._from_py_unchecked(_from_epoch_utc(secs), nanos)
    except ValueError:
        raise ValueError("invalid pickle data") from None


@final
class OffsetDateTime(_ExactAndLocalTime):
    """A datetime with a fixed UTC offset.

    Useful for representing a moment in time together with the local
    date and time as observed at that offset. The offset is fixed and
    does not account for DST transitions.

    >>> # Midnight in Salt Lake City
    >>> OffsetDateTime(2023, 4, 21, offset=hours(-6))
    OffsetDateTime("2023-04-21 00:00:00-06:00")

    Can also be constructed from an ISO 8601 string
    or a standard library :class:`~datetime.datetime`:

    >>> OffsetDateTime("2023-04-21T00:00:00-06:00")
    OffsetDateTime("2023-04-21 00:00:00-06:00")

    Convert to :class:`~whenever.ZonedDateTime` for DST-aware operations:

    >>> dt = OffsetDateTime(2023, 4, 21, offset=hours(-6))
    >>> dt.assume_tz("US/Mountain")
    ZonedDateTime("2023-04-21 00:00:00-06:00[US/Mountain]")

    Important
    ---------
    See the `OffsetDateTime guidance
    <https://whenever.readthedocs.io/en/latest/guide/choosing-a-type.html#offset-datetime-guidance>`_
    for the information this type preserves and its fixed-offset arithmetic
    footgun.
    """

    __slots__ = ()
    _STRICT_EQ_TYPE_MSG = "strict_eq() argument must be an OffsetDateTime"

    # Overloads are for a nicer autodoc
    # Typing is arranged in the stubs
    if not TYPE_CHECKING:

        @overload
        def __init__(self, iso_string: str, /) -> None: ...

        @overload
        def __init__(self, py_datetime: _datetime, /) -> None: ...

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
            offset: TimeDelta,
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
        offset: TimeDelta,
    ) -> None:
        tzinfo = _load_offset(offset)
        self._py_dt = check_utc_bounds(
            _datetime(year, month, day, hour, minute, second, 0, tzinfo)
        )
        self._nanos = check_nanos(nanosecond)
        _warn_integer_offset(offset, stacklevel=4)

    __init__ = add_alternate_constructors(__init__, _datetime)

    @classmethod
    def now(
        cls,
        offset: TimeDelta,
        /,
        *,
        stale_offset_ok: bool = UNSET,
    ) -> OffsetDateTime:
        """Create an instance from the current time at the given offset.

        >>> OffsetDateTime.now(hours(2), stale_offset_ok=True)
        OffsetDateTime("2024-03-09 23:00:00+02:00")

        Warning
        -------
        A fixed offset may be stale relative to the region you intend. See the
        `OffsetDateTime guidance
        <https://whenever.readthedocs.io/en/latest/guide/choosing-a-type.html#offset-datetime-guidance>`_.
        Pass ``stale_offset_ok=True`` when the fixed offset is intentional.
        """
        tzinfo = _load_offset(offset)
        secs, nanos = divmod(time_ns(), 1_000_000_000)
        offset_secs = int(tzinfo.utcoffset(None).total_seconds())
        result = cls._from_py_unchecked(
            _from_epoch_offset(secs, offset_secs), nanos
        )
        _warn_integer_offset(offset, stacklevel=3)
        if not stale_offset_ok:
            warn(
                OFFSET_NOW_STALE_MSG,
                StaleOffsetWarning,
                stacklevel=2,
            )
        return result

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
        """Format as an ISO 8601 string, such as ``2020-08-15T23:12:00+02:00``.

        Inverse of :meth:`parse_iso`.

        >>> OffsetDateTime(2020, 8, 15, 23, 12, offset=hours(2)).format_iso()
        '2020-08-15T23:12:00+02:00'

        ``unit``, ``basic``, and ``sep`` are as on
        :meth:`ZonedDateTime.format_iso`.
        """
        return _format_dt(
            self._py_dt,
            self._nanos,
            self._current_offset_secs(),
            unit,
            sep,
            basic,
        )

    @classmethod
    def parse_iso(cls, s: str, /) -> OffsetDateTime:
        """Parse an ISO 8601 string with an offset, such as
        ``2020-08-15T23:12:00+02:00``. A bracketed time zone ID is accepted
        and ignored. See :ref:`iso8601` for the accepted variants.

        Inverse of :meth:`format_iso`.

        >>> OffsetDateTime.parse_iso("2020-08-15T23:12:00+02:00")
        OffsetDateTime("2020-08-15 23:12:00+02:00")

        Note
        ----
        ``Z`` is accepted as an offset and treated as ``+00:00``.
        Strictly speaking, ``Z`` means "UTC" (i.e. no fixed offset),
        but in practice it is almost universally used as a synonym for ``+00:00``.
        """
        self = _object_new(cls)
        self._init_from_iso(s)
        return self

    def _init_from_iso(self, s: str) -> None:
        self._py_dt, self._nanos = offset_dt_from_iso(s)

    @classmethod
    def from_timestamp(
        cls,
        value: int | float,
        /,
        *,
        offset: int | TimeDelta,
        stale_offset_ok: bool = UNSET,
    ) -> OffsetDateTime:
        """Create an instance from a UNIX timestamp (in seconds).

        .. deprecated:: 0.11
           Create an :class:`Instant` and call ``to_fixed_offset()`` instead.

        The inverse of the ``timestamp()`` method.

        Warning
        -------
        Converting a UNIX timestamp to ``OffsetDateTime`` with a fixed UTC offset
        is correct for that offset, but the offset may be stale for the region you
        intend at that timestamp: a fixed offset contains no DST or other time zone
        rules. Use ``Instant.from_timestamp(ts).to_tz('<tz>')`` if you know the
        time zone, or ``Instant.from_timestamp()`` for exact time independent of
        any time zone. Pass ``stale_offset_ok=True`` to suppress.
        """
        return cls._from_timestamp_deprecated(
            value,
            "second",
            offset,
            stale_offset_ok,
            "OffsetDateTime.from_timestamp() is deprecated; use Instant.from_timestamp(...).to_fixed_offset(...) instead",
        )

    @classmethod
    def from_timestamp_millis(
        cls,
        value: int,
        /,
        *,
        offset: int | TimeDelta,
        stale_offset_ok: bool = UNSET,
    ) -> OffsetDateTime:
        """Create an instance from a UNIX timestamp (in milliseconds).

        .. deprecated:: 0.11
           Use ``Instant.from_timestamp(..., unit="millisecond").to_fixed_offset()``.

        The inverse of the ``timestamp_millis()`` method.

        See :meth:`from_timestamp` for more information.
        """
        return cls._from_timestamp_deprecated(
            value,
            "millisecond",
            offset,
            stale_offset_ok,
            "OffsetDateTime.from_timestamp_millis() is deprecated; use Instant.from_timestamp(..., unit='millisecond').to_fixed_offset(...) instead",
        )

    @classmethod
    def from_timestamp_nanos(
        cls,
        value: int,
        /,
        *,
        offset: int | TimeDelta,
        stale_offset_ok: bool = UNSET,
    ) -> OffsetDateTime:
        """Create an instance from a UNIX timestamp (in nanoseconds).

        .. deprecated:: 0.11
           Use ``Instant.from_timestamp(..., unit="nanosecond").to_fixed_offset()``.

        The inverse of the ``timestamp_nanos()`` method.

        See :meth:`from_timestamp` for more information.
        """
        return cls._from_timestamp_deprecated(
            value,
            "nanosecond",
            offset,
            stale_offset_ok,
            "OffsetDateTime.from_timestamp_nanos() is deprecated; use Instant.from_timestamp(..., unit='nanosecond').to_fixed_offset(...) instead",
        )

    @classmethod
    def _from_timestamp_deprecated(
        cls,
        value: int | float,
        unit: TimestampUnitStr,
        offset: int | TimeDelta,
        stale_offset_ok: bool,
        deprecation: str,
        /,
    ) -> OffsetDateTime:
        # Validate and compute first: a call that raises emits no warning.
        secs, nanos = split_timestamp(value, unit)
        tzinfo = _load_offset(offset)
        try:
            local = _from_epoch_utc(secs).astimezone(tzinfo)
        except OverflowError:
            raise ValueError(RANGE_MSG) from None
        _warn_integer_offset(offset, stacklevel=4)
        warn_deprecated(deprecation, stacklevel=3)
        if not stale_offset_ok:
            warn(
                OFFSET_FROM_TIMESTAMP_STALE_MSG,
                StaleOffsetWarning,
                stacklevel=3,
            )
        return cls._from_py_unchecked(local, nanos)

    def _init_from_py(self, d: _datetime, **kwargs: Any) -> None:
        check_no_kwargs(kwargs, "OffsetDateTime")
        py_dt = _strip_subclasses(d)
        if (offset := py_dt.utcoffset()) is None:
            raise ValueError("datetime is naive; use PlainDateTime() instead")
        elif offset.microseconds:
            raise ValueError("offset must be a whole number of seconds")
        self._py_dt = check_utc_bounds(
            py_dt.replace(microsecond=0, tzinfo=_timezone(offset), fold=0)
        )
        self._nanos = py_dt.microsecond * 1_000
        warn_lossy_stdlib_subclass(d, _datetime)

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
            offset: TimeDelta = ...,
            stale_offset_ok: bool = ...,
        ) -> OffsetDateTime: ...

    def replace(
        self,
        /,
        *,
        stale_offset_ok: bool = UNSET,
        **kwargs: Any,
    ) -> OffsetDateTime:
        """Create a new instance with the given fields replaced

        A stated ``offset=`` keeps the local fields and moves the instant,
        the reverse of :meth:`to_fixed_offset`, and is silent. Any other
        replacement carries the current offset, which may be stale relative
        to its source time zone, and emits :class:`StaleOffsetWarning`
        unless ``stale_offset_ok=True``. See
        :ref:`offset-datetime-guidance`.

        >>> d = OffsetDateTime(2024, 3, 9, 12, offset=hours(-7))
        >>> d.replace(offset=hours(-6))
        OffsetDateTime("2024-03-09 12:00:00-06:00")
        >>> d.replace(day=10, stale_offset_ok=True)
        OffsetDateTime("2024-03-10 12:00:00-07:00")
        """
        nanos = _pop_replace_nanos(kwargs, self._nanos)
        offset = kwargs.pop("offset", UNSET)
        if offset_stated := offset is not UNSET:
            kwargs["tzinfo"] = _load_offset(offset)
        result = self._from_py_unchecked(
            check_utc_bounds(replace_fields(self._py_dt, **kwargs)), nanos
        )
        _warn_integer_offset(offset, stacklevel=3)
        if not (offset_stated or stale_offset_ok):
            warn(
                OFFSET_REPLACE_STALE_MSG,
                StaleOffsetWarning,
                stacklevel=2,
            )
        return result

    def replace_date(
        self,
        date: Date,
        /,
        *,
        stale_offset_ok: bool = UNSET,
    ) -> OffsetDateTime:
        """Create a new instance with the date replaced

        See :meth:`replace` for more information. The offset is always
        carried, so this warns unless ``stale_offset_ok=True``.

        >>> d = OffsetDateTime(2024, 3, 9, 12, offset=hours(-7))
        >>> d.replace_date(Date(2024, 12, 25), stale_offset_ok=True)
        OffsetDateTime("2024-12-25 12:00:00-07:00")
        """
        if not isinstance(date, Date):
            raise TypeError("replace_date() argument must be a Date")
        result = self._from_py_unchecked(
            check_utc_bounds(
                _datetime.combine(date._py_date, self._py_dt.timetz())
            ),
            self._nanos,
        )
        if not stale_offset_ok:
            warn(
                OFFSET_REPLACE_STALE_MSG,
                StaleOffsetWarning,
                stacklevel=2,
            )
        return result

    def replace_time(
        self,
        time: Time,
        /,
        *,
        stale_offset_ok: bool = UNSET,
    ) -> OffsetDateTime:
        """Create a new instance with the time replaced

        See :meth:`replace` for more information. The offset is always
        carried, so this warns unless ``stale_offset_ok=True``.

        >>> d = OffsetDateTime(2024, 3, 9, 12, offset=hours(-7))
        >>> d.replace_time(Time(8, 30), stale_offset_ok=True)
        OffsetDateTime("2024-03-09 08:30:00-07:00")
        """
        if not isinstance(time, Time):
            raise TypeError("replace_time() argument must be a Time")
        result = self._from_py_unchecked(
            check_utc_bounds(
                _datetime.combine(
                    self._py_dt.date(), time._py, self._py_dt.tzinfo
                )
            ),
            time._nanos,
        )
        if not stale_offset_ok:
            warn(
                OFFSET_REPLACE_STALE_MSG,
                StaleOffsetWarning,
                stacklevel=2,
            )
        return result

    def start_of(
        self,
        unit: Literal[
            "year",
            "month",
            "week_mon",
            "week_sun",
            "day",
            "hour",
            "minute",
            "second",
        ],
        /,
        *,
        stale_offset_ok: bool = UNSET,
    ) -> OffsetDateTime:
        """The start of the given unit

        >>> OffsetDateTime(2024, 8, 15, 14, 30, offset=hours(5)).start_of("day")
        OffsetDateTime("2024-08-15 00:00:00+05:00")

        Warning
        -------
        The preserved offset may be stale relative to its source time zone. See
        the `OffsetDateTime guidance
        <https://whenever.readthedocs.io/en/latest/guide/choosing-a-type.html#offset-datetime-guidance>`_.
        Pass ``stale_offset_ok=True`` when preserving it is intentional.
        """
        new_dt = check_utc_bounds(_start_of_dt(self._py_dt, unit))
        if not stale_offset_ok:
            warn(
                OFFSET_START_END_OF_STALE_MSG,
                StaleOffsetWarning,
                stacklevel=2,
            )
        return self._from_py_unchecked(new_dt, 0)

    def end_of(
        self,
        unit: Literal[
            "year",
            "month",
            "week_mon",
            "week_sun",
            "day",
            "hour",
            "minute",
            "second",
        ],
        /,
        *,
        stale_offset_ok: bool = UNSET,
    ) -> OffsetDateTime:
        """The end of the given unit

        >>> OffsetDateTime(2024, 8, 15, 14, 30, offset=hours(5)).end_of("day")
        OffsetDateTime("2024-08-15 23:59:59.999999999+05:00")

        See also :meth:`start_of`

        Warning
        -------
        The preserved offset may be stale relative to its source time zone. See
        the `OffsetDateTime guidance
        <https://whenever.readthedocs.io/en/latest/guide/choosing-a-type.html#offset-datetime-guidance>`_.
        Pass ``stale_offset_ok=True`` when preserving it is intentional.
        """
        new_dt = check_utc_bounds(_end_of_dt(self._py_dt, unit))
        if not stale_offset_ok:
            warn(
                OFFSET_START_END_OF_STALE_MSG,
                StaleOffsetWarning,
                stacklevel=2,
            )
        return self._from_py_unchecked(new_dt, _MAX_SUBSEC_NANOS)

    def __hash__(self) -> int:
        return hash((self._py_dt, self._nanos))

    def __add__(self, delta: TimeDelta, /) -> OffsetDateTime:
        """Add a time delta to this datetime.

        Warning
        -------
        See the `OffsetDateTime guidance
        <https://whenever.readthedocs.io/en/latest/guide/choosing-a-type.html#offset-datetime-guidance>`_
        for why the preserved offset may be stale relative to its source
        time zone.
        """
        if isinstance(delta, TimeDelta):
            delta_secs, nanos = divmod(
                delta._total_ns + self._nanos, 1_000_000_000
            )
            result = self._from_py_unchecked(
                check_utc_bounds(_add_seconds(self._py_dt, delta_secs)),
                nanos,
            )
            warn(
                OFFSET_SHIFT_STALE_MSG,
                StaleOffsetWarning,
                stacklevel=2,
            )
            return result
        return NotImplemented

    @overload
    def __sub__(self, other: _ExactTimeAlias, /) -> TimeDelta: ...

    @overload
    def __sub__(self, other: TimeDelta, /) -> OffsetDateTime: ...

    def __sub__(
        self,
        other: _ExactTimeAlias | TimeDelta,
        /,
    ) -> TimeDelta | OffsetDateTime:
        """Subtract a time delta or calculate the duration to another exact time.

        Warning
        -------
        Subtracting a ``TimeDelta`` preserves the offset. See the
        `OffsetDateTime guidance
        <https://whenever.readthedocs.io/en/latest/guide/choosing-a-type.html#offset-datetime-guidance>`_
        for why that offset may be stale relative to its source time zone.
        Measuring the difference to another exact time is silent.
        """
        if isinstance(other, TimeDelta):
            delta_secs, nanos = divmod(
                -other._total_ns + self._nanos, 1_000_000_000
            )
            result = self._from_py_unchecked(
                check_utc_bounds(_add_seconds(self._py_dt, delta_secs)),
                nanos,
            )
            warn(
                OFFSET_SHIFT_STALE_MSG,
                StaleOffsetWarning,
                stacklevel=2,
            )
            return result
        return super()._subtract_operator(other)

    def format_rfc2822(self) -> str:
        """Format as an RFC 2822 string.

        RFC 2822 has whole-second datetimes and minute-precision offsets.
        Nanoseconds and offset seconds are discarded.

        >>> OffsetDateTime(2020, 8, 15, 23, 12, offset=hours(2)).format_rfc2822()
        "Sat, 15 Aug 2020 23:12:00 +0200"
        """
        offset = self._current_offset_secs()
        # -0000 means the offset is unknown; a known one under a minute
        # truncates to +0000.
        offset_sign = "-" if offset <= -60 else "+"
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

    _PATTERN_CATS = frozenset({"date", "time", "offset"})

    def format(self, pattern: str, /) -> str:
        """Format as a custom pattern string.

        See :ref:`pattern-format` for details.

        >>> OffsetDateTime(2024, 3, 15, 14, 30, offset=hours(2)).format(
        ...     "YYYY-MM-DD HH:mmxxx"
        ... )
        '2024-03-15 14:30+02:00'
        """
        return self._format(pattern)

    def _format(self, pattern: str, /) -> str:
        # Shared by format() and __format__(); the stack level counts
        # from warn_pattern() through here to the caller of either.
        elements = compile_pattern(pattern)
        validate_fields(elements, self._PATTERN_CATS, "OffsetDateTime")
        d = self._py_dt
        result = format_fields(
            elements,
            year=d.year,
            month=d.month,
            day=d.day,
            weekday=d.weekday(),
            hour=d.hour,
            minute=d.minute,
            second=d.second,
            nanos=self._nanos,
            offset_secs=self._current_offset_secs(),
        )
        warn_pattern(elements, stacklevel=4)
        return result

    def __format__(self, spec: str, /) -> str:
        return str(self) if not spec else self._format(spec)

    @classmethod
    def parse(
        cls, s: str, /, *, pattern: str = UNSET, **kwargs: Any
    ) -> OffsetDateTime:
        """Parse an offset datetime from a custom pattern string.

        The pattern **must** include an offset specifier (``x``/``X``).
        See :ref:`pattern-format` for details.

        .. tip::

            If your input string doesn't include an offset, parse it with
            :meth:`PlainDateTime.parse` first, then convert using
            :meth:`~PlainDateTime.assume_fixed_offset` or
            :meth:`~PlainDateTime.assume_tz`.

        >>> OffsetDateTime.parse("2024-03-15 14:30+02:00", pattern="YYYY-MM-DD HH:mmxxx")
        OffsetDateTime("2024-03-15 14:30:00+02:00")
        """
        pattern, renamed = _normalize_pattern(pattern, kwargs)
        elements = compile_pattern(pattern)
        validate_fields(elements, cls._PATTERN_CATS, "OffsetDateTime")
        state = parse_fields(elements, s)
        if state.offset_secs is None:
            raise ValueError("pattern must include an offset specifier (x/X)")
        if state.year is None or state.month is None or state.day is None:
            raise ValueError("pattern must include a year, a month, and a day")
        result = cls(
            state.year,
            state.month,
            state.day,
            state.hour or 0,
            state.minute or 0,
            state.second or 0,
            nanosecond=state.nanos,
            offset=TimeDelta(seconds=state.offset_secs),
        )
        if (
            state.weekday is not None
            and result._py_dt.weekday() != state.weekday
        ):
            raise ValueError("weekday does not match the date")
        warn_pattern(elements, stacklevel=3)
        if renamed:
            _warn_format(stacklevel=2)
        return result

    if not TYPE_CHECKING:  # for a nicer autodoc

        @overload
        def add(
            self,
            delta: AnyDelta,
            /,
            *,
            stale_offset_ok: bool = ...,
        ) -> OffsetDateTime: ...

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
            stale_offset_ok: bool = ...,
        ) -> OffsetDateTime: ...

    @no_type_check
    def add(self, *args, **kwargs) -> OffsetDateTime:
        """Add a time amount to this datetime.

        Years and months are applied first (clamped), then weeks and days,
        all in local time; then the exact units move the instant.
        ``subtract()`` is ``add()`` of the negated components.

        Warning
        -------
        See the `OffsetDateTime guidance
        <https://whenever.readthedocs.io/en/latest/guide/choosing-a-type.html#offset-datetime-guidance>`_
        for the fixed-offset arithmetic footgun. Pass
        ``stale_offset_ok=True`` when preserving the offset is intentional.
        """
        return self._shift(1, *args, **kwargs)

    if not TYPE_CHECKING:  # for a nicer autodoc

        @overload
        def subtract(
            self,
            delta: AnyDelta,
            /,
            *,
            stale_offset_ok: bool = ...,
        ) -> OffsetDateTime: ...

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
            stale_offset_ok: bool = ...,
        ) -> OffsetDateTime: ...

    @no_type_check
    def subtract(self, *args, **kwargs) -> OffsetDateTime:
        """Subtract a time amount from this datetime.

        See :meth:`add` for more information.
        """
        return self._shift(-1, *args, **kwargs)

    @no_type_check
    def _shift(
        self, sign: int, *args, stale_offset_ok: bool = UNSET, **kwargs
    ) -> OffsetDateTime:
        return self._shift_kwargs(
            sign,
            stale_offset_ok=stale_offset_ok,
            **_shift_components(
                "add" if sign == 1 else "subtract",
                args,
                kwargs,
                units=TOTAL_UNITS,
                delta_types=AnyDelta,
                expected=_ANY_DELTA_EXPECTED,
            ),
        )

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
        stale_offset_ok: bool = UNSET,
    ) -> OffsetDateTime:
        new_date = _shift_date(self.date(), sign, years, months, weeks, days)
        delta_ns = _time_units_to_nanos(
            sign,
            hours,
            minutes,
            seconds,
            milliseconds,
            microseconds,
            nanoseconds,
        )
        if not stale_offset_ok:
            warn(
                OFFSET_SHIFT_STALE_MSG,
                StaleOffsetWarning,
                stacklevel=4,
            )
        py_dt_with_new_date = _datetime.combine(
            new_date._py_date, self._py_dt.timetz()
        )
        delta_secs, nanos = divmod(delta_ns + self._nanos, 1_000_000_000)
        return self._from_py_unchecked(
            check_utc_bounds(_add_seconds(py_dt_with_new_date, delta_secs)),
            nanos,
        )

    def round(
        self,
        unit: (
            Literal[
                "day",
                "hour",
                "minute",
                "second",
                "millisecond",
                "microsecond",
                "nanosecond",
            ]
            | TimeDelta
        ) = "second",
        /,
        *,
        increment: int = UNSET,
        mode: RoundModeStr = "half_even",
        stale_offset_ok: bool = UNSET,
    ) -> OffsetDateTime:
        """Round the datetime to the specified unit and increment,
        or to a multiple of a :class:`TimeDelta`.
        Different rounding modes are available.

        >>> d = OffsetDateTime(2020, 8, 15, 23, 24, 18, offset=hours(4))
        >>> d.round("day")
        OffsetDateTime("2020-08-16 00:00:00+04:00")
        >>> d.round("minute", increment=15, mode="floor")
        OffsetDateTime("2020-08-15 23:15:00+04:00")
        >>> d.round(TimeDelta(minutes=15))
        OffsetDateTime("2020-08-15 23:30:00+04:00")

        Warning
        -------
        The preserved offset may be stale relative to its source time zone. See
        the `OffsetDateTime guidance
        <https://whenever.readthedocs.io/en/latest/guide/choosing-a-type.html#offset-datetime-guidance>`_.
        Pass ``stale_offset_ok=True`` when preserving it is intentional.
        """
        result = (
            self.to_plain()
            ._round_unchecked(
                _round_increment_ns(unit, increment, False), mode
            )
            .assume_fixed_offset(self.offset)
        )
        if not stale_offset_ok:
            warn(
                OFFSET_ROUND_STALE_MSG,
                StaleOffsetWarning,
                stacklevel=2,
            )
        return result

    def assume_tz(
        self,
        tz: str | _SystemTZ,
        /,
        *,
        offset_mismatch: OffsetMismatchStr = "raise",
        disambiguation: DisambiguationStr = UNSET,
    ) -> ZonedDateTime:
        """Associate this offset datetime with a time zone, returning a ZonedDateTime.
        Pass ``SYSTEM_TZ`` for the system time zone.

        This is the inverse of :meth:`ZonedDateTime.to_fixed_offset`.

        See the :ref:`time zone resolution guide <offset-mismatch>`
        for how ``offset_mismatch`` interacts with ``disambiguation``.

        Raises
        ------
        ~whenever.TimeZoneNotFoundError
            If the time zone ID is not found in the time zone database.
        ~whenever.InvalidOffsetError
            If the offset matches no offset the time zone applies to the
            local time, under ``offset_mismatch="raise"``.
        """
        if offset_mismatch not in ("raise", "keep_instant", "keep_local"):
            raise invalid("offset_mismatch", offset_mismatch)
        if disambiguation is not UNSET:
            check_disambiguation(disambiguation)
        _tz = _load_tz(tz)
        # Compare offsets before converting: the instant may have no local
        # time in the time zone while the local time is valid there.
        offset = self._current_offset_secs()
        if _tz.offset_for_instant(int(self._py_dt.timestamp())) == offset:
            return ZonedDateTime._from_py_unchecked(
                self._py_dt, self._nanos, _tz
            )
        elif offset_mismatch == "keep_instant":
            return ZonedDateTime._from_py_unchecked(
                _tz.convert(self._py_dt), self._nanos, _tz
            )
        elif offset_mismatch == "raise":
            raise InvalidOffsetError._for_tz(offset, _tz.key)
        else:  # offset_mismatch == "keep_local":
            result, implicit = self.to_plain()._assume_tz(tz, disambiguation)
            if implicit:
                _warn_implicit_disambiguation(stacklevel=2)
            return result

    @overload
    def since(
        self,
        other: OffsetDateTime,
        /,
        *,
        total: DeltaTotalUnitStr,
        stale_offset_ok: bool = ...,
    ) -> float: ...

    @overload
    def since(
        self,
        other: OffsetDateTime,
        /,
        *,
        in_units: Sequence[DeltaUnitStr],
        round_mode: RoundModeStr = ...,
        round_increment: int = ...,
        stale_offset_ok: bool = ...,
    ) -> ItemizedDelta: ...

    def since(
        self,
        other: OffsetDateTime,
        /,
        *,
        total: DeltaTotalUnitStr = UNSET,
        in_units: Sequence[DeltaUnitStr] = UNSET,
        round_mode: RoundModeStr = UNSET,
        round_increment: int = UNSET,
        stale_offset_ok: bool = UNSET,
    ) -> ItemizedDelta | float:
        """Calculate the duration since another OffsetDateTime,
        in terms of the specified units.

        >>> d1 = OffsetDateTime(2020, 8, 15, 23, 12, offset=hours(2))
        >>> d2 = OffsetDateTime(2020, 8, 14, 22, offset=hours(2))
        >>> d1.since(d2, in_units=["hours", "minutes"],
        ...          round_increment=15,
        ...          round_mode="ceil")
        ItemizedDelta("PT25h15m")

        When calculating calendar units (years, months, weeks, days),
        both datetimes must have the same offset.

        Warning
        -------
        Whole calendar units are exact, but a remainder in exact units
        after them (``in_units`` mixing the two kinds, or ``total=`` of a
        calendar unit) is computed with the offset held fixed, which emits
        :class:`~whenever.StaleOffsetWarning`. Pass ``stale_offset_ok=True``
        when the fixed offset is intentional.
        """
        return _offset_since(
            self,
            other,
            flip=False,
            total=total,
            in_units=in_units,
            round_mode=round_mode,
            round_increment=round_increment,
            stale_offset_ok=stale_offset_ok,
        )

    @overload
    def until(
        self,
        other: OffsetDateTime,
        /,
        *,
        total: DeltaTotalUnitStr,
        stale_offset_ok: bool = ...,
    ) -> float: ...

    @overload
    def until(
        self,
        other: OffsetDateTime,
        /,
        *,
        in_units: Sequence[DeltaUnitStr],
        round_mode: RoundModeStr = ...,
        round_increment: int = ...,
        stale_offset_ok: bool = ...,
    ) -> ItemizedDelta: ...

    def until(
        self,
        other: OffsetDateTime,
        /,
        *,
        total: DeltaTotalUnitStr = UNSET,
        in_units: Sequence[DeltaUnitStr] = UNSET,
        round_mode: RoundModeStr = UNSET,
        round_increment: int = UNSET,
        stale_offset_ok: bool = UNSET,
    ) -> ItemizedDelta | float:
        """Inverse of the ``since()`` method. See :meth:`since` for more information."""
        return _offset_since(
            self,
            other,
            flip=True,
            total=total,
            in_units=in_units,
            round_mode=round_mode,
            round_increment=round_increment,
            stale_offset_ok=stale_offset_ok,
        )

    def __repr__(self) -> str:
        return f'OffsetDateTime("{str(self).replace("T", " ")}")'

    # a custom pickle implementation with a smaller payload
    def __reduce__(self) -> tuple[object, ...]:
        return (
            _unpkl_offset,
            (
                pack(
                    "<HBBBBBil",
                    *self._py_dt.timetuple()[:6],
                    self._nanos,
                    self._current_offset_secs(),
                ),
            ),
        )


# A separate function is needed for unpickling, because the
# constructor doesn't accept positional offset argument as
# required by __reduce__.
# Also, it allows backwards-compatible changes to the pickling format.
def _unpkl_offset(data: bytes) -> OffsetDateTime:
    *args, nanos, offset_secs = unpack_pickle("<HBBBBBil", data)
    try:
        return OffsetDateTime(
            *args,
            nanosecond=nanos,
            offset=TimeDelta(seconds=offset_secs),
        )
    except ValueError:
        raise ValueError("invalid pickle data") from None


@final
class ZonedDateTime(_ExactAndLocalTime):
    """A datetime associated with a time zone from the IANA database.

    This is the right type when you need both the exact moment *and*
    the local date/time at a specific location. Arithmetic is fully
    DST-aware: the offset is always kept in sync with the time zone rules.
    ``tz=`` takes a time zone ID; pass ``SYSTEM_TZ`` for the system time
    zone. A string that names no time zone raises
    :exc:`~whenever.TimeZoneNotFoundError`, also inside an ISO string.

    >>> ZonedDateTime("2024-12-08T11[Europe/Paris]")
    ZonedDateTime("2024-12-08 11:00:00+01:00[Europe/Paris]")
    >>> # Explicitly resolve ambiguities during DST transitions
    >>> ZonedDateTime(2023, 10, 29, 1, 15, tz="Europe/London", disambiguation="earlier")
    ZonedDateTime("2023-10-29 01:15:00+01:00[Europe/London]")
    >>> # From a standard library datetime whose tzinfo is a ZoneInfo
    >>> # (or a subclass of it); any other tzinfo raises ValueError
    >>> ZonedDateTime(datetime(2020, 8, 15, 23, 12, tzinfo=ZoneInfo("Europe/London")))
    ZonedDateTime("2020-08-15 23:12:00+01:00[Europe/London]")

    Convert to other types to discard time zone information:

    >>> d = ZonedDateTime(2024, 7, 1, 12, tz="Europe/Amsterdam")
    >>> d.to_instant()
    Instant("2024-07-01 10:00:00Z")
    >>> d.to_plain()
    PlainDateTime("2024-07-01 12:00:00")

    Important
    ---------
    To use this type properly, read more about
    `resolving local times in time zones
    <https://whenever.readthedocs.io/en/latest/guide/resolving-local-times.html>`_.
    For ISO inputs containing both an offset and time zone ID, see the
    `offset-mismatch flow
    <https://whenever.readthedocs.io/en/latest/guide/resolving-local-times.html#offset-mismatch>`_.
    """

    __slots__ = ("_tz",)

    # Overloads are for a nicer autodoc
    # Typing is arranged in the stubs
    if not TYPE_CHECKING:

        @overload
        def __init__(
            self,
            iso_string: str,
            /,
            *,
            disambiguation: DisambiguationStr = ...,
            offset_mismatch: OffsetMismatchStr = "raise",
        ) -> None: ...

        @overload
        def __init__(
            self,
            py_datetime: _datetime,
            /,
            *,
            disambiguation: DisambiguationStr = ...,
            offset_mismatch: OffsetMismatchStr = "raise",
        ) -> None: ...

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
            tz: str | _SystemTZ,
            disambiguation: DisambiguationStr = ...,
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
        tz: str | _SystemTZ,
        disambiguation: DisambiguationStr = UNSET,
        **kwargs: Any,
    ) -> None:
        disambiguation, renamed = _normalize_disambiguation(
            disambiguation,
            kwargs,
            function_name="ZonedDateTime",
        )
        check_no_kwargs(kwargs, "ZonedDateTime")
        self._nanos = check_nanos(nanosecond)
        self._py_dt, implicit = _resolve_disambiguation(
            _datetime(year, month, day, hour, minute, second),
            (_tz := _load_tz(tz)),
            disambiguation,
            self._nanos,
            preferred_offset=None,
        )
        self._tz = _tz
        # One frame further: the alternate-constructor wrapper of __init__
        if implicit:
            _warn_implicit_disambiguation(stacklevel=3)
        if renamed:
            _warn_disambiguate(stacklevel=3)

    __init__ = add_alternate_constructors(__init__, _datetime)

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
        disambiguation: DisambiguationStr = UNSET,
        **kwargs: Any,
    ) -> ZonedDateTime:
        """Create an instance in the system time zone.

        .. deprecated:: 0.11
           Use ``ZonedDateTime(..., tz=SYSTEM_TZ)`` instead.

        Equivalent to ``ZonedDateTime(..., tz=SYSTEM_TZ)``.

        >>> ZonedDateTime.from_system_tz(2020, 8, 15, hour=23, minute=12)
        ZonedDateTime("2020-08-15 23:12:00+02:00[Europe/Berlin]")
        """
        disambiguation, renamed = _normalize_disambiguation(
            disambiguation,
            kwargs,
            function_name="from_system_tz",
        )
        check_no_kwargs(kwargs, "from_system_tz")
        if disambiguation is UNSET:
            disambiguation = "compatible"
        # Validate and compute first: a call that raises emits no warning.
        result = cls(
            year,
            month,
            day,
            hour,
            minute,
            second,
            nanosecond=nanosecond,
            tz=SYSTEM_TZ,
            disambiguation=disambiguation,
        )
        warn_deprecated(
            "from_system_tz() is deprecated; use ZonedDateTime(..., tz=SYSTEM_TZ) instead",
            stacklevel=2,
        )
        if renamed:
            _warn_disambiguate(stacklevel=2)
        return result

    @classmethod
    def now(cls, tz: str | _SystemTZ, /) -> ZonedDateTime:
        """Create an instance from the current time in the given time zone.
        Pass ``SYSTEM_TZ`` for the system time zone.

        >>> ZonedDateTime.now("Europe/Amsterdam")
        ZonedDateTime("2024-03-09 23:00:00+01:00[Europe/Amsterdam]")

        Raises
        ------
        ~whenever.TimeZoneNotFoundError
            If the time zone ID is not found in the time zone database.
        """
        secs, nanos = divmod(time_ns(), 1_000_000_000)
        _tz = _load_tz(tz)
        return cls._from_py_unchecked(_from_epoch(secs, _tz), nanos, _tz)

    @classmethod
    def now_in_system_tz(cls) -> ZonedDateTime:
        """Create an instance from the current time in the system time zone.

        .. deprecated:: 0.11
           Use ``ZonedDateTime.now(SYSTEM_TZ)`` instead.

        Equivalent to ``now(SYSTEM_TZ)``.
        """
        warn_deprecated(
            "now_in_system_tz() is deprecated; use now(SYSTEM_TZ) instead",
            stacklevel=2,
        )
        return cls.now(SYSTEM_TZ)

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
        tz_id_display: Literal[
            "required", "if_available", "omit", "always", "auto", "never"
        ] = UNSET,
        **kwargs: Any,
    ) -> str:
        """Format as an ISO 8601 string, such as
        ``2020-08-15T23:12:00+01:00[Europe/London]``.

        Inverse of :meth:`parse_iso`.

        >>> zdt = ZonedDateTime(2020, 8, 15, hour=23, minute=12, tz="Europe/London")
        >>> zdt.format_iso(unit="minute", basic=True)
        "20200815T2312+0100[Europe/London]"

        Parameters
        ----------
        unit
            The smallest unit to include in the output.
            ``"auto"`` is the same as ``"nanosecond"``,
            except that trailing zeroes are omitted from the time part.
            A unit above ``"second"`` drops the smaller fields:
            ``unit="hour"`` writes ``2020-08-15T23+01:00[Europe/London]``.
        basic
            Whether to use the basic ISO format (without separators) instead of the extended one.
        sep
            The separator between the date and time parts.
        tz_id_display
            Whether to include the time zone ID in the output.
            ``"required"`` (default) raises :exc:`ValueError` when the time zone
            has no ID, which happens for some system time zones.
            ``"if_available"`` writes the ID when there is one and omits it otherwise.
            ``"omit"`` never writes it.

        Important
        ---------
        The time zone ID is a recent extension to the ISO 8601 format (RFC 9557).
        Although it is gaining popularity, it is not yet widely supported
        by ISO 8601 parsers.
        """
        tz_id_display, renamed = normalize_renamed_keyword(
            tz_id_display,
            kwargs,
            function_name="format_iso",
            new_name="tz_id_display",
            old_name="tz",
        )
        check_no_kwargs(kwargs, "format_iso")
        deprecated_value = None
        if tz_id_display is UNSET:
            tz_id_display = "required"
        elif tz_id_display in _TZ_ID_DISPLAY_DEPRECATED:
            deprecated_value = tz_id_display
            tz_id_display = _TZ_ID_DISPLAY_DEPRECATED[tz_id_display]

        if tz_id_display == "required":
            if self._tz.key is None:
                raise ValueError(FORMAT_ISO_NO_TZ_MSG)
            suffix = f"[{self._tz.key}]"
        elif tz_id_display == "if_available":
            suffix = f"[{self._tz.key}]" if self._tz.key is not None else ""
        elif tz_id_display == "omit":
            suffix = ""
        else:
            raise ValueError(f"invalid tz_id_display: {tz_id_display!r}")

        result = (
            _format_dt(
                self._py_dt,
                self._nanos,
                self._current_offset_secs(),
                unit,
                sep,
                basic,
            )
            + suffix
        )
        if renamed:
            warn_renamed_keyword("tz_id_display", "tz", stacklevel=2)
        if deprecated_value is not None:
            warn_deprecated(
                f"tz_id_display='{deprecated_value}' is deprecated; "
                f"use '{tz_id_display}' instead",
                stacklevel=2,
            )
        return result

    @classmethod
    def parse_iso(
        cls,
        s: str,
        /,
        *,
        disambiguation: DisambiguationStr = UNSET,
        offset_mismatch: OffsetMismatchStr = "raise",
        **kwargs: Any,
    ) -> ZonedDateTime:
        """Parse an ISO 8601 string with a bracketed time zone ID, such as
        ``2020-08-15T23:12:00+01:00[Europe/London]``.

        Inverse of :meth:`format_iso`. The bracketed time zone
        ID follows the same rules as ``tz=``: an unknown or malformed one
        raises :exc:`~whenever.TimeZoneNotFoundError`.
        See :ref:`iso8601` for the accepted variants.

        See the :ref:`time zone resolution guide <offset-mismatch>`
        for how ``offset_mismatch`` interacts with ``disambiguation``.

        >>> ZonedDateTime.parse_iso("2020-08-15T23:12:00+01:00[Europe/London]")
        ZonedDateTime("2020-08-15 23:12:00+01:00[Europe/London]")

        Important
        ---------
        The time zone ID is a recent extension to the ISO 8601 format (RFC 9557).
        Although it is gaining popularity, it is not yet widely supported.

        Raises
        ------
        ValueError
            If the string is not in the expected format.
        ~whenever.TimeZoneNotFoundError
            If the time zone ID is not found in the time zone database.
        ~whenever.InvalidOffsetError
            If the offset matches no offset the time zone applies to the
            local time, under ``offset_mismatch="raise"``.
        """
        disambiguation, renamed = _normalize_disambiguation(
            disambiguation,
            kwargs,
            function_name="parse_iso",
        )
        check_no_kwargs(kwargs, "parse_iso")
        self = _object_new(cls)
        self._init_from_iso(
            s,
            disambiguation=disambiguation,
            offset_mismatch=offset_mismatch,
        )
        if renamed:
            _warn_disambiguate(stacklevel=2)
        return self

    def _init_from_iso(
        self,
        s: str,
        *,
        disambiguation: DisambiguationStr = UNSET,
        offset_mismatch: OffsetMismatchStr = "raise",
        **kwargs: Any,
    ) -> None:
        check_no_kwargs(kwargs, "ZonedDateTime")
        if disambiguation is not UNSET:
            check_disambiguation(disambiguation)
        written = zdt_parts_from_iso(s)
        self._py_dt, implicit = _resolve_zoned_local(
            written, False, disambiguation, offset_mismatch
        )
        self._nanos = written.nanos
        self._tz = written.tz
        # One frame further: parse_iso() or the __init__ wrapper
        if implicit:
            _warn_implicit_disambiguation(stacklevel=3)

    _PATTERN_CATS = frozenset({"date", "time", "offset", "tz"})

    def format(self, pattern: str, /) -> str:
        """Format as a custom pattern string.

        See :ref:`pattern-format` for details.

        >>> ZonedDateTime(2024, 3, 15, 14, 30, tz="Europe/Paris").format(
        ...     "YYYY-MM-DD HH:mmxxx'['VV']'"
        ... )
        '2024-03-15 14:30+01:00[Europe/Paris]'
        """
        return self._format(pattern)

    def _format(self, pattern: str, /) -> str:
        # Shared by format() and __format__(); the stack level counts
        # from warn_pattern() through here to the caller of either.
        elements = compile_pattern(pattern)
        validate_fields(elements, self._PATTERN_CATS, "ZonedDateTime")
        d = self._py_dt
        result = format_fields(
            elements,
            year=d.year,
            month=d.month,
            day=d.day,
            weekday=d.weekday(),
            hour=d.hour,
            minute=d.minute,
            second=d.second,
            nanos=self._nanos,
            offset_secs=self._current_offset_secs(),
            tz_id=self._tz.key,
            tz_abbrev=self.tz_abbrev(),
        )
        warn_pattern(elements, stacklevel=4)
        return result

    def __format__(self, spec: str, /) -> str:
        return str(self) if not spec else self._format(spec)

    @classmethod
    def parse(
        cls,
        s: str,
        /,
        *,
        pattern: str = UNSET,
        disambiguation: DisambiguationStr = UNSET,
        offset_mismatch: OffsetMismatchStr = "raise",
        **kwargs: Any,
    ) -> ZonedDateTime:
        """Parse a zoned datetime from a custom pattern string.

        The pattern **must** include a time zone ID specifier (``VV``), which
        follows the same rules as ``tz=``: an unknown or malformed ID raises
        :exc:`~whenever.TimeZoneNotFoundError`.
        An offset specifier (``x``/``X``) is optional but recommended for
        disambiguation during DST transitions.
        See the :ref:`time zone resolution guide <offset-mismatch>`
        for how ``offset_mismatch`` interacts with ``disambiguation``.
        See :ref:`pattern-format` for details.

        .. tip::

            If your input string doesn't include a time zone ID, parse it with
            :meth:`PlainDateTime.parse` first, then convert using
            :meth:`~PlainDateTime.assume_tz`.

        >>> ZonedDateTime.parse(
        ...     "2024-03-15 14:30+01:00[Europe/Paris]",
        ...     pattern="YYYY-MM-DD HH:mmxxx'['VV']'",
        ... )
        ZonedDateTime("2024-03-15 14:30:00+01:00[Europe/Paris]")

        Raises
        ------
        ValueError
            If the string does not match the pattern.
        ~whenever.TimeZoneNotFoundError
            If the time zone ID is not found in the time zone database.
        ~whenever.InvalidOffsetError
            If the offset matches no offset the time zone applies to the
            local time, under ``offset_mismatch="raise"``.
        """
        disambiguation, disambiguate_renamed = _normalize_disambiguation(
            disambiguation, kwargs, function_name="parse"
        )
        pattern, renamed = _normalize_pattern(pattern, kwargs)
        if disambiguation is not UNSET:
            check_disambiguation(disambiguation)
        elements = compile_pattern(pattern)
        validate_fields(elements, cls._PATTERN_CATS, "ZonedDateTime")
        state = parse_fields(elements, s)
        if state.tz_id is None:
            raise ValueError(
                "pattern must include a time zone ID specifier (VV)"
            )
        if state.year is None or state.month is None or state.day is None:
            raise ValueError("pattern must include a year, a month, and a day")
        local = _datetime(
            state.year,
            state.month,
            state.day,
            state.hour or 0,
            state.minute or 0,
            state.second or 0,
        )
        if state.weekday is not None and local.weekday() != state.weekday:
            raise ValueError("weekday does not match the date")
        written = ZonedInput(
            local,
            state.nanos,
            get_tz(state.tz_id),
            (
                "Z"
                if state.offset_is_z
                else (
                    None
                    if state.offset_secs is None
                    else mk_fixed_tzinfo(state.offset_secs)
                )
            ),
            state.offset_exact,
        )
        resolved, implicit = _resolve_zoned_local(
            written, False, disambiguation, offset_mismatch
        )
        self = _object_new(cls)
        self._py_dt = resolved
        self._nanos = written.nanos
        self._tz = written.tz
        if implicit:
            _warn_implicit_disambiguation(stacklevel=2)
        warn_pattern(elements, stacklevel=3)
        if renamed:
            _warn_format(stacklevel=2)
        if disambiguate_renamed:
            _warn_disambiguate(stacklevel=2)
        return self

    @classmethod
    def from_timestamp(
        cls, value: int | float, /, *, tz: str | _SystemTZ
    ) -> ZonedDateTime:
        """Create an instance from a UNIX timestamp (in seconds).

        .. deprecated:: 0.11
           Create an :class:`Instant` and call ``to_tz()`` instead.

        The inverse of the ``timestamp()`` method.
        """
        return cls._from_timestamp_deprecated(
            value,
            "second",
            tz,
            "ZonedDateTime.from_timestamp() is deprecated; use Instant.from_timestamp(...).to_tz(...) instead",
        )

    @classmethod
    def from_timestamp_millis(
        cls, value: int, /, *, tz: str | _SystemTZ
    ) -> ZonedDateTime:
        """Create an instance from a UNIX timestamp (in milliseconds).

        .. deprecated:: 0.11
           Use ``Instant.from_timestamp(..., unit="millisecond").to_tz()``.

        The inverse of the ``timestamp_millis()`` method.
        """
        return cls._from_timestamp_deprecated(
            value,
            "millisecond",
            tz,
            "ZonedDateTime.from_timestamp_millis() is deprecated; use Instant.from_timestamp(..., unit='millisecond').to_tz(...) instead",
        )

    @classmethod
    def from_timestamp_nanos(
        cls, value: int, /, *, tz: str | _SystemTZ
    ) -> ZonedDateTime:
        """Create an instance from a UNIX timestamp (in nanoseconds).

        .. deprecated:: 0.11
           Use ``Instant.from_timestamp(..., unit="nanosecond").to_tz()``.

        The inverse of the ``timestamp_nanos()`` method.
        """
        return cls._from_timestamp_deprecated(
            value,
            "nanosecond",
            tz,
            "ZonedDateTime.from_timestamp_nanos() is deprecated; use Instant.from_timestamp(..., unit='nanosecond').to_tz(...) instead",
        )

    @classmethod
    def _from_timestamp_deprecated(
        cls,
        value: int | float,
        unit: TimestampUnitStr,
        tz: str | _SystemTZ,
        deprecation: str,
        /,
    ) -> ZonedDateTime:
        # Validate and compute first: a call that raises emits no warning.
        secs, nanos = split_timestamp(value, unit)
        _tz = _load_tz(tz)
        py_dt = _tz.convert(_from_epoch_utc(secs))
        warn_deprecated(deprecation, stacklevel=3)
        return cls._from_py_unchecked(py_dt, nanos, _tz)

    def _init_from_py(
        self,
        d: _datetime,
        *,
        disambiguation: DisambiguationStr = UNSET,
        offset_mismatch: OffsetMismatchStr = "raise",
        **kwargs: Any,
    ) -> None:
        from zoneinfo import ZoneInfo

        check_no_kwargs(kwargs, "ZonedDateTime")
        if disambiguation is not UNSET:
            check_disambiguation(disambiguation)
        py_dt = _strip_subclasses(d)
        tzinfo = py_dt.tzinfo
        if tzinfo is None:
            raise ValueError("datetime is naive; use PlainDateTime() instead")
        if not isinstance(tzinfo, ZoneInfo):
            raise ValueError(f"tzinfo must be a ZoneInfo, got {tzinfo!r}")
        if tzinfo.key is None:
            raise ValueError(ZONEINFO_NO_KEY_MSG)
        if not isinstance(tzinfo.key, str):
            raise TypeError("ZoneInfo key must be a string")

        # The datetime is read the way its own tzinfo reads it: local fields,
        # the offset ZoneInfo computes for them, and a time zone ID. That is the
        # same shape as an ISO string with an offset and a time zone ID, so it
        # goes through the same resolution flow.
        offset = py_dt.utcoffset()
        assert offset is not None
        if offset.microseconds:  # pragma: no cover
            # Unreachable via ZoneInfo: the TZif format stores whole seconds.
            raise ValueError("offset must be a whole number of seconds")
        written = ZonedInput(
            py_dt.replace(tzinfo=None, microsecond=0, fold=0),
            py_dt.microsecond * 1_000,
            get_tz(tzinfo.key),
            _timezone(offset),
            True,
        )
        self._py_dt, implicit = _resolve_zoned_local(
            written, True, disambiguation, offset_mismatch
        )
        self._nanos = written.nanos
        self._tz = written.tz
        warn_lossy_stdlib_subclass(d, _datetime)
        # One frame further: the __init__ wrapper
        if implicit:
            _warn_implicit_disambiguation(stacklevel=3)

    def replace_date(
        self,
        date: Date,
        /,
        *,
        disambiguation: DisambiguationStr = UNSET,
        **kwargs: Any,
    ) -> ZonedDateTime:
        """Create a new instance with the date replaced

        See :meth:`replace`: the current offset is kept while it applies to
        the new local time; otherwise ``disambiguation=`` decides, with
        :class:`ImplicitDisambiguationWarning` when omitted.

        >>> d = ZonedDateTime(2023, 10, 29, 2, 30, tz="Europe/Paris", disambiguation="later")
        >>> d.replace_date(Date(2023, 10, 30))
        ZonedDateTime("2023-10-30 02:30:00+01:00[Europe/Paris]")
        """
        if not isinstance(date, Date):
            raise TypeError("replace_date() argument must be a Date")
        disambiguation, renamed = _normalize_disambiguation(
            disambiguation,
            kwargs,
            function_name="replace_date",
        )
        check_no_kwargs(kwargs, "replace_date")
        result, implicit = self._replace_date(date, disambiguation)
        if implicit:
            _warn_implicit_disambiguation(stacklevel=2)
        if renamed:
            _warn_disambiguate(stacklevel=2)
        return result

    def _replace_date(
        self, date: Date, disambiguation: Any, /
    ) -> tuple[ZonedDateTime, bool]:
        resolved, implicit = _resolve_disambiguation(
            _datetime.combine(date._py_date, self._py_dt.time()),
            self._tz,
            disambiguation,
            self._nanos,
            preferred_offset=self._current_offset_secs(),
        )
        return (
            self._from_py_unchecked(resolved, self._nanos, self._tz),
            implicit,
        )

    def _with_date(self, date: Date, /) -> ZonedDateTime:
        """The same time on ``date``, keeping the offset while it applies:
        an intermediate value in a calculation, which no warning attends."""
        return self._replace_date(date, UNSET)[0]

    def replace_time(
        self,
        time: Time,
        /,
        *,
        disambiguation: DisambiguationStr = UNSET,
        **kwargs: Any,
    ) -> ZonedDateTime:
        """Create a new instance with the time replaced

        See :meth:`replace`: the current offset is kept while it applies to
        the new local time; otherwise ``disambiguation=`` decides, with
        :class:`ImplicitDisambiguationWarning` when omitted.

        >>> d = ZonedDateTime(2023, 10, 29, 2, 30, tz="Europe/Paris", disambiguation="later")
        >>> d.replace_time(Time(12))
        ZonedDateTime("2023-10-29 12:00:00+01:00[Europe/Paris]")
        """
        if not isinstance(time, Time):
            raise TypeError("replace_time() argument must be a Time")
        disambiguation, renamed = _normalize_disambiguation(
            disambiguation,
            kwargs,
            function_name="replace_time",
        )
        check_no_kwargs(kwargs, "replace_time")
        resolved, implicit = _resolve_disambiguation(
            _datetime.combine(self._py_dt, time._py),
            self._tz,
            disambiguation,
            time._nanos,
            preferred_offset=self._current_offset_secs(),
        )
        result = self._from_py_unchecked(resolved, time._nanos, self._tz)
        if implicit:
            _warn_implicit_disambiguation(stacklevel=2)
        if renamed:
            _warn_disambiguate(stacklevel=2)
        return result

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
            tz: str | _SystemTZ = ...,
            disambiguation: DisambiguationStr = ...,
        ) -> ZonedDateTime: ...

    def replace(
        self,
        /,
        *,
        disambiguation: DisambiguationStr = UNSET,
        **kwargs: Any,
    ) -> ZonedDateTime:
        """Create a new instance with the given fields replaced

        Tip
        ---
        If you need the start or end of a unit (e.g. the start of the day),
        use :meth:`start_of` and :meth:`end_of` instead.

        Important
        ---------
        Replacing fields keeps the current offset while it is valid for the
        new local time (**offset-preserving resolution**), so a repeated
        local time stays on its side of the transition, whatever
        ``disambiguation=`` says. A skipped local time, a changed ``tz=``,
        or an offset that no longer applies falls to ``disambiguation=``,
        which is ``"compatible"`` with :class:`ImplicitDisambiguationWarning`
        when omitted. A stated ``tz=`` keeps the local fields and moves the
        instant; :meth:`to_tz` keeps the instant. See
        :ref:`offset-preserving`.

        >>> d = ZonedDateTime(2023, 10, 29, 2, 30, tz="Europe/Paris", disambiguation="later")
        >>> d.replace(minute=45)  # still the second occurrence
        ZonedDateTime("2023-10-29 02:45:00+01:00[Europe/Paris]")
        >>> d.replace(minute=45, disambiguation="earlier")  # the offset still decides
        ZonedDateTime("2023-10-29 02:45:00+01:00[Europe/Paris]")

        Pass ``SYSTEM_TZ`` as ``tz=`` for the system time zone.

        Raises
        ------
        ValueError
            If a field is out of range or the result is out of range.
        ~whenever.TimeZoneNotFoundError
            If the time zone ID is not found in the time zone database.
        """

        disambiguation, renamed = _normalize_disambiguation(
            disambiguation,
            kwargs,
            function_name="replace",
        )
        nanos = _pop_replace_nanos(kwargs, self._nanos)
        try:
            tzid = kwargs.pop("tz")
        except KeyError:
            tz = self._tz
        else:
            tz = _load_tz(tzid)
        resolved, implicit = _resolve_disambiguation(
            replace_fields(self._py_dt, **kwargs, tzinfo=None),
            tz,
            disambiguation,
            nanos,
            # The offset is only kept within the same time zone
            preferred_offset=(
                self._current_offset_secs() if tz == self._tz else None
            ),
        )
        result = self._from_py_unchecked(resolved, nanos, tz)
        if implicit:
            _warn_implicit_disambiguation(stacklevel=2)
        if renamed:
            _warn_disambiguate(stacklevel=2)
        return result

    @property
    def tz(self) -> str | None:
        """Deprecated alias of :attr:`tz_id`.

        .. deprecated:: 0.11
           Use :attr:`tz_id` instead.
        """
        warn_deprecated(
            "tz is deprecated; use tz_id instead",
            stacklevel=2,
        )
        return self.tz_id

    @property
    def tz_id(self) -> str | None:
        """The time zone ID. In rare cases, this may be ``None``,
        if the ``ZonedDateTime`` was created from a :ref:`system time zone
        <systemtime>` without a time zone ID.
        """
        return self._tz.key

    def __hash__(self) -> int:
        return hash((self._py_dt, self._nanos))

    def __add__(
        self,
        delta: TimeDelta,
        /,
    ) -> ZonedDateTime:
        """Add an amount of time, accounting for time zone changes (e.g. DST).

        See `the docs <https://whenever.rtfd.io/en/latest/guide/arithmetic.html>`__
        for more information.
        """
        if isinstance(delta, TimeDelta):
            delta_secs, nanos = divmod(
                delta._total_ns + self._nanos, 1_000_000_000
            )
            new_epoch = int(self._py_dt.timestamp()) + delta_secs
            return self._from_py_unchecked(
                _from_epoch(new_epoch, self._tz),
                nanos,
                self._tz,
            )
        return NotImplemented

    @overload
    def __sub__(self, other: _ExactTimeAlias, /) -> TimeDelta: ...

    @overload
    def __sub__(self, other: TimeDelta, /) -> ZonedDateTime: ...

    def __sub__(
        self, other: TimeDelta | _ExactTimeAlias, /
    ) -> _ExactTimeAlias | TimeDelta:
        """Subtract an exact time or a delta.

        See `the docs <https://whenever.rtfd.io/en/latest/guide/arithmetic.html>`__
        for more information.
        """
        if isinstance(other, _EXACT_TIME_TYPES):
            return self._subtract_operator(other)
        elif isinstance(other, TimeDelta):
            return self + -other
        return NotImplemented

    @overload
    def add(
        self,
        d: AnyDelta,
        /,
        *,
        disambiguation: DisambiguationStr = ...,
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
        disambiguation: DisambiguationStr = ...,
    ) -> ZonedDateTime: ...

    @no_type_check
    def add(self, *args, **kwargs) -> ZonedDateTime:
        """Return a new ``ZonedDateTime`` shifted by the given time amounts

        Years and months are applied first (clamped), then weeks and days,
        all in local time; then the exact units move the instant.
        ``subtract()`` is ``add()`` of the negated components.

        Important
        ---------
        Shifting by **calendar units** (e.g. months, weeks)
        may land on a repeated or skipped local time (e.g. during a DST transition).
        Therefore, when adding calendar units, it's recommended to
        specify how to handle such a situation using the ``disambiguation`` argument.

        See `the documentation <https://whenever.rtfd.io/en/latest/guide/arithmetic.html>`__
        for more information.
        """
        return self._shift(1, *args, **kwargs)

    @overload
    def subtract(self, d: TimeDelta, /) -> ZonedDateTime: ...

    @overload
    def subtract(
        self,
        d: ItemizedDelta | ItemizedDateDelta,
        /,
        *,
        disambiguation: DisambiguationStr = ...,
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
        disambiguation: DisambiguationStr = ...,
    ) -> ZonedDateTime: ...

    @no_type_check
    def subtract(self, *args, **kwargs) -> ZonedDateTime:
        """The inverse of the ``add()`` method. See :meth:`add` for more information."""
        return self._shift(-1, *args, **kwargs)

    @no_type_check
    def _shift(
        self,
        sign: int,
        *args,
        disambiguation: DisambiguationStr = UNSET,
        **kwargs,
    ) -> ZonedDateTime:
        # Undocumented, and accepted by the Rust backend too: a
        # library-internal calendar shift (the itemized-delta operators in
        # `_ideltas.py`, shared by both backends) passes it so its
        # ImplicitDisambiguationWarning lands on its own caller; never catch
        # and re-emit the warning.
        extra = kwargs.pop("_warn_stacklevel", 1) - 1
        fname = "add" if sign == 1 else "subtract"
        disambiguation, renamed = _normalize_disambiguation(
            disambiguation, kwargs, function_name=fname
        )
        # Validated on entry, whether or not the shift consults it.
        if disambiguation is not UNSET:
            check_disambiguation(disambiguation)
        result, implicit = self._shift_kwargs(
            sign,
            disambiguation=disambiguation,
            **_shift_components(
                fname,
                args,
                kwargs,
                units=TOTAL_UNITS,
                delta_types=AnyDelta,
                expected=_ANY_DELTA_EXPECTED,
            ),
        )
        if implicit:
            _warn_implicit_disambiguation(stacklevel=3 + extra)
        if renamed:
            _warn_disambiguate(stacklevel=3 + extra)
        return result

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
        disambiguation: DisambiguationStr = UNSET,
    ) -> tuple[ZonedDateTime, bool]:
        new_date = _shift_date(self.date(), sign, years, months, weeks, days)
        delta_ns = _time_units_to_nanos(
            sign,
            hours,
            minutes,
            seconds,
            milliseconds,
            microseconds,
            nanoseconds,
        )
        implicit = False
        if new_date != self.date():
            self, implicit = self._replace_date(new_date, disambiguation)
        delta_secs, nanos = divmod(delta_ns + self._nanos, 1_000_000_000)
        new_epoch = int(self._py_dt.timestamp()) + delta_secs
        return (
            self._from_py_unchecked(
                _from_epoch(new_epoch, self._tz), nanos, self._tz
            ),
            implicit,
        )

    @overload
    def since(
        self,
        other: ZonedDateTime,
        /,
        *,
        total: DeltaTotalUnitStr,
    ) -> float: ...

    @overload
    def since(
        self,
        other: ZonedDateTime,
        /,
        *,
        in_units: Sequence[DeltaUnitStr],
        round_mode: RoundModeStr = ...,
        round_increment: int = ...,
    ) -> ItemizedDelta: ...

    def since(
        self,
        other: ZonedDateTime,
        /,
        *,
        total: DeltaTotalUnitStr = UNSET,
        in_units: Sequence[DeltaUnitStr] = UNSET,
        round_mode: RoundModeStr = UNSET,
        round_increment: int = UNSET,
    ) -> ItemizedDelta | float:
        """Calculate the duration since another ZonedDateTime,
        in terms of the specified units.

        >>> d1 = ZonedDateTime("2020-08-15T23:12:00+01:00[Europe/London]")
        >>> d2 = ZonedDateTime("2020-08-14T22:00:00+09:00[Asia/Tokyo]")
        >>> d1.since(d2, in_units=["hours", "minutes"],
        ...          round_increment=15,
        ...          round_mode="ceil")
        ItemizedDelta("PT33h15m")

        When calculating calendar units (years, months, weeks, days),
        both datetimes must have the same time zone.
        """
        return _zoned_since(
            self,
            other,
            flip=False,
            total=total,
            in_units=in_units,
            round_mode=round_mode,
            round_increment=round_increment,
        )

    @overload
    def until(
        self,
        other: ZonedDateTime,
        /,
        *,
        total: DeltaTotalUnitStr,
    ) -> float: ...

    @overload
    def until(
        self,
        other: ZonedDateTime,
        /,
        *,
        in_units: Sequence[DeltaUnitStr],
        round_mode: RoundModeStr = ...,
        round_increment: int = ...,
    ) -> ItemizedDelta: ...

    def until(
        self,
        other: ZonedDateTime,
        /,
        *,
        total: DeltaTotalUnitStr = UNSET,
        in_units: Sequence[DeltaUnitStr] = UNSET,
        round_mode: RoundModeStr = UNSET,
        round_increment: int = UNSET,
    ) -> ItemizedDelta | float:
        """Inverse of the ``since()`` method. See :meth:`since` for more information."""
        return _zoned_since(
            self,
            other,
            flip=True,
            total=total,
            in_units=in_units,
            round_mode=round_mode,
            round_increment=round_increment,
        )

    def is_repeated(self) -> bool:
        """Whether this local time occurs twice in its time zone
        (a :term:`repeated local time`), for example on the night
        daylight saving time ends.

        >>> ZonedDateTime(2020, 8, 15, 23, tz="Europe/London").is_repeated()
        False
        >>> ZonedDateTime(2023, 10, 29, 2, 15, tz="Europe/Amsterdam").is_repeated()
        True
        """
        return (
            type(
                self._tz.ambiguity_for_local(self._py_dt.replace(tzinfo=None))
            )
            is not Unique
        )

    def is_ambiguous(self) -> bool:
        """Whether this local time occurs twice in its time zone.

        .. deprecated:: 0.11
           Use :meth:`is_repeated` instead.
        """
        warn_deprecated(
            "is_ambiguous() is deprecated; use is_repeated() instead",
            stacklevel=2,
        )
        return self.is_repeated()

    def next_transition(self) -> ZonedDateTime | None:
        """The next change of the time zone's rules strictly after this
        datetime, as the first instant at which the new rules apply, in the
        same time zone, with zero nanoseconds. A change of the UTC offset,
        the DST offset, or the abbreviation counts. ``None`` when the time
        zone has no further change: UTC and fixed offsets. A POSIX rule tail
        projects offset changes for every year through 9999.

        >>> d = ZonedDateTime(2024, 1, 1, tz="America/New_York")
        >>> d.next_transition()
        ZonedDateTime("2024-03-10 03:00:00-04:00[America/New_York]")
        >>> # the offset stays; the DST offset and abbreviation change
        >>> ZonedDateTime(1968, 6, 1, tz="Europe/London").next_transition()
        ZonedDateTime("1968-10-27 00:00:00+01:00[Europe/London]")
        """
        epoch = int(self._py_dt.timestamp())
        if (result := self._tz.next_transition(epoch)) is None:
            return None
        t, offset = result
        return self._from_py_unchecked(
            _from_epoch_offset(t, offset), 0, self._tz
        )

    def prev_transition(self) -> ZonedDateTime | None:
        """The previous change of the time zone's rules strictly before this
        datetime, as the first instant at which its rules apply, in the same
        time zone, with zero nanoseconds. A change of the UTC offset, the DST
        offset, or the abbreviation counts. ``None`` when the time zone has
        no earlier change: UTC and fixed offsets, and before the first
        recorded change.

        >>> d = ZonedDateTime(2024, 1, 1, tz="America/New_York")
        >>> d.prev_transition()
        ZonedDateTime("2023-11-05 01:00:00-05:00[America/New_York]")
        """
        # The search is in whole seconds, strictly before: a value less than
        # a second past a transition still follows it.
        epoch = int(self._py_dt.timestamp()) + (self._nanos > 0)
        if (result := self._tz.prev_transition(epoch)) is None:
            return None
        t, offset = result
        return self._from_py_unchecked(
            _from_epoch_offset(t, offset), 0, self._tz
        )

    def dst_offset(self) -> TimeDelta:
        """The DST offset (adjustment) of the datetime

        >>> ZonedDateTime(2020, 8, 15, tz="Europe/London").dst_offset()
        TimeDelta("PT1h")
        >>> ZonedDateTime(2020, 1, 15, tz="Europe/London").dst_offset()
        TimeDelta("PT0s")

        This value is ``TimeDelta.ZERO`` when DST is not active:

        >>> d = ZonedDateTime(2020, 8, 15, tz="Europe/London")
        >>> if d.dst_offset():
        ...     print("DST is active")
        DST is active

        Note
        ----
        Some time zones have unusual DST rules. For example, some builds
        of the time zone database define Europe/Dublin's standard time as
        IST (UTC+1), with "negative DST" in winter. With such data, this
        method returns a negative value during winter.

        The value can differ from ``zoneinfo``'s ``dst()``, which falls back
        to one hour when it cannot pair a DST period with a standard one.
        """
        dst_saving, _ = self._tz.meta_for_instant(int(self._py_dt.timestamp()))
        return TimeDelta._from_nanos_unchecked(dst_saving * 1_000_000_000)

    def tz_abbrev(self) -> str:
        """The time zone abbreviation (e.g. ``"EST"``, ``"CEST"``).

        >>> ZonedDateTime(2020, 8, 15, tz="Europe/London").tz_abbrev()
        'BST'
        >>> ZonedDateTime(2020, 1, 15, tz="Europe/London").tz_abbrev()
        'GMT'

        Warning
        -------
        The abbreviation is often ambiguous and may not be unique,
        but it is commonly used in human-readable formats.
        Use the time zone ID (e.g. ``"Europe/London"``) for unambiguous identification of time zones.
        """
        return self._tz.meta_for_instant(int(self._py_dt.timestamp()))[1]

    def day_length(self) -> TimeDelta:
        """The duration between the start of the current day and the next.
        This is usually 24 hours, but may be different due to time zone transitions.

        >>> ZonedDateTime(2020, 8, 15, tz="Europe/London").day_length()
        TimeDelta("PT24h")
        >>> ZonedDateTime(2023, 10, 29, tz="Europe/Amsterdam").day_length()
        TimeDelta("PT25h")
        """
        start, end = self._day_bounds()
        return TimeDelta._from_nanos_unchecked(
            int((end - start).total_seconds()) * 1_000_000_000
        )

    def _day_bounds(self) -> tuple[_datetime, _datetime]:
        """The start of the day this value lies in, and of the next. Both go
        through the resolver ``start_of("day")`` uses, so the day's length
        can't drift from the boundaries it measures."""
        midnight = self._day_midnight()
        return (
            self._resolve_derived_local(midnight),
            self._resolve_derived_local(_shift_days(midnight, 1)),
        )

    def _day_midnight(self) -> _datetime:
        """The naive midnight of the day this value lies in. A day is chosen
        by the instant, not by the local date: past a repeated midnight, the
        second pass of the evening before lies in the day that has already
        started."""
        midnight = _datetime.combine(self._py_dt.date(), _time.min)
        try:
            next_midnight = midnight + _timedelta(days=1)
            next_start = self._resolve_derived_local(next_midnight)
        except (OverflowError, ValueError):
            return midnight
        return next_midnight if self._py_dt >= next_start else midnight

    def _resolve_derived_local(self, naive: _datetime, /) -> _datetime:
        """Resolve a calendar-unit boundary this value derived, which every
        value on the date must share: a repeated one takes the earlier
        occurrence, and a skipped one snaps to the end of the gap, so that
        successive intervals stay contiguous."""
        match self._tz.ambiguity_for_local(naive):
            case Unique(offset):
                pass
            case Fold(_, earlier_offset, _):
                offset = earlier_offset
            case Gap(end, later_offset, _):  # pragma: no branch
                return _from_epoch_offset(end - later_offset, later_offset)
        # Raise for a local time that is valid but whose instant is not.
        return check_utc_bounds(naive.replace(tzinfo=mk_fixed_tzinfo(offset)))

    def _time_unit_bounds(self, unit_ns: int, /) -> tuple[int, int, bool]:
        """The boundaries of a unit shorter than a day around this value, in
        epoch nanoseconds: the latest at or before it, and the earliest after
        it. Also whether the first is an odd multiple of the unit within its
        local day, for a tie.

        ADR 0003 defines the boundaries: each multiple of the unit on the
        local clock, at both occurrences in a fold at least as long as the
        unit, at the earlier one in a shorter fold, and at the end of a gap.
        Where a multiple around the value occurs only at the value's own
        offset, it is the boundary on that side: another would take two
        transitions within a unit.
        """
        tz = self._tz
        t = int(self._py_dt.timestamp()) * 1_000_000_000 + self._nanos
        offset = self._current_offset_secs()
        local = t + offset * 1_000_000_000
        floor = local - local % unit_ns
        start: tuple[int, int] | None = None  # (instant, local)
        after: int | None = None
        match tz._ambiguity_for_local_epoch(floor // 1_000_000_000):
            case Unique(o) if o == offset:
                start = (floor - offset * 1_000_000_000, floor)
        match tz._ambiguity_for_local_epoch(
            (floor + unit_ns) // 1_000_000_000
        ):
            case Unique(o) if o == offset:
                after = floor + unit_ns - offset * 1_000_000_000

        if start is None or after is None:
            # Near a transition, the boundaries around the instant are
            # multiples on the clock of one of the offsets around it. The
            # floor under each is not enough: the instant may read as a
            # multiple that lies after it, and a transition within a unit
            # after it moves the first multiple of the new offset past the
            # next one of the old.
            boundaries: list[tuple[int, int]] = []  # (instant, local)
            for o in {
                offset,
                tz.offset_for_instant((t - unit_ns) // 1_000_000_000),
                tz.offset_for_instant((t + unit_ns) // 1_000_000_000),
            }:
                local = t + o * 1_000_000_000
                local -= local % unit_ns
                for multiple in (
                    local - unit_ns,
                    local,
                    local + unit_ns,
                    local + 2 * unit_ns,
                ):
                    match tz._ambiguity_for_local_epoch(
                        multiple // 1_000_000_000
                    ):
                        case Unique(unique):
                            boundaries.append(
                                (multiple - unique * 1_000_000_000, multiple)
                            )
                        case Fold(_, earlier, later):
                            boundaries.append(
                                (multiple - earlier * 1_000_000_000, multiple)
                            )
                            if (earlier - later) * 1_000_000_000 >= unit_ns:
                                boundaries.append(
                                    (
                                        multiple - later * 1_000_000_000,
                                        multiple,
                                    )
                                )
                        case Gap(end_local, later, _):  # pragma: no branch
                            boundaries.append(
                                ((end_local - later) * 1_000_000_000, multiple)
                            )
            if start is None:
                start = max(b for b in boundaries if b[0] <= t)
            if after is None:
                after = min(b for b, _ in boundaries if b > t)
        return (
            start[0],
            after,
            (start[1] % NS_PER_DAY) // unit_ns % 2 == 1,
        )

    def _from_epoch_ns(self, ns: int, /) -> ZonedDateTime:
        secs, nanos = divmod(ns, 1_000_000_000)
        return self._from_py_unchecked(
            _from_epoch(secs, self._tz), nanos, self._tz
        )

    def start_of(
        self,
        unit: Literal[
            "year",
            "month",
            "week_mon",
            "week_sun",
            "day",
            "hour",
            "minute",
            "second",
        ],
        /,
    ) -> ZonedDateTime:
        """The start of the given unit

        >>> ZonedDateTime(2024, 8, 15, 14, 30, tz="America/New_York").start_of("day")
        ZonedDateTime("2024-08-15 00:00:00-04:00[America/New_York]")
        >>> ZonedDateTime(2024, 8, 15, 14, 30, tz="America/New_York").start_of("hour")
        ZonedDateTime("2024-08-15 14:00:00-04:00[America/New_York]")

        A boundary in a gap snaps to the end of the gap, so that successive
        intervals stay contiguous.

        In a fold, a boundary on the clock occurs twice. For ``"hour"``,
        ``"minute"``, and ``"second"``, both occurrences start a unit if the
        fold is at least as long as the unit; in a shorter fold, only the
        first does, and that unit runs longer. The result is the latest start
        at or before the value. For ``"day"`` and longer units, only the
        first occurrence of a repeated midnight starts a unit: where a fold
        repeats the evening before, its second pass belongs to the new day.
        """
        if unit in _TIME_UNIT_SECS:
            return self._from_epoch_ns(
                self._time_unit_bounds(_TIME_UNIT_SECS[unit] * 1_000_000_000)[
                    0
                ]
            )
        return self._from_py_unchecked(
            self._resolve_derived_local(
                _start_of_dt(self._day_midnight(), unit)
            ),
            0,
            self._tz,
        )

    def end_of(
        self,
        unit: Literal[
            "year",
            "month",
            "week_mon",
            "week_sun",
            "day",
            "hour",
            "minute",
            "second",
        ],
        /,
    ) -> ZonedDateTime:
        """The end of the given unit

        >>> ZonedDateTime(2024, 8, 15, 14, 30, tz="America/New_York").end_of("day")
        ZonedDateTime("2024-08-15 23:59:59.999999999-04:00[America/New_York]")

        The end is one nanosecond before the start of the next unit, as
        :meth:`start_of` defines it.
        """
        if unit in _TIME_UNIT_SECS:
            return self._from_epoch_ns(
                self._time_unit_bounds(_TIME_UNIT_SECS[unit] * 1_000_000_000)[
                    1
                ]
                - 1
            )
        naive = _start_of_next_dt(self._day_midnight(), unit)
        return self._from_py_unchecked(
            self._resolve_derived_local(naive), 0, self._tz
        ).subtract(nanoseconds=1)

    def round(
        self,
        unit: (
            Literal[
                "day",
                "hour",
                "minute",
                "second",
                "millisecond",
                "microsecond",
                "nanosecond",
            ]
            | TimeDelta
        ) = "second",
        /,
        *,
        increment: int = UNSET,
        mode: RoundModeStr = "half_even",
    ) -> ZonedDateTime:
        """Round the datetime to the specified unit and increment,
        or to a multiple of a :class:`TimeDelta`.
        Different rounding modes are available.

        >>> d = ZonedDateTime("2020-08-15 23:24:18+02:00[Europe/Paris]")
        >>> d.round("day")
        ZonedDateTime("2020-08-16 00:00:00+02:00[Europe/Paris]")
        >>> d.round("minute", increment=15, mode="floor")
        ZonedDateTime("2020-08-15 23:15:00+02:00[Europe/Paris]")
        >>> d.round(TimeDelta(minutes=15))
        ZonedDateTime("2020-08-15 23:30:00+02:00[Europe/Paris]")

        Notes
        -----
        * The result is one of the boundaries :meth:`start_of` knows, with
          the increment as the unit: the latest at or before the value, or
          the earliest after it. So ``floor`` never returns a later instant,
          and ``ceil`` never an earlier one. A rounded time that is skipped
          becomes the first instant after the gap.
        * Rounding to a day compares the time elapsed since the start of the
          day with the day's length. On the 23-hour day of 2023-03-26 in
          Amsterdam, 11:31 therefore rounds down and 12:31 rounds up.
        """
        increment_ns = _round_increment_ns(unit, increment, False)
        if unit == "day":
            return self._round_day(mode)

        start, end, odd = self._time_unit_bounds(increment_ns)
        elapsed = (
            int(self._py_dt.timestamp()) * 1_000_000_000 + self._nanos - start
        )
        return self._from_epoch_ns(
            end if rounds_up(mode, elapsed, end - start, odd, 1) else start
        )

    def _round_day(self, mode: str) -> ZonedDateTime:
        # A day is not a fixed length, so the fraction to round is the time
        # elapsed since the start of the day over the day's own length.
        start, end = self._day_bounds()
        day_ns = int((end - start).total_seconds()) * 1_000_000_000
        elapsed_ns = (
            int((self._py_dt - start).total_seconds()) * 1_000_000_000
            + self._nanos
        )
        assert 0 <= elapsed_ns < day_ns
        # The start of the day is the even multiple
        return self._from_py_unchecked(
            end if rounds_up(mode, elapsed_ns, day_ns, False, 1) else start,
            0,
            self._tz,
        )

    def to_stdlib(self) -> _datetime:
        """Convert to a standard library :class:`~datetime.datetime`
        with a :class:`~zoneinfo.ZoneInfo` tzinfo.

        The time zone ID is handed to the standard library, which resolves
        it on its own search path. For a repeated local time, ``fold`` is
        set, so the value round-trips through ``ZonedDateTime()``.
        A system time zone without a time zone ID gives a fixed-offset
        :class:`~datetime.timezone` instead.

        Note
        ----
        Nanoseconds are floored to microseconds.
        If you need more control over rounding, use :meth:`round` first.
        """
        if (key := self._tz.key) is None:
            # For system time zone datetimes without a key,
            # there's nothing else we can do. This is documented behavior.
            return self._py_dt.replace(microsecond=self._nanos // 1_000)

        from zoneinfo import ZoneInfo

        # We go through astimezone because, in theory, ZoneInfo could disagree
        # with our offset. This ensures we keep the same moment in time.
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

    def strict_eq(self, other: ZonedDateTime, /) -> bool:
        """Compare two values, including what ``==`` ignores.

        ``ZonedDateTime.__eq__`` ignores the argument's type, the local
        datetime, the offset, and the time zone. A time zone is compared by
        time zone ID and definition; the system time zone may have no ID and
        then compares by definition alone. An argument of a different type
        raises :exc:`TypeError`.

        >>> a = ZonedDateTime(2020, 8, 15, hour=12, tz="Europe/Amsterdam")
        >>> b = a.to_tz("America/New_York")
        >>> a == b
        True  # same moment in time
        >>> a.strict_eq(b)
        False  # different local datetime, offset and time zone

        See :ref:`strict-equality` for the rules on every type.
        """
        if type(other) is not type(self):
            raise TypeError("strict_eq() argument must be a ZonedDateTime")
        # The contract compares the local datetime, the offset, the
        # nanoseconds and the time zone, which is what the Rust extension does.
        # Comparing the instant instead is equivalent and cheaper: the offset
        # is always resolved from the time zone, so an equal instant and an
        # equal time zone imply an equal offset, and therefore an equal local
        # datetime. Only a stale offset would separate the two, and no
        # constructor produces one.
        return (
            self._py_dt == other._py_dt  # same moment in time
            and self._nanos == other._nanos
            and self._tz == other._tz  # same time zone definition
        )

    def exact_eq(self, other: ZonedDateTime, /) -> bool:
        """Deprecated alias for :meth:`strict_eq`.

        .. deprecated:: 0.11
           Use :meth:`strict_eq` instead.
        """
        result = self.strict_eq(other)
        warn_deprecated(
            "exact_eq() is deprecated; use strict_eq() instead",
            stacklevel=2,
        )
        return result

    # An override with shortcut for efficiency if the time zone stays the same
    def to_tz(self, tz: str | _SystemTZ, /) -> ZonedDateTime:
        """Convert to the same moment in time in another time zone.

        ``to_tz(SYSTEM_TZ)`` converts to the system time zone.

        >>> d = ZonedDateTime(2020, 8, 15, 12, tz="Europe/Amsterdam")
        >>> d.to_tz("America/New_York")
        ZonedDateTime("2020-08-15 06:00:00-04:00[America/New_York]")

        Raises
        ------
        ~whenever.TimeZoneNotFoundError
            If the time zone ID is not found in the time zone database.
        """
        if (_tz := _load_tz(tz)) == self._tz:
            return self
        return self._from_py_unchecked(
            _tz.convert(self._py_dt), self._nanos, _tz
        )

    def __repr__(self) -> str:
        return (
            'ZonedDateTime("'
            + _format_dt(
                self._py_dt,
                self._nanos,
                self._current_offset_secs(),
                "auto",
                " ",
                False,
            )
            + f'[{self._tz.key or "<system time zone without ID>"}]")'
        )

    def __str__(self) -> str:
        return self.format_iso(tz_id_display="if_available")

    # a custom pickle implementation with a smaller payload
    def __reduce__(self) -> tuple[object, ...]:
        if (key := self._tz.key) is None:
            raise ValueError(
                "cannot pickle ZonedDateTime without a time zone ID"
            )
        return (
            _unpkl_zoned,
            (
                pack(
                    "<HBBBBBil",
                    *self._py_dt.timetuple()[:6],
                    self._nanos,
                    self._current_offset_secs(),
                ),
                key,
            ),
        )


# A separate function is needed for unpickling, because the
# constructor doesn't accept positional tz and fold arguments as
# required by __reduce__.
# Also, it allows backwards-compatible changes to the pickling format.
def _unpkl_zoned(data: bytes, tzid: str) -> ZonedDateTime:
    *args, nanos, offset_secs = unpack_pickle("<HBBBBBil", data)
    if not 0 <= nanos < 1_000_000_000:
        raise ValueError("invalid pickle data")
    try:
        stored = check_utc_bounds(
            _datetime(*args, tzinfo=mk_fixed_tzinfo(offset_secs))  # type: ignore[misc]
        )
    except ValueError:
        raise ValueError("invalid pickle data") from None
    tz = get_tz(tzid)
    resolved = tz.convert(stored)
    result = ZonedDateTime._from_py_unchecked(resolved, nanos, tz)
    current_offset = result._current_offset_secs()
    if current_offset != offset_secs:
        stored_local = _format_dt(stored, nanos, "", "auto", " ", False)
        resulting_local = _format_dt(resolved, nanos, "", "auto", " ", False)
        warn(
            f"the ZonedDateTime pickle stored {stored_local} with offset "
            f"{format_offset_secs(offset_secs, basic=False)} for "
            f"{tzid_display(tzid)}, but the current time zone rules map that "
            f"instant to {resulting_local} with offset "
            f"{format_offset_secs(current_offset, basic=False)}; the instant "
            "was preserved and the local datetime and offset were updated",
            PickleOffsetMismatchWarning,
            stacklevel=2,
        )
    return result


# Concrete types that implement _ExactTime. Defined here (after all three
# classes) so methods in _ExactTime can use it at call time.
_EXACT_TIME_TYPES = (Instant, OffsetDateTime, ZonedDateTime)


@final
class PlainDateTime(_LocalTime):
    """A date and time-of-day without any time zone information.

    Represents a local time as people observe it, without saying where.
    It can't be mixed with exact-time types (e.g. ``Instant``,
    ``ZonedDateTime``) without explicitly assuming a time zone or offset.

    >>> PlainDateTime(2024, 3, 10, 15, 30)
    PlainDateTime("2024-03-10 15:30:00")

    Can also be constructed from an ISO 8601 string
    or a standard library :class:`~datetime.datetime`:

    >>> PlainDateTime("2024-03-10T15:30:00")
    PlainDateTime("2024-03-10 15:30:00")

    Convert to an exact time type by supplying a time zone or offset:

    >>> dt = PlainDateTime(2024, 3, 10, 15, 30)
    >>> dt.assume_tz("Europe/Amsterdam")
    ZonedDateTime("2024-03-10 15:30:00+01:00[Europe/Amsterdam]")
    >>> dt.assume_fixed_offset(hours(5))
    OffsetDateTime("2024-03-10 15:30:00+05:00")

    When to use this type:

    - You need to express a date and time as it would appear on a
      local time, independent of time zone.
    - You receive a datetime without time zone information and need
      to represent this lack of information in the type system.
    - You're working in a context where time zones and DST
      transitions truly don't apply (e.g. a simulation).
    """

    __slots__ = ()

    # Overloads are for a nice autodoc
    # Proper typing is done in the stubs
    if not TYPE_CHECKING:

        @overload
        def __init__(self, iso_string: str, /) -> None: ...

        @overload
        def __init__(self, py_datetime: _datetime, /) -> None: ...

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
        self._py_dt = _datetime(year, month, day, hour, minute, second)
        self._nanos = check_nanos(nanosecond)

    __init__ = add_alternate_constructors(__init__, _datetime)

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
        """Format as an ISO 8601 string, such as ``2020-08-15T23:12:00``.

        Inverse of :meth:`parse_iso`.

        >>> PlainDateTime(2020, 8, 15, 23, 12).format_iso()
        '2020-08-15T23:12:00'

        ``unit``, ``basic``, and ``sep`` are as on
        :meth:`ZonedDateTime.format_iso`.
        """
        return _format_dt(self._py_dt, self._nanos, "", unit, sep, basic)

    @classmethod
    def parse_iso(cls, s: str, /) -> PlainDateTime:
        """Parse an ISO 8601 string without an offset, such as
        ``2020-08-15T23:12:00``. An offset or a bracketed time zone ID is
        rejected. See :ref:`iso8601` for the accepted variants.

        Inverse of :meth:`format_iso`.

        >>> PlainDateTime.parse_iso("2020-08-15T23:12:00")
        PlainDateTime("2020-08-15 23:12:00")
        """
        self = _object_new(cls)
        self._init_from_iso(s)
        return self

    def _init_from_iso(self, s: str) -> None:
        self._py_dt, self._nanos = datetime_from_iso(s)

    _PATTERN_CATS = frozenset({"date", "time"})

    def format(self, pattern: str, /) -> str:
        """Format as a custom pattern string.

        Also available via ``f"{dt:YYYY-MM-DD HH:mm}"`` (Python's ``__format__``
        protocol), where an empty spec falls back to :meth:`__str__`.

        See :ref:`pattern-format` for details.

        >>> PlainDateTime(2024, 3, 15, 14, 30).format("YYYY-MM-DD HH:mm")
        '2024-03-15 14:30'
        """
        return self._format(pattern)

    def _format(self, pattern: str, /) -> str:
        # Shared by format() and __format__(); the stack level counts
        # from warn_pattern() through here to the caller of either.
        elements = compile_pattern(pattern)
        validate_fields(elements, self._PATTERN_CATS, "PlainDateTime")
        d = self._py_dt
        result = format_fields(
            elements,
            year=d.year,
            month=d.month,
            day=d.day,
            weekday=d.weekday(),
            hour=d.hour,
            minute=d.minute,
            second=d.second,
            nanos=self._nanos,
        )
        warn_pattern(elements, stacklevel=4)
        return result

    def __format__(self, spec: str, /) -> str:
        return str(self) if not spec else self._format(spec)

    @classmethod
    def parse(
        cls, s: str, /, *, pattern: str = UNSET, **kwargs: Any
    ) -> PlainDateTime:
        """Parse a plain datetime from a custom pattern string.

        See :ref:`pattern-format` for details.

        >>> PlainDateTime.parse("2024-03-15 14:30", pattern="YYYY-MM-DD HH:mm")
        PlainDateTime("2024-03-15 14:30:00")
        """
        pattern, renamed = _normalize_pattern(pattern, kwargs)
        elements = compile_pattern(pattern)
        validate_fields(elements, cls._PATTERN_CATS, "PlainDateTime")
        state = parse_fields(elements, s)
        if state.year is None or state.month is None or state.day is None:
            raise ValueError("pattern must include a year, a month, and a day")
        result = cls(
            state.year,
            state.month,
            state.day,
            state.hour or 0,
            state.minute or 0,
            state.second or 0,
            nanosecond=state.nanos,
        )
        if (
            state.weekday is not None
            and result._py_dt.weekday() != state.weekday
        ):
            raise ValueError("weekday does not match the date")
        warn_pattern(elements, stacklevel=3)
        if renamed:
            _warn_format(stacklevel=2)
        return result

    def _init_from_py(self, d: _datetime, **kwargs: Any) -> None:
        check_no_kwargs(kwargs, "PlainDateTime")
        py_dt = _strip_subclasses(d)
        if py_dt.tzinfo is not None:
            raise ValueError(
                f"datetime must be naive, got tzinfo={py_dt.tzinfo!r}"
            )
        self._py_dt = py_dt.replace(microsecond=0, fold=0)
        self._nanos = py_dt.microsecond * 1_000
        warn_lossy_stdlib_subclass(d, _datetime)

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
        """Create a new instance with the given fields replaced

        A result that is not a valid date or time raises :class:`ValueError`.

        >>> d = PlainDateTime(2021, 1, 31, 12, 30)
        >>> d.replace(month=2, day=28)
        PlainDateTime("2021-02-28 12:30:00")
        """
        nanos = _pop_replace_nanos(kwargs, self._nanos)
        return self._from_py_unchecked(
            replace_fields(self._py_dt, **kwargs), nanos
        )

    def replace_date(self, date: Date, /) -> PlainDateTime:
        """Create a new instance with the date replaced

        >>> d = PlainDateTime(2021, 1, 2, 12, 30)
        >>> d.replace_date(Date(2024, 2, 29))
        PlainDateTime("2024-02-29 12:30:00")
        """
        if not isinstance(date, Date):
            raise TypeError("replace_date() argument must be a Date")
        return self._from_py_unchecked(
            _datetime.combine(date._py_date, self._py_dt.time()), self._nanos
        )

    def replace_time(self, time: Time, /) -> PlainDateTime:
        """Create a new instance with the time replaced

        >>> d = PlainDateTime(2021, 1, 2, 12, 30)
        >>> d.replace_time(Time(8, 15, nanosecond=1))
        PlainDateTime("2021-01-02 08:15:00.000000001")
        """
        if not isinstance(time, Time):
            raise TypeError("replace_time() argument must be a Time")
        return self._from_py_unchecked(
            _datetime.combine(self._py_dt.date(), time._py), time._nanos
        )

    def start_of(
        self,
        unit: Literal[
            "year",
            "month",
            "week_mon",
            "week_sun",
            "day",
            "hour",
            "minute",
            "second",
        ],
        /,
    ) -> PlainDateTime:
        """The start of the given unit

        >>> PlainDateTime(2024, 8, 15, 14, 30, 45).start_of("day")
        PlainDateTime("2024-08-15 00:00:00")
        >>> PlainDateTime(2024, 8, 15, 14, 30, 45).start_of("hour")
        PlainDateTime("2024-08-15 14:00:00")
        """
        new_dt = _start_of_dt(self._py_dt, unit)
        return self._from_py_unchecked(new_dt, 0)

    def end_of(
        self,
        unit: Literal[
            "year",
            "month",
            "week_mon",
            "week_sun",
            "day",
            "hour",
            "minute",
            "second",
        ],
        /,
    ) -> PlainDateTime:
        """The end of the given unit

        >>> PlainDateTime(2024, 8, 15, 14, 30, 45).end_of("day")
        PlainDateTime("2024-08-15 23:59:59.999999999")
        >>> PlainDateTime(2024, 8, 15, 14, 30, 45).end_of("hour")
        PlainDateTime("2024-08-15 14:59:59.999999999")

        See also :meth:`start_of`
        """
        new_dt = _end_of_dt(self._py_dt, unit)
        return self._from_py_unchecked(new_dt, _MAX_SUBSEC_NANOS)

    def __hash__(self) -> int:
        return hash((self._py_dt, self._nanos))

    def __eq__(self, other: object, /) -> bool:
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
    """The minimum possible value of this type."""
    MAX: ClassVar[PlainDateTime]
    """The maximum possible value of this type."""

    def __lt__(self, other: PlainDateTime, /) -> bool:
        if not isinstance(other, PlainDateTime):
            return NotImplemented
        return (self._py_dt, self._nanos) < (other._py_dt, other._nanos)

    def __le__(self, other: PlainDateTime, /) -> bool:
        if not isinstance(other, PlainDateTime):
            return NotImplemented
        return (self._py_dt, self._nanos) <= (other._py_dt, other._nanos)

    def __gt__(self, other: PlainDateTime, /) -> bool:
        if not isinstance(other, PlainDateTime):
            return NotImplemented
        return (self._py_dt, self._nanos) > (other._py_dt, other._nanos)

    def __ge__(self, other: PlainDateTime, /) -> bool:
        if not isinstance(other, PlainDateTime):
            return NotImplemented
        return (self._py_dt, self._nanos) >= (other._py_dt, other._nanos)

    def __add__(self, delta: TimeDelta, /) -> PlainDateTime:
        """Add a delta to this datetime.

        Warning
        -------
        Adding exact time units (a ``TimeDelta``) to a ``PlainDateTime`` does
        not account for time zone transitions that may occur in the interval.
        Use ``.assume_tz('<tz>') + delta`` if you know the time zone.
        Use ``.add(..., naive_arithmetic_ok=True)`` or Python's
        standard warning filters to suppress.
        """
        if isinstance(delta, TimeDelta):
            delta_secs, nanos = divmod(
                delta._total_ns + self._nanos, 1_000_000_000
            )
            result = self._from_py_unchecked(
                _add_seconds(self._py_dt, delta_secs), nanos
            )
            if delta._total_ns:
                warn(
                    PLAIN_SHIFT_UNAWARE_MSG,
                    NaiveArithmeticWarning,
                    stacklevel=2,
                )
            return result
        return NotImplemented

    @overload
    def __sub__(self, other: PlainDateTime, /) -> TimeDelta: ...

    @overload
    def __sub__(self, other: TimeDelta, /) -> PlainDateTime: ...

    def __sub__(
        self,
        other: PlainDateTime | TimeDelta,
        /,
    ) -> TimeDelta | PlainDateTime:
        """Subtract a delta or calculate the duration to another plain datetime.

        Warning
        -------
        Subtracting a ``TimeDelta`` or measuring the difference between two
        ``PlainDateTime`` values does not account for time zone transitions that
        may occur in the interval. Use :meth:`~whenever.PlainDateTime.assume_tz`
        to convert to a ``ZonedDateTime`` first for accurate results.
        When that is intentional, use ``subtract(..., naive_arithmetic_ok=True)``
        or ``difference(..., naive_arithmetic_ok=True)``; the operator takes
        no keyword.
        """
        if isinstance(other, TimeDelta):
            delta_secs, nanos = divmod(
                -other._total_ns + self._nanos, 1_000_000_000
            )
            result = self._from_py_unchecked(
                _add_seconds(self._py_dt, delta_secs), nanos
            )
            if other._total_ns:
                warn(
                    PLAIN_SHIFT_UNAWARE_MSG,
                    NaiveArithmeticWarning,
                    stacklevel=2,
                )
            return result
        elif isinstance(other, PlainDateTime):
            warn(
                PLAIN_DIFF_UNAWARE_MSG,
                NaiveArithmeticWarning,
                stacklevel=2,
            )
            return self._sub(other)
        return NotImplemented

    def _sub(self, other: PlainDateTime) -> TimeDelta:
        py_delta = self._py_dt - other._py_dt
        return TimeDelta(
            seconds=py_delta.days * 86_400 + py_delta.seconds,
            nanoseconds=self._nanos - other._nanos,
        )

    def difference(
        self,
        other: PlainDateTime,
        /,
        *,
        naive_arithmetic_ok: bool = UNSET,
    ) -> TimeDelta:
        """Calculate the exact time difference between two plain datetimes.

        This method returns the exact elapsed :class:`TimeDelta` between two
        ``PlainDateTime`` values. Equivalent to the subtraction operator (``-``),
        but allows suppressing the :class:`NaiveArithmeticWarning`
        via the ``naive_arithmetic_ok`` parameter.

        Use :meth:`since` or :meth:`until` for more advanced options such as
        calendar units, unit decomposition, and rounding.

        Warning
        -------
        Calculating the difference between two ``PlainDateTime`` values does
        not account for time zone transitions. Use :meth:`assume_tz` to convert
        to a ``ZonedDateTime`` first for accurate results.
        """
        if not isinstance(other, PlainDateTime):
            raise TypeError("difference() argument must be a PlainDateTime")
        if not naive_arithmetic_ok:
            warn(
                PLAIN_DIFF_UNAWARE_MSG,
                NaiveArithmeticWarning,
                stacklevel=2,
            )
        return self._sub(other)

    @overload
    def since(
        self,
        other: PlainDateTime,
        /,
        *,
        total: DeltaTotalUnitStr,
        naive_arithmetic_ok: bool = ...,
    ) -> float: ...

    @overload
    def since(
        self,
        other: PlainDateTime,
        /,
        *,
        in_units: Sequence[DeltaUnitStr],
        round_mode: RoundModeStr = ...,
        round_increment: int = ...,
        naive_arithmetic_ok: bool = ...,
    ) -> ItemizedDelta: ...

    def since(
        self,
        other: PlainDateTime,
        /,
        *,
        total: DeltaTotalUnitStr = UNSET,
        in_units: Sequence[DeltaUnitStr] = UNSET,
        round_mode: RoundModeStr = UNSET,
        round_increment: int = UNSET,
        naive_arithmetic_ok: bool = UNSET,
    ) -> ItemizedDelta | float:
        """Calculate the duration since another PlainDateTime,
        in terms of the specified units.

        >>> d1 = PlainDateTime(2020, 8, 15, 23, 12)
        >>> d2 = PlainDateTime(2020, 8, 14, 22)
        >>> d1.since(d2, in_units=["hours", "minutes"],
        ...          round_increment=15,
        ...          round_mode="ceil")
        ItemizedDelta("PT25h15m")

        Warning
        -------
        Exact units in the result (``total=`` of one, or ``in_units``
        containing any) emit :class:`~whenever.NaiveArithmeticWarning`:
        a difference in hours between two local times ignores the
        time zone transitions between them. Pass ``naive_arithmetic_ok=True``
        when that is intentional.
        """
        return _plain_since(
            self,
            other,
            flip=False,
            total=total,
            in_units=in_units,
            round_mode=round_mode,
            round_increment=round_increment,
            naive_arithmetic_ok=naive_arithmetic_ok,
        )

    @overload
    def until(
        self,
        other: PlainDateTime,
        /,
        *,
        total: DeltaTotalUnitStr,
        naive_arithmetic_ok: bool = ...,
    ) -> float: ...

    @overload
    def until(
        self,
        other: PlainDateTime,
        /,
        *,
        in_units: Sequence[DeltaUnitStr],
        round_mode: RoundModeStr = ...,
        round_increment: int = ...,
        naive_arithmetic_ok: bool = ...,
    ) -> ItemizedDelta: ...

    def until(
        self,
        other: PlainDateTime,
        /,
        *,
        total: DeltaTotalUnitStr = UNSET,
        in_units: Sequence[DeltaUnitStr] = UNSET,
        round_mode: RoundModeStr = UNSET,
        round_increment: int = UNSET,
        naive_arithmetic_ok: bool = UNSET,
    ) -> ItemizedDelta | float:
        """Inverse of the ``since()`` method. See :meth:`since` for more information."""
        return _plain_since(
            self,
            other,
            flip=True,
            total=total,
            in_units=in_units,
            round_mode=round_mode,
            round_increment=round_increment,
            naive_arithmetic_ok=naive_arithmetic_ok,
        )

    @overload
    def add(
        self,
        d: AnyDelta,
        /,
        *,
        naive_arithmetic_ok: bool = ...,
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
        naive_arithmetic_ok: bool = ...,
    ) -> PlainDateTime: ...

    @no_type_check
    def add(self, *args, **kwargs) -> PlainDateTime:
        """Add a time amount to this datetime.

        Years and months are applied first (clamped), then weeks and days;
        then the exact units. ``subtract()`` is ``add()`` of the negated
        components.

        Warning
        -------
        Adding **exact time units** (e.g. hours, seconds) to a ``PlainDateTime``
        does not account for time zone transitions that may occur in the interval.
        Use ``.assume_tz('<tz>') + delta`` if you know the time zone.
        Pass ``naive_arithmetic_ok=True`` to suppress;
        Python's standard warning filters also apply.
        """
        return self._shift(1, *args, **kwargs)

    @overload
    def subtract(
        self,
        d: AnyDelta,
        /,
        *,
        naive_arithmetic_ok: bool = ...,
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
        naive_arithmetic_ok: bool = ...,
    ) -> PlainDateTime: ...

    @no_type_check
    def subtract(self, *args, **kwargs) -> PlainDateTime:
        """Subtract a time amount from this datetime.

        See :meth:`add` for more information.
        """
        return self._shift(-1, *args, **kwargs)

    @no_type_check
    def _shift(
        self, sign: int, *args, naive_arithmetic_ok: bool = UNSET, **kwargs
    ) -> PlainDateTime:
        return self._shift_kwargs(
            sign,
            naive_arithmetic_ok=naive_arithmetic_ok,
            **_shift_components(
                "add" if sign == 1 else "subtract",
                args,
                kwargs,
                units=TOTAL_UNITS,
                delta_types=AnyDelta,
                expected=_ANY_DELTA_EXPECTED,
            ),
        )

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
        naive_arithmetic_ok: bool = UNSET,
    ) -> PlainDateTime:
        py_dt_with_new_date = self.replace_date(
            _shift_date(self.date(), sign, years, months, weeks, days),
        )._py_dt

        delta_ns = _time_units_to_nanos(
            sign,
            hours,
            minutes,
            seconds,
            milliseconds,
            microseconds,
            nanoseconds,
        )
        delta_secs, nanos = divmod(delta_ns + self._nanos, 1_000_000_000)
        result = self._from_py_unchecked(
            _add_seconds(py_dt_with_new_date, delta_secs), nanos
        )
        if delta_ns != 0 and not naive_arithmetic_ok:
            warn(
                PLAIN_SHIFT_UNAWARE_MSG,
                NaiveArithmeticWarning,
                stacklevel=4,
            )
        return result

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

        >>> PlainDateTime(2020, 8, 15, 23, 12).assume_fixed_offset(hours(2))
        OffsetDateTime("2020-08-15 23:12:00+02:00")
        """
        result = OffsetDateTime._from_py_unchecked(
            check_utc_bounds(self._py_dt.replace(tzinfo=_load_offset(offset))),
            self._nanos,
        )
        _warn_integer_offset(offset, stacklevel=3)
        return result

    def assume_tz(
        self,
        tz: str | _SystemTZ,
        /,
        *,
        disambiguation: DisambiguationStr = UNSET,
        **kwargs: Any,
    ) -> ZonedDateTime:
        """Assume the datetime is in the given time zone,
        creating a ``ZonedDateTime``. Pass ``SYSTEM_TZ`` for the system
        time zone.

        Note
        ----
        The local time may be repeated or skipped in the given time zone
        (e.g. during a DST transition). You can explicitly
        specify how to handle such a situation using the ``disambiguation`` argument.
        See `the documentation
        <https://whenever.readthedocs.io/en/latest/guide/resolving-local-times.html>`__
        for more information.

        >>> d = PlainDateTime(2020, 8, 15, 23, 12)
        >>> d.assume_tz("Europe/Amsterdam", disambiguation="raise")
        ZonedDateTime("2020-08-15 23:12:00+02:00[Europe/Amsterdam]")

        Raises
        ------
        ~whenever.TimeZoneNotFoundError
            If the time zone ID is not found in the time zone database.
        """
        disambiguation, renamed = _normalize_disambiguation(
            disambiguation,
            kwargs,
            function_name="assume_tz",
        )
        check_no_kwargs(kwargs, "assume_tz")
        result, implicit = self._assume_tz(tz, disambiguation)
        if implicit:
            _warn_implicit_disambiguation(stacklevel=2)
        if renamed:
            _warn_disambiguate(stacklevel=2)
        return result

    def _assume_tz(
        self, tz: str | _SystemTZ, disambiguation: Any, /
    ) -> tuple[ZonedDateTime, bool]:
        resolved, implicit = _resolve_disambiguation(
            self._py_dt,
            _tz := _load_tz(tz),
            disambiguation,
            self._nanos,
            preferred_offset=None,
        )
        return (
            ZonedDateTime._from_py_unchecked(resolved, self._nanos, _tz),
            implicit,
        )

    def assume_system_tz(
        self,
        *,
        disambiguation: DisambiguationStr = UNSET,
        **kwargs: Any,
    ) -> ZonedDateTime:
        """Assume the datetime is in the system time zone,
        creating a ``ZonedDateTime``.

        .. deprecated:: 0.11
           Use ``assume_tz(SYSTEM_TZ)`` instead.

        Note
        ----
        The local time may be repeated or skipped in the system time zone
        (e.g. during a DST transition). You can explicitly
        specify how to handle such a situation using ``disambiguation``.
        See `the documentation
        <https://whenever.readthedocs.io/en/latest/guide/resolving-local-times.html>`__
        for more information.

        >>> d = PlainDateTime(2020, 8, 15, 23, 12)
        >>> # assuming system time zone is America/New_York
        >>> d.assume_tz(SYSTEM_TZ, disambiguation="raise")
        ZonedDateTime("2020-08-15 23:12:00-04:00[America/New_York]")
        """
        disambiguation, renamed = _normalize_disambiguation(
            disambiguation,
            kwargs,
            function_name="assume_system_tz",
        )
        check_no_kwargs(kwargs, "assume_system_tz")
        if disambiguation is UNSET:
            disambiguation = "compatible"
        # Validate and compute first: a call that raises emits no warning.
        result = self.assume_tz(SYSTEM_TZ, disambiguation=disambiguation)
        warn_deprecated(
            "assume_system_tz() is deprecated; use assume_tz(SYSTEM_TZ) instead",
            stacklevel=2,
        )
        if renamed:
            _warn_disambiguate(stacklevel=2)
        return result

    def round(
        self,
        unit: (
            Literal[
                "day",
                "hour",
                "minute",
                "second",
                "millisecond",
                "microsecond",
                "nanosecond",
            ]
            | TimeDelta
        ) = "second",
        /,
        *,
        increment: int = UNSET,
        mode: RoundModeStr = "half_even",
    ) -> PlainDateTime:
        """Round the datetime to the specified unit and increment,
        or to a multiple of a :class:`TimeDelta`.
        Different rounding modes are available.

        >>> d = PlainDateTime(2020, 8, 15, 23, 24, 18)
        >>> d.round("day")
        PlainDateTime("2020-08-16 00:00:00")
        >>> d.round("minute", increment=15, mode="floor")
        PlainDateTime("2020-08-15 23:15:00")
        >>> d.round(TimeDelta(minutes=15))
        PlainDateTime("2020-08-15 23:30:00")
        """
        return self._round_unchecked(
            _round_increment_ns(unit, increment, False), mode
        )

    def _round_unchecked(self, increment_ns: int, mode: str) -> PlainDateTime:
        rounded_time, next_day = self.time()._round_unchecked(
            increment_ns, mode
        )
        return self.date()._add_days(next_day).at(rounded_time)

    def __repr__(self) -> str:
        return f'PlainDateTime("{str(self).replace("T", " ")}")'

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
    *args, nanos = unpack_pickle("<HBBBBBi", data)
    try:
        return PlainDateTime(*args, nanosecond=nanos)
    except ValueError:
        raise ValueError("invalid pickle data") from None


class PotentialDstBugWarning(WheneverWarning):
    """Base class for warnings about potential DST-related bugs in user code.

    Not raised directly. Subclasses cover four distinct scenarios:

    - :class:`~whenever.DaysAssumed24HoursWarning` — days treated as exact 24-hour units
    - :class:`~whenever.StaleOffsetWarning` — fixed offset may become stale relative to its source time zone
    - :class:`~whenever.NaiveArithmeticWarning` — exact-time arithmetic without time zone context
    - :class:`~whenever.ImplicitDisambiguationWarning` — resolving a repeated or skipped local time without an explicit policy

    Catching or filtering this base class handles all four at once:

    .. code-block:: python

        import warnings, whenever
        warnings.filterwarnings("error", category=whenever.PotentialDstBugWarning)
    """


class PickleOffsetMismatchWarning(WheneverWarning):
    """The offset stored in a ZonedDateTime pickle no longer matches the
    time zone's current rules. The instant is preserved; the local fields
    and offset are recomputed from the current rules. Not escapable per
    call: filter the category to reject a mismatch. See the pickling guide
    and ADR 0006.
    """


class ImplicitDisambiguationWarning(PotentialDstBugWarning):
    """Emitted when a repeated or skipped local datetime is resolved without an
    explicit disambiguation policy.

    Such local datetimes occur around time zone transitions and do not identify
    one unambiguous instant. Pass ``disambiguation=`` explicitly to document
    whether the compatible, earlier, later, or rejecting behavior is intended.
    """


class DaysAssumed24HoursWarning(PotentialDstBugWarning):
    """Emitted when days are treated as exactly 24 hours, which may be wrong
    across a DST transition.

    :class:`~whenever.TimeDelta` always represents exact time.
    Constructing one with ``days`` or ``weeks`` kwargs converts those units
    to nanoseconds using fixed 86400-second days. If you later add this delta
    to a :class:`~whenever.ZonedDateTime` on a day where clocks spring forward
    or fall back, the local time of the result will be off by the transition
    length (usually one hour).

    .. rubric:: When it can occur

    Constructing a :class:`~whenever.TimeDelta` with ``days`` or ``weeks``,
    passing them to :meth:`Instant.add() <whenever.Instant.add>`,
    :meth:`Instant.subtract() <whenever.Instant.subtract>`, or
    :meth:`TimePatch.shift() <whenever.TimePatch.shift>`, and the delta
    methods that read them as exact units, such as
    :meth:`TimeDelta.in_units() <whenever.TimeDelta.in_units>`.

    .. code-block:: python

        from whenever import TimeDelta, ZonedDateTime

        # TimeDelta(days=1) is exactly 86 400 seconds — no DST awareness.
        delta = TimeDelta(days=1)  # DaysAssumed24HoursWarning

        # Adding it to a ZonedDateTime across a spring-forward night gives
        # the wrong local time:
        eve = ZonedDateTime(2025, 3, 29, 12, tz="Europe/Amsterdam")
        eve + delta
        # ZonedDateTime("2025-03-30 13:00:00+02:00[Europe/Amsterdam]")
        # ^^ 13:00, not 12:00 — one hour lost to the DST transition

    .. rubric:: How to fix it

    Use calendar-based arithmetic directly on the datetime to preserve
    local time across transitions:

    .. code-block:: python

        eve.add(days=1)
        # ZonedDateTime("2025-03-30 12:00:00+02:00[Europe/Amsterdam]")  ✓

    To suppress when exact 24-hour arithmetic is genuinely intended, pass
    ``days_assumed_24h_ok=True`` (or use Python's standard warning filters):

    .. code-block:: python

        TimeDelta(days=1, days_assumed_24h_ok=True)
    """


class StaleOffsetWarning(PotentialDstBugWarning):
    """Emitted when an :class:`~whenever.OffsetDateTime` operation may
    preserve an offset that is stale relative to its source time zone.

    Pass ``stale_offset_ok=True`` to accept this for one call. See
    :ref:`offset-datetime-guidance` for the stale-offset footgun, examples,
    and remediation.
    """


class NaiveArithmeticWarning(PotentialDstBugWarning):
    """Emitted when exact-time arithmetic is performed on a
    :class:`~whenever.PlainDateTime` without time zone context.

    :class:`~whenever.PlainDateTime` carries no time zone information, so it
    can't account for DST transitions. When you add or subtract exact time
    units (hours, minutes, seconds) or measure the exact difference between
    two :class:`~whenever.PlainDateTime` values, the computation treats every
    hour as equal. If a time zone transition falls in the interval, the result
    may be off by an hour or more.

    .. rubric:: When it can occur

    Adding or subtracting exact units with ``add()``, ``subtract()``,
    ``+``, or ``-``; measuring exact units with ``-``, ``difference()``,
    ``since()``, or ``until()``; and a delta method whose ``relative_to``
    is a :class:`~whenever.PlainDateTime`.

    .. code-block:: python

        from whenever import PlainDateTime

        # On 2023-10-29, Amsterdam clocks fall back at 3:00 AM.
        # PlainDateTime has no knowledge of this.
        d = PlainDateTime(2023, 10, 29, 1, 30)
        d.add(hours=2)  # NaiveArithmeticWarning
        # PlainDateTime("2023-10-29 03:30:00")
        # ^^ only 1 real hour passed in Amsterdam (clocks went back)

        # Also emitted for exact-unit differences:
        d2 = PlainDateTime(2023, 10, 30, 1, 30)
        d2 - d  # NaiveArithmeticWarning

    .. rubric:: How to fix it

    Attach a time zone with :meth:`~whenever.PlainDateTime.assume_tz` first,
    then perform arithmetic on the resulting :class:`~whenever.ZonedDateTime`:

    .. code-block:: python

        d.assume_tz("Europe/Amsterdam").add(hours=2)
        # ZonedDateTime("2023-10-29 02:30:00+01:00[Europe/Amsterdam]")  ✓

    To suppress when time zone context doesn't apply (e.g. simulations,
    clock times not tied to a real-world time zone, or when you know no
    transitions occur in the interval), pass ``naive_arithmetic_ok=True``
    (or use Python's standard warning filters):

    .. code-block:: python

        d.add(hours=2, naive_arithmetic_ok=True)
    """


OFFSET_NOW_STALE_MSG = (
    "You are getting the current time using a fixed UTC offset. A fixed offset "
    "has no time zone rules, so it may be stale relative to the region you "
    "intend after a DST or other rule change. If you mean a named time zone, "
    "use ZonedDateTime.now('<tz>'); if "
    "you only need the current instant, use Instant.now(). If the fixed offset "
    "is intentional, pass `stale_offset_ok=True`. "
    + OFFSET_DATETIME_DOCS_MSG
    + " "
    + WARNING_HANDLING_DOCS_MSG
)

OFFSET_FROM_TIMESTAMP_STALE_MSG = (
    "You are converting a timestamp using a fixed UTC offset. The result is "
    "correct for that offset, but the offset may be stale relative to the "
    "region you intend at this timestamp. If you "
    "mean a named time zone, use Instant.from_timestamp(ts).to_tz('<tz>'); "
    "if you only need the instant, use Instant.from_timestamp(ts). If the fixed "
    "offset is intentional, pass `stale_offset_ok=True`. "
    + OFFSET_DATETIME_DOCS_MSG
    + " "
    + WARNING_HANDLING_DOCS_MSG
)

OFFSET_REPLACE_STALE_MSG = (
    "Replacing fields of an OffsetDateTime is valid and preserves its observed "
    "UTC offset. That offset may be stale relative to the source time zone if "
    "the result is in a different DST or time zone rule period (e.g. after "
    "replacing the month on a datetime in a European time zone). "
    "Convert to ZonedDateTime first (using .assume_tz()) for field replacement that accounts for the time zone. "
    "If the fixed offset is intentional, pass `stale_offset_ok=True`. "
    + OFFSET_DATETIME_DOCS_MSG
    + " "
    + WARNING_HANDLING_DOCS_MSG
)

OFFSET_ROUND_STALE_MSG = (
    "Rounding an OffsetDateTime is valid and preserves its observed UTC offset. "
    "That offset may be stale relative to the source time zone if the rounded "
    "time crosses a time zone transition. "
    "Convert to a ZonedDateTime first (using .assume_tz()) for rounding that accounts for the time zone. "
    "If the fixed offset is intentional, pass `stale_offset_ok=True`. "
    + OFFSET_DATETIME_DOCS_MSG
    + " "
    + WARNING_HANDLING_DOCS_MSG
)

OFFSET_START_END_OF_STALE_MSG = (
    "Getting the start or end of a unit on an OffsetDateTime is valid and "
    "preserves its observed UTC offset. That offset may be stale relative to "
    "the source time zone at the resulting time "
    "(e.g. the start of the year may have a different UTC offset due to DST). "
    "Convert to ZonedDateTime first (using .assume_tz()) for results that account for the time zone. "
    "If the fixed offset is intentional, pass `stale_offset_ok=True`. "
    + OFFSET_DATETIME_DOCS_MSG
    + " "
    + WARNING_HANDLING_DOCS_MSG
)

OFFSET_DIFFERENCE_STALE_MSG = (
    "You are calculating a difference in calendar units between OffsetDateTimes "
    "with a remainder in exact units. The whole calendar units are correct in "
    "any time zone, but the remainder after the last whole unit is computed "
    "with the offset held fixed, and a time zone transition inside that final "
    "partial unit shifts it by the transition length. Use a ZonedDateTime for "
    "a difference that accounts for the time zone. If the fixed-offset "
    "assumption is intentional, pass `stale_offset_ok=True` to `since()` or "
    "`until()`. " + OFFSET_DATETIME_DOCS_MSG + " " + WARNING_HANDLING_DOCS_MSG
)

PLAIN_DIFF_UNAWARE_MSG = (
    "Calculating the difference between two PlainDateTime values does not account for "
    "time zone transitions that may have occurred between them: "
    "for example, PlainDateTime(2023, 3, 26, 3, 0) - PlainDateTime(2023, 3, 26, 1, 0) "
    "gives 2h, but in Amsterdam clocks jumped from 2:00 to 3:00 that morning, "
    "so only 1 real hour elapsed. "
    "Use .assume_tz('<tz>') for both values if you know the time zone. "
    "If time zone transitions are intentionally irrelevant here, pass "
    "`naive_arithmetic_ok=True` to `add()`, `subtract()`, `difference()`, "
    "`since()`, or `until()`; `+` and `-` take no keyword. "
    + WARNING_HANDLING_DOCS_MSG
)

CANNOT_ROUND_DAY_MSG = (
    "cannot round an Instant to a day: an Instant has no calendar; "
    "use 'hour' with increment=24 for exactly 24 hours"
)

ZONEINFO_NO_KEY_MSG = (
    "tzinfo has no time zone ID (ZoneInfo.key is None); pass key= to "
    "ZoneInfo.from_file(), or use OffsetDateTime() to keep only the offset"
)

_TZ_ID_DISPLAY_DEPRECATED: dict[
    str, Literal["required", "if_available", "omit"]
] = {
    "always": "required",
    "auto": "if_available",
    "never": "omit",
}
FORMAT_ISO_NO_TZ_MSG = (
    "the time zone has no ID; use tz_id_display='if_available' or 'omit'"
)


_EPOCH_DT = _datetime(1970, 1, 1, tzinfo=_UTC)


def _check_epoch(ts: int, /) -> None:
    if not EPOCH_SECS_MIN <= ts <= EPOCH_SECS_MAX:
        raise ValueError(RANGE_MSG)


def _from_epoch(ts: int, tz: TimeZone) -> _datetime:
    # Before the offset lookup: a POSIX rule has no year past 9999
    _check_epoch(ts)
    return _from_epoch_offset(ts, tz.offset_for_instant(ts))


def _from_epoch_utc(ts: int) -> _datetime:
    return _from_epoch_offset(ts, 0)


def _from_epoch_offset(ts: int, offset: int) -> _datetime:
    # Both are checked: the instant can be in range while its local time is
    # not, and a negative offset can bring the local time of an instant past
    # Instant.MAX back into range.
    local_ts = ts + offset
    if not (
        EPOCH_SECS_MIN <= ts <= EPOCH_SECS_MAX
        and EPOCH_SECS_MIN <= local_ts <= EPOCH_SECS_MAX
    ):
        raise ValueError(RANGE_MSG)
    # datetime.fromtimestamp() is faster than manual arithmetic, but may fail
    # for dates outside the platform's time_t range (e.g. year 1 or year 9999
    # on 32-bit Windows). Fall back to the portable ordinal approach in that case.
    try:
        return _datetime.fromtimestamp(local_ts, _UTC).replace(
            tzinfo=mk_fixed_tzinfo(offset)
        )
    except (OSError, OverflowError, ValueError):  # pragma: no cover
        return (_EPOCH_DT + _timedelta(seconds=local_ts)).replace(
            tzinfo=mk_fixed_tzinfo(offset)
        )


def _load_offset(offset: int | TimeDelta, /) -> _timezone:
    """Read an offset; a caller that succeeds then calls
    :func:`_warn_integer_offset`, so a call that raises emits no warning."""
    if isinstance(offset, int):
        secs = offset * 3_600
    elif isinstance(offset, TimeDelta):
        if offset._total_ns % 1_000_000_000:
            raise ValueError("offset must be a whole number of seconds")
        secs = offset._total_ns // 1_000_000_000
    else:
        raise TypeError("offset must be a TimeDelta")
    if not -86_400 < secs < 86_400:
        raise ValueError("offset must be between -24 and 24 hours")
    return mk_fixed_tzinfo(secs)


def _warn_integer_offset(
    offset: int | TimeDelta, /, *, stacklevel: int
) -> None:
    if isinstance(offset, int):
        warn_deprecated(INTEGER_OFFSET_DEPRECATION_MSG, stacklevel=stacklevel)


# Helpers that pre-compute/lookup as much as possible
_STDLIB_ONLY_FIELDS = frozenset({"tzinfo", "fold", "microsecond"})


def _pop_replace_nanos(kwargs: dict[str, Any], default: int, /) -> int:
    """The nanosecond of a ``replace()`` call, after rejecting the stdlib
    fields these types do not have."""
    check_no_kwargs(
        dict.fromkeys(kwargs.keys() & _STDLIB_ONLY_FIELDS), "replace"
    )
    return check_nanos(kwargs.pop("nanosecond", default))


def _weekday_ordinal(n: Any, /) -> int:
    """The ``n`` of the weekday finders: an integer other than zero."""
    n_int = expect_int("n", n)
    if n_int == 0:
        raise ValueError("n must not be 0")
    return n_int


def _format_date(d: _date, basic: bool) -> str:
    sep = "" if basic else "-"
    return f"{d.year:04d}{sep}{d.month:02d}{sep}{d.day:02d}"


def _format_time(
    t: _time | _datetime, ns: _Nanos, precision: str, basic: bool
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
    elif precision == "second":
        return ""
    else:
        raise invalid("unit", precision)


def _format_dt(
    dt: _datetime,
    ns: _Nanos,
    offset: int | Literal["Z", ""],
    unit: str,
    sep: Literal["T", " "],
    basic: bool,
) -> str:
    """The ISO form; ``offset`` is in seconds, ``Z``, or absent."""
    if sep not in ("T", " "):
        raise invalid("sep", sep)
    return (
        f"{_format_date(dt, basic)}{sep}"
        f"{_format_time(dt, ns, unit, basic)}"
        + (
            offset
            if isinstance(offset, str)
            else format_offset_secs(offset, basic=basic)
        )
    )


def _parse_difference_kwargs(
    total: Any,
    in_units: Any,
    round_mode: Any,
    round_increment: Any,
    /,
    *,
    date_only: bool,
) -> tuple[Any, tuple[Any, ...], RoundModeStr, int]:
    """The validated keywords of ``since()``/``until()``: ``total`` or
    ``None``, the units of ``in_units`` (empty with ``total``), and the
    rounding pair with its defaults, which ``total`` excludes."""
    if total is not UNSET:
        if in_units is not UNSET:
            raise TypeError("cannot specify both 'total' and 'in_units'")
        if round_mode is not UNSET or round_increment is not UNSET:
            raise TypeError(
                "'round_mode' and 'round_increment' cannot be used with 'total'"
            )
        unit_index(total, DATE_DELTA_UNITS if date_only else TOTAL_UNITS)
        return total, (), "trunc", 1
    elif in_units is UNSET:
        raise TypeError("must specify either 'total' or 'in_units'")
    units: tuple[Any, ...]
    if date_only:
        units = normalize_units(in_units, valid_units=DATE_DELTA_UNITS)
        round_mode, round_increment = resolve_date_rounding(
            round_mode, round_increment
        )
    else:
        units = normalize_units(in_units, valid_units=DELTA_UNITS)
        round_mode, round_increment = resolve_rounding(
            round_mode, round_increment
        )
    return None, units, round_mode, round_increment


def _date_difference(
    a: _date,
    b: _date,
    units: tuple[DateDeltaUnitStr, ...],
    round_mode: RoundModeStr,
    round_increment: int,
    sign: Literal[1, -1],
    /,
) -> dict[DateDeltaUnitStr, int]:
    results, trunc, expand = date_diff(a, b, round_increment, units, sign)
    # Round is expensive, so only do it if needed
    if round_mode != "trunc":
        smallest_unit = units[-1]
        trunc_date = resolve_leap_day(trunc)
        expand_date = resolve_leap_day(expand)
        if rounds_up(
            round_mode,
            abs((a - trunc_date).days),
            abs((expand_date - trunc_date).days),
            results[smallest_unit] // round_increment % 2 == 1,
            sign,
        ):
            # Rounded up: the larger units take the carry, and the
            # smallest stays a multiple of the increment
            return _date_difference(
                expand_date, b, units, "trunc", round_increment, sign
            )
    return results


def _plain_since(
    self: PlainDateTime,
    other: PlainDateTime,
    /,
    *,
    flip: bool,
    total: DeltaTotalUnitStr,
    in_units: Sequence[DeltaUnitStr],
    round_mode: RoundModeStr,
    round_increment: int,
    naive_arithmetic_ok: bool,
) -> ItemizedDelta | float:
    """``since()``/``until()`` of PlainDateTime: every day is 24 hours.
    Validates everything, then warns once for exact units in the result."""
    if not isinstance(other, PlainDateTime):
        raise TypeError(
            f"{'until' if flip else 'since'}() argument must be a PlainDateTime"
        )
    total, units, round_mode, round_increment = _parse_difference_kwargs(
        total, in_units, round_mode, round_increment, date_only=False
    )
    a, b = (other, self) if flip else (self, other)
    exact_output = (
        total in EXACT_TOTAL_UNITS
        if total is not None
        else units[-1] not in DATE_DELTA_UNITS
    )
    if exact_output and not naive_arithmetic_ok:
        warn(PLAIN_DIFF_UNAWARE_MSG, NaiveArithmeticWarning, stacklevel=3)
    return _plain_difference(a, b, total, units, round_mode, round_increment)


def _plain_difference(
    a: PlainDateTime,
    b: PlainDateTime,
    total: DeltaTotalUnitStr | None,
    units: tuple[DeltaUnitStr, ...],
    round_mode: RoundModeStr,
    round_increment: int,
    /,
) -> ItemizedDelta | float:
    """The validated difference of two local datetimes, which
    OffsetDateTime shares for two values at the same offset. Every day is
    24 hours, so it is the zoned difference in UTC; that reference also
    keeps ``TimeDelta.total()`` from warning a second time."""
    return _zoned_difference(
        a._assume_tz("UTC", UNSET)[0],
        b._assume_tz("UTC", UNSET)[0],
        total,
        units,
        round_mode,
        round_increment,
    )


def _offset_since(
    self: OffsetDateTime,
    other: OffsetDateTime,
    /,
    *,
    flip: bool,
    total: DeltaTotalUnitStr,
    in_units: Sequence[DeltaUnitStr],
    round_mode: RoundModeStr,
    round_increment: int,
    stale_offset_ok: bool,
) -> ItemizedDelta | float:
    """``since()``/``until()`` of OffsetDateTime: the local difference of
    two values at the same offset, otherwise exact units of the instants.
    Calendar units require the same offset; an exact remainder after them
    is computed with that offset held fixed, which warns."""
    if not isinstance(other, OffsetDateTime):
        raise TypeError(
            f"{'until' if flip else 'since'}() argument must be an OffsetDateTime"
        )
    total, units, round_mode, round_increment = _parse_difference_kwargs(
        total, in_units, round_mode, round_increment, date_only=False
    )
    a, b = (other, self) if flip else (self, other)
    same_offset = self.offset == other.offset
    if total is not None:
        calendar_output = total in DATE_DELTA_UNITS
        # The fraction after the whole units is a remainder.
        exact_remainder = calendar_output
    else:
        calendar_output = units[0] in DATE_DELTA_UNITS
        exact_remainder = calendar_output and units[-1] not in DATE_DELTA_UNITS
    if calendar_output and not same_offset:
        raise ValueError(
            "calendar units require the same offset, got "
            f"{format_offset_secs(self._current_offset_secs(), basic=False)}"
            " and "
            f"{format_offset_secs(other._current_offset_secs(), basic=False)}"
        )
    if exact_remainder and not stale_offset_ok:
        warn(OFFSET_DIFFERENCE_STALE_MSG, StaleOffsetWarning, stacklevel=3)

    if same_offset:
        return _plain_difference(
            a.to_plain(),
            b.to_plain(),
            total,
            units,
            round_mode,
            round_increment,
        )
    diff = a._subtract_operator(b)
    if total is not None:
        return diff.total(total)
    sign: Sign = 1 if diff._total_ns >= 0 else -1
    result = diff._in_exact_units(
        units,
        round_increment=round_increment,
        round_mode=round_mode,
    )
    return ItemizedDelta._from_signed(
        sign if any(result.values()) else 0, **result
    )


def _zoned_since(
    self: ZonedDateTime,
    other: ZonedDateTime,
    /,
    *,
    flip: bool,
    total: DeltaTotalUnitStr,
    in_units: Sequence[DeltaUnitStr],
    round_mode: RoundModeStr,
    round_increment: int,
) -> ItemizedDelta | float:
    """``since()``/``until()`` of ZonedDateTime. Calendar units require the
    same time zone."""
    if not isinstance(other, ZonedDateTime):
        raise TypeError(
            f"{'until' if flip else 'since'}() argument must be a ZonedDateTime"
        )
    total, units, round_mode, round_increment = _parse_difference_kwargs(
        total, in_units, round_mode, round_increment, date_only=False
    )
    a, b = (other, self) if flip else (self, other)
    calendar_output = (
        total in DATE_DELTA_UNITS
        if total is not None
        else units[0] in DATE_DELTA_UNITS
    )
    if calendar_output and self.tz_id != other.tz_id:
        raise ValueError(
            "calendar units require the same time zone, got "
            f"{self.tz_id!r} and {other.tz_id!r}"
        )
    return _zoned_difference(a, b, total, units, round_mode, round_increment)


def _zoned_difference(
    a: ZonedDateTime,
    b: ZonedDateTime,
    total: DeltaTotalUnitStr | None,
    units: tuple[DeltaUnitStr, ...],
    round_mode: RoundModeStr,
    round_increment: int,
    /,
) -> ItemizedDelta | float:
    if total is not None:
        return (a - b).total(total, relative_to=b)
    sign: Literal[1, -1] = 1 if a >= b else -1
    result = _zoned_difference_in_units(
        a, b, units, round_mode, round_increment, sign
    )
    return ItemizedDelta._from_signed(
        sign if any(result.values()) else 0, **result
    )


def _zoned_target_date(
    a: ZonedDateTime, b: ZonedDateTime, sign: Literal[1, -1], /
) -> Date:
    """The date on which ``b`` comes closest to ``a`` without passing it:
    the exact remainder then has the sign of the difference.

    It is usually the date of ``a`` or the one next to it. A gap of a day
    or more (Samoa, 2011) steps further away, and a fold across midnight
    (St. John's, 2010) steps past the date of ``a``: past a repeated
    midnight, the second pass of the evening before lies in the day that
    has already started.
    """

    def past(shifted: ZonedDateTime) -> bool:
        return shifted > a if sign == 1 else shifted < a

    target_date = a.date()
    shifted = b._with_date(target_date)
    if past(shifted):
        target_date = target_date._add_days(-sign)
        while past(b._with_date(target_date)):
            target_date = target_date._add_days(-sign)
    else:
        while True:
            try:
                next_date = target_date._add_days(sign)
            except ValueError:  # a date past the range is past ``a`` too
                break
            next_shifted = b._with_date(next_date)
            # A skipped day resolves to the same time as the next
            if past(next_shifted) or next_shifted == shifted:
                break
            target_date, shifted = next_date, next_shifted
    return target_date


def _zoned_difference_in_units(
    a: ZonedDateTime,
    b: ZonedDateTime,
    units: tuple[DeltaUnitStr, ...],
    round_mode: RoundModeStr,
    round_increment: int,
    sign: Literal[1, -1],
    /,
) -> dict[DeltaUnitStr, int]:
    cal_units, exact_units = _split_calendar_and_exact_units(units)
    target_date = _zoned_target_date(a, b, sign)
    cal_results, trunc_date, expand_date = date_diff(
        target_date._py_date,
        b._py_dt.date(),
        # Rounding only applies to the smallest unit.
        # Thus if there are any exact units, calendar units aren't rounded.
        1 if exact_units else round_increment,
        cal_units,
        sign,
    )
    trunc = b._with_date(Date._from_py_unchecked(resolve_leap_day(trunc_date)))
    expand = b._with_date(
        Date._from_py_unchecked(resolve_leap_day(expand_date))
    )

    # Rounding is very different for exact units than calendar units
    smallest_unit = units[-1]
    result = cast(dict[DeltaUnitStr, int], cal_results)
    # Where rounding ends up when it moves away from the truncated value
    rounded_up: ZonedDateTime | None = None
    if exact_units:
        exact_results = (a - trunc)._in_exact_units(
            exact_units,
            round_increment=round_increment,
            round_mode=round_mode,
        )
        result.update(exact_results)  # type: ignore[arg-type]
        if cal_units and round_mode != "trunc":
            endpoint = trunc + TimeDelta._from_nanos_unchecked(
                _exact_total_ns(exact_results, sign)
            )
            if endpoint != a and (endpoint > a) == (sign == 1):
                rounded_up = endpoint
    # Round is expensive, so only do it if needed
    elif round_mode != "trunc":
        span = abs((expand - trunc)._total_ns)
        # A skipped day can make the two endpoints coincide. The truncated
        # value is then already rounded.
        if span and rounds_up(
            round_mode,
            abs((a - trunc)._total_ns),
            span,
            result[smallest_unit] // round_increment % 2 == 1,
            sign,
        ):
            rounded_up = expand

    if rounded_up is not None:
        # The larger units take the carry
        return _zoned_difference_in_units(
            rounded_up, b, units, "trunc", round_increment, sign
        )
    return result


def _exact_total_ns(
    values: Mapping[ExactDeltaUnitStr, int], sign: Sign
) -> int:
    return sign * sum(NS_PER_UNIT_PLURAL[u] * v for u, v in values.items())


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
def _base_fields(obj: Any, base: type, names: tuple[str, ...], /) -> list[Any]:
    """Read fields through the stdlib base type, leaving a subclass's
    overrides unread: the "Stdlib overloads" rule."""
    return [getattr(base, n).__get__(obj) for n in names]


_DATETIME_FIELDS = (
    "year",
    "month",
    "day",
    "hour",
    "minute",
    "second",
    "microsecond",
    "tzinfo",
)


def _strip_subclasses(dt: _datetime, /) -> _datetime:
    if type(dt) is _datetime:
        return dt
    return _datetime(
        *_base_fields(dt, _datetime, _DATETIME_FIELDS),
        fold=_datetime.fold.__get__(dt),
    )


Instant.MIN = Instant._from_py_unchecked(
    _datetime.min.replace(tzinfo=_UTC),
    0,
)
Instant.MAX = Instant._from_py_unchecked(
    _datetime.max.replace(tzinfo=_UTC, microsecond=0),
    _MAX_SUBSEC_NANOS,
)
PlainDateTime.MIN = PlainDateTime._from_py_unchecked(_datetime.min, 0)
PlainDateTime.MAX = PlainDateTime._from_py_unchecked(
    _datetime.max.replace(microsecond=0), _MAX_SUBSEC_NANOS
)


def hours(i: float, /) -> TimeDelta:
    """Create a :class:`TimeDelta` with the given number of hours.
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
        return inst.timestamp(unit="nanosecond")


def _patch_time_keep_ticking(inst: Instant) -> None:
    global time_ns

    patched_at = _physical_time_ns()

    def time_ns() -> int:
        return (
            inst.timestamp(unit="nanosecond")
            + _physical_time_ns()
            - patched_at
        )


def _unpatch_time() -> None:
    global time_ns

    time_ns = _physical_time_ns


# This alias exists because we don't want to expose the _ExactTime abstract class
# in the public API, but we do want to use it in type annotations.
_ExactTimeAlias = Instant | OffsetDateTime | ZonedDateTime

# Itemized deltas are implemented in the dedicated pure-Python module.
ItemizedDateDelta = _ideltas.ItemizedDateDelta
ItemizedDelta = _ideltas.ItemizedDelta
_unpkl_iddelta = _ideltas._unpkl_iddelta
_unpkl_idelta = _ideltas._unpkl_idelta
AnyDelta: Any = TimeDelta | ItemizedDelta | ItemizedDateDelta

# We expose the public members in the root of the module.
# For clarity, we remove the "_pywhenever" part from the names,
# since this is an implementation detail.
# This is important for usability, as users would otherwise
# be directed to an internal module they shouldn't use directly,
# also because these internal modules aren't available in the Rust version!
# This does mess up sphinx autodoc's introspection a bit, so we fix that below.
# see https://github.com/sphinx-doc/sphinx/issues/3673
if not SPHINX_RUNNING:  # pragma: no branch
    _ftype = type(_unpkl_date)
    for _name in __all__:
        _member = globals()[_name]
        if isinstance(_member, (type, _ftype)) and (
            getattr(_member, "__module__", "") or ""
        ).startswith("whenever"):  # pragma: no branch
            _member.__module__ = "whenever"

# disable further subclassing
final(_Base)
final(_ExactTime)
final(_LocalTime)
final(_ExactAndLocalTime)
final(_BasicConversions)
