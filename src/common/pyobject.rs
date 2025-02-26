use core::ffi::c_long;
use core::mem;
use pyo3_ffi::*;
use std::fmt::Debug;

// We use `Result` to implement Python's error handling.
// Note that Python's error handling doesn't map exactly onto Rust's `Result` type,
// The most important difference being that Python's error handling
// is based on a global error indicator.
// This means that some `Result` functionality will not behave as expected.
// However, this is a price we can pay in exchange for the convenience
// of the `?` operator.
#[derive(Debug, Copy, Clone, PartialEq, Eq, PartialOrd, Ord)]
pub(crate) struct PyErrOccurred(); // sentinel that the Python error indicator is set
pub(crate) type PyResult<T> = Result<T, PyErrOccurred>;
pub(crate) type PyReturn = PyResult<&'static mut PyObject>;

pub(crate) struct DecrefOnDrop(pub(crate) *mut PyObject);

impl Drop for DecrefOnDrop {
    fn drop(&mut self) {
        unsafe { Py_DECREF(self.0) };
    }
}

// Automatically decref the object when it goes out of scope
macro_rules! defer_decref(
    ($name:ident) => {
        let _deferred = DecrefOnDrop($name);
    };
);

// Apply this on arguments to have them decref'd after the containing expression.
// For function calls, it has the same effect as if the call would 'steal' the reference
macro_rules! steal(
    ($e:expr) => {
        DecrefOnDrop($e).0
    };
);

pub(crate) trait PyObjectExt {
    #[allow(clippy::wrong_self_convention)]
    unsafe fn as_result<'a>(self) -> PyResult<&'a mut PyObject>;
    #[allow(clippy::wrong_self_convention)]
    unsafe fn is_int(self) -> bool;
    #[allow(clippy::wrong_self_convention)]
    unsafe fn is_str(self) -> bool;
    #[allow(clippy::wrong_self_convention)]
    unsafe fn is_float(self) -> bool;
    // FUTURE: unchecked versions of these in case we know the type
    unsafe fn to_bytes<'a>(self) -> PyResult<Option<&'a [u8]>>;
    unsafe fn to_utf8<'a>(self) -> PyResult<Option<&'a [u8]>>;
    unsafe fn to_str<'a>(self) -> PyResult<Option<&'a str>>;
    unsafe fn to_long(self) -> PyResult<Option<c_long>>;
    unsafe fn to_i64(self) -> PyResult<Option<i64>>;
    unsafe fn to_i128(self) -> PyResult<Option<i128>>;
    unsafe fn to_f64(self) -> PyResult<Option<f64>>;
    unsafe fn repr(self) -> String;
    unsafe fn kwarg_eq(self, other: *mut PyObject) -> bool;
}

impl PyObjectExt for *mut PyObject {
    unsafe fn as_result<'a>(self) -> PyResult<&'a mut PyObject> {
        self.as_mut().ok_or(PyErrOccurred())
    }
    unsafe fn is_int(self) -> bool {
        PyLong_Check(self) != 0
    }

    unsafe fn is_float(self) -> bool {
        PyFloat_Check(self) != 0
    }

    unsafe fn is_str(self) -> bool {
        PyUnicode_Check(self) != 0
    }

    // WARNING: the string lifetime is only valid so long as the
    // Python object is alive
    unsafe fn to_bytes<'a>(self) -> PyResult<Option<&'a [u8]>> {
        if PyBytes_Check(self) == 0 {
            return Ok(None);
        };
        let p = PyBytes_AsString(self);
        if p.is_null() {
            return Err(PyErrOccurred());
        };
        Ok(Some(std::slice::from_raw_parts(
            p.cast::<u8>(),
            PyBytes_Size(self) as usize,
        )))
    }

    // WARNING: the string lifetime is only valid so long as the
    // Python object is alive
    unsafe fn to_utf8<'a>(self) -> PyResult<Option<&'a [u8]>> {
        if PyUnicode_Check(self) == 0 {
            return Ok(None);
        }
        let mut size = 0;
        let p = PyUnicode_AsUTF8AndSize(self, &mut size);
        if p.is_null() {
            return Err(PyErrOccurred());
        };
        Ok(Some(std::slice::from_raw_parts(
            p.cast::<u8>(),
            size as usize,
        )))
    }

    // WARNING: the string lifetime is only valid so long as the
    // Python object is alive
    unsafe fn to_str<'a>(self) -> PyResult<Option<&'a str>> {
        Ok(self.to_utf8()?.map(|s| std::str::from_utf8_unchecked(s)))
    }

