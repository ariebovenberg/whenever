import pickle
import re
from copy import copy, deepcopy
from datetime import (
    datetime as py_datetime,
    timedelta as py_timedelta,
    timezone as py_timezone,
)
from typing import Any
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

import pytest
from hypothesis import given
from hypothesis.strategies import text

from whenever import (
    Date,
    Instant,
    InvalidOffset,
    LocalDateTime,
    OffsetDateTime,
    RepeatedTime,
    SkippedTime,
    SystemDateTime,
    Time,
    ZonedDateTime,
    days,
    hours,
    milliseconds,
    minutes,
    months,
    weeks,
    years,
)

from .common import (
    AlwaysEqual,
    AlwaysLarger,
    AlwaysSmaller,
    NeverEqual,
    system_tz_ams,
    system_tz_nyc,
)


class TestInit:
    def test_unambiguous(self):
        zone = "America/New_York"
        d = ZonedDateTime(2020, 8, 15, 5, 12, 30, nanosecond=450, tz=zone)

        assert d.year == 2020
        assert d.month == 8
        assert d.day == 15
        assert d.hour == 5
        assert d.minute == 12
        assert d.second == 30
        assert d.nanosecond == 450
        assert d.tz == zone

    def test_ambiguous(self):
        kwargs: dict[str, Any] = dict(
            year=2023,
            month=10,
            day=29,
            hour=2,
            minute=15,
            second=30,
            tz="Europe/Amsterdam",
        )

        with pytest.raises(
            RepeatedTime,
            match="2023-10-29 02:15:30 is repeated in timezone 'Europe/Amsterdam'",
        ):
            ZonedDateTime(**kwargs)

        with pytest.raises(
            RepeatedTime,
            match="2023-10-29 02:15:30 is repeated in timezone 'Europe/Amsterdam'",
        ):
            ZonedDateTime(**kwargs, disambiguate="raise")

        assert (
            ZonedDateTime(**kwargs, disambiguate="earlier").offset
            > ZonedDateTime(**kwargs, disambiguate="later").offset
        )
        assert ZonedDateTime(**kwargs, disambiguate="compatible").exact_eq(
            ZonedDateTime(**kwargs, disambiguate="earlier")
        )

    def test_invalid_zone(self):
        with pytest.raises(TypeError):
            ZonedDateTime(
                2020,
                8,
                15,
                5,
                12,
                tz=hours(34),  # type: ignore[arg-type]
            )

        with pytest.raises(ZoneInfoNotFoundError):
            ZonedDateTime(2020, 8, 15, 5, 12, tz="America/Nowhere")

    def test_optionality(self):
        tz = "America/New_York"
        assert (
            ZonedDateTime(2020, 8, 15, 12, tz=tz)
            == ZonedDateTime(2020, 8, 15, 12, 0, tz=tz)
            == ZonedDateTime(2020, 8, 15, 12, 0, 0, tz=tz)
            == ZonedDateTime(2020, 8, 15, 12, 0, 0, nanosecond=0, tz=tz)
            == ZonedDateTime(
                2020,
                8,
                15,
                12,
                0,
                0,
                nanosecond=0,
                tz=tz,
                disambiguate="raise",
            )
        )

    def test_tz_required(self):
        with pytest.raises(TypeError):
            ZonedDateTime(2020, 8, 15, 12)  # type: ignore[call-arg]

    def test_out_of_range_due_to_offset(self):
        with pytest.raises((ValueError, OverflowError), match="range|year"):
            ZonedDateTime(1, 1, 1, tz="Asia/Tokyo")

        with pytest.raises((ValueError, OverflowError), match="range|year"):
            ZonedDateTime(9999, 12, 31, 23, tz="America/New_York")

    def test_invalid(self):
        with pytest.raises(ValueError):
            ZonedDateTime(
                2020,
                8,
                15,
                12,
                8,
                30,
                nanosecond=1_000_000_000,
                tz="Europe/Amsterdam",
            )

    def test_skipped(self):
        kwargs: dict[str, Any] = dict(
            year=2023,
            month=3,
            day=26,
            hour=2,
            minute=15,
            second=30,
            tz="Europe/Amsterdam",
        )
        with pytest.raises(
            SkippedTime,
            match="2023-03-26 02:15:30 is skipped in timezone 'Europe/Amsterdam'",
        ):
            ZonedDateTime(**kwargs)

        with pytest.raises(
            SkippedTime,
            match="2023-03-26 02:15:30 is skipped in timezone 'Europe/Amsterdam'",
        ):
            ZonedDateTime(**kwargs, disambiguate="raise")

        d1 = ZonedDateTime(**kwargs, disambiguate="compatible")
        assert d1.exact_eq(
            ZonedDateTime(2023, 3, 26, 3, 15, 30, tz="Europe/Amsterdam")
        )

        assert ZonedDateTime(**kwargs, disambiguate="later").exact_eq(
            ZonedDateTime(2023, 3, 26, 3, 15, 30, tz="Europe/Amsterdam")
        )
        assert ZonedDateTime(**kwargs, disambiguate="earlier").exact_eq(
            ZonedDateTime(2023, 3, 26, 1, 15, 30, tz="Europe/Amsterdam")
        )


def test_offset():
    d = ZonedDateTime(
        2020, 8, 15, 5, 12, 30, nanosecond=450, tz="America/New_York"
    )
    assert d.offset == hours(-4)


def test_immutable():
    d = ZonedDateTime(2020, 8, 15, tz="Europe/Amsterdam")
    with pytest.raises(AttributeError):
        d.year = 2021  # type: ignore[misc]


def test_date():
    d = ZonedDateTime(2020, 8, 15, 14, tz="Europe/Amsterdam")
    assert d.date() == Date(2020, 8, 15)


def test_time():
    d = ZonedDateTime(2020, 8, 15, 14, 30, 45, tz="Europe/Amsterdam")
    assert d.time() == Time(14, 30, 45)


def test_local():
    d = ZonedDateTime(2020, 8, 15, 13, tz="Europe/Amsterdam")
    assert d.local() == LocalDateTime(2020, 8, 15, 13)
    assert d.replace(disambiguate="later").local() == LocalDateTime(
        2020, 8, 15, 13
    )


class TestWithDate:
    def test_unambiguous(self):
        d = ZonedDateTime(2020, 8, 15, 14, nanosecond=2, tz="Europe/Amsterdam")
        assert d.replace_date(Date(2021, 1, 2), disambiguate="raise").exact_eq(
            ZonedDateTime(2021, 1, 2, 14, nanosecond=2, tz="Europe/Amsterdam")
        )

        # disambiguation required
        with pytest.raises(TypeError, match="disambigua"):
            d.replace_date(Date(2023, 10, 29))  # type: ignore[call-arg]

    def test_fold(self):
        d = ZonedDateTime(2020, 1, 1, 2, 15, 30, tz="Europe/Amsterdam")
        date = Date(2023, 10, 29)

        with pytest.raises(RepeatedTime):
            assert d.replace_date(date, disambiguate="raise")
        assert d.replace_date(date, disambiguate="earlier").exact_eq(
            d.replace(year=2023, month=10, day=29, disambiguate="earlier")
        )
        assert d.replace_date(date, disambiguate="later").exact_eq(
            d.replace(year=2023, month=10, day=29, disambiguate="later")
        )
        assert d.replace_date(date, disambiguate="compatible").exact_eq(
            d.replace(year=2023, month=10, day=29, disambiguate="compatible")
        )

    def test_gap(self):
        d = ZonedDateTime(2020, 1, 1, 2, 15, 30, tz="Europe/Amsterdam")
        date = Date(2023, 3, 26)

        with pytest.raises(SkippedTime):
            assert d.replace_date(date, disambiguate="raise")

        assert d.replace_date(date, disambiguate="earlier").exact_eq(
            d.replace(year=2023, month=3, day=26, disambiguate="earlier")
        )
        assert d.replace_date(date, disambiguate="later").exact_eq(
            d.replace(year=2023, month=3, day=26, disambiguate="later")
        )
        assert d.replace_date(date, disambiguate="compatible").exact_eq(
            d.replace(year=2023, month=3, day=26, disambiguate="compatible")
        )

    def test_invalid(self):
        d = ZonedDateTime(2020, 8, 15, 14, tz="Europe/Amsterdam")
        with pytest.raises((TypeError, AttributeError)):
            d.replace_date(object(), disambiguate="compatible")  # type: ignore[arg-type]

        with pytest.raises(ValueError, match="disambiguate"):
            d.replace_date(Date(2020, 8, 15), disambiguate="foo")  # type: ignore[arg-type]

        with pytest.raises(TypeError, match="got 2|foo"):
            d.replace_date(Date(2020, 8, 15), disambiguate="raise", foo=4)  # type: ignore[call-arg]

        with pytest.raises(TypeError, match="foo"):
            d.replace_date(Date(2020, 8, 15), foo="raise")  # type: ignore[call-arg]

    def test_out_of_range_due_to_offset(self):
        d = ZonedDateTime(2020, 1, 1, tz="Asia/Tokyo")
        with pytest.raises((ValueError, OverflowError), match="range|year"):
            d.replace_date(Date(1, 1, 1), disambiguate="compatible")

        d2 = ZonedDateTime(2020, 1, 1, hour=23, tz="America/New_York")
        with pytest.raises((ValueError, OverflowError), match="range|year"):
            d2.replace_date(Date(9999, 12, 31), disambiguate="compatible")


