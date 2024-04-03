import pickle
import re
import weakref
from datetime import datetime as py_datetime, timedelta, timezone, tzinfo

import pytest
from hypothesis import given
from hypothesis.strategies import text
from pytest import approx

from whenever import (
    LocalSystemDateTime,
    NaiveDateTime,
    OffsetDateTime,
    TimeDelta,
    UTCDateTime,
    ZonedDateTime,
    hours,
    minutes,
    seconds,
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

    def test_int_offset(self):
        d = OffsetDateTime(2020, 8, 15, 5, 12, 30, 450, offset=-5)
        assert d.offset == hours(-5)

    def test_offset_missing(self):
        with pytest.raises(TypeError, match="offset"):
            OffsetDateTime(2020, 8, 15, 5, 12, 30, 450)  # type: ignore[call-arg]

    def test_invalid_offset(self):
        with pytest.raises(ValueError, match="offset"):
            OffsetDateTime(2020, 8, 15, 5, 12, offset=34)

    def test_init_optionality(self):
        assert (
            OffsetDateTime(2020, 8, 15, 12, offset=5)
            == OffsetDateTime(2020, 8, 15, 12, 0, offset=5)
            == OffsetDateTime(2020, 8, 15, 12, 0, 0, offset=5)
        )

    def test_kwargs(self):
        d = OffsetDateTime(
            year=2020,
            month=8,
            day=15,
            hour=5,
            minute=12,
            second=30,
            offset=5,
        )
        assert d == OffsetDateTime(2020, 8, 15, 5, 12, 30, 0, offset=5)


def test_immutable():
    d = OffsetDateTime(2020, 8, 15, offset=minutes(5))
    with pytest.raises(AttributeError):
        d.year = 2021  # type: ignore[misc]


class TestCanonicalFormat:

    @pytest.mark.parametrize(
        "d, expected",
        [
            (
                OffsetDateTime(2020, 8, 15, 23, 12, 9, offset=5),
                "2020-08-15T23:12:09+05:00",
            ),
            (
                OffsetDateTime(2020, 8, 15, 23, 12, 9, 987_654, offset=5),
                "2020-08-15T23:12:09.987654+05:00",
            ),
        ],
    )
    def test_canonical_format(self, d: OffsetDateTime, expected: str):
        assert str(d) == expected.replace("T", " ")
        assert d.canonical_format() == expected

    def test_seperator(self):
        d = OffsetDateTime(2020, 8, 15, 23, 12, 9, offset=5)
        assert d.canonical_format(sep=" ") == "2020-08-15 23:12:09+05:00"


class TestFromCanonicalFormat:
    def test_valid(self):
        assert OffsetDateTime.from_canonical_format(
            "2020-08-15T12:08:30+05:00"
        ).exact_eq(OffsetDateTime(2020, 8, 15, 12, 8, 30, offset=5))

    def test_valid_offset_with_seconds(self):
        assert OffsetDateTime.from_canonical_format(
            "2020-08-15T12:08:30+05:00:33"
        ).exact_eq(
            OffsetDateTime(
                2020,
                8,
                15,
                12,
                8,
                30,
                offset=hours(5) + seconds(33),
            )
        )

    def test_valid_three_fractions(self):
        assert OffsetDateTime.from_canonical_format(
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
                offset=hours(5) + seconds(33),
            )
        )

    def test_valid_six_fractions(self):
        assert OffsetDateTime.from_canonical_format(
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
                offset=TimeDelta(hours=5, seconds=33, microseconds=987_654),
            )
        )

    def test_single_space_instead_of_T(self):
        assert OffsetDateTime.from_canonical_format(
            "2020-08-15 12:08:30-04:00"
        ).exact_eq(OffsetDateTime(2020, 8, 15, 12, 8, 30, offset=-4))

    def test_unpadded(self):
        with pytest.raises(
            ValueError,
            match=r"Could not parse.*canonical format.*'2020-8-15T12:8:30\+05:00'",
        ):
            OffsetDateTime.from_canonical_format("2020-8-15T12:8:30+05:00")

    def test_overly_precise_fraction(self):
        with pytest.raises(
            ValueError,
            match=r"Could not parse.*canonical format.*"
            r"'2020-08-15T12:08:30.123456789123\+05:00'",
        ):
            OffsetDateTime.from_canonical_format(
                "2020-08-15T12:08:30.123456789123+05:00"
            )

    def test_invalid_offset(self):
        with pytest.raises(
            ValueError,
            match=r"Could not parse.*canonical format.*'2020-08-15T12:08:30-99:00'",
        ):
            OffsetDateTime.from_canonical_format("2020-08-15T12:08:30-99:00")

    def test_no_offset(self):
        with pytest.raises(
            ValueError,
            match=r"Could not parse.*canonical format.*'2020-08-15T12:08:30'",
        ):
            OffsetDateTime.from_canonical_format("2020-08-15T12:08:30")

    def test_no_seconds(self):
        with pytest.raises(
            ValueError,
            match=r"Could not parse.*canonical format.*'2020-08-15T12:08-05:00'",
        ):
            OffsetDateTime.from_canonical_format("2020-08-15T12:08-05:00")

    def test_empty(self):
        with pytest.raises(
            ValueError, match=r"Could not parse.*canonical format.*''"
        ):
            OffsetDateTime.from_canonical_format("")

    def test_garbage(self):
        with pytest.raises(
            ValueError,
            match=r"Could not parse.*canonical format.*'garbage'",
        ):
            OffsetDateTime.from_canonical_format("garbage")

    @given(text())
    def test_fuzzing(self, s: str):
        with pytest.raises(
            ValueError,
            match=r"Could not parse.*canonical format.*" + re.escape(repr(s)),
        ):
            OffsetDateTime.from_canonical_format(s)


