//! Static storage for the C-API definition structs (`PyMethodDef`, `PyType_Slot`, …)
//! that CPython accesses through `*mut` pointers.
use core::{cell::UnsafeCell, ffi::c_void};

/// Read-only C-API definition arrays handed to CPython as `*mut` pointers.
///
/// CPython never writes to method/slot/getset definition arrays; the contents
/// may live in read-only memory, so writing through the cast pointer would be UB.
pub(crate) struct PyDefSlice<T: 'static> {
    defs: &'static [T],
}

// SAFETY: the contents are only read--by Rust and by CPython alike.
unsafe impl<T> Sync for PyDefSlice<T> {}

impl<T> PyDefSlice<T> {
    pub(crate) const fn new(defs: &'static [T]) -> Self {
        Self { defs }
    }

    pub(crate) const fn as_mut_ptr(&self) -> *mut T {
        self.defs.as_ptr().cast_mut()
    }

    /// The same pointer, typed for a `PyType_Slot.pfunc` field.
    pub(crate) const fn as_pfunc(&self) -> *mut c_void {
        self.as_mut_ptr().cast()
    }
}

/// Static storage for a single C-API definition struct.
///
/// Unlike [`PyDefSlice`], the contents *are* written by CPython:
/// `PyModuleDef_Init` fills in `PyModuleDef.m_base`.
#[repr(transparent)]
pub(crate) struct PyDefCell<T>(UnsafeCell<T>);

// SAFETY: only accessed under CPython's own synchronization (module-init
// exclusivity: module initialization and type creation).
unsafe impl<T> Sync for PyDefCell<T> {}

impl<T> PyDefCell<T> {
    pub(crate) const fn new(def: T) -> Self {
        Self(UnsafeCell::new(def))
    }

    pub(crate) const fn get(&self) -> *mut T {
        self.0.get()
    }
}