class TestWithTime:
    def test_unambiguous(self):
        d = ZonedDateTime(2020, 8, 15, 14, tz="Europe/Amsterdam")
        assert d.replace_time(
            Time(1, 2, 3, nanosecond=4_000), disambiguate="raise"
        ).exact_eq(
            ZonedDateTime(
                2020, 8, 15, 1, 2, 3, nanosecond=4_000, tz="Europe/Amsterdam"
            )
        )

        # disambiguation required
        with pytest.raises(TypeError, match="disambigua"):
            d.replace_time(Time(1, 2, 3, nanosecond=4_000))  # type: ignore[call-arg]

    def test_fold(self):
        d = ZonedDateTime(2023, 10, 29, 0, 15, 30, tz="Europe/Amsterdam")
        time = Time(2, 15, 30)

        with pytest.raises(RepeatedTime):
            assert d.replace_time(time, disambiguate="raise")

        assert d.replace_time(time, disambiguate="earlier").exact_eq(
            d.replace(hour=2, minute=15, second=30, disambiguate="earlier")
        )
        assert d.replace_time(time, disambiguate="later").exact_eq(
            d.replace(hour=2, minute=15, second=30, disambiguate="later")
        )
        assert d.replace_time(time, disambiguate="compatible").exact_eq(
            d.replace(hour=2, minute=15, second=30, disambiguate="compatible")
        )

    def test_gap(self):
        d = ZonedDateTime(2023, 3, 26, 0, 15, tz="Europe/Amsterdam")
        time = Time(2, 15)
        with pytest.raises(SkippedTime):
            assert d.replace_time(time, disambiguate="raise")

        assert d.replace_time(time, disambiguate="earlier").exact_eq(
            d.replace(hour=2, minute=15, disambiguate="earlier")
        )
        assert d.replace_time(time, disambiguate="later").exact_eq(
            d.replace(hour=2, minute=15, disambiguate="later")
        )
        assert d.replace_time(time, disambiguate="compatible").exact_eq(
            d.replace(hour=2, minute=15, disambiguate="compatible")
        )

    def test_invalid(self):
        d = ZonedDateTime(2020, 8, 15, 14, tz="Europe/Amsterdam")
        with pytest.raises((TypeError, AttributeError)):
            d.replace_time(object(), disambiguate="later")  # type: ignore[arg-type]

        with pytest.raises(ValueError, match="disambiguate"):
            d.replace_time(Time(1, 2, 3), disambiguate="foo")  # type: ignore[arg-type]

        with pytest.raises(TypeError, match="got 2|foo"):
            d.replace_time(Time(1, 2, 3), disambiguate="raise", foo=4)  # type: ignore[call-arg]

        with pytest.raises(TypeError, match="foo"):
            d.replace_time(Time(1, 2, 3), foo="raise")  # type: ignore[call-arg]

    def test_out_of_range_due_to_offset(self):
        d = ZonedDateTime(1, 1, 1, hour=23, tz="Asia/Tokyo")
        with pytest.raises((ValueError, OverflowError), match="range|year"):
            d.replace_time(Time(1), disambiguate="compatible")

        d2 = ZonedDateTime(9999, 12, 31, hour=2, tz="America/New_York")
        with pytest.raises((ValueError, OverflowError), match="range|year"):
            d2.replace_time(Time(23), disambiguate="compatible")


class TestFormatCommonIso:

    @pytest.mark.parametrize(
        "d, expected",
        [
            (
                ZonedDateTime(
                    2020,
                    8,
                    15,
                    23,
                    12,
                    9,
                    nanosecond=987_654_321,
                    tz="Europe/Amsterdam",
                ),
                "2020-08-15T23:12:09.987654321+02:00[Europe/Amsterdam]",
            ),
            (
                ZonedDateTime(
                    2023,
                    10,
                    29,
                    2,
                    15,
                    30,
                    tz="Europe/Amsterdam",
                    disambiguate="earlier",
                ),
                "2023-10-29T02:15:30+02:00[Europe/Amsterdam]",
            ),
            (
                ZonedDateTime(
                    2023,
                    10,
                    29,
                    2,
                    15,
                    30,
                    tz="Europe/Amsterdam",
                    disambiguate="later",
                ),
                "2023-10-29T02:15:30+01:00[Europe/Amsterdam]",
            ),
            (
                ZonedDateTime(
                    1900,
                    1,
                    1,
                    tz="Europe/Dublin",
                ),
                "1900-01-01T00:00:00-00:25:21[Europe/Dublin]",
            ),
        ],
    )
    def test_common_iso(self, d: ZonedDateTime, expected: str):
        assert str(d) == expected
        assert d.format_common_iso() == expected


class TestEquality:
    def test_same_exact(self):
        a = ZonedDateTime(2020, 8, 15, 12, 8, 30, tz="Europe/Amsterdam")
        b = ZonedDateTime(2020, 8, 15, 12, 8, 30, tz="Europe/Amsterdam")
        assert a == b
        assert hash(a) == hash(b)

    def test_different_timezone(self):
        a = ZonedDateTime(2020, 8, 15, 12, 8, 30, tz="Europe/Amsterdam")

        # same **wall clock** time, different timezone
        b = ZonedDateTime(2020, 8, 15, 12, 8, 30, tz="America/New_York")
        assert a != b
        assert hash(a) != hash(b)

        # same moment, different timezone
        c = ZonedDateTime(2020, 8, 15, 6, 8, 30, tz="America/New_York")
        assert a == c
        assert hash(a) == hash(c)

    def test_different_time(self):
        a = ZonedDateTime(2020, 8, 15, 12, 8, 30, tz="Europe/Amsterdam")
        b = ZonedDateTime(2020, 8, 15, 12, 8, 31, tz="Europe/Amsterdam")
        assert a != b
        assert hash(a) != hash(b)

    def test_different_fold_no_ambiguity(self):
        a = ZonedDateTime(
            2020,
            8,
            15,
            12,
            8,
            30,
            tz="Europe/Amsterdam",
            disambiguate="earlier",
        )
        b = a.replace(disambiguate="later")
        assert a == b
        assert hash(a) == hash(b)

    def test_different_fold_ambiguity(self):
        a = ZonedDateTime(
            2023,
            10,
            29,
            2,
            15,
            30,
            tz="Europe/Amsterdam",
            disambiguate="earlier",
        )
        b = ZonedDateTime(
            2023,
            10,
            29,
            2,
            15,
            30,
            tz="Europe/Amsterdam",
            disambiguate="later",
        )
        assert a != b
        assert hash(a) != hash(b)

    def test_ambiguity_between_different_timezones(self):
        a = ZonedDateTime(
            2023,
            10,
            29,
            2,
            15,
            30,
            tz="Europe/Amsterdam",
            disambiguate="later",
        )
        b = a.to_tz("America/New_York")
        assert a.instant() == b.instant()  # sanity check
        assert hash(a) == hash(b)
        assert a == b

    @system_tz_nyc()
    def test_other_aware(self):
        d: ZonedDateTime | OffsetDateTime | SystemDateTime = ZonedDateTime(
            2023,
            10,
            29,
            2,
            15,
            tz="Europe/Amsterdam",
            disambiguate="earlier",
        )
        assert d == d.instant()  # type: ignore[comparison-overlap]
        assert hash(d) == hash(d.instant())
        assert d != d.instant() + hours(2)  # type: ignore[comparison-overlap]

        assert d == d.to_system_tz()
        assert d != d.to_system_tz().replace(hour=8, disambiguate="raise")

        assert d == d.to_fixed_offset()
        assert hash(d) == hash(d.to_fixed_offset())
        assert d != d.to_fixed_offset().replace(hour=10, ignore_dst=True)

    def test_not_implemented(self):
        d = ZonedDateTime(2020, 8, 15, 12, 8, 30, tz="Europe/Amsterdam")
        assert d == AlwaysEqual()
        assert d != NeverEqual()
        assert not d == NeverEqual()
        assert not d != AlwaysEqual()

        assert d != 42  # type: ignore[comparison-overlap]
        assert not d == 42  # type: ignore[comparison-overlap]
        assert 42 != d  # type: ignore[comparison-overlap]
        assert not 42 == d  # type: ignore[comparison-overlap]
        assert not hours(2) == d  # type: ignore[comparison-overlap]


