use crate::pymodule::State;
use core::{
    ffi::{c_long, c_void, CStr},
    mem::{self, ManuallyDrop},
    ptr::null_mut as NULL,
};
use pyo3_ffi::*;
use std::{fmt::Debug, ptr::NonNull};

// We use `Result` to implement Python's error handling.
// Note that Python's error handling doesn't map exactly onto Rust's `Result` type,
// The most important difference being that Python's error handling
// is based on a global error indicator.
// This means that some `Result` functionality will not behave as expected.
// However, this is a price we can pay in exchange for the convenience
// of the `?` operator.
#[derive(Debug, Copy, Clone, PartialEq, Eq, PartialOrd, Ord)]
pub(crate) struct PyErrMarker(); // sentinel that the Python error indicator is set

pub(crate) type PyResult<T> = Result<T, PyErrMarker>;
pub(crate) type PyReturn = PyResult<Owned<PyObj>>;

pub(crate) trait PyObjectExt {
    fn rust_owned(self) -> PyResult<Owned<PyObj>>;
}

impl PyObjectExt for *mut PyObject {
    // TODO: name
    // TODO a version without checking for null
    fn rust_owned(self) -> PyResult<Owned<PyObj>> {
        PyObj::new(self).map(Owned::new)
    }
}

pub(crate) fn none() -> Owned<PyObj> {
    // SAFETY: Py_None is a valid pointer
    unsafe { PyObj::from_ptr_unchecked(Py_None()) }.newref()
}

// TODO a non-raw version?
pub(crate) fn raise<T, U: ToPy>(exc: *mut PyObject, msg: U) -> PyResult<T> {
    Err(exception(exc, msg))
}

pub(crate) fn exception<U: ToPy>(exc: *mut PyObject, msg: U) -> PyErrMarker {
    // If the message conversion fails, an error is set for us.
    // It's mostly likely a MemoryError.
    // TODO safety
    if let Ok(m) = msg.to_py2() {
        unsafe { PyErr_SetObject(exc, m.as_ptr()) }
    };
    PyErrMarker()
}

pub(crate) fn value_err<U: ToPy>(msg: U) -> PyErrMarker {
    exception(unsafe { PyExc_ValueError }, msg)
}

pub(crate) trait OptionExt<T> {
    fn ok_or_else_raise<F, M: ToPy>(self, exc: *mut PyObject, fmt: F) -> PyResult<T>
    where
        Self: Sized,
        F: FnOnce() -> M;

    fn ok_or_raise<U: ToPy>(self, exc: *mut PyObject, msg: U) -> PyResult<T>
    where
        Self: Sized,
    {
        self.ok_or_else_raise(exc, || msg)
    }

    fn ok_or_value_err<U: ToPy>(self, msg: U) -> PyResult<T>
    where
        Self: Sized,
    {
        self.ok_or_raise(unsafe { PyExc_ValueError }, msg)
    }

    fn ok_or_else_value_err<F, M: ToPy>(self, fmt: F) -> PyResult<T>
    where
        Self: Sized,
        F: FnOnce() -> M,
    {
        unsafe { self.ok_or_else_raise(PyExc_ValueError, fmt) }
    }

    fn ok_or_else_type_err<F, M: ToPy>(self, fmt: F) -> PyResult<T>
    where
        Self: Sized,
        F: FnOnce() -> M,
    {
        unsafe { self.ok_or_else_raise(PyExc_TypeError, fmt) }
    }

    fn ok_or_type_err<U: ToPy>(self, msg: U) -> PyResult<T>
    where
        Self: Sized,
    {
        self.ok_or_raise(unsafe { PyExc_TypeError }, msg)
    }
}

impl<T> OptionExt<T> for Option<T> {
    fn ok_or_else_raise<F, M: ToPy>(self, exc: *mut PyObject, fmt: F) -> PyResult<T>
    where
        F: FnOnce() -> M,
    {
        match self {
            Some(x) => Ok(x),
            None => raise(exc, fmt()),
        }
    }
}

pub(crate) fn raise_type_err<T, U: ToPy>(msg: U) -> PyResult<T> {
    raise(unsafe { PyExc_TypeError }, msg)
}

pub(crate) fn raise_value_err<T, U: ToPy>(msg: U) -> PyResult<T> {
    raise(unsafe { PyExc_ValueError }, msg)
}

pub(crate) trait FromPy: Sized {
    // TODO: remove
    unsafe fn from_py_ptr_unchecked(ptr: *mut PyObject) -> Self;
}

// TODO: remove
impl<T: PyWrapped> FromPy for T {
    unsafe fn from_py_ptr_unchecked(ptr: *mut PyObject) -> T {
        T::extract(ptr)
    }
}

impl FromPy for PyObj {
    unsafe fn from_py_ptr_unchecked(ptr: *mut PyObject) -> PyObj {
        PyObj::from_ptr_unchecked(ptr)
    }
}

pub(crate) trait ToPy: Sized {
    // TODO name
    fn to_py2(self) -> PyReturn;
}

impl ToPy for bool {
    fn to_py2(self) -> PyReturn {
        Ok(unsafe {
            PyObj::from_ptr_unchecked(match self {
                true => Py_True(),
                false => Py_False(),
            })
        }
        .newref())
    }
}

impl ToPy for i128 {
    fn to_py2(self) -> PyReturn {
        // Yes, this is a private API, but it's the only way to create a 128-bit integer
        // on Python < 3.13. Other libraries do this too.
        unsafe {
            _PyLong_FromByteArray(
                self.to_le_bytes().as_ptr().cast(),
                mem::size_of::<i128>(),
                1,
                1,
            )
        }
        .rust_owned()
    }
}

impl ToPy for i64 {
    fn to_py2(self) -> PyReturn {
        unsafe { PyLong_FromLongLong(self) }.rust_owned()
    }
}

impl ToPy for i32 {
    fn to_py2(self) -> PyReturn {
        unsafe { PyLong_FromLong(self.into()) }.rust_owned()
    }
}

impl ToPy for f64 {
    fn to_py2(self) -> PyReturn {
        unsafe { PyFloat_FromDouble(self) }.rust_owned()
    }
}

