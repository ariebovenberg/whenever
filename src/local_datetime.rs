use core::ffi::{c_int, c_long, c_void, CStr};
use core::{mem, ptr::null_mut as NULL};
use pyo3_ffi::*;
use std::time::SystemTime;

use crate::common::*;
use crate::{
    date::Date,
    date_delta::DateDelta,
    datetime_delta::{set_units_from_kwargs, DateTimeDelta},
    naive_datetime::{set_components_from_kwargs, DateTime},
    offset_datetime::{self, naive, timestamp, timestamp_millis, timestamp_nanos, OffsetDateTime},
    time::Time,
    time_delta::TimeDelta,
    utc_datetime::Instant,
    zoned_datetime::ZonedDateTime,
    State,
};

pub(crate) const SINGLETONS: [(&CStr, OffsetDateTime); 0] = [];

impl OffsetDateTime {
    #[inline]
    pub(crate) unsafe fn from_system_tz(
        py_api: &PyDateTime_CAPI,
        date: Date,
        time: Time,
        dis: Disambiguate,
    ) -> PyResult<Result<Self, Ambiguity>> {
        use OffsetResult::*;
        Ok(match OffsetResult::for_system_tz(py_api, date, time)? {
            Unambiguous(offset_secs) => Ok(OffsetDateTime::new_unchecked(date, time, offset_secs)),
            Fold(offset0, offset1) => match dis {
                Disambiguate::Compatible | Disambiguate::Earlier => Ok(offset0),
                Disambiguate::Later => Ok(offset1),
                Disambiguate::Raise => Err(Ambiguity::Fold),
            }
            .map(|offset_secs| OffsetDateTime::new_unchecked(date, time, offset_secs)),
            Gap(offset0, offset1) => match dis {
                Disambiguate::Compatible | Disambiguate::Later => Ok((offset1, offset1 - offset0)),
                Disambiguate::Earlier => Ok((offset0, offset0 - offset1)),
                Disambiguate::Raise => Err(Ambiguity::Gap),
            }
            .map(|(offset_secs, shift)| {
                DateTime { date, time }
                    .small_shift_unchecked(shift)
                    .with_offset_unchecked(offset_secs)
            }),
        })
    }

    #[inline]
    pub(crate) unsafe fn to_system_tz(self, py_api: &PyDateTime_CAPI) -> PyResult<Self> {
        let dt_original = self.to_py(py_api)?;
        defer_decref!(dt_original);
        // FUTURE: define `astimezone` string once, then reuse it?
        let dt_new = methcall0(dt_original, "astimezone")?;
        defer_decref!(dt_new);
        Ok(OffsetDateTime::new_unchecked(
            Date {
                year: PyDateTime_GET_YEAR(dt_new) as u16,
                month: PyDateTime_GET_MONTH(dt_new) as u8,
                day: PyDateTime_GET_DAY(dt_new) as u8,
            },
            Time {
                hour: PyDateTime_DATE_GET_HOUR(dt_new) as u8,
                minute: PyDateTime_DATE_GET_MINUTE(dt_new) as u8,
                second: PyDateTime_DATE_GET_SECOND(dt_new) as u8,
                nanos: self.time().nanos,
            },
            offset_from_py_dt(dt_new)?,
        ))
    }
}

impl Instant {
    #[inline]
    pub(crate) unsafe fn to_system_tz(self, py_api: &PyDateTime_CAPI) -> PyResult<OffsetDateTime> {
        let dt_utc = self.to_py(py_api)?;
        defer_decref!(dt_utc);
        let dt_new = methcall0(dt_utc, "astimezone")?;
        defer_decref!(dt_new);
        Ok(OffsetDateTime::new_unchecked(
            Date {
                year: PyDateTime_GET_YEAR(dt_new) as u16,
                month: PyDateTime_GET_MONTH(dt_new) as u8,
                day: PyDateTime_GET_DAY(dt_new) as u8,
            },
            Time {
                hour: PyDateTime_DATE_GET_HOUR(dt_new) as u8,
                minute: PyDateTime_DATE_GET_MINUTE(dt_new) as u8,
                second: PyDateTime_DATE_GET_SECOND(dt_new) as u8,
                nanos: self.subsec_nanos(),
            },
            offset_from_py_dt(dt_new)?,
        ))
    }
}

