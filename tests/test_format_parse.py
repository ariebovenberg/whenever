"""Tests for custom format/parse patterns."""

import warnings

import pytest

from whenever import (
    Date,
    Instant,
    OffsetDateTime,
    PlainDateTime,
    Time,
    ZonedDateTime,
    hours,
    minutes,
)
from whenever._format import compile_pattern, format_fields


class TestCompilePattern:
    """Tests for pattern compilation edge cases."""

    def test_simple(self):
        d = Date(2024, 3, 15)
        assert d.format("YYYY-MM-DD") == "2024-03-15"

    def test_quoted_literal(self):
        d = Date(2024, 3, 15)
        assert d.format("YYYY'xx'MM'xx'DD") == "2024xx03xx15"

    def test_escaped_quote(self):
        d = Date(2024, 3, 15)
        assert d.format("YYYY''MM") == "2024'03"

    def test_quote_at_end(self):
        """Quoted literal at end of pattern."""
        d = Date(2024, 3, 15)
        assert d.format("YYYY-MM-DD'!'") == "2024-03-15!"

    def test_three_consecutive_quotes(self):
        """''' = escaped quote + start of new quoted literal (unterminated)."""
        with pytest.raises(ValueError, match="Unterminated"):
            Date(2024, 1, 1).format("YYYY'''")

    def test_four_consecutive_quotes(self):
        """'''' = two escaped quotes."""
        d = Date(2024, 3, 15)
        assert d.format("YYYY''''MM") == "2024''03"

    def test_empty_quoted_literal(self):
        """'' is an escaped quote, not an empty literal."""
        d = Date(2024, 3, 15)
        assert d.format("YYYY''-MM") == "2024'-03"

    def test_nonletter_literal(self):
        d = Date(2024, 3, 15)
        assert d.format("YYYY/MM/DD") == "2024/03/15"
        assert d.format("YYYY.MM.DD") == "2024.03.15"
        assert d.format("YYYY_MM_DD") == "2024_03_15"
        assert d.format("YYYY MM DD") == "2024 03 15"

    def test_unrecognized_letter(self):
        d = Date(2024, 3, 15)
        with pytest.raises(ValueError, match="Unrecognized"):
            d.format("YYYY-Q-DD")

    def test_unterminated_quote(self):
        d = Date(2024, 3, 15)
        with pytest.raises(ValueError, match="Unterminated"):
            d.format("YYYY'abc")

    def test_too_many_fractional(self):
        t = Time(14, 30)
        with pytest.raises(ValueError, match="Too many"):
            t.format("hh:mm:ss.ffffffffff")

    def test_empty_pattern(self):
        d = Date(2024, 3, 15)
        assert d.format("") == ""

    def test_24h_with_ampm_raises(self):
        t = Time(14, 30)
        with pytest.raises(ValueError, match="24-hour.*cannot.*AM/PM"):
            t.format("hh:mm aa")

    def test_12h_without_ampm_warns(self):
        t = Time(14, 30)
        with warnings.catch_warnings(record=True) as w:
            warnings.simplefilter("always")
            t.format("ii:mm")
            assert len(w) == 1
            assert "ambiguous" in str(w[0].message).lower()

    def test_yy_parse_disabled(self):
        with pytest.raises(ValueError, match="YY.*only.*formatting"):
            Date.parse("24-03-15", format="YY-MM-DD")

    def test_invalid_specifier_count(self):
        """E.g. YYY (3 Y's) is not valid — only 2 or 4."""
        with pytest.raises(ValueError, match="Valid counts"):
            Date(2024, 1, 1).format("YYY-MM-DD")

        with pytest.raises(ValueError, match="Valid counts"):
            Date(2024, 1, 1).format("Y-MM-DD")


    def test_duplicate_field_error(self):
        """Two fields writing to the same state should be rejected."""
        with pytest.raises(ValueError, match="Duplicate.*month"):
            Date(2024, 1, 1).format("MM MMM DD YYYY")

    def test_duplicate_year_error(self):
        with pytest.raises(ValueError, match="Duplicate.*year"):
            Date(2024, 1, 1).format("YYYY-YY-MM-DD")

    def test_reserved_chars_error(self):
        """< > [ ] { } # are reserved for future use."""
        for ch in "<>[]{}#":
            with pytest.raises(ValueError, match="reserved"):
                Date(2024, 1, 1).format(f"YYYY{ch}MM")

    def test_non_ascii_error(self):
        with pytest.raises(ValueError, match="Non-ASCII"):
            Date(2024, 1, 1).format("YYYY\u2013MM\u2013DD")

    def test_literal_digits(self):
        """Digits are valid as unquoted literals."""
        d = Date(2024, 3, 15)
        assert d.format("YYYY0MM0DD") == "2024003015"

    def test_control_char_rejected(self):
        """ASCII control characters are not in the literal allowlist."""
        with pytest.raises(ValueError, match="Unexpected"):
            Date(2024, 1, 1).format("YYYY\x00MM")


