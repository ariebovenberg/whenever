import pickle
import struct
import warnings
from collections.abc import Callable, Iterator
from pathlib import Path
from typing import cast

import pytest
import whenever as w
from whenever import _pywhenever as py

from .common import AMS_TZ_RAWFILE_DST_LATE, tz_rules_from_file, warns_here

_ReduceResult = tuple[Callable[..., object], tuple[object, ...]]


@pytest.mark.parametrize(
    ("value", "payload"),
    [
        (w.Date(2024, 2, 29), struct.pack("<HBB", 2024, 2, 29)),
        (
            w.Time(3, 4, 5, nanosecond=600_700_800),
            struct.pack("<BBBI", 3, 4, 5, 600_700_800),
        ),
        (
            w.PlainDateTime(2024, 2, 29, 3, 4, 5, nanosecond=600_700_800),
            struct.pack("<HBBBBBi", 2024, 2, 29, 3, 4, 5, 600_700_800),
        ),
        (
            w.Instant.from_utc(2024, 2, 29, 3, 4, 5, nanosecond=600_700_800),
            struct.pack("<qL", 1_709_175_845, 600_700_800),
        ),
        (
            w.TimeDelta(seconds=-12_345, nanoseconds=678_901_234),
            struct.pack("<qI", -12_345, 678_901_234),
        ),
        (
            w.OffsetDateTime(
                2024,
                2,
                29,
                3,
                4,
                5,
                nanosecond=600_700_800,
                offset=w.TimeDelta(seconds=-3_723),
            ),
            struct.pack(
                "<HBBBBBil", 2024, 2, 29, 3, 4, 5, 600_700_800, -3_723
            ),
        ),
        (
            w.ZonedDateTime(
                2024,
                2,
                29,
                3,
                4,
                5,
                nanosecond=600_700_800,
                tz="UTC",
            ),
            struct.pack("<HBBBBBil", 2024, 2, 29, 3, 4, 5, 600_700_800, 0),
        ),
        (w.YearMonth(2024, 2), struct.pack("<HB", 2024, 2)),
        (w.MonthDay(2, 29), struct.pack("<BB", 2, 29)),
        (
            w.IsoWeekDate(2024, 9, w.Weekday.THURSDAY),
            struct.pack("<hBB", 2024, 9, 4),
        ),
    ],
)
def test_payload_matches_wire_format(value: object, payload: bytes):
    assert value.__reduce__()[1][0] == payload


@pytest.mark.parametrize(
    ("value", "name", "payload"),
    [
        (
            w.ItemizedDelta(years=-1, days=-2, nanoseconds=-3),
            "_unpkl_idelta",
            (-1, None, None, -2, None, None, 0, -3),
        ),
        (
            w.ItemizedDateDelta(months=1, weeks=0),
            "_unpkl_iddelta",
            (None, 1, 0, None),
        ),
    ],
)
def test_itemized_payload_matches_wire_format(
    value: object, name: str, payload: tuple[int | None, ...]
):
    unpickle, args = cast(_ReduceResult, value.__reduce__())
    assert unpickle.__name__ == name
    assert args == payload


@pytest.mark.parametrize(
    ("value", "payload"),
    [
        (w.Date.MIN, struct.pack("<HBB", 1, 1, 1)),
        (w.Date.MAX, struct.pack("<HBB", 9999, 12, 31)),
        (w.Time.MIN, struct.pack("<BBBI", 0, 0, 0, 0)),
        (w.Time.MAX, struct.pack("<BBBI", 23, 59, 59, 999_999_999)),
        (
            w.PlainDateTime.MIN,
            struct.pack("<HBBBBBi", 1, 1, 1, 0, 0, 0, 0),
        ),
        (
            w.PlainDateTime.MAX,
            struct.pack("<HBBBBBi", 9999, 12, 31, 23, 59, 59, 999_999_999),
        ),
        (w.Instant.MIN, struct.pack("<qL", -62_135_596_800, 0)),
        (
            w.Instant.MAX,
            struct.pack("<qL", 253_402_300_799, 999_999_999),
        ),
        (
            w.TimeDelta.MIN,
            struct.pack("<qI", -(9999 * 366 * 24 * 3_600), 0),
        ),
        (
            w.TimeDelta.MAX,
            struct.pack("<qI", 9999 * 366 * 24 * 3_600, 0),
        ),
    ],
)
def test_boundary_payloads_match_wire_format(value: object, payload: bytes):
    assert value.__reduce__()[1][0] == payload


