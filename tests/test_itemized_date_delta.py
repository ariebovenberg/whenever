import pickle
from collections import Counter
from typing import Any, Literal, Sequence, cast

import pytest

from whenever import Date, ItemizedDateDelta, ItemizedDelta

from .common import AlwaysEqual, NeverEqual
from .test_date_delta import INVALID_DDELTAS

UNITS = cast(
    Sequence[Literal["years", "months", "weeks", "days"]],
    "years months weeks days".split(),
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
            ({"months": 90}, 1),
            ({"days": 5, "weeks": 1, "years": 2, "months": 90}, 1),
            ({"years": -80, "weeks": -1}, -1),
            ({"days": 0, "years": -1}, -1),
            ({"days": -1, "months": 0}, -1),
            ({"days": 3, "weeks": 9}, 1),
            ({"weeks": 0}, 0),
            ({"months": -30}, -1),
            ({"years": 3, "months": 1}, 1),
            ({"days": 3, "months": 10_000}, 1),
            ({"weeks": 50}, 1),
        ],
    )
    def test_simple_valid(self, kwargs, expect_sign: int):
        d = ItemizedDateDelta(**kwargs)
        assert d.sign == expect_sign
        for unit in UNITS:
            assert getattr(d, unit) == kwargs.get(unit, 0)

    def test_no_components(self):
        with pytest.raises(ValueError, match="At least one"):
            ItemizedDateDelta()

    @pytest.mark.parametrize(
        "kwargs",
        [
            {"days": 5, "weeks": -10},
            {"years": -2, "months": 30},
            {"months": 3, "weeks": -3},
        ],
    )
    def test_mixed_sign(self, kwargs):
        with pytest.raises(ValueError, match="sign"):
            ItemizedDateDelta(**kwargs)

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
        ],
    )
    def test_range(self, value, unit):
        kwargs = {unit: value}
        with pytest.raises(ValueError, match="range"):
            ItemizedDateDelta(**kwargs)


@pytest.mark.parametrize(
    "d, expected",
    [
        (ItemizedDateDelta(days=5), {"days": 5}),
        (
            ItemizedDateDelta(weeks=1, years=2, months=8),
            {"years": 2, "months": 8, "weeks": 1},
        ),
        (
            ItemizedDateDelta(weeks=-1, years=-80),
            {"years": -80, "weeks": -1},
        ),
        (
            ItemizedDateDelta(years=1, months=0, weeks=9_000, days=1_000),
            {"years": 1, "months": 0, "weeks": 9_000, "days": 1_000},
        ),
    ],
)
def test_mapping_like_interface(
    d: ItemizedDateDelta,
    expected: dict[Literal["years", "months", "weeks", "days"], int],
):
    # Components
    assert list(d.keys()) == list(expected.keys())
    assert list(d.values()) == list(expected.values())
    assert list(d.items()) == list(expected.items())

    # passing as arguments
    assert dict(d) == expected
    assert Counter(d) == Counter(expected)
    # mypy ignore awaiting release of https://github.com/python/mypy/pull/20416
    assert ItemizedDateDelta(**d) == d  # type: ignore[misc]

    for key in expected:
        assert key in d
        assert d[key] == expected[key]
        assert d.get(key) is not None

    # a random missing key
    assert "foo" not in d
    with pytest.raises(KeyError):
        d["foo"]  # type: ignore[index]

    assert d.get("foo") is None  # type: ignore[call-overload]

    for missing_key in UNITS - expected.keys():
        assert missing_key not in d
        assert d.get(missing_key) is None
        with pytest.raises(KeyError):
            d[missing_key]

    assert len(d) == len(expected)


