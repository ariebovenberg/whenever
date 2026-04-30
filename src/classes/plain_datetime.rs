use crate::{
    classes::{
        date::Date,
        instant::Instant,
        itemized_date_delta::ItemizedDateDelta,
        itemized_delta::{ItemizedDelta, handle_delta_unit_kwargs},
        time::Time,
        time_delta::TimeDelta,
        zoned_datetime::ZonedDateTime,
    },
    common::{
        ambiguity::*,
        fmt,
        math::{self, DateRoundIncrement, DeltaUnit, DeltaUnitSet, SinceUntilKwargs},
        parse::Scan,
        pattern, round,
        scalar::*,
    },
    docstrings as doc,
    py::*,
    pymodule::State,
};
use core::{
    ffi::{CStr, c_int, c_long, c_void},
    ptr::null_mut as NULL,
};
use pyo3_ffi::*;
use std::cmp::Ordering;

#[derive(Debug, Eq, PartialEq, Ord, PartialOrd, Copy, Clone)]
pub struct DateTime {
    pub(crate) date: Date,
    pub(crate) time: Time,
}

pub(crate) const SINGLETONS: &[(&CStr, DateTime); 2] = &[
    (
        c"MIN",
        DateTime {
            date: Date {
                year: Year::new(1).unwrap(),
                month: Month::January,
                day: 1,
            },
            time: Time {
                hour: 0,
                minute: 0,
                second: 0,
                subsec: SubSecNanos::MIN,
            },
        },
    ),
    (
        c"MAX",
        DateTime {
            date: Date {
                year: Year::new(9999).unwrap(),
                month: Month::December,
                day: 31,
            },
            time: Time {
                hour: 23,
                minute: 59,
                second: 59,
                subsec: SubSecNanos::MAX,
            },
        },
    ),
];

impl DateTime {
    pub(crate) fn assume_utc(self) -> Instant {
        Instant {
            epoch: self.date.epoch_at(self.time),
            subsec: self.time.subsec,
        }
    }

    pub(crate) fn diff(self, other: Self) -> TimeDelta {
        self.assume_utc().diff(other.assume_utc())
    }

    pub(crate) fn with_date(self, date: Date) -> Self {
        DateTime {
            date,
            time: self.time,
        }
    }

    pub(crate) fn shift_date(self, months: DeltaMonths, days: DeltaDays) -> Option<Self> {
        let DateTime { date, time } = self;
        date.shift(months, days).map(|date| DateTime { date, time })
    }

    pub(crate) fn shift(self, t: TimeDelta) -> Option<Self> {
        self.assume_utc().shift(t).map(|i| i.utc_datetime())
    }

    // FUTURE: is this actually worth it?
    pub(crate) fn change_offset(self, s: OffsetDelta) -> Option<Self> {
        let Self { date, time } = self;
        // Safety: both values sufficiently within i32 range
        let secs_since_midnight = time.total_seconds() as i32 + s.get();
        Some(Self {
            date: match secs_since_midnight.div_euclid(S_PER_DAY) {
                0 => date,
                1 => date.tomorrow()?,
                -1 => date.yesterday()?,
                // more than 1 day difference is highly unlikely--but possible
                2 => date.tomorrow()?.tomorrow()?,
                -2 => date.yesterday()?.yesterday()?,
                // OffsetDelta is <48 hours, so this is safe
                _ => unreachable!(),
            },
            time: Time::from_sec_subsec(
                secs_since_midnight.rem_euclid(S_PER_DAY) as u32,
                time.subsec,
            ),
        })
    }

    /// Compute the start-of-unit DateTime. Returns `(DateTime, bool)` where
    /// the bool indicates whether the result needs DST-aware resolution
    /// (true for year/month/day, false for sub-day units that stay in the same day).
    pub(crate) fn start_of_unit(
        self,
        unit_obj: PyObj,
        state: &State,
    ) -> PyResult<(DateTime, bool)> {
        let &State {
            str_year,
            str_month,
            str_day,
            str_hour,
            str_minute,
            str_second,
            ..
        } = state;
        let d = self.date;
        match_interned_str("unit", unit_obj, |v, eq| {
            if eq(v, str_year) {
                Some((
                    DateTime {
                        date: Date {
                            year: d.year,
                            month: Month::January,
                            day: 1,
                        },
                        time: Time::MIDNIGHT,
                    },
                    true,
                ))
            } else if eq(v, str_month) {
                Some((
                    DateTime {
                        date: Date {
                            year: d.year,
                            month: d.month,
                            day: 1,
                        },
                        time: Time::MIDNIGHT,
                    },
                    true,
                ))
            } else if eq(v, str_day) {
                Some((
                    DateTime {
                        date: d,
                        time: Time::MIDNIGHT,
                    },
                    true,
                ))
            } else if eq(v, str_hour) {
                Some((
                    DateTime {
                        date: d,
                        time: Time {
                            hour: self.time.hour,
                            minute: 0,
                            second: 0,
                            subsec: SubSecNanos::MIN,
                        },
                    },
                    false,
                ))
            } else if eq(v, str_minute) {
                Some((
                    DateTime {
                        date: d,
                        time: Time {
                            hour: self.time.hour,
                            minute: self.time.minute,
                            second: 0,
                            subsec: SubSecNanos::MIN,
                        },
                    },
                    false,
                ))
            } else if eq(v, str_second) {
                Some((
                    DateTime {
                        date: d,
                        time: Time {
                            hour: self.time.hour,
                            minute: self.time.minute,
                            second: self.time.second,
                            subsec: SubSecNanos::MIN,
                        },
                    },
                    false,
                ))
            } else {
                None
            }
        })
    }

