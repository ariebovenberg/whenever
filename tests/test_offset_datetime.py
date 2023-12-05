import pickle
import weakref
from datetime import datetime as py_datetime
from datetime import timedelta, timezone, tzinfo

import pytest
from hypothesis import given
from hypothesis.strategies import text
from pytest import approx

from whenever import OffsetDateTime, hours, minutes

from .common import AlwaysEqual, AlwaysLarger, AlwaysSmaller, NeverEqual


def test_init_and_attributes():
    d = OffsetDateTime(2020, 8, 15, 5, 12, 30, 450, offset=hours(5))

    assert d.year == 2020
    assert d.month == 8
    assert d.day == 15
    assert d.hour == 5
    assert d.minute == 12
    assert d.second == 30
    assert d.microsecond == 450
    assert d.offset == hours(5)


def test_offset_missing():
    with pytest.raises(TypeError, match="offset"):
        OffsetDateTime(2020, 8, 15, 5, 12, 30, 450)  # type: ignore[call-arg]


def test_invalid_offset():
    with pytest.raises(ValueError, match="offset"):
        OffsetDateTime(2020, 8, 15, 5, 12, offset=hours(34))


def test_init_optionality():
    assert (
        OffsetDateTime(2020, 8, 15, 12, offset=hours(5))
        == OffsetDateTime(2020, 8, 15, 12, 0, offset=hours(5))
        == OffsetDateTime(2020, 8, 15, 12, 0, 0, offset=hours(5))
    )


def test_init_named():
    d = OffsetDateTime(
        year=2020,
        month=8,
        day=15,
        hour=5,
        minute=12,
        second=30,
        offset=hours(5),
    )
    assert d == OffsetDateTime(2020, 8, 15, 5, 12, 30, 0, offset=hours(5))


def test_immutable():
    d = OffsetDateTime(2020, 8, 15, offset=minutes(5))
    with pytest.raises(AttributeError):
        d.year = 2021  # type: ignore[misc]


def test_str():
    d = OffsetDateTime(2020, 8, 15, 23, 12, 9, 987_654, offset=hours(5))
    assert str(d) == "2020-08-15T23:12:09.987654+05:00"


class TestFromStr:
    def test_valid(self):
        assert OffsetDateTime.from_str(
            "2020-08-15T12:08:30+05:00"
        ) == OffsetDateTime(2020, 8, 15, 12, 8, 30, offset=hours(5))

    def test_valid_offset_with_seconds(self):
        assert OffsetDateTime.from_str(
            "2020-08-15T12:08:30+05:00:33"
        ) == OffsetDateTime(
            2020, 8, 15, 12, 8, 30, offset=timedelta(hours=5, seconds=33)
        )

    def test_valid_three_fractions(self):
        assert OffsetDateTime.from_str(
            "2020-08-15T12:08:30.349+05:00:33"
        ) == OffsetDateTime(
            2020,
            8,
            15,
            12,
            8,
            30,
            349_000,
            offset=timedelta(hours=5, seconds=33),
        )

    def test_valid_six_fractions(self):
        assert OffsetDateTime.from_str(
            "2020-08-15T12:08:30.349123+05:00:33.987654"
        ) == OffsetDateTime(
            2020,
            8,
            15,
            12,
            8,
            30,
            349_123,
            offset=timedelta(hours=5, seconds=33, microseconds=987_654),
        )

    def test_single_space_instead_of_T(self):
        assert OffsetDateTime.from_str(
            "2020-08-15 12:08:30-04:00"
        ) == OffsetDateTime(2020, 8, 15, 12, 8, 30, offset=hours(-4))

    def test_unpadded(self):
        with pytest.raises(ValueError):
            OffsetDateTime.from_str("2020-8-15T12:8:30+05:00")

    def test_overly_precise_fraction(self):
        with pytest.raises(ValueError):
            OffsetDateTime.from_str("2020-08-15T12:08:30.123456789123+05:00")

    def test_invalid_offset(self):
        with pytest.raises(ValueError, match="offset"):
            OffsetDateTime.from_str("2020-08-15T12:08:30-99:00")

    def test_no_offset(self):
        with pytest.raises(ValueError):
            OffsetDateTime.from_str("2020-08-15T12:08:30")

    def test_no_seconds(self):
        with pytest.raises(ValueError):
            OffsetDateTime.from_str("2020-08-15T12:08-05:00")

    def test_empty(self):
        with pytest.raises(ValueError):
            OffsetDateTime.from_str("")

    def test_garbage(self):
        with pytest.raises(ValueError):
            OffsetDateTime.from_str("garbage")

    @given(text())
    def test_fuzzing(self, s: str):
        with pytest.raises(ValueError, match="Invalid"):
            OffsetDateTime.from_str(s)


