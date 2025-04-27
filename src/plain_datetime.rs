use core::ffi::{c_int, c_long, c_void, CStr};
use core::ptr::null_mut as NULL;
use pyo3_ffi::*;

use crate::{
    common::{math::*, *},
    date::Date,
    date_delta::DateDelta,
    datetime_delta::{set_units_from_kwargs, DateTimeDelta},
    docstrings as doc,
    instant::Instant,
    offset_datetime::{self, check_ignore_dst_kwarg, OffsetDateTime},
    parse::Scan,
    round,
    time::Time,
    time_delta::TimeDelta,
    zoned_datetime::ZonedDateTime,
    State,
};

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
    pub(crate) fn shift_date(self, months: DeltaMonths, days: DeltaDays) -> Option<Self> {
        let DateTime { date, time } = self;
        date.shift(months, days).map(|date| DateTime { date, time })
    }

    pub(crate) fn shift_nanos(self, nanos: i128) -> Option<Self> {
        let DateTime { mut date, time } = self;
        let new_time = i128::from(time.total_nanos()).checked_add(nanos)?;
        let days_delta = i32::try_from(new_time.div_euclid(NS_PER_DAY)).ok()?;
        let nano_delta = new_time.rem_euclid(NS_PER_DAY) as u64;
        if days_delta != 0 {
            date = DeltaDays::new(days_delta).and_then(|d| date.shift_days(d))?;
        }
        Some(DateTime {
            date,
            time: Time::from_total_nanos_unchecked(nano_delta),
        })
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
}

impl PyWrapped for DateTime {}

impl std::fmt::Display for DateTime {
    fn fmt(&self, f: &mut std::fmt::Formatter) -> std::fmt::Result {
        write!(f, "{}T{}", self.date, self.time)
    }
}

unsafe fn __new__(cls: *mut PyTypeObject, args: *mut PyObject, kwargs: *mut PyObject) -> PyReturn {
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
        date: Date::from_longs(year, month, day).ok_or_type_err("Invalid date")?,
        time: Time::from_longs(hour, minute, second, nanosecond).ok_or_type_err("Invalid time")?,
    }
    .to_obj(cls)
}

unsafe fn __repr__(slf: *mut PyObject) -> PyReturn {
    let DateTime { date, time } = DateTime::extract(slf);
    format!("PlainDateTime({} {})", date, time).to_py()
}

unsafe fn __str__(slf: *mut PyObject) -> PyReturn {
    format!("{}", DateTime::extract(slf)).to_py()
}

unsafe fn format_common_iso(slf: *mut PyObject, _: *mut PyObject) -> PyReturn {
    __str__(slf)
}

