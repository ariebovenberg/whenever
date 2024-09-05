use core::ffi::c_long;
use core::mem;
use core::ptr::null_mut as NULL;
use pyo3_ffi::*;

use crate::date::Date;
use crate::time::Time;

macro_rules! cstr(
    ($s:expr) => {{
        use core::ffi::c_char;
        concat!($s, "\0").as_ptr().cast::<c_char>()
    }};
    ($template:expr, $($arg:tt)*) => {{
        use core::ffi::c_char;
        format!(
            concat!($template, "\0"),
            $($arg)*
        ).as_ptr().cast::<c_char>()
    }}
);

macro_rules! py_err(
    () => {
        PyErrOccurred()
    };
    ($exc:expr, $msg:expr) => {{
        match $msg.to_py() {
            Ok(msg) => PyErr_SetObject($exc, msg),
            Err(_) => {},
        }
        PyErrOccurred()
    }};
    ($exc:expr, $msg:literal, $($args:tt)*) => {{
        match format!($msg, $($args)*).to_py() {
            Ok(msg) => PyErr_SetObject($exc, msg),
            Err(_) => {},
        }
        PyErrOccurred()
    }};
);

macro_rules! value_err(
    ($msg:literal) => {
        py_err!(PyExc_ValueError, $msg)
    };
    ($msg:literal, $($args:expr),*) => {
        py_err!(PyExc_ValueError, $msg, $($args),*)
    };
);

macro_rules! type_err(
    ($msg:literal) => {
        py_err!(PyExc_TypeError, $msg)
    };
    ($msg:literal, $($args:expr),*) => {
        py_err!(PyExc_TypeError, $msg, $($args),*)
    };
);

#[inline]
pub(crate) fn parse_digit(s: &[u8], index: usize) -> Option<u8> {
    match s[index] {
        c if c.is_ascii_digit() => Some(c - b'0'),
        _ => None,
    }
}

#[inline]
pub(crate) fn parse_digit_max(s: &[u8], index: usize, max: u8) -> Option<u8> {
    match s[index] {
        c if c >= b'0' && c <= max => Some(c - b'0'),
        _ => None,
    }
}

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
        let data = <$t>::from_le_bytes($arr[..SIZE].try_into().unwrap());
        #[allow(unused_assignments)]
        {
            $arr = &$arr[SIZE..];
        }
        data
    }};
}

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
            ml_name: cstr!($name),
            ml_meth: PyMethodDefPointer {
                PyCFunction: {
                    unsafe extern "C" fn _wrap(slf: *mut PyObject, arg: *mut PyObject) -> *mut PyObject {
                        match $meth(&mut *slf, &mut *arg) {
                            Ok(x) => x,
                            Err(PyErrOccurred()) => core::ptr::null_mut(),
                        }
                    }
                    _wrap
                },
            },
            ml_flags: $flags,
            ml_doc: cstr!($doc),
        }
    };
);

macro_rules! method_vararg(
    ($meth:ident, $doc:expr) => {
        method_vararg!($meth named stringify!($meth), $doc, 0)
    };

    ($meth:ident, $doc:expr, $flags:expr) => {
        method_vararg!($meth named stringify!($meth), $doc, $flags)
    };

    ($meth:ident named $name:expr, $doc:expr) => {
        method_vararg!($meth named $name, $doc, 0)
    };

    ($meth:ident named $name:expr, $doc:expr, $flags:expr) => {
        PyMethodDef {
            ml_name: cstr!($name),
            ml_meth: PyMethodDefPointer {
                _PyCFunctionFast: {
                    unsafe extern "C" fn _wrap(
                        slf: *mut PyObject,
                        args: *mut *mut PyObject,
                        nargs: Py_ssize_t,
                    ) -> *mut PyObject {
                        match $meth(&mut *slf, std::slice::from_raw_parts(args, nargs as usize)) {
                            Ok(x) => x,
                            Err(PyErrOccurred()) => core::ptr::null_mut(),
                        }
                    }
                    _wrap
                },
            },
            ml_flags: METH_FASTCALL | $flags,
            ml_doc: cstr!($doc),
        }
    };
);

