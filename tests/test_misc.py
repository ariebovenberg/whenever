import json
import os
import pickle
import subprocess
import sys
import warnings
from contextlib import nullcontext
from copy import copy, deepcopy
from time import sleep
from unittest.mock import patch

import pytest
from whenever import (
    _EXTENSION_LOADED,
    SYSTEM_TZ,
    Date,
    Instant,
    ItemizedDateDelta,
    ItemizedDelta,
    OffsetDateTime,
    PlainDateTime,
    TimeDelta,
    TimePatch,
    ZonedDateTime,
    get_tzpath,
    hours,
    patch_current_time,
    reset_system_tz,
    reset_tzpath,
)
from whenever._tz.system import _tzid_from_path, get_tz

from .common import system_tz_ams

pytestmark = pytest.mark.filterwarnings(
    "ignore::whenever.WheneverDeprecationWarning"
)


@pytest.mark.parametrize(
    "dt, delta, expected",
    [
        (
            Date(2021, 1, 31),
            ItemizedDateDelta(months=1),
            Date(2021, 2, 28),
        ),
        (
            PlainDateTime(2021, 1, 31),
            ItemizedDelta(months=1, hours=2),
            PlainDateTime(2021, 2, 28, 2),
        ),
        (
            OffsetDateTime(2021, 1, 31, offset=hours(0)),
            ItemizedDelta(months=1, hours=2),
            OffsetDateTime(2021, 2, 28, 2, offset=hours(0)),
        ),
        (
            ZonedDateTime(2021, 1, 31, tz="UTC"),
            ItemizedDelta(months=1, hours=2),
            ZonedDateTime(2021, 2, 28, 2, tz="UTC"),
        ),
    ],
)
def test_itemized_delta_datetime_operators(dt, delta, expected):
    warning = isinstance(dt, (PlainDateTime, OffsetDateTime))
    with pytest.warns(Warning) if warning else nullcontext():
        assert dt + delta == expected
    with pytest.warns(Warning) if warning else nullcontext():
        assert delta + dt == expected
    with pytest.warns(Warning) if warning else nullcontext():
        subtracted = dt - delta
    with pytest.warns(Warning) if warning else nullcontext():
        expected_subtracted = dt.subtract(delta)
    assert subtracted == expected_subtracted


@pytest.mark.parametrize(
    "operation",
    [
        lambda dt, delta: dt + delta,
        lambda dt, delta: delta + dt,
        lambda dt, delta: dt - delta,
    ],
)
@pytest.mark.parametrize("delta", [ItemizedDelta(hours=1), hours(1)])
def test_datetime_operator_warning_location(operation, delta):
    dt = PlainDateTime(2021, 1, 31)
    with pytest.warns(Warning) as caught:
        operation(dt, delta)
    assert all("_ideltas.py" not in warning.filename for warning in caught)


@pytest.mark.parametrize(
    "delta",
    [ItemizedDelta(months=1), ItemizedDateDelta(days=1)],
)
def test_plain_datetime_calendar_delta_operators_do_not_warn(delta):
    dt = PlainDateTime(2021, 1, 31)
    with warnings.catch_warnings():
        warnings.simplefilter("error")
        dt + delta
        delta + dt
        dt - delta


def test_zero_time_delta_plain_datetime_addition_warns_from_both_sides():
    dt = PlainDateTime(2021, 1, 31)
    delta = TimeDelta.ZERO
    with pytest.warns(Warning):
        dt + delta
    with pytest.warns(Warning):
        delta + dt


@pytest.mark.parametrize(
    "delta", [ItemizedDelta(hours=1), ItemizedDateDelta(days=1)]
)
@pytest.mark.parametrize("method", ["__radd__", "__rsub__"])
def test_itemized_delta_reflected_operator_not_implemented(delta, method):
    assert getattr(delta, method)(object()) is NotImplemented


@pytest.mark.parametrize(
    "dt",
    [
        PlainDateTime(2021, 1, 31),
        OffsetDateTime(2021, 1, 31, offset=hours(0)),
        ZonedDateTime(2021, 1, 31, tz="UTC"),
        Instant.from_utc(2021, 1, 31),
    ],
)
def test_time_delta_reflected_datetime_addition(dt):
    delta = hours(2)
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        expected = dt + delta
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        assert delta + dt == expected


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


def test_type_aliases():
    from whenever import AnyDelta  # noqa
    from whenever import DateDeltaUnitStr  # noqa
    from whenever import DeltaUnitStr  # noqa
    from whenever import DisambiguateStr  # noqa
    from whenever import ExactDeltaUnitStr  # noqa
    from whenever import OffsetMismatchStr  # noqa
    from whenever import RoundModeStr  # noqa


def test_version():
    from whenever import __version__

    assert isinstance(__version__, str)


