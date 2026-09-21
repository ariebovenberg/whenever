import pickle
import re
import shutil
import warnings
from datetime import (
    datetime as py_datetime,
    timedelta as py_timedelta,
    timezone as py_timezone,
)
from fractions import Fraction
from pathlib import Path
from typing import Any, Literal, Sequence, cast
from zoneinfo import (
    ZoneInfo,
    available_timezones as zoneinfo_available_timezones,
    reset_tzpath as zoneinfo_reset_tzpath,
)

import pytest
from hypothesis import given
from hypothesis.strategies import text
from whenever import (
    MONDAY,
    SATURDAY,
    SYSTEM_TZ,
    Date,
    ImplicitDisambiguationWarning,
    Instant,
    InvalidOffsetError,
    ItemizedDateDelta,
    ItemizedDelta,
    OffsetDateTime,
    PlainDateTime,
    RepeatedTime,
    SkippedTime,
    Time,
    TimeDelta,
    TimeZoneNotFoundError,
    ZonedDateTime,
    hours,
    milliseconds,
    minutes,
    patch_current_time,
    reset_system_tz,
)

from .common import (
    AMS_TZ_POSIX,
    AMS_TZ_RAWFILE,
    AMS_TZ_RAWFILE_DST_LATE,
    DatetimeSubclass,
    Idx,
    create_zdt,
    system_tz,
    tz_rules_from_file,
    warns_here,
)

try:
    import tzdata  # noqa
except ImportError:
    HAS_TZDATA = False
else:
    HAS_TZDATA = True

TEST_DIR = Path(__file__).parent

_NEEDS_TZDATA = pytest.mark.skipif(
    not HAS_TZDATA, reason="tzdata not installed"
)
_NEEDS_CASABLANCA = pytest.mark.skipif(
    not HAS_TZDATA
    or "Africa/Casablanca" not in zoneinfo_available_timezones(),
    reason="tzdata or Africa/Casablanca not available",
)

ZDT1 = create_zdt(
    2020,
    8,
    15,
    23,
    12,
    9,
    nanosecond=987_654_321,
    tz="Europe/Amsterdam",
)
ZDT2 = create_zdt(
    1900,
    1,
    1,
    tz="Europe/Dublin",
)
ZDT3 = create_zdt(
    1995,
    12,
    4,
    23,
    12,
    30,
    tz="America/New_York",
)
ZDT_POSIX = create_zdt(
    2020, 8, 15, 23, 12, 9, nanosecond=987_654_321, tz=AMS_TZ_POSIX
)
ZDT_RAWFILE = create_zdt(
    2020, 8, 15, 23, 12, 9, nanosecond=987_654_321, tz=AMS_TZ_RAWFILE
)


class TestInit:
    def test_unambiguous(self):
        zone = "America/New_York"
        d = ZonedDateTime(2020, 8, 15, 5, 12, 30, nanosecond=450, tz=zone)

        assert d.year == 2020
        assert d.month == 8
        assert d.day == 15
        assert d.hour == 5
        assert d.minute == 12
        assert d.second == 30
        assert d.nanosecond == 450
        assert d.tz_id == zone

    def test_implicit_disambiguation_warning(self):
        with warns_here(ImplicitDisambiguationWarning) as caught:
            result = ZonedDateTime(2023, 10, 29, 2, 15, tz="Europe/Amsterdam")

        assert result == ZonedDateTime(
            2023,
            10,
            29,
            2,
            15,
            tz="Europe/Amsterdam",
            disambiguation="compatible",
        )
        message = str(caught[0].message)
        assert "repeated or skipped" in message
        assert "wrong instant" in message
        assert "pass disambiguation=" in message
        assert "/guide/resolving-local-times.html" in message

    def test_explicit_compatible_does_not_warn(self):
        with warnings.catch_warnings():
            warnings.simplefilter("error", ImplicitDisambiguationWarning)
            ZonedDateTime(
                2023,
                10,
                29,
                2,
                15,
                tz="Europe/Amsterdam",
                disambiguation="compatible",
            )

    def test_none_disambiguation_is_invalid(self):
        with pytest.raises(ValueError, match="disambiguation"):
            ZonedDateTime(
                2023,
                10,
                29,
                2,
                15,
                tz="Europe/Amsterdam",
                disambiguation=None,  # type: ignore[call-overload]
            )

    def test_repeated_time(self):
        kwargs: dict[str, Any] = dict(
            year=2023,
            month=10,
            day=29,
            hour=2,
            minute=15,
            second=30,
            tz="Europe/Amsterdam",
        )

        with warns_here(ImplicitDisambiguationWarning):
            assert ZonedDateTime(**kwargs).strict_eq(
                ZonedDateTime(**kwargs, disambiguation="compatible")
            )

        with pytest.raises(
            RepeatedTime,
            match="2023-10-29 02:15:30 is repeated in time zone 'Europe/Amsterdam'",
        ):
            ZonedDateTime(**kwargs, disambiguation="raise")

        assert (
            ZonedDateTime(**kwargs, disambiguation="earlier").offset
            > ZonedDateTime(**kwargs, disambiguation="later").offset
        )
        assert ZonedDateTime(**kwargs, disambiguation="compatible").strict_eq(
            ZonedDateTime(**kwargs, disambiguation="earlier")
        )

    def test_invalid_zone(self):
        with pytest.raises(
            TypeError, match="^tz must be a string or SYSTEM_TZ$"
        ):
            ZonedDateTime(
                2020,
                8,
                15,
                5,
                12,
                tz=hours(34),
            )

    def test_optionality(self):
        tz = "America/New_York"
        assert ZonedDateTime(2020, 8, 15, 12, tz=tz).strict_eq(
            ZonedDateTime(
                2020,
                8,
                15,
                12,
                0,
                0,
                nanosecond=0,
                tz=tz,
                disambiguation="raise",
            )
        )

    def test_tz_required(self):
        with pytest.raises(
            TypeError, match=r"missing 1 required keyword-only argument: 'tz'$"
        ):
            ZonedDateTime(2020, 8, 15, 12)  # type: ignore[call-overload]

    def test_single_argument_wrong_type(self):
        with pytest.raises(
            TypeError,
            match=r"^ZonedDateTime\(\) requires an ISO 8601 string or datetime.datetime$",
        ):
            ZonedDateTime(None)  # type: ignore[call-overload]

    @pytest.mark.parametrize(
        "args, kwargs",
        [
            ((2020, 8, 15, 5, 12, 30, 450), {"tz": "Europe/Amsterdam"}),
            ((2020, 8, 15, 5, 12, 30, "Europe/Amsterdam"), {}),
            (
                (),
                {"iso_string": "2020-08-15T05:12:30+02:00[Europe/Amsterdam]"},
            ),
            (
                (),
                {
                    "py_datetime": py_datetime(
                        2020, 8, 15, tzinfo=ZoneInfo("Europe/Amsterdam")
                    )
                },
            ),
        ],
    )
    def test_parameter_kinds(self, args, kwargs):
        with pytest.raises(TypeError):
            ZonedDateTime(*args, **kwargs)

    def test_invalid_disambiguation_with_settled_offset(self):
        # the written offset settles the instant, but the policy is
        # still validated
        with pytest.raises(
            ValueError, match=r"^invalid disambiguation: 'bogus'$"
        ):
            ZonedDateTime(
                "2023-10-29T02:30:00+01:00[Europe/Amsterdam]",
                disambiguation="bogus",  # type: ignore[call-overload]
            )
        with pytest.raises(
            ValueError, match=r"^invalid disambiguation: 'bogus'$"
        ):
            ZonedDateTime(
                py_datetime(
                    2023, 10, 29, 2, 30, tzinfo=ZoneInfo("Europe/Amsterdam")
                ),
                disambiguation="bogus",  # type: ignore[call-overload]
            )

    def test_out_of_range_due_to_offset(self):
        with pytest.raises((ValueError, OverflowError), match="range|year"):
            ZonedDateTime(1, 1, 1, tz="Asia/Tokyo")

        with pytest.raises((ValueError, OverflowError), match="range|year"):
            ZonedDateTime(9999, 12, 31, 23, tz="America/New_York")

    def test_invalid(self):
        with pytest.raises(ValueError):
            ZonedDateTime(
                2020,
                8,
                15,
                12,
                8,
                30,
                nanosecond=1_000_000_000,
                tz="Europe/Amsterdam",
            )

    def test_skipped(self):
        kwargs: dict[str, Any] = dict(
            year=2023,
            month=3,
            day=26,
            hour=2,
            minute=15,
            second=30,
            tz="Europe/Amsterdam",
        )

        with warns_here(ImplicitDisambiguationWarning):
            assert ZonedDateTime(**kwargs).strict_eq(
                ZonedDateTime(**kwargs, disambiguation="compatible")
            )

        with pytest.raises(
            SkippedTime,
            match="2023-03-26 02:15:30 is skipped in time zone 'Europe/Amsterdam'",
        ):
            ZonedDateTime(**kwargs, disambiguation="raise")

        d1 = ZonedDateTime(**kwargs, disambiguation="compatible")
        assert d1.strict_eq(
            ZonedDateTime(2023, 3, 26, 3, 15, 30, tz="Europe/Amsterdam")
        )

        assert ZonedDateTime(**kwargs, disambiguation="later").strict_eq(
            ZonedDateTime(2023, 3, 26, 3, 15, 30, tz="Europe/Amsterdam")
        )
        assert ZonedDateTime(**kwargs, disambiguation="earlier").strict_eq(
            ZonedDateTime(2023, 3, 26, 1, 15, 30, tz="Europe/Amsterdam")
        )

        assert issubclass(SkippedTime, ValueError)

    def test_from_iso(self):
        assert ZonedDateTime(
            "2020-08-15T23:12:09.987654321-04:00[America/New_York]"
        ).strict_eq(
            ZonedDateTime(
                2020,
                8,
                15,
                23,
                12,
                9,
                nanosecond=987_654_321,
                tz="America/New_York",
            )
        )

    def test_leap_seconds_parsing(self):
        # Leap second (60) should be parsed and normalized to 59
        assert ZonedDateTime.parse_iso(
            "2020-08-15T05:12:60-04:00[America/New_York]"
        ).strict_eq(
            ZonedDateTime(2020, 8, 15, 5, 12, 59, tz="America/New_York")
        )

        # Direct construction should still reject 60
        with pytest.raises(ValueError):
            ZonedDateTime(2020, 8, 15, 5, 12, 60, tz="America/New_York")


class TestInitFromPy:
    @pytest.mark.parametrize(
        "pydt, expect",
        [
            (
                py_datetime(
                    2020,
                    8,
                    15,
                    23,
                    12,
                    9,
                    987_654,
                    tzinfo=ZoneInfo("Europe/Paris"),
                ),
                ZonedDateTime(
                    2020,
                    8,
                    15,
                    23,
                    12,
                    9,
                    nanosecond=987_654_000,
                    tz="Europe/Paris",
                ),
            ),
            # subclass of datetime
            (
                DatetimeSubclass(
                    2020,
                    8,
                    15,
                    23,
                    12,
                    9,
                    987_654,
                    tzinfo=ZoneInfo("Europe/Paris"),
                ),
                ZonedDateTime(
                    2020,
                    8,
                    15,
                    23,
                    12,
                    9,
                    nanosecond=987_654_000,
                    tz="Europe/Paris",
                ),
            ),
            # skipped time
            (
                py_datetime(
                    2023,
                    3,
                    26,
                    2,
                    15,
                    30,
                    tzinfo=ZoneInfo("Europe/Amsterdam"),
                ),
                ZonedDateTime(
                    2023,
                    3,
                    26,
                    3,
                    15,
                    30,
                    tz="Europe/Amsterdam",
                ),
            ),
            (
                py_datetime(
                    2023,
                    3,
                    26,
                    2,
                    15,
                    30,
                    fold=1,
                    tzinfo=ZoneInfo("Europe/Amsterdam"),
                ),
                ZonedDateTime(
                    2023,
                    3,
                    26,
                    1,
                    15,
                    30,
                    tz="Europe/Amsterdam",
                ),
            ),
            # repeated time
            (
                py_datetime(
                    2023,
                    10,
                    29,
                    2,
                    15,
                    30,
                    tzinfo=ZoneInfo("Europe/Amsterdam"),
                ),
                ZonedDateTime(
                    2023,
                    10,
                    29,
                    2,
                    15,
                    30,
                    tz="Europe/Amsterdam",
                    disambiguation="earlier",
                ),
            ),
            (
                py_datetime(
                    2023,
                    10,
                    29,
                    2,
                    15,
                    30,
                    fold=1,
                    tzinfo=ZoneInfo("Europe/Amsterdam"),
                ),
                ZonedDateTime(
                    2023,
                    10,
                    29,
                    2,
                    15,
                    30,
                    tz="Europe/Amsterdam",
                    disambiguation="later",
                ),
            ),
        ],
    )
    def test_valid(self, pydt: py_datetime, expect: ZonedDateTime):
        assert ZonedDateTime(pydt).strict_eq(expect)

    def test_wrong_tzinfo(self):
        d = py_datetime(
            2020, 8, 15, 23, 12, 9, 987_654, tzinfo=py_timezone.utc
        )
        with pytest.raises(
            ValueError,
            match=r"^tzinfo must be a ZoneInfo, got datetime\.timezone\.utc$",
        ):
            ZonedDateTime(d)

    def test_zoneinfo_subclass(self):
        # A subclass carries a time zone ID like its base; the offset it
        # computes is checked like any other.
        class MyZoneInfo(ZoneInfo):
            pass

        dt = py_datetime(2020, 8, 15, 23, 12, 9, 987_654)
        assert ZonedDateTime(
            dt.replace(tzinfo=MyZoneInfo("Europe/Paris"))
        ).strict_eq(ZonedDateTime(dt.replace(tzinfo=ZoneInfo("Europe/Paris"))))

    def test_naive(self):

        with pytest.raises(
            ValueError,
            match=r"^datetime is naive; use PlainDateTime\(\) instead$",
        ):
            ZonedDateTime(py_datetime(2020, 3, 4))

    def test_out_of_range(self):
        min_pydt = py_datetime(1, 1, 1, tzinfo=ZoneInfo("Asia/Kolkata"))
        with pytest.raises((ValueError, OverflowError), match="range|year"):
            ZonedDateTime(min_pydt)

        max_pydt = py_datetime(
            9999, 12, 31, 22, tzinfo=ZoneInfo("America/New_York")
        )

        with pytest.raises((ValueError, OverflowError), match="range|year"):
            ZonedDateTime(max_pydt)

    def test_zoneinfo_key_is_none(self):
        with TEST_DIR.joinpath("tzif/Amsterdam.tzif").open("rb") as f:
            tz = ZoneInfo.from_file(f)

        py_dt = py_datetime(2020, 8, 15, 12, 8, 30, tzinfo=tz)

        with pytest.raises(
            ValueError,
            match=(
                r"^tzinfo has no time zone ID \(ZoneInfo\.key is None\); "
                r"pass key= to ZoneInfo\.from_file\(\), or use "
                r"OffsetDateTime\(\) to keep only the offset$"
            ),
        ):
            ZonedDateTime(py_dt)

    def test_zoneinfo_key_not_a_string(self):
        with TEST_DIR.joinpath("tzif/Amsterdam.tzif").open("rb") as f:
            tz = ZoneInfo.from_file(f, key=1)  # type: ignore[arg-type]

        py_dt = py_datetime(2020, 8, 15, 12, 8, 30, tzinfo=tz)

        with pytest.raises(TypeError, match="^ZoneInfo key must be a string$"):
            ZonedDateTime(py_dt)

    # The standard-library overload follows the same resolution flow as the
    # ISO one: the offset its ``tzinfo`` computes identifies the occurrence,
    # and ``offset_mismatch=`` decides what happens when it identifies none.
    @pytest.fixture()
    def disagreeing_tz(self, tmp_path: Path):
        """A ``ZoneInfo`` that calls itself ``Europe/Amsterdam`` but reads its
        rules from a file whenever never sees, so the two disagree."""
        with tz_rules_from_file("Europe/Amsterdam", AMS_TZ_RAWFILE, tmp_path):
            yield self._keyed_zoneinfo

    @staticmethod
    def _keyed_zoneinfo(path: str) -> ZoneInfo:
        with open(path, "rb") as f:
            return ZoneInfo.from_file(f, key="Europe/Amsterdam")

    @pytest.mark.parametrize(
        "fold, offset",
        [(0, hours(2)), (1, hours(1))],
    )
    def test_repeated_time_identified_by_its_offset(self, fold, offset):
        pydt = py_datetime(
            2023,
            10,
            29,
            2,
            15,
            30,
            fold=fold,
            tzinfo=ZoneInfo("Europe/Amsterdam"),
        )
        with warnings.catch_warnings():
            warnings.simplefilter("error", ImplicitDisambiguationWarning)
            # No policy is consulted: the offset already picks an occurrence.
            result = ZonedDateTime(pydt, disambiguation="raise")
        assert result.offset == offset
        assert result.to_plain() == PlainDateTime(2023, 10, 29, 2, 15, 30)

    @pytest.mark.parametrize(
        "fold, expect_hour",
        [(0, 3), (1, 1)],
    )
    def test_skipped_time_extrapolates(self, fold, expect_hour):
        pydt = py_datetime(
            2023,
            3,
            26,
            2,
            15,
            30,
            fold=fold,
            tzinfo=ZoneInfo("Europe/Amsterdam"),
        )
        with warnings.catch_warnings():
            warnings.simplefilter("error", ImplicitDisambiguationWarning)
            result = ZonedDateTime(pydt, disambiguation="raise")
        assert result.strict_eq(
            ZonedDateTime(
                2023, 3, 26, expect_hour, 15, 30, tz="Europe/Amsterdam"
            )
        )

    def test_offset_with_seconds(self):
        # Dublin ran on an offset of -00:25:21 before 1916. It matches
        # exactly, because the stdlib offset is written with seconds.
        pydt = py_datetime(1900, 1, 1, 12, tzinfo=ZoneInfo("Europe/Dublin"))
        result = ZonedDateTime(pydt)
        assert result.offset == TimeDelta(seconds=-1521)
        assert result.to_plain() == PlainDateTime(1900, 1, 1, 12)

    def test_mismatch_raises_by_default(self, disagreeing_tz):
        pydt = py_datetime(
            2020, 10, 28, 12, tzinfo=disagreeing_tz(AMS_TZ_RAWFILE_DST_LATE)
        )
        with pytest.raises(InvalidOffsetError, match="Europe/Amsterdam"):
            ZonedDateTime(pydt)

    def test_mismatch_keep_instant(self, disagreeing_tz):
        pydt = py_datetime(
            2020, 10, 28, 12, tzinfo=disagreeing_tz(AMS_TZ_RAWFILE_DST_LATE)
        )
        assert ZonedDateTime(pydt, offset_mismatch="keep_instant").strict_eq(
            ZonedDateTime(2020, 10, 28, 11, tz="Europe/Amsterdam")
        )

    def test_mismatch_keep_local(self, disagreeing_tz):
        pydt = py_datetime(
            2020, 10, 28, 12, tzinfo=disagreeing_tz(AMS_TZ_RAWFILE_DST_LATE)
        )
        with warnings.catch_warnings():
            warnings.simplefilter("error", ImplicitDisambiguationWarning)
            result = ZonedDateTime(pydt, offset_mismatch="keep_local")
        assert result.strict_eq(
            ZonedDateTime(2020, 10, 28, 12, tz="Europe/Amsterdam")
        )

    def test_mismatch_keep_local_consults_disambiguation(self, disagreeing_tz):
        # Honolulu's rules under Amsterdam's name: the offset matches neither
        # side of the fold, so keeping the local time needs a policy.
        pydt = py_datetime(
            2020,
            10,
            25,
            2,
            30,
            tzinfo=disagreeing_tz(str(TEST_DIR / "tzif" / "Honolulu.tzif")),
        )
        with warns_here(ImplicitDisambiguationWarning):
            implicit = ZonedDateTime(pydt, offset_mismatch="keep_local")
        assert implicit.strict_eq(
            ZonedDateTime(
                2020,
                10,
                25,
                2,
                30,
                tz="Europe/Amsterdam",
                disambiguation="earlier",
            )
        )
        assert ZonedDateTime(
            pydt, offset_mismatch="keep_local", disambiguation="later"
        ).strict_eq(
            ZonedDateTime(
                2020,
                10,
                25,
                2,
                30,
                tz="Europe/Amsterdam",
                disambiguation="later",
            )
        )
        with pytest.raises(RepeatedTime):
            ZonedDateTime(
                pydt, offset_mismatch="keep_local", disambiguation="raise"
            )

    def test_invalid_keywords(self):
        pydt = py_datetime(
            2020, 8, 15, 23, 12, tzinfo=ZoneInfo("Europe/Paris")
        )
        with pytest.raises(TypeError, match="disambiguate"):
            ZonedDateTime(pydt, disambiguate="earlier")  # type: ignore[call-overload]
        with pytest.raises(ValueError, match="offset_mismatch: 'foo'"):
            ZonedDateTime(pydt, offset_mismatch="foo")  # type: ignore[call-overload]
        with pytest.raises(TypeError, match="foo"):
            ZonedDateTime(pydt, foo=1)  # type: ignore[call-overload]


class TestNow:
    def test_typical(self):
        now = ZonedDateTime.now("Iceland")
        assert now.tz_id == "Iceland"
        py_now = py_datetime.now(ZoneInfo("Iceland"))
        assert py_now - now.to_stdlib() < py_timedelta(seconds=1)

    def test_patched(self):
        instant = Instant.from_utc(2020, 8, 15, 12, 30, 45, nanosecond=5)
        with patch_current_time(instant, keep_ticking=False):
            assert ZonedDateTime.now("Europe/Amsterdam").strict_eq(
                instant.to_tz("Europe/Amsterdam")
            )

    @system_tz("Europe/Amsterdam")
    def test_system_tz(self):
        now = ZonedDateTime.now(SYSTEM_TZ)
        py_now = py_datetime.now().astimezone()
        assert now.tz_id == "Europe/Amsterdam"
        assert py_now - now.to_stdlib() < py_timedelta(seconds=1)


class TestAccessors:
    @pytest.mark.parametrize(
        "d, expected",
        [
            (ZDT1, hours(2)),
            (ZDT2, -TimeDelta(minutes=25, seconds=21)),
            (ZDT3, hours(-5)),
            (ZDT_POSIX, hours(2)),
            (ZDT_RAWFILE, hours(2)),
        ],
    )
    def test_offset(self, d: ZonedDateTime, expected: TimeDelta):
        assert d.offset == expected

    @pytest.mark.parametrize(
        "d, expected",
        [
            (ZDT1, Date(2020, 8, 15)),
            (ZDT2, Date(1900, 1, 1)),
            (ZDT3, Date(1995, 12, 4)),
            (ZDT_POSIX, Date(2020, 8, 15)),
            (ZDT_RAWFILE, Date(2020, 8, 15)),
        ],
    )
    def test_date(self, d: ZonedDateTime, expected: Date):
        assert d.date() == expected

    @pytest.mark.parametrize(
        "d, expected",
        [
            (ZDT1, Time(23, 12, 9, nanosecond=987_654_321)),
            (ZDT2, Time(0, 0, 0)),
            (ZDT3, Time(23, 12, 30)),
            (ZDT_POSIX, Time(23, 12, 9, nanosecond=987_654_321)),
            (ZDT_RAWFILE, Time(23, 12, 9, nanosecond=987_654_321)),
        ],
    )
    def test_time(self, d: ZonedDateTime, expected: Time):
        assert d.time() == expected

    def test_day_of_week(self):
        assert (
            ZonedDateTime(2024, 3, 9, 22, tz="America/New_York").day_of_week()
            is SATURDAY
        )
        assert (
            ZonedDateTime(2024, 12, 30, tz="America/New_York").day_of_week()
            is MONDAY
        )


