import sys

import pytest

from whenever import ImplicitlyIgnoringDST, InvalidOffset


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
