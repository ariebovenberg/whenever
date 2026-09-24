import re
import warnings
from collections import Counter
from collections.abc import ItemsView, KeysView, Mapping, ValuesView
from fractions import Fraction
from typing import Any, Literal, Sequence, cast

import pytest
from whenever import (
    CalendarUnitCompositionWarning,
    Date,
    Instant,
    ItemizedDateDelta,
    ItemizedDelta,
    NaiveArithmeticWarning,
    OffsetDateTime,
    PlainDateTime,
    StaleOffsetWarning,
    ZonedDateTime,
    hours,
)

from .common import INVALID_DDELTAS, Idx, warns_here

UNITS = cast(
    Sequence[Literal["years", "months", "weeks", "days"]],
    "years months weeks days".split(),
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
    "P3M4DT",
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


_D: Any = ItemizedDateDelta(days=1)

RANGE_MSG = "value or calculation out of range"

_DATE = Date(2024, 1, 1)


class TestInit:
    @pytest.mark.parametrize(
        "args, kwargs",
        [
            ((1, 2), {}),  # components are keyword-only
            ((), {"iso_string": "P1Y2D"}),
        ],
    )
    def test_parameter_kinds(self, args, kwargs):
        with pytest.raises(TypeError):
            ItemizedDateDelta(*args, **kwargs)

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
        assert d.sign() == expect_sign
        for unit in UNITS:
            assert d.get(unit, 0) == kwargs.get(unit, 0)

    def test_no_components(self):
        with pytest.raises(
            ValueError, match="^at least one component must be present$"
        ):
            ItemizedDateDelta()

    @pytest.mark.parametrize(
        "kwargs",
        [
            {"days": 1.5},
            {"years": 1.0},
            {"months": float("nan")},
            {"days": Fraction(3, 2)},
            {"days": "1"},
        ],
    )
    def test_component_must_be_integer(self, kwargs):
        (name,) = kwargs
        with pytest.raises(TypeError, match=f"^{name} must be an integer$"):
            ItemizedDateDelta(**kwargs)
        with pytest.raises(TypeError, match=f"^{name} must be an integer$"):
            ItemizedDateDelta(weeks=1).replace(**kwargs)
        with pytest.raises(TypeError, match=f"^{name} must be an integer$"):
            ItemizedDateDelta(weeks=1).add(**kwargs)
        with pytest.raises(TypeError, match=f"^{name} must be an integer$"):
            ItemizedDateDelta(weeks=1).subtract(**kwargs)

    def test_index_protocol(self):
        five = cast(int, Idx())
        assert ItemizedDateDelta(days=five)["days"] == 5
        assert type(ItemizedDateDelta(days=True)["days"]) is int
        assert ItemizedDateDelta(days=True)["days"] == 1
        assert ItemizedDateDelta(weeks=1).replace(days=five)["days"] == 5
        d = ItemizedDateDelta(days=1)
        assert d.add(days=five, cal_unit_composition_ok=True)["days"] == 6
        assert (
            d.subtract(days=five, cal_unit_composition_ok=True)["days"] == -4
        )
        assert (
            type(d.add(days=True, cal_unit_composition_ok=True)["days"]) is int
        )
        assert str(ItemizedDateDelta(days=True, weeks=five)) == "P5W1D"

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

    def test_from_str(self):
        assert ItemizedDateDelta("P2W3D").strict_eq(
            ItemizedDateDelta(weeks=2, days=3)
        )
        assert ItemizedDateDelta("P1Y6M").strict_eq(
            ItemizedDateDelta(years=1, months=6)
        )
        with pytest.raises(ValueError, match="invalid ISO 8601 string"):
            ItemizedDateDelta("not valid")


class TestAccessors:
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
            # an explicit zero is present
            (ItemizedDateDelta(days=0), {"days": 0}),
        ],
    )
    def test_mapping_like_interface(
        self,
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
        assert ItemizedDateDelta(**d) == d  # type: ignore[arg-type]

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

        # get() with a default, and keys of another type
        for key in expected:
            assert d.get(key, 42) == expected[key]
        assert d.get("foo", 42) == 42  # type: ignore[call-overload]
        assert 0 not in d  # type: ignore[comparison-overlap]
        assert 42 not in d  # type: ignore[comparison-overlap]
        with pytest.raises(KeyError):
            d[0]  # type: ignore[index]

    def test_mapping_views(self):
        d = ItemizedDateDelta(years=2, months=3, weeks=4)

        assert isinstance(d, Mapping)

        # KeysView
        keys = d.keys()
        assert isinstance(keys, KeysView)
        assert set(keys) == {"years", "months", "weeks"}
        assert keys | {"extra"} == {"years", "months", "weeks", "extra"}
        assert keys & {"years", "days"} == {"years"}
        assert keys - {"months"} == {"years", "weeks"}

        # ValuesView
        values = d.values()
        assert isinstance(values, ValuesView)
        assert set(values) == {2, 3, 4}

        # ItemsView
        items = d.items()
        assert isinstance(items, ItemsView)
        assert set(items) == {("years", 2), ("months", 3), ("weeks", 4)}
        assert items | {("days", 5)} == {
            ("years", 2),
            ("months", 3),
            ("weeks", 4),
            ("days", 5),
        }

    def test_bool(self):
        d_zero = ItemizedDateDelta(days=0)
        assert not d_zero
        assert d_zero.sign() == 0

        assert not ItemizedDateDelta(years=0)
        assert ItemizedDateDelta(weeks=0).sign() == 0

        d_nonzero = ItemizedDateDelta(weeks=1, days=0)
        assert d_nonzero
        assert d_nonzero.sign() == 1


class TestKeysView:
    def test_iter_order(self):
        keys = ItemizedDateDelta(days=1, years=2).keys()
        assert list(keys) == ["years", "days"]

    def test_and_with_keys_view(self):
        k1 = ItemizedDateDelta(years=1, months=2).keys()
        k2 = ItemizedDateDelta(months=5, days=6).keys()
        result = k1 & k2
        assert isinstance(result, set)
        assert set(result) == {"months"}

    def test_subset(self):
        k1 = ItemizedDateDelta(years=1).keys()
        k2 = ItemizedDateDelta(years=3, months=4).keys()
        assert k1 <= k2
        assert k1 < k2
        assert k2 >= k1
        assert k2 > k1

    def test_isdisjoint(self):
        k1 = ItemizedDateDelta(years=1).keys()
        k2 = ItemizedDateDelta(days=2).keys()
        assert k1.isdisjoint(k2)


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

    @pytest.mark.parametrize("lowercase_units", [True, False])
    def test_round_trip(self, lowercase_units):
        d = ItemizedDateDelta(months=-6, weeks=0, days=-4)
        assert ItemizedDateDelta.parse_iso(
            d.format_iso(lowercase_units=lowercase_units)
        ).strict_eq(d)

    def test_repr(self):
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

    def test_str(self):
        d = ItemizedDateDelta(
            years=3,
            months=6,
            weeks=9,
            days=4,
        )
        assert str(d) == "P3Y6M9W4D" == d.format_iso()
        assert str(ItemizedDateDelta(days=0)) == "P0D"


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
        assert ItemizedDateDelta.parse_iso(s).strict_eq(expected)

    @pytest.mark.parametrize("s", INVALID_DELTAS)
    def test_invalid(self, s: str):
        # a range failure after a successful parse keeps its own text
        with pytest.raises(
            ValueError,
            match=r"^(invalid ISO 8601 string: "
            + re.escape(repr(s))
            + "|delta out of range)$",
        ):
            ItemizedDateDelta.parse_iso(s)

    @pytest.mark.parametrize(
        "s", ["P999999999Y", "P" + "9" * 35 + "D", "P1Y" + "9" * 20 + "M"]
    )
    def test_well_formed_out_of_range(self, s: str):
        with pytest.raises(ValueError, match="^delta out of range$"):
            ItemizedDateDelta.parse_iso(s)

    def test_digit_limit(self):
        assert ItemizedDateDelta.parse_iso("P" + "0" * 34 + "1D").strict_eq(
            ItemizedDateDelta(days=1)
        )
        s = "P" + "0" * 35 + "1D"
        with pytest.raises(
            ValueError, match=f"^invalid ISO 8601 string: {s!r}$"
        ):
            ItemizedDateDelta.parse_iso(s)


class TestEquality:
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
        assert d != {"days": 5}
        assert d != ItemizedDelta(days=5)

    def test_strict_eq(self):
        d1 = ItemizedDateDelta(years=2, months=0, weeks=5, days=0)
        d2 = ItemizedDateDelta(years=2, weeks=5)
        d3 = ItemizedDateDelta(years=2, months=1, weeks=5)
        assert d1.strict_eq(d1)
        assert not d1.strict_eq(d2)
        assert not d1.strict_eq(d3)
        with pytest.raises(
            TypeError,
            match=r"^strict_eq\(\) argument must be an ItemizedDateDelta$",
        ):
            d1.strict_eq(ItemizedDelta(years=2))  # type: ignore[arg-type]
        assert not ItemizedDateDelta(days=1).strict_eq(
            ItemizedDateDelta(days=-1)
        )
        assert ItemizedDateDelta(days=1) != ItemizedDateDelta(days=-1)

    # ``hash()`` agrees with ``==``, which ignores explicit zeros.
    @pytest.mark.parametrize(
        "a, b",
        [
            (
                ItemizedDateDelta(weeks=1, days=2),
                ItemizedDateDelta(weeks=1, days=2),
            ),
            (ItemizedDateDelta(weeks=1, days=0), ItemizedDateDelta(weeks=1)),
            (ItemizedDateDelta(weeks=0, days=1), ItemizedDateDelta(days=1)),
        ],
    )
    def test_equal_values_hash_alike(self, a, b):
        assert a == b
        assert hash(a) == hash(b)

    def test_unequal_values(self):
        assert hash(ItemizedDateDelta(weeks=1, days=2)) != hash(
            ItemizedDateDelta(weeks=2, days=1)
        )

    def test_set_member(self):
        s = {ItemizedDateDelta(weeks=1, days=0), ItemizedDateDelta(weeks=1)}
        assert s == {ItemizedDateDelta(weeks=1)}
        assert ItemizedDateDelta(weeks=1, days=0) in s


class TestReplace:
    def test_valid(self):
        d = ItemizedDateDelta(years=2, months=3, weeks=4)

        # changing an existing value
        assert d.replace(months=10).strict_eq(
            ItemizedDateDelta(years=2, months=10, weeks=4)
        )

        # adding a value
        assert d.replace(days=5).strict_eq(
            ItemizedDateDelta(years=2, months=3, weeks=4, days=5)
        )

        # setting to zero
        assert d.replace(weeks=0).strict_eq(
            ItemizedDateDelta(years=2, months=3, weeks=0)
        )

        # setting to missing (zero)
        assert d.replace(years=None).strict_eq(
            ItemizedDateDelta(months=3, weeks=4)
        )

        # invalid sign
        with pytest.raises(ValueError, match="sign"):
            assert d.replace(days=-1)

        with pytest.raises(ValueError, match="sign"):
            assert (-d).replace(days=1)

        # sign becomes zero
        assert d.replace(years=0, months=0, weeks=0).strict_eq(
            ItemizedDateDelta(years=0, months=0, weeks=0)
        )

        # sign becomes negative
        assert d.replace(years=-3, months=-1, weeks=0, days=-4).strict_eq(
            ItemizedDateDelta(years=-3, months=-1, weeks=0, days=-4)
        )

        # negative becomes positive
        assert (
            (-d)
            .replace(years=3, months=1, weeks=0, days=4)
            .strict_eq(ItemizedDateDelta(years=3, months=1, weeks=0, days=4))
        )

        # last component removed
        with pytest.raises(
            ValueError, match="^at least one component must remain present$"
        ):
            d.replace(years=None, months=None, weeks=None)

        # no arguments
        assert d.replace().strict_eq(d)
        assert (-d).replace().strict_eq(-d)

        # invalid component
        with pytest.raises(
            TypeError,
            match=r"^replace\(\) got an unexpected keyword argument 'foo'$",
        ):
            d.replace(foo=5)  # type: ignore[call-arg]


class TestShift:
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
                {"in_units": ["years", "months"]},
            ),
            # with carry
            (
                ItemizedDateDelta(years=2, months=3, weeks=4, days=5),
                ItemizedDateDelta(years=1, months=8, weeks=3, days=30),
                Date("2021-12-31"),
                ItemizedDateDelta(years=4, months=1, weeks=3, days=1),
                {"in_units": ["years", "months", "weeks", "days"]},
            ),
            # different units
            (
                ItemizedDateDelta(years=2, days=5),
                ItemizedDateDelta(years=1, months=8, days=30),
                Date("0021-08-03"),
                ItemizedDateDelta(years=3, months=9, days=5),
                {"in_units": ["years", "months", "days"]},
            ),
            # customized output kwargs
            (
                ItemizedDateDelta(years=2, days=5),
                ItemizedDateDelta(years=1, months=8, days=30),
                Date("0021-08-03"),
                ItemizedDateDelta(months=45, weeks=2),
                {
                    "in_units": ["months", "weeks"],
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
                {"in_units": ["years", "months"]},
            ),
            # negative arg, positive result
            (
                ItemizedDateDelta(years=2, months=3),
                ItemizedDateDelta(years=-1, months=-4),
                Date("2021-12-31"),
                ItemizedDateDelta(years=0, months=11),
                {"in_units": ["years", "months"]},
            ),
            # negative arg, negative result
            (
                ItemizedDateDelta(years=2, months=3),
                ItemizedDateDelta(years=-1, months=-20),
                Date("2021-12-31"),
                ItemizedDateDelta(years=-0, months=-5),
                {"in_units": ["years", "months"]},
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
        assert result.strict_eq(expected)

        # same result with kwargs
        assert d1.add(**d2, relative_to=relative_to, **kwargs).strict_eq(  # type: ignore[call-overload, arg-type]
            expected
        )

        # same result with subtraction
        if (
            kwargs.get("round_increment", 1) == 1
            and kwargs.get("round_mode", "trunc") == "trunc"
        ):
            assert d1.subtract(
                -d2, relative_to=relative_to, **kwargs
            ).strict_eq(expected)

            assert d1.subtract(  # type: ignore[call-overload]
                **{k: -v for k, v in d2.items()},
                relative_to=relative_to,
                **kwargs,
            ).strict_eq(expected)

    def test_mixed_sign_in_kwargs_allowed(self):
        assert (
            ItemizedDateDelta(years=2)
            .add(
                years=-1,
                months=3,
                relative_to=Date("2021-12-31"),
                in_units=["years", "months"],
            )
            .strict_eq(ItemizedDateDelta(years=1, months=3))
        )

    def test_no_positional_and_kwarg_mix(self):
        with pytest.raises(TypeError, match="mix"):
            ItemizedDateDelta(years=2).add(  # type: ignore[call-overload]
                ItemizedDateDelta(years=1),
                years=3,
                relative_to=Date("2021-12-31"),
                in_units=["years"],
            )

    def test_add_nothing(self):
        result = ItemizedDateDelta(years=2).add(
            relative_to=Date("2021-12-31"),
            in_units=["years", "months"],
        )
        assert result.strict_eq(ItemizedDateDelta(years=2, months=0))

    def test_add_nothing_changes_units(self):
        assert (
            ItemizedDateDelta(years=2)
            .add(relative_to=Date("2021-12-31"), in_units=["months", "days"])
            .strict_eq(ItemizedDateDelta(months=24, days=0))
        )

    def test_invalid_unit_kwarg(self):
        with pytest.raises(TypeError, match="foo"):
            ItemizedDateDelta(years=2).add(  # type: ignore[call-overload]
                foo=5,
                relative_to=Date("2021-12-31"),
                in_units=["years", "months"],
            )

    def test_overflows(self):
        with pytest.raises(ValueError, match="out of range"):
            ItemizedDateDelta(years=5_000).add(
                years=5_000,
                relative_to=Date("2021-12-31"),
                in_units=["years"],
            )

        # Overflow due to relative_to
        with pytest.raises(ValueError, match="out of range"):
            ItemizedDateDelta(years=5).add(
                months=29,
                relative_to=Date("9994-12-31"),
                in_units=["years", "months"],
            )

    def test_floor_round_mode_behaves_correctly_on_negative(self):
        d1 = ItemizedDateDelta(years=4, months=5)
        d2 = ItemizedDateDelta(years=-8, months=-2)

        assert d1.add(
            d2,
            relative_to=Date("2021-11-20"),
            round_mode="floor",
            round_increment=2,
            in_units=["years", "months"],
        ).strict_eq(ItemizedDateDelta(years=-3, months=-10))

    def test_month_clamping_avoided_by_summing_first(self):
        # Sequential application would apply the month-end clamping twice:
        # Jan 31 + 1 month → Feb 28 (clamped), Feb 28 + 1 month → Mar 28.
        # Summing first avoids the intermediate clamp:
        # Jan 31 + 2 months = Mar 31.
        assert (
            ItemizedDateDelta(months=1)
            .add(months=1, relative_to=Date(2021, 1, 31), in_units=["months"])
            .strict_eq(ItemizedDateDelta(months=2))
        )

    def test_full_delta_with_datetime_reference(self):
        reference = ZonedDateTime(2021, 1, 31, tz="UTC")
        result = ItemizedDateDelta(months=1).add(
            ItemizedDelta(months=1, hours=2),
            relative_to=reference,
            in_units=["months", "hours"],
        )
        assert result.strict_eq(ItemizedDelta(months=2, hours=2))

        result = ItemizedDateDelta(months=3).subtract(
            ItemizedDelta(months=1, hours=2),
            relative_to=reference,
            in_units=["hours"],
        )
        assert result.strict_eq(ItemizedDelta(hours=1414))

    def test_full_delta_requires_datetime_reference(self):
        with pytest.raises(
            TypeError, match="relative_to must be a .*DateTime"
        ):
            ItemizedDateDelta(months=1).add(
                ItemizedDelta(hours=1),
                relative_to=Date(2021, 1, 31),  # type: ignore[call-overload]
                in_units=["hours"],
            )

    def test_reference_free_add_and_subtract(self):
        with warns_here(CalendarUnitCompositionWarning):
            result = ItemizedDateDelta(days=1).add(ItemizedDateDelta(days=0))
        assert result.strict_eq(ItemizedDateDelta(days=1))

        with warns_here(CalendarUnitCompositionWarning):
            result = ItemizedDateDelta(days=1).add(days=2)
        assert result.strict_eq(ItemizedDateDelta(days=3))

        with warns_here(CalendarUnitCompositionWarning):
            full_result = ItemizedDateDelta(days=2).subtract(
                ItemizedDelta(days=1)
            )
        assert full_result.strict_eq(ItemizedDelta(days=1))

    def test_operator_composition(self):
        with warns_here(CalendarUnitCompositionWarning):
            result = ItemizedDateDelta(days=1) + ItemizedDateDelta(months=2)
        assert result.strict_eq(ItemizedDateDelta(months=2, days=1))

        with warns_here(CalendarUnitCompositionWarning):
            full_result = ItemizedDateDelta(days=2) + ItemizedDelta(days=3)
        assert full_result.strict_eq(ItemizedDelta(days=5))

        with warns_here(CalendarUnitCompositionWarning):
            full_result = ItemizedDateDelta(days=2) - ItemizedDelta(days=1)
        assert full_result.strict_eq(ItemizedDelta(days=1))

    def test_cal_unit_composition_ok_is_read_by_truthiness(self):
        d = ItemizedDateDelta(months=1)
        with warnings.catch_warnings():
            warnings.simplefilter("error")
            d.add(days=1, cal_unit_composition_ok=1)  # type: ignore[call-overload]
        with warns_here(CalendarUnitCompositionWarning):
            d.add(days=1, cal_unit_composition_ok="")  # type: ignore[call-overload]

    def test_cal_unit_composition_ok_suppresses_warning(self):
        result = ItemizedDateDelta(days=1).add(
            ItemizedDateDelta(days=0), cal_unit_composition_ok=True
        )
        assert result.strict_eq(ItemizedDateDelta(days=1))

    def test_no_op_does_not_warn(self):
        d = ItemizedDateDelta(days=1)
        result = d.add()
        assert result is d

    def test_invalid_reference_free_arguments(self):
        with pytest.raises(TypeError, match="relative_to"):
            ItemizedDateDelta(days=1).add(  # type: ignore[call-overload]
                days=1, round_mode="ceil"
            )
        with pytest.raises(TypeError, match="relative_to"):
            ItemizedDateDelta(days=1).add(  # type: ignore[call-overload]
                days=1, in_units=["days"], cal_unit_composition_ok=True
            )

    @pytest.mark.parametrize("method", ["add", "subtract"])
    def test_invalid_composition_arguments(self, method: str):
        delta = ItemizedDateDelta(days=1)
        operation = getattr(delta, method)
        reference = Date("2024-01-01")
        with pytest.raises(TypeError, match="mix"):
            operation(ItemizedDateDelta(days=1), days=1)
        with pytest.raises(
            TypeError, match="argument must be an ItemizedDelta"
        ):
            operation(1)
        with pytest.raises(TypeError, match="foo"):
            operation(foo=1)
        with pytest.raises(TypeError, match="in_units"):
            operation(days=1, relative_to=reference)
        with pytest.raises(TypeError, match="relative_to"):
            operation(days=1, in_units=["days"])
        with pytest.raises(
            TypeError,
            match="round_mode and round_increment require relative_to",
        ):
            operation(days=1, round_mode="ceil")

    @pytest.mark.parametrize("method", ["add", "subtract"])
    @pytest.mark.parametrize(
        "rounding, error",
        [
            ({"round_mode": ""}, ValueError),
            ({"round_increment": 0}, ValueError),
            ({"round_increment": 0.5}, TypeError),
        ],
    )
    def test_invalid_rounding_arguments(
        self,
        method: str,
        rounding: dict[str, str | int | float],
        error: type[Exception],
    ):
        delta = ItemizedDateDelta(days=1)
        operation = getattr(delta, method)
        reference = Date("2024-01-01")
        with pytest.raises(error):
            operation(
                days=1,
                relative_to=reference,
                in_units=["days"],
                **rounding,
            )
        with pytest.raises(
            TypeError,
            match="round_mode and round_increment require relative_to",
        ):
            operation(round_mode="ceil", round_increment=2)

    def test_subtract_no_op_and_date_result(self):
        delta = ItemizedDateDelta(days=1)
        assert delta.subtract() is delta
        with warns_here(CalendarUnitCompositionWarning):
            result = delta.subtract(ItemizedDateDelta(days=1))
        assert result.strict_eq(ItemizedDateDelta(days=0))

    def test_full_delta_add_and_suppressed_subtract_warning(self):
        with warns_here(CalendarUnitCompositionWarning):
            result = ItemizedDateDelta(days=1).add(ItemizedDelta(hours=1))
        assert result.strict_eq(ItemizedDelta(days=1, hours=1))

        result = ItemizedDateDelta(days=1).subtract(
            ItemizedDelta(hours=-1), cal_unit_composition_ok=True
        )
        assert result.strict_eq(ItemizedDelta(days=1, hours=1))

    def test_unsupported_operand(self):
        with pytest.raises(TypeError):
            assert ItemizedDateDelta(days=1) + 1  # type: ignore[operator]

        with pytest.raises(TypeError):
            assert ItemizedDateDelta(days=1) - 1  # type: ignore[operator]

    def test_plain_datetime_reference(self):
        reference = PlainDateTime(2024, 3, 30, 12)
        with warnings.catch_warnings():
            warnings.simplefilter("error")
            result = ItemizedDateDelta(months=1).add(
                days=1, relative_to=reference, in_units=["months", "days"]
            )
        assert result.strict_eq(ItemizedDateDelta(months=1, days=1))

    def test_abs(self):
        d = ItemizedDateDelta(days=-5, weeks=-3)
        assert abs(d).strict_eq(ItemizedDateDelta(days=5, weeks=3))

        d_pos = ItemizedDateDelta(days=2, years=30)
        assert abs(d_pos) is d_pos

        d_zero = ItemizedDateDelta(months=0)
        assert abs(d_zero) is d_zero

    def test_neg(self):
        d = ItemizedDateDelta(days=5, weeks=3, years=200)
        assert (-d).strict_eq(ItemizedDateDelta(days=-5, weeks=-3, years=-200))
        assert (--d).strict_eq(d)

        d_zero = ItemizedDateDelta(weeks=0)
        assert -d_zero is d_zero


class TestInUnits:
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
            (
                ItemizedDateDelta(days=45),
                Date("2021-01-01"),
                ["months"],
                {"round_mode": "half_even"},
                ItemizedDateDelta(months=2),
            ),
            (
                ItemizedDateDelta(days=45),
                Date("2021-01-01"),
                ["months"],
                {"round_mode": "half_floor"},
                ItemizedDateDelta(months=1),
            ),
        ],
    )
    def test_valid(
        self,
        d: ItemizedDateDelta,
        relative_to: Date,
        units: Sequence[Literal["years", "months", "weeks", "days"]],
        kwargs: Any,
        expect: ItemizedDateDelta,
    ):
        assert d.in_units(units, relative_to=relative_to, **kwargs).strict_eq(
            expect
        )
        if kwargs.get("round_increment", 1) == 1 and units[-1] == "days":
            assert relative_to.add(expect) == relative_to.add(d)


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
                "foo",  # type: ignore[arg-type]
                relative_to=Date("2021-12-31"),
            )

    def test_no_relative_to(self):
        with pytest.raises(TypeError, match="relative_to"):
            ItemizedDateDelta(years=2).total("months")  # type: ignore[call-arg]

    def test_relative_to_overflows(self):
        with pytest.raises(ValueError, match="out of range"):
            ItemizedDateDelta(years=2).total(
                "months", relative_to=Date("9998-04-30")
            )

        with pytest.raises(ValueError, match="out of range"):
            ItemizedDateDelta(years=-2).total(
                "months", relative_to=Date("0001-12-31")
            )