class TestConversion:
    @pytest.mark.parametrize(
        "d",
        [
            ZDT1,
            ZDT2,
            ZDT3,
            ZDT_POSIX,
            ZDT_RAWFILE,
        ],
    )
    def test_to_plain(self, d: ZonedDateTime):
        plain = d.to_plain()
        assert isinstance(plain, PlainDateTime)
        assert plain.year == d.year
        assert plain.month == d.month
        assert plain.day == d.day
        assert plain.hour == d.hour
        assert plain.minute == d.minute
        assert plain.second == d.second
        assert plain.nanosecond == d.nanosecond

    @pytest.mark.parametrize(
        "tz",
        ["Europe/Amsterdam", AMS_TZ_POSIX, AMS_TZ_RAWFILE],
    )
    def test_to_instant(self, tz: str):
        assert (
            create_zdt(2020, 8, 15, 12, 8, 30, tz=tz)
            .to_instant()
            .strict_eq(Instant.from_utc(2020, 8, 15, 10, 8, 30))
        )
        d = create_zdt(
            2023,
            10,
            29,
            2,
            15,
            30,
            tz=tz,
            disambiguation="earlier",
        )
        assert d.to_instant().strict_eq(
            Instant.from_utc(2023, 10, 29, 0, 15, 30)
        )
        assert (
            create_zdt(
                2023,
                10,
                29,
                2,
                15,
                30,
                tz=tz,
                disambiguation="later",
            )
            .to_instant()
            .strict_eq(Instant.from_utc(2023, 10, 29, 1, 15, 30))
        )

    @pytest.mark.parametrize(
        "ams_tz",
        ["Europe/Amsterdam", AMS_TZ_POSIX, AMS_TZ_RAWFILE],
    )
    def test_to_tz(self, ams_tz: str):
        # unambiguous time
        assert (
            create_zdt(2020, 8, 15, 12, 8, 30, tz=ams_tz)
            .to_tz("America/New_York")
            .strict_eq(
                ZonedDateTime(2020, 8, 15, 6, 8, 30, tz="America/New_York")
            )
        )
        ams = ZonedDateTime(
            2023,
            10,
            29,
            2,
            15,
            30,
            tz="Europe/Paris",
            disambiguation="earlier",
        )
        nyc = ZonedDateTime(2023, 10, 28, 20, 15, 30, tz="America/New_York")
        assert ams.to_tz("America/New_York").strict_eq(nyc)
        assert (
            ams.replace(disambiguation="later")
            .to_tz("America/New_York")
            .strict_eq(nyc.replace(hour=21, disambiguation="raise"))
        )
        assert nyc.to_tz("Europe/Paris").strict_eq(ams)
        assert (
            nyc.replace(hour=21, disambiguation="raise")
            .to_tz("Europe/Paris")
            .strict_eq(ams.replace(disambiguation="later"))
        )
        # disambiguation doesn't affect NYC time because there's no ambiguity
        assert (
            nyc.replace(disambiguation="later")
            .to_tz("Europe/Paris")
            .strict_eq(ams)
        )

        # catch local time sliding out of range
        small_zdt = ZonedDateTime(1, 1, 1, tz="Etc/UTC")
        with pytest.raises(ValueError, match="out of range"):
            small_zdt.to_tz("America/New_York")

        big_zdt = ZonedDateTime(9999, 12, 31, 23, tz="Etc/UTC")
        with pytest.raises(ValueError, match="out of range"):
            big_zdt.to_tz("Asia/Tokyo")

        with pytest.raises(
            TypeError, match="^tz must be a string or SYSTEM_TZ$"
        ):
            nyc.to_tz(3)

        with pytest.raises(TimeZoneNotFoundError):
            nyc.to_tz("America/Nowhere")

    @pytest.mark.parametrize(
        "tz",
        ["Europe/Amsterdam", AMS_TZ_POSIX, AMS_TZ_RAWFILE],
    )
    def test_to_fixed_offset(self, tz: str):
        d = create_zdt(2020, 8, 15, 12, 8, 30, tz=tz)

        assert d.to_fixed_offset().strict_eq(
            OffsetDateTime(2020, 8, 15, 12, 8, 30, offset=hours(2))
        )
        assert (
            d.replace(month=1, disambiguation="raise")
            .to_fixed_offset()
            .strict_eq(OffsetDateTime(2020, 1, 15, 12, 8, 30, offset=hours(1)))
        )
        assert (
            d.replace(month=1, disambiguation="raise")
            .to_fixed_offset(hours(4))
            .strict_eq(OffsetDateTime(2020, 1, 15, 15, 8, 30, offset=hours(4)))
        )
        assert d.to_fixed_offset(hours(0)).strict_eq(
            OffsetDateTime(2020, 8, 15, 10, 8, 30, offset=hours(0))
        )
        assert d.to_fixed_offset(hours(-4)).strict_eq(
            OffsetDateTime(2020, 8, 15, 6, 8, 30, offset=hours(-4))
        )

        # catch local time sliding out of range
        small_zdt = ZonedDateTime(1, 1, 1, tz="Etc/UTC")
        with pytest.raises((ValueError, OverflowError), match="range|year"):
            small_zdt.to_fixed_offset(hours(-3))

        big_zdt = ZonedDateTime(9999, 12, 31, 23, tz="Etc/UTC")
        with pytest.raises((ValueError, OverflowError), match="range|year"):
            big_zdt.to_fixed_offset(hours(4))

    @system_tz("Europe/Amsterdam")
    def test_to_system_tz(self):
        d = ZonedDateTime(2023, 10, 28, 2, 15, tz="Europe/Amsterdam")
        assert d.to_tz(SYSTEM_TZ).strict_eq(
            ZonedDateTime(2023, 10, 28, 2, 15, tz="Europe/Amsterdam")
        )
        assert (
            d.replace(day=29, disambiguation="later")
            .to_tz(SYSTEM_TZ)
            .strict_eq(
                ZonedDateTime(
                    2023,
                    10,
                    29,
                    2,
                    15,
                    disambiguation="later",
                    tz="Europe/Amsterdam",
                )
            )
        )

        # posix tz
        with system_tz(AMS_TZ_POSIX):
            assert d.to_tz(SYSTEM_TZ).strict_eq(
                create_zdt(2023, 10, 28, 2, 15, tz=AMS_TZ_POSIX)
            )

        # filepath
        with system_tz(AMS_TZ_RAWFILE):
            assert d.to_tz(SYSTEM_TZ).strict_eq(
                create_zdt(2023, 10, 28, 2, 15, tz=AMS_TZ_RAWFILE)
            )

        # colon prefix
        with system_tz(":America/New_York"):
            assert d.to_tz(SYSTEM_TZ).strict_eq(
                ZonedDateTime(2023, 10, 27, 20, 15, tz="America/New_York")
            )

        # catch local time sliding out of range
        small_zdt = ZonedDateTime(1, 1, 1, tz="Etc/UTC")
        with system_tz("America/New_York"):
            with pytest.raises(
                (ValueError, OverflowError), match="range|year"
            ):
                small_zdt.to_tz(SYSTEM_TZ)

        big_zdt = ZonedDateTime(9999, 12, 31, 23, tz="Etc/UTC")
        with pytest.raises((ValueError, OverflowError), match="range|year"):
            big_zdt.to_tz(SYSTEM_TZ)


class TestToStdlib:
    def test_tz_id(self):
        d = ZonedDateTime(
            2020,
            8,
            15,
            23,
            12,
            9,
            nanosecond=987_654_999,
            tz="Europe/Amsterdam",
        )
        py_dt = d.to_stdlib()
        assert py_dt == py_datetime(
            2020,
            8,
            15,
            23,
            12,
            9,
            987_654,
            tzinfo=ZoneInfo("Europe/Amsterdam"),
        )
        # This isn't checked by the comparison above!
        assert py_dt.tzinfo is ZoneInfo("Europe/Amsterdam")

        # a repeated local time
        d2 = ZonedDateTime(
            2023,
            10,
            29,
            2,
            15,
            tz="Europe/Amsterdam",
            disambiguation="earlier",
        )
        assert d2.to_stdlib().fold == 0
        assert d2.replace(disambiguation="later").to_stdlib().fold == 1

        # ensure the ZoneInfo isn't file-based, and can thus be pickled
        pickle.dumps(d2.to_stdlib())

        # negative offset
        d3 = ZonedDateTime(
            2020,
            8,
            15,
            12,
            8,
            30,
            tz="America/New_York",
        )
        assert d3.to_stdlib().timestamp() == d3.timestamp()

    @pytest.mark.parametrize(
        "d",
        [
            # both occurrences of a repeated time
            ZonedDateTime(
                2023,
                10,
                29,
                2,
                15,
                tz="Europe/Amsterdam",
                disambiguation="earlier",
            ),
            ZonedDateTime(
                2023,
                10,
                29,
                2,
                15,
                tz="Europe/Amsterdam",
                disambiguation="later",
            ),
            # just past a skipped time
            ZonedDateTime(2023, 3, 26, 1, 30, tz="Europe/Amsterdam").add(
                hours=1
            ),
        ],
    )
    def test_round_trip(self, d):
        # fold is set on the way out and read on the way in
        with warnings.catch_warnings():
            warnings.simplefilter("error")
            assert ZonedDateTime(d.to_stdlib()).strict_eq(d)

    def test_zoneinfo_disagrees_with_the_rules(self, tmp_path: Path):
        # The stdlib reads Amsterdam's rules from a file in which DST ends a
        # week later than in the file whenever read. The instant survives;
        # the local fields follow the stdlib's rules.
        zone = tmp_path / "Europe" / "Amsterdam"
        zone.parent.mkdir()
        shutil.copyfile(AMS_TZ_RAWFILE_DST_LATE, zone)
        d = ZonedDateTime(2020, 10, 28, 12, tz="Europe/Amsterdam")
        assert d.offset == hours(1)

        zoneinfo_reset_tzpath([tmp_path])
        ZoneInfo.clear_cache(only_keys=["Europe/Amsterdam"])
        try:
            py_dt = d.to_stdlib()
        finally:
            zoneinfo_reset_tzpath()
            ZoneInfo.clear_cache(only_keys=["Europe/Amsterdam"])
        assert py_dt.timestamp() == d.timestamp()
        assert py_dt.hour == 13
        assert py_dt.utcoffset() == py_timedelta(hours=2)

    @pytest.mark.parametrize(
        "tz",
        [AMS_TZ_POSIX, AMS_TZ_RAWFILE],
    )
    def test_system_tz(self, tz: str):
        d = create_zdt(
            2020,
            8,
            15,
            12,
            8,
            30,
            nanosecond=123_456_789,
            tz=tz,
        )
        py_dt = d.to_stdlib()
        assert py_dt == py_datetime(
            2020, 8, 15, 10, 8, 30, 123_456, tzinfo=py_timezone.utc
        )
        # Ensure the offset is correct (the check above only checks UTC equality)
        assert py_dt.utcoffset() == py_timedelta(hours=2)


class TestTimestamp:
    @pytest.mark.parametrize(
        ("unit", "expected"),
        [
            ("second", 1_597_493_310),
            ("millisecond", 1_597_493_310_045),
            ("microsecond", 1_597_493_310_045_123),
            ("nanosecond", 1_597_493_310_045_123_987),
        ],
    )
    def test_unit(self, unit, expected):
        value = ZonedDateTime(
            2020,
            8,
            15,
            8,
            8,
            30,
            nanosecond=45_123_987,
            tz="America/New_York",
        )

        assert value.timestamp(unit=unit) == expected

    @pytest.mark.parametrize(
        # One nanosecond after the epoch floors to 0 in every unit that
        # cannot resolve it; in nanoseconds it is the exact value 1.
        ("unit", "after_epoch"),
        [
            ("second", 0),
            ("millisecond", 0),
            ("microsecond", 0),
            ("nanosecond", 1),
        ],
    )
    def test_unit_floors_around_epoch(self, unit, after_epoch):
        before = Instant.from_utc(
            1969, 12, 31, 23, 59, 59, nanosecond=999_999_999
        )
        after = Instant.from_utc(1970, 1, 1, nanosecond=1)

        assert before.to_tz("America/New_York").timestamp(unit=unit) == -1
        assert after.to_tz("Asia/Tokyo").timestamp(unit=unit) == after_epoch

    def test_default_seconds(self):
        assert ZonedDateTime(1970, 1, 1, tz="Iceland").timestamp() == 0
        assert (
            ZonedDateTime(
                2020, 8, 15, 8, 8, 30, nanosecond=45_123, tz="America/New_York"
            ).timestamp()
            == 1_597_493_310
        )

        repeated = ZonedDateTime(
            2023,
            10,
            29,
            2,
            15,
            30,
            tz="Europe/Amsterdam",
            disambiguation="earlier",
        )
        assert (
            repeated.timestamp()
            != repeated.replace(disambiguation="later").timestamp()
        )


class TestFormatIso:
    @pytest.mark.parametrize(
        ("tz_id_display", "suffix"),
        [
            ("required", "[Europe/Amsterdam]"),
            ("if_available", "[Europe/Amsterdam]"),
            ("omit", ""),
        ],
    )
    def test_tz_id_display(self, tz_id_display, suffix):
        value = ZonedDateTime(2020, 8, 15, tz="Europe/Amsterdam")
        assert (
            value.format_iso(tz_id_display=tz_id_display)
            == "2020-08-15T00:00:00+02:00" + suffix
        )

    @pytest.mark.parametrize(
        "kwargs",
        [{}, {"basic": True}, {"sep": " "}, {"unit": "hour"}],
    )
    def test_round_trip(self, kwargs):
        d = ZonedDateTime(2020, 8, 15, 23, tz="Europe/Amsterdam")
        assert ZonedDateTime.parse_iso(d.format_iso(**kwargs)).strict_eq(d)

    def test_unexpected_keyword(self):
        with pytest.raises(
            TypeError, match="unexpected keyword argument 'foo'"
        ):
            ZonedDateTime(2020, 8, 15, tz="UTC").format_iso(foo=1)  # type: ignore[call-overload]

    @pytest.mark.parametrize(
        "d, expected",
        [
            (
                ZonedDateTime(
                    1998,
                    11,
                    15,
                    23,
                    12,
                    9,
                    nanosecond=987_654_321,
                    tz="Europe/Amsterdam",
                ),
                "1998-11-15T23:12:09.987654321+01:00[Europe/Amsterdam]",
            ),
            (
                ZonedDateTime(
                    2023,
                    10,
                    29,
                    2,
                    15,
                    30,
                    tz="Europe/Amsterdam",
                    disambiguation="earlier",
                ),
                "2023-10-29T02:15:30+02:00[Europe/Amsterdam]",
            ),
            (
                ZonedDateTime(
                    2023,
                    10,
                    29,
                    2,
                    15,
                    30,
                    tz="Europe/Amsterdam",
                    disambiguation="later",
                ),
                "2023-10-29T02:15:30+01:00[Europe/Amsterdam]",
            ),
            (
                ZDT2,
                "1900-01-01T00:00:00-00:25:21[Europe/Dublin]",
            ),
            (
                ZDT3,
                "1995-12-04T23:12:30-05:00[America/New_York]",
            ),
        ],
    )
    def test_defaults(self, d: ZonedDateTime, expected: str):
        assert str(d) == expected
        assert d.format_iso() == expected

    @pytest.mark.parametrize("d", [ZDT_POSIX, ZDT_RAWFILE])
    def test_no_timezone_id(self, d: ZonedDateTime):
        msg = "^the time zone has no ID; use tz_id_display='if_available' or 'omit'$"
        with pytest.raises(ValueError, match=msg):
            d.format_iso()
        with pytest.raises(ValueError, match=msg):
            d.format_iso(tz_id_display="required")

    @pytest.mark.parametrize(
        "zdt, kwargs, expected",
        [
            (
                ZDT1,
                {"unit": "nanosecond"},
                "2020-08-15T23:12:09.987654321+02:00[Europe/Amsterdam]",
            ),
            (
                ZDT1,
                {"unit": "microsecond", "sep": " "},
                "2020-08-15 23:12:09.987654+02:00[Europe/Amsterdam]",
            ),
            (
                ZDT1,
                {"unit": "millisecond", "basic": True},
                "20200815T231209.987+0200[Europe/Amsterdam]",
            ),
            (
                ZDT1,
                {"unit": "second", "sep": "T", "basic": True},
                "20200815T231209+0200[Europe/Amsterdam]",
            ),
            (
                ZDT1,
                {"unit": "minute"},
                "2020-08-15T23:12+02:00[Europe/Amsterdam]",
            ),
            (
                ZDT1,
                {"unit": "hour", "basic": True},
                "20200815T23+0200[Europe/Amsterdam]",
            ),
            (
                ZDT1,
                {"unit": "auto", "basic": False},
                "2020-08-15T23:12:09.987654321+02:00[Europe/Amsterdam]",
            ),
            (
                ZDT2,
                {"unit": "auto"},
                "1900-01-01T00:00:00-00:25:21[Europe/Dublin]",
            ),
            (
                ZDT2,
                {"unit": "millisecond"},
                "1900-01-01T00:00:00.000-00:25:21[Europe/Dublin]",
            ),
            (
                ZDT2,
                {"unit": "millisecond", "tz_id_display": "omit"},
                "1900-01-01T00:00:00.000-00:25:21",
            ),
            (
                ZDT2,
                {"unit": "microsecond", "tz_id_display": "required"},
                "1900-01-01T00:00:00.000000-00:25:21[Europe/Dublin]",
            ),
            (
                ZDT2,
                {
                    "unit": "nanosecond",
                    "basic": True,
                    "sep": " ",
                    "tz_id_display": "if_available",
                },
                "19000101 000000.000000000-002521[Europe/Dublin]",
            ),
            (
                ZDT2,
                {"unit": "hour", "basic": True, "sep": "T"},
                "19000101T00-002521[Europe/Dublin]",
            ),
            (
                ZDT_POSIX,
                {
                    "unit": "nanosecond",
                    "basic": True,
                    "sep": "T",
                    "tz_id_display": "if_available",
                },
                "20200815T231209.987654321+0200",
            ),
            (
                ZDT_RAWFILE,
                {"unit": "millisecond", "sep": " ", "tz_id_display": "omit"},
                "2020-08-15 23:12:09.987+02:00",
            ),
        ],
    )
    def test_variations(self, zdt, kwargs, expected):
        assert zdt.format_iso(**kwargs) == expected

    def test_invalid(self):
        with pytest.raises(ValueError, match="unit"):
            ZDT1.format_iso(unit="foo")  # type: ignore[call-overload]

        with pytest.raises(ValueError, match="invalid unit"):
            ZDT1.format_iso(unit=True)  # type: ignore[call-overload]

        with pytest.raises(ValueError, match="sep"):
            ZDT1.format_iso(sep="_")  # type: ignore[call-overload]

        with pytest.raises(ValueError, match="invalid sep"):
            ZDT1.format_iso(sep=1)  # type: ignore[call-overload]

        with pytest.raises(ValueError, match="tz_id_display"):
            ZDT1.format_iso(tz_id_display="sometimes")  # type: ignore[call-overload]

    def test_str_without_tz_id(self):
        """str() never raises: without an ID it gives the offset form."""
        with system_tz(AMS_TZ_POSIX):
            d = ZonedDateTime.now(SYSTEM_TZ)
        assert str(d).endswith(("+02:00", "+01:00"))
        assert str(d) == d.format_iso(tz_id_display="if_available")
        assert "<system time zone without ID>" in repr(d)


class TestFormat:
    def test_tz_id_without_id(self):
        d = create_zdt(2020, 8, 15, 12, 8, 30, tz=AMS_TZ_POSIX)
        with pytest.raises(
            ValueError, match="^the time zone has no ID; VV cannot be written$"
        ):
            d.format("VV")


class TestRepr:
    @pytest.mark.parametrize(
        "d, expect",
        [
            (
                ZonedDateTime(
                    2020,
                    8,
                    15,
                    23,
                    12,
                    9,
                    nanosecond=9_876_543,
                    tz="Australia/Darwin",
                ),
                'ZonedDateTime("2020-08-15 23:12:09.009876543+09:30[Australia/Darwin]")',
            ),
            (
                ZonedDateTime(2020, 8, 15, 23, 12, tz="Iceland"),
                'ZonedDateTime("2020-08-15 23:12:00+00:00[Iceland]")',
            ),
            (
                ZonedDateTime(2020, 8, 15, 23, 12, tz="UTC"),
                'ZonedDateTime("2020-08-15 23:12:00+00:00[UTC]")',
            ),
            (
                create_zdt(2020, 8, 15, 12, 8, 30, tz=AMS_TZ_POSIX),
                'ZonedDateTime("2020-08-15 12:08:30+02:00[<system time zone without ID>]")',
            ),
            (
                create_zdt(2020, 8, 15, 12, 8, 30, tz=AMS_TZ_RAWFILE),
                'ZonedDateTime("2020-08-15 12:08:30+02:00[<system time zone without ID>]")',
            ),
        ],
    )
    def test_typical(self, d: ZonedDateTime, expect: str):
        assert repr(d) == expect


