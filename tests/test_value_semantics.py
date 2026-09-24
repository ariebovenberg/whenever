"""The contracts every value type shares, each stated once over every type."""

import pickle
from copy import copy, deepcopy
from datetime import (
    date as py_date,
    datetime as py_datetime,
    time as py_time,
    timedelta as py_timedelta,
    timezone as py_timezone,
)

import pytest
from whenever import (
    FRIDAY,
    MONDAY,
    SYSTEM_TZ,
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
    Weekday,
    YearMonth,
    ZonedDateTime,
    hours,
)

from .common import (
    ALL_TYPES,
    SAMPLE_VALUES,
    AlwaysEqual,
    AlwaysLarger,
    AlwaysSmaller,
    Idx,
    NeverEqual,
    type_name,
)

# Beyond the sample values: the edges of each range, a week 53, and itemized
# deltas with negative and zero components (their payload keeps the sign).
_MORE_VALUES = [
    *(cls.MIN for cls in ALL_TYPES if hasattr(cls, "MIN")),
    *(cls.MAX for cls in ALL_TYPES if hasattr(cls, "MAX")),
    IsoWeekDate(2004, 53, FRIDAY),
    ItemizedDelta(
        years=1,
        months=2,
        weeks=3,
        days=4,
        hours=5,
        minutes=6,
        seconds=7,
        nanoseconds=8,
    ),
    ItemizedDelta(days=-5, hours=-3),
    ItemizedDelta(days=-5, nanoseconds=0),
    ItemizedDateDelta(years=1, months=2, weeks=3, days=4),
    ItemizedDateDelta(days=-5, months=-3),
    ItemizedDateDelta(days=-5, weeks=0),
]

# The same three instants in each type of the exact family: 01:14, 01:15 and
# 01:16 UTC on 2023-10-29, while Paris repeats its 02:00 hour.
_EXACT_FAMILY = [
    [Instant.from_utc(2023, 10, 29, 1, m) for m in (14, 15, 16)],
    [
        OffsetDateTime(2023, 10, 29, 5, m, offset=hours(4))
        for m in (14, 15, 16)
    ],
    [
        ZonedDateTime(
            2023, 10, 29, 2, m, tz="Europe/Paris", disambiguation="later"
        )
        for m in (14, 15, 16)
    ],
]


@pytest.mark.parametrize("value", SAMPLE_VALUES + _MORE_VALUES, ids=type_name)
def test_pickle_round_trip(value):
    dumped = pickle.dumps(value)
    # a compact payload, read by a public name of the package on both backends
    assert len(dumped) < 100
    assert value.__reduce__()[0].__module__ == "whenever"
    assert b"whenever._" not in dumped
    loaded = pickle.loads(dumped)
    assert loaded == value
    if hasattr(value, "strict_eq"):
        assert loaded.strict_eq(value)


@pytest.mark.parametrize(
    "value", SAMPLE_VALUES + [Weekday.MONDAY, SYSTEM_TZ], ids=type_name
)
def test_copies_are_the_value(value: object):
    assert copy(value) is value and deepcopy(value) is value


@pytest.mark.parametrize("value", SAMPLE_VALUES, ids=type_name)
def test_immutable(value):
    with pytest.raises(AttributeError):
        value.foo = 1


@pytest.mark.parametrize("value", SAMPLE_VALUES, ids=type_name)
def test_equality_defers_to_the_other_operand(value):
    assert value == AlwaysEqual()
    assert AlwaysEqual() == value
    assert not value != AlwaysEqual()
    assert not AlwaysEqual() != value
    assert value != NeverEqual()
    assert NeverEqual() != value
    assert not value == NeverEqual()
    assert not NeverEqual() == value
    # ...and is False once neither side has an answer
    assert not value == 3
    assert value != 3
    assert not 3 == value
    assert 3 != value
    assert not value == None  # noqa: E711
    assert value != None  # noqa: E711
    assert not None == value  # noqa: E711
    assert None != value  # noqa: E711


@pytest.mark.parametrize("value", SAMPLE_VALUES, ids=type_name)
def test_ordering_defers_to_the_other_operand(value):
    assert value < AlwaysLarger()
    assert value <= AlwaysLarger()
    assert not value > AlwaysLarger()
    assert not value >= AlwaysLarger()
    assert not value < AlwaysSmaller()
    assert not value <= AlwaysSmaller()
    assert value > AlwaysSmaller()
    assert value >= AlwaysSmaller()


