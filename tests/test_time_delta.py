import pickle
import weakref
from copy import copy, deepcopy
from datetime import timedelta

import pytest
from pytest import approx

from whenever import (
    DateDelta,
    InvalidFormat,
    TimeDelta,
    hours,
    microseconds,
    minutes,
    seconds,
)

from .common import AlwaysEqual, AlwaysLarger, AlwaysSmaller, NeverEqual


class TestInit:

    def test_basics(self):
        d = TimeDelta(hours=1, minutes=2, seconds=3, microseconds=4)
        # the components are not accessible directly
        assert not hasattr(d, "hours")

    def test_defaults(self):
        d = TimeDelta()
        assert d.in_microseconds() == 0


def test_parts():
    d = TimeDelta(hours=1, minutes=2, seconds=3, microseconds=4)
    assert d._date_part == DateDelta.ZERO
    assert d._time_part is d


def test_factories():
    assert hours(1) == TimeDelta(hours=1)
    assert minutes(1) == TimeDelta(minutes=1)
    assert seconds(1) == TimeDelta(seconds=1)
    assert microseconds(1) == TimeDelta(microseconds=1)


@pytest.mark.parametrize(
    "kwargs, expected",
    [
        (dict(), TimeDelta()),
        (dict(hours=1), TimeDelta(microseconds=3_600_000_000)),
        (dict(minutes=1), TimeDelta(microseconds=60_000_000)),
        (dict(seconds=1), TimeDelta(microseconds=1_000_000)),
        (
            dict(minutes=90, microseconds=-3_600_000_000),
            TimeDelta(minutes=30),
        ),
    ],
)
def test_normalization(kwargs, expected):
    assert TimeDelta(**kwargs) == expected


def test_fractional():
    assert TimeDelta(minutes=1.5) == TimeDelta(seconds=90)


def test_avoids_floating_point_errors():
    assert TimeDelta(hours=10_000_001.0, microseconds=1) == TimeDelta(
        microseconds=int(10_000_001 * 3_600_000_000) + 1
    )


def test_zero():
    assert TimeDelta().ZERO == TimeDelta()
    assert TimeDelta.ZERO == TimeDelta(
        hours=0, minutes=0, seconds=0, microseconds=0
    )


def test_boolean():
    assert not TimeDelta(hours=0, minutes=0, seconds=0, microseconds=0)
    assert not TimeDelta(hours=1, minutes=-60)
    assert TimeDelta(microseconds=1)


def test_aggregations():
    d = TimeDelta(hours=1, minutes=2, seconds=3, microseconds=4)
    assert d.in_hours() == approx(1 + 2 / 60 + 3 / 3_600 + 4 / 3_600_000_000)
    assert d.in_minutes() == approx(60 + 2 + 3 / 60 + 4 / 60_000_000)
    assert d.in_seconds() == approx(3600 + 2 * 60 + 3 + 4 / 1_000_000)
    assert (
        d.in_microseconds()
        == 3_600_000_000 + 2 * 60_000_000 + 3 * 1_000_000 + 4
    )


def test_equality():
    d = TimeDelta(hours=1, minutes=2, seconds=3, microseconds=4)
    same = TimeDelta(hours=1, minutes=2, seconds=3, microseconds=4)
    same_total = TimeDelta(hours=0, minutes=62, seconds=3, microseconds=4)
    different = TimeDelta(hours=1, minutes=2, seconds=3, microseconds=5)
    assert d == same
    assert d == same_total
    assert not d == different
    assert not d == NeverEqual()
    assert d == AlwaysEqual()
    assert not d != same
    assert not d != same_total
    assert d != different
    assert d != NeverEqual()
    assert not d != AlwaysEqual()

    assert hash(d) == hash(same)
    assert hash(d) == hash(same_total)
    assert hash(d) != hash(different)


