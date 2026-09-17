"""The warning hierarchy, and that every warning names the caller's line."""

import warnings

import pytest
from whenever import (
    CalendarUnitCompositionWarning,
    Date,
    DaysAssumed24HoursWarning,
    ImplicitDisambiguationWarning,
    Instant,
    InvalidOffsetError,
    ItemizedDateDelta,
    ItemizedDelta,
    NaiveArithmeticWarning,
    OffsetDateTime,
    PickleOffsetMismatchWarning,
    PlainDateTime,
    PotentialDstBugWarning,
    RepeatedTime,
    SkippedTime,
    StaleOffsetWarning,
    Time,
    TimeDelta,
    TimeZoneNotFoundError,
    WheneverDeprecationWarning,
    WheneverWarning,
    ZonedDateTime,
    hours,
    patch_current_time,
)

from .common import warns_here

_PLAIN = PlainDateTime(2021, 1, 31)
# One day later is 02:30 on the morning Amsterdam skips 02:00-03:00.
_BEFORE_SKIPPED = ZonedDateTime(2023, 3, 25, 2, 30, tz="Europe/Amsterdam")


def test_hierarchy():
    assert issubclass(WheneverWarning, UserWarning)
    assert issubclass(PotentialDstBugWarning, WheneverWarning)
    assert issubclass(PickleOffsetMismatchWarning, WheneverWarning)
    assert issubclass(CalendarUnitCompositionWarning, WheneverWarning)
    assert issubclass(WheneverDeprecationWarning, WheneverWarning)
    assert not issubclass(WheneverDeprecationWarning, DeprecationWarning)
    assert issubclass(DaysAssumed24HoursWarning, PotentialDstBugWarning)
    assert issubclass(StaleOffsetWarning, PotentialDstBugWarning)
    assert issubclass(NaiveArithmeticWarning, PotentialDstBugWarning)
    assert issubclass(ImplicitDisambiguationWarning, PotentialDstBugWarning)
    assert issubclass(RepeatedTime, ValueError)
    assert issubclass(SkippedTime, ValueError)
    assert issubclass(InvalidOffsetError, ValueError)
    assert issubclass(TimeZoneNotFoundError, ValueError)


def test_deprecation_warning_is_shown_by_default():
    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter("default")
        Date.today_in_system_tz()  # type: ignore[deprecated]
    assert len(caught) == 1
    assert caught[0].category is WheneverDeprecationWarning


def test_naive_arithmetic_warning_names_its_escape():
    with warns_here(NaiveArithmeticWarning) as caught:
        PlainDateTime(2024, 1, 1).add(hours=1)
    assert (
        "pass `naive_arithmetic_ok=True` to `add()`, `subtract()`, "
        "`difference()`, `since()`, or `until()`; `+` and `-` take no keyword"
        in str(caught[0].message)
    )
    with warns_here(NaiveArithmeticWarning) as caught:
        PlainDateTime(2024, 1, 1).since(
            PlainDateTime(2023, 1, 1), total="hours"
        )
    assert "`since()`, or `until()`; `+` and `-` take no keyword" in str(
        caught[0].message
    )


def test_time_patch_shift_points_at_the_caller():
    i = Instant.from_utc(2024, 1, 1)
    with patch_current_time(i, keep_ticking=False) as p:
        with warns_here(DaysAssumed24HoursWarning):
            p.shift(days=1)
        assert Instant.now() == i.add(hours=24)
        with warns_here(DaysAssumed24HoursWarning):
            p.shift(weeks=1)
        assert Instant.now() == i.add(hours=24 * 8)
        with warnings.catch_warnings():
            warnings.simplefilter("error")
            p.shift(days=1, days_assumed_24h_ok=True)
            p.shift(hours(1))
        assert Instant.now() == i.add(hours=24 * 9 + 1)


