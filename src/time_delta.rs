use core::ffi::{c_int, c_void};
use core::{mem, ptr};
use pyo3_ffi::*;
use std::cmp::min;
use std::fmt;
use std::ops::Neg;
use std::ptr::null_mut as NULL;

use crate::common::*;
use crate::date::MAX_YEAR;
use crate::State;

#[repr(C)]
#[derive(Debug, Eq, PartialEq, Ord, PartialOrd, Copy, Clone)]
pub(crate) struct TimeDelta {
    // struct design inspired by datetime.timedelta and chrono::TimeDelta
    secs: i64,  // div_euclid(total_nanos) - may be negative
    nanos: u32, // rem_euclid(total_nanos) - never negative
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
        (*obj.cast::<PyTimeDelta>()).delta
    }

    pub(crate) const fn subsec_nanos(&self) -> u32 {
        self.nanos
    }

    pub(crate) const fn whole_seconds(&self) -> i64 {
        self.secs
    }
}

#[repr(C)]
pub(crate) struct PyTimeDelta {
    _ob_base: PyObject,
    delta: TimeDelta,
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
            -self.clone()
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
            f.write_str(&format!(".{:09}", delta.nanos).trim_end_matches('0'))
        } else {
            fmt::Result::Ok(())
        }
    }
}

const MAX_SECS: i64 = (MAX_YEAR * 366 * 24 * 3600) as i64;
const MAX_HOURS: i64 = MAX_SECS / 3600;
const MAX_MINUTES: i64 = MAX_SECS / 60;
const MAX_MILLISECONDS: i64 = MAX_SECS * 1_000;
const MAX_MICROSECONDS: i64 = MAX_SECS * 1_000_000;
const MAX_NANOSECONDS: i128 = MAX_SECS as i128 * 1_000_000_000;
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
            let i = pyint_as_long!($obj);
            if i < -$max || i > $max {
                raise!(PyExc_ValueError, "%s out of range", c_str!($unit));
            }
            i as i128 * $num_nanos
        } else {
            let f = try_get_float!($obj);
            if f < -$max as _ || f > $max as _ || f.is_nan() {
                raise!(PyExc_ValueError, "%s out of range", c_str!($unit));
            }
            (f * $num_nanos as f64) as i128
        }
    }}
);

unsafe extern "C" fn __new__(
    type_: *mut PyTypeObject,
    args: *mut PyObject,
    kwargs: *mut PyObject,
) -> *mut PyObject {
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
    } = State::for_type(type_);

    let delta = match (nargs, nkwargs) {
        (0, 0) => TimeDelta { secs: 0, nanos: 0 }, // FUTURE: return the singleton
        (0, _) => {
            let mut key: *mut PyObject = NULL();
            let mut value: *mut PyObject = NULL();
            let mut pos: Py_ssize_t = 0;
            while PyDict_Next(kwargs, &mut pos, &mut key, &mut value) != 0 {
                if key == str_hours {
                    nanos += handle_unit!(value, "hours", MAX_HOURS, 3600_000_000_000i128);
                } else if key == str_minutes {
                    nanos += handle_unit!(value, "minutes", MAX_MINUTES, 60_000_000_000i128);
                } else if key == str_seconds {
                    nanos += handle_unit!(value, "seconds", MAX_SECS, 1_000_000_000i128);
                } else if key == str_milliseconds {
                    nanos += handle_unit!(value, "milliseconds", MAX_MILLISECONDS, 1_000_000i128);
                } else if key == str_microseconds {
                    nanos += handle_unit!(value, "microseconds", MAX_MICROSECONDS, 1_000i128);
                } else if key == str_nanoseconds {
                    nanos += i128_extract!(value, "nanoseconds must be an integer");
                } else {
                    raise!(
                        PyExc_TypeError,
                        "TimeDelta() got an unexpected keyword argument: %R",
                        key
                    );
                }
            }
            unwrap_or_raise!(
                TimeDelta::from_nanos(nanos),
                PyExc_ValueError,
                "TimeDelta out of range"
            )
        }
        _ => raise!(PyExc_TypeError, "TimeDelta() takes no positional arguments"),
    };
    new_unchecked(type_, delta)
}

