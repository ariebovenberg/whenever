use core::ffi::{c_int, c_long, c_void};
use core::{mem, ptr};
use pyo3_ffi::*;
use std::cmp::min;
use std::fmt;
use std::ops::Neg;
use std::ptr::null_mut as NULL;

use crate::common::*;
use crate::date::MAX_YEAR;
use crate::State;

// TODO: replace with non-enum to save space
#[derive(Debug, Eq, PartialEq, Copy, Clone)]
pub(crate) struct DateDelta {
    // invariant: these never have opposite signs
    pub(crate) months: i32,
    pub(crate) days: i32,
}

#[repr(C)]
pub(crate) struct PyDateDelta {
    _ob_base: PyObject,
    delta: DateDelta,
}

pub(crate) enum InitError {
    TooBig,
    MixedSign,
}

impl DateDelta {
    pub(crate) fn extract(obj: *mut PyObject) -> DateDelta {
        unsafe { (*obj.cast::<PyDateDelta>()).delta }
    }

    #[cfg(target_pointer_width = "32")]
    pub(crate) fn pyhash(self) -> Py_hash_t {
        hashmask(self.months as Py_hash_t ^ self.days as Py_hash_t)
    }

    #[cfg(target_pointer_width = "64")]
    pub(crate) fn pyhash(self) -> Py_hash_t {
        hashmask(self.months as Py_hash_t | (self.days as Py_hash_t) << 32)
    }

    pub(crate) fn new(months: i32, days: i32) -> Result<Self, InitError> {
        match (months.signum(), days.signum()) {
            (0, 0) => Ok(Self { months: 0, days: 0 }),
            (1, -1) | (-1, 1) => Err(InitError::MixedSign),
            (1 | 0, 1 | 0) => Ok(Self {
                months: (months < MAX_MONTHS)
                    .then_some(months)
                    .ok_or(InitError::TooBig)?,
                days: (days < MAX_DAYS).then_some(days).ok_or(InitError::TooBig)?,
            }),
            (-1 | 0, -1 | 0) => Ok(Self {
                months: (-months < MAX_MONTHS)
                    .then_some(months)
                    .ok_or(InitError::TooBig)?,
                days: (-days < MAX_DAYS)
                    .then_some(days)
                    .ok_or(InitError::TooBig)?,
            }),
            _ => unreachable!(),
        }
    }

    pub(crate) fn from_longs(months: c_long, days: c_long) -> Result<Self, InitError> {
        match (months.signum(), days.signum()) {
            (0, 0) => Ok(Self { months: 0, days: 0 }),
            (1, -1) | (-1, 1) => Err(InitError::MixedSign),
            (1 | 0, 1 | 0) => Ok(Self {
                months: (months < MAX_MONTHS as _)
                    .then_some(months as _)
                    .ok_or(InitError::TooBig)?,
                days: (days < MAX_DAYS as _)
                    .then_some(days as _)
                    .ok_or(InitError::TooBig)?,
            }),
            (-1 | 0, -1 | 0) => Ok(Self {
                months: (-months < MAX_MONTHS as _)
                    .then_some(months as _)
                    .ok_or(InitError::TooBig)?,
                days: (-days < MAX_DAYS as _)
                    .then_some(days as _)
                    .ok_or(InitError::TooBig)?,
            }),
            _ => unreachable!(),
        }
    }

    pub(crate) fn from_same_sign(months: i32, days: i32) -> Option<Self> {
        debug_assert!(months >= 0 && days >= 0 || months <= 0 && days <= 0);
        (months.abs() < MAX_MONTHS && days.abs() < MAX_DAYS).then_some(Self { months, days })
    }

    pub(crate) fn from_months(months: i32) -> Option<Self> {
        (months.abs() < MAX_MONTHS).then_some(Self { months, days: 0 })
    }

    pub(crate) fn from_days(days: i32) -> Option<Self> {
        (days.abs() < MAX_DAYS).then_some(Self { months: 0, days })
    }

    pub(crate) fn checked_mul(self, factor: i32) -> Option<Self> {
        let Self { months, days } = self;
        months
            .checked_mul(factor)
            .zip(days.checked_mul(factor))
            .and_then(|(months, days)| Self::from_same_sign(months, days))
    }

    pub(crate) fn checked_add(self, other: Self) -> Result<Self, InitError> {
        Self::new(self.months + other.months, self.days + other.days)
    }
}

