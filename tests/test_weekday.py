import pickle

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
    Weekday,
)


def test_repr_rebuilds_the_member():
    namespace: dict[str, object] = {}
    exec("from whenever import *", namespace)
    for w in Weekday:
        assert repr(w) == f"Weekday.{w.name}"
        assert eval(repr(w), namespace) is w


def test_contract():
    assert Weekday(7) is SUNDAY
    assert Weekday.MONDAY.value == 1
    assert MONDAY != 1  # type: ignore[comparison-overlap]
    assert not (MONDAY == 1)  # type: ignore[comparison-overlap]
    with pytest.raises(TypeError):
        MONDAY < TUESDAY  # type: ignore[operator]
    with pytest.raises(TypeError):
        int(MONDAY)  # type: ignore[call-overload]


def test_members_are_the_module_constants():
    assert [
        MONDAY,
        TUESDAY,
        WEDNESDAY,
        THURSDAY,
        FRIDAY,
        SATURDAY,
        SUNDAY,
    ] == list(Weekday)
    assert Date(1915, 7, 19).day_of_week() is MONDAY
    assert Date(1915, 7, 25).day_of_week() is SUNDAY


def test_pickle_is_the_member():
    assert pickle.loads(pickle.dumps(SATURDAY)) is SATURDAY
