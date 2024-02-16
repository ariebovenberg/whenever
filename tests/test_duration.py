import pytest

from whenever import Duration, InvalidFormat, Period, TimeDelta

from .common import AlwaysEqual, NeverEqual


def test_init():
    d = Duration(
        years=1,
        months=2,
        weeks=3,
        days=11,
        hours=4,
        minutes=5,
        seconds=6,
        microseconds=7,
    )
    assert d.date_part == Period(years=1, months=2, weeks=3, days=11)
    assert d.time_part == TimeDelta(
        hours=4, minutes=5, seconds=6, microseconds=7
    )

    assert Duration() == Duration(
        years=0,
        months=0,
        weeks=0,
        days=0,
        hours=0,
        minutes=0,
        seconds=0,
        microseconds=0,
    )


def test_immutable():
    p = Duration(
        years=1,
        months=2,
        weeks=3,
        hours=4,
    )
    with pytest.raises(AttributeError):
        p.date_part = Period()  # type: ignore[misc]


def test_equality():
    p = Duration(
        years=1,
        months=2,
        weeks=3,
        hours=4,
    )
    same = Duration(
        years=1,
        months=2,
        weeks=3,
        hours=4,
    )
    same_total = Duration(
        years=1,
        months=2,
        days=3 * 7,
        minutes=60 * 4,
    )
    different = Duration(
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
    assert Duration.ZERO == Duration()


def test_bool():
    assert not Duration()
    assert Duration(days=1)


@pytest.mark.parametrize(
    "p, expect",
    [
        (Duration(), "P0D"),
        (Duration(years=-2), "P-2Y"),
        (Duration(days=1), "P1D"),
        (Duration(hours=1), "PT1H"),
        (Duration(minutes=1), "PT1M"),
        (Duration(seconds=1), "PT1S"),
        (Duration(microseconds=1), "PT0.000001S"),
        (Duration(microseconds=4300), "PT0.0043S"),
        (Duration(weeks=1), "P1W"),
        (Duration(months=1), "P1M"),
        (Duration(years=1), "P1Y"),
        (
            Duration(
                years=1,
                months=2,
                weeks=3,
                days=4,
                hours=5,
                minutes=6,
                seconds=7,
                microseconds=8,
            ),
            "P1Y2M3W4DT5H6M7.000008S",
        ),
        (
            Duration(
                years=1,
                months=2,
                weeks=3,
                days=4,
                hours=5,
                minutes=6,
                seconds=7,
                microseconds=8,
            ),
            "P1Y2M3W4DT5H6M7.000008S",
        ),
        (Duration(months=2, weeks=3, minutes=6, seconds=7), "P2M3WT6M7S"),
        (Duration(microseconds=-45), "PT-0.000045S"),
        (
            Duration(
                years=-3,
                months=2,
                weeks=3,
                minutes=-6,
                seconds=7,
                microseconds=-45,
            ),
            "P-3Y2M3WT-5M-53.000045S",
        ),
    ],
)
def test_canonical_format(p, expect):
    assert p.canonical_format() == expect
    assert str(p) == expect


class TestFromCanonicalFormat:

    def test_empty(self):
        assert Duration.from_canonical_format("P0D") == Duration()

    @pytest.mark.parametrize(
        "input, expect",
        [
            ("P0D", Duration()),
            ("PT0S", Duration()),
            ("P2Y", Duration(years=2)),
            ("P1M", Duration(months=1)),
            ("P1W", Duration(weeks=1)),
            ("P1D", Duration(days=1)),
            ("PT1H", Duration(hours=1)),
            ("PT1M", Duration(minutes=1)),
            ("PT1S", Duration(seconds=1)),
            ("PT0.000001S", Duration(microseconds=1)),
            ("PT0.0043S", Duration(microseconds=4300)),
        ],
    )
    def test_single_unit(self, input, expect):
        assert Duration.from_canonical_format(input) == expect

    @pytest.mark.parametrize(
        "input, expect",
        [
            (
                "P1Y2M3W4DT5H6M7S",
                Duration(
                    years=1,
                    months=2,
                    weeks=3,
                    days=4,
                    hours=5,
                    minutes=6,
                    seconds=7,
                ),
            ),
            (
                "P1Y2M3W4DT5H6M7.000008S",
                Duration(
                    years=1,
                    months=2,
                    weeks=3,
                    days=4,
                    hours=5,
                    minutes=6,
                    seconds=7,
                    microseconds=8,
                ),
            ),
            (
                "P2M3WT6M7S",
                Duration(months=2, weeks=3, minutes=6, seconds=7),
            ),
            ("PT-0.000045S", Duration(microseconds=-45)),
            (
                "P-3Y2M+3WT-6M6.999955S",
                Duration(
                    years=-3,
                    months=2,
                    weeks=3,
                    minutes=-6,
                    seconds=7,
                    microseconds=-45,
                ),
            ),
            ("P-2MT-1M", Duration(months=-2, minutes=-1)),
            (
                "P-2Y3W-0DT-0.999S",
                Duration(years=-2, weeks=3, seconds=-1, microseconds=1_000),
            ),
        ],
    )
    def test_multiple_units(self, input, expect):
        assert Duration.from_canonical_format(input) == expect

    def test_invalid(self):
        with pytest.raises(InvalidFormat):
            Duration.from_canonical_format("P")

    def test_too_many_microseconds(self):
        with pytest.raises(InvalidFormat):
            Duration.from_canonical_format("PT0.0000001S")


class TestAdd:

    def test_same_type(self):
        p = Duration(
            years=1,
            months=2,
            weeks=3,
            days=4,
            hours=5,
            minutes=6,
            seconds=7,
            microseconds=800_000,
        )
        q = Duration(
            years=-1,
            months=3,
            weeks=-1,
            minutes=0,
            seconds=1,
            microseconds=300_000,
        )
        assert p + q == Duration(
            months=5,
            weeks=2,
            days=4,
            hours=5,
            minutes=6,
            seconds=9,
            microseconds=100_000,
        )
        assert p + Duration(
            years=-1,
            months=3,
            weeks=-1,
            minutes=0,
            seconds=1,
            microseconds=-300_000,
        ) == Duration(
            months=5,
            weeks=2,
            days=4,
            hours=5,
            minutes=6,
            seconds=8,
            microseconds=500_000,
        )

    def test_duration(self):
        p = Duration(
            years=1,
            months=2,
            weeks=3,
            days=4,
            hours=5,
            minutes=6,
            seconds=7,
            microseconds=800_000,
        )
        q = TimeDelta(
            hours=1,
            minutes=2,
            seconds=3,
            microseconds=400_000,
        )
        assert p + q == Duration(
            years=1,
            months=2,
            weeks=3,
            days=4,
            hours=6,
            minutes=8,
            seconds=11,
            microseconds=200_000,
        )
        assert q + p == Duration(
            years=1,
            months=2,
            weeks=3,
            days=4,
            hours=6,
            minutes=8,
            seconds=11,
            microseconds=200_000,
        )

    def test_period(self):
        p = Duration(
            years=1,
            months=2,
            weeks=3,
            days=4,
            hours=5,
            minutes=6,
            seconds=7,
            microseconds=800_000,
        )
        q = Period(years=-1, months=3, weeks=-1, days=0)
        assert p + q == Duration(
            months=5,
            weeks=2,
            days=4,
            hours=5,
            minutes=6,
            seconds=7,
            microseconds=800_000,
        )
        assert q + p == Duration(
            months=5,
            weeks=2,
            days=4,
            hours=5,
            minutes=6,
            seconds=7,
            microseconds=800_000,
        )

    def test_unsupported(self):
        p = Duration(
            years=1,
            months=2,
            weeks=3,
            days=4,
            hours=5,
            minutes=6,
            seconds=7,
            microseconds=800_000,
        )
        with pytest.raises(TypeError, match="unsupported operand"):
            p + 32  # type: ignore[operator]

        with pytest.raises(TypeError, match="unsupported operand"):
            32 + p  # type: ignore[operator]


class TestSubtract:

    def test_same_type(self):
        p = Duration(
            years=1,
            months=2,
            weeks=3,
            days=4,
            hours=5,
            minutes=6,
            seconds=7,
            microseconds=300_000,
        )
        q = Duration(
            years=-1,
            months=2,
            weeks=-1,
            minutes=0,
            seconds=1,
            microseconds=800_000,
        )
        assert p - q == Duration(
            years=2,
            weeks=4,
            days=4,
            hours=5,
            minutes=6,
            seconds=5,
            microseconds=500_000,
        )

    def test_duration(self):
        p = Duration(
            years=1,
            months=2,
            weeks=3,
            days=4,
            hours=5,
            minutes=6,
            seconds=7,
            microseconds=300_000,
        )
        q = TimeDelta(
            hours=1,
            minutes=2,
            seconds=3,
            microseconds=800_000,
        )
        assert p - q == Duration(
            years=1,
            months=2,
            weeks=3,
            days=4,
            hours=4,
            minutes=4,
            seconds=3,
            microseconds=500_000,
        )
        assert q - p == Duration(
            years=-1,
            months=-2,
            weeks=-3,
            days=-4,
            hours=-4,
            minutes=-4,
            seconds=-3,
            microseconds=-500_000,
        )

    def test_period(self):
        p = Duration(
            years=1,
            months=2,
            weeks=3,
            days=4,
            hours=5,
            minutes=6,
            seconds=7,
            microseconds=300_000,
        )
        q = Period(
            years=-1,
            months=2,
            weeks=-1,
            days=0,
        )
        assert p - q == Duration(
            years=2,
            weeks=4,
            days=4,
            hours=5,
            minutes=6,
            seconds=7,
            microseconds=300_000,
        )
        assert q - p == Duration(
            years=-2,
            weeks=-4,
            days=-4,
            hours=-5,
            minutes=-6,
            seconds=-7,
            microseconds=-300_000,
        )

    def test_unsupported(self):
        p = Duration(
            years=1,
            months=2,
            weeks=3,
            days=4,
            hours=5,
            minutes=6,
            seconds=7,
            microseconds=300_000,
        )
        with pytest.raises(TypeError, match="unsupported operand"):
            p - 32  # type: ignore[operator]

        with pytest.raises(TypeError, match="unsupported operand"):
            32 - p  # type: ignore[operator]


def test_negate():
    p = Duration(
        years=1,
        months=2,
        weeks=-3,
        days=4,
        hours=5,
        minutes=6,
        seconds=7,
        microseconds=800_000,
    )
    assert -p == Duration(
        years=-1,
        months=-2,
        weeks=3,
        days=-4,
        hours=-5,
        minutes=-6,
        seconds=-7,
        microseconds=-800_000,
    )


def test_abs():
    p = Duration(
        years=1,
        months=-2,
        weeks=3,
        days=4,
        hours=-5,
        minutes=-6,
        seconds=-7,
        microseconds=-800_000,
    )
    assert abs(p) == Duration(
        years=1,
        months=2,
        weeks=3,
        days=4,
        hours=5,
        minutes=6,
        seconds=7,
        microseconds=800_000,
    )


def test_as_tuple():
    p = Duration(
        years=1,
        months=-2,
        weeks=3,
        days=4,
        hours=5,
        minutes=6,
        seconds=7,
        microseconds=800_000,
    )
    assert p.as_tuple() == (1, -2, 3, 4, 5, 6, 7, 800_000)
