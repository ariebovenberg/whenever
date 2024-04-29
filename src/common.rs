use core::mem;
use pyo3_ffi::*;

use crate::date::Date;
use crate::time::Time;

macro_rules! py_try {
    ($e:expr) => {{
        let x = $e;
        if x.is_null() {
            return ptr::null_mut();
        }
        x
    }};
}

macro_rules! c_str(
    ($s:expr) => {{
        use core::ffi::c_char;
        concat!($s, "\0").as_ptr().cast::<c_char>()
    }};
);

macro_rules! raise(
    ($exc:expr, $msg:literal) => {{
        use crate::common::c_str;
        PyErr_SetString($exc, c_str!($msg));
        return ptr::null_mut();
    }};
    ($exc:expr, $msg:literal, $($args:expr),*) => {{
        use crate::common::c_str;
        PyErr_Format($exc, c_str!($msg), $($args),*);
        return ptr::null_mut();
    }};
);

// TODO: rename `or_else_raise`?
macro_rules! unwrap_or_raise(
    ($e:expr, $exc:ident, $msg:literal) => {
        match $e {
            Some(x) => x,
            None => raise!($exc, $msg),
        }
    };
    ($e:expr, $exc:ident, $msg:literal, $($args:expr),*) => {
        match $e {
            Some(x) => x,
            None => raise!($exc, $msg, $($args),*),
        }
    };
);

macro_rules! between(
    ($x:expr, =$min:expr, $max:expr) => {
        $x >= $min as _ && $x < $max as _
    };
    ($x:expr, =$min:expr, =$max:expr) => {
        $x >= $min as _ && $x <= $max as _
    };
);

macro_rules! get_digit(
    ($s:ident, $index:expr) => {
        match $s[$index] {
            c if c.is_ascii_digit() => c - b'0',
            _ => return None,
        }
    };
    ($s:ident, $index:expr, ..=$max:literal) => {
        match $s[$index] {
            c @ b'0'..=$max => c - b'0',
            _ => return None,
        }
    }
);

