import json
import os
import pickle
import subprocess
import sys
import warnings
from collections.abc import Callable
from contextlib import nullcontext
from copy import copy, deepcopy
from time import sleep
from unittest.mock import patch

import pytest
from typing_extensions import assert_type
from whenever import (
    _EXTENSION_LOADED,
    SYSTEM_TZ,
    Date,
    Instant,
    IsoWeekDate,
    ItemizedDateDelta,
    ItemizedDelta,
    MonthDay,
    OffsetDateTime,
    PlainDateTime,
    Time,
    TimeDelta,
    TimePatch,
    YearMonth,
    ZonedDateTime,
    clear_tzcache,
    get_tzpath,
    hours,
    patch_current_time,
    reset_system_tz,
    reset_tzpath,
)
from whenever._tz.system import _tzid_from_path, get_tz

from .common import system_tz_ams, warns_here

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
    with warns_here(Warning):
        operation(dt, delta)


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


@pytest.mark.parametrize(
    "value, invalid_iso",
    [
        (Date(2020, 8, 15), "2020-13-15"),
        (YearMonth(2020, 8), "2020-13"),
        (MonthDay(8, 15), "--13-15"),
        (IsoWeekDate("2020-W33-6"), "2020-W54-1"),
        (Time(12, 30, 45), "25:30:45"),
        (PlainDateTime(2020, 8, 15, 12, 30), "2020-08-15T25:30"),
        (Instant("2020-08-15T12:30Z"), "2020-08-15T12:30"),
        (
            OffsetDateTime("2020-08-15T12:30+02:00"),
            "2020-08-15T12:30",
        ),
        (
            ZonedDateTime("2020-08-15T12:30+02:00[Europe/Amsterdam]"),
            "2020-08-15T12:30+03:00[Europe/Amsterdam]",
        ),
        (TimeDelta("PT2H30M"), "P1M"),
        (ItemizedDateDelta("P1Y2M"), "PT1H"),
        (ItemizedDelta("P1Y2MT3H"), "invalid"),
    ],
)
def test_pydantic(value, invalid_iso):
    pydantic = pytest.importorskip("pydantic")
    adapter = pydantic.TypeAdapter(type(value))
    serialized = json.dumps(str(value), separators=(",", ":"))

    assert adapter.validate_python(value) is value
    assert adapter.validate_python(str(value)) == value
    assert adapter.validate_json(serialized) == value
    assert adapter.dump_json(value) == serialized.encode()
    with pytest.raises(pydantic.ValidationError, match="cannot parse"):
        adapter.validate_python(42)
    with pytest.raises(pydantic.ValidationError):
        adapter.validate_python(invalid_iso)
    assert adapter.json_schema()["type"] == "string"


