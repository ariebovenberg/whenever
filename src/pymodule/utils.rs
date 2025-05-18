use crate::py::*;
use pyo3_ffi::*;
use std::{ffi::CStr, ptr::null_mut as NULL};

/// Create and add a new enum type to the module
pub(crate) fn new_enum(
    module: PyModule,
    module_name: PyObj,
    name: &str,
    members: &[(&CStr, i32)],
) -> PyResult<Owned<PyType>> {
    let members_dict = PyDict::new()?;
    for &(key, value) in members {
        members_dict.set_item_str(key, value.to_py2()?.borrow())?;
    }
    let enum_module = import(c"enum")?;
    let enum_cls = enum_module
        .getattr(c"Enum")?
        .call((name.to_py2()?, members_dict).into_pytuple()?.borrow())?
        .cast_allow_subclass::<PyType>()
        .unwrap();

    enum_cls.setattr(c"__module__", module_name)?;

    module.add_type(enum_cls.borrow())?;
    Ok(enum_cls)
}

/// Create and add a new exception type to the module
pub(crate) fn new_exception(
    module: PyModule,
    name: &CStr,
    doc: &CStr,
    base: *mut PyObject,
) -> PyResult<Owned<PyObj>> {
    // SAFETY: calling C API with valid arguments
    let e = unsafe { PyErr_NewExceptionWithDoc(name.as_ptr(), doc.as_ptr(), base, NULL()) }
        .rust_owned()?;
    module.add_type(e.borrow().cast::<PyType>().unwrap())?;
    Ok(e)
}

/// Create a new class in the module, including configuring the
/// unpickler and setting the module name
pub(crate) fn new_class<T: PyWrapped>(
    module: PyModule,
    module_nameobj: PyObj,
    spec: *mut PyType_Spec,
    unpickle_name: &CStr,
    singletons: &[(&CStr, T)],
    unpickle_ref: &mut PyObj,
) -> PyResult<Owned<HeapType<T>>> {
    let cls = unsafe { PyType_FromModuleAndSpec(module.as_ptr(), spec, NULL()) }
        .rust_owned()?
        .cast_allow_subclass::<PyType>()
        .unwrap()
        .map(|t| unsafe { t.link_type::<T>() });
    module.add_type(cls.borrow().into())?;

    // SAFETY: each type is guaranteed to have tp_dict
    let cls_dict =
        unsafe { PyDict::from_ptr_unchecked((*cls.as_ptr().cast::<PyTypeObject>()).tp_dict) };
    for (name, value) in singletons {
        let pyvalue = value.to_obj3(cls.borrow())?;
        cls_dict
            // NOTE: We drop the value here, but count on the class dict to
            // keep the reference alive. This is safe since the dict is blocked
            // from mutation by the Py_TPFLAGS_IMMUTABLETYPE flag.
            .set_item_str(name, pyvalue.borrow())?;
    }

    let unpickler = module.getattr(unpickle_name)?;
    unpickler.setattr(c"__module__", module_nameobj)?;
    *unpickle_ref = unpickler.into_py();
    Ok(cls)
}

/// Intern a string in the Python interpreter
pub(crate) fn intern(s: &CStr) -> PyReturn {
    unsafe { PyUnicode_InternFromString(s.as_ptr()) }.rust_owned()
}
