import pickle
import re
from copy import copy, deepcopy
from datetime import datetime as py_datetime, timedelta, timezone

import pytest
from hypothesis import given
from hypothesis.strategies import floats, integers, text

from whenever import (
    Instant,
    LocalDateTime,
    OffsetDateTime,
    SystemDateTime,
    ZonedDateTime,
    hours,
    milliseconds,
    minutes,
    nanoseconds,
    seconds,
)

from .common import (
    AlwaysEqual,
    AlwaysLarger,
    AlwaysSmaller,
    NeverEqual,
    system_tz_ams,
    system_tz_nyc,
)

BIG_INT = 1 << 64 + 1  # a big int that may cause an overflow error


def test_no_init():
    with pytest.raises(TypeError, match="cannot"):
        Instant()


class TestFromUTC:
    def test_defaults(self):
        assert Instant.from_utc(2020, 8, 15) == Instant.from_utc(
            2020, 8, 15, 0, 0, 0, nanosecond=0
        )

    @pytest.mark.parametrize(
        "kwargs, keyword",
        [
            (dict(year=0), "date|year"),
            (dict(year=10_000), "date|year"),
            (dict(year=BIG_INT), "too large|date|year"),
            (dict(year=-BIG_INT), "too large|date|year"),
            (dict(month=0), "date|month"),
            (dict(month=13), "date|month"),
            (dict(month=BIG_INT), "too large|date|month"),
            (dict(month=-BIG_INT), "too large|date|month"),
            (dict(day=0), "date|day"),
            (dict(day=32), "date|day"),
            (dict(day=BIG_INT), "too large|date|day"),
            (dict(day=-BIG_INT), "too large|date|day"),
            (dict(hour=-1), "time|hour"),
            (dict(hour=24), "time|hour"),
            (dict(hour=BIG_INT), "too large|time|hour"),
            (dict(hour=-BIG_INT), "too large|time|hour"),
            (dict(minute=-1), "time|minute"),
            (dict(minute=60), "time|minute"),
            (dict(minute=BIG_INT), "too large|time|minute"),
            (dict(minute=-BIG_INT), "too large|time|minute"),
            (dict(second=-1), "time|second"),
            (dict(second=60), "time|second"),
            (dict(second=BIG_INT), "too large|time|second"),
            (dict(second=-BIG_INT), "too large|time|second"),
            (dict(nanosecond=-1), "time|nanos"),
            (dict(nanosecond=1_000_000_000), "time|nanos"),
            (dict(nanosecond=BIG_INT), "too large|time|nanos"),
            (dict(nanosecond=-BIG_INT), "too large|time|nanos"),
        ],
    )
    def test_bounds(self, kwargs, keyword):
        defaults = {
            "year": 1,
            "month": 1,
            "day": 1,
            "hour": 0,
            "minute": 0,
            "second": 0,
            "nanosecond": 0,
        }

        with pytest.raises((ValueError, OverflowError), match=keyword):
            Instant.from_utc(**{**defaults, **kwargs})

    def test_kwargs(self):
        d = Instant.from_utc(
            year=2020, month=8, day=15, hour=5, minute=12, second=30
        )
        assert d == Instant.from_utc(2020, 8, 15, 5, 12, 30)

    def test_wrong_types(self):
        with pytest.raises(TypeError):
            Instant.from_utc("2020", 8, 15, 5, 12, 30)  # type: ignore[arg-type]

    @given(
        integers(),
        integers(),
        integers(),
        integers(),
        integers(),
        integers(),
        integers(),
    )
    def test_fuzzing(self, year, month, day, hour, minute, second, nanos):
        try:
            Instant.from_utc(
                year, month, day, hour, minute, second, nanosecond=nanos
            )
        except (ValueError, OverflowError):
            pass


def test_immutable():
    d = Instant.from_utc(2020, 8, 15)
    with pytest.raises(AttributeError):
        d.foo = 2021  # type: ignore[attr-defined]


