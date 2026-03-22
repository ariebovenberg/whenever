"""Pattern-based formatting and parsing for whenever types.

A pattern string is compiled into a tuple of elements, which can then
be used to format values to strings or parse strings into values.
"""

from __future__ import annotations

import warnings
from collections.abc import Iterable
from functools import lru_cache
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from typing import Sequence

# Month and weekday names (English only, invariant)
_MONTH_ABBR = [
    "",
    "Jan",
    "Feb",
    "Mar",
    "Apr",
    "May",
    "Jun",
    "Jul",
    "Aug",
    "Sep",
    "Oct",
    "Nov",
    "Dec",
]
_MONTH_FULL = [
    "",
    "January",
    "February",
    "March",
    "April",
    "May",
    "June",
    "July",
    "August",
    "September",
    "October",
    "November",
    "December",
]
_WEEKDAY_ABBR = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]
_WEEKDAY_FULL = [
    "Monday",
    "Tuesday",
    "Wednesday",
    "Thursday",
    "Friday",
    "Saturday",
    "Sunday",
]

# Reverse lookups for parsing (lowercase key → value)
_MONTH_ABBR_LOOKUP = {n.lower(): i for i, n in enumerate(_MONTH_ABBR) if n}
_MONTH_FULL_LOOKUP = {n.lower(): i for i, n in enumerate(_MONTH_FULL) if n}
_WEEKDAY_ABBR_LOOKUP = {n.lower(): i for i, n in enumerate(_WEEKDAY_ABBR)}
_WEEKDAY_FULL_LOOKUP = {n.lower(): i for i, n in enumerate(_WEEKDAY_FULL)}


def _parse_digits(s: str, pos: int, count: int) -> tuple[int, int]:
    """Parse exactly ``count`` digits from s at pos.
    Returns (value, new_pos).
    """
    end = pos + count
    if end > len(s):
        raise ValueError(
            f"Expected {count} digits at position {pos}, "
            f"but input is too short"
        )
    chunk = s[pos:end]
    if not chunk.isdigit():
        raise ValueError(
            f"Expected {count} digits at position {pos}, " f"got {chunk!r}"
        )
    return int(chunk), end


def _parse_1or2_digits(s: str, pos: int) -> tuple[int, int]:
    """Parse 1 or 2 digits from s at pos (greedy).
    Returns (value, new_pos).
    """
    n = len(s)
    if pos >= n or not s[pos].isdigit():
        raise ValueError(f"Expected 1-2 digits at position {pos}")
    count = 1
    if pos + 1 < n and s[pos + 1].isdigit():
        count = 2
    return int(s[pos : pos + count]), pos + count


def _parse_text_match(
    s: str,
    pos: int,
    lookup: dict[str, int],
    field_name: str,
) -> tuple[int, int]:
    """Match text against a lookup dict (case-insensitive).
    Returns (value, new_pos). Tries longest match first.
    """
    s_lower = s[pos:].lower()
    for key in sorted(lookup, key=len, reverse=True):
        if s_lower.startswith(key):
            return lookup[key], pos + len(key)
    raise ValueError(f"Cannot parse {field_name} at position {pos}")


# --- Format values (input to formatting) ---


class _FormatValues:
    """Values available for formatting."""

    __slots__ = (
        "year",
        "month",
        "day",
        "weekday",
        "hour",
        "minute",
        "second",
        "nanos",
        "offset_secs",
        "tz_id",
        "tz_abbrev",
    )

    def __init__(
        self,
        *,
        year: int = 0,
        month: int = 0,
        day: int = 0,
        weekday: int = 0,  # 0=Mon, 6=Sun
        hour: int = 0,
        minute: int = 0,
        second: int = 0,
        nanos: int = 0,
        offset_secs: int | None = None,
        tz_id: str | None = None,
        tz_abbrev: str | None = None,
    ):
        self.year = year
        self.month = month
        self.day = day
        self.weekday = weekday
        self.hour = hour
        self.minute = minute
        self.second = second
        self.nanos = nanos
        self.offset_secs = offset_secs
        self.tz_id = tz_id
        self.tz_abbrev = tz_abbrev


# --- Parse state ---


