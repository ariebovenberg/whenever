use crate::date::Date;
use core::ptr::null_mut as NULL;
use pyo3_ffi::*;
use std::num::NonZeroU16;
use std::ops::Neg;
use std::{fmt::Debug, num::NonZeroU8};

pub(crate) mod parse;
pub(crate) mod pydatetime;
pub(crate) mod pyobject;
pub(crate) mod pytype;

/// Try to parse digit at index. No bounds check on the index.
/// Returns None if the character is not an ASCII digit
pub(crate) fn parse_digit(s: &[u8], index: usize) -> Option<u8> {
    match s[index] {
        c if c.is_ascii_digit() => Some(c - b'0'),
        _ => None,
    }
}

/// Like `parse_digit`, but also checks that the digit is less than or equal to `max`
pub(crate) fn parse_digit_max(s: &[u8], index: usize, max: u8) -> Option<u8> {
    match s[index] {
        c if c >= b'0' && c <= max => Some(c - b'0'),
        _ => None,
    }
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

/// Format an offset in seconds as a string like "+hh:mm",
/// adding ":ss" only if needed
pub(crate) fn offset_fmt(secs: Offset) -> String {
    // OPTIMIZE: is it worth avoiding the allocation since we know the max size?
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
pub enum Disambiguate {
    Compatible,
    Earlier,
    Later,
    Raise,
}

#[derive(Debug, Copy, Clone, PartialEq, Eq)]
pub enum Ambiguity {
    Unambiguous(Offset),
    Gap(Offset, Offset),  // (earlier, later) occurrence, (a > b)
    Fold(Offset, Offset), // (earlier, later) occurrence, (a > b)
}

impl Disambiguate {
    fn parse(s: &[u8]) -> Option<Self> {
        Some(match s {
            b"compatible" => Self::Compatible,
            b"earlier" => Self::Earlier,
            b"later" => Self::Later,
            b"raise" => Self::Raise,
            _ => None?,
        })
    }

    // OPTIMIZE: use fast string compare, as the values are in most cases interned
    // TODO: already checked to be string?
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
    ) -> PyResult<Option<Self>> {
        match kwargs.next() {
            Some((name, value)) => {
                if kwargs.len() == 1 {
                    if name.kwarg_eq(str_disambiguate) {
                        Self::from_py(value).map(Some)
                    } else {
                        raise_type_err(format!(
                            "{}() got an unexpected keyword argument {}",
                            fname,
                            name.repr()
                        ))
                    }
                } else {
                    raise_type_err(format!(
                        "{}() takes at most 1 keyword argument, got {}",
                        fname,
                        kwargs.len()
                    ))
                }
            }
            None => Ok(None),
        }
    }
}

#[inline]
pub(crate) unsafe fn call1(func: *mut PyObject, arg: *mut PyObject) -> PyReturn {
    PyObject_CallOneArg(func, arg).as_result()
}

#[inline]
pub(crate) unsafe fn methcall1(slf: *mut PyObject, name: &str, arg: *mut PyObject) -> PyReturn {
    // OPTIMIZE: what if we use an interned string for the method name?
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

/// A container for iterating over a dictionary's items.
pub(crate) struct DictItems {
    dict: *mut PyObject,
    pos: Py_ssize_t,
}

impl DictItems {
    pub(crate) fn new_unchecked(dict: *mut PyObject) -> Self {
        debug_assert!(!dict.is_null() && unsafe { PyDict_Size(dict) > 0 });
        DictItems { dict, pos: 0 }
    }

    pub(crate) fn new(dict: *mut PyObject) -> Option<Self> {
        (!dict.is_null() && unsafe { PyDict_Size(dict) > 0 }).then(|| Self::new_unchecked(dict))
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
            return raise_type_err(format!(
                "{}() got an unexpected keyword argument: {}",
                fname,
                key.repr()
            ));
        }
    }
    Ok(())
}

pub(crate) unsafe fn match_interned_str<T, F>(
    name: &str,
    value: *mut PyObject,
    mut handler: F,
) -> PyResult<T>
where
    F: FnMut(*mut PyObject, fn(*mut PyObject, *mut PyObject) -> bool) -> Option<T>,
{
    handler(value, ptr_eq)
        .or_else(|| handler(value, value_eq))
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

macro_rules! parse_args_kwargs {
    ($args:ident, $kwargs:ident, $fmt:expr, $($var:ident),* $(,)?) => {
        const _ARGNAMES: *mut *const std::ffi::c_char = [
            $(
                concat!(stringify!($var), "\0").as_ptr() as *const std::ffi::c_char,
            )*
            std::ptr::null(),
        ].as_ptr() as *mut _;
        if PyArg_ParseTupleAndKeywords(
            $args,
            $kwargs,
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
    };
}

/// Offset in seconds from UTC. -86_399..=86_399  (+/- 24 hours)
pub(crate) type Offset = i32;
/// Month of the year. 1..=12
pub(crate) type Month = NonZeroU8;
/// Year 1..=9999
pub(crate) type Year = NonZeroU16;

/// Time since UNIX epoch in seconds.
/// Bounded -62_135_596_800..=25_3402_300_799 (0001-01-01T00..9999-12-31T23:59:59)
pub(crate) type EpochSeconds = i64;

/// Number of sub-second nanoseconds. 0..=999_999_999
pub(crate) type SubsecNanos = u32;

#[derive(Debug, Copy, Clone, PartialEq, Eq, Ord, PartialOrd)]
pub(crate) struct OffsetS(i32);

impl OffsetS {
    pub const MIN: OffsetS = OffsetS(-86_399);
    pub const MAX: OffsetS = OffsetS(86_399);
    pub(crate) fn new_unchecked(secs: i32) -> Self {
        Self(secs)
    }

    pub(crate) fn new(secs: i32) -> Option<Self> {
        (Self::MIN.0..=Self::MAX.0)
            .contains(&secs)
            .then(|| Self(secs))
    }

    pub(crate) fn new_saturating(secs: i32) -> Self {
        Self(secs.clamp(Self::MIN.0, Self::MAX.0))
    }

    pub(crate) fn get(self) -> i32 {
        self.0
    }

    pub(crate) fn shift(self, x: OffsetDelta) -> Option<Self> {
        // Safe since both arguments are constrained far below i32::MAX
        Self::new(self.0 + x.0)
    }
}

impl Neg for OffsetS {
    type Output = Self;

    fn neg(self) -> Self::Output {
        Self(-self.0)
    }
}

impl TryFrom<i32> for OffsetS {
    type Error = ();

    fn try_from(value: i32) -> Result<Self, Self::Error> {
        OffsetS::new(value).ok_or(())
    }
}

impl From<OffsetS> for i32 {
    fn from(x: OffsetS) -> Self {
        x.0
    }
}

/// Difference between two offsets in seconds. +/- 48 hours
#[derive(Debug, Copy, Clone, PartialEq, Eq, Ord, PartialOrd)]
pub(crate) struct OffsetDelta(i32);

impl OffsetDelta {
    pub const MIN: OffsetDelta = OffsetDelta(-86_400 * 2);
    pub const MAX: OffsetDelta = OffsetDelta(86_400 * 2);
    pub(crate) const fn new_unchecked(secs: i32) -> Self {
        Self(secs)
    }

    pub(crate) fn new(secs: i32) -> Option<Self> {
        (Self::MIN.0..=Self::MAX.0)
            .contains(&secs)
            .then(|| Self(secs))
    }

    pub(crate) fn new_saturating(secs: i32) -> Self {
        Self(secs.clamp(Self::MIN.0, Self::MAX.0))
    }

    pub(crate) fn get(self) -> i32 {
        self.0
    }
}

#[derive(Debug, Copy, Clone, PartialEq, Eq, Ord, PartialOrd)]
pub(crate) struct EpochSecs(i64);

impl EpochSecs {
    pub const MIN: EpochSecs = EpochSecs(-62_135_596_800);
    pub const MAX: EpochSecs = EpochSecs(25_402_300_799);
    pub(crate) fn new_unchecked(secs: i64) -> Self {
        Self(secs)
    }

    pub(crate) fn new(secs: i64) -> Option<Self> {
        (Self::MIN.0..=Self::MAX.0)
            .contains(&secs)
            .then(|| Self(secs))
    }

    pub(crate) fn new_saturating(secs: i64) -> Self {
        Self(secs.clamp(Self::MIN.0, Self::MAX.0))
    }

    pub(crate) fn get(self) -> i64 {
        self.0
    }

    pub(crate) fn offset(self, x: OffsetS) -> Option<Self> {
        Self::new(self.0 + x.0 as i64)
    }

    pub(crate) fn saturating_offset(self, x: OffsetS) -> Self {
        Self::new_saturating(self.0 + x.get() as i64)
    }

    pub(crate) fn saturating_add_i32(self, x: i32) -> Self {
        // Safe since both arguments are constrained far below i64/i32::MIN/MAX
        Self::new_saturating(self.0 + x as i64)
    }

    pub(crate) fn as_days(self) -> UnixDay {
        UnixDay::new_unchecked((self.0 / S_PER_DAY as i64) as _)
    }

    pub(crate) fn date(self) -> Date {
        self.as_days().date()
    }
}

impl TryFrom<i64> for EpochSecs {
    type Error = ();

    fn try_from(value: i64) -> Result<Self, Self::Error> {
        EpochSecs::new(value).ok_or(())
    }
}

pub(crate) struct UnixDay(i32);

impl UnixDay {
    const MIN: i32 = 0; // TODO
    const MAX: i32 = 365_205; // TODO
    pub(crate) fn new_unchecked(days: i32) -> Self {
        Self(days)
    }

    pub(crate) fn new(days: i32) -> Option<Self> {
        (0..=365_205).contains(&days).then(|| Self(days))
    }

    pub(crate) fn get(self) -> i32 {
        self.0
    }

    pub(crate) fn date(self) -> Date {
        Date::from_unix_days_unchecked(self.0)
    }
}

pub(crate) static S_PER_DAY: i32 = 86_400;
pub(crate) static NS_PER_DAY: i128 = S_PER_DAY as i128 * 1_000_000_000;
pub(crate) static MAX_OFFSET: Offset = S_PER_DAY - 1; // 24 hours exclusive

// TODO: rename to abs_lte?
/// Check if a value is within a range, casting types safely if needed
pub(crate) fn in_range<T, U>(value: T, max: U) -> bool
where
    T: Copy + PartialOrd + Neg<Output = T>,
    U: Into<T> + Copy,
{
    let max_t = max.into();
    (-max_t..=max_t).contains(&value)
}

/// Ensure a value is within a range, casting it to the target type if needed
pub(crate) fn cap<T, U>(value: T, max: U) -> Option<U>
where
    T: Copy + PartialOrd + Neg<Output = T> + TryInto<U> + Debug,
    U: Into<T> + Copy + Debug,
    <T as TryInto<U>>::Error: Debug,
{
    in_range(value, max).then(|| {
        value
            // Safe conversion since we just checked the range
            .try_into()
            .unwrap()
    })
}

#[allow(unused_imports)]
pub(crate) use {pack, parse_args_kwargs, pydatetime::*, pyobject::*, pytype::*, unpack_one};
