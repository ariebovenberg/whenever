"""The time zone store: the search path, lookup, caching and the system time zone."""

import os
import pickle
import re
import shutil
from copy import copy, deepcopy
from pathlib import Path
from unittest.mock import patch
from zoneinfo import available_timezones as zoneinfo_available_timezones

import pytest
from whenever import (
    _EXTENSION_LOADED,
    SYSTEM_TZ,
    Instant,
    OffsetDateTime,
    PlainDateTime,
    TimeZoneNotFoundError,
    ZonedDateTime,
    available_timezones,
    clear_tzcache,
    get_tzpath,
    hours,
    reset_system_tz,
    reset_tzpath,
)
from whenever._tz.system import _tzid_from_path, get_tz

from .common import system_tz

try:
    import tzdata  # noqa
except ImportError:
    HAS_TZDATA = False
else:
    HAS_TZDATA = True

TEST_DIR = Path(__file__).parent


INVALID_TZ_IDS = [
    "America/Nowhere",  # unknown
    "/America/New_York",  # slash at the beginning
    "America/New_York/",  # slash at the end
    "America/New\0York",  # null byte
    "America\\New_York",  # backslash
    "../America/New_York/",  # relative path
    "America/New_York/..",  # other dots
    "America//New_York",  # double slash
    "./America/New_York",  # start with dot
    "America/../America/New_York",  # not normalized
    "America/./America/New_York",  # not normalized
    "+VERSION",  # in tz path, but not a tzif file
    "leapseconds",  # in tz path, but not a tzif file
    "Europe",  # a directory
    "__init__.py",  # file in tzdata package
    "",
    ".",
    "/",
    " ",
    "Foo" * 100,  # too long
    # invalid file path characters
    "foo:bar",
    "bla*",
    "*",
    "**",
    ":",
    "&",
    # non-ascii
    "🇨🇦",
    "America/Bogotá",
    # invalid start characters
    "+B",
    "+",
    "-",
    "-foo",
]

# Every entry point that takes a time zone ID resolves it through one
# function, so the same string gets the same rejection everywhere.
TZ_ENTRY_POINTS = [
    pytest.param(
        lambda tz: ZonedDateTime(2020, 8, 15, 5, 12, tz=tz), id="constructor"
    ),
    pytest.param(lambda tz: ZonedDateTime.now(tz), id="now"),
    pytest.param(
        lambda tz: ZonedDateTime(2020, 8, 15, tz="UTC").replace(tz=tz),
        id="replace",
    ),
    pytest.param(
        lambda tz: ZonedDateTime(2020, 8, 15, tz="UTC").to_tz(tz), id="to_tz"
    ),
    pytest.param(
        lambda tz: Instant.from_utc(2020, 8, 15).to_tz(tz), id="Instant.to_tz"
    ),
    pytest.param(
        lambda tz: OffsetDateTime(2020, 8, 15, offset=hours(2)).to_tz(tz),
        id="OffsetDateTime.to_tz",
    ),
    pytest.param(
        lambda tz: PlainDateTime(2020, 8, 15).assume_tz(tz),
        id="PlainDateTime.assume_tz",
    ),
    pytest.param(
        lambda tz: OffsetDateTime(2020, 8, 15, offset=hours(2)).assume_tz(tz),
        id="OffsetDateTime.assume_tz",
    ),
]

# The ISO parser reads the ID out of a string, so a non-ASCII one never
# reaches the lookup: the string fails as text first. The pattern parser
# scans `VV` with its own character class; test_format_parse.py covers it.
TZ_PARSE_ENTRY_POINTS = [
    pytest.param(
        lambda tz: ZonedDateTime.parse_iso(f"2020-08-15T05:12:00+00:00[{tz}]"),
        id="parse_iso",
    ),
    pytest.param(
        lambda tz: ZonedDateTime(f"2020-08-15T05:12:00+00:00[{tz}]"),
        id="constructor_iso",
    ),
]


