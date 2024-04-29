use core::ffi::{c_int, c_long, c_void};
use core::ptr::null_mut as NULL;
use core::{mem, ptr};
use pyo3_ffi::*;

use crate::common::{c_str, py_str};

mod common;
pub mod date;
mod date_delta;
mod local_datetime;
pub mod naive_datetime;
mod offset_datetime;
mod time;
mod time_delta;
mod utc_datetime;
mod zoned_datetime;

static mut MODULE_DEF: PyModuleDef = PyModuleDef {
    m_base: PyModuleDef_HEAD_INIT,
    m_name: c_str!("whenever"),
    m_doc: c_str!("Fast and typesafe datetimes for Python, written in Rust"),
    m_size: mem::size_of::<State>() as _,
    m_methods: unsafe { METHODS as *const [_] as *mut _ },
    m_slots: unsafe { MODULE_SLOTS as *const [_] as *mut _ },
    m_traverse: Some(module_traverse),
    m_clear: Some(module_clear),
    m_free: Some(module_free),
};

static mut METHODS: &[PyMethodDef] = &[
    PyMethodDef {
        ml_name: c_str!("_unpkl_date"),
        ml_meth: PyMethodDefPointer {
            _PyCFunctionFast: date::unpickle,
        },
        ml_flags: METH_FASTCALL,
        ml_doc: NULL(),
    },
    PyMethodDef {
        ml_name: c_str!("_unpkl_time"),
        ml_meth: PyMethodDefPointer {
            _PyCFunctionFast: time::unpickle,
        },
        ml_flags: METH_FASTCALL,
        ml_doc: NULL(),
    },
    PyMethodDef {
        ml_name: c_str!("_unpkl_tdelta"),
        ml_meth: PyMethodDefPointer {
            _PyCFunctionFast: time_delta::unpickle,
        },
        ml_flags: METH_FASTCALL,
        ml_doc: NULL(),
    },
    PyMethodDef {
        ml_name: c_str!("_unpkl_ddelta"),
        ml_meth: PyMethodDefPointer {
            _PyCFunctionFast: date_delta::unpickle,
        },
        ml_flags: METH_FASTCALL,
        ml_doc: NULL(),
    },
    PyMethodDef {
        ml_name: c_str!("_unpkl_naive"),
        ml_meth: PyMethodDefPointer {
            _PyCFunctionFast: naive_datetime::unpickle,
        },
        ml_flags: METH_FASTCALL,
        ml_doc: NULL(),
    },
    PyMethodDef {
        ml_name: c_str!("_unpkl_utc"),
        ml_meth: PyMethodDefPointer {
            _PyCFunctionFast: utc_datetime::unpickle,
        },
        ml_flags: METH_FASTCALL,
        ml_doc: NULL(),
    },
    PyMethodDef {
        ml_name: c_str!("_unpkl_offset"),
        ml_meth: PyMethodDefPointer {
            _PyCFunctionFast: offset_datetime::unpickle,
        },
        ml_flags: METH_FASTCALL,
        ml_doc: NULL(),
    },
    PyMethodDef {
        ml_name: c_str!("_unpkl_zoned"),
        ml_meth: PyMethodDefPointer {
            _PyCFunctionFast: zoned_datetime::unpickle,
        },
        ml_flags: METH_FASTCALL,
        ml_doc: NULL(),
    },
    PyMethodDef {
        ml_name: c_str!("_unpkl_local"),
        ml_meth: PyMethodDefPointer {
            _PyCFunctionFast: local_datetime::unpickle,
        },
        ml_flags: METH_FASTCALL,
        ml_doc: NULL(),
    },
    PyMethodDef {
        ml_name: c_str!("years"),
        ml_meth: PyMethodDefPointer {
            PyCFunction: date_delta::years,
        },
        ml_flags: METH_O,
        ml_doc: c_str!("Create a new `DateDelta` representing the given number of years."),
    },
    PyMethodDef {
        // TODO: set __module__ on these
        ml_name: c_str!("months"),
        ml_meth: PyMethodDefPointer {
            PyCFunction: date_delta::months,
        },
        ml_flags: METH_O,
        ml_doc: c_str!("Create a new `DateDelta` representing the given number of months."),
    },
    PyMethodDef {
        ml_name: c_str!("weeks"),
        ml_meth: PyMethodDefPointer {
            PyCFunction: date_delta::weeks,
        },
        ml_flags: METH_O,
        ml_doc: c_str!("Create a new `DateDelta` representing the given number of weeks."),
    },
    PyMethodDef {
        ml_name: c_str!("days"),
        ml_meth: PyMethodDefPointer {
            PyCFunction: date_delta::days,
        },
        ml_flags: METH_O,
        ml_doc: c_str!("Create a new `DateDelta` representing the given number of days."),
    },
    PyMethodDef {
        ml_name: c_str!("hours"),
        ml_meth: PyMethodDefPointer {
            PyCFunction: time_delta::hours,
        },
        ml_flags: METH_O,
        ml_doc: c_str!("Create a new `TimeDelta` representing the given number of hours."),
    },
    PyMethodDef {
        ml_name: c_str!("minutes"),
        ml_meth: PyMethodDefPointer {
            PyCFunction: time_delta::minutes,
        },
        ml_flags: METH_O,
        ml_doc: c_str!("Create a new `TimeDelta` representing the given number of minutes."),
    },
    PyMethodDef {
        ml_name: c_str!("seconds"),
        ml_meth: PyMethodDefPointer {
            PyCFunction: time_delta::seconds,
        },
        ml_flags: METH_O,
        ml_doc: c_str!("Create a new `TimeDelta` representing the given number of seconds."),
    },
    PyMethodDef {
        ml_name: c_str!("milliseconds"),
        ml_meth: PyMethodDefPointer {
            PyCFunction: time_delta::milliseconds,
        },
        ml_flags: METH_O,
        ml_doc: c_str!("Create a new `TimeDelta` representing the given number of milliseconds."),
    },
    PyMethodDef {
        ml_name: c_str!("microseconds"),
        ml_meth: PyMethodDefPointer {
            PyCFunction: time_delta::microseconds,
        },
        ml_flags: METH_O,
        ml_doc: c_str!("Create a new `TimeDelta` representing the given number of microseconds."),
    },
    PyMethodDef {
        ml_name: c_str!("nanoseconds"),
        ml_meth: PyMethodDefPointer {
            PyCFunction: time_delta::nanoseconds,
        },
        ml_flags: METH_O,
        ml_doc: c_str!("Create a new `TimeDelta` representing the given number of nanoseconds."),
    },
    PyMethodDef::zeroed(),
];