class TestDateFormat:
    def test_basic(self):
        d = Date(2024, 3, 15)
        assert d.format("YYYY-MM-DD") == "2024-03-15"

    def test_two_digit_year_format(self):
        assert Date(2024, 1, 1).format("YY-MM-DD") == "24-01-01"
        assert Date(2000, 1, 1).format("YY-MM-DD") == "00-01-01"
        assert Date(1999, 1, 1).format("YY-MM-DD") == "99-01-01"

    def test_month_name(self):
        assert Date(2024, 1, 15).format("DD MMM YYYY") == "15 Jan 2024"
        assert Date(2024, 12, 25).format("DD MMMM YYYY") == "25 December 2024"

    def test_weekday(self):
        d = Date(2024, 3, 15)  # Friday
        assert d.format("ddd DD") == "Fri 15"
        assert d.format("dddd, DD MMMM YYYY") == "Friday, 15 March 2024"

    def test_small_year(self):
        d = Date(1, 6, 15)
        assert d.format("YYYY-MM-DD") == "0001-06-15"

    def test_disallowed_time_field(self):
        d = Date(2024, 3, 15)
        with pytest.raises(ValueError, match="does not support.*hh"):
            d.format("hh:mm")

    def test_disallowed_offset_field(self):
        d = Date(2024, 3, 15)
        with pytest.raises(ValueError, match="does not support.*xxx"):
            d.format("YYYY-MM-DDxxx")


class TestDateParse:
    def test_basic(self):
        d = Date.parse("2024-03-15", format="YYYY-MM-DD")
        assert d == Date(2024, 3, 15)

    def test_slash_separator(self):
        d = Date.parse("2024/03/15", format="YYYY/MM/DD")
        assert d == Date(2024, 3, 15)

    def test_month_name(self):
        d = Date.parse("15 Mar 2024", format="DD MMM YYYY")
        assert d == Date(2024, 3, 15)

    def test_full_month_name(self):
        d = Date.parse("15 December 2024", format="DD MMMM YYYY")
        assert d == Date(2024, 12, 15)

    def test_case_insensitive_month(self):
        d = Date.parse("15 MARCH 2024", format="DD MMMM YYYY")
        assert d == Date(2024, 3, 15)

    def test_weekday_valid(self):
        d = Date.parse("Fri 2024-03-15", format="ddd YYYY-MM-DD")
        assert d == Date(2024, 3, 15)

    def test_weekday_mismatch(self):
        with pytest.raises(ValueError, match="weekday"):
            Date.parse("Mon 2024-03-15", format="ddd YYYY-MM-DD")

    def test_missing_year(self):
        with pytest.raises(ValueError, match="year"):
            Date.parse("03-15", format="MM-DD")

    def test_missing_month(self):
        with pytest.raises(ValueError, match="month"):
            Date.parse("2024-15", format="YYYY-DD")

    def test_missing_day(self):
        with pytest.raises(ValueError, match="day"):
            Date.parse("2024-03", format="YYYY-MM")

    def test_trailing_text(self):
        with pytest.raises(ValueError, match="trailing"):
            Date.parse("2024-03-15extra", format="YYYY-MM-DD")

    def test_roundtrip(self):
        d = Date(2024, 3, 15)
        pattern = "YYYY-MM-DD"
        assert Date.parse(d.format(pattern), format=pattern) == d

    # TODO: test for invalid year, moths, and day values.
    # Same for time (e.g. 27:60). Also for offsets! 13:99 is commonly parsed I've noticed but NOT valid!
    # see parse_iso() tests for the amount of rigor we should aim for here in tests too.

    def test_roundtrip_complex(self):
        d = Date(2024, 12, 25)
        pattern = "dddd, DD MMMM YYYY"
        assert Date.parse(d.format(pattern), format=pattern) == d


class TestMonthWeekdayCoverage:
    """Ensure all 12 months and all 7 weekdays parse correctly."""

    @pytest.mark.parametrize(
        "month, abbr, full",
        [
            (1, "Jan", "January"),
            (2, "Feb", "February"),
            (3, "Mar", "March"),
            (4, "Apr", "April"),
            (5, "May", "May"),
            (6, "Jun", "June"),
            (7, "Jul", "July"),
            (8, "Aug", "August"),
            (9, "Sep", "September"),
            (10, "Oct", "October"),
            (11, "Nov", "November"),
            (12, "Dec", "December"),
        ],
    )
    def test_all_months(self, month, abbr, full):
        d = Date(2024, month, 1)
        assert Date.parse(d.format("DD MMM YYYY"), format="DD MMM YYYY") == d
        assert Date.parse(d.format("DD MMMM YYYY"), format="DD MMMM YYYY") == d

    @pytest.mark.parametrize(
        "day, abbr, full",
        [
            (Date(2024, 3, 11), "Mon", "Monday"),
            (Date(2024, 3, 12), "Tue", "Tuesday"),
            (Date(2024, 3, 13), "Wed", "Wednesday"),
            (Date(2024, 3, 14), "Thu", "Thursday"),
            (Date(2024, 3, 15), "Fri", "Friday"),
            (Date(2024, 3, 16), "Sat", "Saturday"),
            (Date(2024, 3, 17), "Sun", "Sunday"),
        ],
    )
    def test_all_weekdays(self, day, abbr, full):
        assert Date.parse(f"{abbr} {day}", format="ddd YYYY-MM-DD") == day
        assert Date.parse(f"{full} {day}", format="dddd YYYY-MM-DD") == day


