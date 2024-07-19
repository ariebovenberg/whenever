use core::ffi::{c_int, c_long, c_void, CStr};
use core::{mem, ptr::null_mut as NULL};
use pyo3_ffi::*;
use std::fmt::{self, Display, Formatter};

use crate::common::*;
use crate::{date_delta::DateDelta, local_datetime::DateTime, time::Time, State};

#[derive(Debug, Eq, PartialEq, Ord, PartialOrd, Copy, Clone)]
pub struct Date {
    pub(crate) year: u16,
    pub(crate) month: u8,
    pub(crate) day: u8,
}

pub(crate) const SINGLETONS: &[(&CStr, Date); 2] = &[
    (c"MIN", Date::new_unchecked(1, 1, 1)),
    (c"MAX", Date::new_unchecked(9999, 12, 31)),
];

impl Date {
    pub(crate) const unsafe fn hash(self) -> i32 {
        // Since the data already fits within an i32
        // we don't need to do any extra hashing. It may be counterintuitive,
        // but this is also what `int` does: `hash(6) == 6`.
        mem::transmute::<_, i32>(self)
    }

    pub(crate) const fn increment(mut self) -> Self {
        if self.day < days_in_month(self.year, self.month) {
            self.day += 1
        } else if self.month < 12 {
            self.day = 1;
            self.month += 1;
        } else {
            self.year += 1;
            self.month = 1;
            self.day = 1;
        }
        self
    }

    pub(crate) const fn decrement(mut self) -> Self {
        if self.day > 1 {
            self.day -= 1;
        } else if self.month > 1 {
            self.month -= 1;
            self.day = days_in_month(self.year, self.month);
        } else {
            self.day = 31;
            self.month = 12;
            self.year -= 1;
        }
        self
    }

    pub(crate) const fn ord(self) -> u32 {
        days_before_year(self.year)
            + days_before_month(self.year, self.month) as u32
            + self.day as u32
    }

    pub(crate) fn from_ord(ord: i32) -> Option<Self> {
        (MIN_ORD..=MAX_ORD)
            .contains(&ord)
            .then(|| Self::from_ord_unchecked(ord as _))
    }

