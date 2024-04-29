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
    instant: Instant,
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
    pub(crate) fn to_datetime(&self) -> DateTime {
        let ord = (self.secs / 86400) as u32;
        let (year, month, day) = date::ord_to_ymd(ord);
        let hour = ((self.secs % 86400) / 3600) as u8;
        let minute = ((self.secs % 3600) / 60) as u8;
        let second = (self.secs % 60) as u8;
        DateTime {
            date: date::Date { year, month, day },
            time: time::Time {
                hour,
                minute,
                second,
                nanos: self.nanos,
            },
        }
    }

    pub(crate) const fn date(&self) -> date::Date {
        date::Date::from_ord((self.secs / 86400) as u32)
    }

    pub(crate) const fn from_datetime(date: date::Date, time: time::Time) -> Self {
        let ord = date::ymd_to_ord(date.year, date.month, date.day);
        let secs = ord as i64 * 86400
            + time.hour as i64 * 3600
            + time.minute as i64 * 60
            + time.second as i64;
        Instant {
            secs,
            nanos: time.nanos,
        }
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
            .filter(|&timestamp| between!(timestamp, =MIN_INSTANT, =MAX_INSTANT))
            .map(|secs| Instant { secs, nanos: 0 })
    }

    pub(crate) fn from_timestamp_millis(timestamp: i64) -> Option<Self> {
        let secs = timestamp / 1_000 + UNIX_EPOCH_INSTANT;
        between!(secs, =MIN_INSTANT, =MAX_INSTANT).then_some(Instant {
            secs,
            nanos: (timestamp % 1_000) as u32 * 1_000_000,
        })
    }

    pub(crate) fn from_timestamp_nanos(timestamp: i128) -> Option<Self> {
        i64::try_from(timestamp / 1_000_000_000)
            .ok()
            .map(|secs| secs + UNIX_EPOCH_INSTANT)
            .filter(|&secs| between!(secs, =MIN_INSTANT, =MAX_INSTANT))
            .map(|secs| Instant {
                secs,
                nanos: (timestamp % 1_000_000_000) as u32,
            })
    }

    // TODO: shifting days is actually a lot faster! Let's limit to months
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
        (*obj.cast::<PyUTCDateTime>()).instant
    }

    pub(crate) const fn shift_secs_unchecked(&self, secs: i64) -> Self {
        Instant {
            secs: self.secs + secs,
            nanos: self.nanos,
        }
    }

    pub(crate) unsafe fn to_py(
        &self,
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

unsafe extern "C" fn __new__(
    subtype: *mut PyTypeObject,
    args: *mut PyObject,
    kwargs: *mut PyObject,
) -> *mut PyObject {
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
        return NULL();
    }

    new_unchecked(
        subtype,
        Instant::from_datetime(
            match Date::from_longs(year, month, day) {
                Some(date) => date,
                None => raise!(PyExc_ValueError, "Invalid date"),
            },
            match Time::from_longs(hour, minute, second, nanos) {
                Some(time) => time,
                None => raise!(PyExc_ValueError, "Invalid time"),
            },
        ),
    )
}

pub(crate) unsafe fn new_unchecked(type_: *mut PyTypeObject, i: Instant) -> *mut PyObject {
    let f: allocfunc = (*type_).tp_alloc.expect("tp_alloc is not set");
    let slf = py_try!(f(type_, 0).cast::<PyUTCDateTime>());
    ptr::addr_of_mut!((*slf).instant).write(i);
    slf.cast()
}

unsafe extern "C" fn dealloc(slf: *mut PyObject) {
    let tp_free = PyType_GetSlot(Py_TYPE(slf), Py_tp_free);
    debug_assert_ne!(tp_free, NULL());
    let f: freefunc = std::mem::transmute(tp_free);
    f(slf.cast());
}

unsafe extern "C" fn __repr__(slf: *mut PyObject) -> *mut PyObject {
    let DateTime { date, time } = Instant::extract(slf).to_datetime();
    py_str(&format!("UTCDateTime({} {}Z)", date, time))
}

unsafe extern "C" fn __str__(slf: *mut PyObject) -> *mut PyObject {
    let mut basic_str = Instant::extract(slf).to_datetime().default_fmt();
    basic_str.push('Z');
    py_str(&basic_str)
}

