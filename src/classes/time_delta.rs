use core::ffi::{CStr, c_int, c_void};
use pyo3_ffi::*;
use std::{fmt, ops::Neg, ptr::null_mut as NULL};

use crate::{
    classes::{
        date_delta::{DateDelta, InitError},
        datetime_delta::{DateTimeDelta, handle_exact_unit},
        instant::Instant,
        itemized_delta::ItemizedDelta,
        offset_datetime::OffsetDateTime,
        plain_datetime::{DateTime, total_cal_plain},
        zoned_datetime::{ZonedDateTime, zoned_since_in_units, zoned_target},
    },
    common::{
        math::{self, AnyUnit, DateRoundIncrement, DeltaUnitSet, ExactUnit, ExactUnitSet},
        parse::extract_digit,
        round,
        scalar::*,
    },
    docstrings as doc,
    py::*,
    pymodule::State,
};

/// TimeDelta represents a duration of time with nanosecond precision.
///
/// The struct design is inspired by datetime.timedelta and chrono::timedelta
#[derive(Debug, Eq, PartialEq, Ord, PartialOrd, Copy, Clone)]
pub(crate) struct TimeDelta {
    // Invariant: a TD is always between TimeDelta::MIN and TimeDelta::MAX, inclusive
    pub(crate) secs: DeltaSeconds,
    pub(crate) subsec: SubSecNanos,
}

impl TimeDelta {
    pub(crate) const MIN: Self = Self {
        secs: DeltaSeconds::MIN,
        subsec: SubSecNanos::MIN,
    };
    pub(crate) const MAX: Self = Self {
        secs: DeltaSeconds::MAX,
        // NOTE: we don't max the subsecs out, because then we couldn't convert min/max
        // into each other. This would make negation fallible, which has far-reaching
        // consequences for many operations. Do not attempt.
        subsec: SubSecNanos::MIN,
    };

    pub(crate) fn from_nanos_f64(nanos_f: f64) -> Option<Self> {
        if nanos_f.is_nan()
            || !(DeltaNanos::MIN.get() as f64..=DeltaNanos::MAX.get() as f64).contains(&nanos_f)
        {
            return None;
        }
        // Safe since we've already checked the bounds
        let nanos_i = nanos_f as i128;
        Some(TimeDelta {
            secs: DeltaSeconds::new_unchecked(nanos_i.div_euclid(NS_PER_SEC as i128) as _),
            subsec: SubSecNanos::new_unchecked(nanos_i.rem_euclid(NS_PER_SEC as i128) as _),
        })
    }

    // Future: can we prevent loss of prevision when converting to/from f64?
    pub(crate) fn to_nanos_f64(self) -> f64 {
        self.secs.get() as f64 * 1e9 + self.subsec.get() as f64
    }

    pub(crate) const fn from_nanos_unchecked(nanos: i128) -> Self {
        TimeDelta {
            secs: DeltaSeconds::new_unchecked(nanos.div_euclid(NS_PER_SEC as i128) as _),
            subsec: SubSecNanos::new_unchecked(nanos.rem_euclid(NS_PER_SEC as i128) as _),
        }
    }

    pub(crate) fn from_nanos(nanos: i128) -> Option<Self> {
        let (secs, subsec) = DeltaNanos::new(nanos)?.sec_subsec();
        Some(Self { secs, subsec })
    }

    pub(crate) const fn from_offset(x: Offset) -> Self {
        TimeDelta {
            // Safe: offset range is well within DeltaSeconds range
            secs: DeltaSeconds::new_unchecked(x.get() as _),
            subsec: SubSecNanos::MIN,
        }
    }

    // FUTURE: see if we can avoid the i128
    pub(crate) const fn total_nanos(self) -> i128 {
        self.secs.get() as i128 * NS_PER_SEC as i128 + self.subsec.get() as i128
    }

    pub(crate) const fn is_zero(&self) -> bool {
        self.secs.get() == 0 && self.subsec.get() == 0
    }

    pub(crate) fn abs(self) -> Self {
        if self.secs.get() >= 0 { self } else { -self }
    }

    pub(crate) fn mul(self, factor: i128) -> Option<Self> {
        self.total_nanos()
            .checked_mul(factor)
            .and_then(Self::from_nanos)
    }

    pub(crate) fn add(self, other: Self) -> Option<Self> {
        let (extra_sec, subsec) = self.subsec.add(other.subsec);
        Some(Self {
            secs: self.secs.add(other.secs)?.add(extra_sec)?,
            subsec,
        })
    }

    pub(crate) const ZERO: Self = Self {
        secs: DeltaSeconds::ZERO,
        subsec: SubSecNanos::MIN,
    };

    /// Round to the nearest multiple of `increment`.
    pub(crate) fn round(self, increment: DeltaIncrement, abs_mode: round::AbsMode) -> Option<Self> {
        debug_assert!(
            increment.secs > 0 || increment.subsec.get() > 0,
            "increment must be nonzero"
        );
        if increment.secs == 0 && NS_PER_SEC.is_multiple_of(increment.subsec.as_u32()) {
            // Sub-second increment: use efficient integer arithmetic if it divides 1s
            let (extra_secs, subsec) = self.subsec.round(increment.subsec.as_u32(), abs_mode);
            Self {
                // SAFETY: rounding sub-second part can never lead to range errors,
                // due to our choice of MIN/MAX timedelta
                secs: self.secs.add(extra_secs).unwrap(),
                subsec,
            }
        } else {
            // Mixed increment: fall back to generic rounding
            self.round_u128(increment.total_nanos(), abs_mode)?
        }
        .into()
    }

    fn round_u128(self, inc: u128, abs_mode: round::AbsMode) -> Option<Self> {
        debug_assert!(inc > 0);
        // inc always fits in i128: DeltaIncrement is bounded by TimeDelta::MAX nanos < i128::MAX
        debug_assert!(inc <= i128::MAX as u128);
        let inc = inc as i128;
        let total_ns = self.secs.get() as i128 * NS_PER_SEC as i128 + self.subsec.get() as i128;
        let quotient = total_ns.div_euclid(inc);
        let remainder = total_ns.rem_euclid(inc);
        let threshold = match abs_mode {
            round::AbsMode::HalfEven => {
                1i128.max(inc / 2 + quotient.unsigned_abs().is_multiple_of(2) as i128)
            }
            round::AbsMode::Expand => 1,
            round::AbsMode::Trunc => inc + 1,
            round::AbsMode::HalfTrunc => inc / 2 + 1,
            round::AbsMode::HalfExpand => 1i128.max(inc / 2),
        };
        let result_ns = (quotient + i128::from(remainder >= threshold)) * inc;
        let result_secs = result_ns.div_euclid(NS_PER_SEC as i128) as i64;
        let result_subsec = result_ns.rem_euclid(NS_PER_SEC as i128) as i32;
        Some(Self {
            secs: DeltaSeconds::new(result_secs)?,
            subsec: SubSecNanos::new_unchecked(result_subsec),
        })
    }

    pub(crate) fn from_py_unchecked(delta: PyTimeDelta) -> Self {
        Self {
            secs: delta.whole_seconds().unwrap(),
            subsec: delta.subsec(),
        }
    }

    pub(crate) const fn pyhash(self) -> Py_hash_t {
        #[cfg(target_pointer_width = "64")]
        {
            hash_combine(self.subsec.get() as Py_hash_t, self.secs.get() as Py_hash_t)
        }
        #[cfg(target_pointer_width = "32")]
        {
            hash_combine(
                self.subsec.get() as Py_hash_t,
                hash_combine(
                    self.secs.get() as Py_hash_t,
                    (self.secs.get() >> 32) as Py_hash_t,
                ),
            )
        }
    }

    pub(crate) fn fmt_iso(self) -> String {
        if self.is_zero() {
            return "PT0S".to_string();
        }
        let mut s = String::with_capacity(8);
        let self_abs = if self.is_negative() {
            s.push('-');
            -self
        } else {
            self
        };
        s.push_str("PT");
        fmt_components_abs(self_abs, &mut s);
        s
    }

