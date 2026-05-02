"""Pure-Python implementation of ItemizedDelta and ItemizedDateDelta.

These types are always pure Python, even when the Rust extension is active.
The Rust extension imports them from this module.
"""

from __future__ import annotations

from collections.abc import ItemsView, KeysView, Mapping, ValuesView
from datetime import date as _date
from typing import (
    TYPE_CHECKING,
    Any,
    Iterator,
    Sequence,
    no_type_check,
    overload,
)
from warnings import warn

from ._common import (
    SPHINX_RUNNING,
    UNSET,
    _Base,
    add_alternate_constructors,
    final,
)
from ._math import (
    DATE_DELTA_UNITS,
    DIFF_FUNCS,
    EXACT_UNITS_STRICT,
    Sign,
    resolve_leap_day,
)
from ._parse import parse_timedelta_component
from ._typing import DateDeltaUnitStr, DeltaUnitStr, RoundModeStr

if TYPE_CHECKING:
    from whenever import (
        Date,
        OffsetDateTime,
        PlainDateTime,
        TimeDelta,
        ZonedDateTime,
    )

_object_new = object.__new__

_BIT_TO_KEY: tuple[str, ...] = (
    "years",
    "months",
    "weeks",
    "days",
    "hours",
    "minutes",
    "seconds",
    "nanoseconds",
)
_KEY_TO_BIT: dict[str, int] = {k: 1 << i for i, k in enumerate(_BIT_TO_KEY)}


class _DeltaKeysView(KeysView):
    """Efficient bit-flag-based KeysView for delta types.

    Since deltas are immutable and have a fixed, sorted set of possible keys,
    all set operations can be implemented using bitwise operations on a
    single int flag — no reference to the delta object is needed.
    """

    __slots__ = ("_flags",)
    __hash__ = None  # type: ignore[assignment]

    def __init__(self, flags: int):
        self._flags = flags

    @classmethod
    def _from_iterable(cls, it: object) -> set[str]:
        return set(it)  # type: ignore[arg-type]

    def __len__(self) -> int:
        return bin(self._flags).count("1")

    def __contains__(self, key: object) -> bool:
        return bool(self._flags & _KEY_TO_BIT.get(key, 0))  # type: ignore[arg-type]

    def __iter__(self) -> Iterator[str]:
        flags = self._flags
        for i, key in enumerate(_BIT_TO_KEY):
            if flags & (1 << i):
                yield key

    def __reversed__(self) -> Iterator[str]:
        flags = self._flags
        for i in range(len(_BIT_TO_KEY) - 1, -1, -1):
            if flags & (1 << i):
                yield _BIT_TO_KEY[i]

    def __and__(self, other: object) -> _DeltaKeysView | set[str]:
        if isinstance(other, _DeltaKeysView):
            return _DeltaKeysView(self._flags & other._flags)
        return set(self) & set(other)  # type: ignore[arg-type]

    __rand__ = __and__

    def __or__(self, other: object) -> _DeltaKeysView | set[str]:
        if isinstance(other, _DeltaKeysView):
            return _DeltaKeysView(self._flags | other._flags)
        return set(self) | set(other)  # type: ignore[arg-type]

    __ror__ = __or__

    def __sub__(self, other: object) -> _DeltaKeysView | set[str]:
        if isinstance(other, _DeltaKeysView):
            return _DeltaKeysView(self._flags & ~other._flags)
        return set(self) - set(other)  # type: ignore[arg-type]

    def __rsub__(self, other: object) -> set[str]:
        return set(other) - set(self)  # type: ignore[arg-type]

    def __xor__(self, other: object) -> _DeltaKeysView | set[str]:
        if isinstance(other, _DeltaKeysView):
            return _DeltaKeysView(self._flags ^ other._flags)
        return set(self) ^ set(other)  # type: ignore[arg-type]

    __rxor__ = __xor__

    def __eq__(self, other: object) -> bool:
        if isinstance(other, _DeltaKeysView):
            return self._flags == other._flags
        return set(self) == set(other)  # type: ignore[arg-type]

    def __le__(self, other: object) -> bool:
        if isinstance(other, _DeltaKeysView):
            return (self._flags & other._flags) == self._flags
        return set(self) <= set(other)  # type: ignore[arg-type]

    def __ge__(self, other: object) -> bool:
        if isinstance(other, _DeltaKeysView):
            return (self._flags & other._flags) == other._flags
        return set(self) >= set(other)  # type: ignore[arg-type]

    def __lt__(self, other: object) -> bool:
        if isinstance(other, _DeltaKeysView):
            f, o = self._flags, other._flags
            return f != o and (f & o) == f
        return set(self) < set(other)  # type: ignore[arg-type]

    def __gt__(self, other: object) -> bool:
        if isinstance(other, _DeltaKeysView):
            f, o = self._flags, other._flags
            return f != o and (f & o) == o
        return set(self) > set(other)  # type: ignore[arg-type]

    def isdisjoint(self, other: object) -> bool:
        if isinstance(other, _DeltaKeysView):
            return not (self._flags & other._flags)
        return all(x not in self for x in other)  # type: ignore[arg-type]

    def __repr__(self) -> str:
        return f"_DeltaKeysView({{{', '.join(repr(k) for k in self)}}})"


_MAX_DELTA_YEARS = 9999
_MAX_DELTA_MONTHS = 9999 * 12
_MAX_DELTA_WEEKS = 9999 * 53
_MAX_DELTA_DAYS = 9999 * 366
_MAX_DELTA_HOURS = _MAX_DELTA_DAYS * 24
_MAX_DELTA_MINUTES = _MAX_DELTA_HOURS * 60
_MAX_DELTA_SECONDS = _MAX_DELTA_MINUTES * 60
_MAX_DELTA_NANOS = _MAX_DELTA_SECONDS * 1_000_000_000
_MAX_SUBSEC_NANOS = 999_999_999

_MAX_DDELTA_DIGITS = 8  # consistent with Rust extension


# Returns (rest_of_string, value, unit), e.g. ("3D", 2, "Y")
def _parse_datedelta_component(s: str, exc: Exception) -> tuple[str, int, str]:
    try:
        split_index, unit = next(
            (i, c) for i, c in enumerate(s) if c in "YMWD"
        )
    except StopIteration:
        raise exc

    raw, rest = s[:split_index], s[split_index + 1 :]

    if not raw.isdigit() or len(raw) > _MAX_DDELTA_DIGITS:
        raise exc

    return rest, int(raw), unit


def _check_bound(i: int | None, max_value: int) -> int | None:
    if i and i > max_value:
        raise ValueError("delta out of range")
    return i


def _check_component(
    value: int, sign: Sign, max_value: int  # may also be UNSET
) -> tuple[int | None, Sign]:
    if value is UNSET:
        return None, sign
    elif value == 0:
        return 0, sign
    elif value < 0:
        if sign == 1:
            raise ValueError("mixed sign in delta")
        sign = -1
        if -value > max_value:
            raise ValueError("delta out of range")
    else:  # value > 0
        if sign == -1:
            raise ValueError("mixed sign in delta")
        sign = 1
        if value > max_value:
            raise ValueError("delta out of range")
    return value, sign