pub(crate) unsafe extern "C" fn hours(
    module: *mut PyObject,
    amount: *mut PyObject,
) -> *mut PyObject {
    new_unchecked(
        State::for_mod(module).time_delta_type,
        TimeDelta::from_nanos_unchecked(handle_unit!(
            amount,
            "hours",
            MAX_HOURS,
            3600_000_000_000i128
        )),
    )
}

pub(crate) unsafe extern "C" fn minutes(
    module: *mut PyObject,
    amount: *mut PyObject,
) -> *mut PyObject {
    new_unchecked(
        State::for_mod(module).time_delta_type,
        TimeDelta::from_nanos_unchecked(handle_unit!(
            amount,
            "minutes",
            MAX_MINUTES,
            60_000_000_000i128
        )),
    )
}

pub(crate) unsafe extern "C" fn seconds(
    module: *mut PyObject,
    amount: *mut PyObject,
) -> *mut PyObject {
    new_unchecked(
        State::for_mod(module).time_delta_type,
        TimeDelta::from_nanos_unchecked(handle_unit!(
            amount,
            "seconds",
            MAX_SECS,
            1_000_000_000i128
        )),
    )
}

pub(crate) unsafe extern "C" fn milliseconds(
    module: *mut PyObject,
    amount: *mut PyObject,
) -> *mut PyObject {
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

pub(crate) unsafe extern "C" fn microseconds(
    module: *mut PyObject,
    amount: *mut PyObject,
) -> *mut PyObject {
    new_unchecked(
        State::for_mod(module).time_delta_type,
        TimeDelta::from_nanos_unchecked(handle_unit!(
            amount,
            "microseconds",
            MAX_MICROSECONDS,
            1_000i128
        )),
    )
}

pub(crate) unsafe extern "C" fn nanoseconds(
    module: *mut PyObject,
    amount: *mut PyObject,
) -> *mut PyObject {
    new_unchecked(
        State::for_mod(module).time_delta_type,
        TimeDelta::from_nanos_unchecked(i128_extract!(amount, "nanoseconds must be an integer")),
    )
}

unsafe extern "C" fn __richcmp__(
    obj_a: *mut PyObject,
    obj_b: *mut PyObject,
    op: c_int,
) -> *mut PyObject {
    newref(if Py_TYPE(obj_b) == Py_TYPE(obj_a) {
        let a = TimeDelta::extract(obj_a);
        let b = TimeDelta::extract(obj_b);
        py_bool(match op {
            pyo3_ffi::Py_EQ => a == b,
            pyo3_ffi::Py_NE => a != b,
            pyo3_ffi::Py_LT => a < b,
            pyo3_ffi::Py_LE => a <= b,
            pyo3_ffi::Py_GT => a > b,
            pyo3_ffi::Py_GE => a >= b,
            _ => unreachable!(),
        })
    } else {
        Py_NotImplemented()
    })
}

unsafe extern "C" fn __hash__(slf: *mut PyObject) -> Py_hash_t {
    let delta = TimeDelta::extract(slf);
    #[cfg(target_pointer_width = "64")]
    {
        (delta.nanos as Py_hash_t ^ delta.secs as Py_hash_t) & HASH_MASK
    }
    #[cfg(target_pointer_width = "32")]
    {
        (delta.nanos as Py_hash_t ^ delta.secs as Py_hash_t ^ (delta.secs >> 32) as Py_hash_t)
            & HASH_MASK
    }
}

unsafe extern "C" fn __neg__(slf: *mut PyObject) -> *mut PyObject {
    new_unchecked(Py_TYPE(slf), -TimeDelta::extract(slf))
}

unsafe extern "C" fn __bool__(slf: *mut PyObject) -> c_int {
    let TimeDelta { secs, nanos } = TimeDelta::extract(slf);
    (secs != 0 || nanos != 0).into()
}

unsafe extern "C" fn __repr__(slf: *mut PyObject) -> *mut PyObject {
    py_str(format!("TimeDelta({})", TimeDelta::extract(slf)).as_str())
}

unsafe extern "C" fn __str__(slf: *mut PyObject) -> *mut PyObject {
    py_str(format!("{}", TimeDelta::extract(slf)).as_str())
}

unsafe extern "C" fn __mul__(slf: *mut PyObject, factor_obj: *mut PyObject) -> *mut PyObject {
    let new = if PyLong_Check(factor_obj) != 0 {
        let factor = i128_extract_unchecked!(factor_obj.cast());
        if factor == 1 {
            return newref(slf);
        }
        unwrap_or_raise!(
            TimeDelta::extract(slf)
                .total_nanos()
                .checked_mul(factor)
                .and_then(TimeDelta::from_nanos),
            PyExc_ValueError,
            "Multiplication result out of range"
        )
    } else if PyFloat_Check(factor_obj) != 0 {
        let factor = try_get_float!(factor_obj);
        if factor == 1.0 {
            return newref(slf);
        }
        let TimeDelta { secs, nanos } = TimeDelta::extract(slf);
        unwrap_or_raise!(
            Some((secs as f64 * 1e9 + nanos as f64) * factor)
                .filter(|&t| t.is_finite() && t.abs() < MAX_NANOSECONDS as f64)
                .map(|t| TimeDelta::from_nanos_unchecked(t as i128)),
            PyExc_ValueError,
            "Multiplication result out of range"
        )
    } else {
        return newref(Py_NotImplemented());
    };
    new_unchecked(Py_TYPE(slf), new)
}

unsafe extern "C" fn __truediv__(slf: *mut PyObject, factor_obj: *mut PyObject) -> *mut PyObject {
    // get the factor, complicated by the fact that it can be a float,
    // or even a >i64::MAX integer
    let new = if PyLong_Check(factor_obj) != 0 {
        let factor = i128_extract_unchecked!(factor_obj.cast());
        if factor == 1 {
            return newref(slf);
        } else if factor == 0 {
            raise!(PyExc_ZeroDivisionError, "Division by zero");
        }
        let nanos = TimeDelta::extract(slf).total_nanos();
        TimeDelta::from_nanos_unchecked(if nanos % factor == 0 {
            nanos / factor
        } else {
            (nanos as f64 / factor as f64).round() as i128
        })
    } else if PyFloat_Check(factor_obj) != 0 {
        let factor = try_get_float!(factor_obj);
        if factor == 1.0 {
            return newref(slf);
        } else if factor == 0.0 {
            raise!(PyExc_ZeroDivisionError, "Division by zero");
        }
        let mut nanos = TimeDelta::extract(slf).total_nanos() as f64;
        nanos /= factor;
        if nanos.is_nan() || (MAX_NANOSECONDS as f64) < nanos || nanos < -MAX_NANOSECONDS as f64 {
            raise!(PyExc_ValueError, "Division result out of range");
        };
        TimeDelta::from_nanos_unchecked(nanos as i128)
    } else if Py_TYPE(factor_obj) == Py_TYPE(slf) {
        let factor = TimeDelta::extract(factor_obj).total_nanos();
        if factor == 0 {
            raise!(PyExc_ZeroDivisionError, "Division by zero");
        }
        return PyFloat_FromDouble(TimeDelta::extract(slf).total_nanos() as f64 / factor as f64);
    } else {
        return newref(Py_NotImplemented());
    };
    new_unchecked(Py_TYPE(slf), new)
}

unsafe extern "C" fn __add__(obj_a: *mut PyObject, obj_b: *mut PyObject) -> *mut PyObject {
    let cls = Py_TYPE(obj_a);
    if Py_TYPE(obj_b) == cls {
        let a = TimeDelta::extract(obj_a).total_nanos();
        let b = TimeDelta::extract(obj_b).total_nanos();
        new_unchecked(
            cls,
            unwrap_or_raise!(
                TimeDelta::from_nanos(a + b),
                PyExc_ValueError,
                "Addition result out of range"
            ),
        )
    } else {
        newref(Py_NotImplemented())
    }
}

unsafe extern "C" fn __sub__(a_obj: *mut PyObject, b_obj: *mut PyObject) -> *mut PyObject {
    let cls = Py_TYPE(a_obj);
    if Py_TYPE(b_obj) == cls {
        let a = TimeDelta::extract(a_obj).total_nanos();
        let b = TimeDelta::extract(b_obj).total_nanos();
        new_unchecked(
            cls,
            unwrap_or_raise!(
                TimeDelta::from_nanos(a - b),
                PyExc_ValueError,
                "Subtraction result out of range"
            ),
        )
    } else {
        newref(Py_NotImplemented())
    }
}

unsafe extern "C" fn __abs__(slf: *mut PyObject) -> *mut PyObject {
    let delta = TimeDelta::extract(slf);
    if delta.secs >= 0 {
        newref(slf)
    } else {
        new_unchecked(Py_TYPE(slf), -delta)
    }
}

static mut SLOTS: &[PyType_Slot] = &[
    PyType_Slot {
        slot: Py_tp_new,
        pfunc: __new__ as *mut c_void,
    },
    PyType_Slot {
        slot: Py_tp_doc,
        pfunc: "A delta type of precise time units\0".as_ptr() as *mut c_void,
    },
    PyType_Slot {
        slot: Py_tp_methods,
        pfunc: unsafe { METHODS.as_ptr() as *mut c_void },
    },
    PyType_Slot {
        slot: Py_tp_richcompare,
        pfunc: __richcmp__ as *mut c_void,
    },
    PyType_Slot {
        slot: Py_tp_hash,
        pfunc: __hash__ as *mut c_void,
    },
    PyType_Slot {
        slot: Py_nb_negative,
        pfunc: __neg__ as *mut c_void,
    },
    PyType_Slot {
        slot: Py_tp_repr,
        pfunc: __repr__ as *mut c_void,
    },
    PyType_Slot {
        slot: Py_nb_bool,
        pfunc: __bool__ as *mut c_void,
    },
    PyType_Slot {
        slot: Py_tp_str,
        pfunc: __str__ as *mut c_void,
    },
    PyType_Slot {
        slot: Py_nb_positive,
        pfunc: identity as *mut c_void,
    },
    PyType_Slot {
        slot: Py_nb_multiply,
        pfunc: __mul__ as *mut c_void,
    },
    PyType_Slot {
        slot: Py_nb_true_divide,
        pfunc: __truediv__ as *mut c_void,
    },
    PyType_Slot {
        slot: Py_nb_add,
        pfunc: __add__ as *mut c_void,
    },
    PyType_Slot {
        slot: Py_nb_subtract,
        pfunc: __sub__ as *mut c_void,
    },
    PyType_Slot {
        slot: Py_nb_absolute,
        pfunc: __abs__ as *mut c_void,
    },
    PyType_Slot {
        slot: 0,
        pfunc: NULL(),
    },
];

unsafe extern "C" fn default_format(slf: *mut PyObject, _: *mut PyObject) -> *mut PyObject {
    __str__(slf)
}

unsafe extern "C" fn __reduce__(slf: *mut PyObject, _: *mut PyObject) -> *mut PyObject {
    let TimeDelta { secs, nanos } = TimeDelta::extract(slf);
    PyTuple_Pack(
        2,
        State::for_obj(slf).unpickle_time_delta,
        py_try!(PyTuple_Pack(
            2,
            PyLong_FromLongLong(secs.into()),
            PyLong_FromLong(nanos.into()),
        )),
    )
}

// OPTIMIZE: a more efficient pickle?
pub(crate) unsafe extern "C" fn unpickle(
    module: *mut PyObject,
    args: *mut *mut PyObject,
    nargs: Py_ssize_t,
) -> *mut PyObject {
    if PyVectorcall_NARGS(nargs as usize) != 2 {
        raise!(PyExc_TypeError, "Invalid pickle data");
    }
    new_unchecked(
        State::for_mod(module).time_delta_type,
        TimeDelta {
            secs: pyint_as_long!(*args.offset(0)).into(),
            nanos: pyint_as_long!(*args.offset(1)) as _,
        },
    )
}

unsafe extern "C" fn in_nanoseconds(slf: *mut PyObject, _: *mut PyObject) -> *mut PyObject {
    py_int128(TimeDelta::extract(slf).total_nanos())
}

unsafe extern "C" fn in_microseconds(slf: *mut PyObject, _: *mut PyObject) -> *mut PyObject {
    let TimeDelta { secs, nanos } = TimeDelta::extract(slf);
    PyFloat_FromDouble(secs as f64 * 1e6 + nanos as f64 * 1e-3)
}

unsafe extern "C" fn in_milliseconds(slf: *mut PyObject, _: *mut PyObject) -> *mut PyObject {
    let TimeDelta { secs, nanos } = TimeDelta::extract(slf);
    PyFloat_FromDouble(secs as f64 * 1e3 + nanos as f64 * 1e-6)
}

unsafe extern "C" fn in_seconds(slf: *mut PyObject, _: *mut PyObject) -> *mut PyObject {
    let TimeDelta { secs, nanos } = TimeDelta::extract(slf);
    PyFloat_FromDouble(secs as f64 + nanos as f64 * 1e-9)
}

unsafe extern "C" fn in_minutes(slf: *mut PyObject, _: *mut PyObject) -> *mut PyObject {
    let TimeDelta { secs, nanos } = TimeDelta::extract(slf);
    PyFloat_FromDouble(secs as f64 / 60.0 + nanos as f64 * 1e-9 / 60.0)
}

unsafe extern "C" fn in_hours(slf: *mut PyObject, _: *mut PyObject) -> *mut PyObject {
    let TimeDelta { secs, nanos } = TimeDelta::extract(slf);
    PyFloat_FromDouble(secs as f64 / 3600.0 + nanos as f64 * 1e-9 / 3600.0)
}

unsafe extern "C" fn in_days_of_24h(slf: *mut PyObject, _: *mut PyObject) -> *mut PyObject {
    let TimeDelta { secs, nanos } = TimeDelta::extract(slf);
    PyFloat_FromDouble(secs as f64 / 86_400.0 + nanos as f64 * 1e-9 / 86_400.0)
}

unsafe extern "C" fn from_py_timedelta(cls: *mut PyObject, d: *mut PyObject) -> *mut PyObject {
    if PyDelta_Check(d) == 0 {
        raise!(PyExc_TypeError, "argument must be datetime.timedelta");
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

unsafe extern "C" fn py_timedelta(slf: *mut PyObject, _: *mut PyObject) -> *mut PyObject {
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
        micros = micros % 1_000_000;
    }
    let sign = if secs >= 0 { 1 } else { -1 };
    Delta_FromDelta(
        (secs.div_euclid(SECS_PER_DAY * sign) * sign) as _,
        secs.rem_euclid(SECS_PER_DAY * sign) as _,
        micros,
        0,
        DeltaType,
    )
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

unsafe extern "C" fn from_default_format(
    cls: *mut PyObject,
    s_obj: *mut PyObject,
) -> *mut PyObject {
    let s = &mut pystr_to_utf8!(s_obj, "argument must be a string");
    let sign = unwrap_or_raise!(
        (s.len() > 8).then(|| parse_prefix(s)).flatten(),
        PyExc_ValueError,
        "Invalid time delta format: %R",
        s_obj
    );
    let (hours, (mins, secs, nanos)) = unwrap_or_raise!(
        parse_hours(s).zip(parse_mins_secs_nanos(s)),
        PyExc_ValueError,
        "Invalid time delta format: %R",
        s_obj
    );
    new_unchecked(
        cls.cast(),
        unwrap_or_raise!(
            TimeDelta::from_nanos(
                sign * ((hours as i64 * 3600 + mins as i64 * 60 + secs as i64) as i128
                    * 1_000_000_000
                    + nanos as i128),
            ),
            PyExc_ValueError,
            "Time delta out of range"
        ),
    )
}

unsafe extern "C" fn as_tuple(slf: *mut PyObject, _: *mut PyObject) -> *mut PyObject {
    let delta = TimeDelta::extract(slf);

    let (secs, nanos) = if delta.secs >= 0 {
        (delta.secs, delta.nanos as i32)
    } else if delta.nanos == 0 {
        (delta.secs, 0)
    } else {
        (delta.secs + 1, delta.nanos as i32 - 1_000_000_000)
    };
    PyTuple_Pack(
        4,
        PyLong_FromLongLong((secs / 3_600).into()),
        PyLong_FromLong((secs % 3_600 / 60).into()),
        PyLong_FromLong((secs % 60).into()),
        PyLong_FromLong(nanos as _),
    )
}

unsafe extern "C" fn common_iso8601(slf: *mut PyObject, _: *mut PyObject) -> *mut PyObject {
    let mut delta = TimeDelta::extract(slf);
    if delta.secs == 0 && delta.nanos == 0 {
        return py_str("PT0S");
    }
    let mut s: String = String::with_capacity(4);
    if delta.secs < 0 {
        s.push('-');
        delta = -delta;
    }
    s.push_str("PT");
    let hours = delta.secs / 3600;
    let minutes = delta.secs / 60 % 60;
    let seconds = delta.secs % 60;
    if hours != 0 {
        s.push_str(&format!("{}H", hours));
    }
    if minutes != 0 {
        s.push_str(&format!("{}M", minutes));
    }
    match (seconds, delta.nanos) {
        (0, 0) => {}
        (_, 0) => s.push_str(&format!("{}S", seconds)),
        _ => {
            s.push_str(&format!("{}.{:09}", seconds, delta.nanos).trim_end_matches('0'));
            s.push('S');
        }
    }
    py_str(s.as_str())
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
                    .and_then(|ns| Some((tally * 1_000_000_000 + ns, Unit::Nanoseconds)));
                *s = &[];
                return result;
            }
            _ => break,
        }
    }
    None
}

