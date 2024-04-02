use core::ffi::{c_char, c_int, c_long, c_uint, c_void};
use core::{mem, ptr, ptr::null_mut as NULL};
use pyo3_ffi::*;

use crate::common::{c_str, identity, propagate_exc, py_str};
use crate::date::Date;
use crate::ModuleState;

#[derive(Debug, Eq, PartialEq, Ord, PartialOrd, Copy, Clone)]
struct Time {
    hour: u8,
    minute: u8,
    second: u8,
    nanos: u32,
}

impl Time {
    fn seconds(&self) -> i32 {
        self.hour as i32 * 3600 + self.minute as i32 * 60 + self.second as i32
    }

    fn set_seconds(mut self, seconds: u32) -> Self {
        self.hour = (seconds / 3600) as u8;
        self.minute = ((seconds % 3600) / 60) as u8;
        self.second = (seconds % 60) as u8;
        self
    }
}

// TODO: still need repr C?
#[repr(C)]
#[derive(Debug, Eq, PartialEq, Ord, PartialOrd, Copy, Clone)]
struct OffsetDateTime {
    date: Date,
    time: Time,
    offset_seconds: i32,
}

#[repr(C)]
pub(crate) struct PyZonedDateTime {
    _ob_base: PyObject,
    zoneinfo: *mut PyObject,
    dt: OffsetDateTime,
}

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
    let mut tz: *mut PyObject = NULL();

    // FUTURE: parse them manually, which is more efficient
    if PyArg_ParseTupleAndKeywords(
        args,
        kwargs,
        c_str!("lll|llllU:ZonedDateTime"),
        vec![
            c_str!("year") as *mut c_char,
            c_str!("month") as *mut c_char,
            c_str!("day") as *mut c_char,
            c_str!("hour") as *mut c_char,
            c_str!("minute") as *mut c_char,
            c_str!("second") as *mut c_char,
            c_str!("nanosecond") as *mut c_char,
            c_str!("tz") as *mut c_char,
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
        &mut tz,
    ) == 0
    {
        return NULL();
    }
    // TODO: check tz argument required!
    let module = ModuleState::from(subtype);
    let api = *(*module).datetime_api;
    let zoneinfo = propagate_exc!(PyObject_CallOneArg((*module).zoneinfo_type.cast(), tz));
    Py_INCREF(zoneinfo);

    // TODO: check max/min year. Stricter due to offset.

    // TODO: disambiguate
    let offset_delta = propagate_exc!(PyObject_CallMethodOneArg(
        zoneinfo,
        py_str("utcoffset"),
        (api.DateTime_FromDateAndTimeAndFold)(
            year as c_int,
            month as c_int,
            day as c_int,
            hour as c_int,
            minute as c_int,
            second as c_int,
            (nanos / 1000) as c_int,
            Py_None(),
            0,
            api.DateTimeType,
        )
    ));

    // TODO: verify that zoneinfo always rounds to the nearest second
    let offset_seconds = PyFloat_AsDouble(PyObject_CallMethodNoArgs(
        offset_delta,
        py_str("total_seconds"),
    ))
    .trunc() as i32;

    // TODO: bounds checks
    new_unchecked(
        subtype,
        OffsetDateTime {
            date: Date {
                year: year as u16,
                month: month as u8,
                day: day as u8,
            },
            time: Time {
                hour: hour as u8,
                minute: minute as u8,
                second: second as u8,
                nanos: nanos as u32,
            },
            offset_seconds,
        },
        zoneinfo,
    )
    .cast()
}

unsafe fn new_unchecked(
    type_: *mut PyTypeObject,
    dt: OffsetDateTime,
    zoneinfo: *mut PyObject,
) -> *mut PyZonedDateTime {
    let f: allocfunc = (*type_).tp_alloc.expect("tp_alloc is not set");
    let slf = propagate_exc!(f(type_, 0).cast::<PyZonedDateTime>());
    ptr::addr_of_mut!((*slf).dt).write(dt);
    ptr::addr_of_mut!((*slf).zoneinfo).write(zoneinfo);
    slf
}

