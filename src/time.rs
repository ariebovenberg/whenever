use core::ffi::{c_char, c_int, c_long, c_uint, c_void};
use core::{mem, ptr};
use pyo3_ffi::*;
use std::fmt::{self, Display, Formatter};
use std::ptr::null_mut as NULL;

use crate::common::{c_str, get_digit, propagate_exc, py_str, pystr_to_utf8, raise, try_get_long};
use crate::ModuleState;

#[repr(C)]
#[derive(Debug, Eq, PartialEq, Ord, PartialOrd, Copy, Clone)]
pub struct Time {
    pub(crate) hour: u8,
    pub(crate) minute: u8,
    pub(crate) second: u8,
    pub(crate) nanos: u32,
}

#[repr(C)]
pub(crate) struct PyTime {
    _ob_base: PyObject,
    time: Time,
}

impl Time {
    pub(crate) fn hash32(&self) -> u32 {
        ((self.hour as u32) << 16)
            ^ ((self.minute as u32) << 8)
            ^ (self.second as u32)
            ^ (self.nanos as u32)
    }

    pub(crate) fn hash64(&self) -> u64 {
        ((self.hour as u64) << 48)
            | ((self.minute as u64) << 40)
            | ((self.second as u64) << 32)
            | (self.nanos as u64)
    }
}

impl Display for Time {
    fn fmt(&self, f: &mut Formatter<'_>) -> fmt::Result {
        if self.nanos == 0 {
            write!(f, "{:02}:{:02}:{:02}", self.hour, self.minute, self.second)
        } else {
            f.write_str(
                format!(
                    "{:02}:{:02}:{:02}.{:09}",
                    self.hour, self.minute, self.second, self.nanos
                )
                .trim_end_matches('0'),
            )
        }
    }
}

pub(crate) const SINGLETONS: [(&str, Time); 3] = [
    (
        "MIDNIGHT\0",
        Time {
            hour: 0,
            minute: 0,
            second: 0,
            nanos: 0,
        },
    ),
    (
        "NOON\0",
        Time {
            hour: 12,
            minute: 0,
            second: 0,
            nanos: 0,
        },
    ),
    (
        "MAX\0",
        Time {
            hour: 23,
            minute: 59,
            second: 59,
            nanos: 999_999_999,
        },
    ),
];

unsafe extern "C" fn __new__(
    subtype: *mut PyTypeObject,
    args: *mut PyObject,
    kwargs: *mut PyObject,
) -> *mut PyObject {
    let mut hour: c_long = 0;
    let mut minute: c_long = 0;
    let mut second: c_long = 0;
    let mut nanos: c_long = 0;

    // FUTURE: parse them manually, which is more efficient
    if PyArg_ParseTupleAndKeywords(
        args,
        kwargs,
        c_str!("|llll:Time"),
        vec![
            c_str!("hour") as *mut c_char,
            c_str!("minute") as *mut c_char,
            c_str!("second") as *mut c_char,
            c_str!("nanosecond") as *mut c_char,
            NULL(),
        ]
        .as_mut_ptr(),
        &mut hour,
        &mut minute,
        &mut second,
        &mut nanos,
    ) == 0
    {
        return NULL();
    }

    match in_range(hour, minute, second, nanos) {
        Some(time) => new_unchecked(subtype, time).cast(),
        None => raise!(PyExc_ValueError, "Invalid time component value"),
    }
}

pub(crate) fn in_range(
    hour: c_long,
    minute: c_long,
    second: c_long,
    nanos: c_long,
) -> Option<Time> {
    if hour < 0 || hour > 23 {
        return None;
    }
    if minute < 0 || minute > 59 {
        return None;
    }
    if second < 0 || second > 59 {
        return None;
    }
    if nanos < 0 || nanos > 999_999_999 {
        return None;
    }
    Some(Time {
        hour: hour as u8,
        minute: minute as u8,
        second: second as u8,
        nanos: nanos as u32,
    })
}

unsafe extern "C" fn __repr__(slf: *mut PyObject) -> *mut PyObject {
    py_str(format!("Time({})", _canonical_fmt((*slf.cast::<PyTime>()).time)).as_str())
}

