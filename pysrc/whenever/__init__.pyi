import enum
from abc import ABC
from contextlib import contextmanager
from datetime import (
    date as _date,
    datetime as _datetime,
    time as _time,
    timedelta as _timedelta,
)
from typing import Any, ClassVar, Iterator, Literal, TypeVar, final, overload

__all__ = [
    "Date",
    "Time",
    "Instant",
    "OffsetDateTime",
    "ZonedDateTime",
    "SystemDateTime",
    "LocalDateTime",
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
    "SkippedTime",
    "RepeatedTime",
    "InvalidOffset",
    "MONDAY",
    "TUESDAY",
    "WEDNESDAY",
    "THURSDAY",
    "FRIDAY",
    "SATURDAY",
    "SUNDAY",
]

_EXTENSION_LOADED: bool
__version__: str

@final
class Date:
    def __init__(self, year: int, month: int, day: int) -> None: ...
    MIN: ClassVar[Date]
    MAX: ClassVar[Date]
    @staticmethod
    def today_in_system_tz() -> Date: ...
    @property
    def year(self) -> int: ...
    @property
    def month(self) -> int: ...
    @property
    def day(self) -> int: ...
    def year_month(self) -> YearMonth: ...
    def month_day(self) -> MonthDay: ...
    def day_of_week(self) -> Weekday: ...
    def at(self, t: Time, /) -> LocalDateTime: ...
    def py_date(self) -> _date: ...
    @classmethod
    def from_py_date(cls, d: _date, /) -> Date: ...
    def format_common_iso(self) -> str: ...
    @classmethod
    def parse_common_iso(cls, s: str, /) -> Date: ...
    def replace(
        self, *, year: int = ..., month: int = ..., day: int = ...
    ) -> Date: ...
    @overload
    def add(
        self, *, years: int = 0, months: int = 0, weeks: int = 0, days: int = 0
    ) -> Date: ...
    @overload
    def add(self, delta: DateDelta, /) -> Date: ...
    @overload
    def subtract(
        self, *, years: int = 0, months: int = 0, weeks: int = 0, days: int = 0
    ) -> Date: ...
    @overload
    def subtract(self, delta: DateDelta, /) -> Date: ...
    def days_since(self, other: Date, /) -> int: ...
    def days_until(self, other: Date, /) -> int: ...
    def __add__(self, p: DateDelta) -> Date: ...
    @overload
    def __sub__(self, d: DateDelta) -> Date: ...
    @overload
    def __sub__(self, d: Date) -> DateDelta: ...
    def __lt__(self, other: Date) -> bool: ...
    def __le__(self, other: Date) -> bool: ...
    def __gt__(self, other: Date) -> bool: ...
    def __ge__(self, other: Date) -> bool: ...
    def __hash__(self) -> int: ...

@final
class YearMonth:
    def __init__(self, year: int, month: int) -> None: ...
    MIN: ClassVar[YearMonth]
    MAX: ClassVar[YearMonth]
    @property
    def year(self) -> int: ...
    @property
    def month(self) -> int: ...
    def format_common_iso(self) -> str: ...
    @classmethod
    def parse_common_iso(cls, s: str, /) -> YearMonth: ...
    def replace(self, *, year: int = ..., month: int = ...) -> YearMonth: ...
    def on_day(self, day: int, /) -> Date: ...
    def __lt__(self, other: YearMonth) -> bool: ...
    def __le__(self, other: YearMonth) -> bool: ...
    def __gt__(self, other: YearMonth) -> bool: ...
    def __ge__(self, other: YearMonth) -> bool: ...
    def __hash__(self) -> int: ...

@final
class MonthDay:
    def __init__(self, month: int, day: int) -> None: ...
    MIN: ClassVar[MonthDay]
    MAX: ClassVar[MonthDay]
    @property
    def month(self) -> int: ...
    @property
    def day(self) -> int: ...
    def format_common_iso(self) -> str: ...
    @classmethod
    def parse_common_iso(cls, s: str, /) -> MonthDay: ...
    def replace(self, *, month: int = ..., day: int = ...) -> MonthDay: ...
    def in_year(self, year: int, /) -> Date: ...
    def is_leap(self) -> bool: ...
    def __lt__(self, other: MonthDay) -> bool: ...
    def __le__(self, other: MonthDay) -> bool: ...
    def __gt__(self, other: MonthDay) -> bool: ...
    def __ge__(self, other: MonthDay) -> bool: ...
    def __hash__(self) -> int: ...

