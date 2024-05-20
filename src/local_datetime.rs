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
    data: OffsetDateTime,
}

pub(crate) const SINGLETONS: [(&str, OffsetDateTime); 0] = [];

impl OffsetDateTime {
    #[inline]
    pub(crate) unsafe fn from_local_system(
        py_api: &PyDateTime_CAPI,
        date: Date,
        time: Time,
        dis: Disambiguate,
    ) -> PyResult<Result<Self, Ambiguity>> {
        use OffsetResult::*;
        Ok(match OffsetResult::for_localsystem(py_api, date, time)? {
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
        })
    }

    #[inline]
    pub(crate) unsafe fn to_local_system(self, py_api: &PyDateTime_CAPI) -> PyResult<Self> {
        let dt_original = self.to_py(py_api)?;
        defer_decref!(dt_original);
        let dt_new =
            PyObject_CallMethodNoArgs(dt_original, steal!("astimezone".to_py()?)).as_result()?;
        defer_decref!(dt_new);
        Ok(OffsetDateTime {
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
            offset_secs: offset_from_py_dt(dt_new)?,
        })
    }
}

impl Instant {
    #[inline]
    pub(crate) unsafe fn to_local_system(
        self,
        py_api: &PyDateTime_CAPI,
    ) -> PyResult<OffsetDateTime> {
        let dt_utc = self.to_py(py_api).as_result()?;
        defer_decref!(dt_utc);
        let dt_new =
            PyObject_CallMethodNoArgs(dt_utc, steal!("astimezone".to_py()?)).as_result()?;
        defer_decref!(dt_new);
        Ok(OffsetDateTime {
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
            offset_secs: offset_from_py_dt(dt_new)?,
        })
    }
}

unsafe fn __new__(cls: *mut PyTypeObject, args: *mut PyObject, kwargs: *mut PyObject) -> PyReturn {
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
        Err(PyErrOccurred())?
    }

    // TODO: Stricter date validation due to offset?
    let date = Date::from_longs(year, month, day).ok_or_else(|| value_error!("Invalid date"))?;
    let time = Time::from_longs(hour, minute, second, nanos)
        .ok_or_else(|| value_error!("Invalid time"))?;
    // TODO: handle duplication
    let dis = Disambiguate::parse(
        disambiguate
            .to_utf8()?
            .ok_or_else(|| type_error!("disambiguate must be a string"))?,
    )
    .ok_or_else(|| type_error!("Invalid disambiguate value"))?;
    match OffsetDateTime::from_local_system(py_api, date, time, dis)? {
        Ok(dt) => new_unchecked(cls, dt),
        Err(Ambiguity::Fold) => Err(py_error!(
            exc_ambiguous.cast(),
            "%s is ambiguous in the system timezone",
            format!("{} {}\0", date, time).as_ptr().cast::<c_char>()
        )),
        Err(Ambiguity::Gap) => Err(py_error!(
            exc_skipped.cast(),
            "%s is skipped in the system timezone",
            format!("{} {}\0", date, time).as_ptr().cast::<c_char>()
        )),
    }
}

pub(crate) unsafe fn new_unchecked(type_: *mut PyTypeObject, dt: OffsetDateTime) -> PyReturn {
    let f: allocfunc = (*type_).tp_alloc.expect("tp_alloc is not set");
    let slf = f(type_, 0).cast::<PyLocalDateTime>();
    if slf.is_null() {
        return Err(PyErrOccurred());
    }
    ptr::addr_of_mut!((*slf).data).write(dt);
    Ok(slf.cast::<PyObject>().as_mut().unwrap())
}

unsafe fn __repr__(slf: *mut PyObject) -> PyReturn {
    let OffsetDateTime {
        date,
        time,
        offset_secs,
    } = OffsetDateTime::extract(slf);
    format!(
        "LocalSystemDateTime({} {}{})",
        date,
        time,
        offset_fmt(offset_secs)
    )
    .to_py()
}

