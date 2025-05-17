use crate::common::pytype::PyWrapped;
use crate::pymodule::State;
use core::{
    ffi::{c_long, c_void, CStr},
    mem::{self, ManuallyDrop},
    ptr::null_mut as NULL,
};
use pyo3_ffi::*;
use std::fmt::Debug;

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
pub(crate) type PyAny = PyResult<PyObj>;
pub(crate) type PyReturn2 = PyResult<Owned<PyObj>>;

#[derive(Debug, Copy, Clone, PartialEq, Eq)]
pub(crate) struct HeapType<T: PyWrapped> {
    // TODO name
    pub(crate) inner: PyType,
    layout: std::marker::PhantomData<T>,
}

impl<T: PyWrapped> HeapType<T> {
    pub(crate) unsafe fn from_ptr_unchecked(ptr: *mut PyObject) -> Self {
        Self {
            inner: PyType::from_ptr_unchecked(ptr),
            layout: std::marker::PhantomData,
        }
    }

    pub(crate) fn as_ptr(&self) -> *mut PyObject {
        self.inner.as_ptr()
    }

    // TODO: lifetime story
    pub(crate) fn state(&self) -> &'static State {
        // SAFETY: we assume the pointer is valid and points to a PyType object
        unsafe { State::for_type(self.as_ptr().cast()) }
    }
}

// TODO move
impl PyType {
    pub(crate) unsafe fn link_type<T: PyWrapped>(self) -> HeapType<T> {
        // SAFETY: we assume the pointer is valid and points to a PyType object
        unsafe { HeapType::from_ptr_unchecked(self.as_ptr()) }
    }
}

impl<T: PyWrapped> From<HeapType<T>> for PyType {
    fn from(t: HeapType<T>) -> Self {
        t.inner
    }
}

pub(crate) struct DecrefOnDrop(pub(crate) *mut PyObject);

impl Drop for DecrefOnDrop {
    fn drop(&mut self) {
        unsafe { Py_DECREF(self.0) };
    }
}

// Helper to automatically decref the object when it goes out of scope
macro_rules! defer_decref(
    ($e:expr) => {
        let _deferred = DecrefOnDrop($e);
    };
);

// Apply this on arguments to have them decref'd after the containing expression.
// For function calls, it has the same effect as if the call would 'steal' the reference
macro_rules! steal(
    ($e:expr) => {
        DecrefOnDrop($e).0
    };
);

pub(crate) trait PyObjectExt {
    #[allow(clippy::wrong_self_convention)]
    unsafe fn as_result<'a>(self) -> PyResult<&'a mut PyObject>;
    #[allow(clippy::wrong_self_convention)]
    fn rust_owned(self) -> PyResult<Owned<PyObj>>;
    #[allow(clippy::wrong_self_convention)]
    unsafe fn is_str(self) -> bool;
    // FUTURE: unchecked versions of these in case we know the type
    unsafe fn to_utf8<'a>(self) -> PyResult<Option<&'a [u8]>>;
    unsafe fn to_str<'a>(self) -> PyResult<Option<&'a str>>;
    unsafe fn to_i64(self) -> PyResult<Option<i64>>;
    unsafe fn repr(self) -> String;
}

impl PyObjectExt for *mut PyObject {
    unsafe fn as_result<'a>(self) -> PyResult<&'a mut PyObject> {
        self.as_mut().ok_or(PyErrOccurred())
    }
    // TODO: name
    // TODO a version without checking for null
    fn rust_owned(self) -> PyResult<Owned<PyObj>> {
        PyObj::new(self).map(Owned::new)
    }