@pytest.mark.parametrize(
    ("name", "args"),
    [
        ("_unpkl_date", (struct.pack("<HBB", 0, 1, 1),)),
        ("_unpkl_date", (struct.pack("<HBB", 2024, 13, 1),)),
        ("_unpkl_date", (struct.pack("<HBB", 2024, 2, 30),)),
        ("_unpkl_time", (struct.pack("<BBBI", 24, 0, 0, 0),)),
        ("_unpkl_time", (struct.pack("<BBBI", 0, 60, 0, 0),)),
        ("_unpkl_time", (struct.pack("<BBBI", 0, 0, 60, 0),)),
        ("_unpkl_time", (struct.pack("<BBBI", 0, 0, 0, 1_000_000_000),)),
        (
            "_unpkl_local",
            (struct.pack("<HBBBBBi", 2024, 2, 30, 0, 0, 0, 0),),
        ),
        (
            "_unpkl_local",
            (struct.pack("<HBBBBBi", 2024, 2, 29, 0, 0, 0, 1_000_000_000),),
        ),
        ("_unpkl_utc", (struct.pack("<qL", 0, 1_000_000_000),)),
        ("_unpkl_inst", (struct.pack("<qL", -62_135_596_801, 0),)),
        ("_unpkl_inst", (struct.pack("<qL", 253_402_300_800, 0),)),
        ("_unpkl_inst", (struct.pack("<qL", 0, 1_000_000_000),)),
        (
            "_unpkl_tdelta",
            (struct.pack("<qI", 9999 * 366 * 24 * 3_600, 1),),
        ),
        ("_unpkl_tdelta", (struct.pack("<qI", 0, 1_000_000_000),)),
        (
            "_unpkl_offset",
            (struct.pack("<HBBBBBil", 2024, 1, 1, 0, 0, 0, 0, 86_400),),
        ),
        (
            "_unpkl_offset",
            (struct.pack("<HBBBBBil", 1, 1, 1, 0, 0, 0, 0, 1),),
        ),
        (
            "_unpkl_zoned",
            (
                struct.pack(
                    "<HBBBBBil",
                    2024,
                    1,
                    1,
                    0,
                    0,
                    0,
                    1_000_000_000,
                    0,
                ),
                "UTC",
            ),
        ),
        (
            "_unpkl_zoned",
            (
                struct.pack("<HBBBBBil", 2024, 1, 1, 0, 0, 0, 0, 86_400),
                "UTC",
            ),
        ),
        ("_unpkl_md", (struct.pack("<BB", 2, 30),)),
        ("_unpkl_iwd", (struct.pack("<hBB", 2024, 54, 1),)),
        ("_unpkl_iwd", (struct.pack("<hBB", 0, 1, 1),)),
    ],
)
def test_malformed_payload_is_rejected(name: str, args: tuple[object, ...]):
    with pytest.raises(ValueError):
        getattr(w, name)(*args)


