use core::ffi::{c_char, c_int, c_long, c_uint, c_void};
use core::{mem, ptr, ptr::null_mut as NULL};
use pyo3_ffi::*;
use std::cmp::min;
use std::fmt::{self, Display, Formatter};

use crate::common::{c_str, get_digit, propagate_exc, py_str, pystr_to_utf8, raise, try_get_int};
use crate::date_delta;
use crate::date_delta::{DateDelta, PyDateDelta};
use crate::ModuleState;

#[repr(C)]
#[derive(Debug, Eq, PartialEq, Ord, PartialOrd, Copy, Clone)]
pub struct Date {
    pub(crate) year: u16,
    pub(crate) month: u8,
    pub(crate) day: u8,
}

#[repr(C)]
pub(crate) struct PyDate {
    _ob_base: PyObject,
    date: Date,
    // TODO: use the extra padding to cache the ordinal?
}

impl Date {
    pub(crate) unsafe fn hash(self) -> u32 {
        mem::transmute::<_, u32>(self)
    }

    pub(crate) fn increment(mut self) -> Self {
        if self.day < days_in_month(self.year, self.month) {
            self.day += 1
        } else {
            self.day = 1;
            self.month = self.month % 12 + 1;
        }
        self
    }

    pub(crate) fn decrement(mut self) -> Self {
        if self.day > 1 {
            self.day -= 1;
        } else {
            self.day = days_in_month(self.year, self.month - 1);
            self.month = self.month.saturating_sub(1);
        }
        self
    }
}

impl Display for Date {
    fn fmt(&self, f: &mut Formatter<'_>) -> fmt::Result {
        write!(f, "{:04}-{:02}-{:02}", self.year, self.month, self.day)
    }
}

#[derive(Debug, Eq, PartialEq, Ord, PartialOrd)]
pub(crate) enum DateError {
    InvalidYear,
    InvalidMonth,
    InvalidDay,
}

impl DateError {
    pub(crate) unsafe fn set_pyerr(&self) {
        match self {
            DateError::InvalidYear => {
                PyErr_SetString(PyExc_ValueError, c_str!("year is out of range (1..9999)"));
            }
            DateError::InvalidMonth => {
                PyErr_SetString(PyExc_ValueError, c_str!("month must be in 1..12"));
            }
            DateError::InvalidDay => {
                PyErr_SetString(PyExc_ValueError, c_str!("day is out of range"));
            }
        }
    }
}

pub(crate) const MAX_YEAR: c_long = 9999;
const MIN_YEAR: c_long = 1;
const DAYS_IN_MONTH: [u8; 13] = [
    0, // 1-indexed
    31, 28, 31, 30, 31, 30, 31, 31, 30, 31, 30, 31,
];
const MIN_ORD: c_long = 1;
const MAX_ORD: c_long = 3_652_059;
const DAYS_BEFORE_MONTH: [u16; 13] = [
    0, // 1-indexed
    0, 31, 59, 90, 120, 151, 181, 212, 243, 273, 304, 334,
];
const DAYS_IN_400Y: u32 = 146_097;
const DAYS_IN_100Y: u32 = 36_524;
const DAYS_IN_4Y: u32 = 1_461;

fn is_leap(year: u16) -> bool {
    (year % 4 == 0 && year % 100 != 0) || year % 400 == 0
}

fn days_in_month(year: u16, month: u8) -> u8 {
    debug_assert!(month >= 1 && month <= 12);
    if month == 2 && is_leap(year) {
        29
    } else {
        DAYS_IN_MONTH[month as usize]
    }
}

pub(crate) fn in_range(year: c_long, month: c_long, day: c_long) -> Result<Date, DateError> {
    if year < MIN_YEAR || year > MAX_YEAR {
        return Err(DateError::InvalidYear);
    }
    if month < 1 || month > 12 {
        return Err(DateError::InvalidMonth);
    }
    let y = year as u16;
    let m = month as u8;
    if day < 1 || day > days_in_month(y, m) as c_long {
        return Err(DateError::InvalidDay);
    }
    Ok(Date {
        year: y,
        month: m,
        day: day as u8,
    })
}