macro_rules! pystr_to_utf8(
    ($s:expr, $msg:expr) => {{
        use crate::common::c_str;
        use core::ptr;
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

macro_rules! pybytes_extract(
    ($s:expr) => {{
        let p = PyBytes_AsString($s);
        if p.is_null() {
            return ptr::null_mut();
        };
        std::slice::from_raw_parts(p.cast::<u8>(), PyBytes_Size($s) as usize)
    }}
);

macro_rules! pyint_as_long(
    ($o:expr) => {{
        let x = PyLong_AsLong($o);
        if x == -1 && !PyErr_Occurred().is_null() {
            return ptr::null_mut();
        }
        x
    }}
);

macro_rules! pyint_as_i64(
    ($o:expr) => {{
        let x = PyLong_AsLongLong($o);
        if x == -1 && !PyErr_Occurred().is_null() {
            return ptr::null_mut();
        }
        x as i64
    }}
);

macro_rules! i128_extract(
    ($o:expr, $errmsg:literal) => {{
        use crate::common::i128_extract_unchecked;
        if PyLong_Check($o) == 0 {
            raise!(PyExc_TypeError, $errmsg);
        }
        i128_extract_unchecked!($o.cast())
    }}
);

macro_rules! i128_extract_unchecked(
    ($o:expr) => {{
        let mut bytes: [u8; 16] = [0; 16];
        if _PyLong_AsByteArray($o, &mut bytes as *mut _, 16, 1, 1) != 0 {
            raise!(PyExc_OverflowError, "Python int too large to convert to Rust i128");
        }
        i128::from_le_bytes(bytes)
    }}
);

macro_rules! try_get_float(
    ($o:expr) => {{
        let x = PyFloat_AsDouble($o);
        if x == -1.0 && !PyErr_Occurred().is_null() {
            return ptr::null_mut();
        }
        x
    }}
);

macro_rules! pack {
    [$x:expr, $($xs:expr),*] => {{
        let arr = $x.to_le_bytes();
        let arr = arr.iter().copied();
        $(
            let arr = arr.chain($xs.to_le_bytes());
        )*
        let arr:Vec<u8> = arr.collect();
        arr
    }}
}

macro_rules! unpack_one {
    ($arr:ident, $t:ty) => {{
        const SIZE: usize = std::mem::size_of::<$t>();
        let mut bytes = [0; SIZE];
        bytes.copy_from_slice(&$arr[..SIZE]);
        $arr = &$arr[SIZE..];
        <$t>::from_le_bytes(bytes)
    }};
}

macro_rules! classmethod(
    ($meth:ident, $doc:expr) => {
        classmethod!($meth named stringify!($meth), $doc, METH_NOARGS)
    };
    ($meth:ident, $doc:expr, $flags:expr) => {
        classmethod!($meth named stringify!($meth), $doc, $flags)
    };
    ($meth:ident named $name:expr, $doc:expr, $flags:expr) => {
        PyMethodDef {
            ml_name: c_str!($name),
            ml_meth: PyMethodDefPointer {
                PyCFunction: $meth,
            },
            ml_flags: METH_CLASS | $flags,
            ml_doc: c_str!($doc),
        }
    };
);

macro_rules! method(
    ($meth:ident, $doc:expr) => {
        method!($meth named stringify!($meth), $doc, METH_NOARGS)
    };

    ($meth:ident, $doc:expr, $flags:expr) => {
        method!($meth named stringify!($meth), $doc, $flags)
    };

    ($meth:ident named $name:expr, $doc:expr) => {
        method!($meth named $name, $doc, METH_NOARGS)
    };

    ($meth:ident named $name:expr, $doc:expr, $flags:expr) => {
        PyMethodDef {
            ml_name: c_str!($name),
            ml_meth: PyMethodDefPointer {
                PyCFunction: $meth,
            },
            ml_flags: $flags,
            ml_doc: c_str!($doc),
        }
    };
);

macro_rules! getter(
    ($meth:ident named $name:expr, $doc:expr) => {
        PyGetSetDef {
            name: c_str!($name),
            get: Some($meth),
            set: None,
            doc: c_str!($doc),
            closure: ptr::null_mut(),
        }
    };
);

pub(crate) struct DecrefOnDrop(pub(crate) *mut PyObject);

impl Drop for DecrefOnDrop {
    fn drop(&mut self) {
        unsafe { Py_DECREF(self.0) };
    }
}

macro_rules! defer_decref(
    ($name:ident) => {
        let _deferred = DecrefOnDrop($name);
    };
);

// Apply this on arguments to have them decref'd after the call
macro_rules! steal(
    ($e:expr) => {
        DecrefOnDrop($e).0
    };
);

#[derive(Debug, Copy, Clone, PartialEq, Eq, PartialOrd, Ord)]
pub(crate) struct PyErrOccurred(); // sentinel that the Python error indicator is set
pub(crate) type PyResult<T> = Result<T, PyErrOccurred>;

pub(crate) trait PyObjectExt {
    unsafe fn as_result<'a>(self) -> PyResult<&'a mut PyObject>;
}

impl PyObjectExt for *mut PyObject {
    unsafe fn as_result<'a>(self) -> PyResult<&'a mut PyObject> {
        self.as_mut().ok_or(PyErrOccurred())
    }
}

macro_rules! to_py {
    ($e:expr) => {{
        use crate::common::PyErrOccurred;
        match $e {
            Ok(x) => x,
            Err(PyErrOccurred()) => return ptr::null_mut(),
        }
    }};
}

// TODO: remove
// Used for debugging--OK if not used
#[allow(unused_macros)]
macro_rules! print_repr {
    ($e:expr) => {{
        let s = pystr_to_utf8!(py_try!(PyObject_Repr($e)), "Expected a string");
        println!("{:?}", std::str::from_utf8_unchecked(s));
    }};
}

pub(crate) unsafe fn py_bool(val: bool) -> *mut PyObject {
    match val {
        true => Py_True(),
        false => Py_False(),
    }
}

pub(crate) unsafe fn py_int128(n: i128) -> *mut PyObject {
    _PyLong_FromByteArray(
        n.to_le_bytes().as_ptr().cast(),
        mem::size_of::<i128>(),
        1,
        1,
    )
}

pub(crate) unsafe fn py_str(s: &str) -> *mut PyObject {
    PyUnicode_FromStringAndSize(s.as_ptr().cast(), s.len() as _)
}

pub(crate) unsafe fn py_bytes(s: &[u8]) -> *mut PyObject {
    // TODO: cast to c_char always valid?
    PyBytes_FromStringAndSize(s.as_ptr().cast(), s.len() as _)
}

pub(crate) unsafe extern "C" fn identity(slf: *mut PyObject, _: *mut PyObject) -> *mut PyObject {
    newref(slf)
}

pub(crate) unsafe fn newref(obj: *mut PyObject) -> *mut PyObject {
    Py_INCREF(obj);
    obj
}

pub(crate) unsafe fn offset_from_py_dt(dt: *mut PyObject) -> i32 {
    // OPTIMIZE: is calling ZoneInfo.utcoffset() faster?
    let delta = PyObject_CallMethodNoArgs(dt, steal!(py_str("utcoffset")))
        .as_result()
        .unwrap();
    defer_decref!(delta);
    PyDateTime_DELTA_GET_DAYS(delta) * 86400 + PyDateTime_DELTA_GET_SECONDS(delta)
}

pub(crate) unsafe fn offset_from_py_dt_safe(dt: *mut PyObject) -> PyResult<i32> {
    // OPTIMIZE: is calling ZoneInfo.utcoffset() faster?
    let delta = PyObject_CallMethodNoArgs(dt, steal!(py_str("utcoffset")))
        .as_result()
        .unwrap();
    defer_decref!(delta);
    Ok(PyDateTime_DELTA_GET_DAYS(delta) * 86400 + PyDateTime_DELTA_GET_SECONDS(delta))
}

pub(crate) fn offset_fmt(secs: i32) -> String {
    let (sign, secs) = if secs < 0 { ('-', -secs) } else { ('+', secs) };
    if secs % 60 == 0 {
        format!("{}{:02}:{:02}", sign, secs / 3600, (secs % 3600) / 60)
    } else {
        format!(
            "{}{:02}:{:02}:{:02}",
            sign,
            secs / 3600,
            (secs % 3600) / 60,
            secs % 60
        )
    }
}

#[derive(Debug, Copy, Clone, PartialEq, Eq)]
pub(crate) enum Disambiguate {
    Compatible,
    Earlier,
    Later,
    Raise,
}

#[derive(Debug, Copy, Clone, PartialEq, Eq)]
pub(crate) enum OffsetResult {
    Unambiguous(i32),
    Gap(i32, i32),
    Fold(i32, i32),
}

unsafe fn local_offset(
    date: Date,
    time: Time,
    fold: i32,
    &PyDateTime_CAPI {
        DateTime_FromDateAndTimeAndFold,
        DateTimeType,
        ..
    }: &PyDateTime_CAPI,
) -> Option<(i32, bool)> {
    // OPTIMIZE: re-use Python string objects
    let naive = DateTime_FromDateAndTimeAndFold(
        date.year.into(),
        date.month.into(),
        date.day.into(),
        time.hour.into(),
        time.minute.into(),
        time.second.into(),
        0, // no sub-second ZoneInfo offsets exist
        Py_None(),
        fold,
        DateTimeType,
    );
    defer_decref!(naive);
    let aware = PyObject_CallMethodNoArgs(naive, steal!(py_str("astimezone"))).as_mut()?;
    defer_decref!(aware);
    let kwargs = PyDict_New();
    defer_decref!(kwargs);
    PyDict_SetItemString(kwargs, c_str!("tzinfo"), Py_None());
    let shifted_naive = PyObject_Call(
        PyObject_GetAttrString(aware, c_str!("replace")).as_mut()?,
        PyTuple_New(0),
        kwargs,
    );
    defer_decref!(shifted_naive);
    let shifted = PyObject_RichCompareBool(naive, shifted_naive, Py_EQ) == 0;
    Some((offset_from_py_dt(aware), shifted))
}

impl OffsetResult {
    pub(crate) unsafe fn for_localsystem(
        py_api: &PyDateTime_CAPI,
        date: Date,
        time: Time,
    ) -> OffsetResult {
        let (offset0, shifted) = local_offset(date, time, 0, py_api).unwrap();
        let (offset1, _) = local_offset(date, time, 1, py_api).unwrap();
        use OffsetResult::*;
        if offset0 == offset1 {
            Unambiguous(offset0)
        } else if shifted {
            Gap(offset1, offset0)
        } else {
            Fold(offset0, offset1)
        }
    }

    pub(crate) unsafe fn for_tz(
        &PyDateTime_CAPI {
            DateTime_FromDateAndTimeAndFold,
            DateTimeType,
            ..
        }: &PyDateTime_CAPI,
        date: Date,
        time: Time,
        zoneinfo: *mut PyObject,
    ) -> OffsetResult {
        let dt0 = DateTime_FromDateAndTimeAndFold(
            date.year.into(),
            date.month.into(),
            date.day.into(),
            time.hour.into(),
            time.minute.into(),
            time.second.into(),
            0, // no sub-second ZoneInfo offsets exist
            zoneinfo,
            0,
            DateTimeType,
        );
        defer_decref!(dt0);
        let dt1 = DateTime_FromDateAndTimeAndFold(
            date.year.into(),
            date.month.into(),
            date.day.into(),
            time.hour.into(),
            time.minute.into(),
            time.second.into(),
            0, // no sub-second ZoneInfo offsets exist
            zoneinfo,
            1,
            DateTimeType,
        );
        defer_decref!(dt1);
        let offset0 = offset_from_py_dt(dt0);
        let offset1 = offset_from_py_dt(dt1);

        use OffsetResult::*;
        if offset0 == offset1 {
            Unambiguous(offset0)
        } else if offset0 > offset1 {
            Fold(offset0, offset1)
        } else {
            Gap(offset0, offset1)
        }
    }
}

impl Disambiguate {
    pub(crate) fn parse(s: &[u8]) -> Option<Self> {
        match s {
            b"compatible" => Some(Self::Compatible),
            b"earlier" => Some(Self::Earlier),
            b"later" => Some(Self::Later),
            b"raise" => Some(Self::Raise),
            _ => None,
        }
    }
}

#[derive(Debug, Copy, Clone, PartialEq, Eq)]
pub(crate) enum Ambiguity {
    Fold,
    Gap,
}

// This mask prevents the hash value from being -1,
// which is reserved for indicating an error.
// TODO: actually check if using this correctly
pub(crate) const HASH_MASK: Py_hash_t = -2;

// TODO: a more efficient way to guarantee this in case of smaller values?
pub(crate) const fn hashmask(hash: Py_hash_t) -> Py_hash_t {
    match hash {
        -1 => -2,
        x => x,
    }
}

#[allow(unused_imports)]
pub(crate) use {
    between, c_str, classmethod, get_digit, getter, i128_extract, i128_extract_unchecked, method,
    pack, print_repr, py_try, pybytes_extract, pyint_as_i64, pyint_as_long, pystr_to_utf8, raise,
    to_py, try_get_float, unpack_one, unwrap_or_raise,
};
