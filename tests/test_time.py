import pickle
import re
from datetime import (
    time as py_time,
    timedelta as py_timedelta,
    timezone as py_timezone,
)

import pytest

from whenever import Date, LocalDateTime, Time

from .common import AlwaysEqual, AlwaysLarger, AlwaysSmaller, NeverEqual


class TestInit:

    def test_all_args(self):
        t = Time(1, 2, 3, nanosecond=4_000)
        assert t.hour == 1
        assert t.minute == 2
        assert t.second == 3
        assert t.nanosecond == 4_000

    def test_all_kwargs(self):
        assert Time(hour=1, minute=2, second=3, nanosecond=4_000) == Time(
            1, 2, 3, nanosecond=4_000
        )

    def test_defaults(self):
        assert Time() == Time(0, 0, 0, nanosecond=0)

    def test_out_of_range(self):
        with pytest.raises(ValueError):
            Time(24, 0, 0, nanosecond=0)
        with pytest.raises(ValueError):
            Time(0, 60, 0, nanosecond=0)
        with pytest.raises(ValueError):
            Time(0, 0, 60, nanosecond=0)
        with pytest.raises(ValueError):
            Time(0, 0, 0, nanosecond=1_000_000_000)


@pytest.mark.parametrize(
    "t, expect",
    [
        (Time(1, 2, 3, nanosecond=40_000_000), "01:02:03.04"),
        (Time(1, 2, 3), "01:02:03"),
        (Time(1, 2), "01:02:00"),
        (Time(1), "01:00:00"),
    ],
)
def test_format_common_iso(t, expect):
    assert str(t) == expect
    assert t.format_common_iso() == expect


def test_py_time():
    t = Time(1, 2, 3, nanosecond=4_000_000)
    assert t.py_time() == py_time(1, 2, 3, 4_000)
    # truncation
    assert Time(nanosecond=999).py_time() == py_time(0)


def test_repr():
    t = Time(1, 2, 3, nanosecond=40_000_000)
    assert repr(t) == "Time(01:02:03.04)"


def test_replace():
    t = Time(1, 2, 3, nanosecond=4_000)
    assert t.replace() == t
    assert t.replace(hour=5) == Time(5, 2, 3, nanosecond=4_000)
    assert t.replace(minute=5) == Time(1, 5, 3, nanosecond=4_000)
    assert t.replace(second=5) == Time(1, 2, 5, nanosecond=4_000)
    assert t.replace(nanosecond=5) == Time(1, 2, 3, nanosecond=5)

    with pytest.raises(ValueError):
        t.replace(hour=24)

    with pytest.raises(TypeError):
        t.replace(tzinfo=None)  # type: ignore[call-arg]

    with pytest.raises(TypeError):
        t.replace(fold=0)  # type: ignore[call-arg]


class TestParseCommonIso:

    @pytest.mark.parametrize(
        "input, expect",
        [
            ("00:00:00.000000", Time()),
            ("01:02:03.004000", Time(1, 2, 3, nanosecond=4_000_000)),
            ("23:59:59.999999", Time(23, 59, 59, nanosecond=999_999_000)),
            ("23:59:59.99", Time(23, 59, 59, nanosecond=990_000_000)),
            ("23:59:59.123456789", Time(23, 59, 59, nanosecond=123_456_789)),
            ("23:59:59", Time(23, 59, 59)),
        ],
    )
    def test_valid(self, input, expect):
        assert Time.parse_common_iso(input) == expect

    @pytest.mark.parametrize(
        "input",
        [
            "01:02:03.004.0",
            "01:02:03+00:00",
            "32:02:03",
            "22:72:03",
            "22:72:93",
            "22112:23",
            "22:12:23,123",
            "garbage",
            "12:02:03.1234567890",  # too many digits
            "23:59:59.99999𝟙",  # non-ASCII
        ],
    )
    def test_invalid(self, input):
        with pytest.raises(
            ValueError,
            match=r"Invalid format.*" + re.escape(repr(input)),
        ):
            Time.parse_common_iso(input)


def test_eq():
    t = Time(1, 2, 3, nanosecond=4_000)
    same = Time(1, 2, 3, nanosecond=4_000)
    different = Time(1, 2, 3, nanosecond=5_000)

    assert t == same
    assert not t == different
    assert not t == NeverEqual()
    assert t == AlwaysEqual()

    assert not t != same
    assert t != different
    assert t != NeverEqual()
    assert not t != AlwaysEqual()

    assert hash(t) == hash(same)
    assert hash(t) != hash(different)


class TestFromPyTime:
    def test_valid(self):
        assert Time.from_py_time(py_time(1, 2, 3, 4)) == Time(
            1, 2, 3, nanosecond=4_000
        )

    def test_tzinfo(self):
        with pytest.raises(ValueError):
            assert Time.from_py_time(
                py_time(1, 2, 3, 4, tzinfo=py_timezone(py_timedelta(hours=1)))
            )

    def test_fold_ignored(self):
        assert Time.from_py_time(py_time(1, 2, 3, 4, fold=1)) == Time(
            1, 2, 3, nanosecond=4_000
        )

    def test_subclass(self):
        class SubclassTime(py_time):
            pass

        assert Time.from_py_time(SubclassTime(1, 2, 3, 4)) == Time(
            1, 2, 3, nanosecond=4_000
        )

    def test_invalid(self):
        with pytest.raises(TypeError):
            Time.from_py_time(234)  # type: ignore[arg-type]


def test_comparison():
    t = Time(1, 2, 3, nanosecond=4_000)
    same = Time(1, 2, 3, nanosecond=4_000)
    bigger = Time(2, 2, 3, nanosecond=4_000)
    smaller = Time(1, 2, 3, nanosecond=3_999)

    assert t <= same
    assert t <= bigger
    assert not t <= smaller
    assert t <= AlwaysLarger()
    assert not t <= AlwaysSmaller()

    assert not t < same
    assert t < bigger
    assert not t < smaller
    assert t < AlwaysLarger()
    assert not t < AlwaysSmaller()

    assert t >= same
    assert not t >= bigger
    assert t >= smaller
    assert not t >= AlwaysLarger()
    assert t >= AlwaysSmaller()

    assert not t > same
    assert not t > bigger
    assert t > smaller
    assert not t > AlwaysLarger()
    assert t > AlwaysSmaller()


def test_constants():
    assert Time.MIDNIGHT == Time()
    assert Time.NOON == Time(12)
    assert Time.MAX == Time(23, 59, 59, nanosecond=999_999_999)


def test_on():
    t = Time(1, 2, 3, nanosecond=4_000)
    assert t.on(Date(2021, 1, 2)) == LocalDateTime(
        2021, 1, 2, 1, 2, 3, nanosecond=4_000
    )


def test_pickling():
    t = Time(1, 2, 3, nanosecond=4_000)
    dumped = pickle.dumps(t)
    assert len(dumped) < len(pickle.dumps(t.py_time())) + 10
    assert pickle.loads(dumped) == t


def test_compatible_unpickle():
    dumped = (
        b"\x80\x04\x95*\x00\x00\x00\x00\x00\x00\x00\x8c\x08whenever\x94\x8c\x0b_unp"
        b"kl_time\x94\x93\x94C\x07\x01\x02\x03\xa0\x0f\x00\x00\x94\x85\x94R\x94."
    )
    assert pickle.loads(dumped) == Time(1, 2, 3, nanosecond=4_000)


def test_cannot_subclass():
    with pytest.raises(TypeError):

        class SubclassTime(Time):  # type: ignore[misc]
            pass
