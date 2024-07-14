import sys
from time import sleep

import pytest

from whenever import ImplicitlyIgnoringDST, InvalidOffset, hours, seconds


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


def test_patch_time():

    from whenever import Instant, patch_current_time

    i = Instant.from_utc(1980, 3, 2, hour=2)

    with patch_current_time(i, keep_ticking=False) as p:
        assert Instant.now() == i
        p.shift(hours=3)
        p.shift(hours=1)
        assert i.now() == i.add(hours=4)

    assert Instant.now() != i

    with patch_current_time(i, keep_ticking=True) as p:
        assert (Instant.now() - i) < seconds(1)
        p.shift(hours=2)
        sleep(0.000001)
        assert hours(2) < (Instant.now() - i) < hours(2.1)
        p.shift(hours=6)
        sleep(0.000001)
        assert hours(8) < (Instant.now() - i) < hours(8.1)

    assert Instant.now() - i > hours(40_000)