    unsafe fn to_long(self) -> PyResult<Option<c_long>> {
        if PyLong_Check(self) == 0 {
            return Ok(None);
        }
        match PyLong_AsLong(self) {
            x if x != -1 || PyErr_Occurred().is_null() => Ok(Some(x)),
            // The error message is set for us
            _ => Err(PyErrOccurred()),
        }
    }

    unsafe fn to_i64(self) -> PyResult<Option<i64>> {
        // Although PyLong_AsLongLong can handle non-ints, we want to be strict and
        // opt out of accepting __int__, __index__ results.
        if PyLong_Check(self) == 0 {
            return Ok(None);
        }
        match PyLong_AsLongLong(self) {
            x if x != -1 || PyErr_Occurred().is_null() => Ok(Some(x)),
            // The error message is set for us
            _ => Err(PyErrOccurred()),
        }
    }

    unsafe fn to_i128(self) -> PyResult<Option<i128>> {
        if PyLong_Check(self) == 0 {
            return Ok(None);
        }
        let mut bytes: [u8; 16] = [0; 16];
        // Yes, this is a private API, but it's the only way to get a 128-bit integer
        // on Python < 3.13. Other libraries do this too.
        if _PyLong_AsByteArray(self.cast(), &mut bytes as *mut _, 16, 1, 1) == 0 {
            Ok(Some(i128::from_le_bytes(bytes)))
        } else {
            raise(
                PyExc_OverflowError,
                "Python int too large to convert to i128",
            )
        }
    }

    unsafe fn to_f64(self) -> PyResult<Option<f64>> {
        // Although PyFloat_AsDouble can handle non-floats, we want to be strict and
        // opt out of accepting __float__ and __index__ results.
        if PyFloat_Check(self) == 0 {
            return Ok(None);
        }
        match PyFloat_AsDouble(self) {
            x if x != -1.0 || PyErr_Occurred().is_null() => Ok(Some(x)),
            // The error message is set for us
            _ => Err(PyErrOccurred()),
        }
    }

    unsafe fn repr(self) -> String {
        let repr_obj = PyObject_Repr(self);
        if repr_obj.is_null() {
            // i.e repr() raised an exception, or it didn't return a string.
            // Let's clear the exception and return a placeholder.
            PyErr_Clear();
            return "<repr() failed>".to_string();
        }
        defer_decref!(repr_obj);
        debug_assert!(repr_obj.is_str());
        match repr_obj.to_str() {
            Ok(Some(r)) => r,
            _ => {
                PyErr_Clear();
                "<repr() failed>"
            }
        }
        // We need to return owned data, so it outlives the Python string
        // object. repr() is generally not part of performance-critical code
        // anyway, so this is acceptable.
        .to_string()
    }

    // A faster comparison for keyword arguments that leverages
    // the fact that keyword arguments are generally (but not always!) interned.
    unsafe fn kwarg_eq(self, other: *mut PyObject) -> bool {
        self == other || PyObject_RichCompareBool(self, other, Py_EQ) == 1
    }
}

pub(crate) unsafe fn raise<T, U: ToPy>(exc: *mut PyObject, msg: U) -> PyResult<T> {
    Err(exception(exc, msg))
}

pub(crate) unsafe fn exception<U: ToPy>(exc: *mut PyObject, msg: U) -> PyErrOccurred {
    // If the message conversion fails, an error is set for us.
    // It's mostly likely a MemoryError.
    if let Ok(msg) = msg.to_py() {
        PyErr_SetObject(exc, msg);
    };
    PyErrOccurred()
}

pub(crate) unsafe fn value_err<U: ToPy>(msg: U) -> PyErrOccurred {
    exception(PyExc_ValueError, msg)
}

pub(crate) trait OptionExt<T> {
    unsafe fn ok_or_else_raise<F, M: ToPy>(self, exc: *mut PyObject, fmt: F) -> PyResult<T>
    where
        Self: Sized,
        F: FnOnce() -> M;

    unsafe fn ok_or_raise<U: ToPy>(self, exc: *mut PyObject, msg: U) -> PyResult<T>
    where
        Self: Sized,
    {
        self.ok_or_else_raise(exc, || msg)
    }

    unsafe fn ok_or_value_err<U: ToPy>(self, msg: U) -> PyResult<T>
    where
        Self: Sized,
    {
        self.ok_or_raise(PyExc_ValueError, msg)
    }

    unsafe fn ok_or_else_value_err<F, M: ToPy>(self, fmt: F) -> PyResult<T>
    where
        Self: Sized,
        F: FnOnce() -> M,
    {
        self.ok_or_else_raise(PyExc_ValueError, fmt)
    }

    unsafe fn ok_or_type_err<U: ToPy>(self, msg: U) -> PyResult<T>
    where
        Self: Sized,
    {
        self.ok_or_raise(PyExc_TypeError, msg)
    }
}