unsafe fn __new__(cls: *mut PyTypeObject, args: *mut PyObject, kwargs: *mut PyObject) -> PyReturn {
    let &State {
        py_api,
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
        c"lll|lll$lU:LocalSystemDateTime".as_ptr(),
        vec![
            c"year".as_ptr() as *mut _,
            c"month".as_ptr() as *mut _,
            c"day".as_ptr() as *mut _,
            c"hour".as_ptr() as *mut _,
            c"minute".as_ptr() as *mut _,
            c"second".as_ptr() as *mut _,
            c"nanosecond".as_ptr() as *mut _,
            c"disambiguate".as_ptr() as *mut _,
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
        Err(py_err!())?
    }

    let date = Date::from_longs(year, month, day).ok_or_value_err("Invalid date")?;
    let time = Time::from_longs(hour, minute, second, nanos).ok_or_value_err("Invalid time")?;
    let dis = Disambiguate::from_py(disambiguate)?;
    OffsetDateTime::from_system_tz(py_api, date, time, dis)?
        .map_err(|e| match e {
            Ambiguity::Fold => py_err!(
                exc_ambiguous,
                "{} {} is ambiguous in the system timezone",
                date,
                time
            ),
            Ambiguity::Gap => py_err!(
                exc_skipped,
                "{} {} is skipped in the system timezone",
                date,
                time
            ),
        })?
        .to_obj(cls)
}

unsafe fn __repr__(slf: *mut PyObject) -> PyReturn {
    let (date, time, offset) = OffsetDateTime::extract(slf).as_tuple();
    format!(
        "LocalSystemDateTime({} {}{})",
        date,
        time,
        offset_fmt(offset)
    )
    .to_py()
}

unsafe fn __str__(slf: *mut PyObject) -> PyReturn {
    format!("{}", OffsetDateTime::extract(slf)).to_py()
}

unsafe fn __richcmp__(a_obj: *mut PyObject, b_obj: *mut PyObject, op: c_int) -> PyReturn {
    let type_a = Py_TYPE(a_obj);
    let type_b = Py_TYPE(b_obj);
    let inst_a = OffsetDateTime::extract(a_obj).to_instant();
    let inst_b = if type_b == type_a {
        OffsetDateTime::extract(b_obj).to_instant()
    } else if type_b == State::for_type(type_a).utc_datetime_type {
        Instant::extract(b_obj)
    } else if type_b == State::for_type(type_a).zoned_datetime_type {
        ZonedDateTime::extract(b_obj).instant()
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
unsafe fn _shift(obj_a: *mut PyObject, obj_b: *mut PyObject, negate: bool) -> PyReturn {
    let opname = if negate { '-' } else { '+' };
    debug_assert_eq!(
        PyType_GetModule(Py_TYPE(obj_a)),
        PyType_GetModule(Py_TYPE(obj_b))
    );
    let type_a = Py_TYPE(obj_a);
    let type_b = Py_TYPE(obj_b);
    let &State {
        time_delta_type,
        date_delta_type,
        datetime_delta_type,
        py_api,
        ..
    } = State::for_type(type_a);
    let mut delta = if type_b == time_delta_type {
        DateTimeDelta {
            ddelta: DateDelta::ZERO,
            tdelta: TimeDelta::extract(obj_b),
        }
    } else if type_b == date_delta_type {
        DateTimeDelta {
            ddelta: DateDelta::extract(obj_b),
            tdelta: TimeDelta::ZERO,
        }
    } else if type_b == datetime_delta_type {
        DateTimeDelta::extract(obj_b)
    } else {
        // We don't need to return NotImplemented here, as we know
        // which types within the module are supported.
        Err(type_err!(
            "unsupported operand type(s) for {}: 'LocalSystemDateTime' and {}",
            opname,
            type_b.cast::<PyObject>().repr()
        ))?
    };
    debug_assert_eq!(type_a, State::for_type(type_a).local_datetime_type);
    let odt = OffsetDateTime::extract(obj_a);
    if negate {
        delta = -delta;
    }
    let DateTimeDelta { ddelta, tdelta } = delta;
    let date_shifted = if delta.ddelta.is_zero() {
        odt
    } else {
        let DateTime { date, time } = odt
            .without_offset()
            .shift_date(ddelta.months, ddelta.days)
            .ok_or_else(|| value_err!("Result of {} out of range", opname))?;
        OffsetDateTime::from_system_tz(py_api, date, time, Disambiguate::Compatible)?
            // no errors in "compatible" mode
            .unwrap()
    };
    date_shifted
        .to_instant()
        .shift(tdelta.total_nanos())
        .ok_or_else(|| value_err!("Result of {} out of range", opname))?
        .to_system_tz(py_api)?
        .to_obj(type_a)
}

unsafe fn __add__(obj_a: *mut PyObject, obj_b: *mut PyObject) -> PyReturn {
    if PyType_GetModule(Py_TYPE(obj_a)) == PyType_GetModule(Py_TYPE(obj_b)) {
        _shift(obj_a, obj_b, false)
    } else {
        Ok(newref(Py_NotImplemented()))
    }
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
            let inst_b = if type_b == State::for_mod(mod_a).utc_datetime_type {
                Instant::extract(obj_b)
            } else if type_b == State::for_mod(mod_a).zoned_datetime_type {
                ZonedDateTime::extract(obj_b).instant()
            } else if type_b == State::for_mod(mod_a).offset_datetime_type {
                OffsetDateTime::extract(obj_b).to_instant()
            } else {
                return _shift(obj_a, obj_b, true);
            };
            debug_assert_eq!(type_a, State::for_type(type_a).local_datetime_type);
            (OffsetDateTime::extract(obj_a).to_instant(), inst_b)
        } else {
            return Ok(newref(Py_NotImplemented()));
        }
    };
    TimeDelta::from_nanos_unchecked(inst_a.total_nanos() - inst_b.total_nanos())
        .to_obj(State::for_type(type_a).time_delta_type)
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
        pfunc: c"A datetime type in the local system timezone".as_ptr() as *mut c_void,
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
        pfunc: generic_dealloc as *mut c_void,
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
        Err(type_err!(
            "Argument must be same type, got {}",
            obj_b.repr()
        ))
    }
}

