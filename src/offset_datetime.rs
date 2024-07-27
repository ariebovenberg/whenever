use core::ffi::{c_int, c_long, c_void, CStr};
use core::{mem, ptr::null_mut as NULL};
use pyo3_ffi::*;
use std::fmt::{self, Display, Formatter};

use crate::common::*;
use crate::datetime_delta::set_units_from_kwargs;
use crate::local_datetime::set_components_from_kwargs;
use crate::{
    date::Date,
    date_delta::DateDelta,
    datetime_delta::DateTimeDelta,
    instant::{Instant, MAX_INSTANT, MIN_INSTANT},
    local_datetime::DateTime,
    time::Time,
    time_delta::TimeDelta,
    zoned_datetime::ZonedDateTime,
    State,
};

#[derive(Debug, Eq, PartialEq, Ord, PartialOrd, Copy, Clone)]
pub(crate) struct OffsetDateTime {
    date: Date,
    time: Time,
    offset_secs: i32,
}

pub(crate) const SINGLETONS: &[(&CStr, OffsetDateTime); 0] = &[];

impl OffsetDateTime {
    pub(crate) const fn new_unchecked(date: Date, time: Time, offset_secs: i32) -> Self {
        OffsetDateTime {
            date,
            time,
            offset_secs,
        }
    }

    // WARNING: offset seconds should already be checked to be within bounds
    pub(crate) fn new(date: Date, time: Time, offset_secs: i32) -> Option<Self> {
        let ordinal_secs = i64::from(date.ord()) * i64::from(S_PER_DAY)
            + i64::from(time.total_seconds() - offset_secs);
        (MIN_INSTANT..=MAX_INSTANT)
            .contains(&ordinal_secs)
            .then_some(Self {
                date,
                time,
                offset_secs,
            })
    }

    pub(crate) const fn offset_secs(self) -> i32 {
        self.offset_secs
    }

    pub(crate) const fn time(self) -> Time {
        self.time
    }

    pub(crate) const fn date(self) -> Date {
        self.date
    }

    pub(crate) const fn as_tuple(self) -> (Date, Time, i32) {
        (self.date, self.time, self.offset_secs)
    }

    pub(crate) const fn instant(self) -> Instant {
        Instant::from_datetime(self.date, self.time).shift_secs_unchecked(-self.offset_secs as i64)
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
                    nanos,
                },
            offset_secs,
            ..
        } = self;
        let tz = TimeZone_FromTimeZone(Delta_FromDelta(0, offset_secs, 0, 0, DeltaType), NULL());
        defer_decref!(tz);
        DateTime_FromDateAndTime(
            year.into(),
            month.into(),
            day.into(),
            hour.into(),
            minute.into(),
            second.into(),
            (nanos / 1_000) as _,
            tz,
            DateTimeType,
        )
        .as_result()
    }

    // Returns None if the tzinfo is incorrect, or the UTC time is out of bounds
    pub(crate) unsafe fn from_py(dt: *mut PyObject, state: &State) -> PyResult<Option<Self>> {
        debug_assert!(PyObject_IsInstance(dt, state.py_api.DateTimeType.cast()).is_positive());
        let tzinfo = get_dt_tzinfo(dt);
        Ok(match PyObject_IsInstance(tzinfo, state.timezone_type) {
            1 => OffsetDateTime::new(
                Date {
                    year: PyDateTime_GET_YEAR(dt) as u16,
                    month: PyDateTime_GET_MONTH(dt) as u8,
                    day: PyDateTime_GET_DAY(dt) as u8,
                },
                Time {
                    hour: PyDateTime_DATE_GET_HOUR(dt) as u8,
                    minute: PyDateTime_DATE_GET_MINUTE(dt) as u8,
                    second: PyDateTime_DATE_GET_SECOND(dt) as u8,
                    nanos: PyDateTime_DATE_GET_MICROSECOND(dt) as u32 * 1_000,
                },
                offset_from_py_dt(dt)?,
            ),
            0 => None,
            _ => Err(py_err!())?,
        })
    }

    pub(crate) unsafe fn from_py_and_nanos_unchecked(
        dt: *mut PyObject,
        nanos: u32,
    ) -> PyResult<Self> {
        Ok(OffsetDateTime::new_unchecked(
            Date {
                year: PyDateTime_GET_YEAR(dt) as u16,
                month: PyDateTime_GET_MONTH(dt) as u8,
                day: PyDateTime_GET_DAY(dt) as u8,
            },
            Time {
                hour: PyDateTime_DATE_GET_HOUR(dt) as u8,
                minute: PyDateTime_DATE_GET_MINUTE(dt) as u8,
                second: PyDateTime_DATE_GET_SECOND(dt) as u8,
                nanos,
            },
            offset_from_py_dt(dt)?,
        ))
    }
}

