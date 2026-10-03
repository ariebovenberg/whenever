//! Python argument parsing for ISO formatting.

use crate::{
    common::fmt::{Chunk, Precision, Sink},
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
    IfAvailable,
    Omit,
}

fn tz_display_choices(state: &State) -> [(PyObj, TzDisplay); 3] {
    [
        (*state.strs.required, TzDisplay::Required),
        (*state.strs.if_available, TzDisplay::IfAvailable),
        (*state.strs.omit, TzDisplay::Omit),
    ]
}

pub(crate) fn parse_precision(obj: PyObj, state: &State) -> PyResult<Precision> {
    match_interned_str(
        "unit",
        obj,
        &[
            (*state.strs.millisecond, Precision::Millisecond),
            (*state.strs.hour, Precision::Hour),
            (*state.strs.minute, Precision::Minute),
            (*state.strs.second, Precision::Second),
            (*state.strs.microsecond, Precision::Microsecond),
            (*state.strs.nanosecond, Precision::Nanosecond),
            (*state.strs.auto, Precision::Auto),
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
    handle_kwargs("format_iso", kwargs, |k, v, eq| {
        if eq(k, *state.strs.basic) {
            basic = v.is_truthy()?;
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
    handle_kwargs("format_iso", kwargs, |k, v, eq| {
        if eq(k, *state.strs.unit) {
            unit = parse_precision(v, state)?;
        } else if eq(k, *state.strs.basic) {
            basic = v.is_truthy()?;
        } else {
            return Ok(false);
        }
        Ok(true)
    })?;
    PyAsciiStrBuilder::format(time.iso_format(unit, basic))
}

/// Format a date and time with an optional time zone suffix.
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
    let mut display_obj = None;
    handle_kwargs("format_iso", kwargs, |k, v, eq| {
        if eq(k, *state.strs.sep) {
            sep = match_interned_str(
                "sep",
                v,
                &[(*state.strs.space, b' '), (*state.strs.t, b'T')],
            )?;
        } else if eq(k, *state.strs.unit) {
            unit = parse_precision(v, state)?;
        } else if eq(k, *state.strs.basic) {
            basic = v.is_truthy()?;
        } else if matches!(suffix, Suffix::OffsetTz(_, _)) && eq(k, *state.strs.tz_id_display) {
            display_obj = Some(v);
        } else {
            return Ok(false);
        }
        Ok(true)
    })?;

    let tz_id_display = display_obj
        .map(|v| match_interned_str("tz_id_display", v, &tz_display_choices(state)))
        .transpose()?
        .unwrap_or(TzDisplay::Required);

    let suffix = match suffix {
        Suffix::Absent => SuffixFormat::Absent,
        Suffix::Zulu => SuffixFormat::Zulu,
        Suffix::Offset(offset) => SuffixFormat::Offset(offset.iso_format(basic)),
        Suffix::OffsetTz(offset, tz_key) => match (tz_key, tz_id_display) {
            (Some(key), TzDisplay::IfAvailable | TzDisplay::Required) => {
                SuffixFormat::OffsetTz(offset.iso_format(basic), key)
            }
            (_, TzDisplay::Omit | TzDisplay::IfAvailable) => {
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
