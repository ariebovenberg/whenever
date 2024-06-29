import pickle
import re
from datetime import datetime as py_datetime, timezone

import pytest
from hypothesis import given
from hypothesis.strategies import floats, integers, text

from whenever import (
    Date,
    ImplicitlyIgnoringDST,
    Instant,
    LocalDateTime,
    OffsetDateTime,
    RepeatedTime,
    SkippedTime,
    SystemDateTime,
    Time,
    ZonedDateTime,
    days,
    hours,
    months,
    nanoseconds,
    seconds,
    weeks,
    years,
)

from .common import (
    AlwaysEqual,
    AlwaysLarger,
    AlwaysSmaller,
    NeverEqual,
    system_tz_ams,
)


def test_minimal():
    d = LocalDateTime(2020, 8, 15, 5, 12, 30, nanosecond=450)

    assert d.year == 2020
    assert d.month == 8
    assert d.day == 15
    assert d.hour == 5
    assert d.minute == 12
    assert d.second == 30
    assert d.nanosecond == 450

    assert (
        LocalDateTime(2020, 8, 15, 12)
        == LocalDateTime(2020, 8, 15, 12, 0)
        == LocalDateTime(2020, 8, 15, 12, 0, 0)
        == LocalDateTime(2020, 8, 15, 12, 0, 0, nanosecond=0)
    )


def test_components():
    d = LocalDateTime(2020, 8, 15, 23, 12, 9, nanosecond=987_654_123)
    assert d.date() == Date(2020, 8, 15)
    assert d.time() == Time(23, 12, 9, nanosecond=987_654_123)


def test_assume_utc():
    assert LocalDateTime(2020, 8, 15, 23).assume_utc() == Instant.from_utc(
        2020, 8, 15, 23
    )


def test_assume_fixed_offset():
    assert (
        LocalDateTime(2020, 8, 15, 23)
        .assume_fixed_offset(hours(5))
        .exact_eq(OffsetDateTime(2020, 8, 15, 23, offset=5))
    )
    assert (
        LocalDateTime(2020, 8, 15, 23)
        .assume_fixed_offset(-2)
        .exact_eq(OffsetDateTime(2020, 8, 15, 23, offset=-2))
    )


class TestAssumeZoned:
    def test_typical(self):
        d = LocalDateTime(2020, 8, 15, 23)
        assert d.assume_tz(
            "Asia/Tokyo", disambiguate="raise"
        ) == ZonedDateTime(2020, 8, 15, 23, tz="Asia/Tokyo")

        # disambiguate is required
        with pytest.raises(TypeError, match="disambiguat"):
            d.assume_tz("Asia/Tokyo")  # type: ignore[call-arg]

    def test_ambiguous(self):
        d = LocalDateTime(2023, 10, 29, 2, 15)

        with pytest.raises(RepeatedTime, match="02:15.*Europe/Amsterdam"):
            d.assume_tz("Europe/Amsterdam", disambiguate="raise")

        assert d.assume_tz(
            "Europe/Amsterdam", disambiguate="earlier"
        ) == ZonedDateTime(
            2023, 10, 29, 2, 15, tz="Europe/Amsterdam", disambiguate="earlier"
        )
        assert d.assume_tz(
            "Europe/Amsterdam", disambiguate="later"
        ) == ZonedDateTime(
            2023, 10, 29, 2, 15, tz="Europe/Amsterdam", disambiguate="later"
        )

    def test_nonexistent(self):
        d = LocalDateTime(2023, 3, 26, 2, 15)

        with pytest.raises(SkippedTime, match="02:15.*Europe/Amsterdam"):
            d.assume_tz("Europe/Amsterdam", disambiguate="raise")

        assert d.assume_tz(
            "Europe/Amsterdam", disambiguate="earlier"
        ) == ZonedDateTime(
            2023, 3, 26, 2, 15, tz="Europe/Amsterdam", disambiguate="earlier"
        )


