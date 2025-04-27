use core::ffi::{c_int, c_long, c_void, CStr};
use pyo3_ffi::*;
use std::fmt::{self, Display, Formatter};
use std::ptr::null_mut as NULL;

use crate::{
    common::*, date::Date, docstrings as doc, math::*, parse::Scan, plain_datetime::DateTime,
    round, State,
};

#[derive(Debug, Eq, PartialEq, Ord, PartialOrd, Copy, Clone)]
pub struct Time {
    pub(crate) hour: u8,
    pub(crate) minute: u8,
    pub(crate) second: u8,
    pub(crate) subsec: SubSecNanos,
}

impl Time {
    pub(crate) const fn pyhash(&self) -> Py_hash_t {
        #[cfg(target_pointer_width = "64")]
        {
            ((self.hour as Py_hash_t) << 48)
                | ((self.minute as Py_hash_t) << 40)
                | ((self.second as Py_hash_t) << 32)
                | (self.subsec.get() as Py_hash_t)
        }
        #[cfg(target_pointer_width = "32")]
        {
            hash_combine(
                (self.hour as Py_hash_t) << 16
                    | (self.minute as Py_hash_t) << 8
                    | (self.second as Py_hash_t),
                self.subsec.get() as Py_hash_t,
            )
        }
    }

    pub(crate) const fn total_seconds(&self) -> u32 {
        self.hour as u32 * 3600 + self.minute as u32 * 60 + self.second as u32
    }

    pub(crate) const fn from_sec_subsec(sec: u32, subsec: SubSecNanos) -> Self {
        Time {
            hour: (sec / 3600) as u8,
            minute: ((sec % 3600) / 60) as u8,
            second: (sec % 60) as u8,
            subsec,
        }
    }

    pub(crate) const fn total_nanos(&self) -> u64 {
        self.subsec.get() as u64 + self.total_seconds() as u64 * 1_000_000_000
    }

    pub(crate) fn from_total_nanos_unchecked(nanos: u64) -> Self {
        Time {
            hour: (nanos / 3_600_000_000_000) as u8,
            minute: ((nanos % 3_600_000_000_000) / 60_000_000_000) as u8,
            second: ((nanos % 60_000_000_000) / 1_000_000_000) as u8,
            subsec: SubSecNanos::from_remainder(nanos),
        }
    }

    pub(crate) fn from_longs(
        hour: c_long,
        minute: c_long,
        second: c_long,
        nanos: c_long,
    ) -> Option<Self> {
        if (0..24).contains(&hour) && (0..60).contains(&minute) && (0..60).contains(&second) {
            Some(Time {
                hour: hour as u8,
                minute: minute as u8,
                second: second as u8,
                subsec: SubSecNanos::from_long(nanos)?,
            })
        } else {
            None
        }
    }

    /// Read a time string in the ISO 8601 extended format (i.e. with ':' separators)
    pub(crate) fn read_iso_extended(s: &mut Scan) -> Option<Self> {
        // FUTURE: potential double checks coming from some callers
        let hour = s.digits00_23()?;
        let (minute, second, subsec) = match s.advance_on(b':') {
            // The "extended" format with mandatory ':' between components
            Some(true) => {
                let min = s.digits00_59()?;
                // seconds are still optional at this point
                let (sec, subsec) = match s.advance_on(b':') {
                    Some(true) => s.digits00_59().zip(s.subsec())?,
                    _ => (0, SubSecNanos::MIN),
                };
                (min, sec, subsec)
            }
            // No components besides hour
            _ => (0, 0, SubSecNanos::MIN),
        };
        Some(Time {
            hour,
            minute,
            second,
            subsec,
        })
    }

    pub(crate) fn read_iso_basic(s: &mut Scan) -> Option<Self> {
        let hour = s.digits00_23()?;
        let (minute, second, subsec) = match s.digits00_59() {
            Some(m) => {
                let (sec, sub) = match s.digits00_59() {
                    Some(n) => (n, s.subsec().unwrap_or(SubSecNanos::MIN)),
                    None => (0, SubSecNanos::MIN),
                };
                (m, sec, sub)
            }
            None => (0, 0, SubSecNanos::MIN),
        };
        Some(Time {
            hour,
            minute,
            second,
            subsec,
        })
    }

