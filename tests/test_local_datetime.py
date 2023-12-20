import os
import pickle
import weakref
from copy import copy, deepcopy
from datetime import datetime as py_datetime
from datetime import timedelta, timezone
from unittest.mock import patch

import pytest
from hypothesis import given
from hypothesis.strategies import text
from pytest import approx

from whenever import (
    DoesntExistInZone,
    InvalidFormat,
    InvalidOffsetForZone,
    LocalDateTime,
    OffsetDateTime,
    UTCDateTime,
    ZonedDateTime,
    hours,
    minutes,
)

from .common import (
    AlwaysEqual,
    NeverEqual,
    ZoneInfo,
    local_ams_tz,
    local_nyc_tz,
)


class TestInit:
    @local_ams_tz()
    def test_basic(self):
        d = LocalDateTime(2020, 8, 15, 5, 12, 30, 450, fold=0)

        assert d.year == 2020
        assert d.month == 8
        assert d.day == 15
        assert d.hour == 5
        assert d.minute == 12
        assert d.second == 30
        assert d.microsecond == 450
        assert d.fold == 0
        assert d.offset == hours(2)

    def test_optionality(self):
        assert (
            LocalDateTime(2020, 8, 15, 12, fold=0)
            == LocalDateTime(2020, 8, 15, 12, 0, fold=0)
            == LocalDateTime(2020, 8, 15, 12, 0, 0, fold=0)
            == LocalDateTime(2020, 8, 15, 12, 0, 0, 0, fold=0)
        )

    @local_ams_tz()
    def test_nonexistent(self):
        with pytest.raises(DoesntExistInZone):
            LocalDateTime(2023, 3, 26, 2, 15, 30, fold=0)
        with pytest.raises(DoesntExistInZone):
            LocalDateTime(2023, 3, 26, 2, 15, 30, fold=1)


class TestToUTC:
    @local_ams_tz()
    def test_common_time(self):
        d = LocalDateTime(2020, 8, 15, 11, fold=0)
        assert d.to_utc().exact_eq(UTCDateTime(2020, 8, 15, 9))

    @local_ams_tz()
    def test_amibiguous_time(self):
        d = LocalDateTime(2023, 10, 29, 2, 15, fold=0)
        assert d.to_utc() == UTCDateTime(2023, 10, 29, 0, 15)
        assert (
            d.replace(fold=1)
            .to_utc()
            .exact_eq(UTCDateTime(2023, 10, 29, 1, 15))
        )

    @local_nyc_tz()
    def test_doesnt_exist(self):
        d = LocalDateTime(2023, 3, 26, 2, 15, fold=0)
        with local_ams_tz(), pytest.raises(DoesntExistInZone):
            d.to_utc()


@local_ams_tz()
def test_to_zoned():
    assert (
        LocalDateTime(2020, 8, 15, 12, 8, 30, fold=0)
        .to_zoned("America/New_York")
        .exact_eq(
            ZonedDateTime(2020, 8, 15, 6, 8, 30, zone="America/New_York")
        )
    )
    ams = LocalDateTime(2023, 10, 29, 2, 15, 30, fold=0)
    nyc = ZonedDateTime(2023, 10, 28, 20, 15, 30, zone="America/New_York")
    assert ams.to_zoned("America/New_York").exact_eq(nyc)
    assert (
        ams.replace(fold=1)
        .to_zoned("America/New_York")
        .exact_eq(nyc.replace(hour=21))
    )
    assert nyc.to_local() == ams
    assert nyc.replace(hour=21).to_local() == ams.replace(fold=1)
    # fold doesn't affect NYC time because there's no ambiguity
    assert nyc.replace(fold=1).to_local() == ams