impl ToPy for u32 {
    fn to_py2(self) -> PyReturn {
        unsafe { PyLong_FromUnsignedLong(self.into()) }.rust_owned()
    }
}

impl ToPy for u16 {
    fn to_py2(self) -> PyReturn {
        unsafe { PyLong_FromUnsignedLong(self.into()) }.rust_owned()
    }
}

impl ToPy for u8 {
    fn to_py2(self) -> PyReturn {
        unsafe { PyLong_FromUnsignedLong(self.into()) }.rust_owned()
    }
}

impl ToPy for String {
    fn to_py2(self) -> PyReturn {
        unsafe { PyUnicode_FromStringAndSize(self.as_ptr().cast(), self.len() as _) }.rust_owned()
    }
}

impl ToPy for &str {
    fn to_py2(self) -> PyReturn {
        unsafe { PyUnicode_FromStringAndSize(self.as_ptr().cast(), self.len() as _) }.rust_owned()
    }
}

impl ToPy for &[u8] {
    fn to_py2(self) -> PyReturn {
        unsafe { PyBytes_FromStringAndSize(self.as_ptr().cast(), self.len() as _) }.rust_owned()
    }
}

// TODO name
pub(crate) fn identity1(_: PyType, slf: PyObj) -> Owned<PyObj> {
    slf.newref()
}

pub(crate) fn __copy__(_: PyType, slf: PyObj) -> Owned<PyObj> {
    slf.newref()
}

pub(crate) fn __deepcopy__(_: PyType, slf: PyObj, _: PyObj) -> Owned<PyObj> {
    slf.newref()
}

#[derive(Debug)]
pub(crate) struct LazyImport {
    module: &'static CStr,
    name: &'static CStr,
    obj: std::cell::UnsafeCell<*mut PyObject>,
}

impl LazyImport {
    pub(crate) fn new(module: &'static CStr, name: &'static CStr) -> Self {
        Self {
            module,
            name,
            obj: std::cell::UnsafeCell::new(NULL()),
        }
    }

    // TODO
    /// Get the object, importing it if necessary.
    pub(crate) fn get2(&self) -> PyResult<PyObj> {
        unsafe {
            let obj = *self.obj.get();
            if obj.is_null() {
                let t = import(self.module)?.getattr(self.name)?.into_py();
                self.obj.get().write(t.as_ptr());
                Ok(t)
            } else {
                Ok(PyObj::from_ptr_unchecked(obj))
            }
        }
    }

    /// Ensure Python's GC can traverse this object.
    pub(crate) unsafe fn traverse(&self, visit: visitproc, arg: *mut c_void) {
        let obj = *self.obj.get();
        if !obj.is_null() {
            visit(obj, arg);
        }
    }
}

impl Drop for LazyImport {
    fn drop(&mut self) {
        unsafe {
            let obj = self.obj.get();
            if !(*obj).is_null() {
                Py_CLEAR(obj);
            }
        }
    }
}

// TODO
#[inline]
fn ptr_eq2(a: PyObj, b: PyObj) -> bool {
    a == b
}

// TODO
#[inline]
fn value_eq2(a: PyObj, b: PyObj) -> bool {
    unsafe { PyObject_RichCompareBool(a.as_ptr(), b.as_ptr(), Py_EQ) == 1 }
}

pub(crate) fn handle_kwargs2<F, K>(fname: &str, kwargs: K, mut handler: F) -> PyResult<()>
where
    F: FnMut(PyObj, PyObj, fn(PyObj, PyObj) -> bool) -> PyResult<bool>,
    K: IntoIterator<Item = (PyObj, PyObj)>,
{
    for (key, value) in kwargs {
        // First we try to match *all kwargs* on pointer equality.
        // This is actually the common case, as static strings are interned.
        // In the rare case they aren't, we fall back to value comparison.
        // Doing it this way is faster than always doing value comparison outright.
        if !handler(key, value, ptr_eq2)? && !handler(key, value, value_eq2)? {
            return raise_type_err(format!(
                "{}() got an unexpected keyword argument: {}",
                fname,
                key.repr()
            ));
        }
    }
    Ok(())
}

// TODO: is this actually worth it?
pub(crate) fn match_interned_str2<T, F>(name: &str, value: PyObj, mut handler: F) -> PyResult<T>
where
    F: FnMut(PyObj, fn(PyObj, PyObj) -> bool) -> Option<T>,
{
    handler(value, ptr_eq2)
        .or_else(|| handler(value, value_eq2))
        .ok_or_else_value_err(|| format!("Invalid value for {}: {}", name, value.repr()))
}

// FUTURE: a more efficient way for specific cases?
pub(crate) const fn hashmask(hash: Py_hash_t) -> Py_hash_t {
    if hash == -1 {
        return -2;
    }
    hash
}

// fast, safe way to combine hash values, from stackoverflow.com/questions/5889238
#[inline]
pub(crate) const fn hash_combine(lhs: Py_hash_t, rhs: Py_hash_t) -> Py_hash_t {
    #[cfg(target_pointer_width = "64")]
    {
        lhs ^ (rhs
            .wrapping_add(0x517cc1b727220a95)
            .wrapping_add(lhs << 6)
            .wrapping_add(lhs >> 2))
    }
    #[cfg(target_pointer_width = "32")]
    {
        lhs ^ (rhs
            .wrapping_add(-0x61c88647)
            .wrapping_add(lhs << 6)
            .wrapping_add(lhs >> 2))
    }
}

