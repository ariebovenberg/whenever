use core::ffi::{c_int, c_void, CStr};
use pyo3_ffi::*;
use std::fmt;
use std::ops::Neg;
use std::ptr::null_mut as NULL;

use crate::common::math::*;
use crate::common::*;
use crate::date_delta::{DateDelta, InitError};
use crate::datetime_delta::{handle_exact_unit, DateTimeDelta};
use crate::docstrings as doc;
use crate::round;
use crate::State;

/// TimeDelta represents a duration of time with nanosecond precision.
///
/// The struct design is inspired by datetime.timedelta and chrono::timedelta
#[derive(Debug, Eq, PartialEq, Ord, PartialOrd, Copy, Clone)]
pub(crate) struct TimeDelta {
    // Invariant: a TD is always smaller than TimeDelta::MAX.
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
        // Note: we don't max the subsecs out, because then we couldn't convert min/max
        // into each other. This would be a no-go as you can't have a reliable negation
        // operation! I've tried this and it doesn't work out. Do not attempt.
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
            secs: DeltaSeconds::new_unchecked(nanos_i.div_euclid(1_000_000_000) as _),
            subsec: SubSecNanos::new_unchecked(nanos_i.rem_euclid(1_000_000_000) as _),
        })
    }

    // Future: can we prevent loss of prevision when converting to/from f64?
    pub(crate) fn to_nanos_f64(self) -> f64 {
        self.secs.get() as f64 * 1e9 + self.subsec.get() as f64
    }

    pub(crate) const fn from_nanos_unchecked(nanos: i128) -> Self {
        TimeDelta {
            secs: DeltaSeconds::new_unchecked(nanos.div_euclid(1_000_000_000) as _),
            subsec: SubSecNanos::new_unchecked(nanos.rem_euclid(1_000_000_000) as _),
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
        self.secs.get() as i128 * 1_000_000_000 + self.subsec.get() as i128
    }

    pub(crate) const fn is_zero(&self) -> bool {
        self.secs.get() == 0 && self.subsec.get() == 0
    }

    pub(crate) fn abs(self) -> Self {
        if self.secs.get() >= 0 {
            self
        } else {
            -self
        }
    }

    pub(crate) fn checked_mul(self, factor: i128) -> Option<Self> {
        self.total_nanos()
            .checked_mul(factor)
            .and_then(Self::from_nanos)
    }

    pub(crate) fn checked_add(self, other: Self) -> Option<Self> {
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

    pub(crate) fn round(self, increment: i64, mode: round::Mode) -> Option<Self> {
        debug_assert!(increment > 0);
        let TimeDelta { secs, subsec } = self;
        Some(if increment < 1_000_000_000 {
            let (extra_secs, subsec) = subsec.round(increment as _, mode);
            Self {
                // Safe: rounding sub-second part can never lead to range errors,
                // due to our choice of MIN/MAX timedelta
                secs: secs.add(extra_secs).unwrap(),
                subsec,
            }
        } else {
            // Safe: the sub-second part is zero, so we're safe
            // as long as we check the whole seconds.
            Self {
                secs: secs.round(subsec, increment, mode)?,
                subsec: SubSecNanos::MIN,
            }
        })
    }

    pub(crate) unsafe fn from_py_unsafe(delta: *mut PyObject) -> Self {
        Self {
            secs: DeltaSeconds::from_py_unchecked(delta).unwrap(),
            subsec: SubSecNanos::from_py_delta_unchecked(delta),
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
        let self_abs = if self.secs.get() < 0 {
            s.push('-');
            -self
        } else {
            self
        };
        s.push_str("PT");
        fmt_components_abs(self_abs, &mut s);
        s
    }
}

impl PyWrapped for TimeDelta {}

impl Neg for TimeDelta {
    type Output = Self;

    fn neg(self) -> TimeDelta {
        let (extra_seconds, subsec) = self.subsec.negate();
        // Safe: valid timedelta's can always be negated within range,
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
        // Safe: we know the string is ASCII
        let mut isofmt = self.fmt_iso().into_bytes();
        for c in isofmt.iter_mut().skip(3) {
            *c = c.to_ascii_lowercase();
        }
        f.write_str(unsafe { std::str::from_utf8_unchecked(&isofmt) })
    }
}

impl DeltaSeconds {
    fn round(self, subsec: SubSecNanos, increment_ns: i64, mode: round::Mode) -> Option<Self> {
        debug_assert!(increment_ns % 1_000_000_000 == 0);
        let increment_s = increment_ns / 1_000_000_000;
        let quotient = self.get().div_euclid(increment_s);
        let remainder_ns = self.get().rem_euclid(increment_s) * 1_000_000_000 + subsec.get() as i64;
        let threshold_ns = match mode {
            round::Mode::HalfEven => 1.max(increment_ns / 2 + (quotient % 2 == 0) as i64),
            round::Mode::HalfCeil => 1.max(increment_ns / 2),
            round::Mode::Ceil => 1,
            round::Mode::Floor => increment_ns + 1,
            round::Mode::HalfFloor => increment_ns / 2 + 1,
        };
        let round_up = remainder_ns >= threshold_ns;
        Self::new((quotient + i64::from(round_up)) * increment_s)
    }
}

#[allow(clippy::unnecessary_cast)]
pub(crate) const MAX_SECS: i64 = (Year::MAX.get() as i64) * 366 * 24 * 3600;
pub(crate) const MAX_HOURS: i64 = MAX_SECS / 3600;
pub(crate) const MAX_MINUTES: i64 = MAX_SECS / 60;
pub(crate) const MAX_MILLISECONDS: i64 = MAX_SECS * 1_000;
pub(crate) const MAX_MICROSECONDS: i64 = MAX_SECS * 1_000_000;

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

unsafe fn __new__(cls: *mut PyTypeObject, args: *mut PyObject, kwargs: *mut PyObject) -> PyReturn {
    let nargs = PyTuple_GET_SIZE(args);
    let nkwargs = if kwargs.is_null() {
        0
    } else {
        PyDict_Size(kwargs)
    };
    let mut nanos: i128 = 0;
    let &State {
        str_hours,
        str_minutes,
        str_seconds,
        str_milliseconds,
        str_microseconds,
        str_nanoseconds,
        ..
    } = State::for_type(cls);

    match (nargs, nkwargs) {
        (0, 0) => TimeDelta {
            secs: DeltaSeconds::ZERO,
            subsec: SubSecNanos::MIN,
        }, // FUTURE: return the singleton?
        (0, _) => {
            handle_kwargs(
                "TimeDelta",
                DictItems::new_unchecked(kwargs),
                |key, value, eq| {
                    if eq(key, str_hours) {
                        nanos +=
                            handle_exact_unit(value, MAX_HOURS, "hours", 3_600_000_000_000_i128)?;
                    } else if eq(key, str_minutes) {
                        nanos +=
                            handle_exact_unit(value, MAX_MINUTES, "minutes", 60_000_000_000_i128)?;
                    } else if eq(key, str_seconds) {
                        nanos += handle_exact_unit(value, MAX_SECS, "seconds", 1_000_000_000_i128)?;
                    } else if eq(key, str_milliseconds) {
                        nanos += handle_exact_unit(
                            value,
                            MAX_MILLISECONDS,
                            "milliseconds",
                            1_000_000_i128,
                        )?;
                    } else if eq(key, str_microseconds) {
                        nanos +=
                            handle_exact_unit(value, MAX_MICROSECONDS, "microseconds", 1_000_i128)?;
                    } else if eq(key, str_nanoseconds) {
                        nanos += value
                            .to_i128()?
                            .ok_or_value_err("nanoseconds must be an integer")?;
                    } else {
                        return Ok(false);
                    }
                    Ok(true)
                },
            )?;
            TimeDelta::from_nanos(nanos).ok_or_value_err("TimeDelta out of range")?
        }
        _ => raise_type_err("TimeDelta() takes no positional arguments")?,
    }
    .to_obj(cls)
}

pub(crate) unsafe fn hours(module: *mut PyObject, amount: *mut PyObject) -> PyReturn {
    TimeDelta::from_nanos_unchecked(handle_exact_unit(
        amount,
        MAX_HOURS,
        "hours",
        3_600_000_000_000_i128,
    )?)
    .to_obj(State::for_mod(module).time_delta_type)
}

pub(crate) unsafe fn minutes(module: *mut PyObject, amount: *mut PyObject) -> PyReturn {
    TimeDelta::from_nanos_unchecked(handle_exact_unit(
        amount,
        MAX_MINUTES,
        "minutes",
        60_000_000_000_i128,
    )?)
    .to_obj(State::for_mod(module).time_delta_type)
}

pub(crate) unsafe fn seconds(module: *mut PyObject, amount: *mut PyObject) -> PyReturn {
    TimeDelta::from_nanos_unchecked(handle_exact_unit(
        amount,
        MAX_SECS,
        "seconds",
        1_000_000_000_i128,
    )?)
    .to_obj(State::for_mod(module).time_delta_type)
}

pub(crate) unsafe fn milliseconds(module: *mut PyObject, amount: *mut PyObject) -> PyReturn {
    TimeDelta::from_nanos_unchecked(handle_exact_unit(
        amount,
        MAX_MILLISECONDS,
        "milliseconds",
        1_000_000_i128,
    )?)
    .to_obj(State::for_mod(module).time_delta_type)
}

pub(crate) unsafe fn microseconds(module: *mut PyObject, amount: *mut PyObject) -> PyReturn {
    TimeDelta::from_nanos_unchecked(handle_exact_unit(
        amount,
        MAX_MICROSECONDS,
        "microseconds",
        1_000_i128,
    )?)
    .to_obj(State::for_mod(module).time_delta_type)
}

pub(crate) unsafe fn nanoseconds(module: *mut PyObject, amount: *mut PyObject) -> PyReturn {
    TimeDelta::from_nanos(
        amount
            .to_i128()?
            .ok_or_value_err("nanoseconds must be an integer")?,
    )
    .ok_or_value_err("TimeDelta out of range")?
    .to_obj(State::for_mod(module).time_delta_type)
}

unsafe fn __richcmp__(obj_a: *mut PyObject, obj_b: *mut PyObject, op: c_int) -> PyReturn {
    if Py_TYPE(obj_b) == Py_TYPE(obj_a) {
        let a = TimeDelta::extract(obj_a);
        let b = TimeDelta::extract(obj_b);
        match op {
            pyo3_ffi::Py_EQ => a == b,
            pyo3_ffi::Py_NE => a != b,
            pyo3_ffi::Py_LT => a < b,
            pyo3_ffi::Py_LE => a <= b,
            pyo3_ffi::Py_GT => a > b,
            pyo3_ffi::Py_GE => a >= b,
            _ => unreachable!(),
        }
        .to_py()
    } else {
        Ok(newref(Py_NotImplemented()))
    }
}

unsafe extern "C" fn __hash__(slf: *mut PyObject) -> Py_hash_t {
    hashmask(TimeDelta::extract(slf).pyhash())
}

unsafe fn __neg__(slf: *mut PyObject) -> PyReturn {
    (-TimeDelta::extract(slf)).to_obj(Py_TYPE(slf))
}

unsafe extern "C" fn __bool__(slf: *mut PyObject) -> c_int {
    (!TimeDelta::extract(slf).is_zero()).into()
}

unsafe fn __repr__(slf: *mut PyObject) -> PyReturn {
    format!("TimeDelta({})", TimeDelta::extract(slf)).to_py()
}

unsafe fn __str__(slf: *mut PyObject) -> PyReturn {
    format_common_iso(slf, NULL())
}

unsafe fn __mul__(obj_a: *mut PyObject, obj_b: *mut PyObject) -> PyReturn {
    if obj_b.is_int() {
        _mul_int(obj_a, obj_b.to_i128()?.unwrap())
    } else if obj_b.is_float() {
        _mul_float(obj_a, obj_b.to_f64()?.unwrap())
    // important: this method can be called with the arguments reversed (__rmul__)
    } else if obj_a.is_int() {
        _mul_int(obj_b, obj_a.to_i128()?.unwrap())
    } else if obj_a.is_float() {
        _mul_float(obj_b, obj_a.to_f64()?.unwrap())
    } else {
        Ok(newref(Py_NotImplemented()))
    }
}

#[inline]
unsafe fn _mul_int(delta_obj: *mut PyObject, factor: i128) -> PyReturn {
    if factor == 1 {
        Ok(newref(delta_obj))
    } else {
        TimeDelta::extract(delta_obj)
            .total_nanos()
            .checked_mul(factor)
            .and_then(TimeDelta::from_nanos)
            .ok_or_value_err("Multiplication result out of range")?
            .to_obj(Py_TYPE(delta_obj))
    }
}

#[inline]
unsafe fn _mul_float(delta_obj: *mut PyObject, factor: f64) -> PyReturn {
    if factor == 1.0 {
        Ok(newref(delta_obj))
    } else {
        TimeDelta::from_nanos_f64(TimeDelta::extract(delta_obj).to_nanos_f64() * factor)
            .ok_or_value_err("Multiplication result out of range")?
            .to_obj(Py_TYPE(delta_obj))
    }
}

unsafe fn __truediv__(slf: *mut PyObject, factor_obj: *mut PyObject) -> PyReturn {
    if factor_obj.is_int() {
        let factor = factor_obj
            .to_i128()?
            // Safe: we already know it's an int here
            .unwrap();
        if factor == 1 {
            return Ok(newref(slf));
        } else if factor == 0 {
            raise(PyExc_ZeroDivisionError, "Division by zero")?
        }
        let nanos = TimeDelta::extract(slf).total_nanos();
        // Safe: division by integer is never bigger than the original value
        TimeDelta::from_nanos_unchecked(if nanos % factor == 0 {
            nanos / factor
        } else {
            (nanos as f64 / factor as f64).round() as i128
        })
    } else if factor_obj.is_float() {
        let factor = factor_obj
            .to_f64()?
            // safe to unwrap since we already know it's a float
            .unwrap();
        if factor == 1.0 {
            return Ok(newref(slf));
        } else if factor == 0.0 {
            raise(PyExc_ZeroDivisionError, "Division by zero")?
        }
        TimeDelta::from_nanos_f64(TimeDelta::extract(slf).to_nanos_f64() / factor)
            .ok_or_value_err("Division result out of range")?
    } else if Py_TYPE(factor_obj) == Py_TYPE(slf) {
        let factor = TimeDelta::extract(factor_obj).total_nanos();
        if factor == 0 {
            raise(PyExc_ZeroDivisionError, "Division by zero")?
        }
        return (TimeDelta::extract(slf).total_nanos() as f64 / factor as f64).to_py();
    } else {
        return Ok(newref(Py_NotImplemented()));
    }
    .to_obj(Py_TYPE(slf))
}

unsafe fn __floordiv__(a_obj: *mut PyObject, b_obj: *mut PyObject) -> PyReturn {
    if Py_TYPE(b_obj) == Py_TYPE(a_obj) {
        // NOTE: we can't avoid using i128 *in general*, because the divisor
        //       may be 1 nanosecond and the dividend TimeDelta.MAX
        let a = TimeDelta::extract(a_obj).total_nanos();
        let b = TimeDelta::extract(b_obj).total_nanos();
        if b == 0 {
            raise(PyExc_ZeroDivisionError, "Division by zero")?
        }
        let mut result = a / b;
        // Adjust for "correct" (Python style) floor division with mixed signs
        if a.signum() != b.signum() && a % b != 0 {
            result -= 1;
        }
        result.to_py()
    } else {
        Ok(newref(Py_NotImplemented()))
    }
}

unsafe fn __mod__(a_obj: *mut PyObject, b_obj: *mut PyObject) -> PyReturn {
    let type_a = Py_TYPE(a_obj);
    if type_a == Py_TYPE(b_obj) {
        let a = TimeDelta::extract(a_obj).total_nanos();
        let b = TimeDelta::extract(b_obj).total_nanos();
        if b == 0 {
            raise(PyExc_ZeroDivisionError, "Division by zero")?
        }
        let mut result = a % b;
        // Adjust for "correct" (Python style) floor division with mixed signs
        if a.signum() != b.signum() && result != 0 {
            result += b;
        }
        // Safe: remainder is always smaller than the divisor
        TimeDelta::from_nanos_unchecked(result).to_obj(type_a)
    } else {
        Ok(newref(Py_NotImplemented()))
    }
}

unsafe fn __add__(obj_a: *mut PyObject, obj_b: *mut PyObject) -> PyReturn {
    _add_operator(obj_a, obj_b, false)
}

unsafe fn __sub__(a_obj: *mut PyObject, b_obj: *mut PyObject) -> PyReturn {
    _add_operator(a_obj, b_obj, true)
}

#[inline]
unsafe fn _add_operator(obj_a: *mut PyObject, obj_b: *mut PyObject, negate: bool) -> PyReturn {
    let type_a = Py_TYPE(obj_a);
    let type_b = Py_TYPE(obj_b);
    // The easy case: both are TimeDelta
    if type_a == type_b {
        let a = TimeDelta::extract(obj_a);
        let mut b = TimeDelta::extract(obj_b);
        if negate {
            b = -b;
        }
        a.checked_add(b)
            .ok_or_value_err("Addition result out of range")?
            .to_obj(type_a)
    // Careful argument handling since the method may be called with args reversed
    } else {
        let mod_a = PyType_GetModule(type_a);
        let mod_b = PyType_GetModule(type_b);
        if mod_a == mod_b {
            let state = State::for_mod(mod_a);
            if type_b == state.date_delta_type {
                let mut b = DateDelta::extract(obj_b);
                if negate {
                    b = -b;
                }
                DateTimeDelta::new(b, TimeDelta::extract(obj_a))
                    .ok_or_value_err("Mixed sign of delta components")?
            } else if type_b == state.datetime_delta_type {
                let mut b = DateTimeDelta::extract(obj_b);
                if negate {
                    b = -b;
                }
                b.checked_add(DateTimeDelta {
                    ddelta: DateDelta::ZERO,
                    tdelta: TimeDelta::extract(obj_a),
                })
                .map_err(|e| {
                    value_err(match e {
                        InitError::TooBig => "Result out of range",
                        InitError::MixedSign => "Mixed sign of delta components",
                    })
                })?
            } else {
                raise_type_err(format!(
                    "unsupported operand type(s) for +/-: {} and {}",
                    (type_a as *mut PyObject).repr(),
                    (type_b as *mut PyObject).repr()
                ))?
            }
            .to_obj(state.datetime_delta_type)
        } else {
            Ok(newref(Py_NotImplemented()))
        }
    }
}

unsafe fn __abs__(slf: *mut PyObject) -> PyReturn {
    let delta = TimeDelta::extract(slf);
    if delta.secs.get() >= 0 {
        Ok(newref(slf))
    } else {
        (-delta).to_obj(Py_TYPE(slf))
    }
}

#[allow(static_mut_refs)]
static mut SLOTS: &[PyType_Slot] = &[
    slotmethod!(Py_tp_new, __new__),
    slotmethod!(Py_tp_richcompare, __richcmp__),
    slotmethod!(Py_nb_negative, __neg__, 1),
    slotmethod!(Py_tp_repr, __repr__, 1),
    slotmethod!(Py_tp_str, __str__, 1),
    slotmethod!(Py_nb_positive, identity1, 1),
    slotmethod!(Py_nb_multiply, __mul__, 2),
    slotmethod!(Py_nb_true_divide, __truediv__, 2),
    slotmethod!(Py_nb_add, __add__, 2),
    slotmethod!(Py_nb_subtract, __sub__, 2),
    slotmethod!(Py_nb_absolute, __abs__, 1),
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

unsafe fn __reduce__(slf: *mut PyObject, _: *mut PyObject) -> PyReturn {
    let TimeDelta { secs, subsec } = TimeDelta::extract(slf);
    let data = pack![secs.get(), subsec.get()];
    (
        State::for_obj(slf).unpickle_time_delta,
        steal!((steal!(data.to_py()?),).to_py()?),
    )
        .to_py()
}

pub(crate) unsafe fn unpickle(module: *mut PyObject, arg: *mut PyObject) -> PyReturn {
    let mut data = arg.to_bytes()?.ok_or_value_err("Invalid pickle data")?;
    if data.len() != 12 {
        raise_value_err("Invalid pickle data")?;
    }
    TimeDelta {
        secs: DeltaSeconds::new_unchecked(unpack_one!(data, i64)),
        subsec: SubSecNanos::new_unchecked(unpack_one!(data, i32)),
    }
    .to_obj(State::for_mod(module).time_delta_type)
}

unsafe fn in_nanoseconds(slf: *mut PyObject, _: *mut PyObject) -> PyReturn {
    TimeDelta::extract(slf).total_nanos().to_py()
}

unsafe fn in_microseconds(slf: *mut PyObject, _: *mut PyObject) -> PyReturn {
    let TimeDelta { secs, subsec } = TimeDelta::extract(slf);
    (secs.get() as f64 * 1e6 + subsec.get() as f64 * 1e-3).to_py()
}

unsafe fn in_milliseconds(slf: *mut PyObject, _: *mut PyObject) -> PyReturn {
    let TimeDelta { secs, subsec } = TimeDelta::extract(slf);
    (secs.get() as f64 * 1e3 + subsec.get() as f64 * 1e-6).to_py()
}

unsafe fn in_seconds(slf: *mut PyObject, _: *mut PyObject) -> PyReturn {
    let TimeDelta { secs, subsec } = TimeDelta::extract(slf);
    (secs.get() as f64 + subsec.get() as f64 * 1e-9).to_py()
}

unsafe fn in_minutes(slf: *mut PyObject, _: *mut PyObject) -> PyReturn {
    let TimeDelta { secs, subsec } = TimeDelta::extract(slf);
    (secs.get() as f64 / 60.0 + subsec.get() as f64 * 1e-9 / 60.0).to_py()
}

unsafe fn in_hours(slf: *mut PyObject, _: *mut PyObject) -> PyReturn {
    let TimeDelta { secs, subsec } = TimeDelta::extract(slf);
    (secs.get() as f64 / 3600.0 + subsec.get() as f64 * 1e-9 / 3600.0).to_py()
}

unsafe fn in_days_of_24h(slf: *mut PyObject, _: *mut PyObject) -> PyReturn {
    let TimeDelta { secs, subsec } = TimeDelta::extract(slf);
    (secs.get() as f64 / 86_400.0 + subsec.get() as f64 * 1e-9 / 86_400.0).to_py()
}

unsafe fn from_py_timedelta(cls: *mut PyObject, d: *mut PyObject) -> PyReturn {
    if PyDelta_CheckExact(d) == 0 {
        raise_type_err("Argument must be datetime.timedelta exactly")?;
    }
    TimeDelta {
        secs: DeltaSeconds::from_py_unchecked(d).ok_or_value_err("TimeDelta out of range")?,
        subsec: SubSecNanos::from_py_delta_unchecked(d),
    }
    .to_obj(cls.cast())
}

unsafe fn py_timedelta(slf: *mut PyObject, _: *mut PyObject) -> PyReturn {
    let TimeDelta { subsec, secs } = TimeDelta::extract(slf);
    let &PyDateTime_CAPI {
        Delta_FromDelta,
        DeltaType,
        ..
    } = State::for_obj(slf).py_api;
    Delta_FromDelta(
        secs.get().div_euclid(S_PER_DAY.into()) as _,
        secs.get().rem_euclid(S_PER_DAY.into()) as _,
        (subsec.get() / 1_000) as _,
        0,
        DeltaType,
    )
    .as_result()
}

fn parse_prefix(s: &mut &[u8]) -> Option<i128> {
    let sign = match s[0] {
        b'+' => {
            *s = &s[1..];
            1
        }
        b'-' => {
            *s = &s[1..];
            -1
        }
        _ => 1,
    };
    s[..2].eq_ignore_ascii_case(b"PT").then(|| {
        *s = &s[2..];
        sign
    })
}

unsafe fn in_hrs_mins_secs_nanos(slf: *mut PyObject, _: *mut PyObject) -> PyReturn {
    let TimeDelta { secs, subsec } = TimeDelta::extract(slf);
    let secs = secs.get();
    let (secs, nanos) = if secs >= 0 {
        (secs, subsec.get())
    } else if subsec.get() == 0 {
        (secs, 0)
    } else {
        (secs + 1, subsec.get() - 1_000_000_000)
    };
    (
        steal!((secs / 3_600).to_py()?),
        steal!((secs % 3_600 / 60).to_py()?),
        steal!((secs % 60).to_py()?),
        steal!(nanos.to_py()?),
    )
        .to_py()
}

#[inline]
pub(crate) fn fmt_components_abs(td: TimeDelta, s: &mut String) {
    let TimeDelta { secs, subsec } = td;
    debug_assert!(secs.get() >= 0);
    let (hours, mins, secs) = secs.abs_hms();
    if hours != 0 {
        s.push_str(&format!("{}H", hours));
    }
    if mins != 0 {
        s.push_str(&format!("{}M", mins));
    }
    if secs != 0 || subsec.get() != 0 {
        s.push_str(&format!("{}{}S", secs, subsec));
    }
}

unsafe fn format_common_iso(slf: *mut PyObject, _: *mut PyObject) -> PyReturn {
    TimeDelta::extract(slf).fmt_iso().to_py()
}

#[derive(Debug, PartialEq, Copy, Clone)]
enum Unit {
    Hours,
    Minutes,
    Nanoseconds,
}

// 001234 -> 1_234_000
fn parse_nano_fractions(s: &[u8]) -> Option<i128> {
    let mut tally = extract_digit(s, 0)? as i128 * 100_000_000;
    for i in 1..s.len().min(9) {
        match s[i] {
            c if c.is_ascii_digit() => {
                tally += i128::from(c - b'0') * i128::from(10_u32.pow(8 - i as u32))
            }
            // S is only valid at the very end
            b'S' | b's' if i + 1 == s.len() => {
                return Some(tally);
            }
            _ => return None,
        }
    }
    // at this point we've parsed 9 fractional digits successfully.
    // Only encountering `S` is valid. Nothing more, nothing less.
    match s[9..] {
        [b'S' | b's'] => Some(tally),
        _ => None,
    }
}

// parse a component of a ISO8601 duration, e.g. `6M`, `56.3S`, `0H`
fn parse_component(s: &mut &[u8]) -> Option<(i128, Unit)> {
    if s.len() < 2 {
        return None;
    }
    let mut tally: i128 = 0;
    // We limit parsing to 35 characters to prevent overflow of i128
    for i in 0..s.len().min(35) {
        match s[i] {
            c if c.is_ascii_digit() => tally = tally * 10 + i128::from(c - b'0'),
            b'H' | b'h' => {
                *s = &s[i + 1..];
                return Some((tally, Unit::Hours));
            }
            b'M' | b'm' => {
                *s = &s[i + 1..];
                return Some((tally, Unit::Minutes));
            }
            b'S' | b's' => {
                *s = &s[i + 1..];
                return Some((tally * 1_000_000_000, Unit::Nanoseconds));
            }
            b'.' | b',' if i > 0 => {
                let result = parse_nano_fractions(&s[i + 1..])
                    .map(|ns| (tally * 1_000_000_000 + ns, Unit::Nanoseconds));
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
pub(crate) unsafe fn parse_all_components(s: &mut &[u8]) -> Option<(i128, bool)> {
    let mut prev_unit: Option<Unit> = None;
    let mut nanos = 0;
    while !s.is_empty() {
        let (value, unit) = parse_component(s)?;
        match (unit, prev_unit.replace(unit)) {
            (Unit::Hours, None) => {
                nanos += value * 3_600_000_000_000;
            }
            (Unit::Minutes, None | Some(Unit::Hours)) => {
                nanos += value * 60_000_000_000;
            }
            (Unit::Nanoseconds, _) => {
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

unsafe fn parse_common_iso(cls: *mut PyObject, s_obj: *mut PyObject) -> PyReturn {
    let s = &mut s_obj
        .to_utf8()?
        .ok_or_type_err("argument must be a string")?;
    let err = || format!("Invalid format: {}", s_obj.repr());

    let sign = (s.len() >= 4)
        .then(|| parse_prefix(s))
        .flatten()
        .ok_or_else_value_err(err)?;

    let (nanos, is_empty) = parse_all_components(s).ok_or_else_value_err(err)?;

    // i.e. there must be at least one component (`PT` alone is invalid)
    if is_empty {
        raise_value_err(err())?;
    }
    TimeDelta::from_nanos(nanos * sign)
        .ok_or_value_err("Time delta out of range")?
        .to_obj(cls.cast())
}

unsafe fn round(
    slf: *mut PyObject,
    cls: *mut PyTypeObject,
    args: &[*mut PyObject],
    kwargs: &mut KwargIter,
) -> PyReturn {
    let (unit, increment, mode) =
        round::parse_args(State::for_obj(slf), args, kwargs, true, false)?;
    if unit == round::Unit::Day {
        raise_value_err(doc::CANNOT_ROUND_DAY_MSG)?;
    }
    TimeDelta::extract(slf)
        .round(increment, mode)
        .ok_or_value_err("Resulting TimeDelta out of range")?
        .to_obj(cls)
}

static mut METHODS: &[PyMethodDef] = &[
    method!(identity2 named "__copy__", c""),
    method!(identity2 named "__deepcopy__", c"", METH_O),
    method!(__reduce__, c""),
    method!(format_common_iso, doc::TIMEDELTA_FORMAT_COMMON_ISO),
    method!(
        parse_common_iso,
        doc::TIMEDELTA_PARSE_COMMON_ISO,
        METH_O | METH_CLASS
    ),
    method!(in_nanoseconds, doc::TIMEDELTA_IN_NANOSECONDS),
    method!(in_microseconds, doc::TIMEDELTA_IN_MICROSECONDS),
    method!(in_milliseconds, doc::TIMEDELTA_IN_MILLISECONDS),
    method!(in_seconds, doc::TIMEDELTA_IN_SECONDS),
    method!(in_minutes, doc::TIMEDELTA_IN_MINUTES),
    method!(in_hours, doc::TIMEDELTA_IN_HOURS),
    method!(in_days_of_24h, doc::TIMEDELTA_IN_DAYS_OF_24H),
    method!(
        from_py_timedelta,
        doc::TIMEDELTA_FROM_PY_TIMEDELTA,
        METH_O | METH_CLASS
    ),
    method!(py_timedelta, doc::TIMEDELTA_PY_TIMEDELTA),
    method!(
        in_hrs_mins_secs_nanos,
        doc::TIMEDELTA_IN_HRS_MINS_SECS_NANOS
    ),
    method_kwargs!(round, doc::TIMEDELTA_ROUND),
    PyMethodDef::zeroed(),
];

pub(crate) static mut SPEC: PyType_Spec =
    type_spec::<TimeDelta>(c"whenever.TimeDelta", unsafe { SLOTS });
