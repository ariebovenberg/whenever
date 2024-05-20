use core::ffi::c_long;
use core::mem;
use pyo3_ffi::*;

use crate::date::Date;
use crate::time::Time;

macro_rules! c_str(
    ($s:expr) => {{
        use core::ffi::c_char;
        concat!($s, "\0").as_ptr().cast::<c_char>()
    }};
);

macro_rules! py_error(
    () => {
        PyErrOccurred()
    };
    ($exc:expr, $msg:literal) => {{
        use crate::common::c_str;
        PyErr_SetString($exc, c_str!($msg));
        PyErrOccurred()
    }};
    ($exc:expr, $msg:literal, $($args:expr),*) => {{
        use crate::common::c_str;
        PyErr_Format($exc, c_str!($msg), $($args),*);
        PyErrOccurred()
    }};
);

macro_rules! value_error(
    ($msg:literal) => {
        py_error!(PyExc_ValueError, $msg)
    };
    ($msg:literal, $($args:expr),*) => {
        py_error!(PyExc_ValueError, $msg, $($args),*)
    };
);

macro_rules! type_error(
    ($msg:literal) => {
        py_error!(PyExc_TypeError, $msg)
    };
    ($msg:literal, $($args:expr),*) => {
        py_error!(PyExc_TypeError, $msg, $($args),*)
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
            ml_doc: c_str!($doc),
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
            ml_name: c_str!($name),
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
            ml_doc: c_str!($doc),
        }
    };
);

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
            ml_name: c_str!($name),
            ml_meth: PyMethodDefPointer {
                PyCMethod: {
                    unsafe extern "C" fn _wrap(
                        slf: *mut PyObject,
                        cls: *mut PyTypeObject,
                        args_raw: *const *mut PyObject,
                        nargsf: Py_ssize_t,
                        kwnames_raw: *mut PyObject,
                    ) -> *mut PyObject {
                        let nargs = PyVectorcall_NARGS(nargsf as usize);
                        let args = std::slice::from_raw_parts(args_raw, nargs as usize);
                        let kwargs = if kwnames_raw.is_null() {
                            Vec::with_capacity(0)
                        } else {
                            let mut v = Vec::with_capacity(PyTuple_GET_SIZE(kwnames_raw) as usize);
                            for i in 0..PyTuple_GET_SIZE(kwnames_raw) {
                                v.push((
                                     PyTuple_GET_ITEM(kwnames_raw, i),
                                     *args_raw.offset(nargs + i as isize)
                                ));
                            }
                            v
                        };
                        match $meth(slf, cls, args, &kwargs) {
                            Ok(x) => x as *mut PyObject,
                            Err(PyErrOccurred()) => core::ptr::null_mut(),
                        }
                    }
                    _wrap
                },
            },
            ml_flags: $flags | METH_METHOD | METH_FASTCALL | METH_KEYWORDS,
            ml_doc: c_str!($doc),
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
            name: c_str!($name),
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
            doc: c_str!($doc),
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

macro_rules! defer_decref(
    ($name:ident) => {
        let _deferred = DecrefOnDrop($name);
    };
);

// Apply this on arguments to have them decref'd after the call
// It has the same effect as if the call would 'steal' the reference
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
pub(crate) type PyResult<T> = Result<T, PyErrOccurred>;
pub(crate) type PyReturn = PyResult<&'static mut PyObject>;
pub(crate) trait PyResultExt<T> {
    // a version of `unwrap_or` that properly unsets the Python error indicator
    // XXX: There's nothing preventing usage of `unwrap_or`, which
    // would not unset the Python error indicator!
    unsafe fn try_except(self, value: T) -> T;
}
impl<T> PyResultExt<T> for PyResult<T> {
    unsafe fn try_except(self, value: T) -> T {
        match self {
            Ok(x) => x,
            Err(_) => {
                PyErr_Clear();
                value
            }
        }
    }
}

pub(crate) trait PyObjectExt {
    #[allow(clippy::wrong_self_convention)]
    unsafe fn as_result<'a>(self) -> PyResult<&'a mut PyObject>;
    #[allow(clippy::wrong_self_convention)]
    unsafe fn is_int(self) -> bool;
    // FUTURE: unchecked versions of these in case we know the type
    unsafe fn to_bytes<'a>(self) -> PyResult<Option<&'a [u8]>>;
    unsafe fn to_utf8<'a>(self) -> PyResult<Option<&'a [u8]>>;
    unsafe fn to_str<'a>(self) -> PyResult<Option<&'a str>>;
    unsafe fn to_long(self) -> PyResult<Option<c_long>>;
    unsafe fn to_i64(self) -> PyResult<Option<i64>>;
    unsafe fn to_i128(self) -> PyResult<Option<i128>>;
    unsafe fn to_f64(self) -> PyResult<Option<f64>>;
}

