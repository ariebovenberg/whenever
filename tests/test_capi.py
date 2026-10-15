"""The C API capsule ``whenever.C_API_v1``, driven through ``ctypes``.

Extractors are called through ``CFUNCTYPE``, which releases the GIL for the
call, as the contract allows. Constructors are called through ``PYFUNCTYPE``,
which keeps it and raises the exception they set.
"""

import ctypes
import sys
from ctypes import (
    CFUNCTYPE,
    POINTER,
    PYFUNCTYPE,
    Structure,
    byref,
    c_char,
    c_char_p,
    c_int,
    c_int32,
    c_int64,
    c_uint8,
    c_uint16,
    c_uint32,
    c_void_p,
    py_object,
)
from typing import Any, Literal

import pytest
import whenever
from whenever import (
    Date,
    Instant,
    InvalidOffsetError,
    OffsetDateTime,
    PlainDateTime,
    RepeatedTime,
    SkippedTime,
    Time,
    TimeDelta,
    TimeZoneNotFoundError,
    ZonedDateTime,
)

from .common import AMS_TZ_RAWFILE, create_zdt

_AMS = "Europe/Amsterdam"
CAPSULE_NAME = b"whenever.C_API_v1"


pytestmark = pytest.mark.skipif(
    not whenever._EXTENSION_LOADED,
    reason="the capsule needs the Rust extension",
)


# --- include/whenever.h, in ctypes -----------------------------------------


class CDate(Structure):
    _fields_ = [("year", c_uint16), ("month", c_uint8), ("day", c_uint8)]


class CTime(Structure):
    _fields_ = [
        ("hour", c_uint8),
        ("minute", c_uint8),
        ("second", c_uint8),
        ("nanosecond", c_uint32),
    ]


class CPlainDateTime(Structure):
    _fields_ = [("date", CDate), ("time", CTime)]


class CInstant(Structure):
    _fields_ = [("epoch_second", c_int64), ("nanosecond", c_uint32)]


class COffsetDateTime(Structure):
    _fields_ = [("local", CPlainDateTime), ("offset_second", c_int32)]


class CZonedDateTime(Structure):
    _fields_ = [
        ("odt", COffsetDateTime),
        ("tz_id", POINTER(c_char)),
        ("tz_id_len", c_uint8),
    ]


class CTimeDelta(Structure):
    _fields_ = [("second", c_int64), ("nanosecond", c_uint32)]


def _extract(record: type[Structure]) -> Any:
    return CFUNCTYPE(c_int, c_void_p, py_object, POINTER(record))


def _new(record: type[Structure]) -> Any:
    return PYFUNCTYPE(py_object, c_void_p, POINTER(record))


class CAPI(Structure):
    _fields_ = [
        ("magic", c_char_p),
        ("struct_size", c_int32),
        ("version_minor", c_int32),
        ("DateType", c_void_p),
        ("TimeType", c_void_p),
        ("PlainDateTimeType", c_void_p),
        ("InstantType", c_void_p),
        ("OffsetDateTimeType", c_void_p),
        ("ZonedDateTimeType", c_void_p),
        ("TimeDeltaType", c_void_p),
        ("date_extract", _extract(CDate)),
        ("time_extract", _extract(CTime)),
        ("plain_datetime_extract", _extract(CPlainDateTime)),
        ("instant_extract", _extract(CInstant)),
        ("offset_datetime_extract", _extract(COffsetDateTime)),
        ("zoned_datetime_extract", _extract(CZonedDateTime)),
        ("time_delta_extract", _extract(CTimeDelta)),
        ("date_new", _new(CDate)),
        ("time_new", _new(CTime)),
        ("plain_datetime_new", _new(CPlainDateTime)),
        ("instant_new", _new(CInstant)),
        ("offset_datetime_new", _new(COffsetDateTime)),
        ("time_delta_new", _new(CTimeDelta)),
        (
            "zoned_datetime_from_instant",
            PYFUNCTYPE(
                py_object,
                c_void_p,
                POINTER(CInstant),
                POINTER(c_char),
                c_uint8,
            ),
        ),
        (
            "zoned_datetime_new",
            PYFUNCTYPE(
                py_object, c_void_p, POINTER(CZonedDateTime), c_int, c_int
            ),
        ),
    ]


