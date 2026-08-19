//! Python argument parsing for local-time disambiguation.
pub(crate) use crate::domain::local::Disambiguation;
use crate::{common::compat::RenamedKeyword, py::*, pymodule::State};

#[derive(Default)]
pub(crate) struct DisambiguationArg(RenamedKeyword);

impl DisambiguationArg {
    pub(crate) fn set_new(&mut self, v: PyObj) {
        self.0.set_new(v);
    }

    pub(crate) fn set_old(&mut self, v: PyObj) {
        self.0.set_old(v);
    }

    pub(crate) fn handle_kwarg(&mut self, k: PyObj, v: PyObj, eq: StrEqFn, state: &State) -> bool {
        if eq(k, *state.strs.disambiguation) {
            self.set_new(v);
        } else if eq(k, *state.strs.disambiguate) {
            self.set_old(v);
        } else {
            return false;
        }
        true
    }

    pub(crate) fn finish(self, fname: &str, state: &State) -> PyResult<Option<Disambiguation>> {
        self.0
            .finish(
                state,
                fname,
                "disambiguation",
                "disambiguate",
                c"'disambiguate' is deprecated; use 'disambiguation' instead",
                1,
            )?
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
        let mut arg = DisambiguationArg::default();
        handle_kwargs(fname, kwargs, |k, v, eq| {
            Ok(arg.handle_kwarg(k, v, eq, state))
        })?;
        arg.finish(fname, state)
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