impl DateTime {
    pub(crate) fn with_offset(self, offset_secs: i32) -> Option<OffsetDateTime> {
        OffsetDateTime::new(self.date, self.time, offset_secs)
    }
    pub(crate) const fn with_offset_unchecked(self, offset_secs: i32) -> OffsetDateTime {
        OffsetDateTime {
            date: self.date,
            time: self.time,
            offset_secs,
        }
    }
}

impl Instant {
    pub(crate) fn to_offset(self, secs: i32) -> Option<OffsetDateTime> {
        self.shift_secs(secs.into())
            .map(|i| i.to_datetime().with_offset_unchecked(secs))
    }
}

impl PyWrapped for OffsetDateTime {}

impl Display for OffsetDateTime {
    fn fmt(&self, f: &mut Formatter<'_>) -> fmt::Result {
        let &OffsetDateTime {
            date,
            time,
            offset_secs,
        } = self;
        write!(f, "{}T{}{}", date, time, offset_fmt(offset_secs))
    }
}

unsafe fn __new__(cls: *mut PyTypeObject, args: *mut PyObject, kwargs: *mut PyObject) -> PyReturn {
    let mut year: c_long = 0;
    let mut month: c_long = 0;
    let mut day: c_long = 0;
    let mut hour: c_long = 0;
    let mut minute: c_long = 0;
    let mut second: c_long = 0;
    let mut nanos: c_long = 0;
    let mut offset: *mut PyObject = NULL();

    // FUTURE: parse them manually, which is more efficient
    if PyArg_ParseTupleAndKeywords(
        args,
        kwargs,
        c"lll|lll$lO:OffsetDateTime".as_ptr(),
        vec![
            c"year".as_ptr() as *mut _,
            c"month".as_ptr() as *mut _,
            c"day".as_ptr() as *mut _,
            c"hour".as_ptr() as *mut _,
            c"minute".as_ptr() as *mut _,
            c"second".as_ptr() as *mut _,
            c"nanosecond".as_ptr() as *mut _,
            c"offset".as_ptr() as *mut _,
            NULL(),
        ]
        .as_mut_ptr(),
        &mut year,
        &mut month,
        &mut day,
        &mut hour,
        &mut minute,
        &mut second,
        &mut nanos,
        &mut offset,
    ) == 0
    {
        Err(py_err!())?
    }

    let date = Date::from_longs(year, month, day).ok_or_value_err("Invalid date")?;
    let time = Time::from_longs(hour, minute, second, nanos).ok_or_value_err("Invalid time")?;
    let offset_secs = extract_offset(offset, State::for_type(cls).time_delta_type)?;
    OffsetDateTime::new(date, time, offset_secs)
        .ok_or_value_err("Time is out of range")?
        .to_obj(cls)
}