pub(crate) struct KwargIter {
    keys: *mut PyObject,
    values: *const *mut PyObject,
    size: isize,
    pos: isize,
}

impl KwargIter {
    pub(crate) unsafe fn new(keys: *mut PyObject, values: *const *mut PyObject) -> Self {
        Self {
            keys,
            values,
            size: if keys.is_null() {
                0
            } else {
                PyTuple_GET_SIZE(keys) as isize
            },
            pos: 0,
        }
    }

    pub(crate) fn len(&self) -> isize {
        self.size
    }
}

impl Iterator for KwargIter {
    type Item = (*mut PyObject, *mut PyObject);

    fn next(&mut self) -> Option<Self::Item> {
        if self.pos >= self.size {
            return None;
        }
        let i = self.pos;
        self.pos = i + 1;
        unsafe { Some((PyTuple_GET_ITEM(self.keys, i), *self.values.offset(i))) }
    }
}

macro_rules! method_kwargs(
    ($meth:ident, $doc:expr) => {
        method_kwargs!($meth named stringify!($meth), $doc)
    };

    ($meth:ident, $doc:expr, $flags:expr) => {
        method_kwargs!($meth named stringify!($meth), $doc, $flags)
    };

    ($meth:ident named $name:expr, $doc:expr) => {
        method_kwargs!($meth named $name, $doc, 0)
    };

    ($meth:ident named $name:expr, $doc:expr, $flags:expr) => {
        PyMethodDef {
            ml_name: cstr!($name),
            ml_meth: PyMethodDefPointer {
                PyCMethod: {
                    unsafe extern "C" fn _wrap(
                        slf: *mut PyObject,
                        cls: *mut PyTypeObject,
                        args_raw: *const *mut PyObject,
                        nargsf: Py_ssize_t,
                        kwnames: *mut PyObject,
                    ) -> *mut PyObject {
                        let nargs = PyVectorcall_NARGS(nargsf as usize);
                        let args = std::slice::from_raw_parts(args_raw, nargs as usize);
                        let mut kwargs = KwargIter::new(kwnames, args_raw.offset(nargs as isize));
                        match $meth(slf, cls, args, &mut kwargs) {
                            Ok(x) => x as *mut PyObject,
                            Err(PyErrOccurred()) => core::ptr::null_mut(),
                        }
                    }
                    _wrap
                },
            },
            ml_flags: $flags | METH_METHOD | METH_FASTCALL | METH_KEYWORDS,
            ml_doc: cstr!($doc),
        }
    };
);

macro_rules! slotmethod {
    (Py_tp_new, $name:ident) => {
        PyType_Slot {
            slot: Py_tp_new,
            pfunc: {
                unsafe extern "C" fn _wrap(
                    cls: *mut PyTypeObject,
                    args: *mut PyObject,
                    kwargs: *mut PyObject,
                ) -> *mut PyObject {
                    match $name(cls, args, kwargs) {
                        Ok(x) => x,
                        Err(PyErrOccurred()) => core::ptr::null_mut(),
                    }
                }
                _wrap as *mut c_void
            },
        }
    };

    (Py_tp_richcompare, $name:ident) => {
        PyType_Slot {
            slot: Py_tp_richcompare,
            pfunc: {
                unsafe extern "C" fn _wrap(
                    a: *mut PyObject,
                    b: *mut PyObject,
                    op: c_int,
                ) -> *mut PyObject {
                    match $name(a, b, op) {
                        Ok(x) => x,
                        Err(PyErrOccurred()) => core::ptr::null_mut(),
                    }
                }
                _wrap as *mut c_void
            },
        }
    };

    ($slot:ident, $name:ident, 2) => {
        PyType_Slot {
            slot: $slot,
            pfunc: {
                unsafe extern "C" fn _wrap(
                    slf: *mut PyObject,
                    arg: *mut PyObject,
                ) -> *mut PyObject {
                    match $name(slf, arg) {
                        Ok(x) => x,
                        Err(PyErrOccurred()) => core::ptr::null_mut(),
                    }
                }
                _wrap as *mut c_void
            },
        }
    };

    ($slot:ident, $name:ident, 1) => {
        PyType_Slot {
            slot: $slot,
            pfunc: {
                unsafe extern "C" fn _wrap(slf: *mut PyObject) -> *mut PyObject {
                    match $name(slf) {
                        Ok(x) => x,
                        Err(PyErrOccurred()) => core::ptr::null_mut(),
                    }
                }
                _wrap as *mut c_void
            },
        }
    };
}