def test_replace():
    d = ItemizedDateDelta(years=2, months=3, weeks=4)

    # changing an existing value
    assert d.replace(months=10).exact_eq(
        ItemizedDateDelta(years=2, months=10, weeks=4)
    )

    # adding a value
    assert d.replace(days=5).exact_eq(
        ItemizedDateDelta(years=2, months=3, weeks=4, days=5)
    )

    # setting to zero
    assert d.replace(weeks=0).exact_eq(
        ItemizedDateDelta(years=2, months=3, weeks=0)
    )

    # setting to missing (zero)
    assert d.replace(years=None).exact_eq(ItemizedDateDelta(months=3, weeks=4))

    # invalid sign
    with pytest.raises(ValueError, match="sign"):
        assert d.replace(days=-1)

    with pytest.raises(ValueError, match="sign"):
        assert (-d).replace(days=1)

    # sign becomes zero
    assert d.replace(years=0, months=0, weeks=0).exact_eq(
        ItemizedDateDelta(years=0, months=0, weeks=0)
    )

    # sign becomes negative
    assert d.replace(years=-3, months=-1, weeks=0, days=-4).exact_eq(
        ItemizedDateDelta(years=-3, months=-1, weeks=0, days=-4)
    )

    # negative becomes positive
    assert (
        (-d)
        .replace(years=3, months=1, weeks=0, days=4)
        .exact_eq(ItemizedDateDelta(years=3, months=1, weeks=0, days=4))
    )

    # last field dropped
    with pytest.raises(ValueError, match="At least one"):
        d.replace(years=None, months=None, weeks=None)

    # no arguments
    assert d.replace().exact_eq(d)
    assert (-d).replace().exact_eq(-d)

    # invalid field
    with pytest.raises(TypeError, match="foo"):
        d.replace(foo=5)  # type: ignore[call-arg]


class TestEq:
    def test_notimplemented(self):
        d = ItemizedDateDelta(days=5)
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
        d1 = ItemizedDateDelta(days=5, years=2)
        d2 = ItemizedDateDelta(days=5, years=2)
        d3 = ItemizedDateDelta(days=5, years=3)
        assert d1 == d2
        assert not d1 != d2
        assert d1 != d3
        assert not d1 == d3

    def test_zero_is_same_as_missing(self):
        d1 = ItemizedDateDelta(weeks=1)
        d2 = ItemizedDateDelta(weeks=1, days=0)
        assert d1 == d2
        assert not d1 != d2

    def test_no_allow_mixing_delta_types(self):
        d = ItemizedDateDelta(days=5)
        # NOTE: the mypy ignore comments are actually also "tests" in the sense
        # they ensure that the types properly implement strict comparison!
        assert d != "P5D"  # type: ignore[comparison-overlap]
        # TODO LAST: these comparisons *should* be blocked?
        assert d != {"days": 5}
        assert d != ItemizedDelta(days=5)


def test_exact_eq():
    d1 = ItemizedDateDelta(years=2, months=0, weeks=5, days=0)
    d2 = ItemizedDateDelta(years=2, weeks=5)
    d3 = ItemizedDateDelta(years=2, months=1, weeks=5)
    assert d1.exact_eq(d1)
    assert not d1.exact_eq(d2)
    assert not d1.exact_eq(d3)


class TestFormatIso:

    @pytest.mark.parametrize(
        "d, expected",
        [
            (ItemizedDateDelta(days=0), "P0D"),
            (ItemizedDateDelta(days=5), "P5D"),
            (ItemizedDateDelta(days=5, weeks=0), "P0W5D"),
            (
                ItemizedDateDelta(years=3, months=6, weeks=0, days=4),
                "P3Y6M0W4D",
            ),
            (ItemizedDateDelta(days=23_000), "P23000D"),
            (ItemizedDateDelta(years=4), "P4Y"),
            (ItemizedDateDelta(months=0), "P0M"),
            (ItemizedDateDelta(months=-6), "-P6M"),
            (ItemizedDateDelta(weeks=-600), "-P600W"),
        ],
    )
    def test_format_iso(self, d: ItemizedDateDelta, expected: str):
        assert d.format_iso() == expected

    def test_lowercase_units(self):
        d = ItemizedDateDelta(years=1, months=2, weeks=3, days=4)
        assert d.format_iso(lowercase_units=True) == "P1y2m3w4d"
        assert (
            ItemizedDateDelta(days=0).format_iso(lowercase_units=True) == "P0d"
        )