    /// Compute the end-of-unit DateTime. Returns `(DateTime, bool)` where
    /// the bool indicates whether the result needs DST-aware resolution.
    pub(crate) fn end_of_unit(self, unit_obj: PyObj, state: &State) -> PyResult<(DateTime, bool)> {
        let &State {
            str_year,
            str_month,
            str_day,
            str_hour,
            str_minute,
            str_second,
            ..
        } = state;
        let d = self.date;
        let max_time = Time {
            hour: 23,
            minute: 59,
            second: 59,
            subsec: SubSecNanos::MAX,
        };
        match_interned_str("unit", unit_obj, |v, eq| {
            if eq(v, str_year) {
                Some((
                    DateTime {
                        date: Date {
                            year: d.year,
                            month: Month::December,
                            day: 31,
                        },
                        time: max_time,
                    },
                    true,
                ))
            } else if eq(v, str_month) {
                Some((
                    DateTime {
                        date: Date {
                            year: d.year,
                            month: d.month,
                            day: d.year.days_in_month(d.month),
                        },
                        time: max_time,
                    },
                    true,
                ))
            } else if eq(v, str_day) {
                Some((
                    DateTime {
                        date: d,
                        time: max_time,
                    },
                    true,
                ))
            } else if eq(v, str_hour) {
                Some((
                    DateTime {
                        date: d,
                        time: Time {
                            hour: self.time.hour,
                            minute: 59,
                            second: 59,
                            subsec: SubSecNanos::MAX,
                        },
                    },
                    false,
                ))
            } else if eq(v, str_minute) {
                Some((
                    DateTime {
                        date: d,
                        time: Time {
                            hour: self.time.hour,
                            minute: self.time.minute,
                            second: 59,
                            subsec: SubSecNanos::MAX,
                        },
                    },
                    false,
                ))
            } else if eq(v, str_second) {
                Some((
                    DateTime {
                        date: d,
                        time: Time {
                            hour: self.time.hour,
                            minute: self.time.minute,
                            second: self.time.second,
                            subsec: SubSecNanos::MAX,
                        },
                    },
                    false,
                ))
            } else {
                None
            }
        })
    }

    pub(crate) fn read_iso(s: &mut Scan) -> Option<Self> {
        // Minimal length is 11 (YYYYMMDDTHH)
        if s.len() < 11 {
            return None;
        }
        let date = if is_datetime_sep(s[10]) {
            Date::parse_iso_extended(s.take_unchecked(10).try_into().unwrap())
        } else if is_datetime_sep(s[8]) {
            Date::parse_iso_basic(s.take_unchecked(8).try_into().unwrap())
        } else {
            return None;
        }?;
        let time = Time::read_iso(s.skip(1))?;
        Some(DateTime { date, time })
    }

    pub fn parse(s: &[u8]) -> Option<Self> {
        Scan::new(s).parse_all(Self::read_iso)
    }

    fn from_py(dt: PyDateTime) -> PyResult<Self> {
        let tzinfo = dt.tzinfo();
        if !tzinfo.is_none() {
            raise_value_err(format!("datetime must be naive, but got tzinfo={tzinfo}"))?
        }
        Ok(DateTime {
            date: Date::from_py(dt.date()),
            time: Time::from_py_dt(dt),
        })
    }
}

impl PySimpleAlloc for DateTime {}

impl std::fmt::Display for DateTime {
    fn fmt(&self, f: &mut std::fmt::Formatter) -> std::fmt::Result {
        write!(f, "{}T{}", self.date, self.time)
    }
}

fn __new__(cls: HeapType<DateTime>, args: PyTuple, kwargs: Option<PyDict>) -> PyReturn {
    if args.len() == 1 && kwargs.map_or(0, |d| d.len()) == 0 {
        let arg = args.iter().next().unwrap();
        if let Some(dt) = arg.cast_allow_subclass::<PyDateTime>() {
            return DateTime::from_py(dt)?.to_obj(cls);
        }
        return parse_iso(cls, arg);
    }
    let mut year: c_long = 0;
    let mut month: c_long = 0;
    let mut day: c_long = 0;
    let mut hour: c_long = 0;
    let mut minute: c_long = 0;
    let mut second: c_long = 0;
    let mut nanosecond: c_long = 0;

    parse_args_kwargs!(
        args,
        kwargs,
        c"lll|lll$l:PlainDateTime",
        year,
        month,
        day,
        hour,
        minute,
        second,
        nanosecond,
    );

    DateTime {
        date: Date::from_longs(year, month, day).ok_or_value_err("invalid date")?,
        time: Time::from_longs(hour, minute, second, nanosecond).ok_or_value_err("invalid time")?,
    }
    .to_obj(cls)
}

fn __repr__(_: PyType, slf: DateTime) -> PyReturn {
    let DateTime { date, time } = slf;
    PyAsciiStrBuilder::format((
        b"PlainDateTime(\"",
        date.format_iso(false),
        b' ',
        time.format_iso(fmt::Unit::Auto, false),
        b"\")",
    ))
}

fn __str__(_: PyType, slf: DateTime) -> PyReturn {
    format!("{slf}").to_py()
}

fn format_iso(
    cls: HeapType<DateTime>,
    slf: DateTime,
    args: &[PyObj],
    kwargs: &mut IterKwargs,
) -> PyReturn {
    fmt::format_iso(
        slf.date,
        slf.time,
        cls.state(),
        args,
        kwargs,
        fmt::Suffix::Absent,
    )
}

fn parse_iso(cls: HeapType<DateTime>, arg: PyObj) -> PyReturn {
    DateTime::parse(
        arg.cast_allow_subclass::<PyStr>()
            // NOTE: this exception message also needs to make sense when
            // called through the constructor
            .ok_or_type_err("when parsing from ISO format, the argument must be str")?
            .as_utf8()?,
    )
    .ok_or_else_value_err(|| format!("Invalid format: {arg}"))?
    .to_obj(cls)
}

fn __richcmp__(cls: HeapType<DateTime>, slf: DateTime, other: PyObj, op: c_int) -> PyReturn {
    if let Some(dt) = other.extract(cls) {
        match op {
            pyo3_ffi::Py_LT => slf < dt,
            pyo3_ffi::Py_LE => slf <= dt,
            pyo3_ffi::Py_EQ => slf == dt,
            pyo3_ffi::Py_NE => slf != dt,
            pyo3_ffi::Py_GT => slf > dt,
            pyo3_ffi::Py_GE => slf >= dt,
            _ => unreachable!(),
        }
        .to_py()
    } else {
        not_implemented()
    }
}

extern "C" fn __hash__(slf: PyObj) -> Py_hash_t {
    // SAFETY: self type is always passed to __hash__
    let (_, DateTime { date, time }) = unsafe { slf.assume_heaptype() };
    hashmask(hash_combine(date.hash() as Py_hash_t, time.pyhash()))
}

fn __add__(a: PyObj, b: PyObj) -> PyReturn {
    shift_operator(a, b, false)
}

