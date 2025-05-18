macro_rules! method0(
    ($typ:ident, $meth:ident, $doc:expr) => {
        PyMethodDef {
            ml_name: concat!(stringify!($meth), "\0").as_ptr().cast(),
            ml_meth: PyMethodDefPointer {
                PyCFunction: {
                    use crate::py::*;
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
        PyMethodDef {
            ml_name: concat!(stringify!($meth), "\0").as_ptr().cast(),
            ml_meth: PyMethodDefPointer {
                PyCFunction: {
                    use crate::py::*;
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
        PyMethodDef {
            ml_name: concat!(stringify!($meth), "\0").as_ptr().cast(),
            ml_meth: PyMethodDefPointer {
                PyCFunction: {
                    use crate::py::*;
                    unsafe extern "C" fn _wrap(mod_obj: *mut PyObject, arg_obj: *mut PyObject) -> *mut PyObject {
                        $meth(State::for_mod_mut(mod_obj), PyObj::from_ptr_unchecked(arg_obj)).into_py_ptr()
                    }
                    _wrap
                },
            },
            ml_flags: METH_O,
            ml_doc: $doc.as_ptr()
        }
    };
);

macro_rules! modmethod0(
    ($meth:ident, $doc:expr) => {
        PyMethodDef {
            ml_name: concat!(stringify!($meth), "\0").as_ptr().cast(),
            ml_meth: PyMethodDefPointer {
                PyCFunction: {
                    use crate::py::*;
                    unsafe extern "C" fn _wrap(mod_obj: *mut PyObject, _: *mut PyObject) -> *mut PyObject {
                        $meth(State::for_mod_mut(mod_obj)).into_py_ptr()
                    }
                    _wrap
                },
            },
            ml_flags: METH_NOARGS,
            ml_doc: $doc.as_ptr()
        }
    };
);

macro_rules! classmethod1(
    ($typ:ident, $meth:ident, $doc:expr) => {
        PyMethodDef {
            ml_name: concat!(stringify!($meth), "\0").as_ptr().cast(),
            ml_meth: PyMethodDefPointer {
                PyCFunction: {
                    use crate::py::*;
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
        PyMethodDef {
            ml_name: concat!(stringify!($meth), "\0").as_ptr().cast(),
            ml_meth: PyMethodDefPointer {
                PyCFunction: {
                    use crate::py::*;
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
        PyMethodDef {
            ml_name: concat!(stringify!($meth), "\0").as_ptr().cast(),
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
        PyMethodDef {
            ml_name: concat!(stringify!($meth), "\0").as_ptr().cast(),
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
macro_rules! method_kwargs2(
    ($typ:ident, $meth:ident, $doc:expr) => {
        PyMethodDef {
            ml_name: concat!(stringify!($meth), "\0").as_ptr().cast(),
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
        PyMethodDef {
            ml_name: concat!(stringify!($meth), "\0").as_ptr().cast(),
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

macro_rules! getter3(
    ($typ:ident, $meth:ident, $doc:expr) => {
        PyGetSetDef {
            name: concat!(stringify!($meth), "\0").as_ptr().cast(),
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

#[allow(unused_imports)]
pub(crate) use {
    classmethod0, classmethod1, classmethod_kwargs, getter3, method0, method1, method_kwargs2,
    method_vararg2, modmethod0, modmethod1, modmethod_vararg, slotmethod2,
};