class TestEquality:
    def test_same(self):
        d = Instant.from_utc(2020, 8, 15)
        same = Instant.from_utc(2020, 8, 15)
        assert d == same
        assert not d != same
        assert hash(d) == hash(same)
        assert d.exact_eq(same)

    def test_different(self):
        d = Instant.from_utc(2020, 8, 15)
        different = Instant.from_utc(2020, 8, 15, nanosecond=1)
        assert d != different
        assert not d == different
        assert hash(d) != hash(different)

    def test_notimplemented(self):
        d = Instant.from_utc(2020, 8, 15)
        assert d == AlwaysEqual()
        assert d != NeverEqual()
        assert not d == NeverEqual()
        assert not d != AlwaysEqual()

        assert not d == 3  # type: ignore[comparison-overlap]
        assert d != 3  # type: ignore[comparison-overlap]
        assert not 3 == d  # type: ignore[comparison-overlap]
        assert 3 != d  # type: ignore[comparison-overlap]
        assert not None == d  # noqa: E711
        assert None != d  # noqa: E711

    def test_zoned(self):
        d: Instant | ZonedDateTime = Instant.from_utc(2023, 10, 29, 1, 15)
        zoned_same = ZonedDateTime(
            2023, 10, 29, 2, 15, tz="Europe/Paris", disambiguate="later"
        )
        zoned_different = ZonedDateTime(
            2023, 10, 29, 2, 15, tz="Europe/Paris", disambiguate="earlier"
        )
        assert d == zoned_same
        assert not d != zoned_same
        assert not d == zoned_different
        assert d != zoned_different

        assert hash(d) == hash(zoned_same)
        assert hash(d) != hash(zoned_different)

    @system_tz_ams()
    def test_system_tz(self):
        d: Instant | SystemDateTime = Instant.from_utc(2023, 10, 29, 1, 15)
        sys_same = SystemDateTime(2023, 10, 29, 2, 15, disambiguate="later")
        sys_different = SystemDateTime(
            2023, 10, 29, 2, 15, disambiguate="earlier"
        )
        assert d == sys_same
        assert not d != sys_same
        assert not d == sys_different
        assert d != sys_different

        assert hash(d) == hash(sys_same)
        assert hash(d) != hash(sys_different)

    def test_offset(self):
        d: Instant | OffsetDateTime = Instant.from_utc(2023, 4, 5, 4)
        offset_same = OffsetDateTime(2023, 4, 5, 6, offset=+2)
        offset_different = OffsetDateTime(2023, 4, 5, 4, offset=-3)
        assert d == offset_same
        assert not d != offset_same
        assert not d == offset_different
        assert d != offset_different

        assert hash(d) == hash(offset_same)
        assert hash(d) != hash(offset_different)


class TestTimestamp:

    def test_default_seconds(self):
        assert Instant.from_utc(1970, 1, 1).timestamp() == 0
        assert (
            Instant.from_utc(
                2020, 8, 15, 12, 8, 30, nanosecond=45_123
            ).timestamp()
            == 1_597_493_310
        )
        assert Instant.MAX.timestamp() == 253402300799
        assert Instant.MIN.timestamp() == -62135596800

    def test_millis(self):
        assert Instant.from_utc(1970, 1, 1).timestamp_millis() == 0
        assert (
            Instant.from_utc(
                2020, 8, 15, 12, 8, 30, nanosecond=45_123_987
            ).timestamp_millis()
            == 1_597_493_310_045
        )
        assert Instant.MAX.timestamp_millis() == 253402300799999
        assert Instant.MIN.timestamp_millis() == -62135596800000

    def test_nanos(self):
        assert Instant.from_utc(1970, 1, 1).timestamp_nanos() == 0
        assert (
            Instant.from_utc(
                2020, 8, 15, 12, 8, 30, nanosecond=45_123_789
            ).timestamp_nanos()
            == 1_597_493_310_045_123_789
        )
        assert Instant.MAX.timestamp_nanos() == 253402300799_999_999_999
        assert Instant.MIN.timestamp_nanos() == -62135596800_000_000_000