class TestToOffset:
    @local_ams_tz()
    def test_simple(self):
        assert (
            LocalDateTime(2020, 8, 15, 12, 8, 30, fold=0)
            .to_offset()
            .exact_eq(OffsetDateTime(2020, 8, 15, 12, 8, 30, offset=hours(2)))
        )

    @local_ams_tz()
    def test_ambiguous(self):
        assert (
            LocalDateTime(2023, 10, 29, 2, 15, 30, fold=0)
            .to_offset()
            .exact_eq(OffsetDateTime(2023, 10, 29, 2, 15, 30, offset=hours(2)))
        )
        assert (
            LocalDateTime(2023, 10, 29, 2, 15, 30, fold=1)
            .to_offset()
            .exact_eq(OffsetDateTime(2023, 10, 29, 2, 15, 30, offset=hours(1)))
        )

    @local_ams_tz()
    def test_custom_offset(self):
        d = LocalDateTime(2020, 8, 15, 12, 30, fold=0)
        assert d.to_offset(hours(3)).exact_eq(
            OffsetDateTime(2020, 8, 15, 13, 30, offset=hours(3))
        )
        assert d.to_offset(hours(0)).exact_eq(
            OffsetDateTime(2020, 8, 15, 10, 30, offset=hours(0))
        )

    @local_nyc_tz()
    def test_doesnt_exist(self):
        d = LocalDateTime(2023, 3, 26, 2, 15, fold=0)
        with local_ams_tz(), pytest.raises(DoesntExistInZone):
            d.to_offset()


def test_to_local():
    d = LocalDateTime(2020, 8, 15, 12, 8, 30, fold=0)
    assert d.to_local() is d


def test_immutable():
    d = LocalDateTime(2020, 8, 15, fold=0)
    with pytest.raises(AttributeError):
        d.year = 2021  # type: ignore[misc]


class TestStr:
    @local_ams_tz()
    def test_simple(self):
        d = LocalDateTime(2020, 8, 15, 23, 12, 9, 987_654, fold=0)
        assert str(d) == "2020-08-15T23:12:09.987654+02:00"

    @local_ams_tz()
    def test_ambiguous(self):
        d = LocalDateTime(2023, 10, 29, 2, 15, 30, fold=0)
        assert str(d) == "2023-10-29T02:15:30+02:00"
        assert str(d.replace(fold=1)) == "2023-10-29T02:15:30+01:00"

    @local_nyc_tz()
    def test_doesnt_exist(self):
        d = LocalDateTime(2023, 3, 26, 2, 15, fold=0)
        with local_ams_tz(), pytest.raises(DoesntExistInZone):
            str(d)


class TestEquality:
    def test_same_exact(self):
        d = LocalDateTime(2020, 8, 15, 12, 8, 30, 450, fold=0)
        same = LocalDateTime(2020, 8, 15, 12, 8, 30, 450, fold=0)
        assert d == same
        assert not d != same

    def test_same_utc(self):
        d = LocalDateTime(2020, 8, 15, 12, 8, 30, 450, fold=0)
        same = LocalDateTime(2020, 8, 15, 12, 8, 30, 450, fold=1)
        assert d == same
        assert not d != same

    @local_ams_tz()
    def test_amibiguous(self):
        d = LocalDateTime(2023, 10, 29, 2, 15, 30, fold=0)
        same = LocalDateTime(2023, 10, 29, 2, 15, 30, fold=1)
        assert d != same
        assert not d == same

    def test_notimplemented(self):
        d = LocalDateTime(2020, 8, 15, fold=0)
        assert d == AlwaysEqual()
        assert not d != AlwaysEqual()
        assert d != NeverEqual()
        assert not d == NeverEqual()


def test_exact_equality():
    a = LocalDateTime(2020, 8, 15, 12, 8, 30, 450, fold=0)
    same = a.replace()
    same_utc = a.replace(fold=1)
    different = a.replace(hour=13)

    assert a.exact_eq(same)
    assert same.exact_eq(a)
    assert not a.exact_eq(same_utc)
    assert not same_utc.exact_eq(a)
    assert not a.exact_eq(different)
    assert not different.exact_eq(a)


