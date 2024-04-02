use core::ffi::{c_char, c_int, c_long, c_uint, c_void};
use core::{mem, ptr, ptr::null_mut as NULL};
use pyo3_ffi::*;

use crate::common::{c_str, identity, propagate_exc, py_str, pystr_to_utf8, raise, try_get_int};
use crate::date;
use crate::date_delta::{DateDelta, PyDateDelta};
use crate::time;
use crate::ModuleState;

// TODO: still need repr C?
#[repr(C)]
#[derive(Debug, Eq, PartialEq, Ord, PartialOrd, Copy, Clone)]
pub(crate) struct DateTime {
    date: date::Date,
    time: time::Time,
}

#[repr(C)]
pub(crate) struct PyNaiveDateTime {
    _ob_base: PyObject,
    dt: DateTime,
}

pub(crate) const SINGLETONS: [(&str, DateTime); 2] = [
    (
        "MIN\0",
        DateTime {
            date: date::Date {
                year: 1,
                month: 1,
                day: 1,
            },
            time: time::Time {
                hour: 0,
                minute: 0,
                second: 0,
                nanos: 0,
            },
        },
    ),
    (
        "MAX\0",
        DateTime {
            date: date::Date {
                year: 9999,
                month: 12,
                day: 31,
            },
            time: time::Time {
                hour: 23,
                minute: 59,
                second: 59,
                nanos: 999_999_999,
            },
        },
    ),
];

unsafe extern "C" fn __new__(
    subtype: *mut PyTypeObject,
    args: *mut PyObject,
    kwargs: *mut PyObject,
) -> *mut PyObject {
    let mut year: c_long = 0;
    let mut month: c_long = 0;
    let mut day: c_long = 0;
    let mut hour: c_long = 0;
    let mut minute: c_long = 0;
    let mut second: c_long = 0;
    let mut nanos: c_long = 0;

    // FUTURE: parse them manually, which is more efficient
    if PyArg_ParseTupleAndKeywords(
        args,
        kwargs,
        c_str!("lll|llll:NaiveDateTime"),
        vec![
            c_str!("year") as *mut c_char,
            c_str!("month") as *mut c_char,
            c_str!("day") as *mut c_char,
            c_str!("hour") as *mut c_char,
            c_str!("minute") as *mut c_char,
            c_str!("second") as *mut c_char,
            c_str!("nanosecond") as *mut c_char,
            NULL(),
        ]
        .as_mut_ptr(),
        &mut year,
        &mut month,
        &mut day,
        &mut hour,
        &mut minute,
        &mut second,
        &mut nanos,
    ) == 0
    {
        return NULL();
    }

    new_unchecked(
        subtype,
        DateTime {
            date: match date::in_range(year, month, day) {
                Ok(date) => date,
                Err(err) => {
                    err.set_pyerr();
                    return NULL();
                }
            },
            time: match time::in_range(hour, minute, second, nanos) {
                Some(time) => time,
                None => {
                    raise!(PyExc_ValueError, "Invalid time");
                }
            },
        },
    )
    .cast()
}

pub(crate) unsafe fn new_unchecked(type_: *mut PyTypeObject, dt: DateTime) -> *mut PyNaiveDateTime {
    let f: allocfunc = (*type_).tp_alloc.expect("tp_alloc is not set");
    let slf = propagate_exc!(f(type_, 0).cast::<PyNaiveDateTime>());
    ptr::addr_of_mut!((*slf).dt).write(dt);
    slf
}

unsafe extern "C" fn dealloc(slf: *mut PyObject) {
    let tp_free = PyType_GetSlot(Py_TYPE(slf), Py_tp_free);
    debug_assert_ne!(tp_free, NULL());
    let f: freefunc = std::mem::transmute(tp_free);
    f(slf.cast());
}

fn _canonical_fmt(dt: DateTime) -> String {
    if dt.time.nanos == 0 {
        format!(
            "{:04}-{:02}-{:02} {:02}:{:02}:{:02}",
            dt.date.year, dt.date.month, dt.date.day, dt.time.hour, dt.time.minute, dt.time.second,
        )
    } else {
        format!(
            "{:04}-{:02}-{:02} {:02}:{:02}:{:02}.{:09}",
            dt.date.year,
            dt.date.month,
            dt.date.day,
            dt.time.hour,
            dt.time.minute,
            dt.time.second,
            dt.time.nanos,
        )
        .trim_end_matches('0')
        .to_string()
    }
}