class TestFromTimestamp:

    @pytest.mark.parametrize(
        "method, factor",
        [
            (Instant.from_timestamp, 1),
            (Instant.from_timestamp_millis, 1_000),
            (Instant.from_timestamp_nanos, 1_000_000_000),
        ],
    )
    def test_all(self, method, factor):
        assert method(0) == Instant.from_utc(1970, 1, 1)
        assert method(1_597_493_310 * factor) == Instant.from_utc(
            2020, 8, 15, 12, 8, 30
        )

        assert method(-4 * factor) == Instant.from_utc(
            1969, 12, 31, 23, 59, 56
        )

        with pytest.raises((OSError, OverflowError, ValueError)):
            method(1_000_000_000_000_000_000 * factor)

        with pytest.raises((OSError, OverflowError, ValueError)):
            method(-1_000_000_000_000_000_000 * factor)

        with pytest.raises((OSError, OverflowError, ValueError)):
            method(1 << 129)

        if method != Instant.from_timestamp:
            with pytest.raises(TypeError):
                method(1.0)

        assert Instant.from_timestamp_millis(-4) == Instant.from_timestamp(
            0
        ) - milliseconds(4)

        assert Instant.from_timestamp_nanos(-4) == Instant.from_timestamp(
            0
        ) - nanoseconds(4)

    def test_extremes(self):
        assert Instant.from_timestamp(
            Instant.MAX.timestamp()
        ) == Instant.from_utc(9999, 12, 31, 23, 59, 59)
        assert Instant.from_timestamp(Instant.MIN.timestamp()) == Instant.MIN

        assert Instant.from_timestamp_millis(
            Instant.MAX.timestamp_millis()
        ) == Instant.from_utc(9999, 12, 31, 23, 59, 59, nanosecond=999_000_000)
        assert (
            Instant.from_timestamp_millis(Instant.MIN.timestamp_millis())
            == Instant.MIN
        )

        assert (
            Instant.from_timestamp_nanos(Instant.MAX.timestamp_nanos())
            == Instant.MAX
        )
        assert (
            Instant.from_timestamp_nanos(Instant.MIN.timestamp_nanos())
            == Instant.MIN
        )

    def test_float(self):
        assert Instant.from_timestamp(1.0) == Instant.from_timestamp(1)
        assert Instant.from_timestamp(1.000_000_001) == Instant.from_timestamp(
            1
        ) + nanoseconds(1)

        assert Instant.from_timestamp(
            -9.000_000_100
        ) == Instant.from_timestamp(-9) - nanoseconds(100)

        with pytest.raises((ValueError, OverflowError)):
            Instant.from_timestamp(9e200)

        with pytest.raises((ValueError, OverflowError)):
            Instant.from_timestamp(float(Instant.MAX.timestamp()) + 0.99999999)

        with pytest.raises((ValueError, OverflowError)):
            Instant.from_timestamp(float("inf"))

        with pytest.raises((ValueError, OverflowError)):
            Instant.from_timestamp(float("nan"))

    def test_invalid(self):
        with pytest.raises(TypeError):
            Instant.from_timestamp("2020")  # type: ignore[arg-type]


def test_repr():
    d = Instant.from_utc(2020, 8, 15, 23, 12, 9, nanosecond=987_654)
    assert repr(d) == "Instant(2020-08-15 23:12:09.000987654Z)"
    assert (
        repr(Instant.from_utc(2020, 8, 15, 23, 12))
        == "Instant(2020-08-15 23:12:00Z)"
    )