fn __sub__(a: PyObj, b: PyObj) -> PyReturn {
    // easy case: subtracting two PlainDateTime objects
    if a.type_() == b.type_() {
        // SAFETY: at least one of the args is a PlainDateTime so both are.
        let (dt_type, slf) = unsafe { a.assume_heaptype::<DateTime>() };
        let (_, other) = unsafe { b.assume_heaptype::<DateTime>() };
        let state = dt_type.state();
        warn_with_class(state.warn_naive_arithmetic, doc::PLAIN_DIFF_UNAWARE_MSG, 1)?;
        slf.assume_utc()
            .diff(other.assume_utc())
            .to_obj(state.time_delta_type)
    } else {
        shift_operator(a, b, true)
    }
}

#[inline(never)]
fn shift_operator(obj_a: PyObj, obj_b: PyObj, negate: bool) -> PyReturn {
    let type_a = obj_a.type_();
    let type_b = obj_b.type_();

    if let Some(state) = type_a.same_module(type_b) {
        // SAFETY: the way we've structured binary operations within whenever
        // ensures that the first operand is the self type.
        let (dt_type, a) = unsafe { obj_a.assume_heaptype::<DateTime>() };

        if let Some(mut tdelta) = obj_b.extract(state.time_delta_type) {
            warn_with_class(state.warn_naive_arithmetic, doc::PLAIN_SHIFT_UNAWARE_MSG, 1)?;
            tdelta = tdelta.negate_if(negate);
            a.shift(tdelta).ok_or_range_err()?.to_obj(dt_type)
        } else {
            not_implemented()
        }
    } else {
        not_implemented()
    }
}

#[allow(static_mut_refs)]
static mut SLOTS: &[PyType_Slot] = &[
    slotmethod!(DateTime, Py_tp_new, __new__),
    slotmethod!(DateTime, Py_tp_repr, __repr__, 1),
    slotmethod!(DateTime, Py_tp_str, __str__, 1),
    slotmethod!(DateTime, Py_tp_richcompare, __richcmp__),
    slotmethod!(Py_nb_add, __add__, 2),
    slotmethod!(Py_nb_subtract, __sub__, 2),
    PyType_Slot {
        slot: Py_tp_doc,
        pfunc: doc::PLAINDATETIME.as_ptr() as *mut c_void,
    },
    PyType_Slot {
        slot: Py_tp_hash,
        pfunc: __hash__ as *mut c_void,
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
        slot: Py_tp_dealloc,
        pfunc: generic_dealloc as *mut c_void,
    },
    PyType_Slot {
        slot: 0,
        pfunc: NULL(),
    },
];

#[inline]
#[allow(clippy::too_many_arguments)]
pub(crate) fn set_components_from_kwargs(
    key: PyObj,
    value: PyObj,
    year: &mut c_long,
    month: &mut c_long,
    day: &mut c_long,
    hour: &mut c_long,
    minute: &mut c_long,
    second: &mut c_long,
    nanos: &mut c_long,
    str_year: PyObj,
    str_month: PyObj,
    str_day: PyObj,
    str_hour: PyObj,
    str_minute: PyObj,
    str_second: PyObj,
    str_nanosecond: PyObj,
    eq: fn(PyObj, PyObj) -> bool,
) -> PyResult<bool> {
    if eq(key, str_year) {
        *year = value
            .cast_allow_subclass::<PyInt>()
            .ok_or_type_err("year must be an integer")?
            .to_long()?;
    } else if eq(key, str_month) {
        *month = value
            .cast_allow_subclass::<PyInt>()
            .ok_or_type_err("month must be an integer")?
            .to_long()?;
    } else if eq(key, str_day) {
        *day = value
            .cast_allow_subclass::<PyInt>()
            .ok_or_type_err("day must be an integer")?
            .to_long()?;
    } else if eq(key, str_hour) {
        *hour = value
            .cast_allow_subclass::<PyInt>()
            .ok_or_type_err("hour must be an integer")?
            .to_long()?;
    } else if eq(key, str_minute) {
        *minute = value
            .cast_allow_subclass::<PyInt>()
            .ok_or_type_err("minute must be an integer")?
            .to_long()?;
    } else if eq(key, str_second) {
        *second = value
            .cast_allow_subclass::<PyInt>()
            .ok_or_type_err("second must be an integer")?
            .to_long()?;
    } else if eq(key, str_nanosecond) {
        *nanos = value
            .cast_allow_subclass::<PyInt>()
            .ok_or_type_err("nanosecond must be an integer")?
            .to_long()?;
    } else {
        return Ok(false);
    }
    Ok(true)
}

fn replace(
    cls: HeapType<DateTime>,
    slf: DateTime,
    args: &[PyObj],
    kwargs: &mut IterKwargs,
) -> PyReturn {
    if !args.is_empty() {
        raise_type_err("replace() takes no positional arguments")?
    }
    let &State {
        str_year,
        str_month,
        str_day,
        str_hour,
        str_minute,
        str_second,
        str_nanosecond,
        ..
    } = cls.state();
    let mut year = slf.date.year.get().into();
    let mut month = slf.date.month.get().into();
    let mut day = slf.date.day.into();
    let mut hour = slf.time.hour.into();
    let mut minute = slf.time.minute.into();
    let mut second = slf.time.second.into();
    let mut nanos = slf.time.subsec.get() as _;
    handle_kwargs("replace", kwargs, |key, value, eq| {
        set_components_from_kwargs(
            key,
            value,
            &mut year,
            &mut month,
            &mut day,
            &mut hour,
            &mut minute,
            &mut second,
            &mut nanos,
            str_year,
            str_month,
            str_day,
            str_hour,
            str_minute,
            str_second,
            str_nanosecond,
            eq,
        )
    })?;
    DateTime {
        date: Date::from_longs(year, month, day).ok_or_value_err("invalid date")?,
        time: Time::from_longs(hour, minute, second, nanos).ok_or_value_err("invalid time")?,
    }
    .to_obj(cls)
}

fn add(
    cls: HeapType<DateTime>,
    slf: DateTime,
    args: &[PyObj],
    kwargs: &mut IterKwargs,
) -> PyReturn {
    shift_method(cls, slf, args, kwargs, false)
}

fn subtract(
    cls: HeapType<DateTime>,
    slf: DateTime,
    args: &[PyObj],
    kwargs: &mut IterKwargs,
) -> PyReturn {
    shift_method(cls, slf, args, kwargs, true)
}