class TestParseIso:
    @pytest.mark.parametrize(
        "s, expect",
        [
            (
                "2020-08-15T12:08:30+02:00[Europe/Amsterdam]",
                ZonedDateTime(2020, 8, 15, 12, 8, 30, tz="Europe/Amsterdam"),
            ),
            (
                "2020-08-15T12:08:30Z[Iceland]",
                ZonedDateTime(2020, 8, 15, 12, 8, 30, tz="Iceland"),
            ),
            # fractions
            (
                "2020-08-15T12:08:30.02320+02:00[Europe/Amsterdam]",
                ZonedDateTime(
                    2020,
                    8,
                    15,
                    12,
                    8,
                    30,
                    nanosecond=23_200_000,
                    tz="Europe/Amsterdam",
                ),
            ),
            (
                "2020-08-15T12:08:30,02320+02:00[Europe/Amsterdam]",
                ZonedDateTime(
                    2020,
                    8,
                    15,
                    12,
                    8,
                    30,
                    nanosecond=23_200_000,
                    tz="Europe/Amsterdam",
                ),
            ),
            (
                "2020-08-15T12:08:30.000000001+02:00[Europe/Berlin]",
                ZonedDateTime(
                    2020, 8, 15, 12, 8, 30, nanosecond=1, tz="Europe/Berlin"
                ),
            ),
            # second-level offset
            (
                "1900-01-01T23:34:39.01-00:25:21[Europe/Dublin]",
                ZonedDateTime(
                    1900,
                    1,
                    1,
                    23,
                    34,
                    39,
                    nanosecond=10_000_000,
                    tz="Europe/Dublin",
                ),
            ),
            (
                "2020-08-15T12:08:30+02:00:00[Europe/Berlin]",
                ZonedDateTime(2020, 8, 15, 12, 8, 30, tz="Europe/Berlin"),
            ),
            # offset disambiguates
            (
                "2023-10-29T02:15:30+01:00[Europe/Amsterdam]",
                ZonedDateTime(
                    2023,
                    10,
                    29,
                    2,
                    15,
                    30,
                    tz="Europe/Amsterdam",
                    disambiguation="later",
                ),
            ),
            (
                "2023-10-29T02:15:30+02:00[Europe/Amsterdam]",
                ZonedDateTime(
                    2023,
                    10,
                    29,
                    2,
                    15,
                    30,
                    tz="Europe/Amsterdam",
                    disambiguation="earlier",
                ),
            ),
            # Offsets are optional
            (
                "2023-08-25T12:15:30[Europe/Amsterdam]",
                ZonedDateTime(2023, 8, 25, 12, 15, 30, tz="Europe/Amsterdam"),
            ),
            # Alternate formats
            (
                "20200815 12:08:30+02:00[Europe/Amsterdam]",
                ZonedDateTime(2020, 8, 15, 12, 8, 30, tz="Europe/Amsterdam"),
            ),
            (
                "2020-02-15t120830z[Europe/London]",
                ZonedDateTime(2020, 2, 15, 12, 8, 30, tz="Europe/London"),
            ),
            (
                "2020-08-15T12:08:30+02[Europe/Amsterdam]",
                ZonedDateTime(2020, 8, 15, 12, 8, 30, tz="Europe/Amsterdam"),
            ),
            (
                "19000101 00-002521[Europe/Dublin]",
                ZDT2,
            ),
            # leap second cases: 60 is normalized to 59
            (
                "2020-08-15T05:12:60-04:00[America/New_York]",
                ZonedDateTime(2020, 8, 15, 5, 12, 59, tz="America/New_York"),
            ),
            (
                "2020-08-15T05:12:60.123456-04:00[America/New_York]",
                ZonedDateTime(
                    2020,
                    8,
                    15,
                    5,
                    12,
                    59,
                    nanosecond=123_456_000,
                    tz="America/New_York",
                ),
            ),
            (
                "20200815T051260-0400[America/New_York]",
                ZonedDateTime(2020, 8, 15, 5, 12, 59, tz="America/New_York"),
            ),
            (
                "2020-08-15T23:59:60.999999999+00:00[UTC]",
                ZonedDateTime(
                    2020, 8, 15, 23, 59, 59, nanosecond=999_999_999, tz="UTC"
                ),
            ),
            (
                "2020-08-15T12:34:60+00:00[UTC]",
                ZonedDateTime(2020, 8, 15, 12, 34, 59, tz="UTC"),
            ),
            (
                "2020-08-15T12:34:60,5+00:00[UTC]",
                ZonedDateTime(
                    2020, 8, 15, 12, 34, 59, nanosecond=500_000_000, tz="UTC"
                ),
            ),
            # Z is also valid for non-UTC time zones
            (
                "2020-02-15t120830z[America/New_York]",
                ZonedDateTime(2020, 2, 15, 7, 8, 30, tz="America/New_York"),
            ),
        ],
    )
    def test_valid(self, s, expect):
        assert ZonedDateTime.parse_iso(s).strict_eq(expect)

    def test_no_offset_for_skipped_time(self):
        with warns_here(ImplicitDisambiguationWarning):
            parsed = ZonedDateTime.parse_iso(
                "2023-03-26T02:15:30[Europe/Amsterdam]"
            )
        assert parsed.strict_eq(
            ZonedDateTime(
                2023,
                3,
                26,
                2,
                15,
                30,
                tz="Europe/Amsterdam",
                disambiguation="compatible",
            )
        )

    def test_minute_precision_offset_matching(self):
        result = ZonedDateTime.parse_iso(
            "1900-01-01T00:00:00-00:25[Europe/Dublin]"
        )
        assert result.offset == TimeDelta(seconds=-(25 * 60 + 21))

        with pytest.raises(InvalidOffsetError):
            ZonedDateTime.parse_iso(
                "1900-01-01T00:00:00-00:25:00[Europe/Dublin]"
            )

    @pytest.mark.parametrize(
        "construct", [ZonedDateTime.parse_iso, ZonedDateTime]
    )
    def test_keep_instant_on_offset_mismatch(self, construct):
        assert construct(
            "2020-08-15T12:00:00+03:00[Europe/Amsterdam]",
            offset_mismatch="keep_instant",
        ).strict_eq(ZonedDateTime(2020, 8, 15, 11, tz="Europe/Amsterdam"))

    @pytest.mark.parametrize(
        "offset_mismatch", ["raise", "keep_instant", "keep_local"]
    )
    def test_matching_offset_ignores_policies(self, offset_mismatch):
        value = "2023-10-29T02:15:30+02:00[Europe/Amsterdam]"
        expected = ZonedDateTime(
            2023,
            10,
            29,
            2,
            15,
            30,
            tz="Europe/Amsterdam",
            disambiguation="earlier",
        )
        assert ZonedDateTime.parse_iso(
            value,
            offset_mismatch=offset_mismatch,
            disambiguation="raise",
        ).strict_eq(expected)
        assert ZonedDateTime(
            value,
            offset_mismatch=offset_mismatch,
            disambiguation="raise",
        ).strict_eq(expected)

    @pytest.mark.parametrize(
        "construct", [ZonedDateTime.parse_iso, ZonedDateTime]
    )
    def test_invalid_offset_mismatch(self, construct):
        with pytest.raises(ValueError, match="offset_mismatch"):
            construct(
                "2020-08-15T12:00:00+02:00[Europe/Amsterdam]",
                offset_mismatch="ignore",
            )

    @pytest.mark.parametrize(
        "s, disambiguation, expected",
        [
            (
                "2023-10-29T02:15:30+03:00[Europe/Amsterdam]",
                "compatible",
                ZonedDateTime(
                    2023,
                    10,
                    29,
                    2,
                    15,
                    30,
                    tz="Europe/Amsterdam",
                    disambiguation="earlier",
                ),
            ),
            (
                "2023-10-29T02:15:30+03:00[Europe/Amsterdam]",
                "earlier",
                ZonedDateTime(
                    2023,
                    10,
                    29,
                    2,
                    15,
                    30,
                    tz="Europe/Amsterdam",
                    disambiguation="earlier",
                ),
            ),
            (
                "2023-10-29T02:15:30+03:00[Europe/Amsterdam]",
                "later",
                ZonedDateTime(
                    2023,
                    10,
                    29,
                    2,
                    15,
                    30,
                    tz="Europe/Amsterdam",
                    disambiguation="later",
                ),
            ),
            (
                "2023-03-26T02:15:30+03:00[Europe/Amsterdam]",
                "compatible",
                ZonedDateTime(
                    2023,
                    3,
                    26,
                    2,
                    15,
                    30,
                    tz="Europe/Amsterdam",
                    disambiguation="later",
                ),
            ),
            (
                "2023-03-26T02:15:30+03:00[Europe/Amsterdam]",
                "earlier",
                ZonedDateTime(
                    2023,
                    3,
                    26,
                    2,
                    15,
                    30,
                    tz="Europe/Amsterdam",
                    disambiguation="earlier",
                ),
            ),
            (
                "2023-03-26T02:15:30+03:00[Europe/Amsterdam]",
                "later",
                ZonedDateTime(
                    2023,
                    3,
                    26,
                    2,
                    15,
                    30,
                    tz="Europe/Amsterdam",
                    disambiguation="later",
                ),
            ),
        ],
    )
    def test_keep_local_uses_disambiguation(self, s, disambiguation, expected):
        assert ZonedDateTime.parse_iso(
            s,
            offset_mismatch="keep_local",
            disambiguation=disambiguation,
        ).strict_eq(expected)
        assert ZonedDateTime(
            s,
            offset_mismatch="keep_local",
            disambiguation=disambiguation,
        ).strict_eq(expected)

    @pytest.mark.parametrize(
        ("value", "error"),
        [
            (
                "2023-10-29T02:15:30+03:00[Europe/Amsterdam]",
                RepeatedTime,
            ),
            (
                "2023-03-26T02:15:30+03:00[Europe/Amsterdam]",
                SkippedTime,
            ),
        ],
    )
    def test_keep_local_raise(self, value, error):
        with pytest.raises(error):
            ZonedDateTime.parse_iso(
                value,
                offset_mismatch="keep_local",
                disambiguation="raise",
            )
        with pytest.raises(error):
            ZonedDateTime(
                value,
                offset_mismatch="keep_local",
                disambiguation="raise",
            )

    @pytest.mark.parametrize(
        "value",
        [
            "2023-10-29T02:15:30+03:00[Europe/Amsterdam]",
            "2023-03-26T02:15:30+03:00[Europe/Amsterdam]",
        ],
    )
    def test_keep_local_implicit_disambiguation_warns(self, value):
        with warns_here(ImplicitDisambiguationWarning):
            ZonedDateTime.parse_iso(value, offset_mismatch="keep_local")
        with warns_here(ImplicitDisambiguationWarning):
            ZonedDateTime(value, offset_mismatch="keep_local")

    def test_ordinary_mismatch_does_not_disambiguate(self):
        value = "2023-05-01T12:15:30+03:00[Europe/Amsterdam]"
        with warnings.catch_warnings():
            warnings.simplefilter("error", ImplicitDisambiguationWarning)
            parsed = ZonedDateTime.parse_iso(
                value, offset_mismatch="keep_local"
            )
            constructed = ZonedDateTime(value, offset_mismatch="keep_local")
        assert (parsed.hour, parsed.minute) == (12, 15)
        assert constructed.strict_eq(parsed)

    @pytest.mark.parametrize(
        "construct", [ZonedDateTime.parse_iso, ZonedDateTime]
    )
    def test_keep_instant_ignores_disambiguation(self, construct):
        value = "2023-03-26T02:15:30+03:00[Europe/Amsterdam]"
        expected = OffsetDateTime("2023-03-26 02:15:30+03:00").to_instant()
        assert (
            construct(
                value,
                offset_mismatch="keep_instant",
                disambiguation="raise",
            ).to_instant()
            == expected
        )

    @pytest.mark.parametrize(
        "s",
        [
            "2020-08-15T12:08:30+02:00",  # no time zone ID
            # bracket problems
            "2020-08-15T12:08:30+02:00[Europe/Amsterdam",
            "2020-08-15T12:08:30+02:00[Europe][Amsterdam]",
            "2020-08-15T12:08:30+02:00Europe/Amsterdam]",
            "2023-10-29T02:15:30+02:00(Europe/Amsterdam)",
            # separator problems
            "2020-08-15_12:08:30+02:00[Europe/Amsterdam]",
            "2020-08-15T12.08:30+02:00[Europe/Amsterdam]",
            "2020_08-15T12:08:30+02:00[Europe/Amsterdam]",
            # padding problems
            "2020-08-15T12:8:30+02:00[Europe/Amsterdam]",
            "20200815XXT12:30+02:00[Europe/Amsterdam]",
            # invalid values
            "2020-08-32T12:08:30+02:00[Europe/Amsterdam]",
            "2020-08-12T12:68:30+02:00[Europe/Amsterdam]",
            "2020-08-12T12:68:30+99:00[Europe/Amsterdam]",
            "2020-08-12T12:68:30+14:89[Europe/Amsterdam]",
            "2020-08-12T12:68:30+01:00[Europe/Amsterdam]",
            "2020-08-12T12:68:30+14:29:60[Europe/Amsterdam]",
            "2023-10-29T02:15:30>02:00[Europe/Amsterdam]",
            "2020-08-15T12:08:30+015960[Europe/Amsterdam]",
            # trailing/leading space
            " 2023-10-29T02:15:30+02:00[Europe/Amsterdam]",
            "2023-10-29T02:15:30+02:00[Europe/Amsterdam] ",
            # invalid offsets
            "1900-01-01T23:34:39.01-00:24:81[Europe/Dublin]",
            "2020-01-01T00:00:00+04:90[Asia/Calcutta]",
            "2020-01-01T00:00:00+0 :00[UTC]",
            "2023-10-29",  # only date
            "02:15:30",  # only time
            "2023-10-29T02:15:30",  # no offset
            "",  # empty
            "garbage",  # garbage
            "2023-10-29T02:15:30.0000000001+02:00[Europe/Amsterdam]",  # overly precise fraction
            "2023-10-29T02:15:30+02:00:00.00[Europe/Amsterdam]",  # subsecond offset
            "2023-10-29T02:15:30+0𝟙:00[Europe/Amsterdam]",
            "2020-08-15T12:08:30.000000001+29:00[Europe/Berlin]",  # out of range offset
            # decimal problems
            "2020-08-15T12:08:30.+02:00[Europe/Paris]",
            "2020-08-15T12:08:30. +02:00[Europe/Paris]",
            "2020-08-15T12:08:30,+02:00[Europe/Paris]",
            "2020-08-15T12:08:30,Z[Europe/Paris]",
            # invalid leap second cases
            "2020-08-15T12:34:61+00:00[UTC]",
            "2020-08-15T12:34:99+00:00[UTC]",
            # basic-format time is HH/HHMM/HHMMSS, not a separatorless fraction
            "2020-08-15T12083000+02:00[Europe/Amsterdam]",
            "20200815T120830123-0400[America/New_York]",
            "2020-08-15T120830.+00:00[UTC]",
        ],
    )
    def test_invalid(self, s):
        with pytest.raises(
            ValueError,
            match=r"^invalid ISO 8601 string: " + re.escape(repr(s)) + "$",
        ):
            ZonedDateTime.parse_iso(s)

    def test_invalid_tz(self):
        with pytest.raises(TimeZoneNotFoundError):
            ZonedDateTime.parse_iso(
                "2020-08-15T12:08:30+02:00[Europe/Nowhere]"
            )

        with pytest.raises(TimeZoneNotFoundError):
            ZonedDateTime.parse_iso("2020-08-15T12:08:30Z[X]")

        # a malformed ID is one that names no time zone, not a format error
        with pytest.raises(TimeZoneNotFoundError, match="not found"):
            ZonedDateTime.parse_iso(f"2023-10-29T02:15:30+02:00[{'X' * 9999}]")

        with pytest.raises(
            TimeZoneNotFoundError,
            match="^time zone ID 'Europe//Amsterdam' not found$",
        ):
            ZonedDateTime.parse_iso(
                "2023-10-29T02:15:30+02:00[Europe//Amsterdam]"
            )

        with pytest.raises(
            TimeZoneNotFoundError,
            match=r"^time zone ID 'Europe/Amster\\x00dam' not found$",
        ):
            ZonedDateTime.parse_iso(
                "2023-10-29T02:15:30+02:00[Europe/Amster\x00dam]"
            )

        # a non-ASCII string is not an ISO string, so no ID is read from it
        with pytest.raises(ValueError, match="invalid ISO 8601 string"):
            ZonedDateTime.parse_iso(
                f"2023-10-29T02:15:30+02:00[{chr(1600)}]",
            )

        assert issubclass(TimeZoneNotFoundError, ValueError)

    @pytest.mark.parametrize(
        "s",
        [
            "0001-01-01T00:15:30+09:00[Etc/GMT-9]",
            "9999-12-31T20:15:30-09:00[Etc/GMT+9]",
            "9999-12-31T20:15:30Z[Asia/Tokyo]",
            "0001-01-01T00:15:30Z[America/New_York]",
        ],
    )
    def test_out_of_range(self, s):
        with pytest.raises((ValueError, OverflowError), match="range|year"):
            ZonedDateTime.parse_iso(s)

    def test_offset_timezone_mismatch_message(self):
        # The message must actually say something: it was empty in the pure
        # Python backend, which no bare `pytest.raises` could catch.
        with pytest.raises(
            InvalidOffsetError,
            match="offset \\+03:00 does not match time zone 'Europe/Amsterdam'",
        ):
            ZonedDateTime.parse_iso("2023-05-01T12:00+03:00[Europe/Amsterdam]")

        # the message quotes the database spelling, not the ID as written
        with pytest.raises(
            InvalidOffsetError,
            match="offset \\+03:00 does not match time zone 'Europe/Amsterdam'",
        ):
            ZonedDateTime.parse_iso("2023-05-01T12:00+03:00[europe/amsterdam]")

    def test_offset_timezone_mismatch(self):
        with pytest.raises(InvalidOffsetError):
            # at the exact DST transition
            ZonedDateTime.parse_iso(
                "2023-10-29T02:15:30+03:00[Europe/Amsterdam]"
            )
        with pytest.raises(InvalidOffsetError):
            # some other time in the year
            ZonedDateTime.parse_iso(
                "2020-08-15T12:08:30+01:00:01[Europe/Amsterdam]"
            )

        with pytest.raises(InvalidOffsetError):
            # some other time in the year
            ZonedDateTime.parse_iso(
                "2020-08-15T12:08:30+00:00[Europe/Amsterdam]"
            )

        assert issubclass(InvalidOffsetError, ValueError)

    def test_skipped_time(self):
        with pytest.raises(InvalidOffsetError):
            ZonedDateTime.parse_iso(
                "2023-03-26T02:15:30+01:00[Europe/Amsterdam]"
            )

    @given(text())
    def test_fuzzing(self, s: str):
        with pytest.raises(
            ValueError,
            match=r"^invalid ISO 8601 string: " + re.escape(repr(s)) + "$",
        ):
            ZonedDateTime.parse_iso(s)


class TestEquality:
    @pytest.mark.parametrize(
        "d",
        [
            ZDT1,
            ZDT2,
            ZDT3,
            ZDT_POSIX,
            ZDT_RAWFILE,
        ],
    )
    def test_same_exact(self, d: ZonedDateTime):
        d2 = d.replace(year=d.year)  # create a new instance with same value
        assert d == d2
        assert not d != d2
        assert hash(d) == hash(d2)
        assert d.strict_eq(d2)

    @pytest.mark.parametrize(
        "d",
        [
            ZDT1,
            ZDT2,
            ZDT3,
            ZDT_POSIX,
            ZDT_RAWFILE,
        ],
    )
    def test_different_timezone(self, d: ZonedDateTime):
        # same **wall clock** time, different time zone
        d2 = d.replace(tz="America/Los_Angeles")
        assert d != d2
        assert not d == d2
        assert hash(d) != hash(d2)

        # same moment, different time zone
        d3 = d.to_tz("America/New_York")
        assert d == d3
        assert hash(d) == hash(d3)
        assert d.strict_eq(d3) is (d3 is d)

        with pytest.raises(
            TypeError,
            match=r"^strict_eq\(\) argument must be a ZonedDateTime$",
        ):
            d.strict_eq(d.to_instant())  # type: ignore[arg-type]

    @pytest.mark.parametrize(
        "d",
        [
            ZDT1,
            ZDT2,
            ZDT3,
            ZDT_POSIX,
            ZDT_RAWFILE,
        ],
    )
    def test_different_local_time(self, d: ZonedDateTime):
        d2 = d.replace(nanosecond=492_231)
        assert d != d2
        assert not d == d2
        assert hash(d) != hash(d2)

    @pytest.mark.parametrize(
        "d",
        [
            ZDT1,
            ZDT2,
            ZDT3,
            ZDT_POSIX,
            ZDT_RAWFILE,
        ],
    )
    def test_different_disambiguation(self, d: ZonedDateTime):
        d2 = d.replace(disambiguation="later")
        assert d == d2
        assert not d != d2
        assert hash(d) == hash(d2)

    @pytest.mark.parametrize(
        "tz",
        ["Europe/Amsterdam", AMS_TZ_POSIX, AMS_TZ_RAWFILE],
    )
    def test_repeated_time_differs_by_offset(self, tz: str):
        d = create_zdt(2023, 10, 29, 2, 15, 30, tz=tz)
        d2 = d.replace(disambiguation="later")
        assert d != d2
        assert not d == d2
        assert hash(d) != hash(d2)

    @pytest.mark.parametrize(
        "tz",
        ["Europe/Amsterdam", AMS_TZ_POSIX, AMS_TZ_RAWFILE],
    )
    def test_ambiguity_between_different_timezones(self, tz: str):
        a = create_zdt(
            2023,
            10,
            29,
            2,
            15,
            30,
            tz=tz,
            disambiguation="later",
        )
        b = a.to_tz("America/New_York")
        assert a.to_instant() == b.to_instant()  # sanity check
        assert hash(a) == hash(b)
        assert a == b

    def test_strict_eq_same_exact(self):
        a = ZonedDateTime(2020, 8, 15, 12, 8, 30, tz="Europe/Amsterdam")
        b = ZonedDateTime(2020, 8, 15, 12, 8, 30, tz="Europe/Amsterdam")
        assert a.strict_eq(b)

    def test_strict_eq_same_but_without_key(self):
        a = ZonedDateTime(2020, 8, 15, 12, 8, 30, tz="Europe/Amsterdam")
        b = create_zdt(2020, 8, 15, 12, 8, 30, tz=AMS_TZ_RAWFILE)
        assert not a.strict_eq(b)

    def test_strict_eq_different_zones(self):
        a = ZonedDateTime(
            2020, 8, 15, 12, 43, nanosecond=1, tz="Europe/Amsterdam"
        )
        b = a.to_tz("America/New_York")
        assert a == b
        assert not a.strict_eq(b)

        # Different zone but same offset
        c = a.to_tz("Europe/Paris")
        assert a == c
        assert not a.strict_eq(c)

    def test_strict_eq_same_timezone_repeated_time(self):
        a = ZonedDateTime(
            2023,
            10,
            29,
            2,
            15,
            nanosecond=1,
            tz="Europe/Amsterdam",
            disambiguation="earlier",
        )
        b = a.replace(disambiguation="later")
        assert a != b
        assert not a.strict_eq(b)

    def test_strict_eq_same_repeated_time(self):
        a = ZonedDateTime(
            2023,
            10,
            29,
            2,
            15,
            nanosecond=1,
            tz="Europe/Amsterdam",
            disambiguation="earlier",
        )
        b = a.replace(disambiguation="earlier")
        assert a.strict_eq(b)

    def test_strict_eq_same_unambiguous(self):
        a = ZonedDateTime(
            2020, 8, 15, 12, 43, nanosecond=1, tz="Europe/Amsterdam"
        )
        b = a.replace(disambiguation="later")
        assert a.strict_eq(b)
        assert a.strict_eq(b.replace(disambiguation="later"))

    def test_strict_eq_invalid(self):
        a = ZonedDateTime(2020, 8, 15, 12, 8, 30, tz="Europe/Amsterdam")
        with pytest.raises(
            TypeError, match="argument must be a ZonedDateTime"
        ):
            a.strict_eq(42)  # type: ignore[arg-type]

        with pytest.raises(
            TypeError, match="argument must be a ZonedDateTime"
        ):
            a.strict_eq(a.to_instant())  # type: ignore[arg-type]

    @staticmethod
    def _under_both_amsterdams(
        *local: int,
    ) -> tuple[ZonedDateTime, ZonedDateTime]:
        """Build the same local datetime under both Amsterdam definitions.

        Both time zones are loaded straight from a tzif file, so neither has an
        identifier and the two values differ only in the rules they carry.
        """
        with system_tz(AMS_TZ_RAWFILE):
            a = ZonedDateTime(*local, tz=SYSTEM_TZ)
        with system_tz(AMS_TZ_RAWFILE_DST_LATE):
            b = ZonedDateTime(*local, tz=SYSTEM_TZ)
        return a, b

    # Note: there is no test for a stale offset, i.e. a value whose offset
    # disagrees with its own time zone. Every constructor resolves the offset
    # from the time zone (the pickle reader warns and corrects), so such a value
    # is unreachable. It is also the only thing that would tell the two
    # backends apart: the extension compares the local datetime and the offset,
    # the Python version the instant they are derived from.

    def test_strict_eq_different_definition_same_offset(self):
        """Same moment, same offset, no identifier either side—but other rules."""
        a, b = self._under_both_amsterdams(2020, 8, 15, 12)
        assert a.tz_id is b.tz_id is None
        assert a.to_plain() == b.to_plain()
        assert a.offset == b.offset == hours(2)
        assert a == b  # the same moment in time
        assert not a.strict_eq(b)
        assert not b.strict_eq(a)

    def test_strict_eq_different_definition_different_offset(self):
        """The moved transition puts the same local datetime at a different offset."""
        a, b = self._under_both_amsterdams(2020, 10, 28, 12)
        assert a.tz_id is b.tz_id is None
        assert a.to_plain() == b.to_plain()
        assert a.offset == hours(1)
        assert b.offset == hours(2)
        assert not a.strict_eq(b)
        assert not b.strict_eq(a)

    def test_strict_eq_system_tz_compares_by_definition(self):
        """The system time zone has no identifier, so only its rules count."""
        with system_tz("Europe/Amsterdam"):
            a = ZonedDateTime(2020, 8, 15, 12, tz=SYSTEM_TZ)
            # force a reload, so the two values hold distinct time zone objects
            reset_system_tz()
            b = ZonedDateTime(2020, 8, 15, 12, tz=SYSTEM_TZ)
            assert a.strict_eq(b)
            assert b.strict_eq(a)


class TestComparison:
    @pytest.mark.parametrize(
        "tz",
        ["Europe/Amsterdam", AMS_TZ_POSIX, AMS_TZ_RAWFILE],
    )
    def test_different_timezones(self, tz: str):
        d = ZonedDateTime(2020, 8, 15, 15, 12, 9, tz="Asia/Kolkata")
        later = create_zdt(2020, 8, 15, 14, tz=tz)

        assert d < later
        assert d <= later
        assert later > d
        assert later >= d
        assert not d > later
        assert not d >= later
        assert not later < d
        assert not later <= d

    @pytest.mark.parametrize(
        "tz",
        ["Europe/Amsterdam", AMS_TZ_POSIX, AMS_TZ_RAWFILE],
    )
    def test_same_timezone_repeated_time(self, tz: str):
        d = create_zdt(
            2023,
            10,
            29,
            2,
            15,
            30,
            tz=tz,
            disambiguation="earlier",
        )
        later = create_zdt(
            2023,
            10,
            29,
            2,
            15,
            30,
            tz=tz,
            disambiguation="later",
        )
        assert d < later
        assert d <= later
        assert later > d
        assert later >= d
        assert not d > later
        assert not d >= later
        assert not later < d
        assert not later <= d

    @pytest.mark.parametrize(
        "tz",
        ["Europe/Amsterdam", AMS_TZ_POSIX, AMS_TZ_RAWFILE],
    )
    def test_different_timezone_same_time(self, tz: str):
        d = create_zdt(
            2023,
            10,
            29,
            2,
            15,
            30,
            tz=tz,
            disambiguation="earlier",
        )
        other = d.to_tz("America/New_York")
        assert not d < other
        assert d <= other
        assert not other > d
        assert other >= d
        assert not d > other
        assert d >= other
        assert not other < d
        assert other <= d

    @pytest.mark.parametrize(
        "tz",
        ["Europe/Amsterdam", AMS_TZ_POSIX, AMS_TZ_RAWFILE],
    )
    def test_system_tz(self, tz: str):
        d = create_zdt(2023, 10, 29, 2, 30, tz=tz, disambiguation="earlier")

        sys_eq = d.to_tz(SYSTEM_TZ)
        sys_lt = sys_eq.replace(minute=29, disambiguation="earlier")
        sys_gt = sys_eq.replace(minute=31, disambiguation="earlier")

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