class TestAssumeSystemTz:
    @system_tz_ams()
    def test_typical(self):
        assert LocalDateTime(2020, 8, 15, 23).assume_system_tz(
            disambiguate="raise"
        ) == SystemDateTime(2020, 8, 15, 23)

        # disambiguate is required
        with pytest.raises(TypeError, match="disambiguat"):
            LocalDateTime(2020, 8, 15, 23).assume_system_tz()  # type: ignore[call-arg]

    @system_tz_ams()
    def test_ambiguous(self):
        d = LocalDateTime(2023, 10, 29, 2, 15)

        with pytest.raises(RepeatedTime, match="02:15.*system"):
            d.assume_system_tz(disambiguate="raise")

        assert d.assume_system_tz(disambiguate="earlier") == SystemDateTime(
            2023, 10, 29, 2, 15, disambiguate="earlier"
        )
        assert d.assume_system_tz(disambiguate="compatible") == SystemDateTime(
            2023, 10, 29, 2, 15, disambiguate="earlier"
        )
        assert d.assume_system_tz(disambiguate="later") == SystemDateTime(
            2023, 10, 29, 2, 15, disambiguate="later"
        )

    @system_tz_ams()
    def test_nonexistent(self):
        d = LocalDateTime(2023, 3, 26, 2, 15)

        with pytest.raises(SkippedTime, match="02:15.*system"):
            d.assume_system_tz(disambiguate="raise")

        assert d.assume_system_tz(disambiguate="earlier") == SystemDateTime(
            2023, 3, 26, 2, 15, disambiguate="earlier"
        )
        assert d.assume_system_tz(disambiguate="later") == SystemDateTime(
            2023, 3, 26, 2, 15, disambiguate="later"
        )
        assert d.assume_system_tz(disambiguate="compatible") == SystemDateTime(
            2023, 3, 26, 2, 15, disambiguate="compatible"
        )


def test_immutable():
    d = LocalDateTime(2020, 8, 15)
    with pytest.raises(AttributeError):
        d.year = 2021  # type: ignore[misc]


class TestParseCommonIso:
    @pytest.mark.parametrize(
        "s, expected",
        [
            ("2020-08-15T12:08:30", LocalDateTime(2020, 8, 15, 12, 8, 30)),
            (
                "2020-08-15T12:08:30.349",
                LocalDateTime(2020, 8, 15, 12, 8, 30, nanosecond=349_000_000),
            ),
            (
                "2020-08-15T12:08:30.3491239",
                LocalDateTime(2020, 8, 15, 12, 8, 30, nanosecond=349_123_900),
            ),
        ],
    )
    def test_valid(self, s, expected):
        assert LocalDateTime.parse_common_iso(s) == expected

    @pytest.mark.parametrize(
        "s",
        [
            "2020-08-15T12:08:30.1234567890",  # too many fractions
            "2020-08-15T12:08:30.",  # no fractions
            "2020-08-15T12:08:30.45+0500",  # offset
            "2020-08-15T12:08:30+05:00",  # offset
            "2020-08-15",  # just a date
            "2020",  # way too short
            "2020033434T12.08.30",  # invalid separators
            "garbage",  # garbage
            "12:08:30.1234567890",  # no date
            "2020-08-15T12:08:30.123456789Z",  # Z at the end
            "2020-08-15 12:08:30",  # invalid separator
            "2020-08-15T12:8:30",  # missing padding
            "2020-08-15T12:08",  # no seconds
            "",  # empty
            "2020-08-15T12:08:30.349𝟙239",  # non-ascii
        ],
    )
    def test_invalid(self, s):
        with pytest.raises(ValueError, match=re.escape(s)):
            LocalDateTime.parse_common_iso(s)

    @given(text())
    def test_fuzzing(self, s: str):
        with pytest.raises(ValueError, match=re.escape(repr(s))):
            LocalDateTime.parse_common_iso(s)


