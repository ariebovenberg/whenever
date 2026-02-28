import pickle
from collections import Counter
from collections.abc import Sequence, KeysView, ValuesView, ItemsView, Mapping
from typing import Any, Literal, cast

import pytest

from whenever import ItemizedDateDelta, ItemizedDelta, TimeDelta, ZonedDateTime

from .common import AlwaysEqual, NeverEqual
from .test_date_delta import INVALID_DDELTAS
from .test_time_delta import INVALID_TDELTAS

UNITS = cast(
    Sequence[
        Literal[
            "years",
            "months",
            "weeks",
            "days",
            "hours",
            "minutes",
            "seconds",
            "nanoseconds",
        ]
    ],
    "years months weeks days hours minutes seconds nanoseconds".split(),
)
pytestmark = pytest.mark.filterwarnings(
    "ignore::whenever.WheneverDeprecationWarning"
)


class TestInit:

    @pytest.mark.parametrize(
        "kwargs, expect_sign",
        [
            ({"days": 5}, 1),
            ({"weeks": 1}, 1),
            ({"years": 2}, 1),
            ({"years": 0}, 0),
            ({"minutes": 90}, 1),
            ({"days": 5, "weeks": 1, "years": 2, "minutes": 90}, 1),
            ({"minutes": -80, "weeks": -1}, -1),
            ({"days": 0, "minutes": -1}, -1),
            ({"days": -1, "minutes": 0}, -1),
            ({"days": 3, "seconds": 9}, 1),
            ({"seconds": 0}, 0),
            ({"seconds": -30}, -1),
            ({"days": 3, "seconds": 1}, 1),
            ({"days": 3, "nanoseconds": 500_000_00}, 1),
            ({"nanoseconds": 50}, 1),
            ({"seconds": 50, "nanoseconds": 45_000}, 1),
        ],
    )
    def test_simple_valid(self, kwargs, expect_sign):
        d = ItemizedDelta(**kwargs)
        assert d.sign == expect_sign
        for unit in UNITS:
            assert d.get(unit, 0) == kwargs.get(unit, 0)

    def test_no_components(self):
        with pytest.raises(ValueError, match="At least one"):
            ItemizedDelta()

    @pytest.mark.parametrize(
        "kwargs",
        [
            {"days": 5, "seconds": -10},
            {"years": -2, "minutes": 30},
            {"seconds": 3, "nanoseconds": -3},
        ],
    )
    def test_mixed_sign(self, kwargs):
        with pytest.raises(ValueError, match="sign"):
            ItemizedDelta(**kwargs)

    @pytest.mark.parametrize(
        "value, unit",
        [
            (10_000, "years"),
            (-10_000, "years"),
            (10_000 * 12, "months"),
            (-10_000 * 12, "months"),
            (9_999 * 54, "weeks"),
            (-9_999 * 54, "weeks"),
            (10_000 * 366, "days"),
            (-10_000 * 366, "days"),
            (10_000 * 366 * 24, "hours"),
            (-10_000 * 366 * 24, "hours"),
            (10_000 * 366 * 24 * 60, "minutes"),
            (-10_000 * 366 * 24 * 60, "minutes"),
            (10_000 * 366 * 24 * 60 * 60, "seconds"),
            (-10_000 * 366 * 24 * 60 * 60, "seconds"),
            (1_000_000_000, "nanoseconds"),
            (-1_000_000_000, "nanoseconds"),
        ],
    )
    def test_range(self, value, unit):
        kwargs = {unit: value}
        with pytest.raises(ValueError, match="range"):
            ItemizedDelta(**kwargs)

    def test_nanoseconds_implies_seconds(self):
        d = ItemizedDelta(nanoseconds=500_000_000)
        assert d.get("seconds") == 0
        assert d.get("nanoseconds") == 500_000_000

    def test_none_not_allowed(self):
        with pytest.raises(TypeError):
            ItemizedDelta(days=None)  # type: ignore[arg-type]


