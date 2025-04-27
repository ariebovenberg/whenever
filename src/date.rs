use core::{
    ffi::{c_int, c_long, c_void, CStr},
    mem,
    ptr::null_mut as NULL,
};
use pyo3_ffi::*;
use std::{
    fmt::{self, Display, Formatter},
    ptr::NonNull,
};

use crate::{
    common::{math::*, *},
    date_delta::{handle_init_kwargs as handle_datedelta_kwargs, DateDelta},
    docstrings as doc,
    monthday::MonthDay,
    plain_datetime::DateTime,
    time::Time,
    yearmonth::YearMonth,
    State,
};

#[derive(Debug, Eq, PartialEq, Ord, PartialOrd, Copy, Clone)]
pub struct Date {
    pub(crate) year: Year,
    pub(crate) month: Month,
    pub(crate) day: u8,
}

pub(crate) const SINGLETONS: &[(&CStr, Date); 2] = &[(c"MIN", Date::MIN), (c"MAX", Date::MAX)];

impl Date {
    pub(crate) const MAX: Date = Date {
        year: Year::MAX,
        month: Month::December,
        day: 31,
    };
    pub(crate) const MIN: Date = Date {
        year: Year::MIN,
        month: Month::January,
        day: 1,
    };

    pub fn new(year: Year, month: Month, day: u8) -> Option<Self> {
        (day >= 1 && day <= year.days_in_month(month)).then_some(Date { year, month, day })
    }

    pub(crate) fn last_of_month(year: Year, month: Month) -> Self {
        Date {
            year,
            month,
            day: year.days_in_month(month),
        }
    }

    pub(crate) fn first_of_month(year: Year, month: Month) -> Self {
        Date {
            year,
            month,
            day: 1,
        }
    }

    pub(crate) fn from_longs(y: c_long, m: c_long, day: c_long) -> Option<Self> {
        let year = Year::from_long(y)?;
        let month = Month::from_long(m)?;
        (day >= 1 && day <= year.days_in_month(month) as _).then_some(Date {
            year,
            month,
            day: day as _,
        })
    }

    pub(crate) fn unix_days(self) -> UnixDays {
        // Safety: unix days and dates have the same range, conversions are always valid
        UnixDays::new_unchecked(
            days_before_year(self.year)
                + self.year.days_before_month(self.month) as i32
                + self.day as i32
                + UnixDays::MIN.get()
                - 1,
        )
    }

    pub(crate) fn epoch_at(self, t: Time) -> EpochSecs {
        self.unix_days().epoch_at(t)
    }

    pub(crate) fn epoch(self) -> EpochSecs {
        EpochSecs::new_unchecked(self.unix_days().get() as i64 * S_PER_DAY as i64)
    }

    pub(crate) fn shift(self, months: DeltaMonths, days: DeltaDays) -> Option<Date> {
        self.shift_months(months).and_then(|x| x.shift_days(days))
    }

    pub(crate) fn shift_days(self, days: DeltaDays) -> Option<Date> {
        Some(self.unix_days().shift(days)?.date())
    }

    pub(crate) fn shift_months(self, months: DeltaMonths) -> Option<Date> {
        // Safe: both values are ranged well within i32::MAX
        let month_unclamped = self.month as i32 + months.get();
        // Safe: remainder of division by 12 is always in range
        let month = Month::new_unchecked((month_unclamped - 1).rem_euclid(12) as u8 + 1);
        let year = Year::from_i32(self.year.get() as i32 + (month_unclamped - 1).div_euclid(12))?;
        Some(Date {
            year,
            month,
            // Remember to cap the day to the last day of the month
            day: self.day.min(year.days_in_month(month)),
        })
    }

    /// Parse YYYY-MM-DD
    pub(crate) fn parse_iso_extended(s: [u8; 10]) -> Option<Self> {
        (s[4] == b'-' && s[7] == b'-')
            .then(|| {
                Date::new(
                    extract_year(&s, 0)?,
                    extract_2_digits(&s, 5).and_then(Month::new)?,
                    extract_2_digits(&s, 8)?,
                )
            })
            .flatten()
    }

    /// Parse YYYYMMDD
    pub(crate) fn parse_iso_basic(s: [u8; 8]) -> Option<Self> {
        Date::new(
            extract_year(&s, 0)?,
            extract_2_digits(&s, 4).and_then(Month::new)?,
            extract_2_digits(&s, 6)?,
        )
    }

