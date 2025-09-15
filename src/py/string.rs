//! Functionality for working with Python's `str` and `bytes` objects.
use crate::common::fmt;

use super::{base::*, exc::*, refs::*};
use pyo3_ffi::*;
use std::{ffi::c_uint, ptr::copy_nonoverlapping};

#[derive(Debug, Clone, Copy)]
pub(crate) struct PyStr {
    obj: PyObj,
}

impl PyStr {
    pub(crate) fn as_utf8(&self) -> PyResult<&[u8]> {
        let mut size = 0;
        let p = unsafe { PyUnicode_AsUTF8AndSize(self.as_ptr(), &mut size) };
        if p.is_null() {
            return Err(PyErrMarker());
        };
        Ok(unsafe { std::slice::from_raw_parts(p.cast::<u8>(), size as usize) })
    }

    pub(crate) fn as_str(&self) -> PyResult<&str> {
        let mut size = 0;
        let p = unsafe { PyUnicode_AsUTF8AndSize(self.as_ptr(), &mut size) };
        if p.is_null() {
            return Err(PyErrMarker());
        };
        Ok(unsafe {
            std::str::from_utf8_unchecked(std::slice::from_raw_parts(p.cast::<u8>(), size as usize))
        })
    }
}

impl PyBase for PyStr {
    fn as_py_obj(&self) -> PyObj {
        self.obj
    }
}

impl FromPy for PyStr {
    unsafe fn from_ptr_unchecked(ptr: *mut PyObject) -> Self {
        Self {
            obj: unsafe { PyObj::from_ptr_unchecked(ptr) },
        }
    }
}

impl PyStaticType for PyStr {
    fn isinstance_exact(obj: impl PyBase) -> bool {
        unsafe { PyUnicode_CheckExact(obj.as_ptr()) != 0 }
    }

    fn isinstance(obj: impl PyBase) -> bool {
        unsafe { PyUnicode_Check(obj.as_ptr()) != 0 }
    }
}

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub(crate) struct PyBytes {
    obj: PyObj,
}

impl PyBase for PyBytes {
    fn as_py_obj(&self) -> PyObj {
        self.obj
    }
}

impl FromPy for PyBytes {
    unsafe fn from_ptr_unchecked(ptr: *mut PyObject) -> Self {
        Self {
            obj: unsafe { PyObj::from_ptr_unchecked(ptr) },
        }
    }
}

impl PyStaticType for PyBytes {
    fn isinstance_exact(obj: impl PyBase) -> bool {
        unsafe { PyBytes_CheckExact(obj.as_ptr()) != 0 }
    }

    fn isinstance(obj: impl PyBase) -> bool {
        unsafe { PyBytes_Check(obj.as_ptr()) != 0 }
    }
}

impl PyBytes {
    pub(crate) fn as_bytes(&self) -> PyResult<&[u8]> {
        // FUTURE: is there a way to use unchecked versions of
        // the C API: PyBytes_AS_STRING, PyBytes_GET_SIZE?
        let p = unsafe { PyBytes_AsString(self.as_ptr()) };
        if p.is_null() {
            return Err(PyErrMarker());
        };
        Ok(unsafe {
            std::slice::from_raw_parts(p.cast::<u8>(), PyBytes_Size(self.as_ptr()) as usize)
        })
    }
}

impl ToPy for String {
    fn to_py(self) -> PyReturn {
        unsafe { PyUnicode_FromStringAndSize(self.as_ptr().cast(), self.len() as _) }.rust_owned()
    }
}

impl ToPy for &str {
    fn to_py(self) -> PyReturn {
        unsafe { PyUnicode_FromStringAndSize(self.as_ptr().cast(), self.len() as _) }.rust_owned()
    }
}

impl ToPy for &[u8] {
    fn to_py(self) -> PyReturn {
        unsafe { PyBytes_FromStringAndSize(self.as_ptr().cast(), self.len() as _) }.rust_owned()
    }
}

impl<const N: usize> ToPy for [u8; N] {
    fn to_py(self) -> PyReturn {
        unsafe { PyBytes_FromStringAndSize(self.as_ptr().cast(), N as _) }.rust_owned()
    }
}

/// Helper for building a Python `str` object incrementally, without
/// having to allocate a Rust `String` first.
///
/// SAFETY: This only supports ASCII strings (i.e. code points 0..=127).
/// There is no bounds checking, so the caller must ensure that only
/// valid ASCII characters are written, and that the total length does
/// not exceed the length specified at creation.
#[derive(Debug)]
pub(crate) struct PyAsciiStrBuilder {
    obj: Owned<PyObj>, // the PyUnicode object being built. Owned ensures cleanup.
    index: Py_ssize_t, // current write index
    data: *mut u8,     // PyUnicode_DATA() pointer
    #[cfg(debug_assertions)]
    _len: Py_ssize_t, // length of the string (for debug assertions)
}

const ASCII_STR_KIND: c_uint = 1;

impl PyAsciiStrBuilder {
    /// Create a new builder for a string of the given length.
    fn new(len: usize) -> PyResult<Self> {
        let obj = unsafe { PyUnicode_New(len as _, 127) }.rust_owned()?;
        debug_assert!(unsafe { PyUnicode_KIND(obj.as_ptr()) == ASCII_STR_KIND });
        Ok(Self {
            data: unsafe { PyUnicode_DATA(obj.as_ptr()).cast() },
            index: 0,
            obj,
            #[cfg(debug_assertions)]
            _len: len as Py_ssize_t,
        })
    }

    /// Finalize the builder and return the built `str` object.
    fn finish(self) -> Owned<PyObj> {
        #[cfg(debug_assertions)]
        assert_eq!(self.index, self._len); // DEBUG: full length written
        self.obj
    }

    pub(crate) fn format(c: impl fmt::Chunk) -> PyResult<Owned<PyObj>> {
        let mut sink = Self::new(c.len())?;
        c.write(&mut sink);
        Ok(sink.finish())
    }
}

impl fmt::Sink for PyAsciiStrBuilder {
    #[inline]
    fn write_byte(&mut self, b: u8) {
        debug_assert!(b.is_ascii());
        #[cfg(debug_assertions)]
        assert!(self.index < self._len);
        // Essentially the PyUnicode_WRITE() macro from the CPython API
        unsafe { *self.data.offset(self.index) = b };
        self.index += 1;
    }

    #[inline]
    fn write(&mut self, s: &[u8]) {
        debug_assert!(s.is_ascii());
        #[cfg(debug_assertions)]
        assert!(self.index + s.len() as Py_ssize_t <= self._len);
        unsafe { copy_nonoverlapping(s.as_ptr(), self.data.offset(self.index), s.len()) };
        self.index += s.len() as Py_ssize_t;
    }
}