macro_rules! parse_args_kwargs2 {
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

/// Pack various types into a byte array. Used for pickling.
macro_rules! pack {
    [$x:expr, $($xs:expr),*] => {{
        // OPTIMIZE: use Vec::with_capacity, or a fixed-size array
        // since we know the size at compile time
        let mut result = Vec::new();
        result.extend_from_slice(&$x.to_le_bytes());
        $(
            result.extend_from_slice(&$xs.to_le_bytes());
        )*
        result
    }}
}

/// Unpack a single value from a byte array. Used for unpickling.
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

pub(crate) trait IntoPyPtr {
    fn into_py_ptr(self) -> *mut PyObject;
}

impl IntoPyPtr for *mut PyObject {
    fn into_py_ptr(self) -> *mut PyObject {
        self
    }
}

impl<T: PyBase> IntoPyPtr for PyResult<Owned<T>> {
    fn into_py_ptr(self) -> *mut PyObject {
        match self.map(|x| x.into_py()) {
            Ok(x) => x.as_ptr(),
            Err(_) => NULL(),
        }
    }
}

impl<T: PyBase> IntoPyPtr for Owned<T> {
    fn into_py_ptr(self) -> *mut PyObject {
        self.into_py().as_ptr()
    }
}

// Core Python object wrapper
#[repr(transparent)] // to cast to/from PyObject
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub(crate) struct PyObj {
    inner: NonNull<PyObject>,
}

impl PyObj {
    pub(crate) fn new(ptr: *mut PyObject) -> PyResult<Self> {
        match NonNull::new(ptr) {
            Some(x) => Ok(Self { inner: x }),
            None => Err(PyErrMarker()),
        }
    }

    pub(crate) fn wrap(inner: NonNull<PyObject>) -> Self {
        Self { inner }
    }

    pub(crate) fn incref(&self) {
        unsafe { Py_INCREF(self.inner.as_ptr()) }
    }

    pub(crate) fn as_ptr(&self) -> *mut PyObject {
        self.inner.as_ptr()
    }

    // TODO name
    pub(crate) fn class(&self) -> PyType {
        unsafe { PyType::from_ptr_unchecked(Py_TYPE(self.inner.as_ptr()).cast()) }
    }

    // TODO name
    // TODO remove
    pub(crate) unsafe fn extract_unchecked<T: FromPy>(&self) -> T {
        unsafe { T::from_py_ptr_unchecked(self.as_ptr()) }
    }

    pub(crate) unsafe fn assume_heaptype<T: PyWrapped>(&self) -> (HeapType<T>, T) {
        (
            unsafe { HeapType::from_ptr_unchecked(self.class().as_ptr()) },
            unsafe { T::extract(self.inner.as_ptr()) },
        )
    }

    pub(crate) fn extract3<T: PyWrapped>(&self, t: HeapType<T>) -> Option<T> {
        (self.class() == t._inner).then(
            // SAFETY: we've just checked the type, so this is safe
            || unsafe { T::extract(self.inner.as_ptr()) },
        )
    }

    pub(crate) fn repr(&self) -> String {
        let Ok(repr_obj) = unsafe { PyObject_Repr(self.as_ptr()) }.rust_owned() else {
            // i.e. repr() raised an exception
            unsafe { PyErr_Clear() };
            return "<repr() failed>".to_string();
        };
        let Some(py_str) = repr_obj.cast::<PyStr>() else {
            // i.e. repr() didn't return a string
            return "<repr() failed>".to_string();
        };
        let Ok(utf8) = py_str.as_utf8() else {
            // i.e. repr() returned a non-UTF-8 string
            unsafe { PyErr_Clear() };
            return "<repr() failed>".to_string();
        };
        unsafe { std::str::from_utf8_unchecked(utf8) }.to_string()
    }

    pub(crate) fn cast<T: PyStaticType>(self) -> Option<T> {
        T::isinstance_exact(self)
            .then_some(unsafe { T::from_ptr_unchecked(self.as_py_obj().inner.as_ptr()) })
    }

    pub(crate) fn cast_allow_subclass<T: PyStaticType>(self) -> Option<T> {
        T::isinstance(self)
            .then_some(unsafe { T::from_ptr_unchecked(self.as_py_obj().inner.as_ptr()) })
    }

    // TODO: do we need the extra method or just unwrap above?
    pub(crate) unsafe fn cast_unchecked<T: PyBase>(self) -> T {
        unsafe { T::from_ptr_unchecked(self.as_py_obj().inner.as_ptr()) }
    }

    pub(crate) fn is_none(&self) -> bool {
        self.as_ptr() == unsafe { Py_None() }
    }
}

impl PyBase for PyObj {
    fn as_py_obj(&self) -> PyObj {
        *self
    }

    // TODO: unify with from_py_ptr_unchecked
    unsafe fn from_ptr_unchecked(ptr: *mut PyObject) -> Self {
        Self {
            inner: NonNull::new_unchecked(ptr),
        }
    }
}

impl PyStaticType for PyObj {
    fn isinstance_exact(_: impl PyBase) -> bool {
        true
    }

    fn isinstance(_: impl PyBase) -> bool {
        true
    }
}

pub(crate) trait PyStaticType: PyBase {
    fn isinstance_exact(obj: impl PyBase) -> bool;
    fn isinstance(obj: impl PyBase) -> bool;
}

// Define a trait for common Python object behavior
pub(crate) trait PyBase: Copy {
    fn as_py_obj(&self) -> PyObj;

    fn incref(&self) {
        self.as_py_obj().incref();
    }

    fn newref(self) -> Owned<Self> {
        self.incref();
        Owned::new(self)
    }

    fn as_ptr(&self) -> *mut PyObject {
        self.as_py_obj().as_ptr()
    }

    fn repr(&self) -> String {
        self.as_py_obj().repr()
    }

    /// Get the attribute of the object.
    fn getattr(&self, name: &CStr) -> PyReturn {
        unsafe { PyObject_GetAttrString(self.as_ptr(), name.as_ptr()) }.rust_owned()
    }

    /// call __getitem__ of the object
    fn getitem(&self, key: PyObj) -> PyReturn {
        unsafe { PyObject_GetItem(self.as_ptr(), key.as_ptr()) }.rust_owned()
    }

    /// Get the attribute of the object.
    fn setattr(&self, name: &CStr, v: PyObj) -> PyResult<()> {
        if unsafe { PyObject_SetAttrString(self.as_ptr(), name.as_ptr(), v.as_ptr()) } == 0 {
            Ok(())
        } else {
            Err(PyErrMarker())
        }
    }

    /// Call the object with one argument.
    fn call1(&self, arg: impl PyBase) -> PyReturn {
        unsafe { PyObject_CallOneArg(self.as_ptr(), arg.as_ptr()) }.rust_owned()
    }

    /// Call the object with no arguments.
    fn call0(&self) -> PyReturn {
        unsafe { PyObject_CallNoArgs(self.as_ptr()) }.rust_owned()
    }

    /// Call the object with a tuple of arguments.
    fn call(&self, args: PyTuple) -> PyReturn {
        // OPTIMIZE: use vectorcall?
        unsafe { PyObject_Call(self.as_ptr(), args.as_ptr(), NULL()) }.rust_owned()
    }

    fn py_eq(&self, other: impl PyBase) -> PyResult<bool> {
        // SAFETY: calling CPython API with valid arguments
        match unsafe { PyObject_RichCompareBool(self.as_ptr(), other.as_ptr(), Py_EQ) } {
            1 => Ok(true),
            0 => Ok(false),
            _ => Err(PyErrMarker()),
        }
    }

    fn is_true(&self) -> bool {
        unsafe { self.as_ptr() == Py_True() }
    }

    // TODO: nonnull variant?
    unsafe fn from_ptr_unchecked(ptr: *mut PyObject) -> Self;
}

#[derive(Debug, Clone, Copy)]
pub(crate) struct PyDate {
    obj: PyObj,
}

impl PyDate {
    pub fn year(&self) -> i32 {
        unsafe { PyDateTime_GET_YEAR(self.obj.as_ptr()) }
    }

    pub fn month(&self) -> i32 {
        unsafe { PyDateTime_GET_MONTH(self.obj.as_ptr()) }
    }

    pub fn day(&self) -> i32 {
        unsafe { PyDateTime_GET_DAY(self.obj.as_ptr()) }
    }
}

impl PyBase for PyDate {
    fn as_py_obj(&self) -> PyObj {
        self.obj
    }

    unsafe fn from_ptr_unchecked(ptr: *mut PyObject) -> Self {
        Self {
            obj: PyObj::from_ptr_unchecked(ptr),
        }
    }
}

impl PyStaticType for PyDate {
    fn isinstance_exact(obj: impl PyBase) -> bool {
        unsafe { PyDate_CheckExact(obj.as_ptr()) != 0 }
    }

    fn isinstance(obj: impl PyBase) -> bool {
        unsafe { PyDate_Check(obj.as_ptr()) != 0 }
    }
}

#[derive(Debug, Clone, Copy)]
pub(crate) struct PyDateTime {
    obj: PyObj,
}

impl PyDateTime {
    pub(crate) fn year(&self) -> i32 {
        unsafe { PyDateTime_GET_YEAR(self.obj.as_ptr()) }
    }

    pub(crate) fn month(&self) -> i32 {
        unsafe { PyDateTime_GET_MONTH(self.obj.as_ptr()) }
    }

    pub(crate) fn day(&self) -> i32 {
        unsafe { PyDateTime_GET_DAY(self.obj.as_ptr()) }
    }

    pub(crate) fn hour(&self) -> i32 {
        unsafe { PyDateTime_DATE_GET_HOUR(self.obj.as_ptr()) }
    }

    pub(crate) fn minute(&self) -> i32 {
        unsafe { PyDateTime_DATE_GET_MINUTE(self.obj.as_ptr()) }
    }

    pub(crate) fn second(&self) -> i32 {
        unsafe { PyDateTime_DATE_GET_SECOND(self.obj.as_ptr()) }
    }

    pub(crate) fn microsecond(&self) -> i32 {
        unsafe { PyDateTime_DATE_GET_MICROSECOND(self.obj.as_ptr()) }
    }

    /// Get a borrowed reference to the tzinfo object.
    pub(crate) fn tzinfo(&self) -> PyObj {
        // SAFETY: calling CPython API with valid arguments
        unsafe {
            PyObj::from_ptr_unchecked({
                #[cfg(Py_3_10)]
                {
                    PyDateTime_DATE_GET_TZINFO(self.as_ptr())
                }
                #[cfg(not(Py_3_10))]
                {
                    // NOTE: casting to a pointer and back will ensure
                    // the reference is dropped (it's kept alive by the
                    // PyDateTime object)
                    dt.getattr(c"tzinfo")?.as_ptr()
                }
            })
        }
    }

    pub(crate) fn date(&self) -> PyDate {
        // SAFETY: Date has the same layout
        unsafe { PyDate::from_ptr_unchecked(self.obj.as_ptr()) }
    }

    pub(crate) fn utcoffset(&self) -> PyReturn {
        self.getattr(c"utcoffset")?.call0()
    }
}

impl PyBase for PyDateTime {
    fn as_py_obj(&self) -> PyObj {
        self.obj
    }

    unsafe fn from_ptr_unchecked(ptr: *mut PyObject) -> Self {
        Self {
            obj: PyObj::from_ptr_unchecked(ptr),
        }
    }
}

impl PyStaticType for PyDateTime {
    fn isinstance_exact(obj: impl PyBase) -> bool {
        unsafe { PyDateTime_CheckExact(obj.as_ptr()) != 0 }
    }

    fn isinstance(obj: impl PyBase) -> bool {
        unsafe { PyDateTime_Check(obj.as_ptr()) != 0 }
    }
}

#[derive(Debug, Clone, Copy)]
pub(crate) struct PyTimeDelta {
    obj: PyObj,
}

impl PyTimeDelta {
    pub(crate) fn days(&self) -> i32 {
        unsafe { PyDateTime_DELTA_GET_DAYS(self.obj.as_ptr()) }
    }

    pub(crate) fn seconds(&self) -> i32 {
        unsafe { PyDateTime_DELTA_GET_SECONDS(self.obj.as_ptr()) }
    }

    pub(crate) fn microseconds(&self) -> i32 {
        unsafe { PyDateTime_DELTA_GET_MICROSECONDS(self.obj.as_ptr()) }
    }
}

impl PyBase for PyTimeDelta {
    fn as_py_obj(&self) -> PyObj {
        self.obj
    }

    unsafe fn from_ptr_unchecked(ptr: *mut PyObject) -> Self {
        Self {
            obj: PyObj::from_ptr_unchecked(ptr),
        }
    }
}

impl PyStaticType for PyTimeDelta {
    fn isinstance_exact(obj: impl PyBase) -> bool {
        unsafe { PyDelta_CheckExact(obj.as_ptr()) != 0 }
    }

    fn isinstance(obj: impl PyBase) -> bool {
        unsafe { PyDelta_Check(obj.as_ptr()) != 0 }
    }
}

#[derive(Debug, Clone, Copy)]
pub(crate) struct PyTime {
    obj: PyObj,
}

impl PyTime {
    pub(crate) fn hour(&self) -> i32 {
        unsafe { PyDateTime_TIME_GET_HOUR(self.obj.as_ptr()) }
    }

    pub(crate) fn minute(&self) -> i32 {
        unsafe { PyDateTime_TIME_GET_MINUTE(self.obj.as_ptr()) }
    }

    pub(crate) fn second(&self) -> i32 {
        unsafe { PyDateTime_TIME_GET_SECOND(self.obj.as_ptr()) }
    }

    pub(crate) fn microsecond(&self) -> i32 {
        unsafe { PyDateTime_TIME_GET_MICROSECOND(self.obj.as_ptr()) }
    }
}

impl PyBase for PyTime {
    fn as_py_obj(&self) -> PyObj {
        self.obj
    }

    unsafe fn from_ptr_unchecked(ptr: *mut PyObject) -> Self {
        Self {
            obj: PyObj::from_ptr_unchecked(ptr),
        }
    }
}

impl PyStaticType for PyTime {
    fn isinstance_exact(obj: impl PyBase) -> bool {
        unsafe { PyTime_CheckExact(obj.as_ptr()) != 0 }
    }

    fn isinstance(obj: impl PyBase) -> bool {
        unsafe { PyTime_Check(obj.as_ptr()) != 0 }
    }
}

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub(crate) struct PyType {
    obj: PyObj,
}

impl PyBase for PyType {
    fn as_py_obj(&self) -> PyObj {
        self.obj
    }

    // TODO: rename from_ptr unchecked
    unsafe fn from_ptr_unchecked(ptr: *mut PyObject) -> Self {
        Self {
            obj: PyObj::from_ptr_unchecked(ptr.cast()),
        }
    }
}

impl PyStaticType for PyType {
    fn isinstance_exact(obj: impl PyBase) -> bool {
        unsafe { PyType_CheckExact(obj.as_ptr()) != 0 }
    }
    fn isinstance(obj: impl PyBase) -> bool {
        unsafe { PyType_Check(obj.as_ptr()) != 0 }
    }
}

impl PyType {
    // TODO name
    pub(crate) fn are_both_whenever(&self, other: PyType) -> Option<&State> {
        // TODO: need to account for errors!
        let mod_a = unsafe { PyType_GetModule(self.as_ptr().cast()) };
        let mod_b = unsafe { PyType_GetModule(other.as_ptr().cast()) };
        (mod_a == mod_b).then(|| {
            // SAFETY: we just checked the pointers, so this is safe
            unsafe { State::for_mod(mod_a) }
        })
    }

    pub(crate) unsafe fn link_type<T: PyWrapped>(self) -> HeapType<T> {
        // SAFETY: we assume the pointer is valid and points to a PyType object
        unsafe { HeapType::from_ptr_unchecked(self.as_ptr()) }
    }
}

#[derive(Debug, Copy, Clone, PartialEq, Eq)]
pub(crate) struct HeapType<T: PyWrapped> {
    _inner: PyType,
    // TODO name
    layout: std::marker::PhantomData<T>,
}

impl<T: PyWrapped> HeapType<T> {
    // TODO: lifetime story
    pub(crate) fn state(&self) -> &'static State {
        // SAFETY: we assume the pointer is valid and points to a PyType object
        unsafe {
            PyType_GetModuleState(self._inner.as_ptr().cast())
                .cast::<State>()
                .as_ref()
                .unwrap()
        }
    }

    pub(crate) fn inner(&self) -> PyType {
        self._inner
    }
}

