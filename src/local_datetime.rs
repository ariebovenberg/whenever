use core::ffi::{c_char, c_int, c_long, c_void};
use core::{mem, ptr, ptr::null_mut as NULL};
use pyo3_ffi::*;
use std::time::SystemTime;

use crate::common::*;
use crate::{
    date::{self, Date},
    date_delta::DateDelta,
    naive_datetime::DateTime,
    offset_datetime::{self, naive, timestamp, timestamp_millis, timestamp_nanos, OffsetDateTime},
    time::{self, Time},
    time_delta::{self, TimeDelta},
    utc_datetime::{self, Instant},
    zoned_datetime::{self, ZonedDateTime},
    State,
};

#[repr(C)]
pub(crate) struct PyLocalDateTime {
    _ob_base: PyObject,
    dt: OffsetDateTime,
}

impl OffsetDateTime {
    pub(crate) unsafe fn from_local_system(
        py_api: &PyDateTime_CAPI,
        date: Date,
        time: Time,
        dis: Disambiguate,
    ) -> Result<Self, Ambiguity> {
        use OffsetResult::*;
        match OffsetResult::for_localsystem(py_api, date, time) {
            Unambiguous(offset_secs) => Ok(OffsetDateTime {
                date,
                time,
                offset_secs,
            }),
            Fold(offset0, offset1) => match dis {
                Disambiguate::Compatible | Disambiguate::Earlier => Ok(offset0),
                Disambiguate::Later => Ok(offset1),
                Disambiguate::Raise => Err(Ambiguity::Fold),
            }
            .map(|offset_secs| OffsetDateTime {
                date,
                time,
                offset_secs,
            }),
            Gap(offset0, offset1) => match dis {
                Disambiguate::Compatible | Disambiguate::Later => Ok((offset1, offset1 - offset0)),
                Disambiguate::Earlier => Ok((offset0, offset0 - offset1)),
                Disambiguate::Raise => Err(Ambiguity::Gap),
            }
            .map(|(offset_secs, shift)| {
                OffsetDateTime {
                    date,
                    time,
                    offset_secs,
                }
                .small_naive_shift(shift)
            }),
        }
    }

    pub(crate) unsafe fn to_local_system(&self, py_api: &PyDateTime_CAPI) -> Self {
        let dt_original = self.to_py(py_api);
        let dt_new = PyObject_CallMethodNoArgs(dt_original, py_str("astimezone"));
        let result = OffsetDateTime {
            date: Date {
                year: PyDateTime_GET_YEAR(dt_new) as u16,
                month: PyDateTime_GET_MONTH(dt_new) as u8,
                day: PyDateTime_GET_DAY(dt_new) as u8,
            },
            time: Time {
                hour: PyDateTime_DATE_GET_HOUR(dt_new) as u8,
                minute: PyDateTime_DATE_GET_MINUTE(dt_new) as u8,
                second: PyDateTime_DATE_GET_SECOND(dt_new) as u8,
                nanos: self.time.nanos,
            },
            offset_secs: offset_from_py_dt(dt_new),
        };
        Py_DECREF(dt_original);
        Py_DECREF(dt_new);
        result
    }
}

impl Instant {
    pub(crate) unsafe fn to_local_system(&self, py_api: &PyDateTime_CAPI) -> OffsetDateTime {
        let dt_utc = self.to_py(py_api);
        let dt_new = PyObject_CallMethodNoArgs(dt_utc, py_str("astimezone"));
        let result = OffsetDateTime {
            date: Date {
                year: PyDateTime_GET_YEAR(dt_new) as u16,
                month: PyDateTime_GET_MONTH(dt_new) as u8,
                day: PyDateTime_GET_DAY(dt_new) as u8,
            },
            time: Time {
                hour: PyDateTime_DATE_GET_HOUR(dt_new) as u8,
                minute: PyDateTime_DATE_GET_MINUTE(dt_new) as u8,
                second: PyDateTime_DATE_GET_SECOND(dt_new) as u8,
                nanos: self.subsec_nanos(),
            },
            offset_secs: offset_from_py_dt(dt_new),
        };
        Py_DECREF(dt_utc);
        Py_DECREF(dt_new);
        result
    }
}