unsafe extern "C" fn from_common_iso8601(
    cls: *mut PyObject,
    s_obj: *mut PyObject,
) -> *mut PyObject {
    let s = &mut pystr_to_utf8!(s_obj, "argument must be a string");
    let sign = unwrap_or_raise!(
        (s.len() >= 4).then(|| parse_prefix(s)).flatten(),
        PyExc_ValueError,
        "Invalid time delta format: %R",
        s_obj
    );
    let mut total_ns = 0;
    let mut prev_unit: Option<Unit> = None;

    while s.len() > 0 {
        if let Some((value, unit)) = parse_component(s) {
            match (unit, prev_unit.replace(unit)) {
                (Unit::Hours, None) => {
                    total_ns += value * 3_600_000_000_000;
                }
                (Unit::Minutes, None | Some(Unit::Hours)) => {
                    total_ns += value * 60_000_000_000;
                }
                (Unit::Nanoseconds, _) => {
                    total_ns += value;
                    if s.is_empty() {
                        break;
                    }
                    // i.e. there's still something left after the nanoseconds
                    raise!(PyExc_ValueError, "Invalid time delta format: %R", s_obj);
                }
                _ => {
                    // i.e. the order of the components is wrong
                    raise!(PyExc_ValueError, "Invalid time delta format: %R", s_obj);
                }
            }
        } else {
            // i.e. the component parsing failed
            raise!(PyExc_ValueError, "Invalid time delta format: %R", s_obj);
        }
    }

    // i.e. there must be at least one component (`PT` alone is invalid)
    if prev_unit.is_none() {
        raise!(PyExc_ValueError, "Invalid time delta format: %R", s_obj);
    }

    new_unchecked(
        cls.cast(),
        unwrap_or_raise!(
            TimeDelta::from_nanos(total_ns * sign),
            PyExc_ValueError,
            "Time delta out of range"
        ),
    )
}