def test_repr():
    d = ItemizedDateDelta(
        years=3,
        months=6,
        weeks=9,
        days=4,
    )
    assert repr(d) == 'ItemizedDateDelta("P3y6m9w4d")'
    assert repr(ItemizedDateDelta(days=0)) == 'ItemizedDateDelta("P0d")'
    assert (
        repr(ItemizedDateDelta(months=-1, days=0))
        == 'ItemizedDateDelta("-P1m0d")'
    )


INVALID_DELTAS = [
    "P",
    "",
    "3D",
    "-PT",
    "PT",
    "+PT",
    "P1YX3M",  # invalid separator
    "P𝟙D",  # non-ascii
    "P0.0D",  # fractional date not allowed
    # incomplete
    "P3",
    "P3D4",
    "P3D4T",
    # too many digits
    "P9999999999999999999D",
    # out of range
    "P14000Y",
    "P180000M",
    "PT180000000H",
    # unit mixups
    "P3DT4HM",
    "P3DT4H8X",
    "P3DT4M3H",
    # trailing stuff
    "P3M0Dxyz",
    "P3M0DD",
    "P3M0D0",
    *INVALID_DDELTAS,
]


class TestParseIso:

    @pytest.mark.parametrize(
        "s, expected",
        [
            (
                "P3Y6M4D",
                ItemizedDateDelta(years=3, months=6, days=4),
            ),
            ("P0w23d", ItemizedDateDelta(weeks=0, days=23)),
            ("P4Y", ItemizedDateDelta(years=4)),
            ("P0m", ItemizedDateDelta(months=0)),
            ("-P6M", ItemizedDateDelta(months=-6)),
            ("P1Y2m", ItemizedDateDelta(years=1, months=2)),
            ("P0D", ItemizedDateDelta(days=0)),
            ("-P99W0D", ItemizedDateDelta(weeks=-99, days=0)),
            ("+P3M", ItemizedDateDelta(months=3)),
            # long but still valid
            ("P0001000Y", ItemizedDateDelta(years=1_000)),
            ("P9999Y", ItemizedDateDelta(years=9999)),
            ("-P9999Y", ItemizedDateDelta(years=-9999)),
        ],
    )
    def test_valid(self, s: str, expected: ItemizedDateDelta):
        assert ItemizedDateDelta.parse_iso(s).exact_eq(expected)

    @pytest.mark.parametrize("s", INVALID_DELTAS)
    def test_invalid(self, s: str):
        with pytest.raises(ValueError):
            ItemizedDateDelta.parse_iso(s)


# These tests are relatively simple because since() does most of the heavy lifting,
# and is tested more thoroughly elsewhere.
@pytest.mark.parametrize(
    "d, relative_to, units, kwargs, expect",
    [
        (
            ItemizedDateDelta(years=2, months=3, weeks=4, days=5),
            Date("2021-12-31"),
            ["years", "days"],
            {},
            ItemizedDateDelta(years=2, days=124),
        ),
        (
            ItemizedDateDelta(years=2, months=3, weeks=4, days=5),
            Date("2021-12-31"),
            ["years", "days"],
            {"round_increment": 5, "round_mode": "ceil"},
            ItemizedDateDelta(years=2, days=125),
        ),
        (
            ItemizedDateDelta(days=0),
            Date("0023-02-28"),
            ["years", "months", "weeks"],
            {},
            ItemizedDateDelta(years=0, months=0, weeks=0),
        ),
    ],
)
def test_in_units(
    d: ItemizedDateDelta,
    relative_to: Date,
    units: Sequence[Literal["years", "months", "weeks", "days"]],
    kwargs: Any,
    expect: ItemizedDateDelta,
):
    assert d.in_units(units, relative_to=relative_to, **kwargs).exact_eq(
        expect
    )
    if kwargs.get("round_increment", 1) == 1 and units[-1] == "days":
        assert relative_to.add(expect) == relative_to.add(d)


