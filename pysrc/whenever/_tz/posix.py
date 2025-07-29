# TODO: only lazy import due to dataclass dependency
from __future__ import annotations

import calendar
from dataclasses import dataclass
from datetime import date, datetime, time, timedelta, timezone, tzinfo
from typing import Optional, Union

DEFAULT_DST = 3600
DEFAULT_RULE_TIME = 2 * 3600
MAX_OFFSET = 24 * 3600
Weekday = int  # Different than usual! Sunday=0, Saturday=6

UTC = timezone.utc


def year_for_epoch(ts: int) -> int:
    return datetime.fromtimestamp(ts, tz=UTC).year


def epoch_for_date(d: date) -> int:
    """Convert a date to a POSIX timestamp in UTC."""
    return int(datetime.combine(d, time.min).replace(tzinfo=UTC).timestamp())


@dataclass(frozen=True)
class Unambiguous:
    offset: int

    def fold(self, fold: int) -> timedelta:
        return timedelta(seconds=self.offset)


@dataclass(frozen=True)
class Gap:
    earlier: int
    later: int

    def fold(self, fold: int) -> timedelta:
        return timedelta(seconds=self.earlier if fold == 1 else self.later)


@dataclass(frozen=True)
class Fold:
    earlier: int
    later: int

    def fold(self, fold: int) -> timedelta:
        return timedelta(seconds=self.later if fold == 1 else self.earlier)


Ambiguity = Union[Unambiguous, Gap, Fold]

# --- Rule ---


@dataclass(frozen=True)
class LastWeekday:
    month: int
    weekday: Weekday

    def apply(self, year: int) -> date:
        last_day_any_weekday = calendar.monthrange(year, self.month)[1]
        last_weekday = (
            last_day_any_weekday
            - (
                date(year, self.month, last_day_any_weekday).isoweekday() % 7
                + 7
                - self.weekday
            )
            % 7
        )
        return date(year, self.month, last_weekday)


@dataclass(frozen=True)
class NthWeekday:
    month: int
    nth: int
    weekday: Weekday

    def apply(self, year: int) -> date:
        first_day_any_weekday = date(year, self.month, 1)
        first_weekday = (
            ((self.weekday + 7 - first_day_any_weekday.isoweekday() % 7) % 7)
            + 7 * (self.nth - 1)
            + 1
        )
        return first_day_any_weekday.replace(day=first_weekday)


@dataclass(frozen=True)
class DayOfYear:
    nth: int  # 1-365, 366 for leap years

    def apply(self, year: int) -> date:
        day = min(self.nth, 365 + calendar.isleap(year))
        return date(year, 1, 1) + timedelta(day - 1)


@dataclass(frozen=True)
class JulianDayOfYear:
    nth: int  # 1-365

    def apply(self, year: int) -> date:
        day = self.nth
        if calendar.isleap(year) and day > 59:
            day += 1
        return date(year, 1, 1) + timedelta(day - 1)


Rule = Union[LastWeekday, NthWeekday, DayOfYear, JulianDayOfYear]


@dataclass(frozen=True)
class Dst:
    offset: int
    start: tuple[Rule, int]
    end: tuple[Rule, int]