impl Neg for DateDelta {
    type Output = Self;

    fn neg(self) -> Self {
        Self {
            months: -self.months,
            days: -self.days,
        }
    }
}

const MAX_MONTHS: i32 = (MAX_YEAR * 12) as i32;
const MAX_DAYS: i32 = (MAX_YEAR * 366) as i32;

pub(crate) const SINGLETONS: [(&str, DateDelta); 1] =
    [("ZERO\0", DateDelta { months: 0, days: 0 })];

impl fmt::Display for DateDelta {
    fn fmt(&self, f: &mut fmt::Formatter<'_>) -> fmt::Result {
        let Self {
            mut months,
            mut days,
        } = *self;
        if months < 0 || days < 0 {
            write!(f, "-P")?;
            months = -months;
            days = -days;
        } else if months == 0 && days == 0 {
            return write!(f, "P0D");
        } else {
            write!(f, "P")?;
        }
        let years = months / 12;
        months %= 12;
        if years != 0 {
            write!(f, "{}Y", years)?;
        }
        if months != 0 {
            write!(f, "{}M", months)?;
        }
        if days != 0 {
            write!(f, "{}D", days)?;
        }
        Ok(())
    }
}

unsafe extern "C" fn __new__(
    cls: *mut PyTypeObject,
    args: *mut PyObject,
    kwargs: *mut PyObject,
) -> *mut PyObject {
    let mut years: c_long = 0;
    let mut months: c_long = 0;
    let mut weeks: c_long = 0;
    let mut days: c_long = 0;

    // FUTURE: parse them manually, which is more efficient
    if PyArg_ParseTupleAndKeywords(
        args,
        kwargs,
        c_str!("|$llll:DateDelta"),
        vec![
            c_str!("years") as *mut _,
            c_str!("months") as *mut _,
            c_str!("weeks") as *mut _,
            c_str!("days") as *mut _,
            NULL(),
        ]
        .as_mut_ptr(),
        &mut years,
        &mut months,
        &mut weeks,
        &mut days,
    ) == 0
    {
        return NULL();
    }
    match years
        .checked_mul(12)
        .and_then(|m| m.checked_add(months))
        .zip(weeks.checked_mul(7).and_then(|d| d.checked_add(days)))
        .ok_or(InitError::TooBig)
        .and_then(|(m, d)| DateDelta::from_longs(m, d))
    {
        Ok(delta) => new_unchecked(cls, delta),
        Err(InitError::TooBig) => raise!(PyExc_ValueError, "DateDelta out of bounds"),
        Err(InitError::MixedSign) => raise!(PyExc_ValueError, "Mixed sign in DateDelta"),
    }
}

pub(crate) unsafe extern "C" fn years(
    module: *mut PyObject,
    amount: *mut PyObject,
) -> *mut PyObject {
    new_unchecked(
        State::for_mod(module).date_delta_type,
        unwrap_or_raise!(
            pyint_as_long!(amount)
                .checked_mul(12)
                .and_then(|m| i32::try_from(m).ok())
                .and_then(|m| DateDelta::from_months(m)),
            PyExc_ValueError,
            "value out of bounds"
        ),
    )
}

pub(crate) unsafe extern "C" fn months(
    module: *mut PyObject,
    amount: *mut PyObject,
) -> *mut PyObject {
    new_unchecked(
        State::for_mod(module).date_delta_type,
        unwrap_or_raise!(
            i32::try_from(pyint_as_long!(amount))
                .ok()
                .and_then(|m| DateDelta::from_months(m)),
            PyExc_ValueError,
            "value out of bounds"
        ),
    )
}

pub(crate) unsafe extern "C" fn weeks(
    module: *mut PyObject,
    amount: *mut PyObject,
) -> *mut PyObject {
    new_unchecked(
        State::for_mod(module).date_delta_type,
        unwrap_or_raise!(
            pyint_as_long!(amount)
                .checked_mul(7)
                .and_then(|d| i32::try_from(d).ok())
                .and_then(|d| DateDelta::from_days(d)),
            PyExc_ValueError,
            "value out of bounds"
        ),
    )
}

pub(crate) unsafe extern "C" fn days(
    module: *mut PyObject,
    amount: *mut PyObject,
) -> *mut PyObject {
    new_unchecked(
        State::for_mod(module).date_delta_type,
        unwrap_or_raise!(
            i32::try_from(pyint_as_long!(amount))
                .ok()
                .and_then(|d| DateDelta::from_days(d)),
            PyExc_ValueError,
            "value out of bounds"
        ),
    )
}