class TestMessages:
    """One template per condition, identical on both backends."""

    @pytest.mark.parametrize(
        "call, error, message",
        [
            (
                lambda: _D.add(days=1, in_units=["days"]),
                TypeError,
                "in_units requires relative_to",
            ),
            (
                lambda: _D.add(days=1, relative_to=_DATE),
                TypeError,
                "in_units is required with relative_to",
            ),
            (
                lambda: _D.add(days=1, round_mode="ceil"),
                TypeError,
                "round_mode and round_increment require relative_to",
            ),
            (
                lambda: _D.add(_D, days=1),
                TypeError,
                "add() cannot mix positional and keyword arguments",
            ),
            (
                lambda: _D.subtract(_D, days=1),
                TypeError,
                "subtract() cannot mix positional and keyword arguments",
            ),
            (
                lambda: _D.add(foo=1),
                TypeError,
                "ItemizedDateDelta.add() got an unexpected keyword argument 'foo'",
            ),
            (
                lambda: _D.in_units([], relative_to=_DATE),
                ValueError,
                "in_units must not be empty",
            ),
            (
                lambda: _D.in_units(["foo"], relative_to=_DATE),
                ValueError,
                "invalid unit: 'foo'",
            ),
            (
                lambda: _D.in_units(["hours"], relative_to=_DATE),
                ValueError,
                "invalid unit: 'hours'",
            ),
            (
                lambda: _D.total("foo", relative_to=_DATE),
                ValueError,
                "invalid unit: 'foo'",
            ),
            (
                lambda: _D.total("hours", relative_to=_DATE),
                ValueError,
                "invalid unit: 'hours'",
            ),
            (
                lambda: _D.add(days=1, relative_to=_DATE, in_units=["hours"]),
                ValueError,
                "invalid unit: 'hours'",
            ),
            (
                lambda: _D.in_units(
                    ["days"], relative_to=_DATE, round_mode="foo"
                ),
                ValueError,
                "invalid round_mode: 'foo'",
            ),
            (
                lambda: _D.in_units(
                    ["days"], relative_to=_DATE, round_increment=1.5
                ),
                TypeError,
                "round_increment must be an integer",
            ),
            (
                lambda: _D.in_units(
                    ["days"], relative_to=_DATE, round_increment=0
                ),
                ValueError,
                "round_increment must be a positive integer in range",
            ),
            (
                lambda: _D.add(
                    days=1,
                    relative_to=_DATE,
                    in_units=["days"],
                    round_increment=0,
                ),
                ValueError,
                "round_increment must be a positive integer in range",
            ),
            (
                lambda: _D.in_units(
                    ["days"], relative_to=_DATE, round_increment=10**9
                ),
                ValueError,
                "round_increment must be a positive integer in range",
            ),
            (
                lambda: _D.in_units(
                    ["months"], relative_to=_DATE, round_increment=10**9
                ),
                ValueError,
                "round_increment must be a positive integer in range",
            ),
            (
                lambda: _D.in_units(
                    ["years"], relative_to=_DATE, round_increment=10**9
                ),
                ValueError,
                "round_increment must be a positive integer in range",
            ),
            (
                lambda: _D.in_units(
                    ["days"],
                    relative_to=Date(9999, 1, 1),
                    round_increment=3_000_000,
                ),
                ValueError,
                RANGE_MSG,
            ),
            (
                lambda: ItemizedDateDelta(years=1).in_units(
                    ["days"], relative_to=Date(9999, 6, 1)
                ),
                ValueError,
                RANGE_MSG,
            ),
            (
                lambda: ItemizedDateDelta(years=1).total(
                    "days", relative_to=Date(9999, 6, 1)
                ),
                ValueError,
                RANGE_MSG,
            ),
            # the rounding step, not the shift, leaves the calendar
            (
                lambda: ItemizedDateDelta(years=1).in_units(
                    ["years"], relative_to=Date(9998, 6, 1), round_increment=5
                ),
                ValueError,
                RANGE_MSG,
            ),
        ],
    )
    def test_messages(self, call, error, message):
        with pytest.raises(error, match=f"^{re.escape(message)}$"):
            call()

    def test_units_is_any_iterable(self):
        d: Any = ItemizedDateDelta(weeks=1, days=3)
        expected = ItemizedDateDelta(weeks=1, days=3)
        assert (
            d.in_units(iter(["weeks", "days"]), relative_to=_DATE) == expected
        )
        assert (
            d.in_units({"weeks": 0, "days": 0}, relative_to=_DATE) == expected
        )
        with pytest.raises(TypeError):
            d.in_units(None, relative_to=_DATE)
        with pytest.raises(TypeError):
            d.add(days=1, relative_to=_DATE, in_units=None)

    def test_raising_calls_do_not_warn(self):
        with warnings.catch_warnings(record=True) as record:
            warnings.simplefilter("always")
            with pytest.raises(ValueError, match="mixed sign"):
                ItemizedDateDelta(months=1, days=1).add(days=-2)
            with pytest.raises(ValueError, match="mixed sign"):
                ItemizedDateDelta(months=1, days=1) + ItemizedDateDelta(
                    days=-2
                )
            with pytest.raises(ValueError, match="mixed sign"):
                ItemizedDateDelta(months=1, days=1) - ItemizedDelta(days=2)
            with pytest.raises(TypeError):
                _D.add(days=1, foo=2)
        assert record == []


