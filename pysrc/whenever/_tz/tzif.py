"""Parsing of TZif files

This module is largely a port the Rust equivalent, so there might be some
unpythonic edges.
"""

from __future__ import annotations

import struct
from bisect import bisect_right as _bisect_right
from io import BytesIO
from typing import IO, Sequence, final

from .common import Ambiguity, Fold, Gap, Unambiguous
from .posix import TzStr, epoch_for_date, year_for_epoch

EpochSecs = int
Offset = int
OffsetDelta = int
Year = int

EPOCH_SECS_MIN = -62135596800
EPOCH_SECS_MAX = 253402300799


@final
class TimeZone:
    """A complete timezone definition, enough to represent a tzif file.

    Can also be used to represent a POSIX TZ string (if the transition arrays
    are empty) or an anonymous timezone (if the `key` field is set to `None`).

    The timezone data is stored as four parallel arrays (two pairs):

    UTC pair — for mapping an exact UTC instant to a UTC offset:
      _utc_epochs[i]   is the epoch at which transition i occurs (UTC seconds).
      _utc_offsets[i]  is the UTC offset in seconds active *before* transition i.
      ``bisect_right(_utc_epochs, t) - 1`` gives the index of the active offset.

    Local pair — for mapping a local (wall-clock) time to a UTC offset,
    including ambiguity detection for DST gaps/folds:
      _local_epochs[i]          is a local-time epoch at which something changes.
      _local_values[i]          is (offset_before, offset_delta) for that point.
      ``bisect_right(_local_epochs, t)`` points to the entry that is still
      "upcoming" from local time ``t``.

    Invariant: if posix TZ isn't given, there must be at least one entry in
    each pair.
    """

    __slots__ = (
        "__weakref__",
        "key",
        "_utc_epochs",
        "_utc_offsets",
        "_local_epochs",
        "_local_values",
        "_end",
        "_meta_by_utc",
    )

    # The IANA tz ID (e.g. "Europe/Amsterdam"). Not actually parsed from the file,
    # but essential because in our case we always associate a tzif file with a tz ID.
    key: str | None

    _utc_epochs: tuple[EpochSecs, ...]
    _utc_offsets: tuple[Offset, ...]
    _local_epochs: tuple[EpochSecs, ...]
    _local_values: tuple[tuple[Offset, OffsetDelta], ...]
    _end: TzStr | None

    def __init__(
        self,
        key: str | None,
        _utc_epochs: tuple[EpochSecs, ...],
        _utc_offsets: tuple[Offset, ...],
        _local_epochs: tuple[EpochSecs, ...],
        _local_values: tuple[tuple[Offset, OffsetDelta], ...],
        _end: TzStr | None = None,
        _meta_by_utc: tuple[tuple[int, str], ...] = (),
    ):
        self.key = key
        self._utc_epochs = _utc_epochs
        self._utc_offsets = _utc_offsets
        self._local_epochs = _local_epochs
        self._local_values = _local_values
        self._end = _end
        self._meta_by_utc = _meta_by_utc

    def offset_for_instant(self, t: EpochSecs) -> Offset:
        """Get the UTC offset at the given exact time"""
        idx = _bisect_right(self._utc_epochs, t)
        if idx < len(self._utc_epochs):
            return self._utc_offsets[max(0, idx - 1)]

        # If the time is after the last transition, use the POSIX TZ string
        if self._end is not None:
            return self._end.offset_for_instant(t)
        # If there's no POSIX TZ string, use the last offset.
        # There's not much else we can do.
        else:
            assert self._utc_offsets  # ensured during parsing
            return self._utc_offsets[-1]

    def ambiguity_for_local(self, t: EpochSecs) -> Ambiguity:
        """Get the UTC offset at the given local time (expressed in epoch seconds)"""
        idx = _bisect_right(self._local_epochs, t)
        if idx < len(self._local_epochs):
            next_transition = self._local_epochs[idx]
            offset, change = self._local_values[idx]
            # If we've landed in an ambiguous region, determine its size
            ambiguity = 0 if t < (next_transition - abs(change)) else change

            if ambiguity == 0:
                return Unambiguous(offset)
            elif ambiguity < 0:
                return Fold(offset, offset + ambiguity)
            else:  # ambiguity > 0
                return Gap(offset + ambiguity, offset)

        # If the time is after the last transition, use the POSIX TZ string
        if self._end is not None:
            return self._end.ambiguity_for_local(t)

        # If there's no POSIX TZ string, use the last offset.
        # There's not much else we can do.
        else:
            assert self._local_values  # ensured during parsing
            prev_offset, last_shift = self._local_values[-1]
            return Unambiguous(prev_offset + last_shift)

    def meta_for_instant(self, t: EpochSecs) -> tuple[int, str]:
        """Get timezone metadata (dst_saving_secs, abbreviation)
        at the given exact time."""
        idx = _bisect_right(self._utc_epochs, t)
        if idx < len(self._utc_epochs):
            return self._meta_by_utc[max(0, idx - 1)]

        # After last transition: try POSIX TZ string, then fall back
        if self._end is not None:
            return self._end.meta_for_instant(t)
        else:
            assert self._meta_by_utc  # ensured during parsing
            return self._meta_by_utc[-1]

    # NOTE: this equality check needs to be fast, since it's used in
    # some routines to check if the timezone is indeed changing.
    def __eq__(self, other: object) -> bool:
        # We first check for identity, as that's the cheapest check
        # and makes the common case fast.
        if self is other:
            return True
        # Identity inequality doesn't rule out equality, as two different
        # instances may represent the same timezone due to cache clearing.
        elif type(other) is TimeZone:
            return (
                # We compare the key first, as it's the cheapest to compare,
                # and most likely to differ
                self.key == other.key
                # Only in rare cases (i.e. system timezone changes or cache clears)
                # should we need to compare the rest of the data. It's relatively
                # expensive, so we do it last.
                and self._utc_epochs == other._utc_epochs
                and self._utc_offsets == other._utc_offsets
                and self._local_epochs == other._local_epochs
                and self._local_values == other._local_values
                and self._end == other._end
            )
        return NotImplemented  # pragma: no cover

    @classmethod
    def parse_posix(cls, s: str) -> TimeZone:
        """Create a TimeZone from a POSIX TZ string"""
        return TimeZone(
            key=None,
            _utc_epochs=(),
            _utc_offsets=(),
            _local_epochs=(),
            _local_values=(),
            _end=TzStr.parse(s),
        )

    @classmethod
    def parse_tzif(cls, data: bytes, key: str | None = None) -> TimeZone:
        """Create a TimeZone from TZif file data"""
        read = BytesIO(data)
        header = _parse_header(read)
        return _parse_content(header, read, key)


