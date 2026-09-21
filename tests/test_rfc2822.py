import re

import pytest
from whenever import (
    Instant,
    OffsetDateTime,
    hours,
    minutes,
    seconds,
)


@pytest.mark.parametrize(
    "d, expected",
    [
        (
            OffsetDateTime(
                2020,
                8,
                15,
                23,
                12,
                9,
                nanosecond=450,
                offset=hours(5),
            ),
            "Sat, 15 Aug 2020 23:12:09 +0500",
        ),
        (
            OffsetDateTime(2020, 8, 5, 23, 12, 9, offset=hours(5)),
            "Wed, 05 Aug 2020 23:12:09 +0500",
        ),
        (
            OffsetDateTime(1, 1, 1, 9, 9, 9, offset=minutes(1)),
            "Mon, 01 Jan 0001 09:09:09 +0001",
        ),
        (
            OffsetDateTime(
                2020,
                8,
                15,
                23,
                12,
                9,
                offset=hours(5) + minutes(22) + seconds(45),
            ),
            "Sat, 15 Aug 2020 23:12:09 +0522",
        ),
        (
            OffsetDateTime(
                2020,
                8,
                15,
                23,
                12,
                9,
                offset=-(hours(5) + minutes(22) + seconds(45)),
            ),
            "Sat, 15 Aug 2020 23:12:09 -0522",
        ),
    ],
)
def test_format_offset_datetime(d, expected):
    assert d.format_rfc2822() == expected


