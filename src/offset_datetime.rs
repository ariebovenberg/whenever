use core::ffi::{c_char, c_int, c_long, c_void};
use core::{mem, ptr, ptr::null_mut as NULL};
use pyo3_ffi::*;
use std::fmt::{self, Display, Formatter};
use std::time::SystemTime;

use crate::common::*;
use crate::{
    date::{self, Date},
    local_datetime,
    naive_datetime::{self, DateTime},
    time::{self, Time},
    time_delta::{self, TimeDelta},
    utc_datetime::{self, Instant},
    zoned_datetime::{self, ZonedDateTime},
    State,
};

#[derive(Debug, Eq, PartialEq, Ord, PartialOrd, Copy, Clone)]
pub(crate) struct OffsetDateTime {
    pub(crate) date: Date,
    pub(crate) time: Time,
    pub(crate) offset_secs: i32, // the offset is already priced into the date and time
}

#[repr(C)]
pub(crate) struct PyOffsetDateTime {
    _ob_base: PyObject,
    dt: OffsetDateTime,
}

impl OffsetDateTime {
    pub(crate) unsafe fn extract(obj: *mut PyObject) -> Self {
        (*obj.cast::<PyOffsetDateTime>()).dt
    }

    pub(crate) const fn to_instant(&self) -> Instant {
        Instant::from_datetime(self.date, self.time).shift_secs_unchecked(-self.offset_secs as i64)
    }