class TestTzIdRejection:
    @pytest.mark.parametrize("call", TZ_ENTRY_POINTS)
    @pytest.mark.parametrize("key", INVALID_TZ_IDS)
    def test_not_found(self, call, key: str):
        with pytest.raises(
            TimeZoneNotFoundError,
            match="^" + re.escape(f"time zone ID {key!r} not found") + "$",
        ):
            call(key)

    @pytest.mark.parametrize("call", TZ_PARSE_ENTRY_POINTS)
    @pytest.mark.parametrize("key", [k for k in INVALID_TZ_IDS if k.isascii()])
    def test_not_found_in_parsed_string(self, call, key: str):
        with pytest.raises(
            TimeZoneNotFoundError,
            match="^" + re.escape(f"time zone ID {key!r} not found") + "$",
        ):
            call(key)

    @pytest.mark.parametrize("call", TZ_PARSE_ENTRY_POINTS)
    @pytest.mark.parametrize(
        "key", [k for k in INVALID_TZ_IDS if not k.isascii()]
    )
    def test_non_ascii_in_parsed_string_is_not_a_string_to_parse(
        self, call, key: str
    ):
        with pytest.raises(
            ValueError, match="ASCII|invalid ISO 8601 string"
        ) as exc:
            call(key)
        assert not isinstance(exc.value, TimeZoneNotFoundError)

    @pytest.mark.parametrize("call", TZ_ENTRY_POINTS)
    @pytest.mark.parametrize(
        "bad",
        [3, None, b"UTC", 3.5, ["UTC"], hours(34), type(SYSTEM_TZ)()],  # type: ignore[call-arg]
    )
    def test_non_string(self, call, bad):
        with pytest.raises(
            TypeError, match="^tz must be a string or SYSTEM_TZ$"
        ):
            call(bad)

    def test_str_subclass_is_an_id(self):
        class MyStr(str):
            pass

        assert ZonedDateTime.now(MyStr("Iceland")).tz_id == "Iceland"