pub(crate) unsafe fn unpickle(module: *mut PyObject, arg: *mut PyObject) -> PyReturn {
    let mut packed = arg.to_bytes()?.ok_or_type_err("Invalid pickle data")?;
    if packed.len() != 15 {
        Err(value_err!("Invalid pickle data"))?
    }
    OffsetDateTime::new_unchecked(
        Date {
            year: unpack_one!(packed, u16),
            month: unpack_one!(packed, u8),
            day: unpack_one!(packed, u8),
        },
        Time {
            hour: unpack_one!(packed, u8),
            minute: unpack_one!(packed, u8),
            second: unpack_one!(packed, u8),
            nanos: unpack_one!(packed, u32),
        },
        unpack_one!(packed, i32),
    )
    .to_obj(State::for_mod(module).local_datetime_type)
}

unsafe fn py_datetime(slf: *mut PyObject, _: *mut PyObject) -> PyReturn {
    OffsetDateTime::extract(slf).to_py(State::for_obj(slf).py_api)
}

unsafe fn date(slf: *mut PyObject, _: *mut PyObject) -> PyReturn {
    OffsetDateTime::extract(slf)
        .date()
        .to_obj(State::for_obj(slf).date_type)
}

unsafe fn time(slf: *mut PyObject, _: *mut PyObject) -> PyReturn {
    OffsetDateTime::extract(slf)
        .time()
        .to_obj(State::for_obj(slf).time_type)
}

