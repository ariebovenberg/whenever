use chrono::{self, NaiveDateTime};
use chrono::{Datelike, Timelike};
use pyo3::prelude::*;
use pyo3::sync::GILOnceCell;
use pyo3::types::PyDateTime;
use std::collections::hash_map::DefaultHasher;
use std::hash::{Hash, Hasher};

use crate::common::{PyNothing, PySome};

/// Efficient UTC-only datetime
#[pyclass(frozen, module = "whenever.utc", weakref)]
struct DateTime {
    inner: chrono::NaiveDateTime,
}

#[pymethods]
impl DateTime {
    #[new]
    fn py_new() -> PyResult<Self> {
        Err(pyo3::exceptions::PyTypeError::new_err(
            "Cannot create a DateTime directly, use static methods like `new` instead",
        ))
    }

    /// Construct a DateTime from components
    #[staticmethod]
    #[pyo3(signature = (year, month, day, hour=0, min=0, sec=0, nano=0))]
    fn new(
        py: Python,
        year: i32,
        month: u32,
        day: u32,
        hour: u32,
        min: u32,
        sec: u32,
        nano: u32,
    ) -> PyObject {
        match chrono::NaiveDate::from_ymd_opt(year, month, day)
            .and_then(|d| d.and_hms_nano_opt(hour, min, sec, nano))
        {
            Some(inner) => PySome {
                value: DateTime { inner }.into_py(py),
            }
            .into_py(py),
            None => (PyNothing {}).into_py(py),
        }
    }

    /// Parse a string in the format of ``YYYY-MM-DDTHH:MM:SS[.f]Z``
    #[staticmethod]
    fn parse(py: Python, s: &str) -> PyObject {
        match s.chars().last() {
            Some('Z') => match s[..s.len() - 1].parse::<chrono::NaiveDateTime>() {
                Ok(inner) => PySome {
                    value: DateTime { inner }.into_py(py),
                }
                .into_py(py),
                _ => (PyNothing {}).into_py(py),
            },
            _ => (PyNothing {}).into_py(py),
        }
    }

    /// Get the UNIX timestamp of this DateTime
    fn timestamp(&self) -> i64 {
        self.inner.timestamp()
    }

    /// Construct a datetime from a UNIX timestamp
    #[staticmethod]
    fn from_timestamp(py: Python, timestamp: i64) -> PyObject {
        match chrono::NaiveDateTime::from_timestamp_opt(timestamp, 0) {
            Some(inner) => PySome {
                value: DateTime { inner }.into_py(py),
            }
            .into_py(py),
            None => (PyNothing {}).into_py(py),
        }
    }

    /// Get the UNIX timestamp of this DateTime in milliseconds
    fn timestamp_millis(&self) -> i64 {
        self.inner.timestamp_millis()
    }

    /// Construct a datetime from a UNIX timestamp in milliseconds
    #[staticmethod]
    fn from_timestamp_millis(py: Python, timestamp: i64) -> PyObject {
        match chrono::NaiveDateTime::from_timestamp_opt(
            timestamp / 1000,
            ((timestamp % 1000) * 1_000_000) as u32,
        ) {
            Some(inner) => PySome {
                value: DateTime { inner }.into_py(py),
            }
            .into_py(py),
            None => (PyNothing {}).into_py(py),
        }
    }

    /// Convert this datetime to a Python :class:`datetime.datetime` object
    fn to_py<'a>(&self, py: Python<'a>) -> PyResult<&'a PyDateTime> {
        PyDateTime::new(
            py,
            self.inner.year(),
            self.inner.month() as u8,
            self.inner.day() as u8,
            self.inner.hour() as u8,
            self.inner.minute() as u8,
            self.inner.second() as u8,
            self.inner.nanosecond() / 1_000,
            None,
        )
    }

    #[getter]
    fn year(&self) -> i32 {
        self.inner.year()
    }

    #[getter]
    fn month(&self) -> u32 {
        self.inner.month()
    }

    #[getter]
    fn day(&self) -> u32 {
        self.inner.day()
    }

    #[getter]
    fn hour(&self) -> u32 {
        self.inner.hour()
    }

    #[getter]
    fn minute(&self) -> u32 {
        self.inner.minute()
    }

    #[getter]
    fn second(&self) -> u32 {
        self.inner.second()
    }

    #[getter]
    fn nanosecond(&self) -> u32 {
        self.inner.nanosecond()
    }

    fn __eq__(&self, rhs: &DateTime) -> bool {
        self.inner == rhs.inner
    }

    fn __lt__(&self, rhs: &DateTime) -> bool {
        self.inner < rhs.inner
    }

    fn __le__(&self, rhs: &DateTime) -> bool {
        self.inner <= rhs.inner
    }

    fn __gt__(&self, rhs: &DateTime) -> bool {
        self.inner > rhs.inner
    }

    fn __ge__(&self, rhs: &DateTime) -> bool {
        self.inner >= rhs.inner
    }

    fn __hash__(&self) -> u64 {
        let mut hasher = DefaultHasher::new();
        self.inner.hash(&mut hasher);
        hasher.finish()
    }

    fn __repr__(&self) -> String {
        format!("whenever.utc.DateTime({:?}Z)", self.inner)
    }

    fn __reduce__(&self, py: Python) -> PyResult<(PyObject, PyObject)> {
        Ok((
            DATETIME_UNPICKLER.get(py).unwrap().clone(),
            (
                self.inner.timestamp().to_object(py),
                self.inner.timestamp_subsec_nanos().to_object(py),
            )
                .to_object(py),
        ))
    }
}

// Because the constructor cannot be called from Python, we have a custom unpickler.
// We give it a short name in Python because it contributes to the pickled size
#[pyfunction(name = "_ud")]
fn unpickle_datetime(secs: i64, nsecs: u32) -> DateTime {
    DateTime {
        inner: NaiveDateTime::from_timestamp_opt(secs, nsecs).unwrap(),
    }
}

static DATETIME_UNPICKLER: GILOnceCell<PyObject> = GILOnceCell::new();

pub fn submodule(py: Python<'_>) -> PyResult<&PyModule> {
    let m = PyModule::new(py, "utc")?;
    m.add_class::<DateTime>()?;

    let unpickle_func = wrap_pyfunction!(unpickle_datetime, m)?;
    DATETIME_UNPICKLER.set(py, unpickle_func.into()).unwrap();
    unpickle_func.setattr("__module__", "whenever.utc")?;
    m.add_function(unpickle_func)?;

    Ok(m)
}