macro_rules! getter(
    ($meth:ident named $name:expr, $doc:expr) => {
        PyGetSetDef {
            name: cstr!($name),
            get: Some({
                unsafe extern "C" fn _wrap(
                    slf: *mut PyObject,
                    _: *mut c_void,
                ) -> *mut PyObject {
                    match $meth(&mut *slf) {
                        Ok(x) => x,
                        Err(PyErrOccurred()) => core::ptr::null_mut(),
                    }
                }
                _wrap
            }),
            set: None,
            doc: cstr!($doc),
            closure: core::ptr::null_mut(),
        }
    };
);

pub(crate) struct DecrefOnDrop(pub(crate) *mut PyObject);

impl Drop for DecrefOnDrop {
    fn drop(&mut self) {
        unsafe { Py_DECREF(self.0) };
    }
}

// Automatically decref the object when it goes out of scope
macro_rules! defer_decref(
    ($name:ident) => {
        let _deferred = DecrefOnDrop($name);
    };
);

// Apply this on arguments to have them decref'd after the containing expression.
// For function calls, it has the same effect as if the call would 'steal' the reference
macro_rules! steal(
    ($e:expr) => {
        DecrefOnDrop($e).0
    };
);

// We use `Result` to implement Python's error handling.
// Note that Python's error handling doesn't map exactly onto Rust's `Result` type,
// The most important difference being that Python's error handling
// is based on a global error indicator.
// This means that some `Result` functionality will not behave as expected.
// However, this is a price we can pay in exchange for the convenience
// of the `?` operator.
#[derive(Debug, Copy, Clone, PartialEq, Eq, PartialOrd, Ord)]
pub(crate) struct PyErrOccurred(); // sentinel that the Python error indicator is set

impl PyErrOccurred {
    pub(crate) fn err<T>(self) -> PyResult<T> {
        Err(self)
    }
}
pub(crate) type PyResult<T> = Result<T, PyErrOccurred>;
pub(crate) type PyReturn = PyResult<&'static mut PyObject>;

pub(crate) trait PyObjectExt {
    #[allow(clippy::wrong_self_convention)]
    unsafe fn as_result<'a>(self) -> PyResult<&'a mut PyObject>;
    #[allow(clippy::wrong_self_convention)]
    unsafe fn is_int(self) -> bool;
    #[allow(clippy::wrong_self_convention)]
    unsafe fn is_str(self) -> bool;
    #[allow(clippy::wrong_self_convention)]
    unsafe fn is_float(self) -> bool;
    // FUTURE: unchecked versions of these in case we know the type
    unsafe fn to_bytes<'a>(self) -> PyResult<Option<&'a [u8]>>;
    unsafe fn to_utf8<'a>(self) -> PyResult<Option<&'a [u8]>>;
    unsafe fn to_str<'a>(self) -> PyResult<Option<&'a str>>;
    unsafe fn to_long(self) -> PyResult<Option<c_long>>;
    unsafe fn to_i64(self) -> PyResult<Option<i64>>;
    unsafe fn to_i128(self) -> PyResult<Option<i128>>;
    unsafe fn to_f64(self) -> PyResult<Option<f64>>;
    unsafe fn repr(self) -> String;
    unsafe fn kwarg_eq(self, other: *mut PyObject) -> bool;
}

impl PyObjectExt for *mut PyObject {
    unsafe fn as_result<'a>(self) -> PyResult<&'a mut PyObject> {
        self.as_mut().ok_or(PyErrOccurred())
    }
    unsafe fn is_int(self) -> bool {
        PyLong_Check(self) != 0
    }

    unsafe fn is_float(self) -> bool {
        PyFloat_Check(self) != 0
    }

    unsafe fn is_str(self) -> bool {
        PyUnicode_Check(self) != 0
    }