unsafe fn __richcmp__(a_obj: *mut PyObject, b_obj: *mut PyObject, op: c_int) -> PyReturn {
    Ok(if Py_TYPE(b_obj) == Py_TYPE(a_obj) {
        let a = DateTime::extract(a_obj);
        let b = DateTime::extract(b_obj);
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

unsafe extern "C" fn __hash__(slf: *mut PyObject) -> Py_hash_t {
    let DateTime { date, time } = DateTime::extract(slf);
    hashmask(hash_combine(date.hash() as Py_hash_t, time.pyhash()))
}

unsafe fn __add__(obj_a: *mut PyObject, obj_b: *mut PyObject) -> PyReturn {
    _shift_operator(obj_a, obj_b, false)
}

unsafe fn __sub__(obj_a: *mut PyObject, obj_b: *mut PyObject) -> PyReturn {
    // easy case: subtracting two PlainDateTime objects
    if Py_TYPE(obj_a) == Py_TYPE(obj_b) {
        raise(
            State::for_obj(obj_a).exc_implicitly_ignoring_dst,
            doc::DIFF_OPERATOR_LOCAL_MSG,
        )?
    } else {
        _shift_operator(obj_a, obj_b, true)
    }
}

#[inline]
unsafe fn _shift_operator(obj_a: *mut PyObject, obj_b: *mut PyObject, negate: bool) -> PyReturn {
    let opname = if negate { "-" } else { "+" };
    let type_b = Py_TYPE(obj_b);
    let type_a = Py_TYPE(obj_a);

    let mod_a = PyType_GetModule(type_a);
    let mod_b = PyType_GetModule(type_b);

    if mod_a == mod_b {
        let state = State::for_mod(mod_a);
        if type_b == state.date_delta_type {
            let DateDelta {
                mut months,
                mut days,
            } = DateDelta::extract(obj_b);
            debug_assert_eq!(type_a, state.plain_datetime_type);
            let dt = DateTime::extract(obj_a);
            if negate {
                months = -months;
                days = -days;
            }
            dt.shift_date(months, days)
                .ok_or_else_value_err(|| format!("Result of {} out of range", opname))?
                .to_obj(type_a)
        } else if type_b == state.datetime_delta_type || type_b == state.time_delta_type {
            raise(state.exc_implicitly_ignoring_dst, doc::SHIFT_LOCAL_MSG)?
        } else {
            raise_type_err(format!(
                "unsupported operand type(s) for {}: 'PlainDateTime' and {}",
                opname,
                type_b.cast::<PyObject>().repr()
            ))?
        }
    } else {
        Ok(newref(Py_NotImplemented()))
    }
}

#[allow(static_mut_refs)]
static mut SLOTS: &[PyType_Slot] = &[
    slotmethod!(Py_tp_new, __new__),
    slotmethod!(Py_tp_repr, __repr__, 1),
    slotmethod!(Py_tp_str, __str__, 1),
    slotmethod!(Py_tp_richcompare, __richcmp__),
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
pub(crate) unsafe fn set_components_from_kwargs(
    key: *mut PyObject,
    value: *mut PyObject,
    year: &mut c_long,
    month: &mut c_long,
    day: &mut c_long,
    hour: &mut c_long,
    minute: &mut c_long,
    second: &mut c_long,
    nanos: &mut c_long,
    str_year: *mut PyObject,
    str_month: *mut PyObject,
    str_day: *mut PyObject,
    str_hour: *mut PyObject,
    str_minute: *mut PyObject,
    str_second: *mut PyObject,
    str_nanosecond: *mut PyObject,
    eq: fn(*mut PyObject, *mut PyObject) -> bool,
) -> PyResult<bool> {
    if eq(key, str_year) {
        *year = value.to_long()?.ok_or_type_err("year must be an integer")?
    } else if eq(key, str_month) {
        *month = value
            .to_long()?
            .ok_or_type_err("month must be an integer")?
    } else if eq(key, str_day) {
        *day = value.to_long()?.ok_or_type_err("day must be an integer")?
    } else if eq(key, str_hour) {
        *hour = value.to_long()?.ok_or_type_err("hour must be an integer")?
    } else if eq(key, str_minute) {
        *minute = value
            .to_long()?
            .ok_or_type_err("minute must be an integer")?
    } else if eq(key, str_second) {
        *second = value
            .to_long()?
            .ok_or_type_err("second must be an integer")?
    } else if eq(key, str_nanosecond) {
        *nanos = value
            .to_long()?
            .ok_or_type_err("nanosecond must be an integer")?
    } else {
        return Ok(false);
    }
    Ok(true)
}

unsafe fn replace(
    slf: *mut PyObject,
    cls: *mut PyTypeObject,
    args: &[*mut PyObject],
    kwargs: &mut KwargIter,
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
    } = State::for_type(cls);
    let dt = DateTime::extract(slf);
    let mut year = dt.date.year.get().into();
    let mut month = dt.date.month.get().into();
    let mut day = dt.date.day.into();
    let mut hour = dt.time.hour.into();
    let mut minute = dt.time.minute.into();
    let mut second = dt.time.second.into();
    let mut nanos = dt.time.subsec.get() as _;
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
        date: Date::from_longs(year, month, day).ok_or_value_err("Invalid date")?,
        time: Time::from_longs(hour, minute, second, nanos).ok_or_value_err("Invalid time")?,
    }
    .to_obj(cls)
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
    // FUTURE: get fields all at once from State (this is faster)
    let state = State::for_type(cls);
    let mut months = DeltaMonths::ZERO;
    let mut days = DeltaDays::ZERO;
    let mut nanos = 0;
    let mut ignore_dst = false;

    match *args {
        [arg] => {
            match kwargs.next() {
                Some((key, value)) if kwargs.len() == 1 && key.py_eq(state.str_ignore_dst)? => {
                    ignore_dst = value == Py_True();
                }
                Some(_) => raise_type_err(format!(
                    "{}() can't mix positional and keyword arguments",
                    fname
                ))?,
                None => {}
            };
            if Py_TYPE(arg) == state.time_delta_type {
                nanos = TimeDelta::extract(arg).total_nanos();
            } else if Py_TYPE(arg) == state.date_delta_type {
                let dd = DateDelta::extract(arg);
                months = dd.months;
                days = dd.days;
            } else if Py_TYPE(arg) == state.datetime_delta_type {
                let dt = DateTimeDelta::extract(arg);
                months = dt.ddelta.months;
                days = dt.ddelta.days;
                nanos = dt.tdelta.total_nanos();
            } else {
                raise_type_err(format!("{}() argument must be a delta", fname))?
            }
        }
        [] => {
            let mut raw_months = 0;
            let mut raw_days = 0;
            handle_kwargs(fname, kwargs, |key, value, eq| {
                if eq(key, state.str_ignore_dst) {
                    ignore_dst = value == Py_True();
                    Ok(true)
                } else {
                    set_units_from_kwargs(
                        key,
                        value,
                        &mut raw_months,
                        &mut raw_days,
                        &mut nanos,
                        state,
                        eq,
                    )
                }
            })?;
            months = DeltaMonths::new(raw_months).ok_or_value_err("Months out of range")?;
            days = DeltaDays::new(raw_days).ok_or_value_err("Days out of range")?;
        }
        _ => raise_type_err(format!(
            "{}() takes at most 1 positional argument, got {}",
            fname,
            args.len()
        ))?,
    }

    if negate {
        months = -months;
        days = -days;
        nanos = -nanos;
    }
    if nanos != 0 && !ignore_dst {
        raise(
            state.exc_implicitly_ignoring_dst,
            doc::ADJUST_LOCAL_DATETIME_MSG,
        )?
    }
    DateTime::extract(slf)
        .shift_date(months, days)
        .and_then(|dt| dt.shift_nanos(nanos))
        .ok_or_else_value_err(|| format!("Result of {}() out of range", fname))?
        .to_obj(cls)
}

unsafe fn difference(
    slf: *mut PyObject,
    cls: *mut PyTypeObject,
    args: &[*mut PyObject],
    kwargs: &mut KwargIter,
) -> PyReturn {
    let state = State::for_type(cls);
    check_ignore_dst_kwarg(kwargs, state, doc::DIFF_LOCAL_MSG)?;
    let [arg] = *args else {
        raise_type_err("difference() takes exactly 1 argument")?
    };
    if Py_TYPE(arg) == cls {
        let a = DateTime::extract(slf);
        let b = DateTime::extract(arg);
        Instant::from_datetime(a.date, a.time)
            .diff(Instant::from_datetime(b.date, b.time))
            .to_obj(state.time_delta_type)
    } else {
        raise_type_err("difference() argument must be a PlainDateTime")?
    }
}

unsafe fn __reduce__(slf: *mut PyObject, _: *mut PyObject) -> PyReturn {
    let DateTime {
        date: Date { year, month, day },
        time:
            Time {
                hour,
                minute,
                second,
                subsec,
            },
    } = DateTime::extract(slf);
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
        State::for_obj(slf).unpickle_plain_datetime,
        steal!((steal!(data.to_py()?),).to_py()?),
    )
        .to_py()
}

pub(crate) unsafe fn unpickle(module: *mut PyObject, arg: *mut PyObject) -> PyReturn {
    let mut packed = arg.to_bytes()?.ok_or_type_err("Invalid pickle data")?;
    if packed.len() != 11 {
        raise_type_err("Invalid pickle data")?
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
    .to_obj(State::for_mod(module).plain_datetime_type)
}

unsafe fn from_py_datetime(type_: *mut PyObject, dt: *mut PyObject) -> PyReturn {
    if PyDateTime_Check(dt) == 0 {
        raise_type_err("argument must be datetime.datetime")?
    }
    let tzinfo = borrow_dt_tzinfo(dt);
    if !is_none(tzinfo) {
        raise_value_err(format!(
            "datetime must be naive, but got tzinfo={}",
            tzinfo.repr()
        ))?
    }
    DateTime {
        date: Date::from_py_unchecked(dt),
        time: Time::from_py_dt_unchecked(dt),
    }
    .to_obj(type_.cast())
}

unsafe fn py_datetime(slf: *mut PyObject, _: *mut PyObject) -> PyReturn {
    let DateTime {
        date: Date { year, month, day },
        time:
            Time {
                hour,
                minute,
                second,
                subsec,
            },
    } = DateTime::extract(slf);
    let &PyDateTime_CAPI {
        DateTime_FromDateAndTime,
        DateTimeType,
        ..
    } = State::for_type(Py_TYPE(slf)).py_api;
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
    .as_result()
}

unsafe fn get_date(slf: *mut PyObject, _: *mut PyObject) -> PyReturn {
    DateTime::extract(slf)
        .date
        .to_obj(State::for_obj(slf).date_type)
}

unsafe fn get_time(slf: *mut PyObject, _: *mut PyObject) -> PyReturn {
    DateTime::extract(slf)
        .time
        .to_obj(State::for_obj(slf).time_type)
}

pub(crate) fn is_datetime_sep(c: u8) -> bool {
    c == b'T' || c == b' ' || c == b't'
}

unsafe fn parse_common_iso(cls: *mut PyObject, arg: *mut PyObject) -> PyReturn {
    DateTime::parse(arg.to_utf8()?.ok_or_type_err("Expected a string")?)
        .ok_or_else_value_err(|| format!("Invalid format: {}", arg.repr()))?
        .to_obj(cls.cast())
}

unsafe fn parse_strptime(
    _: *mut PyObject,
    cls: *mut PyTypeObject,
    args: &[*mut PyObject],
    kwargs: &mut KwargIter,
) -> PyReturn {
    let &State {
        str_format,
        strptime,
        ..
    } = State::for_type(cls);
    let format_obj = match kwargs.next() {
        Some((key, value)) if kwargs.len() == 1 && key.py_eq(str_format)? => value,
        _ => raise_type_err("parse_strptime() requires exactly one keyword argument `format`")?,
    };
    let &[arg_obj] = args else {
        raise_type_err(format!(
            "parse_strptime() takes exactly 1 positional argument, got {}",
            args.len()
        ))?
    };

    // OPTIMIZE: get this working with vectorcall
    let parsed =
        PyObject_Call(strptime, steal!((arg_obj, format_obj).to_py()?), NULL()).as_result()?;
    defer_decref!(parsed);
    let tzinfo = borrow_dt_tzinfo(parsed);
    if !is_none(tzinfo) {
        raise_value_err(format!(
            "datetime must be naive, but got tzinfo={}",
            tzinfo.repr()
        ))?;
    }
    DateTime {
        date: Date::from_py_unchecked(parsed),
        time: Time::from_py_dt_unchecked(parsed),
    }
    .to_obj(cls.cast())
}

unsafe fn assume_utc(slf: *mut PyObject, _: *mut PyObject) -> PyReturn {
    let DateTime { date, time } = DateTime::extract(slf);
    Instant::from_datetime(date, time).to_obj(State::for_obj(slf).instant_type)
}

unsafe fn assume_fixed_offset(slf: *mut PyObject, arg: *mut PyObject) -> PyReturn {
    let &State {
        time_delta_type,
        offset_datetime_type,
        ..
    } = State::for_obj(slf);
    DateTime::extract(slf)
        .with_offset(offset_datetime::extract_offset(arg, time_delta_type)?)
        .ok_or_value_err("Datetime out of range")?
        .to_obj(offset_datetime_type)
}

unsafe fn assume_tz(
    slf: *mut PyObject,
    cls: *mut PyTypeObject,
    args: &[*mut PyObject],
    kwargs: &mut KwargIter,
) -> PyReturn {
    let &mut State {
        str_disambiguate,
        str_compatible,
        str_raise,
        str_earlier,
        str_later,
        zoned_datetime_type,
        exc_skipped,
        exc_repeated,
        exc_tz_notfound,
        ref mut tz_cache,
        ..
    } = State::for_type_mut(cls);

    let DateTime { date, time } = DateTime::extract(slf);
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
    let tzif = tz_cache.obj_get(tz_obj, exc_tz_notfound)?;
    ZonedDateTime::resolve_using_disambiguate(date, time, tzif, dis, exc_repeated, exc_skipped)?
        .to_obj(zoned_datetime_type)
}

unsafe fn assume_system_tz(
    slf: *mut PyObject,
    cls: *mut PyTypeObject,
    args: &[*mut PyObject],
    kwargs: &mut KwargIter,
) -> PyReturn {
    let &State {
        py_api,
        str_disambiguate,
        system_datetime_type,
        exc_skipped,
        exc_repeated,
        str_compatible,
        str_raise,
        str_earlier,
        str_later,
        ..
    } = State::for_type(cls);
    let DateTime { date, time } = DateTime::extract(slf);
    if !args.is_empty() {
        raise_type_err("assume_system_tz() takes no positional arguments")?
    }

    let dis = Disambiguate::from_only_kwarg(
        kwargs,
        str_disambiguate,
        "assume_system_tz",
        str_compatible,
        str_raise,
        str_earlier,
        str_later,
    )?;
    OffsetDateTime::resolve_system_tz_using_disambiguate(
        py_api,
        date,
        time,
        dis.unwrap_or(Disambiguate::Compatible),
        exc_repeated,
        exc_skipped,
    )?
    .to_obj(system_datetime_type)
}

unsafe fn replace_date(slf: *mut PyObject, arg: *mut PyObject) -> PyReturn {
    let cls = Py_TYPE(slf);
    let DateTime { time, .. } = DateTime::extract(slf);
    if Py_TYPE(arg) == State::for_type(cls).date_type {
        DateTime {
            date: Date::extract(arg),
            time,
        }
        .to_obj(cls)
    } else {
        raise_type_err("date must be a whenever.Date instance")
    }
}

unsafe fn replace_time(slf: *mut PyObject, arg: *mut PyObject) -> PyReturn {
    let cls = Py_TYPE(slf);
    let DateTime { date, .. } = DateTime::extract(slf);
    if Py_TYPE(arg) == State::for_type(cls).time_type {
        DateTime {
            date,
            time: Time::extract(arg),
        }
        .to_obj(cls)
    } else {
        raise_type_err("time must be a whenever.Time instance")
    }
}

unsafe fn round(
    slf: *mut PyObject,
    cls: *mut PyTypeObject,
    args: &[*mut PyObject],
    kwargs: &mut KwargIter,
) -> PyReturn {
    let (_, increment, mode) = round::parse_args(State::for_obj(slf), args, kwargs, false, false)?;
    let DateTime { mut date, time } = DateTime::extract(slf);
    let (time_rounded, next_day) = time.round(increment as u64, mode);
    if next_day == 1 {
        date = date
            .tomorrow()
            .ok_or_value_err("Resulting date out of range")?;
    }
    DateTime {
        date,
        time: time_rounded,
    }
    .to_obj(cls)
}

static mut METHODS: &[PyMethodDef] = &[
    method!(identity2 named "__copy__", c""),
    method!(identity2 named "__deepcopy__", c"", METH_O),
    method!(__reduce__, c""),
    method!(
        from_py_datetime,
        doc::PLAINDATETIME_FROM_PY_DATETIME,
        METH_CLASS | METH_O
    ),
    method!(py_datetime, doc::BASICCONVERSIONS_PY_DATETIME),
    method!(
        get_date named "date",
        doc::LOCALTIME_DATE
    ),
    method!(
        get_time named "time",
        doc::LOCALTIME_TIME
    ),
    method!(format_common_iso, doc::PLAINDATETIME_FORMAT_COMMON_ISO),
    method!(
        parse_common_iso,
        doc::PLAINDATETIME_PARSE_COMMON_ISO,
        METH_O | METH_CLASS
    ),
    method_kwargs!(
        parse_strptime,
        doc::PLAINDATETIME_PARSE_STRPTIME,
        METH_CLASS
    ),
    method_kwargs!(replace, doc::PLAINDATETIME_REPLACE),
    method!(assume_utc, doc::PLAINDATETIME_ASSUME_UTC),
    method!(
        assume_fixed_offset,
        doc::PLAINDATETIME_ASSUME_FIXED_OFFSET,
        METH_O
    ),
    method_kwargs!(assume_tz, doc::PLAINDATETIME_ASSUME_TZ),
    method_kwargs!(assume_system_tz, doc::PLAINDATETIME_ASSUME_SYSTEM_TZ),
    method!(replace_date, doc::PLAINDATETIME_REPLACE_DATE, METH_O),
    method!(replace_time, doc::PLAINDATETIME_REPLACE_TIME, METH_O),
    method_kwargs!(add, doc::PLAINDATETIME_ADD),
    method_kwargs!(subtract, doc::PLAINDATETIME_SUBTRACT),
    method_kwargs!(difference, doc::PLAINDATETIME_DIFFERENCE),
    method_kwargs!(round, doc::PLAINDATETIME_ROUND),
    PyMethodDef::zeroed(),
];

unsafe fn get_year(slf: *mut PyObject) -> PyReturn {
    DateTime::extract(slf).date.year.get().to_py()
}

unsafe fn get_month(slf: *mut PyObject) -> PyReturn {
    DateTime::extract(slf).date.month.get().to_py()
}

unsafe fn get_day(slf: *mut PyObject) -> PyReturn {
    DateTime::extract(slf).date.day.to_py()
}

unsafe fn get_hour(slf: *mut PyObject) -> PyReturn {
    DateTime::extract(slf).time.hour.to_py()
}

unsafe fn get_minute(slf: *mut PyObject) -> PyReturn {
    DateTime::extract(slf).time.minute.to_py()
}

unsafe fn get_second(slf: *mut PyObject) -> PyReturn {
    DateTime::extract(slf).time.second.to_py()
}

unsafe fn get_nanos(slf: *mut PyObject) -> PyReturn {
    DateTime::extract(slf).time.subsec.get().to_py()
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
    getter!(
        get_hour named "hour",
        "The hour component"
    ),
    getter!(
        get_minute named "minute",
        "The minute component"
    ),
    getter!(
        get_second named "second",
        "The second component"
    ),
    getter!(
        get_nanos named "nanosecond",
        "The nanosecond component"
    ),
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
