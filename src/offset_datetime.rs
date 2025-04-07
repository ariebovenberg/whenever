use core::ffi::{c_int, c_long, c_void, CStr};
use core::ptr::null_mut as NULL;
use pyo3_ffi::*;
use std::fmt::{self, Display, Formatter};

use crate::{
    common::{math::*, *},
    date::Date,
    date_delta::DateDelta,
    datetime_delta::{set_units_from_kwargs, DateTimeDelta},
    docstrings as doc,
    instant::Instant,
    plain_datetime::{set_components_from_kwargs, DateTime},
    round,
    time::Time,
    time_delta::TimeDelta,
    zoned_datetime::ZonedDateTime,
    State,
};

/// A date and time with a fixed offset from UTC.
/// Invariant: the instant represented by the date and time is always within range.
#[derive(Debug, Eq, PartialEq, Ord, PartialOrd, Copy, Clone)]
pub(crate) struct OffsetDateTime {
    pub(crate) date: Date,
    pub(crate) time: Time,
    pub(crate) offset: Offset,
}

pub(crate) const SINGLETONS: &[(&CStr, OffsetDateTime); 0] = &[];

impl OffsetDateTime {
    pub(crate) const fn new_unchecked(date: Date, time: Time, offset: Offset) -> Self {
        OffsetDateTime { date, time, offset }
    }

    pub(crate) fn new(date: Date, time: Time, offset: Offset) -> Option<Self> {
        // Check: the instant represented by the date and time is within range
        date.epoch_at(time).offset(-offset)?;
        Some(Self { date, time, offset })
    }

    pub(crate) fn instant(self) -> Instant {
        Instant::from_datetime(self.date, self.time)
            .offset(-self.offset)
            // Safe: we know the instant of an OffsetDateTime is in range
            .unwrap()
    }

    pub(crate) const fn without_offset(self) -> DateTime {
        DateTime {
            date: self.date,
            time: self.time,
        }
    }

    pub(crate) fn parse(string: &[u8]) -> Option<Self> {
        let s = &mut &*string;
        // at least: "YYYY-MM-DDTHH:MM:SSZ"
        if s.len() < 20 || s[10] != b'T' {
            return None;
        }
        let date = Date::parse_partial(s)?;
        *s = &s[1..]; // skip the separator
        Self::new(date, Time::parse_partial(s)?, parse_hms_offset(s)?)
    }

    pub(crate) unsafe fn to_py(
        self,
        &PyDateTime_CAPI {
            DateTime_FromDateAndTime,
            DateTimeType,
            TimeZone_FromTimeZone,
            Delta_FromDelta,
            DeltaType,
            ..
        }: &PyDateTime_CAPI,
    ) -> PyReturn {
        let OffsetDateTime {
            date: Date { year, month, day },
            time:
                Time {
                    hour,
                    minute,
                    second,
                    subsec: nanos,
                },
            offset: offset_secs,
            ..
        } = self;
        let tz = TimeZone_FromTimeZone(
            Delta_FromDelta(0, offset_secs.get(), 0, 0, DeltaType),
            NULL(),
        );
        defer_decref!(tz);
        DateTime_FromDateAndTime(
            year.get().into(),
            month.get().into(),
            day.into(),
            hour.into(),
            minute.into(),
            second.into(),
            (nanos.get() / 1_000) as _,
            tz,
            DateTimeType,
        )
        .as_result()
    }

    // Returns None if the tzinfo is incorrect, or the UTC time is out of bounds
    pub(crate) unsafe fn from_py(dt: *mut PyObject, state: &State) -> PyResult<Option<Self>> {
        debug_assert!(PyObject_IsInstance(dt, state.py_api.DateTimeType.cast()).is_positive());
        if is_none(borrow_dt_tzinfo(dt)) {
            raise_value_err("Datetime cannot be naive")?
        }
        Ok(OffsetDateTime::new(
            Date::from_py_unchecked(dt),
            Time::from_py_dt_unchecked(dt),
            offset_from_py_dt(dt)?,
        ))
    }

    pub(crate) unsafe fn from_py_and_nanos_unchecked(
        dt: *mut PyObject,
        nanos: SubSecNanos,
    ) -> PyResult<Self> {
        OffsetDateTime::new(
            Date::from_py_unchecked(dt),
            Time {
                hour: PyDateTime_DATE_GET_HOUR(dt) as u8,
                minute: PyDateTime_DATE_GET_MINUTE(dt) as u8,
                second: PyDateTime_DATE_GET_SECOND(dt) as u8,
                subsec: nanos,
            },
            offset_from_py_dt(dt)?,
        )
        .ok_or_value_err("Datetime is out of range")
    }
}

impl DateTime {
    pub(crate) fn with_offset(self, offset: Offset) -> Option<OffsetDateTime> {
        OffsetDateTime::new(self.date, self.time, offset)
    }

    pub(crate) const fn with_offset_unchecked(self, offset: Offset) -> OffsetDateTime {
        OffsetDateTime {
            date: self.date,
            time: self.time,
            offset,
        }
    }
}