def bisect(
    arr: Sequence[tuple[EpochSecs, object]], x: EpochSecs
) -> int | None:
    """Bisect the array of (time, value) pairs to find the INDEX at the given time.
    Return None if after the last entry.
    """
    size = len(arr)
    left = 0
    right = size

    while left < right:
        mid = left + size // 2

        if x >= arr[mid][0]:
            left = mid + 1
        else:
            right = mid
        size = right - left

    return left if left != len(arr) else None


def clamp_epoch_secs(value: int) -> EpochSecs:
    """Clamp epoch seconds to valid range"""
    return max(EPOCH_SECS_MIN, min(EPOCH_SECS_MAX, value))


class Header:
    """TZif file header"""

    __slots__ = (
        "version",
        "isutcnt",
        "isstdcnt",
        "leapcnt",
        "timecnt",
        "typecnt",
        "charcnt",
    )

    version: int
    isutcnt: int
    isstdcnt: int
    leapcnt: int
    timecnt: int
    typecnt: int
    charcnt: int

    def __init__(
        self,
        version: int,
        isutcnt: int,
        isstdcnt: int,
        leapcnt: int,
        timecnt: int,
        typecnt: int,
        charcnt: int,
    ):
        self.version = version
        self.isutcnt = isutcnt
        self.isstdcnt = isstdcnt
        self.leapcnt = leapcnt
        self.timecnt = timecnt
        self.typecnt = typecnt
        self.charcnt = charcnt


