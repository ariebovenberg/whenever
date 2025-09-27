from datetime import date, datetime, timedelta, timezone
from functools import partial

import pytest

from whenever._tz.common import Fold, Gap, Unambiguous
from whenever._tz.posix import (
    DEFAULT_RULE_TIME,
    DayOfYear,
    Dst,
    JulianDayOfYear,
    LastWeekday,
    NthWeekday,
    TzStr,
)

UTC = timezone.utc
dt_utc = partial(datetime.fromtimestamp, tz=UTC)


def mk_epoch(
    year: int,
    month: int,
    day: int,
    hour: int = 0,
    minute: int = 0,
    second: int = 0,
) -> int:
    dt = datetime(year, month, day, hour, minute, second, tzinfo=UTC)
    return int(dt.timestamp())


class TestParse:

    @pytest.mark.parametrize(
        "s",
        [
            "",
            # no offset
            "FOO",
            # invalid tzname (digit)
            "1T",
            "<FOO>",
            "<FOO>>-3",
            "<>3",
            # Invalid components
            "FOO+01:",
            "FOO+01:9:03",
            "FOO+01:60:03",
            "FOO-01:59:60",
            "FOO-01:59:",
            "FOO-01:59:4",
            # offset too large
            "FOO24",
            "FOO+24",
            "FOO-24",
            "FOO-27:00",
            "FOO+27:00",
            "FOO-25:45:05",
            "FOO+27:45:09",
            # invalid trailing data
            "FOO+01:30M",
            # Unfinished rule
            "FOO+01:30BAR,J",
            "FOO+01:30BAR,",
            "FOO+01:30BAR,M3.2.",
            # Invalid month rule
            "FOO+01:30BAR,M13.2.1,M1.1.1",
            "FOO+01:30BAR,M12.6.1,M1.1.1",
            "FOO+01:30BAR,M12.2.7,M1.1.1",
            "FOO+01:30BAR,M12.0.2,M1.1.1",
            # Invalid day of year
            "FOO+01:30BAR,J366,M1.1.1",
            "FOO+01:30BAR,J0,M1.1.1",
            "FOO+01:30BAR,-1,M1.1.1",
            "FOO+01:30BAR,366,M1.1.1",
            # Trailing data
            "FOO+01:30BAR,M3.2.1,M1.1.1,",
            "FOO+01:30BAR,M3.2.1,M1.1.1/0/1",
            # std + 1 hr exceeds 24 hours
            "FOO-23:30BAR,M3.2.1,M1.1.1",
            # --- Below are test cases from python's zoneinfo ---
            "PST8PDT",
            "+11",
            "GMT,M3.2.0/2,M11.1.0/3",
            "GMT0+11,M3.2.0/2,M11.1.0/3",
            "PST8PDT,M3.2.0/2",
            # Invalid offsets
            "STD+25",
            "STD-25",
            "STD+374",
            "STD+374DST,M3.2.0/2,M11.1.0/3",
            "STD+23DST+25,M3.2.0/2,M11.1.0/3",
            "STD-23DST-25,M3.2.0/2,M11.1.0/3",
            # Completely invalid dates
            "AAA4BBB,M1443339,M11.1.0/3",
            "AAA4BBB,M3.2.0/2,0349309483959c",
            # Invalid months
            "AAA4BBB,M13.1.1/2,M1.1.1/2",
            "AAA4BBB,M1.1.1/2,M13.1.1/2",
            "AAA4BBB,M0.1.1/2,M1.1.1/2",
            "AAA4BBB,M1.1.1/2,M0.1.1/2",
            # Invalid weeks
            "AAA4BBB,M1.6.1/2,M1.1.1/2",
            "AAA4BBB,M1.1.1/2,M1.6.1/2",
            # Invalid weekday
            "AAA4BBB,M1.1.7/2,M2.1.1/2",
            "AAA4BBB,M1.1.1/2,M2.1.7/2",
            # Invalid numeric offset
            "AAA4BBB,-1/2,20/2",
            "AAA4BBB,1/2,-1/2",
            "AAA4BBB,367,20/2",
            "AAA4BBB,1/2,367/2",
            # Invalid julian offset
            "AAA4BBB,J0/2,J20/2",
            "AAA4BBB,J20/2,J366/2",
            # non-ascii
            "AAÄ8",
        ],
    )
    def test_invalid(self, s):
        with pytest.raises(ValueError):
            TzStr.parse(s)

    @pytest.mark.parametrize(
        "s, expected",
        [
            ("FOO1", -3600),
            ("FOOS0", 0),
            ("FOO+01", -3600),
            ("FOO+01:30", -3600 - 30 * 60),
            ("FOO+01:30:59", -3600 - 30 * 60 - 59),
            ("FOOM+23:59:59", -86399),
            ("FOOS-23:59:59", 86399),
            ("FOOBLA-23:59", 23 * 3600 + 59 * 60),
            ("FOO-23", 23 * 3600),
            ("FOO-01", 3600),
            ("FOO-01:30", 3600 + 30 * 60),
            ("FOO-01:30:59", 3600 + 30 * 60 + 59),
            ("FOO+23:59:59", -86399),
            ("FOO+23:59", -23 * 3600 - 59 * 60),
            ("FOO+23", -23 * 3600),
            ("<FOO>-3", 3 * 3600),
        ],
    )
    def test_fixed_offset(self, s, expected):
        assert TzStr.parse(s) == TzStr(expected, dst=None)

    def test_with_dst(self):
        # Implicit DST offset
        tz = TzStr.parse("FOO-1FOOS,M3.5.0,M10.4.0")
        expected = TzStr(
            std=3600,
            dst=Dst(
                offset=7200,
                start=(LastWeekday(3, 0), DEFAULT_RULE_TIME),
                end=(NthWeekday(10, 4, 0), DEFAULT_RULE_TIME),
            ),
        )
        assert tz == expected

        # Explicit DST offset
        tz = TzStr.parse("FOO+1FOOS2:30,M3.5.0,M10.2.0")
        expected = TzStr(
            std=-3600,
            dst=Dst(
                offset=-2 * 3600 - 30 * 60,
                start=(LastWeekday(3, 0), DEFAULT_RULE_TIME),
                end=(NthWeekday(10, 2, 0), DEFAULT_RULE_TIME),
            ),
        )
        assert tz == expected

        # Explicit time, weekday rule
        tz = TzStr.parse("FOO+1FOOS2:30,M3.5.0/8,M10.2.0")
        expected = TzStr(
            std=-3600,
            dst=Dst(
                offset=-2 * 3600 - 30 * 60,
                start=(LastWeekday(3, 0), 8 * 3600),
                end=(NthWeekday(10, 2, 0), DEFAULT_RULE_TIME),
            ),
        )
        assert tz == expected

        # Explicit time, Julian day rule
        tz = TzStr.parse("FOO+1FOOS2:30,J023/8:34:01,M10.2.0/03")
        expected = TzStr(
            std=-3600,
            dst=Dst(
                offset=-2 * 3600 - 30 * 60,
                start=(JulianDayOfYear(23), 8 * 3600 + 34 * 60 + 1),
                end=(NthWeekday(10, 2, 0), 3 * 3600),
            ),
        )
        assert tz == expected

        # Explicit time, day-of-year rule
        tz = TzStr.parse("FOO+1FOOS2:30,023/8:34:01,J1/0")
        expected = TzStr(
            std=-3600,
            dst=Dst(
                offset=-2 * 3600 - 30 * 60,
                start=(DayOfYear(24), 8 * 3600 + 34 * 60 + 1),
                end=(JulianDayOfYear(1), 0),
            ),
        )
        assert tz == expected

        # Explicit time, zero'th day of year
        tz = TzStr.parse("FOO+1FOOS2:30,00/8:34:01,J1/0")
        expected = TzStr(
            std=-3600,
            dst=Dst(
                offset=-2 * 3600 - 30 * 60,
                start=(DayOfYear(1), 8 * 3600 + 34 * 60 + 1),
                end=(JulianDayOfYear(1), 0),
            ),
        )
        assert tz == expected

        # 24:00:00 is a valid time for a rule
        tz = TzStr.parse("FOO+2FOOS+1,M3.5.0/24,M10.2.0")
        expected = TzStr(
            std=-7200,
            dst=Dst(
                offset=-3600,
                start=(LastWeekday(3, 0), 24 * 3600),
                end=(NthWeekday(10, 2, 0), DEFAULT_RULE_TIME),
            ),
        )
        assert tz == expected

        # Anything between -167 and 167 hours is also valid!
        tz = TzStr.parse("FOO+2FOOS+1,M3.5.0/-89:02,M10.2.0/100")
        expected = TzStr(
            std=-7200,
            dst=Dst(
                offset=-3600,
                start=(LastWeekday(3, 0), -89 * 3600 - 2 * 60),
                end=(NthWeekday(10, 2, 0), 100 * 3600),
            ),
        )
        assert tz == expected


