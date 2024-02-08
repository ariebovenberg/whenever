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
    InvalidOffsetForZone,
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
    ZoneInfo,
    local_ams_tz,
    local_nyc_tz,
)


class TestInit:
    @local_ams_tz()
    def test_basic(self):
        d = LocalDateTime(2020, 8, 15, 5, 12, 30, 450)

        assert d.year == 2020
        assert d.month == 8
        assert d.day == 15
        assert d.hour == 5
        assert d.minute == 12
        assert d.second == 30
        assert d.microsecond == 450
        assert d.fold == 0
        assert d.offset == hours(2)

    def test_optionality(self):
        assert (
            LocalDateTime(2020, 8, 15, 12)
            == LocalDateTime(2020, 8, 15, 12, 0)
            == LocalDateTime(2020, 8, 15, 12, 0, 0)
            == LocalDateTime(2020, 8, 15, 12, 0, 0, 0)
            == LocalDateTime(2020, 8, 15, 12, 0, 0, 0, disambiguate="raise")
        )

    def test_ambiguous(self):
        d = LocalDateTime(2023, 10, 29, 2, 15, disambiguate="earlier")
        assert d < LocalDateTime(2023, 10, 29, 2, 15, disambiguate="later")

        with pytest.raises(Ambiguous) as e:
            LocalDateTime(2023, 10, 29, 2, 15, disambiguate="raise")
        assert (
            str(e.value)
            == "2023-10-29 02:15:00 is ambiguous in the system timezone"
        )

        with pytest.raises(Ambiguous) as e:
            LocalDateTime(2023, 10, 29, 2, 15)
        assert (
            str(e.value)
            == "2023-10-29 02:15:00 is ambiguous in the system timezone"
        )

    @local_ams_tz()
    def test_nonexistent(self):
        with pytest.raises(DoesntExistInZone) as e:
            LocalDateTime(2023, 3, 26, 2, 15, 30)
        assert (
            str(e.value)
            == "2023-03-26 02:15:30 doesn't exist in the system timezone"
        )


@local_nyc_tz()
def test_offset_nonexistent():
    d = LocalDateTime(2023, 3, 26, 2, 15)
    with local_ams_tz(), pytest.raises(
        DoesntExistInZone,
        match="2023-03-26 02:15:00 doesn't exist in the system timezone",
    ):
        d.offset


class TestToUTC:
    @local_ams_tz()
    def test_common_time(self):
        d = LocalDateTime(2020, 8, 15, 11)
        assert d.as_utc().exact_eq(UTCDateTime(2020, 8, 15, 9))

    @local_ams_tz()
    def test_amibiguous_time(self):
        d = LocalDateTime(2023, 10, 29, 2, 15, disambiguate="earlier")
        assert d.as_utc() == UTCDateTime(2023, 10, 29, 0, 15)
        assert (
            d.replace(disambiguate="later")
            .as_utc()
            .exact_eq(UTCDateTime(2023, 10, 29, 1, 15))
        )

    @local_nyc_tz()
    def test_doesnt_exist(self):
        d = LocalDateTime(2023, 3, 26, 2, 15)
        with local_ams_tz(), pytest.raises(
            DoesntExistInZone,
            match="2023-03-26 02:15:00 doesn't exist in the system timezone",
        ):
            d.as_utc()


def test_naive():
    d = LocalDateTime(2020, 8, 15, 12, 8, 30)
    assert d.naive() == NaiveDateTime(2020, 8, 15, 12, 8, 30)


@local_ams_tz()
def test_to_zoned():
    assert (
        LocalDateTime(2020, 8, 15, 12, 8, 30)
        .as_zoned("America/New_York")
        .exact_eq(ZonedDateTime(2020, 8, 15, 6, 8, 30, tz="America/New_York"))
    )
    ams = LocalDateTime(2023, 10, 29, 2, 15, 30, disambiguate="earlier")
    nyc = ZonedDateTime(2023, 10, 28, 20, 15, 30, tz="America/New_York")
    assert ams.as_zoned("America/New_York").exact_eq(nyc)
    assert (
        ams.replace(disambiguate="later")
        .as_zoned("America/New_York")
        .exact_eq(nyc.replace(hour=21))
    )
    assert nyc.as_local() == ams
    assert nyc.replace(hour=21).as_local() == ams.replace(disambiguate="later")
    # fold doesn't affect NYC time because there's no ambiguity
    assert nyc.replace(disambiguate="later").as_local() == ams

    # non-existent time
    d = LocalDateTime(2023, 3, 12, 2, 15)
    with local_nyc_tz(), pytest.raises(DoesntExistInZone) as e:
        d.as_zoned("Europe/London")
    assert (
        str(e.value)
        == "2023-03-12 02:15:00 doesn't exist in the system timezone"
    )