def test_comparison():
    d = TimeDelta(hours=1, minutes=2, seconds=3, microseconds=4)
    same = TimeDelta(hours=1, minutes=2, seconds=3, microseconds=4)
    same_total = TimeDelta(hours=0, minutes=62, seconds=3, microseconds=4)
    bigger = TimeDelta(hours=1, minutes=2, seconds=3, microseconds=5)
    smaller = TimeDelta(hours=1, minutes=2, seconds=3, microseconds=3)

    assert d <= same
    assert d <= same_total
    assert d <= bigger
    assert not d <= smaller
    assert d <= AlwaysLarger()
    assert not d <= AlwaysSmaller()

    assert not d < same
    assert not d < same_total
    assert d < bigger
    assert not d < smaller
    assert d < AlwaysLarger()
    assert not d < AlwaysSmaller()

    assert d >= same
    assert d >= same_total
    assert not d >= bigger
    assert d >= smaller
    assert not d >= AlwaysLarger()
    assert d >= AlwaysSmaller()

    assert not d > same
    assert not d > same_total
    assert not d > bigger
    assert d > smaller
    assert not d > AlwaysLarger()
    assert d > AlwaysSmaller()


@pytest.mark.parametrize(
    "d, expected",
    [
        (
            TimeDelta(hours=1, minutes=2, seconds=3, microseconds=4),
            "01:02:03.000004",
        ),
        (
            TimeDelta(hours=1, minutes=-2, seconds=3, microseconds=-4),
            "00:58:02.999996",
        ),
        (
            TimeDelta(hours=1, minutes=2, seconds=3, microseconds=50_000),
            "01:02:03.05",
        ),
        (
            TimeDelta(hours=1, minutes=120, seconds=3),
            "03:00:03",
        ),
        (
            TimeDelta(),
            "00:00:00",
        ),
        (
            TimeDelta(hours=5),
            "05:00:00",
        ),
        (
            TimeDelta(hours=400),
            "400:00:00",
        ),
        (
            TimeDelta(minutes=-4),
            "-00:04:00",
        ),
    ],
)
def test_canonical_format(d, expected):
    assert d.canonical_format() == expected
    assert str(d) == expected


@pytest.mark.parametrize(
    "d, expected",
    [
        (
            TimeDelta(hours=1, minutes=2, seconds=3, microseconds=4),
            "PT1H2M3.000004S",
        ),
        (
            TimeDelta(hours=1, minutes=-2, seconds=3, microseconds=-4),
            "PT58M2.999996S",
        ),
        (
            TimeDelta(hours=1, minutes=2, seconds=3, microseconds=50_000),
            "PT1H2M3.05S",
        ),
        (
            TimeDelta(hours=1, minutes=120, seconds=3),
            "PT3H3S",
        ),
        (
            TimeDelta(),
            "PT0S",
        ),
        (
            TimeDelta(microseconds=1),
            "PT0.000001S",
        ),
        (
            TimeDelta(microseconds=-1),
            "PT-0.000001S",
        ),
        (
            TimeDelta(seconds=2, microseconds=-3),
            "PT1.999997S",
        ),
        (
            TimeDelta(hours=5),
            "PT5H",
        ),
        (
            TimeDelta(hours=400),
            "PT400H",
        ),
        (
            TimeDelta(minutes=-4),
            "PT-4M",
        ),
    ],
)
def test_common_iso8601(d, expected):
    assert d.common_iso8601() == expected


class TestFromCommonIso8601:

    @pytest.mark.parametrize(
        "s, expected",
        [
            (
                "PT1H2M3.000004S",
                TimeDelta(hours=1, minutes=2, seconds=3, microseconds=4),
            ),
            (
                "PT58M2.999996S",
                TimeDelta(hours=1, minutes=-2, seconds=3, microseconds=-4),
            ),
            (
                "PT1H2M3.05S",
                TimeDelta(hours=1, minutes=2, seconds=3, microseconds=50_000),
            ),
            ("PT3H3S", TimeDelta(hours=1, minutes=120, seconds=3)),
            ("PT0S", TimeDelta()),
            ("PT0.000001S", TimeDelta(microseconds=1)),
            ("PT-0.000001S", TimeDelta(microseconds=-1)),
            ("PT1.999997S", TimeDelta(seconds=2, microseconds=-3)),
            ("PT5H", TimeDelta(hours=5)),
            ("PT400H", TimeDelta(hours=400)),
            ("PT-4M", TimeDelta(minutes=-4)),
            ("P0D", TimeDelta()),
            ("PT0S", TimeDelta()),
            ("P0YT3M", TimeDelta(minutes=3)),
            ("-P-0YT+3M", TimeDelta(minutes=-3)),
            ("PT0M", TimeDelta()),
        ],
    )
    def test_valid(self, s, expected):
        assert TimeDelta.from_common_iso8601(s) == expected

    @pytest.mark.parametrize(
        "s",
        ["P1D", "P1Y", "T1H", "PT4M3H", "PT1.5H"],
    )
    def test_invalid(self, s) -> None:
        with pytest.raises(InvalidFormat):
            TimeDelta.from_common_iso8601(s)


