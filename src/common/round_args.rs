//! Python argument parsing for rounding operations.
use std::num::{NonZero, NonZeroU64, NonZeroU128};

use crate::{
    docstrings as doc,
    domain::scalar::{
        NS_PER_DAY, NS_PER_HOUR, NS_PER_MICROSEC, NS_PER_MILLISEC, NS_PER_MINUTE, NS_PER_SEC,
        NS_PER_WEEK, SubSecNanos,
    },
    domain::time_delta::DeltaIncrement,
    py::*,
    pymodule::{InternedStrings, State},
};

pub(crate) use crate::domain::round::Mode;

impl Mode {
    pub(crate) fn from_py(s: PyObj, strs: &InternedStrings) -> PyResult<Mode> {
        Self::from_py_named("mode", s, strs)
    }

    pub(crate) fn from_py_named(name: &str, s: PyObj, strs: &InternedStrings) -> PyResult<Mode> {
        match_interned_str(
            name,
            s,
            &[
                (*strs.floor, Mode::Floor),
                (*strs.ceil, Mode::Ceil),
                (*strs.trunc, Mode::Trunc),
                (*strs.expand, Mode::Expand),
                (*strs.half_floor, Mode::HalfFloor),
                (*strs.half_ceil, Mode::HalfCeil),
                (*strs.half_even, Mode::HalfEven),
                (*strs.half_trunc, Mode::HalfTrunc),
                (*strs.half_expand, Mode::HalfExpand),
            ],
        )
    }
}

#[derive(Debug, Copy, Clone, Ord, PartialOrd, Eq, PartialEq)]
pub(crate) enum RoundUnit {
    Nanosecond,
    Microsecond,
    Millisecond,
    Second,
    Minute,
    Hour,
    Day,
    Week,
}

impl RoundUnit {
    fn from_py(s: PyObj, state: &State, for_delta: bool) -> PyResult<RoundUnit> {
        // OPTIMIZE: run the comparisons in order if likelihood
        match_interned_str_with("unit", s, |v, eq| {
            find_interned_by(
                v,
                &[
                    (*state.strs.nanosecond, RoundUnit::Nanosecond),
                    (*state.strs.microsecond, RoundUnit::Microsecond),
                    (*state.strs.millisecond, RoundUnit::Millisecond),
                    (*state.strs.second, RoundUnit::Second),
                    (*state.strs.minute, RoundUnit::Minute),
                    (*state.strs.hour, RoundUnit::Hour),
                    (*state.strs.day, RoundUnit::Day),
                ],
                eq,
            )
            .or_else(|| (for_delta && eq(v, *state.strs.week)).then_some(RoundUnit::Week))
        })
    }

    pub(crate) const fn default_increment(self) -> u64 {
        match self {
            RoundUnit::Nanosecond => 1,
            RoundUnit::Microsecond => NS_PER_MICROSEC as _,
            RoundUnit::Millisecond => NS_PER_MILLISEC as _,
            RoundUnit::Second => NS_PER_SEC as _,
            RoundUnit::Minute => NS_PER_MINUTE,
            RoundUnit::Hour => NS_PER_HOUR,
            RoundUnit::Day => NS_PER_DAY,
            RoundUnit::Week => NS_PER_WEEK,
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
    pub(crate) suppress_stale: bool,
}

static INCREMENT_DIV_MSG: &str =
    "Invalid increment. Must be positive and divide a 24-hour day evenly.";

#[derive(Debug, Copy, Clone, Eq, PartialEq)]
pub(crate) enum ArgsContext {
    Standard,
    Offset,
}

impl Args {
    pub(crate) fn parse(
        args: &[PyObj],
        kwargs: &mut IterKwargs,
        state: &State,
        context: ArgsContext,
    ) -> PyResult<Self> {
        let opt_arg = handle_opt_arg("round", args)?;

        let mut mode = Mode::HalfEven;
        let mut suppress_stale = false;
        let mut increment_kwarg = None;
        handle_kwargs("round", kwargs, |key, value, eq| {
            if eq(key, *state.strs.mode) {
                mode = Mode::from_py(value, &state.strs)?;
            } else if eq(key, *state.strs.increment) {
                let raw_increment = value
                    .cast_allow_subclass::<PyInt>()
                    .ok_or_value_err("increment must be an integer")?
                    .to_i64()?;
                if raw_increment <= 0 {
                    raise_value_err("increment must be a positive integer")?;
                }
                // SAFETY: we just checked that it's >0
                increment_kwarg = Some(unsafe { NonZeroU64::new_unchecked(raw_increment as _) });
            } else if context == ArgsContext::Offset && eq(key, *state.strs.stale_offset_ok) {
                suppress_stale = value.is_truthy()?;
            } else {
                return Ok(false);
            }
            Ok(true)
        })?;

        let increment = match opt_arg {
            None => RoundIncrement::Exact(unsafe { NonZeroU64::new_unchecked(1_000_000_000) }),
            Some(arg) => {
                if let Some(delta) = arg.extract(*state.time_delta_type) {
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
                    let unit = RoundUnit::from_py(arg, state, false)?;
                    let increment_int = increment_kwarg.unwrap_or(NonZeroU64::MIN);
                    debug_assert!(unit != RoundUnit::Week);
                    if unit == RoundUnit::Day {
                        if increment_int.get() != 1 {
                            raise_value_err(INCREMENT_DIV_MSG)?;
                        }
                        RoundIncrement::Day
                    } else {
                        let nanos = unit
                            .default_increment()
                            .checked_mul(increment_int.get())
                            .and_then(NonZeroU64::new)
                            .filter(|n| NS_PER_DAY.is_multiple_of(n.get()))
                            .ok_or_value_err(INCREMENT_DIV_MSG)?;
                        RoundIncrement::Exact(nanos)
                    }
                }
            }
        };

        Ok(Args {
            increment,
            mode,
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
    pub(crate) fn parse(args: &[PyObj], kwargs: &mut IterKwargs, state: &State) -> PyResult<Self> {
        let opt_arg = handle_opt_arg("round", args)?;
        let mut mode = Mode::HalfEven;
        let mut increment_kwarg = None;
        let mut suppress_24h_warning = false;
        handle_kwargs("round", kwargs, |key, value, eq| {
            if eq(key, *state.strs.mode) {
                mode = Mode::from_py(value, &state.strs)?;
            } else if eq(key, *state.strs.increment) {
                let raw_increment = value
                    .cast_allow_subclass::<PyInt>()
                    .ok_or_value_err("increment must be an integer")?
                    .to_i128()?;
                if raw_increment <= 0 {
                    raise_value_err("increment must be a positive integer")?;
                }
                // SAFETY: we just checked that it's >0
                increment_kwarg = Some(unsafe { NonZeroU128::new_unchecked(raw_increment as _) });
            } else if eq(key, *state.strs.days_assumed_24h_ok) {
                suppress_24h_warning = value.is_truthy()?;
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
                if let Some(delta) = arg.extract(*state.time_delta_type) {
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
                    let unit = RoundUnit::from_py(arg, state, true)?;
                    if matches!(unit, RoundUnit::Day | RoundUnit::Week) && !suppress_24h_warning {
                        warn_with_class(
                            *state.warn_days_not_always_24h,
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