@dataclass(frozen=True)
class Tz(tzinfo):
    std: int
    dst_: Optional[Dst]

    def offset_for_instant(self, epoch: int) -> int:
        if not self.dst_:
            return self.std
        # Theoretically, the epoch year could be different from the
        # local year. However, in practice, we can assume that the year of
        # the transition isn't affected by the DST change.
        # This is what Python's `zoneinfo` does anyway...
        year = year_for_epoch(epoch + self.std)

        start_rule, start_time = self.dst_.start
        end_rule, end_time = self.dst_.end
        dst_offset = self.dst_.offset

        start = epoch_for_date(start_rule.apply(year)) + start_time - self.std
        end = epoch_for_date(end_rule.apply(year)) + end_time - dst_offset

        # Handle wraparound
        if start < end:
            if start <= epoch < end:
                return dst_offset
            else:
                return self.std
        else:
            if end <= epoch < start:
                return self.std
            else:
                return dst_offset

    # NOTE: `epoch` is the datetime in seconds since the LOCAL epoch.
    def ambiguity_for_local(self, epoch: int) -> Ambiguity:
        if not self.dst_:
            return Unambiguous(self.std)
        year = year_for_epoch(epoch)

        start_rule, start_time = self.dst_.start
        end_rule, end_time = self.dst_.end
        dst_offset = self.dst_.offset

        start = epoch_for_date(start_rule.apply(year)) + start_time
        end = epoch_for_date(end_rule.apply(year)) + end_time

        if start < end:
            t1, t2 = start, end
            off1, off2 = self.std, dst_offset
            shift = dst_offset - self.std
        else:
            t1, t2 = end, start
            off1, off2 = dst_offset, self.std
            shift = self.std - dst_offset

        if shift >= 0:
            if epoch < t1:
                return Unambiguous(off1)
            elif epoch < t1 + shift:
                return Gap(off2, off1)
            elif epoch < t2 - shift:
                return Unambiguous(off2)
            elif epoch < t2:
                return Fold(off2, off1)
            else:
                return Unambiguous(off1)
        else:
            if epoch < t1 + shift:
                return Unambiguous(off1)
            elif epoch < t1:
                return Fold(off1, off2)
            elif epoch < t2:
                return Unambiguous(off2)
            elif epoch < t2 - shift:
                return Gap(off1, off2)
            else:
                return Unambiguous(off1)

    # Two overrides of the tzinfo interface.
    # We don't implement `tzname` or `dst` since we don't use them.
    # This class is only meant for internal use anyway.
    def utcoffset(self, dt: Optional[datetime]) -> Optional[timedelta]:
        if dt is None:
            return None
        return self.ambiguity_for_local(
            int(dt.replace(tzinfo=UTC).timestamp())
        ).fold(dt.fold)

    def fromutc(self, dt: datetime) -> datetime:
        offset = timedelta(
            seconds=self.offset_for_instant(
                int(dt.replace(tzinfo=UTC).timestamp())
            )
        )
        local = dt + offset
        if self.utcoffset(local) != offset:
            local = local.replace(fold=1)
        return local

    def dst(self, _: Optional[datetime]) -> Optional[timedelta]:
        raise NotImplementedError()

    def tzname(self, _: Optional[datetime]) -> Optional[str]:
        raise NotImplementedError()


def parse(s: str) -> Tz:
    if not s.isascii():
        raise ValueError("Invalid POSIX TZ string: non-ASCII characters found")

    s = skip_tzname(s)
    std, s = parse_offset(s)

    if abs(std) >= MAX_OFFSET:
        raise ValueError("Invalid POSIX TZ string: std offset out of range")

    # If there's nothing else, it's a fixed offset without DST
    if not s:
        return Tz(std, dst_=None)

    s = skip_tzname(s)

    if s[:1] == ",":
        # No offset given, the default is std + 1hr
        s = s[1:]
        dst = std + DEFAULT_DST
        if dst >= MAX_OFFSET:
            raise ValueError(
                "Invalid POSIX TZ string: DST offset out of range"
            )
    else:
        dst, s = parse_offset(s)
        s = expect_char(s, ",")

    start, s = parse_rule(s)
    s = expect_char(s, ",")
    end, s = parse_rule(s)

    if s:
        raise ValueError(f"Invalid POSIX TZ string: unexpected trailing '{s}'")
    else:
        return Tz(std, Dst(dst, start, end))


