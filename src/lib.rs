use pyo3::prelude::*;

mod common;
mod utc;

#[pymodule]
fn _whenever(py: Python, m: &PyModule) -> PyResult<()> {
    let mod_utc = utc::submodule(py)?;
    let mod_common = common::submodule(py)?;

    m.add("utc", mod_utc)?;
    m.add("_common", mod_common)?;

    // See github.com/PyO3/pyo3/issues/759
    let sys_modules = py.import("sys")?.getattr("modules")?;
    sys_modules.set_item("whenever.utc", mod_utc)?;
    sys_modules.set_item("whenever._common", mod_common)?;
    Ok(())
}
