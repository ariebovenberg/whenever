use core::ffi::{c_int, c_long, c_void, CStr};
use core::{mem, ptr::null_mut as NULL};
use pyo3_ffi::*;

use crate::common::*;
use crate::datetime_delta::handle_exact_unit;
use crate::time_delta::{MAX_HOURS, MAX_MICROSECONDS, MAX_MILLISECONDS, MAX_MINUTES, MAX_SECS};
use crate::{
    date::Date,
    local_datetime::DateTime,
    offset_datetime::{self, OffsetDateTime},
    time::Time,
    time_delta::TimeDelta,
    zoned_datetime::ZonedDateTime,
    State,
};

#[derive(Debug, Eq, PartialEq, Ord, PartialOrd, Copy, Clone)]
pub(crate) struct Instant {
    secs: i64, // MIN_INSTANT <= secs <= MAX_INSTANT
    nanos: u32, // 0 <= nanos < 1_000_000_000
               // FUTURE: make use of padding to cache the date value?
}

pub(crate) const SINGLETONS: &[(&CStr, Instant); 2] = &[
    (
        c"MIN",
        Instant {
            secs: MIN_INSTANT,
            nanos: 0,
        },
    ),
    (
        c"MAX",
        Instant {
            secs: MAX_INSTANT,
            nanos: 999_999_999,
        },
    ),
];

pub(crate) const UNIX_EPOCH_INSTANT: i64 = 62_135_683_200; // 1970-01-01 in seconds after 0000-12-31
pub(crate) const MIN_INSTANT: i64 = 24 * 60 * 60;
pub(crate) const MAX_INSTANT: i64 = 315_537_983_999;
const MIN_EPOCH: i64 = MIN_INSTANT - UNIX_EPOCH_INSTANT;
const MAX_EPOCH: i64 = MAX_INSTANT - UNIX_EPOCH_INSTANT;

impl Instant {
    pub(crate) fn to_datetime(self) -> DateTime {
        DateTime {
            date: Date::from_ord_unchecked((self.secs / 86400) as _),
            time: Time {
                hour: ((self.secs % 86400) / 3600) as _,
                minute: ((self.secs % 3600) / 60) as _,
                second: (self.secs % 60) as _,
                nanos: self.nanos,
            },
        }
    }

    pub(crate) const fn from_datetime(
        date: Date,
        Time {
            hour,
            minute,
            second,
            nanos,
        }: Time,
    ) -> Self {
        let secs =
            date.ord() as i64 * 86400 + hour as i64 * 3600 + minute as i64 * 60 + second as i64;
        Instant { secs, nanos }
    }

    pub(crate) fn from_nanos(nanos: i128) -> Option<Self> {
        let secs = (nanos / 1_000_000_000).try_into().ok()?;
        (secs > MIN_INSTANT && secs < MAX_INSTANT).then_some(Instant {
            secs,
            nanos: (nanos % 1_000_000_000) as u32,
        })
    }

    pub(crate) const fn total_nanos(&self) -> i128 {
        self.secs as i128 * 1_000_000_000 + self.nanos as i128
    }

    pub(crate) const fn whole_secs(&self) -> i64 {
        self.secs
    }

    pub(crate) const fn subsec_nanos(&self) -> u32 {
        self.nanos
    }

    pub(crate) fn timestamp(&self) -> i64 {
        self.secs - UNIX_EPOCH_INSTANT
    }

    pub(crate) fn timestamp_millis(&self) -> i64 {
        (self.secs - UNIX_EPOCH_INSTANT) * 1_000 + self.nanos as i64 / 1_000_000
    }

    pub(crate) fn timestamp_nanos(&self) -> i128 {
        (self.secs - UNIX_EPOCH_INSTANT) as i128 * 1_000_000_000 + self.nanos as i128
    }

    pub(crate) fn from_timestamp(timestamp: i64) -> Option<Self> {
        timestamp
            .checked_add(UNIX_EPOCH_INSTANT)
            .filter(|ts| (MIN_INSTANT..=MAX_INSTANT).contains(ts))
            .map(|secs| Instant { secs, nanos: 0 })
    }