class TestTzCache:
    @pytest.mark.order(-3)
    def test_timezone_id_casing(self, tmp_path: Path):
        source = TEST_DIR / "tzif" / "Amsterdam.tzif"
        first_path = tmp_path / "first"
        first_zone = first_path / "Europe" / "Amsterdam"
        first_zone.parent.mkdir(parents=True)
        shutil.copyfile(source, first_zone)
        three_component_zone = (
            first_path / "America" / "Argentina" / "Buenos_Aires"
        )
        three_component_zone.parent.mkdir(parents=True)
        shutil.copyfile(source, three_component_zone)
        for name in ("UTC", "CET", "Iceland"):
            shutil.copyfile(source, first_path / name)
        alias = first_path / "US" / "Eastern"
        alias.parent.mkdir()
        alias.symlink_to(first_zone)

        second_path = tmp_path / "second"
        second_zone = second_path / "Europe" / "AMSTERDAM"
        second_zone.parent.mkdir(parents=True)
        shutil.copyfile(source, second_zone)

        previous = get_tzpath()
        reset_tzpath([first_path])
        clear_tzcache()
        try:
            values = [
                ZonedDateTime(2020, 8, 15, 5, 12, tz=key)
                for key in (
                    "europe/amsterdam",
                    "EURope/AMSTERdam",
                    "Europe/Amsterdam",
                )
            ]
            assert [value.tz_id for value in values] == [
                "Europe/Amsterdam"
            ] * 3
            assert values[0].strict_eq(values[1])
            assert "Europe/Amsterdam" in repr(values[0])
            assert values[0].format_iso().endswith("[Europe/Amsterdam]")
            assert values[1].to_tz("Europe/Amsterdam") is values[1]
            assert (
                ZonedDateTime(
                    2020,
                    8,
                    15,
                    5,
                    12,
                    tz="aMeRiCa/aRgEnTiNa/bUeNoS_aIrEs",
                ).tz_id
                == "America/Argentina/Buenos_Aires"
            )
            for key, expected in (
                ("utc", "UTC"),
                ("cet", "CET"),
                ("ICELAND", "Iceland"),
            ):
                assert (
                    ZonedDateTime(2020, 8, 15, 5, 12, tz=key).tz_id == expected
                )
            assert (
                ZonedDateTime.parse_iso(
                    "2020-08-15T05:12:00+02:00[eurOPE/amSTerdam]"
                ).tz_id
                == "Europe/Amsterdam"
            )
            assert (
                ZonedDateTime.parse(
                    "2020-08-15 05:12+02:00[EUROPE/AMSTERDAM]",
                    pattern="YYYY-MM-DD HH:mmxxx'['VV']'",
                ).tz_id
                == "Europe/Amsterdam"
            )
            assert values[0].to_tz("EURope/AMSTERdam") is values[0]
            assert (
                ZonedDateTime(2020, 8, 15, 5, 12, tz="us/eastern").tz_id
                == "US/Eastern"
            )

            clear_tzcache(only_keys=["europe/amsterdam"])
            assert (
                ZonedDateTime(2020, 8, 15, 5, 12, tz="europe/amsterdam").tz_id
                == "Europe/Amsterdam"
            )

            reset_tzpath([second_path])
            assert (
                ZonedDateTime(2020, 8, 15, 5, 12, tz="europe/amsterdam").tz_id
                == "Europe/Amsterdam"
            )
            clear_tzcache(only_keys=["EUROPE/AMSTERDAM"])
            assert (
                ZonedDateTime(2020, 8, 15, 5, 12, tz="europe/amsterdam").tz_id
                == "Europe/AMSTERDAM"
            )
        finally:
            clear_tzcache()
            reset_tzpath(previous)

    def test_timezone_id_case_collision_does_not_crash(self, tmp_path: Path):
        source = TEST_DIR / "tzif" / "Amsterdam.tzif"
        for name in ("Europe", "europe"):
            zone = tmp_path / name / "Amsterdam"
            try:
                zone.parent.mkdir()
            except FileExistsError:
                pytest.skip("filesystem does not permit case-colliding paths")
            shutil.copyfile(source, zone)

        previous = get_tzpath()
        reset_tzpath([tmp_path])
        clear_tzcache()
        try:
            assert ZonedDateTime(
                2020, 8, 15, 5, 12, tz="Europe/Amsterdam"
            ).tz_id in {"Europe/Amsterdam", "europe/Amsterdam"}
        finally:
            clear_tzcache()
            reset_tzpath(previous)

    @pytest.mark.skipif(_EXTENSION_LOADED, reason="tests the Python loader")
    def test_timezone_id_unreadable_file_is_not_found(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ):
        source = TEST_DIR / "tzif" / "Amsterdam.tzif"
        zone = tmp_path / "Europe" / "Amsterdam"
        zone.parent.mkdir()
        shutil.copyfile(source, zone)

        original_open = open

        def blocked_open(path, *args, **kwargs):
            if path == str(zone):
                raise OSError()
            return original_open(path, *args, **kwargs)

        previous = get_tzpath()
        reset_tzpath([tmp_path])
        clear_tzcache()
        monkeypatch.setattr("builtins.open", blocked_open)
        try:
            with pytest.raises(TimeZoneNotFoundError):
                ZonedDateTime(2020, 8, 15, 5, 12, tz="Europe/Amsterdam")
        finally:
            clear_tzcache()
            reset_tzpath(previous)

    @pytest.mark.skipif(_EXTENSION_LOADED, reason="tests the Python cache")
    def test_timezone_directory_cache(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ):
        from whenever._tz import store

        source = TEST_DIR / "tzif" / "Amsterdam.tzif"
        europe = tmp_path / "Europe"
        europe.mkdir()
        for n in ("Amsterdam", "Paris"):
            shutil.copyfile(source, europe / n)
        (europe / "Bogotá").touch()

        scanned: list[str] = []
        original_scandir = os.scandir

        def counting_scandir(path: str):
            scanned.append(path)
            return original_scandir(path)

        previous = get_tzpath()
        reset_tzpath([tmp_path])
        clear_tzcache()
        monkeypatch.setattr("whenever._tz.store.os.scandir", counting_scandir)
        try:
            assert store.get_tz("europe/amsterdam").key == "Europe/Amsterdam"
            assert scanned == [str(tmp_path), str(europe)]

            assert store.get_tz("EUROPE/PARIS").key == "Europe/Paris"
            assert scanned == [str(tmp_path), str(europe)]

            shutil.copyfile(source, europe / "Brussels")
            assert store.get_tz("europe/brussels").key == "Europe/Brussels"
            assert scanned == [str(tmp_path), str(europe), str(europe)]

            clear_tzcache(only_keys=["Europe/Amsterdam"])
            assert store._tzdir_cache == {}

            for _ in range(2):
                with pytest.raises(TimeZoneNotFoundError):
                    store.get_tz("Europe/Missing")
            assert store._tzdir_cache == {}
            local_scans = [p for p in scanned if p.startswith(str(tmp_path))]
            assert local_scans[-4:] == [
                str(tmp_path),
                str(europe),
                str(tmp_path),
                str(europe),
            ]

            (tmp_path / "Broken").write_bytes(b"not a TZif")
            with pytest.raises(TimeZoneNotFoundError):
                store.get_tz("Broken")
            assert store._tzdir_cache == {}
        finally:
            clear_tzcache()
            reset_tzpath(previous)

    @pytest.mark.skipif(_EXTENSION_LOADED, reason="tests the Python cache")
    def test_timezone_directory_cache_discards_stale_positive(
        self, tmp_path: Path
    ):
        from whenever._tz import store

        source = TEST_DIR / "tzif" / "Amsterdam.tzif"
        europe = tmp_path / "Europe"
        europe.mkdir()
        shutil.copyfile(source, europe / "Amsterdam")

        previous = get_tzpath()
        reset_tzpath([tmp_path])
        clear_tzcache()
        try:
            store.get_tz("Europe/Amsterdam")
            assert len(store._tzdir_cache) == 2

            shutil.rmtree(europe)
            assert (
                store._resolve_path(
                    str(tmp_path),
                    store.NormalizedTzId("europe/amsterdam"),
                )
                is None
            )
            assert store._tzdir_cache == {}
        finally:
            clear_tzcache()
            reset_tzpath(previous)

    @pytest.mark.skipif(_EXTENSION_LOADED, reason="tests the Python cache")
    def test_timezone_id_strong_cache_capacity(self, tmp_path: Path):
        from whenever._tz import store

        source = TEST_DIR / "tzif" / "Amsterdam.tzif"
        for i in range(33):
            shutil.copyfile(source, tmp_path / f"Zone{i}")

        previous = get_tzpath()
        reset_tzpath([tmp_path])
        clear_tzcache()
        try:
            for i in range(33):
                store.get_tz(f"Zone{i}")

            assert list(store._tzcache_lru) == [
                f"zone{i}" for i in range(1, 33)
            ]
            assert store.get_tz("zOnE0").key == "Zone0"
        finally:
            clear_tzcache()
            reset_tzpath(previous)

    # This test is run last, because it modifies the tz cache
    # which can affect other tests (namely those using exact_eq)
    @pytest.mark.order(-1)
    def test_tz_cache_adjustments(self):
        nyc = "America/New_York"
        ams = "Europe/Amsterdam"
        # creating a ZDT puts it in the tz cache
        d = ZonedDateTime(2020, 8, 15, 5, 12, tz=nyc)
        ZonedDateTime(2020, 8, 15, 5, 12, tz=ams)

        assert (
            available_timezones()
            == zoneinfo_available_timezones().difference(["localtime"])
        )

        prev_tzpath = get_tzpath()
        # We now set the TZ path to our test directory
        # (which contains some tzif files)
        reset_tzpath([TEST_DIR / "tzif"])
        assert get_tzpath() == (str(TEST_DIR / "tzif"),)
        try:
            # Available time zones should now be different
            assert (
                available_timezones()
                != zoneinfo_available_timezones().difference(["localtime"])
            )
            # Cached zones remain available after changing TZPATH.
            assert ZonedDateTime(1982, 8, 15, 5, 12, tz=nyc)
            assert ZonedDateTime(1982, 8, 15, 5, 12, tz=ams)
            clear_tzcache(only_keys=[nyc])
            if not HAS_TZDATA:
                with pytest.raises(TimeZoneNotFoundError):
                    ZonedDateTime(1982, 8, 15, 5, 12, tz=nyc)

            assert ZonedDateTime(1982, 8, 15, 5, 12, tz=ams)
            clear_tzcache()
            if not HAS_TZDATA:
                with pytest.raises(TimeZoneNotFoundError):
                    ZonedDateTime(1982, 8, 15, 5, 12, tz=ams)

            # We can still use the old instance without problems
            d.add(hours=24)

            # Ok, let's see if we can find our custom time zones
            d2 = ZonedDateTime(1982, 8, 15, 5, 12, tz="Amsterdam.tzif")
            d3 = ZonedDateTime(1982, 8, 15, 5, 12, tz="Asia/Amman")
        finally:
            # We need to reset the tzpath to the original one
            reset_tzpath()

        assert get_tzpath() == prev_tzpath

        # Available time zones should now be the same again
        assert (
            available_timezones()
            == zoneinfo_available_timezones().difference(["localtime"])
        )

        # The custom time zone remains cached until it is explicitly cleared.
        assert ZonedDateTime(1982, 8, 15, 5, 12, tz="Amsterdam.tzif")
        clear_tzcache()
        with pytest.raises(TimeZoneNotFoundError):
            ZonedDateTime(1982, 8, 15, 5, 12, tz="Amsterdam.tzif")

        # strict equality is impacted
        assert not d2.to_plain().assume_tz("Europe/Amsterdam").strict_eq(d2)
        # Note the "Asia/Amman" file in our tzif directory is purposefully
        # an older version, so they shouldn't compare equal
        assert not d3.to_plain().assume_tz("Asia/Amman").strict_eq(d3)
        # the NYC instance is still the same value (but a different instance/pointer)
        assert d.to_plain().assume_tz(nyc).strict_eq(d)

        # but we can still use an old instance
        d2.add(hours=24)

        # We can request proper time zones now again
        assert ZonedDateTime(2020, 8, 15, 5, 12, tz=nyc) == d
        # exact_eq() works again
        assert ZonedDateTime(2020, 8, 15, 5, 12, tz=nyc).strict_eq(d)

        repeated = ZonedDateTime(
            2023,
            11,
            5,
            1,
            30,
            tz=nyc,
            disambiguation="later",
        )
        clear_tzcache(only_keys=[nyc])
        assert repeated.replace(tz=nyc).strict_eq(repeated)

        # check exception handling invalid arguments
        with pytest.raises(TypeError, match="iterable"):
            reset_tzpath("/usr/share/zoneinfo")  # must be a list!
        with pytest.raises(TypeError, match="iterable"):
            clear_tzcache(only_keys=nyc)  # must be a list!
        with pytest.raises(ValueError, match="absolute"):
            reset_tzpath(["../../share/zoneinfo"])


