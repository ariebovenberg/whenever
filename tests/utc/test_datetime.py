import datetime as py_datetime
import pickle
import weakref

import pytest
from hypothesis import given
from hypothesis.strategies import text

from whenever import Nothing
from whenever.utc import DateTime


def test_imports():
    from whenever import utc

    assert utc.__name__ == "whenever.utc"


def test_cannot_construct():
    with pytest.raises(TypeError, match="use static methods.*instead"):
        DateTime()  # type: ignore[call-arg]


def test_minimal():
    d = DateTime.new(2020, 8, 15, 5, 12, 30, 450).unwrap()
    assert d.year == 2020
    assert d.month == 8
    assert d.day == 15
    assert d.hour == 5
    assert d.minute == 12
    assert d.second == 30
    assert d.nanosecond == 450

    assert (
        DateTime.new(2020, 8, 15, 12)
        == DateTime.new(2020, 8, 15, 12, 0)
        == DateTime.new(2020, 8, 15, 12, 0, 0)
        == DateTime.new(2020, 8, 15, 12, 0, 0, 0)
    )


def test_new_invalid():
    assert DateTime.new(2020, 2, 30) == Nothing()


def test_immutable():
    d = DateTime.new(2020, 8, 15).unwrap()
    with pytest.raises(AttributeError):
        d.year = 2021  # type: ignore[misc]


class TestFromStr:
    def test_valid(self):
        assert DateTime.from_str("2020-08-15T12:08:30Z") == DateTime.new(
            2020, 8, 15, 12, 8, 30
        )

    def test_valid_unpadded(self):
        assert DateTime.from_str("2020-8-15T12:8:30Z") == DateTime.new(
            2020, 8, 15, 12, 8, 30
        )

    def test_valid_fraction(self):
        assert DateTime.from_str("2020-08-15T12:08:30.346Z") == DateTime.new(
            2020, 8, 15, 12, 8, 30, 346_000_000
        )

    def test_overly_precise_fraction(self):
        assert DateTime.from_str(
            "2020-08-15T12:08:30.123456789123Z"
        ) == DateTime.new(2020, 8, 15, 12, 8, 30, 123_456_789)

    def test_invalid_lowercase_z(self):
        assert not DateTime.from_str("2020-08-15T12:08:30z")

    def test_no_trailing_z(self):
        assert not DateTime.from_str("2020-08-15T12:08:30")

    def test_no_seconds(self):
        assert not DateTime.from_str("2020-08-15T12:08Z")

    def test_empty(self):
        assert not DateTime.from_str("")

    def test_garbage(self):
        assert not DateTime.from_str("garbage")

    @given(text())
    def test_fuzzing(self, s: str):
        DateTime.from_str(s)  # should not raise an exception, ever


def test_equality():
    d = DateTime.new(2020, 8, 15).unwrap()
    different = DateTime.new(2020, 8, 16).unwrap()
    same = DateTime.new(2020, 8, 15).unwrap()
    assert d == same
    assert d != different
    assert not d == different
    assert not d != same

    assert hash(d) == hash(same)
    assert hash(d) != hash(different)

    assert d != 42  # type: ignore[comparison-overlap]
    assert not d == 42  # type: ignore[comparison-overlap]

    assert (
        DateTime.new(2020, 8, 15, 12, 8, 30).unwrap()
        != DateTime.new(2020, 8, 15, 12, 8, 31).unwrap()
    )


def test_timestamp():
    assert DateTime.new(1970, 1, 1).unwrap().timestamp() == 0
    assert (
        DateTime.new(2020, 8, 15, 12, 8, 30).unwrap().timestamp()
        == 1_597_493_310
    )


def test_from_timestamp():
    assert (
        DateTime.from_timestamp(0).unwrap()
        == DateTime.new(1970, 1, 1).unwrap()
    )
    assert (
        DateTime.from_timestamp(1_597_493_310).unwrap()
        == DateTime.new(2020, 8, 15, 12, 8, 30).unwrap()
    )
    # TODO: test out-of-bounds of i64 and datetime


def test_timestamp_millis():
    assert DateTime.new(1970, 1, 1).unwrap().timestamp_millis() == 0
    assert (
        DateTime.new(2020, 8, 15, 12, 8, 30, 123_456_789)
        .unwrap()
        .timestamp_millis()
        == 1_597_493_310_123
    )
    # TODO: test out-of-bounds of i64 and datetime


def test_from_timestamp_millis():
    assert (
        DateTime.from_timestamp_millis(0).unwrap()
        == DateTime.new(1970, 1, 1).unwrap()
    )
    assert (
        DateTime.from_timestamp_millis(1_597_493_310_123).unwrap()
        == DateTime.new(2020, 8, 15, 12, 8, 30, 123_000_000).unwrap()
    )


def test_repr():
    d = DateTime.new(2020, 8, 15, 23, 12, 9, 987_654_000).unwrap()
    assert repr(d) == "whenever.utc.DateTime(2020-08-15T23:12:09.987654Z)"


def test_pickle(benchmark):
    d = DateTime.new(2020, 8, 15, 23, 12, 9, 987_654_000).unwrap()
    dumped = benchmark(pickle.dumps, d)
    assert pickle.loads(dumped) == d


def test_comparison():
    d = DateTime.from_str("2020-08-15T23:12:09Z").unwrap()
    later = DateTime.from_str("2020-08-16T00:00:00Z").unwrap()
    assert d < later
    assert d <= later
    assert later > d
    assert later >= d

    with pytest.raises(TypeError):
        d < 42  # type: ignore[operator]


def test_to_py():
    d = DateTime.new(2020, 8, 15, 23, 12, 9, 987_654_000).unwrap()
    assert d.to_py() == py_datetime.datetime(
        2020, 8, 15, 23, 12, 9, 987_654, tzinfo=py_datetime.timezone.utc
    )


def test_from_py():
    d = py_datetime.datetime(
        2020, 8, 15, 23, 12, 9, 987_654, tzinfo=py_datetime.timezone.utc
    )
    assert (
        DateTime.from_py(d).unwrap()
        == DateTime.new(2020, 8, 15, 23, 12, 9, 987_654_000).unwrap()
    )


def test_now():
    now = DateTime.now()
    py_now = py_datetime.datetime.now(py_datetime.timezone.utc)
    assert py_now - now.to_py() < py_datetime.timedelta(seconds=1)


def test_weakref():
    d = DateTime.new(2020, 8, 15).unwrap()
    ref = weakref.ref(d)
    assert ref() == d
