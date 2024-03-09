import pickle
import weakref
from datetime import datetime as py_datetime, timezone

import pytest
from hypothesis import given
from hypothesis.strategies import text

from whenever import (
    AmbiguousTime,
    Date,
    InvalidFormat,
    LocalSystemDateTime,
    NaiveDateTime,
    OffsetDateTime,
    SkippedTime,
    UTCDateTime,
    ZonedDateTime,
    days,
    hours,
    minutes,
    seconds,
    weeks,
    years,
)

from .common import (
    AlwaysEqual,
    AlwaysLarger,
    AlwaysSmaller,
    NeverEqual,
    local_ams_tz,
)


def test_minimal():
    d = NaiveDateTime(2020, 8, 15, 5, 12, 30, 450)

    assert d.year == 2020
    assert d.month == 8
    assert d.day == 15
    assert d.hour == 5
    assert d.minute == 12
    assert d.second == 30
    assert d.microsecond == 450

    assert (
        NaiveDateTime(2020, 8, 15, 12)
        == NaiveDateTime(2020, 8, 15, 12, 0)
        == NaiveDateTime(2020, 8, 15, 12, 0, 0)
        == NaiveDateTime(2020, 8, 15, 12, 0, 0, 0)
    )


def test_date():
    d = NaiveDateTime(2020, 8, 15, 23, 12, 9, 987_654)
    assert d.date() == Date(2020, 8, 15)


def test_assume_utc():
    assert NaiveDateTime(2020, 8, 15, 23).assume_utc() == UTCDateTime(
        2020, 8, 15, 23
    )


def test_assume_offset():
    assert (
        NaiveDateTime(2020, 8, 15, 23)
        .assume_offset(hours(5))
        .exact_eq(OffsetDateTime(2020, 8, 15, 23, offset=hours(5)))
    )


class TestAssumeZoned:
    def test_typical(self):
        assert NaiveDateTime(2020, 8, 15, 23).assume_zoned(
            "Asia/Tokyo"
        ) == ZonedDateTime(2020, 8, 15, 23, tz="Asia/Tokyo")

    def test_ambiguous(self):
        d = NaiveDateTime(2023, 10, 29, 2, 15)

        with pytest.raises(AmbiguousTime, match="02:15.*Europe/Amsterdam"):
            d.assume_zoned("Europe/Amsterdam")

        assert d.assume_zoned(
            "Europe/Amsterdam", disambiguate="earlier"
        ) == ZonedDateTime(
            2023, 10, 29, 2, 15, tz="Europe/Amsterdam", disambiguate="earlier"
        )
        assert d.assume_zoned(
            "Europe/Amsterdam", disambiguate="later"
        ) == ZonedDateTime(
            2023, 10, 29, 2, 15, tz="Europe/Amsterdam", disambiguate="later"
        )

    def test_nonexistent(self):
        d = NaiveDateTime(2023, 3, 26, 2, 15)

        with pytest.raises(SkippedTime, match="02:15.*Europe/Amsterdam"):
            d.assume_zoned("Europe/Amsterdam")

        with pytest.raises(SkippedTime, match="02:15.*Europe/Amsterdam"):
            d.assume_zoned("Europe/Amsterdam", disambiguate="raise")

        assert d.assume_zoned(
            "Europe/Amsterdam", disambiguate="earlier"
        ) == ZonedDateTime(
            2023, 3, 26, 2, 15, tz="Europe/Amsterdam", disambiguate="earlier"
        )