def test_equality():
    d = LocalDateTime(2020, 8, 15)
    different = LocalDateTime(2020, 8, 16)
    different2 = LocalDateTime(2020, 8, 15, nanosecond=1)
    same = LocalDateTime(2020, 8, 15)
    assert d == same
    assert d != different
    assert not d == different
    assert d != different2
    assert not d == different2
    assert not d != same

    assert hash(d) == hash(same)
    assert hash(d) != hash(different)
    assert hash(d) != hash(different2)

    assert d == AlwaysEqual()
    assert d != NeverEqual()
    assert not d == NeverEqual()
    assert not d != AlwaysEqual()

    assert d != 42  # type: ignore[comparison-overlap]
    assert not d == 42  # type: ignore[comparison-overlap]

    # Ambiguity in system timezone doesn't affect equality
    with system_tz_ams():
        assert LocalDateTime(
            2023, 10, 29, 2, 15
        ) == LocalDateTime.from_py_datetime(
            py_datetime(2023, 10, 29, 2, 15, fold=1)
        )


def test_repr():
    d = LocalDateTime(2020, 8, 15, 23, 12, 9, nanosecond=987_654)
    assert repr(d) == "LocalDateTime(2020-08-15 23:12:09.000987654)"
    # no fractional seconds
    assert (
        repr(LocalDateTime(2020, 8, 15, 23, 12))
        == "LocalDateTime(2020-08-15 23:12:00)"
    )


def test_format_common_iso():
    d = LocalDateTime(2020, 8, 15, 23, 12, 9, nanosecond=987_654)
    assert str(d) == "2020-08-15T23:12:09.000987654"
    assert d.format_common_iso() == "2020-08-15T23:12:09.000987654"


def test_comparison():
    d = LocalDateTime(2020, 8, 15, 23, 12, 9)
    later = LocalDateTime(2020, 8, 16, 0, 0, 0)
    later2 = d.replace(nanosecond=1)
    assert d < later
    assert d <= later
    assert later > d
    assert later >= d

    assert d < later2
    assert d <= later2
    assert later2 > d
    assert later2 >= d

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


def test_py_datetime():
    d = LocalDateTime(2020, 8, 15, 23, 12, 9, nanosecond=987_654_823)
    assert d.py_datetime() == py_datetime(2020, 8, 15, 23, 12, 9, 987_654)


def test_from_py_datetime():
    d = py_datetime(2020, 8, 15, 23, 12, 9, 987_654)
    assert LocalDateTime.from_py_datetime(d) == LocalDateTime(
        2020, 8, 15, 23, 12, 9, nanosecond=987_654_000
    )

    with pytest.raises(ValueError, match="utc"):
        LocalDateTime.from_py_datetime(
            py_datetime(2020, 8, 15, 23, 12, 9, 987_654, tzinfo=timezone.utc)
        )

    class MyDateTime(py_datetime):
        pass

    assert LocalDateTime.from_py_datetime(
        MyDateTime(2020, 8, 15, 23, 12, 9, 987_654)
    ) == LocalDateTime(2020, 8, 15, 23, 12, 9, nanosecond=987_654_000)


def test_min_max():
    assert LocalDateTime.MIN == LocalDateTime(1, 1, 1)
    assert LocalDateTime.MAX == LocalDateTime(
        9999, 12, 31, 23, 59, 59, nanosecond=999_999_999
    )


def test_replace():
    d = LocalDateTime(2020, 8, 15, 23, 12, 9, nanosecond=987_654)
    assert d.replace(year=2021) == LocalDateTime(
        2021, 8, 15, 23, 12, 9, nanosecond=987_654
    )
    assert d.replace(month=9) == LocalDateTime(
        2020, 9, 15, 23, 12, 9, nanosecond=987_654
    )
    assert d.replace(day=16) == LocalDateTime(
        2020, 8, 16, 23, 12, 9, nanosecond=987_654
    )
    assert d.replace(hour=0) == LocalDateTime(
        2020, 8, 15, 0, 12, 9, nanosecond=987_654
    )
    assert d.replace(minute=0) == LocalDateTime(
        2020, 8, 15, 23, 0, 9, nanosecond=987_654
    )
    assert d.replace(second=0) == LocalDateTime(
        2020, 8, 15, 23, 12, 0, nanosecond=987_654
    )
    assert d.replace(nanosecond=0) == LocalDateTime(
        2020, 8, 15, 23, 12, 9, nanosecond=0
    )

    with pytest.raises(ValueError, match="nano|time"):
        d.replace(nanosecond=1_000_000_000)

    with pytest.raises(ValueError, match="nano|time"):
        d.replace(nanosecond=-4)

    with pytest.raises(TypeError, match="tzinfo"):
        d.replace(tzinfo=timezone.utc)  # type: ignore[call-arg]