unsafe fn replace_date(
    slf: *mut PyObject,
    cls: *mut PyTypeObject,
    args: &[*mut PyObject],
    kwargs: &[(*mut PyObject, *mut PyObject)],
) -> PyReturn {
    let &State {
        date_type,
        py_api,
        str_disambiguate,
        exc_skipped,
        exc_ambiguous,
        ..
    } = State::for_obj(slf);

    if args.len() != 1 {
        Err(type_err!(
            "replace_date() takes 1 positional argument but {} were given",
            args.len()
        ))?
    }

    let dis = Disambiguate::from_only_kwarg(kwargs, str_disambiguate, "replace_date")?;
    if Py_TYPE(args[0]) == date_type {
        match OffsetDateTime::from_system_tz(
            py_api,
            Date::extract(args[0]),
            OffsetDateTime::extract(slf).time(),
            dis,
        )? {
            Ok(d) => d.to_obj(cls),
            Err(Ambiguity::Fold) => Err(py_err!(
                exc_ambiguous,
                "The new datetime is ambiguous in the current timezone"
            )),
            Err(Ambiguity::Gap) => Err(py_err!(
                exc_skipped,
                "The new datetime is skipped in the current timezone"
            )),
        }
    } else {
        Err(type_err!("date must be a Date instance"))
    }
}

unsafe fn replace_time(
    slf: *mut PyObject,
    cls: *mut PyTypeObject,
    args: &[*mut PyObject],
    kwargs: &[(*mut PyObject, *mut PyObject)],
) -> PyReturn {
    let &State {
        time_type,
        py_api,
        str_disambiguate,
        exc_skipped,
        exc_ambiguous,
        ..
    } = State::for_obj(slf);

    if args.len() != 1 {
        return Err(type_err!(
            "replace_time() takes 1 positional argument but {} were given",
            args.len()
        ));
    }

    let dis = Disambiguate::from_only_kwarg(kwargs, str_disambiguate, "replace_time")?;
    if Py_TYPE(args[0]) == time_type {
        match OffsetDateTime::from_system_tz(
            py_api,
            OffsetDateTime::extract(slf).date(),
            Time::extract(args[0]),
            dis,
        )? {
            Ok(d) => d.to_obj(cls),
            Err(Ambiguity::Fold) => Err(py_err!(
                exc_ambiguous,
                "The new datetime is ambiguous in the current timezone"
            )),
            Err(Ambiguity::Gap) => Err(py_err!(
                exc_skipped,
                "The new datetime is skipped in the current timezone"
            )),
        }
    } else {
        Err(type_err!("time must be a Time instance"))
    }
}

unsafe fn format_common_iso(slf: *mut PyObject, _: *mut PyObject) -> PyReturn {
    __str__(slf)
}

unsafe fn replace(
    slf: *mut PyObject,
    cls: *mut PyTypeObject,
    args: &[*mut PyObject],
    kwargs: &[(*mut PyObject, *mut PyObject)],
) -> PyReturn {
    if !args.is_empty() {
        Err(type_err!("replace() takes no positional arguments"))?
    }
    let state = State::for_type(cls);
    let (date, time, _) = OffsetDateTime::extract(slf).as_tuple();
    let mut year = date.year.into();
    let mut month = date.month.into();
    let mut day = date.day.into();
    let mut hour = time.hour.into();
    let mut minute = time.minute.into();
    let mut second = time.second.into();
    let mut nanos = time.nanos as _;
    let mut dis = Disambiguate::Raise;

    for &(name, value) in kwargs {
        if name == state.str_disambiguate {
            dis = Disambiguate::from_py(value)?;
        } else {
            set_components_from_kwargs(
                name,
                value,
                &mut year,
                &mut month,
                &mut day,
                &mut hour,
                &mut minute,
                &mut second,
                &mut nanos,
                state,
                "replace",
            )?;
        }
    }
    let date = Date::from_longs(year, month, day).ok_or_value_err("Invalid date")?;
    let time = Time::from_longs(hour, minute, second, nanos).ok_or_value_err("Invalid time")?;
    OffsetDateTime::from_system_tz(state.py_api, date, time, dis)?
        .map_err(|e| match e {
            Ambiguity::Fold => py_err!(
                state.exc_ambiguous,
                "{} {} is ambiguous in the system timezone",
                date,
                time
            ),
            Ambiguity::Gap => py_err!(
                state.exc_skipped,
                "{} {} is skipped in the system timezone",
                date,
                time
            ),
        })?
        .to_obj(cls)
}

