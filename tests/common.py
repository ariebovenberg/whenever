import os
import sys
from contextlib import contextmanager
from time import tzset
from unittest.mock import patch

import pytest

__all__ = [
    "ZoneInfo",
    "ZoneInfoNotFoundError",
    "AlwaysEqual",
    "NeverEqual",
    "AlwaysLarger",
    "AlwaysSmaller",
]

IS_WINDOWS = sys.platform == "win32"


if sys.version_info >= (3, 9):
    from zoneinfo import ZoneInfo, ZoneInfoNotFoundError
else:
    from backports.zoneinfo import ZoneInfo, ZoneInfoNotFoundError


class AlwaysEqual:
    def __eq__(self, other):
        return True


class NeverEqual:
    def __eq__(self, other):
        return False


class AlwaysLarger:
    def __lt__(self, other):
        return False

    def __le__(self, other):
        return False

    def __gt__(self, other):
        return True

    def __ge__(self, other):
        return True


class AlwaysSmaller:
    def __lt__(self, other):
        return True

    def __le__(self, other):
        return True

    def __gt__(self, other):
        return False

    def __ge__(self, other):
        return False


@contextmanager
def local_ams_tz():
    if IS_WINDOWS:
        pytest.skip("tzset is not available on Windows")
    with patch.dict(os.environ, {"TZ": "Europe/Amsterdam"}):
        tzset()
        yield


@contextmanager
def local_nyc_tz():
    if IS_WINDOWS:
        pytest.skip("tzset is not available on Windows")
    with patch.dict(os.environ, {"TZ": "America/New_York"}):
        tzset()
        yield
