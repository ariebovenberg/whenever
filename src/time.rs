use core::ffi::{c_int, c_long, c_void, CStr};
use core::mem;
use pyo3_ffi::*;
use std::fmt::{self, Display, Formatter};
use std::ptr::null_mut as NULL;

use crate::common::*;
use crate::date::Date;
use crate::local_datetime::DateTime;
use crate::State;

#[derive(Debug, Eq, PartialEq, Ord, PartialOrd, Copy, Clone)]
pub struct Time {
    pub(crate) hour: u8,
    pub(crate) minute: u8,
    pub(crate) second: u8,
    pub(crate) nanos: u32,
}

impl Time {
    pub(crate) const fn new(hour: u8, minute: u8, second: u8, nanos: u32) -> Option<Self> {
        if hour > 23 || minute > 59 || second > 59 || nanos > 999_999_999 {
            None
        } else {
            Some(Time {
                hour,
                minute,
                second,
                nanos,
            })
        }
    }

    #[cfg(target_pointer_width = "32")]
    pub(crate) const fn pyhash(&self) -> Py_hash_t {
        hash_combine(
            (self.hour as Py_hash_t) << 16
                | (self.minute as Py_hash_t) << 8
                | (self.second as Py_hash_t),
            self.nanos as Py_hash_t,
        )
    }

    #[cfg(target_pointer_width = "64")]
    pub(crate) const fn pyhash(&self) -> Py_hash_t {
        ((self.hour as Py_hash_t) << 48)
            | ((self.minute as Py_hash_t) << 40)
            | ((self.second as Py_hash_t) << 32)
            | (self.nanos as Py_hash_t)
    }

    pub(crate) const fn total_seconds(&self) -> i32 {
        self.hour as i32 * 3600 + self.minute as i32 * 60 + self.second as i32
    }

    pub(crate) const fn set_seconds(mut self, seconds: u32) -> Self {
        self.hour = (seconds / 3600) as u8;
        self.minute = ((seconds % 3600) / 60) as u8;
        self.second = (seconds % 60) as u8;
        self
    }

    pub(crate) const fn total_nanos(&self) -> u64 {
        self.nanos as u64 + self.total_seconds() as u64 * 1_000_000_000
    }

    pub(crate) const fn from_total_nanos(nanos: u64) -> Self {
        Time {
            hour: (nanos / 3_600_000_000_000) as u8,
            minute: ((nanos % 3_600_000_000_000) / 60_000_000_000) as u8,
            second: ((nanos % 60_000_000_000) / 1_000_000_000) as u8,
            nanos: (nanos % 1_000_000_000) as u32,
        }
    }

    pub(crate) const fn from_longs(
        hour: c_long,
        minute: c_long,
        second: c_long,
        nanos: c_long,
    ) -> Option<Self> {
        if hour < 0
            || hour > 23
            || minute < 0
            || minute > 59
            || second < 0
            || second > 59
            || nanos < 0
            || nanos > 999_999_999
        {
            None
        } else {
            Some(Time {
                hour: hour as u8,
                minute: minute as u8,
                second: second as u8,
                nanos: nanos as u32,
            })
        }
    }

    pub(crate) fn parse_all(s: &[u8]) -> Option<Self> {
        if s.len() < 8 || s.len() == 9 || s.len() > 18 || s[2] != b':' || s[5] != b':' {
            return None;
        }
        let hour = parse_digit_max(s, 0, b'2')? * 10 + parse_digit(s, 1)?;
        let minute = parse_digit_max(s, 3, b'5')? * 10 + parse_digit(s, 4)?;
        let second = parse_digit_max(s, 6, b'5')? * 10 + parse_digit(s, 7)?;
        let mut nanos: u32 = 0;
        if s.len() > 8 {
            if s[8] != b'.' {
                return None;
            }
            for (i, factor) in s[9..].iter().zip(&[
                100_000_000,
                10_000_000,
                1_000_000,
                100_000,
                10_000,
                1_000,
                100,
                10,
                1,
            ]) {
                if !i.is_ascii_digit() {
                    return None;
                }
                nanos += ((i - b'0') as u32) * factor;
            }
        }
        Time::new(hour, minute, second, nanos)
    }

