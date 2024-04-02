use core::ffi::{c_char, c_int, c_long, c_uint, c_void};
use core::{mem, ptr};
use pyo3_ffi::*;
use std::cmp::min;
use std::collections::hash_map::DefaultHasher;
use std::fmt;
use std::hash::{Hash, Hasher};
use std::ops::Neg;
use std::ptr::null_mut as NULL;

use crate::common::{c_str, get_digit, propagate_exc, py_str, pystr_to_utf8, raise, try_get_long};
use crate::date::MAX_YEAR;
use crate::ModuleState;

#[repr(C)]
#[derive(Debug, Eq, PartialEq, Ord, PartialOrd, Hash, Copy, Clone)]
pub(crate) struct DateDelta {
    pub(crate) years: i16,
    pub(crate) months: i32,
    pub(crate) weeks: i32,
    pub(crate) days: i32,
}

#[repr(C)]
pub(crate) struct PyDateDelta {
    _ob_base: PyObject,
    pub(crate) delta: DateDelta,
}

impl Neg for DateDelta {
    type Output = Self;

    fn neg(self) -> Self {
        Self {
            years: -self.years,
            months: -self.months,
            weeks: -self.weeks,
            days: -self.days,
        }
    }
}

const MAX_MONTHS: i32 = (MAX_YEAR * 12) as i32;
const MAX_WEEKS: i32 = (MAX_YEAR * 53) as i32;
const MAX_DAYS: i32 = (MAX_YEAR * 366) as i32;

pub(crate) const SINGLETONS: [(&str, DateDelta); 1] = [(
    "ZERO\0",
    DateDelta {
        years: 0,
        months: 0,
        weeks: 0,
        days: 0,
    },
)];

impl fmt::Display for DateDelta {
    fn fmt(&self, f: &mut fmt::Formatter<'_>) -> fmt::Result {
        let content = [
            if self.years != 0 {
                format!("{}Y", self.years)
            } else {
                String::new()
            },
            if self.months != 0 {
                format!("{}M", self.months)
            } else {
                String::new()
            },
            if self.weeks != 0 {
                format!("{}W", self.weeks)
            } else {
                String::new()
            },
            if self.days != 0 {
                format!("{}D", self.days)
            } else {
                String::new()
            },
        ]
        .join("");
        write!(f, "P{}", if content.is_empty() { "0D" } else { &content })
    }
}