    pub(crate) fn parse_iso(s: &[u8]) -> Option<Self> {
        match s.len() {
            8 => Self::parse_iso_basic(s.try_into().unwrap()),
            10 => Self::parse_iso_extended(s.try_into().unwrap()),
            _ => None,
        }
    }

    // For small adjustments, this is faster than converting to/from UnixDays
    pub fn tomorrow(self) -> Option<Self> {
        let Date {
            mut year,
            mut month,
            mut day,
        } = self;
        if day < year.days_in_month(month) {
            day += 1;
        } else if month < Month::December {
            day = 1;
            month = Month::new_unchecked(month.get() + 1);
        } else {
            day = 1;
            month = Month::January;
            year = Year::new(year.get() + 1)?;
        }
        Some(Date { year, month, day })
    }

    // For small adjustments, this is faster than converting to/from UnixDays
    pub(crate) fn yesterday(self) -> Option<Self> {
        let Date {
            mut year,
            mut month,
            mut day,
        } = self;
        if day > 1 {
            day -= 1
        } else if month > Month::January {
            month = Month::new_unchecked(month.get() - 1);
            day = year.days_in_month(month);
        } else {
            day = 31;
            month = Month::December;
            year = Year::new(year.get() - 1)?;
        }
        Some(Date { year, month, day })
    }

    pub(crate) unsafe fn from_py_unchecked(obj: *mut PyObject) -> Self {
        debug_assert!(PyDate_Check(obj) == 1);
        Date {
            // Safety: dates coming from Python are always valid
            year: Year::new_unchecked(PyDateTime_GET_YEAR(obj) as _),
            month: Month::new_unchecked(PyDateTime_GET_MONTH(obj) as _),
            day: PyDateTime_GET_DAY(obj) as _,
        }
    }

    pub(crate) fn day_of_week(self) -> Weekday {
        self.unix_days().day_of_week()
    }

    pub(crate) const unsafe fn hash(self) -> i32 {
        // Since the data already fits within an i32
        // we don't need to do any extra hashing. It may be counterintuitive,
        // but this is also what `int` does: `hash(6) == 6`.
        mem::transmute(self)
    }
}

pub(crate) fn extract_year(s: &[u8], index: usize) -> Option<Year> {
    Some(
        extract_digit(s, index)? as u16 * 1000
            + extract_digit(s, index + 1)? as u16 * 100
            + extract_digit(s, index + 2)? as u16 * 10
            + extract_digit(s, index + 3)? as u16,
    )
    .filter(|&y| y > 0)
    .map(Year::new_unchecked)
}

pub(crate) fn extract_2_digits(s: &[u8], index: usize) -> Option<u8> {
    Some(extract_digit(s, index)? * 10 + extract_digit(s, index + 1)?)
}

impl PyWrapped for Date {}

impl Display for Date {
    fn fmt(&self, f: &mut Formatter<'_>) -> fmt::Result {
        write!(
            f,
            "{:04}-{:02}-{:02}",
            self.year.get(),
            self.month.get(),
            self.day
        )
    }
}

