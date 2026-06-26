# NOTE: these tests are mostly a port of the rust equivalent tests,
# so expect some unpythonic code.

import os
from datetime import datetime, timezone
from pathlib import Path

import pytest
from whenever._tz.common import Fold, Gap, Unambiguous
from whenever._tz.posix import TzStr
from whenever._tz.tzif import (
    EPOCH_SECS_MAX,
    EPOCH_SECS_MIN,
    TimeZone,
    bisect,
)

TZIF_DIR = Path(__file__).parent / "tzif"
UTC_EPOCH = datetime(1970, 1, 1, tzinfo=timezone.utc)


def ymdhms(
    year: int,
    month: int,
    day: int,
    hour: int = 0,
    minute: int = 0,
    second: int = 0,
) -> int:
    value = datetime(
        year, month, day, hour, minute, second, tzinfo=timezone.utc
    )
    return int((value - UTC_EPOCH).total_seconds())


def hhmm(hours: int, minutes: int = 0) -> int:
    assert 0 <= minutes < 60
    return hms(hours, minutes, 0)


def hms(hours: int, minutes: int, seconds: int) -> int:
    assert 0 <= minutes < 60
    assert 0 <= seconds < 60
    sign = -1 if hours < 0 else 1
    return hours * 3600 + sign * (minutes * 60 + seconds)


class TestBasicParsing:
    """Test basic parsing functionality"""

    def test_no_magic_header(self):
        """Test invalid headers"""
        # empty
        with pytest.raises(ValueError, match="Invalid header value"):
            TimeZone.parse_tzif(b"")

        # too small
        with pytest.raises(ValueError, match="Invalid header value"):
            TimeZone.parse_tzif(b"TZi")

        # wrong magic value
        with pytest.raises(ValueError, match="Invalid header value"):
            TimeZone.parse_tzif(b"this-is-not-tzif-file")

    def test_binary_search(self):
        """Test binary search functionality"""
        arr = [(4, 10), (9, 20), (12, 30), (16, 40), (24, 50)]

        # middle of the array
        assert bisect(arr, 10) == 2
        assert bisect(arr, 12) == 3
        assert bisect(arr, 15) == 3
        assert bisect(arr, 16) == 4

        # end of the array
        assert bisect(arr, 24) is None
        assert bisect(arr, 30) is None

        # start of the array
        assert bisect(arr, -99) == 0
        assert bisect(arr, 3) == 0
        assert bisect(arr, 4) == 1
        assert bisect(arr, 5) == 1

        # empty case
        assert bisect([], 25) is None


AMS = TimeZone.parse_tzif((TZIF_DIR / "Amsterdam.tzif").read_bytes())