class TestTimeFormat:
    def test_basic(self):
        assert Time(14, 30, 5).format("hh:mm:ss") == "14:30:05"

    def test_12h(self):
        assert Time(14, 30).format("ii:mm aa") == "02:30 PM"
        assert Time(0, 0).format("ii:mm aa") == "12:00 AM"
        assert Time(12, 0).format("ii:mm aa") == "12:00 PM"
        assert Time(23, 59).format("ii:mm aa") == "11:59 PM"
        assert Time(11, 30).format("ii:mm aa") == "11:30 AM"

    def test_ampm_short(self):
        assert Time(14, 30).format("ii:mm a") == "02:30 P"
        assert Time(9, 30).format("ii:mm a") == "09:30 A"

    def test_fractional_exact(self):
        t = Time(14, 30, 5, nanosecond=123_456_789)
        assert t.format("hh:mm:ss.fff") == "14:30:05.123"
        assert t.format("hh:mm:ss.ffffff") == "14:30:05.123456"
        assert t.format("hh:mm:ss.fffffffff") == "14:30:05.123456789"

    def test_fractional_trim(self):
        assert (
            Time(14, 30, 5, nanosecond=120_000_000).format("hh:mm:ss.FFF")
            == "14:30:05.12"
        )
        assert (
            Time(14, 30, 5, nanosecond=100_000_000).format("hh:mm:ss.FFF")
            == "14:30:05.1"
        )
        # All zeros: trim dot too
        assert Time(14, 30, 5).format("hh:mm:ss.FFF") == "14:30:05"

    def test_disallowed_date_field(self):
        t = Time(14, 30)
        with pytest.raises(ValueError, match="does not support.*YYYY"):
            t.format("YYYY hh:mm")


class TestTimeParse:
    def test_basic(self):
        assert Time.parse("14:30:05", format="hh:mm:ss") == Time(14, 30, 5)

    def test_12h_pm(self):
        assert Time.parse("02:30 PM", format="ii:mm aa") == Time(14, 30)

    def test_12h_am(self):
        assert Time.parse("02:30 AM", format="ii:mm aa") == Time(2, 30)

    def test_12h_noon(self):
        assert Time.parse("12:00 PM", format="ii:mm aa") == Time(12, 0)

    def test_12h_midnight(self):
        assert Time.parse("12:00 AM", format="ii:mm aa") == Time(0, 0)

    def test_invalid_ampm_text(self):
        with pytest.raises(ValueError, match="AM/PM"):
            Time.parse("02:30 AA", format="ii:mm aa")

    def test_hour_out_of_range_24h(self):
        with pytest.raises(ValueError):
            Time.parse("24:30", format="hh:mm")

    def test_trailing_text(self):
        with pytest.raises(ValueError, match="trailing"):
            Time.parse("14:30:05extra", format="hh:mm:ss")

    def test_trailing_period_fractional(self):
        """Trailing period after seconds with exact fractional field fails."""
        with pytest.raises(ValueError, match="digits"):
            Time.parse("14:30:05.", format="hh:mm:ss.fff")

    def test_fractional(self):
        t = Time.parse("14:30:05.123", format="hh:mm:ss.fff")
        assert t == Time(14, 30, 5, nanosecond=123_000_000)

    def test_fractional_trimmed(self):
        """FFF parses variable-width digits and trims the preceding dot
        if there are no fractions."""
        t = Time.parse("14:30:05.12", format="hh:mm:ss.FFF")
        assert t == Time(14, 30, 5, nanosecond=120_000_000)
        # No fractional digits: the dot is consumed as literal,
        # then FFF parses zero digits
        assert Time(14, 30, 5).format("hh:mm:ss.FFF") == "14:30:05"

    def test_fractional_nanos(self):
        t = Time.parse("14:30:05.123456789", format="hh:mm:ss.fffffffff")
        assert t == Time(14, 30, 5, nanosecond=123_456_789)

    def test_optional_fields(self):
        # Hour only
        assert Time.parse("14", format="hh") == Time(14)

    def test_roundtrip(self):
        t = Time(14, 30, 5, nanosecond=123_456_789)
        pattern = "hh:mm:ss.fffffffff"
        assert Time.parse(t.format(pattern), format=pattern) == t

    def test_roundtrip_ampm(self):
        for h in (0, 1, 11, 12, 13, 23):
            t = Time(h, 30)
            pattern = "ii:mm aa"
            assert Time.parse(t.format(pattern), format=pattern) == t


class TestPlainDateTimeFormat:
    def test_basic(self):
        pdt = PlainDateTime(2024, 3, 15, 14, 30, 5)
        assert pdt.format("YYYY-MM-DD hh:mm:ss") == "2024-03-15 14:30:05"

    def test_with_nanos(self):
        pdt = PlainDateTime(2024, 3, 15, 14, 30, 5, nanosecond=123_000_000)
        assert (
            pdt.format("YYYY-MM-DD hh:mm:ss.fff") == "2024-03-15 14:30:05.123"
        )

    def test_disallowed_offset(self):
        pdt = PlainDateTime(2024, 3, 15, 14, 30)
        with pytest.raises(ValueError, match="does not support"):
            pdt.format("YYYY-MM-DDxxx")