impl<T: PyWrapped> PyBase for HeapType<T> {
    fn as_py_obj(&self) -> PyObj {
        self._inner.as_py_obj()
    }

    unsafe fn from_ptr_unchecked(ptr: *mut PyObject) -> Self {
        Self {
            _inner: PyType::from_ptr_unchecked(ptr),
            layout: std::marker::PhantomData,
        }
    }
}

impl<T: PyWrapped> From<HeapType<T>> for PyType {
    fn from(t: HeapType<T>) -> Self {
        t._inner
    }
}

#[derive(Debug, Clone, Copy)]
pub(crate) struct PyStr {
    obj: PyObj,
}

impl PyStr {
    pub(crate) fn as_utf8(&self) -> PyResult<&[u8]> {
        let mut size = 0;
        let p = unsafe { PyUnicode_AsUTF8AndSize(self.as_ptr(), &mut size) };
        if p.is_null() {
            return Err(PyErrMarker());
        };
        Ok(unsafe { std::slice::from_raw_parts(p.cast::<u8>(), size as usize) })
    }

    pub(crate) fn as_str(&self) -> PyResult<&str> {
        let mut size = 0;
        let p = unsafe { PyUnicode_AsUTF8AndSize(self.as_ptr(), &mut size) };
        if p.is_null() {
            return Err(PyErrMarker());
        };
        Ok(unsafe {
            std::str::from_utf8_unchecked(std::slice::from_raw_parts(p.cast::<u8>(), size as usize))
        })
    }
}