RAISE, KEEP_INSTANT, KEEP_LOCAL = 0, 1, 2
COMPATIBLE, EARLIER, LATER, DIS_RAISE = 0, 1, 2, 3


@pytest.fixture(scope="module")
def api():
    get = ctypes.pythonapi.PyCapsule_GetPointer
    get.restype = c_void_p
    get.argtypes = [py_object, c_char_p]
    return Api(get(getattr(whenever, "C_API_v1"), CAPSULE_NAME))


class Api:
    """The table, with the pointer each call takes as its first argument."""

    def __init__(self, ptr: int):
        self.ptr = ptr
        self.table = CAPI.from_address(ptr)

    def extract(self, name: str, obj: object, out: Structure) -> int:
        return int(getattr(self.table, name)(self.ptr, obj, byref(out)))

    def new(self, name: str, *args: object) -> Any:
        # ctypes takes over the new reference a ``py_object`` result carries
        return getattr(self.table, name)(self.ptr, *args)

    @staticmethod
    def tz_id(s: bytes) -> tuple[Any, int]:
        return ctypes.cast(c_char_p(s), POINTER(c_char)), len(s)


def test_header(api):
    assert api.table.magic == CAPSULE_NAME
    assert api.table.struct_size == ctypes.sizeof(CAPI)
    assert api.table.version_minor == 0


def test_type_slots(api):
    for name, cls in [
        ("DateType", Date),
        ("TimeType", Time),
        ("PlainDateTimeType", PlainDateTime),
        ("InstantType", Instant),
        ("OffsetDateTimeType", OffsetDateTime),
        ("ZonedDateTimeType", ZonedDateTime),
        ("TimeDeltaType", TimeDelta),
    ]:
        assert getattr(api.table, name) == id(cls)


def _fields(record: Structure) -> dict[str, Any]:
    result = {}
    for field in record._fields_:
        name = field[0]
        value = getattr(record, name)
        result[name] = (
            _fields(value) if isinstance(value, Structure) else value
        )
    return result


