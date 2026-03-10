//! Functions for handling arguments and keyword arguments in Python
use crate::py::*;
use pyo3_ffi::*;

pub(crate) struct IterKwargs {
    keys: *mut PyObject,
    values: *const *mut PyObject,
    size: isize,
    pos: isize,
}

impl IterKwargs {
    pub(crate) unsafe fn new(keys: *mut PyObject, values: *const *mut PyObject) -> Self {
        Self {
            keys,
            values,
            size: if keys.is_null() {
                0
            } else {
                // SAFETY: calling C API with valid arguments
                unsafe { PyTuple_GET_SIZE(keys) as isize }
            },
            pos: 0,
        }
    }

    pub(crate) fn len(&self) -> isize {
        self.size
    }
}

impl Iterator for IterKwargs {
    type Item = (PyObj, PyObj);

    fn next(&mut self) -> Option<Self::Item> {
        if self.pos == self.size {
            return None;
        }
        let item = unsafe {
            (
                PyObj::from_ptr_unchecked(PyTuple_GET_ITEM(self.keys, self.pos)),
                PyObj::from_ptr_unchecked(*self.values.offset(self.pos)),
            )
        };
        self.pos += 1;
        Some(item)
    }
}

macro_rules! parse_args_kwargs {
    ($args:ident, $kwargs:ident, $fmt:expr, $($var:ident),* $(,)?) => {
        // SAFETY: calling CPython API with valid arguments
        unsafe {
            const _ARGNAMES: *mut *const std::ffi::c_char = [
                $(
                    concat!(stringify!($var), "\0").as_ptr() as *const std::ffi::c_char,
                )*
                std::ptr::null(),
            ].as_ptr() as *mut _;
            if PyArg_ParseTupleAndKeywords(
                $args.as_ptr(),
                $kwargs.map_or(NULL(), |d| d.as_ptr()),
                $fmt.as_ptr(),
                {
                    // This API was changed in Python 3.13
                    #[cfg(Py_3_13)]
                    {
                        _ARGNAMES
                    }
                    #[cfg(not(Py_3_13))]
                    {
                        _ARGNAMES as *mut *mut _
                    }
                },
                $(&mut $var,)*
            ) == 0 {
                return Err(PyErrMarker());
            }
        }
    };
}

#[inline]
fn ptr_eq(a: PyObj, b: PyObj) -> bool {
    a == b
}

#[inline]
fn value_eq(a: PyObj, b: PyObj) -> bool {
    unsafe { PyObject_RichCompareBool(a.as_ptr(), b.as_ptr(), Py_EQ) == 1 }
}

pub(crate) fn handle_kwargs<F, K>(fname: &str, kwargs: K, mut handler: F) -> PyResult<()>
where
    F: FnMut(PyObj, PyObj, fn(PyObj, PyObj) -> bool) -> PyResult<bool>,
    K: IntoIterator<Item = (PyObj, PyObj)>,
{
    for (key, value) in kwargs {
        // First we try to match *all kwargs* on pointer equality.
        // This is actually the common case, as static strings are interned.
        // In the rare case they aren't, we fall back to value comparison.
        // Doing it this way is faster than always doing value comparison outright.
        if !handler(key, value, ptr_eq)? && !handler(key, value, value_eq)? {
            return raise_type_err(format!(
                "{fname}() got an unexpected keyword argument: {key}"
            ));
        }
    }
    Ok(())
}

/// Parse one (optional) kwarg from the kwargs, and raise an error if any other kwargs are present.
pub(crate) fn handle_one_kwarg<K>(fname: &str, key: PyObj, kwargs: K) -> PyResult<Option<PyObj>>
where
    K: IntoIterator<Item = (PyObj, PyObj)>,
{
    for (k, v) in kwargs {
        if k.py_eq(key)? {
            return Ok(Some(v));
        } else {
            raise_type_err(format!("{fname}() got an unexpected keyword argument: {k}"))?;
        }
    }
    Ok(None)
}

/// Parse one (optional) positional argument, and raise an error if the number of arguments is more
/// than one.
pub(crate) fn handle_opt_arg(fname: &str, args: &[PyObj]) -> PyResult<Option<PyObj>> {
    match args {
        &[] => Ok(None),
        &[arg_obj] => Ok(Some(arg_obj)),
        _ => raise_type_err(format!(
            "{fname}() takes at most one positional argument ({} given)",
            args.len()
        )),
    }
}

/// Parse one positional argument, and raise an error if the number of arguments is not exactly
/// one.
pub(crate) fn handle_one_arg(fname: &str, args: &[PyObj]) -> PyResult<PyObj> {
    if let &[arg_obj] = args {
        Ok(arg_obj)
    } else {
        raise_type_err(format!(
            "{fname}() takes exactly one positional argument ({} given)",
            args.len()
        ))
    }
}

/// Helper to efficiently match a value against a set of known interned strings.
/// The handler closure is called twice, first with pointer equality (very fast),
/// and only if that fails, with value equality (slower).
///
/// NOTE: although Python's string equality also uses this trick, it does so
/// on a per-object basis, so it will still end up running slower equality checks
/// multiple times. By doing it this way, we end up with only pointer equality
/// checks for the common case of interned strings.
pub(crate) fn match_interned_str<T, F>(name: &str, value: PyObj, mut handler: F) -> PyResult<T>
where
    F: FnMut(PyObj, fn(PyObj, PyObj) -> bool) -> Option<T>,
{
    handler(value, ptr_eq)
        .or_else(|| handler(value, value_eq))
        .ok_or_else_value_err(|| format!("Invalid value for {name}: {value}"))
}

/// Like `match_interned_str`, but returns `None` if no match is found
/// instead of raising an error.
pub(crate) fn find_interned<T, F>(value: PyObj, mut handler: F) -> Option<T>
where
    F: FnMut(PyObj, fn(PyObj, PyObj) -> bool) -> Option<T>,
{
    handler(value, ptr_eq).or_else(|| handler(value, value_eq))
}

/// Like find_interned, but for boolean checks.
/// The closure returns true if a match was found. Tries ptr_eq first, then value_eq.
pub(crate) fn check_interned<F>(value: PyObj, mut handler: F) -> bool
where
    F: FnMut(PyObj, fn(PyObj, PyObj) -> bool) -> bool,
{
    handler(value, ptr_eq) || handler(value, value_eq)
}

pub(crate) use parse_args_kwargs;
