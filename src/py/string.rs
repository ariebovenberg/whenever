//! Functionality for working with Python's `str` and `bytes` objects.
use super::{base::*, exc::*, refs::*};
use pyo3_ffi::*;

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

#[derive(Debug, Clone, Copy)]
pub(crate) struct PyAsciiStrBuilder {
    obj: PyObj,
    index: Py_ssize_t,
}

impl PyBase for PyAsciiStrBuilder {
    fn as_py_obj(&self) -> PyObj {
        self.obj
    }
}

impl FromPy for PyAsciiStrBuilder {
    unsafe fn from_ptr_unchecked(ptr: *mut PyObject) -> Self {
        // TODO: this implementation isn't used
        Self {
            obj: unsafe { PyObj::from_ptr_unchecked(ptr) },
            index: 0,
        }
    }
}

impl PyAsciiStrBuilder {
    pub(crate) fn new(len: usize) -> PyResult<Owned<Self>> {
        Ok(unsafe {
            PyUnicode_New(len as _, 0)
                .rust_owned()?
                .cast_unchecked::<Self>()
        })
    }

    pub(crate) fn write_slice(&mut self, s: &[u8]) -> PyResult<()> {
        for &c in s {
            self.write_char(c)?;
        }
        Ok(())
    }

    pub(crate) fn write_char(&mut self, c: u8) -> PyResult<()> {
        if unsafe { PyUnicode_WriteChar(self.as_ptr(), self.index, c as _) } == -1 {
            return Err(PyErrMarker());
        }
        self.index += 1;
        Ok(())
    }
}

impl Owned<PyAsciiStrBuilder> {
    pub(crate) fn finish(self) -> Owned<PyObj> {
        unsafe { self.cast_unchecked::<PyObj>() }
    }
}
