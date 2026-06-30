from __future__ import annotations

from datetime import (
    datetime as _datetime,
    timedelta as _timedelta,
)

from .._common import UTC, mk_fixed_tzinfo
from .._typing import DisambiguateStr
from .common import Fold, Gap, Unambiguous
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
    dt: _datetime, tz: TimeZone, disambiguate: DisambiguateStr | _timedelta
) -> _datetime:
    assert dt.tzinfo is None, "dt must be naive"
    if isinstance(disambiguate, _timedelta):
        return resolve_ambiguity_using_prev_offset(dt, disambiguate, tz)
    elif disambiguate not in ("compatible", "earlier", "later", "raise"):
        raise ValueError(
            "disambiguate must be 'compatible', 'earlier', 'later', or 'raise'"
        )

    ambiguity = tz.ambiguity_for_local(dt)
    match ambiguity:
        case Unambiguous(offset):
            pass
        case Fold(_, earlier_offset, later_offset):
            if disambiguate in ("compatible", "earlier"):
                offset = earlier_offset
            elif disambiguate == "later":
                offset = later_offset
            else:  # disambiguate == "raise"
                raise RepeatedTime._for_tz(dt, tz.key)
        case Gap(_, later_offset, earlier_offset):  # pragma: no branch
            if disambiguate in ("compatible", "later"):
                offset = later_offset
                shift = later_offset - earlier_offset
            elif disambiguate == "earlier":
                offset = earlier_offset
                shift = earlier_offset - later_offset
            else:  # disambiguate == "raise"
                raise SkippedTime._for_tz(dt, tz.key)
            # shift the datetime out of the gap
            dt += _timedelta(seconds=shift)

    resolved = dt.replace(tzinfo=mk_fixed_tzinfo(offset))
    # This ensures we raise an exception if the instant is out of range,
    # even if the local time is valid.
    resolved.astimezone(UTC)
    return resolved


def resolve_ambiguity_using_prev_offset(
    dt: _datetime, prev_offset: _timedelta, tz: TimeZone
) -> _datetime:
    ambiguity = tz.ambiguity_for_local(dt)
    offset = int(prev_offset.total_seconds())
    if isinstance(ambiguity, Unambiguous):
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