@system_tz_ams()
def test_patch_time():

    i = Instant.from_utc(1980, 3, 2, hour=2)

    # simplest case: freeze time at fixed UTC
    with patch_current_time(i, keep_ticking=False) as p:
        assert callable(p.shift)
        assert callable(p.move_to)
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
        assert i.to_fixed_offset(hours(1)).assume_tz(SYSTEM_TZ).tz_id == (
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


def test_ticking_time_patch_before_epoch():
    i = Instant.from_utc(1960, 3, 2, hour=2)
    with patch_current_time(i, keep_ticking=True):
        assert i <= Instant.now() < i.add(seconds=1)


def test_ticking_time_patch_allows_backward_movement():
    i = Instant.from_utc(1960, 3, 2, hour=2)
    with patch_current_time(i, keep_ticking=True) as p:
        for n in range(2_000):
            p.shift(seconds=-1 if n % 2 == 0 else 1)
        assert i <= Instant.now() < i.add(seconds=1)


def test_time_patch_shift_out_of_range():
    with patch_current_time(Instant.MAX, keep_ticking=False) as p:
        with pytest.raises(ValueError, match="out of range"):
            p.shift(seconds=1)


def test_time_patch_ticks_out_of_range():
    with patch_current_time(Instant.MAX, keep_ticking=True):
        with pytest.raises((OSError, ValueError)):
            sleep(1e-6)
            Instant.now()


@system_tz_ams()
@pytest.mark.parametrize(
    ("method", "value"),
    [
        (ZonedDateTime.from_timestamp, 0),
        (ZonedDateTime.from_timestamp_millis, 0),
        (ZonedDateTime.from_timestamp_nanos, 0),
    ],
)
def test_deprecated_timestamp_factories_accept_system_tz(method, value):
    assert method(value, tz=SYSTEM_TZ).tz_id == "Europe/Amsterdam"


def test_time_patch_is_not_constructable():
    with pytest.raises(TypeError, match="Protocols cannot be instantiated"):
        TimePatch()  # type: ignore[misc]


def test_time_patch_move_to_rejects_non_exact_time():
    i = Instant.from_utc(1980, 3, 2, hour=2)
    with patch_current_time(i, keep_ticking=False) as p:
        with pytest.raises(TypeError, match="exact time"):
            p.move_to(Date(2020, 8, 15))  # type: ignore[arg-type]


def test_time_patch_rejects_invalid_shift_arguments():
    i = Instant.from_utc(1980, 3, 2, hour=2)
    with patch_current_time(i, keep_ticking=False) as handle:
        with pytest.raises(TypeError, match="must be a TimeDelta"):
            handle.shift(ItemizedDelta(days=1))  # type: ignore[call-overload]
        with pytest.raises(TypeError, match="unexpected keyword"):
            handle.shift(years=1)  # type: ignore[call-overload]
        with pytest.raises(TypeError, match="[Cc]annot mix"):
            handle.shift(hours(1), minutes=1)  # type: ignore[call-overload]


def test_patch_current_time_decorator_does_not_inject_handle():
    i = Instant.from_utc(1980, 3, 2, hour=2)

    @patch_current_time(i, keep_ticking=False)
    def decorated(value: Instant, /) -> Instant:
        return Instant.now()

    assert_type(decorated, Callable[[Instant], Instant])
    assert_type(decorated(i), Instant)
    with pytest.raises(TypeError):
        decorated()  # type: ignore[call-arg]
    assert decorated(i) == i


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


class TestOutOfRangeIsValueError:
    """A result that falls outside the supported range must raise
    ``ValueError``, never a bare ``OverflowError`` from the stdlib.

    ``TimeZoneNotFoundError`` is a ``ValueError`` for the same reason: callers
    should be able to catch everything parsing and conversion can raise with a
    single ``except ValueError``.
    """

    KIRITIMATI = "Pacific/Kiritimati"  # UTC+14
    MIDWAY = "Pacific/Midway"  # UTC-11

    @pytest.mark.parametrize(
        "func",
        [
            # parsing
            lambda: ZonedDateTime.parse_iso(
                "9999-12-31T23:59:59Z[Pacific/Kiritimati]"
            ),
            lambda: ZonedDateTime("9999-12-31T23:59:59Z[Pacific/Kiritimati]"),
            lambda: ZonedDateTime.parse_iso(
                "9999-12-31T23:59:59+00:00[Pacific/Kiritimati]",
                offset_mismatch="keep_instant",
            ),
            lambda: ZonedDateTime.parse(
                "9999-12-31 23:59+00:00[Pacific/Kiritimati]",
                pattern="YYYY-MM-DD HH:mmxxx'['VV']'",
                offset_mismatch="keep_instant",
            ),
            # conversion
            lambda: Instant.MAX.to_tz("Pacific/Kiritimati"),
            lambda: Instant.MAX.to_fixed_offset(hours(14)),
            lambda: Instant.MIN.to_fixed_offset(hours(-14)),
            # arithmetic and derived values
            lambda: Instant.MAX.add(seconds=1),
            lambda: Instant.MAX.round(),
            lambda: Date.MAX.next_day(),
            lambda: Date.MIN.prev_day(),
            lambda: Date.MAX.add(days=1),
            lambda: ZonedDateTime(
                9999, 12, 31, tz="Europe/Amsterdam"
            ).day_length(),
            lambda: ZonedDateTime(9999, 12, 31, tz="UTC").add(days=1),
            lambda: ZonedDateTime(
                9999, 12, 31, 23, tz="Pacific/Midway"
            ).end_of("day"),
            lambda: ZonedDateTime(
                9999, 12, 31, 23, 59, tz="Europe/Amsterdam"
            ).round("hour", mode="ceil"),
        ],
    )
    def test_raises_value_error(self, func):
        with pytest.raises(ValueError):
            func()

    @pytest.mark.parametrize("bad", [3, None, b"UTC", 3.5, ["UTC"]])
    def test_non_string_tz_is_type_error(self, bad):
        # was a leaked AttributeError in the pure Python backend
        with pytest.raises(TypeError, match="tz must be a string"):
            ZonedDateTime(2020, 1, 1, tz=bad)
        with pytest.raises(TypeError, match="key must be a string"):
            clear_tzcache(only_keys=[bad])

    def test_oversized_int_is_still_overflow_error(self):
        # Distinct from the above: an *input* that doesn't fit a machine
        # integer is an OverflowError in both backends, and stays that way.
        with pytest.raises(OverflowError):
            Instant.from_timestamp(10**30)


# One pair per type that has ``strict_eq()``: ``a == b`` holds, while
# ``a.strict_eq(b)`` does not. A cross-type pair raises instead of returning
# ``False``, which is also a way of not holding.
EQUAL_BUT_NOT_STRICTLY_EQUAL = [
    (
        Instant.from_utc(2020, 8, 15, 10),
        OffsetDateTime(2020, 8, 15, 12, offset=hours(2)),
    ),
    (
        OffsetDateTime(2020, 8, 15, 12, offset=hours(2)),
        OffsetDateTime(2020, 8, 15, 13, offset=hours(3)),
    ),
    (
        ZonedDateTime(2020, 8, 15, 12, tz="Europe/Amsterdam"),
        ZonedDateTime(2020, 8, 15, 6, tz="America/New_York"),
    ),
    (
        ItemizedDelta(weeks=2, hours=3),
        ItemizedDelta(weeks=2, hours=3, months=0),
    ),
    (
        ItemizedDateDelta(weeks=2, days=3),
        ItemizedDateDelta(weeks=2, days=3, months=0),
    ),
]


@pytest.mark.parametrize("a, b", EQUAL_BUT_NOT_STRICTLY_EQUAL)
def test_strict_eq_refines_eq(a, b):
    # the law: strict_eq() implies ==
    assert a.strict_eq(a) and a == a
    assert b.strict_eq(b) and b == b
    # ...and never the converse
    assert a == b
    if type(a) is type(b):
        assert not a.strict_eq(b)
        assert not b.strict_eq(a)
    else:
        with pytest.raises(TypeError, match="same-type"):
            a.strict_eq(b)