unsafe extern "C" fn default_format(slf: *mut PyObject, _: *mut PyObject) -> *mut PyObject {
    __str__(slf)
}

unsafe extern "C" fn rfc3339(slf: *mut PyObject, _: *mut PyObject) -> *mut PyObject {
    let DateTime { date, time } = Instant::extract(slf).to_datetime();
    py_str(&format!("{} {}Z", date, time))
}

unsafe extern "C" fn __richcmp__(
    a_obj: *mut PyObject,
    b_obj: *mut PyObject,
    op: c_int,
) -> *mut PyObject {
    // TODO: test reflexivity
    let type_a = Py_TYPE(a_obj);
    let type_b = Py_TYPE(b_obj);
    let inst_a = Instant::extract(a_obj);
    let inst_b = if type_b == type_a {
        Instant::extract(b_obj)
    } else if type_b == State::for_type(type_a).zoned_datetime_type {
        ZonedDateTime::extract(b_obj).to_instant()
    } else if type_b == State::for_type(type_a).offset_datetime_type {
        OffsetDateTime::extract(b_obj).to_instant()
    } else if type_b == State::for_type(type_a).local_datetime_type {
        OffsetDateTime::extract(b_obj).to_instant()
    } else {
        return newref(Py_NotImplemented());
    };
    py_bool(match op {
        pyo3_ffi::Py_EQ => inst_a == inst_b,
        pyo3_ffi::Py_NE => inst_a != inst_b,
        pyo3_ffi::Py_LT => inst_a < inst_b,
        pyo3_ffi::Py_LE => inst_a <= inst_b,
        pyo3_ffi::Py_GT => inst_a > inst_b,
        pyo3_ffi::Py_GE => inst_a >= inst_b,
        _ => unreachable!(),
    })
}

unsafe extern "C" fn __hash__(slf: *mut PyObject) -> Py_hash_t {
    Instant::extract(slf).pyhash()
}

unsafe extern "C" fn __sub__(obj_a: *mut PyObject, obj_b: *mut PyObject) -> *mut PyObject {
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
            } else if type_b == State::for_mod(mod_a).offset_datetime_type {
                OffsetDateTime::extract(obj_b).to_instant()
            } else if type_b == State::for_mod(mod_a).local_datetime_type {
                OffsetDateTime::extract(obj_b).to_instant()
            } else {
                return _shift(obj_a, obj_b, true);
            };
            (inst_a, inst_b)
        } else {
            return newref(Py_NotImplemented());
        }
    };
    time_delta::new_unchecked(
        State::for_type(type_a).time_delta_type,
        TimeDelta::from_nanos_unchecked(inst_a.total_nanos() - inst_b.total_nanos()),
    )
}

unsafe extern "C" fn __add__(dt: *mut PyObject, delta_obj: *mut PyObject) -> *mut PyObject {
    if PyType_GetModule(Py_TYPE(dt)) == PyType_GetModule(Py_TYPE(delta_obj)) {
        _shift(dt, delta_obj, false)
    } else {
        newref(Py_NotImplemented())
    }
}

#[inline]
unsafe extern "C" fn _shift(
    slf: *mut PyObject,
    delta_obj: *mut PyObject,
    negate: bool,
) -> *mut PyObject {
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
            unwrap_or_raise!(
                inst.shift(delta.total_nanos()),
                PyExc_ValueError,
                "Resulting datetime is out of range"
            ),
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
            unwrap_or_raise!(
                inst.date_shift(0, months, days),
                PyExc_ValueError,
                "Resulting date is out of range"
            ),
        )
    } else {
        newref(Py_NotImplemented())
    }
}

