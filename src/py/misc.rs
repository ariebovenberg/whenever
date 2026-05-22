//! Miscellaneous utility functions and constants.
use super::{args::*, base::*, exc::*, refs::*, types::*};
use core::ffi::{CStr, c_int, c_void};
use pyo3_ffi::*;

pub(crate) fn none() -> Owned<PyObj> {
    // SAFETY: Py_None is a valid pointer
    unsafe { PyObj::from_ptr_unchecked(Py_None()) }.newref()
}

pub(crate) fn identity1(_: PyType, slf: PyObj) -> Owned<PyObj> {
    slf.newref()
}

pub(crate) fn __copy__(_: PyType, slf: PyObj) -> Owned<PyObj> {
    slf.newref()
}

pub(crate) fn __deepcopy__(_: PyType, slf: PyObj, _: PyObj) -> Owned<PyObj> {
    slf.newref()
}

pub(crate) fn import(module: &CStr) -> PyReturn {
    unsafe { PyImport_ImportModule(module.as_ptr()) }.rust_owned()
}

pub(crate) fn __get_pydantic_core_schema__<T: PyWrapped>(
    cls: HeapType<T>,
    _: &[PyObj],
    _: &mut IterKwargs,
) -> PyReturn {
    cls.state().get_pydantic_schema.get()?.call1(cls)
}

pub(crate) fn not_implemented() -> PyReturn {
    Ok(Owned::new(
        // SAFETY: Py_NotImplemented is always non-null
        unsafe { PyObj::from_ptr_unchecked(Py_NewRef(Py_NotImplemented())) },
    ))
}

/// Pack various types into a byte array. Used for pickling.
macro_rules! pack {
    [$x:expr, $($xs:expr),*] => {{
        // OPTIMIZE: use Vec::with_capacity, or a fixed-size array
        // since we know the size at compile time
        let mut result = Vec::new();
        result.extend_from_slice(&$x.to_le_bytes());
        $(
            result.extend_from_slice(&$xs.to_le_bytes());
        )*
        result
    }}
}

/// Unpack a single value from a byte array. Used for unpickling.
macro_rules! unpack_one {
    ($arr:ident, $t:ty) => {{
        const SIZE: usize = std::mem::size_of::<$t>();
        let data = <$t>::from_le_bytes($arr[..SIZE].try_into().unwrap());
        #[allow(unused_assignments)]
        {
            $arr = &$arr[SIZE..];
        }
        data
    }};
}

/// A lazily-initialized Python object with GC traverse and cleanup support.
/// Uses lock-free CAS on a SwapPtr for initialization.
/// Returns `PyObj` by value (Copy) — no reference lifetime concerns.
pub(crate) struct OncePyObj {
    init: fn() -> PyReturn,
    ptr: crate::common::sync::SwapPtr<PyObject>,
}

impl OncePyObj {
    pub(crate) const fn new(init: fn() -> PyReturn) -> Self {
        Self {
            init,
            ptr: crate::common::sync::SwapPtr::new(None),
        }
    }

    #[inline]
    pub(crate) fn get(&self) -> PyResult<PyObj> {
        if let Some(p) = self.ptr.load() {
            return Ok(PyObj::wrap(p));
        }
        self.get_slow()
    }

    #[cold]
    fn get_slow(&self) -> PyResult<PyObj> {
        let owned = (self.init)()?;
        let obj = owned.py_owned();
        let ptr = obj.as_nonnull();
        match self.ptr.try_init(ptr) {
            Ok(()) => Ok(obj),
            Err(winner) => {
                // Another init beat us — DECREF ours, use theirs
                unsafe { Py_DECREF(obj.as_ptr()) };
                Ok(PyObj::wrap(winner))
            }
        }
    }

    pub(crate) fn traverse(&self, visit: visitproc, arg: *mut c_void) -> TraverseResult {
        if let Some(p) = self.ptr.load() {
            traverse(p.as_ptr(), visit, arg)?;
        }
        Ok(())
    }

    /// Clear the stored pointer, DECREFing the old value if set.
    /// Called from `module_clear` to break reference cycles.
    pub(crate) fn clear(&self) {
        if let Some(p) = self.ptr.swap(None) {
            unsafe { Py_DECREF(p.as_ptr()) };
        }
    }
}

impl Drop for OncePyObj {
    fn drop(&mut self) {
        if let Some(p) = self.ptr.swap(None) {
            unsafe { Py_DECREF(p.as_ptr()) };
        }
    }
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

#[allow(unused_imports)]
pub(crate) use {pack, unpack_one};