    pub const fn from_ord_unchecked(ord: u32) -> Self {
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
            Date {
                year: year - 1,
                month: 12,
                day: 31,
            }
        } else {
            let leap = (n1 == 3) && (n4 != 24 || n100 == 3);
            debug_assert!(is_leap(year) == leap);
            // first estimate that's at most 1 too high
            let mut month = ((n + 50) >> 5) as u8;
            let mut monthdays = days_before_month(year, month);
            if n < monthdays as u32 {
                month -= 1;
                monthdays -= days_in_month(year, month) as u16;
            }
            n -= monthdays as u32;
            debug_assert!((n as u8) < days_in_month(year, month));
            Date {
                year,
                month,
                day: n as u8 + 1,
            }
        }
    }

    pub(crate) fn shift_days(self, days: i32) -> Option<Date> {
        Date::from_ord((self.ord() as i32).checked_add(days)?)
    }

    pub(crate) fn shift_months(self, months: i32) -> Option<Date> {
        let month = ((self.month as i32 + months - 1).rem_euclid(12)) as u8 + 1;
        let year = self.year as i32 + (self.month as i32 + months - 1).div_euclid(12);
        (MIN_YEAR as i32..=MAX_YEAR as i32)
            .contains(&year)
            .then(|| {
                Date::new_unchecked(
                    year as u16,
                    month,
                    if self.day > days_in_month(year as u16, month) {
                        days_in_month(year as u16, month)
                    } else {
                        self.day
                    },
                )
            })
    }

    pub(crate) fn shift(&self, years: i16, months: i32, days: i32) -> Option<Date> {
        self.shift_months(months + years as i32 * 12)
            .and_then(|date| date.shift_days(days))
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
        if day >= 1 && day <= days_in_month(y, m) as c_long {
            Some(Date {
                year: y,
                month: m,
                day: day as u8,
            })
        } else {
            None
        }
    }

    pub(crate) const fn new(year: u16, month: u8, day: u8) -> Option<Self> {
        if year == 0
            || year > MAX_YEAR as _
            || month < 1
            || month > 12
            || day < 1
            || day > days_in_month(year, month) as _
        {
            None
        } else {
            Some(Date { year, month, day })
        }
    }

    pub(crate) const fn new_unchecked(year: u16, month: u8, day: u8) -> Self {
        debug_assert!(year != 0);
        debug_assert!(year <= MAX_YEAR as _);
        debug_assert!(month >= 1 && month <= 12);
        debug_assert!(day >= 1 && day <= days_in_month(year, month));
        Date { year, month, day }
    }

    pub(crate) fn parse_all(s: &[u8]) -> Option<Self> {
        if s.len() == 10 && s[4] == b'-' && s[7] == b'-' {
            Date::new(
                parse_digit(s, 0)? as u16 * 1000
                    + parse_digit(s, 1)? as u16 * 100
                    + parse_digit(s, 2)? as u16 * 10
                    + parse_digit(s, 3)? as u16,
                parse_digit(s, 5)? * 10 + parse_digit(s, 6)?,
                parse_digit(s, 8)? * 10 + parse_digit(s, 9)?,
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

impl PyWrapped for Date {}

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
const MIN_ORD: i32 = 1;
const MAX_ORD: i32 = 3_652_059;
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

unsafe fn __new__(cls: *mut PyTypeObject, args: *mut PyObject, kwargs: *mut PyObject) -> PyReturn {
    let nargs = PyTuple_GET_SIZE(args);
    let nkwargs = if kwargs.is_null() {
        0
    } else {
        PyDict_Size(kwargs)
    };

    // Fast path for the most common case
    let (year, month, day) = if nargs == 3 && nkwargs == 0 {
        (
            PyTuple_GET_ITEM(args, 0)
                .to_long()?
                .ok_or_type_err("year must be an integer")?,
            PyTuple_GET_ITEM(args, 1)
                .to_long()?
                .ok_or_type_err("month must be an integer")?,
            PyTuple_GET_ITEM(args, 2)
                .to_long()?
                .ok_or_type_err("day must be an integer")?,
        )
    } else if nargs + nkwargs > 3 {
        Err(type_err!(
            "Date() takes at most 3 arguments, got {}",
            nargs + nkwargs
        ))?
    // slow path: parse args and kwargs
    } else {
        let mut year: Option<c_long> = None;
        let mut month: Option<c_long> = None;
        let mut day: Option<c_long> = None;

        if nargs > 0 {
            year = Some(
                PyTuple_GET_ITEM(args, 0)
                    .to_long()?
                    .ok_or_type_err("year must be an integer")?,
            );
            if nargs > 1 {
                month = Some(
                    PyTuple_GET_ITEM(args, 1)
                        .to_long()?
                        .ok_or_type_err("month must be an integer")?,
                );
                debug_assert!(nargs == 2); // follows from the first branches
            }
        }
        let &State {
            str_year,
            str_month,
            str_day,
            ..
        } = State::for_type(cls);
        if nkwargs > 0 {
            handle_kwargs(
                "Date()",
                DictItems::new_unchecked(kwargs),
                |key, value, eq| {
                    if eq(key, str_year) {
                        let None = year
                            .replace(value.to_long()?.ok_or_type_err("year must be an integer")?)
                        else {
                            Err(type_err!("Date() got multiple values for argument 'year"))?
                        };
                    } else if eq(key, str_month) {
                        let None = month.replace(
                            value
                                .to_long()?
                                .ok_or_type_err("month must be an integer")?,
                        ) else {
                            Err(type_err!("Date() got multiple values for argument 'month"))?
                        };
                    } else if eq(key, str_day) {
                        let None =
                            day.replace(value.to_long()?.ok_or_type_err("day must be an integer")?)
                        else {
                            Err(type_err!("Date() got multiple values for argument 'day"))?
                        };
                    } else {
                        return Ok(false);
                    }
                    Ok(true)
                },
            )?;
        }
        (
            year.ok_or_type_err("year is a required argument")?,
            month.ok_or_type_err("month is a required argument")?,
            day.ok_or_type_err("day is a required argument")?,
        )
    };
    Date::from_longs(year, month, day)
        .ok_or_value_err("Invalid date components")?
        .to_obj(cls)
}

unsafe fn __repr__(slf: *mut PyObject) -> PyReturn {
    format!("Date({})", Date::extract(slf)).to_py()
}

unsafe extern "C" fn __hash__(slf: *mut PyObject) -> Py_hash_t {
    Date::extract(slf).hash() as Py_hash_t
}

unsafe fn __richcmp__(a_obj: *mut PyObject, b_obj: *mut PyObject, op: c_int) -> PyReturn {
    Ok(if Py_TYPE(b_obj) == Py_TYPE(a_obj) {
        let a = Date::extract(a_obj);
        let b = Date::extract(b_obj);
        match op {
            pyo3_ffi::Py_LT => a < b,
            pyo3_ffi::Py_LE => a <= b,
            pyo3_ffi::Py_EQ => a == b,
            pyo3_ffi::Py_NE => a != b,
            pyo3_ffi::Py_GT => a > b,
            pyo3_ffi::Py_GE => a >= b,
            _ => unreachable!(),
        }
        .to_py()?
    } else {
        newref(Py_NotImplemented())
    })
}

static mut SLOTS: &[PyType_Slot] = &[
    slotmethod!(Py_tp_new, __new__),
    slotmethod!(Py_tp_str, __str__, 1),
    slotmethod!(Py_tp_repr, __repr__, 1),
    slotmethod!(Py_tp_richcompare, __richcmp__),
    slotmethod!(Py_nb_subtract, __sub__, 2),
    slotmethod!(Py_nb_add, __add__, 2),
    PyType_Slot {
        slot: Py_tp_doc,
        pfunc: c"A calendar date type".as_ptr() as *mut c_void,
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
        slot: Py_tp_hash,
        pfunc: __hash__ as *mut c_void,
    },
    PyType_Slot {
        slot: Py_tp_dealloc,
        pfunc: generic_dealloc as *mut c_void,
    },
    PyType_Slot {
        slot: 0,
        pfunc: NULL(),
    },
];

unsafe fn py_date(slf: *mut PyObject, _: *mut PyObject) -> PyReturn {
    let Date { year, month, day } = Date::extract(slf);
    let &PyDateTime_CAPI {
        Date_FromDate,
        DateType,
        ..
    } = State::for_obj(slf).py_api;
    Date_FromDate(year.into(), month.into(), day.into(), DateType).as_result()
}

unsafe fn from_py_date(cls: *mut PyObject, date: *mut PyObject) -> PyReturn {
    if PyDate_Check(date) == 0 {
        Err(type_err!("argument must be a Date"))
    } else {
        Date {
            year: PyDateTime_GET_YEAR(date) as u16,
            month: PyDateTime_GET_MONTH(date) as u8,
            day: PyDateTime_GET_DAY(date) as u8,
        }
        .to_obj(cls.cast())
    }
}

unsafe fn __str__(slf: *mut PyObject) -> PyReturn {
    format!("{}", Date::extract(slf)).to_py()
}

unsafe fn format_common_iso(slf: *mut PyObject, _: *mut PyObject) -> PyReturn {
    __str__(slf)
}

unsafe fn parse_common_iso(cls: *mut PyObject, s: *mut PyObject) -> PyReturn {
    Date::parse_all(s.to_utf8()?.ok_or_type_err("argument must be str")?)
        .ok_or_else(|| value_err!("Invalid format: {}", s.repr()))?
        .to_obj(cls.cast())
}

const fn days_before_year(year: u16) -> u32 {
    debug_assert!(year >= 1);
    let y = (year - 1) as u32;
    y * 365 + y / 4 - y / 100 + y / 400
}

const fn days_before_month(year: u16, month: u8) -> u16 {
    debug_assert!(month >= 1 && month <= 12);
    let mut days = DAYS_BEFORE_MONTH[month as usize];
    if month > 2 && is_leap(year) {
        days += 1;
    }
    days
}

unsafe fn day_of_week(slf: *mut PyObject, _: *mut PyObject) -> PyReturn {
    let enum_members = State::for_obj(slf).weekday_enum_members;
    Ok(newref(
        enum_members[((Date::extract(slf).ord() + 6) % 7) as usize]
            .as_mut()
            .unwrap(),
    ))
}

unsafe fn __reduce__(slf: *mut PyObject, _: *mut PyObject) -> PyReturn {
    let Date { year, month, day } = Date::extract(slf);
    (
        State::for_obj(slf).unpickle_date,
        steal!((steal!(pack![year, month, day].to_py()?),).to_py()?),
    )
        .to_py()
}

unsafe fn __sub__(obj_a: *mut PyObject, obj_b: *mut PyObject) -> PyReturn {
    let type_a = Py_TYPE(obj_a);
    let type_b = Py_TYPE(obj_b);

    // Easy case: Date - Date
    if type_b == type_a {
        let a = Date::extract(obj_a);
        let b = Date::extract(obj_b);

        let mut months = a.month as i32 - b.month as i32 + 12 * (a.year as i32 - b.year as i32);
        let mut day = a.day as i8;
        // FUTURE: use unchecked, faster version of this function
        let mut moved_a = b
            .shift_months(
                (a.year as i32 - b.year as i32) * 12 + i32::from(a.month as i8 - b.month as i8),
            )
            // subtracting two valid dates never overflows
            .unwrap();

        // Check if we've overshot
        if b > a && moved_a < a {
            months += 1;
            moved_a = b.shift_months(months).unwrap();
            day -= days_in_month(a.year, a.month) as i8;
        } else if b < a && moved_a > a {
            months -= 1;
            moved_a = b.shift_months(months).unwrap();
            day += days_in_month(moved_a.year, moved_a.month) as i8
        };
        DateDelta {
            months,
            days: (day - moved_a.day as i8).into(),
        }
        .to_obj(State::for_obj(obj_a).date_delta_type)
    // Other cases are more difficult, as they can be triggered
    // by reflexive operations with arbitrary types.
    // We need to eliminate them carefully.
    } else {
        let mod_a = PyType_GetModule(type_a);
        let mod_b = PyType_GetModule(type_b);
        if mod_a == mod_b && type_b == State::for_type(type_a).date_delta_type {
            let DateDelta { months, days } = DateDelta::extract(obj_b);
            Date::extract(obj_a)
                .shift_months(-months)
                .and_then(|date| date.shift_days(-days))
                .ok_or_value_err("Resulting date out of range")?
                .to_obj(type_a)
        } else {
            // We can safely discount other types within our module
            Err(type_err!(
                "unsupported operand type(s) for -: 'Date' and '{}'",
                (type_b as *mut PyObject).repr()
            ))?
        }
    }
}

unsafe fn __add__(obj_a: *mut PyObject, obj_b: *mut PyObject) -> PyReturn {
    // We need to be careful since this method can be called reflexively
    let type_a = Py_TYPE(obj_a);
    let type_b = Py_TYPE(obj_b);
    let mod_a = PyType_GetModule(type_a);
    let mod_b = PyType_GetModule(type_b);
    if mod_a == mod_b && type_b == State::for_mod(mod_a).date_delta_type {
        let DateDelta { months, days } = DateDelta::extract(obj_b);
        Date::extract(obj_a)
            .shift_months(months)
            .and_then(|date| date.shift_days(days))
            .ok_or_value_err("Resulting date out of range")?
            .to_obj(type_a)
    } else {
        // We can safely discount other types within our module
        Err(type_err!(
            "unsupported operand type(s) for +: 'Date' and '{}'",
            (type_b as *mut PyObject).repr()
        ))?
    }
}

unsafe fn add(
    slf: *mut PyObject,
    cls: *mut PyTypeObject,
    args: &[*mut PyObject],
    kwargs: &mut KwargIter,
) -> PyReturn {
    _shift_method(slf, cls, args, kwargs, false)
}

unsafe fn subtract(
    slf: *mut PyObject,
    cls: *mut PyTypeObject,
    args: &[*mut PyObject],
    kwargs: &mut KwargIter,
) -> PyReturn {
    _shift_method(slf, cls, args, kwargs, true)
}

#[inline]
unsafe fn _shift_method(
    slf: *mut PyObject,
    cls: *mut PyTypeObject,
    args: &[*mut PyObject],
    kwargs: &mut KwargIter,
    negate: bool,
) -> PyReturn {
    let fname = if negate { "subtract" } else { "add" };
    let &State {
        str_days,
        str_months,
        str_years,
        str_weeks,
        ..
    } = State::for_type(cls);
    let mut days: i32 = 0;
    let mut months: i32 = 0;
    let mut years: i16 = 0;

    if !args.is_empty() {
        Err(type_err!("{}() takes no positional arguments", fname))?
    };
    handle_kwargs(fname, kwargs, |key, value, eq| {
        if eq(key, str_days) {
            let add_value: i32 = value
                .to_long()?
                .ok_or_type_err("days must be an integer")?
                .try_into()
                .map_err(|_| value_err!("days out of range"))?;
            days += add_value;
        } else if eq(key, str_months) {
            months = value
                .to_long()?
                .ok_or_type_err("months must be an integer")?
                .try_into()
                .map_err(|_| value_err!("months out of range"))?;
        } else if eq(key, str_years) {
            years = value
                .to_long()?
                .ok_or_type_err("years must be an integer")?
                .try_into()
                .map_err(|_| value_err!("years out of range"))?;
        } else if eq(key, str_weeks) {
            let add_value: i32 = value
                .to_long()?
                .ok_or_type_err("weeks must be an integer")?
                .checked_mul(7)
                .ok_or_value_err("weeks out of range")?
                .try_into()
                .map_err(|_| value_err!("weeks out of range"))?;
            days += add_value;
        } else {
            return Ok(false);
        }
        Ok(true)
    })?;
    if negate {
        days = -days;
        months = -months;
        years = -years;
    }

    Date::extract(slf)
        .shift(years, months, days)
        .ok_or_value_err("Resulting date out of range")?
        .to_obj(cls)
}

unsafe fn replace(
    slf: *mut PyObject,
    cls: *mut PyTypeObject,
    args: &[*mut PyObject],
    kwargs: &mut KwargIter,
) -> PyReturn {
    let &State {
        str_year,
        str_month,
        str_day,
        ..
    } = State::for_type(cls);
    if !args.is_empty() {
        Err(type_err!("replace() takes no positional arguments"))
    } else {
        let date = Date::extract(slf);
        let mut year = date.year.into();
        let mut month = date.month.into();
        let mut day = date.day.into();
        handle_kwargs("replace", kwargs, |key, value, eq| {
            if eq(key, str_year) {
                year = value.to_long()?.ok_or_type_err("year must be an integer")?;
            } else if eq(key, str_month) {
                month = value
                    .to_long()?
                    .ok_or_type_err("month must be an integer")?;
            } else if eq(key, str_day) {
                day = value.to_long()?.ok_or_type_err("day must be an integer")?;
            } else {
                return Ok(false);
            }
            Ok(true)
        })?;
        Date::from_longs(year, month, day)
            .ok_or_value_err("Invalid date components")?
            .to_obj(cls)
    }
}

unsafe fn at(slf: *mut PyObject, time_obj: *mut PyObject) -> PyReturn {
    let &State {
        time_type,
        local_datetime_type,
        ..
    } = State::for_obj(slf);
    if Py_TYPE(time_obj) == time_type {
        DateTime {
            date: Date::extract(slf),
            time: Time::extract(time_obj),
        }
        .to_obj(local_datetime_type)
    } else {
        Err(type_err!("argument must be a whenever.Time"))
    }
}

static mut METHODS: &[PyMethodDef] = &[
    method!(py_date, "Convert to a Python datetime.date"),
    method!(
        format_common_iso,
        "Return the date in the common ISO 8601 format"
    ),
    method!(
        parse_common_iso,
        "Create a date from the common ISO 8601 format",
        METH_O | METH_CLASS
    ),
    method!(
        from_py_date,
        "Create a date from a Python datetime.date",
        METH_O | METH_CLASS
    ),
    method!(identity2 named "__copy__", ""),
    method!(identity2 named "__deepcopy__", "", METH_O),
    method!(day_of_week, "Return the day of the week"),
    method!(at, "Combine with a time to create a datetime", METH_O),
    method!(__reduce__, ""),
    method_kwargs!(add, "Add various units to the date"),
    method_kwargs!(subtract, "Subtract various units from the date"),
    method_kwargs!(
        replace,
        "Return a new date with the specified components replaced"
    ),
    PyMethodDef::zeroed(),
];

pub(crate) unsafe fn unpickle(module: *mut PyObject, arg: *mut PyObject) -> PyReturn {
    let mut packed = arg.to_bytes()?.ok_or_type_err("Invalid pickle data")?;
    if packed.len() != 4 {
        Err(value_err!("Invalid pickle data"))?
    }
    Date {
        year: unpack_one!(packed, u16),
        month: unpack_one!(packed, u8),
        day: unpack_one!(packed, u8),
    }
    .to_obj(State::for_mod(module).date_type)
}

unsafe fn get_year(slf: *mut PyObject) -> PyReturn {
    Date::extract(slf).year.to_py()
}

unsafe fn get_month(slf: *mut PyObject) -> PyReturn {
    Date::extract(slf).month.to_py()
}

unsafe fn get_day(slf: *mut PyObject) -> PyReturn {
    Date::extract(slf).day.to_py()
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

type_spec!(Date, SLOTS);

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
        assert_eq!(Date::from_ord_unchecked(1), Date::new(1, 1, 1).unwrap());
        assert_eq!(Date::from_ord_unchecked(365), Date::new(1, 12, 31).unwrap());
        assert_eq!(Date::from_ord_unchecked(366), Date::new(2, 1, 1).unwrap());
        assert_eq!(
            Date::from_ord_unchecked(1_000),
            Date::new(3, 9, 27).unwrap()
        );
        assert_eq!(
            Date::from_ord_unchecked(1_000_000),
            Date::new(2738, 11, 28).unwrap()
        );
        assert_eq!(
            Date::from_ord_unchecked(730179),
            Date::new(2000, 2, 29).unwrap()
        );
        assert_eq!(
            Date::from_ord_unchecked(730180),
            Date::new(2000, 3, 1).unwrap()
        );
        assert_eq!(
            Date::from_ord_unchecked(3_652_059),
            Date::new(9999, 12, 31).unwrap()
        );
    }

    #[test]
    fn test_ord_ymd_reversible() {
        for ord in 1..=(MAX_ORD as u32) {
            let date = Date::from_ord_unchecked(ord);
            assert_eq!(ord, date.ord());
        }
    }

    #[test]
    fn test_increment() {
        assert_eq!(
            Date::new_unchecked(2021, 1, 1).increment(),
            Date::new(2021, 1, 2).unwrap()
        );
        assert_eq!(
            Date::new_unchecked(2021, 1, 31).increment(),
            Date::new(2021, 2, 1).unwrap()
        );
        assert_eq!(
            Date::new_unchecked(2021, 2, 28).increment(),
            Date::new(2021, 3, 1).unwrap()
        );
        assert_eq!(
            Date::new_unchecked(2020, 2, 29).increment(),
            Date::new(2020, 3, 1).unwrap()
        );
        assert_eq!(
            Date::new_unchecked(2020, 12, 31).increment(),
            Date::new(2021, 1, 1).unwrap()
        );
    }

    #[test]
    fn test_decrement() {
        assert_eq!(
            Date::new_unchecked(2021, 1, 2).decrement(),
            Date::new(2021, 1, 1).unwrap()
        );
        assert_eq!(
            Date::new_unchecked(2021, 2, 1).decrement(),
            Date::new(2021, 1, 31).unwrap()
        );
        assert_eq!(
            Date::new_unchecked(2021, 3, 1).decrement(),
            Date::new(2021, 2, 28).unwrap()
        );
        assert_eq!(
            Date::new_unchecked(2020, 3, 1).decrement(),
            Date::new(2020, 2, 29).unwrap()
        );
        assert_eq!(
            Date::new_unchecked(2021, 1, 1).decrement(),
            Date::new(2020, 12, 31).unwrap()
        );
    }
}