@pytest.mark.parametrize(
    ("name", "size", "extra"),
    [
        ("_unpkl_date", 4, ()),
        ("_unpkl_time", 7, ()),
        ("_unpkl_local", 11, ()),
        ("_unpkl_inst", 12, ()),
        ("_unpkl_tdelta", 12, ()),
        ("_unpkl_offset", 15, ()),
        ("_unpkl_zoned", 15, ("UTC",)),
        ("_unpkl_ym", 3, ()),
        ("_unpkl_md", 2, ()),
        ("_unpkl_iwd", 4, ()),
    ],
)
def test_wrong_payload_length_is_rejected(
    name: str, size: int, extra: tuple[object, ...]
):
    unpickle = getattr(w, name)
    for data in (bytes(size - 1), bytes(size + 1)):
        with pytest.raises(ValueError):
            unpickle(data, *extra)


@pytest.mark.skipif(
    not w._EXTENSION_LOADED,
    reason="the exact-bytes policy belongs to the Rust FFI boundary",
)
@pytest.mark.parametrize(
    ("name", "args"),
    [
        ("_unpkl_date", (bytearray(4),)),
        ("_unpkl_time", (bytearray(7),)),
        ("_unpkl_local", (bytearray(11),)),
        ("_unpkl_inst", (bytearray(12),)),
        ("_unpkl_tdelta", (bytearray(12),)),
        ("_unpkl_offset", (bytearray(15),)),
        ("_unpkl_zoned", (bytearray(15), "UTC")),
    ],
)
def test_rust_unpicklers_require_exact_bytes(
    name: str, args: tuple[object, ...]
):
    with pytest.raises(TypeError, match="expected bytes argument"):
        getattr(w, name)(*args)


# Generated by `pickle.dumps()` under each release, on CPython 3.12. The
# payload layouts of every surviving type have not changed since 0.8.0.
# 0.8.0 could not pickle Weekday (its enum was defined under the wrong module).
_PICKLES_0_8_0 = [
    (
        b"\x80\x04\x95'\x00\x00\x00\x00\x00\x00\x00\x8c\x08whenever\x94"
        b"\x8c\x0b_unpkl_date\x94\x93\x94C\x04\xe4\x07\x03\x01\x94\x85\x94R\x94.",
        w.Date(2020, 3, 1),
    ),
    (
        b"\x80\x04\x95$\x00\x00\x00\x00\x00\x00\x00\x8c\x08whenever\x94"
        b"\x8c\t_unpkl_ym\x94\x93\x94C\x03\xe4\x07\x03\x94\x85\x94R\x94.",
        w.YearMonth(2020, 3),
    ),
    (
        b"\x80\x04\x95#\x00\x00\x00\x00\x00\x00\x00\x8c\x08whenever\x94"
        b"\x8c\t_unpkl_md\x94\x93\x94C\x02\x03\x01\x94\x85\x94R\x94.",
        w.MonthDay(3, 1),
    ),
    (
        b"\x80\x04\x95*\x00\x00\x00\x00\x00\x00\x00\x8c\x08whenever\x94"
        b"\x8c\x0b_unpkl_time\x94\x93\x94C\x07\x0c\x1e-{\x00\x00\x00\x94\x85\x94R\x94.",
        w.Time(12, 30, 45, nanosecond=123),
    ),
    (
        b"\x80\x04\x951\x00\x00\x00\x00\x00\x00\x00\x8c\x08whenever\x94"
        b"\x8c\r_unpkl_tdelta\x94\x93\x94C\x0c\x18\x15\x00\x00\x00\x00\x00\x00"
        b"\x07\x00\x00\x00\x94\x85\x94R\x94.",
        w.TimeDelta(hours=1, minutes=30, nanoseconds=7),
    ),
    (
        b"\x80\x04\x95/\x00\x00\x00\x00\x00\x00\x00\x8c\x08whenever\x94"
        b"\x8c\x0b_unpkl_inst\x94\x93\x94C\x0c\xc0\xa3[^\x00\x00\x00\x00\x00\x00"
        b"\x00\x00\x94\x85\x94R\x94.",
        w.Instant.from_utc(2020, 3, 1, 12),
    ),
    (
        b"\x80\x04\x954\x00\x00\x00\x00\x00\x00\x00\x8c\x08whenever\x94"
        b"\x8c\r_unpkl_offset\x94\x93\x94C\x0f\xe4\x07\x03\x01\x0c\x00\x00\x00"
        b"\x00\x00\x00 \x1c\x00\x00\x94\x85\x94R\x94.",
        w.OffsetDateTime(2020, 3, 1, 12, offset=w.hours(2)),
    ),
    (
        b"\x80\x04\x95F\x00\x00\x00\x00\x00\x00\x00\x8c\x08whenever\x94"
        b"\x8c\x0c_unpkl_zoned\x94\x93\x94C\x0f\xe4\x07\x01\x0f\x0c\x00\x00\x00"
        b"\x00\x00\x00\x10\x0e\x00\x00\x94\x8c\x10Europe/Amsterdam\x94\x86\x94R\x94.",
        w.ZonedDateTime(2020, 1, 15, 12, tz="Europe/Amsterdam"),
    ),
    (
        b"\x80\x04\x95/\x00\x00\x00\x00\x00\x00\x00\x8c\x08whenever\x94"
        b"\x8c\x0c_unpkl_local\x94\x93\x94C\x0b\xe4\x07\x03\x01\x0c\x1e\x00\x00"
        b"\x00\x00\x00\x94\x85\x94R\x94.",
        w.PlainDateTime(2020, 3, 1, 12, 30),
    ),
]