unsafe extern "C" fn __new__(
    type_: *mut PyTypeObject,
    args: *mut PyObject,
    kwargs: *mut PyObject,
) -> *mut PyObject {
    let nargs = PyTuple_GET_SIZE(args);
    let nkwargs = if kwargs.is_null() {
        0
    } else {
        PyDict_Size(kwargs)
    };

    // Fast path for the most common case
    if nargs == 3 && nkwargs == 0 {
        new_checked(
            type_,
            try_get_int!(PyTuple_GET_ITEM(args, 0)),
            try_get_int!(PyTuple_GET_ITEM(args, 1)),
            try_get_int!(PyTuple_GET_ITEM(args, 2)),
        )
    } else if nargs + nkwargs > 3 {
        raise!(
            PyExc_TypeError,
            // TODO: reinstate formatting
            "Date() takes exactly 3 arguments",
        );
    // slow path: parse args and kwargs
    } else {
        let mut year: Option<c_long> = None;
        let mut month: Option<c_long> = None;
        let mut day: Option<c_long> = None;

        if nargs > 0 {
            year = Some(try_get_int!(PyTuple_GET_ITEM(args, 0)));
            if nargs > 1 {
                month = Some(try_get_int!(PyTuple_GET_ITEM(args, 1)));
                debug_assert!(nargs == 2); // follows from the first branches
            }
        }
        if nkwargs > 0 {
            let mut key_obj: *mut PyObject = NULL();
            let mut value_obj: *mut PyObject = NULL();
            let mut pos: Py_ssize_t = 0;
            while PyDict_Next(kwargs, &mut pos, &mut key_obj, &mut value_obj) != 0 {
                match pystr_to_utf8!(key_obj, "Kwargs keys must be str") {
                    b"year" => {
                        if year.replace(try_get_int!(value_obj)).is_some() {
                            raise!(
                                PyExc_TypeError,
                                "Date() got multiple values for argument 'year'"
                            );
                        }
                    }
                    b"month" => {
                        if month.replace(try_get_int!(value_obj)).is_some() {
                            raise!(
                                PyExc_TypeError,
                                "Date() got multiple values for argument 'month'"
                            );
                        }
                    }
                    b"day" => {
                        if day.replace(try_get_int!(value_obj)).is_some() {
                            raise!(
                                PyExc_TypeError,
                                "Date() got multiple values for argument 'day'"
                            );
                        }
                    }
                    _ => {
                        raise!(
                            PyExc_TypeError,
                            "Date() got an unexpected keyword argument: %R",
                            key_obj
                        );
                    }
                }
            }
        }
        new_checked(
            type_,
            match year {
                Some(year) => year,
                None => raise!(PyExc_TypeError, "Date() missing required argument 'year'"),
            },
            match month {
                Some(month) => month,
                None => raise!(PyExc_TypeError, "Date() missing required argument 'month'"),
            },
            match day {
                Some(day) => day,
                None => raise!(PyExc_TypeError, "Date() missing required argument 'day'"),
            },
        )
    }
}

unsafe extern "C" fn __repr__(slf: *mut PyObject) -> *mut PyObject {
    let date = (*slf.cast::<PyDate>()).date;
    py_str(format!("Date({:04}-{:02}-{:02})", date.year, date.month, date.day).as_str())
}

unsafe extern "C" fn __hash__(slf: *mut PyObject) -> Py_hash_t {
    // TODO: check this is valid on 32-bit systems
    (*slf.cast::<PyDate>()).date.hash() as Py_hash_t
}

