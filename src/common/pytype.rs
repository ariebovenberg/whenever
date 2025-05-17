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
                        match $meth(&mut *slf, arg) {
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

macro_rules! method0(
    ($typ:ident, $meth:ident, $doc:expr) => {
        method0!($typ, $meth named stringify!($meth), $doc)
    };

    ($typ:ident, $meth:ident named $name:expr, $doc:expr) => {
        PyMethodDef {
            ml_name: concat!($name, "\0").as_ptr().cast(),
            ml_meth: PyMethodDefPointer {
                PyCFunction: {
                    use crate::common::pyobject::*;
                    unsafe extern "C" fn _wrap(slf_ptr: *mut PyObject, _: *mut PyObject) -> *mut PyObject {
                        let slf = PyObj::from_ptr_unchecked(slf_ptr);
                        $meth(
                            slf.class().link_type::<$typ>().into(),
                            slf.extract_unchecked()
                        ).into_py_ptr()
                    }
                    _wrap
                },
            },
            ml_flags: METH_NOARGS,
            ml_doc: $doc.as_ptr()
        }
    };
);

macro_rules! method1(
    ($typ:ident, $meth:ident, $doc:expr) => {
        method1!($typ, $meth named stringify!($meth), $doc)
    };

    ($typ:ident, $meth:ident named $name:expr, $doc:expr) => {
        PyMethodDef {
            ml_name: concat!($name, "\0").as_ptr().cast(),
            ml_meth: PyMethodDefPointer {
                PyCFunction: {
                    use crate::common::pyobject::*;
                    unsafe extern "C" fn _wrap(slf_ptr: *mut PyObject, arg_obj: *mut PyObject) -> *mut PyObject {
                        let slf = PyObj::from_ptr_unchecked(slf_ptr);
                        let arg = PyObj::from_ptr_unchecked(arg_obj);
                        $meth(
                            slf.class().link_type::<$typ>().into(),
                            slf.extract_unchecked(),
                            arg.extract_unchecked()
                        ).into_py_ptr()
                    }
                    _wrap
                },
            },
            ml_flags: METH_O,
            ml_doc: $doc.as_ptr()
        }
    };
);

macro_rules! modmethod1(
    ($meth:ident, $doc:expr) => {
        modmethod1!($meth named stringify!($meth), $doc)
    };

    ($meth:ident named $name:expr, $doc:expr) => {
        PyMethodDef {
            ml_name: concat!($name, "\0").as_ptr().cast(),
            ml_meth: PyMethodDefPointer {
                PyCFunction: {
                    use crate::common::pyobject::*;
                    unsafe extern "C" fn _wrap(mod_obj: *mut PyObject, arg_obj: *mut PyObject) -> *mut PyObject {
                        $meth(State::for_mod(mod_obj), PyObj::from_ptr_unchecked(arg_obj)).into_py_ptr()
                    }
                    _wrap
                },
            },
            ml_flags: METH_O,
            ml_doc: $doc.as_ptr()
        }
    };
);

macro_rules! classmethod1(
    ($typ:ident, $meth:ident, $doc:expr) => {
        classmethod1!($typ, $meth named stringify!($meth), $doc)
    };

    ($typ:ident, $meth:ident named $name:expr, $doc:expr) => {
        PyMethodDef {
            ml_name: concat!($name, "\0").as_ptr().cast(),
            ml_meth: PyMethodDefPointer {
                PyCFunction: {
                    use crate::common::pyobject::*;
                    unsafe extern "C" fn _wrap(cls: *mut PyObject, arg: *mut PyObject) -> *mut PyObject {
                        $meth(
                            PyType::from_ptr_unchecked(cls).link_type::<$typ>().into(),
                            PyObj::from_ptr_unchecked(arg)
                        ).into_py_ptr()
                    }
                    _wrap
                },
            },
            ml_flags: METH_O | METH_CLASS,
            ml_doc: $doc.as_ptr()
        }
    };
);

macro_rules! classmethod0(
    ($typ:ident, $meth:ident, $doc:expr) => {
        classmethod0!($typ, $meth named stringify!($meth), $doc)
    };

    ($typ:ident, $meth:ident named $name:expr, $doc:expr) => {
        PyMethodDef {
            ml_name: concat!($name, "\0").as_ptr().cast(),
            ml_meth: PyMethodDefPointer {
                PyCFunction: {
                    use crate::common::pyobject::*;
                    unsafe extern "C" fn _wrap(cls: *mut PyObject, _: *mut PyObject) -> *mut PyObject {
                        $meth(
                            PyType::from_ptr_unchecked(cls).link_type::<$typ>().into(),
                        ).into_py_ptr()
                    }
                    _wrap
                },
            },
            ml_flags: METH_NOARGS | METH_CLASS,
            ml_doc: $doc.as_ptr()
        }
    };
);

macro_rules! method_vararg2(
    ($typ:ident, $meth:ident, $doc:expr) => {
        method_vararg2!($typ, $meth named stringify!($meth), $doc)
    };

    ($typ:ident, $meth:ident named $name:expr, $doc:expr) => {
        PyMethodDef {
            ml_name: concat!($name, "\0").as_ptr().cast(),
            ml_meth: PyMethodDefPointer {
                PyCFunctionFast: {
                    unsafe extern "C" fn _wrap(
                        slf_obj: *mut PyObject,
                        args: *mut *mut PyObject,
                        nargs: Py_ssize_t,
                    ) -> *mut PyObject {
                        let slf = PyObj::from_ptr_unchecked(slf_obj);
                        $meth(
                            slf.class().link_type::<$typ>().into(),
                            slf.extract_unchecked(),
                            std::slice::from_raw_parts(args.cast::<PyObj>(), nargs as usize)
                        ).into_py_ptr()
                    }
                    _wrap
                },
            },
            ml_flags: METH_FASTCALL,
            ml_doc: $doc.as_ptr()
        }
    };
);

macro_rules! modmethod_vararg(
    ($meth:ident, $doc:expr) => {
        modmethod_vararg!($meth named stringify!($meth), $doc)
    };

    ($meth:ident named $name:expr, $doc:expr) => {
        PyMethodDef {
            ml_name: concat!($name, "\0").as_ptr().cast(),
            ml_meth: PyMethodDefPointer {
                PyCFunctionFast: {
                    unsafe extern "C" fn _wrap(
                        slf: *mut PyObject,
                        args: *mut *mut PyObject,
                        nargs: Py_ssize_t,
                    ) -> *mut PyObject {
                        $meth(
                            State::for_mod(slf),
                            std::slice::from_raw_parts(args.cast::<PyObj>(), nargs as usize)
                        )
                        .into_py_ptr()
                    }
                    _wrap
                },
            },
            ml_flags: METH_FASTCALL,
            ml_doc: $doc.as_ptr()
        }
    };
);

// TODO: deprecate old
pub(crate) struct IterKwargs {
    keys: *mut PyObject,
    values: *const *mut PyObject,
    size: isize,
    pos: isize,
}

impl IterKwargs {
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

impl Iterator for IterKwargs {
    type Item = (PyObj, PyObj);

    fn next(&mut self) -> Option<Self::Item> {
        if self.pos == self.size {
            return None;
        }
        let item = unsafe {
            (
                PyObj::from_ptr_unchecked(PyTuple_GET_ITEM(self.keys, self.pos)),
                PyObj::from_ptr_unchecked(*self.values.offset(self.pos)),
            )
        };
        self.pos += 1;
        Some(item)
    }
}

macro_rules! method_kwargs2(
    ($typ:ident, $meth:ident, $doc:expr) => {
        method_kwargs2!($typ, $meth named stringify!($meth), $doc)
    };

    ($typ:ident, $meth:ident named $name:expr, $doc:expr) => {
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
                        $meth(
                            PyType::from_ptr_unchecked(cls.cast()).link_type::<$typ>().into(),
                            PyObj::from_ptr_unchecked(slf).extract_unchecked(),
                            std::slice::from_raw_parts(args_raw.cast::<PyObj>(), nargs as usize),
                            &mut IterKwargs::new(kwnames, args_raw.offset(nargs as isize)),
                        ).into_py_ptr()
                    }
                    _wrap
                },
            },
            ml_flags: METH_METHOD | METH_FASTCALL | METH_KEYWORDS,
            ml_doc: $doc.as_ptr()
        }
    };
);