static mut MODULE_SLOTS: &[PyModuleDef_Slot] = &[
    PyModuleDef_Slot {
        slot: Py_mod_exec,
        value: module_exec as *mut c_void,
    },
    #[cfg(Py_3_12)]
    PyModuleDef_Slot {
        slot: Py_mod_multiple_interpreters,
        // awaiting https://github.com/python/cpython/pull/102995
        value: Py_MOD_MULTIPLE_INTERPRETERS_NOT_SUPPORTED,
    },
    PyModuleDef_Slot {
        slot: 0,
        value: NULL(),
    },
];

#[cfg(Py_3_10)]
macro_rules! add {
    ($mptr:expr, $name:expr, $obj:expr) => {
        PyModule_AddObjectRef($mptr, c_str!($name), $obj);
    };
}

#[cfg(not(Py_3_10))]
macro_rules! add {
    ($mptr:expr, $name:expr, $obj:expr) => {
        PyModule_AddObject($mptr, c_str!($name), $obj);
    };
}

macro_rules! add_int {
    ($mptr:expr, $name:expr, $obj:expr) => {
        PyModule_AddIntConstant($mptr, c_str!($name), $obj as c_long);
    };
}

macro_rules! add_exc {
    ($mptr:expr, $state:ident, $name:expr, $varname:ident) => {
        let e = PyErr_NewException(c_str!(concat!("whenever.", $name)), NULL(), NULL());
        if e.is_null() {
            return -1;
        }
        add!($mptr, $name, e);
        $state.$varname = e.cast();
    };
}