    pub(crate) const fn small_naive_shift(&self, secs: i32) -> Self {
        // TODO: unify with similar methods
        debug_assert!(secs.abs() < 86400 * 2);
        let Self { date, time, .. } = self;
        let day_seconds = time.seconds() + secs;
        let (date, time) = match day_seconds.div_euclid(86400) {
            0 => (*date, time.set_seconds(day_seconds as u32)),
            1 => (
                date.increment(),
                time.set_seconds((day_seconds - 86400) as u32),
            ),
            -1 => (
                date.decrement(),
                time.set_seconds((day_seconds + 86400) as u32),
            ),
            // more than 1 day difference is unlikely--but possible
            2 => (
                date.increment().increment(),
                time.set_seconds((day_seconds - 86400 * 2) as u32),
            ),
            -2 => (
                date.decrement().decrement(),
                time.set_seconds((day_seconds + 86400 * 2) as u32),
            ),
            _ => unreachable!(),
        };
        Self {
            date,
            time,
            ..*self
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
        let time = Time::parse_partial(s)?;
        let offset_secs = parse_hms_offset(s)?;
        Some(Self {
            date,
            time,
            offset_secs,
        })
    }

    pub(crate) unsafe fn to_py(
        &self,
        &PyDateTime_CAPI {
            DateTime_FromDateAndTime,
            DateTimeType,
            TimeZone_FromTimeZone,
            Delta_FromDelta,
            DeltaType,
            ..
        }: &PyDateTime_CAPI,
    ) -> *mut PyObject {
        let &OffsetDateTime {
            date: Date { year, month, day },
            time:
                Time {
                    hour,
                    minute,
                    second,
                    nanos,
                },
            offset_secs, // TODO: general checks <24 hours
            ..
        } = self;
        let tz = TimeZone_FromTimeZone(Delta_FromDelta(0, offset_secs, 0, 0, DeltaType), NULL());
        let dt = DateTime_FromDateAndTime(
            year.into(),
            month.into(),
            day.into(),
            hour.into(),
            minute.into(),
            second.into(),
            (nanos / 1_000) as _,
            tz,
            DateTimeType,
        );
        Py_DECREF(tz);
        dt
    }

    pub(crate) unsafe fn from_py(dt: *mut PyObject, state: &State) -> Option<Self> {
        let tzinfo = PyDateTime_DATE_GET_TZINFO(dt);
        if PyObject_IsInstance(tzinfo, state.timezone_type.cast()) == 0 {
            return None;
        }
        // TODO: this can lead to values that can't be converted to UTC!
        Some(OffsetDateTime {
            date: Date {
                year: PyDateTime_GET_YEAR(dt) as u16,
                month: PyDateTime_GET_MONTH(dt) as u8,
                day: PyDateTime_GET_DAY(dt) as u8,
            },
            time: Time {
                hour: PyDateTime_DATE_GET_HOUR(dt) as u8,
                minute: PyDateTime_DATE_GET_MINUTE(dt) as u8,
                second: PyDateTime_DATE_GET_SECOND(dt) as u8,
                nanos: PyDateTime_DATE_GET_MICROSECOND(dt) as u32 * 1_000,
            },
            offset_secs: offset_from_py_dt(dt),
        })
    }
}

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

unsafe extern "C" fn __new__(
    cls: *mut PyTypeObject,
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
    let mut offset: *mut PyObject = NULL();

    // FUTURE: parse them manually, which is more efficient
    if PyArg_ParseTupleAndKeywords(
        args,
        kwargs,
        c_str!("lll|lll$lO:OffsetDateTime"),
        vec![
            c_str!("year") as *mut c_char,
            c_str!("month") as *mut c_char,
            c_str!("day") as *mut c_char,
            c_str!("hour") as *mut c_char,
            c_str!("minute") as *mut c_char,
            c_str!("second") as *mut c_char,
            c_str!("nanosecond") as *mut c_char,
            c_str!("offset") as *mut c_char,
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
        return NULL();
    }

    let offset_secs = to_py!(extract_offset(offset, State::for_type(cls).time_delta_type));

    // TODO: Stricter date validation due to offset?
    let date = unwrap_or_raise!(
        Date::from_longs(year, month, day),
        PyExc_ValueError,
        "Invalid date"
    );
    let time = unwrap_or_raise!(
        Time::from_longs(hour, minute, second, nanos),
        PyExc_ValueError,
        "Invalid time"
    );
    new_unchecked(
        cls,
        OffsetDateTime {
            date,
            time,
            offset_secs,
        },
    )
}

pub(crate) unsafe fn extract_offset(
    obj: *mut PyObject,
    tdelta_cls: *mut PyTypeObject,
) -> PyResult<i32> {
    if obj.is_null() {
        PyErr_SetString(PyExc_TypeError, c_str!("offset argument is required"));
    } else if PyLong_Check(obj) != 0 {
        let given_int = PyLong_AsLong(obj);
        if given_int.abs() >= 24 {
            PyErr_SetString(
                PyExc_ValueError,
                c_str!("offset must be between -24 and 24 hours"),
            );
        } else if given_int != -1 || PyErr_Occurred().is_null() {
            return Ok((given_int * 3600) as _);
        }
    } else if Py_TYPE(obj) == tdelta_cls {
        let td = TimeDelta::extract(obj);
        if td.subsec_nanos() != 0 {
            PyErr_SetString(
                PyExc_ValueError,
                c_str!("offset must be a whole number of seconds"),
            );
        } else if td.whole_seconds().abs() >= 24 * 3600 {
            PyErr_SetString(
                PyExc_ValueError,
                c_str!("offset must be between -24 and 24 hours"),
            );
        } else {
            return Ok(td.whole_seconds() as _);
        }
    } else {
        PyErr_Format(
            PyExc_TypeError,
            c_str!("offset must be an integer or TimeDelta instance, got %R"),
            obj,
        );
    };
    Err(PyErrOccurred())
}

pub(crate) unsafe fn new_unchecked(type_: *mut PyTypeObject, dt: OffsetDateTime) -> *mut PyObject {
    let f: allocfunc = (*type_).tp_alloc.expect("tp_alloc is not set");
    let slf = py_try!(f(type_, 0).cast::<PyOffsetDateTime>());
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
    let OffsetDateTime {
        date,
        time,
        offset_secs,
    } = OffsetDateTime::extract(slf);
    py_str(&format!(
        "OffsetDateTime({} {}{})",
        date,
        time,
        offset_fmt(offset_secs)
    ))
}

unsafe extern "C" fn __str__(slf: *mut PyObject) -> *mut PyObject {
    py_str(&format!("{}", OffsetDateTime::extract(slf)))
}

unsafe extern "C" fn __richcmp__(
    a_obj: *mut PyObject,
    b_obj: *mut PyObject,
    op: c_int,
) -> *mut PyObject {
    let type_a = Py_TYPE(a_obj);
    let type_b = Py_TYPE(b_obj);
    let inst_a = OffsetDateTime::extract(a_obj).to_instant();
    let inst_b = if type_b == type_a {
        OffsetDateTime::extract(b_obj).to_instant()
    } else if type_b == State::for_type(type_a).utc_datetime_type {
        Instant::extract(b_obj)
    } else if type_b == State::for_type(type_a).zoned_datetime_type {
        ZonedDateTime::extract(b_obj).to_instant()
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

pub(crate) unsafe extern "C" fn __hash__(slf: *mut PyObject) -> Py_hash_t {
    OffsetDateTime::extract(slf).to_instant().pyhash()
}

unsafe extern "C" fn __sub__(obj_a: *mut PyObject, obj_b: *mut PyObject) -> *mut PyObject {
    let type_a = Py_TYPE(obj_a);
    let type_b = Py_TYPE(obj_b);

    // Easy case: OffsetDT - OffsetDT
    let (inst_a, inst_b) = if type_a == type_b {
        (
            OffsetDateTime::extract(obj_a).to_instant(),
            OffsetDateTime::extract(obj_b).to_instant(),
        )
    // Other cases are more difficult, as they can be triggered
    // by reflexive operations with arbitrary types.
    // We need to eliminate them carefully.
    } else {
        let mod_a = PyType_GetModule(type_a);
        let mod_b = PyType_GetModule(type_b);
        if mod_a == mod_b {
            // at this point we know that `a` is a `OffsetDT`
            let inst_a = OffsetDateTime::extract(obj_a).to_instant();
            let inst_b = if type_b == State::for_mod(mod_a).utc_datetime_type {
                Instant::extract(obj_b)
            } else if type_b == State::for_mod(mod_a).zoned_datetime_type {
                ZonedDateTime::extract(obj_b).to_instant()
            } else if type_b == State::for_mod(mod_a).local_datetime_type {
                OffsetDateTime::extract(obj_b).to_instant()
            } else {
                return newref(Py_NotImplemented());
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

static mut SLOTS: &[PyType_Slot] = &[
    PyType_Slot {
        slot: Py_tp_new,
        pfunc: __new__ as *mut c_void,
    },
    PyType_Slot {
        slot: Py_tp_doc,
        pfunc: "A datetime type with IANA tz ID\0".as_ptr() as *mut c_void,
    },
    PyType_Slot {
        slot: Py_tp_str,
        pfunc: __str__ as *mut c_void,
    },
    PyType_Slot {
        slot: Py_tp_repr,
        pfunc: __repr__ as *mut c_void,
    },
    PyType_Slot {
        slot: Py_tp_richcompare,
        pfunc: __richcmp__ as *mut c_void,
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

unsafe extern "C" fn exact_eq(obj_a: *mut PyObject, obj_b: *mut PyObject) -> *mut PyObject {
    if Py_TYPE(obj_a) == Py_TYPE(obj_b) {
        newref(py_bool(
            OffsetDateTime::extract(obj_a) == OffsetDateTime::extract(obj_b),
        ))
    } else {
        raise!(
            PyExc_TypeError,
            "Argument must be OffsetDateTime, got %R",
            obj_b
        )
    }
}

unsafe extern "C" fn in_tz(slf: *mut PyObject, tz: *mut PyObject) -> *mut PyObject {
    let type_ = Py_TYPE(slf);
    let &State {
        zoneinfo_type,
        datetime_api: py_api,
        zoned_datetime_type,
        ..
    } = State::for_type(type_);
    let new_zoneinfo = newref(py_try!(PyObject_CallOneArg(zoneinfo_type.cast(), tz)));
    let odt = OffsetDateTime::extract(slf);
    let OffsetDateTime { date, time, .. } = odt.small_naive_shift(-odt.offset_secs);
    zoned_datetime::new_unchecked(
        zoned_datetime_type,
        ZonedDateTime::from_utc(py_api, date, time, new_zoneinfo),
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
        State::for_mod(module).offset_datetime_type,
        OffsetDateTime {
            date: Date {
                year: unpack_one!(packed, u16),
                month: unpack_one!(packed, u8),
                day: unpack_one!(packed, u8),
            },
            time: Time {
                hour: unpack_one!(packed, u8),
                minute: unpack_one!(packed, u8),
                second: unpack_one!(packed, u8),
                nanos: unpack_one!(packed, u32),
            },
            offset_secs: unpack_one!(packed, i32),
        },
    );
    if packed.len() != 0 {
        raise!(PyExc_ValueError, "Invalid pickle data");
    }
    new
}

unsafe extern "C" fn py_datetime(slf: *mut PyObject, _: *mut PyObject) -> *mut PyObject {
    OffsetDateTime::extract(slf).to_py(State::for_obj(slf).datetime_api)
}

unsafe extern "C" fn in_utc(slf: *mut PyObject, _: *mut PyObject) -> *mut PyObject {
    utc_datetime::new_unchecked(
        State::for_obj(slf).utc_datetime_type,
        OffsetDateTime::extract(slf).to_instant(),
    )
}

unsafe extern "C" fn date(slf: *mut PyObject, _: *mut PyObject) -> *mut PyObject {
    date::new_unchecked(
        State::for_obj(slf).date_type,
        OffsetDateTime::extract(slf).date,
    )
}

unsafe extern "C" fn time(slf: *mut PyObject, _: *mut PyObject) -> *mut PyObject {
    time::new_unchecked(
        State::for_obj(slf).time_type,
        OffsetDateTime::extract(slf).time,
    )
}

unsafe extern "C" fn with_date(slf: *mut PyObject, arg: *mut PyObject) -> *mut PyObject {
    let cls = Py_TYPE(slf);
    let OffsetDateTime {
        time, offset_secs, ..
    } = OffsetDateTime::extract(slf);
    if Py_TYPE(arg) == State::for_type(cls).date_type {
        new_unchecked(
            cls,
            OffsetDateTime {
                date: Date::extract(arg),
                time,
                offset_secs,
            },
        )
    } else {
        raise!(PyExc_TypeError, "date must be a Date instance");
    }
}

unsafe extern "C" fn with_time(slf: *mut PyObject, arg: *mut PyObject) -> *mut PyObject {
    let cls = slf.cast();

    let OffsetDateTime {
        date, offset_secs, ..
    } = OffsetDateTime::extract(slf);
    if Py_TYPE(arg) == State::for_type(cls).time_type {
        new_unchecked(
            cls,
            OffsetDateTime {
                date,
                time: Time::extract(arg),
                offset_secs,
            },
        )
    } else {
        raise!(PyExc_TypeError, "time must be a Time instance");
    }
}

unsafe extern "C" fn default_format(slf: *mut PyObject, _: *mut PyObject) -> *mut PyObject {
    __str__(slf)
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
        str_offset,
        time_delta_type,
        ..
    } = State::for_type(type_);
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
    let mut nanos = time.nanos.into();
    let mut offset_secs = offset_secs.into();

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
            } else if name == str_offset {
                offset_secs = to_py!(extract_offset(value, time_delta_type));
            } else {
                raise!(
                    PyExc_TypeError,
                    "replace() got an unexpected keyword argument %R",
                    name
                );
            }
        }
        let date = unwrap_or_raise!(
            Date::from_longs(year, month, day),
            PyExc_ValueError,
            "Invalid date"
        );
        let time = unwrap_or_raise!(
            Time::from_longs(hour, minute, second, nanos),
            PyExc_ValueError,
            "Invalid time"
        );
        new_unchecked(
            type_,
            OffsetDateTime {
                date,
                time,
                offset_secs,
            },
        )
    }
}

unsafe extern "C" fn now(cls: *mut PyObject, offset: *mut PyObject) -> *mut PyObject {
    let nanos = match SystemTime::now().duration_since(SystemTime::UNIX_EPOCH) {
        Ok(dur) => dur.as_nanos(),
        _ => raise!(PyExc_OSError, "SystemTime before UNIX EPOCH"),
    };
    let offset_secs = to_py!(extract_offset(
        offset,
        State::for_type(cls.cast()).time_delta_type
    ));
    let DateTime { date, time } = unwrap_or_raise!(
        // Technically conversion to i128 can overflow, but only if system
        // time is set to a very very very distant future
        Instant::from_timestamp_nanos(nanos as i128),
        PyExc_ValueError,
        "SystemTime out of range"
    )
    .shift_secs_unchecked(offset_secs.into())
    .to_datetime();

    new_unchecked(
        cls.cast(),
        OffsetDateTime {
            date,
            time,
            offset_secs,
        },
    )
}

unsafe extern "C" fn from_py_datetime(cls: *mut PyObject, dt: *mut PyObject) -> *mut PyObject {
    if PyDateTime_Check(dt) == 0 {
        raise!(
            PyExc_TypeError,
            "Argument must be a datetime.datetime instance"
        );
    }
    new_unchecked(
        cls.cast(),
        unwrap_or_raise!(
            OffsetDateTime::from_py(dt, State::for_type(cls.cast())),
            PyExc_ValueError,
            "tzinfo must be a datetime.timezone instance, got %R",
            PyObject_GetAttrString(dt, c_str!("tzinfo"))
        ),
    )
}

pub(crate) unsafe extern "C" fn naive(slf: *mut PyObject, _: *mut PyObject) -> *mut PyObject {
    let OffsetDateTime { date, time, .. } = OffsetDateTime::extract(slf);
    naive_datetime::new_unchecked(
        State::for_obj(slf).naive_datetime_type,
        DateTime { date, time },
    )
}

pub(crate) unsafe extern "C" fn timestamp(slf: *mut PyObject, _: *mut PyObject) -> *mut PyObject {
    PyLong_FromLongLong(OffsetDateTime::extract(slf).to_instant().timestamp())
}

pub(crate) unsafe extern "C" fn timestamp_millis(
    slf: *mut PyObject,
    _: *mut PyObject,
) -> *mut PyObject {
    PyLong_FromLongLong(OffsetDateTime::extract(slf).to_instant().timestamp_millis())
}

pub(crate) unsafe extern "C" fn timestamp_nanos(
    slf: *mut PyObject,
    _: *mut PyObject,
) -> *mut PyObject {
    py_int128(OffsetDateTime::extract(slf).to_instant().timestamp_nanos())
}

unsafe extern "C" fn __reduce__(slf: *mut PyObject, _: *mut PyObject) -> *mut PyObject {
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
    PyTuple_Pack(
        2,
        State::for_obj(slf).unpickle_offset_datetime,
        py_try!(PyTuple_Pack(
            1,
            py_bytes(&pack![
                year,
                month,
                day,
                hour,
                minute,
                second,
                nanos,
                offset_secs
            ]),
        )),
    )
}

// checks the args comply with (ts: ?, /, *, offset: ?)
unsafe fn check_from_timestamp_args_return_offset(
    args: *const *mut PyObject,
    nargs: Py_ssize_t,
    kwnames: *mut PyObject,
    &State {
        str_offset,
        time_delta_type,
        ..
    }: &State,
) -> PyResult<i32> {
    if PyVectorcall_NARGS(nargs as usize) != 1 {
        PyErr_Format(
            PyExc_TypeError,
            c_str!("from_timestamp() takes 1 positional argument but %lld were given"),
            nargs,
        );
    };
    let nkwargs = if kwnames.is_null() {
        0
    } else {
        PyTuple_GET_SIZE(kwnames)
    };
    if nkwargs != 1 {
        PyErr_Format(
            PyExc_TypeError,
            c_str!("from_timestamp() expected 2 arguments, got %lld"),
            nargs + nkwargs,
        );
    } else if PyTuple_GET_ITEM(kwnames, 0) == str_offset {
        return extract_offset(*args.offset(1), time_delta_type);
    } else {
        PyErr_Format(
            PyExc_TypeError,
            c_str!("from_timestamp() got an unexpected keyword argument %R"),
            PyTuple_GET_ITEM(kwnames, 0),
        );
    }
    Err(PyErrOccurred())
}

unsafe extern "C" fn from_timestamp(
    _: *mut PyObject,
    cls: *mut PyTypeObject,
    args: *const *mut PyObject,
    nargs: Py_ssize_t,
    kwnames: *mut PyObject,
) -> *mut PyObject {
    let state = State::for_type(cls);
    let offset_secs = to_py!(check_from_timestamp_args_return_offset(
        args, nargs, kwnames, state
    ));
    let DateTime { date, time } = unwrap_or_raise!(
        Instant::from_timestamp(pyint_as_i64!(*args)),
        PyExc_ValueError,
        "timestamp is out of range"
    )
    .shift_secs_unchecked(offset_secs as i64)
    .to_datetime();
    new_unchecked(
        cls,
        OffsetDateTime {
            date,
            time,
            offset_secs,
        },
    )
}

unsafe extern "C" fn from_timestamp_millis(
    _: *mut PyObject,
    cls: *mut PyTypeObject,
    args: *const *mut PyObject,
    nargs: Py_ssize_t,
    kwnames: *mut PyObject,
) -> *mut PyObject {
    let state = State::for_type(cls);
    let offset_secs = to_py!(check_from_timestamp_args_return_offset(
        args, nargs, kwnames, state
    ));
    let DateTime { date, time } = unwrap_or_raise!(
        Instant::from_timestamp_millis(pyint_as_i64!(*args)),
        PyExc_ValueError,
        "timestamp is out of range"
    )
    .shift_secs_unchecked(offset_secs as i64)
    .to_datetime();
    new_unchecked(
        cls,
        OffsetDateTime {
            date,
            time,
            offset_secs,
        },
    )
}

unsafe extern "C" fn from_timestamp_nanos(
    _: *mut PyObject,
    cls: *mut PyTypeObject,
    args: *const *mut PyObject,
    nargs: Py_ssize_t,
    kwnames: *mut PyObject,
) -> *mut PyObject {
    let state = State::for_type(cls);
    let offset_secs = to_py!(check_from_timestamp_args_return_offset(
        args, nargs, kwnames, state
    ));
    let DateTime { date, time } = unwrap_or_raise!(
        Instant::from_timestamp_nanos(i128_extract!(*args, "timestamp must be an integer")),
        PyExc_ValueError,
        "timestamp is out of range"
    )
    .shift_secs_unchecked(offset_secs as i64)
    .to_datetime();
    new_unchecked(
        cls,
        OffsetDateTime {
            date,
            time,
            offset_secs,
        },
    )
}

// parse ±HH:MM[:SS] exactly
fn parse_hms_offset(s: &[u8]) -> Option<i32> {
    let sign = match s.get(0) {
        Some(b'+') => 1,
        Some(b'-') => -1,
        Some(b'Z' | b'z') if s.len() == 1 => return Some(0),
        _ => return None,
    };
    if s.len() >= 6 && s[3] == b':' {
        // the HH:MM part
        let secs = (get_digit!(s, 1, ..=b'2') * 10 + get_digit!(s, 2)) as i32 * 3600
            + (get_digit!(s, 4, ..=b'5') * 10 + get_digit!(s, 5)) as i32 * 60;
        // the optional seconds part
        match s.get(6) {
            Some(b':') if s.len() == 9 => {
                Some(secs + get_digit!(s, 7, ..=b'5') as i32 * 10 + get_digit!(s, 8) as i32)
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

unsafe extern "C" fn from_default_format(
    cls: *mut PyObject,
    s_obj: *mut PyObject,
) -> *mut PyObject {
    new_unchecked(
        cls.cast(),
        unwrap_or_raise!(
            OffsetDateTime::parse(pystr_to_utf8!(s_obj, "Expected a string")),
            PyExc_ValueError,
            "Invalid format: %R",
            s_obj
        ),
    )
}

// exactly "+HH:MM" or "Z"
fn parse_hm_offset(s: &[u8]) -> Option<i32> {
    let sign = match s.get(0) {
        Some(b'+') => 1,
        Some(b'-') => -1,
        Some(b'Z' | b'z') if s.len() == 1 => return Some(0),
        _ => return None,
    };
    if s.len() == 6 && s[3] == b':' {
        Some(
            sign * ((get_digit!(s, 1, ..=b'2') * 10 + get_digit!(s, 2)) as i32 * 3600
                + (get_digit!(s, 4, ..=b'5') * 10 + get_digit!(s, 5)) as i32 * 60),
        )
        .filter(|secs| secs.abs() < 24 * 3600)
    } else {
        return None;
    }
}

unsafe extern "C" fn from_rfc3339(cls: *mut PyObject, s_obj: *mut PyObject) -> *mut PyObject {
    let s = &mut pystr_to_utf8!(s_obj, "Expected a string");
    // at least: "YYYY-MM-DDTHH:MM:SSZ"
    if s.len() < 20 {
        raise!(PyExc_ValueError, "Invalid RFC3339 format: %R", s_obj);
    }
    let date = unwrap_or_raise!(
        Date::parse_partial(s),
        PyExc_ValueError,
        "Invalid RFC3339 format: %R",
        s_obj
    );
    // parse the separator
    if !(s[0] == b'T' || s[0] == b't' || s[0] == b' ' || s[0] == b'_') {
        raise!(PyExc_ValueError, "Invalid RFC3339 format: %R", s_obj);
    }
    *s = &s[1..];
    let time = unwrap_or_raise!(
        Time::parse_partial(s),
        PyExc_ValueError,
        "Invalid RFC3339 format: %R",
        s_obj
    );
    let offset_secs = unwrap_or_raise!(
        parse_hm_offset(s),
        PyExc_ValueError,
        "Invalid RFC3339 format: %R",
        s_obj
    );
    new_unchecked(
        cls.cast(),
        OffsetDateTime {
            date,
            time,
            offset_secs,
        },
    )
}

unsafe extern "C" fn in_fixed_offset(
    slf_obj: *mut PyObject,
    args: *mut *mut PyObject,
    nargs: Py_ssize_t,
) -> *mut PyObject {
    if nargs == 0 {
        return newref(slf_obj);
    } else if nargs > 1 {
        raise!(
            PyExc_TypeError,
            "in_fixed_offset() takes at most 1 argument"
        );
    }
    let cls = Py_TYPE(slf_obj);
    let slf = OffsetDateTime::extract(slf_obj);
    let offset_secs = to_py!(extract_offset(*args, State::for_type(cls).time_delta_type));
    let OffsetDateTime { date, time, .. } = slf.small_naive_shift(offset_secs - slf.offset_secs);
    new_unchecked(
        cls,
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
        OffsetDateTime::extract(slf).to_local_system(py_api),
    )
}

unsafe extern "C" fn strptime(cls: *mut PyObject, args: *mut PyObject) -> *mut PyObject {
    // FUTURE: get this working with vectorcall
    let &State {
        strptime,
        timezone_type,
        ..
    } = State::for_type(cls.cast());
    let parsed = py_try!(PyObject_Call(strptime, args, NULL()));
    let tzinfo = PyDateTime_DATE_GET_TZINFO(parsed);
    if PyObject_IsInstance(tzinfo, timezone_type.cast()) == 0 {
        raise!(
            PyExc_ValueError,
            "parsed datetime must have a timezone, got %R",
            tzinfo
        );
    }
    new_unchecked(
        cls.cast(),
        OffsetDateTime {
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
            offset_secs: offset_from_py_dt(parsed),
        },
    )
}

pub(crate) fn offset_fmt_rfc3339(secs: i32) -> String {
    let (sign, secs) = if secs < 0 { ('-', -secs) } else { ('+', secs) };
    format!("{}{:02}:{:02}", sign, secs / 3600, (secs % 3600) / 60)
}

unsafe extern "C" fn rfc3339(slf: *mut PyObject, _: *mut PyObject) -> *mut PyObject {
    let OffsetDateTime {
        date,
        time,
        offset_secs,
    } = OffsetDateTime::extract(slf);
    py_str(&format!(
        "{} {}{}",
        date,
        time,
        offset_fmt_rfc3339(offset_secs)
    ))
}

unsafe extern "C" fn common_iso8601(slf: *mut PyObject, _: *mut PyObject) -> *mut PyObject {
    let OffsetDateTime {
        date,
        time,
        offset_secs,
    } = OffsetDateTime::extract(slf);
    py_str(&format!("{}T{}{}", date, time, offset_fmt(offset_secs)))
}

unsafe extern "C" fn rfc2822(slf: *mut PyObject, _: *mut PyObject) -> *mut PyObject {
    let &State {
        format_rfc2822,
        datetime_api,
        ..
    } = State::for_obj(slf);
    PyObject_CallOneArg(
        format_rfc2822,
        OffsetDateTime::extract(slf).to_py(datetime_api),
    )
}

unsafe extern "C" fn from_rfc2822(cls: *mut PyObject, s_obj: *mut PyObject) -> *mut PyObject {
    let state = State::for_type(cls.cast());
    let py_dt = py_try!(PyObject_CallOneArg(state.parse_rfc2822, s_obj));
    // TODO: refcounts, refcounts
    new_unchecked(
        cls.cast(),
        unwrap_or_raise!(
            OffsetDateTime::from_py(py_dt, state),
            PyExc_ValueError,
            "RFC 2822 string with missing or -0000 offset cannot be parsed as OffsetDateTime: %R",
            s_obj
        ),
    )
}

static mut METHODS: &[PyMethodDef] = &[
    // FUTURE: get docstrings from Python implementation
    method!(identity named "__copy__", ""),
    method!(identity named "__deepcopy__", "", METH_O),
    method!(in_tz, "Convert to a `ZonedDateTime` with given tz", METH_O),
    method!(exact_eq, "Exact equality", METH_O),
    method!(py_datetime, "Convert to a `datetime.datetime`"),
    method!(in_utc, "Convert to a `UTCDateTime`"),
    method!(in_local_system, "Convert to a datetime in the local system"),
    method!(date, "The date component"),
    method!(time, "The time component"),
    method!(default_format, "Format in the default way"),
    classmethod!(from_default_format, "", METH_O),
    method!(rfc3339, "Format according to RFC3339"),
    classmethod!(
        from_rfc3339,
        "Create a new instance from an RFC3339 timestamp",
        METH_O
    ),
    method!(rfc2822, "Format according to RFC2822"),
    classmethod!(
        from_rfc2822,
        "Create a new instance from an RFC2822 timestamp",
        METH_O
    ),
    method!(
        common_iso8601,
        "Format according to the common ISO8601 style"
    ),
    classmethod!(from_default_format named "from_common_iso8601", "", METH_O),
    method!(__reduce__, ""),
    classmethod!(
        now,
        "Create a new instance representing the current time",
        METH_O
    ),
    classmethod!(
        from_py_datetime,
        "Create a new instance from a `datetime.datetime`",
        METH_O
    ),
    method!(naive, "Convert to a `NaiveDateTime`"),
    method!(timestamp, "Convert to a UNIX timestamp"),
    method!(
        timestamp_millis,
        "Convert to a UNIX timestamp in milliseconds"
    ),
    method!(
        timestamp_nanos,
        "Convert to a UNIX timestamp in nanoseconds"
    ),
    PyMethodDef {
        ml_name: c_str!("from_timestamp"),
        ml_meth: PyMethodDefPointer {
            PyCMethod: from_timestamp,
        },
        ml_flags: METH_CLASS | METH_METHOD | METH_FASTCALL | METH_KEYWORDS,
        ml_doc: c_str!("Create a new instance from a UNIX timestamp"),
    },
    PyMethodDef {
        ml_name: c_str!("from_timestamp_millis"),
        ml_meth: PyMethodDefPointer {
            PyCMethod: from_timestamp_millis,
        },
        ml_flags: METH_CLASS | METH_METHOD | METH_FASTCALL | METH_KEYWORDS,
        ml_doc: c_str!("Create a new instance from a UNIX timestamp in milliseconds"),
    },
    PyMethodDef {
        ml_name: c_str!("from_timestamp_nanos"),
        ml_meth: PyMethodDefPointer {
            PyCMethod: from_timestamp_nanos,
        },
        ml_flags: METH_CLASS | METH_METHOD | METH_FASTCALL | METH_KEYWORDS,
        ml_doc: c_str!("Create a new instance from a UNIX timestamp in nanoseconds"),
    },
    PyMethodDef {
        ml_name: c_str!("replace"),
        ml_meth: PyMethodDefPointer { PyCMethod: replace },
        ml_flags: METH_METHOD | METH_FASTCALL | METH_KEYWORDS,
        ml_doc: c_str!("Return a new instance with the specified fields replaced"),
    },
    PyMethodDef {
        ml_name: c_str!("in_fixed_offset"),
        ml_meth: PyMethodDefPointer {
            _PyCFunctionFast: in_fixed_offset,
        },
        ml_flags: METH_FASTCALL,
        ml_doc: c_str!("Return a new instance with the specified fields replaced"),
    },
    method!(
        with_date,
        "Return a new instance with the date replaced",
        METH_O
    ),
    method!(
        with_time,
        "Return a new instance with the time replaced",
        METH_O
    ),
    PyMethodDef {
        ml_name: c_str!("strptime"),
        ml_meth: PyMethodDefPointer {
            PyCFunction: strptime,
        },
        ml_flags: METH_CLASS | METH_VARARGS,
        ml_doc: c_str!("Parse a string into a NaiveDateTime"),
    },
    PyMethodDef::zeroed(),
];

unsafe extern "C" fn get_year(slf: *mut PyObject, _: *mut c_void) -> *mut PyObject {
    PyLong_FromLong(OffsetDateTime::extract(slf).date.year.into())
}

unsafe extern "C" fn get_month(slf: *mut PyObject, _: *mut c_void) -> *mut PyObject {
    PyLong_FromLong(OffsetDateTime::extract(slf).date.month.into())
}

unsafe extern "C" fn get_day(slf: *mut PyObject, _: *mut c_void) -> *mut PyObject {
    PyLong_FromLong(OffsetDateTime::extract(slf).date.day.into())
}

unsafe extern "C" fn get_hour(slf: *mut PyObject, _: *mut c_void) -> *mut PyObject {
    PyLong_FromLong(OffsetDateTime::extract(slf).time.hour.into())
}

unsafe extern "C" fn get_minute(slf: *mut PyObject, _: *mut c_void) -> *mut PyObject {
    PyLong_FromLong(OffsetDateTime::extract(slf).time.minute.into())
}

unsafe extern "C" fn get_second(slf: *mut PyObject, _: *mut c_void) -> *mut PyObject {
    PyLong_FromLong(OffsetDateTime::extract(slf).time.second.into())
}

unsafe extern "C" fn get_nanos(slf: *mut PyObject, _: *mut c_void) -> *mut PyObject {
    PyLong_FromLong(OffsetDateTime::extract(slf).time.nanos as _)
}

unsafe extern "C" fn get_offset(slf: *mut PyObject, _: *mut c_void) -> *mut PyObject {
    time_delta::new_unchecked(
        State::for_type(Py_TYPE(slf)).time_delta_type,
        time_delta::TimeDelta::from_secs_unchecked(OffsetDateTime::extract(slf).offset_secs as i64),
    )
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

pub(crate) static mut SPEC: PyType_Spec = PyType_Spec {
    name: c_str!("whenever.OffsetDateTime"),
    basicsize: mem::size_of::<PyOffsetDateTime>() as _,
    itemsize: 0,
    flags: Py_TPFLAGS_DEFAULT as _,
    slots: unsafe { SLOTS as *const [_] as *mut _ },
};