impl<T> OptionExt<T> for Option<T> {
    unsafe fn ok_or_else_raise<F, M: ToPy>(self, exc: *mut PyObject, fmt: F) -> PyResult<T>
    where
        F: FnOnce() -> M,
    {
        match self {
            Some(x) => Ok(x),
            None => raise(exc, fmt()),
        }
    }
}

pub(crate) unsafe fn raise_type_err<T, U: ToPy>(msg: U) -> PyResult<T> {
    raise(PyExc_TypeError, msg)
}

pub(crate) unsafe fn raise_value_err<T, U: ToPy>(msg: U) -> PyResult<T> {
    raise(PyExc_ValueError, msg)
}

pub(crate) trait ToPy {
    unsafe fn to_py(self) -> PyReturn;
}

impl ToPy for bool {
    unsafe fn to_py(self) -> PyReturn {
        Ok(newref(
            match self {
                true => Py_True(),
                false => Py_False(),
            }
            // True/False pointers are never null, unless something is seriously wrong
            .as_mut()
            .unwrap(),
        ))
    }
}

impl ToPy for i128 {
    unsafe fn to_py(self) -> PyReturn {
        // Yes, this is a private API, but it's the only way to create a 128-bit integer
        // on Python < 3.13. Other libraries do this too.
        _PyLong_FromByteArray(
            self.to_le_bytes().as_ptr().cast(),
            mem::size_of::<i128>(),
            1,
            1,
        )
        .as_result()
    }
}

impl ToPy for i64 {
    unsafe fn to_py(self) -> PyReturn {
        PyLong_FromLongLong(self).as_result()
    }
}

impl ToPy for i32 {
    unsafe fn to_py(self) -> PyReturn {
        PyLong_FromLong(self.into()).as_result()
    }
}

impl ToPy for f64 {
    unsafe fn to_py(self) -> PyReturn {
        PyFloat_FromDouble(self).as_result()
    }
}

impl ToPy for u32 {
    unsafe fn to_py(self) -> PyReturn {
        PyLong_FromUnsignedLong(self.into()).as_result()
    }
}

impl ToPy for u16 {
    unsafe fn to_py(self) -> PyReturn {
        PyLong_FromUnsignedLong(self.into()).as_result()
    }
}

impl ToPy for u8 {
    unsafe fn to_py(self) -> PyReturn {
        PyLong_FromUnsignedLong(self.into()).as_result()
    }
}

impl ToPy for String {
    unsafe fn to_py(self) -> PyReturn {
        PyUnicode_FromStringAndSize(self.as_ptr().cast(), self.len() as _).as_result()
    }
}

impl ToPy for &str {
    unsafe fn to_py(self) -> PyReturn {
        PyUnicode_FromStringAndSize(self.as_ptr().cast(), self.len() as _).as_result()
    }
}

impl ToPy for &[u8] {
    unsafe fn to_py(self) -> PyReturn {
        PyBytes_FromStringAndSize(self.as_ptr().cast(), self.len() as _).as_result()
    }
}

impl<T> ToPy for (T,) {
    unsafe fn to_py(self) -> PyReturn {
        PyTuple_Pack(1, self.0).as_result()
    }
}

impl<T, U> ToPy for (T, U) {
    unsafe fn to_py(self) -> PyReturn {
        PyTuple_Pack(2, self.0, self.1).as_result()
    }
}

impl<T, U, V> ToPy for (T, U, V) {
    unsafe fn to_py(self) -> PyReturn {
        PyTuple_Pack(3, self.0, self.1, self.2).as_result()
    }
}

impl<T, U, V, W> ToPy for (T, U, V, W) {
    unsafe fn to_py(self) -> PyReturn {
        PyTuple_Pack(4, self.0, self.1, self.2, self.3).as_result()
    }
}

impl<T, U, V, W, X> ToPy for (T, U, V, W, X) {
    unsafe fn to_py(self) -> PyReturn {
        PyTuple_Pack(5, self.0, self.1, self.2, self.3, self.4).as_result()
    }
}

pub(crate) unsafe fn identity1(slf: *mut PyObject) -> PyReturn {
    Ok(newref(slf))
}

pub(crate) unsafe fn identity2(slf: *mut PyObject, _: *mut PyObject) -> PyReturn {
    Ok(newref(slf))
}

pub(crate) unsafe fn newref<'a>(obj: *mut PyObject) -> &'a mut PyObject {
    Py_INCREF(obj);
    obj.as_mut().unwrap()
}

// FUTURE: replace with Py_IsNone when dropping Py 3.9 support
pub(crate) unsafe fn is_none(x: *mut PyObject) -> bool {
    x == Py_None()
}

#[allow(unused_imports)]
pub(crate) use {defer_decref, steal};
