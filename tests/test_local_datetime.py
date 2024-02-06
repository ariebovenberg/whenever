import pickle
import weakref
from copy import copy, deepcopy
from datetime import datetime as py_datetime, timedelta, timezone

import pytest
from hypothesis import given
from hypothesis.strategies import text
from pytest import approx

from whenever import (
    Ambiguous,
    DoesntExistInZone,
    InvalidFormat,
    LocalDateTime,
    NaiveDateTime,
    OffsetDateTime,
    UTCDateTime,
    ZonedDateTime,
    hours,
)

from .common import (
    AlwaysEqual,
    AlwaysLarger,
    AlwaysSmaller,
    NeverEqual,
    ZoneInfo,
    local_ams_tz,
    local_nyc_tz,
)


class TestInit:
    def test_basic(self):
        d = LocalDateTime(2020, 8, 15, 5, 12, 30, 450)

        assert d.year == 2020
        assert d.month == 8
        assert d.day == 15
        assert d.hour == 5
        assert d.minute == 12
        assert d.second == 30
        assert d.microsecond == 450

    def test_optionality(self):
        assert (
            LocalDateTime(2020, 8, 15, 12)
            == LocalDateTime(2020, 8, 15, 12, 0)
            == LocalDateTime(2020, 8, 15, 12, 0, 0)
            == LocalDateTime(2020, 8, 15, 12, 0, 0, 0)
        )


class TestToUTC:
    @local_ams_tz()
    def test_typical_time(self):
        d = LocalDateTime(2020, 8, 15, 11)
        assert d.to_utc().exact_eq(UTCDateTime(2020, 8, 15, 9))

    @local_ams_tz()
    def test_amibiguous_time(self):
        d = LocalDateTime(2023, 10, 29, 2, 15)
        with pytest.raises(Ambiguous):
            d.to_utc()
        assert d.to_utc(disambiguate="earlier") == UTCDateTime(
            2023, 10, 29, 0, 15
        )
        assert d.to_utc(disambiguate="later") == UTCDateTime(
            2023, 10, 29, 1, 15
        )

        assert d.to_utc(disambiguate="earlier").to_local() == d
        assert d.to_utc(disambiguate="later").to_local() == d

    @local_ams_tz()
    def test_doesnt_exist(self):
        d = LocalDateTime(2023, 3, 26, 2, 15)
        with pytest.raises(
            DoesntExistInZone, match="2023-03-26 02:15:00.*system timezone"
        ):
            d.to_utc()

        assert d.to_utc(nonexistent="earlier") == UTCDateTime(
            2023, 3, 26, 0, 15
        )
        assert d.to_utc(nonexistent="later") == UTCDateTime(2023, 3, 26, 1, 15)

        assert d.to_utc(nonexistent="earlier").to_local() == d.replace(hour=1)
        assert d.to_utc(nonexistent="later").to_local() == d.replace(hour=3)


# @local_ams_tz()
# def test_is_ambiguous():
#     assert not LocalDateTime(2020, 8, 15).is_ambiguous()
#     assert LocalDateTime(2023, 10, 29, 2, 15).is_ambiguous()


class TestToZoned:
    @local_ams_tz()
    def test_typical_time(self):
        d = LocalDateTime(2020, 8, 15, 12, 8, 30)
        assert d.to_zoned("America/New_York").exact_eq(
            ZonedDateTime(2020, 8, 15, 6, 8, 30, tz="America/New_York")
        )

    @pytest.mark.parametrize("nonexistent", ["raise", "earlier", "later"])
    @local_ams_tz()
    def test_ambiguous(self, nonexistent):
        ams = LocalDateTime(2023, 10, 29, 2, 15, 30)
        nyc = ZonedDateTime(2023, 10, 28, 20, 15, 30, tz="America/New_York")
        with pytest.raises(Ambiguous):
            ams.to_zoned("America/New_York", nonexistent=nonexistent)

        assert ams.to_zoned(
            "America/New_York", disambiguate="earlier", nonexistent=nonexistent
        ).exact_eq(nyc)

        assert ams.to_zoned(
            "America/New_York", disambiguate="later", nonexistent=nonexistent
        ).exact_eq(nyc.replace(hour=21))
        # fold doesn't affect NYC time because there's no ambiguity
        # TODO
        # assert nyc.replace(disambiguate="later").as_local() == ams

    @local_ams_tz()
    def test_non_existent(self):
        d = LocalDateTime(2023, 3, 26, 2, 15)
        with pytest.raises(DoesntExistInZone):
            d.to_zoned("Asia/Tokyo")

        assert d.to_zoned("Asia/Tokyo", nonexistent="earlier").exact_eq(
            ZonedDateTime(2023, 3, 26, 9, 15, tz="Asia/Tokyo")
        )
        assert d.to_zoned("Asia/Tokyo", nonexistent="later").exact_eq(
            ZonedDateTime(2023, 3, 26, 10, 15, tz="Asia/Tokyo")
        )
        # TODO: round-trip


