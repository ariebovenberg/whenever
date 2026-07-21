//! Functionality related to Python type objects
use super::{base::*, dict::PyDict, exc::*, misc::not_implemented, module::*, refs::*};
use crate::pymodule::State;
use core::{
    ffi::CStr,
    mem::{self, MaybeUninit},
};
use pyo3_ffi::*;

/// Wrapper around PyTypeObject.
#[repr(transparent)]
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub(crate) struct PyType {
    obj: PyObj,
}

pub(crate) enum BinaryCall<'a, T: PyPayload> {
    SameType {
        cls: PyClass<T>,
        slf: PyRef<'a, T>,
        other: PyRef<'a, T>,
    },
    ExtTypes {
        cls: PyClass<T>,
        slf: PyRef<'a, T>,
        other: PyObj,
    },
    OtherTypes,
}

pub(crate) fn binary_operation<T: PyPayload>(
    a: PyObj,
    b: PyObj,
    operator: &str,
    operation: impl FnOnce(BinaryCall<'_, T>) -> PyResult<Option<Owned<PyObj>>>,
) -> PyReturn {
    let type_a = a.type_();
    let type_b = b.type_();
    let call = binary_call::<T>(a, b, type_a, type_b);
    let other_types = matches!(&call, BinaryCall::OtherTypes);
    match operation(call)? {
        Some(result) => Ok(result),
        None => {
            if other_types {
                not_implemented()
            } else {
                raise_type_err(format!(
                    "unsupported operand type(s) for {operator}: '{}' and '{}'",
                    type_a.name().to_string_lossy(),
                    type_b.name().to_string_lossy(),
                ))
            }
        }
    }
}

fn binary_call<'a, T: PyPayload>(
    a: PyObj,
    b: PyObj,
    type_a: PyType,
    type_b: PyType,
) -> BinaryCall<'a, T> {
    if type_a == type_b {
        // SAFETY: binary_operation's type parameter matches the slot's left type,
        // and equal types mean the right operand has the same representation.
        return BinaryCall::SameType {
            cls: unsafe { type_a.assume_class() },
            slf: unsafe { PyRef::from_obj_unchecked(a) },
            other: unsafe { PyRef::from_obj_unchecked(b) },
        };
    }
    let (Some(module_a), Some(module_b)) = (type_a.get_module(), type_b.get_module()) else {
        return BinaryCall::OtherTypes;
    };
    if module_a.is(module_b) {
        // SAFETY: whenever binary slots never return NotImplemented for two extension types,
        // so equal modules imply that the left operand is this slot's declared type.
        let cls: PyClass<T> = unsafe { type_a.assume_class() };
        let slf = unsafe { PyRef::from_obj_unchecked(a) };
        BinaryCall::ExtTypes { cls, slf, other: b }
    } else {
        BinaryCall::OtherTypes
    }
}

/// Match an extension object against typed classes without erasing the arm types.
macro_rules! match_type {
    ($obj:ident, ref $type_:expr => |$value:ident| $body:block, $($rest:tt)+) => {
        if let Some($value) = $obj.extract_ref($type_) {
            $body
        } else {
            match_type!($obj, $($rest)+)
        }
    };
    ($obj:ident, $type_:expr => |mut $value:ident| $body:block, $($rest:tt)+) => {
        if let Some(mut $value) = $obj.extract($type_) {
            $body
        } else {
            match_type!($obj, $($rest)+)
        }
    };
    ($obj:ident, $type_:expr => |$value:ident| $body:block, $($rest:tt)+) => {
        if let Some($value) = $obj.extract($type_) {
            $body
        } else {
            match_type!($obj, $($rest)+)
        }
    };
    ($obj:ident, _ => $body:block $(,)?) => {
        $body
    };
}

pub(crate) use match_type;

impl PyBase for PyType {
    fn as_py_obj(&self) -> PyObj {
        self.obj
    }
}