class TestToOffset:
    @local_ams_tz()
    def test_simple(self):
        assert (
            LocalDateTime(2020, 8, 15, 12, 8, 30)
            .as_offset()
            .exact_eq(OffsetDateTime(2020, 8, 15, 12, 8, 30, offset=hours(2)))
        )

    @local_ams_tz()
    def test_ambiguous(self):
        assert (
            LocalDateTime(2023, 10, 29, 2, 15, 30, disambiguate="earlier")
            .as_offset()
            .exact_eq(OffsetDateTime(2023, 10, 29, 2, 15, 30, offset=hours(2)))
        )
        assert (
            LocalDateTime(2023, 10, 29, 2, 15, 30, disambiguate="later")
            .as_offset()
            .exact_eq(OffsetDateTime(2023, 10, 29, 2, 15, 30, offset=hours(1)))
        )

    @local_ams_tz()
    def test_custom_offset(self):
        d = LocalDateTime(2020, 8, 15, 12, 30)
        assert d.as_offset(hours(3)).exact_eq(
            OffsetDateTime(2020, 8, 15, 13, 30, offset=hours(3))
        )
        assert d.as_offset(hours(0)).exact_eq(
            OffsetDateTime(2020, 8, 15, 10, 30, offset=hours(0))
        )

    @local_nyc_tz()
    def test_doesnt_exist(self):
        d = LocalDateTime(2023, 3, 26, 2, 15)
        with local_ams_tz(), pytest.raises(DoesntExistInZone) as e:
            d.as_offset()
        assert (
            str(e.value)
            == "2023-03-26 02:15:00 doesn't exist in the system timezone"
        )


def test_to_local():
    d = LocalDateTime(2020, 8, 15, 12, 8, 30)
    assert d.as_local() is d


def test_immutable():
    d = LocalDateTime(2020, 8, 15)
    with pytest.raises(AttributeError):
        d.year = 2021  # type: ignore[misc]


class TestCanonicalStr:
    @local_ams_tz()
    def test_simple(self):
        d = LocalDateTime(2020, 8, 15, 23, 12, 9, 987_654)
        expected = "2020-08-15T23:12:09.987654+02:00"
        assert str(d) == expected
        assert d.canonical_str() == expected

    @local_ams_tz()
    def test_ambiguous(self):
        d = LocalDateTime(2023, 10, 29, 2, 15, 30, disambiguate="earlier")
        expected = "2023-10-29T02:15:30+02:00"
        assert str(d) == expected
        assert d.canonical_str() == expected
        d2 = d.replace(disambiguate="later")
        assert str(d2) == expected.replace("+02:00", "+01:00")
        assert d2.canonical_str() == expected.replace("+02:00", "+01:00")

    @local_nyc_tz()
    def test_doesnt_exist(self):
        d = LocalDateTime(2023, 3, 26, 2, 15)
        with local_ams_tz(), pytest.raises(
            DoesntExistInZone,
            match="2023-03-26 02:15:00 doesn't exist in the system timezone",
        ):
            str(d)
        with local_ams_tz(), pytest.raises(
            DoesntExistInZone,
            match="2023-03-26 02:15:00 doesn't exist in the system timezone",
        ):
            d.canonical_str()


class TestEquality:
    def test_same_exact(self):
        d = LocalDateTime(2020, 8, 15, 12, 8, 30, 450)
        same = LocalDateTime(2020, 8, 15, 12, 8, 30, 450)
        assert d == same
        assert not d != same

    def test_same_utc(self):
        d = LocalDateTime(2020, 8, 15, 12, 8, 30, 450)
        same = LocalDateTime(2020, 8, 15, 12, 8, 30, 450)
        assert d == same
        assert not d != same

    @local_ams_tz()
    def test_amibiguous(self):
        d = LocalDateTime(2023, 10, 29, 2, 15, 30, disambiguate="earlier")
        same = LocalDateTime(2023, 10, 29, 2, 15, 30, disambiguate="later")
        assert d != same
        assert not d == same

    def test_notimplemented(self):
        d = LocalDateTime(2020, 8, 15)
        assert d == AlwaysEqual()
        assert not d != AlwaysEqual()
        assert d != NeverEqual()
        assert not d == NeverEqual()