macro_rules! classmethod_kwargs(
    ($typ:ident, $meth:ident, $doc:expr) => {
        classmethod_kwargs!($typ, $meth named stringify!($meth), $doc)
    };

    ($typ:ident, $meth:ident named $name:expr, $doc:expr) => {
        PyMethodDef {
            ml_name: concat!($name, "\0").as_ptr().cast(),
            ml_meth: PyMethodDefPointer {
                PyCMethod: {
                    unsafe extern "C" fn _wrap(
                        _: *mut PyObject,
                        cls: *mut PyTypeObject,
                        args_raw: *const *mut PyObject,
                        nargsf: Py_ssize_t,
                        kwnames: *mut PyObject,
                    ) -> *mut PyObject {
                        let nargs = PyVectorcall_NARGS(nargsf as usize);
                        $meth(
                            PyType::from_ptr_unchecked(cls.cast()).link_type::<$typ>().into(),
                            std::slice::from_raw_parts(args_raw.cast::<PyObj>(), nargs as usize),
                            &mut IterKwargs::new(kwnames, args_raw.offset(nargs as isize)),
                        ).into_py_ptr()
                    }
                    _wrap
                },
            },
            ml_flags: METH_METHOD | METH_FASTCALL | METH_KEYWORDS | METH_CLASS,
            ml_doc: $doc.as_ptr()
        }
    };
);

