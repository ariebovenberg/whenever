use core::ffi::{c_char, c_int, c_long, c_void};
use core::{mem, ptr, ptr::null_mut as NULL};
use pyo3_ffi::*;

use crate::common::{
    c_str, classmethod, getter, identity, method, newref, py_bool, py_str, py_try, pyint_as_long,
    pystr_to_utf8, raise, HASH_MASK,
};
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
    dt: DateTime,
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

    pub(crate) fn extract(obj: *mut PyObject) -> Self {
        unsafe { (*(obj.cast::<PyNaiveDateTime>())).dt }
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
        return NULL();
    }

    new_unchecked(
        subtype,
        DateTime {
            date: match Date::from_longs(year, month, day) {
                Some(date) => date,
                None => raise!(PyExc_ValueError, "Invalid date"),
            },
            time: match Time::from_longs(hour, minute, second, nanos) {
                Some(time) => time,
                None => raise!(PyExc_ValueError, "Invalid time"),
            },
        },
    )
}

pub(crate) unsafe fn new_unchecked(type_: *mut PyTypeObject, dt: DateTime) -> *mut PyObject {
    let f: allocfunc = (*type_).tp_alloc.expect("tp_alloc is not set");
    let slf = py_try!(f(type_, 0).cast::<PyNaiveDateTime>());
    ptr::addr_of_mut!((*slf).dt).write(dt);
    slf.cast()
}

unsafe extern "C" fn dealloc(slf: *mut PyObject) {
    let tp_free = PyType_GetSlot(Py_TYPE(slf), Py_tp_free);
    debug_assert_ne!(tp_free, NULL());
    let f: freefunc = std::mem::transmute(tp_free);
    f(slf.cast());
}

unsafe extern "C" fn __repr__(slf: *mut PyObject) -> *mut PyObject {
    let DateTime { date, time } = DateTime::extract(slf);
    py_str(&format!("NaiveDateTime({} {})", date, time))
}

unsafe extern "C" fn __str__(slf: *mut PyObject) -> *mut PyObject {
    py_str(&DateTime::extract(slf).default_fmt())
}

unsafe extern "C" fn default_format(slf: *mut PyObject, _: *mut PyObject) -> *mut PyObject {
    __str__(slf)
}

unsafe extern "C" fn __richcmp__(
    a_obj: *mut PyObject,
    b_obj: *mut PyObject,
    op: c_int,
) -> *mut PyObject {
    newref(if Py_TYPE(b_obj) == Py_TYPE(a_obj) {
        let a = DateTime::extract(a_obj);
        let b = DateTime::extract(b_obj);
        py_bool(match op {
            pyo3_ffi::Py_LT => a < b,
            pyo3_ffi::Py_LE => a <= b,
            pyo3_ffi::Py_EQ => a == b,
            pyo3_ffi::Py_NE => a != b,
            pyo3_ffi::Py_GT => a > b,
            pyo3_ffi::Py_GE => a >= b,
            _ => unreachable!(),
        })
    } else {
        Py_NotImplemented()
    })
}

unsafe extern "C" fn __hash__(slf: *mut PyObject) -> Py_hash_t {
    let DateTime { date, time } = DateTime::extract(slf);
    date.hash() as Py_hash_t ^ time.pyhash() & HASH_MASK
}

unsafe extern "C" fn __add__(obj_a: *mut PyObject, obj_b: *mut PyObject) -> *mut PyObject {
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
            None => raise!(PyExc_ValueError, "Resulting date out of range"),
        }
    } else if type_b == date_delta_type {
        match _add_datedelta(a, DateDelta::extract(obj_b)) {
            Some(dt) => new_unchecked(type_a, dt),
            None => raise!(PyExc_ValueError, "Resulting date out of range"),
        }
    } else {
        newref(Py_NotImplemented())
    }
}

unsafe extern "C" fn __sub__(obj_a: *mut PyObject, obj_b: *mut PyObject) -> *mut PyObject {
    let slf = DateTime::extract(obj_a);
    if Py_TYPE(obj_b) == State::for_type(Py_TYPE(obj_a)).date_delta_type {
        match _add_datedelta(slf, -DateDelta::extract(obj_b)) {
            Some(dt) => new_unchecked(Py_TYPE(obj_a), dt),
            None => raise!(PyExc_ValueError, "Resulting date out of range"),
        }
    } else {
        newref(Py_NotImplemented())
    }
}

fn _add_datedelta(dt: DateTime, delta: DateDelta) -> Option<DateTime> {
    dt.date
        .shift(0, delta.months, delta.days)
        .map(|date| DateTime { date, ..dt })
}