def test_exact_equality():
    d = OffsetDateTime(2020, 8, 15, 12, offset=5)
    same = d.replace()
    utc_same = d.replace(hour=13, offset=hours(6))
    different = d.replace(offset=hours(6))
    assert d.exact_eq(same)
    assert not d.exact_eq(utc_same)
    assert not d.exact_eq(different)


class TestEquality:
    def test_same_exact(self):
        d = OffsetDateTime(2020, 8, 15, 12, offset=5)
        same = d.replace()
        assert d == same
        assert not d != same
        assert hash(d) == hash(same)

    def test_different(self):
        d = OffsetDateTime(2020, 8, 15, 12, offset=5)
        different = d.replace(offset=hours(6))
        assert d != different
        assert not d == different
        assert hash(d) != hash(different)

    def test_same_time(self):
        d = OffsetDateTime(2020, 8, 15, 12, offset=5)
        same_time = d.replace(hour=11, offset=hours(4))
        assert d == same_time
        assert not d != same_time
        assert hash(d) == hash(same_time)

    def test_zoned(self):
        d: OffsetDateTime | ZonedDateTime = OffsetDateTime(
            2023, 10, 29, 5, 15, offset=4
        )
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

    @local_ams_tz()
    def test_local(self):
        d: OffsetDateTime | LocalSystemDateTime = OffsetDateTime(
            2023, 10, 29, 0, 15, offset=-1
        )
        local_same = LocalSystemDateTime(
            2023, 10, 29, 2, 15, disambiguate="later"
        )
        local_different = LocalSystemDateTime(
            2023, 10, 29, 2, 15, disambiguate="earlier"
        )
        assert d == local_same
        assert not d != local_same
        assert not d == local_different
        assert d != local_different

        assert hash(d) == hash(local_same)
        assert hash(d) != hash(local_different)

    def test_utc(self):
        d: UTCDateTime | OffsetDateTime = OffsetDateTime(
            2020, 8, 15, 12, offset=5
        )
        utc_same = UTCDateTime(2020, 8, 15, 7)
        utc_different = UTCDateTime(2020, 8, 15, 7, 1)
        assert d == utc_same
        assert not d != utc_same
        assert not d == utc_different
        assert d != utc_different

        assert hash(d) == hash(utc_same)
        assert hash(d) != hash(utc_different)

    def test_not_implemented(self):
        d = OffsetDateTime(2020, 8, 15, 12, offset=5)
        assert d == AlwaysEqual()
        assert d != NeverEqual()
        assert not d == NeverEqual()
        assert not d != AlwaysEqual()
        assert d != 42  # type: ignore[comparison-overlap]
        assert not d == 42  # type: ignore[comparison-overlap]


def test_timestamp():
    assert OffsetDateTime(1970, 1, 1, 3, offset=3).timestamp() == 0
    assert OffsetDateTime(
        2020, 8, 15, 8, 8, 30, 45, offset=-4
    ).timestamp() == approx(1_597_493_310.000045, abs=1e-6)