class TestReplace:
    @pytest.mark.parametrize(
        "tz",
        ["Europe/Amsterdam", AMS_TZ_POSIX, AMS_TZ_RAWFILE],
    )
    def test_basics(self, tz: str):
        d = create_zdt(2020, 8, 15, 23, 12, 9, nanosecond=987_654, tz=tz)
        assert d.replace(year=2021).strict_eq(
            create_zdt(
                2021,
                8,
                15,
                23,
                12,
                9,
                nanosecond=987_654,
                tz=tz,
            )
        )
        assert d.replace(month=9, disambiguation="raise").strict_eq(
            create_zdt(
                2020,
                9,
                15,
                23,
                12,
                9,
                nanosecond=987_654,
                tz=tz,
            )
        )
        assert d.replace(day=16, disambiguation="raise").strict_eq(
            create_zdt(
                2020,
                8,
                16,
                23,
                12,
                9,
                nanosecond=987_654,
                tz=tz,
            )
        )
        assert d.replace(hour=0, disambiguation="raise").strict_eq(
            create_zdt(
                2020,
                8,
                15,
                0,
                12,
                9,
                nanosecond=987_654,
                tz=tz,
            )
        )
        assert d.replace(minute=0, disambiguation="raise").strict_eq(
            create_zdt(
                2020,
                8,
                15,
                23,
                0,
                9,
                nanosecond=987_654,
                tz=tz,
            )
        )
        assert d.replace(second=0, disambiguation="raise").strict_eq(
            create_zdt(
                2020,
                8,
                15,
                23,
                12,
                0,
                nanosecond=987_654,
                tz=tz,
            )
        )
        assert d.replace(nanosecond=0, disambiguation="raise").strict_eq(
            create_zdt(2020, 8, 15, 23, 12, 9, nanosecond=0, tz=tz)
        )
        assert d.replace(tz="Iceland", disambiguation="raise").strict_eq(
            ZonedDateTime(
                2020, 8, 15, 23, 12, 9, nanosecond=987_654, tz="Iceland"
            )
        )

    def test_out_of_range(self):
        d = ZonedDateTime(1, 1, 1, tz="America/New_York")

        with pytest.raises((ValueError, OverflowError), match="range|year"):
            d.replace(tz="Europe/Amsterdam", disambiguation="compatible")

        with pytest.raises((ValueError, OverflowError), match="range|year"):
            d.replace(
                year=9999,
                month=12,
                day=31,
                hour=23,
                disambiguation="compatible",
            )

    def test_system_tz(self):
        d = ZonedDateTime(2020, 8, 15, 12, 30, tz="Europe/Amsterdam")
        with system_tz("America/New_York"):
            result = d.replace(tz=SYSTEM_TZ, disambiguation="raise")
        # the local fields are kept; the time zone is the system's
        assert result.strict_eq(
            ZonedDateTime(2020, 8, 15, 12, 30, tz="America/New_York")
        )

    def test_invalid_disambiguation(self):
        d = ZonedDateTime(2020, 8, 15, tz="Europe/Amsterdam")
        with pytest.raises(
            ValueError, match=r"^invalid disambiguation: 'bogus'$"
        ):
            d.replace(hour=2, disambiguation="bogus")  # type: ignore[call-overload]

    @pytest.mark.parametrize(
        "tz",
        ["Europe/Amsterdam", AMS_TZ_POSIX, AMS_TZ_RAWFILE],
    )
    def test_repeated_time(self, tz: str):
        d = create_zdt(
            2023,
            10,
            29,
            2,
            15,
            30,
            tz=tz,
            disambiguation="earlier",
        )
        d_later = create_zdt(
            2023,
            10,
            29,
            2,
            15,
            30,
            tz=tz,
            disambiguation="later",
        )
        with pytest.raises(
            RepeatedTime,
            match="2023-10-29 02:15:30 is repeated in",
        ):
            d.replace(disambiguation="raise")

        assert d.replace(disambiguation="later").strict_eq(d_later)
        assert d.replace(disambiguation="earlier").strict_eq(d)
        assert d.replace(disambiguation="compatible").strict_eq(d)

        # earlier offset is reused if possible
        assert d.replace().strict_eq(d)
        assert d_later.replace().strict_eq(d_later)
        assert d.replace(minute=30).strict_eq(
            d.replace(minute=30, disambiguation="earlier")
        )
        assert d_later.replace(minute=30).strict_eq(
            d_later.replace(minute=30, disambiguation="later")
        )

        # Disambiguation may differ depending on whether we change tz
        # Note that only a named tz is relevant here
        if tz == "Europe/Amsterdam":
            assert d_later.replace(minute=30, tz=tz).strict_eq(
                d_later.replace(minute=30)
            )
        # Changing tz drops the offset, making the disambiguation implicit
        with warns_here(ImplicitDisambiguationWarning):
            paris = d_later.replace(minute=30, tz="Europe/Paris")
        assert not paris.strict_eq(d_later.replace(minute=30))

    @pytest.mark.parametrize(
        "tz", ["Europe/Amsterdam", AMS_TZ_POSIX, AMS_TZ_RAWFILE]
    )
    @pytest.mark.parametrize(
        "disambiguation, hour, new_tz",
        [
            ("earlier", 3, "Europe/Athens"),
            ("later", 1, "Europe/London"),
            ("earlier", 1, "Europe/London"),
            ("later", 3, "Europe/Athens"),
        ],
    )
    def test_repeated_time_with_tz_change(
        self, tz, disambiguation, hour, new_tz
    ):
        # The offset is not reused when changing time zone. The target local
        # time is repeated in the new time zone too, so this resolves
        # implicitly and warns.
        d = create_zdt(
            2023, 10, 29, 2, 15, 30, tz=tz, disambiguation=disambiguation
        )
        with warns_here(ImplicitDisambiguationWarning):
            result = d.replace(hour=hour, tz=new_tz)
        assert result.strict_eq(
            ZonedDateTime(
                2023,
                10,
                29,
                hour,
                15,
                30,
                tz=new_tz,
                disambiguation="compatible",
            )
        )

    @pytest.mark.parametrize(
        "tz",
        ["Europe/Amsterdam", AMS_TZ_POSIX, AMS_TZ_RAWFILE],
    )
    def test_skipped_time(self, tz: str):
        d = create_zdt(2023, 3, 26, 1, 15, 30, tz=tz)
        d_later = create_zdt(2023, 3, 26, 3, 15, 30, tz=tz)
        with pytest.raises(
            SkippedTime,
            match="2023-03-26 02:15:30 is skipped",
        ):
            d.replace(hour=2, disambiguation="raise")

        # default behavior without explicit disambiguation. Unlike a repeated
        # local time, a skipped one can't reuse the offset: the time doesn't
        # exist at all.
        # Instead, we go to the later time (same as disambiguation="compatible").
        # Since the offset can't decide the matter, this warns.
        with warns_here(ImplicitDisambiguationWarning):
            assert d.replace(hour=2).strict_eq(d_later)

        # Disambiguation may differ depending on whether we change tz.
        # Note that only a named tz is relevant here
        if tz == "Europe/Amsterdam":
            assert d.replace(
                hour=2, disambiguation="earlier", tz=tz
            ).strict_eq(d)
        with warns_here(ImplicitDisambiguationWarning):
            paris = d.replace(hour=2, tz="Europe/Paris")
        assert not paris.strict_eq(d)

        assert d.replace(hour=2, disambiguation="earlier").strict_eq(
            create_zdt(
                2023,
                3,
                26,
                2,
                15,
                30,
                tz=tz,
                disambiguation="earlier",
            )
        )

        assert d.replace(hour=2, disambiguation="later").strict_eq(
            create_zdt(
                2023,
                3,
                26,
                2,
                15,
                30,
                tz=tz,
                disambiguation="later",
            )
        )

        assert d.replace(hour=2, disambiguation="compatible").strict_eq(
            create_zdt(
                2023,
                3,
                26,
                2,
                15,
                30,
                tz=tz,
                disambiguation="compatible",
            )
        )

    @pytest.mark.parametrize(
        "tz", ["Europe/Amsterdam", AMS_TZ_POSIX, AMS_TZ_RAWFILE]
    )
    @pytest.mark.parametrize(
        "start_hour, hour, expect_hour, new_tz",
        [
            (1, 1, 2, "Europe/London"),
            (3, 3, 4, "Europe/Athens"),
            (1, 3, 4, "Europe/Athens"),
            (3, 1, 2, "Europe/London"),
            # ...also when only the tz is replaced
            (1, None, 2, "Europe/London"),
        ],
    )
    def test_skipped_time_with_tz_change(
        self, tz, start_hour, hour, expect_hour, new_tz
    ):
        # The offset is not reused when changing time zone. The target local
        # time is skipped in the new time zone too, so this resolves
        # implicitly and warns.
        d = create_zdt(2023, 3, 26, start_hour, 15, 30, tz=tz)
        kwargs = {} if hour is None else {"hour": hour}
        with warns_here(ImplicitDisambiguationWarning):
            result = d.replace(tz=new_tz, **kwargs)
        assert result.strict_eq(
            ZonedDateTime(2023, 3, 26, expect_hour, 15, 30, tz=new_tz)
        )

    def test_invalid(self):
        d = ZonedDateTime(2020, 8, 15, tz="Europe/Amsterdam")

        with pytest.raises(TypeError, match="tzinfo"):
            d.replace(tzinfo=py_timezone.utc, disambiguation="compatible")  # type: ignore[call-overload]

        with pytest.raises(TypeError, match="fold"):
            d.replace(fold=1, disambiguation="compatible")  # type: ignore[call-overload]

        with pytest.raises(TypeError, match="foo"):
            d.replace(foo="bar", disambiguation="compatible")  # type: ignore[call-overload]

        with pytest.raises(TimeZoneNotFoundError, match="Nowhere"):
            d.replace(tz="Nowhere", disambiguation="compatible")

        with pytest.raises(ValueError, match="date|day"):
            d.replace(year=2023, month=2, day=29, disambiguation="compatible")

        with pytest.raises(ValueError, match="nano|time"):
            d.replace(nanosecond=1_000_000_000, disambiguation="compatible")

    # replace_date()
    @pytest.mark.parametrize(
        "d",
        [
            ZDT1,
            ZDT2,
            ZDT3,
            ZDT_POSIX,
            ZDT_RAWFILE,
        ],
    )
    def test_date_unambiguous(self, d: ZonedDateTime):
        assert d.replace_date(Date(2021, 1, 2)).strict_eq(
            d.replace(year=2021, month=1, day=2)
        )

    @pytest.mark.parametrize(
        "d",
        [
            # before a repeated local time (a fold, in PEP 495's words)
            create_zdt(2020, 6, 1, 2, 15, 30, tz="Europe/Amsterdam"),
            create_zdt(2020, 6, 1, 2, 15, 30, tz=AMS_TZ_POSIX),
            create_zdt(2020, 6, 1, 2, 15, 30, tz=AMS_TZ_RAWFILE),
            # after a repeated local time
            create_zdt(2020, 11, 8, 2, 15, 30, tz="Europe/Amsterdam"),
            create_zdt(2020, 11, 8, 2, 15, 30, tz=AMS_TZ_POSIX),
            create_zdt(2020, 11, 8, 2, 15, 30, tz=AMS_TZ_RAWFILE),
            # in a repeated local time
            create_zdt(2022, 10, 30, 2, 30, 30, tz="Europe/Amsterdam"),
            create_zdt(2022, 10, 30, 2, 30, 30, tz=AMS_TZ_POSIX),
            create_zdt(2022, 10, 30, 2, 30, 30, tz=AMS_TZ_RAWFILE),
        ],
    )
    def test_date_repeated_time(self, d: ZonedDateTime):
        date = Date(2023, 10, 29)

        with pytest.raises(RepeatedTime):
            assert d.replace_date(date, disambiguation="raise")

        assert d.replace_date(date).strict_eq(
            d.replace(year=2023, month=10, day=29)
        )
        assert d.replace_date(date, disambiguation="earlier").strict_eq(
            d.replace(year=2023, month=10, day=29, disambiguation="earlier")
        )
        assert d.replace_date(date, disambiguation="later").strict_eq(
            d.replace(year=2023, month=10, day=29, disambiguation="later")
        )
        assert d.replace_date(date, disambiguation="compatible").strict_eq(
            d.replace(year=2023, month=10, day=29, disambiguation="compatible")
        )

    @pytest.mark.parametrize(
        "d",
        [
            # before the skipped local time (a gap, in PEP 495's words)
            create_zdt(2020, 1, 1, 2, 15, 30, tz="Europe/Amsterdam"),
            create_zdt(2020, 1, 1, 2, 15, 30, tz=AMS_TZ_POSIX),
            create_zdt(2020, 1, 1, 2, 15, 30, tz=AMS_TZ_RAWFILE),
            # after the skipped local time
            create_zdt(2020, 6, 1, 2, 15, 30, tz="Europe/Amsterdam"),
            create_zdt(2020, 6, 1, 2, 15, 30, tz=AMS_TZ_POSIX),
            create_zdt(2020, 6, 1, 2, 15, 30, tz=AMS_TZ_RAWFILE),
        ],
    )
    def test_date_skipped_time(self, d: ZonedDateTime):
        date = Date(2023, 3, 26)

        with pytest.raises(SkippedTime):
            assert d.replace_date(date, disambiguation="raise")

        # A skipped local time can't be resolved by preserving the offset,
        # so an omitted disambiguation is implicit here.
        with warns_here(ImplicitDisambiguationWarning):
            assert d.replace_date(date).strict_eq(
                d.replace(year=2023, month=3, day=26)
            )
        assert d.replace_date(date, disambiguation="earlier").strict_eq(
            d.replace(year=2023, month=3, day=26, disambiguation="earlier")
        )
        assert d.replace_date(date, disambiguation="later").strict_eq(
            d.replace(year=2023, month=3, day=26, disambiguation="later")
        )
        assert d.replace_date(date, disambiguation="compatible").strict_eq(
            d.replace(year=2023, month=3, day=26, disambiguation="compatible")
        )

    def test_date_invalid(self):
        d = ZonedDateTime(2020, 8, 15, 14, tz="Europe/Amsterdam")
        with pytest.raises((TypeError, AttributeError)):
            d.replace_date(object(), disambiguation="compatible")  # type: ignore[call-overload]

        with pytest.raises(ValueError, match="disambig"):
            d.replace_date(Date(2020, 8, 15), disambiguation="foo")  # type: ignore[call-overload]

        with pytest.raises(TypeError, match="got 2|foo"):
            d.replace_date(Date(2020, 8, 15), disambiguation="raise", foo=4)  # type: ignore[call-overload]

        with pytest.raises(TypeError, match="foo"):
            d.replace_date(Date(2020, 8, 15), foo="raise")  # type: ignore[call-overload]

    def test_date_out_of_range_due_to_offset(self):
        d = ZonedDateTime(2020, 1, 1, tz="Asia/Tokyo")
        with pytest.raises(
            ValueError, match="value or calculation out of range"
        ):
            d.replace_date(Date(1, 1, 1), disambiguation="compatible")

        d2 = ZonedDateTime(2020, 1, 1, hour=23, tz="America/New_York")
        with pytest.raises(
            ValueError, match="value or calculation out of range"
        ):
            d2.replace_date(Date(9999, 12, 31), disambiguation="compatible")

    @pytest.mark.parametrize(
        "d, date",
        [
            (ZonedDateTime(9999, 12, 30, 23, tz="Etc/GMT+12"), Date.MAX),
            (ZonedDateTime(1, 1, 2, tz="Etc/GMT-14"), Date.MIN),
        ],
    )
    def test_date_out_of_range_with_offset_preserved(self, d, date):
        # The local result is a valid datetime, but its instant is not
        with pytest.raises(
            ValueError, match="value or calculation out of range"
        ):
            d.replace_date(date)

    # replace_time()
    @pytest.mark.parametrize(
        "d",
        [
            ZDT1,
            ZDT2,
            ZDT3,
            ZDT_POSIX,
            ZDT_RAWFILE,
        ],
    )
    def test_time_unambiguous(self, d):
        assert d.replace_time(Time(1, 2, 3, nanosecond=4_000)).strict_eq(
            d.replace(hour=1, minute=2, second=3, nanosecond=4_000)
        )

    @pytest.mark.parametrize(
        "d",
        [
            # before a repeated local time (a fold, in PEP 495's words)
            create_zdt(2023, 10, 29, 0, 15, 30, tz="Europe/Amsterdam"),
            create_zdt(2023, 10, 29, 0, 15, 30, tz=AMS_TZ_POSIX),
            create_zdt(2023, 10, 29, 0, 15, 30, tz=AMS_TZ_RAWFILE),
            # after a repeated local time
            create_zdt(2023, 10, 29, 4, 15, 30, tz="Europe/Amsterdam"),
            create_zdt(2023, 10, 29, 4, 15, 30, tz=AMS_TZ_POSIX),
            create_zdt(2023, 10, 29, 4, 15, 30, tz=AMS_TZ_RAWFILE),
            # in a repeated local time
            create_zdt(2023, 10, 29, 2, 30, 30, tz="Europe/Amsterdam"),
            create_zdt(2023, 10, 29, 2, 30, 30, tz=AMS_TZ_POSIX),
            create_zdt(2023, 10, 29, 2, 30, 30, tz=AMS_TZ_RAWFILE),
        ],
    )
    def test_time_repeated_time(self, d: ZonedDateTime):
        time = Time(2, 15, 30)

        with pytest.raises(RepeatedTime):
            assert d.replace_time(time, disambiguation="raise")

        assert d.replace_time(time).strict_eq(
            d.replace(hour=2, minute=15, second=30)
        )
        assert d.replace_time(time, disambiguation="earlier").strict_eq(
            d.replace(hour=2, minute=15, second=30, disambiguation="earlier")
        )
        assert d.replace_time(time, disambiguation="later").strict_eq(
            d.replace(hour=2, minute=15, second=30, disambiguation="later")
        )
        assert d.replace_time(time, disambiguation="compatible").strict_eq(
            d.replace(
                hour=2, minute=15, second=30, disambiguation="compatible"
            )
        )

    @pytest.mark.parametrize(
        "d",
        [
            # before a skipped local time (a gap, in PEP 495's words)
            create_zdt(2023, 3, 26, 0, 15, tz="Europe/Amsterdam"),
            create_zdt(2023, 3, 26, 0, 15, tz=AMS_TZ_POSIX),
            create_zdt(2023, 3, 26, 0, 15, tz=AMS_TZ_RAWFILE),
            # after a skipped local time
            create_zdt(2023, 3, 26, 4, 15, tz="Europe/Amsterdam"),
            create_zdt(2023, 3, 26, 4, 15, tz=AMS_TZ_POSIX),
            create_zdt(2023, 3, 26, 4, 15, tz=AMS_TZ_RAWFILE),
        ],
    )
    def test_time_skipped_time(self, d: ZonedDateTime):
        time = Time(2, 15)
        with pytest.raises(SkippedTime):
            assert d.replace_time(time, disambiguation="raise")

        # A skipped local time can't be resolved by preserving the offset,
        # so an omitted disambiguation is implicit here.
        with warns_here(ImplicitDisambiguationWarning):
            assert d.replace_time(time).strict_eq(
                d.replace(hour=2, minute=15, second=0)
            )
        assert d.replace_time(time, disambiguation="earlier").strict_eq(
            d.replace(hour=2, minute=15, disambiguation="earlier")
        )
        assert d.replace_time(time, disambiguation="later").strict_eq(
            d.replace(hour=2, minute=15, disambiguation="later")
        )
        assert d.replace_time(time, disambiguation="compatible").strict_eq(
            d.replace(hour=2, minute=15, disambiguation="compatible")
        )

    def test_time_invalid(self):
        d = ZonedDateTime(2020, 8, 15, 14, tz="Europe/Amsterdam")
        with pytest.raises((TypeError, AttributeError)):
            d.replace_time(object(), disambiguation="later")  # type: ignore[call-overload]

        with pytest.raises(ValueError, match="disambig"):
            d.replace_time(Time(1, 2, 3), disambiguation="foo")  # type: ignore[call-overload]

        with pytest.raises(TypeError, match="got 2|foo"):
            d.replace_time(Time(1, 2, 3), disambiguation="raise", foo=4)  # type: ignore[call-overload]

        with pytest.raises(TypeError, match="foo"):
            d.replace_time(Time(1, 2, 3), foo="raise")  # type: ignore[call-overload]

    def test_time_out_of_range_due_to_offset(self):
        d = ZonedDateTime(1, 1, 1, hour=23, tz="Asia/Tokyo")
        with pytest.raises(
            ValueError, match="value or calculation out of range"
        ):
            d.replace_time(Time(1), disambiguation="compatible")

        d2 = ZonedDateTime(9999, 12, 31, hour=2, tz="America/New_York")
        with pytest.raises(
            ValueError, match="value or calculation out of range"
        ):
            d2.replace_time(Time(23), disambiguation="compatible")

    @pytest.mark.parametrize(
        "d, time",
        [
            (ZonedDateTime(9999, 12, 31, tz="Etc/GMT+12"), Time.MAX),
            (ZonedDateTime(1, 1, 1, 23, tz="Etc/GMT-14"), Time.MIN),
        ],
    )
    def test_time_out_of_range_with_offset_preserved(self, d, time):
        # The local result is a valid datetime, but its instant is not
        with pytest.raises(
            ValueError, match="value or calculation out of range"
        ):
            d.replace_time(time)


class TestShift:
    def test_subtract_overloads(self):
        d = ZonedDateTime(2020, 8, 15, tz="UTC")
        assert d.subtract(hours(1)) == d - hours(1)
        assert d.subtract(
            ItemizedDelta(days=1), disambiguation="compatible"
        ) == d.subtract(days=1, disambiguation="compatible")

    @pytest.mark.parametrize("bad", [None, 1, "bogus"])
    @pytest.mark.parametrize(
        "shift",
        [
            pytest.param(
                lambda m, bad: m(hours=1, disambiguation=bad), id="time_kwargs"
            ),
            pytest.param(
                lambda m, bad: m(days=0, disambiguation=bad), id="zero_days"
            ),
            pytest.param(
                lambda m, bad: m(hours(1), disambiguation=bad), id="TimeDelta"
            ),
            pytest.param(
                lambda m, bad: m(ItemizedDelta(hours=1), disambiguation=bad),
                id="ItemizedDelta",
            ),
            pytest.param(
                lambda m, bad: m(
                    ItemizedDateDelta(days=0), disambiguation=bad
                ),
                id="ItemizedDateDelta",
            ),
            pytest.param(lambda m, bad: m(disambiguation=bad), id="no_delta"),
        ],
    )
    @pytest.mark.parametrize("name", ["add", "subtract"])
    def test_invalid_disambiguation(self, name, shift, bad):
        # validated on entry, whether or not the shift consults it
        d = ZonedDateTime(2020, 8, 15, tz="Europe/Amsterdam")
        with pytest.raises(
            ValueError,
            match="^" + re.escape(f"invalid disambiguation: {bad!r}") + "$",
        ):
            shift(getattr(d, name), bad)

    def test_invalid_arguments(self):
        d = ZonedDateTime(2020, 8, 15, tz="UTC")
        with pytest.raises(TypeError):
            d.add(ItemizedDelta(days=1), days=1)  # type: ignore[call-overload]
        with pytest.raises(TypeError, match="must be a TimeDelta"):
            d.add(42)  # type: ignore[call-overload]

    @pytest.mark.parametrize(
        ("call", "exc", "message"),
        [
            (
                lambda d: d.add(hours(1), hours=1),
                TypeError,
                "add() cannot mix positional and keyword arguments",
            ),
            (
                lambda d: d.subtract(hours(1), hours(1)),
                TypeError,
                "subtract() takes at most one positional argument (2 given)",
            ),
            (
                lambda d: d.add(bogus=1),
                TypeError,
                "add() got an unexpected keyword argument 'bogus'",
            ),
            (
                lambda d: d.add(months=1.5),
                TypeError,
                "months must be an integer",
            ),
            (
                lambda d: d.add(days=1, nanoseconds="x"),
                TypeError,
                "nanoseconds must be an integer",
            ),
            (
                lambda d: d.add(days=1, hours=float("nan")),
                ValueError,
                "value or calculation out of range",
            ),
        ],
    )
    def test_rejected_argument_does_not_warn(self, call, exc, message):
        # One day on lands on a skipped local time, so the calendar stage
        # would warn if it ran before the exact keywords were read.
        d = ZonedDateTime(2023, 3, 25, 2, 30, tz="Europe/Amsterdam")
        with pytest.raises(exc, match="^" + re.escape(message) + "$"):
            call(d)

    def test_policy_accepted_on_every_form(self):
        d = ZonedDateTime(2020, 8, 15, tz="Europe/Amsterdam")
        # the TimeDelta overload declares no policy: an exact shift never
        # lands on a repeated or skipped local time
        assert d.add(hours(1), disambiguation="raise") == d + hours(1)  # type: ignore[call-overload]
        assert d.subtract(hours(1), disambiguation="raise") == d - hours(1)  # type: ignore[call-overload]

    @pytest.mark.parametrize(
        "call",
        [
            lambda d: d + 1,
            lambda d: d - 1,
            lambda d: 1 + d,
            lambda d: d - PlainDateTime(2020, 8, 15),
            lambda d: d + PlainDateTime(2020, 8, 15),
        ],
    )
    def test_rejected_operands(self, call):
        d = ZonedDateTime(2020, 8, 15, tz="UTC")
        with pytest.raises(TypeError, match="unsupported operand type"):
            call(d)

    @pytest.mark.parametrize(
        "tz",
        ["Europe/Amsterdam", AMS_TZ_POSIX, AMS_TZ_RAWFILE],
    )
    def test_zero(self, tz: str):
        d = create_zdt(2020, 8, 15, 23, 12, 9, nanosecond=987_654, tz=tz)
        assert (d + hours(0)).strict_eq(d)

        # the same with the method
        assert d.add().strict_eq(d)

        # the same with subtraction
        assert (d - hours(0)).strict_eq(d)
        assert d.subtract().strict_eq(d)

    @pytest.mark.parametrize(
        "tz",
        ["Europe/Amsterdam", AMS_TZ_POSIX, AMS_TZ_RAWFILE],
    )
    def test_repeated_time_plus_zero(self, tz: str):
        d = create_zdt(
            2023,
            10,
            29,
            2,
            15,
            30,
            disambiguation="earlier",
            tz=tz,
        )
        assert (d + hours(0)).strict_eq(d)
        assert (d.replace(disambiguation="later") + hours(0)).strict_eq(
            d.replace(disambiguation="later")
        )

        # the equivalent with the method
        assert d.add(hours=0).strict_eq(d)
        assert (
            d.replace(disambiguation="later")
            .add(hours=0)
            .strict_eq(d.replace(disambiguation="later"))
        )
        assert (
            d.replace(disambiguation="later")
            .add(ItemizedDelta(hours=0))
            .strict_eq(d.replace(disambiguation="later"))
        )

        # equivalent with subtraction
        assert (d - hours(0)).strict_eq(d)
        assert d.subtract(hours=0).strict_eq(d)
        assert d.subtract(ItemizedDelta(hours=0)).strict_eq(d)

    @pytest.mark.parametrize(
        "tz", ["Europe/Amsterdam", AMS_TZ_POSIX, AMS_TZ_RAWFILE]
    )
    def test_accounts_for_dst(self, tz: str):
        d = create_zdt(
            2023,
            10,
            29,
            2,
            15,
            30,
            disambiguation="earlier",
            tz=tz,
        )
        assert (d + hours(24)).strict_eq(
            create_zdt(2023, 10, 30, 1, 15, 30, tz=tz)
        )
        assert (d.replace(disambiguation="later") + hours(24)).strict_eq(
            create_zdt(2023, 10, 30, 2, 15, 30, tz=tz)
        )

        # the equivalent with the method (kwargs)
        assert d.add(hours=24).strict_eq(d + hours(24))
        assert (
            d.replace(disambiguation="later")
            .add(hours=24)
            .strict_eq(d.replace(disambiguation="later") + hours(24))
        )

        # equivalent with method (arg)
        assert d.add(hours(24)).strict_eq(d + hours(24))
        assert d.add(ItemizedDelta(minutes=24 * 60)).strict_eq(d + hours(24))
        assert (
            d.replace(disambiguation="later")
            .add(hours(24))
            .strict_eq(d.replace(disambiguation="later") + hours(24))
        )
        assert (
            d.replace(disambiguation="later")
            .add(ItemizedDelta(hours=24))
            .strict_eq(d.replace(disambiguation="later") + hours(24))
        )

        # equivalent with subtraction
        assert (d - hours(-24)).strict_eq(
            create_zdt(2023, 10, 30, 1, 15, 30, tz=tz)
        )
        assert d.subtract(hours=-24).strict_eq(d + hours(24))
        assert (
            d.replace(disambiguation="later")
            .subtract(hours=-24)
            .strict_eq(d.replace(disambiguation="later") + hours(24))
        )

    def test_out_of_range(self):
        d = ZonedDateTime(2020, 8, 15, tz="Africa/Abidjan")

        with pytest.raises((ValueError, OverflowError), match="range|year"):
            d + hours(24 * 366 * 8_000)

        # the equivalent with the method
        with pytest.raises((ValueError, OverflowError), match="range|year"):
            d.add(hours=24 * 366 * 8_000)

    # calendar units
    def test_out_of_bounds_min(self):
        d = ZonedDateTime(2000, 1, 1, tz="Europe/Amsterdam")
        with pytest.raises((ValueError, OverflowError), match="range|year"):
            d.add(years=-1999, disambiguation="compatible")

    def test_out_of_bounds_max(self):
        d = ZonedDateTime(2000, 12, 31, hour=23, tz="America/New_York")
        with pytest.raises((ValueError, OverflowError), match="range|year"):
            d.add(years=7999, disambiguation="compatible")

    def test_skipped_day(self):
        zdt = ZonedDateTime("2011-12-29T12-10:00[Pacific/Apia]")
        # Samoa skipped 2011-12-30 entirely, so the result lands on a
        # skipped local time
        with warns_here(ImplicitDisambiguationWarning):
            result = zdt.add(days=1)
        assert result.strict_eq(
            ZonedDateTime("2011-12-31 12:00:00+14:00[Pacific/Apia]")
        )

    def test_policy_onto_skipped_time(self):
        d = ZonedDateTime(2023, 3, 25, 2, 30, tz="Europe/Amsterdam")
        with pytest.raises(SkippedTime):
            d.add(days=1, disambiguation="raise")
        assert d.add(days=1, disambiguation="earlier").strict_eq(
            ZonedDateTime(2023, 3, 26, 1, 30, tz="Europe/Amsterdam")
        )
        assert d.add(days=1, disambiguation="later").strict_eq(
            ZonedDateTime(2023, 3, 26, 3, 30, tz="Europe/Amsterdam")
        )

    def test_policy_onto_repeated_time(self):
        d = ZonedDateTime(2023, 10, 28, 2, 30, tz="Europe/Amsterdam")
        with pytest.raises(RepeatedTime):
            d.add(days=1, disambiguation="raise")
        assert d.add(days=1, disambiguation="earlier").strict_eq(
            ZonedDateTime(
                2023,
                10,
                29,
                2,
                30,
                tz="Europe/Amsterdam",
                disambiguation="earlier",
            )
        )
        assert d.add(days=1, disambiguation="later").strict_eq(
            ZonedDateTime(
                2023,
                10,
                29,
                2,
                30,
                tz="Europe/Amsterdam",
                disambiguation="later",
            )
        )

    def test_carried_offset_matching_neither_occurrence_warns(self):
        # Amsterdam was at UTC+0:19:32 in 1900, so the carried offset
        # settles neither occurrence of the repeated local time
        d = ZonedDateTime(1900, 10, 29, 2, 30, tz="Europe/Amsterdam")
        with warns_here(ImplicitDisambiguationWarning):
            result = d.add(years=123)
        assert result.strict_eq(
            ZonedDateTime(
                2023,
                10,
                29,
                2,
                30,
                tz="Europe/Amsterdam",
                disambiguation="compatible",
            )
        )

    def test_calendar_units_apply_before_exact_units(self):
        # a day first (23 hours across the transition), then 24 hours
        d = ZonedDateTime(2023, 3, 25, 12, tz="Europe/Amsterdam")
        assert d.add(days=1, hours=24).strict_eq(
            ZonedDateTime(2023, 3, 27, 12, tz="Europe/Amsterdam")
        )
        # which is why the shift does not reverse across a transition
        assert (
            d.add(days=1, hours=24)
            .subtract(days=1, hours=24)
            .strict_eq(ZonedDateTime(2023, 3, 25, 11, tz="Europe/Amsterdam"))
        )


class TestDifference:
    @pytest.mark.parametrize(
        "tz", ["Europe/Amsterdam", AMS_TZ_POSIX, AMS_TZ_RAWFILE]
    )
    def test_simple(self, tz: str):
        d = create_zdt(2023, 10, 29, 5, tz=tz, disambiguation="earlier")
        other = create_zdt(2023, 10, 28, 3, nanosecond=4_000_000, tz=tz)
        assert d - other == (hours(27) - milliseconds(4))
        assert other - d == (hours(-27) + milliseconds(4))

        # same with the method
        assert d.difference(other) == d - other
        assert other.difference(d) == other - d

    @pytest.mark.parametrize(
        "tz", ["Europe/Amsterdam", AMS_TZ_POSIX, AMS_TZ_RAWFILE]
    )
    def test_repeated_time(self, tz: str):
        d = create_zdt(
            2023,
            10,
            29,
            2,
            15,
            tz=tz,
            disambiguation="earlier",
        )
        other = create_zdt(2023, 10, 28, 3, 15, tz=tz)
        assert d - other == hours(23)
        assert d.replace(disambiguation="later") - other == hours(24)
        assert other - d == hours(-23)
        assert other - d.replace(disambiguation="later") == hours(-24)

        # same with the method
        assert d.difference(other) == d - other

    def test_instant(self):
        d = ZonedDateTime(
            2023, 10, 29, 2, tz="Europe/Amsterdam", disambiguation="earlier"
        )
        other = Instant.from_utc(2023, 10, 28, 20)
        assert d - other == hours(4)
        assert d.replace(disambiguation="later") - other == hours(5)

        # same with the method
        assert d.difference(other) == d - other

    def test_offset(self):
        d = ZonedDateTime(
            2023, 10, 29, 2, tz="Europe/Amsterdam", disambiguation="earlier"
        )
        other = OffsetDateTime(2023, 10, 28, 20, offset=hours(1))
        assert d - other == hours(5)
        assert d.replace(disambiguation="later") - other == hours(6)

        # same with the method
        assert d.difference(other) == d - other

    def test_rejects_a_delta(self):
        d = ZonedDateTime(2023, 10, 29, tz="Europe/Amsterdam")
        with pytest.raises(
            TypeError,
            match="^difference\\(\\) argument must be an Instant, "
            "OffsetDateTime, or ZonedDateTime$",
        ):
            d.difference(hours(1))  # type: ignore[arg-type]