class TestShiftMethods:

    def test_valid(self):
        d = LocalDateTime(2020, 8, 15, 23, 12, 9, nanosecond=987_654)
        shifted = LocalDateTime(2020, 5, 27, 23, 12, 14, nanosecond=987_651)

        assert d.add(ignore_dst=True) == d

        assert (
            d.add(
                months=-3,
                days=10,
                hours=48,
                seconds=5,
                nanoseconds=-3,
                ignore_dst=True,
            )
            == shifted
        )

        # same result with deltas
        assert (
            d.add(hours(48) + seconds(5) + nanoseconds(-3), ignore_dst=True)
            .add(months(-3))
            .add(days(10))
        ) == shifted

        # same result with subtract()
        assert (
            d.subtract(
                months=3,
                days=-10,
                hours=-48,
                seconds=-5,
                nanoseconds=3,
                ignore_dst=True,
            )
            == shifted
        )

        # same result with deltas
        assert (
            d.subtract(
                hours(-48) + seconds(-5) + nanoseconds(3), ignore_dst=True
            )
            .subtract(months(3))
            .subtract(days(-10))
        ) == shifted

        # date units don't require ignore_dst
        assert d.subtract(months=3) == d.add(months=-3)

    def test_invalid(self):
        d = LocalDateTime(2020, 8, 15, 23, 12, 9, nanosecond=987_654)
        with pytest.raises((ValueError, OverflowError), match="range|year"):
            d.add(hours=24 * 365 * 8000, ignore_dst=True)

        with pytest.raises((ValueError, OverflowError), match="range|year"):
            d.add(hours=-24 * 365 * 3000, ignore_dst=True)

        with pytest.raises((TypeError, AttributeError)):
            d.add(4, ignore_dst=True)  # type: ignore[call-overload]

        # ignore_dst is required
        with pytest.raises(ImplicitlyIgnoringDST):
            d.add(hours=48, seconds=5)  # type: ignore[call-overload]

        # ignore_dst is required
        with pytest.raises(ImplicitlyIgnoringDST):
            d.add(hours(48))  # type: ignore[call-overload]

        # mixing args/kwargs
        with pytest.raises(TypeError):
            d.add(hours(48), seconds=5, ignore_dst=True)  # type: ignore[call-overload]

    @given(
        years=integers(),
        months=integers(),
        days=integers(),
        hours=floats(),
        minutes=floats(),
        seconds=floats(),
        milliseconds=floats(),
        microseconds=floats(),
        nanoseconds=integers(),
    )
    def test_fuzzing(self, **kwargs):
        d = LocalDateTime(2020, 8, 15, 23, 12, 9, nanosecond=987_654_321)
        try:
            d.add(**kwargs, ignore_dst=True)
        except (ValueError, OverflowError):
            pass


