//! Pattern-based formatting and parsing.
//!
//! A pattern string like `"YYYY-MM-DD hh:mm:ss"` is compiled into a `Vec<Element>`,
//! then used for formatting values into strings or parsing strings into values.

use crate::common::fmt::{Sink, format_2_digits, format_4_digits};
use crate::common::scalar::{Month, Offset, SubSecNanos, Weekday, Year};
use crate::py::{
    PyAsciiStrBuilder, PyResult,
    exc::{ResultExt, raise_value_err},
};
use crate::tz::tzif::is_tz_id_char;

// ---- Name tables ----

static MONTH_ABBR: [&str; 13] = [
    "", "Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec",
];
static MONTH_FULL: [&str; 13] = [
    "",
    "January",
    "February",
    "March",
    "April",
    "May",
    "June",
    "July",
    "August",
    "September",
    "October",
    "November",
    "December",
];
static WEEKDAY_ABBR: [&str; 7] = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"];
static WEEKDAY_FULL: [&str; 7] = [
    "Monday",
    "Tuesday",
    "Wednesday",
    "Thursday",
    "Friday",
    "Saturday",
    "Sunday",
];

// ---- Categories ----

/// Field category, used for validation: which types allow which categories.
#[derive(Debug, Copy, Clone, PartialEq, Eq)]
pub(crate) enum Category {
    Date,
    Time,
    Offset,
    Tz,
}

/// A bitmask of allowed categories.
#[derive(Debug, Copy, Clone)]
pub(crate) struct CategorySet(u8);

impl CategorySet {
    pub(crate) const DATE: Self = Self(1);
    pub(crate) const TIME: Self = Self(2);
    pub(crate) const DATE_TIME: Self = Self(1 | 2);
    pub(crate) const DATE_TIME_OFFSET: Self = Self(1 | 2 | 4);
    pub(crate) const DATE_TIME_OFFSET_TZ: Self = Self(1 | 2 | 4 | 8);

    fn contains(self, cat: Category) -> bool {
        let bit = match cat {
            Category::Date => 1,
            Category::Time => 2,
            Category::Offset => 4,
            Category::Tz => 8,
        };
        self.0 & bit != 0
    }
}

// ---- Format values ----

/// Input values available for formatting.
pub(crate) struct FormatValues<'a> {
    pub(crate) year: Year,
    pub(crate) month: Month,
    pub(crate) day: u8,
    pub(crate) weekday: Weekday,
    pub(crate) hour: u8,
    pub(crate) minute: u8,
    pub(crate) second: u8,
    pub(crate) nanos: SubSecNanos,
    pub(crate) offset_secs: Option<Offset>,
    pub(crate) tz_id: Option<&'a str>,
    pub(crate) tz_abbrev: Option<&'a str>,
}

// ---- Parse state ----

/// Mutable state accumulating parsed field values.
#[derive(Debug, Default)]
pub(crate) struct ParseState {
    pub(crate) year: Option<Year>,
    pub(crate) month: Option<Month>,
    pub(crate) day: Option<u8>,
    pub(crate) hour: Option<u8>,
    pub(crate) minute: Option<u8>,
    pub(crate) second: Option<u8>,
    pub(crate) nanos: SubSecNanos,
    pub(crate) ampm: Option<AmPm>,
    pub(crate) offset_secs: Option<Offset>,
    pub(crate) tz_id: Option<String>,
    pub(crate) weekday: Option<Weekday>,
}

#[derive(Debug, Copy, Clone, PartialEq, Eq)]
pub(crate) enum AmPm {
    Am,
    Pm,
}

impl ParseState {
    /// Apply AM/PM adjustment after all fields are parsed.
    pub(crate) fn resolve(&mut self) {
        if let (Some(ampm), Some(hour)) = (self.ampm, self.hour) {
            match ampm {
                AmPm::Pm if hour < 12 => self.hour = Some(hour + 12),
                AmPm::Am if hour == 12 => self.hour = Some(0),
                _ => {}
            }
        }
    }
}

// ---- Pattern elements ----

/// Compiled pattern element: either a literal string or a field specifier.
#[derive(Debug)]
pub(crate) enum Element<'a> {
    /// A run of literal bytes, borrowing directly from the compiled pattern string.
    Literal(&'a [u8]),
    Field(Field),
}

/// A field specifier in a pattern.
#[derive(Debug, Copy, Clone)]
pub(crate) enum Field {
    Year4,
    Year2,
    MonthNum,
    MonthAbbr,
    MonthFull,
    Day,
    WeekdayAbbr,
    WeekdayFull,
    Hour24,
    Hour12,
    Minute,
    Second,
    FracExact(u8), // width 1-9
    FracTrim(u8),  // width 1-9
    DotFrac(u8),   // decimal point followed by trimmed fractional seconds (width 1-9)
    AmPmShort,
    AmPmFull,
    OffsetLower(u8), // width 1-5
    OffsetUpper(u8), // width 1-5
    TzId,
    TzAbbrev,
}

