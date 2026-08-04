//! Python argument parsing for ISO formatting.

use crate::{
    common::{
        compat::{RenamedKeyword, warn_deprecated},
        fmt::{Chunk, Precision, Sink},
    },
    docstrings::FORMAT_ISO_NO_TZ_MSG,
    domain::{
        date::Date,
        scalar::{Offset, OffsetFormat},
        time::Time,
    },
    py::*,
    pymodule::State,
};

#[derive(Clone, Copy)]
pub(crate) enum Suffix<'a> {
    Absent,
    Zulu,
    Offset(Offset),
    OffsetTz(Offset, Option<&'a str>),
}

enum SuffixFormat<'a> {
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
            Self::OffsetTz(offset, tz) => offset.len() + tz.len() + 2,
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

#[derive(Clone, Copy)]
enum TzDisplay {
    Required,
    Never,
    Auto,
}

pub(crate) fn parse_precision(obj: PyObj, state: &State) -> PyResult<Precision> {
    match_interned_str(
        "unit",
        obj,
        &[
            (*state.str_millisecond, Precision::Millisecond),
            (*state.str_hour, Precision::Hour),
            (*state.str_minute, Precision::Minute),
            (*state.str_second, Precision::Second),
            (*state.str_microsecond, Precision::Microsecond),
            (*state.str_nanosecond, Precision::Nanosecond),
            (*state.str_auto, Precision::Auto),
        ],
    )
}

pub(crate) fn format_date_iso(
    date: Date,
    state: &State,
    args: &[PyObj],
    kwargs: &mut IterKwargs,
) -> PyReturn {
    handle_no_args("format_iso", args)?;
    let mut basic = false;
    handle_kwargs("format_iso", kwargs, |key, value, eq| {
        if eq(key, *state.str_basic) {
            basic = value.expect_bool("basic")?;
        } else {
            return Ok(false);
        }
        Ok(true)
    })?;
    PyAsciiStrBuilder::format(date.iso_format(basic))
}

pub(crate) fn format_time_iso(
    time: Time,
    state: &State,
    args: &[PyObj],
    kwargs: &mut IterKwargs,
) -> PyReturn {
    handle_no_args("format_iso", args)?;
    let mut unit = Precision::Auto;
    let mut basic = false;
    handle_kwargs("format_iso", kwargs, |key, value, eq| {
        if eq(key, *state.str_unit) {
            unit = parse_precision(value, state)?;
        } else if eq(key, *state.str_basic) {
            basic = value.expect_bool("basic")?;
        } else {
            return Ok(false);
        }
        Ok(true)
    })?;
    PyAsciiStrBuilder::format(time.iso_format(unit, basic))
}

/// Format a date and time with an optional timezone suffix.
pub(crate) fn format_datetime_iso(
    date: Date,
    time: Time,
    state: &State,
    args: &[PyObj],
    kwargs: &mut IterKwargs,
    suffix: Suffix<'_>,
) -> PyReturn {
    handle_no_args("format_iso", args)?;

    let mut sep = b'T';
    let mut unit = Precision::Auto;
    let mut basic = false;
    let mut display_arg = RenamedKeyword::default();
    handle_kwargs("format_iso", kwargs, |key, value, eq| {
        if eq(key, *state.str_sep) {
            sep = match_interned_str(
                "sep",
                value,
                &[(*state.str_space, b' '), (*state.str_t, b'T')],
            )?;
        } else if eq(key, *state.str_unit) {
            unit = parse_precision(value, state)?;
        } else if eq(key, *state.str_basic) {
            basic = value.expect_bool("basic")?;
        } else if matches!(suffix, Suffix::OffsetTz(_, _)) && eq(key, *state.str_tz_display) {
            display_arg.set_new(value);
        } else if matches!(suffix, Suffix::OffsetTz(_, _)) && eq(key, *state.str_tz) {
            display_arg.set_old(value);
        } else {
            return Ok(false);
        }
        Ok(true)
    })?;

    let tz_display = match display_arg.finish(
        state,
        "format_iso",
        "tz_display",
        "tz",
        c"'tz' is deprecated; use 'tz_display' instead",
        1,
    )? {
        None => TzDisplay::Required,
        Some(value) if value.is(*state.str_always) => {
            warn_deprecated(
                state,
                c"tz_display='always' is deprecated; use 'required' instead",
                1,
            )?;
            TzDisplay::Required
        }
        Some(value) => match_interned_str(
            "tz_display",
            value,
            &[
                (*state.str_auto, TzDisplay::Auto),
                (*state.str_never, TzDisplay::Never),
                (*state.str_required, TzDisplay::Required),
            ],
        )?,
    };

    let suffix = match suffix {
        Suffix::Absent => SuffixFormat::Absent,
        Suffix::Zulu => SuffixFormat::Zulu,
        Suffix::Offset(offset) => SuffixFormat::Offset(offset.iso_format(basic)),
        Suffix::OffsetTz(offset, tz_key) => match (tz_key, tz_display) {
            (Some(key), TzDisplay::Auto | TzDisplay::Required) => {
                SuffixFormat::OffsetTz(offset.iso_format(basic), key)
            }
            (_, TzDisplay::Never | TzDisplay::Auto) => {
                SuffixFormat::Offset(offset.iso_format(basic))
            }
            (None, TzDisplay::Required) => raise_value_err(FORMAT_ISO_NO_TZ_MSG)?,
        },
    };

    PyAsciiStrBuilder::format((
        date.iso_format(basic),
        sep,
        time.iso_format(unit, basic),
        suffix,
    ))
}