class TestPlainDateTimeParse:
    def test_basic(self):
        assert PlainDateTime.parse(
            "2024-03-15 14:30:05", format="YYYY-MM-DD hh:mm:ss"
        ) == PlainDateTime(2024, 3, 15, 14, 30, 5)

    def test_missing_year(self):
        with pytest.raises(ValueError, match="year"):
            PlainDateTime.parse("03-15 14:30", format="MM-DD hh:mm")

    def test_roundtrip(self):
        pdt = PlainDateTime(2024, 3, 15, 14, 30, 5, nanosecond=100_000_000)
        pattern = "YYYY-MM-DD hh:mm:ss.fff"
        assert PlainDateTime.parse(pdt.format(pattern), format=pattern) == pdt


class TestOffsetDateTimeFormat:
    def test_basic(self):
        odt = OffsetDateTime(2024, 3, 15, 14, 30, offset=hours(2))
        assert odt.format("YYYY-MM-DD hh:mmxxx") == "2024-03-15 14:30+02:00"

    def test_negative_offset(self):
        odt = OffsetDateTime(2024, 3, 15, 14, 30, offset=hours(-5))
        assert odt.format("YYYY-MM-DD hh:mmxxx") == "2024-03-15 14:30-05:00"

    def test_utc_offset_shows_plus_zero(self):
        """OffsetDateTime always shows +00:00, never Z."""
        odt = OffsetDateTime(2024, 3, 15, 14, 30, offset=hours(0))
        assert odt.format("YYYY-MM-DD hh:mmxxx") == "2024-03-15 14:30+00:00"

    def test_offset_width_1(self):
        """x — hours only."""
        odt = OffsetDateTime(2024, 3, 15, 14, 30, offset=hours(2))
        assert odt.format("hh:mmx") == "14:30+02"

    def test_offset_width_2(self):
        """xx — compact hours+minutes."""
        odt = OffsetDateTime(
            2024, 3, 15, 14, 30, offset=hours(5) + minutes(30)
        )
        assert odt.format("hh:mmxx") == "14:30+0530"

    def test_offset_width_4_no_seconds(self):
        """xxxx — compact, seconds omitted when zero."""
        odt = OffsetDateTime(
            2024, 3, 15, 14, 30, offset=hours(5) + minutes(30)
        )
        assert odt.format("hh:mmxxxx") == "14:30+0530"

    def test_offset_width_5_no_seconds(self):
        """xxxxx — with colons, seconds omitted when zero."""
        odt = OffsetDateTime(
            2024, 3, 15, 14, 30, offset=hours(5) + minutes(30)
        )
        assert odt.format("hh:mmxxxxx") == "14:30+05:30"

    def test_uppercase_x_zero_offset(self):
        """X uses Z for zero offset."""
        odt = OffsetDateTime(2024, 3, 15, 14, 30, offset=hours(0))
        assert odt.format("hh:mmXXX") == "14:30Z"

    def test_uppercase_x_nonzero_offset(self):
        """X uses numeric for non-zero offset."""
        odt = OffsetDateTime(2024, 3, 15, 14, 30, offset=hours(2))
        assert odt.format("hh:mmXXX") == "14:30+02:00"


class TestOffsetDateTimeParse:
    def test_basic(self):
        odt = OffsetDateTime.parse(
            "2024-03-15 14:30+02:00", format="YYYY-MM-DD hh:mmxxx"
        )
        assert odt == OffsetDateTime(2024, 3, 15, 14, 30, offset=hours(2))

    def test_utc_z(self):
        """Parsing accepts Z as +00:00 with uppercase X."""
        odt = OffsetDateTime.parse(
            "2024-03-15 14:30Z", format="YYYY-MM-DD hh:mmXXX"
        )
        assert odt == OffsetDateTime(2024, 3, 15, 14, 30, offset=hours(0))

    def test_missing_offset(self):
        with pytest.raises(ValueError, match="offset.*x/X"):
            OffsetDateTime.parse("2024-03-15 14:30", format="YYYY-MM-DD hh:mm")

    def test_roundtrip(self):
        odt = OffsetDateTime(
            2024, 3, 15, 14, 30, 5, nanosecond=123_000_000, offset=hours(-5)
        )
        pattern = "YYYY-MM-DD hh:mm:ss.fffxxx"
        assert OffsetDateTime.parse(odt.format(pattern), format=pattern) == odt


class TestZonedDateTimeFormat:
    def test_basic(self):
        zdt = ZonedDateTime(2024, 3, 15, 14, 30, tz="Europe/Paris")
        assert (
            zdt.format("YYYY-MM-DD hh:mmxxx'['VV']'")
            == "2024-03-15 14:30+01:00[Europe/Paris]"
        )

    def test_with_abbreviation(self):
        zdt = ZonedDateTime(2024, 7, 15, 14, 30, tz="Europe/Paris")
        result = zdt.format("YYYY-MM-DD hh:mm zz")
        assert "CEST" in result

    def test_tz_only_no_offset(self):
        """Format with tz ID but no offset field."""
        zdt = ZonedDateTime(2024, 3, 15, 14, 30, tz="Europe/Paris")
        assert (
            zdt.format("YYYY-MM-DD hh:mm '['VV']'")
            == "2024-03-15 14:30 [Europe/Paris]"
        )


