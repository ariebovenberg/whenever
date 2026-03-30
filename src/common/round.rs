//! Functionality for rounding values
use std::num::{NonZero, NonZeroU64, NonZeroU128};

use crate::{
    classes::time_delta::DeltaIncrement,
    common::scalar::{
        NS_PER_DAY, NS_PER_HOUR, NS_PER_MICROSEC, NS_PER_MILLISEC, NS_PER_MINUTE, NS_PER_SEC,
        NS_PER_WEEK, SubSecNanos,
    },
    docstrings as doc,
    py::*,
    pymodule::State,
};

#[derive(Debug, Copy, Clone)]
pub(crate) struct ModeStrs {
    pub(crate) str_floor: PyObj,
    pub(crate) str_ceil: PyObj,
    pub(crate) str_trunc: PyObj,
    pub(crate) str_expand: PyObj,
    pub(crate) str_half_floor: PyObj,
    pub(crate) str_half_ceil: PyObj,
    pub(crate) str_half_even: PyObj,
    pub(crate) str_half_trunc: PyObj,
    pub(crate) str_half_expand: PyObj,
}

#[derive(Debug, Copy, Clone, Eq, PartialEq)]
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
#[derive(Debug, Copy, Clone, Eq, PartialEq)]
pub(crate) enum AbsMode {
    Trunc,
    Expand,
    HalfTrunc,
    HalfExpand,
    HalfEven,
}

// FUTURE: can we simplify the different ways of transforming to "abs" round mode?
impl Mode {
    /// Resolve sign-dependent modes into sign-independent AbsMode
    /// for the **euclidean quotient** domain (used by TimeDelta::round, Instant::round).
    /// Here Floor/Ceil are "native" (already aligned with quotient direction),
    /// while Trunc/Expand need sign-based swapping.
    ///
    /// Use this when rounding a plain signed integer (e.g. nanoseconds, epoch seconds).
    pub(crate) fn to_abs_euclid(self, is_negative: bool) -> AbsMode {
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

    /// Resolve sign-dependent modes into sign-independent AbsMode
    /// for the **sign-magnitude** domain (used by since/until rounding).
    /// Here Trunc/Expand are "native" (already absolute),
    /// while Floor/Ceil need sign-based swapping.
    ///
    /// Use this when rounding a delta whose sign is tracked separately
    /// (e.g. "3 months backward", where `neg = true`).
    pub(crate) fn to_abs_trunc(self, neg: bool) -> AbsMode {
        let positive = !neg;
        match (self, positive) {
            (Mode::Trunc, _) | (Mode::Floor, true) | (Mode::Ceil, false) => AbsMode::Trunc,
            (Mode::Expand, _) | (Mode::Ceil, true) | (Mode::Floor, false) => AbsMode::Expand,
            (Mode::HalfTrunc, _) | (Mode::HalfFloor, true) | (Mode::HalfCeil, false) => {
                AbsMode::HalfTrunc
            }
            (Mode::HalfExpand, _) | (Mode::HalfCeil, true) | (Mode::HalfFloor, false) => {
                AbsMode::HalfExpand
            }
            (Mode::HalfEven, _) => AbsMode::HalfEven,
        }
    }
}

impl Mode {
    pub(crate) fn from_py(s: PyObj, strs: ModeStrs) -> PyResult<Mode> {
        Self::from_py_named("mode", s, strs)
    }

