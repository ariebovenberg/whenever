import pytest

from whenever import (
    Duration,
    InvalidFormat,
    Period,
    TimeDelta,
    days,
    months,
    weeks,
    years,
)

from .common import AlwaysEqual, NeverEqual


class TestInit:

    def test_init(self):
        d = Period(years=1, months=2, weeks=3, days=11)
        assert d.years == 1
        assert d.months == 2
        assert d.weeks == 3
        assert d.days == 11

    def test_defaults(self):
        d = Period()
        assert d.years == 0
        assert d.months == 0
        assert d.weeks == 0
        assert d.days == 0

    def test_factories(self):
        assert years(1) == Period(years=1)
        assert months(1) == Period(months=1)
        assert weeks(1) == Period(weeks=1)
        assert days(1) == Period(days=1)


def test_parts():
    d = Period(years=1, months=2, weeks=3, days=4)
    assert d.date_part is d
    assert d.time_part == TimeDelta.ZERO


def test_immutable():
    p = Period(
        years=1,
        months=2,
        weeks=3,
        days=4,
    )
    with pytest.raises(AttributeError):
        p.years = 2  # type: ignore[misc]


def test_equality():
    p = Period(
        years=1,
        months=2,
        weeks=3,
        days=4,
    )
    same = Period(
        years=1,
        months=2,
        weeks=3,
        days=4,
    )
    same_total = Period(
        years=1,
        months=2,
        weeks=2,
        days=11,
    )
    different = Period(
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
    assert Period.ZERO == Period()


def test_bool():
    assert not Period()
    assert Period(days=1)


@pytest.mark.parametrize(
    "p, expect",
    [
        (Period(), "P0D"),
        (Period(years=-2), "P-2Y"),
        (Period(days=1), "P1D"),
        (Period(weeks=1), "P1W"),
        (Period(months=1), "P1M"),
        (Period(years=1), "P1Y"),
        (Period(years=1, months=2, weeks=3, days=4), "P1Y2M3W4D"),
        (Period(months=2, weeks=3), "P2M3W"),
    ],
)
def test_canonical_format(p, expect):
    assert p.canonical_format() == expect
    assert str(p) == expect


class TestFromCanonicalFormat:

    def test_empty(self):
        assert Period.from_canonical_format("P0D") == Period()

    @pytest.mark.parametrize(
        "input, expect",
        [
            ("P0D", Period()),
            ("P2Y", Period(years=2)),
            ("P1M", Period(months=1)),
            ("P1W", Period(weeks=1)),
            ("P1D", Period(days=1)),
        ],
    )
    def test_single_unit(self, input, expect):
        assert Period.from_canonical_format(input) == expect

    @pytest.mark.parametrize(
        "input, expect",
        [
            ("P1Y2M3W4D", Period(years=1, months=2, weeks=3, days=4)),
            ("P2M3W", Period(months=2, weeks=3)),
            ("P-2M", Period(months=-2)),
            ("P-2Y3W", Period(years=-2, weeks=3)),
        ],
    )
    def test_multiple_units(self, input, expect):
        assert Period.from_canonical_format(input) == expect

    def test_invalid(self):
        with pytest.raises(InvalidFormat):
            Period.from_canonical_format("P")


def test_repr():
    p = Period(
        years=1,
        months=2,
        weeks=3,
        days=4,
    )
    assert repr(p) == "Period(P1Y2M3W4D)"


def test_negate():
    p = Period(years=1, months=2, weeks=3, days=-4)
    assert -p == Period(years=-1, months=-2, weeks=-3, days=4)


def test_multiply():
    p = Period(
        years=1,
        months=2,
        weeks=3,
        days=4,
    )
    assert p * 2 == Period(
        years=2,
        months=4,
        weeks=6,
        days=8,
    )
    assert p * 0 == Period.ZERO

    with pytest.raises(TypeError, match="operand"):
        p * 1.5  # type: ignore[operator]

    with pytest.raises(TypeError, match="operand"):
        p * Ellipsis  # type: ignore[operator]


def test_replace():
    p = Period(years=1, months=2, weeks=3, days=4)
    assert p.replace(years=2) == Period(years=2, months=2, weeks=3, days=4)
    assert p.replace(months=3) == Period(years=1, months=3, weeks=3, days=4)
    assert p.replace(weeks=4) == Period(years=1, months=2, weeks=4, days=4)
    assert p.replace(days=5) == Period(years=1, months=2, weeks=3, days=5)


class TestAdd:

    def test_same_type(self):
        p = Period(years=1, months=2, weeks=3, days=4)
        q = Period(years=-1, months=3, weeks=-1)
        assert p + q == Period(months=5, weeks=2, days=4)
        assert q + p == Period(months=5, weeks=2, days=4)

        with pytest.raises(TypeError, match="unsupported operand"):
            p + 32  # type: ignore[operator]

        with pytest.raises(TypeError, match="unsupported operand"):
            32 + p  # type: ignore[operator]

    def test_duration(self):
        p = Period(years=1, months=2, weeks=3, days=4)
        d = TimeDelta(hours=1, minutes=2, seconds=3, microseconds=400_004)
        assert p + d == Duration(
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
        p = Period(years=1, months=2, weeks=3, days=4)
        with pytest.raises(TypeError, match="unsupported operand"):
            p + 32  # type: ignore[operator]

        with pytest.raises(TypeError, match="unsupported operand"):
            32 + p  # type: ignore[operator]


class TestSubtract:

    def test_same_type(self):
        p = Period(years=1, months=2, weeks=3, days=4)
        q = Period(years=-1, months=3, weeks=-1)
        assert p - q == Period(years=2, months=-1, weeks=4, days=4)
        assert q - p == Period(years=-2, months=1, weeks=-4, days=-4)

    def test_duration(self):
        p = Period(years=1, months=2, weeks=3, days=4)
        d = TimeDelta(hours=1, minutes=2, seconds=3, microseconds=400_004)
        assert p - d == Duration(
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
        assert d - p == Duration(
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
        p = Period(years=1, months=2, weeks=3, days=4)
        with pytest.raises(TypeError, match="unsupported operand"):
            p - 32  # type: ignore[operator]

        with pytest.raises(TypeError, match="unsupported operand"):
            32 - p  # type: ignore[operator]


def test_as_tuple():
    p = Period(years=1, months=2, weeks=3, days=4)
    assert p.as_tuple() == (1, 2, 3, 4)


def test_abs():
    p = Period(years=1, months=2, weeks=3, days=-4)
    assert abs(p) == Period(years=1, months=2, weeks=3, days=4)