@final
class Time:
    def __init__(
        self,
        hour: int = 0,
        minute: int = 0,
        second: int = 0,
        *,
        nanosecond: int = 0,
    ) -> None: ...
    MIDNIGHT: ClassVar[Time]
    NOON: ClassVar[Time]
    MAX: ClassVar[Time]
    @property
    def hour(self) -> int: ...
    @property
    def minute(self) -> int: ...
    @property
    def second(self) -> int: ...
    @property
    def nanosecond(self) -> int: ...
    def on(self, d: Date, /) -> LocalDateTime: ...
    def py_time(self) -> _time: ...
    @classmethod
    def from_py_time(cls, t: _time, /) -> Time: ...
    def format_common_iso(self) -> str: ...
    @classmethod
    def parse_common_iso(cls, s: str, /) -> Time: ...
    def replace(
        self,
        *,
        hour: int = ...,
        minute: int = ...,
        second: int = ...,
        nanosecond: int = ...,
    ) -> Time: ...
    def round(
        self,
        unit: Literal[
            "hour",
            "minute",
            "second",
            "millisecond",
            "microsecond",
            "nanosecond",
        ] = "second",
        increment: int = 1,
        mode: Literal[
            "ceil", "floor", "half_ceil", "half_floor", "half_even"
        ] = "half_even",
    ) -> Time: ...
    def __lt__(self, other: Time) -> bool: ...
    def __le__(self, other: Time) -> bool: ...
    def __gt__(self, other: Time) -> bool: ...
    def __ge__(self, other: Time) -> bool: ...
    def __hash__(self) -> int: ...

@final
class TimeDelta:
    def __init__(
        self,
        *,
        hours: float = 0,
        minutes: float = 0,
        seconds: float = 0,
        milliseconds: float = 0,
        microseconds: float = 0,
        nanoseconds: int = 0,
    ) -> None: ...
    ZERO: ClassVar[TimeDelta]
    MAX: ClassVar[TimeDelta]
    MIN: ClassVar[TimeDelta]
    def in_days_of_24h(self) -> float: ...
    def in_hours(self) -> float: ...
    def in_minutes(self) -> float: ...
    def in_seconds(self) -> float: ...
    def in_milliseconds(self) -> float: ...
    def in_microseconds(self) -> float: ...
    def in_nanoseconds(self) -> int: ...
    def in_hrs_mins_secs_nanos(self) -> tuple[int, int, int, int]: ...
    def py_timedelta(self) -> _timedelta: ...
    @classmethod
    def from_py_timedelta(cls, td: _timedelta, /) -> TimeDelta: ...
    def format_common_iso(self) -> str: ...
    @classmethod
    def parse_common_iso(cls, s: str, /) -> TimeDelta: ...
    def round(
        self,
        unit: Literal[
            "hour",
            "minute",
            "second",
            "millisecond",
            "microsecond",
            "nanosecond",
        ] = "second",
        increment: int = 1,
        mode: Literal[
            "ceil", "floor", "half_ceil", "half_floor", "half_even"
        ] = "half_even",
    ) -> TimeDelta: ...
    def __hash__(self) -> int: ...
    def __lt__(self, other: TimeDelta) -> bool: ...
    def __le__(self, other: TimeDelta) -> bool: ...
    def __gt__(self, other: TimeDelta) -> bool: ...
    def __ge__(self, other: TimeDelta) -> bool: ...
    def __bool__(self) -> bool: ...
    def __add__(self, other: TimeDelta) -> TimeDelta: ...
    def __sub__(self, other: TimeDelta) -> TimeDelta: ...
    def __mul__(self, other: float) -> TimeDelta: ...
    def __rmul__(self, other: float) -> TimeDelta: ...
    def __neg__(self) -> TimeDelta: ...
    def __pos__(self) -> TimeDelta: ...
    @overload
    def __truediv__(self, other: float) -> TimeDelta: ...
    @overload
    def __truediv__(self, other: TimeDelta) -> float: ...
    def __floordiv__(self, other: TimeDelta) -> int: ...
    def __mod__(self, other: TimeDelta) -> TimeDelta: ...
    def __abs__(self) -> TimeDelta: ...

