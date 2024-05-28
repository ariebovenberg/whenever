use core::ffi::{c_char, c_int, c_long, c_void};
use core::ptr::null_mut as NULL;
use core::{mem, ptr};
use pyo3_ffi::*;

use crate::common::*;

mod common;
pub mod date;
mod date_delta;
mod datetime_delta;
mod local_datetime;
pub mod naive_datetime;
mod offset_datetime;
mod time;
mod time_delta;
mod utc_datetime;
mod zoned_datetime;

use date::unpickle as _unpkl_date;
use date_delta::unpickle as _unpkl_ddelta;
use date_delta::{days, months, weeks, years};
use datetime_delta::unpickle as _unpkl_dtdelta;
use local_datetime::unpickle as _unpkl_local;
use naive_datetime::unpickle as _unpkl_naive;
use offset_datetime::unpickle as _unpkl_offset;
use time::unpickle as _unpkl_time;
use time_delta::unpickle as _unpkl_tdelta;
use time_delta::{hours, microseconds, milliseconds, minutes, nanoseconds, seconds};
use utc_datetime::unpickle as _unpkl_utc;
use zoned_datetime::unpickle as _unpkl_zoned;

static mut MODULE_DEF: PyModuleDef = PyModuleDef {
    m_base: PyModuleDef_HEAD_INIT,
    m_name: c_str!("whenever"),
    m_doc: c_str!("A better datetime API for Python, written in Rust"),
    m_size: mem::size_of::<State>() as _,
    m_methods: unsafe { METHODS as *const [_] as *mut _ },
    m_slots: unsafe { MODULE_SLOTS as *const [_] as *mut _ },
    m_traverse: Some(module_traverse),
    m_clear: Some(module_clear),
    m_free: Some(module_free),
};

static mut METHODS: &[PyMethodDef] = &[
    method!(_unpkl_date, "", METH_O),
    method!(_unpkl_time, "", METH_O),
    method!(_unpkl_tdelta, "", METH_O),
    method_vararg!(_unpkl_ddelta, ""),
    method_vararg!(_unpkl_dtdelta, ""),
    method!(_unpkl_naive, "", METH_O),
    method!(_unpkl_utc, "", METH_O),
    method!(_unpkl_offset, "", METH_O),
    method_vararg!(_unpkl_zoned, ""),
    method!(_unpkl_local, "", METH_O),
    // FUTURE: set __module__ on these
    method!(
        years,
        "Create a new `DateDelta` representing the given number of years.",
        METH_O
    ),
    method!(
        months,
        "Create a new `DateDelta` representing the given number of months.",
        METH_O
    ),
    method!(
        weeks,
        "Create a new `DateDelta` representing the given number of weeks.",
        METH_O
    ),
    method!(
        days,
        "Create a new `DateDelta` representing the given number of days.",
        METH_O
    ),
    method!(
        hours,
        "Create a new `TimeDelta` representing the given number of hours.",
        METH_O
    ),
    method!(
        minutes,
        "Create a new `TimeDelta` representing the given number of minutes.",
        METH_O
    ),
    method!(
        seconds,
        "Create a new `TimeDelta` representing the given number of seconds.",
        METH_O
    ),
    method!(
        milliseconds,
        "Create a new `TimeDelta` representing the given number of milliseconds.",
        METH_O
    ),
    method!(
        microseconds,
        "Create a new `TimeDelta` representing the given number of microseconds.",
        METH_O
    ),
    method!(
        nanoseconds,
        "Create a new `TimeDelta` representing the given number of nanoseconds.",
        METH_O
    ),
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
    // FUTURE: set no_gil slot (peps.python.org/pep-0703/#py-mod-gil-slot)
    PyModuleDef_Slot {
        slot: 0,
        value: NULL(),
    },
];

unsafe fn create_enum(name: *const c_char, members: &[(*const c_char, i32)]) -> PyReturn {
    let members_dict = PyDict_New().as_result()?;
    defer_decref!(members_dict);
    for &(name, value) in members {
        if PyDict_SetItemString(members_dict, name, steal!(value.to_py()?)) == -1 {
            return Err(py_err!());
        }
    }
    let enum_module = PyImport_ImportModule(c_str!("enum")).as_result()?;
    defer_decref!(enum_module);
    PyObject_CallMethod(
        enum_module,
        c_str!("Enum"),
        c_str!("sO"),
        name,
        members_dict,
    )
    .as_result()
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
        defer_decref!(e);
        if PyModule_AddType($mptr, e.cast()) != 0 {
            return -1;
        }
        $state.$varname = e;
    };
}

