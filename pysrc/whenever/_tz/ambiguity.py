from __future__ import annotations

from datetime import (
    datetime as _datetime,
    timedelta as _timedelta,
)

from .._common import UTC, mk_fixed_tzinfo
from .common import Disambiguate, Fold, Unambiguous
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
    dt: _datetime, tz: TimeZone, disambiguate: Disambiguate | _timedelta
) -> _datetime:
    assert dt.tzinfo is None, "dt must be naive"
    if isinstance(disambiguate, _timedelta):
        return resolve_ambiguity_using_prev_offset(dt, disambiguate, tz)
    elif disambiguate not in ("compatible", "earlier", "later", "raise"):
        raise ValueError(
            "disambiguate must be 'compatible', 'earlier', 'later', or 'raise'"
        )

    ambiguity = tz.ambiguity_for_local(int(dt.replace(tzinfo=UTC).timestamp()))
    if isinstance(ambiguity, Unambiguous):
        offset = ambiguity.offset
    elif isinstance(ambiguity, Fold):
        if disambiguate in ("compatible", "earlier"):
            offset = ambiguity.before
        elif disambiguate == "later":
            offset = ambiguity.after
        else:  # disambiguate == "raise"
            raise RepeatedTime._for_tz(dt, tz.key)
    else:  # isinstance(ambiguity, Gap):
        if disambiguate in ("compatible", "later"):
            offset = ambiguity.before
            shift = ambiguity.before - ambiguity.after
        elif disambiguate == "earlier":
            offset = ambiguity.after
            shift = ambiguity.after - ambiguity.before
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
    ambiguity = tz.ambiguity_for_local(int(dt.replace(tzinfo=UTC).timestamp()))
    offset = int(prev_offset.total_seconds())
    if isinstance(ambiguity, Unambiguous):
        offset = ambiguity.offset
    elif isinstance(ambiguity, Fold):
        # If the offset is already valid, there's nothing to do
        # otherwise, always use the earlier offset
        if ambiguity.after != offset:
            offset = ambiguity.before
    else:  # isinstance(ambiguity, Gap)
        if ambiguity.before == offset:
            shift = offset - ambiguity.before
        else:
            offset = ambiguity.after
            shift = ambiguity.after - ambiguity.before
        dt += _timedelta(seconds=shift)

    return dt.replace(tzinfo=mk_fixed_tzinfo(offset))