unsafe extern "C" fn dealloc(slf: *mut PyObject) {
    Py_DECREF((*slf.cast::<PyZonedDateTime>()).zoneinfo);
    let tp_free = PyType_GetSlot(Py_TYPE(slf), Py_tp_free);
    debug_assert_ne!(tp_free, NULL());
    let f: freefunc = std::mem::transmute(tp_free);
    f(slf.cast());
}

unsafe extern "C" fn __repr__(slf: *mut PyObject) -> *mut PyObject {
    let dt = (*slf.cast::<PyZonedDateTime>()).dt;
    py_str(
        format!(
            "ZonedDateTime({:04}-{:02}-{:02}T{:02}:{:02}:{:02}.{:09}+{}s)",
            dt.date.year,
            dt.date.month,
            dt.date.day,
            dt.time.hour,
            dt.time.minute,
            dt.time.second,
            dt.time.nanos,
            dt.offset_seconds,
        )
        .as_str(),
    )
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
    // PyType_Slot {
    //     slot: Py_tp_str,
    //     pfunc: canonical_format as *mut c_void,
    // },
    PyType_Slot {
        slot: Py_tp_repr,
        pfunc: __repr__ as *mut c_void,
    },
    // PyType_Slot {
    //     slot: Py_tp_richcompare,
    //     pfunc: richcmp as *mut c_void,
    // },
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

unsafe extern "C" fn exact_eq(obj_a: *mut PyObject, obj_b: *mut PyObject) -> *mut PyObject {
    let a = obj_a.cast::<PyZonedDateTime>();
    let b = obj_b.cast::<PyZonedDateTime>();
    let result = if (*a).dt == (*b).dt && (*a).zoneinfo == (*b).zoneinfo {
        Py_True()
    } else {
        Py_False()
    };
    Py_INCREF(result);
    result
}

fn as_utc(date: Date, time: Time, offset_secs: i32) -> (Date, Time) {
    let day_seconds = time.seconds() - offset_secs;
    match day_seconds.div_euclid(86400) {
        0 => (date, time.set_seconds(day_seconds as u32)),
        1 => (
            date.increment(),
            time.set_seconds((day_seconds - 86400) as u32),
        ),
        -1 => (
            date.decrement(),
            time.set_seconds((day_seconds + 86400) as u32),
        ),
        // more than 2 days difference is highly unlikely--but possible
        2 => (
            date.increment().increment(),
            time.set_seconds((day_seconds - 86400 * 2) as u32),
        ),
        -2 => (
            date.decrement().decrement(),
            time.set_seconds((day_seconds + 86400 * 2) as u32),
        ),
        _ => unreachable!(),
    }
}

unsafe extern "C" fn as_zoned(slf: *mut PyObject, tz: *mut PyObject) -> *mut PyObject {
    let new_zoneinfo = propagate_exc!(PyObject_CallOneArg(
        (*ModuleState::from(Py_TYPE(slf))).zoneinfo_type.cast(),
        tz
    ));
    Py_INCREF(new_zoneinfo);

    let dt = (*slf.cast::<PyZonedDateTime>()).dt;
    let (new_date, new_time) = as_utc(dt.date, dt.time, dt.offset_seconds);
    let api = *(*ModuleState::from(Py_TYPE(slf))).datetime_api;
    let new_py_dt = propagate_exc!(PyObject_CallMethodOneArg(
        new_zoneinfo,
        py_str("fromutc"),
        (api.DateTime_FromDateAndTime)(
            new_date.year as c_int,
            new_date.month as c_int,
            new_date.day as c_int,
            new_time.hour as c_int,
            new_time.minute as c_int,
            new_time.second as c_int,
            (new_time.nanos / 1000) as c_int,
            new_zoneinfo,
            api.DateTimeType,
        ),
    ));

    let offset_delta = propagate_exc!(PyObject_CallMethodOneArg(
        new_zoneinfo,
        py_str("utcoffset"),
        new_py_dt,
    ));
    let offset_seconds = PyDateTime_DELTA_GET_DAYS(offset_delta) * 86400
        + PyDateTime_DELTA_GET_SECONDS(offset_delta);

    new_unchecked(
        Py_TYPE(slf),
        OffsetDateTime {
            date: Date {
                year: PyDateTime_GET_YEAR(new_py_dt) as u16,
                month: PyDateTime_GET_MONTH(new_py_dt) as u8,
                day: PyDateTime_GET_DAY(new_py_dt) as u8,
            },
            time: Time {
                hour: PyDateTime_DATE_GET_HOUR(new_py_dt) as u8,
                minute: PyDateTime_DATE_GET_MINUTE(new_py_dt) as u8,
                second: PyDateTime_DATE_GET_SECOND(new_py_dt) as u8,
                nanos: dt.time.nanos,
            },
            offset_seconds,
        },
        new_zoneinfo,
    )
    .cast()
}

pub(crate) unsafe extern "C" fn unpickle(
    module: *mut PyObject,
    _: *mut *mut PyObject,
    _: Py_ssize_t,
) -> *mut PyObject {
    let state: *mut ModuleState = PyModule_GetState(module).cast();
    new_unchecked(
        (*state).zoned_datetime_type,
        OffsetDateTime {
            date: Date {
                year: 2020,
                month: 1,
                day: 1,
            },
            time: Time {
                hour: 0,
                minute: 0,
                second: 0,
                nanos: 0,
            },
            offset_seconds: 0,
        },
        PyObject_CallOneArg((*state).zoneinfo_type.cast(), py_str("UTC")),
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
        ml_name: c_str!("as_zoned"),
        ml_meth: PyMethodDefPointer {
            PyCFunction: as_zoned,
        },
        ml_flags: METH_O,
        ml_doc: c_str!("Convert to a `ZonedDateTime` with given tz"),
    },
    PyMethodDef {
        ml_name: c_str!("exact_eq"),
        ml_meth: PyMethodDefPointer {
            PyCFunction: exact_eq,
        },
        ml_flags: METH_O,
        ml_doc: c_str!("Exact equality"),
    },
    PyMethodDef::zeroed(),
];

unsafe extern "C" fn get_year(slf: *mut PyObject, _: *mut c_void) -> *mut PyObject {
    PyLong_FromLong((*slf.cast::<PyZonedDateTime>()).dt.date.year as c_long)
}

unsafe extern "C" fn get_month(slf: *mut PyObject, _: *mut c_void) -> *mut PyObject {
    PyLong_FromLong((*slf.cast::<PyZonedDateTime>()).dt.date.month as c_long)
}

unsafe extern "C" fn get_day(slf: *mut PyObject, _: *mut c_void) -> *mut PyObject {
    PyLong_FromLong((*slf.cast::<PyZonedDateTime>()).dt.date.day as c_long)
}

unsafe extern "C" fn get_hour(slf: *mut PyObject, _: *mut c_void) -> *mut PyObject {
    PyLong_FromLong((*slf.cast::<PyZonedDateTime>()).dt.time.hour as c_long)
}

unsafe extern "C" fn get_minute(slf: *mut PyObject, _: *mut c_void) -> *mut PyObject {
    PyLong_FromLong((*slf.cast::<PyZonedDateTime>()).dt.time.minute as c_long)
}

unsafe extern "C" fn get_second(slf: *mut PyObject, _: *mut c_void) -> *mut PyObject {
    PyLong_FromLong((*slf.cast::<PyZonedDateTime>()).dt.time.second as c_long)
}

unsafe extern "C" fn get_nanos(slf: *mut PyObject, _: *mut c_void) -> *mut PyObject {
    PyLong_FromLong((*slf.cast::<PyZonedDateTime>()).dt.time.nanos as c_long)
}

unsafe extern "C" fn get_tz(slf: *mut PyObject, _: *mut c_void) -> *mut PyObject {
    let result = PyObject_GetAttrString((*slf.cast::<PyZonedDateTime>()).zoneinfo, c_str!("key"));
    Py_INCREF(result);
    result
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
        name: c_str!("tz"),
        get: Some(get_tz),
        set: None,
        doc: c_str!("The tz ID"),
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
    name: c_str!("whenever.ZonedDateTime"),
    basicsize: mem::size_of::<PyZonedDateTime>() as c_int,
    // TODO: is this right?
    itemsize: 0,
    flags: Py_TPFLAGS_DEFAULT as c_uint,
    slots: unsafe { SLOTS as *const [_] as *mut _ },
};