unsafe extern "C" fn __hash__(slf: *mut PyObject) -> Py_hash_t {
    let time = (*slf.cast::<PyTime>()).time;
    // TODO: improve
    time.hour as Py_hash_t
        ^ (time.minute as Py_hash_t)
        ^ (time.second as Py_hash_t)
        ^ (time.nanos as Py_hash_t)
}

unsafe extern "C" fn dealloc(slf: *mut PyObject) {
    let tp_free = PyType_GetSlot(Py_TYPE(slf), Py_tp_free);
    debug_assert_ne!(tp_free, NULL());
    let f: freefunc = std::mem::transmute(tp_free);
    f(slf.cast());
}

unsafe extern "C" fn __richcmp__(
    slf: *mut PyObject,
    other: *mut PyObject,
    op: c_int,
) -> *mut PyObject {
    let result = if Py_TYPE(other) == Py_TYPE(slf) {
        let a = (*slf.cast::<PyTime>()).time;
        let b = (*other.cast::<PyTime>()).time;
        let cmp = match op {
            pyo3_ffi::Py_LT => a < b,
            pyo3_ffi::Py_LE => a <= b,
            pyo3_ffi::Py_EQ => a == b,
            pyo3_ffi::Py_NE => a != b,
            pyo3_ffi::Py_GT => a > b,
            pyo3_ffi::Py_GE => a >= b,
            _ => unreachable!(),
        };
        if cmp {
            Py_True()
        } else {
            Py_False()
        }
    } else {
        Py_NotImplemented()
    };
    Py_INCREF(result);
    result
}

static mut SLOTS: &[PyType_Slot] = &[
    PyType_Slot {
        slot: Py_tp_new,
        pfunc: __new__ as *mut c_void,
    },
    PyType_Slot {
        slot: Py_tp_doc,
        pfunc: "A time type\0".as_ptr() as *mut c_void,
    },
    PyType_Slot {
        slot: Py_tp_str,
        pfunc: canonical_format as *mut c_void,
    },
    PyType_Slot {
        slot: Py_tp_repr,
        pfunc: __repr__ as *mut c_void,
    },
    PyType_Slot {
        slot: Py_tp_richcompare,
        pfunc: __richcmp__ as *mut c_void,
    },
    PyType_Slot {
        slot: Py_tp_methods,
        pfunc: unsafe { METHODS.as_ptr() as *mut c_void },
    },
    PyType_Slot {
        slot: Py_tp_getset,
        pfunc: unsafe { GETSETTERS.as_ptr() as *mut c_void },
    },
    PyType_Slot {
        slot: Py_tp_hash,
        pfunc: __hash__ as *mut c_void,
    },
    PyType_Slot {
        slot: Py_tp_members,
        pfunc: unsafe { MEMBERS.as_ptr() as *mut c_void },
    },
    PyType_Slot {
        slot: Py_tp_dealloc,
        pfunc: dealloc as *mut c_void,
    },
    PyType_Slot {
        slot: 0,
        pfunc: NULL(),
    },
];

static mut MEMBERS: &[PyMemberDef] = &[PyMemberDef {
    name: NULL(),
    type_code: 0,
    offset: 0,
    flags: 0,
    doc: NULL(),
}];

unsafe extern "C" fn as_py_time(slf: *mut PyObject, _: *mut PyObject) -> *mut PyObject {
    let time = (*slf.cast::<PyTime>()).time;
    let api = *(*ModuleState::from(Py_TYPE(slf))).datetime_api;
    (api.Time_FromTime)(
        time.hour as c_int,
        time.minute as c_int,
        time.second as c_int,
        (time.nanos / 1_000) as c_int,
        Py_None(),
        api.TimeType,
    )
}

unsafe extern "C" fn from_py_time(type_: *mut PyObject, time: *mut PyObject) -> *mut PyObject {
    // TODO: test subtypes?
    if PyTime_CheckExact(time) == 0 {
        raise!(PyExc_TypeError, "argument must be datetime.time");
    }
    // TODO: check fold etc.
    new_unchecked(
        type_.cast(),
        Time {
            hour: PyDateTime_TIME_GET_HOUR(time) as u8,
            minute: PyDateTime_TIME_GET_MINUTE(time) as u8,
            second: PyDateTime_TIME_GET_SECOND(time) as u8,
            nanos: PyDateTime_TIME_GET_MICROSECOND(time) as u32 * 1_000,
        },
    )
    .cast()
}