def test_is_ambiguous():
    assert not ZonedDateTime(
        2020, 8, 15, 12, 8, 30, tz="Europe/Amsterdam"
    ).is_ambiguous()
    assert ZonedDateTime(
        2023,
        10,
        29,
        2,
        15,
        30,
        tz="Europe/Amsterdam",
        disambiguate="earlier",
    ).is_ambiguous()


def test_instant():
    assert ZonedDateTime(
        2020, 8, 15, 12, 8, 30, tz="Europe/Amsterdam"
    ).instant() == Instant.from_utc(2020, 8, 15, 10, 8, 30)
    d = ZonedDateTime(
        2023,
        10,
        29,
        2,
        15,
        30,
        tz="Europe/Amsterdam",
        disambiguate="earlier",
    )
    assert d.instant() == Instant.from_utc(2023, 10, 29, 0, 15, 30)
    assert ZonedDateTime(
        2023, 10, 29, 2, 15, 30, tz="Europe/Amsterdam", disambiguate="later"
    ).instant() == Instant.from_utc(2023, 10, 29, 1, 15, 30)


def test_to_tz():
    assert (
        ZonedDateTime(2020, 8, 15, 12, 8, 30, tz="Europe/Amsterdam")
        .to_tz("America/New_York")
        .exact_eq(ZonedDateTime(2020, 8, 15, 6, 8, 30, tz="America/New_York"))
    )
    ams = ZonedDateTime(
        2023, 10, 29, 2, 15, 30, tz="Europe/Amsterdam", disambiguate="earlier"
    )
    nyc = ZonedDateTime(2023, 10, 28, 20, 15, 30, tz="America/New_York")
    assert ams.to_tz("America/New_York").exact_eq(nyc)
    assert (
        ams.replace(disambiguate="later")
        .to_tz("America/New_York")
        .exact_eq(nyc.replace(hour=21, disambiguate="raise"))
    )
    assert nyc.to_tz("Europe/Amsterdam").exact_eq(ams)
    assert (
        nyc.replace(hour=21, disambiguate="raise")
        .to_tz("Europe/Amsterdam")
        .exact_eq(ams.replace(disambiguate="later"))
    )
    # disambiguation doesn't affect NYC time because there's no ambiguity
    assert (
        nyc.replace(disambiguate="later")
        .to_tz("Europe/Amsterdam")
        .exact_eq(ams)
    )

    # catch local datetimes sliding out of range
    small_zdt = ZonedDateTime(1, 1, 1, tz="Etc/UTC")
    with pytest.raises((ValueError, OverflowError, OSError)):
        small_zdt.to_tz("America/New_York")

    big_zdt = ZonedDateTime(9999, 12, 31, 23, tz="Etc/UTC")
    with pytest.raises((ValueError, OverflowError, OSError)):
        big_zdt.to_tz("Asia/Tokyo")


def test_to_fixed_offset():
    d = ZonedDateTime(2020, 8, 15, 12, 8, 30, tz="Europe/Amsterdam")

    assert d.to_fixed_offset().exact_eq(
        OffsetDateTime(2020, 8, 15, 12, 8, 30, offset=hours(2))
    )
    assert (
        d.replace(month=1, disambiguate="raise")
        .to_fixed_offset()
        .exact_eq(OffsetDateTime(2020, 1, 15, 12, 8, 30, offset=hours(1)))
    )
    assert (
        d.replace(month=1, disambiguate="raise")
        .to_fixed_offset(hours(4))
        .exact_eq(OffsetDateTime(2020, 1, 15, 15, 8, 30, offset=hours(4)))
    )
    assert d.to_fixed_offset(hours(0)).exact_eq(
        OffsetDateTime(2020, 8, 15, 10, 8, 30, offset=hours(0))
    )
    assert d.to_fixed_offset(-4).exact_eq(
        OffsetDateTime(2020, 8, 15, 6, 8, 30, offset=hours(-4))
    )

    # catch local datetimes sliding out of range
    small_zdt = ZonedDateTime(1, 1, 1, tz="Etc/UTC")
    with pytest.raises((ValueError, OverflowError), match="range|year"):
        small_zdt.to_fixed_offset(-3)

    big_zdt = ZonedDateTime(9999, 12, 31, 23, tz="Etc/UTC")
    with pytest.raises((ValueError, OverflowError), match="range|year"):
        big_zdt.to_fixed_offset(4)


@system_tz_ams()
def test_to_system_tz():
    d = ZonedDateTime(2023, 10, 28, 2, 15, tz="Europe/Amsterdam")
    assert d.to_system_tz().exact_eq(SystemDateTime(2023, 10, 28, 2, 15))
    assert (
        d.replace(day=29, disambiguate="later")
        .to_system_tz()
        .exact_eq(SystemDateTime(2023, 10, 29, 2, 15, disambiguate="later"))
    )

    # catch local datetimes sliding out of range
    small_zdt = ZonedDateTime(1, 1, 1, tz="Etc/UTC")
    with system_tz_nyc():
        with pytest.raises((ValueError, OverflowError), match="range|year"):
            small_zdt.to_system_tz()

    big_zdt = ZonedDateTime(9999, 12, 31, 23, tz="Etc/UTC")
    with pytest.raises((ValueError, OverflowError), match="range|year"):
        big_zdt.to_system_tz()


