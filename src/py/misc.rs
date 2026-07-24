//! Miscellaneous utility functions and constants.
use super::{args::*, base::*, exc::*, refs::*, types::*};
use crate::common::sync::SwapPtr;
use core::ffi::{CStr, c_int, c_void};
use pyo3_ffi::*;

/// A lazily-initialized Python object with GC traverse and cleanup support.
/// Uses lock-free CAS on a `SwapPtr` for initialization.
/// Returns `PyObj` by value (Copy) — no reference lifetime concerns.
pub(crate) struct OncePyObj {
    init: fn() -> PyReturn,
    ptr: SwapPtr<PyObject>,
}

impl OncePyObj {
    pub(crate) const fn new(init: fn() -> PyReturn) -> Self {
        Self {
            init,
            ptr: SwapPtr::new(None),
        }
    }

    #[inline]
    pub(crate) fn get(&self) -> PyResult<PyObj> {
        if let Some(p) = self.ptr.load() {
            return Ok(PyObj::new(p));
        }
        self.get_slow()
    }

    #[cold]
    fn get_slow(&self) -> PyResult<PyObj> {
        let owned = (self.init)()?;
        // SAFETY: `owned` transfers a valid reference which remains stored in this cell.
        let obj = unsafe { PyObj::from_ptr_unchecked(owned.into_raw()) };
        match self.ptr.try_init(obj.as_nonnull()) {
            Ok(()) => Ok(obj),
            Err(winner) => {
                // Another init won the race — DECREF ours, return theirs
                unsafe { Py_DECREF(obj.as_ptr()) };
                Ok(PyObj::new(winner))
            }
        }
    }

    pub(crate) fn gc_traverse(&self, visit: visitproc, arg: *mut c_void) -> TraverseResult {
        if let Some(p) = self.ptr.load() {
            traverse(p.as_ptr(), visit, arg)?;
        }
        Ok(())
    }
}

impl Drop for OncePyObj {
    fn drop(&mut self) {
        if let Some(p) = self.ptr.swap(None) {
            unsafe { Py_DECREF(p.as_ptr()) };
        }
    }
}

pub(crate) fn none() -> Owned<PyObj> {
    // SAFETY: Py_None is a valid pointer
    unsafe { PyObj::from_ptr_unchecked(Py_None()) }.newref()
}

/// Slot function for unary positive: just returns a new reference to self.
pub(crate) const IDENTITY_SLOT: PyType_Slot = PyType_Slot {
    slot: Py_nb_positive,
    pfunc: {
        unsafe extern "C" fn _wrap(slf: *mut PyObject) -> *mut PyObject {
            unsafe { pyo3_ffi::Py_NewRef(slf) }
        }
        _wrap as *mut c_void
    },
};

/// __copy__ slot: immutable objects just return a new reference to self.
pub(crate) const COPY_METHOD: PyMethodDef = PyMethodDef {
    ml_name: c"__copy__".as_ptr().cast(),
    ml_meth: PyMethodDefPointer {
        PyCFunction: {
            unsafe extern "C" fn _wrap(slf: *mut PyObject, _: *mut PyObject) -> *mut PyObject {
                unsafe { pyo3_ffi::Py_NewRef(slf) }
            }
            _wrap
        },
    },
    ml_flags: METH_NOARGS,
    ml_doc: c"".as_ptr(),
};

/// __deepcopy__ slot: immutable objects just return a new reference to self.
pub(crate) const DEEPCOPY_METHOD: PyMethodDef = PyMethodDef {
    ml_name: c"__deepcopy__".as_ptr().cast(),
    ml_meth: PyMethodDefPointer {
        PyCFunction: {
            unsafe extern "C" fn _wrap(slf: *mut PyObject, _: *mut PyObject) -> *mut PyObject {
                unsafe { pyo3_ffi::Py_NewRef(slf) }
            }
            _wrap
        },
    },
    ml_flags: METH_O,
    ml_doc: c"".as_ptr(),
};

pub(crate) fn import(module: &CStr) -> PyReturn {
    unsafe { PyImport_ImportModule(module.as_ptr()) }.own()
}

pub(crate) fn __get_pydantic_core_schema__<T: PyPayload>(
    cls: PyClass<T>,
    _: &[PyObj],
    _: &mut IterKwargs,
) -> PyReturn {
    cls.state().get_pydantic_schema.get()?.call1(cls)
}

pub(crate) fn not_implemented() -> PyReturn {
    Ok(
        // SAFETY: Py_NotImplemented is always non-null
        unsafe { PyObj::from_ptr_unchecked(Py_NotImplemented()) }.newref(),
    )
}

// FUTURE: a more efficient way for specific cases?
pub(crate) const fn hashmask(hash: Py_hash_t) -> Py_hash_t {
    if hash == -1 {
        return -2;
    }
    hash
}

/// fast, safe way to combine hash values, from stackoverflow.com/questions/5889238
#[inline]
pub(crate) const fn hash_combine(lhs: Py_hash_t, rhs: Py_hash_t) -> Py_hash_t {
    #[cfg(target_pointer_width = "64")]
    {
        lhs ^ (rhs
            .wrapping_add(0x517cc1b727220a95)
            .wrapping_add(lhs << 6)
            .wrapping_add(lhs >> 2))
    }
    #[cfg(target_pointer_width = "32")]
    {
        lhs ^ (rhs
            .wrapping_add(-0x61c88647)
            .wrapping_add(lhs << 6)
            .wrapping_add(lhs >> 2))
    }
}

/// Result from traversing a Python object for garbage collection.
pub(crate) type TraverseResult = Result<(), c_int>;

pub(crate) fn traverse(
    target: *mut PyObject,
    visit: visitproc,
    arg: *mut c_void,
) -> TraverseResult {
    if target.is_null() {
        Ok(())
    } else {
        match unsafe { (visit)(target, arg) } {
            0 => Ok(()),
            n => Err(n),
        }
    }
}