pub(crate) unsafe fn extract_offset(
    obj: *mut PyObject,
    tdelta_cls: *mut PyTypeObject,
) -> PyResult<i32> {
    if obj.is_null() {
        Err(type_err!("Missing required keyword argument: 'offset'"))
    } else if obj.is_int() {
        let given_int = obj
            .to_i64()?
            // We've checked before that it's a py int
            .unwrap();
        if given_int.abs() >= 24 {
            Err(value_err!("offset must be between -24 and 24 hours"))
        } else {
            Ok((given_int * 3600) as _)
        }
    } else if Py_TYPE(obj) == tdelta_cls {
        let td = TimeDelta::extract(obj);
        if td.subsec_nanos() != 0 {
            Err(value_err!("offset must be a whole number of seconds"))
        } else if td.whole_seconds().abs() >= 24 * 3600 {
            Err(value_err!("offset must be between -24 and 24 hours"))
        } else {
            Ok(td.whole_seconds() as _)
        }
    } else {
        Err(type_err!(
            "offset must be an integer or TimeDelta instance, got {}",
            obj.repr()
        ))
    }
}

unsafe fn __repr__(slf: *mut PyObject) -> PyReturn {
    let OffsetDateTime {
        date,
        time,
        offset_secs,
    } = OffsetDateTime::extract(slf);
    format!(
        "OffsetDateTime({} {}{})",
        date,
        time,
        offset_fmt(offset_secs)
    )
    .to_py()
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
                Err(py_err!(
                    state.exc_implicitly_ignoring_dst,
                    "Subtracting a delta from a LocalDateTime implicitly ignores \
                     Daylight Saving Time. Instead, convert to a ZonedDateTime first \
                     using to_tz(). Or, if you're sure you want to ignore DST, \
                     explicitly pass ignore_dst=True."
                ))?
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
    TimeDelta::from_nanos_unchecked(inst_a.total_nanos() - inst_b.total_nanos())
        .to_obj(State::for_type(type_a).time_delta_type)
}

static mut SLOTS: &[PyType_Slot] = &[
    slotmethod!(Py_tp_new, __new__),
    slotmethod!(Py_tp_str, __str__, 1),
    slotmethod!(Py_tp_repr, __repr__, 1),
    slotmethod!(Py_tp_richcompare, __richcmp__),
    slotmethod!(Py_nb_subtract, __sub__, 2),
    PyType_Slot {
        slot: Py_tp_doc,
        pfunc: c"A datetime type with a fixed UTC offset".as_ptr() as *mut c_void,
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
        Err(type_err!("Can't compare different types"))
    }
}

unsafe fn instant(slf: *mut PyObject, _: *mut PyObject) -> PyReturn {
    OffsetDateTime::extract(slf)
        .instant()
        .to_obj(State::for_obj(slf).instant_type)
}

unsafe fn to_fixed_offset(slf_obj: *mut PyObject, args: &[*mut PyObject]) -> PyReturn {
    match *args {
        [] => Ok(newref(slf_obj)),
        [offset] => {
            let cls = Py_TYPE(slf_obj);
            let offset_secs = extract_offset(offset, State::for_type(cls).time_delta_type)?;
            OffsetDateTime::extract(slf_obj)
                .instant()
                .to_offset(offset_secs)
                .ok_or_value_err("Resulting local date is out of range")?
                .to_obj(cls)
        }
        _ => Err(type_err!("to_fixed_offset() takes at most 1 argument")),
    }
}