def test_equality():
    d = OffsetDateTime(2020, 8, 15, 12, offset=hours(5))
    different = OffsetDateTime(2020, 8, 15, 12, offset=hours(6))
    same_exact = OffsetDateTime(2020, 8, 15, 12, 0, offset=hours(5))
    same_time = OffsetDateTime(2020, 8, 15, 11, 0, offset=hours(4))
    assert d == same_exact
    assert d == same_time
    assert d != different
    assert not d == different
    assert not d != same_exact
    assert not d != same_time

    assert hash(d) == hash(same_exact)
    assert hash(d) == hash(same_time)
    assert hash(d) != hash(different)

    assert d == AlwaysEqual()
    assert d != NeverEqual()
    assert not d == NeverEqual()
    assert not d != AlwaysEqual()

    assert d != 42  # type: ignore[comparison-overlap]
    assert not d == 42  # type: ignore[comparison-overlap]

    assert OffsetDateTime(
        2020, 8, 15, 12, 8, 30, 450, offset=hours(3)
    ) != OffsetDateTime(2020, 8, 15, 12, 8, 31, 450, offset=hours(3))


def test_timestamp():
    assert OffsetDateTime(1970, 1, 1, 3, offset=hours(3)).timestamp() == 0
    assert OffsetDateTime(
        2020, 8, 15, 8, 8, 30, 45, offset=hours(-4)
    ).timestamp() == approx(1_597_493_310.000045, abs=1e-6)


def test_from_timestamp():
    assert OffsetDateTime.from_timestamp(0, offset=hours(3)) == OffsetDateTime(
        1970, 1, 1, 3, offset=hours(3)
    )
    assert OffsetDateTime.from_timestamp(
        1_597_493_310, offset=hours(-2)
    ) == OffsetDateTime(2020, 8, 15, 10, 8, 30, offset=hours(-2))
    with pytest.raises((OSError, OverflowError)):
        OffsetDateTime.from_timestamp(
            1_000_000_000_000_000_000, offset=hours(0)
        )


def test_repr():
    d = OffsetDateTime(
        2020, 8, 15, 23, 12, 9, 987_654, offset=timedelta(hours=5, minutes=22)
    )
    assert (
        repr(d) == "whenever.OffsetDateTime(2020-08-15T23:12:09.987654+05:22)"
    )
    assert (
        repr(OffsetDateTime(2020, 8, 15, 23, 12, offset=hours(0)))
        == "whenever.OffsetDateTime(2020-08-15T23:12:00+00:00)"
    )


def test_comparison():
    d = OffsetDateTime.from_str("2020-08-15T15:12:09+05:00")
    later = OffsetDateTime.from_str("2020-08-15T16:00:00+02:00")
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


def test_to_py():
    d = OffsetDateTime(2020, 8, 15, 23, 12, 9, 987_654, offset=hours(5))
    assert d.to_py() == py_datetime(
        2020, 8, 15, 23, 12, 9, 987_654, tzinfo=timezone(hours(5))
    )


def test_from_py():
    d = py_datetime(2020, 8, 15, 23, 12, 9, 987_654, tzinfo=timezone(hours(2)))
    assert OffsetDateTime.from_py(d) == OffsetDateTime(
        2020, 8, 15, 23, 12, 9, 987_654, offset=hours(2)
    )

    class SomeTzinfo(tzinfo):
        pass

    d2 = d.replace(tzinfo=SomeTzinfo())  # type: ignore[abstract]
    with pytest.raises(ValueError, match="SomeTzinfo"):
        OffsetDateTime.from_py(d2)


