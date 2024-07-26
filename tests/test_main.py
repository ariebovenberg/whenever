import sys
from time import sleep

import pytest

from whenever import (
    ImplicitlyIgnoringDST,
    Instant,
    InvalidOffset,
    hours,
    patch_current_time,
    seconds,
)


@pytest.mark.skipif(
    sys.version_info < (3, 13),
    reason="feature not supported until Python 3.13",
)
def test_multiple_interpreters():
    import _interpreters as interpreters

    for _ in range(10):
        interp_id = interpreters.create()
        interpreters.run_string(
            interp_id,
            "from whenever import Instant; Instant.now()",
        )
        interpreters.destroy(interp_id)


def test_exceptions():
    assert issubclass(ImplicitlyIgnoringDST, TypeError)
    assert issubclass(InvalidOffset, ValueError)


@pytest.mark.skipif(
    sys.implementation.name == "pypy",
    reason="time-machine doesn't support PyPy",
)
def test_time_machine():
    import time_machine

    with time_machine.travel("1980-03-02 02:00 UTC"):
        assert Instant.now() == Instant.from_utc(1980, 3, 2, hour=2)


def test_patch_time():

    i = Instant.from_utc(1980, 3, 2, hour=2)

    # simplest case: freeze time at fixed UTC
    with patch_current_time(i, keep_ticking=False) as p:
        assert Instant.now() == i
        p.shift(hours=3)
        p.shift(hours=1)
        assert i.now() == i.add(hours=4)

    assert Instant.now() != i

    # complex case: freeze time at zoned datetime and keep ticking
    with patch_current_time(
        i.to_tz("Europe/Amsterdam"), keep_ticking=True
    ) as p:
        assert (Instant.now() - i) < seconds(1)
        p.shift(hours=2)
        sleep(0.000001)
        assert hours(2) < (Instant.now() - i) < hours(2.1)
        p.shift(days=2, disambiguate="raise")
        sleep(0.000001)
        assert hours(50) < (Instant.now() - i) < hours(50.1)

    assert Instant.now() - i > hours(40_000)
