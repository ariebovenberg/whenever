import sys
from datetime import (
    date as _date,
    datetime as _datetime,
    time as _time,
    timedelta as _timedelta,
    timezone as _timezone,
)
from typing import Literal, NoReturn, cast

from ._common import (
    DUMMY_LEAP_YEAR,
    UTC,
    Nanos,
    check_utc_bounds,
    mk_fixed_tzinfo,
)
from ._tz import SafeTzId, TimeZone, get_tz, resolve_ambiguity, validate_tzid


class InvalidOffsetError(ValueError):
    """A string has an invalid offset for the given zone"""


def _parse_err(s: str) -> NoReturn:
    raise ValueError(f"Invalid format: {s!r}") from None


def _parse_nanos(s: str) -> Nanos:
    if len(s) > 9 or not s.isdigit() or not s.isascii():
        raise ValueError("Invalid decimals")
    return int(s.ljust(9, "0"))


def _split_nextchar(
    s: str, chars: str, start: int = 0, end: int = -1
) -> tuple[str, str | None, str]:
    for c in chars:
        if (idx := s.find(c, start, end)) != -1:
            return (s[:idx], c, s[idx + 1 :])
    return (s, None, "")


_is_sep = " Tt".__contains__


def _offset_from_iso(s: str) -> int:
    minutes = 0
    seconds = 0
    if len(s) == 5 and s[2] == ":" and s[3] < "6":  # most common: HH:MM
        hours = int(s[:2])
        minutes = int(s[3:])
    elif len(s) == 4 and s[2] < "6":  # HHMM
        hours = int(s[:2])
        minutes = int(s[2:])
    elif len(s) == 2:  # HH
        hours = int(s)
    elif (
        len(s) == 8
        and s[2] == ":"
        and s[5] == ":"
        and s[3] < "6"
        and s[6] < "6"
    ):  # HH:MM:SS
        hours = int(s[:2])
        minutes = int(s[3:5])
        seconds = int(s[6:])
    elif len(s) == 6 and s[2] < "6" and s[4] < "6":  # HHMMSS
        hours = int(s[:2])
        minutes = int(s[2:4])
        seconds = int(s[4:])
    else:
        raise ValueError("Invalid offset format")
    return hours * 3600 + minutes * 60 + seconds


def datetime_from_iso(s: str) -> tuple[_datetime, Nanos]:
    if len(s) < 11 or "W" in s or not s.isascii():
        _parse_err(s)

    # OPTIMIZE: the happy path can be faster
    try:
        if _is_sep(s[10]):  # date in extended format
            rest, date = s[11:], _date.fromisoformat(s[:10])
        elif _is_sep(s[8]):  # date in basic format
            rest, date = s[9:], __date_from_iso_basic(s[:8])
        else:
            _parse_err(s)
        time, nanos = _time_from_iso(rest)
    except ValueError:
        _parse_err(s)

    return _datetime.combine(date, time), nanos


def offset_dt_from_iso(s: str) -> tuple[_datetime, Nanos]:
    if len(s) < 11 or "W" in s[:11] or not s.isascii():
        _parse_err(s)

    try:
        if _is_sep(s[10]):  # date in extended format
            rest, date = s[11:], _date.fromisoformat(s[:10])
        elif _is_sep(s[8]):  # date in basic format
            rest, date = s[9:], __date_from_iso_basic(s[:8])
        else:
            _parse_err(s)
        time, nanos, offset, _ = _time_offset_tz_from_iso(rest)
        if offset is None:
            raise ValueError("Missing offset")
        elif offset == "Z":
            tzinfo = UTC
        else:
            assert isinstance(offset, _timezone)
            tzinfo = offset

        return (
            check_utc_bounds(_datetime.combine(date, time, tzinfo)),
            nanos,
        )
    except ValueError:
        _parse_err(s)


def zdt_from_iso(s: str) -> tuple[_datetime, Nanos, TimeZone]:
    if len(s) < 11 or "W" in s[:11] or not s.isascii():
        _parse_err(s)

    try:
        if _is_sep(s[10]):  # date in extended format
            rest, date = s[11:], _date.fromisoformat(s[:10])
        elif _is_sep(s[8]):  # date in basic format
            rest, date = s[9:], __date_from_iso_basic(s[:8])
        else:
            _parse_err(s)
        time, nanos, offset, tzid = _time_offset_tz_from_iso(rest)
    except ValueError:
        _parse_err(s)

    if tzid is None:
        _parse_err(s)

    tz = get_tz(tzid)

    if offset is None:
        dt = resolve_ambiguity(_datetime.combine(date, time), tz, "compatible")
    elif offset == "Z":
        utc_dt = _datetime.combine(date, time, UTC)
        dt = utc_dt.astimezone(
            mk_fixed_tzinfo(tz.offset_for_instant(int(utc_dt.timestamp())))
        )
    else:
        assert isinstance(offset, _timezone)
        dt = _datetime.combine(date, time, offset)
        # Raise an exception if instant is out of range
        dt.astimezone(UTC)
        # Ensure the offset is correct for the given instant
        expected_offset = tz.offset_for_instant(int(dt.timestamp()))
        # NOTE: mypy doesn't know utcoffset() can never return None here
        if dt.utcoffset().total_seconds() != expected_offset:  # type: ignore[union-attr]
            raise InvalidOffsetError()

    return (dt, nanos, tz)