unsafe extern "C" fn __new__(
    cls: *mut PyTypeObject,
    args: *mut PyObject,
    kwargs: *mut PyObject,
) -> *mut PyObject {
    let &State {
        datetime_api: py_api,
        exc_ambiguous,
        exc_skipped,
        str_raise,
        ..
    } = State::for_type(cls);
    let mut year: c_long = 0;
    let mut month: c_long = 0;
    let mut day: c_long = 0;
    let mut hour: c_long = 0;
    let mut minute: c_long = 0;
    let mut second: c_long = 0;
    let mut nanos: c_long = 0;
    let mut disambiguate: *mut PyObject = str_raise;

    // FUTURE: parse them manually, which is more efficient
    if PyArg_ParseTupleAndKeywords(
        args,
        kwargs,
        c_str!("lll|lll$lU:LocalSystemDateTime"),
        vec![
            c_str!("year") as *mut c_char,
            c_str!("month") as *mut c_char,
            c_str!("day") as *mut c_char,
            c_str!("hour") as *mut c_char,
            c_str!("minute") as *mut c_char,
            c_str!("second") as *mut c_char,
            c_str!("nanosecond") as *mut c_char,
            c_str!("disambiguate") as *mut c_char,
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
        &mut disambiguate,
    ) == 0
    {
        return NULL();
    }

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
    // TODO: handle duplication
    let dis = unwrap_or_raise!(
        Disambiguate::parse(pystr_to_utf8!(
            disambiguate,
            "disambiguate must be a string"
        )),
        PyExc_ValueError,
        "Invalid disambiguate value"
    );
    match OffsetDateTime::from_local_system(py_api, date, time, dis) {
        Ok(dt) => new_unchecked(cls, dt).cast(),
        Err(Ambiguity::Fold) => {
            raise!(
                exc_ambiguous.cast(),
                "%s is ambiguous in the system timezone",
                format!("{} {}\0", date, time).as_ptr().cast::<c_char>()
            );
        }
        Err(Ambiguity::Gap) => {
            raise!(
                exc_skipped.cast(),
                "%s is skipped in the system timezone",
                format!("{} {}\0", date, time).as_ptr().cast::<c_char>()
            );
        }
    }
}

pub(crate) unsafe fn new_unchecked(typ: *mut PyTypeObject, dt: OffsetDateTime) -> *mut PyObject {
    let f: allocfunc = (*typ).tp_alloc.unwrap();
    let slf = py_try!(f(typ, 0).cast::<PyLocalDateTime>());
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
        "LocalSystemDateTime({} {}{})",
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
    // TODO: can't assume `a` is a `LocalSystemDateTime`?
    let type_a = Py_TYPE(a_obj);
    let type_b = Py_TYPE(b_obj);
    let inst_a = OffsetDateTime::extract(a_obj).to_instant();
    let inst_b = if type_b == type_a {
        OffsetDateTime::extract(b_obj).to_instant()
    } else if type_b == State::for_type(type_a).utc_datetime_type {
        Instant::extract(b_obj)
    } else if type_b == State::for_type(type_a).zoned_datetime_type {
        ZonedDateTime::extract(b_obj).to_instant()
    } else if type_b == State::for_type(type_a).offset_datetime_type {
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

#[inline]
unsafe extern "C" fn _shift(
    slf: *mut PyObject,
    delta_obj: *mut PyObject,
    negate: bool,
) -> *mut PyObject {
    let type_ = Py_TYPE(slf);
    let &State {
        time_delta_type,
        date_delta_type,
        datetime_api: py_api,
        ..
    } = State::for_type(type_);
    let odt = OffsetDateTime::extract(slf);
    if Py_TYPE(delta_obj) == time_delta_type {
        let mut delta = TimeDelta::extract(delta_obj);
        if negate {
            delta = -delta;
        };
        let result = unwrap_or_raise!(
            Instant::from_nanos(odt.to_instant().total_nanos() + delta.total_nanos()),
            PyExc_ValueError,
            "Resulting datetime is out of range"
        )
        .to_local_system(py_api);
        new_unchecked(type_, result)
    } else if Py_TYPE(delta_obj) == date_delta_type {
        let DateDelta {
            mut months,
            mut days,
        } = DateDelta::extract(delta_obj);
        if negate {
            months = -months;
            days = -days;
        };
        // Prevent re-resolving in case there is no shift.
        // otherwise, ambiguous dates may shift unexpectedly.
        if months == 0 && days == 0 {
            return newref(slf);
        }
        let OffsetDateTime { date, time, .. } = odt;
        let new = OffsetDateTime::from_local_system(
            py_api,
            unwrap_or_raise!(
                date.shift(0, months, days),
                PyExc_ValueError,
                "Resulting date is out of range"
            ),
            time,
            Disambiguate::Compatible,
        )
        .unwrap(); // No error possible in "Compatible" mode
        new_unchecked(type_, new)
    } else {
        // TODO: this doens't make sense
        newref(Py_False())
    }
}

unsafe extern "C" fn __add__(slf: *mut PyObject, arg: *mut PyObject) -> *mut PyObject {
    // TODO: elsewhere!
    if PyType_GetModule(Py_TYPE(slf)) != PyType_GetModule(Py_TYPE(arg)) {
        return newref(Py_NotImplemented());
    }
    _shift(slf, arg, false)
}

unsafe extern "C" fn __sub__(obj_a: *mut PyObject, obj_b: *mut PyObject) -> *mut PyObject {
    let type_a = Py_TYPE(obj_a);
    let type_b = Py_TYPE(obj_b);

    // Easy case: LocalDT - LocalDT
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
            } else if type_b == State::for_mod(mod_a).offset_datetime_type {
                OffsetDateTime::extract(obj_b).to_instant()
            } else {
                // Within the same module, we don't need the NotImplemented path
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
        slot: Py_nb_add,
        pfunc: __add__ as *mut c_void,
    },
    PyType_Slot {
        slot: Py_nb_subtract,
        pfunc: __sub__ as *mut c_void,
    },
    PyType_Slot {
        slot: Py_tp_hash,
        pfunc: offset_datetime::__hash__ as *mut c_void,
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
        raise!(PyExc_TypeError, "Argument must be same type, got %R", obj_b)
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
    if PyVectorcall_NARGS(nargs as _) != 1 {
        raise!(PyExc_TypeError, "Invalid pickle data");
    }
    let mut packed = pybytes_extract!(*args);
    let new = new_unchecked(
        State::for_mod(module).local_datetime_type,
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
    if !packed.is_empty() {
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
    cls: *mut PyTypeObject,
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
        str_disambiguate,
        datetime_api: py_api,
        exc_skipped,
        exc_ambiguous,
        ..
    } = State::for_type(cls);
    let OffsetDateTime { date, time, .. } = OffsetDateTime::extract(slf);
    let mut year = date.year.into();
    let mut month = date.month.into();
    let mut day = date.day.into();
    let mut hour = time.hour.into();
    let mut minute = time.minute.into();
    let mut second = time.second.into();
    let mut nanos = time.nanos.into();
    let mut dis = Disambiguate::Raise;

    if !kwnames.is_null() {
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
            } else if name == str_disambiguate {
                dis = unwrap_or_raise!(
                    Disambiguate::parse(pystr_to_utf8!(value, "disambiguate must be a string")),
                    PyExc_ValueError,
                    "Invalid disambiguate value"
                );
            } else {
                raise!(
                    PyExc_TypeError,
                    "replace() got an unexpected keyword argument %R",
                    name
                );
            }
        }
    };
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
    match OffsetDateTime::from_local_system(py_api, date, time, dis) {
        Ok(dt) => new_unchecked(cls, dt).cast(),
        Err(Ambiguity::Fold) => {
            raise!(
                exc_ambiguous.cast(),
                "%s is ambiguous in the system timezone",
                format!("{} {}\0", date, time).as_ptr().cast::<c_char>()
            );
        }
        Err(Ambiguity::Gap) => {
            raise!(
                exc_skipped.cast(),
                "%s is skipped in the system timezone",
                format!("{} {}\0", date, time).as_ptr().cast::<c_char>()
            );
        }
    }
}

unsafe extern "C" fn now(cls: *mut PyObject, _: *mut PyObject) -> *mut PyObject {
    let &State {
        datetime_api:
            &PyDateTime_CAPI {
                DateTime_FromDateAndTime,
                DateTimeType,
                TimeZone_UTC,
                ..
            },
        ..
    } = State::for_type(cls.cast());
    let (timestamp, nanos) = match SystemTime::now().duration_since(SystemTime::UNIX_EPOCH) {
        Ok(dur) => (dur.as_secs(), dur.subsec_nanos()),
        _ => raise!(PyExc_OSError, "SystemTime before UNIX EPOCH"),
    };
    let DateTime { date, time } = unwrap_or_raise!(
        // Technically conversion to i128 can overflow, but only if system
        // time is set to a very very very distant future
        timestamp.try_into().ok().and_then(Instant::from_timestamp),
        PyExc_ValueError,
        "SystemTime out of range"
    )
    .to_datetime();
    let utc_dt = DateTime_FromDateAndTime(
        date.year.into(),
        date.month.into(),
        date.day.into(),
        time.hour.into(),
        time.minute.into(),
        time.second.into(),
        0,
        TimeZone_UTC,
        DateTimeType,
    );
    // TODO: refcounts
    let local_dt = PyObject_CallMethodNoArgs(utc_dt, py_str("astimezone"));
    new_unchecked(
        cls.cast(),
        OffsetDateTime {
            date: Date {
                year: PyDateTime_GET_YEAR(local_dt) as u16,
                month: PyDateTime_GET_MONTH(local_dt) as u8,
                day: PyDateTime_GET_DAY(local_dt) as u8,
            },
            time: Time {
                hour: PyDateTime_DATE_GET_HOUR(local_dt) as u8,
                minute: PyDateTime_DATE_GET_MINUTE(local_dt) as u8,
                second: PyDateTime_DATE_GET_SECOND(local_dt) as u8,
                nanos,
            },
            offset_secs: offset_from_py_dt(local_dt),
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
        State::for_obj(slf).unpickle_local_datetime,
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

unsafe extern "C" fn from_timestamp(cls: *mut PyObject, arg: *mut PyObject) -> *mut PyObject {
    let result = unwrap_or_raise!(
        Instant::from_timestamp(pyint_as_i64!(arg)),
        PyExc_ValueError,
        "timestamp is out of range"
    )
    .to_local_system(State::for_type(cls.cast()).datetime_api);
    new_unchecked(cls.cast(), result)
}

unsafe extern "C" fn from_timestamp_millis(
    cls: *mut PyObject,
    arg: *mut PyObject,
) -> *mut PyObject {
    let result = unwrap_or_raise!(
        Instant::from_timestamp_millis(pyint_as_i64!(arg)),
        PyExc_ValueError,
        "timestamp is out of range"
    )
    .to_local_system(State::for_type(cls.cast()).datetime_api);
    new_unchecked(cls.cast(), result)
}

unsafe extern "C" fn from_timestamp_nanos(cls: *mut PyObject, arg: *mut PyObject) -> *mut PyObject {
    let result = unwrap_or_raise!(
        Instant::from_timestamp_nanos(i128_extract!(arg, "timestamp must be an integer")),
        PyExc_ValueError,
        "timestamp is out of range"
    )
    .to_local_system(State::for_type(cls.cast()).datetime_api);
    new_unchecked(cls.cast(), result)
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

unsafe extern "C" fn in_fixed_offset(
    slf_obj: *mut PyObject,
    args: *mut *mut PyObject,
    nargs: Py_ssize_t,
) -> *mut PyObject {
    let odt = OffsetDateTime::extract(slf_obj);
    if nargs == 0 {
        return offset_datetime::new_unchecked(State::for_obj(slf_obj).offset_datetime_type, odt);
    } else if nargs > 1 {
        raise!(
            PyExc_TypeError,
            "in_fixed_offset() takes at most 1 argument"
        );
    }
    let &State {
        offset_datetime_type,
        time_delta_type,
        ..
    } = State::for_obj(slf_obj);
    let offset_secs = to_py!(offset_datetime::extract_offset(*args, time_delta_type));
    let OffsetDateTime { date, time, .. } = odt.small_naive_shift(offset_secs - odt.offset_secs);
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
    let cls = Py_TYPE(slf);
    new_unchecked(
        cls,
        OffsetDateTime::extract(slf).to_local_system(State::for_type(cls).datetime_api),
    )
}

unsafe extern "C" fn common_iso8601(slf: *mut PyObject, _: *mut PyObject) -> *mut PyObject {
    let OffsetDateTime {
        date,
        time,
        offset_secs,
    } = OffsetDateTime::extract(slf);
    py_str(&format!("{}T{}{}", date, time, offset_fmt(offset_secs)))
}

static mut METHODS: &[PyMethodDef] = &[
    // FUTURE: get docstrings from Python implementation
    method!(identity named "__copy__", ""),
    method!(identity named "__deepcopy__", "", METH_O),
    method!(in_tz, "Convert to a `ZonedDateTime` with given tz", METH_O),
    method!(exact_eq, "Exact equality", METH_O),
    method!(py_datetime, "Convert to a `datetime.datetime`"),
    method!(in_utc, "Convert to a `UTCDateTime`"),
    method!(date, "The date component"),
    method!(time, "The time component"),
    method!(default_format, "Format in the default way"),
    classmethod!(
        from_default_format,
        "Parse from the default string format",
        METH_O
    ),
    method!(
        common_iso8601,
        "Format according to the common ISO8601 style"
    ),
    method!(in_local_system, "Convert to the local system timezone"),
    method!(__reduce__, ""),
    classmethod!(now, "Create a new instance representing the current time"),
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
    classmethod!(
        from_timestamp,
        "Create a new instance from a UNIX timestamp in seconds",
        METH_O
    ),
    classmethod!(
        from_timestamp_millis,
        "Create a new instance from a UNIX timestamp in milliseconds",
        METH_O
    ),
    classmethod!(
        from_timestamp_nanos,
        "Create a new instance from a UNIX timestamp in nanoseconds",
        METH_O
    ),
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
    name: c_str!("whenever.LocalSystemDateTime"),
    basicsize: mem::size_of::<PyLocalDateTime>() as _,
    itemsize: 0,
    flags: Py_TPFLAGS_DEFAULT as _,
    slots: unsafe { SLOTS as *const [_] as *mut _ },
};