@pytest.mark.parametrize(
    "d, expected",
    [
        (ItemizedDelta(days=5), {"days": 5}),
        (
            ItemizedDelta(weeks=1, years=2, minutes=8),
            {"years": 2, "weeks": 1, "minutes": 8},
        ),
        (
            ItemizedDelta(weeks=-1, minutes=-80),
            {"weeks": -1, "minutes": -80},
        ),
        (
            ItemizedDelta(years=1, seconds=9_000_000_000, nanoseconds=1),
            {"years": 1, "seconds": 9_000_000_000, "nanoseconds": 1},
        ),
    ],
)
def test_mapping_like_interface(
    d: ItemizedDelta,
    expected: dict[
        Literal[
            "years",
            "months",
            "weeks",
            "days",
            "hours",
            "minutes",
            "seconds",
            "nanoseconds",
        ],
        int,
    ],
):
    # Components
    assert list(d.keys()) == list(expected.keys())
    assert list(d.values()) == list(expected.values())
    assert list(d.items()) == list(expected.items())

    # passing as arguments
    assert dict(d) == expected
    assert Counter(d) == Counter(expected)
    # mypy ignore awaiting release of https://github.com/python/mypy/pull/20416
    assert ItemizedDelta(**d) == d  # type: ignore[misc]

    for key in expected:
        assert key in d
        assert d[key] == expected[key]
        assert d.get(key) is not None

    # a random missing key
    assert "foo" not in d
    with pytest.raises(KeyError):
        d["foo"]  # type: ignore[index]

    for missing_key in UNITS - expected.keys():
        assert missing_key not in d
        assert d.get(missing_key) is None
        with pytest.raises(KeyError):
            d[missing_key]

    assert len(d) == len(expected)


def test_mapping_views():
    d = ItemizedDelta(years=2, months=3, seconds=4)

    assert isinstance(d, Mapping)

    # KeysView
    keys = d.keys()
    assert isinstance(keys, KeysView)
    assert set(keys) == {"years", "months", "seconds"}
    assert keys | {"extra"} == {"years", "months", "seconds", "extra"}
    assert keys & {"years", "days"} == {"years"}
    assert keys - {"months"} == {"years", "seconds"}

    # ValuesView
    values = d.values()
    assert isinstance(values, ValuesView)
    assert set(values) == {2, 3, 4}

    # ItemsView
    items = d.items()
    assert isinstance(items, ItemsView)
    assert set(items) == {("years", 2), ("months", 3), ("seconds", 4)}
    assert items | {("days", 5)} == {
        ("years", 2),
        ("months", 3),
        ("seconds", 4),
        ("days", 5),
    }


class TestEq:
    def test_notimplemented(self):
        d = ItemizedDelta(days=5)
        assert d != NeverEqual()
        assert NeverEqual() != d
        assert not d == NeverEqual()
        assert not NeverEqual() == d

        assert d == AlwaysEqual()
        assert AlwaysEqual() == d
        assert not d != AlwaysEqual()
        assert not AlwaysEqual() != d

        assert d != 5  # type: ignore[comparison-overlap]
        assert 5 != d  # type: ignore[comparison-overlap]

    def test_equal(self):
        d1 = ItemizedDelta(days=5, years=2)
        d2 = ItemizedDelta(days=5, years=2)
        d3 = ItemizedDelta(days=5, years=3)
        assert d1 == d2
        assert not d1 != d2
        assert d1 != d3
        assert not d1 == d3

    def test_zero_is_the_same_as_missing(self):
        d1 = ItemizedDelta(weeks=1)
        d2 = ItemizedDelta(weeks=1, seconds=0)
        assert d1 == d2
        assert not d1 != d2

    def test_no_allow_mixing_delta_types(self):
        d = ItemizedDelta(days=5)
        # NOTE: the mypy ignore comments are actually also "tests" in the sense
        # they ensure that the types properly implement strict comparison!
        assert d != "P5D"  # type: ignore[comparison-overlap]
        # FUTURE: these comparisons *should* be blocked?
        assert d != {"days": 5}
        assert d != ItemizedDateDelta(days=5)