unsafe extern "C" fn canonical_format(slf: *mut PyObject, _: *mut PyObject) -> *mut PyObject {
    py_str(_canonical_fmt((*slf.cast::<PyTime>()).time).as_str())
}

fn _canonical_fmt(time: Time) -> String {
    if time.nanos == 0 {
        format!("{:02}:{:02}:{:02}", time.hour, time.minute, time.second)
    } else {
        format!(
            "{:02}:{:02}:{:02}.{:09}",
            time.hour, time.minute, time.second, time.nanos
        )
        .trim_end_matches('0')
        .to_string()
    }
}

unsafe extern "C" fn identity(slf: *mut PyObject, _: *mut PyObject) -> *mut PyObject {
    Py_INCREF(slf);
    slf
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
    let time = (*slf.cast::<PyTime>()).time;
    PyTuple_Pack(
        2,
        (*module).unpickle_time,
        propagate_exc!(PyTuple_Pack(
            4,
            PyLong_FromLong(time.hour as c_long),
            PyLong_FromLong(time.minute as c_long),
            PyLong_FromLong(time.second as c_long),
            PyLong_FromLong(time.nanos as c_long),
        )),
    )
}

pub(crate) fn parse(s: &[u8]) -> Option<(u8, u8, u8, u32)> {
    // TODO: allow length check skip
    if s.len() <= 7 || s.len() == 9 || s.len() > 18 || s[2] != b':' || s[5] != b':' {
        return None;
    }
    let hour = get_digit!(s, 0) * 10 + get_digit!(s, 1);
    let minute = get_digit!(s, 3) * 10 + get_digit!(s, 4);
    let second = get_digit!(s, 6) * 10 + get_digit!(s, 7);
    let mut nanos: u32 = 0;
    if s.len() > 8 {
        if s[8] != b'.' {
            return None;
        }
        for (i, factor) in s[9..].iter().zip(&[
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
        }
    }
    Some((hour, minute, second, nanos))
}

unsafe extern "C" fn from_canonical_format(cls: *mut PyObject, s: *mut PyObject) -> *mut PyObject {
    if let Some((h, m, s, n)) = parse(pystr_to_utf8!(s, "argument must be str")) {
        if let Some(time) = in_range(h as c_long, m as c_long, s as c_long, n as c_long) {
            return new_unchecked(cls.cast(), time).cast();
        }
    }
    raise!(PyExc_ValueError, "Could not parse time: %R", s);
}

static mut METHODS: &[PyMethodDef] = &[
    PyMethodDef {
        ml_name: c_str!("py_time"),
        ml_meth: PyMethodDefPointer {
            PyCFunction: as_py_time,
        },
        ml_flags: METH_NOARGS,
        ml_doc: c_str!("Convert to a Python datetime.time"),
    },
    PyMethodDef {
        ml_name: c_str!("canonical_format"),
        ml_meth: PyMethodDefPointer {
            PyCFunction: canonical_format,
        },
        ml_flags: METH_NOARGS,
        ml_doc: c_str!("Return the time in the canonical format"),
    },
    PyMethodDef {
        ml_name: c_str!("common_iso8601"),
        ml_meth: PyMethodDefPointer {
            PyCFunction: canonical_format,
        },
        ml_flags: METH_NOARGS,
        ml_doc: c_str!("Return the time in the common ISO 8601 format"),
    },
    PyMethodDef {
        ml_name: c_str!("from_canonical_format"),
        ml_meth: PyMethodDefPointer {
            PyCFunction: from_canonical_format,
        },
        ml_flags: METH_O | METH_CLASS,
        ml_doc: c_str!("Create a date from the canonical format"),
    },
    PyMethodDef {
        ml_name: c_str!("from_common_iso8601"),
        ml_meth: PyMethodDefPointer {
            PyCFunction: from_canonical_format,
        },
        ml_flags: METH_O | METH_CLASS,
        ml_doc: c_str!("Create a date from the common ISO 8601 format"),
    },
    PyMethodDef {
        ml_name: c_str!("from_py_time"),
        ml_meth: PyMethodDefPointer {
            PyCFunction: from_py_time,
        },
        ml_flags: METH_O | METH_CLASS,
        ml_doc: c_str!("Create a time from a Python datetime.time"),
    },
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
        ml_name: c_str!("__reduce__"),
        ml_meth: PyMethodDefPointer { PyCMethod: reduce },
        ml_flags: METH_METHOD | METH_FASTCALL | METH_KEYWORDS,
        ml_doc: NULL(),
    },
    PyMethodDef::zeroed(),
];

