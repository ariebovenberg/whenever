"""Parsing of TZif files

This module is largely a port the Rust equivalent, so there might be some
unpythonic edges.
"""

from __future__ import annotations

import struct
from bisect import bisect_left as _bisect_left, bisect_right as _bisect_right
from datetime import datetime as _datetime, timezone as _timezone
from io import BytesIO
from typing import IO, MutableSequence, Sequence, final

from .._common import (
    EPOCH_SECS_MAX,
    EPOCH_SECS_MIN,
    RANGE_MSG,
    mk_fixed_tzinfo,
)
from .common import Fold, Gap, LocalMapping, Unique
from .posix import MAX_OFFSET, TzStr, year_for_epoch

EpochSecs = int
Offset = int
OffsetDelta = int
TransitionMeta = tuple[int, int | None, str]
Year = int


@final
class TimeZone:
    """A complete time zone definition, enough to represent a tzif file.

    Can also be used to represent a POSIX TZ string (if the transition arrays
    are empty) or an anonymous time zone (if the `key` field is set to `None`).

    The time zone data is stored as four parallel arrays (two pairs):

    UTC pair — for mapping an exact UTC instant to a UTC offset:
      _utc_epochs[i]   is the epoch at which transition i occurs (UTC seconds).
      _utc_offsets[i]  is the UTC offset in seconds active *from* transition i.
      ``bisect_right(_utc_epochs, t) - 1`` gives the index of the active offset.

    Local pair — for mapping a local (wall-clock) time to a UTC offset,
    including ambiguity detection for DST gaps/folds:
      _local_epochs[i]          is a local-time epoch at which something changes.
      _local_values[i]          is (offset_before, offset_delta) for that point.
      ``bisect_right(_local_epochs, t)`` points to the entry that is still
      "upcoming" from local time ``t``.

    Invariant: if posix TZ isn't given, there must be at least one entry in
    each pair.

    The POSIX TZ string takes over from the last recorded offset at
    ``_footer_from``: its first transition after the file's last record,
    which may be a marker that changes nothing (zic's "slim" files). Before
    it, the last recorded offset holds. ``_footer_local_from`` is where that
    transition's gap or fold begins, in local time.
    """

    __slots__ = (
        "__weakref__",
        "key",
        "_utc_epochs",
        "_utc_offsets",
        "_local_epochs",
        "_local_values",
        "_end",
        "_footer_from",
        "_footer_local_from",
        "_meta_by_utc",
        "_abbrev_data",
    )

    # The IANA tz ID (e.g. "Europe/Amsterdam"). Not actually parsed from the file,
    # but essential because in our case we always associate a tzif file with a tz ID.
    key: str | None

    _utc_epochs: tuple[EpochSecs, ...]
    _utc_offsets: tuple[Offset, ...]
    _local_epochs: tuple[EpochSecs, ...]
    _local_values: tuple[tuple[Offset, OffsetDelta], ...]
    _end: TzStr | None
    _footer_from: EpochSecs
    _footer_local_from: EpochSecs

    def __init__(
        self,
        key: str | None,
        _utc_epochs: tuple[EpochSecs, ...],
        _utc_offsets: tuple[Offset, ...],
        _local_epochs: tuple[EpochSecs, ...],
        _local_values: tuple[tuple[Offset, OffsetDelta], ...],
        _end: TzStr | None,
        _footer_from: EpochSecs,
        _footer_local_from: EpochSecs,
        _meta_by_utc: tuple[TransitionMeta, ...],
        _abbrev_data: bytes,
    ):
        self.key = key
        self._utc_epochs = _utc_epochs
        self._utc_offsets = _utc_offsets
        self._local_epochs = _local_epochs
        self._local_values = _local_values
        self._end = _end
        self._footer_from = _footer_from
        self._footer_local_from = _footer_local_from
        self._meta_by_utc = _meta_by_utc
        self._abbrev_data = _abbrev_data

    def offset_for_instant(self, t: EpochSecs) -> Offset:
        """Get the UTC offset at the given exact time"""
        idx = _bisect_right(self._utc_epochs, t)
        if idx < len(self._utc_epochs):
            return self._utc_offsets[max(0, idx - 1)]

        # If the time is after the last transition, use the POSIX TZ string
        if self._end is not None and t >= self._footer_from:
            return self._end.offset_for_instant(t)
        # Otherwise, the last offset holds.
        else:
            assert self._utc_offsets  # ensured during parsing
            return self._utc_offsets[-1]

    def convert(self, dt: _datetime) -> _datetime:
        """Re-express an aware datetime with the offset at its instant"""
        try:
            return dt.astimezone(
                mk_fixed_tzinfo(self.offset_for_instant(int(dt.timestamp())))
            )
        except OverflowError:
            raise ValueError(RANGE_MSG) from None

    def ambiguity_for_local(self, dt: _datetime) -> LocalMapping:
        assert dt.tzinfo is None
        return self._ambiguity_for_local_epoch(
            int(dt.replace(tzinfo=_timezone.utc).timestamp())
        )

    def _ambiguity_for_local_epoch(self, t: EpochSecs) -> LocalMapping:
        """Get the UTC offset at the given local time (expressed in epoch seconds)"""
        idx = _bisect_right(self._local_epochs, t)
        if idx < len(self._local_epochs):
            next_transition = self._local_epochs[idx]
            offset, change = self._local_values[idx]
            # If we've landed in an ambiguous region, determine its size
            ambiguity = 0 if t < (next_transition - abs(change)) else change

            if ambiguity == 0:
                return Unique(offset)
            elif ambiguity < 0:
                return Fold(next_transition, offset, offset + ambiguity)
            else:  # ambiguity > 0
                return Gap(next_transition, offset + ambiguity, offset)

        # If the time is after the last transition, use the POSIX TZ string
        if self._end is not None and t >= self._footer_local_from:
            return self._end._ambiguity_for_local_epoch(t)

        # Otherwise, the last offset holds.
        else:
            assert self._utc_offsets  # ensured during parsing
            return Unique(self._utc_offsets[-1])

    def meta_for_instant(self, t: EpochSecs) -> tuple[int, str]:
        """Get time zone metadata (dst_saving_secs, abbreviation)
        at the given exact time."""
        idx = _bisect_right(self._utc_epochs, t)
        if idx < len(self._utc_epochs):
            saving, _, abbrev = self._meta_by_utc[max(0, idx - 1)]
            return saving, abbrev

        # After last transition: try POSIX TZ string, then fall back
        if self._end is not None and t >= self._footer_from:
            return self._end.meta_for_instant(t)
        else:
            assert self._meta_by_utc  # ensured during parsing
            saving, _, abbrev = self._meta_by_utc[-1]
            return saving, abbrev

    def next_transition(self, t: EpochSecs) -> tuple[EpochSecs, Offset] | None:
        """Get the (epoch, new_offset) of the next transition record
        strictly after `t`, or None if there is no next transition."""
        idx = _bisect_right(self._utc_epochs, t)
        if idx < len(self._utc_epochs):
            return (self._utc_epochs[idx], self._utc_offsets[idx])
        if self._end is not None:
            # The first transition of the POSIX TZ string that counts is the
            # one at `_footer_from`.
            return self._end.next_transition(max(t, self._footer_from - 1))
        return None

    def prev_transition(self, t: EpochSecs) -> tuple[EpochSecs, Offset] | None:
        """Get the (epoch, new_offset) of the previous transition record
        strictly before `t`, or None if there is no previous transition."""
        # If past all recorded transitions, check POSIX first
        if self._end is not None and (
            not self._utc_epochs or t > self._utc_epochs[-1]
        ):
            result = self._end.prev_transition(t)
            if result is not None and result[0] >= self._footer_from:
                return result
        # Search recorded transitions: last one strictly < t.
        # Skip index 0 which is the sentinel initial offset, not a real transition.
        idx = _bisect_left(self._utc_epochs, t) - 1
        if idx >= 1:
            return (self._utc_epochs[idx], self._utc_offsets[idx])
        return None

    # NOTE: this equality check needs to be fast, since it's used in
    # some routines to check if the time zone is indeed changing.
    def __eq__(self, other: object) -> bool:
        # We first check for identity, as that's the cheapest check
        # and makes the common case fast.
        if self is other:
            return True
        # Identity inequality doesn't rule out equality, as two different
        # instances may represent the same time zone due to cache clearing.
        elif type(other) is TimeZone:
            return (
                # We compare the key first, as it's the cheapest to compare,
                # and most likely to differ
                self.key == other.key
                # Only in rare cases (i.e. system time zone changes or cache clears)
                # should we need to compare the rest of the data. It's relatively
                # expensive, so we do it last.
                and self._utc_epochs == other._utc_epochs
                and self._utc_offsets == other._utc_offsets
                and self._local_epochs == other._local_epochs
                and self._local_values == other._local_values
                and self._end == other._end
                and self._footer_from == other._footer_from
                and self._footer_local_from == other._footer_local_from
                and self._meta_by_utc == other._meta_by_utc
                and self._abbrev_data == other._abbrev_data
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
            _footer_from=EPOCH_SECS_MIN,
            _footer_local_from=EPOCH_SECS_MIN,
            _meta_by_utc=(),
            _abbrev_data=b"",
        )

    @classmethod
    def parse_tzif(cls, data: bytes, key: str | None = None) -> TimeZone:
        """Create a TimeZone from TZif file data"""
        read = BytesIO(data)
        try:
            header = _parse_header(read)
            return _parse_content(header, read, key)
        # A corrupt file fails in many ways; callers get one
        except (struct.error, LookupError, OverflowError, UnicodeError):
            raise ValueError("Invalid TZif data") from None


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


