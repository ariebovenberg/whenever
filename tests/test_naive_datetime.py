import pickle
import weakref
from datetime import datetime as py_datetime
from datetime import timedelta, timezone

import pytest
from hypothesis import given
from hypothesis.strategies import text

from whenever import InvalidFormat, NaiveDateTime

from .common import (
    AlwaysEqual,
    AlwaysLarger,
    AlwaysSmaller,
    NeverEqual,
    local_ams_tz,
)


def test_minimal():
    d = NaiveDateTime(2020, 8, 15, 5, 12, 30, 450)

    assert d.year == 2020
    assert d.month == 8
    assert d.day == 15
    assert d.hour == 5
    assert d.minute == 12
    assert d.second == 30
    assert d.microsecond == 450

    assert (
        NaiveDateTime(2020, 8, 15, 12)
        == NaiveDateTime(2020, 8, 15, 12, 0)
        == NaiveDateTime(2020, 8, 15, 12, 0, 0)
        == NaiveDateTime(2020, 8, 15, 12, 0, 0, 0)
    )


def test_immutable():
    d = NaiveDateTime(2020, 8, 15)
    with pytest.raises(AttributeError):
        d.year = 2021  # type: ignore[misc]


class TestFromCanonicalStr:
    def test_valid(self):
        assert NaiveDateTime.from_canonical_str(
            "2020-08-15T12:08:30"
        ) == NaiveDateTime(2020, 8, 15, 12, 8, 30)

    def test_valid_three_fractions(self):
        assert NaiveDateTime.from_canonical_str(
            "2020-08-15T12:08:30.349"
        ) == NaiveDateTime(2020, 8, 15, 12, 8, 30, 349_000)

    def test_valid_six_fractions(self):
        assert NaiveDateTime.from_canonical_str(
            "2020-08-15T12:08:30.349123"
        ) == NaiveDateTime(2020, 8, 15, 12, 8, 30, 349_123)

    def test_single_space_instead_of_T(self):
        assert NaiveDateTime.from_canonical_str(
            "2020-08-15 12:08:30"
        ) == NaiveDateTime(2020, 8, 15, 12, 8, 30)

    def test_unpadded(self):
        with pytest.raises(InvalidFormat):
            NaiveDateTime.from_canonical_str("2020-8-15T12:8:30")

    def test_overly_precise_fraction(self):
        with pytest.raises(InvalidFormat):
            NaiveDateTime.from_canonical_str(
                "2020-08-15T12:08:30.123456789123"
            )

    def test_trailing_z(self):
        with pytest.raises(InvalidFormat):
            NaiveDateTime.from_canonical_str("2020-08-15T12:08:30Z")

    def test_no_seconds(self):
        with pytest.raises(InvalidFormat):
            NaiveDateTime.from_canonical_str("2020-08-15T12:08")

    def test_empty(self):
        with pytest.raises(InvalidFormat):
            NaiveDateTime.from_canonical_str("")

    def test_garbage(self):
        with pytest.raises(InvalidFormat):
            NaiveDateTime.from_canonical_str("garbage")

    @given(text())
    def test_fuzzing(self, s: str):
        with pytest.raises(InvalidFormat):
            NaiveDateTime.from_canonical_str(s)


def test_equality():
    d = NaiveDateTime(2020, 8, 15)
    different = NaiveDateTime(2020, 8, 16)
    same = NaiveDateTime(2020, 8, 15)
    assert d == same
    assert d != different
    assert not d == different
    assert not d != same

    assert hash(d) == hash(same)
    assert hash(d) != hash(different)

    assert d == AlwaysEqual()
    assert d != NeverEqual()
    assert not d == NeverEqual()
    assert not d != AlwaysEqual()

    assert d != 42  # type: ignore[comparison-overlap]
    assert not d == 42  # type: ignore[comparison-overlap]

    # Ambiguity in system timezone
    with local_ams_tz():
        assert NaiveDateTime(2023, 10, 29, 2, 15) == NaiveDateTime.from_py(
            py_datetime(2023, 10, 29, 2, 15, fold=1)
        )


def test_repr():
    d = NaiveDateTime(2020, 8, 15, 23, 12, 9, 987_654)
    assert repr(d) == "whenever.NaiveDateTime(2020-08-15T23:12:09.987654)"
    assert (
        repr(NaiveDateTime(2020, 8, 15, 23, 12))
        == "whenever.NaiveDateTime(2020-08-15T23:12:00)"
    )


def test_canonical_str():
    d = NaiveDateTime(2020, 8, 15, 23, 12, 9, 987_654)
    assert str(d) == "2020-08-15T23:12:09.987654"
    assert d.canonical_str() == "2020-08-15T23:12:09.987654"