@final
class DateDelta:
    ZERO: ClassVar[DateDelta]
    def __init__(
        self, *, years: int = 0, months: int = 0, weeks: int = 0, days: int = 0
    ) -> None: ...
    def in_months_days(self) -> tuple[int, int]: ...
    def in_years_months_days(self) -> tuple[int, int, int]: ...
    def format_common_iso(self) -> str: ...
    @classmethod
    def parse_common_iso(cls, s: str, /) -> DateDelta: ...
    def __hash__(self) -> int: ...
    def __bool__(self) -> bool: ...
    def __neg__(self) -> DateDelta: ...
    def __pos__(self) -> DateDelta: ...
    def __mul__(self, other: int) -> DateDelta: ...
    def __rmul__(self, other: int) -> DateDelta: ...
    @overload
    def __add__(self, other: DateDelta) -> DateDelta: ...
    @overload
    def __add__(self, other: TimeDelta) -> DateTimeDelta: ...
    def __radd__(self, other: TimeDelta) -> DateTimeDelta: ...
    @overload
    def __sub__(self, other: DateDelta) -> DateDelta: ...
    @overload
    def __sub__(self, other: TimeDelta) -> DateTimeDelta: ...
    def __rsub__(self, other: TimeDelta) -> DateTimeDelta: ...
    def __abs__(self) -> DateDelta: ...

@final
class DateTimeDelta:
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
    ) -> None: ...
    ZERO: ClassVar[DateTimeDelta]
    def date_part(self) -> DateDelta: ...
    def time_part(self) -> TimeDelta: ...
    def in_months_days_secs_nanos(self) -> tuple[int, int, int, int]: ...
    def format_common_iso(self) -> str: ...
    @classmethod
    def parse_common_iso(cls, s: str, /) -> DateTimeDelta: ...
    def __eq__(self, other: object) -> bool: ...
    def __hash__(self) -> int: ...
    def __bool__(self) -> bool: ...
    def __add__(self, other: Delta) -> DateTimeDelta: ...
    def __radd__(self, other: TimeDelta | DateDelta) -> DateTimeDelta: ...
    def __sub__(
        self, other: DateTimeDelta | TimeDelta | DateDelta
    ) -> DateTimeDelta: ...
    def __rsub__(self, other: TimeDelta | DateDelta) -> DateTimeDelta: ...
    def __mul__(self, other: int) -> DateTimeDelta: ...
    def __rmul__(self, other: int) -> DateTimeDelta: ...
    def __neg__(self) -> DateTimeDelta: ...
    def __pos__(self) -> DateTimeDelta: ...
    def __abs__(self) -> DateTimeDelta: ...

Delta = DateTimeDelta | TimeDelta | DateDelta

_T = TypeVar("_T")

class _KnowsLocal(ABC):
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
    def nanosecond(self) -> int: ...
    def date(self) -> Date: ...
    def time(self) -> Time: ...

class _KnowsInstant(ABC):
    def timestamp(self) -> int: ...
    def timestamp_millis(self) -> int: ...
    def timestamp_nanos(self) -> int: ...
    @overload
    def to_fixed_offset(self, /) -> OffsetDateTime: ...
    @overload
    def to_fixed_offset(
        self, offset: int | TimeDelta, /
    ) -> OffsetDateTime: ...
    def to_tz(self, tz: str, /) -> ZonedDateTime: ...
    def to_system_tz(self) -> SystemDateTime: ...
    def difference(self, other: _KnowsInstant, /) -> TimeDelta: ...
    def __lt__(self, other: _KnowsInstant) -> bool: ...
    def __le__(self, other: _KnowsInstant) -> bool: ...
    def __gt__(self, other: _KnowsInstant) -> bool: ...
    def __ge__(self, other: _KnowsInstant) -> bool: ...

class _KnowsInstantAndLocal(_KnowsInstant, _KnowsLocal, ABC):
    def instant(self) -> Instant: ...
    def local(self) -> LocalDateTime: ...
    @property
    def offset(self) -> TimeDelta: ...