class TestComparison:
    def test_instant(self):
        d = Instant.from_utc(2020, 8, 15, 23, 12, 9)
        same = Instant.from_utc(2020, 8, 15, 23, 12, 9)
        later = Instant.from_utc(2020, 8, 16)

        assert not d > same
        assert d >= same
        assert not d < same
        assert d <= same

        assert d < later
        assert d <= later
        assert not d > later
        assert not d >= later

        assert later > d
        assert later >= d
        assert not later < d
        assert not later <= d

        assert d < AlwaysLarger()
        assert d <= AlwaysLarger()
        assert not d > AlwaysLarger()
        assert not d >= AlwaysLarger()
        assert not d < AlwaysSmaller()
        assert not d <= AlwaysSmaller()
        assert d > AlwaysSmaller()
        assert d >= AlwaysSmaller()

    def test_offset(self):
        d = Instant.from_utc(2020, 8, 15, 12, 30)

        offset_eq = d.to_fixed_offset(4)
        offset_gt = offset_eq.replace(minute=31, ignore_dst=True)
        offset_lt = offset_eq.replace(minute=29, ignore_dst=True)
        assert d >= offset_eq
        assert d <= offset_eq
        assert not d > offset_eq
        assert not d < offset_eq

        assert d > offset_lt
        assert d >= offset_lt
        assert not d < offset_lt
        assert not d <= offset_lt

        assert d < offset_gt
        assert d <= offset_gt
        assert not d > offset_gt
        assert not d >= offset_gt

    def test_zoned(self):
        d = Instant.from_utc(2023, 10, 29, 1, 15)
        zoned_eq = ZonedDateTime(
            2023, 10, 29, 2, 15, tz="Europe/Paris", disambiguate="later"
        )

        zoned_gt = zoned_eq.replace(minute=16, disambiguate="later")
        zoned_lt = zoned_eq.replace(minute=14, disambiguate="later")
        assert d >= zoned_eq
        assert d <= zoned_eq
        assert not d > zoned_eq
        assert not d < zoned_eq

        assert d > zoned_lt
        assert d >= zoned_lt
        assert not d < zoned_lt
        assert not d <= zoned_lt

        assert d < zoned_gt
        assert d <= zoned_gt
        assert not d > zoned_gt
        assert not d >= zoned_gt

    @system_tz_nyc()
    def test_system_tz(self):
        d = Instant.from_utc(2020, 8, 15, 12, 30)

        sys_eq = d.to_system_tz()
        sys_gt = sys_eq + minutes(1)
        sys_lt = sys_eq - minutes(1)
        assert d >= sys_eq
        assert d <= sys_eq
        assert not d > sys_eq
        assert not d < sys_eq

        assert d > sys_lt
        assert d >= sys_lt
        assert not d < sys_lt
        assert not d <= sys_lt

        assert d < sys_gt
        assert d <= sys_gt
        assert not d > sys_gt
        assert not d >= sys_gt

    def test_notimplemented(self):
        d = Instant.from_utc(2020, 8, 15)
        assert d < AlwaysLarger()
        assert d <= AlwaysLarger()
        assert not d > AlwaysLarger()
        assert not d >= AlwaysLarger()
        assert not d < AlwaysSmaller()
        assert not d <= AlwaysSmaller()
        assert d > AlwaysSmaller()
        assert d >= AlwaysSmaller()

        with pytest.raises(TypeError):
            d < 42  # type: ignore[operator]
        with pytest.raises(TypeError):
            d <= 42  # type: ignore[operator]
        with pytest.raises(TypeError):
            d > 42  # type: ignore[operator]
        with pytest.raises(TypeError):
            d >= 42  # type: ignore[operator]
        with pytest.raises(TypeError):
            42 < d  # type: ignore[operator]
        with pytest.raises(TypeError):
            42 <= d  # type: ignore[operator]
        with pytest.raises(TypeError):
            42 > d  # type: ignore[operator]
        with pytest.raises(TypeError):
            42 >= d  # type: ignore[operator]
        with pytest.raises(TypeError):
            None < d  # type: ignore[operator]
        with pytest.raises(TypeError):
            None <= d  # type: ignore[operator]
        with pytest.raises(TypeError):
            None > d  # type: ignore[operator]
        with pytest.raises(TypeError):
            None >= d  # type: ignore[operator]


def test_py_datetime():
    d = Instant.from_utc(2020, 8, 15, 23, 12, 9, nanosecond=987_654)
    assert d.py_datetime() == py_datetime(
        2020, 8, 15, 23, 12, 9, 987, tzinfo=timezone.utc
    )


def test_from_py_datetime():
    d = py_datetime(2020, 8, 15, 23, 12, 9, 987_654, tzinfo=timezone.utc)
    assert Instant.from_py_datetime(d) == Instant.from_utc(
        2020, 8, 15, 23, 12, 9, nanosecond=987_654_000
    )

    with pytest.raises(ValueError, match="UTC.*timedelta"):
        Instant.from_py_datetime(
            d.replace(tzinfo=timezone(-timedelta(hours=4)))
        )


def test_now():
    now = Instant.now()
    py_now = py_datetime.now(timezone.utc)
    assert py_now - now.py_datetime() < timedelta(seconds=1)


def test_min_max():
    assert Instant.MIN == Instant.from_utc(1, 1, 1)
    assert Instant.MAX == Instant.from_utc(
        9999, 12, 31, 23, 59, 59, nanosecond=999_999_999
    )


class TestAddMethod:

    def test_valid(self):
        d = Instant.from_utc(2020, 8, 15, 23, 12, 9, nanosecond=987_654_321)
        assert d.add(hours=24, seconds=5) == d + hours(24) + seconds(5)
        assert d + nanoseconds(20_000_000) == d.add(nanoseconds=20_000_000)

    def test_invalid(self):
        d = Instant.from_utc(2020, 8, 15, 23, 12, 9, nanosecond=987_654)
        with pytest.raises((ValueError, OverflowError), match="range"):
            d.add(hours=24 * 365 * 8000)

        with pytest.raises((ValueError, OverflowError), match="range"):
            d.add(hours=-24 * 365 * 3000)

        with pytest.raises(TypeError, match="positional"):
            d.add(4)  # type: ignore[misc]

    @given(
        hours=floats(),
        minutes=floats(),
        seconds=floats(),
        milliseconds=floats(),
        microseconds=floats(),
        nanoseconds=integers(),
    )
    def test_fuzzing(self, **kwargs):
        d = Instant.from_utc(2020, 8, 15, 23, 12, 9, nanosecond=987_654_321)
        try:
            d.add(**kwargs)
        except (ValueError, OverflowError):
            pass