unsafe fn __str__(slf: *mut PyObject) -> PyReturn {
    format!("{}", OffsetDateTime::extract(slf)).to_py()
}

unsafe fn __richcmp__(a_obj: *mut PyObject, b_obj: *mut PyObject, op: c_int) -> PyReturn {
    // TODO: reflexivity
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

#[inline]
unsafe fn _shift(slf: *mut PyObject, delta_obj: *mut PyObject, negate: bool) -> PyReturn {
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
        new_unchecked(
            type_,
            Instant::from_nanos(odt.to_instant().total_nanos() + delta.total_nanos())
                .ok_or_else(|| value_error!("Resulting datetime is out of range"))
                .and_then(|inst| inst.to_local_system(py_api))?,
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
        // Prevent re-resolving in case there is no shift.
        // otherwise, ambiguous dates may shift unexpectedly.
        if months == 0 && days == 0 {
            return Ok(newref(slf));
        }
        let OffsetDateTime { date, time, .. } = odt;
        new_unchecked(
            type_,
            OffsetDateTime::from_local_system(
                py_api,
                date.shift(0, months, days)
                    .ok_or_else(|| value_error!("Resulting date is out of range"))?,
                time,
                Disambiguate::Compatible,
            )?
            // No error possible in "Compatible" mode
            .unwrap(),
        )
    } else {
        // TODO: test
        Ok(newref(Py_NotImplemented()))
    }
}

unsafe fn __add__(slf: *mut PyObject, arg: *mut PyObject) -> PyReturn {
    // TODO: elsewhere!
    if PyType_GetModule(Py_TYPE(slf)) != PyType_GetModule(Py_TYPE(arg)) {
        return Ok(newref(Py_NotImplemented()));
    }
    _shift(slf, arg, false)
}

unsafe fn __sub__(obj_a: *mut PyObject, obj_b: *mut PyObject) -> PyReturn {
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
            return Ok(newref(Py_NotImplemented()));
        }
    };
    time_delta::new_unchecked(
        State::for_type(type_a).time_delta_type,
        TimeDelta::from_nanos_unchecked(inst_a.total_nanos() - inst_b.total_nanos()),
    )
}

static mut SLOTS: &[PyType_Slot] = &[
    slotmethod!(Py_tp_new, __new__),
    slotmethod!(Py_tp_str, __str__, 1),
    slotmethod!(Py_tp_repr, __repr__, 1),
    slotmethod!(Py_tp_richcompare, __richcmp__),
    slotmethod!(Py_nb_add, __add__, 2),
    slotmethod!(Py_nb_subtract, __sub__, 2),
    PyType_Slot {
        slot: Py_tp_doc,
        pfunc: "A datetime type in the local system timezone\0".as_ptr() as *mut c_void,
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

unsafe fn exact_eq(obj_a: *mut PyObject, obj_b: *mut PyObject) -> PyReturn {
    if Py_TYPE(obj_a) == Py_TYPE(obj_b) {
        Ok(newref(
            (OffsetDateTime::extract(obj_a) == OffsetDateTime::extract(obj_b)).to_py()?,
        ))
    } else {
        Err(type_error!("Argument must be same type, got %R", obj_b))
    }
}

unsafe fn in_tz(slf: *mut PyObject, tz: *mut PyObject) -> PyReturn {
    let type_ = Py_TYPE(slf);
    let &State {
        zoneinfo_type,
        datetime_api: py_api,
        zoned_datetime_type,
        ..
    } = State::for_type(type_);
    let zoneinfo = PyObject_CallOneArg(zoneinfo_type.cast(), tz).as_result()?;
    defer_decref!(zoneinfo);
    let odt = OffsetDateTime::extract(slf);
    let OffsetDateTime { date, time, .. } = odt.small_naive_shift(-odt.offset_secs);
    zoned_datetime::new_unchecked(
        zoned_datetime_type,
        ZonedDateTime::from_utc(py_api, date, time, zoneinfo)?,
    )
}

pub(crate) unsafe fn unpickle(module: *mut PyObject, args: &[*mut PyObject]) -> PyReturn {
    if args.len() != 1 {
        Err(type_error!("Invalid pickle data"))?
    }
    let mut packed = args[0]
        .to_bytes()?
        .ok_or_else(|| type_error!("Invalid pickle data"))?;
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
        Err(value_error!("Invalid pickle data"))?
    }
    new
}

unsafe fn py_datetime(slf: *mut PyObject, _: *mut PyObject) -> PyReturn {
    OffsetDateTime::extract(slf).to_py(State::for_obj(slf).datetime_api)
}

unsafe fn in_utc(slf: *mut PyObject, _: *mut PyObject) -> PyReturn {
    utc_datetime::new_unchecked(
        State::for_obj(slf).utc_datetime_type,
        OffsetDateTime::extract(slf).to_instant(),
    )
}

unsafe fn date(slf: *mut PyObject, _: *mut PyObject) -> PyReturn {
    date::new_unchecked(
        State::for_obj(slf).date_type,
        OffsetDateTime::extract(slf).date,
    )
}

unsafe fn time(slf: *mut PyObject, _: *mut PyObject) -> PyReturn {
    time::new_unchecked(
        State::for_obj(slf).time_type,
        OffsetDateTime::extract(slf).time,
    )
}

// TODO: test
unsafe fn with_date(slf: *mut PyObject, arg: *mut PyObject) -> PyReturn {
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
        Err(type_error!("date must be a Date instance"))
    }
}