#[inline(never)]
fn shift_method(
    cls: HeapType<DateTime>,
    slf: DateTime,
    args: &[PyObj],
    kwargs: &mut IterKwargs,
    negate: bool,
) -> PyReturn {
    let fname = if negate { "subtract" } else { "add" };
    let state = cls.state();
    let &State {
        str_years,
        str_months,
        str_weeks,
        str_days,
        str_hours,
        str_minutes,
        str_seconds,
        str_milliseconds,
        str_microseconds,
        str_nanoseconds,
        str_naive_arithmetic_ok,
        time_delta_type,
        itemized_date_delta_type,
        itemized_delta_type,
        warn_naive_arithmetic,
        ..
    } = state;
    let mut months = DeltaMonths::ZERO;
    let mut days = DeltaDays::ZERO;
    let mut tdelta = TimeDelta::ZERO;
    let mut suppress_unaware = false;

    match *args {
        [arg] => {
            for (key, value) in kwargs.by_ref() {
                if key.py_eq(str_naive_arithmetic_ok)? {
                    suppress_unaware = value.is_truthy();
                } else {
                    raise_type_err(format!(
                        "{fname}() can't mix positional and keyword arguments"
                    ))?;
                }
            }
            if let Some(t) = arg.extract(time_delta_type) {
                tdelta = t;
            } else if let Some(d) = arg.extract(itemized_date_delta_type) {
                let (m, dy) = d.to_months_days().ok_or_range_err()?;
                months = m;
                days = dy;
            } else if let Some(d) = arg.extract(itemized_delta_type) {
                let (m, dy, td) = d.to_components().ok_or_range_err()?;
                months = m;
                days = dy;
                tdelta = td;
            } else {
                raise_type_err(format!("{fname}() argument must be a delta"))?
            }
        }
        [] => {
            let mut units = DeltaUnitSet::EMPTY;
            handle_kwargs(fname, kwargs, |key, value, eq| {
                if eq(key, str_naive_arithmetic_ok) {
                    suppress_unaware = value.is_truthy();
                    Ok(true)
                } else {
                    handle_delta_unit_kwargs(
                        key,
                        value,
                        &mut months,
                        &mut days,
                        &mut tdelta,
                        &mut units,
                        eq,
                        str_years,
                        str_months,
                        str_weeks,
                        str_days,
                        str_hours,
                        str_minutes,
                        str_seconds,
                        Some(str_milliseconds),
                        Some(str_microseconds),
                        str_nanoseconds,
                    )
                }
            })?;
        }
        _ => raise_type_err(format!(
            "{}() takes at most 1 positional argument, got {}",
            fname,
            args.len()
        ))?,
    }

    months = months.negate_if(negate);
    days = days.negate_if(negate);
    tdelta = tdelta.negate_if(negate);

    if !tdelta.is_zero() && !suppress_unaware {
        warn_with_class(warn_naive_arithmetic, doc::PLAIN_SHIFT_UNAWARE_MSG, 1)?;
    }
    slf.shift_date(months, days)
        .and_then(|dt| dt.shift(tdelta))
        .ok_or_range_err()?
        .to_obj(cls)
}

fn difference(
    cls: HeapType<DateTime>,
    slf: DateTime,
    args: &[PyObj],
    kwargs: &mut IterKwargs,
) -> PyReturn {
    let state = cls.state();
    let mut suppress_unaware = false;
    for (key, value) in kwargs.by_ref() {
        if key.py_eq(state.str_naive_arithmetic_ok)? {
            suppress_unaware = value.is_truthy();
        } else {
            raise_type_err(format!("Unknown keyword argument: {key}"))?;
        }
    }
    let [arg] = *args else {
        raise_type_err("difference() takes exactly 1 argument")?
    };
    if let Some(dt) = arg.extract(cls) {
        if !suppress_unaware {
            warn_with_class(state.warn_naive_arithmetic, doc::PLAIN_DIFF_UNAWARE_MSG, 1)?;
        }
        slf.assume_utc()
            .diff(dt.assume_utc())
            .to_obj(state.time_delta_type)
    } else {
        raise_type_err("difference() argument must be a PlainDateTime")?
    }
}

fn __reduce__(cls: HeapType<DateTime>, slf: DateTime) -> PyResult<Owned<PyTuple>> {
    let DateTime {
        date: Date { year, month, day },
        time:
            Time {
                hour,
                minute,
                second,
                subsec,
            },
    } = slf;
    let data = pack![
        year.get(),
        month.get(),
        day,
        hour,
        minute,
        second,
        subsec.get()
    ];
    (
        cls.state().unpickle_plain_datetime.newref(),
        (data.to_py()?,).into_pytuple()?,
    )
        .into_pytuple()
}

pub(crate) fn unpickle(state: &State, arg: PyObj) -> PyReturn {
    let py_bytes = arg
        .cast_exact::<PyBytes>()
        .ok_or_type_err("invalid pickle data")?;

    let mut packed = py_bytes.as_bytes()?;
    if packed.len() != 11 {
        raise_type_err("invalid pickle data")?
    }
    DateTime {
        date: Date {
            year: Year::new_unchecked(unpack_one!(packed, u16)),
            month: Month::new_unchecked(unpack_one!(packed, u8)),
            day: unpack_one!(packed, u8),
        },
        time: Time {
            hour: unpack_one!(packed, u8),
            minute: unpack_one!(packed, u8),
            second: unpack_one!(packed, u8),
            subsec: SubSecNanos::new_unchecked(unpack_one!(packed, i32)),
        },
    }
    .to_obj(state.plain_datetime_type)
}

fn to_stdlib(cls: HeapType<DateTime>, slf: DateTime) -> PyReturn {
    let DateTime {
        date: Date { year, month, day },
        time:
            Time {
                hour,
                minute,
                second,
                subsec,
            },
    } = slf;
    let &PyDateTime_CAPI {
        DateTime_FromDateAndTime,
        DateTimeType,
        ..
    } = cls.state().py_api;
    // SAFETY: calling C API with valid arguments
    unsafe {
        DateTime_FromDateAndTime(
            year.get().into(),
            month.get().into(),
            day.into(),
            hour.into(),
            minute.into(),
            second.into(),
            (subsec.get() / 1_000) as _,
            Py_None(),
            DateTimeType,
        )
    }
    .rust_owned()
}

