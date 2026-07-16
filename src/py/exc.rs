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
#[must_use = "exception is set on the current thread; propagate with ? or clear with PyErr_Clear"]
pub(crate) struct PyErrMarker; // sentinel that the Python error indicator is set

pub(crate) type PyResult<T> = Result<T, PyErrMarker>;
pub(crate) type PyReturn = PyResult<Owned<PyObj>>;

/// Extension methods for [`PyResult`] to handle Python exceptions.
pub(crate) trait PyResultExt<T>: Sized {
    /// On error, clears the Python exception and returns `None`.
    fn or_clear(self) -> Option<T>;

    /// If the error matches `exc_type`, clears it and returns `Ok(None)`.
    /// Other errors propagate unchanged. On success, returns `Ok(Some(...))`.
    fn catch(self, exc_type: PyObj) -> PyResult<Option<T>>;
}

impl<T> PyResultExt<T> for PyResult<T> {
    fn or_clear(self) -> Option<T> {
        match self {
            Ok(x) => Some(x),
            Err(_) => {
                unsafe { PyErr_Clear() };
                None
            }
        }
    }

    fn catch(self, exc_type: PyObj) -> PyResult<Option<T>> {
        match self {
            Ok(x) => Ok(Some(x)),
            Err(e) => {
                if unsafe { PyErr_ExceptionMatches(exc_type.as_ptr()) } == 1 {
                    unsafe { PyErr_Clear() };
                    Ok(None)
                } else {
                    Err(e)
                }
            }
        }
    }
}

/// Returns the built-in [`PyObj`] for a Python exception type.
pub(crate) fn exc_import_error() -> PyObj {
    unsafe { PyObj::from_ptr_unchecked(PyExc_ImportError) }
}
pub(crate) fn exc_value_error() -> PyObj {
    unsafe { PyObj::from_ptr_unchecked(PyExc_ValueError) }
}
pub(crate) fn exc_type_error() -> PyObj {
    unsafe { PyObj::from_ptr_unchecked(PyExc_TypeError) }
}
pub(crate) fn exc_os_error() -> PyObj {
    unsafe { PyObj::from_ptr_unchecked(PyExc_OSError) }
}
pub(crate) fn exc_runtime_error() -> PyObj {
    unsafe { PyObj::from_ptr_unchecked(PyExc_RuntimeError) }
}
pub(crate) fn exc_zero_division_error() -> PyObj {
    unsafe { PyObj::from_ptr_unchecked(PyExc_ZeroDivisionError) }
}
pub(crate) fn exc_user_warning() -> PyObj {
    unsafe { PyObj::from_ptr_unchecked(PyExc_UserWarning) }
}
pub(crate) fn exc_overflow_error() -> PyObj {
    unsafe { PyObj::from_ptr_unchecked(PyExc_OverflowError) }
}

#[cold]
pub(crate) fn raise<T, U: ToPy>(exc: PyObj, msg: U) -> PyResult<T> {
    Err(exception(exc, msg))
}

#[cold]
pub(crate) fn exception<U: ToPy>(exc: PyObj, msg: U) -> PyErrMarker {
    // If the message conversion fails, an error is set for us.
    // It's mostly likely a MemoryError.
    if let Ok(m) = msg.to_py() {
        unsafe { PyErr_SetObject(exc.as_ptr(), m.as_ptr()) }
    };
    PyErrMarker
}

#[cold]
pub(crate) fn value_err<U: ToPy>(msg: U) -> PyErrMarker {
    exception(exc_value_error(), msg)
}

pub(crate) trait OptionExt<T> {
    fn ok_or_else_raise<F, M: ToPy>(self, exc: PyObj, fmt: F) -> PyResult<T>
    where
        Self: Sized,
        F: FnOnce() -> M;

    fn ok_or_raise<U: ToPy>(self, exc: PyObj, msg: U) -> PyResult<T>
    where
        Self: Sized,
    {
        self.ok_or_else_raise(exc, || msg)
    }

    fn ok_or_value_err<U: ToPy>(self, msg: U) -> PyResult<T>
    where
        Self: Sized,
    {
        self.ok_or_raise(exc_value_error(), msg)
    }

    fn ok_or_range_err(self) -> PyResult<T>
    where
        Self: Sized,
    {
        // FUTURE: can/should we intern this somehow, since it's static?
        self.ok_or_raise(exc_value_error(), "Value or calculation out of range")
    }

    fn ok_or_else_value_err<F, M: ToPy>(self, fmt: F) -> PyResult<T>
    where
        Self: Sized,
        F: FnOnce() -> M,
    {
        self.ok_or_else_raise(exc_value_error(), fmt)
    }

    fn ok_or_type_err<U: ToPy>(self, msg: U) -> PyResult<T>
    where
        Self: Sized,
    {
        self.ok_or_raise(exc_type_error(), msg)
    }
}

impl<T> OptionExt<T> for Option<T> {
    fn ok_or_else_raise<F, M: ToPy>(self, exc: PyObj, fmt: F) -> PyResult<T>
    where
        F: FnOnce() -> M,
    {
        match self {
            Some(x) => Ok(x),
            None => raise(exc, fmt()),
        }
    }
}

/// Extension trait for converting `Result<T, String>` into `PyResult<T>`,
/// treating the `String` error as a Python `ValueError` message.
pub(crate) trait ResultExt<T> {
    fn into_value_err(self) -> PyResult<T>;
}

impl<T> ResultExt<T> for Result<T, String> {
    fn into_value_err(self) -> PyResult<T> {
        self.map_err(value_err)
    }
}

#[cold]
pub(crate) fn raise_type_err<T, U: ToPy>(msg: U) -> PyResult<T> {
    raise(exc_type_error(), msg)
}

#[cold]
pub(crate) fn raise_value_err<T, U: ToPy>(msg: U) -> PyResult<T> {
    raise(exc_value_error(), msg)
}

/// Emit a warning using a custom warning class (e.g. a heap-type UserWarning subclass).
/// `stacklevel` controls how many frames to skip (1 = caller).
pub(crate) fn warn_with_class(warning_cls: PyObj, msg: &CStr, stacklevel: isize) -> PyResult<()> {
    match unsafe { PyErr_WarnEx(warning_cls.as_ptr(), msg.as_ptr(), stacklevel as _) } {
        0 => Ok(()),
        _ => Err(PyErrMarker),
    }
}
