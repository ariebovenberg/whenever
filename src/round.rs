use std::ptr::NonNull;

use crate::{common::*, docstrings as doc, State};
use pyo3_ffi::*;

#[derive(Debug, Copy, Clone)]
pub(crate) enum Mode {
    Floor,
    Ceil,
    HalfFloor,
    HalfCeil,
    HalfEven,
}

impl Mode {
    unsafe fn from_py(
        s: *mut PyObject,
        str_floor: *mut PyObject,
        str_ceil: *mut PyObject,
        str_half_floor: *mut PyObject,
        str_half_ceil: *mut PyObject,
        str_half_even: *mut PyObject,
    ) -> PyResult<Mode> {
        match_interned_str("mode", s, |v, eq| {
            if eq(v, str_floor) {
                Some(Mode::Floor)
            } else if eq(v, str_ceil) {
                Some(Mode::Ceil)
            } else if eq(v, str_half_floor) {
                Some(Mode::HalfFloor)
            } else if eq(v, str_half_ceil) {
                Some(Mode::HalfCeil)
            } else if eq(v, str_half_even) {
                Some(Mode::HalfEven)
            } else {
                None
            }
        })
    }
}

#[derive(Debug, Copy, Clone, Ord, PartialOrd, Eq, PartialEq)]
pub(crate) enum Unit {
    Nanosecond,
    Microsecond,
    Millisecond,
    Second,
    Minute,
    Hour,
    Day,
}

impl Unit {
    #[allow(clippy::too_many_arguments)]
    unsafe fn from_py(
        s: *mut PyObject,
        str_nanosecond: *mut PyObject,
        str_microsecond: *mut PyObject,
        str_millisecond: *mut PyObject,
        str_second: *mut PyObject,
        str_minute: *mut PyObject,
        str_hour: *mut PyObject,
        str_day: *mut PyObject,
    ) -> PyResult<Unit> {
        match_interned_str("unit", s, |v, eq| {
            if eq(v, str_nanosecond) {
                Some(Unit::Nanosecond)
            } else if eq(v, str_microsecond) {
                Some(Unit::Microsecond)
            } else if eq(v, str_millisecond) {
                Some(Unit::Millisecond)
            } else if eq(v, str_second) {
                Some(Unit::Second)
            } else if eq(v, str_minute) {
                Some(Unit::Minute)
            } else if eq(v, str_hour) {
                Some(Unit::Hour)
            } else if eq(v, str_day) {
                Some(Unit::Day)
            } else {
                None
            }
        })
    }

    unsafe fn increment_from_py(
        self,
        v: *mut PyObject,
        hours_increment_always_ok: bool,
    ) -> PyResult<i64> {
        let inc = v.to_i64()?.ok_or_type_err("increment must be an integer")?;
        if inc <= 0 || inc >= 1000 {
            Err(value_err!("increment must be between 0 and 1000"))?;
        }
        match self {
            Unit::Nanosecond => (1_000 % inc == 0)
                .then_some(inc)
                .ok_or_value_err("Increment must be a divisor of 1000"),
            Unit::Microsecond => (1_000 % inc == 0)
                .then_some(inc * 1_000)
                .ok_or_value_err("Increment must be a divisor of 1000"),
            Unit::Millisecond => (1_000 % inc == 0)
                .then_some(inc * 1_000_000)
                .ok_or_value_err("Increment must be a divisor of 1000"),
            Unit::Second => (60 % inc == 0)
                .then_some(inc * 1_000_000_000)
                .ok_or_value_err("Increment must be a divisor of 60"),
            Unit::Minute => (60 % inc == 0)
                .then_some(inc * 60 * 1_000_000_000)
                .ok_or_value_err("Increment must be a divisor of 60"),
            Unit::Hour => (hours_increment_always_ok || 24 % inc == 0)
                .then_some(inc * 3_600 * 1_000_000_000)
                .ok_or_value_err("Increment must be a divisor of 24"),
            Unit::Day => (inc == 1)
                .then_some(86_400 * 1_000_000_000)
                .ok_or_value_err("Increment must be 1 for 'day' unit"),
        }
    }