VALID_RFC2822 = [
    (
        "Sat, 15 Aug 2020 23:12:09 GMT",
        OffsetDateTime(2020, 8, 15, 23, 12, 9, offset=hours(0)),
    ),
    (
        "Sat, 15 Aug 2020 23:12:09 +0000",
        OffsetDateTime(2020, 8, 15, 23, 12, 9, offset=hours(0)),
    ),
    (
        "Sat, 1 Aug 2020 23:12:09 +0000",
        OffsetDateTime(2020, 8, 1, 23, 12, 9, offset=hours(0)),
    ),
    (
        "Sat, 01 Aug 2020 23:12:09 +0000",
        OffsetDateTime(2020, 8, 1, 23, 12, 9, offset=hours(0)),
    ),
    (
        "Sat, 15 Aug 2020 23:12:09 -0000",
        OffsetDateTime(2020, 8, 15, 23, 12, 9, offset=hours(0)),
    ),
    (
        "Sat, 15 Aug 2020 23:12:09 UTC",
        OffsetDateTime(2020, 8, 15, 23, 12, 9, offset=hours(0)),
    ),
    (
        "Sat, 15 Aug 2020 23:12:09 -0100",
        OffsetDateTime(2020, 8, 15, 23, 12, 9, offset=hours(-1)),
    ),
    (
        "Sat, 15 Aug 2020 23:12:09 +1200",
        OffsetDateTime(2020, 8, 15, 23, 12, 9, offset=hours(12)),
    ),
    (
        "Sun, 2 Aug 2020 23:12:09 +0000",
        OffsetDateTime(2020, 8, 2, 23, 12, 9, offset=hours(0)),
    ),
    (
        "Mon, 3 Aug 2020 23:12:09 +0000",
        OffsetDateTime(2020, 8, 3, 23, 12, 9, offset=hours(0)),
    ),
    (
        "Tue, 4 Aug 2020 23:12:09 +0000",
        OffsetDateTime(2020, 8, 4, 23, 12, 9, offset=hours(0)),
    ),
    (
        "Wed, 5 Aug 2020 23:12:09 +0000",
        OffsetDateTime(2020, 8, 5, 23, 12, 9, offset=hours(0)),
    ),
    (
        "Thu, 6 Aug 2020 23:12:09 +0000",
        OffsetDateTime(2020, 8, 6, 23, 12, 9, offset=hours(0)),
    ),
    (
        "Fri, 7 Aug 2020 23:12:09 +0000",
        OffsetDateTime(2020, 8, 7, 23, 12, 9, offset=hours(0)),
    ),
    (
        "7 Jan 2020 23:12:09 +0000",
        OffsetDateTime(2020, 1, 7, 23, 12, 9, offset=hours(0)),
    ),
    (
        "7 Feb 2020 23:12:09 +0000",
        OffsetDateTime(2020, 2, 7, 23, 12, 9, offset=hours(0)),
    ),
    (
        "7 Mar 2020 23:12:09 +0000",
        OffsetDateTime(2020, 3, 7, 23, 12, 9, offset=hours(0)),
    ),
    (
        "7 Apr 2020 23:12:09 +0000",
        OffsetDateTime(2020, 4, 7, 23, 12, 9, offset=hours(0)),
    ),
    (
        "7 May 2020 23:12:09 +0000",
        OffsetDateTime(2020, 5, 7, 23, 12, 9, offset=hours(0)),
    ),
    (
        "7 Jun 2020 23:12:09 +0000",
        OffsetDateTime(2020, 6, 7, 23, 12, 9, offset=hours(0)),
    ),
    (
        "7 Jul 2020 23:12:09 +0000",
        OffsetDateTime(2020, 7, 7, 23, 12, 9, offset=hours(0)),
    ),
    (
        "7 Sep 2020 23:12:09 +0000",
        OffsetDateTime(2020, 9, 7, 23, 12, 9, offset=hours(0)),
    ),
    (
        "7 Oct 2020 23:12:09 +0000",
        OffsetDateTime(2020, 10, 7, 23, 12, 9, offset=hours(0)),
    ),
    (
        "7 Nov 2020 23:12:09 +0000",
        OffsetDateTime(2020, 11, 7, 23, 12, 9, offset=hours(0)),
    ),
    (
        "7 Dec 2020 23:12:09 +0000",
        OffsetDateTime(2020, 12, 7, 23, 12, 9, offset=hours(0)),
    ),
    # named time zones
    (
        "Sat, 15 Aug 2020 23:12:09 MST",
        OffsetDateTime(2020, 8, 15, 23, 12, 9, offset=hours(-7)),
    ),
    # non-4-digit years
    (
        "Sun, 15 Aug 49 23:12:09 +1200",
        OffsetDateTime(2000 + 49, 8, 15, 23, 12, 9, offset=hours(12)),
    ),
    (
        "Tue, 15 Aug 50 23:12:09 +1200",
        OffsetDateTime(1900 + 50, 8, 15, 23, 12, 9, offset=hours(12)),
    ),
    (
        "Mon, 15 Aug 049 23:12:09 +1200",
        OffsetDateTime(1900 + 49, 8, 15, 23, 12, 9, offset=hours(12)),
    ),
    (
        "Thu, 15 Aug 220 23:12:09 +1200",
        OffsetDateTime(1900 + 220, 8, 15, 23, 12, 9, offset=hours(12)),
    ),
    # various whitespace is allowed
    (
        "   15      Aug 2020\r\n  \r\n23:12 \t UTC   ",
        OffsetDateTime(2020, 8, 15, 23, 12, offset=hours(0)),
    ),
    (
        "Sat\t, 15 Aug 2020 23:12:09 MST",
        OffsetDateTime(2020, 8, 15, 23, 12, 9, offset=hours(-7)),
    ),
    (
        "Sat, 15 Aug 2020 23 :12 : 09 MST",
        OffsetDateTime(2020, 8, 15, 23, 12, 9, offset=hours(-7)),
    ),
    (
        "Sat, 15 Aug 2020 23: \t12:09\nMST",
        OffsetDateTime(2020, 8, 15, 23, 12, 9, offset=hours(-7)),
    ),
    (
        "Sat,15 Aug 2020 23:12:09 MST",
        OffsetDateTime(2020, 8, 15, 23, 12, 9, offset=hours(-7)),
    ),
    (
        "Sat   ,15 Aug 2020 23:12:09 MST",
        OffsetDateTime(2020, 8, 15, 23, 12, 9, offset=hours(-7)),
    ),
    # technically not valid whitespace, but we accept it
    (
        "Sat\t,\n\r15 Aug 2020 23:\x0b\t12\x0c:09\nMST",
        OffsetDateTime(2020, 8, 15, 23, 12, 9, offset=hours(-7)),
    ),
    # According to the spec, unknown time zones should be interpreted as -0000.
    (
        "15 Aug 2020  23:12 FOO",
        OffsetDateTime(2020, 8, 15, 23, 12, offset=hours(0)),
    ),
    (
        "15 Aug 2020  23:12 a",
        OffsetDateTime(2020, 8, 15, 23, 12, offset=hours(0)),
    ),
    # Case insensitive
    (
        "TUe, 15 auG 1950 23:12:09 MsT",
        OffsetDateTime(1950, 8, 15, 23, 12, 9, offset=hours(-7)),
    ),
    # minimal required
    (
        "5 Aug 20 23:12 UT",
        OffsetDateTime(2020, 8, 5, 23, 12, offset=hours(0)),
    ),
    # Leap second normalization (60 -> 59)
    (
        "Sat, 31 Dec 2016 23:59:60 +0000",
        OffsetDateTime(2016, 12, 31, 23, 59, 59, offset=hours(0)),
    ),
]