def _parse_header(data: IO[bytes]) -> Header:
    """Parse TZif header and return header with new offset"""
    # Check magic bytes
    if data.read(4) != b"TZif":
        raise ValueError("Invalid header value")

    # Parse version
    version_byte = data.read(1)
    if version_byte == b"\x00":
        version = 1
    elif version_byte.isdigit():
        version = int(version_byte)
    else:
        raise ValueError("Invalid header value")  # pragma: no cover

    data.read(15)  # Skip reserved bytes

    return Header(version, *struct.unpack(">6i", data.read(24)))


# Pre-compute POSIX DST transitions up to this year so the bisect fast-path
# is used for all common date operations without falling back to the slow
# Python-level POSIX rule evaluation.
_PRECALC_UNTIL = 2050


def _extend_with_posix(
    offsets: list[tuple[EpochSecs, Offset]],
    meta: list[tuple[int, str]],
    end: TzStr,
) -> None:
    """Append pre-computed DST transitions from the POSIX TZ rule to *offsets*
    and *meta*, covering years from (last recorded year + 1) to
    ``_PRECALC_UNTIL`` inclusive.

    For timezones without a DST rule the tables are already complete; this
    function returns immediately.
    """
    if not end.dst:
        return

    start_rule, start_time = end.dst.start
    end_rule, end_time = end.dst.end
    std = end.std
    dst_offset = end.dst.offset
    dst_saving = dst_offset - std
    dst_abbrev = end.dst.abbrev
    std_abbrev = end.std_abbrev

    start_year = year_for_epoch(offsets[-1][0]) + 1 if offsets else 1970

    for year in range(start_year, _PRECALC_UNTIL + 1):
        dst_start = epoch_for_date(start_rule.apply(year)) + start_time - std
        dst_end = epoch_for_date(end_rule.apply(year)) + end_time - dst_offset
        if dst_start < dst_end:
            # Northern hemisphere: DST active in summer
            offsets.append((dst_start, dst_offset))
            offsets.append((dst_end, std))
            meta.append((dst_saving, dst_abbrev))
            meta.append((0, std_abbrev))
        else:
            # Southern hemisphere: DST active in winter
            offsets.append((dst_end, std))
            offsets.append((dst_start, dst_offset))
            meta.append((0, std_abbrev))
            meta.append((dst_saving, dst_abbrev))


def _parse_content(
    header: Header, data: IO[bytes], key: str | None
) -> TimeZone:
    """Parse the content section of a TZif file"""
    # Handle version 2+ files
    if header.version >= 2:
        # Skip v1 data section
        data.read(
            header.timecnt * 5
            + header.typecnt * 6
            + header.charcnt
            + header.leapcnt * 8
            + header.isstdcnt
            + header.isutcnt
        )
        # Parse second header
        header = _parse_header(data)
        # Parse v2 transitions (64-bit)
        transition_times = _parse_v2_transitions(header, data)
    else:
        # Parse v1 transitions (32-bit)
        transition_times = _parse_v1_transitions(header, data)

    offset_indices = list(data.read(header.timecnt))
    types = _parse_type_info(header.typecnt, data)
    abbrev_data = data.read(header.charcnt)

    offsets_by_utc, meta_by_utc = _load_transitions(
        transition_times, types, offset_indices, abbrev_data
    )

    # Parse POSIX TZ string for v2+ files
    end = None
    if header.version >= 2:
        # Skip unused metadata and newline before tz string
        data.read(header.isutcnt + header.isstdcnt + header.leapcnt * 12 + 1)
        # Find the TZ string (until newline or end of data)
        tz_string, *_ = data.read().split(b"\n", 1)

        if tz_string:  # pragma: no branch
            end = TzStr.parse(tz_string.decode("ascii"))

    if not (end or offsets_by_utc):
        raise ValueError("No transition data in file")  # pragma: no cover

    # Pre-compute transitions from POSIX rule up to a fixed horizon.
    # This ensures the fast bisect path is used for common date ranges,
    # avoiding repeated Python-level DST boundary calculations.
    if end:
        _extend_with_posix(offsets_by_utc, meta_by_utc, end)

    local_transitions = _local_transitions(offsets_by_utc)
    return TimeZone(
        key=key,
        _utc_epochs=tuple(t for t, _ in offsets_by_utc),
        _utc_offsets=tuple(v for _, v in offsets_by_utc),
        _local_epochs=tuple(t for t, _ in local_transitions),
        _local_values=tuple(v for _, v in local_transitions),
        _end=end,
        _meta_by_utc=tuple(meta_by_utc),
    )


