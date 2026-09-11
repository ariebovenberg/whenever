from __future__ import annotations

from datetime import (
    datetime as _datetime,
    timedelta as _timedelta,
)

from .._common import check_utc_bounds, invalid, mk_fixed_tzinfo, tzid_display
from .._typing import DisambiguationStr
from .common import Fold, Gap, LocalMapping, Unique
from .tzif import TimeZone


class RepeatedTime(ValueError):
    """A local time that is repeated in a time zone, e.g. because of DST.

    See :term:`repeated local time`.
    """

    @classmethod
    def _for_tz(
        cls, d: _datetime, nanos: int, tzid: str | None
    ) -> RepeatedTime:
        return cls(
            f"{_local_display(d, nanos)} is repeated in {tzid_display(tzid)}"
        )


class SkippedTime(ValueError):
    """A local time that is skipped in a time zone, e.g. because of DST.

    See :term:`skipped local time`.
    """

    @classmethod
    def _for_tz(
        cls, d: _datetime, nanos: int, tzid: str | None
    ) -> SkippedTime:
        return cls(
            f"{_local_display(d, nanos)} is skipped in {tzid_display(tzid)}"
        )


def _local_display(d: _datetime, nanos: int) -> str:
    """The local datetime as messages show it: subseconds only when nonzero."""
    base = f"{d.date()} {d.hour:02d}:{d.minute:02d}:{d.second:02d}"
    return base + (f".{nanos:09d}".rstrip("0") if nanos else "")


def resolve_ambiguity(
    dt: _datetime,
    tz: TimeZone,
    disambiguation: DisambiguationStr,
    nanos: int,
) -> _datetime:
    assert dt.tzinfo is None, "dt must be naive"
    return _resolve_ambiguity_from_mapping(
        dt, tz, disambiguation, tz.ambiguity_for_local(dt), nanos
    )


def _resolve_ambiguity_from_mapping(
    dt: _datetime,
    tz: TimeZone,
    disambiguation: DisambiguationStr,
    ambiguity: LocalMapping,
    nanos: int,
    /,
) -> _datetime:
    if disambiguation not in ("compatible", "earlier", "later", "raise"):
        raise invalid("disambiguation", disambiguation)
    match ambiguity:
        case Unique(offset):
            pass
        case Fold(_, earlier_offset, later_offset):
            if disambiguation in ("compatible", "earlier"):
                offset = earlier_offset
            elif disambiguation == "later":
                offset = later_offset
            else:  # disambiguation == "raise"
                raise RepeatedTime._for_tz(dt, nanos, tz.key)
        case Gap(_, later_offset, earlier_offset):  # pragma: no branch
            if disambiguation in ("compatible", "later"):
                offset = later_offset
                shift = later_offset - earlier_offset
            elif disambiguation == "earlier":
                offset = earlier_offset
                shift = earlier_offset - later_offset
            else:  # disambiguation == "raise"
                raise SkippedTime._for_tz(dt, nanos, tz.key)
            # shift the datetime out of the gap
            dt += _timedelta(seconds=shift)

    # This ensures we raise an exception if the instant is out of range,
    # even if the local time is valid.
    return check_utc_bounds(dt.replace(tzinfo=mk_fixed_tzinfo(offset)))


def _resolve_ambiguity_using_prev_offset_from_mapping(
    dt: _datetime,
    prev_offset: _timedelta,
    ambiguity: LocalMapping,
    /,
) -> _datetime:
    offset = int(prev_offset.total_seconds())
    if isinstance(ambiguity, Unique):
        offset = ambiguity.offset
    elif isinstance(ambiguity, Fold):
        # If the offset is already valid, there's nothing to do
        # otherwise, always use the earlier offset
        if ambiguity.later_offset != offset:
            offset = ambiguity.earlier_offset
    else:  # isinstance(ambiguity, Gap)
        # Don't try to reuse the previous offset in case of a gap,
        # since we can't prevent an unexpected shift anyway.
        # We just do the default (compatible) behavior.
        offset = ambiguity.later_offset
        dt += _timedelta(seconds=offset - ambiguity.earlier_offset)

    return dt.replace(tzinfo=mk_fixed_tzinfo(offset))