    // WARNING: the string lifetime is only valid so long as the
    // Python object is alive
    unsafe fn to_bytes<'a>(self) -> PyResult<Option<&'a [u8]>> {
        if PyBytes_Check(self) == 0 {
            return Ok(None);
        };
        let p = PyBytes_AsString(self);
        if p.is_null() {
            return Err(PyErrOccurred());
        };
        Ok(Some(std::slice::from_raw_parts(
            p.cast::<u8>(),
            PyBytes_Size(self) as usize,
        )))
    }

    // WARNING: the string lifetime is only valid so long as the
    // Python object is alive
    unsafe fn to_utf8<'a>(self) -> PyResult<Option<&'a [u8]>> {
        if PyUnicode_Check(self) == 0 {
            return Ok(None);
        }
        let mut size = 0;
        let p = PyUnicode_AsUTF8AndSize(self, &mut size);
        if p.is_null() {
            return Err(PyErrOccurred());
        };
        Ok(Some(std::slice::from_raw_parts(
            p.cast::<u8>(),
            size as usize,
        )))
    }

    // WARNING: the string lifetime is only valid so long as the
    // Python object is alive
    unsafe fn to_str<'a>(self) -> PyResult<Option<&'a str>> {
        Ok(self.to_utf8()?.map(|s| std::str::from_utf8_unchecked(s)))
    }

    unsafe fn to_long(self) -> PyResult<Option<c_long>> {
        if PyLong_Check(self) == 0 {
            return Ok(None);
        }
        let x = PyLong_AsLong(self);
        if x == -1 && !PyErr_Occurred().is_null() {
            return Err(PyErrOccurred());
        }
        Ok(Some(x))
    }

    unsafe fn to_i64(self) -> PyResult<Option<i64>> {
        if PyLong_Check(self) == 0 {
            return Ok(None);
        }
        let x = PyLong_AsLongLong(self);
        if x == -1 && !PyErr_Occurred().is_null() {
            return Err(PyErrOccurred());
        }
        Ok(Some(x))
    }

    unsafe fn to_i128(self) -> PyResult<Option<i128>> {
        if PyLong_Check(self) == 0 {
            return Ok(None);
        }
        let mut bytes: [u8; 16] = [0; 16];
        if _PyLong_AsByteArray(self.cast(), &mut bytes as *mut _, 16, 1, 1) != 0 {
            Err(py_err!(
                PyExc_OverflowError,
                "Python int too large to convert to i128"
            ))
        } else {
            Ok(Some(i128::from_le_bytes(bytes)))
        }
    }

    unsafe fn to_f64(self) -> PyResult<Option<f64>> {
        if PyFloat_Check(self) == 0 {
            return Ok(None);
        }
        let x = PyFloat_AsDouble(self);
        if x == -1.0 && !PyErr_Occurred().is_null() {
            return Err(PyErrOccurred());
        }
        Ok(Some(x))
    }

    unsafe fn repr(self) -> String {
        let repr_obj = PyObject_Repr(self);
        if repr_obj.is_null() {
            // i.e. it raised an exception, or isn't a string
            PyErr_Clear();
            return "<repr() failed>".to_string();
        }
        defer_decref!(repr_obj);
        debug_assert!(repr_obj.is_str());
        match repr_obj.to_str() {
            Ok(Some(r)) => r,
            _ => {
                PyErr_Clear();
                "<repr() failed>"
            }
        }
        .to_string()
    }

    // A faster comparison for keyword arguments that leverages
    // the fact that keyword arguments are almost always interned
    unsafe fn kwarg_eq(self, other: *mut PyObject) -> bool {
        self == other || PyObject_RichCompareBool(self, other, Py_EQ) == 1
    }
}

pub(crate) trait OptionExt<T> {
    unsafe fn ok_or_py_err(self, exc: *mut PyObject, msg: &str) -> PyResult<T>;
    unsafe fn ok_or_value_err(self, msg: &str) -> PyResult<T>;
    unsafe fn ok_or_type_err(self, msg: &str) -> PyResult<T>;
}

