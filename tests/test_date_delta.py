import pickle
import re
from copy import copy, deepcopy

import pytest

from whenever import (  # DateTimeDelta,; TimeDelta,
    DateDelta,
    days,
    months,
    weeks,
    years,
)

from .common import AlwaysEqual, NeverEqual

MAX_I64 = 1 << 64


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

    @pytest.mark.parametrize(
        "kwargs",
        [
            {"years": 10_000},
            {"years": -10_000},
            {"years": MAX_I64},
            {"years": -MAX_I64},
            {"months": 10_000 * 12},
            {"months": -10_000 * 12},
            {"months": MAX_I64},
            {"months": -MAX_I64},
            {"weeks": 10_000 * 53},
            {"weeks": -10_000 * 53},
            {"weeks": MAX_I64},
            {"weeks": -MAX_I64},
            {"days": 10_000 * 366},
            {"days": -10_000 * 366},
            {"days": MAX_I64},
            {"days": -MAX_I64},
        ],
    )
    def test_bounds(self, kwargs):
        with pytest.raises((ValueError, OverflowError)):
            DateDelta(**kwargs)


class TestFactories:
    def test_valid(self):
        assert years(5) == DateDelta(years=5)
        assert months(8) == DateDelta(months=8)
        assert weeks(2) == DateDelta(weeks=2)
        assert days(4) == DateDelta(days=4)

    @pytest.mark.parametrize(
        "factory, value",
        [
            (years, 10_000),
            (years, -10_000),
            (months, 10_000 * 12),
            (months, -10_000 * 12),
            (weeks, 10_000 * 53),
            (weeks, -10_000 * 53),
            (days, 10_000 * 366),
            (days, -10_000 * 366),
        ],
    )
    def test_bounds(self, factory, value):
        with pytest.raises((ValueError, OverflowError)):
            factory(value)


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
    p = DateDelta(years=1, months=2, weeks=3, days=4)
    same = DateDelta(years=1, months=2, weeks=3, days=4)
    same_total = DateDelta(years=1, months=2, weeks=2, days=11)
    different = DateDelta(years=1, months=2, weeks=3, days=5)
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
        (DateDelta(months=2, weeks=-3), "P2M-3W"),
    ],
)
def test_string_formats(p, expect):
    assert p.canonical_format() == expect
    assert p.common_iso8601() == expect
    assert str(p) == expect


class TestFromCanonicalFormat:

    def test_empty(self):
        assert DateDelta.from_canonical_format("P0D") == DateDelta()
        assert DateDelta.from_common_iso8601("P0D") == DateDelta()

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
        assert DateDelta.from_common_iso8601(input) == expect

    @pytest.mark.parametrize(
        "input, expect",
        [
            ("P1Y2M3W4D", DateDelta(years=1, months=2, weeks=3, days=4)),
            ("P2M3W", DateDelta(months=2, weeks=3)),
            ("P-2M", DateDelta(months=-2)),
            ("P-2Y3W", DateDelta(years=-2, weeks=3)),
            ("P1Y2M3W4D", DateDelta(years=1, months=2, weeks=3, days=4)),
            ("P2M3W", DateDelta(months=2, weeks=3)),
            ("P-2M", DateDelta(months=-2)),
            ("-P-2Y+3W", DateDelta(years=2, weeks=-3)),
        ],
    )
    def test_multiple_units(self, input, expect):
        assert DateDelta.from_canonical_format(input) == expect
        assert DateDelta.from_common_iso8601(input) == expect

    @pytest.mark.parametrize(
        "s",
        [
            "",
            "P",  # no components
            "Y",
            "5Y",  # no prefix
            "-5Y",  # no prefix
            "P8",  # digits without units
            "P8M3",  # digits without units
            "P3D7Y",  # components out of order
            "P--2D",
            "P++2D",
            "P+-2D",
            "P-D",
            "P+D",
            "P-",
            "P+",
            f"P{MAX_I64+2}Y",
            f"P-{MAX_I64+2}Y",
        ],
    )
    def test_invalid_format(self, s):
        with pytest.raises(
            ValueError,
            match=r"Invalid date delta format.*" + re.escape(s),
        ):
            DateDelta.from_canonical_format(s)

        with pytest.raises(
            ValueError,
            match=r"Invalid date delta format.*" + re.escape(s),
        ):
            DateDelta.from_common_iso8601(s)

    def test_invalid_type(self):
        with pytest.raises(TypeError):
            DateDelta.from_canonical_format(1)  # type: ignore[arg-type]

        with pytest.raises(TypeError):
            DateDelta.from_common_iso8601(1)  # type: ignore[arg-type]

    def test_time_component_not_allowed(self):
        with pytest.raises(ValueError, match=r"Invalid date delta format"):
            DateDelta.from_common_iso8601("P1Y2M3W4DT1H2M3S")

        with pytest.raises(
            ValueError,
            match=r"Invalid date delta format",
        ):
            DateDelta.from_canonical_format("P1Y2M3W4DT1H2M3S")


def test_repr():
    p = DateDelta(years=1, months=2, weeks=3, days=4)
    assert repr(p) == "DateDelta(P1Y2M3W4D)"


