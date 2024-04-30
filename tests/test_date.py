import pickle
import weakref
from copy import copy, deepcopy
from datetime import date as py_date
from itertools import chain, product

import pytest

from tests.common import AlwaysEqual, AlwaysLarger, AlwaysSmaller, NeverEqual
from whenever import (
    FRIDAY,
    MONDAY,
    SATURDAY,
    SUNDAY,
    THURSDAY,
    TUESDAY,
    WEDNESDAY,
    Date,
    DateDelta,
    NaiveDateTime,
    Time,
    days,
)


def test_basics():
    d = Date(2021, 1, 2)
    assert d.year == 2021
    assert d.month == 1
    assert d.day == 2


def test_canonical_format():
    d = Date(2021, 1, 2)
    assert str(d) == "2021-01-02"
    assert d.canonical_format() == "2021-01-02"


class TestFromCanonicalFormat:

    @pytest.mark.parametrize(
        "s, expected",
        [
            ("2021-01-02", Date(2021, 1, 2)),
            ("2014-12-31", Date(2014, 12, 31)),
        ],
    )
    def test_valid(self, s, expected):
        assert Date.from_canonical_format(s) == expected

    @pytest.mark.parametrize(
        "s",
        [
            "2021-01-02T03:04:05",  # with a time
            "2021-1-2",  # no padding
            "2020-123",  # ordinal date
            "2020-W12-3",  # week date
            "20-12-03",  # two-digit year
            "-0123-12-03",  # negative year
        ],
    )
    def test_invalid(self, s):
        with pytest.raises(
            ValueError,
            match=r"Could not parse.*canonical format.*" + repr(s),
        ):
            Date.from_canonical_format(s)


def test_at():
    d = Date(2021, 1, 2)
    assert d.at(Time(3, 4, 5)) == NaiveDateTime(2021, 1, 2, 3, 4, 5)


def test_repr():
    d = Date(2021, 1, 2)
    assert repr(d) == "Date(2021-01-02)"


def test_eq():
    d = Date(2021, 1, 2)
    same = Date(2021, 1, 2)
    different = Date(2021, 1, 3)

    assert d == same
    assert not d == different
    assert not d == NeverEqual()
    assert d == AlwaysEqual()

    assert not d != same
    assert d != different
    assert d != NeverEqual()
    assert not d != AlwaysEqual()

    assert hash(d) == hash(same)


def test_comparison():
    d = Date(2021, 5, 10)
    same = Date(2021, 5, 10)
    bigger = Date(2022, 2, 28)
    smaller = Date(2020, 12, 31)

    assert d <= same
    assert d <= bigger
    assert not d <= smaller
    assert d <= AlwaysLarger()
    assert not d <= AlwaysSmaller()

    assert not d < same
    assert d < bigger
    assert not d < smaller
    assert d < AlwaysLarger()
    assert not d < AlwaysSmaller()

    assert d >= same
    assert not d >= bigger
    assert d >= smaller
    assert not d >= AlwaysLarger()
    assert d >= AlwaysSmaller()

    assert not d > same
    assert not d > bigger
    assert d > smaller
    assert not d > AlwaysLarger()
    assert d > AlwaysSmaller()


@pytest.mark.parametrize(
    "d, kwargs, expected",
    [
        (Date(2021, 1, 31), dict(), Date(2021, 1, 31)),
        (Date(2021, 1, 31), dict(days=1), Date(2021, 2, 1)),
        (Date(2021, 2, 1), dict(days=-1), Date(2021, 1, 31)),
        (Date(2021, 2, 28), dict(months=-2), Date(2020, 12, 28)),
        (Date(2021, 1, 31), dict(years=1), Date(2022, 1, 31)),
        (Date(2021, 1, 31), dict(months=37), Date(2024, 2, 29)),
        (Date(2020, 2, 29), dict(years=1), Date(2021, 2, 28)),
        (Date(2020, 2, 29), dict(years=1, days=1), Date(2021, 3, 1)),
        (Date(2020, 1, 30), dict(years=1, months=1, days=1), Date(2021, 3, 1)),
        (
            Date(2020, 1, 30),
            dict(years=1, months=1, weeks=1),
            Date(2021, 3, 7),
        ),
    ],
)
def test_add(d, kwargs, expected):
    assert d.add(**kwargs) == expected
    assert d + DateDelta(**kwargs) == expected


