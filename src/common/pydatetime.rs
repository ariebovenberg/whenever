use pyo3_ffi::*;

use crate::common::{math::*, pyobject::*};

pub(crate) unsafe fn offset_from_py_dt(dt: *mut PyObject) -> PyResult<Offset> {
    let delta = methcall0(dt, "utcoffset")?;
    defer_decref!(delta);
    if is_none(delta) {
        // This case is rare, but possible even with aware datetimes
        raise_value_err("utcoffset() returned None")?
    }
    if PyDateTime_DELTA_GET_MICROSECONDS(delta) != 0 {
        raise_value_err("Sub-second offsets are not supported")?
    }
    // Unchecked: Python offsets are already bounded to +/- 24 hours
    Ok(Offset::new_unchecked(
        PyDateTime_DELTA_GET_DAYS(delta) * 86_400 + PyDateTime_DELTA_GET_SECONDS(delta),
    ))
}

// TODO method?
pub(crate) fn offset_from_py_delta_unchecked(delta: PyTimeDelta) -> PyResult<Offset> {
    if delta.microseconds() != 0 {
        raise_value_err("Sub-second offsets are not supported")?
    }
    // Unchecked: Python offsets are already bounded to +/- 24 hours
    Ok(Offset::new_unchecked(
        delta.days() * 86_400 + delta.seconds(),
    ))
}

#[inline]
#[allow(dead_code)] // only used in <py310
unsafe fn getattr_tzinfo_unchecked(dt: *mut PyObject) -> *mut PyObject {
    let tzinfo = PyObject_GetAttrString(dt, c"tzinfo".as_ptr());
    // To keep things consistent with the Py3.10 version,
    // we need to decref it, turning it into a borrowed reference.
    // We can assume the parent datetime keeps it alive.
    Py_DECREF(tzinfo);
    tzinfo
}

#[inline]
pub(crate) unsafe fn borrow_dt_tzinfo(dt: *mut PyObject) -> *mut PyObject {
    #[cfg(Py_3_10)]
    {
        PyDateTime_DATE_GET_TZINFO(dt)
    }
    #[cfg(not(Py_3_10))]
    {
        getattr_tzinfo_unchecked(dt)
    }
}
