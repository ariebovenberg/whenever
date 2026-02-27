//! Functionality for rounding datetime values
use crate::{py::*, pymodule::State};

#[derive(Debug, Copy, Clone)]
pub(crate) enum Mode {
    Floor,
    Ceil,
    Trunc,
    Expand,
    HalfFloor,
    HalfCeil,
    HalfEven,
    HalfTrunc,
    HalfExpand,
}

/// Rounding mode resolved for the euclidean domain.
/// After sign-based normalization, these modes can be used directly
/// in euclidean quotient/remainder rounding without needing the sign.
///
/// In the euclidean domain:
/// - `Trunc`: keep the quotient as-is (≡ floor, towards -∞)
/// - `Expand`: increment the quotient (≡ ceil, towards +∞)
#[derive(Debug, Copy, Clone)]
pub(crate) enum AbsMode {
    Trunc,
    Expand,
    HalfTrunc,
    HalfExpand,
    HalfEven,
}

impl Mode {
    /// Resolve sign-dependent modes (Floor/Ceil, Trunc/Expand) into
    /// sign-independent euclidean-domain modes.
    pub(crate) fn to_abs(self, is_negative: bool) -> AbsMode {
        match (self, is_negative) {
            (Mode::Floor, _) | (Mode::Trunc, false) | (Mode::Expand, true) => AbsMode::Trunc,
            (Mode::Ceil, _) | (Mode::Expand, false) | (Mode::Trunc, true) => AbsMode::Expand,
            (Mode::HalfFloor, _) | (Mode::HalfTrunc, false) | (Mode::HalfExpand, true) => {
                AbsMode::HalfTrunc
            }
            (Mode::HalfCeil, _) | (Mode::HalfExpand, false) | (Mode::HalfTrunc, true) => {
                AbsMode::HalfExpand
            }
            (Mode::HalfEven, _) => AbsMode::HalfEven,
        }
    }
}