@final
class ItemizedDelta(_Base, Mapping[DeltaUnitStr, int]):
    """A duration that preserves the exact fields it was created with.
    It closely models the ISO 8601 duration format for durations.

    >>> d = ItemizedDelta(weeks=2, days=3, hours=14)
    ItemizedDelta("P2w3dT14h")
    >>> d = ItemizedDelta("P2w3dT14h")
    >>> str(d)
    'P2w3dT14h'

    It behaves like a mapping where the keys are
    the unit names and the values are the amounts.
    Items are ordered from largest to smallest unit.

    >>> d['weeks']
    2
    >>> d.get('minutes')
    None
    >>> dict(d)
    {"weeks": 2, "days": 3, "hours": 14}
    >>> list(d.keys())
    ["weeks", "days", "hours"]
    >>> weeks, days, hours = d.values()
    (2, 3, 14)

    ``ItemizedDelta`` also supports other dictionary-like operations:

    >>> "months" in d  # check for presence of a field
    False
    >>> len(d)  # number of fields set
    3

    Zero values are considered distinct from "missing" values:

    >>> d2 = ItemizedDelta(years=2, weeks=3, hours=0)
    >>> dict(d2)
    {"years": 2, "weeks": 3, "hours": 0}

    Additionally, no normalization is performed.
    Months are not rolled into years, minutes into hours, etc.

    >>> d3 = ItemizedDelta(months=24, minutes=90)
    ItemizedDelta("P24mT90m")

    Empty durations are not allowed. At least one field must be set (but it can be zero):

    >>> ItemizedDelta()
    ValueError: At least one field must be set
    >>> ItemizedDelta(seconds=0)
    ItemizedDelta("PT0s")

    Negative durations are supported, but all fields must have the same sign:

    >>> d4 = ItemizedDelta(years=-1, weeks=-2, days=0)
    ItemizedDelta("-P1y2w0d")
    >>> ItemizedDelta(years=1, days=-3)
    ValueError: All fields must have the same sign

    Note
    ----
    Unlike :class:`TimeDelta`, ``ItemizedDelta`` does not normalize
    its fields. This means that ``ItemizedDelta(hours=90)`` and
    ``ItemizedDelta(days=3, hours=18)`` are considered different values.
    To convert to a normalized form, use :meth:`in_units`.
    See also the `delta documentation <https://whenever.rtfd.io/en/latest/guide/deltas.html>`_.
    """

    __module__ = "whenever"

    __slots__ = (
        # Values are stored as signed integers (or None if not set).
        # All non-zero fields must have the same sign.
        "_years",
        "_months",
        "_weeks",
        "_days",
        "_hours",
        "_minutes",
        "_seconds",
        # FUTURE: allow nanoseconds to exceed 999,999,999?
        "_nanoseconds",
    )

    def _has_cal(self) -> bool:
        """True if this delta has any calendar units (years, months, weeks, days) set."""
        return (
            self._years is not None
            or self._months is not None
            or self._weeks is not None
            or self._days is not None
        )

    def _has_exact_time(self) -> bool:
        """True if this delta has any exact time units (hours, minutes, seconds, nanoseconds) set."""
        return (
            self._hours is not None
            or self._minutes is not None
            or self._seconds is not None
            or self._nanoseconds is not None
        )

    # Overloads for a nice autodoc.
    # Proper typing of the constructors is handled in the type stubs
    if not TYPE_CHECKING:

        @overload
        def __init__(self, iso_string: str, /) -> None: ...

        @overload
        def __init__(
            self,
            *,
            years: int = ...,
            months: int = ...,
            weeks: int = ...,
            days: int = ...,
            hours: int = ...,
            minutes: int = ...,
            seconds: int = ...,
            nanoseconds: int = ...,
        ) -> None: ...

    def __init__(
        self,
        *,
        years: int = UNSET,
        months: int = UNSET,
        weeks: int = UNSET,
        days: int = UNSET,
        hours: int = UNSET,
        minutes: int = UNSET,
        seconds: int = UNSET,
        nanoseconds: int = UNSET,
    ) -> None:
        sign: Sign = 0
        if nanoseconds is not UNSET and seconds is UNSET:
            seconds = 0

        self._years, sign = _check_component(years, sign, _MAX_DELTA_YEARS)
        self._months, sign = _check_component(months, sign, _MAX_DELTA_MONTHS)
        self._weeks, sign = _check_component(weeks, sign, _MAX_DELTA_WEEKS)
        self._days, sign = _check_component(days, sign, _MAX_DELTA_DAYS)
        self._hours, sign = _check_component(hours, sign, _MAX_DELTA_HOURS)
        self._minutes, sign = _check_component(
            minutes, sign, _MAX_DELTA_MINUTES
        )
        self._seconds, sign = _check_component(
            seconds, sign, _MAX_DELTA_SECONDS
        )
        self._nanoseconds, sign = _check_component(
            nanoseconds, sign, _MAX_SUBSEC_NANOS
        )
        if (
            years is UNSET
            and months is UNSET
            and weeks is UNSET
            and days is UNSET
            and hours is UNSET
            and minutes is UNSET
            and seconds is UNSET
            and nanoseconds is UNSET
        ):
            # This is to ensure ISO8601 formatting/parsing is round-trip safe.
            # There is no "empty" duration in ISO8601; at least one field must be present.
            raise ValueError("at least one field must be set")

    __init__ = add_alternate_constructors(__init__)

    def sign(self) -> Sign:
        """The sign of the delta, 1, 0, or -1"""
        for v in (
            self._years,
            self._months,
            self._weeks,
            self._days,
            self._hours,
            self._minutes,
            self._seconds,
            self._nanoseconds,
        ):
            if v:
                return 1 if v > 0 else -1
        return 0

    # FUTURE: a float_seconds method that combines seconds and nanoseconds into a single float value?

    def __iter__(self) -> Iterator[DeltaUnitStr]:
        """Iterate over all non-missing fields, ordered from largest to smallest unit."""
        if self._years is not None:
            yield "years"
        if self._months is not None:
            yield "months"
        if self._weeks is not None:
            yield "weeks"
        if self._days is not None:
            yield "days"
        if self._hours is not None:
            yield "hours"
        if self._minutes is not None:
            yield "minutes"
        if self._seconds is not None:
            yield "seconds"
        if self._nanoseconds is not None:
            yield "nanoseconds"

    def keys(self) -> KeysView:
        """The names of all defined fields, in order of largest to smallest unit.

        Part of the mapping protocol
        """
        return _DeltaKeysView(
            ((self._years is not None) << 0)
            | ((self._months is not None) << 1)
            | ((self._weeks is not None) << 2)
            | ((self._days is not None) << 3)
            | ((self._hours is not None) << 4)
            | ((self._minutes is not None) << 5)
            | ((self._seconds is not None) << 6)
            | ((self._nanoseconds is not None) << 7)
        )

    # These methods defer to the base class implementations, but need to be
    # documented here for the API docs.
    if not TYPE_CHECKING:  # pragma: no cover
        if SPHINX_RUNNING:

            # FUTURE: an optimized ValuesView class that defers to the internal
            # fields directly instead of going through __getitem__
            def values(self) -> ValuesView[int]:
                """Return all defined field values, in order
                of largest to smallest unit.

                >>> d = ItemizedDelta(years=3, hours=12, days=0)
                >>> years, days, hours = d.values()
                (3, 0, 12)
                >>> list(d.values())
                [3, 0, 12]

                Part of the mapping protocol
                """
                ...

            def items(self) -> ItemsView[DeltaUnitStr, int]:
                """Return all defined fields as (unit, value) pairs
                ordered from largest to smallest unit.

                >>> d = ItemizedDelta(years=3, hours=12, days=0)
                >>> list(d.items())
                [('years', 3), ('days', 0), ('hours', 12)]

                Part of the mapping protocol
                """
                ...

            @overload
            def get(self, key: DeltaUnitStr, /) -> int | None: ...

            @overload
            def get(self, key: DeltaUnitStr, default: int, /) -> int: ...

            def get(
                self, key: DeltaUnitStr, default: object = None, /
            ) -> object:
                """Get the value of a specific field by name, or return default if not set.

                Part of the mapping protocol
                """
                ...

    def __getitem__(self, key: str) -> int:
        """Get the value of a specific field by name.

        >>> d = ItemizedDelta(weeks=1, days=3)
        >>> d["weeks"]
        1
        >>> d["days"]
        3
        >>> d["hours"]
        KeyError: 'hours'
        """
        match key:
            case "years":
                value = self._years
            case "months":
                value = self._months
            case "weeks":
                value = self._weeks
            case "days":
                value = self._days
            case "hours":
                value = self._hours
            case "minutes":
                value = self._minutes
            case "seconds":
                value = self._seconds
            case "nanoseconds":
                value = self._nanoseconds
            case _:
                raise KeyError(key)

        if value is not None:
            return value

        raise KeyError(key)

    def __len__(self) -> int:
        """Get the number of fields that are set.

        >>> d = ItemizedDelta(weeks=1, days=3)
        >>> len(d)
        2
        """
        return (
            (self._years is not None)
            + (self._months is not None)
            + (self._weeks is not None)
            + (self._days is not None)
            + (self._hours is not None)
            + (self._minutes is not None)
            + (self._seconds is not None)
            + (self._nanoseconds is not None)
        )

    def __contains__(self, key: object) -> bool:
        """Check if a specific field is set.

        >>> d = ItemizedDelta(weeks=1, days=3)
        >>> "weeks" in d
        True
        >>> "hours" in d
        False
        """
        if key == "years":
            return self._years is not None
        elif key == "months":
            return self._months is not None
        elif key == "weeks":
            return self._weeks is not None
        elif key == "days":
            return self._days is not None
        elif key == "hours":
            return self._hours is not None
        elif key == "minutes":
            return self._minutes is not None
        elif key == "seconds":
            return self._seconds is not None
        elif key == "nanoseconds":
            return self._nanoseconds is not None
        return False

    def __bool__(self) -> bool:
        """An ItemizedDelta is considered False if its sign is 0.

        >>> bool(ItemizedDelta(weeks=0))
        False
        >>> bool(ItemizedDelta(weeks=1))
        True
        """
        return bool(
            self._years
            or self._months
            or self._weeks
            or self._days
            or self._hours
            or self._minutes
            or self._seconds
            or self._nanoseconds
        )

    def format_iso(self, *, lowercase_units: bool = False) -> str:
        """Format as the *popular interpretation* of the ISO 8601 duration format.
        May not strictly adhere to (all versions of) the standard.
        See :ref:`here <iso8601-durations>` for more information.

        Inverse of :meth:`parse_iso`.

        The format is:

        .. code-block:: text

            P(nY)(nM)(nW)(nD)T(nH)(nM)(nS)

        >>> d = ItemizedDelta(
        ...     weeks=1,
        ...     days=11,
        ...     hours=4,
        ...     seconds=1,
        ...     nanoseconds=12_000,
        ... )
        >>> d.format_iso()
        'P1W11DT4H1.000012S'
        """
        y, m, w, d, h, s = "ymwdhs" if lowercase_units else "YMWDHS"

        sgn = self.sign()
        parts = ["-" * (sgn < 0), "P"]
        if self._years is not None:
            parts.append(f"{abs(self._years)}{y}")
        if self._months is not None:
            parts.append(f"{abs(self._months)}{m}")
        if self._weeks is not None:
            parts.append(f"{abs(self._weeks)}{w}")
        if self._days is not None:
            parts.append(f"{abs(self._days)}{d}")

        parts.append("T")

        if self._hours is not None:
            parts.append(f"{abs(self._hours)}{h}")
        if self._minutes is not None:
            parts.append(f"{abs(self._minutes)}{m}")
        if self._seconds is not None:
            if self._nanoseconds is None:
                parts.append(f"{abs(self._seconds)}{s}")
            elif self._nanoseconds:
                parts.append(
                    f"{abs(self._seconds)}.{abs(self._nanoseconds):09d}".rstrip(
                        "0"
                    )
                    + s
                )
            else:
                parts.append(f"{abs(self._seconds)}.0{s}")

        joined = "".join(parts)
        if joined.endswith("T"):  # skip the T if no time fields
            return joined[:-1]
        # NOTE: we always have at least one field,
        # so we don't need to check for "empty" durations.
        return joined

    @classmethod
    def parse_iso(cls, s: str, /) -> ItemizedDelta:
        """Parse the *popular interpretation* of the ISO 8601 duration format.
        Does not parse all possible ISO 8601 durations.
        See :ref:`here <iso8601-durations>` for more information.

        .. code-block:: text

           P4D        # 4 days
           PT4H       # 4 hours
           PT0M       # 0 minutes
           PT3M40.5S  # 3 minutes and 40.5 seconds
           P1W11DT90M # 1 week, 11 days, and 90 minutes
           -PT7H400M  # -7 hours and -400 minutes
           +PT7H4M    # 7 hours and 4 minutes (7:04:00)

        Inverse of :meth:`format_iso`

        >>> ItemizeDelta.parse_iso("-P1W11DT4H")
        ItemizeDelta("-P1w11dT4h")
        """
        exc = ValueError(f"Invalid format: {s!r}")
        prev_unit = ""
        years, months, weeks, days, hours, minutes, seconds, nanos = (
            None,
        ) * 8

        # Catch certain invalid strings early, making parsing easier
        if len(s) < 3 or not s.isascii() or s.endswith("T"):
            raise exc

        sign: Sign
        s = s.upper()
        if s[0] == "P":
            sign = 1
            rest = s[1:]
        elif s.startswith("-P"):
            sign = -1
            rest = s[2:]
        elif s.startswith("+P"):
            sign = 1
            rest = s[2:]
        else:
            raise exc

        # parse the date part
        while rest and not rest.startswith("T"):
            rest, value, unit = _parse_datedelta_component(rest, exc)

            if unit == "Y" and prev_unit == "":
                years = value
            elif unit == "M" and prev_unit in "Y":
                months = value
            elif unit == "W" and prev_unit in "YM":
                weeks = value
            elif unit == "D" and prev_unit in "YMW":
                days = value
                break
            else:
                raise exc  # components out of order

            prev_unit = unit

        prev_unit = ""
        if rest and not rest.startswith("T"):
            raise exc

        # skip the "T" separator
        rest = rest[1:]

        while rest:
            rest_new, value, unit = parse_timedelta_component(rest, exc)

            if unit == "H" and prev_unit == "":
                hours = value
            elif unit == "M" and prev_unit in "H":
                minutes = value
            elif unit == "S":
                seconds = value // 1_000_000_000
                # Only set nanos if there are fractional digits
                if "," in rest or "." in rest:
                    nanos = value % 1_000_000_000
                if rest_new:
                    raise exc
                break
            else:
                raise exc

            rest = rest_new
            prev_unit = unit

        if not (
            years
            or months
            or weeks
            or days
            or hours
            or minutes
            or seconds
            or nanos
        ):
            sign = 0

        # NOTE: we've implicitly validated that at least one field is set
        return cls._from_signed(
            sign,
            years,
            months,
            weeks,
            days,
            hours,
            minutes,
            seconds,
            nanos,
        )

    def date_and_time_parts(
        self,
    ) -> tuple[ItemizedDateDelta | None, TimeDelta | None]:
        """Split into date and time parts.

        Either part may be None if no fields were set of that type.
        At least one part will be non-None, since at least one field must be set.

        >>> d = ItemizedDelta(
        ...     years=1,
        ...     months=2,
        ...     weeks=3,
        ...     days=4,
        ...     hours=5,
        ...     minutes=6,
        ...     seconds=7,
        ...     nanoseconds=8,
        ... )
        >>> date_part, time_part = d.date_and_time_parts()
        >>> date_part
        ItemizedDateDelta("P1y2m3w4d")
        >>> time_part
        TimeDelta("P5h6m7.000000008s")
        >>> ItemizedDelta(weeks=2).date_and_time_parts()
        (ItemizedDateDelta("P2w"), None)

        """
        from ._core import TimeDelta

        years, months, weeks, days = date_values = (
            self._years,
            self._months,
            self._weeks,
            self._days,
        )
        if all(v is None for v in date_values):
            date_part = None
        else:
            sgn = self.sign()
            date_part = ItemizedDateDelta._from_signed(
                sgn if any(date_values) else 0,
                years=abs(years) if years is not None else None,
                months=abs(months) if months is not None else None,
                weeks=abs(weeks) if weeks is not None else None,
                days=abs(days) if days is not None else None,
            )

        hours, minutes, seconds, nanoseconds = time_values = (
            self._hours,
            self._minutes,
            self._seconds,
            self._nanoseconds,
        )
        if all(v is None for v in time_values):
            time_part = None
        else:
            time_part = TimeDelta(
                hours=hours or 0,
                minutes=minutes or 0,
                seconds=seconds or 0,
                nanoseconds=nanoseconds or 0,
            )
        return date_part, time_part

    # A private constructor that bypasses sign/presence validation.
    # All field values must be non-negative; `sign` is applied when storing.
    @classmethod
    def _from_signed(
        cls,
        sign: Sign,
        years: int | None = None,
        months: int | None = None,
        weeks: int | None = None,
        days: int | None = None,
        hours: int | None = None,
        minutes: int | None = None,
        seconds: int | None = None,
        nanoseconds: int | None = None,
    ) -> ItemizedDelta:
        self = _object_new(cls)

        def _apply(v: int | None, max_val: int) -> int | None:
            v = _check_bound(v, max_val)
            return -v if v and sign < 0 else v

        self._years = _apply(years, _MAX_DELTA_YEARS)
        self._months = _apply(months, _MAX_DELTA_MONTHS)
        self._weeks = _apply(weeks, _MAX_DELTA_WEEKS)
        self._days = _apply(days, _MAX_DELTA_DAYS)
        self._hours = _apply(hours, _MAX_DELTA_HOURS)
        self._minutes = _apply(minutes, _MAX_DELTA_MINUTES)
        self._seconds = _apply(seconds, _MAX_DELTA_SECONDS)
        self._nanoseconds = _apply(nanoseconds, _MAX_SUBSEC_NANOS)
        return self

    def __eq__(self, other: object) -> bool:
        """Compare for equality. Each field is individually compared.
        No normalization is performed. Zero values are considered equivalent
        to missing values.

        Thus, ``ItemizedDelta(weeks=1, seconds=0) == ItemizedDelta(weeks=1)``

        >>> d = ItemizedDelta(weeks=2, minutes=90)
        >>> d == ItemizedDelta(weeks=2, minutes=90)
        True
        >>> d == ItemizedDelta(weeks=2, minutes=91)
        False

        If you want strict equality (including presence of fields),
        use :meth:`exact_eq`.

        """
        if not isinstance(other, ItemizedDelta):
            return NotImplemented
        return (
            (self._years or 0) == (other._years or 0)
            and (self._months or 0) == (other._months or 0)
            and (self._weeks or 0) == (other._weeks or 0)
            and (self._days or 0) == (other._days or 0)
            and (self._hours or 0) == (other._hours or 0)
            and (self._minutes or 0) == (other._minutes or 0)
            and (self._seconds or 0) == (other._seconds or 0)
            and (self._nanoseconds or 0) == (other._nanoseconds or 0)
        )

    def exact_eq(self, other: ItemizedDelta, /) -> bool:
        """Check for strict equality. All fields *and their presence* must match."""
        return (
            self._years == other._years
            and self._months == other._months
            and self._weeks == other._weeks
            and self._days == other._days
            and self._hours == other._hours
            and self._minutes == other._minutes
            and self._seconds == other._seconds
            and self._nanoseconds == other._nanoseconds
        )

    def __abs__(self) -> ItemizedDelta:
        """If the contents are negative, return the positive version

        >>> d = ItemizedDelta(weeks=-2, days=-3)
        >>> abs(d)
        ItemizedDelta("P2w3d")
        """
        if self.sign() >= 0:
            return self
        return ItemizedDelta._from_signed(
            1,
            abs(self._years) if self._years is not None else None,
            abs(self._months) if self._months is not None else None,
            abs(self._weeks) if self._weeks is not None else None,
            abs(self._days) if self._days is not None else None,
            abs(self._hours) if self._hours is not None else None,
            abs(self._minutes) if self._minutes is not None else None,
            abs(self._seconds) if self._seconds is not None else None,
            abs(self._nanoseconds) if self._nanoseconds is not None else None,
        )

    def __neg__(self) -> ItemizedDelta:
        """Invert the sign of the contents

        >>> d = ItemizedDelta(weeks=2, days=3)
        >>> -d
        ItemizedDelta("-P2w3d")
        >>> --d
        ItemizedDelta("P2w3d")
        """
        if self.sign() == 0:
            return self
        return ItemizedDelta._from_signed(
            -self.sign(),
            abs(self._years) if self._years is not None else None,
            abs(self._months) if self._months is not None else None,
            abs(self._weeks) if self._weeks is not None else None,
            abs(self._days) if self._days is not None else None,
            abs(self._hours) if self._hours is not None else None,
            abs(self._minutes) if self._minutes is not None else None,
            abs(self._seconds) if self._seconds is not None else None,
            abs(self._nanoseconds) if self._nanoseconds is not None else None,
        )

    @overload
    def add(
        self,
        other: ItemizedDelta,
        /,
        *,
        relative_to: ZonedDateTime,
        in_units: Sequence[DeltaUnitStr],
        round_mode: RoundModeStr = ...,
        round_increment: int = ...,
    ) -> ItemizedDelta: ...

    @overload
    def add(
        self,
        /,
        *,
        years: int = ...,
        months: int = ...,
        weeks: int = ...,
        days: int = ...,
        hours: int = ...,
        minutes: int = ...,
        seconds: int = ...,
        nanoseconds: int = ...,
        relative_to: ZonedDateTime,
        in_units: Sequence[DeltaUnitStr],
        round_mode: RoundModeStr = ...,
        round_increment: int = ...,
    ) -> ItemizedDelta: ...

    def add(
        self,
        arg: ItemizedDelta = UNSET,
        /,
        *,
        relative_to: ZonedDateTime,
        in_units: Sequence[DeltaUnitStr],
        round_mode: RoundModeStr = "trunc",
        round_increment: int = 1,
        **kwargs: Any,
    ) -> ItemizedDelta:
        """Add time to this delta, returning a new delta"""
        valid_keys = frozenset(
            {
                "years",
                "months",
                "weeks",
                "days",
                "hours",
                "minutes",
                "seconds",
                "nanoseconds",
            }
        )
        if kwargs:
            if arg is not UNSET:
                raise TypeError("Cannot mix positional and keyword arguments")
            invalid = set(kwargs) - valid_keys
            if invalid:
                raise TypeError(
                    f"Unexpected keyword argument: {next(iter(invalid))!r}"
                )
        elif arg is not UNSET:
            # In this case the mapping types are interchangeable
            kwargs = arg  # type: ignore[assignment]
        else:
            return self

        return relative_to.add(
            years=self.get("years", 0) + kwargs.get("years", 0),
            months=self.get("months", 0) + kwargs.get("months", 0),
            weeks=self.get("weeks", 0) + kwargs.get("weeks", 0),
            days=self.get("days", 0) + kwargs.get("days", 0),
            hours=self.get("hours", 0) + kwargs.get("hours", 0),
            minutes=self.get("minutes", 0) + kwargs.get("minutes", 0),
            seconds=self.get("seconds", 0) + kwargs.get("seconds", 0),
            nanoseconds=self.get("nanoseconds", 0)
            + kwargs.get("nanoseconds", 0),
        ).since(
            relative_to,
            in_units=in_units,
            round_mode=round_mode,
            round_increment=round_increment,
        )

    @overload
    def subtract(
        self,
        other: ItemizedDelta,
        /,
        *,
        relative_to: ZonedDateTime,
        in_units: Sequence[DeltaUnitStr],
        round_mode: RoundModeStr = ...,
        round_increment: int = ...,
    ) -> ItemizedDelta: ...

    @overload
    def subtract(
        self,
        /,
        *,
        years: int = ...,
        months: int = ...,
        weeks: int = ...,
        days: int = ...,
        hours: int = ...,
        minutes: int = ...,
        seconds: int = ...,
        nanoseconds: int = ...,
        relative_to: ZonedDateTime,
        in_units: Sequence[DeltaUnitStr],
        round_mode: RoundModeStr = ...,
        round_increment: int = ...,
    ) -> ItemizedDelta: ...

    def subtract(
        self,
        arg: ItemizedDelta = UNSET,
        /,
        *,
        relative_to: ZonedDateTime,
        in_units: Sequence[DeltaUnitStr],
        round_mode: RoundModeStr = "trunc",
        round_increment: int = 1,
        **kwargs: Any,
    ) -> ItemizedDelta:
        """Inverse of :meth:`add`."""
        arg = -arg if arg is not UNSET else UNSET
        return self.add(
            arg,
            **{k: -v for k, v in kwargs.items()},
            relative_to=relative_to,
            in_units=in_units,
            round_mode=round_mode,
            round_increment=round_increment,
        )

    def in_units(
        self,
        units: Sequence[DeltaUnitStr],
        /,
        *,
        relative_to: ZonedDateTime | PlainDateTime | OffsetDateTime,
        round_mode: RoundModeStr = "trunc",
        round_increment: int = 1,
    ) -> ItemizedDelta:
        """Convert this delta into the specified units. A `relative_to` datetime
        is required to resolve calendar units.

        >>> d = ItemizedDelta(years=1, months=8, minutes=1000)
        >>> d.in_units(["weeks", "hours"], relative_to=ZonedDateTime(2020, 6, 30, 12, tz="Asia/Tokyo"))
        ItemizedDelta("P86w160h")

        Parameters
        ----------
        relative_to
            A :class:`ZonedDateTime`, :class:`PlainDateTime`, or
            :class:`OffsetDateTime` reference point.

            - :class:`ZonedDateTime`: DST-aware; emits no warning
            - :class:`PlainDateTime`: emits :class:`NaiveArithmeticWarning`
              when the conversion crosses the calendar/exact-time boundary
              (i.e. the delta or output mixes calendar and exact-time units).
              Pure calendar-to-calendar or exact-to-exact conversions do not warn.
            - :class:`OffsetDateTime`: emits :class:`StaleOffsetWarning`
              when the delta contains calendar units (years, months, weeks, days)
              **or** the output units include calendar units
        """
        from ._core import (
            NaiveArithmeticWarning,
            OffsetDateTime,
            PlainDateTime,
            StaleOffsetWarning,
            ZonedDateTime,
        )
        from ._pywhenever import (
            PLAIN_RELATIVE_TO_UNAWARE_MSG,
            STALE_OFFSET_CALENDAR_MSG,
        )

        has_exact_in_units = any(map(EXACT_UNITS_STRICT.__contains__, units))
        has_cal_in_units = any(map(DATE_DELTA_UNITS.__contains__, units))
        if isinstance(relative_to, PlainDateTime):
            if (self._has_exact_time() or has_exact_in_units) and (
                self._has_cal() or has_cal_in_units
            ):
                warn(
                    PLAIN_RELATIVE_TO_UNAWARE_MSG,
                    NaiveArithmeticWarning,
                    stacklevel=2,
                )
            relative_to = relative_to.assume_tz("UTC")
        elif isinstance(relative_to, OffsetDateTime):
            if self._has_cal() or has_cal_in_units:
                warn(
                    StaleOffsetWarning(STALE_OFFSET_CALENDAR_MSG),
                    stacklevel=2,
                )
            relative_to = relative_to.to_plain().assume_tz("UTC")
        elif not isinstance(relative_to, ZonedDateTime):
            raise TypeError(
                "relative_to must be a ZonedDateTime, PlainDateTime, or OffsetDateTime"
            )
        return relative_to.add(self).since(
            relative_to,
            in_units=units,
            round_mode=round_mode,
            round_increment=round_increment,
        )

    def total(
        self,
        unit: DeltaUnitStr,
        /,
        *,
        relative_to: ZonedDateTime | PlainDateTime | OffsetDateTime,
    ) -> float:
        """Return the total duration expressed in the specified unit as a float

        Parameters
        ----------
        relative_to
            A :class:`ZonedDateTime`, :class:`PlainDateTime`, or
            :class:`OffsetDateTime` reference point.

            - :class:`ZonedDateTime`: DST-aware; emits no warning
            - :class:`PlainDateTime`: emits :class:`NaiveArithmeticWarning`
              when the conversion crosses the calendar/exact-time boundary
              (i.e. the delta or target unit mixes calendar and exact-time units).
              Pure calendar-to-calendar or exact-to-exact conversions do not warn.
            - :class:`OffsetDateTime`: emits :class:`StaleOffsetWarning`
              when the delta contains calendar units (years, months, weeks, days)
              **or** the target unit is a calendar unit
        """
        from ._core import (
            NaiveArithmeticWarning,
            OffsetDateTime,
            PlainDateTime,
            StaleOffsetWarning,
            ZonedDateTime,
        )
        from ._pywhenever import (
            PLAIN_RELATIVE_TO_UNAWARE_MSG,
            STALE_OFFSET_CALENDAR_MSG,
        )

        is_exact_unit = unit in EXACT_UNITS_STRICT
        if isinstance(relative_to, PlainDateTime):
            if (self._has_exact_time() or is_exact_unit) and (
                self._has_cal() or not is_exact_unit
            ):
                warn(
                    PLAIN_RELATIVE_TO_UNAWARE_MSG,
                    NaiveArithmeticWarning,
                    stacklevel=2,
                )
            relative_to = relative_to.assume_tz("UTC")
        elif isinstance(relative_to, OffsetDateTime):
            if self._has_cal() or not is_exact_unit:
                warn(
                    StaleOffsetWarning(STALE_OFFSET_CALENDAR_MSG),
                    stacklevel=2,
                )
            relative_to = relative_to.to_plain().assume_tz("UTC")
        elif not isinstance(relative_to, ZonedDateTime):
            raise TypeError(
                "relative_to must be a ZonedDateTime, PlainDateTime, or OffsetDateTime"
            )
        return (relative_to.add(self) - relative_to).total(
            unit, relative_to=relative_to
        )

    if not TYPE_CHECKING:
        # This overload ensures it shows up nicely in the API docs, not just as "kwargs"
        @overload
        def replace(
            self,
            *,
            years: int | None = ...,
            months: int | None = ...,
            weeks: int | None = ...,
            days: int | None = ...,
            hours: int | None = ...,
            minutes: int | None = ...,
            seconds: int | None = ...,
            nanoseconds: int | None = ...,
        ) -> ItemizedDelta: ...

    def replace(self, **kwargs: int | None) -> ItemizedDelta:
        """Return a new delta with specific fields replaced.
        Fields set to ``None`` will be removed.

        All normal validation rules apply.

        >>> d = ItemizedDelta(years=1, months=2, hours=3)
        >>> d.replace(months=None, hours=2)
        ItemizedDelta("P1yT2h")
        """
        kwargs_w_sentinel = {
            k: UNSET if v is None else v for k, v in kwargs.items()
        }
        fields = {**self, **kwargs_w_sentinel}
        if all(v is UNSET for v in fields.values()):
            raise ValueError("at least one field must remain set")
        return ItemizedDelta(**fields)

    @no_type_check
    def __reduce__(self):
        return (
            _unpkl_idelta,
            (
                self._years,
                self._months,
                self._weeks,
                self._days,
                self._hours,
                self._minutes,
                self._seconds,
                self._nanoseconds,
            ),
        )

    def __repr__(self) -> str:
        return f'ItemizedDelta("{self.format_iso(lowercase_units=True)}")'

    __str__ = format_iso

    def _init_from_iso(self, s: str) -> None:
        parsed = type(self).parse_iso(s)
        self._years = parsed._years
        self._months = parsed._months
        self._weeks = parsed._weeks
        self._days = parsed._days
        self._hours = parsed._hours
        self._minutes = parsed._minutes
        self._seconds = parsed._seconds
        self._nanoseconds = parsed._nanoseconds

    def _to_tuple(self):  # pragma: no cover
        return (
            self._years,
            self._months,
            self._weeks,
            self._days,
            self._hours,
            self._minutes,
            self._seconds,
            self._nanoseconds,
        )