class TestZonedDateTimeParse:
    def test_basic(self):
        zdt = ZonedDateTime.parse(
            "2024-03-15 14:30+01:00[Europe/Paris]",
            format="YYYY-MM-DD hh:mmxxx'['VV']'",
        )
        assert zdt == ZonedDateTime(2024, 3, 15, 14, 30, tz="Europe/Paris")

    def test_missing_tz_id(self):
        with pytest.raises(ValueError, match="timezone ID.*VV"):
            ZonedDateTime.parse(
                "2024-03-15 14:30+01:00",
                format="YYYY-MM-DD hh:mmxxx",
            )

    def test_tz_only_no_offset(self):
        """Parse with tz ID but no offset — uses disambiguate kwarg."""
        zdt = ZonedDateTime.parse(
            "2024-03-15 14:30[Europe/Paris]",
            format="YYYY-MM-DD hh:mm'['VV']'",
        )
        assert zdt == ZonedDateTime(2024, 3, 15, 14, 30, tz="Europe/Paris")

    def test_offset_mismatch(self):
        """Offset doesn't match timezone: should raise."""
        with pytest.raises(ValueError, match="does not match"):
            ZonedDateTime.parse(
                "2024-03-15 14:30+05:00[Europe/Paris]",
                format="YYYY-MM-DD hh:mmxxx'['VV']'",
            )

    def test_offset_disambiguation(self):
        # November 3, 2024: US DST transition (fall back)
        # 1:30 AM exists twice: EDT (-04:00) and EST (-05:00)
        zdt_edt = ZonedDateTime.parse(
            "2024-11-03 01:30-04:00[America/New_York]",
            format="YYYY-MM-DD hh:mmxxx'['VV']'",
        )
        zdt_est = ZonedDateTime.parse(
            "2024-11-03 01:30-05:00[America/New_York]",
            format="YYYY-MM-DD hh:mmxxx'['VV']'",
        )
        assert zdt_edt != zdt_est  # different instants
        assert zdt_edt.hour == zdt_est.hour == 1
        assert zdt_edt.minute == zdt_est.minute == 30

    def test_skipped_time_with_offset(self):
        """Parsing a skipped local time should be rejected,
        consistent with parse_iso()."""
        # 2024-03-10 02:30 doesn't exist in New York (spring forward)
        with pytest.raises(ValueError, match="does not exist"):
            ZonedDateTime.parse(
                "2024-03-10 02:30-05:00[America/New_York]",
                format="YYYY-MM-DD hh:mmxxx'['VV']'",
            )

    def test_roundtrip(self):
        zdt = ZonedDateTime(2024, 7, 15, 14, 30, tz="Europe/Paris")
        pattern = "YYYY-MM-DD hh:mm:ssxxx'['VV']'"
        assert ZonedDateTime.parse(zdt.format(pattern), format=pattern) == zdt


class TestInstantFormat:
    def test_basic_uses_z(self):
        """Instant uses Z for UTC offset with uppercase X specifier."""
        i = Instant.from_utc(2024, 3, 15, 14, 30)
        assert i.format("YYYY-MM-DD hh:mmXXX") == "2024-03-15 14:30Z"

    def test_with_fractional(self):
        i = Instant.from_utc(2024, 3, 15, 14, 30, 5, nanosecond=123_000_000)
        assert (
            i.format("YYYY-MM-DD hh:mm:ss.fffXXX")
            == "2024-03-15 14:30:05.123Z"
        )


class TestInstantParse:
    def test_utc(self):
        i = Instant.parse("2024-03-15 14:30Z", format="YYYY-MM-DD hh:mmXXX")
        assert i == Instant.from_utc(2024, 3, 15, 14, 30)

    def test_with_offset(self):
        # Offset is converted to UTC
        i = Instant.parse(
            "2024-03-15 14:30+05:30", format="YYYY-MM-DD hh:mmxxx"
        )
        assert i == Instant.from_utc(2024, 3, 15, 9, 0)

    def test_offset_causes_out_of_range(self):
        """Applying a negative offset to the latest valid date pushes it out of range."""
        with pytest.raises(ValueError, match="out of range"):
            Instant.parse(
                "9999-12-31 23:00-02:00", format="YYYY-MM-DD hh:mmxxx"
            )

    def test_without_offset_raises(self):
        """Instant.parse requires an offset field in the pattern."""
        with pytest.raises(ValueError, match="offset.*x/X"):
            Instant.parse("2024-03-15 14:30", format="YYYY-MM-DD hh:mm")

    def test_roundtrip(self):
        i = Instant.from_utc(2024, 3, 15, 14, 30, 5, nanosecond=123_456_789)
        pattern = "YYYY-MM-DD hh:mm:ss.fffffffffXXX"
        assert Instant.parse(i.format(pattern), format=pattern) == i


class TestStrftimeParity:
    """Verify we can express common strftime patterns."""

    def test_date_us(self):
        """Equivalent to %m/%d/%Y"""
        d = Date(2024, 3, 15)
        assert d.format("MM/DD/YYYY") == "03/15/2024"

    def test_date_european(self):
        """Equivalent to %d.%m.%Y"""
        d = Date(2024, 3, 15)
        assert d.format("DD.MM.YYYY") == "15.03.2024"

    def test_iso_datetime(self):
        """Equivalent to %Y-%m-%dT%H:%M:%S"""
        pdt = PlainDateTime(2024, 3, 15, 14, 30, 5)
        assert pdt.format("YYYY-MM-DD'T'hh:mm:ss") == "2024-03-15T14:30:05"

    def test_rfc2822_like(self):
        """Roughly equivalent to %a, %d %b %Y %H:%M:%S %z"""
        odt = OffsetDateTime(2024, 3, 15, 14, 30, 5, offset=hours(2))
        result = odt.format("ddd, DD MMM YYYY hh:mm:ssxxx")
        assert result == "Fri, 15 Mar 2024 14:30:05+02:00"

    def test_12h_time(self):
        """Equivalent to %I:%M %p"""
        t = Time(14, 30)
        assert t.format("ii:mm aa") == "02:30 PM"

    def test_full_weekday_month(self):
        """Equivalent to %A, %B %d, %Y"""
        d = Date(2024, 12, 25)
        assert (
            d.format("dddd, MMMM DD, YYYY") == "Wednesday, December 25, 2024"
        )


