use crate::common::{pyobject::*, pytype::*};
use pyo3_ffi::*;
use std::ffi::CStr;
use std::ptr::null_mut as NULL;

/// Create and add a new enum type to the module
pub(crate) fn new_enum(
    module: PyObj,
    name: &str,
    members: &[(&CStr, i32)],
) -> PyResult<Owned<PyType>> {
    let members_dict = PyDict::new()?;
    for &(key, value) in members {
        members_dict.set_item_str(key, value.to_py2()?.borrow())?;
    }
    let enum_module = import(c"enum")?;
    // TODO: set __module__ on the enum class
    let enum_cls = enum_module
        .getattr(c"Enum")?
        .call((name.to_py2()?, members_dict).into_pytuple()?.borrow())?
        .cast_allow_subclass::<PyType>()
        .unwrap();

    add_type_to_module(module, enum_cls.borrow())?;
    Ok(enum_cls)
}

pub(crate) fn add_type_to_module(module: PyObj, cls: PyType) -> PyResult<()> {
    // TODO double-check refcount story
    // SAFETY: calling C API with valid arguments
    if unsafe { PyModule_AddType(module.as_ptr(), cls.as_ptr().cast()) } == 0 {
        Ok(())
    } else {
        Err(PyErrOccurred())
    }
}

/// Create and add a new exception type to the module
pub(crate) unsafe fn new_exception(
    module: *mut PyObject,
    name: &CStr,
    doc: &CStr,
    base: *mut PyObject,
) -> PyResult<PyObj> {
    let e = PyErr_NewExceptionWithDoc(name.as_ptr(), doc.as_ptr(), base, NULL()).as_result()?;
    if PyModule_AddType(module, (e as *mut PyObject).cast()) == 0 {
        // TODO: are references in order?
        Ok(PyObj::from_ptr_unchecked(e))
    } else {
        defer_decref!(e);
        Err(PyErrOccurred())
    }
}

/// Create a new class in the module, including configuring the
/// unpickler and setting the module name
pub(crate) unsafe fn new_class<T: PyWrapped>(
    module: *mut PyObject,
    module_nameobj: *mut PyObject,
    spec: *mut PyType_Spec,
    unpickle_name: &CStr,
    singletons: &[(&CStr, T)],
    dest: &mut HeapType<T>,
    unpickle_ref: &mut PyObj,
) -> PyResult<()> {
    // TODO: nicer way to track decref of cls?
    let cls: *mut PyTypeObject = PyType_FromModuleAndSpec(module, spec, NULL()).cast();
    if cls.is_null() || PyModule_AddType(module, cls) != 0 {
        defer_decref!(cls.cast());
        return Err(PyErrOccurred());
    }

    let unpickler = PyObject_GetAttrString(module, unpickle_name.as_ptr()).as_result()?;
    defer_decref!(unpickler);
    if PyObject_SetAttrString(unpickler, c"__module__".as_ptr(), module_nameobj) != 0 {
        defer_decref!(cls.cast());
        Err(PyErrOccurred())?;
    }

    for (name, value) in singletons {
        let pyvalue = value.to_obj(cls)?;
        defer_decref!(pyvalue);
        if PyDict_SetItemString((*cls).tp_dict, name.as_ptr(), pyvalue) != 0 {
            defer_decref!(cls.cast());
            Err(PyErrOccurred())?;
        }
    }
    *dest = HeapType::from_ptr_unchecked(cls.cast());
    *unpickle_ref = PyObj::from_ptr_unchecked(unpickler);
    Ok(())
}

// Sets __module__ on <module>.<attrname> to <module_name>
pub(crate) unsafe fn patch_dunder_module(
    module: *mut PyObject,
    module_name: *mut PyObject,
    attrname: &CStr,
) -> PyResult<()> {
    let obj = PyObject_GetAttrString(module, attrname.as_ptr()).as_result()?;
    defer_decref!(obj);
    if PyObject_SetAttrString(module, c"__module__".as_ptr(), module_name) == 0 {
        Ok(())
    } else {
        Err(PyErrOccurred())
    }
}

/// Intern a string in the Python interpreter
pub(crate) unsafe fn intern(s: &CStr) -> PyAny {
    let ptr = PyUnicode_InternFromString(s.as_ptr());
    if ptr.is_null() {
        Err(PyErrOccurred())
    } else {
        // TODO: from ptr checked
        Ok(PyObj::from_ptr_unchecked(ptr))
    }
}