unsafe extern "C" fn __richcmp__(
    slf: *mut PyObject,
    other: *mut PyObject,
    op: c_int,
) -> *mut PyObject {
    let result = if Py_TYPE(other) == Py_TYPE(slf) {
        let a = (*slf.cast::<PyDate>()).date;
        let b = (*other.cast::<PyDate>()).date;
        let cmp = match op {
            pyo3_ffi::Py_LT => a < b,
            pyo3_ffi::Py_LE => a <= b,
            pyo3_ffi::Py_EQ => a == b,
            pyo3_ffi::Py_NE => a != b,
            pyo3_ffi::Py_GT => a > b,
            pyo3_ffi::Py_GE => a >= b,
            _ => unreachable!(),
        };
        if cmp {
            Py_True()
        } else {
            Py_False()
        }
    } else {
        Py_NotImplemented()
    };
    Py_INCREF(result);
    result
}

unsafe extern "C" fn dealloc(slf: *mut PyObject) {
    let tp_free = PyType_GetSlot(Py_TYPE(slf), Py_tp_free);
    debug_assert_ne!(tp_free, NULL());
    let f: freefunc = std::mem::transmute(tp_free);
    f(slf.cast());
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
        slot: Py_tp_str,
        pfunc: canonical_format as *mut c_void,
    },
    PyType_Slot {
        slot: Py_tp_repr,
        pfunc: __repr__ as *mut c_void,
    },
    PyType_Slot {
        slot: Py_tp_richcompare,
        pfunc: __richcmp__ as *mut c_void,
    },
    PyType_Slot {
        slot: Py_tp_methods,
        pfunc: unsafe { METHODS.as_ptr() as *mut c_void },
    },
    PyType_Slot {
        slot: Py_nb_subtract,
        pfunc: __sub__ as *mut c_void,
    },
    PyType_Slot {
        slot: Py_nb_add,
        pfunc: __add__ as *mut c_void,
    },
    PyType_Slot {
        slot: Py_tp_getset,
        pfunc: unsafe { GETSETTERS.as_ptr() as *mut c_void },
    },
    PyType_Slot {
        slot: Py_tp_hash,
        pfunc: __hash__ as *mut c_void,
    },
    PyType_Slot {
        slot: Py_tp_members,
        pfunc: unsafe { MEMBERS.as_ptr() as *mut c_void },
    },
    PyType_Slot {
        slot: Py_tp_dealloc,
        pfunc: dealloc as *mut c_void,
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

unsafe extern "C" fn as_py_date(slf: *mut PyObject, _: *mut PyObject) -> *mut PyObject {
    let date = (*slf.cast::<PyDate>()).date;
    let api = *(*ModuleState::from(Py_TYPE(slf))).datetime_api;
    (api.Date_FromDate)(
        date.year as c_int,
        date.month as c_int,
        date.day as c_int,
        api.DateType,
    )
}

unsafe extern "C" fn from_py_date(cls: *mut PyObject, date: *mut PyObject) -> *mut PyObject {
    // TODO: allow subclasses?
    if PyDate_Check(date) == 0 {
        raise!(PyExc_TypeError, "argument must be datetime.date");
    }
    new_unchecked(
        cls.cast(),
        Date {
            year: PyDateTime_GET_YEAR(date) as u16,
            month: PyDateTime_GET_MONTH(date) as u8,
            day: PyDateTime_GET_DAY(date) as u8,
        },
    )
    .cast()
}

unsafe extern "C" fn canonical_format(slf: *mut PyObject, _: *mut PyObject) -> *mut PyObject {
    let date = (*slf.cast::<PyDate>()).date;
    py_str(format!("{:04}-{:02}-{:02}", date.year, date.month, date.day).as_str())
}

pub(crate) fn parse(s: &[u8]) -> Option<(u16, u8, u8)> {
    // TODO: allow length check to be skipped
    if s.len() != 10 {
        return None;
    }
    let year = get_digit!(s, 0) as u16 * 1000
        + get_digit!(s, 1) as u16 * 100
        + get_digit!(s, 2) as u16 * 10
        + get_digit!(s, 3) as u16;
    let month = get_digit!(s, 5) * 10 + get_digit!(s, 6);
    let day = get_digit!(s, 8) * 10 + get_digit!(s, 9);
    Some((year, month, day))
}

unsafe extern "C" fn from_canonical_format(cls: *mut PyObject, s: *mut PyObject) -> *mut PyObject {
    if let Some((y, m, d)) = parse(pystr_to_utf8!(s, "argument must be str")) {
        new_checked(cls.cast(), y as c_long, m as c_long, d as c_long).cast()
    } else {
        raise!(PyExc_ValueError, "Could not parse date: %R", s);
    }
}

unsafe extern "C" fn identity(slf: *mut PyObject, _: *mut PyObject) -> *mut PyObject {
    Py_INCREF(slf);
    slf
}

fn days_before_year(year: u16) -> u32 {
    debug_assert!(year >= 1);
    let y = (year - 1) as u32;
    return y * 365 + y / 4 - y / 100 + y / 400;
}

fn days_before_month(year: u16, month: u8) -> u16 {
    debug_assert!(month >= 1 && month <= 12);
    let mut days = DAYS_BEFORE_MONTH[month as usize];
    if month > 2 && is_leap(year) {
        days += 1;
    }
    days
}

pub(crate) fn ymd_to_ord(year: u16, month: u8, day: u8) -> u32 {
    days_before_year(year) + days_before_month(year, month) as u32 + day as u32
}

unsafe extern "C" fn day_of_week(slf: *mut PyObject, _: *mut PyObject) -> *mut PyObject {
    let date = (*slf.cast::<PyDate>()).date;
    PyLong_FromLong(((ymd_to_ord(date.year, date.month, date.day) + 6) % 7 + 1).into())
}

unsafe extern "C" fn __reduce__(
    slf: *mut PyObject,
    type_: *mut PyTypeObject,
    // All args are unused. We don't need to check this since __reduce__
    // is only called internally by pickle (without arguments).
    _: *const *mut PyObject,
    _: Py_ssize_t,
    _: *mut PyObject,
) -> *mut PyObject {
    let module = ModuleState::from(type_);
    let date = (*slf.cast::<PyDate>()).date;
    PyTuple_Pack(
        2,
        (*module).unpickle_date,
        propagate_exc!(PyTuple_Pack(
            3,
            PyLong_FromLong(date.year as c_long),
            PyLong_FromLong(date.month as c_long),
            PyLong_FromLong(date.day as c_long),
        )),
    )
}

pub fn ord_to_ymd(ord: u32) -> (u16, u8, u8) {
    // based on the algorithm from datetime.date.fromordinal
    let mut n = ord - 1;
    let n400 = n / DAYS_IN_400Y;
    n %= DAYS_IN_400Y;
    let n100 = n / DAYS_IN_100Y;
    n %= DAYS_IN_100Y;
    let n4 = n / DAYS_IN_4Y;
    n %= DAYS_IN_4Y;
    let n1 = n / 365;
    n %= 365;

    let year = (400 * n400 + 100 * n100 + 4 * n4 + n1 + 1) as u16;
    if (n1 == 4) || (n100 == 4) {
        (year - 1, 12, 31)
    } else {
        let leap = (n1 == 3) && (n4 != 24 || n100 == 3);
        debug_assert!(is_leap(year) == leap);
        // first estimate that's at most 1 too high
        let mut month = (n + 50 >> 5) as u8;
        let mut monthdays = days_before_month(year, month);
        if n < monthdays as u32 {
            month -= 1;
            monthdays -= days_in_month(year, month) as u16;
        }
        n -= monthdays as u32;
        debug_assert!((n as u8) < days_in_month(year, month));
        (year, month as u8, n as u8 + 1)
    }
}

pub(crate) fn add(d: Date, years: c_long, months: c_long, days: c_long) -> Option<Date> {
    let mut year = d.year as c_long + years;
    let month = ((d.month as c_long + months - 1).rem_euclid(12)) as u8 + 1;
    year += (d.month as c_long + months - 1).div_euclid(12);
    if year < MIN_YEAR || year > MAX_YEAR {
        return None;
    }
    let ord = ymd_to_ord(
        year as u16,
        month,
        min(d.day, days_in_month(year as u16, month)),
    ) as i64
        + days;
    if ord < MIN_ORD || ord > MAX_ORD {
        return None;
    }
    let (year, month, day) = ord_to_ymd(ord as u32);
    Some(Date { year, month, day })
}

unsafe extern "C" fn __sub__(obj_a: *mut PyObject, obj_b: *mut PyObject) -> *mut PyObject {
    let a = (*obj_a.cast::<PyDate>()).date;
    if Py_TYPE(obj_b) == Py_TYPE(obj_a) {
        let b = (*obj_b.cast::<PyDate>()).date;

        let mut months = a.month as i32 - b.month as i32 + 12 * (a.year as i32 - b.year as i32);
        let mut days = a.day as i8;
        // TODO: use unchecked, faster version of this function
        let mut moved_a = add(
            b,
            a.year as c_long - b.year as c_long,
            a.month as c_long - b.month as c_long,
            0,
        )
        // subtracting two valid dates never overflows
        .unwrap();

        // Check if we've overshot
        if b > a && moved_a < a {
            months += 1;
            moved_a = add(b, 0, months as c_long, 0).unwrap();
            days -= days_in_month(a.year, a.month) as i8;
        } else if b < a && moved_a > a {
            months -= 1;
            moved_a = add(b, 0, months as c_long, 0).unwrap();
            days += days_in_month(moved_a.year, moved_a.month) as i8
        };
        date_delta::new_unchecked(
            (*ModuleState::from(Py_TYPE(obj_a))).date_delta_type,
            DateDelta {
                years: (months / 12) as i16,
                months: months % 12,
                weeks: 0,
                days: (days - moved_a.day as i8) as i32,
            },
        )
        .cast()
    } else if Py_TYPE(obj_b) == (*ModuleState::from(Py_TYPE(obj_a))).date_delta_type {
        let delta = (*obj_b.cast::<PyDateDelta>()).delta;
        match add(
            a,
            -delta.years as c_long,
            -delta.months as c_long,
            -(delta.weeks * 7 + delta.days) as c_long,
        ) {
            Some(shifted) => new_unchecked(Py_TYPE(obj_a), shifted).cast(),
            None => {
                raise!(PyExc_ValueError, "Resulting date out of range");
            }
        }
    } else {
        let result = Py_NotImplemented();
        Py_INCREF(result);
        result
    }
}

unsafe extern "C" fn __add__(obj_a: *mut PyObject, obj_b: *mut PyObject) -> *mut PyObject {
    if Py_TYPE(obj_b) != (*ModuleState::from(Py_TYPE(obj_a))).date_delta_type {
        let result = Py_NotImplemented();
        Py_INCREF(result);
        result
    } else {
        let delta = (*obj_b.cast::<PyDateDelta>()).delta;
        if let Some(date) = add(
            (*obj_a.cast::<PyDate>()).date,
            delta.years as c_long,
            delta.months as c_long,
            (delta.weeks * 7 + delta.days) as c_long,
        ) {
            new_unchecked(Py_TYPE(obj_a), date).cast()
        } else {
            raise!(PyExc_ValueError, "Resulting date out of range");
        }
    }
}

unsafe extern "C" fn add_method(
    slf: *mut PyObject,
    type_: *mut PyTypeObject,
    args: *const *mut PyObject,
    nargs: Py_ssize_t,
    kwnames: *mut PyObject,
) -> *mut PyObject {
    shift(slf, type_, args, nargs, kwnames, false)
}

unsafe extern "C" fn subtract(
    slf: *mut PyObject,
    type_: *mut PyTypeObject,
    args: *const *mut PyObject,
    nargs: Py_ssize_t,
    kwnames: *mut PyObject,
) -> *mut PyObject {
    shift(slf, type_, args, nargs, kwnames, true)
}

unsafe extern "C" fn shift(
    slf: *mut PyObject,
    type_: *mut PyTypeObject,
    args: *const *mut PyObject,
    nargs: Py_ssize_t,
    kwnames: *mut PyObject,
    negate: bool,
) -> *mut PyObject {
    let mut days: c_long = 0;
    let mut months: c_long = 0;
    let mut years: c_long = 0;

    if PyVectorcall_NARGS(nargs as usize) != 0 {
        raise!(PyExc_TypeError, "add() takes no positional arguments");
    }
    if !kwnames.is_null() {
        for i in 0..=Py_SIZE(kwnames).saturating_sub(1) {
            let name = PyTuple_GET_ITEM(kwnames, i as Py_ssize_t);
            let value = try_get_int!(*args.offset(i));
            if name == PyUnicode_InternFromString(c_str!("days")) {
                days += value;
            } else if name == PyUnicode_InternFromString(c_str!("months")) {
                months = value;
            } else if name == PyUnicode_InternFromString(c_str!("years")) {
                years = value;
            } else if name == PyUnicode_InternFromString(c_str!("weeks")) {
                days += value * 7;
            } else {
                raise!(
                    PyExc_TypeError,
                    // TODO: add() may be subtract()!
                    "add() got an unexpected keyword argument %R",
                    name
                );
            }
        }
    }

    if let Some(date) = add(
        (*slf.cast::<PyDate>()).date,
        if negate { -years } else { years },
        if negate { -months } else { months },
        if negate { -days } else { days },
    ) {
        new_unchecked(type_, date).cast()
    } else {
        raise!(PyExc_ValueError, "Resulting date out of range");
    }
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
    if !kwnames.is_null() {
        let date = (*slf.cast::<PyDate>()).date;
        let mut year = date.year as c_long;
        let mut month = date.month as c_long;
        let mut day = date.day as c_long;
        for i in 0..=Py_SIZE(kwnames).saturating_sub(1) {
            let name = PyTuple_GET_ITEM(kwnames, i as Py_ssize_t);
            if name == PyUnicode_InternFromString(c_str!("year")) {
                year = try_get_int!(*args.offset(i));
            } else if name == PyUnicode_InternFromString(c_str!("month")) {
                month = try_get_int!(*args.offset(i));
            } else if name == PyUnicode_InternFromString(c_str!("day")) {
                day = try_get_int!(*args.offset(i));
            } else {
                raise!(
                    PyExc_TypeError,
                    "replace() got an unexpected keyword argument %R",
                    name
                );
            }
        }
        match in_range(year, month, day) {
            Ok(date) => new_unchecked(type_, date).cast(),
            Err(e) => {
                e.set_pyerr();
                NULL()
            }
        }
    } else {
        Py_INCREF(slf);
        slf
    }
}

static mut METHODS: &[PyMethodDef] = &[
    PyMethodDef {
        ml_name: c_str!("py_date"),
        ml_meth: PyMethodDefPointer {
            PyCFunction: as_py_date,
        },
        ml_flags: METH_NOARGS,
        ml_doc: c_str!("Convert to a Python datetime.date"),
    },
    PyMethodDef {
        ml_name: c_str!("canonical_format"),
        ml_meth: PyMethodDefPointer {
            PyCFunction: canonical_format,
        },
        ml_flags: METH_NOARGS,
        ml_doc: c_str!("Return the date in the canonical format"),
    },
    PyMethodDef {
        ml_name: c_str!("from_canonical_format"),
        ml_meth: PyMethodDefPointer {
            PyCFunction: from_canonical_format,
        },
        ml_flags: METH_O | METH_CLASS,
        ml_doc: c_str!("Create a date from the canonical format"),
    },
    PyMethodDef {
        ml_name: c_str!("common_iso8601"),
        ml_meth: PyMethodDefPointer {
            PyCFunction: canonical_format,
        },
        ml_flags: METH_NOARGS,
        ml_doc: c_str!("Return the date in the common ISO 8601 format"),
    },
    PyMethodDef {
        ml_name: c_str!("from_common_iso8601"),
        ml_meth: PyMethodDefPointer {
            PyCFunction: from_canonical_format,
        },
        ml_flags: METH_O | METH_CLASS,
        ml_doc: c_str!("Create a date from the common ISO 8601 format"),
    },
    PyMethodDef {
        ml_name: c_str!("from_py_date"),
        ml_meth: PyMethodDefPointer {
            PyCFunction: from_py_date,
        },
        ml_flags: METH_O | METH_CLASS,
        ml_doc: c_str!("Create a date from a Python datetime.date"),
    },
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
        // TODO: rename iso_weekday
        ml_name: c_str!("day_of_week"),
        ml_meth: PyMethodDefPointer {
            PyCFunction: day_of_week,
        },
        ml_flags: METH_NOARGS,
        ml_doc: c_str!("Return the ISO day of the week, where monday=1"),
    },
    PyMethodDef {
        ml_name: c_str!("__reduce__"),
        ml_meth: PyMethodDefPointer {
            PyCMethod: __reduce__,
        },
        ml_flags: METH_METHOD | METH_FASTCALL | METH_KEYWORDS,
        ml_doc: NULL(),
    },
    // TODO: docstrings
    PyMethodDef {
        ml_name: c_str!("add"),
        ml_meth: PyMethodDefPointer {
            PyCMethod: add_method,
        },
        ml_flags: METH_METHOD | METH_FASTCALL | METH_KEYWORDS,
        ml_doc: NULL(),
    },
    PyMethodDef {
        ml_name: c_str!("subtract"),
        ml_meth: PyMethodDefPointer {
            PyCMethod: subtract,
        },
        ml_flags: METH_METHOD | METH_FASTCALL | METH_KEYWORDS,
        ml_doc: NULL(),
    },
    PyMethodDef {
        ml_name: c_str!("replace"),
        ml_meth: PyMethodDefPointer { PyCMethod: replace },
        ml_flags: METH_METHOD | METH_FASTCALL | METH_KEYWORDS,
        ml_doc: c_str!("Return a new date with the specified components replaced"),
    },
    PyMethodDef::zeroed(),
];

