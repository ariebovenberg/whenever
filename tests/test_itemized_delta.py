import pickle
from collections import OrderedDict

import pytest

from whenever import ItemizedDelta

from .common import AlwaysEqual, NeverEqual
from .test_date_delta import INVALID_DDELTAS
from .test_time_delta import INVALID_TDELTAS

UNITS = "years months weeks days hours minutes seconds nanoseconds".split()


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
            assert getattr(d, unit) == kwargs.get(unit, 0)

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

    def test_float_seconds(self):
        d = ItemizedDelta(seconds=9_000, nanoseconds=1)
        assert d.float_seconds() == 9_000.000000001


@pytest.mark.parametrize(
    "d, expected",
    [
        (ItemizedDelta(days=5), (5,)),
        (ItemizedDelta(weeks=1, years=2, minutes=8), (2, 1, 8)),
        (ItemizedDelta(weeks=-1, minutes=0), (-1, 0)),
        (
            ItemizedDelta(years=1, seconds=9_000, nanoseconds=20),
            (1, 9_000, 20),
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
def test_dictlike_behavior(d, expected):
    # explicit method
    assert d.dict() == expected
    assert list(d.dict()) == list(expected)  # keys in order

    # dict() constructor
    assert dict(d) == expected
    assert OrderedDict(d) == OrderedDict(expected)

    # The rest of the mapping interface
    assert list(d.keys()) == list(expected.keys())
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

    def test_zero_is_not_same_as_missing(self):
        d1 = ItemizedDelta(weeks=1)
        d2 = ItemizedDelta(weeks=1, seconds=0)
        assert d1 != d2
        assert not d1 == d2


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
            (ItemizedDelta(months=-6), "-P6M"),
            (ItemizedDelta(minutes=-600), "-PT600M"),
        ],
    )
    def test_format_iso(self, d, expected):
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
            # # non-uppercase
            (
                "pt58m2.999996s",
                ItemizedDelta(minutes=58, seconds=2, nanoseconds=999_996_000),
            ),
            ("PT316192377600s", ItemizedDelta(seconds=316192377600)),
            ("PT400h", ItemizedDelta(hours=400)),
            # # comma instead of dot
            ("PT1,999997S", ItemizedDelta(seconds=1, nanoseconds=999_997_000)),
        ],
    )
    def test_valid(self, s: str, expected: ItemizedDelta):
        assert ItemizedDelta.parse_iso(s) == expected

    @pytest.mark.parametrize("s", INVALID_DELTAS)
    def test_invalid(self, s: str):
        with pytest.raises(ValueError):
            ItemizedDelta.parse_iso(s)


def test_abs():
    d = ItemizedDelta(days=-5, hours=-3, nanoseconds=-200)
    assert abs(d) == ItemizedDelta(days=5, hours=3, nanoseconds=200)

    d_pos = ItemizedDelta(days=2, minutes=30)
    assert abs(d_pos) is d_pos

    d_zero = ItemizedDelta(seconds=0)
    assert abs(d_zero) is d_zero


def test_neg():
    d = ItemizedDelta(days=5, hours=3, nanoseconds=200)
    assert -d == ItemizedDelta(days=-5, hours=-3, nanoseconds=-200)
    assert --d == d

    d_zero = ItemizedDelta(seconds=0)
    neg_zero = -d_zero
    assert neg_zero is d_zero


class TestAddAndSubtract:
    def test_valid(self):
        d1 = ItemizedDelta(
            years=1,
            months=2,
            days=5,
            hours=3,
            seconds=41,
            nanoseconds=987_654_321,
        )
        d2 = ItemizedDelta(weeks=1, months=13, hours=4, nanoseconds=500)

        assert d1 + d2 == ItemizedDelta(
            years=1,
            months=15,
            weeks=1,
            days=5,
            hours=7,
            seconds=41,
            nanoseconds=987_654_821,
        )
        assert d1 + ItemizedDelta(days=0) == d1
        assert d1 + ItemizedDelta(minutes=0) == ItemizedDelta(
            years=1,
            months=2,
            days=5,
            hours=3,
            minutes=0,
            seconds=41,
            nanoseconds=987_654_321,
        )
        assert d1 + ItemizedDelta(days=-3, hours=-3) == ItemizedDelta(
            years=1,
            months=2,
            days=2,
            hours=0,
            seconds=41,
            nanoseconds=987_654_321,
        )

        # nanosecond overflow
        assert d1 + ItemizedDelta(nanoseconds=200_000_000) == ItemizedDelta(
            years=1,
            months=2,
            days=5,
            hours=3,
            seconds=42,
            nanoseconds=187_654_321,
        )
        # nanosecond underflow
        assert d1 + ItemizedDelta(nanoseconds=-999_000_000) == ItemizedDelta(
            years=1,
            months=2,
            days=5,
            hours=3,
            seconds=40,
            nanoseconds=988_654_321,
        )

        # resulting in zero delta
        assert d1 + (-d1) == ItemizedDelta(
            years=0, months=0, days=0, hours=0, seconds=0, nanoseconds=0
        )
        # resulting in sign swap
        assert d1 + ItemizedDelta(
            years=-1,
            months=-5,
            days=-10,
            hours=-4,
            seconds=-41,
            nanoseconds=-987_654_321,
        ) == ItemizedDelta(
            years=0,
            months=-3,
            days=-5,
            hours=-1,
            seconds=0,
            nanoseconds=0,
        )
        # pure nanosecond over/underflow
        assert ItemizedDelta(nanoseconds=900_000_000) + ItemizedDelta(
            nanoseconds=200_000_000
        ) == ItemizedDelta(seconds=1, nanoseconds=100_000_000)
        assert ItemizedDelta(nanoseconds=-900_000_000) + ItemizedDelta(
            nanoseconds=-200_000_000
        ) == ItemizedDelta(seconds=-1, nanoseconds=-100_000_000)
        assert ItemizedDelta(nanoseconds=200) + ItemizedDelta(
            nanoseconds=-500
        ) == ItemizedDelta(nanoseconds=-300)

    def test_mixed_sign_error(self):
        d1 = ItemizedDelta(days=5, hours=3, nanoseconds=200)
        with pytest.raises(ValueError, match="sign"):
            d1 + ItemizedDelta(days=-2, hours=-4)

        with pytest.raises(ValueError, match="sign"):
            d1 + ItemizedDelta(nanoseconds=-201)

        # TODO: max value overflow

        # TODO: ItemizedDelta.in_units() for rebalancing

        # TODO: method to remove zero components


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
def test_pickle(d):
    dumped = pickle.dumps(d)
    assert len(dumped) < 100
    assert pickle.loads(dumped) == d


def test_compatible_unpickle():
    # This is a pickle of ItemizedDelta created with the initial implementation.
    # We keep this test to ensure backwards compatibility.
    dumped = (
        b"\x80\x04\x95A\x00\x00\x00\x00\x00\x00\x00\x8c\x14whenever._pywheneve"
        b"r\x94\x8c\r_unpkl_idelta\x94\x93\x94(K\x01K\x01K\x02K\x03K\x04K\x05K\x06K"
        b"\x07K\x08t\x94R\x94."
    )
    result = pickle.loads(dumped)
    assert result == ItemizedDelta(
        years=1,
        months=2,
        weeks=3,
        days=4,
        hours=5,
        minutes=6,
        seconds=7,
        nanoseconds=8,
    )
