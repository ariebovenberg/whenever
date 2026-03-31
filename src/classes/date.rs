use core::{
    ffi::{CStr, c_int, c_long, c_void},
    mem,
    ptr::null_mut as NULL,
};
use pyo3_ffi::*;
use std::fmt::{Display, Formatter};

use crate::{
    classes::{
        date_delta::{DateDelta, handle_init_kwargs as handle_datedelta_kwargs},
        itemized_date_delta::ItemizedDateDelta,
        plain_datetime::DateTime,
        time::Time,
    },
    common::{
        fmt::{self, Chunk},
        math::{self, CalUnit, CalUnitSet, DateRoundIncrement, DateSinceUnits},
        parse::{extract_2_digits, extract_digit},
        pattern, round,
        scalar::*,
    },
    docstrings as doc,
    py::*,
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

    /// Like new(), but clamps the day (up to 31) to to shorter months
    pub fn new_clamp_days(year: Year, month: Month, day: u8) -> Self {
        debug_assert!(day <= 31);
        debug_assert!(day > 0);
        Date {
            year,
            month,
            day: day.min(year.days_in_month(month)),
        }
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

    /// Core logic for finding the nth weekday in a month.
    /// Positive n counts from the start (1 = first), negative from the end (-1 = last).
    /// Returns None if the nth occurrence doesn't exist.
    pub(crate) fn nth_weekday_in_month(
        year: Year,
        month: Month,
        n: i32,
        target_dow: Weekday,
    ) -> Option<Date> {
        debug_assert!(n != 0);
        let target_dow = target_dow as i32;
        let day = if n > 0 {
            let first_dow = Date::first_of_month(year, month).day_of_week() as i32;
            let offset = (target_dow - first_dow).rem_euclid(7);
            1 + offset + (n - 1) * 7
        } else {
            let dim = year.days_in_month(month) as i32;
            let last_dow = Date::last_of_month(year, month).day_of_week() as i32;
            let offset = (last_dow - target_dow).rem_euclid(7);
            dim - offset + (n + 1) * 7
        };
        let dim = year.days_in_month(month) as i32;
        (day >= 1 && day <= dim).then_some(Date {
            year,
            month,
            day: day as u8,
        })
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
        // SAFETY: unix days and dates have the same range, conversions are always valid
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
        let (year, month) = self.month.shift(self.year, months)?;
        Some(Date::new_clamp_days(year, month, self.day))
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

    pub(crate) fn format_iso(self, basic: bool) -> IsoFormat {
        IsoFormat { date: self, basic }
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

    pub(crate) fn to_py(
        self,
        &PyDateTime_CAPI {
            DateType,
            Date_FromDate,
            ..
        }: &PyDateTime_CAPI,
    ) -> PyReturn {
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

    /// Compute the ISO week year and week number for this date.
    pub(crate) fn iso_year_week(self) -> (i32, u8) {
        let day_of_year = self.year.days_before_month(self.month) + self.day as u16;
        // ISO weekday: Monday=1, Sunday=7
        let dow = self.day_of_week() as u8;
        // The nearest Thursday determines the ISO year and week
        let nearest_thursday_doy = day_of_year as i32 + (4 - dow as i32);
        let mut iso_year = self.year.get() as i32;

        if nearest_thursday_doy <= 0 {
            // Belongs to the previous year's last week
            iso_year -= 1;
            let prev_year_days = if Year::new_unchecked(iso_year as u16).is_leap() {
                366
            } else {
                365
            };
            let week = (nearest_thursday_doy + prev_year_days - 1) / 7 + 1;
            (iso_year, week as u8)
        } else {
            let year_days = if self.year.is_leap() { 366 } else { 365 };
            if nearest_thursday_doy > year_days {
                // Belongs to the next year's first week
                iso_year += 1;
                (iso_year, 1)
            } else {
                let week = (nearest_thursday_doy - 1) / 7 + 1;
                (iso_year, week as u8)
            }
        }
    }

    pub(crate) const fn hash(self) -> i32 {
        // SAFETY: the struct size is equeval to the size of an i32.
        // We don't need to do any extra hashing. It may be counterintuitive,
        // but this is also what `int` does: `hash(6) == 6`.
        unsafe { mem::transmute(self) }
    }
}

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub(crate) struct IsoFormat {
    date: Date,
    basic: bool,
}

impl fmt::Chunk for IsoFormat {
    fn len(&self) -> usize {
        if self.basic { 8 } else { 10 }
    }

    fn write(&self, buf: &mut impl fmt::Sink) {
        let Date { year, month, day } = self.date;
        buf.write(fmt::format_4_digits(year.get()).as_ref());
        if self.basic {
            buf.write(fmt::format_2_digits(month.get()).as_ref());
        } else {
            buf.write(b"-");
            buf.write(fmt::format_2_digits(month.get()).as_ref());
            buf.write(b"-");
        }
        buf.write(fmt::format_2_digits(day).as_ref());
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

impl PySimpleAlloc for Date {}

impl Display for Date {
    fn fmt(&self, f: &mut Formatter<'_>) -> std::fmt::Result {
        let mut s = fmt::ArrayWriter::<10>::new();
        let fmt = self.format_iso(false);
        fmt.write(&mut s);
        f.write_str(s.finish())
    }
}

fn __new__(cls: HeapType<Date>, args: PyTuple, kwargs: Option<PyDict>) -> PyReturn {
    if args.len() == 1 && kwargs.map_or(0, |d| d.len()) == 0 {
        let arg = args.iter().next().unwrap();
        // Accept stdlib datetime.date (or datetime.datetime, which is a subclass)
        if let Some(d) = arg.cast_allow_subclass::<PyDate>() {
            return Date::from_py(d).to_obj(cls);
        }
        return parse_iso(cls, arg);
    }
    let mut year: c_long = 0;
    let mut month: c_long = 0;
    let mut day: c_long = 0;
    parse_args_kwargs!(args, kwargs, c"lll:Date", year, month, day);
    Date::from_longs(year, month, day)
        .ok_or_value_err("invalid date value")?
        .to_obj(cls)
}

fn __richcmp__(cls: HeapType<Date>, a: Date, b_obj: PyObj, op: c_int) -> PyReturn {
    match b_obj.extract(cls) {
        Some(b) => match op {
            pyo3_ffi::Py_EQ => a == b,
            pyo3_ffi::Py_NE => a != b,
            pyo3_ffi::Py_LT => a < b,
            pyo3_ffi::Py_LE => a <= b,
            pyo3_ffi::Py_GT => a > b,
            pyo3_ffi::Py_GE => a >= b,
            _ => unreachable!(),
        }
        .to_py(),
        None => not_implemented(),
    }
}

fn __str__(_: PyType, slf: Date) -> PyReturn {
    PyAsciiStrBuilder::format(slf.format_iso(false))
}

fn __repr__(_: PyType, slf: Date) -> PyReturn {
    PyAsciiStrBuilder::format((b"Date(\"", slf.format_iso(false), b"\")"))
}

extern "C" fn __hash__(slf: PyObj) -> Py_hash_t {
    // SAFETY: we know self is passed to this method
    unsafe { slf.assume_heaptype::<Date>() }.1.hash() as Py_hash_t
}

#[allow(static_mut_refs)]
static mut SLOTS: &[PyType_Slot] = &[
    slotmethod!(Date, Py_tp_new, __new__),
    slotmethod!(Date, Py_tp_str, __str__, 1),
    slotmethod!(Date, Py_tp_repr, __repr__, 1),
    slotmethod!(Date, Py_tp_richcompare, __richcmp__),
    slotmethod!(Py_nb_subtract, __sub__, 2),
    slotmethod!(Py_nb_add, __add__, 2),
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

fn to_stdlib(cls: HeapType<Date>, slf: Date) -> PyReturn {
    slf.to_py(cls.state().py_api)
}

fn py_date(cls: HeapType<Date>, slf: Date) -> PyReturn {
    let &State {
        warn_deprecation, ..
    } = cls.state();
    warn_with_class(
        warn_deprecation,
        c"py_date() is deprecated. Use to_stdlib() instead.",
        1,
    )?;
    to_stdlib(cls, slf)
}

fn from_py_date(cls: HeapType<Date>, arg: PyObj) -> PyReturn {
    let &State {
        warn_deprecation, ..
    } = cls.state();
    warn_with_class(
        warn_deprecation,
        c"from_py_date() is deprecated. Use Date() constructor instead.",
        1,
    )?;
    Date::from_py(
        arg.cast_allow_subclass::<PyDate>()
            .ok_or_type_err("argument must be a datetime.date")?,
    )
    .to_obj(cls)
}

fn year_month(cls: HeapType<Date>, Date { year, month, .. }: Date) -> PyReturn {
    let state = cls.state();
    let args = (year.get().to_py()?, month.get().to_py()?).into_pytuple()?;
    state.yearmonth_type.call(args.borrow())
}

fn month_day(cls: HeapType<Date>, Date { month, day, .. }: Date) -> PyReturn {
    let state = cls.state();
    let args = (month.get().to_py()?, day.to_py()?).into_pytuple()?;
    state.monthday_type.call(args.borrow())
}

fn format_iso(cls: HeapType<Date>, slf: Date, args: &[PyObj], kwargs: &mut IterKwargs) -> PyReturn {
    if !args.is_empty() {
        raise_type_err("format_iso() takes no positional arguments")?
    }

    let mut basic = false;
    let str_basic = cls.state().str_basic;

    handle_kwargs("format_iso", kwargs, |key, value, eq| {
        if eq(key, str_basic) {
            if value.is_true() {
                basic = true;
            } else if value.is_false() {
                basic = false;
            } else {
                raise_type_err("basic must be a bool")?
            }
        } else {
            return Ok(false);
        };
        Ok(true)
    })?;

    PyAsciiStrBuilder::format(slf.format_iso(basic))
}

fn parse_iso(cls: HeapType<Date>, s: PyObj) -> PyReturn {
    Date::parse_iso(
        s.cast_allow_subclass::<PyStr>()
            // NOTE: this exception message also needs to make sense when
            // called through the constructor
            .ok_or_type_err("when parsing from ISO format, the argument must be str")?
            .as_utf8()?,
    )
    .ok_or_else_value_err(|| format!("Invalid format: {s}"))?
    .to_obj(cls)
}

fn day_of_week(cls: HeapType<Date>, slf: Date) -> Owned<PyObj> {
    cls.state().weekday_enum_members[(slf.day_of_week() as u8 - 1) as usize].newref()
}

fn iso_week_date(cls: HeapType<Date>, slf: Date) -> PyReturn {
    let state = cls.state();
    let (iso_year, iso_week) = slf.iso_year_week();
    let weekday_idx = slf.day_of_week() as u8 - 1;
    let args = (
        iso_year.to_py()?,
        iso_week.to_py()?,
        state.weekday_enum_members[weekday_idx as usize].newref(),
    )
        .into_pytuple()?;
    state.isoweekdate_new.call(args.borrow())
}

fn day_of_year(_: HeapType<Date>, slf: Date) -> PyReturn {
    (slf.year.days_before_month(slf.month) + slf.day as u16).to_py()
}

fn days_in_month(_: HeapType<Date>, slf: Date) -> PyReturn {
    slf.year.days_in_month(slf.month).to_py()
}

fn days_in_year(_: HeapType<Date>, slf: Date) -> PyReturn {
    (if slf.year.is_leap() { 366_u16 } else { 365_u16 }).to_py()
}

fn in_leap_year(_: HeapType<Date>, slf: Date) -> PyReturn {
    slf.year.is_leap().to_py()
}

fn next_day(cls: HeapType<Date>, slf: Date) -> PyReturn {
    slf.shift(DeltaMonths::ZERO, DeltaDays::new_unchecked(1))
        .ok_or_range_err()?
        .to_obj(cls)
}

fn prev_day(cls: HeapType<Date>, slf: Date) -> PyReturn {
    slf.shift(DeltaMonths::ZERO, DeltaDays::new_unchecked(-1))
        .ok_or_range_err()?
        .to_obj(cls)
}

fn nth_weekday_of_month(cls: HeapType<Date>, slf: Date, args: &[PyObj]) -> PyReturn {
    let &[n_obj, dow_obj] = args else {
        raise_type_err("nth_weekday_of_month() requires exactly 2 positional arguments")?
    };
    let state = cls.state();
    let n = {
        let raw = n_obj
            .cast_exact::<PyInt>()
            .ok_or_type_err("n must be an integer")?
            .to_i64()?;
        if raw == 0 {
            raise_value_err("n must not be 0")?
        } else if !(-5..=5).contains(&raw) {
            raise_value_err("n must be between -5 and 5")?
        }
        // SAFETY: we just checked that it's well within range
        raw as i32
    };

    let target_dow = extract_weekday(state, dow_obj)?;
    Date::nth_weekday_in_month(slf.year, slf.month, n, target_dow)
        .ok_or_value_err(format!(
            "Weekday #{n} doesn't exist in {}-{:02}",
            slf.year.get(),
            slf.month.get()
        ))?
        .to_obj(cls)
}

fn nth_weekday(cls: HeapType<Date>, slf: Date, args: &[PyObj]) -> PyReturn {
    let &[n_obj, dow_obj] = args else {
        raise_type_err("nth_weekday_of_month() requires exactly 2 positional arguments")?
    };
    let state = cls.state();
    let n = {
        let raw = n_obj
            .cast_exact::<PyInt>()
            .ok_or_type_err("n must be an integer")?
            .to_i64()?;
        if raw == 0 {
            raise_value_err("n must not be 0")?
        } else if !(-5..=5).contains(&raw) {
            raise_value_err("n must be between -5 and 5")?
        }
        // SAFETY: we just checked that it's well within range
        raw as i32
    };
    let target_dow = extract_weekday(state, dow_obj)? as i32;
    let self_dow = slf.day_of_week() as i32;

    let days = if n > 0 {
        let mut offset = (target_dow - self_dow).rem_euclid(7);
        if offset == 0 {
            offset = 7;
        }
        offset + (n - 1) * 7
    } else {
        let mut offset = (self_dow - target_dow).rem_euclid(7);
        if offset == 0 {
            offset = 7;
        }
        -(offset + (-n - 1) * 7)
    };

    slf.shift(DeltaMonths::ZERO, DeltaDays::new(days).ok_or_range_err()?)
        .ok_or_range_err()?
        .to_obj(cls)
}

fn start_of(cls: HeapType<Date>, slf: Date, unit_obj: PyObj) -> PyReturn {
    let &State {
        str_year,
        str_month,
        ..
    } = cls.state();
    match_interned_str("unit", unit_obj, |v, eq| {
        if eq(v, str_year) {
            Some(Date {
                year: slf.year,
                month: Month::January,
                day: 1,
            })
        } else if eq(v, str_month) {
            Some(Date {
                year: slf.year,
                month: slf.month,
                day: 1,
            })
        } else {
            None
        }
    })?
    .to_obj(cls)
}

fn end_of(cls: HeapType<Date>, slf: Date, unit_obj: PyObj) -> PyReturn {
    let &State {
        str_year,
        str_month,
        ..
    } = cls.state();
    match_interned_str("unit", unit_obj, |v, eq| {
        if eq(v, str_year) {
            Some(Date {
                year: slf.year,
                month: Month::December,
                day: 31,
            })
        } else if eq(v, str_month) {
            Some(Date {
                year: slf.year,
                month: slf.month,
                day: slf.year.days_in_month(slf.month),
            })
        } else {
            None
        }
    })?
    .to_obj(cls)
}

/// Extract a Weekday enum value from a Python argument
fn extract_weekday(state: &State, arg: PyObj) -> PyResult<Weekday> {
    state
        .weekday_enum_members
        .iter()
        .position(|m| *m == arg)
        .map(|i| Weekday::from_iso_unchecked(i as u8 + 1))
        .ok_or_type_err("weekday must be a Weekday enum member")
}

fn __reduce__(cls: HeapType<Date>, Date { year, month, day }: Date) -> PyResult<Owned<PyTuple>> {
    let data = pack![year.get(), month.get(), day];
    (
        cls.state().unpickle_date.newref(),
        (data.to_py()?,).into_pytuple()?,
    )
        .into_pytuple()
}

fn __sub__(obj_a: PyObj, obj_b: PyObj) -> PyReturn {
    let type_a = obj_a.type_();
    let type_b = obj_b.type_();

    // Easy case: Date - Date
    if type_b == type_a {
        // SAFETY: the only way to get here is if *both* are Date
        let (date_type, a) = unsafe { obj_a.assume_heaptype::<Date>() };
        let (_, b) = unsafe { obj_b.assume_heaptype::<Date>() };
        warn_with_class(
            date_type.state().warn_deprecation,
            c"Using the `-` operator on Date is deprecated; use the .since() method with explicit units instead.",
            1,
        )?;

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
        .to_obj(date_type.state().date_delta_type)
    // Case: types within whenever module.
    } else if let Some(state) = type_a.same_module(type_b) {
        warn_with_class(
            state.warn_deprecation,
            c"Using the `-` operator on Date is deprecated; use the .subtract() method instead.",
            1,
        )?;
        // SAFETY: the way we've structured binary operations within whenever
        // ensures that the first operand is the self type.
        let (date_type, date) = unsafe { obj_a.assume_heaptype::<Date>() };
        let DateDelta { months, days } =
            obj_b
                .extract(state.date_delta_type)
                .ok_or_else_type_err(|| {
                    format!("unsupported operand type(s) for -: 'Date' and '{type_b}'")
                })?;
        date.shift_months(-months)
            .and_then(|date| date.shift_days(-days))
            .ok_or_range_err()?
            .to_obj(date_type)
    // Case: other types
    } else {
        not_implemented()
    }
}

fn __add__(obj_a: PyObj, obj_b: PyObj) -> PyReturn {
    // We need to be careful since this method can be called reflexively
    let type_a = obj_a.type_();
    let type_b = obj_b.type_();
    if let Some(state) = type_a.same_module(type_b) {
        warn_with_class(
            state.warn_deprecation,
            c"Using the + operator on Date is deprecated; use the .add() method instead.",
            1,
        )?;
        // SAFETY: the way we've structured binary operations within whenever
        // ensures that the first operand is the self type.
        let (date_type, date) = unsafe { obj_a.assume_heaptype::<Date>() };
        let DateDelta { months, days } =
            obj_b
                .extract(state.date_delta_type)
                .ok_or_else_type_err(|| {
                    format!("unsupported operand type(s) for +: 'Date' and '{type_b}'")
                })?;
        // SAFETY: at least one of the operands must be a Date
        date.shift_months(months)
            .and_then(|date| date.shift_days(days))
            .ok_or_range_err()?
            .to_obj(date_type)
    } else {
        not_implemented()
    }
}

fn add(cls: HeapType<Date>, slf: Date, args: &[PyObj], kwargs: &mut IterKwargs) -> PyReturn {
    shift_method(cls, slf, args, kwargs, false)
}

fn subtract(cls: HeapType<Date>, slf: Date, args: &[PyObj], kwargs: &mut IterKwargs) -> PyReturn {
    shift_method(cls, slf, args, kwargs, true)
}

#[inline(never)]
fn shift_method(
    cls: HeapType<Date>,
    slf: Date,
    args: &[PyObj],
    kwargs: &mut IterKwargs,
    negate: bool,
) -> PyReturn {
    let fname = if negate { "subtract" } else { "add" };
    let state = cls.state();
    let (mut months, mut days) = match (args, kwargs.len()) {
        (&[arg], 0) => {
            if let Some(d) = arg.extract(state.date_delta_type) {
                (d.months, d.days)
            } else if let Some(d) = arg.extract(state.itemized_date_delta_type) {
                d.to_months_days().ok_or_range_err()?
            } else {
                raise_type_err(format!(
                    "{fname}() argument must be a DateDelta or ItemizedDateDelta"
                ))?
            }
        }
        ([], _) => {
            let &State {
                str_days,
                str_months,
                str_years,
                str_weeks,
                ..
            } = state;
            handle_datedelta_kwargs(fname, kwargs, str_years, str_months, str_days, str_weeks)?
        }
        _ => raise_type_err(format!(
            "{fname}() takes either only kwargs or 1 positional arg"
        ))?,
    };
    if negate {
        days = -days;
        months = -months;
    }

    slf.shift(months, days).ok_or_range_err()?.to_obj(cls)
}

fn since(cls: HeapType<Date>, slf: Date, args: &[PyObj], kwargs: &mut IterKwargs) -> PyReturn {
    since_inner(cls, slf, args, kwargs, "since", false)
}

fn until(cls: HeapType<Date>, slf: Date, args: &[PyObj], kwargs: &mut IterKwargs) -> PyReturn {
    since_inner(cls, slf, args, kwargs, "until", true)
}

#[inline(never)]
fn since_inner(
    cls: HeapType<Date>,
    slf: Date,
    args: &[PyObj],
    kwargs: &mut IterKwargs,
    fname: &str,
    negate: bool,
) -> PyReturn {
    let state = cls.state();
    let &State {
        str_total,
        str_in_units,
        str_round_mode,
        str_round_increment,
        round_mode_strs,
        ..
    } = state;

    let other = handle_one_arg(fname, args)?
        .extract(cls)
        .ok_or_type_err("argument must be a Date")?;

    let mut units: Option<math::DateSinceUnits> = None;
    let mut round_mode = None;
    let mut round_increment = math::DateRoundIncrement::MIN;
    let mut round_was_set = false;
    handle_kwargs(fname, kwargs, |key, value, eq| {
        if eq(key, str_total) {
            if units.is_some() {
                return raise_type_err("cannot specify both 'total' and 'in_units'");
            }
            units = Some(DateSinceUnits::Total(CalUnit::from_py(value, state)?));
        } else if eq(key, str_in_units) {
            if units.is_some() {
                return raise_type_err("cannot specify both 'total' and 'in_units'");
            }
            units = Some(DateSinceUnits::InUnits(CalUnitSet::from_py(value, state)?));
        } else if eq(key, str_round_mode) {
            round_mode = round::Mode::from_py_named("round_mode", value, round_mode_strs)?.into();
            round_was_set = true;
        } else if eq(key, str_round_increment) {
            round_increment = DateRoundIncrement::from_py(value)?;
            round_was_set = true;
        } else {
            return Ok(false);
        }
        Ok(true)
    })?;

    let (a, b) = if negate { (other, slf) } else { (slf, other) };
    match units {
        Some(DateSinceUnits::Total(unit)) => {
            if round_was_set {
                raise_type_err("'round_mode' and 'round_increment' cannot be used with 'total'")
            } else {
                date_since_float(a, b, unit)
            }
        }
        Some(DateSinceUnits::InUnits(units)) => date_since_iddelta(
            a,
            b,
            units,
            round_mode.unwrap_or(round::Mode::Trunc),
            round_increment,
        )
        .unwrap()
        .to_obj(cls.state().itemized_date_delta_type),
        None => raise_type_err("must specify either 'total' or 'in_units'"),
    }
}

pub(crate) fn date_since_iddelta(
    a: Date,
    b: Date,
    units: CalUnitSet,
    round_mode: round::Mode,
    round_increment: DateRoundIncrement,
) -> PyResult<ItemizedDateDelta> {
    let neg = a < b;
    let (mut result, trunc, expand) =
        math::date_diff(a, b, round_increment, units, neg).ok_or_range_err()?;

    result.round_by_days(
        units.smallest(),
        a,
        trunc.into(),
        expand.into(),
        round_mode.to_abs_trunc(neg),
        round_increment,
        neg,
    );
    Ok(result)
}

fn date_since_float(a: Date, b: Date, unit: CalUnit) -> PyReturn {
    let neg = a < b;
    let (result, trunc_raw, expand_raw) =
        math::date_diff_single_unit(a, b, DateRoundIncrement::MIN, unit, neg).ok_or_range_err()?;
    let trunc: Date = trunc_raw.into();
    let expand: Date = expand_raw.into();
    // result is signed; use its absolute value and restore sign at the end.
    // num/denom ratio is always positive (same sign, since expand and a are both
    // on the same side of trunc relative to b).
    let num = a.unix_days().diff(trunc.unix_days()).get() as f64;
    let denom = expand.unix_days().diff(trunc.unix_days()).get() as f64;
    ((result.abs() as f64 + num / denom).negate_if(neg)).to_py()
}

fn days_since(cls: HeapType<Date>, slf: Date, other: PyObj) -> PyReturn {
    warn_with_class(
        cls.state().warn_deprecation,
        c"days_since() is deprecated; use since() with total='days' instead.",
        1,
    )?;
    slf.unix_days()
        .diff(
            other
                .extract(cls)
                .ok_or_type_err("argument must be a whenever.Date")?
                .unix_days(),
        )
        .get()
        .to_py()
}

fn days_until(cls: HeapType<Date>, slf: Date, other: PyObj) -> PyReturn {
    warn_with_class(
        cls.state().warn_deprecation,
        c"days_until() is deprecated; use until() with total='days' instead.",
        1,
    )?;
    other
        .extract(cls)
        .ok_or_type_err("argument must be a whenever.Date")?
        .unix_days()
        .diff(slf.unix_days())
        .get()
        .to_py()
}

fn replace(cls: HeapType<Date>, slf: Date, args: &[PyObj], kwargs: &mut IterKwargs) -> PyReturn {
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
    handle_kwargs("replace", kwargs, |key, value, eq| {
        if eq(key, str_year) {
            year = value
                .cast_allow_subclass::<PyInt>()
                .ok_or_type_err("year must be an integer")?
                .to_long()?;
        } else if eq(key, str_month) {
            month = value
                .cast_allow_subclass::<PyInt>()
                .ok_or_type_err("month must be an integer")?
                .to_long()?;
        } else if eq(key, str_day) {
            day = value
                .cast_allow_subclass::<PyInt>()
                .ok_or_type_err("day must be an integer")?
                .to_long()?;
        } else {
            return Ok(false);
        }
        Ok(true)
    })?;
    Date::from_longs(year, month, day)
        .ok_or_value_err("invalid date components")?
        .to_obj(cls)
}

fn at(cls: HeapType<Date>, date: Date, time_obj: PyObj) -> PyReturn {
    let &State {
        time_type,
        plain_datetime_type,
        ..
    } = cls.state();
    let time = time_obj
        .extract(time_type)
        .ok_or_type_err("argument must be a whenever.Time")?;
    DateTime { date, time }.to_obj(plain_datetime_type)
}

fn today_in_system_tz(cls: HeapType<Date>) -> PyReturn {
    let state = cls.state();
    let epoch = state.time_ns()?.epoch;
    Date::from_py(system_tz_today_from_timestamp(state.py_api, epoch)?.borrow()).to_obj(cls)
}

fn system_tz_today_from_timestamp(
    &PyDateTime_CAPI {
        Date_FromTimestamp,
        DateType,
        ..
    }: &PyDateTime_CAPI,
    s: EpochSecs,
) -> PyResult<Owned<PyDate>> {
    let timestamp_obj = s.get().to_py()?;
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

fn format(_: HeapType<Date>, slf: Date, pattern_obj: PyObj) -> PyReturn {
    let pattern_pystr = pattern_obj
        .cast_exact::<PyStr>()
        .ok_or_type_err("format() argument must be str")?;
    let pattern_str = pattern_pystr.as_utf8()?;
    let elements = pattern::compile(pattern_str).into_value_err()?;
    pattern::validate_fields(&elements, pattern::CategorySet::DATE, "Date")?;
    if pattern::has_12h_without_ampm(&elements) {
        warn_with_class(
            // SAFETY: PyExc_UserWarning is always valid
            unsafe { PyObj::from_ptr_unchecked(PyExc_UserWarning) },
            c"12-hour format (ii) without AM/PM designator (a/aa) may be ambiguous",
            1,
        )?;
    }
    let vals = pattern::FormatValues {
        year: slf.year,
        month: slf.month,
        day: slf.day,
        weekday: slf.day_of_week(),
        hour: 0,
        minute: 0,
        second: 0,
        nanos: SubSecNanos::MIN,
        offset_secs: None,
        tz_id: None,
        tz_abbrev: None,
    };
    pattern::format_to_py(&elements, &vals)
}

fn __format__(cls: HeapType<Date>, slf: Date, spec_obj: PyObj) -> PyReturn {
    if spec_obj.is_truthy() {
        format(cls, slf, spec_obj)
    } else {
        __str__(cls.into(), slf)
    }
}

fn parse(cls: HeapType<Date>, args: &[PyObj], kwargs: &mut IterKwargs) -> PyReturn {
    let &[s_obj] = args else {
        raise_type_err(format!(
            "parse() takes exactly 1 positional argument ({} given)",
            args.len()
        ))?
    };
    let s_pystr = s_obj
        .cast_exact::<PyStr>()
        .ok_or_type_err("parse() argument must be str")?;
    let s = s_pystr.as_utf8()?;

    let fmt_obj = handle_one_kwarg("parse", cls.state().str_format, kwargs)?.ok_or_else(|| {
        raise_type_err::<(), _>("parse() requires 'format' keyword argument").unwrap_err()
    })?;
    let fmt_pystr = fmt_obj
        .cast_exact::<PyStr>()
        .ok_or_type_err("format must be str")?;
    let fmt_bytes = fmt_pystr.as_utf8()?;

    let elements = pattern::compile(fmt_bytes).into_value_err()?;
    pattern::validate_fields(&elements, pattern::CategorySet::DATE, "Date")?;

    let state = pattern::parse_to_state(&elements, s).into_value_err()?;

    let year = state.year.ok_or_value_err(
        "Pattern must include year (YYYY/YY), month (MM/MMM/MMMM), and day (DD) fields",
    )?;
    let month = state.month.ok_or_value_err(
        "Pattern must include year (YYYY/YY), month (MM/MMM/MMMM), and day (DD) fields",
    )?;
    let day = state.day.ok_or_value_err(
        "Pattern must include year (YYYY/YY), month (MM/MMM/MMMM), and day (DD) fields",
    )?;

    let date = Date::new(year, month, day).ok_or_value_err("Invalid date")?;

    if let Some(wd) = state.weekday
        && date.day_of_week() != wd
    {
        raise_value_err("Parsed weekday does not match the date")?;
    }

    date.to_obj(cls)
}

static mut METHODS: &mut [PyMethodDef] = &mut [
    method0!(Date, to_stdlib, doc::DATE_TO_STDLIB),
    method0!(Date, py_date, doc::DATE_PY_DATE),
    method_kwargs!(Date, format_iso, doc::DATE_FORMAT_ISO),
    classmethod0!(Date, today_in_system_tz, doc::DATE_TODAY_IN_SYSTEM_TZ),
    classmethod1!(Date, parse_iso, doc::DATE_PARSE_ISO),
    classmethod1!(Date, from_py_date, doc::DATE_FROM_PY_DATE),
    method0!(Date, __copy__, c""),
    method1!(Date, __deepcopy__, c""),
    method0!(Date, year_month, doc::DATE_YEAR_MONTH),
    method0!(Date, month_day, doc::DATE_MONTH_DAY),
    method1!(Date, at, doc::DATE_AT),
    method0!(Date, day_of_week, doc::DATE_DAY_OF_WEEK),
    method0!(Date, iso_week_date, doc::DATE_ISO_WEEK_DATE),
    method0!(Date, day_of_year, doc::DATE_DAY_OF_YEAR),
    method0!(Date, days_in_month, doc::DATE_DAYS_IN_MONTH),
    method0!(Date, days_in_year, doc::DATE_DAYS_IN_YEAR),
    method0!(Date, in_leap_year, doc::DATE_IN_LEAP_YEAR),
    method0!(Date, next_day, doc::DATE_NEXT_DAY),
    method0!(Date, prev_day, doc::DATE_PREV_DAY),
    method_vararg!(Date, nth_weekday_of_month, doc::DATE_NTH_WEEKDAY_OF_MONTH),
    method_vararg!(Date, nth_weekday, doc::DATE_NTH_WEEKDAY),
    method1!(Date, start_of, doc::DATE_START_OF),
    method1!(Date, end_of, doc::DATE_END_OF),
    method0!(Date, __reduce__, c""),
    method_kwargs!(Date, add, doc::DATE_ADD),
    method_kwargs!(Date, subtract, doc::DATE_SUBTRACT),
    method1!(Date, days_since, doc::DATE_DAYS_SINCE),
    method1!(Date, days_until, doc::DATE_DAYS_UNTIL),
    method_kwargs!(Date, since, doc::DATE_SINCE),
    method_kwargs!(Date, until, doc::DATE_UNTIL),
    method_kwargs!(Date, replace, doc::DATE_REPLACE),
    method1!(Date, format, doc::DATE_FORMAT),
    method1!(Date, __format__, c""),
    classmethod_kwargs!(Date, parse, doc::DATE_PARSE),
    classmethod_kwargs!(Date, __get_pydantic_core_schema__, doc::PYDANTIC_SCHEMA),
    PyMethodDef::zeroed(),
];

pub(crate) fn unpickle(state: &State, arg: PyObj) -> PyReturn {
    let binding = arg
        .cast_exact::<PyBytes>()
        .ok_or_type_err("invalid pickle data")?;
    let mut packed = binding.as_bytes()?;
    if packed.len() != 4 {
        raise_value_err("invalid pickle data")?
    }
    Date {
        year: Year::new_unchecked(unpack_one!(packed, u16)),
        month: Month::new_unchecked(unpack_one!(packed, u8)),
        day: unpack_one!(packed, u8),
    }
    .to_obj(state.date_type)
}

fn year(_: PyType, slf: Date) -> PyReturn {
    slf.year.get().to_py()
}

fn month(_: PyType, slf: Date) -> PyReturn {
    slf.month.get().to_py()
}

fn day(_: PyType, slf: Date) -> PyReturn {
    slf.day.to_py()
}

static mut GETSETTERS: &mut [PyGetSetDef] = &mut [
    getter!(Date, year, doc::DATE_YEAR),
    getter!(Date, month, doc::DATE_MONTH),
    getter!(Date, day, doc::DATE_DAY),
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