unsafe extern "C" fn get_year(slf: *mut PyObject, _: *mut c_void) -> *mut PyObject {
    PyLong_FromLong((*slf.cast::<PyDate>()).date.year as c_long)
}

unsafe extern "C" fn get_month(slf: *mut PyObject, _: *mut c_void) -> *mut PyObject {
    PyLong_FromLong((*slf.cast::<PyDate>()).date.month as c_long)
}

unsafe extern "C" fn get_day(slf: *mut PyObject, _: *mut c_void) -> *mut PyObject {
    PyLong_FromLong((*slf.cast::<PyDate>()).date.day as c_long)
}

pub(crate) unsafe fn new_checked(
    type_: *mut PyTypeObject,
    year: c_long,
    month: c_long,
    day: c_long,
) -> *mut PyObject {
    match in_range(year, month, day) {
        Ok(date) => new_unchecked(type_, date).cast(),
        Err(e) => {
            e.set_pyerr();
            NULL()
        }
    }
}

pub(crate) unsafe fn new_unchecked(type_: *mut PyTypeObject, d: Date) -> *mut PyDate {
    let f: allocfunc = (*type_).tp_alloc.expect("tp_alloc is not set");
    let slf = propagate_exc!(f(type_, 0).cast::<PyDate>());
    ptr::addr_of_mut!((*slf).date).write(d);
    slf
}

