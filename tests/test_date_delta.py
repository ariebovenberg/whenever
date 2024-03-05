import pytest

from whenever import (
    DateDelta,
    DateTimeDelta,
    InvalidFormat,
    TimeDelta,
    days,
    months,
    weeks,
    years,
)

from .common import AlwaysEqual, NeverEqual


class TestInit:

    def test_init(self):
        d = DateDelta(years=1, months=2, weeks=3, days=11)
        assert d.years == 1
        assert d.months == 2
        assert d.weeks == 3
        assert d.days == 11

    def test_defaults(self):
        d = DateDelta()
        assert d.years == 0
        assert d.months == 0
        assert d.weeks == 0
        assert d.days == 0

    def test_factories(self):
        assert years(1) == DateDelta(years=1)
        assert months(1) == DateDelta(months=1)
        assert weeks(1) == DateDelta(weeks=1)
        assert days(1) == DateDelta(days=1)


def test_parts():
    d = DateDelta(years=1, months=2, weeks=3, days=4)
    assert d.date_part is d
    assert d.time_part == TimeDelta.ZERO


def test_immutable():
    p = DateDelta(
        years=1,
        months=2,
        weeks=3,
        days=4,
    )
    with pytest.raises(AttributeError):
        p.years = 2  # type: ignore[misc]


def test_equality():
    p = DateDelta(
        years=1,
        months=2,
        weeks=3,
        days=4,
    )
    same = DateDelta(
        years=1,
        months=2,
        weeks=3,
        days=4,
    )
    same_total = DateDelta(
        years=1,
        months=2,
        weeks=2,
        days=11,
    )
    different = DateDelta(
        years=1,
        months=2,
        weeks=3,
        days=5,
    )
    assert p == same
    assert not p == same_total
    assert not p == different
    assert not p == NeverEqual()
    assert p == AlwaysEqual()
    assert not p != same
    assert p != same_total
    assert p != different
    assert p != NeverEqual()
    assert not p != AlwaysEqual()
    assert hash(p) == hash(same)
    assert hash(p) != hash(same_total)
    assert hash(p) != hash(different)


def test_zero():
    assert DateDelta.ZERO == DateDelta()


def test_bool():
    assert not DateDelta()
    assert DateDelta(days=1)


@pytest.mark.parametrize(
    "p, expect",
    [
        (DateDelta(), "P0D"),
        (DateDelta(years=-2), "P-2Y"),
        (DateDelta(days=1), "P1D"),
        (DateDelta(weeks=1), "P1W"),
        (DateDelta(months=1), "P1M"),
        (DateDelta(years=1), "P1Y"),
        (DateDelta(years=1, months=2, weeks=3, days=4), "P1Y2M3W4D"),
        (DateDelta(months=2, weeks=3), "P2M3W"),
    ],
)
def test_canonical_format(p, expect):
    assert p.canonical_format() == expect
    assert str(p) == expect


class TestFromCanonicalFormat:

    def test_empty(self):
        assert DateDelta.from_canonical_format("P0D") == DateDelta()

    @pytest.mark.parametrize(
        "input, expect",
        [
            ("P0D", DateDelta()),
            ("P2Y", DateDelta(years=2)),
            ("P1M", DateDelta(months=1)),
            ("P1W", DateDelta(weeks=1)),
            ("P1D", DateDelta(days=1)),
        ],
    )
    def test_single_unit(self, input, expect):
        assert DateDelta.from_canonical_format(input) == expect

    @pytest.mark.parametrize(
        "input, expect",
        [
            ("P1Y2M3W4D", DateDelta(years=1, months=2, weeks=3, days=4)),
            ("P2M3W", DateDelta(months=2, weeks=3)),
            ("P-2M", DateDelta(months=-2)),
            ("P-2Y3W", DateDelta(years=-2, weeks=3)),
        ],
    )
    def test_multiple_units(self, input, expect):
        assert DateDelta.from_canonical_format(input) == expect

    def test_invalid(self):
        with pytest.raises(InvalidFormat):
            DateDelta.from_canonical_format("P")