macro_rules! add_type {
    ($module:ident,
     $module_nameobj:expr,
     $state:ident,
     $submodule:ident,
     $name:expr,
     $varname:ident,
     $unpickle_name:expr,
     $unpickle_var:ident,
     WITH_SINGLETONS) => {
        add_type!(
            $module,
            $module_nameobj,
            $state,
            $submodule,
            $name,
            $varname,
            $unpickle_name,
            $unpickle_var
        );

        for (name, value) in $submodule::SINGLETONS {
            let pyvalue = $submodule::new_unchecked($varname.cast(), value);
            PyDict_SetItemString(
                (*$varname.cast::<PyTypeObject>()).tp_dict,
                name.as_ptr().cast(),
                pyvalue.cast(),
            );
        }
    };
    ($module:ident,
     $module_nameobj:expr,
     $state:ident,
     $submodule:ident,
     $name:expr,
     $varname:ident,
     $unpickle_name:expr,
     $unpickle_var:ident) => {
        let $varname = PyType_FromModuleAndSpec(
            $module,
            ptr::addr_of_mut!($submodule::SPEC),
            ptr::null_mut(),
        );
        if $varname.is_null() {
            return -1;
        }
        add!($module, $name, $varname);
        $state.$varname = $varname.cast();

        let unpickler = PyObject_GetAttrString($module, c_str!($unpickle_name));
        PyObject_SetAttrString(unpickler, c_str!("__module__"), $module_nameobj);
        $state.$unpickle_var = unpickler;
    };
}