class _ParseState:
    """Mutable parse state accumulating field values from input."""

    __slots__ = (
        "year",
        "month",
        "day",
        "hour",
        "minute",
        "second",
        "nanos",
        "ampm",
        "offset_secs",
        "tz_id",
        "weekday",
        "second_absent",
    )

    def __init__(self) -> None:
        self.year: int | None = None
        self.month: int | None = None
        self.day: int | None = None
        self.hour: int | None = None
        self.minute: int | None = None
        self.second: int | None = None
        self.nanos: int = 0
        self.ampm: str | None = None
        self.offset_secs: int | None = None
        self.tz_id: str | None = None
        self.weekday: int | None = None
        self.second_absent: bool = False

    def resolve(self) -> None:
        """Apply AM/PM adjustment after all fields are parsed."""
        if self.ampm is not None and self.hour is not None:
            if self.ampm == "PM" and self.hour < 12:
                self.hour += 12
            elif self.ampm == "AM" and self.hour == 12:
                self.hour = 0


# --- Pattern elements ---


class _Literal:
    __slots__ = ("text",)

    def __init__(self, text: str):
        self.text = text

    def __repr__(self) -> str:
        return f"Literal({self.text!r})"


class _Field:
    """Base class for pattern fields.

    Subclasses define:
    - ``pattern``: (letter, count) for specifier table registration
    - ``category``: 'date', 'time', 'offset', or 'tz'
    - ``state_field``: name of the _ParseState field this writes to (for
      duplicate detection), or None if it doesn't write state
    - ``format_only``: True if the field cannot be used in parsing
    """

    pattern: tuple[str, int]
    category: str
    state_field: str
    format_only: bool = False

    def format_value(self, v: _FormatValues) -> str:
        raise NotImplementedError

    def parse_value(self, s: str, pos: int, state: _ParseState) -> int:
        raise NotImplementedError

    def apply_pending(self, ch: str) -> list[_Element]:
        """Called when a pending prefix char (``'.'`` or ``':'``) precedes this field.

        Returns the elements to emit: by default the pending char is flushed as a
        literal followed by self. Override to consume the pending char and transform
        into a compound field (e.g. ``.FFF`` → :class:`_DotFrac`).
        """
        return [_Literal(ch), self]

    def __repr__(self) -> str:
        letter, count = self.pattern
        return letter * count


_Element = _Literal | _Field


# --- Concrete field types ---


class _Year4(_Field):
    pattern = ("Y", 4)
    category = "date"
    state_field = "year"

    def format_value(self, v: _FormatValues) -> str:
        return f"{v.year:04d}"

    def parse_value(self, s: str, pos: int, state: _ParseState) -> int:
        state.year, pos = _parse_digits(s, pos, 4)
        return pos


class _Year2(_Field):
    pattern = ("Y", 2)
    category = "date"
    state_field = "year"
    format_only = True

    def format_value(self, v: _FormatValues) -> str:
        return f"{v.year % 100:02d}"


class _MonthNum(_Field):
    pattern = ("M", 2)
    category = "date"
    state_field = "month"

    def format_value(self, v: _FormatValues) -> str:
        return f"{v.month:02d}"

    def parse_value(self, s: str, pos: int, state: _ParseState) -> int:
        state.month, pos = _parse_digits(s, pos, 2)
        return pos


class _MonthNumUnpadded(_Field):
    pattern = ("M", 1)
    category = "date"
    state_field = "month"

    def format_value(self, v: _FormatValues) -> str:
        return str(v.month)

    def parse_value(self, s: str, pos: int, state: _ParseState) -> int:
        state.month, pos = _parse_1or2_digits(s, pos)
        return pos


class _MonthAbbr(_Field):
    pattern = ("M", 3)
    category = "date"
    state_field = "month"

    def format_value(self, v: _FormatValues) -> str:
        return _MONTH_ABBR[v.month]

    def parse_value(self, s: str, pos: int, state: _ParseState) -> int:
        state.month, pos = _parse_text_match(
            s, pos, _MONTH_ABBR_LOOKUP, "month"
        )
        return pos


