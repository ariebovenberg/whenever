//! Functionality related to Python type objects
use super::{base::*, dict::PyDict, exc::*, module::*, refs::*};
use crate::pymodule::State;
use core::{
    ffi::CStr,
    mem::{self, MaybeUninit},
};
use pyo3_ffi::*;

/// Wrapper around PyTypeObject.
#[repr(transparent)]
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub(crate) struct PyType {
    obj: PyObj,
}

impl PyBase for PyType {
    fn as_py_obj(&self) -> PyObj {
        self.obj
    }
}

impl FromPy for PyType {
    unsafe fn from_ptr_unchecked(ptr: *mut PyObject) -> Self {
        Self {
            obj: unsafe { PyObj::from_ptr_unchecked(ptr.cast()) },
        }
    }
}

impl PyStaticType for PyType {
    fn isinstance_exact(obj: impl PyBase) -> bool {
        unsafe { PyType_CheckExact(obj.as_ptr()) != 0 }
    }
    fn isinstance(obj: impl PyBase) -> bool {
        unsafe { PyType_Check(obj.as_ptr()) != 0 }
    }
}

impl PyType {
    /// Get the Python module this type belongs to, if any.
    /// Returns `None` (and clears the exception) for types not belonging to a module.
    pub(crate) fn get_module(&self) -> Option<PyModule> {
        Some(unsafe {
            PyType_GetModule(self.as_ptr().cast())
                .borrow()
                .or_clear()?
                .cast_unchecked::<PyModule>()
        })
    }

    /// Get the `__dict__` of this type.
    pub(crate) fn get_dict(self) -> PyDict {
        // SAFETY: type objects always have tp_dict populated
        unsafe { PyDict::from_ptr_unchecked((*self.as_ptr().cast::<PyTypeObject>()).tp_dict) }
    }

    /// Get the module state if both types are from the whenever module.
    pub(crate) fn same_module(&self, other: PyType) -> Option<&State> {
        let mod_a = self.get_module()?;
        mod_a.is(other.get_module()?).then(|| {
            // SAFETY: we only use this function after module initialization
            unsafe { mod_a.state().assume_init_ref() }
                .as_ref()
                .expect("Module state should be initialized")
        })
    }

    /// Associate the type with the given Rust type.
    pub(crate) unsafe fn link_type<T: PyWrapped>(self) -> HeapType<T> {
        // SAFETY: we assume the pointer is valid and points to a PyType object
        unsafe { HeapType::from_ptr_unchecked(self.as_ptr()) }
    }
}

impl std::fmt::Display for PyType {
    fn fmt(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        self.write_repr(f)
    }
}

/// A PyTypeObject that is linked to a Rust struct in whenever.
/// `#[repr(transparent)]` so that `*mut HeapType<T>` can be cast to
/// `*mut *mut PyObject` in `module_clear` (same as PyType → PyObj chain).
#[repr(transparent)]
#[derive(Debug, PartialEq, Eq)]
pub(crate) struct HeapType<T: PyWrapped> {
    type_py: PyType,
    type_rust: std::marker::PhantomData<T>,
}

// HeapType is always Copy/Clone: it's just a pointer + PhantomData marker.
impl<T: PyWrapped> Copy for HeapType<T> {}
impl<T: PyWrapped> Clone for HeapType<T> {
    fn clone(&self) -> Self {
        *self
    }
}

impl<T: PyWrapped> HeapType<T> {
    /// Get the module state
    pub(crate) fn state<'a>(&self) -> &'a State {
        // SAFETY: the type pointer is valid, and the retrieved module
        // state is valid once the Python module is initialized.
        unsafe {
            PyType_GetModuleState(self.type_py.as_ptr().cast())
                .cast::<MaybeUninit<Option<State>>>()
                .as_ref()
                .unwrap()
                .assume_init_ref()
                .as_ref()
                .unwrap()
        }
    }

    pub(crate) fn inner(&self) -> PyType {
        self.type_py
    }
}

impl<T: PyWrapped> PyBase for HeapType<T> {
    fn as_py_obj(&self) -> PyObj {
        self.type_py.as_py_obj()
    }
}

impl<T: PyWrapped> FromPy for HeapType<T> {
    unsafe fn from_ptr_unchecked(ptr: *mut PyObject) -> Self {
        Self {
            type_py: unsafe { PyType::from_ptr_unchecked(ptr) },
            type_rust: std::marker::PhantomData,
        }
    }
}

impl<T: PyWrapped> From<HeapType<T>> for PyType {
    fn from(t: HeapType<T>) -> Self {
        t.type_py
    }
}

