use core::{
    ffi::{CStr, c_int, c_long, c_void},
    mem,
    ptr::null_mut as NULL,
};
use pyo3_ffi::*;

pub use crate::domain::date::Date;
pub(crate) use crate::domain::date::DateBoundaryUnit;

use crate::{
    classes::{
        date_delta::DateDelta, itemized_date_delta::ItemizedDateDelta,
        plain_datetime::PlainDateTime,
    },
    common::{
        math::{self, CalendarIncrement, CalendarUnit, CalendarUnitSet, DateDifferenceUnits},
        pattern, pickle, round,
        scalar::*,
        shift::{parse_calendar_shift_arg, parse_calendar_shift_kwargs},
    },
    docstrings as doc,
    py::*,
    pymodule::State,
};

pub(crate) const SINGLETONS: &[(&CStr, Date); 2] = &[(c"MIN", Date::MIN), (c"MAX", Date::MAX)];

impl Date {
    pub(crate) fn from_longs(y: c_long, m: c_long, day: c_long) -> Option<Self> {
        let year = Year::from_long(y)?;
        let month = Month::from_long(m)?;
        (day >= 1 && day <= year.days_in_month(month) as _).then_some(Date {
            year,
            month,
            day: day as _,
        })
    }

    pub(crate) fn to_stdlib_date(
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
        .own()
    }

    pub(crate) fn from_stdlib_date(d: PyDate) -> Self {
        Date {
            // SAFETY: stdlib dates always have years in 1..=9999.
            year: unsafe { Year::new_unchecked(d.year() as _) },
            // SAFETY: stdlib dates always have months in 1..=12.
            month: unsafe { Month::new_unchecked(d.month() as _) },
            day: d.day() as _,
        }
    }

    pub(crate) const fn hash(self) -> i32 {
        // SAFETY: Date has the same size as i32, and Python uses its packed value as the hash.
        unsafe { mem::transmute(self) }
    }
}

impl DateBoundaryUnit {
    pub(crate) fn from_py(state: &State, obj: PyObj) -> PyResult<Self> {
        find_interned(obj, |v, eq| {
            if eq(v, *state.str_year) {
                Some(Ok(DateBoundaryUnit::Year))
            } else if eq(v, *state.str_month) {
                Some(Ok(DateBoundaryUnit::Month))
            } else if eq(v, *state.str_week_mon) {
                Some(Ok(DateBoundaryUnit::WeekMon))
            } else if eq(v, *state.str_week_sun) {
                Some(Ok(DateBoundaryUnit::WeekSun))
            } else if eq(v, *state.str_week) {
                Some(raise_value_err(
                    "unit 'week' is ambiguous. Use 'week_mon' or 'week_sun' instead.",
                ))
            } else {
                None
            }
        })
        .transpose()?
        .ok_or_else_value_err(|| format!("Invalid unit: {obj}"))
    }
}

impl PyPayload for Date {}

fn __new__(cls: PyClass<Date>, args: PyTuple, kwargs: Option<PyDict>) -> PyReturn {
    if args.len() == 1 && kwargs.map_or(0, |d| d.len()) == 0 {
        let arg = args.iter().next().unwrap();
        if PyStr::isinstance(arg) {
            return parse_iso(cls, arg);
        }
        // Accept stdlib datetime.date (or datetime.datetime, which is a subclass)
        if let Some(d) = arg.cast_allow_subclass::<PyDate>() {
            return Date::from_stdlib_date(d).to_obj(cls);
        }
        return raise_type_err("Date() requires an ISO 8601 string or datetime.date");
    }
    let mut year: c_long = 0;
    let mut month: c_long = 0;
    let mut day: c_long = 0;
    parse_args_kwargs!(args, kwargs, c"lll:Date", year, month, day);
    Date::from_longs(year, month, day)
        .ok_or_value_err("invalid date value")?
        .to_obj(cls)
}