class TestParseCommonIso:
    @pytest.mark.parametrize(
        "s, expect",
        [
            (
                "2020-08-15T12:08:30+02:00[Europe/Amsterdam]",
                ZonedDateTime(2020, 8, 15, 12, 8, 30, tz="Europe/Amsterdam"),
            ),
            (
                "2020-08-15T12:08:30Z[Iceland]",
                ZonedDateTime(2020, 8, 15, 12, 8, 30, tz="Iceland"),
            ),
            # fractions
            (
                "2020-08-15T12:08:30.0232+02:00[Europe/Amsterdam]",
                ZonedDateTime(
                    2020,
                    8,
                    15,
                    12,
                    8,
                    30,
                    nanosecond=23_200_000,
                    tz="Europe/Amsterdam",
                ),
            ),
            # nano precision
            (
                "2020-08-15T12:08:30.000000001+02:00[Europe/Berlin]",
                ZonedDateTime(
                    2020, 8, 15, 12, 8, 30, nanosecond=1, tz="Europe/Berlin"
                ),
            ),
            # second-level offset
            (
                "1900-01-01T23:34:39.01-00:25:21[Europe/Dublin]",
                ZonedDateTime(
                    1900,
                    1,
                    1,
                    23,
                    34,
                    39,
                    nanosecond=10_000_000,
                    tz="Europe/Dublin",
                ),
            ),
            (
                "2020-08-15T12:08:30+02:00:00[Europe/Berlin]",
                ZonedDateTime(2020, 8, 15, 12, 8, 30, tz="Europe/Berlin"),
            ),
            # offset disambiguates
            (
                "2023-10-29T02:15:30+01:00[Europe/Amsterdam]",
                ZonedDateTime(
                    2023,
                    10,
                    29,
                    2,
                    15,
                    30,
                    tz="Europe/Amsterdam",
                    disambiguate="later",
                ),
            ),
            (
                "2023-10-29T02:15:30+02:00[Europe/Amsterdam]",
                ZonedDateTime(
                    2023,
                    10,
                    29,
                    2,
                    15,
                    30,
                    tz="Europe/Amsterdam",
                    disambiguate="earlier",
                ),
            ),
        ],
    )
    def test_valid(self, s, expect):
        assert ZonedDateTime.parse_common_iso(s).exact_eq(expect)

    @pytest.mark.parametrize(
        "s",
        [
            "2020-08-15T12:08:30+02:00",  # no tz
            "2020-08-15T12:08:30[Europe/Amsterdam]",  # no offset
            "2020-08-15T12:08:30+02:00[Europe/Amsterdam",  # mismatched brackets
            "2020-08-15T12:08:30+02:00Europe/Amsterdam]",  # mismatched brackets
            "2020-08-15 12:08:30+02:00[Europe/Amsterdam]",  # wrong separator
            "2020-08-15T12.08:30+02:00[Europe/Amsterdam]",  # wrong separator
            "2020_08-15T12:08:30+02:00[Europe/Amsterdam]",  # wrong separator
            "2020-08-15T12:8:30+02:00[Europe/Amsterdam]",  # unpadded
            "2020-08-32T12:08:30+02:00[Europe/Amsterdam]",  # invalid date
            "2020-08-12T12:68:30+02:00[Europe/Amsterdam]",  # invalid time
            "2020-08-12T12:68:30+99:00[Europe/Amsterdam]",  # invalid offset
            "2020-08-12T12:68:30+14:89[Europe/Amsterdam]",  # invalid offset
            "2020-08-12T12:68:30+14:29:60[Europe/Amsterdam]",  # invalid offset
            "2023-10-29T02:15:30>02:00[Europe/Amsterdam]",  # invalid offset
            " 2023-10-29T02:15:30+02:00[Europe/Amsterdam]",  # leading space
            "2023-10-29T02:15:30+02:00[Europe/Amsterdam] ",  # trailing space
            "2023-10-29T02:15:30+02:00(Europe/Amsterdam)",  # wrong brackets
            "2023-10-29",  # only date
            "02:15:30",  # only time
            "2023-10-29T02:15:30",  # no offset
            "",  # empty
            "garbage",  # garbage
            "2023-10-29T02:15:30.0000000001+02:00[Europe/Amsterdam]",  # overly precise fraction
            "2023-10-29T02:15:30+02:00:00.00[Europe/Amsterdam]",  # subsecond offset
            "2023-10-29T02:15:30+0𝟙:00[Europe/Amsterdam]",
            "2020-08-15T12:08:30.000000001+29:00[Europe/Berlin]",  # out of range offset
        ],
    )
    def test_invalid(self, s):
        with pytest.raises(ValueError, match="format.*" + re.escape(s)):
            ZonedDateTime.parse_common_iso(s)

    def test_invalid_tz(self):
        with pytest.raises(ZoneInfoNotFoundError):
            ZonedDateTime.parse_common_iso(
                "2020-08-15T12:08:30+02:00[Europe/Nowhere]"
            )

        with pytest.raises(ZoneInfoNotFoundError):
            ZonedDateTime.parse_common_iso("2020-08-15T12:08:30Z[X]")

        with pytest.raises((ZoneInfoNotFoundError, ValueError)):
            ZonedDateTime.parse_common_iso(
                f"2023-10-29T02:15:30+02:00[{'X'*9999}]"
            )

        with pytest.raises((ZoneInfoNotFoundError, ValueError)):
            ZonedDateTime.parse_common_iso(
                f"2023-10-29T02:15:30+02:00[{chr(1600)}]",
            )

    @pytest.mark.parametrize(
        "s",
        [
            "0001-01-01T00:15:30+09:00[Etc/GMT-9]",
            "9999-12-31T20:15:30-09:00[Etc/GMT+9]",
        ],
    )
    def test_out_of_range(self, s):
        with pytest.raises((ValueError, OverflowError), match="range|year"):
            ZonedDateTime.parse_common_iso(s)

    def test_offset_timezone_mismatch(self):
        with pytest.raises(InvalidOffset):
            # at the exact DST transition
            ZonedDateTime.parse_common_iso(
                "2023-10-29T02:15:30+03:00[Europe/Amsterdam]"
            )
        with pytest.raises(InvalidOffset):
            # some other time in the year
            ZonedDateTime.parse_common_iso(
                "2020-08-15T12:08:30+01:00:01[Europe/Amsterdam]"
            )

    @given(text())
    def test_fuzzing(self, s: str):
        with pytest.raises(
            ValueError,
            match=r"Invalid format.*" + re.escape(repr(s)),
        ):
            ZonedDateTime.parse_common_iso(s)


class TestTimestamp:

    def test_default_seconds(self):
        assert ZonedDateTime(1970, 1, 1, tz="Iceland").timestamp() == 0
        assert (
            ZonedDateTime(
                2020, 8, 15, 8, 8, 30, nanosecond=45_123, tz="America/New_York"
            ).timestamp()
            == 1_597_493_310
        )

        ambiguous = ZonedDateTime(
            2023,
            10,
            29,
            2,
            15,
            30,
            tz="Europe/Amsterdam",
            disambiguate="earlier",
        )
        assert (
            ambiguous.timestamp()
            != ambiguous.replace(disambiguate="later").timestamp()
        )

    def test_millis(self):
        assert ZonedDateTime(1970, 1, 1, tz="Iceland").timestamp_millis() == 0
        assert (
            ZonedDateTime(
                2020,
                8,
                15,
                8,
                8,
                30,
                nanosecond=45_923_789,
                tz="America/New_York",
            ).timestamp_millis()
            == 1_597_493_310_045
        )

        ambiguous = ZonedDateTime(
            2023,
            10,
            29,
            2,
            15,
            30,
            tz="Europe/Amsterdam",
            disambiguate="earlier",
        )
        assert (
            ambiguous.timestamp_millis()
            != ambiguous.replace(disambiguate="later").timestamp_millis()
        )

    def test_nanos(self):
        assert ZonedDateTime(1970, 1, 1, tz="Iceland").timestamp_nanos() == 0
        assert (
            ZonedDateTime(
                2020,
                8,
                15,
                8,
                8,
                30,
                nanosecond=45_123_789,
                tz="America/New_York",
            ).timestamp_nanos()
            == 1_597_493_310_045_123_789
        )

        ambiguous = ZonedDateTime(
            2023,
            10,
            29,
            2,
            15,
            30,
            tz="Europe/Amsterdam",
            disambiguate="earlier",
        )
        assert (
            ambiguous.timestamp_nanos()
            != ambiguous.replace(disambiguate="later").timestamp_nanos()
        )