class TestSince:
    @pytest.mark.parametrize(
        ("unit", "expected"),
        [
            ("milliseconds", 86_400_000.0),
            ("microseconds", 86_400_000_000.0),
        ],
    )
    def test_total_subsecond_units(self, unit, expected):
        a = ZonedDateTime(2023, 2, 15, tz="Asia/Tokyo")
        b = ZonedDateTime(2023, 2, 14, tz="Asia/Tokyo")
        assert a.since(b, total=unit) == expected

    @pytest.mark.parametrize(
        "a, b, units, kwargs, expect",
        [
            # simple cases involving only calendar units
            (
                ZonedDateTime(
                    2023,
                    10,
                    29,
                    hour=11,
                    tz="Europe/Amsterdam",
                    disambiguation="earlier",
                ),
                ZonedDateTime(
                    2023,
                    10,
                    28,
                    hour=11,
                    tz="Europe/Amsterdam",
                    disambiguation="earlier",
                ),
                ["days"],
                {},
                ItemizedDelta(days=1),
            ),
            (
                ZonedDateTime(
                    2023,
                    10,
                    29,
                    hour=11,
                    tz="Europe/Amsterdam",
                    disambiguation="earlier",
                ),
                ZonedDateTime(
                    2023,
                    10,
                    28,
                    hour=10,
                    tz="Europe/Amsterdam",
                    disambiguation="earlier",
                ),
                ["days"],
                {},
                ItemizedDelta(days=1),
            ),
            (
                ZonedDateTime(
                    2025,
                    5,
                    31,
                    hour=23,
                    tz="Europe/Amsterdam",
                ),
                ZonedDateTime(
                    2023,
                    1,
                    28,
                    hour=1,
                    tz="Europe/Amsterdam",
                ),
                ["years", "months", "days"],
                {"round_increment": 2},
                ItemizedDelta(years=2, months=4, days=2),
            ),
            # calendar units only--but with time-of-day differences that affect rounding
            (
                ZonedDateTime(
                    2025,
                    5,
                    31,
                    hour=4,
                    tz="Europe/Amsterdam",
                ),
                ZonedDateTime(
                    2023,
                    1,
                    28,
                    hour=4,
                    nanosecond=1,
                    tz="Europe/Amsterdam",
                ),
                ["years", "months", "days"],
                {},
                ItemizedDelta(years=2, months=4, days=2),
            ),
            # same but with rounding
            (
                ZonedDateTime(
                    2025,
                    5,
                    31,
                    hour=4,
                    tz="Europe/Amsterdam",
                ),
                ZonedDateTime(
                    2023,
                    1,
                    28,
                    hour=4,
                    nanosecond=1,
                    tz="Europe/Amsterdam",
                ),
                ["years", "months", "days"],
                {"round_increment": 3, "round_mode": "half_ceil"},
                ItemizedDelta(years=2, months=4, days=3),
            ),
            (
                ZonedDateTime(
                    2025,
                    5,
                    31,
                    hour=4,
                    tz="Europe/Amsterdam",
                ),
                ZonedDateTime(
                    2025,
                    5,
                    1,
                    hour=4,
                    nanosecond=1,
                    tz="Europe/Amsterdam",
                ),
                ["years", "months", "days"],
                {"round_increment": 40, "round_mode": "floor"},
                ItemizedDelta(years=0, months=0, days=0),
            ),
            # Rounding affected by time-of-day
            (
                ZonedDateTime(
                    2023,
                    2,
                    15,
                    hour=13,
                    minute=25,
                    tz="Europe/Berlin",
                ),
                ZonedDateTime(
                    2021,
                    7,
                    3,
                    hour=1,
                    tz="Europe/Berlin",
                ),
                ["years", "days"],
                {"round_mode": "floor"},
                ItemizedDelta(years=1, days=227),
            ),
            (
                ZonedDateTime(
                    2023,
                    2,
                    15,
                    hour=13,
                    minute=25,
                    tz="Europe/Berlin",
                ),
                ZonedDateTime(
                    2021,
                    7,
                    3,
                    hour=1,
                    tz="Europe/Berlin",
                ),
                ["years", "days"],
                {"round_mode": "half_even"},
                ItemizedDelta(years=1, days=228),
            ),
            # Rounding affected by shorter days (due to DST)
            (
                ZonedDateTime(
                    2023,
                    10,
                    29,
                    hour=12,
                    minute=35,
                    tz="Europe/Berlin",
                ),
                ZonedDateTime(
                    2021,
                    7,
                    3,
                    hour=1,
                    tz="Europe/Berlin",
                ),
                ["years", "days"],
                {"round_mode": "half_even"},
                ItemizedDelta(years=2, days=119),
            ),
            (
                ZonedDateTime(
                    2023,
                    3,
                    26,
                    hour=13,
                    minute=25,
                    tz="Europe/Berlin",
                ),
                ZonedDateTime(
                    2021,
                    7,
                    3,
                    hour=1,
                    tz="Europe/Berlin",
                ),
                ["years", "days"],
                {"round_mode": "half_even"},
                ItemizedDelta(years=1, days=266),
            ),
            (
                ZonedDateTime(
                    2023,
                    3,
                    26,
                    hour=1,
                    minute=35,
                    tz="Europe/Berlin",
                ),
                ZonedDateTime(
                    2021,
                    7,
                    3,
                    hour=14,
                    tz="Europe/Berlin",
                ),
                ["years", "days"],
                {"round_mode": "half_even"},
                ItemizedDelta(years=1, days=266),
            ),
            # Rounding affected by disambiguation
            (
                ZonedDateTime(
                    2023,
                    3,
                    31,
                    hour=19,
                    minute=35,
                    tz="Europe/Berlin",
                ),
                ZonedDateTime(
                    2021,
                    1,
                    26,
                    hour=2,
                    minute=25,
                    tz="Europe/Berlin",
                ),
                ["years", "months"],
                {"round_mode": "half_even"},
                ItemizedDelta(years=2, months=2),
            ),
            (
                ZonedDateTime(
                    2023,
                    3,
                    20,
                    hour=19,
                    minute=35,
                    tz="Europe/Berlin",
                ),
                ZonedDateTime(
                    2820,
                    1,
                    26,
                    hour=2,
                    minute=25,
                    tz="Europe/Berlin",
                ),
                ["years", "months"],
                {"round_mode": "half_even"},
                ItemizedDelta(years=-796, months=-10),
            ),
            # Beyond calendar units
            (
                ZonedDateTime(
                    2023,
                    2,
                    15,
                    hour=13,
                    minute=25,
                    tz="Europe/Berlin",
                ),
                ZonedDateTime(
                    2021,
                    7,
                    3,
                    hour=1,
                    tz="Europe/Berlin",
                ),
                ["years", "weeks", "hours"],
                {"round_mode": "floor"},
                ItemizedDelta(years=1, weeks=32, hours=84),
            ),
            (
                ZonedDateTime(
                    2023,
                    2,
                    15,
                    hour=13,
                    minute=25,
                    tz="Europe/Berlin",
                ),
                ZonedDateTime(
                    2021,
                    7,
                    3,
                    hour=1,
                    tz="Europe/Berlin",
                ),
                ["years", "weeks", "minutes"],
                {"round_mode": "ceil", "round_increment": 12},
                ItemizedDelta(years=1, weeks=32, minutes=5076),
            ),
            (
                ZonedDateTime(
                    2020,
                    2,
                    15,
                    hour=13,
                    minute=25,
                    tz="Europe/Berlin",
                ),
                ZonedDateTime(
                    2021,
                    7,
                    3,
                    hour=1,
                    tz="Europe/Berlin",
                ),
                ["hours", "minutes"],
                {"round_mode": "ceil", "round_increment": 12},
                ItemizedDelta(hours=-12082, minutes=-24),
            ),
            # Handling skipped days (rare case involved international date line crossing)
            (
                ZonedDateTime("2011-12-31T21+14:00[Pacific/Apia]"),
                ZonedDateTime("2011-12-29T20-10:00[Pacific/Apia]"),
                ["days", "hours"],
                {},
                ItemizedDelta(days=2, hours=1),
            ),
            (
                ZonedDateTime("2011-12-31T21+14:00[Pacific/Apia]"),
                ZonedDateTime("2011-12-29T20:50-10:00[Pacific/Apia]"),
                ["hours", "minutes"],
                {},
                ItemizedDelta(hours=24, minutes=10),
            ),
            (
                ZonedDateTime("2011-12-31T17+14:00[Pacific/Apia]"),
                ZonedDateTime("2011-12-29T17-10:00[Pacific/Apia]"),
                ["days", "hours"],
                {},
                ItemizedDelta(days=2, hours=0),
            ),
            (
                ZonedDateTime("2011-12-31T17+14:00[Pacific/Apia]"),
                ZonedDateTime("2011-12-29T17-10:00[Pacific/Apia]"),
                ["hours"],
                {},
                ItemizedDelta(hours=24),
            ),
            (
                ZonedDateTime("2011-12-31T17+14:00[Pacific/Apia]"),
                ZonedDateTime("2011-12-29T18-10:00[Pacific/Apia]"),
                ["days", "hours"],
                {},
                ItemizedDelta(days=0, hours=23),
            ),
            (
                ZonedDateTime("2011-12-31T17+14:00[Pacific/Apia]"),
                ZonedDateTime("2011-12-29T16-10:00[Pacific/Apia]"),
                ["days", "hours"],
                {},
                ItemizedDelta(days=2, hours=1),
            ),
            (
                ZonedDateTime("2011-12-31T17+14:00[Pacific/Apia]"),
                ZonedDateTime("2011-12-29T16-10:00[Pacific/Apia]"),
                ["hours"],
                {},
                ItemizedDelta(hours=25),
            ),
            # DST-at-midnight case
            (
                ZonedDateTime(
                    2016,
                    2,
                    20,
                    hour=23,
                    minute=29,
                    tz="America/Sao_Paulo",
                    disambiguation="later",
                ),
                ZonedDateTime(
                    2016, 2, 19, hour=23, minute=45, tz="America/Sao_Paulo"
                ),
                ["days", "minutes"],
                {},
                ItemizedDelta(days=1, minutes=44),
            ),
            # Negative delta date truncation handled correctly
            (
                ZonedDateTime(2022, 2, 2, tz="Asia/Kolkata"),
                ZonedDateTime(2022, 2, 5, tz="Asia/Kolkata"),
                ["days"],
                {},
                ItemizedDelta(days=-3),
            ),
            (
                ZonedDateTime(2022, 2, 2, hour=3, tz="Asia/Kolkata"),
                ZonedDateTime(2022, 2, 5, hour=2, tz="Asia/Kolkata"),
                ["days", "hours"],
                {},
                ItemizedDelta(days=-2, hours=-23),
            ),
            (
                ZonedDateTime(2022, 2, 2, hour=3, tz="Asia/Kolkata"),
                ZonedDateTime(2022, 2, 5, hour=2, tz="Asia/Kolkata"),
                ["days"],
                {},
                ItemizedDelta(days=-2),
            ),
            (
                ZonedDateTime(2022, 2, 2, hour=3, tz="Asia/Kolkata"),
                ZonedDateTime(2022, 2, 5, hour=2, tz="Asia/Kolkata"),
                ["days"],
                {"round_mode": "floor"},
                ItemizedDelta(days=-3),
            ),
            # Zero situations
            (
                ZonedDateTime(
                    2020,
                    2,
                    15,
                    hour=13,
                    minute=25,
                    tz="Europe/Berlin",
                ),
                ZonedDateTime(
                    2021,
                    7,
                    3,
                    hour=1,
                    tz="Europe/Berlin",
                ),
                ["years"],
                {"round_mode": "trunc", "round_increment": 4},
                ItemizedDelta(years=0),
            ),
            (
                ZonedDateTime(
                    2023,
                    2,
                    15,
                    hour=13,
                    minute=25,
                    tz="Europe/Berlin",
                ),
                ZonedDateTime(
                    2021,
                    7,
                    3,
                    hour=1,
                    tz="Europe/Berlin",
                ),
                ["months"],
                {"round_mode": "trunc", "round_increment": 50},
                ItemizedDelta(months=0),
            ),
            (
                ZonedDateTime(
                    2023,
                    2,
                    15,
                    hour=13,
                    minute=25,
                    tz="Asia/Tokyo",
                ),
                ZonedDateTime(
                    2023,
                    2,
                    15,
                    hour=13,
                    minute=25,
                    tz="Asia/Tokyo",
                ),
                ["weeks"],
                {},
                ItemizedDelta(weeks=0),
            ),
            (
                ZonedDateTime(
                    2023,
                    2,
                    15,
                    hour=13,
                    minute=25,
                    tz="Asia/Tokyo",
                ),
                ZonedDateTime(
                    2023,
                    2,
                    15,
                    hour=13,
                    minute=25,
                    tz="Asia/Tokyo",
                ),
                ["seconds"],
                {},
                ItemizedDelta(seconds=0),
            ),
            # single unit cases
            (
                ZonedDateTime(
                    2023,
                    2,
                    15,
                    hour=13,
                    minute=25,
                    tz="Asia/Tokyo",
                ),
                ZonedDateTime(
                    2023,
                    2,
                    15,
                    hour=13,
                    minute=25,
                    nanosecond=1,
                    tz="Asia/Tokyo",
                ),
                ["seconds"],
                {},
                ItemizedDelta(seconds=0),
            ),
            (
                ZonedDateTime(
                    2023,
                    2,
                    15,
                    hour=13,
                    minute=25,
                    tz="Asia/Tokyo",
                ),
                ZonedDateTime(
                    2023,
                    2,
                    15,
                    hour=13,
                    minute=25,
                    second=1,
                    tz="Asia/Tokyo",
                ),
                ["seconds"],
                {},
                ItemizedDelta(seconds=-1),
            ),
            # different time zone
            (
                ZonedDateTime(
                    2023,
                    2,
                    15,
                    hour=13,
                    minute=25,
                    tz="Asia/Tokyo",
                ),
                ZonedDateTime(
                    2023,
                    2,
                    15,
                    hour=13,
                    minute=25,
                    second=1,
                    tz="America/Los_Angeles",
                ),
                ["hours", "minutes"],
                {},
                ItemizedDelta(hours=-17, minutes=0),
            ),
        ],
    )
    def test_examples(
        self,
        a: ZonedDateTime,
        b: ZonedDateTime,
        units: Sequence[
            Literal[
                "years",
                "months",
                "weeks",
                "days",
                "hours",
                "minutes",
                "seconds",
                "nanoseconds",
            ]
        ],
        kwargs: dict[str, Any],
        expect: ItemizedDelta,
    ):
        assert a.since(b, in_units=units, **kwargs).strict_eq(expect)

    @pytest.mark.parametrize(
        "a, b",
        [
            # spanning a skipped local time
            (
                ZonedDateTime(2023, 3, 27, 2, 30, tz="Europe/Amsterdam"),
                ZonedDateTime(2023, 3, 25, 2, 30, tz="Europe/Amsterdam"),
            ),
            # spanning a repeated local time
            (
                ZonedDateTime(2023, 10, 30, 2, 30, tz="Europe/Amsterdam"),
                ZonedDateTime(2023, 10, 28, 2, 30, tz="Europe/Amsterdam"),
            ),
            # spanning a skipped day
            (
                ZonedDateTime(2012, 1, 3, 12, tz="Pacific/Apia"),
                ZonedDateTime(2011, 12, 28, 12, tz="Pacific/Apia"),
            ),
        ],
    )
    def test_no_implicit_disambiguation_warning(self, a, b):
        # The intermediate values of a difference calculation aren't local
        # times the caller asked us to resolve, so they mustn't warn.
        with warnings.catch_warnings():
            warnings.simplefilter("error", ImplicitDisambiguationWarning)
            a.since(b, in_units=["months", "days", "hours", "minutes"])
            b.since(a, in_units=["months", "days", "hours", "minutes"])
            a.until(b, in_units=["days", "hours"])
            b.until(a, in_units=["days", "hours"])

    @pytest.mark.parametrize(
        "call",
        [
            lambda a, b: a.since(b, in_units=["days"]),
            lambda a, b: a.until(b, in_units=["months", "hours"]),
            lambda a, b: a.since(b, total="days"),
            lambda a, b: a.until(b, total="years"),
        ],
    )
    def test_cal_units_with_different_tz_not_supported(self, call):
        a = ZonedDateTime(2023, 2, 15, tz="Asia/Tokyo")
        b = ZonedDateTime(2023, 2, 15, tz="America/Los_Angeles")
        with pytest.raises(
            ValueError,
            match="^calendar units require the same time zone, "
            "got 'Asia/Tokyo' and 'America/Los_Angeles'$",
        ):
            call(a, b)

    @pytest.mark.parametrize("method", ["since", "until"])
    @pytest.mark.parametrize(
        "other",
        [
            OffsetDateTime(2021, 7, 3, offset=hours(9)),
            Instant.from_utc(2021, 7, 3),
            PlainDateTime(2021, 7, 3),
            hours(1),
        ],
    )
    def test_rejects_other_types(self, method, other):
        a = ZonedDateTime(2023, 2, 15, tz="Asia/Tokyo")
        with pytest.raises(
            TypeError,
            match=f"^{method}\\(\\) argument must be a ZonedDateTime$",
        ):
            getattr(a, method)(other, total="hours")

    def test_units_may_be_any_iterable(self):
        a = ZonedDateTime(2023, 2, 15, tz="Asia/Tokyo")
        b = ZonedDateTime(2023, 2, 14, tz="Asia/Tokyo")
        assert a.since(b, in_units=iter(["hours"])) == ItemizedDelta(hours=24)  # type: ignore[call-overload]

    @pytest.mark.parametrize(
        "a, b, mode, expect",
        [
            (
                ZonedDateTime(2024, 1, 1, tz="UTC"),
                ZonedDateTime(2024, 1, 2, 23, 30, tz="UTC"),
                "ceil",
                ItemizedDelta(days=2, hours=0),
            ),
            # 22.5 hours into a 23-hour day
            (
                ZonedDateTime(2023, 3, 26, tz="Europe/Amsterdam"),
                ZonedDateTime(2023, 3, 26, 23, 30, tz="Europe/Amsterdam"),
                "ceil",
                ItemizedDelta(days=1, hours=0),
            ),
            (
                ZonedDateTime(2023, 3, 26, tz="Europe/Amsterdam"),
                ZonedDateTime(2023, 3, 26, 23, 30, tz="Europe/Amsterdam"),
                "floor",
                ItemizedDelta(days=0, hours=22),
            ),
        ],
    )
    def test_rounding_up_carries_into_larger_units(self, a, b, mode, expect):
        assert (
            a.until(b, in_units=["days", "hours"], round_mode=mode) == expect
        )

    @pytest.mark.parametrize(
        ("kwargs", "message"),
        [
            ({"in_units": []}, "units must not be empty"),
            (
                {"in_units": ["hours", "hours"]},
                "units cannot contain duplicates",
            ),
            ({"in_units": ["foo"]}, "invalid unit: 'foo'"),
            (
                {"in_units": ["minutes", "hours"]},
                "units must be in decreasing order of size",
            ),
            (
                {"in_units": "hours"},
                "units must be a sequence of strings, not a single string",
            ),
            (
                {"in_units": ["hours", "nanoseconds"]},
                "nanoseconds can only be specified together with seconds",
            ),
            (
                {"in_units": ["hours"], "round_mode": "bad"},
                "invalid round_mode: 'bad'",
            ),
            (
                {"in_units": ["days"], "round_increment": 0},
                "round_increment must be a positive integer in range",
            ),
            (
                {"in_units": ["hours"], "round_increment": -1},
                "round_increment must be a positive integer in range",
            ),
            (
                {"in_units": ["hours"], "round_increment": 1.5},
                "round_increment must be an integer",
            ),
            (
                {"in_units": ["hours"], "round_increment": "1"},
                "round_increment must be an integer",
            ),
            (
                {"in_units": ["hours"], "round_increment": None},
                "round_increment must be an integer",
            ),
            (
                {"in_units": ["hours"], "round_increment": 2**63},
                "value or calculation out of range",
            ),
            ({"total": "foo"}, "invalid unit: 'foo'"),
        ],
    )
    @pytest.mark.parametrize("method", ["since", "until"])
    def test_invalid_units_and_rounding(self, method, kwargs, message):
        a = ZonedDateTime(2023, 2, 15, tz="Asia/Tokyo")
        b = ZonedDateTime(2023, 2, 14, tz="Asia/Tokyo")
        with pytest.raises(
            (TypeError, ValueError), match="^" + re.escape(message) + "$"
        ):
            getattr(a, method)(b, **kwargs)

    @pytest.mark.parametrize(
        ("unit", "expected"),
        [
            ("months", 1 / 28),
            ("weeks", 1 / 7),
            ("days", 1.0),
            ("minutes", 1440.0),
            ("seconds", 86_400.0),
        ],
    )
    def test_total_per_unit(self, unit, expected):
        a = ZonedDateTime(2023, 2, 15, 9, tz="Asia/Tokyo")
        b = ZonedDateTime(2023, 2, 14, 9, tz="Asia/Tokyo")
        assert a.since(b, total=unit) == pytest.approx(expected)

    def test_total_nanoseconds_returns_int(self):
        a = ZonedDateTime(2023, 2, 15, tz="Asia/Tokyo")
        b = ZonedDateTime(2023, 2, 14, tz="Asia/Tokyo")
        result = a.since(b, total="nanoseconds")
        assert isinstance(result, int)
        assert result == 86_400_000_000_000

    def test_very_large_increment(self):
        a = ZonedDateTime(2023, 2, 15, tz="Asia/Tokyo")
        b = ZonedDateTime(2021, 7, 3, tz="Asia/Tokyo")
        # round_increment=1<<65 ns exceeds i64::MAX; ceil mode rounds up to 1*(1<<65)
        assert a.since(
            b,
            in_units=["seconds", "nanoseconds"],
            round_increment=1 << 65,
            round_mode="ceil",
        ) == ItemizedDelta(seconds=36_893_488_147, nanoseconds=419_103_232)

    def test_until_is_inverse(self):
        a = ZonedDateTime(2023, 2, 15, hour=3, tz="Asia/Tokyo")
        b = ZonedDateTime(2021, 7, 3, tz="Asia/Tokyo")
        assert a.since(
            b, in_units=["years", "months", "days", "hours"]
        ) == b.until(a, in_units=["years", "months", "days", "hours"])
        # floor rounding works correctly
        assert a.since(
            b,
            in_units=["years", "months", "days", "hours"],
            round_increment=2,
            round_mode="floor",
        ) == b.until(
            a,
            in_units=["years", "months", "days", "hours"],
            round_increment=2,
            round_mode="floor",
        )

    def test_nanoseconds_dont_overflow(self):
        a = ZonedDateTime(9000, 1, 1, tz="UTC")
        b = ZonedDateTime(23, 3, 15, tz="UTC")
        assert a.since(b, total="nanoseconds") == 283280457600000000000

    def test_total_calendar_unit_same_tz(self):
        a = ZonedDateTime(2025, 3, 15, tz="Asia/Tokyo")
        b = ZonedDateTime(2023, 3, 15, tz="Asia/Tokyo")
        result = a.since(b, total="years")
        assert isinstance(result, float)
        assert result == 2.0

    @pytest.mark.parametrize(
        "kwargs, message",
        [
            ({}, "total.*in_units|in_units.*total"),
            (
                {"total": "hours", "in_units": ["hours"]},
                "total.*in_units|in_units.*total",
            ),
            (
                {"total": "hours", "round_mode": "floor"},
                "round_mode.*total|total.*round",
            ),
        ],
    )
    def test_conflicting_keywords(self, kwargs, message):
        a = ZonedDateTime(2023, 2, 15, tz="Asia/Tokyo")
        b = ZonedDateTime(2021, 7, 3, tz="Asia/Tokyo")
        with pytest.raises(TypeError, match=message):
            a.since(b, **kwargs)


