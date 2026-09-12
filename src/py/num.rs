//! Functionality for Python's int and float types
use super::{base::*, exc::*, refs::*, typed::*};
use core::mem;
use pyo3_ffi::*;

/// Whether CPython's native `l` integer parser writes a 64-bit value on this platform.
pub(crate) const IS_LP64: bool = cfg!(all(target_pointer_width = "64", not(windows)));

#[derive(Debug, Clone, Copy)]
pub(crate) struct IntTag;

impl TypeTag for IntTag {
    fn check_exact(obj: PyObj) -> bool {
        unsafe { PyLong_CheckExact(obj.as_ptr()) != 0 }
    }

    fn check(obj: PyObj) -> bool {
        unsafe { PyLong_Check(obj.as_ptr()) != 0 }
    }
}

pub(crate) type PyInt = Typed<IntTag>;

impl Typed<IntTag> {
    pub(crate) fn to_i64(self) -> PyResult<i64> {
        // PyLong_AsLong is measurably faster on LP64, where its result is already 64 bits.
        let value = if IS_LP64 {
            (unsafe { PyLong_AsLong(self.as_ptr()) }) as i64
        } else {
            unsafe { PyLong_AsLongLong(self.as_ptr()) }
        };
        match value {
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

impl PyObj {
    /// Read an integer through the index protocol (`__index__`), as
    /// CPython's own argument parser does. A `bool` passes; a `float` does not.
    pub(crate) fn expect_int(self, name: &str) -> PyResult<Owned<PyInt>> {
        if unsafe { PyIndex_Check(self.as_ptr()) } == 0 {
            raise_type_err(format!("{name} must be an integer"))?
        }
        // SAFETY: PyNumber_Index returns a new reference to an int on success
        unsafe { PyNumber_Index(self.as_ptr()) }
            .own()
            .map(|obj| unsafe { obj.cast_unchecked::<PyInt>() })
    }
}

#[derive(Debug, Clone, Copy)]
pub(crate) struct FloatTag;

impl TypeTag for FloatTag {
    fn check_exact(obj: PyObj) -> bool {
        unsafe { PyFloat_CheckExact(obj.as_ptr()) != 0 }
    }

    fn check(obj: PyObj) -> bool {
        unsafe { PyFloat_Check(obj.as_ptr()) != 0 }
    }
}

pub(crate) type PyFloat = Typed<FloatTag>;

impl Typed<FloatTag> {
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