unsafe fn __new__(cls: *mut PyTypeObject, args: *mut PyObject, kwargs: *mut PyObject) -> PyReturn {
    let nargs = PyTuple_GET_SIZE(args);
    if nargs <= 3 {
        let mut arg_obj: [Option<NonNull<PyObject>>; 3] = [None, None, None];
        for i in 0..nargs {
            arg_obj[i as usize] = Some(NonNull::new_unchecked(PyTuple_GET_ITEM(args, i)));
        }
        if let Some(items) = DictItems::new(kwargs) {
            let &State {
                str_year,
                str_month,
                str_day,
                ..
            } = State::for_type(cls);
            handle_kwargs("Date", items, |key, value, eq| {
                for (i, &kwname) in [str_year, str_month, str_day].iter().enumerate() {
                    if eq(key, kwname) {
                        if arg_obj[i].replace(NonNull::new_unchecked(value)).is_some() {
                            raise_type_err(format!(
                                "Date() got multiple values for argument {}",
                                kwname.repr()
                            ))?;
                        }
                        return Ok(true);
                    }
                }
                Ok(false)
            })?;
        };
        Date::from_longs(
            arg_obj[0]
                .ok_or_type_err("function missing required argument 'year'")?
                .as_ptr()
                .to_long()?
                .ok_or_type_err("year must be an integer")?,
            arg_obj[1]
                .ok_or_type_err("function missing required argument 'month'")?
                .as_ptr()
                .to_long()?
                .ok_or_type_err("month must be an integer")?,
            arg_obj[2]
                .ok_or_type_err("function missing required argument 'day'")?
                .as_ptr()
                .to_long()?
                .ok_or_type_err("day must be an integer")?,
        )
        .ok_or_value_err("Invalid date components")?
        .to_obj(cls)
    } else {
        raise_type_err(format!(
            "Date() takes at most 3 arguments, got {}",
            nargs
                + if kwargs.is_null() {
                    0
                } else {
                    PyDict_Size(kwargs)
                }
        ))?
    }
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

#[allow(static_mut_refs)]
static mut SLOTS: &[PyType_Slot] = &[
    slotmethod!(Py_tp_new, __new__),
    slotmethod!(Py_tp_str, __str__, 1),
    slotmethod!(Py_tp_repr, __repr__, 1),
    slotmethod!(Py_tp_richcompare, __richcmp__),
    slotmethod!(Py_nb_subtract, __sub__, 2),
    slotmethod!(Py_nb_add, __add__, 2),
    PyType_Slot {
        slot: Py_tp_doc,
        pfunc: doc::DATE.as_ptr() as *mut c_void,
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
    Date_FromDate(year.get().into(), month.get().into(), day.into(), DateType).as_result()
}

unsafe fn from_py_date(cls: *mut PyObject, date: *mut PyObject) -> PyReturn {
    if PyDate_Check(date) == 0 {
        raise_type_err("argument must be a Date")
    } else {
        Date::from_py_unchecked(date).to_obj(cls.cast())
    }
}

unsafe fn year_month(slf: *mut PyObject, _: *mut PyObject) -> PyReturn {
    let Date { year, month, .. } = Date::extract(slf);
    YearMonth::new_unchecked(year.get(), month.get()).to_obj(State::for_obj(slf).yearmonth_type)
}

unsafe fn month_day(slf: *mut PyObject, _: *mut PyObject) -> PyReturn {
    let Date { month, day, .. } = Date::extract(slf);
    MonthDay::new_unchecked(month, day).to_obj(State::for_obj(slf).monthday_type)
}

unsafe fn __str__(slf: *mut PyObject) -> PyReturn {
    format!("{}", Date::extract(slf)).to_py()
}

unsafe fn format_common_iso(slf: *mut PyObject, _: *mut PyObject) -> PyReturn {
    __str__(slf)
}

unsafe fn parse_common_iso(cls: *mut PyObject, s: *mut PyObject) -> PyReturn {
    Date::parse_iso(s.to_utf8()?.ok_or_type_err("argument must be str")?)
        .ok_or_else_value_err(|| format!("Invalid format: {}", s.repr()))?
        .to_obj(cls.cast())
}

pub(crate) const fn days_before_year(year: Year) -> i32 {
    let y = (year.get() - 1) as i32;
    y * 365 + y / 4 - y / 100 + y / 400
}

unsafe fn day_of_week(slf: *mut PyObject, _: *mut PyObject) -> PyReturn {
    let enum_members = State::for_obj(slf).weekday_enum_members;
    Ok(newref(
        enum_members[Date::extract(slf).day_of_week() as usize - 1]
            .as_mut()
            .unwrap(),
    ))
}

unsafe fn __reduce__(slf: *mut PyObject, _: *mut PyObject) -> PyReturn {
    let Date { year, month, day } = Date::extract(slf);
    (
        State::for_obj(slf).unpickle_date,
        steal!((steal!(pack![year.get(), month.get(), day].to_py()?),).to_py()?),
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

        let year_a = a.year.get() as i32;
        let year_b = b.year.get() as i32;
        let month_a = a.month as i32;
        let month_b = b.month as i32;
        let mut days = a.day as i32;

        // Safe: subtraction is always within bounds
        let mut months = DeltaMonths::new_unchecked(month_a - month_b + 12 * (year_a - year_b));

        // FUTURE: use unchecked, faster version of this function
        let mut moved_a = b
            .shift_months(months)
            // The move is within bounds since we derived it from the dates
            .unwrap();

        // Check if we've overshot
        if b > a && moved_a < a {
            months = DeltaMonths::new_unchecked(months.get() + 1);
            moved_a = b.shift_months(months).unwrap();
            days -= a.year.days_in_month(a.month) as i32;
        } else if b < a && moved_a > a {
            months = DeltaMonths::new_unchecked(months.get() - 1);
            moved_a = b.shift_months(months).unwrap();
            days += moved_a.year.days_in_month(moved_a.month) as i32;
        };
        DateDelta {
            months,
            days: DeltaDays::new_unchecked(days - moved_a.day as i32),
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
            // FUTURE: do we unnecessarily eliminate classes implementing __rsub__?
            // We can safely discount other types within our module
            raise_type_err(format!(
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
        raise_type_err(format!(
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
    let (mut months, mut days) = match (args, kwargs.len()) {
        (&[arg], 0) => {
            let delta_type = State::for_type(cls).date_delta_type;
            if Py_TYPE(arg) == delta_type {
                let DateDelta { months, days } = DateDelta::extract(args[0]);
                (months, days)
            } else {
                raise_type_err(format!("{}() argument must be a whenever.DateDelta", fname))?
            }
        }
        ([], _) => {
            let &State {
                str_days,
                str_months,
                str_years,
                str_weeks,
                ..
            } = State::for_type(cls);
            handle_datedelta_kwargs(fname, kwargs, str_years, str_months, str_days, str_weeks)?
        }
        _ => raise_type_err(format!(
            "{}() takes either only kwargs or 1 positional arg",
            fname
        ))?,
    };
    if negate {
        days = -days;
        months = -months;
    }

    Date::extract(slf)
        .shift(months, days)
        .ok_or_value_err("Resulting date out of range")?
        .to_obj(cls)
}

unsafe fn days_since(a: *mut PyObject, b: *mut PyObject) -> PyReturn {
    if Py_TYPE(b) != Py_TYPE(a) {
        raise_type_err("argument must be a whenever.Date")?
    }
    Date::extract(a)
        .unix_days()
        .diff(Date::extract(b).unix_days())
        .get()
        .to_py()
}

unsafe fn days_until(a: *mut PyObject, b: *mut PyObject) -> PyReturn {
    days_since(b, a)
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
        raise_type_err("replace() takes no positional arguments")
    } else {
        let date = Date::extract(slf);
        let mut year = date.year.get().into();
        let mut month = date.month.get().into();
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
        plain_datetime_type,
        ..
    } = State::for_obj(slf);
    if Py_TYPE(time_obj) == time_type {
        DateTime {
            date: Date::extract(slf),
            time: Time::extract(time_obj),
        }
        .to_obj(plain_datetime_type)
    } else {
        raise_type_err("argument must be a whenever.Time")
    }
}

unsafe fn today_in_system_tz(cls: *mut PyObject, _: *mut PyObject) -> PyReturn {
    let state = State::for_type(cls.cast());
    let &PyDateTime_CAPI {
        Date_FromTimestamp,
        DateType,
        ..
    } = state.py_api;
    let timestamp_obj = state.time_ns()?.epoch.get().to_py()?;
    defer_decref!(timestamp_obj);
    // date.fromtimstamp() will translate to the system timezone for us
    let date = Date_FromTimestamp(DateType, steal!((timestamp_obj,).to_py()?)).as_result()?;
    defer_decref!(date);
    Date::from_py_unchecked(date).to_obj(cls.cast())
}

static mut METHODS: &[PyMethodDef] = &[
    method!(py_date, doc::DATE_PY_DATE),
    method!(
        today_in_system_tz,
        doc::DATE_TODAY_IN_SYSTEM_TZ,
        METH_CLASS | METH_NOARGS
    ),
    method!(format_common_iso, doc::DATE_FORMAT_COMMON_ISO),
    method!(
        parse_common_iso,
        doc::DATE_PARSE_COMMON_ISO,
        METH_O | METH_CLASS
    ),
    method!(from_py_date, doc::DATE_FROM_PY_DATE, METH_O | METH_CLASS),
    method!(identity2 named "__copy__", c""),
    method!(identity2 named "__deepcopy__", c"", METH_O),
    method!(day_of_week, doc::DATE_DAY_OF_WEEK),
    method!(at, doc::DATE_AT, METH_O),
    method!(year_month, doc::DATE_YEAR_MONTH),
    method!(month_day, doc::DATE_MONTH_DAY),
    method!(__reduce__, c""),
    method_kwargs!(add, doc::DATE_ADD),
    method_kwargs!(subtract, doc::DATE_SUBTRACT),
    method!(days_since, doc::DATE_DAYS_SINCE, METH_O),
    method!(days_until, doc::DATE_DAYS_UNTIL, METH_O),
    method_kwargs!(replace, doc::DATE_REPLACE),
    PyMethodDef::zeroed(),
];

pub(crate) unsafe fn unpickle(module: *mut PyObject, arg: *mut PyObject) -> PyReturn {
    let mut packed = arg.to_bytes()?.ok_or_type_err("Invalid pickle data")?;
    if packed.len() != 4 {
        raise_value_err("Invalid pickle data")?
    }
    Date {
        year: Year::new_unchecked(unpack_one!(packed, u16)),
        month: Month::new_unchecked(unpack_one!(packed, u8)),
        day: unpack_one!(packed, u8),
    }
    .to_obj(State::for_mod(module).date_type)
}

unsafe fn get_year(slf: *mut PyObject) -> PyReturn {
    Date::extract(slf).year.get().to_py()
}

unsafe fn get_month(slf: *mut PyObject) -> PyReturn {
    Date::extract(slf).month.get().to_py()
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

pub(crate) static mut SPEC: PyType_Spec = type_spec::<Date>(c"whenever.Date", unsafe { SLOTS });

#[cfg(test)]
mod tests {
    use super::*;

    fn mkdate(year: u16, month: u8, day: u8) -> Date {
        Date {
            year: Year::new_unchecked(year),
            month: Month::new_unchecked(month),
            day,
        }
    }

    #[test]
    fn test_check_date_valid() {
        let cases = &[
            (2021, 1, 1),
            (2021, 12, 31),
            (2021, 2, 28),
            (2020, 2, 29),
            (2021, 4, 30),
            (2000, 2, 29),
            (1900, 2, 28),
        ];
        for &(year, month, day) in cases {
            assert_eq!(
                Date::new(year.try_into().unwrap(), month.try_into().unwrap(), day),
                Some(mkdate(year, month, day))
            );
        }
    }

    #[test]
    fn test_check_date_invalid_day() {
        let cases = &[
            (2021, 1, 0),
            (2021, 1, 32),
            (2021, 4, 31),
            (2021, 2, 29),
            (2020, 2, 30),
            (2000, 2, 30),
            (1900, 2, 29),
        ];
        for &(year, month, day) in cases {
            assert_eq!(
                Date::new(year.try_into().unwrap(), month.try_into().unwrap(), day),
                None
            );
        }
    }

    #[test]
    fn test_unix_days_reversible() {
        for n in UnixDays::MIN.get()..=UnixDays::MAX.get() {
            let date = UnixDays::new_unchecked(n).date();
            assert_eq!(n, date.unix_days().get());
        }
    }

    #[test]
    fn test_tomorrow() {
        assert_eq!(mkdate(2021, 1, 1).tomorrow().unwrap(), mkdate(2021, 1, 2));
        assert_eq!(mkdate(2021, 1, 31).tomorrow().unwrap(), mkdate(2021, 2, 1));
        assert_eq!(mkdate(2021, 2, 28).tomorrow().unwrap(), mkdate(2021, 3, 1));
        assert_eq!(mkdate(2020, 2, 29).tomorrow().unwrap(), mkdate(2020, 3, 1));
        assert_eq!(mkdate(2020, 12, 31).tomorrow().unwrap(), mkdate(2021, 1, 1));
    }

    #[test]
    fn test_yesterday() {
        assert_eq!(mkdate(2021, 1, 2).yesterday().unwrap(), mkdate(2021, 1, 1));
        assert_eq!(mkdate(2021, 2, 1).yesterday().unwrap(), mkdate(2021, 1, 31));
        assert_eq!(mkdate(2021, 3, 1).yesterday().unwrap(), mkdate(2021, 2, 28));
        assert_eq!(mkdate(2020, 3, 1).yesterday().unwrap(), mkdate(2020, 2, 29));
        assert_eq!(
            mkdate(2021, 1, 1).yesterday().unwrap(),
            mkdate(2020, 12, 31)
        );
    }
}