impl Field {
    // Function pointers would add indirection and complicate the match; the current
    // approach is clearer and likely faster for a small, fixed field set.
    fn category(self) -> Category {
        match self {
            Self::Year4
            | Self::Year2
            | Self::MonthNum
            | Self::MonthAbbr
            | Self::MonthFull
            | Self::Day
            | Self::WeekdayAbbr
            | Self::WeekdayFull => Category::Date,
            Self::Hour24
            | Self::Hour12
            | Self::Minute
            | Self::Second
            | Self::FracExact(_)
            | Self::FracTrim(_)
            | Self::DotFrac(_)
            | Self::AmPmShort
            | Self::AmPmFull => Category::Time,
            Self::OffsetLower(_) | Self::OffsetUpper(_) => Category::Offset,
            Self::TzId | Self::TzAbbrev => Category::Tz,
        }
    }

    /// Identifier for duplicate detection. Fields that set the same
    /// parse state return the same key.
    fn state_key(self) -> Option<u8> {
        Some(match self {
            Self::Year4 | Self::Year2 => 0,
            Self::MonthNum | Self::MonthAbbr | Self::MonthFull => 1,
            Self::Day => 2,
            Self::WeekdayAbbr | Self::WeekdayFull => 3,
            Self::Hour24 | Self::Hour12 => 4,
            Self::Minute => 5,
            Self::Second => 6,
            Self::FracExact(_) | Self::FracTrim(_) | Self::DotFrac(_) => 7,
            Self::AmPmShort | Self::AmPmFull => 8,
            Self::OffsetLower(_) | Self::OffsetUpper(_) => 9,
            Self::TzId => 10,
            Self::TzAbbrev => 11,
        })
    }

    fn is_format_only(self) -> bool {
        matches!(self, Self::Year2 | Self::TzAbbrev)
    }

    /// Display name for error messages.
    fn display_name(self) -> &'static str {
        match self {
            Self::Year4 => "YYYY",
            Self::Year2 => "YY",
            Self::MonthNum => "MM",
            Self::MonthAbbr => "MMM",
            Self::MonthFull => "MMMM",
            Self::Day => "DD",
            Self::WeekdayAbbr => "ddd",
            Self::WeekdayFull => "dddd",
            Self::Hour24 => "hh",
            Self::Hour12 => "ii",
            Self::Minute => "mm",
            Self::Second => "ss",
            Self::FracExact(w) => match w {
                1 => "f",
                2 => "ff",
                3 => "fff",
                4 => "ffff",
                5 => "fffff",
                6 => "ffffff",
                7 => "fffffff",
                8 => "ffffffff",
                _ => "fffffffff",
            },
            Self::FracTrim(w) => match w {
                1 => "F",
                2 => "FF",
                3 => "FFF",
                4 => "FFFF",
                5 => "FFFFF",
                6 => "FFFFFF",
                7 => "FFFFFFF",
                8 => "FFFFFFFF",
                _ => "FFFFFFFFF",
            },
            Self::DotFrac(w) => match w {
                1 => ".F",
                2 => ".FF",
                3 => ".FFF",
                4 => ".FFFF",
                5 => ".FFFFF",
                6 => ".FFFFFF",
                7 => ".FFFFFFF",
                8 => ".FFFFFFFF",
                _ => ".FFFFFFFFF",
            },
            Self::AmPmShort => "a",
            Self::AmPmFull => "aa",
            Self::OffsetLower(w) => match w {
                1 => "x",
                2 => "xx",
                3 => "xxx",
                4 => "xxxx",
                _ => "xxxxx",
            },
            Self::OffsetUpper(w) => match w {
                1 => "X",
                2 => "XX",
                3 => "XXX",
                4 => "XXXX",
                _ => "XXXXX",
            },
            Self::TzId => "VV",
            Self::TzAbbrev => "zz",
        }
    }
}

// ---- Literal / reserved character sets ----

fn is_literal_char(ch: u8) -> bool {
    matches!(
        ch,
        b' ' | b'\t' | b'\n' | b'0'
            ..=b'9'
                | b':'
                | b'-'
                | b'/'
                | b'.'
                | b','
                | b';'
                | b'_'
                | b'('
                | b')'
                | b'+'
                | b'@'
                | b'!'
                | b'~'
                | b'*'
                | b'&'
                | b'%'
                | b'$'
                | b'^'
                | b'|'
                | b'\\'
                | b'='
                | b'?'
                | b'`'
                | b'"'
    )
}

fn is_reserved_char(ch: u8) -> bool {
    matches!(ch, b'<' | b'>' | b'[' | b']' | b'{' | b'}' | b'#')
}

// ---- Pattern compilation ----

