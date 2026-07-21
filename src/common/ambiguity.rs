//! Functionality for handling ambiguous datetime values.
use crate::{
    common::scalar::{EpochSecs, Offset},
    py::*,
    pymodule::State,
};

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
    Gap(EpochSecs, Offset, Offset), // (end, later_offset, earlier_offset)
    Fold(EpochSecs, Offset, Offset), // (end, earlier_offset, later_offset)
}

impl Disambiguate {
    pub(crate) fn from_only_kwarg(
        kwargs: &mut IterKwargs,
        fname: &str,
        state: &State,
    ) -> PyResult<Option<Self>> {
        match kwargs.next() {
            Some((name, value)) => {
                if kwargs.len() == 1 {
                    if unicode_eq(name, *state.str_disambiguate) {
                        Self::from_py(value, state).map(Some)
                    } else {
                        raise_type_err(format!(
                            "{fname}() got an unexpected keyword argument {name}"
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

    pub(crate) fn from_py(obj: PyObj, state: &State) -> PyResult<Self> {
        match_interned_str("disambiguate", obj, |v, eq| {
            Some(if eq(v, *state.str_compatible) {
                Disambiguate::Compatible
            } else if eq(v, *state.str_raise) {
                Disambiguate::Raise
            } else if eq(v, *state.str_earlier) {
                Disambiguate::Earlier
            } else if eq(v, *state.str_later) {
                Disambiguate::Later
            } else {
                None?
            })
        })
    }
}
