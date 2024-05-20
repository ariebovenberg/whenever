use core::ffi::{c_int, c_void};
use core::{mem, ptr};
use pyo3_ffi::*;
use std::cmp::min;
use std::fmt;
use std::ops::Neg;
use std::ptr::null_mut as NULL;

use crate::common::*;
use crate::date::MAX_YEAR;
use crate::date_delta::{DateDelta, InitError};
use crate::datetime_delta::{self, DateTimeDelta};
use crate::State;

#[derive(Debug, Eq, PartialEq, Ord, PartialOrd, Copy, Clone)]
pub(crate) struct TimeDelta {
    // struct design inspired by datetime.timedelta and chrono::TimeDelta
    pub(crate) secs: i64,  // div_euclid(total_nanos) - may be negative
    pub(crate) nanos: u32, // rem_euclid(total_nanos) - never negative
}

#[repr(C)]
pub(crate) struct PyTimeDelta {
    _ob_base: PyObject,
    data: TimeDelta,
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

    pub(crate) unsafe fn extract(obj: *mut PyObject) -> Self {
        (*obj.cast::<PyTimeDelta>()).data
    }

    pub(crate) const fn subsec_nanos(&self) -> u32 {
        self.nanos
    }

    pub(crate) const fn whole_seconds(&self) -> i64 {
        self.secs
    }

    #[cfg(target_pointer_width = "64")]
    pub(crate) const fn pyhash(self) -> Py_hash_t {
        self.nanos as Py_hash_t ^ self.secs as Py_hash_t
    }

