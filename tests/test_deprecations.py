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
from whenever._format import compile_pattern

from .common import (
    AMS_TZ_POSIX,
    StrSubclass,
    create_zdt,
    suppress,
    system_tz,
    warns_here,
)


def deprecated(call: Callable[[], Any], /, *, match: str) -> Any:
    with warns_here(WheneverDeprecationWarning, match=match) as caught:
        result = call()
    assert len(caught) == 1
    return result


class TestDisambiguateKeyword:
    @pytest.mark.parametrize(
        "old, new",
        [
            (
                lambda: ZonedDateTime(
                    2020, 8, 15, tz="UTC", disambiguate="raise"
                ),  # type: ignore[deprecated]
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
                lambda: ZonedDateTime(2020, 8, 15, tz="UTC").subtract(  # type: ignore[deprecated]
                    hours=1, disambiguate="raise"
                ),
                lambda: ZonedDateTime(2020, 8, 15, tz="UTC").subtract(
                    hours=1, disambiguation="raise"
                ),
            ),
            (
                lambda: ZonedDateTime(2020, 8, 15, tz="UTC").add(  # type: ignore[deprecated]
                    ItemizedDelta(hours=1), disambiguate="raise"
                ),
                lambda: ZonedDateTime(2020, 8, 15, tz="UTC").add(
                    ItemizedDelta(hours=1), disambiguation="raise"
                ),
            ),
            (
                lambda: ZonedDateTime(2020, 8, 15, tz="UTC").subtract(  # type: ignore[call-overload]
                    hours(1), disambiguate="raise"
                ),
                lambda: ZonedDateTime(2020, 8, 15, tz="UTC").subtract(  # type: ignore[call-overload]
                    hours(1), disambiguation="raise"
                ),
            ),
            (
                lambda: ZonedDateTime(2020, 8, 15, tz="UTC").replace(  # type: ignore[deprecated]
                    hour=1, disambiguate="raise"
                ),
                lambda: ZonedDateTime(2020, 8, 15, tz="UTC").replace(
                    hour=1, disambiguation="raise"
                ),
            ),
            (
                lambda: ZonedDateTime(2020, 8, 15, tz="UTC").replace_date(  # type: ignore[deprecated]
                    Date(2020, 8, 16), disambiguate="raise"
                ),
                lambda: ZonedDateTime(2020, 8, 15, tz="UTC").replace_date(
                    Date(2020, 8, 16), disambiguation="raise"
                ),
            ),
            (
                lambda: ZonedDateTime(2020, 8, 15, tz="UTC").replace_time(  # type: ignore[deprecated]
                    Time(1), disambiguate="raise"
                ),
                lambda: ZonedDateTime(2020, 8, 15, tz="UTC").replace_time(
                    Time(1), disambiguation="raise"
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
    def test_replacement(self, old, new):
        assert deprecated(old, match="'disambiguate' is deprecated").strict_eq(
            new()
        )

    def test_parse_as_called_in_0_10(self):
        with warns_here(WheneverDeprecationWarning) as caught:
            d = ZonedDateTime.parse(  # type: ignore[deprecated]
                "2023-10-29 02:30[Europe/Amsterdam]",
                format="YYYY-MM-DD HH:mm'['VV']'",
                disambiguate="later",
            )
        assert d.strict_eq(
            ZonedDateTime(
                2023,
                10,
                29,
                2,
                30,
                tz="Europe/Amsterdam",
                disambiguation="later",
            )
        )
        assert sorted(str(w.message) for w in caught) == [
            "'disambiguate' is deprecated; use 'disambiguation' instead",
            "'format' is deprecated; use 'pattern' instead",
        ]

    def test_both_keywords_rejected(self):
        with pytest.raises(TypeError, match="received both 'disambiguation'"):
            ZonedDateTime(  # type: ignore[call-overload]
                2020,
                8,
                15,
                tz="UTC",
                disambiguation="raise",
                disambiguate="raise",
            )

    def test_not_accepted_by_iso_constructor(self):
        with pytest.raises(
            TypeError, match="unexpected keyword argument:? 'disambiguate'"
        ):
            ZonedDateTime(
                "2020-08-15T00:00:00+00:00[UTC]",
                disambiguate="raise",  # type: ignore[call-overload]
            )

    def test_str_alias(self):
        """``DisambiguateStr`` is a silent alias: no warning, same values."""
        from whenever import DisambiguateStr, DisambiguationStr

        def values(alias: Any) -> tuple[Any, ...]:
            # On Python 3.12+ these are `type` statements, whose values sit
            # behind `__value__`; before that they're plain `Literal`s.
            return get_args(getattr(alias, "__value__", alias))

        assert values(DisambiguateStr) == values(DisambiguationStr)


class TestParseFormatKeyword:
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
    def test_replacement(self, cls, value, pattern):
        actual = deprecated(
            lambda: cls.parse(value, format=pattern),
            match="'format' is deprecated",
        )
        assert actual == cls.parse(value, pattern=pattern)

    def test_both_keywords_rejected(self):
        with pytest.raises(TypeError, match="received both 'pattern'"):
            Date.parse(
                "2020-08-15",
                pattern="YYYY-MM-DD",
                format="YYYY-MM-DD",
            )  # type: ignore[call-overload]


class TestFormatIsoTzIdDisplay:
    def test_tz_keyword(self):
        dt = ZonedDateTime(2020, 8, 15, tz="UTC")
        actual = deprecated(
            lambda: dt.format_iso(tz="omit"),  # type: ignore[deprecated]
            match="'tz' is deprecated",
        )
        assert actual == dt.format_iso(tz_id_display="omit")

    def test_tz_keyword_with_deprecated_value(self):
        """A deprecated keyword carrying a deprecated value warns once for each."""
        dt = ZonedDateTime(2020, 8, 15, tz="UTC")
        with warns_here(WheneverDeprecationWarning) as caught:
            actual = dt.format_iso(tz="never")  # type: ignore[deprecated]
        assert [str(w.message) for w in caught] == [
            "'tz' is deprecated; use 'tz_id_display' instead",
            "tz_id_display='never' is deprecated; use 'omit' instead",
        ]
        assert all(w.filename == __file__ for w in caught)
        assert actual == dt.format_iso(tz_id_display="omit")

    @pytest.mark.parametrize(
        "old, new",
        [
            ("always", "required"),
            ("auto", "if_available"),
            ("never", "omit"),
        ],
    )
    def test_deprecated_values(self, old, new):
        dt = ZonedDateTime(2020, 8, 15, tz="UTC")
        actual = deprecated(
            lambda: dt.format_iso(tz_id_display=old),
            match=f"tz_id_display='{old}' is deprecated; use '{new}' instead",
        )
        assert actual == dt.format_iso(tz_id_display=new)

    @pytest.mark.parametrize(
        "old, new",
        [
            ("always", "required"),
            ("auto", "if_available"),
            ("never", "omit"),
        ],
    )
    @pytest.mark.parametrize(
        "make",
        [
            pytest.param(lambda s: s, id="literal"),
            pytest.param(lambda s: "".join(s), id="dynamic"),
            pytest.param(StrSubclass, id="subclass"),
        ],
    )
    def test_deprecated_values_not_interned(self, old, new, make):
        dt = ZonedDateTime(2020, 8, 15, tz="UTC")
        actual = deprecated(
            lambda: dt.format_iso(tz_id_display=make(old)),
            match=f"tz_id_display='{old}' is deprecated",
        )
        assert actual == dt.format_iso(tz_id_display=make(new))


class TestRaisingCallEmitsNoWarning:
    """A call that raises emits no warning: a deprecated spelling or method
    is validated with the rest of the arguments, and warns only on success.
    """

    @pytest.mark.parametrize(
        "call, exc",
        [
            (
                lambda: ZonedDateTime(
                    2023, 6, 1, tz="Foo/Bar", disambiguate="raise"
                ),  # type: ignore[deprecated]
                TimeZoneNotFoundError,
            ),
            (
                lambda: ZonedDateTime(
                    2023, 13, 1, tz="Europe/Amsterdam", disambiguate="raise"
                ),  # type: ignore[deprecated]
                ValueError,
            ),
            (
                lambda: ZonedDateTime(2023, 6, 1, tz="UTC").replace(  # type: ignore[deprecated]
                    tz="Foo/Bar", disambiguate="raise"
                ),
                TimeZoneNotFoundError,
            ),
            (
                lambda: ZonedDateTime(2023, 6, 1, tz="UTC").replace(  # type: ignore[deprecated]
                    minute=99, disambiguate="raise"
                ),
                ValueError,
            ),
            (
                lambda: ZonedDateTime(2023, 6, 1, tz="UTC").replace_date(  # type: ignore[call-overload]
                    1, disambiguate="raise"
                ),
                (TypeError, AttributeError),
            ),
            (
                lambda: ZonedDateTime(2023, 6, 1, tz="UTC").replace_time(  # type: ignore[call-overload]
                    1, disambiguate="raise"
                ),
                (TypeError, AttributeError),
            ),
            (
                lambda: ZonedDateTime(2023, 6, 1, tz="UTC").add(  # type: ignore[call-overload]
                    hours=1, disambiguate="bogus"
                ),
                ValueError,
            ),
            (
                lambda: ZonedDateTime(2023, 6, 1, tz="UTC").subtract(  # type: ignore[deprecated]
                    years=99999, disambiguate="raise"
                ),
                ValueError,
            ),
            (
                lambda: ZonedDateTime.parse_iso(
                    "garbage", disambiguate="raise"
                ),  # type: ignore[deprecated]
                ValueError,
            ),
            (
                lambda: PlainDateTime(2023, 6, 1).assume_tz(  # type: ignore[deprecated]
                    "Foo/Bar", disambiguate="raise"
                ),
                TimeZoneNotFoundError,
            ),
            (
                lambda: PlainDateTime(2023, 6, 1).assume_system_tz(  # type: ignore[deprecated, call-arg]
                    disambiguate="bogus"
                ),
                ValueError,
            ),
            (
                lambda: ZonedDateTime.from_system_tz(2023, 13, 1),  # type: ignore[deprecated]
                ValueError,
            ),
            (
                lambda: ZonedDateTime.from_system_tz(2023, 1, 1, foo=1),  # type: ignore[call-overload]
                TypeError,
            ),
            (
                lambda: ZonedDateTime.from_system_tz(  # type: ignore[call-overload]
                    2023, 1, 1, disambiguation="raise", disambiguate="raise"
                ),
                TypeError,
            ),
            (
                lambda: Date.parse("garbage", format="YYYY-MM-DD"),  # type: ignore[deprecated]
                ValueError,
            ),
            (
                lambda: ZonedDateTime.parse(  # type: ignore[deprecated]
                    "2020-08-15 14:30+02:00[Foo/Bar]",
                    format="YYYY-MM-DD HH:mmxxx'['VV']'",
                ),
                TimeZoneNotFoundError,
            ),
            (
                lambda: ZonedDateTime(2020, 8, 15, tz="UTC").format_iso(  # type: ignore[call-overload]
                    tz="bogus"
                ),
                ValueError,
            ),
        ],
    )
    def test_deprecated_spelling(self, call, exc):
        with warnings.catch_warnings(record=True) as caught:
            warnings.simplefilter("always")
            with pytest.raises(exc):
                call()
        assert caught == []

    @pytest.mark.parametrize(
        "call",
        [
            lambda: OffsetDateTime.from_timestamp(  # type: ignore[deprecated]
                Instant.MAX.timestamp(), offset=hours(1)
            ),
            lambda: OffsetDateTime.from_timestamp(0, offset="x"),  # type: ignore[deprecated, arg-type]
            lambda: ZonedDateTime.from_timestamp(  # type: ignore[deprecated]
                Instant.MAX.timestamp(), tz="Asia/Tokyo"
            ),
            lambda: PlainDateTime(2020, 1, 1).assume_system_tz("raise"),  # type: ignore[deprecated, call-arg]
        ],
    )
    def test_deprecated_method(self, call: Callable[[], object]):
        with warnings.catch_warnings(record=True) as caught:
            warnings.simplefilter("always")
            with pytest.raises((ValueError, TypeError)):
                call()
        assert caught == []


class TestTimestampWrappers:
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
        [
            ("timestamp_millis", "millisecond"),
            ("timestamp_nanos", "nanosecond"),
        ],
    )
    def test_methods(self, value, method, unit):
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
    def test_instant_factories(self, method, value, unit):
        actual = deprecated(
            lambda: getattr(Instant, method)(value),
            match=rf"{method}\(\) is deprecated",
        )
        assert actual == Instant.from_timestamp(value, unit=unit)

    @pytest.mark.parametrize(
        "method, unit",
        [
            ("from_timestamp_millis", "millisecond"),
            ("from_timestamp_nanos", "nanosecond"),
        ],
    )
    def test_instant_factories_keep_integer_requirement(self, method, unit):
        with warns_here(WheneverDeprecationWarning) as caught:
            with pytest.raises(
                TypeError, match=f"^timestamp in {unit}s must be an integer$"
            ):
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
    def test_offset_factories(self, method, value, unit):
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
    def test_offset_factories_warn_about_stale_offset(self, method):
        with warns_here(WheneverDeprecationWarning):
            with warns_here(StaleOffsetWarning):
                getattr(OffsetDateTime, method)(0, offset=hours(5))

    @pytest.mark.parametrize(
        "method",
        ["from_timestamp", "from_timestamp_millis", "from_timestamp_nanos"],
    )
    def test_offset_factories_take_stale_offset_ok(self, method):
        with warns_here(WheneverDeprecationWarning):
            with warnings.catch_warnings():
                warnings.simplefilter("error", StaleOffsetWarning)
                getattr(OffsetDateTime, method)(
                    0, offset=hours(5), stale_offset_ok=True
                )

    def test_offset_factory_local_out_of_range(self):
        with pytest.raises(
            ValueError, match="value or calculation out of range"
        ):
            OffsetDateTime.from_timestamp(  # type: ignore[deprecated]
                Instant.MAX.timestamp(), offset=hours(1)
            )
        with pytest.raises(
            ValueError, match="value or calculation out of range"
        ):
            ZonedDateTime.from_timestamp(  # type: ignore[deprecated]
                Instant.MAX.timestamp(), tz="Asia/Tokyo"
            )

    @pytest.mark.parametrize(
        "method, unit",
        [
            ("from_timestamp_millis", "millisecond"),
            ("from_timestamp_nanos", "nanosecond"),
        ],
    )
    def test_offset_factories_keep_integer_requirement(self, method, unit):
        with pytest.raises(
            TypeError, match=f"^timestamp in {unit}s must be an integer$"
        ):
            getattr(OffsetDateTime, method)(
                1.5,
                offset=hours(2),
                stale_offset_ok=True,
            )

    @pytest.mark.parametrize(
        "method, value, unit",
        [
            ("from_timestamp", 1.25, "second"),
            ("from_timestamp_millis", 1_250, "millisecond"),
            ("from_timestamp_nanos", 1_250_000_000, "nanosecond"),
        ],
    )
    def test_zoned_factories(self, method, value, unit):
        actual = deprecated(
            lambda: getattr(ZonedDateTime, method)(
                value, tz="Europe/Amsterdam"
            ),
            match=rf"ZonedDateTime\.{method}\(\) is deprecated",
        )
        expected = Instant.from_timestamp(value, unit=unit).to_tz(
            "Europe/Amsterdam"
        )
        assert actual.strict_eq(expected)

    @system_tz("Europe/Amsterdam")
    @pytest.mark.parametrize(
        "method",
        [
            ZonedDateTime.from_timestamp,  # type: ignore[deprecated]
            ZonedDateTime.from_timestamp_millis,  # type: ignore[deprecated]
            ZonedDateTime.from_timestamp_nanos,  # type: ignore[deprecated]
        ],
    )
    def test_zoned_factories_accept_system_tz(self, method):
        with warns_here(WheneverDeprecationWarning):
            assert method(0, tz=SYSTEM_TZ).tz_id == "Europe/Amsterdam"


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
        with pytest.raises(ValueError, match="out of range"):
            method(1_000_000_000_000_000_000 * factor, tz="America/Nuuk")

        with pytest.raises(ValueError, match="out of range"):
            method(-1_000_000_000_000_000_000 * factor, tz="America/Nuuk")

        with pytest.raises(
            TypeError, match="^tz must be a string or SYSTEM_TZ$"
        ):
            method(0, tz=3)

        with pytest.raises(TypeError):
            method("0", tz="America/New_York")

        with pytest.raises(TimeZoneNotFoundError):
            method(0, tz="America/Nowhere")

        with pytest.raises(
            TypeError, match="unexpected keyword argument 'foo'"
        ):
            method(0, tz="America/New_York", foo="bar")

        with pytest.raises(
            TypeError, match="unexpected keyword argument 'ts'"
        ):
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
        with pytest.raises(ValueError):
            ZonedDateTime.from_timestamp(9e200, tz="America/New_York")  # type: ignore[deprecated]

        with pytest.raises(ValueError, match="out of range"):
            ZonedDateTime.from_timestamp(  # type: ignore[deprecated]
                float(Instant.MAX.timestamp()) + 0.99999999,
                tz="America/New_York",
            )

        with pytest.raises(ValueError):
            ZonedDateTime.from_timestamp(float("inf"), tz="America/New_York")  # type: ignore[deprecated]

        with pytest.raises(ValueError):
            ZonedDateTime.from_timestamp(float("nan"), tz="America/New_York")  # type: ignore[deprecated]


class TestSystemTzWrappers:
    @system_tz("Europe/Amsterdam")
    def test_replacements(self):
        instant = Instant.from_utc(2020, 8, 15)
        with patch_current_time(instant, keep_ticking=False):
            assert deprecated(
                Date.today_in_system_tz,  # type: ignore[deprecated]
                match=r"today_in_system_tz\(\) is deprecated",
            ) == Date.today(SYSTEM_TZ)

        # Both keyword spellings are accepted, so that a global rename of
        # `disambiguate=` to `disambiguation=` doesn't break these wrappers.
        from_system_tz_msg = r"from_system_tz\(\) is deprecated"
        resolved = ZonedDateTime(
            2020, 8, 15, tz=SYSTEM_TZ, disambiguation="raise"
        )
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
            ZonedDateTime(
                2020, 8, 15, tz=SYSTEM_TZ, disambiguation="compatible"
            )
        )
        # The arguments are validated before the method warns, so a call that
        # raises emits no warning.
        with warnings.catch_warnings(record=True) as caught:
            warnings.simplefilter("always")
            with pytest.raises(
                TypeError,
                match="both 'disambiguation' and deprecated 'disambiguate'",
            ):
                ZonedDateTime.from_system_tz(  # type: ignore[call-overload]
                    2020, 8, 15, disambiguation="raise", disambiguate="raise"
                )
        assert caught == []

        plain = PlainDateTime(2020, 8, 15)
        assume_system_tz_msg = r"assume_system_tz\(\) is deprecated"
        assumed = plain.assume_tz(SYSTEM_TZ, disambiguation="raise")
        assert deprecated(
            lambda: plain.assume_system_tz(disambiguation="raise"),  # type: ignore[deprecated]
            match=assume_system_tz_msg,
        ).strict_eq(assumed)
        with warns_here(WheneverDeprecationWarning) as caught:
            actual = plain.assume_system_tz(disambiguate="raise")  # type: ignore[deprecated, call-arg]
        assert actual.strict_eq(assumed)
        assert {str(w.message) for w in caught} == {
            "assume_system_tz() is deprecated; use assume_tz(SYSTEM_TZ) instead",
            "'disambiguate' is deprecated; use 'disambiguation' instead",
        }
        assert deprecated(
            plain.assume_system_tz,  # type: ignore[deprecated]
            match=assume_system_tz_msg,
        ).strict_eq(plain.assume_tz(SYSTEM_TZ, disambiguation="compatible"))
        # The arguments are validated before the method warns, so a call that
        # raises emits no warning.
        with warnings.catch_warnings(record=True) as caught:
            warnings.simplefilter("always")
            with pytest.raises(
                TypeError,
                match="both 'disambiguation' and deprecated 'disambiguate'",
            ):
                plain.assume_system_tz(  # type: ignore[deprecated, call-arg]
                    disambiguation="raise", disambiguate="raise"
                )
        assert caught == []

        with patch_current_time(instant, keep_ticking=False):
            actual = deprecated(
                ZonedDateTime.now_in_system_tz,  # type: ignore[deprecated]
                match=r"now_in_system_tz\(\) is deprecated",
            )
            assert actual.strict_eq(ZonedDateTime.now(SYSTEM_TZ))

    @system_tz("Europe/Amsterdam")
    @pytest.mark.parametrize(
        "v",
        [
            Instant.from_utc(2020, 8, 15),
            Instant.from_utc(2020, 8, 15).to_fixed_offset(hours(2)),
            Instant.from_utc(2020, 8, 15).to_tz("UTC"),
        ],
    )
    def test_to_system_tz(self, v):
        assert deprecated(
            v.to_system_tz,
            match=r"to_system_tz\(\) is deprecated",
        ).strict_eq(v.to_tz(SYSTEM_TZ))

    @suppress(WheneverDeprecationWarning)
    @system_tz("Europe/Amsterdam")
    def test_from_system_tz_argument_parsing(self):
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
            ZonedDateTime.from_system_tz(2020, 8, 15, tz="America/New_York")  # type: ignore[call-overload]

        with pytest.raises(ValueError):
            ZonedDateTime.from_system_tz(2020, 8, 15, nanosecond=1_000_000_000)  # type: ignore[deprecated]


class TestRenamedMembers:
    @pytest.mark.parametrize(
        "zdt",
        [
            ZonedDateTime(
                2023,
                10,
                29,
                2,
                15,
                tz="Europe/Amsterdam",
                disambiguation="earlier",
            ),
            ZonedDateTime(2020, 8, 15, 23, tz="Europe/London"),
        ],
    )
    def test_is_ambiguous(self, zdt: ZonedDateTime):
        assert (
            deprecated(
                zdt.is_ambiguous,  # type: ignore[deprecated]
                match=r"is_ambiguous\(\) is deprecated; use is_repeated\(\) instead",
            )
            == zdt.is_repeated()
        )

    def test_zoned_tz_property(self):
        dt = ZonedDateTime(2020, 8, 15, tz="Europe/Amsterdam")
        assert deprecated(lambda: dt.tz, match="tz is deprecated") == dt.tz_id  # type: ignore[deprecated]

        with system_tz(AMS_TZ_POSIX):
            no_id = ZonedDateTime(2020, 8, 15, tz=SYSTEM_TZ)
        assert no_id.tz_id is None
        assert deprecated(lambda: no_id.tz, match="tz is deprecated") is None  # type: ignore[deprecated]

    def test_month_day_is_leap(self):
        month_day = MonthDay(2, 29)
        assert (
            deprecated(month_day.is_leap, match=r"is_leap\(\) is deprecated")  # type: ignore[deprecated]
            == month_day.is_leap_day()
        )

    def test_tzpath(self):
        assert (
            deprecated(lambda: whenever.TZPATH, match="TZPATH is deprecated")
            == get_tzpath()
        )

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
    def test_exact_eq_wrapper(self, value):
        assert deprecated(
            lambda: value.exact_eq(value), match=r"exact_eq\(\) is deprecated"
        ) == value.strict_eq(value)


class TestIntegerOffsets:
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
                lambda: Instant.from_utc(2020, 8, 15).to_fixed_offset(
                    hours(2)
                ),
            ),
            (
                lambda: PlainDateTime(2020, 8, 15).assume_fixed_offset(2),  # type: ignore[deprecated]
                lambda: PlainDateTime(2020, 8, 15).assume_fixed_offset(
                    hours(2)
                ),
            ),
            # Rust implements to_fixed_offset() separately on each type
            (
                lambda: OffsetDateTime(
                    2020, 8, 15, offset=hours(1)
                ).to_fixed_offset(2),  # type: ignore[deprecated]
                lambda: OffsetDateTime(
                    2020, 8, 15, offset=hours(1)
                ).to_fixed_offset(hours(2)),
            ),
            (
                lambda: ZonedDateTime(
                    2020, 8, 15, tz="Europe/Paris"
                ).to_fixed_offset(2),  # type: ignore[deprecated]
                lambda: ZonedDateTime(
                    2020, 8, 15, tz="Europe/Paris"
                ).to_fixed_offset(hours(2)),
            ),
        ],
    )
    def test_replacement(self, old, new):
        actual = deprecated(
            old,
            match=r"integer offsets are deprecated.*TimeDelta.*hours\(2\)",
        )
        assert actual.strict_eq(new())

    def test_init(self):
        with warns_here(WheneverDeprecationWarning):
            d = OffsetDateTime(
                2020, 8, 15, 5, 12, 30, nanosecond=450, offset=-5
            )  # type: ignore[deprecated]
        assert d.offset == hours(-5)

    def test_still_range_checked(self):
        with warns_here(WheneverDeprecationWarning):
            with pytest.raises(
                ValueError, match="offset must be between -24 and 24 hours"
            ):
                OffsetDateTime(2020, 8, 15, 5, 12, offset=34)  # type: ignore[deprecated]

    def test_now(self):
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
    def test_deprecated_timestamp_factories(self, method, value):
        with warnings.catch_warnings(record=True) as caught:
            warnings.simplefilter("always")
            getattr(OffsetDateTime, method)(
                value, offset=2, stale_offset_ok=True
            )
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


