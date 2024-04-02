use pyo3_ffi::*;

macro_rules! propagate_exc {
    ($e:expr) => {{
        let x = $e;
        if x.is_null() {
            return ptr::null_mut();
        }
        x
    }};
}

macro_rules! raise(
    ($exc:ident, $msg:expr) => {{
        use crate::common::c_str;
        PyErr_SetString($exc, c_str!($msg));
        return ptr::null_mut();
    }};
    ($exc:ident, $msg:expr, $($args:tt),*) => {{
        use crate::common::c_str;
        PyErr_Format($exc, c_str!($msg), $($args),*);
        return ptr::null_mut();
    }};
);

macro_rules! get_digit(
    ($s:ident, $index:expr) => {
        match $s[$index] {
            c if c.is_ascii_digit() => c - b'0',
            _ => return None,
        }
    }
);

macro_rules! pystr_to_utf8(
    ($s:expr, $msg:expr) => {{
        use crate::common::c_str;
        if PyUnicode_Check($s) == 0 {
            PyErr_SetString(PyExc_TypeError, c_str!($msg));
            return ptr::null_mut();
        }
        let mut size = 0;
        let p = PyUnicode_AsUTF8AndSize($s, &mut size);
        if p.is_null() {
            return ptr::null_mut();
        };
        std::slice::from_raw_parts(p.cast::<u8>(), size as usize)
    }}
);

macro_rules! try_get_long(
    ($o:expr) => {{
        let x = PyLong_AsLong($o);
        if x == -1 && !PyErr_Occurred().is_null() {
            return ptr::null_mut();
        }
        x
    }}
);

macro_rules! c_str(
    ($s:expr) => {
        concat!($s, "\0").as_ptr().cast::<c_char>()
    };
);

// TODO: remove
// Used for debugging--OK if not used
#[allow(unused_macros)]
macro_rules! print_repr {
    ($e:expr) => {{
        let s = pystr_to_utf8!(propagate_exc!(PyObject_Repr($e)), "Expected a string");
        println!("{:?}", std::str::from_utf8_unchecked(s));
    }};
}

#[inline]
pub(crate) unsafe fn py_str(s: &str) -> *mut PyObject {
    PyUnicode_FromStringAndSize(s.as_ptr().cast(), s.len() as Py_ssize_t)
}

pub(crate) unsafe extern "C" fn identity(slf: *mut PyObject, _: *mut PyObject) -> *mut PyObject {
    Py_INCREF(slf);
    slf
}

#[allow(unused_imports)]
pub(crate) use {c_str, get_digit, print_repr, propagate_exc, pystr_to_utf8, raise, try_get_long};