    pub(crate) fn from_py(d: PyTimeDelta) -> Option<Self> {
        Some(TimeDelta {
            secs: d.whole_seconds()?,
            subsec: d.subsec(),
        })
    }

    pub(crate) fn in_exact_units(
        self,
        units: ExactUnitSet,
        round_increment: math::RoundIncrement,
        round_mode: round::AbsMode,
    ) -> Option<ItemizedDelta> {
        debug_assert!(
            !units.contains(ExactUnit::Milliseconds) && !units.contains(ExactUnit::Microseconds)
        );
        let increment = (units.smallest().in_nanos() as u64 as u128)
            .checked_mul(round_increment.as_i128() as u128)
            .and_then(DeltaIncrement::from_nanos)?;
        let rounded = self.round(increment, round_mode)?;

        let mut remaining = rounded.total_nanos();
        let mut target = ItemizedDelta::UNSET;

        type Setter = fn(&mut ItemizedDelta, i128);

        let fields: &[(ExactUnit, Setter)] = &[
            (ExactUnit::Weeks, |t, v| {
                t.weeks = DeltaField::new_unchecked(v as i32)
            }),
            (ExactUnit::Days, |t, v| {
                t.days = DeltaField::new_unchecked(v as i32)
            }),
            (ExactUnit::Hours, |t, v| {
                t.hours = DeltaField::new_unchecked(v as i32)
            }),
            (ExactUnit::Minutes, |t, v| {
                t.minutes = DeltaField::new_unchecked(v as i64)
            }),
            (ExactUnit::Seconds, |t, v| {
                t.seconds = DeltaField::new_unchecked(v as i64)
            }),
        ];

        for &(unit, setter) in fields {
            if units.contains(unit) {
                let per = unit.in_nanos() as i128;
                let value = remaining / per;
                remaining %= per;
                setter(&mut target, value);
            }
        }

        if units.contains(ExactUnit::Nanoseconds) {
            target.nanos = DeltaField::new_unchecked(remaining as i32);
        }

        Some(target)
    }

    pub(crate) fn negate_if(self, condition: bool) -> Self {
        if condition { -self } else { self }
    }

    pub(crate) fn is_negative(self) -> bool {
        self.secs.get() < 0
    }
}

impl PySimpleAlloc for TimeDelta {}

impl Neg for TimeDelta {
    type Output = Self;

    fn neg(self) -> TimeDelta {
        let (extra_seconds, subsec) = self.subsec.negate();
        // SAFETY: valid timedelta's can always be negated within range,
        // due to our choice of MIN/MAX
        TimeDelta {
            secs: (-self.secs).add(extra_seconds).unwrap(),
            subsec,
        }
    }
}

impl std::fmt::Display for TimeDelta {
    fn fmt(&self, f: &mut fmt::Formatter<'_>) -> fmt::Result {
        // This is a bit wasteful, but we don't use it in performance critical
        // places.
        let mut isofmt = self.fmt_iso().into_bytes();
        for c in isofmt.iter_mut().skip(3) {
            *c = c.to_ascii_lowercase();
        }
        // SAFETY: we know it's just ASCII
        f.write_str(unsafe { std::str::from_utf8_unchecked(&isofmt) })
    }
}

/// A rounding increment wit similar structure to TimeDelta.
/// Always positive and nonzero: at least one of `secs` or `subsec` is nonzero.
#[derive(Debug, Copy, Clone, PartialEq, Eq)]
pub(crate) struct DeltaIncrement {
    pub(crate) secs: u64,
    pub(crate) subsec: SubSecNanos,
}

impl DeltaIncrement {
    /// Create from total nanoseconds. Returns `None` if zero or out of TimeDelta range.
    pub(crate) fn from_nanos(nanos: u128) -> Option<Self> {
        if nanos == 0 {
            return None;
        }
        Some(Self {
            secs: u64::try_from(nanos / NS_PER_SEC as u128).ok()?,
            subsec: SubSecNanos::from_remainder(nanos),
        })
    }

    pub(crate) fn total_nanos(self) -> u128 {
        self.secs as u128 * NS_PER_SEC as u128 + self.subsec.as_u32() as u128
    }
}

pub(crate) const MAX_SECS: u64 = (Year::MAX.get() as u64) * 366 * 24 * S_PER_HOUR as u64;
pub(crate) const MAX_HOURS: u64 = MAX_SECS / S_PER_HOUR as u64;
pub(crate) const MAX_MINUTES: u64 = MAX_SECS / 60;
pub(crate) const MAX_MILLISECONDS: u64 = MAX_SECS * 1_000;
pub(crate) const MAX_MICROSECONDS: u64 = MAX_SECS * 1_000_000;

pub(crate) const SINGLETONS: &[(&CStr, TimeDelta); 3] = &[
    (
        c"ZERO",
        TimeDelta {
            secs: DeltaSeconds::ZERO,
            subsec: SubSecNanos::MIN,
        },
    ),
    (c"MIN", TimeDelta::MIN),
    (c"MAX", TimeDelta::MAX),
];

#[inline]
#[allow(clippy::too_many_arguments)]
pub(crate) fn set_timedelta_from_kwargs(
    key: PyObj,
    value: PyObj,
    delta: &mut TimeDelta,
    state: &State,
    eq: fn(PyObj, PyObj) -> bool,
    str_weeks: PyObj,
    str_days: PyObj,
    str_hours: PyObj,
    str_minutes: PyObj,
    str_seconds: PyObj,
    str_milliseconds: PyObj,
    str_microseconds: PyObj,
    str_nanoseconds: PyObj,
) -> PyResult<bool> {
    if eq(key, str_weeks) {
        *delta = delta
            .add(ExactUnit::Weeks.parse_py_number(value)?)
            .ok_or_range_err()?;
        if !state.cv_ignore_days_not_always_24h.get()? {
            warn_with_class(
                state.warn_days_not_always_24h,
                doc::DAYS_NOT_ALWAYS_24H_MSG,
                1,
            )?;
        }
    } else if eq(key, str_days) {
        *delta = delta
            .add(ExactUnit::Days.parse_py_number(value)?)
            .ok_or_range_err()?;
        if !state.cv_ignore_days_not_always_24h.get()? {
            warn_with_class(
                state.warn_days_not_always_24h,
                doc::DAYS_NOT_ALWAYS_24H_MSG,
                1,
            )?;
        }
    } else if eq(key, str_hours) {
        *delta = delta
            .add(ExactUnit::Hours.parse_py_number(value)?)
            .ok_or_range_err()?;
    } else if eq(key, str_minutes) {
        *delta = delta
            .add(ExactUnit::Minutes.parse_py_number(value)?)
            .ok_or_range_err()?;
    } else if eq(key, str_seconds) {
        *delta = delta
            .add(ExactUnit::Seconds.parse_py_number(value)?)
            .ok_or_range_err()?;
    } else if eq(key, str_milliseconds) {
        *delta = delta
            .add(ExactUnit::Milliseconds.parse_py_number(value)?)
            .ok_or_range_err()?;
    } else if eq(key, str_microseconds) {
        *delta = delta
            .add(ExactUnit::Microseconds.parse_py_number(value)?)
            .ok_or_range_err()?;
    } else if eq(key, str_nanoseconds) {
        *delta = delta
            .add(ExactUnit::Nanoseconds.parse_py_number(value)?)
            .ok_or_range_err()?;
    } else {
        return Ok(false);
    }
    Ok(true)
}