class TestRound:
    @pytest.mark.parametrize(
        "d, increment, unit, floor, ceil, half_floor, half_ceil, half_even",
        [
            (
                ZonedDateTime(
                    2023, 7, 14, 1, nanosecond=459_999_999, tz="Europe/Paris"
                ),
                1,
                "nanosecond",
                ZonedDateTime(
                    2023, 7, 14, 1, nanosecond=459_999_999, tz="Europe/Paris"
                ),
                ZonedDateTime(
                    2023, 7, 14, 1, nanosecond=459_999_999, tz="Europe/Paris"
                ),
                ZonedDateTime(
                    2023, 7, 14, 1, nanosecond=459_999_999, tz="Europe/Paris"
                ),
                ZonedDateTime(
                    2023, 7, 14, 1, nanosecond=459_999_999, tz="Europe/Paris"
                ),
                ZonedDateTime(
                    2023, 7, 14, 1, nanosecond=459_999_999, tz="Europe/Paris"
                ),
            ),
            (
                ZonedDateTime(
                    2023,
                    7,
                    14,
                    1,
                    2,
                    21,
                    nanosecond=459_999_999,
                    tz="Europe/Paris",
                ),
                4,
                "second",
                ZonedDateTime(2023, 7, 14, 1, 2, 20, tz="Europe/Paris"),
                ZonedDateTime(2023, 7, 14, 1, 2, 24, tz="Europe/Paris"),
                ZonedDateTime(2023, 7, 14, 1, 2, 20, tz="Europe/Paris"),
                ZonedDateTime(2023, 7, 14, 1, 2, 20, tz="Europe/Paris"),
                ZonedDateTime(2023, 7, 14, 1, 2, 20, tz="Europe/Paris"),
            ),
            (
                ZonedDateTime(
                    2023,
                    7,
                    14,
                    23,
                    52,
                    29,
                    nanosecond=999_999_999,
                    tz="Europe/Paris",
                ),
                10,
                "minute",
                ZonedDateTime(2023, 7, 14, 23, 50, 0, tz="Europe/Paris"),
                ZonedDateTime(2023, 7, 15, tz="Europe/Paris"),
                ZonedDateTime(2023, 7, 14, 23, 50, 0, tz="Europe/Paris"),
                ZonedDateTime(2023, 7, 14, 23, 50, 0, tz="Europe/Paris"),
                ZonedDateTime(2023, 7, 14, 23, 50, 0, tz="Europe/Paris"),
            ),
            (
                ZonedDateTime(
                    2023,
                    7,
                    14,
                    11,
                    59,
                    29,
                    nanosecond=999_999_999,
                    tz="Europe/Paris",
                ),
                12,
                "hour",
                ZonedDateTime(2023, 7, 14, tz="Europe/Paris"),
                ZonedDateTime(2023, 7, 14, 12, 0, 0, tz="Europe/Paris"),
                ZonedDateTime(2023, 7, 14, 12, 0, 0, tz="Europe/Paris"),
                ZonedDateTime(2023, 7, 14, 12, 0, 0, tz="Europe/Paris"),
                ZonedDateTime(2023, 7, 14, 12, 0, 0, tz="Europe/Paris"),
            ),
            # Unusual increment, but still divides a day evenly
            (
                ZonedDateTime(
                    2023,
                    7,
                    14,
                    11,
                    59,
                    29,
                    nanosecond=999_999_999,
                    tz="Europe/Paris",
                ),
                90,
                "minute",
                ZonedDateTime(2023, 7, 14, 10, 30, tz="Europe/Paris"),
                ZonedDateTime(2023, 7, 14, 12, 0, 0, tz="Europe/Paris"),
                ZonedDateTime(2023, 7, 14, 12, 0, 0, tz="Europe/Paris"),
                ZonedDateTime(2023, 7, 14, 12, 0, 0, tz="Europe/Paris"),
                ZonedDateTime(2023, 7, 14, 12, 0, 0, tz="Europe/Paris"),
            ),
            # normal, 24-hour day at midnight
            (
                ZonedDateTime(2023, 7, 14, tz="Europe/Paris"),
                1,
                "day",
                ZonedDateTime(2023, 7, 14, tz="Europe/Paris"),
                ZonedDateTime(2023, 7, 14, tz="Europe/Paris"),
                ZonedDateTime(2023, 7, 14, tz="Europe/Paris"),
                ZonedDateTime(2023, 7, 14, tz="Europe/Paris"),
                ZonedDateTime(2023, 7, 14, tz="Europe/Paris"),
            ),
            # normal, 24-hour day
            (
                ZonedDateTime(2023, 7, 14, 12, tz="Europe/Paris"),
                1,
                "day",
                ZonedDateTime(2023, 7, 14, tz="Europe/Paris"),
                ZonedDateTime(2023, 7, 15, tz="Europe/Paris"),
                ZonedDateTime(2023, 7, 14, tz="Europe/Paris"),
                ZonedDateTime(2023, 7, 15, tz="Europe/Paris"),
                ZonedDateTime(2023, 7, 14, tz="Europe/Paris"),
            ),
            # shorter day (23 hours): only 10h30m has elapsed at 11:30
            (
                ZonedDateTime(2023, 3, 26, 11, 30, tz="Europe/Paris"),
                1,
                "day",
                ZonedDateTime(2023, 3, 26, tz="Europe/Paris"),
                ZonedDateTime(2023, 3, 27, tz="Europe/Paris"),
                ZonedDateTime(2023, 3, 26, tz="Europe/Paris"),
                ZonedDateTime(2023, 3, 26, tz="Europe/Paris"),
                ZonedDateTime(2023, 3, 26, tz="Europe/Paris"),
            ),
            # longer day (24.5 hours): 12h45m has elapsed at 12:15
            (
                ZonedDateTime(2024, 4, 7, 12, 15, tz="Australia/Lord_Howe"),
                1,
                "day",
                ZonedDateTime(2024, 4, 7, tz="Australia/Lord_Howe"),
                ZonedDateTime(2024, 4, 8, tz="Australia/Lord_Howe"),
                ZonedDateTime(2024, 4, 8, tz="Australia/Lord_Howe"),
                ZonedDateTime(2024, 4, 8, tz="Australia/Lord_Howe"),
                ZonedDateTime(2024, 4, 8, tz="Australia/Lord_Howe"),
            ),
            # keeps the offset if possible
            (
                ZonedDateTime(
                    2023,
                    10,
                    29,
                    2,
                    15,
                    tz="Europe/Paris",
                    disambiguation="later",
                ),
                30,
                "minute",
                ZonedDateTime(
                    2023,
                    10,
                    29,
                    2,
                    0,
                    tz="Europe/Paris",
                    disambiguation="later",
                ),
                ZonedDateTime(
                    2023,
                    10,
                    29,
                    2,
                    30,
                    tz="Europe/Paris",
                    disambiguation="later",
                ),
                ZonedDateTime(
                    2023,
                    10,
                    29,
                    2,
                    0,
                    tz="Europe/Paris",
                    disambiguation="later",
                ),
                ZonedDateTime(
                    2023,
                    10,
                    29,
                    2,
                    30,
                    tz="Europe/Paris",
                    disambiguation="later",
                ),
                ZonedDateTime(
                    2023,
                    10,
                    29,
                    2,
                    0,
                    tz="Europe/Paris",
                    disambiguation="later",
                ),
            ),
        ],
    )
    def test_round(
        self,
        d: ZonedDateTime,
        increment,
        unit,
        floor,
        ceil,
        half_floor,
        half_ceil,
        half_even,
    ):
        assert d.round(unit, increment=increment) == half_even
        assert d.round(unit, increment=increment, mode="floor") == floor
        assert d.round(unit, increment=increment, mode="trunc") == floor
        assert d.round(unit, increment=increment, mode="ceil") == ceil
        assert d.round(unit, increment=increment, mode="expand") == ceil
        assert (
            d.round(unit, increment=increment, mode="half_floor") == half_floor
        )
        assert (
            d.round(unit, increment=increment, mode="half_trunc") == half_floor
        )
        assert (
            d.round(unit, increment=increment, mode="half_ceil") == half_ceil
        )
        assert (
            d.round(unit, increment=increment, mode="half_expand") == half_ceil
        )
        assert (
            d.round(unit, increment=increment, mode="half_even") == half_even
        )

    def test_default(self):
        d = ZonedDateTime(
            2023, 7, 14, 1, 2, 3, nanosecond=500_000_000, tz="Europe/Paris"
        )
        assert d.round() == ZonedDateTime(
            2023, 7, 14, 1, 2, 4, tz="Europe/Paris"
        )
        assert d.replace(second=8).round() == ZonedDateTime(
            2023, 7, 14, 1, 2, 8, tz="Europe/Paris"
        )

    def test_default_increment(self):
        d = ZonedDateTime(
            2023, 7, 14, 1, 2, 3, nanosecond=800_000, tz="Europe/Paris"
        )
        assert d.round("millisecond").strict_eq(
            ZonedDateTime(
                2023, 7, 14, 1, 2, 3, nanosecond=1_000_000, tz="Europe/Paris"
            )
        )

    # a value already on the increment validates the mode too
    @pytest.mark.parametrize(
        "d",
        [
            ZonedDateTime(
                2023, 7, 14, 1, 2, 3, nanosecond=4_000, tz="Europe/Paris"
            ),
            ZonedDateTime(2023, 7, 14, 1, 2, 3, tz="Europe/Paris"),
        ],
    )
    @pytest.mark.parametrize("mode", ["foo", "TRUNC", None, 3])
    def test_invalid_mode(self, d, mode):
        with pytest.raises(ValueError, match=f"^invalid mode: {mode!r}$"):
            d.round("second", mode=mode)

    @pytest.mark.parametrize(
        "unit, increment",
        [
            ("minute", 21),
            ("second", 14),
            ("millisecond", 13),
            ("day", 2),
            ("hour", 48),
            ("microsecond", 1542),
            ("microsecond", 7),
            ("second", 1 << 62),
        ],
    )
    def test_increment_does_not_divide_day(self, unit, increment):
        d = ZonedDateTime(
            2023, 7, 14, 1, 2, 3, nanosecond=4_000, tz="Europe/Paris"
        )
        with pytest.raises(
            ValueError, match="^increment must divide a 24-hour day evenly$"
        ):
            d.round(unit, increment=increment)

    @pytest.mark.parametrize("increment", [0, -5])
    def test_increment_not_positive(self, increment):
        d = ZonedDateTime(2023, 7, 14, 1, 2, 3, tz="Europe/Paris")
        with pytest.raises(
            ValueError, match="^increment must be a positive integer$"
        ):
            d.round("minute", increment=increment)

    @pytest.mark.parametrize(
        "increment", [1.5, float("nan"), "5", Fraction(3, 2)]
    )
    def test_increment_not_an_integer(self, increment):
        d = ZonedDateTime(2023, 7, 14, 1, 2, 3, tz="Europe/Paris")
        with pytest.raises(TypeError, match="^increment must be an integer$"):
            d.round("second", increment=increment)

    def test_increment_read_through_index(self):
        d = ZonedDateTime(2023, 7, 14, 12, 39, 59, tz="Europe/Paris")
        assert d.round("minute", increment=True) == d.round("minute")
        assert d.round("minute", increment=cast(int, Idx())) == d.round(
            "minute", increment=5
        )

    @pytest.mark.parametrize("unit", ["foo", "week", "minutes", None, 5])
    def test_invalid_unit(self, unit):
        d = ZonedDateTime(
            2023, 7, 14, 1, 2, 3, nanosecond=4_000, tz="Europe/Paris"
        )
        with pytest.raises(ValueError, match=f"^invalid unit: {unit!r}$"):
            d.round(unit)

    def test_range_edges(self):
        last = ZonedDateTime(
            9999, 12, 31, 23, 59, 59, nanosecond=999_999_999, tz="Etc/UTC"
        )
        assert last.round("hour", mode="floor").strict_eq(
            ZonedDateTime(9999, 12, 31, 23, tz="Etc/UTC")
        )
        with pytest.raises(
            ValueError, match="^value or calculation out of range$"
        ):
            last.round("hour", mode="ceil")
        with pytest.raises(
            ValueError, match="^value or calculation out of range$"
        ):
            last.round("hour", increment=4)
        with pytest.raises(
            ValueError, match="^value or calculation out of range$"
        ):
            last.round("day")

        first = ZonedDateTime(1, 1, 1, tz="Etc/UTC")
        just_after = first.add(seconds=1)
        assert just_after.round("hour", mode="floor").strict_eq(first)
        assert just_after.round("day", mode="floor").strict_eq(first)
        assert just_after.round("hour", mode="ceil").strict_eq(
            ZonedDateTime(1, 1, 1, 1, tz="Etc/UTC")
        )

    def test_round_by_timedelta(self):
        d = ZonedDateTime(2020, 8, 15, 23, 24, 18, tz="Europe/Amsterdam")
        assert d.round(TimeDelta(minutes=15)) == ZonedDateTime(
            2020, 8, 15, 23, 30, tz="Europe/Amsterdam"
        )
        assert d.round(TimeDelta(hours=1)) == ZonedDateTime(
            2020, 8, 15, 23, tz="Europe/Amsterdam"
        )
        assert d.round(TimeDelta(minutes=15), mode="floor") == ZonedDateTime(
            2020, 8, 15, 23, 15, tz="Europe/Amsterdam"
        )

    @pytest.mark.parametrize("unit", [hours(7), hours(25)])
    def test_round_by_timedelta_not_dividing_day(self, unit):
        d = ZonedDateTime(2020, 8, 15, 12, tz="Europe/Amsterdam")
        with pytest.raises(
            ValueError, match="^unit must divide a 24-hour day evenly$"
        ):
            d.round(unit)

    @pytest.mark.parametrize("unit", [hours(-1), TimeDelta.ZERO])
    def test_round_by_timedelta_not_positive(self, unit):
        d = ZonedDateTime(2020, 8, 15, 12, tz="Europe/Amsterdam")
        with pytest.raises(
            ValueError, match="^unit must be a positive TimeDelta$"
        ):
            d.round(unit)

    @pytest.mark.parametrize("increment", [1, 2])
    def test_round_by_timedelta_with_increment(self, increment):
        d = ZonedDateTime(2020, 8, 15, 12, tz="Europe/Amsterdam")
        with pytest.raises(
            TypeError,
            match="^cannot specify an increment with a TimeDelta argument$",
        ):
            d.round(TimeDelta(hours=1), increment=increment)  # type: ignore[call-overload]

    # Amsterdam clocks fell back from 03:00 to 02:00 on 2023-10-29, so 02:30
    # occurs twice. A TimeDelta unit follows the time-unit rule: the result
    # keeps the offset it started from.
    @pytest.mark.parametrize("disambiguation", ["earlier", "later"])
    def test_round_by_timedelta_inside_a_fold_keeps_the_offset(
        self, disambiguation
    ):
        d = ZonedDateTime(
            2023,
            10,
            29,
            2,
            30,
            tz="Europe/Amsterdam",
            disambiguation=disambiguation,
        )
        assert d.round(TimeDelta(minutes=20)).strict_eq(d.replace(minute=40))

    # Colombo clocks fell back from 00:30 to 00:00 on 2006-04-15, a fold
    # shorter than an hour: rounding to the hour takes the first occurrence
    @pytest.mark.parametrize("disambiguation", ["earlier", "later"])
    def test_round_inside_a_fold_shorter_than_the_increment(
        self, disambiguation
    ):
        d = ZonedDateTime(
            2006,
            4,
            15,
            0,
            15,
            tz="Asia/Colombo",
            disambiguation=disambiguation,
        )
        first = ZonedDateTime(
            2006, 4, 15, tz="Asia/Colombo", disambiguation="earlier"
        )
        assert d.round("hour", mode="floor").strict_eq(first)
        assert d.round(TimeDelta(hours=1), mode="floor").strict_eq(first)
        # a 15-minute increment fits inside the fold, so the offset is kept
        assert d.round("minute", increment=15, mode="floor").strict_eq(d)

    # On 2023-10-01, Lord Howe clocks jump from 02:00 to 02:30, so a 20-minute
    # grid has a point (02:20) strictly inside the gap.
    LORD_HOWE_BEFORE = ZonedDateTime.parse_iso(
        "2023-10-01T02:35:00+11:00[Australia/Lord_Howe]"
    )
    LORD_HOWE_AFTER = ZonedDateTime.parse_iso(
        "2023-10-01T02:55:00+11:00[Australia/Lord_Howe]"
    )

    @pytest.mark.parametrize(
        "unit, increment",
        [("minute", 20), (TimeDelta(minutes=20), 1)],
    )
    def test_round_floor_into_gap_snaps_to_edge(self, unit, increment):
        kwargs = (
            {} if isinstance(unit, TimeDelta) else {"increment": increment}
        )
        assert self.LORD_HOWE_BEFORE.round(
            unit, mode="floor", **kwargs
        ).strict_eq(
            ZonedDateTime(2023, 10, 1, 2, 30, tz="Australia/Lord_Howe")
        )
        assert self.LORD_HOWE_AFTER.round(
            unit, mode="floor", **kwargs
        ).strict_eq(
            ZonedDateTime(2023, 10, 1, 2, 40, tz="Australia/Lord_Howe")
        )

    @pytest.mark.parametrize(
        "mode",
        [
            "ceil",
            "expand",
            "floor",
            "trunc",
            "half_ceil",
            "half_expand",
            "half_floor",
            "half_trunc",
            "half_even",
        ],
    )
    @pytest.mark.parametrize(
        "unit, increment",
        [("minute", 20), (TimeDelta(minutes=20), 1)],
    )
    def test_round_is_monotonic_across_gap(self, mode, unit, increment):
        kwargs = (
            {} if isinstance(unit, TimeDelta) else {"increment": increment}
        )
        earlier = self.LORD_HOWE_BEFORE.round(unit, mode=mode, **kwargs)
        later = self.LORD_HOWE_AFTER.round(unit, mode=mode, **kwargs)
        assert earlier <= later
        if mode in ("floor", "trunc"):
            assert earlier <= self.LORD_HOWE_BEFORE
            assert later <= self.LORD_HOWE_AFTER

    # Amsterdam 2023-03-26 is 23 hours, so half a day is 11h30m of elapsed
    # time, reached at 12:30 on the clock. 2023-10-29 is 25 hours, so half is
    # 12h30m, reached at 11:30.
    @pytest.mark.parametrize(
        "d, expect",
        [
            (
                ZonedDateTime(2023, 3, 26, 12, 29, tz="Europe/Amsterdam"),
                ZonedDateTime(2023, 3, 26, tz="Europe/Amsterdam"),
            ),
            (
                ZonedDateTime(2023, 3, 26, 12, 31, tz="Europe/Amsterdam"),
                ZonedDateTime(2023, 3, 27, tz="Europe/Amsterdam"),
            ),
            (
                ZonedDateTime(2023, 10, 29, 11, 29, tz="Europe/Amsterdam"),
                ZonedDateTime(2023, 10, 29, tz="Europe/Amsterdam"),
            ),
            (
                ZonedDateTime(2023, 10, 29, 11, 31, tz="Europe/Amsterdam"),
                ZonedDateTime(2023, 10, 30, tz="Europe/Amsterdam"),
            ),
        ],
    )
    def test_round_day_measures_elapsed_time(self, d, expect):
        assert d.round("day").strict_eq(expect)


class TestStartOf:
    @pytest.mark.parametrize(
        "unit, expect",
        [
            ("year", ZonedDateTime(2024, 1, 1, tz="America/New_York")),
            ("month", ZonedDateTime(2024, 8, 1, tz="America/New_York")),
            # Thursday Aug 15 -> Monday Aug 12 at midnight
            ("week_mon", ZonedDateTime(2024, 8, 12, tz="America/New_York")),
            # Thursday Aug 15 -> Sunday Aug 11 at midnight
            ("week_sun", ZonedDateTime(2024, 8, 11, tz="America/New_York")),
            ("day", ZonedDateTime(2024, 8, 15, tz="America/New_York")),
            ("hour", ZonedDateTime(2024, 8, 15, 14, tz="America/New_York")),
            (
                "minute",
                ZonedDateTime(2024, 8, 15, 14, 30, tz="America/New_York"),
            ),
            (
                "second",
                ZonedDateTime(2024, 8, 15, 14, 30, 45, tz="America/New_York"),
            ),
        ],
    )
    def test_per_unit(self, unit, expect):
        zdt = ZonedDateTime(
            2024, 8, 15, 14, 30, 45, nanosecond=123, tz="America/New_York"
        )
        assert zdt.start_of(unit).strict_eq(expect)

    def test_invalid_unit(self):
        with pytest.raises(ValueError, match="^invalid unit: 'invalid'$"):
            ZonedDateTime(2024, 8, 15, 14, 30, tz="America/New_York").start_of(
                "invalid"  # type: ignore[arg-type]
            )

    def test_week_value_error(self):
        with pytest.raises(
            ValueError,
            match="^invalid unit: 'week', use 'week_mon' or 'week_sun'$",
        ):
            ZonedDateTime(2024, 8, 15, 14, 30, tz="America/New_York").start_of(
                "week"  # type: ignore[arg-type]
            )

    def test_non_hour_gap(self):
        # Lord Howe starts DST: 2:00-2:29 does not exist
        zdt = ZonedDateTime(2024, 10, 6, 2, 45, tz="Australia/Lord_Howe")
        result = zdt.start_of("hour")
        assert result.strict_eq(
            ZonedDateTime(2024, 10, 6, 2, 30, tz="Australia/Lord_Howe")
        )
        assert zdt.start_of("day").strict_eq(
            ZonedDateTime(2024, 10, 6, tz="Australia/Lord_Howe")
        )

    def test_non_minute_aligned_gap(self):
        # Monrovia advanced from 00:00 to 00:44:30 on Jan 7, 1972.
        zdt = ZonedDateTime(
            1972,
            1,
            7,
            0,
            44,
            45,
            nanosecond=123,
            tz="Africa/Monrovia",
        )
        result = zdt.start_of("minute")
        assert result.strict_eq(
            ZonedDateTime(1972, 1, 7, 0, 44, 30, tz="Africa/Monrovia")
        )
        assert (
            ZonedDateTime(1972, 1, 6, 23, 59, 45, tz="Africa/Monrovia")
            .end_of("minute")
            .add(nanoseconds=1)
            .strict_eq(result)
        )

    def test_non_hour_fold(self):
        # Lord Howe end of DST: Apr 7, 1:30-1:59 occurs twice.
        zdt = ZonedDateTime(
            2024,
            4,
            7,
            1,
            45,
            tz="Australia/Lord_Howe",
            disambiguation="earlier",
        )
        zdt_later = zdt.replace(disambiguation="later")
        expect = ZonedDateTime(2024, 4, 7, 1, tz="Australia/Lord_Howe")
        assert zdt.start_of("hour").strict_eq(expect)
        assert (
            zdt.replace(disambiguation="later")
            .start_of("hour")
            .strict_eq(expect)
        )

        # For small units, the offset is preserved
        assert zdt.start_of("minute").strict_eq(zdt)
        assert zdt_later.start_of("minute").strict_eq(zdt_later)
        assert (
            zdt.replace(minute=30, second=1, disambiguation="later")
            .start_of("minute")
            .strict_eq(
                zdt.replace(minute=30, second=0, disambiguation="later")
            )
        )

    # Colombo clocks fell back from 00:30 to 00:00 on 2006-04-15, a fold
    # shorter than an hour that begins on the hour boundary
    @pytest.mark.parametrize("disambiguation", ["earlier", "later"])
    def test_fold_shorter_than_the_unit_takes_the_first_occurrence(
        self, disambiguation
    ):
        zdt = ZonedDateTime(
            2006,
            4,
            15,
            0,
            15,
            tz="Asia/Colombo",
            disambiguation=disambiguation,
        )
        assert zdt.start_of("hour").strict_eq(
            ZonedDateTime(
                2006, 4, 15, tz="Asia/Colombo", disambiguation="earlier"
            )
        )
        # the fold is longer than a minute, so the offset is kept
        assert zdt.start_of("minute").strict_eq(zdt)

    def test_fold_shorter_than_the_unit_other_zones(self):
        # Colombo 1996-10-26: 00:30 back to 00:00
        assert (
            ZonedDateTime(
                1996, 10, 26, 0, 15, tz="Asia/Colombo", disambiguation="later"
            )
            .start_of("hour")
            .strict_eq(
                ZonedDateTime(
                    1996, 10, 26, tz="Asia/Colombo", disambiguation="earlier"
                )
            )
        )
        # Barbados 1944-09-10: 02:30 back to 02:00
        assert (
            ZonedDateTime(
                1944,
                9,
                10,
                2,
                15,
                tz="America/Barbados",
                disambiguation="later",
            )
            .start_of("hour")
            .strict_eq(
                ZonedDateTime(
                    1944,
                    9,
                    10,
                    2,
                    tz="America/Barbados",
                    disambiguation="earlier",
                )
            )
        )

    # Denver adopted standard time on 1883-11-18: 12:00:04 LMT back to
    # 12:00:00 MST, a fold of four seconds
    @pytest.mark.parametrize("disambiguation", ["earlier", "later"])
    def test_fold_of_seconds(self, disambiguation):
        zdt = ZonedDateTime(
            1883,
            11,
            18,
            12,
            0,
            2,
            tz="America/Denver",
            disambiguation=disambiguation,
        )
        noon_lmt = ZonedDateTime(
            1883, 11, 18, 12, tz="America/Denver", disambiguation="earlier"
        )
        assert noon_lmt.offset == TimeDelta(hours=-6, minutes=-59, seconds=-56)
        assert zdt.start_of("hour").strict_eq(noon_lmt)
        assert zdt.start_of("minute").strict_eq(noon_lmt)
        # the fold is longer than a second, so the offset is kept
        assert zdt.start_of("second").strict_eq(zdt)

    # Amsterdam clocks fell back from 03:00 to 02:00 on 2023-10-29, so 02:30
    # occurs twice
    AMS_FOLD = [
        ZonedDateTime(
            2023, 10, 29, 2, 30, tz="Europe/Amsterdam", disambiguation=d
        )
        for d in ("earlier", "later")
    ]

    @pytest.mark.parametrize("d", AMS_FOLD)
    @pytest.mark.parametrize(
        "unit, expect",
        [
            ("week_mon", ZonedDateTime(2023, 10, 23, tz="Europe/Amsterdam")),
            ("week_sun", ZonedDateTime(2023, 10, 29, tz="Europe/Amsterdam")),
            ("month", ZonedDateTime(2023, 10, 1, tz="Europe/Amsterdam")),
            ("year", ZonedDateTime(2023, 1, 1, tz="Europe/Amsterdam")),
        ],
    )
    def test_calendar_unit_inside_a_fold(self, d, unit, expect):
        # which occurrence the call starts from does not change the boundary
        assert d.start_of(unit).strict_eq(expect)

    @pytest.mark.parametrize("d", AMS_FOLD)
    def test_second_inside_a_fold_keeps_the_offset(self, d):
        assert d.start_of("second").strict_eq(d)

    def test_range_edges(self):
        # 0001-01-01 is a Monday, 9999-12-31 a Friday
        first = ZonedDateTime(1, 1, 1, tz="UTC")
        assert first.start_of("week_mon").strict_eq(first)
        with pytest.raises(
            ValueError, match="^value or calculation out of range$"
        ):
            first.start_of("week_sun")

        last = ZonedDateTime(9999, 12, 31, 23, 59, 59, tz="UTC")
        assert last.start_of("week_mon").strict_eq(
            ZonedDateTime(9999, 12, 27, tz="UTC")
        )
        assert last.start_of("week_sun").strict_eq(
            ZonedDateTime(9999, 12, 26, tz="UTC")
        )