class TestSecurityEdgeCases:
    """Guard against malicious or unexpectedly large inputs."""

    def test_pattern_too_long_raises(self):
        with pytest.raises(ValueError, match="too long"):
            Date.parse("2024-01-01", format="Y" * 1001)

    def test_input_too_long_raises(self):
        with pytest.raises(ValueError, match="too long"):
            Date.parse("2024" + "-" * 1001, format="YYYY-MM-DD")

    def test_pattern_at_max_length_ok(self):
        # 1000 chars: 250 repetitions of "YYYY" is a valid (if odd) pattern
        # Use quoted literals so it doesn't raise for duplicate fields
        pattern = "'x'" * 333 + "YYYY"  # 333*3 + 4 = 1003 chars — too long
        with pytest.raises(ValueError, match="too long"):
            Date.parse("2024", format=pattern)

    def test_empty_input(self):
        with pytest.raises(ValueError):
            Date.parse("", format="YYYY-MM-DD")

    def test_empty_pattern_on_empty_input(self):
        """Empty pattern on empty input is technically valid (all fields missing)."""
        from whenever._format import compile_pattern, parse_fields

        state = parse_fields(compile_pattern(""), "")
        assert state.year is None


class TestDeprecations:
    """Test that deprecated methods emit warnings."""

    def test_offset_datetime_parse_strptime_deprecated(self):
        with pytest.warns(match="parse_strptime.*deprecated"):
            OffsetDateTime.parse_strptime(
                "2020-08-15+0200", format="%Y-%m-%d%z"
            )

    def test_plain_datetime_parse_strptime_deprecated(self):
        with pytest.warns(match="parse_strptime.*deprecated"):
            PlainDateTime.parse_strptime(
                "2020-08-15 14:30", format="%Y-%m-%d %H:%M"
            )


class TestParseEdgeCases:
    """Test parse error paths for coverage."""

    def test_input_too_short(self):
        with pytest.raises(ValueError, match="too short"):
            Date.parse("202", format="YYYY-MM-DD")

    def test_non_digit(self):
        with pytest.raises(ValueError, match="digits"):
            Date.parse("abcd-03-15", format="YYYY-MM-DD")

    def test_literal_mismatch(self):
        with pytest.raises(ValueError, match="Expected"):
            Date.parse("2024/03/15", format="YYYY-MM-DD")

    def test_invalid_month_name(self):
        with pytest.raises(ValueError, match="month"):
            Date.parse("15 Xyz 2024", format="DD MMM YYYY")

    def test_ampm_short_parse(self):
        assert Time.parse("02 P", format="ii a") == Time(14, 0)
        assert Time.parse("02 A", format="ii a") == Time(2, 0)

    def test_ampm_short_invalid(self):
        with pytest.raises(ValueError, match="AM/PM"):
            Time.parse("02 X", format="ii a")

    def test_ampm_full_invalid(self):
        with pytest.raises(ValueError, match="AM/PM"):
            Time.parse("02:00 XY", format="ii:mm aa")

    def test_offset_with_seconds(self):
        odt = OffsetDateTime.parse(
            "2024-03-15 14:30+05:30:15",
            format="YYYY-MM-DD hh:mmxxxxx",
        )
        # 5*3600 + 30*60 + 15 = 19815 seconds offset
        assert odt.offset.total("seconds") == 19815

    def test_offset_invalid_char(self):
        with pytest.raises(ValueError, match="offset"):
            OffsetDateTime.parse(
                "2024-03-15 14:30Q02:00",
                format="YYYY-MM-DD hh:mmxxx",
            )

    def test_offset_not_available_for_format(self):
        """PlainDateTime doesn't have offset — formatting should error."""
        pdt = PlainDateTime(2024, 3, 15, 14, 30)
        with pytest.raises(ValueError, match="does not support"):
            pdt.format("YYYY-MM-DD hh:mmxxx")

    def test_tz_id_empty(self):
        with pytest.raises(ValueError, match="timezone ID"):
            ZonedDateTime.parse(
                "2024-03-15 14:30+01:00[]",
                format="YYYY-MM-DD hh:mmxxx'['VV']'",
            )

    def test_tz_abbrev_parse_rejected(self):
        """zz is format-only; parsing with it raises."""
        with pytest.raises(ValueError, match="only.*formatting"):
            ZonedDateTime.parse(
                "2024-07-15 14:30 CEST+02:00[Europe/Paris]",
                format="YYYY-MM-DD hh:mm zzxxx'['VV']'",
            )

    def test_frac_trim_parse_no_digits(self):
        """FFF with no fractional digits should set nanos to 0."""
        # The literal '.' is consumed, then FFF sees no digits
        t = Time.parse("14:30:05", format="hh:mm:ss")
        assert t == Time(14, 30, 5)

    def test_frac_trim_parse_partial(self):
        """FFF parses fewer digits than max width."""
        t = Time.parse("14:30:05.1", format="hh:mm:ss.FFF")
        assert t == Time(14, 30, 5, nanosecond=100_000_000)

    def test_frac_trim_parse_empty(self):
        """FFF with trailing dot but no digits sets nanos to 0."""
        t = Time.parse("14:30:05.", format="hh:mm:ss.FFF")
        assert t == Time(14, 30, 5)

    def test_offset_parse_without_colon(self):
        """Offset parsing accepts compact format like +0530 with xx."""
        odt = OffsetDateTime.parse(
            "2024-03-15 14:30+0530",
            format="YYYY-MM-DD hh:mmxx",
        )
        assert odt.offset.total("seconds") == 19800  # 5*3600 + 30*60

    def test_offset_parse_width_1(self):
        """Offset parsing with width 1 (hours only)."""
        odt = OffsetDateTime.parse(
            "2024-03-15 14:30+05",
            format="YYYY-MM-DD hh:mmx",
        )
        assert odt.offset.total("seconds") == 18000  # 5*3600

    def test_offset_parse_width_4_with_seconds(self):
        """Offset parsing with width 4 (compact, optional seconds present)."""
        odt = OffsetDateTime.parse(
            "2024-03-15 14:30+053015",
            format="YYYY-MM-DD hh:mmxxxx",
        )
        assert odt.offset.total("seconds") == 19815  # 5*3600 + 30*60 + 15

    def test_offset_parse_width_4_no_seconds(self):
        """Offset parsing with width 4 (compact, no seconds)."""
        odt = OffsetDateTime.parse(
            "2024-03-15 14:30+0530",
            format="YYYY-MM-DD hh:mmxxxx",
        )
        assert odt.offset.total("seconds") == 19800  # 5*3600 + 30*60

    def test_offset_parse_colon_expected(self):
        """Width 3 expects colon separator."""
        with pytest.raises(ValueError, match="':'"):
            OffsetDateTime.parse(
                "2024-03-15 14:30+0530",
                format="YYYY-MM-DD hh:mmxxx",
            )

    def test_ampm_short_parse_values(self):
        """Verify short AM/PM specifier (a) parses A and P correctly."""
        assert Time.parse("09 A", format="ii a") == Time(9, 0)
        assert Time.parse("09 P", format="ii a") == Time(21, 0)


