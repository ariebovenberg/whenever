"""The binary format: ``to_bytes()`` and ``from_bytes()`` on the seven types
that the C API also handles.
"""

import pickle
import re
import struct
import warnings
from pathlib import Path
from typing import Literal

import pytest
from whenever import (
    Date,
    ImplicitDisambiguationWarning,
    Instant,
    InvalidOffsetError,
    OffsetDateTime,
    PlainDateTime,
    RepeatedTime,
    Time,
    TimeDelta,
    TimeZoneNotFoundError,
    ZonedDateTime,
)

from .common import (
    AMS_TZ_POSIX,
    AMS_TZ_RAWFILE,
    AMS_TZ_RAWFILE_DST_LATE,
    create_zdt,
    tz_rules_from_file,
    warns_here,
)

_AMS = "Europe/Amsterdam"

# The same values as the pickle payload tests, which the bytes are.
WIRE_FORMAT = [
    (Date(2024, 2, 29), struct.pack("<HBB", 2024, 2, 29)),
    (
        Time(3, 4, 5, nanosecond=600_700_800),
        struct.pack("<BBBI", 3, 4, 5, 600_700_800),
    ),
    (
        PlainDateTime(2024, 2, 29, 3, 4, 5, nanosecond=600_700_800),
        struct.pack("<HBBBBBi", 2024, 2, 29, 3, 4, 5, 600_700_800),
    ),
    (
        Instant.from_utc(2024, 2, 29, 3, 4, 5, nanosecond=600_700_800),
        struct.pack("<qL", 1_709_175_845, 600_700_800),
    ),
    (
        TimeDelta(seconds=-12_345, nanoseconds=678_901_234),
        struct.pack("<qI", -12_345, 678_901_234),
    ),
    (
        OffsetDateTime(
            2024,
            2,
            29,
            3,
            4,
            5,
            nanosecond=600_700_800,
            offset=TimeDelta(seconds=-3_723),
        ),
        struct.pack("<HBBBBBil", 2024, 2, 29, 3, 4, 5, 600_700_800, -3_723),
    ),
    (
        ZonedDateTime(2024, 2, 29, 3, 4, 5, nanosecond=600_700_800, tz=_AMS),
        struct.pack("<HBBBBBil", 2024, 2, 29, 3, 4, 5, 600_700_800, 3_600)
        + b"Europe/Amsterdam",
    ),
]

BOUNDARIES = [
    Date.MIN,
    Date.MAX,
    Time.MIN,
    Time.MAX,
    PlainDateTime.MIN,
    PlainDateTime.MAX,
    Instant.MIN,
    Instant.MAX,
    TimeDelta.MIN,
    TimeDelta.MAX,
    OffsetDateTime(1, 1, 1, offset=TimeDelta(seconds=-86_399)),
    OffsetDateTime(9999, 12, 31, 23, 59, 59, offset=TimeDelta(seconds=86_399)),
    ZonedDateTime(1, 1, 1, tz="UTC"),
    ZonedDateTime(9999, 12, 31, 23, 59, 59, tz="UTC"),
]


def _type_name(value: object) -> str:
    return type(value).__name__


@pytest.mark.parametrize(("value", "payload"), WIRE_FORMAT, ids=_type_name)
def test_to_bytes_matches_wire_format(value, payload):
    assert value.to_bytes() == payload


@pytest.mark.parametrize(
    "value", [v for v, _ in WIRE_FORMAT] + BOUNDARIES, ids=_type_name
)
def test_round_trip(value):
    restored = type(value).from_bytes(value.to_bytes())
    assert restored == value
    if isinstance(value, ZonedDateTime):
        assert restored.strict_eq(value)


@pytest.mark.parametrize("value", [v for v, _ in WIRE_FORMAT], ids=_type_name)
def test_same_bytes_as_pickle(value):
    """The bytes are the pickle payload, so a reader of one reads the other."""
    payload = value.__reduce__()[1][0]
    if isinstance(value, ZonedDateTime):
        assert value.tz_id is not None
        assert value.to_bytes() == payload + value.tz_id.encode()
    else:
        assert value.to_bytes() == payload
    assert pickle.loads(pickle.dumps(value)) == value


def test_from_bytes_accepts_bytes_subclass():
    class Bytes(bytes):
        pass

    assert Date.from_bytes(Bytes(struct.pack("<HBB", 2024, 2, 29))) == Date(
        2024, 2, 29
    )


