use pyo3::prelude::*;

#[pymodule]
#[pyo3(name = "_whenever")]
fn whenever(_py: Python, _m: &PyModule) -> PyResult<()> {
    Ok(())
}
