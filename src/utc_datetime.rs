use core::ffi::{c_char, c_int, c_long, c_void};
use core::{mem, ptr, ptr::null_mut as NULL};
use pyo3_ffi::*;
use std::time::SystemTime;

use crate::common::*;
use crate::{
    date::{self, Date},
    date_delta::DateDelta,
    local_datetime,
    naive_datetime::{self, DateTime},
    offset_datetime::{self, OffsetDateTime},
    time::{self, Time},
    time_delta::{self, TimeDelta},
    zoned_datetime::{self, ZonedDateTime},
    State,
};

#[derive(Debug, Eq, PartialEq, Ord, PartialOrd, Copy, Clone)]
pub(crate) struct Instant {
    secs: i64, // MIN_INSTANT <= secs <= MAX_INSTANT
    nanos: u32, // 0 <= nanos < 1_000_000_000
               // FUTURE: make use of padding to cache the date value?
}

#[repr(C)]
pub(crate) struct PyUTCDateTime {
    _ob_base: PyObject,
    data: Instant,
}

pub(crate) const SINGLETONS: [(&str, Instant); 2] = [
    (
        "MIN\0",
        Instant {
            secs: MIN_INSTANT,
            nanos: 0,
        },
    ),
    (
        "MAX\0",
        Instant {
            secs: MAX_INSTANT,
            nanos: 999_999_999,
        },
    ),
];

pub(crate) const UNIX_EPOCH_INSTANT: i64 = 62_135_683_200; // 1970-01-01 in seconds after 0000-12-31
const MIN_INSTANT: i64 = 24 * 60 * 60;
const MAX_INSTANT: i64 = 315_537_983_999;

impl Instant {
    pub(crate) fn to_datetime(self) -> DateTime {
        DateTime {
            date: Date::from_ord((self.secs / 86400) as _),
            time: Time {
                hour: ((self.secs % 86400) / 3600) as _,
                minute: ((self.secs % 3600) / 60) as _,
                second: (self.secs % 60) as _,
                nanos: self.nanos,
            },
        }
    }