class TestEndOf:
    @pytest.mark.parametrize(
        "unit, expect",
        [
            ("year", (2024, 12, 31, 23, 59, 59)),
            ("month", (2024, 8, 31, 23, 59, 59)),
            # Thursday Aug 15 -> Sunday Aug 18 end of day
            ("week_mon", (2024, 8, 18, 23, 59, 59)),
            # Thursday Aug 15 -> Saturday Aug 17 end of day
            ("week_sun", (2024, 8, 17, 23, 59, 59)),
            ("day", (2024, 8, 15, 23, 59, 59)),
            ("hour", (2024, 8, 15, 14, 59, 59)),
            ("minute", (2024, 8, 15, 14, 30, 59)),
            ("second", (2024, 8, 15, 14, 30, 45)),
        ],
    )
    def test_per_unit(self, unit, expect):
        zdt = ZonedDateTime(
            2024, 8, 15, 14, 30, 45, nanosecond=123, tz="America/New_York"
        )
        assert zdt.end_of(unit).strict_eq(
            ZonedDateTime(
                *expect, nanosecond=999_999_999, tz="America/New_York"
            )
        )

    @pytest.mark.parametrize(
        ("unit", "next_start"),
        [
            ("year", ZonedDateTime(2025, 1, 1, tz="America/New_York")),
            ("month", ZonedDateTime(2024, 9, 1, tz="America/New_York")),
            ("week_mon", ZonedDateTime(2024, 8, 19, tz="America/New_York")),
            ("week_sun", ZonedDateTime(2024, 8, 18, tz="America/New_York")),
            ("day", ZonedDateTime(2024, 8, 16, tz="America/New_York")),
            ("hour", ZonedDateTime(2024, 8, 15, 15, tz="America/New_York")),
            (
                "minute",
                ZonedDateTime(2024, 8, 15, 14, 31, tz="America/New_York"),
            ),
            (
                "second",
                ZonedDateTime(2024, 8, 15, 14, 30, 46, tz="America/New_York"),
            ),
        ],
    )
    def test_adjacent_to_next_start(self, unit, next_start):
        zdt = ZonedDateTime(
            2024,
            8,
            15,
            14,
            30,
            45,
            nanosecond=123,
            tz="America/New_York",
        )
        assert zdt.end_of(unit).add(nanoseconds=1).strict_eq(next_start)

    def test_month_feb_leap(self):
        zdt = ZonedDateTime(2024, 2, 10, 12, tz="America/New_York")
        result = zdt.end_of("month")
        assert result.strict_eq(
            ZonedDateTime(
                2024,
                2,
                29,
                23,
                59,
                59,
                nanosecond=999_999_999,
                tz="America/New_York",
            )
        )

    @pytest.mark.parametrize(
        ("tz", "hour"),
        [
            ("UTC", 23),
            ("America/New_York", 18),
        ],
    )
    def test_hour_at_upper_boundary(self, tz, hour):
        zdt = ZonedDateTime(9999, 12, 31, hour, tz=tz)
        assert zdt.end_of("hour").strict_eq(
            ZonedDateTime(
                9999,
                12,
                31,
                hour,
                59,
                59,
                nanosecond=999_999_999,
                tz=tz,
            )
        )

    def test_invalid_unit(self):
        with pytest.raises(ValueError, match="^invalid unit: 'invalid'$"):
            ZonedDateTime(2024, 8, 15, 14, 30, tz="America/New_York").end_of(
                "invalid"  # type: ignore[arg-type]
            )

    def test_week_value_error(self):
        with pytest.raises(
            ValueError,
            match="^invalid unit: 'week', use 'week_mon' or 'week_sun'$",
        ):
            ZonedDateTime(2024, 8, 15, 14, 30, tz="America/New_York").end_of(
                "week"  # type: ignore[arg-type]
            )

    def test_month_feb_non_leap(self):
        zdt = ZonedDateTime(2023, 2, 10, 12, tz="Europe/Amsterdam")
        assert zdt.end_of("month").strict_eq(
            ZonedDateTime(
                2023,
                2,
                28,
                23,
                59,
                59,
                nanosecond=999_999_999,
                tz="Europe/Amsterdam",
            )
        )

    def test_week_end_on_dst_boundary(self):
        zdt = ZonedDateTime(2016, 2, 20, tz="America/Sao_Paulo")
        result = zdt.end_of("week_sun")
        assert result.strict_eq(
            ZonedDateTime(
                2016,
                2,
                21,
                4,
                tz="America/Sao_Paulo",
            )
            .start_of("week_sun")
            .subtract(nanoseconds=1)
        )

    def test_day_end_on_dst_boundary(self):
        zdt = ZonedDateTime(2016, 2, 20, tz="America/Sao_Paulo")
        result = zdt.end_of("day")
        assert result.strict_eq(
            ZonedDateTime(
                2016,
                2,
                21,
                4,
                tz="America/Sao_Paulo",
            )
            .start_of("day")
            .subtract(nanoseconds=1)
        )

    def test_non_hour_gap(self):
        # Lord Howe: at 2:00 AM Oct 6, clocks spring forward 30min.
        zdt = ZonedDateTime(2024, 10, 6, 2, 45, tz="Australia/Lord_Howe")
        result = zdt.end_of("hour")
        assert result.strict_eq(
            ZonedDateTime(
                2024,
                10,
                6,
                2,
                59,
                59,
                nanosecond=999_999_999,
                tz="Australia/Lord_Howe",
            )
        )
        assert (
            ZonedDateTime(2024, 10, 6, 1, 45, tz="Australia/Lord_Howe")
            .end_of("hour")
            .strict_eq(
                ZonedDateTime(
                    2024,
                    10,
                    6,
                    1,
                    59,
                    59,
                    nanosecond=999_999_999,
                    tz="Australia/Lord_Howe",
                )
            )
        )

    def test_end_lands_in_gap(self):
        # Caracas advanced from 02:30 to 03:00 on May 1, 2016.
        zdt = ZonedDateTime(2016, 5, 1, 2, 15, tz="America/Caracas")
        assert zdt.end_of("hour").strict_eq(
            ZonedDateTime(
                2016,
                5,
                1,
                2,
                29,
                59,
                nanosecond=999_999_999,
                tz="America/Caracas",
            )
        )

    def test_non_hour_fold(self):
        # Lord Howe end of DST: 1:30-1:59 occurs twice.
        zdt_e = ZonedDateTime(
            2024,
            4,
            7,
            1,
            45,
            tz="Australia/Lord_Howe",
            disambiguation="earlier",
        )
        zdt_l = zdt_e.replace(disambiguation="later")
        # end of 'hour' consumes the fold
        assert zdt_e.end_of("hour").strict_eq(
            zdt_e.replace(
                hour=1,
                minute=59,
                second=59,
                nanosecond=999_999_999,
                disambiguation="later",
            )
        )
        assert zdt_l.end_of("hour").strict_eq(
            zdt_l.replace(
                hour=1,
                minute=59,
                second=59,
                nanosecond=999_999_999,
            )
        )
        # end of minute does *not* consume the fold
        assert zdt_e.end_of("minute").strict_eq(
            zdt_e.replace(
                second=59,
                nanosecond=999_999_999,
                disambiguation="earlier",
            )
        )
        assert zdt_l.end_of("minute").strict_eq(
            zdt_l.replace(
                second=59,
                nanosecond=999_999_999,
            )
        )

    def test_hour_fold_does_not_consume_full_hour_fold(self):
        zdt = ZonedDateTime(
            2024,
            11,
            3,
            1,
            30,
            tz="America/New_York",
            disambiguation="earlier",
        )
        assert zdt.end_of("hour").strict_eq(
            ZonedDateTime(
                2024,
                11,
                3,
                1,
                59,
                59,
                nanosecond=999_999_999,
                tz="America/New_York",
                disambiguation="earlier",
            )
        )

    # Amsterdam clocks fell back from 03:00 to 02:00 on 2023-10-29, so 02:30
    # occurs twice
    AMS_FOLD = [
        ZonedDateTime(
            2023, 10, 29, 2, 30, tz="Europe/Amsterdam", disambiguation=d
        )
        for d in ("earlier", "later")
    ]

    @pytest.mark.parametrize("d", AMS_FOLD)
    @pytest.mark.parametrize(
        "unit, next_start",
        [
            ("week_mon", ZonedDateTime(2023, 10, 30, tz="Europe/Amsterdam")),
            ("week_sun", ZonedDateTime(2023, 11, 5, tz="Europe/Amsterdam")),
            ("month", ZonedDateTime(2023, 11, 1, tz="Europe/Amsterdam")),
            ("year", ZonedDateTime(2024, 1, 1, tz="Europe/Amsterdam")),
        ],
    )
    def test_calendar_unit_inside_a_fold(self, d, unit, next_start):
        # which occurrence the call starts from does not change the boundary
        assert d.end_of(unit).strict_eq(next_start.subtract(nanoseconds=1))

    @pytest.mark.parametrize("d", AMS_FOLD)
    def test_second_inside_a_fold_keeps_the_offset(self, d):
        assert d.end_of("second").strict_eq(d.replace(nanosecond=999_999_999))

    # Lord Howe clocks fell back from 02:00 to 01:30 on 2024-04-07, a fold
    # shorter than an hour but longer than a minute
    @pytest.mark.parametrize("disambiguation", ["earlier", "later"])
    def test_time_unit_inside_a_short_fold_keeps_the_offset(
        self, disambiguation
    ):
        zdt = ZonedDateTime(
            2024,
            4,
            7,
            1,
            45,
            30,
            tz="Australia/Lord_Howe",
            disambiguation=disambiguation,
        )
        assert zdt.end_of("second").strict_eq(
            zdt.replace(nanosecond=999_999_999)
        )
        assert zdt.end_of("minute").strict_eq(
            zdt.replace(second=59, nanosecond=999_999_999)
        )

    # Colombo clocks fell back from 00:30 to 00:00 on 2006-04-15, a fold
    # shorter than an hour that begins on the hour boundary: the hour
    # intervals still tile the timeline
    @pytest.mark.parametrize("disambiguation", ["earlier", "later"])
    def test_fold_shorter_than_the_unit_on_the_boundary(self, disambiguation):
        zdt = ZonedDateTime(
            2006,
            4,
            15,
            0,
            15,
            tz="Asia/Colombo",
            disambiguation=disambiguation,
        )
        end = zdt.end_of("hour")
        assert end.strict_eq(
            ZonedDateTime(
                2006,
                4,
                15,
                0,
                59,
                59,
                nanosecond=999_999_999,
                tz="Asia/Colombo",
            )
        )
        assert end.add(nanoseconds=1).strict_eq(
            ZonedDateTime(2006, 4, 15, 1, tz="Asia/Colombo")
        )
        # the previous hour ends one nanosecond before the shared start
        assert (
            ZonedDateTime(2006, 4, 14, 23, 45, tz="Asia/Colombo")
            .end_of("hour")
            .add(nanoseconds=1)
            .strict_eq(zdt.start_of("hour"))
        )

    def test_fold_shorter_than_the_unit_other_zones(self):
        # Barbados 1944-09-10: 02:30 back to 02:00
        assert (
            ZonedDateTime(
                1944,
                9,
                10,
                2,
                15,
                tz="America/Barbados",
                disambiguation="later",
            )
            .end_of("hour")
            .strict_eq(
                ZonedDateTime(
                    1944,
                    9,
                    10,
                    2,
                    59,
                    59,
                    nanosecond=999_999_999,
                    tz="America/Barbados",
                )
            )
        )
        # Denver 1883-11-18: 12:00:04 LMT back to 12:00:00 MST
        assert (
            ZonedDateTime(1883, 11, 18, 11, 59, 30, tz="America/Denver")
            .end_of("hour")
            .add(nanoseconds=1)
            .strict_eq(
                ZonedDateTime(
                    1883,
                    11,
                    18,
                    12,
                    tz="America/Denver",
                    disambiguation="earlier",
                )
            )
        )

    def test_range_edges(self):
        # 0001-01-01 is a Monday, 9999-12-31 a Friday
        first = ZonedDateTime(1, 1, 1, tz="UTC")
        assert first.end_of("week_mon").strict_eq(
            ZonedDateTime(
                1, 1, 7, 23, 59, 59, nanosecond=999_999_999, tz="UTC"
            )
        )
        assert first.end_of("week_sun").strict_eq(
            ZonedDateTime(
                1, 1, 6, 23, 59, 59, nanosecond=999_999_999, tz="UTC"
            )
        )

        last = ZonedDateTime(9999, 12, 31, tz="UTC")
        assert last.end_of("hour").strict_eq(
            ZonedDateTime(
                9999, 12, 31, 0, 59, 59, nanosecond=999_999_999, tz="UTC"
            )
        )

    @pytest.mark.parametrize(
        "unit", ["day", "week_mon", "week_sun", "month", "year"]
    )
    def test_past_the_range(self, unit):
        # the end of a calendar unit is computed from the next start, which
        # lies past the range for every unit that ends on 9999-12-31
        last = ZonedDateTime(9999, 12, 31, tz="UTC")
        with pytest.raises(
            ValueError, match="^value or calculation out of range$"
        ):
            last.end_of(unit)


class TestCalendarProperties:
    @pytest.mark.parametrize(
        "d, expect",
        [
            (ZonedDateTime(2024, 2, 29, 12, tz="America/New_York"), 60),
            (ZonedDateTime(2023, 1, 1, 0, tz="America/New_York"), 1),
            (ZonedDateTime(2023, 12, 31, 12, tz="America/New_York"), 365),
            (ZonedDateTime(2024, 12, 31, 12, tz="America/New_York"), 366),
        ],
    )
    def test_day_of_year(self, d, expect):
        assert d.day_of_year() == expect

    @pytest.mark.parametrize(
        "d, expect",
        [
            (ZonedDateTime(2024, 2, 29, 12, tz="America/New_York"), 29),
            (ZonedDateTime(2023, 2, 15, 12, tz="America/New_York"), 28),
            (ZonedDateTime(2023, 1, 15, 12, tz="America/New_York"), 31),
            (ZonedDateTime(1900, 2, 15, 12, tz="UTC"), 28),
            (ZonedDateTime(2000, 2, 15, 12, tz="UTC"), 29),
        ],
    )
    def test_days_in_month(self, d, expect):
        assert d.days_in_month() == expect

    @pytest.mark.parametrize(
        "d, days, leap",
        [
            (ZonedDateTime(2024, 2, 29, 12, tz="America/New_York"), 366, True),
            (
                ZonedDateTime(2023, 6, 15, 12, tz="America/New_York"),
                365,
                False,
            ),
            (ZonedDateTime(1900, 6, 15, 12, tz="UTC"), 365, False),
            (ZonedDateTime(2000, 6, 15, 12, tz="UTC"), 366, True),
        ],
    )
    def test_days_in_year_and_in_leap_year(self, d, days, leap):
        assert d.days_in_year() == days
        assert d.in_leap_year() is leap


class TestIsRepeated:
    def test_fixed_offset_zone(self):
        d = ZonedDateTime(2020, 8, 15, tz="Etc/GMT+3")
        assert d.is_repeated() is False

    @pytest.mark.parametrize(
        "tz",
        ["Europe/Amsterdam", AMS_TZ_POSIX, AMS_TZ_RAWFILE],
    )
    def test_unambiguous(self, tz: str):
        d = create_zdt(2020, 8, 15, 12, 8, 30, tz=tz)
        assert not d.is_repeated()

    @pytest.mark.parametrize(
        "tz",
        ["Europe/Amsterdam", AMS_TZ_POSIX, AMS_TZ_RAWFILE],
    )
    def test_repeated_time(self, tz: str):
        d = create_zdt(
            2023,
            10,
            29,
            2,
            15,
            30,
            tz=tz,
            disambiguation="earlier",
        )
        assert d.is_repeated()

        d2 = d.replace(disambiguation="later")
        assert d2.is_repeated()

    @pytest.mark.parametrize(
        "tz",
        ["Europe/Amsterdam", AMS_TZ_POSIX, AMS_TZ_RAWFILE],
    )
    def test_skipped_time(self, tz: str):
        d = create_zdt(2023, 3, 26, 2, 15, 30, tz=tz)
        # skipped local times are shifted into unambiguous ones
        assert not d.is_repeated()

        # same for different disambiguation
        d2 = create_zdt(
            2023, 3, 26, 2, 15, 30, tz=tz, disambiguation="earlier"
        )
        assert not d2.is_repeated()


class TestTransitions:
    """``next_transition()`` and ``prev_transition()``."""

    @pytest.mark.parametrize(
        "tz", ["Europe/Amsterdam", AMS_TZ_POSIX, AMS_TZ_RAWFILE]
    )
    @pytest.mark.parametrize(
        "method, local, expect",
        [
            # From summer: the next transition is the fall-back in October
            # 2023, the previous the spring-forward in March. The returned
            # instant is when the new offset takes effect, so
            # disambiguation="later" matches the CET offset.
            (
                "next_transition",
                (2023, 8, 15, 12),
                ((2023, 10, 29, 2), "later"),
            ),
            (
                "prev_transition",
                (2023, 8, 15, 12),
                ((2023, 3, 26, 3), "compatible"),
            ),
            # from winter
            (
                "next_transition",
                (2024, 1, 15, 12),
                ((2024, 3, 31, 3), "compatible"),
            ),
            (
                "prev_transition",
                (2024, 1, 15, 12),
                ((2023, 10, 29, 2), "later"),
            ),
        ],
    )
    def test_amsterdam(self, tz, method, local, expect):
        d = create_zdt(*local, tz=tz)
        t = getattr(d, method)()
        assert t is not None
        args, disambiguation = expect
        assert t.strict_eq(
            create_zdt(*args, tz=tz, disambiguation=disambiguation)
        )
        # the same time zone: None for the POSIX and raw-file ones
        assert t.tz_id == d.tz_id

    @pytest.mark.parametrize(
        "d, method, expect",
        [
            (
                ZonedDateTime(2024, 1, 15, tz="Australia/Sydney"),
                "next_transition",
                # DST ends in April (fall-back)
                ZonedDateTime(
                    2024,
                    4,
                    7,
                    2,
                    tz="Australia/Sydney",
                    disambiguation="later",
                ),
            ),
            (
                ZonedDateTime(2024, 1, 15, tz="Australia/Sydney"),
                "prev_transition",
                # DST started in October 2023 (spring-forward)
                ZonedDateTime(2023, 10, 1, 3, tz="Australia/Sydney"),
            ),
            # At the exact moment of spring-forward in New York: the
            # current transition is skipped
            (
                ZonedDateTime(2024, 3, 10, 3, tz="America/New_York"),
                "next_transition",
                ZonedDateTime(
                    2024,
                    11,
                    3,
                    1,
                    tz="America/New_York",
                    disambiguation="later",
                ),
            ),
            (
                ZonedDateTime(2024, 3, 10, 3, tz="America/New_York"),
                "prev_transition",
                ZonedDateTime(
                    2023,
                    11,
                    5,
                    1,
                    tz="America/New_York",
                    disambiguation="later",
                ),
            ),
            # No transitions at all
            (
                create_zdt(2024, 6, 15, 12, tz="Etc/UTC"),
                "next_transition",
                None,
            ),
            (
                create_zdt(2024, 6, 15, 12, tz="Etc/UTC"),
                "prev_transition",
                None,
            ),
            (
                create_zdt(2024, 6, 15, 12, tz="Etc/GMT+2"),
                "next_transition",
                None,
            ),
            (
                create_zdt(2024, 6, 15, 12, tz="Etc/GMT+2"),
                "prev_transition",
                None,
            ),
            # no DST in modern times
            (
                create_zdt(2024, 6, 15, 12, tz="Asia/Kolkata"),
                "next_transition",
                None,
            ),
            # Zones whose very first recorded transition is directly INTO a
            # DST period: nothing precedes it, and the initial period has
            # no DST. Iqaluit: 1942-08-01 00:00:00 UTC -> -04:00 (EWT).
            pytest.param(
                ZonedDateTime(1940, 1, 1, tz="America/Iqaluit"),
                "next_transition",
                ZonedDateTime(
                    1942,
                    7,
                    31,
                    20,
                    tz="America/Iqaluit",
                    disambiguation="later",
                ),
                marks=_NEEDS_TZDATA,
            ),
            pytest.param(
                ZonedDateTime(1940, 1, 1, tz="America/Iqaluit"),
                "prev_transition",
                None,
                marks=_NEEDS_TZDATA,
            ),
            pytest.param(
                ZonedDateTime(1943, 1, 1, tz="America/Iqaluit"),
                "prev_transition",
                ZonedDateTime(
                    1942,
                    7,
                    31,
                    20,
                    tz="America/Iqaluit",
                    disambiguation="later",
                ),
                marks=_NEEDS_TZDATA,
            ),
            # Palmer: 1965-01-01 00:00:00 UTC -> -03:00 (DST), a fall-back
            # in which local 21:00 is repeated
            pytest.param(
                ZonedDateTime(1963, 1, 1, tz="Antarctica/Palmer"),
                "next_transition",
                ZonedDateTime(
                    1964,
                    12,
                    31,
                    21,
                    tz="Antarctica/Palmer",
                    disambiguation="later",
                ),
                marks=_NEEDS_TZDATA,
            ),
            pytest.param(
                ZonedDateTime(1965, 2, 1, tz="Antarctica/Palmer"),
                "prev_transition",
                ZonedDateTime(
                    1964,
                    12,
                    31,
                    21,
                    tz="Antarctica/Palmer",
                    disambiguation="later",
                ),
                marks=_NEEDS_TZDATA,
            ),
        ],
    )
    def test_examples(self, d, method, expect):
        t = getattr(d, method)()
        if expect is None:
            assert t is None
        else:
            assert isinstance(t, ZonedDateTime)
            assert t.strict_eq(expect)
            assert t.tz_id == d.tz_id
            # transitions are always on second boundaries
            assert t.nanosecond == 0

    @pytest.mark.parametrize("tz", [AMS_TZ_POSIX, AMS_TZ_RAWFILE])
    @pytest.mark.parametrize(
        "method, local",
        [
            ("next_transition", (2050, 12, 1)),
            ("prev_transition", (2051, 4, 1)),
        ],
    )
    def test_crosses_into_the_posix_tz_string(self, tz, method, local):
        # After the last explicitly recorded transition, the POSIX TZ string
        # takes over; both directions cross that boundary seamlessly. The
        # last Sunday of March 2051: 2051-03-26 01:00:00 UTC springs
        # forward to 03:00:00+02:00.
        t = getattr(create_zdt(*local, tz=tz), method)()
        assert t is not None
        assert t.strict_eq(create_zdt(2051, 3, 26, 3, tz=tz))

    @pytest.mark.parametrize(
        "tz", ["Europe/Amsterdam", AMS_TZ_POSIX, AMS_TZ_RAWFILE]
    )
    @pytest.mark.parametrize(
        "method, month", [("next_transition", 10), ("prev_transition", 3)]
    )
    def test_far_future_posix(self, tz, method, month):
        t = getattr(create_zdt(2050, 6, 15, 12, tz=tz), method)()
        assert t is not None
        assert t.year == 2050
        assert t.month == month  # fall-back, or spring-forward

    @pytest.mark.parametrize(
        "method, local, first, second",
        [
            (
                "next_transition",
                (2024, 1, 1),
                ZonedDateTime(2024, 3, 10, 3, tz="America/New_York"),
                ZonedDateTime(
                    2024,
                    11,
                    3,
                    1,
                    tz="America/New_York",
                    disambiguation="later",
                ),
            ),
            (
                "prev_transition",
                (2024, 12, 1),
                ZonedDateTime(
                    2024,
                    11,
                    3,
                    1,
                    tz="America/New_York",
                    disambiguation="later",
                ),
                ZonedDateTime(2024, 3, 10, 3, tz="America/New_York"),
            ),
        ],
    )
    def test_chain_nyc(self, method, local, first, second):
        d = ZonedDateTime(*local, tz="America/New_York")
        t1 = getattr(d, method)()
        assert t1 is not None
        t2 = getattr(t1, method)()
        assert t2 is not None
        assert t1.strict_eq(first)
        assert t2.strict_eq(second)

    @pytest.mark.parametrize(
        "method, local, nanosecond",
        [
            ("next_transition", (2024, 1, 1), 123_456),
            ("prev_transition", (2024, 12, 1), 999_999),
        ],
    )
    def test_nanosecond_is_zero(self, method, local, nanosecond):
        # Transitions are always on second boundaries
        d = ZonedDateTime(*local, nanosecond=nanosecond, tz="America/New_York")
        t = getattr(d, method)()
        assert t is not None
        assert t.nanosecond == 0

    @pytest.mark.parametrize(
        "method, local, required",
        [
            # Year 9999 may or may not have a transition depending on the
            # POSIX rule year limits; year 1 may have none before it
            ("next_transition", (9999, 12, 1), False),
            ("next_transition", (1, 1, 1), True),
            ("prev_transition", (9999, 12, 1), True),
            ("prev_transition", (1, 1, 1), False),
        ],
    )
    def test_near_range_edges(self, method, local, required):
        # must not crash
        t = getattr(ZonedDateTime(*local, tz="America/New_York"), method)()
        if required:
            assert t is not None
        if t is not None:
            assert isinstance(t, ZonedDateTime)

    # The second year is past the recorded transitions
    @pytest.mark.parametrize("year, day", [(2023, 26), (2090, 26)])
    def test_less_than_a_second_after_a_transition(self, year, day):
        t = ZonedDateTime(year, 3, day, 3, tz="Europe/Amsterdam")
        d = t.add(nanoseconds=1)
        prev = d.prev_transition()
        assert prev is not None and prev.strict_eq(t)
        assert prev.next_transition() == d.next_transition()
        assert t.prev_transition() != t

    def test_next_same_offset_london_1968(self):
        # British Standard Time: the offset stays +01:00, but the rules
        # change from summer time to standard time, so it is a transition
        d = ZonedDateTime(1968, 6, 1, tz="Europe/London")
        t = d.next_transition()
        assert t is not None
        assert t.strict_eq(ZonedDateTime(1968, 10, 27, tz="Europe/London"))
        assert t.offset == d.offset == hours(1)
        assert t.dst_offset() == TimeDelta.ZERO
        assert t.tz_abbrev() == "BST"
        before = t.subtract(nanoseconds=1)
        assert before.dst_offset() == hours(1)
        assert before.tz_abbrev() == "BST"

    def test_prev_same_offset_london_1968(self):
        # the same-offset transition next_transition() finds from June 1968
        d = ZonedDateTime(1969, 6, 1, tz="Europe/London")
        t = d.prev_transition()
        assert t is not None
        assert t.strict_eq(ZonedDateTime(1968, 10, 27, tz="Europe/London"))
        assert t.offset == hours(1)
        assert t.dst_offset() == TimeDelta.ZERO
        assert t.tz_abbrev() == "BST"

    def test_next_standard_time_and_dst_change_together_argentina_1999(self):
        # Argentina moved standard time from -03:00 to -04:00 and began DST
        # at the same moment, so the offset stays -03:00 while the DST
        # offset changes
        tz = "America/Argentina/Buenos_Aires"
        t = ZonedDateTime(1999, 9, 1, tz=tz).next_transition()
        assert t is not None
        assert t.strict_eq(ZonedDateTime(1999, 10, 3, tz=tz))
        assert t.offset == hours(-3)
        assert t.dst_offset() == hours(1)
        assert t.subtract(nanoseconds=1).dst_offset() == TimeDelta.ZERO

    def test_prev_standard_time_and_dst_change_together_argentina_2000(self):
        # DST ended and standard time moved back to -03:00 at the same
        # moment, so the offset stays -03:00 while the DST offset changes
        tz = "America/Argentina/Buenos_Aires"
        t = ZonedDateTime(2000, 6, 1, tz=tz).prev_transition()
        assert t is not None
        assert t.strict_eq(ZonedDateTime(2000, 3, 3, tz=tz))
        assert t.offset == hours(-3)
        assert t.dst_offset() == TimeDelta.ZERO
        assert t.subtract(nanoseconds=1).dst_offset() == hours(1)

    def test_abbreviation_only_anchorage_1983(self):
        # Alaska renamed its zones on 1983-11-30: YST became AKST, the
        # offset and DST offset unchanged
        tz = "America/Anchorage"
        t = ZonedDateTime(1983, 11, 1, tz=tz).next_transition()
        assert t is not None
        assert t.strict_eq(ZonedDateTime(1983, 11, 30, tz=tz))
        assert t.tz_abbrev() == "AKST"
        before = t.subtract(nanoseconds=1)
        assert before.tz_abbrev() == "YST"
        assert before.offset == t.offset == hours(-9)
        assert before.dst_offset() == t.dst_offset() == TimeDelta.ZERO

    def test_record_that_changes_nothing_is_skipped_tbilisi_1997(self):
        # The database repeats the 1996 type at 1997-03-30, which changes
        # neither the offset, the DST offset, nor the abbreviation
        tz = "Asia/Tbilisi"
        t = ZonedDateTime(1997, 3, 29, tz=tz).next_transition()
        assert t is not None
        assert t.strict_eq(
            ZonedDateTime(1997, 10, 25, 23, tz=tz, disambiguation="later")
        )
        p = ZonedDateTime(1997, 4, 1, tz=tz).prev_transition()
        assert p is not None
        assert p.strict_eq(ZonedDateTime(1996, 3, 31, 1, tz=tz))

    def test_prev_kolkata_historical(self):
        # Asia/Kolkata has no transitions in modern times
        # but has historical transitions
        d = create_zdt(2024, 6, 15, 12, tz="Asia/Kolkata")
        t = d.prev_transition()
        # There are historical transitions, so it should return something
        assert t is not None
        assert t.year < 2024  # historical


