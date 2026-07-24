//! Helpers for writing formatted strings

use crate::{
    docstrings::FORMAT_ISO_NO_TZ_MSG,
    domain::{
        date::Date,
        scalar::{Offset, OffsetFormat},
        time::Time,
    },
    py::*,
    pymodule::State,
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

/// Something you can write bytes into.
pub(crate) trait Sink {
    fn write_byte(&mut self, b: u8);
    fn write(&mut self, s: &[u8]);
}

/// Something with a fixed length that can write itself into a `Sink`.
/// Used for "fast" formatting of known-size chunks.
pub(crate) trait Chunk {
    fn len(&self) -> usize;
    fn write(&self, b: &mut impl Sink);
}

impl<T: AsRef<[u8]>> Chunk for &T {
    fn len(&self) -> usize {
        self.as_ref().len()
    }
    fn write(&self, b: &mut impl Sink) {
        b.write(self.as_ref());
    }
}

impl Chunk for u8 {
    fn len(&self) -> usize {
        1
    }

    fn write(&self, b: &mut impl Sink) {
        b.write_byte(*self);
    }
}

macro_rules! impl_chunk_for_tuples {
    ( $( $name:ident : $idx:tt ),+ ) => {
        impl<$( $name: Chunk ),+> Chunk for ( $( $name ),+ ) {
            fn len(&self) -> usize {
                0 $( + self.$idx.len() )+
            }

            fn write(&self, b: &mut impl Sink) {
                $( self.$idx.write(b); )+
            }
        }
    };
}

// Generate the impls
impl_chunk_for_tuples!(T0:0, T1:1);
impl_chunk_for_tuples!(T0:0, T1:1, T2:2);
impl_chunk_for_tuples!(T0:0, T1:1, T2:2, T3:3);
impl_chunk_for_tuples!(T0:0, T1:1, T2:2, T3:3, T4:4);
impl_chunk_for_tuples!(T0:0, T1:1, T2:2, T3:3, T4:4, T5:5);
impl_chunk_for_tuples!(T0:0, T1:1, T2:2, T3:3, T4:4, T5:5, T6:6);
impl_chunk_for_tuples!(T0:0, T1:1, T2:2, T3:3, T4:4, T5:5, T6:6, T7:7);
impl_chunk_for_tuples!(T0:0, T1:1, T2:2, T3:3, T4:4, T5:5, T6:6, T7:7, T8:8);
impl_chunk_for_tuples!(T0:0, T1:1, T2:2, T3:3, T4:4, T5:5, T6:6, T7:7, T8:8, T9:9);

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

impl<const N: usize> Sink for ArrayWriter<N> {
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

#[derive(Debug, Clone, Copy, PartialEq, Eq, PartialOrd, Ord)]
pub(crate) enum Precision {
    Auto,
    Nanosecond,
    Microsecond,
    Millisecond,
    Second,
    Minute,
    Hour,
}

impl Precision {
    pub(crate) fn from_py(obj: PyObj, state: &State) -> PyResult<Self> {
        match_interned_str("unit", obj, |v, eq| {
            if eq(v, *state.str_millisecond) {
                Some(Self::Millisecond)
            } else if eq(v, *state.str_hour) {
                Some(Self::Hour)
            } else if eq(v, *state.str_minute) {
                Some(Self::Minute)
            } else if eq(v, *state.str_second) {
                Some(Self::Second)
            } else if eq(v, *state.str_microsecond) {
                Some(Self::Microsecond)
            } else if eq(v, *state.str_nanosecond) {
                Some(Self::Nanosecond)
            } else if eq(v, *state.str_auto) {
                Some(Self::Auto)
            } else {
                None
            }
        })
    }
}

/// Suffix kind of a ISO8601 formatted string
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub(crate) enum Suffix<'a> {
    Absent,                            // No suffix (i.e. local/naive datetime)
    Zulu,                              // Static Z (Zulu, i.e. UTC)
    Offset(Offset),                    // Offset only
    OffsetTz(Offset, Option<&'a str>), // Offset and timezone name (in brackets)
}

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub(crate) enum SuffixFormat<'a> {
    Absent,
    Zulu,
    Offset(OffsetFormat),
    OffsetTz(OffsetFormat, &'a str),
}

impl Chunk for SuffixFormat<'_> {
    fn len(&self) -> usize {
        match self {
            Self::Absent => 0,
            Self::Zulu => 1,
            Self::Offset(fmt) => fmt.len(),
            Self::OffsetTz(offset, tz) => {
                offset.len() + tz.len() + 2 // two brackets around the tz name
            }
        }
    }

    fn write(&self, b: &mut impl Sink) {
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
    suffix: Suffix<'_>,
) -> PyReturn {
    if !args.is_empty() {
        raise_type_err("format_iso() takes no positional arguments")?;
    }

    // As-efficient-as-possible assignment of keyword arguments
    let mut sep = b'T';
    let mut unit = Precision::Auto;
    let mut basic = false;
    let mut tz_display = TzDisplay::Always;
    handle_kwargs("format_iso", kwargs, |key, value, eq| {
        if eq(key, *state.str_sep) {
            sep = match_interned_str("sep", value, |v, eq| {
                if eq(v, *state.str_space) {
                    Some(b' ')
                } else if eq(v, *state.str_t) {
                    Some(b'T')
                } else {
                    None
                }
            })?;
        } else if eq(key, *state.str_unit) {
            unit = Precision::from_py(value, state)?;
        } else if eq(key, *state.str_basic) {
            basic = value.expect_bool("basic")?;
        // Only allow the tz argument if we have a timezone suffix
        } else if matches!(suffix, Suffix::OffsetTz(_, _)) && eq(key, *state.str_tz) {
            tz_display = match_interned_str("tz", value, |v, eq| {
                if eq(v, *state.str_auto) {
                    Some(TzDisplay::Auto)
                } else if eq(v, *state.str_never) {
                    Some(TzDisplay::Never)
                } else if eq(v, *state.str_always) {
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
    let date_fmt = date.iso_format(basic);
    let time_fmt = time.iso_format(unit, basic);
    let suffix_fmt = match suffix {
        Suffix::Absent => SuffixFormat::Absent,
        Suffix::Zulu => SuffixFormat::Zulu,
        Suffix::Offset(offset) => SuffixFormat::Offset(offset.iso_format(basic)),
        Suffix::OffsetTz(offset, tz_key) => match (tz_key, tz_display) {
            (Some(key), TzDisplay::Auto | TzDisplay::Always) => {
                SuffixFormat::OffsetTz(offset.iso_format(basic), key)
            }
            (_, TzDisplay::Never | TzDisplay::Auto) => {
                SuffixFormat::Offset(offset.iso_format(basic))
            }
            (None, TzDisplay::Always) => raise_value_err(FORMAT_ISO_NO_TZ_MSG)?,
        },
    };

    PyAsciiStrBuilder::format((date_fmt, sep, time_fmt, suffix_fmt))
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
