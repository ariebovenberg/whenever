"""Posix TZ string parser and time zone implementation.

This is pretty much a reimplementation of the Rust version located in the
`src/tz/posix.rs` file.
"""

from __future__ import annotations

import calendar
from datetime import date, datetime, timezone
from operator import itemgetter

from .._common import (
    EPOCH_ORDINAL,
    EPOCH_SECS_MAX,
    EPOCH_SECS_MIN,
    S_PER_DAY,
    S_PER_HOUR,
)
from .common import Fold, Gap, LocalMapping, Unique

DEFAULT_DST = S_PER_HOUR
DEFAULT_RULE_TIME = 2 * S_PER_HOUR
# RFC 9636: a rule time ranges from -167 to 167 hours
MAX_RULE_TIME = 167 * S_PER_HOUR + 59 * 60 + 59
MAX_OFFSET = 24 * S_PER_HOUR
Weekday = int  # Different than usual! Sunday=0, Saturday=6
UTC = timezone.utc


def year_for_epoch(ts: int) -> int:
    # Note: we can't use fromtimestamp() because it fails on extreme values
    # on some platforms. Instead, we go through the ordinal.
    return date.fromordinal(ts // S_PER_DAY + EPOCH_ORDINAL).year


def _days(d: date) -> int:
    """Days since the Unix epoch"""
    return d.toordinal() - EPOCH_ORDINAL


def _clamp(secs: int) -> int:
    return max(EPOCH_SECS_MIN, min(EPOCH_SECS_MAX, secs))


# How far a year's rule transitions can stray into an adjacent year: a rule
# time of up to 168 hours, an offset of up to 24, and the 366th day of a
# common year.
_STRAY = (168 + 24 + 24) * S_PER_HOUR


def _jan1(year: int) -> int:
    """Midnight UTC on Jan 1 of `year`, saturating at the supported range"""
    if year < 1:
        return EPOCH_SECS_MIN
    if year > 9999:
        return EPOCH_SECS_MAX
    return _days(date(year, 1, 1)) * S_PER_DAY


class LastWeekday:
    month: int
    weekday: Weekday

    __slots__ = ("month", "weekday")

    def __init__(self, month: int, weekday: Weekday):
        self.month = month
        self.weekday = weekday

    def days(self, year: int) -> int:
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
        return _days(date(year, self.month, last_weekday))

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

    def days(self, year: int) -> int:
        first_day_any_weekday = date(year, self.month, 1)
        first_weekday = (
            ((self.weekday + 7 - first_day_any_weekday.isoweekday() % 7) % 7)
            + 7 * (self.nth - 1)
            + 1
        )
        return _days(first_day_any_weekday.replace(day=first_weekday))

    def __eq__(self, other: object) -> bool:
        if not isinstance(other, NthWeekday):
            return NotImplemented  # pragma: no cover
        return (
            self.month == other.month
            and self.nth == other.nth
            and self.weekday == other.weekday
        )


class DayOfYear:
    # 1-366; in a common year, 366 is Jan 1 of the next year, as POSIX,
    # zoneinfo and libc have it.
    nth: int

    __slots__ = ("nth",)

    def __init__(self, nth: int):
        self.nth = nth

    def days(self, year: int) -> int:
        return _days(date(year, 1, 1)) + self.nth - 1

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

    def days(self, year: int) -> int:
        day = self.nth
        if calendar.isleap(year) and day > 59:
            day += 1
        return _days(date(year, 1, 1)) + day - 1

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
        if self.dst and self._is_dst_at(self.dst, epoch):
            return self.dst.offset
        return self.std

    def ambiguity_for_local(self, dt: datetime) -> LocalMapping:
        assert dt.tzinfo is None
        return self._ambiguity_for_local_epoch(
            int(dt.replace(tzinfo=UTC).timestamp())
        )

    # NOTE: `epoch` is the datetime in seconds since the LOCAL epoch.
    def _ambiguity_for_local_epoch(self, epoch: int) -> LocalMapping:
        dst = self.dst
        if not dst:
            return Unique(self.std)
        # A local time reads one instant per offset; an offset holds for the
        # local time when it is in effect at that instant.
        std_holds = not self._is_dst_at(dst, _clamp(epoch - self.std))
        dst_holds = self._is_dst_at(dst, _clamp(epoch - dst.offset))
        if std_holds != dst_holds:
            return Unique(self.std if std_holds else dst.offset)
        small, large = sorted((self.std, dst.offset))
        # The larger offset reads the earlier instant: before the transition
        # in a fold, after it in a gap.
        transition = _clamp(
            self._change_after(dst, _clamp(epoch - large)) + large
        )
        if std_holds:
            return Fold(transition, large, small)
        return Gap(transition, large, small)

    def _year_transitions(
        self, dst: Dst, year: int
    ) -> tuple[tuple[int, bool], tuple[int, bool]]:
        """The two rule transitions of a year, earliest first, each flagged
        with whether DST starts there. A rule time beyond 24 hours, or the
        366th day of a common year, can move a transition into an adjacent
        year."""
        start_rule, start_time = dst.start
        end_rule, end_time = dst.end
        start = _clamp(
            _clamp(start_rule.days(year) * S_PER_DAY + start_time) - self.std
        )
        end = _clamp(
            _clamp(end_rule.days(year) * S_PER_DAY + end_time) - dst.offset
        )
        if end < start:
            return ((end, False), (start, True))
        return ((start, True), (end, False))

    def _transitions_near(
        self, dst: Dst, epoch: int, years_before: int, years_after: int
    ) -> list[tuple[int, bool]]:
        """The rule transitions of the years around `epoch`, in order. At a
        shared instant, the later year's transition comes last and wins."""
        year = self._year_of(epoch)
        items = [
            t
            for y in range(
                max(1, year - years_before), min(9999, year + years_after) + 1
            )
            for t in self._year_transitions(dst, y)
        ]
        # Stable, so a tie keeps the year order
        items.sort(key=itemgetter(0))
        return items

    def _year_of(self, epoch: int) -> int:
        """The local year of `epoch`, in standard time"""
        return year_for_epoch(_clamp(epoch + self.std))

    def _is_dst_at(self, dst: Dst, epoch: int) -> bool:
        """Whether DST is in effect at the given UTC epoch: the latest rule
        transition at or before it decides. An adjacent year's transitions
        count only near the turn of the year, so most calls see one year."""
        year = self._year_of(epoch)

        def latest(y: int) -> tuple[int, bool] | None:
            if not 1 <= y <= 9999:
                return None
            return next(
                (
                    t
                    for t in reversed(self._year_transitions(dst, y))
                    if t[0] <= epoch
                ),
                None,
            )

        best = latest(year)
        if best is None or best[0] < _jan1(year) + _STRAY:
            prev = latest(year - 1)
            if prev is not None and (best is None or prev[0] > best[0]):
                best = prev
        # At a shared instant, the later year wins
        if epoch >= _jan1(year + 1) - _STRAY:
            nxt = latest(year + 1)
            if nxt is not None and (best is None or nxt[0] >= best[0]):
                best = nxt
        if best is not None:
            return best[1]
        # Only at the edge of the supported range: before a transition, the
        # other state holds.
        return not self._year_transitions(dst, year)[0][1]

    def _change_after(self, dst: Dst, epoch: int) -> int:
        """The first instant after `epoch` where DST starts or ends"""
        change = self._next_change(dst, epoch)
        return EPOCH_SECS_MAX if change is None else change[0]

    def _next_change(self, dst: Dst, epoch: int) -> tuple[int, bool] | None:
        state = self._is_dst_at(dst, epoch)
        items = self._transitions_near(dst, epoch, 1, 2)
        # A year's transitions stay within days of it, so the years in view
        # settle every instant up to a year before the last of them ends.
        limit = _jan1(self._year_of(epoch) + 2)
        for i, (t, starts_dst) in enumerate(items):
            if t >= limit:
                break
            # Only the last transition at an instant counts
            if t <= epoch or (i + 1 < len(items) and items[i + 1][0] == t):
                continue
            if starts_dst != state:
                return t, starts_dst
        return None

    def next_transition(self, epoch: int) -> tuple[int, int] | None:
        """Return (epoch, new_offset) of the next UTC offset transition
        after `epoch`, or None if there is none."""
        dst = self.dst
        if not dst:
            return None
        change = self._next_change(dst, epoch)
        if change is None:
            return None
        t, is_dst = change
        return t, dst.offset if is_dst else self.std

    def prev_transition(self, epoch: int) -> tuple[int, int] | None:
        """Return (epoch, new_offset) of the previous UTC offset transition
        before `epoch`, or None if there is none."""
        dst = self.dst
        if not dst:
            return None
        items = self._transitions_near(dst, epoch, 2, 1)
        # See `_next_change`
        limit = _jan1(self._year_of(epoch) - 1)
        for i in reversed(range(len(items))):
            t, starts_dst = items[i]
            if t < limit:
                break
            # Only the last transition at an instant counts
            if t >= epoch or (i + 1 < len(items) and items[i + 1][0] == t):
                continue
            before = next(
                (s for u, s in reversed(items[:i]) if u < t),
                None,
            )
            if before is None:
                before = self._is_dst_at(dst, _clamp(t - 1))
            if starts_dst != before:
                return t, dst.offset if starts_dst else self.std
        return None

    def meta_for_instant(self, epoch: int) -> tuple[int, str]:
        """Return (dst_saving_secs, abbreviation) for the given UTC epoch."""
        if self.dst and self._is_dst_at(self.dst, epoch):
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
    """Parse the time zone name, returning (name, rest_of_string). Per POSIX,
    a name has three or more characters: letters, or, between ``<`` and
    ``>``, letters, digits, ``+`` and ``-``."""
    if s[:1] == "<":  # bracketed format
        stop = s.find(">") + 1
        name = s[1 : stop - 1]
        if not stop or not all(c.isalnum() or c in "+-" for c in name):
            raise ValueError("Invalid TZ string: invalid name")
    else:  # unbracketed format only allows letters
        stop = len(s) - len(s.lstrip(_LETTERS))
        name = s[:stop]
    if len(name) < 3:
        raise ValueError("Invalid TZ string: invalid name")
    return name, s[stop:]


_LETTERS = "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz"


def expect_char(s: str, char: str) -> str:
    if s[:1] != char:
        raise ValueError(f"Invalid TZ string: expected '{char}'")
    return s[1:]


def parse_offset(s: str) -> tuple[int, str]:
    delta_s, s = parse_hms(s, MAX_OFFSET - 1)
    # POSIX TZ strings use negative offsets, so we negate the parsed value
    return -delta_s, s


# Parse a time string in the format h[h[h]][:mm[:ss]], up to `max` seconds.
# The hours take a third digit only when `max` needs one.
def parse_hms(s: str, max: int) -> tuple[int, str]:
    sign = 1
    if s[:1] == "+":
        s = s[1:]
    elif s[:1] == "-":
        s = s[1:]
        sign = -1

    total = 0
    if max > 99 * S_PER_HOUR:
        hour, s = parse_up_to_3_digits(s)
    else:
        hour, s = parse_up_to_2_digits(s)
    total += hour * 3600
    if s[:1] == ":":
        s = s[1:]
        minute, s = parse_00_to_59(s)
        total += minute * 60
        if s[:1] == ":":
            s = s[1:]
            second, s = parse_00_to_59(s)
            total += second

    if total > max:
        raise ValueError("Invalid POSIX TZ string: time out of range")
    return sign * total, s


def parse_up_to_2_digits(s: str) -> tuple[int, str]:
    total = int(s[:1])
    if (nextchar := s[1:2]).isdigit():
        return total * 10 + int(nextchar), s[2:]
    return total, s[1:]


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
        time, s = parse_hms(s, MAX_RULE_TIME)
    else:
        time = DEFAULT_RULE_TIME

    return (rule, time), s
