import pickle
import weakref
from datetime import datetime as py_datetime
from datetime import timedelta, timezone, tzinfo

import pytest
from hypothesis import given
from hypothesis.strategies import text
from pytest import approx

from whenever import (
    AwareDateTime,
    InvalidFormat,
    LocalDateTime,
    NaiveDateTime,
    OffsetDateTime,
    UTCDateTime,
    ZonedDateTime,
    hours,
    minutes,
)

from .common import (
    AlwaysEqual,
    AlwaysLarger,
    AlwaysSmaller,
    NeverEqual,
    ZoneInfoNotFoundError,
    local_ams_tz,
    local_nyc_tz,
)


class TestInit:
    def test_init_and_attributes(self):
        d = OffsetDateTime(2020, 8, 15, 5, 12, 30, 450, offset=hours(5))
        assert d.year == 2020
        assert d.month == 8
        assert d.day == 15
        assert d.hour == 5
        assert d.minute == 12
        assert d.second == 30
        assert d.microsecond == 450
        assert d.offset == hours(5)

    def test_offset_missing(self):
        with pytest.raises(TypeError, match="offset"):
            OffsetDateTime(2020, 8, 15, 5, 12, 30, 450)  # type: ignore[call-arg]

    def test_invalid_offset(self):
        with pytest.raises(ValueError, match="offset"):
            OffsetDateTime(2020, 8, 15, 5, 12, offset=hours(34))

    def test_init_optionality(self):
        assert (
            OffsetDateTime(2020, 8, 15, 12, offset=hours(5))
            == OffsetDateTime(2020, 8, 15, 12, 0, offset=hours(5))
            == OffsetDateTime(2020, 8, 15, 12, 0, 0, offset=hours(5))
        )

    def test_kwargs(self):
        d = OffsetDateTime(
            year=2020,
            month=8,
            day=15,
            hour=5,
            minute=12,
            second=30,
            offset=hours(5),
        )
        assert d == OffsetDateTime(2020, 8, 15, 5, 12, 30, 0, offset=hours(5))


def test_immutable():
    d = OffsetDateTime(2020, 8, 15, offset=minutes(5))
    with pytest.raises(AttributeError):
        d.year = 2021  # type: ignore[misc]


@pytest.mark.parametrize(
    "d, expected",
    [
        (
            OffsetDateTime(2020, 8, 15, 23, 12, 9, offset=hours(5)),
            "2020-08-15T23:12:09+05:00",
        ),
        (
            OffsetDateTime(2020, 8, 15, 23, 12, 9, 987_654, offset=hours(5)),
            "2020-08-15T23:12:09.987654+05:00",
        ),
    ],
)
def test_canonical_str(d: OffsetDateTime, expected: str):
    assert str(d) == expected
    assert d.canonical_str() == expected