_PICKLES_0_10_5 = [
    (
        b"\x80\x04\x95'\x00\x00\x00\x00\x00\x00\x00\x8c\x08whenever\x94"
        b"\x8c\x0b_unpkl_date\x94\x93\x94C\x04\xe4\x07\x03\x01\x94\x85\x94R\x94.",
        w.Date(2020, 3, 1),
    ),
    (
        b"\x80\x04\x95$\x00\x00\x00\x00\x00\x00\x00\x8c\x08whenever\x94"
        b"\x8c\t_unpkl_ym\x94\x93\x94C\x03\xe4\x07\x03\x94\x85\x94R\x94.",
        w.YearMonth(2020, 3),
    ),
    (
        b"\x80\x04\x95#\x00\x00\x00\x00\x00\x00\x00\x8c\x08whenever\x94"
        b"\x8c\t_unpkl_md\x94\x93\x94C\x02\x03\x01\x94\x85\x94R\x94.",
        w.MonthDay(3, 1),
    ),
    (
        b"\x80\x04\x95*\x00\x00\x00\x00\x00\x00\x00\x8c\x08whenever\x94"
        b"\x8c\x0b_unpkl_time\x94\x93\x94C\x07\x0c\x1e-{\x00\x00\x00\x94\x85\x94R\x94.",
        w.Time(12, 30, 45, nanosecond=123),
    ),
    (
        b"\x80\x04\x951\x00\x00\x00\x00\x00\x00\x00\x8c\x08whenever\x94"
        b"\x8c\r_unpkl_tdelta\x94\x93\x94C\x0c\x18\x15\x00\x00\x00\x00\x00\x00"
        b"\x07\x00\x00\x00\x94\x85\x94R\x94.",
        w.TimeDelta(hours=1, minutes=30, nanoseconds=7),
    ),
    (
        b"\x80\x04\x95/\x00\x00\x00\x00\x00\x00\x00\x8c\x08whenever\x94"
        b"\x8c\x0b_unpkl_inst\x94\x93\x94C\x0c\xc0\xa3[^\x00\x00\x00\x00\x00\x00"
        b"\x00\x00\x94\x85\x94R\x94.",
        w.Instant.from_utc(2020, 3, 1, 12),
    ),
    (
        b"\x80\x04\x954\x00\x00\x00\x00\x00\x00\x00\x8c\x08whenever\x94"
        b"\x8c\r_unpkl_offset\x94\x93\x94C\x0f\xe4\x07\x03\x01\x0c\x00\x00\x00"
        b"\x00\x00\x00 \x1c\x00\x00\x94\x85\x94R\x94.",
        w.OffsetDateTime(2020, 3, 1, 12, offset=w.hours(2)),
    ),
    (
        b"\x80\x04\x95F\x00\x00\x00\x00\x00\x00\x00\x8c\x08whenever\x94"
        b"\x8c\x0c_unpkl_zoned\x94\x93\x94C\x0f\xe4\x07\x01\x0f\x0c\x00\x00\x00"
        b"\x00\x00\x00\x10\x0e\x00\x00\x94\x8c\x10Europe/Amsterdam\x94\x86\x94R\x94.",
        w.ZonedDateTime(2020, 1, 15, 12, tz="Europe/Amsterdam"),
    ),
    (
        b"\x80\x04\x95/\x00\x00\x00\x00\x00\x00\x00\x8c\x08whenever\x94"
        b"\x8c\x0c_unpkl_local\x94\x93\x94C\x0b\xe4\x07\x03\x01\x0c\x1e\x00\x00"
        b"\x00\x00\x00\x94\x85\x94R\x94.",
        w.PlainDateTime(2020, 3, 1, 12, 30),
    ),
    (
        b"\x80\x04\x95\x1e\x00\x00\x00\x00\x00\x00\x00\x8c\x08whenever\x94"
        b"\x8c\x07Weekday\x94\x93\x94K\x01\x85\x94R\x94.",
        w.Weekday.MONDAY,
    ),
    (
        b"\x80\x04\x95&\x00\x00\x00\x00\x00\x00\x00\x8c\x08whenever\x94"
        b"\x8c\n_unpkl_iwd\x94\x93\x94C\x04\xe4\x07\n\x01\x94\x85\x94R\x94.",
        w.IsoWeekDate(2020, 10, w.Weekday.MONDAY),
    ),
]