def test_naive():
    d = LocalDateTime(2020, 8, 15, 12, 8, 30)
    assert d.naive() == NaiveDateTime(2020, 8, 15, 12, 8, 30)


class TestToOffset:
    @local_ams_tz()
    def test_simple(self):
        d = LocalDateTime(2020, 8, 15, 12, 8, 30)
        assert d.to_offset().exact_eq(
            OffsetDateTime(2020, 8, 15, 12, 8, 30, offset=hours(2))
        )
        assert d.to_offset(hours(0)).exact_eq(
            OffsetDateTime(2020, 8, 15, 10, 8, 30, offset=hours(0))
        )
        assert d.to_offset(hours(5)).exact_eq(
            OffsetDateTime(2020, 8, 15, 15, 8, 30, offset=hours(5))
        )

    @local_ams_tz()
    def test_ambiguous(self):
        d = LocalDateTime(2023, 10, 29, 2, 15, 30)
        assert d.to_offset(disambiguate="earlier").exact_eq(
            OffsetDateTime(2023, 10, 29, 2, 15, 30, offset=hours(2))
        )
        assert d.to_offset(disambiguate="later").exact_eq(
            OffsetDateTime(2023, 10, 29, 2, 15, 30, offset=hours(1))
        )
        with pytest.raises(Ambiguous):
            d.to_offset(disambiguate="raise")

        with pytest.raises(Ambiguous):
            # this setting should have no effect
            d.to_offset(nonexistent="earlier")

        with pytest.raises(Ambiguous):
            d.to_offset()

        assert d.to_offset(hours(3), disambiguate="earlier").exact_eq(
            OffsetDateTime(2023, 10, 29, 3, 15, 30, offset=hours(3))
        )
        assert d.to_offset(hours(3), disambiguate="later").exact_eq(
            OffsetDateTime(2023, 10, 29, 4, 15, 30, offset=hours(3))
        )

    @local_ams_tz()
    def test_non_existent(self):
        d = LocalDateTime(2023, 3, 26, 2, 15)
        with pytest.raises(
            DoesntExistInZone,
            match="2023-03-26 02:15:00 doesn't exist in the system timezone",
        ):
            d.to_offset(hours(2))

        with pytest.raises(DoesntExistInZone):
            d.to_offset(hours(2), disambiguate="later")

        assert d.to_offset(hours(2), nonexistent="earlier").exact_eq(
            OffsetDateTime(2023, 3, 26, 2, 15, offset=hours(2))
        )
        assert d.to_offset(hours(2), nonexistent="later").exact_eq(
            OffsetDateTime(2023, 3, 26, 3, 15, offset=hours(2))
        )


def test_immutable():
    d = LocalDateTime(2020, 8, 15)
    with pytest.raises(AttributeError):
        d.year = 2021  # type: ignore[misc]


def test_test_canonical_str():
    d = LocalDateTime(2020, 8, 15, 23, 12, 9, 987_654)
    expected = "2020-08-15T23:12:09.987654"
    assert str(d) == expected
    assert d.canonical_str() == expected


class TestEquality:
    def test_simple(self):
        d = LocalDateTime(2020, 8, 15, 12, 8, 30, 450)
        same = LocalDateTime(2020, 8, 15, 12, 8, 30, 450)
        different = LocalDateTime(2020, 8, 15, 12, 8, 30, 451)
        assert d == same
        assert not d != same
        assert d != different
        assert not d == different

        assert hash(d) == hash(same)
        assert hash(d) != hash(different)

    def test_notimplemented(self):
        d = LocalDateTime(2020, 8, 15)
        assert d == AlwaysEqual()
        assert not d != AlwaysEqual()
        assert d != NeverEqual()
        assert not d == NeverEqual()