macro_rules! slotmethod2 {
    ($typ:ident, Py_tp_new, $name:ident) => {
        PyType_Slot {
            slot: Py_tp_new,
            pfunc: {
                unsafe extern "C" fn _wrap(
                    cls: *mut PyTypeObject,
                    args: *mut PyObject,
                    kwargs: *mut PyObject,
                ) -> *mut PyObject {
                    $name(
                        HeapType::<$typ>::from_ptr_unchecked(cls.cast()),
                        PyTuple::from_ptr_unchecked(args),
                        (!kwargs.is_null()).then(|| PyDict::from_ptr_unchecked(kwargs)),
                    )
                    .into_py_ptr()
                }
                _wrap as *mut c_void
            },
        }
    };

    ($typ:ident, Py_tp_richcompare, $name:ident) => {
        PyType_Slot {
            slot: Py_tp_richcompare,
            pfunc: {
                unsafe extern "C" fn _wrap(
                    a: *mut PyObject,
                    b: *mut PyObject,
                    op: c_int,
                ) -> *mut PyObject {
                    let a = PyObj::from_ptr_unchecked(a);
                    $name(
                        a.class().link_type::<$typ>().into(),
                        a.extract_unchecked(),
                        PyObj::from_ptr_unchecked(b),
                        op,
                    )
                    .into_py_ptr()
                }
                _wrap as *mut c_void
            },
        }
    };
    ($slot:ident, $name:ident, 2) => {
        PyType_Slot {
            slot: $slot,
            pfunc: {
                unsafe extern "C" fn _wrap(a: *mut PyObject, b: *mut PyObject) -> *mut PyObject {
                    $name(PyObj::from_ptr_unchecked(a), PyObj::from_ptr_unchecked(b)).into_py_ptr()
                }
                _wrap as *mut c_void
            },
        }
    };

    ($typ:ident, $slot:ident, $name:ident, 1) => {
        PyType_Slot {
            slot: $slot,
            pfunc: {
                unsafe extern "C" fn _wrap(slf: *mut PyObject) -> *mut PyObject {
                    let slf = PyObj::from_ptr_unchecked(slf);
                    $name(
                        slf.class().link_type::<$typ>().into(),
                        slf.extract_unchecked(),
                    )
                    .into_py_ptr()
                }
                _wrap as *mut c_void
            },
        }
    };
}