# Captured under earlier releases without a version note; the Instant payload
# naming ``_unpkl_utc`` predates 0.8.0.
_PICKLES_EARLIER = [
    (
        b"\x80\x04\x95'\x00\x00\x00\x00\x00\x00\x00\x8c\x08whenever\x94\x8c\x0b_unp"
        b"kl_date\x94\x93\x94C\x04\xe5\x07\x01\x02\x94\x85\x94R\x94.",
        w.Date(2021, 1, 2),
    ),
    (
        b"\x80\x04\x95$\x00\x00\x00\x00\x00\x00\x00\x8c\x08whenever\x94\x8c\t_unpkl_y"
        b"m\x94\x93\x94C\x03\xe5\x07\x01\x94\x85\x94R\x94.",
        w.YearMonth(2021, 1),
    ),
    (
        b"\x80\x04\x95#\x00\x00\x00\x00\x00\x00\x00\x8c\x08whenever\x94\x8c\t_unpkl_m"
        b"d\x94\x93\x94C\x02\x0b\x01\x94\x85\x94R\x94.",
        w.MonthDay(11, 1),
    ),
    (
        b"\x80\x04\x95&\x00\x00\x00\x00\x00\x00\x00\x8c\x08whenever"
        b"\x94\x8c\n_unpkl_iwd\x94\x93\x94C\x04\xe8\x07\x01\x01\x94"
        b"\x85\x94R\x94.",
        w.IsoWeekDate(2024, 1, w.Weekday.MONDAY),
    ),
    (
        b"\x80\x04\x95*\x00\x00\x00\x00\x00\x00\x00\x8c\x08whenever\x94\x8c\x0b_unp"
        b"kl_time\x94\x93\x94C\x07\x01\x02\x03\xa0\x0f\x00\x00\x94\x85\x94R\x94.",
        w.Time(1, 2, 3, nanosecond=4_000),
    ),
    (
        b"\x80\x04\x951\x00\x00\x00\x00\x00\x00\x00\x8c\x08whenever\x94\x8c\r_unpkl_t"
        b"delta\x94\x93\x94C\x0c\x8b\x0e\x00\x00\x00\x00\x00\x00\xa0\x0f"
        b"\x00\x00\x94\x85\x94R\x94.",
        w.TimeDelta(hours=1, minutes=2, seconds=3, microseconds=4),
    ),
    (
        b"\x80\x04\x95/\x00\x00\x00\x00\x00\x00\x00\x8c\x08whenever\x94\x8c\x0b_unp"
        b"kl_inst\x94\x93\x94C\x0c\xc9k8_\x00\x00\x00\x008h\xde:\x94\x85\x94R\x94.",
        w.Instant.from_utc(2020, 8, 15, 23, 12, 9, nanosecond=987_654_200),
    ),
    (
        b"\x80\x04\x95.\x00\x00\x00\x00\x00\x00\x00\x8c\x08whenever\x94\x8c\n_unpkl_u"
        b"tc\x94\x93\x94C\x0cI\xb4\xcb\xd6\x0e\x00\x00\x008h\xde:\x94\x85\x94R\x94.",
        w.Instant.from_utc(2020, 8, 15, 23, 12, 9, nanosecond=987_654_200),
    ),
    (
        b"\x80\x04\x954\x00\x00\x00\x00\x00\x00\x00\x8c\x08whenever\x94\x8c\r_unpkl_o"
        b"ffset\x94\x93\x94C\x0f\xe4\x07\x08\x0f\x17\x0c\t\xb1h\xde:0*\x00"
        b"\x00\x94\x85\x94R\x94.",
        w.OffsetDateTime(
            2020, 8, 15, 23, 12, 9, nanosecond=987_654_321, offset=w.hours(3)
        ),
    ),
    (
        b"\x80\x04\x95F\x00\x00\x00\x00\x00\x00\x00\x8c\x08whenever\x94\x8c\x0c_unp"
        b"kl_zoned\x94\x93\x94C\x0f\xe4\x07\x08\x0f\x17\x0c\t\x06\x12\x0f\x00"
        b" \x1c\x00\x00\x94\x8c\x10Europe/Amsterdam\x94\x86\x94R\x94.",
        w.ZonedDateTime(
            2020, 8, 15, 23, 12, 9, nanosecond=987_654, tz="Europe/Amsterdam"
        ),
    ),
    (
        b"\x80\x04\x95/\x00\x00\x00\x00\x00\x00\x00\x8c\x08whenever\x94\x8c\x0c_unp"
        b"kl_local\x94\x93\x94C\x0b\xe4\x07\x08\x0f\x17\x0c\t\x06\x12\x0f\x00"
        b"\x94\x85\x94R\x94.",
        w.PlainDateTime(2020, 8, 15, 23, 12, 9, nanosecond=987_654),
    ),
    (
        b"\x80\x04\x953\x00\x00\x00\x00\x00\x00\x00\x8c\x08whenever\x94\x8c\r_unpkl_i"
        b"delta\x94\x93\x94(K\x01K\x02K\x03K\x04K\x05K\x06K\x07K\x08t\x94R\x94.",
        w.ItemizedDelta(
            years=1,
            months=2,
            weeks=3,
            days=4,
            hours=5,
            minutes=6,
            seconds=7,
            nanoseconds=8,
        ),
    ),
    (
        b"\x80\x04\x95,\x00\x00\x00\x00\x00\x00\x00\x8c\x08whenever\x94\x8c\x0e_unp"
        b"kl_iddelta\x94\x93\x94(K\x01K\x02K\x03K\x04t\x94R\x94.",
        w.ItemizedDateDelta(years=1, months=2, weeks=3, days=4),
    ),
    # absent components, under a negative sign
    (
        b"\x80\x04\x954\x00\x00\x00\x00\x00\x00\x00\x8c\x08whenever\x94\x8c\r_unpkl_i"
        b"delta\x94\x93\x94(NNNNJ\xfb\xff\xff\xffNK\x00J\xf8\xff\xff\xfft\x94R\x94.",
        w.ItemizedDelta(hours=-5, seconds=0, nanoseconds=-8),
    ),
]