    unsafe fn is_str(self) -> bool {
        PyUnicode_Check(self) != 0
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

    unsafe fn to_i64(self) -> PyResult<Option<i64>> {
        // Although PyLong_AsLongLong can handle non-ints, we want to be strict and
        // opt out of accepting __int__, __index__ results.
        if PyLong_Check(self) == 0 {
            return Ok(None);
        }
        match PyLong_AsLongLong(self) {
            x if x != -1 || PyErr_Occurred().is_null() => Ok(Some(x)),
            // The error message is set for us
            _ => Err(PyErrOccurred()),
        }
    }

    unsafe fn repr(self) -> String {
        let repr_obj = PyObject_Repr(self);
        if repr_obj.is_null() {
            // i.e repr() raised an exception, or it didn't return a string.
            // Let's clear the exception and return a placeholder.
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
        // We need to return owned data, so it outlives the Python string
        // object. repr() is generally not part of performance-critical code
        // anyway, so this is acceptable.
        .to_string()
    }
}

// TODO a non-raw version?
pub(crate) fn raise<T, U: ToPy>(exc: *mut PyObject, msg: U) -> PyResult<T> {
    Err(exception(exc, msg))
}

pub(crate) fn exception<U: ToPy>(exc: *mut PyObject, msg: U) -> PyErrOccurred {
    // If the message conversion fails, an error is set for us.
    // It's mostly likely a MemoryError.
    // TODO safety
    if let Ok(msg) = unsafe { msg.to_py() } {
        unsafe { PyErr_SetObject(exc, msg) }
    };
    PyErrOccurred()
}

pub(crate) fn value_err<U: ToPy>(msg: U) -> PyErrOccurred {
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
    unsafe fn from_py_ptr_unchecked(ptr: *mut PyObject) -> Self;
}

impl<T> FromPy for T
where
    T: PyWrapped,
{
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
    unsafe fn to_py(self) -> PyReturn;
    // TODO name
    fn to_py2(self) -> PyReturn2 {
        unsafe {
            self.to_py()
                .map(|x| Owned::new(PyObj::from_ptr_unchecked(x)))
        }
    }
}

impl ToPy for bool {
    unsafe fn to_py(self) -> PyReturn {
        Ok(newref(
            match self {
                true => Py_True(),
                false => Py_False(),
            }
            // True/False pointers are never null, unless something is seriously wrong
            .as_mut()
            .unwrap(),
        ))
    }
}

impl ToPy for i128 {
    unsafe fn to_py(self) -> PyReturn {
        // Yes, this is a private API, but it's the only way to create a 128-bit integer
        // on Python < 3.13. Other libraries do this too.
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

// REFACTOR: instead of this trait, have an explicit macro/function
// that is more readable in typical usage scenarios.
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

// TODO name
pub(crate) fn identity1b(_: PyType, slf: PyObj) -> Owned<PyObj> {
    slf.newref()
}

pub(crate) fn __copy__(_: PyType, slf: PyObj) -> Owned<PyObj> {
    slf.newref()
}

pub(crate) fn __deepcopy__(_: PyType, slf: PyObj, _: PyObj) -> Owned<PyObj> {
    slf.newref()
}

pub(crate) unsafe fn newref<'a>(obj: *mut PyObject) -> &'a mut PyObject {
    Py_INCREF(obj);
    obj.as_mut().unwrap()
}

// FUTURE: replace with Py_IsNone when dropping Py 3.9 support
pub(crate) unsafe fn is_none(x: *mut PyObject) -> bool {
    x == Py_None()
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
                let imported = import_from(self.module, self.name)?;
                self.obj.get().write(imported);
                Ok(PyObj::from_py_ptr_unchecked(imported))
            } else {
                Ok(PyObj::from_py_ptr_unchecked(obj))
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

// TODO refactor
pub(crate) unsafe fn import_from(module: &CStr, name: &CStr) -> PyReturn {
    let module = PyImport_ImportModule(module.as_ptr()).as_result()?;
    defer_decref!(module);
    PyObject_GetAttrString(module, name.as_ptr()).as_result()
}

#[inline]
pub(crate) unsafe fn call1(func: *mut PyObject, arg: *mut PyObject) -> PyReturn {
    PyObject_CallOneArg(func, arg).as_result()
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
                return Err(PyErrOccurred());
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

// TODO: remove this impl? Since we *require* a fresh reference to cross the Py boundary?
impl IntoPyPtr for PyReturn {
    fn into_py_ptr(self) -> *mut PyObject {
        match self {
            Ok(x) => x,
            Err(_) => NULL(),
        }
    }
}

impl IntoPyPtr for PyAny {
    fn into_py_ptr(self) -> *mut PyObject {
        match self {
            Ok(x) => x.as_ptr(),
            Err(_) => NULL(),
        }
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

use std::ptr::NonNull;

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
            None => Err(PyErrOccurred()),
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
        unsafe { T::from_py_ptr_unchecked(self.inner.as_ptr()) }
    }

    pub(crate) unsafe fn assume_heaptype<T: PyWrapped>(&self) -> (HeapType<T>, T) {
        (
            unsafe { HeapType::from_ptr_unchecked(self.class().as_ptr()) },
            unsafe { T::extract(self.inner.as_ptr()) },
        )
    }

    pub(crate) fn extract3<T: FromPy + PyWrapped>(&self, t: HeapType<T>) -> Option<T> {
        (self.class() == t.inner).then(
            // SAFETY: we've just checked the type, so this is safe
            || unsafe { self.extract_unchecked() },
        )
    }

    pub(crate) fn repr(&self) -> String {
        unsafe { self.inner.as_ptr().repr() }
    }

    pub(crate) fn cast<T: PyBase>(self) -> Option<T> {
        T::isinstance_exact(self)
            .then_some(unsafe { T::from_ptr_unchecked(self.as_py_obj().inner.as_ptr()) })
    }

    pub(crate) fn cast_allow_subclass<T: PyBase>(self) -> Option<T> {
        T::isinstance(self)
            .then_some(unsafe { T::from_ptr_unchecked(self.as_py_obj().inner.as_ptr()) })
    }

    // TODO: do we need the extra method or just unwrap above?
    pub(crate) unsafe fn cast_unchecked<T: PyBase>(self) -> T {
        unsafe { T::from_ptr_unchecked(self.as_py_obj().inner.as_ptr()) }
    }
}

impl PyBase for PyObj {
    fn as_py_obj(&self) -> PyObj {
        *self
    }

    fn isinstance_exact(_: impl PyBase) -> bool {
        true
    }

    fn isinstance(_: impl PyBase) -> bool {
        true
    }

    // TODO: unify with from_py_ptr_unchecked
    unsafe fn from_ptr_unchecked(ptr: *mut PyObject) -> Self {
        Self {
            inner: NonNull::new_unchecked(ptr),
        }
    }
}

// TODO rename "static type"?
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
    fn getattr(&self, name: &CStr) -> PyReturn2 {
        unsafe { PyObject_GetAttrString(self.as_ptr(), name.as_ptr()) }.rust_owned()
    }

    /// Call the object with one argument.
    fn call1(&self, arg: impl PyBase) -> PyReturn2 {
        unsafe { PyObject_CallOneArg(self.as_ptr(), arg.as_ptr()) }.rust_owned()
    }

    /// Call the object with no arguments.
    fn call0(&self) -> PyReturn2 {
        unsafe { PyObject_CallNoArgs(self.as_ptr()) }.rust_owned()
    }

    /// Call the object with a tuple of arguments.
    fn call(&self, args: PyTuple) -> PyReturn2 {
        // OPTIMIZE: use vectorcall?
        unsafe { PyObject_Call(self.as_ptr(), args.as_ptr(), NULL()) }.rust_owned()
    }

    fn is_none(&self) -> bool {
        // TODO
        unsafe { is_none(self.as_ptr()) }
    }

    fn py_eq(&self, other: impl PyBase) -> PyResult<bool> {
        // SAFETY: calling CPython API with valid arguments
        match unsafe { PyObject_RichCompareBool(self.as_ptr(), other.as_ptr(), Py_EQ) } {
            1 => Ok(true),
            0 => Ok(false),
            _ => Err(PyErrOccurred()),
        }
    }

    fn is_true(&self) -> bool {
        unsafe { self.as_ptr() == Py_True() }
    }

    fn isinstance_exact(obj: impl PyBase) -> bool;
    fn isinstance(obj: impl PyBase) -> bool;
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

    fn isinstance_exact(obj: impl PyBase) -> bool {
        unsafe { PyDate_CheckExact(obj.as_ptr()) != 0 }
    }

    fn isinstance(obj: impl PyBase) -> bool {
        unsafe { PyDate_Check(obj.as_ptr()) != 0 }
    }

    unsafe fn from_ptr_unchecked(ptr: *mut PyObject) -> Self {
        Self {
            obj: PyObj::from_ptr_unchecked(ptr),
        }
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

    pub(crate) fn utcoffset(&self) -> PyReturn2 {
        self.getattr(c"utcoffset")?.call0()
    }
}

impl PyBase for PyDateTime {
    fn as_py_obj(&self) -> PyObj {
        self.obj
    }

    fn isinstance_exact(obj: impl PyBase) -> bool {
        unsafe { PyDateTime_CheckExact(obj.as_ptr()) != 0 }
    }

    fn isinstance(obj: impl PyBase) -> bool {
        unsafe { PyDateTime_Check(obj.as_ptr()) != 0 }
    }

    unsafe fn from_ptr_unchecked(ptr: *mut PyObject) -> Self {
        Self {
            obj: PyObj::from_ptr_unchecked(ptr),
        }
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

    fn isinstance_exact(obj: impl PyBase) -> bool {
        unsafe { PyDelta_CheckExact(obj.as_ptr()) != 0 }
    }

    fn isinstance(obj: impl PyBase) -> bool {
        unsafe { PyDelta_Check(obj.as_ptr()) != 0 }
    }

    unsafe fn from_ptr_unchecked(ptr: *mut PyObject) -> Self {
        Self {
            obj: PyObj::from_ptr_unchecked(ptr),
        }
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

    fn isinstance_exact(obj: impl PyBase) -> bool {
        unsafe { PyTime_CheckExact(obj.as_ptr()) != 0 }
    }

    fn isinstance(obj: impl PyBase) -> bool {
        unsafe { PyTime_Check(obj.as_ptr()) != 0 }
    }

    unsafe fn from_ptr_unchecked(ptr: *mut PyObject) -> Self {
        Self {
            obj: PyObj::from_ptr_unchecked(ptr),
        }
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

    fn isinstance_exact(obj: impl PyBase) -> bool {
        unsafe { PyType_CheckExact(obj.as_ptr()) != 0 }
    }
    fn isinstance(obj: impl PyBase) -> bool {
        unsafe { PyType_Check(obj.as_ptr()) != 0 }
    }

    // TODO: rename from_ptr unchecked
    unsafe fn from_ptr_unchecked(ptr: *mut PyObject) -> Self {
        Self {
            obj: PyObj::from_ptr_unchecked(ptr.cast()),
        }
    }
}

impl PyType {
    // TODO return module state
    pub(crate) fn are_both_whenever(&self, other: PyType) -> Option<&State> {
        // TODO: need to account for errors!
        let mod_a = unsafe { PyType_GetModule(self.as_ptr().cast()) };
        let mod_b = unsafe { PyType_GetModule(other.as_ptr().cast()) };
        (mod_a == mod_b).then(|| {
            // SAFETY: we just checked the pointers, so this is safe
            unsafe { State::for_mod(mod_a) }
        })
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
            return Err(PyErrOccurred());
        };
        Ok(unsafe { std::slice::from_raw_parts(p.cast::<u8>(), size as usize) })
    }
}

impl PyBase for PyStr {
    fn as_py_obj(&self) -> PyObj {
        self.obj
    }

    fn isinstance_exact(obj: impl PyBase) -> bool {
        unsafe { PyUnicode_CheckExact(obj.as_ptr()) != 0 }
    }

    fn isinstance(obj: impl PyBase) -> bool {
        unsafe { PyUnicode_Check(obj.as_ptr()) != 0 }
    }

    unsafe fn from_ptr_unchecked(ptr: *mut PyObject) -> Self {
        Self {
            obj: PyObj::from_ptr_unchecked(ptr),
        }
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

    fn isinstance_exact(obj: impl PyBase) -> bool {
        unsafe { PyDict_CheckExact(obj.as_ptr()) != 0 }
    }

    fn isinstance(obj: impl PyBase) -> bool {
        unsafe { PyDict_Check(obj.as_ptr()) != 0 }
    }

    unsafe fn from_ptr_unchecked(ptr: *mut PyObject) -> Self {
        Self {
            obj: PyObj::from_ptr_unchecked(ptr),
        }
    }
}

impl PyDict {
    pub(crate) fn new() -> PyResult<Owned<PyDict>> {
        // SAFETY: PyDict_New() returns a new reference to a PyDict
        Ok(unsafe { PyDict_New().rust_owned()?.cast_unchecked() })
    }

    pub(crate) fn set_item_str(&self, key: &CStr, value: PyObj) -> PyResult<()> {
        if unsafe { PyDict_SetItemString(self.obj.as_ptr(), key.as_ptr(), value.as_ptr()) } == -1 {
            return Err(PyErrOccurred());
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

    fn isinstance_exact(obj: impl PyBase) -> bool {
        unsafe { PyTuple_CheckExact(obj.as_ptr()) != 0 }
    }

    fn isinstance(obj: impl PyBase) -> bool {
        unsafe { PyTuple_Check(obj.as_ptr()) != 0 }
    }

    unsafe fn from_ptr_unchecked(ptr: *mut PyObject) -> Self {
        Self {
            obj: PyObj::from_ptr_unchecked(ptr),
        }
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

    fn isinstance_exact(obj: impl PyBase) -> bool {
        unsafe { PyLong_CheckExact(obj.as_ptr()) != 0 }
    }

    fn isinstance(obj: impl PyBase) -> bool {
        unsafe { PyLong_Check(obj.as_ptr()) != 0 }
    }

    unsafe fn from_ptr_unchecked(ptr: *mut PyObject) -> Self {
        Self {
            obj: PyObj::from_ptr_unchecked(ptr),
        }
    }
}

impl PyInt {
    pub(crate) fn to_long(self) -> PyResult<c_long> {
        match unsafe { PyLong_AsLong(self.as_ptr()) } {
            x if x != -1 || unsafe { PyErr_Occurred() }.is_null() => Ok(x),
            // The error message is set for us
            _ => Err(PyErrOccurred()),
        }
    }

    pub(crate) fn to_i64(self) -> PyResult<c_long> {
        match unsafe { PyLong_AsLongLong(self.as_ptr()) } {
            x if x != -1 || unsafe { PyErr_Occurred() }.is_null() => Ok(x),
            // The error message is set for us
            _ => Err(PyErrOccurred()),
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

    fn isinstance_exact(obj: impl PyBase) -> bool {
        unsafe { PyFloat_CheckExact(obj.as_ptr()) != 0 }
    }

    fn isinstance(obj: impl PyBase) -> bool {
        unsafe { PyFloat_Check(obj.as_ptr()) != 0 }
    }

    unsafe fn from_ptr_unchecked(ptr: *mut PyObject) -> Self {
        Self {
            obj: PyObj::from_ptr_unchecked(ptr),
        }
    }
}

impl PyFloat {
    pub(crate) fn to_f64(self) -> PyResult<f64> {
        match unsafe { PyFloat_AsDouble(self.as_ptr()) } {
            x if x != -1.0 || unsafe { PyErr_Occurred() }.is_null() => Ok(x),
            // The error message is set for us
            _ => Err(PyErrOccurred()),
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

    fn isinstance_exact(obj: impl PyBase) -> bool {
        unsafe { PyBytes_CheckExact(obj.as_ptr()) != 0 }
    }

    fn isinstance(obj: impl PyBase) -> bool {
        unsafe { PyBytes_Check(obj.as_ptr()) != 0 }
    }

    unsafe fn from_ptr_unchecked(ptr: *mut PyObject) -> Self {
        Self {
            obj: PyObj::from_ptr_unchecked(ptr),
        }
    }
}

impl PyBytes {
    // TODO rename as_slice?
    pub(crate) fn as_bytes(&self) -> PyResult<&[u8]> {
        let p = unsafe { PyBytes_AsString(self.as_ptr()) };
        // TODO: this check shouldn't be necessary, PyBytes_AS_STRING?
        // Also: PyBytes_GET_SIZE?
        if p.is_null() {
            return Err(PyErrOccurred());
        };
        Ok(unsafe {
            std::slice::from_raw_parts(p.cast::<u8>(), PyBytes_Size(self.as_ptr()) as usize)
        })
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
pub(crate) struct Owned<T: PyBase> {
    inner: T,
}

impl<T: PyBase> Owned<T> {
    pub(crate) fn new(inner: T) -> Self {
        Self { inner }
    }

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
}

impl<T: PyBase> Owned<T> {
    // TODO: return Result type to keep ownership?
    pub(crate) fn cast<U: PyBase>(self) -> Option<Owned<U>> {
        // TODO rename method?
        let inner = self.into_py();
        inner.as_py_obj().cast().map(Owned::new).or_else(|| {
            // Casting failed, but don't forget to decref the original object
            unsafe { Py_DECREF(inner.as_ptr()) };
            None
        })
    }

    pub(crate) fn cast_allow_subclass<U: PyBase>(self) -> Option<Owned<U>> {
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
        println!("Dropping OwnedPyObj: {:?}", self.inner.repr());
        unsafe {
            Py_DECREF(self.inner.as_ptr());
        }
    }
}

impl<T: PyBase> std::ops::Deref for Owned<T> {
    type Target = T;

    fn deref(&self) -> &Self::Target {
        &self.inner
    }
}

pub(crate) fn import(module: &CStr) -> PyReturn2 {
    unsafe { PyImport_ImportModule(module.as_ptr()) }.rust_owned()
}

// TODO wrap in result
pub(crate) fn not_implemented() -> PyReturn2 {
    Ok(Owned {
        // SAFETY: Py_NotImplemented is always non-null
        inner: unsafe { PyObj::from_ptr_unchecked(Py_NewRef(Py_NotImplemented())) },
    })
}

#[allow(unused_imports)]
pub(crate) use {defer_decref, pack, parse_args_kwargs2, steal, unpack_one};