class TestExtract:
    def test_date(self, api):
        out = CDate()
        assert api.extract("date_extract", Date(2024, 2, 29), out) == 0
        assert _fields(out) == {"year": 2024, "month": 2, "day": 29}

    def test_time(self, api):
        out = CTime()
        assert (
            api.extract("time_extract", Time(3, 4, 5, nanosecond=6), out) == 0
        )
        assert _fields(out) == {
            "hour": 3,
            "minute": 4,
            "second": 5,
            "nanosecond": 6,
        }

    def test_plain_datetime(self, api):
        out = CPlainDateTime()
        value = PlainDateTime(2024, 2, 29, 3, 4, 5, nanosecond=600_700_800)
        assert api.extract("plain_datetime_extract", value, out) == 0
        assert _fields(out) == {
            "date": {"year": 2024, "month": 2, "day": 29},
            "time": {
                "hour": 3,
                "minute": 4,
                "second": 5,
                "nanosecond": 600_700_800,
            },
        }

    @pytest.mark.parametrize(
        ("value", "expect"),
        [
            (
                Instant.from_utc(2024, 2, 29, 3, 4, 5, nanosecond=7),
                (1_709_175_845, 7),
            ),
            (Instant.MIN, (-62_135_596_800, 0)),
            (Instant.MAX, (253_402_300_799, 999_999_999)),
        ],
    )
    def test_instant(self, api, value, expect):
        out = CInstant()
        assert api.extract("instant_extract", value, out) == 0
        assert (out.epoch_second, out.nanosecond) == expect

    def test_offset_datetime(self, api):
        out = COffsetDateTime()
        value = OffsetDateTime(
            2024, 2, 29, 3, 4, 5, offset=TimeDelta(seconds=-3723)
        )
        assert api.extract("offset_datetime_extract", value, out) == 0
        assert out.local.date.year == 2024
        assert out.local.time.hour == 3
        assert out.offset_second == -3723

    def test_zoned_datetime(self, api):
        out = CZonedDateTime()
        value = ZonedDateTime(2024, 2, 29, 3, 4, 5, tz="europe/amsterdam")
        assert api.extract("zoned_datetime_extract", value, out) == 0
        assert out.odt.local.date.day == 29
        assert out.odt.offset_second == 3600
        assert (
            ctypes.string_at(out.tz_id, out.tz_id_len) == b"Europe/Amsterdam"
        )

    def test_zoned_datetime_without_tz_id(self, api):
        out = CZonedDateTime()
        value = create_zdt(2023, 12, 3, 9, 15, tz=AMS_TZ_RAWFILE)
        assert api.extract("zoned_datetime_extract", value, out) == 0
        assert not out.tz_id
        assert out.tz_id_len == 0

    @pytest.mark.parametrize(
        ("value", "expect"),
        [
            (
                TimeDelta(seconds=-12_345, nanoseconds=678_901_234),
                (-12_345, 678_901_234),
            ),
            (TimeDelta(nanoseconds=-1), (-1, 999_999_999)),
            (TimeDelta.ZERO, (0, 0)),
        ],
    )
    def test_time_delta(self, api, value, expect):
        out = CTimeDelta()
        assert api.extract("time_delta_extract", value, out) == 0
        assert (out.second, out.nanosecond) == expect

    @pytest.mark.parametrize(
        ("name", "record"),
        [
            ("date_extract", CDate),
            ("time_extract", CTime),
            ("plain_datetime_extract", CPlainDateTime),
            ("instant_extract", CInstant),
            ("offset_datetime_extract", COffsetDateTime),
            ("zoned_datetime_extract", CZonedDateTime),
            ("time_delta_extract", CTimeDelta),
        ],
    )
    def test_wrong_type_writes_nothing(self, api, name, record):
        out = record()
        before = bytes(out)
        for obj in (Time(1), Date(2024, 1, 1), 3, None, "x"):
            if isinstance(obj, (Date, Time)) and name.startswith(
                type(obj).__name__.lower()
            ):
                continue
            assert api.extract(name, obj, out) == 1
            assert bytes(out) == before
            assert sys.exc_info() == (None, None, None)