class TestAssumeLocal:
    @local_ams_tz()
    def test_typical(self):
        assert NaiveDateTime(
            2020, 8, 15, 23
        ).assume_local() == LocalSystemDateTime(2020, 8, 15, 23)

    @local_ams_tz()
    def test_ambiguous(self):
        d = NaiveDateTime(2023, 10, 29, 2, 15)

        with pytest.raises(AmbiguousTime, match="02:15.*system"):
            d.assume_local()

        with pytest.raises(AmbiguousTime, match="02:15.*system"):
            d.assume_local(disambiguate="raise")

        assert d.assume_local(disambiguate="earlier") == LocalSystemDateTime(
            2023, 10, 29, 2, 15, disambiguate="earlier"
        )
        assert d.assume_local(
            disambiguate="compatible"
        ) == LocalSystemDateTime(2023, 10, 29, 2, 15, disambiguate="earlier")
        assert d.assume_local(disambiguate="later") == LocalSystemDateTime(
            2023, 10, 29, 2, 15, disambiguate="later"
        )

    @local_ams_tz()
    def test_nonexistent(self):
        d = NaiveDateTime(2023, 3, 26, 2, 15)

        with pytest.raises(SkippedTime, match="02:15.*system"):
            d.assume_local()

        with pytest.raises(SkippedTime, match="02:15.*system"):
            d.assume_local(disambiguate="raise")

        assert d.assume_local(disambiguate="earlier") == LocalSystemDateTime(
            2023, 3, 26, 2, 15, disambiguate="earlier"
        )
        assert d.assume_local(disambiguate="later") == LocalSystemDateTime(
            2023, 3, 26, 2, 15, disambiguate="later"
        )
        assert d.assume_local(
            disambiguate="compatible"
        ) == LocalSystemDateTime(2023, 3, 26, 2, 15, disambiguate="compatible")


def test_immutable():
    d = NaiveDateTime(2020, 8, 15)
    with pytest.raises(AttributeError):
        d.year = 2021  # type: ignore[misc]


class TestFromCanonicalFormat:
    def test_valid(self):
        assert NaiveDateTime.from_canonical_format(
            "2020-08-15T12:08:30"
        ) == NaiveDateTime(2020, 8, 15, 12, 8, 30)

    def test_valid_three_fractions(self):
        assert NaiveDateTime.from_canonical_format(
            "2020-08-15T12:08:30.349"
        ) == NaiveDateTime(2020, 8, 15, 12, 8, 30, 349_000)

    def test_valid_six_fractions(self):
        assert NaiveDateTime.from_canonical_format(
            "2020-08-15T12:08:30.349123"
        ) == NaiveDateTime(2020, 8, 15, 12, 8, 30, 349_123)

    def test_single_space_instead_of_T(self):
        assert NaiveDateTime.from_canonical_format(
            "2020-08-15 12:08:30"
        ) == NaiveDateTime(2020, 8, 15, 12, 8, 30)

    def test_unpadded(self):
        with pytest.raises(InvalidFormat):
            NaiveDateTime.from_canonical_format("2020-8-15T12:8:30")

    def test_overly_precise_fraction(self):
        with pytest.raises(InvalidFormat):
            NaiveDateTime.from_canonical_format(
                "2020-08-15T12:08:30.123456789123"
            )

    def test_trailing_z(self):
        with pytest.raises(InvalidFormat):
            NaiveDateTime.from_canonical_format("2020-08-15T12:08:30Z")

    def test_no_seconds(self):
        with pytest.raises(InvalidFormat):
            NaiveDateTime.from_canonical_format("2020-08-15T12:08")

    def test_empty(self):
        with pytest.raises(InvalidFormat):
            NaiveDateTime.from_canonical_format("")

    def test_garbage(self):
        with pytest.raises(InvalidFormat):
            NaiveDateTime.from_canonical_format("garbage")

    @given(text())
    def test_fuzzing(self, s: str):
        with pytest.raises(InvalidFormat):
            NaiveDateTime.from_canonical_format(s)