def test_comparison():
    d = NaiveDateTime.from_canonical_str("2020-08-15T23:12:09")
    later = NaiveDateTime.from_canonical_str("2020-08-16T00:00:00")
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
    d = NaiveDateTime(2020, 8, 15, 23, 12, 9, 987_654)
    assert d.py == py_datetime(2020, 8, 15, 23, 12, 9, 987_654)


def test_from_py():
    d = py_datetime(2020, 8, 15, 23, 12, 9, 987_654)
    assert NaiveDateTime.from_py(d) == NaiveDateTime(
        2020, 8, 15, 23, 12, 9, 987_654
    )

    with pytest.raises(ValueError, match="utc"):
        NaiveDateTime.from_py(
            py_datetime(2020, 8, 15, 23, 12, 9, 987_654, tzinfo=timezone.utc)
        )


def test_weakref():
    d = NaiveDateTime(2020, 8, 15)
    ref = weakref.ref(d)
    assert ref() == d


def test_min_max():
    assert NaiveDateTime.min == NaiveDateTime(1, 1, 1)
    assert NaiveDateTime.max == NaiveDateTime(
        9999, 12, 31, 23, 59, 59, 999_999
    )


def test_passthrough_datetime_attrs():
    d = NaiveDateTime(2020, 8, 15)
    assert d.resolution == py_datetime.resolution
    assert d.weekday() == d.py.weekday()
    assert d.date() == d.py.date()


def test_tzinfo():
    d = NaiveDateTime(2020, 8, 15)
    assert d.tzinfo is None


def test_replace():
    d = NaiveDateTime(2020, 8, 15, 23, 12, 9, 987_654)
    assert d.replace(year=2021) == NaiveDateTime(
        2021, 8, 15, 23, 12, 9, 987_654
    )
    assert d.replace(month=9) == NaiveDateTime(2020, 9, 15, 23, 12, 9, 987_654)
    assert d.replace(day=16) == NaiveDateTime(2020, 8, 16, 23, 12, 9, 987_654)
    assert d.replace(hour=0) == NaiveDateTime(2020, 8, 15, 0, 12, 9, 987_654)
    assert d.replace(minute=0) == NaiveDateTime(2020, 8, 15, 23, 0, 9, 987_654)
    assert d.replace(second=0) == NaiveDateTime(
        2020, 8, 15, 23, 12, 0, 987_654
    )
    assert d.replace(microsecond=0) == NaiveDateTime(2020, 8, 15, 23, 12, 9, 0)

    with pytest.raises(TypeError, match="tzinfo"):
        d.replace(tzinfo=timezone.utc)  # type: ignore[call-arg]


def test_add():
    d = NaiveDateTime(2020, 8, 15, 23, 12, 9, 987_654)
    assert d + timedelta(days=1, seconds=5) == NaiveDateTime(
        2020, 8, 16, 23, 12, 14, 987_654
    )


def test_add_invalid():
    d = NaiveDateTime(2020, 8, 15, 23, 12, 9, 987_654)
    with pytest.raises(TypeError, match="unsupported operand type"):
        d + 42  # type: ignore[operator]


def test_sub():
    d = NaiveDateTime(2020, 8, 15, 23, 12, 9, 987_654)
    assert d - timedelta(days=1, seconds=5) == NaiveDateTime(
        2020, 8, 14, 23, 12, 4, 987_654
    )


def test_subtract_datetime():
    d = NaiveDateTime(2020, 8, 15, 23, 12, 9, 987_654)
    other = NaiveDateTime(2020, 8, 14, 23, 12, 4, 987_654)
    assert d - other == timedelta(days=1, seconds=5)


def test_subtract_invalid():
    d = NaiveDateTime(2020, 8, 15, 23, 12, 9, 987_654)
    with pytest.raises(TypeError, match="unsupported operand type"):
        d - 42  # type: ignore[operator]


def test_pickle():
    d = NaiveDateTime(2020, 8, 15, 23, 12, 9, 987_654)
    dumped = pickle.dumps(d)
    assert len(dumped) <= len(pickle.dumps(d.py)) + 15
    assert pickle.loads(pickle.dumps(d)) == d


def test_strptime():
    assert NaiveDateTime.strptime(
        "2020-08-15 23:12", "%Y-%m-%d %H:%M"
    ) == NaiveDateTime(2020, 8, 15, 23, 12)


def test_strptime_invalid():
    with pytest.raises(ValueError):
        NaiveDateTime.strptime(
            "2020-08-15 23:12:09+0500", "%Y-%m-%d %H:%M:%S%z"
        )