fn date(cls: HeapType<DateTime>, slf: DateTime) -> PyReturn {
    slf.date.to_obj(cls.state().date_type)
}

fn time(cls: HeapType<DateTime>, slf: DateTime) -> PyReturn {
    slf.time.to_obj(cls.state().time_type)
}

fn day_of_year(_: HeapType<DateTime>, slf: DateTime) -> PyReturn {
    let d = slf.date;
    (d.year.days_before_month(d.month) + d.day as u16).to_py()
}

fn days_in_month(_: HeapType<DateTime>, slf: DateTime) -> PyReturn {
    let d = slf.date;
    d.year.days_in_month(d.month).to_py()
}

fn days_in_year(_: HeapType<DateTime>, slf: DateTime) -> PyReturn {
    (if slf.date.year.is_leap() {
        366_u16
    } else {
        365_u16
    })
    .to_py()
}

fn in_leap_year(_: HeapType<DateTime>, slf: DateTime) -> PyReturn {
    slf.date.year.is_leap().to_py()
}

fn start_of(cls: HeapType<DateTime>, slf: DateTime, unit_obj: PyObj) -> PyReturn {
    let (dt, _) = slf.start_of_unit(unit_obj, cls.state())?;
    dt.to_obj(cls)
}

fn end_of(cls: HeapType<DateTime>, slf: DateTime, unit_obj: PyObj) -> PyReturn {
    let (dt, _) = slf.end_of_unit(unit_obj, cls.state())?;
    dt.to_obj(cls)
}

fn is_datetime_sep(c: u8) -> bool {
    c == b'T' || c == b' ' || c == b't'
}

fn assume_utc(cls: HeapType<DateTime>, d: DateTime) -> PyReturn {
    d.assume_utc().to_obj(cls.state().instant_type)
}

fn assume_fixed_offset(cls: HeapType<DateTime>, slf: DateTime, arg: PyObj) -> PyReturn {
    let &State {
        time_delta_type,
        offset_datetime_type,
        ..
    } = cls.state();
    slf.with_offset(Offset::from_obj(arg, time_delta_type)?)
        .ok_or_range_err()?
        .to_obj(offset_datetime_type)
}

fn assume_tz(
    cls: HeapType<DateTime>,
    slf: DateTime,
    args: &[PyObj],
    kwargs: &mut IterKwargs,
) -> PyReturn {
    let &State {
        str_disambiguate,
        str_compatible,
        str_raise,
        str_earlier,
        str_later,
        zoned_datetime_type,
        exc_skipped,
        exc_repeated,
        ref tz_store,
        ..
    } = cls.state();

    let DateTime { date, time } = slf;
    let &[tz_obj] = args else {
        raise_type_err(format!(
            "assume_tz() takes 1 positional argument but {} were given",
            args.len()
        ))?
    };

    let dis = Disambiguate::from_only_kwarg(
        kwargs,
        str_disambiguate,
        "assume_tz",
        str_compatible,
        str_raise,
        str_earlier,
        str_later,
    )?
    .unwrap_or(Disambiguate::Compatible);
    let tz = tz_store.obj_get(tz_obj)?;
    ZonedDateTime::resolve_using_disambiguate(date, time, &tz, dis, exc_repeated, exc_skipped)?
        .assume_tz_unchecked(tz, zoned_datetime_type)
}

fn assume_system_tz(
    cls: HeapType<DateTime>,
    slf: DateTime,
    args: &[PyObj],
    kwargs: &mut IterKwargs,
) -> PyReturn {
    let &State {
        ref tz_store,
        zoned_datetime_type,
        str_disambiguate,
        exc_skipped,
        exc_repeated,
        str_compatible,
        str_raise,
        str_earlier,
        str_later,
        ..
    } = cls.state();
    let DateTime { date, time } = slf;
    if !args.is_empty() {
        raise_type_err("assume_system_tz() takes no positional arguments")?
    }

    let dis = Disambiguate::from_only_kwarg(
        kwargs,
        str_disambiguate,
        "assume_tz",
        str_compatible,
        str_raise,
        str_earlier,
        str_later,
    )?
    .unwrap_or(Disambiguate::Compatible);
    let tz = tz_store.get_system_tz()?;
    ZonedDateTime::resolve_using_disambiguate(date, time, &tz, dis, exc_repeated, exc_skipped)?
        .assume_tz_unchecked(tz, zoned_datetime_type)
}

fn replace_date(cls: HeapType<DateTime>, slf: DateTime, arg: PyObj) -> PyReturn {
    let Some(date) = arg.extract(cls.state().date_type) else {
        raise_type_err("argument must be a whenever.Date")?
    };
    DateTime { date, ..slf }.to_obj(cls)
}

fn replace_time(cls: HeapType<DateTime>, slf: DateTime, arg: PyObj) -> PyReturn {
    let Some(time) = arg.extract(cls.state().time_type) else {
        raise_type_err("argument must be a whenever.Time")?
    };
    DateTime { time, ..slf }.to_obj(cls)
}

fn since(
    cls: HeapType<DateTime>,
    slf: DateTime,
    args: &[PyObj],
    kwargs: &mut IterKwargs,
) -> PyReturn {
    plain_since(cls, slf, args, kwargs, false)
}

fn until(
    cls: HeapType<DateTime>,
    slf: DateTime,
    args: &[PyObj],
    kwargs: &mut IterKwargs,
) -> PyReturn {
    plain_since(cls, slf, args, kwargs, true)
}

#[inline(never)]
fn plain_since(
    cls: HeapType<DateTime>,
    slf: DateTime,
    args: &[PyObj],
    kwargs: &mut IterKwargs,
    flip: bool,
) -> PyReturn {
    let fname = if flip { "until" } else { "since" };
    let state = cls.state();

    let other = handle_one_arg(fname, args)?
        .extract(cls)
        .ok_or_type_err("argument must be a whenever.PlainDateTime")?;

    let mut suppress_unaware = false;
    let since_kwargs = SinceUntilKwargs::parse_with(fname, state, kwargs, |key, value, eq| {
        if eq(key, state.str_naive_arithmetic_ok) {
            suppress_unaware = value.is_truthy();
            Ok(true)
        } else {
            Ok(false)
        }
    })?;

    // Warn only when the output contains exact time units (hours/min/sec/ns).
    // Calendar-only output (years/months/weeks/days) doesn't involve clock time,
    // so there's no DST ambiguity in that case.
    if since_kwargs.has_exact_output() && !suppress_unaware {
        warn_with_class(state.warn_naive_arithmetic, doc::PLAIN_DIFF_UNAWARE_MSG, 1)?;
    }

    plain_since_inner(state, slf, other, since_kwargs, flip)
}