# NOTE: there's a separate test for changing the search path and
# its effect on available_timezones()
# We run this test relatively late to allow the cache to be used more
# organically throughout other tests instead of immediately loading everything
# here beforehand
@pytest.mark.order(-2)
def test_available_timezones():
    tzs = available_timezones()

    # So long as we don't mess with the configuration, these should be identical
    assert tzs == zoneinfo_available_timezones().difference(["localtime"])

    d = ZonedDateTime(2025, 3, 26, 1, 15, 30, tz="UTC")

    # We should be able to load all of them
    for tz in tzs:
        d = d.to_tz(tz)


def test_available_timezones_skips_right_and_posix(tmp_path: Path):
    source = TEST_DIR / "tzif" / "Amsterdam.tzif"
    for prefix in ("", "right", "posix"):
        zone = tmp_path / prefix / "Europe" / "Amsterdam"
        zone.parent.mkdir(parents=True)
        shutil.copyfile(source, zone)

    previous = get_tzpath()
    reset_tzpath([tmp_path])
    try:
        tzs = available_timezones()
    finally:
        reset_tzpath(previous)
    assert "Europe/Amsterdam" in tzs
    assert not {z for z in tzs if z.startswith(("right/", "posix/"))}


class TestClearTzCache:
    @pytest.mark.skipif(
        _EXTENSION_LOADED, reason="Rust extension has its own cache"
    )
    def test_clear_by_keys_clears_last_tz(self):
        """Clearing the cache by key clears _last_tz_key when it matches."""
        from whenever._tz import store

        # Load a time zone to populate the fast cache
        ZonedDateTime(2024, 1, 1, tz="US/Eastern")
        assert store._last_tz_key == "us/eastern"
        # Now clear that exact key — _last_tz_key should be reset
        clear_tzcache(only_keys=["US/Eastern"])
        assert store._last_tz_key is None

    @pytest.mark.parametrize("bad", [3, None, b"UTC", 3.5, ["UTC"]])
    def test_non_string_key(self, bad):
        with pytest.raises(
            TypeError, match="^only_keys must be an iterable of time zone IDs$"
        ):
            clear_tzcache(only_keys=[bad])

    def test_system_tz_is_not_a_key(self):
        with pytest.raises(
            TypeError, match="^only_keys must be an iterable of time zone IDs$"
        ):
            clear_tzcache(only_keys=[SYSTEM_TZ])  # type: ignore[list-item]


