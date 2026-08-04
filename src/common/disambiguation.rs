//! Python argument parsing for local-time disambiguation.
pub(crate) use crate::domain::local::Disambiguation;
use crate::{common::compat::RenamedKeyword, py::*, pymodule::State};

impl Disambiguation {
    pub(crate) fn from_only_kwarg(
        kwargs: &mut IterKwargs,
        fname: &str,
        state: &State,
    ) -> PyResult<Option<Self>> {
        let mut value = RenamedKeyword::default();
        handle_kwargs(fname, kwargs, |key, arg, eq| {
            if eq(key, *state.str_disambiguation) {
                value.set_new(arg);
            } else if eq(key, *state.str_disambiguate) {
                value.set_old(arg);
            } else {
                return Ok(false);
            }
            Ok(true)
        })?;
        value
            .finish(
                state,
                fname,
                "disambiguation",
                "disambiguate",
                c"'disambiguate' is deprecated; use 'disambiguation' instead",
                1,
            )?
            .map(|v| Self::from_py(v, state))
            .transpose()
    }

    pub(crate) fn from_py(obj: PyObj, state: &State) -> PyResult<Self> {
        match_interned_str(
            "disambiguation",
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