def test_unhashable():
    d = LocalDateTime(2020, 8, 15, fold=0)
    with pytest.raises(TypeError):
        hash(d)


@local_ams_tz()
def test_is_ambiguous():
    assert not LocalDateTime(2020, 8, 15, 12, 8, 30, fold=0).is_ambiguous()
    assert LocalDateTime(2023, 10, 29, 2, 15, 30, fold=0).is_ambiguous()

    # non-existent isn't ambiguous
    d = LocalDateTime(2023, 3, 12, 2, 15, fold=0)
    with local_nyc_tz():
        assert not d.is_ambiguous()


@local_nyc_tz()
def test_exists():
    d = LocalDateTime(2023, 3, 26, 2, 15, fold=0)
    assert d.exists()
    with local_ams_tz():
        assert not d.exists()

    # ambiguous does exist
    assert LocalDateTime(2023, 11, 5, 1, 15, fold=0).exists()


class TestFromStr:
    @local_ams_tz()
    def test_valid(self):
        assert LocalDateTime.from_str(
            "2020-08-15T12:08:30+02:00"
        ) == LocalDateTime(2020, 8, 15, 12, 8, 30, fold=0)

    @local_ams_tz()
    def test_offset_determines_fold(self):
        assert LocalDateTime.from_str(
            "2023-10-29T02:15:30+02:00"
        ) == LocalDateTime(2023, 10, 29, 2, 15, 30, fold=0)
        assert LocalDateTime.from_str(
            "2023-10-29T02:15:30+01:00"
        ) == LocalDateTime(2023, 10, 29, 2, 15, 30, fold=1)

    @local_ams_tz()
    def test_offset_timezone_mismatch(self):
        with pytest.raises(InvalidOffsetForZone):
            # at the exact DST transition
            LocalDateTime.from_str("2023-10-29T02:15:30+03:00")
        with pytest.raises(InvalidOffsetForZone):
            # some other time in the year
            LocalDateTime.from_str("2020-08-15T12:08:30+01:00:01")

    @local_ams_tz()
    def test_valid_three_fractions(self):
        assert LocalDateTime.from_str(
            "2020-08-15T12:08:30.349+02:00"
        ) == LocalDateTime(
            2020,
            8,
            15,
            12,
            8,
            30,
            349_000,
            fold=0,
        )

    @local_ams_tz()
    def test_valid_six_fractions(self):
        assert LocalDateTime.from_str(
            "2020-08-15T12:08:30.349123+02:00"
        ) == LocalDateTime(
            2020,
            8,
            15,
            12,
            8,
            30,
            349_123,
            fold=0,
        )

    @local_ams_tz()
    def test_single_space_instead_of_T(self):
        assert LocalDateTime.from_str(
            "2020-08-15 12:08:30+02:00"
        ) == LocalDateTime(2020, 8, 15, 12, 8, 30, fold=0)

    @local_ams_tz()
    def test_unpadded(self):
        with pytest.raises(InvalidFormat):
            LocalDateTime.from_str("2020-8-15T12:8:30+02:00")

    @local_ams_tz()
    def test_overly_precise_fraction(self):
        with pytest.raises(InvalidFormat):
            LocalDateTime.from_str("2020-08-15T12:08:30.123456789123+02:00")

    @local_ams_tz()
    def test_invalid_offset(self):
        with pytest.raises(InvalidOffsetForZone):
            LocalDateTime.from_str("2020-08-15T12:08:30-20:00")

    def test_no_offset(self):
        with pytest.raises(InvalidFormat):
            LocalDateTime.from_str("2020-08-15T12:08:30")

    def test_no_timezone(self):
        with pytest.raises(InvalidFormat):
            LocalDateTime.from_str("2020-08-15T12:08:30")

    def test_no_seconds(self):
        with pytest.raises(InvalidFormat):
            LocalDateTime.from_str("2020-08-15T12:08+02:00")

    def test_empty(self):
        with pytest.raises(InvalidFormat):
            LocalDateTime.from_str("")

    def test_garbage(self):
        with pytest.raises(InvalidFormat):
            LocalDateTime.from_str("garbage")

    @given(text())
    def test_fuzzing(self, s: str):
        with pytest.raises(InvalidFormat):
            LocalDateTime.from_str(s)