def _parse_v2_transitions(
    header: Header, data: IO[bytes]
) -> Sequence[EpochSecs]:
    return list(
        map(
            clamp_epoch_secs,
            struct.unpack(
                f">{header.timecnt}q", data.read(8 * header.timecnt)
            ),
        )
    )


def _parse_v1_transitions(
    header: Header, data: IO[bytes]
) -> Sequence[EpochSecs]:
    return struct.unpack(f">{header.timecnt}i", data.read(4 * header.timecnt))


def _parse_type_info(
    typecnt: int, data: IO[bytes]
) -> Sequence[tuple[Offset, bool, int]]:
    """Parse type info records: (utoff, isdst, abbrind)"""
    return [
        (utoff, isdst != 0, abbrind)
        for utoff, isdst, abbrind in struct.iter_unpack(
            ">iBB", data.read(6 * typecnt)
        )
    ]


def _abbrev_at(abbrev_data: bytes, idx: int) -> str:
    """Extract a NUL-terminated abbreviation string at the given index."""
    try:
        end = abbrev_data.index(b"\x00", idx)
    except ValueError:  # pragma: no cover
        end = len(abbrev_data)
    return abbrev_data[idx:end].decode("ascii", errors="replace")


def _load_transitions(
    transition_times: Sequence[EpochSecs],
    types: Sequence[tuple[Offset, bool, int]],
    indices: Sequence[int],
    abbrev_data: bytes,
) -> tuple[
    Sequence[tuple[EpochSecs, Offset]],
    Sequence[tuple[int, str]],
]:
    """Load transitions and metadata from parsed data"""
    first_utoff, first_isdst, first_abbrind = types[0]
    last_std_offset = first_utoff

    offsets: list[tuple[EpochSecs, Offset]] = [
        (EPOCH_SECS_MIN, first_utoff),
    ]
    meta: list[tuple[int, str]] = [
        (0, _abbrev_at(abbrev_data, first_abbrind)),
    ]

    for idx, epoch in zip(indices, transition_times):
        utoff, isdst, abbrind = types[idx]
        offsets.append((epoch, utoff))

        dst_saving = utoff - last_std_offset if isdst else 0
        if not isdst:
            last_std_offset = utoff

        meta.append((dst_saving, _abbrev_at(abbrev_data, abbrind)))

    return offsets, meta


# See the TimeZone class definition for explanation of these data structures
def _local_transitions(
    transitions: Sequence[tuple[EpochSecs, Offset]],
) -> Sequence[tuple[EpochSecs, tuple[Offset, OffsetDelta]]]:
    result: list[tuple[EpochSecs, tuple[Offset, OffsetDelta]]] = []
    assert transitions  # we've ensured there's at least one transition

    (_, offset_prev), *remaining = transitions
    for epoch, offset in remaining:
        # NOTE: we don't check for "impossible" gaps or folds
        local_time = epoch + max(offset_prev, offset)
        # Saturating add to be consistent with Rust version
        local_time = max(EPOCH_SECS_MIN, min(EPOCH_SECS_MAX, local_time))

        result.append((local_time, (offset_prev, offset - offset_prev)))
        offset_prev = offset

    return result