def test_system_tz_sentinel():
    assert repr(SYSTEM_TZ) == "SYSTEM_TZ"
    assert copy(SYSTEM_TZ) is SYSTEM_TZ
    assert deepcopy(SYSTEM_TZ) is SYSTEM_TZ
    payload = pickle.dumps(SYSTEM_TZ)
    assert b"whenever._" not in payload
    assert b"whenever" in payload
    assert b"SYSTEM_TZ" in payload
    assert pickle.loads(payload) is SYSTEM_TZ


def test_get_tzpath_returns_snapshot(tmp_path):
    previous = get_tzpath()
    try:
        reset_tzpath([tmp_path])
        assert get_tzpath() == (str(tmp_path),)
        assert previous != get_tzpath()
    finally:
        reset_tzpath(previous)


class TestResetTzpath:
    def test_empty_environment_variable(self, monkeypatch):
        # an empty PYTHONTZPATH means no directories, as it does for zoneinfo
        previous = get_tzpath()
        monkeypatch.setenv("PYTHONTZPATH", "")
        try:
            reset_tzpath()
            assert get_tzpath() == ()
        finally:
            reset_tzpath(previous)

    def test_iterator_is_read_once(self, tmp_path):
        previous = get_tzpath()
        try:
            reset_tzpath(iter([tmp_path]))
            assert get_tzpath() == (str(tmp_path),)
        finally:
            reset_tzpath(previous)

    @pytest.mark.parametrize("bad", [[b"/x"], [1], 1, "/x", b"/x", [None]])
    def test_not_an_iterable_of_paths(self, bad):
        with pytest.raises(
            TypeError,
            match="^reset_tzpath\\(\\) argument must be an iterable of paths$",
        ):
            reset_tzpath(bad)

    def test_relative_entry(self, tmp_path):
        with pytest.raises(
            ValueError,
            match="^time zone search path entries must be absolute paths, "
            "got 'zoneinfo'$",
        ):
            reset_tzpath([tmp_path, "zoneinfo"])
        with pytest.raises(
            ValueError,
            match="^time zone search path entries must be absolute paths, "
            "got .*Path\\('zoneinfo'\\)$",
        ):
            reset_tzpath([Path("zoneinfo")])
        # nothing was set
        assert get_tzpath() != (str(tmp_path),)