@local_nyc_tz()
def test_timestamp():
    assert LocalDateTime(1969, 12, 31, 19, fold=0).timestamp() == 0
    assert LocalDateTime(
        2020, 8, 15, 8, 8, 30, 45, fold=0
    ).timestamp() == approx(1_597_493_310.000045, abs=1e-6)

    ambiguous = LocalDateTime(2023, 11, 5, 1, 15, 30, fold=0)
    assert ambiguous.timestamp() != ambiguous.replace(fold=1).timestamp()


@local_nyc_tz()
def test_from_timestamp():
    assert LocalDateTime.from_timestamp(0) == (
        LocalDateTime(1969, 12, 31, 19, fold=0)
    )
    assert LocalDateTime.from_timestamp(
        1_597_493_310,
    ) == LocalDateTime(2020, 8, 15, 8, 8, 30, fold=0)
    with pytest.raises((OSError, OverflowError)):
        LocalDateTime.from_timestamp(1_000_000_000_000_000_000)


@local_nyc_tz()
def test_repr():
    d = LocalDateTime(2023, 3, 26, 2, 15, fold=0)
    assert repr(d) == "whenever.LocalDateTime(2023-03-26T02:15:00-04:00)"

    with local_ams_tz():
        assert (
            repr(d)
            == "whenever.LocalDateTime(2023-03-26T02:15:00[nonexistent])"
        )


# class TestComparison:
#     @local_ams_tz()
#     def test_different_timezones(self):
#         d = LocalDateTime.from_str("2020-08-15T15:12:09+02:00")
#         later = LocalDateTime.from_str(
#             "2020-08-15T14:00:00+02:00[Europe/Amsterdam]"
#         )
#         assert d < later
#         assert d <= later
#         assert later > d
#         assert later >= d
#         assert not d > later
#         assert not d >= later
#         assert not later < d
#         assert not later <= d

#     def test_same_timezone_fold(self):
#         d = ZonedDateTime.from_str(
#             "2023-10-29T02:15:30+02:00[Europe/Amsterdam]"
#         )
#         later = ZonedDateTime.from_str(
#             "2023-10-29T02:15:30+01:00[Europe/Amsterdam]"
#         )
#         assert d < later
#         assert d <= later
#         assert later > d
#         assert later >= d
#         assert not d > later
#         assert not d >= later
#         assert not later < d
#         assert not later <= d

#     def test_different_timezone_same_time(self):
#         d = ZonedDateTime.from_str(
#             "2023-10-29T02:15:30+02:00[Europe/Amsterdam]"
#         )
#         other = d.to_zoned("America/New_York")
#         assert not d < other
#         assert d <= other
#         assert not other > d
#         assert other >= d
#         assert not d > other
#         assert d >= other
#         assert not other < d
#         assert other <= d

#     def test_notimplemented(self):
#         d = ZonedDateTime(2020, 8, 15, zone="Europe/Amsterdam", fold=0)
#         assert d < AlwaysLarger()
#         assert d <= AlwaysLarger()
#         assert not d > AlwaysLarger()
#         assert not d >= AlwaysLarger()
#         assert not d < AlwaysSmaller()
#         assert not d <= AlwaysSmaller()
#         assert d > AlwaysSmaller()
#         assert d >= AlwaysSmaller()

#         with pytest.raises(TypeError):
#             d < 42  # type: ignore[operator]