    pub(crate) fn from_timestamp_f64(timestamp: f64) -> Option<Self> {
        (MIN_EPOCH as f64..MAX_EPOCH as f64)
            .contains(&timestamp)
            .then(|| Instant {
                secs: (timestamp.floor() as i64 + UNIX_EPOCH_INSTANT),
                nanos: (timestamp * 1_000_000_000_f64).rem_euclid(1_000_000_000_f64) as u32,
            })
    }

    pub(crate) fn from_timestamp_millis(timestamp: i64) -> Option<Self> {
        let secs = timestamp.div_euclid(1_000) + UNIX_EPOCH_INSTANT;
        ((MIN_INSTANT..=MAX_INSTANT).contains(&secs)).then(|| Instant {
            secs,
            nanos: timestamp.rem_euclid(1_000) as u32 * 1_000_000,
        })
    }

    pub(crate) fn from_timestamp_nanos(timestamp: i128) -> Option<Self> {
        i64::try_from(timestamp.div_euclid(1_000_000_000))
            .ok()
            .map(|s| s + UNIX_EPOCH_INSTANT)
            .filter(|s| (MIN_INSTANT..=MAX_INSTANT).contains(s))
            .map(|secs| Instant {
                secs,
                nanos: timestamp.rem_euclid(1_000_000_000) as u32,
            })
    }

    pub(crate) fn shift(&self, nanos: i128) -> Option<Instant> {
        self.total_nanos()
            .checked_add(nanos)
            .and_then(Instant::from_nanos)
    }

    pub(crate) const fn shift_secs_unchecked(&self, secs: i64) -> Self {
        Instant {
            secs: self.secs + secs,
            nanos: self.nanos,
        }
    }

    pub(crate) const fn shift_secs(&self, secs: i64) -> Option<Self> {
        let new_secs = self.secs + secs;
        if MIN_INSTANT <= new_secs && new_secs <= MAX_INSTANT {
            Some(Instant {
                secs: new_secs,
                nanos: self.nanos,
            })
        } else {
            None
        }
    }

    pub(crate) unsafe fn to_py(
        self,
        &PyDateTime_CAPI {
            DateTime_FromDateAndTime,
            TimeZone_UTC,
            DateTimeType,
            ..
        }: &PyDateTime_CAPI,
    ) -> PyReturn {
        let DateTime {
            date: Date { year, month, day },
            time:
                Time {
                    hour,
                    minute,
                    second,
                    nanos,
                },
        } = self.to_datetime();
        DateTime_FromDateAndTime(
            year.into(),
            month.into(),
            day.into(),
            hour.into(),
            minute.into(),
            second.into(),
            (nanos / 1_000) as _,
            TimeZone_UTC,
            DateTimeType,
        )
        .as_result()
    }

    pub(crate) unsafe fn to_py_ignore_nanos(
        self,
        &PyDateTime_CAPI {
            DateTime_FromDateAndTime,
            TimeZone_UTC,
            DateTimeType,
            ..
        }: &PyDateTime_CAPI,
    ) -> PyReturn {
        let DateTime {
            date: Date { year, month, day },
            time:
                Time {
                    hour,
                    minute,
                    second,
                    ..
                },
        } = self.to_datetime();
        DateTime_FromDateAndTime(
            year.into(),
            month.into(),
            day.into(),
            hour.into(),
            minute.into(),
            second.into(),
            0,
            TimeZone_UTC,
            DateTimeType,
        )
        .as_result()
    }

    pub(crate) unsafe fn from_py(dt: *mut PyObject, state: &State) -> Option<Self> {
        let tzinfo = get_dt_tzinfo(dt);
        (tzinfo == state.py_api.TimeZone_UTC).then_some(Instant::from_datetime(
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
        ))
    }

    #[cfg(target_pointer_width = "64")]
    pub(crate) const fn pyhash(&self) -> Py_hash_t {
        hash_combine(self.secs as Py_hash_t, self.nanos as Py_hash_t)
    }

    #[cfg(target_pointer_width = "32")]
    pub(crate) const fn pyhash(&self) -> Py_hash_t {
        hash_combine(
            self.secs as Py_hash_t,
            hash_combine((self.secs >> 32) as Py_hash_t, self.nanos as Py_hash_t),
        )
    }
}

unsafe fn __new__(_: *mut PyTypeObject, _: *mut PyObject, _: *mut PyObject) -> PyReturn {
    Err(py_err!(
        PyExc_TypeError,
        "Instant cannot be instantiated directly"
    ))
}