unsafe extern "C" fn module_exec(module: *mut PyObject) -> c_int {
    let state: &mut State = PyModule_GetState(module).cast::<State>().as_mut().unwrap();
    let module_name = py_str("whenever");

    add_type!(
        module,
        module_name,
        state,
        date,
        "Date",
        date_type,
        "_unpkl_date",
        unpickle_date
    );
    add_type!(
        module,
        module_name,
        state,
        time,
        "Time",
        time_type,
        "_unpkl_time",
        unpickle_time,
        WITH_SINGLETONS
    );
    add_type!(
        module,
        module_name,
        state,
        date_delta,
        "DateDelta",
        date_delta_type,
        "_unpkl_ddelta",
        unpickle_date_delta,
        WITH_SINGLETONS
    );
    add_type!(
        module,
        module_name,
        state,
        time_delta,
        "TimeDelta",
        time_delta_type,
        "_unpkl_tdelta",
        unpickle_time_delta,
        WITH_SINGLETONS
    );
    add_type!(
        module,
        module_name,
        state,
        naive_datetime,
        "NaiveDateTime",
        naive_datetime_type,
        "_unpkl_naive",
        unpickle_naive_datetime,
        WITH_SINGLETONS
    );
    add_type!(
        module,
        module_name,
        state,
        utc_datetime,
        "UTCDateTime",
        utc_datetime_type,
        "_unpkl_utc",
        unpickle_utc_datetime,
        WITH_SINGLETONS
    );
    add_type!(
        module,
        module_name,
        state,
        offset_datetime,
        "OffsetDateTime",
        offset_datetime_type,
        "_unpkl_offset",
        unpickle_offset_datetime
    );
    add_type!(
        module,
        module_name,
        state,
        zoned_datetime,
        "ZonedDateTime",
        zoned_datetime_type,
        "_unpkl_zoned",
        unpickle_zoned_datetime
    );
    add_type!(
        module,
        module_name,
        state,
        local_datetime,
        "LocalSystemDateTime",
        local_datetime_type,
        "_unpkl_local",
        unpickle_local_datetime
    );

    PyDict_SetItemString(
        (*state.utc_datetime_type).tp_dict,
        c_str!("offset"),
        time_delta::new_unchecked(
            state.time_delta_type,
            time_delta::TimeDelta::from_nanos_unchecked(0),
        ),
    );

    // zoneinfo module
    let zoneinfo_module = PyImport_ImportModule(c_str!("zoneinfo"));
    state.zoneinfo_type = PyObject_GetAttrString(zoneinfo_module, c_str!("ZoneInfo")).cast();
    Py_DECREF(zoneinfo_module);

    // datetime module
    PyDateTime_IMPORT();
    match PyDateTimeAPI().as_ref() {
        Some(api) => state.datetime_api = api,
        None => return -1,
    }

    let datetime_module = PyImport_ImportModule(c_str!("datetime"));
    state.strptime = PyObject_GetAttrString(
        PyObject_GetAttrString(datetime_module, c_str!("datetime")),
        c_str!("strptime"),
    );
    state.timezone_type = PyObject_GetAttrString(datetime_module, c_str!("timezone")).cast();
    Py_DECREF(datetime_module);

    let email_utils = PyImport_ImportModule(c_str!("email.utils"));
    state.format_rfc2822 = PyObject_GetAttrString(email_utils, c_str!("format_datetime")).cast();
    state.parse_rfc2822 =
        PyObject_GetAttrString(email_utils, c_str!("parsedate_to_datetime")).cast();
    Py_DECREF(email_utils);

    // TODO: a proper enum
    add_int!(module, "MONDAY", 1);
    add_int!(module, "TUESDAY", 2);
    add_int!(module, "WEDNESDAY", 3);
    add_int!(module, "THURSDAY", 4);
    add_int!(module, "FRIDAY", 5);
    add_int!(module, "SATURDAY", 6);
    add_int!(module, "SUNDAY", 7);

    state.str_years = PyUnicode_InternFromString(c_str!("years"));
    state.str_months = PyUnicode_InternFromString(c_str!("months"));
    state.str_weeks = PyUnicode_InternFromString(c_str!("weeks"));
    state.str_days = PyUnicode_InternFromString(c_str!("days"));
    state.str_hours = PyUnicode_InternFromString(c_str!("hours"));
    state.str_minutes = PyUnicode_InternFromString(c_str!("minutes"));
    state.str_seconds = PyUnicode_InternFromString(c_str!("seconds"));
    state.str_milliseconds = PyUnicode_InternFromString(c_str!("milliseconds"));
    state.str_microseconds = PyUnicode_InternFromString(c_str!("microseconds"));
    state.str_nanoseconds = PyUnicode_InternFromString(c_str!("nanoseconds"));
    state.str_year = PyUnicode_InternFromString(c_str!("year"));
    state.str_month = PyUnicode_InternFromString(c_str!("month"));
    state.str_day = PyUnicode_InternFromString(c_str!("day"));
    state.str_hour = PyUnicode_InternFromString(c_str!("hour"));
    state.str_minute = PyUnicode_InternFromString(c_str!("minute"));
    state.str_second = PyUnicode_InternFromString(c_str!("second"));
    state.str_nanosecond = PyUnicode_InternFromString(c_str!("nanosecond"));
    state.str_nanos = PyUnicode_InternFromString(c_str!("nanos"));
    state.str_raise = PyUnicode_InternFromString(c_str!("raise"));
    state.str_tz = PyUnicode_InternFromString(c_str!("tz"));
    state.str_disambiguate = PyUnicode_InternFromString(c_str!("disambiguate"));
    state.str_offset = PyUnicode_InternFromString(c_str!("offset"));

    add_exc!(module, state, "AmbiguousTime", exc_ambiguous);
    add_exc!(module, state, "SkippedTime", exc_skipped);
    add_exc!(module, state, "InvalidOffset", exc_invalid_offset);

    0
}

