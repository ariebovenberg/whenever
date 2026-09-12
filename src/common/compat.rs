use core::ffi::CStr;

use crate::{py::*, pymodule::State};

pub(crate) fn warn_deprecated(state: &State, message: &CStr, stacklevel: isize) -> PyResult<()> {
    warn_with_class(*state.warn_deprecation, message, stacklevel)
}

/// Warn when a stdlib subclass known to carry more than the stdlib fields
/// (`base` names the stdlib type) is read through those fields: the pandas
/// and pendulum families, and a `datetime` read as a `date`. An exact
/// stdlib instance returns at once; the module check is allowed to be imperfect.
pub(crate) fn warn_lossy_stdlib_subclass<T: PyStaticType>(
    state: &State,
    obj: PyObj,
    base: &str,
) -> PyResult<()> {
    if obj.cast_exact::<T>().is_some() {
        return Ok(());
    }
    let cls = obj.type_();
    let module = cls.getattr(c"__module__")?;
    let Ok(module) = module.cast_allow_subclass::<PyStr>() else {
        return Ok(());
    };
    let package = module.as_str()?.split('.').next().unwrap_or("");
    if !matches!(
        (package, base),
        ("pandas", "datetime") | ("pandas", "timedelta") | ("pendulum", "timedelta")
    ) && !(base == "date" && PyDateTime::isinstance(obj))
    {
        return Ok(());
    }
    let qualname = cls.getattr(c"__qualname__")?;
    let Ok(qualname) = qualname.cast_allow_subclass::<PyStr>() else {
        return Ok(());
    };
    let message = format!(
        "{package}.{} contains data that cannot be reliably read through the datetime.{base} fields; convert it explicitly",
        qualname.as_str()?,
    )
    .to_py()?;
    warn_with_class_obj(*state.warn_whenever, *message, 1)
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
        if eq(k, *state.strs.pattern) {
            value.set_new(v);
        } else if eq(k, *state.strs.format) {
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
        .ok_or_type_err("parse() missing 1 required keyword-only argument: 'pattern'")
}
