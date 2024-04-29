use core::ffi::{c_int, c_long, c_void};
use core::{mem, ptr, ptr::null_mut as NULL};
use pyo3_ffi::*;
use std::fmt::{self, Display, Formatter};

use crate::common::*;
use crate::{
    date_delta::{self, DateDelta},
    naive_datetime::{self, DateTime},
    time::Time,
    State,
};

#[derive(Debug, Eq, PartialEq, Ord, PartialOrd, Copy, Clone)]
pub struct Date {
    pub(crate) year: u16,
    pub(crate) month: u8,
    pub(crate) day: u8,
}

#[repr(C)]
pub(crate) struct PyDate {
    _ob_base: PyObject,
    pub(crate) date: Date,
    // TODO: use the extra padding to cache the ordinal?
}

impl Date {
    pub(crate) const unsafe fn hash(self) -> i32 {
        mem::transmute::<_, i32>(self)
    }

    pub(crate) const fn increment(mut self) -> Self {
        if self.day < days_in_month(self.year, self.month) {
            self.day += 1
        } else {
            self.day = 1;
            self.month = self.month % 12 + 1;
        }
        self
    }

    pub(crate) const fn decrement(mut self) -> Self {
        if self.day > 1 {
            self.day -= 1;
        } else {
            self.day = days_in_month(self.year, self.month - 1);
            self.month = self.month.saturating_sub(1);
        }
        self
    }

    pub(crate) const fn ord(self) -> u32 {
        ymd_to_ord(self.year, self.month, self.day)
    }

    pub(crate) const fn from_ord(ord: u32) -> Self {
        let (year, month, day) = ord_to_ymd(ord);
        Self { year, month, day }
    }

    pub(crate) const fn shift(&self, years: i16, months: i32, days: i32) -> Option<Date> {
        let mut year = self.year as i32 + years as i32;
        let month = ((self.month as i32 + months - 1).rem_euclid(12)) as u8 + 1;
        year += (self.month as i32 + months - 1).div_euclid(12);
        if year < MIN_YEAR as i32 || year > MAX_YEAR as i32 {
            return None;
        }
        let ord = ymd_to_ord(
            year as u16,
            month,
            if self.day > days_in_month(year as u16, month) {
                days_in_month(year as u16, month)
            } else {
                self.day
            },
        ) as i32
            + days;
        if ord < MIN_ORD as i32 || ord > MAX_ORD as i32 {
            return None;
        }
        let (year, month, day) = ord_to_ymd(ord as u32);
        Some(Date { year, month, day })
    }

    pub(crate) unsafe fn extract(obj: *mut PyObject) -> Self {
        (*obj.cast::<PyDate>()).date
    }

    pub(crate) const fn from_longs(year: c_long, month: c_long, day: c_long) -> Option<Self> {
        if year < MIN_YEAR || year > MAX_YEAR {
            return None;
        }
        if month < 1 || month > 12 {
            return None;
        }
        let y = year as u16;
        let m = month as u8;
        if day < 1 || day > days_in_month(y, m) as c_long {
            return None;
        }
        Some(Date {
            year: y,
            month: m,
            day: day as u8,
        })
    }

    pub(crate) const fn new(year: u16, month: u8, day: u8) -> Option<Self> {
        if year == 0 || year > MAX_YEAR as _ {
            None
        } else if month < 1 || month > 12 {
            None
        } else if day < 1 || day > days_in_month(year, month) {
            None
        } else {
            Some(Date { year, month, day })
        }
    }
    pub(crate) const fn parse_all(s: &[u8]) -> Option<Self> {
        if s.len() == 10 && s[4] == b'-' && s[7] == b'-' {
            Date::new(
                get_digit!(s, 0) as u16 * 1000
                    + get_digit!(s, 1) as u16 * 100
                    + get_digit!(s, 2) as u16 * 10
                    + get_digit!(s, 3) as u16,
                get_digit!(s, 5) * 10 + get_digit!(s, 6),
                get_digit!(s, 8) * 10 + get_digit!(s, 9),
            )
        } else {
            None
        }
    }

    pub(crate) fn parse_partial(s: &mut &[u8]) -> Option<Self> {
        debug_assert!(s.len() >= 10);
        let result = Self::parse_all(&s[..10]);
        *s = &s[10..];
        result
    }
}

