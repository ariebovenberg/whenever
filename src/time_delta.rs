use core::ffi::{c_char, c_double, c_int, c_void};
use core::{mem, ptr};
use pyo3_ffi::*;
use std::cmp::min;
use std::fmt;
use std::ops::Neg;
use std::ptr::null_mut as NULL;

use crate::common::{
    c_str, get_digit, propagate_exc, py_str, pystr_to_utf8, raise, try_get_float, try_get_int,
};
use crate::date::MAX_YEAR;
use crate::ModuleState;

// TODO: hide the constructors
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

    pub(crate) const fn total_nanos(&self) -> i128 {
        self.secs as i128 * 1_000_000_000 + self.nanos as i128
    }
}

#[repr(C)]
pub(crate) struct PyTimeDelta {
    _ob_base: PyObject,
    pub(crate) delta: TimeDelta,
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
            "{:02}:{:02}:{:02}",
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
const SECONDS_PER_DAY: i64 = 24 * 3600;

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

// impl fmt::Display for TimeDelta {
//     fn fmt(&self, f: &mut fmt::Formatter<'_>) -> fmt::Result {
//         let content = [
//             if self.years != 0 {
//                 format!("{}Y", self.years)
//             } else {
//                 String::new()
//             },
//             if self.months != 0 {
//                 format!("{}M", self.months)
//             } else {
//                 String::new()
//             },
//             if self.weeks != 0 {
//                 format!("{}W", self.weeks)
//             } else {
//                 String::new()
//             },
//             if self.days != 0 {
//                 format!("{}D", self.days)
//             } else {
//                 String::new()
//             },
//         ]
//         .join("");
//         write!(f, "P{}", if content.is_empty() { "0D" } else { &content })
//     }
// }
//

macro_rules! handle_unit(
    ($obj:expr, $unit:expr, $max:expr, $num_nanos:expr) => {{
        if PyLong_Check($obj) != 0 {
            let i = try_get_int!($obj);
            if i < -$max || i > $max {
                raise!(PyExc_ValueError, concat!($unit, " out of range"));
            }
            i as i128 * $num_nanos
        } else {
            let f = try_get_float!($obj);
            if f < -$max as _ || f > $max as _ || f.is_nan() {
                raise!(PyExc_ValueError, concat!($unit, " out of range"));
            }
            (f * $num_nanos as f64) as i128
        }
    }}
);

macro_rules! try_get_int128(
    ($o:expr, $errmsg:expr) => {{
        let mut bytes: [u8; 16] = [0; 16];
        if _PyLong_AsByteArray($o, &mut bytes as *mut _, 16, 1, 1) != 0 {
            raise!(PyExc_ValueError, $errmsg);
        }
        i128::from_le_bytes(bytes)
    }}
);

unsafe fn py_int128(n: i128) -> *mut PyObject {
    _PyLong_FromByteArray(
        n.to_le_bytes().as_ptr().cast(),
        mem::size_of::<i128>(),
        1,
        1,
    )
}

unsafe extern "C" fn __new__(
    subtype: *mut PyTypeObject,
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

    let delta = match (nargs, nkwargs) {
        (0, 0) => TimeDelta { secs: 0, nanos: 0 }, // FUTURE: return the singleton
        (0, _) => {
            let mut key: *mut PyObject = NULL();
            let mut value: *mut PyObject = NULL();
            let mut pos: Py_ssize_t = 0;
            while PyDict_Next(kwargs, &mut pos, &mut key, &mut value) != 0 {
                match pystr_to_utf8!(key, "Kwargs keys must be str") {
                    b"hours" => {
                        nanos += handle_unit!(value, "hours", MAX_HOURS, 3600_000_000_000i128);
                    }
                    b"minutes" => {
                        nanos += handle_unit!(value, "minutes", MAX_MINUTES, 60_000_000_000i128);
                    }
                    b"seconds" => {
                        nanos += handle_unit!(value, "seconds", MAX_SECS, 1_000_000_000i128);
                    }
                    b"milliseconds" => {
                        nanos +=
                            handle_unit!(value, "milliseconds", MAX_MILLISECONDS, 1_000_000i128);
                    }
                    b"microseconds" => {
                        nanos += handle_unit!(value, "microseconds", MAX_MICROSECONDS, 1_000i128);
                    }
                    b"nanoseconds" => {
                        if PyLong_Check(value) == 0 {
                            raise!(PyExc_TypeError, concat!("nanoseconds must be an integer"));
                        }
                        nanos += try_get_int128!(value.cast(), "nanoseconds out of range");
                    }
                    _ => {
                        raise!(
                            PyExc_TypeError,
                            "TimeDelta() got an unexpected keyword argument: %R",
                            key
                        );
                    }
                }
            }
            if nanos < -MAX_NANOSECONDS || nanos > MAX_NANOSECONDS {
                raise!(PyExc_ValueError, "Total TimeDelta() size out of range");
            }
            TimeDelta {
                secs: (nanos.div_euclid(1_000_000_000)) as _,
                nanos: (nanos.rem_euclid(1_000_000_000)) as _,
            }
        }
        _ => raise!(PyExc_TypeError, "TimeDelta() takes no positional arguments"),
    };
    new_unchecked(subtype, delta).cast()
}

pub(crate) unsafe extern "C" fn hours(
    module: *mut PyObject,
    amount: *mut PyObject,
) -> *mut PyObject {
    new_unchecked(
        (*PyModule_GetState(module).cast::<crate::ModuleState>()).time_delta_type,
        TimeDelta::from_nanos_unchecked(handle_unit!(
            amount,
            "hours",
            MAX_HOURS,
            3600_000_000_000i128
        )),
    )
    .cast()
}

pub(crate) unsafe extern "C" fn minutes(
    module: *mut PyObject,
    amount: *mut PyObject,
) -> *mut PyObject {
    new_unchecked(
        (*PyModule_GetState(module).cast::<crate::ModuleState>()).time_delta_type,
        TimeDelta::from_nanos_unchecked(handle_unit!(
            amount,
            "minutes",
            MAX_MINUTES,
            60_000_000_000i128
        )),
    )
    .cast()
}

pub(crate) unsafe extern "C" fn seconds(
    module: *mut PyObject,
    amount: *mut PyObject,
) -> *mut PyObject {
    new_unchecked(
        (*PyModule_GetState(module).cast::<crate::ModuleState>()).time_delta_type,
        TimeDelta::from_nanos_unchecked(handle_unit!(
            amount,
            "seconds",
            MAX_SECS,
            1_000_000_000i128
        )),
    )
    .cast()
}

pub(crate) unsafe extern "C" fn milliseconds(
    module: *mut PyObject,
    amount: *mut PyObject,
) -> *mut PyObject {
    new_unchecked(
        (*PyModule_GetState(module).cast::<crate::ModuleState>()).time_delta_type,
        TimeDelta::from_nanos_unchecked(handle_unit!(
            amount,
            "milliseconds",
            MAX_MILLISECONDS,
            1_000_000i128
        )),
    )
    .cast()
}

pub(crate) unsafe extern "C" fn microseconds(
    module: *mut PyObject,
    amount: *mut PyObject,
) -> *mut PyObject {
    new_unchecked(
        (*PyModule_GetState(module).cast::<crate::ModuleState>()).time_delta_type,
        TimeDelta::from_nanos_unchecked(handle_unit!(
            amount,
            "microseconds",
            MAX_MICROSECONDS,
            1_000i128
        )),
    )
    .cast()
}

pub(crate) unsafe extern "C" fn nanoseconds(
    module: *mut PyObject,
    amount: *mut PyObject,
) -> *mut PyObject {
    if PyLong_Check(amount) == 0 {
        raise!(PyExc_TypeError, "nanoseconds must be an integer");
    }
    let mut bytes: [u8; 16] = [0; 16];
    if _PyLong_AsByteArray(amount.cast(), &mut bytes as *mut _, 16, 1, 1) == 0 {
        new_unchecked(
            (*PyModule_GetState(module).cast::<crate::ModuleState>()).time_delta_type,
            TimeDelta::from_nanos_unchecked(i128::from_le_bytes(bytes)),
        )
        .cast()
    } else {
        raise!(PyExc_ValueError, "nanoseconds out of range");
    }
}

unsafe extern "C" fn richcmp(slf: *mut PyObject, other: *mut PyObject, op: c_int) -> *mut PyObject {
    let result = if Py_TYPE(other) != Py_TYPE(slf) {
        Py_NotImplemented()
    } else {
        let slf = (*slf.cast::<PyTimeDelta>()).delta;
        let other = (*other.cast::<PyTimeDelta>()).delta;
        let cmp = match op {
            pyo3_ffi::Py_EQ => slf == other,
            pyo3_ffi::Py_NE => slf != other,
            pyo3_ffi::Py_LT => slf < other,
            pyo3_ffi::Py_LE => slf <= other,
            pyo3_ffi::Py_GT => slf > other,
            pyo3_ffi::Py_GE => slf >= other,
            _ => unreachable!(),
        };
        if cmp {
            Py_True()
        } else {
            Py_False()
        }
    };
    Py_INCREF(result);
    result
}

// TODO: hash can never be -1? Check this can never be the case
unsafe extern "C" fn __hash__(slf: *mut PyObject) -> Py_hash_t {
    let delta = (*slf.cast::<PyTimeDelta>()).delta;
    #[cfg(target_pointer_width = "64")]
    {
        delta.nanos as Py_hash_t ^ delta.secs as Py_hash_t
    }
    #[cfg(target_pointer_width = "32")]
    {
        delta.nanos as Py_hash_t ^ delta.secs as Py_hash_t ^ (delta.secs >> 32) as Py_hash_t
    }
}

unsafe extern "C" fn __neg__(slf: *mut PyObject) -> *mut PyObject {
    let delta = (*slf.cast::<PyTimeDelta>()).delta;
    new_unchecked(Py_TYPE(slf), -delta).cast()
}

unsafe extern "C" fn __bool__(slf: *mut PyObject) -> c_int {
    let delta = (*slf.cast::<PyTimeDelta>()).delta;
    (delta.secs != 0 || delta.nanos != 0) as c_int
}

unsafe extern "C" fn __repr__(slf: *mut PyObject) -> *mut PyObject {
    let delta = (*slf.cast::<PyTimeDelta>()).delta;
    py_str(format!("TimeDelta({})", delta).as_str())
}

unsafe extern "C" fn __str__(slf: *mut PyObject) -> *mut PyObject {
    let delta = (*slf.cast::<PyTimeDelta>()).delta;
    py_str(format!("{}", delta).as_str())
}

unsafe extern "C" fn __mul__(slf: *mut PyObject, factor_obj: *mut PyObject) -> *mut PyObject {
    let new = if PyLong_Check(factor_obj) != 0 {
        let factor = try_get_int128!(factor_obj.cast(), "Multiplication factor out of range");
        if factor == 1 {
            Py_INCREF(slf);
            return slf;
        }
        let delta = (*slf.cast::<PyTimeDelta>()).delta;
        let total_ns: i128 = delta.nanos as i128 + delta.secs as i128 * 1_000_000_000;

        match total_ns.checked_mul(factor) {
            Some(ns) if MAX_NANOSECONDS > ns && ns > -MAX_NANOSECONDS => {
                TimeDelta::from_nanos_unchecked(ns)
            }
            _ => raise!(PyExc_ValueError, "Multiplication result out of range"),
        }
    } else if PyFloat_Check(factor_obj) != 0 {
        let factor = try_get_float!(factor_obj);
        if factor == 1.0 {
            Py_INCREF(slf);
            return slf;
        }
        let mut nanos = (*slf.cast::<PyTimeDelta>()).delta.secs as f64 * 1e9
            + (*slf.cast::<PyTimeDelta>()).delta.nanos as f64;
        nanos *= factor;
        if nanos.is_nan() || (MAX_NANOSECONDS as f64) < nanos || nanos < -MAX_NANOSECONDS as f64 {
            raise!(PyExc_ValueError, "Multiplication result out of range");
        };
        TimeDelta::from_nanos_unchecked(nanos as i128)
    } else {
        let result = Py_NotImplemented();
        Py_INCREF(result);
        return result;
    };
    new_unchecked(Py_TYPE(slf), new).cast()
}

unsafe extern "C" fn __truediv__(slf: *mut PyObject, factor_obj: *mut PyObject) -> *mut PyObject {
    // get the factor, complicated by the fact that it can be a float,
    // or even a >i64::MAX integer

    let new = if PyLong_Check(factor_obj) != 0 {
        let factor = try_get_int128!(factor_obj.cast(), "Division factor out of range");
        if factor == 1 {
            Py_INCREF(slf);
            return slf;
        } else if factor == 0 {
            raise!(PyExc_ZeroDivisionError, "Division by zero");
        }
        let nanos = (*slf.cast::<PyTimeDelta>()).delta.total_nanos();
        TimeDelta::from_nanos_unchecked(if nanos % factor == 0 {
            nanos / factor
        } else {
            (nanos as f64 / factor as f64).round() as i128
        })
    } else if PyFloat_Check(factor_obj) != 0 {
        let factor = try_get_float!(factor_obj);
        if factor == 1.0 {
            Py_INCREF(slf);
            return slf;
        } else if factor == 0.0 {
            raise!(PyExc_ZeroDivisionError, "Division by zero");
        }
        let mut nanos = (*slf.cast::<PyTimeDelta>()).delta.total_nanos() as f64;
        nanos /= factor;
        if nanos.is_nan() || (MAX_NANOSECONDS as f64) < nanos || nanos < -MAX_NANOSECONDS as f64 {
            raise!(PyExc_ValueError, "Division result out of range");
        };
        TimeDelta::from_nanos_unchecked(nanos as i128)
    } else if Py_TYPE(factor_obj) == Py_TYPE(slf) {
        let factor = (*factor_obj.cast::<PyTimeDelta>()).delta.total_nanos();
        if factor == 0 {
            raise!(PyExc_ZeroDivisionError, "Division by zero");
        }
        let nanos = (*slf.cast::<PyTimeDelta>()).delta.total_nanos();
        return PyFloat_FromDouble(nanos as f64 / factor as f64);
    } else {
        let result = Py_NotImplemented();
        Py_INCREF(result);
        return result;
    };
    new_unchecked(Py_TYPE(slf), new).cast()
}

unsafe extern "C" fn __add__(slf: *mut PyObject, other: *mut PyObject) -> *mut PyObject {
    if Py_TYPE(other) != Py_TYPE(slf) {
        let result = Py_NotImplemented();
        Py_INCREF(result);
        return result;
    }
    let a = (*slf.cast::<PyTimeDelta>()).delta.total_nanos();
    let b = (*other.cast::<PyTimeDelta>()).delta.total_nanos();
    new_unchecked(
        Py_TYPE(slf),
        match TimeDelta::from_nanos(a + b) {
            Some(d) => d,
            None => raise!(PyExc_ValueError, "Addition result out of range"),
        },
    )
    .cast()
}

unsafe extern "C" fn __sub__(slf: *mut PyObject, other: *mut PyObject) -> *mut PyObject {
    if Py_TYPE(other) != Py_TYPE(slf) {
        let result = Py_NotImplemented();
        Py_INCREF(result);
        return result;
    }
    let a = (*slf.cast::<PyTimeDelta>()).delta.total_nanos();
    let b = (*other.cast::<PyTimeDelta>()).delta.total_nanos();
    new_unchecked(
        Py_TYPE(slf),
        match TimeDelta::from_nanos(a - b) {
            Some(d) => d,
            None => raise!(PyExc_ValueError, "Subtraction result out of range"),
        },
    )
    .cast()
}

unsafe extern "C" fn __abs__(slf: *mut PyObject) -> *mut PyObject {
    let delta = (*slf.cast::<PyTimeDelta>()).delta;
    if delta.secs >= 0 {
        Py_INCREF(slf);
        slf
    } else {
        new_unchecked(Py_TYPE(slf), -delta).cast()
    }
}

static mut SLOTS: &[PyType_Slot] = &[
    PyType_Slot {
        slot: Py_tp_new,
        pfunc: __new__ as *mut c_void,
    },
    PyType_Slot {
        slot: Py_tp_doc,
        pfunc: "A calendar date type\0".as_ptr() as *mut c_void,
    },
    PyType_Slot {
        slot: Py_tp_methods,
        pfunc: unsafe { METHODS.as_ptr() as *mut c_void },
    },
    PyType_Slot {
        slot: Py_tp_richcompare,
        pfunc: richcmp as *mut c_void,
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

unsafe extern "C" fn identity(slf: *mut PyObject, _: *mut PyObject) -> *mut PyObject {
    Py_INCREF(slf);
    slf
}

unsafe extern "C" fn canonical_format(slf: *mut PyObject, _: *mut PyObject) -> *mut PyObject {
    __str__(slf)
}

unsafe extern "C" fn __reduce__(
    slf: *mut PyObject,
    type_: *mut PyTypeObject,
    // All args are unused. We don't need to check this since __reduce__
    // is only called internally by pickle (without arguments).
    _: *const *mut PyObject,
    _: Py_ssize_t,
    _: *mut PyObject,
) -> *mut PyObject {
    let delta = (*slf.cast::<PyTimeDelta>()).delta;
    PyTuple_Pack(
        2,
        (*ModuleState::from(type_)).unpickle_time_delta,
        propagate_exc!(PyTuple_Pack(
            2,
            PyLong_FromLongLong(delta.secs.into()),
            PyLong_FromLong(delta.nanos.into()),
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
        (*PyModule_GetState(module).cast::<crate::ModuleState>()).time_delta_type,
        TimeDelta {
            secs: try_get_int!(*args.offset(0)) as _,
            nanos: try_get_int!(*args.offset(1)) as _,
        },
    )
    .cast()
}

unsafe extern "C" fn in_nanoseconds(slf: *mut PyObject, _: *mut PyObject) -> *mut PyObject {
    py_int128((*slf.cast::<PyTimeDelta>()).delta.total_nanos())
}

unsafe extern "C" fn in_microseconds(slf: *mut PyObject, _: *mut PyObject) -> *mut PyObject {
    let delta = (*slf.cast::<PyTimeDelta>()).delta;
    let n = delta.secs as f64 * 1e6 + delta.nanos as f64 * 1e-3;
    PyFloat_FromDouble(n as c_double)
}

unsafe extern "C" fn in_milliseconds(slf: *mut PyObject, _: *mut PyObject) -> *mut PyObject {
    let delta = (*slf.cast::<PyTimeDelta>()).delta;
    let n = delta.secs as f64 * 1e3 + delta.nanos as f64 * 1e-6;
    PyFloat_FromDouble(n as c_double)
}

unsafe extern "C" fn in_seconds(slf: *mut PyObject, _: *mut PyObject) -> *mut PyObject {
    let delta = (*slf.cast::<PyTimeDelta>()).delta;
    let n = delta.secs as f64 + delta.nanos as f64 * 1e-9;
    PyFloat_FromDouble(n as c_double)
}

unsafe extern "C" fn in_minutes(slf: *mut PyObject, _: *mut PyObject) -> *mut PyObject {
    let delta = (*slf.cast::<PyTimeDelta>()).delta;
    let n = delta.secs as f64 / 60.0 + delta.nanos as f64 * 1e-9 / 60.0;
    PyFloat_FromDouble(n as c_double)
}

unsafe extern "C" fn in_hours(slf: *mut PyObject, _: *mut PyObject) -> *mut PyObject {
    let delta = (*slf.cast::<PyTimeDelta>()).delta;
    let n = delta.secs as f64 / 3600.0 + delta.nanos as f64 * 1e-9 / 3600.0;
    PyFloat_FromDouble(n as c_double)
}

unsafe extern "C" fn in_days_of_24h(slf: *mut PyObject, _: *mut PyObject) -> *mut PyObject {
    let delta = (*slf.cast::<PyTimeDelta>()).delta;
    let n = delta.secs as f64 / 86_400.0 + delta.nanos as f64 * 1e-9 / 86_400.0;
    PyFloat_FromDouble(n as c_double)
}

unsafe extern "C" fn from_py_timedelta(cls: *mut PyObject, d: *mut PyObject) -> *mut PyObject {
    // TODO: allow subclasses?
    if PyDelta_Check(d) == 0 {
        raise!(PyExc_TypeError, "argument must be datetime.timedelta");
    }
    new_unchecked(
        cls.cast(),
        TimeDelta {
            secs: PyDateTime_DELTA_GET_DAYS(d) as i64 * 24 * 3600
                + PyDateTime_DELTA_GET_SECONDS(d) as i64,
            nanos: PyDateTime_DELTA_GET_MICROSECONDS(d) as u32 * 1_000,
        },
    )
    .cast()
}

unsafe extern "C" fn py_timedelta(slf: *mut PyObject, _: *mut PyObject) -> *mut PyObject {
    let delta = (*slf.cast::<PyTimeDelta>()).delta;
    let py_api = *(*ModuleState::from(Py_TYPE(slf))).datetime_api;

    // a whole circus just to round nanoseconds...
    let mut micros = (delta.nanos / 1_000) as i32;
    let mut secs = delta.secs;
    if delta.nanos % 1_000 >= 500 {
        micros += 1;
        secs += (micros / 1_000_000) as i64;
        micros = micros % 1_000_000;
    }
    let sign = if secs >= 0 { 1 } else { -1 };
    (py_api.Delta_FromDelta)(
        (secs.div_euclid(SECONDS_PER_DAY * sign) * sign) as _,
        secs.rem_euclid(SECONDS_PER_DAY * sign) as _,
        micros,
        0,
        py_api.DeltaType,
    )
    .cast()
}

// H[HHHHHH]:<rest> -> (H..., <rest>)
fn parse_hours(s: &[u8]) -> Option<(u32, &[u8])> {
    let mut hours = get_digit!(s, 0) as u32;
    // limit parsing to 8 characters in total to prevent overflow
    for i in 1..min(s.len(), 7) {
        match s[i] {
            c if c.is_ascii_digit() => hours = hours * 10 + (c - b'0') as u32,
            b':' => return Some((hours, &s[i + 1..])),
            _ => return None,
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
            nanos += ((i - b'0') as u32) * factor;
            // TODO: check extra digits?
        }
    }
    Some((minutes, seconds, nanos))
}

unsafe extern "C" fn from_canonical_format(
    cls: *mut PyObject,
    s_obj: *mut PyObject,
) -> *mut PyObject {
    let s = pystr_to_utf8!(s_obj, "argument must be a string");
    if s.len() < 7 {
        // at least `H:MM:SS`
        raise!(PyExc_ValueError, "Invalid time delta format: %R", s_obj);
    }
    let (sign, rest) = match s[0] {
        b'-' => (-1, &s[1..]),
        b'+' => (1, &s[1..]),
        _ => (1, s),
    };
    let (hours, rest) = match parse_hours(rest) {
        Some((h, r)) => (h, r),
        None => raise!(PyExc_ValueError, "Invalid time delta format: %R", s_obj),
    };
    let (minutes, seconds, nanos) = match parse_mins_secs_nanos(rest) {
        Some((m, s, r)) => (m, s, r),
        None => raise!(PyExc_ValueError, "Invalid time delta format: %R", s_obj),
    };

    new_unchecked(
        cls.cast(),
        match TimeDelta::from_nanos(
            sign * ((hours as i64 * 3600 + minutes as i64 * 60 + seconds as i64) as i128
                * 1_000_000_000
                + nanos as i128),
        ) {
            Some(d) => d,
            None => raise!(PyExc_ValueError, "Time delta out of range"),
        },
    )
    .cast()
}

unsafe extern "C" fn as_tuple(slf: *mut PyObject, _: *mut PyObject) -> *mut PyObject {
    let delta = (*slf.cast::<PyTimeDelta>()).delta;

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
    let mut delta = (*slf.cast::<PyTimeDelta>()).delta;
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

// `PT`, `-PT`
fn parse_prefix(s: &[u8]) -> Option<(bool, &[u8])> {
    match s[0] {
        b'-' if &s[1..3] == b"PT" => Some((true, &s[3..])),
        b'+' if &s[1..3] == b"PT" => Some((false, &s[3..])),
        b'P' if s[1] == b'T' => Some((false, &s[2..])),
        _ => None,
    }
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
                tally += ((c - b'0') as i128) * 10_u32.pow(8 - i as u32) as i128
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
fn parse_component(s: &[u8]) -> Option<(i128, Unit, &[u8])> {
    if s.len() < 2 {
        return None;
    }
    let mut tally: i128 = 0;
    // We limit parsing to 35 characters to prevent overflow of i128
    for i in 0..min(s.len(), 35) {
        match s[i] {
            c if c.is_ascii_digit() => tally = tally * 10 + (c - b'0') as i128,
            b'H' => return Some((tally, Unit::Hours, &s[i + 1..])),
            b'M' => return Some((tally, Unit::Minutes, &s[i + 1..])),
            b'S' => return Some((tally * 1_000_000_000, Unit::Nanoseconds, &s[i + 1..])),
            b'.' => {
                return parse_nano_fractions(&s[i + 1..]).and_then(|ns| {
                    Some((tally * 1_000_000_000 + ns, Unit::Nanoseconds, &[] as &[u8]))
                })
            }
            _ => return None,
        }
    }
    None
}

unsafe extern "C" fn from_common_iso8601(
    cls: *mut PyObject,
    s_obj: *mut PyObject,
) -> *mut PyObject {
    let s = pystr_to_utf8!(s_obj, "argument must be a string");
    if s.len() < 4 {
        // at least "PT" plus one digit and a unit
        raise!(PyExc_ValueError, "Invalid time delta format: %R", s_obj);
    };
    let mut total_ns = 0;
    let mut prev_unit: Option<Unit> = None;

    let (negated, mut s) = match parse_prefix(s) {
        Some((neg, rest)) => (neg, rest),
        None => raise!(PyExc_ValueError, "Invalid time delta format: %R", s_obj),
    };

    while s.len() > 0 {
        // FUTURE: there's still some optimization to be done here...
        if let Some((value, unit, rest)) = parse_component(s) {
            match (unit, prev_unit.replace(unit)) {
                (Unit::Hours, None) => {
                    total_ns += value * 3_600_000_000_000;
                }
                (Unit::Minutes, None | Some(Unit::Hours)) => {
                    total_ns += value * 60_000_000_000;
                }
                (Unit::Nanoseconds, _) => {
                    total_ns += value;
                    if rest.is_empty() {
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
            s = rest;
        } else {
            // i.e. the component parsing failed
            raise!(PyExc_ValueError, "Invalid time delta format: %R", s_obj);
        }
    }

    // i.e. there must be at least one component (`PT` alone is invalid)
    if prev_unit.is_none() {
        raise!(PyExc_ValueError, "Invalid time delta format: %R", s_obj);
    }
    match TimeDelta::from_nanos(if negated { -total_ns } else { total_ns }) {
        Some(d) => new_unchecked(cls.cast(), d).cast(),
        None => raise!(PyExc_ValueError, "Time delta out of range"),
    }
}

static mut METHODS: &[PyMethodDef] = &[
    PyMethodDef {
        ml_name: c_str!("__copy__"),
        ml_meth: PyMethodDefPointer {
            PyCFunction: identity,
        },
        ml_flags: METH_NOARGS,
        ml_doc: NULL(),
    },
    PyMethodDef {
        ml_name: c_str!("__deepcopy__"),
        ml_meth: PyMethodDefPointer {
            PyCFunction: identity,
        },
        ml_flags: METH_O,
        ml_doc: NULL(),
    },
    PyMethodDef {
        ml_name: c_str!("canonical_format"),
        ml_meth: PyMethodDefPointer {
            PyCFunction: canonical_format,
        },
        ml_flags: METH_NOARGS,
        ml_doc: c_str!("Return the canonical string representation"),
    },
    PyMethodDef {
        ml_name: c_str!("common_iso8601"),
        ml_meth: PyMethodDefPointer {
            PyCFunction: common_iso8601,
        },
        ml_flags: METH_NOARGS,
        ml_doc: c_str!("Return the ISO 8601 string representation"),
    },
    PyMethodDef {
        ml_name: c_str!("in_nanoseconds"),
        ml_meth: PyMethodDefPointer {
            PyCFunction: in_nanoseconds,
        },
        ml_flags: METH_NOARGS,
        ml_doc: c_str!("Return the total number of nanoseconds"),
    },
    PyMethodDef {
        ml_name: c_str!("in_microseconds"),
        ml_meth: PyMethodDefPointer {
            PyCFunction: in_microseconds,
        },
        ml_flags: METH_NOARGS,
        ml_doc: c_str!("Return the total number of microseconds"),
    },
    PyMethodDef {
        ml_name: c_str!("in_milliseconds"),
        ml_meth: PyMethodDefPointer {
            PyCFunction: in_milliseconds,
        },
        ml_flags: METH_NOARGS,
        ml_doc: c_str!("Return the total number of milliseconds"),
    },
    PyMethodDef {
        ml_name: c_str!("in_seconds"),
        ml_meth: PyMethodDefPointer {
            PyCFunction: in_seconds,
        },
        ml_flags: METH_NOARGS,
        ml_doc: c_str!("Return the total number of seconds"),
    },
    PyMethodDef {
        ml_name: c_str!("in_minutes"),
        ml_meth: PyMethodDefPointer {
            PyCFunction: in_minutes,
        },
        ml_flags: METH_NOARGS,
        ml_doc: c_str!("Return the total number of minutes"),
    },
    PyMethodDef {
        ml_name: c_str!("in_hours"),
        ml_meth: PyMethodDefPointer {
            PyCFunction: in_hours,
        },
        ml_flags: METH_NOARGS,
        ml_doc: c_str!("Return the total number of hours"),
    },
    PyMethodDef {
        ml_name: c_str!("in_days_of_24h"),
        ml_meth: PyMethodDefPointer {
            PyCFunction: in_days_of_24h,
        },
        ml_flags: METH_NOARGS,
        ml_doc: c_str!("Return the total number of days, assuming 24 hours per day"),
    },
    PyMethodDef {
        ml_name: c_str!("from_py_timedelta"),
        ml_meth: PyMethodDefPointer {
            PyCFunction: from_py_timedelta,
        },
        ml_flags: METH_O | METH_CLASS,
        ml_doc: c_str!("Create a date from a Python datetime.timedelta"),
    },
    PyMethodDef {
        ml_name: c_str!("py_timedelta"),
        ml_meth: PyMethodDefPointer {
            PyCFunction: py_timedelta,
        },
        ml_flags: METH_NOARGS,
        ml_doc: c_str!("Convert to a Python datetime.timedelta"),
    },
    PyMethodDef {
        ml_name: c_str!("from_canonical_format"),
        ml_meth: PyMethodDefPointer {
            PyCFunction: from_canonical_format,
        },
        ml_flags: METH_O | METH_CLASS,
        ml_doc: c_str!("Parse from the canonical string representation"),
    },
    PyMethodDef {
        ml_name: c_str!("from_common_iso8601"),
        ml_meth: PyMethodDefPointer {
            PyCFunction: from_common_iso8601,
        },
        ml_flags: METH_O | METH_CLASS,
        ml_doc: c_str!("Parse from the common ISO8601 period format"),
    },
    PyMethodDef {
        ml_name: c_str!("as_tuple"),
        ml_meth: PyMethodDefPointer {
            PyCFunction: as_tuple,
        },
        ml_flags: METH_NOARGS,
        ml_doc: c_str!("Return the date delta as a tuple"),
    },
    PyMethodDef {
        ml_name: c_str!("__reduce__"),
        ml_meth: PyMethodDefPointer {
            PyCMethod: __reduce__,
        },
        ml_flags: METH_METHOD | METH_FASTCALL | METH_KEYWORDS,
        ml_doc: NULL(),
    },
    PyMethodDef::zeroed(),
];

pub(crate) unsafe fn new_unchecked(type_: *mut PyTypeObject, d: TimeDelta) -> *mut PyTimeDelta {
    let f: allocfunc = (*type_).tp_alloc.expect("tp_alloc is not set");
    // TODO: rename to `return_ifnull`
    let slf = propagate_exc!(f(type_, 0).cast::<PyTimeDelta>());
    ptr::addr_of_mut!((*slf).delta).write(d);
    slf
}

pub(crate) static mut SPEC: PyType_Spec = PyType_Spec {
    name: c_str!("whenever.TimeDelta"),
    basicsize: mem::size_of::<PyTimeDelta>() as _,
    itemsize: 0,
    flags: Py_TPFLAGS_DEFAULT as _,
    slots: unsafe { SLOTS as *const [_] as *mut _ },
};

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn test_parse_component() {
        assert_eq!(parse_component(b"0006H"), Some((6, Unit::Hours, &b""[..])));
        assert_eq!(
            parse_component(b"56M9"),
            Some((56, Unit::Minutes, &b"9"[..]))
        );
        assert_eq!(
            parse_component(b"2S"),
            Some((2_000_000_000, Unit::Nanoseconds, &b""[..]))
        );
        assert_eq!(
            parse_component(b"0S98"),
            Some((0, Unit::Nanoseconds, &b"98"[..]))
        );
        assert_eq!(parse_component(b"S"), None);
        assert_eq!(parse_component(b"0"), None);
        assert_eq!(parse_component(b"+3S"), None);
        assert_eq!(parse_component(b"-"), None);
    }
}