fn __richcmp__(cls: PyClass<Date>, a: Date, b_obj: PyObj, op: c_int) -> PyReturn {
    match b_obj.extract(cls) {
        Some(b) => CompareOp::from_ffi(op).apply(a, b).to_py(),
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

fn to_stdlib(cls: PyClass<Date>, slf: Date) -> PyReturn {
    slf.to_stdlib_date(cls.state().py_api()?)
}

fn py_date(cls: PyClass<Date>, slf: Date) -> PyReturn {
    warn_with_class(
        *cls.state().warn_deprecation,
        c"py_date() is deprecated. Use to_stdlib() instead.",
        1,
    )?;
    to_stdlib(cls, slf)
}

fn from_py_date(cls: PyClass<Date>, arg: PyObj) -> PyReturn {
    warn_with_class(
        *cls.state().warn_deprecation,
        c"from_py_date() is deprecated. Use Date() constructor instead.",
        1,
    )?;
    Date::from_stdlib_date(
        arg.cast_allow_subclass::<PyDate>()
            .ok_or_type_err("argument must be a datetime.date")?,
    )
    .to_obj(cls)
}

fn year_month(cls: PyClass<Date>, Date { year, month, .. }: Date) -> PyReturn {
    cls.state()
        .yearmonth_type
        .get()?
        .call_args([*year.get().to_py()?, *month.get().to_py()?])
}

fn month_day(cls: PyClass<Date>, Date { month, day, .. }: Date) -> PyReturn {
    cls.state()
        .monthday_type
        .get()?
        .call_args([*month.get().to_py()?, *day.to_py()?])
}

fn format_iso(cls: PyClass<Date>, slf: Date, args: &[PyObj], kwargs: &mut IterKwargs) -> PyReturn {
    if !args.is_empty() {
        raise_type_err("format_iso() takes no positional arguments")?
    }
    let mut basic = false;
    let state = cls.state();

    handle_kwargs("format_iso", kwargs, |key, value, eq| {
        if eq(key, *state.str_basic) {
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

fn parse_iso(cls: PyClass<Date>, s: PyObj) -> PyReturn {
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

fn day_of_week(cls: PyClass<Date>, slf: Date) -> PyReturn {
    let members = cls.state().weekday_enum_members.get()?;
    Ok(members[(slf.day_of_week() as u8 - 1) as usize].newref())
}

fn iso_week_date(cls: PyClass<Date>, slf: Date) -> PyReturn {
    let state = cls.state();
    let (iso_year, iso_week) = slf.iso_year_week();
    let weekday_idx = slf.day_of_week() as u8 - 1;
    state.isoweekdate_new.get()?.call_args([
        *iso_year.to_py()?,
        *iso_week.to_py()?,
        *state.weekday_enum_members.get()?[weekday_idx as usize],
    ])
}

fn day_of_year(_: PyClass<Date>, slf: Date) -> PyReturn {
    (slf.year.days_before_month(slf.month) + slf.day as u16).to_py()
}

fn days_in_month(_: PyClass<Date>, slf: Date) -> PyReturn {
    slf.year.days_in_month(slf.month).to_py()
}

fn days_in_year(_: PyClass<Date>, slf: Date) -> PyReturn {
    (if slf.year.is_leap() { 366_u16 } else { 365_u16 }).to_py()
}

fn in_leap_year(_: PyClass<Date>, slf: Date) -> PyReturn {
    slf.year.is_leap().to_py()
}

fn next_day(cls: PyClass<Date>, slf: Date) -> PyReturn {
    slf.shift(DeltaMonths::ZERO, DeltaDays::new_unchecked(1))
        .ok_or_range_err()?
        .to_obj(cls)
}

fn prev_day(cls: PyClass<Date>, slf: Date) -> PyReturn {
    slf.shift(DeltaMonths::ZERO, DeltaDays::new_unchecked(-1))
        .ok_or_range_err()?
        .to_obj(cls)
}

fn nth_weekday_of_month(cls: PyClass<Date>, slf: Date, args: &[PyObj]) -> PyReturn {
    let &[n_obj, dow_obj] = args else {
        raise_type_err("nth_weekday_of_month() requires exactly 2 positional arguments")?
    };
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

    let target_dow = extract_weekday(cls.state(), dow_obj)?;
    Date::nth_weekday_in_month(slf.year, slf.month, n, target_dow)
        .ok_or_value_err(format!(
            "Weekday #{n} doesn't exist in {}-{:02}",
            slf.year.get(),
            slf.month.get()
        ))?
        .to_obj(cls)
}

fn nth_weekday(cls: PyClass<Date>, slf: Date, args: &[PyObj]) -> PyReturn {
    let &[n_obj, dow_obj] = args else {
        raise_type_err("nth_weekday() requires exactly 2 positional arguments")?
    };
    let n = {
        let raw = n_obj
            .cast_exact::<PyInt>()
            .ok_or_type_err("n must be an integer")?
            .to_i64()?;
        if raw == 0 {
            raise_value_err("n must not be 0")?
        } else if !(-521_722..=521_722).contains(&raw) {
            raise_value_err("n out of range")?
        }
        // SAFETY: we just checked that it's well within range
        raw as i32
    };
    let target_dow = extract_weekday(cls.state(), dow_obj)? as i32;
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

fn start_of(cls: PyClass<Date>, slf: Date, unit_obj: PyObj) -> PyReturn {
    let unit = DateBoundaryUnit::from_py(cls.state(), unit_obj)?;
    slf.start_of(unit).ok_or_range_err()?.to_obj(cls)
}

fn end_of(cls: PyClass<Date>, slf: Date, unit_obj: PyObj) -> PyReturn {
    let unit = DateBoundaryUnit::from_py(cls.state(), unit_obj)?;
    slf.end_of(unit).ok_or_range_err()?.to_obj(cls)
}

/// Extract a Weekday enum value from a Python argument
fn extract_weekday(state: &State, arg: PyObj) -> PyResult<Weekday> {
    state
        .weekday_enum_members
        .get()?
        .iter()
        .position(|m| m.eq(&arg))
        // SAFETY: weekday_enum_members contains exactly seven entries.
        .map(|i| unsafe { Weekday::from_iso_unchecked(i as u8 + 1) })
        .ok_or_type_err("weekday must be a Weekday enum member")
}

fn __reduce__(cls: PyClass<Date>, slf: Date) -> PyReturn {
    let data = pickle::encode_date(slf);
    [
        cls.state().unpickle_date.newref(),
        [data.to_py()?].into_pytuple()?,
    ]
    .into_pytuple()
}

fn __sub__(obj_a: PyObj, obj_b: PyObj) -> PyReturn {
    binary_operation::<Date>(obj_a, obj_b, "-", |operands| match operands {
        BinaryCall::SameType { cls, slf, other } => {
            warn_with_class(
                *cls.state().warn_deprecation,
                c"Using the `-` operator on Date is deprecated; use the .since() method with explicit units instead.",
                1,
            )?;

            let mut days = slf.day as i32;
            let mut months = DeltaMonths::new_unchecked(
                slf.month as i32 - other.month as i32
                    + 12 * (slf.year.get() as i32 - other.year.get() as i32),
            );
            let mut moved_other = other.shift_months(months).unwrap();
            if *other > *slf && moved_other < *slf {
                months = DeltaMonths::new_unchecked(months.get() + 1);
                moved_other = other.shift_months(months).unwrap();
                days -= slf.year.days_in_month(slf.month) as i32;
            } else if *other < *slf && moved_other > *slf {
                months = DeltaMonths::new_unchecked(months.get() - 1);
                moved_other = other.shift_months(months).unwrap();
                days += moved_other.year.days_in_month(moved_other.month) as i32;
            };
            Ok(Some(
                DateDelta {
                    months,
                    days: DeltaDays::new_unchecked(days - moved_other.day as i32),
                }
                .to_obj(*cls.state().date_delta_type)?,
            ))
        }
        BinaryCall::ExtTypes { cls, slf, other } => {
            let state = cls.state();
            let Some(d) = other.extract(*state.date_delta_type) else {
                return Ok(None);
            };
            warn_with_class(
                *state.warn_deprecation,
                c"Using the `-` operator on Date is deprecated; use the .subtract() method instead.",
                1,
            )?;
            Ok(Some(
                slf.shift_months(-d.months)
                    .and_then(|date| date.shift_days(-d.days))
                    .ok_or_range_err()?
                    .to_obj(cls)?,
            ))
        }
        BinaryCall::OtherTypes => Ok(None),
    })
}

fn __add__(obj_a: PyObj, obj_b: PyObj) -> PyReturn {
    binary_operation::<Date>(obj_a, obj_b, "+", |operands| {
        let BinaryCall::ExtTypes { cls, slf, other } = operands else {
            return Ok(None);
        };
        let state = cls.state();
        let Some(d) = other.extract(*state.date_delta_type) else {
            return Ok(None);
        };
        warn_with_class(
            *state.warn_deprecation,
            c"Using the + operator on Date is deprecated; use the .add() method instead.",
            1,
        )?;
        Ok(Some(
            slf.shift_months(d.months)
                .and_then(|date| date.shift_days(d.days))
                .ok_or_range_err()?
                .to_obj(cls)?,
        ))
    })
}

fn add(cls: PyClass<Date>, slf: Date, args: &[PyObj], kwargs: &mut IterKwargs) -> PyReturn {
    shift_method(cls, slf, args, kwargs, false)
}

fn subtract(cls: PyClass<Date>, slf: Date, args: &[PyObj], kwargs: &mut IterKwargs) -> PyReturn {
    shift_method(cls, slf, args, kwargs, true)
}

#[inline(never)]
fn shift_method(
    cls: PyClass<Date>,
    slf: Date,
    args: &[PyObj],
    kwargs: &mut IterKwargs,
    negate: bool,
) -> PyReturn {
    let fname = if negate { "subtract" } else { "add" };
    let state = cls.state();
    let shift = match (args, kwargs.len()) {
        (&[arg], 0) => parse_calendar_shift_arg(fname, arg, state)?,
        ([], _) => parse_calendar_shift_kwargs(fname, kwargs, state)?,
        _ => raise_type_err(format!(
            "{fname}() takes either only kwargs or 1 positional arg"
        ))?,
    };

    slf.shift_by(shift.negate_if(negate))
        .ok_or_range_err()?
        .to_obj(cls)
}

fn since(cls: PyClass<Date>, slf: Date, args: &[PyObj], kwargs: &mut IterKwargs) -> PyReturn {
    since_inner(cls, slf, args, kwargs, "since", false)
}

fn until(cls: PyClass<Date>, slf: Date, args: &[PyObj], kwargs: &mut IterKwargs) -> PyReturn {
    since_inner(cls, slf, args, kwargs, "until", true)
}

#[inline(never)]
fn since_inner(
    cls: PyClass<Date>,
    slf: Date,
    args: &[PyObj],
    kwargs: &mut IterKwargs,
    fname: &str,
    negate: bool,
) -> PyReturn {
    let state = cls.state();

    let other = handle_one_arg(fname, args)?
        .extract(cls)
        .ok_or_type_err("argument must be a Date")?;

    let mut units: Option<math::DateDifferenceUnits> = None;
    let mut round_mode = None;
    let mut round_increment = math::CalendarIncrement::MIN;
    let mut round_was_set = false;
    handle_kwargs(fname, kwargs, |key, value, eq| {
        if eq(key, *state.str_total) {
            if units.is_some() {
                return raise_type_err("cannot specify both 'total' and 'in_units'");
            }
            units = Some(DateDifferenceUnits::Total(CalendarUnit::from_py(
                value, state,
            )?));
        } else if eq(key, *state.str_in_units) {
            if units.is_some() {
                return raise_type_err("cannot specify both 'total' and 'in_units'");
            }
            units = Some(DateDifferenceUnits::InUnits(CalendarUnitSet::from_py(
                value, state,
            )?));
        } else if eq(key, *state.str_round_mode) {
            round_mode =
                round::Mode::from_py_named("round_mode", value, &state.round_mode_strs)?.into();
            round_was_set = true;
        } else if eq(key, *state.str_round_increment) {
            round_increment = CalendarIncrement::from_py(value)?;
            round_was_set = true;
        } else {
            return Ok(false);
        }
        Ok(true)
    })?;

    let (a, b) = if negate { (other, slf) } else { (slf, other) };
    match units {
        Some(DateDifferenceUnits::Total(unit)) => {
            if round_was_set {
                raise_type_err("'round_mode' and 'round_increment' cannot be used with 'total'")
            } else {
                date_since_float(a, b, unit)
            }
        }
        Some(DateDifferenceUnits::InUnits(units)) => {
            let d = date_since_iddelta(
                a,
                b,
                units,
                round_mode.unwrap_or(round::Mode::Trunc),
                round_increment,
            )?;
            d.to_obj(cls.state())
        }
        None => raise_type_err("must specify either 'total' or 'in_units'"),
    }
}

pub(crate) fn date_since_iddelta(
    a: Date,
    b: Date,
    units: CalendarUnitSet,
    round_mode: round::Mode,
    round_increment: CalendarIncrement,
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

fn date_since_float(a: Date, b: Date, unit: CalendarUnit) -> PyReturn {
    let neg = a < b;
    let (result, trunc_raw, expand_raw) =
        math::date_diff_single_unit(a, b, CalendarIncrement::MIN, unit, neg).ok_or_range_err()?;
    let trunc: Date = trunc_raw.into();
    let expand: Date = expand_raw.into();
    // result is signed; use its absolute value and restore sign at the end.
    // num/denom ratio is always positive (same sign, since expand and a are both
    // on the same side of trunc relative to b).
    let num = a.unix_days().diff(trunc.unix_days()).get() as f64;
    let denom = expand.unix_days().diff(trunc.unix_days()).get() as f64;
    ((result.abs() as f64 + num / denom).negate_if(neg)).to_py()
}

fn days_since(cls: PyClass<Date>, slf: Date, other: PyObj) -> PyReturn {
    warn_with_class(
        *cls.state().warn_deprecation,
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

fn days_until(cls: PyClass<Date>, slf: Date, other: PyObj) -> PyReturn {
    warn_with_class(
        *cls.state().warn_deprecation,
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

fn replace(cls: PyClass<Date>, slf: Date, args: &[PyObj], kwargs: &mut IterKwargs) -> PyReturn {
    if !args.is_empty() {
        raise_type_err("replace() takes no positional arguments")?
    }

    let state = cls.state();
    let mut year = slf.year.get().into();
    let mut month = slf.month.get().into();
    let mut day = slf.day.into();
    handle_kwargs("replace", kwargs, |k, v, eq| {
        if eq(k, *state.str_year) {
            year = v.expect_int("year")?.to_long()?;
        } else if eq(k, *state.str_month) {
            month = v.expect_int("month")?.to_long()?;
        } else if eq(k, *state.str_day) {
            day = v.expect_int("day")?.to_long()?;
        } else {
            return Ok(false);
        }
        Ok(true)
    })?;
    Date::from_longs(year, month, day)
        .ok_or_value_err("invalid date components")?
        .to_obj(cls)
}

fn at(cls: PyClass<Date>, date: Date, time_obj: PyObj) -> PyReturn {
    let state = cls.state();
    let time = time_obj
        .extract(*state.time_type)
        .ok_or_type_err("argument must be a whenever.Time")?;
    PlainDateTime { date, time }.to_obj(*state.plain_datetime_type)
}

fn today_in_system_tz(cls: PyClass<Date>) -> PyReturn {
    let state = cls.state();
    let tz = state.tz_store.get_system_tz()?;
    state
        .now()?
        .to_offset_in(&tz)
        .ok_or_range_err()?
        .date
        .to_obj(cls)
}

fn format(_: PyClass<Date>, slf: Date, pattern_obj: PyObj) -> PyReturn {
    let pattern_pystr = pattern_obj
        .cast_exact::<PyStr>()
        .ok_or_type_err("format() argument must be str")?;
    let pattern_str = pattern_pystr.as_utf8()?;
    let elements = pattern::compile(pattern_str).into_value_err()?;
    pattern::validate_fields(&elements, pattern::CategorySet::DATE, "Date")?;
    if pattern::has_12h_without_ampm(&elements) {
        warn_with_class(
            exc_user_warning(),
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

fn __format__(cls: PyClass<Date>, slf: Date, spec_obj: PyObj) -> PyReturn {
    if spec_obj.is_truthy()? {
        format(cls, slf, spec_obj)
    } else {
        __str__(cls.into(), slf)
    }
}

fn parse(cls: PyClass<Date>, args: &[PyObj], kwargs: &mut IterKwargs) -> PyReturn {
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

    let fmt_obj = handle_one_kwarg("parse", *cls.state().str_format, kwargs)?.ok_or_else(|| {
        raise_type_err::<(), _>("parse() requires 'format' keyword argument").unwrap_err()
    })?;
    let fmt_pystr = fmt_obj
        .cast_exact::<PyStr>()
        .ok_or_type_err("format must be str")?;
    let fmt_bytes = fmt_pystr.as_utf8()?;

    let elements = pattern::compile(fmt_bytes).into_value_err()?;
    pattern::validate_fields(&elements, pattern::CategorySet::DATE, "Date")?;

    let pstate = pattern::parse_to_state(&elements, s).into_value_err()?;

    let year = pstate.year.ok_or_value_err(
        "Pattern must include year (YYYY/YY), month (MM/MMM/MMMM), and day (DD) fields",
    )?;
    let month = pstate.month.ok_or_value_err(
        "Pattern must include year (YYYY/YY), month (MM/MMM/MMMM), and day (DD) fields",
    )?;
    let day = pstate.day.ok_or_value_err(
        "Pattern must include year (YYYY/YY), month (MM/MMM/MMMM), and day (DD) fields",
    )?;

    let date = Date::new(year, month, day).ok_or_value_err("Invalid date")?;

    if let Some(wd) = pstate.weekday
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
    COPY_METHOD,
    DEEPCOPY_METHOD,
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
    pickle::decode_date(arg.expect_bytes()?)
        .ok_or_value_err(pickle::INVALID_DATA)?
        .to_obj(*state.date_type)
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
            year: Year::new(year).unwrap(),
            month: Month::new(month).unwrap(),
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
