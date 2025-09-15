//! Helpers for writing formatted strings

use crate::{
    classes::{date::Date, time::Time},
    common::scalar::{Offset, OffsetFormat},
    docstrings::FORMAT_ISO_NO_TZ_MSG,
    py::*,
    pymodule::State,
    tz::store::TzPtr,
};

// Static table for formatting 2-digit numbers. Avoids division/modulo operations.
pub(crate) static DIGITS: &[u8; 200] = b"00010203040506070809101112131415161718192021222324252627282930313233343536373839404142434445464748495051525354555657585960616263646566676869707172737475767778798081828384858687888990919293949596979899";

pub(crate) fn format_2_digits(n: u8) -> [u8; 2] {
    debug_assert!(n < 100);
    let i = n as usize * 2;
    [DIGITS[i], DIGITS[i + 1]]
}

pub(crate) fn format_4_digits(n: u16) -> [u8; 4] {
    debug_assert!(n < 10000);
    // use static digits table
    let first = format_2_digits((n / 100) as u8);
    let second = format_2_digits((n % 100) as u8);
    [first[0], first[1], second[0], second[1]]
}

pub trait ByteWrite {
    fn write_byte(&mut self, b: u8);

    fn write(&mut self, s: &[u8]);
}

pub(crate) struct ArrayWriter<const N: usize> {
    buf: [u8; N],
    pos: usize,
}

impl<const N: usize> ArrayWriter<N> {
    pub fn new() -> Self {
        Self {
            buf: [0; N],
            pos: 0,
        }
    }

    pub fn finish(&self) -> &str {
        debug_assert!(self.pos == N);
        debug_assert!(self.buf.iter().all(|&b| b.is_ascii()));
        unsafe { std::str::from_utf8_unchecked(&self.buf[..]) }
    }
}

impl<const N: usize> ByteWrite for ArrayWriter<N> {
    fn write_byte(&mut self, b: u8) {
        debug_assert!(self.pos < N);
        self.buf[self.pos] = b;
        self.pos += 1;
    }

    fn write(&mut self, s: &[u8]) {
        debug_assert!(self.pos + s.len() <= N);
        self.buf[self.pos..self.pos + s.len()].copy_from_slice(s);
        self.pos += s.len();
    }
}

// TODO: rename
#[derive(Debug, Clone, Copy, PartialEq, Eq, PartialOrd, Ord)]
pub(crate) enum Unit {
    Auto,
    Nanosecond,
    Microsecond,
    Millisecond,
    Second,
    Minute,
    Hour,
}

impl Unit {
    #[allow(clippy::too_many_arguments)]
    pub(crate) fn from_py(
        obj: PyObj,
        str_hour: PyObj,
        str_minute: PyObj,
        str_second: PyObj,
        str_millisecond: PyObj,
        str_microsecond: PyObj,
        str_nanosecond: PyObj,
        str_auto: PyObj,
    ) -> PyResult<Self> {
        match_interned_str("unit", obj, |v, eq| {
            if eq(v, str_millisecond) {
                Some(Self::Millisecond)
            } else if eq(v, str_hour) {
                Some(Self::Hour)
            } else if eq(v, str_minute) {
                Some(Self::Minute)
            } else if eq(v, str_second) {
                Some(Self::Second)
            } else if eq(v, str_microsecond) {
                Some(Self::Microsecond)
            } else if eq(v, str_nanosecond) {
                Some(Self::Nanosecond)
            } else if eq(v, str_auto) {
                Some(Self::Auto)
            } else {
                None
            }
        })
    }
}

/// Suffix kind of a ISO8601 formatted string
pub(crate) enum Suffix {
    Absent,                  // No suffix (i.e. local/naive datetime)
    Zulu,                    // Static Z (Zulu, i.e. UTC)
    Offset(Offset),          // Offset only
    OffsetTz(Offset, TzPtr), // Offset and timezone name (in brackets)
}

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub(crate) enum SuffixFormat<'a> {
    Absent,
    Zulu,
    Offset(OffsetFormat),
    OffsetTz(OffsetFormat, &'a str),
}

impl SuffixFormat<'_> {
    pub(crate) fn len(self) -> usize {
        match self {
            Self::Absent => 0,
            Self::Zulu => 1,
            Self::Offset(fmt) => fmt.len(),
            Self::OffsetTz(offset, tz) => {
                offset.len() + tz.len() + 2 // two brackets around the tz name
            }
        }
    }

    pub(crate) fn write(self, b: &mut impl ByteWrite) {
        match self {
            Self::Absent => {}
            Self::Zulu => b.write_byte(b'Z'),
            Self::Offset(fmt) => fmt.write(b),
            Self::OffsetTz(offset, tz) => {
                offset.write(b);
                b.write_byte(b'[');
                b.write(tz.as_bytes());
                b.write_byte(b']');
            }
        }
    }
}

