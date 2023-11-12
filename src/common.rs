use pyo3::types::{PyAny, PyTuple, PyType};
use pyo3::{intern, prelude::*};

#[pyclass(frozen, name = "Some", module = "whenever")]
pub struct PySome {
    #[pyo3(get)]
    pub value: PyObject,
}

#[pymethods]
impl PySome {
    #[new]
    fn new(value: PyObject) -> Self {
        PySome { value }
    }

    fn unwrap(&self, py: Python) -> PyResult<PyObject> {
        Ok(self.value.clone_ref(py))
    }

    pub fn __repr__(&self, py: Python) -> PyResult<String> {
        Ok(format!("Some({})", self.value.as_ref(py).repr()?,))
    }

    fn __eq__(&self, py: Python, rhs: &PySome) -> PyResult<bool> {
        self.value.as_ref(py).eq(&rhs.value)
    }

    fn __hash__(&self, py: Python) -> PyResult<isize> {
        self.value.as_ref(py).hash()
    }

    #[classmethod]
    pub fn __class_getitem__(cls: &PyType, py: Python, _item: &PyAny) -> Py<PyType> {
        cls.into_py(py)
    }

    #[classattr]
    fn __match_args__(py: Python) -> &PyTuple {
        PyTuple::new(py, vec![intern!(py, "value")])
    }
}

#[pyclass(frozen, name = "Nothing", module = "whenever")]
pub struct PyNothing;

#[pymethods]
impl PyNothing {
    #[new]
    fn new() -> Self {
        // TODO: singleton?
        PyNothing {}
    }

    fn unwrap(&self) -> PyResult<PyObject> {
        Err(pyo3::exceptions::PyValueError::new_err(
            "called `unwrap` on a `Nothing` value",
        ))
    }

    fn __eq__(&self, _rhs: &PyNothing) -> bool {
        true
    }

    fn __hash__(&self) -> u64 {
        0
    }

    fn __bool__(&self) -> bool {
        false
    }

    pub fn __repr__(&self) -> &'static str {
        "whenever.Nothing()"
    }

    #[classmethod]
    pub fn __class_getitem__(cls: &PyType, py: Python, _item: &PyAny) -> Py<PyType> {
        cls.into_py(py)
    }
}

pub fn submodule(py: Python) -> PyResult<&PyModule> {
    let m = PyModule::new(py, "_common")?;
    m.add("_NOTHING", (PyNothing {}).into_py(py))?;
    m.add_class::<PySome>()?;
    m.add_class::<PyNothing>()?;
    Ok(m)
}