def test_from_timestamp():
    assert OffsetDateTime.from_timestamp(0, offset=hours(3)).exact_eq(
        OffsetDateTime(1970, 1, 1, 3, offset=3)
    )
    assert OffsetDateTime.from_timestamp(0, offset=3).exact_eq(
        OffsetDateTime(1970, 1, 1, 3, offset=3)
    )
    assert OffsetDateTime.from_timestamp(
        1_597_493_310, offset=hours(-2)
    ).exact_eq(OffsetDateTime(2020, 8, 15, 10, 8, 30, offset=-2))
    with pytest.raises((OSError, OverflowError, ValueError)):
        OffsetDateTime.from_timestamp(
            1_000_000_000_000_000_000, offset=hours(0)
        )


def test_repr():
    d = OffsetDateTime(
        2020,
        8,
        15,
        23,
        12,
        9,
        987_654,
        offset=hours(5) + minutes(22),
    )
    assert repr(d) == "OffsetDateTime(2020-08-15 23:12:09.987654+05:22)"
    assert (
        repr(OffsetDateTime(2020, 8, 15, 23, 12, offset=0))
        == "OffsetDateTime(2020-08-15 23:12:00+00:00)"
    )


class TestComparison:
    def test_offset(self):
        d = OffsetDateTime(2020, 8, 15, 12, 30, offset=5)
        later = d.replace(hour=13)
        assert d < later
        assert d <= later
        assert later > d
        assert later >= d

    def test_utc(self):
        d = OffsetDateTime(2020, 8, 15, 12, 30, offset=5)
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
        d = OffsetDateTime(2023, 10, 29, 5, 30, offset=5)
        zoned_eq = d.as_zoned("Europe/Paris")
        zoned_gt = zoned_eq.replace(minute=31, disambiguate="earlier")
        zoned_lt = zoned_eq.replace(minute=29, disambiguate="earlier")

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
        d = OffsetDateTime(2020, 8, 15, 12, 30, offset=5)
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
        d = OffsetDateTime(2020, 8, 15, 12, 30, offset=5)

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


def test_py_datetime():
    d = OffsetDateTime(2020, 8, 15, 23, 12, 9, 987_654, offset=5)
    assert d.py_datetime() == py_datetime(
        2020,
        8,
        15,
        23,
        12,
        9,
        987_654,
        tzinfo=timezone(timedelta(hours=5)),
    )


def test_from_py_datetime():
    d = py_datetime(
        2020,
        8,
        15,
        23,
        12,
        9,
        987_654,
        tzinfo=timezone(timedelta(hours=2)),
    )
    assert OffsetDateTime.from_py_datetime(d).exact_eq(
        OffsetDateTime(2020, 8, 15, 23, 12, 9, 987_654, offset=2)
    )

    class SomeTzinfo(tzinfo):
        pass

    d2 = d.replace(tzinfo=SomeTzinfo())  # type: ignore[abstract]
    with pytest.raises(ValueError, match="SomeTzinfo"):
        OffsetDateTime.from_py_datetime(d2)


class TestNow:

    def test_timedelta(self):
        now = OffsetDateTime.now(hours(5))
        assert now.offset == hours(5)
        py_now = py_datetime.now(timezone.utc)
        assert py_now - now.py_datetime() < timedelta(seconds=1)

    def test_int(self):
        now = OffsetDateTime.now(-5)
        assert now.offset == hours(-5)
        py_now = py_datetime.now(timezone.utc)
        assert py_now - now.py_datetime() < timedelta(seconds=1)


def test_weakref():
    d = OffsetDateTime(2020, 8, 15, offset=5)
    ref = weakref.ref(d)
    assert ref() == d


def test_replace():
    d = OffsetDateTime(2020, 8, 15, 23, 12, 9, 987_654, offset=5)
    assert d.replace(year=2021).exact_eq(
        OffsetDateTime(2021, 8, 15, 23, 12, 9, 987_654, offset=5)
    )
    assert d.replace(month=9).exact_eq(
        OffsetDateTime(2020, 9, 15, 23, 12, 9, 987_654, offset=5)
    )
    assert d.replace(day=16).exact_eq(
        OffsetDateTime(2020, 8, 16, 23, 12, 9, 987_654, offset=5)
    )
    assert d.replace(hour=0).exact_eq(
        OffsetDateTime(2020, 8, 15, 0, 12, 9, 987_654, offset=5)
    )
    assert d.replace(minute=0).exact_eq(
        OffsetDateTime(2020, 8, 15, 23, 0, 9, 987_654, offset=5)
    )
    assert d.replace(second=0).exact_eq(
        OffsetDateTime(2020, 8, 15, 23, 12, 0, 987_654, offset=5)
    )
    assert d.replace(microsecond=0).exact_eq(
        OffsetDateTime(2020, 8, 15, 23, 12, 9, 0, offset=5)
    )
    assert d.replace(offset=hours(6)).exact_eq(
        OffsetDateTime(2020, 8, 15, 23, 12, 9, 987_654, offset=6)
    )
    assert d.replace(offset=-6).exact_eq(
        OffsetDateTime(2020, 8, 15, 23, 12, 9, 987_654, offset=-6)
    )

    with pytest.raises(TypeError, match="tzinfo"):
        d.replace(tzinfo=timezone.utc)  # type: ignore[call-arg]


