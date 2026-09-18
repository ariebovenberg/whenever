import re

import pytest
from whenever import (
    FRIDAY,
    MONDAY,
    SATURDAY,
    SUNDAY,
    THURSDAY,
    TUESDAY,
    WEDNESDAY,
    Date,
    IsoWeekDate,
    Weekday,
)


class TestInit:
    def test_basic(self):
        iwd = IsoWeekDate(2024, 1, MONDAY)
        assert iwd.year == 2024
        assert iwd.week == 1
        assert iwd.weekday == MONDAY

    def test_keyword_arguments(self):
        assert IsoWeekDate(year=2024, week=1, weekday=MONDAY) == IsoWeekDate(
            2024, 1, MONDAY
        )

    def test_mixed_arguments(self):
        assert IsoWeekDate(2024, week=1, weekday=MONDAY) == IsoWeekDate(
            2024, 1, MONDAY
        )

    def test_duplicate_argument(self):
        with pytest.raises(TypeError):
            IsoWeekDate(2024, 1, MONDAY, year=2025)  # type: ignore[call-overload]

    def test_unexpected_keyword_argument(self):
        with pytest.raises(TypeError):
            IsoWeekDate(2024, 1, MONDAY, era="CE")  # type: ignore[call-overload]

    def test_iso_string_is_positional_only(self):
        with pytest.raises(TypeError):
            IsoWeekDate(iso_string="2024-W01-1")  # type: ignore[call-overload]

    def test_no_defaults(self):
        with pytest.raises(TypeError):
            IsoWeekDate()  # type: ignore[call-overload]

    def test_one_day_past_max(self):
        assert IsoWeekDate(9999, 52, FRIDAY).date() == Date.MAX
        with pytest.raises(ValueError):
            IsoWeekDate(9999, 52, SATURDAY)

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

    def test_invalid_field_type(self):
        with pytest.raises(TypeError, match="week must be an integer"):
            IsoWeekDate(2024, "1", MONDAY)  # type: ignore[call-overload]

        with pytest.raises(TypeError, match="year must be an integer"):
            IsoWeekDate(2024.0, 1, MONDAY)  # type: ignore[call-overload]

    def test_invalid_string(self):
        with pytest.raises(ValueError):
            IsoWeekDate("2024-01-01")

    def test_invalid_string_missing_weekday(self):
        with pytest.raises(ValueError):
            IsoWeekDate("2024-W01")

    def test_invalid_string_abc(self):
        with pytest.raises(ValueError):
            IsoWeekDate("abc")

    def test_invalid_string_empty(self):
        with pytest.raises(ValueError):
            IsoWeekDate("")

    def test_invalid_string_week_0(self):
        with pytest.raises(ValueError):
            IsoWeekDate("2024-W00-1")

    def test_invalid_string_bad_day(self):
        with pytest.raises(ValueError):
            IsoWeekDate("2024-W01-0")

    def test_invalid_string_day_8(self):
        with pytest.raises(ValueError):
            IsoWeekDate("2024-W01-8")

    @pytest.mark.parametrize(
        "s",
        [
            "+024-W01-1",
            " 024-W01-1",
            "202𝟙-W01-1",
            "2024-W+1-1",
            "2024-W 1-1",
        ],
    )
    def test_invalid_string_non_digits(self, s):
        with pytest.raises(ValueError):
            IsoWeekDate(s)


class TestAccessors:
    def test_year(self):
        assert IsoWeekDate(2024, 1, MONDAY).year == 2024

    def test_week(self):
        assert IsoWeekDate(2024, 52, FRIDAY).week == 52

    def test_weekday(self):
        assert IsoWeekDate(2024, 1, FRIDAY).weekday == FRIDAY

    @pytest.mark.parametrize(
        "i, wd",
        list(
            enumerate(
                [
                    MONDAY,
                    TUESDAY,
                    WEDNESDAY,
                    THURSDAY,
                    FRIDAY,
                    SATURDAY,
                    SUNDAY,
                ],
                start=1,
            )
        ),
    )
    def test_all_weekdays(self, i, wd):
        iwd = IsoWeekDate(2024, 1, wd)
        assert iwd.weekday == wd
        assert iwd.weekday.value == i

    def test_min_exists(self):
        assert isinstance(IsoWeekDate.MIN, IsoWeekDate)
        assert IsoWeekDate.MIN == IsoWeekDate(1, 1, Weekday.MONDAY)
        assert IsoWeekDate.MIN.date() == Date.MIN

    def test_max_exists(self):
        assert isinstance(IsoWeekDate.MAX, IsoWeekDate)
        assert IsoWeekDate.MAX == IsoWeekDate(9999, 52, Weekday.FRIDAY)
        assert IsoWeekDate.MAX.date() == Date.MAX

    def test_min_le_max(self):
        assert IsoWeekDate.MIN <= IsoWeekDate.MAX


class TestFormatIso:
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

    @pytest.mark.parametrize("basic", [True, False])
    def test_round_trip(self, basic):
        iwd = IsoWeekDate(2004, 53, FRIDAY)
        assert IsoWeekDate.parse_iso(iwd.format_iso(basic=basic)) == iwd

    def test_str(self):
        iwd = IsoWeekDate(2024, 1, MONDAY)
        assert str(iwd) == "2024-W01-1" == iwd.format_iso()

    def test_repr(self):
        assert (
            repr(IsoWeekDate(2024, 1, MONDAY)) == 'IsoWeekDate("2024-W01-1")'
        )


