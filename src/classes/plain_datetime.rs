use crate::{
    classes::{
        date::{self, Date},
        date_delta::DateDelta,
        instant::Instant,
        itemized_date_delta::ItemizedDateDelta,
        itemized_delta::ItemizedDelta,
        time::{self, Time},
    },
    common::{
        disambiguation::*,
        fmt, pattern, pickle, round_args as round,
        shift_args::{parse_datetime_shift_arg, parse_datetime_shift_kwargs},
    },
    docstrings as doc,
    domain::{
        difference::{self, CalendarIncrement, DifferenceSpec, DifferenceUnit, DifferenceUnitSet},
        local::ResolvePolicy,
        scalar::*,
    },
    py::*,
    pymodule::State,
};
use core::{
    ffi::{CStr, c_int, c_long, c_void},
    ptr::null_mut as NULL,
};
use pyo3_ffi::*;
use std::cmp::Ordering;

pub(crate) use crate::domain::plain_datetime::DateTimeBoundaryUnit;
pub use crate::domain::plain_datetime::PlainDateTime;

pub(crate) const SINGLETONS: &[(&CStr, PlainDateTime); 2] =
    &[(c"MIN", PlainDateTime::MIN), (c"MAX", PlainDateTime::MAX)];

impl DateTimeBoundaryUnit {
    pub(crate) fn from_py(obj: PyObj, state: &State) -> PyResult<Self> {
        find_interned(obj, |v, eq| {
            Some(Ok(
                if let Some(unit) = date::DateBoundaryUnit::match_py(v, state, eq) {
                    Self::Date(unit)
                } else if eq(v, *state.str_day) {
                    Self::Day
                } else if let Some(unit) = time::TimeBoundaryUnit::match_py(v, state, eq) {
                    Self::Time(unit)
                } else if eq(v, *state.str_week) {
                    return Some(raise_value_err(
                        "unit 'week' is ambiguous. Use 'week_mon' or 'week_sun' instead.",
                    ));
                } else {
                    None?
                },
            ))
        })
        .transpose()?
        .ok_or_else_value_err(|| format!("Invalid unit: {obj}"))
    }
}

impl PlainDateTime {
    fn to_stdlib_datetime(self, api: &PyDateTime_CAPI) -> PyReturn {
        api.new_datetime(self, None).map(Owned::into_obj)
    }

    fn from_stdlib_datetime(dt: PyDateTime) -> PyResult<Self> {
        let tzinfo = dt.tzinfo();
        if !tzinfo.is_none() {
            raise_value_err(format!("datetime must be naive, but got tzinfo={tzinfo}"))?
        }
        Ok(PlainDateTime {
            date: Date::from_stdlib_date(dt.date()),
            time: Time::from_stdlib_datetime(dt),
        })
    }
}

impl PyPayload for PlainDateTime {}