/// Rust representation of the `tz` keyword argument used in format_iso()
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
enum TzDisplay {
    Always,
    Never,
    Auto,
}

/// Common routine for writing ISO8601 formatted strings consisting of
/// date, time and optional timezone suffix
///
/// E.g. `2023-03-15T13:45:30.123456789+02:00[Europe/Berlin]`
/// or `20230315 134530Z`
#[inline]
pub(crate) fn format_iso(
    date: Date,
    time: Time,
    state: &State,
    args: &[PyObj],
    kwargs: &mut IterKwargs,
    suffix: Suffix,
) -> PyReturn {
    if !args.is_empty() {
        raise_type_err("format_iso() takes no positional arguments")?;
    }

    // As-efficient-as-possible assignment of keyword arguments
    let mut sep = b'T';
    let mut unit = Unit::Auto;
    let mut basic = false;
    let mut tz_display = TzDisplay::Always;
    let &State {
        str_sep,
        str_space,
        str_t,
        str_unit,
        str_hour,
        str_minute,
        str_second,
        str_millisecond,
        str_microsecond,
        str_nanosecond,
        str_auto,
        str_basic,
        str_always,
        str_never,
        str_tz,
        ..
    } = state;
    handle_kwargs("format_iso", kwargs, |key, value, eq| {
        if eq(key, str_sep) {
            sep = match_interned_str("sep", value, |v, eq| {
                if eq(v, str_space) {
                    Some(b' ')
                } else if eq(v, str_t) {
                    Some(b'T')
                } else {
                    None
                }
            })?;
        } else if eq(key, str_unit) {
            unit = Unit::from_py(
                value,
                str_hour,
                str_minute,
                str_second,
                str_millisecond,
                str_microsecond,
                str_nanosecond,
                str_auto,
            )?;
        } else if eq(key, str_basic) {
            if value.is_true() {
                basic = true;
            } else if value.is_false() {
                basic = false;
            } else {
                raise_type_err("`basic` must be a boolean value")?;
            }
        // Only allow the tz argument if we have a timezone suffix
        } else if matches!(suffix, Suffix::OffsetTz(_, _)) && eq(key, str_tz) {
            tz_display = match_interned_str("tz", value, |v, eq| {
                if eq(v, str_auto) {
                    Some(TzDisplay::Auto)
                } else if eq(v, str_never) {
                    Some(TzDisplay::Never)
                } else if eq(v, str_always) {
                    Some(TzDisplay::Always)
                } else {
                    None
                }
            })?;
        } else {
            return Ok(false);
        }
        Ok(true)
    })?;

    // Perform the formatting of the individual parts
    let date_fmt = date.format_iso(basic);
    let time_fmt = time.format_iso(unit, basic);
    let suffix_fmt = match suffix {
        Suffix::Absent => SuffixFormat::Absent,
        Suffix::Zulu => SuffixFormat::Zulu,
        Suffix::Offset(offset) => SuffixFormat::Offset(offset.format_iso(basic)),
        Suffix::OffsetTz(offset, ref tz) => match (tz.key.as_deref(), tz_display) {
            (Some(key), TzDisplay::Auto | TzDisplay::Always) => {
                SuffixFormat::OffsetTz(offset.format_iso(basic), key)
            }
            (_, TzDisplay::Never | TzDisplay::Auto) => {
                SuffixFormat::Offset(offset.format_iso(basic))
            }
            (None, TzDisplay::Always) => raise_value_err(FORMAT_ISO_NO_TZ_MSG)?,
        },
    };

    // Allocate the required space and write the parts
    let mut b = PyAsciiStrBuilder::new(
        date_fmt.len()
        + 1 // separator
        + time_fmt.len()
        + suffix_fmt.len(),
    )?;
    date_fmt.write(&mut b);
    b.write_byte(sep);
    time_fmt.write(&mut b);
    suffix_fmt.write(&mut b);
    Ok(b.finish())
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn test_format_2_digits() {
        for i in 0..100 {
            let s = format_2_digits(i);
            assert_eq!(
                s,
                <[u8; 2]>::try_from(format!("{:02}", i).as_bytes()).unwrap()
            );
        }
    }

    #[test]
    fn test_format_4_digits() {
        for i in 0..10000 {
            let s = format_4_digits(i);
            assert_eq!(
                s,
                <[u8; 4]>::try_from(format!("{:04}", i).as_bytes()).unwrap()
            );
        }
    }
}
