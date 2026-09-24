# NOTE: these tests are mostly a port of the rust equivalent tests,
# so expect some unpythonic code.

import os
import struct
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest
from whenever import (
    Instant,
    TimeDelta,
    TimeZoneNotFoundError,
    ZonedDateTime,
    hours,
)
from whenever._common import EPOCH_SECS_MAX, EPOCH_SECS_MIN
from whenever._tz.common import Fold, Gap, Unique
from whenever._tz.posix import TzStr
from whenever._tz.tzif import TimeZone, bisect

from .common import hhmm, tz_rules_from_file, ymdhms

TZIF_DIR = Path(__file__).parent / "tzif"
UTC_EPOCH = datetime(1970, 1, 1, tzinfo=timezone.utc)


def hms(hours: int, minutes: int, seconds: int) -> int:
    assert 0 <= minutes < 60
    assert 0 <= seconds < 60
    sign = -1 if hours < 0 else 1
    return hours * 3600 + sign * (minutes * 60 + seconds)


def ambiguity(tz: TimeZone, local_epoch: int):
    dt = (UTC_EPOCH + timedelta(seconds=local_epoch)).replace(tzinfo=None)
    return tz.ambiguity_for_local(dt)


def simple_tz(
    meta_by_utc: tuple[tuple[int, int | None, str], ...],
    abbrev_data: bytes,
) -> TimeZone:
    return TimeZone(
        key="Test/Zone",
        _utc_epochs=(EPOCH_SECS_MIN,),
        _utc_offsets=(0,),
        _local_epochs=(),
        _local_values=(),
        _end=None,
        _footer_from=EPOCH_SECS_MIN,
        _footer_local_from=EPOCH_SECS_MIN,
        _meta_by_utc=meta_by_utc,
        _abbrev_data=abbrev_data,
    )


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

    def test_equality_includes_raw_abbreviation_data(self):
        assert simple_tz(((0, 0, "UTC"),), b"UTC\0") == simple_tz(
            ((0, 0, "UTC"),), b"UTC\0"
        )
        assert simple_tz(((0, 0, "UTC"),), b"UTC\0") != simple_tz(
            ((0, 0, "UTC"),), b"UTC\0unused\0"
        )

    def test_equality_includes_raw_abbreviation_indices(self):
        assert simple_tz(((0, 0, "UTC"),), b"UTC\0UTC\0") != simple_tz(
            ((0, 4, "UTC"),), b"UTC\0UTC\0"
        )


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
        """Test UTC time zone file"""
        test_file = TZIF_DIR / "UTC.tzif"
        tzif = TimeZone.parse_tzif(test_file.read_bytes())
        assert tzif._utc_epochs == (EPOCH_SECS_MIN,)
        assert tzif._utc_offsets == (0,)
        assert tzif._end == TzStr.parse("UTC0")

        assert tzif.offset_for_instant(2216250001) == 0
        assert ambiguity(tzif, 2216250000) == Unique(0)

    def test_fixed(self):
        """Test fixed offset time zone file"""
        test_file = TZIF_DIR / "GMT-13.tzif"
        tzif = TimeZone.parse_tzif(test_file.read_bytes())
        assert tzif._utc_epochs == (EPOCH_SECS_MIN,)
        assert tzif._utc_offsets == (13 * 3600,)
        assert tzif._end == TzStr.parse("<+13>-13")

        assert tzif.offset_for_instant(2216250001) == 13 * 3600
        assert ambiguity(tzif, 2216250000) == Unique(13 * 3600)

    def test_v1(self):
        """Test version 1 TZif file"""
        test_file = TZIF_DIR / "Paris_v1.tzif"

        tzif = TimeZone.parse_tzif(test_file.read_bytes())
        assert len(tzif._utc_epochs) > 0
        assert tzif._end is None

        # a timestamp out of the range of the file should return the last offset (best guess)
        assert tzif.offset_for_instant(3_155_760_000) == 3600
        assert ambiguity(tzif, 4_000_000_000) == Unique(3600)
        # meta_for_instant after last transition with no POSIX string: falls back to last entry
        assert tzif.meta_for_instant(4_000_000_000) == (0, "CET")

    def test_v1_without_transitions(self):
        tzif = TimeZone.parse_tzif((TZIF_DIR / "Fixed_v1.tzif").read_bytes())
        assert tzif._end is None
        assert tzif.offset_for_instant(0) == 3600
        assert ambiguity(tzif, 0) == Unique(3600)
        assert tzif.meta_for_instant(0) == (0, "CET")

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
        assert ambiguity(tzif, -712150201 - 37800) == Unique(-37800)

        # Start of the gap
        assert ambiguity(tzif, -712150200 - 37800) == Gap(
            -712150200 - 37800 + 1800, -36000, -37800
        )

        # Just before end of gap
        assert ambiguity(tzif, -712150200 - 37800 + 1800 - 1) == Gap(
            -712150200 - 37800 + 1800, -36000, -37800
        )

        # End of gap
        assert ambiguity(tzif, -712150200 - 37800 + 1800) == Unique(-36000)

        # After the gap
        assert ambiguity(tzif, -712150200) == Unique(-36000)

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
        """Test comprehensive example with Amsterdam time zone"""
        assert AMS.offset_for_instant(t) == expected

    @pytest.mark.parametrize(
        "t, expected",
        [
            # before the entire range
            (
                ymdhms(1879, 9, 8, 21, 37, 30),
                Unique(hms(0, 17, 30)),
            ),
            # At the start of the range
            (
                ymdhms(1879, 12, 31, 23, 59, 59),
                Unique(hms(0, 17, 30)),
            ),
            (ymdhms(1880, 1, 1), Unique(hms(0, 17, 30))),
            (
                ymdhms(1880, 1, 1, 0, 0, 1),
                Unique(hms(0, 17, 30)),
            ),
            # --- The first transition (a fold) ---
            # well before the fold (no ambiguity)
            (
                ymdhms(1882, 10, 28, 17, 49, 11),
                Unique(hms(0, 17, 30)),
            ),
            # Just before times become ambiguous
            (
                ymdhms(1892, 4, 30, 23, 59, 59),
                Unique(hms(0, 17, 30)),
            ),
            # At the moment times becomes ambiguous
            (
                ymdhms(1892, 5, 1),
                Fold(
                    ymdhms(1892, 5, 1, 0, 17, 30),
                    hms(0, 17, 30),
                    hhmm(0),
                ),
            ),
            # Short before the clock change, short enough for ambiguity!
            (
                ymdhms(1892, 5, 1, 0, 5, 48),
                Fold(
                    ymdhms(1892, 5, 1, 0, 17, 30),
                    hms(0, 17, 30),
                    hhmm(0),
                ),
            ),
            # A second before the clock change (ambiguity!)
            (
                ymdhms(1892, 5, 1, 0, 17, 29),
                Fold(
                    ymdhms(1892, 5, 1, 0, 17, 30),
                    hms(0, 17, 30),
                    hhmm(0),
                ),
            ),
            # At the exact clock change (no ambiguity)
            (ymdhms(1892, 5, 1, 0, 17, 30), Unique(hhmm(0))),
            # Directly after the clock change (no ambiguity)
            (ymdhms(1892, 5, 1, 0, 17, 31), Unique(hhmm(0))),
            # --- A "gap" transition ---
            # Well before the transition
            (ymdhms(1916, 3, 3, 1, 6, 40), Unique(hhmm(1))),
            # Just before the clock change
            (ymdhms(1916, 4, 30, 23, 59, 59), Unique(hhmm(1))),
            # At the exact clock change (ambiguity!)
            (
                ymdhms(1916, 5, 1),
                Gap(ymdhms(1916, 5, 1, 1), hhmm(2), hhmm(1)),
            ),
            # Right after the clock change (ambiguity)
            (
                ymdhms(1916, 5, 1, 0, 0, 7),
                Gap(ymdhms(1916, 5, 1, 1), hhmm(2), hhmm(1)),
            ),
            # Slightly before the gap ends (ambiguity)
            (
                ymdhms(1916, 5, 1, 0, 59, 59),
                Gap(ymdhms(1916, 5, 1, 1), hhmm(2), hhmm(1)),
            ),
            # The gap ends (no ambiguity)
            (ymdhms(1916, 5, 1, 1), Unique(hhmm(2))),
            # A sample of other times
            (ymdhms(1992, 3, 12, 8, 5), Unique(hhmm(1))),
            (
                ymdhms(1992, 3, 29, 2, 5),
                Gap(ymdhms(1992, 3, 29, 3), hhmm(2), hhmm(1)),
            ),
            (ymdhms(1992, 8, 31, 23, 5), Unique(hhmm(2))),
            # ---- Transitions after the last explicit one need to use the POSIX TZ string
            # before gap
            (ymdhms(2040, 3, 25, 1, 59, 59), Unique(hhmm(1))),
            # gap starts
            (
                ymdhms(2040, 3, 25, 2),
                Gap(ymdhms(2040, 3, 25, 3), hhmm(2), hhmm(1)),
            ),
            # gap ends
            (ymdhms(2040, 3, 25, 3), Unique(hhmm(2))),
            # somewhere in summer
            (ymdhms(2040, 3, 25, 12, 6, 40), Unique(hhmm(2))),
            # Fold starts
            (
                ymdhms(2053, 10, 26, 2),
                Fold(ymdhms(2053, 10, 26, 3), hhmm(2), hhmm(1)),
            ),
            # In the fold
            (
                ymdhms(2053, 10, 26, 2, 2, 20),
                Fold(ymdhms(2053, 10, 26, 3), hhmm(2), hhmm(1)),
            ),
            # end of the fold
            (ymdhms(2053, 10, 26, 3), Unique(hhmm(1))),
        ],
    )
    def test_ambiguity_for_local(self, t, expected):
        assert ambiguity(AMS, t) == expected


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