fn timedelta_from_kwargs<K>(fname: &'static str, kwargs: K, state: &State) -> PyResult<TimeDelta>
where
    K: IntoIterator<Item = (PyObj, PyObj)>,
{
    let mut result = TimeDelta::ZERO;

    let &State {
        str_weeks,
        str_days,
        str_hours,
        str_minutes,
        str_seconds,
        str_milliseconds,
        str_microseconds,
        str_nanoseconds,
        ..
    } = state;

    handle_kwargs(fname, kwargs, |key, value, eq| {
        set_timedelta_from_kwargs(
            key,
            value,
            &mut result,
            state,
            eq,
            str_weeks,
            str_days,
            str_hours,
            str_minutes,
            str_seconds,
            str_milliseconds,
            str_microseconds,
            str_nanoseconds,
        )
    })?;

    Ok(result)
}

fn __new__(cls: HeapType<TimeDelta>, args: PyTuple, kwargs: Option<PyDict>) -> PyReturn {
    let nkwargs = kwargs.map_or(0, |k| k.len());
    let state = cls.state();

    match (args.len(), nkwargs) {
        (1, 0) => {
            let arg = args.iter().next().unwrap();
            // NOTE: this needs to be a bit roundabout to ensure
            // we have a clear error message for timedelta subclasses.
            if arg.cast_allow_subclass::<PyTimeDelta>().is_some() {
                let d = arg
                    .cast_exact::<PyTimeDelta>()
                    .ok_or_type_err("argument must be datetime.timedelta exactly")?;
                TimeDelta::from_py(d).ok_or_range_err()?.to_obj(cls)
            } else {
                parse_iso(cls, arg)
            }
        }
        (0, 0) => TimeDelta::ZERO.to_obj(cls),
        (0, _) => {
            timedelta_from_kwargs("TimeDelta", kwargs.unwrap().iteritems(), state)?.to_obj(cls)
        }
        _ => raise_type_err("TimeDelta() takes no positional arguments"),
    }
}

pub(crate) fn hours(state: &State, arg: PyObj) -> PyReturn {
    TimeDelta::from_nanos_unchecked(handle_exact_unit(
        arg,
        MAX_HOURS,
        "hours",
        NS_PER_HOUR as i128,
    )?)
    .to_obj(state.time_delta_type)
}

pub(crate) fn minutes(state: &State, arg: PyObj) -> PyReturn {
    TimeDelta::from_nanos_unchecked(handle_exact_unit(
        arg,
        MAX_MINUTES,
        "minutes",
        NS_PER_MINUTE as i128,
    )?)
    .to_obj(state.time_delta_type)
}

pub(crate) fn seconds(state: &State, arg: PyObj) -> PyReturn {
    TimeDelta::from_nanos_unchecked(handle_exact_unit(
        arg,
        MAX_SECS,
        "seconds",
        1_000_000_000_i128,
    )?)
    .to_obj(state.time_delta_type)
}

pub(crate) fn milliseconds(state: &State, arg: PyObj) -> PyReturn {
    TimeDelta::from_nanos_unchecked(handle_exact_unit(
        arg,
        MAX_MILLISECONDS,
        "milliseconds",
        1_000_000_i128,
    )?)
    .to_obj(state.time_delta_type)
}

pub(crate) fn microseconds(state: &State, arg: PyObj) -> PyReturn {
    TimeDelta::from_nanos_unchecked(handle_exact_unit(
        arg,
        MAX_MICROSECONDS,
        "microseconds",
        1_000_i128,
    )?)
    .to_obj(state.time_delta_type)
}

pub(crate) fn nanoseconds(state: &State, arg: PyObj) -> PyReturn {
    TimeDelta::from_nanos(
        arg.cast_allow_subclass::<PyInt>()
            .ok_or_value_err("nanoseconds must be an integer")?
            .to_i128()?,
    )
    .ok_or_range_err()?
    .to_obj(state.time_delta_type)
}

fn __richcmp__(cls: HeapType<TimeDelta>, a: TimeDelta, arg: PyObj, op: c_int) -> PyReturn {
    match arg.extract(cls) {
        Some(b) => match op {
            pyo3_ffi::Py_EQ => a == b,
            pyo3_ffi::Py_NE => a != b,
            pyo3_ffi::Py_LT => a < b,
            pyo3_ffi::Py_LE => a <= b,
            pyo3_ffi::Py_GT => a > b,
            pyo3_ffi::Py_GE => a >= b,
            _ => unreachable!(),
        }
        .to_py(),
        None => not_implemented(),
    }
}

extern "C" fn __hash__(slf: PyObj) -> Py_hash_t {
    // SAFETY: we know self is passed to this method
    hashmask(unsafe { slf.assume_heaptype::<TimeDelta>().1 }.pyhash()) as Py_hash_t
}

fn __neg__(cls: HeapType<TimeDelta>, slf: TimeDelta) -> PyReturn {
    (-slf).to_obj(cls)
}

extern "C" fn __bool__(slf: PyObj) -> c_int {
    // SAFETY: self argument is always the self type
    (!unsafe { slf.assume_heaptype::<TimeDelta>() }.1.is_zero()).into()
}

fn __repr__(_: PyType, slf: TimeDelta) -> PyReturn {
    format!("TimeDelta(\"{slf}\")").to_py()
}

fn __str__(cls: PyType, slf: TimeDelta) -> PyReturn {
    format_iso(cls, slf)
}

fn __mul__(obj_a: PyObj, obj_b: PyObj) -> PyReturn {
    if let Some(py_int) = obj_b.cast_allow_subclass::<PyInt>() {
        mul_int(obj_a, py_int.to_i128()?)
    } else if let Some(py_int) = obj_a.cast_allow_subclass::<PyInt>() {
        mul_int(obj_b, py_int.to_i128()?)
    } else if let Some(py_float) = obj_b.cast_allow_subclass::<PyFloat>() {
        mul_float(obj_a, py_float.to_f64()?)
    } else if let Some(py_float) = obj_a.cast_allow_subclass::<PyFloat>() {
        mul_float(obj_b, py_float.to_f64()?)
    } else {
        not_implemented()
    }
}

#[inline]
fn mul_int(delta_obj: PyObj, factor: i128) -> PyReturn {
    if factor == 1 {
        Ok(delta_obj.newref())
    } else {
        // SAFETY: one of the arguments is always the self type (the other is int)
        let (cls, delta) = unsafe { delta_obj.assume_heaptype::<TimeDelta>() };
        delta
            .total_nanos()
            .checked_mul(factor)
            .and_then(TimeDelta::from_nanos)
            .ok_or_range_err()?
            .to_obj(cls)
    }
}

#[inline]
fn mul_float(delta_obj: PyObj, factor: f64) -> PyReturn {
    if factor == 1.0 {
        Ok(delta_obj.newref())
    } else {
        // SAFETY: one of the arguments is always the self type (the other is float)
        let (cls, delta) = unsafe { delta_obj.assume_heaptype::<TimeDelta>() };
        TimeDelta::from_nanos_f64(delta.to_nanos_f64() * factor)
            .ok_or_range_err()?
            .to_obj(cls)
    }
}

fn __truediv__(a_obj: PyObj, b_obj: PyObj) -> PyReturn {
    if let Some(py_int) = b_obj.cast_allow_subclass::<PyInt>() {
        let factor = py_int.to_i128()?;
        // SAFETY: one of the arguments is always the self type (the other is int)
        let (cls, delta) = unsafe { a_obj.assume_heaptype::<TimeDelta>() };
        if factor == 1 {
            // This special case saves us an allocation
            return Ok(a_obj.newref());
        } else if factor == 0 {
            raise(unsafe { PyExc_ZeroDivisionError }, "Division by zero")?
        }
        let nanos = delta.total_nanos();
        // SAFETY: division by integer is never bigger than the original value
        TimeDelta::from_nanos_unchecked(
            // NOTE: we try integer division if possible, to avoid precision loss
            if nanos % factor == 0 {
                nanos / factor
            } else {
                (nanos as f64 / factor as f64).round() as i128
            },
        )
        .to_obj(cls)
    } else if let Some(py_float) = b_obj.cast_allow_subclass::<PyFloat>() {
        // SAFETY: one of the arguments is always the self type (the other is float)
        let (cls, delta) = unsafe { a_obj.assume_heaptype::<TimeDelta>() };
        let factor = py_float.to_f64()?;
        if factor == 1.0 {
            // This special case saves us an allocation
            return Ok(a_obj.newref());
        } else if factor == 0.0 {
            raise(unsafe { PyExc_ZeroDivisionError }, "Division by zero")?
        }
        TimeDelta::from_nanos_f64(delta.to_nanos_f64() / factor)
            .ok_or_range_err()?
            .to_obj(cls)
    } else if a_obj.type_() == b_obj.type_() {
        // SAFETY: one of the arguments is always the self type, so both are
        let (_, a) = unsafe { a_obj.assume_heaptype::<TimeDelta>() };
        let (_, b) = unsafe { b_obj.assume_heaptype::<TimeDelta>() };
        if b.is_zero() {
            raise(unsafe { PyExc_ZeroDivisionError }, "Division by zero")?
        }
        (a.total_nanos() as f64 / b.total_nanos() as f64).to_py()
    } else {
        not_implemented()
    }
}

fn __floordiv__(a_obj: PyObj, b_obj: PyObj) -> PyReturn {
    if a_obj.type_() == b_obj.type_() {
        // SAFETY: one of the arguments is always the self type, so both are
        let (_, a_delta) = unsafe { a_obj.assume_heaptype::<TimeDelta>() };
        let (_, b_delta) = unsafe { b_obj.assume_heaptype::<TimeDelta>() };
        if b_delta.is_zero() {
            raise(unsafe { PyExc_ZeroDivisionError }, "Division by zero")?
        }
        // NOTE: we can't avoid using i128 *in general*, because the divisor
        //       may be 1 nanosecond and the dividend TimeDelta.MAX
        let a = a_delta.total_nanos();
        let b = b_delta.total_nanos();
        let mut result = a / b;
        // Adjust for "correct" (Python style) floor division with mixed signs
        if a.signum() != b.signum() && a % b != 0 {
            result -= 1;
        }
        result.to_py()
    } else {
        not_implemented()
    }
}

fn __mod__(a_obj: PyObj, b_obj: PyObj) -> PyReturn {
    if a_obj.type_() == b_obj.type_() {
        // SAFETY: one of the arguments is always the self type, so both are
        let (cls, a_delta) = unsafe { a_obj.assume_heaptype::<TimeDelta>() };
        let (_, b_delta) = unsafe { b_obj.assume_heaptype::<TimeDelta>() };

        let a = a_delta.total_nanos();
        let b = b_delta.total_nanos();
        if b == 0 {
            raise(unsafe { PyExc_ZeroDivisionError }, "Division by zero")?
        }
        let mut result = a % b;
        // Adjust for "correct" (Python style) floor division with mixed signs
        if a.signum() != b.signum() && result != 0 {
            result += b;
        }
        // SAFETY: remainder is always smaller than the divisor
        TimeDelta::from_nanos_unchecked(result).to_obj(cls)
    } else {
        not_implemented()
    }
}

fn __add__(a_obj: PyObj, b_obj: PyObj) -> PyReturn {
    add_operator(a_obj, b_obj, false)
}

fn __sub__(a_obj: PyObj, b_obj: PyObj) -> PyReturn {
    add_operator(a_obj, b_obj, true)
}

#[inline]
fn add_operator(a_obj: PyObj, b_obj: PyObj, negate: bool) -> PyReturn {
    let a_cls = a_obj.type_();
    let b_cls = b_obj.type_();

    // The easy case: both are TimeDelta
    if a_cls == b_cls {
        // SAFETY: one of the arguments is always the self type, so both are
        let (cls, a) = unsafe { a_obj.assume_heaptype::<TimeDelta>() };
        let (_, b) = unsafe { b_obj.assume_heaptype::<TimeDelta>() };

        a.add(b.negate_if(negate)).ok_or_range_err()?.to_obj(cls)
    } else if let Some(state) = a_cls.same_module(b_cls) {
        // SAFETY: the way we've structured binary operations within whenever
        // ensures that the first operand is the self type.
        let (_, tdelta) = unsafe { a_obj.assume_heaptype::<TimeDelta>() };

        if let Some(mut ddelta) = b_obj.extract(state.date_delta_type) {
            if negate {
                ddelta = -ddelta;
            }
            warn_with_class(
                state.warn_deprecation,
                c"DateTimeDelta is deprecated; use ItemizedDelta instead.",
                1,
            )?;
            DateTimeDelta::new(ddelta, tdelta)
                .ok_or_value_err("mixed sign of delta components")?
                .to_obj(state.datetime_delta_type)
        } else if let Some(mut dtdelta) = b_obj.extract(state.datetime_delta_type) {
            if negate {
                dtdelta = -dtdelta;
            }
            dtdelta
                .add(DateTimeDelta {
                    ddelta: DateDelta::ZERO,
                    tdelta,
                })
                .map_err(|e| {
                    value_err(match e {
                        InitError::TooBig => "Result out of range",
                        InitError::MixedSign => "mixed sign of delta components",
                    })
                })?
                .to_obj(state.datetime_delta_type)
        } else {
            raise_type_err(format!(
                "unsupported operand type(s) for +/-: {a_cls} and {b_cls}"
            ))?
        }
    } else {
        not_implemented()
    }
}

fn __abs__(cls: HeapType<TimeDelta>, slf: PyObj) -> PyReturn {
    // SAFETY: we know slf is passed to this method
    let (_, a) = unsafe { slf.assume_heaptype::<TimeDelta>() };
    if a.is_negative() {
        (-a).to_obj(cls)
    } else {
        Ok(slf.newref())
    }
}

#[allow(static_mut_refs)]
static mut SLOTS: &[PyType_Slot] = &[
    slotmethod!(TimeDelta, Py_tp_new, __new__),
    slotmethod!(TimeDelta, Py_tp_richcompare, __richcmp__),
    slotmethod!(TimeDelta, Py_nb_negative, __neg__, 1),
    slotmethod!(TimeDelta, Py_tp_repr, __repr__, 1),
    slotmethod!(TimeDelta, Py_tp_str, __str__, 1),
    slotmethod!(TimeDelta, Py_nb_positive, identity1, 1),
    slotmethod!(Py_nb_multiply, __mul__, 2),
    slotmethod!(Py_nb_true_divide, __truediv__, 2),
    slotmethod!(Py_nb_add, __add__, 2),
    slotmethod!(Py_nb_subtract, __sub__, 2),
    slotmethod!(TimeDelta, Py_nb_absolute, __abs__, 1),
    slotmethod!(Py_nb_floor_divide, __floordiv__, 2),
    slotmethod!(Py_nb_remainder, __mod__, 2),
    PyType_Slot {
        slot: Py_tp_doc,
        pfunc: doc::TIMEDELTA.as_ptr() as *mut c_void,
    },
    PyType_Slot {
        slot: Py_tp_methods,
        pfunc: unsafe { METHODS.as_ptr() as *mut c_void },
    },
    PyType_Slot {
        slot: Py_tp_hash,
        pfunc: __hash__ as *mut c_void,
    },
    PyType_Slot {
        slot: Py_nb_bool,
        pfunc: __bool__ as *mut c_void,
    },
    PyType_Slot {
        slot: Py_tp_dealloc,
        pfunc: generic_dealloc as *mut c_void,
    },
    PyType_Slot {
        slot: 0,
        pfunc: NULL(),
    },
];

fn __reduce__(cls: HeapType<TimeDelta>, slf: TimeDelta) -> PyResult<Owned<PyTuple>> {
    let TimeDelta { secs, subsec } = slf;
    let data = pack![secs.get(), subsec.get()];
    (
        cls.state().unpickle_time_delta.newref(),
        (data.to_py()?,).into_pytuple()?,
    )
        .into_pytuple()
}

pub(crate) fn unpickle(state: &State, arg: PyObj) -> PyReturn {
    let py_bytes = arg
        .cast_exact::<PyBytes>()
        .ok_or_type_err("invalid pickle data")?;
    let mut data = py_bytes.as_bytes()?;
    if data.len() != 12 {
        raise_value_err("invalid pickle data")?;
    }
    TimeDelta {
        secs: DeltaSeconds::new_unchecked(unpack_one!(data, i64)),
        subsec: SubSecNanos::new_unchecked(unpack_one!(data, i32)),
    }
    .to_obj(state.time_delta_type)
}

fn in_nanoseconds(cls: HeapType<TimeDelta>, slf: TimeDelta) -> PyReturn {
    warn_with_class(
        cls.state().warn_deprecation,
        c"in_nanoseconds is deprecated, use total('nanoseconds') instead",
        1,
    )?;
    slf.total_nanos().to_py()
}

fn in_microseconds(cls: HeapType<TimeDelta>, slf: TimeDelta) -> PyReturn {
    warn_with_class(
        cls.state().warn_deprecation,
        c"in_microseconds is deprecated, use total('microseconds') instead",
        1,
    )?;
    let TimeDelta { secs, subsec } = slf;
    (secs.get() as f64 * 1e6 + subsec.get() as f64 * 1e-3).to_py()
}

fn in_milliseconds(cls: HeapType<TimeDelta>, slf: TimeDelta) -> PyReturn {
    warn_with_class(
        cls.state().warn_deprecation,
        c"in_milliseconds is deprecated, use total('milliseconds') instead",
        1,
    )?;
    let TimeDelta { secs, subsec } = slf;
    (secs.get() as f64 * 1e3 + subsec.get() as f64 * 1e-6).to_py()
}

fn in_seconds(cls: HeapType<TimeDelta>, slf: TimeDelta) -> PyReturn {
    warn_with_class(
        cls.state().warn_deprecation,
        c"in_seconds is deprecated, use total('seconds') instead",
        1,
    )?;
    let TimeDelta { secs, subsec } = slf;
    (secs.get() as f64 + subsec.get() as f64 * 1e-9).to_py()
}

fn in_minutes(cls: HeapType<TimeDelta>, slf: TimeDelta) -> PyReturn {
    warn_with_class(
        cls.state().warn_deprecation,
        c"in_minutes is deprecated, use total('minutes') instead",
        1,
    )?;
    let TimeDelta { secs, subsec } = slf;
    (secs.get() as f64 / 60.0 + subsec.get() as f64 * 1e-9 / 60.0).to_py()
}

fn in_hours(cls: HeapType<TimeDelta>, slf: TimeDelta) -> PyReturn {
    warn_with_class(
        cls.state().warn_deprecation,
        c"in_hours is deprecated, use total('hours') instead",
        1,
    )?;
    let TimeDelta { secs, subsec } = slf;
    (secs.get() as f64 / 3600.0 + subsec.get() as f64 * 1e-9 / 3600.0).to_py()
}

fn in_days_of_24h(cls: HeapType<TimeDelta>, slf: TimeDelta) -> PyReturn {
    warn_with_class(
        cls.state().warn_deprecation,
        c"in_days_of_24h is deprecated, use total('days') instead",
        1,
    )?;
    let TimeDelta { secs, subsec } = slf;
    (secs.get() as f64 / S_PER_DAY as f64 + subsec.get() as f64 * 1e-9 / S_PER_DAY as f64).to_py()
}

fn from_py_timedelta(cls: HeapType<TimeDelta>, arg: PyObj) -> PyReturn {
    let &State {
        warn_deprecation, ..
    } = cls.state();
    warn_with_class(
        warn_deprecation,
        c"from_py_timedelta() is deprecated. Use TimeDelta() constructor instead.",
        1,
    )?;
    if let Some(d) = arg.cast_exact::<PyTimeDelta>() {
        TimeDelta::from_py(d).ok_or_range_err()?.to_obj(cls)
    } else {
        raise_type_err("argument must be datetime.timedelta exactly")
    }
}

fn to_stdlib(cls: HeapType<TimeDelta>, slf: TimeDelta) -> PyReturn {
    let TimeDelta { subsec, secs } = slf;
    let &PyDateTime_CAPI {
        Delta_FromDelta,
        DeltaType,
        ..
    } = cls.state().py_api;
    // SAFETY: calling C API with valid arguments
    unsafe {
        Delta_FromDelta(
            secs.get().div_euclid(S_PER_DAY.into()) as _,
            secs.get().rem_euclid(S_PER_DAY.into()) as _,
            (subsec.get() / NS_PER_MICROSEC as i32) as _,
            0,
            DeltaType,
        )
    }
    .rust_owned()
}

fn py_timedelta(cls: HeapType<TimeDelta>, slf: TimeDelta) -> PyReturn {
    let &State {
        warn_deprecation, ..
    } = cls.state();
    warn_with_class(
        warn_deprecation,
        c"py_timedelta() is deprecated. Use to_stdlib() instead.",
        1,
    )?;
    to_stdlib(cls, slf)
}

fn in_hrs_mins_secs_nanos(_: PyType, slf: TimeDelta) -> PyResult<Owned<PyTuple>> {
    let TimeDelta { secs, subsec } = slf;
    let secs = secs.get();
    let (secs, nanos) = if secs >= 0 {
        (secs, subsec.get())
    } else if subsec.get() == 0 {
        (secs, 0)
    } else {
        (secs + 1, subsec.get() - NS_PER_SEC as i32)
    };
    (
        (secs / S_PER_HOUR as i64).to_py()?,
        (secs % S_PER_HOUR as i64 / 60).to_py()?,
        (secs % 60).to_py()?,
        nanos.to_py()?,
    )
        .into_pytuple()
}

fn format_iso(_: PyType, slf: TimeDelta) -> PyReturn {
    slf.fmt_iso().to_py()
}

fn parse_iso(cls: HeapType<TimeDelta>, arg: PyObj) -> PyReturn {
    let py_str = arg
        .cast_allow_subclass::<PyStr>()
        // NOTE: this exception message also needs to make sense when
        // called through the constructor
        .ok_or_type_err("when parsing from ISO format, the argument must be str")?;
    let s = &mut py_str.as_utf8()?;
    let err = || format!("Invalid format: {arg}");

    let negate = (s.len() >= 4)
        .then(|| parse_prefix(s))
        .flatten()
        .ok_or_else_value_err(err)?;

    let (nanos, is_empty) = parse_all_components(s).ok_or_else_value_err(err)?;

    // i.e. there must be at least one component (`PT` alone is invalid)
    if is_empty {
        raise_value_err(err())?;
    }
    TimeDelta::from_nanos(nanos as i128)
        .ok_or_range_err()?
        .negate_if(negate)
        .to_obj(cls)
}

#[inline]
pub(crate) fn fmt_components_abs(td: TimeDelta, s: &mut String) {
    let TimeDelta { secs, subsec } = td;
    debug_assert!(secs.get() >= 0);
    let (hours, mins, secs) = secs.abs_hms();
    if hours != 0 {
        s.push_str(&format!("{hours}H"));
    }
    if mins != 0 {
        s.push_str(&format!("{mins}M"));
    }
    if secs != 0 || subsec.get() != 0 {
        s.push_str(&format!("{secs}{subsec}S"));
    }
}

fn parse_prefix(s: &mut &[u8]) -> Option<bool> {
    let neg = match s[0] {
        b'+' => {
            *s = &s[1..];
            false
        }
        b'-' => {
            *s = &s[1..];
            true
        }
        _ => false,
    };
    s[..2].eq_ignore_ascii_case(b"PT").then(|| {
        *s = &s[2..];
        neg
    })
}

#[derive(Debug, Copy, Clone, PartialEq, Eq, PartialOrd, Ord)]
pub(crate) enum TimeUnit {
    Hours,
    Minutes,
    /// Value is in nanoseconds. `has_fraction` distinguishes `5S` from `5.0S`.
    Nanos {
        has_fraction: bool,
    },
}

// 001234 -> 1_234_000
fn parse_nano_fractions(s: &[u8]) -> Option<u32> {
    if s.is_empty() {
        return None;
    }
    let mut tally = extract_digit(s, 0)? as u32 * 100_000_000;
    for i in 1..s.len().min(9) {
        match s[i] {
            c if c.is_ascii_digit() => tally += u32::from(c - b'0') * 10_u32.pow(8 - i as u32),
            // S is only valid at the very end
            b'S' | b's' if i + 1 == s.len() => {
                return Some(tally);
            }
            _ => return None,
        }
    }

    // We only end up here if we didn't encounter a `S` or `s` in the first 9 places
    (s.len() == 10 && s[9].eq_ignore_ascii_case(&b's')).then_some(tally)
}

/// parse a component of a ISO8601 duration, e.g. `6M`, `56.3S`, `0H`
pub(crate) fn parse_time_component(s: &mut &[u8]) -> Option<(u128, TimeUnit)> {
    if s.len() < 2 {
        return None;
    }
    let mut tally: u128 = 0;
    // We limit parsing to 35 characters to prevent overflow of 128 bits
    for i in 0..s.len().min(35) {
        match s[i] {
            c if c.is_ascii_digit() => tally = tally * 10 + u128::from(c - b'0'),
            b'H' | b'h' => {
                *s = &s[i + 1..];
                return Some((tally, TimeUnit::Hours));
            }
            b'M' | b'm' => {
                *s = &s[i + 1..];
                return Some((tally, TimeUnit::Minutes));
            }
            b'S' | b's' => {
                *s = &s[i + 1..];
                return Some((
                    tally * NS_PER_SEC as u128,
                    TimeUnit::Nanos {
                        has_fraction: false,
                    },
                ));
            }
            b'.' | b',' if i > 0 => {
                let result = parse_nano_fractions(&s[i + 1..]).map(|ns| {
                    (
                        tally * NS_PER_SEC as u128 + ns as u128,
                        TimeUnit::Nanos { has_fraction: true },
                    )
                });
                *s = &[];
                return result;
            }
            _ => break,
        }
    }
    None
}

// Parse all time components of an ISO8601 duration into total nanoseconds
// also whether it is empty (to distinguish no components from zero components)
pub(crate) fn parse_all_components(s: &mut &[u8]) -> Option<(u128, bool)> {
    let mut prev_unit: Option<TimeUnit> = None;
    let mut nanos = 0;
    while !s.is_empty() {
        let (value, unit) = parse_time_component(s)?;
        match (unit, prev_unit.replace(unit)) {
            (TimeUnit::Hours, None) => {
                nanos += value * NS_PER_HOUR as u128;
            }
            (TimeUnit::Minutes, None | Some(TimeUnit::Hours)) => {
                nanos += value * NS_PER_MINUTE as u128;
            }
            (TimeUnit::Nanos { .. }, _) => {
                nanos += value;
                if s.is_empty() {
                    break;
                } else {
                    // i.e. there's still something left after the nanoseconds
                    return None;
                }
            }
            // i.e. the order of the components is wrong
            _ => return None,
        }
    }
    Some((nanos, prev_unit.is_none()))
}

fn round(
    cls: HeapType<TimeDelta>,
    slf: TimeDelta,
    args: &[PyObj],
    kwargs: &mut IterKwargs,
) -> PyReturn {
    let round::DeltaArgs { increment, mode } = round::DeltaArgs::parse(cls.state(), args, kwargs)?;
    slf.round(increment, mode.to_abs_euclid(slf.is_negative()))
        .ok_or_range_err()?
        .to_obj(cls)
}

fn add(
    cls: HeapType<TimeDelta>,
    slf: TimeDelta,
    args: &[PyObj],
    kwargs: &mut IterKwargs,
) -> PyReturn {
    add_method(cls, slf, args, kwargs, false)
}

fn subtract(
    cls: HeapType<TimeDelta>,
    slf: TimeDelta,
    args: &[PyObj],
    kwargs: &mut IterKwargs,
) -> PyReturn {
    add_method(cls, slf, args, kwargs, true)
}

fn add_method(
    cls: HeapType<TimeDelta>,
    slf: TimeDelta,
    args: &[PyObj],
    kwargs: &mut IterKwargs,
    negate: bool,
) -> PyReturn {
    let other = match (args.first(), kwargs.len()) {
        (Some(_), n) if n > 0 => raise_type_err("cannot mix positional and keyword arguments")?,
        (Some(arg), _) => arg.extract(cls).ok_or_type_err(if negate {
            "subtract() argument must be a whenever.TimeDelta"
        } else {
            "add() argument must be a whenever.TimeDelta"
        })?,
        (None, 0) => return slf.to_obj(cls),
        (None, _) => {
            timedelta_from_kwargs(if negate { "subtract" } else { "add" }, kwargs, cls.state())?
        }
    }
    .negate_if(negate);
    slf.add(other).ok_or_range_err()?.to_obj(cls)
}

fn in_units(
    cls: HeapType<TimeDelta>,
    slf: TimeDelta,
    args: &[PyObj],
    kwargs: &mut IterKwargs,
) -> PyReturn {
    let state = cls.state();

    let units = DeltaUnitSet::from_py(handle_one_arg("in_units", args)?, state)?;

    // Parse optional round kwargs
    let &State {
        str_round_mode,
        str_round_increment,
        round_mode_strs,
        str_relative_to,
        ..
    } = state;

    let mut round_mode = round::Mode::Trunc;
    let mut round_increment = math::RoundIncrement::MIN;
    let mut relative_to = None;

    handle_kwargs("in_units", kwargs, |key, value, eq| {
        if eq(key, str_round_mode) {
            round_mode = round::Mode::from_py_named("rounding mode", value, round_mode_strs)?;
        } else if eq(key, str_round_increment) {
            round_increment = math::RoundIncrement::from_py(value)?;
        } else if eq(key, str_relative_to) {
            relative_to = value
                .extract(state.zoned_datetime_type)
                .ok_or_type_err("relative_to must be a whenever.ZonedDateTime")?
                .into();
        } else {
            return Ok(false);
        }
        Ok(true)
    })?;
    let neg = slf.is_negative();

    if let Some(zdt) = relative_to {
        let shifted_inst = zdt.instant().shift(slf).ok_or_range_err()?;
        let shifted = shifted_inst.to_tz(zdt.tz).ok_or_range_err()?;
        zoned_since_in_units(
            shifted,
            shifted_inst,
            zdt,
            zoned_target(shifted.date, shifted_inst, zdt, neg).ok_or_range_err()?,
            units,
            round_mode,
            round_increment,
            neg,
        )
        .ok_or_range_err()?
        .to_obj(state.itemized_delta_type)
    } else {
        if units.has_days_or_weeks() && !state.cv_ignore_days_not_always_24h.get()? {
            warn_with_class(
                state.warn_days_not_always_24h,
                doc::DAYS_NOT_ALWAYS_24H_MSG,
                1,
            )?;
        }
        if let Some(exact) = units.to_exact_assuming_24h_days() {
            slf.in_exact_units(exact, round_increment, round_mode.to_abs_euclid(neg))
                .ok_or_range_err()?
                .to_obj(state.itemized_delta_type)
        } else {
            raise_type_err("years and months units require a `relative_to` argument")
        }
    }
}

fn total(
    cls: HeapType<TimeDelta>,
    slf: TimeDelta,
    args: &[PyObj],
    kwargs: &mut IterKwargs,
) -> PyReturn {
    let state = cls.state();
    let unit = AnyUnit::from_py(handle_one_arg("total", args)?, state)?;
    let relative_to_arg = handle_one_kwarg("total", state.str_relative_to, kwargs)?;

    let cal_unit = match unit.to_exact(relative_to_arg.is_none()) {
        Ok(ExactUnit::Nanoseconds) => {
            // Special case for nanoseconds: always return an int
            return slf.total_nanos().to_py();
        }
        Ok(u) => {
            if (u == ExactUnit::Weeks || u == ExactUnit::Days)
                && !state.cv_ignore_days_not_always_24h.get()?
            {
                warn_with_class(
                    state.warn_days_not_always_24h,
                    doc::DAYS_NOT_ALWAYS_24H_MSG,
                    1,
                )?;
            }
            return (slf.to_nanos_f64() / u.in_nanos() as f64).to_py();
        }
        // FUTURE: fast early exit for zero
        Err(cal_unit) => cal_unit,
    };

    let arg = relative_to_arg
        .ok_or_type_err("for calendar units, a `relative_to` argument must be passed")?;

    // ZonedDateTime: full DST-aware path via zoned_target.
    if let Some(zdt) = arg.extract(state.zoned_datetime_type) {
        let shifted_inst = zdt.instant().shift(slf).ok_or_range_err()?;
        let shifted = shifted_inst.to_tz(zdt.tz).ok_or_range_err()?;
        return total_cal(slf.is_negative(), cal_unit, zdt, shifted, shifted_inst);
    }

    // PlainDateTime/OffsetDateTime: treat local time as UTC for the calendar
    // diff, emitting appropriate warnings. Same approach as Python's
    // `assume_tz("UTC")` trick (to_tz("UTC") would be wrong: it re-interprets
    // the instant in UTC rather than keeping the local date as the anchor).
    let b_dt: DateTime = if let Some(pdt) = arg.extract(state.plain_datetime_type) {
        if !state.cv_ignore_tz_unaware_arithmetic.get()? {
            warn_with_class(
                state.warn_tz_unaware_arithmetic,
                doc::PLAIN_DIFF_UNAWARE_MSG,
                1,
            )?;
        }
        pdt
    } else if let Some(odt) = arg.extract(state.offset_datetime_type) {
        if !state.cv_ignore_potentially_stale_offset.get()? {
            warn_with_class(
                state.warn_potentially_stale_offset,
                doc::STALE_OFFSET_CALENDAR_MSG,
                1,
            )?;
        }
        odt.without_offset()
    } else {
        raise_type_err("relative_to must be a ZonedDateTime, PlainDateTime, or OffsetDateTime")?
    };

    let neg = slf.is_negative();
    let a_inst = b_dt.assume_utc().shift(slf).ok_or_range_err()?;
    let a_dt = a_inst
        .to_offset(Offset::ZERO)
        .ok_or_range_err()?
        .without_offset();
    let target_date = match (neg, b_dt.with_date(a_dt.date).cmp(&a_dt)) {
        (false, std::cmp::Ordering::Greater) => a_dt.date.yesterday(),
        (true, std::cmp::Ordering::Less) => a_dt.date.tomorrow(),
        _ => Some(a_dt.date),
    }
    .ok_or_range_err()?;
    total_cal_plain(neg, cal_unit, a_inst, b_dt, target_date)
}

pub(crate) fn total_cal(
    neg: bool,
    unit: math::CalUnit,
    relative_to: ZonedDateTime,
    shifted: OffsetDateTime,
    shifted_inst: Instant,
) -> PyReturn {
    let target_date =
        zoned_target(shifted.date, shifted_inst, relative_to, neg).ok_or_range_err()?;

    let (trunc_amount, trunc_date, expand_date) = math::date_diff_single_unit(
        target_date,
        relative_to.date,
        DateRoundIncrement::MIN,
        unit,
        neg,
    )
    .ok_or_range_err()?;

    let trunc_odt = relative_to.with_date(trunc_date.into()).ok_or_range_err()?;
    let expand_odt = relative_to
        .with_date(expand_date.into())
        .ok_or_range_err()?;

    let r = shifted_inst.diff(trunc_odt.instant()).abs();
    let e = expand_odt.instant().diff(trunc_odt.instant());

    (trunc_amount as f64 + r.to_nanos_f64() / e.to_nanos_f64()).to_py()
}

static mut METHODS: &[PyMethodDef] = &[
    method0!(TimeDelta, __copy__, c""),
    method1!(TimeDelta, __deepcopy__, c""),
    method0!(TimeDelta, __reduce__, c""),
    method0!(TimeDelta, format_iso, doc::TIMEDELTA_FORMAT_ISO),
    classmethod1!(TimeDelta, parse_iso, doc::TIMEDELTA_PARSE_ISO),
    method0!(TimeDelta, in_nanoseconds, doc::TIMEDELTA_IN_NANOSECONDS),
    method0!(TimeDelta, in_microseconds, doc::TIMEDELTA_IN_MICROSECONDS),
    method0!(TimeDelta, in_milliseconds, doc::TIMEDELTA_IN_MILLISECONDS),
    method0!(TimeDelta, in_seconds, doc::TIMEDELTA_IN_SECONDS),
    method0!(TimeDelta, in_minutes, doc::TIMEDELTA_IN_MINUTES),
    method0!(TimeDelta, in_hours, doc::TIMEDELTA_IN_HOURS),
    method0!(TimeDelta, in_days_of_24h, doc::TIMEDELTA_IN_DAYS_OF_24H),
    classmethod1!(
        TimeDelta,
        from_py_timedelta,
        doc::TIMEDELTA_FROM_PY_TIMEDELTA
    ),
    method0!(TimeDelta, to_stdlib, doc::TIMEDELTA_TO_STDLIB),
    method0!(TimeDelta, py_timedelta, doc::TIMEDELTA_PY_TIMEDELTA),
    method0!(
        TimeDelta,
        in_hrs_mins_secs_nanos,
        doc::TIMEDELTA_IN_HRS_MINS_SECS_NANOS
    ),
    method_kwargs!(TimeDelta, round, doc::TIMEDELTA_ROUND),
    method_kwargs!(TimeDelta, add, doc::TIMEDELTA_ADD),
    method_kwargs!(TimeDelta, subtract, doc::TIMEDELTA_SUBTRACT),
    method_kwargs!(TimeDelta, in_units, doc::TIMEDELTA_IN_UNITS),
    method_kwargs!(TimeDelta, total, doc::TIMEDELTA_TOTAL),
    classmethod_kwargs!(
        TimeDelta,
        __get_pydantic_core_schema__,
        doc::PYDANTIC_SCHEMA
    ),
    PyMethodDef::zeroed(),
];

pub(crate) static mut SPEC: PyType_Spec =
    type_spec::<TimeDelta>(c"whenever.TimeDelta", unsafe { SLOTS });

#[cfg(test)]
mod tests {
    use super::*;

    fn td(secs: i64, nanos: i32) -> TimeDelta {
        TimeDelta {
            secs: DeltaSeconds::new(secs).unwrap(),
            subsec: SubSecNanos::new_unchecked(nanos),
        }
    }

    fn td_secs(s: i64) -> TimeDelta {
        td(s, 0)
    }

    fn inc(secs: u64, nanos: i32) -> DeltaIncrement {
        DeltaIncrement {
            secs,
            subsec: SubSecNanos::new_unchecked(nanos),
        }
    }

    fn sec() -> DeltaIncrement {
        inc(1, 0)
    }

    fn ten_sec() -> DeltaIncrement {
        inc(10, 0)
    }

    fn abs(mode: round::Mode, negative: bool) -> round::AbsMode {
        mode.to_abs_euclid(negative)
    }

    // --- Sub-second rounding (increment < 1s) ---

    #[test]
    fn round_subsec_floor() {
        // 1.7s → floor to 1s
        assert_eq!(
            td(1, 700_000_000).round(sec(), abs(round::Mode::Floor, false)),
            Some(td_secs(1))
        );
    }

    #[test]
    fn round_subsec_ceil() {
        // 1.7s → ceil to 2s
        assert_eq!(
            td(1, 700_000_000).round(sec(), abs(round::Mode::Ceil, false)),
            Some(td_secs(2))
        );
    }

    #[test]
    fn round_subsec_trunc_positive() {
        // 1.7s → trunc (towards 0) = 1s
        assert_eq!(
            td(1, 700_000_000).round(sec(), abs(round::Mode::Trunc, false)),
            Some(td_secs(1))
        );
    }

    #[test]
    fn round_subsec_trunc_negative() {
        // -1.3s (secs=-2, subsec=700_000_000) → trunc (towards 0) = -1s
        assert_eq!(
            td(-2, 700_000_000).round(sec(), abs(round::Mode::Trunc, true)),
            Some(td_secs(-1))
        );
    }

    #[test]
    fn round_subsec_expand_positive() {
        // 1.7s → expand (away from 0) = 2s
        assert_eq!(
            td(1, 700_000_000).round(sec(), abs(round::Mode::Expand, false)),
            Some(td_secs(2))
        );
    }

    #[test]
    fn round_subsec_expand_negative() {
        // -1.3s → expand (away from 0) = -2s
        assert_eq!(
            td(-2, 700_000_000).round(sec(), abs(round::Mode::Expand, true)),
            Some(td_secs(-2))
        );
    }

    // --- Half-way tie-breaking with sub-second ---

    #[test]
    fn round_subsec_half_even_tie() {
        // 1.5s → half_even: quotient=1 (odd), round up to 2
        assert_eq!(
            td(1, 500_000_000).round(sec(), abs(round::Mode::HalfEven, false)),
            Some(td_secs(2))
        );
        // 2.5s → half_even: quotient=2 (even), round down to 2
        assert_eq!(
            td(2, 500_000_000).round(sec(), abs(round::Mode::HalfEven, false)),
            Some(td_secs(2))
        );
    }

    #[test]
    fn round_subsec_half_ceil_tie() {
        // 1.5s → half_ceil: round up (towards +∞) = 2s
        assert_eq!(
            td(1, 500_000_000).round(sec(), abs(round::Mode::HalfCeil, false)),
            Some(td_secs(2))
        );
        // -1.5s (secs=-2, subsec=500_000_000) → half_ceil: round up (towards +∞) = -1s
        assert_eq!(
            td(-2, 500_000_000).round(sec(), abs(round::Mode::HalfCeil, true)),
            Some(td_secs(-1))
        );
    }

    #[test]
    fn round_subsec_half_floor_tie() {
        // 1.5s → half_floor: round down = 1s
        assert_eq!(
            td(1, 500_000_000).round(sec(), abs(round::Mode::HalfFloor, false)),
            Some(td_secs(1))
        );
        // -1.5s → half_floor: round down (towards -∞) = -2s
        assert_eq!(
            td(-2, 500_000_000).round(sec(), abs(round::Mode::HalfFloor, true)),
            Some(td_secs(-2))
        );
    }

    #[test]
    fn round_subsec_half_trunc_tie() {
        // 1.5s → half_trunc: ties towards 0 = 1s
        assert_eq!(
            td(1, 500_000_000).round(sec(), abs(round::Mode::HalfTrunc, false)),
            Some(td_secs(1))
        );
        // -1.5s → half_trunc: ties towards 0 = -1s
        assert_eq!(
            td(-2, 500_000_000).round(sec(), abs(round::Mode::HalfTrunc, true)),
            Some(td_secs(-1))
        );
    }

    #[test]
    fn round_subsec_half_expand_tie() {
        // 1.5s → half_expand: ties away from 0 = 2s
        assert_eq!(
            td(1, 500_000_000).round(sec(), abs(round::Mode::HalfExpand, false)),
            Some(td_secs(2))
        );
        // -1.5s → half_expand: ties away from 0 = -2s
        assert_eq!(
            td(-2, 500_000_000).round(sec(), abs(round::Mode::HalfExpand, true)),
            Some(td_secs(-2))
        );
    }

    // --- Whole-second rounding (increment >= 1s) ---

    #[test]
    fn round_wholesec_trunc_positive() {
        // 45s → trunc to 10s = 40s
        assert_eq!(
            td_secs(45).round(ten_sec(), abs(round::Mode::Trunc, false)),
            Some(td_secs(40))
        );
    }

    #[test]
    fn round_wholesec_trunc_negative() {
        // -45s → trunc to 10s = -40s (towards zero)
        assert_eq!(
            td_secs(-45).round(ten_sec(), abs(round::Mode::Trunc, true)),
            Some(td_secs(-40))
        );
    }

    #[test]
    fn round_wholesec_expand_positive() {
        // 41s → expand to 10s = 50s
        assert_eq!(
            td_secs(41).round(ten_sec(), abs(round::Mode::Expand, false)),
            Some(td_secs(50))
        );
    }

    #[test]
    fn round_wholesec_expand_negative() {
        // -41s → expand to 10s = -50s (away from zero)
        assert_eq!(
            td_secs(-41).round(ten_sec(), abs(round::Mode::Expand, true)),
            Some(td_secs(-50))
        );
    }

    #[test]
    fn round_wholesec_half_trunc_tie() {
        // 45s → half_trunc to 10s = 40s (tie towards zero)
        assert_eq!(
            td_secs(45).round(ten_sec(), abs(round::Mode::HalfTrunc, false)),
            Some(td_secs(40))
        );
        // -45s → half_trunc to 10s = -40s
        assert_eq!(
            td_secs(-45).round(ten_sec(), abs(round::Mode::HalfTrunc, true)),
            Some(td_secs(-40))
        );
    }

    #[test]
    fn round_wholesec_half_expand_tie() {
        // 45s → half_expand to 10s = 50s (tie away from zero)
        assert_eq!(
            td_secs(45).round(ten_sec(), abs(round::Mode::HalfExpand, false)),
            Some(td_secs(50))
        );
        // -45s → half_expand to 10s = -50s
        assert_eq!(
            td_secs(-45).round(ten_sec(), abs(round::Mode::HalfExpand, true)),
            Some(td_secs(-50))
        );
    }

    #[test]
    fn round_zero() {
        // Zero should remain zero for all modes
        for mode in [
            round::Mode::Floor,
            round::Mode::Ceil,
            round::Mode::Trunc,
            round::Mode::Expand,
            round::Mode::HalfEven,
            round::Mode::HalfCeil,
            round::Mode::HalfFloor,
            round::Mode::HalfTrunc,
            round::Mode::HalfExpand,
        ] {
            assert_eq!(
                td_secs(0).round(sec(), mode.to_abs_euclid(false)),
                Some(td_secs(0))
            );
        }
    }

    #[test]
    fn round_exact_value() {
        // Already at increment boundary → unchanged for all modes
        for mode in [
            round::Mode::Floor,
            round::Mode::Ceil,
            round::Mode::Trunc,
            round::Mode::Expand,
            round::Mode::HalfEven,
            round::Mode::HalfCeil,
            round::Mode::HalfFloor,
            round::Mode::HalfTrunc,
            round::Mode::HalfExpand,
        ] {
            assert_eq!(
                td_secs(30).round(ten_sec(), mode.to_abs_euclid(false)),
                Some(td_secs(30))
            );
            assert_eq!(
                td_secs(-30).round(ten_sec(), mode.to_abs_euclid(true)),
                Some(td_secs(-30))
            );
        }
    }

    #[test]
    fn round_large_increment() {
        // increment = 1<<65 ns (> i64::MAX), trunc mode
        let large_inc = inc(36_893_488_147, 419_103_232);
        // A value smaller than the increment should round to zero
        assert_eq!(
            td_secs(3600).round(large_inc, abs(round::Mode::Trunc, false)),
            Some(td_secs(0))
        );
        // A value exactly equal to the increment should be unchanged
        assert_eq!(
            td(36_893_488_147, 419_103_232).round(large_inc, abs(round::Mode::Trunc, false)),
            Some(td(36_893_488_147, 419_103_232))
        );
    }
}