def _read_exact(data: IO[bytes], n: int) -> bytes:
    # read() returns what is left of a truncated file without complaint
    result = data.read(n)
    if len(result) != n:
        raise ValueError("Unexpected end of TZif data")
    return result


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

    return Header(version, *struct.unpack(">6I", data.read(24)))


# Pre-compute POSIX DST transitions up to this year so the bisect fast-path
# is used for all common date operations without falling back to the slow
# Python-level POSIX rule evaluation.
_PRECALC_UNTIL = 2050


def _extend_with_posix(
    offsets: MutableSequence[tuple[EpochSecs, Offset]],
    meta: MutableSequence[TransitionMeta],
    end: TzStr,
    footer_from: EpochSecs,
) -> None:
    """Append the transitions of the POSIX TZ rule to *offsets* and *meta*,
    from ``footer_from`` up to ``_PRECALC_UNTIL`` inclusive."""
    t = footer_from - 1
    while (nxt := end.next_transition(t)) is not None and (
        year_for_epoch(nxt[0]) <= _PRECALC_UNTIL
    ):
        t = nxt[0]
        offsets.append(nxt)
        saving, abbrev = end.meta_for_instant(t)
        meta.append((saving, None, abbrev))


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

    offset_indices = list(_read_exact(data, header.timecnt))
    types = _parse_type_info(header.typecnt, data)
    abbrev_data = _read_exact(data, header.charcnt)
    # RFC 8536 has abbreviations in ASCII
    if not abbrev_data.isascii():
        raise ValueError("Invalid TZif data")

    offsets_by_utc, meta_by_utc = _load_transitions(
        transition_times, types, offset_indices, abbrev_data
    )

    # Parse POSIX TZ string for v2+ files
    end = None
    if header.version < 2:
        # The unused metadata ends the file, and a truncated file is corrupt
        _read_exact(
            data, header.isutcnt + header.isstdcnt + header.leapcnt * 8
        )
    else:
        # Skip unused metadata and newline before tz string
        _read_exact(
            data, header.isutcnt + header.isstdcnt + header.leapcnt * 12 + 1
        )
        # Find the TZ string (until newline or end of data).
        # RFC 8536 allows an empty one: then there is none.
        tz_string, *_ = data.read().split(b"\n", 1)

        if tz_string:
            end = TzStr.parse(tz_string.decode("ascii"))

    # DST records with no standard record after them pair with the standard
    # offset of the POSIX TZ string, the next one to come (Indiana/Winamac
    # moved from Central standard time to Eastern DST in 2007).
    if end is not None:
        i = len(meta_by_utc) - 1
        # The entry before the first record has no DST saving
        while meta_by_utc[i][0]:
            if footer_saving := offsets_by_utc[i][1] - end.std:
                _, abbrind, abbrev = meta_by_utc[i]
                meta_by_utc[i] = (footer_saving, abbrind, abbrev)
            i -= 1

    # The last record, even one that changes nothing, marks where the POSIX
    # TZ string takes over (RFC 8536 section 3.3). Without records, it
    # governs the whole range.
    footer_from = footer_local_from = EPOCH_SECS_MIN
    if end is not None and transition_times:
        last = transition_times[-1]
        last_offset = offsets_by_utc[-1][1]
        # RFC 8536 section 3.3: the POSIX TZ string agrees with the last record
        if end.offset_for_instant(last) != last_offset:
            raise ValueError("Invalid TZif data")
        if (nxt := end.next_transition(last)) is not None:
            footer_from, offset = nxt
            footer_local_from = clamp_epoch_secs(
                footer_from + min(offset, last_offset)
            )
        else:
            footer_from = last
            footer_local_from = clamp_epoch_secs(last + last_offset)
        # Pre-compute transitions from POSIX rule up to a fixed horizon.
        # This ensures the fast bisect path is used for common date ranges,
        # avoiding repeated Python-level DST boundary calculations.
        _extend_with_posix(offsets_by_utc, meta_by_utc, end, footer_from)

    local_transitions = _local_transitions(offsets_by_utc)
    return TimeZone(
        key=key,
        _utc_epochs=tuple(t for t, _ in offsets_by_utc),
        _utc_offsets=tuple(v for _, v in offsets_by_utc),
        _local_epochs=tuple(t for t, _ in local_transitions),
        _local_values=tuple(v for _, v in local_transitions),
        _end=end,
        _footer_from=footer_from,
        _footer_local_from=footer_local_from,
        _meta_by_utc=tuple(meta_by_utc),
        _abbrev_data=abbrev_data,
    )