# One pair per type that has ``strict_eq()``: ``a == b`` holds, while
# ``a.strict_eq(b)`` does not. A cross-type pair raises instead of returning
# ``False``, which is also a way of not holding.
EQUAL_BUT_NOT_STRICTLY_EQUAL = [
    (
        Instant.from_utc(2020, 8, 15, 10),
        OffsetDateTime(2020, 8, 15, 12, offset=hours(2)),
    ),
    (
        OffsetDateTime(2020, 8, 15, 12, offset=hours(2)),
        OffsetDateTime(2020, 8, 15, 13, offset=hours(3)),
    ),
    (
        ZonedDateTime(2020, 8, 15, 12, tz="Europe/Amsterdam"),
        ZonedDateTime(2020, 8, 15, 6, tz="America/New_York"),
    ),
    (
        ItemizedDelta(weeks=2, hours=3),
        ItemizedDelta(weeks=2, hours=3, months=0),
    ),
    (
        ItemizedDateDelta(weeks=2, days=3),
        ItemizedDateDelta(weeks=2, days=3, months=0),
    ),
]


class TestCrossTypeComparison:
    """Outside the exact family, values of different types are never equal
    and never order; the same holds against the standard library."""

    @pytest.mark.parametrize(
        "a, b",
        [
            (Date(2020, 1, 1), PlainDateTime(2020, 1, 1)),
            (Time(), Date(2020, 1, 1)),
            (TimeDelta(hours=1), ItemizedDelta(hours=1)),
            (ItemizedDelta(days=1), ItemizedDateDelta(days=1)),
            (Instant.from_utc(2020, 1, 1), PlainDateTime(2020, 1, 1)),
            (ItemizedDelta(hours=1), {"hours": 1}),
            (Date(2020, 1, 1), py_date(2020, 1, 1)),
            (Time(), py_time()),
            (TimeDelta(hours=1), py_timedelta(hours=1)),
            (
                Instant.from_utc(2020, 1, 1),
                py_datetime(2020, 1, 1, tzinfo=py_timezone.utc),
            ),
            (PlainDateTime(2020, 1, 1), py_datetime(2020, 1, 1)),
        ],
    )
    def test_never_equal_never_ordered(self, a, b):
        assert not a == b
        assert a != b
        assert not b == a
        assert b != a
        with pytest.raises(TypeError):
            a < b
        with pytest.raises(TypeError):
            b < a

    @pytest.mark.parametrize("a", _EXACT_FAMILY, ids=lambda v: type_name(v[1]))
    @pytest.mark.parametrize("b", _EXACT_FAMILY, ids=lambda v: type_name(v[1]))
    def test_exact_family_compares_by_instant(self, a, b):
        value = a[1]
        earlier, same, later = b
        assert value == same and not value != same
        assert hash(value) == hash(same)
        assert value != earlier and not value == earlier
        assert value <= same and value >= same
        assert not value < same and not value > same
        assert value < later and value <= later
        assert not value > later and not value >= later
        assert value > earlier and value >= earlier
        assert not value < earlier and not value <= earlier
        if type(value) is not type(same):
            with pytest.raises(
                TypeError,
                match=rf"^strict_eq\(\) argument must be an? {type_name(value)}$",
            ):
                value.strict_eq(same)

    def test_exact_family_equality_is_flagged_by_the_type_checker(self):
        # mypy's strict equality treats the types as disjoint, so each of
        # these needs its ignore: warn_unused_ignores fails if that changes
        inst = Instant.from_utc(2020, 8, 15)
        assert inst == inst.to_fixed_offset(hours(4))  # type: ignore[comparison-overlap]
        assert inst == inst.to_tz("Europe/Paris")  # type: ignore[comparison-overlap]
        offset = inst.to_fixed_offset(hours(4))
        assert offset == offset.to_tz("Europe/Paris")  # type: ignore[comparison-overlap]


@pytest.mark.parametrize("a, b", EQUAL_BUT_NOT_STRICTLY_EQUAL)
def test_strict_eq_refines_eq(a, b):
    # the law: strict_eq() implies ==
    assert a.strict_eq(a) and a == a
    assert b.strict_eq(b) and b == b
    # ...and never the converse
    assert a == b
    if type(a) is type(b):
        assert not a.strict_eq(b)
        assert not b.strict_eq(a)
    else:
        with pytest.raises(TypeError, match="argument must be"):
            a.strict_eq(b)


@pytest.mark.parametrize(
    "value",
    [
        Date(2024, 2, 29),
        Time(12, 30, nanosecond=1),
        YearMonth(2024, 2),
        MonthDay(2, 29),
        IsoWeekDate(2024, 9, MONDAY),
        PlainDateTime(2024, 2, 29, 12, 30),
        OffsetDateTime(2024, 2, 29, 12, 30, offset=hours(2)),
        ZonedDateTime(2024, 2, 29, 12, 30, tz="Europe/Paris"),
        ItemizedDelta(years=1, hours=2),
        ItemizedDateDelta(years=1, days=2),
    ],
)
def test_replace_contract(value):
    """The contract every ``replace()`` shares: no arguments gives an equal
    value, and both a positional argument and an unknown keyword raise."""
    kwargs = (
        {"stale_offset_ok": True} if isinstance(value, OffsetDateTime) else {}
    )
    same = value.replace(**kwargs)
    if isinstance(value, (ItemizedDelta, ItemizedDateDelta)):
        assert same.strict_eq(value)
    else:
        assert same == value
    with pytest.raises(TypeError):
        value.replace(1, **kwargs)
    with pytest.raises(TypeError, match="foo"):
        value.replace(foo=1, **kwargs)