class TestShiftOperators:

    def test_calendar_units(self):
        d = LocalDateTime(2020, 8, 15, 23, 12, 9, nanosecond=987_654)
        shifted = d.replace(year=2021, day=19)
        assert d + (years(1) + weeks(1) + days(-3)) == shifted

        # same results with subtraction
        assert d - (years(-1) + weeks(-1) + days(3)) == shifted

        with pytest.raises((ValueError, OverflowError), match="range|year"):
            d + years(8_000)

        with pytest.raises((ValueError, OverflowError), match="range|year"):
            d + days(366 * 8_000)

        with pytest.raises((ValueError, OverflowError), match="range|year"):
            d + years(-3_000)

        with pytest.raises((ValueError, OverflowError), match="range|year"):
            d + days(-366 * 8_000)

    def test_invalid(self):
        d = LocalDateTime(2020, 8, 15, 23, 12, 9, nanosecond=987_654)
        with pytest.raises(TypeError, match="unsupported operand type"):
            d + 42  # type: ignore[operator]
        with pytest.raises(TypeError, match="unsupported operand type"):
            42 + d  # type: ignore[operator]
        with pytest.raises(TypeError, match="unsupported operand type"):
            seconds(4) + d  # type: ignore[operator]

        with pytest.raises(ImplicitlyIgnoringDST, match="add"):
            d + hours(24)  # type: ignore[operator]

        with pytest.raises(ImplicitlyIgnoringDST, match="add"):
            d - (hours(24) + months(3))  # type: ignore[operator]


class TestDifference:
    def test_same(self):
        d = LocalDateTime(2020, 8, 15, 23, 12, 9, nanosecond=987_654_000)
        other = LocalDateTime(2020, 8, 14, 23, 12, 4, nanosecond=987_654_321)
        assert d.difference(d, ignore_dst=True) == hours(0)
        assert d.difference(other, ignore_dst=True) == hours(24) + seconds(
            5
        ) - nanoseconds(321)

    def test_invalid(self):
        d = LocalDateTime(2020, 8, 15, 23, 12, 9, nanosecond=987_654)
        with pytest.raises(ImplicitlyIgnoringDST):
            d.difference(d)  # type: ignore[call-arg]

        with pytest.raises(ImplicitlyIgnoringDST):
            d - d  # type: ignore[operator]

        with pytest.raises(TypeError):
            d - 43  # type: ignore[operator]


def test_replace_date():
    d = LocalDateTime(2020, 8, 15, 3, 12, 9)
    assert d.replace_date(Date(1996, 2, 19)) == LocalDateTime(
        1996, 2, 19, 3, 12, 9
    )
    with pytest.raises((TypeError, AttributeError)):
        d.replace_date(42)  # type: ignore[arg-type]


def test_replace_time():
    d = LocalDateTime(2020, 8, 15, 3, 12, 9)
    assert d.replace_time(Time(1, 2, 3)) == LocalDateTime(2020, 8, 15, 1, 2, 3)
    with pytest.raises((TypeError, AttributeError)):
        d.replace_time(42)  # type: ignore[arg-type]


def test_pickle():
    d = LocalDateTime(2020, 8, 15, 23, 12, 9, nanosecond=987_654)
    dumped = pickle.dumps(d)
    assert len(dumped) <= len(pickle.dumps(d.py_datetime())) + 10
    assert pickle.loads(pickle.dumps(d)) == d


def test_old_pickle_data_remains_unpicklable():
    # Don't update this value -- the whole idea is that it's a pickle at
    # a specific version of the library.
    dumped = (
        b"\x80\x04\x95/\x00\x00\x00\x00\x00\x00\x00\x8c\x08whenever\x94\x8c\x0c_unp"
        b"kl_local\x94\x93\x94C\x0b\xe4\x07\x08\x0f\x17\x0c\t\x06\x12\x0f\x00"
        b"\x94\x85\x94R\x94."
    )
    assert pickle.loads(dumped) == LocalDateTime(
        2020, 8, 15, 23, 12, 9, nanosecond=987_654
    )


def test_strptime():
    assert LocalDateTime.strptime(
        "2020-08-15 23:12", "%Y-%m-%d %H:%M"
    ) == LocalDateTime(2020, 8, 15, 23, 12)


def test_strptime_invalid():
    with pytest.raises(ValueError):
        LocalDateTime.strptime(
            "2020-08-15 23:12:09+0500", "%Y-%m-%d %H:%M:%S%z"
        )

    with pytest.raises(TypeError):
        LocalDateTime.strptime("2020-08-15 23:12:09+0500")  # type: ignore[call-arg]


def test_cannot_subclass():
    with pytest.raises(TypeError):

        class Subclass(LocalDateTime):  # type: ignore[misc]
            pass
