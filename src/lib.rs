use core::ffi::{c_int, c_void, CStr};
use core::ptr::null_mut as NULL;
use core::{mem, ptr};
use pyo3_ffi::*;

use crate::common::*;

mod common;
pub mod date;
mod date_delta;
mod datetime_delta;
mod instant;
pub mod naive_datetime;
mod offset_datetime;
mod system_datetime;
mod time;
mod time_delta;
mod zoned_datetime;

use date::unpickle as _unpkl_date;
use date_delta::unpickle as _unpkl_ddelta;
use date_delta::{days, months, weeks, years};
use datetime_delta::unpickle as _unpkl_dtdelta;
use instant::unpickle as _unpkl_utc;
use naive_datetime::unpickle as _unpkl_naive;
use offset_datetime::unpickle as _unpkl_offset;
use system_datetime::unpickle as _unpkl_system;
use time::unpickle as _unpkl_time;
use time_delta::unpickle as _unpkl_tdelta;
use time_delta::{hours, microseconds, milliseconds, minutes, nanoseconds, seconds};
use zoned_datetime::unpickle as _unpkl_zoned;

static mut MODULE_DEF: PyModuleDef = PyModuleDef {
    m_base: PyModuleDef_HEAD_INIT,
    m_name: c"whenever".as_ptr(),
    m_doc: c"A better datetime API for Python, written in Rust".as_ptr(),
    m_size: mem::size_of::<State>() as _,
    m_methods: unsafe { METHODS.as_ptr() as *mut _ },
    m_slots: unsafe { MODULE_SLOTS.as_ptr() as *mut _ },
    m_traverse: Some(module_traverse),
    m_clear: Some(module_clear),
    // XXX: m_free likely not needed, since m_clear clears all references,
    // and the module state is deallocated along with the module.
    // See https://github.com/python/cpython/blob/c3b6dbff2c8886de1edade737febe85dd47ff4d0/Modules/xxlimited.c#L429C1-L431C8
    m_free: None,
};