INVALID_RFC2822 = [
    # What int() takes and a digit isn't: a sign, or whitespace in a number
    "Sat, 15 Aug 2020 23:12:09 --900",
    "Sat, 15 Aug 2020 23:12:09 +09-5",
    "Sat, 15 Aug +20 23:12:09 +0000",
    "Sat, +5 Aug 2020 23:12:09 +0000",
    "Sat, 15 Aug 2020 23:12:+9 +0000",
    "Sat, 15 Aug 2020 23:12:0\r9 +0000",
    "Sat, 15 Aug 2020 2 3:12:09 +0000",
    # Invalid time zone/offset
    "Sat, 15 Aug 2020 23:12:09",
    "Sat, 15 Aug 2020 23:12 -",
    "Sat, 15 Aug 2020 23:12 +",
    "Sat, 15 Aug 2020 23:12 0400",
    "Sat, 15 Aug 2020 23:12 +400",
    "Sat, 15 Aug 2020 23:12 +4060",
    "Sat, 15 Aug 2020 23:12 -4060",
    "Sat, 15 Aug 2020 23:12:00 +0160",
    "Sat, 15 Aug 2020 23:12:00 +0060",
    "Sat, 15 Aug 2020 23:12 +MST",
    "Sat, 15 Aug 2020 23:12 -MST",
    "Sat, 15 Aug 2020 23:12 MST4",
    "Sat, 15 Aug 2020 23:12 -04",
    "Sat, 15 Aug 2020 23:12 -   ",
    # whitespace problems
    "Sat, 15Aug 2020 23:12 -2100",
    "Sat, 15 Aug2020 23:12 -2100",
    "Sat, 15 Aug 202023:12 -2100",
    "Sat, 15 Aug 2020 23:12-2100",
    "Sat, 15 Aug 2020 23:12:00-2100",
    # Invalid values
    "Sun, 15 Aug 2020 23:12 +0400",
    "Foo, 15 Aug 2020 23:12 +0400",
    "Sat, 32 Aug 2020 23:12 +0400",
    "Sat, 31 Sep 2020 23:12 +0400",
    "Sat, 0 Sep 2020 23:12 +0400",
    "Sat, 1 Sep 0000 23:12 +0400",
    "Sat, 1 Sep 2020 24:12 +0400",
    "Sat, 1 Sep 2020 22:62 +0400",
    "Sat, 1 Sep 2020 22:22 +2400",
    "Sat, 1 Sep 2020 22:22 -2400",
    "Tue, 29 Feb 2023 22:22 -0400",
    "Wed, 30 Feb 2024 22:22 -0400",
    "Sat, 1 Foo 2020 14:12 +0400",
    "Sat, 15 Aug 2𝟘2𝟘 23:12:09 +0400",  # non-ascii
    # invalid comma
    "Mon 28 Feb 2023 22:22 -0400",
    "Sat. 15 Aug 2020 23:12:09 GMT",
    "Sat.15 Aug 2020 23:12:09 GMT",
    "Sat .15 Aug 2020 23:12:09 GMT",
    "Sat . 15 Aug 2020 23:12:09 GMT",
    "Tue, 028 Feb 2023 22:22 -0400",
    "Tue, 28 Feb 02023 22:22 -0400",
    "Tue, 28 Feb 2023 022:22 -0400",
    "Tue, 28 Feb 2023 22:022 -0400",
    "Tue, 28 Feb 2023 22:22 -00000400",
    # garbage strings
    "",
    "    \t\r\n ",
    "\t",
    " ",
    "garbage",
    # incomplete
    "S,",
    "Sa",
    "Sat",
    "Sat,",
    "Sat, ",
    "Sat, 1",
    "Sat, 1 ",
    "Sat, 1 Ja",
    "Sat, 1 Jan 20",
    "Sat, 1 Jan 89",
    "Sat, 1 Jan 198",
    "Sat, 1 Jan 1989 23",
    "Sat, 1 Jan 1989 23:",
    "Sat, 1 Jan 1989 23:2",
    "Sat, 1 Jan 1989 23:23",
    "Sat, 1 Jan 1989 23:23:0",
    "Sat, 1 Jan 1989 23:23:01 ",
    "Sat, 1 Jan 1989 23:23:01 +03 00",
    "Sat, 1 Jan 1989 23:23:01 +0300 ,",
    "Sat, 1 Jan 1989 23:23:01 +0300 MST",
    # leap second out of range
    "Sat, 31 Dec 2016 23:59:61 +0000",
]