/// Resolve a non-ZonedDateTime `relative_to` argument to a `DateTime`,
/// emitting the appropriate warning if the condition is met.
///
/// - `warn_plain`: emit `TZUnawareArithmetic` warning for PlainDateTime
/// - `warn_offset`: emit `PotentiallyStaleOffset` warning for OffsetDateTime
///
/// The caller is responsible for handling the ZonedDateTime case before calling
/// this function (which always returns `Err` for ZonedDateTime args).
pub(crate) fn resolve_local_relative_to(
    arg: PyObj,
    state: &State,
    warn_plain: bool,
    warn_offset: bool,
) -> PyResult<DateTime> {
    if let Some(pdt) = arg.extract(state.plain_datetime_type) {
        if warn_plain {
            warn_with_class(
                state.warn_naive_arithmetic,
                doc::PLAIN_RELATIVE_TO_UNAWARE_MSG,
                1,
            )?;
        }
        Ok(pdt)
    } else if let Some(odt) = arg.extract(state.offset_datetime_type) {
        if warn_offset {
            warn_with_class(
                state.warn_potentially_stale_offset,
                doc::STALE_OFFSET_CALENDAR_MSG,
                1,
            )?;
        }
        Ok(odt.without_offset())
    } else {
        raise_type_err("relative_to must be a ZonedDateTime, PlainDateTime, or OffsetDateTime")
    }
}

pub(crate) fn plain_since_float(
    a: DateTime,
    b: DateTime,
    target_date: Date,
    unit: DeltaUnit,
    neg: bool,
) -> PyReturn {
    match unit.to_exact(true) {
        Ok(u) => {
            // Exact unit (including weeks/days as 24h): divide by unit nanoseconds.
            // For nanoseconds (in_nanos == 1), return int to preserve full precision.
            let nanos = a.diff(b).total_nanos();
            let unit_nanos = u.in_nanos();
            if unit_nanos == 1 {
                nanos.to_py()
            } else {
                (nanos as f64 / unit_nanos as f64).to_py()
            }
        }
        Err(cal_unit) => total_cal_plain(neg, cal_unit, a.assume_utc(), b, target_date),
    }
}

/// Calendar-unit fractional total for PlainDateTime/OffsetDateTime, treating
/// the reference datetime as UTC (no DST transitions).
///
/// This mirrors `zoned_datetime::total_cal` but works with raw `Instant` and
/// `DateTime` values instead of `ZonedDateTime`, avoiding the need for a UTC
/// `TzPtr`.
pub(crate) fn total_cal_plain(
    neg: bool,
    unit: math::CalUnit,
    a_inst: Instant,
    b_dt: DateTime,
    target_date: Date,
) -> PyReturn {
    let (result, trunc_raw, expand_raw) =
        math::date_diff_single_unit(target_date, b_dt.date, DateRoundIncrement::MIN, unit, neg)
            .ok_or_range_err()?;
    let trunc = b_dt.with_date(trunc_raw.into()).assume_utc();
    let expand = b_dt.with_date(expand_raw.into()).assume_utc();
    let num = a_inst.diff(trunc).total_nanos() as f64;
    let denom = expand.diff(trunc).total_nanos() as f64;
    let sign: f64 = if neg { -1.0 } else { 1.0 };
    ((result.abs() as f64 + num / denom) * sign).to_py()
}

/// Shared since() implementation for PlainDateTime (and OffsetDateTime).
/// Days are always 24 hours (no DST adjustments).
pub(crate) fn plain_since_inner(
    state: &State,
    slf: DateTime,
    other: DateTime,
    kwargs: SinceUntilKwargs,
    flip: bool,
) -> PyReturn {
    let (a, b) = if flip { (other, slf) } else { (slf, other) };

    let neg = a < b;

    let target_date = match (neg, b.with_date(a.date).cmp(&a)) {
        (false, Ordering::Greater) => a.date.yesterday(),
        (true, Ordering::Less) => a.date.tomorrow(),
        _ => Some(a.date),
    }
    .ok_or_range_err()?;
    match kwargs {
        SinceUntilKwargs::Total(unit) => plain_since_float(a, b, target_date, unit, neg),
        SinceUntilKwargs::InUnits(units, round_mode, round_increment) => plain_since_in_units(
            state,
            a,
            b,
            target_date,
            units,
            round_mode,
            round_increment,
            neg,
        ),
    }
}

#[allow(clippy::too_many_arguments)]
fn plain_since_in_units(
    state: &State,
    a: DateTime,
    b: DateTime,
    target_date: Date,
    units: DeltaUnitSet,
    round_mode: round::Mode,
    round_increment: math::RoundIncrement,
    neg: bool,
) -> PyReturn {
    let smallest_unit = units.smallest();
    let (cal_units, exact_units) = units.split_cal_exact();

    let (mut cal_results, trunc_date, expand_date) = if cal_units.is_empty() {
        (ItemizedDateDelta::UNSET, b.date.into(), a.date.into())
    } else {
        let inc = if smallest_unit.to_exact(false).is_err() {
            round_increment.to_date().ok_or_range_err()?
        } else {
            DateRoundIncrement::MIN
        };
        math::date_diff(target_date, b.date, inc, cal_units, neg).ok_or_range_err()?
    };

    let trunc_dt = b.with_date(trunc_date.into());
    let expand_dt = b.with_date(expand_date.into());

    // If there are no time units, round the calendar units.
    // Otherwise, calculate the time delta remainder
    let mut result = if exact_units.is_empty() {
        cal_results.round_by_time(
            cal_units.smallest(),
            // This UTC conversion is a bit weird, but it allows us to reuse
            // the logic since plain and UTC datetimes both have no timezone
            // adjustments.
            a.assume_utc(),
            trunc_dt.assume_utc(),
            expand_dt.assume_utc(),
            round_mode.to_abs_trunc(neg),
            round_increment.to_date().ok_or_range_err()?,
            neg,
        );
        ItemizedDelta::UNSET
    } else {
        a.diff(trunc_dt)
            .in_exact_units(exact_units, round_increment, round_mode.to_abs_euclid(neg))
            .ok_or_range_err()?
    };

    result.fill_cal_units(cal_results);
    result.to_obj(state.itemized_delta_type)
}