class TestPatternDeprecations:
    @pytest.mark.parametrize(
        "pattern, replacement", [("h", "'H'"), ("hh", "'HH'")]
    )
    def test_legacy_hour_format(self, pattern, replacement):
        with warns_here(WheneverDeprecationWarning) as w:
            Time(13).format(pattern)
        assert len(w) == 1
        assert f"use {replacement} instead" in str(w[0].message)
        with warns_here(WheneverDeprecationWarning) as w:
            Time.parse("13", pattern=pattern)
        assert len(w) == 1
        assert f"use {replacement} instead" in str(w[0].message)

    @pytest.mark.parametrize(
        "pattern, s, replacement",
        [
            ("HH:mm:SS", "13:00", "'[:ss]'"),
            ("HH:mm:SS.fff", "13:00:05.123", "'[:ss.fff]'"),
            ("HH:mm:SS.FFF", "13:00", "'[:ss.FFF]'"),
        ],
    )
    def test_legacy_prefixed_optional_seconds(self, pattern, s, replacement):
        with warns_here(WheneverDeprecationWarning) as w:
            Time(13).format(pattern)
        assert len(w) == 1
        assert f"use {replacement} instead" in str(w[0].message)
        with warns_here(WheneverDeprecationWarning) as w:
            Time.parse(s, pattern=pattern)
        assert len(w) == 1
        assert f"use {replacement} instead" in str(w[0].message)

    @pytest.mark.parametrize(
        "pattern, s, replacement",
        [
            ("HH:mmSS", "13:00", "'[ss]'"),
            ("HH:mmSS.fff", "13:0005.123", "'[ss.fff]'"),
            ("HH:mmSS.FFF", "13:00", "'[ss.FFF]'"),
            ("HH:mmSS.'x'", "13:00.x", "'[ss]'"),
        ],
    )
    def test_legacy_separator_free_optional_seconds(
        self, pattern, s, replacement
    ):
        with warns_here(WheneverDeprecationWarning) as w:
            Time(13).format(pattern)
        assert len(w) == 1
        assert f"use {replacement} instead" in str(w[0].message)
        with warns_here(WheneverDeprecationWarning) as w:
            Time.parse(s, pattern=pattern)
        assert len(w) == 1
        assert f"use {replacement} instead" in str(w[0].message)

    @pytest.mark.parametrize(
        "t, pattern, expect",
        [
            (Time(14, 30), "HH:mmSS", "14:30"),
            (Time(14, 30, 5), "HH:mmSS", "14:3005"),
            (Time(14, 30, 5), "HH:mm.SS", "14:30.05"),
        ],
    )
    def test_legacy_optional_seconds_format(self, t, pattern, expect):
        with warns_here(WheneverDeprecationWarning):
            assert t.format(pattern) == expect

    @pytest.mark.parametrize(
        "s, pattern, expect",
        [
            ("14:30", "HH:mmSS", Time(14, 30)),
            ("14:3005", "HH:mmSS", Time(14, 30, 5)),
            ("14:3060", "HH:mmSS", Time(14, 30, 59)),
            ("14:30", "HH:mm:SS", Time(14, 30)),
            ("14:30:05", "HH:mm:SS", Time(14, 30, 5)),
            ("14:30:60", "HH:mm:SS", Time(14, 30, 59)),
            ("14:30", "HH:mmSSFFF", Time(14, 30)),
        ],
    )
    def test_legacy_optional_seconds_parse(self, s, pattern, expect):
        with warns_here(WheneverDeprecationWarning):
            assert Time.parse(s, pattern=pattern) == expect

    @pytest.mark.parametrize(
        "call",
        [
            lambda: Time.parse("x", pattern="hh"),
            lambda: Time.parse("x", pattern="ii"),
            lambda: Time.parse("12:00", pattern="HH:mm SS"),
            lambda: Instant.parse("12:00", pattern="hh:mm"),
            lambda: create_zdt(2020, 8, 15, tz=AMS_TZ_POSIX).format("VV hh"),
            lambda: f"{create_zdt(2020, 8, 15, tz=AMS_TZ_POSIX):VV ii}",
        ],
    )
    def test_no_warning_when_the_call_raises(self, call):
        """Validate, then warn: a call that raises warns about nothing."""
        with warnings.catch_warnings():
            warnings.simplefilter("error")
            with pytest.raises(ValueError):
                call()

    def test_cached_pattern_warns_at_each_call_site(self):
        compile_pattern.cache_clear()

        def first() -> None:
            Time(13).format("h")

        def second() -> None:
            Time(13).format("h")

        with warnings.catch_warnings(record=True) as w:
            warnings.simplefilter("always")
            first()
            second()
        assert len(w) == 2
        assert all(x.category is WheneverDeprecationWarning for x in w)
        assert all(x.filename == __file__ for x in w)
        assert w[0].lineno != w[1].lineno