# Local times to compare against the standard library's ``dst()`` and
# ``tzname()``: around the transitions of each zone, and past the last
# recorded transition, where the POSIX TZ string takes over.
_ZONEINFO_CASES = [
    # America/New_York: standard US DST. Second Sunday of March: 2:00 AM
    # springs to 3:00 AM; first Sunday of November: 2:00 AM falls back to
    # 1:00 AM.
    ("America/New_York", (2020, 7, 15, 12), 0),
    ("America/New_York", (2020, 1, 15, 12), 0),
    ("America/New_York", (2020, 3, 8, 1, 30), 0),
    ("America/New_York", (2020, 3, 8, 3, 30), 0),
    ("America/New_York", (2020, 11, 1, 1, 30), 0),
    ("America/New_York", (2020, 11, 1, 1, 30), 1),
    ("America/New_York", (2100, 7, 15, 12), 0),
    ("America/New_York", (2100, 1, 15, 12), 0),
    ("UTC", (2020, 7, 15, 12), 0),
    ("Asia/Tokyo", (2020, 7, 15, 12), 0),
    ("Asia/Tokyo", (2020, 1, 15, 12), 0),
    ("Asia/Tokyo", (2100, 7, 15, 12), 0),
    *(
        pytest.param(*c, marks=_NEEDS_TZDATA)
        for c in [
            # Europe/Dublin: "negative DST" (standard=IST UTC+1, winter=GMT
            # UTC+0 isdst=1). Spring-forward on the last Sunday of March,
            # fall-back on the last Sunday of October.
            ("Europe/Dublin", (2020, 7, 15, 12), 0),
            ("Europe/Dublin", (2020, 1, 15, 12), 0),
            ("Europe/Dublin", (2020, 3, 29, 0, 30), 0),
            ("Europe/Dublin", (2020, 3, 29, 2, 30), 0),
            ("Europe/Dublin", (2020, 10, 25, 1, 30), 0),
            ("Europe/Dublin", (2020, 10, 25, 1, 30), 1),
            ("Europe/Dublin", (2100, 7, 15, 12), 0),
            ("Europe/Dublin", (2100, 1, 15, 12), 0),
            # Australia/Sydney: southern hemisphere DST (summer in January).
            # DST starts the first Sunday of October, ends the first Sunday
            # of April.
            ("Australia/Sydney", (2020, 1, 15, 12), 0),
            ("Australia/Sydney", (2020, 7, 15, 12), 0),
            ("Australia/Sydney", (2020, 10, 4, 1, 30), 0),
            ("Australia/Sydney", (2020, 10, 4, 3, 30), 0),
            ("Australia/Sydney", (2020, 4, 5, 2, 30), 0),
            ("Australia/Sydney", (2020, 4, 5, 2, 30), 1),
            ("Australia/Sydney", (2100, 1, 15, 12), 0),
            # Pacific/Honolulu: no DST ever
            ("Pacific/Honolulu", (2020, 7, 15, 12), 0),
            ("Pacific/Honolulu", (2020, 1, 15, 12), 0),
            ("Pacific/Honolulu", (2100, 6, 15, 12), 0),
            # Zones whose very first recorded transition is INTO a DST
            # state: the initial period has no DST. Iqaluit was UTC+0, then
            # EWT (DST = +1h vs EST), then back to standard time.
            ("America/Iqaluit", (1940, 1, 1, 12), 0),
            ("America/Iqaluit", (1942, 9, 1, 12), 0),
            ("America/Iqaluit", (1946, 1, 1, 12), 0),
            # Palmer was UTC+0 until 1965-01-01, then DST (+1h vs -04)
            ("Antarctica/Palmer", (1963, 6, 15, 12), 0),
            ("Antarctica/Palmer", (1965, 2, 15, 12), 0),
        ]
    ),
    *(
        pytest.param(*c, marks=_NEEDS_CASABLANCA)
        for c in [
            # Africa/Casablanca: complex DST schedule
            ("Africa/Casablanca", (2019, 7, 15, 12), 0),
            ("Africa/Casablanca", (2019, 1, 15, 12), 0),
            ("Africa/Casablanca", (2100, 7, 15, 12), 0),
        ]
    ),
]


class TestDstOffsetAndTzAbbrev:
    @pytest.mark.parametrize("tz, local, fold", _ZONEINFO_CASES, ids=str)
    def test_matches_zoneinfo(self, tz, local, fold):
        d = ZonedDateTime(
            *local, tz=tz, disambiguation="later" if fold else "earlier"
        )
        py_dt = py_datetime(*local).replace(fold=fold, tzinfo=ZoneInfo(tz))
        assert d.dst_offset() == TimeDelta(
            py_dt.dst()  # type: ignore[arg-type]
        )
        assert d.tz_abbrev() == py_dt.tzname()

    @pytest.mark.parametrize(
        "tz", ["Europe/Amsterdam", AMS_TZ_POSIX, AMS_TZ_RAWFILE]
    )
    @pytest.mark.parametrize(
        "local, disambiguation, dst_offset, abbrev",
        [
            ((2020, 8, 15, 12), "compatible", hours(1), "CEST"),
            ((2020, 1, 15, 12), "compatible", TimeDelta.ZERO, "CET"),
            ((2023, 10, 29, 2, 30), "earlier", hours(1), "CEST"),
            ((2023, 10, 29, 2, 30), "later", TimeDelta.ZERO, "CET"),
            # POSIX TZ string fallback for dates beyond transition data
            ((2100, 7, 15, 12), "compatible", hours(1), "CEST"),
            ((2100, 1, 15, 12), "compatible", TimeDelta.ZERO, "CET"),
        ],
    )
    def test_amsterdam(self, tz, local, disambiguation, dst_offset, abbrev):
        d = create_zdt(*local, tz=tz, disambiguation=disambiguation)
        assert d.dst_offset() == dst_offset
        assert d.tz_abbrev() == abbrev

    @pytest.mark.parametrize(
        "d, dst_offset, abbrev",
        [
            (
                ZonedDateTime(2020, 8, 15, tz="Etc/GMT+3"),
                TimeDelta.ZERO,
                "-03",
            ),
            (ZonedDateTime(2020, 8, 15, 12, tz="UTC"), TimeDelta.ZERO, "UTC"),
            (ZonedDateTime(2100, 7, 15, 12, tz="UTC"), TimeDelta.ZERO, "UTC"),
            (
                ZonedDateTime(2020, 8, 15, 12, tz="Asia/Tokyo"),
                TimeDelta.ZERO,
                "JST",
            ),
            (
                ZonedDateTime(2020, 1, 15, 12, tz="Asia/Tokyo"),
                TimeDelta.ZERO,
                "JST",
            ),
            (
                ZonedDateTime(2100, 7, 15, 12, tz="Asia/Tokyo"),
                TimeDelta.ZERO,
                "JST",
            ),
            (
                ZonedDateTime(2020, 8, 15, 12, tz="America/New_York"),
                hours(1),
                "EDT",
            ),
            (
                ZonedDateTime(2020, 1, 15, 12, tz="America/New_York"),
                TimeDelta.ZERO,
                "EST",
            ),
            *(
                pytest.param(
                    ZonedDateTime(*local, tz="Pacific/Honolulu"),
                    TimeDelta.ZERO,
                    "HST",
                    marks=_NEEDS_TZDATA,
                )
                for local in [
                    (2020, 7, 15, 12),
                    (2020, 1, 15, 12),
                    (2100, 6, 15, 12),
                ]
            ),
        ],
    )
    def test_examples(self, d, dst_offset, abbrev):
        assert d.dst_offset() == dst_offset
        assert d.tz_abbrev() == abbrev

    def test_standard_time_and_dst_changed_together(self):
        # Argentina 1999-2000: standard time -04:00 with a one-hour saving,
        # so the offset equals the previous standard offset
        d = ZonedDateTime(1999, 12, 1, tz="America/Argentina/Buenos_Aires")
        assert d.offset == hours(-3)
        assert d.dst_offset() == hours(1)

    def test_returns_str(self):
        d = create_zdt(2020, 8, 15, 12, tz="Europe/Amsterdam")
        assert type(d.tz_abbrev()) is str


class TestDayLength:
    @pytest.mark.parametrize(
        "d, expect",
        [
            # no special day
            (
                ZonedDateTime(2020, 8, 15, 12, 8, 30, tz="Europe/Amsterdam"),
                hours(24),
            ),
            (ZonedDateTime(1832, 12, 15, 12, 1, 30, tz="UTC"), hours(24)),
            # Longer day
            (
                ZonedDateTime(2023, 10, 29, 12, 8, 30, tz="Europe/Amsterdam"),
                hours(25),
            ),
            (
                create_zdt(2023, 10, 29, 12, 8, 30, tz=AMS_TZ_POSIX),
                hours(25),
            ),
            (ZonedDateTime(2023, 10, 29, tz="Europe/Amsterdam"), hours(25)),
            (
                ZonedDateTime(2023, 10, 30, tz="Europe/Amsterdam").subtract(
                    nanoseconds=1
                ),
                hours(25),
            ),
            # Shorter day
            (
                ZonedDateTime(2023, 3, 26, 12, 8, 30, tz="Europe/Amsterdam"),
                hours(23),
            ),
            (ZonedDateTime(2023, 3, 26, tz="Europe/Amsterdam"), hours(23)),
            (
                ZonedDateTime(2023, 3, 27, tz="Europe/Amsterdam").subtract(
                    nanoseconds=1
                ),
                hours(23),
            ),
            # non-hour DST change
            (
                ZonedDateTime(2024, 10, 6, 1, tz="Australia/Lord_Howe"),
                hours(23.5),
            ),
            (
                ZonedDateTime(2024, 4, 7, 1, tz="Australia/Lord_Howe"),
                hours(24.5),
            ),
            # Non-regular transition
            (
                ZonedDateTime(1894, 6, 1, 1, tz="Europe/Zurich"),
                TimeDelta(hours=24, minutes=-30, seconds=-14),
            ),
            # DST starts at midnight
            (ZonedDateTime(2016, 2, 20, tz="America/Sao_Paulo"), hours(25)),
            (ZonedDateTime(2016, 2, 21, tz="America/Sao_Paulo"), hours(24)),
            (
                ZonedDateTime(
                    2016,
                    10,
                    16,
                    tz="America/Sao_Paulo",
                    disambiguation="compatible",
                ),
                hours(23),
            ),
            (ZonedDateTime(2016, 10, 17, tz="America/Sao_Paulo"), hours(24)),
            # Samoa skipped a day
            (ZonedDateTime(2011, 12, 31, 21, tz="Pacific/Apia"), hours(24)),
            (ZonedDateTime(2011, 12, 29, 21, tz="Pacific/Apia"), hours(24)),
            # A day that starts twice
            (
                ZonedDateTime(
                    2016,
                    2,
                    20,
                    23,
                    45,
                    disambiguation="later",
                    tz="America/Sao_Paulo",
                ),
                hours(25),
            ),
            (
                ZonedDateTime(
                    2016,
                    2,
                    20,
                    23,
                    45,
                    disambiguation="earlier",
                    tz="America/Sao_Paulo",
                ),
                hours(25),
            ),
        ],
    )
    def test_typical(self, d: ZonedDateTime, expect: TimeDelta):
        assert d.day_length() == expect

    def test_extreme_bounds(self):
        # Negative UTC offsets at lower bound are fine
        d_min_neg = ZonedDateTime(1, 1, 1, 2, tz="America/New_York")
        assert d_min_neg.day_length() == hours(24)

        # Positive UTC offsets at lower bound are NOT fine
        d_min_pos = ZonedDateTime(1, 1, 1, 12, tz="Asia/Tokyo")
        with pytest.raises(
            ValueError, match="^value or calculation out of range$"
        ):
            d_min_pos.day_length()

        # upper bound is NOT fine
        d_max_pos = ZonedDateTime(9999, 12, 31, 4, tz="Asia/Tokyo")
        with pytest.raises(
            ValueError, match="^value or calculation out of range$"
        ):
            d_max_pos.day_length()

        d_max_neg = ZonedDateTime(9999, 12, 31, 12, tz="America/New_York")
        with pytest.raises(
            ValueError, match="^value or calculation out of range$"
        ):
            d_max_neg.day_length()

    @pytest.mark.parametrize(
        "d",
        [
            ZonedDateTime(2010, 11, 6, 12, tz="America/Goose_Bay"),
            ZonedDateTime(2010, 11, 7, 12, tz="America/Goose_Bay"),
            ZonedDateTime(2024, 4, 7, 1, tz="Australia/Lord_Howe"),
            ZonedDateTime(2024, 10, 6, 1, tz="Australia/Lord_Howe"),
            ZonedDateTime(
                2023,
                10,
                29,
                2,
                30,
                tz="Europe/Amsterdam",
                disambiguation="later",
            ),
        ],
    )
    def test_is_the_difference_of_consecutive_day_starts(self, d):
        next_start = d.add(hours=30).start_of("day")
        assert d.day_length() == next_start - d.start_of("day")


class TestDayBoundariesAroundMidnight:
    """A transition can straddle midnight, which puts the day boundary itself
    in a gap or a fold."""

    # Toronto jumped from 23:30 on 1919-03-30 to 00:30 on 1919-03-31, so
    # midnight of Mar 31 lies strictly inside the gap.
    TORONTO = "America/Toronto"
    MAR_31_START = ZonedDateTime.parse_iso(
        "1919-03-31T00:30:00-04:00[America/Toronto]"
    )

    MAR_30 = ZonedDateTime.parse_iso(
        "1919-03-30T12:00:00-05:00[America/Toronto]"
    )
    MAR_31 = ZonedDateTime.parse_iso(
        "1919-03-31T12:00:00-04:00[America/Toronto]"
    )

    def test_start_of_day_snaps_to_gap_edge(self):
        assert self.MAR_31.start_of("day").strict_eq(self.MAR_31_START)

    def test_start_of_day_never_follows_its_value(self):
        d = self.MAR_31_START
        end = ZonedDateTime(1919, 4, 1, tz=self.TORONTO)
        while d < end:
            assert d.start_of("day") <= d
            d += minutes(7)

    def test_end_of_day_is_the_nanosecond_before(self):
        # The instant before the day starts still reads as Mar 30 23:29:59...,
        # because the local times up to Mar 31 00:30 never happened.
        assert self.MAR_30.end_of("day").strict_eq(
            self.MAR_31_START.subtract(nanoseconds=1)
        )

    @pytest.mark.parametrize("d", [MAR_30, MAR_31])
    def test_day_length_spans_the_gap(self, d):
        assert d.day_length() == hours(23) + minutes(30)

    def test_day_length_equals_the_gap_between_day_starts(self):
        assert self.MAR_30.day_length() == self.MAR_31.start_of(
            "day"
        ) - self.MAR_30.start_of("day")

    def test_round_day_snaps_to_gap_edge(self):
        assert (
            ZonedDateTime.parse_iso(
                "1919-03-30T23:00:00-05:00[America/Toronto]"
            )
            .round("day")
            .strict_eq(self.MAR_31_START)
        )

    # Goose Bay fell back from 00:01 on 2010-11-07 to 23:01 on 2010-11-06, so
    # midnight of Nov 7 is repeated.
    GOOSE_BAY = "America/Goose_Bay"

    def test_repeated_midnight_takes_the_earlier_occurrence(self):
        d = ZonedDateTime(2010, 11, 7, 12, tz=self.GOOSE_BAY)
        assert d.start_of("day").strict_eq(
            ZonedDateTime(
                2010, 11, 7, tz=self.GOOSE_BAY, disambiguation="earlier"
            )
        )

    @pytest.mark.parametrize("day, expect", [(6, hours(24)), (7, hours(25))])
    def test_day_length_around_a_repeated_midnight(self, day, expect):
        assert (
            ZonedDateTime(2010, 11, day, 12, tz=self.GOOSE_BAY).day_length()
            == expect
        )

    # A day is chosen by the instant, not by the local date: the second pass
    # of the evening lies in the day that has already started (ADR 0003).
    # Newfoundland fell back from 00:01 on 1987-10-25, Guam on 1969-01-26.
    @pytest.mark.parametrize(
        "second_pass, day_start, next_day_start, length",
        [
            (
                "1987-10-24T23:01:00-03:30[America/St_Johns]",
                "1987-10-25T00:00:00-02:30[America/St_Johns]",
                "1987-10-26T00:00:00-03:30[America/St_Johns]",
                hours(25),
            ),
            (
                "2010-11-06T23:30:00-04:00[America/Goose_Bay]",
                "2010-11-07T00:00:00-03:00[America/Goose_Bay]",
                "2010-11-08T00:00:00-04:00[America/Goose_Bay]",
                hours(25),
            ),
            (
                "1969-01-25T23:59:59+10:00[Pacific/Guam]",
                "1969-01-26T00:00:00+11:00[Pacific/Guam]",
                "1969-01-27T00:00:00+10:00[Pacific/Guam]",
                hours(25),
            ),
        ],
    )
    def test_second_pass_lies_in_the_day_that_already_started(
        self, second_pass, day_start, next_day_start, length
    ):
        d = ZonedDateTime.parse_iso(second_pass)
        start = ZonedDateTime.parse_iso(day_start)
        next_start = ZonedDateTime.parse_iso(next_day_start)
        assert d.start_of("day").strict_eq(start)
        assert d.end_of("day").strict_eq(next_start.subtract(nanoseconds=1))
        assert d.day_length() == length
        assert d.round("day", mode="floor").strict_eq(start)
        assert d.round("day", mode="ceil").strict_eq(next_start)
        assert d.round("day").strict_eq(start)

    @pytest.mark.parametrize("unit", ["day", "month", "year"])
    def test_second_pass_lies_in_the_year_that_already_started(self, unit):
        # Phoenix fell back from 00:01 on 1944-01-01
        d = ZonedDateTime.parse_iso(
            "1943-12-31T23:30:00-07:00[America/Phoenix]"
        )
        new_year = ZonedDateTime.parse_iso(
            "1944-01-01T00:00:00-06:00[America/Phoenix]"
        )
        assert d.start_of(unit).strict_eq(new_year)
        assert d.start_of(unit) <= d <= d.end_of(unit)

    @pytest.mark.parametrize(
        "first_midnight",
        [
            "1987-10-25T00:00:00-02:30[America/St_Johns]",
            "2010-11-07T00:00:00-03:00[America/Goose_Bay]",
            "1969-01-26T00:00:00+11:00[Pacific/Guam]",
        ],
    )
    def test_boundaries_enclose_both_passes(self, first_midnight):
        d = ZonedDateTime.parse_iso(first_midnight).subtract(hours=2)
        for _ in range(60):
            for u in ("day", "week_mon", "month", "year"):
                assert d.start_of(u) <= d <= d.end_of(u)
            assert d.round("day", mode="floor") <= d
            assert d <= d.round("day", mode="ceil")
            assert d.round("day", mode="floor").strict_eq(d.start_of("day"))
            d += minutes(4)

    # These shapes never depended on how the day is chosen
    @pytest.mark.parametrize(
        "d, start, ceil, length",
        [
            # a skipped midnight: the day starts at 01:00
            (
                "2017-10-15T01:30:00-02:00[America/Sao_Paulo]",
                "2017-10-15T01:00:00-02:00[America/Sao_Paulo]",
                "2017-10-16T00:00:00-02:00[America/Sao_Paulo]",
                hours(23),
            ),
            (
                "2017-10-14T23:30:00-03:00[America/Sao_Paulo]",
                "2017-10-14T00:00:00-03:00[America/Sao_Paulo]",
                "2017-10-15T01:00:00-02:00[America/Sao_Paulo]",
                hours(24),
            ),
            # a fold that ends at midnight
            (
                "2018-02-17T23:30:00-03:00[America/Sao_Paulo]",
                "2018-02-17T00:00:00-02:00[America/Sao_Paulo]",
                "2018-02-18T00:00:00-03:00[America/Sao_Paulo]",
                hours(25),
            ),
            # a skipped day
            (
                "2011-12-29T20:00:00-10:00[Pacific/Apia]",
                "2011-12-29T00:00:00-10:00[Pacific/Apia]",
                "2011-12-31T00:00:00+14:00[Pacific/Apia]",
                hours(24),
            ),
        ],
    )
    def test_other_midnight_transitions(self, d, start, ceil, length):
        d = ZonedDateTime.parse_iso(d)
        assert d.start_of("day").strict_eq(ZonedDateTime.parse_iso(start))
        assert d.round("day", mode="ceil").strict_eq(
            ZonedDateTime.parse_iso(ceil)
        )
        assert d.day_length() == length


class TestPickle:
    def test_repeated_time(self):
        d1 = ZonedDateTime(
            2023,
            10,
            29,
            2,
            15,
            30,
            tz="Europe/Amsterdam",
            disambiguation="earlier",
        )
        d2 = d1.replace(disambiguation="later")
        assert pickle.loads(pickle.dumps(d1)).strict_eq(d1)
        assert pickle.loads(pickle.dumps(d2)).strict_eq(d2)

    @pytest.mark.parametrize("tz", [AMS_TZ_POSIX, AMS_TZ_RAWFILE])
    def test_no_tzid(self, tz: str):
        d = create_zdt(2023, 12, 3, 9, 15, tz=tz)
        with pytest.raises(
            ValueError,
            match="cannot pickle ZonedDateTime without a time zone ID",
        ):
            pickle.dumps(d)


# --- Fixtures for TestImplicitDisambiguationWarning ---
_AMS = "Europe/Amsterdam"
# A repeated local time, so its offset settles which occurrence is meant
_IN_REPEATED = ZonedDateTime(
    2023, 10, 29, 2, 30, tz=_AMS, disambiguation="earlier"
)
# Amsterdam was at UTC+0 back then: an offset matching neither occurrence
# of the repeated local time
_ANCIENT = ZonedDateTime(1900, 6, 1, 2, 30, tz=_AMS)
_BEFORE_SKIPPED = ZonedDateTime(2023, 3, 25, 2, 30, tz=_AMS)
_AFTER_SKIPPED = ZonedDateTime(2023, 3, 27, 2, 30, tz=_AMS)
_BEFORE_REPEATED = ZonedDateTime(2023, 10, 28, 2, 30, tz=_AMS)
_REPEATED_DAY_NOON = ZonedDateTime(2023, 10, 29, 12, tz=_AMS)
_SKIPPED_DAY_NOON = ZonedDateTime(2023, 3, 26, 12, tz=_AMS)
_REPEATED_DATE = Date(2023, 10, 29)
_SKIPPED_DATE = Date(2023, 3, 26)


class TestImplicitDisambiguationWarning:
    """The cross-method contract: an omitted ``disambiguation`` warns exactly
    when neither an explicit policy nor the previous offset settles the matter.
    """

    @pytest.mark.parametrize(
        "func",
        [
            # A skipped local time can never be resolved by preserving the
            # offset
            lambda: _BEFORE_SKIPPED.add(days=1),
            lambda: _AFTER_SKIPPED.subtract(days=1),
            lambda: _BEFORE_SKIPPED.replace_date(_SKIPPED_DATE),
            lambda: _SKIPPED_DAY_NOON.replace_time(Time(2, 30)),
            lambda: _BEFORE_SKIPPED.replace(day=26),
            # A repeated local time whose offset matches neither occurrence
            lambda: _ANCIENT.replace_date(_REPEATED_DATE),
            lambda: _ANCIENT.replace(year=2023, month=10, day=29),
            # Changing tz discards the offset entirely
            lambda: _IN_REPEATED.replace(tz="Europe/Paris"),
        ],
    )
    def test_warns(self, func):
        with warns_here(ImplicitDisambiguationWarning) as caught:
            func()
        assert len(caught) == 1

    @pytest.mark.parametrize(
        "func",
        [
            lambda: _BEFORE_SKIPPED + ItemizedDateDelta(days=1),
            lambda: _BEFORE_SKIPPED + ItemizedDelta(days=1),
            lambda: _AFTER_SKIPPED - ItemizedDateDelta(days=1),
            lambda: _AFTER_SKIPPED - ItemizedDelta(days=1),
            lambda: ItemizedDateDelta(days=1) + _BEFORE_SKIPPED,
            lambda: ItemizedDelta(days=1) + _BEFORE_SKIPPED,
        ],
    )
    def test_operators_warn(self, func):
        # The operators can't take a policy at all, so they always warn
        with warns_here(ImplicitDisambiguationWarning) as caught:
            func()
        assert len(caught) == 1

    @pytest.mark.parametrize(
        "func",
        [
            # The previous offset settles which occurrence of the repeated
            # local time is meant
            lambda: _BEFORE_REPEATED.add(days=1),
            lambda: _BEFORE_REPEATED.replace_date(_REPEATED_DATE),
            lambda: _REPEATED_DAY_NOON.replace_time(Time(2, 30)),
            lambda: _REPEATED_DAY_NOON.replace(hour=2, minute=30),
            # Setting the same tz doesn't count as a tz change
            lambda: _IN_REPEATED.replace(tz=_AMS),
            # An explicit policy never warns
            lambda: _BEFORE_SKIPPED.add(days=1, disambiguation="later"),
            lambda: _BEFORE_SKIPPED.replace_date(
                _SKIPPED_DATE, disambiguation="compatible"
            ),
            lambda: _IN_REPEATED.replace(
                tz="Europe/Paris", disambiguation="compatible"
            ),
            # Unambiguous local times never warn
            lambda: _IN_REPEATED.add(days=2),
            lambda: _IN_REPEATED.replace(hour=12),
            # The offset still settles a repeated local time when shifted by
            # operator
            lambda: _BEFORE_REPEATED + ItemizedDateDelta(days=1),
            lambda: _BEFORE_REPEATED + ItemizedDelta(days=1),
            # Exact-time shifts never resolve a local time
            lambda: _BEFORE_SKIPPED + hours(24),
            lambda: _BEFORE_SKIPPED + ItemizedDelta(hours=24),
            # The boundary methods take no policy (ADR 0003)
            lambda: _IN_REPEATED.start_of("hour"),
            lambda: _IN_REPEATED.end_of("day"),
            lambda: _IN_REPEATED.round("hour"),
            lambda: _IN_REPEATED.day_length(),
        ],
    )
    def test_does_not_warn(self, func):
        with warnings.catch_warnings():
            warnings.simplefilter("error", ImplicitDisambiguationWarning)
            func()