class TestComparison:
    @local_nyc_tz()
    def test_different_timezones(self):
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

    @local_ams_tz()
    def test_same_timezone_fold(self):
        d = LocalDateTime(2023, 10, 29, 2, 15, 30, disambiguate="earlier")
        later = d.replace(disambiguate="later")
        assert d < later
        assert d <= later
        assert later > d
        assert later >= d
        assert not d > later
        assert not d >= later
        assert not later < d
        assert not later <= d

    @local_ams_tz()
    def test_offset(self):
        d = LocalDateTime(2020, 8, 15, 12, 30)
        same = d.as_offset(hours(5))
        later = same.replace(minute=31)
        earlier = same.replace(minute=29)
        assert d >= same
        assert d <= same
        assert not d > same
        assert not d < same

        assert d < later
        assert d <= later
        assert not d > later
        assert not d >= later

        assert d > earlier
        assert d >= earlier
        assert not d < earlier
        assert not d <= earlier

    @local_ams_tz()
    def test_zoned(self):
        d = LocalDateTime(2020, 8, 15, 12, 30)
        same = d.as_zoned("America/New_York")
        later = same.replace(minute=31)
        earlier = same.replace(minute=29)
        assert d >= same
        assert d <= same
        assert not d > same
        assert not d < same

        assert d < later
        assert d <= later
        assert not d > later
        assert not d >= later

        assert d > earlier
        assert d >= earlier
        assert not d < earlier
        assert not d <= earlier

    @local_ams_tz()
    def test_utc(self):
        d = LocalDateTime(2020, 8, 15, 12, 30)
        same = d.as_utc()
        later = same.replace(minute=31)
        earlier = same.replace(minute=29)
        assert d >= same
        assert d <= same
        assert not d > same
        assert not d < same

        assert d < later
        assert d <= later
        assert not d > later
        assert not d >= later

        assert d > earlier
        assert d >= earlier
        assert not d < earlier
        assert not d <= earlier

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


def test_exact_equality():
    a = LocalDateTime(2020, 8, 15, 12, 8, 30, 450)
    same = a.replace()
    same_utc = a.replace(disambiguate="later")
    different = a.replace(hour=13)

    assert a.exact_eq(same)
    assert same.exact_eq(a)
    assert not a.exact_eq(same_utc)
    assert not same_utc.exact_eq(a)
    assert not a.exact_eq(different)
    assert not different.exact_eq(a)


def test_unhashable():
    d = LocalDateTime(2020, 8, 15)
    with pytest.raises(TypeError):
        hash(d)


@local_ams_tz()
def test_is_ambiguous():
    assert not LocalDateTime(2020, 8, 15, 12, 8, 30).disambiguated()
    assert LocalDateTime(
        2023, 10, 29, 2, 15, 30, disambiguate="later"
    ).disambiguated()

    # non-existent isn't ambiguous
    d = LocalDateTime(2023, 3, 12, 2, 15)
    with local_nyc_tz():
        assert not d.disambiguated()


@local_nyc_tz()
def test_exists():
    d = LocalDateTime(2023, 3, 26, 2, 15)
    assert d.exists()
    with local_ams_tz():
        assert not d.exists()

    # ambiguous does exist
    assert LocalDateTime(2023, 11, 5, 1, 15, disambiguate="later").exists()


