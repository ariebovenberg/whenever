import warnings
from collections.abc import Callable
from typing import Any, get_args

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
    StaleOffsetWarning,
    Time,
    TimeZoneNotFoundError,
    WheneverDeprecationWarning,
    ZonedDateTime,
    get_tzpath,
    hours,
    milliseconds,
    patch_current_time,
)

from .common import (
    suppress,
    system_tz_ams,
    warns_here,
)


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
            lambda: ZonedDateTime(2020, 8, 15, tz="UTC", disambiguate="raise"),  # type: ignore[deprecated]
            lambda: ZonedDateTime(
                2020, 8, 15, tz="UTC", disambiguation="raise"
            ),
        ),
        (
            lambda: ZonedDateTime.parse_iso(  # type: ignore[deprecated]
                "2020-08-15T00:00:00+00:00[UTC]",
                disambiguate="raise",
            ),
            lambda: ZonedDateTime.parse_iso(
                "2020-08-15T00:00:00+00:00[UTC]",
                disambiguation="raise",
            ),
        ),
        (
            lambda: ZonedDateTime(2020, 8, 15, tz="UTC").add(  # type: ignore[deprecated]
                hours=1, disambiguate="raise"
            ),
            lambda: ZonedDateTime(2020, 8, 15, tz="UTC").add(
                hours=1, disambiguation="raise"
            ),
        ),
        (
            lambda: PlainDateTime(2020, 8, 15).assume_tz(  # type: ignore[deprecated]
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
        ZonedDateTime(  # type: ignore[call-overload]
            2020,
            8,
            15,
            tz="UTC",
            disambiguation="raise",
            disambiguate="raise",
        )


def test_disambiguate_not_accepted_by_iso_constructor():
    with pytest.raises(
        TypeError, match="unexpected keyword argument:? 'disambiguate'"
    ):
        ZonedDateTime(
            "2020-08-15T00:00:00+00:00[UTC]",
            disambiguate="raise",  # type: ignore[call-overload]
        )


@pytest.mark.parametrize(
    "cls, value, pattern",
    [
        (Date, "2020-08-15", "YYYY-MM-DD"),
        (Time, "14:30", "HH:mm"),
        (PlainDateTime, "2020-08-15 14:30", "YYYY-MM-DD HH:mm"),
        (Instant, "2020-08-15 14:30Z", "YYYY-MM-DD HH:mmXXX"),
        (
            OffsetDateTime,
            "2020-08-15 14:30+02:00",
            "YYYY-MM-DD HH:mmxxx",
        ),
        (
            ZonedDateTime,
            "2020-08-15 14:30+02:00[Europe/Amsterdam]",
            "YYYY-MM-DD HH:mmxxx'['VV']'",
        ),
    ],
)
def test_parse_format_keyword(cls, value, pattern):
    actual = deprecated(
        lambda: cls.parse(value, format=pattern),
        match="'format' is deprecated",
    )
    assert actual == cls.parse(value, pattern=pattern)


def test_both_parse_pattern_keywords_rejected():
    with pytest.raises(TypeError, match="received both 'pattern'"):
        Date.parse(
            "2020-08-15",
            pattern="YYYY-MM-DD",
            format="YYYY-MM-DD",
        )  # type: ignore[call-overload]


def test_format_iso_tz_keyword():
    dt = ZonedDateTime(2020, 8, 15, tz="UTC")
    actual = deprecated(
        lambda: dt.format_iso(tz="never"),  # type: ignore[deprecated]
        match="'tz' is deprecated",
    )
    assert actual == dt.format_iso(tz_id_display="never")


def test_format_iso_always_value():
    dt = ZonedDateTime(2020, 8, 15, tz="UTC")
    actual = deprecated(
        lambda: dt.format_iso(tz_id_display="always"),  # type: ignore[deprecated]
        match="tz_id_display='always' is deprecated",
    )
    assert actual == dt.format_iso(tz_id_display="required")


@pytest.mark.parametrize(
    "value",
    [
        Instant.from_utc(2020, 8, 15, nanosecond=123_456_789),
        OffsetDateTime(
            2020,
            8,
            15,
            nanosecond=123_456_789,
            offset=hours(2),
        ),
        ZonedDateTime(
            2020,
            8,
            15,
            nanosecond=123_456_789,
            tz="Europe/Amsterdam",
        ),
    ],
)
@pytest.mark.parametrize(
    "method, unit",
    [("timestamp_millis", "millisecond"), ("timestamp_nanos", "nanosecond")],
)
def test_timestamp_method_wrappers(value, method, unit):
    actual = deprecated(
        lambda: getattr(value, method)(),
        match=rf"{method}\(\) is deprecated",
    )
    assert actual == value.timestamp(unit=unit)


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
    with warns_here(WheneverDeprecationWarning) as caught:
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
    "method",
    ["from_timestamp", "from_timestamp_millis", "from_timestamp_nanos"],
)
def test_offset_timestamp_factory_wrappers_warn_about_stale_offset(method):
    with warns_here(WheneverDeprecationWarning):
        with warns_here(StaleOffsetWarning):
            getattr(OffsetDateTime, method)(0, offset=hours(5))


@pytest.mark.parametrize(
    "method",
    ["from_timestamp", "from_timestamp_millis", "from_timestamp_nanos"],
)
def test_offset_timestamp_factory_wrappers_take_stale_offset_ok(method):
    with warns_here(WheneverDeprecationWarning):
        with warnings.catch_warnings():
            warnings.simplefilter("error", StaleOffsetWarning)
            getattr(OffsetDateTime, method)(
                0, offset=hours(5), stale_offset_ok=True
            )


@pytest.mark.parametrize(
    "method", ["from_timestamp_millis", "from_timestamp_nanos"]
)
def test_offset_timestamp_factory_wrappers_keep_integer_requirement(method):
    with warns_here(WheneverDeprecationWarning) as caught:
        with pytest.raises(TypeError, match="requires an integer"):
            getattr(OffsetDateTime, method)(
                1.5,
                offset=hours(2),
                stale_offset_ok=True,
            )
    assert caught[0].filename == __file__


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
    with patch_current_time(instant, keep_ticking=False):
        assert deprecated(
            Date.today_in_system_tz,  # type: ignore[deprecated]
            match=r"today_in_system_tz\(\) is deprecated",
        ) == Date.today(SYSTEM_TZ)

    for v in (
        instant,
        instant.to_fixed_offset(hours(2)),
        instant.to_tz("UTC"),
    ):
        assert deprecated(
            v.to_system_tz,  # type: ignore[deprecated]
            match=r"to_system_tz\(\) is deprecated",
        ).strict_eq(v.to_tz(SYSTEM_TZ))

    # Both keyword spellings are accepted, so that a global rename of
    # `disambiguate=` to `disambiguation=` doesn't break these wrappers.
    from_system_tz_msg = r"from_system_tz\(\) is deprecated"
    resolved = ZonedDateTime(2020, 8, 15, tz=SYSTEM_TZ, disambiguation="raise")
    assert deprecated(
        lambda: ZonedDateTime.from_system_tz(  # type: ignore[deprecated]
            2020, 8, 15, disambiguation="raise"
        ),
        match=from_system_tz_msg,
    ).strict_eq(resolved)
    # The old keyword goes through the same shim as everywhere else, so it
    # adds its own warning on top of the method's.
    with warns_here(WheneverDeprecationWarning) as caught:
        actual = ZonedDateTime.from_system_tz(  # type: ignore[deprecated]
            2020, 8, 15, disambiguate="raise"
        )
    assert actual.strict_eq(resolved)
    assert {str(w.message) for w in caught} == {
        "from_system_tz() is deprecated; "
        "use ZonedDateTime(..., tz=SYSTEM_TZ) instead",
        "'disambiguate' is deprecated; use 'disambiguation' instead",
    }
    assert deprecated(
        lambda: ZonedDateTime.from_system_tz(2020, 8, 15),  # type: ignore[deprecated]
        match=from_system_tz_msg,
    ).strict_eq(
        ZonedDateTime(2020, 8, 15, tz=SYSTEM_TZ, disambiguation="compatible")
    )
    # The method warns before parsing its arguments, so the TypeError
    # arrives after the deprecation warning.
    with pytest.warns(WheneverDeprecationWarning, match=from_system_tz_msg):
        with pytest.raises(
            TypeError,
            match="both 'disambiguation' and deprecated 'disambiguate'",
        ):
            ZonedDateTime.from_system_tz(  # type: ignore[deprecated]
                2020, 8, 15, disambiguation="raise", disambiguate="raise"
            )

    plain = PlainDateTime(2020, 8, 15)
    assume_system_tz_msg = r"assume_system_tz\(\) is deprecated"
    assumed = plain.assume_tz(SYSTEM_TZ, disambiguation="raise")
    assert deprecated(
        lambda: plain.assume_system_tz(disambiguation="raise"),  # type: ignore[deprecated]
        match=assume_system_tz_msg,
    ).strict_eq(assumed)
    with warns_here(WheneverDeprecationWarning) as caught:
        actual = plain.assume_system_tz(disambiguate="raise")  # type: ignore[deprecated]
    assert actual.strict_eq(assumed)
    assert {str(w.message) for w in caught} == {
        "assume_system_tz() is deprecated; use assume_tz(SYSTEM_TZ) instead",
        "'disambiguate' is deprecated; use 'disambiguation' instead",
    }
    assert deprecated(
        plain.assume_system_tz,  # type: ignore[deprecated]
        match=assume_system_tz_msg,
    ).strict_eq(plain.assume_tz(SYSTEM_TZ, disambiguation="compatible"))
    with pytest.warns(WheneverDeprecationWarning, match=assume_system_tz_msg):
        with pytest.raises(
            TypeError,
            match="both 'disambiguation' and deprecated 'disambiguate'",
        ):
            plain.assume_system_tz(  # type: ignore[deprecated]
                disambiguation="raise", disambiguate="raise"
            )

    with patch_current_time(instant, keep_ticking=False):
        actual = deprecated(
            ZonedDateTime.now_in_system_tz,  # type: ignore[deprecated]
            match=r"now_in_system_tz\(\) is deprecated",
        )
        assert actual.strict_eq(ZonedDateTime.now(SYSTEM_TZ))


@system_tz_ams()
@pytest.mark.parametrize(
    "method",
    [
        ZonedDateTime.from_timestamp,  # type: ignore[deprecated]
        ZonedDateTime.from_timestamp_millis,  # type: ignore[deprecated]
        ZonedDateTime.from_timestamp_nanos,  # type: ignore[deprecated]
    ],
)
def test_deprecated_timestamp_factories_accept_system_tz(method):
    with pytest.warns(WheneverDeprecationWarning):
        assert method(0, tz=SYSTEM_TZ).tz_id == "Europe/Amsterdam"


def test_zoned_tz_property():
    dt = ZonedDateTime(2020, 8, 15, tz="Europe/Amsterdam")
    assert deprecated(lambda: dt.tz, match="tz is deprecated") == dt.tz_id  # type: ignore[deprecated]


def test_month_day_is_leap():
    month_day = MonthDay(2, 29)
    assert (
        deprecated(month_day.is_leap, match=r"is_leap\(\) is deprecated")  # type: ignore[deprecated]
        == month_day.is_leap_day()
    )


def test_disambiguate_str_alias():
    """``DisambiguateStr`` is a silent alias: no warning, same values."""
    from whenever import DisambiguateStr, DisambiguationStr

    def values(alias: Any) -> tuple[Any, ...]:
        # On Python 3.12+ these are `type` statements, whose values sit
        # behind `__value__`; before that they're plain `Literal`s.
        return get_args(getattr(alias, "__value__", alias))

    assert values(DisambiguateStr) == values(DisambiguationStr)


def test_tzpath():
    assert (
        deprecated(lambda: whenever.TZPATH, match="TZPATH is deprecated")
        == get_tzpath()
    )


@pytest.mark.parametrize(
    "old, new",
    [
        (
            lambda: OffsetDateTime(2020, 8, 15, offset=2),  # type: ignore[deprecated]
            lambda: OffsetDateTime(2020, 8, 15, offset=hours(2)),
        ),
        (
            lambda: OffsetDateTime(2020, 8, 15, offset=hours(1)).replace(  # type: ignore[deprecated]
                offset=2, stale_offset_ok=True
            ),
            lambda: OffsetDateTime(2020, 8, 15, offset=hours(1)).replace(
                offset=hours(2), stale_offset_ok=True
            ),
        ),
        (
            lambda: Instant.from_utc(2020, 8, 15).to_fixed_offset(2),  # type: ignore[deprecated]
            lambda: Instant.from_utc(2020, 8, 15).to_fixed_offset(hours(2)),
        ),
        (
            lambda: PlainDateTime(2020, 8, 15).assume_fixed_offset(2),  # type: ignore[deprecated]
            lambda: PlainDateTime(2020, 8, 15).assume_fixed_offset(hours(2)),
        ),
    ],
)
def test_integer_offsets(old, new):
    actual = deprecated(
        old,
        match=r"integer offsets are deprecated.*TimeDelta.*hours\(2\)",
    )
    assert actual.strict_eq(new())


def test_integer_offset_to_init():
    with warns_here(WheneverDeprecationWarning):
        d = OffsetDateTime(2020, 8, 15, 5, 12, 30, nanosecond=450, offset=-5)  # type: ignore[deprecated]
    assert d.offset == hours(-5)


def test_integer_offset_is_still_range_checked():
    with warns_here(WheneverDeprecationWarning):
        with pytest.raises(ValueError, match="offset.*24.*hours"):
            OffsetDateTime(2020, 8, 15, 5, 12, offset=34)  # type: ignore[deprecated]


def test_integer_offset_to_now():
    instant = Instant.from_utc(2020, 8, 15)
    with patch_current_time(instant, keep_ticking=False):
        actual = deprecated(
            lambda: OffsetDateTime.now(2, stale_offset_ok=True),  # type: ignore[deprecated]
            match=r"integer offsets are deprecated.*TimeDelta.*hours\(2\)",
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


@suppress(WheneverDeprecationWarning)
@system_tz_ams()
def test_from_system_tz_argument_parsing():
    d = ZonedDateTime.from_system_tz(  # type: ignore[deprecated]
        2020,
        8,
        15,
        23,
        12,
        9,
        nanosecond=987_654_321,
        disambiguation="later",
    )
    assert d.tz_id == "Europe/Amsterdam"
    assert d.offset == hours(2)
    assert d.strict_eq(
        ZonedDateTime(
            2020,
            8,
            15,
            23,
            12,
            9,
            nanosecond=987_654_321,
            tz="Europe/Amsterdam",
        )
    )

    # check variations of the call
    assert ZonedDateTime.from_system_tz(2020, 8, 15).strict_eq(  # type: ignore[deprecated]
        ZonedDateTime(2020, 8, 15, tz="Europe/Amsterdam")
    )

    with pytest.raises(TypeError):
        ZonedDateTime.from_system_tz(2020, 8, 15, tz="America/New_York")  # type: ignore[call-arg, deprecated]

    with pytest.raises(ValueError):
        ZonedDateTime.from_system_tz(2020, 8, 15, nanosecond=1_000_000_000)  # type: ignore[deprecated]


class TestZonedTimestampFactoryWrapperArguments:
    """The zoned timestamp factories parse their own arguments."""

    @suppress(WheneverDeprecationWarning)
    @pytest.mark.parametrize(
        "method, factor",
        [
            (ZonedDateTime.from_timestamp, 1),  # type: ignore[deprecated]
            (ZonedDateTime.from_timestamp_millis, 1_000),  # type: ignore[deprecated]
            (ZonedDateTime.from_timestamp_nanos, 1_000_000_000),  # type: ignore[deprecated]
        ],
    )
    def test_all(self, method, factor):
        assert method(0, tz="Iceland").strict_eq(
            ZonedDateTime(1970, 1, 1, tz="Iceland")
        )
        assert method(1_597_493_310 * factor, tz="America/Nuuk").strict_eq(
            ZonedDateTime(2020, 8, 15, 10, 8, 30, tz="America/Nuuk")
        )
        with pytest.raises((OSError, OverflowError, ValueError)):
            method(1_000_000_000_000_000_000 * factor, tz="America/Nuuk")

        with pytest.raises((OSError, OverflowError, ValueError)):
            method(-1_000_000_000_000_000_000 * factor, tz="America/Nuuk")

        with pytest.raises((TypeError, AttributeError)):
            method(0, tz=3)

        with pytest.raises(TypeError):
            method("0", tz="America/New_York")

        with pytest.raises(TimeZoneNotFoundError):
            method(0, tz="America/Nowhere")

        with pytest.raises(TypeError, match="got 3|foo"):
            method(0, tz="America/New_York", foo="bar")

        with pytest.raises(TypeError, match="positional|ts"):
            method(ts=0, tz="America/New_York")

        with pytest.raises(TypeError):
            method(0, foo="bar")

        with pytest.raises(TypeError):
            method(0)

        with pytest.raises(TypeError):
            method(0, "bar")

        assert ZonedDateTime.from_timestamp_millis(  # type: ignore[deprecated]
            -4, tz="America/Nuuk"
        ).to_instant() == Instant.from_timestamp(0) - milliseconds(4)

        assert ZonedDateTime.from_timestamp_nanos(  # type: ignore[deprecated]
            -4, tz="America/Nuuk"
        ).to_instant() == Instant.from_timestamp(0).subtract(nanoseconds=4)

    @suppress(WheneverDeprecationWarning)
    def test_nanos(self):
        assert ZonedDateTime.from_timestamp_nanos(  # type: ignore[deprecated]
            1_597_493_310_123_456_789, tz="America/Nuuk"
        ).strict_eq(
            ZonedDateTime(
                2020,
                8,
                15,
                10,
                8,
                30,
                nanosecond=123_456_789,
                tz="America/Nuuk",
            )
        )

    @suppress(WheneverDeprecationWarning)
    def test_millis(self):
        assert ZonedDateTime.from_timestamp_millis(  # type: ignore[deprecated]
            1_597_493_310_123, tz="America/Nuuk"
        ).strict_eq(
            ZonedDateTime(
                2020,
                8,
                15,
                10,
                8,
                30,
                nanosecond=123_000_000,
                tz="America/Nuuk",
            )
        )

    @suppress(WheneverDeprecationWarning)
    @pytest.mark.parametrize("value", [1.0, 1.000_000_001, -9.000_000_100])
    def test_float(self, value):
        assert ZonedDateTime.from_timestamp(  # type: ignore[deprecated]
            value,
            tz="America/New_York",
        ).strict_eq(Instant.from_timestamp(value).to_tz("America/New_York"))

    @suppress(WheneverDeprecationWarning)
    def test_float_out_of_range(self):
        with pytest.raises((ValueError, OverflowError)):
            ZonedDateTime.from_timestamp(9e200, tz="America/New_York")  # type: ignore[deprecated]

        with pytest.raises((ValueError, OverflowError, OSError)):
            ZonedDateTime.from_timestamp(  # type: ignore[deprecated]
                float(Instant.MAX.timestamp()) + 0.99999999,
                tz="America/New_York",
            )

        with pytest.raises((ValueError, OverflowError)):
            ZonedDateTime.from_timestamp(float("inf"), tz="America/New_York")  # type: ignore[deprecated]

        with pytest.raises((ValueError, OverflowError)):
            ZonedDateTime.from_timestamp(float("nan"), tz="America/New_York")  # type: ignore[deprecated]