@pytest.mark.parametrize(
    ("version", "payload", "expected"),
    [("0.8.0", *p) for p in _PICKLES_0_8_0]
    + [("0.10.5", *p) for p in _PICKLES_0_10_5]
    + [("earlier", *p) for p in _PICKLES_EARLIER],
    ids=lambda v: v if isinstance(v, str) else type(v).__name__,
)
def test_reads_pickles_written_by_earlier_releases(
    version: str, payload: bytes, expected: object
):
    with warnings.catch_warnings():
        warnings.simplefilter("error")
        loaded = pickle.loads(payload)

    assert loaded == expected
    if hasattr(expected, "strict_eq"):
        assert loaded.strict_eq(expected)


def test_zoned_pickle_reconciles_changed_offset_rules():
    with warns_here(w.PickleOffsetMismatchWarning) as caught:
        value = getattr(w, "_unpkl_zoned")(
            struct.pack("<HBBBBBil", 2023, 7, 1, 12, 0, 0, 0, 3_600),
            "Europe/Amsterdam",
        )

    assert value.to_instant() == w.Instant.from_utc(2023, 7, 1, 11)
    assert value.to_plain() == w.PlainDateTime(2023, 7, 1, 13)
    assert value.offset == w.TimeDelta(hours=2)
    message = str(caught[0].message)
    assert "Europe/Amsterdam" in message
    assert "pickle stored 2023-07-01 12:00:00 with offset +01:00" in message
    assert "current time zone rules" in message
    assert "instant to 2023-07-01 13:00:00 with offset +02:00" in message
    assert "instant was preserved" in message
    assert "local datetime and offset were updated" in message