static mut METHODS: &[PyMethodDef] = &[
    method!(_unpkl_date, "", METH_O),
    method!(_unpkl_time, "", METH_O),
    method_vararg!(_unpkl_ddelta, ""),
    method!(_unpkl_tdelta, "", METH_O),
    method_vararg!(_unpkl_dtdelta, ""),
    method!(_unpkl_naive, "", METH_O),
    method!(_unpkl_utc, "", METH_O),
    method!(_unpkl_offset, "", METH_O),
    method_vararg!(_unpkl_zoned, ""),
    method!(_unpkl_system, "", METH_O),
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

#[allow(non_upper_case_globals)]
pub const Py_mod_gil: c_int = 4;
#[allow(non_upper_case_globals)]
pub const Py_MOD_GIL_NOT_USED: *mut c_void = 1 as *mut c_void;

static mut MODULE_SLOTS: &[PyModuleDef_Slot] = &[
    PyModuleDef_Slot {
        slot: Py_mod_exec,
        value: module_exec as *mut c_void,
    },
    #[cfg(Py_3_13)]
    PyModuleDef_Slot {
        slot: Py_mod_multiple_interpreters,
        // awaiting https://github.com/python/cpython/pull/102995
        value: Py_MOD_PER_INTERPRETER_GIL_SUPPORTED,
    },
    #[cfg(Py_3_13)]
    PyModuleDef_Slot {
        slot: Py_mod_gil,
        value: Py_MOD_GIL_NOT_USED,
    },
    // FUTURE: set no_gil slot (peps.python.org/pep-0703/#py-mod-gil-slot)
    PyModuleDef_Slot {
        slot: 0,
        value: NULL(),
    },
];

unsafe fn create_enum(name: &CStr, members: &[(&CStr, i32)]) -> PyReturn {
    let members_dict = PyDict_New().as_result()?;
    defer_decref!(members_dict);
    for &(key, value) in members {
        if PyDict_SetItemString(members_dict, key.as_ptr(), steal!(value.to_py()?)) == -1 {
            return Err(py_err!());
        }
    }
    let enum_module = PyImport_ImportModule(c"enum".as_ptr()).as_result()?;
    defer_decref!(enum_module);
    PyObject_CallMethod(
        enum_module,
        c"Enum".as_ptr(),
        c"sO".as_ptr(),
        name.as_ptr(),
        members_dict,
    )
    .as_result()
}

unsafe fn new_exc(module: *mut PyObject, name: &CStr) -> *mut PyObject {
    let e = PyErr_NewException(name.as_ptr(), NULL(), NULL());
    if e.is_null() {
        return NULL();
    }
    defer_decref!(e);
    if PyModule_AddType(module, e.cast()) != 0 {
        return NULL();
    }
    e
}

macro_rules! add_type {
    ($module:ident,
     $module_nameobj:expr,
     $state:ident,
     $submodule:ident,
     $varname:ident,
     $unpickle_name:literal,
     $unpickle_var:ident) => {
        let $varname = null_to_errcode!(PyType_FromModuleAndSpec(
            $module,
            ptr::addr_of_mut!($submodule::SPEC),
            ptr::null_mut(),
        ));
        if PyModule_AddType($module, $varname.cast()) != 0 {
            return -1;
        }
        $state.$varname = $varname.cast();

        let unpickler = PyObject_GetAttrString($module, $unpickle_name.as_ptr());
        defer_decref!(unpickler);
        PyObject_SetAttrString(unpickler, c"__module__".as_ptr(), $module_nameobj);
        $state.$unpickle_var = unpickler;

        for (name, value) in $submodule::SINGLETONS {
            let pyvalue = unwrap_or_errcode!(value.to_obj($varname.cast()));
            // NOTE: we don't decref the value here on purpose.
            // Singletons work out refcount/GC-wise in the end.
            PyDict_SetItemString(
                (*$varname.cast::<PyTypeObject>()).tp_dict,
                name.as_ptr().cast(),
                pyvalue,
            );
        }
    };
}

macro_rules! unwrap_or_errcode {
    ($expr:expr) => {
        match $expr {
            Ok(v) => v,
            Err(_) => return -1,
        }
    };
}

macro_rules! null_to_errcode {
    ($expr:expr) => {
        match $expr {
            x if x.is_null() => return -1,
            x => x,
        }
    };
}

unsafe extern "C" fn module_exec(module: *mut PyObject) -> c_int {
    let state: &mut State = PyModule_GetState(module).cast::<State>().as_mut().unwrap();
    let module_name = unwrap_or_errcode!("whenever".to_py());
    defer_decref!(module_name);

    add_type!(
        module,
        module_name,
        state,
        date,
        date_type,
        c"_unpkl_date",
        unpickle_date
    );
    add_type!(
        module,
        module_name,
        state,
        time,
        time_type,
        c"_unpkl_time",
        unpickle_time
    );
    add_type!(
        module,
        module_name,
        state,
        date_delta,
        date_delta_type,
        c"_unpkl_ddelta",
        unpickle_date_delta
    );
    add_type!(
        module,
        module_name,
        state,
        time_delta,
        time_delta_type,
        c"_unpkl_tdelta",
        unpickle_time_delta
    );
    add_type!(
        module,
        module_name,
        state,
        datetime_delta,
        datetime_delta_type,
        c"_unpkl_dtdelta",
        unpickle_datetime_delta
    );
    add_type!(
        module,
        module_name,
        state,
        naive_datetime,
        naive_datetime_type,
        c"_unpkl_naive",
        unpickle_naive_datetime
    );
    add_type!(
        module,
        module_name,
        state,
        instant,
        instant_type,
        c"_unpkl_utc",
        unpickle_instant
    );
    add_type!(
        module,
        module_name,
        state,
        offset_datetime,
        offset_datetime_type,
        c"_unpkl_offset",
        unpickle_offset_datetime
    );
    add_type!(
        module,
        module_name,
        state,
        zoned_datetime,
        zoned_datetime_type,
        c"_unpkl_zoned",
        unpickle_zoned_datetime
    );
    add_type!(
        module,
        module_name,
        state,
        system_datetime,
        system_datetime_type,
        c"_unpkl_system",
        unpickle_system_datetime
    );

    // XXX: this SEEMS to work out refcount- and GC-wise
    PyDict_SetItemString(
        (*state.instant_type).tp_dict,
        c"offset".as_ptr(),
        steal!(unwrap_or_errcode!(PyDict_GetItemString(
            (*state.time_delta_type).tp_dict,
            c"ZERO".as_ptr()
        )
        .as_result())),
    );

    let zoneinfo_module = PyImport_ImportModule(c"zoneinfo".as_ptr());
    defer_decref!(zoneinfo_module);
    state.zoneinfo_type = PyObject_GetAttrString(zoneinfo_module, c"ZoneInfo".as_ptr());

    PyDateTime_IMPORT();
    state.py_api = match PyDateTimeAPI().as_ref() {
        Some(api) => api,
        None => return -1,
    };

    let datetime_module = PyImport_ImportModule(c"datetime".as_ptr());
    defer_decref!(datetime_module);
    state.strptime = PyObject_GetAttrString(
        steal!(PyObject_GetAttrString(
            datetime_module,
            c"datetime".as_ptr()
        )),
        c"strptime".as_ptr(),
    );
    state.timezone_type = PyObject_GetAttrString(datetime_module, c"timezone".as_ptr()).cast();

    let email_utils = PyImport_ImportModule(c"email.utils".as_ptr());
    defer_decref!(email_utils);
    state.format_rfc2822 = PyObject_GetAttrString(email_utils, c"format_datetime".as_ptr()).cast();
    state.parse_rfc2822 =
        PyObject_GetAttrString(email_utils, c"parsedate_to_datetime".as_ptr()).cast();

    let weekday_enum = unwrap_or_errcode!(create_enum(
        c"Weekday",
        &[
            (c"MONDAY", 1),
            (c"TUESDAY", 2),
            (c"WEDNESDAY", 3),
            (c"THURSDAY", 4),
            (c"FRIDAY", 5),
            (c"SATURDAY", 6),
            (c"SUNDAY", 7),
        ],
    )) as *mut _;
    defer_decref!(weekday_enum);
    if PyModule_AddType(module, weekday_enum.cast()) != 0 {
        return -1;
    }

    state.weekday_enum_members = [
        PyObject_GetAttrString(weekday_enum, c"MONDAY".as_ptr()),
        PyObject_GetAttrString(weekday_enum, c"TUESDAY".as_ptr()),
        PyObject_GetAttrString(weekday_enum, c"WEDNESDAY".as_ptr()),
        PyObject_GetAttrString(weekday_enum, c"THURSDAY".as_ptr()),
        PyObject_GetAttrString(weekday_enum, c"FRIDAY".as_ptr()),
        PyObject_GetAttrString(weekday_enum, c"SATURDAY".as_ptr()),
        PyObject_GetAttrString(weekday_enum, c"SUNDAY".as_ptr()),
    ];

    state.str_years = PyUnicode_InternFromString(c"years".as_ptr());
    state.str_months = PyUnicode_InternFromString(c"months".as_ptr());
    state.str_weeks = PyUnicode_InternFromString(c"weeks".as_ptr());
    state.str_days = PyUnicode_InternFromString(c"days".as_ptr());
    state.str_hours = PyUnicode_InternFromString(c"hours".as_ptr());
    state.str_minutes = PyUnicode_InternFromString(c"minutes".as_ptr());
    state.str_seconds = PyUnicode_InternFromString(c"seconds".as_ptr());
    state.str_milliseconds = PyUnicode_InternFromString(c"milliseconds".as_ptr());
    state.str_microseconds = PyUnicode_InternFromString(c"microseconds".as_ptr());
    state.str_nanoseconds = PyUnicode_InternFromString(c"nanoseconds".as_ptr());
    state.str_year = PyUnicode_InternFromString(c"year".as_ptr());
    state.str_month = PyUnicode_InternFromString(c"month".as_ptr());
    state.str_day = PyUnicode_InternFromString(c"day".as_ptr());
    state.str_hour = PyUnicode_InternFromString(c"hour".as_ptr());
    state.str_minute = PyUnicode_InternFromString(c"minute".as_ptr());
    state.str_second = PyUnicode_InternFromString(c"second".as_ptr());
    state.str_nanosecond = PyUnicode_InternFromString(c"nanosecond".as_ptr());
    state.str_nanos = PyUnicode_InternFromString(c"nanos".as_ptr());
    state.str_raise = PyUnicode_InternFromString(c"raise".as_ptr());
    state.str_tz = PyUnicode_InternFromString(c"tz".as_ptr());
    state.str_disambiguate = PyUnicode_InternFromString(c"disambiguate".as_ptr());
    state.str_offset = PyUnicode_InternFromString(c"offset".as_ptr());

    state.exc_ambiguous = new_exc(module, c"whenever.AmbiguousTime");
    state.exc_skipped = new_exc(module, c"whenever.SkippedTime");
    state.exc_invalid_offset = new_exc(module, c"whenever.InvalidOffset");

    0
}

unsafe fn do_visit(target: *mut PyObject, visit: visitproc, arg: *mut c_void) {
    let obj: *mut PyObject = target.cast();
    if !obj.is_null() {
        (visit)(obj, arg);
    }
}

unsafe fn do_type_visit(
    target: *mut PyTypeObject,
    visit: visitproc,
    arg: *mut c_void,
    num_singletons: usize,
) {
    let obj: *mut PyObject = target.cast();
    if !obj.is_null() {
        (visit)(obj, arg);
        // XXX: This trick SEEMS to let us avoid adding GC
        // support to our types: Since our types are atomic and immutable
        // this should be allowed...
        // ...BUT there is a reference cycle between the class and the
        // singleton instances (e.g. the Date.MAX instance and Date class itself)
        // Visiting the type once for each singleton should make GC aware of this.
        for _ in 0..num_singletons {
            (visit)(obj, arg);
        }
    }
}

unsafe extern "C" fn module_traverse(
    module: *mut PyObject,
    visit: visitproc,
    arg: *mut c_void,
) -> c_int {
    let state = State::for_mod(module);
    // types
    do_type_visit(state.date_type, visit, arg, date::SINGLETONS.len());
    do_type_visit(state.time_type, visit, arg, time::SINGLETONS.len());
    do_type_visit(
        state.date_delta_type,
        visit,
        arg,
        date_delta::SINGLETONS.len(),
    );
    do_type_visit(
        state.time_delta_type,
        visit,
        arg,
        time_delta::SINGLETONS.len(),
    );
    do_type_visit(
        state.datetime_delta_type,
        visit,
        arg,
        datetime_delta::SINGLETONS.len(),
    );
    do_type_visit(
        state.naive_datetime_type,
        visit,
        arg,
        naive_datetime::SINGLETONS.len(),
    );
    do_type_visit(state.instant_type, visit, arg, instant::SINGLETONS.len());
    do_type_visit(
        state.offset_datetime_type,
        visit,
        arg,
        offset_datetime::SINGLETONS.len(),
    );
    do_type_visit(
        state.zoned_datetime_type,
        visit,
        arg,
        zoned_datetime::SINGLETONS.len(),
    );
    do_type_visit(
        state.system_datetime_type,
        visit,
        arg,
        system_datetime::SINGLETONS.len(),
    );

    // enum members
    for &member in state.weekday_enum_members.iter() {
        do_visit(member, visit, arg);
    }

    // exceptions
    do_visit(state.exc_ambiguous, visit, arg);
    do_visit(state.exc_skipped, visit, arg);
    do_visit(state.exc_invalid_offset, visit, arg);

    // Imported modules
    do_visit(state.zoneinfo_type, visit, arg);
    do_visit(state.timezone_type, visit, arg);
    do_visit(state.strptime, visit, arg);
    do_visit(state.format_rfc2822, visit, arg);
    do_visit(state.parse_rfc2822, visit, arg);

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
    Py_CLEAR(ptr::addr_of_mut!(state.instant_type).cast());
    Py_CLEAR(ptr::addr_of_mut!(state.offset_datetime_type).cast());
    Py_CLEAR(ptr::addr_of_mut!(state.zoned_datetime_type).cast());
    Py_CLEAR(ptr::addr_of_mut!(state.system_datetime_type).cast());

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

#[repr(C)]
struct State {
    // types
    date_type: *mut PyTypeObject,
    time_type: *mut PyTypeObject,
    date_delta_type: *mut PyTypeObject,
    time_delta_type: *mut PyTypeObject,
    datetime_delta_type: *mut PyTypeObject,
    naive_datetime_type: *mut PyTypeObject,
    instant_type: *mut PyTypeObject,
    offset_datetime_type: *mut PyTypeObject,
    zoned_datetime_type: *mut PyTypeObject,
    system_datetime_type: *mut PyTypeObject,

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
    unpickle_instant: *mut PyObject,
    unpickle_offset_datetime: *mut PyObject,
    unpickle_zoned_datetime: *mut PyObject,
    unpickle_system_datetime: *mut PyObject,

    py_api: &'static PyDateTime_CAPI,

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

impl State {
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