class _MonthFull(_Field):
    pattern = ("M", 4)
    category = "date"
    state_field = "month"

    def format_value(self, v: _FormatValues) -> str:
        return _MONTH_FULL[v.month]

    def parse_value(self, s: str, pos: int, state: _ParseState) -> int:
        state.month, pos = _parse_text_match(
            s, pos, _MONTH_FULL_LOOKUP, "month"
        )
        return pos


class _Day(_Field):
    pattern = ("D", 2)
    category = "date"
    state_field = "day"

    def format_value(self, v: _FormatValues) -> str:
        return f"{v.day:02d}"

    def parse_value(self, s: str, pos: int, state: _ParseState) -> int:
        state.day, pos = _parse_digits(s, pos, 2)
        return pos


class _DayUnpadded(_Field):
    pattern = ("D", 1)
    category = "date"
    state_field = "day"

    def format_value(self, v: _FormatValues) -> str:
        return str(v.day)

    def parse_value(self, s: str, pos: int, state: _ParseState) -> int:
        state.day, pos = _parse_1or2_digits(s, pos)
        return pos


class _WeekdayAbbr(_Field):
    pattern = ("d", 3)
    category = "date"
    state_field = "weekday"

    def format_value(self, v: _FormatValues) -> str:
        return _WEEKDAY_ABBR[v.weekday]

    def parse_value(self, s: str, pos: int, state: _ParseState) -> int:
        state.weekday, pos = _parse_text_match(
            s, pos, _WEEKDAY_ABBR_LOOKUP, "weekday"
        )
        return pos


class _WeekdayFull(_Field):
    pattern = ("d", 4)
    category = "date"
    state_field = "weekday"

    def format_value(self, v: _FormatValues) -> str:
        return _WEEKDAY_FULL[v.weekday]

    def parse_value(self, s: str, pos: int, state: _ParseState) -> int:
        state.weekday, pos = _parse_text_match(
            s, pos, _WEEKDAY_FULL_LOOKUP, "weekday"
        )
        return pos


class _Hour24(_Field):
    pattern = ("h", 2)
    category = "time"
    state_field = "hour"

    def format_value(self, v: _FormatValues) -> str:
        return f"{v.hour:02d}"

    def parse_value(self, s: str, pos: int, state: _ParseState) -> int:
        state.hour, pos = _parse_digits(s, pos, 2)
        return pos


class _Hour24Unpadded(_Field):
    pattern = ("h", 1)
    category = "time"
    state_field = "hour"

    def format_value(self, v: _FormatValues) -> str:
        return str(v.hour)

    def parse_value(self, s: str, pos: int, state: _ParseState) -> int:
        state.hour, pos = _parse_1or2_digits(s, pos)
        return pos


class _Hour12(_Field):
    pattern = ("i", 2)
    category = "time"
    state_field = "hour"

    def format_value(self, v: _FormatValues) -> str:
        h12 = v.hour % 12
        if h12 == 0:
            h12 = 12
        return f"{h12:02d}"

    def parse_value(self, s: str, pos: int, state: _ParseState) -> int:
        state.hour, pos = _parse_digits(s, pos, 2)
        if not (1 <= state.hour <= 12):
            raise ValueError(
                f"12-hour format requires hour in 1..12, got {state.hour}"
            )
        return pos


class _Hour12Unpadded(_Field):
    pattern = ("i", 1)
    category = "time"
    state_field = "hour"

    def format_value(self, v: _FormatValues) -> str:
        h12 = v.hour % 12 or 12
        return str(h12)

    def parse_value(self, s: str, pos: int, state: _ParseState) -> int:
        state.hour, pos = _parse_1or2_digits(s, pos)
        if not (1 <= state.hour <= 12):
            raise ValueError(
                f"12-hour format requires hour in 1..12, got {state.hour}"
            )
        return pos


class _Minute(_Field):
    pattern = ("m", 2)
    category = "time"
    state_field = "minute"

    def format_value(self, v: _FormatValues) -> str:
        return f"{v.minute:02d}"

    def parse_value(self, s: str, pos: int, state: _ParseState) -> int:
        state.minute, pos = _parse_digits(s, pos, 2)
        return pos


