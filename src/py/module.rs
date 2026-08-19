//! Functions for working with the module object.

use super::{base::*, exc::*, typed::*, types::*};
use crate::pymodule::State;
use core::mem::MaybeUninit;
use pyo3_ffi::*;

#[derive(Debug, Clone, Copy)]
pub(crate) struct ModuleTag;

impl TypeTag for ModuleTag {
    fn check_exact(obj: PyObj) -> bool {
        unsafe { PyModule_CheckExact(obj.as_ptr()) != 0 }
    }

    fn check(obj: PyObj) -> bool {
        unsafe { PyModule_Check(obj.as_ptr()) != 0 }
    }
}

pub(crate) type PyModule = Typed<ModuleTag>;

impl Typed<ModuleTag> {
    pub(crate) fn state(&self) -> &MaybeUninit<Option<State>> {
        // SAFETY: calling CPython API with valid arguments
        unsafe {
            PyModule_GetState(self.as_ptr())
                .cast::<MaybeUninit<Option<State>>>()
                .as_ref()
        }
        .unwrap()
    }

    /// Mutably borrow the module-state slot during a module lifecycle transition.
    ///
    /// # Safety
    /// This may only be called during module initialization or teardown, where the module
    /// state is only accessed under CPython's own synchronization (module-init exclusivity
    /// on the way in, the GC pause on the way out).
    pub(crate) unsafe fn state_mut(&mut self) -> &mut MaybeUninit<Option<State>> {
        // SAFETY: calling CPython API with valid arguments
        unsafe {
            PyModule_GetState(self.as_ptr())
                .cast::<MaybeUninit<Option<State>>>()
                .as_mut()
        }
        .unwrap()
    }

    pub(crate) fn add_type(&self, cls: PyType) -> PyResult<()> {
        // SAFETY: calling CPython API with valid arguments
        if unsafe { PyModule_AddType(self.as_ptr(), cls.as_ptr().cast()) } == 0 {
            Ok(())
        } else {
            Err(PyErrMarker)
        }
    }
}