class TestComparison:
    def test_with_other(self):
        d = LocalDateTime(2020, 8, 15, 12, 30)
        later = d.replace(hour=13)
        earlier = d.replace(hour=11)
        assert d < later
        assert d <= later
        assert later > d
        assert later >= d
        assert not d > later
        assert not d >= later
        assert not later < d
        assert not later <= d

        assert d > earlier
        assert d >= earlier
        assert earlier < d
        assert earlier <= d
        assert not d < earlier
        assert not d <= earlier
        assert not earlier > d
        assert not earlier >= d

    def test_notimplemented(self):
        d = LocalDateTime(2020, 8, 15)
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
            d > UTCDateTime(2020, 8, 15)  # type: ignore[operator]


class TestFromCanonicalStr:
    def test_valid(self):
        assert LocalDateTime.from_canonical_str(
            "2020-08-15T12:08:30"
        ) == LocalDateTime(2020, 8, 15, 12, 8, 30)

    def test_valid_three_fractions(self):
        assert LocalDateTime.from_canonical_str(
            "2020-08-15T12:08:30.349"
        ) == LocalDateTime(
            2020,
            8,
            15,
            12,
            8,
            30,
            349_000,
        )

    def test_valid_six_fractions(self):
        assert LocalDateTime.from_canonical_str(
            "2020-08-15T12:08:30.349123"
        ) == LocalDateTime(
            2020,
            8,
            15,
            12,
            8,
            30,
            349_123,
        )

    def test_single_space_instead_of_T(self):
        assert LocalDateTime.from_canonical_str(
            "2020-08-15 12:08:30"
        ) == LocalDateTime(2020, 8, 15, 12, 8, 30)

    def test_unpadded(self):
        with pytest.raises(InvalidFormat):
            LocalDateTime.from_canonical_str("2020-8-15T12:8:30")

    def test_overly_precise_fraction(self):
        with pytest.raises(InvalidFormat):
            LocalDateTime.from_canonical_str(
                "2020-08-15T12:08:30.123456789123"
            )

    def test_no_seconds(self):
        with pytest.raises(InvalidFormat):
            LocalDateTime.from_canonical_str("2020-08-15T12:08")

    def test_empty(self):
        with pytest.raises(InvalidFormat):
            LocalDateTime.from_canonical_str("")

    def test_garbage(self):
        with pytest.raises(InvalidFormat):
            LocalDateTime.from_canonical_str("garbage")

    @given(text())
    def test_fuzzing(self, s: str):
        with pytest.raises(InvalidFormat):
            LocalDateTime.from_canonical_str(s)


@local_nyc_tz()
def test_timestamp():
    assert LocalDateTime(1969, 12, 31, 19).timestamp() == 0
    assert LocalDateTime(2020, 8, 15, 8, 8, 30, 45).timestamp() == approx(
        1_597_493_310.000045, abs=1e-6
    )

    ambiguous = LocalDateTime(2023, 11, 5, 1, 15, 30)
    assert (
        ambiguous.timestamp(disambiguate="later")
        - ambiguous.timestamp(disambiguate="earlier")
    ) == 3600

    nonexistent = LocalDateTime(2023, 3, 12, 2, 15)
    assert (
        nonexistent.timestamp(nonexistent="later")
        - nonexistent.timestamp(nonexistent="earlier")
    ) == 3600


@local_nyc_tz()
def test_from_timestamp():
    assert LocalDateTime.from_timestamp(0) == LocalDateTime(1969, 12, 31, 19)
    assert LocalDateTime.from_timestamp(
        1_597_493_310,
    ) == LocalDateTime(2020, 8, 15, 8, 8, 30)
    with pytest.raises((OSError, OverflowError)):
        LocalDateTime.from_timestamp(1_000_000_000_000_000_000)


def test_repr():
    d = LocalDateTime(2023, 3, 26, 2, 15)
    assert repr(d) == "whenever.LocalDateTime(2023-03-26T02:15:00)"