static mut SLOTS: &[PyType_Slot] = &[
    PyType_Slot {
        slot: Py_tp_new,
        pfunc: __new__ as *mut c_void,
    },
    PyType_Slot {
        slot: Py_tp_doc,
        pfunc: "A calendar date type\0".as_ptr() as *mut c_void,
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
        slot: Py_nb_add,
        pfunc: __add__ as *mut c_void,
    },
    PyType_Slot {
        slot: Py_nb_subtract,
        pfunc: __sub__ as *mut c_void,
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
    if kwnames.is_null() {
        newref(slf)
    } else {
        let module = State::for_type(type_);
        let dt = DateTime::extract(slf);
        let mut year = dt.date.year as c_long;
        let mut month = dt.date.month as c_long;
        let mut day = dt.date.day as c_long;
        let mut hour = dt.time.hour as c_long;
        let mut minute = dt.time.minute as c_long;
        let mut second = dt.time.second as c_long;
        let mut nanos = dt.time.nanos as c_long;
        for i in 0..=Py_SIZE(kwnames).saturating_sub(1) {
            let name = PyTuple_GET_ITEM(kwnames, i);
            if name == module.str_year {
                year = pyint_as_long!(*args.offset(i));
            } else if name == module.str_month {
                month = pyint_as_long!(*args.offset(i));
            } else if name == module.str_day {
                day = pyint_as_long!(*args.offset(i));
            } else if name == module.str_hour {
                hour = pyint_as_long!(*args.offset(i));
            } else if name == module.str_minute {
                minute = pyint_as_long!(*args.offset(i));
            } else if name == module.str_second {
                second = pyint_as_long!(*args.offset(i));
            } else if name == module.str_nanosecond {
                nanos = pyint_as_long!(*args.offset(i));
            } else {
                raise!(
                    PyExc_TypeError,
                    "replace() got an unexpected keyword argument %R",
                    name
                );
            }
        }
        new_unchecked(
            type_,
            DateTime {
                date: match Date::from_longs(year, month, day) {
                    Some(date) => date,
                    None => raise!(PyExc_ValueError, "Invalid date"),
                },
                time: match Time::from_longs(hour, minute, second, nanos) {
                    Some(time) => time,
                    None => {
                        raise!(PyExc_ValueError, "Invalid time");
                    }
                },
            },
        )
    }
}

unsafe extern "C" fn __reduce__(slf: *mut PyObject, _: *mut PyObject) -> *mut PyObject {
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
        py_try!(PyTuple_Pack(
            7,
            PyLong_FromLong(year.into()),
            PyLong_FromLong(month.into()),
            PyLong_FromLong(day.into()),
            PyLong_FromLong(hour.into()),
            PyLong_FromLong(minute.into()),
            PyLong_FromLong(second.into()),
            PyLong_FromLong(nanos as c_long),
        )),
    )
}

pub(crate) unsafe extern "C" fn unpickle(
    module: *mut PyObject,
    args: *mut *mut PyObject,
    nargs: Py_ssize_t,
) -> *mut PyObject {
    if PyVectorcall_NARGS(nargs as usize) != 7 {
        raise!(PyExc_TypeError, "Invalid pickle data");
    }
    new_unchecked(
        State::for_mod(module).naive_datetime_type,
        DateTime {
            date: date::Date {
                year: pyint_as_long!(*args.offset(0)) as u16,
                month: pyint_as_long!(*args.offset(1)) as u8,
                day: pyint_as_long!(*args.offset(2)) as u8,
            },
            time: time::Time {
                hour: pyint_as_long!(*args.offset(3)) as u8,
                minute: pyint_as_long!(*args.offset(4)) as u8,
                second: pyint_as_long!(*args.offset(5)) as u8,
                nanos: pyint_as_long!(*args.offset(6)) as u32,
            },
        },
    )
}