@final
class Instant(_KnowsInstant):
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
    ) -> Instant: ...
    MIN: ClassVar[Instant]
    MAX: ClassVar[Instant]
    @classmethod
    def now(cls) -> Instant: ...
    @classmethod
    def from_timestamp(cls, i: int | float, /) -> Instant: ...
    @classmethod
    def from_timestamp_millis(cls, i: int, /) -> Instant: ...
    @classmethod
    def from_timestamp_nanos(cls, i: int, /) -> Instant: ...
    @classmethod
    def from_py_datetime(cls, d: _datetime, /) -> Instant: ...
    def py_datetime(self) -> _datetime: ...
    def format_rfc2822(self) -> str: ...
    @classmethod
    def parse_rfc2822(cls, s: str, /) -> Instant: ...
    def format_rfc3339(self) -> str: ...
    @classmethod
    def parse_rfc3339(cls, s: str, /) -> Instant: ...
    @classmethod
    def parse_common_iso(cls, s: str, /) -> Instant: ...
    def format_common_iso(self) -> str: ...
    def exact_eq(self, other: Instant, /) -> bool: ...
    def add(
        self,
        *,
        hours: float = 0,
        minutes: float = 0,
        seconds: float = 0,
        milliseconds: float = 0,
        microseconds: float = 0,
        nanoseconds: int = 0,
    ) -> Instant: ...
    def subtract(
        self,
        *,
        hours: float = 0,
        minutes: float = 0,
        seconds: float = 0,
        milliseconds: float = 0,
        microseconds: float = 0,
        nanoseconds: int = 0,
    ) -> Instant: ...
    def round(
        self,
        unit: Literal[
            "hour",
            "minute",
            "second",
            "millisecond",
            "microsecond",
            "nanosecond",
        ] = "second",
        increment: int = 1,
        mode: Literal[
            "ceil", "floor", "half_ceil", "half_floor", "half_even"
        ] = "half_even",
    ) -> Instant: ...
    def __add__(self, delta: TimeDelta) -> Instant: ...
    @overload
    def __sub__(self, other: _KnowsInstant) -> TimeDelta: ...
    @overload
    def __sub__(self, other: TimeDelta) -> Instant: ...

@final
class OffsetDateTime(_KnowsInstantAndLocal):
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
    ) -> None: ...
    @classmethod
    def now(
        cls, offset: int | TimeDelta, /, *, ignore_dst: Literal[True]
    ) -> OffsetDateTime: ...
    @classmethod
    def from_timestamp(
        cls,
        i: int | float,
        /,
        *,
        offset: int | TimeDelta,
        ignore_dst: Literal[True],
    ) -> OffsetDateTime: ...
    @classmethod
    def from_timestamp_millis(
        cls, i: int, /, *, offset: int | TimeDelta, ignore_dst: Literal[True]
    ) -> OffsetDateTime: ...
    @classmethod
    def from_timestamp_nanos(
        cls, i: int, /, *, offset: int | TimeDelta, ignore_dst: Literal[True]
    ) -> OffsetDateTime: ...
    @classmethod
    def from_py_datetime(cls, d: _datetime, /) -> OffsetDateTime: ...
    def py_datetime(self) -> _datetime: ...
    @classmethod
    def strptime(cls, s: str, fmt: str, /) -> OffsetDateTime: ...
    def format_rfc2822(self) -> str: ...
    @classmethod
    def parse_rfc2822(cls, s: str, /) -> OffsetDateTime: ...
    def format_common_iso(self) -> str: ...
    def format_rfc3339(self) -> str: ...
    @classmethod
    def parse_rfc3339(cls, s: str, /) -> OffsetDateTime: ...
    @classmethod
    def parse_common_iso(cls, s: str, /) -> OffsetDateTime: ...
    def exact_eq(self, other: OffsetDateTime, /) -> bool: ...
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
        offset: int | TimeDelta = ...,
        ignore_dst: Literal[True],
    ) -> OffsetDateTime: ...
    def replace_date(
        self, d: Date, /, *, ignore_dst: Literal[True]
    ) -> OffsetDateTime: ...
    def replace_time(
        self, t: Time, /, *, ignore_dst: Literal[True]
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
        ignore_dst: Literal[True],
    ) -> OffsetDateTime: ...
    @overload
    def add(
        self, d: Delta, /, ignore_dst: Literal[True]
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
        ignore_dst: Literal[True],
    ) -> OffsetDateTime: ...
    @overload
    def subtract(
        self, d: Delta, /, ignore_dst: Literal[True]
    ) -> OffsetDateTime: ...
    def round(
        self,
        unit: Literal[
            "day",
            "hour",
            "minute",
            "second",
            "millisecond",
            "microsecond",
            "nanosecond",
        ] = "second",
        increment: int = 1,
        mode: Literal[
            "ceil", "floor", "half_ceil", "half_floor", "half_even"
        ] = "half_even",
        *,
        ignore_dst: Literal[True],
    ) -> OffsetDateTime: ...
    def __sub__(self, other: _KnowsInstant) -> TimeDelta: ...

