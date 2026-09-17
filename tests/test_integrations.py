import json
import sys

import pytest
from whenever import (
    Date,
    Instant,
    IsoWeekDate,
    ItemizedDateDelta,
    ItemizedDelta,
    MonthDay,
    OffsetDateTime,
    PlainDateTime,
    Time,
    TimeDelta,
    YearMonth,
    ZonedDateTime,
)

from .common import StrSubclass


@pytest.mark.skipif(
    sys.implementation.name == "pypy",
    reason="time-machine doesn't support PyPy",
)
def test_time_machine():
    time_machine = pytest.importorskip("time_machine")

    with time_machine.travel("1980-03-02T02:00+00:00"):
        assert Instant.now() == Instant.from_utc(1980, 3, 2, hour=2)


@pytest.mark.parametrize(
    "value, invalid_iso",
    [
        (Date(2020, 8, 15), "2020-13-15"),
        (YearMonth(2020, 8), "2020-13"),
        (MonthDay(8, 15), "--13-15"),
        (IsoWeekDate("2020-W33-6"), "2020-W54-1"),
        (Time(12, 30, 45), "25:30:45"),
        (PlainDateTime(2020, 8, 15, 12, 30), "2020-08-15T25:30"),
        (Instant("2020-08-15T12:30Z"), "2020-08-15T12:30"),
        (
            OffsetDateTime("2020-08-15T12:30+02:00"),
            "2020-08-15T12:30",
        ),
        (
            ZonedDateTime("2020-08-15T12:30+02:00[Europe/Amsterdam]"),
            "2020-08-15T12:30+03:00[Europe/Amsterdam]",
        ),
        (TimeDelta("PT2H30M"), "P1M"),
        (ItemizedDateDelta("P1Y2M"), "PT1H"),
        (ItemizedDelta("P1Y2MT3H"), "invalid"),
    ],
)
def test_pydantic(value, invalid_iso):
    pydantic = pytest.importorskip("pydantic")
    adapter = pydantic.TypeAdapter(type(value))
    serialized = json.dumps(str(value), separators=(",", ":"))

    assert adapter.validate_python(value) is value
    assert adapter.validate_python(str(value)) == value
    assert adapter.validate_python(StrSubclass(str(value))) == value
    assert adapter.validate_json(serialized) == value
    assert adapter.dump_json(value) == serialized.encode()
    with pytest.raises(
        pydantic.ValidationError,
        match=f"cannot parse {type(value).__name__} from type int",
    ):
        adapter.validate_python(42)
    with pytest.raises(pydantic.ValidationError):
        adapter.validate_python(invalid_iso)
    assert adapter.json_schema()["type"] == "string"
