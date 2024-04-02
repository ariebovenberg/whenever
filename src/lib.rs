use core::ffi::{c_char, c_int, c_long, c_void};
use core::ptr::null_mut as NULL;
use core::{mem, ptr};
use pyo3_ffi::*;

use crate::common::{c_str, py_str};

mod common;
pub mod date;
mod date_delta;
pub mod naive_datetime;
mod time;
mod time_delta;
mod zoned_datetime;

static mut MODULE_DEF: PyModuleDef = PyModuleDef {
    m_base: PyModuleDef_HEAD_INIT,
    m_name: c_str!("whenever"),
    m_doc: c_str!("Fast, correct, and typesafe datetimes."),
    m_size: mem::size_of::<ModuleState>() as _,
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
        ml_name: c_str!("_unpkl_zoned"),
        ml_meth: PyMethodDefPointer {
            _PyCFunctionFast: zoned_datetime::unpickle,
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
        (*$state).$varname = $varname.cast();

        let unpickler = PyObject_GetAttrString($module, c_str!($unpickle_name));
        PyObject_SetAttrString(unpickler, "__module__\0".as_ptr().cast(), $module_nameobj);
        (*$state).$unpickle_var = unpickler;
    };
}

unsafe extern "C" fn module_exec(module: *mut PyObject) -> c_int {
    let state: *mut ModuleState = PyModule_GetState(module).cast();
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
        zoned_datetime,
        "ZonedDateTime",
        zoned_datetime_type,
        "_unpkl_zoned",
        unpickle_zoned_datetime
    );

    // zoneinfo module
    let zoneinfo_module = PyImport_ImportModule(c_str!("zoneinfo"));
    (*state).zoneinfo_type = PyObject_GetAttrString(zoneinfo_module, c_str!("ZoneInfo")).cast();
    // TODO: refcount?
    Py_DECREF(zoneinfo_module);

    // datetime module
    PyDateTime_IMPORT();
    (*state).datetime_api = PyDateTimeAPI();

    let datetime_py_module = PyImport_ImportModule(c_str!("datetime"));
    // TODO: refcount?
    (*state).strptime = PyObject_GetAttrString(
        PyObject_GetAttrString(datetime_py_module, c_str!("datetime")),
        c_str!("strptime"),
    );

    // TODO: a proper enum
    add_int!(module, "MONDAY", 1);
    add_int!(module, "TUESDAY", 2);
    add_int!(module, "WEDNESDAY", 3);
    add_int!(module, "THURSDAY", 4);
    add_int!(module, "FRIDAY", 5);
    add_int!(module, "SATURDAY", 6);
    add_int!(module, "SUNDAY", 7);

    0
}

unsafe extern "C" fn module_traverse(
    module: *mut PyObject,
    visit: visitproc,
    arg: *mut c_void,
) -> c_int {
    let state: *mut ModuleState = PyModule_GetState(module.cast()).cast();

    // types
    let date_type: *mut PyObject = (*state).date_type.cast();
    if !date_type.is_null() {
        (visit)(date_type, arg);
    };
    let time_type: *mut PyObject = (*state).time_type.cast();
    if !time_type.is_null() {
        (visit)(time_type, arg);
    };
    let date_delta_type: *mut PyObject = (*state).date_delta_type.cast();
    if !date_delta_type.is_null() {
        (visit)(date_delta_type, arg);
    };
    let time_delta_type: *mut PyObject = (*state).time_delta_type.cast();
    if !time_delta_type.is_null() {
        (visit)(time_delta_type, arg);
    };
    let naive_datetime_type: *mut PyObject = (*state).naive_datetime_type.cast();
    if !naive_datetime_type.is_null() {
        (visit)(naive_datetime_type, arg);
    };
    let zoned_datetime_type: *mut PyObject = (*state).zoned_datetime_type.cast();
    if !zoned_datetime_type.is_null() {
        (visit)(zoned_datetime_type, arg);
    };

    // Imported modules
    let zoneinfo_type: *mut PyObject = (*state).zoneinfo_type.cast();
    if !zoneinfo_type.is_null() {
        (visit)(zoneinfo_type, arg);
    };

    0
}

unsafe extern "C" fn module_clear(module: *mut PyObject) -> c_int {
    let state: *mut ModuleState = PyModule_GetState(module.cast()).cast();
    // types
    Py_CLEAR(ptr::addr_of_mut!((*state).date_type).cast());
    Py_CLEAR(ptr::addr_of_mut!((*state).time_type).cast());
    Py_CLEAR(ptr::addr_of_mut!((*state).date_delta_type).cast());
    Py_CLEAR(ptr::addr_of_mut!((*state).zoned_datetime_type).cast());

    // unpickling functions
    Py_CLEAR(ptr::addr_of_mut!((*state).unpickle_date).cast());
    Py_CLEAR(ptr::addr_of_mut!((*state).unpickle_time).cast());
    Py_CLEAR(ptr::addr_of_mut!((*state).unpickle_date_delta).cast());
    Py_CLEAR(ptr::addr_of_mut!((*state).unpickle_zoned_datetime).cast());
    Py_CLEAR(ptr::addr_of_mut!((*state).unpickle_naive_datetime).cast());

    // imported modules
    Py_CLEAR(ptr::addr_of_mut!((*state).zoneinfo_type).cast());
    Py_CLEAR(ptr::addr_of_mut!((*state).datetime_api).cast());
    0
}

unsafe extern "C" fn module_free(module: *mut c_void) {
    module_clear(module.cast());
}

#[repr(C)]
struct ModuleState {
    // types
    date_type: *mut PyTypeObject,
    time_type: *mut PyTypeObject,
    date_delta_type: *mut PyTypeObject,
    time_delta_type: *mut PyTypeObject,
    naive_datetime_type: *mut PyTypeObject,
    zoned_datetime_type: *mut PyTypeObject,

    // unpickling functions
    unpickle_date: *mut PyObject,
    unpickle_time: *mut PyObject,
    unpickle_date_delta: *mut PyObject,
    unpickle_time_delta: *mut PyObject,
    unpickle_naive_datetime: *mut PyObject,
    unpickle_zoned_datetime: *mut PyObject,

    // imported modules
    zoneinfo_type: *mut PyTypeObject,
    datetime_api: *mut PyDateTime_CAPI,
    strptime: *mut PyObject,
}

impl ModuleState {
    unsafe fn from(tp: *mut PyTypeObject) -> *mut Self {
        PyType_GetModuleState(tp).cast()
    }
}

#[allow(non_snake_case)]
#[no_mangle]
pub unsafe extern "C" fn PyInit__whenever() -> *mut PyObject {
    PyModuleDef_Init(ptr::addr_of_mut!(MODULE_DEF))
}