@pytest.mark.parametrize(
    "cls",
    [
        Date,
        Time,
        PlainDateTime,
        Instant,
        TimeDelta,
        OffsetDateTime,
        ZonedDateTime,
    ],
)
@pytest.mark.parametrize(
    "data",
    [
        "2024-02-29",
        bytearray(b"\xe8\x07\x02\x1d"),
        memoryview(b"\xe8\x07\x02\x1d"),
    ],
    ids=_type_name,
)
def test_from_bytes_rejects_non_bytes(cls, data):
    with pytest.raises(TypeError, match="expected bytes argument"):
        cls.from_bytes(data)


@pytest.mark.parametrize(
    ("cls", "data"),
    [
        (Date, struct.pack("<HBB", 0, 1, 1)),
        (Date, struct.pack("<HBB", 2024, 13, 1)),
        (Date, struct.pack("<HBB", 2024, 2, 30)),
        (Time, struct.pack("<BBBI", 24, 0, 0, 0)),
        (Time, struct.pack("<BBBI", 0, 60, 0, 0)),
        (Time, struct.pack("<BBBI", 0, 0, 60, 0)),
        (Time, struct.pack("<BBBI", 0, 0, 0, 1_000_000_000)),
        (PlainDateTime, struct.pack("<HBBBBBi", 2024, 2, 30, 0, 0, 0, 0)),
        (
            PlainDateTime,
            struct.pack("<HBBBBBi", 2024, 2, 29, 0, 0, 0, 1_000_000_000),
        ),
        (PlainDateTime, struct.pack("<HBBBBBi", 2024, 2, 29, 0, 0, 0, -1)),
        (Instant, struct.pack("<qL", -62_135_596_801, 0)),
        (Instant, struct.pack("<qL", 253_402_300_800, 0)),
        (Instant, struct.pack("<qL", 0, 1_000_000_000)),
        (TimeDelta, struct.pack("<qI", 9999 * 366 * 24 * 3_600, 1)),
        (TimeDelta, struct.pack("<qI", 0, 1_000_000_000)),
        (
            OffsetDateTime,
            struct.pack("<HBBBBBil", 2024, 1, 1, 0, 0, 0, 0, 86_400),
        ),
        (OffsetDateTime, struct.pack("<HBBBBBil", 1, 1, 1, 0, 0, 0, 0, 1)),
        (
            ZonedDateTime,
            struct.pack("<HBBBBBil", 2024, 1, 1, 0, 0, 0, 1_000_000_000, 0)
            + b"UTC",
        ),
        (
            ZonedDateTime,
            struct.pack("<HBBBBBil", 2024, 1, 1, 0, 0, 0, 0, 86_400) + b"UTC",
        ),
        (
            ZonedDateTime,
            struct.pack("<HBBBBBil", 2024, 1, 1, 0, 0, 0, -1, 0) + b"UTC",
        ),
        (
            ZonedDateTime,
            struct.pack("<HBBBBBil", 1, 1, 1, 0, 0, 0, 0, 1) + b"UTC",
        ),
        # a time zone ID that is not text
        (
            ZonedDateTime,
            struct.pack("<HBBBBBil", 2024, 1, 1, 0, 0, 0, 0, 0)
            + b"Europe/\xff",
        ),
    ],
)
def test_malformed_payload_is_rejected(cls, data):
    with pytest.raises(
        ValueError,
        match=f"^invalid bytes for {cls.__name__}: {re.escape(repr(data))}$",
    ):
        cls.from_bytes(data)


@pytest.mark.parametrize(
    ("cls", "size"),
    [
        (Date, 4),
        (Time, 7),
        (PlainDateTime, 11),
        (Instant, 12),
        (TimeDelta, 12),
        (OffsetDateTime, 15),
        (ZonedDateTime, 15),
    ],
)
def test_wrong_payload_length_is_rejected(cls, size):
    for data in (bytes(size - 1), bytes(size + 1)):
        with pytest.raises(ValueError, match="invalid bytes"):
            cls.from_bytes(data)