    pub(crate) fn parse_partial(s: &mut &[u8]) -> Option<Self> {
        debug_assert!(s.len() > 7);
        if s[2] != b':' || s[5] != b':' {
            return None;
        }
        let hour = parse_digit_max(s, 0, b'2')? * 10 + parse_digit(s, 1)?;
        let minute = parse_digit_max(s, 3, b'5')? * 10 + parse_digit(s, 4)?;
        let second = parse_digit_max(s, 6, b'5')? * 10 + parse_digit(s, 7)?;
        let mut nanos: u32 = 0;
        let mut end_index = 8;
        if s.len() > 8 && s[8] == b'.' {
            for (i, factor) in (9..s.len()).zip(&[
                100_000_000,
                10_000_000,
                1_000_000,
                100_000,
                10_000,
                1_000,
                100,
                10,
                1,
            ]) {
                if !s[i].is_ascii_digit() {
                    end_index = i;
                    break;
                }
                end_index = i + 1;
                nanos += ((s[i] - b'0') as u32) * factor;
            }
        }
        let result = Time::new(hour, minute, second, nanos);
        *s = &s[end_index..]; // advance the slice
        result
    }
}

impl PyWrapped for Time {}

impl Display for Time {
    fn fmt(&self, f: &mut Formatter<'_>) -> fmt::Result {
        if self.nanos == 0 {
            write!(f, "{:02}:{:02}:{:02}", self.hour, self.minute, self.second)
        } else {
            f.write_str(
                format!(
                    "{:02}:{:02}:{:02}.{:09}",
                    self.hour, self.minute, self.second, self.nanos
                )
                .trim_end_matches('0'),
            )
        }
    }
}

pub(crate) const SINGLETONS: &[(&CStr, Time); 3] = &[
    (
        c"MIDNIGHT",
        Time {
            hour: 0,
            minute: 0,
            second: 0,
            nanos: 0,
        },
    ),
    (
        c"NOON",
        Time {
            hour: 12,
            minute: 0,
            second: 0,
            nanos: 0,
        },
    ),
    (
        c"MAX",
        Time {
            hour: 23,
            minute: 59,
            second: 59,
            nanos: 999_999_999,
        },
    ),
];

unsafe fn __new__(cls: *mut PyTypeObject, args: *mut PyObject, kwargs: *mut PyObject) -> PyReturn {
    let mut hour: c_long = 0;
    let mut minute: c_long = 0;
    let mut second: c_long = 0;
    let mut nanos: c_long = 0;

    // FUTURE: parse them manually, which is more efficient
    if PyArg_ParseTupleAndKeywords(
        args,
        kwargs,
        c"|lll$l:Time".as_ptr(),
        vec![
            c"hour".as_ptr() as *mut _,
            c"minute".as_ptr() as *mut _,
            c"second".as_ptr() as *mut _,
            c"nanosecond".as_ptr() as *mut _,
            NULL(),
        ]
        .as_mut_ptr(),
        &mut hour,
        &mut minute,
        &mut second,
        &mut nanos,
    ) == 0
    {
        Err(py_err!())?
    }

    Time::from_longs(hour, minute, second, nanos)
        .ok_or_value_err("Invalid time component value")?
        .to_obj(cls)
}

