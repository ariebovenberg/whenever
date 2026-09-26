"""Pure-Python implementation of ItemizedDelta and ItemizedDateDelta.

These types are always pure Python, even when the Rust extension is active.
The Rust extension imports them from this module.
"""

from __future__ import annotations

from collections import Counter
from collections.abc import (
    ItemsView,
    KeysView,
    Mapping,
    ValuesView,
)
from typing import (
    TYPE_CHECKING,
    Any,
    Iterable,
    Iterator,
    Sequence,
    TypeVar,
    cast,
    no_type_check,
    overload,
)
from warnings import warn

from ._common import (
    _MAX_DELTA_DAYS,
    _MAX_DELTA_HOURS,
    _MAX_DELTA_MINUTES,
    _MAX_DELTA_MONTHS,
    _MAX_DELTA_SECONDS,
    _MAX_DELTA_WEEKS,
    _MAX_DELTA_YEARS,
    _MAX_SUBSEC_NANOS,
    OFFSET_SHIFT_STALE_MSG,
    PLAIN_RELATIVE_TO_UNAWARE_MSG,
    PLAIN_SHIFT_UNAWARE_MSG,
    SPHINX_RUNNING,  # noqa
    STALE_OFFSET_CALENDAR_MSG,
    UNSET,
    WARNING_HANDLING_DOCS_MSG,
    WheneverWarning,
    _Base,
    add_alternate_constructors,
    check_no_kwargs,
    expect_int,
    final,
    invalid,
    warn_deprecated,
)
from ._math import (
    DATE_DELTA_UNITS,
    DELTA_UNITS,
    EXACT_TOTAL_UNITS,
    EXACT_UNITS_STRICT,
    TOTAL_UNITS,
    Sign,
    normalize_units,
    resolve_date_rounding,
    resolve_rounding,
)
from ._parse import parse_timedelta_component
from ._typing import (
    DateDeltaUnitStr,
    DeltaTotalUnitStr,
    DeltaUnitStr,
    RoundModeStr,
)

# The reference module under the type checker, so a call into a datetime type
# is checked against the real overloads and needs no cast(); the package at
# runtime, so it resolves to whichever backend is loaded.
if TYPE_CHECKING:
    from . import _pywhenever as _whenever
else:
    import whenever as _whenever

_object_new = object.__new__
_T = TypeVar("_T")


def _shift_datetime_operator(
    datetime: _T,
    delta: ItemizedDelta | ItemizedDateDelta | _whenever.TimeDelta,
    subtract: bool,
) -> _T:
    """Called by an operator method: the warnings point at the operator's
    own caller."""
    from ._core import (
        NaiveArithmeticWarning,
        OffsetDateTime,
        PlainDateTime,
        StaleOffsetWarning,
        TimeDelta,
        ZonedDateTime,
    )

    operand = cast(Any, datetime)
    kwargs: dict[str, Any]
    warning: tuple[str, type[Warning]] | None = None
    if isinstance(datetime, PlainDateTime):
        if (
            isinstance(delta, TimeDelta)
            and delta
            or isinstance(delta, ItemizedDelta)
            and any(delta.get(unit, 0) for unit in EXACT_UNITS_STRICT)
        ):
            warning = (PLAIN_SHIFT_UNAWARE_MSG, NaiveArithmeticWarning)
        kwargs = {"naive_arithmetic_ok": True}
    elif isinstance(datetime, OffsetDateTime):
        if delta:
            warning = (OFFSET_SHIFT_STALE_MSG, StaleOffsetWarning)
        kwargs = {"stale_offset_ok": True}
    elif isinstance(datetime, ZonedDateTime):
        # add()/subtract() would attribute their warnings to this frame, so
        # tell them to point further up, at the operator's own caller.
        kwargs = {"_warn_stacklevel": 3}
    else:
        kwargs = {}
    operation = operand.subtract if subtract else operand.add
    result = cast(_T, operation(delta, **kwargs))
    if warning is not None:
        warn(*warning, stacklevel=3)
    return result


RELATIVE_TO_DATETIME_MSG = (
    "relative_to must be a ZonedDateTime, PlainDateTime, or OffsetDateTime"
)
RELATIVE_TO_DATE_MSG = (
    "relative_to must be a Date, ZonedDateTime, PlainDateTime, or "
    "OffsetDateTime"
)
IN_UNITS_REQUIRED_MSG = "in_units is required with relative_to"


def _reference_and_warning(
    relative_to: object,
    has_exact: bool,
    has_cal: bool,
    naive_arithmetic_ok: bool,
    stale_offset_ok: bool,
) -> tuple[_whenever.ZonedDateTime, Warning | None]:
    """The ``ZonedDateTime`` a calendar-aware delta computation runs on, and
    the one warning its reference type carries, for the caller to emit from
    its own frame once the computation has succeeded.

    ``has_exact`` and ``has_cal`` say which unit kinds the computation
    involves, the delta's components and the target units together: a
    ``PlainDateTime`` warns when both do, an ``OffsetDateTime`` when calendar
    units do. Both compute as if in UTC, which is an implementation detail:
    to the caller the former is naive and the latter holds its offset fixed.
    """
    from ._core import (
        NaiveArithmeticWarning,
        OffsetDateTime,
        PlainDateTime,
        StaleOffsetWarning,
        ZonedDateTime,
    )

    if isinstance(relative_to, ZonedDateTime):
        return relative_to, None
    elif isinstance(relative_to, PlainDateTime):
        return relative_to.assume_tz("UTC"), (
            NaiveArithmeticWarning(PLAIN_RELATIVE_TO_UNAWARE_MSG)
            if has_exact and has_cal and not naive_arithmetic_ok
            else None
        )
    elif isinstance(relative_to, OffsetDateTime):
        return relative_to.to_plain().assume_tz("UTC"), (
            StaleOffsetWarning(STALE_OFFSET_CALENDAR_MSG)
            if has_cal and not stale_offset_ok
            else None
        )
    raise TypeError(RELATIVE_TO_DATETIME_MSG)


def _reference_date(relative_to: object) -> _whenever.Date:
    """The ``Date`` a date-only delta computation runs on: a datetime
    reference contributes its date alone, without a warning."""
    from ._core import Date, OffsetDateTime, PlainDateTime, ZonedDateTime

    if isinstance(relative_to, Date):
        return relative_to
    elif isinstance(
        relative_to, (ZonedDateTime, PlainDateTime, OffsetDateTime)
    ):
        return relative_to.date()
    raise TypeError(RELATIVE_TO_DATE_MSG)


def _has_unit_kinds(
    components: Mapping[str, int] | ItemizedDelta | ItemizedDateDelta,
    units: Iterable[str],
) -> tuple[bool, bool]:
    """Whether exact and calendar units are involved: as a nonzero component
    of the delta, or as a requested unit, which may be a subsecond total."""
    return (
        any(v for k, v in components.items() if k in EXACT_UNITS_STRICT)
        or any(u in EXACT_TOTAL_UNITS for u in units),
        _has_nonzero_calendar_units(components)
        or any(u in DATE_DELTA_UNITS for u in units),
    )


def _read_components(
    components: Mapping[str, int], negate: bool
) -> dict[str, int]:
    """The given component keywords of ``add()``/``subtract()``, as
    integers."""
    return {
        k: -expect_int(k, v) if negate else expect_int(k, v)
        for k, v in components.items()
        if v is not UNSET
    }


def _shift_reference(
    reference: _whenever.ZonedDateTime,
    components: Mapping[Any, int],
    warn_stacklevel: int,
) -> _whenever.ZonedDateTime:
    """Shift a reference by summed components, which may mix signs, and
    attribute the shift's ``ImplicitDisambiguationWarning`` to the caller.

    Both go past the stub, so a cast is needed: a mixed-sign sum cannot
    form an itemized delta, and ``_warn_stacklevel`` is private.
    ``warn_stacklevel`` counts from the caller of this helper.
    """
    return cast(
        _whenever.ZonedDateTime,
        cast(Any, reference).add(
            **components, _warn_stacklevel=warn_stacklevel + 1
        ),
    )