impl PyBase for PyStr {
    fn as_py_obj(&self) -> PyObj {
        self.obj
    }

    unsafe fn from_ptr_unchecked(ptr: *mut PyObject) -> Self {
        Self {
            obj: PyObj::from_ptr_unchecked(ptr),
        }
    }
}

impl PyStaticType for PyStr {
    fn isinstance_exact(obj: impl PyBase) -> bool {
        unsafe { PyUnicode_CheckExact(obj.as_ptr()) != 0 }
    }

    fn isinstance(obj: impl PyBase) -> bool {
        unsafe { PyUnicode_Check(obj.as_ptr()) != 0 }
    }
}

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub(crate) struct PyDict {
    obj: PyObj,
}

impl PyBase for PyDict {
    fn as_py_obj(&self) -> PyObj {
        self.obj
    }

    unsafe fn from_ptr_unchecked(ptr: *mut PyObject) -> Self {
        Self {
            obj: PyObj::from_ptr_unchecked(ptr),
        }
    }
}

impl PyStaticType for PyDict {
    fn isinstance_exact(obj: impl PyBase) -> bool {
        unsafe { PyDict_CheckExact(obj.as_ptr()) != 0 }
    }

    fn isinstance(obj: impl PyBase) -> bool {
        unsafe { PyDict_Check(obj.as_ptr()) != 0 }
    }
}

