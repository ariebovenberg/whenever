import warnings
from collections.abc import Callable
from typing import Any

import pytest
import whenever
from whenever import (
    SYSTEM_TZ,
    Date,
    Instant,
    ItemizedDateDelta,
    ItemizedDelta,
    MonthDay,
    OffsetDateTime,
    PlainDateTime,
    WheneverDeprecationWarning,
    ZonedDateTime,
    get_tzpath,
    hours,
    patch_current_time,
)

from .common import system_tz_ams


def deprecated(call: Callable[[], Any], /, *, match: str) -> Any:
    with pytest.warns(WheneverDeprecationWarning, match=match) as caught:
        result = call()
    assert len(caught) == 1
    assert caught[0].filename == __file__
    return result


@pytest.mark.parametrize(
    "old, new",
    [
        (
            lambda: ZonedDateTime(2020, 8, 15, tz="UTC", disambiguate="raise"),
            lambda: ZonedDateTime(
                2020, 8, 15, tz="UTC", disambiguation="raise"
            ),
        ),
        (
            lambda: ZonedDateTime.parse_iso(
                "2020-08-15T00:00:00+00:00[UTC]",
                disambiguate="raise",
            ),
            lambda: ZonedDateTime.parse_iso(
                "2020-08-15T00:00:00+00:00[UTC]",
                disambiguation="raise",
            ),
        ),
        (
            lambda: ZonedDateTime(2020, 8, 15, tz="UTC").add(
                hours=1, disambiguate="raise"
            ),
            lambda: ZonedDateTime(2020, 8, 15, tz="UTC").add(
                hours=1, disambiguation="raise"
            ),
        ),
        (
            lambda: PlainDateTime(2020, 8, 15).assume_tz(
                "UTC", disambiguate="raise"
            ),
            lambda: PlainDateTime(2020, 8, 15).assume_tz(
                "UTC", disambiguation="raise"
            ),
        ),
    ],
)
def test_disambiguate_keyword(old, new):
    assert deprecated(old, match="'disambiguate' is deprecated").strict_eq(
        new()
    )


def test_both_disambiguation_keywords_rejected():
    with pytest.raises(TypeError, match="received both 'disambiguation'"):
        ZonedDateTime(
            2020,
            8,
            15,
            tz="UTC",
            disambiguation="raise",
            disambiguate="raise",
        )


def test_parse_format_keyword():
    actual = deprecated(
        lambda: Date.parse("2020-08-15", format="YYYY-MM-DD"),
        match="'format' is deprecated",
    )
    assert actual == Date.parse("2020-08-15", pattern="YYYY-MM-DD")


def test_both_parse_pattern_keywords_rejected():
    with pytest.raises(TypeError, match="received both 'pattern'"):
        Date.parse(
            "2020-08-15",
            pattern="YYYY-MM-DD",
            format="YYYY-MM-DD",
        )


def test_format_iso_tz_keyword():
    dt = ZonedDateTime(2020, 8, 15, tz="UTC")
    actual = deprecated(
        lambda: dt.format_iso(tz="never"), match="'tz' is deprecated"
    )
    assert actual == dt.format_iso(tz_display="never")


def test_format_iso_always_value():
    dt = ZonedDateTime(2020, 8, 15, tz="UTC")
    actual = deprecated(
        lambda: dt.format_iso(tz_display="always"),
        match="tz_display='always' is deprecated",
    )
    assert actual == dt.format_iso(tz_display="required")


@pytest.mark.parametrize(
    "method, unit",
    [
        ("timestamp_millis", "millisecond"),
        ("timestamp_nanos", "nanosecond"),
    ],
)
def test_timestamp_method_wrappers(method, unit):
    instant = Instant.from_utc(2020, 8, 15, nanosecond=123_456_789)
    actual = deprecated(
        lambda: getattr(instant, method)(),
        match=rf"{method}\(\) is deprecated",
    )
    assert actual == instant.timestamp(unit=unit)


@pytest.mark.parametrize(
    "method, value, unit",
    [
        ("from_timestamp_millis", 1_234, "millisecond"),
        ("from_timestamp_nanos", 1_234, "nanosecond"),
    ],
)
def test_instant_timestamp_factory_wrappers(method, value, unit):
    actual = deprecated(
        lambda: getattr(Instant, method)(value),
        match=rf"{method}\(\) is deprecated",
    )
    assert actual == Instant.from_timestamp(value, unit=unit)


@pytest.mark.parametrize(
    "method", ["from_timestamp_millis", "from_timestamp_nanos"]
)
def test_instant_timestamp_factory_wrappers_keep_integer_requirement(method):
    with pytest.warns(WheneverDeprecationWarning) as caught:
        with pytest.raises(TypeError, match="requires an integer"):
            getattr(Instant, method)(1.5)
    assert caught[0].filename == __file__


@pytest.mark.parametrize(
    "method, value, unit",
    [
        ("from_timestamp", 1.25, "second"),
        ("from_timestamp_millis", 1_250, "millisecond"),
        ("from_timestamp_nanos", 1_250_000_000, "nanosecond"),
    ],
)
def test_offset_timestamp_factory_wrappers(method, value, unit):
    actual = deprecated(
        lambda: getattr(OffsetDateTime, method)(
            value, offset=hours(2), stale_offset_ok=True
        ),
        match=rf"OffsetDateTime\.{method}\(\) is deprecated",
    )
    expected = Instant.from_timestamp(value, unit=unit).to_fixed_offset(
        hours(2)
    )
    assert actual.strict_eq(expected)