class TestApplyRule:

    @pytest.mark.parametrize(
        "year, nth, expected",
        [
            # Extremes
            (1, 1, (1, 1, 1)),  # MIN day
            (9999, 366, (9999, 12, 31)),  # MAX day
            # no leap year
            (2021, 1, (2021, 1, 1)),  # First day
            (2059, 40, (2059, 2, 9)),  # < Feb 28
            (2221, 59, (2221, 2, 28)),  # Feb 28
            (1911, 60, (1911, 3, 1)),  # Mar 1
            (1900, 124, (1900, 5, 4)),  # > Mar 1
            (2021, 365, (2021, 12, 31)),  # Last day
            (2021, 366, (2021, 12, 31)),  # Last day (clamped)
            # leap year
            (2024, 1, (2024, 1, 1)),  # First day
            (2060, 40, (2060, 2, 9)),  # < Feb 28
            (2228, 59, (2228, 2, 28)),  # Feb 28
            (2228, 60, (2228, 2, 29)),  # Feb 29
            (1920, 61, (1920, 3, 1)),  # Mar 1
            (2000, 125, (2000, 5, 4)),  # > Mar 1
            (2020, 365, (2020, 12, 30)),  # second-to-last day
            (2020, 366, (2020, 12, 31)),  # Last day
        ],
    )
    def test_day_of_year(self, year, nth, expected):
        assert DayOfYear(nth).apply(year) == date(*expected)

    @pytest.mark.parametrize(
        "year, nth, expected",
        [
            # Extremes
            (1, 1, (1, 1, 1)),  # MIN day
            (9999, 365, (9999, 12, 31)),  # MAX day
            # no leap year
            (2021, 1, (2021, 1, 1)),  # First day
            (2059, 40, (2059, 2, 9)),  # < Feb 28
            (2221, 59, (2221, 2, 28)),  # Feb 28
            (1911, 60, (1911, 3, 1)),  # Mar 1
            (1900, 124, (1900, 5, 4)),  # > Mar 1
            (2021, 365, (2021, 12, 31)),  # Last day
            # leap year
            (2024, 1, (2024, 1, 1)),  # First day
            (2060, 40, (2060, 2, 9)),  # < Feb 28
            (2228, 59, (2228, 2, 28)),  # Feb 28
            (1920, 60, (1920, 3, 1)),  # Mar 1
            (2000, 124, (2000, 5, 4)),  # > Mar 1
            (2020, 364, (2020, 12, 30)),  # second-to-last day
            (2020, 365, (2020, 12, 31)),  # Last day
        ],
    )
    def test_julian_day_of_year(self, year, nth, expected):
        assert JulianDayOfYear(nth).apply(year) == date(*expected)

    @pytest.mark.parametrize(
        "year, weekday, month, expected",
        [
            (2024, 3, 0, (2024, 3, 31)),
            (2024, 3, 1, (2024, 3, 25)),
            (1915, 7, 0, (1915, 7, 25)),
            (1915, 7, 6, (1915, 7, 31)),
            (1919, 7, 4, (1919, 7, 31)),
            (1919, 7, 0, (1919, 7, 27)),
        ],
    )
    def test_last_weekday(self, year, weekday, month, expected):
        assert LastWeekday(weekday, month).apply(year) == date(*expected)

    @pytest.mark.parametrize(
        "year, month, nth, weekday, expected",
        [
            (1919, 7, 1, 0, (1919, 7, 6)),
            (2002, 12, 1, 0, (2002, 12, 1)),
            (2002, 12, 2, 0, (2002, 12, 8)),
            (2002, 12, 3, 6, (2002, 12, 21)),
            (1992, 2, 1, 6, (1992, 2, 1)),
            (1992, 2, 4, 6, (1992, 2, 22)),
        ],
    )
    def test_nth_weekday(self, year, month, nth, weekday, expected):
        assert NthWeekday(month, nth, weekday).apply(year) == date(*expected)