class _MinuteUnpadded(_Field):
    pattern = ("m", 1)
    category = "time"
    state_field = "minute"

    def format_value(self, v: _FormatValues) -> str:
        return str(v.minute)

    def parse_value(self, s: str, pos: int, state: _ParseState) -> int:
        state.minute, pos = _parse_1or2_digits(s, pos)
        return pos


class _Second(_Field):
    pattern = ("s", 2)
    category = "time"
    state_field = "second"

    def format_value(self, v: _FormatValues) -> str:
        return f"{v.second:02d}"

    def parse_value(self, s: str, pos: int, state: _ParseState) -> int:
        state.second, pos = _parse_digits(s, pos, 2)
        return pos


class _SecondUnpadded(_Field):
    pattern = ("s", 1)
    category = "time"
    state_field = "second"

    def format_value(self, v: _FormatValues) -> str:
        return str(v.second)

    def parse_value(self, s: str, pos: int, state: _ParseState) -> int:
        state.second, pos = _parse_1or2_digits(s, pos)
        return pos


class _SecondOpt(_Field):
    pattern = ("S", 2)
    category = "time"
    state_field = "second"

    def format_value(self, v: _FormatValues) -> str:
        return f"{v.second:02d}" if (v.second or v.nanos) else ""

    def parse_value(self, s: str, pos: int, state: _ParseState) -> int:
        if pos < len(s) and s[pos].isdigit():
            state.second, pos = _parse_digits(s, pos, 2)
        else:
            state.second = 0
            state.second_absent = True
        return pos

    def apply_pending(self, ch: str) -> list[_Element]:
        if ch == ":":
            return [_ColonSec()]
        return [_Literal(ch), self]


class _ColonSec(_Field):
    """Colon + optional seconds: written as ``:ss`` only when second > 0 or nanos > 0.

    Produced by the compiler when a ``:`` literal immediately precedes ``SS``.
    """

    category = "time"
    state_field = "second"

    def format_value(self, v: _FormatValues) -> str:
        return f":{v.second:02d}" if (v.second or v.nanos) else ""

    def parse_value(self, s: str, pos: int, state: _ParseState) -> int:
        if pos < len(s) and s[pos] == ":":
            pos += 1  # consume the colon
            state.second, pos = _parse_digits(s, pos, 2)
        else:
            state.second = 0
            state.second_absent = True
        return pos

    def __repr__(self) -> str:
        return ":SS"


class _FracExact(_Field):
    """Fixed-width fractional seconds (e.g. ``fff`` = 3 digits)."""

    category = "time"
    state_field = "nanos"

    def __init__(self, width: int):
        self.width = width

    def format_value(self, v: _FormatValues) -> str:
        return f"{v.nanos:09d}"[: self.width]

    def parse_value(self, s: str, pos: int, state: _ParseState) -> int:
        val, pos = _parse_digits(s, pos, self.width)
        state.nanos = val * (10 ** (9 - self.width))
        return pos

    def __repr__(self) -> str:
        return "f" * self.width


class _FracTrim(_Field):
    """Trimmed fractional seconds (e.g. ``FFF`` = up to 3 digits)."""

    category = "time"
    state_field = "nanos"

    def __init__(self, width: int):
        self.width = width

    def format_value(self, v: _FormatValues) -> str:
        return f"{v.nanos:09d}"[: self.width].rstrip("0")

    def parse_value(self, s: str, pos: int, state: _ParseState) -> int:
        if state.second_absent:
            state.nanos = 0
            return pos
        count = 0
        while (
            count < self.width
            and pos + count < len(s)
            and s[pos + count].isdigit()
        ):
            count += 1
        if count == 0:
            state.nanos = 0
        else:
            val = int(s[pos : pos + count])
            state.nanos = val * (10 ** (9 - count))
            pos += count
        return pos

    def apply_pending(self, ch: str) -> list[_Element]:
        if ch == ".":
            return [_DotFrac(self.width)]
        return [_Literal(ch), self]