def _parse_v2_transitions(
    header: Header, data: IO[bytes]
) -> Sequence[EpochSecs]:
    times = struct.unpack(f">{header.timecnt}q", data.read(8 * header.timecnt))
    return list(map(clamp_epoch_secs, _ascending(times)))


def _parse_v1_transitions(
    header: Header, data: IO[bytes]
) -> Sequence[EpochSecs]:
    return _ascending(
        struct.unpack(f">{header.timecnt}i", data.read(4 * header.timecnt))
    )


def _ascending(times: tuple[int, ...]) -> tuple[int, ...]:
    # RFC 8536 requires ascending times
    if any(a >= b for a, b in zip(times, times[1:])):
        raise ValueError("Invalid TZif data")
    return times


def _parse_type_info(
    typecnt: int, data: IO[bytes]
) -> Sequence[tuple[Offset, bool, int]]:
    """Parse type info records: (utoff, isdst, abbrind)"""
    # A transition names its type by one byte
    if not 0 < typecnt <= 256:
        raise ValueError("Invalid type count")
    types = [
        (utoff, isdst != 0, abbrind)
        for utoff, isdst, abbrind in struct.iter_unpack(
            ">iBB", _read_exact(data, 6 * typecnt)
        )
    ]
    if any(abs(utoff) >= MAX_OFFSET for utoff, _, _ in types):
        raise ValueError("Offset out of range")
    return types


