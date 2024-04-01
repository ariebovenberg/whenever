use core::ffi::{c_char, c_int, c_void};
use core::{mem, ptr};
use pyo3_ffi::*;

mod interval;
mod timedelta;

static mut MODULE_DEF: PyModuleDef = PyModuleDef {
    m_base: PyModuleDef_HEAD_INIT,
    m_name: "whenever\0".as_ptr().cast::<c_char>(),
    m_doc: "Sensible, fast, and typesafe datetimes.\0"
        .as_ptr()
        .cast::<c_char>(),
    m_size: mem::size_of::<WheneverState>() as Py_ssize_t,
    m_methods: unsafe { METHODS.as_mut_ptr().cast() },
    m_slots: unsafe { WHENEVER_SLOTS as *const [PyModuleDef_Slot] as *mut PyModuleDef_Slot },
    m_traverse: Some(whenever_traverse),
    m_clear: Some(whenever_clear),
    m_free: Some(whenever_free),
};

static mut METHODS: [PyMethodDef; 2] = [
    PyMethodDef {
        ml_name: "sum_as_string\0".as_ptr().cast::<c_char>(),
        ml_meth: PyMethodDefPointer {
            _PyCFunctionFast: sum_as_string,
        },
        ml_flags: METH_FASTCALL,
        ml_doc: "returns the sum of two integers as a string\0"
            .as_ptr()
            .cast::<c_char>(),
    },
    PyMethodDef::zeroed(),
];

static mut WHENEVER_SLOTS: &[PyModuleDef_Slot] = &[
    PyModuleDef_Slot {
        slot: Py_mod_exec,
        value: whenever_exec as *mut c_void,
    },
    // TODO: actually check if this is correct
    #[cfg(Py_3_12)]
    PyModuleDef_Slot {
        slot: Py_mod_multiple_interpreters,
        value: Py_MOD_PER_INTERPRETER_GIL_SUPPORTED,
    },
    PyModuleDef_Slot {
        slot: 0,
        value: ptr::null_mut(),
    },
];

#[cfg(Py_3_10)]
macro_rules! add {
    ($mptr:expr, $name:expr, $obj:expr) => {
        PyModule_AddObjectRef($mptr, $name.as_ptr() as *const c_char, $obj);
    };
}

#[cfg(not(Py_3_10))]
macro_rules! add {
    ($mptr:expr, $name:expr, $obj:expr) => {
        PyModule_AddObject($mptr, $name.as_ptr() as *const c_char, $obj);
    };
}

unsafe extern "C" fn whenever_exec(module: *mut PyObject) -> c_int {
    let state: *mut WheneverState = PyModule_GetState(module).cast();

    // PyType_FromModuleAndSpec -> how to set module?

    // TimeDelta type
    let timedelta_type = PyType_FromSpec(ptr::addr_of_mut!(crate::timedelta::TIMEDELTA_SPEC));
    if timedelta_type.is_null() {
        return -1;
    }
    add!(module, "TimeDelta\0", timedelta_type);
    (*state).timedelta_type = timedelta_type.cast::<PyTypeObject>();

    // Interval
    let interval_type = PyType_FromSpec(ptr::addr_of_mut!(crate::interval::SPEC));
    if interval_type.is_null() {
        return -1;
    }
    add!(module, "Interval\0", interval_type);

    let ambiguoustime_type = PyErr_NewException(
        "whenever.AmbiguousTime\0".as_ptr().cast::<c_char>(),
        std::ptr::null_mut(),
        std::ptr::null_mut(),
    );
    if ambiguoustime_type.is_null() {
        return -1;
    }
    add!(module, "AmbiguousTime\0", ambiguoustime_type);
    (*state).ambigoustime_type = ambiguoustime_type.cast::<PyTypeObject>();

    0
}

unsafe extern "C" fn whenever_traverse(
    module: *mut PyObject,
    visit: visitproc,
    arg: *mut c_void,
) -> c_int {
    let state: *mut WheneverState = PyModule_GetState(module.cast()).cast();
    let timedelta_type: *mut PyObject = (*state).timedelta_type.cast();

    if timedelta_type.is_null() {
        0
    } else {
        (visit)(timedelta_type, arg)
    }
}

unsafe extern "C" fn whenever_clear(module: *mut PyObject) -> c_int {
    let state: *mut WheneverState = PyModule_GetState(module.cast()).cast();
    Py_CLEAR(ptr::addr_of_mut!((*state).timedelta_type).cast());
    0
}

unsafe extern "C" fn whenever_free(module: *mut c_void) {
    whenever_clear(module.cast());
}

#[repr(C)]
struct WheneverState {
    timedelta_type: *mut PyTypeObject,
    ambigoustime_type: *mut PyTypeObject,
}

#[allow(non_snake_case)]
#[no_mangle]
pub unsafe extern "C" fn PyInit__whenever() -> *mut PyObject {
    let m = PyModuleDef_Init(ptr::addr_of_mut!(MODULE_DEF));
    if m.is_null() {
        return std::ptr::null_mut();
    };
    m
}

pub unsafe extern "C" fn sum_as_string(
    _self: *mut PyObject,
    args: *mut *mut PyObject,
    nargs: Py_ssize_t,
) -> *mut PyObject {
    if nargs != 2 {
        PyErr_SetString(
            PyExc_TypeError,
            "sum_as_string() expected 2 positional arguments\0"
                .as_ptr()
                .cast::<c_char>(),
        );
        return std::ptr::null_mut();
    }

    let arg1 = *args;
    if PyLong_Check(arg1) == 0 {
        PyErr_SetString(
            PyExc_TypeError,
            "sum_as_string() expected an int for positional argument 1\0"
                .as_ptr()
                .cast::<c_char>(),
        );
        return std::ptr::null_mut();
    }

    let arg1 = PyLong_AsLong(arg1);
    if !PyErr_Occurred().is_null() {
        return ptr::null_mut();
    }

    let arg2 = *args.add(1);
    if PyLong_Check(arg2) == 0 {
        PyErr_SetString(
            PyExc_TypeError,
            "sum_as_string() expected an int for positional argument 2\0"
                .as_ptr()
                .cast::<c_char>(),
        );
        return std::ptr::null_mut();
    }

    let arg2 = PyLong_AsLong(arg2);
    if !PyErr_Occurred().is_null() {
        return ptr::null_mut();
    }

    match arg1.checked_add(arg2) {
        Some(sum) => {
            let string = sum.to_string();
            PyUnicode_FromStringAndSize(string.as_ptr().cast::<c_char>(), string.len() as isize)
        }
        None => {
            PyErr_SetString(
                PyExc_OverflowError,
                "arguments too large to add\0".as_ptr().cast::<c_char>(),
            );
            std::ptr::null_mut()
        }
    }
}
