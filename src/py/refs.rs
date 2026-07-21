//! Functionality relating to ownership and references
use super::{base::*, exc::*};
use core::mem::ManuallyDrop;
use core::ptr::null_mut as NULL;
use pyo3_ffi::*;
use std::ptr::NonNull;

/// A wrapper for Python objects that have a reference owned by Rust.
/// They are decreferred on drop.
#[derive(Debug)]
pub(crate) struct Owned<T: PyBase> {
    inner: T,
}

impl<T: PyBase> Owned<T> {
    /// Construct an owned reference from a pointer for which the caller owns a reference.
    ///
    /// # Safety
    /// `ptr` must be non-null, point to a `T`, and transfer one owned reference to this value.
    pub(crate) unsafe fn from_owned_ptr(ptr: *mut PyObject) -> Self {
        Self {
            inner: unsafe { T::from_ptr_unchecked(ptr) },
        }
    }

    /// Transfer ownership to the caller without decrementing the reference count.
    pub(crate) fn into_raw(self) -> *mut PyObject {
        let this = ManuallyDrop::new(self);
        this.inner.as_ptr()
    }

    /// Upcast to `Owned<PyObj>`, losing the specific subtype.
    pub(crate) fn into_obj(self) -> Owned<PyObj> {
        let ptr = self.into_raw();
        // SAFETY: the pointer and its owned reference are transferred unchanged.
        unsafe { Owned::from_owned_ptr(ptr) }
    }

    pub(crate) fn cast_exact<U: PyStaticType>(self) -> Result<Owned<U>, Self> {
        if U::isinstance_exact(self.inner) {
            let ptr = self.into_raw();
            // SAFETY: the exact type check succeeded and ownership is transferred unchanged.
            Ok(unsafe { Owned::from_owned_ptr(ptr) })
        } else {
            Err(self)
        }
    }

    pub(crate) fn cast_allow_subclass<U: PyStaticType>(self) -> Result<Owned<U>, Self> {
        if U::isinstance(self.inner) {
            let ptr = self.into_raw();
            // SAFETY: the type check succeeded and ownership is transferred unchanged.
            Ok(unsafe { Owned::from_owned_ptr(ptr) })
        } else {
            Err(self)
        }
    }

    pub(crate) unsafe fn cast_unchecked<U: PyBase>(self) -> Owned<U> {
        let ptr = self.into_raw();
        // SAFETY: the caller guarantees the pointee has type U; ownership is unchanged.
        unsafe { Owned::from_owned_ptr(ptr) }
    }
}

impl<T: PyBase> Drop for Owned<T> {
    fn drop(&mut self) {
        unsafe {
            // SAFETY: we hold a reference to the object, so it's guaranteed to be valid
            Py_DECREF(self.inner.as_ptr());
        }
    }
}

impl<T: PyBase> std::ops::Deref for Owned<T> {
    type Target = T;

    fn deref(&self) -> &Self::Target {
        &self.inner
    }
}

pub(crate) trait PyObjectExt {
    fn own(self) -> PyResult<Owned<PyObj>>;
    fn borrow(self) -> PyResult<PyObj>;
    fn borrow_opt(self) -> Option<PyObj>;
}

impl PyObjectExt for *mut PyObject {
    /// Take ownership of a raw PyObject, interpreting NULL as an error.
    fn own(self) -> PyResult<Owned<PyObj>> {
        self.borrow()?;
        // SAFETY: CPython APIs used with `own()` transfer a new reference on success.
        Ok(unsafe { Owned::from_owned_ptr(self) })
    }

    /// Wrap a raw PyObject, interpreting NULL as an error.
    fn borrow(self) -> PyResult<PyObj> {
        NonNull::new(self).map(PyObj::new).ok_or(PyErrMarker)
    }

    /// Wrap a raw PyObject, interpreting NULL as None.
    fn borrow_opt(self) -> Option<PyObj> {
        NonNull::new(self).map(PyObj::new)
    }
}

pub(crate) trait ToPyOwnedPtr {
    fn to_py_owned_ptr(self) -> *mut PyObject;
}

impl ToPyOwnedPtr for *mut PyObject {
    fn to_py_owned_ptr(self) -> *mut PyObject {
        self
    }
}

impl<T: PyBase> ToPyOwnedPtr for PyResult<Owned<T>> {
    fn to_py_owned_ptr(self) -> *mut PyObject {
        match self {
            Ok(x) => x.into_raw(),
            Err(_) => NULL(),
        }
    }
}

impl<T: PyBase> ToPyOwnedPtr for Owned<T> {
    fn to_py_owned_ptr(self) -> *mut PyObject {
        self.into_raw()
    }
}
