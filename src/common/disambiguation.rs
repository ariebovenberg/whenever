//! Python argument parsing for local-time disambiguation.
pub(crate) use crate::domain::local::Disambiguation;
use crate::{py::*, pymodule::State};

#[derive(Default)]
pub(crate) struct DisambiguationArg(Option<PyObj>);

impl DisambiguationArg {
    pub(crate) fn handle_kwarg(&mut self, k: PyObj, v: PyObj, eq: StrEqFn, state: &State) -> bool {
        if eq(k, *state.strs.disambiguation) {
            self.0 = Some(v);
            true
        } else {
            false
        }
    }

    pub(crate) fn finish(self, state: &State) -> PyResult<Option<Disambiguation>> {
        self.0
            .map(|v| Disambiguation::from_py(v, state))
            .transpose()
    }
}

impl Disambiguation {
    pub(crate) fn from_only_kwarg(
        kwargs: &mut IterKwargs,
        fname: &str,
        state: &State,
    ) -> PyResult<Option<Self>> {
        handle_one_kwarg(fname, *state.strs.disambiguation, kwargs)?
            .map(|v| Disambiguation::from_py(v, state))
            .transpose()
    }

    pub(crate) fn from_py(obj: PyObj, state: &State) -> PyResult<Self> {
        match_interned_str(
            "disambiguation",
            obj,
            &[
                (*state.strs.compatible, Disambiguation::Compatible),
                (*state.strs.raise, Disambiguation::Reject),
                (*state.strs.earlier, Disambiguation::Earlier),
                (*state.strs.later, Disambiguation::Later),
            ],
        )
    }
}