fn round(
    cls: HeapType<DateTime>,
    slf: DateTime,
    args: &[PyObj],
    kwargs: &mut IterKwargs,
) -> PyReturn {
    let round::Args {
        increment, mode, ..
    } = round::Args::parse(cls.state(), args, kwargs, false)?;
    let round_nanos = match increment {
        round::RoundIncrement::Day => NS_PER_DAY,
        round::RoundIncrement::Exact(ns) => ns.get(),
    };
    let DateTime { mut date, time } = slf;
    let (time_rounded, next_day) = time.round(round_nanos, mode);
    if next_day == 1 {
        date = date.tomorrow().ok_or_range_err()?;
    }
    DateTime {
        date,
        time: time_rounded,
    }
    .to_obj(cls)
}

fn format(_cls: HeapType<DateTime>, slf: DateTime, pattern_obj: PyObj) -> PyReturn {
    let pattern_pystr = pattern_obj
        .cast_exact::<PyStr>()
        .ok_or_type_err("format() argument must be str")?;
    let pattern_str = pattern_pystr.as_utf8()?;
    let elements = pattern::compile(pattern_str).into_value_err()?;
    pattern::validate_fields(&elements, pattern::CategorySet::DATE_TIME, "PlainDateTime")?;
    if pattern::has_12h_without_ampm(&elements) {
        warn_with_class(
            // SAFETY: PyExc_UserWarning is always valid
            unsafe { PyObj::from_ptr_unchecked(PyExc_UserWarning) },
            c"12-hour format (ii) without AM/PM designator (a/aa) may be ambiguous",
            1,
        )?;
    }
    let vals = pattern::FormatValues {
        year: slf.date.year,
        month: slf.date.month,
        day: slf.date.day,
        weekday: slf.date.day_of_week(),
        hour: slf.time.hour,
        minute: slf.time.minute,
        second: slf.time.second,
        nanos: slf.time.subsec,
        offset_secs: None,
        tz_id: None,
        tz_abbrev: None,
    };
    pattern::format_to_py(&elements, &vals)
}

fn __format__(cls: HeapType<DateTime>, slf: DateTime, spec_obj: PyObj) -> PyReturn {
    if spec_obj.is_truthy() {
        format(cls, slf, spec_obj)
    } else {
        __str__(cls.into(), slf)
    }
}

fn parse(cls: HeapType<DateTime>, args: &[PyObj], kwargs: &mut IterKwargs) -> PyReturn {
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
    pattern::validate_fields(&elements, pattern::CategorySet::DATE_TIME, "PlainDateTime")?;

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

    let hour = state.hour.unwrap_or(0);
    let minute = state.minute.unwrap_or(0);
    let second = state.second.unwrap_or(0);

    if hour >= 24 || minute >= 60 || second >= 60 {
        raise_value_err("Invalid time")?;
    }

    let time = Time {
        hour,
        minute,
        second,
        subsec: state.nanos,
    };

    DateTime { date, time }.to_obj(cls)
}

static mut METHODS: &[PyMethodDef] = &[
    method0!(DateTime, __copy__, c""),
    method1!(DateTime, __deepcopy__, c""),
    method0!(DateTime, __reduce__, c""),
    method0!(DateTime, to_stdlib, doc::BASICCONVERSIONS_TO_STDLIB),
    method0!(DateTime, date, doc::LOCALTIME_DATE),
    method0!(DateTime, time, doc::LOCALTIME_TIME),
    method0!(DateTime, day_of_year, doc::LOCALTIME_DAY_OF_YEAR),
    method0!(DateTime, days_in_month, doc::LOCALTIME_DAYS_IN_MONTH),
    method0!(DateTime, days_in_year, doc::LOCALTIME_DAYS_IN_YEAR),
    method0!(DateTime, in_leap_year, doc::LOCALTIME_IN_LEAP_YEAR),
    method1!(DateTime, start_of, doc::PLAINDATETIME_START_OF),
    method1!(DateTime, end_of, doc::PLAINDATETIME_END_OF),
    method_kwargs!(DateTime, format_iso, doc::PLAINDATETIME_FORMAT_ISO),
    classmethod1!(DateTime, parse_iso, doc::PLAINDATETIME_PARSE_ISO),
    method_kwargs!(DateTime, replace, doc::PLAINDATETIME_REPLACE),
    method0!(DateTime, assume_utc, doc::PLAINDATETIME_ASSUME_UTC),
    method1!(
        DateTime,
        assume_fixed_offset,
        doc::PLAINDATETIME_ASSUME_FIXED_OFFSET
    ),
    method_kwargs!(DateTime, assume_tz, doc::PLAINDATETIME_ASSUME_TZ),
    method_kwargs!(
        DateTime,
        assume_system_tz,
        doc::PLAINDATETIME_ASSUME_SYSTEM_TZ
    ),
    method1!(DateTime, replace_date, doc::PLAINDATETIME_REPLACE_DATE),
    method1!(DateTime, replace_time, doc::PLAINDATETIME_REPLACE_TIME),
    method_kwargs!(DateTime, add, doc::PLAINDATETIME_ADD),
    method_kwargs!(DateTime, subtract, doc::PLAINDATETIME_SUBTRACT),
    method_kwargs!(DateTime, difference, doc::PLAINDATETIME_DIFFERENCE),
    method_kwargs!(DateTime, since, doc::PLAINDATETIME_SINCE),
    method_kwargs!(DateTime, until, doc::PLAINDATETIME_UNTIL),
    method_kwargs!(DateTime, round, doc::PLAINDATETIME_ROUND),
    method1!(DateTime, format, doc::PLAINDATETIME_FORMAT),
    method1!(DateTime, __format__, c""),
    classmethod_kwargs!(DateTime, parse, doc::PLAINDATETIME_PARSE),
    classmethod_kwargs!(DateTime, __get_pydantic_core_schema__, doc::PYDANTIC_SCHEMA),
    PyMethodDef::zeroed(),
];

fn year(_: PyType, slf: DateTime) -> PyReturn {
    slf.date.year.get().to_py()
}

