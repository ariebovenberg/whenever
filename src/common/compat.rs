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
    let unreliable = matches!(
        (package, base),
        ("pandas", "datetime") | ("pandas", "timedelta") | ("pendulum", "timedelta")
    ) || (base == "date" && PyDateTime::isinstance(obj));
    if !unreliable {
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

    /// The value, and whether it came by the deprecated name. The caller
    /// warns once its call has succeeded: a call that raises emits no warning.
    pub(crate) fn finish(
        self,
        function_name: &str,
        new_name: &str,
        old_name: &str,
    ) -> PyResult<(Option<PyObj>, bool)> {
        match (self.new, self.old) {
            (Some(_), Some(_)) => raise_type_err(format!(
                "{function_name}() received both '{new_name}' and deprecated '{old_name}'"
            )),
            (Some(value), None) => Ok((Some(value), false)),
            (None, Some(value)) => Ok((Some(value), true)),
            (None, None) => Ok((None, false)),
        }
    }
}

pub(crate) const FORMAT_KEYWORD_WARNING: &CStr = c"'format' is deprecated; use 'pattern' instead";

/// The pattern, and whether it came as `format=`: the caller parses, then
/// warns with `FORMAT_KEYWORD_WARNING`.
pub(crate) fn parse_pattern_keyword(
    kwargs: &mut IterKwargs,
    state: &State,
) -> PyResult<(PyObj, bool)> {
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
    let (value, renamed) = value.finish("parse", "pattern", "format")?;
    Ok((
        value.ok_or_type_err("parse() missing 1 required keyword-only argument: 'pattern'")?,
        renamed,
    ))
}