class TestSubtractMethod:

    def test_valid(self):
        d = Instant.from_utc(2020, 8, 15, 23, 12, 9, nanosecond=987_654)
        assert d.subtract(hours=24, seconds=5) == d - hours(24) - seconds(5)

    def test_invalid(self):
        d = Instant.from_utc(2020, 8, 15, 23, 12, 9, nanosecond=987_654)
        with pytest.raises((ValueError, OverflowError), match="range"):
            d.subtract(hours=24 * 365 * 3000)

        with pytest.raises((ValueError, OverflowError), match="range"):
            d.subtract(hours=-24 * 365 * 8000)

        with pytest.raises(TypeError, match="positional"):
            d.subtract(4)  # type: ignore[misc]

        with pytest.raises(TypeError, match="positional"):
            d.subtract(hours(4))  # type: ignore[arg-type,misc]

    @given(
        hours=floats(),
        minutes=floats(),
        seconds=floats(),
        milliseconds=floats(),
        microseconds=floats(),
        nanoseconds=integers(),
    )
    def test_fuzzing(self, **kwargs):
        d = Instant.from_utc(2020, 8, 15, 23, 12, 9, nanosecond=987_654_321)
        try:
            d.subtract(**kwargs)
        except (ValueError, OverflowError):
            pass


class TestShiftOperators:
    def test_time_units(self):
        d = Instant.from_utc(2020, 8, 15, 23, 12, 9, nanosecond=987_654_321)
        assert d + hours(24) + seconds(5) == Instant.from_utc(
            2020, 8, 16, 23, 12, 14, nanosecond=987_654_321
        )
        assert d + nanoseconds(20_000_000) == Instant.from_utc(
            2020, 8, 15, 23, 12, 10, nanosecond=7_654_321
        )

        # same with subtract
        assert d - hours(-24) - seconds(-5) == d + hours(24) + seconds(5)

        with pytest.raises((ValueError, OverflowError), match="range"):
            d + hours(9_000 * 366 * 24)

    def test_invalid(self):
        d = Instant.from_utc(2020, 8, 15, 23, 12, 9, nanosecond=987_654)
        with pytest.raises(TypeError, match="unsupported operand type"):
            d + 42  # type: ignore[operator]

        with pytest.raises(TypeError, match="unsupported operand type"):
            42 + d  # type: ignore[operator]

        with pytest.raises(TypeError, match="unsupported operand type"):
            None + d  # type: ignore[operator]

        with pytest.raises(TypeError, match="unsupported operand type"):
            LocalDateTime(2020, 1, 1) + d  # type: ignore[operator]


class TestDifference:

    def test_other_instant(self):
        d = Instant.from_utc(2020, 8, 15, 23, 12, 9, nanosecond=987_654_000)
        other = Instant.from_utc(
            2020, 8, 14, 23, 12, 4, nanosecond=987_654_321
        )
        assert d - other == hours(24) + seconds(5) - nanoseconds(321)

        # same with method
        assert d.difference(other) == d - other

    def test_offset(self):
        d = Instant.from_utc(2020, 8, 15, 23)
        other = OffsetDateTime(2020, 8, 15, 20, offset=2)
        assert d - other == hours(5)

        # same with method
        assert d.difference(other) == d - other

    def test_zoned(self):
        d = Instant.from_utc(2023, 10, 29, 6)
        other = ZonedDateTime(
            2023, 10, 29, 3, tz="Europe/Paris", disambiguate="later"
        )
        assert d - other == hours(4)
        assert d - ZonedDateTime(
            2023, 10, 29, 2, tz="Europe/Paris", disambiguate="later"
        ) == hours(5)
        assert d - ZonedDateTime(
            2023, 10, 29, 2, tz="Europe/Paris", disambiguate="earlier"
        ) == hours(6)
        assert d - ZonedDateTime(2023, 10, 29, 1, tz="Europe/Paris") == hours(
            7
        )

        # same with method
        assert d.difference(other) == d - other

    @system_tz_ams()
    def test_system_tz(self):
        d = Instant.from_utc(2023, 10, 29, 6)
        other = SystemDateTime(2023, 10, 29, 3, disambiguate="later")
        assert d - other == hours(4)
        assert d - SystemDateTime(
            2023, 10, 29, 2, disambiguate="later"
        ) == hours(5)
        assert d - SystemDateTime(
            2023, 10, 29, 2, disambiguate="earlier"
        ) == hours(6)
        assert d - SystemDateTime(2023, 10, 29, 1) == hours(7)

        # same with method
        assert d.difference(other) == d - other

    def test_invalid(self):
        d = Instant.from_utc(2020, 8, 15, 23, 12, 9, nanosecond=987_654)
        with pytest.raises(TypeError, match="unsupported operand type"):
            d - 42  # type: ignore[operator]

        with pytest.raises(TypeError, match="unsupported operand type"):
            42 - d  # type: ignore[operator]

        with pytest.raises(TypeError, match="unsupported operand type"):
            None - d  # type: ignore[operator]


