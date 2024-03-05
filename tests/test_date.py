import pytest

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
)

from .common import AlwaysEqual, NeverEqual


def test_basics():
    d = Date(2021, 1, 2)
    assert d.year == 2021
    assert d.month == 1
    assert d.day == 2


def test_canonical_format():
    d = Date(2021, 1, 2)
    assert str(d) == "2021-01-02"
    assert d.canonical_format() == "2021-01-02"


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


def test_day_of_week():
    d = Date(2021, 1, 2)
    assert d.day_of_week() == SATURDAY
    assert Date(2021, 1, 3).day_of_week() == SUNDAY
    assert Date(2021, 1, 4).day_of_week() == MONDAY
    assert Date(2021, 1, 5).day_of_week() == TUESDAY
    assert Date(2021, 1, 6).day_of_week() == WEDNESDAY
    assert Date(2021, 1, 7).day_of_week() == THURSDAY
    assert Date(2021, 1, 8).day_of_week() == FRIDAY