def test_equality():
    d = NaiveDateTime(2020, 8, 15)
    different = NaiveDateTime(2020, 8, 16)
    same = NaiveDateTime(2020, 8, 15)
    assert d == same
    assert d != different
    assert not d == different
    assert not d != same

    assert hash(d) == hash(same)
    assert hash(d) != hash(different)

    assert d == AlwaysEqual()
    assert d != NeverEqual()
    assert not d == NeverEqual()
    assert not d != AlwaysEqual()

    assert d != 42  # type: ignore[comparison-overlap]
    assert not d == 42  # type: ignore[comparison-overlap]

    # Ambiguity in system timezone
    with local_ams_tz():
        assert NaiveDateTime(
            2023, 10, 29, 2, 15
        ) == NaiveDateTime.from_py_datetime(
            py_datetime(2023, 10, 29, 2, 15, fold=1)
        )


def test_repr():
    d = NaiveDateTime(2020, 8, 15, 23, 12, 9, 987_654)
    assert repr(d) == "NaiveDateTime(2020-08-15 23:12:09.987654)"
    assert (
        repr(NaiveDateTime(2020, 8, 15, 23, 12))
        == "NaiveDateTime(2020-08-15 23:12:00)"
    )


def test_canonical_format():
    d = NaiveDateTime(2020, 8, 15, 23, 12, 9, 987_654)
    assert str(d) == "2020-08-15 23:12:09.987654"
    assert d.canonical_format() == "2020-08-15T23:12:09.987654"


def test_comparison():
    d = NaiveDateTime.from_canonical_format("2020-08-15T23:12:09")
    later = NaiveDateTime.from_canonical_format("2020-08-16T00:00:00")
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


def test_py():
    d = NaiveDateTime(2020, 8, 15, 23, 12, 9, 987_654)
    assert d.py_datetime() == py_datetime(2020, 8, 15, 23, 12, 9, 987_654)


def test_from_py_datetime():
    d = py_datetime(2020, 8, 15, 23, 12, 9, 987_654)
    assert NaiveDateTime.from_py_datetime(d) == NaiveDateTime(
        2020, 8, 15, 23, 12, 9, 987_654
    )

    with pytest.raises(ValueError, match="utc"):
        NaiveDateTime.from_py_datetime(
            py_datetime(2020, 8, 15, 23, 12, 9, 987_654, tzinfo=timezone.utc)
        )


def test_weakref():
    d = NaiveDateTime(2020, 8, 15)
    ref = weakref.ref(d)
    assert ref() == d


def test_min_max():
    assert NaiveDateTime.MIN == NaiveDateTime(1, 1, 1)
    assert NaiveDateTime.MAX == NaiveDateTime(
        9999, 12, 31, 23, 59, 59, 999_999
    )


def test_replace():
    d = NaiveDateTime(2020, 8, 15, 23, 12, 9, 987_654)
    assert d.replace(year=2021) == NaiveDateTime(
        2021, 8, 15, 23, 12, 9, 987_654
    )
    assert d.replace(month=9) == NaiveDateTime(2020, 9, 15, 23, 12, 9, 987_654)
    assert d.replace(day=16) == NaiveDateTime(2020, 8, 16, 23, 12, 9, 987_654)
    assert d.replace(hour=0) == NaiveDateTime(2020, 8, 15, 0, 12, 9, 987_654)
    assert d.replace(minute=0) == NaiveDateTime(2020, 8, 15, 23, 0, 9, 987_654)
    assert d.replace(second=0) == NaiveDateTime(
        2020, 8, 15, 23, 12, 0, 987_654
    )
    assert d.replace(microsecond=0) == NaiveDateTime(2020, 8, 15, 23, 12, 9, 0)

    with pytest.raises(TypeError, match="tzinfo"):
        d.replace(tzinfo=timezone.utc)  # type: ignore[call-arg]