def test_pickle():
    d = Instant.from_utc(2020, 8, 15, 23, 12, 9, nanosecond=987_654_200)
    dumped = pickle.dumps(d)
    assert len(dumped) <= len(pickle.dumps(d.py_datetime()))
    assert pickle.loads(pickle.dumps(d)) == d


def test_old_pickle_data_remains_unpicklable():
    # Don't update this value after 1.x release -- the whole idea is that it's
    # a pickle at a specific version of the library.
    dumped = (
        b"\x80\x04\x95.\x00\x00\x00\x00\x00\x00\x00\x8c\x08whenever\x94\x8c\n_unpkl_u"
        b"tc\x94\x93\x94C\x0cI\xb4\xcb\xd6\x0e\x00\x00\x008h\xde:\x94\x85\x94R\x94."
    )
    assert pickle.loads(dumped) == Instant.from_utc(
        2020, 8, 15, 23, 12, 9, nanosecond=987_654_200
    )


def test_copy():
    d = Instant.from_utc(2020, 8, 15, 23, 12, 9, nanosecond=987_654)
    assert copy(d) is d
    assert deepcopy(d) is d


def test_to_fixed_offset():
    d = Instant.from_utc(2020, 8, 15, 20)
    assert d.to_fixed_offset().exact_eq(
        OffsetDateTime(2020, 8, 15, 20, offset=0)
    )
    assert d.to_fixed_offset(hours(3)).exact_eq(
        OffsetDateTime(2020, 8, 15, 23, offset=3)
    )
    assert d.to_fixed_offset(-3).exact_eq(
        OffsetDateTime(2020, 8, 15, 17, offset=-3)
    )

    with pytest.raises((ValueError, OverflowError)):
        Instant.MIN.to_fixed_offset(-4)

    with pytest.raises((ValueError, OverflowError)):
        Instant.MAX.to_fixed_offset(4)


def test_to_tz():
    d = Instant.from_utc(2020, 8, 15, 20)
    assert d.to_tz("America/New_York").exact_eq(
        ZonedDateTime(2020, 8, 15, 16, tz="America/New_York")
    )

    with pytest.raises((ValueError, OverflowError, OSError)):
        Instant.MIN.to_tz("America/New_York")

    with pytest.raises((ValueError, OverflowError, OSError)):
        Instant.MAX.to_tz("Asia/Tokyo")


@system_tz_nyc()
def test_to_system_tz():
    d = Instant.from_utc(2020, 8, 15, 20)
    assert d.to_system_tz().exact_eq(SystemDateTime(2020, 8, 15, 16))
    # ensure disembiguation is correct
    d = Instant.from_utc(2022, 11, 6, 5)
    assert d.to_system_tz().exact_eq(
        SystemDateTime(2022, 11, 6, 1, disambiguate="earlier")
    )
    assert Instant.from_utc(2022, 11, 6, 6).to_system_tz() == SystemDateTime(
        2022, 11, 6, 1, disambiguate="later"
    )

    with pytest.raises((ValueError, OverflowError)):
        Instant.MIN.to_system_tz()

    with system_tz_ams():
        with pytest.raises((ValueError, OverflowError)):
            Instant.MAX.to_system_tz()