unsafe extern "C" fn richcmp(
    a_obj: *mut PyObject,
    b_obj: *mut PyObject,
    op: c_int,
) -> *mut PyObject {
    newref(if Py_TYPE(b_obj) == Py_TYPE(a_obj) {
        let a = DateDelta::extract(a_obj);
        let b = DateDelta::extract(b_obj);
        match op {
            pyo3_ffi::Py_EQ => py_bool(a == b),
            pyo3_ffi::Py_NE => py_bool(a != b),
            _ => Py_NotImplemented(),
        }
    } else {
        Py_NotImplemented()
    })
}

unsafe extern "C" fn __hash__(slf: *mut PyObject) -> Py_hash_t {
    DateDelta::extract(slf).pyhash()
}

unsafe extern "C" fn __neg__(slf: *mut PyObject) -> *mut PyObject {
    new_unchecked(Py_TYPE(slf), -DateDelta::extract(slf))
}

unsafe extern "C" fn __bool__(slf: *mut PyObject) -> c_int {
    let DateDelta { months, days } = DateDelta::extract(slf);
    (months != 0 || days != 0).into()
}

unsafe extern "C" fn __repr__(slf: *mut PyObject) -> *mut PyObject {
    py_str(&format!("DateDelta({})", DateDelta::extract(slf)))
}

unsafe extern "C" fn __str__(slf: *mut PyObject) -> *mut PyObject {
    py_str(&format!("{}", DateDelta::extract(slf)))
}

unsafe extern "C" fn __mul__(slf: *mut PyObject, factor_obj: *mut PyObject) -> *mut PyObject {
    // TODO: reflexivity?
    let delta = DateDelta::extract(slf);
    let factor = pyint_as_long!(factor_obj);
    if factor == 1 {
        return newref(slf);
    };
    // FUTURE: optimize zero delta case
    new_unchecked(
        Py_TYPE(slf),
        unwrap_or_raise!(
            i32::try_from(factor)
                .ok()
                .and_then(|f| delta.checked_mul(f)),
            PyExc_ValueError,
            "multiplication factor or result out of bounds"
        ),
    )
}

unsafe extern "C" fn __add__(a_obj: *mut PyObject, b_obj: *mut PyObject) -> *mut PyObject {
    // TODO: reflexivity?
    // FUTURE: optimize zero delta case
    let cls = Py_TYPE(a_obj);
    if Py_TYPE(b_obj) == cls {
        match DateDelta::extract(a_obj).checked_add(DateDelta::extract(b_obj)) {
            Ok(new) => new_unchecked(cls, new),
            Err(InitError::TooBig) => raise!(PyExc_ValueError, "Addition result out of bounds"),
            Err(InitError::MixedSign) => raise!(PyExc_ValueError, "Mixed sign in DateDelta"),
        }
    } else {
        return newref(Py_NotImplemented());
    }
}

unsafe extern "C" fn __sub__(a_obj: *mut PyObject, b_obj: *mut PyObject) -> *mut PyObject {
    // TODO: reflexivity?
    // FUTURE: optimize zero delta case
    let cls = Py_TYPE(a_obj);
    if Py_TYPE(b_obj) == cls {
        match DateDelta::extract(a_obj).checked_add(-DateDelta::extract(b_obj)) {
            Ok(new) => new_unchecked(cls, new),
            Err(InitError::TooBig) => raise!(PyExc_ValueError, "Addition result out of bounds"),
            Err(InitError::MixedSign) => raise!(PyExc_ValueError, "Mixed sign in DateDelta"),
        }
    } else {
        return newref(Py_NotImplemented());
    }
}

unsafe extern "C" fn __abs__(slf: *mut PyObject) -> *mut PyObject {
    let DateDelta { months, days } = DateDelta::extract(slf);
    if months >= 0 && days >= 0 {
        newref(slf)
    } else {
        new_unchecked(
            Py_TYPE(slf),
            DateDelta {
                months: -months,
                days: -days,
            },
        )
    }
}

