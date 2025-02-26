use crate::common::pyobject::*;
use core::ffi::CStr;
use pyo3_ffi::*;
use std::mem;

macro_rules! method(
    ($meth:ident, $doc:expr) => {
        method!($meth named stringify!($meth), $doc, METH_NOARGS)
    };

    ($meth:ident, $doc:expr, $flags:expr) => {
        method!($meth named stringify!($meth), $doc, $flags)
    };

    ($meth:ident named $name:expr, $doc:expr) => {
        method!($meth named $name, $doc, METH_NOARGS)
    };
    ($meth:ident named $name:expr, $doc:expr, $flags:expr) => {
        PyMethodDef {
            ml_name: concat!($name, "\0").as_ptr().cast(),
            ml_meth: PyMethodDefPointer {
                PyCFunction: {
                    unsafe extern "C" fn _wrap(slf: *mut PyObject, arg: *mut PyObject) -> *mut PyObject {
                        match $meth(&mut *slf, &mut *arg) {
                            Ok(x) => x,
                            Err(PyErrOccurred()) => core::ptr::null_mut(),
                        }
                    }
                    _wrap
                },
            },
            ml_flags: $flags,
            ml_doc: $doc.as_ptr()
        }
    };
);

macro_rules! method_vararg(
    ($meth:ident, $doc:expr) => {
        method_vararg!($meth named stringify!($meth), $doc, 0)
    };

    ($meth:ident, $doc:expr, $flags:expr) => {
        method_vararg!($meth named stringify!($meth), $doc, $flags)
    };

    ($meth:ident named $name:expr, $doc:expr) => {
        method_vararg!($meth named $name, $doc, 0)
    };

    ($meth:ident named $name:expr, $doc:expr, $flags:expr) => {
        PyMethodDef {
            ml_name: concat!($name, "\0").as_ptr().cast(),
            ml_meth: PyMethodDefPointer {
                PyCFunctionFast: {
                    unsafe extern "C" fn _wrap(
                        slf: *mut PyObject,
                        args: *mut *mut PyObject,
                        nargs: Py_ssize_t,
                    ) -> *mut PyObject {
                        match $meth(&mut *slf, std::slice::from_raw_parts(args, nargs as usize)) {
                            Ok(x) => x,
                            Err(PyErrOccurred()) => core::ptr::null_mut(),
                        }
                    }
                    _wrap
                },
            },
            ml_flags: METH_FASTCALL | $flags,
            ml_doc: $doc.as_ptr()
        }
    };
);

pub(crate) struct KwargIter {
    keys: *mut PyObject,
    values: *const *mut PyObject,
    size: isize,
    pos: isize,
}

impl KwargIter {
    pub(crate) unsafe fn new(keys: *mut PyObject, values: *const *mut PyObject) -> Self {
        Self {
            keys,
            values,
            size: if keys.is_null() {
                0
            } else {
                PyTuple_GET_SIZE(keys) as isize
            },
            pos: 0,
        }
    }

    pub(crate) fn len(&self) -> isize {
        self.size
    }
}

impl Iterator for KwargIter {
    type Item = (*mut PyObject, *mut PyObject);

    fn next(&mut self) -> Option<Self::Item> {
        if self.pos == self.size {
            return None;
        }
        unsafe {
            let item = (
                PyTuple_GET_ITEM(self.keys, self.pos),
                *self.values.offset(self.pos),
            );
            self.pos += 1;
            Some(item)
        }
    }
}

// FUTURE: the method macros could probably become plain functions
macro_rules! method_kwargs(
    ($meth:ident, $doc:expr) => {
        method_kwargs!($meth named stringify!($meth), $doc)
    };

    ($meth:ident, $doc:expr, $flags:expr) => {
        method_kwargs!($meth named stringify!($meth), $doc, $flags)
    };

    ($meth:ident named $name:expr, $doc:expr) => {
        method_kwargs!($meth named $name, $doc, 0)
    };

    ($meth:ident named $name:expr, $doc:expr, $flags:expr) => {
        PyMethodDef {
            ml_name: concat!($name, "\0").as_ptr().cast(),
            ml_meth: PyMethodDefPointer {
                PyCMethod: {
                    unsafe extern "C" fn _wrap(
                        slf: *mut PyObject,
                        cls: *mut PyTypeObject,
                        args_raw: *const *mut PyObject,
                        nargsf: Py_ssize_t,
                        kwnames: *mut PyObject,
                    ) -> *mut PyObject {
                        let nargs = PyVectorcall_NARGS(nargsf as usize);
                        let args = std::slice::from_raw_parts(args_raw, nargs as usize);
                        let mut kwargs = KwargIter::new(kwnames, args_raw.offset(nargs as isize));
                        match $meth(slf, cls, args, &mut kwargs) {
                            Ok(x) => x as *mut PyObject,
                            Err(PyErrOccurred()) => core::ptr::null_mut(),
                        }
                    }
                    _wrap
                },
            },
            ml_flags: $flags | METH_METHOD | METH_FASTCALL | METH_KEYWORDS,
            ml_doc: $doc.as_ptr()
        }
    };
);