def test_exact_eq():
    d1 = ItemizedDelta(years=2, months=0, minutes=5, seconds=0)
    d2 = ItemizedDelta(years=2, minutes=5)
    d3 = ItemizedDelta(years=2, months=1, minutes=5)
    d4 = ItemizedDelta(years=2, months=1, minutes=5, seconds=0)
    d5 = ItemizedDelta(years=2, months=0, minutes=5, seconds=0)
    assert d1.exact_eq(d1)
    assert d1.exact_eq(d5)
    assert not d1.exact_eq(d2)
    assert not d1.exact_eq(d3)
    assert not d1.exact_eq(d4)


class TestFormatIso:

    @pytest.mark.parametrize(
        "d, expected",
        [
            (ItemizedDelta(seconds=0), "PT0S"),
            (ItemizedDelta(days=0), "P0D"),
            (ItemizedDelta(days=5), "P5D"),
            (ItemizedDelta(days=5, seconds=0), "P5DT0S"),
            (
                ItemizedDelta(
                    years=3, months=6, days=4, hours=12, minutes=30, seconds=5
                ),
                "P3Y6M4DT12H30M5S",
            ),
            (ItemizedDelta(days=23, hours=23), "P23DT23H"),
            (ItemizedDelta(years=4), "P4Y"),
            (ItemizedDelta(seconds=0), "PT0S"),
            (ItemizedDelta(weeks=0, seconds=0), "P0WT0S"),
            (ItemizedDelta(weeks=0, seconds=0, nanoseconds=0), "P0WT0.0S"),
            (ItemizedDelta(months=-6), "-P6M"),
            (ItemizedDelta(minutes=-600), "-PT600M"),
        ],
    )
    def test_format_iso(self, d: ItemizedDelta, expected: str):
        assert d.format_iso() == expected

    def test_lowercase_units(self):
        d = ItemizedDelta(
            years=1, months=2, days=3, hours=4, minutes=5, seconds=6
        )
        assert d.format_iso(lowercase_units=True) == "P1y2m3dT4h5m6s"
        assert (
            ItemizedDelta(seconds=0).format_iso(lowercase_units=True) == "PT0s"
        )


def test_repr():
    d = ItemizedDelta(
        years=3,
        months=6,
        days=4,
        hours=12,
        minutes=30,
        seconds=5,
        nanoseconds=400_000_000,
    )
    assert repr(d) == 'ItemizedDelta("P3y6m4dT12h30m5.4s")'
    assert repr(ItemizedDelta(seconds=0)) == 'ItemizedDelta("PT0s")'
    assert repr(ItemizedDelta(days=0)) == 'ItemizedDelta("P0d")'
    assert (
        repr(ItemizedDelta(hours=-1, minutes=0)) == 'ItemizedDelta("-PT1h0m")'
    )


INVALID_DELTAS = [
    "P",
    "PT0.0000000001S",  # too many decimal places
    "",
    "3D",
    "-PT",
    "PT",
    "+PT",
    "P1YX3M",  # invalid separator
    "PT𝟙H",  # non-ascii
    # incomplete
    "P3DT",
    "P3DT4",
    "P3DT4h0",
    "P3D4",
    "P3D4T",
    # too many digits
    "PT9999999999999999999S",
    # out of range
    "P14000Y",
    "P180000M",
    "PT180000000H",
    # unit mixups
    "P3DT4HM",
    "P3DT4H8X",
    "P3DT4M3H",
    # trailing stuff
    "P3DT4SXYZ",
    "P3DT4S   ",
    "P3DT4SS",
    "P3DT4S0",
    *INVALID_DDELTAS,
    *INVALID_TDELTAS,
]
# some formats are invalid as date or time deltas alone, but valid as combined
INVALID_DELTAS.remove("PT3M")
INVALID_DELTAS.remove("P1Y2M3W4DT1H2M3S")
INVALID_DELTAS.remove("P1YT0S")
INVALID_DELTAS.remove("P1D")
INVALID_DELTAS.remove("P1YT4M")
INVALID_DELTAS.remove("PT4M3H")


