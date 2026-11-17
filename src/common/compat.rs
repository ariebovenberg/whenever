use crate::{py::*, pymodule::State};

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