def _abbrev_at(abbrev_data: bytes, idx: int) -> str:
    """Extract a NUL-terminated abbreviation string at the given index."""
    try:
        end = abbrev_data.index(b"\x00", idx)
    except ValueError:  # pragma: no cover
        end = len(abbrev_data)
    return abbrev_data[idx:end].decode("ascii")


def _load_transitions(
    transition_times: Sequence[EpochSecs],
    types: Sequence[tuple[Offset, bool, int]],
    indices: Sequence[int],
    abbrev_data: bytes,
) -> tuple[
    MutableSequence[tuple[EpochSecs, Offset]],
    MutableSequence[TransitionMeta],
]:
    """Load transitions and metadata from parsed data.

    A record whose type repeats the previous record's changes nothing
    observable, so it is dropped: a transition is a change of the offset,
    the DST saving, or the abbreviation.
    """
    prev_type = types[0]
    first_utoff, _, first_abbrind = prev_type

    # Pre-seed last_std_offset from the first non-DST type in actual transitions.
    # This ensures correct DST saving computation when the very first transitions
    # are DST (e.g. America/Iqaluit, Antarctica/Palmer), where types[0] is the
    # pre-standard LMT type and not the relevant standard offset.
    last_std_offset = next(
        (types[idx][0] for idx in indices if not types[idx][1]),
        first_utoff,
    )

    offsets: list[tuple[EpochSecs, Offset]] = [
        (EPOCH_SECS_MIN, first_utoff),
    ]
    meta: list[TransitionMeta] = [
        (0, first_abbrind, _abbrev_at(abbrev_data, first_abbrind)),
    ]

    for i, (idx, epoch) in enumerate(zip(indices, transition_times)):
        if types[idx] == prev_type:
            continue
        follows_dst = prev_type[1]
        prev_type = utoff, isdst, abbrind = types[idx]
        prev_epoch, prev_offset = offsets[-1]
        # Real data changes by 24 hours at most (Alaska in 1867), which
        # lets a day's bounds lie at most one day away. A gap or fold that
        # overlaps the previous one maps local times to an offset its
        # instant doesn't have.
        if abs(utoff - prev_offset) > 86_400 or (
            len(offsets) > 1
            and epoch + min(utoff, prev_offset)
            < prev_epoch + max(offsets[-2][1], prev_offset)
        ):
            raise ValueError("Invalid TZif data")
        offsets.append((epoch, utoff))

        if not isdst:
            dst_saving = 0
            last_std_offset = utoff
        elif (
            follows_dst
            and i + 1 < len(indices)
            and not (next_type := types[indices[i + 1]])[1]
            and next_type[0] != utoff
        ):
            # One DST type straight after another (Pacific/Apia crossing the
            # date line): pair it with the standard type that follows it
            # directly, as CPython does.
            dst_saving = utoff - next_type[0]
        elif utoff == last_std_offset:
            # Standard time moved and DST began at the same moment, so the
            # saving cannot be read off the previous standard offset.
            dst_saving = 3600
        else:
            dst_saving = utoff - last_std_offset

        meta.append((dst_saving, abbrind, _abbrev_at(abbrev_data, abbrind)))

    return offsets, meta


# See the TimeZone class definition for explanation of these data structures
def _local_transitions(
    transitions: Sequence[tuple[EpochSecs, Offset]],
) -> Sequence[tuple[EpochSecs, tuple[Offset, OffsetDelta]]]:
    result: list[tuple[EpochSecs, tuple[Offset, OffsetDelta]]] = []
    assert transitions  # we've ensured there's at least one transition

    (_, offset_prev), *remaining = transitions
    # `_load_transitions` has rejected overlapping gaps and folds among the
    # records, so their local times ascend
    for epoch, offset in remaining:
        local_time = epoch + max(offset_prev, offset)
        # Saturating add to be consistent with Rust version
        local_time = max(EPOCH_SECS_MIN, min(EPOCH_SECS_MAX, local_time))

        result.append((local_time, (offset_prev, offset - offset_prev)))
        offset_prev = offset

    return result