class TestParseIso:

    @pytest.mark.parametrize(
        "s, expected",
        [
            (
                "P3Y6M4DT12H30M5S",
                ItemizedDelta(
                    years=3, months=6, days=4, hours=12, minutes=30, seconds=5
                ),
            ),
            (
                "P3Y4M6WT0.03S",
                ItemizedDelta(
                    years=3,
                    months=4,
                    weeks=6,
                    seconds=0,
                    nanoseconds=30_000_000,
                ),
            ),
            ("P23dt23h", ItemizedDelta(days=23, hours=23)),
            ("P4Y", ItemizedDelta(years=4)),
            ("PT0s", ItemizedDelta(seconds=0)),
            ("-P6M", ItemizedDelta(months=-6)),
            (
                "PT1H2M3.000004S",
                ItemizedDelta(
                    hours=1, minutes=2, seconds=3, nanoseconds=4_000
                ),
            ),
            (
                "-PT58m200.999996S",
                ItemizedDelta(
                    minutes=-58, seconds=-200, nanoseconds=-999_996_000
                ),
            ),
            ("PT0S", ItemizedDelta(seconds=0)),
            ("PT00000.000000001S", ItemizedDelta(seconds=0, nanoseconds=1)),
            ("PT00000.000000000S", ItemizedDelta(seconds=0, nanoseconds=0)),
            ("PT450.000000001S", ItemizedDelta(seconds=450, nanoseconds=1)),
            ("-PT0.000001S", ItemizedDelta(nanoseconds=-1_000)),
            ("PT1.999997S", ItemizedDelta(seconds=1, nanoseconds=999_997_000)),
            ("PT5H", ItemizedDelta(hours=5)),
            ("PT400H", ItemizedDelta(hours=400)),
            (
                "PT400H0M0.0S",
                ItemizedDelta(hours=400, minutes=0, seconds=0, nanoseconds=0),
            ),
            ("-PT4M", ItemizedDelta(minutes=-4)),
            ("PT0S", ItemizedDelta(seconds=0)),
            ("PT3M", ItemizedDelta(minutes=3)),
            ("+PT3M", ItemizedDelta(minutes=3)),
            ("PT0M", ItemizedDelta(minutes=0)),
            ("PT0.000000000S", ItemizedDelta(seconds=0, nanoseconds=0)),
            # # extremely long but still valid
            (
                "PT0H0M000000000000000300000000000.000000000S",
                ItemizedDelta(
                    hours=0, minutes=0, seconds=300_000_000_000, nanoseconds=0
                ),
            ),
            ("PT316192377600S", ItemizedDelta(seconds=316192377600)),
            # non-uppercase
            (
                "pt58m2.999996s",
                ItemizedDelta(minutes=58, seconds=2, nanoseconds=999_996_000),
            ),
            ("PT316192377600s", ItemizedDelta(seconds=316192377600)),
            ("PT400h", ItemizedDelta(hours=400)),
            # comma instead of dot
            ("PT1,999997S", ItemizedDelta(seconds=1, nanoseconds=999_997_000)),
        ],
    )
    def test_valid(self, s: str, expected: ItemizedDelta):
        assert ItemizedDelta.parse_iso(s).exact_eq(expected)

    @pytest.mark.parametrize("s", INVALID_DELTAS)
    def test_invalid(self, s: str):
        with pytest.raises(ValueError):
            ItemizedDelta.parse_iso(s)


