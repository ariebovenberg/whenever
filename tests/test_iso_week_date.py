import pickle
import re
from copy import copy, deepcopy

import pytest

from whenever import Date, IsoWeekDate, Weekday

MONDAY = Weekday.MONDAY
TUESDAY = Weekday.TUESDAY
WEDNESDAY = Weekday.WEDNESDAY
THURSDAY = Weekday.THURSDAY
FRIDAY = Weekday.FRIDAY
SATURDAY = Weekday.SATURDAY
SUNDAY = Weekday.SUNDAY


class TestConstructor:

    def test_basic(self):
        iwd = IsoWeekDate(2024, 1, MONDAY)
        assert iwd.year == 2024
        assert iwd.week == 1
        assert iwd.weekday == MONDAY

    def test_from_string(self):
        iwd = IsoWeekDate("2024-W01-1")
        assert iwd.year == 2024
        assert iwd.week == 1
        assert iwd.weekday == MONDAY

    def test_basic_format(self):
        iwd = IsoWeekDate("2024W011")
        assert iwd.year == 2024
        assert iwd.week == 1
        assert iwd.weekday == MONDAY

    def test_week_53_long_year(self):
        iwd = IsoWeekDate(2004, 53, FRIDAY)
        assert iwd.week == 53

    def test_invalid_week_0(self):
        with pytest.raises(ValueError):
            IsoWeekDate(2024, 0, MONDAY)

    def test_invalid_week_53_short_year(self):
        with pytest.raises(ValueError):
            IsoWeekDate(2024, 53, MONDAY)

    def test_invalid_week_54(self):
        with pytest.raises(ValueError):
            IsoWeekDate(2004, 54, MONDAY)

    def test_invalid_weekday_type(self):
        with pytest.raises(TypeError):
            IsoWeekDate(2024, 1, 1)  # type: ignore[call-overload]

    def test_invalid_string(self):
        with pytest.raises(ValueError):
            IsoWeekDate("2024-01-01")

    def test_invalid_string_bad_day(self):
        with pytest.raises(ValueError):
            IsoWeekDate("2024-W01-0")

    def test_invalid_string_day_8(self):
        with pytest.raises(ValueError):
            IsoWeekDate("2024-W01-8")


class TestProperties:

    def test_year(self):
        assert IsoWeekDate(2024, 1, MONDAY).year == 2024

    def test_week(self):
        assert IsoWeekDate(2024, 52, FRIDAY).week == 52

    def test_weekday(self):
        assert IsoWeekDate(2024, 1, FRIDAY).weekday == FRIDAY

    def test_all_weekdays(self):
        for i, wd in enumerate(
            [MONDAY, TUESDAY, WEDNESDAY, THURSDAY, FRIDAY, SATURDAY, SUNDAY],
            start=1,
        ):
            iwd = IsoWeekDate(2024, 1, wd)
            assert iwd.weekday == wd
            assert iwd.weekday.value == i


class TestDate:

    def test_basic(self):
        assert IsoWeekDate(2024, 1, MONDAY).date() == Date(2024, 1, 1)

    def test_year_boundary(self):
        # Dec 30, 2024 is Monday of ISO week 2025-W01
        assert IsoWeekDate(2025, 1, MONDAY).date() == Date(2024, 12, 30)

    def test_end_of_year(self):
        # Dec 28, 2024 is Saturday of ISO week 2024-W52
        assert IsoWeekDate(2024, 52, SATURDAY).date() == Date(2024, 12, 28)

    def test_week53(self):
        # 2004-W53-6 (Saturday) = Jan 1, 2005
        assert IsoWeekDate(2004, 53, SATURDAY).date() == Date(2005, 1, 1)

    def test_roundtrip(self):
        d = Date(2024, 7, 4)
        assert d.iso_week_date().date() == d


class TestWeeksInYear:

    def test_long_year(self):
        assert IsoWeekDate(2004, 1, MONDAY).weeks_in_year() == 53

    def test_short_year(self):
        assert IsoWeekDate(2024, 1, MONDAY).weeks_in_year() == 52


class TestFormatParse:

    def test_format_iso(self):
        assert IsoWeekDate(2024, 1, MONDAY).format_iso() == "2024-W01-1"

    def test_format_iso_week53(self):
        assert IsoWeekDate(2004, 53, FRIDAY).format_iso() == "2004-W53-5"

    def test_format_iso_basic(self):
        assert (
            IsoWeekDate(2024, 1, MONDAY).format_iso(basic=True) == "2024W011"
        )

    def test_format_iso_basic_week53(self):
        assert (
            IsoWeekDate(2004, 53, FRIDAY).format_iso(basic=True) == "2004W535"
        )

    def test_parse_iso_extended(self):
        iwd = IsoWeekDate.parse_iso("2024-W01-1")
        assert iwd == IsoWeekDate(2024, 1, MONDAY)

    def test_parse_iso_basic(self):
        iwd = IsoWeekDate.parse_iso("2024W011")
        assert iwd == IsoWeekDate(2024, 1, MONDAY)

    def test_str(self):
        assert str(IsoWeekDate(2024, 1, MONDAY)) == "2024-W01-1"

    def test_repr(self):
        assert (
            repr(IsoWeekDate(2024, 1, MONDAY)) == 'IsoWeekDate("2024-W01-1")'
        )

    def test_parse_invalid(self):
        with pytest.raises(ValueError):
            IsoWeekDate.parse_iso("not-a-date")

    def test_parse_wrong_format(self):
        with pytest.raises(ValueError):
            IsoWeekDate.parse_iso("2024-01-01")