class TestCalculateOffsets:

    TZ_FIXED = TzStr(std=1234, dst=None)

    # A TZ with random-ish DST rules
    TZ = TzStr(
        std=4800,
        dst=Dst(
            offset=9300,
            start=(LastWeekday(3, 0), 4 * 3600),
            end=(JulianDayOfYear(281), DEFAULT_RULE_TIME),
        ),
    )

    # A TZ with DST time rules that are very large, or negative!
    TZ_WEIRDTIME = TzStr(
        std=4800,
        dst=Dst(
            offset=9300,
            start=(LastWeekday(3, 0), 50 * 3600),
            end=(JulianDayOfYear(281), -2 * 3600),
        ),
    )

    # A TZ with DST rules that are 00:00:00
    TZ00 = TzStr(
        std=4800,
        dst=Dst(
            offset=9300,
            start=(LastWeekday(3, 0), 0),
            end=(JulianDayOfYear(281), 0),
        ),
    )

    # A TZ with a DST offset smaller than the standard offset (theoretically possible)
    TZ_NEG = TzStr(
        std=4800,
        dst=Dst(
            offset=1200,
            start=(LastWeekday(3, 0), DEFAULT_RULE_TIME),
            end=(JulianDayOfYear(281), 4 * 3600),
        ),
    )

    # Some timezones have DST end before start
    TZ_INVERTED = TzStr(
        std=4800,
        dst=Dst(
            offset=7200,
            end=(LastWeekday(3, 0), DEFAULT_RULE_TIME),
            start=(JulianDayOfYear(281), 4 * 3600),  # oct 8th
        ),
    )

    # Some timezones appear to be "always DST", like Africa/Casablanca
    TZ_ALWAYS_DST = TzStr(
        std=7200,
        dst=Dst(
            offset=3600,
            start=(DayOfYear(1), 0),
            end=(JulianDayOfYear(365), 23 * 3600),
        ),
    )

    @pytest.mark.parametrize(
        "tz, ymd, hms, expected",
        [
            # fixed always the same
            (TZ_FIXED, (2020, 3, 19), (12, 34, 56), Unambiguous(1234)),
            # First second of the year
            (TZ, (1990, 1, 1), (0, 0, 0), Unambiguous(4800)),
            # Last second of the year
            (TZ, (1990, 12, 31), (23, 59, 59), Unambiguous(4800)),
            # Well before the transition
            (TZ, (1990, 3, 13), (12, 34, 56), Unambiguous(4800)),
            # Gap: Before, start, mid, end, after
            (TZ, (1990, 3, 25), (3, 59, 59), Unambiguous(4800)),
            (TZ, (1990, 3, 25), (4, 0, 0), Gap(9300, 4800)),
            (TZ, (1990, 3, 25), (5, 10, 0), Gap(9300, 4800)),
            (TZ, (1990, 3, 25), (5, 14, 59), Gap(9300, 4800)),
            (TZ, (1990, 3, 25), (5, 15, 0), Unambiguous(9300)),
            # Well after the transition
            (TZ, (1990, 6, 26), (8, 0, 0), Unambiguous(9300)),
            # Fold: Before, start, mid, end, after
            (TZ, (1990, 10, 8), (0, 44, 59), Unambiguous(9300)),
            (TZ, (1990, 10, 8), (0, 45, 0), Fold(9300, 4800)),
            (TZ, (1990, 10, 8), (1, 33, 59), Fold(9300, 4800)),
            (TZ, (1990, 10, 8), (1, 59, 59), Fold(9300, 4800)),
            (TZ, (1990, 10, 8), (2, 0, 0), Unambiguous(4800)),
            # Well after the end of DST
            (TZ, (1990, 11, 30), (23, 34, 56), Unambiguous(4800)),
            # time outside 0-24h range is also valid for a rule
            (TZ_WEIRDTIME, (1990, 3, 26), (1, 59, 59), Unambiguous(4800)),
            (TZ_WEIRDTIME, (1990, 3, 27), (2, 0, 0), Gap(9300, 4800)),
            (TZ_WEIRDTIME, (1990, 3, 27), (3, 0, 0), Gap(9300, 4800)),
            (TZ_WEIRDTIME, (1990, 3, 27), (3, 14, 59), Gap(9300, 4800)),
            (TZ_WEIRDTIME, (1990, 3, 27), (3, 15, 0), Unambiguous(9300)),
            (TZ_WEIRDTIME, (1990, 10, 7), (20, 44, 59), Unambiguous(9300)),
            (TZ_WEIRDTIME, (1990, 10, 7), (20, 45, 0), Fold(9300, 4800)),
            (TZ_WEIRDTIME, (1990, 10, 7), (21, 33, 59), Fold(9300, 4800)),
            (TZ_WEIRDTIME, (1990, 10, 7), (21, 59, 59), Fold(9300, 4800)),
            (TZ_WEIRDTIME, (1990, 10, 7), (22, 0, 0), Unambiguous(4800)),
            (TZ_WEIRDTIME, (1990, 10, 7), (22, 0, 1), Unambiguous(4800)),
            # 00:00:00 is a valid time for a rule
            (TZ00, (1990, 3, 24), (23, 59, 59), Unambiguous(4800)),
            (TZ00, (1990, 3, 25), (0, 0, 0), Gap(9300, 4800)),
            (TZ00, (1990, 3, 25), (1, 0, 0), Gap(9300, 4800)),
            (TZ00, (1990, 3, 25), (1, 14, 59), Gap(9300, 4800)),
            (TZ00, (1990, 3, 25), (1, 15, 0), Unambiguous(9300)),
            (TZ00, (1990, 10, 7), (22, 44, 59), Unambiguous(9300)),
            (TZ00, (1990, 10, 7), (22, 45, 0), Fold(9300, 4800)),
            (TZ00, (1990, 10, 7), (23, 33, 59), Fold(9300, 4800)),
            (TZ00, (1990, 10, 7), (23, 59, 59), Fold(9300, 4800)),
            (TZ00, (1990, 10, 8), (0, 0, 0), Unambiguous(4800)),
            (TZ00, (1990, 10, 8), (0, 0, 1), Unambiguous(4800)),
            # Negative DST should be handled gracefully. Gap and fold reversed
            # Fold instead of gap
            (TZ_NEG, (1990, 3, 25), (0, 59, 59), Unambiguous(4800)),
            (TZ_NEG, (1990, 3, 25), (1, 0, 0), Fold(4800, 1200)),
            (TZ_NEG, (1990, 3, 25), (1, 33, 59), Fold(4800, 1200)),
            (TZ_NEG, (1990, 3, 25), (1, 59, 59), Fold(4800, 1200)),
            (TZ_NEG, (1990, 3, 25), (2, 0, 0), Unambiguous(1200)),
            # Gap instead of fold
            (TZ_NEG, (1990, 10, 8), (3, 59, 59), Unambiguous(1200)),
            (TZ_NEG, (1990, 10, 8), (4, 0, 0), Gap(4800, 1200)),
            (TZ_NEG, (1990, 10, 8), (4, 42, 12), Gap(4800, 1200)),
            (TZ_NEG, (1990, 10, 8), (4, 59, 59), Gap(4800, 1200)),
            (TZ_NEG, (1990, 10, 8), (5, 0, 0), Unambiguous(4800)),
            # Always DST
            (TZ_ALWAYS_DST, (1990, 1, 1), (0, 0, 0), Unambiguous(3600)),
            # This is actually incorrect, but ZoneInfo does the same...
            (TZ_ALWAYS_DST, (1992, 12, 31), (23, 0, 0), Gap(7200, 3600)),
            # Inverted DST
            (
                TZ_INVERTED,
                (1990, 2, 9),
                (15, 0, 0),
                Unambiguous(7200),
            ),  # DST in effect
            (
                TZ_INVERTED,
                (1990, 3, 25),
                (1, 19, 0),
                Unambiguous(7200),
            ),  # Before fold
            (
                TZ_INVERTED,
                (1990, 3, 25),
                (1, 20, 0),
                Fold(7200, 4800),
            ),  # Fold starts
            (
                TZ_INVERTED,
                (1990, 3, 25),
                (1, 59, 0),
                Fold(7200, 4800),
            ),  # Fold almost over
            (
                TZ_INVERTED,
                (1990, 3, 25),
                (2, 0, 0),
                Unambiguous(4800),
            ),  # Fold over
            (
                TZ_INVERTED,
                (1990, 9, 8),
                (8, 0, 0),
                Unambiguous(4800),
            ),  # DST not in effect
            (
                TZ_INVERTED,
                (1990, 10, 8),
                (3, 59, 0),
                Unambiguous(4800),
            ),  # Before gap
            (
                TZ_INVERTED,
                (1990, 10, 8),
                (4, 0, 0),
                Gap(7200, 4800),
            ),  # Gap starts
            (
                TZ_INVERTED,
                (1990, 10, 8),
                (4, 39, 0),
                Gap(7200, 4800),
            ),  # Gap almost over
            (
                TZ_INVERTED,
                (1990, 10, 8),
                (4, 40, 0),
                Unambiguous(7200),
            ),  # Gap over
            (
                TZ_INVERTED,
                (1990, 12, 31),
                (23, 40, 0),
                Unambiguous(7200),
            ),  # DST not in effect
        ],
    )
    def test_calculate_offsets(self, tz: TzStr, ymd, hms, expected):

        def to_epoch_s(
            year: int,
            month: int,
            day: int,
            hour: int,
            minute: int,
            second: int,
            offset: int = 0,
        ) -> int:
            dt = datetime(year, month, day, hour, minute, second, tzinfo=UTC)
            return int((dt - timedelta(seconds=offset)).timestamp())

        y, m, d = ymd
        hour, minute, second = hms

        local_epoch = to_epoch_s(y, m, d, hour, minute, second, 0)

        actual = tz.ambiguity_for_local(local_epoch)
        assert actual == expected

        # Test that the inverse operation (epoch->local) works
        if isinstance(expected, Unambiguous):
            assert (
                tz.offset_for_instant(
                    to_epoch_s(y, m, d, hour, minute, second, expected.offset)
                )
                == expected.offset
            )
        elif isinstance(expected, Fold):
            epoch_a = to_epoch_s(
                y, m, d, hour, minute, second, expected.before
            )
            epoch_b = to_epoch_s(y, m, d, hour, minute, second, expected.after)
            assert tz.offset_for_instant(epoch_a) == expected.before
            assert tz.offset_for_instant(epoch_b) == expected.after
        else:
            pass  # Gap times aren't reversible