class TestTZifFiles:
    """Test parsing of actual TZif files"""

    def test_posix_extension_includes_remainder_of_last_explicit_year(self):
        test_file = TZIF_DIR / "Lord_Howe.tzif"
        tzif = TimeZone.parse_tzif(test_file.read_bytes())

        # The final explicit transition ends DST in April 2008. The POSIX tail
        # starts it again in October of that same year.
        assert tzif.offset_for_instant(ymdhms(2008, 12, 1)) == hhmm(11)

    def test_utc(self):
        """Test UTC timezone file"""
        test_file = TZIF_DIR / "UTC.tzif"
        tzif = TimeZone.parse_tzif(test_file.read_bytes())
        assert tzif._utc_epochs == (EPOCH_SECS_MIN,)
        assert tzif._utc_offsets == (0,)
        assert tzif._end == TzStr.parse("UTC0")

        assert tzif.offset_for_instant(2216250001) == 0
        assert tzif.ambiguity_for_local(2216250000) == Unambiguous(0)

    def test_fixed(self):
        """Test fixed offset timezone file"""
        test_file = TZIF_DIR / "GMT-13.tzif"
        tzif = TimeZone.parse_tzif(test_file.read_bytes())
        assert tzif._utc_epochs == (EPOCH_SECS_MIN,)
        assert tzif._utc_offsets == (13 * 3600,)
        assert tzif._end == TzStr.parse("<+13>-13")

        assert tzif.offset_for_instant(2216250001) == 13 * 3600
        assert tzif.ambiguity_for_local(2216250000) == Unambiguous(13 * 3600)

    def test_v1(self):
        """Test version 1 TZif file"""
        test_file = TZIF_DIR / "Paris_v1.tzif"

        tzif = TimeZone.parse_tzif(test_file.read_bytes())
        assert len(tzif._utc_epochs) > 0
        assert tzif._end is None

        # a timestamp out of the range of the file should return the last offset (best guess)
        assert tzif.offset_for_instant(3_155_760_000) == 3600
        assert tzif.ambiguity_for_local(4_000_000_000) == Unambiguous(3600)
        # meta_for_instant after last transition with no POSIX string: falls back to last entry
        assert tzif.meta_for_instant(4_000_000_000) == (0, "CET")

    def test_clamp_transitions_to_range(self):
        """Test clamping of out-of-range transitions"""
        test_file = TZIF_DIR / "Sydney_widerange.tzif"
        tzif = TimeZone.parse_tzif(test_file.read_bytes())
        assert len(tzif._utc_epochs) > 0
        assert tzif.offset_for_instant(EPOCH_SECS_MIN) == 36292
        # don't take the absolute extreme, since this causes exceptions
        # in Python's datetime module.
        assert tzif.offset_for_instant(EPOCH_SECS_MAX - 50_000) == 39600

    def test_implicit_initial_offset(self):
        """Test handling implicit initial offset from TZif file"""
        test_file = TZIF_DIR / "Honolulu.tzif"

        tzif = TimeZone.parse_tzif(test_file.read_bytes())
        assert tzif.offset_for_instant(-3_000_000_000) == -37886

    def test_last_transition_is_gap(self):
        """Test handling of gap at last transition"""
        test_file = TZIF_DIR / "Honolulu.tzif"

        tzif = TimeZone.parse_tzif(test_file.read_bytes())
        assert tzif._end == TzStr.parse("HST10")
        assert tzif.offset_for_instant(-712150201) == -37800
        assert tzif.offset_for_instant(-712150200) == -36000

        # Just before the last gap
        assert tzif.ambiguity_for_local(-712150201 - 37800) == Unambiguous(
            -37800
        )

        # Start of the gap
        assert tzif.ambiguity_for_local(-712150200 - 37800) == Gap(
            -36000, -37800
        )

        # Just before end of gap
        assert tzif.ambiguity_for_local(-712150200 - 37800 + 1800 - 1) == Gap(
            -36000, -37800
        )

        # End of gap
        assert tzif.ambiguity_for_local(
            -712150200 - 37800 + 1800
        ) == Unambiguous(-36000)

        # After the gap
        assert tzif.ambiguity_for_local(-712150200) == Unambiguous(-36000)

    @pytest.mark.parametrize(
        "t, expected",
        [
            # before the entire range
            (ymdhms(1879, 9, 8, 21, 20), hms(0, 17, 30)),
            # at start of range
            (ymdhms(1879, 12, 31, 23, 42, 29), hms(0, 17, 30)),
            (ymdhms(1879, 12, 31, 23, 42, 30), hms(0, 17, 30)),
            (ymdhms(1879, 12, 31, 23, 42, 31), hms(0, 17, 30)),
            # The first transition
            (ymdhms(1892, 4, 30, 23, 59, 59), hms(0, 17, 30)),
            (ymdhms(1892, 5, 1), hhmm(0)),
            (ymdhms(1892, 5, 1, 0, 0, 1), hhmm(0)),
            # Arbitrary transition (fold)
            (ymdhms(2023, 10, 29, 0, 59, 59), hhmm(2)),
            (ymdhms(2023, 10, 29, 1), hhmm(1)),
            (ymdhms(2023, 10, 29, 1, 0, 1), hhmm(1)),
            # Arbitrary transition (gap)
            (ymdhms(2025, 3, 30, 0, 59, 59), hhmm(1)),
            (ymdhms(2025, 3, 30, 1), hhmm(2)),
            (ymdhms(2025, 3, 30, 1, 0, 1), hhmm(2)),
            # Transitions after the last explicit one need to use the POSIX TZ string
            (ymdhms(2040, 3, 25, 0, 59, 59), hhmm(1)),
            (ymdhms(2040, 3, 25, 1), hhmm(2)),
            (ymdhms(2040, 3, 25, 1, 0, 1), hhmm(2)),
            (ymdhms(2053, 10, 26, 0, 59, 59), hhmm(2)),
            (ymdhms(2053, 10, 26, 1), hhmm(1)),
            (ymdhms(2053, 10, 26, 1, 0, 1), hhmm(1)),
        ],
    )
    def test_offset_for_instant(self, t, expected):
        """Test comprehensive example with Amsterdam timezone"""
        assert AMS.offset_for_instant(t) == expected

    @pytest.mark.parametrize(
        "t, expected",
        [
            # before the entire range
            (
                ymdhms(1879, 9, 8, 21, 37, 30),
                Unambiguous(hms(0, 17, 30)),
            ),
            # At the start of the range
            (
                ymdhms(1879, 12, 31, 23, 59, 59),
                Unambiguous(hms(0, 17, 30)),
            ),
            (ymdhms(1880, 1, 1), Unambiguous(hms(0, 17, 30))),
            (
                ymdhms(1880, 1, 1, 0, 0, 1),
                Unambiguous(hms(0, 17, 30)),
            ),
            # --- The first transition (a fold) ---
            # well before the fold (no ambiguity)
            (
                ymdhms(1882, 10, 28, 17, 49, 11),
                Unambiguous(hms(0, 17, 30)),
            ),
            # Just before times become ambiguous
            (
                ymdhms(1892, 4, 30, 23, 59, 59),
                Unambiguous(hms(0, 17, 30)),
            ),
            # At the moment times becomes ambiguous
            (
                ymdhms(1892, 5, 1),
                Fold(hms(0, 17, 30), hhmm(0)),
            ),
            # Short before the clock change, short enough for ambiguity!
            (
                ymdhms(1892, 5, 1, 0, 5, 48),
                Fold(hms(0, 17, 30), hhmm(0)),
            ),
            # A second before the clock change (ambiguity!)
            (
                ymdhms(1892, 5, 1, 0, 17, 29),
                Fold(hms(0, 17, 30), hhmm(0)),
            ),
            # At the exact clock change (no ambiguity)
            (ymdhms(1892, 5, 1, 0, 17, 30), Unambiguous(hhmm(0))),
            # Directly after the clock change (no ambiguity)
            (ymdhms(1892, 5, 1, 0, 17, 31), Unambiguous(hhmm(0))),
            # --- A "gap" transition ---
            # Well before the transition
            (ymdhms(1916, 3, 3, 1, 6, 40), Unambiguous(hhmm(1))),
            # Just before the clock change
            (ymdhms(1916, 4, 30, 23, 59, 59), Unambiguous(hhmm(1))),
            # At the exact clock change (ambiguity!)
            (ymdhms(1916, 5, 1), Gap(hhmm(2), hhmm(1))),
            # Right after the clock change (ambiguity)
            (ymdhms(1916, 5, 1, 0, 0, 7), Gap(hhmm(2), hhmm(1))),
            # Slightly before the gap ends (ambiguity)
            (ymdhms(1916, 5, 1, 0, 59, 59), Gap(hhmm(2), hhmm(1))),
            # The gap ends (no ambiguity)
            (ymdhms(1916, 5, 1, 1), Unambiguous(hhmm(2))),
            # A sample of other times
            (ymdhms(1992, 3, 12, 8, 5), Unambiguous(hhmm(1))),
            (ymdhms(1992, 3, 29, 2, 5), Gap(hhmm(2), hhmm(1))),
            (ymdhms(1992, 8, 31, 23, 5), Unambiguous(hhmm(2))),
            # ---- Transitions after the last explicit one need to use the POSIX TZ string
            # before gap
            (ymdhms(2040, 3, 25, 1, 59, 59), Unambiguous(hhmm(1))),
            # gap starts
            (ymdhms(2040, 3, 25, 2), Gap(hhmm(2), hhmm(1))),
            # gap ends
            (ymdhms(2040, 3, 25, 3), Unambiguous(hhmm(2))),
            # somewhere in summer
            (ymdhms(2040, 3, 25, 12, 6, 40), Unambiguous(hhmm(2))),
            # Fold starts
            (ymdhms(2053, 10, 26, 2), Fold(hhmm(2), hhmm(1))),
            # In the fold
            (ymdhms(2053, 10, 26, 2, 2, 20), Fold(hhmm(2), hhmm(1))),
            # end of the fold
            (ymdhms(2053, 10, 26, 3), Unambiguous(hhmm(1))),
        ],
    )
    def test_ambiguity_for_local(self, t, expected):
        assert AMS.ambiguity_for_local(t) == expected


def test_smoke():
    """Test parsing various TZif files without crashing"""
    tzdir = "/usr/share/zoneinfo"

    for root, _, files in os.walk(tzdir):
        # Special directories we should ignore
        if "right/" in root or "posix/" in root:
            continue

        for file in files:
            path = os.path.join(root, file)

            # Skip unreadable files
            try:
                with open(path, "rb") as f:
                    data = f.read()
            except (PermissionError, IsADirectoryError):
                continue

            # Skip non-TZif files
            if not data.startswith(b"TZif"):
                continue

            assert TimeZone.parse_tzif(data) is not None