def test_py():
    d = Date(2021, 1, 2)
    assert d.py_date() == py_date(2021, 1, 2)


def test_from_py_date():
    assert Date.from_py_date(py_date(2021, 1, 2)) == Date(2021, 1, 2)


@pytest.mark.parametrize(
    "d, kwargs, expected",
    [
        (Date(2021, 1, 31), dict(), Date(2021, 1, 31)),
        (Date(2021, 1, 31), dict(days=1), Date(2021, 1, 30)),
        (Date(2021, 2, 1), dict(days=-1), Date(2021, 2, 2)),
        (Date(2021, 2, 28), dict(months=2), Date(2020, 12, 28)),
        (Date(2021, 1, 31), dict(years=1), Date(2020, 1, 31)),
        (Date(2021, 1, 31), dict(months=37), Date(2017, 12, 31)),
        (Date(2020, 2, 29), dict(years=1), Date(2019, 2, 28)),
        (Date(2020, 2, 29), dict(years=1, days=1), Date(2019, 2, 27)),
        (
            Date(2020, 1, 30),
            dict(years=1, months=1, days=1),
            Date(2018, 12, 29),
        ),
        (
            Date(2020, 1, 30),
            dict(years=1, months=1, weeks=1),
            Date(2018, 12, 23),
        ),
    ],
)
def test_subtract(d, kwargs, expected):
    assert d.subtract(**kwargs) == expected
    assert d - DateDelta(**kwargs) == expected


_EXAMPLE_DATES = [
    *chain.from_iterable(
        [
            Date(y, 1, 1),
            Date(y, 1, 2),
            Date(y, 1, 4),
            Date(y, 1, 10),
            Date(y, 1, 28),
            Date(y, 1, 29),
            Date(y, 1, 30),
            Date(y, 1, 31),
            Date(y, 2, 1),
            Date(y, 2, 26),
            Date(y, 2, 27),
            Date(y, 2, 28),
            Date(y, 3, 1),
            Date(y, 3, 2),
            Date(y, 3, 31),
            Date(y, 4, 1),
            Date(y, 4, 2),
            Date(y, 4, 15),
            Date(y, 4, 30),
            Date(y, 5, 1),
            Date(y, 5, 31),
            Date(y, 8, 25),
            Date(y, 11, 30),
            Date(y, 12, 1),
            Date(y, 12, 2),
            Date(y, 12, 27),
            Date(y, 12, 28),
            Date(y, 12, 29),
            Date(y, 12, 30),
            Date(y, 12, 31),
        ]
        for y in (2020, 2021, 2022, 2023, 2024)
    ),
    Date(2024, 2, 29),
    Date(2020, 2, 29),
]