// TODO: test
unsafe fn with_time(slf: *mut PyObject, arg: *mut PyObject) -> PyReturn {
    let cls = Py_TYPE(slf);
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
        Err(type_error!("time must be a Time instance"))
    }
}

unsafe fn default_format(slf: *mut PyObject, _: *mut PyObject) -> PyReturn {
    __str__(slf)
}

unsafe fn replace(
    slf: *mut PyObject,
    cls: *mut PyTypeObject,
    args: &[*mut PyObject],
    kwargs: &[(*mut PyObject, *mut PyObject)],
) -> PyReturn {
    if !args.is_empty() {
        Err(type_error!("replace() takes no positional arguments"))?
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

    for &(name, value) in kwargs {
        if name == str_year {
            year = value
                .to_long()?
                .ok_or_else(|| type_error!("year must be an integer"))?
        } else if name == str_month {
            month = value
                .to_long()?
                .ok_or_else(|| type_error!("month must be an integer"))?
        } else if name == str_day {
            day = value
                .to_long()?
                .ok_or_else(|| type_error!("day must be an integer"))?
        } else if name == str_hour {
            hour = value
                .to_long()?
                .ok_or_else(|| type_error!("hour must be an integer"))?
        } else if name == str_minute {
            minute = value
                .to_long()?
                .ok_or_else(|| type_error!("minute must be an integer"))?
        } else if name == str_second {
            second = value
                .to_long()?
                .ok_or_else(|| type_error!("second must be an integer"))?
        } else if name == str_nanosecond {
            nanos = value
                .to_long()?
                .ok_or_else(|| type_error!("nanosecond must be an integer"))?
        } else if name == str_disambiguate {
            dis = Disambiguate::parse(
                value
                    .to_utf8()?
                    .ok_or_else(|| type_error!("disambiguate must be a string"))?,
            )
            .ok_or_else(|| type_error!("Invalid disambiguate value"))?;
        } else {
            Err(type_error!(
                "replace() got an unexpected keyword argument: %R",
                name
            ))?
        }
    }
    let date = Date::from_longs(year, month, day).ok_or_else(|| value_error!("Invalid date"))?;
    let time = Time::from_longs(hour, minute, second, nanos)
        .ok_or_else(|| value_error!("Invalid time"))?;
    match OffsetDateTime::from_local_system(py_api, date, time, dis)? {
        Ok(dt) => new_unchecked(cls, dt),
        Err(Ambiguity::Fold) => Err(py_error!(
            exc_ambiguous.cast(),
            "%s is ambiguous in the system timezone",
            format!("{} {}\0", date, time).as_ptr().cast::<c_char>()
        )),
        Err(Ambiguity::Gap) => Err(py_error!(
            exc_skipped.cast(),
            "%s is skipped in the system timezone",
            format!("{} {}\0", date, time).as_ptr().cast::<c_char>()
        )),
    }
}

unsafe fn now(cls: *mut PyObject, _: *mut PyObject) -> PyReturn {
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
        _ => Err(py_error!(PyExc_OSError, "SystemTime before UNIX EPOCH"))?,
    };
    // Technically conversion to i128 can overflow, but only if system
    // time is set to a very very very distant future
    let DateTime { date, time } = timestamp
        .try_into()
        .ok()
        .and_then(Instant::from_timestamp)
        .ok_or_else(|| value_error!("timestamp is out of range"))?
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
    )
    .as_result()?;
    defer_decref!(utc_dt);
    let local_dt = PyObject_CallMethodNoArgs(utc_dt, steal!("astimezone".to_py()?)).as_result()?;
    defer_decref!(local_dt);
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
            offset_secs: offset_from_py_dt(local_dt)?,
        },
    )
}