def test_rfc2822():
    assert (
        Instant.from_utc(
            2020, 8, 15, 23, 12, 9, nanosecond=450
        ).format_rfc2822()
        == "Sat, 15 Aug 2020 23:12:09 GMT"
    )


class TestParseRFC2822:

    @pytest.mark.parametrize(
        "s, expected",
        [
            (
                "Sat, 15 Aug 2020 23:12:09 GMT",
                Instant.from_utc(2020, 8, 15, 23, 12, 9),
            ),
            (
                "Sat, 15 Aug 2020 23:12:09 +0000",
                Instant.from_utc(2020, 8, 15, 23, 12, 9),
            ),
            (
                "Sat, 15 Aug 2020 23:12:09 -0000",
                Instant.from_utc(2020, 8, 15, 23, 12, 9),
            ),
            (
                "Sat, 15 Aug 2020 23:12:09 UTC",
                Instant.from_utc(2020, 8, 15, 23, 12, 9),
            ),
            (
                "15      Aug 2020\n23:12 UTC",
                Instant.from_utc(2020, 8, 15, 23, 12),
            ),
        ],
    )
    def test_valid(self, s, expected):
        assert Instant.parse_rfc2822(s) == expected

    @pytest.mark.parametrize(
        "s",
        [
            "Sat, 15 Aug 2020 23:12:09 +0200",  # non-UTC offset
            "Sat, 15 Aug 2020 23:12:09,0 GMT",  # fraction
            "Sat, 15 Aug 2020 23:12:09.0 GMT",  # fraction
            "Sat, 15 Aug 2020 23:12:09",  # missing zone/offset
            "blurb",  # garbage
            # FUTURE: is this a bug in the stdlib?
            # "Sat, 𝟙5 Aug 2020 23:12:09 UTC",  # non-ascii
        ],
    )
    def test_invalid(self, s):
        with pytest.raises(
            ValueError,
            match=r"(Could not parse.*RFC 2822|Invalid).*" + re.escape(s),
        ):
            Instant.parse_rfc2822(s)


def test_format_rfc3339():
    assert (
        Instant.from_utc(
            2020, 8, 15, 23, 12, 9, nanosecond=450
        ).format_rfc3339()
        == "2020-08-15 23:12:09.00000045Z"
    )


class TestParseRFC3339:

    @pytest.mark.parametrize(
        "s, expect",
        [
            (
                "2020-08-15T23:12:09.000450Z",
                Instant.from_utc(2020, 8, 15, 23, 12, 9, nanosecond=450_000),
            ),
            (
                "2020-08-15T23:12:09.000002001Z",
                Instant.from_utc(2020, 8, 15, 23, 12, 9, nanosecond=2_001),
            ),
            (
                "2020-08-15t23:12:09z",
                Instant.from_utc(2020, 8, 15, 23, 12, 9),
            ),
            (
                "2020-08-15_23:12:09-00:00",
                Instant.from_utc(2020, 8, 15, 23, 12, 9),
            ),
            (
                "2020-08-15_23:12:09+00:00",
                Instant.from_utc(2020, 8, 15, 23, 12, 9),
            ),
            (
                "2020-08-15T23:12:09.34Z",
                Instant.from_utc(
                    2020, 8, 15, 23, 12, 9, nanosecond=340_000_000
                ),
            ),
        ],
    )
    def test_parse_rfc3339(self, s, expect):
        assert Instant.parse_rfc3339(s) == expect

    @pytest.mark.parametrize(
        "s",
        [
            "2020-8-15T23:12:45Z",  # invalid padding
            "2020-08-15T23:12Z",  # no seconds
            "2020-08-15_23Z",  # no time
            "2020-08Z",  # no time or date
            "",  # empty
            "garbage",  # garbage
            "2020-08-15T23:12:09.1234567890Z",  # too precise
            "2020-09-15T22:44:20+01:00",  # non-UTC offset
            "2020-08-15T23:12:09.34ZZ",  # extra Z
            "2020-08-15T23:12:09.34Z01:00",  # offset and Z
            "2020-08-15T23:12:09.3𝟜Z",  # non ascii
        ],
    )
    def test_invalid(self, s):
        # no timezone
        with pytest.raises(
            ValueError,
            match=r"Invalid.*RFC 3339.*" + re.escape(s),
        ):
            Instant.parse_rfc3339(s)