# A special version of "Counter + Counter" that preserves zero
# and negative values.
def _items_add(
    # NOTE: we need to explicitly specify a union with itemized deltas
    # because mypy can't detect that itemized deltas are Mapping[str, int].
    a: Mapping[str, int] | ItemizedDelta | ItemizedDateDelta,
    b: Mapping[str, int] | ItemizedDelta | ItemizedDateDelta,
) -> Mapping[str, int]:
    sum = Counter(a)
    sum.update(b)
    # Seconds and nanoseconds are one quantity (ADR 0005): carry and borrow
    # between them, and only between them.
    ns = sum.get("nanoseconds")
    if ns is not None and ("seconds" in sum or abs(ns) >= 1_000_000_000):
        total = sum.get("seconds", 0) * 1_000_000_000 + ns
        secs, ns = divmod(abs(total), 1_000_000_000)
        sign = -1 if total < 0 else 1
        sum["seconds"], sum["nanoseconds"] = sign * secs, sign * ns
    return sum


CALENDAR_UNIT_OPERATOR_COMPOSITION_MSG = (
    "Using `+` or `-` between two itemized deltas combines their components instead "
    "of applying the deltas one after another. With calendar units such as "
    "months or days, the combined delta can produce a different date because "
    "calendar arithmetic may clamp at month boundaries. To apply the deltas "
    "sequentially, apply each one to the date or datetime in a separate step. "
    "To create one delta relative to a starting point, use the corresponding "
    "`.add()` or `.subtract()` method with `relative_to=...` and "
    "`in_units=...`. If component-wise composition is intentional, use that method "
    "with `cal_unit_composition_ok=True`. " + WARNING_HANDLING_DOCS_MSG
)

CALENDAR_UNIT_METHOD_COMPOSITION_MSG = (
    "Calling `.add()` or `.subtract()` without `relative_to` combines the "
    "itemized deltas component by component. With calendar units such as months or "
    "days, the resulting delta may behave differently from applying the deltas "
    "one after another. Pass `relative_to=...` and `in_units=...` to create a "
    "delta relative to a specific starting point. If component-wise composition is "
    "intentional, pass `cal_unit_composition_ok=True`. "
    + WARNING_HANDLING_DOCS_MSG
)


def _has_nonzero_calendar_units(
    delta: Mapping[str, int] | ItemizedDelta | ItemizedDateDelta,
) -> bool:
    return any(map(delta.get, DATE_DELTA_UNITS))


def _compose_operator(
    a: ItemizedDelta | ItemizedDateDelta,
    b: ItemizedDelta | ItemizedDateDelta,
    negate: bool,
) -> ItemizedDelta | ItemizedDateDelta:
    """The body of ``+``/``-`` between itemized deltas, called directly by
    the operator method so the warning points at its caller."""
    result = _composed_type(a, b)(**_items_add(a, -b if negate else b))
    if _has_nonzero_calendar_units(a) or _has_nonzero_calendar_units(b):
        warn(
            CALENDAR_UNIT_OPERATOR_COMPOSITION_MSG,
            CalendarUnitCompositionWarning,
            stacklevel=3,
        )
    return result


# The types an itemized delta shifts through ``+``/``-``. Built on demand:
# the datetime types can't be imported while this module loads.
def _datetime_types() -> tuple[
    type[_whenever.ZonedDateTime],
    type[_whenever.PlainDateTime],
    type[_whenever.OffsetDateTime],
]:
    from ._core import OffsetDateTime, PlainDateTime, ZonedDateTime

    return (ZonedDateTime, PlainDateTime, OffsetDateTime)


# Only a date delta shifts a ``Date``: for an ``ItemizedDelta`` operand,
# ``Date`` rejects the operation itself.
def _date_or_datetime_types() -> tuple[
    type[_whenever.Date],
    type[_whenever.ZonedDateTime],
    type[_whenever.PlainDateTime],
    type[_whenever.OffsetDateTime],
]:
    from ._core import Date

    return (Date, *_datetime_types())


def _compose(
    self: ItemizedDelta | ItemizedDateDelta,
    arg: ItemizedDelta | ItemizedDateDelta,
    components: Mapping[str, int],
    /,
    *,
    relative_to: object,
    in_units: Sequence[DeltaUnitStr],
    round_mode: RoundModeStr,
    round_increment: int,
    cal_unit_composition_ok: bool,
    naive_arithmetic_ok: bool,
    stale_offset_ok: bool,
    negate: bool,
) -> ItemizedDelta | ItemizedDateDelta:
    """The body of ``add()``/``subtract()``, called directly by them so the
    warnings point at their caller. The result is an ``ItemizedDelta`` if
    either operand is one, else an ``ItemizedDateDelta``."""
    fname = "subtract" if negate else "add"
    # Normalize the input into a single unit->value mapping
    other: Mapping[str, int] = _read_components(components, negate)
    if other:
        if arg is not UNSET:
            raise TypeError(
                f"{fname}() cannot mix positional and keyword arguments"
            )
    elif isinstance(arg, (ItemizedDelta, ItemizedDateDelta)):
        # Mypy can't see how itemized deltas are always valid str->int mappings
        other = -arg if negate else arg  # type: ignore[assignment]
    elif arg is not UNSET:
        raise TypeError(
            "argument must be an ItemizedDelta or ItemizedDateDelta"
        )

    if (
        arg is UNSET
        and not other
        and relative_to is UNSET
        and in_units is UNSET
        and round_mode is UNSET
        and round_increment is UNSET
    ):
        return self

    type_ = _composed_type(self, other)

    if relative_to is UNSET:
        if in_units is not UNSET:
            raise TypeError("in_units requires relative_to")
        if round_mode is not UNSET or round_increment is not UNSET:
            raise TypeError(
                "round_mode and round_increment require relative_to"
            )
        result = type_(**_items_add(self, other))
        if not cal_unit_composition_ok and (
            _has_nonzero_calendar_units(self)
            or _has_nonzero_calendar_units(other)
        ):
            warn(
                CALENDAR_UNIT_METHOD_COMPOSITION_MSG,
                CalendarUnitCompositionWarning,
                stacklevel=3,
            )
        return result

    if in_units is UNSET:
        raise TypeError(IN_UNITS_REQUIRED_MSG)
    combined = _items_add(self, other)
    if type_ is ItemizedDateDelta:
        date_units = normalize_units(in_units, DATE_DELTA_UNITS)
        round_mode, round_increment = resolve_date_rounding(
            round_mode, round_increment
        )
        date = _reference_date(relative_to)
        return date.add(**combined).since(
            date,
            in_units=date_units,
            round_mode=round_mode,
            round_increment=round_increment,
        )
    if isinstance(self, ItemizedDateDelta):
        from ._core import Date

        if isinstance(relative_to, Date):
            raise TypeError(
                RELATIVE_TO_DATETIME_MSG + " when composing with ItemizedDelta"
            )
    units = normalize_units(in_units, DELTA_UNITS)
    round_mode, round_increment = resolve_rounding(round_mode, round_increment)
    reference, warning = _reference_and_warning(
        relative_to,
        *_has_unit_kinds(combined, units),
        naive_arithmetic_ok,
        stale_offset_ok,
    )
    result = _shift_reference(reference, combined, 3).since(
        reference,
        in_units=units,
        round_mode=round_mode,
        round_increment=round_increment,
    )
    if warning is not None:
        warn(warning, stacklevel=3)
    return result


def _composed_type(
    a: Mapping[str, int] | ItemizedDelta | ItemizedDateDelta,
    b: Mapping[str, int] | ItemizedDelta | ItemizedDateDelta,
) -> type[ItemizedDelta] | type[ItemizedDateDelta]:
    """The type of a composition: ``ItemizedDelta`` if either operand is
    one, else ``ItemizedDateDelta``."""
    if isinstance(a, ItemizedDelta) or isinstance(b, ItemizedDelta):
        return ItemizedDelta
    return ItemizedDateDelta