static mut SLOTS: &[PyType_Slot] = &[
    PyType_Slot {
        slot: Py_tp_new,
        pfunc: __new__ as *mut c_void,
    },
    PyType_Slot {
        slot: Py_tp_doc,
        pfunc: "A delta for calendar units\0".as_ptr() as *mut c_void,
    },
    PyType_Slot {
        slot: Py_tp_methods,
        pfunc: unsafe { METHODS.as_ptr() as *mut c_void },
    },
    PyType_Slot {
        slot: Py_tp_richcompare,
        pfunc: richcmp as *mut c_void,
    },
    PyType_Slot {
        slot: Py_tp_hash,
        pfunc: __hash__ as *mut c_void,
    },
    PyType_Slot {
        slot: Py_nb_negative,
        pfunc: __neg__ as *mut c_void,
    },
    PyType_Slot {
        slot: Py_tp_repr,
        pfunc: __repr__ as *mut c_void,
    },
    PyType_Slot {
        slot: Py_nb_bool,
        pfunc: __bool__ as *mut c_void,
    },
    PyType_Slot {
        slot: Py_tp_str,
        pfunc: __str__ as *mut c_void,
    },
    PyType_Slot {
        slot: Py_nb_positive,
        pfunc: identity as *mut c_void,
    },
    PyType_Slot {
        slot: Py_nb_multiply,
        pfunc: __mul__ as *mut c_void,
    },
    PyType_Slot {
        slot: Py_nb_add,
        pfunc: __add__ as *mut c_void,
    },
    PyType_Slot {
        slot: Py_nb_subtract,
        pfunc: __sub__ as *mut c_void,
    },
    PyType_Slot {
        slot: Py_nb_absolute,
        pfunc: __abs__ as *mut c_void,
    },
    PyType_Slot {
        slot: 0,
        pfunc: NULL(),
    },
];

unsafe extern "C" fn default_format(slf: *mut PyObject, _: *mut PyObject) -> *mut PyObject {
    __str__(slf)
}

// parse the prefix of an ISO8601 duration, e.g. `P`, `-P`, `+P`,
fn parse_prefix(s: &mut &[u8]) -> Option<bool> {
    debug_assert!(s.len() >= 2);
    match s[0] {
        b'P' => {
            let result = Some(false);
            *s = &s[1..];
            result
        }
        b'-' if s[1] == b'P' => {
            let result = Some(true);
            *s = &s[2..];
            result
        }
        b'+' if s[1] == b'P' => {
            let result = Some(false);
            *s = &s[2..];
            result
        }
        _ => None,
    }
}

#[derive(Debug, PartialEq, Eq, PartialOrd, Ord, Copy, Clone)]
enum Unit {
    Years,
    Months,
    Weeks,
    Days,
}

fn finish_parsing_component(s: &mut &[u8], mut value: i32) -> Option<(i32, Unit)> {
    // We limit parsing to 7 digits to prevent overflow
    for i in 1..min(s.len(), 7) {
        match s[i] {
            c if c.is_ascii_digit() => value = value * 10 + i32::from(c - b'0'),
            b'D' => {
                *s = &s[i + 1..];
                return Some((value, Unit::Days));
            }
            b'W' => {
                *s = &s[i + 1..];
                return Some((value, Unit::Weeks));
            }
            b'M' => {
                *s = &s[i + 1..];
                return Some((value, Unit::Months));
            }
            b'Y' => {
                *s = &s[i + 1..];
                return Some((value, Unit::Years));
            }
            _ => {
                return None;
            }
        }
    }
    None
}

// parse a component of a ISO8601 duration, e.g. `6Y`, `-56M`, `+2W`, `0D`
fn parse_component(s: &mut &[u8]) -> Option<(i32, Unit)> {
    if s.len() >= 2 && s[0].is_ascii_digit() {
        finish_parsing_component(s, (s[0] - b'0').into())
    } else {
        None
    }
}