impl<T> OptionExt<T> for Option<T> {
    unsafe fn ok_or_py_err(self, exc: *mut PyObject, msg: &str) -> PyResult<T> {
        self.ok_or_else(|| {
            // If conversion to a Python object fails (MemoryError likely),
            // a message is already set for us.
            if let Ok(msg) = msg.to_py() {
                PyErr_SetObject(exc, msg)
            };
            PyErrOccurred()
        })
    }

    unsafe fn ok_or_value_err(self, msg: &str) -> PyResult<T> {
        self.ok_or_py_err(PyExc_ValueError, msg)
    }

    unsafe fn ok_or_type_err(self, msg: &str) -> PyResult<T> {
        self.ok_or_py_err(PyExc_TypeError, msg)
    }
}

pub(crate) trait ToPy {
    unsafe fn to_py(self) -> PyReturn;
}

impl ToPy for bool {
    unsafe fn to_py(self) -> PyReturn {
        match self {
            true => Ok(newref(Py_True().as_mut().unwrap())),
            false => Ok(newref(Py_False().as_mut().unwrap())),
        }
    }
}

impl ToPy for i128 {
    unsafe fn to_py(self) -> PyReturn {
        _PyLong_FromByteArray(
            self.to_le_bytes().as_ptr().cast(),
            mem::size_of::<i128>(),
            1,
            1,
        )
        .as_result()
    }
}

impl ToPy for i64 {
    unsafe fn to_py(self) -> PyReturn {
        PyLong_FromLongLong(self).as_result()
    }
}

impl ToPy for i32 {
    unsafe fn to_py(self) -> PyReturn {
        PyLong_FromLong(self.into()).as_result()
    }
}

impl ToPy for f64 {
    unsafe fn to_py(self) -> PyReturn {
        PyFloat_FromDouble(self).as_result()
    }
}

impl ToPy for u32 {
    unsafe fn to_py(self) -> PyReturn {
        PyLong_FromUnsignedLong(self.into()).as_result()
    }
}

impl ToPy for u16 {
    unsafe fn to_py(self) -> PyReturn {
        PyLong_FromUnsignedLong(self.into()).as_result()
    }
}

impl ToPy for u8 {
    unsafe fn to_py(self) -> PyReturn {
        PyLong_FromUnsignedLong(self.into()).as_result()
    }
}

impl ToPy for String {
    unsafe fn to_py(self) -> PyReturn {
        PyUnicode_FromStringAndSize(self.as_ptr().cast(), self.len() as _).as_result()
    }
}

impl ToPy for &str {
    unsafe fn to_py(self) -> PyReturn {
        PyUnicode_FromStringAndSize(self.as_ptr().cast(), self.len() as _).as_result()
    }
}

impl ToPy for &[u8] {
    unsafe fn to_py(self) -> PyReturn {
        PyBytes_FromStringAndSize(self.as_ptr().cast(), self.len() as _).as_result()
    }
}

impl<T> ToPy for (T,) {
    unsafe fn to_py(self) -> PyReturn {
        PyTuple_Pack(1, self.0).as_result()
    }
}

impl<T, U> ToPy for (T, U) {
    unsafe fn to_py(self) -> PyReturn {
        PyTuple_Pack(2, self.0, self.1).as_result()
    }
}

impl<T, U, V> ToPy for (T, U, V) {
    unsafe fn to_py(self) -> PyReturn {
        PyTuple_Pack(3, self.0, self.1, self.2).as_result()
    }
}

impl<T, U, V, W> ToPy for (T, U, V, W) {
    unsafe fn to_py(self) -> PyReturn {
        PyTuple_Pack(4, self.0, self.1, self.2, self.3).as_result()
    }
}

impl<T, U, V, W, X> ToPy for (T, U, V, W, X) {
    unsafe fn to_py(self) -> PyReturn {
        PyTuple_Pack(5, self.0, self.1, self.2, self.3, self.4).as_result()
    }
}

pub(crate) unsafe fn identity1(slf: *mut PyObject) -> PyReturn {
    Ok(newref(slf))
}

pub(crate) unsafe fn identity2(slf: *mut PyObject, _: *mut PyObject) -> PyReturn {
    Ok(newref(slf))
}

pub(crate) unsafe fn newref<'a>(obj: *mut PyObject) -> &'a mut PyObject {
    Py_INCREF(obj);
    obj.as_mut().unwrap()
}