def test_zoned_pickle_loads_reconciles_under_changed_rules(tmp_path: Path):
    # The real rules ended DST on October 25, 2020; the week-late file ends
    # it on November 1, so this instant sits in the one week they disagree on.
    original = w.ZonedDateTime(2020, 10, 28, 12, tz="Europe/Amsterdam")
    assert original.offset == w.TimeDelta(hours=1)
    payload = pickle.dumps(original)

    with tz_rules_from_file(
        "Europe/Amsterdam", AMS_TZ_RAWFILE_DST_LATE, tmp_path
    ):
        with warns_here(w.PickleOffsetMismatchWarning) as caught:
            restored = pickle.loads(payload)

    assert restored.to_instant() == original.to_instant()
    assert restored.offset == w.TimeDelta(hours=2)
    assert restored.to_plain() == w.PlainDateTime(2020, 10, 28, 13)
    assert restored.tz_id == "Europe/Amsterdam"
    message = str(caught[0].message)
    assert "stored 2020-10-28 12:00:00 with offset +01:00" in message
    assert "instant to 2020-10-28 13:00:00 with offset +02:00" in message


def test_zoned_pickle_loads_unchanged_rules_do_not_warn():
    original = w.ZonedDateTime(
        2023, 7, 1, 12, nanosecond=123, tz="Europe/Amsterdam"
    )
    with warnings.catch_warnings():
        warnings.simplefilter("error")
        restored = pickle.loads(pickle.dumps(original))

    assert restored.strict_eq(original)


def test_zoned_pickle_unchanged_rules_do_not_warn():
    with warnings.catch_warnings():
        warnings.simplefilter("error")
        value = getattr(w, "_unpkl_zoned")(
            struct.pack("<HBBBBBil", 2023, 7, 1, 12, 0, 0, 123, 7_200),
            "Europe/Amsterdam",
        )

    assert value.strict_eq(
        w.ZonedDateTime(
            2023,
            7,
            1,
            12,
            nanosecond=123,
            tz="Europe/Amsterdam",
        )
    )