unsafe fn from_py_datetime(cls: *mut PyObject, dt: *mut PyObject) -> PyReturn {
    if PyDateTime_Check(dt) == 0 {
        Err(type_error!("Argument must be a datetime.datetime instance"))?
    }
    new_unchecked(
        cls.cast(),
        match OffsetDateTime::from_py(dt, State::for_type(cls.cast()))? {
            Some(dt) => dt,
            None => Err(value_error!(
                "tzinfo must be a datetime.timezone, got: %R",
                dt
            ))?,
        },
    )
}

unsafe fn __reduce__(slf: *mut PyObject, _: *mut PyObject) -> PyReturn {
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
        steal!(PyTuple_Pack(
            1,
            steal!(pack![year, month, day, hour, minute, second, nanos, offset_secs].to_py()?)
        )
        .as_result()?),
    )
    .as_result()
}

unsafe fn from_timestamp(cls: *mut PyObject, arg: *mut PyObject) -> PyReturn {
    new_unchecked(
        cls.cast(),
        Instant::from_timestamp(
            arg.to_i64()?
                .ok_or_else(|| type_error!("argument must be an integer"))?,
        )
        .ok_or_else(|| value_error!("timestamp is out of range"))
        .and_then(|inst| inst.to_local_system(State::for_type(cls.cast()).datetime_api))?,
    )
}

unsafe fn from_timestamp_millis(cls: *mut PyObject, arg: *mut PyObject) -> PyReturn {
    new_unchecked(
        cls.cast(),
        Instant::from_timestamp_millis(
            arg.to_i64()?
                .ok_or_else(|| type_error!("timestamp must be an integer"))?,
        )
        .ok_or_else(|| value_error!("timestamp is out of range"))
        .and_then(|inst| inst.to_local_system(State::for_type(cls.cast()).datetime_api))?,
    )
}

unsafe fn from_timestamp_nanos(cls: *mut PyObject, arg: *mut PyObject) -> PyReturn {
    new_unchecked(
        cls.cast(),
        Instant::from_timestamp_nanos(
            arg.to_i128()?
                .ok_or_else(|| type_error!("timestamp must be an integer"))?,
        )
        .ok_or_else(|| value_error!("timestamp is out of range"))
        .and_then(|inst| inst.to_local_system(State::for_type(cls.cast()).datetime_api))?,
    )
}

unsafe fn from_default_format(cls: *mut PyObject, s_obj: *mut PyObject) -> PyReturn {
    new_unchecked(
        cls.cast(),
        OffsetDateTime::parse(
            s_obj
                .to_utf8()?
                .ok_or_else(|| type_error!("argument must be a string"))?,
        )
        .ok_or_else(|| value_error!("Invalid format: %R", s_obj))?,
    )
}