unsafe extern "C" fn from_py_datetime(type_: *mut PyObject, dt: *mut PyObject) -> *mut PyObject {
    if PyDateTime_Check(dt) == 0 {
        raise!(PyExc_TypeError, "argument must be datetime.datetime");
    }
    let tzinfo = PyDateTime_DATE_GET_TZINFO(dt);
    if tzinfo != Py_None() {
        raise!(
            PyExc_ValueError,
            "datetime must be naive, but got tzinfo=%R",
            tzinfo
        );
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

unsafe extern "C" fn py_datetime(slf: *mut PyObject, _: *mut PyObject) -> *mut PyObject {
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
    py_try!(DateTime_FromDateAndTime(
        year.into(),
        month.into(),
        day.into(),
        hour.into(),
        minute.into(),
        second.into(),
        (nanos / 1_000) as c_int,
        Py_None(),
        DateTimeType,
    ))
}

unsafe extern "C" fn get_date(slf: *mut PyObject, _: *mut PyObject) -> *mut PyObject {
    date::new_unchecked(State::for_obj(slf).date_type, DateTime::extract(slf).date)
}

unsafe extern "C" fn get_time(slf: *mut PyObject, _: *mut PyObject) -> *mut PyObject {
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

unsafe extern "C" fn from_default_format(cls: *mut PyObject, arg: *mut PyObject) -> *mut PyObject {
    let s = pystr_to_utf8!(arg, "Expected a string");
    if s.len() < 19 || s[10] != b'T' {
        raise!(PyExc_ValueError, "Invalid format: %R", arg);
    }
    match parse_date_and_time(s) {
        Some((date, time)) => new_unchecked(cls.cast(), DateTime { date, time }),
        None => raise!(PyExc_ValueError, "Invalid format: %R", arg),
    }
}

unsafe extern "C" fn common_iso8601(slf: *mut PyObject, _: *mut PyObject) -> *mut PyObject {
    let DateTime { date, time } = DateTime::extract(slf);
    py_str(&format!("{}T{}", date, time))
}

unsafe extern "C" fn from_common_iso8601(cls: *mut PyObject, obj: *mut PyObject) -> *mut PyObject {
    let s = pystr_to_utf8!(obj, "Expected a string");
    if s.len() < 19 || s[10] != b'T' {
        raise!(PyExc_ValueError, "Invalid common ISO 8601 format: %R", obj);
    }
    match parse_date_and_time(s) {
        Some((date, time)) => new_unchecked(cls.cast(), DateTime { date, time }),
        None => raise!(PyExc_ValueError, "Invalid common ISO 8601 format: %R", obj),
    }
}

unsafe extern "C" fn strptime(cls: *mut PyObject, args: *mut PyObject) -> *mut PyObject {
    // FUTURE: get this working with vectorcall
    let parsed = py_try!(PyObject_Call(
        State::for_type(cls.cast()).strptime,
        args,
        NULL()
    ));
    let tzinfo = PyDateTime_DATE_GET_TZINFO(parsed);
    if tzinfo != Py_None() {
        raise!(
            PyExc_ValueError,
            "datetime must be naive, but got tzinfo=%R",
            tzinfo
        );
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

unsafe extern "C" fn assume_utc(slf: *mut PyObject, _: *mut PyObject) -> *mut PyObject {
    let DateTime { date, time } = DateTime::extract(slf);
    utc_datetime::new_unchecked(
        State::for_obj(slf).utc_datetime_type,
        utc_datetime::Instant::from_datetime(date, time),
    )
}

static mut METHODS: &[PyMethodDef] = &[
    method!(
        identity named "__copy__",
        "Return a shallow copy of the instance"
    ),
    method!(
        identity named "__deepcopy__",
        "Return a deep copy of the instance",
        METH_O
    ),
    classmethod!(
        from_py_datetime,
        "Create an instance from a datetime.datetime",
        METH_O
    ),
    method!(py_datetime, "Convert to a datetime.datetime", METH_NOARGS),
    method!(
        get_date named "date",
        "Get the date component",
        METH_NOARGS
    ),
    method!(
        get_time named "time",
        "Get the time component",
        METH_NOARGS
    ),
    method!(default_format, ""),
    classmethod!(from_default_format, "", METH_O),
    method!(
        common_iso8601,
        "Get the common ISO 8601 string representation"
    ),
    classmethod!(
        from_common_iso8601,
        "Create an instance from the common ISO 8601 string representation",
        METH_O
    ),
    method!(__reduce__, ""),
    PyMethodDef {
        ml_name: c_str!("strptime"),
        ml_meth: PyMethodDefPointer {
            PyCFunction: strptime,
        },
        ml_flags: METH_CLASS | METH_VARARGS,
        ml_doc: c_str!("Parse a string into a NaiveDateTime"),
    },
    PyMethodDef {
        ml_name: c_str!("replace"),
        ml_meth: PyMethodDefPointer { PyCMethod: replace },
        ml_flags: METH_METHOD | METH_FASTCALL | METH_KEYWORDS,
        ml_doc: c_str!("Return a new instance with the specified fields replaced"),
    },
    method!(
        assume_utc,
        "Convert to an equivalent UTCDateTime",
        METH_NOARGS
    ),
    PyMethodDef::zeroed(),
];

unsafe extern "C" fn get_year(slf: *mut PyObject, _: *mut c_void) -> *mut PyObject {
    PyLong_FromLong(DateTime::extract(slf).date.year.into())
}

unsafe extern "C" fn get_month(slf: *mut PyObject, _: *mut c_void) -> *mut PyObject {
    PyLong_FromLong(DateTime::extract(slf).date.month.into())
}

unsafe extern "C" fn get_day(slf: *mut PyObject, _: *mut c_void) -> *mut PyObject {
    PyLong_FromLong(DateTime::extract(slf).date.day.into())
}

unsafe extern "C" fn get_hour(slf: *mut PyObject, _: *mut c_void) -> *mut PyObject {
    PyLong_FromLong(DateTime::extract(slf).time.hour.into())
}

unsafe extern "C" fn get_minute(slf: *mut PyObject, _: *mut c_void) -> *mut PyObject {
    PyLong_FromLong(DateTime::extract(slf).time.minute.into())
}

unsafe extern "C" fn get_second(slf: *mut PyObject, _: *mut c_void) -> *mut PyObject {
    PyLong_FromLong(DateTime::extract(slf).time.second.into())
}

unsafe extern "C" fn get_nanos(slf: *mut PyObject, _: *mut c_void) -> *mut PyObject {
    PyLong_FromLong(DateTime::extract(slf).time.nanos as c_long)
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
