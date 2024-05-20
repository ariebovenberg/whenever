use core::ffi::{c_char, c_int, c_long, c_void};
use core::{mem, ptr, ptr::null_mut as NULL};
use pyo3_ffi::*;

use crate::common::*;
use crate::{
    date::{self, Date},
    date_delta::DateDelta,
    time::{self, Time},
    time_delta::TimeDelta,
    utc_datetime, State,
};

#[derive(Debug, Eq, PartialEq, Ord, PartialOrd, Copy, Clone)]
pub(crate) struct DateTime {
    pub date: date::Date,
    pub time: time::Time,
}

#[repr(C)]
pub(crate) struct PyNaiveDateTime {
    _ob_base: PyObject,
    data: DateTime,
}

pub(crate) const SINGLETONS: [(&str, DateTime); 2] = [
    (
        "MIN\0",
        DateTime {
            date: date::Date {
                year: 1,
                month: 1,
                day: 1,
            },
            time: time::Time {
                hour: 0,
                minute: 0,
                second: 0,
                nanos: 0,
            },
        },
    ),
    (
        "MAX\0",
        DateTime {
            date: date::Date {
                year: 9999,
                month: 12,
                day: 31,
            },
            time: time::Time {
                hour: 23,
                minute: 59,
                second: 59,
                nanos: 999_999_999,
            },
        },
    ),
];

impl DateTime {
    #[inline]
    pub(crate) fn default_fmt(&self) -> String {
        if self.time.nanos == 0 {
            format!(
                "{:04}-{:02}-{:02}T{:02}:{:02}:{:02}",
                self.date.year,
                self.date.month,
                self.date.day,
                self.time.hour,
                self.time.minute,
                self.time.second,
            )
        } else {
            format!(
                "{:04}-{:02}-{:02}T{:02}:{:02}:{:02}.{:09}",
                self.date.year,
                self.date.month,
                self.date.day,
                self.time.hour,
                self.time.minute,
                self.time.second,
                self.time.nanos,
            )
            .trim_end_matches('0')
            .to_string()
        }
    }