impl PyDict {
    pub(crate) fn new() -> PyResult<Owned<PyDict>> {
        // SAFETY: PyDict_New() returns a new reference to a PyDict
        Ok(unsafe { PyDict_New().rust_owned()?.cast_unchecked() })
    }

    pub(crate) fn set_item_str(&self, key: &CStr, value: PyObj) -> PyResult<()> {
        if unsafe { PyDict_SetItemString(self.obj.as_ptr(), key.as_ptr(), value.as_ptr()) } == -1 {
            return Err(PyErrMarker());
        }
        Ok(())
    }

    pub(crate) fn len(&self) -> Py_ssize_t {
        unsafe { PyDict_Size(self.obj.as_ptr()) }
    }

    pub(crate) fn iteritems(&self) -> PyDictIterItems {
        PyDictIterItems {
            obj: self.obj.as_ptr(),
            pos: 0,
        }
    }
}

pub(crate) struct PyDictIterItems {
    obj: *mut PyObject,
    pos: Py_ssize_t,
}

impl Iterator for PyDictIterItems {
    type Item = (PyObj, PyObj);

    fn next(&mut self) -> Option<Self::Item> {
        let mut key = NULL();
        let mut value = NULL();
        (unsafe { PyDict_Next(self.obj, &mut self.pos, &mut key, &mut value) } != 0).then(
            || unsafe {
                (
                    PyObj::from_ptr_unchecked(key),
                    PyObj::from_ptr_unchecked(value),
                )
            },
        )
    }
}

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub(crate) struct PyTuple {
    obj: PyObj,
}

impl PyBase for PyTuple {
    fn as_py_obj(&self) -> PyObj {
        self.obj
    }

    unsafe fn from_ptr_unchecked(ptr: *mut PyObject) -> Self {
        Self {
            obj: PyObj::from_ptr_unchecked(ptr),
        }
    }
}

impl PyStaticType for PyTuple {
    fn isinstance_exact(obj: impl PyBase) -> bool {
        unsafe { PyTuple_CheckExact(obj.as_ptr()) != 0 }
    }

    fn isinstance(obj: impl PyBase) -> bool {
        unsafe { PyTuple_Check(obj.as_ptr()) != 0 }
    }
}

impl PyTuple {
    pub(crate) fn len(&self) -> Py_ssize_t {
        unsafe { PyTuple_GET_SIZE(self.obj.as_ptr()) }
    }

    pub(crate) fn iter(&self) -> PyTupleIter {
        PyTupleIter {
            obj: self.as_ptr(),
            index: 0,
            size: self.len(),
        }
    }
}

pub(crate) struct PyTupleIter {
    obj: *mut PyObject,
    index: Py_ssize_t,
    size: Py_ssize_t,
}

impl Iterator for PyTupleIter {
    type Item = PyObj;

    fn next(&mut self) -> Option<Self::Item> {
        if self.index >= self.size {
            return None;
        }
        let result = unsafe { PyObj::from_ptr_unchecked(PyTuple_GET_ITEM(self.obj, self.index)) };
        self.index += 1;
        Some(result)
    }
}

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub(crate) struct PyInt {
    obj: PyObj,
}

impl PyBase for PyInt {
    fn as_py_obj(&self) -> PyObj {
        self.obj
    }

    unsafe fn from_ptr_unchecked(ptr: *mut PyObject) -> Self {
        Self {
            obj: PyObj::from_ptr_unchecked(ptr),
        }
    }
}

impl PyStaticType for PyInt {
    fn isinstance_exact(obj: impl PyBase) -> bool {
        unsafe { PyLong_CheckExact(obj.as_ptr()) != 0 }
    }

    fn isinstance(obj: impl PyBase) -> bool {
        unsafe { PyLong_Check(obj.as_ptr()) != 0 }
    }
}

impl PyInt {
    pub(crate) fn to_long(self) -> PyResult<c_long> {
        match unsafe { PyLong_AsLong(self.as_ptr()) } {
            x if x != -1 || unsafe { PyErr_Occurred() }.is_null() => Ok(x),
            // The error message is set for us
            _ => Err(PyErrMarker()),
        }
    }

    pub(crate) fn to_i64(self) -> PyResult<c_long> {
        match unsafe { PyLong_AsLongLong(self.as_ptr()) } {
            x if x != -1 || unsafe { PyErr_Occurred() }.is_null() => Ok(x),
            // The error message is set for us
            _ => Err(PyErrMarker()),
        }
    }

    pub(crate) fn to_i128(self) -> PyResult<i128> {
        let mut bytes: [u8; 16] = [0; 16];
        // Yes, this is a private API, but it's the only way to get a 128-bit integer
        // on Python < 3.13. Other libraries do this too.
        if unsafe { _PyLong_AsByteArray(self.as_ptr().cast(), &mut bytes as *mut _, 16, 1, 1) } == 0
        {
            Ok(i128::from_le_bytes(bytes))
        } else {
            raise(
                unsafe { PyExc_OverflowError },
                "Python int too large to convert to i128",
            )
        }
    }
}

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub(crate) struct PyFloat {
    obj: PyObj,
}

impl PyBase for PyFloat {
    fn as_py_obj(&self) -> PyObj {
        self.obj
    }

    unsafe fn from_ptr_unchecked(ptr: *mut PyObject) -> Self {
        Self {
            obj: PyObj::from_ptr_unchecked(ptr),
        }
    }
}

impl PyStaticType for PyFloat {
    fn isinstance_exact(obj: impl PyBase) -> bool {
        unsafe { PyFloat_CheckExact(obj.as_ptr()) != 0 }
    }