unsafe extern "C" fn module_traverse(
    module: *mut PyObject,
    visit: visitproc,
    arg: *mut c_void,
) -> c_int {
    let state = State::for_mod(module);

    // types
    let date_type: *mut PyObject = state.date_type.cast();
    if !date_type.is_null() {
        (visit)(date_type, arg);
    };
    let time_type: *mut PyObject = state.time_type.cast();
    if !time_type.is_null() {
        (visit)(time_type, arg);
    };
    let date_delta_type: *mut PyObject = state.date_delta_type.cast();
    if !date_delta_type.is_null() {
        (visit)(date_delta_type, arg);
    };
    let time_delta_type: *mut PyObject = state.time_delta_type.cast();
    if !time_delta_type.is_null() {
        (visit)(time_delta_type, arg);
    };
    let naive_datetime_type: *mut PyObject = state.naive_datetime_type.cast();
    if !naive_datetime_type.is_null() {
        (visit)(naive_datetime_type, arg);
    };
    let utc_datetime_type: *mut PyObject = state.utc_datetime_type.cast();
    if !utc_datetime_type.is_null() {
        (visit)(utc_datetime_type, arg);
    };
    let offset_datetime_type: *mut PyObject = state.offset_datetime_type.cast();
    if !offset_datetime_type.is_null() {
        (visit)(offset_datetime_type, arg);
    };
    let zoned_datetime_type: *mut PyObject = state.zoned_datetime_type.cast();
    if !zoned_datetime_type.is_null() {
        (visit)(zoned_datetime_type, arg);
    };
    let local_datetime_type: *mut PyObject = state.local_datetime_type.cast();
    if !local_datetime_type.is_null() {
        (visit)(local_datetime_type, arg);
    };

    // Imported modules
    let zoneinfo_type: *mut PyObject = state.zoneinfo_type.cast();
    if !zoneinfo_type.is_null() {
        (visit)(zoneinfo_type, arg);
    };

    let timezone_type: *mut PyObject = state.timezone_type.cast();
    if !timezone_type.is_null() {
        (visit)(timezone_type, arg);
    };

    0
}

unsafe extern "C" fn module_clear(module: *mut PyObject) -> c_int {
    let state = PyModule_GetState(module).cast::<State>().as_mut().unwrap();
    // types
    Py_CLEAR(ptr::addr_of_mut!(state.date_type).cast());
    Py_CLEAR(ptr::addr_of_mut!(state.time_type).cast());
    Py_CLEAR(ptr::addr_of_mut!(state.date_delta_type).cast());
    Py_CLEAR(ptr::addr_of_mut!(state.time_delta_type).cast());
    Py_CLEAR(ptr::addr_of_mut!(state.naive_datetime_type).cast());
    Py_CLEAR(ptr::addr_of_mut!(state.utc_datetime_type).cast());
    Py_CLEAR(ptr::addr_of_mut!(state.offset_datetime_type).cast());
    Py_CLEAR(ptr::addr_of_mut!(state.zoned_datetime_type).cast());
    Py_CLEAR(ptr::addr_of_mut!(state.local_datetime_type).cast());

    // unpickling functions
    Py_CLEAR(ptr::addr_of_mut!(state.unpickle_date).cast());
    Py_CLEAR(ptr::addr_of_mut!(state.unpickle_time).cast());
    Py_CLEAR(ptr::addr_of_mut!(state.unpickle_date_delta).cast());
    Py_CLEAR(ptr::addr_of_mut!(state.unpickle_time_delta).cast());
    Py_CLEAR(ptr::addr_of_mut!(state.unpickle_naive_datetime).cast());
    Py_CLEAR(ptr::addr_of_mut!(state.unpickle_utc_datetime).cast());
    Py_CLEAR(ptr::addr_of_mut!(state.unpickle_offset_datetime).cast());
    Py_CLEAR(ptr::addr_of_mut!(state.unpickle_zoned_datetime).cast());
    Py_CLEAR(ptr::addr_of_mut!(state.unpickle_local_datetime).cast());

    // TODO: check if this is at all sensible
    // imported modules
    Py_CLEAR(ptr::addr_of_mut!(state.zoneinfo_type).cast());
    0
}