class TestFromStr:
    def test_valid(self):
        assert OffsetDateTime.from_canonical_str(
            "2020-08-15T12:08:30+05:00"
        ).exact_eq(OffsetDateTime(2020, 8, 15, 12, 8, 30, offset=hours(5)))

    def test_valid_offset_with_seconds(self):
        assert OffsetDateTime.from_canonical_str(
            "2020-08-15T12:08:30+05:00:33"
        ).exact_eq(
            OffsetDateTime(
                2020, 8, 15, 12, 8, 30, offset=timedelta(hours=5, seconds=33)
            )
        )

    def test_valid_three_fractions(self):
        assert OffsetDateTime.from_canonical_str(
            "2020-08-15T12:08:30.349+05:00:33"
        ).exact_eq(
            OffsetDateTime(
                2020,
                8,
                15,
                12,
                8,
                30,
                349_000,
                offset=timedelta(hours=5, seconds=33),
            )
        )

    def test_valid_six_fractions(self):
        assert OffsetDateTime.from_canonical_str(
            "2020-08-15T12:08:30.349123+05:00:33.987654"
        ).exact_eq(
            OffsetDateTime(
                2020,
                8,
                15,
                12,
                8,
                30,
                349_123,
                offset=timedelta(hours=5, seconds=33, microseconds=987_654),
            )
        )

    def test_single_space_instead_of_T(self):
        assert OffsetDateTime.from_canonical_str(
            "2020-08-15 12:08:30-04:00"
        ).exact_eq(OffsetDateTime(2020, 8, 15, 12, 8, 30, offset=hours(-4)))

    def test_unpadded(self):
        with pytest.raises(InvalidFormat):
            OffsetDateTime.from_canonical_str("2020-8-15T12:8:30+05:00")

    def test_overly_precise_fraction(self):
        with pytest.raises(InvalidFormat):
            OffsetDateTime.from_canonical_str(
                "2020-08-15T12:08:30.123456789123+05:00"
            )

    def test_invalid_offset(self):
        with pytest.raises(ValueError):
            OffsetDateTime.from_canonical_str("2020-08-15T12:08:30-99:00")

    def test_no_offset(self):
        with pytest.raises(InvalidFormat):
            OffsetDateTime.from_canonical_str("2020-08-15T12:08:30")

    def test_no_seconds(self):
        with pytest.raises(InvalidFormat):
            OffsetDateTime.from_canonical_str("2020-08-15T12:08-05:00")

    def test_empty(self):
        with pytest.raises(InvalidFormat):
            OffsetDateTime.from_canonical_str("")

    def test_garbage(self):
        with pytest.raises(InvalidFormat):
            OffsetDateTime.from_canonical_str("garbage")

    @given(text())
    def test_fuzzing(self, s: str):
        with pytest.raises(InvalidFormat):
            OffsetDateTime.from_canonical_str(s)


def test_exact_equality():
    d = OffsetDateTime(2020, 8, 15, 12, offset=hours(5))
    same = d.replace()
    utc_same = d.replace(hour=13, offset=hours(6))
    different = d.replace(offset=hours(6))
    assert d.exact_eq(same)
    assert not d.exact_eq(utc_same)
    assert not d.exact_eq(different)


class TestEquality:
    def test_same_exact(self):
        d = OffsetDateTime(2020, 8, 15, 12, offset=hours(5))
        same = d.replace()
        assert d == same
        assert not d != same
        assert hash(d) == hash(same)

    def test_different(self):
        d = OffsetDateTime(2020, 8, 15, 12, offset=hours(5))
        different = d.replace(offset=hours(6))
        assert d != different
        assert not d == different
        assert hash(d) != hash(different)

    def test_same_time(self):
        d = OffsetDateTime(2020, 8, 15, 12, offset=hours(5))
        same_time = d.replace(hour=11, offset=hours(4))
        assert d == same_time
        assert not d != same_time
        assert hash(d) == hash(same_time)

    @local_nyc_tz()
    def test_other_aware(self):
        d: AwareDateTime = OffsetDateTime(2020, 8, 15, 12, offset=hours(5))
        assert d == d.as_utc()
        assert hash(d) == hash(d.as_utc())
        assert d != d.as_utc().replace(hour=10)

        assert d == d.as_local()
        assert d != d.as_local().replace(hour=8)

        assert d == d.as_zoned("America/New_York")
        assert hash(d) == hash(d.as_zoned("America/New_York"))
        assert d != d.as_zoned("America/New_York").replace(hour=12)

    def test_not_implemented(self):
        d = OffsetDateTime(2020, 8, 15, 12, offset=hours(5))
        assert d == AlwaysEqual()
        assert d != NeverEqual()
        assert not d == NeverEqual()
        assert not d != AlwaysEqual()
        assert d != 42  # type: ignore[comparison-overlap]
        assert not d == 42  # type: ignore[comparison-overlap]


def test_timestamp():
    assert OffsetDateTime(1970, 1, 1, 3, offset=hours(3)).timestamp() == 0
    assert OffsetDateTime(
        2020, 8, 15, 8, 8, 30, 45, offset=hours(-4)
    ).timestamp() == approx(1_597_493_310.000045, abs=1e-6)


