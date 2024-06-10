import sys

import pytest


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
            "from whenever import UTCDateTime; UTCDateTime.now()",
        )
        interpreters.destroy(interp_id)
