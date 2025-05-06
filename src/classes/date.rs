use core::{
    ffi::{c_int, c_long, c_void, CStr},
    mem,
    ptr::null_mut as NULL,
};
use pyo3_ffi::*;
use std::fmt::{self, Display, Formatter};

use crate::{
    classes::{
        date_delta::{handle_init_kwargs2 as handle_datedelta_kwargs, DateDelta},
        monthday::MonthDay,
        plain_datetime::DateTime,
        time::Time,
        yearmonth::YearMonth,
    },
    common::{
        math::*,
        parse::{extract_2_digits, extract_digit},
        pyobject::*,
        pytype::*,
    },
    docstrings as doc,
    pymodule::State,
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
            self.year.days_before()
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

    // TODO: remove
    pub(crate) unsafe fn from_py_unchecked(obj: *mut PyObject) -> Self {
        debug_assert!(PyDate_Check(obj) == 1);
        Date {
            // Safety: dates coming from Python are always valid
            year: Year::new_unchecked(PyDateTime_GET_YEAR(obj) as _),
            month: Month::new_unchecked(PyDateTime_GET_MONTH(obj) as _),
            day: PyDateTime_GET_DAY(obj) as _,
        }
    }

    pub(crate) fn to_py(
        self,
        &PyDateTime_CAPI {
            DateType,
            Date_FromDate,
            ..
        }: &PyDateTime_CAPI,
    ) -> PyReturn2 {
        // SAFETY: Date_FromDate is safe to call with valid pointers
        unsafe {
            Date_FromDate(
                self.year.get().into(),
                self.month.get().into(),
                self.day.into(),
                DateType,
            )
        }
        .rust_owned()
    }

    pub(crate) fn from_py(d: PyDate) -> Self {
        println!("from_py inner");
        Date {
            // SAFETY: dates coming from Python are always valid
            year: Year::new_unchecked(d.year() as _),
            month: Month::new_unchecked(d.month() as _),
            day: d.day() as _,
        }
    }

    pub(crate) fn day_of_week(self) -> Weekday {
        self.unix_days().day_of_week()
    }

    pub(crate) const fn hash(self) -> i32 {
        // SAFETY: the struct size is equeval to the size of an i32.
        // We don't need to do any extra hashing. It may be counterintuitive,
        // but this is also what `int` does: `hash(6) == 6`.
        unsafe { mem::transmute(self) }
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

fn __new__(cls: PyType, args: PyTuple, kwargs: Option<PyDict>) -> PyReturn2 {
    if args.len() > 3 {
        raise_type_err(format!(
            "Date() takes at most 3 arguments, got {}",
            args.len() + kwargs.map(|x| x.len()).unwrap_or(0)
        ))?
    }

    let mut arg_obj: [Option<PyObj>; 3] = [None, None, None];
    for (i, arg) in args.iter().enumerate() {
        arg_obj[i] = Some(arg);
    }
    if let Some(kwarg_dict) = kwargs {
        let &State {
            str_year,
            str_month,
            str_day,
            ..
        } = cls.state();
        handle_kwargs2("Date", kwarg_dict.iteritems(), |key, value, eq| {
            for (i, &kwname) in [str_year, str_month, str_day].iter().enumerate() {
                if eq(key, kwname) {
                    if arg_obj[i].replace(value).is_some() {
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
            .cast::<PyInt>()
            .ok_or_type_err("year must be an integer")?
            .to_long()?,
        arg_obj[1]
            .ok_or_type_err("function missing required argument 'month'")?
            .cast::<PyInt>()
            .ok_or_type_err("month must be an integer")?
            .to_long()?,
        arg_obj[2]
            .ok_or_type_err("function missing required argument 'day'")?
            .cast::<PyInt>()
            .ok_or_type_err("day must be an integer")?
            .to_long()?,
    )
    .ok_or_value_err("Invalid date components")?
    .to_obj2(cls)
}

fn __richcmp__(cls: PyType, a: Date, b_obj: PyObj, op: c_int) -> PyReturn2 {
    match b_obj.extract2::<Date>(cls) {
        Some(b) => match op {
            pyo3_ffi::Py_EQ => a == b,
            pyo3_ffi::Py_NE => a != b,
            pyo3_ffi::Py_LT => a < b,
            pyo3_ffi::Py_LE => a <= b,
            pyo3_ffi::Py_GT => a > b,
            pyo3_ffi::Py_GE => a >= b,
            _ => unreachable!(),
        }
        .to_py2(),
        None => Ok(not_implemented()),
    }
}

fn __str__(_: PyType, slf: Date) -> PyReturn2 {
    // TODO: avoid heap allocation since it's fixed size
    format!("{}", slf).to_py2()
}

fn __repr__(_: PyType, slf: Date) -> PyReturn2 {
    // TODO: avoid heap allocation since it's fixed size
    format!("Date({})", slf).to_py2()
}

#[allow(static_mut_refs)]
static mut SLOTS: &[PyType_Slot] = &[
    slotmethod2!(Py_tp_new, __new__),
    slotmethod2!(Py_tp_str, __str__, 1),
    slotmethod2!(Py_tp_repr, __repr__, 1),
    slotmethod2!(Py_tp_richcompare, __richcmp__),
    slotmethod2!(Py_nb_subtract, __sub__, 2),
    slotmethod2!(Py_nb_add, __add__, 2),
    PyType_Slot {
        slot: Py_tp_doc,
        pfunc: doc::DATE.as_ptr() as *mut c_void,
    },
    PyType_Slot {
        slot: Py_tp_methods,
        pfunc: unsafe { METHODS.as_mut_ptr().cast() },
    },
    PyType_Slot {
        slot: Py_tp_getset,
        pfunc: unsafe { GETSETTERS.as_mut_ptr().cast() },
    },
    PyType_Slot {
        slot: Py_tp_hash,
        pfunc: {
            unsafe extern "C" fn __hash__(slf: *mut PyObject) -> Py_hash_t {
                Date::extract(slf).hash() as Py_hash_t
            }
            __hash__
        } as *mut c_void,
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

fn py_date(cls: PyType, slf: Date) -> PyReturn2 {
    slf.to_py(cls.state().py_api)
}

fn from_py_date(cls: PyType, arg: PyObj) -> PyReturn2 {
    Date::from_py(
        arg.cast::<PyDate>()
            .ok_or_type_err("argument must be a datetime.date")?,
    )
    .to_obj2(cls)
}

fn year_month(cls: PyType, Date { year, month, .. }: Date) -> PyReturn2 {
    YearMonth::new(year, month).to_obj2(cls.state().yearmonth_type)
}

fn month_day(cls: PyType, Date { month, day, .. }: Date) -> PyReturn2 {
    MonthDay::new_unchecked(month, day).to_obj2(cls.state().monthday_type)
}

fn format_common_iso(_: PyType, slf: Date) -> PyReturn2 {
    format!("{}", slf).to_py2()
}

fn parse_common_iso(cls: PyType, s: PyObj) -> PyReturn2 {
    Date::parse_iso(
        s.cast::<PyStr>()
            .ok_or_type_err("argument must be str")?
            .as_utf8()?,
    )
    .ok_or_else_value_err(|| format!("Invalid format: {}", s.repr()))?
    .to_obj2(cls)
}

fn day_of_week(cls: PyType, slf: Date) -> PyReturn2 {
    let enum_members = cls.state().weekday_enum_members;
    Ok(enum_members[slf.day_of_week() as usize - 1].newref())
}

fn __reduce__(cls: PyType, Date { year, month, day }: Date) -> PyResult<Owned<PyTuple>> {
    let data = pack![year.get(), month.get(), day];
    (
        PyObj::new(cls.state().unpickle_date).unwrap().newref(),
        (data.to_py2()?,).into_pytuple()?,
    )
        .into_pytuple()
}

fn __sub__(obj_a: PyObj, obj_b: PyObj) -> PyReturn2 {
    let type_a = obj_a.class();
    let type_b = obj_b.class();

    // Easy case: Date - Date
    if type_b == type_a {
        // SAFETY: the only way to get here is if *both* are Date
        let a: Date = unsafe { obj_a.extract_unchecked() };
        let b: Date = unsafe { obj_b.extract_unchecked() };

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
        .to_obj2(type_a.state().date_delta_type)
    // Case: types within whenever module.
    //       This is more complicated than it seems since we can have
    //       reflective operations like Date - DateDelta or DateDelta - Date
    } else if type_a.same_module(type_b) {
        let DateDelta { months, days } = obj_b
            .extract2(type_a.state().date_delta_type)
            // It's important that we don't return NotImplemented here,
            // in order not to trigger reflexive calls
            .ok_or_else_type_err(|| {
                format!(
                    "unsupported operand type(s) for -: 'Date' and '{}'",
                    type_b.repr()
                )
            })?;
        // SAFETY: at least one of the operands must be a Date
        unsafe { obj_a.extract_unchecked::<Date>() }
            .shift_months(-months)
            .and_then(|date| date.shift_days(-days))
            .ok_or_value_err("Resulting date out of range")?
            .to_obj2(type_a)
    // Case: other types
    } else {
        Ok(not_implemented())
    }
}

fn __add__(obj_a: PyObj, obj_b: PyObj) -> PyReturn2 {
    // We need to be careful since this method can be called reflexively
    let type_a = obj_a.class();
    let type_b = obj_b.class();
    if type_a.same_module(type_b) {
        let DateDelta { months, days } = obj_b
            .extract2(type_a.state().date_delta_type)
            .ok_or_else_type_err(|| {
                format!(
                    "unsupported operand type(s) for +: 'Date' and '{}'",
                    type_b.repr()
                )
            })?;
        // SAFETY: at least one of the operands must be a Date
        unsafe { obj_a.extract_unchecked::<Date>() }
            .shift_months(months)
            .and_then(|date| date.shift_days(days))
            .ok_or_value_err("Resulting date out of range")?
            .to_obj2(type_a)
    } else {
        Ok(not_implemented())
    }
}

fn add(cls: PyType, slf: Date, args: &[PyObj], kwargs: &mut IterKwargs) -> PyReturn2 {
    _shift_method(cls, slf, args, kwargs, false)
}

fn subtract(cls: PyType, slf: Date, args: &[PyObj], kwargs: &mut IterKwargs) -> PyReturn2 {
    _shift_method(cls, slf, args, kwargs, true)
}

#[inline]
fn _shift_method(
    cls: PyType,
    slf: Date,
    args: &[PyObj],
    kwargs: &mut IterKwargs,
    negate: bool,
) -> PyReturn2 {
    let fname = if negate { "subtract" } else { "add" };
    let (mut months, mut days) = match (args, kwargs.len()) {
        (&[arg], 0) => {
            let delta_type = cls.state().date_delta_type;
            let DateDelta { months, days } = arg
                .extract2::<DateDelta>(delta_type)
                .ok_or_type_err(format!("{}() argument must be a whenever.DateDelta", fname))?;
            (months, days)
        }
        ([], _) => {
            let &State {
                str_days,
                str_months,
                str_years,
                str_weeks,
                ..
            } = cls.state();
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

    slf.shift(months, days)
        .ok_or_value_err("Resulting date out of range")?
        .to_obj2(cls)
}

fn days_since(cls: PyType, slf: Date, other: PyObj) -> PyReturn2 {
    slf.unix_days()
        .diff(
            other
                .extract2::<Date>(cls)
                .ok_or_type_err("argument must be a whenever.Date")?
                .unix_days(),
        )
        .get()
        .to_py2()
}

fn days_until(cls: PyType, slf: Date, other: PyObj) -> PyReturn2 {
    other
        .extract2::<Date>(cls)
        .ok_or_type_err("argument must be a whenever.Date")?
        .unix_days()
        .diff(slf.unix_days())
        .get()
        .to_py2()
}

fn replace(cls: PyType, slf: Date, args: &[PyObj], kwargs: &mut IterKwargs) -> PyReturn2 {
    if !args.is_empty() {
        raise_type_err("replace() takes no positional arguments")?
    }

    let &State {
        str_year,
        str_month,
        str_day,
        ..
    } = cls.state();
    let mut year = slf.year.get().into();
    let mut month = slf.month.get().into();
    let mut day = slf.day.into();
    handle_kwargs2("replace", kwargs, |key, value, eq| {
        if eq(key, str_year) {
            year = value
                .cast::<PyInt>()
                .ok_or_type_err("year must be an integer")?
                .to_long()?;
        } else if eq(key, str_month) {
            month = value
                .cast::<PyInt>()
                .ok_or_type_err("month must be an integer")?
                .to_long()?;
        } else if eq(key, str_day) {
            day = value
                .cast::<PyInt>()
                .ok_or_type_err("day must be an integer")?
                .to_long()?;
        } else {
            return Ok(false);
        }
        Ok(true)
    })?;
    Date::from_longs(year, month, day)
        .ok_or_value_err("Invalid date components")?
        .to_obj2(cls)
}

fn at(cls: PyType, date: Date, time_obj: PyObj) -> PyReturn2 {
    let &State {
        time_type,
        plain_datetime_type,
        ..
    } = cls.state();
    let time: Time = time_obj
        .extract2(time_type)
        .ok_or_type_err("argument must be a whenever.Time")?;
    DateTime { date, time }.to_obj2(plain_datetime_type)
}

fn today_in_system_tz(cls: PyType) -> PyReturn2 {
    let state = cls.state();
    let epoch = state.time_ns()?.epoch;
    Date::from_py(system_tz_today_from_timestamp(state.py_api, epoch)?.borrow()).to_obj2(cls)
}

fn system_tz_today_from_timestamp(
    &PyDateTime_CAPI {
        Date_FromTimestamp,
        DateType,
        ..
    }: &PyDateTime_CAPI,
    s: EpochSecs,
) -> PyResult<Owned<PyDate>> {
    let timestamp_obj = s.get().to_py2()?;
    let args = (timestamp_obj,).into_pytuple()?;
    Ok(unsafe {
        // we make use of the fact that date.fromtimstamp() by default
        // uses the system timezone
        // SAFETY: Date_FromTimestamp is safe to call with valid pointers
        Date_FromTimestamp(DateType, args.as_ptr())
            .rust_owned()?
            // SAFETY: safe to assume Date_FromTimestamp returns a date
            .cast_unchecked::<PyDate>()
    })
}

static mut METHODS: &mut [PyMethodDef] = &mut [
    method0!(py_date, doc::DATE_PY_DATE),
    method0!(format_common_iso, doc::DATE_FORMAT_COMMON_ISO),
    classmethod0!(today_in_system_tz, doc::DATE_TODAY_IN_SYSTEM_TZ),
    classmethod1!(parse_common_iso, doc::DATE_PARSE_COMMON_ISO),
    classmethod1!(from_py_date, doc::DATE_FROM_PY_DATE),
    method0!(__copy__, c""),
    method1!(__deepcopy__, c""),
    method0!(year_month, doc::DATE_YEAR_MONTH),
    method0!(month_day, doc::DATE_MONTH_DAY),
    method1!(at, doc::DATE_AT),
    method0!(day_of_week, doc::DATE_DAY_OF_WEEK),
    method0!(__reduce__, c""),
    method_kwargs2!(add, doc::DATE_ADD),
    method_kwargs2!(subtract, doc::DATE_SUBTRACT),
    method1!(days_since, doc::DATE_DAYS_SINCE),
    method1!(days_until, doc::DATE_DAYS_UNTIL),
    method_kwargs2!(replace, doc::DATE_REPLACE),
    PyMethodDef::zeroed(),
];

pub(crate) fn unpickle(state: &State, arg: PyObj) -> PyReturn2 {
    let binding = arg
        .cast::<PyBytes>()
        .ok_or_type_err("Pickle date must be `bytes` object")?;
    let mut packed = binding.as_bytes()?;
    if packed.len() != 4 {
        raise_value_err("Invalid pickle data")?
    }
    Date {
        year: Year::new_unchecked(unpack_one!(packed, u16)),
        month: Month::new_unchecked(unpack_one!(packed, u8)),
        day: unpack_one!(packed, u8),
    }
    .to_obj2(state.date_type)
}

fn get_year(_: PyType, slf: Date) -> PyReturn2 {
    // TODO: just return Year which implements IntoPy?
    slf.year.get().to_py2()
}

fn get_month(_: PyType, slf: Date) -> PyReturn2 {
    slf.month.get().to_py2()
}

fn get_day(_: PyType, slf: Date) -> PyReturn2 {
    slf.day.to_py2()
}

static mut GETSETTERS: &mut [PyGetSetDef] = &mut [
    getter2!(
        get_year named "year",
        "The year component"
    ),
    getter2!(
        get_month named "month",
        "The month component"
    ),
    getter2!(
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