class _DotFrac(_Field):
    """Decimal point + trimmed fractional seconds (``.FFF``).

    Produced by the compiler when a ``'.'`` literal immediately precedes a
    ``FFF``-style specifier. Both the dot and digits are omitted when nanos are zero.
    """

    category = "time"
    state_field = "nanos"

    def __init__(self, width: int):
        self.width = width

    def format_value(self, v: _FormatValues) -> str:
        trimmed = f"{v.nanos:09d}"[: self.width].rstrip("0")
        return f".{trimmed}" if trimmed else ""

    def parse_value(self, s: str, pos: int, state: _ParseState) -> int:
        if state.second_absent or pos >= len(s) or s[pos] != ".":
            state.nanos = 0
            return pos
        pos += 1  # consume the dot
        count = 0
        while (
            count < self.width
            and pos + count < len(s)
            and s[pos + count].isdigit()
        ):
            count += 1
        if count == 0:
            state.nanos = 0
        else:
            val = int(s[pos : pos + count])
            state.nanos = val * (10 ** (9 - count))
        return pos + count

    def __repr__(self) -> str:
        return f".{'F' * self.width}"


class _AmPmShort(_Field):
    pattern = ("a", 1)
    category = "time"
    state_field = "ampm"

    def format_value(self, v: _FormatValues) -> str:
        return "A" if v.hour < 12 else "P"

    def parse_value(self, s: str, pos: int, state: _ParseState) -> int:
        ch = s[pos : pos + 1].upper()
        if ch == "A":
            state.ampm = "AM"
        elif ch == "P":
            state.ampm = "PM"
        else:
            raise ValueError(f"Expected AM/PM at position {pos}, got {ch!r}")
        return pos + 1


class _AmPmFull(_Field):
    pattern = ("a", 2)
    category = "time"
    state_field = "ampm"

    def format_value(self, v: _FormatValues) -> str:
        return "AM" if v.hour < 12 else "PM"

    def parse_value(self, s: str, pos: int, state: _ParseState) -> int:
        chunk = s[pos : pos + 2].upper()
        if chunk == "AM":
            state.ampm = "AM"
        elif chunk == "PM":
            state.ampm = "PM"
        else:
            raise ValueError(
                f"Expected AM/PM at position {pos}, got {chunk!r}"
            )
        return pos + 2


def _format_offset_value(offset_secs: int, width: int, use_z: bool) -> str:
    """Format an offset value according to width and z-substitution rules."""
    if offset_secs == 0 and use_z:
        return "Z"
    sign = "+" if offset_secs >= 0 else "-"
    total = abs(offset_secs)
    oh, remainder = divmod(total, 3600)
    om, os = divmod(remainder, 60)
    if width == 1:
        return f"{sign}{oh:02d}"
    elif width == 2:
        return f"{sign}{oh:02d}{om:02d}"
    elif width == 3:
        return f"{sign}{oh:02d}:{om:02d}"
    elif width == 4:
        base = f"{sign}{oh:02d}{om:02d}"
        return base if os == 0 else f"{base}{os:02d}"
    else:  # width == 5
        base = f"{sign}{oh:02d}:{om:02d}"
        return base if os == 0 else f"{base}:{os:02d}"


def _parse_offset_value(
    s: str, pos: int, width: int, accept_z: bool
) -> tuple[int, int]:
    """Parse an offset value. Returns (offset_secs, new_pos)."""
    if accept_z and pos < len(s) and s[pos] == "Z":
        return 0, pos + 1
    if pos >= len(s) or s[pos] not in "+-":
        raise ValueError(f"Expected offset sign at position {pos}")
    sign = 1 if s[pos] == "+" else -1
    pos += 1
    oh, pos = _parse_digits(s, pos, 2)
    if width == 1:
        return sign * oh * 3600, pos
    if width in (2, 4):
        om, pos = _parse_digits(s, pos, 2)
    else:  # width 3 or 5
        if pos >= len(s) or s[pos] != ":":
            raise ValueError(f"Expected ':' at position {pos}")
        pos += 1
        om, pos = _parse_digits(s, pos, 2)
    if om >= 60:
        raise ValueError("offset minutes must be 0..59")
    os = 0
    if width >= 4:
        has_colon = width == 5
        if has_colon and pos < len(s) and s[pos] == ":":
            pos += 1
            os, pos = _parse_digits(s, pos, 2)
        elif not has_colon and pos < len(s) and s[pos].isdigit():
            os, pos = _parse_digits(s, pos, 2)
        if os >= 60:
            raise ValueError("offset seconds must be 0..59")
    return sign * (oh * 3600 + om * 60 + os), pos