class CalendarUnitCompositionWarning(WheneverWarning):
    """Warn when itemized deltas are composed component by component.

    Itemized deltas preserve the components they were given:
    ``1 month`` remains ``1 month`` rather than being normalized to days.
    Composing two itemized deltas without a ``relative_to`` reference therefore
    performs literal component-wise arithmetic, such as
    ``ItemizedDateDelta(months=1) + ItemizedDateDelta(months=1)`` becoming
    ``ItemizedDateDelta(months=2)``.

    This is often useful for display and ISO 8601 round-tripping, but it is
    not the same as sequentially applying both deltas to a date or datetime.
    Calendar units do not compose reliably: for example, adding one month to
    January 31 may clamp to the end of February, so adding another month from
    there can differ from adding two months to January 31 in one step.
    The warning is only emitted when either operand contains a nonzero calendar
    unit; exact-only composition does not warn.

    Composition is flagged rather than refused (Temporal's ``Duration.add()``
    throws without a reference) because a warning serves strict, accepting,
    and unaware callers alike: see :ref:`flagged-not-forbidden`.

    To preserve calendar-aware semantics, pass ``relative_to=...`` and
    ``in_units=...`` to :meth:`~whenever.ItemizedDelta.add` or
    :meth:`~whenever.ItemizedDateDelta.add`. If component-wise composition is
    intentional, pass ``cal_unit_composition_ok=True`` or use Python's
    standard warning filters.
    """

    __module__ = "whenever"


_OUT_OF_RANGE_MSG = "delta out of range"
_NANOS_OUT_OF_RANGE_MSG = (
    "nanoseconds must be within ±999,999,999; put whole seconds in seconds="
)

# As for the time components; the constructor reports a larger value as out
# of range.
_MAX_DDELTA_DIGITS = 35


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


def _parse_iso_prefix(s: str, exc: Exception) -> tuple[Sign, str]:
    """The sign, and the rest of the uppercased string after the ``P``."""
    # Catch certain invalid strings early, making parsing easier
    if len(s) < 3 or not s.isascii() or s[-1] in "Tt":
        raise exc

    s = s.upper()
    if s[0] == "P":
        return 1, s[1:]
    elif s.startswith("-P"):
        return -1, s[2:]
    elif s.startswith("+P"):
        return 1, s[2:]
    raise exc


def _parse_iso_date_part(
    rest: str, exc: Exception
) -> tuple[str, int | None, int | None, int | None, int | None]:
    """The rest from the ``T`` separator on, and the years, months, weeks,
    and days before it."""
    years, months, weeks, days = (None,) * 4
    prev_unit = ""
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
    return rest, years, months, weeks, days


def _check_bound(i: int | None, max_value: int, err: str) -> int | None:
    if i and i > max_value:
        raise ValueError(err)
    return i


def _check_component(
    name: str,
    value: int,
    sign: Sign,
    max_value: int,
    err: str,
) -> tuple[int | None, Sign]:
    if value is UNSET:
        return None, sign
    value = expect_int(name, value)
    if value == 0:
        return 0, sign
    elif value < 0:
        if sign == 1:
            raise ValueError("mixed sign in delta")
        sign = -1
        if -value > max_value:
            raise ValueError(err)
    else:  # value > 0
        if sign == -1:
            raise ValueError("mixed sign in delta")
        sign = 1
        if value > max_value:
            raise ValueError(err)
    return value, sign


