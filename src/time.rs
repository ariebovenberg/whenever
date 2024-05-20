use core::ffi::{c_char, c_int, c_long, c_void};
use core::{mem, ptr};
use pyo3_ffi::*;
use std::fmt::{self, Display, Formatter};
use std::ptr::null_mut as NULL;

use crate::common::*;
use crate::date::Date;
use crate::naive_datetime::{self, DateTime};
use crate::State;

#[derive(Debug, Eq, PartialEq, Ord, PartialOrd, Copy, Clone)]
pub struct Time {
    pub(crate) hour: u8,
    pub(crate) minute: u8,
    pub(crate) second: u8,
    pub(crate) nanos: u32,
}

#[repr(C)]
pub(crate) struct PyTime {
    _ob_base: PyObject,
    data: Time,
}

impl Time {
    #[cfg(target_pointer_width = "32")]
    pub(crate) const fn pyhash(&self) -> Py_hash_t {
        hashmask(
            ((self.hour as Py_hash_t) << 16)
                ^ ((self.minute as Py_hash_t) << 8)
                ^ (self.second as Py_hash_t)
                ^ (self.nanos as Py_hash_t),
        )
    }

    #[cfg(target_pointer_width = "64")]
    pub(crate) const fn pyhash(&self) -> Py_hash_t {
        hashmask(
            ((self.hour as Py_hash_t) << 48)
                | ((self.minute as Py_hash_t) << 40)
                | ((self.second as Py_hash_t) << 32) ^ (self.nanos as Py_hash_t),
        )
    }

    pub(crate) const fn seconds(&self) -> i32 {
        self.hour as i32 * 3600 + self.minute as i32 * 60 + self.second as i32
    }

    pub(crate) const fn set_seconds(mut self, seconds: u32) -> Self {
        self.hour = (seconds / 3600) as u8;
        self.minute = ((seconds % 3600) / 60) as u8;
        self.second = (seconds % 60) as u8;
        self
    }

    pub(crate) const fn total_nanos(&self) -> u64 {
        self.nanos as u64 + self.seconds() as u64 * 1_000_000_000
    }

    pub(crate) const fn from_total_nanos(nanos: u64) -> Self {
        Time {
            hour: (nanos / 3_600_000_000_000) as u8,
            minute: ((nanos % 3_600_000_000_000) / 60_000_000_000) as u8,
            second: ((nanos % 60_000_000_000) / 1_000_000_000) as u8,
            nanos: (nanos % 1_000_000_000) as u32,
        }
    }

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

    pub(crate) const fn from_longs(
        hour: c_long,
        minute: c_long,
        second: c_long,
        nanos: c_long,
    ) -> Option<Self> {
        if hour < 0 || hour > 23 {
            return None;
        }
        if minute < 0 || minute > 59 {
            return None;
        }
        if second < 0 || second > 59 {
            return None;
        }
        if nanos < 0 || nanos > 999_999_999 {
            return None;
        }
        Some(Time {
            hour: hour as u8,
            minute: minute as u8,
            second: second as u8,
            nanos: nanos as u32,
        })
    }

    pub(crate) fn extract(obj: *mut PyObject) -> Self {
        unsafe { (*obj.cast::<PyTime>()).data }
    }

