use core::ffi::c_long;

use crate::{common::scalar::*, py::*};

pub(crate) fn handle_init_kwargs<T>(
    fname: &str,
    kwargs: T,
    str_years: PyObj,
    str_months: PyObj,
    str_days: PyObj,
    str_weeks: PyObj,
) -> PyResult<(DeltaMonths, DeltaDays)>
where
    T: IntoIterator<Item = (PyObj, PyObj)>,
{
    let mut days: c_long = 0;
    let mut months: c_long = 0;
    handle_kwargs(fname, kwargs, |key, value, eq| {
        if eq(key, str_days) {
            days = value
                .cast_allow_subclass::<PyInt>()
                .ok_or_type_err("days must be an integer")?
                .to_long()?
                .checked_add(days)
                .ok_or_range_err()?;
        } else if eq(key, str_months) {
            months = value
                .cast_allow_subclass::<PyInt>()
                .ok_or_type_err("months must be an integer")?
                .to_long()?
                .checked_add(months)
                .ok_or_range_err()?;
        } else if eq(key, str_years) {
            months = value
                .cast_allow_subclass::<PyInt>()
                .ok_or_type_err("years must be an integer")?
                .to_long()?
                .checked_mul(12)
                .and_then(|m| m.checked_add(months))
                .ok_or_range_err()?;
        } else if eq(key, str_weeks) {
            days = value
                .cast_allow_subclass::<PyInt>()
                .ok_or_type_err("weeks must be an integer")?
                .to_long()?
                .checked_mul(7)
                .and_then(|d| d.checked_add(days))
                .ok_or_range_err()?;
        } else {
            return Ok(false);
        }
        Ok(true)
    })?;
    Ok((
        DeltaMonths::from_long(months).ok_or_range_err()?,
        DeltaDays::from_long(days).ok_or_range_err()?,
    ))
}