impl PyObjectExt for *mut PyObject {
    unsafe fn as_result<'a>(self) -> PyResult<&'a mut PyObject> {
        self.as_mut().ok_or(PyErrOccurred())
    }
    unsafe fn is_int(self) -> bool {
        PyLong_Check(self) != 0
    }

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

    unsafe fn to_str<'a>(self) -> PyResult<Option<&'a str>> {
        match self.to_utf8()? {
            Some(s) => Ok(Some(std::str::from_utf8_unchecked(s))),
            None => Ok(None),
        }
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
            Err(py_error!(
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
}

pub(crate) trait ToPy {
    unsafe fn to_py(self) -> PyReturn;
}

impl ToPy for bool {
    unsafe fn to_py(self) -> PyReturn {
        // TODO: refcounts?
        match self {
            true => Ok(Py_True().as_mut().unwrap()),
            false => Ok(Py_False().as_mut().unwrap()),
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

// TODO: remove
// Used for debugging--OK if not used
#[allow(unused_macros)]
macro_rules! print_repr {
    ($e:expr) => {{
        let s = pystr_to_utf8!(py_try!(PyObject_Repr($e)), "Expected a string");
        println!("{:?}", std::str::from_utf8_unchecked(s));
    }};
}

pub(crate) unsafe fn identity1(slf: *mut PyObject) -> PyReturn {
    Ok(newref(slf))
}

pub(crate) unsafe fn identity2(slf: &'static mut PyObject, _: &mut PyObject) -> PyReturn {
    Ok(newref(slf))
}

pub(crate) unsafe fn newref<'a>(obj: *mut PyObject) -> &'a mut PyObject {
    Py_INCREF(obj);
    obj.as_mut().unwrap()
}

pub(crate) unsafe fn offset_from_py_dt(dt: *mut PyObject) -> PyResult<i32> {
    // OPTIMIZE: is calling ZoneInfo.utcoffset() faster?
    let delta = PyObject_CallMethodNoArgs(dt, steal!("utcoffset".to_py()?)).as_result()?;
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
    let aware = PyObject_CallMethodNoArgs(naive, steal!("astimezone".to_py()?)).as_result()?;
    defer_decref!(aware);
    let kwargs = PyDict_New().as_result()?;
    defer_decref!(kwargs);
    if PyDict_SetItemString(kwargs, c_str!("tzinfo"), Py_None()) == -1 {
        return Err(PyErrOccurred());
    }
    let shifted_naive = PyObject_Call(
        PyObject_GetAttrString(aware, c_str!("replace")).as_result()?,
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
    pub(crate) unsafe fn for_localsystem(
        py_api: &PyDateTime_CAPI,
        date: Date,
        time: Time,
    ) -> PyResult<OffsetResult> {
        let (offset0, shifted) = local_offset(date, time, 0, py_api)?;
        let (offset1, _) = local_offset(date, time, 1, py_api)?;
        Ok(if offset0 == offset1 {
            Self::Unambiguous(offset0)
        } else if shifted {
            Self::Gap(offset1, offset0)
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
}

#[derive(Debug, Copy, Clone, PartialEq, Eq)]
pub(crate) enum Ambiguity {
    Fold,
    Gap,
}

pub(crate) unsafe extern "C" fn dealloc(slf: *mut PyObject) {
    let tp_free = PyType_GetSlot(Py_TYPE(slf), Py_tp_free);
    debug_assert_ne!(tp_free, core::ptr::null_mut());
    let f: freefunc = std::mem::transmute(tp_free);
    f(slf.cast());
}

// FUTURE: a more efficient way for specific cases?
pub(crate) const fn hashmask(hash: Py_hash_t) -> Py_hash_t {
    match hash {
        -1 => -2,
        x => x,
    }
}

#[allow(unused_imports)]
pub(crate) use {
    c_str, defer_decref, get_digit, getter, method, method_kwargs, method_vararg, pack, print_repr,
    py_error, slotmethod, steal, type_error, unpack_one, value_error,
};