class TestFormatFieldsInternal:
    """Tests for internal format_fields edge cases."""

    def test_offset_format_error_when_none(self):
        """Offset format errors when offset_secs is None."""
        with pytest.raises(ValueError, match="offset"):
            format_fields(compile_pattern("xxx"), offset_secs=None)

    def test_offset_upper_format_error_when_none(self):
        """Uppercase X offset format errors when offset_secs is None."""
        with pytest.raises(ValueError, match="offset"):
            format_fields(compile_pattern("XXX"), offset_secs=None)

    def test_offset_format_with_seconds(self):
        """Offset formatting includes seconds when non-zero (width 5)."""
        els = compile_pattern("xxxxx")
        result = format_fields(els, offset_secs=19815)  # 5:30:15
        assert result == "+05:30:15"

    def test_tz_id_format_error_when_none(self):
        with pytest.raises(ValueError, match="timezone ID"):
            format_fields(compile_pattern("VV"), tz_id=None)

    def test_tz_abbrev_format_error_when_none(self):
        with pytest.raises(ValueError, match="abbreviation"):
            format_fields(compile_pattern("zz"), tz_abbrev=None)

    def test_dot_trimmed_with_frac_trim(self):
        """Preceding dot is trimmed when FFF produces empty string."""
        els = compile_pattern("hh:mm:ss.FFF")
        result = format_fields(els, hour=14, minute=30, second=5, nanos=0)
        assert result == "14:30:05"

    def test_dot_not_trimmed_with_frac_exact(self):
        """fff always produces digits, dot is not trimmed."""
        els = compile_pattern("hh:mm:ss.fff")
        result = format_fields(els, hour=14, minute=30, second=5, nanos=0)
        assert result == "14:30:05.000"

    def test_parse_12hour_hour_too_high(self):
        """12-hour format rejects hour > 12."""
        with pytest.raises(
            ValueError, match="12-hour format requires hour in 1..12"
        ):
            Time.parse("13:30 AM", format="ii:mm aa")
        with pytest.raises(
            ValueError, match="12-hour format requires hour in 1..12"
        ):
            Time.parse("99:30 PM", format="ii:mm aa")

    def test_parse_12hour_hour_zero(self):
        """12-hour format rejects hour = 0."""
        with pytest.raises(
            ValueError, match="12-hour format requires hour in 1..12"
        ):
            Time.parse("00:30 AM", format="ii:mm aa")

    def test_parse_offset_seconds_overflow(self):
        """Offset parsing rejects seconds >= 60."""
        with pytest.raises(ValueError, match="offset seconds must be 0..59"):
            OffsetDateTime.parse(
                "2024-01-01 12:00 +05:30:60", format="YYYY-MM-DD hh:mm xxxxx"
            )
        with pytest.raises(ValueError, match="offset seconds must be 0..59"):
            OffsetDateTime.parse(
                "2024-01-01 12:00 +05:30:99", format="YYYY-MM-DD hh:mm xxxxx"
            )

    def test_parse_offset_minutes_overflow(self):
        """Offset parsing rejects minutes >= 60 (not silently treated as more hours)."""
        with pytest.raises(ValueError, match="offset minutes must be 0..59"):
            OffsetDateTime.parse(
                "2024-01-01 12:00+00:60", format="YYYY-MM-DD hh:mmxxx"
            )
        with pytest.raises(ValueError, match="offset minutes must be 0..59"):
            OffsetDateTime.parse(
                "2024-01-01 12:00+01:99", format="YYYY-MM-DD hh:mmxxx"
            )

    def test_frac_trim_roundtrip_no_nanos(self):
        """FFF format trims the dot when nanos=0; parsing the result back must work."""
        t = Time(14, 30, 5)  # no nanoseconds
        formatted = t.format("hh:mm:ss.FFF")
        assert formatted == "14:30:05"  # sanity: dot was trimmed by format
        # Parsing the trimmed output with the same pattern must succeed
        assert Time.parse(formatted, format="hh:mm:ss.FFF") == t

    def test_frac_trim_no_preceding_dot(self):
        """FFF with no preceding dot: nanos=0 produces empty, nothing is trimmed."""
        els = compile_pattern("hh:mm:ssFFF")
        result = format_fields(els, hour=14, minute=30, second=5, nanos=0)
        assert result == "14:30:05"

    def test_frac_trim_no_preceding_dot_nonzero(self):
        """FFF with no preceding dot: non-zero nanos are appended directly."""
        els = compile_pattern("hh:mm:ssFFF")
        result = format_fields(
            els, hour=14, minute=30, second=5, nanos=100_000_000
        )
        assert result == "14:30:051"

    def test_frac_trim_at_start_of_pattern(self):
        """FFF at the start of a pattern (no preceding literal) works correctly."""
        els = compile_pattern("FFFhh")
        result = format_fields(els, hour=14, nanos=100_000_000)
        assert result == "114"

    def test_frac_trim_dot_in_multichar_literal(self):
        """Trailing dot in a multi-char unquoted literal is trimmed when FFF is empty."""
        els = compile_pattern("123.FFF")
        result = format_fields(els, nanos=0)
        assert result == "123"

    def test_frac_trim_dot_quoted_literal_not_trimmed(self):
        """Dot inside a quoted literal is NOT subject to DotFrac trimming."""
        els = compile_pattern("'test.'FFF")
        result = format_fields(els, nanos=0)
        # The quoted literal 'test.' is emitted as-is; FFF produces no output
        assert result == "test."

    def test_frac_trim_roundtrip_no_dot_in_pattern(self):
        """FFF without preceding dot: round-trip works when nanos=0."""
        t = Time(14, 30, 5)  # nanos=0
        formatted = t.format("hh:mm:ssFFF")
        assert formatted == "14:30:05"
        assert Time.parse(formatted, format="hh:mm:ssFFF") == t