    pub(crate) fn from_py_named(name: &str, s: PyObj, strs: ModeStrs) -> PyResult<Mode> {
        let ModeStrs {
            str_floor,
            str_ceil,
            str_trunc,
            str_expand,
            str_half_floor,
            str_half_ceil,
            str_half_even,
            str_half_trunc,
            str_half_expand,
        } = strs;
        match_interned_str(name, s, |v, eq| {
            if eq(v, str_floor) {
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
            }
            .into()
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

    pub(crate) const fn default_increment(self) -> u64 {
        match self {
            Unit::Nanosecond => 1,
            Unit::Microsecond => NS_PER_MICROSEC as _,
            Unit::Millisecond => NS_PER_MILLISEC as _,
            Unit::Second => NS_PER_SEC as _,
            Unit::Minute => NS_PER_MINUTE,
            Unit::Hour => NS_PER_HOUR,
            Unit::Day => NS_PER_DAY,
            Unit::Week => NS_PER_WEEK,
        }
    }
}

/// Parsed rounding increment from `round()` arguments.
#[derive(Debug, Copy, Clone, Eq, PartialEq)]
pub(crate) enum RoundIncrement {
    /// Round by an exact time increment
    Exact(NonZeroU64),
    /// Round to day boundaries (local time types only).
    Day,
}

/// Parsed result from `round()` arguments.
#[derive(Debug, Copy, Clone)]
pub(crate) struct Args {
    pub(crate) increment: RoundIncrement,
    pub(crate) mode: Mode,
    pub(crate) got_ignore_dst: bool,
    pub(crate) suppress_stale: bool,
}

static INCREMENT_DIV_MSG: &str =
    "Invalid increment. Must be positive and divide a 24-hour day evenly.";

impl Args {
    pub(crate) fn parse(
        state: &State,
        args: &[PyObj],
        kwargs: &mut IterKwargs,
        ignore_dst_kwarg: bool,
    ) -> PyResult<Self> {
        let &State {
            str_nanosecond,
            str_microsecond,
            str_millisecond,
            str_second,
            str_minute,
            str_hour,
            str_day,
            str_week,
            str_mode,
            str_increment,
            round_mode_strs,
            str_ignore_dst,
            str_stale_offset_ok,
            time_delta_type,
            ..
        } = state;

        let opt_arg = handle_opt_arg("round", args)?;

        let mut mode = Mode::HalfEven;
        let mut got_ignore_dst = false;
        let mut suppress_stale = false;
        let mut increment_kwarg = None;
        handle_kwargs("round", kwargs, |key, value, eq| {
            if eq(key, str_mode) {
                mode = Mode::from_py(value, round_mode_strs)?;
            } else if eq(key, str_increment) {
                let raw_increment = value
                    .cast_allow_subclass::<PyInt>()
                    .ok_or_value_err("increment must be an integer")?
                    .to_i64()?;
                if raw_increment <= 0 {
                    raise_value_err("increment must be a positive integer")?;
                }
                // SAFETY: we just checked that it's >0
                increment_kwarg = Some(unsafe { NonZeroU64::new_unchecked(raw_increment as _) });
            } else if ignore_dst_kwarg && eq(key, str_ignore_dst) {
                got_ignore_dst = true;
            } else if ignore_dst_kwarg && eq(key, str_stale_offset_ok) {
                suppress_stale = value.is_truthy();
            } else {
                return Ok(false);
            }
            Ok(true)
        })?;

        let increment = match opt_arg {
            None => RoundIncrement::Exact(unsafe { NonZeroU64::new_unchecked(1_000_000_000) }),
            Some(arg) => {
                if let Some(delta) = arg.extract(time_delta_type) {
                    let nanos = delta
                        .total_nanos()
                        .try_into()
                        .ok()
                        .and_then(NonZero::<u64>::new)
                        .filter(|&n| NS_PER_DAY.is_multiple_of(n.get()))
                        .ok_or_value_err(INCREMENT_DIV_MSG)?;
                    if increment_kwarg.is_some() {
                        raise_type_err("cannot specify an increment with a TimeDelta argument")?;
                    }
                    RoundIncrement::Exact(nanos)
                } else {
                    let unit = Unit::from_py(
                        arg,
                        str_nanosecond,
                        str_microsecond,
                        str_millisecond,
                        str_second,
                        str_minute,
                        str_hour,
                        str_day,
                        str_week,
                        false,
                    )?;
                    let increment_int = increment_kwarg.unwrap_or(NonZeroU64::MIN);
                    debug_assert!(unit != Unit::Week);
                    if unit == Unit::Day {
                        if increment_int.get() != 1 {
                            raise_value_err(INCREMENT_DIV_MSG)?;
                        }
                        RoundIncrement::Day
                    } else {
                        RoundIncrement::Exact(unsafe {
                            let n = unit.default_increment() * increment_int.get();
                            if !NS_PER_DAY.is_multiple_of(n) {
                                raise_value_err(INCREMENT_DIV_MSG)?;
                            }
                            NonZero::<u64>::new_unchecked(n)
                        })
                    }
                }
            }
        };

        Ok(Args {
            increment,
            mode,
            got_ignore_dst,
            suppress_stale,
        })
    }
}

/// Parsed arguments for `TimeDelta.round()`. `increment` is always positive and nonzero
/// (invariant upheld by `parse()`).
#[derive(Debug, Copy, Clone)]
pub(crate) struct DeltaArgs {
    pub(crate) increment: DeltaIncrement,
    pub(crate) mode: Mode,
}

impl DeltaArgs {
    pub(crate) fn parse(state: &State, args: &[PyObj], kwargs: &mut IterKwargs) -> PyResult<Self> {
        let &State {
            str_nanosecond,
            str_microsecond,
            str_millisecond,
            str_second,
            str_minute,
            str_hour,
            str_day,
            str_week,
            str_mode,
            str_increment,
            round_mode_strs,
            str_assume_24h_days,
            time_delta_type,
            ..
        } = state;

        let opt_arg = handle_opt_arg("round", args)?;

        let mut mode = Mode::HalfEven;
        let mut increment_kwarg = None;
        let mut suppress_24h_warning = false;
        handle_kwargs("round", kwargs, |key, value, eq| {
            if eq(key, str_mode) {
                mode = Mode::from_py(value, round_mode_strs)?;
            } else if eq(key, str_increment) {
                let raw_increment = value
                    .cast_allow_subclass::<PyInt>()
                    .ok_or_value_err("increment must be an integer")?
                    .to_i128()?;
                if raw_increment <= 0 {
                    raise_value_err("increment must be a positive integer")?;
                }
                // SAFETY: we just checked that it's >0
                increment_kwarg = Some(unsafe { NonZeroU128::new_unchecked(raw_increment as _) });
            } else if eq(key, str_assume_24h_days) {
                suppress_24h_warning = value.is_truthy();
            } else {
                return Ok(false);
            }
            Ok(true)
        })?;
        let increment = match opt_arg {
            None => DeltaIncrement {
                secs: 1,
                subsec: SubSecNanos::MIN,
            },
            Some(arg) => {
                if let Some(delta) = arg.extract(time_delta_type) {
                    if increment_kwarg.is_some() {
                        raise_type_err("cannot specify an increment with a TimeDelta argument")?;
                    }
                    if delta.is_negative() || delta.is_zero() {
                        raise_value_err("rounding TimeDelta must be positive")?;
                    }
                    DeltaIncrement {
                        secs: delta.secs.get() as u64,
                        subsec: delta.subsec,
                    }
                } else {
                    let unit = Unit::from_py(
                        arg,
                        str_nanosecond,
                        str_microsecond,
                        str_millisecond,
                        str_second,
                        str_minute,
                        str_hour,
                        str_day,
                        str_week,
                        true,
                    )?;
                    if matches!(unit, Unit::Day | Unit::Week) && !suppress_24h_warning {
                        warn_with_class(
                            state.warn_days_not_always_24h,
                            doc::DAYS_NOT_ALWAYS_24H_MSG,
                            1,
                        )?;
                    }
                    DeltaIncrement::from_nanos(
                        increment_kwarg
                            .map_or(1, |v| v.get())
                            .checked_mul(unit.default_increment().into())
                            .ok_or_range_err()?,
                    )
                    .ok_or_range_err()?
                }
            }
        };

        Ok(DeltaArgs { increment, mode })
    }
}