impl Display for Date {
    fn fmt(&self, f: &mut Formatter<'_>) -> fmt::Result {
        write!(f, "{:04}-{:02}-{:02}", self.year, self.month, self.day)
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

const fn is_leap(year: u16) -> bool {
    (year % 4 == 0 && year % 100 != 0) || year % 400 == 0
}

const fn days_in_month(year: u16, month: u8) -> u8 {
    debug_assert!(month >= 1 && month <= 12);
    if month == 2 && is_leap(year) {
        29
    } else {
        DAYS_IN_MONTH[month as usize]
    }
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
            pyint_as_long!(PyTuple_GET_ITEM(args, 0)),
            pyint_as_long!(PyTuple_GET_ITEM(args, 1)),
            pyint_as_long!(PyTuple_GET_ITEM(args, 2)),
        )
    } else if nargs + nkwargs > 3 {
        raise!(
            PyExc_TypeError,
            "Date() takes exactly 3 arguments, got %lld",
            nargs + nkwargs
        );
    // slow path: parse args and kwargs
    } else {
        let mut year: Option<c_long> = None;
        let mut month: Option<c_long> = None;
        let mut day: Option<c_long> = None;

        if nargs > 0 {
            year = Some(pyint_as_long!(PyTuple_GET_ITEM(args, 0)));
            if nargs > 1 {
                month = Some(pyint_as_long!(PyTuple_GET_ITEM(args, 1)));
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
                        if year.replace(pyint_as_long!(value_obj)).is_some() {
                            raise!(
                                PyExc_TypeError,
                                "Date() got multiple values for argument 'year'"
                            );
                        }
                    }
                    b"month" => {
                        if month.replace(pyint_as_long!(value_obj)).is_some() {
                            raise!(
                                PyExc_TypeError,
                                "Date() got multiple values for argument 'month'"
                            );
                        }
                    }
                    b"day" => {
                        if day.replace(pyint_as_long!(value_obj)).is_some() {
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
    let Date { year, month, day } = Date::extract(slf);
    py_str(format!("Date({:04}-{:02}-{:02})", year, month, day).as_str())
}

unsafe extern "C" fn __hash__(slf: *mut PyObject) -> Py_hash_t {
    Date::extract(slf).hash() as Py_hash_t
}

unsafe extern "C" fn __richcmp__(
    a_obj: *mut PyObject,
    b_obj: *mut PyObject,
    op: c_int,
) -> *mut PyObject {
    newref(if Py_TYPE(b_obj) == Py_TYPE(a_obj) {
        let a = Date::extract(a_obj);
        let b = Date::extract(b_obj);
        py_bool(match op {
            pyo3_ffi::Py_LT => a < b,
            pyo3_ffi::Py_LE => a <= b,
            pyo3_ffi::Py_EQ => a == b,
            pyo3_ffi::Py_NE => a != b,
            pyo3_ffi::Py_GT => a > b,
            pyo3_ffi::Py_GE => a >= b,
            _ => unreachable!(),
        })
    } else {
        Py_NotImplemented()
    })
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
        pfunc: default_format as *mut c_void,
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
        slot: Py_tp_dealloc,
        pfunc: dealloc as *mut c_void,
    },
    PyType_Slot {
        slot: 0,
        pfunc: NULL(),
    },
];

unsafe extern "C" fn py_date(slf: *mut PyObject, _: *mut PyObject) -> *mut PyObject {
    let Date { year, month, day } = Date::extract(slf);
    let &PyDateTime_CAPI {
        Date_FromDate,
        DateType,
        ..
    } = State::for_obj(slf).datetime_api;
    Date_FromDate(year.into(), month.into(), day.into(), DateType)
}

unsafe extern "C" fn from_py_date(cls: *mut PyObject, date: *mut PyObject) -> *mut PyObject {
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

unsafe extern "C" fn default_format(slf: *mut PyObject, _: *mut PyObject) -> *mut PyObject {
    let Date { year, month, day } = Date::extract(slf);
    py_str(format!("{:04}-{:02}-{:02}", year, month, day).as_str())
}

unsafe extern "C" fn from_default_format(cls: *mut PyObject, s: *mut PyObject) -> *mut PyObject {
    match Date::parse_all(pystr_to_utf8!(s, "argument must be str")) {
        Some(d) => new_unchecked(cls.cast(), d),
        None => raise!(PyExc_ValueError, "Could not parse date: %R", s),
    }
}

const fn days_before_year(year: u16) -> u32 {
    debug_assert!(year >= 1);
    let y = (year - 1) as u32;
    return y * 365 + y / 4 - y / 100 + y / 400;
}

const fn days_before_month(year: u16, month: u8) -> u16 {
    debug_assert!(month >= 1 && month <= 12);
    let mut days = DAYS_BEFORE_MONTH[month as usize];
    if month > 2 && is_leap(year) {
        days += 1;
    }
    days
}

pub(crate) const fn ymd_to_ord(year: u16, month: u8, day: u8) -> u32 {
    days_before_year(year) + days_before_month(year, month) as u32 + day as u32
}

unsafe extern "C" fn day_of_week(slf: *mut PyObject, _: *mut PyObject) -> *mut PyObject {
    let Date { year, month, day } = Date::extract(slf);
    PyLong_FromLong(((ymd_to_ord(year, month, day) + 6) % 7 + 1).into())
}

unsafe extern "C" fn __reduce__(slf: *mut PyObject, _: *mut PyObject) -> *mut PyObject {
    let Date { year, month, day } = Date::extract(slf);
    PyTuple_Pack(
        2,
        State::for_obj(slf).unpickle_date,
        py_try!(PyTuple_Pack(
            3,
            PyLong_FromLong(year.into()),
            PyLong_FromLong(month.into()),
            PyLong_FromLong(day.into()),
        )),
    )
}

pub const fn ord_to_ymd(ord: u32) -> (u16, u8, u8) {
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

unsafe extern "C" fn __sub__(obj_a: *mut PyObject, obj_b: *mut PyObject) -> *mut PyObject {
    let a = Date::extract(obj_a);
    let cls = Py_TYPE(obj_a);
    let argtype = Py_TYPE(obj_b);
    if argtype == cls {
        let b = Date::extract(obj_b);

        let mut months = a.month as i32 - b.month as i32 + 12 * (a.year as i32 - b.year as i32);
        let mut day = a.day as i8;
        // FUTURE: use unchecked, faster version of this function
        let mut moved_a = b
            .shift(
                a.year as i16 - b.year as i16,
                (a.month as i8 - b.month as i8).into(),
                0,
            )
            // subtracting two valid dates never overflows
            .unwrap();

        // Check if we've overshot
        if b > a && moved_a < a {
            months += 1;
            moved_a = b.shift(0, months, 0).unwrap();
            day -= days_in_month(a.year, a.month) as i8;
        } else if b < a && moved_a > a {
            months -= 1;
            moved_a = b.shift(0, months, 0).unwrap();
            day += days_in_month(moved_a.year, moved_a.month) as i8
        };
        date_delta::new_unchecked(
            State::for_obj(obj_a).date_delta_type,
            DateDelta {
                months,
                days: (day - moved_a.day as i8).into(),
            },
        )
    } else if argtype == State::for_type(cls).date_delta_type {
        let DateDelta { months, days } = DateDelta::extract(obj_b);
        new_unchecked(
            cls,
            unwrap_or_raise!(
                a.shift(0, -months, -days),
                PyExc_ValueError,
                "Resulting date out of range"
            ),
        )
    } else {
        newref(Py_NotImplemented())
    }
}

unsafe extern "C" fn __add__(obj_a: *mut PyObject, obj_b: *mut PyObject) -> *mut PyObject {
    // TODO: reflexivity
    let cls = Py_TYPE(obj_a);
    if Py_TYPE(obj_b) == State::for_type(cls).date_delta_type {
        let DateDelta { months, days } = DateDelta::extract(obj_b);
        new_unchecked(
            cls,
            unwrap_or_raise!(
                Date::extract(obj_a).shift(0, months, days),
                PyExc_ValueError,
                "Resulting date out of range"
            ),
        )
    } else {
        newref(Py_NotImplemented())
    }
}

unsafe extern "C" fn add_method(
    slf: *mut PyObject,
    type_: *mut PyTypeObject,
    args: *const *mut PyObject,
    nargs: Py_ssize_t,
    kwnames: *mut PyObject,
) -> *mut PyObject {
    _shift_method(slf, type_, args, nargs, kwnames, false)
}

unsafe extern "C" fn subtract(
    slf: *mut PyObject,
    type_: *mut PyTypeObject,
    args: *const *mut PyObject,
    nargs: Py_ssize_t,
    kwnames: *mut PyObject,
) -> *mut PyObject {
    _shift_method(slf, type_, args, nargs, kwnames, true)
}

#[inline]
unsafe extern "C" fn _shift_method(
    slf: *mut PyObject,
    type_: *mut PyTypeObject,
    args: *const *mut PyObject,
    nargs: Py_ssize_t,
    kwnames: *mut PyObject,
    negate: bool,
) -> *mut PyObject {
    let state = State::for_type(type_);
    let mut days: c_long = 0;
    let mut months: c_long = 0;
    let mut years: c_long = 0;

    if PyVectorcall_NARGS(nargs as usize) != 0 {
        raise!(
            PyExc_TypeError,
            "add()/subtract() takes no positional arguments"
        );
    }
    if !kwnames.is_null() {
        for i in 0..=Py_SIZE(kwnames).saturating_sub(1) {
            let name = PyTuple_GET_ITEM(kwnames, i);
            if name == state.str_days {
                days += pyint_as_long!(*args.offset(i));
            } else if name == state.str_months {
                months = pyint_as_long!(*args.offset(i));
            } else if name == state.str_years {
                years = pyint_as_long!(*args.offset(i));
            } else if name == state.str_weeks {
                days += pyint_as_long!(*args.offset(i)) * 7;
            } else {
                raise!(
                    PyExc_TypeError,
                    "add()/subtract() got an unexpected keyword argument %R",
                    name
                );
            }
        }
    }
    if negate {
        days = -days;
        months = -months;
        years = -years;
    }

    match Date::extract(slf).shift(
        unwrap_or_raise!(
            years.try_into().ok(),
            PyExc_ValueError,
            "years out of range"
        ),
        unwrap_or_raise!(
            months.try_into().ok(),
            PyExc_ValueError,
            "months out of range"
        ),
        unwrap_or_raise!(days.try_into().ok(), PyExc_ValueError, "days out of range"),
    ) {
        Some(date) => new_unchecked(type_, date).cast(),
        None => raise!(PyExc_ValueError, "Resulting date out of range"),
    }
}

unsafe extern "C" fn replace(
    slf: *mut PyObject,
    type_: *mut PyTypeObject,
    args: *const *mut PyObject,
    nargs: Py_ssize_t,
    kwnames: *mut PyObject,
) -> *mut PyObject {
    let &State {
        str_year,
        str_month,
        str_day,
        ..
    } = State::for_type(type_);
    if PyVectorcall_NARGS(nargs as usize) != 0 {
        raise!(PyExc_TypeError, "replace() takes no positional arguments");
    } else if kwnames.is_null() {
        newref(slf)
    } else {
        let date = Date::extract(slf);
        let mut year = date.year as c_long;
        let mut month = date.month as c_long;
        let mut day = date.day as c_long;
        for i in 0..=Py_SIZE(kwnames).saturating_sub(1) {
            let name = PyTuple_GET_ITEM(kwnames, i);
            if name == str_year {
                year = pyint_as_long!(*args.offset(i));
            } else if name == str_month {
                month = pyint_as_long!(*args.offset(i));
            } else if name == str_day {
                day = pyint_as_long!(*args.offset(i));
            } else {
                raise!(
                    PyExc_TypeError,
                    "replace() got an unexpected keyword argument %R",
                    name
                );
            }
        }
        match Date::from_longs(year, month, day) {
            Some(date) => new_unchecked(type_, date).cast(),
            None => raise!(PyExc_ValueError, "Invalid date components"),
        }
    }
}

unsafe extern "C" fn at(slf: *mut PyObject, time_obj: *mut PyObject) -> *mut PyObject {
    let &State {
        time_type,
        naive_datetime_type,
        ..
    } = State::for_obj(slf);
    if Py_TYPE(time_obj) == time_type {
        naive_datetime::new_unchecked(
            naive_datetime_type,
            DateTime {
                date: Date::extract(slf),
                time: Time::extract(time_obj),
            },
        )
        .cast()
    } else {
        raise!(PyExc_TypeError, "argument must be a date");
    }
}

static mut METHODS: &[PyMethodDef] = &[
    method!(py_date, "Convert to a Python datetime.date"),
    method!(default_format, ""),
    classmethod!(from_default_format, "", METH_O),
    method!(
        default_format named "common_iso8601",
        "Return the date in the common ISO 8601 format"
    ),
    classmethod!(
        from_default_format named "from_common_iso8601",
        "Create a date from the common ISO 8601 format",
        METH_O
    ),
    classmethod!(
        from_py_date,
        "Create a date from a Python datetime.date",
        METH_O
    ),
    method!(identity named "__copy__", ""),
    method!(identity named "__deepcopy__", "", METH_O),
    method!(
        day_of_week,
        "Return the ISO day of the week, where monday=1"
    ),
    method!(at, "Combine with a time to create a datetime", METH_O),
    method!(__reduce__, ""),
    PyMethodDef {
        ml_name: c_str!("add"),
        ml_meth: PyMethodDefPointer {
            PyCMethod: add_method,
        },
        ml_flags: METH_METHOD | METH_FASTCALL | METH_KEYWORDS,
        ml_doc: c_str!("Add various units to the date"),
    },
    PyMethodDef {
        ml_name: c_str!("subtract"),
        ml_meth: PyMethodDefPointer {
            PyCMethod: subtract,
        },
        ml_flags: METH_METHOD | METH_FASTCALL | METH_KEYWORDS,
        ml_doc: c_str!("Subtract various units from the date"),
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
    PyLong_FromLong(Date::extract(slf).year.into())
}

unsafe extern "C" fn get_month(slf: *mut PyObject, _: *mut c_void) -> *mut PyObject {
    PyLong_FromLong(Date::extract(slf).month.into())
}

unsafe extern "C" fn get_day(slf: *mut PyObject, _: *mut c_void) -> *mut PyObject {
    PyLong_FromLong(Date::extract(slf).day.into())
}

pub(crate) unsafe fn new_checked(
    type_: *mut PyTypeObject,
    year: c_long,
    month: c_long,
    day: c_long,
) -> *mut PyObject {
    match Date::from_longs(year, month, day) {
        Some(date) => new_unchecked(type_, date).cast(),
        None => raise!(PyExc_ValueError, "Invalid date components"),
    }
}

pub(crate) unsafe fn new_unchecked(type_: *mut PyTypeObject, d: Date) -> *mut PyObject {
    let f: allocfunc = (*type_).tp_alloc.expect("tp_alloc is not set");
    let slf = py_try!(f(type_, 0).cast::<PyDate>());
    ptr::addr_of_mut!((*slf).date).write(d);
    slf.cast()
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
        State::for_mod(module).date_type,
        Date {
            year: pyint_as_long!(*args.offset(0)) as u16,
            month: pyint_as_long!(*args.offset(1)) as u8,
            day: pyint_as_long!(*args.offset(2)) as u8,
        },
    )
    .cast()
}

static mut GETSETTERS: &[PyGetSetDef] = &[
    getter!(
        get_year named "year",
        "The year component"
    ),
    getter!(
        get_month named "month",
        "The month component"
    ),
    getter!(
        get_day named "day",
        "The day component"
    ),
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
    basicsize: mem::size_of::<PyDate>() as _,
    itemsize: 0,
    flags: Py_TPFLAGS_DEFAULT as _,
    slots: unsafe { SLOTS as *const [_] as *mut _ },
};

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn test_check_date_valid() {
        assert_eq!(
            Date::new(2021, 1, 1),
            Some(Date {
                year: 2021,
                month: 1,
                day: 1
            })
        );
        assert_eq!(
            Date::new(2021, 12, 31),
            Some(Date {
                year: 2021,
                month: 12,
                day: 31
            })
        );
        assert_eq!(
            Date::new(2021, 2, 28),
            Some(Date {
                year: 2021,
                month: 2,
                day: 28
            })
        );
        assert_eq!(
            Date::new(2020, 2, 29),
            Some(Date {
                year: 2020,
                month: 2,
                day: 29
            })
        );
        assert_eq!(
            Date::new(2021, 4, 30),
            Some(Date {
                year: 2021,
                month: 4,
                day: 30
            })
        );
        assert_eq!(
            Date::new(2000, 2, 29),
            Some(Date {
                year: 2000,
                month: 2,
                day: 29
            })
        );
        assert_eq!(
            Date::new(1900, 2, 28),
            Some(Date {
                year: 1900,
                month: 2,
                day: 28
            })
        );
    }

    #[test]
    fn test_check_date_invalid_year() {
        assert_eq!(Date::new(0, 1, 1), None);
        assert_eq!(Date::new(10_000, 1, 1), None);
    }

    #[test]
    fn test_check_date_invalid_month() {
        assert_eq!(Date::new(2021, 0, 1), None);
        assert_eq!(Date::new(2021, 13, 1), None);
    }

    #[test]
    fn test_check_date_invalid_day() {
        assert_eq!(Date::new(2021, 1, 0), None);
        assert_eq!(Date::new(2021, 1, 32), None);
        assert_eq!(Date::new(2021, 4, 31), None);
        assert_eq!(Date::new(2021, 2, 29), None);
        assert_eq!(Date::new(2020, 2, 30), None);
        assert_eq!(Date::new(2000, 2, 30), None);
        assert_eq!(Date::new(1900, 2, 29), None);
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
