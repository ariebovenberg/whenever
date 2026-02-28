//! Utilities for dealing with Python exceptions.
use std::ffi::CStr;

use super::{base::*, refs::*};
use pyo3_ffi::*;

// We use `Result` to implement Python's error handling.
// Note that Python's error handling doesn't map exactly onto Rust's `Result` type,
// The most important difference being that Python's error handling
// is based on a global error indicator.
// This means that some `Result` functionality will not behave as expected.
// However, this is a price we can pay in exchange for the convenience
// of the `?` operator.
#[derive(Debug, Copy, Clone, PartialEq, Eq, PartialOrd, Ord)]
pub(crate) struct PyErrMarker(); // sentinel that the Python error indicator is set

pub(crate) type PyResult<T> = Result<T, PyErrMarker>;
pub(crate) type PyReturn = PyResult<Owned<PyObj>>;

pub(crate) fn raise<T, U: ToPy>(exc: *mut PyObject, msg: U) -> PyResult<T> {
    Err(exception(exc, msg))
}

pub(crate) fn exception<U: ToPy>(exc: *mut PyObject, msg: U) -> PyErrMarker {
    // If the message conversion fails, an error is set for us.
    // It's mostly likely a MemoryError.
    if let Ok(m) = msg.to_py() {
        unsafe { PyErr_SetObject(exc, m.as_ptr()) }
    };
    PyErrMarker()
}

pub(crate) fn value_err<U: ToPy>(msg: U) -> PyErrMarker {
    exception(unsafe { PyExc_ValueError }, msg)
}

pub(crate) trait OptionExt<T> {
    fn ok_or_else_raise<F, M: ToPy>(self, exc: *mut PyObject, fmt: F) -> PyResult<T>
    where
        Self: Sized,
        F: FnOnce() -> M;

    fn ok_or_raise<U: ToPy>(self, exc: *mut PyObject, msg: U) -> PyResult<T>
    where
        Self: Sized,
    {
        self.ok_or_else_raise(exc, || msg)
    }

    fn ok_or_value_err<U: ToPy>(self, msg: U) -> PyResult<T>
    where
        Self: Sized,
    {
        self.ok_or_raise(unsafe { PyExc_ValueError }, msg)
    }

    fn ok_or_else_value_err<F, M: ToPy>(self, fmt: F) -> PyResult<T>
    where
        Self: Sized,
        F: FnOnce() -> M,
    {
        unsafe { self.ok_or_else_raise(PyExc_ValueError, fmt) }
    }

    fn ok_or_else_type_err<F, M: ToPy>(self, fmt: F) -> PyResult<T>
    where
        Self: Sized,
        F: FnOnce() -> M,
    {
        unsafe { self.ok_or_else_raise(PyExc_TypeError, fmt) }
    }

    fn ok_or_type_err<U: ToPy>(self, msg: U) -> PyResult<T>
    where
        Self: Sized,
    {
        self.ok_or_raise(unsafe { PyExc_TypeError }, msg)
    }
}

impl<T> OptionExt<T> for Option<T> {
    fn ok_or_else_raise<F, M: ToPy>(self, exc: *mut PyObject, fmt: F) -> PyResult<T>
    where
        F: FnOnce() -> M,
    {
        match self {
            Some(x) => Ok(x),
            None => raise(exc, fmt()),
        }
    }
}

pub(crate) fn raise_type_err<T, U: ToPy>(msg: U) -> PyResult<T> {
    raise(unsafe { PyExc_TypeError }, msg)
}

pub(crate) fn raise_value_err<T, U: ToPy>(msg: U) -> PyResult<T> {
    raise(unsafe { PyExc_ValueError }, msg)
}

pub(crate) fn raise_key_err<T>(key: PyObj) -> PyResult<T> {
    unsafe { PyErr_SetObject(PyExc_KeyError, key.as_ptr()) };
    Err(PyErrMarker())
}

/// Emit a warning using a custom warning class (e.g. a heap-type UserWarning subclass).
/// `stacklevel` controls how many frames to skip (1 = caller).
pub(crate) fn warn_with_class(
    warning_cls: PyObj,
    msg: &CStr,
    stacklevel: isize,
) -> PyResult<()> {
    match unsafe { PyErr_WarnEx(warning_cls.as_ptr(), msg.as_ptr(), stacklevel as _) } {
        0 => Ok(()),
        _ => Err(PyErrMarker()),
    }
}

/// A `Copy` wrapper around a Python `ContextVar[bool]`.
/// Owned by module state and manually `Py_CLEAR`'ed on shutdown—no refcount
/// management needed here.
#[derive(Debug, Clone, Copy)]
#[repr(transparent)]
pub(crate) struct ContextVarBool(PyObj);

impl ContextVarBool {
    /// Create a new `ContextVar[bool]` with default `False`,
    /// and set it as an attribute on `module`.
    pub(crate) fn create(name: &CStr, module: impl PyBase) -> PyResult<Self> {
        let cv = unsafe { PyContextVar_New(name.as_ptr(), Py_False()) }.rust_owned()?;
        module.setattr(name, cv.borrow())?;
        Ok(Self(cv.py_owned()))
    }

    pub(crate) fn as_ptr(self) -> *mut PyObject {
        self.0.as_ptr()
    }

    /// Read the current value of the context variable.
    /// Returns `false` if the variable is not set (default=False).
    pub(crate) fn get(self) -> PyResult<bool> {
        let mut value: *mut PyObject = std::ptr::null_mut();
        match unsafe { PyContextVar_Get(self.as_ptr(), std::ptr::null_mut(), &mut value) } {
            -1 => Err(PyErrMarker()),
            _ => {
                if value.is_null() {
                    Ok(false)
                } else {
                    let result = unsafe { PyObject_IsTrue(value) };
                    unsafe { Py_DECREF(value) };
                    match result {
                        -1 => Err(PyErrMarker()),
                        0 => Ok(false),
                        _ => Ok(true),
                    }
                }
            }
        }
    }
}