@final
class ZonedDateTime(_KnowsInstantAndLocal):
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
        disambiguate: Literal["compatible", "raise", "earlier", "later"] = ...,
    ) -> None: ...
    @property
    def tz(self) -> str: ...
    @classmethod
    def now(cls, tz: str, /) -> ZonedDateTime: ...
    @classmethod
    def from_py_datetime(cls, d: _datetime, /) -> ZonedDateTime: ...
    def py_datetime(self) -> _datetime: ...
    @classmethod
    def from_timestamp(
        cls, i: int | float, /, *, tz: str
    ) -> ZonedDateTime: ...
    @classmethod
    def from_timestamp_millis(cls, i: int, /, *, tz: str) -> ZonedDateTime: ...
    @classmethod
    def from_timestamp_nanos(cls, i: int, /, *, tz: str) -> ZonedDateTime: ...
    def format_common_iso(self) -> str: ...
    @classmethod
    def parse_common_iso(cls, s: str, /) -> ZonedDateTime: ...
    def exact_eq(self, other: ZonedDateTime, /) -> bool: ...
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
        tz: str = ...,
        disambiguate: Literal["compatible", "raise", "earlier", "later"] = ...,
    ) -> ZonedDateTime: ...
    def replace_date(
        self,
        d: Date,
        /,
        *,
        disambiguate: Literal["compatible", "raise", "earlier", "later"] = ...,
    ) -> ZonedDateTime: ...
    def replace_time(
        self,
        t: Time,
        /,
        *,
        disambiguate: Literal["compatible", "raise", "earlier", "later"] = ...,
    ) -> ZonedDateTime: ...
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
        disambiguate: Literal["compatible", "raise", "earlier", "later"] = ...,
    ) -> ZonedDateTime: ...
    # FUTURE: include this in strict stubs version
    # @overload
    # def add(
    #     self,
    #     *,
    #     hours: float = 0,
    #     minutes: float = 0,
    #     seconds: float = 0,
    #     milliseconds: float = 0,
    #     microseconds: float = 0,
    #     nanoseconds: int = 0,
    # ) -> ZonedDateTime: ...
    @overload
    def add(self, d: TimeDelta, /) -> ZonedDateTime: ...
    @overload
    def add(
        self,
        d: DateDelta | DateTimeDelta,
        /,
        *,
        disambiguate: Literal["compatible", "raise", "earlier", "later"] = ...,
    ) -> ZonedDateTime: ...
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
        disambiguate: Literal["compatible", "raise", "earlier", "later"] = ...,
    ) -> ZonedDateTime: ...
    # FUTURE: include this in strict stubs version
    # @overload
    # def subtract(
    #     self,
    #     *,
    #     hours: float = 0,
    #     minutes: float = 0,
    #     seconds: float = 0,
    #     milliseconds: float = 0,
    #     microseconds: float = 0,
    #     nanoseconds: int = 0,
    # ) -> ZonedDateTime: ...
    @overload
    def subtract(self, d: TimeDelta, /) -> ZonedDateTime: ...
    @overload
    def subtract(
        self,
        d: DateDelta | DateTimeDelta,
        /,
        *,
        disambiguate: Literal["compatible", "raise", "earlier", "later"] = ...,
    ) -> ZonedDateTime: ...
    def is_ambiguous(self) -> bool: ...
    def hours_in_day(self) -> float: ...
    def start_of_day(self) -> ZonedDateTime: ...
    def round(
        self,
        unit: Literal[
            "day",
            "hour",
            "minute",
            "second",
            "millisecond",
            "microsecond",
            "nanosecond",
        ] = "second",
        increment: int = 1,
        mode: Literal[
            "ceil", "floor", "half_ceil", "half_floor", "half_even"
        ] = "half_even",
    ) -> ZonedDateTime: ...
    # FUTURE: disable date components in strict stubs version
    def __add__(self, delta: Delta) -> ZonedDateTime: ...
    @overload
    def __sub__(self, other: _KnowsInstant) -> TimeDelta: ...
    @overload
    def __sub__(self, other: Delta) -> ZonedDateTime: ...

