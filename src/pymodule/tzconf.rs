/// Utility functions for managing tzpath and tzcache
use crate::common::pyobject::*;
use crate::pymodule::State;
use pyo3_ffi::*;
use std::path::PathBuf;

pub(crate) unsafe fn _set_tzpath(module: *mut PyObject, to: *mut PyObject) -> PyReturn {
    let state = State::for_mod_mut(module);

    if PyTuple_CheckExact(to) == 0 {
        raise_type_err("Argument must be a tuple")?;
    }
    let size = PyTuple_GET_SIZE(to);
    let mut result = Vec::with_capacity(size as _);

    for i in 0..size {
        let path = PyTuple_GET_ITEM(to, i);
        result.push(PathBuf::from(
            path.to_str()?.ok_or_type_err("Path must be a string")?,
        ))
    }
    state.tz_store.paths = result;
    Py_None().as_result()
}

pub(crate) unsafe fn _clear_tz_cache(module: *mut PyObject, _: *mut PyObject) -> PyReturn {
    let state = State::for_mod_mut(module);
    state.tz_store.clear_all();
    Py_None().as_result()
}

pub(crate) unsafe fn _clear_tz_cache_by_keys(
    module: *mut PyObject,
    keys_obj: *mut PyObject,
) -> PyReturn {
    let state = State::for_mod_mut(module);
    if PyTuple_CheckExact(keys_obj) == 0 {
        raise_type_err("Argument must be a tuple")?;
    }
    let size = PyTuple_GET_SIZE(keys_obj);
    let mut keys = Vec::with_capacity(size as _);
    for i in 0..size {
        let path = PyTuple_GET_ITEM(keys_obj, i);
        keys.push(path.to_str()?.ok_or_type_err("Path must be a string")?)
    }
    state.tz_store.clear_only(&keys);
    Py_None().as_result()
}