class TestFromCanonicalStr:
    @local_ams_tz()
    def test_valid(self):
        assert LocalDateTime.from_canonical_str(
            "2020-08-15T12:08:30+02:00"
        ).exact_eq(LocalDateTime(2020, 8, 15, 12, 8, 30))

    @local_ams_tz()
    def test_offset_determines_fold(self):
        assert LocalDateTime.from_canonical_str(
            "2023-10-29T02:15:30+02:00"
        ).exact_eq(
            LocalDateTime(2023, 10, 29, 2, 15, 30, disambiguate="earlier")
        )
        assert LocalDateTime.from_canonical_str(
            "2023-10-29T02:15:30+01:00"
        ).exact_eq(
            LocalDateTime(2023, 10, 29, 2, 15, 30, disambiguate="later")
        )

    @local_ams_tz()
    def test_offset_timezone_mismatch(self):
        with pytest.raises(InvalidOffsetForZone):
            # at the exact DST transition
            LocalDateTime.from_canonical_str("2023-10-29T02:15:30+03:00")
        with pytest.raises(InvalidOffsetForZone):
            # some other time in the year
            LocalDateTime.from_canonical_str("2020-08-15T12:08:30+01:00:01")

    @local_ams_tz()
    def test_valid_three_fractions(self):
        assert LocalDateTime.from_canonical_str(
            "2020-08-15T12:08:30.349+02:00"
        ).exact_eq(
            LocalDateTime(
                2020,
                8,
                15,
                12,
                8,
                30,
                349_000,
            )
        )

    @local_ams_tz()
    def test_valid_six_fractions(self):
        assert LocalDateTime.from_canonical_str(
            "2020-08-15T12:08:30.349123+02:00"
        ).exact_eq(
            LocalDateTime(
                2020,
                8,
                15,
                12,
                8,
                30,
                349_123,
            )
        )

    @local_ams_tz()
    def test_single_space_instead_of_T(self):
        assert LocalDateTime.from_canonical_str(
            "2020-08-15 12:08:30+02:00"
        ).exact_eq(LocalDateTime(2020, 8, 15, 12, 8, 30))

    @local_ams_tz()
    def test_unpadded(self):
        with pytest.raises(InvalidFormat):
            LocalDateTime.from_canonical_str("2020-8-15T12:8:30+02:00")

    @local_ams_tz()
    def test_overly_precise_fraction(self):
        with pytest.raises(InvalidFormat):
            LocalDateTime.from_canonical_str(
                "2020-08-15T12:08:30.123456789123+02:00"
            )

    @local_ams_tz()
    def test_invalid_offset(self):
        with pytest.raises(InvalidOffsetForZone):
            LocalDateTime.from_canonical_str("2020-08-15T12:08:30-20:00")

    def test_no_offset(self):
        with pytest.raises(InvalidFormat):
            LocalDateTime.from_canonical_str("2020-08-15T12:08:30")

    def test_no_timezone(self):
        with pytest.raises(InvalidFormat):
            LocalDateTime.from_canonical_str("2020-08-15T12:08:30")

    def test_no_seconds(self):
        with pytest.raises(InvalidFormat):
            LocalDateTime.from_canonical_str("2020-08-15T12:08+02:00")

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

    ambiguous = LocalDateTime(2023, 11, 5, 1, 15, 30, disambiguate="earlier")
    assert (
        ambiguous.timestamp()
        != ambiguous.replace(disambiguate="later").timestamp()
    )


@local_nyc_tz()
def test_from_timestamp():
    assert LocalDateTime.from_timestamp(0).exact_eq(
        LocalDateTime(1969, 12, 31, 19)
    )
    assert LocalDateTime.from_timestamp(
        1_597_493_310,
    ).exact_eq(LocalDateTime(2020, 8, 15, 8, 8, 30))
    with pytest.raises((OSError, OverflowError)):
        LocalDateTime.from_timestamp(1_000_000_000_000_000_000)


@local_nyc_tz()
def test_repr():
    d = LocalDateTime(2023, 3, 26, 2, 15)
    assert repr(d) == "whenever.LocalDateTime(2023-03-26T02:15:00-04:00)"

    with local_ams_tz():
        assert (
            repr(d)
            == "whenever.LocalDateTime(2023-03-26T02:15:00[nonexistent])"
        )


def test_py():
    d = LocalDateTime(2020, 8, 15, 23, 12, 9, 987_654)
    py = d.py
    assert py == py_datetime(2020, 8, 15, 23, 12, 9, 987_654)
    assert py.fold == 0


class TestFromPy:
    def test_basic(self):
        d = py_datetime(2020, 8, 15, 23)
        assert LocalDateTime.from_py(d).exact_eq(
            LocalDateTime(2020, 8, 15, 23)
        )

    def test_disambiguated(self):
        d = py_datetime(2023, 10, 29, 2, 15, 30, fold=1)
        assert LocalDateTime.from_py(d).exact_eq(
            LocalDateTime(2023, 10, 29, 2, 15, 30, disambiguate="later")
        )

    def test_wrong_tzinfo(self):
        with pytest.raises(ValueError, match="utc"):
            LocalDateTime.from_py(
                py_datetime(2020, 8, 15, 23, tzinfo=timezone.utc)
            )

    @local_ams_tz()
    def test_doesnt_exist(self):
        with pytest.raises(
            DoesntExistInZone,
            match="2023-03-26 02:15:00 doesn't exist in the system timezone",
        ):
            LocalDateTime.from_py(py_datetime(2023, 3, 26, 2, 15))


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
    assert d.tzinfo is d.py.tzinfo is None


