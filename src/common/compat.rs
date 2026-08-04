use core::ffi::CStr;

use crate::{py::*, pymodule::State};

pub(crate) fn warn_deprecated(state: &State, message: &CStr, stacklevel: isize) -> PyResult<()> {
    warn_with_class(*state.warn_deprecation, message, stacklevel)
}

#[derive(Default)]
pub(crate) struct RenamedKeyword {
    new: Option<PyObj>,
    old: Option<PyObj>,
}

impl RenamedKeyword {
    pub(crate) fn set_new(&mut self, value: PyObj) {
        self.new = Some(value);
    }

    pub(crate) fn set_old(&mut self, value: PyObj) {
        self.old = Some(value);
    }

    pub(crate) fn finish(
        self,
        state: &State,
        function_name: &str,
        new_name: &str,
        old_name: &str,
        warning: &CStr,
        stacklevel: isize,
    ) -> PyResult<Option<PyObj>> {
        match (self.new, self.old) {
            (Some(_), Some(_)) => raise_type_err(format!(
                "{function_name}() received both '{new_name}' and deprecated '{old_name}'"
            )),
            (Some(value), None) => Ok(Some(value)),
            (None, Some(value)) => {
                warn_deprecated(state, warning, stacklevel)?;
                Ok(Some(value))
            }
            (None, None) => Ok(None),
        }
    }
}

pub(crate) fn parse_pattern_keyword(kwargs: &mut IterKwargs, state: &State) -> PyResult<PyObj> {
    let mut value = RenamedKeyword::default();
    handle_kwargs("parse", kwargs, |k, v, eq| {
        if eq(k, *state.str_pattern) {
            value.set_new(v);
        } else if eq(k, *state.str_format) {
            value.set_old(v);
        } else {
            return Ok(false);
        }
        Ok(true)
    })?;
    value
        .finish(
            state,
            "parse",
            "pattern",
            "format",
            c"'format' is deprecated; use 'pattern' instead",
            1,
        )?
        .ok_or_type_err("parse() missing required keyword argument 'pattern'")
}