@pytest.mark.parametrize(
    "method, value, unit",
    [
        ("from_timestamp", 1.25, "second"),
        ("from_timestamp_millis", 1_250, "millisecond"),
        ("from_timestamp_nanos", 1_250_000_000, "nanosecond"),
    ],
)
def test_zoned_timestamp_factory_wrappers(method, value, unit):
    actual = deprecated(
        lambda: getattr(ZonedDateTime, method)(value, tz="Europe/Amsterdam"),
        match=rf"ZonedDateTime\.{method}\(\) is deprecated",
    )
    expected = Instant.from_timestamp(value, unit=unit).to_tz(
        "Europe/Amsterdam"
    )
    assert actual.strict_eq(expected)


@pytest.mark.parametrize(
    "value",
    [
        Instant.from_utc(2020, 8, 15),
        OffsetDateTime(2020, 8, 15, offset=hours(2)),
        ZonedDateTime(2020, 8, 15, tz="UTC"),
        ItemizedDelta(days=1, hours=2),
        ItemizedDateDelta(days=1),
    ],
)
def test_exact_eq_wrapper(value):
    assert deprecated(
        lambda: value.exact_eq(value), match=r"exact_eq\(\) is deprecated"
    ) == value.strict_eq(value)


@system_tz_ams()
def test_system_timezone_wrappers():
    instant = Instant.from_utc(2020, 8, 15)
    assert deprecated(
        instant.to_system_tz, match=r"to_system_tz\(\) is deprecated"
    ).strict_eq(instant.to_tz(SYSTEM_TZ))

    actual = deprecated(
        lambda: ZonedDateTime.from_system_tz(
            2020, 8, 15, disambiguate="raise"
        ),
        match=r"from_system_tz\(\) is deprecated",
    )
    assert actual.strict_eq(
        ZonedDateTime(2020, 8, 15, tz=SYSTEM_TZ, disambiguation="raise")
    )

    plain = PlainDateTime(2020, 8, 15)
    actual = deprecated(
        lambda: plain.assume_system_tz(disambiguate="raise"),
        match=r"assume_system_tz\(\) is deprecated",
    )
    assert actual.strict_eq(plain.assume_tz(SYSTEM_TZ, disambiguation="raise"))

    with patch_current_time(instant, keep_ticking=False):
        actual = deprecated(
            ZonedDateTime.now_in_system_tz,
            match=r"now_in_system_tz\(\) is deprecated",
        )
        assert actual.strict_eq(ZonedDateTime.now(SYSTEM_TZ))


def test_zoned_tz_property():
    dt = ZonedDateTime(2020, 8, 15, tz="Europe/Amsterdam")
    assert deprecated(lambda: dt.tz, match="tz is deprecated") == dt.tz_id


def test_month_day_is_leap():
    month_day = MonthDay(2, 29)
    assert (
        deprecated(month_day.is_leap, match=r"is_leap\(\) is deprecated")
        == month_day.is_leap_day()
    )


def test_tzpath():
    assert (
        deprecated(lambda: whenever.TZPATH, match="TZPATH is deprecated")
        == get_tzpath()
    )


@pytest.mark.parametrize(
    "old, new",
    [
        (
            lambda: OffsetDateTime(2020, 8, 15, offset=2),
            lambda: OffsetDateTime(2020, 8, 15, offset=hours(2)),
        ),
        (
            lambda: OffsetDateTime(2020, 8, 15, offset=hours(1)).replace(
                offset=2, stale_offset_ok=True
            ),
            lambda: OffsetDateTime(2020, 8, 15, offset=hours(1)).replace(
                offset=hours(2), stale_offset_ok=True
            ),
        ),
        (
            lambda: Instant.from_utc(2020, 8, 15).to_fixed_offset(2),
            lambda: Instant.from_utc(2020, 8, 15).to_fixed_offset(hours(2)),
        ),
        (
            lambda: PlainDateTime(2020, 8, 15).assume_fixed_offset(2),
            lambda: PlainDateTime(2020, 8, 15).assume_fixed_offset(hours(2)),
        ),
    ],
)
def test_integer_offsets(old, new):
    actual = deprecated(old, match="integer offsets are deprecated")
    assert actual.strict_eq(new())


def test_integer_offset_to_now():
    instant = Instant.from_utc(2020, 8, 15)
    with patch_current_time(instant, keep_ticking=False):
        actual = deprecated(
            lambda: OffsetDateTime.now(2, stale_offset_ok=True),
            match="integer offsets are deprecated",
        )
        assert actual.strict_eq(
            OffsetDateTime.now(hours(2), stale_offset_ok=True)
        )


@pytest.mark.parametrize(
    "method, value",
    [
        ("from_timestamp", 1.25),
        ("from_timestamp_millis", 1_250),
        ("from_timestamp_nanos", 1_250_000_000),
    ],
)
def test_integer_offset_to_deprecated_timestamp_factories(method, value):
    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter("always")
        getattr(OffsetDateTime, method)(value, offset=2, stale_offset_ok=True)
    deprecations = [
        warning
        for warning in caught
        if warning.category is WheneverDeprecationWarning
    ]
    assert len(deprecations) == 2
    assert all(warning.filename == __file__ for warning in deprecations)
    assert any(
        "integer offsets are deprecated" in str(w.message)
        for w in deprecations
    )