def tzif(
    *,
    version: int,
    times: tuple[int, ...],
    idxs: tuple[int, ...],
    types: tuple[tuple[int, int, int], ...],
    abbrevs: bytes,
    footer: bytes,
) -> bytes:
    """A TZif file: `types` are (utoff, isdst, abbrind); a v1 file has its
    data in the first block and no footer."""

    def header(timecnt: int) -> bytes:
        v = b"\x00" if version == 1 else str(version).encode()
        return (
            b"TZif"
            + v
            + b"\x00" * 15
            + struct.pack(">6i", 0, 0, 0, timecnt, len(types), len(abbrevs))
        )

    def block(fmt: str) -> bytes:
        return (
            struct.pack(f">{len(times)}{fmt}", *times)
            + bytes(idxs)
            + b"".join(struct.pack(">iBB", *t) for t in types)
            + abbrevs
        )

    if version == 1:
        return header(len(times)) + block("i")
    empty_v1 = header(0) + b"".join(struct.pack(">iBB", *t) for t in types)
    return (
        empty_v1
        + abbrevs
        + header(len(times))
        + block("q")
        + b"\n"
        + footer
        + b"\n"
    )


def _with_leap_count(data: bytes, count: int) -> bytes:
    """Overwrite the leap second count in the first header"""
    return data[:28] + struct.pack(">i", count) + data[32:]