class TestFromCanonicalFormat:

    @pytest.mark.parametrize(
        "s, expected",
        [
            (
                "01:02:03.000004",
                TimeDelta(hours=1, minutes=2, seconds=3, microseconds=4),
            ),
            ("00:04:00", TimeDelta(minutes=4)),
            ("00:00:00", TimeDelta()),
            ("05:00:00", TimeDelta(hours=5)),
            ("400:00:00", TimeDelta(hours=400)),
            ("00:00:00.000000", TimeDelta()),
            ("00:00:00.999955", TimeDelta(microseconds=999_955)),
            ("00:00:00.99", TimeDelta(microseconds=990_000)),
            ("-00:04:00", TimeDelta(minutes=-4)),
            ("+00:04:00", TimeDelta(minutes=4)),
        ],
    )
    def test_valid(self, s, expected):
        assert TimeDelta.from_canonical_format(s) == expected

    @pytest.mark.parametrize(
        "s",
        ["00:60:00", "00:00:60"],
    )
    def test_invalid_too_large(self, s):
        with pytest.raises(InvalidFormat):
            TimeDelta.from_canonical_format(s)

    @pytest.mark.parametrize(
        "s",
        [
            "00:00:00.000000.000000",
            "00:00:00.0000.00" "00:00.00.0000",
            "00.00.00.0000",
            "+0000:00",
        ],
    )
    def test_invalid_seperators(self, s):
        with pytest.raises(InvalidFormat):
            TimeDelta.from_canonical_format(s)


def test_addition():
    d = TimeDelta(hours=1, minutes=2, seconds=3, microseconds=4)
    assert d + TimeDelta() == d
    assert d + TimeDelta(hours=1) == TimeDelta(
        hours=2, minutes=2, seconds=3, microseconds=4
    )
    assert d + TimeDelta(minutes=-1) == TimeDelta(
        hours=1, minutes=1, seconds=3, microseconds=4
    )

    with pytest.raises(TypeError, match="unsupported operand"):
        d + Ellipsis  # type: ignore[operator]


def test_subtraction():
    d = TimeDelta(hours=1, minutes=2, seconds=3, microseconds=4)
    assert d - TimeDelta() == d
    assert d - TimeDelta(hours=1) == TimeDelta(
        hours=0, minutes=2, seconds=3, microseconds=4
    )
    assert d - TimeDelta(minutes=-1) == TimeDelta(
        hours=1, minutes=3, seconds=3, microseconds=4
    )

    with pytest.raises(TypeError, match="unsupported operand"):
        d - Ellipsis  # type: ignore[operator]


def test_multiply():
    d = TimeDelta(hours=1, minutes=2, seconds=3, microseconds=4)
    assert d * 2 == TimeDelta(hours=2, minutes=4, seconds=6, microseconds=8)
    assert d * 0.5 == TimeDelta(
        hours=0, minutes=31, seconds=1, microseconds=500_002
    )

    with pytest.raises(TypeError, match="unsupported operand"):
        d * Ellipsis  # type: ignore[operator]


