import pickle
import weakref
from copy import copy, deepcopy
from datetime import datetime as py_datetime, timedelta, timezone
from typing import Any

import pytest
from hypothesis import given
from hypothesis.strategies import text
from pytest import approx

from whenever import (
    Ambiguous,
    AwareDateTime,
    Date,
    DoesntExist,
    InvalidFormat,
    InvalidOffsetForZone,
    LocalDateTime,
    NaiveDateTime,
    OffsetDateTime,
    UTCDateTime,
    ZonedDateTime,
    days,
    hours,
    months,
    weeks,
    years,
)

from .common import (
    AlwaysEqual,
    AlwaysLarger,
    AlwaysSmaller,
    NeverEqual,
    ZoneInfo,
    ZoneInfoNotFoundError,
    local_ams_tz,
    local_nyc_tz,
)


class TestInit:
    def test_unambiguous(self):
        zone = "America/New_York"
        d = ZonedDateTime(2020, 8, 15, 5, 12, 30, 450, tz=zone)

        assert d.year == 2020
        assert d.month == 8
        assert d.day == 15
        assert d.hour == 5
        assert d.minute == 12
        assert d.second == 30
        assert d.microsecond == 450
        assert d.tz == zone
        assert d.offset == hours(-4)

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
            Ambiguous,
            match="2023-10-29 02:15:30 is ambiguous in timezone Europe/Amsterdam",
        ):
            ZonedDateTime(**kwargs)

        with pytest.raises(
            Ambiguous,
            match="2023-10-29 02:15:30 is ambiguous in timezone Europe/Amsterdam",
        ):
            ZonedDateTime(**kwargs, disambiguate="raise")

        d1 = ZonedDateTime(**kwargs, disambiguate="earlier")
        assert d1.as_utc() == UTCDateTime(2023, 10, 29, 0, 15, 30)
        assert ZonedDateTime(**kwargs, disambiguate="compatible") == d1

        d2 = ZonedDateTime(**kwargs, disambiguate="later")
        assert d2.as_utc() == UTCDateTime(2023, 10, 29, 1, 15, 30)

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
            == ZonedDateTime(2020, 8, 15, 12, 0, 0, 0, tz=tz)
            == ZonedDateTime(
                2020, 8, 15, 12, 0, 0, 0, tz=tz, disambiguate="raise"
            )
        )

    def test_nonexistent(self):
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
            DoesntExist,
            match="2023-03-26 02:15:30 doesn't exist in timezone Europe/Amsterdam",
        ):
            ZonedDateTime(**kwargs)

        with pytest.raises(
            DoesntExist,
            match="2023-03-26 02:15:30 doesn't exist in timezone Europe/Amsterdam",
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


def test_immutable():
    d = ZonedDateTime(2020, 8, 15, tz="Europe/Amsterdam")
    with pytest.raises(AttributeError):
        d.year = 2021  # type: ignore[misc]


def test_date():
    d = ZonedDateTime(2020, 8, 15, 14, tz="Europe/Amsterdam")
    assert d.date() == Date(2020, 8, 15)


class TestWithDate:
    def test_unambiguous(self):
        d = ZonedDateTime(2020, 8, 15, 14, tz="Europe/Amsterdam")
        assert d.with_date(Date(2021, 1, 2)) == ZonedDateTime(
            2021, 1, 2, 14, tz="Europe/Amsterdam"
        )

    def test_ambiguous(self):
        d = ZonedDateTime(2020, 1, 1, 2, 15, 30, tz="Europe/Amsterdam")
        date = Date(2023, 10, 29)
        with pytest.raises(Ambiguous):
            assert d.with_date(date)

        assert d.with_date(date, disambiguate="earlier") == d.replace(
            year=2023, month=10, day=29, disambiguate="earlier"
        )
        assert d.with_date(date, disambiguate="later") == d.replace(
            year=2023, month=10, day=29, disambiguate="later"
        )
        assert d.with_date(date, disambiguate="compatible") == d.replace(
            year=2023, month=10, day=29, disambiguate="compatible"
        )

    def test_nonexistent(self):
        d = ZonedDateTime(2020, 1, 1, 2, 15, 30, tz="Europe/Amsterdam")
        date = Date(2023, 3, 26)
        with pytest.raises(DoesntExist):
            assert d.with_date(date)

        assert d.with_date(date, disambiguate="earlier") == d.replace(
            year=2023, month=3, day=26, disambiguate="earlier"
        )
        assert d.with_date(date, disambiguate="later") == d.replace(
            year=2023, month=3, day=26, disambiguate="later"
        )
        assert d.with_date(date, disambiguate="compatible") == d.replace(
            year=2023, month=3, day=26, disambiguate="compatible"
        )


class TestCanonicalFormat:

    @pytest.mark.parametrize(
        "d, expected",
        [
            (
                ZonedDateTime(
                    2020, 8, 15, 23, 12, 9, 987_654, tz="Europe/Amsterdam"
                ),
                "2020-08-15T23:12:09.987654+02:00[Europe/Amsterdam]",
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
        ],
    )
    def test_canonical_format(self, d: ZonedDateTime, expected: str):
        assert str(d) == expected.replace("T", " ")
        assert d.canonical_format() == expected

    def test_seperator(self):
        d = ZonedDateTime(
            2020, 8, 15, 23, 12, 9, 987_654, tz="Europe/Amsterdam"
        )
        assert (
            d.canonical_format(sep=" ")
            == "2020-08-15 23:12:09.987654+02:00[Europe/Amsterdam]"
        )


class TestEquality:
    def test_same_exact(self):
        a = ZonedDateTime(2020, 8, 15, 12, 8, 30, tz="Europe/Amsterdam")
        b = a.replace()
        assert a == b
        assert hash(a) == hash(b)

    def test_wildly_different_timezone(self):
        a = ZonedDateTime(2020, 8, 15, 12, 8, 30, tz="Europe/Amsterdam")
        b = ZonedDateTime(2020, 8, 15, 12, 8, 30, tz="America/New_York")
        assert a != b
        assert hash(a) != hash(b)

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
        b = a.as_zoned("America/New_York")
        assert a.as_utc() == b.as_utc()  # sanity check
        assert hash(a) == hash(b)
        assert a == b

    @local_nyc_tz()
    def test_other_aware(self):
        d: AwareDateTime = ZonedDateTime(
            2020, 8, 15, 12, tz="Europe/Amsterdam"
        )
        assert d == d.as_utc()
        assert hash(d) == hash(d.as_utc())
        assert d != d.as_utc().replace(hour=23)

        assert d == d.as_local()
        assert d != d.as_local().replace(hour=8)

        assert d == d.as_offset()
        assert hash(d) == hash(d.as_offset())
        assert d != d.as_offset().replace(hour=10)

    def test_not_implemented(self):
        d = ZonedDateTime(2020, 8, 15, 12, 8, 30, tz="Europe/Amsterdam")
        assert d == AlwaysEqual()
        assert d != NeverEqual()
        assert not d == NeverEqual()
        assert not d != AlwaysEqual()

        assert d != 42  # type: ignore[comparison-overlap]
        assert not d == 42  # type: ignore[comparison-overlap]


def test_ambiguous():
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


def test_as_utc():
    assert ZonedDateTime(
        2020, 8, 15, 12, 8, 30, tz="Europe/Amsterdam"
    ).as_utc() == UTCDateTime(2020, 8, 15, 10, 8, 30)
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
    assert d.as_utc() == UTCDateTime(2023, 10, 29, 0, 15, 30)
    assert d.replace(disambiguate="later").as_utc() == UTCDateTime(
        2023, 10, 29, 1, 15, 30
    )


def test_as_zoned():
    assert (
        ZonedDateTime(2020, 8, 15, 12, 8, 30, tz="Europe/Amsterdam")
        .as_zoned("America/New_York")
        .exact_eq(ZonedDateTime(2020, 8, 15, 6, 8, 30, tz="America/New_York"))
    )
    ams = ZonedDateTime(
        2023, 10, 29, 2, 15, 30, tz="Europe/Amsterdam", disambiguate="earlier"
    )
    nyc = ZonedDateTime(2023, 10, 28, 20, 15, 30, tz="America/New_York")
    assert ams.as_zoned("America/New_York").exact_eq(nyc)
    assert (
        ams.replace(disambiguate="later")
        .as_zoned("America/New_York")
        .exact_eq(nyc.replace(hour=21))
    )
    assert nyc.as_zoned("Europe/Amsterdam").exact_eq(ams)
    assert (
        nyc.replace(hour=21)
        .as_zoned("Europe/Amsterdam")
        .exact_eq(ams.replace(disambiguate="later"))
    )
    # disambiguation doesn't affect NYC time because there's no ambiguity
    assert (
        nyc.replace(disambiguate="later")
        .as_zoned("Europe/Amsterdam")
        .exact_eq(ams)
    )


def test_as_offset():
    d = ZonedDateTime(2020, 8, 15, 12, 8, 30, tz="Europe/Amsterdam")

    assert d.as_offset().exact_eq(
        OffsetDateTime(2020, 8, 15, 12, 8, 30, offset=hours(2))
    )
    assert (
        d.replace(month=1)
        .as_offset()
        .exact_eq(OffsetDateTime(2020, 1, 15, 12, 8, 30, offset=hours(1)))
    )
    assert (
        d.replace(month=1)
        .as_offset(hours(4))
        .exact_eq(OffsetDateTime(2020, 1, 15, 15, 8, 30, offset=hours(4)))
    )
    assert d.as_offset(hours(0)).exact_eq(
        OffsetDateTime(2020, 8, 15, 10, 8, 30, offset=hours(0))
    )
    assert d.as_offset(-4).exact_eq(
        OffsetDateTime(2020, 8, 15, 6, 8, 30, offset=hours(-4))
    )


@local_ams_tz()
def test_to_local():
    d = ZonedDateTime(2023, 10, 28, 2, 15, tz="Europe/Amsterdam")
    assert d.as_local().exact_eq(LocalDateTime(2023, 10, 28, 2, 15))
    assert (
        d.replace(day=29, disambiguate="later")
        .as_local()
        .exact_eq(LocalDateTime(2023, 10, 29, 2, 15, disambiguate="later"))
    )


def test_naive():
    d = ZonedDateTime(2020, 8, 15, 13, tz="Europe/Amsterdam")
    assert d.naive() == NaiveDateTime(2020, 8, 15, 13)
    assert d.replace(disambiguate="later").naive() == NaiveDateTime(
        2020, 8, 15, 13
    )


class TestFromCanonicalFormat:
    def test_valid(self):
        assert ZonedDateTime.from_canonical_format(
            "2020-08-15T12:08:30+02:00[Europe/Amsterdam]"
        ).exact_eq(
            ZonedDateTime(2020, 8, 15, 12, 8, 30, tz="Europe/Amsterdam")
        )

    def test_offset_disambiguates(self):
        assert ZonedDateTime.from_canonical_format(
            "2023-10-29T02:15:30+01:00[Europe/Amsterdam]"
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
        assert ZonedDateTime.from_canonical_format(
            "2023-10-29T02:15:30+02:00[Europe/Amsterdam]"
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

    def test_offset_timezone_mismatch(self):
        with pytest.raises(InvalidOffsetForZone):
            # at the exact DST transition
            ZonedDateTime.from_canonical_format(
                "2023-10-29T02:15:30+03:00[Europe/Amsterdam]"
            )
        with pytest.raises(InvalidOffsetForZone):
            # some other time in the year
            ZonedDateTime.from_canonical_format(
                "2020-08-15T12:08:30+01:00:01[Europe/Amsterdam]"
            )

    def test_valid_three_fractions(self):
        assert ZonedDateTime.from_canonical_format(
            "2020-08-15T12:08:30.349-04:00[America/New_York]"
        ).exact_eq(
            ZonedDateTime(
                2020,
                8,
                15,
                12,
                8,
                30,
                349_000,
                tz="America/New_York",
            )
        )

    def test_valid_six_fractions(self):
        assert ZonedDateTime.from_canonical_format(
            "2020-08-15T12:08:30.349123-04:00[America/New_York]"
        ).exact_eq(
            ZonedDateTime(
                2020,
                8,
                15,
                12,
                8,
                30,
                349_123,
                tz="America/New_York",
            )
        )

    def test_single_space_instead_of_T(self):
        assert ZonedDateTime.from_canonical_format(
            "2020-08-15 12:08:30-04:00[America/New_York]"
        ).exact_eq(
            ZonedDateTime(2020, 8, 15, 12, 8, 30, tz="America/New_York")
        )

    def test_unpadded(self):
        with pytest.raises(InvalidFormat):
            ZonedDateTime.from_canonical_format(
                "2020-8-15T12:8:30+05:00[Asia/Kolkata]"
            )

    def test_overly_precise_fraction(self):
        with pytest.raises(InvalidFormat):
            ZonedDateTime.from_canonical_format(
                "2020-08-15T12:08:30.123456789123+05:00[Asia/Kolkata]"
            )

    def test_invalid_offset(self):
        with pytest.raises(InvalidOffsetForZone):
            ZonedDateTime.from_canonical_format(
                "2020-08-15T12:08:30-09:00[Asia/Kolkata]"
            )

    def test_no_offset(self):
        with pytest.raises(InvalidFormat):
            ZonedDateTime.from_canonical_format(
                "2020-08-15T12:08:30[Europe/Amsterdam]"
            )

    def test_no_timezone(self):
        with pytest.raises(InvalidFormat):
            ZonedDateTime.from_canonical_format("2020-08-15T12:08:30+05:00")

    def test_no_seconds(self):
        with pytest.raises(InvalidFormat):
            ZonedDateTime.from_canonical_format(
                "2020-08-15T12:08-05:00[America/New_York]"
            )

    def test_empty(self):
        with pytest.raises(InvalidFormat):
            ZonedDateTime.from_canonical_format("")

    def test_garbage(self):
        with pytest.raises(InvalidFormat):
            ZonedDateTime.from_canonical_format("garbage")

    @given(text())
    def test_fuzzing(self, s: str):
        with pytest.raises(InvalidFormat):
            ZonedDateTime.from_canonical_format(s)


def test_timestamp():
    assert ZonedDateTime(1970, 1, 1, tz="Iceland").timestamp() == 0
    assert ZonedDateTime(
        2020, 8, 15, 8, 8, 30, 45, tz="America/New_York"
    ).timestamp() == approx(1_597_493_310.000045, abs=1e-6)

    ambiguous = ZonedDateTime(
        2023, 10, 29, 2, 15, 30, tz="Europe/Amsterdam", disambiguate="earlier"
    )
    assert (
        ambiguous.timestamp()
        != ambiguous.replace(disambiguate="later").timestamp()
    )


def test_from_timestamp():
    assert ZonedDateTime.from_timestamp(0, tz="Iceland").exact_eq(
        ZonedDateTime(1970, 1, 1, tz="Iceland")
    )
    assert ZonedDateTime.from_timestamp(
        1_597_493_310, tz="America/Nuuk"
    ).exact_eq(ZonedDateTime(2020, 8, 15, 10, 8, 30, tz="America/Nuuk"))
    with pytest.raises((OSError, OverflowError)):
        ZonedDateTime.from_timestamp(
            1_000_000_000_000_000_000, tz="America/Nuuk"
        )


def test_repr():
    d = ZonedDateTime(2020, 8, 15, 23, 12, 9, 987_654, tz="Australia/Darwin")
    assert (
        repr(d) == "ZonedDateTime(2020-08-15 23:12:09.987654"
        "+09:30[Australia/Darwin])"
    )
    assert (
        repr(ZonedDateTime(2020, 8, 15, 23, 12, tz="Iceland"))
        == "ZonedDateTime(2020-08-15 23:12:00+00:00[Iceland])"
    )


class TestComparison:
    def test_different_timezones(self):
        d = ZonedDateTime.from_canonical_format(
            "2020-08-15T15:12:09+05:30[Asia/Kolkata]"
        )
        later = ZonedDateTime.from_canonical_format(
            "2020-08-15T14:00:00+02:00[Europe/Amsterdam]"
        )
        assert d < later
        assert d <= later
        assert later > d
        assert later >= d
        assert not d > later
        assert not d >= later
        assert not later < d
        assert not later <= d

    def test_same_timezone_ambiguity(self):
        d = ZonedDateTime.from_canonical_format(
            "2023-10-29T02:15:30+02:00[Europe/Amsterdam]"
        )
        later = ZonedDateTime.from_canonical_format(
            "2023-10-29T02:15:30+01:00[Europe/Amsterdam]"
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
        d = ZonedDateTime.from_canonical_format(
            "2023-10-29T02:15:30+02:00[Europe/Amsterdam]"
        )
        other = d.as_zoned("America/New_York")
        assert not d < other
        assert d <= other
        assert not other > d
        assert other >= d
        assert not d > other
        assert d >= other
        assert not other < d
        assert other <= d

    def test_utc(self):
        d = ZonedDateTime(2020, 8, 15, 12, 30, tz="Europe/Amsterdam")

        utc_eq = d.as_utc()
        utc_lt = utc_eq.replace(minute=29)
        utc_gt = utc_eq.replace(minute=31)

        assert d >= utc_eq
        assert d <= utc_eq
        assert not d > utc_eq
        assert not d < utc_eq

        assert d > utc_lt
        assert d >= utc_lt
        assert not d < utc_lt
        assert not d <= utc_lt

        assert d < utc_gt
        assert d <= utc_gt
        assert not d > utc_gt
        assert not d >= utc_gt

    def test_offset(self):
        d = ZonedDateTime(2020, 8, 15, 12, 30, tz="Europe/Amsterdam")

        offset_eq = d.as_offset()
        offset_lt = offset_eq.replace(minute=29)
        offset_gt = offset_eq.replace(minute=31)

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

    def test_local(self):
        d = ZonedDateTime(2020, 8, 15, 12, 30, tz="Europe/Amsterdam")

        local_eq = d.as_local()
        local_lt = local_eq.replace(minute=29)
        local_gt = local_eq.replace(minute=31)

        assert d >= local_eq
        assert d <= local_eq
        assert not d > local_eq
        assert not d < local_eq

        assert d > local_lt
        assert d >= local_lt
        assert not d < local_lt
        assert not d <= local_lt

        assert d < local_gt
        assert d <= local_gt
        assert not d > local_gt
        assert not d >= local_gt

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


def test_py():
    d = ZonedDateTime(2020, 8, 15, 23, 12, 9, 987_654, tz="Europe/Amsterdam")
    assert d.py_datetime() == py_datetime(
        2020, 8, 15, 23, 12, 9, 987_654, tzinfo=ZoneInfo("Europe/Amsterdam")
    )


def test_from_py_datetime():
    d = py_datetime(
        2020, 8, 15, 23, 12, 9, 987_654, tzinfo=ZoneInfo("Europe/Paris")
    )
    assert ZonedDateTime.from_py_datetime(d).exact_eq(
        ZonedDateTime(2020, 8, 15, 23, 12, 9, 987_654, tz="Europe/Paris")
    )

    d2 = d.replace(tzinfo=timezone.utc)
    with pytest.raises(ValueError, match="utc"):
        ZonedDateTime.from_py_datetime(d2)

    with pytest.raises(
        DoesntExist,
        match="2023-03-26 02:15:30 doesn't exist in timezone Europe/Amsterdam",
    ):
        ZonedDateTime.from_py_datetime(
            py_datetime(
                2023, 3, 26, 2, 15, 30, tzinfo=ZoneInfo("Europe/Amsterdam")
            )
        )


def test_now():
    now = ZonedDateTime.now("Iceland")
    assert now.tz == "Iceland"
    py_now = py_datetime.now(ZoneInfo("Iceland"))
    assert py_now - now.py_datetime() < timedelta(seconds=1)


def test_weakref():
    d = ZonedDateTime(2020, 8, 15, tz="Europe/Amsterdam")
    ref = weakref.ref(d)
    assert ref() == d


class TestExactEquality:
    def test_different_zones(self):
        a = ZonedDateTime(2020, 8, 15, 12, 43, tz="Europe/Amsterdam")
        b = a.as_zoned("America/New_York")
        assert a == b
        assert not a.exact_eq(b)

    def test_same_timezone_ambiguity(self):
        a = ZonedDateTime(
            2023,
            10,
            29,
            2,
            15,
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
            tz="Europe/Amsterdam",
            disambiguate="earlier",
        )
        b = a.replace(disambiguate="earlier")
        assert a.exact_eq(b)

    def test_same_unambiguous(self):
        a = ZonedDateTime(2020, 8, 15, 12, 43, tz="Europe/Amsterdam")
        b = a.replace()
        assert a.exact_eq(b)
        assert not a.exact_eq(b.replace(disambiguate="later"))


class TestReplace:
    def test_basics(self):
        d = ZonedDateTime(
            2020, 8, 15, 23, 12, 9, 987_654, tz="Europe/Amsterdam"
        )
        assert d.replace(year=2021).exact_eq(
            ZonedDateTime(
                2021, 8, 15, 23, 12, 9, 987_654, tz="Europe/Amsterdam"
            )
        )
        assert d.replace(month=9).exact_eq(
            ZonedDateTime(
                2020, 9, 15, 23, 12, 9, 987_654, tz="Europe/Amsterdam"
            )
        )
        assert d.replace(day=16).exact_eq(
            ZonedDateTime(
                2020, 8, 16, 23, 12, 9, 987_654, tz="Europe/Amsterdam"
            )
        )
        assert d.replace(hour=0).exact_eq(
            ZonedDateTime(
                2020, 8, 15, 0, 12, 9, 987_654, tz="Europe/Amsterdam"
            )
        )
        assert d.replace(minute=0).exact_eq(
            ZonedDateTime(
                2020, 8, 15, 23, 0, 9, 987_654, tz="Europe/Amsterdam"
            )
        )
        assert d.replace(second=0).exact_eq(
            ZonedDateTime(
                2020, 8, 15, 23, 12, 0, 987_654, tz="Europe/Amsterdam"
            )
        )
        assert d.replace(microsecond=0).exact_eq(
            ZonedDateTime(2020, 8, 15, 23, 12, 9, 0, tz="Europe/Amsterdam")
        )
        assert d.replace(tz="Iceland").exact_eq(
            ZonedDateTime(2020, 8, 15, 23, 12, 9, 987_654, tz="Iceland")
        )

    def test_invalid_args(self):
        d = ZonedDateTime(2020, 8, 15, tz="Europe/Amsterdam")
        with pytest.raises(TypeError, match="tzinfo"):
            d.replace(tzinfo=timezone.utc)  # type: ignore[call-arg]
        with pytest.raises(TypeError, match="fold"):
            d.replace(fold=1)  # type: ignore[call-arg]
        with pytest.raises(TypeError, match="foo"):
            d.replace(foo="bar")  # type: ignore[call-arg]

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
            Ambiguous,
            match="2023-10-29 02:15:30 is ambiguous in timezone Europe/Amsterdam",
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

    def test_nonexistent(self):
        d = ZonedDateTime(2023, 3, 26, 1, 15, 30, tz="Europe/Amsterdam")
        with pytest.raises(
            DoesntExist,
            match="2023-03-26 02:15:30 doesn't exist in timezone Europe/Amsterdam",
        ):
            d.replace(hour=2)

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


class TestAddTimeUnits:
    def test_zero(self):
        d = ZonedDateTime(
            2020, 8, 15, 23, 12, 9, 987_654, tz="Europe/Amsterdam"
        )
        assert (d + hours(0)).exact_eq(d)

    def test_ambiguous_plus_zero(self):
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
        assert (d + hours(0)).exact_eq(d)
        assert (d.replace(disambiguate="later") + hours(0)).exact_eq(
            d.replace(disambiguate="later")
        )

    def test_accounts_for_dst(self):
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
        assert (d + hours(24)).exact_eq(
            ZonedDateTime(2023, 10, 30, 1, 15, 30, tz="Europe/Amsterdam")
        )
        assert (d.replace(disambiguate="later") + hours(24)).exact_eq(
            ZonedDateTime(2023, 10, 30, 2, 15, 30, tz="Europe/Amsterdam")
        )

    def test_not_implemented(self):
        d = ZonedDateTime(2020, 8, 15, tz="Europe/Amsterdam")
        with pytest.raises(TypeError, match="unsupported operand type"):
            d + 42  # type: ignore[operator]


class TestAddDateUnits:

    def test_zero(self):
        d = ZonedDateTime(
            2020, 8, 15, 23, 12, 9, 987_654, tz="Europe/Amsterdam"
        )
        assert d + days(0) == d

    def test_simple_date(self):
        d = ZonedDateTime(
            2020, 8, 15, 23, 12, 9, 987_654, tz="Europe/Amsterdam"
        )
        assert d + days(1) == d.replace(day=16)
        assert d + years(1) + weeks(2) + days(-2) == d.replace(
            year=2021, day=27
        )

    def test_ambiguity(self):
        d = ZonedDateTime(
            2023,
            10,
            29,
            2,
            15,
            30,
            tz="Europe/Amsterdam",
            disambiguate="later",
        )
        assert d + days(0) == d
        assert d + (days(7) - weeks(1)) == d
        assert d + days(1) == d.replace(day=30)
        assert d + days(6) == d.replace(month=11, day=4)
        assert d + hours(-1) == d.replace(disambiguate="earlier")
        assert d + hours(1) == d.replace(hour=3)
        assert d.replace(disambiguate="earlier") + hours(1) == d

        # transition to another fold
        assert d + years(1) + days(-2) == d.replace(
            year=2024, day=27, disambiguate="earlier"
        )
        # transition to a gap
        assert d + months(5) + days(2) == d.replace(
            year=2024, month=3, day=31, disambiguate="later"
        )
        # transition over a gap
        assert d + months(5) + days(2) + hours(2) == d.replace(
            year=2024, month=3, day=31, hour=5
        )
        assert d + months(5) + days(2) + hours(-1) == d.replace(
            year=2024, month=3, day=31, disambiguate="earlier"
        )


class TestSubtractTimeUnits:
    def test_zero(self):
        d = ZonedDateTime(
            2020, 8, 15, 23, 12, 9, 987_654, tz="Europe/Amsterdam"
        )
        assert (d - hours(0)).exact_eq(d)

    def test_ambiguous_minus_zero(self):
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
        assert (d - hours(0)).exact_eq(d)
        assert (d.replace(disambiguate="later") - hours(0)).exact_eq(
            d.replace(disambiguate="later")
        )

    def test_accounts_for_dst(self):
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
        assert (d - hours(24)).exact_eq(
            ZonedDateTime(2023, 10, 28, 2, 15, 30, tz="Europe/Amsterdam")
        )
        assert (d.replace(disambiguate="later") - hours(24)).exact_eq(
            ZonedDateTime(2023, 10, 28, 3, 15, 30, tz="Europe/Amsterdam")
        )

    def test_subtract_not_implemented(self):
        d = ZonedDateTime(2020, 8, 15, tz="Europe/Amsterdam")
        with pytest.raises(TypeError, match="unsupported operand type"):
            d - 42  # type: ignore[operator]


class TestSubtractDateUnits:
    def test_zero(self):
        d = ZonedDateTime(
            2020, 8, 15, 23, 12, 9, 987_654, tz="Europe/Amsterdam"
        )
        assert d - days(0) == d

    def test_simple_date(self):
        d = ZonedDateTime(
            2020, 8, 15, 23, 12, 9, 987_654, tz="Europe/Amsterdam"
        )
        assert d - days(1) == d.replace(day=14)
        assert d - years(1) - weeks(2) - days(-2) == d.replace(
            year=2019, day=3
        )

    def test_ambiguity(self):
        d = ZonedDateTime(
            2023,
            10,
            29,
            2,
            15,
            30,
            tz="Europe/Amsterdam",
            disambiguate="later",
        )
        assert d - days(0) == d
        assert d - (days(7) + weeks(-1)) == d
        assert d - days(1) == d.replace(day=28)
        assert d - days(6) == d.replace(month=10, day=23)
        assert d - hours(1) == d.replace(disambiguate="earlier")
        assert d - hours(-1) == d.replace(hour=3)
        assert d.replace(disambiguate="earlier") - hours(-1) == d

        # transition to another fold
        assert d - years(1) - days(-1) == d.replace(
            year=2022, day=30, disambiguate="earlier"
        )
        # transition to a gap
        assert d - months(7) - days(3) == d.replace(
            month=3, day=26, disambiguate="later"
        )
        # # transition over a gap
        assert d - months(7) - days(3) - hours(1) == d.replace(
            month=3, day=26, hour=1
        )
        assert d - months(7) - days(3) - hours(-1) == d.replace(
            month=3, day=26, hour=4
        )


class TestSubtractDateTime:

    def test_simple(self):
        d = ZonedDateTime(
            2023, 10, 29, 5, tz="Europe/Amsterdam", disambiguate="earlier"
        )
        other = ZonedDateTime(2023, 10, 28, 3, tz="Europe/Amsterdam")
        assert d - other == hours(27)
        assert other - d == hours(-27)

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

    def test_utc(self):
        d = ZonedDateTime(
            2023, 10, 29, 2, tz="Europe/Amsterdam", disambiguate="earlier"
        )
        assert d - UTCDateTime(2023, 10, 28, 20) == hours(4)
        assert d.replace(disambiguate="later") - UTCDateTime(
            2023, 10, 28, 20
        ) == hours(5)

    def test_offset(self):
        d = ZonedDateTime(
            2023, 10, 29, 2, tz="Europe/Amsterdam", disambiguate="earlier"
        )
        assert d - OffsetDateTime(2023, 10, 28, 20, offset=hours(1)) == hours(
            5
        )
        assert d.replace(disambiguate="later") - OffsetDateTime(
            2023, 10, 28, 20, offset=hours(1)
        ) == hours(6)

    @local_nyc_tz()
    def test_local(self):
        d = ZonedDateTime(
            2023, 10, 29, 2, tz="Europe/Amsterdam", disambiguate="earlier"
        )
        assert d - LocalDateTime(2023, 10, 28, 19) == hours(1)
        assert d.replace(disambiguate="later") - LocalDateTime(
            2023, 10, 28, 19
        ) == hours(2)


def test_pickle():
    d = ZonedDateTime(2020, 8, 15, 23, 12, 9, 987_654, tz="Europe/Amsterdam")
    dumped = pickle.dumps(d)
    assert len(dumped) <= len(pickle.dumps(d.py_datetime))
    assert pickle.loads(pickle.dumps(d)).exact_eq(d)


def test_old_pickle_data_remains_unpicklable():
    # Don't update this value -- the whole idea is that it's a pickle at
    # a specific version of the library.
    dumped = (
        b"\x80\x04\x95I\x00\x00\x00\x00\x00\x00\x00\x8c\x08whenever\x94\x8c\x0c_unp"
        b"kl_zoned\x94\x93\x94(M\xe4\x07K\x08K\x0fK\x17K\x0cK\tJ\x06\x12"
        b"\x0f\x00\x8c\x10Europe/Amsterdam\x94K\x00t\x94R\x94."
    )
    assert pickle.loads(dumped) == ZonedDateTime(
        2020, 8, 15, 23, 12, 9, 987_654, tz="Europe/Amsterdam"
    )


def test_copy():
    d = ZonedDateTime(2020, 8, 15, 23, 12, 9, 987_654, tz="Europe/Amsterdam")
    assert copy(d) is d
    assert deepcopy(d) is d