class TestFromTimestamp:

    @pytest.mark.parametrize(
        "method, factor",
        [
            (ZonedDateTime.from_timestamp, 1),
            (ZonedDateTime.from_timestamp_millis, 1_000),
            (ZonedDateTime.from_timestamp_nanos, 1_000_000_000),
        ],
    )
    def test_all(self, method, factor):
        assert method(0, tz="Iceland").exact_eq(
            ZonedDateTime(1970, 1, 1, tz="Iceland")
        )
        assert method(1_597_493_310 * factor, tz="America/Nuuk").exact_eq(
            ZonedDateTime(2020, 8, 15, 10, 8, 30, tz="America/Nuuk")
        )
        with pytest.raises((OSError, OverflowError, ValueError)):
            method(1_000_000_000_000_000_000 * factor, tz="America/Nuuk")

        with pytest.raises((OSError, OverflowError, ValueError)):
            method(-1_000_000_000_000_000_000 * factor, tz="America/Nuuk")

        with pytest.raises(TypeError):
            method(0, tz=3)

        with pytest.raises(TypeError):
            method("0", tz="America/New_York")

        with pytest.raises(ZoneInfoNotFoundError):
            method(0, tz="America/Nowhere")

        with pytest.raises(TypeError, match="got 3|foo"):
            method(0, tz="America/New_York", foo="bar")

        with pytest.raises(TypeError, match="positional|ts"):
            method(ts=0, tz="America/New_York")

        with pytest.raises(TypeError):
            method(0, foo="bar")

        with pytest.raises(TypeError):
            method(0)

        with pytest.raises(TypeError):
            method(0, "bar")

        assert ZonedDateTime.from_timestamp_millis(
            -4, tz="America/Nuuk"
        ).instant() == Instant.from_timestamp(0) - milliseconds(4)

        assert ZonedDateTime.from_timestamp_nanos(
            -4, tz="America/Nuuk"
        ).instant() == Instant.from_timestamp(0).subtract(nanoseconds=4)

    def test_nanos(self):
        assert ZonedDateTime.from_timestamp_nanos(
            1_597_493_310_123_456_789, tz="America/Nuuk"
        ).exact_eq(
            ZonedDateTime(
                2020,
                8,
                15,
                10,
                8,
                30,
                nanosecond=123_456_789,
                tz="America/Nuuk",
            )
        )

    def test_millis(self):
        assert ZonedDateTime.from_timestamp_millis(
            1_597_493_310_123, tz="America/Nuuk"
        ).exact_eq(
            ZonedDateTime(
                2020,
                8,
                15,
                10,
                8,
                30,
                nanosecond=123_000_000,
                tz="America/Nuuk",
            )
        )

    def test_float(self):
        assert ZonedDateTime.from_timestamp(
            1.0,
            tz="America/New_York",
        ).exact_eq(
            ZonedDateTime.from_timestamp(
                1,
                tz="America/New_York",
            )
        )

        assert ZonedDateTime.from_timestamp(
            1.000_000_001,
            tz="America/New_York",
        ).exact_eq(
            ZonedDateTime.from_timestamp(
                1,
                tz="America/New_York",
            ).add(
                nanoseconds=1,
            )
        )

        assert ZonedDateTime.from_timestamp(
            -9.000_000_100,
            tz="America/New_York",
        ).exact_eq(
            ZonedDateTime.from_timestamp(
                -9,
                tz="America/New_York",
            ).subtract(
                nanoseconds=100,
            )
        )

        with pytest.raises((ValueError, OverflowError)):
            ZonedDateTime.from_timestamp(9e200, tz="America/New_York")

        with pytest.raises((ValueError, OverflowError)):
            ZonedDateTime.from_timestamp(
                float(Instant.MAX.timestamp()) + 0.99999999,
                tz="America/New_York",
            )

        with pytest.raises((ValueError, OverflowError)):
            ZonedDateTime.from_timestamp(float("inf"), tz="America/New_York")

        with pytest.raises((ValueError, OverflowError)):
            ZonedDateTime.from_timestamp(float("nan"), tz="America/New_York")


def test_repr():
    d = ZonedDateTime(
        2020, 8, 15, 23, 12, 9, nanosecond=9_876_543, tz="Australia/Darwin"
    )
    assert (
        repr(d) == "ZonedDateTime(2020-08-15 23:12:09.009876543"
        "+09:30[Australia/Darwin])"
    )
    assert (
        repr(ZonedDateTime(2020, 8, 15, 23, 12, tz="Iceland"))
        == "ZonedDateTime(2020-08-15 23:12:00+00:00[Iceland])"
    )


class TestComparison:
    def test_different_timezones(self):
        d = ZonedDateTime(2020, 8, 15, 15, 12, 9, tz="Asia/Kolkata")
        later = ZonedDateTime(2020, 8, 15, 14, tz="Europe/Amsterdam")

        assert d < later
        assert d <= later
        assert later > d
        assert later >= d
        assert not d > later
        assert not d >= later
        assert not later < d
        assert not later <= d

    def test_same_timezone_ambiguity(self):
        d = ZonedDateTime(
            2023,
            10,
            29,
            2,
            15,
            30,
            tz="Europe/Amsterdam",
            disambiguate="earlier",
        )
        later = ZonedDateTime(
            2023,
            10,
            29,
            2,
            15,
            30,
            tz="Europe/Amsterdam",
            disambiguate="later",
        )
        assert d < later
        assert d <= later
        assert later > d
        assert later >= d
        assert not d > later
        assert not d >= later
        assert not later < d
        assert not later <= d

    def test_different_timezone_same_time(self):
        d = ZonedDateTime(
            2023,
            10,
            29,
            2,
            15,
            30,
            tz="Europe/Amsterdam",
            disambiguate="earlier",
        )
        other = d.to_tz("America/New_York")
        assert not d < other
        assert d <= other
        assert not other > d
        assert other >= d
        assert not d > other
        assert d >= other
        assert not other < d
        assert other <= d

    def test_instant(self):
        d = ZonedDateTime(
            2023, 10, 29, 2, 30, tz="Europe/Amsterdam", disambiguate="later"
        )

        inst_eq = d.instant()
        inst_lt = inst_eq - minutes(1)
        inst_gt = inst_eq + minutes(1)

        assert d >= inst_eq
        assert d <= inst_eq
        assert not d > inst_eq
        assert not d < inst_eq

        assert d > inst_lt
        assert d >= inst_lt
        assert not d < inst_lt
        assert not d <= inst_lt

        assert d < inst_gt
        assert d <= inst_gt
        assert not d > inst_gt
        assert not d >= inst_gt

    def test_offset(self):
        d = ZonedDateTime(
            2023, 10, 29, 2, 30, tz="Europe/Amsterdam", disambiguate="later"
        )

        offset_eq = d.to_fixed_offset()
        offset_lt = offset_eq.replace(minute=29, ignore_dst=True)
        offset_gt = offset_eq.replace(minute=31, ignore_dst=True)

        assert d >= offset_eq
        assert d <= offset_eq
        assert not d > offset_eq
        assert not d < offset_eq

        assert d > offset_lt
        assert d >= offset_lt
        assert not d < offset_lt
        assert not d <= offset_lt

        assert d < offset_gt
        assert d <= offset_gt
        assert not d > offset_gt
        assert not d >= offset_gt

    def test_system_tz(self):
        d = ZonedDateTime(
            2023, 10, 29, 2, 30, tz="Europe/Amsterdam", disambiguate="earlier"
        )

        sys_eq = d.to_system_tz()
        sys_lt = sys_eq.replace(minute=29, disambiguate="earlier")
        sys_gt = sys_eq.replace(minute=31, disambiguate="earlier")

        assert d >= sys_eq
        assert d <= sys_eq
        assert not d > sys_eq
        assert not d < sys_eq

        assert d > sys_lt
        assert d >= sys_lt
        assert not d < sys_lt
        assert not d <= sys_lt

        assert d < sys_gt
        assert d <= sys_gt
        assert not d > sys_gt
        assert not d >= sys_gt

    def test_notimplemented(self):
        d = ZonedDateTime(2020, 8, 15, tz="Europe/Amsterdam")
        assert d < AlwaysLarger()
        assert d <= AlwaysLarger()
        assert not d > AlwaysLarger()
        assert not d >= AlwaysLarger()
        assert not d < AlwaysSmaller()
        assert not d <= AlwaysSmaller()
        assert d > AlwaysSmaller()
        assert d >= AlwaysSmaller()

        with pytest.raises(TypeError):
            d < 42  # type: ignore[operator]
        with pytest.raises(TypeError):
            d <= 42  # type: ignore[operator]
        with pytest.raises(TypeError):
            d > 42  # type: ignore[operator]
        with pytest.raises(TypeError):
            d >= 42  # type: ignore[operator]
        with pytest.raises(TypeError):
            42 < d  # type: ignore[operator]
        with pytest.raises(TypeError):
            42 <= d  # type: ignore[operator]
        with pytest.raises(TypeError):
            42 > d  # type: ignore[operator]
        with pytest.raises(TypeError):
            42 >= d  # type: ignore[operator]