    #[inline]
    pub(crate) fn extract(obj: *mut PyObject) -> Self {
        unsafe { (*(obj.cast::<PyNaiveDateTime>())).data }
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

    // FUTURE: parse them manually, which is more efficient
    if PyArg_ParseTupleAndKeywords(
        args,
        kwargs,
        c_str!("lll|llll:NaiveDateTime"),
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
        Err(PyErrOccurred())?
    }

    new_unchecked(
        cls,
        DateTime {
            date: Date::from_longs(year, month, day).ok_or_else(|| type_error!("Invalid date"))?,
            time: Time::from_longs(hour, minute, second, nanos)
                .ok_or_else(|| type_error!("Invalid time"))?,
        },
    )
}

pub(crate) unsafe fn new_unchecked(type_: *mut PyTypeObject, dt: DateTime) -> PyReturn {
    let f: allocfunc = (*type_).tp_alloc.expect("tp_alloc is not set");
    let slf = f(type_, 0).cast::<PyNaiveDateTime>();
    if slf.is_null() {
        return Err(PyErrOccurred());
    }
    ptr::addr_of_mut!((*slf).data).write(dt);
    Ok(slf.cast::<PyObject>().as_mut().unwrap())
}

unsafe fn __repr__(slf: *mut PyObject) -> PyReturn {
    let DateTime { date, time } = DateTime::extract(slf);
    format!("NaiveDateTime({} {})", date, time).to_py()
}

unsafe fn __str__(slf: *mut PyObject) -> PyReturn {
    DateTime::extract(slf).default_fmt().to_py()
}

unsafe fn default_format(slf: *mut PyObject, _: *mut PyObject) -> PyReturn {
    __str__(slf)
}

unsafe fn __richcmp__(a_obj: *mut PyObject, b_obj: *mut PyObject, op: c_int) -> PyReturn {
    Ok(newref(if Py_TYPE(b_obj) == Py_TYPE(a_obj) {
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
        Py_NotImplemented()
    }))
}

unsafe extern "C" fn __hash__(slf: *mut PyObject) -> Py_hash_t {
    let DateTime { date, time } = DateTime::extract(slf);
    hashmask(date.hash() as Py_hash_t ^ time.pyhash())
}

unsafe fn __add__(obj_a: *mut PyObject, obj_b: *mut PyObject) -> PyReturn {
    // TODO: reflexivity
    let type_b = Py_TYPE(obj_b);
    let type_a = Py_TYPE(obj_a);
    let a = DateTime::extract(obj_a);
    let &State {
        date_delta_type,
        time_delta_type,
        ..
    } = State::for_type(type_a);
    if type_b == time_delta_type {
        let new_nanos = a.time.total_nanos() as i128 + TimeDelta::extract(obj_b).total_nanos();
        match new_nanos
            .div_euclid(86_400_000_000_000)
            .try_into()
            .ok()
            .and_then(|days| a.date.shift(0, 0, days))
        {
            Some(date) => new_unchecked(
                type_a,
                DateTime {
                    date,
                    time: Time::from_total_nanos(new_nanos.rem_euclid(86_400_000_000_000) as u64),
                },
            ),
            None => Err(value_error!("Resulting date out of range")),
        }
    } else if type_b == date_delta_type {
        match _add_datedelta(a, DateDelta::extract(obj_b)) {
            Some(dt) => new_unchecked(type_a, dt),
            None => Err(value_error!("Resulting date out of range")),
        }
    } else {
        Ok(newref(Py_NotImplemented()))
    }
}

unsafe fn __sub__(obj_a: *mut PyObject, obj_b: *mut PyObject) -> PyReturn {
    let slf = DateTime::extract(obj_a);
    if Py_TYPE(obj_b) == State::for_type(Py_TYPE(obj_a)).date_delta_type {
        match _add_datedelta(slf, -DateDelta::extract(obj_b)) {
            Some(dt) => new_unchecked(Py_TYPE(obj_a), dt),
            None => Err(value_error!("Resulting date out of range")),
        }
    } else {
        Ok(newref(Py_NotImplemented()))
    }
}

fn _add_datedelta(dt: DateTime, delta: DateDelta) -> Option<DateTime> {
    dt.date
        .shift(0, delta.months, delta.days)
        .map(|date| DateTime { date, ..dt })
}

static mut SLOTS: &[PyType_Slot] = &[
    slotmethod!(Py_tp_new, __new__),
    slotmethod!(Py_tp_repr, __repr__, 1),
    slotmethod!(Py_tp_str, __str__, 1),
    slotmethod!(Py_tp_richcompare, __richcmp__),
    slotmethod!(Py_nb_add, __add__, 2),
    slotmethod!(Py_nb_subtract, __sub__, 2),
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

unsafe fn replace(
    slf: *mut PyObject,
    cls: *mut PyTypeObject,
    args: &[*mut PyObject],
    kwargs: &[(*mut PyObject, *mut PyObject)],
) -> PyReturn {
    if !args.is_empty() {
        Err(type_error!("replace() takes no positional arguments"))?
    }
    let module = State::for_type(cls);
    let dt = DateTime::extract(slf);
    let mut year = dt.date.year as c_long;
    let mut month = dt.date.month as c_long;
    let mut day = dt.date.day as c_long;
    let mut hour = dt.time.hour as c_long;
    let mut minute = dt.time.minute as c_long;
    let mut second = dt.time.second as c_long;
    let mut nanos = dt.time.nanos as c_long;
    for &(name, value) in kwargs {
        if name == module.str_year {
            year = value
                .to_long()?
                .ok_or_else(|| type_error!("year must be an integer"))?;
        } else if name == module.str_month {
            month = value
                .to_long()?
                .ok_or_else(|| type_error!("month must be an integer"))?;
        } else if name == module.str_day {
            day = value
                .to_long()?
                .ok_or_else(|| type_error!("day must be an integer"))?;
        } else if name == module.str_hour {
            hour = value
                .to_long()?
                .ok_or_else(|| type_error!("hour must be an integer"))?;
        } else if name == module.str_minute {
            minute = value
                .to_long()?
                .ok_or_else(|| type_error!("minute must be an integer"))?;
        } else if name == module.str_second {
            second = value
                .to_long()?
                .ok_or_else(|| type_error!("second must be an integer"))?;
        } else if name == module.str_nanosecond {
            nanos = value
                .to_long()?
                .ok_or_else(|| type_error!("nanosecond must be an integer"))?;
        } else {
            Err(type_error!(
                "replace() got an unexpected keyword argument: %R",
                name
            ))?
        }
    }
    new_unchecked(
        cls,
        DateTime {
            date: Date::from_longs(year, month, day).ok_or_else(|| type_error!("Invalid date"))?,
            time: Time::from_longs(hour, minute, second, nanos)
                .ok_or_else(|| type_error!("Invalid time"))?,
        },
    )
}

unsafe fn __reduce__(slf: *mut PyObject, _: *mut PyObject) -> PyReturn {
    let DateTime {
        date: Date { year, month, day },
        time:
            Time {
                hour,
                minute,
                second,
                nanos,
            },
    } = DateTime::extract(slf);
    PyTuple_Pack(
        2,
        State::for_obj(slf).unpickle_naive_datetime,
        steal!(PyTuple_Pack(
            1,
            pack![year, month, day, hour, minute, second, nanos].to_py()?
        )
        .as_result()?),
    )
    .as_result()
}

pub(crate) unsafe fn unpickle(module: *mut PyObject, args: &[*mut PyObject]) -> PyReturn {
    if args.len() != 1 {
        Err(type_error!("Invalid pickle data"))?
    }
    let mut packed = args[0]
        .to_bytes()?
        .ok_or_else(|| type_error!("Invalid pickle data"))?;
    let new = new_unchecked(
        State::for_mod(module).naive_datetime_type,
        DateTime {
            date: date::Date {
                year: unpack_one!(packed, u16),
                month: unpack_one!(packed, u8),
                day: unpack_one!(packed, u8),
            },
            time: time::Time {
                hour: unpack_one!(packed, u8),
                minute: unpack_one!(packed, u8),
                second: unpack_one!(packed, u8),
                nanos: unpack_one!(packed, u32),
            },
        },
    );
    if !packed.is_empty() {
        Err(type_error!("Invalid pickle data"))?
    }
    new
}

unsafe fn from_py_datetime(type_: *mut PyObject, dt: *mut PyObject) -> PyReturn {
    if PyDateTime_Check(dt) == 0 {
        Err(type_error!("argument must be datetime.datetime"))?
    }
    let tzinfo = PyDateTime_DATE_GET_TZINFO(dt);
    if tzinfo != Py_None() {
        Err(value_error!(
            "datetime must be naive, but got tzinfo=%R",
            tzinfo
        ))?
    }
    new_unchecked(
        type_.cast(),
        DateTime {
            date: date::Date {
                year: PyDateTime_GET_YEAR(dt) as u16,
                month: PyDateTime_GET_MONTH(dt) as u8,
                day: PyDateTime_GET_DAY(dt) as u8,
            },
            time: time::Time {
                hour: PyDateTime_DATE_GET_HOUR(dt) as u8,
                minute: PyDateTime_DATE_GET_MINUTE(dt) as u8,
                second: PyDateTime_DATE_GET_SECOND(dt) as u8,
                nanos: PyDateTime_DATE_GET_MICROSECOND(dt) as u32 * 1_000,
            },
        },
    )
}

unsafe fn py_datetime(slf: *mut PyObject, _: *mut PyObject) -> PyReturn {
    let DateTime {
        date: date::Date { year, month, day },
        time:
            time::Time {
                hour,
                minute,
                second,
                nanos,
            },
    } = DateTime::extract(slf);
    let &PyDateTime_CAPI {
        DateTime_FromDateAndTime,
        DateTimeType,
        ..
    } = State::for_type(Py_TYPE(slf)).datetime_api;
    DateTime_FromDateAndTime(
        year.into(),
        month.into(),
        day.into(),
        hour.into(),
        minute.into(),
        second.into(),
        (nanos / 1_000) as c_int,
        Py_None(),
        DateTimeType,
    )
    .as_result()
}

unsafe fn get_date(slf: *mut PyObject, _: *mut PyObject) -> PyReturn {
    date::new_unchecked(State::for_obj(slf).date_type, DateTime::extract(slf).date)
}

unsafe fn get_time(slf: *mut PyObject, _: *mut PyObject) -> PyReturn {
    time::new_unchecked(
        State::for_type(Py_TYPE(slf)).time_type,
        DateTime::extract(slf).time,
    )
}

pub(crate) fn parse_date_and_time(s: &[u8]) -> Option<(date::Date, time::Time)> {
    // This should have already been checked by caller
    debug_assert!(
        s.len() >= 19 && (s[10] == b' ' || s[10] == b'T' || s[10] == b't' || s[10] == b'_')
    );
    Date::parse_all(&s[..10]).zip(Time::parse_all(&s[11..]))
}

unsafe fn from_default_format(cls: *mut PyObject, arg: *mut PyObject) -> PyReturn {
    let s = arg
        .to_utf8()?
        .ok_or_else(|| type_error!("Expected a string"))?;
    if s.len() < 19 || s[10] != b'T' {
        Err(value_error!("Invalid format: %R", arg))
    } else {
        match parse_date_and_time(s) {
            Some((date, time)) => new_unchecked(cls.cast(), DateTime { date, time }),
            None => Err(value_error!("Invalid format: %R", arg)),
        }
    }
}

unsafe fn strptime(cls: *mut PyObject, args: &[*mut PyObject]) -> PyReturn {
    // OPTIMIZE: get this working with vectorcall
    let parsed = PyObject_Call(
        State::for_type(cls.cast()).strptime,
        steal!(PyTuple_Pack(2, args[0], args[1]).as_result()?),
        NULL(),
    )
    .as_result()?;
    defer_decref!(parsed);
    let tzinfo = PyDateTime_DATE_GET_TZINFO(parsed);
    if tzinfo != Py_None() {
        Err(value_error!(
            "datetime must be naive, but got tzinfo=%R",
            tzinfo
        ))?;
    }
    new_unchecked(
        cls.cast(),
        DateTime {
            date: Date {
                year: PyDateTime_GET_YEAR(parsed) as u16,
                month: PyDateTime_GET_MONTH(parsed) as u8,
                day: PyDateTime_GET_DAY(parsed) as u8,
            },
            time: Time {
                hour: PyDateTime_DATE_GET_HOUR(parsed) as u8,
                minute: PyDateTime_DATE_GET_MINUTE(parsed) as u8,
                second: PyDateTime_DATE_GET_SECOND(parsed) as u8,
                nanos: PyDateTime_DATE_GET_MICROSECOND(parsed) as u32 * 1_000,
            },
        },
    )
}

unsafe fn assume_utc(slf: *mut PyObject, _: *mut PyObject) -> PyReturn {
    let DateTime { date, time } = DateTime::extract(slf);
    utc_datetime::new_unchecked(
        State::for_obj(slf).utc_datetime_type,
        utc_datetime::Instant::from_datetime(date, time),
    )
}

static mut METHODS: &[PyMethodDef] = &[
    method!(identity2 named "__copy__", ""),
    method!(identity2 named "__deepcopy__", "", METH_O),
    method!(
        from_py_datetime,
        "Create an instance from a datetime.datetime",
        METH_CLASS | METH_O
    ),
    method!(py_datetime, "Convert to a datetime.datetime"),
    method!(
        get_date named "date",
        "Get the date component"
    ),
    method!(
        get_time named "time",
        "Get the time component"
    ),
    method!(default_format, "Format in the default way"),
    method!(
        from_default_format,
        "Parse from the default format",
        METH_O | METH_CLASS
    ),
    method!(
        default_format named "common_iso8601",
        "Get the common ISO 8601 string representation"
    ),
    method!(
        from_default_format named "from_common_iso8601",
        "Create an instance from the common ISO 8601 string representation",
        METH_O | METH_CLASS
    ),
    method!(__reduce__, ""),
    method_vararg!(strptime, "Parse a string into a NaiveDateTime", METH_CLASS),
    method_kwargs!(
        replace,
        "Return a new instance with the specified fields replaced"
    ),
    method!(assume_utc, "Convert to an equivalent UTCDateTime"),
    PyMethodDef::zeroed(),
];

unsafe fn get_year(slf: *mut PyObject) -> PyReturn {
    DateTime::extract(slf).date.year.to_py()
}

unsafe fn get_month(slf: *mut PyObject) -> PyReturn {
    DateTime::extract(slf).date.month.to_py()
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
    DateTime::extract(slf).time.nanos.to_py()
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

pub(crate) static mut SPEC: PyType_Spec = PyType_Spec {
    name: c_str!("whenever.NaiveDateTime"),
    basicsize: mem::size_of::<PyNaiveDateTime>() as _,
    itemsize: 0,
    flags: Py_TPFLAGS_DEFAULT as _,
    slots: unsafe { SLOTS as *const [_] as *mut _ },
};

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn test_parse_valid() {
        assert_eq!(
            parse_date_and_time(b"2023-03-02 02:09:09"),
            Some((
                date::Date {
                    year: 2023,
                    month: 3,
                    day: 2,
                },
                time::Time {
                    hour: 2,
                    minute: 9,
                    second: 9,
                    nanos: 0,
                },
            ))
        );
        assert_eq!(
            parse_date_and_time(b"2023-03-02 02:09:09.123456789"),
            Some((
                date::Date {
                    year: 2023,
                    month: 3,
                    day: 2,
                },
                time::Time {
                    hour: 2,
                    minute: 9,
                    second: 9,
                    nanos: 123_456_789,
                },
            ))
        );
    }

    #[test]
    fn test_parse_invalid() {
        // dot but no fractional digits
        assert_eq!(parse_date_and_time(b"2023-03-02 02:09:09."), None);
        // too many fractions
        assert_eq!(parse_date_and_time(b"2023-03-02 02:09:09.1234567890"), None);
        // invalid minute
        assert_eq!(parse_date_and_time(b"2023-03-02 02:69:09.123456789"), None);
        // invalid date
        assert_eq!(parse_date_and_time(b"2023-02-29 02:29:09.123456789"), None);
    }
}