class TestZonedDateTime:
    def test_tz_id_takes_the_database_spelling(self):
        data = struct.pack("<HBBBBBil", 2024, 7, 1, 12, 0, 0, 0, 7_200)
        result = ZonedDateTime.from_bytes(data + b"europe/amsterdam")
        assert result.tz_id == "Europe/Amsterdam"
        assert result.to_bytes() == data + b"Europe/Amsterdam"

    @pytest.mark.parametrize(
        "tz_id", [b"", b"Nowhere/Nope", b"../UTC", "Europe/Zürich".encode()]
    )
    def test_unknown_tz_id(self, tz_id):
        data = struct.pack("<HBBBBBil", 2024, 7, 1, 12, 0, 0, 0, 7_200)
        with pytest.raises(TimeZoneNotFoundError):
            ZonedDateTime.from_bytes(data + tz_id)

    @pytest.mark.parametrize("tz", [AMS_TZ_POSIX, AMS_TZ_RAWFILE])
    def test_no_tz_id(self, tz):
        d = create_zdt(2023, 12, 3, 9, 15, tz=tz)
        with pytest.raises(
            ValueError,
            match="cannot convert a ZonedDateTime without a time zone ID",
        ):
            d.to_bytes()

    @pytest.mark.parametrize("which", ["earlier", "later"])
    def test_repeated_time_identified_by_its_offset(
        self, which: Literal["earlier", "later"]
    ):
        d = ZonedDateTime(2023, 10, 29, 2, 30, tz=_AMS, disambiguation=which)
        with warnings.catch_warnings():
            warnings.simplefilter("error", ImplicitDisambiguationWarning)
            # No policy is consulted: the offset already picks an occurrence
            restored = ZonedDateTime.from_bytes(
                d.to_bytes(), disambiguation="raise"
            )
        assert restored.strict_eq(d)

    # A payload written under rules that end DST a week later than the
    # installed ones: its offset identifies no occurrence of the local time.
    @pytest.fixture()
    def stale(self, tmp_path: Path) -> bytes:
        with tz_rules_from_file(_AMS, AMS_TZ_RAWFILE_DST_LATE, tmp_path):
            return ZonedDateTime(2020, 10, 28, 12, tz=_AMS).to_bytes()

    @pytest.mark.parametrize("kwargs", [{}, {"offset_mismatch": "raise"}])
    def test_mismatch_raises_by_default(self, stale, kwargs):
        with pytest.raises(InvalidOffsetError, match="Europe/Amsterdam"):
            ZonedDateTime.from_bytes(stale, **kwargs)

    def test_mismatch_keep_instant(self, stale):
        result = ZonedDateTime.from_bytes(
            stale, offset_mismatch="keep_instant"
        )
        assert result.strict_eq(ZonedDateTime(2020, 10, 28, 11, tz=_AMS))

    def test_mismatch_keep_local(self, stale):
        with warnings.catch_warnings():
            warnings.simplefilter("error", ImplicitDisambiguationWarning)
            result = ZonedDateTime.from_bytes(
                stale, offset_mismatch="keep_local"
            )
        assert result.strict_eq(ZonedDateTime(2020, 10, 28, 12, tz=_AMS))

    # A repeated local time, written with an offset that matches neither
    # occurrence: keeping the local time needs a policy.
    stale_repeated = (
        struct.pack("<HBBBBBil", 2020, 10, 25, 2, 30, 0, 0, 0)
        + b"Europe/Amsterdam"
    )

    def test_mismatch_keep_local_consults_disambiguation(self):
        stale_repeated = self.stale_repeated
        with warns_here(ImplicitDisambiguationWarning):
            result = ZonedDateTime.from_bytes(
                stale_repeated, offset_mismatch="keep_local"
            )
        assert result.strict_eq(
            ZonedDateTime(
                2020, 10, 25, 2, 30, tz=_AMS, disambiguation="earlier"
            )
        )
        later = ZonedDateTime.from_bytes(
            stale_repeated,
            offset_mismatch="keep_local",
            disambiguation="later",
        )
        assert later.strict_eq(
            ZonedDateTime(2020, 10, 25, 2, 30, tz=_AMS, disambiguation="later")
        )
        with pytest.raises(RepeatedTime):
            ZonedDateTime.from_bytes(
                stale_repeated,
                offset_mismatch="keep_local",
                disambiguation="raise",
            )

    def test_invalid_policies(self):
        data = ZonedDateTime(2024, 7, 1, tz=_AMS).to_bytes()
        with pytest.raises(ValueError, match="offset_mismatch"):
            ZonedDateTime.from_bytes(data, offset_mismatch="keep")  # type: ignore[arg-type]
        with pytest.raises(ValueError, match="disambiguation"):
            ZonedDateTime.from_bytes(data, disambiguation="later!")  # type: ignore[arg-type]
        with pytest.raises(TypeError):
            ZonedDateTime.from_bytes(data, "raise")  # type: ignore[call-arg]
        with pytest.raises(TypeError):
            ZonedDateTime.from_bytes(data, tz=_AMS)  # type: ignore[call-arg]
