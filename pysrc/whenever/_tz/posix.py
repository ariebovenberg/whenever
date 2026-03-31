"""Posix TZ string parser and timezone implementation.

This is pretty much a reimplementation of the Rust version located in the
`src/tz/posix.rs` file.
"""

from __future__ import annotations

import calendar
from datetime import date, datetime, time, timedelta, timezone

from .common import Ambiguity, Fold, Gap, Unambiguous

DEFAULT_DST = 3600
DEFAULT_RULE_TIME = 2 * 3600
MAX_OFFSET = 24 * 3600
Weekday = int  # Different than usual! Sunday=0, Saturday=6
UTC = timezone.utc


def year_for_epoch(ts: int) -> int:
    # Note: we can't use fromtimestamp() because it fails on extreme values
    # on some platforms. Instead, we go through the ordinal.
    return date.fromordinal(ts // 86400 + 719163).year


def epoch_for_date(d: date) -> int:
    """Convert a date to a POSIX timestamp in UTC."""
    return int(datetime.combine(d, time.min).replace(tzinfo=UTC).timestamp())


class LastWeekday:
    month: int
    weekday: Weekday

    __slots__ = ("month", "weekday")

    def __init__(self, month: int, weekday: Weekday):
        self.month = month
        self.weekday = weekday

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

    def __eq__(self, other: object) -> bool:
        if not isinstance(other, LastWeekday):
            return NotImplemented  # pragma: no cover
        return self.month == other.month and self.weekday == other.weekday

    def __repr__(self) -> str:
        return f"LastWeekday({self.month}, {self.weekday})"


class NthWeekday:
    month: int
    nth: int
    weekday: Weekday

    __slots__ = ("month", "nth", "weekday")

    def __init__(self, month: int, nth: int, weekday: Weekday):
        self.month = month
        self.nth = nth
        self.weekday = weekday

    def apply(self, year: int) -> date:
        first_day_any_weekday = date(year, self.month, 1)
        first_weekday = (
            ((self.weekday + 7 - first_day_any_weekday.isoweekday() % 7) % 7)
            + 7 * (self.nth - 1)
            + 1
        )
        return first_day_any_weekday.replace(day=first_weekday)

    def __eq__(self, other: object) -> bool:
        if not isinstance(other, NthWeekday):
            return NotImplemented  # pragma: no cover
        return (
            self.month == other.month
            and self.nth == other.nth
            and self.weekday == other.weekday
        )


class DayOfYear:
    nth: int  # 1-365, 366 for leap years

    __slots__ = ("nth",)

    def __init__(self, nth: int):
        self.nth = nth

    def apply(self, year: int) -> date:
        day = min(self.nth, 365 + calendar.isleap(year))
        return date(year, 1, 1) + timedelta(day - 1)

    def __eq__(self, other: object) -> bool:
        if not isinstance(other, DayOfYear):
            return NotImplemented  # pragma: no cover
        return self.nth == other.nth

    def __repr__(self) -> str:
        return f"DayOfYear({self.nth})"


class JulianDayOfYear:
    nth: int  # 1-365

    __slots__ = ("nth",)

    def __init__(self, nth: int):
        self.nth = nth

    def apply(self, year: int) -> date:
        day = self.nth
        if calendar.isleap(year) and day > 59:
            day += 1
        return date(year, 1, 1) + timedelta(day - 1)

    def __eq__(self, other: object) -> bool:
        if not isinstance(other, JulianDayOfYear):
            return NotImplemented  # pragma: no cover
        return self.nth == other.nth

    def __repr__(self) -> str:
        return f"JulianDayOfYear({self.nth})"


Rule = LastWeekday | NthWeekday | DayOfYear | JulianDayOfYear


class Dst:
    offset: int
    start: tuple[Rule, int]
    end: tuple[Rule, int]
    abbrev: str

    __slots__ = ("offset", "start", "end", "abbrev")

    def __init__(
        self,
        offset: int,
        start: tuple[Rule, int],
        end: tuple[Rule, int],
        abbrev: str,
    ):
        self.offset = offset
        self.start = start
        self.end = end
        self.abbrev = abbrev

    def __eq__(self, other: object) -> bool:
        if not isinstance(other, Dst):
            return NotImplemented  # pragma: no cover
        return (
            self.offset == other.offset
            and self.start == other.start
            and self.end == other.end
            and self.abbrev == other.abbrev
        )

    def __repr__(self) -> str:
        return f"Dst(offset={self.offset}, start={self.start}, end={self.end})"


class TzStr:
    std: int
    dst: Dst | None
    std_abbrev: str

    __slots__ = ("std", "dst", "std_abbrev")

    def __init__(
        self,
        std: int,
        dst: Dst | None,
        std_abbrev: str,
    ):
        self.std = std
        self.dst = dst
        self.std_abbrev = std_abbrev

    def offset_for_instant(self, epoch: int) -> int:
        if self.dst and self._is_dst_at(epoch):
            return self.dst.offset
        return self.std

    # NOTE: `epoch` is the datetime in seconds since the LOCAL epoch.
    def ambiguity_for_local(self, epoch: int) -> Ambiguity:
        if not self.dst:
            return Unambiguous(self.std)
        year = year_for_epoch(epoch)

        start_rule, start_time = self.dst.start
        end_rule, end_time = self.dst.end
        dst_offset = self.dst.offset

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

    def _utc_transitions_for_year(
        self, year: int
    ) -> tuple[tuple[int, int], tuple[int, int]] | None:
        """Return ((start_epoch, new_offset), (end_epoch, new_offset))
        DST transition instants in UTC for the given year.
        Returns None if no DST rule or year out of range."""
        if not self.dst or not (1 <= year <= 9999):
            return None
        start_rule, start_time = self.dst.start
        end_rule, end_time = self.dst.end
        start = epoch_for_date(start_rule.apply(year)) + start_time - self.std
        end = epoch_for_date(end_rule.apply(year)) + end_time - self.dst.offset
        return ((start, self.dst.offset), (end, self.std))

    def _is_dst_at(self, epoch: int) -> bool:
        """Whether DST is active at the given UTC epoch."""
        trans = self._utc_transitions_for_year(
            year_for_epoch(epoch + self.std)
        )
        if trans is None:
            return False
        (start, _), (end, _) = trans
        if start < end:
            return start <= epoch < end
        else:
            return not (end <= epoch < start)

    def next_transition(self, epoch: int) -> tuple[int, int] | None:
        """Return (epoch, new_offset) of the next UTC offset transition
        after `epoch`, or None if there is no DST rule."""
        trans = self._utc_transitions_for_year(
            year_for_epoch(epoch + self.std)
        )
        if trans is None:
            return None
        future = sorted((e, o) for e, o in trans if e > epoch)
        if future:
            return future[0]
        # Both transitions are <= epoch; check next year
        trans = self._utc_transitions_for_year(
            year_for_epoch(epoch + self.std) + 1
        )
        if trans is None:
            return None
        return min(trans)

    def prev_transition(self, epoch: int) -> tuple[int, int] | None:
        """Return (epoch, new_offset) of the previous UTC offset transition
        before `epoch`, or None if there is no DST rule."""
        trans = self._utc_transitions_for_year(
            year_for_epoch(epoch + self.std)
        )
        if trans is None:
            return None
        past = sorted(((e, o) for e, o in trans if e < epoch), reverse=True)
        if past:
            return past[0]
        # Both transitions are >= epoch; check previous year
        trans = self._utc_transitions_for_year(
            year_for_epoch(epoch + self.std) - 1
        )
        if trans is None:
            return None
        return max(trans)

    def meta_for_instant(self, epoch: int) -> tuple[int, str]:
        """Return (dst_saving_secs, abbreviation) for the given UTC epoch."""
        if self.dst and self._is_dst_at(epoch):
            return (self.dst.offset - self.std, self.dst.abbrev)
        return (0, self.std_abbrev)

    def __eq__(self, other: object) -> bool:
        if not isinstance(other, TzStr):
            return NotImplemented  # pragma: no cover
        return (
            self.std == other.std
            and self.dst == other.dst
            and self.std_abbrev == other.std_abbrev
        )

    def __repr__(self) -> str:
        if not self.dst:
            return f"TzStr(std={self.std})"
        else:
            return f"TzStr(std={self.std}, dst={self.dst})"

    @classmethod
    def parse(cls, s: str) -> TzStr:
        if not s.isascii():
            raise ValueError(
                "Invalid POSIX TZ string: non-ASCII characters found"
            )

        std_abbrev, s = parse_tzname(s)
        std, s = parse_offset(s)

        # If there's nothing else, it's a fixed offset without DST
        if not s:
            return cls(std, dst=None, std_abbrev=std_abbrev)

        dst_abbrev, s = parse_tzname(s)

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
            raise ValueError(
                f"Invalid POSIX TZ string: unexpected trailing '{s}'"
            )
        else:
            return cls(
                std,
                Dst(dst, start, end, dst_abbrev),
                std_abbrev=std_abbrev,
            )


def parse_tzname(s: str) -> tuple[str, str]:
    """Parse the timezone name, returning (name, rest_of_string)."""
    if s[:1] == "<":  # bracketed format
        stop = s.find(">") + 1
        if stop < 3:  # not found or empty name
            raise ValueError("Invalid TZ string: missing or empty name")
        name = s[1 : stop - 1]
    else:  # unbracketed format only allows letters
        for stop, char in enumerate(s):
            if not char.isalpha():
                break
        else:
            raise ValueError("Invalid TZ string: missing or empty name")

        if stop == 0:
            raise ValueError("Invalid TZ string: invalid name")
        name = s[:stop]

    return name, s[stop:]


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