def test_repr():
    p = DateDelta(years=1, months=2, weeks=3, days=4)
    assert repr(p) == "DateDelta(P1Y2M3W4D)"


def test_negate():
    p = DateDelta(years=1, months=2, weeks=3, days=-4)
    assert -p == DateDelta(years=-1, months=-2, weeks=-3, days=4)


def test_multiply():
    p = DateDelta(
        years=1,
        months=2,
        weeks=3,
        days=4,
    )
    assert p * 2 == DateDelta(
        years=2,
        months=4,
        weeks=6,
        days=8,
    )
    assert p * 0 == DateDelta.ZERO

    with pytest.raises(TypeError, match="operand"):
        p * 1.5  # type: ignore[operator]

    with pytest.raises(TypeError, match="operand"):
        p * Ellipsis  # type: ignore[operator]


def test_replace():
    p = DateDelta(years=1, months=2, weeks=3, days=4)
    assert p.replace(years=2) == DateDelta(years=2, months=2, weeks=3, days=4)
    assert p.replace(months=3) == DateDelta(years=1, months=3, weeks=3, days=4)
    assert p.replace(weeks=4) == DateDelta(years=1, months=2, weeks=4, days=4)
    assert p.replace(days=5) == DateDelta(years=1, months=2, weeks=3, days=5)


class TestAdd:

    def test_same_type(self):
        p = DateDelta(years=1, months=2, weeks=3, days=4)
        q = DateDelta(years=-1, months=3, weeks=-1)
        assert p + q == DateDelta(months=5, weeks=2, days=4)
        assert q + p == DateDelta(months=5, weeks=2, days=4)

        with pytest.raises(TypeError, match="unsupported operand"):
            p + 32  # type: ignore[operator]

        with pytest.raises(TypeError, match="unsupported operand"):
            32 + p  # type: ignore[operator]

    def test_duration(self):
        p = DateDelta(years=1, months=2, weeks=3, days=4)
        d = TimeDelta(hours=1, minutes=2, seconds=3, microseconds=400_004)
        assert p + d == DateTimeDelta(
            years=1,
            months=2,
            weeks=3,
            days=4,
            hours=1,
            minutes=2,
            seconds=3,
            microseconds=400_004,
        )
        assert p + d == d + p

    def test_unsupported(self):
        p = DateDelta(years=1, months=2, weeks=3, days=4)
        with pytest.raises(TypeError, match="unsupported operand"):
            p + 32  # type: ignore[operator]

        with pytest.raises(TypeError, match="unsupported operand"):
            32 + p  # type: ignore[operator]


class TestSubtract:

    def test_same_type(self):
        p = DateDelta(years=1, months=2, weeks=3, days=4)
        q = DateDelta(years=-1, months=3, weeks=-1)
        assert p - q == DateDelta(years=2, months=-1, weeks=4, days=4)
        assert q - p == DateDelta(years=-2, months=1, weeks=-4, days=-4)

    def test_duration(self):
        p = DateDelta(years=1, months=2, weeks=3, days=4)
        d = TimeDelta(hours=1, minutes=2, seconds=3, microseconds=400_004)
        assert p - d == DateTimeDelta(
            years=1,
            months=2,
            weeks=3,
            days=4,
            hours=-1,
            minutes=-2,
            seconds=-3,
            microseconds=-400_004,
        )
        assert p - d == -d + p
        assert d - p == DateTimeDelta(
            years=-1,
            months=-2,
            weeks=-3,
            days=-4,
            hours=1,
            minutes=2,
            seconds=3,
            microseconds=400_004,
        )

    def test_unsupported(self):
        p = DateDelta(years=1, months=2, weeks=3, days=4)
        with pytest.raises(TypeError, match="unsupported operand"):
            p - 32  # type: ignore[operator]

        with pytest.raises(TypeError, match="unsupported operand"):
            32 - p  # type: ignore[operator]


def test_as_tuple():
    p = DateDelta(years=1, months=2, weeks=3, days=4)
    assert p.as_tuple() == (1, 2, 3, 4)


def test_abs():
    p = DateDelta(years=1, months=2, weeks=3, days=-4)
    assert abs(p) == DateDelta(years=1, months=2, weeks=3, days=4)