SLIM_DIR = TZIF_DIR / "slim"


class TestSlimFiles:
    """zic's "slim" files (the ``tzdata`` package) end with a record that
    changes nothing: the POSIX TZ string takes over only from there."""

    @pytest.mark.parametrize(
        "tz, utc, offset, abbrev",
        [
            # the footer's DST began only in 2019
            ("Pacific/Norfolk", (2016, 1, 15), hours(11), "+11"),
            ("Pacific/Norfolk", (2019, 8, 1), hours(11), "+11"),
            # standard time moved to -02 in March 2023, and stayed there
            ("America/Nuuk", (2023, 6, 1, 12), hours(-2), "-02"),
            ("America/Nuuk", (2023, 11, 15), hours(-2), "-02"),
            # 1995 summer time ended a week before the footer's rule
            ("Europe/London", (1995, 10, 25, 12), hours(0), "GMT"),
            ("Europe/London", (1995, 12, 25, 12), hours(0), "GMT"),
        ],
    )
    def test_last_record_holds_until_the_marker(
        self, tz, utc, offset, abbrev, tmp_path: Path
    ):
        with tz_rules_from_file(tz, str(SLIM_DIR / tz), tmp_path):
            d = Instant.from_utc(*utc).to_tz(tz)
            assert d.offset == offset
            assert d.tz_abbrev() == abbrev
            assert d.dst_offset() == TimeDelta.ZERO

    @pytest.mark.parametrize(
        "tz, last_change, footer_start",
        [
            (
                "Pacific/Norfolk",
                "2015-10-04 01:30:00+11:00",
                "2019-10-06 03:00:00+12:00",
            ),
            (
                "America/Nuuk",
                "2023-03-25 23:00:00-02:00",
                "2024-03-31 00:00:00-01:00",
            ),
            (
                "Europe/London",
                "1995-10-22 01:00:00+00:00",
                "1996-03-31 02:00:00+01:00",
            ),
            (
                "Antarctica/Troll",
                "2005-02-12 00:00:00+00:00",
                "2005-03-27 03:00:00+02:00",
            ),
        ],
    )
    def test_no_transition_between_last_change_and_footer(
        self, tz, last_change, footer_start, tmp_path: Path
    ):
        with tz_rules_from_file(tz, str(SLIM_DIR / tz), tmp_path):
            last = ZonedDateTime(f"{last_change}[{tz}]")
            first = ZonedDateTime(f"{footer_start}[{tz}]")
            assert last.next_transition() == first
            assert first.prev_transition() == last

    def test_dst_record_before_the_footer_pairs_with_its_standard_time(
        self, tmp_path: Path
    ):
        # The file ends with Winamac's 2007 move from Central standard time
        # to Eastern DST: an hour of DST, not two
        tz = "America/Indiana/Winamac"
        with tz_rules_from_file(tz, str(SLIM_DIR / tz), tmp_path):
            d = ZonedDateTime(2007, 7, 1, tz=tz)
            assert d.offset == hours(-4)
            assert d.dst_offset() == hours(1)

    def test_no_fold_before_the_marker(self, tmp_path: Path):
        # The footer ends DST at the marker instant, a change the file's
        # last records never had. (zoneinfo reports a fold here.)
        tz = "America/Nuuk"
        with tz_rules_from_file(tz, str(SLIM_DIR / tz), tmp_path):
            d = ZonedDateTime(
                2023, 10, 28, 23, 30, tz=tz, disambiguation="raise"
            )
            assert d.offset == hours(-2)
            assert not d.is_repeated()


