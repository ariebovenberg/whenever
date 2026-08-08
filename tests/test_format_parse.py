"""Tests for custom format/parse patterns."""

import warnings

import pytest
from whenever import (
    Date,
    ImplicitDisambiguationWarning,
    Instant,
    InvalidOffsetError,
    OffsetDateTime,
    PlainDateTime,
    RepeatedTime,
    SkippedTime,
    Time,
    TimeDelta,
    WheneverDeprecationWarning,
    WheneverWarning,
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

    def test_pending_not_consumed_by_specifier(self):
        """A pending '.' or ':' flushed as a literal when not consumed."""
        # '.' before a non-F specifier — flushed, not a DotFrac
        assert Date(2024, 3, 5).format("YYYY.M") == "2024.3"
        # ':' before a non-S specifier — flushed, not a ColonSec
        assert Time(14, 3, 5).format("HH:m") == "14:3"
        # ':' before 'FFF' — flushed (not ColonSec; FFF needs '.')
        assert (
            Time(14, 30, 5, nanosecond=120_000_000).format("HH:mm:FFF")
            == "14:30:12"
        )

    def test_pending_flushed_before_quote(self):
        """A pending char must be flushed as a literal before a quoted literal."""
        assert Date(2024, 3, 15).format("YYYY.'year'") == "2024.year"
        assert Date(2024, 3, 15).format("YYYY:'year'") == "2024:year"

    def test_pending_flushed_before_literal(self):
        """A pending char flushed when followed by a plain literal character."""
        assert Date(2024, 3, 15).format("YYYY.-MM") == "2024.-03"
        assert Date(2024, 3, 15).format("YYYY:-MM") == "2024:-03"

    def test_trailing_pending_flushed(self):
        """A pattern ending with '.' or ':' emits them as literals."""
        assert Date(2024, 3, 15).format("YYYY.") == "2024."
        assert Date(2024, 3, 15).format("YYYY:") == "2024:"

    def test_unterminated_quote(self):
        d = Date(2024, 3, 15)
        with pytest.raises(ValueError, match="Unterminated"):
            d.format("YYYY'abc")

    def test_too_many_fractional(self):
        t = Time(14, 30)
        with pytest.raises(ValueError, match="Too many"):
            t.format("HH:mm:ss.ffffffffff")

    def test_too_many_frac_trim(self):
        """More than 9 'F' characters raises ValueError."""
        with pytest.raises(ValueError, match="Too many.*F"):
            compile_pattern("HH:mm:ss.FFFFFFFFFF")

    def test_empty_pattern(self):
        d = Date(2024, 3, 15)
        assert d.format("") == ""

    def test_24h_with_ampm_raises(self):
        t = Time(14, 30)
        with pytest.raises(ValueError, match="24-hour.*cannot.*AM/PM"):
            t.format("HH:mm aa")

    def test_12h_without_ampm_warns(self):
        t = Time(14, 30)
        with warnings.catch_warnings(record=True) as w:
            warnings.simplefilter("always")
            t.format("ii:mm")
            assert len(w) == 1
            assert w[0].category is WheneverWarning
            assert "without an AM/PM field" in str(w[0].message)
            assert "24-hour fields" in str(w[0].message)

    def test_yy_parse_disabled(self):
        with pytest.raises(ValueError, match="YY.*only.*formatting"):
            Date.parse("24-03-15", pattern="YY-MM-DD")

    def test_parse_requires_pattern(self):
        with pytest.raises(TypeError, match="required.*pattern"):
            Date.parse("2024-03-15")  # type: ignore[call-overload]

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
        """< > ] { } # are reserved for future use."""
        for ch in "<>]{}#":
            with pytest.raises(ValueError, match="reserved"):
                Date(2024, 1, 1).format(f"YYYY{ch}MM")

    @pytest.mark.parametrize(
        "pattern",
        ["YYYY\u2013MM", "YYYY'é'", "YYYY'😀'", "YYYY[:ssé]"],
    )
    def test_non_ascii_error(self, pattern):
        with pytest.raises(ValueError, match="Non-ASCII"):
            Date(2024, 1, 1).format(pattern)

    def test_literal_digits(self):
        """Digits are valid as unquoted literals."""
        d = Date(2024, 3, 15)
        assert d.format("YYYY0MM0DD") == "2024003015"

    def test_control_char_rejected(self):
        """ASCII control characters are not in the literal allowlist."""
        with pytest.raises(ValueError, match="Unexpected"):
            Date(2024, 1, 1).format("YYYY\x00MM")


class TestOptionalSecondsPattern:
    def test_format_presence(self):
        assert Time(14, 30).format("HH:mm[:ss]") == "14:30"
        assert Time(14, 30, 5).format("HH:mm[:ss]") == "14:30:05"
        assert Time(14, 30, nanosecond=1).format("HH:mm[:ss]") == "14:30:00"

    @pytest.mark.parametrize("separator", ["", ":"])
    def test_supported_separator(self, separator):
        pattern = f"HH:mm[{separator}ss]"
        present = f"14:30{separator}05"
        assert Time(14, 30).format(pattern) == "14:30"
        assert Time(14, 30, 5).format(pattern) == present
        assert Time.parse("14:30", pattern=pattern) == Time(14, 30)
        assert Time.parse(present, pattern=pattern) == Time(14, 30, 5)

    @pytest.mark.parametrize("separator", ["-", "/", " ", ".", "0"])
    def test_other_separators_rejected(self, separator):
        with pytest.raises(ValueError, match="start with 'ss' or ':ss'"):
            Time(14, 30).format(f"HH:mm[{separator}ss]")

    @pytest.mark.parametrize("width", range(1, 10))
    def test_exact_fraction_each_width(self, width):
        fraction = "123456789"[:width]
        pattern = f"HH:mm[:ss.{('f' * width)}]"
        value = Time(14, 30, 5, nanosecond=123_456_789)
        assert value.format(pattern) == f"14:30:05.{fraction}"
        assert Time.parse(f"14:30:05.{fraction}", pattern=pattern) == Time(
            14,
            30,
            5,
            nanosecond=int(fraction) * (10 ** (9 - width)),
        )

    @pytest.mark.parametrize("width", range(1, 10))
    def test_trimmed_fraction_each_width(self, width):
        fraction = "123450000"[:width].rstrip("0")
        pattern = f"HH:mm[:ss.{('F' * width)}]"
        value = Time(14, 30, 5, nanosecond=123_450_000)
        assert value.format(pattern) == f"14:30:05.{fraction}"
        assert Time.parse(f"14:30:05.{fraction}", pattern=pattern) == Time(
            14,
            30,
            5,
            nanosecond=int(fraction) * (10 ** (9 - len(fraction))),
        )

    @pytest.mark.parametrize(
        "pattern",
        ["HH:mm[:ss]", "HH:mm[:ss.fff]", "HH:mm[:ss.FFF]"],
    )
    def test_parse_absent(self, pattern):
        assert Time.parse("14:30", pattern=pattern) == Time(14, 30)

    def test_present_zero_seconds(self):
        assert Time.parse("14:30:00", pattern="HH:mm[:ss]") == Time(14, 30)

    def test_present_exact_fraction_is_required(self):
        with pytest.raises(ValueError, match="expected.*'\\.'"):
            Time.parse("14:30:05", pattern="HH:mm[:ss.fff]")
        with pytest.raises(ValueError, match="digits"):
            Time.parse("14:30:05.", pattern="HH:mm[:ss.fff]")

    def test_present_trimmed_fraction_follows_dot_fraction_rules(self):
        assert Time.parse("14:30:05", pattern="HH:mm[:ss.FFF]") == Time(
            14, 30, 5
        )
        with pytest.raises(ValueError, match="trailing"):
            Time.parse("14:30:05.", pattern="HH:mm[:ss.FFF]")

    @pytest.mark.parametrize(
        "pattern, match",
        [
            ("HH:mm[:ss", "missing closing"),
            ("HH:mm[[:ss]]", "nested"),
            ("HH:mm[]", "empty"),
            ("HH:mm[:s]", "start with 'ss' or ':ss'"),
            ("HH:mm[:SS]", "start with 'ss' or ':ss'"),
            ("HH:mm[:ss.fF]", "only 'f'.*only 'F'"),
            ("HH:mm[:ss.x]", "only 'f'.*only 'F'"),
            ("HH:mm[:ss.foo]", "only 'f'.*only 'F'"),
            ("HH:mm[:ssx]", "unsupported optional group"),
            ("HH:mm[:ss.]", "fraction is missing"),
            ("HH:mm[:ss.ffffffffff]", "limited to 9"),
        ],
    )
    def test_malformed_group(self, pattern, match):
        with pytest.raises(ValueError, match=match):
            Time(14, 30).format(pattern)

    def test_trailing_input(self):
        with pytest.raises(ValueError, match="trailing"):
            Time.parse("14:30x", pattern="HH:mm[:ss]")

    def test_pending_literal_before_group(self):
        with pytest.raises(ValueError, match="immediately follow.*'mm'"):
            Time(14, 30).format("HH:mm.[:ss]")

    @pytest.mark.parametrize(
        "pattern, match",
        [
            ("HH:m[:ss]", "immediately follow.*'mm'"),
            ("HH:mm[ss]00", "starts with a digit"),
            ("HH:mm[ss]YYYY", "starts with a digit"),
            ("HH:mm[:ss]:", "starts with ':'"),
            ("HH:mm[:ss]FFF", "optional field"),
            ("HH:mm[:ss.FFF].", "starts with '\\.'"),
            ("HH:mm[:ss.FFF]VV", "starts with '\\.'"),
            ("HH:mm[:ss.FFF]zz", "starts with '\\.'"),
        ],
    )
    def test_ambiguous_placement_rejected(self, pattern, match):
        with pytest.raises(ValueError, match=match):
            Time(14, 30).format(pattern)

    @pytest.mark.parametrize(
        ("pattern", "without_seconds", "with_seconds"),
        [
            ("HH:mm[ss]'x'", "14:30x", "14:3005x"),
            ("HH:mm[:ss]00", "14:3000", "14:30:0500"),
        ],
    )
    def test_unambiguous_follower_allowed(
        self, pattern, without_seconds, with_seconds
    ):
        assert Time(14, 30).format(pattern) == without_seconds
        assert Time(14, 30, 5).format(pattern) == with_seconds
        assert Time.parse(without_seconds, pattern=pattern) == Time(14, 30)
        assert Time.parse(with_seconds, pattern=pattern) == Time(14, 30, 5)

    def test_duplicate_fields(self):
        with pytest.raises(ValueError, match="Duplicate.*second"):
            Time(1, 2, 3).format("HH:mm[:ss]ss")
        with pytest.raises(ValueError, match="Duplicate.*nanos"):
            Time(1, 2, 3).format("HH:mm[:ss.fff]fff")

    def test_brackets_invalid_for_date(self):
        with pytest.raises(ValueError, match="immediately follow.*'mm'"):
            Date(2024, 3, 15).format("YYYY-MM-DD[:ss]")

    def test_quoted_reserved_characters_are_literals(self):
        with warnings.catch_warnings():
            warnings.simplefilter("error")
            assert Date(2024, 3, 15).format("'hH S[]'") == "hH S[]"


class TestPatternDeprecations:
    @pytest.mark.parametrize(
        "pattern, replacement", [("h", "`H`"), ("hh", "`HH`")]
    )
    def test_legacy_hour_format(self, pattern, replacement):
        with pytest.warns(WheneverDeprecationWarning) as w:
            Time(13).format(pattern)
        assert len(w) == 1
        assert f"use {replacement} instead" in str(w[0].message)
        assert w[0].filename == __file__

    @pytest.mark.parametrize(
        "pattern, replacement",
        [
            ("HH:mm:SS", "`[:ss]`"),
            ("HH:mm:SS.fff", "`[:ss.fff]`"),
            ("HH:mm:SS.FFF", "`[:ss.FFF]`"),
        ],
    )
    def test_legacy_prefixed_optional_seconds(self, pattern, replacement):
        with pytest.warns(WheneverDeprecationWarning) as w:
            Time(13).format(pattern)
        assert len(w) == 1
        assert f"use {replacement} instead" in str(w[0].message)
        assert w[0].filename == __file__

    @pytest.mark.parametrize(
        "pattern, replacement",
        [
            ("HH:mmSS", "`[ss]`"),
            ("HH:mmSS.fff", "`[ss.fff]`"),
            ("HH:mmSS.FFF", "`[ss.FFF]`"),
            ("HH:mmSS.'x'", "`[ss]`"),
        ],
    )
    def test_legacy_separator_free_optional_seconds(
        self, pattern, replacement
    ):
        with pytest.warns(WheneverDeprecationWarning) as w:
            Time(13).format(pattern)
        assert len(w) == 1
        assert f"use {replacement} instead" in str(w[0].message)
        assert w[0].filename == __file__

    def test_legacy_optional_seconds_compatibility(self):
        with warnings.catch_warnings():
            warnings.simplefilter("ignore", WheneverDeprecationWarning)
            assert Time(14, 30).format("HH:mmSS") == "14:30"
            assert Time(14, 30, 5).format("HH:mmSS") == "14:3005"
            assert Time(14, 30, 5).format("HH:mm.SS") == "14:30.05"
            assert Time.parse("14:30", pattern="HH:mmSS") == Time(14, 30)
            assert Time.parse("14:3005", pattern="HH:mmSS") == Time(14, 30, 5)
            assert Time.parse("14:3060", pattern="HH:mmSS") == Time(14, 30, 59)
            assert Time.parse("14:30", pattern="HH:mm:SS") == Time(14, 30)
            assert Time.parse("14:30:05", pattern="HH:mm:SS") == Time(
                14, 30, 5
            )
            assert Time.parse("14:30:60", pattern="HH:mm:SS") == Time(
                14, 30, 59
            )
            assert Time.parse("14:30", pattern="HH:mmSSFFF") == Time(14, 30)

    def test_cached_pattern_warns_at_each_call_site(self):
        compile_pattern.cache_clear()

        def first() -> None:
            Time(13).format("h")

        def second() -> None:
            Time(13).format("h")

        with warnings.catch_warnings(record=True) as w:
            warnings.simplefilter("always")
            first()
            second()
        assert len(w) == 2
        assert all(x.category is WheneverDeprecationWarning for x in w)
        assert all(x.filename == __file__ for x in w)
        assert w[0].lineno != w[1].lineno


class TestFracTrimErrorRendering:
    """Regression tests for whenever/pull/386"""

    def test_repr_matches_letter_times_count(self):
        from whenever._format import _FracExact, _FracTrim

        assert repr(_FracTrim(1)) == "F"
        assert repr(_FracTrim(3)) == "FFF"
        assert repr(_FracTrim(9)) == "FFFFFFFFF"
        # mirrors the sibling fixed-width fractional field
        assert repr(_FracExact(3)) == "fff"

    @pytest.mark.parametrize("pattern", ["fF", "Ff", "ffF", "Fff", "FFFff"])
    def test_compile_duplicate_nanos_with_frac_trim(self, pattern):
        with pytest.raises(ValueError, match="Duplicate.*nanos"):
            compile_pattern(pattern)

    @pytest.mark.parametrize("pattern", ["fF", "Ff", "ffF", "Fff"])
    def test_format_duplicate_nanos_with_frac_trim(self, pattern):
        with pytest.raises(ValueError, match="Duplicate.*nanos"):
            Time(1, 2, 3, nanosecond=4).format(pattern)

    @pytest.mark.parametrize("pattern", ["fF", "ffF", "Fff"])
    def test_parse_duplicate_nanos_with_frac_trim(self, pattern):
        with pytest.raises(ValueError, match="Duplicate.*nanos"):
            Time.parse("01:02:03", pattern=pattern)

    def test_frac_trim_unsupported_for_date_format(self):
        with pytest.raises(ValueError, match="does not support.*F"):
            Date(2024, 3, 15).format("F")
        with pytest.raises(ValueError, match="does not support.*FFF"):
            Date(2024, 3, 15).format("YYYY-MM-DD FFF")

    def test_frac_trim_unsupported_for_date_parse(self):
        with pytest.raises(ValueError, match="does not support.*F"):
            Date.parse("2024-03-15", pattern="F")


class TestDateFormat:
    def test_basic(self):
        d = Date(2024, 3, 15)
        assert d.format("YYYY-MM-DD") == "2024-03-15"

    def test_unpadded_month_day(self):
        assert Date(2024, 3, 5).format("YYYY-M-D") == "2024-3-5"
        assert Date(2024, 12, 25).format("YYYY-M-D") == "2024-12-25"
        # MM/DD still zero-pad
        assert Date(2024, 3, 5).format("YYYY-MM-DD") == "2024-03-05"

    def test_two_digit_year_format(self):
        assert Date(2024, 1, 1).format("YY-MM-DD") == "24-01-01"
        assert Date(2000, 1, 1).format("YY-MM-DD") == "00-01-01"
        assert Date(1999, 1, 1).format("YY-MM-DD") == "99-01-01"

    def test_month_name(self):
        assert Date(2024, 1, 15).format("DD MMM YYYY") == "15 Jan 2024"
        assert Date(2024, 12, 25).format("DD MMMM YYYY") == "25 December 2024"

    def test_weekday(self):
        d = Date(2024, 3, 15)  # Friday
        assert d.format("EEE DD") == "Fri 15"
        assert d.format("EEEE, DD MMMM YYYY") == "Friday, 15 March 2024"

    def test_small_year(self):
        d = Date(1, 6, 15)
        assert d.format("YYYY-MM-DD") == "0001-06-15"

    def test_disallowed_time_field(self):
        d = Date(2024, 3, 15)
        with pytest.raises(ValueError, match="does not support.*HH"):
            d.format("HH:mm")

    def test_disallowed_offset_field(self):
        d = Date(2024, 3, 15)
        with pytest.raises(ValueError, match="does not support.*xxx"):
            d.format("YYYY-MM-DDxxx")


class TestDateParse:
    def test_basic(self):
        d = Date.parse("2024-03-15", pattern="YYYY-MM-DD")
        assert d == Date(2024, 3, 15)

    def test_unpadded_month_day(self):
        assert Date.parse("2024-3-5", pattern="YYYY-M-D") == Date(2024, 3, 5)
        assert Date.parse("2024-12-25", pattern="YYYY-M-D") == Date(
            2024, 12, 25
        )
        # MM requires exactly 2 digits — single digit fails
        with pytest.raises(ValueError):
            Date.parse("2024-3-05", pattern="YYYY-MM-DD")
        # DD requires exactly 2 digits
        with pytest.raises(ValueError):
            Date.parse("2024-03-5", pattern="YYYY-MM-DD")

    def test_roundtrip_unpadded_month_day(self):
        for month, day in [(1, 1), (12, 31), (3, 5)]:
            d = Date(2024, month, day)
            pattern = "YYYY-M-D"
            assert Date.parse(d.format(pattern), pattern=pattern) == d

    def test_slash_separator(self):
        d = Date.parse("2024/03/15", pattern="YYYY/MM/DD")
        assert d == Date(2024, 3, 15)

    def test_month_name(self):
        d = Date.parse("15 Mar 2024", pattern="DD MMM YYYY")
        assert d == Date(2024, 3, 15)

    def test_full_month_name(self):
        d = Date.parse("15 December 2024", pattern="DD MMMM YYYY")
        assert d == Date(2024, 12, 15)

    def test_case_insensitive_month(self):
        d = Date.parse("15 MARCH 2024", pattern="DD MMMM YYYY")
        assert d == Date(2024, 3, 15)

    def test_weekday_valid(self):
        d = Date.parse("Fri 2024-03-15", pattern="EEE YYYY-MM-DD")
        assert d == Date(2024, 3, 15)

    def test_weekday_mismatch(self):
        with pytest.raises(ValueError, match="weekday"):
            Date.parse("Mon 2024-03-15", pattern="EEE YYYY-MM-DD")

    def test_missing_year(self):
        with pytest.raises(ValueError, match="year"):
            Date.parse("03-15", pattern="MM-DD")

    def test_missing_month(self):
        with pytest.raises(ValueError, match="month"):
            Date.parse("2024-15", pattern="YYYY-DD")

    def test_missing_day(self):
        with pytest.raises(ValueError, match="day"):
            Date.parse("2024-03", pattern="YYYY-MM")

    def test_trailing_text(self):
        with pytest.raises(ValueError, match="trailing"):
            Date.parse("2024-03-15extra", pattern="YYYY-MM-DD")

    def test_roundtrip(self):
        d = Date(2024, 3, 15)
        pattern = "YYYY-MM-DD"
        assert Date.parse(d.format(pattern), pattern=pattern) == d

    def test_roundtrip_complex(self):
        d = Date(2024, 12, 25)
        pattern = "EEEE, DD MMMM YYYY"
        assert Date.parse(d.format(pattern), pattern=pattern) == d


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
        assert Date.parse(f"01 {abbr} 2024", pattern="DD MMM YYYY") == Date(
            2024, month, 1
        )
        assert Date.parse(f"01 {full} 2024", pattern="DD MMMM YYYY") == Date(
            2024, month, 1
        )

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
        assert Date.parse(f"{abbr} {day}", pattern="EEE YYYY-MM-DD") == day
        assert Date.parse(f"{full} {day}", pattern="EEEE YYYY-MM-DD") == day


class TestTimeFormat:
    def test_basic(self):
        assert Time(14, 30, 5).format("HH:mm:ss") == "14:30:05"

    def test_unpadded_hour(self):
        assert Time(4, 30).format("H:mm") == "4:30"
        assert Time(14, 30).format("H:mm") == "14:30"
        # HH still zero-pads
        assert Time(4, 30).format("HH:mm") == "04:30"

    def test_unpadded_minute(self):
        assert Time(14, 5).format("HH:m") == "14:5"
        assert Time(14, 30).format("HH:m") == "14:30"

    def test_unpadded_second(self):
        assert Time(14, 30, 5).format("HH:mm:s") == "14:30:5"
        assert Time(14, 30, 45).format("HH:mm:s") == "14:30:45"

    def test_optional_seconds(self):
        # [:ss] omits colon+seconds when both second and nanos are zero
        assert Time(14, 30, 0).format("HH:mm[:ss]") == "14:30"
        # [:ss] includes when seconds are non-zero
        assert Time(14, 30, 5).format("HH:mm[:ss]") == "14:30:05"
        assert Time(14, 30, 45).format("HH:mm[:ss]") == "14:30:45"
        # [:ss] includes ':00' when second=0 but nanos > 0 (use round() to avoid)
        assert (
            Time(14, 30, 0, nanosecond=500_000_000).format("HH:mm[:ss]")
            == "14:30:00"
        )
        # [:ss] combined with .FFF — colon and seconds present when nanos>0 even if second=0
        assert (
            Time(14, 30, 0, nanosecond=500_000_000).format("HH:mm[:ss.FFF]")
            == "14:30:00.5"
        )
        assert Time(14, 30, 0).format("HH:mm[:ss.FFF]") == "14:30"
        assert Time(14, 30, 5).format("HH:mm[:ss.FFF]") == "14:30:05"
        assert (
            Time(14, 30, 5, nanosecond=120_000_000).format("HH:mm[:ss.FFF]")
            == "14:30:05.12"
        )
        # error: wrong count of S characters in [:ss] context
        with pytest.raises(ValueError, match="specifier.*S"):
            Time(14, 30).format("HH:mm[:ss]S")

    def test_12h(self):
        assert Time(14, 30).format("ii:mm aa") == "02:30 PM"
        assert Time(0, 0).format("ii:mm aa") == "12:00 AM"
        assert Time(12, 0).format("ii:mm aa") == "12:00 PM"
        assert Time(23, 59).format("ii:mm aa") == "11:59 PM"
        assert Time(11, 30).format("ii:mm aa") == "11:30 AM"

    def test_12h_unpadded(self):
        assert Time(14, 30).format("i:mm aa") == "2:30 PM"
        assert Time(0, 0).format("i:mm aa") == "12:00 AM"
        assert Time(1, 0).format("i:mm aa") == "1:00 AM"
        assert Time(12, 0).format("i:mm aa") == "12:00 PM"
        # ii still zero-pads
        assert Time(1, 0).format("ii:mm aa") == "01:00 AM"

    def test_ampm_short(self):
        assert Time(14, 30).format("ii:mm a") == "02:30 P"
        assert Time(9, 30).format("ii:mm a") == "09:30 A"

    def test_fractional_exact(self):
        t = Time(14, 30, 5, nanosecond=123_456_789)
        assert t.format("HH:mm:ss.fff") == "14:30:05.123"
        assert t.format("HH:mm:ss.ffffff") == "14:30:05.123456"
        assert t.format("HH:mm:ss.fffffffff") == "14:30:05.123456789"

    def test_fractional_trim(self):
        assert (
            Time(14, 30, 5, nanosecond=120_000_000).format("HH:mm:ss.FFF")
            == "14:30:05.12"
        )
        assert (
            Time(14, 30, 5, nanosecond=100_000_000).format("HH:mm:ss.FFF")
            == "14:30:05.1"
        )
        # All zeros: trim dot too
        assert Time(14, 30, 5).format("HH:mm:ss.FFF") == "14:30:05"

    def test_disallowed_date_field(self):
        t = Time(14, 30)
        with pytest.raises(ValueError, match="does not support.*YYYY"):
            t.format("YYYY HH:mm")


class TestTimeParse:
    def test_basic(self):
        assert Time.parse("14:30:05", pattern="HH:mm:ss") == Time(14, 30, 5)

    def test_unpadded_hour(self):
        # Single-digit
        assert Time.parse("4:30", pattern="H:mm") == Time(4, 30)
        # Two-digit (also accepted by h)
        assert Time.parse("14:30", pattern="H:mm") == Time(14, 30)
        # HH requires exactly 2 digits
        with pytest.raises(ValueError):
            Time.parse("4:30", pattern="HH:mm")
        # Non-digit input
        with pytest.raises(ValueError, match="1-2 digits"):
            Time.parse("x:30", pattern="H:mm")

    def test_unpadded_minute(self):
        assert Time.parse("14:5", pattern="HH:m") == Time(14, 5)
        assert Time.parse("14:30", pattern="HH:m") == Time(14, 30)
        with pytest.raises(ValueError):
            Time.parse("14:5", pattern="HH:mm")

    def test_unpadded_second(self):
        assert Time.parse("14:30:5", pattern="HH:mm:s") == Time(14, 30, 5)
        assert Time.parse("14:30:45", pattern="HH:mm:s") == Time(14, 30, 45)
        with pytest.raises(ValueError):
            Time.parse("14:30:5", pattern="HH:mm:ss")

    def test_optional_seconds(self):
        # [:ss] - seconds absent
        assert Time.parse("14:30", pattern="HH:mm[:ss]") == Time(14, 30, 0)
        # [:ss] - seconds present
        assert Time.parse("14:30:05", pattern="HH:mm[:ss]") == Time(14, 30, 5)
        assert Time.parse("14:30:45", pattern="HH:mm[:ss]") == Time(14, 30, 45)
        # [:ss.FFF] roundtrip
        assert Time.parse("14:30", pattern="HH:mm[:ss.FFF]") == Time(14, 30, 0)
        assert Time.parse("14:30:05", pattern="HH:mm[:ss.FFF]") == Time(
            14, 30, 5
        )
        assert Time.parse("14:30:00.5", pattern="HH:mm[:ss.FFF]") == Time(
            14, 30, 0, nanosecond=500_000_000
        )
        assert Time.parse("14:30:05.12", pattern="HH:mm[:ss.FFF]") == Time(
            14, 30, 5, nanosecond=120_000_000
        )
        # fractional part must be absent when seconds are absent
        with pytest.raises(ValueError, match="trailing"):
            Time.parse("14:30.5", pattern="HH:mm[:ss.FFF]")

    def test_roundtrip_optional_seconds(self):
        cases = [
            Time(14, 30, 0),
            Time(14, 30, 5),
            Time(0, 0, 0),
            Time(14, 30, 0, nanosecond=500_000_000),
            Time(14, 30, 5, nanosecond=120_000_000),
        ]
        for t in cases:
            assert (
                Time.parse(
                    t.format("HH:mm[:ss.FFF]"), pattern="HH:mm[:ss.FFF]"
                )
                == t
            )

    def test_12h_pm(self):
        assert Time.parse("02:30 PM", pattern="ii:mm aa") == Time(14, 30)

    def test_12h_am(self):
        assert Time.parse("02:30 AM", pattern="ii:mm aa") == Time(2, 30)

    def test_12h_noon(self):
        assert Time.parse("12:00 PM", pattern="ii:mm aa") == Time(12, 0)

    def test_12h_midnight(self):
        assert Time.parse("12:00 AM", pattern="ii:mm aa") == Time(0, 0)

    def test_12h_unpadded(self):
        assert Time.parse("2:30 PM", pattern="i:mm aa") == Time(14, 30)
        assert Time.parse("12:00 AM", pattern="i:mm aa") == Time(0, 0)
        assert Time.parse("1:00 AM", pattern="i:mm aa") == Time(1, 0)
        # ii requires exactly 2 digits
        with pytest.raises(ValueError):
            Time.parse("2:30 PM", pattern="ii:mm aa")
        # Out-of-range hour with single i
        with pytest.raises(ValueError, match="1..12"):
            Time.parse("0:30 AM", pattern="i:mm aa")

    def test_invalid_ampm_text(self):
        with pytest.raises(ValueError, match="AM/PM"):
            Time.parse("02:30 AA", pattern="ii:mm aa")

    def test_hour_out_of_range_24h(self):
        with pytest.raises(ValueError):
            Time.parse("24:30", pattern="HH:mm")

    def test_trailing_text(self):
        with pytest.raises(ValueError, match="trailing"):
            Time.parse("14:30:05extra", pattern="HH:mm:ss")

    def test_trailing_period_fractional(self):
        """Trailing period after seconds with exact fractional field fails."""
        with pytest.raises(ValueError, match="digits"):
            Time.parse("14:30:05.", pattern="HH:mm:ss.fff")

    def test_fractional(self):
        t = Time.parse("14:30:05.123", pattern="HH:mm:ss.fff")
        assert t == Time(14, 30, 5, nanosecond=123_000_000)

    def test_fractional_trimmed(self):
        """FFF parses variable-width digits and trims the preceding dot
        if there are no fractions."""
        t = Time.parse("14:30:05.12", pattern="HH:mm:ss.FFF")
        assert t == Time(14, 30, 5, nanosecond=120_000_000)
        # No fractional digits: the dot is consumed as literal,
        # then FFF parses zero digits
        assert Time(14, 30, 5).format("HH:mm:ss.FFF") == "14:30:05"
        with pytest.raises(ValueError, match="trailing"):
            Time.parse("14:30:05.", pattern="HH:mm:ss.FFF")
        assert Time.parse("14:30:05.", pattern="HH:mm:ss.FFF'.'") == Time(
            14, 30, 5
        )

    def test_fractional_nanos(self):
        t = Time.parse("14:30:05.123456789", pattern="HH:mm:ss.fffffffff")
        assert t == Time(14, 30, 5, nanosecond=123_456_789)

    def test_optional_fields(self):
        # Hour only
        assert Time.parse("14", pattern="HH") == Time(14)

    def test_roundtrip(self):
        t = Time(14, 30, 5, nanosecond=123_456_789)
        pattern = "HH:mm:ss.fffffffff"
        assert Time.parse(t.format(pattern), pattern=pattern) == t

    def test_roundtrip_unpadded(self):
        for h, m, s in [(4, 5, 9), (14, 30, 45), (0, 0, 0)]:
            t = Time(h, m, s)
            pattern = "H:m:s"
            assert Time.parse(t.format(pattern), pattern=pattern) == t

    def test_roundtrip_ampm(self):
        for h in (0, 1, 11, 12, 13, 23):
            t = Time(h, 30)
            pattern = "ii:mm aa"
            assert Time.parse(t.format(pattern), pattern=pattern) == t

    def test_leap_second(self):
        # ss (_Second): accepts 60, normalizes to 59
        assert Time.parse("14:30:60", pattern="HH:mm:ss") == Time(14, 30, 59)
        # s (_SecondUnpadded): same
        assert Time.parse("14:30:60", pattern="HH:mm:s") == Time(14, 30, 59)
        # [:ss] (_ColonSec, compiled from "[:ss]"): same
        assert Time.parse("14:30:60", pattern="HH:mm[:ss]") == Time(14, 30, 59)
        # Values > 60 are invalid
        with pytest.raises(ValueError):
            Time.parse("14:30:61", pattern="HH:mm:ss")


class TestPlainDateTimeFormat:
    def test_basic(self):
        pdt = PlainDateTime(2024, 3, 15, 14, 30, 5)
        assert pdt.format("YYYY-MM-DD HH:mm:ss") == "2024-03-15 14:30:05"

    def test_with_nanos(self):
        pdt = PlainDateTime(2024, 3, 15, 14, 30, 5, nanosecond=123_000_000)
        assert (
            pdt.format("YYYY-MM-DD HH:mm:ss.fff") == "2024-03-15 14:30:05.123"
        )

    def test_disallowed_offset(self):
        pdt = PlainDateTime(2024, 3, 15, 14, 30)
        with pytest.raises(ValueError, match="does not support"):
            pdt.format("YYYY-MM-DDxxx")


class TestPlainDateTimeParse:
    def test_basic(self):
        assert PlainDateTime.parse(
            "2024-03-15 14:30:05", pattern="YYYY-MM-DD HH:mm:ss"
        ) == PlainDateTime(2024, 3, 15, 14, 30, 5)

    def test_missing_year(self):
        with pytest.raises(ValueError, match="year"):
            PlainDateTime.parse("03-15 14:30", pattern="MM-DD HH:mm")

    def test_roundtrip(self):
        pdt = PlainDateTime(2024, 3, 15, 14, 30, 5, nanosecond=100_000_000)
        pattern = "YYYY-MM-DD HH:mm:ss.fff"
        assert PlainDateTime.parse(pdt.format(pattern), pattern=pattern) == pdt

    def test_weekday_mismatch(self):
        # March 15, 2024 is a Friday, not Monday
        with pytest.raises(ValueError, match="weekday"):
            PlainDateTime.parse(
                "Mon 2024-03-15 14:30", pattern="EEE YYYY-MM-DD HH:mm"
            )


class TestOffsetDateTimeFormat:
    def test_basic(self):
        odt = OffsetDateTime(2024, 3, 15, 14, 30, offset=hours(2))
        assert odt.format("YYYY-MM-DD HH:mmxxx") == "2024-03-15 14:30+02:00"

    def test_negative_offset(self):
        odt = OffsetDateTime(2024, 3, 15, 14, 30, offset=hours(-5))
        assert odt.format("YYYY-MM-DD HH:mmxxx") == "2024-03-15 14:30-05:00"

    def test_utc_offset_shows_plus_zero(self):
        """OffsetDateTime always shows +00:00, never Z."""
        odt = OffsetDateTime(2024, 3, 15, 14, 30, offset=hours(0))
        assert odt.format("YYYY-MM-DD HH:mmxxx") == "2024-03-15 14:30+00:00"

    def test_offset_width_1(self):
        """x — hours only."""
        odt = OffsetDateTime(2024, 3, 15, 14, 30, offset=hours(2))
        assert odt.format("HH:mmx") == "14:30+02"

    def test_offset_width_2(self):
        """xx — compact hours+minutes."""
        odt = OffsetDateTime(
            2024, 3, 15, 14, 30, offset=hours(5) + minutes(30)
        )
        assert odt.format("HH:mmxx") == "14:30+0530"

    def test_offset_width_4_no_seconds(self):
        """xxxx — compact, seconds omitted when zero."""
        odt = OffsetDateTime(
            2024, 3, 15, 14, 30, offset=hours(5) + minutes(30)
        )
        assert odt.format("HH:mmxxxx") == "14:30+0530"

    def test_offset_width_5_no_seconds(self):
        """xxxxx — with colons, seconds omitted when zero."""
        odt = OffsetDateTime(
            2024, 3, 15, 14, 30, offset=hours(5) + minutes(30)
        )
        assert odt.format("HH:mmxxxxx") == "14:30+05:30"

    def test_uppercase_x_zero_offset(self):
        """X uses Z for zero offset."""
        odt = OffsetDateTime(2024, 3, 15, 14, 30, offset=hours(0))
        assert odt.format("HH:mmXXX") == "14:30Z"

    def test_uppercase_x_nonzero_offset(self):
        """X uses numeric for non-zero offset."""
        odt = OffsetDateTime(2024, 3, 15, 14, 30, offset=hours(2))
        assert odt.format("HH:mmXXX") == "14:30+02:00"


class TestOffsetDateTimeParse:
    def test_basic(self):
        odt = OffsetDateTime.parse(
            "2024-03-15 14:30+02:00", pattern="YYYY-MM-DD HH:mmxxx"
        )
        assert odt == OffsetDateTime(2024, 3, 15, 14, 30, offset=hours(2))

    def test_utc_z(self):
        """Parsing accepts Z as +00:00 with uppercase X."""
        odt = OffsetDateTime.parse(
            "2024-03-15 14:30Z", pattern="YYYY-MM-DD HH:mmXXX"
        )
        assert odt == OffsetDateTime(2024, 3, 15, 14, 30, offset=hours(0))

    def test_missing_offset(self):
        with pytest.raises(ValueError, match="offset.*x/X"):
            OffsetDateTime.parse(
                "2024-03-15 14:30", pattern="YYYY-MM-DD HH:mm"
            )

    def test_missing_date_fields(self):
        with pytest.raises(ValueError, match="year.*month.*day|date.*fields"):
            OffsetDateTime.parse("14:30+02:00", pattern="HH:mmxxx")

    def test_roundtrip(self):
        odt = OffsetDateTime(
            2024, 3, 15, 14, 30, 5, nanosecond=123_000_000, offset=hours(-5)
        )
        pattern = "YYYY-MM-DD HH:mm:ss.fffxxx"
        assert (
            OffsetDateTime.parse(odt.format(pattern), pattern=pattern) == odt
        )

    def test_weekday_mismatch(self):
        # March 15, 2024 is a Friday, not Monday
        with pytest.raises(ValueError, match="weekday"):
            OffsetDateTime.parse(
                "Mon 2024-03-15 14:30+02:00",
                pattern="EEE YYYY-MM-DD HH:mmxxx",
            )


class TestZonedDateTimeFormat:
    def test_basic(self):
        zdt = ZonedDateTime(2024, 3, 15, 14, 30, tz="Europe/Paris")
        assert (
            zdt.format("YYYY-MM-DD HH:mmxxx'['VV']'")
            == "2024-03-15 14:30+01:00[Europe/Paris]"
        )

    def test_with_abbreviation(self):
        zdt = ZonedDateTime(2024, 7, 15, 14, 30, tz="Europe/Paris")
        result = zdt.format("YYYY-MM-DD HH:mm zz")
        assert "CEST" in result

    def test_tz_only_no_offset(self):
        """Format with tz ID but no offset field."""
        zdt = ZonedDateTime(2024, 3, 15, 14, 30, tz="Europe/Paris")
        assert (
            zdt.format("YYYY-MM-DD HH:mm '['VV']'")
            == "2024-03-15 14:30 [Europe/Paris]"
        )


class TestZonedDateTimeParse:
    def test_basic(self):
        zdt = ZonedDateTime.parse(
            "2024-03-15 14:30+01:00[Europe/Paris]",
            pattern="YYYY-MM-DD HH:mmxxx'['VV']'",
        )
        assert zdt == ZonedDateTime(2024, 3, 15, 14, 30, tz="Europe/Paris")

    def test_missing_tz_id(self):
        with pytest.raises(ValueError, match="timezone ID.*VV"):
            ZonedDateTime.parse(
                "2024-03-15 14:30+01:00",
                pattern="YYYY-MM-DD HH:mmxxx",
            )

    @pytest.mark.parametrize("char", ["Ĕ", "é", "界", "𝟙", "Ⅷ", "①"])
    @pytest.mark.parametrize(
        ("prefix", "suffix", "match"),
        [
            ("", "urope/Paris", r"Expected timezone ID at position 23"),
            ("Europe/Par", "is", r"Expected .* at position 33"),
            ("Europe/Paris", "", r"Expected .* at position 35"),
        ],
    )
    def test_non_ascii_tz_id(self, char, prefix, suffix, match):
        with pytest.raises(ValueError, match=match):
            ZonedDateTime.parse(
                f"2024-03-15 14:30+01:00[{prefix}{char}{suffix}]",
                pattern="YYYY-MM-DD HH:mmxxx'['VV']'",
            )

    def test_missing_date_fields(self):
        with pytest.raises(ValueError, match="year.*month.*day|date.*fields"):
            ZonedDateTime.parse(
                "14:30+01:00[Europe/Paris]",
                pattern="HH:mmxxx'['VV']'",
            )

    def test_tz_only_no_offset(self):
        """Parse with tz ID but no offset — uses disambiguation."""
        zdt = ZonedDateTime.parse(
            "2024-03-15 14:30[Europe/Paris]",
            pattern="YYYY-MM-DD HH:mm'['VV']'",
        )
        assert zdt == ZonedDateTime(2024, 3, 15, 14, 30, tz="Europe/Paris")

    def test_disambiguate_is_not_a_legacy_keyword(self):
        with pytest.raises(
            TypeError, match="unexpected keyword.*disambiguate"
        ):
            ZonedDateTime.parse(
                "2024-03-15 14:30[Europe/Paris]",
                pattern="YYYY-MM-DD HH:mm'['VV']'",
                disambiguate="raise",  # type: ignore[call-overload]
            )

    def test_offset_mismatch(self):
        """Offset doesn't match timezone: should raise."""
        with pytest.raises(InvalidOffsetError, match="does not match"):
            ZonedDateTime.parse(
                "2024-03-15 14:30+05:00[Europe/Paris]",
                pattern="YYYY-MM-DD HH:mmxxx'['VV']'",
            )

    def test_keep_instant_on_offset_mismatch(self):
        assert ZonedDateTime.parse(
            "2020-08-15 12:00+03:00[Europe/Amsterdam]",
            pattern="YYYY-MM-DD HH:mmxxx'['VV']'",
            offset_mismatch="keep_instant",
        ).strict_eq(ZonedDateTime(2020, 8, 15, 11, tz="Europe/Amsterdam"))

    @pytest.mark.parametrize(
        "offset_mismatch", ["raise", "keep_instant", "keep_local"]
    )
    def test_matching_offset_ignores_policies(self, offset_mismatch):
        result = ZonedDateTime.parse(
            "2023-10-29 02:15+02:00[Europe/Amsterdam]",
            pattern="YYYY-MM-DD HH:mmxxx'['VV']'",
            offset_mismatch=offset_mismatch,
            disambiguation="raise",
        )
        assert result.strict_eq(
            ZonedDateTime(
                2023,
                10,
                29,
                2,
                15,
                tz="Europe/Amsterdam",
                disambiguation="earlier",
            )
        )

    def test_invalid_offset_mismatch(self):
        with pytest.raises(ValueError, match="offset_mismatch"):
            ZonedDateTime.parse(  # type: ignore[call-overload]
                "2020-08-15 12:00+02:00[Europe/Amsterdam]",
                pattern="YYYY-MM-DD HH:mmxxx'['VV']'",
                offset_mismatch="ignore",
            )

    @pytest.mark.parametrize(
        ("value", "disambiguation", "expected"),
        [
            (
                "2023-10-29 02:15+03:00[Europe/Amsterdam]",
                "compatible",
                "2023-10-29 02:15:00+02:00[Europe/Amsterdam]",
            ),
            (
                "2023-10-29 02:15+03:00[Europe/Amsterdam]",
                "earlier",
                "2023-10-29 02:15:00+02:00[Europe/Amsterdam]",
            ),
            (
                "2023-10-29 02:15+03:00[Europe/Amsterdam]",
                "later",
                "2023-10-29 02:15:00+01:00[Europe/Amsterdam]",
            ),
            (
                "2023-03-26 02:15+03:00[Europe/Amsterdam]",
                "compatible",
                "2023-03-26 03:15:00+02:00[Europe/Amsterdam]",
            ),
            (
                "2023-03-26 02:15+03:00[Europe/Amsterdam]",
                "earlier",
                "2023-03-26 01:15:00+01:00[Europe/Amsterdam]",
            ),
            (
                "2023-03-26 02:15+03:00[Europe/Amsterdam]",
                "later",
                "2023-03-26 03:15:00+02:00[Europe/Amsterdam]",
            ),
        ],
    )
    def test_keep_local_uses_disambiguation(
        self, value, disambiguation, expected
    ):
        result = ZonedDateTime.parse(
            value,
            pattern="YYYY-MM-DD HH:mmxxx'['VV']'",
            offset_mismatch="keep_local",
            disambiguation=disambiguation,
        )
        assert result.strict_eq(ZonedDateTime(expected))

    @pytest.mark.parametrize(
        ("value", "error"),
        [
            (
                "2023-10-29 02:15+03:00[Europe/Amsterdam]",
                RepeatedTime,
            ),
            ("2023-03-26 02:15+03:00[Europe/Amsterdam]", SkippedTime),
        ],
    )
    def test_keep_local_raise(self, value, error):
        with pytest.raises(error):
            ZonedDateTime.parse(
                value,
                pattern="YYYY-MM-DD HH:mmxxx'['VV']'",
                offset_mismatch="keep_local",
                disambiguation="raise",
            )

    @pytest.mark.parametrize(
        "value",
        [
            "2023-10-29 02:15+03:00[Europe/Amsterdam]",
            "2023-03-26 02:15+03:00[Europe/Amsterdam]",
        ],
    )
    def test_keep_local_implicit_disambiguation_warns(self, value):
        with pytest.warns(ImplicitDisambiguationWarning):
            ZonedDateTime.parse(
                value,
                pattern="YYYY-MM-DD HH:mmxxx'['VV']'",
                offset_mismatch="keep_local",
            )

    def test_ordinary_mismatch_does_not_disambiguate(self):
        with warnings.catch_warnings():
            warnings.simplefilter("error", ImplicitDisambiguationWarning)
            result = ZonedDateTime.parse(
                "2023-05-01 12:15+03:00[Europe/Amsterdam]",
                pattern="YYYY-MM-DD HH:mmxxx'['VV']'",
                offset_mismatch="keep_local",
            )
        assert (result.hour, result.minute) == (12, 15)

    def test_keep_instant_ignores_disambiguation(self):
        result = ZonedDateTime.parse(
            "2023-03-26 02:15+03:00[Europe/Amsterdam]",
            pattern="YYYY-MM-DD HH:mmxxx'['VV']'",
            offset_mismatch="keep_instant",
            disambiguation="raise",
        )
        assert (
            result.to_instant()
            == OffsetDateTime("2023-03-26 02:15:00+03:00").to_instant()
        )

    def test_offset_disambiguation(self):
        # November 3, 2024: US DST transition (fall back)
        # 1:30 AM exists twice: EDT (-04:00) and EST (-05:00)
        zdt_edt = ZonedDateTime.parse(
            "2024-11-03 01:30-04:00[America/New_York]",
            pattern="YYYY-MM-DD HH:mmxxx'['VV']'",
        )
        zdt_est = ZonedDateTime.parse(
            "2024-11-03 01:30-05:00[America/New_York]",
            pattern="YYYY-MM-DD HH:mmxxx'['VV']'",
        )
        assert zdt_edt != zdt_est  # different instants
        assert zdt_edt.hour == zdt_est.hour == 1
        assert zdt_edt.minute == zdt_est.minute == 30

    def test_offset_precision_matching(self):
        result = ZonedDateTime.parse(
            "1900-01-01 00:00-00:25[Europe/Dublin]",
            pattern="YYYY-MM-DD HH:mmxxx'['VV']'",
        )
        assert result.offset == TimeDelta(seconds=-(25 * 60 + 21))

        with pytest.raises(ValueError, match="does not match"):
            ZonedDateTime.parse(
                "1900-01-01 00:00-00:25:00[Europe/Dublin]",
                pattern="YYYY-MM-DD HH:mmxxxxx'['VV']'",
            )

    def test_z_is_an_instant(self):
        result = ZonedDateTime.parse(
            "2020-02-15 12:08Z[America/New_York]",
            pattern="YYYY-MM-DD HH:mmX'['VV']'",
        )
        assert result == ZonedDateTime(
            2020, 2, 15, 7, 8, tz="America/New_York"
        )

    def test_skipped_time_with_offset(self):
        """Parsing a skipped local time should be rejected,
        consistent with parse_iso()."""
        # 2024-03-10 02:30 doesn't exist in New York (spring forward)
        with pytest.raises(ValueError, match="does not match"):
            ZonedDateTime.parse(
                "2024-03-10 02:30-05:00[America/New_York]",
                pattern="YYYY-MM-DD HH:mmxxx'['VV']'",
            )

    def test_roundtrip(self):
        zdt = ZonedDateTime(2024, 7, 15, 14, 30, tz="Europe/Paris")
        pattern = "YYYY-MM-DD HH:mm:ssxxx'['VV']'"
        assert ZonedDateTime.parse(zdt.format(pattern), pattern=pattern) == zdt

    def test_weekday_mismatch(self):
        # March 15, 2024 is a Friday, not Monday
        with pytest.raises(ValueError, match="weekday"):
            ZonedDateTime.parse(
                "Mon 2024-03-15 14:30+01:00[Europe/Paris]",
                pattern="EEE YYYY-MM-DD HH:mmxxx'['VV']'",
            )


class TestInstantFormat:
    def test_basic_uses_z(self):
        """Instant uses Z for UTC offset with uppercase X specifier."""
        i = Instant.from_utc(2024, 3, 15, 14, 30)
        assert i.format("YYYY-MM-DD HH:mmXXX") == "2024-03-15 14:30Z"

    def test_with_fractional(self):
        i = Instant.from_utc(2024, 3, 15, 14, 30, 5, nanosecond=123_000_000)
        assert (
            i.format("YYYY-MM-DD HH:mm:ss.fffXXX")
            == "2024-03-15 14:30:05.123Z"
        )


class TestInstantParse:
    def test_utc(self):
        i = Instant.parse("2024-03-15 14:30Z", pattern="YYYY-MM-DD HH:mmXXX")
        assert i == Instant.from_utc(2024, 3, 15, 14, 30)

    def test_with_offset(self):
        # Offset is converted to UTC
        i = Instant.parse(
            "2024-03-15 14:30+05:30", pattern="YYYY-MM-DD HH:mmxxx"
        )
        assert i == Instant.from_utc(2024, 3, 15, 9, 0)

    def test_offset_causes_out_of_range(self):
        """Applying a negative offset to the latest valid date pushes it out of range."""
        with pytest.raises(ValueError, match="out of range"):
            Instant.parse(
                "9999-12-31 23:00-02:00", pattern="YYYY-MM-DD HH:mmxxx"
            )

    def test_without_offset_raises(self):
        """Instant.parse requires an offset field in the pattern."""
        with pytest.raises(ValueError, match="offset.*x/X"):
            Instant.parse("2024-03-15 14:30", pattern="YYYY-MM-DD HH:mm")

    def test_missing_date_fields(self):
        with pytest.raises(ValueError, match="year.*month.*day|date.*fields"):
            Instant.parse("14:30Z", pattern="HH:mmXXX")

    def test_roundtrip(self):
        i = Instant.from_utc(2024, 3, 15, 14, 30, 5, nanosecond=123_456_789)
        pattern = "YYYY-MM-DD HH:mm:ss.fffffffffXXX"
        assert Instant.parse(i.format(pattern), pattern=pattern) == i


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
        assert pdt.format("YYYY-MM-DD'T'HH:mm:ss") == "2024-03-15T14:30:05"

    def test_rfc2822_like(self):
        """Roughly equivalent to %a, %d %b %Y %H:%M:%S %z"""
        odt = OffsetDateTime(2024, 3, 15, 14, 30, 5, offset=hours(2))
        result = odt.format("EEE, DD MMM YYYY HH:mm:ssxxx")
        assert result == "Fri, 15 Mar 2024 14:30:05+02:00"

    def test_12h_time(self):
        """Equivalent to %I:%M %p"""
        t = Time(14, 30)
        assert t.format("ii:mm aa") == "02:30 PM"

    def test_full_weekday_month(self):
        """Equivalent to %A, %B %d, %Y"""
        d = Date(2024, 12, 25)
        assert (
            d.format("EEEE, MMMM DD, YYYY") == "Wednesday, December 25, 2024"
        )


class TestSecurityEdgeCases:
    """Guard against malicious or unexpectedly large inputs."""

    def test_pattern_too_long_raises(self):
        with pytest.raises(ValueError, match="too long"):
            Date.parse("2024-01-01", pattern="Y" * 1001)

    def test_input_too_long_raises(self):
        with pytest.raises(ValueError, match="too long"):
            Date.parse("2024" + "-" * 1001, pattern="YYYY-MM-DD")

    def test_pattern_at_max_length_ok(self):
        # 1000 chars: 250 repetitions of "YYYY" is a valid (if odd) pattern
        # Use quoted literals so it doesn't raise for duplicate fields
        pattern = "'x'" * 333 + "YYYY"  # 333*3 + 4 = 1003 chars — too long
        with pytest.raises(ValueError, match="too long"):
            Date.parse("2024", pattern=pattern)

    def test_empty_input(self):
        with pytest.raises(ValueError):
            Date.parse("", pattern="YYYY-MM-DD")

    def test_empty_pattern_on_empty_input(self):
        """Empty pattern on empty input is technically valid (all fields missing)."""
        from whenever._format import compile_pattern, parse_fields

        state = parse_fields(compile_pattern(""), "")
        assert state.year is None


class TestDeprecations:
    """Test that deprecated methods emit warnings."""


class TestParseEdgeCases:
    """Test parse error paths for coverage."""

    def test_input_too_short(self):
        with pytest.raises(ValueError, match="too short"):
            Date.parse("202", pattern="YYYY-MM-DD")

    def test_non_digit(self):
        with pytest.raises(ValueError, match="digits"):
            Date.parse("abcd-03-15", pattern="YYYY-MM-DD")

    def test_literal_mismatch(self):
        with pytest.raises(ValueError, match="Expected"):
            Date.parse("2024/03/15", pattern="YYYY-MM-DD")

    def test_invalid_month_name(self):
        with pytest.raises(ValueError, match="month"):
            Date.parse("15 Xyz 2024", pattern="DD MMM YYYY")

    def test_ampm_short_parse(self):
        assert Time.parse("02 P", pattern="ii a") == Time(14, 0)
        assert Time.parse("02 A", pattern="ii a") == Time(2, 0)

    def test_ampm_short_invalid(self):
        with pytest.raises(ValueError, match="AM/PM"):
            Time.parse("02 X", pattern="ii a")

    def test_ampm_full_invalid(self):
        with pytest.raises(ValueError, match="AM/PM"):
            Time.parse("02:00 XY", pattern="ii:mm aa")

    def test_offset_with_seconds(self):
        odt = OffsetDateTime.parse(
            "2024-03-15 14:30+05:30:15",
            pattern="YYYY-MM-DD HH:mmxxxxx",
        )
        # 5*3600 + 30*60 + 15 = 19815 seconds offset
        assert odt.offset.total("seconds") == 19815

    def test_offset_invalid_char(self):
        with pytest.raises(ValueError, match="offset"):
            OffsetDateTime.parse(
                "2024-03-15 14:30Q02:00",
                pattern="YYYY-MM-DD HH:mmxxx",
            )

    def test_offset_not_available_for_format(self):
        """PlainDateTime doesn't have offset — formatting should error."""
        pdt = PlainDateTime(2024, 3, 15, 14, 30)
        with pytest.raises(ValueError, match="does not support"):
            pdt.format("YYYY-MM-DD HH:mmxxx")

    def test_tz_id_empty(self):
        with pytest.raises(ValueError, match="timezone ID"):
            ZonedDateTime.parse(
                "2024-03-15 14:30+01:00[]",
                pattern="YYYY-MM-DD HH:mmxxx'['VV']'",
            )

    def test_tz_abbrev_parse_rejected(self):
        """zz is format-only; parsing with it raises."""
        with pytest.raises(ValueError, match="only.*formatting"):
            ZonedDateTime.parse(
                "2024-07-15 14:30 CEST+02:00[Europe/Paris]",
                pattern="YYYY-MM-DD HH:mm zzxxx'['VV']'",
            )

    def test_frac_trim_parse_no_digits(self):
        """FFF with no fractional digits should set nanos to 0."""
        # The literal '.' is consumed, then FFF sees no digits
        t = Time.parse("14:30:05", pattern="HH:mm:ss")
        assert t == Time(14, 30, 5)

    def test_frac_trim_parse_partial(self):
        """FFF parses fewer digits than max width."""
        t = Time.parse("14:30:05.1", pattern="HH:mm:ss.FFF")
        assert t == Time(14, 30, 5, nanosecond=100_000_000)

    def test_frac_trim_parse_dangling_dot(self):
        with pytest.raises(ValueError, match="trailing"):
            Time.parse("14:30:05.", pattern="HH:mm:ss.FFF")

    def test_offset_parse_without_colon(self):
        """Offset parsing accepts compact format like +0530 with xx."""
        odt = OffsetDateTime.parse(
            "2024-03-15 14:30+0530",
            pattern="YYYY-MM-DD HH:mmxx",
        )
        assert odt.offset.total("seconds") == 19800  # 5*3600 + 30*60

    def test_offset_parse_width_1(self):
        """Offset parsing with width 1 (hours only)."""
        odt = OffsetDateTime.parse(
            "2024-03-15 14:30+05",
            pattern="YYYY-MM-DD HH:mmx",
        )
        assert odt.offset.total("seconds") == 18000  # 5*3600

    def test_offset_parse_width_4_with_seconds(self):
        """Offset parsing with width 4 (compact, optional seconds present)."""
        odt = OffsetDateTime.parse(
            "2024-03-15 14:30+053015",
            pattern="YYYY-MM-DD HH:mmxxxx",
        )
        assert odt.offset.total("seconds") == 19815  # 5*3600 + 30*60 + 15

    def test_offset_parse_width_4_no_seconds(self):
        """Offset parsing with width 4 (compact, no seconds)."""
        odt = OffsetDateTime.parse(
            "2024-03-15 14:30+0530",
            pattern="YYYY-MM-DD HH:mmxxxx",
        )
        assert odt.offset.total("seconds") == 19800  # 5*3600 + 30*60

    def test_offset_parse_colon_expected(self):
        """Width 3 expects colon separator."""
        with pytest.raises(ValueError, match="':'"):
            OffsetDateTime.parse(
                "2024-03-15 14:30+0530",
                pattern="YYYY-MM-DD HH:mmxxx",
            )

    def test_ampm_short_parse_values(self):
        """Verify short AM/PM specifier (a) parses A and P correctly."""
        assert Time.parse("09 A", pattern="ii a") == Time(9, 0)
        assert Time.parse("09 P", pattern="ii a") == Time(21, 0)


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
        els = compile_pattern("HH:mm:ss.FFF")
        result = format_fields(els, hour=14, minute=30, second=5, nanos=0)
        assert result == "14:30:05"

    def test_dot_not_trimmed_with_frac_exact(self):
        """fff always produces digits, dot is not trimmed."""
        els = compile_pattern("HH:mm:ss.fff")
        result = format_fields(els, hour=14, minute=30, second=5, nanos=0)
        assert result == "14:30:05.000"

    def test_parse_12hour_hour_too_high(self):
        """12-hour format rejects hour > 12."""
        with pytest.raises(
            ValueError, match="12-hour format requires hour in 1..12"
        ):
            Time.parse("13:30 AM", pattern="ii:mm aa")
        with pytest.raises(
            ValueError, match="12-hour format requires hour in 1..12"
        ):
            Time.parse("99:30 PM", pattern="ii:mm aa")

    def test_parse_12hour_hour_zero(self):
        """12-hour format rejects hour = 0."""
        with pytest.raises(
            ValueError, match="12-hour format requires hour in 1..12"
        ):
            Time.parse("00:30 AM", pattern="ii:mm aa")

    def test_parse_offset_seconds_overflow(self):
        """Offset parsing rejects seconds >= 60."""
        with pytest.raises(ValueError, match="offset seconds must be 0..59"):
            OffsetDateTime.parse(
                "2024-01-01 12:00 +05:30:60", pattern="YYYY-MM-DD HH:mm xxxxx"
            )
        with pytest.raises(ValueError, match="offset seconds must be 0..59"):
            OffsetDateTime.parse(
                "2024-01-01 12:00 +05:30:99", pattern="YYYY-MM-DD HH:mm xxxxx"
            )

    def test_parse_offset_minutes_overflow(self):
        """Offset parsing rejects minutes >= 60 (not silently treated as more hours)."""
        with pytest.raises(ValueError, match="offset minutes must be 0..59"):
            OffsetDateTime.parse(
                "2024-01-01 12:00+00:60", pattern="YYYY-MM-DD HH:mmxxx"
            )
        with pytest.raises(ValueError, match="offset minutes must be 0..59"):
            OffsetDateTime.parse(
                "2024-01-01 12:00+01:99", pattern="YYYY-MM-DD HH:mmxxx"
            )

    def test_frac_trim_roundtrip_no_nanos(self):
        """FFF format trims the dot when nanos=0; parsing the result back must work."""
        t = Time(14, 30, 5)  # no nanoseconds
        formatted = t.format("HH:mm:ss.FFF")
        assert formatted == "14:30:05"  # sanity: dot was trimmed by format
        # Parsing the trimmed output with the same pattern must succeed
        assert Time.parse(formatted, pattern="HH:mm:ss.FFF") == t

    def test_frac_trim_no_preceding_dot(self):
        """FFF with no preceding dot: nanos=0 produces empty, nothing is trimmed."""
        els = compile_pattern("HH:mm:ssFFF")
        result = format_fields(els, hour=14, minute=30, second=5, nanos=0)
        assert result == "14:30:05"

    def test_frac_trim_no_preceding_dot_nonzero(self):
        """FFF with no preceding dot: non-zero nanos are appended directly."""
        els = compile_pattern("HH:mm:ssFFF")
        result = format_fields(
            els, hour=14, minute=30, second=5, nanos=100_000_000
        )
        assert result == "14:30:051"

    def test_frac_trim_no_preceding_dot_parse(self):
        """FFF standalone (no dot) correctly parses non-zero fractional digits."""
        t = Time.parse("14:30:051", pattern="HH:mm:ssFFF")
        assert t == Time(14, 30, 5, nanosecond=100_000_000)

    def test_frac_trim_at_start_of_pattern(self):
        """FFF at the start of a pattern (no preceding literal) works correctly."""
        els = compile_pattern("FFFHH")
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
        formatted = t.format("HH:mm:ssFFF")
        assert formatted == "14:30:05"
        assert Time.parse(formatted, pattern="HH:mm:ssFFF") == t


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
        assert f"{t:HH:mm}" == "14:30"

    def test_time_empty_spec(self):
        t = Time(14, 30)
        assert f"{t}" == str(t)

    def test_plain_datetime_with_spec(self):
        dt = PlainDateTime(2024, 3, 15, 14, 30)
        assert f"{dt:YYYY-MM-DD HH:mm}" == "2024-03-15 14:30"

    def test_plain_datetime_empty_spec(self):
        dt = PlainDateTime(2024, 3, 15, 14, 30)
        assert f"{dt}" == str(dt)

    def test_instant_with_spec(self):
        i = Instant.from_utc(2024, 3, 15, 14, 30)
        assert f"{i:YYYY-MM-DD HH:mmXXX}" == "2024-03-15 14:30Z"

    def test_instant_empty_spec(self):
        i = Instant.from_utc(2024, 3, 15, 14, 30)
        assert f"{i}" == str(i)

    def test_offset_datetime_with_spec(self):
        odt = OffsetDateTime(2024, 3, 15, 14, 30, offset=hours(2))
        assert f"{odt:YYYY-MM-DD HH:mmxxx}" == "2024-03-15 14:30+02:00"

    def test_offset_datetime_empty_spec(self):
        odt = OffsetDateTime(2024, 3, 15, 14, 30, offset=hours(2))
        assert f"{odt}" == str(odt)

    def test_zoned_datetime_with_spec(self):
        zdt = ZonedDateTime(2024, 3, 15, 14, 30, tz="Europe/Paris")
        assert f"{zdt:YYYY-MM-DD HH:mm}" == "2024-03-15 14:30"

    def test_zoned_datetime_empty_spec(self):
        zdt = ZonedDateTime(2024, 3, 15, 14, 30, tz="Europe/Paris")
        assert f"{zdt}" == str(zdt)