def test_negate():
    p = DateDelta(years=1, months=2, weeks=3, days=-4)
    assert -p == DateDelta(years=-1, months=-2, weeks=-3, days=4)


@pytest.mark.parametrize(
    "p",
    [
        DateDelta(years=1, months=2, weeks=3, days=4),
        DateDelta(),
        DateDelta(years=-1, months=2),
    ],
)
def test_pos(p):
    assert +p is p


class TestMultiply:
    def test_simple(self):
        p = DateDelta(
            years=10,
            months=2,
            weeks=3,
            days=4,
        )
        assert p * 2 == DateDelta(
            years=20,
            months=4,
            weeks=6,
            days=8,
        )
        assert p * 0 == DateDelta.ZERO

    def large_factors_allowed_while_zero(self):
        assert DateDelta(days=1) * 100_000 == DateDelta(days=100_000)
        assert DateDelta.ZERO * (1 << 31) == DateDelta.ZERO
        assert DateDelta.ZERO * (1 << 63) == DateDelta.ZERO

    def test_year_range(self):
        DateDelta(years=2) * 4999  # allowed
        with pytest.raises(ValueError, match="range"):
            DateDelta(years=5) * 2000

        with pytest.raises(ValueError, match="range"):
            DateDelta(years=5) * (1 << 15 + 1)

    def test_month_range(self):
        DateDelta(months=2) * 59993  # just allowed
        with pytest.raises(ValueError):
            DateDelta(months=2) * 59995

        with pytest.raises(ValueError):
            DateDelta(months=2) * (1 << 31 + 1)

    @pytest.mark.parametrize(
        "factor",
        [
            1_000,
            1 << 66,
            1 << 32,
            -(1 << 66),
            -(1 << 32),
        ],
    )
    def test_overflow(self, factor):
        with pytest.raises((ValueError, OverflowError)):
            DateDelta(years=10) * factor

    def test_invalid_type(self):
        p = DateDelta(months=1)
        with pytest.raises(TypeError):
            p * 1.5  # type: ignore[operator]

        with pytest.raises(TypeError):
            p * Ellipsis  # type: ignore[operator]


def test_replace():
    p = DateDelta(years=1, months=2, weeks=3, days=4)
    assert p.replace(years=2) == DateDelta(years=2, months=2, weeks=3, days=4)
    assert p.replace(months=3) == DateDelta(years=1, months=3, weeks=3, days=4)
    assert p.replace(weeks=4) == DateDelta(years=1, months=2, weeks=4, days=4)
    assert p.replace(days=5) == DateDelta(years=1, months=2, weeks=3, days=5)
    assert p.replace() == p

    with pytest.raises(TypeError):
        p.replace(3)  # type: ignore[arg-type]

    with pytest.raises(TypeError, match="foo"):
        p.replace(foo=3)  # type: ignore[arg-type]

    with pytest.raises(ValueError, match="years"):
        p.replace(years=10_000)


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

    #     def test_time_delta(self):
    #         p = DateDelta(years=1, months=2, weeks=3, days=4)
    #         d = TimeDelta(hours=1, minutes=2, seconds=3, microseconds=400_004)
    #         assert p + d == DateTimeDelta(
    #             years=1,
    #             months=2,
    #             weeks=3,
    #             days=4,
    #             hours=1,
    #             minutes=2,
    #             seconds=3,
    #             microseconds=400_004,
    #         )
    #         assert p + d == d + p

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

    #     def test_time_delta(self):
    #         p = DateDelta(years=1, months=2, weeks=3, days=4)
    #         d = TimeDelta(hours=1, minutes=2, seconds=3, microseconds=400_004)
    #         assert p - d == DateTimeDelta(
    #             years=1,
    #             months=2,
    #             weeks=3,
    #             days=4,
    #             hours=-1,
    #             minutes=-2,
    #             seconds=-3,
    #             microseconds=-400_004,
    #         )
    #         assert p - d == -d + p
    #         assert d - p == DateTimeDelta(
    #             years=-1,
    #             months=-2,
    #             weeks=-3,
    #             days=-4,
    #             hours=1,
    #             minutes=2,
    #             seconds=3,
    #             microseconds=400_004,
    #         )

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


def test_copy():
    p = DateDelta(years=1, months=2, weeks=3, days=4)
    assert copy(p) is p
    assert deepcopy(p) is p


def test_pickle():
    p = DateDelta(years=1, months=2, weeks=3, days=4)
    dumped = pickle.dumps(p)
    assert len(dumped) < 55
    assert pickle.loads(dumped) == p


def test_compatible_unpickle():
    dumped = (
        b"\x80\x04\x95+\x00\x00\x00\x00\x00\x00\x00\x8c\x08whenever\x94\x8c\r_unpkl_d"
        b"delta\x94\x93\x94(K\x01K\x02K\x03K\x04t\x94R\x94."
    )
    assert pickle.loads(dumped) == DateDelta(
        years=1, months=2, weeks=3, days=4
    )


def test_cannot_subclass():
    with pytest.raises(TypeError):

        class SubclassDateDelta(DateDelta):  # type: ignore[misc]
            pass