@final
class SystemDateTime(_KnowsInstantAndLocal):
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
        disambiguate: Literal["compatible", "raise", "earlier", "later"] = ...,
    ) -> None: ...
    @classmethod
    def now(cls) -> SystemDateTime: ...
    @classmethod
    def from_timestamp(cls, i: int | float, /) -> SystemDateTime: ...
    @classmethod
    def from_timestamp_millis(cls, i: int, /) -> SystemDateTime: ...
    @classmethod
    def from_timestamp_nanos(cls, i: int, /) -> SystemDateTime: ...
    @classmethod
    def from_py_datetime(cls, d: _datetime, /) -> SystemDateTime: ...
    def py_datetime(self) -> _datetime: ...
    @classmethod
    def parse_common_iso(cls, s: str, /) -> SystemDateTime: ...
    def format_common_iso(self) -> str: ...
    def exact_eq(self, other: SystemDateTime, /) -> bool: ...
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
        disambiguate: Literal["compatible", "raise", "earlier", "later"] = ...,
    ) -> SystemDateTime: ...
    def replace_date(
        self,
        d: Date,
        /,
        *,
        disambiguate: Literal["compatible", "raise", "earlier", "later"] = ...,
    ) -> SystemDateTime: ...
    def replace_time(
        self,
        t: Time,
        /,
        *,
        disambiguate: Literal["compatible", "raise", "earlier", "later"] = ...,
    ) -> SystemDateTime: ...
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
        disambiguate: Literal["compatible", "raise", "earlier", "later"] = ...,
    ) -> SystemDateTime: ...
    # FUTURE: include this in strict stubs version
    # @overload
    # def add(
    #     self,
    #     *,
    #     hours: float = 0,
    #     minutes: float = 0,
    #     seconds: float = 0,
    #     milliseconds: float = 0,
    #     microseconds: float = 0,
    #     nanoseconds: int = 0,
    # ) -> SystemDateTime: ...
    @overload
    def add(self, d: TimeDelta, /) -> SystemDateTime: ...
    @overload
    def add(
        self,
        d: DateDelta | DateTimeDelta,
        /,
        *,
        disambiguate: Literal["compatible", "raise", "earlier", "later"] = ...,
    ) -> SystemDateTime: ...
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
        disambiguate: Literal["compatible", "raise", "earlier", "later"] = ...,
    ) -> SystemDateTime: ...
    # FUTURE: include this in strict stubs version
    # @overload
    # def subtract(
    #     self,
    #     *,
    #     hours: float = 0,
    #     minutes: float = 0,
    #     seconds: float = 0,
    #     milliseconds: float = 0,
    #     microseconds: float = 0,
    #     nanoseconds: int = 0,
    # ) -> SystemDateTime: ...
    @overload
    def subtract(self, d: TimeDelta, /) -> SystemDateTime: ...
    @overload
    def subtract(
        self,
        d: DateDelta | DateTimeDelta,
        /,
        *,
        disambiguate: Literal["compatible", "raise", "earlier", "later"] = ...,
    ) -> SystemDateTime: ...
    def is_ambiguous(self) -> bool: ...
    def hours_in_day(self) -> float: ...
    def start_of_day(self) -> ZonedDateTime: ...
    def round(
        self,
        unit: Literal[
            "day",
            "hour",
            "minute",
            "second",
            "millisecond",
            "microsecond",
            "nanosecond",
        ] = "second",
        increment: int = 1,
        mode: Literal[
            "ceil", "floor", "half_ceil", "half_floor", "half_even"
        ] = "half_even",
    ) -> SystemDateTime: ...
    # FUTURE: disable date components in strict stubs version
    def __add__(self, delta: Delta) -> SystemDateTime: ...
    @overload
    def __sub__(self, other: _KnowsInstant) -> TimeDelta: ...
    @overload
    def __sub__(self, other: Delta) -> SystemDateTime: ...