def skip_tzname(s: str) -> str:
    """Skip the timezone name, returning the rest of the string."""
    if s[:1] == "<":  # bracketed format
        stop = s.find(">") + 1
        if stop < 3:  # not found or empty name
            raise ValueError("Invalid TZ string: missing or empty name")
    else:  # unbracketed format only allows letters
        for stop, char in enumerate(s):
            if not char.isalpha():
                break
        else:
            raise ValueError("Invalid TZ string: missing or empty name")

        if stop == 0:
            raise ValueError("Invalid TZ string: invalid name")

    return s[stop:]


def expect_char(s: str, char: str) -> str:
    if s[:1] != char:
        raise ValueError(f"Invalid TZ string: expected '{char}'")
    return s[1:]


def parse_offset(s: str) -> tuple[int, str]:
    delta_s, s = parse_hms(s)
    if abs(delta_s) >= MAX_OFFSET:
        raise ValueError("Invalid POSIX TZ string: offset out of range")
    # POSIX TZ strings use negative offsets, so we negate the parsed value
    return -delta_s, s


# Parse a time string in the format h[hh[:mm[:ss]]]
def parse_hms(s: str) -> tuple[int, str]:
    sign = 1
    if s[:1] == "+":
        s = s[1:]
    elif s[:1] == "-":
        s = s[1:]
        sign = -1

    total = 0
    hour, s = parse_up_to_3_digits(s)
    total += hour * 3600
    if s[:1] == ":":
        s = s[1:]
        minute, s = parse_00_to_59(s)
        total += minute * 60
        if s[:1] == ":":
            s = s[1:]
            second, s = parse_00_to_59(s)
            total += second

    return sign * total, s


def parse_up_to_3_digits(s: str) -> tuple[int, str]:
    total = int(s[:1])
    if (nextchar := s[1:2]).isdigit():
        total = total * 10 + int(nextchar)
        if (nextchar := s[2:3]).isdigit():
            total = total * 10 + int(nextchar)
            return total, s[3:]
        return total, s[2:]
    return total, s[1:]


def parse_1_to_12(s: str) -> tuple[int, str]:
    total = int(s[:1])
    if (nextchar := s[1:2]).isdigit():
        total = total * 10 + int(nextchar)
        return total, s[2:]
    if total < 1 or total > 12:
        raise ValueError(f"Invalid TZ string: expected 1-12, got '{s[:2]}'")
    return total, s[1:]


def parse_00_to_59(s: str) -> tuple[int, str]:
    if len(s) < 2 or not s[:2].isdigit():
        raise ValueError(f"Invalid TZ string: expected 2 digits, got '{s}'")
    value = int(s[:2])
    if value > 59:
        raise ValueError(f"Invalid TZ string: expected 00-59, got '{s[:2]}'")
    return value, s[2:]


def parse_digit(s: str) -> tuple[int, str]:
    return int(s[:1]), s[1:]


def parse_rule(s: str) -> tuple[tuple[Rule, int], str]:

    rule: Rule
    if s[:1] == "M":  # Mm.n.d format
        m, s = parse_1_to_12(s[1:])
        s = expect_char(s, ".")
        n, s = parse_digit(s)
        s = expect_char(s, ".")
        d, s = parse_digit(s)

        if m < 1 or m > 12 or n < 1 or d > 6:
            raise ValueError("Invalid DST rule")

        if n < 5:
            rule = NthWeekday(m, n, d)
        elif n == 5:
            rule = LastWeekday(m, d)
        else:
            raise ValueError(f"Invalid week number: {n}")
    elif s[:1] == "J":  # Jnnn format
        nth, s = parse_up_to_3_digits(s[1:])
        if nth < 1 or nth > 365:
            raise ValueError(f"Invalid Julian day of year: {nth}")
        rule = JulianDayOfYear(nth)
    else:  # nnn format
        nth, s = parse_up_to_3_digits(s)
        if nth > 365:
            raise ValueError(f"Invalid day of year: {nth}")
        rule = DayOfYear(nth + 1)

    if s[:1] == "/":
        # Optional time
        s = s[1:]
        time, s = parse_hms(s)
    else:
        time = DEFAULT_RULE_TIME

    return (rule, time), s