def test_py_datetime():
    d = ZonedDateTime(
        2020, 8, 15, 23, 12, 9, nanosecond=987_654_999, tz="Europe/Amsterdam"
    )
    assert d.py_datetime() == py_datetime(
        2020, 8, 15, 23, 12, 9, 987_654, tzinfo=ZoneInfo("Europe/Amsterdam")
    )

    # ambiguous time
    d2 = ZonedDateTime(
        2023,
        10,
        29,
        2,
        15,
        tz="Europe/Amsterdam",
        disambiguate="earlier",
    )
    assert d2.py_datetime().fold == 0
    assert d2.replace(disambiguate="later").py_datetime().fold == 1


def test_from_py_datetime():
    d = py_datetime(
        2020, 8, 15, 23, 12, 9, 987_654, tzinfo=ZoneInfo("Europe/Paris")
    )
    assert ZonedDateTime.from_py_datetime(d).exact_eq(
        ZonedDateTime(
            2020, 8, 15, 23, 12, 9, nanosecond=987_654_000, tz="Europe/Paris"
        )
    )

    # subclass
    class MyDatetime(py_datetime):
        pass

    assert ZonedDateTime.from_py_datetime(
        MyDatetime(
            2020, 8, 15, 23, 12, 9, 987_654, tzinfo=ZoneInfo("Europe/Paris")
        )
    ).exact_eq(
        ZonedDateTime(
            2020, 8, 15, 23, 12, 9, nanosecond=987_654_000, tz="Europe/Paris"
        )
    )

    # wrong tzinfo class
    d2 = d.replace(tzinfo=py_timezone.utc)
    with pytest.raises(ValueError, match="datetime.timezone"):
        ZonedDateTime.from_py_datetime(d2)

    # ZoneInfo subclass also not allowed
    class MyZoneInfo(ZoneInfo):
        pass

    with pytest.raises(ValueError, match="ZoneInfo.*MyZoneInfo"):
        ZonedDateTime.from_py_datetime(
            py_datetime(
                2020,
                8,
                15,
                23,
                12,
                9,
                987_654,
                tzinfo=MyZoneInfo("Europe/Paris"),
            )
        )

    # naive
    with pytest.raises(ValueError, match="None"):
        ZonedDateTime.from_py_datetime(py_datetime(2020, 3, 4))

    # skipped time
    assert ZonedDateTime.from_py_datetime(
        py_datetime(
            2023, 3, 26, 2, 15, 30, tzinfo=ZoneInfo("Europe/Amsterdam")
        )
    ).exact_eq(ZonedDateTime(2023, 3, 26, 3, 15, 30, tz="Europe/Amsterdam"))
    assert ZonedDateTime.from_py_datetime(
        py_datetime(
            2023, 3, 26, 2, 15, 30, fold=1, tzinfo=ZoneInfo("Europe/Amsterdam")
        )
    ).exact_eq(ZonedDateTime(2023, 3, 26, 1, 15, 30, tz="Europe/Amsterdam"))

    # ambiguous time
    assert ZonedDateTime.from_py_datetime(
        py_datetime(
            2023, 10, 29, 2, 15, 30, tzinfo=ZoneInfo("Europe/Amsterdam")
        )
    ).exact_eq(
        ZonedDateTime(
            2023,
            10,
            29,
            2,
            15,
            30,
            tz="Europe/Amsterdam",
            disambiguate="earlier",
        )
    )
    assert ZonedDateTime.from_py_datetime(
        py_datetime(
            2023,
            10,
            29,
            2,
            15,
            30,
            fold=1,
            tzinfo=ZoneInfo("Europe/Amsterdam"),
        )
    ).exact_eq(
        ZonedDateTime(
            2023,
            10,
            29,
            2,
            15,
            30,
            tz="Europe/Amsterdam",
            disambiguate="later",
        )
    )

    # out-of-range
    with pytest.raises((ValueError, OverflowError), match="range|year"):
        ZonedDateTime.from_py_datetime(
            py_datetime(1, 1, 1, tzinfo=ZoneInfo("Asia/Kolkata"))
        )


def test_now():
    now = ZonedDateTime.now("Iceland")
    assert now.tz == "Iceland"
    py_now = py_datetime.now(ZoneInfo("Iceland"))
    assert py_now - now.py_datetime() < py_timedelta(seconds=1)


class TestExactEquality:
    def test_same_exact(self):
        a = ZonedDateTime(2020, 8, 15, 12, 8, 30, tz="Europe/Amsterdam")
        b = ZonedDateTime(2020, 8, 15, 12, 8, 30, tz="Europe/Amsterdam")
        assert a.exact_eq(b)

    def test_different_zones(self):
        a = ZonedDateTime(
            2020, 8, 15, 12, 43, nanosecond=1, tz="Europe/Amsterdam"
        )
        b = a.to_tz("America/New_York")
        assert a == b
        assert not a.exact_eq(b)

    def test_same_timezone_ambiguity(self):
        a = ZonedDateTime(
            2023,
            10,
            29,
            2,
            15,
            nanosecond=1,
            tz="Europe/Amsterdam",
            disambiguate="earlier",
        )
        b = a.replace(disambiguate="later")
        assert a != b
        assert not a.exact_eq(b)

    def test_same_ambiguous(self):
        a = ZonedDateTime(
            2023,
            10,
            29,
            2,
            15,
            nanosecond=1,
            tz="Europe/Amsterdam",
            disambiguate="earlier",
        )
        b = a.replace(disambiguate="earlier")
        assert a.exact_eq(b)

    def test_same_unambiguous(self):
        a = ZonedDateTime(
            2020, 8, 15, 12, 43, nanosecond=1, tz="Europe/Amsterdam"
        )
        b = a.replace(disambiguate="later")
        assert a.exact_eq(b)
        assert a.exact_eq(b.replace(disambiguate="later"))

    def test_invalid(self):
        a = ZonedDateTime(2020, 8, 15, 12, 8, 30, tz="Europe/Amsterdam")
        with pytest.raises((TypeError, AttributeError)):
            a.exact_eq(42)  # type: ignore[arg-type]