def _time_from_iso(s_orig: str) -> tuple[_time, Nanos]:
    s, sep, nanos_raw = _split_nextchar(s_orig, ".,", 6, 9)

    try:
        return (
            __time_from_iso_nofrac(s),
            _parse_nanos(nanos_raw) if sep else 0,
        )
    except ValueError:
        _parse_err(s_orig)


# Parse the time, UTC offset, and timezone ID
def _time_offset_tz_from_iso(
    s: str,
) -> tuple[_time, Nanos, _timezone | Literal["Z"] | None, SafeTzId | None]:
    # ditch the bracketted timezone (if present)
    if s.endswith("]"):
        # NOTE: sorry for the unicode escape sequences. Literal brackets
        # break my LSP's indentation detection. \x5b is open bracket '['
        s, tz_raw = s[:-1].rsplit("\x5b", 1)
        tz = validate_tzid(tz_raw)
    else:
        tz = None

    # determine the offset
    offset: Literal["Z"] | _timezone | None
    if s.endswith(("Z", "z")):
        s_time = s[:-1]
        offset = "Z"
    else:
        s_time, sign, s_offset = _split_nextchar(s, "+-")
        if sign is None:
            offset = None
        else:
            offset_secs = _offset_from_iso(s_offset)
            if sign == "-":
                offset_secs = -offset_secs
            offset = mk_fixed_tzinfo(offset_secs)

    time, nanos = _time_from_iso(s_time)
    return (time, nanos, offset, tz)


def yearmonth_from_iso(s: str) -> _date:
    if not s.isascii():
        _parse_err(s)
    try:
        if len(s) == 7 and s[4] == "-":
            year, month = int(s[:4]), int(s[5:])
        elif len(s) == 6:
            year, month = int(s[:4]), int(s[4:])
        else:
            _parse_err(s)
        return _date(year, month, 1)
    except ValueError:
        _parse_err(s)


def monthday_from_iso(s: str) -> _date:
    if not (s.startswith("--") and s.isascii()):
        _parse_err(s)
    try:
        if len(s) == 7 and s[4] == "-":
            month, day = int(s[2:4]), int(s[5:])
        elif len(s) == 6:
            month, day = int(s[2:4]), int(s[4:])
        else:
            _parse_err(s)
        return _date(DUMMY_LEAP_YEAR, month, day)
    except ValueError:
        _parse_err(s)


# The ISO parsing functions were improved in Python 3.11,
# so we use them if available.
if sys.version_info >= (3, 11):

    __date_from_iso_basic = _date.fromisoformat

    def __time_from_iso_nofrac(s: str) -> _time:
        # Compensate for a bug in CPython where times like "12:34:56:78" are
        # accepted as valid times. This is only fixed in Python 3.14+
        if s.count(":") > 2:
            raise ValueError()
        if all(map("0123456789:".__contains__, s)):
            return _time.fromisoformat(s)
        raise ValueError()

    def date_from_iso(s: str) -> _date:
        # prevent isoformat from parsing stuff we don't want it to
        if "W" in s or not s.isascii():
            _parse_err(s)
        try:
            return _date.fromisoformat(s)
        except ValueError:
            _parse_err(s)

else:  # pragma: no cover

    def __date_from_iso_basic(s: str, /) -> _date:
        return _date.fromisoformat(s[:4] + "-" + s[4:6] + "-" + s[6:8])

    def __time_from_iso_nofrac(s: str) -> _time:
        # Compensate for the fact that Python's isoformat
        # doesn't support basic ISO 8601 formats
        if len(s) == 4:
            s = s[:2] + ":" + s[2:]
        elif len(s) == 6:
            s = s[:2] + ":" + s[2:4] + ":" + s[4:]
        if all(map("0123456789:".__contains__, s)):
            return _time.fromisoformat(s)
        raise ValueError()

    def date_from_iso(s: str) -> _date:
        if not s.isascii():
            _parse_err(s)
        try:
            if len(s) == 8:
                return __date_from_iso_basic(s)
            return _date.fromisoformat(s)
        except ValueError:
            _parse_err(s)


_RFC2822_WEEKDAY_TO_ISO = {
    "mon": 1,
    "tue": 2,
    "wed": 3,
    "thu": 4,
    "fri": 5,
    "sat": 6,
    "sun": 7,
}


_RFC2822_MONTH_NAMES = {
    "jan": 1,
    "feb": 2,
    "mar": 3,
    "apr": 4,
    "may": 5,
    "jun": 6,
    "jul": 7,
    "aug": 8,
    "sep": 9,
    "oct": 10,
    "nov": 11,
    "dec": 12,
}

