use core::ffi::{c_int, c_void, CStr};
use core::mem;
use pyo3_ffi::*;
use std::cmp::min;
use std::fmt;
use std::ops::Neg;
use std::ptr::null_mut as NULL;

use crate::common::*;
use crate::date::MAX_YEAR;
use crate::date_delta::{DateDelta, InitError};
use crate::datetime_delta::{handle_exact_unit, DateTimeDelta};
use crate::State;

#[derive(Debug, Eq, PartialEq, Ord, PartialOrd, Copy, Clone)]
pub(crate) struct TimeDelta {
    // struct design inspired by datetime.timedelta and chrono::TimeDelta
    pub(crate) secs: i64,  // div_euclid(total_nanos) - may be negative
    pub(crate) nanos: u32, // rem_euclid(total_nanos) - never negative
}

impl TimeDelta {
    pub(crate) const fn from_nanos_unchecked(nanos: i128) -> Self {
        TimeDelta {
            secs: (nanos.div_euclid(1_000_000_000)) as _,
            nanos: (nanos.rem_euclid(1_000_000_000)) as _,
        }
    }

    pub(crate) const fn from_nanos(nanos: i128) -> Option<Self> {
        if nanos < -MAX_NANOSECONDS || nanos > MAX_NANOSECONDS {
            None
        } else {
            Some(Self::from_nanos_unchecked(nanos))
        }
    }

    pub(crate) const fn from_secs_unchecked(secs: i64) -> Self {
        TimeDelta { secs, nanos: 0 }
    }

    pub(crate) const fn total_nanos(&self) -> i128 {
        self.secs as i128 * 1_000_000_000 + self.nanos as i128
    }

    pub(crate) const fn subsec_nanos(&self) -> u32 {
        self.nanos
    }

    pub(crate) const fn whole_seconds(&self) -> i64 {
        self.secs
    }

    #[cfg(target_pointer_width = "64")]
    pub(crate) const fn pyhash(self) -> Py_hash_t {
        hash_combine(self.nanos as Py_hash_t, self.secs as Py_hash_t)
    }

    #[cfg(target_pointer_width = "32")]
    pub(crate) const fn pyhash(self) -> Py_hash_t {
        hash_combine(
            self.nanos as Py_hash_t,
            hash_combine(self.secs as Py_hash_t, (self.secs >> 32) as Py_hash_t),
        )
    }

    pub(crate) const fn is_zero(&self) -> bool {
        self.secs == 0 && self.nanos == 0
    }

    pub(crate) fn abs(self) -> Self {
        if self.secs >= 0 {
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
        Self::from_nanos(self.total_nanos() + other.total_nanos())
    }

    pub(crate) const ZERO: Self = Self { secs: 0, nanos: 0 };
}

impl PyWrapped for TimeDelta {}

impl Neg for TimeDelta {
    type Output = Self;

    fn neg(self) -> TimeDelta {
        let (extra_seconds, nanos) = match self.nanos {
            0 => (0, 0),
            nanos => (1, 1_000_000_000 - nanos),
        };
        TimeDelta {
            secs: -self.secs - extra_seconds,
            nanos,
        }
    }
}

impl std::fmt::Display for TimeDelta {
    fn fmt(&self, f: &mut fmt::Formatter<'_>) -> fmt::Result {
        let delta: TimeDelta = if self.secs < 0 {
            write!(f, "-")?;
            -*self
        } else {
            *self
        };
        write!(
            f,
            "{:02}:{:02}:{:02}",
            delta.secs / 3600,
            (delta.secs % 3600) / 60,
            delta.secs % 60,
        )?;
        if delta.nanos != 0 {
            f.write_str(format!(".{:09}", delta.nanos).trim_end_matches('0'))
        } else {
            fmt::Result::Ok(())
        }
    }
}

#[allow(clippy::unnecessary_cast)]
pub(crate) const MAX_SECS: i64 = (MAX_YEAR as i64) * 366 * 24 * 3600;
pub(crate) const MAX_HOURS: i64 = MAX_SECS / 3600;
pub(crate) const MAX_MINUTES: i64 = MAX_SECS / 60;
pub(crate) const MAX_MILLISECONDS: i64 = MAX_SECS * 1_000;
pub(crate) const MAX_MICROSECONDS: i64 = MAX_SECS * 1_000_000;
pub(crate) const MAX_NANOSECONDS: i128 = MAX_SECS as i128 * 1_000_000_000;
const SECS_PER_DAY: i64 = 24 * 3600;

pub(crate) const SINGLETONS: &[(&CStr, TimeDelta); 3] = &[
    (c"ZERO", TimeDelta { secs: 0, nanos: 0 }),
    (
        c"MIN",
        TimeDelta {
            secs: -MAX_SECS,
            nanos: 0,
        },
    ),
    (
        // FUTURE: should the nanos be 999_999_999?
        c"MAX",
        TimeDelta {
            secs: MAX_SECS,
            nanos: 0,
        },
    ),
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
        (0, 0) => TimeDelta { secs: 0, nanos: 0 }, // FUTURE: return the singleton?
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
        _ => Err(type_err!("TimeDelta() takes no positional arguments"))?,
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
        let TimeDelta { secs, nanos } = TimeDelta::extract(delta_obj);
        let nanos = (secs as f64 * 1e9 + nanos as f64) * factor;
        if nanos.is_nan() || !(-MAX_NANOSECONDS as f64..MAX_NANOSECONDS as f64).contains(&nanos) {
            Err(value_err!("Multiplication result out of range"))?
        }
        TimeDelta::from_nanos_unchecked(nanos as i128).to_obj(Py_TYPE(delta_obj))
    }
}