impl Mode {
    fn from_py(
        s: PyObj,
        str_floor: PyObj,
        str_ceil: PyObj,
        str_trunc: PyObj,
        str_expand: PyObj,
        str_half_floor: PyObj,
        str_half_ceil: PyObj,
        str_half_even: PyObj,
        str_half_trunc: PyObj,
        str_half_expand: PyObj,
    ) -> PyResult<Mode> {
        match_interned_str("mode", s, |v, eq| {
            Some(if eq(v, str_floor) {
                Mode::Floor
            } else if eq(v, str_ceil) {
                Mode::Ceil
            } else if eq(v, str_trunc) {
                Mode::Trunc
            } else if eq(v, str_expand) {
                Mode::Expand
            } else if eq(v, str_half_floor) {
                Mode::HalfFloor
            } else if eq(v, str_half_ceil) {
                Mode::HalfCeil
            } else if eq(v, str_half_even) {
                Mode::HalfEven
            } else if eq(v, str_half_trunc) {
                Mode::HalfTrunc
            } else if eq(v, str_half_expand) {
                Mode::HalfExpand
            } else {
                None?
            })
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
    Week,
}

impl Unit {
    #[allow(clippy::too_many_arguments)]
    fn from_py(
        s: PyObj,
        str_nanosecond: PyObj,
        str_microsecond: PyObj,
        str_millisecond: PyObj,
        str_second: PyObj,
        str_minute: PyObj,
        str_hour: PyObj,
        str_day: PyObj,
        str_week: PyObj,
        for_delta: bool,
    ) -> PyResult<Unit> {
        // OPTIMIZE: run the comparisons in order if likelihood
        match_interned_str("unit", s, |v, eq| {
            Some(if eq(v, str_nanosecond) {
                Unit::Nanosecond
            } else if eq(v, str_microsecond) {
                Unit::Microsecond
            } else if eq(v, str_millisecond) {
                Unit::Millisecond
            } else if eq(v, str_second) {
                Unit::Second
            } else if eq(v, str_minute) {
                Unit::Minute
            } else if eq(v, str_hour) {
                Unit::Hour
            } else if eq(v, str_day) {
                Unit::Day
            } else if for_delta && eq(v, str_week) {
                Unit::Week
            } else {
                None?
            })
        })
    }

    fn increment_from_py(self, v: PyObj, for_delta: bool) -> PyResult<i64> {
        let inc = v
            .cast_allow_subclass::<PyInt>()
            .ok_or_type_err("increment must be an integer")?
            .to_i64()?;
        if inc <= 0 {
            raise_value_err("increment must be a positive integer")?;
        }
        let ns_per_unit: i64 = match self {
            Unit::Nanosecond => 1,
            Unit::Microsecond => 1_000,
            Unit::Millisecond => 1_000_000,
            Unit::Second => 1_000_000_000,
            Unit::Minute => 60_000_000_000,
            Unit::Hour => 3_600_000_000_000,
            Unit::Day => 86_400_000_000_000,
            Unit::Week => 604_800_000_000_000,
        };
        let increment_ns = inc
            .checked_mul(ns_per_unit)
            .ok_or_value_err("increment too large")?;
        if !for_delta && 86_400_000_000_000 % increment_ns != 0 {
            raise_value_err("Invalid increment. Must divide a 24-hour day evenly.")?;
        }
        Ok(increment_ns)
    }

    const fn default_increment(self) -> i64 {
        match self {
            Unit::Nanosecond => 1,
            Unit::Microsecond => 1_000,
            Unit::Millisecond => 1_000_000,
            Unit::Second => 1_000_000_000,
            Unit::Minute => 60 * 1_000_000_000,
            Unit::Hour => 3_600 * 1_000_000_000,
            Unit::Day => 86_400 * 1_000_000_000,
            Unit::Week => 604_800 * 1_000_000_000,
        }
    }
}

pub(crate) fn parse_args(
    state: &State,
    args: &[PyObj],
    kwargs: &mut IterKwargs,
    for_delta: bool,
    ignore_dst_kwarg: bool,
) -> PyResult<(Unit, i64, Mode, bool)> {
    let &State {
        str_nanosecond,
        str_microsecond,
        str_millisecond,
        str_second,
        str_minute,
        str_hour,
        str_day,
        str_week,
        str_unit,
        str_mode,
        str_increment,
        str_floor,
        str_ceil,
        str_trunc,
        str_expand,
        str_half_floor,
        str_half_ceil,
        str_half_even,
        str_half_trunc,
        str_half_expand,
        str_ignore_dst,
        ..
    } = state;

    let num_argkwargs = args.len() + kwargs.len() as usize;
    if ignore_dst_kwarg {
        if args.len() > 3 {
            raise_type_err(format!(
                "round() takes at most 3 positional arguments, got {}",
                args.len()
            ))?;
        }
        if num_argkwargs > 4 {
            raise_type_err(format!(
                "round() takes at most 4 arguments, got {num_argkwargs}"
            ))?;
        }
    } else if num_argkwargs > 3 {
        raise_type_err(format!(
            "round() takes at most 3 arguments, got {num_argkwargs}"
        ))?;
    }
    let mut got_ignore_dst = false;
    let mut arg_obj: [Option<PyObj>; 3] = [None, None, None];
    for (i, &obj) in args.iter().enumerate() {
        arg_obj[i] = Some(obj)
    }
    handle_kwargs("round", kwargs, |key, value, eq| {
        for (i, &kwname) in [str_unit, str_increment, str_mode].iter().enumerate() {
            if eq(key, kwname) {
                if arg_obj[i].replace(value).is_some() {
                    raise_type_err(format!("round() got multiple values for argument {kwname}"))?;
                }
                return Ok(true);
            }
        }
        if ignore_dst_kwarg && eq(key, str_ignore_dst) {
            got_ignore_dst = true;
            return Ok(true);
        }
        Ok(false)
    })?;

    let unit = arg_obj[0]
        .map(|v| {
            Unit::from_py(
                v,
                str_nanosecond,
                str_microsecond,
                str_millisecond,
                str_second,
                str_minute,
                str_hour,
                str_day,
                str_week,
                for_delta,
            )
        })
        .transpose()?
        .unwrap_or(Unit::Second);
    let increment = arg_obj[1]
        .map(|v| unit.increment_from_py(v, for_delta))
        .transpose()?
        .unwrap_or_else(|| unit.default_increment());
    let mode = arg_obj[2]
        .map(|v| {
            Mode::from_py(
                v,
                str_floor,
                str_ceil,
                str_trunc,
                str_expand,
                str_half_floor,
                str_half_ceil,
                str_half_even,
                str_half_trunc,
                str_half_expand,
            )
        })
        .transpose()?
        .unwrap_or(Mode::HalfEven);

    Ok((unit, increment, mode, got_ignore_dst))
}

#[cfg(test)]
mod tests {
    use super::*;
}