static mut METHODS: &[PyMethodDef] = &[
    method!(identity named "__copy__", ""),
    method!(identity named "__deepcopy__", "", METH_O),
    method!(default_format, "Format the time delta in the default way"),
    method!(
        common_iso8601,
        "Return the time delta in the common ISO8601 format"
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
    classmethod!(
        from_py_timedelta,
        "Create a date from a Python datetime.timedelta",
        METH_O
    ),
    method!(py_timedelta, "Convert to a Python datetime.timedelta"),
    classmethod!(
        from_default_format,
        "Parse from the default string representation",
        METH_O
    ),
    classmethod!(
        from_common_iso8601,
        "Parse from the common ISO8601 period format",
        METH_O
    ),
    method!(as_tuple, "Return the date delta as a tuple"),
    method!(__reduce__, ""),
    PyMethodDef::zeroed(),
];

pub(crate) unsafe fn new_unchecked(type_: *mut PyTypeObject, d: TimeDelta) -> *mut PyObject {
    let f: allocfunc = (*type_).tp_alloc.expect("tp_alloc is not set");
    let slf = py_try!(f(type_, 0).cast::<PyTimeDelta>());
    ptr::addr_of_mut!((*slf).delta).write(d);
    slf.cast()
}

pub(crate) static mut SPEC: PyType_Spec = PyType_Spec {
    name: c_str!("whenever.TimeDelta"),
    basicsize: mem::size_of::<PyTimeDelta>() as _,
    itemsize: 0,
    flags: Py_TPFLAGS_DEFAULT as _,
    slots: unsafe { SLOTS as *const [_] as *mut _ },
};
