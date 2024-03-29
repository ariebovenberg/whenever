use core::ffi::{c_char, c_int, c_uint, c_ulonglong, c_void};
use core::{mem, ptr};
use pyo3_ffi::*;
use std::ptr::null_mut;

#[repr(C)]
pub struct PyTimeDelta {
    _ob_base: PyObject,
    delta: chrono::TimeDelta,
}

unsafe extern "C" fn timedelta_new(
    subtype: *mut PyTypeObject,
    args: *mut PyObject,
    kwds: *mut PyObject,
) -> *mut PyObject {
    if PyTuple_Size(args) != 0 || !kwds.is_null() {
        PyErr_SetString(
            PyExc_TypeError,
            "TimeDelta() takes no arguments\0".as_ptr().cast::<c_char>(),
        );
        return ptr::null_mut();
    }

    let f: allocfunc = (*subtype).tp_alloc.unwrap_or(PyType_GenericAlloc);
    let slf = f(subtype, 0);

    if slf.is_null() {
        return ptr::null_mut();
    } else {
        let delta = chrono::TimeDelta::zero();
        let slf = slf.cast::<PyTimeDelta>();
        ptr::addr_of_mut!((*slf).delta).write(delta);
    }
    slf
}

unsafe extern "C" fn timedelta_repr(slf: *mut PyObject) -> *mut PyObject {
    let slf = slf.cast::<PyTimeDelta>();
    let delta = (*slf).delta;
    let string = format!("TimeDelta({})", delta);
    PyUnicode_FromStringAndSize(string.as_ptr().cast::<c_char>(), string.len() as Py_ssize_t)
}

unsafe extern "C" fn timedelta_int(slf: *mut PyObject) -> *mut PyObject {
    let slf = slf.cast::<PyTimeDelta>();
    let hours = (*slf).delta.num_hours();
    PyLong_FromUnsignedLongLong(hours as c_ulonglong)
}

unsafe extern "C" fn timedelta_richcompare(
    slf: *mut PyObject,
    other: *mut PyObject,
    op: c_int,
) -> *mut PyObject {
    let pytype = Py_TYPE(slf); // guaranteed to be `whenever.TimeDelta`
    if Py_TYPE(other) != pytype {
        let result = Py_NotImplemented();
        Py_INCREF(result);
        return result;
    }
    let slf = (*slf.cast::<PyTimeDelta>()).delta;
    let other = (*other.cast::<PyTimeDelta>()).delta;
    let cmp = match op {
        pyo3_ffi::Py_LT => slf < other,
        pyo3_ffi::Py_LE => slf <= other,
        pyo3_ffi::Py_EQ => slf == other,
        pyo3_ffi::Py_NE => slf != other,
        pyo3_ffi::Py_GT => slf > other,
        pyo3_ffi::Py_GE => slf >= other,
        _ => unreachable!(),
    };

    let result = if cmp { Py_True() } else { Py_False() };
    Py_INCREF(result);
    result
}

unsafe extern "C" fn in_hours(_: *mut PyObject, _: *mut PyObject) -> *mut PyObject {
    PyLong_FromLong(0)
}

static mut METHODS: &[PyMethodDef] = &[
    PyMethodDef {
        ml_name: "in_hours\0".as_ptr().cast::<c_char>(),
        ml_meth: PyMethodDefPointer {
            PyCFunction: in_hours,
        },
        ml_flags: METH_NOARGS,
        ml_doc: "Size in hours\0".as_ptr().cast::<c_char>(),
    },
    PyMethodDef::zeroed(),
];

unsafe extern "C" fn foo_getter(_: *mut PyObject, _: *mut c_void) -> *mut PyObject {
    PyLong_FromLong(3)
}

static mut GETSETTERS: &[PyGetSetDef] = &[
    PyGetSetDef {
        name: "foo\0".as_ptr().cast::<c_char>(),
        get: Some(foo_getter),
        set: None,
        doc: "Dummy property\0".as_ptr().cast::<c_char>(),
        closure: ptr::null_mut(),
    },
    PyGetSetDef {
        name: null_mut(),
        get: None,
        set: None,
        doc: null_mut(),
        closure: null_mut(),
    },
];

static mut SLOTS: &[PyType_Slot] = &[
    PyType_Slot {
        slot: Py_tp_new,
        pfunc: timedelta_new as *mut c_void,
    },
    PyType_Slot {
        slot: Py_tp_doc,
        pfunc: "A precise duration type\0".as_ptr() as *mut c_void,
    },
    PyType_Slot {
        slot: Py_tp_repr,
        pfunc: timedelta_repr as *mut c_void,
    },
    PyType_Slot {
        slot: Py_nb_int,
        pfunc: timedelta_int as *mut c_void,
    },
    PyType_Slot {
        slot: Py_tp_richcompare,
        pfunc: timedelta_richcompare as *mut c_void,
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
        slot: 0,
        pfunc: ptr::null_mut(),
    },
];

pub static mut TIMEDELTA_SPEC: PyType_Spec = PyType_Spec {
    name: "whenever.TimeDelta\0".as_ptr().cast::<c_char>(),
    basicsize: mem::size_of::<PyTimeDelta>() as c_int,
    itemsize: 0,
    flags: Py_TPFLAGS_DEFAULT as c_uint,
    slots: unsafe { SLOTS as *const [PyType_Slot] as *mut PyType_Slot },
};