macro_rules! slotmethod {
    (Py_tp_new, $name:ident) => {
        PyType_Slot {
            slot: Py_tp_new,
            pfunc: {
                unsafe extern "C" fn _wrap(
                    cls: *mut PyTypeObject,
                    args: *mut PyObject,
                    kwargs: *mut PyObject,
                ) -> *mut PyObject {
                    match $name(cls, args, kwargs) {
                        Ok(x) => x,
                        Err(PyErrOccurred()) => core::ptr::null_mut(),
                    }
                }
                _wrap as *mut c_void
            },
        }
    };

    (Py_tp_richcompare, $name:ident) => {
        PyType_Slot {
            slot: Py_tp_richcompare,
            pfunc: {
                unsafe extern "C" fn _wrap(
                    a: *mut PyObject,
                    b: *mut PyObject,
                    op: c_int,
                ) -> *mut PyObject {
                    match $name(a, b, op) {
                        Ok(x) => x,
                        Err(PyErrOccurred()) => core::ptr::null_mut(),
                    }
                }
                _wrap as *mut c_void
            },
        }
    };

    ($slot:ident, $name:ident, 2) => {
        PyType_Slot {
            slot: $slot,
            pfunc: {
                unsafe extern "C" fn _wrap(
                    slf: *mut PyObject,
                    arg: *mut PyObject,
                ) -> *mut PyObject {
                    match $name(slf, arg) {
                        Ok(x) => x,
                        Err(PyErrOccurred()) => core::ptr::null_mut(),
                    }
                }
                _wrap as *mut c_void
            },
        }
    };

    ($slot:ident, $name:ident, 1) => {
        PyType_Slot {
            slot: $slot,
            pfunc: {
                unsafe extern "C" fn _wrap(slf: *mut PyObject) -> *mut PyObject {
                    match $name(slf) {
                        Ok(x) => x,
                        Err(PyErrOccurred()) => core::ptr::null_mut(),
                    }
                }
                _wrap as *mut c_void
            },
        }
    };
}

macro_rules! getter(
    ($meth:ident named $name:expr, $doc:expr) => {
        PyGetSetDef {
            name: concat!($name, "\0").as_ptr().cast(),
            get: Some({
                unsafe extern "C" fn _wrap(
                    slf: *mut PyObject,
                    _: *mut c_void,
                ) -> *mut PyObject {
                    match $meth(&mut *slf) {
                        Ok(x) => x,
                        Err(PyErrOccurred()) => core::ptr::null_mut(),
                    }
                }
                _wrap
            }),
            set: None,
            doc: concat!($doc, "\0").as_ptr().cast(),
            closure: core::ptr::null_mut(),
        }
    };
);

pub(crate) unsafe extern "C" fn generic_dealloc(slf: *mut PyObject) {
    let cls = Py_TYPE(slf);
    let tp_free = PyType_GetSlot(cls, Py_tp_free);
    debug_assert_ne!(tp_free, core::ptr::null_mut());
    std::mem::transmute::<_, freefunc>(tp_free)(slf.cast());
    Py_DECREF(cls.cast());
}

#[inline]
pub(crate) unsafe fn generic_alloc<T>(type_: *mut PyTypeObject, d: T) -> PyReturn {
    let slf = (*type_).tp_alloc.unwrap()(type_, 0).cast::<PyWrap<T>>();
    match slf.cast::<PyObject>().as_mut() {
        Some(r) => {
            core::ptr::addr_of_mut!((*slf).data).write(d);
            Ok(r)
        }
        None => Err(PyErrOccurred()),
    }
}

pub(crate) trait PyWrapped: Copy {
    #[inline]
    unsafe fn extract(obj: *mut PyObject) -> Self {
        generic_extract(obj)
    }

    #[inline]
    unsafe fn to_obj(self, type_: *mut PyTypeObject) -> PyReturn {
        generic_alloc(type_, self)
    }
}

#[repr(C)]
pub(crate) struct PyWrap<T> {
    _ob_base: PyObject,
    data: T,
}

#[inline]
pub(crate) unsafe fn generic_extract<T: Copy>(obj: *mut PyObject) -> T {
    (*obj.cast::<PyWrap<T>>()).data
}

pub(crate) const fn type_spec<T>(name: &CStr, slots: &'static [PyType_Slot]) -> PyType_Spec {
    PyType_Spec {
        name: name.as_ptr().cast(),
        basicsize: mem::size_of::<PyWrap<T>>() as _,
        itemsize: 0,
        #[cfg(Py_3_10)]
        flags: (Py_TPFLAGS_DEFAULT | Py_TPFLAGS_IMMUTABLETYPE) as _,
        // XXX: implement a way to prevent refcycles on Python 3.9
        // without Py_TPFLAGS_IMMUTABLETYPE.
        // Not a pressing concern, because this only will be triggered
        // if users themselves decide to add instances to the class
        // namespace.
        // Even so, this will just result in a minor memory leak
        // preventing the module from being GC'ed,
        // since subinterpreters aren't a concern.
        #[cfg(not(Py_3_10))]
        flags: Py_TPFLAGS_DEFAULT as _,
        slots: slots as *const [_] as *mut _,
    }
}

#[allow(unused_imports)]
pub(crate) use {getter, method, method_kwargs, method_vararg, slotmethod};