@pytest.mark.parametrize(
    "call, category",
    [
        pytest.param(
            lambda: _PLAIN + ItemizedDelta(hours=1),
            NaiveArithmeticWarning,
            id="plain + itemized",
        ),
        pytest.param(
            lambda: ItemizedDelta(hours=1) + _PLAIN,
            NaiveArithmeticWarning,
            id="itemized + plain",
        ),
        pytest.param(
            lambda: _PLAIN - ItemizedDelta(hours=1),
            NaiveArithmeticWarning,
            id="plain - itemized",
        ),
        pytest.param(
            lambda: _PLAIN + hours(1),
            NaiveArithmeticWarning,
            id="plain + timedelta",
        ),
        pytest.param(
            lambda: hours(1) + _PLAIN,
            NaiveArithmeticWarning,
            id="timedelta + plain",
        ),
        pytest.param(
            lambda: _PLAIN - hours(1),
            NaiveArithmeticWarning,
            id="plain - timedelta",
        ),
        pytest.param(
            lambda: TimeDelta(days=1),
            DaysAssumed24HoursWarning,
            id="TimeDelta(days=)",
        ),
        pytest.param(
            lambda: hours(49).total("days"),
            DaysAssumed24HoursWarning,
            id="TimeDelta.total(days)",
        ),
        pytest.param(
            lambda: ItemizedDelta(days=1).total(
                "hours", relative_to=_BEFORE_SKIPPED
            ),
            ImplicitDisambiguationWarning,
            id="ItemizedDelta.total",
        ),
        pytest.param(
            lambda: ItemizedDelta(days=1).in_units(
                ["hours"], relative_to=_BEFORE_SKIPPED
            ),
            ImplicitDisambiguationWarning,
            id="ItemizedDelta.in_units",
        ),
        pytest.param(
            lambda: ItemizedDelta(days=1).add(
                hours=0, relative_to=_BEFORE_SKIPPED, in_units=["hours"]
            ),
            ImplicitDisambiguationWarning,
            id="ItemizedDelta.add",
        ),
        pytest.param(
            lambda: ItemizedDelta(days=1).subtract(
                hours=0, relative_to=_BEFORE_SKIPPED, in_units=["hours"]
            ),
            ImplicitDisambiguationWarning,
            id="ItemizedDelta.subtract",
        ),
        pytest.param(
            lambda: ItemizedDateDelta(days=1).add(
                ItemizedDelta(hours=0),
                relative_to=_BEFORE_SKIPPED,
                in_units=["hours"],
            ),
            ImplicitDisambiguationWarning,
            id="ItemizedDateDelta.add",
        ),
        pytest.param(
            lambda: ItemizedDateDelta(days=1).subtract(
                ItemizedDelta(hours=0),
                relative_to=_BEFORE_SKIPPED,
                in_units=["hours"],
            ),
            ImplicitDisambiguationWarning,
            id="ItemizedDateDelta.subtract",
        ),
    ],
)
def test_points_at_the_caller(call, category):
    """A library-internal call that warns attributes the warning to the
    line that called the library, not to a frame inside it."""
    with warns_here(category):
        call()


def test_12h_warning_points_at_the_caller():
    with warns_here(WheneverWarning) as caught:
        Time(14, 30).format("ii:mm")
    assert "specifier" in str(caught[0].message)
    with warns_here(WheneverWarning):
        Time.parse("02:30", pattern="ii:mm")


@pytest.mark.parametrize(
    "value",
    [
        Time(13),
        PlainDateTime(2024, 3, 15, 13),
        Instant.from_utc(2024, 3, 15, 13),
        OffsetDateTime(2024, 3, 15, 13, offset=hours(2)),
        ZonedDateTime(2024, 3, 15, 13, tz="Europe/Paris"),
    ],
    ids=lambda v: type(v).__name__,
)
def test_warnings_point_at_the_f_string(value):
    """A pattern warning raised through __format__ names the caller's
    line, as it does through format(). Date is absent because it has
    no deprecated or ambiguous specifier."""
    with warns_here(WheneverDeprecationWarning):
        f"{value:hh}"
    with warns_here(WheneverWarning):
        f"{value:ii}"
