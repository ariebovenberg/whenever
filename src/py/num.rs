//! Functionality for Python's int and float types
use super::{base::*, exc::*, refs::*};
use core::ffi::c_long;
use core::mem;
use pyo3_ffi::*;

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub(crate) struct PyInt {
    obj: PyObj,
}

impl PyBase for PyInt {
    fn as_py_obj(&self) -> PyObj {
        self.obj
    }
}

impl FromPy for PyInt {
    unsafe fn from_ptr_unchecked(ptr: *mut PyObject) -> Self {
        Self {
            obj: unsafe { PyObj::from_ptr_unchecked(ptr) },
        }
    }
}

impl PyStaticType for PyInt {
    fn isinstance_exact(obj: impl PyBase) -> bool {
        unsafe { PyLong_CheckExact(obj.as_ptr()) != 0 }
    }

    fn isinstance(obj: impl PyBase) -> bool {
        unsafe { PyLong_Check(obj.as_ptr()) != 0 }
    }
}

impl PyInt {
    pub(crate) fn to_long(self) -> PyResult<c_long> {
        match unsafe { PyLong_AsLong(self.as_ptr()) } {
            x if x != -1 || unsafe { PyErr_Occurred() }.is_null() => Ok(x),
            // The error message is set for us
            _ => Err(PyErrMarker),
        }
    }

    pub(crate) fn to_i64(self) -> PyResult<i64> {
        match unsafe { PyLong_AsLongLong(self.as_ptr()) } {
            x if x != -1 || unsafe { PyErr_Occurred() }.is_null() => Ok(x),
            // The error message is set for us
            _ => Err(PyErrMarker),
        }
    }

    pub(crate) fn to_i128(self) -> PyResult<i128> {
        let mut bytes: [u8; 16] = [0; 16];
        #[cfg(not(Py_3_13))]
        {
            // This private API is the only direct 128-bit conversion before Python 3.13.
            if unsafe {
                _PyLong_AsByteArray(self.as_ptr().cast(), bytes.as_mut_ptr(), bytes.len(), 1, 1)
            } == 0
            {
                Ok(i128::from_le_bytes(bytes))
            } else {
                raise(
                    exc_overflow_error(),
                    "Python int too large to convert to i128",
                )
            }
        }
        #[cfg(Py_3_13)]
        {
            let size = unsafe {
                PyLong_AsNativeBytes(
                    self.as_ptr(),
                    bytes.as_mut_ptr().cast(),
                    bytes.len() as Py_ssize_t,
                    Py_ASNATIVEBYTES_NATIVE_ENDIAN,
                )
            };
            if size < 0 {
                Err(PyErrMarker)
            } else if size as usize > bytes.len() {
                raise(
                    exc_overflow_error(),
                    "Python int too large to convert to i128",
                )
            } else {
                Ok(i128::from_ne_bytes(bytes))
            }
        }
    }
}

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub(crate) struct PyFloat {
    obj: PyObj,
}

impl PyBase for PyFloat {
    fn as_py_obj(&self) -> PyObj {
        self.obj
    }
}

impl FromPy for PyFloat {
    unsafe fn from_ptr_unchecked(ptr: *mut PyObject) -> Self {
        Self {
            obj: unsafe { PyObj::from_ptr_unchecked(ptr) },
        }
    }
}

impl PyStaticType for PyFloat {
    fn isinstance_exact(obj: impl PyBase) -> bool {
        unsafe { PyFloat_CheckExact(obj.as_ptr()) != 0 }
    }

    fn isinstance(obj: impl PyBase) -> bool {
        unsafe { PyFloat_Check(obj.as_ptr()) != 0 }
    }
}

impl PyFloat {
    pub(crate) fn to_f64(self) -> PyResult<f64> {
        match unsafe { PyFloat_AsDouble(self.as_ptr()) } {
            x if x != -1.0 || unsafe { PyErr_Occurred() }.is_null() => Ok(x),
            // The error message is set for us
            _ => Err(PyErrMarker),
        }
    }
}

impl ToPy for i128 {
    fn to_py(self) -> PyReturn {
        #[cfg(not(Py_3_13))]
        let ptr = {
            // This private API is the only direct 128-bit conversion before Python 3.13.
            unsafe {
                _PyLong_FromByteArray(
                    self.to_le_bytes().as_ptr().cast(),
                    mem::size_of::<i128>(),
                    1,
                    1,
                )
            }
        };
        #[cfg(Py_3_13)]
        let ptr = {
            unsafe {
                PyLong_FromNativeBytes(
                    self.to_ne_bytes().as_ptr().cast(),
                    mem::size_of::<i128>(),
                    Py_ASNATIVEBYTES_NATIVE_ENDIAN,
                )
            }
        };
        ptr.own()
    }
}

impl ToPy for i64 {
    fn to_py(self) -> PyReturn {
        unsafe { PyLong_FromLongLong(self) }.own()
    }
}

impl ToPy for i32 {
    fn to_py(self) -> PyReturn {
        unsafe { PyLong_FromLong(self.into()) }.own()
    }
}

impl ToPy for f64 {
    fn to_py(self) -> PyReturn {
        unsafe { PyFloat_FromDouble(self) }.own()
    }
}

impl ToPy for u32 {
    fn to_py(self) -> PyReturn {
        unsafe { PyLong_FromUnsignedLong(self.into()) }.own()
    }
}

impl ToPy for u16 {
    fn to_py(self) -> PyReturn {
        unsafe { PyLong_FromUnsignedLong(self.into()) }.own()
    }
}

impl ToPy for u8 {
    fn to_py(self) -> PyReturn {
        unsafe { PyLong_FromUnsignedLong(self.into()) }.own()
    }
}

impl ToPy for bool {
    fn to_py(self) -> PyReturn {
        Ok(unsafe {
            PyObj::from_ptr_unchecked(match self {
                true => Py_True(),
                false => Py_False(),
            })
        }
        .newref())
    }
}
