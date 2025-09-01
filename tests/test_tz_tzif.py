# NOTE: these tests are mostly a port of the rust equivalent tests,
# so expect some unpythonic code.

import os
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

    def test_utc(self):
        """Test UTC timezone file"""
        test_file = TZIF_DIR / "UTC.tzif"
        tzif = TimeZone.parse_tzif(test_file.read_bytes())
        assert tzif._offsets_by_utc == ()
        assert tzif._end == TzStr.parse("UTC0")

        assert tzif.offset_for_instant(2216250001) == 0
        assert tzif.ambiguity_for_local(2216250000) == Unambiguous(0)

    def test_fixed(self):
        """Test fixed offset timezone file"""
        test_file = TZIF_DIR / "GMT-13.tzif"
        tzif = TimeZone.parse_tzif(test_file.read_bytes())
        assert tzif._offsets_by_utc == ()
        assert tzif._end == TzStr.parse("<+13>-13")

        assert tzif.offset_for_instant(2216250001) == 13 * 3600
        assert tzif.ambiguity_for_local(2216250000) == Unambiguous(13 * 3600)

    def test_v1(self):
        """Test version 1 TZif file"""
        test_file = TZIF_DIR / "Paris_v1.tzif"

        tzif = TimeZone.parse_tzif(test_file.read_bytes())
        assert len(tzif._offsets_by_utc) > 0
        assert tzif._end is None

        # a timestamp out of the range of the file should return the last offset (best guess)
        assert tzif.offset_for_instant(3155760000) == 3600

    def test_clamp_transitions_to_range(self):
        """Test clamping of out-of-range transitions"""
        test_file = TZIF_DIR / "Sydney_widerange.tzif"
        tzif = TimeZone.parse_tzif(test_file.read_bytes())
        assert len(tzif._offsets_by_utc) > 0
        assert tzif.offset_for_instant(EPOCH_SECS_MIN) == 36292
        # don't take the absolute extreme, since this causes exceptions
        # in Python's datetime module.
        assert tzif.offset_for_instant(EPOCH_SECS_MAX - 50_000) == 39600

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
            (-2850000000, 1050),
            # at start of range
            (-2840141851, 1050),
            (-2840141850, 1050),
            (-2840141849, 1050),
            # The first transition
            (-2450995201, 1050),
            (-2450995200, 0),
            (-2450995199, 0),
            # Arbitrary transition (fold)
            (1698541199, 7200),
            (1698541200, 3600),
            (1698541201, 3600),
            # Arbitrary transition (gap)
            (1743296399, 3600),
            (1743296400, 7200),
            (1743296401, 7200),
            # Transitions after the last explicit one need to use the POSIX TZ string
            (2216249999, 3600),
            (2216250000, 7200),
            (2216250001, 7200),
            (2645053199, 7200),
            (2645053200, 3600),
            (2645053201, 3600),
        ],
    )
    def test_offset_for_instant(self, t, expected):
        """Test comprehensive example with Amsterdam timezone"""
        assert AMS.offset_for_instant(t) == expected

    @pytest.mark.parametrize(
        "t, expected",
        [
            # before the entire range
            (-2850000000 + 1050, Unambiguous(1050)),
            # At the start of the range
            (-2840141851 + 1050, Unambiguous(1050)),
            (-2840141850 + 1050, Unambiguous(1050)),
            (-2840141849 + 1050, Unambiguous(1050)),
            # --- The first transition (a fold) ---
            # well before the fold (no ambiguity)
            (-2750999299 + 1050, Unambiguous(1050)),
            # Just before times become ambiguous
            (-2450995201, Unambiguous(1050)),
            # At the moment times becomes ambiguous
            (-2450995200, Fold(1050, 0)),
            # Short before the clock change, short enough for ambiguity!
            (-2450995902 + 1050, Fold(1050, 0)),
            # A second before the clock change (ambiguity!)
            (-2450995201 + 1050, Fold(1050, 0)),
            # At the exact clock change (no ambiguity)
            (-2450995200 + 1050, Unambiguous(0)),
            # Directly after the clock change (no ambiguity)
            (-2450995199 + 1050, Unambiguous(0)),
            # --- A "gap" transition ---
            # Well before the transition
            (-1698792800, Unambiguous(3600)),
            # Just before the clock change
            (-1693702801 + 3600, Unambiguous(3600)),
            # At the exact clock change (ambiguity!)
            (-1693702800 + 3600, Gap(7200, 3600)),
            # Right after the clock change (ambiguity)
            (-1693702793 + 3600, Gap(7200, 3600)),
            # Slightly before the gap ends (ambiguity)
            (-1693702801 + 7200, Gap(7200, 3600)),
            # The gap ends (no ambiguity)
            (-1693702800 + 7200, Unambiguous(7200)),
            # A sample of other times
            (700387500, Unambiguous(3600)),
            (701834700, Gap(7200, 3600)),
            (715302300, Unambiguous(7200)),
            # ---- Transitions after the last explicit one need to use the POSIX TZ string
            # before gap
            (2216249999 + 3600, Unambiguous(3600)),
            # gap starts
            (2216250000 + 3600, Gap(7200, 3600)),
            # gap ends
            (2216250000 + 7200, Unambiguous(7200)),
            # somewhere in summer
            (2216290000, Unambiguous(7200)),
            # Fold starts
            (2645056800, Fold(7200, 3600)),
            # In the fold
            (2645056940, Fold(7200, 3600)),
            # end of the fold
            (2645056800 + 3600, Unambiguous(3600)),
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