    pub(crate) fn read_iso(s: &mut Scan) -> Option<Self> {
        match s.get(2) {
            Some(b':') => Self::read_iso_extended(s),
            _ => Self::read_iso_basic(s),
        }
    }

    pub(crate) fn parse_iso(s: &[u8]) -> Option<Self> {
        Scan::new(s).parse_all(Self::read_iso)
    }

    /// Round the time to the specified increment
    ///
    /// Returns the rounded time and whether it has wrapped around to the next day (0 or 1)
    /// The increment is given in ns must be a divisor of 24 hours
    pub(crate) fn round(self, increment: u64, mode: round::Mode) -> (Self, u64) {
        debug_assert!(86_400_000_000_000 % increment == 0);
        let total_nanos = self.total_nanos();
        let quotient = total_nanos / increment;
        let remainder = total_nanos % increment;

        let threshold = match mode {
            round::Mode::HalfEven => 1.max(increment / 2 + (quotient % 2 == 0) as u64),
            round::Mode::Ceil => 1,
            round::Mode::Floor => increment + 1,
            round::Mode::HalfFloor => increment / 2 + 1,
            round::Mode::HalfCeil => 1.max(increment / 2),
        };
        let round_up = remainder >= threshold;
        let ns_since_midnight = (quotient + round_up as u64) * increment;
        (
            Self::from_total_nanos_unchecked(ns_since_midnight % 86_400_000_000_000),
            ns_since_midnight / 86_400_000_000_000,
        )
    }

    pub(crate) unsafe fn from_py_time_unchecked(time: *mut PyObject) -> Self {
        Time {
            hour: unsafe { PyDateTime_TIME_GET_HOUR(time) as u8 },
            minute: unsafe { PyDateTime_TIME_GET_MINUTE(time) as u8 },
            second: unsafe { PyDateTime_TIME_GET_SECOND(time) as u8 },
            subsec: SubSecNanos::from_py_time_unchecked(time),
        }
    }

    pub(crate) unsafe fn from_py_dt_unchecked(dt: *mut PyObject) -> Self {
        Time {
            hour: unsafe { PyDateTime_DATE_GET_HOUR(dt) as u8 },
            minute: unsafe { PyDateTime_DATE_GET_MINUTE(dt) as u8 },
            second: unsafe { PyDateTime_DATE_GET_SECOND(dt) as u8 },
            subsec: SubSecNanos::from_py_dt_unchecked(dt),
        }
    }

    pub(crate) const MIDNIGHT: Time = Time {
        hour: 0,
        minute: 0,
        second: 0,
        subsec: SubSecNanos::MIN,
    };
}

impl PyWrapped for Time {}

// FUTURE: a trait for faster formatting since timestamp are small and
// limited in length?
impl Display for Time {
    fn fmt(&self, f: &mut Formatter<'_>) -> fmt::Result {
        write!(
            f,
            "{:02}:{:02}:{:02}{}",
            self.hour, self.minute, self.second, self.subsec
        )
    }
}

pub(crate) const SINGLETONS: &[(&CStr, Time); 3] = &[
    (c"MIDNIGHT", Time::MIDNIGHT),
    (
        c"NOON",
        Time {
            hour: 12,
            minute: 0,
            second: 0,
            subsec: SubSecNanos::MIN,
        },
    ),
    (
        c"MAX",
        Time {
            hour: 23,
            minute: 59,
            second: 59,
            subsec: SubSecNanos::MAX,
        },
    ),
];

unsafe fn __new__(cls: *mut PyTypeObject, args: *mut PyObject, kwargs: *mut PyObject) -> PyReturn {
    let mut hour: c_long = 0;
    let mut minute: c_long = 0;
    let mut second: c_long = 0;
    let mut nanosecond: c_long = 0;

    parse_args_kwargs!(
        args,
        kwargs,
        c"|lll$l:Time",
        hour,
        minute,
        second,
        nanosecond
    );

    Time::from_longs(hour, minute, second, nanosecond)
        .ok_or_value_err("Invalid time component value")?
        .to_obj(cls)
}

