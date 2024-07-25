import sys

import pytest
import time_machine

from whenever import ImplicitlyIgnoringDST, Instant, InvalidOffset


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


@time_machine.travel("1980-03-02 02:00 UTC")
def test_patch_time():
    assert Instant.now() == Instant.from_utc(1980, 3, 2, hour=2)
