//! Helpers for writing formatted strings

use crate::{
    classes::offset_datetime::OffsetDateTime, docstrings::FORMAT_ISO_NO_TZ_MSG, py::*,
    pymodule::State, tz::store::TzPtr,
};

pub(crate) fn write_2_digits(n: u8, buf: &mut [u8]) {
    buf[0] = n / 10 + b'0';
    buf[1] = n % 10 + b'0';
}

pub(crate) fn write_4_digits(n: u16, buf: &mut [u8]) {
    buf[0] = (n / 1000) as u8 + b'0';
    buf[1] = (n / 100 % 10) as u8 + b'0';
    buf[2] = (n / 10 % 10) as u8 + b'0';
    buf[3] = (n % 10) as u8 + b'0';
}

/// Useful for storing formatted ASCII strings with flexible length
/// (e.g. due to decimal places)
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub(crate) struct AsciiArrayVec<const N: usize> {
    pub(crate) data: [u8; N],
    pub(crate) len: usize,
}

impl<const N: usize> std::ops::Deref for AsciiArrayVec<N> {
    type Target = [u8];

    fn deref(&self) -> &Self::Target {
        &self.data[..self.len]
    }
}

pub(crate) enum Precision {
    Hour,
    Minute,
    Second,
    Millisecond,
    Microsecond,
    Nanosecond,
    Auto,
}

enum TzDisplay {
    Always,
    Never,
    Auto,
}

/// Common routine for ZonedDateTime.format_iso() and
/// OffsetDateTime.format_iso()
#[inline]
pub(crate) fn format_iso(
    OffsetDateTime { date, time, offset }: OffsetDateTime,
    state: &State,
    args: &[PyObj],
    kwargs: &mut IterKwargs,
    tz: Option<TzPtr>,
) -> PyReturn {
    if !args.is_empty() {
        raise_type_err("format_iso() takes no positional arguments")?;
    }
    let mut sep = b'T';
    let mut unit = Precision::Auto;
    let mut extended = true; // Whether to use ISO "extended" format (or basic)
    let mut tz_display = match tz {
        None => TzDisplay::Never,
        Some(_) => TzDisplay::Always,
    };
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
            Ok(true)
        } else if eq(key, str_unit) {
            unit = match_interned_str("unit", value, |v, eq| {
                // Milliseconds is probably the most common choice, so
                // we check it first.
                if eq(v, str_millisecond) {
                    Some(Precision::Millisecond)
                } else if eq(v, str_hour) {
                    Some(Precision::Hour)
                } else if eq(v, str_minute) {
                    Some(Precision::Minute)
                } else if eq(v, str_second) {
                    Some(Precision::Second)
                } else if eq(v, str_microsecond) {
                    Some(Precision::Microsecond)
                } else if eq(v, str_nanosecond) {
                    Some(Precision::Nanosecond)
                } else if eq(v, str_auto) {
                    Some(Precision::Auto) // Auto cutoff
                } else {
                    None
                }
            })?;
            Ok(true)
        } else if eq(key, str_basic) {
            if value.is_true() {
                extended = false;
            } else if value.is_false() {
                extended = true;
            } else {
                raise_type_err("`basic` must be a boolean value")?;
            }
            Ok(true)
        } else if tz.is_some() && eq(key, str_tz) {
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
            Ok(true)
        } else {
            Ok(false)
        }
    })?;
    let date_str = date.format_iso_custom(extended);
    let time_str = time.format_iso_custom(unit, extended);
    let offset_str = offset.format_iso_custom(extended);

    let tzid = if let Some(t) = tz.as_deref() {
        match tz_display {
            TzDisplay::Auto => t.key.as_deref(),
            TzDisplay::Always => Some(t.key.as_deref().ok_or_value_err(FORMAT_ISO_NO_TZ_MSG)?),
            TzDisplay::Never => None,
        }
    } else {
        None
    };

    let mut b = PyAsciiStrBuilder::new(
        date_str.len
        + 1 // separator
        + time_str.len
        + offset_str.len
        + tzid
            .map_or(
                0, |s| s.len() + 2 // two brackets around the tz name
            ),
    )?;
    b.write_slice(&date_str);
    b.write_char(sep);
    b.write_slice(&time_str);
    b.write_slice(&offset_str);
    if let Some(key) = tzid {
        b.write_char(b'[');
        b.write_slice(key.as_bytes());
        b.write_char(b']');
    }
    Ok(b.build())
}