    pub(crate) fn parse_all(s: &[u8]) -> Option<Self> {
        if s.len() < 8 || s.len() == 9 || s.len() > 18 || s[2] != b':' || s[5] != b':' {
            return None;
        }
        let hour = get_digit!(s, 0) * 10 + get_digit!(s, 1);
        let minute = get_digit!(s, 3) * 10 + get_digit!(s, 4);
        let second = get_digit!(s, 6) * 10 + get_digit!(s, 7);
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
        let hour = get_digit!(s, 0) * 10 + get_digit!(s, 1);
        let minute = get_digit!(s, 3) * 10 + get_digit!(s, 4);
        let second = get_digit!(s, 6) * 10 + get_digit!(s, 7);
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

pub(crate) const SINGLETONS: [(&str, Time); 3] = [
    (
        "MIDNIGHT\0",
        Time {
            hour: 0,
            minute: 0,
            second: 0,
            nanos: 0,
        },
    ),
    (
        "NOON\0",
        Time {
            hour: 12,
            minute: 0,
            second: 0,
            nanos: 0,
        },
    ),
    (
        "MAX\0",
        Time {
            hour: 23,
            minute: 59,
            second: 59,
            nanos: 999_999_999,
        },
    ),
];

unsafe fn __new__(
    subtype: *mut PyTypeObject,
    args: *mut PyObject,
    kwargs: *mut PyObject,
) -> PyReturn {
    let mut hour: c_long = 0;
    let mut minute: c_long = 0;
    let mut second: c_long = 0;
    let mut nanos: c_long = 0;

    // FUTURE: parse them manually, which is more efficient
    if PyArg_ParseTupleAndKeywords(
        args,
        kwargs,
        c_str!("|llll:Time"),
        vec![
            c_str!("hour") as *mut c_char,
            c_str!("minute") as *mut c_char,
            c_str!("second") as *mut c_char,
            c_str!("nanosecond") as *mut c_char,
            NULL(),
        ]
        .as_mut_ptr(),
        &mut hour,
        &mut minute,
        &mut second,
        &mut nanos,
    ) == 0
    {
        Err(PyErrOccurred())?
    }

    match Time::from_longs(hour, minute, second, nanos) {
        Some(time) => new_unchecked(subtype, time),
        None => Err(value_error!("Invalid time component value")),
    }
}

unsafe fn __repr__(slf: *mut PyObject) -> PyReturn {
    format!("Time({})", _default_fmt(Time::extract(slf))).to_py()
}

unsafe extern "C" fn __hash__(slf: *mut PyObject) -> Py_hash_t {
    Time::extract(slf).pyhash()
}

unsafe fn __richcmp__(obj_a: *mut PyObject, obj_b: *mut PyObject, op: c_int) -> PyReturn {
    Ok(newref(if Py_TYPE(obj_b) == Py_TYPE(obj_a) {
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
        Py_NotImplemented()
    }))
}

static mut SLOTS: &[PyType_Slot] = &[
    slotmethod!(Py_tp_new, __new__),
    slotmethod!(Py_tp_str, default_format, 2),
    slotmethod!(Py_tp_repr, __repr__, 1),
    slotmethod!(Py_tp_richcompare, __richcmp__),
    PyType_Slot {
        slot: Py_tp_doc,
        pfunc: "A time type\0".as_ptr() as *mut c_void,
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
        pfunc: dealloc as *mut c_void,
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
    } = State::for_obj(slf).datetime_api;
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
        Err(type_error!("argument must be a Time"))?
    }
    if PyDateTime_TIME_GET_TZINFO(time) != Py_None() {
        Err(value_error!("time with timezone is not supported"))?
    }
    // TODO: check fold etc.
    new_unchecked(
        type_.cast(),
        Time {
            hour: PyDateTime_TIME_GET_HOUR(time) as u8,
            minute: PyDateTime_TIME_GET_MINUTE(time) as u8,
            second: PyDateTime_TIME_GET_SECOND(time) as u8,
            nanos: PyDateTime_TIME_GET_MICROSECOND(time) as u32 * 1_000,
        },
    )
}

unsafe fn default_format(slf: *mut PyObject, _: *mut PyObject) -> PyReturn {
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
    PyTuple_Pack(
        2,
        State::for_obj(slf).unpickle_time,
        steal!(PyTuple_Pack(1, steal!(pack![hour, minute, second, nanos].to_py()?)).as_result()?),
    )
    .as_result()
}

unsafe fn from_default_format(cls: *mut PyObject, s: *mut PyObject) -> PyReturn {
    match Time::parse_all(
        s.to_utf8()?
            .ok_or_else(|| type_error!("Argument must be a string"))?,
    ) {
        Some(t) => new_unchecked(cls.cast(), t),
        None => Err(value_error!("Could not parse time: %R", s)),
    }
}

unsafe fn on(slf: *mut PyObject, date: *mut PyObject) -> PyReturn {
    let &State {
        naive_datetime_type,
        date_type,
        ..
    } = State::for_obj(slf);
    if Py_TYPE(date) == date_type {
        naive_datetime::new_unchecked(
            naive_datetime_type,
            DateTime {
                date: Date::extract(date),
                time: Time::extract(slf),
            },
        )
    } else {
        Err(type_error!("argument must be a date"))
    }
}

static mut METHODS: &[PyMethodDef] = &[
    method!(py_time, "Convert to a Python datetime.time"),
    method!(default_format, ""),
    method!(
        default_format named "common_iso8601",
        "Return the time in the common ISO 8601 format"
    ),
    method!(from_default_format, "", METH_O | METH_CLASS),
    method!(
        from_default_format named "from_common_iso8601", 
        "Create a date from the common ISO 8601 format", 
        METH_O | METH_CLASS),
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

pub(crate) unsafe fn new_unchecked(type_: *mut PyTypeObject, t: Time) -> PyReturn {
    let f: allocfunc = (*type_).tp_alloc.expect("tp_alloc is not set");
    let slf = f(type_, 0).cast::<PyTime>();
    if slf.is_null() {
        return Err(PyErrOccurred());
    }
    ptr::addr_of_mut!((*slf).data).write(t);
    Ok(slf.cast::<PyObject>().as_mut().unwrap())
}

// OPTIMIZE: a more efficient pickle?
pub(crate) unsafe fn unpickle(module: *mut PyObject, args: &[*mut PyObject]) -> PyReturn {
    if args.len() != 1 {
        Err(type_error!("Invalid pickle data"))?
    }
    let mut data = args[0]
        .to_bytes()?
        .ok_or_else(|| type_error!("Invalid pickle data"))?;
    let new = new_unchecked(
        State::for_mod(module).time_type,
        Time {
            hour: unpack_one!(data, u8),
            minute: unpack_one!(data, u8),
            second: unpack_one!(data, u8),
            nanos: unpack_one!(data, u32),
        },
    );
    if !data.is_empty() {
        Err(type_error!("Invalid pickle data"))?
    }
    new
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

pub(crate) static mut SPEC: PyType_Spec = PyType_Spec {
    name: c_str!("whenever.Time"),
    basicsize: mem::size_of::<PyTime>() as _,
    itemsize: 0,
    flags: Py_TPFLAGS_DEFAULT as _,
    slots: unsafe { SLOTS as *const [_] as *mut _ },
};