@final
class ItemizedDelta(_Base, Mapping[DeltaUnitStr, int]):
    """A delta that preserves the components it was given.
    It closely models the ISO 8601 duration format.

    >>> d = ItemizedDelta(weeks=2, days=3, hours=14)
    ItemizedDelta("P2w3dT14h")
    >>> d = ItemizedDelta("P2w3dT14h")
    >>> str(d)
    'P2W3DT14H'

    It behaves like a mapping where the keys are
    the unit names and the values are the amounts.
    Items are ordered from largest to smallest unit.

    >>> d['weeks']
    2
    >>> print(d.get('minutes'))
    None
    >>> dict(d)
    {"weeks": 2, "days": 3, "hours": 14}
    >>> list(d.keys())
    ["weeks", "days", "hours"]
    >>> weeks, days, hours = d.values()
    (2, 3, 14)

    ``ItemizedDelta`` also supports other dictionary-like operations:

    >>> "months" in d  # check for presence of a component
    False
    >>> len(d)  # number of components present
    3

    An explicit zero is a present component, distinct from an absent one:

    >>> d2 = ItemizedDelta(years=2, weeks=3, hours=0)
    >>> dict(d2)
    {"years": 2, "weeks": 3, "hours": 0}

    Additionally, no normalization is performed.
    Months are not rolled into years, minutes into hours, etc.

    >>> d3 = ItemizedDelta(months=24, minutes=90)
    ItemizedDelta("P24mT90m")

    Seconds and nanoseconds are one quantity in two components:
    ``nanoseconds`` is bounded to 999,999,999, and setting it also sets
    ``seconds``. There are no millisecond or microsecond components; use
    :meth:`total` for those units. See the
    `subsecond rules <https://whenever.rtfd.io/en/latest/reference/deltas.html#delta-subsecond>`_.

    An empty delta is not allowed: at least one component must be present, but it may be zero:

    >>> ItemizedDelta()
    ValueError: at least one component must be present
    >>> ItemizedDelta(seconds=0)
    ItemizedDelta("PT0s")

    Negative deltas are supported, but all components must have the same sign:

    >>> d4 = ItemizedDelta(years=-1, weeks=-2, days=0)
    ItemizedDelta("-P1y2w0d")
    >>> ItemizedDelta(years=1, days=-3)
    ValueError: mixed sign in delta

    Note
    ----
    Unlike :class:`TimeDelta`, ``ItemizedDelta`` does not normalize
    its components. This means that ``ItemizedDelta(hours=90)`` and
    ``ItemizedDelta(days=3, hours=18)`` are considered different values.
    To convert to a normalized form, use :meth:`in_units`.
    See also the `delta documentation <https://whenever.rtfd.io/en/latest/guide/deltas.html>`_.
    """

    __module__ = "whenever"

    __slots__ = (
        # Values are stored as signed integers (or None if absent).
        # All non-zero components must have the same sign.
        "_years",
        "_months",
        "_weeks",
        "_days",
        "_hours",
        "_minutes",
        "_seconds",
        "_nanoseconds",
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

        self._years, sign = _check_component(
            "years", years, sign, _MAX_DELTA_YEARS, _OUT_OF_RANGE_MSG
        )
        self._months, sign = _check_component(
            "months", months, sign, _MAX_DELTA_MONTHS, _OUT_OF_RANGE_MSG
        )
        self._weeks, sign = _check_component(
            "weeks", weeks, sign, _MAX_DELTA_WEEKS, _OUT_OF_RANGE_MSG
        )
        self._days, sign = _check_component(
            "days", days, sign, _MAX_DELTA_DAYS, _OUT_OF_RANGE_MSG
        )
        self._hours, sign = _check_component(
            "hours", hours, sign, _MAX_DELTA_HOURS, _OUT_OF_RANGE_MSG
        )
        self._minutes, sign = _check_component(
            "minutes", minutes, sign, _MAX_DELTA_MINUTES, _OUT_OF_RANGE_MSG
        )
        self._seconds, sign = _check_component(
            "seconds", seconds, sign, _MAX_DELTA_SECONDS, _OUT_OF_RANGE_MSG
        )
        self._nanoseconds, sign = _check_component(
            "nanoseconds",
            nanoseconds,
            sign,
            _MAX_SUBSEC_NANOS,
            _NANOS_OUT_OF_RANGE_MSG,
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
            # There is no "empty" duration in ISO 8601; at least one component must be present.
            raise ValueError("at least one component must be present")

    __init__ = add_alternate_constructors(__init__, None)

    def sign(self) -> Sign:
        """The sign of the delta, whether it's positive, negative, or zero.

        >>> ItemizedDelta(weeks=2).sign()
        1
        >>> ItemizedDelta(hours=-3).sign()
        -1
        >>> ItemizedDelta(weeks=0).sign()
        0
        """
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

    def __iter__(self) -> Iterator[DeltaUnitStr]:
        """Iterate over the present components, ordered from largest to smallest unit."""
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

    # These methods defer to the base class implementations, but need to be
    # documented here for the API docs.
    if not TYPE_CHECKING:  # pragma: no cover
        if SPHINX_RUNNING:

            def keys(self) -> KeysView[DeltaUnitStr]:
                """The names of the present components, in order of largest to smallest unit.

                Part of the mapping protocol
                """
                ...

            def values(self) -> ValuesView[int]:
                """The values of the present components, in order
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
                """The present components as (unit, value) pairs,
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
                """Get the value of a specific component by name, or return default if absent.

                Part of the mapping protocol
                """

            ...

    def __getitem__(self, key: str, /) -> int:
        """Get the value of a specific component by name.

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
        """The number of present components.

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

    def __contains__(self, key: object, /) -> bool:
        """Whether a specific component is present.

        >>> d = ItemizedDelta(weeks=1, days=3)
        >>> "weeks" in d
        True
        >>> "hours" in d
        False
        """
        match key:
            case "years":
                return self._years is not None
            case "months":
                return self._months is not None
            case "weeks":
                return self._weeks is not None
            case "days":
                return self._days is not None
            case "hours":
                return self._hours is not None
            case "minutes":
                return self._minutes is not None
            case "seconds":
                return self._seconds is not None
            case "nanoseconds":
                return self._nanoseconds is not None
            case _:
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

        Parameters
        ----------
        lowercase_units
            Write the unit designators in lowercase, as ``repr()`` does;
            ``parse_iso()`` reads both cases.
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
        if joined.endswith("T"):  # skip the T if no time components
            return joined[:-1]
        # NOTE: we always have at least one component,
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

        >>> ItemizedDelta.parse_iso("-P1W11DT4H")
        ItemizedDelta("-P1w11dT4h")
        """
        exc = ValueError(f"invalid ISO 8601 string: {s!r}")
        sign, rest = _parse_iso_prefix(s, exc)
        rest, years, months, weeks, days = _parse_iso_date_part(rest, exc)
        if rest and not rest.startswith("T"):
            raise exc

        hours, minutes, seconds, nanos = (None,) * 4
        prev_unit = ""

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

        # NOTE: we've implicitly validated that at least one component is present
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
    ) -> tuple[ItemizedDateDelta | None, _whenever.TimeDelta | None]:
        """Split into the date part and the time part.

        The date part is an :class:`ItemizedDateDelta`; the time part is a
        normalized :class:`TimeDelta`, since no itemized time-only type
        exists. A half with no component present is ``None``, while a half
        given only as zero is a present zero. At least one half is present,
        since at least one component is.

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
        TimeDelta("PT5h6m7.000000008s")
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
    # All component values must be non-negative; `sign` is applied when storing.
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

        def _apply(v: int | None, max_val: int, err: str) -> int | None:
            v = _check_bound(v, max_val, err)
            return -v if v and sign < 0 else v

        self._years = _apply(years, _MAX_DELTA_YEARS, _OUT_OF_RANGE_MSG)
        self._months = _apply(months, _MAX_DELTA_MONTHS, _OUT_OF_RANGE_MSG)
        self._weeks = _apply(weeks, _MAX_DELTA_WEEKS, _OUT_OF_RANGE_MSG)
        self._days = _apply(days, _MAX_DELTA_DAYS, _OUT_OF_RANGE_MSG)
        self._hours = _apply(hours, _MAX_DELTA_HOURS, _OUT_OF_RANGE_MSG)
        self._minutes = _apply(minutes, _MAX_DELTA_MINUTES, _OUT_OF_RANGE_MSG)
        self._seconds = _apply(seconds, _MAX_DELTA_SECONDS, _OUT_OF_RANGE_MSG)
        self._nanoseconds = _apply(
            nanoseconds, _MAX_SUBSEC_NANOS, _NANOS_OUT_OF_RANGE_MSG
        )
        return self

    def __eq__(self, other: object, /) -> bool:
        """Compare for equality. Each component is individually compared.
        No normalization is performed. An explicit zero is equivalent to an
        absent component.

        Thus, ``ItemizedDelta(weeks=1, seconds=0) == ItemizedDelta(weeks=1)``

        >>> d = ItemizedDelta(weeks=2, minutes=90)
        >>> d == ItemizedDelta(weeks=2, minutes=90)
        True
        >>> d == ItemizedDelta(weeks=2, minutes=91)
        False

        An :class:`ItemizedDateDelta` with the same components is equal:

        >>> ItemizedDelta(weeks=2, hours=0) == ItemizedDateDelta(weeks=2)
        True

        If you want strict equality (including presence of components
        and the type), use :meth:`strict_eq`.

        """
        if isinstance(other, ItemizedDateDelta):
            return (
                not (
                    self._hours
                    or self._minutes
                    or self._seconds
                    or self._nanoseconds
                )
                and (self._years or 0) == (other._years or 0)
                and (self._months or 0) == (other._months or 0)
                and (self._weeks or 0) == (other._weeks or 0)
                and (self._days or 0) == (other._days or 0)
            )
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

    def __hash__(self) -> int:
        # Equal values must hash alike, so a component given as zero
        # hashes like a missing one.
        return hash(tuple((k, v) for k, v in self.items() if v))

    def strict_eq(self, other: ItemizedDelta, /) -> bool:
        """Compare two deltas, including what ``==`` ignores.

        ``ItemizedDelta.__eq__`` ignores the argument's type, and whether a
        component was given explicitly as zero. An argument of a different
        type raises :exc:`TypeError`.

        >>> d = ItemizedDelta(weeks=2, hours=3)
        >>> d == ItemizedDelta(weeks=2, hours=3, months=0)
        True
        >>> d.strict_eq(ItemizedDelta(weeks=2, hours=3, months=0))
        False

        See :ref:`strict-equality` for the rules on every type.
        """
        if type(other) is not type(self):
            raise TypeError("strict_eq() argument must be an ItemizedDelta")
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

    def exact_eq(self, other: ItemizedDelta, /) -> bool:
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

    def __abs__(self) -> ItemizedDelta:
        """If the components are negative, return the positive version

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
        """Invert the sign of the components

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

    def add(
        self,
        delta: ItemizedDelta | ItemizedDateDelta = UNSET,
        /,
        *,
        years: int = UNSET,
        months: int = UNSET,
        weeks: int = UNSET,
        days: int = UNSET,
        hours: int = UNSET,
        minutes: int = UNSET,
        seconds: int = UNSET,
        nanoseconds: int = UNSET,
        relative_to: _whenever.ZonedDateTime
        | _whenever.PlainDateTime
        | _whenever.OffsetDateTime = UNSET,
        in_units: Sequence[DeltaUnitStr] = UNSET,
        round_mode: RoundModeStr = UNSET,
        round_increment: int = UNSET,
        cal_unit_composition_ok: bool = UNSET,
        naive_arithmetic_ok: bool = UNSET,
        stale_offset_ok: bool = UNSET,
    ) -> ItemizedDelta:
        """Add a delta to this one, returning a new delta.

        Pass either a delta or its components as keywords, not both.

        >>> d = ItemizedDelta(months=1)
        >>> d.add(days=30, relative_to=ZonedDateTime(2023, 1, 1, tz="UTC"), in_units=["months", "days"])
        ItemizedDelta("P2m2d")
        >>> d.add(hours=3, cal_unit_composition_ok=True)
        ItemizedDelta("P1mT3h")

        Parameters
        ----------
        delta
            The delta to add, or else its components as keywords, named
            as in the constructor.
        relative_to
            The reference for calendar-aware composition: the components of
            both deltas are summed, applied to the reference, and the result
            is measured back from it in ``in_units``. Without a reference,
            composition is component-wise: like components are summed.
            A :class:`ZonedDateTime` emits no warning. A
            :class:`PlainDateTime` ignores time zone transitions, and emits
            :class:`NaiveArithmeticWarning` when the computation crosses the
            calendar/exact boundary. An :class:`OffsetDateTime` holds its
            offset fixed for the whole calculation, and emits
            :class:`StaleOffsetWarning` when calendar units are involved.
        in_units
            The units of the result, largest first. Required with
            ``relative_to``: the coarsest unit decides how the sum is
            expressed, and no default fits every sum.
        round_mode
            The rounding mode for the smallest unit in ``in_units``, as on
            :meth:`~ZonedDateTime.since`.
        round_increment
            The rounding increment for that unit.
        cal_unit_composition_ok
            Accepts :class:`~whenever.CalendarUnitCompositionWarning`, which
            component-wise composition emits when a nonzero calendar unit is
            involved.
        naive_arithmetic_ok
            Accepts the :class:`NaiveArithmeticWarning` of a
            :class:`PlainDateTime` reference.
        stale_offset_ok
            Accepts the :class:`StaleOffsetWarning` of an
            :class:`OffsetDateTime` reference.
        """
        return cast(
            ItemizedDelta,
            _compose(
                self,
                delta,
                {
                    "years": years,
                    "months": months,
                    "weeks": weeks,
                    "days": days,
                    "hours": hours,
                    "minutes": minutes,
                    "seconds": seconds,
                    "nanoseconds": nanoseconds,
                },
                relative_to=relative_to,
                in_units=in_units,
                round_mode=round_mode,
                round_increment=round_increment,
                cal_unit_composition_ok=cal_unit_composition_ok,
                naive_arithmetic_ok=naive_arithmetic_ok,
                stale_offset_ok=stale_offset_ok,
                negate=False,
            ),
        )

    def subtract(
        self,
        delta: ItemizedDelta | ItemizedDateDelta = UNSET,
        /,
        *,
        years: int = UNSET,
        months: int = UNSET,
        weeks: int = UNSET,
        days: int = UNSET,
        hours: int = UNSET,
        minutes: int = UNSET,
        seconds: int = UNSET,
        nanoseconds: int = UNSET,
        relative_to: _whenever.ZonedDateTime
        | _whenever.PlainDateTime
        | _whenever.OffsetDateTime = UNSET,
        in_units: Sequence[DeltaUnitStr] = UNSET,
        round_mode: RoundModeStr = UNSET,
        round_increment: int = UNSET,
        cal_unit_composition_ok: bool = UNSET,
        naive_arithmetic_ok: bool = UNSET,
        stale_offset_ok: bool = UNSET,
    ) -> ItemizedDelta:
        """Subtract a delta from this one, returning a new delta.

        The inverse of :meth:`add`, with the same parameters and rules.

        >>> ItemizedDelta(months=1, hours=5).subtract(hours=3, cal_unit_composition_ok=True)
        ItemizedDelta("P1mT2h")
        """
        return cast(
            ItemizedDelta,
            _compose(
                self,
                delta,
                {
                    "years": years,
                    "months": months,
                    "weeks": weeks,
                    "days": days,
                    "hours": hours,
                    "minutes": minutes,
                    "seconds": seconds,
                    "nanoseconds": nanoseconds,
                },
                relative_to=relative_to,
                in_units=in_units,
                round_mode=round_mode,
                round_increment=round_increment,
                cal_unit_composition_ok=cal_unit_composition_ok,
                naive_arithmetic_ok=naive_arithmetic_ok,
                stale_offset_ok=stale_offset_ok,
                negate=True,
            ),
        )

    def __add__(
        self,
        other: ItemizedDelta
        | ItemizedDateDelta
        | _whenever.ZonedDateTime
        | _whenever.PlainDateTime
        | _whenever.OffsetDateTime,
        /,
    ) -> (
        ItemizedDelta
        | _whenever.ZonedDateTime
        | _whenever.PlainDateTime
        | _whenever.OffsetDateTime
    ):
        """Compose component-wise with another itemized delta, or shift a
        datetime by this delta.

        >>> ItemizedDelta(hours=1) + ItemizedDelta(minutes=30)
        ItemizedDelta("PT1h30m")
        >>> ItemizedDelta(hours=1) + ZonedDateTime(2023, 1, 1, tz="UTC")
        ZonedDateTime("2023-01-01 01:00:00+00:00[UTC]")

        Composition emits :class:`~whenever.CalendarUnitCompositionWarning`
        when a nonzero calendar unit is involved; :meth:`add` accepts that
        with ``cal_unit_composition_ok=True``, or composes calendar-aware
        with ``relative_to``.
        """
        if isinstance(other, _datetime_types()):
            return _shift_datetime_operator(other, self, False)
        if isinstance(other, (ItemizedDelta, ItemizedDateDelta)):
            return cast(ItemizedDelta, _compose_operator(self, other, False))
        return NotImplemented

    def __radd__(
        self,
        other: _whenever.ZonedDateTime
        | _whenever.PlainDateTime
        | _whenever.OffsetDateTime,
        /,
    ) -> (
        _whenever.ZonedDateTime
        | _whenever.PlainDateTime
        | _whenever.OffsetDateTime
    ):
        if isinstance(other, _datetime_types()):
            return _shift_datetime_operator(other, self, False)
        return NotImplemented

    def __sub__(
        self, other: ItemizedDelta | ItemizedDateDelta, /
    ) -> ItemizedDelta:
        """Compose component-wise by subtracting another itemized delta.

        >>> ItemizedDelta(hours=2, minutes=30) - ItemizedDelta(minutes=30)
        ItemizedDelta("PT2h0m")

        The same rules apply as for :meth:`__add__`.
        """
        if isinstance(other, (ItemizedDelta, ItemizedDateDelta)):
            return cast(ItemizedDelta, _compose_operator(self, other, True))
        return NotImplemented

    def __rsub__(
        self,
        other: _whenever.ZonedDateTime
        | _whenever.PlainDateTime
        | _whenever.OffsetDateTime,
        /,
    ) -> (
        _whenever.ZonedDateTime
        | _whenever.PlainDateTime
        | _whenever.OffsetDateTime
    ):
        if isinstance(other, _datetime_types()):
            return _shift_datetime_operator(other, self, True)
        return NotImplemented

    def in_units(
        self,
        units: Sequence[DeltaUnitStr],
        /,
        *,
        relative_to: _whenever.ZonedDateTime
        | _whenever.PlainDateTime
        | _whenever.OffsetDateTime,
        round_mode: RoundModeStr = "trunc",
        round_increment: int = 1,
        naive_arithmetic_ok: bool = UNSET,
        stale_offset_ok: bool = UNSET,
    ) -> ItemizedDelta:
        """Convert this delta into the given units.

        >>> d = ItemizedDelta(years=1, months=8, minutes=1000)
        >>> d.in_units(["weeks", "hours"], relative_to=ZonedDateTime(2020, 6, 30, 12, tz="Asia/Tokyo"))
        ItemizedDelta("P86wT160h")

        Parameters
        ----------
        units
            The units of the result, largest first.
        relative_to
            The reference the calendar units are resolved against.
            A :class:`ZonedDateTime` emits no warning. A
            :class:`PlainDateTime` ignores time zone transitions, and emits
            :class:`NaiveArithmeticWarning` when the computation crosses the
            calendar/exact boundary. An :class:`OffsetDateTime` holds its
            offset fixed for the whole calculation, and emits
            :class:`StaleOffsetWarning` when calendar units are involved.
        round_mode
            The rounding mode for the smallest unit in ``units``, as on
            :meth:`~ZonedDateTime.since`.
        round_increment
            The rounding increment for that unit.
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
        reference, warning = _reference_and_warning(
            relative_to,
            *_has_unit_kinds(self, units),
            naive_arithmetic_ok,
            stale_offset_ok,
        )
        result = _shift_reference(reference, self, 2).since(
            reference,
            in_units=units,
            round_mode=round_mode,
            round_increment=round_increment,
        )
        if warning is not None:
            warn(warning, stacklevel=2)
        return result

    def total(
        self,
        unit: DeltaTotalUnitStr,
        /,
        *,
        relative_to: _whenever.ZonedDateTime
        | _whenever.PlainDateTime
        | _whenever.OffsetDateTime,
        naive_arithmetic_ok: bool = UNSET,
        stale_offset_ok: bool = UNSET,
    ) -> float:
        """The total duration in the given unit.

        >>> d = ItemizedDelta(months=1, hours=6)
        >>> d.total("days", relative_to=ZonedDateTime(2023, 1, 1, tz="UTC"))
        31.25
        >>> d.total("nanoseconds", relative_to=ZonedDateTime(2023, 1, 1, tz="UTC"))
        2700000000000000

        Parameters
        ----------
        unit
            The unit to sum into. ``"nanoseconds"`` gives an ``int``, any
            other unit a ``float``.
        relative_to
            The reference the calendar units are resolved against.
            A :class:`ZonedDateTime` emits no warning. A
            :class:`PlainDateTime` ignores time zone transitions, and emits
            :class:`NaiveArithmeticWarning` when the computation crosses the
            calendar/exact boundary. An :class:`OffsetDateTime` holds its
            offset fixed for the whole calculation, and emits
            :class:`StaleOffsetWarning` when calendar units are involved.
        naive_arithmetic_ok
            Accepts the :class:`NaiveArithmeticWarning` of a
            :class:`PlainDateTime` reference.
        stale_offset_ok
            Accepts the :class:`StaleOffsetWarning` of an
            :class:`OffsetDateTime` reference.
        """
        if unit not in TOTAL_UNITS:
            raise invalid("unit", unit)
        reference, warning = _reference_and_warning(
            relative_to,
            *_has_unit_kinds(self, (unit,)),
            naive_arithmetic_ok,
            stale_offset_ok,
        )
        result = (_shift_reference(reference, self, 2) - reference).total(
            unit, relative_to=reference
        )
        if warning is not None:
            warn(warning, stacklevel=2)
        return result

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
        """Create a new delta with the given components replaced

        A component given as ``None`` is removed. Removing the last one
        raises :class:`ValueError`, as does a mixed sign.

        >>> d = ItemizedDelta(years=1, months=2, hours=3)
        >>> d.replace(months=None, hours=2)
        ItemizedDelta("P1yT2h")
        """
        check_no_kwargs(
            {k: v for k, v in kwargs.items() if k not in DELTA_UNITS},
            "replace",
        )
        kwargs_w_sentinel = {
            k: UNSET if v is None else v for k, v in kwargs.items()
        }
        components = {**self, **kwargs_w_sentinel}
        if all(v is UNSET for v in components.values()):
            raise ValueError("at least one component must remain present")
        return ItemizedDelta(**components)

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

    def __str__(self) -> str:
        return self.format_iso()

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

    def _to_tuple(self) -> tuple[int | None, ...]:  # pragma: no cover
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
    components = {
        "years": years,
        "months": months,
        "weeks": weeks,
        "days": days,
        "hours": hours,
        "minutes": minutes,
        "seconds": seconds,
        "nanoseconds": nanoseconds,
    }
    return ItemizedDelta(
        **{k: v for k, v in components.items() if v is not None}
    )


_unpkl_idelta.__module__ = "whenever"


@final
class ItemizedDateDelta(_Base, Mapping[DateDeltaUnitStr, int]):
    """A date delta that preserves the components it was given.
    It closely models the ISO 8601 duration format for date-only durations.

    >>> d = ItemizedDateDelta(years=2, weeks=3)
    ItemizedDateDelta("P2y3w")
    >>> str(ItemizedDateDelta("P22W"))
    'P22W'

    It behaves like a mapping where the keys are
    the unit names and the values are the amounts.
    Items are ordered from largest to smallest unit.

    >>> d['weeks']
    3
    >>> print(d.get('days'))
    None
    >>> dict(d)
    {"years": 2, "weeks": 3}
    >>> list(d.keys())
    ["years", "weeks"]
    >>> years, weeks = d.values()
    (2, 3)

    ``ItemizedDateDelta`` also supports other dictionary-like operations:

    >>> "days" in d  # check for presence of a component
    False
    >>> len(d)  # number of components present
    2

    An explicit zero is a present component, distinct from an absent one:

    >>> d2 = ItemizedDateDelta(years=2, weeks=3, days=0)
    >>> dict(d2)
    {"years": 2, "weeks": 3, "days": 0}

    Additionally, no normalization is performed.
    Months are not rolled into years, weeks into days, etc.

    >>> d3 = ItemizedDateDelta(months=24, days=100)
    ItemizedDateDelta("P24m100d")

    An empty delta is not allowed: at least one component must be present, but it may be zero:

    >>> ItemizedDateDelta()
    ValueError: at least one component must be present
    >>> ItemizedDateDelta(days=0)
    ItemizedDateDelta("P0d")

    Negative deltas are supported, but all components must have the same sign:

    >>> d4 = ItemizedDateDelta(years=-1, weeks=-2, days=0)
    ItemizedDateDelta("-P1y2w0d")
    >>> ItemizedDateDelta(years=1, days=-3)
    ValueError: mixed sign in delta

    Note
    ----
    ``ItemizedDateDelta`` does not normalize its components. This means that
    ``ItemizedDateDelta(months=14)`` and
    ``ItemizedDateDelta(years=1, months=2)`` are considered different values.
    To convert to a normalized form, use :meth:`in_units`.
    See also the `delta documentation <https://whenever.rtfd.io/en/latest/guide/deltas.html>`_.
    """

    __module__ = "whenever"

    __slots__ = (
        # Values are stored as signed integers (or None if absent).
        # All non-zero components must have the same sign.
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
        self._years, sign = _check_component(
            "years", years, sign, _MAX_DELTA_YEARS, _OUT_OF_RANGE_MSG
        )
        self._months, sign = _check_component(
            "months", months, sign, _MAX_DELTA_MONTHS, _OUT_OF_RANGE_MSG
        )
        self._weeks, sign = _check_component(
            "weeks", weeks, sign, _MAX_DELTA_WEEKS, _OUT_OF_RANGE_MSG
        )
        self._days, sign = _check_component(
            "days", days, sign, _MAX_DELTA_DAYS, _OUT_OF_RANGE_MSG
        )
        if (
            years is UNSET
            and months is UNSET
            and weeks is UNSET
            and days is UNSET
        ):
            # This is to ensure ISO8601 formatting/parsing is round-trip safe.
            # There is no "empty" duration in ISO 8601; at least one component must be present.
            raise ValueError("at least one component must be present")

    __init__ = add_alternate_constructors(__init__, None)

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
        relative_to: _whenever.Date
        | _whenever.ZonedDateTime
        | _whenever.PlainDateTime
        | _whenever.OffsetDateTime,
        round_mode: RoundModeStr = "trunc",
        round_increment: int = 1,
    ) -> ItemizedDateDelta:
        """Convert this delta into the given units.

        >>> d = ItemizedDateDelta(years=1, months=8)
        >>> d.in_units(["weeks", "days"], relative_to=Date(2020, 6, 30))
        ItemizedDateDelta("P86w6d")

        Parameters
        ----------
        units
            The units of the result, largest first.
        relative_to
            The reference the calendar units are resolved against: a
            :class:`Date`, or a datetime of which only the date is read,
            without a warning.
        round_mode
            The rounding mode for the smallest unit in ``units``, as on
            :meth:`~Date.since`.
        round_increment
            The rounding increment for that unit.
        """
        units = normalize_units(units, DATE_DELTA_UNITS)
        round_mode, round_increment = resolve_date_rounding(
            round_mode, round_increment
        )
        date = _reference_date(relative_to)
        return date.add(self).since(
            date,
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
        """Create a new delta with the given components replaced

        A component given as ``None`` is removed. Removing the last one
        raises :class:`ValueError`, as does a mixed sign.

        >>> d = ItemizedDateDelta(years=1, months=2, weeks=3)
        >>> d.replace(months=None, weeks=4)
        ItemizedDateDelta("P1y4w")
        """
        check_no_kwargs(
            {k: v for k, v in kwargs.items() if k not in DATE_DELTA_UNITS},
            "replace",
        )
        kwargs_w_sentinel = {
            k: UNSET if v is None else v for k, v in kwargs.items()
        }
        components: dict[str, object] = {
            **{key: value for key, value in self.items()},
            **kwargs_w_sentinel,
        }
        if all(v is UNSET for v in components.values()):
            raise ValueError("at least one component must remain present")
        return ItemizedDateDelta(**cast(Any, components))

    def format_iso(self, *, lowercase_units: bool = False) -> str:
        """Convert to the canonical ISO 8601 string representation:

        .. code-block:: text

            P(nY)(nM)(nW)(nD)

        You can also use ``str(d)`` which is equivalent to ``d.format_iso()``.

        Inverse of :meth:`parse_iso`.

        >>> d = ItemizedDateDelta(weeks=1, days=11)
        >>> d.format_iso()
        'P1W11D'

        Parameters
        ----------
        lowercase_units
            Write the unit designators in lowercase, as ``repr()`` does;
            ``parse_iso()`` reads both cases.

        Note
        ----
        Negative deltas are prefixed with a minus sign,
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

        # NOTE: we always have at least one component,
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
        exc = ValueError(f"invalid ISO 8601 string: {s!r}")
        sign, rest = _parse_iso_prefix(s, exc)
        rest, years, months, weeks, days = _parse_iso_date_part(rest, exc)
        if rest:
            raise exc

        if not (years or months or weeks or days):
            sign = 0

        # NOTE: we've implicitly validated that at least one component is present
        return cls._from_signed(sign, years, months, weeks, days)

    # These methods defer to the base class implementations, but need to be
    # documented here for the API docs.
    if not TYPE_CHECKING:  # pragma: no cover
        if SPHINX_RUNNING:

            def keys(self) -> KeysView[DateDeltaUnitStr]:
                """The names of the present components, ordered from largest to smallest unit.

                Part of the mapping protocol
                """
                ...

            def values(self) -> ValuesView[int]:
                """The values of the present components, in order
                of largest to smallest unit.

                >>> d = ItemizedDateDelta(years=3, days=12, months=0)
                >>> years, months, days = d.values()
                (3, 0, 12)
                >>> list(d.values())
                [3, 0, 12]
                """
                ...

            def items(self) -> ItemsView[DateDeltaUnitStr, int]:
                """The present components as (unit, value) pairs,
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
                """Get the value of a specific component by name, or return default if absent.

                Part of the mapping protocol
                """
                ...

    def __iter__(self) -> Iterator[DateDeltaUnitStr]:
        """Iterate over the present components, ordered from largest to smallest unit."""
        if self._years is not None:
            yield "years"
        if self._months is not None:
            yield "months"
        if self._weeks is not None:
            yield "weeks"
        if self._days is not None:
            yield "days"

    def __getitem__(self, key: DateDeltaUnitStr, /) -> int:
        """Get the value of a specific component by name.

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
        """The number of present components.

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

    def __contains__(self, key: object, /) -> bool:
        """Whether a specific component is present.

        >>> d = ItemizedDateDelta(weeks=1, days=0)
        >>> "weeks" in d
        True
        >>> "days" in d
        True
        >>> "months" in d
        False
        """
        match key:
            case "years":
                return self._years is not None
            case "months":
                return self._months is not None
            case "weeks":
                return self._weeks is not None
            case "days":
                return self._days is not None
            case _:
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

    def __eq__(self, other: object, /) -> bool:
        """Compare each component for equality, under the following rules:

        - No normalization is performed. 12 months is not equal to 1 year, etc.
        - An explicit zero is equivalent to an absent component.
        - An :class:`ItemizedDelta` with the same components is equal.

        If you want strict equality (including presence of components
        and the type), use :meth:`strict_eq`.

        >>> d = ItemizedDateDelta(weeks=2, days=3)
        >>> d == ItemizedDateDelta(weeks=2, days=3, months=0)
        True
        >>> d == ItemizedDateDelta(weeks=2, days=4)
        False
        >>> d == ItemizedDelta(weeks=2, days=3, hours=0)
        True
        """
        # An ItemizedDelta operand is compared by its reflected __eq__
        if not isinstance(other, ItemizedDateDelta):
            return NotImplemented
        return (
            (self._years or 0) == (other._years or 0)
            and (self._months or 0) == (other._months or 0)
            and (self._weeks or 0) == (other._weeks or 0)
            and (self._days or 0) == (other._days or 0)
        )

    def __hash__(self) -> int:
        # Equal values must hash alike, so a component given as zero
        # hashes like a missing one.
        return hash(tuple((k, v) for k, v in self.items() if v))

    def strict_eq(self, other: ItemizedDateDelta, /) -> bool:
        """Compare two deltas, including what ``==`` ignores.

        ``ItemizedDateDelta.__eq__`` ignores the argument's type, and whether
        a component was given explicitly as zero. An argument of a different
        type raises :exc:`TypeError`.

        >>> d = ItemizedDateDelta(weeks=2, days=3)
        >>> d == ItemizedDateDelta(weeks=2, days=3, months=0)
        True
        >>> d.strict_eq(ItemizedDateDelta(weeks=2, days=3, months=0))
        False

        See :ref:`strict-equality` for the rules on every type.
        """
        if type(other) is not type(self):
            raise TypeError(
                "strict_eq() argument must be an ItemizedDateDelta"
            )
        return (
            self._years == other._years
            and self._months == other._months
            and self._weeks == other._weeks
            and self._days == other._days
        )

    def exact_eq(self, other: ItemizedDateDelta, /) -> bool:
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

    def __abs__(self) -> ItemizedDateDelta:
        """If the components are negative, return the positive version

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
        """Invert the sign of the components

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

    def add(
        self,
        delta: ItemizedDateDelta | ItemizedDelta = UNSET,
        /,
        *,
        years: int = UNSET,
        months: int = UNSET,
        weeks: int = UNSET,
        days: int = UNSET,
        relative_to: _whenever.Date
        | _whenever.ZonedDateTime
        | _whenever.PlainDateTime
        | _whenever.OffsetDateTime = UNSET,
        in_units: Sequence[DeltaUnitStr] = UNSET,
        round_mode: RoundModeStr = UNSET,
        round_increment: int = UNSET,
        cal_unit_composition_ok: bool = UNSET,
        naive_arithmetic_ok: bool = UNSET,
        stale_offset_ok: bool = UNSET,
    ) -> ItemizedDateDelta | ItemizedDelta:
        """Add a delta to this one, returning a new delta.

        Pass either a delta or its components as keywords, not both. The
        operands decide the result type: an :class:`ItemizedDateDelta` or
        date components give an :class:`ItemizedDateDelta`, an
        :class:`ItemizedDelta` gives an :class:`ItemizedDelta`.

        >>> d = ItemizedDateDelta(months=1)
        >>> d.add(days=30, relative_to=Date(2023, 1, 1), in_units=["months", "days"])
        ItemizedDateDelta("P2m2d")
        >>> d.add(ItemizedDelta(hours=3), cal_unit_composition_ok=True)
        ItemizedDelta("P1mT3h")

        Parameters
        ----------
        delta
            The delta to add, or else its components as keywords, named
            as in the constructor.
        relative_to
            The reference for calendar-aware composition: the components of
            both deltas are summed, applied to the reference, and the result
            is measured back from it in ``in_units``. Without a reference,
            composition is component-wise: like components are summed.
            For an :class:`ItemizedDateDelta` result, a :class:`Date` or a
            datetime, of which only the date is read, without a warning.
            For an :class:`ItemizedDelta` result, a datetime.
            A :class:`ZonedDateTime` emits no warning. A
            :class:`PlainDateTime` ignores time zone transitions, and emits
            :class:`NaiveArithmeticWarning` when the computation crosses the
            calendar/exact boundary. An :class:`OffsetDateTime` holds its
            offset fixed for the whole calculation, and emits
            :class:`StaleOffsetWarning` when calendar units are involved.
        in_units
            The units of the result, largest first: date units for an
            :class:`ItemizedDateDelta` result. Required with
            ``relative_to``: the coarsest unit decides how the sum is
            expressed, and no default fits every sum.
        round_mode
            The rounding mode for the smallest unit in ``in_units``, as on
            :meth:`~Date.since`.
        round_increment
            The rounding increment for that unit.
        cal_unit_composition_ok
            Accepts :class:`~whenever.CalendarUnitCompositionWarning`, which
            component-wise composition emits when a nonzero calendar unit is
            involved.
        naive_arithmetic_ok
            Accepts the :class:`NaiveArithmeticWarning` of a
            :class:`PlainDateTime` reference.
        stale_offset_ok
            Accepts the :class:`StaleOffsetWarning` of an
            :class:`OffsetDateTime` reference.
        """
        return _compose(
            self,
            delta,
            {
                "years": years,
                "months": months,
                "weeks": weeks,
                "days": days,
            },
            relative_to=relative_to,
            in_units=in_units,
            round_mode=round_mode,
            round_increment=round_increment,
            cal_unit_composition_ok=cal_unit_composition_ok,
            naive_arithmetic_ok=naive_arithmetic_ok,
            stale_offset_ok=stale_offset_ok,
            negate=False,
        )

    def subtract(
        self,
        delta: ItemizedDateDelta | ItemizedDelta = UNSET,
        /,
        *,
        years: int = UNSET,
        months: int = UNSET,
        weeks: int = UNSET,
        days: int = UNSET,
        relative_to: _whenever.Date
        | _whenever.ZonedDateTime
        | _whenever.PlainDateTime
        | _whenever.OffsetDateTime = UNSET,
        in_units: Sequence[DeltaUnitStr] = UNSET,
        round_mode: RoundModeStr = UNSET,
        round_increment: int = UNSET,
        cal_unit_composition_ok: bool = UNSET,
        naive_arithmetic_ok: bool = UNSET,
        stale_offset_ok: bool = UNSET,
    ) -> ItemizedDateDelta | ItemizedDelta:
        """Subtract a delta from this one, returning a new delta.

        The inverse of :meth:`add`, with the same parameters and rules.

        >>> ItemizedDateDelta(months=1, days=5).subtract(days=3, cal_unit_composition_ok=True)
        ItemizedDateDelta("P1m2d")
        """
        return _compose(
            self,
            delta,
            {
                "years": years,
                "months": months,
                "weeks": weeks,
                "days": days,
            },
            relative_to=relative_to,
            in_units=in_units,
            round_mode=round_mode,
            round_increment=round_increment,
            cal_unit_composition_ok=cal_unit_composition_ok,
            naive_arithmetic_ok=naive_arithmetic_ok,
            stale_offset_ok=stale_offset_ok,
            negate=True,
        )

    def __add__(
        self,
        other: ItemizedDateDelta
        | ItemizedDelta
        | _whenever.Date
        | _whenever.ZonedDateTime
        | _whenever.PlainDateTime
        | _whenever.OffsetDateTime,
        /,
    ) -> (
        ItemizedDateDelta
        | ItemizedDelta
        | _whenever.Date
        | _whenever.ZonedDateTime
        | _whenever.PlainDateTime
        | _whenever.OffsetDateTime
    ):
        """Compose component-wise with another itemized delta, or shift a
        date or datetime by this delta.

        >>> ItemizedDateDelta(months=1) + ItemizedDateDelta(days=3)
        ItemizedDateDelta("P1m3d")
        >>> ItemizedDateDelta(months=1) + Date(2023, 1, 31)
        Date("2023-02-28")

        The operands decide the result type: an :class:`ItemizedDelta` gives
        an :class:`ItemizedDelta`. Composition emits
        :class:`~whenever.CalendarUnitCompositionWarning` when a nonzero
        calendar unit is involved; :meth:`add` accepts that with
        ``cal_unit_composition_ok=True``, or composes calendar-aware with
        ``relative_to``.
        """
        if isinstance(other, _date_or_datetime_types()):
            return _shift_datetime_operator(other, self, False)
        if isinstance(other, (ItemizedDateDelta, ItemizedDelta)):
            return _compose_operator(self, other, False)
        return NotImplemented

    def __radd__(
        self,
        other: _whenever.Date
        | _whenever.ZonedDateTime
        | _whenever.PlainDateTime
        | _whenever.OffsetDateTime,
        /,
    ) -> (
        _whenever.Date
        | _whenever.ZonedDateTime
        | _whenever.PlainDateTime
        | _whenever.OffsetDateTime
    ):
        if isinstance(other, _date_or_datetime_types()):
            return _shift_datetime_operator(other, self, False)
        return NotImplemented

    def __sub__(
        self, other: ItemizedDateDelta | ItemizedDelta, /
    ) -> ItemizedDateDelta | ItemizedDelta:
        """Compose component-wise by subtracting another itemized delta.

        >>> ItemizedDateDelta(months=1, days=5) - ItemizedDateDelta(days=3)
        ItemizedDateDelta("P1m2d")

        The same rules apply as for :meth:`__add__`.
        """
        if isinstance(other, (ItemizedDateDelta, ItemizedDelta)):
            return _compose_operator(self, other, True)
        return NotImplemented

    def __rsub__(
        self,
        other: _whenever.Date
        | _whenever.ZonedDateTime
        | _whenever.PlainDateTime
        | _whenever.OffsetDateTime,
        /,
    ) -> (
        _whenever.Date
        | _whenever.ZonedDateTime
        | _whenever.PlainDateTime
        | _whenever.OffsetDateTime
    ):
        if isinstance(other, _date_or_datetime_types()):
            return _shift_datetime_operator(other, self, True)
        return NotImplemented

    def total(
        self,
        unit: DateDeltaUnitStr,
        /,
        *,
        relative_to: _whenever.Date
        | _whenever.ZonedDateTime
        | _whenever.PlainDateTime
        | _whenever.OffsetDateTime,
    ) -> float:
        """The total duration in the given unit, as a float.

        >>> ItemizedDateDelta(years=1, months=6).total("months", relative_to=Date(2020, 1, 31))
        18.0
        >>> ItemizedDateDelta(days=1000).total("years", relative_to=Date(2020, 4, 10))
        2.73972602739726

        Parameters
        ----------
        unit
            The unit to sum into.
        relative_to
            The reference the calendar units are resolved against: a
            :class:`Date`, or a datetime of which only the date is read,
            without a warning.
        """
        date = _reference_date(relative_to)
        return date.add(self).since(date, total=unit)

    # A private constructor that bypasses sign/presence validation.
    # All component values must be non-negative; `sign` is applied when storing.
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

        def _apply(v: int | None, max_val: int, err: str) -> int | None:
            v = _check_bound(v, max_val, err)
            return -v if v and sign < 0 else v

        self._years = _apply(years, _MAX_DELTA_YEARS, _OUT_OF_RANGE_MSG)
        self._months = _apply(months, _MAX_DELTA_MONTHS, _OUT_OF_RANGE_MSG)
        self._weeks = _apply(weeks, _MAX_DELTA_WEEKS, _OUT_OF_RANGE_MSG)
        self._days = _apply(days, _MAX_DELTA_DAYS, _OUT_OF_RANGE_MSG)
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

    def __str__(self) -> str:
        return self.format_iso()

    def _init_from_iso(self, s: str) -> None:
        parsed = type(self).parse_iso(s)
        self._years = parsed._years
        self._months = parsed._months
        self._weeks = parsed._weeks
        self._days = parsed._days

    def _to_tuple(self) -> tuple[int | None, ...]:  # pragma: no cover
        return (self._years, self._months, self._weeks, self._days)


# A separate unpickling function allows us to make backwards-compatible changes
# to the pickling format in the future
def _unpkl_iddelta(
    years: int | None,
    months: int | None,
    weeks: int | None,
    days: int | None,
) -> ItemizedDateDelta:
    components = {
        "years": years,
        "months": months,
        "weeks": weeks,
        "days": days,
    }
    return ItemizedDateDelta(
        **{k: v for k, v in components.items() if v is not None}
    )


_unpkl_iddelta.__module__ = "whenever"