class TestAddSub:
    # We have a limited number of test cases here since this operation is
    # mostly a combination of logic tested elsewhere: Date.add() and Date.since()
    @pytest.mark.parametrize(
        "d1, d2, relative_to, expected, kwargs",
        [
            # simple case with no carry
            (
                ItemizedDateDelta(years=2, months=3),
                ItemizedDateDelta(years=1, months=2),
                Date("2021-12-31"),
                ItemizedDateDelta(years=3, months=5),
                {},
            ),
            # with carry
            (
                ItemizedDateDelta(years=2, months=3, weeks=4, days=5),
                ItemizedDateDelta(years=1, months=8, weeks=3, days=30),
                Date("2021-12-31"),
                ItemizedDateDelta(years=4, months=1, weeks=3, days=2),
                {},
            ),
            # different units
            (
                ItemizedDateDelta(years=2, days=5),
                ItemizedDateDelta(years=1, months=8, days=30),
                Date("0021-08-03"),
                ItemizedDateDelta(years=3, months=9, days=5),
                {},
            ),
            # customized output kwargs
            (
                ItemizedDateDelta(years=2, days=5),
                ItemizedDateDelta(years=1, months=8, days=30),
                Date("0021-08-03"),
                ItemizedDateDelta(months=45, weeks=2),
                {
                    "units": ["months", "weeks"],
                    "round_mode": "expand",
                    "round_increment": 2,
                },
            ),
            # zero result
            (
                ItemizedDateDelta(years=2, months=3),
                ItemizedDateDelta(years=-2, months=-3),
                Date("2021-12-31"),
                ItemizedDateDelta(years=0, months=0),
                {},
            ),
            # negative arg, positive result
            (
                ItemizedDateDelta(years=2, months=3),
                ItemizedDateDelta(years=-1, months=-4),
                Date("2021-12-31"),
                ItemizedDateDelta(years=0, months=11),
                {},
            ),
            # negative arg, negative result
            (
                ItemizedDateDelta(years=2, months=3),
                ItemizedDateDelta(years=-1, months=-20),
                Date("2021-12-31"),
                ItemizedDateDelta(years=-0, months=-5),
                {},
            ),
        ],
    )
    def test_success(
        self,
        d1: ItemizedDateDelta,
        d2: ItemizedDateDelta,
        relative_to: Date,
        expected: ItemizedDateDelta,
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
            ItemizedDateDelta(years=2)
            .add(years=-1, months=3, relative_to=Date("2021-12-31"))
            .exact_eq(ItemizedDateDelta(years=1, months=3))
        )

    def test_no_positional_and_kwarg_mix(self):
        with pytest.raises(TypeError, match="mix"):
            ItemizedDateDelta(years=2).add(  # type: ignore[call-overload]
                ItemizedDateDelta(years=1),
                years=3,
                relative_to=Date("2021-12-31"),
            )

    def test_add_nothing(self):
        ItemizedDateDelta(years=2).add(
            relative_to=Date("2021-12-31")
        ).exact_eq(ItemizedDateDelta(years=2))

    def test_invalid_unit(self):
        with pytest.raises(ValueError, match="foo"):
            ItemizedDateDelta(years=2).add(  # type: ignore[call-overload]
                foo=5, relative_to=Date("2021-12-31")
            )

    def test_overflows(self):
        with pytest.raises((ValueError, OverflowError)):
            ItemizedDateDelta(years=5_000).add(
                years=5_000, relative_to=Date("2021-12-31")
            )

        # Overflow due to relative_to
        with pytest.raises((ValueError, OverflowError)):
            ItemizedDateDelta(years=5).add(
                months=29, relative_to=Date("9994-12-31")
            )

    def test_floor_round_mode_behaves_correctly_on_negative(self):
        d1 = ItemizedDateDelta(years=4, months=5)
        d2 = ItemizedDateDelta(years=-8, months=-2)

        assert d1.add(
            d2,
            relative_to=Date("2021-11-20"),
            round_mode="floor",
            round_increment=2,
        ).exact_eq(ItemizedDateDelta(years=-3, months=-10))


