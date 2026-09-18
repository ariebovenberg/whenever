import warnings
from datetime import (
    datetime as py_datetime,
    timedelta as py_timedelta,
    timezone as py_timezone,
)
from zoneinfo import ZoneInfo

import pytest
from whenever import (
    Date,
    Instant,
    OffsetDateTime,
    PlainDateTime,
    Time,
    TimeDelta,
    WheneverWarning,
    ZonedDateTime,
    hours,
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
        ],
    )
    def test_raises_value_error(self, func):
        with pytest.raises(ValueError):
            func()

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
