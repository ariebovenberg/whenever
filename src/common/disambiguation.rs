//! Python argument parsing for local-time disambiguation.
pub(crate) use crate::domain::local::Disambiguation;
use crate::{py::*, pymodule::State};

impl Disambiguation {
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
                Disambiguation::Compatible
            } else if eq(v, *state.str_raise) {
                Disambiguation::Reject
            } else if eq(v, *state.str_earlier) {
                Disambiguation::Earlier
            } else if eq(v, *state.str_later) {
                Disambiguation::Later
            } else {
                None?
            })
        })
    }
}