def test_now():
    now = OffsetDateTime.now(hours(5))
    assert now.offset == hours(5)
    py_now = py_datetime.now(timezone.utc)
    assert py_now - now.to_py() < timedelta(seconds=1)


def test_weakref():
    d = OffsetDateTime(2020, 8, 15, offset=hours(5))
    ref = weakref.ref(d)
    assert ref() == d


def test_min_max():
    assert OffsetDateTime.min == OffsetDateTime(1, 1, 1, offset=hours(0))
    assert OffsetDateTime.max == OffsetDateTime(
        9999, 12, 31, 23, 59, 59, 999_999, offset=hours(0)
    )


def test_passthrough_datetime_attrs():
    d = OffsetDateTime(2020, 8, 15, 12, 43, offset=hours(5))
    assert d.resolution == py_datetime.resolution
    assert d.weekday() == d.to_py().weekday()
    assert d.date() == d.to_py().date()
    time = d.time()
    assert time.tzinfo is None
    assert time == d.to_py().time()


def test_tz():
    d = OffsetDateTime(2020, 8, 15, 12, 43, offset=hours(5))
    assert d.tzinfo == d.to_py().tzinfo == timezone(hours(5))


def test_replace():
    d = OffsetDateTime(2020, 8, 15, 23, 12, 9, 987_654, offset=hours(5))
    assert d.replace(year=2021) == OffsetDateTime(
        2021, 8, 15, 23, 12, 9, 987_654, offset=hours(5)
    )
    assert d.replace(month=9) == OffsetDateTime(
        2020, 9, 15, 23, 12, 9, 987_654, offset=hours(5)
    )
    assert d.replace(day=16) == OffsetDateTime(
        2020, 8, 16, 23, 12, 9, 987_654, offset=hours(5)
    )
    assert d.replace(hour=0) == OffsetDateTime(
        2020, 8, 15, 0, 12, 9, 987_654, offset=hours(5)
    )
    assert d.replace(minute=0) == OffsetDateTime(
        2020, 8, 15, 23, 0, 9, 987_654, offset=hours(5)
    )
    assert d.replace(second=0) == OffsetDateTime(
        2020, 8, 15, 23, 12, 0, 987_654, offset=hours(5)
    )
    assert d.replace(microsecond=0) == OffsetDateTime(
        2020, 8, 15, 23, 12, 9, 0, offset=hours(5)
    )
    assert d.replace(offset=hours(6)) == OffsetDateTime(
        2020, 8, 15, 23, 12, 9, 987_654, offset=hours(6)
    )

    with pytest.raises(TypeError, match="tzinfo"):
        d.replace(tzinfo=timezone.utc)  # type: ignore[call-arg]


def test_add_invalid():
    d = OffsetDateTime(2020, 8, 15, 23, 12, 9, 987_654, offset=hours(5))
    with pytest.raises(TypeError, match="unsupported operand type"):
        d + hours(4)  # type: ignore[operator]

    with pytest.raises(TypeError, match="unsupported operand type"):
        d + 32  # type: ignore[operator]


def test_subtract_invalid():
    d = OffsetDateTime(2020, 8, 15, 23, 12, 9, 987_654, offset=hours(5))

    with pytest.raises(TypeError, match="unsupported operand type"):
        d - hours(2)  # type: ignore[operator]

    with pytest.raises(TypeError, match="unsupported operand type"):
        d - 42  # type: ignore[operator]


def test_subtract_datetime():
    d = OffsetDateTime(2020, 8, 15, 23, 12, 9, 987_654, offset=hours(5))
    other = OffsetDateTime(2020, 8, 14, 23, 12, 4, 987_654, offset=hours(-3))
    assert d - other == timedelta(hours=16, seconds=5)


def test_pickle():
    d = OffsetDateTime(2020, 8, 15, 23, 12, 9, 987_654, offset=hours(3))
    dumped = pickle.dumps(d)
    assert len(dumped) <= len(pickle.dumps(d.to_py())) + 10
    assert pickle.loads(pickle.dumps(d)) == d