@pytest.mark.parametrize(
    "call",
    [
        lambda n: Date(2024, 1, 1).replace(day=n),
        lambda n: Time(12).replace(minute=n),
        lambda n: PlainDateTime(2024, 1, 1).replace(hour=n),
        lambda n: OffsetDateTime(2024, 1, 1, offset=hours(2)).replace(
            day=n, stale_offset_ok=True
        ),
        lambda n: ZonedDateTime(2024, 1, 1, tz="Europe/Paris").replace(
            month=n
        ),
        lambda n: YearMonth(2024, 1).on_day(n),
        lambda n: MonthDay(1, 1).in_year(n),
        lambda n: IsoWeekDate(2024, n, MONDAY),
        lambda n: Date(2024, 1, 1).nth_weekday(n, MONDAY),
        lambda n: Date(2024, 1, 1).add(days=n),
        lambda n: YearMonth(2024, 1).add(months=n),
        lambda n: Instant.from_utc(2024, 1, 1).add(nanoseconds=n),
        lambda n: OffsetDateTime(2024, 1, 1, offset=hours(2)).subtract(
            weeks=n, stale_offset_ok=True
        ),
        lambda n: ZonedDateTime(2024, 1, 1, tz="Europe/Paris").add(years=n),
        lambda n: PlainDateTime(2024, 1, 1).add(months=n),
    ],
)
def test_integer_keywords_read_the_index_protocol(call):
    assert call(Idx()) == call(5)


_Z = ZonedDateTime(2020, 1, 1, tz="Europe/Paris")
_O = OffsetDateTime(2020, 1, 1, offset=hours(1))
_P = PlainDateTime(2020, 1, 1)


# A wrong operand is named by its expected type, not by what it lacks
@pytest.mark.parametrize(
    "call, message",
    [
        (
            lambda x: Date(2020, 1, 1).since(x, total="days"),
            r"since\(\) argument must be a Date",
        ),
        (
            lambda x: Date(2020, 1, 1).until(x, total="days"),
            r"until\(\) argument must be a Date",
        ),
        (lambda x: Date(2020, 1, 1).at(x), r"at\(\) argument must be a Time"),
        (lambda x: Time(12).on(x), r"on\(\) argument must be a Date"),
        (
            lambda x: _P.replace_date(x),
            r"replace_date\(\) argument must be a Date",
        ),
        (
            lambda x: _P.replace_time(x),
            r"replace_time\(\) argument must be a Time",
        ),
        (
            lambda x: _O.replace_date(x),
            r"replace_date\(\) argument must be a Date",
        ),
        (
            lambda x: _O.replace_time(x),
            r"replace_time\(\) argument must be a Time",
        ),
        (
            lambda x: _Z.replace_date(x),
            r"replace_date\(\) argument must be a Date",
        ),
        (
            lambda x: _Z.replace_time(x),
            r"replace_time\(\) argument must be a Time",
        ),
    ],
)
@pytest.mark.parametrize("operand", [None, 3, _P])
def test_wrong_operand_names_the_expected_type(call, message, operand):
    with pytest.raises(TypeError, match=f"^{message}$"):
        call(operand)


@pytest.mark.parametrize(
    "value",
    [
        Date(2020, 1, 1),
        Time(12),
        PlainDateTime(2020, 1, 1),
        OffsetDateTime(2020, 1, 1, offset=hours(1)),
    ],
    ids=type_name,
)
@pytest.mark.parametrize("convert", [str, lambda v: v.to_stdlib()])
def test_single_argument_rejects_a_keyword(value, convert):
    with pytest.raises(
        TypeError, match=r"\(\) got an unexpected keyword argument 'foo'$"
    ):
        type(value)(convert(value), foo=1)


@pytest.mark.parametrize("cls", ALL_TYPES, ids=lambda c: c.__name__)
def test_types_are_final(cls):
    with pytest.raises(
        TypeError,
        match=f"type 'whenever.{cls.__name__}' is not an acceptable base type",
    ):
        type("Sub", (cls,), {})


@pytest.mark.parametrize("value", SAMPLE_VALUES, ids=type_name)
def test_value_types_have_no_dict(value):
    # slotscheck can't check this: the lazy module __getattr__ hides
    # the classes from it
    assert not hasattr(value, "__dict__")
