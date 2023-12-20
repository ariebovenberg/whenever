import pickle
import weakref
from copy import copy, deepcopy
from datetime import datetime as py_datetime
from datetime import timedelta, timezone

import pytest
from freezegun import freeze_time
from hypothesis import given
from hypothesis.strategies import text
from pytest import approx

from whenever import (
    AwareDateTime,
    InvalidFormat,
    LocalDateTime,
    OffsetDateTime,
    UTCDateTime,
    ZonedDateTime,
    hours,
)

from .common import (
    AlwaysEqual,
    AlwaysLarger,
    AlwaysSmaller,
    NeverEqual,
    local_nyc_tz,
)


def test_init_and_attributes():
    d = UTCDateTime(2020, 8, 15, 5, 12, 30, 450)

    assert d.year == 2020
    assert d.month == 8
    assert d.day == 15
    assert d.hour == 5
    assert d.minute == 12
    assert d.second == 30
    assert d.microsecond == 450
    assert d.offset == timedelta()


def test_init_optionality():
    assert (
        UTCDateTime(2020, 8, 15, 12)
        == UTCDateTime(2020, 8, 15, 12, 0)
        == UTCDateTime(2020, 8, 15, 12, 0, 0)
        == UTCDateTime(2020, 8, 15, 12, 0, 0, 0)
    )


def test_init_invalid():
    with pytest.raises(ValueError, match="microsecond must"):
        UTCDateTime(2020, 8, 15, 12, 8, 30, 1_000_000)


def test_init_named():
    d = UTCDateTime(year=2020, month=8, day=15, hour=5, minute=12, second=30)
    assert d == UTCDateTime(2020, 8, 15, 5, 12, 30)


def test_immutable():
    d = UTCDateTime(2020, 8, 15)
    with pytest.raises(AttributeError):
        d.year = 2021  # type: ignore[misc]


class TestFromStr:
    def test_valid(self):
        assert UTCDateTime.from_str("2020-08-15T12:08:30Z") == UTCDateTime(
            2020, 8, 15, 12, 8, 30
        )

    def test_valid_three_fractions(self):
        assert UTCDateTime.from_str("2020-08-15T12:08:30.349Z") == UTCDateTime(
            2020, 8, 15, 12, 8, 30, 349_000
        )

    def test_valid_six_fractions(self):
        assert UTCDateTime.from_str(
            "2020-08-15T12:08:30.349123Z"
        ) == UTCDateTime(2020, 8, 15, 12, 8, 30, 349_123)

    def test_single_space_instead_of_T(self):
        assert UTCDateTime.from_str("2020-08-15 12:08:30Z") == UTCDateTime(
            2020, 8, 15, 12, 8, 30
        )

    def test_unpadded(self):
        with pytest.raises(InvalidFormat):
            UTCDateTime.from_str("2020-8-15T12:8:30Z")

    def test_overly_precise_fraction(self):
        with pytest.raises(InvalidFormat):
            UTCDateTime.from_str("2020-08-15T12:08:30.123456789123Z")

    def test_invalid_lowercase_z(self):
        with pytest.raises(InvalidFormat):
            UTCDateTime.from_str("2020-08-15T12:08:30z")

    def test_no_trailing_z(self):
        with pytest.raises(InvalidFormat):
            UTCDateTime.from_str("2020-08-15T12:08:30")

    def test_no_seconds(self):
        with pytest.raises(InvalidFormat):
            UTCDateTime.from_str("2020-08-15T12:08Z")

    def test_empty(self):
        with pytest.raises(InvalidFormat):
            UTCDateTime.from_str("")

    def test_garbage(self):
        with pytest.raises(InvalidFormat):
            UTCDateTime.from_str("garbage")

    @given(text())
    def test_fuzzing(self, s: str):
        with pytest.raises(InvalidFormat):
            UTCDateTime.from_str(s)