unsafe fn __repr__(slf: *mut PyObject) -> PyReturn {
    format!("Time({})", Time::extract(slf)).to_py()
}

unsafe extern "C" fn __hash__(slf: *mut PyObject) -> Py_hash_t {
    hashmask(Time::extract(slf).pyhash())
}

unsafe fn __richcmp__(obj_a: *mut PyObject, obj_b: *mut PyObject, op: c_int) -> PyReturn {
    Ok(if Py_TYPE(obj_b) == Py_TYPE(obj_a) {
        let a = Time::extract(obj_a);
        let b = Time::extract(obj_b);
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

#[allow(static_mut_refs)]
static mut SLOTS: &[PyType_Slot] = &[
    slotmethod!(Py_tp_new, __new__),
    slotmethod!(Py_tp_str, format_common_iso, 2),
    slotmethod!(Py_tp_repr, __repr__, 1),
    slotmethod!(Py_tp_richcompare, __richcmp__),
    PyType_Slot {
        slot: Py_tp_doc,
        pfunc: doc::TIME.as_ptr() as *mut c_void,
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

unsafe fn py_time(slf: *mut PyObject, _: *mut PyObject) -> PyReturn {
    let Time {
        hour,
        minute,
        second,
        subsec,
    } = Time::extract(slf);
    let &PyDateTime_CAPI {
        Time_FromTime,
        TimeType,
        ..
    } = State::for_obj(slf).py_api;
    Time_FromTime(
        hour.into(),
        minute.into(),
        second.into(),
        (subsec.get() / 1_000) as c_int,
        Py_None(),
        TimeType,
    )
    .as_result()
}

unsafe fn from_py_time(type_: *mut PyObject, time: *mut PyObject) -> PyReturn {
    if PyTime_Check(time) == 0 {
        raise_type_err("argument must be a datetime.time")?
    }
    if !is_none(get_time_tzinfo(time)) {
        raise_value_err("time with tzinfo is not supported")?
    }
    // FUTURE: check `fold=0`?
    Time::from_py_time_unchecked(time).to_obj(type_.cast())
}

unsafe fn format_common_iso(slf: *mut PyObject, _: *mut PyObject) -> PyReturn {
    format!("{}", Time::extract(slf)).to_py()
}

unsafe fn __reduce__(slf: *mut PyObject, _: *mut PyObject) -> PyReturn {
    let Time {
        hour,
        minute,
        second,
        subsec: nanos,
    } = Time::extract(slf);
    let data = pack![hour, minute, second, nanos.get()];
    (
        State::for_obj(slf).unpickle_time,
        steal!((steal!(data.to_py()?),).to_py()?),
    )
        .to_py()
}

unsafe fn parse_common_iso(cls: *mut PyObject, s: *mut PyObject) -> PyReturn {
    Time::parse_iso(s.to_utf8()?.ok_or_type_err("Argument must be a string")?)
        .ok_or_else_value_err(|| format!("Invalid format: {}", s.repr()))?
        .to_obj(cls.cast())
}

unsafe fn on(slf: *mut PyObject, date: *mut PyObject) -> PyReturn {
    let &State {
        plain_datetime_type,
        date_type,
        ..
    } = State::for_obj(slf);
    if Py_TYPE(date) == date_type {
        DateTime {
            date: Date::extract(date),
            time: Time::extract(slf),
        }
        .to_obj(plain_datetime_type)
    } else {
        raise_type_err("argument must be a date")
    }
}

unsafe fn replace(
    slf: *mut PyObject,
    type_: *mut PyTypeObject,
    args: &[*mut PyObject],
    kwargs: &mut KwargIter,
) -> PyReturn {
    let &State {
        str_hour,
        str_minute,
        str_second,
        str_nanosecond,
        ..
    } = State::for_type(type_);
    if !args.is_empty() {
        raise_type_err("replace() takes no positional arguments")
    } else {
        let time = Time::extract(slf);
        let mut hour = time.hour.into();
        let mut minute = time.minute.into();
        let mut second = time.second.into();
        let mut nanos = time.subsec.get() as _;
        handle_kwargs("replace", kwargs, |key, value, eq| {
            if eq(key, str_hour) {
                hour = value.to_long()?.ok_or_type_err("hour must be an integer")?;
            } else if eq(key, str_minute) {
                minute = value
                    .to_long()?
                    .ok_or_type_err("minute must be an integer")?;
            } else if eq(key, str_second) {
                second = value
                    .to_long()?
                    .ok_or_type_err("second must be an integer")?;
            } else if eq(key, str_nanosecond) {
                nanos = value
                    .to_long()?
                    .ok_or_type_err("nanosecond must be an integer")?;
            } else {
                return Ok(false);
            }
            Ok(true)
        })?;
        Time::from_longs(hour, minute, second, nanos)
            .ok_or_value_err("Invalid time component value")?
            .to_obj(type_)
    }
}

unsafe fn round(
    slf: *mut PyObject,
    cls: *mut PyTypeObject,
    args: &[*mut PyObject],
    kwargs: &mut KwargIter,
) -> PyReturn {
    let (unit, increment, mode) =
        round::parse_args(State::for_obj(slf), args, kwargs, false, false)?;
    if unit == round::Unit::Day {
        raise_value_err("Cannot round Time to day")?;
    } else if unit == round::Unit::Hour && 86_400_000_000_000 % increment != 0 {
        raise_value_err("increment must be a divisor of 24")?;
    }
    Time::extract(slf)
        .round(increment as u64, mode)
        .0
        .to_obj(cls)
}

static mut METHODS: &[PyMethodDef] = &[
    method!(identity2 named "__copy__", c""),
    method!(identity2 named "__deepcopy__", c"", METH_O),
    method!(__reduce__, c""),
    method!(py_time, doc::TIME_PY_TIME),
    method_kwargs!(replace, doc::TIME_REPLACE),
    method!(format_common_iso, doc::TIME_FORMAT_COMMON_ISO),
    method!(
        parse_common_iso,
        doc::TIME_PARSE_COMMON_ISO,
        METH_O | METH_CLASS
    ),
    method!(from_py_time, doc::TIME_FROM_PY_TIME, METH_O | METH_CLASS),
    method!(on, doc::TIME_ON, METH_O),
    method_kwargs!(round, doc::TIME_ROUND),
    PyMethodDef::zeroed(),
];

pub(crate) unsafe fn unpickle(module: *mut PyObject, arg: *mut PyObject) -> PyReturn {
    let mut data = arg.to_bytes()?.ok_or_type_err("Invalid pickle data")?;
    if data.len() != 7 {
        raise_type_err("Invalid pickle data")?
    }
    Time {
        hour: unpack_one!(data, u8),
        minute: unpack_one!(data, u8),
        second: unpack_one!(data, u8),
        subsec: SubSecNanos::new_unchecked(unpack_one!(data, i32)),
    }
    .to_obj(State::for_mod(module).time_type)
}

unsafe fn get_hour(slf: *mut PyObject) -> PyReturn {
    Time::extract(slf).hour.to_py()
}

unsafe fn get_minute(slf: *mut PyObject) -> PyReturn {
    Time::extract(slf).minute.to_py()
}

unsafe fn get_second(slf: *mut PyObject) -> PyReturn {
    Time::extract(slf).second.to_py()
}

unsafe fn get_nanos(slf: *mut PyObject) -> PyReturn {
    Time::extract(slf).subsec.get().to_py()
}

static mut GETSETTERS: &[PyGetSetDef] = &[
    getter!(get_hour named "hour", "The hour component"),
    getter!(get_minute named "minute", "The minute component"),
    getter!(get_second named "second", "The second component"),
    getter!(get_nanos named "nanosecond", "The nanosecond component"),
    PyGetSetDef {
        name: NULL(),
        get: None,
        set: None,
        doc: NULL(),
        closure: NULL(),
    },
];

pub(crate) static mut SPEC: PyType_Spec = type_spec::<Time>(c"whenever.Time", unsafe { SLOTS });