class TestNew:
    def test_date(self, api):
        assert api.new("date_new", byref(CDate(2024, 2, 29))) == Date(
            2024, 2, 29
        )
        with pytest.raises(ValueError, match="invalid date"):
            api.new("date_new", byref(CDate(2023, 2, 29)))
        with pytest.raises(ValueError, match="invalid date"):
            api.new("date_new", byref(CDate(0, 1, 1)))

    def test_time(self, api):
        assert api.new("time_new", byref(CTime(3, 4, 5, 6))) == Time(
            3, 4, 5, nanosecond=6
        )
        with pytest.raises(ValueError, match="invalid time"):
            api.new("time_new", byref(CTime(24, 0, 0, 0)))
        with pytest.raises(ValueError, match="invalid time"):
            api.new("time_new", byref(CTime(0, 0, 0, 1_000_000_000)))

    def test_plain_datetime(self, api):
        rec = CPlainDateTime(CDate(2024, 2, 29), CTime(3, 4, 5, 6))
        assert api.new("plain_datetime_new", byref(rec)) == PlainDateTime(
            2024, 2, 29, 3, 4, 5, nanosecond=6
        )
        with pytest.raises(ValueError, match="invalid date or time"):
            api.new(
                "plain_datetime_new", byref(CPlainDateTime(CDate(2024, 2, 30)))
            )

    def test_instant(self, api):
        assert api.new("instant_new", byref(CInstant(1_709_175_845, 7))) == (
            Instant.from_utc(2024, 2, 29, 3, 4, 5, nanosecond=7)
        )
        assert (
            api.new("instant_new", byref(CInstant(-62_135_596_800, 0)))
            == Instant.MIN
        )
        for rec in [
            CInstant(-62_135_596_801, 0),
            CInstant(253_402_300_800, 0),
            CInstant(0, 1_000_000_000),
        ]:
            with pytest.raises(ValueError, match="instant out of range"):
                api.new("instant_new", byref(rec))

    def test_offset_datetime(self, api):
        rec = COffsetDateTime(
            CPlainDateTime(CDate(2024, 2, 29), CTime(3, 4, 5)), -3723
        )
        assert api.new("offset_datetime_new", byref(rec)) == OffsetDateTime(
            2024, 2, 29, 3, 4, 5, offset=TimeDelta(seconds=-3723)
        )
        for rec in [
            COffsetDateTime(CPlainDateTime(CDate(2024, 2, 29)), 86_400),
            COffsetDateTime(CPlainDateTime(CDate(1, 1, 1)), 1),
            COffsetDateTime(CPlainDateTime(CDate(2024, 2, 29), CTime(25)), 0),
        ]:
            with pytest.raises(
                ValueError, match="invalid date, time, or offset"
            ):
                api.new("offset_datetime_new", byref(rec))

    def test_time_delta(self, api):
        rec = CTimeDelta(-12_345, 678_901_234)
        assert api.new("time_delta_new", byref(rec)) == TimeDelta(
            seconds=-12_345, nanoseconds=678_901_234
        )
        for rec in [
            CTimeDelta(9999 * 366 * 24 * 3_600, 1),
            CTimeDelta(0, 1_000_000_000),
        ]:
            with pytest.raises(ValueError, match="TimeDelta out of range"):
                api.new("time_delta_new", byref(rec))

    def test_zoned_datetime_from_instant(self, api):
        rec = CInstant(1_709_175_845, 7)
        result = api.new(
            "zoned_datetime_from_instant",
            byref(rec),
            *api.tz_id(b"europe/amsterdam"),
        )
        assert result.strict_eq(
            ZonedDateTime(2024, 2, 29, 4, 4, 5, nanosecond=7, tz=_AMS)
        )
        with pytest.raises(TimeZoneNotFoundError):
            api.new(
                "zoned_datetime_from_instant",
                byref(rec),
                *api.tz_id(b"Nope/Zone"),
            )
        with pytest.raises(ValueError, match="tz_id is required"):
            api.new("zoned_datetime_from_instant", byref(rec), None, 0)
        with pytest.raises(TimeZoneNotFoundError):
            api.new(
                "zoned_datetime_from_instant",
                byref(rec),
                *api.tz_id("Europe/Zürich".encode()),
            )
        with pytest.raises(ValueError, match="invalid tz_id"):
            api.new(
                "zoned_datetime_from_instant",
                byref(rec),
                *api.tz_id(b"Europe/\xff"),
            )
        with pytest.raises(ValueError, match="instant out of range"):
            api.new(
                "zoned_datetime_from_instant",
                byref(CInstant(0, 1_000_000_000)),
                *api.tz_id(b"UTC"),
            )

    @pytest.fixture()
    def ams(self, api):
        """A record builder in Amsterdam."""

        def build(local: PlainDateTime, offset_second: int) -> CZonedDateTime:
            return CZonedDateTime(
                COffsetDateTime(
                    CPlainDateTime(
                        CDate(local.year, local.month, local.day),
                        CTime(
                            local.hour,
                            local.minute,
                            local.second,
                            local.nanosecond,
                        ),
                    ),
                    offset_second,
                ),
                *api.tz_id(b"Europe/Amsterdam"),
            )

        return build

    def test_zoned_datetime_new(self, api, ams):
        rec = ams(PlainDateTime(2024, 7, 1, 12), 7200)
        result = api.new("zoned_datetime_new", byref(rec), RAISE, DIS_RAISE)
        assert result.strict_eq(ZonedDateTime(2024, 7, 1, 12, tz=_AMS))

    def test_zoned_datetime_new_mismatch(self, api, ams):
        rec = ams(PlainDateTime(2024, 7, 1, 12), 3600)
        with pytest.raises(InvalidOffsetError, match="Europe/Amsterdam"):
            api.new("zoned_datetime_new", byref(rec), RAISE, COMPATIBLE)
        kept_instant = api.new(
            "zoned_datetime_new", byref(rec), KEEP_INSTANT, COMPATIBLE
        )
        assert kept_instant.strict_eq(ZonedDateTime(2024, 7, 1, 13, tz=_AMS))
        kept_local = api.new(
            "zoned_datetime_new", byref(rec), KEEP_LOCAL, COMPATIBLE
        )
        assert kept_local.strict_eq(ZonedDateTime(2024, 7, 1, 12, tz=_AMS))

    def test_zoned_datetime_new_repeated(self, api, ams):
        # The offset settles a repeated time; a policy is consulted only
        # when it matches neither occurrence.
        cases: list[tuple[int, Literal["earlier", "later"]]] = [
            (7200, "earlier"),
            (3600, "later"),
        ]
        for offset, which in cases:
            rec = ams(PlainDateTime(2023, 10, 29, 2, 30), offset)
            result = api.new(
                "zoned_datetime_new", byref(rec), RAISE, DIS_RAISE
            )
            assert result.strict_eq(
                ZonedDateTime(
                    2023, 10, 29, 2, 30, tz=_AMS, disambiguation=which
                )
            )
        rec = ams(PlainDateTime(2023, 10, 29, 2, 30), 0)
        with pytest.raises(RepeatedTime):
            api.new("zoned_datetime_new", byref(rec), KEEP_LOCAL, DIS_RAISE)
        policies: list[tuple[int, Literal["earlier", "later"]]] = [
            (COMPATIBLE, "earlier"),
            (EARLIER, "earlier"),
            (LATER, "later"),
        ]
        for policy, which in policies:
            result = api.new(
                "zoned_datetime_new", byref(rec), KEEP_LOCAL, policy
            )
            assert result.strict_eq(
                ZonedDateTime(
                    2023, 10, 29, 2, 30, tz=_AMS, disambiguation=which
                )
            )

    def test_zoned_datetime_new_skipped(self, api, ams):
        rec = ams(PlainDateTime(2023, 3, 26, 2, 30), 3600)
        with pytest.raises(InvalidOffsetError):
            api.new("zoned_datetime_new", byref(rec), RAISE, COMPATIBLE)
        with pytest.raises(SkippedTime):
            api.new("zoned_datetime_new", byref(rec), KEEP_LOCAL, DIS_RAISE)
        result = api.new("zoned_datetime_new", byref(rec), KEEP_LOCAL, LATER)
        assert result.strict_eq(
            ZonedDateTime(2023, 3, 26, 2, 30, tz=_AMS, disambiguation="later")
        )

    def test_zoned_datetime_new_invalid(self, api, ams):
        rec = ams(PlainDateTime(2024, 7, 1, 12), 7200)
        with pytest.raises(ValueError, match="invalid offset_mismatch: 3"):
            api.new("zoned_datetime_new", byref(rec), 3, COMPATIBLE)
        with pytest.raises(ValueError, match="invalid disambiguation: -1"):
            api.new("zoned_datetime_new", byref(rec), RAISE, -1)
        rec = ams(PlainDateTime(2024, 7, 1, 12), 86_400)
        with pytest.raises(ValueError, match="offset out of range"):
            api.new("zoned_datetime_new", byref(rec), RAISE, COMPATIBLE)
        rec = ams(PlainDateTime(2024, 7, 1, 12), 7200)
        rec.odt.local.date.month = 13
        with pytest.raises(ValueError, match="invalid date or time"):
            api.new("zoned_datetime_new", byref(rec), RAISE, COMPATIBLE)
        rec = ams(PlainDateTime(2024, 7, 1, 12), 7200)
        rec.tz_id, rec.tz_id_len = api.tz_id(b"Nope/Zone")
        with pytest.raises(TimeZoneNotFoundError):
            api.new("zoned_datetime_new", byref(rec), RAISE, COMPATIBLE)
        rec.tz_id, rec.tz_id_len = None, 0
        with pytest.raises(ValueError, match="tz_id is required"):
            api.new("zoned_datetime_new", byref(rec), RAISE, COMPATIBLE)