class TestSubtractDate:

    @pytest.mark.parametrize(
        "d1, d2, expected",
        [
            (Date(2021, 1, 31), Date(2021, 1, 1), days(30)),
            (Date(2021, 1, 1), Date(2021, 1, 31), -days(30)),
            (Date(2021, 1, 20), Date(2021, 1, 11), days(9)),
            (Date(2021, 2, 28), Date(2021, 2, 28), days(0)),
            (Date(2021, 2, 28), Date(2021, 2, 27), days(1)),
            (Date(2021, 2, 28), Date(2021, 2, 1), days(27)),
        ],
    )
    def test_days(self, d1, d2, expected):
        assert d1 - d2 == expected

    @pytest.mark.parametrize(
        "d1, d2, delta",
        [
            (Date(2021, 2, 1), Date(2020, 1, 29), DateDelta(years=1, days=3)),
            (Date(2021, 1, 31), Date(2020, 12, 31), DateDelta(months=1)),
            (Date(2020, 12, 31), Date(2021, 1, 31), DateDelta(months=-1)),
            (
                Date(2021, 1, 20),
                Date(2020, 12, 19),
                DateDelta(months=1, days=1),
            ),
            (Date(2024, 2, 28), Date(2024, 2, 29), -DateDelta(days=1)),
            (Date(2024, 2, 29), Date(2024, 2, 28), DateDelta(days=1)),
            (
                Date(2024, 2, 29),
                Date(2023, 3, 1),
                DateDelta(months=11, days=28),
            ),
            (
                Date(2024, 2, 29),
                Date(2023, 3, 2),
                DateDelta(months=11, days=27),
            ),
            (
                Date(2023, 3, 2),
                Date(2024, 2, 29),
                -DateDelta(months=11, days=27),
            ),
            (
                Date(2024, 1, 31),
                Date(2023, 1, 31),
                DateDelta(years=1),
            ),
            (
                Date(2023, 1, 31),
                Date(2024, 2, 29),
                -DateDelta(years=1, days=28),
            ),
            (
                Date(2023, 1, 30),
                Date(2024, 2, 29),
                -DateDelta(years=1, days=29),
            ),
            (
                Date(2022, 12, 30),
                Date(2024, 2, 29),
                -DateDelta(years=1, months=1, days=30),
            ),
            (
                Date(2024, 2, 29),
                Date(2023, 1, 31),
                DateDelta(years=1, months=1),
            ),
            (Date(2024, 2, 29), Date(2023, 2, 28), DateDelta(years=1, days=1)),
            (Date(2023, 2, 28), Date(2024, 2, 29), -DateDelta(years=1)),
            (Date(2023, 2, 28), Date(2024, 2, 28), -DateDelta(years=1)),
            (Date(2025, 2, 28), Date(2024, 2, 29), DateDelta(years=1)),
            (
                Date(2024, 2, 29),
                Date(2025, 2, 28),
                -DateDelta(months=11, days=28),
            ),
            (
                Date(2023, 2, 28),
                Date(2024, 2, 29),
                DateDelta(years=-1),
            ),
        ],
    )
    def test_months_and_years(self, d1, d2, delta):
        assert d1 - d2 == delta
        assert d2 + delta == d1

    def test_fuzzing(self):
        for d1, d2 in product(_EXAMPLE_DATES, _EXAMPLE_DATES):
            delta = d1 - d2
            assert d2 + delta == d1


def test_subtract_invalid():
    with pytest.raises(TypeError, match="unsupported operand"):
        Date(2021, 1, 1) - 1  # type: ignore[operator]
    with pytest.raises(TypeError, match="unsupported operand"):
        Date(2021, 1, 1) - "2021-01-01"  # type: ignore[operator]


def test_day_of_week():
    d = Date(2021, 1, 2)
    assert d.day_of_week() == SATURDAY
    assert Date(2021, 1, 3).day_of_week() == SUNDAY
    assert Date(2021, 1, 4).day_of_week() == MONDAY
    assert Date(2021, 1, 5).day_of_week() == TUESDAY
    assert Date(2021, 1, 6).day_of_week() == WEDNESDAY
    assert Date(2021, 1, 7).day_of_week() == THURSDAY
    assert Date(2021, 1, 8).day_of_week() == FRIDAY


def test_pickling():
    d = Date(2021, 1, 2)
    dumped = pickle.dumps(d)
    assert len(dumped) < len(pickle.dumps(d._py_date)) + 10
    assert pickle.loads(dumped) == d


def test_unpickle_compatibility():
    dumped = (
        b"\x80\x04\x95'\x00\x00\x00\x00\x00\x00\x00\x8c\x08whenever\x94\x8c\x0b_unp"
        b"kl_date\x94\x93\x94M\xe5\x07K\x01K\x02\x87\x94R\x94."
    )
    assert pickle.loads(dumped) == Date(2021, 1, 2)


def test_copy():
    d = Date(2021, 1, 2)
    assert copy(d) is d
    assert deepcopy(d) is d


def test_weakref():
    d = Date(2021, 1, 2)
    ref = weakref.ref(d)
    assert ref() is d


def test_common_iso8601():
    assert Date(2021, 1, 2).common_iso8601() == "2021-01-02"


@pytest.mark.parametrize(
    "s, expected",
    [
        ("2021-01-02", Date(2021, 1, 2)),
        ("2014-12-31", Date(2014, 12, 31)),
    ],
)
def test_from_common_iso8601(s, expected):
    assert Date.from_common_iso8601(s) == expected


@pytest.mark.parametrize(
    "s",
    [
        "2021-01-02T03:04:05",  # with a time
        "2021-1-2",  # no padding
        "2020-123",  # ordinal date
        "2020-W12-3",  # week date
        "20-12-03",  # two-digit year
        "-0123-12-03",  # negative year
    ],
)
def test_from_common_iso8601_invalid(s):
    with pytest.raises(
        ValueError,
        match=r"Could not parse.*ISO 8601.*" + repr(s),
    ):
        Date.from_common_iso8601(s)