def test_dir_includes_public_names():
    import whenever

    expected = {
        *whenever.__all__,
        "TZPATH",
        "__version__",
        "_EXTENSION_LOADED",
        "RoundModeStr",
    }
    assert expected <= set(dir(whenever))

    result = subprocess.run(
        [
            sys.executable,
            "-c",
            "import sys; import whenever; "
            f"expected = {expected!r}; "
            "assert expected <= set(dir(whenever)); "
            "assert 'whenever._core' not in sys.modules; "
            "assert 'whenever._utils' not in sys.modules; "
            "assert 'whenever._typing' not in sys.modules",
        ],
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, result.stderr


def test_star_import_includes_utilities():
    result = subprocess.run(
        [
            sys.executable,
            "-c",
            "namespace = {}; exec('from whenever import *', namespace); "
            "expected = {'patch_current_time', 'reset_tzpath', "
            "'clear_tzcache', 'available_timezones'}; "
            "assert expected <= namespace.keys()",
        ],
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, result.stderr


def test_itemized_runtime_annotations_resolve_from_lazy_import():
    result = subprocess.run(
        [
            sys.executable,
            "-c",
            "import sys; from typing import get_type_hints; "
            "import whenever; "
            "ItemizedDelta = whenever.ItemizedDelta; "
            "ItemizedDateDelta = whenever.ItemizedDateDelta; "
            "assert 'whenever._core' not in sys.modules; "
            "assert get_type_hints(ItemizedDelta.add)['relative_to'] "
            "is whenever.ZonedDateTime; "
            "get_type_hints(ItemizedDelta.date_and_time_parts); "
            "get_type_hints(ItemizedDateDelta.__add__); "
            "assert get_type_hints(ItemizedDateDelta.total)['relative_to'] "
            "is whenever.Date",
        ],
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, result.stderr


def test_no_attr_on_module():
    with pytest.raises((AttributeError, ImportError), match="DoesntExist"):
        from whenever import DoesntExist  # type: ignore[attr-defined] # noqa


@pytest.mark.skipif(
    not _EXTENSION_LOADED, reason="only relevant when extension is active"
)
def test_extension_doesnt_import_tz_modules():
    # When the Rust extension is active, the Python timezone subsystem
    # (_tz, calendar, platform) and _shared must not be imported just by doing
    # `import whenever`. Violations here mean slow startup for all users.
    result = subprocess.run(
        [
            sys.executable,
            "-c",
            "import whenever, json, sys; "
            "print(json.dumps([k for k in sys.modules "
            "if k == 'whenever._tz' or k.startswith('whenever._tz.')  "
            "or k == 'whenever._shared' "
            "or k == 'whenever._typing' "
            "or k == 'whenever._utils' "
            "or k in ('calendar', 'platform')]))",
        ],
        capture_output=True,
        text=True,
        check=True,
    )
    imported = json.loads(result.stdout)
    assert imported == [], (
        f"unexpected modules imported on 'import whenever': {imported}"
    )


@pytest.mark.skipif(
    not _EXTENSION_LOADED, reason="only relevant when extension is active"
)
def test_module_cleanup_runs():
    # Verify module_free is called on interpreter shutdown (debug builds only).
    # This ensures Python objects held by module state are properly released.
    result = subprocess.run(
        [sys.executable, "-c", "import whenever"],
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0
    if "[whenever] module_exec (debug)" not in result.stderr:
        pytest.skip("extension not built with debug_assertions")
    # In debug builds, module_free MUST be called during shutdown
    assert "[whenever] module_free called" in result.stderr


@pytest.mark.skipif(
    sys.implementation.name == "pypy",
    reason="time-machine doesn't support PyPy",
)
def test_time_machine():
    time_machine = pytest.importorskip("time_machine")

    with time_machine.travel("1980-03-02T02:00+00:00"):
        assert Instant.now() == Instant.from_utc(1980, 3, 2, hour=2)


@system_tz_ams()
def test_patch_time():

    i = Instant.from_utc(1980, 3, 2, hour=2)

    # simplest case: freeze time at fixed UTC
    with patch_current_time(i, keep_ticking=False) as p:
        assert isinstance(p, TimePatch)
        assert Instant.now() == i
        assert Date.today_in_system_tz() == i.to_system_tz().date()
        assert Date.today(SYSTEM_TZ) == i.to_tz(SYSTEM_TZ).date()
        assert (
            Date.today("Europe/Amsterdam")
            == i.to_tz("Europe/Amsterdam").date()
        )
        with pytest.raises(TypeError):
            Date.today(tz="Europe/Amsterdam")  # type: ignore[call-arg]
        assert ZonedDateTime.now(SYSTEM_TZ).tz_id == "Europe/Amsterdam"
        assert PlainDateTime(2020, 8, 15).assume_tz(SYSTEM_TZ).tz_id == (
            "Europe/Amsterdam"
        )
        p.shift(hours=3)
        p.shift(hours(1))
        assert Instant.now() == i.add(hours=4)
        p.move_to(i.to_fixed_offset(hours(2)))
        assert Instant.now() == i

    # patch has ended
    assert Instant.now() > Instant.from_utc(2024, 1, 1)
    assert Date.today_in_system_tz() > Date(2024, 1, 1)

    # complex case: freeze time at zoned datetime and keep ticking
    with patch_current_time(
        i.to_tz("Europe/Amsterdam"), keep_ticking=True
    ) as p:
        assert (Instant.now() - i).total("seconds") < 1
        p.shift(hours(2))
        sleep(0.000001)
        assert 2 < (Instant.now() - i).total("hours") < 2.1
        p.move_to(Instant.now().to_tz("Europe/Amsterdam").add(days=2))
        sleep(0.000001)
        assert 50 < (Instant.now() - i).total("hours") < 50.1

    assert Instant.now() - i > TimeDelta(hours=40_000)


def test_time_patch_lifetime_and_overlap():
    i = Instant.from_utc(1980, 3, 2, hour=2)
    with patch_current_time(i, keep_ticking=False) as handle:
        with pytest.raises(RuntimeError, match="already active"):
            with patch_current_time(i, keep_ticking=False):
                pass

    with pytest.raises(RuntimeError, match="no longer active"):
        handle.shift(hours(1))
    with pytest.raises(RuntimeError, match="no longer active"):
        handle.move_to(i)


def test_time_patch_rejects_invalid_shift_arguments():
    i = Instant.from_utc(1980, 3, 2, hour=2)
    with patch_current_time(i, keep_ticking=False) as handle:
        with pytest.raises(TypeError, match="must be a TimeDelta"):
            handle.shift(ItemizedDelta(days=1))  # type: ignore[arg-type]
        with pytest.raises(TypeError, match="unexpected keyword"):
            handle.shift(years=1)
        with pytest.raises(TypeError, match="[Cc]annot mix"):
            handle.shift(hours(1), minutes=1)


def test_patch_current_time_decorator_does_not_inject_handle():
    i = Instant.from_utc(1980, 3, 2, hour=2)

    @patch_current_time(i, keep_ticking=False)
    def decorated() -> Instant:
        return Instant.now()

    assert decorated() == i


def test_system_tz_sentinel():
    assert repr(SYSTEM_TZ) == "SYSTEM_TZ"
    assert copy(SYSTEM_TZ) is SYSTEM_TZ
    assert deepcopy(SYSTEM_TZ) is SYSTEM_TZ
    payload = pickle.dumps(SYSTEM_TZ)
    assert b"whenever._" not in payload
    assert b"whenever" in payload
    assert b"SYSTEM_TZ" in payload
    assert pickle.loads(payload) is SYSTEM_TZ


def test_get_tzpath_returns_snapshot(tmp_path):
    previous = get_tzpath()
    try:
        reset_tzpath([tmp_path])
        assert get_tzpath() == (str(tmp_path),)
        assert previous != get_tzpath()
    finally:
        reset_tzpath(previous)


def test_get_system_tz():

    tz_type, tz_value = get_tz()
    assert tz_type in (0, 1, 2)
    assert isinstance(tz_value, str)


@system_tz_ams()
def test_reset_system_tz():
    plain = PlainDateTime(2020, 1, 1)
    d1 = plain.assume_system_tz()
    assert d1.tz_id == "Europe/Amsterdam"

    with patch.dict(os.environ, {"TZ": "America/New_York"}):
        # The system timezone is now set to America/New_York
        # ...but the cache isn't updated until we call reset_system_tz()
        assert plain.assume_system_tz().tz_id == "Europe/Amsterdam"

        reset_system_tz()
        d2 = plain.assume_system_tz()
        assert d2.tz_id == "America/New_York"

        # old instances should not change
        assert d1.tz_id == "Europe/Amsterdam"

    # Cache not yet updated again...
    assert plain.assume_system_tz().tz_id == "America/New_York"

    reset_system_tz()
    assert plain.assume_system_tz().tz_id == "Europe/Amsterdam"


@pytest.mark.parametrize(
    "path, expect",
    [
        ("/usr/share/foo", None),
        ("", None),
        ("/etc/timezone", None),
        ("/usr/share/zoneinfo/Europe/Amsterdam", "Europe/Amsterdam"),
        ("/usr/share/zoneinfo.default/America/New_York", "America/New_York"),
        ("/usr/share/zoneinfo.default/", ""),
        ("/usr/share/zoneinfo/zoneinfo.default/UTC", "UTC"),
        ("/usr/share/zoneinfo", None),
    ],
)
def test_tzid_from_path(path, expect):
    assert _tzid_from_path(path) == expect