unsafe fn now(cls: *mut PyObject, _: *mut PyObject) -> PyReturn {
    let &State { py_api, .. } = State::for_type(cls.cast());
    let (timestamp, nanos) = match SystemTime::now().duration_since(SystemTime::UNIX_EPOCH) {
        Ok(dur) => (dur.as_secs(), dur.subsec_nanos()),
        _ => Err(py_err!(PyExc_OSError, "SystemTime before UNIX EPOCH"))?,
    };
    // Technically conversion to i128 can overflow, but only if system
    // time is set to a very very very distant future
    let utc_dt = timestamp
        .try_into()
        .ok()
        .and_then(Instant::from_timestamp)
        .ok_or_value_err("timestamp is out of range")?
        .to_py_ignore_nanos(py_api)?;
    defer_decref!(utc_dt);
    let local_dt = methcall0(utc_dt, "astimezone")?;
    defer_decref!(local_dt);
    OffsetDateTime::from_py_and_nanos_unchecked(local_dt, nanos)?.to_obj(cls.cast())
}

unsafe fn from_py_datetime(cls: *mut PyObject, dt: *mut PyObject) -> PyReturn {
    if PyDateTime_Check(dt) == 0 {
        Err(type_err!("Argument must be a datetime.datetime instance"))?
    }
    OffsetDateTime::from_py(dt, State::for_type(cls.cast()))?
        .ok_or_else(|| {
            value_err!(
                "Argument must have a `datetime.timezone` tzinfo and be within range, got {}",
                dt.repr()
            )
        })?
        .to_obj(cls.cast())
}

unsafe fn __reduce__(slf: *mut PyObject, _: *mut PyObject) -> PyReturn {
    let (
        Date { year, month, day },
        Time {
            hour,
            minute,
            second,
            nanos,
            ..
        },
        offset_secs,
    ) = OffsetDateTime::extract(slf).as_tuple();
    let data = pack![year, month, day, hour, minute, second, nanos, offset_secs];
    (
        State::for_obj(slf).unpickle_local_datetime,
        steal!((steal!(data.to_py()?),).to_py()?),
    )
        .to_py()
}

unsafe fn from_timestamp(cls: *mut PyObject, arg: *mut PyObject) -> PyReturn {
    Instant::from_timestamp(
        arg.to_i64()?
            .ok_or_type_err("argument must be an integer")?,
    )
    .ok_or_value_err("timestamp is out of range")
    .and_then(|inst| inst.to_system_tz(State::for_type(cls.cast()).py_api))?
    .to_obj(cls.cast())
}

unsafe fn from_timestamp_millis(cls: *mut PyObject, arg: *mut PyObject) -> PyReturn {
    Instant::from_timestamp_millis(
        arg.to_i64()?
            .ok_or_type_err("timestamp must be an integer")?,
    )
    .ok_or_value_err("timestamp is out of range")
    .and_then(|inst| inst.to_system_tz(State::for_type(cls.cast()).py_api))?
    .to_obj(cls.cast())
}