def test_py():
    d = LocalDateTime(2020, 8, 15, 23, 12, 9, 987_654, fold=1)
    py = d.py
    assert py == py_datetime(2020, 8, 15, 23, 12, 9, 987_654)
    assert py.fold == 1


def test_from_py():
    d = py_datetime(2020, 8, 15, 23, 12, 9, 987_654, fold=1)
    assert LocalDateTime.from_py(d) == LocalDateTime(
        2020, 8, 15, 23, 12, 9, 987_654, fold=1
    )

    d2 = d.replace(tzinfo=timezone.utc)
    with pytest.raises(ValueError, match="utc"):
        LocalDateTime.from_py(d2)


@patch.dict(os.environ, {"TZ": "America/New_York"})
def test_now():
    now = LocalDateTime.now()
    py_now = py_datetime.now(ZoneInfo("America/New_York")).replace(tzinfo=None)
    assert py_now - now.py < timedelta(seconds=1)


def test_weakref():
    d = LocalDateTime(2020, 8, 15, fold=0)
    ref = weakref.ref(d)
    assert ref() == d


def test_min_max():
    assert LocalDateTime.min == LocalDateTime(1, 1, 2, fold=0)
    assert LocalDateTime.max == LocalDateTime(
        9999,
        12,
        30,
        23,
        59,
        59,
        999_999,
        fold=0,
    )


def test_passthrough_datetime_attrs():
    d = LocalDateTime(2020, 8, 15, 12, 43, fold=0)
    assert d.resolution == py_datetime.resolution
    assert d.weekday() == d.py.weekday()
    assert d.date() == d.py.date()
    time = d.time()
    assert time.tzinfo is None
    assert time == d.py.time()
    assert d.tzinfo is d.py.tzinfo is None


def test_replace():
    d = LocalDateTime(2020, 8, 15, 23, 12, 9, 987_654, fold=0)
    assert d.replace(year=2021) == LocalDateTime(
        2021, 8, 15, 23, 12, 9, 987_654, fold=0
    )
    assert d.replace(month=9) == LocalDateTime(
        2020, 9, 15, 23, 12, 9, 987_654, fold=0
    )

    assert d.replace(day=16) == LocalDateTime(
        2020, 8, 16, 23, 12, 9, 987_654, fold=0
    )

    assert d.replace(hour=0) == LocalDateTime(
        2020, 8, 15, 0, 12, 9, 987_654, fold=0
    )

    assert d.replace(minute=0) == LocalDateTime(
        2020, 8, 15, 23, 0, 9, 987_654, fold=0
    )

    assert d.replace(second=0) == LocalDateTime(
        2020, 8, 15, 23, 12, 0, 987_654, fold=0
    )

    assert d.replace(microsecond=0) == LocalDateTime(
        2020, 8, 15, 23, 12, 9, 0, fold=0
    )

    assert d.replace(fold=1) == LocalDateTime(
        2020, 8, 15, 23, 12, 9, 987_654, fold=1
    )

    with pytest.raises(TypeError, match="tzinfo"):
        d.replace(tzinfo=timezone.utc)  # type: ignore[call-arg]