    #[cfg(target_pointer_width = "32")]
    pub(crate) const fn pyhash(self) -> Py_hash_t {
        self.nanos as Py_hash_t ^ self.secs as Py_hash_t ^ (self.secs >> 32) as Py_hash_t
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
            "PT{:02}:{:02}:{:02}",
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
pub(crate) const MAX_SECS: i64 = (MAX_YEAR * 366 * 24 * 3600) as i64;
pub(crate) const MAX_HOURS: i64 = MAX_SECS / 3600;
pub(crate) const MAX_MINUTES: i64 = MAX_SECS / 60;
pub(crate) const MAX_MILLISECONDS: i64 = MAX_SECS * 1_000;
pub(crate) const MAX_MICROSECONDS: i64 = MAX_SECS * 1_000_000;
pub(crate) const MAX_NANOSECONDS: i128 = MAX_SECS as i128 * 1_000_000_000;
const SECS_PER_DAY: i64 = 24 * 3600;

pub(crate) const SINGLETONS: [(&str, TimeDelta); 3] = [
    ("ZERO\0", TimeDelta { secs: 0, nanos: 0 }),
    (
        "MIN\0",
        TimeDelta {
            secs: -MAX_SECS,
            nanos: 0,
        },
    ),
    (
        "MAX\0",
        TimeDelta {
            secs: MAX_SECS,
            nanos: 0,
        },
    ),
];

macro_rules! handle_unit(
    ($obj:expr, $unit:literal, $max:expr, $num_nanos:expr) => {{
        if PyLong_Check($obj) != 0 {
            let i = $obj.to_long()?
                // Safe to unwrap since we just checked that it's a long
                .unwrap();
            if !(-$max..=$max).contains(&i) {
                Err(value_error!("%s out of range", c_str!($unit)))?
            }
            i as i128 * $num_nanos
        } else {
            let f = $obj.to_f64()?
                .ok_or_else(|| value_error!("%s must be an integer or float", c_str!($unit)))?;
            if f < -$max as _ || f > $max as _ || f.is_nan() {
                Err(value_error!("%s out of range", c_str!($unit)))?
            }
            (f * $num_nanos as f64) as i128
        }
    }}
);

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

    let delta = match (nargs, nkwargs) {
        (0, 0) => TimeDelta { secs: 0, nanos: 0 }, // FUTURE: return the singleton
        (0, _) => {
            let mut key: *mut PyObject = NULL();
            let mut value: *mut PyObject = NULL();
            let mut pos: Py_ssize_t = 0;
            while PyDict_Next(kwargs, &mut pos, &mut key, &mut value) != 0 {
                if key == str_hours {
                    nanos += handle_unit!(value, "hours", MAX_HOURS, 3_600_000_000_000_i128);
                } else if key == str_minutes {
                    nanos += handle_unit!(value, "minutes", MAX_MINUTES, 60_000_000_000_i128);
                } else if key == str_seconds {
                    nanos += handle_unit!(value, "seconds", MAX_SECS, 1_000_000_000_i128);
                } else if key == str_milliseconds {
                    nanos += handle_unit!(value, "milliseconds", MAX_MILLISECONDS, 1_000_000_i128);
                } else if key == str_microseconds {
                    nanos += handle_unit!(value, "microseconds", MAX_MICROSECONDS, 1_000_i128);
                } else if key == str_nanoseconds {
                    nanos += value
                        .to_i128()?
                        .ok_or_else(|| value_error!("nanoseconds must be an integer"))?;
                } else {
                    Err(type_error!(
                        "TimeDelta() got an unexpected keyword argument: %R",
                        key
                    ))?
                }
            }
            TimeDelta::from_nanos(nanos).ok_or_else(|| value_error!("TimeDelta out of range"))?
        }
        _ => Err(type_error!("TimeDelta() takes no positional arguments"))?,
    };
    new_unchecked(cls, delta)
}

pub(crate) unsafe fn hours(module: *mut PyObject, amount: *mut PyObject) -> PyReturn {
    new_unchecked(
        State::for_mod(module).time_delta_type,
        TimeDelta::from_nanos_unchecked(handle_unit!(
            amount,
            "hours",
            MAX_HOURS,
            3_600_000_000_000_i128
        )),
    )
}

pub(crate) unsafe fn minutes(module: *mut PyObject, amount: *mut PyObject) -> PyReturn {
    new_unchecked(
        State::for_mod(module).time_delta_type,
        TimeDelta::from_nanos_unchecked(handle_unit!(
            amount,
            "minutes",
            MAX_MINUTES,
            60_000_000_000_i128
        )),
    )
}

pub(crate) unsafe fn seconds(module: *mut PyObject, amount: *mut PyObject) -> PyReturn {
    new_unchecked(
        State::for_mod(module).time_delta_type,
        TimeDelta::from_nanos_unchecked(handle_unit!(
            amount,
            "seconds",
            MAX_SECS,
            1_000_000_000_i128
        )),
    )
}

pub(crate) unsafe fn milliseconds(module: *mut PyObject, amount: *mut PyObject) -> PyReturn {
    new_unchecked(
        State::for_mod(module).time_delta_type,
        TimeDelta::from_nanos_unchecked(handle_unit!(
            amount,
            "milliseconds",
            MAX_MILLISECONDS,
            1_000_000i128
        )),
    )
}

pub(crate) unsafe fn microseconds(module: *mut PyObject, amount: *mut PyObject) -> PyReturn {
    new_unchecked(
        State::for_mod(module).time_delta_type,
        TimeDelta::from_nanos_unchecked(handle_unit!(
            amount,
            "microseconds",
            MAX_MICROSECONDS,
            1_000_i128
        )),
    )
}

pub(crate) unsafe fn nanoseconds(module: *mut PyObject, amount: *mut PyObject) -> PyReturn {
    new_unchecked(
        State::for_mod(module).time_delta_type,
        TimeDelta::from_nanos_unchecked(
            amount
                .to_i128()?
                .ok_or_else(|| value_error!("nanoseconds must be an integer"))?,
        ),
    )
}

unsafe fn __richcmp__(obj_a: *mut PyObject, obj_b: *mut PyObject, op: c_int) -> PyReturn {
    Ok(newref(if Py_TYPE(obj_b) == Py_TYPE(obj_a) {
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
        .to_py()?
    } else {
        Py_NotImplemented()
    }))
}

unsafe extern "C" fn __hash__(slf: *mut PyObject) -> Py_hash_t {
    let tdelta = TimeDelta::extract(slf);
    hashmask(tdelta.pyhash())
}

unsafe fn __neg__(slf: *mut PyObject) -> PyReturn {
    new_unchecked(Py_TYPE(slf), -TimeDelta::extract(slf))
}

unsafe extern "C" fn __bool__(slf: *mut PyObject) -> c_int {
    let TimeDelta { secs, nanos } = TimeDelta::extract(slf);
    (secs != 0 || nanos != 0).into()
}

unsafe fn __repr__(slf: *mut PyObject) -> PyReturn {
    format!("TimeDelta({})", TimeDelta::extract(slf)).to_py()
}

unsafe fn __str__(slf: *mut PyObject) -> PyReturn {
    format!("{}", TimeDelta::extract(slf)).to_py()
}

unsafe fn __mul__(slf: *mut PyObject, factor_obj: *mut PyObject) -> PyReturn {
    // TODO: reflexivity?
    let new = if PyLong_Check(factor_obj) != 0 {
        let factor = factor_obj
            .to_i128()?
            // safe to unwrap since we already know it's a long
            .unwrap();
        if factor == 1 {
            return Ok(newref(slf));
        }
        TimeDelta::extract(slf)
            .total_nanos()
            .checked_mul(factor)
            .and_then(TimeDelta::from_nanos)
            .ok_or_else(|| value_error!("Multiplication result out of range"))?
    } else if PyFloat_Check(factor_obj) != 0 {
        let factor = factor_obj
            .to_f64()?
            // safe to unwrap since we've just checked it's a float
            .unwrap();
        if factor == 1.0 {
            return Ok(newref(slf));
        }
        let TimeDelta { secs, nanos } = TimeDelta::extract(slf);
        Some((secs as f64 * 1e9 + nanos as f64) * factor)
            .filter(|&t| t.is_finite() && t.abs() < MAX_NANOSECONDS as f64)
            .map(|t| TimeDelta::from_nanos_unchecked(t as i128))
            .ok_or_else(|| value_error!("Multiplication result out of range"))?
    } else {
        return Ok(newref(Py_NotImplemented()));
    };
    new_unchecked(Py_TYPE(slf), new)
}

unsafe fn __truediv__(slf: *mut PyObject, factor_obj: *mut PyObject) -> PyReturn {
    // TODO: reflexivity?
    // get the factor, complicated by the fact that it can be a float,
    // or even a >i64::MAX integer
    let new = if PyLong_Check(factor_obj) != 0 {
        let factor = factor_obj
            .to_i128()?
            // safe to unwrap since we already know it's a long
            .unwrap();
        if factor == 1 {
            return Ok(newref(slf));
        } else if factor == 0 {
            Err(py_error!(PyExc_ZeroDivisionError, "Division by zero"))?
        }
        let nanos = TimeDelta::extract(slf).total_nanos();
        TimeDelta::from_nanos_unchecked(if nanos % factor == 0 {
            nanos / factor
        } else {
            (nanos as f64 / factor as f64).round() as i128
        })
    } else if PyFloat_Check(factor_obj) != 0 {
        let factor = factor_obj
            .to_f64()?
            // safe to unwrap since we already know it's a float
            .unwrap();
        if factor == 1.0 {
            return Ok(newref(slf));
        } else if factor == 0.0 {
            Err(py_error!(PyExc_ZeroDivisionError, "Division by zero"))?
        }
        let mut nanos = TimeDelta::extract(slf).total_nanos() as f64;
        nanos /= factor;
        if nanos.is_nan() || (MAX_NANOSECONDS as f64) < nanos || nanos < -MAX_NANOSECONDS as f64 {
            Err(py_error!(PyExc_ValueError, "Division result out of range"))?
        };
        TimeDelta::from_nanos_unchecked(nanos as i128)
    } else if Py_TYPE(factor_obj) == Py_TYPE(slf) {
        let factor = TimeDelta::extract(factor_obj).total_nanos();
        if factor == 0 {
            Err(py_error!(PyExc_ZeroDivisionError, "Division by zero"))?
        }
        return (TimeDelta::extract(slf).total_nanos() as f64 / factor as f64).to_py();
    } else {
        return Ok(newref(Py_NotImplemented()));
    };
    new_unchecked(Py_TYPE(slf), new)
}

// TODO: add/subtract *methods*
unsafe fn __add__(obj_a: *mut PyObject, obj_b: *mut PyObject) -> PyReturn {
    _add_method(obj_a, obj_b, false)
}

unsafe fn __sub__(a_obj: *mut PyObject, b_obj: *mut PyObject) -> PyReturn {
    _add_method(a_obj, b_obj, true)
}

#[inline]
unsafe fn _add_method(obj_a: *mut PyObject, obj_b: *mut PyObject, negate: bool) -> PyReturn {
    let type_a = Py_TYPE(obj_a);
    let type_b = Py_TYPE(obj_b);
    // The easy case: both are TimeDelta
    if type_a == type_b {
        let a = TimeDelta::extract(obj_a);
        let mut b = TimeDelta::extract(obj_b);
        if negate {
            b = -b;
        }
        new_unchecked(
            type_a,
            a.checked_add(b)
                .ok_or_else(|| value_error!("Addition result out of range"))?,
        )
    } else {
        let mod_a = PyType_GetModule(type_a);
        let mod_b = PyType_GetModule(type_b);
        if mod_a == mod_b {
            // at this point we know that `a` is a TimeDelta
            let state = State::for_mod(mod_a);
            let delta_a = TimeDelta::extract(obj_a);
            let result = if type_b == state.date_delta_type {
                let mut b = DateDelta::extract(obj_b);
                if negate {
                    b = -b;
                }
                DateTimeDelta::new(b, delta_a)
                    .ok_or_else(|| value_error!("Mixed sign of delta components"))?
            } else if type_b == state.datetime_delta_type {
                let mut b = DateTimeDelta::extract(obj_b);
                if negate {
                    b = -b;
                }
                b.checked_add(DateTimeDelta {
                    ddelta: DateDelta::ZERO,
                    tdelta: delta_a,
                })
                .map_err(|e| match e {
                    InitError::TooBig => value_error!("Result out of range"),
                    InitError::MixedSign => value_error!("Mixed sign of delta components"),
                })?
            } else {
                return Err(type_error!(
                    "unsupported operand type(s) for +/-: %R and %R",
                    type_a,
                    type_b
                ));
            };
            datetime_delta::new_unchecked(state.datetime_delta_type, result)
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
        new_unchecked(Py_TYPE(slf), -delta)
    }
}

static mut SLOTS: &[PyType_Slot] = &[
    PyType_Slot {
        slot: Py_tp_doc,
        pfunc: "A delta type of precise time units\0".as_ptr() as *mut c_void,
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
        pfunc: dealloc as *mut c_void,
    },
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
        slot: 0,
        pfunc: NULL(),
    },
];

unsafe fn default_format(slf: *mut PyObject, _: *mut PyObject) -> PyReturn {
    __str__(slf)
}

unsafe fn __reduce__(slf: *mut PyObject, _: *mut PyObject) -> PyReturn {
    let TimeDelta { secs, nanos } = TimeDelta::extract(slf);
    PyTuple_Pack(
        2,
        State::for_obj(slf).unpickle_time_delta,
        steal!(PyTuple_Pack(1, steal!(pack![secs, nanos].to_py()?)).as_result()?),
    )
    .as_result()
}

// OPTIMIZE: a more efficient pickle?
pub(crate) unsafe fn unpickle(module: *mut PyObject, args: &[*mut PyObject]) -> PyReturn {
    if args.len() != 1 {
        Err(type_error!("TimeDelta unpickle requires 1 argument"))?
    }
    let mut data = args[0]
        .to_bytes()?
        .ok_or_else(|| value_error!("Invalid pickle data"))?;
    let new = new_unchecked(
        State::for_mod(module).time_delta_type,
        TimeDelta {
            secs: unpack_one!(data, i64),
            nanos: unpack_one!(data, u32),
        },
    );
    if !data.is_empty() {
        Err(value_error!("Invalid pickle data"))?;
    }
    new
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
        Err(type_error!("argument must be datetime.timedelta"))?;
    }
    new_unchecked(
        cls.cast(),
        TimeDelta {
            secs: i64::from(PyDateTime_DELTA_GET_DAYS(d)) * 24 * 3600
                + i64::from(PyDateTime_DELTA_GET_SECONDS(d)),
            nanos: PyDateTime_DELTA_GET_MICROSECONDS(d) as u32 * 1_000,
        },
    )
}