class TestEmptyTzIsUtc:
    def test_from_the_database(self):
        with system_tz(""):
            assert ZonedDateTime.now(SYSTEM_TZ).tz_id == "UTC"

    @pytest.mark.skipif(
        _EXTENSION_LOADED, reason="the pure-Python store is not in use"
    )
    def test_falls_back_to_posix(self, monkeypatch):
        from whenever._tz import store

        def not_found(key):
            raise TimeZoneNotFoundError._for_key(key)  # type: ignore[attr-defined]

        monkeypatch.setattr(store, "get_tz", not_found)
        with patch.dict(os.environ, {"TZ": ""}):
            tz = store._read_system_tz()
        assert tz.key is None
        assert tz.offset_for_instant(0) == 0


def test_get_system_tz():

    tz_type, tz_value = get_tz()
    assert tz_type in (0, 1, 2)
    assert isinstance(tz_value, str)


@system_tz("Europe/Amsterdam")
def test_reset_system_tz():
    plain = PlainDateTime(2020, 1, 1)
    d1 = plain.assume_tz(SYSTEM_TZ)
    assert d1.tz_id == "Europe/Amsterdam"

    with patch.dict(os.environ, {"TZ": "America/New_York"}):
        # The system time zone is now set to America/New_York
        # ...but the cache isn't updated until we call reset_system_tz()
        assert plain.assume_tz(SYSTEM_TZ).tz_id == "Europe/Amsterdam"

        reset_system_tz()
        d2 = plain.assume_tz(SYSTEM_TZ)
        assert d2.tz_id == "America/New_York"

        # old instances should not change
        assert d1.tz_id == "Europe/Amsterdam"

    # Cache not yet updated again...
    assert plain.assume_tz(SYSTEM_TZ).tz_id == "America/New_York"

    reset_system_tz()
    assert plain.assume_tz(SYSTEM_TZ).tz_id == "Europe/Amsterdam"