    fn isinstance(obj: impl PyBase) -> bool {
        unsafe { PyFloat_Check(obj.as_ptr()) != 0 }
    }
}

impl PyFloat {
    pub(crate) fn to_f64(self) -> PyResult<f64> {
        match unsafe { PyFloat_AsDouble(self.as_ptr()) } {
            x if x != -1.0 || unsafe { PyErr_Occurred() }.is_null() => Ok(x),
            // The error message is set for us
            _ => Err(PyErrMarker()),
        }
    }
}

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub(crate) struct PyBytes {
    obj: PyObj,
}

impl PyBase for PyBytes {
    fn as_py_obj(&self) -> PyObj {
        self.obj
    }

    unsafe fn from_ptr_unchecked(ptr: *mut PyObject) -> Self {
        Self {
            obj: PyObj::from_ptr_unchecked(ptr),
        }
    }
}

impl PyStaticType for PyBytes {
    fn isinstance_exact(obj: impl PyBase) -> bool {
        unsafe { PyBytes_CheckExact(obj.as_ptr()) != 0 }
    }

    fn isinstance(obj: impl PyBase) -> bool {
        unsafe { PyBytes_Check(obj.as_ptr()) != 0 }
    }
}

impl PyBytes {
    // TODO rename as_slice?
    pub(crate) fn as_bytes(&self) -> PyResult<&[u8]> {
        let p = unsafe { PyBytes_AsString(self.as_ptr()) };
        // TODO: this check shouldn't be necessary, PyBytes_AS_STRING?
        // Also: PyBytes_GET_SIZE?
        if p.is_null() {
            return Err(PyErrMarker());
        };
        Ok(unsafe {
            std::slice::from_raw_parts(p.cast::<u8>(), PyBytes_Size(self.as_ptr()) as usize)
        })
    }
}

#[derive(Debug, Clone, Copy)]
pub(crate) struct PyModule {
    obj: PyObj,
}

impl PyBase for PyModule {
    fn as_py_obj(&self) -> PyObj {
        self.obj
    }

    unsafe fn from_ptr_unchecked(ptr: *mut PyObject) -> Self {
        Self {
            obj: PyObj::from_ptr_unchecked(ptr),
        }
    }
}

impl PyStaticType for PyModule {
    fn isinstance_exact(obj: impl PyBase) -> bool {
        unsafe { PyModule_CheckExact(obj.as_ptr()) != 0 }
    }

    fn isinstance(obj: impl PyBase) -> bool {
        unsafe { PyModule_Check(obj.as_ptr()) != 0 }
    }
}

impl PyModule {
    #[allow(clippy::mut_from_ref)]
    pub(crate) fn state(&self) -> &mut State {
        // SAFETY: calling CPython API with valid arguments
        unsafe { PyModule_GetState(self.as_ptr()).cast::<State>().as_mut() }.unwrap()
    }

    pub(crate) fn add_type(&self, cls: PyType) -> PyResult<()> {
        // SAFETY: calling CPython API with valid arguments
        if unsafe { PyModule_AddType(self.as_ptr(), cls.as_ptr().cast()) } == 0 {
            Ok(())
        } else {
            Err(PyErrMarker())
        }
    }
}

pub(crate) trait IntoPyTuple {
    fn into_pytuple(self) -> PyResult<Owned<PyTuple>>;
}

impl<T: PyBase> IntoPyTuple for (Owned<T>,) {
    fn into_pytuple(self) -> PyResult<Owned<PyTuple>> {
        let tuple = unsafe { PyTuple_New(1).rust_owned()?.cast_unchecked::<PyTuple>() };
        unsafe { PyTuple_SET_ITEM(tuple.as_ptr(), 0, self.0.into_py().as_ptr()) };
        Ok(tuple)
    }
}

impl<T: PyBase, U: PyBase> IntoPyTuple for (Owned<T>, Owned<U>) {
    fn into_pytuple(self) -> PyResult<Owned<PyTuple>> {
        let tuple = unsafe { PyTuple_New(2).rust_owned()?.cast_unchecked::<PyTuple>() };
        unsafe { PyTuple_SET_ITEM(tuple.as_ptr(), 0, self.0.into_py().as_ptr()) };
        unsafe { PyTuple_SET_ITEM(tuple.as_ptr(), 1, self.1.into_py().as_ptr()) };
        Ok(tuple)
    }
}

impl<T: PyBase, U: PyBase, V: PyBase> IntoPyTuple for (Owned<T>, Owned<U>, Owned<V>) {
    fn into_pytuple(self) -> PyResult<Owned<PyTuple>> {
        let tuple = unsafe { PyTuple_New(3).rust_owned()?.cast_unchecked::<PyTuple>() };
        unsafe { PyTuple_SET_ITEM(tuple.as_ptr(), 0, self.0.into_py().as_ptr()) };
        unsafe { PyTuple_SET_ITEM(tuple.as_ptr(), 1, self.1.into_py().as_ptr()) };
        unsafe { PyTuple_SET_ITEM(tuple.as_ptr(), 2, self.2.into_py().as_ptr()) };
        Ok(tuple)
    }
}

impl<T: PyBase, U: PyBase, V: PyBase, W: PyBase> IntoPyTuple
    for (Owned<T>, Owned<U>, Owned<V>, Owned<W>)
{
    fn into_pytuple(self) -> PyResult<Owned<PyTuple>> {
        let tuple = unsafe { PyTuple_New(4).rust_owned()?.cast_unchecked::<PyTuple>() };
        unsafe { PyTuple_SET_ITEM(tuple.as_ptr(), 0, self.0.into_py().as_ptr()) };
        unsafe { PyTuple_SET_ITEM(tuple.as_ptr(), 1, self.1.into_py().as_ptr()) };
        unsafe { PyTuple_SET_ITEM(tuple.as_ptr(), 2, self.2.into_py().as_ptr()) };
        unsafe { PyTuple_SET_ITEM(tuple.as_ptr(), 3, self.3.into_py().as_ptr()) };
        Ok(tuple)
    }
}