unsafe fn from_utc(cls: *mut PyTypeObject, args: *mut PyObject, kwargs: *mut PyObject) -> PyReturn {
    let mut year: c_long = 0;
    let mut month: c_long = 0;
    let mut day: c_long = 0;
    let mut hour: c_long = 0;
    let mut minute: c_long = 0;
    let mut second: c_long = 0;
    let mut nanos: c_long = 0;

    // FUTURE: parse them manually, which is more efficient
    if PyArg_ParseTupleAndKeywords(
        args,
        kwargs,
        c"lll|lll$l:Instant.from_utc".as_ptr(),
        vec![
            c"year".as_ptr() as *mut _,
            c"month".as_ptr() as *mut _,
            c"day".as_ptr() as *mut _,
            c"hour".as_ptr() as *mut _,
            c"minute".as_ptr() as *mut _,
            c"second".as_ptr() as *mut _,
            c"nanosecond".as_ptr() as *mut _,
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
    ) == 0
    {
        return Err(py_err!());
    }

    Instant::from_datetime(
        Date::from_longs(year, month, day).ok_or_value_err("Invalid date")?,
        Time::from_longs(hour, minute, second, nanos).ok_or_value_err("Invalid time")?,
    )
    .to_obj(cls)
}

impl PyWrapped for Instant {}

unsafe fn __repr__(slf: *mut PyObject) -> PyReturn {
    let DateTime { date, time } = Instant::extract(slf).to_datetime();
    format!("Instant({} {}Z)", date, time).to_py()
}

unsafe fn __str__(slf: *mut PyObject) -> PyReturn {
    let DateTime { date, time } = Instant::extract(slf).to_datetime();
    format!("{}T{}Z", date, time).to_py()
}

unsafe fn format_rfc3339(slf: *mut PyObject, _: *mut PyObject) -> PyReturn {
    let DateTime { date, time } = Instant::extract(slf).to_datetime();
    format!("{} {}Z", date, time).to_py()
}

unsafe fn __richcmp__(a_obj: *mut PyObject, b_obj: *mut PyObject, op: c_int) -> PyReturn {
    let type_a = Py_TYPE(a_obj);
    let type_b = Py_TYPE(b_obj);
    let inst_a = Instant::extract(a_obj);
    let inst_b = if type_b == type_a {
        Instant::extract(b_obj)
    } else if type_b == State::for_type(type_a).zoned_datetime_type {
        ZonedDateTime::extract(b_obj).instant()
    } else if type_b == State::for_type(type_a).offset_datetime_type
        || type_b == State::for_type(type_a).system_datetime_type
    {
        OffsetDateTime::extract(b_obj).instant()
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

unsafe extern "C" fn __hash__(slf: *mut PyObject) -> Py_hash_t {
    hashmask(Instant::extract(slf).pyhash())
}

unsafe fn __sub__(obj_a: *mut PyObject, obj_b: *mut PyObject) -> PyReturn {
    let type_a = Py_TYPE(obj_a);
    let type_b = Py_TYPE(obj_b);

    // Easy case: UTC - UTC
    let (inst_a, inst_b) = if type_a == type_b {
        (Instant::extract(obj_a), Instant::extract(obj_b))
    // Other cases are more difficult, as they can be triggered
    // by reflexive operations with arbitrary types.
    // We need to eliminate them carefully.
    } else {
        let mod_a = PyType_GetModule(type_a);
        let mod_b = PyType_GetModule(type_b);
        if mod_a == mod_b {
            let inst_b = if type_b == State::for_mod(mod_a).zoned_datetime_type {
                ZonedDateTime::extract(obj_b).instant()
            } else if type_b == State::for_mod(mod_a).offset_datetime_type
                || type_b == State::for_mod(mod_a).system_datetime_type
            {
                OffsetDateTime::extract(obj_b).instant()
            } else {
                return _shift(obj_a, obj_b, true);
            };
            (Instant::extract(obj_a), inst_b)
        } else {
            return Ok(newref(Py_NotImplemented()));
        }
    };
    TimeDelta::from_nanos_unchecked(inst_a.total_nanos() - inst_b.total_nanos())
        .to_obj(State::for_type(type_a).time_delta_type)
}

unsafe fn __add__(dt: *mut PyObject, delta_obj: *mut PyObject) -> PyReturn {
    if PyType_GetModule(Py_TYPE(dt)) == PyType_GetModule(Py_TYPE(delta_obj)) {
        _shift(dt, delta_obj, false)
    } else {
        Ok(newref(Py_NotImplemented()))
    }
}

#[inline]
unsafe fn _shift(obj_a: *mut PyObject, obj_b: *mut PyObject, negate: bool) -> PyReturn {
    debug_assert_eq!(
        PyType_GetModule(Py_TYPE(obj_a)),
        PyType_GetModule(Py_TYPE(obj_b))
    );
    let type_a = Py_TYPE(obj_a);
    let mut nanos = if Py_TYPE(obj_b) == State::for_type(type_a).time_delta_type {
        TimeDelta::extract(obj_b).total_nanos()
    } else {
        return Ok(newref(Py_NotImplemented()));
    };
    if negate {
        nanos = -nanos;
    }
    Instant::extract(obj_a)
        .shift(nanos)
        .ok_or_value_err("Resulting datetime is out of range")?
        .to_obj(type_a)
}

static mut SLOTS: &[PyType_Slot] = &[
    slotmethod!(Py_tp_new, __new__),
    slotmethod!(Py_tp_repr, __repr__, 1),
    slotmethod!(Py_tp_str, __str__, 1),
    slotmethod!(Py_tp_richcompare, __richcmp__),
    slotmethod!(Py_nb_subtract, __sub__, 2),
    slotmethod!(Py_nb_add, __add__, 2),
    PyType_Slot {
        slot: Py_tp_doc,
        pfunc: c"A UTC datetime type".as_ptr() as *mut c_void,
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
        (Instant::extract(obj_a) == Instant::extract(obj_b)).to_py()
    } else {
        Err(type_err!("Can't compare different types"))
    }
}

unsafe fn __reduce__(slf: *mut PyObject, _: *mut PyObject) -> PyReturn {
    let Instant { secs, nanos } = Instant::extract(slf);
    let data = pack![secs, nanos];
    (
        State::for_obj(slf).unpickle_instant,
        steal!((steal!(data.to_py()?),).to_py()?),
    )
        .to_py()
}

pub(crate) unsafe fn unpickle(module: *mut PyObject, arg: *mut PyObject) -> PyReturn {
    let mut packed = arg.to_bytes()?.ok_or_value_err("Invalid pickle data")?;
    if packed.len() != 12 {
        Err(value_err!("Invalid pickle data"))?;
    }
    Instant {
        secs: unpack_one!(packed, i64),
        nanos: unpack_one!(packed, u32),
    }
    .to_obj(State::for_mod(module).instant_type)
}

unsafe fn timestamp(slf: *mut PyObject, _: *mut PyObject) -> PyReturn {
    Instant::extract(slf).timestamp().to_py()
}

unsafe fn timestamp_millis(slf: *mut PyObject, _: *mut PyObject) -> PyReturn {
    Instant::extract(slf).timestamp_millis().to_py()
}

unsafe fn timestamp_nanos(slf: *mut PyObject, _: *mut PyObject) -> PyReturn {
    Instant::extract(slf).timestamp_nanos().to_py()
}

unsafe fn from_timestamp(cls: *mut PyObject, ts: *mut PyObject) -> PyReturn {
    match ts.to_i64()? {
        Some(ts) => Instant::from_timestamp(ts),
        None => Instant::from_timestamp_f64(
            ts.to_f64()?
                .ok_or_type_err("Timestamp must be an integer or float")?,
        ),
    }
    .ok_or_value_err("Timestamp out of range")?
    .to_obj(cls.cast())
}

unsafe fn from_timestamp_millis(cls: *mut PyObject, ts: *mut PyObject) -> PyReturn {
    Instant::from_timestamp_millis(
        ts.to_i64()?
            .ok_or_type_err("Timestamp must be an integer")?,
    )
    .ok_or_value_err("Timestamp out of range")?
    .to_obj(cls.cast())
}

unsafe fn from_timestamp_nanos(cls: *mut PyObject, ts: *mut PyObject) -> PyReturn {
    Instant::from_timestamp_nanos(
        ts.to_i128()?
            .ok_or_type_err("Timestamp must be an integer")?,
    )
    .ok_or_value_err("Timestamp out of range")?
    .to_obj(cls.cast())
}

unsafe fn py_datetime(slf: *mut PyObject, _: *mut PyObject) -> PyReturn {
    Instant::extract(slf).to_py(State::for_obj(slf).py_api)
}

unsafe fn from_py_datetime(cls: *mut PyObject, dt: *mut PyObject) -> PyReturn {
    if PyDateTime_Check(dt) == 0 {
        Err(type_err!("Expected a datetime object"))?;
    }
    Instant::from_py(dt, State::for_type(cls.cast()))
        .ok_or_else(|| value_err!("datetime must have tzinfo set to UTC, got {}", dt.repr()))?
        .to_obj(cls.cast())
}

unsafe fn now(cls: *mut PyObject, _: *mut PyObject) -> PyReturn {
    let (secs, nanos) = State::for_type(cls.cast()).time_ns()?;
    Instant {
        secs: secs + UNIX_EPOCH_INSTANT,
        nanos,
    }
    .to_obj(cls.cast())
}

unsafe fn parse_rfc3339(cls: *mut PyObject, s_obj: *mut PyObject) -> PyReturn {
    let s = &mut s_obj.to_utf8()?.ok_or_type_err("Expected a string")?;
    let raise = || value_err!("Invalid RFC 3339 format: {}", s_obj.repr());
    if s.len() < 20 || !(s[10] == b' ' || s[10] == b'T' || s[10] == b't' || s[10] == b'_') {
        Err(raise())?;
    };
    let date = Date::parse_partial(s).ok_or_else(raise)?;
    // parse the separator
    if !(s[0] == b'T' || s[0] == b't' || s[0] == b' ' || s[0] == b'_') {
        Err(raise())?
    }
    *s = &s[1..];
    let time = Time::parse_partial(s).ok_or_else(raise)?;
    if let b"Z" | b"z" | b"+00:00" | b"-00:00" = &s[..] {
        Instant::from_datetime(date, time).to_obj(cls.cast())
    } else {
        Err(raise())?
    }
}

unsafe fn format_common_iso(slf: *mut PyObject, _: *mut PyObject) -> PyReturn {
    __str__(slf)
}

unsafe fn parse_common_iso(cls: *mut PyObject, s_obj: *mut PyObject) -> PyReturn {
    let s = &mut s_obj
        .to_utf8()?
        .ok_or_else(|| type_err!("Expected a string"))?;
    let raise = || value_err!("Invalid format: {}", s_obj.repr());
    if s.len() < 20 || s[10] != b'T' {
        Err(raise())?;
    };
    let date = Date::parse_partial(s).ok_or_else(raise)?;
    // parse the separator
    if s[0] != b'T' {
        Err(raise())?
    }
    *s = &s[1..];
    let time = Time::parse_partial(s).ok_or_else(raise)?;
    if let b"Z" | b"+00:00" | b"+00:00:00" = &s[..] {
        Instant::from_datetime(date, time).to_obj(cls.cast())
    } else {
        Err(raise())?
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
    let instant = Instant::extract(slf);
    let &State {
        str_hours,
        str_minutes,
        str_seconds,
        str_milliseconds,
        str_microseconds,
        str_nanoseconds,
        ..
    } = State::for_type(cls);
    let mut nanos: i128 = 0;

    if !args.is_empty() {
        Err(type_err!("{}() takes no positional arguments", fname))?;
    }
    handle_kwargs(fname, kwargs, |key, value, eq| {
        if eq(key, str_hours) {
            nanos += handle_exact_unit(value, MAX_HOURS, "hours", 3_600_000_000_000_i128)?;
        } else if eq(key, str_minutes) {
            nanos += handle_exact_unit(value, MAX_MINUTES, "minutes", 60_000_000_000_i128)?;
        } else if eq(key, str_seconds) {
            nanos += handle_exact_unit(value, MAX_SECS, "seconds", 1_000_000_000_i128)?;
        } else if eq(key, str_milliseconds) {
            nanos += handle_exact_unit(value, MAX_MILLISECONDS, "milliseconds", 1_000_000_i128)?;
        } else if eq(key, str_microseconds) {
            nanos += handle_exact_unit(value, MAX_MICROSECONDS, "microseconds", 1_000_i128)?;
        } else if eq(key, str_nanoseconds) {
            nanos = value
                .to_i128()?
                .ok_or_value_err("nanoseconds must be an integer")?
                .checked_add(nanos)
                .ok_or_value_err("total nanoseconds out of range")?;
        } else {
            return Ok(false);
        }
        Ok(true)
    })?;
    if negate {
        nanos = -nanos;
    }

    instant
        .shift(nanos)
        .ok_or_value_err("Resulting datetime is out of range")?
        .to_obj(cls)
}

unsafe fn difference(obj_a: *mut PyObject, obj_b: *mut PyObject) -> PyReturn {
    let type_b = Py_TYPE(obj_b);
    let type_a = Py_TYPE(obj_a);
    let state = State::for_type(type_a);
    let inst_a = Instant::extract(obj_a);
    let inst_b = if type_b == Py_TYPE(obj_a) {
        Instant::extract(obj_b)
    } else if type_b == state.zoned_datetime_type {
        ZonedDateTime::extract(obj_b).instant()
    } else if type_b == state.system_datetime_type || type_b == state.offset_datetime_type {
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

unsafe fn to_tz(slf: &mut PyObject, tz: &mut PyObject) -> PyReturn {
    let &State {
        zoned_datetime_type,
        zoneinfo_type,
        py_api,
        ..
    } = State::for_obj(slf);
    let zoneinfo = call1(zoneinfo_type, tz)?;
    defer_decref!(zoneinfo);
    Instant::extract(slf)
        .to_tz(py_api, zoneinfo)?
        .to_obj(zoned_datetime_type)
}

unsafe fn to_fixed_offset(slf_obj: *mut PyObject, args: &[*mut PyObject]) -> PyReturn {
    let cls = Py_TYPE(slf_obj);
    let slf = Instant::extract(slf_obj);
    let &State {
        offset_datetime_type,
        time_delta_type,
        ..
    } = State::for_type(cls);
    match *args {
        [] => slf
            .to_datetime()
            .with_offset_unchecked(0)
            .to_obj(offset_datetime_type),
        [offset] => {
            let offset_secs = offset_datetime::extract_offset(offset, time_delta_type)?;
            slf.to_offset(offset_secs)
                .ok_or_value_err("Resulting local date is out of range")?
                .to_obj(offset_datetime_type)
        }
        _ => Err(type_err!("to_fixed_offset() takes at most 1 argument")),
    }
}

unsafe fn to_system_tz(slf: *mut PyObject, _: *mut PyObject) -> PyReturn {
    let &State {
        py_api,
        system_datetime_type,
        ..
    } = State::for_obj(slf);
    Instant::extract(slf)
        .to_system_tz(py_api)?
        .to_obj(system_datetime_type)
}

unsafe fn format_rfc2822(slf: *mut PyObject, _: *mut PyObject) -> PyReturn {
    let state = State::for_obj(slf);
    // FUTURE: use vectorcall
    PyObject_Call(
        state.format_rfc2822,
        steal!((
            steal!(Instant::extract(slf).to_py(state.py_api)?),
            Py_True(),
        )
            .to_py()?),
        NULL(),
    )
    .as_result()
}

unsafe fn parse_rfc2822(cls: *mut PyObject, s_obj: *mut PyObject) -> PyReturn {
    let state = State::for_type(cls.cast());
    let dt: &mut PyObject;
    // On python 3.9, parsing RFC2822 is more flaky in returning TypeError
    #[cfg(not(Py_3_10))]
    {
        if !s_obj.is_str() {
            Err(type_err!("Expected a string"))?;
        }
        dt = call1(state.parse_rfc2822, s_obj).map_err(|e| {
            if PyErr_ExceptionMatches(PyExc_TypeError) != 0 {
                PyErr_Clear();
                value_err!("Invalid format: {}", s_obj.repr())
            } else {
                e
            }
        })?;
    }
    #[cfg(Py_3_10)]
    {
        dt = call1(state.parse_rfc2822, s_obj)?;
    }
    defer_decref!(dt);
    let tzinfo = get_dt_tzinfo(dt);
    if tzinfo == state.py_api.TimeZone_UTC
        || (tzinfo == Py_None() && s_obj.to_str()?.unwrap().contains("-0000"))
    {
        Instant::from_datetime(
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
        )
        .to_obj(cls.cast())
    } else {
        Err(value_err!(
            "Could not parse RFC 2822 with nonzero offset: {}",
            s_obj.repr()
        ))
    }
}

static mut METHODS: &[PyMethodDef] = &[
    method!(identity2 named "__copy__", ""),
    method!(identity2 named "__deepcopy__", "", METH_O),
    method!(exact_eq, "Equality check limited to the same type", METH_O),
    method!(__reduce__, ""),
    method!(timestamp, "Get the UNIX timestamp in seconds"),
    method!(timestamp_millis, "Get the UNIX timestamp in milliseconds"),
    method!(timestamp_nanos, "Get the UNIX timestamp in nanoseconds"),
    method!(
        from_timestamp,
        "Create an instance from a UNIX timestamp in seconds",
        METH_O | METH_CLASS
    ),
    PyMethodDef {
        ml_name: c"from_utc".as_ptr(),
        ml_meth: PyMethodDefPointer {
            PyCFunctionWithKeywords: {
                unsafe extern "C" fn _wrap(
                    slf: *mut PyObject,
                    args: *mut PyObject,
                    kwargs: *mut PyObject,
                ) -> *mut PyObject {
                    match from_utc(slf.cast(), args, kwargs) {
                        Ok(x) => x as *mut PyObject,
                        Err(PyErrOccurred()) => core::ptr::null_mut(),
                    }
                }
                _wrap
            },
        },
        ml_flags: METH_CLASS | METH_VARARGS | METH_KEYWORDS,
        ml_doc: c"Create an instance from a UTC date and time".as_ptr(),
    },
    method!(
        from_timestamp_millis,
        "Create an instance from a UNIX timestamp in milliseconds",
        METH_O | METH_CLASS
    ),
    method!(
        from_timestamp_nanos,
        "Create an instance from a UNIX timestamp in nanoseconds",
        METH_O | METH_CLASS
    ),
    method!(py_datetime, "Get the equivalent datetime.datetime object"),
    method!(
        from_py_datetime,
        "Create an instance from a datetime.datetime",
        METH_O | METH_CLASS
    ),
    method!(
        now,
        "Create an instance from the current time",
        METH_CLASS | METH_NOARGS
    ),
    method!(format_rfc3339, "Format in the RFC3339 format"),
    method!(
        parse_rfc3339,
        "Create an instance from an RFC3339 string",
        METH_CLASS | METH_O
    ),
    method!(format_rfc2822, "Format in the RFC2822 format"),
    method!(
        parse_rfc2822,
        "Create an instance from an RFC2822 string",
        METH_O | METH_CLASS
    ),
    method!(
        format_common_iso,
        "Format in the common ISO8601 representation"
    ),
    method!(
        parse_common_iso,
        "Create an instance from the common ISO8601 format",
        METH_O | METH_CLASS
    ),
    method_kwargs!(add, "Add various time units to the instance"),
    method_kwargs!(subtract, "Subtract various time units from the instance"),
    method!(to_tz, "Convert to an equivalent ZonedDateTime", METH_O),
    method!(
        to_system_tz,
        "Convert to an equivalent datetime in the system timezone"
    ),
    method_vararg!(to_fixed_offset, "Convert to an equivalent OffsetDateTime"),
    method!(
        difference,
        "Calculate the difference between two instances",
        METH_O
    ),
    PyMethodDef::zeroed(),
];

unsafe fn get_hour(slf: *mut PyObject) -> PyReturn {
    (Instant::extract(slf).secs % 86400 / 3600).to_py()
}

unsafe fn get_minute(slf: *mut PyObject) -> PyReturn {
    (Instant::extract(slf).secs % 3600 / 60).to_py()
}

unsafe fn get_secs(slf: *mut PyObject) -> PyReturn {
    (Instant::extract(slf).secs % 60).to_py()
}

unsafe fn get_nanos(slf: *mut PyObject) -> PyReturn {
    Instant::extract(slf).nanos.to_py()
}

static mut GETSETTERS: &[PyGetSetDef] = &[
    getter!(get_hour named "hour", "The hour component"),
    getter!(get_minute named "minute", "The minute component"),
    getter!(get_secs named "second", "The second component"),
    getter!(get_nanos named "nanosecond", "The nanosecond component"),
    PyGetSetDef {
        name: NULL(),
        get: None,
        set: None,
        doc: NULL(),
        closure: NULL(),
    },
];

type_spec!(Instant, SLOTS);
