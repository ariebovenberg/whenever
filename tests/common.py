import os
from contextlib import contextmanager
from pathlib import Path
from unittest.mock import patch

from whenever import reset_system_tz

# The POSIX TZ string for the Amsterdam timezone.
AMS_TZ_POSIX = "CET-1CEST,M3.5.0,M10.5.0/3"
# A non-standard path to the Amsterdam timezone file, that can't be traced
# back to the zoneinfo database.
AMS_TZ_RAWFILE = str(Path(__file__).parent / "tzif" / "Amsterdam.tzif")


class AlwaysEqual:
    def __eq__(self, _):
        return True


class NeverEqual:
    def __eq__(self, _):
        return False


class AlwaysLarger:
    def __lt__(self, _):
        return False

    def __le__(self, _):
        return False

    def __gt__(self, _):
        return True

    def __ge__(self, _):
        return True


class AlwaysSmaller:
    def __lt__(self, _):
        return True

    def __le__(self, _):
        return True

    def __gt__(self, _):
        return False

    def __ge__(self, _):
        return False


@contextmanager
def system_tz_ams():
    try:
        with patch.dict(os.environ, {"TZ": "Europe/Amsterdam"}):
            reset_system_tz()
            yield
    finally:
        reset_system_tz()  # don't forget to reset the timezone after the patch!


@contextmanager
def system_tz(name):
    try:
        with patch.dict(os.environ, {"TZ": name}):
            reset_system_tz()
            yield
    finally:
        reset_system_tz()  # don't forget to reset the timezone after the patch!


@contextmanager
def system_tz_nyc():
    try:
        with patch.dict(os.environ, {"TZ": "America/New_York"}):
            reset_system_tz()
            yield
    finally:
        reset_system_tz()  # don't forget to reset the timezone after the patch!