pub(crate) unsafe fn offset_from_py_dt(dt: *mut PyObject) -> PyResult<i32> {
    // OPTIMIZE: is calling ZoneInfo.utcoffset() faster?
    let delta = methcall0(dt, "utcoffset")?;
    defer_decref!(delta);
    Ok(PyDateTime_DELTA_GET_DAYS(delta) * 86_400 + PyDateTime_DELTA_GET_SECONDS(delta))
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

unsafe fn system_offset(
    date: Date,
    time: Time,
    fold: i32,
    &PyDateTime_CAPI {
        DateTime_FromDateAndTimeAndFold,
        DateTimeType,
        ..
    }: &PyDateTime_CAPI,
) -> PyResult<(i32, bool)> {
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
    )
    .as_result()?;
    defer_decref!(naive);
    let aware = methcall0(naive, "astimezone")?;
    defer_decref!(aware);
    let kwargs = PyDict_New().as_result()?;
    defer_decref!(kwargs);
    if PyDict_SetItemString(kwargs, c"tzinfo".as_ptr(), Py_None()) == -1 {
        return Err(PyErrOccurred());
    }
    let shifted_naive = PyObject_Call(
        PyObject_GetAttrString(aware, c"replace".as_ptr()).as_result()?,
        PyTuple_New(0),
        kwargs,
    )
    .as_result()?;
    defer_decref!(shifted_naive);
    let shifted = match PyObject_RichCompareBool(naive, shifted_naive, Py_EQ) {
        1 => false,
        0 => true,
        _ => return Err(PyErrOccurred()),
    };
    Ok((offset_from_py_dt(aware)?, shifted))
}

impl OffsetResult {
    pub(crate) unsafe fn for_system_tz(
        py_api: &PyDateTime_CAPI,
        date: Date,
        time: Time,
    ) -> PyResult<OffsetResult> {
        let (offset0, shifted) = system_offset(date, time, 0, py_api)?;
        let (offset1, _) = system_offset(date, time, 1, py_api)?;

        Ok(if offset0 == offset1 {
            Self::Unambiguous(offset0)
        } else if shifted {
            // Before Python 3.12, the fold of system times was erroneously reversed
            // in case of gaps. See cpython/issues/83861
            #[cfg(Py_3_12)]
            {
                Self::Gap(offset1, offset0)
            }
            #[cfg(not(Py_3_12))]
            {
                Self::Gap(offset0, offset1)
            }
        } else {
            Self::Fold(offset0, offset1)
        })
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
    ) -> PyResult<OffsetResult> {
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
        )
        .as_result()?;
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
        )
        .as_result()?;
        defer_decref!(dt1);
        let off0 = offset_from_py_dt(dt0)?;
        let off1 = offset_from_py_dt(dt1)?;

        Ok(match off0.cmp(&off1) {
            std::cmp::Ordering::Equal => Self::Unambiguous(off0),
            std::cmp::Ordering::Greater => Self::Fold(off0, off1),
            std::cmp::Ordering::Less => Self::Gap(off0, off1),
        })
    }
}

impl Disambiguate {
    pub(crate) fn parse(s: &[u8]) -> Option<Self> {
        Some(match s {
            b"compatible" => Self::Compatible,
            b"earlier" => Self::Earlier,
            b"later" => Self::Later,
            b"raise" => Self::Raise,
            _ => None?,
        })
    }

    pub(crate) unsafe fn from_py(obj: *mut PyObject) -> PyResult<Self> {
        Disambiguate::parse(
            obj.to_utf8()?
                .ok_or_type_err("disambiguate must be a string")?,
        )
        .ok_or_value_err("Invalid disambiguate value")
    }

    pub(crate) unsafe fn from_only_kwarg(
        kwargs: &mut KwargIter,
        str_disambiguate: *mut PyObject,
        fname: &str,
    ) -> PyResult<Self> {
        match kwargs.next() {
            Some((name, value)) if kwargs.len() == 1 => {
                if name.kwarg_eq(str_disambiguate) {
                    Self::from_py(value)
                } else {
                    Err(type_err!(
                        "{}() got an unexpected keyword argument {}",
                        fname,
                        name.repr()
                    ))
                }
            }
            Some(_) => Err(type_err!(
                "{}() takes at most 1 keyword argument, got {}",
                fname,
                kwargs.len()
            )),
            None => Err(type_err!(
                "{}() missing 1 required keyword-only argument: 'disambiguate'",
                fname
            )),
        }
    }
}