class _OffsetLower(_Field):
    """Lowercase x offset (always numeric, never Z)."""

    category = "offset"
    state_field = "offset_secs"

    def __init__(self, width: int):
        self.width = width

    def format_value(self, v: _FormatValues) -> str:
        if v.offset_secs is None:
            raise ValueError(
                "Cannot format offset: not available for this type"
            )
        return _format_offset_value(v.offset_secs, self.width, use_z=False)

    def parse_value(self, s: str, pos: int, state: _ParseState) -> int:
        state.offset_secs, pos = _parse_offset_value(
            s, pos, self.width, accept_z=False
        )
        return pos

    def __repr__(self) -> str:
        return "x" * self.width


class _OffsetUpper(_Field):
    """Uppercase X offset (Z for zero offset)."""

    category = "offset"
    state_field = "offset_secs"

    def __init__(self, width: int):
        self.width = width

    def format_value(self, v: _FormatValues) -> str:
        if v.offset_secs is None:
            raise ValueError(
                "Cannot format offset: not available for this type"
            )
        return _format_offset_value(v.offset_secs, self.width, use_z=True)

    def parse_value(self, s: str, pos: int, state: _ParseState) -> int:
        state.offset_secs, pos = _parse_offset_value(
            s, pos, self.width, accept_z=True
        )
        return pos

    def __repr__(self) -> str:
        return "X" * self.width


class _TzId(_Field):
    pattern = ("V", 2)
    category = "tz"
    state_field = "tz_id"

    def format_value(self, v: _FormatValues) -> str:
        if v.tz_id is None:
            raise ValueError(
                "Cannot format timezone ID: not available for this type"
            )
        return v.tz_id

    def parse_value(self, s: str, pos: int, state: _ParseState) -> int:
        start = pos
        while pos < len(s) and (s[pos].isalnum() or s[pos] in "/_-+."):
            pos += 1
        if pos == start:
            raise ValueError(f"Expected timezone ID at position {pos}")
        state.tz_id = s[start:pos]
        return pos


class _TzAbbrev(_Field):
    pattern = ("z", 2)
    category = "tz"
    state_field = "tz_abbrev"
    format_only = True

    def format_value(self, v: _FormatValues) -> str:
        if v.tz_abbrev is None:
            raise ValueError(
                "Cannot format timezone abbreviation: "
                "not available for this type"
            )
        return v.tz_abbrev


# --- Spec table (auto-generated from field pattern attributes) ---

_FIXED_FIELDS: list[type[_Field]] = [
    _Year4,
    _Year2,
    _MonthNum,
    _MonthNumUnpadded,
    _MonthAbbr,
    _MonthFull,
    _Day,
    _DayUnpadded,
    _WeekdayAbbr,
    _WeekdayFull,
    _Hour24,
    _Hour24Unpadded,
    _Hour12,
    _Hour12Unpadded,
    _Minute,
    _MinuteUnpadded,
    _Second,
    _SecondUnpadded,
    _SecondOpt,
    _AmPmShort,
    _AmPmFull,
    _TzId,
    _TzAbbrev,
]

# Maps letter → {count → field_class}
_FIXED_SPEC: dict[str, dict[int, type[_Field]]] = {}
for _cls in _FIXED_FIELDS:
    _letter, _count = _cls.pattern
    _FIXED_SPEC.setdefault(_letter, {})[_count] = _cls

# Variable-width fields: letter → (field_class, min_count, max_count)
_VARIABLE_SPEC: dict[str, tuple[type, int, int]] = {
    "f": (_FracExact, 1, 9),
    "F": (_FracTrim, 1, 9),
    "x": (_OffsetLower, 1, 5),
    "X": (_OffsetUpper, 1, 5),
}

# All recognized first characters
_SPEC_CHARS = frozenset(_FIXED_SPEC) | frozenset(_VARIABLE_SPEC)


# --- Pattern compilation ---


