//! Functions for dealing with Python tuples.
use super::{base::*, exc::*, refs::*};
use pyo3_ffi::*;

#[derive(Debug, Clone, Copy)]
pub(crate) struct PyTuple {
    obj: PyObj,
}

impl PyBase for PyTuple {
    fn as_py_obj(&self) -> PyObj {
        self.obj
    }
}

impl FromPy for PyTuple {
    unsafe fn from_ptr_unchecked(ptr: *mut PyObject) -> Self {
        Self {
            obj: unsafe { PyObj::from_ptr_unchecked(ptr) },
        }
    }
}

impl PyStaticType for PyTuple {
    fn isinstance_exact(obj: impl PyBase) -> bool {
        unsafe { PyTuple_CheckExact(obj.as_ptr()) != 0 }
    }

    fn isinstance(obj: impl PyBase) -> bool {
        unsafe { PyTuple_Check(obj.as_ptr()) != 0 }
    }
}

impl PyTuple {
    pub(crate) fn len(&self) -> Py_ssize_t {
        unsafe { PyTuple_GET_SIZE(self.obj.as_ptr()) }
    }

    pub(crate) fn iter(&self) -> PyTupleIter {
        PyTupleIter {
            obj: self.as_ptr(),
            index: 0,
            size: self.len(),
        }
    }

    /// Create a new tuple with the given length.
    pub(crate) fn with_len(len: Py_ssize_t) -> PyResult<Owned<Self>> {
        Ok(unsafe { PyTuple_New(len).own()?.cast_unchecked::<PyTuple>() })
    }
}

impl Owned<PyTuple> {
    /// Set an item in a tuple being constructed, stealing the value's reference.
    ///
    /// # Safety
    ///
    /// `index` must be in bounds and refer to an uninitialized slot, and the tuple must not have
    /// been exposed to Python.
    pub(crate) unsafe fn init_item_unchecked(&self, index: Py_ssize_t, value: Owned<impl PyBase>) {
        unsafe { PyTuple_SET_ITEM(self.as_ptr(), index, value.into_raw()) };
    }
}

pub(crate) struct PyTupleIter {
    obj: *mut PyObject,
    index: Py_ssize_t,
    size: Py_ssize_t,
}

impl Iterator for PyTupleIter {
    type Item = PyObj;

    fn next(&mut self) -> Option<Self::Item> {
        if self.index >= self.size {
            return None;
        }
        let result = unsafe { PyObj::from_ptr_unchecked(PyTuple_GET_ITEM(self.obj, self.index)) };
        self.index += 1;
        Some(result)
    }
}

pub(crate) trait IntoPyTuple {
    fn into_pytuple(self) -> PyReturn;
}

impl<const N: usize, T: PyBase> IntoPyTuple for [Owned<T>; N] {
    fn into_pytuple(self) -> PyReturn {
        let tuple = PyTuple::with_len(N as _)?;
        for (i, item) in self.into_iter().enumerate() {
            // SAFETY: the tuple has N uninitialized slots and enumerate visits each exactly once.
            unsafe { tuple.init_item_unchecked(i as _, item) };
        }
        Ok(tuple.into_obj())
    }
}
