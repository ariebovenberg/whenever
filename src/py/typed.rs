//! A generic newtype for objects statically known to be of a particular Python type.
use super::base::*;
use core::marker::PhantomData;
use pyo3_ffi::PyObject;

/// Identifies a Python type through its `Check`/`CheckExact` predicates.
pub(crate) trait TypeTag: Copy {
    fn check_exact(obj: PyObj) -> bool;
    fn check(obj: PyObj) -> bool;
}

/// A PyObj statically known to be of the type identified by tag `K`.
/// Transparent to PyObject to allow casting to/from PyObject.
#[repr(transparent)]
#[derive(Debug, Clone, Copy)]
pub(crate) struct Typed<K: TypeTag> {
    obj: PyObj,
    _tag: PhantomData<K>,
}

impl<K: TypeTag> PyBase for Typed<K> {
    fn as_py_obj(&self) -> PyObj {
        self.obj
    }
}

impl<K: TypeTag> FromPy for Typed<K> {
    unsafe fn from_ptr_unchecked(ptr: *mut PyObject) -> Self {
        Self {
            obj: unsafe { PyObj::from_ptr_unchecked(ptr) },
            _tag: PhantomData,
        }
    }
}

impl<K: TypeTag> PyStaticType for Typed<K> {
    fn isinstance_exact(obj: PyObj) -> bool {
        K::check_exact(obj)
    }

    fn isinstance(obj: PyObj) -> bool {
        K::check(obj)
    }
}

impl<K: TypeTag> std::fmt::Display for Typed<K> {
    fn fmt(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        self.write_repr(f)
    }
}