class TestReferenceRule:
    """The operands decide the result type; a date-only computation reads a
    datetime reference's date alone, without a warning."""

    DATE = Date(2023, 1, 1)
    REFERENCES = [
        Date(2023, 1, 1),
        ZonedDateTime(2023, 1, 1, 12, tz="Europe/Amsterdam"),
        PlainDateTime(2023, 1, 1, 12),
        OffsetDateTime(2023, 1, 1, 12, offset=hours(2)),
    ]

    @pytest.mark.parametrize("reference", REFERENCES)
    def test_date_operands_give_a_date_delta(self, reference):
        with warnings.catch_warnings():
            warnings.simplefilter("error")
            by_keyword = ItemizedDateDelta(months=1).add(
                days=30, relative_to=reference, in_units=["months", "days"]
            )
            by_delta = ItemizedDateDelta(months=1).subtract(
                ItemizedDateDelta(days=-30),
                relative_to=reference,
                in_units=["months", "days"],
            )
        assert type(by_keyword) is ItemizedDateDelta
        assert by_keyword.strict_eq(ItemizedDateDelta(months=2, days=2))
        assert by_delta.strict_eq(by_keyword)

    @pytest.mark.parametrize("reference", REFERENCES)
    def test_date_operands_take_date_units_only(self, reference):
        with pytest.raises(ValueError, match="^invalid unit: 'hours'$"):
            ItemizedDateDelta(months=1).add(
                days=30,
                relative_to=reference,
                in_units=["months", "hours"],  # type: ignore[list-item]
            )

    def test_full_delta_operand_gives_a_full_delta(self):
        with warns_here(NaiveArithmeticWarning) as caught:
            result = ItemizedDateDelta(months=1).add(
                ItemizedDelta(hours=1),
                relative_to=PlainDateTime(2023, 1, 1),
                in_units=["days", "hours"],
            )
        assert len(caught) == 1
        assert type(result) is ItemizedDelta
        assert result.strict_eq(ItemizedDelta(days=31, hours=1))

    @pytest.mark.parametrize(
        "units, warns, expected",
        [
            (["days"], False, ItemizedDelta(days=1)),
            (["hours"], True, ItemizedDelta(hours=24)),
        ],
    )
    def test_plain_datetime_zero_exact_component(self, units, warns, expected):
        # A zero exact component is no clock arithmetic: the operator and
        # the method agree. A requested exact unit is.
        d = ItemizedDateDelta(days=1)
        ref = PlainDateTime(2020, 1, 1)
        with warnings.catch_warnings():
            warnings.simplefilter("error")
            assert ref + d == PlainDateTime(2020, 1, 2)
        if warns:
            with warns_here(NaiveArithmeticWarning):
                result = d.add(
                    ItemizedDelta(hours=0), relative_to=ref, in_units=units
                )
        else:
            with warnings.catch_warnings():
                warnings.simplefilter("error")
                result = d.add(
                    ItemizedDelta(hours=0), relative_to=ref, in_units=units
                )
        assert result.strict_eq(expected)

    @pytest.mark.parametrize("method", ["add", "subtract"])
    def test_full_delta_operand_reference_rule(self, method):
        operation = getattr(ItemizedDateDelta(months=1), method)
        with warns_here(StaleOffsetWarning) as caught:
            operation(
                ItemizedDelta(hours=1),
                relative_to=OffsetDateTime(2023, 1, 1, offset=hours(2)),
                in_units=["days", "hours"],
            )
        assert len(caught) == 1
        with warnings.catch_warnings():
            warnings.simplefilter("error")
            operation(
                ItemizedDelta(hours=1),
                relative_to=OffsetDateTime(2023, 1, 1, offset=hours(2)),
                in_units=["days", "hours"],
                stale_offset_ok=True,
            )
            operation(
                ItemizedDelta(hours=1),
                relative_to=PlainDateTime(2023, 1, 1),
                in_units=["days", "hours"],
                naive_arithmetic_ok=True,
            )
            operation(
                ItemizedDelta(hours=1),
                relative_to=ZonedDateTime(2023, 1, 1, tz="Europe/Amsterdam"),
                in_units=["days", "hours"],
            )

    @pytest.mark.parametrize("reference", REFERENCES)
    def test_in_units_and_total_read_the_date(self, reference):
        d = ItemizedDateDelta(months=1, days=40)
        with warnings.catch_warnings():
            warnings.simplefilter("error")
            balanced = d.in_units(["months", "days"], relative_to=reference)
            total = d.total("days", relative_to=reference)
        assert type(balanced) is ItemizedDateDelta
        assert balanced.strict_eq(
            d.in_units(["months", "days"], relative_to=self.DATE)
        )
        assert total == d.total("days", relative_to=self.DATE) == 71.0

    @pytest.mark.parametrize(
        "call",
        [
            lambda ref: ItemizedDateDelta(days=1).total(
                "days", relative_to=ref
            ),
            lambda ref: ItemizedDateDelta(days=1).in_units(
                ["days"], relative_to=ref
            ),
            lambda ref: ItemizedDateDelta(days=1).add(
                days=1, relative_to=ref, in_units=["days"]
            ),
        ],
    )
    def test_invalid_reference_type(self, call):
        with pytest.raises(
            TypeError,
            match="^relative_to must be a Date, ZonedDateTime, PlainDateTime, "
            "or OffsetDateTime$",
        ):
            call(Instant.from_utc(2023, 1, 1))