# These tests are relatively simple because since() does most of the heavy lifting,
# and is tested more thoroughly elsewhere.
@pytest.mark.parametrize(
    "d, relative_to, units, kwargs, is_exact, expect",
    [
        (
            ItemizedDelta(years=2, months=3, weeks=4, days=5, hours=6),
            ZonedDateTime("2021-12-31T00:34+01:00[Europe/Berlin]"),
            ["weeks", "minutes"],
            {},
            True,
            ItemizedDelta(weeks=122, minutes=360),
        ),
        (
            -ItemizedDelta(years=2, months=3, weeks=4, days=5),
            ZonedDateTime("2021-02-28T23:00+09:00[Asia/Tokyo]"),
            ["years", "days"],
            {"round_increment": 5, "round_mode": "ceil"},
            False,
            -ItemizedDelta(years=2, days=125),
        ),
        (
            ItemizedDelta(days=0),
            ZonedDateTime("0023-02-28T14:15Z[Europe/London]"),
            ["years", "months", "weeks", "seconds"],
            {},
            True,
            ItemizedDelta(years=0, months=0, weeks=0, seconds=0),
        ),
    ],
)
def test_in_units(
    d: ItemizedDelta,
    relative_to: ZonedDateTime,
    units: Sequence[
        Literal[
            "years",
            "months",
            "weeks",
            "days",
            "hours",
            "minutes",
            "seconds",
            "nanoseconds",
        ]
    ],
    kwargs: Any,
    is_exact: bool,
    expect: ItemizedDateDelta,
):
    assert d.in_units(units, relative_to=relative_to, **kwargs).exact_eq(
        expect
    )
    if is_exact:
        assert relative_to.add(d) == relative_to.add(expect)


class TestAddSub:
    # We have a limited number of test cases here since this operation is
    # mostly a combination of logic tested elsewhere: ZonedDateTime.add() and ZonedDateTime.since()
    @pytest.mark.parametrize(
        "d1, d2, relative_to, expected, kwargs",
        [
            # simple case with no carry
            (
                ItemizedDelta(years=2, months=3, minutes=5),
                ItemizedDelta(years=1, months=2, seconds=500),
                ZonedDateTime("2021-12-31T15:16Z[America/Sao_Paulo]"),
                ItemizedDelta(years=3, months=5, minutes=13, seconds=20),
                {},
            ),
            # with carry
            (
                ItemizedDelta(
                    years=2, months=3, weeks=4, days=5, hours=0, seconds=5000
                ),
                ItemizedDelta(
                    years=1, months=8, weeks=3, days=30, hours=0, seconds=1042
                ),
                ZonedDateTime(
                    "2024-02-29T05:16:00.00004Z[America/Los_Angeles]"
                ),
                ItemizedDelta(
                    years=4, months=1, weeks=3, days=2, hours=1, seconds=2442
                ),
                {},
            ),
            # different units
            (
                ItemizedDelta(years=2, days=5, minutes=3_000),
                ItemizedDelta(years=1, months=8, days=30, seconds=3603),
                ZonedDateTime("0021-01-01T00:16Z[Europe/Dublin]"),
                ItemizedDelta(
                    years=3, months=9, days=7, minutes=180, seconds=3
                ),
                {},
            ),
            # customized output kwargs
            (
                ItemizedDelta(years=2, days=5, minutes=3_000),
                ItemizedDelta(years=1, months=8, days=30, seconds=3603),
                ZonedDateTime("9921-01-01T00:16Z[Africa/Johannesburg]"),
                ItemizedDelta(months=45, weeks=1, hours=3, minutes=2),
                {
                    "units": ["months", "weeks", "hours", "minutes"],
                    "round_mode": "expand",
                    "round_increment": 2,
                },
            ),
            # zero result
            (
                ItemizedDelta(years=2, months=3, hours=2),
                ItemizedDelta(years=-2, months=-3, minutes=-120),
                ZonedDateTime(
                    "2024-02-29T05:16:00.00004Z[America/Los_Angeles]"
                ),
                ItemizedDelta(years=0, months=0, hours=0, minutes=0),
                {},
            ),
            # negative arg, positive result
            (
                ItemizedDelta(years=2, months=3, hours=2),
                ItemizedDelta(years=-1, months=-4, hours=-4_000),
                ZonedDateTime("1995-03-30T23:16Z[Australia/Sydney]"),
                ItemizedDelta(years=0, months=5, hours=369),
                {},
            ),
            # negative arg, negative result
            (
                ItemizedDelta(years=2, months=3, hours=2),
                ItemizedDelta(years=-1, months=-20, hours=-4_000),
                ZonedDateTime("1995-03-01T23:16Z[Australia/Sydney]"),
                ItemizedDelta(years=-0, months=-10, hours=-326),
                {},
            ),
        ],
    )
    def test_valid(
        self,
        d1: ItemizedDelta,
        d2: ItemizedDelta,
        relative_to: ZonedDateTime,
        expected: ItemizedDelta,
        kwargs: Any,
    ):
        result = d1.add(d2, relative_to=relative_to, **kwargs)
        assert result.exact_eq(expected)

        # same result with kwargs
        assert d1.add(**d2, relative_to=relative_to, **kwargs).exact_eq(  # type: ignore[call-overload, misc]
            expected
        )

        # same result with subtraction
        if (
            kwargs.get("round_increment", 1) == 1
            and kwargs.get("round_mode", "trunc") == "trunc"
        ):
            assert d1.subtract(
                -d2, relative_to=relative_to, **kwargs
            ).exact_eq(expected)

            assert d1.subtract(  # type: ignore[call-overload]
                **{k: -v for k, v in d2.items()},  # type: ignore[misc]
                relative_to=relative_to,
                **kwargs,
            ).exact_eq(expected)

    def test_mixed_sign_in_kwargs_allowed(self):
        assert (
            ItemizedDelta(days=2)
            .add(
                days=-1,
                minutes=3,
                relative_to=ZonedDateTime("2021-12-31T00:00Z[Africa/Cairo]"),
            )
            .exact_eq(ItemizedDelta(days=1, minutes=3))
        )

    def test_no_positional_and_kwarg_mix(self):
        with pytest.raises(TypeError, match="mix"):
            ItemizedDelta(years=2).add(  # type: ignore[call-overload]
                ItemizedDelta(years=1),
                years=3,
                relative_to=ZonedDateTime("2021-12-31T00:00Z[Africa/Cairo]"),
            )

    def test_add_nothing(self):
        ItemizedDelta(years=2).add(
            relative_to=ZonedDateTime(
                "2021-11-10T23:00:01.000200Z[Africa/Cairo]"
            )
        ).exact_eq(ItemizedDelta(years=2))

    def test_invalid_unit(self):
        with pytest.raises(ValueError, match="foo"):
            ItemizedDelta(years=2).add(  # type: ignore[call-overload]
                foo=5,
                relative_to=ZonedDateTime("2021-12-31T00:00Z[Africa/Cairo]"),
            )

    def test_overflows(self):
        with pytest.raises((ValueError, OverflowError)):
            ItemizedDelta(years=5_000).add(
                years=5_000,
                relative_to=ZonedDateTime("2021-12-31T00:00Z[Africa/Cairo]"),
            )

        # Overflow due to relative_to
        with pytest.raises((ValueError, OverflowError)):
            ItemizedDelta(years=5).add(
                months=29,
                relative_to=ZonedDateTime("9994-12-31T00:00Z[Asia/Tokyo]"),
            )

    def test_floor_round_mode_behaves_correctly_on_negative(self):
        d1 = ItemizedDelta(years=4, seconds=500_000)
        d2 = ItemizedDelta(years=-8, seconds=-6)

        assert d1.add(
            d2,
            relative_to=ZonedDateTime("2021-12-31T00:00Z[Africa/Cairo]"),
            round_mode="floor",
            round_increment=2,
        ).exact_eq(ItemizedDelta(years=-3, seconds=-31036006))