class TestAdd:
    @local_ams_tz()
    def test_zero_timedelta(self):
        d = LocalDateTime(2020, 8, 15, 23, 12, 9, 987_654, fold=0)
        assert d + timedelta() == d

    @local_ams_tz()
    def test_ambiguous(self):
        d = LocalDateTime(2023, 10, 29, 2, 15, 30, fold=0)
        assert d + minutes(10) == d.replace(minute=25)
        assert (d.replace(fold=1) + minutes(10)) == d.replace(
            fold=1, minute=25
        )

    @local_nyc_tz()
    def test_non_existent(self):
        d = LocalDateTime(2023, 3, 26, 2, 15, fold=0)
        with local_ams_tz(), pytest.raises(DoesntExistInZone):
            d + minutes(10)

    @local_ams_tz()
    def test_accounts_for_dst(self):
        d = LocalDateTime(2023, 10, 29, 2, 15, 30, fold=0)
        assert d + hours(24) == LocalDateTime(2023, 10, 30, 1, 15, 30, fold=0)
        assert d.replace(fold=1) + hours(24) == LocalDateTime(
            2023, 10, 30, 2, 15, 30, fold=0
        )

    def test_add_not_implemented(self):
        d = LocalDateTime(2020, 8, 15, fold=0)
        with pytest.raises(TypeError, match="unsupported operand type"):
            d + 42  # type: ignore[operator]

    def test_larger_than_max(self):
        d = LocalDateTime(9999, 12, 30, 23, 59, 59, 999_999, fold=0)
        with pytest.raises(ValueError, match="out of range"):
            d + timedelta(1)

        with pytest.raises(ValueError, match="out of range"):
            LocalDateTime(1, 1, 1, fold=0) + timedelta(-1)

    def test_overflow(self):
        d = LocalDateTime(9999, 12, 30, 23, 59, 59, 999_999, fold=0)
        with pytest.raises(OverflowError):
            d + timedelta.max

        with pytest.raises(OverflowError):
            d + (-timedelta.max)


class TestSubtract:
    @local_ams_tz()
    def test_zero_timedelta(self):
        d = LocalDateTime(2020, 8, 15, 23, 12, 9, 987_654, fold=0)
        assert d - timedelta() == d

    @local_ams_tz()
    def test_ambiguous(self):
        d = LocalDateTime(2023, 10, 29, 2, 15, 30, fold=0)
        assert d - minutes(10) == d.replace(minute=5)
        assert d.replace(fold=1) - minutes(10) == d.replace(fold=1, minute=5)

    @local_ams_tz()
    def test_accounts_for_dst(self):
        d = LocalDateTime(2023, 10, 29, 2, 15, 30, fold=0)
        assert d - hours(24) == LocalDateTime(2023, 10, 28, 2, 15, 30, fold=0)
        assert d.replace(fold=1) - hours(24) == LocalDateTime(
            2023, 10, 28, 3, 15, 30, fold=0
        )

    @local_nyc_tz()
    def test_non_existent(self):
        d = LocalDateTime(2023, 3, 26, 2, 15, fold=0)
        with local_ams_tz(), pytest.raises(DoesntExistInZone):
            d - minutes(10)

        with local_ams_tz(), pytest.raises(DoesntExistInZone):
            d - LocalDateTime(2023, 1, 1, fold=0)

    @local_ams_tz()
    def test_subtract_not_implemented(self):
        d = LocalDateTime(2020, 8, 15, fold=0)
        with pytest.raises(TypeError, match="unsupported operand type"):
            d - 42  # type: ignore[operator]

    @local_ams_tz()
    def test_subtract_datetime(self):
        d = LocalDateTime(2023, 10, 29, 5, fold=0)
        other = LocalDateTime(2023, 10, 28, 3, fold=0)
        assert d - other == hours(27)
        assert other - d == timedelta(hours=-27)

    @local_ams_tz()
    def test_subtract_amibiguous_datetime(self):
        d = LocalDateTime(2023, 10, 29, 2, 15, fold=0)
        other = LocalDateTime(2023, 10, 28, 3, 15, fold=0)
        assert d - other == hours(23)
        assert d.replace(fold=1) - other == hours(24)
        assert other - d == hours(-23)
        assert other - d.replace(fold=1) == hours(-24)


def test_pickle():
    d = LocalDateTime(2020, 8, 15, 23, 12, 9, 987_654, fold=0)
    dumped = pickle.dumps(d)
    assert len(dumped) <= len(pickle.dumps(d.py)) + 15
    assert pickle.loads(pickle.dumps(d)) == d


def test_copy():
    d = LocalDateTime(2020, 8, 15, 23, 12, 9, 987_654, fold=0)
    assert copy(d) is d
    assert deepcopy(d) is d