fn month(_: PyType, slf: DateTime) -> PyReturn {
    slf.date.month.get().to_py()
}

fn day(_: PyType, slf: DateTime) -> PyReturn {
    slf.date.day.to_py()
}

fn hour(_: PyType, slf: DateTime) -> PyReturn {
    slf.time.hour.to_py()
}

fn minute(_: PyType, slf: DateTime) -> PyReturn {
    slf.time.minute.to_py()
}

fn second(_: PyType, slf: DateTime) -> PyReturn {
    slf.time.second.to_py()
}

fn nanosecond(_: PyType, slf: DateTime) -> PyReturn {
    slf.time.subsec.get().to_py()
}

static mut GETSETTERS: &[PyGetSetDef] = &[
    getter!(DateTime, year, doc::LOCALTIME_YEAR),
    getter!(DateTime, month, doc::LOCALTIME_MONTH),
    getter!(DateTime, day, doc::LOCALTIME_DAY),
    getter!(DateTime, hour, doc::LOCALTIME_HOUR),
    getter!(DateTime, minute, doc::LOCALTIME_MINUTE),
    getter!(DateTime, second, doc::LOCALTIME_SECOND),
    getter!(DateTime, nanosecond, doc::LOCALTIME_NANOSECOND),
    PyGetSetDef {
        name: NULL(),
        get: None,
        set: None,
        doc: NULL(),
        closure: NULL(),
    },
];

pub(crate) static mut SPEC: PyType_Spec =
    type_spec::<DateTime>(c"whenever.PlainDateTime", unsafe { SLOTS });

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
    fn test_parse_valid() {
        let cases = &[
            (&b"2023-03-02 02:09:09"[..], 2023, 3, 2, 2, 9, 9, 0),
            (
                b"2023-03-02 02:09:09.123456789",
                2023,
                3,
                2,
                2,
                9,
                9,
                123_456_789,
            ),
        ];
        for &(str, y, m, d, h, min, s, ns) in cases {
            assert_eq!(
                DateTime::parse(str),
                Some(DateTime {
                    date: mkdate(y, m, d),
                    time: Time {
                        hour: h,
                        minute: min,
                        second: s,
                        subsec: SubSecNanos::new_unchecked(ns),
                    },
                })
            );
        }
    }

    #[test]
    fn test_parse_invalid() {
        // dot but no fractional digits
        assert_eq!(DateTime::parse(b"2023-03-02 02:09:09."), None);
        // too many fractions
        assert_eq!(DateTime::parse(b"2023-03-02 02:09:09.1234567890"), None);
        // invalid minute
        assert_eq!(DateTime::parse(b"2023-03-02 02:69:09.123456789"), None);
        // invalid date
        assert_eq!(DateTime::parse(b"2023-02-29 02:29:09.123456789"), None);
    }

    #[test]
    fn test_change_offset() {
        let d = DateTime {
            date: mkdate(2023, 3, 2),
            time: Time {
                hour: 2,
                minute: 9,
                second: 9,
                subsec: SubSecNanos::MIN,
            },
        };
        assert_eq!(d.change_offset(OffsetDelta::ZERO).unwrap(), d);
        assert_eq!(
            d.change_offset(OffsetDelta::new_unchecked(1)).unwrap(),
            DateTime {
                date: mkdate(2023, 3, 2),
                time: Time {
                    hour: 2,
                    minute: 9,
                    second: 10,
                    subsec: SubSecNanos::MIN,
                }
            }
        );
        assert_eq!(
            d.change_offset(OffsetDelta::new_unchecked(-1)).unwrap(),
            DateTime {
                date: mkdate(2023, 3, 2),
                time: Time {
                    hour: 2,
                    minute: 9,
                    second: 8,
                    subsec: SubSecNanos::MIN,
                }
            }
        );
        assert_eq!(
            d.change_offset(OffsetDelta::new_unchecked(86_400)).unwrap(),
            DateTime {
                date: mkdate(2023, 3, 3),
                time: Time {
                    hour: 2,
                    minute: 9,
                    second: 9,
                    subsec: SubSecNanos::MIN,
                }
            }
        );
        assert_eq!(
            d.change_offset(OffsetDelta::new_unchecked(-86_400))
                .unwrap(),
            DateTime {
                date: mkdate(2023, 3, 1),
                time: Time {
                    hour: 2,
                    minute: 9,
                    second: 9,
                    subsec: SubSecNanos::MIN,
                }
            }
        );
        let midnight = DateTime {
            date: mkdate(2023, 3, 2),
            time: Time {
                hour: 0,
                minute: 0,
                second: 0,
                subsec: SubSecNanos::MIN,
            },
        };
        assert_eq!(midnight.change_offset(OffsetDelta::ZERO).unwrap(), midnight);
        assert_eq!(
            midnight
                .change_offset(OffsetDelta::new_unchecked(-1))
                .unwrap(),
            DateTime {
                date: mkdate(2023, 3, 1),
                time: Time {
                    hour: 23,
                    minute: 59,
                    second: 59,
                    subsec: SubSecNanos::MIN,
                }
            }
        );
        assert_eq!(
            midnight
                .change_offset(OffsetDelta::new_unchecked(-86_400))
                .unwrap(),
            DateTime {
                date: mkdate(2023, 3, 1),
                time: Time {
                    hour: 0,
                    minute: 0,
                    second: 0,
                    subsec: SubSecNanos::MIN,
                }
            }
        );
        assert_eq!(
            midnight
                .change_offset(OffsetDelta::new_unchecked(-86_401))
                .unwrap(),
            DateTime {
                date: mkdate(2023, 2, 28),
                time: Time {
                    hour: 23,
                    minute: 59,
                    second: 59,
                    subsec: SubSecNanos::MIN,
                }
            }
        );
        assert_eq!(
            DateTime {
                date: mkdate(2023, 1, 1),
                time: Time {
                    hour: 0,
                    minute: 0,
                    second: 0,
                    subsec: SubSecNanos::MIN,
                }
            }
            .change_offset(OffsetDelta::new_unchecked(-1))
            .unwrap(),
            DateTime {
                date: mkdate(2022, 12, 31),
                time: Time {
                    hour: 23,
                    minute: 59,
                    second: 59,
                    subsec: SubSecNanos::MIN,
                }
            }
        )
    }
}