impl FromPy for PyType {
    unsafe fn from_ptr_unchecked(ptr: *mut PyObject) -> Self {
        Self {
            obj: unsafe { PyObj::from_ptr_unchecked(ptr.cast()) },
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
    fn name(&self) -> &CStr {
        // SAFETY: a type object's tp_name is always a null-terminated string.
        unsafe { CStr::from_ptr((*self.as_ptr().cast::<PyTypeObject>()).tp_name) }
    }

    /// Get the Python module this type belongs to, if any.
    /// Returns `None` (and clears the exception) for types not belonging to a module.
    pub(crate) fn get_module(&self) -> Option<PyModule> {
        Some(unsafe {
            PyType_GetModule(self.as_ptr().cast())
                .borrow()
                .or_clear()?
                .cast_unchecked::<PyModule>()
        })
    }

    /// Get the `__dict__` of this type.
    pub(crate) fn get_dict(self) -> PyDict {
        // SAFETY: type objects always have tp_dict populated
        unsafe { PyDict::from_ptr_unchecked((*self.as_ptr().cast::<PyTypeObject>()).tp_dict) }
    }

    /// Treat this Python type as the class whose instances contain `T`.
    ///
    /// # Safety
    /// Instances of this type must use `PyObjectLayout<T>`.
    pub(crate) unsafe fn assume_class<T: PyPayload>(self) -> PyClass<T> {
        // SAFETY: PyClass is transparent over a valid PyType pointer.
        unsafe { PyClass::from_ptr_unchecked(self.as_ptr()) }
    }
}

impl std::fmt::Display for PyType {
    fn fmt(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        self.write_repr(f)
    }
}

/// A PyTypeObject that is linked to a Rust struct in whenever.
/// `#[repr(transparent)]` so that `*mut PyClass<T>` can be cast to
/// `*mut *mut PyObject` in `module_clear` (same as PyType → PyObj chain).
#[repr(transparent)]
#[derive(Debug, PartialEq, Eq)]
pub(crate) struct PyClass<T: PyPayload> {
    py_type: PyType,
    type_rust: std::marker::PhantomData<T>,
}

// PyClass is always Copy/Clone: it's just a pointer + PhantomData marker.
impl<T: PyPayload> Copy for PyClass<T> {}
impl<T: PyPayload> Clone for PyClass<T> {
    fn clone(&self) -> Self {
        *self
    }
}

impl<T: PyPayload> PyClass<T> {
    /// Get the module state
    pub(crate) fn state(&self) -> &State {
        // SAFETY: the type pointer is valid, and the retrieved module
        // state is valid once the Python module is initialized.
        unsafe {
            PyType_GetModuleState(self.py_type.as_ptr().cast())
                .cast::<MaybeUninit<Option<State>>>()
                .as_ref()
                .unwrap()
                .assume_init_ref()
                .as_ref()
                .unwrap()
        }
    }

    pub(crate) fn as_type(&self) -> PyType {
        self.py_type
    }
}

impl<T: PyPayload> PyBase for PyClass<T> {
    fn as_py_obj(&self) -> PyObj {
        self.py_type.as_py_obj()
    }
}

impl<T: PyPayload> FromPy for PyClass<T> {
    unsafe fn from_ptr_unchecked(ptr: *mut PyObject) -> Self {
        Self {
            py_type: unsafe { PyType::from_ptr_unchecked(ptr) },
            type_rust: std::marker::PhantomData,
        }
    }
}

impl<T: PyPayload> From<PyClass<T>> for PyType {
    fn from(t: PyClass<T>) -> Self {
        t.py_type
    }
}

/// A trait for Rust structs that can be embedded in a Python heap object.
pub(crate) trait PyPayload: Sized {
    /// Allocate a new Python object wrapping this data.
    #[inline]
    fn to_obj(self, cls: PyClass<Self>) -> PyReturn {
        generic_alloc(cls, self)
    }
}

/// A reference to the Rust data embedded in a Python object, together with
/// the containing PyObj. This enables both safe value extraction (for Copy types)
/// and safe identity-preserving returns (via `.newref()`).
///
/// The method dispatch macros create this and pass it through `FromWrapped`,
/// which the Rust compiler resolves based on what the function expects:
/// - `T` (Copy types): extracts the value
/// - `&T`: extracts the reference
/// - `PyRef<T>`: passes the full wrapper (for `__abs__` etc.)
pub(crate) struct PyRef<'a, T: PyPayload> {
    obj: PyObj,
    data: &'a T,
}

impl<'a, T: PyPayload> PyRef<'a, T> {
    /// # Safety
    /// `obj` must be an instance of `PyClass<T>` and remain alive for `'a`.
    #[inline]
    pub(crate) unsafe fn from_obj_unchecked(obj: PyObj) -> Self {
        Self {
            obj,
            data: unsafe { &(*obj.as_ptr().cast::<PyObjectLayout<T>>()).data },
        }
    }