class TestDegenerateFiles:
    LMT = (-5364662400,)  # one record in 1800

    def _zone(self, tmp_path: Path, data: bytes):
        path = tmp_path / "src"
        path.write_bytes(data)
        return tz_rules_from_file("Test/Zone", str(path), tmp_path / "db")

    def test_empty_footer(self, tmp_path: Path):
        # RFC 8536 allows it: the last record then holds
        data = tzif(
            version=2,
            times=self.LMT,
            idxs=(1,),
            types=((0, 0, 0), (7200, 0, 4)),
            abbrevs=b"LMT\x00EET\x00",
            footer=b"",
        )
        with self._zone(tmp_path, data):
            d = ZonedDateTime(2024, 7, 1, tz="Test/Zone")
            assert d.offset == hours(2)
            assert d.tz_abbrev() == "EET"
            assert d.next_transition() is None

    def test_dst_record_at_the_footers_standard_offset(self, tmp_path: Path):
        # DST began with standard time moving to the offset of the footer's
        # standard time: the saving stays one hour until the footer governs
        data = tzif(
            version=2,
            times=(1590969600,),  # 2020-06-01
            idxs=(1,),
            types=((0, 0, 0), (3600, 1, 4)),
            abbrevs=b"LMT\x00XDT\x00",
            footer=b"CET-1CEST,M3.5.0,M10.5.0/3",
        )
        with self._zone(tmp_path, data):
            d = ZonedDateTime(2020, 7, 1, tz="Test/Zone")
            assert d.offset == hours(1)
            assert d.dst_offset() == hours(1)
            assert d.tz_abbrev() == "XDT"

    def test_no_records_and_a_dst_footer(self, tmp_path: Path):
        # The footer governs the whole range, as in zoneinfo
        data = tzif(
            version=2,
            times=(),
            idxs=(),
            types=((1050, 0, 0),),
            abbrevs=b"LMT\x00",
            footer=b"CET-1CEST,M3.5.0,M10.5.0/3",
        )
        with self._zone(tmp_path, data):
            for year in (1, 1000, 2024):
                summer = ZonedDateTime(year, 7, 1, tz="Test/Zone")
                assert summer.offset == hours(2)
                assert summer.tz_abbrev() == "CEST"
                assert ZonedDateTime(
                    year, 1, 15, tz="Test/Zone"
                ).offset == hours(1)

    def test_long_abbreviation(self, tmp_path: Path):
        data = tzif(
            version=2,
            times=self.LMT,
            idxs=(1,),
            types=((0, 0, 0), (3600, 0, 4)),
            abbrevs=b"LMT\x00ABCDEFGHI\x00",
            footer=b"",
        )
        with self._zone(tmp_path, data):
            d = ZonedDateTime(2024, 7, 1, tz="Test/Zone")
            assert d.tz_abbrev() == "ABCDEFGHI"
            assert d.format("zz") == "ABCDEFGHI"

    @pytest.mark.parametrize(
        "data",
        [
            # transitions out of order
            tzif(
                version=2,
                times=(0, -100),
                idxs=(1, 0),
                types=((0, 0, 0), (3600, 0, 0)),
                abbrevs=b"UTC\x00",
                footer=b"UTC0",
            ),
            # a repeated transition time
            tzif(
                version=1,
                times=(0, 0),
                idxs=(1, 0),
                types=((0, 0, 0), (3600, 0, 0)),
                abbrevs=b"UTC\x00",
                footer=b"",
            ),
            # a v1 leap second count beyond the end of the file
            _with_leap_count(
                tzif(
                    version=1,
                    times=(),
                    idxs=(),
                    types=((3600, 0, 0),),
                    abbrevs=b"CET\x00",
                    footer=b"",
                ),
                1000,
            ),
            # a type index beyond the types
            tzif(
                version=2,
                times=(0,),
                idxs=(5,),
                types=((3600, 0, 0),),
                abbrevs=b"CET\x00",
                footer=b"CET-1",
            ),
            # a footer outside ASCII
            tzif(
                version=2,
                times=(0,),
                idxs=(0,),
                types=((3600, 0, 0),),
                abbrevs=b"CET\x00",
                footer=b"C\xc3\xa9T-1",
            ),
            # an abbreviation outside ASCII
            tzif(
                version=2,
                times=(0,),
                idxs=(0,),
                types=((3600, 0, 0),),
                abbrevs=b"C\xc3\xa9T\x00",
                footer=b"",
            ),
            # a footer whose rule time was cut off
            tzif(
                version=2,
                times=(-5364662400,),
                idxs=(0,),
                types=((3600, 0, 0),),
                abbrevs=b"CET\x00",
                footer=b"CET-1CEST,M3.5.0,M10.5.0/",
            ),
        ],
    )
    def test_corrupt_file_is_not_found(self, data, tmp_path: Path):
        with self._zone(tmp_path, data):
            with pytest.raises(TimeZoneNotFoundError, match="Test/Zone"):
                ZonedDateTime(2024, 7, 1, tz="Test/Zone")