unsafe fn __repr__(slf: *mut PyObject) -> PyReturn {
    format!("Time({})", _default_fmt(Time::extract(slf))).to_py()
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

static mut SLOTS: &[PyType_Slot] = &[
    slotmethod!(Py_tp_new, __new__),
    slotmethod!(Py_tp_str, format_common_iso, 2),
    slotmethod!(Py_tp_repr, __repr__, 1),
    slotmethod!(Py_tp_richcompare, __richcmp__),
    PyType_Slot {
        slot: Py_tp_doc,
        pfunc: c"A type representing the time of day".as_ptr() as *mut c_void,
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
        nanos,
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
        (nanos / 1_000) as c_int,
        Py_None(),
        TimeType,
    )
    .as_result()
}

unsafe fn from_py_time(type_: *mut PyObject, time: *mut PyObject) -> PyReturn {
    if PyTime_Check(time) == 0 {
        Err(type_err!("argument must be a whenever.Time"))?
    }
    if get_time_tzinfo(time) != Py_None() {
        Err(value_err!("time with timezone is not supported"))?
    }
    // FUTURE: check `fold=0`?
    Time {
        hour: PyDateTime_TIME_GET_HOUR(time) as u8,
        minute: PyDateTime_TIME_GET_MINUTE(time) as u8,
        second: PyDateTime_TIME_GET_SECOND(time) as u8,
        nanos: PyDateTime_TIME_GET_MICROSECOND(time) as u32 * 1_000,
    }
    .to_obj(type_.cast())
}

unsafe fn format_common_iso(slf: *mut PyObject, _: *mut PyObject) -> PyReturn {
    _default_fmt(Time::extract(slf)).to_py()
}

fn _default_fmt(time: Time) -> String {
    if time.nanos == 0 {
        format!("{:02}:{:02}:{:02}", time.hour, time.minute, time.second)
    } else {
        format!(
            "{:02}:{:02}:{:02}.{:09}",
            time.hour, time.minute, time.second, time.nanos
        )
        .trim_end_matches('0')
        .to_string()
    }
}

unsafe fn __reduce__(slf: *mut PyObject, _: *mut PyObject) -> PyReturn {
    let Time {
        hour,
        minute,
        second,
        nanos,
    } = Time::extract(slf);
    let data = pack![hour, minute, second, nanos];
    (
        State::for_obj(slf).unpickle_time,
        steal!((steal!(data.to_py()?),).to_py()?),
    )
        .to_py()
}

unsafe fn parse_common_iso(cls: *mut PyObject, s: *mut PyObject) -> PyReturn {
    Time::parse_all(s.to_utf8()?.ok_or_type_err("Argument must be a string")?)
        .ok_or_else(|| value_err!("Invalid format: {}", s.repr()))?
        .to_obj(cls.cast())
}

unsafe fn on(slf: *mut PyObject, date: *mut PyObject) -> PyReturn {
    let &State {
        local_datetime_type,
        date_type,
        ..
    } = State::for_obj(slf);
    if Py_TYPE(date) == date_type {
        DateTime {
            date: Date::extract(date),
            time: Time::extract(slf),
        }
        .to_obj(local_datetime_type)
    } else {
        Err(type_err!("argument must be a date"))
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
        Err(type_err!("replace() takes no positional arguments"))
    } else {
        let time = Time::extract(slf);
        let mut hour = time.hour.into();
        let mut minute = time.minute.into();
        let mut second = time.second.into();
        let mut nanos = time.nanos as _;
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

static mut METHODS: &[PyMethodDef] = &[
    method!(py_time, "Convert to a Python datetime.time"),
    method_kwargs!(replace, "Replace one or more components of the time"),
    method!(
        format_common_iso,
        "Return the time in the common ISO 8601 format"
    ),
    method!(
        parse_common_iso,
        "Create an instance from the common ISO 8601 format",
        METH_O | METH_CLASS
    ),
    method!(
        from_py_time,
        "Create a time from a Python datetime.time",
        METH_O | METH_CLASS
    ),
    method!(identity2 named "__copy__", ""),
    method!(identity2 named "__deepcopy__", "", METH_O),
    method!(__reduce__, ""),
    method!(on, "Combine with a date to create a datetime", METH_O),
    PyMethodDef::zeroed(),
];

pub(crate) unsafe fn unpickle(module: *mut PyObject, arg: *mut PyObject) -> PyReturn {
    let mut data = arg.to_bytes()?.ok_or_type_err("Invalid pickle data")?;
    if data.len() != 7 {
        Err(type_err!("Invalid pickle data"))?
    }
    Time {
        hour: unpack_one!(data, u8),
        minute: unpack_one!(data, u8),
        second: unpack_one!(data, u8),
        nanos: unpack_one!(data, u32),
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
    Time::extract(slf).nanos.to_py()
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

type_spec!(Time, SLOTS);