// OPTIMIZE: a more efficient pickle?
pub(crate) unsafe extern "C" fn unpickle(
    module: *mut PyObject,
    args: *mut *mut PyObject,
    nargs: Py_ssize_t,
) -> *mut PyObject {
    if PyVectorcall_NARGS(nargs as usize) != 3 {
        raise!(PyExc_TypeError, "Invalid pickle data");
    }
    new_unchecked(
        (*PyModule_GetState(module).cast::<crate::ModuleState>()).date_type,
        Date {
            year: try_get_int!(*args.offset(0)) as u16,
            month: try_get_int!(*args.offset(1)) as u8,
            day: try_get_int!(*args.offset(2)) as u8,
        },
    )
    .cast()
}

static mut GETSETTERS: &[PyGetSetDef] = &[
    PyGetSetDef {
        name: c_str!("year"),
        get: Some(get_year),
        set: None,
        doc: c_str!("The year component"),
        closure: NULL(),
    },
    PyGetSetDef {
        name: c_str!("month"),
        get: Some(get_month),
        set: None,
        doc: c_str!("The month component"),
        closure: NULL(),
    },
    PyGetSetDef {
        name: c_str!("day"),
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
    name: c_str!("whenever.Date"),
    basicsize: mem::size_of::<PyDate>() as c_int,
    itemsize: 0,
    flags: Py_TPFLAGS_DEFAULT as c_uint,
    slots: unsafe { SLOTS as *const [_] as *mut _ },
};

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn test_check_date_valid() {
        assert_eq!(
            in_range(2021, 1, 1),
            Ok(Date {
                year: 2021,
                month: 1,
                day: 1
            })
        );
        assert_eq!(
            in_range(2021, 12, 31),
            Ok(Date {
                year: 2021,
                month: 12,
                day: 31
            })
        );
        assert_eq!(
            in_range(2021, 2, 28),
            Ok(Date {
                year: 2021,
                month: 2,
                day: 28
            })
        );
        assert_eq!(
            in_range(2020, 2, 29),
            Ok(Date {
                year: 2020,
                month: 2,
                day: 29
            })
        );
        assert_eq!(
            in_range(2021, 4, 30),
            Ok(Date {
                year: 2021,
                month: 4,
                day: 30
            })
        );
        assert_eq!(
            in_range(2000, 2, 29),
            Ok(Date {
                year: 2000,
                month: 2,
                day: 29
            })
        );
        assert_eq!(
            in_range(1900, 2, 28),
            Ok(Date {
                year: 1900,
                month: 2,
                day: 28
            })
        );
    }

    #[test]
    fn test_check_date_invalid_year() {
        assert_eq!(in_range(0, 1, 1), Err(DateError::InvalidYear));
        assert_eq!(in_range(10_000, 1, 1), Err(DateError::InvalidYear));
    }

    #[test]
    fn test_check_date_invalid_month() {
        assert_eq!(in_range(2021, 0, 1), Err(DateError::InvalidMonth));
        assert_eq!(in_range(2021, 13, 1), Err(DateError::InvalidMonth));
    }

    #[test]
    fn test_check_date_invalid_day() {
        assert_eq!(in_range(2021, 1, 0), Err(DateError::InvalidDay));
        assert_eq!(in_range(2021, 1, 32), Err(DateError::InvalidDay));
        assert_eq!(in_range(2021, 4, 31), Err(DateError::InvalidDay));
        assert_eq!(in_range(2021, 2, 29), Err(DateError::InvalidDay));
        assert_eq!(in_range(2020, 2, 30), Err(DateError::InvalidDay));
        assert_eq!(in_range(2000, 2, 30), Err(DateError::InvalidDay));
        assert_eq!(in_range(1900, 2, 29), Err(DateError::InvalidDay));
    }

    #[test]
    fn test_ord_to_ymd() {
        assert_eq!(ord_to_ymd(1), (1, 1, 1));
        assert_eq!(ord_to_ymd(365), (1, 12, 31));
        assert_eq!(ord_to_ymd(366), (2, 1, 1));
        assert_eq!(ord_to_ymd(1_000), (3, 9, 27));
        assert_eq!(ord_to_ymd(1_000_000), (2738, 11, 28));
        assert_eq!(ord_to_ymd(730179), (2000, 2, 29));
        assert_eq!(ord_to_ymd(730180), (2000, 3, 1));
        assert_eq!(ord_to_ymd(3_652_059), (9999, 12, 31));
    }

    #[test]
    fn test_ord_ymd_reversible() {
        for ord in 1..=(366 * 4) {
            let (year, month, day) = ord_to_ymd(ord);
            assert_eq!(ord, ymd_to_ord(year, month, day));
        }
    }
}