    pub(crate) const fn date(&self) -> date::Date {
        date::Date::from_ord((self.secs / 86400) as _)
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

    pub(crate) fn from_timestamp_millis(timestamp: i64) -> Option<Self> {
        let secs = timestamp / 1_000 + UNIX_EPOCH_INSTANT;
        ((MIN_INSTANT..=MAX_INSTANT).contains(&secs)).then_some(Instant {
            secs,
            nanos: (timestamp % 1_000) as u32 * 1_000_000,
        })
    }

    pub(crate) fn from_timestamp_nanos(timestamp: i128) -> Option<Self> {
        i64::try_from(timestamp / 1_000_000_000)
            .ok()
            .map(|secs| secs + UNIX_EPOCH_INSTANT)
            .filter(|s| (MIN_INSTANT..=MAX_INSTANT).contains(s))
            .map(|secs| Instant {
                secs,
                nanos: (timestamp % 1_000_000_000) as u32,
            })
    }

    // OPTIMIZE: shifting days is actually a lot faster in UTC (no offset changes)
    // Let's take advantage of that.
    pub(crate) fn date_shift(&self, years: i16, months: i32, days: i32) -> Option<Instant> {
        self.date().shift(years, months, days).map(|new_date| Self {
            secs: new_date.ord() as i64 * 86400 + self.secs % 86400,
            ..*self
        })
    }

    pub(crate) fn shift(&self, nanos: i128) -> Option<Instant> {
        self.total_nanos()
            .checked_add(nanos)
            .and_then(Instant::from_nanos)
    }

    pub(crate) unsafe fn extract(obj: *mut PyObject) -> Self {
        (*obj.cast::<PyUTCDateTime>()).data
    }

    pub(crate) const fn shift_secs_unchecked(&self, secs: i64) -> Self {
        Instant {
            secs: self.secs + secs,
            nanos: self.nanos,
        }
    }

    // TODO return result
    pub(crate) unsafe fn to_py(
        self,
        &PyDateTime_CAPI {
            DateTime_FromDateAndTime,
            TimeZone_UTC,
            DateTimeType,
            ..
        }: &PyDateTime_CAPI,
    ) -> *mut PyObject {
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
    }

    pub(crate) unsafe fn from_py(dt: *mut PyObject, state: &State) -> Option<Self> {
        let tzinfo = PyDateTime_DATE_GET_TZINFO(dt);
        (tzinfo == state.datetime_api.TimeZone_UTC).then_some(Instant::from_datetime(
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
        hashmask(self.secs as Py_hash_t ^ self.nanos as Py_hash_t)
    }

    #[cfg(target_pointer_width = "32")]
    pub(crate) const fn pyhash(&self) -> Py_hash_t {
        hashmask(
            (self.secs as Py_hash_t) ^ ((self.secs >> 32) as Py_hash_t) ^ (self.nanos as Py_hash_t),
        )
    }
}

unsafe fn __new__(
    subtype: *mut PyTypeObject,
    args: *mut PyObject,
    kwargs: *mut PyObject,
) -> PyReturn {
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
        c_str!("lll|llll:UTCDateTime"),
        vec![
            c_str!("year") as *mut c_char,
            c_str!("month") as *mut c_char,
            c_str!("day") as *mut c_char,
            c_str!("hour") as *mut c_char,
            c_str!("minute") as *mut c_char,
            c_str!("second") as *mut c_char,
            c_str!("nanosecond") as *mut c_char,
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
        return Err(PyErrOccurred());
    }

    new_unchecked(
        subtype,
        Instant::from_datetime(
            match Date::from_longs(year, month, day) {
                Some(date) => date,
                None => Err(value_error!("Invalid date"))?,
            },
            match Time::from_longs(hour, minute, second, nanos) {
                Some(time) => time,
                None => Err(value_error!("Invalid time"))?,
            },
        ),
    )
}

pub(crate) unsafe fn new_unchecked(type_: *mut PyTypeObject, i: Instant) -> PyReturn {
    let f: allocfunc = (*type_).tp_alloc.expect("tp_alloc is not set");
    let slf = f(type_, 0).cast::<PyUTCDateTime>();
    if slf.is_null() {
        return Err(PyErrOccurred());
    }
    ptr::addr_of_mut!((*slf).data).write(i);
    Ok(slf.cast::<PyObject>().as_mut().unwrap())
}

unsafe fn __repr__(slf: *mut PyObject) -> PyReturn {
    let DateTime { date, time } = Instant::extract(slf).to_datetime();
    format!("UTCDateTime({} {}Z)", date, time).to_py()
}

unsafe fn __str__(slf: *mut PyObject) -> PyReturn {
    let mut basic_str = Instant::extract(slf).to_datetime().default_fmt();
    basic_str.push('Z');
    basic_str.to_py()
}

unsafe fn default_format(slf: *mut PyObject, _: *mut PyObject) -> PyReturn {
    __str__(slf)
}

unsafe fn rfc3339(slf: *mut PyObject, _: *mut PyObject) -> PyReturn {
    let DateTime { date, time } = Instant::extract(slf).to_datetime();
    format!("{} {}Z", date, time).to_py()
}

unsafe fn __richcmp__(a_obj: *mut PyObject, b_obj: *mut PyObject, op: c_int) -> PyReturn {
    // TODO: test reflexivity
    let type_a = Py_TYPE(a_obj);
    let type_b = Py_TYPE(b_obj);
    let inst_a = Instant::extract(a_obj);
    let inst_b = if type_b == type_a {
        Instant::extract(b_obj)
    } else if type_b == State::for_type(type_a).zoned_datetime_type {
        ZonedDateTime::extract(b_obj).to_instant()
    } else if type_b == State::for_type(type_a).offset_datetime_type
        || type_b == State::for_type(type_a).local_datetime_type
    {
        OffsetDateTime::extract(b_obj).to_instant()
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
    Instant::extract(slf).pyhash()
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
            // at this point we know that `a` is a `UTCDateTime` and `b` isn't
            let inst_a = Instant::extract(obj_a);
            let inst_b = if type_b == State::for_mod(mod_a).zoned_datetime_type {
                ZonedDateTime::extract(obj_b).to_instant()
            } else if type_b == State::for_mod(mod_a).offset_datetime_type
                || type_b == State::for_mod(mod_a).local_datetime_type
            {
                OffsetDateTime::extract(obj_b).to_instant()
            } else {
                return _shift(obj_a, obj_b, true);
            };
            (inst_a, inst_b)
        } else {
            return Ok(newref(Py_NotImplemented()));
        }
    };
    time_delta::new_unchecked(
        State::for_type(type_a).time_delta_type,
        TimeDelta::from_nanos_unchecked(inst_a.total_nanos() - inst_b.total_nanos()),
    )
}

unsafe fn __add__(dt: *mut PyObject, delta_obj: *mut PyObject) -> PyReturn {
    if PyType_GetModule(Py_TYPE(dt)) == PyType_GetModule(Py_TYPE(delta_obj)) {
        _shift(dt, delta_obj, false)
    } else {
        Ok(newref(Py_NotImplemented()))
    }
}

#[inline]
unsafe fn _shift(slf: *mut PyObject, delta_obj: *mut PyObject, negate: bool) -> PyReturn {
    debug_assert_eq!(
        PyType_GetModule(Py_TYPE(slf)),
        PyType_GetModule(Py_TYPE(delta_obj))
    );
    let cls = Py_TYPE(slf);
    let &State {
        time_delta_type,
        date_delta_type,
        ..
    } = State::for_type(cls);
    let inst = Instant::extract(slf);
    if Py_TYPE(delta_obj) == time_delta_type {
        let mut delta = TimeDelta::extract(delta_obj);
        if negate {
            delta = -delta;
        };
        new_unchecked(
            cls,
            inst.shift(delta.total_nanos())
                .ok_or_else(|| value_error!("Resulting datetime is out of range"))?,
        )
    } else if Py_TYPE(delta_obj) == date_delta_type {
        let DateDelta {
            mut months,
            mut days,
        } = DateDelta::extract(delta_obj);
        if negate {
            months = -months;
            days = -days;
        };
        new_unchecked(
            cls,
            inst.date_shift(0, months, days)
                .ok_or_else(|| value_error!("Resulting datetime is out of range"))?,
        )
    } else {
        Ok(newref(Py_NotImplemented()))
    }
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
        pfunc: "A UTC datetime type\0".as_ptr() as *mut c_void,
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
        pfunc: dealloc as *mut c_void,
    },
    PyType_Slot {
        slot: 0,
        pfunc: NULL(),
    },
];

unsafe fn __reduce__(slf: *mut PyObject, _: *mut PyObject) -> PyReturn {
    let Instant { secs, nanos } = Instant::extract(slf);
    PyTuple_Pack(
        2,
        State::for_obj(slf).unpickle_utc_datetime,
        steal!(PyTuple_Pack(1, steal!(pack![secs, nanos].to_py()?)).as_result()?),
    )
    .as_result()
}

pub(crate) unsafe fn unpickle(module: *mut PyObject, args: &[*mut PyObject]) -> PyReturn {
    if args.len() != 1 {
        Err(type_error!("Invalid pickle data"))?;
    }
    let mut packed = args[0]
        .to_bytes()?
        .ok_or_else(|| value_error!("Invalid pickle data"))?;
    let new = new_unchecked(
        State::for_mod(module).utc_datetime_type,
        Instant {
            secs: unpack_one!(packed, i64),
            nanos: unpack_one!(packed, u32),
        },
    );
    if !packed.is_empty() {
        Err(value_error!("Invalid pickle data"))?;
    }
    new
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
    new_unchecked(
        State::for_type(cls.cast()).utc_datetime_type,
        Instant::from_timestamp(
            ts.to_i64()?
                .ok_or_else(|| value_error!("Timestamp out of range"))?,
        )
        .ok_or_else(|| value_error!("Timestamp out of range"))?,
    )
}

unsafe fn from_timestamp_millis(cls: *mut PyObject, ts: *mut PyObject) -> PyReturn {
    new_unchecked(
        State::for_type(cls.cast()).utc_datetime_type,
        Instant::from_timestamp_millis(
            ts.to_i64()?
                .ok_or_else(|| value_error!("Timestamp out of range"))?,
        )
        .ok_or_else(|| value_error!("Timestamp out of range"))?,
    )
}

unsafe fn from_timestamp_nanos(cls: *mut PyObject, ts: *mut PyObject) -> PyReturn {
    new_unchecked(
        State::for_type(cls.cast()).utc_datetime_type,
        Instant::from_timestamp_nanos(
            ts.to_i128()?
                .ok_or_else(|| value_error!("Timestamp out of range"))?,
        )
        .ok_or_else(|| value_error!("Timestamp out of range"))?,
    )
}

unsafe fn py_datetime(slf: *mut PyObject, _: *mut PyObject) -> PyReturn {
    Instant::extract(slf)
        .to_py(State::for_obj(slf).datetime_api)
        .as_result()
}

unsafe fn from_py_datetime(cls: *mut PyObject, dt: *mut PyObject) -> PyReturn {
    if PyDateTime_Check(dt) == 0 {
        Err(type_error!("Expected a datetime object"))?;
    }
    new_unchecked(
        cls.cast(),
        Instant::from_py(dt, State::for_type(cls.cast())).ok_or_else(|| {
            value_error!(
                "datetime must have tzinfo set to datetime.timezone.utc, got %R",
                dt
            )
        })?,
    )
}

unsafe fn now(cls: *mut PyObject, _: *mut PyObject) -> PyReturn {
    match SystemTime::now().duration_since(SystemTime::UNIX_EPOCH) {
        Ok(dur) => new_unchecked(
            cls.cast(),
            Instant {
                // FUTURE: decide on overflow check (only possible in ridiculous cases)
                secs: i64::try_from(dur.as_secs()).unwrap() + UNIX_EPOCH_INSTANT,
                nanos: dur.subsec_nanos(),
            },
        ),
        _ => Err(py_error!(PyExc_OSError, "SystemTime before UNIX EPOCH")),
    }
}

unsafe fn naive(slf: *mut PyObject, _: *mut PyObject) -> PyReturn {
    naive_datetime::new_unchecked(
        State::for_obj(slf).naive_datetime_type,
        Instant::extract(slf).to_datetime(),
    )
}

unsafe fn to_date(slf: *mut PyObject, _: *mut PyObject) -> PyReturn {
    date::new_unchecked(
        State::for_obj(slf).date_type,
        Instant::extract(slf).to_datetime().date,
    )
}

unsafe fn to_time(slf: *mut PyObject, _: *mut PyObject) -> PyReturn {
    time::new_unchecked(
        State::for_obj(slf).time_type,
        Instant::extract(slf).to_datetime().time,
    )
}

unsafe fn from_default_format(cls: *mut PyObject, s_obj: *mut PyObject) -> PyReturn {
    let s = s_obj
        .to_utf8()?
        .ok_or_else(|| type_error!("Expected a string"))?;
    if s.len() < 20 || s[10] != b'T' || s[s.len() - 1] != b'Z' {
        Err(value_error!("Invalid format: %R", s_obj))?;
    }
    match naive_datetime::parse_date_and_time(&s[..s.len() - 1]) {
        Some((date, time)) => new_unchecked(cls.cast(), Instant::from_datetime(date, time)),
        None => Err(value_error!("Invalid format: %R", s_obj)),
    }
}

unsafe fn with_date(slf: *mut PyObject, date_obj: *mut PyObject) -> PyReturn {
    let cls = Py_TYPE(slf);
    if Py_TYPE(date_obj) == State::for_type(cls).date_type {
        let mut instant = Instant::extract(slf);
        instant.secs = i64::from(Date::extract(date_obj).ord()) * 86400 + instant.secs % 86400;
        new_unchecked(cls, instant)
    } else {
        Err(type_error!("Expected a date object"))
    }
}

unsafe fn with_time(slf: *mut PyObject, time_obj: *mut PyObject) -> PyReturn {
    let cls = Py_TYPE(slf);
    if Py_TYPE(time_obj) == State::for_type(cls).time_type {
        let Time {
            hour,
            minute,
            second,
            nanos,
        } = Time::extract(time_obj);
        new_unchecked(
            cls,
            Instant {
                secs: Instant::extract(slf).secs / 86400 * 86400
                    + i64::from(hour) * 3600
                    + i64::from(minute) * 60
                    + i64::from(second),
                nanos,
            },
        )
    } else {
        Err(type_error!("Expected a time object"))
    }
}

unsafe fn strptime(cls: *mut PyObject, args: &[*mut PyObject]) -> PyReturn {
    let module = State::for_type(cls.cast());
    if args.len() != 2 {
        Err(type_error!("strptime() takes exactly 2 arguments"))?;
    }
    // OPTIMIZE: get this working with vectorcall
    let parsed = PyObject_Call(
        module.strptime,
        steal!(PyTuple_Pack(2, args[0], args[1]).as_result()?),
        NULL(),
    )
    .as_result()?;
    defer_decref!(parsed);
    let tzinfo = PyDateTime_DATE_GET_TZINFO(parsed);
    if !(tzinfo == Py_None() || tzinfo == module.datetime_api.TimeZone_UTC) {
        Err(value_error!(
            "datetime must have UTC tzinfo, but got %R",
            tzinfo
        ))?;
    }
    new_unchecked(
        cls.cast(),
        Instant {
            secs: Date::new_unchecked(
                PyDateTime_GET_YEAR(parsed) as u16,
                PyDateTime_GET_MONTH(parsed) as u8,
                PyDateTime_GET_DAY(parsed) as u8,
            )
            .ord() as i64
                * 86400
                + i64::from(PyDateTime_DATE_GET_HOUR(parsed)) * 3600
                + i64::from(PyDateTime_DATE_GET_MINUTE(parsed)) * 60
                + i64::from(PyDateTime_DATE_GET_SECOND(parsed)),
            nanos: PyDateTime_DATE_GET_MICROSECOND(parsed) as u32 * 1_000,
        },
    )
}

unsafe fn from_rfc3339(cls: *mut PyObject, s_obj: *mut PyObject) -> PyReturn {
    let s = s_obj
        .to_utf8()?
        .ok_or_else(|| type_error!("Expected a string"))?;
    if s.len() < 20 || !(s[10] == b' ' || s[10] == b'T' || s[10] == b't' || s[10] == b'_') {
        Err(value_error!("Invalid RFC3339 format: %R", s_obj))?;
    };
    let offset_index = match s[s.len() - 1] {
        b'Z' | b'z' => s.len() - 1,
        _ => match &s[s.len() - 6..] {
            b"+00:00" | b"-00:00" => s.len() - 6,
            _ => Err(value_error!("Invalid RFC3339 format: %R", s_obj))?,
        },
    };
    // TODO: do we check that there's no stuff afterwards?
    match naive_datetime::parse_date_and_time(&s[..offset_index]) {
        Some((date, time)) => new_unchecked(cls.cast(), Instant::from_datetime(date, time)),
        None => Err(value_error!("Invalid RFC3339 format: %R", s_obj)),
    }
}

unsafe fn common_iso8601(slf: *mut PyObject, _: *mut PyObject) -> PyReturn {
    let mut basic_str = Instant::extract(slf).to_datetime().default_fmt();
    basic_str.push('Z');
    basic_str.to_py()
}

unsafe fn from_common_iso8601(cls: *mut PyObject, s_obj: *mut PyObject) -> PyReturn {
    let s = s_obj
        .to_utf8()?
        .ok_or_else(|| type_error!("Expected a string"))?;
    if s.len() < 20 || s[10] != b'T' {
        Err(value_error!("Invalid common ISO8601 format: %R", s_obj))?;
    };
    let offset_index = match s[s.len() - 1] {
        b'Z' => s.len() - 1,
        _ if &s[s.len() - 6..] == b"+00:00" => s.len() - 6,
        _ => Err(value_error!("Invalid common ISO8601 format: %R", s_obj))?,
    };
    match naive_datetime::parse_date_and_time(&s[..offset_index]) {
        Some((date, time)) => new_unchecked(cls.cast(), Instant::from_datetime(date, time)),
        None => Err(value_error!("Invalid common ISO8601 format: %R", s_obj)),
    }
}

unsafe fn replace(
    slf: *mut PyObject,
    cls: *mut PyTypeObject,
    args: &[*mut PyObject],
    kwargs: &[(*mut PyObject, *mut PyObject)],
) -> PyReturn {
    if !args.is_empty() {
        Err(type_error!("replace() takes no positional arguments"))?;
    } else if kwargs.is_empty() {
        return Ok(newref(slf));
    };
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
    let DateTime { date, time } = Instant::extract(slf).to_datetime();
    let mut year = date.year.into();
    let mut month = date.month.into();
    let mut day = date.day.into();
    let mut hour = time.hour.into();
    let mut minute = time.minute.into();
    let mut second = time.second.into();
    let mut nanos = time.nanos.into();

    for &(name, value) in kwargs {
        if name == str_year {
            year = value
                .to_long()?
                .ok_or_else(|| type_error!("year must be an integer"))?;
        } else if name == str_month {
            month = value
                .to_long()?
                .ok_or_else(|| type_error!("month must be an integer"))?;
        } else if name == str_day {
            day = value
                .to_long()?
                .ok_or_else(|| type_error!("day must be an integer"))?;
        } else if name == str_hour {
            hour = value
                .to_long()?
                .ok_or_else(|| type_error!("hour must be an integer"))?;
        } else if name == str_minute {
            minute = value
                .to_long()?
                .ok_or_else(|| type_error!("minute must be an integer"))?;
        } else if name == str_second {
            second = value
                .to_long()?
                .ok_or_else(|| type_error!("second must be an integer"))?;
        } else if name == str_nanosecond {
            nanos = value
                .to_long()?
                .ok_or_else(|| type_error!("nanosecond must be an integer"))?;
        } else {
            Err(type_error!(
                "replace() got an unexpected keyword argument %R",
                name
            ))?;
        }
    }

    // FUTURE: optimize for case without year, month, day
    new_unchecked(
        cls,
        Instant::from_datetime(
            match Date::from_longs(year, month, day) {
                Some(date) => date,
                // TODO: test this case
                None => Err(value_error!("Invalid date"))?,
            },
            match Time::from_longs(hour, minute, second, nanos) {
                Some(time) => time,
                // TODO: test this case
                None => Err(value_error!("Invalid time"))?,
            },
        ),
    )
}

unsafe fn add(
    slf: *mut PyObject,
    cls: *mut PyTypeObject,
    args: &[*mut PyObject],
    kwargs: &[(*mut PyObject, *mut PyObject)],
) -> PyReturn {
    _shift_method(slf, cls, args, kwargs, false)
}

unsafe fn subtract(
    slf: *mut PyObject,
    cls: *mut PyTypeObject,
    args: &[*mut PyObject],
    kwargs: &[(*mut PyObject, *mut PyObject)],
) -> PyReturn {
    _shift_method(slf, cls, args, kwargs, true)
}

#[inline]
unsafe fn _shift_method(
    slf: *mut PyObject,
    type_: *mut PyTypeObject,
    args: &[*mut PyObject],
    kwargs: &[(*mut PyObject, *mut PyObject)],
    negate: bool,
) -> PyReturn {
    let instant = Instant::extract(slf);
    let state = State::for_type(type_);
    let mut delta_nanos: i128 = 0;
    let mut years: i16 = 0;
    let mut months: i32 = 0;
    let mut days: i32 = 0;

    if !args.is_empty() {
        Err(type_error!("add() takes no positional arguments"))?;
    }
    for &(name, value) in kwargs {
        // TODO: test very large nanos
        // TODO: test invalid kwarg with invalid type
        if name == state.str_years {
            years = value
                .to_long()?
                .ok_or_else(|| type_error!("years must be an integer"))?
                .try_into()
                .map_err(|_| type_error!("years out of range"))?;
        } else if name == state.str_months {
            months = value
                .to_long()?
                .ok_or_else(|| type_error!("months must be an integer"))?
                .try_into()
                .map_err(|_| type_error!("months out of range"))?;
        } else if name == state.str_weeks {
            let add_value: i32 = value
                .to_long()?
                .ok_or_else(|| type_error!("weeks must be an integer"))?
                .checked_mul(7)
                .ok_or_else(|| type_error!("days/weeks out of range"))?
                .try_into()
                .map_err(|_| type_error!("days/weeks out of range"))?;
            days += add_value;
        } else if name == state.str_days {
            let add_value: i32 = value
                .to_long()?
                .ok_or_else(|| type_error!("days must be an integer"))?
                .try_into()
                .map_err(|_| type_error!("days/weeks out of range"))?;
            days += add_value;
        } else if name == state.str_hours {
            delta_nanos += value
                .to_long()?
                .ok_or_else(|| type_error!("hours must be an integer"))?
                as i128
                * 3_600_000_000_000;
        } else if name == state.str_minutes {
            delta_nanos += value
                .to_long()?
                .ok_or_else(|| type_error!("minutes must be an integer"))?
                as i128
                * 60_000_000_000;
        } else if name == state.str_seconds {
            // TODO: is i64 the right size?
            delta_nanos += value
                .to_i64()?
                .ok_or_else(|| type_error!("seconds must be an integer"))?
                as i128
                * 1_000_000_000;
        } else if name == state.str_nanoseconds {
            delta_nanos += value
                .to_i128()?
                .ok_or_else(|| type_error!("nanoseconds must be an integer"))?;
        } else {
            Err(type_error!(
                "add()/subtract() got an unexpected keyword argument %R",
                name
            ))?;
        }
    }

    if negate {
        delta_nanos = -delta_nanos;
        years = -years;
        months = -months;
        days = -days;
    }

    // OPTIMIZE: shifting days is also fast--no calendar arithmetic
    // fast path: no date aritmethic
    let new = if years == 0 && months == 0 && days == 0 {
        instant.shift(delta_nanos)
    } else {
        instant
            .date_shift(years, months, days)
            .and_then(|inst| inst.shift(delta_nanos))
    };
    match new {
        Some(inst) => new_unchecked(type_, inst),
        None => Err(type_error!("Resulting datetime is out of range")),
    }
}

unsafe fn in_tz(slf: &mut PyObject, tz: &mut PyObject) -> PyReturn {
    let &State {
        zoned_datetime_type,
        zoneinfo_type,
        datetime_api: py_api,
        ..
    } = State::for_obj(slf);
    let DateTime { date, time } = Instant::extract(slf).to_datetime();
    let zoneinfo = PyObject_CallOneArg(zoneinfo_type.cast(), tz).as_result()?;
    defer_decref!(zoneinfo);
    zoned_datetime::new_unchecked(
        zoned_datetime_type,
        ZonedDateTime::from_utc(py_api, date, time, zoneinfo)?,
    )
}

unsafe fn in_fixed_offset(slf_obj: *mut PyObject, args: &[*mut PyObject]) -> PyReturn {
    let cls = Py_TYPE(slf_obj);
    let slf = Instant::extract(slf_obj);
    let &State {
        offset_datetime_type,
        time_delta_type,
        ..
    } = State::for_type(cls);
    if args.is_empty() {
        let DateTime { date, time } = slf.to_datetime();
        return offset_datetime::new_unchecked(
            offset_datetime_type,
            OffsetDateTime {
                date,
                time,
                offset_secs: 0,
            },
        );
    } else if args.len() > 1 {
        Err(type_error!("in_fixed_offset() takes at most 1 argument"))?;
    }
    let offset_secs = offset_datetime::extract_offset(args[0], time_delta_type)?;
    let DateTime { date, time, .. } = slf.shift_secs_unchecked(offset_secs.into()).to_datetime();
    offset_datetime::new_unchecked(
        offset_datetime_type,
        OffsetDateTime {
            date,
            time,
            offset_secs,
        },
    )
}

unsafe fn in_local_system(slf: *mut PyObject, _: *mut PyObject) -> PyReturn {
    let &State {
        datetime_api: py_api,
        local_datetime_type,
        ..
    } = State::for_obj(slf);
    local_datetime::new_unchecked(
        local_datetime_type,
        Instant::extract(slf).to_local_system(py_api)?,
    )
}

unsafe fn rfc2822(slf: *mut PyObject, _: *mut PyObject) -> PyReturn {
    let state = State::for_obj(slf);
    // FUTURE: use vectorcall
    PyObject_Call(
        state.format_rfc2822,
        steal!(PyTuple_Pack(
            2,
            steal!(Instant::extract(slf)
                .to_py(state.datetime_api)
                .as_result()?),
            Py_True(),
        )),
        NULL(),
    )
    .as_result()
}

unsafe fn from_rfc2822(cls: *mut PyObject, s_obj: *mut PyObject) -> PyReturn {
    let state = State::for_type(cls.cast());
    let py_dt = PyObject_CallOneArg(state.parse_rfc2822, s_obj).as_result()?;
    defer_decref!(py_dt);
    new_unchecked(
        cls.cast(),
        Instant::from_py(py_dt, state).ok_or_else(|| {
            value_error!(
                "Could not parse RFC 2822 string with nonzero offset: %R",
                s_obj
            )
        })?,
    )
}

static mut METHODS: &[PyMethodDef] = &[
    method!(identity2 named "__copy__", ""),
    method!(identity2 named "__deepcopy__", "", METH_O),
    method!(__reduce__, ""),
    method!(timestamp, "Get the UNIX timestamp in seconds"),
    method!(timestamp_millis, "Get the UNIX timestamp in milliseconds"),
    method!(timestamp_nanos, "Get the UNIX timestamp in nanoseconds"),
    method!(
        from_timestamp,
        "Create an instance from a UNIX timestamp in seconds",
        METH_O | METH_CLASS
    ),
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
    method!(identity2 named "in_utc", "Convert to a UTCDateTime"),
    method!(default_format, "Format in the default way"),
    method!(
        from_default_format,
        "Parse a UTCDateTime from its default format",
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
    method!(naive, "Convert to a naive datetime"),
    method!(to_date named "date", "Get the date part"),
    method!(to_time named "time", "Get the time part"),
    // TODO: add to naivedatetime
    method!(
        with_date,
        "Create a new instance with the date part replaced",
        METH_O
    ),
    method!(
        with_time,
        "Create a new instance with the time part replaced",
        METH_O
    ),
    method_vararg!(
        strptime,
        "Create an instance from a strptime result",
        METH_CLASS
    ),
    method!(rfc3339, "Format in the RFC3339 format"),
    method!(
        from_rfc3339,
        "Create an instance from an RFC3339 string",
        METH_CLASS | METH_O
    ),
    method!(rfc2822, "Format in the RFC2822 format"),
    method!(
        from_rfc2822,
        "Create an instance from an RFC2822 string",
        METH_O | METH_CLASS
    ),
    method!(common_iso8601, "Format in the common ISO8601 format"),
    method!(
        from_common_iso8601,
        "Create an instance from the common ISO8601 format",
        METH_O | METH_CLASS
    ),
    method_kwargs!(
        replace,
        "Return a new instance with the specified fields replaced"
    ),
    method_kwargs!(add, "Add various time units to the instance"),
    method_kwargs!(subtract, "Subtract various time units from the instance"),
    method!(in_tz, "Convert to an equivalent ZonedDateTime", METH_O),
    method!(
        in_local_system,
        "Convert to an equivalent datetime in the local system"
    ),
    method_vararg!(in_fixed_offset, "Convert to an equivalent OffsetDateTime"),
    PyMethodDef::zeroed(),
];

unsafe fn get_year(slf: *mut PyObject) -> PyReturn {
    Instant::extract(slf).date().year.to_py()
}

unsafe fn get_month(slf: *mut PyObject) -> PyReturn {
    Instant::extract(slf).date().month.to_py()
}

unsafe fn get_day(slf: *mut PyObject) -> PyReturn {
    Instant::extract(slf).date().day.to_py()
}

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
    getter!(get_year named "year", "The year component"),
    getter!(get_month named "month", "The month component"),
    getter!(get_day named "day", "The day component"),
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

pub(crate) static mut SPEC: PyType_Spec = PyType_Spec {
    name: c_str!("whenever.UTCDateTime"),
    basicsize: mem::size_of::<PyUTCDateTime>() as _,
    itemsize: 0,
    flags: Py_TPFLAGS_DEFAULT as _,
    slots: unsafe { SLOTS as *const [_] as *mut _ },
};