unsafe fn in_fixed_offset(slf_obj: *mut PyObject, args: &[*mut PyObject]) -> PyReturn {
    let odt = OffsetDateTime::extract(slf_obj);
    if args.is_empty() {
        return offset_datetime::new_unchecked(State::for_obj(slf_obj).offset_datetime_type, odt);
    } else if args.len() > 1 {
        Err(type_error!("in_fixed_offset() takes at most 1 argument"))?
    }
    let &State {
        offset_datetime_type,
        time_delta_type,
        ..
    } = State::for_obj(slf_obj);
    let offset_secs = offset_datetime::extract_offset(args[0], time_delta_type)?;
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

unsafe fn in_local_system(slf: *mut PyObject, _: *mut PyObject) -> PyReturn {
    let cls = Py_TYPE(slf);
    new_unchecked(
        cls,
        OffsetDateTime::extract(slf).to_local_system(State::for_type(cls).datetime_api)?,
    )
}

static mut METHODS: &[PyMethodDef] = &[
    // FUTURE: get docstrings from Python implementation
    method!(identity2 named "__copy__", ""),
    method!(identity2 named "__deepcopy__", "", METH_O),
    method!(in_tz, "Convert to a `ZonedDateTime` with given tz", METH_O),
    method!(exact_eq, "Exact equality", METH_O),
    method!(py_datetime, "Convert to a `datetime.datetime`"),
    method!(in_utc, "Convert to a `UTCDateTime`"),
    method!(date, "The date component"),
    method!(time, "The time component"),
    method!(default_format, "Format in the default way"),
    method!(
        from_default_format,
        "Parse from the default string format",
        METH_O | METH_CLASS
    ),
    method!(
        default_format named "common_iso8601",
        "Format according to the common ISO8601 style"
    ),
    method!(in_local_system, "Convert to the local system timezone"),
    method!(__reduce__, ""),
    method!(
        now,
        "Create a new instance representing the current time",
        METH_CLASS | METH_NOARGS
    ),
    method!(
        from_py_datetime,
        "Create a new instance from a `datetime.datetime`",
        METH_O | METH_CLASS
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
    method!(
        from_timestamp,
        "Create a new instance from a UNIX timestamp in seconds",
        METH_O | METH_CLASS
    ),
    method!(
        from_timestamp_millis,
        "Create a new instance from a UNIX timestamp in milliseconds",
        METH_O | METH_CLASS
    ),
    method!(
        from_timestamp_nanos,
        "Create a new instance from a UNIX timestamp in nanoseconds",
        METH_O | METH_CLASS
    ),
    method_kwargs!(
        replace,
        "Return a new instance with the specified fields replaced"
    ),
    method_vararg!(
        in_fixed_offset,
        "Return an equivalent instance with the given offset"
    ),
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

unsafe fn get_year(slf: *mut PyObject) -> PyReturn {
    OffsetDateTime::extract(slf).date.year.to_py()
}

unsafe fn get_month(slf: *mut PyObject) -> PyReturn {
    OffsetDateTime::extract(slf).date.month.to_py()
}

unsafe fn get_day(slf: *mut PyObject) -> PyReturn {
    OffsetDateTime::extract(slf).date.day.to_py()
}

unsafe fn get_hour(slf: *mut PyObject) -> PyReturn {
    OffsetDateTime::extract(slf).time.hour.to_py()
}

unsafe fn get_minute(slf: *mut PyObject) -> PyReturn {
    OffsetDateTime::extract(slf).time.minute.to_py()
}

unsafe fn get_second(slf: *mut PyObject) -> PyReturn {
    OffsetDateTime::extract(slf).time.second.to_py()
}

unsafe fn get_nanos(slf: *mut PyObject) -> PyReturn {
    OffsetDateTime::extract(slf).time.nanos.to_py()
}

unsafe fn get_offset(slf: *mut PyObject) -> PyReturn {
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