def _validate_cross_fields(elements: Iterable[_Element]) -> None:
    """Check for invalid field combinations and duplicates."""
    has_24h = False
    has_12h = False
    has_ampm = False
    seen_state_fields: dict[str, _Field] = {}

    for el in elements:
        if not isinstance(el, _Field):
            continue
        if isinstance(el, (_Hour24, _Hour24Unpadded)):
            has_24h = True
        elif isinstance(el, (_Hour12, _Hour12Unpadded)):
            has_12h = True
        elif isinstance(el, (_AmPmShort, _AmPmFull)):
            has_ampm = True

        sf = el.state_field
        if sf in seen_state_fields:
            raise ValueError(
                f"Duplicate field: {el!r} conflicts with "
                f"{seen_state_fields[sf]!r} (both set {sf})"
            )
        seen_state_fields[sf] = el

    if has_24h and has_ampm:
        raise ValueError(
            "24-hour format (h/hh) cannot be combined with "
            "AM/PM (a/aa). Use 12-hour format (i/ii) instead."
        )
    if has_12h and not has_ampm:
        warnings.warn(
            "12-hour format (i/ii) without AM/PM designator (a/aa) "
            "may be ambiguous",
            stacklevel=4,
        )


# Characters allowed as unquoted literals in patterns.
# Letters must be quoted. Reserved chars (< > [ ] { } #) raise errors.
# '.' and ':' are handled separately as potential compound-token prefixes.
_LITERAL_CHARS = frozenset(
    " \t\n" "0123456789" "-/,;_" "()+@!~*&%$^|\\=?`" '"'
)
_PENDING_CHARS = frozenset(".:")

_RESERVED_CHARS = frozenset("<>[]{}#")


def _compile_quoted_literal(
    pattern: str, i: int, n: int
) -> tuple[int, _Element]:
    """Compile a quoted literal ('...' or escaped quote '').
    Returns (new_pos, element).
    """
    i += 1  # skip opening quote
    if i < n and pattern[i] == "'":
        return i + 1, _Literal("'")
    start = i
    while i < n and pattern[i] != "'":
        i += 1
    if i >= n:
        raise ValueError("Unterminated quoted literal in pattern")
    return i + 1, _Literal(pattern[start:i])  # skip closing quote


def _compile_specifier(
    pattern: str, i: int, n: int, ch: str
) -> tuple[int, _Field]:
    """Compile a specifier (e.g. YYYY, MM, fff).
    Returns (new_pos, field).
    """
    count = 1
    while i + count < n and pattern[i + count] == ch:
        count += 1

    # Variable-width field?
    if ch in _VARIABLE_SPEC:
        cls, _, max_w = _VARIABLE_SPEC[ch]
        if count > max_w:
            raise ValueError(
                f"Too many '{ch}' characters in pattern (max {max_w})"
            )
        return i + count, cls(count)

    # Fixed-width field
    by_count = _FIXED_SPEC[ch]
    try:
        return i + count, by_count[count]()
    except KeyError:
        valid = sorted(by_count, reverse=True)
        raise ValueError(
            f"Unrecognized specifier '{ch * count}' at "
            f"position {i}. Valid counts for '{ch}': {valid}"
        )


