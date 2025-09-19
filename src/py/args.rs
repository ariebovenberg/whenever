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

pub(crate) trait ArgArray<const N: usize> {
    fn all_required(self) -> PyResult<[PyObj; N]>
    where
        Self: Sized;

    fn required(&self, n: usize) -> PyResult<(&[PyObj], &[Option<PyObj>])>
    where
        Self: Sized;
}

impl<const N: usize> ArgArray<N> for [Option<PyObj>; N] {
    fn all_required(self) -> PyResult<[PyObj; N]> {
        let arr = self;
        if arr.iter().any(|o| o.is_none()) {
            raise_type_err("missing required positional argument")?;
        }
        // SAFETY: we just checked all elements are Some
        Ok(arr.map(|o| o.unwrap()))
    }

    fn required(&self, n: usize) -> PyResult<(&[PyObj], &[Option<PyObj>])> {
        if n > N {
            panic!("n must be <= N");
        }
        if self[..n].iter().any(|o| o.is_none()) {
            raise_type_err("missing required positional argument")?;
        }
        // SAFETY: we just checked all elements are Some
        Ok((
            // SAFETY: we just checked all elements are Some
            unsafe { &*(self[..n].as_ptr() as *const [PyObj; N]) },
            &self[n..],
        ))
    }
}

/// Simple helper for functions that only have positional-or-keyword
/// arguments (i.e. no varargs, no kw-only args, no defaults).
pub(crate) fn bind_simple<const N: usize>(
    fname: &'static str,
    param_names: [PyObj; N],
    args: impl IntoIterator<Item = PyObj>,
    kwargs: Option<impl IntoIterator<Item = (PyObj, PyObj)>>,
) -> PyResult<[Option<PyObj>; N]> {
    let sig = Signature::new_simple(fname, param_names);
    let (pos, _) = sig.bind(args, kwargs)?;
    Ok(pos)
}

/// Defines a Python signature with different kinds of arguments:
/// provided)
struct Signature<const P: usize, const K: usize> {
    fname: &'static str,
    pos: [PyObj; P],
    kw_only: [PyObj; K],
}

impl<const P: usize> Signature<P, 0> {
    fn new_simple(fname: &'static str, pos: [PyObj; P]) -> Self {
        Self {
            fname,
            pos,
            kw_only: [],
        }
    }
}

impl<const P: usize, const K: usize> Signature<P, K> {
    pub(crate) fn bind(
        &self,
        args: impl IntoIterator<Item = PyObj>,
        kwargs: Option<impl IntoIterator<Item = (PyObj, PyObj)>>,
    ) -> PyResult<([Option<PyObj>; P], [Option<PyObj>; K])> {
        self.bind_with_pos_only(args, kwargs, 0)
    }

    /// Like `bind`, but allows specifying how many positional-only
    /// arguments there are. This is useful for functions that
    /// have a `/` in their signature.
    #[inline]
    pub(crate) fn bind_with_pos_only(
        &self,
        args: impl IntoIterator<Item = PyObj>,
        kwargs: Option<impl IntoIterator<Item = (PyObj, PyObj)>>,
        pos_only: usize,
    ) -> PyResult<([Option<PyObj>; P], [Option<PyObj>; K])> {
        let mut arg_iter = args.into_iter();
        let mut pos = [None; P];
        let mut kw = [None; K];

        // Fill positional args first
        pos.iter_mut()
            .zip(&mut arg_iter)
            .for_each(|(slot, arg)| *slot = Some(arg));

        // Check remaining positionals don't exceed expected count
        let pos_remaining = (&mut arg_iter).count();
        if pos_remaining > 0 {
            return raise_type_err(format!(
                "{}() takes at most {} positional arguments but {} were given",
                self.fname,
                P,
                P + pos_remaining,
            ));
        }

        // Process kwargs (if any). We integrate with handle_kwargs.
        if let Some(kw_iter) = kwargs {
            handle_kwargs(self.fname, kw_iter, |key, value, eq| {
                // Try keyword-only names first
                for (&name, out) in self.kw_only.iter().zip(kw.iter_mut()) {
                    if eq(key, name) {
                        // It's guaranteed to be empty, since kw-only args
                        // can't be filled positionally.
                        // Python's calling mechanism also prevents duplicates.
                        debug_assert!(out.is_none());
                        *out = Some(value);
                        return Ok(true);
                    }
                }
                // Try positional-or-keyword names.
                // We iterate in reverse order, since later names
                // are more likely to be passed as keywords.
                for (&param, out) in self.pos.iter().zip(pos.iter_mut()).skip(pos_only).rev() {
                    if eq(key, param) {
                        // Duplicate if slot already filled (positional or earlier kw)
                        if out.replace(value).is_some() {
                            raise_type_err(format!(
                                "{}() got multiple values for argument {}",
                                self.fname, param
                            ))?;
                        }
                        return Ok(true);
                    }
                }
                Ok(false)
            })?;
        }
        Ok((pos, kw))
    }
}