WEEKDAY_TO_RFC2822 = [s.title() for s in _RFC2822_WEEKDAY_TO_ISO]
MONTH_TO_RFC2822 = [s.title() for s in _RFC2822_MONTH_NAMES]
MONTH_TO_RFC2822.insert(0, "")  # 1-indexed

_RFC2822_ZONES = {
    "EST": -5,
    "EDT": -4,
    "CST": -6,
    "CDT": -5,
    "MST": -7,
    "MDT": -6,
    "PST": -8,
    "PDT": -7,
    "UT": 0,
    "GMT": 0,
}


def parse_rfc2822(s: str) -> _datetime:
    # Technically, only tab, space and CRLF are allowed in RFC2822,
    # but we allow any ASCII whitespace
    if not s.isascii():
        _parse_err(s)

    # Parse the weekday
    try:
        first, second, *parts = s.split()
        if first.isdigit():
            iso_weekday = None
            parts = [first, second, *parts]
        else:
            # Case: Mon, 23 Jan
            if len(first) == 4 and first[3] == ",":
                weekday_raw = first[:3]
                parts = [second, *parts]
            # Case: Mon , 23 Jan
            elif len(first) == 3 and second == ",":
                weekday_raw = first
            # Case: Mon ,23 Jan
            elif len(first) == 3 and second.startswith(","):
                weekday_raw = first
                parts = [second[1:], *parts]
            # Case: Mon,23 Jan
            elif len(first) > 4 and first[3] == ",":
                weekday_raw = first[:3]
                parts = [first[4:], second, *parts]
            else:
                _parse_err(s)

            iso_weekday = _RFC2822_WEEKDAY_TO_ISO[weekday_raw.lower()]
    except (ValueError, KeyError):
        _parse_err(s)

    # Parse the date
    try:
        day_raw, month_raw, year_raw, *parts = parts
        if len(day_raw) > 2:
            _parse_err(s)
        day = int(day_raw)
        month = _RFC2822_MONTH_NAMES[month_raw.lower()]
        if len(year_raw) == 4:
            year = int(year_raw)
        elif len(year_raw) == 2:
            year = int(year_raw)
            if year < 50:
                year += 2000
            else:
                year += 1900
        elif len(year_raw) == 3:
            year = int(year_raw) + 1900
        else:
            _parse_err(s)
        date = _date(year, month, day)
    except (ValueError, KeyError):
        _parse_err(s)

    if iso_weekday and iso_weekday != date.isoweekday():
        _parse_err(s)

    # Parse the time
    try:
        # time components may be separated by whitespace
        *time_parts, offset_raw = parts
        time_raw = "".join(time_parts)
        if len(time_raw) == 5 and time_raw[2] == ":":
            time = _time(int(time_raw[:2]), int(time_raw[3:]))
        elif len(time_raw) == 8 and time_raw[2] == ":" and time_raw[5] == ":":
            time = _time(
                int(time_raw[:2]), int(time_raw[3:5]), int(time_raw[6:])
            )
        else:
            _parse_err(s)
    except ValueError:
        _parse_err(s)

    # Parse the offset
    try:
        if offset_raw.startswith(("+", "-")) and len(offset_raw) == 5:
            sign = 1 if offset_raw[0] == "+" else -1
            offset = (
                _timedelta(
                    hours=int(offset_raw[1:3]), minutes=int(offset_raw[3:5])
                )
                * sign
            )
        elif offset_raw.isalpha():
            # According to the spec, unknown timezones should
            # just be treated at -0000 (UTC with unknown offset)
            offset = _timedelta(
                hours=_RFC2822_ZONES.get(offset_raw.upper(), 0)
            )
        else:
            _parse_err(s)
        tzinfo = _timezone(offset)
    except ValueError:
        _parse_err(s)

    return check_utc_bounds(_datetime.combine(date, time, tzinfo=tzinfo))


_MAX_TDELTA_DIGITS = 35  # consistent with Rust extension


def _parse_timedelta_component(
    fullstr: str, exc: Exception
) -> tuple[str, int, Literal["H", "M", "S"]]:
    try:
        split_index, unit = next(
            (i, c) for i, c in enumerate(fullstr) if c in "HMS"
        )
    except StopIteration:
        raise exc

    raw, rest = fullstr[:split_index], fullstr[split_index + 1 :]

    if unit == "S":
        digits, sep, nanos_raw = _split_nextchar(raw, ".,")

        if (
            len(digits) > _MAX_TDELTA_DIGITS
            or not digits.isdigit()
            or len(nanos_raw) > 9
            or (sep and not nanos_raw.isdigit())
        ):
            raise exc

        value = int(digits) * 1_000_000_000 + int(nanos_raw.ljust(9, "0"))
    else:
        if len(raw) > _MAX_TDELTA_DIGITS or not raw.isdigit():
            raise exc
        value = int(raw)

    return rest, value, cast(Literal["H", "M", "S"], unit)