unsafe extern "C" fn __new__(
    subtype: *mut PyTypeObject,
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
        "|$llll:DateDelta\0".as_ptr().cast::<c_char>(),
        vec![
            "years\0".as_ptr().cast::<c_char>() as *mut c_char,
            "months\0".as_ptr().cast::<c_char>() as *mut c_char,
            "weeks\0".as_ptr().cast::<c_char>() as *mut c_char,
            "days\0".as_ptr().cast::<c_char>() as *mut c_char,
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

    if years < -MAX_YEAR || years > MAX_YEAR {
        raise!(PyExc_ValueError, "years out of bounds");
    }
    if months < -MAX_MONTHS as c_long || months > MAX_MONTHS as c_long {
        raise!(PyExc_ValueError, "months out of bounds");
    }
    if weeks < -MAX_WEEKS as c_long || weeks > MAX_WEEKS as c_long {
        raise!(PyExc_ValueError, "weeks out of bounds");
    }
    if days < -MAX_DAYS as c_long || days > MAX_DAYS as c_long {
        raise!(PyExc_ValueError, "days out of bounds");
    }

    new_unchecked(
        subtype,
        DateDelta {
            years: years as i16,
            months: months as i32,
            weeks: weeks as i32,
            days: days as i32,
        },
    )
    .cast()
}

pub(crate) unsafe extern "C" fn years(
    module: *mut PyObject,
    amount: *mut PyObject,
) -> *mut PyObject {
    let parsed_amount = try_get_long!(amount);
    if parsed_amount < -MAX_YEAR || parsed_amount > MAX_YEAR {
        raise!(PyExc_ValueError, "years out of bounds");
    }
    new_unchecked(
        (*PyModule_GetState(module).cast::<crate::ModuleState>()).date_delta_type,
        DateDelta {
            years: parsed_amount as i16,
            months: 0,
            weeks: 0,
            days: 0,
        },
    )
    .cast()
}

pub(crate) unsafe extern "C" fn months(
    module: *mut PyObject,
    amount: *mut PyObject,
) -> *mut PyObject {
    let parsed_amount = try_get_long!(amount);
    if parsed_amount < -MAX_MONTHS as c_long || parsed_amount > MAX_MONTHS as c_long {
        raise!(PyExc_ValueError, "months out of bounds");
    }
    new_unchecked(
        (*PyModule_GetState(module).cast::<crate::ModuleState>()).date_delta_type,
        DateDelta {
            years: 0,
            months: parsed_amount as i32,
            weeks: 0,
            days: 0,
        },
    )
    .cast()
}

pub(crate) unsafe extern "C" fn weeks(
    module: *mut PyObject,
    amount: *mut PyObject,
) -> *mut PyObject {
    let parsed_amount = try_get_long!(amount);
    if parsed_amount < -MAX_WEEKS as c_long || parsed_amount > MAX_WEEKS as c_long {
        raise!(PyExc_ValueError, "weeks out of bounds");
    }
    new_unchecked(
        (*PyModule_GetState(module).cast::<crate::ModuleState>()).date_delta_type,
        DateDelta {
            years: 0,
            months: 0,
            weeks: parsed_amount as i32,
            days: 0,
        },
    )
    .cast()
}

pub(crate) unsafe extern "C" fn days(
    module: *mut PyObject,
    amount: *mut PyObject,
) -> *mut PyObject {
    let parsed_amount = try_get_long!(amount);
    if parsed_amount < -MAX_DAYS as c_long || parsed_amount > MAX_DAYS as c_long {
        raise!(PyExc_ValueError, "days out of bounds");
    }
    new_unchecked(
        (*PyModule_GetState(module).cast::<crate::ModuleState>()).date_delta_type,
        DateDelta {
            years: 0,
            months: 0,
            weeks: 0,
            days: parsed_amount as i32,
        },
    )
    .cast()
}

unsafe extern "C" fn richcmp(slf: *mut PyObject, other: *mut PyObject, op: c_int) -> *mut PyObject {
    let result: *mut PyObject;
    if Py_TYPE(other) != Py_TYPE(slf) {
        result = Py_NotImplemented();
    } else {
        let slf = (*slf.cast::<PyDateDelta>()).delta;
        let other = (*other.cast::<PyDateDelta>()).delta;
        result = match op {
            pyo3_ffi::Py_EQ => {
                if slf == other {
                    Py_True()
                } else {
                    Py_False()
                }
            }
            pyo3_ffi::Py_NE => {
                if slf != other {
                    Py_True()
                } else {
                    Py_False()
                }
            }
            _ => Py_NotImplemented(),
        };
    }
    Py_INCREF(result);
    result
}

// TODO: cache this value?
unsafe extern "C" fn __hash__(slf: *mut PyObject) -> Py_hash_t {
    let date = (*slf.cast::<PyDateDelta>()).delta;
    let mut hasher = DefaultHasher::new();
    date.hash(&mut hasher);
    // TODO: is this OK?
    hasher.finish() as Py_hash_t
}

unsafe extern "C" fn __neg__(slf: *mut PyObject) -> *mut PyObject {
    let date = (*slf.cast::<PyDateDelta>()).delta;
    new_unchecked(
        Py_TYPE(slf),
        DateDelta {
            years: -date.years,
            months: -date.months,
            weeks: -date.weeks,
            days: -date.days,
        },
    )
    .cast()
}

unsafe extern "C" fn __bool__(slf: *mut PyObject) -> c_int {
    let date = (*slf.cast::<PyDateDelta>()).delta;
    !(date.years == 0 && date.months == 0 && date.weeks == 0 && date.days == 0) as c_int
}

unsafe extern "C" fn __repr__(slf: *mut PyObject) -> *mut PyObject {
    let delta = (*slf.cast::<PyDateDelta>()).delta;
    py_str(format!("DateDelta({})", delta).as_str())
}

unsafe extern "C" fn __str__(slf: *mut PyObject) -> *mut PyObject {
    let delta = (*slf.cast::<PyDateDelta>()).delta;
    py_str(format!("{}", delta).as_str())
}

unsafe extern "C" fn __mul__(slf: *mut PyObject, factor_obj: *mut PyObject) -> *mut PyObject {
    let factor = try_get_long!(factor_obj);
    if factor == 1 {
        Py_INCREF(slf);
        return slf;
    }
    let mut delta = (*slf.cast::<PyDateDelta>()).delta;
    // Overflow checks that allow us to do `factor as i16/i32` later
    if delta.years != 0 && (factor > i16::MAX as c_long || factor < i16::MIN as c_long)
        || factor > i32::MAX as c_long
        || factor < i32::MIN as c_long
    {
        raise!(PyExc_ValueError, "Multiplication result out of range");
    }
    if let (Some(years), Some(months), Some(weeks), Some(days)) = (
        delta.years.checked_mul(factor as i16),
        delta.months.checked_mul(factor as i32),
        delta.weeks.checked_mul(factor as i32),
        delta.days.checked_mul(factor as i32),
    ) {
        delta = DateDelta {
            years,
            months,
            weeks,
            days,
        };
    } else {
        raise!(PyExc_ValueError, "Multiplication result out of range");
    }
    if !is_in_range(delta) {
        raise!(PyExc_ValueError, "Multiplication result out of range");
    }
    new_unchecked(Py_TYPE(slf), delta).cast()
}

unsafe extern "C" fn __add__(slf: *mut PyObject, other: *mut PyObject) -> *mut PyObject {
    if Py_TYPE(other) != Py_TYPE(slf) {
        let result = Py_NotImplemented();
        Py_INCREF(result);
        return result;
    }
    let a = (*other.cast::<PyDateDelta>()).delta;
    let b = (*slf.cast::<PyDateDelta>()).delta;
    let new = DateDelta {
        // don't need to check for overflow here, since valid deltas well below overflow
        years: a.years + b.years,
        months: a.months + b.months,
        weeks: a.weeks + b.weeks,
        days: a.days + b.days,
    };
    if !is_in_range(new) {
        raise!(PyExc_ValueError, "Addition result out of range");
    }
    new_unchecked(Py_TYPE(slf), new).cast()
}

unsafe extern "C" fn __sub__(slf: *mut PyObject, other: *mut PyObject) -> *mut PyObject {
    if Py_TYPE(other) != Py_TYPE(slf) {
        let result = Py_NotImplemented();
        Py_INCREF(result);
        return result;
    }
    let a = (*slf.cast::<PyDateDelta>()).delta;
    let b = (*other.cast::<PyDateDelta>()).delta;
    let new = DateDelta {
        // don't need to check for overflow here, since valid deltas well below overflow
        years: a.years - b.years,
        months: a.months - b.months,
        weeks: a.weeks - b.weeks,
        days: a.days - b.days,
    };
    if !is_in_range(new) {
        raise!(PyExc_ValueError, "Subtraction result out of range");
    }
    new_unchecked(Py_TYPE(slf), new).cast()
}

unsafe extern "C" fn __abs__(slf: *mut PyObject) -> *mut PyObject {
    let delta = (*slf.cast::<PyDateDelta>()).delta;
    if delta.years >= 0 && delta.months >= 0 && delta.weeks >= 0 && delta.days >= 0 {
        Py_INCREF(slf);
        return slf;
    }
    new_unchecked(
        Py_TYPE(slf),
        DateDelta {
            years: delta.years.abs(),
            months: delta.months.abs(),
            weeks: delta.weeks.abs(),
            days: delta.days.abs(),
        },
    )
    .cast()
}

static mut SLOTS: &[PyType_Slot] = &[
    PyType_Slot {
        slot: Py_tp_new,
        pfunc: __new__ as *mut c_void,
    },
    PyType_Slot {
        slot: Py_tp_doc,
        pfunc: "A calendar date type\0".as_ptr() as *mut c_void,
    },
    PyType_Slot {
        slot: Py_tp_methods,
        pfunc: unsafe { METHODS.as_ptr() as *mut c_void },
    },
    PyType_Slot {
        slot: Py_tp_getset,
        pfunc: unsafe { GETSETTERS.as_ptr() as *mut c_void },
    },
    PyType_Slot {
        slot: Py_tp_members,
        pfunc: unsafe { MEMBERS.as_ptr() as *mut c_void },
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

static mut MEMBERS: &[PyMemberDef] = &[PyMemberDef {
    name: NULL(),
    type_code: 0,
    offset: 0,
    flags: 0,
    doc: NULL(),
}];

unsafe extern "C" fn identity(slf: *mut PyObject, _: *mut PyObject) -> *mut PyObject {
    Py_INCREF(slf);
    slf
}

unsafe extern "C" fn canonical_format(slf: *mut PyObject, _: *mut PyObject) -> *mut PyObject {
    __str__(slf)
}

// parse the prefix of an ISO8601 duration, e.g. `P`, `-P`, `+P`,
fn parse_prefix(s: &[u8]) -> Option<(bool, &[u8])> {
    match s[0] {
        b'P' => Some((false, &s[1..])),
        b'-' => {
            if s[1] == b'P' {
                Some((true, &s[2..]))
            } else {
                None
            }
        }
        b'+' => {
            if s[1] == b'P' {
                Some((false, &s[2..]))
            } else {
                None
            }
        }
        _ => None,
    }
}

#[derive(Debug, PartialEq, Eq, PartialOrd, Ord, Hash, Copy, Clone)]
enum Unit {
    Years,
    Months,
    Weeks,
    Days,
}

fn finish_parsing_component(s: &[u8], value: i32) -> Option<(i32, Unit, &[u8])> {
    let sign = value.signum();
    let mut tally = value * sign;
    // We limit parsing to 8 digits to prevent overflow
    for i in 0..min(s.len(), 8) {
        match s[i] {
            b'Y' if -MAX_YEAR as i32 <= tally && tally <= MAX_YEAR as i32 => {
                return Some((tally * sign, Unit::Years, &s[i + 1..]))
            }
            b'M' if -MAX_MONTHS <= tally && tally <= MAX_MONTHS => {
                return Some((tally * sign, Unit::Months, &s[i + 1..]))
            }
            b'W' if -MAX_WEEKS <= tally && tally <= MAX_WEEKS => {
                return Some((tally * sign, Unit::Weeks, &s[i + 1..]))
            }
            b'D' if -MAX_DAYS <= tally && tally <= MAX_DAYS => {
                return Some((tally * sign, Unit::Days, &s[i + 1..]))
            }
            c if c.is_ascii_digit() => tally = tally * 10 + (c - b'0') as i32,
            _ => {
                return None;
            }
        }
    }
    None
}

// parse a component of a ISO8601 duration, e.g. `6Y`, `-56M`, `+2W`, `0D`
fn parse_component(s: &[u8]) -> Option<(i32, Unit, &[u8])> {
    if s.len() < 2 {
        return None;
    }
    match s[0] {
        b'-' => finish_parsing_component(&s[2..], -(get_digit!(s, 1) as i32)),
        b'+' => finish_parsing_component(&s[2..], get_digit!(s, 1) as i32),
        c if c.is_ascii_digit() => finish_parsing_component(&s[1..], (c - b'0') as i32),
        _ => None,
    }
}

unsafe extern "C" fn from_canonical_format(
    type_: *mut PyObject,
    str: *mut PyObject,
) -> *mut PyObject {
    let mut s = pystr_to_utf8!(str, "argument must be str");
    if s.len() == 0 {
        raise!(PyExc_ValueError, "Invalid date delta format: %R", str);
    }
    let mut years = 0;
    let mut months = 0;
    let mut weeks = 0;
    let mut days = 0;
    let mut last_unit: Option<Unit> = None;
    let negated;

    match parse_prefix(s) {
        Some((neg, rest)) => {
            negated = neg;
            s = rest;
        }
        None => {
            raise!(PyExc_ValueError, "Invalid date delta format: %R", str);
        }
    }

    while s.len() > 0 {
        // FUTURE: there's still some optimization to be done here...
        if let Some((value, unit, rest)) = parse_component(s) {
            match (unit, last_unit) {
                (Unit::Years, None) => {
                    years = value;
                    last_unit = Some(Unit::Years);
                }
                (Unit::Months, None | Some(Unit::Years)) => {
                    months = value;
                    last_unit = Some(Unit::Months);
                }
                (Unit::Weeks, None | Some(Unit::Years | Unit::Months)) => {
                    weeks = value;
                    last_unit = Some(Unit::Weeks);
                }
                (Unit::Days, None | Some(Unit::Years | Unit::Months | Unit::Weeks)) => {
                    days = value;
                    last_unit = Some(Unit::Days);
                }
                _ => {
                    // i.e. the order of the components is wrong
                    raise!(PyExc_ValueError, "Invalid date delta format: %R", str);
                }
            }
            s = rest;
        } else {
            // i.e. the component is invalid
            raise!(PyExc_ValueError, "Invalid date delta format: %R", str);
        }
    }

    // i.e. there must be at least one component (`P` alone is invalid)
    if last_unit.is_none() {
        raise!(PyExc_ValueError, "Invalid date delta format: %R", str);
    }

    new_unchecked(
        type_.cast::<PyTypeObject>(),
        DateDelta {
            years: if negated { -years } else { years } as i16,
            months: if negated { -months } else { months },
            weeks: if negated { -weeks } else { weeks },
            days: if negated { -days } else { days },
        },
    )
    .cast()
}

unsafe extern "C" fn as_tuple(slf: *mut PyObject, _: *mut PyObject) -> *mut PyObject {
    let delta = (*slf.cast::<PyDateDelta>()).delta;
    PyTuple_Pack(
        4,
        PyLong_FromLong(delta.years as c_long),
        PyLong_FromLong(delta.months as c_long),
        PyLong_FromLong(delta.weeks as c_long),
        PyLong_FromLong(delta.days as c_long),
    )
}

unsafe extern "C" fn reduce(
    slf: *mut PyObject,
    type_: *mut PyTypeObject,
    // All args are unused. We don't need to check this since __reduce__
    // is only called internally by pickle (without arguments).
    _: *const *mut PyObject,
    _: Py_ssize_t,
    _: *mut PyObject,
) -> *mut PyObject {
    let module = ModuleState::from(type_);
    let delta = (*slf.cast::<PyDateDelta>()).delta;
    PyTuple_Pack(
        2,
        (*module).unpickle_date_delta,
        propagate_exc!(PyTuple_Pack(
            4,
            PyLong_FromLong(delta.years as c_long),
            PyLong_FromLong(delta.months as c_long),
            PyLong_FromLong(delta.weeks as c_long),
            PyLong_FromLong(delta.days as c_long)
        )),
    )
}

// OPTIMIZE: a more efficient pickle?
pub(crate) unsafe extern "C" fn unpickle(
    module: *mut PyObject,
    args: *mut *mut PyObject,
    nargs: Py_ssize_t,
) -> *mut PyObject {
    if PyVectorcall_NARGS(nargs as usize) != 4 {
        raise!(PyExc_TypeError, "Invalid pickle data");
    }
    new_unchecked(
        (*PyModule_GetState(module).cast::<crate::ModuleState>()).date_delta_type,
        DateDelta {
            years: try_get_long!(*args.offset(0)) as i16,
            months: try_get_long!(*args.offset(1)) as i32,
            weeks: try_get_long!(*args.offset(2)) as i32,
            days: try_get_long!(*args.offset(3)) as i32,
        },
    )
    .cast()
}

unsafe extern "C" fn replace(
    slf: *mut PyObject,
    type_: *mut PyTypeObject,
    args: *const *mut PyObject,
    nargs: Py_ssize_t,
    kwnames: *mut PyObject,
) -> *mut PyObject {
    if PyVectorcall_NARGS(nargs as usize) != 0 {
        raise!(PyExc_TypeError, "replace() takes no positional arguments");
    }
    let delta = (*slf.cast::<PyDateDelta>()).delta;
    let mut years = delta.years;
    let mut months = delta.months;
    let mut weeks = delta.weeks;
    let mut days = delta.days;

    if !kwnames.is_null() {
        for i in 0..=Py_SIZE(kwnames).saturating_sub(1) {
            let name = PyTuple_GET_ITEM(kwnames, i as Py_ssize_t);
            let value = try_get_long!(*args.offset(i));
            if name == PyUnicode_InternFromString(c_str!("years")) {
                if value < -MAX_YEAR as c_long || value > MAX_YEAR as c_long {
                    raise!(PyExc_ValueError, "years out of bounds");
                }
                years = value as i16;
            } else if name == PyUnicode_InternFromString(c_str!("months")) {
                if value < -MAX_MONTHS as c_long || value > MAX_MONTHS as c_long {
                    raise!(PyExc_ValueError, "months out of bounds");
                }
                months = value as i32;
            } else if name == PyUnicode_InternFromString(c_str!("weeks")) {
                if value < -MAX_WEEKS as c_long || value > MAX_WEEKS as c_long {
                    raise!(PyExc_ValueError, "weeks out of bounds");
                }
                weeks = value as i32;
            } else if name == PyUnicode_InternFromString(c_str!("days")) {
                if value < -MAX_DAYS as c_long || value > MAX_DAYS as c_long {
                    raise!(PyExc_ValueError, "days out of bounds");
                }
                days = value as i32;
            } else {
                raise!(PyExc_TypeError, "Invalid keyword argument: %R", name);
            }
        }
    }

    new_unchecked(
        type_,
        DateDelta {
            years,
            months,
            weeks,
            days,
        },
    )
    .cast()
}

static mut METHODS: &[PyMethodDef] = &[
    PyMethodDef {
        ml_name: c_str!("__copy__"),
        ml_meth: PyMethodDefPointer {
            PyCFunction: identity,
        },
        ml_flags: METH_NOARGS,
        ml_doc: NULL(),
    },
    PyMethodDef {
        ml_name: c_str!("__deepcopy__"),
        ml_meth: PyMethodDefPointer {
            PyCFunction: identity,
        },
        ml_flags: METH_O,
        ml_doc: NULL(),
    },
    PyMethodDef {
        ml_name: c_str!("canonical_format"),
        ml_meth: PyMethodDefPointer {
            PyCFunction: canonical_format,
        },
        ml_flags: METH_NOARGS,
        ml_doc: c_str!("Return the canonical string representation"),
    },
    PyMethodDef {
        ml_name: c_str!("common_iso8601"),
        ml_meth: PyMethodDefPointer {
            PyCFunction: canonical_format,
        },
        ml_flags: METH_NOARGS,
        ml_doc: c_str!("Return the ISO 8601 string representation"),
    },
    PyMethodDef {
        ml_name: c_str!("from_canonical_format"),
        ml_meth: PyMethodDefPointer {
            PyCFunction: from_canonical_format,
        },
        ml_flags: METH_O | METH_CLASS,
        ml_doc: c_str!("Parse a canonical string representation"),
    },
    PyMethodDef {
        ml_name: c_str!("from_common_iso8601"),
        ml_meth: PyMethodDefPointer {
            PyCFunction: from_canonical_format,
        },
        ml_flags: METH_O | METH_CLASS,
        ml_doc: c_str!("Parse from the common ISO8601 period format"),
    },
    PyMethodDef {
        ml_name: c_str!("as_tuple"),
        ml_meth: PyMethodDefPointer {
            PyCFunction: as_tuple,
        },
        ml_flags: METH_NOARGS,
        ml_doc: c_str!("Return the date delta as a tuple"),
    },
    PyMethodDef {
        ml_name: c_str!("__reduce__"),
        ml_meth: PyMethodDefPointer { PyCMethod: reduce },
        ml_flags: METH_METHOD | METH_FASTCALL | METH_KEYWORDS,
        ml_doc: NULL(),
    },
    PyMethodDef {
        ml_name: c_str!("replace"),
        ml_meth: PyMethodDefPointer { PyCMethod: replace },
        ml_flags: METH_METHOD | METH_FASTCALL | METH_KEYWORDS,
        ml_doc: c_str!("Return a new date delta with the specified components replaced"),
    },
    PyMethodDef::zeroed(),
];

unsafe extern "C" fn get_years(slf: *mut PyObject, _: *mut c_void) -> *mut PyObject {
    PyLong_FromLong((*slf.cast::<PyDateDelta>()).delta.years as c_long)
}

unsafe extern "C" fn get_months(slf: *mut PyObject, _: *mut c_void) -> *mut PyObject {
    PyLong_FromLong((*slf.cast::<PyDateDelta>()).delta.months as c_long)
}

unsafe extern "C" fn get_weeks(slf: *mut PyObject, _: *mut c_void) -> *mut PyObject {
    PyLong_FromLong((*slf.cast::<PyDateDelta>()).delta.weeks as c_long)
}

unsafe extern "C" fn get_day(slf: *mut PyObject, _: *mut c_void) -> *mut PyObject {
    PyLong_FromLong((*slf.cast::<PyDateDelta>()).delta.days as c_long)
}

pub(crate) unsafe fn new_unchecked(type_: *mut PyTypeObject, d: DateDelta) -> *mut PyDateDelta {
    let f: allocfunc = (*type_).tp_alloc.expect("tp_alloc is not set");
    let slf = propagate_exc!(f(type_, 0).cast::<PyDateDelta>());
    ptr::addr_of_mut!((*slf).delta).write(d);
    slf
}

pub(crate) unsafe fn is_in_range(d: DateDelta) -> bool {
    d.years >= -MAX_YEAR as i16
        && d.years <= MAX_YEAR as i16
        && d.months >= -MAX_MONTHS
        && d.months <= MAX_MONTHS
        && d.weeks >= -MAX_WEEKS
        && d.weeks <= MAX_WEEKS
        && d.days >= -MAX_DAYS
        && d.days <= MAX_DAYS
}

static mut GETSETTERS: &[PyGetSetDef] = &[
    PyGetSetDef {
        name: c_str!("years"),
        get: Some(get_years),
        set: None,
        doc: c_str!("The year component"),
        closure: NULL(),
    },
    PyGetSetDef {
        name: c_str!("months"),
        get: Some(get_months),
        set: None,
        doc: c_str!("The month component"),
        closure: NULL(),
    },
    PyGetSetDef {
        name: c_str!("weeks"),
        get: Some(get_weeks),
        set: None,
        doc: c_str!("The week component"),
        closure: NULL(),
    },
    PyGetSetDef {
        name: c_str!("days"),
        get: Some(get_day),
        set: None,
        doc: c_str!("The day component"),
        closure: NULL(),
    },
    PyGetSetDef {
        name: NULL(),
        get: None,
        set: None,
        doc: NULL(),
        closure: NULL(),
    },
];

pub(crate) static mut SPEC: PyType_Spec = PyType_Spec {
    name: c_str!("whenever.DateDelta"),
    basicsize: mem::size_of::<PyDateDelta>() as c_int,
    itemsize: 0,
    flags: Py_TPFLAGS_DEFAULT as c_uint,
    slots: unsafe { SLOTS as *const [_] as *mut _ },
};

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn test_parse_prefix() {
        assert_eq!(parse_prefix(b"P56D"), Some((false, &b"56D"[..])));
        assert_eq!(parse_prefix(b"-P"), Some((true, &b""[..])));
        assert_eq!(parse_prefix(b"+P"), Some((false, &b""[..])));
        assert_eq!(parse_prefix(b"X43"), None);
        assert_eq!(parse_prefix(b"P"), Some((false, &b""[..])));
    }

    #[test]
    fn test_parse_component() {
        assert_eq!(parse_component(b"6Y"), Some((6, Unit::Years, &b""[..])));
        assert_eq!(
            parse_component(b"-56M9"),
            Some((-56, Unit::Months, &b"9"[..]))
        );
        assert_eq!(parse_component(b"+2W"), Some((2, Unit::Weeks, &b""[..])));
        assert_eq!(parse_component(b"0D98"), Some((0, Unit::Days, &b"98"[..])));
        assert_eq!(parse_component(b"D"), None);
        assert_eq!(parse_component(b"0"), None);
        assert_eq!(parse_component(b"+"), None);
        assert_eq!(parse_component(b"-"), None);
    }
}