@pytest.mark.parametrize(
    "d, expect",
    [
        (
            Instant.from_utc(2020, 8, 15, 23, 12, 9, nanosecond=987_654),
            "2020-08-15T23:12:09.000987654Z",
        ),
        (
            Instant.from_utc(2020, 8, 15, 23, 12, 9, nanosecond=980_000_000),
            "2020-08-15T23:12:09.98Z",
        ),
        (Instant.from_utc(2020, 8, 15), "2020-08-15T00:00:00Z"),
        (Instant.from_utc(2020, 8, 15, 23, 12, 9), "2020-08-15T23:12:09Z"),
    ],
)
def test_format_common_iso(d, expect):
    assert d.format_common_iso() == expect
    assert str(d) == expect


class TestParseCommonIso:

    @pytest.mark.parametrize(
        "s, expect",
        [
            (
                "2020-08-15T23:12:09.000450Z",
                Instant.from_utc(2020, 8, 15, 23, 12, 9, nanosecond=450_000),
            ),
            (
                "2020-08-15T23:12:09+00:00",
                Instant.from_utc(2020, 8, 15, 23, 12, 9),
            ),
            (
                "2020-08-15T23:12:09Z",
                Instant.from_utc(2020, 8, 15, 23, 12, 9),
            ),
            (
                "2020-08-15T23:12:09.34Z",
                Instant.from_utc(
                    2020, 8, 15, 23, 12, 9, nanosecond=340_000_000
                ),
            ),
            # full precision
            (
                "2020-08-15T23:12:09.987654001Z",
                Instant.from_utc(
                    2020, 8, 15, 23, 12, 9, nanosecond=987_654_001
                ),
            ),
            # microsecond precision
            (
                "2020-08-15T23:12:09.987654Z",
                Instant.from_utc(
                    2020, 8, 15, 23, 12, 9, nanosecond=987_654_000
                ),
            ),
            # no fractions
            ("2020-08-15T23:12:09Z", Instant.from_utc(2020, 8, 15, 23, 12, 9)),
            # no time
            ("2020-08-15T00:00:00Z", Instant.from_utc(2020, 8, 15)),
            # millisecond precision
            (
                "2020-08-15T23:12:09.344Z",
                Instant.from_utc(
                    2020, 8, 15, 23, 12, 9, nanosecond=344_000_000
                ),
            ),
            # single fraction
            (
                "2020-08-15T23:12:09.3Z",
                Instant.from_utc(
                    2020, 8, 15, 23, 12, 9, nanosecond=300_000_000
                ),
            ),
            ("2020-08-15T23:12:09Z", Instant.from_utc(2020, 8, 15, 23, 12, 9)),
        ],
    )
    def test_valid(self, s, expect):
        assert Instant.parse_common_iso(s) == expect

    @pytest.mark.parametrize(
        "s",
        [
            "2020-8-15T23:12:45Z",  # invalid padding
            "2020-08-15T23:12Z",  # no seconds
            "2020-08-15_23Z",  # no time
            "2020-08Z",  # no time or date
            "2020Z",  # no time or date
            "Z",  # no time or date
            "garbage",  # garbage
            "",  # empty
            "2020-08-15T23:12:09.000450",  # no offset
            "2020-08-15T23:12:09+02:00",  # non-UTC offset
            "2020-08-15 23:12:09Z",  # non-T separator
            "2020-08-15t23:12:09Z",  # non-T separator
            "2020-08-15T23:12:09z",  # lowercase Z
            "2020-08-15T23:12:09-00:00",  # forbidden offset
            "2020-08-15T23:12:09-02:00:03",  # seconds in offset
            "2020-08-15T23:12:09.3𝟜Z",  # non ascii
            "2020-08-15T23:12:09.1234567890Z",  # too precise
            "2020-09-15T22:44:20",  # no trailing z
            "2020-09-15T\x0012:32",  # NULL byte
            "2020-08-15T23:12:09.3𝟙Z",  # non ascii
        ],
    )
    def test_invalid(self, s):
        with pytest.raises(
            ValueError,
            match=r"Invalid format.*" + re.escape(repr(s)),
        ):
            Instant.parse_common_iso(s)

    @given(text())
    def test_fuzzing(self, s: str):
        with pytest.raises(
            ValueError,
            match=r"Invalid format.*" + re.escape(repr(s)),
        ):
            Instant.parse_common_iso(s)


def test_cannot_subclass():
    with pytest.raises(TypeError):

        class Subclass(Instant):  # type: ignore[misc]
            pass