unsafe fn __truediv__(slf: *mut PyObject, factor_obj: *mut PyObject) -> PyReturn {
    if factor_obj.is_int() {
        let factor = factor_obj
            .to_i128()?
            // safe to unwrap since we already know it's an int
            .unwrap();
        if factor == 1 {
            return Ok(newref(slf));
        } else if factor == 0 {
            Err(py_err!(PyExc_ZeroDivisionError, "Division by zero"))?
        }
        let nanos = TimeDelta::extract(slf).total_nanos();
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
            Err(py_err!(PyExc_ZeroDivisionError, "Division by zero"))?
        }
        let mut nanos = TimeDelta::extract(slf).total_nanos() as f64;
        nanos /= factor;
        if nanos.is_nan() || (MAX_NANOSECONDS as f64) < nanos || nanos < -MAX_NANOSECONDS as f64 {
            Err(py_err!(PyExc_ValueError, "Division result out of range"))?
        };
        TimeDelta::from_nanos_unchecked(nanos as i128)
    } else if Py_TYPE(factor_obj) == Py_TYPE(slf) {
        let factor = TimeDelta::extract(factor_obj).total_nanos();
        if factor == 0 {
            Err(py_err!(PyExc_ZeroDivisionError, "Division by zero"))?
        }
        return (TimeDelta::extract(slf).total_nanos() as f64 / factor as f64).to_py();
    } else {
        return Ok(newref(Py_NotImplemented()));
    }
    .to_obj(Py_TYPE(slf))
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
                .map_err(|e| match e {
                    InitError::TooBig => value_err!("Result out of range"),
                    InitError::MixedSign => value_err!("Mixed sign of delta components"),
                })?
            } else {
                Err(type_err!(
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
    if delta.secs >= 0 {
        Ok(newref(slf))
    } else {
        (-delta).to_obj(Py_TYPE(slf))
    }
}

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
    PyType_Slot {
        slot: Py_tp_doc,
        pfunc: c"A delta type of precise time units".as_ptr() as *mut c_void,
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
    let TimeDelta { secs, nanos } = TimeDelta::extract(slf);
    let data = pack![secs, nanos];
    (
        State::for_obj(slf).unpickle_time_delta,
        steal!((steal!(data.to_py()?),).to_py()?),
    )
        .to_py()
}

pub(crate) unsafe fn unpickle(module: *mut PyObject, arg: *mut PyObject) -> PyReturn {
    let mut data = arg.to_bytes()?.ok_or_value_err("Invalid pickle data")?;
    if data.len() != 12 {
        Err(value_err!("Invalid pickle data"))?;
    }
    TimeDelta {
        secs: unpack_one!(data, i64),
        nanos: unpack_one!(data, u32),
    }
    .to_obj(State::for_mod(module).time_delta_type)
}

unsafe fn in_nanoseconds(slf: *mut PyObject, _: *mut PyObject) -> PyReturn {
    TimeDelta::extract(slf).total_nanos().to_py()
}

unsafe fn in_microseconds(slf: *mut PyObject, _: *mut PyObject) -> PyReturn {
    let TimeDelta { secs, nanos } = TimeDelta::extract(slf);
    (secs as f64 * 1e6 + nanos as f64 * 1e-3).to_py()
}

unsafe fn in_milliseconds(slf: *mut PyObject, _: *mut PyObject) -> PyReturn {
    let TimeDelta { secs, nanos } = TimeDelta::extract(slf);
    (secs as f64 * 1e3 + nanos as f64 * 1e-6).to_py()
}

unsafe fn in_seconds(slf: *mut PyObject, _: *mut PyObject) -> PyReturn {
    let TimeDelta { secs, nanos } = TimeDelta::extract(slf);
    (secs as f64 + nanos as f64 * 1e-9).to_py()
}

unsafe fn in_minutes(slf: *mut PyObject, _: *mut PyObject) -> PyReturn {
    let TimeDelta { secs, nanos } = TimeDelta::extract(slf);
    (secs as f64 / 60.0 + nanos as f64 * 1e-9 / 60.0).to_py()
}

unsafe fn in_hours(slf: *mut PyObject, _: *mut PyObject) -> PyReturn {
    let TimeDelta { secs, nanos } = TimeDelta::extract(slf);
    (secs as f64 / 3600.0 + nanos as f64 * 1e-9 / 3600.0).to_py()
}

unsafe fn in_days_of_24h(slf: *mut PyObject, _: *mut PyObject) -> PyReturn {
    let TimeDelta { secs, nanos } = TimeDelta::extract(slf);
    (secs as f64 / 86_400.0 + nanos as f64 * 1e-9 / 86_400.0).to_py()
}

unsafe fn from_py_timedelta(cls: *mut PyObject, d: *mut PyObject) -> PyReturn {
    if PyDelta_Check(d) == 0 {
        Err(type_err!("argument must be datetime.timedelta"))?;
    }
    let secs = i64::from(PyDateTime_DELTA_GET_DAYS(d)) * SECS_PER_DAY
        + i64::from(PyDateTime_DELTA_GET_SECONDS(d));
    if !(-MAX_SECS..=MAX_SECS).contains(&secs) {
        Err(value_err!("TimeDelta out of range"))?;
    }
    TimeDelta {
        secs,
        nanos: PyDateTime_DELTA_GET_MICROSECONDS(d) as u32 * 1_000,
    }
    .to_obj(cls.cast())
}

unsafe fn py_timedelta(slf: *mut PyObject, _: *mut PyObject) -> PyReturn {
    let TimeDelta { nanos, mut secs } = TimeDelta::extract(slf);
    let &PyDateTime_CAPI {
        Delta_FromDelta,
        DeltaType,
        ..
    } = State::for_obj(slf).py_api;
    let mut micros = (nanos as f64 / 1_000.0).round_ties_even() as i32;
    if micros == 1_000_000 {
        micros = 0;
        secs += 1
    }
    let sign = if secs >= 0 { 1 } else { -1 };
    Delta_FromDelta(
        (secs.div_euclid(SECS_PER_DAY * sign) * sign) as _,
        secs.rem_euclid(SECS_PER_DAY * sign) as _,
        micros,
        0,
        DeltaType,
    )
    .as_result()
}

fn parse_prefix(s: &mut &[u8]) -> Option<i128> {
    let (result, cursor) = match &s[..3] {
        b"+PT" => (Some(1), 3),
        b"-PT" => (Some(-1), 3),
        [b'P', b'T', _] => (Some(1), 2),
        _ => return None,
    };
    *s = &s[cursor..];
    result
}

unsafe fn in_hrs_mins_secs_nanos(slf: *mut PyObject, _: *mut PyObject) -> PyReturn {
    let TimeDelta {
        secs,
        nanos: nanos_unsigned,
    } = TimeDelta::extract(slf);

    let (secs, nanos) = if secs >= 0 {
        (secs, nanos_unsigned as i32)
    } else if nanos_unsigned == 0 {
        (secs, 0)
    } else {
        (secs + 1, nanos_unsigned as i32 - 1_000_000_000)
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
pub(crate) fn format_components(td: TimeDelta, s: &mut String) {
    let TimeDelta { mut secs, nanos } = td;
    debug_assert!(secs >= 0);
    debug_assert!(secs > 0 || nanos > 0);
    let hours = secs / 3600;
    let minutes = secs / 60 % 60;
    secs %= 60;
    if hours != 0 {
        s.push_str(&format!("{}H", hours));
    }
    if minutes != 0 {
        s.push_str(&format!("{}M", minutes));
    }
    match (secs, nanos) {
        (0, 0) => {}
        (_, 0) => s.push_str(&format!("{}S", secs)),
        _ => {
            s.push_str(format!("{}.{:09}", secs, nanos).trim_end_matches('0'));
            s.push('S');
        }
    }
}

unsafe fn format_common_iso(slf: *mut PyObject, _: *mut PyObject) -> PyReturn {
    let mut delta = TimeDelta::extract(slf);
    if delta.secs == 0 && delta.nanos == 0 {
        return "PT0S".to_py();
    }
    let mut s: String = String::with_capacity(8);
    if delta.secs < 0 {
        s.push('-');
        delta = -delta;
    }
    s.push_str("PT");
    format_components(delta, &mut s);
    s.to_py()
}

#[derive(Debug, PartialEq, Copy, Clone)]
enum Unit {
    Hours,
    Minutes,
    Nanoseconds,
}

// 001234 -> 1_234_000
fn parse_nano_fractions(s: &[u8]) -> Option<i128> {
    let mut tally = parse_digit(s, 0)? as i128 * 100_000_000;
    for i in 1..min(s.len(), 9) {
        match s[i] {
            c if c.is_ascii_digit() => {
                tally += i128::from(c - b'0') * i128::from(10_u32.pow(8 - i as u32))
            }
            // S is only valid at the very end
            b'S' if i + 1 == s.len() => {
                return Some(tally);
            }
            _ => return None,
        }
    }
    // at this point we've parsed 9 fractional digits successfully.
    // Only encountering `S` is valid. Nothing more, nothing less.
    match s[9..] {
        [b'S'] => Some(tally),
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
    for i in 0..min(s.len(), 35) {
        match s[i] {
            c if c.is_ascii_digit() => tally = tally * 10 + i128::from(c - b'0'),
            b'H' => {
                *s = &s[i + 1..];
                return Some((tally, Unit::Hours));
            }
            b'M' => {
                *s = &s[i + 1..];
                return Some((tally, Unit::Minutes));
            }
            b'S' => {
                *s = &s[i + 1..];
                return Some((tally * 1_000_000_000, Unit::Nanoseconds));
            }
            b'.' if i > 0 => {
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
                }
                // i.e. there's still something left after the nanoseconds
                return None;
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

    let sign = (s.len() >= 4)
        .then(|| parse_prefix(s))
        .flatten()
        .ok_or_else(|| value_err!("Invalid format: {}", s_obj.repr()))?;

    let (nanos, empty) =
        parse_all_components(s).ok_or_else(|| value_err!("Invalid format: {}", s_obj.repr()))?;

    // i.e. there must be at least one component (`PT` alone is invalid)
    if empty {
        Err(value_err!("Invalid format: {}", s_obj.repr()))?;
    }
    TimeDelta::from_nanos(nanos * sign)
        .ok_or_value_err("Time delta out of range")?
        .to_obj(cls.cast())
}

static mut METHODS: &[PyMethodDef] = &[
    method!(identity2 named "__copy__", ""),
    method!(identity2 named "__deepcopy__", "", METH_O),
    method!(
        format_common_iso,
        "Return the time delta in the common ISO8601 format"
    ),
    method!(
        parse_common_iso,
        "Parse from the common ISO8601 period format",
        METH_O | METH_CLASS
    ),
    method!(in_nanoseconds, "Return the total number of nanoseconds"),
    method!(in_microseconds, "Return the total number of microseconds"),
    method!(in_milliseconds, "Return the total number of milliseconds"),
    method!(in_seconds, "Return the total number of seconds"),
    method!(in_minutes, "Return the total number of minutes"),
    method!(in_hours, "Return the total number of hours"),
    method!(
        in_days_of_24h,
        "Return the total number of days, assuming 24 hours per day"
    ),
    method!(
        from_py_timedelta,
        "Create a date from a Python datetime.timedelta",
        METH_O | METH_CLASS
    ),
    method!(py_timedelta, "Convert to a Python datetime.timedelta"),
    method!(in_hrs_mins_secs_nanos, "Return the time delta as a tuple"),
    method!(__reduce__, ""),
    PyMethodDef::zeroed(),
];

type_spec!(TimeDelta, SLOTS);