class TestTotal:

    @pytest.mark.parametrize(
        "d, relative_to, unit, expected",
        [
            (
                ItemizedDateDelta(years=2, months=3, weeks=4, days=5),
                Date("2021-12-31"),
                "months",
                28.096774193548388,
            ),
            (
                ItemizedDateDelta(weeks=2, days=16),
                Date("2021-04-30"),
                "months",
                1.0,
            ),
            (
                ItemizedDateDelta(weeks=-2, days=-18),
                Date("2021-04-30"),
                "years",
                -0.08767123287671233,
            ),
            (
                ItemizedDateDelta(weeks=-2, days=-18),
                Date("2021-04-30"),
                "days",
                -32,
            ),
        ],
    )
    def test_valid(
        self,
        d: ItemizedDateDelta,
        relative_to: Date,
        unit: Literal["years", "months", "weeks", "days"],
        expected: float,
    ):
        assert d.total(unit, relative_to=relative_to) == pytest.approx(
            expected
        )

    def test_invalid_unit(self):
        with pytest.raises(ValueError, match="foo"):
            ItemizedDateDelta(years=2).total(
                "foo", relative_to=Date("2021-12-31")  # type: ignore[arg-type]
            )

    def test_no_relative_to(self):
        with pytest.raises(TypeError, match="relative_to"):
            ItemizedDateDelta(years=2).total("months")  # type: ignore[call-arg]

    def test_relative_to_overflows(self):
        with pytest.raises((ValueError, OverflowError)):
            ItemizedDateDelta(years=2).total(
                "months", relative_to=Date("9998-04-30")
            )

        with pytest.raises((ValueError, OverflowError)):
            ItemizedDateDelta(years=-2).total(
                "months", relative_to=Date("0001-12-31")
            )


def test_abs():
    d = ItemizedDateDelta(days=-5, weeks=-3)
    assert abs(d).exact_eq(ItemizedDateDelta(days=5, weeks=3))

    d_pos = ItemizedDateDelta(days=2, years=30)
    assert abs(d_pos) is d_pos

    d_zero = ItemizedDateDelta(months=0)
    assert abs(d_zero) is d_zero


def test_neg():
    d = ItemizedDateDelta(days=5, weeks=3, years=200)
    assert (-d).exact_eq(ItemizedDateDelta(days=-5, weeks=-3, years=-200))
    assert (--d).exact_eq(d)

    d_zero = ItemizedDateDelta(weeks=0)
    assert -d_zero is d_zero


def test_bool():
    d_zero = ItemizedDateDelta(days=0)
    assert not d_zero
    assert d_zero.sign == 0

    assert not ItemizedDateDelta(years=0)
    assert ItemizedDateDelta(weeks=0).sign == 0

    d_nonzero = ItemizedDateDelta(weeks=1, days=0)
    assert d_nonzero
    assert d_nonzero.sign == 1


@pytest.mark.parametrize(
    "d",
    [
        ItemizedDateDelta(
            years=1,
            months=2,
            weeks=3,
            days=4,
        ),
        ItemizedDateDelta(days=5),
        ItemizedDateDelta(days=-5, months=-3),
        ItemizedDateDelta(days=-5, weeks=0),
    ],
)
def test_pickle(d: ItemizedDateDelta):
    dumped = pickle.dumps(d)
    assert len(dumped) < 100
    assert pickle.loads(dumped).exact_eq(d)


def test_compatible_unpickle():
    # This is a pickle of ItemizedDateDelta created with the initial implementation.
    # We keep this test to ensure backwards compatibility.
    dumped = (
        b"\x80\x04\x95.\x00\x00\x00\x00\x00\x00\x00\x8c\x08whenever\x94\x8c\x0e_unp"
        b"kl_iddelta\x94\x93\x94(K\x01K\x01K\x02K\x03K\x04t\x94R\x94."
    )
    result = pickle.loads(dumped)
    assert result.exact_eq(
        ItemizedDateDelta(years=1, months=2, weeks=3, days=4)
    )