class TestReplace:
    def test_basics(self):
        d = LocalDateTime(2020, 8, 15, 23, 12, 9, 987_654)
        assert d.replace(year=2021).exact_eq(
            LocalDateTime(2021, 8, 15, 23, 12, 9, 987_654)
        )
        assert d.replace(month=9).exact_eq(
            LocalDateTime(2020, 9, 15, 23, 12, 9, 987_654)
        )
        assert d.replace(day=16).exact_eq(
            LocalDateTime(2020, 8, 16, 23, 12, 9, 987_654)
        )
        assert d.replace(hour=0).exact_eq(
            LocalDateTime(2020, 8, 15, 0, 12, 9, 987_654)
        )
        assert d.replace(minute=0).exact_eq(
            LocalDateTime(2020, 8, 15, 23, 0, 9, 987_654)
        )
        assert d.replace(second=0).exact_eq(
            LocalDateTime(2020, 8, 15, 23, 12, 0, 987_654)
        )
        assert d.replace(microsecond=0).exact_eq(
            LocalDateTime(2020, 8, 15, 23, 12, 9, 0)
        )

    def test_invalid(self):
        d = LocalDateTime(2020, 8, 15, 23, 12, 9, 987_654)
        with pytest.raises(TypeError, match="tzinfo"):
            d.replace(tzinfo=timezone.utc)  # type: ignore[call-arg]
        with pytest.raises(TypeError, match="fold"):
            d.replace(fold=1)  # type: ignore[call-arg]
        with pytest.raises(TypeError, match="foo"):
            d.replace(foo=1)  # type: ignore[call-arg]

    @local_ams_tz()
    def test_disambiguate(self):
        d = LocalDateTime(2023, 10, 29, 2, 15, 30, disambiguate="earlier")
        with pytest.raises(
            Ambiguous,
            match="2023-10-29 02:15:30 is ambiguous in the system timezone",
        ):
            d.replace(disambiguate="raise")
        with pytest.raises(
            Ambiguous,
            match="2023-10-29 02:15:30 is ambiguous in the system timezone",
        ):
            d.replace()
        assert d.replace(disambiguate="later").exact_eq(
            LocalDateTime(2023, 10, 29, 2, 15, 30, disambiguate="later")
        )
        assert d.replace(disambiguate="earlier").exact_eq(d)

    @local_ams_tz()
    def test_nonexistent(self):
        d = LocalDateTime(2023, 3, 26, 1, 15, 30)
        with pytest.raises(
            DoesntExistInZone,
            match="2023-03-26 02:15:30 doesn't exist in the system timezone",
        ):
            d.replace(hour=2)


class TestAdd:
    @local_ams_tz()
    def test_zero_timedelta(self):
        d = LocalDateTime(2020, 8, 15, 23, 12, 9, 987_654)
        assert (d + timedelta()).exact_eq(d)

    @local_ams_tz()
    def test_ambiguous(self):
        d = LocalDateTime(2023, 10, 29, 2, 15, 30, disambiguate="earlier")
        assert (d + minutes(10)).exact_eq(
            d.replace(minute=25, disambiguate="earlier")
        )
        assert (d.replace(disambiguate="later") + minutes(10)).exact_eq(
            d.replace(disambiguate="later", minute=25)
        )

    @local_nyc_tz()
    def test_non_existent(self):
        d = LocalDateTime(2023, 3, 26, 2, 15)
        with local_ams_tz(), pytest.raises(
            DoesntExistInZone,
            match="2023-03-26 02:15:00 doesn't exist in the system timezone",
        ):
            d + minutes(10)

    @local_ams_tz()
    def test_accounts_for_dst(self):
        d = LocalDateTime(2023, 10, 29, 2, 15, 30, disambiguate="earlier")
        assert (d + hours(24)).exact_eq(LocalDateTime(2023, 10, 30, 1, 15, 30))
        assert (d.replace(disambiguate="later") + hours(24)).exact_eq(
            LocalDateTime(2023, 10, 30, 2, 15, 30)
        )

    def test_add_not_implemented(self):
        d = LocalDateTime(2020, 8, 15)
        with pytest.raises(TypeError, match="unsupported operand type"):
            d + 42  # type: ignore[operator]


