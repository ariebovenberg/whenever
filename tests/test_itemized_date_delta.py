import pickle
from collections import OrderedDict

import pytest

from whenever import ItemizedDateDelta

from .common import AlwaysEqual, NeverEqual
from .test_date_delta import INVALID_DDELTAS

UNITS = "years months weeks days".split()


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
    def test_simple_valid(self, kwargs, expect_sign):
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
        (ItemizedDateDelta(days=5), (5,)),
        (ItemizedDateDelta(weeks=1, years=2, months=8), (2, 8, 1)),
        (ItemizedDateDelta(weeks=-1, days=0), (-1, 0)),
        (
            ItemizedDateDelta(years=1, weeks=9_000, months=20),
            (1, 20, 9_000),
        ),
    ],
)
def test_values(d, expected):
    assert d.values() == expected
    # Values are also emitted from iteration
    assert list(d) == list(expected)


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
def test_dictlike_behavior(d, expected):
    # explicit method
    assert d.dict() == expected
    assert list(d.dict()) == list(expected)  # keys in order

    # The mapping-like interface
    assert list(d.units()) == list(expected.keys())
    assert list(d.values()) == list(expected.values())

    for key in expected:
        assert key in d
        assert d[key] == expected[key]

    # a random missing key
    assert "foo" not in d
    with pytest.raises(KeyError):
        d["foo"]

    for missing_key in UNITS - expected.keys():
        assert missing_key not in d
        with pytest.raises(KeyError):
            d[missing_key]

    assert len(d) == len(expected)


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

    def test_zero_is_not_same_as_missing(self):
        d1 = ItemizedDateDelta(weeks=1)
        d2 = ItemizedDateDelta(weeks=1, days=0)
        assert d1 != d2
        assert not d1 == d2


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
    def test_format_iso(self, d, expected):
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
        assert ItemizedDateDelta.parse_iso(s) == expected

    @pytest.mark.parametrize("s", INVALID_DELTAS)
    def test_invalid(self, s: str):
        with pytest.raises(ValueError):
            ItemizedDateDelta.parse_iso(s)


def test_abs():
    d = ItemizedDateDelta(days=-5, weeks=-3)
    assert abs(d) == ItemizedDateDelta(days=5, weeks=3)

    d_pos = ItemizedDateDelta(days=2, years=30)
    assert abs(d_pos) is d_pos

    d_zero = ItemizedDateDelta(months=0)
    assert abs(d_zero) is d_zero


def test_neg():
    d = ItemizedDateDelta(days=5, weeks=3, years=200)
    assert -d == ItemizedDateDelta(days=-5, weeks=-3, years=-200)
    assert --d == d

    d_zero = ItemizedDateDelta(weeks=0)
    assert -d_zero is d_zero


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
def test_pickle(d):
    dumped = pickle.dumps(d)
    assert len(dumped) < 100
    assert pickle.loads(dumped) == d


def test_compatible_unpickle():
    # This is a pickle of ItemizedDateDelta created with the initial implementation.
    # We keep this test to ensure backwards compatibility.
    dumped = (
        b"\x80\x04\x95:\x00\x00\x00\x00\x00\x00\x00\x8c\x14whenever._pywheneve"
        b"r\x94\x8c\x0e_unpkl_iddelta\x94\x93\x94(K\x01K\x01K\x02K\x03K\x04t\x94R\x94"
        b"."
    )
    result = pickle.loads(dumped)
    assert result == ItemizedDateDelta(years=1, months=2, weeks=3, days=4)