class TestReplace:
    def test_basics(self):
        d = ZonedDateTime(
            2020, 8, 15, 23, 12, 9, nanosecond=987_654, tz="Europe/Amsterdam"
        )
        assert d.replace(year=2021, disambiguate="raise").exact_eq(
            ZonedDateTime(
                2021,
                8,
                15,
                23,
                12,
                9,
                nanosecond=987_654,
                tz="Europe/Amsterdam",
            )
        )
        assert d.replace(month=9, disambiguate="raise").exact_eq(
            ZonedDateTime(
                2020,
                9,
                15,
                23,
                12,
                9,
                nanosecond=987_654,
                tz="Europe/Amsterdam",
            )
        )
        assert d.replace(day=16, disambiguate="raise").exact_eq(
            ZonedDateTime(
                2020,
                8,
                16,
                23,
                12,
                9,
                nanosecond=987_654,
                tz="Europe/Amsterdam",
            )
        )
        assert d.replace(hour=0, disambiguate="raise").exact_eq(
            ZonedDateTime(
                2020,
                8,
                15,
                0,
                12,
                9,
                nanosecond=987_654,
                tz="Europe/Amsterdam",
            )
        )
        assert d.replace(minute=0, disambiguate="raise").exact_eq(
            ZonedDateTime(
                2020,
                8,
                15,
                23,
                0,
                9,
                nanosecond=987_654,
                tz="Europe/Amsterdam",
            )
        )
        assert d.replace(second=0, disambiguate="raise").exact_eq(
            ZonedDateTime(
                2020,
                8,
                15,
                23,
                12,
                0,
                nanosecond=987_654,
                tz="Europe/Amsterdam",
            )
        )
        assert d.replace(nanosecond=0, disambiguate="raise").exact_eq(
            ZonedDateTime(
                2020, 8, 15, 23, 12, 9, nanosecond=0, tz="Europe/Amsterdam"
            )
        )
        assert d.replace(tz="Iceland", disambiguate="raise").exact_eq(
            ZonedDateTime(
                2020, 8, 15, 23, 12, 9, nanosecond=987_654, tz="Iceland"
            )
        )

    def test_invalid(self):
        d = ZonedDateTime(2020, 8, 15, tz="Europe/Amsterdam")

        with pytest.raises(TypeError, match="tzinfo"):
            d.replace(tzinfo=py_timezone.utc, disambiguate="compatible")  # type: ignore[call-arg]

        with pytest.raises(TypeError, match="fold"):
            d.replace(fold=1, disambiguate="compatible")  # type: ignore[call-arg]

        with pytest.raises(TypeError, match="foo"):
            d.replace(foo="bar", disambiguate="compatible")  # type: ignore[call-arg]

        with pytest.raises(ZoneInfoNotFoundError, match="Nowhere"):
            d.replace(tz="Nowhere", disambiguate="compatible")

        with pytest.raises(ValueError, match="date|day"):
            d.replace(year=2023, month=2, day=29, disambiguate="compatible")

        with pytest.raises(ValueError, match="nano|time"):
            d.replace(nanosecond=1_000_000_000, disambiguate="compatible")

        # disambiguation required
        with pytest.raises(TypeError, match="disambigua"):
            d.replace(hour=12)  # type: ignore[call-arg]

    def test_disambiguate_ambiguous(self):
        d = ZonedDateTime(
            2023,
            10,
            29,
            2,
            15,
            30,
            tz="Europe/Amsterdam",
            disambiguate="earlier",
        )
        with pytest.raises(
            RepeatedTime,
            match="2023-10-29 02:15:30 is repeated in timezone 'Europe/Amsterdam'",
        ):
            d.replace(disambiguate="raise")

        assert d.replace(disambiguate="later").exact_eq(
            ZonedDateTime(
                2023,
                10,
                29,
                2,
                15,
                30,
                tz="Europe/Amsterdam",
                disambiguate="later",
            )
        )
        assert d.replace(disambiguate="earlier").exact_eq(d)
        assert d.replace(disambiguate="compatible").exact_eq(d)

        with pytest.raises(RepeatedTime):
            d.replace(disambiguate="raise")

    def test_nonexistent(self):
        d = ZonedDateTime(2023, 3, 26, 1, 15, 30, tz="Europe/Amsterdam")
        with pytest.raises(
            SkippedTime,
            match="2023-03-26 02:15:30 is skipped in timezone 'Europe/Amsterdam'",
        ):
            d.replace(hour=2, disambiguate="raise")

        assert d.replace(hour=2, disambiguate="earlier").exact_eq(
            ZonedDateTime(
                2023,
                3,
                26,
                2,
                15,
                30,
                tz="Europe/Amsterdam",
                disambiguate="earlier",
            )
        )

        assert d.replace(hour=2, disambiguate="later").exact_eq(
            ZonedDateTime(
                2023,
                3,
                26,
                2,
                15,
                30,
                tz="Europe/Amsterdam",
                disambiguate="later",
            )
        )

        assert d.replace(hour=2, disambiguate="compatible").exact_eq(
            ZonedDateTime(
                2023,
                3,
                26,
                2,
                15,
                30,
                tz="Europe/Amsterdam",
                disambiguate="compatible",
            )
        )

    def test_out_of_range(self):
        d = ZonedDateTime(1, 1, 1, tz="America/New_York")

        with pytest.raises((ValueError, OverflowError), match="range|year"):
            d.replace(tz="Europe/Amsterdam", disambiguate="compatible")

        with pytest.raises((ValueError, OverflowError), match="range|year"):
            d.replace(
                year=9999, month=12, day=31, hour=23, disambiguate="compatible"
            )


class TestShiftTimeUnits:
    def test_zero(self):
        d = ZonedDateTime(
            2020, 8, 15, 23, 12, 9, nanosecond=987_654, tz="Europe/Amsterdam"
        )
        assert (d + hours(0)).exact_eq(d)

        # the same with the method
        assert d.add().exact_eq(d)

        # the same with subtraction
        assert (d - hours(0)).exact_eq(d)
        assert d.subtract().exact_eq(d)

    def test_ambiguous_plus_zero(self):
        d = ZonedDateTime(
            2023,
            10,
            29,
            2,
            15,
            30,
            disambiguate="earlier",
            tz="Europe/Amsterdam",
        )
        assert (d + hours(0)).exact_eq(d)
        assert (d.replace(disambiguate="later") + hours(0)).exact_eq(
            d.replace(disambiguate="later")
        )

        # the equivalent with the method
        assert d.add(hours=0).exact_eq(d)
        assert (
            d.replace(disambiguate="later")
            .add(hours=0)
            .exact_eq(d.replace(disambiguate="later"))
        )

        # equivalent with subtraction
        assert (d - hours(0)).exact_eq(d)
        assert d.subtract(hours=0).exact_eq(d)

    @system_tz_ams()
    def test_accounts_for_dst(self):
        d = ZonedDateTime(
            2023,
            10,
            29,
            2,
            15,
            30,
            disambiguate="earlier",
            tz="Europe/Amsterdam",
        )
        assert (d + hours(24)).exact_eq(
            ZonedDateTime(2023, 10, 30, 1, 15, 30, tz="Europe/Amsterdam")
        )
        assert (d.replace(disambiguate="later") + hours(24)).exact_eq(
            ZonedDateTime(2023, 10, 30, 2, 15, 30, tz="Europe/Amsterdam")
        )

        # the equivalent with the method (kwargs)
        assert d.add(hours=24).exact_eq(d + hours(24))
        assert (
            d.replace(disambiguate="later")
            .add(hours=24)
            .exact_eq(d.replace(disambiguate="later") + hours(24))
        )

        # equivalent with method (arg)
        assert d.add(hours(24)).exact_eq(d + hours(24))
        assert (
            d.replace(disambiguate="later")
            .add(hours(24))
            .exact_eq(d.replace(disambiguate="later") + hours(24))
        )

        # equivalent with subtraction
        assert (d - hours(-24)).exact_eq(
            ZonedDateTime(2023, 10, 30, 1, 15, 30, tz="Europe/Amsterdam")
        )
        assert d.subtract(hours=-24).exact_eq(d + hours(24))
        assert (
            d.replace(disambiguate="later")
            .subtract(hours=-24)
            .exact_eq(d.replace(disambiguate="later") + hours(24))
        )

    @system_tz_ams()
    def test_out_of_range(self):
        d = ZonedDateTime(2020, 8, 15, tz="Africa/Abidjan")

        with pytest.raises((ValueError, OverflowError), match="range|year"):
            d + hours(24 * 366 * 8_000)

        # the equivalent with the method
        with pytest.raises((ValueError, OverflowError), match="range|year"):
            d.add(hours=24 * 366 * 8_000)

    @system_tz_ams()
    def test_not_implemented(self):
        d = ZonedDateTime(2020, 8, 15, tz="Asia/Tokyo")
        with pytest.raises(TypeError, match="unsupported operand type"):
            d + 42  # type: ignore[operator]

        with pytest.raises(TypeError, match="unsupported operand type"):
            d - 42  # type: ignore[operator]

        with pytest.raises(TypeError, match="unsupported operand type"):
            42 + d  # type: ignore[operator]

        with pytest.raises(TypeError, match="unsupported operand type"):
            42 - d  # type: ignore[operator]

        with pytest.raises(TypeError, match="unsupported operand type"):
            years(1) + d  # type: ignore[operator]

        with pytest.raises(TypeError, match="unsupported operand type"):
            years(1) - d  # type: ignore[operator]

        with pytest.raises(TypeError, match="unsupported operand type"):
            d + d  # type: ignore[operator]

        with pytest.raises((TypeError, AttributeError)):
            d.add(4)  # type: ignore[call-overload]

        # mix args/kwargs
        with pytest.raises(TypeError):
            d.add(hours(34), seconds=3)  # type: ignore[call-overload]

        # other types of delta: recommend use the method
        with pytest.raises(TypeError, match="ambigu.*add"):
            d + months(1)  # type: ignore[operator]