unsafe extern "C" fn get_hour(slf: *mut PyObject, _: *mut c_void) -> *mut PyObject {
    PyLong_FromLong((*slf.cast::<PyTime>()).time.hour as c_long)
}

unsafe extern "C" fn get_minute(slf: *mut PyObject, _: *mut c_void) -> *mut PyObject {
    PyLong_FromLong((*slf.cast::<PyTime>()).time.minute as c_long)
}

unsafe extern "C" fn get_second(slf: *mut PyObject, _: *mut c_void) -> *mut PyObject {
    PyLong_FromLong((*slf.cast::<PyTime>()).time.second as c_long)
}

unsafe extern "C" fn get_nanos(slf: *mut PyObject, _: *mut c_void) -> *mut PyObject {
    PyLong_FromLong((*slf.cast::<PyTime>()).time.nanos as c_long)
}

pub(crate) unsafe fn new_unchecked(type_: *mut PyTypeObject, t: Time) -> *mut PyTime {
    let f: allocfunc = (*type_).tp_alloc.expect("tp_alloc is not set");
    let slf = propagate_exc!(f(type_, 0).cast::<PyTime>());
    ptr::addr_of_mut!((*slf).time).write(t);
    slf
}

// OPTIMIZE: a more efficient pickle?
pub(crate) unsafe extern "C" fn unpickle(
    module: *mut PyObject,
    args: *mut *mut PyObject,
    nargs: Py_ssize_t,
) -> *mut PyObject {
    if PyVectorcall_NARGS(nargs as usize) != 4 {
        raise!(PyExc_TypeError, "Invalid pickle data");
    }
    new_unchecked(
        (*PyModule_GetState(module).cast::<crate::ModuleState>()).time_type,
        Time {
            hour: try_get_long!(*args) as u8,
            minute: try_get_long!(*args.add(1)) as u8,
            second: try_get_long!(*args.add(2)) as u8,
            nanos: try_get_long!(*args.add(3)) as u32,
        },
    )
    .cast()
}

static mut GETSETTERS: &[PyGetSetDef] = &[
    PyGetSetDef {
        name: c_str!("hour"),
        get: Some(get_hour),
        set: None,
        doc: c_str!("The hour component"),
        closure: NULL(),
    },
    PyGetSetDef {
        name: c_str!("minute"),
        get: Some(get_minute),
        set: None,
        doc: c_str!("The minute component"),
        closure: NULL(),
    },
    PyGetSetDef {
        name: c_str!("second"),
        get: Some(get_second),
        set: None,
        doc: c_str!("The second component"),
        closure: NULL(),
    },
    PyGetSetDef {
        name: c_str!("nanosecond"),
        get: Some(get_nanos),
        set: None,
        doc: c_str!("The nanosecond component"),
        closure: NULL(),
    },
    PyGetSetDef {
        name: NULL(),
        get: None,
        set: None,
        doc: NULL(),
        closure: NULL(),
    },
];

pub(crate) static mut SPEC: PyType_Spec = PyType_Spec {
    name: c_str!("whenever.Time"),
    basicsize: mem::size_of::<PyTime>() as c_int,
    itemsize: 0,
    flags: Py_TPFLAGS_DEFAULT as c_uint,
    slots: unsafe { SLOTS as *const [PyType_Slot] as *mut PyType_Slot },
};