def test_py():
    d = LocalDateTime(2020, 8, 15, 23, 12, 9, 987_654)
    py = d.py
    assert py == py_datetime(2020, 8, 15, 23, 12, 9, 987_654)
    assert py.fold == 0


class TestFromPy:
    def test_basic(self):
        d = py_datetime(2020, 8, 15, 23)
        assert LocalDateTime.from_py(d) == LocalDateTime(2020, 8, 15, 23)

    # TODO: disallow fold--also for naive

    def test_wrong_tzinfo(self):
        with pytest.raises(ValueError, match="utc"):
            LocalDateTime.from_py(
                py_datetime(2020, 8, 15, 23, tzinfo=timezone.utc)
            )


@local_nyc_tz()
def test_now():
    now = LocalDateTime.now()
    py_now = py_datetime.now(ZoneInfo("America/New_York")).replace(tzinfo=None)
    assert py_now - now.py < timedelta(seconds=1)


def test_weakref():
    d = LocalDateTime(2020, 8, 15)
    ref = weakref.ref(d)
    assert ref() == d


def test_passthrough_datetime_attrs():
    d = LocalDateTime(2020, 8, 15, 12, 43)
    assert d.resolution == py_datetime.resolution
    assert d.weekday() == d.py.weekday()
    assert d.date() == d.py.date()
    time = d.time()
    assert time.tzinfo is None
    assert time == d.py.time()


class TestReplace:
    def test_basics(self):
        d = LocalDateTime(2020, 8, 15, 23, 12, 9, 987_654)
        assert d.replace(year=2021) == LocalDateTime(
            2021, 8, 15, 23, 12, 9, 987_654
        )
        assert d.replace(month=9) == LocalDateTime(
            2020, 9, 15, 23, 12, 9, 987_654
        )
        assert d.replace(day=16) == LocalDateTime(
            2020, 8, 16, 23, 12, 9, 987_654
        )
        assert d.replace(hour=0) == LocalDateTime(
            2020, 8, 15, 0, 12, 9, 987_654
        )
        assert d.replace(minute=0) == LocalDateTime(
            2020, 8, 15, 23, 0, 9, 987_654
        )
        assert d.replace(second=0) == LocalDateTime(
            2020, 8, 15, 23, 12, 0, 987_654
        )
        assert d.replace(microsecond=0) == LocalDateTime(
            2020, 8, 15, 23, 12, 9, 0
        )

    def test_invalid(self):
        d = LocalDateTime(2020, 8, 15, 23, 12, 9, 987_654)
        with pytest.raises(TypeError, match="tzinfo"):
            d.replace(tzinfo=timezone.utc)  # type: ignore[call-arg]
        with pytest.raises(TypeError, match="fold"):
            d.replace(fold=1)  # type: ignore[call-arg]
        with pytest.raises(TypeError, match="foo"):
            d.replace(foo=1)  # type: ignore[call-arg]
        with pytest.raises(TypeError, match="disambiguate"):
            d.replace(disambiguate="raise")  # type: ignore[call-arg]


def test_pickle():
    d = LocalDateTime(2020, 8, 15, 23, 12, 9, 987_654)
    dumped = pickle.dumps(d)
    assert len(dumped) <= len(pickle.dumps(d.py)) + 15
    assert pickle.loads(pickle.dumps(d)) == d


def test_old_pickle_data_remains_unpicklable():
    # Don't update this value -- the whole idea is that it's a pickle at
    # a specific version of the library.
    dumped = (
        b"\x80\x04\x954\x00\x00\x00\x00\x00\x00\x00\x8c\x08whenever\x94\x8c\x0c_unp"
        b"kl_local\x94\x93\x94(M\xe4\x07K\x08K\x0fK\x17K\x0cK\tJ\x06\x12\x0f\x00t\x94"
        b"R\x94."
    )
    assert pickle.loads(dumped) == LocalDateTime(
        2020, 8, 15, 23, 12, 9, 987_654
    )


def test_copy():
    d = LocalDateTime(2020, 8, 15, 23, 12, 9, 987_654)
    assert copy(d) is d
    assert deepcopy(d) is d