class TestSubtract:
    @local_ams_tz()
    def test_zero_timedelta(self):
        d = LocalDateTime(2020, 8, 15, 23, 12, 9, 987_654)
        assert (d - timedelta()).exact_eq(d)

    @local_ams_tz()
    def test_ambiguous(self):
        d = LocalDateTime(2023, 10, 29, 2, 15, 30, disambiguate="earlier")
        assert (d - minutes(10)).exact_eq(
            d.replace(minute=5, disambiguate="earlier")
        )
        assert (d.replace(disambiguate="later") - minutes(10)).exact_eq(
            d.replace(disambiguate="later", minute=5)
        )

    @local_ams_tz()
    def test_accounts_for_dst(self):
        d = LocalDateTime(2023, 10, 29, 2, 15, 30, disambiguate="earlier")
        assert (d - hours(24)).exact_eq(LocalDateTime(2023, 10, 28, 2, 15, 30))
        assert (d.replace(disambiguate="later") - hours(24)).exact_eq(
            LocalDateTime(2023, 10, 28, 3, 15, 30)
        )

    @local_nyc_tz()
    def test_non_existent(self):
        d = LocalDateTime(2023, 3, 26, 2, 15)
        with local_ams_tz(), pytest.raises(
            DoesntExistInZone,
            match="2023-03-26 02:15:00 doesn't exist in the system timezone",
        ):
            d - minutes(10)
        with local_ams_tz(), pytest.raises(
            DoesntExistInZone,
            match="2023-03-26 02:15:00 doesn't exist in the system timezone",
        ):
            d - LocalDateTime(2023, 1, 1)

    @local_ams_tz()
    def test_subtract_not_implemented(self):
        d = LocalDateTime(2020, 8, 15)
        with pytest.raises(TypeError, match="unsupported operand type"):
            d - 42  # type: ignore[operator]

    @local_ams_tz()
    def test_subtract_datetime(self):
        d = LocalDateTime(2023, 10, 29, 5)
        other = LocalDateTime(2023, 10, 28, 3)
        assert d - other == hours(27)
        assert other - d == timedelta(hours=-27)

    @local_ams_tz()
    def test_subtract_amibiguous_datetime(self):
        d = LocalDateTime(2023, 10, 29, 2, 15, disambiguate="earlier")
        other = LocalDateTime(2023, 10, 28, 3, 15)
        assert d - other == hours(23)
        assert d.replace(disambiguate="later") - other == hours(24)
        assert other - d == hours(-23)
        assert other - d.replace(disambiguate="later") == hours(-24)

    @local_ams_tz()
    def test_utc(self):
        d = LocalDateTime(2023, 10, 29, 2, disambiguate="earlier")
        assert d - UTCDateTime(2023, 10, 28, 20) == hours(4)
        assert d.replace(disambiguate="later") - UTCDateTime(
            2023, 10, 28, 20
        ) == hours(5)

    @local_ams_tz()
    def test_offset(self):
        d = LocalDateTime(2023, 10, 29, 2, disambiguate="earlier")
        assert d - OffsetDateTime(2023, 10, 28, 22, offset=hours(1)) == hours(
            3
        )
        assert d.replace(disambiguate="later") - OffsetDateTime(
            2023, 10, 28, 22, offset=hours(1)
        ) == hours(4)

    @local_ams_tz()
    def test_zoned(self):
        d = LocalDateTime(2023, 10, 29, 2, disambiguate="earlier")
        assert d - ZonedDateTime(
            2023, 10, 28, 17, tz="America/New_York"
        ) == hours(3)
        assert d.replace(disambiguate="later") - ZonedDateTime(
            2023, 10, 28, 17, tz="America/New_York"
        ) == hours(4)


def test_pickle():
    d = LocalDateTime(2020, 8, 15, 23, 12, 9, 987_654)
    dumped = pickle.dumps(d)
    assert len(dumped) <= len(pickle.dumps(d.py)) + 15
    assert pickle.loads(pickle.dumps(d)) == d


def test_old_pickle_data_remains_unpicklable():
    # Don't update this value -- the whole idea is that it's a pickle at
    # a specific version of the library.
    dumped = (
        b"\x80\x04\x956\x00\x00\x00\x00\x00\x00\x00\x8c\x08whenever\x94\x8c\x0c_unp"
        b"kl_local\x94\x93\x94(M\xe4\x07K\x08K\x0fK\x17K\x0cK\tJ\x06\x12\x0f\x00K\x00"
        b"t\x94R\x94."
    )
    assert pickle.loads(dumped) == LocalDateTime(
        2020, 8, 15, 23, 12, 9, 987_654
    )


def test_copy():
    d = LocalDateTime(2020, 8, 15, 23, 12, 9, 987_654)
    assert copy(d) is d
    assert deepcopy(d) is d