unsafe fn to_tz(slf: *mut PyObject, tz: *mut PyObject) -> PyReturn {
    let type_ = Py_TYPE(slf);
    let &State {
        zoneinfo_type,
        py_api,
        zoned_datetime_type,
        ..
    } = State::for_type(type_);
    let zoneinfo = call1(zoneinfo_type, tz)?;
    defer_decref!(zoneinfo);
    OffsetDateTime::extract(slf)
        .instant()
        .to_tz(py_api, zoneinfo)?
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
        Err(value_err!("Invalid pickle data"))?;
    }
    OffsetDateTime::new_unchecked(
        Date {
            year: unpack_one!(packed, u16),
            month: unpack_one!(packed, u8),
            day: unpack_one!(packed, u8),
        },
        Time {
            hour: unpack_one!(packed, u8),
            minute: unpack_one!(packed, u8),
            second: unpack_one!(packed, u8),
            nanos: unpack_one!(packed, u32),
        },
        unpack_one!(packed, i32),
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
            if kwargs.len() == 1 && key.kwarg_eq(state.str_ignore_dst) && value == Py_True() =>
        {
            Ok(())
        }
        Some((key, _)) => Err(type_err!("Unknown keyword argument: {}", key.repr())),
        _ => Err(py_err!(state.exc_implicitly_ignoring_dst, msg)),
    }
}

unsafe fn replace_date(
    slf: *mut PyObject,
    cls: *mut PyTypeObject,
    args: &[*mut PyObject],
    kwargs: &mut KwargIter,
) -> PyReturn {
    let OffsetDateTime {
        time, offset_secs, ..
    } = OffsetDateTime::extract(slf);
    let state = State::for_type(cls);

    check_ignore_dst_kwarg(kwargs, state, IGNORE_DST_MSG)?;

    let &[arg] = args else {
        Err(type_err!("replace() takes exactly 1 positional argument"))?
    };
    if Py_TYPE(arg) == state.date_type {
        OffsetDateTime::new(Date::extract(arg), time, offset_secs)
            .ok_or_value_err("New datetime is out of range")?
            .to_obj(cls)
    } else {
        Err(type_err!("date must be a whenever.Date instance"))
    }
}

unsafe fn replace_time(
    slf: *mut PyObject,
    cls: *mut PyTypeObject,
    args: &[*mut PyObject],
    kwargs: &mut KwargIter,
) -> PyReturn {
    let OffsetDateTime {
        date, offset_secs, ..
    } = OffsetDateTime::extract(slf);
    let state = State::for_type(cls);
    check_ignore_dst_kwarg(kwargs, state, IGNORE_DST_MSG)?;

    let &[arg] = args else {
        Err(type_err!("replace() takes exactly 1 positional argument"))?
    };

    if Py_TYPE(arg) == state.time_type {
        OffsetDateTime::new(date, Time::extract(arg), offset_secs)
            .ok_or_value_err("New datetime is out of range")?
            .to_obj(cls)
    } else {
        Err(type_err!("time must be a whenever.Time instance"))
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
        Err(type_err!("replace() takes no positional arguments"))?
    }
    let state = State::for_type(cls);
    let OffsetDateTime {
        date,
        time,
        offset_secs,
    } = OffsetDateTime::extract(slf);
    let mut year = date.year.into();
    let mut month = date.month.into();
    let mut day = date.day.into();
    let mut hour = time.hour.into();
    let mut minute = time.minute.into();
    let mut second = time.second.into();
    let mut nanos = time.nanos as _;
    let mut offset_secs = offset_secs;
    let mut ignore_dst = false;

    handle_kwargs("replace", kwargs, |key, value, eq| {
        if eq(key, state.str_ignore_dst) {
            ignore_dst = value == Py_True();
        } else if eq(key, state.str_offset) {
            offset_secs = extract_offset(value, state.time_delta_type)?;
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
                state,
                eq,
            );
        }
        Ok(true)
    })?;

    if !ignore_dst {
        Err(py_err!(state.exc_implicitly_ignoring_dst, IGNORE_DST_MSG))?
    }

    let date = Date::from_longs(year, month, day).ok_or_value_err("Invalid date")?;
    let time = Time::from_longs(hour, minute, second, nanos).ok_or_value_err("Invalid time")?;
    OffsetDateTime::new(date, time, offset_secs)
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
    let (secs, subsec_nanos) = state.time_ns()?;

    let &[offset] = args else {
        Err(type_err!("now() takes exactly 1 positional argument"))?
    };

    check_ignore_dst_kwarg(
        kwargs,
        state,
        "Getting the current time with a fixed offset implicitly ignores DST \
         and other timezone changes. Instead, use `Instant.now()` or \
         `ZonedDateTime.now(<tz name>)` if you know the timezone. \
         Or, if you want to ignore DST and accept potentially incorrect offsets, \
         pass `ignore_dst=True` to this method.",
    )?;

    let offset_secs = extract_offset(offset, state.time_delta_type)?;
    // FUTURE: Conversion to Instant can be done a bit more efficiently
    let DateTime { date, time } =
        Instant::from_timestamp_nanos(secs as i128 * 1_000_000_000 + i128::from(subsec_nanos))
            .ok_or_value_err("SystemTime out of range")?
            .shift_secs_unchecked(offset_secs.into())
            .to_datetime();
    // Technically this can fail if the system time is set beyond year 9999
    OffsetDateTime::new_unchecked(date, time, offset_secs).to_obj(cls.cast())
}