#[derive(Debug, Copy, Clone, PartialEq, Eq)]
pub(crate) enum Ambiguity {
    Fold,
    Gap,
}

pub(crate) unsafe extern "C" fn generic_dealloc(slf: *mut PyObject) {
    let cls = Py_TYPE(slf);
    let tp_free = PyType_GetSlot(cls, Py_tp_free);
    debug_assert_ne!(tp_free, core::ptr::null_mut());
    let f: freefunc = std::mem::transmute(tp_free);
    f(slf.cast());
    Py_DECREF(cls.cast());
}

#[inline]
pub(crate) unsafe fn generic_alloc<T>(type_: *mut PyTypeObject, d: T) -> PyReturn {
    let f: allocfunc = (*type_).tp_alloc.unwrap();
    let slf = f(type_, 0).cast::<PyWrap<T>>();
    match slf.cast::<PyObject>().as_mut() {
        Some(r) => {
            core::ptr::addr_of_mut!((*slf).data).write(d);
            Ok(r)
        }
        None => Err(PyErrOccurred()),
    }
}

pub(crate) trait PyWrapped: Copy {
    #[inline]
    unsafe fn extract(obj: *mut PyObject) -> Self {
        generic_extract(obj)
    }

    #[inline]
    unsafe fn to_obj(self, type_: *mut PyTypeObject) -> PyReturn {
        generic_alloc(type_, self)
    }
}

#[repr(C)]
pub(crate) struct PyWrap<T> {
    _ob_base: PyObject,
    data: T,
}

#[inline]
pub(crate) unsafe fn generic_extract<T: Copy>(obj: *mut PyObject) -> T {
    (*obj.cast::<PyWrap<T>>()).data
}

macro_rules! type_spec {
    ($typ:ident, $slots:expr) => {
        pub(crate) static mut SPEC: PyType_Spec = PyType_Spec {
            name: concat!("whenever.", stringify!($typ), "\0").as_ptr().cast(),
            basicsize: mem::size_of::<PyWrap<$typ>>() as _,
            itemsize: 0,
            #[cfg(Py_3_10)]
            flags: (Py_TPFLAGS_DEFAULT | Py_TPFLAGS_IMMUTABLETYPE) as _,
            // XXX: implement a way to prevent refcycles on Python 3.9
            // without Py_TPFLAGS_IMMUTABLETYPE.
            // Not a pressing concern, because this only will be triggered
            // if users themselves decide to add instances to the class
            // namespace.
            // Even so, this will just result in a minor memory leak
            // preventing the module from being GC'ed,
            // since subinterpreters aren't a concern.
            #[cfg(not(Py_3_10))]
            flags: Py_TPFLAGS_DEFAULT as _,
            slots: unsafe { $slots as *const [_] as *mut _ },
        };
    };
}

// FUTURE: a more efficient way for specific cases?
pub(crate) const fn hashmask(hash: Py_hash_t) -> Py_hash_t {
    match hash {
        -1 => -2,
        x => x,
    }
}

#[inline]
pub(crate) unsafe fn call1(func: *mut PyObject, arg: *mut PyObject) -> PyReturn {
    PyObject_CallOneArg(func, arg).as_result()
}

#[inline]
pub(crate) unsafe fn methcall1(slf: *mut PyObject, name: &str, arg: *mut PyObject) -> PyReturn {
    PyObject_CallMethodOneArg(slf, steal!(name.to_py()?), arg).as_result()
}

#[inline]
pub(crate) unsafe fn methcall0(slf: *mut PyObject, name: &str) -> PyReturn {
    PyObject_CallMethodNoArgs(slf, steal!(name.to_py()?)).as_result()
}

#[inline]
fn ptr_eq(a: *mut PyObject, b: *mut PyObject) -> bool {
    a == b
}

