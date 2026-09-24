import warnings
from datetime import (
    date as py_date,
    datetime as py_datetime,
    time as py_time,
    timedelta as py_timedelta,
    timezone as py_timezone,
    tzinfo as py_tzinfo,
)
from zoneinfo import ZoneInfo

import pytest
from whenever import (
    Date,
    Instant,
    IsoWeekDate,
    ItemizedDelta,
    MonthDay,
    OffsetDateTime,
    PlainDateTime,
    Time,
    TimeDelta,
    Weekday,
    WheneverWarning,
    YearMonth,
    ZonedDateTime,
    hours,
    patch_current_time,
)

from .common import warns_here


class TestOutOfRangeIsValueError:
    """A result that falls outside the supported range raises ``ValueError``
    with the message ``value or calculation out of range``, never a bare
    ``OverflowError`` from the stdlib. Only an integer too large for the
    backend's machine integer may raise ``OverflowError`` instead, and the
    backends need not agree there (ADR 0002).

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
            # the instant is in range, its local time not
            lambda: (
                ZonedDateTime(9999, 12, 31, 20, tz="Asia/Tokyo")
                + TimeDelta(hours=5)
            ),
            lambda: ZonedDateTime(9999, 12, 31, 20, tz="Asia/Tokyo").add(
                hours=5
            ),
            lambda: (
                ZonedDateTime(9999, 12, 31, 20, tz="Asia/Tokyo")
                + ItemizedDelta(hours=5)
            ),
            lambda: ZonedDateTime(9999, 12, 31, 23, tz="Pacific/Apia").add(
                hours=1
            ),
            lambda: ZonedDateTime(1, 1, 1, tz="America/New_York") - hours(1),
            lambda: ZonedDateTime(1, 1, 1, 2, tz="America/New_York").subtract(
                hours=5
            ),
            lambda: (
                ZonedDateTime(1, 1, 1, tz="America/New_York")
                - ItemizedDelta(hours=1)
            ),
            lambda: ZonedDateTime(
                9999, 12, 31, 20, 29, tz="America/St_Johns"
            ).end_of("hour"),
            # past the rules of a POSIX TZ string
            lambda: ZonedDateTime(9999, 12, 31, 18, tz="America/New_York").add(
                hours=10
            ),
            lambda: ZonedDateTime(9999, 10, 31, 3, 45, tz="Europe/Dublin").add(
                hours=2000
            ),
        ],
    )
    def test_raises_value_error(self, func):
        with pytest.raises(
            ValueError, match="^value or calculation out of range$"
        ):
            func()

    @pytest.mark.parametrize(
        "now",
        [
            lambda: ZonedDateTime.now("Pacific/Kiritimati"),
            lambda: OffsetDateTime.now(hours(1), stale_offset_ok=True),
        ],
    )
    def test_now_past_max(self, now):
        with patch_current_time(Instant.MAX, keep_ticking=False):
            with pytest.raises(
                ValueError, match="^value or calculation out of range$"
            ):
                now()

    @pytest.mark.parametrize(
        "now",
        [
            lambda: ZonedDateTime.now("America/New_York"),
            lambda: OffsetDateTime.now(hours(-1), stale_offset_ok=True),
        ],
    )
    def test_now_before_min(self, now):
        with patch_current_time(Instant.MIN, keep_ticking=False):
            with pytest.raises(
                ValueError, match="^value or calculation out of range$"
            ):
                now()

    @pytest.mark.parametrize("value", [1 << 31, -(1 << 62)])
    @pytest.mark.parametrize(
        "make",
        [
            lambda v: Date(v, 1, 1),
            lambda v: Date(2020, 1, 1).replace(month=v),
            lambda v: YearMonth(v, 1),
            lambda v: YearMonth(2020, 1).replace(month=v),
            lambda v: MonthDay(v, 1),
            lambda v: MonthDay(1, 1).replace(day=v),
            lambda v: IsoWeekDate(v, 1, Weekday.MONDAY),
            lambda v: Time(v),
            lambda v: Time().replace(second=v),
            lambda v: PlainDateTime(2020, 1, 1, v),
            lambda v: PlainDateTime(2020, 1, 1).replace(day=v),
            lambda v: OffsetDateTime(v, 1, 1, offset=hours(0)),
            lambda v: OffsetDateTime(2020, 1, 1, offset=hours(0)).replace(
                minute=v, stale_offset_ok=True
            ),
            lambda v: ZonedDateTime(2020, 1, v, tz="UTC"),
            lambda v: ZonedDateTime(2020, 1, 1, tz="UTC").replace(hour=v),
            lambda v: Instant.from_utc(2020, 1, 1, v),
        ],
    )
    def test_field_beyond_a_c_int(self, make, value):
        # below 2**63, a field is out of range, not a machine-integer overflow
        with pytest.raises(ValueError):
            make(value)

    def test_oversized_int_is_out_of_range(self):
        # Distinct from the above: for an integer far outside the range the
        # backends may disagree on the type. Rust overflows its machine
        # integer before it can check the range; Python raises whatever its
        # own arithmetic produces.
        with pytest.raises((ValueError, OverflowError)):
            Instant.from_timestamp(10**30)


@pytest.mark.parametrize(
    "convert",
    [
        Instant.from_utc(2020, 1, 1).to_fixed_offset,
        OffsetDateTime(2020, 1, 1, offset=hours(1)).to_fixed_offset,
        ZonedDateTime(2020, 1, 1, tz="Europe/Amsterdam").to_fixed_offset,
        PlainDateTime(2020, 1, 1).assume_fixed_offset,
    ],
)
@pytest.mark.parametrize(
    "offset, exc, message",
    [
        ("x", TypeError, "offset must be a TimeDelta"),
        (
            hours(1) + TimeDelta(nanoseconds=1),
            ValueError,
            "offset must be a whole number of seconds",
        ),
        (hours(24), ValueError, "offset must be between -24 and 24 hours"),
        (hours(-24), ValueError, "offset must be between -24 and 24 hours"),
    ],
)
def test_offset_rejections(convert, offset, exc, message):
    # the four entry points that take an offset share one set of messages
    with pytest.raises(exc, match=f"^{message}$"):
        convert(offset)


@pytest.mark.parametrize(
    "cls", [Date, Time, TimeDelta, PlainDateTime, Instant]
)
def test_to_stdlib_extremes_convert(cls):
    cls.MIN.to_stdlib()
    cls.MAX.to_stdlib()


def test_to_stdlib_tzinfo():
    assert Instant.from_utc(2020, 1, 1).to_stdlib().tzinfo is py_timezone.utc
    assert (
        type(OffsetDateTime(2020, 1, 1, offset=hours(1)).to_stdlib().tzinfo)
        is py_timezone
    )
    assert isinstance(
        ZonedDateTime(2020, 1, 1, tz="Europe/Amsterdam").to_stdlib().tzinfo,
        ZoneInfo,
    )
    assert PlainDateTime(2020, 1, 1).to_stdlib().tzinfo is None


class TestLossyStdlibSubclass:
    """A pandas or pendulum object read through the stdlib fields warns."""

    @staticmethod
    def _datetime_subclass(module: str) -> type[py_datetime]:
        class Subclass(py_datetime):
            pass

        Subclass.__module__ = module
        return Subclass

    @staticmethod
    def _timedelta_subclass(module: str) -> type[py_timedelta]:
        class Subclass(py_timedelta):
            pass

        Subclass.__module__ = module
        return Subclass

    def test_pandas_timestamp(self):
        cls = self._datetime_subclass("pandas._libs.tslibs.timestamps")
        aware = cls(2020, 8, 15, 12, tzinfo=py_timezone.utc)
        match = (
            r"^pandas\.TestLossyStdlibSubclass\._datetime_subclass\.<locals>"
            r"\.Subclass contains data that cannot be reliably read through "
            r"the datetime\.datetime fields; convert it explicitly$"
        )
        with warns_here(WheneverWarning, match=match):
            assert Instant(aware) == Instant.from_utc(2020, 8, 15, 12)
        with warns_here(WheneverWarning, match=match):
            assert OffsetDateTime(aware) == OffsetDateTime(
                2020, 8, 15, 12, offset=hours(0)
            )
        with warns_here(WheneverWarning, match=match):
            assert ZonedDateTime(
                cls(2020, 8, 15, 12, tzinfo=ZoneInfo("Europe/Amsterdam"))
            ) == ZonedDateTime(2020, 8, 15, 12, tz="Europe/Amsterdam")
        with warns_here(WheneverWarning, match=match):
            assert PlainDateTime(cls(2020, 8, 15, 12)) == PlainDateTime(
                2020, 8, 15, 12
            )
        # read as a date, the datetime fields (not only pandas') are dropped
        with warns_here(
            WheneverWarning,
            match=match.replace("datetime\\.datetime", "datetime\\.date"),
        ):
            assert Date(cls(2020, 8, 15, 12)) == Date(2020, 8, 15)

    @pytest.mark.parametrize("module", ["pandas._libs", "pendulum.duration"])
    def test_lossy_timedelta(self, module: str):
        cls = self._timedelta_subclass(module)
        with warns_here(
            WheneverWarning,
            match=(
                r"Subclass contains data that cannot be reliably read "
                r"through the datetime\.timedelta fields; convert it explicitly$"
            ),
        ):
            assert TimeDelta(cls(days=1, seconds=2)) == TimeDelta(
                hours=24, seconds=2
            )

    def test_harmless_subclass_is_silent(self):
        cls = self._datetime_subclass("freezegun.api")
        aware = cls(2020, 8, 15, 12, tzinfo=py_timezone.utc)
        with warnings.catch_warnings():
            warnings.simplefilter("error")
            assert Instant(aware) == Instant.from_utc(2020, 8, 15, 12)
            assert PlainDateTime(cls(2020, 8, 15, 12)) == PlainDateTime(
                2020, 8, 15, 12
            )
            assert TimeDelta(
                self._timedelta_subclass("freezegun.api")(days=1)
            ) == TimeDelta(hours=24)

    def test_pendulum_datetime_is_silent(self):
        cls = self._datetime_subclass("pendulum.datetime")
        with warnings.catch_warnings():
            warnings.simplefilter("error")
            assert PlainDateTime(cls(2020, 8, 15, 12)) == PlainDateTime(
                2020, 8, 15, 12
            )


def _overriding(base: type) -> type:
    """A subclass whose overrides all lie: a reader must use the base fields."""

    def fail(*args, **kwargs):
        raise AssertionError("a subclass override was called")

    lies: dict[str, object] = {
        name: property(lambda self: 7)
        for name in (
            "year",
            "month",
            "day",
            "hour",
            "minute",
            "second",
            "microsecond",
            "fold",
            "days",
            "seconds",
            "microseconds",
        )
        if hasattr(base, name)
    }
    if hasattr(base, "tzinfo"):
        lies["tzinfo"] = property(lambda self: None)
    for name in ("replace", "astimezone", "date", "time", "timetz"):
        if hasattr(base, name):
            lies[name] = fail
    if base is py_datetime:
        lies["utcoffset"] = lambda self: py_timedelta(hours=5)
    return type(f"Overriding{base.__name__}", (base,), lies)


class TestSubclassIsReadThroughBase:
    """A stdlib subclass is read through the base type's fields, so its
    overrides go unread (the "Stdlib overloads" convention)."""

    @pytest.mark.parametrize(
        "make, expect",
        [
            (
                lambda: Instant(
                    _overriding(py_datetime)(
                        2020,
                        8,
                        15,
                        12,
                        tzinfo=py_timezone(py_timedelta(hours=2)),
                    )
                ),
                Instant.from_utc(2020, 8, 15, 10),
            ),
            (
                lambda: OffsetDateTime(
                    _overriding(py_datetime)(
                        2020,
                        8,
                        15,
                        12,
                        tzinfo=py_timezone(py_timedelta(hours=2)),
                    )
                ),
                OffsetDateTime(2020, 8, 15, 12, offset=hours(2)),
            ),
            (
                lambda: ZonedDateTime(
                    _overriding(py_datetime)(
                        2020, 8, 15, 12, tzinfo=ZoneInfo("Europe/Amsterdam")
                    )
                ),
                ZonedDateTime(2020, 8, 15, 12, tz="Europe/Amsterdam"),
            ),
            (
                lambda: PlainDateTime(
                    _overriding(py_datetime)(2020, 8, 15, 12)
                ),
                PlainDateTime(2020, 8, 15, 12),
            ),
            (
                lambda: Date(_overriding(py_date)(2020, 8, 15)),
                Date(2020, 8, 15),
            ),
            (lambda: Time(_overriding(py_time)(12, 30)), Time(12, 30)),
            (
                lambda: TimeDelta(_overriding(py_timedelta)(hours=1)),
                hours(1),
            ),
        ],
    )
    def test_overrides_are_ignored(self, make, expect):
        result = make()
        assert result == expect
        if hasattr(expect, "strict_eq"):
            assert result.strict_eq(expect)

    def test_tzinfo_may_return_a_timedelta_subclass(self):
        class Delta(py_timedelta):
            pass

        class MyTz(py_tzinfo):
            def utcoffset(self, _):
                return Delta(hours=2)

        d = py_datetime(2020, 8, 15, 12, tzinfo=MyTz())  # type: ignore[abstract]
        assert OffsetDateTime(d) == OffsetDateTime(
            2020, 8, 15, 12, offset=hours(2)
        )
        assert Instant(d) == Instant.from_utc(2020, 8, 15, 10)

    @pytest.mark.parametrize("cls", [Instant, OffsetDateTime])
    def test_fold_of_a_fixed_offset_is_dropped(self, cls):
        d = py_datetime(2020, 8, 15, 12, tzinfo=py_timezone.utc, fold=1)
        assert cls(d).to_stdlib().fold == 0
