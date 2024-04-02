use core::ffi::{c_char, c_int, c_long, c_uint, c_void};
use core::{mem, ptr};
use pyo3_ffi::*;
use std::cmp::min;
use std::collections::hash_map::DefaultHasher;
use std::hash::{Hash, Hasher};
use std::ops::Neg;
use std::ptr::null_mut as NULL;

use crate::common::{c_str, get_digit, propagate_exc, py_str, pystr_to_utf8, raise, try_get_long};
use crate::date::MAX_YEAR;
use crate::ModuleState;

// TODO: hide the constructors
#[repr(C)]
#[derive(Debug, Eq, PartialEq, Ord, PartialOrd, Hash, Copy, Clone)]
pub(crate) struct TimeDelta {
    // struct design inspired by datetime.timedelta and chrono::TimeDelta
    secs: i64,
    nanos: u32, // 0..1_000_000_000
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

const MAX_SECS: i64 = (MAX_YEAR * 366 * 24 * 3600) as i64;

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
            nanos: 999_999_999,
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

unsafe extern "C" fn __new__(
    subtype: *mut PyTypeObject,
    args: *mut PyObject,
    kwargs: *mut PyObject,
) -> *mut PyObject {
    let mut secs: c_long = 0;
    let mut nanos: c_long = 0;

    let nargs = PyTuple_GET_SIZE(args);
    let nkwargs = if kwargs.is_null() {
        0
    } else {
        PyDict_Size(kwargs)
    };

    // the happy path
    match (nargs, nkwargs) {
        (0, 0) => {
            // TODO: return the ZERO singleton
        }
        (0, _) => {
            // TODO: parse the kwargs
        }
        _ => raise!(PyExc_TypeError, "TimeDelta() takes no positional arguments"),
    };

    new_unchecked(subtype, TimeDelta { secs: 0, nanos: 0 }).cast()
}

pub(crate) unsafe extern "C" fn hours(
    module: *mut PyObject,
    amount: *mut PyObject,
) -> *mut PyObject {
    let parsed_amount = try_get_long!(amount);
    if parsed_amount < -MAX_YEAR || parsed_amount > MAX_YEAR {
        raise!(PyExc_ValueError, "years out of bounds");
    }
    new_unchecked(
        (*PyModule_GetState(module).cast::<crate::ModuleState>()).time_delta_type,
        TimeDelta {
            secs: 
            months: 0,
            weeks: 0,
            days: 0,
        },
    )
    .cast()
}

unsafe extern "C" fn richcmp(slf: *mut PyObject, other: *mut PyObject, op: c_int) -> *mut PyObject {
    let result: *mut PyObject;
    if Py_TYPE(other) != Py_TYPE(slf) {
        result = Py_NotImplemented();
    } else {
        let slf = (*slf.cast::<PyTimeDelta>()).delta;
        let other = (*other.cast::<PyTimeDelta>()).delta;
        result = match op {
            pyo3_ffi::Py_EQ => {
                if slf == other {
                    Py_True()
                } else {
                    Py_False()
                }
            }
            pyo3_ffi::Py_NE => {
                if slf != other {
                    Py_True()
                } else {
                    Py_False()
                }
            }
            _ => Py_NotImplemented(),
        };
    }
    Py_INCREF(result);
    result
}

// TODO: hash can never be -1? Check this...
// TODO: cache this value?
unsafe extern "C" fn __hash__(slf: *mut PyObject) -> Py_hash_t {
    // TODO: use xors
    let date = (*slf.cast::<PyTimeDelta>()).delta;
    let mut hasher = DefaultHasher::new();
    date.hash(&mut hasher);
    // TODO: is this OK?
    hasher.finish() as Py_hash_t
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
    py_str("TimeDelta")
}

unsafe extern "C" fn __str__(slf: *mut PyObject) -> *mut PyObject {
    let delta = (*slf.cast::<PyTimeDelta>()).delta;
    py_str("TimeDelta")
}

// unsafe extern "C" fn __mul__(slf: *mut PyObject, factor_obj: *mut PyObject) -> *mut PyObject {
//     let factor = try_get_long!(factor_obj);
//     if factor == 1 {
//         Py_INCREF(slf);
//         return slf;
//     }
//     let mut delta = (*slf.cast::<PyTimeDelta>()).delta;
//     // Overflow checks that allow us to do `factor as i16/i32` later
//     if delta.years != 0 && (factor > i16::MAX as c_long || factor < i16::MIN as c_long)
//         || factor > i32::MAX as c_long
//         || factor < i32::MIN as c_long
//     {
//         raise!(PyExc_ValueError, "Multiplication result out of range");
//     }
//     if let (Some(years), Some(months), Some(weeks), Some(days)) = (
//         delta.years.checked_mul(factor as i16),
//         delta.months.checked_mul(factor as i32),
//         delta.weeks.checked_mul(factor as i32),
//         delta.days.checked_mul(factor as i32),
//     ) {
//         delta = TimeDelta {
//             years,
//             months,
//             weeks,
//             days,
//         };
//     } else {
//         raise!(PyExc_ValueError, "Multiplication result out of range");
//     }
//     if !is_in_range(delta) {
//         raise!(PyExc_ValueError, "Multiplication result out of range");
//     }
//     new_unchecked(Py_TYPE(slf), delta).cast()
// }

// unsafe extern "C" fn __add__(slf: *mut PyObject, other: *mut PyObject) -> *mut PyObject {
//     if Py_TYPE(other) != Py_TYPE(slf) {
//         let result = Py_NotImplemented();
//         Py_INCREF(result);
//         return result;
//     }
//     let a = (*other.cast::<PyTimeDelta>()).delta;
//     let b = (*slf.cast::<PyTimeDelta>()).delta;
//     let new = TimeDelta {
//         // don't need to check for overflow here, since valid deltas well below overflow
//         years: a.years + b.years,
//         months: a.months + b.months,
//         weeks: a.weeks + b.weeks,
//         days: a.days + b.days,
//     };
//     if !is_in_range(new) {
//         raise!(PyExc_ValueError, "Addition result out of range");
//     }
//     new_unchecked(Py_TYPE(slf), new).cast()
// }

// unsafe extern "C" fn __sub__(slf: *mut PyObject, other: *mut PyObject) -> *mut PyObject {
//     if Py_TYPE(other) != Py_TYPE(slf) {
//         let result = Py_NotImplemented();
//         Py_INCREF(result);
//         return result;
//     }
//     let a = (*slf.cast::<PyTimeDelta>()).delta;
//     let b = (*other.cast::<PyTimeDelta>()).delta;
//     let new = TimeDelta {
//         // don't need to check for overflow here, since valid deltas well below overflow
//         years: a.years - b.years,
//         months: a.months - b.months,
//         weeks: a.weeks - b.weeks,
//         days: a.days - b.days,
//     };
//     if !is_in_range(new) {
//         raise!(PyExc_ValueError, "Subtraction result out of range");
//     }
//     new_unchecked(Py_TYPE(slf), new).cast()
// }

// unsafe extern "C" fn __abs__(slf: *mut PyObject) -> *mut PyObject {
//     let delta = (*slf.cast::<PyTimeDelta>()).delta;
//     if delta.years >= 0 && delta.months >= 0 && delta.weeks >= 0 && delta.days >= 0 {
//         Py_INCREF(slf);
//         return slf;
//     }
//     new_unchecked(
//         Py_TYPE(slf),
//         TimeDelta {
//             years: delta.years.abs(),
//             months: delta.months.abs(),
//             weeks: delta.weeks.abs(),
//             days: delta.days.abs(),
//         },
//     )
//     .cast()
// }

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
    // PyType_Slot {
    //     slot: Py_nb_multiply,
    //     pfunc: __mul__ as *mut c_void,
    // },
    // PyType_Slot {
    //     slot: Py_nb_add,
    //     pfunc: __add__ as *mut c_void,
    // },
    // PyType_Slot {
    //     slot: Py_nb_subtract,
    //     pfunc: __sub__ as *mut c_void,
    // },
    // PyType_Slot {
    //     slot: Py_nb_absolute,
    //     pfunc: __abs__ as *mut c_void,
    // },
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

unsafe extern "C" fn reduce(
    slf: *mut PyObject,
    type_: *mut PyTypeObject,
    // All args are unused. We don't need to check this since __reduce__
    // is only called internally by pickle (without arguments).
    _: *const *mut PyObject,
    _: Py_ssize_t,
    _: *mut PyObject,
) -> *mut PyObject {
    let module = ModuleState::from(type_);
    let delta = (*slf.cast::<PyTimeDelta>()).delta;
    PyTuple_Pack(
        2,
        (*module).unpickle_time_delta,
        propagate_exc!(PyTuple_Pack(
            2,
            PyLong_FromLong(delta.secs as c_long),
            PyLong_FromLong(delta.nanos as c_long),
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
            secs: try_get_long!(*args.offset(0)) as i64,
            nanos: try_get_long!(*args.offset(1)) as u32,
        },
    )
    .cast()
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
            PyCFunction: canonical_format,
        },
        ml_flags: METH_NOARGS,
        ml_doc: c_str!("Return the ISO 8601 string representation"),
    },
    // PyMethodDef {
    //     ml_name: c_str!("from_canonical_format"),
    //     ml_meth: PyMethodDefPointer {
    //         PyCFunction: from_canonical_format,
    //     },
    //     ml_flags: METH_O | METH_CLASS,
    //     ml_doc: c_str!("Parse a canonical string representation"),
    // },
    // PyMethodDef {
    //     ml_name: c_str!("from_common_iso8601"),
    //     ml_meth: PyMethodDefPointer {
    //         PyCFunction: from_canonical_format,
    //     },
    //     ml_flags: METH_O | METH_CLASS,
    //     ml_doc: c_str!("Parse from the common ISO8601 period format"),
    // },
    // PyMethodDef {
    //     ml_name: c_str!("as_tuple"),
    //     ml_meth: PyMethodDefPointer {
    //         PyCFunction: as_tuple,
    //     },
    //     ml_flags: METH_NOARGS,
    //     ml_doc: c_str!("Return the date delta as a tuple"),
    // },
    PyMethodDef {
        ml_name: c_str!("__reduce__"),
        ml_meth: PyMethodDefPointer { PyCMethod: reduce },
        ml_flags: METH_METHOD | METH_FASTCALL | METH_KEYWORDS,
        ml_doc: NULL(),
    },
    PyMethodDef::zeroed(),
];

pub(crate) unsafe fn new_unchecked(type_: *mut PyTypeObject, d: TimeDelta) -> *mut PyTimeDelta {
    let f: allocfunc = (*type_).tp_alloc.expect("tp_alloc is not set");
    let slf = propagate_exc!(f(type_, 0).cast::<PyTimeDelta>());
    ptr::addr_of_mut!((*slf).delta).write(d);
    slf
}

static mut GETSETTERS: &[PyGetSetDef] = &[PyGetSetDef {
    name: NULL(),
    get: None,
    set: None,
    doc: NULL(),
    closure: NULL(),
}];

pub(crate) static mut SPEC: PyType_Spec = PyType_Spec {
    name: c_str!("whenever.TimeDelta"),
    basicsize: mem::size_of::<PyTimeDelta>() as c_int,
    itemsize: 0,
    flags: Py_TPFLAGS_DEFAULT as c_uint,
    slots: unsafe { SLOTS as *const [_] as *mut _ },
};