class TestAdd:

    def test_time_units(self):
        d = NaiveDateTime(2020, 8, 15, 23, 12, 9, 987_654)
        assert d + hours(24) + seconds(5) == NaiveDateTime(
            2020, 8, 16, 23, 12, 14, 987_654
        )

    def test_invalid(self):
        d = NaiveDateTime(2020, 8, 15, 23, 12, 9, 987_654)
        with pytest.raises(TypeError, match="unsupported operand type"):
            d + 42  # type: ignore[operator]

    def test_date_units(self):
        d = NaiveDateTime(2020, 8, 15, 23, 12, 9, 987_654)
        assert d + years(1) + weeks(1) + days(-3) + minutes(5) == d.replace(
            year=2021, day=19, minute=17
        )


class TestSubtract:

    def test_time_units(self):
        d = NaiveDateTime(2020, 8, 15, 23, 12, 9, 987_654)
        assert d - hours(24) - seconds(5) == NaiveDateTime(
            2020, 8, 14, 23, 12, 4, 987_654
        )

    def test_date_units(self):
        d = NaiveDateTime(2020, 8, 15, 23, 12, 9, 987_654)
        assert d - (years(1) + weeks(1) + days(-3) + minutes(6)) == d.replace(
            year=2019, day=11, minute=6
        )

    def test_other_datetime(self):
        d = NaiveDateTime(2020, 8, 15, 23, 12, 9, 987_654)
        other = NaiveDateTime(2020, 8, 14, 23, 12, 4, 987_654)
        assert d - other == hours(24) + seconds(5)

    def test_invalid(self):
        d = NaiveDateTime(2020, 8, 15, 23, 12, 9, 987_654)
        with pytest.raises(TypeError, match="unsupported operand type"):
            d - 42  # type: ignore[operator]


def test_pickle():
    d = NaiveDateTime(2020, 8, 15, 23, 12, 9, 987_654)
    dumped = pickle.dumps(d)
    assert len(dumped) <= len(pickle.dumps(d.py_datetime())) + 15
    assert pickle.loads(pickle.dumps(d)) == d


def test_old_pickle_data_remains_unpicklable():
    # Don't update this value -- the whole idea is that it's a pickle at
    # a specific version of the library.
    dumped = (
        b"\x80\x04\x954\x00\x00\x00\x00\x00\x00\x00\x8c\x08whenever\x94\x8c\x0c_unp"
        b"kl_naive\x94\x93\x94(M\xe4\x07K\x08K\x0fK\x17K\x0cK\tJ\x06\x12\x0f\x00t\x94"
        b"R\x94."
    )
    assert pickle.loads(dumped) == NaiveDateTime(
        2020, 8, 15, 23, 12, 9, 987_654
    )


def test_strptime():
    assert NaiveDateTime.strptime(
        "2020-08-15 23:12", "%Y-%m-%d %H:%M"
    ) == NaiveDateTime(2020, 8, 15, 23, 12)


def test_strptime_invalid():
    with pytest.raises(ValueError):
        NaiveDateTime.strptime(
            "2020-08-15 23:12:09+0500", "%Y-%m-%d %H:%M:%S%z"
        )


def test_rfc2822():
    assert (
        NaiveDateTime(2020, 8, 15, 23, 12, 9, 450).rfc2822()
        == "Sat, 15 Aug 2020 23:12:09 -0000"
    )


@pytest.mark.parametrize(
    "s, expected",
    [
        (
            "Sat, 15 Aug 2020 23:12:09",
            NaiveDateTime(2020, 8, 15, 23, 12, 9),
        ),
        (
            "Sat, 15 Aug 2020 23:12:09 -0000",
            NaiveDateTime(2020, 8, 15, 23, 12, 9),
        ),
        (
            "15      Aug 2020\n23:12 -0000",
            NaiveDateTime(2020, 8, 15, 23, 12),
        ),
    ],
)
def test_from_rfc2822(s, expected):
    assert NaiveDateTime.from_rfc2822(s) == expected


def test_from_rfc2822_invalid():
    # non-0000 timezone
    with pytest.raises(ValueError, match="RFC.*-0000"):
        NaiveDateTime.from_rfc2822("Sat, 15 Aug 2020 23:12:09 +0000")