#[inline]
fn value_eq(a: *mut PyObject, b: *mut PyObject) -> bool {
    unsafe { PyObject_RichCompareBool(a, b, Py_EQ) == 1 }
}

pub(crate) struct DictItems {
    dict: *mut PyObject,
    pos: Py_ssize_t,
}

impl DictItems {
    pub(crate) fn new_unchecked(dict: *mut PyObject) -> Self {
        debug_assert!(!dict.is_null() && unsafe { PyDict_Size(dict) > 0 });
        DictItems { dict, pos: 0 }
    }
}

impl Iterator for DictItems {
    type Item = (*mut PyObject, *mut PyObject);

    fn next(&mut self) -> Option<Self::Item> {
        let mut key = NULL();
        let mut value = NULL();
        (unsafe { PyDict_Next(self.dict, &mut self.pos, &mut key, &mut value) } != 0)
            .then_some((key, value))
    }
}

#[inline]
pub(crate) unsafe fn handle_kwargs<F, K>(fname: &str, kwargs: K, mut handler: F) -> PyResult<()>
where
    F: FnMut(
        *mut PyObject,
        *mut PyObject,
        fn(*mut PyObject, *mut PyObject) -> bool,
    ) -> PyResult<bool>,
    K: IntoIterator<Item = (*mut PyObject, *mut PyObject)>,
{
    for (key, value) in kwargs {
        // First we try to match on pointer equality.
        // This is actually the common case, as static strings are interned.
        // In the rare case they aren't, we fall back to value comparison.
        // Doing it this way is faster than always doing value comparison outright.
        if !handler(key, value, ptr_eq)? && !handler(key, value, value_eq)? {
            return Err(type_err!(
                "{}() got an unexpected keyword argument: {}",
                fname,
                key.repr()
            ));
        }
    }
    Ok(())
}

#[inline]
#[allow(dead_code)]
unsafe fn getattr_tzinfo(dt: *mut PyObject) -> *mut PyObject {
    let tzinfo = PyObject_GetAttrString(dt, c"tzinfo".as_ptr());
    // To keep things consistent with the Py3.10 version,
    // we need to decref it, turning it into a borrowed reference.
    // We can assume the parent datetime keeps it alive.
    Py_DECREF(tzinfo);
    tzinfo
}

#[inline]
pub(crate) unsafe fn get_dt_tzinfo(dt: *mut PyObject) -> *mut PyObject {
    #[cfg(Py_3_10)]
    {
        PyDateTime_DATE_GET_TZINFO(dt)
    }
    #[cfg(not(Py_3_10))]
    {
        getattr_tzinfo(dt)
    }
}

#[inline]
pub(crate) unsafe fn get_time_tzinfo(dt: *mut PyObject) -> *mut PyObject {
    #[cfg(Py_3_10)]
    {
        PyDateTime_TIME_GET_TZINFO(dt)
    }
    #[cfg(not(Py_3_10))]
    {
        getattr_tzinfo(dt)
    }
}

// from stackoverflow.com/questions/5889238
#[cfg(target_pointer_width = "64")]
#[inline]
pub(crate) const fn hash_combine(lhs: Py_hash_t, rhs: Py_hash_t) -> Py_hash_t {
    lhs ^ (rhs
        .wrapping_add(0x517cc1b727220a95)
        .wrapping_add(lhs << 6)
        .wrapping_add(lhs >> 2))
}

#[cfg(target_pointer_width = "32")]
#[inline]
pub(crate) const fn hash_combine(lhs: Py_hash_t, rhs: Py_hash_t) -> Py_hash_t {
    lhs ^ (rhs
        .wrapping_add(-0x61c88647)
        .wrapping_add(lhs << 6)
        .wrapping_add(lhs >> 2))
}

pub(crate) static S_PER_DAY: i32 = 86_400;
pub(crate) static NS_PER_DAY: i128 = 86_400 * 1_000_000_000;

#[allow(unused_imports)]
pub(crate) use {
    cstr, defer_decref, getter, method, method_kwargs, method_vararg, pack, py_err, slotmethod,
    steal, type_err, type_spec, unpack_one, value_err,
};