def test_add_not_allowed():
    d = OffsetDateTime(2020, 8, 15, 23, 12, 9, 987_654, offset=5)
    with pytest.raises(TypeError, match="unsupported operand type"):
        d + hours(4)  # type: ignore[operator]

    with pytest.raises(TypeError, match="unsupported operand type"):
        d + 32  # type: ignore[operator]


class TestSubtract:
    def test_invalid(self):
        d = OffsetDateTime(2020, 8, 15, 23, 12, 9, 987_654, offset=5)
        with pytest.raises(TypeError, match="unsupported operand type"):
            d - hours(2)  # type: ignore[operator]
        with pytest.raises(TypeError, match="unsupported operand type"):
            d - 42  # type: ignore[operator]

    def test_offset(self):
        d = OffsetDateTime(2020, 8, 15, 23, 12, 9, 987_654, offset=5)
        other = OffsetDateTime(2020, 8, 14, 23, 12, 4, 987_654, offset=-3)
        assert d - other == hours(16) + seconds(5)

    def test_utc(self):
        d = OffsetDateTime(2020, 8, 15, 20, offset=5)
        assert d - UTCDateTime(2020, 8, 15, 20) == -hours(5)

    def test_zoned(self):
        d = OffsetDateTime(2023, 10, 29, 6, offset=2)
        assert d - ZonedDateTime(2023, 10, 29, 3, tz="Europe/Paris") == hours(
            2
        )
        assert d - ZonedDateTime(
            2023, 10, 29, 2, tz="Europe/Paris", disambiguate="later"
        ) == hours(3)
        assert d - ZonedDateTime(
            2023, 10, 29, 2, tz="Europe/Paris", disambiguate="earlier"
        ) == hours(4)
        assert d - ZonedDateTime(2023, 10, 29, 1, tz="Europe/Paris") == hours(
            5
        )

    @local_ams_tz()
    def test_local(self):
        d = OffsetDateTime(2023, 10, 29, 6, offset=2)
        assert d - LocalSystemDateTime(
            2023, 10, 29, 3, disambiguate="later"
        ) == hours(2)
        assert d - LocalSystemDateTime(
            2023, 10, 29, 2, disambiguate="later"
        ) == hours(3)
        assert d - LocalSystemDateTime(
            2023, 10, 29, 2, disambiguate="earlier"
        ) == hours(4)
        assert d - LocalSystemDateTime(2023, 10, 29, 1) == hours(5)


def test_pickle():
    d = OffsetDateTime(2020, 8, 15, 23, 12, 9, 987_654, offset=3)
    dumped = pickle.dumps(d)
    assert len(dumped) <= len(pickle.dumps(d.py_datetime()))
    assert pickle.loads(pickle.dumps(d)) == d


def test_old_pickle_data_remains_unpicklable():
    # Don't update this value -- the whole idea is that it's a pickle at
    # a specific version of the library.
    dumped = (
        b"\x80\x04\x95>\x00\x00\x00\x00\x00\x00\x00\x8c\x08whenever\x94\x8c\r_unpkl_o"
        b"ffset\x94\x93\x94(M\xe4\x07K\x08K\x0fK\x17K\x0cK\tJ\x06\x12\x0f\x00G"
        b"@\xc5\x18\x00\x00\x00\x00\x00t\x94R\x94."
    )
    assert pickle.loads(dumped) == OffsetDateTime(
        2020, 8, 15, 23, 12, 9, 987_654, offset=3
    )


def test_to_utc():
    d = OffsetDateTime(2020, 8, 15, 23, 12, 9, 987_654, offset=3)
    assert d.as_utc() == UTCDateTime(2020, 8, 15, 20, 12, 9, 987_654)