def test_from_timestamp():
    assert OffsetDateTime.from_timestamp(0, offset=hours(3)).exact_eq(
        OffsetDateTime(1970, 1, 1, 3, offset=hours(3))
    )
    assert OffsetDateTime.from_timestamp(
        1_597_493_310, offset=hours(-2)
    ).exact_eq(OffsetDateTime(2020, 8, 15, 10, 8, 30, offset=hours(-2)))
    with pytest.raises((OSError, OverflowError)):
        OffsetDateTime.from_timestamp(
            1_000_000_000_000_000_000, offset=hours(0)
        )


def test_repr():
    d = OffsetDateTime(
        2020, 8, 15, 23, 12, 9, 987_654, offset=timedelta(hours=5, minutes=22)
    )
    assert (
        repr(d) == "whenever.OffsetDateTime(2020-08-15T23:12:09.987654+05:22)"
    )
    assert (
        repr(OffsetDateTime(2020, 8, 15, 23, 12, offset=hours(0)))
        == "whenever.OffsetDateTime(2020-08-15T23:12:00+00:00)"
    )


class TestComparison:
    def test_offset(self):
        d = OffsetDateTime(2020, 8, 15, 12, 30, offset=hours(5))
        later = d.replace(hour=13)
        assert d < later
        assert d <= later
        assert later > d
        assert later >= d

    def test_utc(self):
        d = OffsetDateTime(2020, 8, 15, 12, 30, offset=hours(5))
        utc_eq = d.as_utc()
        utc_gt = utc_eq.replace(minute=31)
        utc_lt = utc_eq.replace(minute=29)

        assert d >= utc_eq
        assert d <= utc_eq
        assert not d > utc_eq
        assert not d < utc_eq

        assert d < utc_gt
        assert d <= utc_gt
        assert not d > utc_gt
        assert not d >= utc_gt

        assert d > utc_lt
        assert d >= utc_lt
        assert not d < utc_lt
        assert not d <= utc_lt

    def test_zoned(self):
        d = OffsetDateTime(2020, 8, 15, 12, 30, offset=hours(5))
        zoned_eq = d.as_zoned("America/New_York")
        zoned_gt = zoned_eq.replace(minute=31)
        zoned_lt = zoned_eq.replace(minute=29)

        assert d >= zoned_eq
        assert d <= zoned_eq
        assert not d > zoned_eq
        assert not d < zoned_eq

        assert d < zoned_gt
        assert d <= zoned_gt
        assert not d > zoned_gt
        assert not d >= zoned_gt

        assert d > zoned_lt
        assert d >= zoned_lt
        assert not d < zoned_lt
        assert not d <= zoned_lt

    @local_nyc_tz()
    def test_local(self):
        d = OffsetDateTime(2020, 8, 15, 12, 30, offset=hours(5))
        local_eq = d.as_local()
        local_gt = local_eq.replace(minute=31)
        local_lt = local_eq.replace(minute=29)

        assert d >= local_eq
        assert d <= local_eq
        assert not d > local_eq
        assert not d < local_eq

        assert d < local_gt
        assert d <= local_gt
        assert not d > local_gt
        assert not d >= local_gt

        assert d > local_lt
        assert d >= local_lt
        assert not d < local_lt
        assert not d <= local_lt

    def test_not_implemented(self):
        d = OffsetDateTime(2020, 8, 15, 12, 30, offset=hours(5))

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


def test_py():
    d = OffsetDateTime(2020, 8, 15, 23, 12, 9, 987_654, offset=hours(5))
    assert d.py == py_datetime(
        2020, 8, 15, 23, 12, 9, 987_654, tzinfo=timezone(hours(5))
    )


def test_from_py():
    d = py_datetime(2020, 8, 15, 23, 12, 9, 987_654, tzinfo=timezone(hours(2)))
    assert OffsetDateTime.from_py(d).exact_eq(
        OffsetDateTime(2020, 8, 15, 23, 12, 9, 987_654, offset=hours(2))
    )

    class SomeTzinfo(tzinfo):
        pass

    d2 = d.replace(tzinfo=SomeTzinfo())  # type: ignore[abstract]
    with pytest.raises(ValueError, match="SomeTzinfo"):
        OffsetDateTime.from_py(d2)