class TestEquality:
    def test_same(self):
        d = UTCDateTime(2020, 8, 15)
        same = d.replace()
        assert d == same
        assert not d != same
        assert hash(d) == hash(same)

    def test_different(self):
        d = UTCDateTime(2020, 8, 15)
        different = d.replace(year=2021)
        assert d != different
        assert not d == different
        assert hash(d) != hash(different)

    def test_notimplemented(self):
        d = UTCDateTime(2020, 8, 15)
        assert d == AlwaysEqual()
        assert d != NeverEqual()
        assert not d == NeverEqual()
        assert not d != AlwaysEqual()

    def test_invalid(self):
        d = UTCDateTime(2020, 8, 15)
        d == 42  # type: ignore[comparison-overlap]

    @local_nyc_tz()
    def test_other_aware_types(self):
        d: AwareDateTime = UTCDateTime(2020, 8, 15)
        assert d == d.to_local()
        assert d == d.to_local().replace(fold=1)
        assert d == d.to_offset()
        assert d == d.to_offset(hours(3))
        assert d == d.to_zoned("Europe/Paris")

        assert d != d.to_local().replace(year=2021)
        assert d != d.to_offset(hours(1)).replace(year=2021)
        assert d != d.to_zoned("Europe/London").replace(year=2021)


def test_timestamp():
    assert UTCDateTime(1970, 1, 1).timestamp() == 0
    assert UTCDateTime(2020, 8, 15, 12, 8, 30, 45).timestamp() == approx(
        1_597_493_310.000045, abs=1e-6
    )


def test_from_timestamp():
    assert UTCDateTime.from_timestamp(0) == UTCDateTime(1970, 1, 1)
    assert UTCDateTime.from_timestamp(1_597_493_310) == UTCDateTime(
        2020, 8, 15, 12, 8, 30
    )
    with pytest.raises((OSError, OverflowError)):
        UTCDateTime.from_timestamp(1_000_000_000_000_000_000)


def test_repr():
    d = UTCDateTime(2020, 8, 15, 23, 12, 9, 987_654)
    assert repr(d) == "whenever.UTCDateTime(2020-08-15T23:12:09.987654Z)"
    assert (
        repr(UTCDateTime(2020, 8, 15, 23, 12))
        == "whenever.UTCDateTime(2020-08-15T23:12:00Z)"
    )


def test_str():
    d = UTCDateTime(2020, 8, 15, 23, 12, 9, 987_654)
    assert str(d) == "2020-08-15T23:12:09.987654Z"


def test_comparison():
    d = UTCDateTime.from_str("2020-08-15T23:12:09Z")
    later = UTCDateTime.from_str("2020-08-16T00:00:00Z")
    assert d < later
    assert d <= later
    assert later > d
    assert later >= d

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


def test_py():
    d = UTCDateTime(2020, 8, 15, 23, 12, 9, 987_654)
    assert d.py == py_datetime(
        2020, 8, 15, 23, 12, 9, 987_654, tzinfo=timezone.utc
    )


def test_from_py():
    d = py_datetime(2020, 8, 15, 23, 12, 9, 987_654, tzinfo=timezone.utc)
    assert UTCDateTime.from_py(d) == UTCDateTime(
        2020, 8, 15, 23, 12, 9, 987_654
    )

    with pytest.raises(ValueError, match="UTC.*timedelta"):
        UTCDateTime.from_py(d.replace(tzinfo=timezone(-timedelta(hours=4))))


def test_now():
    now = UTCDateTime.now()
    py_now = py_datetime.now(timezone.utc)
    assert py_now - now.py < timedelta(seconds=1)


@freeze_time("2020-08-15T23:12:09Z")
def test_now_works_with_freezegun():
    assert UTCDateTime.now() == UTCDateTime(2020, 8, 15, 23, 12, 9)


def test_weakref():
    d = UTCDateTime(2020, 8, 15)
    ref = weakref.ref(d)
    assert ref() == d


def test_min_max():
    assert UTCDateTime.min == UTCDateTime(1, 1, 1)
    assert UTCDateTime.max == UTCDateTime(9999, 12, 31, 23, 59, 59, 999_999)


def test_passthrough_datetime_attrs():
    d = UTCDateTime(2020, 8, 15, 12, 43)
    assert d.resolution == py_datetime.resolution
    assert d.weekday() == d.py.weekday()
    assert d.date() == d.py.date()
    time = d.time()
    assert time.tzinfo is None
    assert time == d.py.time()


