from __future__ import annotations

from datetime import (
    datetime as _datetime,
    timedelta as _timedelta,
)

from .._common import UTC, check_utc_bounds, mk_fixed_tzinfo
from .._typing import DisambiguationStr
from .common import Fold, Gap, LocalMapping, Unique
from .tzif import TimeZone


class RepeatedTime(ValueError):
    """A datetime is repeated in a timezone, e.g. because of DST"""

    @classmethod
    def _for_tz(cls, d: _datetime, tzid: str | None) -> RepeatedTime:
        return cls(f"{d} is repeated in {_tzid_display(tzid)}")


class SkippedTime(ValueError):
    """A datetime is skipped in a timezone, e.g. because of DST"""

    @classmethod
    def _for_tz(cls, d: _datetime, tzid: str | None) -> SkippedTime:
        return cls(f"{d} is skipped in {_tzid_display(tzid)}")


def _tzid_display(tzid: str | None) -> str:
    if tzid is None:
        return "system timezone (with unknown ID)"
    else:
        return f"timezone '{tzid}'"


def resolve_ambiguity(
    dt: _datetime,
    tz: TimeZone,
    disambiguation: DisambiguationStr,
) -> _datetime:
    assert dt.tzinfo is None, "dt must be naive"
    return _resolve_ambiguity_from_mapping(
        dt, tz, disambiguation, tz.ambiguity_for_local(dt)
    )


def _resolve_ambiguity_from_mapping(
    dt: _datetime,
    tz: TimeZone,
    disambiguation: DisambiguationStr,
    ambiguity: LocalMapping,
    /,
) -> _datetime:
    if disambiguation not in ("compatible", "earlier", "later", "raise"):
        raise ValueError(
            "disambiguation must be 'compatible', 'earlier', 'later', or 'raise'"
        )
    match ambiguity:
        case Unique(offset):
            pass
        case Fold(_, earlier_offset, later_offset):
            if disambiguation in ("compatible", "earlier"):
                offset = earlier_offset
            elif disambiguation == "later":
                offset = later_offset
            else:  # disambiguation == "raise"
                raise RepeatedTime._for_tz(dt, tz.key)
        case Gap(_, later_offset, earlier_offset):  # pragma: no branch
            if disambiguation in ("compatible", "later"):
                offset = later_offset
                shift = later_offset - earlier_offset
            elif disambiguation == "earlier":
                offset = earlier_offset
                shift = earlier_offset - later_offset
            else:  # disambiguation == "raise"
                raise SkippedTime._for_tz(dt, tz.key)
            # shift the datetime out of the gap
            dt += _timedelta(seconds=shift)

    # This ensures we raise an exception if the instant is out of range,
    # even if the local time is valid.
    return check_utc_bounds(dt.replace(tzinfo=mk_fixed_tzinfo(offset)))


def resolve_ambiguity_using_prev_offset(
    dt: _datetime, prev_offset: _timedelta, tz: TimeZone
) -> _datetime:
    return _resolve_ambiguity_using_prev_offset_from_mapping(
        dt, prev_offset, tz.ambiguity_for_local(dt)
    )


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
