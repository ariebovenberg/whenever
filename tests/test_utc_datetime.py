import pickle
import weakref
from copy import copy, deepcopy
from datetime import datetime as py_datetime, timedelta, timezone

import pytest
from freezegun import freeze_time
from hypothesis import given
from hypothesis.strategies import text
from pytest import approx

from whenever import (
    AwareDateTime,
    Date,
    InvalidFormat,
    LocalSystemDateTime,
    NaiveDateTime,
    OffsetDateTime,
    Time,
    UTCDateTime,
    ZonedDateTime,
    days,
    hours,
    minutes,
    seconds,
    years,
)

from .common import (
    AlwaysEqual,
    AlwaysLarger,
    AlwaysSmaller,
    NeverEqual,
    local_ams_tz,
    local_nyc_tz,
)


class TestInit:
    def test_basic(self):
        d = UTCDateTime(2020, 8, 15, 5, 12, 30, 450)
        assert d.year == 2020
        assert d.month == 8
        assert d.day == 15
        assert d.hour == 5
        assert d.minute == 12
        assert d.second == 30
        assert d.microsecond == 450
        assert d.offset == hours(0)

    def test_defaults(self):
        assert (
            UTCDateTime(2020, 8, 15, 12)
            == UTCDateTime(2020, 8, 15, 12, 0)
            == UTCDateTime(2020, 8, 15, 12, 0, 0)
            == UTCDateTime(2020, 8, 15, 12, 0, 0, 0)
        )

    def test_invalid(self):
        with pytest.raises(ValueError, match="microsecond must"):
            UTCDateTime(2020, 8, 15, 12, 8, 30, 1_000_000)

    def test_kwargs(self):
        d = UTCDateTime(
            year=2020, month=8, day=15, hour=5, minute=12, second=30
        )
        assert d == UTCDateTime(2020, 8, 15, 5, 12, 30)


def test_immutable():
    d = UTCDateTime(2020, 8, 15)
    with pytest.raises(AttributeError):
        d.year = 2021  # type: ignore[misc]


def test_components():
    d = UTCDateTime(2020, 8, 15, 23, 12, 9, 987_654)
    assert d.date() == Date(2020, 8, 15)
    assert d.time() == Time(23, 12, 9, 987_654)


class TestCanonicalFormat:

    @pytest.mark.parametrize(
        "d, expected",
        [
            (
                UTCDateTime(2020, 8, 15, 23, 12, 9, 987_654),
                "2020-08-15T23:12:09.987654Z",
            ),
            (UTCDateTime(2020, 8, 15, 23, 12, 9), "2020-08-15T23:12:09Z"),
        ],
    )
    def test_canonical_format(self, d: UTCDateTime, expected: str):
        assert str(d) == expected.replace("T", " ")
        assert d.canonical_format() == expected

    def test_seperator(self):
        d = UTCDateTime(2020, 8, 15, 23, 12, 9, 987_654)
        assert d.canonical_format(sep=" ") == "2020-08-15 23:12:09.987654Z"


class TestFromCanonicalFormat:
    def test_valid(self):
        assert UTCDateTime.from_canonical_format(
            "2020-08-15T12:08:30Z"
        ) == UTCDateTime(2020, 8, 15, 12, 8, 30)

    def test_valid_three_fractions(self):
        assert UTCDateTime.from_canonical_format(
            "2020-08-15T12:08:30.349Z"
        ) == UTCDateTime(2020, 8, 15, 12, 8, 30, 349_000)

    def test_valid_six_fractions(self):
        assert UTCDateTime.from_canonical_format(
            "2020-08-15T12:08:30.349123Z"
        ) == UTCDateTime(2020, 8, 15, 12, 8, 30, 349_123)

    def test_single_space_instead_of_T(self):
        assert UTCDateTime.from_canonical_format(
            "2020-08-15 12:08:30Z"
        ) == UTCDateTime(2020, 8, 15, 12, 8, 30)

    def test_unpadded(self):
        with pytest.raises(InvalidFormat):
            UTCDateTime.from_canonical_format("2020-8-15T12:8:30Z")

    def test_overly_precise_fraction(self):
        with pytest.raises(InvalidFormat):
            UTCDateTime.from_canonical_format(
                "2020-08-15T12:08:30.123456789123Z"
            )

    def test_invalid_lowercase_z(self):
        with pytest.raises(InvalidFormat):
            UTCDateTime.from_canonical_format("2020-08-15T12:08:30z")

    def test_no_trailing_z(self):
        with pytest.raises(InvalidFormat):
            UTCDateTime.from_canonical_format("2020-08-15T12:08:30")

    def test_no_seconds(self):
        with pytest.raises(InvalidFormat):
            UTCDateTime.from_canonical_format("2020-08-15T12:08Z")

    def test_empty(self):
        with pytest.raises(InvalidFormat):
            UTCDateTime.from_canonical_format("")

    def test_garbage(self):
        with pytest.raises(InvalidFormat):
            UTCDateTime.from_canonical_format("garbage")

    @given(text())
    def test_fuzzing(self, s: str):
        with pytest.raises(InvalidFormat):
            UTCDateTime.from_canonical_format(s)


