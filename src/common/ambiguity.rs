use crate::common::{math::Offset, pyobject::*, pytype::*};
use pyo3_ffi::*;

#[derive(Debug, Copy, Clone, PartialEq, Eq)]
pub(crate) enum Disambiguate {
    Compatible,
    Earlier,
    Later,
    Raise,
}

#[derive(Debug, Copy, Clone, PartialEq, Eq)]
pub enum Ambiguity {
    Unambiguous(Offset),
    Gap(Offset, Offset),  // (earlier, later) occurrence, (a > b)
    Fold(Offset, Offset), // (earlier, later) occurrence, (a > b)
}

impl Disambiguate {
    pub(crate) unsafe fn from_py(
        obj: *mut PyObject,
        str_compatible: *mut PyObject,
        str_raise: *mut PyObject,
        str_earlier: *mut PyObject,
        str_later: *mut PyObject,
    ) -> PyResult<Self> {
        match_interned_str("disambiguate", obj, |v, eq| {
            Some(if eq(v, str_compatible) {
                Disambiguate::Compatible
            } else if eq(v, str_raise) {
                Disambiguate::Raise
            } else if eq(v, str_earlier) {
                Disambiguate::Earlier
            } else if eq(v, str_later) {
                Disambiguate::Later
            } else {
                None?
            })
        })
    }

    pub(crate) unsafe fn from_only_kwarg(
        kwargs: &mut KwargIter,
        str_disambiguate: *mut PyObject,
        fname: &str,
        str_compatible: *mut PyObject,
        str_raise: *mut PyObject,
        str_earlier: *mut PyObject,
        str_later: *mut PyObject,
    ) -> PyResult<Option<Self>> {
        match kwargs.next() {
            Some((name, value)) => {
                if kwargs.len() == 1 {
                    if name.py_eq(str_disambiguate)? {
                        Self::from_py(value, str_compatible, str_raise, str_earlier, str_later)
                            .map(Some)
                    } else {
                        raise_type_err(format!(
                            "{}() got an unexpected keyword argument {}",
                            fname,
                            name.repr()
                        ))
                    }
                } else {
                    raise_type_err(format!(
                        "{}() takes at most 1 keyword argument, got {}",
                        fname,
                        kwargs.len()
                    ))
                }
            }
            None => Ok(None),
        }
    }
}