class TestDivision:

    def test_by_number(self):
        d = TimeDelta(hours=1, minutes=2, seconds=3, microseconds=4)
        assert d / 2 == TimeDelta(
            hours=0, minutes=31, seconds=1, microseconds=500_002
        )
        assert d / 0.5 == TimeDelta(
            hours=2, minutes=4, seconds=6, microseconds=8
        )

    def test_divide_by_duration(self):
        d = TimeDelta(hours=1, minutes=2, seconds=3, microseconds=4)
        assert d / TimeDelta(hours=1) == approx(
            1 + 2 / 60 + 3 / 3_600 + 4 / 3_600_000_000
        )

    def test_divide_by_zero(self):
        d = TimeDelta(hours=1, minutes=2, seconds=3, microseconds=4)
        with pytest.raises(ZeroDivisionError):
            d / TimeDelta()

        with pytest.raises(ZeroDivisionError):
            d / 0

    def test_invalid(self):
        d = TimeDelta(hours=1, minutes=2, seconds=3, microseconds=4)
        with pytest.raises(TypeError):
            d / "invalid"  # type: ignore[operator]


def test_negate():
    assert TimeDelta.ZERO == -TimeDelta.ZERO
    assert TimeDelta(
        hours=-1, minutes=2, seconds=-3, microseconds=4
    ) == -TimeDelta(hours=1, minutes=-2, seconds=3, microseconds=-4)


@pytest.mark.parametrize(
    "d",
    [
        TimeDelta(hours=1, minutes=2, seconds=3, microseconds=4),
        TimeDelta.ZERO,
        TimeDelta(hours=-2, minutes=-15),
    ],
)
def test_pos(d):
    assert d is +d


def test_py_timedelta():
    assert TimeDelta().py_timedelta() == timedelta(0)
    assert TimeDelta(
        hours=1, minutes=2, seconds=3, microseconds=4
    ).py_timedelta() == timedelta(
        hours=1, minutes=2, seconds=3, microseconds=4
    )


def test_from_timedelta():
    assert TimeDelta.from_py_timedelta(timedelta(0)) == TimeDelta()
    assert TimeDelta.from_py_timedelta(
        timedelta(weeks=8, hours=1, minutes=2, seconds=3, microseconds=4)
    ) == TimeDelta(hours=1 + 7 * 24 * 8, minutes=2, seconds=3, microseconds=4)


def test_tuple():
    d = TimeDelta(hours=1, minutes=2, seconds=-3, microseconds=4_060_000)
    hms = d.as_tuple()
    assert all(isinstance(x, int) for x in hms)
    assert hms == (1, 2, 1, 60_000)
    assert TimeDelta(hours=-2, minutes=-15).as_tuple() == (-2, -15, 0, 0)
    assert TimeDelta.ZERO.as_tuple() == (0, 0, 0, 0)


def test_abs():
    assert abs(TimeDelta()) == TimeDelta()
    assert abs(
        TimeDelta(hours=-1, minutes=-2, seconds=-3, microseconds=-4)
    ) == TimeDelta(hours=1, minutes=2, seconds=3, microseconds=4)
    assert abs(TimeDelta(hours=1)) == TimeDelta(hours=1)


def test_weakref():
    d = TimeDelta(hours=1, minutes=2, seconds=3, microseconds=4)
    r = weakref.ref(d)
    assert r() is d
    del d
    assert r() is None


def test_copy():
    d = TimeDelta(hours=1, minutes=2, seconds=3, microseconds=4)
    assert copy(d) is d
    assert deepcopy(d) is d


def test_pickling():
    d = TimeDelta(hours=1, minutes=2, seconds=3, microseconds=4)
    dumped = pickle.dumps(d)
    assert len(dumped) < len(pickle.dumps(d.py_timedelta())) + 10
    assert pickle.loads(dumped) == d


def test_compatible_unpickle():
    dumped = (
        b"\x80\x04\x95)\x00\x00\x00\x00\x00\x00\x00\x8c\x08whenever\x94\x8c\r_unpkl_t"
        b"delta\x94\x93\x94\x8a\x05\xc4x\xe8\xdd\x00\x85\x94R\x94."
    )
    assert pickle.loads(dumped) == TimeDelta(
        hours=1, minutes=2, seconds=3, microseconds=4
    )