impl<T: PyBase, U: PyBase, V: PyBase, W: PyBase, X: PyBase> IntoPyTuple
    for (Owned<T>, Owned<U>, Owned<V>, Owned<W>, Owned<X>)
{
    fn into_pytuple(self) -> PyResult<Owned<PyTuple>> {
        let tuple = unsafe { PyTuple_New(5).rust_owned()?.cast_unchecked::<PyTuple>() };
        unsafe { PyTuple_SET_ITEM(tuple.as_ptr(), 0, self.0.into_py().as_ptr()) };
        unsafe { PyTuple_SET_ITEM(tuple.as_ptr(), 1, self.1.into_py().as_ptr()) };
        unsafe { PyTuple_SET_ITEM(tuple.as_ptr(), 2, self.2.into_py().as_ptr()) };
        unsafe { PyTuple_SET_ITEM(tuple.as_ptr(), 3, self.3.into_py().as_ptr()) };
        unsafe { PyTuple_SET_ITEM(tuple.as_ptr(), 4, self.4.into_py().as_ptr()) };
        Ok(tuple)
    }
}

// TODO: naming (newref? rust_owned?)
/// A wrapper for Python objects that are owned by Rust.
#[derive(Debug)]
pub(crate) struct Owned<T: PyBase> {
    inner: T,
}

impl<T: PyBase> Owned<T> {
    pub(crate) fn new(inner: T) -> Self {
        Self { inner }
    }

    // TODO rename py_owned
    pub(crate) fn into_py(self) -> T {
        // By transferring ownership to Python, we essentially say
        // Rust is no longer responsible for the memory (i.e. Drop)
        let this = ManuallyDrop::new(self);
        unsafe {
            std::ptr::read(&this.inner) // Read the inner object without dropping it
        }
    }

    // TODO don't use this name
    pub(crate) fn borrow(&self) -> T {
        self.inner
    }

    pub(crate) fn map<U, F>(self, f: F) -> Owned<U>
    where
        F: FnOnce(T) -> U,
        U: PyBase,
    {
        Owned {
            inner: f(self.into_py()),
        }
    }
}

impl<T: PyBase> Owned<T> {
    // TODO: return Result type to keep ownership?
    pub(crate) fn cast<U: PyStaticType>(self) -> Option<Owned<U>> {
        // TODO rename method?
        let inner = self.into_py();
        inner.as_py_obj().cast().map(Owned::new).or_else(|| {
            // Casting failed, but don't forget to decref the original object
            unsafe { Py_DECREF(inner.as_ptr()) };
            None
        })
    }

    pub(crate) fn cast_allow_subclass<U: PyStaticType>(self) -> Option<Owned<U>> {
        // TODO rename method?
        let inner = self.into_py();
        inner
            .as_py_obj()
            .cast_allow_subclass()
            .map(Owned::new)
            .or_else(|| {
                // Casting failed, but don't forget to decref the original object
                unsafe { Py_DECREF(inner.as_ptr()) };
                None
            })
    }

    // TODO rename method?
    // TODO unsafe?
    pub(crate) unsafe fn cast_unchecked<U: PyBase>(self) -> Owned<U> {
        Owned {
            inner: self.into_py().as_py_obj().cast_unchecked(),
        }
    }
}

impl<T: PyBase> Drop for Owned<T> {
    fn drop(&mut self) {
        unsafe {
            Py_DECREF(self.inner.as_ptr());
        }
    }
}

// TODO: remove?
impl<T: PyBase> std::ops::Deref for Owned<T> {
    type Target = T;

    fn deref(&self) -> &Self::Target {
        &self.inner
    }
}

pub(crate) fn import(module: &CStr) -> PyReturn {
    unsafe { PyImport_ImportModule(module.as_ptr()) }.rust_owned()
}

pub(crate) fn not_implemented() -> PyReturn {
    Ok(Owned {
        // SAFETY: Py_NotImplemented is always non-null
        inner: unsafe { PyObj::from_ptr_unchecked(Py_NewRef(Py_NotImplemented())) },
    })
}

pub(crate) extern "C" fn generic_dealloc(slf: PyObj) {
    let cls = slf.class().as_ptr().cast::<PyTypeObject>();
    unsafe {
        let tp_free = PyType_GetSlot(cls, Py_tp_free);
        debug_assert_ne!(tp_free, core::ptr::null_mut());
        let tp_free: freefunc = std::mem::transmute(tp_free);
        tp_free(slf.as_ptr().cast());
        Py_DECREF(cls.cast());
    }
}

#[inline]
pub(crate) fn generic_alloc2<T: PyWrapped>(type_: PyType, d: T) -> PyReturn {
    let type_ptr = type_.as_ptr().cast::<PyTypeObject>();
    unsafe {
        let slf = (*type_ptr).tp_alloc.unwrap()(type_ptr, 0).cast::<PyWrap<T>>();
        match slf.cast::<PyObject>().as_mut() {
            Some(r) => {
                (&raw mut (*slf).data).write(d);
                Ok(Owned::new(PyObj::from_ptr_unchecked(r)))
            }
            None => Err(PyErrMarker()),
        }
    }
}

pub(crate) trait PyWrapped: Copy {
    // TODO: phase out
    #[inline]
    unsafe fn extract(obj: *mut PyObject) -> Self {
        (*obj.cast::<PyWrap<Self>>()).data
    }

    // TODO: rename `new_of_heaptype`?
    #[inline]
    fn to_obj3(self, type_: HeapType<Self>) -> PyReturn {
        // generic alloc3!
        generic_alloc2(type_._inner, self)
    }
}

#[repr(C)]
pub(crate) struct PyWrap<T: PyWrapped> {
    _ob_base: PyObject,
    data: T,
}

pub(crate) const fn type_spec<T: PyWrapped>(
    name: &CStr,
    slots: &'static [PyType_Slot],
) -> PyType_Spec {
    PyType_Spec {
        name: name.as_ptr().cast(),
        basicsize: mem::size_of::<PyWrap<T>>() as _,
        itemsize: 0,
        // NOTE: IMMUTABLETYPE flag is required to prevent additional refcycles
        // between the class and the instance.
        // This allows us to keep our types GC-free.
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
        slots: slots.as_ptr().cast_mut(),
    }
}

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

#[allow(unused_imports)]
pub(crate) use {pack, parse_args_kwargs2, unpack_one};