class TestTotal:

    # Relatively few test cases since it reuses ZonedDateTime.since()
    # which is tested more thoroughly elsewhere.
    @pytest.mark.parametrize(
        "d, relative_to, unit, expected",
        [
            (
                ItemizedDelta(years=2, months=3, weeks=4, days=5),
                ZonedDateTime("2021-12-31T03Z[America/New_York]"),
                "months",
                28.06666666666666,
            ),
            (
                ItemizedDelta(weeks=-4),
                ZonedDateTime("2021-02-23T03Z[America/New_York]"),
                "months",
                -0.9032258064516129,
            ),
            (
                ItemizedDelta(weeks=-4, minutes=-9123),
                ZonedDateTime("2021-02-23T03Z[America/New_York]"),
                "days",
                -34.33541666666667,
            ),
            (
                ItemizedDelta(months=6, seconds=3),
                ZonedDateTime("2021-02-23T03Z[America/New_York]"),
                "hours",
                4343.0008333333335,
            ),
            (
                ItemizedDelta(months=6, seconds=3),
                ZonedDateTime("2021-02-23T03Z[America/New_York]"),
                "hours",
                4343.0008333333335,
            ),
            (
                ItemizedDelta(months=6, seconds=3),
                ZonedDateTime("2021-02-23T03Z[America/New_York]"),
                "nanoseconds",
                15634803000000000,
            ),
        ],
    )
    def test_valid(
        self,
        d: ItemizedDelta,
        relative_to: ZonedDateTime,
        unit: Literal[
            "years",
            "months",
            "weeks",
            "days",
            "hours",
            "minutes",
            "seconds",
            "nanoseconds",
        ],
        expected: float,
    ):
        assert d.total(unit, relative_to=relative_to) == pytest.approx(
            expected
        )

    def test_invalid_unit(self):
        with pytest.raises(ValueError, match="foo"):
            ItemizedDelta(years=2, seconds=4_000_000).total(
                "foo", relative_to=ZonedDateTime("2021-12-31T22Z[Europe/Athens]")  # type: ignore[arg-type]
            )

    def test_no_relative_to(self):
        with pytest.raises(TypeError, match="relative_to"):
            ItemizedDelta(years=2, hours=9).total("months")  # type: ignore[call-arg]

    def test_nanoseconds_is_int(self):
        assert isinstance(
            ItemizedDelta(years=200, nanoseconds=1).total(
                "nanoseconds",
                relative_to=ZonedDateTime("2021-12-31T22Z[Europe/Athens]"),
            ),
            int,
        )

    def test_relative_to_overflows(self):
        with pytest.raises((ValueError, OverflowError)):
            ItemizedDelta(years=2, nanoseconds=1).total(
                "months",
                relative_to=ZonedDateTime("9998-04-30T00:00Z[Asia/Tokyo]"),
            )

        with pytest.raises((ValueError, OverflowError)):
            ItemizedDelta(years=-2, minutes=0).total(
                "months",
                relative_to=ZonedDateTime(
                    "0001-12-31T00:00Z[America/New_York]"
                ),
            )