def test_to_offset():
    d = OffsetDateTime(2020, 8, 15, 23, 12, 9, 987_654, offset=3)
    assert d.as_offset(5).exact_eq(
        OffsetDateTime(2020, 8, 16, 1, 12, 9, 987_654, offset=5)
    )
    assert d.as_offset() is d
    assert d.as_offset(-3).exact_eq(
        OffsetDateTime(2020, 8, 15, 17, 12, 9, 987_654, offset=-3)
    )


def test_to_zoned():
    d = OffsetDateTime(2020, 8, 15, 20, 12, 9, 987_654, offset=3)
    assert d.as_zoned("America/New_York").exact_eq(
        ZonedDateTime(2020, 8, 15, 13, 12, 9, 987_654, tz="America/New_York")
    )
    with pytest.raises(ZoneInfoNotFoundError):
        d.as_zoned("America/Not_A_Real_Zone")


@local_nyc_tz()
def test_as_local():
    d = OffsetDateTime(2020, 8, 15, 20, 12, 9, 987_654, offset=3)
    assert d.as_local().exact_eq(
        LocalSystemDateTime(2020, 8, 15, 13, 12, 9, 987_654)
    )


def test_naive():
    d = OffsetDateTime(2020, 8, 15, 20, offset=3)
    assert d.naive() == NaiveDateTime(2020, 8, 15, 20)


@pytest.mark.parametrize(
    "string, fmt, expected",
    [
        (
            "2020-08-15 23:12+0315",
            "%Y-%m-%d %H:%M%z",
            OffsetDateTime(2020, 8, 15, 23, 12, offset=hours(3) + minutes(15)),
        ),
        (
            "2020-08-15 23:12:09+0550",
            "%Y-%m-%d %H:%M:%S%z",
            OffsetDateTime(
                2020,
                8,
                15,
                23,
                12,
                9,
                offset=hours(5) + minutes(50),
            ),
        ),
        (
            "2020-08-15 23:12:09Z",
            "%Y-%m-%d %H:%M:%S%z",
            OffsetDateTime(2020, 8, 15, 23, 12, 9, offset=0),
        ),
    ],
)
def test_strptime(string, fmt, expected):
    assert OffsetDateTime.strptime(string, fmt) == expected


def test_strptime_invalid():
    with pytest.raises(ValueError):
        OffsetDateTime.strptime("2020-08-15 23:12:09", "%Y-%m-%d %H:%M:%S")


def test_rfc2822():
    assert (
        OffsetDateTime(2020, 8, 15, 23, 12, 9, 450, offset=1).rfc2822()
        == "Sat, 15 Aug 2020 23:12:09 +0100"
    )


@pytest.mark.parametrize(
    "s, expected",
    [
        (
            "Sat, 15 Aug 2020 23:12:09 GMT",
            OffsetDateTime(2020, 8, 15, 23, 12, 9, offset=0),
        ),
        (
            "Sat, 15 Aug 2020 23:12:09 +0000",
            OffsetDateTime(2020, 8, 15, 23, 12, 9, offset=0),
        ),
        (
            "Sat, 15 Aug 2020 23:12:09 UTC",
            OffsetDateTime(2020, 8, 15, 23, 12, 9, offset=0),
        ),
        (
            "Sat, 15 Aug 2020 23:12:09 -0100",
            OffsetDateTime(2020, 8, 15, 23, 12, 9, offset=-1),
        ),
        (
            "Sat, 15 Aug 2020 23:12:09 +1200",
            OffsetDateTime(2020, 8, 15, 23, 12, 9, offset=12),
        ),
        (
            "Sat, 15 Aug 2020 23:12:09 MST",
            OffsetDateTime(2020, 8, 15, 23, 12, 9, offset=-7),
        ),
        (
            "15      Aug 2020\n23:12 UTC",
            OffsetDateTime(2020, 8, 15, 23, 12, offset=0),
        ),
    ],
)
def test_from_rfc2822(s, expected):
    assert OffsetDateTime.from_rfc2822(s) == expected


def test_from_rfc2822_invalid():
    # no timezone
    with pytest.raises(ValueError, match="missing"):
        OffsetDateTime.from_rfc2822("Sat, 15 Aug 2020 23:12:09")

    # -0000 timezone special case
    with pytest.raises(ValueError, match="RFC.*-0000"):
        OffsetDateTime.from_rfc2822("Sat, 15 Aug 2020 23:12:09 -0000")