    /// Return a new Python reference to the containing object.
    #[inline]
    pub(crate) fn newref(&self) -> Owned<PyObj> {
        self.obj.newref()
    }

    #[inline]
    pub(crate) fn class(&self) -> PyClass<T> {
        // SAFETY: PyRef is only constructed for an instance of PyClass<T>.
        unsafe { self.obj.type_().assume_class() }
    }
}

impl<T: PyPayload> std::ops::Deref for PyRef<'_, T> {
    type Target = T;
    #[inline]
    fn deref(&self) -> &T {
        self.data
    }
}

/// Trait for automatic conversion from `PyRef<T>` to the type expected
/// by a method function. Resolved by the compiler at each call site.
pub(crate) trait FromWrapped<'a, T: PyPayload>: Sized {
    fn from_wrapped(w: PyRef<'a, T>) -> Self;
}

/// Copy types: extract the value.
impl<T: PyPayload + Copy> FromWrapped<'_, T> for T {
    #[inline]
    fn from_wrapped(w: PyRef<'_, T>) -> T {
        *w.data
    }
}

/// Reference access: extract `&T`.
impl<'a, T: PyPayload> FromWrapped<'a, T> for &'a T {
    #[inline]
    fn from_wrapped(w: PyRef<'a, T>) -> &'a T {
        w.data
    }
}

/// Pass-through: keep the full wrapper.
impl<'a, T: PyPayload> FromWrapped<'a, T> for PyRef<'a, T> {
    #[inline]
    fn from_wrapped(w: PyRef<'a, T>) -> Self {
        w
    }
}

/// The shape of PyObjects that wrap a `whenever` Rust type.
#[repr(C)]
pub(crate) struct PyObjectLayout<T: PyPayload> {
    _ob_base: PyObject,
    pub(crate) data: T,
}

pub(crate) const fn type_spec<T: PyPayload>(
    name: &CStr,
    slots: &'static [PyType_Slot],
) -> PyType_Spec {
    PyType_Spec {
        name: name.as_ptr().cast(),
        basicsize: mem::size_of::<PyObjectLayout<T>>() as _,
        itemsize: 0,
        // NOTE: IMMUTABLETYPE flag is required to prevent additional refcycles
        // between the class and the instance.
        // This allows us to keep our types GC-free.
        flags: (Py_TPFLAGS_DEFAULT | Py_TPFLAGS_IMMUTABLETYPE) as _,
        slots: slots.as_ptr().cast_mut(),
    }
}

pub(crate) extern "C" fn generic_dealloc(slf: PyObj) {
    let cls = slf.type_().as_ptr().cast::<PyTypeObject>();
    unsafe {
        let tp_free = PyType_GetSlot(cls, Py_tp_free);
        debug_assert_ne!(tp_free, core::ptr::null_mut());
        let tp_free: freefunc = std::mem::transmute(tp_free);
        tp_free(slf.as_ptr().cast());
        Py_DECREF(cls.cast());
    }
}

#[inline]
pub(crate) fn generic_alloc<T: PyPayload>(cls: PyClass<T>, data: T) -> PyReturn {
    let type_ptr = cls.as_ptr().cast::<PyTypeObject>();
    unsafe {
        let slf = (*type_ptr).tp_alloc.unwrap()(type_ptr, 0).cast::<PyObjectLayout<T>>();
        match slf.cast::<PyObject>().as_mut() {
            Some(r) => {
                (&raw mut (*slf).data).write(data);
                // SAFETY: tp_alloc returns a new reference and `r` is non-null here.
                Ok(Owned::from_owned_ptr(r))
            }
            None => Err(PyErrMarker),
        }
    }
}