    unsafe fn default_increment(self) -> i64 {
        match self {
            Unit::Nanosecond => 1,
            Unit::Microsecond => 1_000,
            Unit::Millisecond => 1_000_000,
            Unit::Second => 1_000_000_000,
            Unit::Minute => 60 * 1_000_000_000,
            Unit::Hour => 3_600 * 1_000_000_000,
            Unit::Day => 86_400 * 1_000_000_000,
        }
    }
}

// NOTE: the caller still needs to check whenever 'day' is valid for them
pub(crate) unsafe fn parse_args(
    state: &State,
    args: &[*mut PyObject],
    kwargs: &mut KwargIter,
    hours_largest_unit: bool,
    ignore_dst_kwarg: bool,
) -> PyResult<(Unit, i64, Mode)> {
    let &State {
        str_nanosecond,
        str_microsecond,
        str_millisecond,
        str_second,
        str_minute,
        str_hour,
        str_day,
        str_unit,
        str_mode,
        str_increment,
        str_floor,
        str_ceil,
        str_half_floor,
        str_half_ceil,
        str_half_even,
        ..
    } = state;

    let num_argkwargs = args.len() + kwargs.len() as usize;
    if ignore_dst_kwarg {
        if args.len() > 3 {
            Err(type_err!(
                "round() takes at most 3 positional arguments, got {}",
                args.len()
            ))?;
        }
        if num_argkwargs > 4 {
            Err(type_err!(
                "round() takes at most 4 arguments, got {}",
                num_argkwargs
            ))?;
        }
    } else if num_argkwargs > 3 {
        Err(type_err!(
            "round() takes at most 3 arguments, got {}",
            num_argkwargs
        ))?;
    }
    let mut ignore_dst = false;
    let mut arg_obj: [Option<NonNull<PyObject>>; 3] = [None, None, None];
    for i in 0..args.len() {
        arg_obj[i] = Some(NonNull::new_unchecked(args[i]));
    }
    handle_kwargs("round", kwargs, |key, value, eq| {
        for (i, &kwname) in [str_unit, str_increment, str_mode].iter().enumerate() {
            if eq(key, kwname) {
                if arg_obj[i].replace(NonNull::new_unchecked(value)).is_some() {
                    Err(type_err!(
                        "round() got multiple values for argument {}",
                        kwname.repr()
                    ))?;
                }
                return Ok(true);
            }
        }
        if ignore_dst_kwarg && eq(key, state.str_ignore_dst) {
            if value == Py_True() {
                ignore_dst = true;
            }
            return Ok(true);
        }
        Ok(false)
    })?;

    if ignore_dst_kwarg && !ignore_dst {
        Err(py_err!(
            state.exc_implicitly_ignoring_dst,
            doc::OFFSET_ROUNDING_DST_MSG
        ))?
    }

    let unit = arg_obj[0]
        .map(|v| {
            Unit::from_py(
                v.as_ptr(),
                str_nanosecond,
                str_microsecond,
                str_millisecond,
                str_second,
                str_minute,
                str_hour,
                str_day,
            )
        })
        .transpose()?
        .unwrap_or(Unit::Second);
    let increment = arg_obj[1]
        .map(|v| unit.increment_from_py(v.as_ptr(), hours_largest_unit))
        .transpose()?
        .unwrap_or_else(|| unit.default_increment());
    let mode = arg_obj[2]
        .map(|v| {
            Mode::from_py(
                v.as_ptr(),
                str_floor,
                str_ceil,
                str_half_floor,
                str_half_ceil,
                str_half_even,
            )
        })
        .transpose()?
        .unwrap_or(Mode::HalfEven);

    Ok((unit, increment, mode))
}