unsafe fn from_py_datetime(cls: *mut PyObject, dt: *mut PyObject) -> PyReturn {
    if PyDateTime_Check(dt) == 0 {
        Err(type_err!("Argument must be a datetime.datetime instance"))?
    }
    OffsetDateTime::from_py(dt, State::for_type(cls.cast()))?
        .ok_or_else(|| {
            value_err!(
                "Argument must have a `datetime.timezone` tzinfo and be within range, got {}",
                dt.repr()
            )
        })?
        .to_obj(cls.cast())
}

pub(crate) unsafe fn local(slf: *mut PyObject, _: *mut PyObject) -> PyReturn {
    OffsetDateTime::extract(slf)
        .without_offset()
        .to_obj(State::for_obj(slf).local_datetime_type)
}

pub(crate) unsafe fn timestamp(slf: *mut PyObject, _: *mut PyObject) -> PyReturn {
    OffsetDateTime::extract(slf).instant().timestamp().to_py()
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
    let mut months = 0;
    let mut days = 0;
    let mut nanos = 0;
    let mut ignore_dst = false;

    match *args {
        [arg] => {
            match kwargs.next() {
                Some((key, value)) if kwargs.len() == 1 && key.kwarg_eq(state.str_ignore_dst) => {
                    ignore_dst = value == Py_True();
                }
                None => {}
                _ => Err(type_err!(
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
                Err(type_err!("{}() argument must be a delta", fname))?
            }
        }
        [] => {
            handle_kwargs(fname, kwargs, |key, value, eq| {
                if eq(key, state.str_ignore_dst) {
                    ignore_dst = value == Py_True();
                    Ok(true)
                } else {
                    set_units_from_kwargs(key, value, &mut months, &mut days, &mut nanos, state, eq)
                }
            })?;
        }
        _ => Err(type_err!(
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
        Err(py_err!(
            state.exc_implicitly_ignoring_dst,
            "Adding time units to a LocalDateTime implicitly ignores \
            Daylight Saving Time. Instead, convert to a ZonedDateTime first \
            using assume_tz(). Or, if you're sure you want to ignore DST, \
            explicitly pass ignore_dst=True."
        ))?
    }
    let OffsetDateTime {
        date,
        time,
        offset_secs,
    } = OffsetDateTime::extract(slf);
    DateTime { date, time }
        .shift_date(months, days)
        .and_then(|dt| dt.shift_nanos(nanos))
        .and_then(|dt| dt.with_offset(offset_secs))
        .ok_or_else(|| value_err!("Result of {}() out of range", fname))?
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
        Err(type_err!(
            "difference() argument must be an OffsetDateTime, 
                Instant, ZonedDateTime, or SystemDateTime"
        ))?
    };
    TimeDelta::from_nanos_unchecked(inst_a.total_nanos() - inst_b.total_nanos())
        .to_obj(state.time_delta_type)
}

unsafe fn __reduce__(slf: *mut PyObject, _: *mut PyObject) -> PyReturn {
    let OffsetDateTime {
        date: Date { year, month, day },
        time:
            Time {
                hour,
                minute,
                second,
                nanos,
            },
        offset_secs,
    } = OffsetDateTime::extract(slf);
    let data = pack![year, month, day, hour, minute, second, nanos, offset_secs];
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
) -> PyResult<i32> {
    let mut ignore_dst = false;
    let mut offset_secs = None;
    if args.len() != 1 {
        Err(type_err!(
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
        Err(py_err!(exc_implicitly_ignoring_dst, IGNORE_DST_MSG))?
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
    let offset_secs =
        check_from_timestamp_args_return_offset("from_timestamp", args, kwargs, state)?;

    match args[0].to_i64()? {
        Some(ts) => Instant::from_timestamp(ts),
        None => Instant::from_timestamp_f64(
            args[0]
                .to_f64()?
                .ok_or_type_err("Timestamp must be an integer or float")?,
        ),
    }
    .ok_or_value_err("Timestamp is out of range")?
    .shift_secs_unchecked(offset_secs as i64)
    .to_datetime()
    .with_offset_unchecked(offset_secs)
    .to_obj(cls)
}

unsafe fn from_timestamp_millis(
    _: *mut PyObject,
    cls: *mut PyTypeObject,
    args: &[*mut PyObject],
    kwargs: &mut KwargIter,
) -> PyReturn {
    let state = State::for_type(cls);
    let offset_secs =
        check_from_timestamp_args_return_offset("from_timestamp_millis", args, kwargs, state)?;
    Instant::from_timestamp_millis(
        args[0]
            .to_i64()?
            .ok_or_type_err("timestamp must be an integer")?,
    )
    .ok_or_value_err("timestamp is out of range")?
    .shift_secs_unchecked(offset_secs as i64)
    .to_datetime()
    .with_offset_unchecked(offset_secs)
    .to_obj(cls)
}

unsafe fn from_timestamp_nanos(
    _: *mut PyObject,
    cls: *mut PyTypeObject,
    args: &[*mut PyObject],
    kwargs: &mut KwargIter,
) -> PyReturn {
    let state = State::for_type(cls);
    let offset_secs =
        check_from_timestamp_args_return_offset("from_timestamp_nanos", args, kwargs, state)?;
    Instant::from_timestamp_nanos(
        args[0]
            .to_i128()?
            .ok_or_type_err("timestamp must be an integer")?,
    )
    .ok_or_value_err("timestamp is out of range")?
    .shift_secs_unchecked(offset_secs as i64)
    .to_datetime()
    .with_offset_unchecked(offset_secs)
    .to_obj(cls)
}

// parse ±HH:MM[:SS] or [Zz]
fn parse_hms_offset(s: &[u8]) -> Option<i32> {
    let sign = match s.first() {
        Some(b'+') => 1,
        Some(b'-') => -1,
        Some(b'Z') if s.len() == 1 => return Some(0),
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
        .filter(|s| s.abs() < 24 * 3600)
        .map(|s| sign * s)
    } else {
        None
    }
}

unsafe fn parse_common_iso(cls: *mut PyObject, s_obj: *mut PyObject) -> PyReturn {
    OffsetDateTime::parse(s_obj.to_utf8()?.ok_or_type_err("Expected a string")?)
        .ok_or_else(|| value_err!("Invalid format: {}", s_obj.repr()))?
        .to_obj(cls.cast())
}

// exactly "±HH:MM" or "Z|z"
fn parse_rfc3339_offset(s: &[u8]) -> Option<i32> {
    let sign = match s.first() {
        Some(b'+') => 1,
        Some(b'-') => -1,
        Some(b'Z' | b'z') if s.len() == 1 => return Some(0),
        _ => return None,
    };
    if s.len() == 6 && s[3] == b':' {
        Some(
            sign * ((parse_digit_max(s, 1, b'2')? * 10 + parse_digit(s, 2)?) as i32 * 3600
                + (parse_digit_max(s, 4, b'5')? * 10 + parse_digit(s, 5)?) as i32 * 60),
        )
        .filter(|secs| secs.abs() < 24 * 3600)
    } else {
        None
    }
}

unsafe fn parse_rfc3339(cls: *mut PyObject, s_obj: *mut PyObject) -> PyReturn {
    let s = &mut s_obj.to_utf8()?.ok_or_type_err("Expected a string")?;
    let raise = || value_err!("Invalid RFC 3339 format: {}", s_obj.repr());
    // at least: "YYYY-MM-DDTHH:MM:SSZ"
    if s.len() < 20 {
        Err(raise())?
    }
    let date = Date::parse_partial(s).ok_or_else(raise)?;
    // parse the separator
    if !(s[0] == b'T' || s[0] == b't' || s[0] == b' ' || s[0] == b'_') {
        Err(raise())?
    }
    *s = &s[1..];
    let time = Time::parse_partial(s).ok_or_else(raise)?;
    let offset_secs = parse_rfc3339_offset(s).ok_or_else(raise)?;
    OffsetDateTime::new(date, time, offset_secs)
        .ok_or_else(raise)?
        .to_obj(cls.cast())
}

unsafe fn strptime(cls: *mut PyObject, args: &[*mut PyObject]) -> PyReturn {
    let state = State::for_type(cls.cast());
    if args.len() != 2 {
        Err(type_err!("strptime() takes exactly 2 arguments"))?;
    }
    // OPTIMIZE: get this working with vectorcall
    let parsed =
        PyObject_Call(state.strptime, steal!((args[0], args[1]).to_py()?), NULL()).as_result()?;
    defer_decref!(parsed);

    OffsetDateTime::from_py(parsed, state)?
        .ok_or_else(|| {
            value_err!(
                "parsed datetime must have a timezone and be within range, got {}",
                (parsed as *mut PyObject).repr()
            )
        })?
        .to_obj(cls.cast())
}

pub(crate) fn offset_fmt_rfc3339(secs: i32) -> String {
    let (sign, secs) = if secs < 0 { ('-', -secs) } else { ('+', secs) };
    format!("{}{:02}:{:02}", sign, secs / 3600, (secs % 3600) / 60)
}

unsafe fn format_rfc3339(slf: *mut PyObject, _: *mut PyObject) -> PyReturn {
    let OffsetDateTime {
        date,
        time,
        offset_secs,
    } = OffsetDateTime::extract(slf);
    format!("{} {}{}", date, time, offset_fmt_rfc3339(offset_secs)).to_py()
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
    OffsetDateTime::from_py(py_dt, state)?
        .ok_or_else(|| {
            value_err!(
                "parsed datetime must have a timezone and be in range, got {}",
                s_obj.repr()
            )
        })?
        .to_obj(cls.cast())
}

// On python 3.9, parsing sometimes raises a TypeError.
// We need special handling for this case.
#[cfg(not(Py_3_10))]
unsafe fn parse_rfc2822(cls: *mut PyObject, s_obj: *mut PyObject) -> PyReturn {
    let state = State::for_type(cls.cast());
    if !s_obj.is_str() {
        Err(type_err!("Argument must be a string"))?
    }
    let py_dt = call1(state.parse_rfc2822, s_obj).map_err(|e| {
        if PyErr_ExceptionMatches(PyExc_TypeError) != 0 {
            PyErr_Clear();
            value_err!("Invalid format: {}", s_obj.repr())
        } else {
            e
        }
    })?;
    defer_decref!(py_dt);
    OffsetDateTime::from_py(py_dt, state)?
        .ok_or_else(|| {
            value_err!(
                "parsed datetime must have a timezone and be in range, got {}",
                s_obj.repr()
            )
        })?
        .to_obj(cls.cast())
}

static mut METHODS: &[PyMethodDef] = &[
    // FUTURE: get docstrings from Python implementation
    method!(identity2 named "__copy__", ""),
    method!(identity2 named "__deepcopy__", "", METH_O),
    method!(__reduce__, ""),
    method_kwargs!(
        now,
        "Create a new instance representing the current time",
        METH_CLASS
    ),
    method!(exact_eq, "Exact equality", METH_O),
    method!(py_datetime, "Convert to a `datetime.datetime`"),
    method!(
        from_py_datetime,
        "Create a new instance from a `datetime.datetime`",
        METH_O | METH_CLASS
    ),
    method!(instant, "Get the underlying instant"),
    method!(local, "Get the local date and time"),
    method!(to_tz, "Convert to a `ZonedDateTime` with given tz", METH_O),
    method_vararg!(
        to_fixed_offset,
        "Convert to a new instance with a different offset"
    ),
    method!(to_system_tz, "Convert to a datetime to the system timezone"),
    method!(date, "The date component"),
    method!(time, "The time component"),
    method!(format_rfc3339, "Format according to RFC3339"),
    method!(
        parse_rfc3339,
        "Create a new instance from an RFC3339 timestamp",
        METH_O | METH_CLASS
    ),
    method!(format_rfc2822, "Format according to RFC2822"),
    method!(
        parse_rfc2822,
        "Create a new instance from an RFC2822 timestamp",
        METH_O | METH_CLASS
    ),
    method!(
        format_common_iso,
        "Format according to the common ISO8601 style"
    ),
    method!(
        parse_common_iso,
        "Parse from the common ISO8601 format",
        METH_O | METH_CLASS
    ),
    method!(timestamp, "Convert to a UNIX timestamp"),
    method!(
        timestamp_millis,
        "Convert to a UNIX timestamp in milliseconds"
    ),
    method!(
        timestamp_nanos,
        "Convert to a UNIX timestamp in nanoseconds"
    ),
    method_kwargs!(
        from_timestamp,
        "Create a new instance from a UNIX timestamp",
        METH_CLASS
    ),
    method_kwargs!(
        from_timestamp_millis,
        "Create a new instance from a UNIX timestamp in milliseconds",
        METH_CLASS
    ),
    method_kwargs!(
        from_timestamp_nanos,
        "Create a new instance from a UNIX timestamp",
        METH_CLASS
    ),
    method_kwargs!(
        replace,
        "Return a new instance with the specified fields replaced"
    ),
    method_kwargs!(replace_date, "Return a new instance with the date replaced"),
    method_kwargs!(replace_time, "Return a new instance with the time replaced"),
    method_vararg!(strptime, "Parse a string with strptime", METH_CLASS),
    method_kwargs!(add, "Add time units"),
    method_kwargs!(subtract, "Subtract time units"),
    method!(
        difference,
        "Calculate the difference between two instances",
        METH_O
    ),
    PyMethodDef::zeroed(),
];

unsafe fn get_year(slf: *mut PyObject) -> PyReturn {
    OffsetDateTime::extract(slf).date.year.to_py()
}

unsafe fn get_month(slf: *mut PyObject) -> PyReturn {
    OffsetDateTime::extract(slf).date.month.to_py()
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
    OffsetDateTime::extract(slf).time.nanos.to_py()
}

unsafe fn get_offset(slf: *mut PyObject) -> PyReturn {
    TimeDelta::from_secs_unchecked(OffsetDateTime::extract(slf).offset_secs as i64)
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

static IGNORE_DST_MSG: &str =
    "Adjusting a fixed offset datetime implicitly ignores DST and other timezone changes. \
    To perform DST-safe operations, convert to a ZonedDateTime first using `to_tz()`. \
    Or, if you don't know the timezone and accept potentially incorrect results \
    during DST transitions, pass `ignore_dst=True`.";

type_spec!(OffsetDateTime, SLOTS);