unsafe extern "C" fn __repr__(slf: *mut PyObject) -> *mut PyObject {
    py_str(
        format!(
            "NaiveDateTime({})",
            _canonical_fmt((*slf.cast::<PyNaiveDateTime>()).dt)
        )
        .as_str(),
    )
}

unsafe extern "C" fn __str__(slf: *mut PyObject) -> *mut PyObject {
    py_str(_canonical_fmt((*slf.cast::<PyNaiveDateTime>()).dt).as_str())
}

unsafe extern "C" fn canonical_format(slf: *mut PyObject, _: *mut PyObject) -> *mut PyObject {
    py_str(_canonical_fmt((*slf.cast::<PyNaiveDateTime>()).dt).as_str())
}

unsafe extern "C" fn __richcmp__(
    slf: *mut PyObject,
    other: *mut PyObject,
    op: c_int,
) -> *mut PyObject {
    let result = if Py_TYPE(other) == Py_TYPE(slf) {
        let a = (*slf.cast::<PyNaiveDateTime>()).dt;
        let b = (*other.cast::<PyNaiveDateTime>()).dt;
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

unsafe extern "C" fn __hash__(slf: *mut PyObject) -> Py_hash_t {
    let dt = (*slf.cast::<PyNaiveDateTime>()).dt;
    #[cfg(target_pointer_width = "64")]
    {
        (dt.date.hash() as u64 ^ dt.time.hash64()) as Py_hash_t
    }
    #[cfg(target_pointer_width = "32")]
    {
        (dt.date.hash() as u32 ^ dt.time.hash32()) as Py_hash_t
    }
}

unsafe extern "C" fn __add__(obj_a: *mut PyObject, obj_b: *mut PyObject) -> *mut PyObject {
    let slf = (*obj_a.cast::<PyNaiveDateTime>()).dt;
    if Py_TYPE(obj_b) != (*ModuleState::from(Py_TYPE(obj_a))).date_delta_type {
        let result = Py_NotImplemented();
        Py_INCREF(result);
        result
    } else {
        let delta = (*obj_b.cast::<PyDateDelta>()).delta;
        match _add_datedelta(slf, delta) {
            Some(dt) => new_unchecked(Py_TYPE(obj_a), dt).cast(),
            None => raise!(PyExc_ValueError, "Resulting date out of range"),
        }
    }
}

unsafe extern "C" fn __sub__(obj_a: *mut PyObject, obj_b: *mut PyObject) -> *mut PyObject {
    let slf = (*obj_a.cast::<PyNaiveDateTime>()).dt;
    if Py_TYPE(obj_b) != (*ModuleState::from(Py_TYPE(obj_a))).date_delta_type {
        let result = Py_NotImplemented();
        Py_INCREF(result);
        result
    } else {
        let delta = (*obj_b.cast::<PyDateDelta>()).delta;
        match _add_datedelta(slf, -delta) {
            Some(dt) => new_unchecked(Py_TYPE(obj_a), dt).cast(),
            None => raise!(PyExc_ValueError, "Resulting date out of range"),
        }
    }
}

fn _add_datedelta(dt: DateTime, delta: DateDelta) -> Option<DateTime> {
    date::add(
        dt.date,
        delta.years as c_long,
        delta.months as c_long,
        (delta.weeks * 7 + delta.days) as c_long,
    )
    .map(|date| DateTime { date, ..dt })
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
        slot: Py_tp_repr,
        pfunc: __repr__ as *mut c_void,
    },
    PyType_Slot {
        slot: Py_tp_str,
        pfunc: __str__ as *mut c_void,
    },
    PyType_Slot {
        slot: Py_tp_richcompare,
        pfunc: __richcmp__ as *mut c_void,
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
        slot: Py_tp_hash,
        pfunc: __hash__ as *mut c_void,
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

unsafe extern "C" fn replace(
    slf: *mut PyObject,
    type_: *mut PyTypeObject,
    args: *const *mut PyObject,
    nargs: Py_ssize_t,
    kwnames: *mut PyObject,
) -> *mut PyObject {
    if PyVectorcall_NARGS(nargs as usize) != 0 {
        raise!(PyExc_TypeError, "replace() takes no positional arguments");
    }
    if !kwnames.is_null() {
        let dt = (*slf.cast::<PyNaiveDateTime>()).dt;
        let mut year = dt.date.year as c_long;
        let mut month = dt.date.month as c_long;
        let mut day = dt.date.day as c_long;
        let mut hour = dt.time.hour as c_long;
        let mut minute = dt.time.minute as c_long;
        let mut second = dt.time.second as c_long;
        let mut nanos = dt.time.nanos as c_long;
        for i in 0..=Py_SIZE(kwnames).saturating_sub(1) {
            let name = PyTuple_GET_ITEM(kwnames, i as Py_ssize_t);
            if name == PyUnicode_InternFromString(c_str!("year")) {
                year = try_get_int!(*args.offset(i));
            } else if name == PyUnicode_InternFromString(c_str!("month")) {
                month = try_get_int!(*args.offset(i));
            } else if name == PyUnicode_InternFromString(c_str!("day")) {
                day = try_get_int!(*args.offset(i));
            } else if name == PyUnicode_InternFromString(c_str!("hour")) {
                hour = try_get_int!(*args.offset(i));
            } else if name == PyUnicode_InternFromString(c_str!("minute")) {
                minute = try_get_int!(*args.offset(i));
            } else if name == PyUnicode_InternFromString(c_str!("second")) {
                second = try_get_int!(*args.offset(i));
            } else if name == PyUnicode_InternFromString(c_str!("nanosecond")) {
                nanos = try_get_int!(*args.offset(i));
            } else {
                raise!(
                    PyExc_TypeError,
                    "replace() got an unexpected keyword argument %R",
                    name
                );
            }
        }
        new_unchecked(
            type_,
            DateTime {
                date: match date::in_range(year, month, day) {
                    Ok(date) => date,
                    Err(err) => {
                        err.set_pyerr();
                        return NULL();
                    }
                },
                time: match time::in_range(hour, minute, second, nanos) {
                    Some(time) => time,
                    None => {
                        raise!(PyExc_ValueError, "Invalid time");
                    }
                },
            },
        )
        .cast()
    } else {
        Py_INCREF(slf);
        slf
    }
}

unsafe extern "C" fn __reduce__(slf: *mut PyObject, _: *mut PyObject) -> *mut PyObject {
    let dt = (*slf.cast::<PyNaiveDateTime>()).dt;
    PyTuple_Pack(
        2,
        (*ModuleState::from(Py_TYPE(slf))).unpickle_naive_datetime,
        propagate_exc!(PyTuple_Pack(
            7,
            PyLong_FromLong(dt.date.year as c_long),
            PyLong_FromLong(dt.date.month as c_long),
            PyLong_FromLong(dt.date.day as c_long),
            PyLong_FromLong(dt.time.hour as c_long),
            PyLong_FromLong(dt.time.minute as c_long),
            PyLong_FromLong(dt.time.second as c_long),
            PyLong_FromLong(dt.time.nanos as c_long),
        )),
    )
}

pub(crate) unsafe extern "C" fn unpickle(
    module: *mut PyObject,
    args: *mut *mut PyObject,
    nargs: Py_ssize_t,
) -> *mut PyObject {
    if PyVectorcall_NARGS(nargs as usize) != 7 {
        raise!(PyExc_TypeError, "Invalid pickle data");
    }
    new_unchecked(
        (*PyModule_GetState(module).cast::<ModuleState>()).naive_datetime_type,
        DateTime {
            date: date::Date {
                year: try_get_int!(*args.offset(0)) as u16,
                month: try_get_int!(*args.offset(1)) as u8,
                day: try_get_int!(*args.offset(2)) as u8,
            },
            time: time::Time {
                hour: try_get_int!(*args.offset(3)) as u8,
                minute: try_get_int!(*args.offset(4)) as u8,
                second: try_get_int!(*args.offset(5)) as u8,
                nanos: try_get_int!(*args.offset(6)) as u32,
            },
        },
    )
    .cast()
}

unsafe extern "C" fn from_py_datetime(type_: *mut PyObject, dt: *mut PyObject) -> *mut PyObject {
    if PyDateTime_Check(dt) == 0 {
        raise!(PyExc_TypeError, "argument must be datetime.datetime");
    }
    let tzinfo = PyDateTime_DATE_GET_TZINFO(dt);
    if tzinfo != Py_None() {
        raise!(
            PyExc_ValueError,
            "datetime must be naive, but got tzinfo=%R",
            tzinfo
        );
    }
    new_unchecked(
        type_.cast(),
        DateTime {
            date: date::Date {
                year: PyDateTime_GET_YEAR(dt) as u16,
                month: PyDateTime_GET_MONTH(dt) as u8,
                day: PyDateTime_GET_DAY(dt) as u8,
            },
            time: time::Time {
                hour: PyDateTime_DATE_GET_HOUR(dt) as u8,
                minute: PyDateTime_DATE_GET_MINUTE(dt) as u8,
                second: PyDateTime_DATE_GET_SECOND(dt) as u8,
                nanos: PyDateTime_DATE_GET_MICROSECOND(dt) as u32 * 1_000,
            },
        },
    )
    .cast()
}

unsafe extern "C" fn py_datetime(slf: *mut PyObject, _: *mut PyObject) -> *mut PyObject {
    let dt = (*slf.cast::<PyNaiveDateTime>()).dt;
    let py_api = *(*ModuleState::from(Py_TYPE(slf))).datetime_api;
    propagate_exc!((py_api.DateTime_FromDateAndTime)(
        dt.date.year as c_int,
        dt.date.month as c_int,
        dt.date.day as c_int,
        dt.time.hour as c_int,
        dt.time.minute as c_int,
        dt.time.second as c_int,
        dt.time.nanos as c_int / 1_000,
        Py_None(),
        py_api.DateTimeType,
    ))
}

unsafe extern "C" fn get_date(slf: *mut PyObject, _: *mut PyObject) -> *mut PyObject {
    let dt = (*slf.cast::<PyNaiveDateTime>()).dt;
    date::new_unchecked((*ModuleState::from(Py_TYPE(slf))).date_type, dt.date).cast()
}

unsafe extern "C" fn get_time(slf: *mut PyObject, _: *mut PyObject) -> *mut PyObject {
    let dt = (*slf.cast::<PyNaiveDateTime>()).dt;
    time::new_unchecked((*ModuleState::from(Py_TYPE(slf))).time_type, dt.time).cast()
}

pub fn parse(s: &[u8]) -> Option<(date::Date, time::Time)> {
    // This should have already been checked by caller
    debug_assert!(s.len() >= 19 && (s[10] == b' ' || s[10] == b'T'));
    Some((
        date::parse(&s[..10])
            .and_then(|(y, m, d)| date::in_range(y as c_long, m as c_long, d as c_long).ok())?,
        time::parse(&s[11..]).and_then(|(h, m, s, ns)| {
            time::in_range(h as c_long, m as c_long, s as c_long, ns as c_long)
        })?,
    ))
}

unsafe extern "C" fn from_canonical_format(
    cls: *mut PyObject,
    arg: *mut PyObject,
) -> *mut PyObject {
    let s = pystr_to_utf8!(arg, "Expected a string");
    if s.len() < 19 || s[10] != b' ' {
        raise!(PyExc_ValueError, "Invalid canonical format: %R", arg);
    }
    match parse(s) {
        Some((date, time)) => new_unchecked(cls.cast(), DateTime { date, time }).cast(),
        None => raise!(PyExc_ValueError, "Invalid canonical format: %R", arg),
    }
}

unsafe extern "C" fn common_iso8601(slf: *mut PyObject, _: *mut PyObject) -> *mut PyObject {
    let dt = (*slf.cast::<PyNaiveDateTime>()).dt;
    py_str(format!("{}T{}", dt.date, dt.time).as_str())
}

unsafe extern "C" fn from_common_iso8601(cls: *mut PyObject, obj: *mut PyObject) -> *mut PyObject {
    let s = pystr_to_utf8!(obj, "Expected a string");
    if s.len() < 19 || s[10] != b'T' {
        raise!(PyExc_ValueError, "Invalid common ISO 8601 format: %R", obj);
    }
    match parse(s) {
        Some((date, time)) => new_unchecked(cls.cast(), DateTime { date, time }).cast(),
        None => raise!(PyExc_ValueError, "Invalid common ISO 8601 format: %R", obj),
    }
}

unsafe extern "C" fn strptime(cls: *mut PyObject, args: *mut PyObject) -> *mut PyObject {
    // FUTURE: get this working with vectorcall
    let module = ModuleState::from(cls.cast());
    let parsed = propagate_exc!(PyObject_Call((*module).strptime, args, NULL()));
    let tzinfo = PyDateTime_DATE_GET_TZINFO(parsed);
    if tzinfo != Py_None() {
        raise!(
            PyExc_ValueError,
            "datetime must be naive, but got tzinfo=%R",
            tzinfo
        );
    }
    new_unchecked(
        cls.cast(),
        DateTime {
            date: date::Date {
                year: PyDateTime_GET_YEAR(parsed) as u16,
                month: PyDateTime_GET_MONTH(parsed) as u8,
                day: PyDateTime_GET_DAY(parsed) as u8,
            },
            time: time::Time {
                hour: PyDateTime_DATE_GET_HOUR(parsed) as u8,
                minute: PyDateTime_DATE_GET_MINUTE(parsed) as u8,
                second: PyDateTime_DATE_GET_SECOND(parsed) as u8,
                nanos: PyDateTime_DATE_GET_MICROSECOND(parsed) as u32 * 1_000,
            },
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
        ml_name: c_str!("from_py_datetime"),
        ml_meth: PyMethodDefPointer {
            PyCFunction: from_py_datetime,
        },
        ml_flags: METH_O | METH_CLASS,
        ml_doc: c_str!("Create an instance from a datetime.datetime"),
    },
    PyMethodDef {
        ml_name: c_str!("py_datetime"),
        ml_meth: PyMethodDefPointer {
            PyCFunction: py_datetime,
        },
        ml_flags: METH_NOARGS,
        ml_doc: c_str!("Convert to a datetime.datetime"),
    },
    PyMethodDef {
        ml_name: c_str!("date"),
        ml_meth: PyMethodDefPointer {
            PyCFunction: get_date,
        },
        ml_flags: METH_NOARGS,
        ml_doc: c_str!("Get the date component"),
    },
    PyMethodDef {
        ml_name: c_str!("time"),
        ml_meth: PyMethodDefPointer {
            PyCFunction: get_time,
        },
        ml_flags: METH_NOARGS,
        ml_doc: c_str!("Get the time component"),
    },
    PyMethodDef {
        ml_name: c_str!("canonical_format"),
        ml_meth: PyMethodDefPointer {
            PyCFunction: canonical_format,
        },
        ml_flags: METH_NOARGS,
        ml_doc: c_str!("Get the canonical string representation"),
    },
    PyMethodDef {
        ml_name: c_str!("from_canonical_format"),
        ml_meth: PyMethodDefPointer {
            PyCFunction: from_canonical_format,
        },
        ml_flags: METH_O | METH_CLASS,
        ml_doc: c_str!("Create an instance from the canonical string representation"),
    },
    PyMethodDef {
        ml_name: c_str!("common_iso8601"),
        ml_meth: PyMethodDefPointer {
            PyCFunction: common_iso8601,
        },
        ml_flags: METH_NOARGS,
        ml_doc: c_str!("Get the common ISO 8601 string representation"),
    },
    PyMethodDef {
        ml_name: c_str!("from_common_iso8601"),
        ml_meth: PyMethodDefPointer {
            PyCFunction: from_common_iso8601,
        },
        ml_flags: METH_O | METH_CLASS,
        ml_doc: c_str!("Create an instance from the common ISO 8601 string representation"),
    },
    PyMethodDef {
        ml_name: c_str!("__reduce__"),
        ml_meth: PyMethodDefPointer {
            PyCFunction: __reduce__,
        },
        ml_flags: METH_NOARGS,
        ml_doc: NULL(),
    },
    PyMethodDef {
        ml_name: c_str!("strptime"),
        ml_meth: PyMethodDefPointer {
            PyCFunction: strptime,
        },
        ml_flags: METH_CLASS | METH_VARARGS,
        ml_doc: c_str!("Parse a string into a NaiveDateTime"),
    },
    PyMethodDef {
        ml_name: c_str!("replace"),
        ml_meth: PyMethodDefPointer { PyCMethod: replace },
        ml_flags: METH_METHOD | METH_FASTCALL | METH_KEYWORDS,
        ml_doc: c_str!("Return a new instance with the specified fields replaced"),
    },
    PyMethodDef::zeroed(),
];

unsafe extern "C" fn get_year(slf: *mut PyObject, _: *mut c_void) -> *mut PyObject {
    PyLong_FromLong((*slf.cast::<PyNaiveDateTime>()).dt.date.year as c_long)
}

unsafe extern "C" fn get_month(slf: *mut PyObject, _: *mut c_void) -> *mut PyObject {
    PyLong_FromLong((*slf.cast::<PyNaiveDateTime>()).dt.date.month as c_long)
}

unsafe extern "C" fn get_day(slf: *mut PyObject, _: *mut c_void) -> *mut PyObject {
    PyLong_FromLong((*slf.cast::<PyNaiveDateTime>()).dt.date.day as c_long)
}

unsafe extern "C" fn get_hour(slf: *mut PyObject, _: *mut c_void) -> *mut PyObject {
    PyLong_FromLong((*slf.cast::<PyNaiveDateTime>()).dt.time.hour as c_long)
}

unsafe extern "C" fn get_minute(slf: *mut PyObject, _: *mut c_void) -> *mut PyObject {
    PyLong_FromLong((*slf.cast::<PyNaiveDateTime>()).dt.time.minute as c_long)
}

unsafe extern "C" fn get_second(slf: *mut PyObject, _: *mut c_void) -> *mut PyObject {
    PyLong_FromLong((*slf.cast::<PyNaiveDateTime>()).dt.time.second as c_long)
}

unsafe extern "C" fn get_nanos(slf: *mut PyObject, _: *mut c_void) -> *mut PyObject {
    PyLong_FromLong((*slf.cast::<PyNaiveDateTime>()).dt.time.nanos as c_long)
}

static mut GETSETTERS: &[PyGetSetDef] = &[
    PyGetSetDef {
        name: c_str!("year"),
        get: Some(get_year),
        set: None,
        doc: c_str!("The year component"),
        closure: NULL(),
    },
    PyGetSetDef {
        name: c_str!("month"),
        get: Some(get_month),
        set: None,
        doc: c_str!("The month component"),
        closure: NULL(),
    },
    PyGetSetDef {
        name: c_str!("day"),
        get: Some(get_day),
        set: None,
        doc: c_str!("The day component"),
        closure: NULL(),
    },
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
    name: c_str!("whenever.NaiveDateTime"),
    basicsize: mem::size_of::<PyNaiveDateTime>() as c_int,
    itemsize: 0,
    flags: Py_TPFLAGS_DEFAULT as c_uint,
    slots: unsafe { SLOTS as *const [PyType_Slot] as *mut PyType_Slot },
};

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn test_parse_valid() {
        assert_eq!(
            parse(b"2023-03-02 02:09:09"),
            Some((
                date::Date {
                    year: 2023,
                    month: 3,
                    day: 2,
                },
                time::Time {
                    hour: 2,
                    minute: 9,
                    second: 9,
                    nanos: 0,
                },
            ))
        );
        assert_eq!(
            parse(b"2023-03-02 02:09:09.123456789"),
            Some((
                date::Date {
                    year: 2023,
                    month: 3,
                    day: 2,
                },
                time::Time {
                    hour: 2,
                    minute: 9,
                    second: 9,
                    nanos: 123_456_789,
                },
            ))
        );
    }

    #[test]
    fn test_parse_invalid() {
        // dot but no fractional digits
        assert_eq!(parse(b"2023-03-02 02:09:09."), None);
        // too many fractions
        assert_eq!(parse(b"2023-03-02 02:09:09.1234567890"), None);
        // invalid minute
        assert_eq!(parse(b"2023-03-02 02:69:09.123456789"), None);
        // invalid date
        assert_eq!(parse(b"2023-02-29 02:29:09.123456789"), None);
    }
}