def test_now():
    now = OffsetDateTime.now(hours(5))
    assert now.offset == hours(5)
    py_now = py_datetime.now(timezone.utc)
    assert py_now - now.py < timedelta(seconds=1)


def test_weakref():
    d = OffsetDateTime(2020, 8, 15, offset=hours(5))
    ref = weakref.ref(d)
    assert ref() == d


def test_passthrough_datetime_attrs():
    d = OffsetDateTime(2020, 8, 15, 12, 43, offset=hours(5))
    assert d.resolution == py_datetime.resolution
    assert d.weekday() == d.py.weekday()
    assert d.date() == d.py.date()
    time = d.time()
    assert time.tzinfo is None
    assert time == d.py.time()
    assert d.tzinfo == d.py.tzinfo == timezone(hours(5))


def test_replace():
    d = OffsetDateTime(2020, 8, 15, 23, 12, 9, 987_654, offset=hours(5))
    assert d.replace(year=2021).exact_eq(
        OffsetDateTime(2021, 8, 15, 23, 12, 9, 987_654, offset=hours(5))
    )
    assert d.replace(month=9).exact_eq(
        OffsetDateTime(2020, 9, 15, 23, 12, 9, 987_654, offset=hours(5))
    )
    assert d.replace(day=16).exact_eq(
        OffsetDateTime(2020, 8, 16, 23, 12, 9, 987_654, offset=hours(5))
    )
    assert d.replace(hour=0).exact_eq(
        OffsetDateTime(2020, 8, 15, 0, 12, 9, 987_654, offset=hours(5))
    )
    assert d.replace(minute=0).exact_eq(
        OffsetDateTime(2020, 8, 15, 23, 0, 9, 987_654, offset=hours(5))
    )
    assert d.replace(second=0).exact_eq(
        OffsetDateTime(2020, 8, 15, 23, 12, 0, 987_654, offset=hours(5))
    )
    assert d.replace(microsecond=0).exact_eq(
        OffsetDateTime(2020, 8, 15, 23, 12, 9, 0, offset=hours(5))
    )
    assert d.replace(offset=hours(6)).exact_eq(
        OffsetDateTime(2020, 8, 15, 23, 12, 9, 987_654, offset=hours(6))
    )

    with pytest.raises(TypeError, match="tzinfo"):
        d.replace(tzinfo=timezone.utc)  # type: ignore[call-arg]


def test_add_not_allowed():
    d = OffsetDateTime(2020, 8, 15, 23, 12, 9, 987_654, offset=hours(5))
    with pytest.raises(TypeError, match="unsupported operand type"):
        d + hours(4)  # type: ignore[operator]

    with pytest.raises(TypeError, match="unsupported operand type"):
        d + 32  # type: ignore[operator]


class TestSubtract:
    def test_invalid(self):
        d = OffsetDateTime(2020, 8, 15, 23, 12, 9, 987_654, offset=hours(5))
        with pytest.raises(TypeError, match="unsupported operand type"):
            d - hours(2)  # type: ignore[operator]
        with pytest.raises(TypeError, match="unsupported operand type"):
            d - 42  # type: ignore[operator]

    def test_offset(self):
        d = OffsetDateTime(2020, 8, 15, 23, 12, 9, 987_654, offset=hours(5))
        other = OffsetDateTime(
            2020, 8, 14, 23, 12, 4, 987_654, offset=hours(-3)
        )
        assert d - other == timedelta(hours=16, seconds=5)

    def test_utc(self):
        d = OffsetDateTime(2020, 8, 15, 20, offset=hours(5))
        assert d - UTCDateTime(2020, 8, 15, 20) == -timedelta(hours=5)

    def test_zoned(self):
        d = OffsetDateTime(2023, 10, 29, 6, offset=hours(2))
        assert d - ZonedDateTime(
            2023, 10, 29, 3, tz="Europe/Paris"
        ) == timedelta(hours=2)
        assert d - ZonedDateTime(
            2023, 10, 29, 2, tz="Europe/Paris", disambiguate="later"
        ) == timedelta(hours=3)
        assert d - ZonedDateTime(
            2023, 10, 29, 2, tz="Europe/Paris", disambiguate="earlier"
        ) == timedelta(hours=4)
        assert d - ZonedDateTime(
            2023, 10, 29, 1, tz="Europe/Paris"
        ) == timedelta(hours=5)

    @local_ams_tz()
    def test_local(self):
        d = OffsetDateTime(2023, 10, 29, 6, offset=hours(2))
        assert d - LocalDateTime(
            2023, 10, 29, 3, disambiguate="later"
        ) == timedelta(hours=2)
        assert d - LocalDateTime(
            2023, 10, 29, 2, disambiguate="later"
        ) == timedelta(hours=3)
        assert d - LocalDateTime(
            2023, 10, 29, 2, disambiguate="earlier"
        ) == timedelta(hours=4)
        assert d - LocalDateTime(2023, 10, 29, 1) == timedelta(hours=5)