#[inline(never)]
fn __new__(cls: PyClass<PlainDateTime>, args: PyTuple, kwargs: Option<PyDict>) -> PyReturn {
    if args.len() == 1 && kwargs.map_or(0, |d| d.len()) == 0 {
        let arg = args.iter().next().unwrap();
        if PyStr::isinstance(arg) {
            return parse_iso(cls, arg);
        }
        if let Some(dt) = arg.cast_allow_subclass::<PyDateTime>() {
            return PlainDateTime::from_stdlib_datetime(dt)?.to_obj(cls);
        }
        return raise_type_err("PlainDateTime() requires an ISO 8601 string or datetime.datetime");
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

    Date::from_longs(year, month, day)
        .ok_or_value_err("invalid date")?
        .at(Time::from_longs(hour, minute, second, nanosecond).ok_or_value_err("invalid time")?)
        .to_obj(cls)
}

fn __repr__(_: PyType, slf: PlainDateTime) -> PyReturn {
    let PlainDateTime { date, time } = slf;
    PyAsciiStrBuilder::format((
        b"PlainDateTime(\"",
        date.iso_format(false),
        b' ',
        time.iso_format(fmt::Precision::Auto, false),
        b"\")",
    ))
}

fn __str__(_: PyType, slf: PlainDateTime) -> PyReturn {
    format!("{slf}").to_py()
}

fn format_iso(
    cls: PyClass<PlainDateTime>,
    slf: PlainDateTime,
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

fn parse_iso(cls: PyClass<PlainDateTime>, arg: PyObj) -> PyReturn {
    PlainDateTime::parse(
        arg.cast_allow_subclass::<PyStr>()
            // NOTE: this exception message also needs to make sense when
            // called through the constructor
            .ok_or_type_err("when parsing from ISO format, the argument must be str")?
            .as_utf8()?,
    )
    .ok_or_else_value_err(|| format!("Invalid format: {arg}"))?
    .to_obj(cls)
}

fn __richcmp__(
    cls: PyClass<PlainDateTime>,
    slf: PlainDateTime,
    other: PyObj,
    op: c_int,
) -> PyReturn {
    if let Some(dt) = other.extract(cls) {
        CompareOp::from_ffi(op).apply(slf, dt).to_py()
    } else {
        not_implemented()
    }
}

extern "C" fn __hash__(slf: PyObj) -> Py_hash_t {
    // SAFETY: self type is always passed to __hash__
    let (_, PlainDateTime { date, time }) = unsafe { slf.assume_heaptype() };
    hashmask(hash_combine(
        date.python_hash() as Py_hash_t,
        time.python_hash(),
    ))
}

fn __add__(a: PyObj, b: PyObj) -> PyReturn {
    shift_operator(a, b, false)
}

fn __sub__(a: PyObj, b: PyObj) -> PyReturn {
    shift_operator(a, b, true)
}

#[inline(never)]
fn shift_operator(obj_a: PyObj, obj_b: PyObj, negate: bool) -> PyReturn {
    binary_operation::<PlainDateTime>(obj_a, obj_b, if negate { "-" } else { "+" }, |operands| {
        let (cls, slf, other) = match operands {
            BinaryCall::SameType { cls, slf, other } if negate => {
                let state = cls.state();
                warn_with_class(*state.warn_naive_arithmetic, doc::PLAIN_DIFF_UNAWARE_MSG, 1)?;
                return Ok(Some(
                    slf.assume_utc()
                        .diff(other.assume_utc())
                        .to_obj(*state.time_delta_type)?,
                ));
            }
            BinaryCall::SameType { .. } => return Ok(None),
            BinaryCall::ExtTypes { cls, slf, other } => (cls, slf, other),
            BinaryCall::OtherTypes => return Ok(None),
        };
        let state = cls.state();

        let result = if let Some(DateDelta {
            mut months,
            mut days,
        }) = other.extract(*state.date_delta_type)
        {
            months = months.negate_if(negate);
            days = days.negate_if(negate);
            slf.shift_date(months, days).ok_or_range_err()?
        } else if let Some(tdelta) = other.extract(*state.time_delta_type) {
            warn_with_class(
                *state.warn_naive_arithmetic,
                doc::PLAIN_SHIFT_UNAWARE_MSG,
                1,
            )?;
            slf.shift(tdelta.negate_if(negate)).ok_or_range_err()?
        } else if let Some(dt) = other.extract(*state.datetime_delta_type) {
            let mut months = dt.date.months;
            let mut days = dt.date.days;
            let mut tdelta = dt.time;
            if negate {
                months = -months;
                days = -days;
                tdelta = -tdelta;
            }
            if !tdelta.is_zero() {
                warn_with_class(
                    *state.warn_naive_arithmetic,
                    doc::PLAIN_SHIFT_UNAWARE_MSG,
                    1,
                )?;
            }
            slf.shift_date(months, days)
                .and_then(|dt| dt.shift(tdelta))
                .ok_or_range_err()?
        } else {
            return Ok(None);
        };
        Ok(Some(result.to_obj(slf.class())?))
    })
}

#[allow(static_mut_refs)]
static mut SLOTS: &[PyType_Slot] = &[
    slotmethod!(PlainDateTime, Py_tp_new, __new__),
    slotmethod!(PlainDateTime, Py_tp_repr, __repr__, 1),
    slotmethod!(PlainDateTime, Py_tp_str, __str__, 1),
    slotmethod!(PlainDateTime, Py_tp_richcompare, __richcmp__),
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

pub(crate) struct DateTimeComponents {
    year: c_long,
    month: c_long,
    day: c_long,
    hour: c_long,
    minute: c_long,
    second: c_long,
    nanosecond: c_long,
}

impl PlainDateTime {
    pub(crate) fn components(self) -> DateTimeComponents {
        DateTimeComponents {
            year: self.date.year.get().into(),
            month: self.date.month.get().into(),
            day: self.date.day.into(),
            hour: self.time.hour.into(),
            minute: self.time.minute.into(),
            second: self.time.second.into(),
            nanosecond: self.time.subsec.get().into(),
        }
    }
}

impl DateTimeComponents {
    #[inline]
    pub(crate) fn set_from_kwarg(
        &mut self,
        key: PyObj,
        value: PyObj,
        state: &State,
        eq: StrEqFn,
    ) -> PyResult<bool> {
        if eq(key, *state.str_year) {
            self.year = value.expect_int("year")?.to_long()?;
        } else if eq(key, *state.str_month) {
            self.month = value.expect_int("month")?.to_long()?;
        } else if eq(key, *state.str_day) {
            self.day = value.expect_int("day")?.to_long()?;
        } else if eq(key, *state.str_hour) {
            self.hour = value.expect_int("hour")?.to_long()?;
        } else if eq(key, *state.str_minute) {
            self.minute = value.expect_int("minute")?.to_long()?;
        } else if eq(key, *state.str_second) {
            self.second = value.expect_int("second")?.to_long()?;
        } else if eq(key, *state.str_nanosecond) {
            self.nanosecond = value.expect_int("nanosecond")?.to_long()?;
        } else {
            return Ok(false);
        }
        Ok(true)
    }

    pub(crate) fn into_plain(self) -> PyResult<PlainDateTime> {
        Ok(PlainDateTime {
            date: Date::from_longs(self.year, self.month, self.day)
                .ok_or_value_err("invalid date")?,
            time: Time::from_longs(self.hour, self.minute, self.second, self.nanosecond)
                .ok_or_value_err("invalid time")?,
        })
    }
}

fn replace(
    cls: PyClass<PlainDateTime>,
    slf: PlainDateTime,
    args: &[PyObj],
    kwargs: &mut IterKwargs,
) -> PyReturn {
    if !args.is_empty() {
        raise_type_err("replace() takes no positional arguments")?
    }
    let state = cls.state();
    let mut components = slf.components();
    handle_kwargs("replace", kwargs, |k, v, eq| {
        components.set_from_kwarg(k, v, state, eq)
    })?;
    components.into_plain()?.to_obj(cls)
}

fn add(
    cls: PyClass<PlainDateTime>,
    slf: PlainDateTime,
    args: &[PyObj],
    kwargs: &mut IterKwargs,
) -> PyReturn {
    shift_method(cls, slf, args, kwargs, false)
}

fn subtract(
    cls: PyClass<PlainDateTime>,
    slf: PlainDateTime,
    args: &[PyObj],
    kwargs: &mut IterKwargs,
) -> PyReturn {
    shift_method(cls, slf, args, kwargs, true)
}

#[inline(never)]
fn shift_method(
    cls: PyClass<PlainDateTime>,
    slf: PlainDateTime,
    args: &[PyObj],
    kwargs: &mut IterKwargs,
    negate: bool,
) -> PyReturn {
    let fname = if negate { "subtract" } else { "add" };
    let state = cls.state();
    let mut got_ignore_dst = false;
    let mut suppress_unaware = false;

    let shift = match *args {
        [arg] => {
            for (key, value) in kwargs.by_ref() {
                if unicode_eq(key, *state.str_ignore_dst) {
                    got_ignore_dst = true;
                } else if unicode_eq(key, *state.str_naive_arithmetic_ok) {
                    suppress_unaware = value.is_truthy()?;
                } else {
                    raise_type_err(format!(
                        "{fname}() can't mix positional and keyword arguments"
                    ))?;
                }
            }
            parse_datetime_shift_arg(fname, arg, state)?
        }
        [] => parse_datetime_shift_kwargs(fname, kwargs, state, |k, v, eq| {
            if eq(k, *state.str_ignore_dst) {
                got_ignore_dst = true;
                Ok(true)
            } else if eq(k, *state.str_naive_arithmetic_ok) {
                suppress_unaware = v.is_truthy()?;
                Ok(true)
            } else {
                Ok(false)
            }
        })?,
        _ => raise_type_err(format!(
            "{}() takes at most 1 positional argument, got {}",
            fname,
            args.len()
        ))?,
    };

    if got_ignore_dst {
        warn_with_class(*state.warn_deprecation, doc::IGNORE_DST_DEPRECATED_MSG, 1)?;
    }

    let shift = shift.negate_if(negate);

    if !shift.time.is_zero() && !suppress_unaware {
        warn_with_class(
            *state.warn_naive_arithmetic,
            doc::PLAIN_SHIFT_UNAWARE_MSG,
            1,
        )?;
    }
    slf.shift_by(shift).ok_or_range_err()?.to_obj(cls)
}

fn difference(
    cls: PyClass<PlainDateTime>,
    slf: PlainDateTime,
    args: &[PyObj],
    kwargs: &mut IterKwargs,
) -> PyReturn {
    let state = cls.state();
    let mut suppress_unaware = false;
    // Accept deprecated ignore_dst kwarg and new naive_arithmetic_ok kwarg
    for (key, value) in kwargs.by_ref() {
        if unicode_eq(key, *state.str_ignore_dst) {
            warn_with_class(*state.warn_deprecation, doc::IGNORE_DST_DEPRECATED_MSG, 1)?;
        } else if unicode_eq(key, *state.str_naive_arithmetic_ok) {
            suppress_unaware = value.is_truthy()?;
        } else {
            raise_type_err(format!("Unknown keyword argument: {key}"))?;
        }
    }
    let [arg] = *args else {
        raise_type_err("difference() takes exactly 1 argument")?
    };
    if let Some(dt) = arg.extract(cls) {
        if !suppress_unaware {
            warn_with_class(*state.warn_naive_arithmetic, doc::PLAIN_DIFF_UNAWARE_MSG, 1)?;
        }
        slf.assume_utc()
            .diff(dt.assume_utc())
            .to_obj(*state.time_delta_type)
    } else {
        raise_type_err("difference() argument must be a PlainDateTime")?
    }
}

fn __reduce__(cls: PyClass<PlainDateTime>, slf: PlainDateTime) -> PyReturn {
    let data = pickle::encode_plain(slf);
    [
        cls.state().unpickle_plain_datetime.newref(),
        [data.to_py()?].into_pytuple()?,
    ]
    .into_pytuple()
}

pub(crate) fn unpickle(state: &State, arg: PyObj) -> PyReturn {
    pickle::decode_plain(arg.expect_bytes()?)
        .ok_or_type_err(pickle::INVALID_DATA)?
        .to_obj(*state.plain_datetime_type)
}

fn from_py_datetime(cls: PyClass<PlainDateTime>, arg: PyObj) -> PyReturn {
    warn_with_class(
        *cls.state().warn_deprecation,
        c"from_py_datetime() is deprecated. Use PlainDateTime() constructor instead.",
        1,
    )?;
    let Some(dt) = arg.cast_allow_subclass::<PyDateTime>() else {
        raise_type_err("argument must be datetime.datetime")?
    };
    PlainDateTime::from_stdlib_datetime(dt)?.to_obj(cls)
}

fn to_stdlib(cls: PyClass<PlainDateTime>, slf: PlainDateTime) -> PyReturn {
    slf.to_stdlib_datetime(cls.state().py_api()?)
}

fn py_datetime(cls: PyClass<PlainDateTime>, slf: PlainDateTime) -> PyReturn {
    let state = cls.state();
    warn_with_class(
        *state.warn_deprecation,
        c"py_datetime() is deprecated. Use to_stdlib() instead.",
        1,
    )?;
    to_stdlib(cls, slf)
}

fn date(cls: PyClass<PlainDateTime>, slf: PlainDateTime) -> PyReturn {
    slf.date.to_obj(*cls.state().date_type)
}

fn time(cls: PyClass<PlainDateTime>, slf: PlainDateTime) -> PyReturn {
    slf.time.to_obj(*cls.state().time_type)
}

fn day_of_year(_: PyClass<PlainDateTime>, slf: PlainDateTime) -> PyReturn {
    slf.date.day_of_year().to_py()
}

fn days_in_month(_: PyClass<PlainDateTime>, slf: PlainDateTime) -> PyReturn {
    slf.date.days_in_month().to_py()
}

fn days_in_year(_: PyClass<PlainDateTime>, slf: PlainDateTime) -> PyReturn {
    slf.date.days_in_year().to_py()
}

fn in_leap_year(_: PyClass<PlainDateTime>, slf: PlainDateTime) -> PyReturn {
    slf.date.is_in_leap_year().to_py()
}

fn start_of(cls: PyClass<PlainDateTime>, slf: PlainDateTime, unit_obj: PyObj) -> PyReturn {
    slf.start_of_unit(DateTimeBoundaryUnit::from_py(unit_obj, cls.state())?)
        .ok_or_range_err()?
        .to_obj(cls)
}

fn end_of(cls: PyClass<PlainDateTime>, slf: PlainDateTime, unit_obj: PyObj) -> PyReturn {
    slf.end_of_unit(DateTimeBoundaryUnit::from_py(unit_obj, cls.state())?)
        .ok_or_range_err()?
        .to_obj(cls)
}

fn parse_strptime(
    cls: PyClass<PlainDateTime>,
    args: &[PyObj],
    kwargs: &mut IterKwargs,
) -> PyReturn {
    let state = cls.state();
    warn_with_class(
        *state.warn_deprecation,
        c"parse_strptime() is deprecated; use parse() with a format pattern instead.",
        1,
    )?;
    let format_obj = match kwargs.next() {
        Some((key, value)) if kwargs.len() == 1 && unicode_eq(key, *state.str_format) => value,
        _ => raise_type_err("parse_strptime() requires exactly one keyword argument `format`")?,
    };
    let &[arg_obj] = args else {
        raise_type_err(format!(
            "parse_strptime() takes exactly 1 positional argument, got {}",
            args.len()
        ))?
    };

    let parsed = state
        .strptime
        .get()?
        .call_args([arg_obj, format_obj])?
        .cast_exact::<PyDateTime>()
        .ok_or_type_err("strptime() returned non-datetime")?;

    PlainDateTime::from_stdlib_datetime(*parsed)?.to_obj(cls)
}

fn assume_utc(cls: PyClass<PlainDateTime>, d: PlainDateTime) -> PyReturn {
    d.assume_utc().to_obj(*cls.state().instant_type)
}

fn assume_fixed_offset(cls: PyClass<PlainDateTime>, slf: PlainDateTime, arg: PyObj) -> PyReturn {
    let state = cls.state();
    slf.assume_offset(Offset::from_py(arg, *state.time_delta_type)?)
        .ok_or_range_err()?
        .to_obj(*state.offset_datetime_type)
}

fn assume_tz(
    cls: PyClass<PlainDateTime>,
    slf: PlainDateTime,
    args: &[PyObj],
    kwargs: &mut IterKwargs,
) -> PyReturn {
    let state = cls.state();
    let &[tz_obj] = args else {
        raise_type_err(format!(
            "assume_tz() takes 1 positional argument but {} were given",
            args.len()
        ))?
    };

    let dis = Disambiguation::from_only_kwarg(kwargs, "assume_tz", state)?
        .unwrap_or(Disambiguation::Compatible);
    let tz = state.tz_store.obj_get(tz_obj)?;
    slf.resolve_or_raise(&tz, ResolvePolicy::Disambiguate(dis), state)?
        .into_zoned_obj_unchecked(tz, *state.zoned_datetime_type)
}

fn assume_system_tz(
    cls: PyClass<PlainDateTime>,
    slf: PlainDateTime,
    args: &[PyObj],
    kwargs: &mut IterKwargs,
) -> PyReturn {
    let state = cls.state();
    if !args.is_empty() {
        raise_type_err("assume_system_tz() takes no positional arguments")?
    }

    let dis = Disambiguation::from_only_kwarg(kwargs, "assume_tz", state)?
        .unwrap_or(Disambiguation::Compatible);
    let tz = state.tz_store.get_system_tz()?;
    slf.resolve_or_raise(&tz, ResolvePolicy::Disambiguate(dis), state)?
        .into_zoned_obj_unchecked(tz, *state.zoned_datetime_type)
}

fn replace_date(cls: PyClass<PlainDateTime>, slf: PlainDateTime, arg: PyObj) -> PyReturn {
    let Some(date) = arg.extract(*cls.state().date_type) else {
        raise_type_err("argument must be a whenever.Date")?
    };
    slf.with_date(date).to_obj(cls)
}

fn replace_time(cls: PyClass<PlainDateTime>, slf: PlainDateTime, arg: PyObj) -> PyReturn {
    let Some(time) = arg.extract(*cls.state().time_type) else {
        raise_type_err("argument must be a whenever.Time")?
    };
    slf.with_time(time).to_obj(cls)
}

fn since(
    cls: PyClass<PlainDateTime>,
    slf: PlainDateTime,
    args: &[PyObj],
    kwargs: &mut IterKwargs,
) -> PyReturn {
    plain_since(cls, slf, args, kwargs, false)
}

fn until(
    cls: PyClass<PlainDateTime>,
    slf: PlainDateTime,
    args: &[PyObj],
    kwargs: &mut IterKwargs,
) -> PyReturn {
    plain_since(cls, slf, args, kwargs, true)
}

#[inline(never)]
fn plain_since(
    cls: PyClass<PlainDateTime>,
    slf: PlainDateTime,
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
    let mut got_ignore_dst = false;
    let since_kwargs = DifferenceSpec::parse_with(fname, kwargs, state, |key, value, eq| {
        if eq(key, *state.str_naive_arithmetic_ok) {
            suppress_unaware = value.is_truthy()?;
            Ok(true)
        } else if eq(key, *state.str_ignore_dst) {
            got_ignore_dst = true;
            Ok(true)
        } else {
            Ok(false)
        }
    })?;

    if got_ignore_dst {
        warn_with_class(*state.warn_deprecation, doc::IGNORE_DST_DEPRECATED_MSG, 1)?;
    }

    // Warn only when the output contains exact time units (hours/min/sec/ns).
    // Calendar-only output (years/months/weeks/days) doesn't involve clock time,
    // so there's no DST ambiguity in that case.
    if since_kwargs.has_exact_output() && !suppress_unaware {
        warn_with_class(*state.warn_naive_arithmetic, doc::PLAIN_DIFF_UNAWARE_MSG, 1)?;
    }

    plain_since_inner(state, slf, other, since_kwargs, flip)
}

/// Resolve a non-ZonedDateTime `relative_to` argument to a `PlainDateTime`,
/// emitting the appropriate warning if the condition is met.
///
/// If `warn` is true, emit the warning appropriate to the argument type.
///
/// The caller is responsible for handling the ZonedDateTime case before calling
/// this function (which always returns `Err` for ZonedDateTime args).
pub(crate) fn resolve_local_relative_to(
    arg: PyObj,
    state: &State,
    warn: bool,
) -> PyResult<PlainDateTime> {
    if let Some(pdt) = arg.extract(*state.plain_datetime_type) {
        if warn {
            warn_with_class(
                *state.warn_naive_arithmetic,
                doc::PLAIN_RELATIVE_TO_UNAWARE_MSG,
                1,
            )?;
        }
        Ok(pdt)
    } else if let Some(odt) = arg.extract(*state.offset_datetime_type) {
        if warn {
            warn_with_class(
                *state.warn_potentially_stale_offset,
                doc::STALE_OFFSET_CALENDAR_MSG,
                1,
            )?;
        }
        Ok(odt.to_plain())
    } else {
        raise_type_err("relative_to must be a ZonedDateTime, PlainDateTime, or OffsetDateTime")
    }
}

pub(crate) fn plain_since_float(
    a: PlainDateTime,
    b: PlainDateTime,
    target_date: Date,
    unit: DifferenceUnit,
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
        Err(calendar_unit) => {
            total_calendar_plain(neg, calendar_unit, a.assume_utc(), b, target_date)
        }
    }
}

/// Calendar-unit fractional total for PlainDateTime/OffsetDateTime, treating
/// the reference datetime as UTC (no DST transitions).
///
/// This mirrors `zoned_datetime::total_calendar` but works with raw `Instant` and
/// `PlainDateTime` values instead of `ZonedDateTime`, avoiding the need for a UTC
/// timezone object.
pub(crate) fn total_calendar_plain(
    neg: bool,
    unit: difference::CalendarUnit,
    a_inst: Instant,
    b_dt: PlainDateTime,
    target_date: Date,
) -> PyReturn {
    let (result, trunc_raw, expand_raw) = difference::date_diff_single_unit(
        target_date,
        b_dt.date,
        CalendarIncrement::MIN,
        unit,
        neg,
    )
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
    slf: PlainDateTime,
    other: PlainDateTime,
    kwargs: DifferenceSpec,
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
        DifferenceSpec::Total(unit) => plain_since_float(a, b, target_date, unit, neg),
        DifferenceSpec::InUnits {
            units,
            mode,
            increment,
        } => plain_since_in_units(state, a, b, target_date, units, mode, increment, neg),
    }
}

#[inline(never)]
#[allow(clippy::too_many_arguments)]
fn plain_since_in_units(
    state: &State,
    a: PlainDateTime,
    b: PlainDateTime,
    target_date: Date,
    units: DifferenceUnitSet,
    round_mode: round::Mode,
    round_increment: difference::DifferenceIncrement,
    neg: bool,
) -> PyReturn {
    let smallest_unit = units.smallest();
    let (calendar_units, exact_units) = units.split_calendar_exact();

    let (mut calendar_results, trunc_date, expand_date) = if calendar_units.is_empty() {
        (ItemizedDateDelta::UNSET, b.date.into(), a.date.into())
    } else {
        let inc = if smallest_unit.to_exact(false).is_err() {
            round_increment.to_calendar().ok_or_range_err()?
        } else {
            CalendarIncrement::MIN
        };
        difference::date_diff(target_date, b.date, inc, calendar_units, neg).ok_or_range_err()?
    };

    let trunc_dt = b.with_date(trunc_date.into());
    let expand_dt = b.with_date(expand_date.into());

    // If there are no time units, round the calendar units.
    // Otherwise, calculate the time delta remainder
    let mut result = if exact_units.is_empty() {
        calendar_results.round_by_time(
            calendar_units.smallest(),
            // This UTC conversion is a bit weird, but it allows us to reuse
            // the logic since plain and UTC datetimes both have no timezone
            // adjustments.
            a.assume_utc(),
            trunc_dt.assume_utc(),
            expand_dt.assume_utc(),
            round_mode.to_abs_trunc(neg),
            round_increment.to_calendar().ok_or_range_err()?,
            neg,
        );
        ItemizedDelta::UNSET
    } else {
        a.diff(trunc_dt)
            .in_exact_units(exact_units, round_increment, round_mode.to_abs_euclid(neg))
            .ok_or_range_err()?
    };

    result.fill_calendar_units(calendar_results);
    result.to_obj(state)
}

fn round(
    cls: PyClass<PlainDateTime>,
    slf: PlainDateTime,
    args: &[PyObj],
    kwargs: &mut IterKwargs,
) -> PyReturn {
    let round::Args {
        increment, mode, ..
    } = round::Args::parse(args, kwargs, cls.state(), round::ArgsContext::Standard)?;
    let round_nanos = match increment {
        round::RoundIncrement::Day => NS_PER_DAY,
        round::RoundIncrement::Exact(ns) => ns.get(),
    };
    let PlainDateTime { mut date, time } = slf;
    let (time_rounded, next_day) = time.round(round_nanos, mode);
    if next_day == 1 {
        date = date.tomorrow().ok_or_range_err()?;
    }
    slf.with_date(date).with_time(time_rounded).to_obj(cls)
}

fn format(_cls: PyClass<PlainDateTime>, slf: PlainDateTime, pattern_obj: PyObj) -> PyReturn {
    let pattern_pystr = pattern_obj
        .cast_exact::<PyStr>()
        .ok_or_type_err("format() argument must be str")?;
    let pattern_str = pattern_pystr.as_utf8()?;
    let pattern = pattern::CompiledPattern::compile(pattern_str).into_value_err()?;
    pattern.validate(pattern::CategorySet::DATE_TIME, "PlainDateTime")?;
    pattern.warn_if_ambiguous_12h()?;
    pattern.format(&slf.pattern_values())
}

fn __format__(cls: PyClass<PlainDateTime>, slf: PlainDateTime, spec_obj: PyObj) -> PyReturn {
    if spec_obj.is_truthy()? {
        format(cls, slf, spec_obj)
    } else {
        __str__(cls.into(), slf)
    }
}

fn parse(cls: PyClass<PlainDateTime>, args: &[PyObj], kwargs: &mut IterKwargs) -> PyReturn {
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

    let pattern = pattern::CompiledPattern::compile(fmt_bytes).into_value_err()?;
    pattern.validate(pattern::CategorySet::DATE_TIME, "PlainDateTime")?;
    let parsed = pattern.parse(s).into_value_err()?;
    let date = parsed
        .date("Pattern must include year (YYYY/YY), month (MM/MMM/MMMM), and day (DD) fields")?;
    parsed.validate_weekday(date)?;
    date.at(parsed.time()?).to_obj(cls)
}

static mut METHODS: &[PyMethodDef] = &[
    COPY_METHOD,
    DEEPCOPY_METHOD,
    method0!(PlainDateTime, __reduce__, c""),
    classmethod1!(
        PlainDateTime,
        from_py_datetime,
        doc::BASICCONVERSIONS_FROM_PY_DATETIME
    ),
    method0!(PlainDateTime, to_stdlib, doc::BASICCONVERSIONS_TO_STDLIB),
    method0!(
        PlainDateTime,
        py_datetime,
        doc::BASICCONVERSIONS_PY_DATETIME
    ),
    method0!(PlainDateTime, date, doc::LOCALTIME_DATE),
    method0!(PlainDateTime, time, doc::LOCALTIME_TIME),
    method0!(PlainDateTime, day_of_year, doc::LOCALTIME_DAY_OF_YEAR),
    method0!(PlainDateTime, days_in_month, doc::LOCALTIME_DAYS_IN_MONTH),
    method0!(PlainDateTime, days_in_year, doc::LOCALTIME_DAYS_IN_YEAR),
    method0!(PlainDateTime, in_leap_year, doc::LOCALTIME_IN_LEAP_YEAR),
    method1!(PlainDateTime, start_of, doc::PLAINDATETIME_START_OF),
    method1!(PlainDateTime, end_of, doc::PLAINDATETIME_END_OF),
    method_kwargs!(PlainDateTime, format_iso, doc::PLAINDATETIME_FORMAT_ISO),
    classmethod1!(PlainDateTime, parse_iso, doc::PLAINDATETIME_PARSE_ISO),
    classmethod_kwargs!(
        PlainDateTime,
        parse_strptime,
        doc::PLAINDATETIME_PARSE_STRPTIME
    ),
    method_kwargs!(PlainDateTime, replace, doc::PLAINDATETIME_REPLACE),
    method0!(PlainDateTime, assume_utc, doc::PLAINDATETIME_ASSUME_UTC),
    method1!(
        PlainDateTime,
        assume_fixed_offset,
        doc::PLAINDATETIME_ASSUME_FIXED_OFFSET
    ),
    method_kwargs!(PlainDateTime, assume_tz, doc::PLAINDATETIME_ASSUME_TZ),
    method_kwargs!(
        PlainDateTime,
        assume_system_tz,
        doc::PLAINDATETIME_ASSUME_SYSTEM_TZ
    ),
    method1!(PlainDateTime, replace_date, doc::PLAINDATETIME_REPLACE_DATE),
    method1!(PlainDateTime, replace_time, doc::PLAINDATETIME_REPLACE_TIME),
    method_kwargs!(PlainDateTime, add, doc::PLAINDATETIME_ADD),
    method_kwargs!(PlainDateTime, subtract, doc::PLAINDATETIME_SUBTRACT),
    method_kwargs!(PlainDateTime, difference, doc::PLAINDATETIME_DIFFERENCE),
    method_kwargs!(PlainDateTime, since, doc::PLAINDATETIME_SINCE),
    method_kwargs!(PlainDateTime, until, doc::PLAINDATETIME_UNTIL),
    method_kwargs!(PlainDateTime, round, doc::PLAINDATETIME_ROUND),
    method1!(PlainDateTime, format, doc::PLAINDATETIME_FORMAT),
    method1!(PlainDateTime, __format__, c""),
    classmethod_kwargs!(PlainDateTime, parse, doc::PLAINDATETIME_PARSE),
    classmethod_kwargs!(
        PlainDateTime,
        __get_pydantic_core_schema__,
        doc::PYDANTIC_SCHEMA
    ),
    PyMethodDef::zeroed(),
];

fn year(_: PyType, slf: PlainDateTime) -> PyReturn {
    slf.date.year.get().to_py()
}

fn month(_: PyType, slf: PlainDateTime) -> PyReturn {
    slf.date.month.get().to_py()
}

fn day(_: PyType, slf: PlainDateTime) -> PyReturn {
    slf.date.day.to_py()
}

fn hour(_: PyType, slf: PlainDateTime) -> PyReturn {
    slf.time.hour.to_py()
}

fn minute(_: PyType, slf: PlainDateTime) -> PyReturn {
    slf.time.minute.to_py()
}

fn second(_: PyType, slf: PlainDateTime) -> PyReturn {
    slf.time.second.to_py()
}

fn nanosecond(_: PyType, slf: PlainDateTime) -> PyReturn {
    slf.time.subsec.get().to_py()
}

static mut GETSETTERS: &[PyGetSetDef] = &[
    getter!(PlainDateTime, year, doc::LOCALTIME_YEAR),
    getter!(PlainDateTime, month, doc::LOCALTIME_MONTH),
    getter!(PlainDateTime, day, doc::LOCALTIME_DAY),
    getter!(PlainDateTime, hour, doc::LOCALTIME_HOUR),
    getter!(PlainDateTime, minute, doc::LOCALTIME_MINUTE),
    getter!(PlainDateTime, second, doc::LOCALTIME_SECOND),
    getter!(PlainDateTime, nanosecond, doc::LOCALTIME_NANOSECOND),
    PyGetSetDef {
        name: NULL(),
        get: None,
        set: None,
        doc: NULL(),
        closure: NULL(),
    },
];

pub(crate) static mut SPEC: PyType_Spec =
    type_spec::<PlainDateTime>(c"whenever.PlainDateTime", unsafe { SLOTS });

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
                PlainDateTime::parse(str),
                Some(PlainDateTime {
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
        assert_eq!(PlainDateTime::parse(b"2023-03-02 02:09:09."), None);
        // too many fractions
        assert_eq!(
            PlainDateTime::parse(b"2023-03-02 02:09:09.1234567890"),
            None
        );
        // invalid minute
        assert_eq!(PlainDateTime::parse(b"2023-03-02 02:69:09.123456789"), None);
        // invalid date
        assert_eq!(PlainDateTime::parse(b"2023-02-29 02:29:09.123456789"), None);
    }

    #[test]
    fn test_change_offset() {
        let d = PlainDateTime {
            date: mkdate(2023, 3, 2),
            time: Time {
                hour: 2,
                minute: 9,
                second: 9,
                subsec: SubSecNanos::MIN,
            },
        };
        assert_eq!(d.shift_by_offset(OffsetDelta::ZERO).unwrap(), d);
        assert_eq!(
            d.shift_by_offset(OffsetDelta::new_unchecked(1)).unwrap(),
            PlainDateTime {
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
            d.shift_by_offset(OffsetDelta::new_unchecked(-1)).unwrap(),
            PlainDateTime {
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
            d.shift_by_offset(OffsetDelta::new_unchecked(86_400))
                .unwrap(),
            PlainDateTime {
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
            d.shift_by_offset(OffsetDelta::new_unchecked(-86_400))
                .unwrap(),
            PlainDateTime {
                date: mkdate(2023, 3, 1),
                time: Time {
                    hour: 2,
                    minute: 9,
                    second: 9,
                    subsec: SubSecNanos::MIN,
                }
            }
        );
        let midnight = PlainDateTime {
            date: mkdate(2023, 3, 2),
            time: Time {
                hour: 0,
                minute: 0,
                second: 0,
                subsec: SubSecNanos::MIN,
            },
        };
        assert_eq!(
            midnight.shift_by_offset(OffsetDelta::ZERO).unwrap(),
            midnight
        );
        assert_eq!(
            midnight
                .shift_by_offset(OffsetDelta::new_unchecked(-1))
                .unwrap(),
            PlainDateTime {
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
                .shift_by_offset(OffsetDelta::new_unchecked(-86_400))
                .unwrap(),
            PlainDateTime {
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
                .shift_by_offset(OffsetDelta::new_unchecked(-86_401))
                .unwrap(),
            PlainDateTime {
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
            PlainDateTime {
                date: mkdate(2023, 1, 1),
                time: Time {
                    hour: 0,
                    minute: 0,
                    second: 0,
                    subsec: SubSecNanos::MIN,
                }
            }
            .shift_by_offset(OffsetDelta::new_unchecked(-1))
            .unwrap(),
            PlainDateTime {
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