/// Compile a pattern string into a list of elements.
pub(crate) fn compile(pattern: &[u8]) -> Result<Vec<Element<'_>>, String> {
    if pattern.len() > 1000 {
        return Err("Pattern string too long (max 1000 characters)".to_string());
    }
    let mut elements = Vec::new();
    let n = pattern.len();
    let mut i = 0;

    while i < n {
        let ch = pattern[i];

        if !ch.is_ascii() {
            return Err(format!(
                "Non-ASCII character at position {}. Patterns must be ASCII-only.",
                i
            ));
        }

        // Quoted literal
        if ch == b'\'' {
            i = compile_quoted_literal(pattern, i, n, &mut elements)?;
            continue;
        }

        // Recognized specifier letter
        if is_spec_char(ch) {
            i = compile_specifier(pattern, i, n, ch, &mut elements)?;
            continue;
        }

        // Other ASCII letters are errors
        if ch.is_ascii_alphabetic() {
            return Err(format!(
                "Unrecognized pattern character '{}' at position {}. Use quotes for literal text: '...'",
                ch as char, i
            ));
        }

        // Reserved characters
        if is_reserved_char(ch) {
            return Err(format!(
                "Character '{}' at position {} is reserved for future use. Use quotes for literal: '...'",
                ch as char, i
            ));
        }

        // Allowed literal characters: collect a run, then check if it ends in '.'
        // followed immediately by a 'F' specifier (DotFrac inline detection).
        if is_literal_char(ch) {
            let start = i;
            while i < n && is_literal_char(pattern[i]) {
                i += 1;
            }
            // If the literal run ends in '.' and the next char is 'F', emit the
            // prefix without the dot and compile the F-run as a DotFrac field.
            if pattern[i - 1] == b'.' && i < n && pattern[i] == b'F' {
                if i - 1 > start {
                    elements.push(Element::Literal(&pattern[start..i - 1]));
                }
                i = compile_specifier(pattern, i, n, b'F', &mut elements)?;
                // FracTrim emitted by compile_specifier; convert last element to DotFrac.
                if let Some(Element::Field(Field::FracTrim(w))) = elements.last() {
                    let w = *w;
                    *elements.last_mut().unwrap() = Element::Field(Field::DotFrac(w));
                }
            } else {
                elements.push(Element::Literal(&pattern[start..i]));
            }
            continue;
        }

        return Err(format!(
            "Unexpected character {:?} at position {}. Use quotes for literal text: '...'",
            ch as char, i
        ));
    }

    validate_cross_fields(&elements)?;
    Ok(elements)
}

fn is_spec_char(ch: u8) -> bool {
    matches!(
        ch,
        b'Y' | b'M'
            | b'D'
            | b'd'
            | b'h'
            | b'i'
            | b'm'
            | b's'
            | b'f'
            | b'F'
            | b'a'
            | b'V'
            | b'z'
            | b'x'
            | b'X'
    )
}

fn compile_quoted_literal<'a>(
    pattern: &'a [u8],
    start: usize,
    n: usize,
    elements: &mut Vec<Element<'a>>,
) -> Result<usize, String> {
    let mut i = start + 1; // skip opening quote
    if i < n && pattern[i] == b'\'' {
        // '' is an escaped single quote — emit exactly one apostrophe byte
        elements.push(Element::Literal(&pattern[i..i + 1]));
        return Ok(i + 1);
    }
    let text_start = i;
    while i < n && pattern[i] != b'\'' {
        i += 1;
    }
    if i >= n {
        return Err("Unterminated quoted literal in pattern".into());
    }
    if i > text_start {
        elements.push(Element::Literal(&pattern[text_start..i]));
    }
    Ok(i + 1) // skip closing quote
}

fn compile_specifier(
    pattern: &[u8],
    start: usize,
    n: usize,
    ch: u8,
    elements: &mut Vec<Element<'_>>,
) -> Result<usize, String> {
    let mut count: usize = 1;
    while start + count < n && pattern[start + count] == ch {
        count += 1;
    }

    let field = match ch {
        // Variable-width fields
        b'f' => {
            if count > 9 {
                return Err(format!("Too many 'f' characters in pattern (max 9)"));
            }
            Field::FracExact(count as u8)
        }
        b'F' => {
            if count > 9 {
                return Err(format!("Too many 'F' characters in pattern (max 9)"));
            }
            Field::FracTrim(count as u8)
        }
        b'x' => {
            if count > 5 {
                return Err(format!("Too many 'x' characters in pattern (max 5)"));
            }
            Field::OffsetLower(count as u8)
        }
        b'X' => {
            if count > 5 {
                return Err(format!("Too many 'X' characters in pattern (max 5)"));
            }
            Field::OffsetUpper(count as u8)
        }
        // Fixed-width fields
        b'Y' => match count {
            4 => Field::Year4,
            2 => Field::Year2,
            _ => return Err(bad_count_err(ch, count, start, "4, 2")),
        },
        b'M' => match count {
            2 => Field::MonthNum,
            3 => Field::MonthAbbr,
            4 => Field::MonthFull,
            _ => return Err(bad_count_err(ch, count, start, "4, 3, 2")),
        },
        b'D' => match count {
            2 => Field::Day,
            _ => return Err(bad_count_err(ch, count, start, "2")),
        },
        b'd' => match count {
            3 => Field::WeekdayAbbr,
            4 => Field::WeekdayFull,
            _ => return Err(bad_count_err(ch, count, start, "4, 3")),
        },
        b'h' => match count {
            2 => Field::Hour24,
            _ => return Err(bad_count_err(ch, count, start, "2")),
        },
        b'i' => match count {
            2 => Field::Hour12,
            _ => return Err(bad_count_err(ch, count, start, "2")),
        },
        b'm' => match count {
            2 => Field::Minute,
            _ => return Err(bad_count_err(ch, count, start, "2")),
        },
        b's' => match count {
            2 => Field::Second,
            _ => return Err(bad_count_err(ch, count, start, "2")),
        },
        b'a' => match count {
            1 => Field::AmPmShort,
            2 => Field::AmPmFull,
            _ => return Err(bad_count_err(ch, count, start, "2, 1")),
        },
        b'V' => match count {
            2 => Field::TzId,
            _ => return Err(bad_count_err(ch, count, start, "2")),
        },
        b'z' => match count {
            2 => Field::TzAbbrev,
            _ => return Err(bad_count_err(ch, count, start, "2")),
        },
        _ => unreachable!(),
    };

    elements.push(Element::Field(field));
    Ok(start + count)
}