class TestComparison:

    def test_equal(self):
        assert IsoWeekDate(2024, 1, MONDAY) == IsoWeekDate(2024, 1, MONDAY)

    def test_not_equal(self):
        assert IsoWeekDate(2024, 1, MONDAY) != IsoWeekDate(2024, 1, TUESDAY)

    def test_less_than_by_week(self):
        assert IsoWeekDate(2024, 1, MONDAY) < IsoWeekDate(2024, 2, MONDAY)

    def test_less_than_by_year(self):
        assert IsoWeekDate(2023, 52, SUNDAY) < IsoWeekDate(2024, 1, MONDAY)

    def test_less_than_by_day(self):
        assert IsoWeekDate(2024, 1, MONDAY) < IsoWeekDate(2024, 1, TUESDAY)

    def test_greater_than(self):
        assert IsoWeekDate(2024, 2, MONDAY) > IsoWeekDate(2024, 1, MONDAY)

    def test_le(self):
        assert IsoWeekDate(2024, 1, MONDAY) <= IsoWeekDate(2024, 1, MONDAY)
        assert IsoWeekDate(2024, 1, MONDAY) <= IsoWeekDate(2024, 1, TUESDAY)

    def test_ge(self):
        assert IsoWeekDate(2024, 1, TUESDAY) >= IsoWeekDate(2024, 1, TUESDAY)
        assert IsoWeekDate(2024, 1, TUESDAY) >= IsoWeekDate(2024, 1, MONDAY)

    def test_not_equal_to_other_type(self):
        assert IsoWeekDate(2024, 1, MONDAY) != "2024-W01-1"  # type: ignore[comparison-overlap]
        assert IsoWeekDate(2024, 1, MONDAY) != (2024, 1, MONDAY)  # type: ignore[comparison-overlap]


class TestHash:

    def test_equal_values_same_hash(self):
        a = IsoWeekDate(2024, 1, MONDAY)
        b = IsoWeekDate(2024, 1, MONDAY)
        assert hash(a) == hash(b)

    def test_usable_in_set(self):
        s = {IsoWeekDate(2024, 1, MONDAY), IsoWeekDate(2024, 1, MONDAY)}
        assert len(s) == 1


class TestReplace:

    def test_replace_week(self):
        iwd = IsoWeekDate(2024, 1, MONDAY)
        assert iwd.replace(week=10) == IsoWeekDate(2024, 10, MONDAY)

    def test_replace_weekday(self):
        iwd = IsoWeekDate(2024, 1, MONDAY)
        assert iwd.replace(weekday=FRIDAY) == IsoWeekDate(2024, 1, FRIDAY)

    def test_replace_year(self):
        iwd = IsoWeekDate(2024, 1, MONDAY)
        assert iwd.replace(year=2025) == IsoWeekDate(2025, 1, MONDAY)

    def test_replace_invalid(self):
        with pytest.raises(ValueError):
            IsoWeekDate(2024, 52, MONDAY).replace(week=53)


class TestPickle:

    def test_roundtrip(self):
        iwd = IsoWeekDate(2024, 1, MONDAY)
        assert pickle.loads(pickle.dumps(iwd)) == iwd

    def test_roundtrip_week53(self):
        iwd = IsoWeekDate(2004, 53, FRIDAY)
        assert pickle.loads(pickle.dumps(iwd)) == iwd

    def test_unpickle_compatibility(self):
        dumped = (
            b"\x80\x04\x95&\x00\x00\x00\x00\x00\x00\x00\x8c\x08whenever"
            b"\x94\x8c\n_unpkl_iwd\x94\x93\x94C\x04\xe8\x07\x01\x01\x94"
            b"\x85\x94R\x94."
        )
        assert pickle.loads(dumped) == IsoWeekDate(2024, 1, MONDAY)


class TestMinMax:

    def test_min_exists(self):
        assert isinstance(IsoWeekDate.MIN, IsoWeekDate)

    def test_max_exists(self):
        assert isinstance(IsoWeekDate.MAX, IsoWeekDate)

    def test_min_le_max(self):
        assert IsoWeekDate.MIN <= IsoWeekDate.MAX