class TestParseOffsetDateTime:
    @pytest.mark.parametrize("s, expected", VALID_RFC2822)
    def test_valid(self, s, expected):
        assert OffsetDateTime.parse_rfc2822(s) == expected

    @pytest.mark.parametrize("s", INVALID_RFC2822)
    def test_invalid(self, s):
        with pytest.raises(
            ValueError,
            match=r"^invalid RFC 2822 string: " + re.escape(repr(s)) + "$",
        ):
            OffsetDateTime.parse_rfc2822(s)

    @pytest.mark.parametrize(
        "s",
        [
            "Mon, 1 Jan 0001 03:12:09 +0400",
            "Fri, 31 Dec 9999 23:12:09 -0400",
        ],
    )
    def test_out_of_range(self, s):
        with pytest.raises(ValueError, match="range"):
            OffsetDateTime.parse_rfc2822(s)


@pytest.mark.parametrize(
    "i, expect",
    [
        (
            Instant.from_utc(2020, 8, 15, 23, 12, 9, nanosecond=450),
            "Sat, 15 Aug 2020 23:12:09 GMT",
        ),
        (
            Instant.from_utc(1, 1, 1, 9, 9),
            "Mon, 01 Jan 0001 09:09:00 GMT",
        ),
        (Instant.MIN, "Mon, 01 Jan 0001 00:00:00 GMT"),
        (Instant.MAX, "Fri, 31 Dec 9999 23:59:59 GMT"),
    ],
)
def test_format_instant(i, expect):
    assert i.format_rfc2822() == expect


class TestParseInstant:
    @pytest.mark.parametrize("s, expected", VALID_RFC2822)
    def test_valid(self, s, expected: OffsetDateTime):
        assert Instant.parse_rfc2822(s) == expected.to_instant()

    def test_military_letter_is_utc(self):
        assert Instant.parse_rfc2822(
            "Sat, 15 Aug 2020 23:12:00 Z"
        ) == Instant.from_utc(2020, 8, 15, 23, 12)

    @pytest.mark.parametrize(
        "s",
        [
            "Fri, 31 Dec 9999 23:59:59 -0100",  # out of range once in UTC
            "Sat, 15 Aug 2020 23:12:00 +0000 (UTC)",  # comment
        ],
    )
    def test_rejected(self, s):
        with pytest.raises(ValueError):
            Instant.parse_rfc2822(s)

    @pytest.mark.parametrize("s", INVALID_RFC2822)
    def test_invalid(self, s):
        with pytest.raises(
            ValueError,
            match=r"^invalid RFC 2822 string: " + re.escape(repr(s)) + "$",
        ):
            Instant.parse_rfc2822(s)