static mut SLOTS: &[PyType_Slot] = &[
    PyType_Slot {
        slot: Py_tp_new,
        pfunc: __new__ as *mut c_void,
    },
    PyType_Slot {
        slot: Py_tp_doc,
        pfunc: "A UTC datetime type\0".as_ptr() as *mut c_void,
    },
    PyType_Slot {
        slot: Py_tp_repr,
        pfunc: __repr__ as *mut c_void,
    },
    PyType_Slot {
        slot: Py_tp_str,
        pfunc: __str__ as *mut c_void,
    },
    PyType_Slot {
        slot: Py_tp_richcompare,
        pfunc: __richcmp__ as *mut c_void,
    },
    PyType_Slot {
        slot: Py_tp_hash,
        pfunc: __hash__ as *mut c_void,
    },
    PyType_Slot {
        slot: Py_nb_subtract,
        pfunc: __sub__ as *mut c_void,
    },
    PyType_Slot {
        slot: Py_nb_add,
        pfunc: __add__ as *mut c_void,
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

unsafe extern "C" fn __reduce__(slf: *mut PyObject, _: *mut PyObject) -> *mut PyObject {
    let Instant { secs, nanos } = Instant::extract(slf);
    PyTuple_Pack(
        2,
        State::for_obj(slf).unpickle_utc_datetime,
        py_try!(PyTuple_Pack(1, py_bytes(&pack![secs, nanos]))),
    )
}

pub(crate) unsafe extern "C" fn unpickle(
    module: *mut PyObject,
    args: *mut *mut PyObject,
    nargs: Py_ssize_t,
) -> *mut PyObject {
    if PyVectorcall_NARGS(nargs as usize) != 1 {
        raise!(PyExc_TypeError, "Invalid pickle data");
    }
    let mut packed = pybytes_extract!(*args);
    let new = new_unchecked(
        State::for_mod(module).utc_datetime_type,
        Instant {
            secs: unpack_one!(packed, i64),
            nanos: unpack_one!(packed, u32),
        },
    );
    // TODO: refcounts
    if !packed.is_empty() {
        raise!(PyExc_ValueError, "Invalid pickle data");
    }
    new
}

unsafe extern "C" fn timestamp(slf: *mut PyObject, _: *mut PyObject) -> *mut PyObject {
    PyLong_FromLongLong(Instant::extract(slf).timestamp())
}

unsafe extern "C" fn timestamp_millis(slf: *mut PyObject, _: *mut PyObject) -> *mut PyObject {
    PyLong_FromLongLong(Instant::extract(slf).timestamp_millis())
}

unsafe extern "C" fn timestamp_nanos(slf: *mut PyObject, _: *mut PyObject) -> *mut PyObject {
    py_int128(Instant::extract(slf).timestamp_nanos())
}

unsafe extern "C" fn from_timestamp(cls: *mut PyObject, ts: *mut PyObject) -> *mut PyObject {
    new_unchecked(
        State::for_type(cls.cast()).utc_datetime_type,
        unwrap_or_raise!(
            Instant::from_timestamp(pyint_as_i64!(ts)),
            PyExc_ValueError,
            "Timestamp out of range"
        ),
    )
}

unsafe extern "C" fn from_timestamp_millis(cls: *mut PyObject, ts: *mut PyObject) -> *mut PyObject {
    new_unchecked(
        State::for_type(cls.cast()).utc_datetime_type,
        unwrap_or_raise!(
            Instant::from_timestamp_millis(pyint_as_i64!(ts)),
            PyExc_ValueError,
            "Timestamp out of range"
        ),
    )
}

unsafe extern "C" fn from_timestamp_nanos(cls: *mut PyObject, ts: *mut PyObject) -> *mut PyObject {
    new_unchecked(
        State::for_type(cls.cast()).utc_datetime_type,
        unwrap_or_raise!(
            Instant::from_timestamp_nanos(i128_extract!(ts, "Expected an integer")),
            PyExc_ValueError,
            "Timestamp out of range"
        ),
    )
}

unsafe extern "C" fn py_datetime(slf: *mut PyObject, _: *mut PyObject) -> *mut PyObject {
    Instant::extract(slf).to_py(&State::for_type(Py_TYPE(slf)).datetime_api)
}

unsafe extern "C" fn from_py_datetime(type_: *mut PyObject, dt: *mut PyObject) -> *mut PyObject {
    if PyDateTime_Check(dt) == 0 {
        raise!(PyExc_TypeError, "argument must be datetime.datetime");
    }
    new_unchecked(
        type_.cast(),
        unwrap_or_raise!(
            Instant::from_py(dt, State::for_type(type_.cast())),
            PyExc_ValueError,
            "datetime must have tzinfo set to datetime.timezone.utc, got %R",
            dt
        ),
    )
}

unsafe extern "C" fn now(cls: *mut PyObject, _: *mut PyObject) -> *mut PyObject {
    match SystemTime::now().duration_since(SystemTime::UNIX_EPOCH) {
        Ok(dur) => new_unchecked(
            cls.cast(),
            Instant {
                // FUTURE: decide on overflow check (only possible in ridiculous cases)
                secs: dur.as_secs() as i64 + UNIX_EPOCH_INSTANT,
                nanos: dur.subsec_nanos(),
            },
        ),
        _ => raise!(PyExc_OSError, "SystemTime before UNIX EPOCH"),
    }
}

unsafe extern "C" fn naive(slf: *mut PyObject, _: *mut PyObject) -> *mut PyObject {
    naive_datetime::new_unchecked(
        State::for_obj(slf).naive_datetime_type,
        Instant::extract(slf).to_datetime(),
    )
}

unsafe extern "C" fn to_date(slf: *mut PyObject, _: *mut PyObject) -> *mut PyObject {
    date::new_unchecked(
        State::for_obj(slf).date_type,
        Instant::extract(slf).to_datetime().date,
    )
}

unsafe extern "C" fn to_time(slf: *mut PyObject, _: *mut PyObject) -> *mut PyObject {
    time::new_unchecked(
        State::for_obj(slf).time_type,
        Instant::extract(slf).to_datetime().time,
    )
}

unsafe extern "C" fn from_default_format(
    cls: *mut PyObject,
    s_obj: *mut PyObject,
) -> *mut PyObject {
    let s = pystr_to_utf8!(s_obj, "Expected a string");
    if s.len() < 20 || s[10] != b'T' || s[s.len() - 1] != b'Z' {
        raise!(PyExc_ValueError, "Invalid format: %R", s_obj);
    }
    match naive_datetime::parse_date_and_time(&s[..s.len() - 1]) {
        Some((date, time)) => new_unchecked(cls.cast(), Instant::from_datetime(date, time)),
        None => raise!(PyExc_ValueError, "Invalid format: %R", s_obj),
    }
}

unsafe extern "C" fn with_date(slf: *mut PyObject, date_obj: *mut PyObject) -> *mut PyObject {
    if Py_TYPE(date_obj) == State::for_type(Py_TYPE(slf)).date_type {
        let mut instant = Instant::extract(slf);
        instant.secs = Date::extract(date_obj).ord() as i64 * 86400 + instant.secs % 86400;
        new_unchecked(Py_TYPE(slf), instant)
    } else {
        raise!(PyExc_TypeError, "Expected a date object");
    }
}

unsafe extern "C" fn with_time(slf: *mut PyObject, time_obj: *mut PyObject) -> *mut PyObject {
    if Py_TYPE(time_obj) == State::for_type(Py_TYPE(slf)).time_type {
        let Time {
            hour,
            minute,
            second,
            nanos,
        } = Time::extract(time_obj);
        new_unchecked(
            Py_TYPE(slf),
            Instant {
                secs: Instant::extract(slf).secs / 86400 * 86400
                    + hour as i64 * 3600
                    + minute as i64 * 60
                    + second as i64,
                nanos,
            },
        )
    } else {
        raise!(PyExc_TypeError, "Expected a time object");
    }
}

unsafe extern "C" fn strptime(cls: *mut PyObject, args: *mut PyObject) -> *mut PyObject {
    // FUTURE: get this working with vectorcall
    let module = State::for_type(cls.cast());
    let parsed = py_try!(PyObject_Call(module.strptime, args, NULL()));
    let tzinfo = PyDateTime_DATE_GET_TZINFO(parsed);
    if !(tzinfo == Py_None() || tzinfo == module.datetime_api.TimeZone_UTC) {
        raise!(
            PyExc_ValueError,
            "datetime must have UTC tzinfo, but got %R",
            tzinfo
        );
    }
    new_unchecked(
        cls.cast(),
        Instant {
            secs: date::ymd_to_ord(
                PyDateTime_GET_YEAR(parsed) as u16,
                PyDateTime_GET_MONTH(parsed) as u8,
                PyDateTime_GET_DAY(parsed) as u8,
            ) as i64
                * 86400
                + PyDateTime_DATE_GET_HOUR(parsed) as i64 * 3600
                + PyDateTime_DATE_GET_MINUTE(parsed) as i64 * 60
                + PyDateTime_DATE_GET_SECOND(parsed) as i64,
            nanos: PyDateTime_DATE_GET_MICROSECOND(parsed) as u32 * 1_000,
        },
    )
}

unsafe extern "C" fn from_rfc3339(cls: *mut PyObject, s_obj: *mut PyObject) -> *mut PyObject {
    let s = pystr_to_utf8!(s_obj, "Expected a string");
    if s.len() < 20 || !(s[10] == b' ' || s[10] == b'T' || s[10] == b't' || s[10] == b'_') {
        raise!(PyExc_ValueError, "Invalid RFC3339 format: %R", s_obj);
    };
    let offset_index = match s[s.len() - 1] {
        b'Z' | b'z' => s.len() - 1,
        _ => match &s[s.len() - 6..] {
            b"+00:00" | b"-00:00" => s.len() - 6,
            _ => raise!(PyExc_ValueError, "Invalid RFC3339 format: %R", s_obj),
        },
    };
    match naive_datetime::parse_date_and_time(&s[..offset_index]) {
        Some((date, time)) => new_unchecked(cls.cast(), Instant::from_datetime(date, time)),
        None => raise!(PyExc_ValueError, "Invalid RFC3339 format: %R", s_obj),
    }
}

unsafe extern "C" fn common_iso8601(slf: *mut PyObject, _: *mut PyObject) -> *mut PyObject {
    let mut basic_str = Instant::extract(slf).to_datetime().default_fmt();
    basic_str.push('Z');
    basic_str.replace_range(10..11, "T");
    py_str(&basic_str)
}

unsafe extern "C" fn from_common_iso8601(
    cls: *mut PyObject,
    s_obj: *mut PyObject,
) -> *mut PyObject {
    let s = pystr_to_utf8!(s_obj, "Expected a string");
    if s.len() < 20 || s[10] != b'T' {
        raise!(PyExc_ValueError, "Invalid common ISO8601 format: %R", s_obj);
    };
    let offset_index = match s[s.len() - 1] {
        b'Z' => s.len() - 1,
        _ if &s[s.len() - 6..] == b"+00:00" => s.len() - 6,
        _ => raise!(PyExc_ValueError, "Invalid common ISO8601 format: %R", s_obj),
    };
    match naive_datetime::parse_date_and_time(&s[..offset_index]) {
        Some((date, time)) => new_unchecked(cls.cast(), Instant::from_datetime(date, time)),
        None => raise!(PyExc_ValueError, "Invalid common ISO8601 format: %R", s_obj),
    }
}

unsafe extern "C" fn replace(
    slf: *mut PyObject,
    type_: *mut PyTypeObject,
    args: *const *mut PyObject,
    nargs: Py_ssize_t,
    kwnames: *mut PyObject,
) -> *mut PyObject {
    if PyVectorcall_NARGS(nargs as usize) != 0 {
        raise!(PyExc_TypeError, "replace() takes no positional arguments");
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
    } = State::for_type(type_);
    let DateTime { date, time } = Instant::extract(slf).to_datetime();
    let mut year = date.year.into();
    let mut month = date.month.into();
    let mut day = date.day.into();
    let mut hour = time.hour.into();
    let mut minute = time.minute.into();
    let mut second = time.second.into();
    let mut nanos = time.nanos.into();

    if kwnames.is_null() {
        newref(slf)
    } else {
        for i in 0..=Py_SIZE(kwnames).saturating_sub(1) {
            let name = PyTuple_GET_ITEM(kwnames, i);
            let value = *args.offset(i);
            if name == str_year {
                year = pyint_as_long!(value);
            } else if name == str_month {
                month = pyint_as_long!(value);
            } else if name == str_day {
                day = pyint_as_long!(value);
            } else if name == str_hour {
                hour = pyint_as_long!(value);
            } else if name == str_minute {
                minute = pyint_as_long!(value);
            } else if name == str_second {
                second = pyint_as_long!(value);
            } else if name == str_nanosecond {
                nanos = pyint_as_long!(value);
            } else {
                raise!(
                    PyExc_TypeError,
                    "replace() got an unexpected keyword argument %R",
                    name
                );
            }
        }
        // FUTURE: optimize for case without year, month, day
        new_unchecked(
            type_,
            Instant::from_datetime(
                match Date::from_longs(year, month, day) {
                    Some(date) => date,
                    None => raise!(PyExc_ValueError, "Invalid date"),
                },
                match Time::from_longs(hour, minute, second, nanos) {
                    Some(time) => time,
                    None => raise!(PyExc_ValueError, "Invalid time"),
                },
            ),
        )
    }
}

unsafe extern "C" fn add(
    slf: *mut PyObject,
    type_: *mut PyTypeObject,
    args: *const *mut PyObject,
    nargs: Py_ssize_t,
    kwnames: *mut PyObject,
) -> *mut PyObject {
    _shift_method(slf, type_, args, nargs, kwnames, false)
}

unsafe extern "C" fn subtract(
    slf: *mut PyObject,
    type_: *mut PyTypeObject,
    args: *const *mut PyObject,
    nargs: Py_ssize_t,
    kwnames: *mut PyObject,
) -> *mut PyObject {
    _shift_method(slf, type_, args, nargs, kwnames, true)
}

unsafe extern "C" fn _shift_method(
    slf: *mut PyObject,
    type_: *mut PyTypeObject,
    args: *const *mut PyObject,
    nargs: Py_ssize_t,
    kwnames: *mut PyObject,
    negate: bool,
) -> *mut PyObject {
    let instant = Instant::extract(slf);
    let state = State::for_type(type_);
    let mut delta_nanos: i128 = 0;
    let mut years: c_long = 0;
    let mut months: c_long = 0;
    let mut days: c_long = 0;

    if PyVectorcall_NARGS(nargs as usize) != 0 {
        raise!(PyExc_TypeError, "add() takes no positional arguments");
    }
    if !kwnames.is_null() {
        for i in 0..=Py_SIZE(kwnames).saturating_sub(1) {
            let name = PyTuple_GET_ITEM(kwnames, i as Py_ssize_t);
            // TODO: allow very large nanos
            let value = pyint_as_long!(*args.offset(i));
            if name == state.str_years {
                years = value;
            } else if name == state.str_months {
                months = value;
            } else if name == state.str_weeks {
                days += value * 7;
            } else if name == state.str_days {
                days += value;
            } else if name == state.str_hours {
                delta_nanos += value as i128 * 3_600_000_000_000;
            } else if name == state.str_minutes {
                delta_nanos += value as i128 * 60_000_000_000;
            } else if name == state.str_seconds {
                delta_nanos += value as i128 * 1_000_000_000;
            } else if name == state.str_nanoseconds {
                delta_nanos += value as i128;
            } else {
                raise!(
                    PyExc_TypeError,
                    "add()/subtract() got an unexpected keyword argument %R",
                    name
                );
            }
        }
    }

    if negate {
        delta_nanos = -delta_nanos;
        years = -years;
        months = -months;
        days = -days;
    }

    // TODO: shifting days is also fast
    // fast path: no date aritmethic
    let new = if years == 0 && months == 0 && days == 0 {
        instant.shift(delta_nanos)
    } else {
        instant
            .date_shift(
                unwrap_or_raise!(
                    years.try_into().ok(),
                    PyExc_ValueError,
                    "years out of range"
                ),
                unwrap_or_raise!(
                    months.try_into().ok(),
                    PyExc_ValueError,
                    "months out of range"
                ),
                unwrap_or_raise!(days.try_into().ok(), PyExc_ValueError, "days out of range"),
            )
            .and_then(|inst| inst.shift(delta_nanos))
    };
    match new {
        Some(inst) => new_unchecked(type_, inst),
        None => {
            raise!(PyExc_ValueError, "Result out of range");
        }
    }
}

unsafe extern "C" fn in_tz(slf: *mut PyObject, tz: *mut PyObject) -> *mut PyObject {
    let &State {
        zoned_datetime_type,
        zoneinfo_type,
        datetime_api:
            &PyDateTime_CAPI {
                DateTime_FromDateAndTime,
                DateTimeType,
                ..
            },
        ..
    } = State::for_type(Py_TYPE(slf));
    let DateTime {
        date: Date { year, month, day },
        time:
            Time {
                hour,
                minute,
                second,
                nanos,
            },
    } = Instant::extract(slf).to_datetime();
    let zoneinfo = newref(py_try!(PyObject_CallOneArg(zoneinfo_type.cast(), tz)));
    let new_py_dt = py_try!(PyObject_CallMethodOneArg(
        zoneinfo,
        py_str("fromutc"),
        DateTime_FromDateAndTime(
            year.into(),
            month.into(),
            day.into(),
            hour.into(),
            minute.into(),
            second.into(),
            0, // assumption: no sub-second offsets in tzdb
            zoneinfo,
            DateTimeType,
        ),
    ));

    let offset_delta = py_try!(PyObject_CallMethodNoArgs(new_py_dt, py_str("utcoffset")));
    let offset_secs = PyDateTime_DELTA_GET_DAYS(offset_delta) * 86400
        + PyDateTime_DELTA_GET_SECONDS(offset_delta);

    let result = zoned_datetime::new_unchecked(
        zoned_datetime_type,
        ZonedDateTime {
            date: Date {
                year: PyDateTime_GET_YEAR(new_py_dt) as u16,
                month: PyDateTime_GET_MONTH(new_py_dt) as u8,
                day: PyDateTime_GET_DAY(new_py_dt) as u8,
            },
            time: Time {
                hour: PyDateTime_DATE_GET_HOUR(new_py_dt) as u8,
                minute: PyDateTime_DATE_GET_MINUTE(new_py_dt) as u8,
                second: PyDateTime_DATE_GET_SECOND(new_py_dt) as u8,
                nanos,
            },
            offset_secs,
            zoneinfo,
        },
    );
    Py_DECREF(new_py_dt);
    Py_DECREF(offset_delta);
    result
}

unsafe extern "C" fn in_fixed_offset(
    slf_obj: *mut PyObject,
    args: *mut *mut PyObject,
    nargs: Py_ssize_t,
) -> *mut PyObject {
    let cls = Py_TYPE(slf_obj);
    let slf = Instant::extract(slf_obj);
    let &State {
        offset_datetime_type,
        time_delta_type,
        ..
    } = State::for_type(cls);
    if nargs == 0 {
        let DateTime { date, time } = slf.to_datetime();
        return offset_datetime::new_unchecked(
            offset_datetime_type,
            OffsetDateTime {
                date,
                time,
                offset_secs: 0,
            },
        );
    } else if nargs > 1 {
        raise!(
            PyExc_TypeError,
            "in_fixed_offset() takes at most 1 argument"
        );
    }
    let offset_secs = to_py!(offset_datetime::extract_offset(*args, time_delta_type));
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

unsafe extern "C" fn in_local_system(slf: *mut PyObject, _: *mut PyObject) -> *mut PyObject {
    let &State {
        datetime_api: py_api,
        local_datetime_type,
        ..
    } = State::for_obj(slf);
    local_datetime::new_unchecked(
        local_datetime_type,
        Instant::extract(slf).to_local_system(py_api),
    )
}

unsafe extern "C" fn rfc2822(slf: *mut PyObject, _: *mut PyObject) -> *mut PyObject {
    let state = State::for_obj(slf);
    // FUTURE: use vectorcall
    PyObject_Call(
        state.format_rfc2822,
        PyTuple_Pack(
            2,
            Instant::extract(slf).to_py(state.datetime_api),
            Py_True(),
        ),
        NULL(),
    )
}

unsafe extern "C" fn from_rfc2822(cls: *mut PyObject, s_obj: *mut PyObject) -> *mut PyObject {
    let state = State::for_type(cls.cast());
    let py_dt = py_try!(PyObject_CallOneArg(state.parse_rfc2822, s_obj));
    // TODO: refcounts, refcounts
    new_unchecked(
        cls.cast(),
        unwrap_or_raise!(
            Instant::from_py(py_dt, state),
            PyExc_ValueError,
            "Could not parse RFC 2822 string with nonzero offset: %R",
            s_obj
        ),
    )
}

static mut METHODS: &[PyMethodDef] = &[
    method!(identity named "__copy__", ""),
    method!(identity named "__deepcopy__", "", METH_O),
    method!(__reduce__, ""),
    method!(timestamp, "Get the UNIX timestamp in seconds"),
    method!(timestamp_millis, "Get the UNIX timestamp in milliseconds"),
    method!(timestamp_nanos, "Get the UNIX timestamp in nanoseconds"),
    classmethod!(
        from_timestamp,
        "Create an instance from a UNIX timestamp in seconds",
        METH_O
    ),
    classmethod!(
        from_timestamp_millis,
        "Create an instance from a UNIX timestamp in milliseconds",
        METH_O
    ),
    classmethod!(
        from_timestamp_nanos,
        "Create an instance from a UNIX timestamp in nanoseconds",
        METH_O
    ),
    method!(identity named "in_utc", "Convert to a UTCDateTime"),
    method!(default_format, ""),
    classmethod!(from_default_format, "", METH_O),
    method!(py_datetime, "Get the equivalent datetime.datetime object"),
    classmethod!(
        from_py_datetime,
        "Create an instance from a datetime.datetime",
        METH_O
    ),
    classmethod!(now, "Create an instance from the current time"),
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
    PyMethodDef {
        ml_name: c_str!("strptime"),
        ml_meth: PyMethodDefPointer {
            PyCFunction: strptime,
        },
        ml_flags: METH_CLASS | METH_VARARGS,
        ml_doc: c_str!("Create an instance from a strptime result"),
    },
    method!(rfc3339, "Format in the RFC3339 format"),
    classmethod!(
        from_rfc3339,
        "Create an instance from an RFC3339 string",
        METH_O
    ),
    method!(rfc2822, "Format in the RFC2822 format"),
    classmethod!(
        from_rfc2822,
        "Create an instance from an RFC2822 string",
        METH_O
    ),
    method!(common_iso8601, "Format in the common ISO8601 format"),
    classmethod!(
        from_common_iso8601,
        "Create an instance from the common ISO8601 format",
        METH_O
    ),
    PyMethodDef {
        ml_name: c_str!("replace"),
        ml_meth: PyMethodDefPointer { PyCMethod: replace },
        ml_flags: METH_METHOD | METH_FASTCALL | METH_KEYWORDS,
        ml_doc: c_str!("Return a new instance with the specified fields replaced"),
    },
    PyMethodDef {
        ml_name: c_str!("add"),
        ml_meth: PyMethodDefPointer { PyCMethod: add },
        ml_flags: METH_METHOD | METH_FASTCALL | METH_KEYWORDS,
        ml_doc: c_str!("Add various time units to the instance"),
    },
    PyMethodDef {
        ml_name: c_str!("subtract"),
        ml_meth: PyMethodDefPointer {
            PyCMethod: subtract,
        },
        ml_flags: METH_METHOD | METH_FASTCALL | METH_KEYWORDS,
        ml_doc: c_str!("Subtract various time units from the instance"),
    },
    method!(in_tz, "Convert to an equivalent ZonedDateTime", METH_O),
    method!(
        in_local_system,
        "Convert to an equivalent datetime in the local system"
    ),
    PyMethodDef {
        ml_name: c_str!("in_fixed_offset"),
        ml_meth: PyMethodDefPointer {
            _PyCFunctionFast: in_fixed_offset,
        },
        ml_flags: METH_FASTCALL,
        ml_doc: c_str!("Convert to an equivalent offset datetime"),
    },
    PyMethodDef::zeroed(),
];

unsafe extern "C" fn get_year(slf: *mut PyObject, _: *mut c_void) -> *mut PyObject {
    PyLong_FromUnsignedLong(Instant::extract(slf).date().year.into())
}

unsafe extern "C" fn get_month(slf: *mut PyObject, _: *mut c_void) -> *mut PyObject {
    PyLong_FromUnsignedLong(Instant::extract(slf).date().month.into())
}

unsafe extern "C" fn get_day(slf: *mut PyObject, _: *mut c_void) -> *mut PyObject {
    PyLong_FromUnsignedLong(Instant::extract(slf).date().day.into())
}

unsafe extern "C" fn get_hour(slf: *mut PyObject, _: *mut c_void) -> *mut PyObject {
    PyLong_FromUnsignedLong((Instant::extract(slf).secs % 86400 / 3600) as _)
}

unsafe extern "C" fn get_minute(slf: *mut PyObject, _: *mut c_void) -> *mut PyObject {
    PyLong_FromUnsignedLong((Instant::extract(slf).secs % 3600 / 60) as _)
}

unsafe extern "C" fn get_secs(slf: *mut PyObject, _: *mut c_void) -> *mut PyObject {
    PyLong_FromUnsignedLong((Instant::extract(slf).secs % 60) as _)
}

unsafe extern "C" fn get_nanos(slf: *mut PyObject, _: *mut c_void) -> *mut PyObject {
    PyLong_FromUnsignedLong(Instant::extract(slf).nanos.into())
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