def test_replace():
    d = ItemizedDelta(years=2, months=3, seconds=4)

    # changing an existing value
    assert d.replace(months=10).exact_eq(
        ItemizedDelta(years=2, months=10, seconds=4)
    )

    # adding a value
    assert d.replace(hours=5).exact_eq(
        ItemizedDelta(years=2, months=3, seconds=4, hours=5)
    )

    # setting to zero
    assert d.replace(seconds=0).exact_eq(
        ItemizedDelta(years=2, months=3, seconds=0)
    )

    # setting to missing (zero)
    assert d.replace(years=None).exact_eq(ItemizedDelta(months=3, seconds=4))

    # invalid sign
    with pytest.raises(ValueError, match="sign"):
        assert d.replace(days=-1)

    with pytest.raises(ValueError, match="sign"):
        assert (-d).replace(days=1)

    # sign becomes zero
    assert d.replace(years=0, months=0, seconds=0).exact_eq(
        ItemizedDelta(years=0, months=0, seconds=0)
    )

    # sign becomes negative
    assert d.replace(years=-3, months=-1, seconds=0, days=-4).exact_eq(
        ItemizedDelta(years=-3, months=-1, seconds=0, days=-4)
    )

    # negative becomes positive
    assert (
        (-d)
        .replace(years=3, months=1, seconds=0, days=4)
        .exact_eq(ItemizedDelta(years=3, months=1, seconds=0, days=4))
    )

    # last field dropped
    with pytest.raises(ValueError, match="At least one"):
        d.replace(years=None, months=None, seconds=None)

    # no arguments
    assert d.replace().exact_eq(d)
    assert (-d).replace().exact_eq(-d)

    # invalid field
    with pytest.raises(TypeError, match="foo"):
        d.replace(foo=5)  # type: ignore[call-arg]


