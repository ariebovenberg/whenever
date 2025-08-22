"""Parsing of TZif files

This module is largely a port the Rust equivalent, so there might be some
unpythonic edges.
"""

from __future__ import annotations

import struct
from typing import Optional, Sequence, final

from .common import Ambiguity, Fold, Gap, Unambiguous
from .posix import TzStr

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
    """

    __slots__ = (
        "__weakref__",
        "key",
        "_offsets_by_utc",
        "_offsets_by_local",
        "_end",
    )

    # The IANA tz ID (e.g. "Europe/Amsterdam"). Not actually parsed from the file,
    # but essential because in our case we always associate a tzif file with a tz ID.
    key: Optional[str]

    # The following two fields are used to map UTC time to local time and vice versa.
    # For UTC -> local, the transition is unambiguous and simple.
    # Read Sequence[(X, Y)] as "FROM time X onwards (expressed in epoch seconds) the offset is Y".
    _offsets_by_utc: tuple[tuple[EpochSecs, Offset], ...]

    # For local -> UTC, the transition may be ambiguous and therefore requires extra information.
    # Read Sequence[(X, (Y, Z))] as "UNTIL time X (expressed in local epoch seconds) the offset is Y.
    # At this point it shifts by Z.
    _offsets_by_local: tuple[tuple[EpochSecs, tuple[Offset, OffsetDelta]], ...]

    # Invariant: if posix TZ isn't given, there must be at least one entry in each of the above
    # vectors.
    _end: Optional[TzStr]

    def __init__(
        self,
        key: Optional[str],
        _offsets_by_utc: tuple[tuple[EpochSecs, Offset], ...],
        _offsets_by_local: tuple[
            tuple[EpochSecs, tuple[Offset, OffsetDelta]], ...
        ],
        _end: Optional[TzStr] = None,
    ):
        self.key = key
        self._offsets_by_utc = _offsets_by_utc
        self._offsets_by_local = _offsets_by_local
        self._end = _end

    def offset_for_instant(self, t: EpochSecs) -> Offset:
        """Get the UTC offset at the given exact time"""
        idx = bisect(self._offsets_by_utc, t)
        if idx is not None:
            return self._offsets_by_utc[max(0, idx - 1)][1]

        # If the time is after the last transition, use the POSIX TZ string
        if self._end is not None:
            return self._end.offset_for_instant(t)
        # If there's no POSIX TZ string, use the last offset.
        # There's not much else we can do.
        elif self._offsets_by_utc:
            return self._offsets_by_utc[-1][1]
        raise ValueError("No offset data available")

    def ambiguity_for_local(self, t: EpochSecs) -> Ambiguity:
        """Get the UTC offset at the given local time (expressed in epoch seconds)"""
        idx = bisect(self._offsets_by_local, t)
        if idx is not None:
            next_transition, (offset, change) = self._offsets_by_local[idx]
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
        if self._offsets_by_local:
            _, (offset, _) = self._offsets_by_local[-1]
            return Unambiguous(offset)

        raise ValueError("No offset data available")

    def __eq__(self, other: object) -> bool:
        if type(other) is TimeZone:
            return (
                self.key == other.key
                and self._offsets_by_utc == other._offsets_by_utc
                and self._offsets_by_local == other._offsets_by_local
                and self._end == other._end
            )
        return NotImplemented

    @classmethod
    def parse_posix(cls, s: str) -> TimeZone:
        """Create a TimeZone from a POSIX TZ string"""
        return TimeZone(
            key=None,
            _offsets_by_utc=(),
            _offsets_by_local=(),
            _end=TzStr.parse(s),
        )

    @classmethod
    def parse_tzif(cls, data: bytes, key: Optional[str] = None) -> TimeZone:
        """Create a TimeZone from TZif file data"""
        offset = 0
        header, offset = _parse_header(data, offset)
        return _parse_content(header, data, offset, key)


def bisect(
    arr: Sequence[tuple[EpochSecs, object]], x: EpochSecs
) -> Optional[int]:
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


# TODO: use IO reader instead of offset tracking
def _parse_header(data: bytes, offset: int) -> tuple[Header, int]:
    """Parse TZif header and return header with new offset"""
    # Check magic bytes
    if data[offset : offset + 4] != b"TZif":
        raise ValueError("Invalid header value")
    offset += 4

    # Parse version
    version_byte = data[offset : offset + 1]
    if version_byte == b"\x00":
        version = 1
    elif version_byte.isdigit():
        version = int(version_byte)
    else:
        raise ValueError("Invalid header value")
    offset += 1

    # Skip reserved bytes
    offset += 15

    # Parse header fields
    header_data = data[offset : offset + 24]
    offset += 24

    header = Header(
        version=version,
        isutcnt=struct.unpack(">i", header_data[0:4])[0],
        isstdcnt=struct.unpack(">i", header_data[4:8])[0],
        leapcnt=struct.unpack(">i", header_data[8:12])[0],
        timecnt=struct.unpack(">i", header_data[12:16])[0],
        typecnt=struct.unpack(">i", header_data[16:20])[0],
        charcnt=struct.unpack(">i", header_data[20:24])[0],
    )

    return header, offset


def _parse_content(
    header: Header, data: bytes, offset: int, key: Optional[str]
) -> TimeZone:
    """Parse the content section of a TZif file"""
    # Handle version 2+ files
    if header.version >= 2:
        # Skip v1 data section
        v1_size = (
            header.timecnt * 5
            + header.typecnt * 6
            + header.charcnt
            + header.leapcnt * 8
            + header.isstdcnt
            + header.isutcnt
        )
        offset += v1_size

        # Parse second header
        header, offset = _parse_header(data, offset)

        # Parse v2 transitions (64-bit)
        transition_times = _parse_v2_transitions(header, data, offset)
        offset += header.timecnt * 8
    else:
        # Parse v1 transitions (32-bit)
        transition_times = _parse_v1_transitions(header, data, offset)
        offset += header.timecnt * 4

    offset_indices = []
    for i in range(header.timecnt):
        offset_indices.append(data[offset + i])
    offset += header.timecnt

    offsets = _parse_offsets(header.typecnt, data, offset)
    offset += header.typecnt * 6 + header.charcnt

    offsets_by_utc = _load_transitions(
        transition_times, offsets, offset_indices
    )

    # Parse POSIX TZ string for v2+ files
    end = None
    if header.version >= 2:
        # Skip unused metadata and newline before tz string
        skip_size = header.isutcnt + header.isstdcnt + header.leapcnt * 12 + 1
        offset += skip_size

        # Find the TZ string (until newline or end of data)
        tz_start = offset
        tz_end = tz_start
        while tz_end < len(data) and data[tz_end : tz_end + 1] != b"\n":
            tz_end += 1

        if tz_end > tz_start:
            tz_string = data[tz_start:tz_end]
            end = TzStr.parse(tz_string.decode("ascii"))

    if end is None and not offsets_by_utc:
        # There doesn't seem to be any transition data in the file!
        raise ValueError("Invalid or corrupted data")

    return TimeZone(
        key=key,
        _offsets_by_utc=tuple(offsets_by_utc),
        _offsets_by_local=tuple(_local_transitions(offsets_by_utc)),
        _end=end,
    )


def _parse_v2_transitions(
    header: Header, data: bytes, offset: int
) -> Sequence[EpochSecs]:
    result = []
    for i in range(header.timecnt):
        start_idx = offset + i * 8
        end_idx = start_idx + 8
        value = struct.unpack(">q", data[start_idx:end_idx])[0]
        # Clamp values that are out of range
        result.append(clamp_epoch_secs(value))

    return result


def _parse_v1_transitions(
    header: Header, data: bytes, offset: int
) -> Sequence[EpochSecs]:
    """Parse 32-bit transition times"""
    result = []
    for i in range(header.timecnt):
        start_idx = offset + i * 4
        end_idx = start_idx + 4
        value = struct.unpack(">i", data[start_idx:end_idx])[0]
        result.append(value)

    return result


def _parse_offsets(typecnt: int, data: bytes, offset: int) -> Sequence[Offset]:
    result = []
    for i in range(typecnt):
        start_idx = offset + i * 6
        end_idx = start_idx + 4  # Only first 4 bytes are the offset
        offset_value = struct.unpack(">i", data[start_idx:end_idx])[0]
        result.append(offset_value)

    return result


def _load_transitions(
    transition_times: Sequence[EpochSecs],
    offsets: Sequence[Offset],
    indices: Sequence[int],
) -> Sequence[tuple[EpochSecs, Offset]]:
    """Load transitions from parsed data"""
    return [
        (epoch, offsets[idx]) for idx, epoch in zip(indices, transition_times)
    ]


def _local_transitions(
    transitions: Sequence[tuple[EpochSecs, Offset]],
) -> Sequence[tuple[EpochSecs, tuple[Offset, OffsetDelta]]]:
    """Convert UTC transitions to local transitions"""
    result = []
    if not transitions:
        return result

    _, offset_prev = transitions[0]
    for epoch, offset in transitions[1:]:
        # NOTE: we don't check for "impossible" gaps or folds
        local_time = epoch + max(offset_prev, offset)
        # Saturating add to be consistent with Rust version
        local_time = max(EPOCH_SECS_MIN, min(EPOCH_SECS_MAX, local_time))

        result.append((local_time, (offset_prev, offset - offset_prev)))
        offset_prev = offset

    return result