unsafe extern "C" fn module_free(module: *mut c_void) {
    module_clear(module.cast());
}

#[repr(C)]
struct State<'a> {
    // types
    date_type: *mut PyTypeObject,
    time_type: *mut PyTypeObject,
    date_delta_type: *mut PyTypeObject,
    time_delta_type: *mut PyTypeObject,
    naive_datetime_type: *mut PyTypeObject,
    utc_datetime_type: *mut PyTypeObject,
    offset_datetime_type: *mut PyTypeObject,
    zoned_datetime_type: *mut PyTypeObject,
    local_datetime_type: *mut PyTypeObject,

    // exceptions
    exc_ambiguous: *mut PyTypeObject,
    exc_skipped: *mut PyTypeObject,
    exc_invalid_offset: *mut PyTypeObject,

    // unpickling functions
    unpickle_date: *mut PyObject,
    unpickle_time: *mut PyObject,
    unpickle_date_delta: *mut PyObject,
    unpickle_time_delta: *mut PyObject,
    unpickle_naive_datetime: *mut PyObject,
    unpickle_utc_datetime: *mut PyObject,
    unpickle_offset_datetime: *mut PyObject,
    unpickle_zoned_datetime: *mut PyObject,
    unpickle_local_datetime: *mut PyObject,

    // imported stuff
    zoneinfo_type: *mut PyTypeObject,
    datetime_api: &'a PyDateTime_CAPI,
    strptime: *mut PyObject,
    timezone_type: *mut PyTypeObject,
    format_rfc2822: *mut PyObject,
    parse_rfc2822: *mut PyObject,

    // strings
    str_years: *mut PyObject,
    str_months: *mut PyObject,
    str_weeks: *mut PyObject,
    str_days: *mut PyObject,
    str_hours: *mut PyObject,
    str_minutes: *mut PyObject,
    str_seconds: *mut PyObject,
    str_milliseconds: *mut PyObject,
    str_microseconds: *mut PyObject,
    str_nanoseconds: *mut PyObject,
    str_year: *mut PyObject,
    str_month: *mut PyObject,
    str_day: *mut PyObject,
    str_hour: *mut PyObject,
    str_minute: *mut PyObject,
    str_second: *mut PyObject,
    str_nanosecond: *mut PyObject,
    str_nanos: *mut PyObject,
    str_raise: *mut PyObject,
    str_tz: *mut PyObject,
    str_disambiguate: *mut PyObject,
    str_offset: *mut PyObject,
}

impl State<'_> {
    unsafe fn for_type<'a>(tp: *mut PyTypeObject) -> &'a Self {
        PyType_GetModuleState(tp).cast::<Self>().as_ref().unwrap()
    }

    unsafe fn for_mod<'a>(module: *mut PyObject) -> &'a Self {
        PyModule_GetState(module).cast::<Self>().as_ref().unwrap()
    }

    unsafe fn for_obj<'a>(obj: *mut PyObject) -> &'a Self {
        PyType_GetModuleState(Py_TYPE(obj))
            .cast::<Self>()
            .as_mut()
            .unwrap()
    }
}

#[allow(non_snake_case)]
#[no_mangle]
pub unsafe extern "C" fn PyInit__whenever() -> *mut PyObject {
    PyModuleDef_Init(ptr::addr_of_mut!(MODULE_DEF))
}