class TestEquality:
    def test_same(self):
        d = UTCDateTime(2020, 8, 15)
        same = d.replace()
        assert d == same
        assert not d != same
        assert hash(d) == hash(same)

    def test_different(self):
        d = UTCDateTime(2020, 8, 15)
        different = d.replace(year=2021)
        assert d != different
        assert not d == different
        assert hash(d) != hash(different)

    def test_notimplemented(self):
        d = UTCDateTime(2020, 8, 15)
        assert d == AlwaysEqual()
        assert d != NeverEqual()
        assert not d == NeverEqual()
        assert not d != AlwaysEqual()

    def test_invalid(self):
        d = UTCDateTime(2020, 8, 15)
        d == 42  # type: ignore[comparison-overlap]

    @local_nyc_tz()
    def test_other_aware_types(self):
        d: AwareDateTime = UTCDateTime(2020, 8, 15)
        assert d == d.as_local()
        assert d == d.as_local().replace(disambiguate="later")
        assert d == d.as_offset()
        assert d == d.as_offset(hours(3))
        assert d == d.as_zoned("Europe/Paris")

        assert d != d.as_local().replace(year=2021)
        assert d != d.as_offset(hours(1)).replace(year=2021)
        assert d != d.as_zoned("Europe/London").replace(year=2021)


def test_timestamp():
    assert UTCDateTime(1970, 1, 1).timestamp() == 0
    assert UTCDateTime(2020, 8, 15, 12, 8, 30, 45).timestamp() == approx(
        1_597_493_310.000045, abs=1e-6
    )


def test_from_timestamp():
    assert UTCDateTime.from_timestamp(0) == UTCDateTime(1970, 1, 1)
    assert UTCDateTime.from_timestamp(1_597_493_310) == UTCDateTime(
        2020, 8, 15, 12, 8, 30
    )
    with pytest.raises((OSError, OverflowError)):
        UTCDateTime.from_timestamp(1_000_000_000_000_000_000)


def test_repr():
    d = UTCDateTime(2020, 8, 15, 23, 12, 9, 987_654)
    assert repr(d) == "UTCDateTime(2020-08-15 23:12:09.987654Z)"
    assert (
        repr(UTCDateTime(2020, 8, 15, 23, 12))
        == "UTCDateTime(2020-08-15 23:12:00Z)"
    )


class TestComparison:
    def test_utc(self):
        d = UTCDateTime.from_canonical_format("2020-08-15T23:12:09Z")
        later = UTCDateTime.from_canonical_format("2020-08-16T00:00:00Z")
        assert d < later
        assert d <= later
        assert later > d
        assert later >= d

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

    def test_offset(self):
        d = UTCDateTime(2020, 8, 15, 12, 30)

        offset_eq = d.as_offset(hours(4))
        offset_gt = offset_eq.replace(minute=31)
        offset_lt = offset_eq.replace(minute=29)
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
        d = UTCDateTime(2020, 8, 15, 12, 30)

        zoned_eq = d.as_zoned("America/New_York")
        zoned_gt = zoned_eq.replace(minute=31)
        zoned_lt = zoned_eq.replace(minute=29)
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

    @local_nyc_tz()
    def test_local(self):
        d = UTCDateTime(2020, 8, 15, 12, 30)

        local_eq = d.as_local()
        local_gt = local_eq.replace(minute=31)
        local_lt = local_eq.replace(minute=29)
        assert d >= local_eq
        assert d <= local_eq
        assert not d > local_eq
        assert not d < local_eq

        assert d > local_lt
        assert d >= local_lt
        assert not d < local_lt
        assert not d <= local_lt

        assert d < local_gt
        assert d <= local_gt
        assert not d > local_gt
        assert not d >= local_gt

    def test_notimplemented(self):
        d = UTCDateTime(2020, 8, 15)
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
    d = UTCDateTime(2020, 8, 15, 23, 12, 9, 987_654)
    assert d.py_datetime() == py_datetime(
        2020, 8, 15, 23, 12, 9, 987_654, tzinfo=timezone.utc
    )