macro_rules! getter2(
    ($typ:ident, $meth:ident named $name:expr, $doc:expr) => {
        PyGetSetDef {
            name: concat!($name, "\0").as_ptr().cast(),
            get: Some({
                unsafe extern "C" fn _wrap(
                    slf_obj: *mut PyObject,
                    _: *mut c_void,
                ) -> *mut PyObject {
                    let slf = PyObj::from_ptr_unchecked(slf_obj);
                    $meth(
                        slf.class().link_type::<$typ>().into(),
                        slf.extract_unchecked()
                    ).into_py_ptr()
                }
                _wrap
            }),
            set: None,
            doc: concat!($doc, "\0").as_ptr().cast(),
            closure: core::ptr::null_mut(),
        }
    };
);

pub(crate) extern "C" fn generic_dealloc(slf: PyObj) {
    let cls = slf.class().as_ptr().cast::<PyTypeObject>();
    unsafe {
        let tp_free = PyType_GetSlot(cls, Py_tp_free);
        debug_assert_ne!(tp_free, core::ptr::null_mut());
        let tp_free: freefunc = std::mem::transmute(tp_free);
        tp_free(slf.as_ptr().cast());
        Py_DECREF(cls.cast());
    }
}

#[inline]
pub(crate) unsafe fn generic_alloc<T: PyWrapped>(type_: *mut PyTypeObject, d: T) -> PyReturn {
    let slf = (*type_).tp_alloc.unwrap()(type_, 0).cast::<PyWrap<T>>();
    match slf.cast::<PyObject>().as_mut() {
        Some(r) => {
            (&raw mut (*slf).data).write(d);
            Ok(r)
        }
        None => Err(PyErrOccurred()),
    }
}

#[inline]
pub(crate) fn generic_alloc2<T: PyWrapped>(type_: PyType, d: T) -> PyReturn2 {
    let type_ptr = type_.as_ptr().cast::<PyTypeObject>();
    unsafe {
        let slf = (*type_ptr).tp_alloc.unwrap()(type_ptr, 0).cast::<PyWrap<T>>();
        match slf.cast::<PyObject>().as_mut() {
            Some(r) => {
                (&raw mut (*slf).data).write(d);
                Ok(Owned::new(PyObj::from_ptr_unchecked(r)))
            }
            None => Err(PyErrOccurred()),
        }
    }
}

pub(crate) trait PyWrapped: Copy {
    // TODO: phase out
    #[inline]
    unsafe fn extract(obj: *mut PyObject) -> Self {
        (*obj.cast::<PyWrap<Self>>()).data
    }

    #[inline]
    unsafe fn to_obj(self, type_: *mut PyTypeObject) -> PyReturn {
        generic_alloc(type_, self)
    }

    // TODO: rename `new_of_heaptype`?
    #[inline]
    fn to_obj3(self, type_: HeapType<Self>) -> PyReturn2 {
        // generic alloc3!
        generic_alloc2(type_.inner, self)
    }
}

#[repr(C)]
pub(crate) struct PyWrap<T: PyWrapped> {
    _ob_base: PyObject,
    data: T,
}

pub(crate) const fn type_spec<T: PyWrapped>(
    name: &CStr,
    slots: &'static [PyType_Slot],
) -> PyType_Spec {
    PyType_Spec {
        name: name.as_ptr().cast(),
        basicsize: mem::size_of::<PyWrap<T>>() as _,
        itemsize: 0,
        // NOTE: IMMUTABLETYPE flag is required to prevent additional refcycles
        // between the class and the instance.
        // This allows us to keep our types GC-free.
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
        slots: slots.as_ptr().cast_mut(),
    }
}

#[allow(unused_imports)]
pub(crate) use {
    classmethod0, classmethod1, classmethod_kwargs, getter2, method, method0, method1,
    method_kwargs2, method_vararg2, modmethod1, modmethod_vararg, slotmethod2,
};
