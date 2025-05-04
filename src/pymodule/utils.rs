use crate::common::{pyobject::*, pytype::*};
use pyo3_ffi::*;
use std::ffi::CStr;
use std::ptr::null_mut as NULL;

/// Create and add a new enum type to the module
pub(crate) unsafe fn new_enum(
    module: *mut PyObject,
    name: &CStr,
    members: &[(&CStr, i32)],
) -> PyReturn {
    let members_dict = PyDict_New().as_result()?;
    defer_decref!(members_dict);
    for &(key, value) in members {
        if PyDict_SetItemString(members_dict, key.as_ptr(), steal!(value.to_py()?)) == -1 {
            return Err(PyErrOccurred());
        }
    }
    let enum_module = PyImport_ImportModule(c"enum".as_ptr()).as_result()?;
    defer_decref!(enum_module);
    let enum_cls = PyObject_CallMethod(
        enum_module,
        c"Enum".as_ptr(),
        c"sO".as_ptr(),
        name.as_ptr(),
        members_dict,
    )
    .as_result()?;
    if PyModule_AddType(module, (enum_cls as *mut PyObject).cast()) == 0 {
        Ok(enum_cls)
    } else {
        defer_decref!(enum_cls);
        Err(PyErrOccurred())
    }
}

/// Create and add a new exception type to the module
pub(crate) unsafe fn new_exception(
    module: *mut PyObject,
    name: &CStr,
    doc: &CStr,
    base: *mut PyObject,
) -> PyReturn {
    let e = PyErr_NewExceptionWithDoc(name.as_ptr(), doc.as_ptr(), base, NULL()).as_result()?;
    if PyModule_AddType(module, (e as *mut PyObject).cast()) == 0 {
        Ok(e)
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
    dest: &mut *mut PyTypeObject,
    unpickle_ptr: &mut *mut PyObject,
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
    *dest = cls;
    *unpickle_ptr = unpickler;
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
pub(crate) unsafe fn intern(s: &CStr) -> PyReturn {
    PyUnicode_InternFromString(s.as_ptr()).as_result()
}