@final
class LocalDateTime(_KnowsLocal):
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
    MIN: ClassVar[LocalDateTime]
    MAX: ClassVar[LocalDateTime]
    def assume_utc(self) -> Instant: ...
    def assume_fixed_offset(
        self, offset: int | TimeDelta, /
    ) -> OffsetDateTime: ...
    def assume_tz(
        self,
        tz: str,
        /,
        *,
        disambiguate: Literal["compatible", "raise", "earlier", "later"] = ...,
    ) -> ZonedDateTime: ...
    def assume_system_tz(
        self,
        *,
        disambiguate: Literal["compatible", "raise", "earlier", "later"] = ...,
    ) -> SystemDateTime: ...
    @classmethod
    def from_py_datetime(cls, d: _datetime, /) -> LocalDateTime: ...
    def py_datetime(self) -> _datetime: ...
    @classmethod
    def parse_common_iso(cls, s: str, /) -> LocalDateTime: ...
    def format_common_iso(self) -> str: ...
    @classmethod
    def strptime(cls, s: str, fmt: str, /) -> LocalDateTime: ...
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
    ) -> LocalDateTime: ...
    def replace_date(self, d: Date, /) -> LocalDateTime: ...
    def replace_time(self, t: Time, /) -> LocalDateTime: ...
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
        ignore_dst: Literal[True],
    ) -> LocalDateTime: ...
    @overload
    def add(
        self, *, years: int = 0, months: int = 0, weeks: int = 0, days: int = 0
    ) -> LocalDateTime: ...
    @overload
    def add(self, d: DateDelta, /) -> LocalDateTime: ...
    @overload
    def add(
        self, d: TimeDelta | DateTimeDelta, /, *, ignore_dst: Literal[True]
    ) -> LocalDateTime: ...
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
        ignore_dst: Literal[True],
    ) -> LocalDateTime: ...
    @overload
    def subtract(
        self, *, years: int = 0, months: int = 0, weeks: int = 0, days: int = 0
    ) -> LocalDateTime: ...
    @overload
    def subtract(self, d: DateDelta, /) -> LocalDateTime: ...
    @overload
    def subtract(
        self, d: TimeDelta | DateTimeDelta, /, *, ignore_dst: Literal[True]
    ) -> LocalDateTime: ...
    def difference(
        self, other: LocalDateTime, /, *, ignore_dst: Literal[True]
    ) -> TimeDelta: ...
    def round(
        self,
        unit: Literal[
            "day",
            "hour",
            "minute",
            "second",
            "millisecond",
            "microsecond",
            "nanosecond",
        ] = "second",
        increment: int = 1,
        mode: Literal[
            "ceil", "floor", "half_ceil", "half_floor", "half_even"
        ] = "half_even",
    ) -> LocalDateTime: ...
    def __add__(self, delta: DateDelta) -> LocalDateTime: ...
    def __sub__(self, other: DateDelta) -> LocalDateTime: ...
    def __lt__(self, other: LocalDateTime) -> bool: ...
    def __le__(self, other: LocalDateTime) -> bool: ...
    def __gt__(self, other: LocalDateTime) -> bool: ...
    def __ge__(self, other: LocalDateTime) -> bool: ...

@final
class RepeatedTime(Exception): ...

@final
class SkippedTime(Exception): ...

@final
class InvalidOffset(ValueError): ...

@final
class ImplicitlyIgnoringDST(TypeError): ...

class Weekday(enum.Enum):
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

def years(i: int, /) -> DateDelta: ...
def months(i: int, /) -> DateDelta: ...
def weeks(i: int, /) -> DateDelta: ...
def days(i: int, /) -> DateDelta: ...
def hours(i: float, /) -> TimeDelta: ...
def minutes(i: float, /) -> TimeDelta: ...
def seconds(i: float, /) -> TimeDelta: ...
def milliseconds(i: float, /) -> TimeDelta: ...
def microseconds(i: float, /) -> TimeDelta: ...
def nanoseconds(i: int, /) -> TimeDelta: ...

class _TimePatch:
    def shift(self, *args: Any, **kwargs: Any) -> None: ...

@contextmanager
def patch_current_time(
    i: _KnowsInstant, /, *, keep_ticking: bool
) -> Iterator[_TimePatch]: ...
