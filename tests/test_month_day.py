import re

import pytest
from whenever import (
    Date,
    MonthDay,
)


class TestInit:
    @pytest.mark.parametrize(
        "month, day", [(12, 3), (1, 1), (12, 31), (2, 29)]
    )
    def test_valid(self, month, day):
        md = MonthDay(month, day)
        assert (md.month, md.day) == (month, day)

    @pytest.mark.parametrize(
        "month, day",
        [
            (13, 1),
            (2, 30),
            (4, 31),
            (8, 32),
            (0, 3),
            (10_000, 3),
        ],
    )
    def test_invalid_combinations(self, month, day):
        with pytest.raises(ValueError, match=r"^invalid date$"):
            MonthDay(month, day)

    def test_invalid(self):
        with pytest.raises(TypeError):
            MonthDay(2)  # type: ignore[call-overload]

        with pytest.raises(TypeError):
            MonthDay("20", "SEP")  # type: ignore[call-overload]

        with pytest.raises(TypeError):
            MonthDay()  # type: ignore[call-overload]

    def test_iso_string_is_positional_only(self):
        with pytest.raises(TypeError):
            MonthDay(iso_string="--12-25")  # type: ignore[call-overload]

    def test_iso(self):
        assert MonthDay("--12-25") == MonthDay(12, 25)


class TestAccessors:
    def test_properties(self):
        md = MonthDay(12, 14)
        assert md.month == 12
        assert md.day == 14

    def test_singletons(self):
        assert MonthDay.MIN == MonthDay(1, 1)
        assert MonthDay.MAX == MonthDay(12, 31)


class TestFormatIso:
    def test_format_iso(self):
        assert MonthDay(11, 12).format_iso() == "--11-12"
        assert MonthDay(2, 1).format_iso() == "--02-01"
        assert MonthDay.parse_iso(MonthDay(2, 1).format_iso()) == MonthDay(
            2, 1
        )

    def test_str(self):
        assert (
            str(MonthDay(10, 31)) == "--10-31" == MonthDay(10, 31).format_iso()
        )
        assert str(MonthDay(2, 1)) == "--02-01"

    def test_repr(self):
        assert repr(MonthDay(11, 12)) == 'MonthDay("--11-12")'
        assert repr(MonthDay(2, 1)) == 'MonthDay("--02-01")'


class TestParseIso:
    @pytest.mark.parametrize(
        "s, expected",
        [
            ("--08-21", MonthDay(8, 21)),
            ("--10-02", MonthDay(10, 2)),
            # basic format
            ("--1002", MonthDay(10, 2)),
        ],
    )
    def test_valid(self, s, expected):
        assert MonthDay.parse_iso(s) == expected

    @pytest.mark.parametrize(
        "s",
        [
            "--2A-01",  # non-digit
            "--11-01T03:04:05",  # with a time
            "2021-01-02",  # with a year
            "--11-1",  # no padding
            "--1-13",  # no padding
            "W12-04",  # week date
            "03-12",  # no dashes
            "-10-12",  # not enough dashes
            "---12-03",  # negative month
            "--+1-03",  # signed month
            "-- 1-03",  # whitespace in month
            "--12-+3",  # signed day
            "--12- 3",  # whitespace in day
            "--1🧨-12",  # non-ASCII
            "--1𝟙-11",  # non-ascii
            # invalid components
            "--00-01",
            "--13-01",
            "--11-00",
            "--11-31",
        ],
    )
    def test_invalid(self, s):
        with pytest.raises(
            ValueError,
            match=r"^invalid ISO 8601 string: " + re.escape(repr(s)) + "$",
        ):
            MonthDay.parse_iso(s)

    def test_no_string(self):
        with pytest.raises((TypeError, AttributeError), match="(int|str)"):
            MonthDay.parse_iso(20210102)  # type: ignore[arg-type]


class TestEquality:
    def test_eq(self):
        md = MonthDay(10, 12)
        same = MonthDay(10, 12)
        different = MonthDay(10, 11)

        assert md == same
        assert not md == different

        assert not md != same
        assert md != different

        assert hash(md) == hash(same)


class TestComparison:
    def test_comparison(self):
        md = MonthDay(7, 5)
        same = MonthDay(7, 5)
        bigger = MonthDay(8, 2)
        smaller = MonthDay(6, 12)

        assert md <= same
        assert md <= bigger
        assert not md <= smaller

        assert not md < same
        assert md < bigger
        assert not md < smaller

        assert md >= same
        assert not md >= bigger
        assert md >= smaller

        assert not md > same
        assert not md > bigger
        assert md > smaller


class TestReplace:
    def test_replace(self):
        md = MonthDay(12, 31)
        assert md.replace(month=8) == MonthDay(8, 31)
        assert md.replace(day=8) == MonthDay(12, 8)
        assert md == MonthDay(12, 31)  # original is unchanged

        # the message names no dummy year
        with pytest.raises(ValueError, match="^invalid date$"):
            md.replace(month=2)

        with pytest.raises(ValueError, match="^invalid date$"):
            md.replace(day=32)

        with pytest.raises(ValueError, match="^invalid date$"):
            md.replace(month=2, day=31)

        with pytest.raises(TypeError):
            md.replace(3)  # type: ignore[call-arg]

        with pytest.raises(TypeError, match="foo"):
            md.replace(foo=3)  # type: ignore[call-arg]

        with pytest.raises(TypeError, match="year"):
            md.replace(year=2000)  # type: ignore[call-arg]

        with pytest.raises(TypeError, match="foo"):
            md.replace(foo="blabla")  # type: ignore[call-arg]

        with pytest.raises(ValueError, match="^invalid date$"):
            md.replace(month=13)


class TestCalendarProperties:
    def test_is_leap_day(self):
        assert MonthDay(2, 29).is_leap_day()
        assert not MonthDay(2, 28).is_leap_day()
        assert not MonthDay(3, 1).is_leap_day()
        assert not MonthDay(1, 1).is_leap_day()
        assert not MonthDay(12, 31).is_leap_day()


class TestConversion:
    def test_in_year(self):
        md = MonthDay(12, 28)
        assert md.in_year(2000) == Date(2000, 12, 28)
        assert md.in_year(4) == Date(4, 12, 28)

        with pytest.raises(ValueError):
            md.in_year(0)

        with pytest.raises(ValueError):
            md.in_year(10_000)

        with pytest.raises(ValueError):
            md.in_year(-1)

        leap_day = MonthDay(2, 29)
        assert leap_day.in_year(2000) == Date(2000, 2, 29)
        with pytest.raises(ValueError):
            leap_day.in_year(2001)