fn bad_count_err(ch: u8, count: usize, start: usize, valid: &str) -> String {
    let repeated: String = std::iter::repeat(ch as char).take(count).collect();
    format!(
        "Unrecognized specifier '{}' at position {}. Valid counts for '{}': [{}]",
        repeated, start, ch as char, valid
    )
}

fn validate_cross_fields(elements: &[Element<'_>]) -> Result<(), String> {
    let mut has_24h = false;
    let mut has_ampm = false;
    let mut seen_keys: [Option<&'static str>; 12] = [None; 12];

    for el in elements {
        let field = match el {
            Element::Field(f) => *f,
            _ => continue,
        };

        match field {
            Field::Hour24 => has_24h = true,
            Field::AmPmShort | Field::AmPmFull => has_ampm = true,
            _ => {}
        }

        if let Some(key) = field.state_key() {
            let idx = key as usize;
            if let Some(prev) = seen_keys[idx] {
                return Err(format!(
                    "Duplicate field: {} conflicts with {} (both set {})",
                    field.display_name(),
                    prev,
                    state_key_name(key)
                ));
            }
            seen_keys[idx] = Some(field.display_name());
        }
    }

    if has_24h && has_ampm {
        return Err(
            "24-hour format (hh) cannot be combined with AM/PM (a/aa). Use 12-hour format (ii) instead.".into(),
        );
    }
    // 12h without AM/PM: we return Ok but the Python side emits a warning.
    // The warning is handled by the caller since we don't have Python API access here.
    Ok(())
}

fn state_key_name(key: u8) -> &'static str {
    match key {
        0 => "year",
        1 => "month",
        2 => "day",
        3 => "weekday",
        4 => "hour",
        5 => "minute",
        6 => "second",
        7 => "nanos",
        8 => "ampm",
        9 => "offset_secs",
        10 => "tz_id",
        11 => "tz_abbrev",
        _ => unreachable!(),
    }
}

/// Check if the pattern has 12-hour without AM/PM (for warning by caller).
pub(crate) fn has_12h_without_ampm(elements: &[Element<'_>]) -> bool {
    let mut has_12h = false;
    let mut has_ampm = false;
    for el in elements {
        match el {
            Element::Field(Field::Hour12) => has_12h = true,
            Element::Field(Field::AmPmShort | Field::AmPmFull) => has_ampm = true,
            _ => {}
        }
    }
    has_12h && !has_ampm
}

// ---- Formatting ----

/// A [`Sink`] that only counts bytes, used for the first (dry-run) pass of
/// two-pass formatting.
struct ByteCounter(usize);

impl ByteCounter {
    fn new() -> Self {
        Self(0)
    }
    fn len(&self) -> usize {
        self.0
    }
}

impl Sink for ByteCounter {
    fn write_byte(&mut self, _: u8) {
        self.0 += 1;
    }
    fn write(&mut self, s: &[u8]) {
        self.0 += s.len();
    }
}

/// Write exactly `width` digits (0-padded) of `nanos` into `sink`.
fn write_nanos_digits(nanos: SubSecNanos, width: usize, sink: &mut impl Sink) {
    let mut buf = [b'0'; 9];
    let mut n = nanos.get() as u32;
    for i in (0..9).rev() {
        buf[i] = b'0' + (n % 10) as u8;
        n /= 10;
    }
    sink.write(&buf[..width]);
}

/// Write trimmed (trailing-zero-stripped) fractional digits into `sink`.
fn write_nanos_trimmed(nanos: SubSecNanos, width: usize, sink: &mut impl Sink) {
    let mut buf = [b'0'; 9];
    let mut n = nanos.get() as u32;
    for i in (0..9).rev() {
        buf[i] = b'0' + (n % 10) as u8;
        n /= 10;
    }
    let slice = &buf[..width];
    let trimmed_len = slice.iter().rposition(|&b| b != b'0').map_or(0, |p| p + 1);
    sink.write(&slice[..trimmed_len]);
}

/// Returns `true` if `FracTrim(width)` would produce no output for these `nanos`.
fn frac_trim_is_empty(nanos: SubSecNanos, width: usize) -> bool {
    // The first `width` digits are all zeros iff nanos < 10^(9-width)
    (nanos.get() as u32) < 10u32.pow((9 - width) as u32)
}

fn write_offset(secs: i32, width: u8, use_z: bool, sink: &mut impl Sink) {
    if secs == 0 && use_z {
        sink.write_byte(b'Z');
        return;
    }
    let sign = if secs >= 0 { b'+' } else { b'-' };
    let total = secs.unsigned_abs();
    let oh = (total / 3600) as u8;
    let remainder = total % 3600;
    let om = (remainder / 60) as u8;
    let os = (remainder % 60) as u8;
    let h = format_2_digits(oh);
    let m = format_2_digits(om);
    let s_digits = format_2_digits(os);
    sink.write_byte(sign);
    sink.write(&h);
    match width {
        1 => {}
        2 => sink.write(&m),
        3 => {
            sink.write_byte(b':');
            sink.write(&m);
        }
        4 => {
            sink.write(&m);
            if os != 0 {
                sink.write(&s_digits);
            }
        }
        _ => {
            // width == 5
            sink.write_byte(b':');
            sink.write(&m);
            if os != 0 {
                sink.write_byte(b':');
                sink.write(&s_digits);
            }
        }
    }
}

fn write_field<S: Sink>(field: Field, vals: &FormatValues, sink: &mut S) -> Result<(), String> {
    match field {
        Field::Year4 => sink.write(&format_4_digits(vals.year.get())),
        Field::Year2 => sink.write(&format_2_digits((vals.year.get() % 100) as u8)),
        Field::MonthNum => sink.write(&format_2_digits(vals.month.get())),
        Field::MonthAbbr => sink.write(MONTH_ABBR[vals.month.get() as usize].as_bytes()),
        Field::MonthFull => sink.write(MONTH_FULL[vals.month.get() as usize].as_bytes()),
        Field::Day => sink.write(&format_2_digits(vals.day)),
        Field::WeekdayAbbr => {
            // Weekday::iso() is 1-based (Mon=1); array is 0-based.
            sink.write(WEEKDAY_ABBR[vals.weekday.iso() as usize - 1].as_bytes());
        }
        Field::WeekdayFull => {
            sink.write(WEEKDAY_FULL[vals.weekday.iso() as usize - 1].as_bytes());
        }
        Field::Hour24 => sink.write(&format_2_digits(vals.hour)),
        Field::Hour12 => {
            let h12 = if vals.hour % 12 == 0 {
                12
            } else {
                vals.hour % 12
            };
            sink.write(&format_2_digits(h12));
        }
        Field::Minute => sink.write(&format_2_digits(vals.minute)),
        Field::Second => sink.write(&format_2_digits(vals.second)),
        Field::FracExact(w) => write_nanos_digits(vals.nanos, w as usize, sink),
        Field::FracTrim(w) => write_nanos_trimmed(vals.nanos, w as usize, sink),
        Field::DotFrac(w) => {
            if !frac_trim_is_empty(vals.nanos, w as usize) {
                sink.write_byte(b'.');
                write_nanos_trimmed(vals.nanos, w as usize, sink);
            }
            // Empty: write nothing (dot is omitted together with the digits)
        }
        Field::AmPmShort => sink.write_byte(if vals.hour < 12 { b'A' } else { b'P' }),
        Field::AmPmFull => sink.write(if vals.hour < 12 { b"AM" } else { b"PM" }),
        Field::OffsetLower(w) => {
            let offset = vals
                .offset_secs
                .ok_or("Cannot format offset: not available for this type")?;
            write_offset(offset.get(), w, false, sink);
        }
        Field::OffsetUpper(w) => {
            let offset = vals
                .offset_secs
                .ok_or("Cannot format offset: not available for this type")?;
            write_offset(offset.get(), w, true, sink);
        }
        Field::TzId => {
            let id = vals
                .tz_id
                .ok_or("Cannot format timezone ID: not available for this type")?;
            sink.write(id.as_bytes());
        }
        Field::TzAbbrev => {
            let abbrev = vals
                .tz_abbrev
                .ok_or("Cannot format timezone abbreviation: not available for this type")?;
            sink.write(abbrev.as_bytes());
        }
    }
    Ok(())
}

/// Write formatted pattern elements into `sink`.
///
/// Called twice by `format_to_py`: first with a `ByteCounter` to compute the
/// output length, then with a `PyAsciiStrBuilder` to write the actual bytes.
/// Both passes must produce identical output for the same `(elements, vals)`.
fn format_elements<S: Sink>(
    elements: &[Element<'_>],
    vals: &FormatValues,
    sink: &mut S,
) -> Result<(), String> {
    for el in elements {
        match el {
            Element::Literal(text) => sink.write(text),
            Element::Field(field) => write_field(*field, vals, sink)?,
        }
    }
    Ok(())
}

/// Format values using compiled pattern elements, returning a Python `str` object.
///
/// Uses a two-pass approach: the first pass counts the output bytes (and validates
/// all required values are present); the second pass writes directly into a
/// presized Python string object via [`PyAsciiStrBuilder`], avoiding any
/// intermediate Rust string allocation.
pub(crate) fn format_to_py(elements: &[Element<'_>], vals: &FormatValues) -> crate::py::PyReturn {
    let mut counter = ByteCounter::new();
    format_elements(elements, vals, &mut counter).into_value_err()?;
    let mut builder = PyAsciiStrBuilder::new(counter.len())?;
    // SAFETY: the second pass uses the same `elements` and `vals`, so it is
    // deterministic and cannot fail after the first pass succeeded.
    format_elements(elements, vals, &mut builder)
        .expect("second pass cannot fail after successful first pass");
    Ok(builder.finish())
}

// ---- Parsing ----

/// Parse a string using compiled pattern elements.
pub(crate) fn parse_to_state(elements: &[Element<'_>], s: &[u8]) -> Result<ParseState, String> {
    if s.len() > 1000 {
        return Err("Input string too long (max 1000 characters)".to_string());
    }
    let mut state = ParseState::default();
    let mut pos = 0;

    for el in elements {
        match el {
            Element::Literal(text) => {
                let end = pos + text.len();
                if end > s.len() || &s[pos..end] != *text {
                    let expected = std::str::from_utf8(text).unwrap_or("?");
                    let got = std::str::from_utf8(&s[pos..s.len().min(end)]).unwrap_or("?");
                    return Err(format!(
                        "Expected {:?} at position {}, got {:?}",
                        expected, pos, got
                    ));
                }
                pos = end;
            }
            Element::Field(field) => {
                if field.is_format_only() {
                    return Err(format!(
                        "Field {} is only supported for formatting, not parsing",
                        field.display_name()
                    ));
                }
                pos = parse_field(*field, s, pos, &mut state)?;
            }
        }
    }

    if pos != s.len() {
        let trailing = std::str::from_utf8(&s[pos..]).unwrap_or("?");
        return Err(format!(
            "Unexpected trailing text at position {}: {:?}",
            pos, trailing
        ));
    }

    state.resolve();
    Ok(state)
}

fn parse_digits(s: &[u8], pos: usize, count: usize) -> Result<(u32, usize), String> {
    let end = pos + count;
    if end > s.len() {
        return Err(format!(
            "Expected {} digits at position {}, but input is too short",
            count, pos
        ));
    }
    let mut val = 0u32;
    for &b in &s[pos..end] {
        if !b.is_ascii_digit() {
            let chunk = std::str::from_utf8(&s[pos..end]).unwrap_or("?");
            return Err(format!(
                "Expected {} digits at position {}, got {:?}",
                count, pos, chunk
            ));
        }
        val = val * 10 + (b - b'0') as u32;
    }
    Ok((val, end))
}

static MONTH_ABBR_SORTED: [(usize, &str); 12] = [
    (1, "Jan"),
    (2, "Feb"),
    (3, "Mar"),
    (4, "Apr"),
    (5, "May"),
    (6, "Jun"),
    (7, "Jul"),
    (8, "Aug"),
    (9, "Sep"),
    (10, "Oct"),
    (11, "Nov"),
    (12, "Dec"),
];

// Month name arrays sorted by length (longest first) for matching
static MONTH_FULL_SORTED: [(usize, &str); 12] = [
    (9, "September"),
    (11, "November"),
    (12, "December"),
    (2, "February"),
    (8, "August"),
    (1, "January"),
    (10, "October"),
    (3, "March"),
    (4, "April"),
    (7, "July"),
    (6, "June"),
    (5, "May"),
];

static WEEKDAY_ABBR_SORTED: [(usize, &str); 7] = [
    (0, "Mon"),
    (1, "Tue"),
    (2, "Wed"),
    (3, "Thu"),
    (4, "Fri"),
    (5, "Sat"),
    (6, "Sun"),
];

static WEEKDAY_FULL_SORTED: [(usize, &str); 7] = [
    (2, "Wednesday"),
    (3, "Thursday"),
    (5, "Saturday"),
    (4, "Friday"),
    (0, "Monday"),
    (6, "Sunday"),
    (1, "Tuesday"),
];

fn parse_name_match(
    s: &[u8],
    pos: usize,
    candidates: &[(usize, &str)],
    field_name: &str,
) -> Result<(usize, usize), String> {
    let remaining = &s[pos..];
    for &(value, name) in candidates {
        let name_bytes = name.as_bytes();
        if remaining.len() >= name_bytes.len()
            && remaining[..name_bytes.len()].eq_ignore_ascii_case(name_bytes)
        {
            return Ok((value, pos + name_bytes.len()));
        }
    }
    Err(format!("Cannot parse {} at position {}", field_name, pos))
}

fn parse_offset_value(
    s: &[u8],
    pos: usize,
    width: u8,
    accept_z: bool,
) -> Result<(i32, usize), String> {
    if accept_z && pos < s.len() && s[pos] == b'Z' {
        return Ok((0, pos + 1));
    }
    if pos >= s.len() || (s[pos] != b'+' && s[pos] != b'-') {
        return Err(format!("Expected offset sign at position {}", pos));
    }
    let sign: i32 = if s[pos] == b'+' { 1 } else { -1 };
    let mut p = pos + 1;

    let (oh, new_p) = parse_digits(s, p, 2)?;
    p = new_p;

    if width == 1 {
        return Ok((sign * oh as i32 * 3600, p));
    }

    let om;
    if width == 2 || width == 4 {
        let (v, new_p) = parse_digits(s, p, 2)?;
        om = v;
        p = new_p;
    } else {
        // width 3 or 5: expect colon
        if p >= s.len() || s[p] != b':' {
            return Err(format!("Expected ':' at position {}", p));
        }
        p += 1;
        let (v, new_p) = parse_digits(s, p, 2)?;
        om = v;
        p = new_p;
    }
    if om >= 60 {
        return Err("offset minutes must be 0..59".into());
    }

    let mut os = 0u32;
    if width >= 4 {
        let has_colon = width == 5;
        if has_colon && p < s.len() && s[p] == b':' {
            p += 1;
            let (v, new_p) = parse_digits(s, p, 2)?;
            os = v;
            p = new_p;
        } else if !has_colon && p < s.len() && s[p].is_ascii_digit() {
            let (v, new_p) = parse_digits(s, p, 2)?;
            os = v;
            p = new_p;
        }
        if os >= 60 {
            return Err("offset seconds must be 0..59".into());
        }
    }

    Ok((sign * (oh as i32 * 3600 + om as i32 * 60 + os as i32), p))
}

fn parse_dot_frac(
    s: &[u8],
    pos: usize,
    width: usize,
    state: &mut ParseState,
) -> Result<usize, String> {
    if pos < s.len() && s[pos] == b'.' {
        let pos = pos + 1; // consume the dot
        let start = pos;
        let mut end = pos;
        while end < s.len() && end - start < width && s[end].is_ascii_digit() {
            end += 1;
        }
        let count = end - start;
        if count == 0 {
            state.nanos = SubSecNanos::MIN;
        } else {
            let val: u32 = s[start..end]
                .iter()
                .fold(0, |acc, &b| acc * 10 + (b - b'0') as u32);
            // SAFETY: val is at most 9 digits of fractional seconds, scaled to
            // nanoseconds (max 999_999_999), which is within SubSecNanos range.
            state.nanos = SubSecNanos::new_unchecked(val as i32 * 10i32.pow((9 - count) as u32));
        }
        Ok(end)
    } else {
        // No dot present: nanos are zero, position unchanged
        state.nanos = SubSecNanos::MIN;
        Ok(pos)
    }
}

fn parse_field(
    field: Field,
    s: &[u8],
    pos: usize,
    state: &mut ParseState,
) -> Result<usize, String> {
    match field {
        Field::Year4 => {
            let (v, p) = parse_digits(s, pos, 4)?;
            state.year =
                Some(Year::new(v as u16).ok_or_else(|| format!("year out of range: {}", v))?);
            Ok(p)
        }
        Field::Year2 => unreachable!("Year2 is format-only"),
        Field::MonthNum => {
            let (v, p) = parse_digits(s, pos, 2)?;
            state.month =
                Some(Month::new(v as u8).ok_or_else(|| format!("month out of range: {}", v))?);
            Ok(p)
        }
        Field::MonthAbbr => {
            // value from MONTH_ABBR_SORTED is already 1-12
            let (v, p) = parse_name_match(s, pos, &MONTH_ABBR_SORTED, "month")?;
            // SAFETY: MONTH_ABBR_SORTED values are all in 1..=12.
            state.month = Some(Month::new_unchecked(v as u8));
            Ok(p)
        }
        Field::MonthFull => {
            // value from MONTH_FULL_SORTED is already 1-12
            let (v, p) = parse_name_match(s, pos, &MONTH_FULL_SORTED, "month")?;
            // SAFETY: MONTH_FULL_SORTED values are all in 1..=12.
            state.month = Some(Month::new_unchecked(v as u8));
            Ok(p)
        }
        Field::Day => {
            let (v, p) = parse_digits(s, pos, 2)?;
            state.day = Some(v as u8);
            Ok(p)
        }
        Field::WeekdayAbbr => {
            // value from WEEKDAY_ABBR_SORTED is 0-indexed (0=Mon); convert to 1-indexed ISO.
            let (v, p) = parse_name_match(s, pos, &WEEKDAY_ABBR_SORTED, "weekday")?;
            // SAFETY: WEEKDAY_ABBR_SORTED values are 0..=6, so (v+1) is 1..=7.
            state.weekday = Some(Weekday::from_iso_unchecked((v + 1) as u8));
            Ok(p)
        }
        Field::WeekdayFull => {
            // value from WEEKDAY_FULL_SORTED is 0-indexed (0=Mon); convert to 1-indexed ISO.
            let (v, p) = parse_name_match(s, pos, &WEEKDAY_FULL_SORTED, "weekday")?;
            // SAFETY: WEEKDAY_FULL_SORTED values are 0..=6, so (v+1) is 1..=7.
            state.weekday = Some(Weekday::from_iso_unchecked((v + 1) as u8));
            Ok(p)
        }
        Field::Hour24 => {
            let (v, p) = parse_digits(s, pos, 2)?;
            state.hour = Some(v as u8);
            Ok(p)
        }
        Field::Hour12 => {
            let (v, p) = parse_digits(s, pos, 2)?;
            if !(1..=12).contains(&v) {
                return Err(format!("12-hour format requires hour in 1..12, got {}", v));
            }
            state.hour = Some(v as u8);
            Ok(p)
        }
        Field::Minute => {
            let (v, p) = parse_digits(s, pos, 2)?;
            state.minute = Some(v as u8);
            Ok(p)
        }
        Field::Second => {
            let (v, p) = parse_digits(s, pos, 2)?;
            state.second = Some(v as u8);
            Ok(p)
        }
        Field::FracExact(width) => {
            let (v, p) = parse_digits(s, pos, width as usize)?;
            // SAFETY: v is at most `width` fractional digits scaled to ns (max 999_999_999).
            state.nanos = SubSecNanos::new_unchecked(v as i32 * 10i32.pow(9 - width as u32));
            Ok(p)
        }
        Field::FracTrim(width) => {
            let mut count = 0usize;
            while count < width as usize && pos + count < s.len() && s[pos + count].is_ascii_digit()
            {
                count += 1;
            }
            if count == 0 {
                state.nanos = SubSecNanos::MIN;
            } else {
                let (v, _) = parse_digits(s, pos, count)?;
                // SAFETY: same scaling argument as FracExact.
                state.nanos = SubSecNanos::new_unchecked(v as i32 * 10i32.pow(9 - count as u32));
            }
            Ok(pos + count)
        }
        Field::DotFrac(width) => parse_dot_frac(s, pos, width as usize, state),
        Field::AmPmShort => {
            if pos >= s.len() {
                return Err(format!("Expected AM/PM at position {}", pos));
            }
            let ch = s[pos].to_ascii_uppercase();
            if ch == b'A' {
                state.ampm = Some(AmPm::Am);
            } else if ch == b'P' {
                state.ampm = Some(AmPm::Pm);
            } else {
                return Err(format!(
                    "Expected AM/PM at position {}, got {:?}",
                    pos,
                    std::str::from_utf8(&s[pos..pos + 1]).unwrap_or("?")
                ));
            }
            Ok(pos + 1)
        }
        Field::AmPmFull => {
            if pos + 2 > s.len() {
                return Err(format!("Expected AM/PM at position {}", pos));
            }
            let mut chunk = [0u8; 2];
            chunk[0] = s[pos].to_ascii_uppercase();
            chunk[1] = s[pos + 1].to_ascii_uppercase();
            if &chunk == b"AM" {
                state.ampm = Some(AmPm::Am);
            } else if &chunk == b"PM" {
                state.ampm = Some(AmPm::Pm);
            } else {
                let got = std::str::from_utf8(&s[pos..pos + 2]).unwrap_or("?");
                return Err(format!("Expected AM/PM at position {}, got {:?}", pos, got));
            }
            Ok(pos + 2)
        }
        Field::OffsetLower(width) => {
            let (secs, p) = parse_offset_value(s, pos, width, false)?;
            // SAFETY: parse_offset_value validates components, so secs is within Offset bounds.
            state.offset_secs = Some(Offset::new_unchecked(secs));
            Ok(p)
        }
        Field::OffsetUpper(width) => {
            let (secs, p) = parse_offset_value(s, pos, width, true)?;
            // SAFETY: parse_offset_value validates components, so secs is within Offset bounds.
            state.offset_secs = Some(Offset::new_unchecked(secs));
            Ok(p)
        }
        Field::TzId => {
            let start = pos;
            let mut p = pos;
            // NOTE: we don't catch "evil" TZ IDs like "America/Los_Angeles/../etc/passwd" here.
            // That's done (and required) in a later step using an explicit wrapper (BenignKey)
            while p < s.len() && is_tz_id_char(s[p]) {
                p += 1;
            }
            if p == start {
                return Err(format!("Expected timezone ID at position {}", pos));
            }
            // SAFETY: is_tz_id_char only passes ASCII bytes
            state.tz_id = Some(unsafe { std::str::from_utf8_unchecked(&s[start..p]) }.to_string());
            Ok(p)
        }
        Field::TzAbbrev => unreachable!("TzAbbrev is format-only"),
    }
}

// ---- Validation ----

/// Raise a `ValueError` if any element's field is not in `allowed`.
pub(crate) fn validate_fields(
    elements: &[Element<'_>],
    allowed: CategorySet,
    type_name: &str,
) -> PyResult<()> {
    for el in elements {
        if let Element::Field(field) = el {
            if !allowed.contains(field.category()) {
                return raise_value_err(format!(
                    "{} does not support pattern field {}",
                    type_name,
                    field.display_name()
                ));
            }
        }
    }
    Ok(())
}