class TestUnresolvableSystemTz:
    @staticmethod
    def _cases(tmp_path: Path) -> list[tuple[str, str]]:
        not_tzif = tmp_path / "not-tzif"
        not_tzif.write_bytes(b"this is not a TZif file")
        # absolute on every platform: a bare `/x` is not absolute on Windows
        return [
            (str(tmp_path / "missing"), "no time zone found at path"),
            (str(not_tzif), "no time zone found at path"),
            ("Foo1Bar", "is not a time zone ID or POSIX TZ string"),
        ]

    @system_tz("Europe/Amsterdam")
    def test_raises_and_keeps_cache(self, tmp_path: Path) -> None:
        for value, message in self._cases(tmp_path):
            with pytest.raises(TimeZoneNotFoundError, match=message):
                with system_tz(value):
                    pass  # pragma: no cover
            # the failed reset left the cached time zone in place
            assert ZonedDateTime.now(SYSTEM_TZ).tz_id == "Europe/Amsterdam"


@pytest.mark.parametrize(
    "path, expect",
    [
        ("/usr/share/foo", None),
        ("", None),
        ("/etc/timezone", None),
        ("/usr/share/zoneinfo/Europe/Amsterdam", "Europe/Amsterdam"),
        ("/usr/share/zoneinfo.default/America/New_York", "America/New_York"),
        ("/usr/share/zoneinfo.default/", ""),
        ("/usr/share/zoneinfo/zoneinfo.default/UTC", "UTC"),
        ("/usr/share/zoneinfo", None),
    ],
)
def test_tzid_from_path(path, expect):
    assert _tzid_from_path(path) == expect


def test_tz_store_rejects_non_string_key():
    from whenever._tz.store import get_tz as store_get_tz

    with pytest.raises(TypeError, match="^tz must be a string or SYSTEM_TZ$"):
        store_get_tz(1)  # type: ignore[arg-type]