class TestShiftDateUnits:

    def test_zero(self):
        d = ZonedDateTime(
            2020, 8, 15, 23, 12, 9, nanosecond=987_654_321, tz="Asia/Tokyo"
        )
        assert d.add(days=0, disambiguate="raise").exact_eq(d)
        assert d.add().exact_eq(d)

        # same with subtraction
        assert d.subtract(days=0, disambiguate="raise").exact_eq(d)

        # disambiguate is required
        with pytest.raises(TypeError, match="disambiguat"):
            d.add(days=1)  # type: ignore[call-overload]

    def test_simple_date(self):
        d = ZonedDateTime(
            2020,
            8,
            15,
            23,
            12,
            9,
            nanosecond=987_654_321,
            tz="Australia/Sydney",
        )
        assert d.add(days=1, disambiguate="raise").exact_eq(
            d.replace(day=16, disambiguate="raise")
        )
        assert d.add(years=1, weeks=2, days=-2, disambiguate="raise").exact_eq(
            d.replace(year=2021, day=27, disambiguate="raise")
        )

        # same with subtraction
        assert d.subtract(days=1, disambiguate="raise").exact_eq(
            d.replace(day=14, disambiguate="raise")
        )
        assert d.subtract(
            years=1, weeks=2, days=-2, disambiguate="raise"
        ).exact_eq(d.replace(year=2019, day=3, disambiguate="raise"))

        assert d.add(years=1, weeks=2, days=-2, disambiguate="raise").exact_eq(
            d.replace(year=2021, day=27, disambiguate="raise")
        )
        # same with arg
        assert d.add(
            years(1) + weeks(2) + days(-2), disambiguate="raise"
        ).exact_eq(d.add(years=1, weeks=2, days=-2, disambiguate="raise"))
        assert d.add(
            years(1) + weeks(2) + hours(2), disambiguate="raise"
        ).exact_eq(d.add(years=1, weeks=2, hours=2, disambiguate="raise"))

    def test_ambiguity(self):
        d = ZonedDateTime(
            2023,
            10,
            29,
            2,
            15,
            30,
            disambiguate="later",
            tz="Europe/Berlin",
        )
        assert d.add(days=0, disambiguate="raise").exact_eq(d)
        assert d.add(days=7, weeks=-1, disambiguate="raise").exact_eq(d)
        assert d.add(days=1, disambiguate="raise").exact_eq(
            d.replace(day=30, disambiguate="raise")
        )
        assert d.add(days=6, disambiguate="raise").exact_eq(
            d.replace(month=11, day=4, disambiguate="raise")
        )
        assert d.replace(disambiguate="earlier").add(hours=1).exact_eq(d)

        # transition to another fold
        assert d.add(years=1, days=-2, disambiguate="compatible").exact_eq(
            d.replace(year=2024, day=27, disambiguate="earlier")
        )

        # transition to a gap
        assert d.add(months=5, days=2, disambiguate="compatible").exact_eq(
            d.replace(year=2024, month=3, day=31, disambiguate="later")
        )

        # transition over a gap
        assert d.add(
            months=5, days=2, hours=2, disambiguate="compatible"
        ).exact_eq(
            d.replace(year=2024, month=3, day=31, hour=5, disambiguate="raise")
        )
        assert d.add(
            months=5, days=2, hours=-1, disambiguate="compatible"
        ).exact_eq(
            d.replace(year=2024, month=3, day=31, disambiguate="earlier")
        )

        # same with subtraction
        assert d.subtract(days=0, disambiguate="raise").exact_eq(d)
        assert d.subtract(days=7, weeks=-1, disambiguate="raise").exact_eq(d)
        assert d.subtract(days=1, disambiguate="raise").exact_eq(
            d.replace(day=28, disambiguate="raise")
        )

    def test_out_of_bounds_min(self):
        d = ZonedDateTime(2000, 1, 1, tz="Europe/Amsterdam")
        with pytest.raises((ValueError, OverflowError), match="range|year"):
            d.add(years=-1999, disambiguate="compatible")

    def test_out_of_bounds_max(self):
        d = ZonedDateTime(2000, 12, 31, hour=23, tz="America/New_York")
        with pytest.raises((ValueError, OverflowError), match="range|year"):
            d.add(years=7999, disambiguate="compatible")


class TestDifference:

    def test_simple(self):
        d = ZonedDateTime(
            2023, 10, 29, 5, tz="Europe/Amsterdam", disambiguate="earlier"
        )
        other = ZonedDateTime(
            2023, 10, 28, 3, nanosecond=4_000_000, tz="Europe/Amsterdam"
        )
        assert d - other == (hours(27) - milliseconds(4))
        assert other - d == (hours(-27) + milliseconds(4))

        # same with the method
        assert d.difference(other) == d - other
        assert other.difference(d) == other - d

    def test_amibiguous(self):
        d = ZonedDateTime(
            2023,
            10,
            29,
            2,
            15,
            tz="Europe/Amsterdam",
            disambiguate="earlier",
        )
        other = ZonedDateTime(2023, 10, 28, 3, 15, tz="Europe/Amsterdam")
        assert d - other == hours(23)
        assert d.replace(disambiguate="later") - other == hours(24)
        assert other - d == hours(-23)
        assert other - d.replace(disambiguate="later") == hours(-24)

        # same with the method
        assert d.difference(other) == d - other

    def test_instant(self):
        d = ZonedDateTime(
            2023, 10, 29, 2, tz="Europe/Amsterdam", disambiguate="earlier"
        )
        other = Instant.from_utc(2023, 10, 28, 20)
        assert d - other == hours(4)
        assert d.replace(disambiguate="later") - other == hours(5)

        # same with the method
        assert d.difference(other) == d - other

    def test_offset(self):
        d = ZonedDateTime(
            2023, 10, 29, 2, tz="Europe/Amsterdam", disambiguate="earlier"
        )
        other = OffsetDateTime(2023, 10, 28, 20, offset=hours(1))
        assert d - other == hours(5)
        assert d.replace(disambiguate="later") - other == hours(6)

        # same with the method
        assert d.difference(other) == d - other

    @system_tz_nyc()
    def test_system_tz(self):
        d = ZonedDateTime(
            2023, 10, 29, 2, tz="Europe/Amsterdam", disambiguate="earlier"
        )
        other = SystemDateTime(2023, 10, 28, 19)
        assert d - other == hours(1)
        assert d.replace(disambiguate="later") - other == hours(2)

        # same with the method
        assert d.difference(other) == d - other


def test_pickle():
    d = ZonedDateTime(
        2020, 8, 15, 23, 12, 9, nanosecond=987_654, tz="Europe/Amsterdam"
    )
    dumped = pickle.dumps(d)
    assert len(dumped) <= len(pickle.dumps(d.py_datetime()))
    assert pickle.loads(pickle.dumps(d)).exact_eq(d)


def test_old_pickle_data_remains_unpicklable():
    # Don't update this value after 1.x release: the whole idea is that
    # it's a pickle at a specific version of the library,
    # and it should remain unpicklable even in later versions.
    dumped = (
        b"\x80\x04\x95F\x00\x00\x00\x00\x00\x00\x00\x8c\x08whenever\x94\x8c\x0c_unp"
        b"kl_zoned\x94\x93\x94C\x0f\xe4\x07\x08\x0f\x17\x0c\t\x06\x12\x0f\x00"
        b" \x1c\x00\x00\x94\x8c\x10Europe/Amsterdam\x94\x86\x94R\x94."
    )
    assert pickle.loads(dumped).exact_eq(
        ZonedDateTime(
            2020, 8, 15, 23, 12, 9, nanosecond=987_654, tz="Europe/Amsterdam"
        )
    )


def test_copy():
    d = ZonedDateTime(
        2020, 8, 15, 23, 12, 9, nanosecond=987_654, tz="Europe/Amsterdam"
    )
    assert copy(d) is d
    assert deepcopy(d) is d


def test_cannot_subclass():
    with pytest.raises(TypeError):

        class Subclass(ZonedDateTime):  # type: ignore[misc]
            pass