unsafe fn from_timestamp_nanos(cls: *mut PyObject, arg: *mut PyObject) -> PyReturn {
    Instant::from_timestamp_nanos(
        arg.to_i128()?
            .ok_or_type_err("timestamp must be an integer")?,
    )
    .ok_or_value_err("timestamp is out of range")
    .and_then(|inst| inst.to_system_tz(State::for_type(cls.cast()).py_api))?
    .to_obj(cls.cast())
}

unsafe fn parse_common_iso(cls: *mut PyObject, s_obj: *mut PyObject) -> PyReturn {
    OffsetDateTime::parse(
        s_obj
            .to_utf8()?
            .ok_or_type_err("argument must be a string")?,
    )
    .ok_or_else(|| value_err!("Invalid format: {}", s_obj.repr()))?
    .to_obj(cls.cast())
}

unsafe fn to_utc(slf: *mut PyObject, _: *mut PyObject) -> PyReturn {
    OffsetDateTime::extract(slf)
        .to_instant()
        .to_obj(State::for_obj(slf).utc_datetime_type)
}

unsafe fn to_fixed_offset(slf_obj: *mut PyObject, args: &[*mut PyObject]) -> PyReturn {
    let slf = OffsetDateTime::extract(slf_obj);
    match args {
        &[] => {
            let &State {
                offset_datetime_type,
                ..
            } = State::for_obj(slf_obj);
            slf.to_obj(offset_datetime_type)
        }
        &[arg] => {
            let &State {
                offset_datetime_type,
                time_delta_type,
                ..
            } = State::for_obj(slf_obj);
            let offset_secs = offset_datetime::extract_offset(arg, time_delta_type)?;
            slf.to_instant()
                .to_offset(offset_secs)
                .ok_or_value_err("Resulting local date out of range")?
                .to_obj(offset_datetime_type)
        }
        _ => Err(type_err!("to_fixed_offset() takes at most 1 argument")),
    }
}

unsafe fn to_tz(slf: *mut PyObject, tz: *mut PyObject) -> PyReturn {
    let &State {
        zoneinfo_type,
        py_api,
        zoned_datetime_type,
        ..
    } = State::for_obj(slf);
    let zoneinfo = call1(zoneinfo_type, tz)?;
    defer_decref!(zoneinfo);
    OffsetDateTime::extract(slf)
        .to_instant()
        .to_tz(py_api, zoneinfo)?
        .to_obj(zoned_datetime_type)
}

// TODO: rename
unsafe fn to_local_system(slf: *mut PyObject, _: *mut PyObject) -> PyReturn {
    let cls = Py_TYPE(slf);
    OffsetDateTime::extract(slf)
        .to_system_tz(State::for_type(cls).py_api)?
        .to_obj(cls)
}

unsafe fn add(
    slf: *mut PyObject,
    cls: *mut PyTypeObject,
    args: &[*mut PyObject],
    kwargs: &[(*mut PyObject, *mut PyObject)],
) -> PyReturn {
    _shift_method(slf, cls, args, kwargs, false, "add")
}

unsafe fn subtract(
    slf: *mut PyObject,
    cls: *mut PyTypeObject,
    args: &[*mut PyObject],
    kwargs: &[(*mut PyObject, *mut PyObject)],
) -> PyReturn {
    _shift_method(slf, cls, args, kwargs, true, "subtract")
}

