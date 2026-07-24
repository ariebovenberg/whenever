import struct

import pytest
import whenever as w
from whenever import _pywhenever as py


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
    ],
)
def test_payload_matches_wire_format(value: object, payload: bytes):
    assert value.__reduce__()[1][0] == payload  # type: ignore[attr-defined]


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
    assert value.__reduce__()[1][0] == payload  # type: ignore[attr-defined]


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
        ("_unpkl_inst", (struct.pack("<qL", -62_135_596_801, 0),)),
        ("_unpkl_inst", (struct.pack("<qL", 253_402_300_800, 0),)),
        ("_unpkl_inst", (struct.pack("<qL", 0, 1_000_000_000),)),
        (
            "_unpkl_tdelta",
            (struct.pack("<qI", 9999 * 366 * 24 * 3_600, 1),),
        ),
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
                struct.pack("<HBBBBBil", 2024, 1, 1, 0, 0, 0, 0, 86_400),
                "UTC",
            ),
        ),
    ],
)
def test_malformed_payload_is_rejected(name: str, args: tuple[object, ...]):
    with pytest.raises((TypeError, ValueError, OverflowError, struct.error)):
        getattr(w, name)(*args)


@pytest.mark.parametrize(
    ("name", "size"),
    [
        ("_unpkl_date", 4),
        ("_unpkl_time", 7),
        ("_unpkl_local", 11),
        ("_unpkl_inst", 12),
        ("_unpkl_tdelta", 12),
        ("_unpkl_offset", 15),
    ],
)
def test_wrong_payload_length_is_rejected(name: str, size: int):
    unpickle = getattr(w, name)
    for data in (bytes(size - 1), bytes(size + 1)):
        with pytest.raises((TypeError, ValueError, struct.error)):
            unpickle(data)


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


def test_zoned_pickle_preserves_stored_offset():
    value = w._unpkl_zoned(
        struct.pack("<HBBBBBil", 2023, 7, 1, 12, 0, 0, 0, 3_600),
        "Europe/Amsterdam",
    )

    assert value.offset == w.TimeDelta(hours=1)


@pytest.mark.skipif(
    not w._EXTENSION_LOADED,
    reason="requires both implementations in one process",
)
def test_cross_backend_payloads_and_unpicklers():
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
        rust_unpickler, rust_args = rust_value.__reduce__()
        python_unpickler, python_args = python_value.__reduce__()

        assert rust_unpickler.__name__ == python_unpickler.__name__
        assert rust_args == python_args
        assert str(rust_unpickler(*python_args)) == str(rust_value)
        assert str(python_unpickler(*rust_args)) == str(python_value)