impl Instant {
    pub(crate) fn to_offset(self, secs: Offset) -> Option<OffsetDateTime> {
        Some(
            self.offset(secs)?
                .to_datetime()
                // Safety: at this point, we know the instant and local date
                // are in range
                .with_offset_unchecked(secs),
        )
    }
}

impl PyWrapped for OffsetDateTime {}

impl Display for OffsetDateTime {
    fn fmt(&self, f: &mut Formatter<'_>) -> fmt::Result {
        let &OffsetDateTime {
            date,
            time,
            offset: offset_secs,
        } = self;
        write!(f, "{}T{}{}", date, time, offset_secs)
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
    let mut offset: *mut PyObject = NULL();

    parse_args_kwargs!(
        args,
        kwargs,
        c"lll|lll$lO:OffsetDateTime",
        year,
        month,
        day,
        hour,
        minute,
        second,
        nanosecond,
        offset
    );

    let date = Date::from_longs(year, month, day).ok_or_value_err("Invalid date")?;
    let time =
        Time::from_longs(hour, minute, second, nanosecond).ok_or_value_err("Invalid time")?;
    let offset_secs = extract_offset(offset, State::for_type(cls).time_delta_type)?;
    OffsetDateTime::new(date, time, offset_secs)
        .ok_or_value_err("Time is out of range")?
        .to_obj(cls)
}

pub(crate) unsafe fn extract_offset(
    obj: *mut PyObject,
    tdelta_cls: *mut PyTypeObject,
) -> PyResult<Offset> {
    if obj.is_null() {
        raise_type_err("Missing required keyword argument: 'offset'")
    } else if obj.is_int() {
        Offset::from_hours(
            obj.to_long()?
                // We've checked before that it's a py int
                .unwrap(),
        )
        .ok_or_value_err("offset must be between -24 and 24 hours")
    } else if Py_TYPE(obj) == tdelta_cls {
        let TimeDelta { secs, subsec } = TimeDelta::extract(obj);
        if subsec.get() == 0 {
            Offset::from_i64(secs.get()).ok_or_value_err("offset must be between -24 and 24 hours")
        } else {
            raise_value_err("offset must be a whole number of seconds")
        }
    } else {
        raise_type_err(format!(
            "offset must be an integer or TimeDelta instance, got {}",
            obj.repr()
        ))
    }
}

unsafe fn __repr__(slf: *mut PyObject) -> PyReturn {
    let OffsetDateTime {
        date,
        time,
        offset: offset_secs,
    } = OffsetDateTime::extract(slf);
    format!("OffsetDateTime({} {}{})", date, time, offset_secs).to_py()
}

unsafe fn __str__(slf: *mut PyObject) -> PyReturn {
    format!("{}", OffsetDateTime::extract(slf)).to_py()
}

unsafe fn __richcmp__(a_obj: *mut PyObject, b_obj: *mut PyObject, op: c_int) -> PyReturn {
    let type_a = Py_TYPE(a_obj);
    let type_b = Py_TYPE(b_obj);
    let inst_a = OffsetDateTime::extract(a_obj).instant();
    let inst_b = if type_b == type_a {
        OffsetDateTime::extract(b_obj).instant()
    } else if type_b == State::for_type(type_a).instant_type {
        Instant::extract(b_obj)
    } else if type_b == State::for_type(type_a).zoned_datetime_type {
        ZonedDateTime::extract(b_obj).instant()
    } else {
        return Ok(newref(Py_NotImplemented()));
    };
    match op {
        pyo3_ffi::Py_EQ => inst_a == inst_b,
        pyo3_ffi::Py_NE => inst_a != inst_b,
        pyo3_ffi::Py_LT => inst_a < inst_b,
        pyo3_ffi::Py_LE => inst_a <= inst_b,
        pyo3_ffi::Py_GT => inst_a > inst_b,
        pyo3_ffi::Py_GE => inst_a >= inst_b,
        _ => unreachable!(),
    }
    .to_py()
}

pub(crate) unsafe extern "C" fn __hash__(slf: *mut PyObject) -> Py_hash_t {
    hashmask(OffsetDateTime::extract(slf).instant().pyhash())
}

unsafe fn __sub__(obj_a: *mut PyObject, obj_b: *mut PyObject) -> PyReturn {
    let type_a = Py_TYPE(obj_a);
    let type_b = Py_TYPE(obj_b);

    // Easy case: OffsetDT - OffsetDT
    let (inst_a, inst_b) = if type_a == type_b {
        (
            OffsetDateTime::extract(obj_a).instant(),
            OffsetDateTime::extract(obj_b).instant(),
        )
    // Other cases are more difficult, as they can be triggered
    // by reflexive operations with arbitrary types.
    // We need to eliminate them carefully.
    } else {
        let mod_a = PyType_GetModule(type_a);
        let mod_b = PyType_GetModule(type_b);
        if mod_a == mod_b {
            let state = State::for_mod(mod_a);
            let inst_b = if type_b == state.instant_type {
                Instant::extract(obj_b)
            } else if type_b == state.zoned_datetime_type {
                ZonedDateTime::extract(obj_b).instant()
            } else if type_b == state.system_datetime_type {
                OffsetDateTime::extract(obj_b).instant()
            } else if type_b == state.time_delta_type
                || type_b == state.date_delta_type
                || type_b == state.datetime_delta_type
            {
                raise(
                    state.exc_implicitly_ignoring_dst,
                    doc::ADJUST_OFFSET_DATETIME_MSG,
                )?
            } else {
                return Ok(newref(Py_NotImplemented()));
            };
            debug_assert_eq!(type_a, State::for_mod(mod_a).offset_datetime_type);
            let inst_a = OffsetDateTime::extract(obj_a).instant();
            (inst_a, inst_b)
        } else {
            return Ok(newref(Py_NotImplemented()));
        }
    };
    inst_a
        .diff(inst_b)
        .to_obj(State::for_type(type_a).time_delta_type)
}

#[allow(static_mut_refs)]
static mut SLOTS: &[PyType_Slot] = &[
    slotmethod!(Py_tp_new, __new__),
    slotmethod!(Py_tp_str, __str__, 1),
    slotmethod!(Py_tp_repr, __repr__, 1),
    slotmethod!(Py_tp_richcompare, __richcmp__),
    slotmethod!(Py_nb_subtract, __sub__, 2),
    PyType_Slot {
        slot: Py_tp_doc,
        pfunc: doc::OFFSETDATETIME.as_ptr() as *mut c_void,
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

unsafe fn exact_eq(obj_a: *mut PyObject, obj_b: *mut PyObject) -> PyReturn {
    if Py_TYPE(obj_a) == Py_TYPE(obj_b) {
        (OffsetDateTime::extract(obj_a) == OffsetDateTime::extract(obj_b)).to_py()
    } else {
        raise_type_err("Can't compare different types")
    }
}

pub(crate) unsafe fn to_instant(slf: *mut PyObject, _: *mut PyObject) -> PyReturn {
    OffsetDateTime::extract(slf)
        .instant()
        .to_obj(State::for_obj(slf).instant_type)
}

pub(crate) unsafe fn instant(slf: *mut PyObject, _: *mut PyObject) -> PyReturn {
    PyErr_WarnEx(
        PyExc_DeprecationWarning,
        c"instant() method is deprecated. Use to_instant() instead".as_ptr(),
        1,
    );
    to_instant(slf, NULL())
}

unsafe fn to_fixed_offset(slf_obj: *mut PyObject, args: &[*mut PyObject]) -> PyReturn {
    match *args {
        [] => Ok(newref(slf_obj)),
        [offset_obj] => {
            let cls = Py_TYPE(slf_obj);
            OffsetDateTime::extract(slf_obj)
                .instant()
                .to_offset(extract_offset(
                    offset_obj,
                    State::for_type(cls).time_delta_type,
                )?)
                .ok_or_value_err("Resulting date is out of range")?
                .to_obj(cls)
        }
        _ => raise_type_err("to_fixed_offset() takes at most 1 argument"),
    }
}

unsafe fn to_tz(slf: *mut PyObject, tz_obj: *mut PyObject) -> PyReturn {
    let &mut State {
        zoned_datetime_type,
        exc_tz_notfound,
        ref mut tz_cache,
        ..
    } = State::for_obj_mut(slf);

    let tz = tz_cache.obj_get(tz_obj, exc_tz_notfound)?;
    OffsetDateTime::extract(slf)
        .instant()
        .to_tz(tz)
        .ok_or_value_err("Resulting datetime is out of range")?
        .to_obj(zoned_datetime_type)
}

unsafe fn to_system_tz(slf: *mut PyObject, _: *mut PyObject) -> PyReturn {
    let &State {
        py_api,
        system_datetime_type,
        ..
    } = State::for_obj(slf);
    OffsetDateTime::extract(slf)
        .to_system_tz(py_api)?
        .to_obj(system_datetime_type)
}

pub(crate) unsafe fn unpickle(module: *mut PyObject, arg: *mut PyObject) -> PyReturn {
    let mut packed = arg.to_bytes()?.ok_or_type_err("Invalid pickle data")?;
    if packed.len() != 15 {
        raise_value_err("Invalid pickle data")?;
    }
    OffsetDateTime::new_unchecked(
        Date {
            year: Year::new_unchecked(unpack_one!(packed, u16)),
            month: Month::new_unchecked(unpack_one!(packed, u8)),
            day: unpack_one!(packed, u8),
        },
        Time {
            hour: unpack_one!(packed, u8),
            minute: unpack_one!(packed, u8),
            second: unpack_one!(packed, u8),
            subsec: SubSecNanos::new_unchecked(unpack_one!(packed, i32)),
        },
        Offset::new_unchecked(unpack_one!(packed, i32)),
    )
    .to_obj(State::for_mod(module).offset_datetime_type)
}

unsafe fn py_datetime(slf: *mut PyObject, _: *mut PyObject) -> PyReturn {
    OffsetDateTime::extract(slf).to_py(State::for_obj(slf).py_api)
}

unsafe fn date(slf: *mut PyObject, _: *mut PyObject) -> PyReturn {
    OffsetDateTime::extract(slf)
        .date
        .to_obj(State::for_obj(slf).date_type)
}

unsafe fn time(slf: *mut PyObject, _: *mut PyObject) -> PyReturn {
    OffsetDateTime::extract(slf)
        .time
        .to_obj(State::for_obj(slf).time_type)
}

#[inline]
pub(crate) unsafe fn check_ignore_dst_kwarg(
    kwargs: &mut KwargIter,
    state: &State,
    msg: &str,
) -> PyResult<()> {
    match kwargs.next() {
        Some((key, value))
            if kwargs.len() == 1 && key.py_eq(state.str_ignore_dst)? && value == Py_True() =>
        {
            Ok(())
        }
        Some((key, _)) => raise_type_err(format!("Unknown keyword argument: {}", key.repr())),
        _ => raise(state.exc_implicitly_ignoring_dst, msg),
    }
}

unsafe fn replace_date(
    slf: *mut PyObject,
    cls: *mut PyTypeObject,
    args: &[*mut PyObject],
    kwargs: &mut KwargIter,
) -> PyReturn {
    let OffsetDateTime {
        time,
        offset: offset_secs,
        ..
    } = OffsetDateTime::extract(slf);
    let state = State::for_type(cls);

    check_ignore_dst_kwarg(kwargs, state, doc::ADJUST_OFFSET_DATETIME_MSG)?;

    let &[arg] = args else {
        raise_type_err("replace() takes exactly 1 positional argument")?
    };
    if Py_TYPE(arg) == state.date_type {
        OffsetDateTime::new(Date::extract(arg), time, offset_secs)
            .ok_or_value_err("New datetime is out of range")?
            .to_obj(cls)
    } else {
        raise_type_err("date must be a whenever.Date instance")
    }
}

unsafe fn replace_time(
    slf: *mut PyObject,
    cls: *mut PyTypeObject,
    args: &[*mut PyObject],
    kwargs: &mut KwargIter,
) -> PyReturn {
    let OffsetDateTime {
        date,
        offset: offset_secs,
        ..
    } = OffsetDateTime::extract(slf);
    let state = State::for_type(cls);
    check_ignore_dst_kwarg(kwargs, state, doc::ADJUST_OFFSET_DATETIME_MSG)?;

    let &[arg] = args else {
        raise_type_err("replace() takes exactly 1 positional argument")?
    };

    if Py_TYPE(arg) == state.time_type {
        OffsetDateTime::new(date, Time::extract(arg), offset_secs)
            .ok_or_value_err("New datetime is out of range")?
            .to_obj(cls)
    } else {
        raise_type_err("time must be a whenever.Time instance")
    }
}

unsafe fn format_common_iso(slf: *mut PyObject, _: *mut PyObject) -> PyReturn {
    __str__(slf)
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
        str_ignore_dst,
        str_offset,
        str_year,
        str_month,
        str_day,
        str_hour,
        str_minute,
        str_second,
        str_nanosecond,
        time_delta_type,
        exc_implicitly_ignoring_dst,
        ..
    } = State::for_type(cls);
    let OffsetDateTime {
        date,
        time,
        mut offset,
    } = OffsetDateTime::extract(slf);
    let mut year = date.year.get().into();
    let mut month = date.month.get().into();
    let mut day = date.day.into();
    let mut hour = time.hour.into();
    let mut minute = time.minute.into();
    let mut second = time.second.into();
    let mut nanos = time.subsec.get() as _;
    let mut ignore_dst = false;

    handle_kwargs("replace", kwargs, |key, value, eq| {
        if eq(key, str_ignore_dst) {
            ignore_dst = value == Py_True();
        } else if eq(key, str_offset) {
            offset = extract_offset(value, time_delta_type)?;
        } else {
            return set_components_from_kwargs(
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
            );
        }
        Ok(true)
    })?;

    if !ignore_dst {
        raise(exc_implicitly_ignoring_dst, doc::ADJUST_OFFSET_DATETIME_MSG)?
    }

    let date = Date::from_longs(year, month, day).ok_or_value_err("Invalid date")?;
    let time = Time::from_longs(hour, minute, second, nanos).ok_or_value_err("Invalid time")?;
    OffsetDateTime::new(date, time, offset)
        .ok_or_value_err("Resulting datetime is out of range")?
        .to_obj(cls)
}

unsafe fn now(
    _: *mut PyObject,
    cls: *mut PyTypeObject,
    args: &[*mut PyObject],
    kwargs: &mut KwargIter,
) -> PyReturn {
    let state = State::for_type(cls);
    let &[offset_obj] = args else {
        raise_type_err("now() takes exactly 1 positional argument")?
    };
    check_ignore_dst_kwarg(kwargs, state, doc::OFFSET_NOW_DST_MSG)?;
    let offset = extract_offset(offset_obj, state.time_delta_type)?;
    state
        .time_ns()?
        .to_offset(offset)
        .ok_or_raise(PyExc_OSError, "Date is out of range")?
        .to_obj(cls.cast())
}

unsafe fn from_py_datetime(cls: *mut PyObject, dt: *mut PyObject) -> PyReturn {
    if PyDateTime_Check(dt) == 0 {
        raise_type_err("Argument must be a datetime.datetime instance")?
    }
    OffsetDateTime::from_py(dt, State::for_type(cls.cast()))?
        .ok_or_else_value_err(|| {
            format!(
                "Argument must have a `datetime.timezone` tzinfo and be within range, got {}",
                dt.repr()
            )
        })?
        .to_obj(cls.cast())
}

pub(crate) unsafe fn to_plain(slf: *mut PyObject, _: *mut PyObject) -> PyReturn {
    OffsetDateTime::extract(slf)
        .without_offset()
        .to_obj(State::for_obj(slf).plain_datetime_type)
}

pub(crate) unsafe fn local(slf: *mut PyObject, _: *mut PyObject) -> PyReturn {
    PyErr_WarnEx(
        PyExc_DeprecationWarning,
        c"local() method is deprecated. Use to_plain() instead".as_ptr(),
        1,
    );
    to_plain(slf, NULL())
}

pub(crate) unsafe fn timestamp(slf: *mut PyObject, _: *mut PyObject) -> PyReturn {
    OffsetDateTime::extract(slf).instant().epoch.get().to_py()
}

pub(crate) unsafe fn timestamp_millis(slf: *mut PyObject, _: *mut PyObject) -> PyReturn {
    OffsetDateTime::extract(slf)
        .instant()
        .timestamp_millis()
        .to_py()
}

pub(crate) unsafe fn timestamp_nanos(slf: *mut PyObject, _: *mut PyObject) -> PyReturn {
    OffsetDateTime::extract(slf)
        .instant()
        .timestamp_nanos()
        .to_py()
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
                None => {}
                _ => raise_type_err(format!(
                    "{}() can't mix positional and keyword arguments",
                    fname
                ))?,
            }
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
            // FUTURE: some redundancy in checks
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
    if !ignore_dst {
        raise(
            state.exc_implicitly_ignoring_dst,
            doc::ADJUST_OFFSET_DATETIME_MSG,
        )?
    }
    let OffsetDateTime { date, time, offset } = OffsetDateTime::extract(slf);
    DateTime { date, time }
        .shift_date(months, days)
        .and_then(|dt| dt.shift_nanos(nanos))
        .and_then(|dt| dt.with_offset(offset))
        .ok_or_else_value_err(|| format!("Result of {}() out of range", fname))?
        .to_obj(cls)
}

unsafe fn difference(obj_a: *mut PyObject, obj_b: *mut PyObject) -> PyReturn {
    let type_b = Py_TYPE(obj_b);
    let type_a = Py_TYPE(obj_a);
    let state = State::for_type(type_a);
    let inst_a = OffsetDateTime::extract(obj_a).instant();
    let inst_b = if type_b == Py_TYPE(obj_a) {
        OffsetDateTime::extract(obj_b).instant()
    } else if type_b == state.instant_type {
        Instant::extract(obj_b)
    } else if type_b == state.zoned_datetime_type {
        ZonedDateTime::extract(obj_b).instant()
    } else if type_b == state.system_datetime_type {
        OffsetDateTime::extract(obj_b).instant()
    } else {
        raise_type_err(
            "difference() argument must be an OffsetDateTime, 
                Instant, ZonedDateTime, or SystemDateTime",
        )?
    };
    inst_a.diff(inst_b).to_obj(state.time_delta_type)
}

unsafe fn __reduce__(slf: *mut PyObject, _: *mut PyObject) -> PyReturn {
    let OffsetDateTime {
        date: Date { year, month, day },
        time:
            Time {
                hour,
                minute,
                second,
                subsec: nanos,
            },
        offset,
    } = OffsetDateTime::extract(slf);
    let data = pack![
        year.get(),
        month.get(),
        day,
        hour,
        minute,
        second,
        nanos.get(),
        offset.get()
    ];
    (
        State::for_obj(slf).unpickle_offset_datetime,
        steal!((steal!(data.to_py()?),).to_py()?),
    )
        .to_py()
}

// checks the args comply with (ts: ?, /, *, offset: ?, ignore_dst: true)
unsafe fn check_from_timestamp_args_return_offset(
    fname: &str,
    args: &[*mut PyObject],
    kwargs: &mut KwargIter,
    &State {
        str_offset,
        str_ignore_dst,
        time_delta_type,
        exc_implicitly_ignoring_dst,
        ..
    }: &State,
) -> PyResult<Offset> {
    let mut ignore_dst = false;
    let mut offset_secs = None;
    if args.len() != 1 {
        raise_type_err(format!(
            "{}() takes 1 positional argument but {} were given",
            fname,
            args.len()
        ))?
    }

    handle_kwargs("from_timestamp", kwargs, |key, value, eq| {
        if eq(key, str_ignore_dst) {
            ignore_dst = value == Py_True();
        } else if eq(key, str_offset) {
            offset_secs = Some(extract_offset(value, time_delta_type)?);
        } else {
            return Ok(false);
        }
        Ok(true)
    })?;

    if !ignore_dst {
        raise(exc_implicitly_ignoring_dst, doc::TIMESTAMP_DST_MSG)?
    }

    offset_secs.ok_or_type_err("Missing required keyword argument: 'offset'")
}

unsafe fn from_timestamp(
    _: *mut PyObject,
    cls: *mut PyTypeObject,
    args: &[*mut PyObject],
    kwargs: &mut KwargIter,
) -> PyReturn {
    let state = State::for_type(cls);
    let offset = check_from_timestamp_args_return_offset("from_timestamp", args, kwargs, state)?;

    match args[0].to_i64()? {
        Some(ts) => Instant::from_timestamp(ts),
        None => Instant::from_timestamp_f64(
            args[0]
                .to_f64()?
                .ok_or_type_err("Timestamp must be an integer or float")?,
        ),
    }
    .ok_or_value_err("Timestamp is out of range")?
    .to_offset(offset)
    .ok_or_value_err("Resulting date is out of range")?
    .to_obj(cls)
}

unsafe fn from_timestamp_millis(
    _: *mut PyObject,
    cls: *mut PyTypeObject,
    args: &[*mut PyObject],
    kwargs: &mut KwargIter,
) -> PyReturn {
    let state = State::for_type(cls);
    let offset =
        check_from_timestamp_args_return_offset("from_timestamp_millis", args, kwargs, state)?;
    Instant::from_timestamp_millis(
        args[0]
            .to_i64()?
            .ok_or_type_err("timestamp must be an integer")?,
    )
    .ok_or_value_err("timestamp is out of range")?
    .to_offset(offset)
    .ok_or_value_err("Resulting date is out of range")?
    .to_obj(cls)
}

unsafe fn from_timestamp_nanos(
    _: *mut PyObject,
    cls: *mut PyTypeObject,
    args: &[*mut PyObject],
    kwargs: &mut KwargIter,
) -> PyReturn {
    let state = State::for_type(cls);
    let offset =
        check_from_timestamp_args_return_offset("from_timestamp_nanos", args, kwargs, state)?;
    Instant::from_timestamp_nanos(
        args[0]
            .to_i128()?
            .ok_or_type_err("timestamp must be an integer")?,
    )
    .ok_or_value_err("Timestamp is out of range")?
    .to_offset(offset)
    .ok_or_value_err("Resulting date is out of range")?
    .to_obj(cls)
}

// parse ±HH:MM[:SS] or [Zz]
fn parse_hms_offset(s: &[u8]) -> Option<Offset> {
    let sign = match s.first() {
        Some(b'+') => Sign::Plus,
        Some(b'-') => Sign::Minus,
        Some(b'Z') if s.len() == 1 => return Some(Offset::ZERO),
        _ => return None,
    };
    if s.len() >= 6 && s[3] == b':' {
        // the HH:MM part
        let secs = (parse_digit_max(s, 1, b'2')? * 10 + parse_digit(s, 2)?) as i32 * 3600
            + (parse_digit_max(s, 4, b'5')? * 10 + parse_digit(s, 5)?) as i32 * 60;
        // the optional seconds part
        match s.get(6) {
            Some(b':') if s.len() == 9 => {
                Some(secs + parse_digit_max(s, 7, b'5')? as i32 * 10 + parse_digit(s, 8)? as i32)
            }
            None => Some(secs),
            _ => None,
        }
        .and_then(Offset::new)
        .map(|s| s.with_sign(sign))
    } else {
        None
    }
}

unsafe fn parse_common_iso(cls: *mut PyObject, s_obj: *mut PyObject) -> PyReturn {
    OffsetDateTime::parse(s_obj.to_utf8()?.ok_or_type_err("Expected a string")?)
        .ok_or_else_value_err(|| format!("Invalid format: {}", s_obj.repr()))?
        .to_obj(cls.cast())
}

// exactly "±HH:MM" or "Z|z"
fn parse_rfc3339_offset(s: &[u8]) -> Option<Offset> {
    let sign = match s.first() {
        Some(b'+') => Sign::Plus,
        Some(b'-') => Sign::Minus,
        Some(b'Z' | b'z') if s.len() == 1 => return Some(Offset::ZERO),
        _ => return None,
    };
    if s.len() == 6 && s[3] == b':' {
        Some(
            (parse_digit_max(s, 1, b'2')? * 10 + parse_digit(s, 2)?) as i32 * 3600
                + (parse_digit_max(s, 4, b'5')? * 10 + parse_digit(s, 5)?) as i32 * 60,
        )
        // No risk of overflow since we've parsed few digits
        .and_then(Offset::new)
        .map(|s| s.with_sign(sign))
    } else {
        None
    }
}

unsafe fn parse_rfc3339(cls: *mut PyObject, s_obj: *mut PyObject) -> PyReturn {
    let s = &mut s_obj.to_utf8()?.ok_or_type_err("Expected a string")?;
    let errmsg = || format!("Invalid RFC 3339 format: {}", s_obj.repr());
    // at least: "YYYY-MM-DDTHH:MM:SSZ"
    if s.len() < 20 {
        raise_value_err(errmsg())?
    }
    let date = Date::parse_partial(s).ok_or_else_value_err(errmsg)?;
    // parse the separator
    if !(s[0] == b'T' || s[0] == b't' || s[0] == b' ' || s[0] == b'_') {
        raise_value_err(errmsg())?
    }
    *s = &s[1..];
    let time = Time::parse_partial(s).ok_or_else_value_err(errmsg)?;
    let offset_secs = parse_rfc3339_offset(s).ok_or_else_value_err(errmsg)?;
    OffsetDateTime::new(date, time, offset_secs)
        .ok_or_else_value_err(errmsg)?
        .to_obj(cls.cast())
}

unsafe fn strptime(cls: *mut PyObject, args: &[*mut PyObject]) -> PyReturn {
    let state = State::for_type(cls.cast());
    if args.len() != 2 {
        raise_type_err("strptime() takes exactly 2 arguments")?;
    }
    // OPTIMIZE: get this working with vectorcall
    let parsed =
        PyObject_Call(state.strptime, steal!((args[0], args[1]).to_py()?), NULL()).as_result()?;
    defer_decref!(parsed);

    OffsetDateTime::from_py(parsed, state)?
        .ok_or_else_value_err(|| {
            format!(
                "parsed datetime must have a timezone and be within range, got {}",
                (parsed as *mut PyObject).repr()
            )
        })?
        .to_obj(cls.cast())
}

// Different from the Display impl, this is only exact to the minute, not second.
pub(crate) fn offset_fmt_rfc3339(x: Offset) -> String {
    let secs = x.get();
    let (sign, secs) = if secs < 0 { ('-', -secs) } else { ('+', secs) };
    format!("{}{:02}:{:02}", sign, secs / 3600, (secs % 3600) / 60)
}

unsafe fn format_rfc3339(slf: *mut PyObject, _: *mut PyObject) -> PyReturn {
    let OffsetDateTime { date, time, offset } = OffsetDateTime::extract(slf);
    format!("{} {}{}", date, time, offset_fmt_rfc3339(offset)).to_py()
}

unsafe fn format_rfc2822(slf: *mut PyObject, _: *mut PyObject) -> PyReturn {
    let &State {
        format_rfc2822,
        py_api,
        ..
    } = State::for_obj(slf);
    call1(format_rfc2822, OffsetDateTime::extract(slf).to_py(py_api)?)
}

#[cfg(Py_3_10)]
unsafe fn parse_rfc2822(cls: *mut PyObject, s_obj: *mut PyObject) -> PyReturn {
    let state = State::for_type(cls.cast());
    let py_dt = call1(state.parse_rfc2822, s_obj)?;
    defer_decref!(py_dt);
    if is_none(borrow_dt_tzinfo(py_dt)) {
        raise_value_err(format!(
            "parsed datetime must have a timezone, got {}",
            s_obj.repr()
        ))?
    };
    OffsetDateTime::from_py(py_dt, state)?
        .ok_or_value_err(format!(
            "parsed datetime must have a timezone and be in range, got {}",
            s_obj.repr()
        ))?
        .to_obj(cls.cast())
}

// On python 3.9, parsing sometimes raises a TypeError.
// We need special handling for this case.
#[cfg(not(Py_3_10))]
unsafe fn parse_rfc2822(cls: *mut PyObject, s_obj: *mut PyObject) -> PyReturn {
    let state = State::for_type(cls.cast());
    if !s_obj.is_str() {
        raise_type_err("Argument must be a string")?
    }
    let py_dt = call1(state.parse_rfc2822, s_obj).map_err(|e| {
        if PyErr_ExceptionMatches(PyExc_TypeError) != 0 {
            PyErr_Clear();
            value_err(format!("Invalid format: {}", s_obj.repr()))
        } else {
            e
        }
    })?;
    defer_decref!(py_dt);
    if is_none(borrow_dt_tzinfo(py_dt)) {
        raise_value_err(format!(
            "parsed datetime must have a timezone, got {}",
            s_obj.repr()
        ))?
    };
    OffsetDateTime::from_py(py_dt, state)?
        .ok_or_else_value_err(|| {
            format!(
                "parsed datetime must have a timezone and be in range, got {}",
                s_obj.repr()
            )
        })?
        .to_obj(cls.cast())
}

unsafe fn round(
    slf: *mut PyObject,
    cls: *mut PyTypeObject,
    args: &[*mut PyObject],
    kwargs: &mut KwargIter,
) -> PyReturn {
    let (_, increment, mode) = round::parse_args(State::for_obj(slf), args, kwargs, false, true)?;
    let OffsetDateTime {
        mut date,
        time,
        offset: offset_secs,
    } = OffsetDateTime::extract(slf);
    let (time_rounded, next_day) = time.round(increment as u64, mode);
    if next_day == 1 {
        date = date
            .tomorrow()
            .ok_or_value_err("Resulting datetime out of range")?;
    }
    OffsetDateTime {
        date,
        time: time_rounded,
        offset: offset_secs,
    }
    .to_obj(cls)
}

static mut METHODS: &[PyMethodDef] = &[
    // FUTURE: get docstrings from Python implementation
    method!(identity2 named "__copy__", c""),
    method!(identity2 named "__deepcopy__", c"", METH_O),
    method!(__reduce__, c""),
    method_kwargs!(now, doc::OFFSETDATETIME_NOW, METH_CLASS),
    method!(exact_eq, doc::EXACTTIME_EXACT_EQ, METH_O),
    method!(py_datetime, doc::BASICCONVERSIONS_PY_DATETIME),
    method!(
        from_py_datetime,
        doc::OFFSETDATETIME_FROM_PY_DATETIME,
        METH_O | METH_CLASS
    ),
    method!(to_instant, doc::EXACTANDLOCALTIME_TO_INSTANT),
    method!(instant, c""), // deprecated alias
    method!(to_plain, doc::EXACTANDLOCALTIME_TO_PLAIN),
    method!(local, c""), // deprecated alias
    method!(to_tz, doc::EXACTTIME_TO_TZ, METH_O),
    method_vararg!(to_fixed_offset, doc::EXACTTIME_TO_FIXED_OFFSET),
    method!(to_system_tz, doc::EXACTTIME_TO_SYSTEM_TZ),
    method!(date, doc::LOCALTIME_DATE),
    method!(time, doc::LOCALTIME_TIME),
    method!(format_rfc3339, doc::OFFSETDATETIME_FORMAT_RFC3339),
    method!(
        parse_rfc3339,
        doc::OFFSETDATETIME_PARSE_RFC3339,
        METH_O | METH_CLASS
    ),
    method!(format_rfc2822, doc::OFFSETDATETIME_FORMAT_RFC2822),
    method!(
        parse_rfc2822,
        doc::OFFSETDATETIME_PARSE_RFC2822,
        METH_O | METH_CLASS
    ),
    method!(format_common_iso, doc::OFFSETDATETIME_FORMAT_COMMON_ISO),
    method!(
        parse_common_iso,
        doc::OFFSETDATETIME_PARSE_COMMON_ISO,
        METH_O | METH_CLASS
    ),
    method!(timestamp, doc::EXACTTIME_TIMESTAMP),
    method!(timestamp_millis, doc::EXACTTIME_TIMESTAMP_MILLIS),
    method!(timestamp_nanos, doc::EXACTTIME_TIMESTAMP_NANOS),
    method_kwargs!(
        from_timestamp,
        doc::OFFSETDATETIME_FROM_TIMESTAMP,
        METH_CLASS
    ),
    method_kwargs!(
        from_timestamp_millis,
        doc::OFFSETDATETIME_FROM_TIMESTAMP_MILLIS,
        METH_CLASS
    ),
    method_kwargs!(
        from_timestamp_nanos,
        doc::OFFSETDATETIME_FROM_TIMESTAMP_NANOS,
        METH_CLASS
    ),
    method_kwargs!(replace, doc::OFFSETDATETIME_REPLACE),
    method_kwargs!(replace_date, doc::OFFSETDATETIME_REPLACE_DATE),
    method_kwargs!(replace_time, doc::OFFSETDATETIME_REPLACE_TIME),
    method_vararg!(strptime, doc::OFFSETDATETIME_STRPTIME, METH_CLASS),
    method_kwargs!(add, doc::OFFSETDATETIME_ADD),
    method_kwargs!(subtract, doc::OFFSETDATETIME_SUBTRACT),
    method!(difference, doc::EXACTTIME_DIFFERENCE, METH_O),
    method_kwargs!(round, doc::OFFSETDATETIME_ROUND),
    PyMethodDef::zeroed(),
];

unsafe fn get_year(slf: *mut PyObject) -> PyReturn {
    OffsetDateTime::extract(slf).date.year.get().to_py()
}

unsafe fn get_month(slf: *mut PyObject) -> PyReturn {
    OffsetDateTime::extract(slf).date.month.get().to_py()
}

unsafe fn get_day(slf: *mut PyObject) -> PyReturn {
    OffsetDateTime::extract(slf).date.day.to_py()
}

unsafe fn get_hour(slf: *mut PyObject) -> PyReturn {
    OffsetDateTime::extract(slf).time.hour.to_py()
}

unsafe fn get_minute(slf: *mut PyObject) -> PyReturn {
    OffsetDateTime::extract(slf).time.minute.to_py()
}

unsafe fn get_second(slf: *mut PyObject) -> PyReturn {
    OffsetDateTime::extract(slf).time.second.to_py()
}

unsafe fn get_nanos(slf: *mut PyObject) -> PyReturn {
    OffsetDateTime::extract(slf).time.subsec.get().to_py()
}

unsafe fn get_offset(slf: *mut PyObject) -> PyReturn {
    TimeDelta::from_offset(OffsetDateTime::extract(slf).offset)
        .to_obj(State::for_obj(slf).time_delta_type)
}

static mut GETSETTERS: &[PyGetSetDef] = &[
    getter!(get_year named "year", "The year component"),
    getter!(get_month named "month", "The month component"),
    getter!(get_day named "day", "The day component"),
    getter!(get_hour named "hour", "The hour component"),
    getter!(get_minute named "minute", "The minute component"),
    getter!(get_second named "second", "The second component"),
    getter!(get_nanos named "nanosecond", "The nanosecond component"),
    getter!(get_offset named "offset", "The offset from UTC"),
    PyGetSetDef {
        name: NULL(),
        get: None,
        set: None,
        doc: NULL(),
        closure: NULL(),
    },
];

pub(crate) static mut SPEC: PyType_Spec =
    type_spec::<OffsetDateTime>(c"whenever.OffsetDateTime", unsafe { SLOTS });