def test_from_py_datetime():
    d = py_datetime(2020, 8, 15, 23, 12, 9, 987_654, tzinfo=timezone.utc)
    assert UTCDateTime.from_py_datetime(d) == UTCDateTime(
        2020, 8, 15, 23, 12, 9, 987_654
    )

    with pytest.raises(ValueError, match="UTC.*timedelta"):
        UTCDateTime.from_py_datetime(
            d.replace(tzinfo=timezone(-timedelta(hours=4)))
        )


def test_now():
    now = UTCDateTime.now()
    py_now = py_datetime.now(timezone.utc)
    assert py_now - now.py_datetime() < timedelta(seconds=1)


@freeze_time("2020-08-15T23:12:09Z")
def test_now_works_with_freezegun():
    assert UTCDateTime.now() == UTCDateTime(2020, 8, 15, 23, 12, 9)


def test_weakref():
    d = UTCDateTime(2020, 8, 15)
    ref = weakref.ref(d)
    assert ref() == d


def test_min_max():
    assert UTCDateTime.MIN == UTCDateTime(1, 1, 1)
    assert UTCDateTime.MAX == UTCDateTime(9999, 12, 31, 23, 59, 59, 999_999)


def test_replace():
    d = UTCDateTime(2020, 8, 15, 23, 12, 9, 987_654)
    assert d.replace(year=2021) == UTCDateTime(2021, 8, 15, 23, 12, 9, 987_654)
    assert d.replace(month=9) == UTCDateTime(2020, 9, 15, 23, 12, 9, 987_654)
    assert d.replace(day=16) == UTCDateTime(2020, 8, 16, 23, 12, 9, 987_654)
    assert d.replace(hour=0) == UTCDateTime(2020, 8, 15, 0, 12, 9, 987_654)
    assert d.replace(minute=0) == UTCDateTime(2020, 8, 15, 23, 0, 9, 987_654)
    assert d.replace(second=0) == UTCDateTime(2020, 8, 15, 23, 12, 0, 987_654)
    assert d.replace(microsecond=0) == UTCDateTime(2020, 8, 15, 23, 12, 9, 0)

    with pytest.raises(TypeError, match="tzinfo"):
        d.replace(tzinfo=timezone.utc)  # type: ignore[call-arg]


def test_with_date():
    d = UTCDateTime(2020, 8, 15, 23, 12, 9, 987_654)
    assert d.with_date(Date(2019, 1, 1)) == UTCDateTime(
        2019, 1, 1, 23, 12, 9, 987_654
    )


def test_add():
    d = UTCDateTime(2020, 8, 15, 23, 12, 9, 987_654)
    assert d.add(hours=24, seconds=5) == UTCDateTime(
        2020, 8, 16, 23, 12, 14, 987_654
    )
    assert d.add(years=1, days=4, minutes=-4) == UTCDateTime(
        2021, 8, 19, 23, 8, 9, 987_654
    )


class TestAddOperator:
    def test_time_units(self):
        d = UTCDateTime(2020, 8, 15, 23, 12, 9, 987_654)
        assert d + hours(24) + seconds(5) == UTCDateTime(
            2020, 8, 16, 23, 12, 14, 987_654
        )

    def test_date_units(self):
        d = UTCDateTime(2020, 8, 15, 23, 30)
        assert d + years(1) + days(4) - minutes(4) == UTCDateTime(
            2021, 8, 19, 23, 26
        )

    def test_invalid(self):
        d = UTCDateTime(2020, 8, 15, 23, 12, 9, 987_654)
        with pytest.raises(TypeError, match="unsupported operand type"):
            d + 42  # type: ignore[operator]


def test_subtract():
    d = UTCDateTime(2020, 8, 15, 23, 12, 9, 987_654)
    assert d.subtract(hours=24, seconds=5) == UTCDateTime(
        2020, 8, 14, 23, 12, 4, 987_654
    )
    assert d.subtract(years=1, days=4, minutes=-4) == UTCDateTime(
        2019, 8, 11, 23, 16, 9, 987_654
    )


