//! Python argument parsing for local-time disambiguation.
pub(crate) use crate::domain::local::Disambiguation;
use crate::{py::*, pymodule::State};

impl Disambiguation {
    pub(crate) fn from_only_kwarg(
        kwargs: &mut IterKwargs,
        fname: &str,
        state: &State,
    ) -> PyResult<Option<Self>> {
        handle_one_kwarg(fname, *state.str_disambiguate, kwargs)?
            .map(|v| Self::from_py(v, state))
            .transpose()
    }

    pub(crate) fn from_py(obj: PyObj, state: &State) -> PyResult<Self> {
        match_interned_str(
            "disambiguate",
            obj,
            &[
                (*state.str_compatible, Disambiguation::Compatible),
                (*state.str_raise, Disambiguation::Reject),
                (*state.str_earlier, Disambiguation::Earlier),
                (*state.str_later, Disambiguation::Later),
            ],
        )
    }
}
