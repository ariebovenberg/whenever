import os
import warnings
from contextlib import contextmanager
from pathlib import Path
from sys import _getframe
from typing import Literal
from unittest.mock import patch

import pytest
from whenever import (
    SYSTEM_TZ,
    PlainDateTime,
    ZonedDateTime,
    reset_system_tz,
)

MAX_I64 = 1 << 64

INVALID_DDELTAS = [
    "P3D7Y",  # components out of order
    "P3M7Y",  # components out of order
    "P\U0001d7d9Y",  # non-ASCII
    "P--2D",
    "P++2D",
    "P+-2D",
    "--P2D",
    "++P2D",
    "1P2",
    f"P{MAX_I64 + 2}Y",
    f"P-{MAX_I64 + 2}Y",
    "P3R",  # invalid unit
    "PT3M",  # time component
    "P3.4Y",  # decimal
    "P1,5D",  # comma
    "P1Y2M3W4DT1H2M3S",  # time component
    "P1YT0S",  # zero time component still invalid
    "P99999Y",  # too large
    # incomplete
    "",
    "P",  # no components
    "P34m4",
    "P34",
    "P-D",
    "P+D",
    "P-",
    "P+",
    "Y",
    "5Y",
    "-5Y",
    "P8",
    "P8M3",
]


@contextmanager
def warns_here(warning_class):
    """Like ``pytest.warns``, but also assert the warning points at this very
    ``with`` block instead of at whenever's own internals.

    ``pytest.warns`` matches only the category and the message, so it happily
    accepts a warning whose ``stacklevel`` is off—even though the file and line
    are the only part a user actually sees. Use this wherever the call site
    attribution matters, i.e. nearly everywhere::

        with warns_here(ImplicitDisambiguationWarning):
            ZonedDateTime(2023, 10, 29, 2, 30, tz="Europe/Amsterdam")

    Must be used directly in a test function: 2 frames up is this generator,
    then contextlib's __enter__, then the caller.
    """
    caller_file = _getframe(2).f_code.co_filename
    with pytest.warns(warning_class) as caught:
        yield caught
    for w in caught:
        assert w.filename == caller_file, (
            f"{warning_class.__name__} has a wrong stacklevel: it points at "
            f"{w.filename}:{w.lineno}, not at the caller in {caller_file}"
        )


@contextmanager
def suppress(*warning_classes):
    """Suppress specific warning classes in a block.

    Usage::

        with suppress(StaleOffsetWarning):
            ...

    Can also be used as a decorator::

        @suppress(StaleOffsetWarning)
        def test_something():
            ...
    """
    with warnings.catch_warnings():
        for cls in warning_classes:
            warnings.simplefilter("ignore", cls)
        yield


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


with system_tz(AMS_TZ_POSIX):
    _AMS_POSIX_DT = PlainDateTime(2023, 3, 26, 2, 30).assume_tz(
        SYSTEM_TZ, disambiguation="compatible"
    )

with system_tz(AMS_TZ_RAWFILE):
    _AMS_RAWFILE_DT = PlainDateTime(2023, 3, 26, 2, 30).assume_tz(
        SYSTEM_TZ, disambiguation="compatible"
    )


def create_zdt(
    year: int,
    month: int,
    day: int,
    hour: int = 0,
    minute: int = 0,
    second: int = 0,
    nanosecond: int = 0,
    *,
    tz: str = "",
    disambiguation: Literal[
        "compatible", "earlier", "later", "raise"
    ] = "compatible",
) -> ZonedDateTime:
    """Convenience method to create a ZonedDateTime object, potentially
    with system timezone."""
    # A special check that is only useful in tests of course
    if tz == AMS_TZ_POSIX:
        return _AMS_POSIX_DT.replace(
            year=year,
            month=month,
            day=day,
            hour=hour,
            minute=minute,
            second=second,
            nanosecond=nanosecond,
            disambiguation=disambiguation,
        )
    elif tz == AMS_TZ_RAWFILE:
        return _AMS_RAWFILE_DT.replace(
            year=year,
            month=month,
            day=day,
            hour=hour,
            minute=minute,
            second=second,
            nanosecond=nanosecond,
            disambiguation=disambiguation,
        )
    else:
        return ZonedDateTime(
            year,
            month,
            day,
            hour,
            minute,
            second,
            nanosecond=nanosecond,
            tz=tz,
            disambiguation=disambiguation,
        )