def test_pickle():
    d = OffsetDateTime(2020, 8, 15, 23, 12, 9, 987_654, offset=hours(3))
    dumped = pickle.dumps(d)
    assert len(dumped) <= len(pickle.dumps(d.py)) + 10
    assert pickle.loads(pickle.dumps(d)) == d


def test_to_utc():
    d = OffsetDateTime(2020, 8, 15, 23, 12, 9, 987_654, offset=hours(3))
    assert d.as_utc() == UTCDateTime(2020, 8, 15, 20, 12, 9, 987_654)


def test_to_offset():
    d = OffsetDateTime(2020, 8, 15, 23, 12, 9, 987_654, offset=hours(3))
    assert d.as_offset(hours(5)).exact_eq(
        OffsetDateTime(2020, 8, 16, 1, 12, 9, 987_654, offset=hours(5))
    )
    assert d.as_offset() is d


def test_to_zoned():
    d = OffsetDateTime(2020, 8, 15, 20, 12, 9, 987_654, offset=hours(3))
    assert d.as_zoned("America/New_York").exact_eq(
        ZonedDateTime(2020, 8, 15, 13, 12, 9, 987_654, tz="America/New_York")
    )
    with pytest.raises(ZoneInfoNotFoundError):
        d.as_zoned("America/Not_A_Real_Zone")


@local_nyc_tz()
def test_to_local():
    d = OffsetDateTime(2020, 8, 15, 20, 12, 9, 987_654, offset=hours(3))
    assert d.as_local().exact_eq(
        LocalDateTime(2020, 8, 15, 13, 12, 9, 987_654)
    )


def test_naive():
    d = OffsetDateTime(2020, 8, 15, 20, offset=hours(3))
    assert d.naive() == NaiveDateTime(2020, 8, 15, 20)


def test_from_naive():
    d = NaiveDateTime(2020, 8, 15, 20)
    assert OffsetDateTime.from_naive(d, hours(3)).exact_eq(
        OffsetDateTime(2020, 8, 15, 20, offset=hours(3))
    )


@pytest.mark.parametrize(
    "string, fmt, expected",
    [
        (
            "2020-08-15 23:12+0315",
            "%Y-%m-%d %H:%M%z",
            OffsetDateTime(
                2020, 8, 15, 23, 12, offset=timedelta(hours=3, minutes=15)
            ),
        ),
        (
            "2020-08-15 23:12:09+0550",
            "%Y-%m-%d %H:%M:%S%z",
            OffsetDateTime(
                2020, 8, 15, 23, 12, 9, offset=timedelta(hours=5, minutes=50)
            ),
        ),
        (
            "2020-08-15 23:12:09Z",
            "%Y-%m-%d %H:%M:%S%z",
            OffsetDateTime(2020, 8, 15, 23, 12, 9, offset=timedelta()),
        ),
    ],
)
def test_strptime(string, fmt, expected):
    assert OffsetDateTime.strptime(string, fmt) == expected


def test_strptime_invalid():
    with pytest.raises(ValueError):
        OffsetDateTime.strptime("2020-08-15 23:12:09", "%Y-%m-%d %H:%M:%S")