unsafe extern "C" fn from_default_format(
    type_: *mut PyObject,
    s_obj: *mut PyObject,
) -> *mut PyObject {
    let s = &mut pystr_to_utf8!(s_obj, "argument must be str");
    if s.len() < 3 {
        // at least `P0D`
        raise!(PyExc_ValueError, "Invalid date delta format: %R", s_obj);
    }
    let mut months = 0;
    let mut days = 0;
    let mut prev_unit: Option<Unit> = None;

    let negated = unwrap_or_raise!(
        parse_prefix(s),
        PyExc_ValueError,
        "Invalid date delta format: %R",
        s_obj
    );

    while !s.is_empty() {
        if let Some((value, unit)) = parse_component(s) {
            match (unit, prev_unit.replace(unit)) {
                (Unit::Years, None) => {
                    months += value * 12;
                }
                (Unit::Months, None | Some(Unit::Years)) => {
                    months += value;
                }
                (Unit::Weeks, None | Some(Unit::Years | Unit::Months)) => {
                    days += value * 7;
                }
                (Unit::Days, _) => {
                    days += value;
                    if s.is_empty() {
                        break;
                    }
                    // i.e. there's more after the days component
                    raise!(PyExc_ValueError, "Invalid date delta format: %R", s_obj);
                }
                _ => {
                    // i.e. the order of the components is wrong
                    raise!(PyExc_ValueError, "Invalid date delta format: %R", s_obj);
                }
            }
        } else {
            // i.e. the component is invalid
            raise!(PyExc_ValueError, "Invalid date delta format: %R", s_obj);
        }
    }

    // i.e. there must be at least one component (`P` alone is invalid)
    if prev_unit.is_none() {
        raise!(PyExc_ValueError, "Invalid date delta format: %R", s_obj);
    }

    if negated {
        months *= -1;
        days *= -1;
    }
    new_unchecked(type_.cast(), DateDelta { months, days })
}

unsafe extern "C" fn in_months_days(slf: *mut PyObject, _: *mut PyObject) -> *mut PyObject {
    let DateDelta { months, days } = DateDelta::extract(slf);
    // TODO: refcounts
    PyTuple_Pack(
        2,
        PyLong_FromLong(months.into()),
        PyLong_FromLong(days.into()),
    )
}

unsafe extern "C" fn in_years_months_days(slf: *mut PyObject, _: *mut PyObject) -> *mut PyObject {
    let DateDelta { months, days } = DateDelta::extract(slf);
    let years = months / 12;
    let months = months % 12;
    PyTuple_Pack(
        3,
        PyLong_FromLong(years.into()),
        PyLong_FromLong(months.into()),
        PyLong_FromLong(days.into()),
    )
}

unsafe extern "C" fn __reduce__(slf: *mut PyObject, _: *mut PyObject) -> *mut PyObject {
    let DateDelta { months, days } = DateDelta::extract(slf);
    PyTuple_Pack(
        2,
        State::for_type(Py_TYPE(slf)).unpickle_date_delta,
        py_try!(PyTuple_Pack(
            2,
            PyLong_FromLong(months.into()),
            PyLong_FromLong(days.into()),
        )),
    )
}

pub(crate) unsafe extern "C" fn unpickle(
    module: *mut PyObject,
    args: *mut *mut PyObject,
    nargs: Py_ssize_t,
) -> *mut PyObject {
    if PyVectorcall_NARGS(nargs as usize) != 2 {
        raise!(PyExc_TypeError, "Invalid pickle data");
    }
    new_unchecked(
        State::for_mod(module).date_delta_type,
        DateDelta {
            months: PyLong_AsLong(*args) as _,
            days: PyLong_AsLong(*args.offset(1)) as _,
        },
    )
}

static mut METHODS: &[PyMethodDef] = &[
    method!(identity named "__copy__", ""),
    method!(identity named "__deepcopy__", "", METH_O),
    method!(default_format, ""),
    method!(default_format named "common_iso8601", "Return the ISO 8601 string representation"),
    classmethod!(from_default_format, "", METH_O),
    classmethod!(
        from_default_format named "from_common_iso8601",
        "Parse from the common ISO8601 period format",
        METH_O
    ),
    method!(
        in_months_days,
        "Return the date delta as a tuple of months and days"
    ),
    method!(
        in_years_months_days,
        "Return the date delta as a tuple of years, months, and days"
    ),
    method!(__reduce__, ""),
    PyMethodDef::zeroed(),
];

pub(crate) unsafe fn new_unchecked(type_: *mut PyTypeObject, d: DateDelta) -> *mut PyObject {
    let f: allocfunc = (*type_).tp_alloc.expect("tp_alloc is not set");
    let slf = py_try!(f(type_, 0).cast::<PyDateDelta>());
    ptr::addr_of_mut!((*slf).delta).write(d);
    slf.cast()
}

pub(crate) static mut SPEC: PyType_Spec = PyType_Spec {
    name: c_str!("whenever.DateDelta"),
    basicsize: mem::size_of::<PyDateDelta>() as _,
    itemsize: 0,
    flags: Py_TPFLAGS_DEFAULT as _,
    slots: unsafe { SLOTS as *const [_] as *mut _ },
};