class TestSubtractOperator:
    def test_time_units(self):
        d = UTCDateTime(2020, 8, 15, 23, 12, 9, 987_654)
        assert d - hours(24) - seconds(5) == UTCDateTime(
            2020, 8, 14, 23, 12, 4, 987_654
        )

    def test_date_units(self):
        d = UTCDateTime(2020, 8, 15, 23, 30)
        assert d - years(1) - days(4) - minutes(-4) == UTCDateTime(
            2019, 8, 11, 23, 34
        )

    def test_utc(self):
        d = UTCDateTime(2020, 8, 15, 23, 12, 9, 987_654)
        other = UTCDateTime(2020, 8, 14, 23, 12, 4, 987_654)
        assert d - other == hours(24) + seconds(5)

    def test_offset(self):
        d = UTCDateTime(2020, 8, 15, 23)
        assert d - OffsetDateTime(2020, 8, 15, 20, offset=2) == hours(5)

    def test_zoned(self):
        d = UTCDateTime(2023, 10, 29, 6)
        assert d - ZonedDateTime(
            2023, 10, 29, 3, tz="Europe/Paris", disambiguate="later"
        ) == hours(4)
        assert d - ZonedDateTime(
            2023, 10, 29, 2, tz="Europe/Paris", disambiguate="later"
        ) == hours(5)
        assert d - ZonedDateTime(
            2023, 10, 29, 2, tz="Europe/Paris", disambiguate="earlier"
        ) == hours(6)
        assert d - ZonedDateTime(2023, 10, 29, 1, tz="Europe/Paris") == hours(
            7
        )

    @local_ams_tz()
    def test_local(self):
        d = UTCDateTime(2023, 10, 29, 6)
        assert d - LocalSystemDateTime(
            2023, 10, 29, 3, disambiguate="later"
        ) == hours(4)
        assert d - LocalSystemDateTime(
            2023, 10, 29, 2, disambiguate="later"
        ) == hours(5)
        assert d - LocalSystemDateTime(
            2023, 10, 29, 2, disambiguate="earlier"
        ) == hours(6)
        assert d - LocalSystemDateTime(2023, 10, 29, 1) == hours(7)

    def test_invalid(self):
        d = UTCDateTime(2020, 8, 15, 23, 12, 9, 987_654)
        with pytest.raises(TypeError, match="unsupported operand type"):
            d - 42  # type: ignore[operator]


def test_pickle():
    d = UTCDateTime(2020, 8, 15, 23, 12, 9, 987_654)
    dumped = pickle.dumps(d)
    assert len(dumped) <= len(pickle.dumps(d.py_datetime))
    assert pickle.loads(pickle.dumps(d)) == d


def test_old_pickle_data_remains_unpicklable():
    # Don't update this value -- the whole idea is that it's a pickle at
    # a specific version of the library.
    dumped = (
        b"\x80\x04\x952\x00\x00\x00\x00\x00\x00\x00\x8c\x08whenever\x94\x8c\n_unpkl_u"
        b"tc\x94\x93\x94(M\xe4\x07K\x08K\x0fK\x17K\x0cK\tJ\x06\x12\x0f\x00t\x94R\x94."
    )
    assert pickle.loads(dumped) == UTCDateTime(2020, 8, 15, 23, 12, 9, 987_654)


def test_copy():
    d = UTCDateTime(2020, 8, 15, 23, 12, 9, 987_654)
    assert copy(d) is d
    assert deepcopy(d) is d


def test_to_utc():
    d = UTCDateTime(2020, 8, 15, 20)
    assert d.as_utc() is d


def test_to_offset():
    d = UTCDateTime(2020, 8, 15, 20)
    assert d.as_offset().exact_eq(
        OffsetDateTime(2020, 8, 15, 20, offset=hours(0))
    )
    assert d.as_offset(hours(3)).exact_eq(
        OffsetDateTime(2020, 8, 15, 23, offset=hours(3))
    )
    assert d.as_offset(-3).exact_eq(OffsetDateTime(2020, 8, 15, 17, offset=-3))


def test_to_zoned():
    d = UTCDateTime(2020, 8, 15, 20)
    assert d.as_zoned("America/New_York").exact_eq(
        ZonedDateTime(2020, 8, 15, 16, tz="America/New_York")
    )


@local_nyc_tz()
def test_to_local():
    d = UTCDateTime(2020, 8, 15, 20)
    assert d.as_local().exact_eq(LocalSystemDateTime(2020, 8, 15, 16))
    # ensure disembiguation is correct
    d = UTCDateTime(2022, 11, 6, 5)
    assert d.as_local().exact_eq(
        LocalSystemDateTime(2022, 11, 6, 1, disambiguate="earlier")
    )
    assert d.replace(hour=6).as_local() == LocalSystemDateTime(
        2022, 11, 6, 1, disambiguate="later"
    )