class TestParseIso:
    @pytest.mark.parametrize(
        "s, expect",
        [
            ("2024-W01-1", IsoWeekDate(2024, 1, MONDAY)),
            ("2024W011", IsoWeekDate(2024, 1, MONDAY)),
            ("2023-w52-5", IsoWeekDate(2023, 52, FRIDAY)),
            ("2023w525", IsoWeekDate(2023, 52, FRIDAY)),
        ],
    )
    def test_valid(self, s, expect):
        assert IsoWeekDate.parse_iso(s) == expect

    @pytest.mark.parametrize(
        "s",
        [
            "not-a-date",
            "2024-01-01",  # a calendar date, not a week date
            "2024-W01-8",  # weekday out of range
            "2024-W54-1",  # week out of range
            "2024-W01-\u0661",  # non-ASCII
        ],
    )
    def test_invalid(self, s):
        with pytest.raises(ValueError, match=re.escape(repr(s)) + "|ISO week"):
            IsoWeekDate.parse_iso(s)

    def test_invalid_names_the_format(self):
        with pytest.raises(
            ValueError, match="^invalid ISO 8601 string: 'not-a-date'$"
        ):
            IsoWeekDate.parse_iso("not-a-date")

    def test_non_string(self):
        with pytest.raises((TypeError, AttributeError)):
            IsoWeekDate.parse_iso(20240101)  # type: ignore[arg-type]


class TestEquality:
    def test_equal(self):
        assert IsoWeekDate(2024, 1, MONDAY) == IsoWeekDate(2024, 1, MONDAY)

    def test_not_equal(self):
        assert IsoWeekDate(2024, 1, MONDAY) != IsoWeekDate(2024, 1, TUESDAY)

    def test_not_equal_to_other_type(self):
        assert IsoWeekDate(2024, 1, MONDAY) != "2024-W01-1"  # type: ignore[comparison-overlap]
        assert IsoWeekDate(2024, 1, MONDAY) != (2024, 1, MONDAY)  # type: ignore[comparison-overlap]

    def test_equal_values_same_hash(self):
        a = IsoWeekDate(2024, 1, MONDAY)
        b = IsoWeekDate(2024, 1, MONDAY)
        assert hash(a) == hash(b)

    def test_usable_in_set(self):
        s = {IsoWeekDate(2024, 1, MONDAY), IsoWeekDate(2024, 1, MONDAY)}
        assert len(s) == 1


class TestComparison:
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

    def test_ordering_with_other_type(self):
        d = IsoWeekDate(2024, 1, MONDAY)
        with pytest.raises(TypeError):
            d < "2024-W01-1"  # type: ignore[operator]
        with pytest.raises(TypeError):
            d <= "2024-W01-1"  # type: ignore[operator]
        with pytest.raises(TypeError):
            d > "2024-W01-1"  # type: ignore[operator]
        with pytest.raises(TypeError):
            d >= "2024-W01-1"  # type: ignore[operator]


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

    def test_replace_multiple_fields(self):
        iwd = IsoWeekDate(2024, 1, MONDAY)
        assert iwd.replace(year=2025, week=10, weekday=FRIDAY) == IsoWeekDate(
            2025, 10, FRIDAY
        )

    def test_replace_invalid(self):
        with pytest.raises(ValueError):
            IsoWeekDate(2024, 52, MONDAY).replace(week=53)

    def test_replace_year_makes_week53_invalid(self):
        # 2004 has 53 weeks, 2024 does not
        with pytest.raises(ValueError, match="week must be between 1 and 52"):
            IsoWeekDate(2004, 53, FRIDAY).replace(year=2024)

    @pytest.mark.parametrize(
        "kwargs, match",
        [
            ({"week": 0}, "week must be between 1 and 52"),
            ({"week": 54}, "week must be between 1 and 52"),
            ({"year": 0}, "^invalid date$"),
        ],
    )
    def test_replace_out_of_range(self, kwargs, match):
        with pytest.raises(ValueError, match=match):
            IsoWeekDate(2024, 1, MONDAY).replace(**kwargs)

    def test_replace_invalid_arguments(self):
        iwd = IsoWeekDate(2024, 1, MONDAY)
        with pytest.raises(TypeError):
            iwd.replace(2025)  # type: ignore[call-arg]

        with pytest.raises(TypeError, match="foo"):
            iwd.replace(foo=2025)  # type: ignore[call-arg]

        with pytest.raises(TypeError, match="weekday must be a Weekday"):
            iwd.replace(weekday=1)  # type: ignore[arg-type]

    def test_replace_year_past_gregorian_range(self):
        # The Gregorian date would be in year 10000, which the message
        # must not name: the caller never passed it
        with pytest.raises(ValueError, match="^invalid date$"):
            IsoWeekDate(2021, 52, SUNDAY).replace(year=9999)


class TestCalendarProperties:
    def test_weeks_in_long_year(self):
        assert IsoWeekDate(2004, 1, MONDAY).weeks_in_year() == 53

    def test_weeks_in_short_year(self):
        assert IsoWeekDate(2024, 1, MONDAY).weeks_in_year() == 52


class TestConversion:
    def test_date(self):
        assert IsoWeekDate(2024, 1, MONDAY).date() == Date(2024, 1, 1)

    def test_date_year_boundary(self):
        # Dec 30, 2024 is Monday of ISO week 2025-W01
        assert IsoWeekDate(2025, 1, MONDAY).date() == Date(2024, 12, 30)

    def test_date_end_of_year(self):
        # Dec 28, 2024 is Saturday of ISO week 2024-W52
        assert IsoWeekDate(2024, 52, SATURDAY).date() == Date(2024, 12, 28)

    def test_date_week53(self):
        # 2004-W53-6 (Saturday) = Jan 1, 2005
        assert IsoWeekDate(2004, 53, SATURDAY).date() == Date(2005, 1, 1)

    def test_date_round_trip(self):
        d = Date(2024, 7, 4)
        assert d.iso_week_date().date() == d