class TestDunderFormat:
    """Test the __format__ protocol for all supported types."""

    def test_date_with_spec(self):
        d = Date(2024, 3, 15)
        assert f"{d:YYYY/MM/DD}" == "2024/03/15"

    def test_date_empty_spec(self):
        d = Date(2024, 3, 15)
        assert f"{d}" == str(d)

    def test_time_with_spec(self):
        t = Time(14, 30)
        assert f"{t:hh:mm}" == "14:30"

    def test_time_empty_spec(self):
        t = Time(14, 30)
        assert f"{t}" == str(t)

    def test_plain_datetime_with_spec(self):
        dt = PlainDateTime(2024, 3, 15, 14, 30)
        assert f"{dt:YYYY-MM-DD hh:mm}" == "2024-03-15 14:30"

    def test_plain_datetime_empty_spec(self):
        dt = PlainDateTime(2024, 3, 15, 14, 30)
        assert f"{dt}" == str(dt)

    def test_instant_with_spec(self):
        i = Instant.from_utc(2024, 3, 15, 14, 30)
        assert f"{i:YYYY-MM-DD hh:mmXXX}" == "2024-03-15 14:30Z"

    def test_instant_empty_spec(self):
        i = Instant.from_utc(2024, 3, 15, 14, 30)
        assert f"{i}" == str(i)

    def test_offset_datetime_with_spec(self):
        odt = OffsetDateTime(2024, 3, 15, 14, 30, offset=hours(2))
        assert f"{odt:YYYY-MM-DD hh:mmxxx}" == "2024-03-15 14:30+02:00"

    def test_offset_datetime_empty_spec(self):
        odt = OffsetDateTime(2024, 3, 15, 14, 30, offset=hours(2))
        assert f"{odt}" == str(odt)

    def test_zoned_datetime_with_spec(self):
        zdt = ZonedDateTime(2024, 3, 15, 14, 30, tz="Europe/Paris")
        assert f"{zdt:YYYY-MM-DD hh:mm}" == "2024-03-15 14:30"

    def test_zoned_datetime_empty_spec(self):
        zdt = ZonedDateTime(2024, 3, 15, 14, 30, tz="Europe/Paris")
        assert f"{zdt}" == str(zdt)