/// A trait for Rust structs that can be embedded in a Python heap object.
pub(crate) trait PyWrapped: Sized {
    /// Allocate a new Python object wrapping this data.
    #[inline]
    fn to_obj(self, type_: HeapType<Self>) -> PyReturn {
        generic_alloc(type_.into(), self)
    }
}

/// A reference to the Rust data embedded in a Python object, together with
/// the containing PyObj. This enables both safe value extraction (for Copy types)
/// and safe identity-preserving returns (via `.newref()`).
///
/// The method dispatch macros create this and pass it through `FromWrapped`,
/// which the Rust compiler resolves based on what the function expects:
/// - `T` (Copy types): extracts the value
/// - `&T`: extracts the reference
/// - `Wrapped<T>`: passes the full wrapper (for `__abs__` etc.)
pub(crate) struct Wrapped<'a, T: PyWrapped> {
    obj: PyObj,
    data: &'a T,
}

impl<'a, T: PyWrapped> Wrapped<'a, T> {
    #[inline]
    pub(crate) unsafe fn new(obj: PyObj, data: &'a T) -> Self {
        Self { obj, data }
    }

    /// Return a new Python reference to the containing object.
    #[inline]
    pub(crate) fn newref(&self) -> Owned<PyObj> {
        self.obj.newref()
    }
}

impl<T: PyWrapped> std::ops::Deref for Wrapped<'_, T> {
    type Target = T;
    #[inline]
    fn deref(&self) -> &T {
        self.data
    }
}

/// Trait for automatic conversion from `Wrapped<T>` to the type expected
/// by a method function. Resolved by the compiler at each call site.
pub(crate) trait FromWrapped<'a, T: PyWrapped>: Sized {
    fn from_wrapped(w: Wrapped<'a, T>) -> Self;
}

/// Copy types: extract the value.
impl<T: PyWrapped + Copy> FromWrapped<'_, T> for T {
    #[inline]
    fn from_wrapped(w: Wrapped<'_, T>) -> T {
        *w.data
    }
}

/// Reference access: extract `&T`.
impl<'a, T: PyWrapped> FromWrapped<'a, T> for &'a T {
    #[inline]
    fn from_wrapped(w: Wrapped<'a, T>) -> &'a T {
        w.data
    }
}

/// Pass-through: keep the full wrapper.
impl<'a, T: PyWrapped> FromWrapped<'a, T> for Wrapped<'a, T> {
    #[inline]
    fn from_wrapped(w: Wrapped<'a, T>) -> Self {
        w
    }
}

/// The shape of PyObjects that wrap a `whenever` Rust type.
#[repr(C)]
pub(crate) struct PyWrap<T: PyWrapped> {
    _ob_base: PyObject,
    pub(crate) data: T,
}

pub(crate) const fn type_spec<T: PyWrapped>(
    name: &CStr,
    slots: &'static [PyType_Slot],
) -> PyType_Spec {
    PyType_Spec {
        name: name.as_ptr().cast(),
        basicsize: mem::size_of::<PyWrap<T>>() as _,
        itemsize: 0,
        // NOTE: IMMUTABLETYPE flag is required to prevent additional refcycles
        // between the class and the instance.
        // This allows us to keep our types GC-free.
        flags: (Py_TPFLAGS_DEFAULT | Py_TPFLAGS_IMMUTABLETYPE) as _,
        slots: slots.as_ptr().cast_mut(),
    }
}

pub(crate) extern "C" fn generic_dealloc(slf: PyObj) {
    let cls = slf.type_().as_ptr().cast::<PyTypeObject>();
    unsafe {
        let tp_free = PyType_GetSlot(cls, Py_tp_free);
        debug_assert_ne!(tp_free, core::ptr::null_mut());
        let tp_free: freefunc = std::mem::transmute(tp_free);
        tp_free(slf.as_ptr().cast());
        Py_DECREF(cls.cast());
    }
}

#[inline]
pub(crate) fn generic_alloc<T: PyWrapped>(type_: PyType, d: T) -> PyReturn {
    let type_ptr = type_.as_ptr().cast::<PyTypeObject>();
    unsafe {
        let slf = (*type_ptr).tp_alloc.unwrap()(type_ptr, 0).cast::<PyWrap<T>>();
        match slf.cast::<PyObject>().as_mut() {
            Some(r) => {
                (&raw mut (*slf).data).write(d);
                Ok(Owned::new(PyObj::from_ptr_unchecked(r)))
            }
            None => Err(PyErrMarker),
        }
    }
}