@pytest.mark.skipif(
    not w._EXTENSION_LOADED,
    reason="requires both implementations in one process",
)
def test_cross_backend_payloads_and_unpicklers(
    initialized_pure_tz_store: None,
):
    pairs = [
        (w.Date(2024, 2, 29), py.Date(2024, 2, 29)),
        (
            w.Time(3, 4, 5, nanosecond=600_700_800),
            py.Time(3, 4, 5, nanosecond=600_700_800),
        ),
        (
            w.PlainDateTime(2024, 2, 29, 3, 4, 5, nanosecond=600_700_800),
            py.PlainDateTime(2024, 2, 29, 3, 4, 5, nanosecond=600_700_800),
        ),
        (
            w.Instant.from_utc(2024, 2, 29, 3, 4, 5, nanosecond=600_700_800),
            py.Instant.from_utc(2024, 2, 29, 3, 4, 5, nanosecond=600_700_800),
        ),
        (
            w.TimeDelta(seconds=-12_345, nanoseconds=678_901_234),
            py.TimeDelta(seconds=-12_345, nanoseconds=678_901_234),
        ),
        (
            w.OffsetDateTime(
                2024,
                2,
                29,
                3,
                4,
                5,
                nanosecond=600_700_800,
                offset=w.TimeDelta(seconds=-3_723),
            ),
            py.OffsetDateTime(
                2024,
                2,
                29,
                3,
                4,
                5,
                nanosecond=600_700_800,
                offset=py.TimeDelta(seconds=-3_723),
            ),
        ),
        (
            w.ZonedDateTime(
                2024,
                2,
                29,
                3,
                4,
                5,
                nanosecond=600_700_800,
                tz="UTC",
            ),
            py.ZonedDateTime(
                2024,
                2,
                29,
                3,
                4,
                5,
                nanosecond=600_700_800,
                tz="UTC",
            ),
        ),
        (w.Date.MIN, py.Date.MIN),
        (w.Date.MAX, py.Date.MAX),
        (w.Time.MIN, py.Time.MIN),
        (w.Time.MAX, py.Time.MAX),
        (w.PlainDateTime.MIN, py.PlainDateTime.MIN),
        (w.PlainDateTime.MAX, py.PlainDateTime.MAX),
        (w.Instant.MIN, py.Instant.MIN),
        (w.Instant.MAX, py.Instant.MAX),
        (w.TimeDelta.MIN, py.TimeDelta.MIN),
        (w.TimeDelta.MAX, py.TimeDelta.MAX),
    ]

    for rust_value, python_value in pairs:
        rust_unpickler, rust_args = cast(
            _ReduceResult, rust_value.__reduce__()
        )
        python_unpickler, python_args = cast(
            _ReduceResult, python_value.__reduce__()
        )

        assert rust_unpickler.__name__ == python_unpickler.__name__
        assert rust_args == python_args
        assert str(rust_unpickler(*python_args)) == str(rust_value)
        assert str(python_unpickler(*rust_args)) == str(python_value)


@pytest.fixture
def initialized_pure_tz_store() -> Iterator[None]:
    previous = py.get_tzpath()
    py._set_tzpath(w.get_tzpath())
    try:
        yield
    finally:
        py._clear_tz_cache()
        py._set_tzpath(previous)


def test_zoned_unpickle_canonicalizes_timezone_casing(
    initialized_pure_tz_store: None,
):
    data = struct.pack("<HBBBBBil", 2024, 2, 29, 3, 4, 5, 0, 3_600)
    rust_value = getattr(w, "_unpkl_zoned")(data, "europe/amsterdam")
    python_value = py._unpkl_zoned(data, "europe/amsterdam")

    assert rust_value.tz_id == python_value.tz_id == "Europe/Amsterdam"
    assert str(rust_value) == str(python_value)