macro_rules! add_type {
    ($module:ident,
     $module_nameobj:expr,
     $state:ident,
     $submodule:ident,
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
        defer_decref!($varname);
        if PyModule_AddType($module, $varname.cast()) != 0 {
            return -1;
        }
        $state.$varname = $varname.cast();

        let unpickler = PyObject_GetAttrString($module, c_str!($unpickle_name));
        PyObject_SetAttrString(unpickler, c_str!("__module__"), $module_nameobj);
        $state.$unpickle_var = unpickler;

        // TODO: set these in a way that we don't need to support GC
        for (name, value) in $submodule::SINGLETONS {
            let pyvalue = match value.to_obj($varname.cast()) {
                Ok(v) => v,
                Err(_) => return -1,
            };
            PyDict_SetItemString(
                (*$varname.cast::<PyTypeObject>()).tp_dict,
                name.as_ptr().cast(),
                pyvalue,
            );
        }
    };
}

unsafe extern "C" fn module_exec(module: *mut PyObject) -> c_int {
    let state: &mut State = PyModule_GetState(module).cast::<State>().as_mut().unwrap();
    let module_name = match "whenever".to_py() {
        Ok(name) => name,
        Err(_) => return -1,
    };
    defer_decref!(module_name);

    add_type!(
        module,
        module_name,
        state,
        date,
        date_type,
        "_unpkl_date",
        unpickle_date
    );
    add_type!(
        module,
        module_name,
        state,
        time,
        time_type,
        "_unpkl_time",
        unpickle_time
    );
    add_type!(
        module,
        module_name,
        state,
        date_delta,
        date_delta_type,
        "_unpkl_ddelta",
        unpickle_date_delta
    );
    add_type!(
        module,
        module_name,
        state,
        time_delta,
        time_delta_type,
        "_unpkl_tdelta",
        unpickle_time_delta
    );
    add_type!(
        module,
        module_name,
        state,
        datetime_delta,
        datetime_delta_type,
        "_unpkl_dtdelta",
        unpickle_datetime_delta
    );
    add_type!(
        module,
        module_name,
        state,
        naive_datetime,
        naive_datetime_type,
        "_unpkl_naive",
        unpickle_naive_datetime
    );
    add_type!(
        module,
        module_name,
        state,
        utc_datetime,
        utc_datetime_type,
        "_unpkl_utc",
        unpickle_utc_datetime
    );
    add_type!(
        module,
        module_name,
        state,
        offset_datetime,
        offset_datetime_type,
        "_unpkl_offset",
        unpickle_offset_datetime
    );
    add_type!(
        module,
        module_name,
        state,
        zoned_datetime,
        zoned_datetime_type,
        "_unpkl_zoned",
        unpickle_zoned_datetime
    );
    add_type!(
        module,
        module_name,
        state,
        local_datetime,
        local_datetime_type,
        "_unpkl_local",
        unpickle_local_datetime
    );

    PyDict_SetItemString(
        (*state.utc_datetime_type).tp_dict,
        c_str!("offset"),
        steal!(
            match time_delta::TimeDelta::from_nanos_unchecked(0).to_obj(state.time_delta_type) {
                Ok(v) => v,
                Err(_) => return -1,
            }
        ),
    );

    // zoneinfo module
    let zoneinfo_module = PyImport_ImportModule(c_str!("zoneinfo"));
    defer_decref!(zoneinfo_module);
    state.zoneinfo_type = PyObject_GetAttrString(zoneinfo_module, c_str!("ZoneInfo"));

    // datetime C API
    PyDateTime_IMPORT();
    match PyDateTimeAPI().as_ref() {
        Some(api) => state.py_api = api,
        None => return -1,
    }

    let datetime_module = PyImport_ImportModule(c_str!("datetime"));
    defer_decref!(datetime_module);
    state.strptime = PyObject_GetAttrString(
        steal!(PyObject_GetAttrString(datetime_module, c_str!("datetime"))),
        c_str!("strptime"),
    );
    state.timezone_type = PyObject_GetAttrString(datetime_module, c_str!("timezone")).cast();

    let email_utils = PyImport_ImportModule(c_str!("email.utils"));
    defer_decref!(email_utils);
    state.format_rfc2822 = PyObject_GetAttrString(email_utils, c_str!("format_datetime")).cast();
    state.parse_rfc2822 =
        PyObject_GetAttrString(email_utils, c_str!("parsedate_to_datetime")).cast();

    let weekday_enum = match create_enum(
        c_str!("Weekday"),
        &[
            (c_str!("MONDAY"), 1),
            (c_str!("TUESDAY"), 2),
            (c_str!("WEDNESDAY"), 3),
            (c_str!("THURSDAY"), 4),
            (c_str!("FRIDAY"), 5),
            (c_str!("SATURDAY"), 6),
            (c_str!("SUNDAY"), 7),
        ],
    ) {
        Err(_) => return -1,
        Ok(v) => v,
    } as *mut PyObject;
    defer_decref!(weekday_enum);
    if PyModule_AddType(module, weekday_enum.cast()) != 0 {
        return -1;
    }

    state.weekday_enum_members = [
        PyObject_GetAttrString(weekday_enum, c_str!("MONDAY")),
        PyObject_GetAttrString(weekday_enum, c_str!("TUESDAY")),
        PyObject_GetAttrString(weekday_enum, c_str!("WEDNESDAY")),
        PyObject_GetAttrString(weekday_enum, c_str!("THURSDAY")),
        PyObject_GetAttrString(weekday_enum, c_str!("FRIDAY")),
        PyObject_GetAttrString(weekday_enum, c_str!("SATURDAY")),
        PyObject_GetAttrString(weekday_enum, c_str!("SUNDAY")),
    ];

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

macro_rules! visit {
    ($target:expr, $visit:ident, $arg:ident) => {
        let obj: *mut PyObject = $target.cast();
        if !obj.is_null() {
            ($visit)(obj, $arg);
        }
    };
}

unsafe extern "C" fn module_traverse(
    module: *mut PyObject,
    visit: visitproc,
    arg: *mut c_void,
) -> c_int {
    let state = State::for_mod(module);

    // types
    visit!(state.date_type, visit, arg);
    visit!(state.time_type, visit, arg);
    visit!(state.date_delta_type, visit, arg);
    visit!(state.time_delta_type, visit, arg);
    visit!(state.datetime_delta_type, visit, arg);
    visit!(state.naive_datetime_type, visit, arg);
    visit!(state.utc_datetime_type, visit, arg);
    visit!(state.offset_datetime_type, visit, arg);
    visit!(state.zoned_datetime_type, visit, arg);
    visit!(state.local_datetime_type, visit, arg);

    // enum members
    visit!(state.weekday_enum_members[0], visit, arg);
    visit!(state.weekday_enum_members[1], visit, arg);
    visit!(state.weekday_enum_members[2], visit, arg);
    visit!(state.weekday_enum_members[3], visit, arg);
    visit!(state.weekday_enum_members[4], visit, arg);
    visit!(state.weekday_enum_members[5], visit, arg);
    visit!(state.weekday_enum_members[6], visit, arg);

    // interned strings
    visit!(state.str_years, visit, arg);
    visit!(state.str_months, visit, arg);
    visit!(state.str_weeks, visit, arg);
    visit!(state.str_days, visit, arg);
    visit!(state.str_hours, visit, arg);
    visit!(state.str_minutes, visit, arg);
    visit!(state.str_seconds, visit, arg);
    visit!(state.str_milliseconds, visit, arg);
    visit!(state.str_microseconds, visit, arg);
    visit!(state.str_nanoseconds, visit, arg);
    visit!(state.str_year, visit, arg);
    visit!(state.str_month, visit, arg);
    visit!(state.str_day, visit, arg);
    visit!(state.str_hour, visit, arg);
    visit!(state.str_minute, visit, arg);
    visit!(state.str_second, visit, arg);
    visit!(state.str_nanosecond, visit, arg);
    visit!(state.str_nanos, visit, arg);
    visit!(state.str_raise, visit, arg);
    visit!(state.str_tz, visit, arg);
    visit!(state.str_disambiguate, visit, arg);
    visit!(state.str_offset, visit, arg);

    // exceptions
    visit!(state.exc_ambiguous, visit, arg);
    visit!(state.exc_skipped, visit, arg);
    visit!(state.exc_invalid_offset, visit, arg);

    // Imported modules
    visit!(state.zoneinfo_type, visit, arg);
    visit!(state.timezone_type, visit, arg);
    0
}

unsafe extern "C" fn module_clear(module: *mut PyObject) -> c_int {
    let state = PyModule_GetState(module).cast::<State>().as_mut().unwrap();
    // types
    Py_CLEAR(ptr::addr_of_mut!(state.date_type).cast());
    Py_CLEAR(ptr::addr_of_mut!(state.time_type).cast());
    Py_CLEAR(ptr::addr_of_mut!(state.date_delta_type).cast());
    Py_CLEAR(ptr::addr_of_mut!(state.time_delta_type).cast());
    Py_CLEAR(ptr::addr_of_mut!(state.datetime_delta_type).cast());
    Py_CLEAR(ptr::addr_of_mut!(state.naive_datetime_type).cast());
    Py_CLEAR(ptr::addr_of_mut!(state.utc_datetime_type).cast());
    Py_CLEAR(ptr::addr_of_mut!(state.offset_datetime_type).cast());
    Py_CLEAR(ptr::addr_of_mut!(state.zoned_datetime_type).cast());
    Py_CLEAR(ptr::addr_of_mut!(state.local_datetime_type).cast());

    // enum members
    Py_CLEAR(ptr::addr_of_mut!(state.weekday_enum_members[0]));
    Py_CLEAR(ptr::addr_of_mut!(state.weekday_enum_members[1]));
    Py_CLEAR(ptr::addr_of_mut!(state.weekday_enum_members[2]));
    Py_CLEAR(ptr::addr_of_mut!(state.weekday_enum_members[3]));
    Py_CLEAR(ptr::addr_of_mut!(state.weekday_enum_members[4]));
    Py_CLEAR(ptr::addr_of_mut!(state.weekday_enum_members[5]));
    Py_CLEAR(ptr::addr_of_mut!(state.weekday_enum_members[6]));

    // exceptions
    Py_CLEAR(ptr::addr_of_mut!(state.exc_ambiguous));
    Py_CLEAR(ptr::addr_of_mut!(state.exc_skipped));
    Py_CLEAR(ptr::addr_of_mut!(state.exc_invalid_offset));

    // imported modules
    Py_CLEAR(ptr::addr_of_mut!(state.zoneinfo_type));
    Py_CLEAR(ptr::addr_of_mut!(state.timezone_type));
    Py_CLEAR(ptr::addr_of_mut!(state.strptime));
    Py_CLEAR(ptr::addr_of_mut!(state.format_rfc2822));
    Py_CLEAR(ptr::addr_of_mut!(state.parse_rfc2822));
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
    datetime_delta_type: *mut PyTypeObject,
    naive_datetime_type: *mut PyTypeObject,
    utc_datetime_type: *mut PyTypeObject,
    offset_datetime_type: *mut PyTypeObject,
    zoned_datetime_type: *mut PyTypeObject,
    local_datetime_type: *mut PyTypeObject,

    // weekday enum
    weekday_enum_members: [*mut PyObject; 7],

    // exceptions
    exc_ambiguous: *mut PyObject,
    exc_skipped: *mut PyObject,
    exc_invalid_offset: *mut PyObject,

    // unpickling functions
    unpickle_date: *mut PyObject,
    unpickle_time: *mut PyObject,
    unpickle_date_delta: *mut PyObject,
    unpickle_time_delta: *mut PyObject,
    unpickle_datetime_delta: *mut PyObject,
    unpickle_naive_datetime: *mut PyObject,
    unpickle_utc_datetime: *mut PyObject,
    unpickle_offset_datetime: *mut PyObject,
    unpickle_zoned_datetime: *mut PyObject,
    unpickle_local_datetime: *mut PyObject,

    py_api: &'a PyDateTime_CAPI,

    // imported stuff
    zoneinfo_type: *mut PyObject,
    timezone_type: *mut PyObject,
    strptime: *mut PyObject,
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
            .as_ref()
            .unwrap()
    }
}

#[allow(clippy::missing_safety_doc)]
#[allow(non_snake_case)]
#[no_mangle]
pub unsafe extern "C" fn PyInit__whenever() -> *mut PyObject {
    PyModuleDef_Init(ptr::addr_of_mut!(MODULE_DEF))
}
