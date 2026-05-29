use crate::py::*;

#[inline]
pub(crate) fn handle_exact_unit(
    value: PyObj,
    max: u64,
    name: &str,
    factor: i128,
) -> PyResult<i128> {
    if let Some(int) = value.cast_allow_subclass::<PyInt>() {
        let i = int.to_i64()?;
        (i.unsigned_abs() <= max)
            .then(|| i as i128 * factor)
            .ok_or_range_err()
    } else if let Some(py_float) = value.cast_allow_subclass::<PyFloat>() {
        let f = py_float.to_f64()?;
        (f.abs() <= max as f64)
            .then_some((f * factor as f64) as i128)
            .ok_or_range_err()
    } else {
        raise_value_err(format!("{name} must be an integer or float"))?
    }
}