def test_abs():
    d = ItemizedDelta(days=-5, hours=-3, nanoseconds=-200)
    assert abs(d).exact_eq(ItemizedDelta(days=5, hours=3, nanoseconds=200))

    d_pos = ItemizedDelta(days=2, minutes=30)
    assert abs(d_pos) is d_pos

    d_zero = ItemizedDelta(seconds=0)
    assert abs(d_zero) is d_zero


def test_neg():
    d = ItemizedDelta(days=5, hours=3, nanoseconds=200)
    assert (-d).exact_eq(ItemizedDelta(days=-5, hours=-3, nanoseconds=-200))
    assert (--d).exact_eq(d)

    d_zero = ItemizedDelta(seconds=0)
    neg_zero = -d_zero
    assert neg_zero is d_zero


def test_bool():
    d_zero = ItemizedDelta(seconds=0)
    assert not d_zero
    assert d_zero.sign == 0

    assert not ItemizedDelta(years=0)
    assert ItemizedDelta(hours=0, seconds=0).sign == 0

    d_nonzero = ItemizedDelta(weeks=1, seconds=0)
    assert d_nonzero
    assert d_nonzero.sign == 1


@pytest.mark.parametrize(
    "d, expected_date, expected_time",
    [
        (
            ItemizedDelta(
                years=1,
                months=2,
                weeks=3,
                days=4,
                hours=5,
                minutes=6,
                seconds=7,
                nanoseconds=8,
            ),
            ItemizedDateDelta(years=1, months=2, weeks=3, days=4),
            TimeDelta(hours=5, minutes=6, seconds=7, nanoseconds=8),
        ),
        (
            ItemizedDelta(days=5),
            ItemizedDateDelta(days=5),
            None,
        ),
        (
            ItemizedDelta(days=5, minutes=0),
            ItemizedDateDelta(days=5),
            TimeDelta.ZERO,
        ),
        (
            ItemizedDelta(days=0, months=0, minutes=-1),
            ItemizedDateDelta(months=0, days=0),
            TimeDelta(minutes=-1),
        ),
        (
            ItemizedDelta(days=0, months=0, minutes=0),
            ItemizedDateDelta(months=0, days=0),
            TimeDelta.ZERO,
        ),
        (
            ItemizedDelta(days=-5, hours=0),
            ItemizedDateDelta(days=-5),
            TimeDelta.ZERO,
        ),
        (
            ItemizedDelta(hours=0),
            None,
            TimeDelta.ZERO,
        ),
        (
            ItemizedDelta(nanoseconds=1),
            None,
            TimeDelta(nanoseconds=1),
        ),
    ],
)
def test_parts(
    d: ItemizedDelta,
    expected_date: ItemizedDateDelta,
    expected_time: TimeDelta,
):
    (date_part, time_part) = d.parts()
    if date_part is None:
        assert expected_date is None
    else:
        assert date_part.exact_eq(expected_date)
    assert time_part == expected_time


@pytest.mark.parametrize(
    "d",
    [
        ItemizedDelta(
            years=1,
            months=2,
            weeks=3,
            days=4,
            hours=5,
            minutes=6,
            seconds=7,
            nanoseconds=8,
        ),
        ItemizedDelta(days=5),
        ItemizedDelta(days=-5, hours=-3),
        ItemizedDelta(days=-5, nanoseconds=0),
    ],
)
def test_pickle(d: ItemizedDelta):
    dumped = pickle.dumps(d)
    assert len(dumped) < 100
    assert pickle.loads(dumped).exact_eq(d)


def test_compatible_unpickle():
    # This is a pickle of ItemizedDelta created with the current format.
    # Signed values, no separate sign field.
    dumped = (
        b"\x80\x04\x953\x00\x00\x00\x00\x00\x00\x00\x8c\x08whenever\x94\x8c\r_unpkl_i"
        b"delta\x94\x93\x94(K\x01K\x02K\x03K\x04K\x05K\x06K\x07K\x08t\x94R\x94."
    )
    result = pickle.loads(dumped)
    assert result.exact_eq(
        ItemizedDelta(
            years=1,
            months=2,
            weeks=3,
            days=4,
            hours=5,
            minutes=6,
            seconds=7,
            nanoseconds=8,
        )
    )
