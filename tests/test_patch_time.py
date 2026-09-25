import warnings
from collections.abc import Callable
from time import sleep, time_ns

import pytest
from typing_extensions import assert_type
from whenever import (
    SYSTEM_TZ,
    Date,
    Instant,
    ItemizedDelta,
    PlainDateTime,
    TimeDelta,
    TimePatch,
    ZonedDateTime,
    hours,
    patch_current_time,
)

from .common import system_tz


@system_tz("Europe/Amsterdam")
def test_patch_time():

    i = Instant.from_utc(1980, 3, 2, hour=2)

    # simplest case: freeze time at fixed UTC
    with patch_current_time(i, keep_ticking=False) as p:
        assert callable(p.shift)
        assert callable(p.move_to)
        assert Instant.now() == i
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
    assert Date.today(SYSTEM_TZ) > Date(2024, 1, 1)

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


def test_ticking_time_patch_past_the_range():
    with patch_current_time(Instant.MAX, keep_ticking=True):
        # The clock must visibly advance: before Python 3.13, the Windows
        # clock ticks only every ~16ms, and zero elapsed time is in range.
        t = time_ns()
        while time_ns() == t:
            pass
        with pytest.raises(ValueError, match="out of range"):
            Instant.now()


def test_time_patch_shift_out_of_range():
    with patch_current_time(Instant.MAX, keep_ticking=False) as p:
        with pytest.raises(ValueError, match="out of range"):
            p.shift(seconds=1)


def test_time_patch_ticks_out_of_range():
    with patch_current_time(Instant.MAX, keep_ticking=True):
        sleep(1e-6)
        with pytest.raises(
            ValueError, match="^value or calculation out of range$"
        ):
            Instant.now()


def test_time_patch_is_not_constructable():
    with pytest.raises(TypeError, match="Protocols cannot be instantiated"):
        TimePatch()  # type: ignore[misc]


def test_time_patch_move_to_rejects_non_exact_time():
    i = Instant.from_utc(1980, 3, 2, hour=2)
    with patch_current_time(i, keep_ticking=False) as p:
        with pytest.raises(TypeError, match="must be an Instant"):
            p.move_to(Date(2020, 8, 15))  # type: ignore[arg-type]


def test_patch_current_time_rejects_non_exact_time():
    with pytest.raises(
        TypeError, match=r"patch_current_time\(\) argument must be an Instant"
    ):
        with patch_current_time(
            PlainDateTime(2020, 1, 1),  # type: ignore[arg-type]
            keep_ticking=False,
        ):
            pass  # pragma: no cover


def test_time_patch_rejects_invalid_shift_arguments():
    i = Instant.from_utc(1980, 3, 2, hour=2)
    with patch_current_time(i, keep_ticking=False) as handle:
        with pytest.raises(
            TypeError, match=r"^shift\(\) argument must be a TimeDelta$"
        ):
            handle.shift(ItemizedDelta(days=1))  # type: ignore[call-overload]
        with pytest.raises(TypeError, match="unexpected keyword"):
            handle.shift(years=1)  # type: ignore[call-overload]
        with pytest.raises(TypeError, match=r"^shift\(\) cannot mix"):
            handle.shift(hours(1), minutes=1)  # type: ignore[call-overload]
        with warnings.catch_warnings():
            warnings.simplefilter("error")
            with pytest.raises(TypeError, match="unexpected keyword"):
                handle.shift(days=1, foo=1)  # type: ignore[call-overload]


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