# A separate unpickling function allows us to make backwards-compatible changes
# to the pickling format in the future
def _unpkl_idelta(
    years: int | None,
    months: int | None,
    weeks: int | None,
    days: int | None,
    hours: int | None,
    minutes: int | None,
    seconds: int | None,
    nanoseconds: int | None,
) -> ItemizedDelta:
    self = _object_new(ItemizedDelta)
    self._years = years
    self._months = months
    self._weeks = weeks
    self._days = days
    self._hours = hours
    self._minutes = minutes
    self._seconds = seconds
    self._nanoseconds = nanoseconds
    return self


@final
class ItemizedDateDelta(_Base, Mapping[DateDeltaUnitStr, int]):
    """A date duration that preserves the exact fields it was created with.
    It closely models the ISO 8601 duration format for date-only durations.

    >>> d = ItemizedDateDelta(years=2, weeks=3)
    ItemizedDateDelta("P2Y3W")
    >>> d = ItemizedDateDelta("P22W")
    >>> str(d)
    'P22W'

    It behaves like a mapping where the keys are
    the unit names and the values are the amounts.
    Items are ordered from largest to smallest unit.

    >>> d['weeks']
    22
    >>> d.get('days')
    None
    >>> dict(d)
    {"years": 2, "weeks": 3}
    >>> list(d.keys())
    ["years", "weeks"]
    >>> years, weeks = d.values()
    (2, 3)

    ``ItemizedDateDelta`` also supports other dictionary-like operations:

    >>> "days" in d  # check for presence of a field
    False
    >>> len(d)  # number of fields set
    2

    Zero values are considered distinct from "missing" values:

    >>> d2 = ItemizedDateDelta(years=2, weeks=3, days=0)
    >>> dict(d2)
    {"years": 2, "weeks": 3, "days": 0}

    Additionally, no normalization is performed.
    Months are not rolled into years, weeks into days, etc.

    >>> d3 = ItemizedDateDelta(months=24, days=100)
    ItemizedDateDelta("P24m100d")

    Empty durations are not allowed. At least one field must be set (but it can be zero):

    >>> ItemizedDateDelta()
    ValueError: At least one field must be set
    >>> ItemizedDateDelta(days=0)
    ItemizedDateDelta("P0d")

    Negative durations are supported, but all fields must have the same sign:

    >>> d4 = ItemizedDateDelta(years=-1, weeks=-2, days=0)
    ItemizedDateDelta("-P1y2w0d")
    >>> ItemizedDateDelta(years=1, days=-3)
    ValueError: All fields must have the same sign

    Note
    ----
    Unlike its predecessor ``DateDelta``, ``ItemizedDateDelta`` does not normalize
    its fields. This means that ``ItemizedDateDelta(months=14)`` and
    ``ItemizedDateDelta(years=1, months=2)`` are considered different values.
    To convert to a normalized form, use :meth:`in_units`.
    See also the `delta documentation <https://whenever.rtfd.io/en/latest/guide/deltas.html>`_.
    """

    __module__ = "whenever"

    __slots__ = (
        # Values are stored as signed integers (or None if not set).
        # All non-zero fields must have the same sign.
        "_years",
        "_months",
        "_weeks",
        "_days",
    )

    # Overloads for a nice autodoc.
    # Proper typing of the constructors is handled in the type stubs
    if not TYPE_CHECKING:

        @overload
        def __init__(self, iso_string: str, /) -> None: ...

        @overload
        def __init__(
            self,
            *,
            years: int = ...,
            months: int = ...,
            weeks: int = ...,
            days: int = ...,
        ) -> None: ...

    def __init__(
        self,
        *,
        years: int = UNSET,
        months: int = UNSET,
        weeks: int = UNSET,
        days: int = UNSET,
    ) -> None:
        sign: Sign = 0
        self._years, sign = _check_component(years, sign, _MAX_DELTA_YEARS)
        self._months, sign = _check_component(months, sign, _MAX_DELTA_MONTHS)
        self._weeks, sign = _check_component(weeks, sign, _MAX_DELTA_WEEKS)
        self._days, sign = _check_component(days, sign, _MAX_DELTA_DAYS)
        if (
            years is UNSET
            and months is UNSET
            and weeks is UNSET
            and days is UNSET
        ):
            # This is to ensure ISO8601 formatting/parsing is round-trip safe.
            # There is no "empty" duration in ISO8601; at least one field must be present.
            raise ValueError("at least one field must be set")

    __init__ = add_alternate_constructors(__init__)

    def sign(self) -> Sign:
        """The sign of the delta, whether it's positive, negative, or zero.

        >>> ItemizedDateDelta(weeks=2).sign()
        1
        >>> ItemizedDateDelta(days=-3).sign()
        -1
        >>> ItemizedDateDelta(weeks=0).sign()
        0
        """
        for v in (self._years, self._months, self._weeks, self._days):
            if v:
                return 1 if v > 0 else -1
        return 0

    def in_units(
        self,
        units: Sequence[DateDeltaUnitStr],
        /,
        *,
        relative_to: Date,
        round_mode: RoundModeStr = "trunc",
        round_increment: int = 1,
    ) -> ItemizedDateDelta:
        """Convert this delta into the specified units. A `relative_to` date
        is required to resolve variable-length units (years and months).

        >>> d = ItemizedDateDelta(years=1, months=8)
        >>> d.in_units(["weeks", "days"], relative_to=Date(2020, 6, 30))
        ItemizedDateDelta("P86w6d")
        """
        return relative_to.add(self).since(
            relative_to,
            in_units=units,
            round_mode=round_mode,
            round_increment=round_increment,
        )

    if not TYPE_CHECKING:
        # This overload ensures it shows up nicely in the API docs, not just as "kwargs"
        @overload
        def replace(
            self,
            *,
            years: int | None = ...,
            months: int | None = ...,
            weeks: int | None = ...,
            days: int | None = ...,
        ) -> ItemizedDateDelta: ...

    def replace(self, **kwargs: int | None) -> ItemizedDateDelta:
        """Return a new delta with specific fields replaced.
        Fields set to ``None`` will be removed.

        All normal validation rules apply.

        >>> d = ItemizedDateDelta(years=1, months=2, weeks=3)
        >>> d.replace(months=None, weeks=4)
        ItemizedDateDelta("P1y4w")
        """
        kwargs_w_sentinel = {
            k: UNSET if v is None else v for k, v in kwargs.items()
        }
        # Keys may be invalid here, but the constructor will catch that.
        fields = {**self, **kwargs_w_sentinel}  # type: ignore[misc]
        if all(v is UNSET for v in fields.values()):
            raise ValueError("at least one field must remain set")
        return ItemizedDateDelta(**fields)

    def format_iso(self, *, lowercase_units: bool = False) -> str:
        """Convert to the canionical ISO 8601 string representation:

        .. code-block:: text

            P(nY)(nM)(nW)(nD)

        You can also use ``str(d)`` which is equivalent to ``d.format_iso()``.

        Inverse of :meth:`parse_iso`.

        >>> d = ItemizedDateDelta(weeks=1, days=11)
        >>> d.format_iso()
        'P1W11D'

        Note
        ----
        Negative durations are prefixed with a minus sign,
        which is not part of the ISO 8601 standard, but is a common extension.
        See :ref:`here <iso8601-durations>` for more information.
        """
        y, m, w, d = "ymwd" if lowercase_units else "YMWD"

        parts = ["-" * (self.sign() < 0), "P"]
        if self._years is not None:
            parts.append(f"{abs(self._years)}{y}")
        if self._months is not None:
            parts.append(f"{abs(self._months)}{m}")
        if self._weeks is not None:
            parts.append(f"{abs(self._weeks)}{w}")
        if self._days is not None:
            parts.append(f"{abs(self._days)}{d}")

        # NOTE: we always have at least one field,
        # so we don't need to check for "empty" durations.
        return "".join(parts)

    @classmethod
    def parse_iso(cls, s: str, /) -> ItemizedDateDelta:
        """Parse the *popular interpretation* of the ISO 8601 duration format.
        Inverse of :meth:`format_iso`

        >>> ItemizedDateDelta.parse_iso("-P1W11D")
        ItemizedDateDelta("-P1w11d")

        You can also use the constructor ``ItemizedDateDelta(s)`` which is
        equivalent to ``ItemizedDateDelta.parse_iso(s)``.

        Note
        ----
        Does not parse all possible ISO 8601 durations. In particular,
        it doesn't allow fractional values.
        See :ref:`here <iso8601-durations>` for more information.
        """
        exc = ValueError(f"Invalid format: {s!r}")

        # Catch certain invalid strings early, making parsing easier
        if len(s) < 3 or not s.isascii():
            raise exc

        sign: Sign
        s = s.upper()  # normalize to uppercase for parsing
        if s[0] == "P":
            sign = 1
            rest = s[1:]
        elif s.startswith("-P"):
            sign = -1
            rest = s[2:]
        elif s.startswith("+P"):
            sign = 1
            rest = s[2:]
        else:
            raise exc

        years, months, weeks, days = (None,) * 4
        prev_unit = ""
        while rest:
            rest, value, unit = _parse_datedelta_component(rest, exc)

            if unit == "Y" and prev_unit == "":
                years = value
            elif unit == "M" and prev_unit in "Y":
                months = value
            elif unit == "W" and prev_unit in "YM":
                weeks = value
            elif unit == "D" and prev_unit in "YMW":
                days = value
                break
            else:
                raise exc  # components out of order

            prev_unit = unit

        if rest:
            raise exc

        if not (years or months or weeks or days):
            sign = 0

        # NOTE: we've implicitly validated that at least one field is set
        return cls._from_signed(sign, years, months, weeks, days)

    # These methods defer to the base class implementations, but need to be
    # documented here for the API docs.
    if not TYPE_CHECKING:  # pragma: no cover
        if SPHINX_RUNNING:

            # FUTURE: an optimized ValuesView class that defers to the internal
            # fields directly instead of going through __getitem__
            def values(self) -> ValuesView[int]:
                """Return all defined field values, in order
                of largest to smallest unit.

                >>> d = ItemizedDateDelta(years=3, days=12, months=0)
                >>> years, months, days = d.values()
                (3, 0, 12)
                >>> list(d.values())
                [3, 0, 12]
                """
                ...

            def items(self) -> ItemsView[DateDeltaUnitStr, int]:
                """Return all defined fields as (unit, value) pairs
                ordered from largest to smallest unit.

                >>> d = ItemizedDateDelta(years=3, days=12, months=0)
                >>> list(d.items())
                [('years', 3), ('months', 0), ('days', 12)]
                """
                ...

            @overload
            def get(self, key: DateDeltaUnitStr, /) -> int | None: ...

            @overload
            def get(self, key: DateDeltaUnitStr, default: int, /) -> int: ...

            def get(
                self, key: DateDeltaUnitStr, default: object = None, /
            ) -> object:
                """Get the value of a specific field by name, or return default if not set.

                Part of the mapping protocol
                """
                ...

    def __iter__(self) -> Iterator[DateDeltaUnitStr]:
        """Iterate over all unit names for fields that are set, ordered from largest to smallest unit."""
        if self._years is not None:
            yield "years"
        if self._months is not None:
            yield "months"
        if self._weeks is not None:
            yield "weeks"
        if self._days is not None:
            yield "days"

    def keys(self) -> KeysView:
        """The names of all defined fields, ordered from largest to smallest unit.

        Part of the mapping protocol
        """
        return _DeltaKeysView(
            ((self._years is not None) << 0)
            | ((self._months is not None) << 1)
            | ((self._weeks is not None) << 2)
            | ((self._days is not None) << 3)
        )

    def __getitem__(self, key: DateDeltaUnitStr) -> int:
        """Get the value of a specific field by name.

        >>> d = ItemizedDateDelta(weeks=1, days=0)
        >>> d["weeks"]
        1
        >>> d["days"]
        0
        >>> d["years"]
        KeyError: 'years'
        """
        match key:
            case "years":
                value = self._years
            case "months":
                value = self._months
            case "weeks":
                value = self._weeks
            case "days":
                value = self._days
            case _:
                raise KeyError(key)

        if value is not None:
            return value

        raise KeyError(key)

    def __len__(self) -> int:
        """Get the number of fields that are set.

        >>> d = ItemizedDateDelta(weeks=1, days=0)
        >>> len(d)
        2
        """
        return (
            (self._years is not None)
            + (self._months is not None)
            + (self._weeks is not None)
            + (self._days is not None)
        )

    def __contains__(self, key: object) -> bool:
        """Check if a specific field is set.

        >>> d = ItemizedDateDelta(weeks=1, days=0)
        >>> "weeks" in d
        True
        >>> "days" in d
        True
        >>> "months" in d
        False
        """
        if key == "years":
            return self._years is not None
        elif key == "months":
            return self._months is not None
        elif key == "weeks":
            return self._weeks is not None
        elif key == "days":
            return self._days is not None
        return False

    def __bool__(self) -> bool:
        """An ItemizedDateDelta is considered False if its sign is 0.

        >>> d = ItemizedDateDelta(weeks=0)
        >>> bool(d)
        False
        >>> d = ItemizedDateDelta(weeks=1)
        >>> bool(d)
        True
        """
        return bool(self._years or self._months or self._weeks or self._days)

    def __eq__(self, other: object) -> bool:
        """Compare each field for equality, under the following rules:

        - No normalization is performed. 12 months is not equal to 1 year, etc.
        - Zero values are considered equivalent to missing values.

        If you want strict equality (including presence of fields),
        use :meth:`exact_eq`.

        >>> d = ItemizedDateDelta(weeks=2, days=3)
        >>> d == ItemizedDateDelta(weeks=2, days=3, months=0)
        True
        >>> d == ItemizedDateDelta(weeks=2, days=4)
        False
        """
        if not isinstance(other, ItemizedDateDelta):
            return NotImplemented
        return (
            (self._years or 0) == (other._years or 0)
            and (self._months or 0) == (other._months or 0)
            and (self._weeks or 0) == (other._weeks or 0)
            and (self._days or 0) == (other._days or 0)
        )

    def exact_eq(self, other: ItemizedDateDelta, /) -> bool:
        """Check for strict equality. All fields *and their presence* must match.

        >>> d = ItemizedDateDelta(weeks=2, days=3)
        >>> d == ItemizedDateDelta(weeks=2, days=3)
        True
        >>> d == ItemizedDateDelta(weeks=2, days=3, months=0)
        True
        >>> d.exact_eq(ItemizedDateDelta(weeks=2, days=3, months=0))
        False
        """
        return (
            self._years == other._years
            and self._months == other._months
            and self._weeks == other._weeks
            and self._days == other._days
        )

    def __abs__(self) -> ItemizedDateDelta:
        """If the contents are negative, return the positive version

        >>> d = ItemizedDateDelta(weeks=-2, days=-3)
        >>> abs(d)
        ItemizedDateDelta("P2w3d")
        """
        if self.sign() >= 0:
            return self
        return ItemizedDateDelta._from_signed(
            1,
            abs(self._years) if self._years is not None else None,
            abs(self._months) if self._months is not None else None,
            abs(self._weeks) if self._weeks is not None else None,
            abs(self._days) if self._days is not None else None,
        )

    def __neg__(self) -> ItemizedDateDelta:
        """Invert the sign of the contents

        >>> d = ItemizedDateDelta(weeks=2, days=3)
        >>> -d
        ItemizedDateDelta("-P2w3d")
        >>> --d
        ItemizedDateDelta("P2w3d")
        """
        if self.sign() == 0:
            return self
        return ItemizedDateDelta._from_signed(
            -self.sign(),
            abs(self._years) if self._years is not None else None,
            abs(self._months) if self._months is not None else None,
            abs(self._weeks) if self._weeks is not None else None,
            abs(self._days) if self._days is not None else None,
        )

    @overload
    def add(
        self,
        other: ItemizedDateDelta,
        /,
        *,
        relative_to: Date,
        in_units: Sequence[DateDeltaUnitStr],
        round_mode: RoundModeStr = "trunc",
        round_increment: int = 1,
    ) -> ItemizedDateDelta: ...

    @overload
    def add(
        self,
        /,
        *,
        years: int = ...,
        months: int = ...,
        weeks: int = ...,
        days: int = ...,
        relative_to: Date,
        in_units: Sequence[DateDeltaUnitStr],
        round_mode: RoundModeStr = "trunc",
        round_increment: int = 1,
    ) -> ItemizedDateDelta: ...

    def add(
        self,
        arg: ItemizedDateDelta = UNSET,
        /,
        *,
        relative_to: Date,
        in_units: Sequence[DateDeltaUnitStr],
        round_mode: RoundModeStr = "trunc",
        round_increment: int = 1,
        **kwargs: int,
    ) -> ItemizedDateDelta:
        """Add time to this delta, returning a new delta"""
        valid_keys = frozenset({"years", "months", "weeks", "days"})
        if kwargs:
            if arg is not UNSET:
                raise TypeError("Cannot mix positional and keyword arguments")
            invalid = set(kwargs) - valid_keys
            if invalid:
                raise TypeError(
                    f"Unexpected keyword argument: {next(iter(invalid))!r}"
                )
        elif arg is not UNSET:
            # In this case the mapping types are interchangeable
            kwargs = arg  # type: ignore[assignment]
        else:
            return self

        return relative_to.add(
            years=self.get("years", 0) + kwargs.get("years", 0),
            months=self.get("months", 0) + kwargs.get("months", 0),
            weeks=self.get("weeks", 0) + kwargs.get("weeks", 0),
            days=self.get("days", 0) + kwargs.get("days", 0),
        ).since(
            relative_to,
            in_units=in_units,
            round_mode=round_mode,
            round_increment=round_increment,
        )

    @overload
    def subtract(
        self,
        other: ItemizedDateDelta,
        /,
        *,
        relative_to: Date,
        in_units: Sequence[DateDeltaUnitStr],
        round_mode: RoundModeStr = "trunc",
        round_increment: int = 1,
    ) -> ItemizedDateDelta: ...

    @overload
    def subtract(
        self,
        /,
        *,
        years: int = ...,
        months: int = ...,
        weeks: int = ...,
        days: int = ...,
        relative_to: Date,
        in_units: Sequence[DateDeltaUnitStr],
        round_mode: RoundModeStr = "trunc",
        round_increment: int = 1,
    ) -> ItemizedDateDelta: ...

    def subtract(
        self,
        arg: ItemizedDateDelta = UNSET,
        /,
        *,
        relative_to: Date,
        in_units: Sequence[DateDeltaUnitStr],
        round_mode: RoundModeStr = "trunc",
        round_increment: int = 1,
        **kwargs: Any,
    ) -> ItemizedDateDelta:
        """Subtract time from this delta, returning a new delta"""
        arg = -arg if arg is not UNSET else UNSET
        return self.add(
            arg,
            **{k: -v for k, v in kwargs.items()},
            relative_to=relative_to,
            in_units=in_units,
            round_mode=round_mode,
            round_increment=round_increment,
        )

    def total(self, unit: DateDeltaUnitStr, /, *, relative_to: Date) -> float:
        """Return the total duration expressed in the specified unit as a float

        >>> ItemizedDateDelta(years=1, months=6).total("months", relative_to=Date(2020, 1, 31))
        18.0
        >>> ItemizedDateDelta(days=1000).total("years", relative_to=Date(2020, 4, 10))
        2.73972602739726
        """
        shifted = relative_to.add(self)
        sgn = self.sign()
        shifted_d = _date(shifted.year, shifted.month, shifted.day)
        ref_d = _date(relative_to.year, relative_to.month, relative_to.day)
        try:
            trunc_amount, trunc_date_interim, expand_date_interim = DIFF_FUNCS[
                unit
            ](shifted_d, ref_d, 1, sgn or 1)
        except KeyError:
            raise ValueError(f"Unsupported unit: {unit!r}") from None

        trunc_date = resolve_leap_day(trunc_date_interim)
        expand_date = resolve_leap_day(expand_date_interim)

        return (
            trunc_amount
            + ((shifted_d - trunc_date) / (expand_date - trunc_date))
        ) * sgn

    # A private constructor that bypasses sign/presence validation.
    # All field values must be non-negative; `sign` is applied when storing.
    @classmethod
    def _from_signed(
        cls,
        sign: Sign,
        years: int | None = None,
        months: int | None = None,
        weeks: int | None = None,
        days: int | None = None,
    ) -> ItemizedDateDelta:
        self = _object_new(cls)

        def _apply(v: int | None, max_val: int) -> int | None:
            v = _check_bound(v, max_val)
            return -v if v and sign < 0 else v

        self._years = _apply(years, _MAX_DELTA_YEARS)
        self._months = _apply(months, _MAX_DELTA_MONTHS)
        self._weeks = _apply(weeks, _MAX_DELTA_WEEKS)
        self._days = _apply(days, _MAX_DELTA_DAYS)
        return self

    @no_type_check
    def __reduce__(self):
        return (
            _unpkl_iddelta,
            (
                self._years,
                self._months,
                self._weeks,
                self._days,
            ),
        )

    def __repr__(self) -> str:
        return f'ItemizedDateDelta("{self.format_iso(lowercase_units=True)}")'

    __str__ = format_iso

    def _init_from_iso(self, s: str) -> None:
        parsed = type(self).parse_iso(s)
        self._years = parsed._years
        self._months = parsed._months
        self._weeks = parsed._weeks
        self._days = parsed._days

    def _to_tuple(self):  # pragma: no cover
        return (self._years, self._months, self._weeks, self._days)


# A separate unpickling function allows us to make backwards-compatible changes
# to the pickling format in the future
def _unpkl_iddelta(
    years: int | None,
    months: int | None,
    weeks: int | None,
    days: int | None,
) -> ItemizedDateDelta:
    self = _object_new(ItemizedDateDelta)
    self._years = years
    self._months = months
    self._weeks = weeks
    self._days = days
    return self