#[inline]
unsafe fn _shift_method(
    slf: *mut PyObject,
    cls: *mut PyTypeObject,
    args: &[*mut PyObject],
    kwargs: &[(*mut PyObject, *mut PyObject)],
    negate: bool,
    fname: &str,
) -> PyReturn {
    if !args.is_empty() {
        return Err(type_err!("{}() takes no positional arguments", fname));
    }
    let state = State::for_type(cls);
    let mut dis = Disambiguate::Raise;
    let mut months = 0;
    let mut days = 0;
    let mut nanos = 0;
    for &(key, value) in kwargs {
        if key == state.str_disambiguate {
            dis = Disambiguate::from_py(value)?;
        } else {
            set_units_from_kwargs(key, value, &mut months, &mut days, &mut nanos, state, fname)?;
        }
    }
    if negate {
        months = -months;
        days = -days;
        nanos = -nanos;
    }
    // First, shift the calendar units
    let odt = if months != 0 || days != 0 {
        let odt = OffsetDateTime::extract(slf);
        OffsetDateTime::from_system_tz(
            state.py_api,
            odt.date()
                .shift(0, months, days)
                .ok_or_value_err("Resulting date is out of range")?,
            odt.time(),
            dis,
        )?
        .map_err(|amb| match amb {
            Ambiguity::Fold => py_err!(
                state.exc_ambiguous,
                "The resulting datetime is ambiguous in the system timezone"
            ),
            Ambiguity::Gap => py_err!(
                state.exc_skipped,
                "The resulting datetime is skipped in the system timezone"
            ),
        })?
    } else {
        OffsetDateTime::extract(slf)
    };

    odt.to_instant()
        .shift(nanos)
        .ok_or_value_err("Result is out of range")?
        .to_system_tz(state.py_api)?
        .to_obj(cls)
}

static mut METHODS: &[PyMethodDef] = &[
    // FUTURE: get docstrings from Python implementation
    method!(identity2 named "__copy__", ""),
    method!(identity2 named "__deepcopy__", "", METH_O),
    method!(to_tz, "Convert to a `ZonedDateTime` with given tz", METH_O),
    method!(exact_eq, "Exact equality", METH_O),
    method!(py_datetime, "Convert to a `datetime.datetime`"),
    method!(to_utc, "Convert to a `UTCDateTime`"),
    method!(date, "The date component"),
    method!(time, "The time component"),
    method!(
        format_common_iso,
        "Format according to the common ISO8601 style"
    ),
    method!(
        parse_common_iso,
        "Create a new instance from the common ISO8601 style",
        METH_O | METH_CLASS
    ),
    method!(to_local_system, "Convert to the local system timezone"),
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
        to_fixed_offset,
        "Return an equivalent instance with the given offset"
    ),
    method_kwargs!(replace_date, "Return a new instance with the date replaced"),
    method_kwargs!(replace_time, "Return a new instance with the time replaced"),
    method_kwargs!(add, "Return a new instance with the given time units added"),
    method_kwargs!(
        subtract,
        "Return a new instance with the given time units subtracted"
    ),
    PyMethodDef::zeroed(),
];

unsafe fn get_year(slf: *mut PyObject) -> PyReturn {
    OffsetDateTime::extract(slf).date().year.to_py()
}

unsafe fn get_month(slf: *mut PyObject) -> PyReturn {
    OffsetDateTime::extract(slf).date().month.to_py()
}

unsafe fn get_day(slf: *mut PyObject) -> PyReturn {
    OffsetDateTime::extract(slf).date().day.to_py()
}

unsafe fn get_hour(slf: *mut PyObject) -> PyReturn {
    OffsetDateTime::extract(slf).time().hour.to_py()
}

unsafe fn get_minute(slf: *mut PyObject) -> PyReturn {
    OffsetDateTime::extract(slf).time().minute.to_py()
}

unsafe fn get_second(slf: *mut PyObject) -> PyReturn {
    OffsetDateTime::extract(slf).time().second.to_py()
}

unsafe fn get_nanos(slf: *mut PyObject) -> PyReturn {
    OffsetDateTime::extract(slf).time().nanos.to_py()
}

unsafe fn get_offset(slf: *mut PyObject) -> PyReturn {
    TimeDelta::from_secs_unchecked(OffsetDateTime::extract(slf).offset_secs() as i64)
        .to_obj(State::for_obj(slf).time_delta_type)
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

type LocalSystemDateTime = OffsetDateTime;
type_spec!(LocalSystemDateTime, SLOTS);