pub(crate) trait CastTuple<To> {
    fn extract_types(self) -> PyResult<To>;
}

// Helper to reduce repetition
fn cast_opt<T: PyStaticType>(o: Option<PyObj>) -> PyResult<Option<T>> {
    match o {
        Some(obj) => {
            let val = obj
                .cast()
                .ok_or_else_type_err(|| format!("cannot convert {} to {}", obj, T::NAME))?;
            Ok(Some(val))
        }
        None => Ok(None),
    }
}

fn cast_req<T: PyStaticType>(p: PyObj) -> PyResult<T> {
    p.cast()
        .ok_or_else_type_err(|| format!("cannot convert {} to {}", p, T::NAME))
}

macro_rules! impl_cast_tuple {
    // pattern: length; identifiers for type params; indices
    ($len:literal; ($($T:ident),+); ($($idx:tt),+)) => {
        #[allow(unused_parens)]
        impl<$($T: PyStaticType),+> CastTuple<( $(Option<$T>),+ )> for [Option<PyObj>; $len] {
            fn extract_types(self) -> PyResult<( $(Option<$T>),+ )> {
                let arr = self;
                Ok((
                    $(
                        {
                            // reuse helper
                            cast_opt::<$T>(arr[$idx])? // if PyObj isn't Copy; otherwise remove clone
                        }
                    ),+
                ))
            }
        }

        #[allow(unused_parens)]
        impl<$($T: PyStaticType),+> CastTuple<( $($T),+ )> for [PyObj; $len] {
            fn extract_types(self) -> PyResult<( $($T),+ )> {
                let arr = self;
                Ok((
                    $(
                        {
                            // reuse helper
                            cast_req::<$T>(arr[$idx])?
                        }
                    ),+
                ))
            }
        }
    };
}

impl_cast_tuple!(1; (A0); (0));
impl_cast_tuple!(2; (A0, A1); (0, 1));
impl_cast_tuple!(3; (A0, A1, A2); (0, 1, 2));
impl_cast_tuple!(4; (A0, A1, A2, A3); (0, 1, 2, 3));
impl_cast_tuple!(5; (A0, A1, A2, A3, A4); (0, 1, 2, 3, 4));
impl_cast_tuple!(6; (A0, A1, A2, A3, A4, A5); (0, 1, 2, 3, 4, 5));
impl_cast_tuple!(7; (A0, A1, A2, A3, A4, A5, A6); (0, 1, 2, 3, 4, 5, 6));
impl_cast_tuple!(8; (A0, A1, A2, A3, A4, A5, A6, A7); (0, 1, 2, 3, 4, 5, 6, 7));
impl_cast_tuple!(9; (A0, A1, A2, A3, A4, A5, A6, A7, A8); (0, 1, 2, 3, 4, 5, 6, 7, 8));

pub(crate) use parse_args_kwargs;