@lru_cache(maxsize=64)
def compile_pattern(pattern: str) -> tuple[_Element, ...]:
    """Compile a pattern string into a tuple of elements."""
    if len(pattern) > 1000:
        raise ValueError("Pattern string too long (max 1000 characters)")
    elements: list[_Element] = []
    # A trailing '.' or ':' from the last literal run that may be consumed
    # by the next specifier as part of a compound token (.FFF → _DotFrac,
    # :SS → _ColonSec). Flushed as a plain literal if not consumed.
    pending: str | None = None
    i = 0
    n = len(pattern)

    while i < n:
        ch = pattern[i]

        if not ch.isascii():
            raise ValueError(
                f"Non-ASCII character {ch!r} at position {i}. "
                f"Patterns must be ASCII-only."
            )

        # Quoted literal — pending is never consumed by a quoted literal
        if ch == "'":
            if pending is not None:
                elements.append(_Literal(pending))
                pending = None
            new_i, el = _compile_quoted_literal(pattern, i, n)
            elements.append(el)
            i = new_i
            continue

        # Recognized specifier: delegate pending handling to the field itself
        if ch in _SPEC_CHARS:
            new_i, el = _compile_specifier(pattern, i, n, ch)
            if pending is not None:
                elements.extend(el.apply_pending(pending))
            else:
                elements.append(el)
            pending = None
            i = new_i
            continue

        # From here on, pending (if any) is not consumable — flush it
        if pending is not None:
            elements.append(_Literal(pending))
            pending = None

        # Other ASCII letters are errors (reserved for future specifiers)
        if ch.isalpha():
            raise ValueError(
                f"Unrecognized pattern character '{ch}' at "
                f"position {i}. "
                f"Use quotes for literal text: '...'"
            )

        # Reserved characters
        if ch in _RESERVED_CHARS:
            raise ValueError(
                f"Character '{ch}' at position {i} is reserved "
                f"for future use. Use quotes for literal: '...'"
            )

        # '.' and ':' are held as pending — they may be consumed by the next
        # specifier to form a compound token (e.g. '.FFF' → _DotFrac).
        if ch in _PENDING_CHARS:
            pending = ch
            i += 1
            continue

        # Plain literal characters: collect a run
        if ch in _LITERAL_CHARS:
            start = i
            while i < n and pattern[i] in _LITERAL_CHARS:
                i += 1
            elements.append(_Literal(pattern[start:i]))
            continue

        raise ValueError(
            f"Unexpected character {ch!r} at position {i}. "
            f"Use quotes for literal text: '...'"
        )

    # Flush any pending prefix left at end of pattern (e.g. pattern = "hh:mm.")
    if pending is not None:
        elements.append(_Literal(pending))

    _validate_cross_fields(elements)
    return tuple(elements)


def validate_fields(
    elements: Sequence[_Element],
    allowed_categories: frozenset[str],
    type_name: str,
) -> None:
    """Validate that all fields are allowed for the given type."""
    for el in elements:
        if isinstance(el, _Field) and el.category not in allowed_categories:
            raise ValueError(
                f"{type_name} does not support pattern " f"field {el!r}"
            )


# --- Format ---


def format_fields(
    elements: Sequence[_Element],
    *,
    year: int = 0,
    month: int = 0,
    day: int = 0,
    weekday: int = 0,  # 0=Mon, 6=Sun
    hour: int = 0,
    minute: int = 0,
    second: int = 0,
    nanos: int = 0,
    offset_secs: int | None = None,
    tz_id: str | None = None,
    tz_abbrev: str | None = None,
) -> str:
    """Format values into a string using compiled pattern elements."""
    vals = _FormatValues(
        year=year,
        month=month,
        day=day,
        weekday=weekday,
        hour=hour,
        minute=minute,
        second=second,
        nanos=nanos,
        offset_secs=offset_secs,
        tz_id=tz_id,
        tz_abbrev=tz_abbrev,
    )
    parts: list[str] = []
    for el in elements:
        if isinstance(el, _Literal):
            parts.append(el.text)
        else:
            result = el.format_value(vals)
            if result:
                parts.append(result)
    return "".join(parts)


# --- Parse ---


def parse_fields(
    elements: Sequence[_Element],
    s: str,
) -> _ParseState:
    """Parse a string using compiled pattern elements."""
    if len(s) > 1000:
        raise ValueError("Input string too long (max 1000 characters)")
    state = _ParseState()
    pos = 0

    for el in elements:
        if isinstance(el, _Literal):
            end = pos + len(el.text)
            if s[pos:end] != el.text:
                raise ValueError(
                    f"Expected {el.text!r} at position {pos}, "
                    f"got {s[pos:end]!r}"
                )
            pos = end
        else:
            assert isinstance(el, _Field)
            if el.format_only:
                raise ValueError(
                    f"Field {el!r} is only supported for "
                    f"formatting, not parsing"
                )
            pos = el.parse_value(s, pos, state)

    if pos != len(s):
        raise ValueError(
            f"Unexpected trailing text at position {pos}: " f"{s[pos:]!r}"
        )

    state.resolve()
    return state