def test_naive():
    d = UTCDateTime(2020, 8, 15, 20)
    assert d.naive() == NaiveDateTime(2020, 8, 15, 20)


@pytest.mark.parametrize(
    "string, fmt, expected",
    [
        (
            "2020-08-15 23:12+0000",
            "%Y-%m-%d %H:%M%z",
            UTCDateTime(2020, 8, 15, 23, 12),
        ),
        (
            "2020-08-15 23:12:09+0000",
            "%Y-%m-%d %H:%M:%S%z",
            UTCDateTime(2020, 8, 15, 23, 12, 9),
        ),
        (
            "2020-08-15 23:12:09Z",
            "%Y-%m-%d %H:%M:%S%z",
            UTCDateTime(2020, 8, 15, 23, 12, 9),
        ),
        ("2020-08-15 23", "%Y-%m-%d %H", UTCDateTime(2020, 8, 15, 23)),
    ],
)
def test_strptime(string, fmt, expected):
    assert UTCDateTime.strptime(string, fmt) == expected


def test_strptime_invalid():
    with pytest.raises(ValueError):
        UTCDateTime.strptime("2020-08-15 23:12:09+0200", "%Y-%m-%d %H:%M:%S%z")


def test_rfc2822():
    assert (
        UTCDateTime(2020, 8, 15, 23, 12, 9, 450).rfc2822()
        == "Sat, 15 Aug 2020 23:12:09 GMT"
    )


@pytest.mark.parametrize(
    "s, expected",
    [
        (
            "Sat, 15 Aug 2020 23:12:09 GMT",
            UTCDateTime(2020, 8, 15, 23, 12, 9),
        ),
        (
            "Sat, 15 Aug 2020 23:12:09 +0000",
            UTCDateTime(2020, 8, 15, 23, 12, 9),
        ),
        (
            "Sat, 15 Aug 2020 23:12:09 UTC",
            UTCDateTime(2020, 8, 15, 23, 12, 9),
        ),
        (
            "15      Aug 2020\n23:12 UTC",
            UTCDateTime(2020, 8, 15, 23, 12),
        ),
    ],
)
def test_from_rfc2822(s, expected):
    assert UTCDateTime.from_rfc2822(s) == expected


def test_from_rfc2822_invalid():
    # no timezone
    with pytest.raises(ValueError):
        UTCDateTime.from_rfc2822("Sat, 15 Aug 2020 23:12:09")

    # -0000 timezone special case
    with pytest.raises(ValueError, match="RFC.*-0000.*UTC"):
        UTCDateTime.from_rfc2822("Sat, 15 Aug 2020 23:12:09 -0000")

    # nonzero offset
    with pytest.raises(ValueError, match="nonzero"):
        UTCDateTime.from_rfc2822("Sat, 15 Aug 2020 23:12:09 +0200")


def test_rfc3339():
    assert (
        UTCDateTime(2020, 8, 15, 23, 12, 9, 450).rfc3339()
        == "2020-08-15T23:12:09.000450Z"
    )


@pytest.mark.parametrize(
    "s, expect",
    [
        (
            "2020-08-15T23:12:09.000450Z",
            UTCDateTime(2020, 8, 15, 23, 12, 9, 450),
        ),
        (
            "2020-08-15t23:12:09z",
            UTCDateTime(2020, 8, 15, 23, 12, 9),
        ),
        (
            "2020-08-15_23:12:09-00:00",
            UTCDateTime(2020, 8, 15, 23, 12, 9),
        ),
        (
            "2020-08-15_23:12:09+00:00",
            UTCDateTime(2020, 8, 15, 23, 12, 9),
        ),
        # subsecond precision that isn't supported by older fromisoformat()
        (
            "2020-08-15T23:12:09.34Z",
            UTCDateTime(2020, 8, 15, 23, 12, 9, 340_000),
        ),
    ],
)
def test_from_rfc3339(s, expect):
    assert UTCDateTime.from_rfc3339(s) == expect


def test_from_rfc3339_invalid():
    # no timezone
    with pytest.raises(ValueError):
        UTCDateTime.from_rfc3339("2020-08-15T23:12:09")

    # no seconds
    with pytest.raises(ValueError):
        UTCDateTime.from_rfc3339("2020-08-15T23:12-00:00")

    # nonzero offset
    with pytest.raises(ValueError):
        UTCDateTime.from_rfc3339("2020-08-15T23:12:09+02:00")
