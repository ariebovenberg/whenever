use core::ffi::{c_char, c_int, c_uint, c_void};
use core::{mem, ptr};
use pyo3_ffi::*;

#[repr(C)]
pub struct PyInterval {
    _ob_base: PyObject,
    data: (),
}

unsafe extern "C" fn new(
    subtype: *mut PyTypeObject,
    args: *mut PyObject,
    kwds: *mut PyObject,
) -> *mut PyObject {
    if PyTuple_Size(args) != 0 || !kwds.is_null() {
        PyErr_SetString(
            PyExc_TypeError,
            "Interval() takes no arguments\0".as_ptr().cast::<c_char>(),
        );
        return ptr::null_mut();
    }

    let f: allocfunc = (*subtype).tp_alloc.unwrap_or(PyType_GenericAlloc);
    let slf = f(subtype, 0);

    if slf.is_null() {
        return ptr::null_mut();
    } else {
        let slf = slf.cast::<PyInterval>();
        ptr::addr_of_mut!((*slf).data).write(());
    }
    slf
}

#[cfg(Py_3_9)]
extern "C" {
    fn Py_GenericAlias(origin: *mut PyObject, args: *mut PyObject) -> *mut PyObject;
}

#[cfg(Py_3_9)]
unsafe extern "C" fn class_getitem(type_: *mut PyObject, item: *mut PyObject) -> *mut PyObject {
    Py_GenericAlias(type_, item)
}

#[cfg(not(Py_3_9))]
unsafe extern "C" fn class_getitem(type_: *mut PyObject, _item: *mut PyObject) -> *mut PyObject {
    type_
}

unsafe extern "C" fn repr(_slf: *mut PyObject) -> *mut PyObject {
    let string = "Interval(<empty>)\0";
    PyUnicode_FromStringAndSize(string.as_ptr().cast::<c_char>(), string.len() as Py_ssize_t)
}

static mut METHODS: &[PyMethodDef] = &[
    PyMethodDef {
        ml_name: "__class_getitem__\0".as_ptr().cast::<c_char>(),
        ml_meth: PyMethodDefPointer {
            PyCFunction: class_getitem,
        },
        ml_flags: METH_O | METH_CLASS,
        ml_doc: "See PEP 585\0".as_ptr().cast::<c_char>(),
    },
    PyMethodDef::zeroed(),
];

static mut SLOTS: &[PyType_Slot] = &[
    PyType_Slot {
        slot: Py_tp_new,
        pfunc: new as *mut c_void,
    },
    PyType_Slot {
        slot: Py_tp_doc,
        pfunc: "An interval type\0".as_ptr() as *mut c_void,
    },
    PyType_Slot {
        slot: Py_tp_repr,
        pfunc: repr as *mut c_void,
    },
    PyType_Slot {
        slot: Py_tp_methods,
        pfunc: unsafe { METHODS.as_ptr() as *mut c_void },
    },
    PyType_Slot {
        slot: 0,
        pfunc: ptr::null_mut(),
    },
];

pub static mut SPEC: PyType_Spec = PyType_Spec {
    name: "whenever.Interval\0".as_ptr().cast::<c_char>(),
    basicsize: mem::size_of::<PyInterval>() as c_int,
    itemsize: 0,
    flags: Py_TPFLAGS_DEFAULT as c_uint,
    slots: unsafe { SLOTS as *const [PyType_Slot] as *mut PyType_Slot },
};