def test_tz():
    d = UTCDateTime(2020, 8, 15, 12, 43)
    assert d.tzinfo == d.py.tzinfo == timezone.utc


def test_replace():
    d = UTCDateTime(2020, 8, 15, 23, 12, 9, 987_654)
    assert d.replace(year=2021) == UTCDateTime(2021, 8, 15, 23, 12, 9, 987_654)
    assert d.replace(month=9) == UTCDateTime(2020, 9, 15, 23, 12, 9, 987_654)
    assert d.replace(day=16) == UTCDateTime(2020, 8, 16, 23, 12, 9, 987_654)
    assert d.replace(hour=0) == UTCDateTime(2020, 8, 15, 0, 12, 9, 987_654)
    assert d.replace(minute=0) == UTCDateTime(2020, 8, 15, 23, 0, 9, 987_654)
    assert d.replace(second=0) == UTCDateTime(2020, 8, 15, 23, 12, 0, 987_654)
    assert d.replace(microsecond=0) == UTCDateTime(2020, 8, 15, 23, 12, 9, 0)

    with pytest.raises(TypeError, match="tzinfo"):
        d.replace(tzinfo=timezone.utc)  # type: ignore[call-arg]


def test_add():
    d = UTCDateTime(2020, 8, 15, 23, 12, 9, 987_654)
    assert d + timedelta(days=1, seconds=5) == UTCDateTime(
        2020, 8, 16, 23, 12, 14, 987_654
    )


def test_add_invalid():
    d = UTCDateTime(2020, 8, 15, 23, 12, 9, 987_654)
    with pytest.raises(TypeError, match="unsupported operand type"):
        d + 42  # type: ignore[operator]


def test_sub():
    d = UTCDateTime(2020, 8, 15, 23, 12, 9, 987_654)
    assert d - timedelta(days=1, seconds=5) == UTCDateTime(
        2020, 8, 14, 23, 12, 4, 987_654
    )


def test_subtract_datetime():
    d = UTCDateTime(2020, 8, 15, 23, 12, 9, 987_654)
    other = UTCDateTime(2020, 8, 14, 23, 12, 4, 987_654)
    assert d - other == timedelta(days=1, seconds=5)


def test_subtract_invalid():
    d = UTCDateTime(2020, 8, 15, 23, 12, 9, 987_654)
    with pytest.raises(TypeError, match="unsupported operand type"):
        d - 42  # type: ignore[operator]


def test_pickle():
    d = UTCDateTime(2020, 8, 15, 23, 12, 9, 987_654)
    dumped = pickle.dumps(d)
    assert len(dumped) <= len(pickle.dumps(d.py))
    assert pickle.loads(pickle.dumps(d)) == d


def test_copy():
    d = UTCDateTime(2020, 8, 15, 23, 12, 9, 987_654)
    assert copy(d) is d
    assert deepcopy(d) is d


def test_to_utc():
    d = UTCDateTime(2020, 8, 15, 20)
    assert d.to_utc() is d


def test_to_offset():
    d = UTCDateTime(2020, 8, 15, 20)
    assert d.to_offset().exact_eq(
        OffsetDateTime(2020, 8, 15, 20, offset=timedelta())
    )
    assert d.to_offset(hours(3)).exact_eq(
        OffsetDateTime(2020, 8, 15, 23, offset=timedelta(hours=3))
    )


def test_to_zoned():
    d = UTCDateTime(2020, 8, 15, 20)
    assert d.to_zoned("America/New_York").exact_eq(
        ZonedDateTime(2020, 8, 15, 16, zone="America/New_York")
    )


@local_nyc_tz()
def test_to_local():
    d = UTCDateTime(2020, 8, 15, 20)
    assert d.to_local().exact_eq(LocalDateTime(2020, 8, 15, 16, fold=0))
    # ensure fold is set correctly
    d = UTCDateTime(2022, 11, 6, 5)
    assert d.to_local().exact_eq(LocalDateTime(2022, 11, 6, 1, fold=0))
    assert d.replace(hour=6).to_local() == LocalDateTime(
        2022, 11, 6, 1, fold=1
    )
