//! Miscellaneous utilities for the `whenever` module definition.
use crate::py::*;
use pyo3_ffi::*;
use std::{ffi::CStr, ptr::null_mut as NULL};

/// Create and add a new exception type to the module
pub(crate) fn new_exception(
    module: PyModule,
    name: &CStr,
    doc: &CStr,
    base: PyObj,
) -> PyResult<Owned<PyObj>> {
    // SAFETY: calling C API with valid arguments
    let e =
        unsafe { PyErr_NewExceptionWithDoc(name.as_ptr(), doc.as_ptr(), base.as_ptr(), NULL()) }
            .own()?;
    module.add_type((*e).cast_allow_subclass::<PyType>().unwrap())?;
    Ok(e)
}

/// Create a new class in the module, including configuring the
/// unpickler and setting the module name
pub(crate) fn new_class<T: PyWrapped>(
    module: PyModule,
    module_nameobj: PyObj,
    spec: &mut PyType_Spec,
    unpickle_name: &CStr,
) -> PyResult<(Owned<HeapType<T>>, Owned<PyObj>)> {
    let cls = unsafe { PyType_FromModuleAndSpec(module.as_ptr(), spec, NULL()) }
        .own()?
        .cast_allow_subclass::<PyType>()
        .unwrap()
        .map(|t| unsafe { t.link_type::<T>() });
    module.add_type((*cls).into())?;

    let unpickler = module.getattr(unpickle_name)?;
    unpickler.setattr(c"__module__", module_nameobj)?;
    Ok((cls, unpickler))
}

pub(crate) fn create_singletons<T: PySimpleAlloc>(
    cls: HeapType<T>,
    objs: &[(&CStr, T)],
) -> PyResult<()> {
    let cls_dict = cls.inner().get_dict();
    for (name, value) in objs {
        let pyvalue = value.to_obj(cls)?;
        cls_dict
            // NOTE: We drop the value here, but count on the class dict to
            // keep the reference alive. This is safe since the dict is blocked
            // from mutation by the Py_TPFLAGS_IMMUTABLETYPE flag.
            .set_item_str(name, *pyvalue)?;
    }
    Ok(())
}

/// Intern a string in the Python interpreter
pub(crate) fn intern(s: &CStr) -> PyReturn {
    unsafe { PyUnicode_InternFromString(s.as_ptr()) }.own()
}