def test_rfc3339():
    assert (
        OffsetDateTime(2020, 8, 15, 23, 12, 9, 450, offset=4).rfc3339()
        == "2020-08-15T23:12:09.000450+04:00"
    )


@pytest.mark.parametrize(
    "s, expect",
    [
        (
            "2020-08-15T23:12:09.000450Z",
            OffsetDateTime(2020, 8, 15, 23, 12, 9, 450, offset=0),
        ),
        (
            "2020-08-15t23:12:09z",
            OffsetDateTime(2020, 8, 15, 23, 12, 9, offset=0),
        ),
        (
            "2020-08-15_23:12:09-02:00",
            OffsetDateTime(2020, 8, 15, 23, 12, 9, offset=-2),
        ),
        (
            "2020-08-15_23:12:09+00:00",
            OffsetDateTime(2020, 8, 15, 23, 12, 9, offset=0),
        ),
        # subsecond precision that isn't supported by older fromisoformat()
        (
            "2020-08-15_23:12:09.23+02:00",
            OffsetDateTime(2020, 8, 15, 23, 12, 9, 230_000, offset=2),
        ),
    ],
)
def test_from_rfc3339(s, expect):
    assert OffsetDateTime.from_rfc3339(s) == expect


def test_from_rfc3339_invalid():
    # no timezone
    with pytest.raises(
        ValueError,
        match=r"Could not parse.*RFC3339.*'2020-08-15T23:12:09'",
    ):
        OffsetDateTime.from_rfc3339("2020-08-15T23:12:09")

    # no seconds
    with pytest.raises(
        ValueError,
        match=r"Could not parse.*RFC3339.*'2020-08-15T23:12-02:00'",
    ):
        OffsetDateTime.from_rfc3339("2020-08-15T23:12-02:00")


@pytest.mark.parametrize(
    "d, expected",
    [
        (
            OffsetDateTime(2020, 8, 15, 23, 12, 9, offset=5),
            "2020-08-15T23:12:09+05:00",
        ),
        (
            OffsetDateTime(2020, 8, 15, 23, 12, 9, offset=0),
            "2020-08-15T23:12:09+00:00",
        ),
        (
            OffsetDateTime(
                2020,
                8,
                15,
                23,
                12,
                9,
                987_654,
                offset=TimeDelta(hours=5, seconds=3),
            ),
            "2020-08-15T23:12:09.987654+05:00:03",
        ),
    ],
)
def test_common_iso8601(d, expected):
    assert d.common_iso8601() == expected


@pytest.mark.parametrize(
    "s, expected",
    [
        (
            "2020-08-15T23:12:09+05:00",
            OffsetDateTime(2020, 8, 15, 23, 12, 9, offset=5),
        ),
        (
            "2020-08-15T23:12:09Z",
            OffsetDateTime(2020, 8, 15, 23, 12, 9, offset=0),
        ),
        (
            "2020-08-15T23:12:09.12Z",
            OffsetDateTime(2020, 8, 15, 23, 12, 9, 120_000, offset=0),
        ),
        (
            "2020-08-15T23:12:09.98765+05:03",
            OffsetDateTime(
                2020,
                8,
                15,
                23,
                12,
                9,
                987_650,
                offset=TimeDelta(hours=5, minutes=3),
            ),
        ),
        (
            "2020-08-15T23:12:09.98765+05:03",
            OffsetDateTime(
                2020,
                8,
                15,
                23,
                12,
                9,
                987_650,
                offset=TimeDelta(hours=5, minutes=3),
            ),
        ),
    ],
)
def test_from_common_iso8601(s, expected):
    assert OffsetDateTime.from_common_iso8601(s) == expected


@pytest.mark.parametrize(
    "s",
    [
        "2020-08-15T23:12:09",  # no offset
        "2020-08-15 23:12:09+05:00",  # no separator
        "2020-08-15T23:12.98+05:00",  # fractional minutes
        "2020-08-15T23:12:09-99:00",  # invalid offset
        "2020-08-15T23:12:09-12:00:04",  # seconds offset
        "2020-08-15T23:12:09-00:00",  # special forbidden offset
        "2020-08-15t23:12:09-00:00",  # non-T separator
        "2020-08-15T23:12:09z",  # lowercase Z
    ],
)
def test_from_common_iso8601_invalid(s):
    with pytest.raises(
        ValueError,
        match=r"Could not parse.*ISO 8601.*" + re.escape(repr(s)),
    ):
        OffsetDateTime.from_common_iso8601(s)