unsafe fn py_timedelta(slf: *mut PyObject, _: *mut PyObject) -> PyReturn {
    let TimeDelta { nanos, mut secs } = TimeDelta::extract(slf);
    let &PyDateTime_CAPI {
        Delta_FromDelta,
        DeltaType,
        ..
    } = State::for_obj(slf).datetime_api;
    // This whole circus just to round nanoseconds...there's probably
    // a better way to do this
    let mut micros = (nanos / 1_000) as i32;
    if nanos % 1_000 >= 500 {
        micros += 1;
        secs += (micros / 1_000_000) as i64;
        micros %= 1_000_000;
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

// parses H[HHHHHH]:<rest>
fn parse_hours(s: &mut &[u8]) -> Option<u32> {
    let mut hours = u32::from(get_digit!(s, 0));
    // limit parsing to 8 characters in total to prevent overflow
    for i in 1..min(s.len(), 7) {
        match s[i] {
            c if c.is_ascii_digit() => hours = hours * 10 + u32::from(c - b'0'),
            b':' => {
                *s = &s[i + 1..];
                return Some(hours);
            }
            _ => break,
        }
    }
    None
}

// MM:SS[.nnnnnnnnn] -> (MM, SS, nnnnnnnnn)
fn parse_mins_secs_nanos(s: &[u8]) -> Option<(u8, u8, u32)> {
    if s.len() < 5 || s[2] != b':' {
        return None;
    }
    let minutes = get_digit!(s, 0, ..=b'5') * 10 + get_digit!(s, 1);
    let seconds = get_digit!(s, 3, ..=b'5') * 10 + get_digit!(s, 4);

    let mut nanos = 0;
    if s.len() > 5 {
        if s[5] != b'.' || s.len() == 6 || s.len() > 15 {
            return None;
        }
        for (i, factor) in s[6..].iter().zip(&[
            100_000_000,
            10_000_000,
            1_000_000,
            100_000,
            10_000,
            1_000,
            100,
            10,
            1,
        ]) {
            if !i.is_ascii_digit() {
                return None;
            }
            nanos += u32::from(i - b'0') * factor;
        }
    }
    Some((minutes, seconds, nanos))
}

fn parse_prefix(s: &mut &[u8]) -> Option<i128> {
    let (result, i) = match &s[..3] {
        b"+PT" => (Some(1), 3),
        b"-PT" => (Some(-1), 3),
        [b'P', b'T', _] => (Some(1), 2),
        _ => return None,
    };
    *s = &s[i..];
    result
}

unsafe fn from_default_format(cls: *mut PyObject, s_obj: *mut PyObject) -> PyReturn {
    let s = &mut s_obj
        .to_utf8()?
        .ok_or_else(|| type_error!("Argument must be a string"))?;

    let sign = (s.len() > 8)
        .then(|| parse_prefix(s))
        .flatten()
        .ok_or_else(|| value_error!("Invalid time delta format: %R", s_obj))?;

    let (hours, (mins, secs, nanos)) = parse_hours(s)
        .zip(parse_mins_secs_nanos(s))
        .ok_or_else(|| value_error!("Invalid time delta format: %R", s_obj))?;
    new_unchecked(
        cls.cast(),
        TimeDelta::from_nanos(
            sign * ((hours as i64 * 3600 + mins as i64 * 60 + secs as i64) as i128 * 1_000_000_000
                + nanos as i128),
        )
        .ok_or_else(|| value_error!("TimeDelta out of range"))?,
    )
}

unsafe fn as_hrs_mins_secs_nanos(slf: *mut PyObject, _: *mut PyObject) -> PyReturn {
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
    PyTuple_Pack(
        4,
        steal!((secs / 3_600).to_py()?),
        steal!((secs % 3_600 / 60).to_py()?),
        steal!((secs % 60).to_py()?),
        steal!(nanos.to_py()?),
    )
    .as_result()
}

#[inline]
pub(crate) fn format_components(td: TimeDelta, s: &mut String) -> () {
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

unsafe fn common_iso8601(slf: *mut PyObject, _: *mut PyObject) -> PyReturn {
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
    let mut tally = get_digit!(s, 0) as i128 * 100_000_000;
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
            b'.' => {
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
        if let Some((value, unit)) = parse_component(s) {
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
                    None?
                }
                // i.e. the order of the components is wrong
                _ => None?,
            }
        } else {
            // i.e. the component parsing failed
            None?
        }
    }
    Some((nanos, prev_unit.is_none()))
}

unsafe fn from_common_iso8601(cls: *mut PyObject, s_obj: *mut PyObject) -> PyReturn {
    let s = &mut s_obj
        .to_utf8()?
        .ok_or_else(|| type_error!("argument must be a string"))?;

    let sign = (s.len() >= 4)
        .then(|| parse_prefix(s))
        .flatten()
        .ok_or_else(|| value_error!("Invalid format: %R", s_obj))?;

    let (nanos, empty) =
        parse_all_components(s).ok_or_else(|| value_error!("Invalid format: %R", s_obj))?;

    // i.e. there must be at least one component (`PT` alone is invalid)
    if empty {
        Err(value_error!("Invalid format: %R", s_obj))?;
    }
    new_unchecked(
        cls.cast(),
        TimeDelta::from_nanos(nanos * sign)
            .ok_or_else(|| value_error!("Time delta out of range"))?,
    )
}

static mut METHODS: &[PyMethodDef] = &[
    method!(identity2 named "__copy__", ""),
    method!(identity2 named "__deepcopy__", "", METH_O),
    method!(default_format, "Format the time delta in the default way"),
    method!(
        common_iso8601,
        "Return the time delta in the common ISO8601 format"
    ),
    method!(
        from_default_format,
        "Parse from the default string representation",
        METH_O | METH_CLASS
    ),
    method!(
        from_common_iso8601,
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
    method!(as_hrs_mins_secs_nanos, "Return the date delta as a tuple"),
    method!(__reduce__, ""),
    PyMethodDef::zeroed(),
];

pub(crate) unsafe fn new_unchecked(type_: *mut PyTypeObject, d: TimeDelta) -> PyReturn {
    let f: allocfunc = (*type_).tp_alloc.expect("tp_alloc is not set");
    let slf = f(type_, 0).cast::<PyTimeDelta>();
    if slf.is_null() {
        return Err(PyErrOccurred());
    }
    ptr::addr_of_mut!((*slf).data).write(d);
    Ok(slf.cast::<PyObject>().as_mut().unwrap())
}

pub(crate) static mut SPEC: PyType_Spec = PyType_Spec {
    name: c_str!("whenever.TimeDelta"),
    basicsize: mem::size_of::<PyTimeDelta>() as _,
    itemsize: 0,
    flags: Py_TPFLAGS_DEFAULT as _,
    slots: unsafe { SLOTS as *const [_] as *mut _ },
};

#[allow(unused_imports)]
pub(crate) use handle_unit;
