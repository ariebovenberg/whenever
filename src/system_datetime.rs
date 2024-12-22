use core::ffi::{c_int, c_void, CStr};
use core::{mem, ptr::null_mut as NULL};
use pyo3_ffi::*;

use crate::common::*;
use crate::docstrings as doc;
use crate::{
    date::Date,
    date_delta::DateDelta,
    datetime_delta::set_units_from_kwargs,
    datetime_delta::DateTimeDelta,
    instant::Instant,
    local_datetime::{set_components_from_kwargs, DateTime},
    offset_datetime::{self, local, timestamp, timestamp_millis, timestamp_nanos, OffsetDateTime},
    time::Time,
    time_delta::TimeDelta,
    zoned_datetime::ZonedDateTime,
    State,
};

pub(crate) const SINGLETONS: &[(&CStr, OffsetDateTime); 0] = &[];

impl OffsetDateTime {
    pub(crate) unsafe fn resolve_system_tz(
        py_api: &PyDateTime_CAPI,
        date: Date,
        time: Time,
        dis: Option<Disambiguate>,
        preferred_offset: i32,
        exc_repeated: *mut PyObject,
        exc_skipped: *mut PyObject,
    ) -> PyResult<Self> {
        match dis {
            Some(dis) => Self::resolve_system_tz_using_disambiguate(
                py_api,
                date,
                time,
                dis,
                exc_repeated,
                exc_skipped,
            ),
            None => Self::resolve_system_tz_using_offset(py_api, date, time, preferred_offset),
        }
    }

    pub(crate) unsafe fn resolve_system_tz_using_disambiguate(
        py_api: &PyDateTime_CAPI,
        date: Date,
        time: Time,
        dis: Disambiguate,
        exc_repeated: *mut PyObject,
        exc_skipped: *mut PyObject,
    ) -> PyResult<Self> {
        use OffsetResult::*;
        Ok(match OffsetResult::for_system_tz(py_api, date, time)? {
            Unambiguous(offset_secs) => OffsetDateTime::new_unchecked(date, time, offset_secs),
            Fold(offset0, offset1) => {
                let offset = match dis {
                    Disambiguate::Compatible | Disambiguate::Earlier => offset0,
                    Disambiguate::Later => offset1,
                    Disambiguate::Raise => Err(py_err!(
                        exc_repeated,
                        "{} {} is repeated in the system timezone",
                        date,
                        time
                    ))?,
                };
                OffsetDateTime::new_unchecked(date, time, offset)
            }
            Gap(offset0, offset1) => {
                let (offset_secs, shift) = match dis {
                    Disambiguate::Compatible | Disambiguate::Later => (offset1, offset1 - offset0),
                    Disambiguate::Earlier => (offset0, offset0 - offset1),
                    Disambiguate::Raise => Err(py_err!(
                        exc_skipped,
                        "{} {} is skipped in the system timezone",
                        date,
                        time
                    ))?,
                };
                DateTime { date, time }
                    .small_shift_unchecked(shift)
                    .with_offset_unchecked(offset_secs)
            }
        })
    }

    unsafe fn resolve_system_tz_using_offset(
        py_api: &PyDateTime_CAPI,
        date: Date,
        time: Time,
        offset: i32,
    ) -> PyResult<Self> {
        use OffsetResult::*;
        match OffsetResult::for_system_tz(py_api, date, time)? {
            Unambiguous(offset_secs) => OffsetDateTime::new(date, time, offset_secs),
            Fold(offset0, offset1) => OffsetDateTime::new(
                date,
                time,
                if offset == offset1 { offset1 } else { offset0 },
            ),
            Gap(offset0, offset1) => {
                let (offset_secs, shift) = if offset == offset0 {
                    (offset0, offset0 - offset1)
                } else {
                    (offset1, offset1 - offset0)
                };
                DateTime { date, time }
                    .small_shift_unchecked(shift)
                    .with_offset(offset_secs)
            }
        }
        .ok_or_value_err("Resulting datetime is out of range")
    }

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
                nanos: self.time.nanos,
            },
            offset_from_py_dt(dt_new)?,
        ))
    }

    #[allow(clippy::too_many_arguments)]
    unsafe fn shift_in_system_tz(
        self,
        py_api: &PyDateTime_CAPI,
        months: i32,
        days: i32,
        nanos: i128,
        dis: Option<Disambiguate>,
        exc_repeated: *mut PyObject,
        exc_skipped: *mut PyObject,
    ) -> PyResult<Self> {
        let slf = if months != 0 || days != 0 {
            Self::resolve_system_tz(
                py_api,
                self.date
                    .shift(0, months, days)
                    .ok_or_value_err("Resulting date is out of range")?,
                self.time,
                dis,
                self.offset_secs,
                exc_repeated,
                exc_skipped,
            )?
        } else {
            self
        };
        slf.instant()
            .shift(nanos)
            .ok_or_value_err("Result is out of range")?
            .to_system_tz(py_api)
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
        exc_repeated,
        exc_skipped,
        str_compatible,
        ..
    } = State::for_type(cls);
    let mut year = 0;
    let mut month = 0;
    let mut day = 0;
    let mut hour = 0;
    let mut minute = 0;
    let mut second = 0;
    let mut nanos = 0;
    let mut disambiguate: *mut PyObject = str_compatible;

    // FUTURE: parse them manually, which is more efficient
    if PyArg_ParseTupleAndKeywords(
        args,
        kwargs,
        c"lll|lll$lU:SystemDateTime".as_ptr(),
        arg_vec(&[
            c"year",
            c"month",
            c"day",
            c"hour",
            c"minute",
            c"second",
            c"nanosecond",
            c"disambiguate",
        ])
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
    OffsetDateTime::resolve_system_tz_using_disambiguate(
        py_api,
        date,
        time,
        dis,
        exc_repeated,
        exc_skipped,
    )?
    .to_obj(cls)
}

unsafe fn __repr__(slf: *mut PyObject) -> PyReturn {
    let OffsetDateTime {
        date,
        time,
        offset_secs,
    } = OffsetDateTime::extract(slf);
    format!(
        "SystemDateTime({} {}{})",
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
    let type_a = Py_TYPE(a_obj);
    let type_b = Py_TYPE(b_obj);
    let inst_a = OffsetDateTime::extract(a_obj).instant();
    let inst_b = if type_b == type_a {
        OffsetDateTime::extract(b_obj).instant()
    } else if type_b == State::for_type(type_a).instant_type {
        Instant::extract(b_obj)
    } else if type_b == State::for_type(type_a).zoned_datetime_type {
        ZonedDateTime::extract(b_obj).instant()
    } else if type_b == State::for_type(type_a).offset_datetime_type {
        OffsetDateTime::extract(b_obj).instant()
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
unsafe fn _shift_operator(obj_a: *mut PyObject, obj_b: *mut PyObject, negate: bool) -> PyReturn {
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
        exc_repeated,
        exc_skipped,
        ..
    } = State::for_type(type_a);

    let odt = OffsetDateTime::extract(obj_a);
    let mut months = 0;
    let mut days = 0;
    let mut nanos = 0;

    if type_b == time_delta_type {
        nanos = TimeDelta::extract(obj_b).total_nanos();
    } else if type_b == date_delta_type {
        let dd = DateDelta::extract(obj_b);
        months = dd.months;
        days = dd.days;
    } else if type_b == datetime_delta_type {
        let dtd = DateTimeDelta::extract(obj_b);
        months = dtd.ddelta.months;
        days = dtd.ddelta.days;
        nanos = dtd.tdelta.total_nanos();
    } else {
        return Ok(newref(Py_NotImplemented()));
    };
    if negate {
        months = -months;
        days = -days;
        nanos = -nanos;
    };

    odt.shift_in_system_tz(py_api, months, days, nanos, None, exc_repeated, exc_skipped)?
        .to_obj(type_a)
}

unsafe fn __add__(obj_a: *mut PyObject, obj_b: *mut PyObject) -> PyReturn {
    if PyType_GetModule(Py_TYPE(obj_a)) == PyType_GetModule(Py_TYPE(obj_b)) {
        _shift_operator(obj_a, obj_b, false)
    } else {
        Ok(newref(Py_NotImplemented()))
    }
}

unsafe fn __sub__(obj_a: *mut PyObject, obj_b: *mut PyObject) -> PyReturn {
    let type_a = Py_TYPE(obj_a);
    let type_b = Py_TYPE(obj_b);

    // Easy case: systemDT - systemDT
    let (inst_a, inst_b) = if type_a == type_b {
        (
            OffsetDateTime::extract(obj_a).instant(),
            OffsetDateTime::extract(obj_b).instant(),
        )
    // Other cases are more difficult, as they can be triggered
    // by reflexive operations with arbitrary types.
    // We need to eliminate them carefully.
    } else {
        let mod_a = PyType_GetModule(type_a);
        let mod_b = PyType_GetModule(type_b);
        if mod_a == mod_b {
            let inst_b = if type_b == State::for_mod(mod_a).instant_type {
                Instant::extract(obj_b)
            } else if type_b == State::for_mod(mod_a).zoned_datetime_type {
                ZonedDateTime::extract(obj_b).instant()
            } else if type_b == State::for_mod(mod_a).offset_datetime_type {
                OffsetDateTime::extract(obj_b).instant()
            } else {
                return _shift_operator(obj_a, obj_b, true);
            };
            debug_assert_eq!(type_a, State::for_type(type_a).system_datetime_type);
            (OffsetDateTime::extract(obj_a).instant(), inst_b)
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
        pfunc: doc::SYSTEMDATETIME.as_ptr() as *mut c_void,
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
    .to_obj(State::for_mod(module).system_datetime_type)
}

unsafe fn py_datetime(slf: *mut PyObject, _: *mut PyObject) -> PyReturn {
    OffsetDateTime::extract(slf).to_py(State::for_obj(slf).py_api)
}

unsafe fn date(slf: *mut PyObject, _: *mut PyObject) -> PyReturn {
    OffsetDateTime::extract(slf)
        .date
        .to_obj(State::for_obj(slf).date_type)
}

unsafe fn time(slf: *mut PyObject, _: *mut PyObject) -> PyReturn {
    OffsetDateTime::extract(slf)
        .time
        .to_obj(State::for_obj(slf).time_type)
}

unsafe fn replace_date(
    slf: *mut PyObject,
    cls: *mut PyTypeObject,
    args: &[*mut PyObject],
    kwargs: &mut KwargIter,
) -> PyReturn {
    let &State {
        date_type,
        py_api,
        str_disambiguate,
        exc_skipped,
        exc_repeated,
        ..
    } = State::for_obj(slf);

    let &[arg] = args else {
        Err(type_err!(
            "replace_date() takes 1 positional argument but {} were given",
            args.len()
        ))?
    };

    if Py_TYPE(arg) == date_type {
        let OffsetDateTime {
            time, offset_secs, ..
        } = OffsetDateTime::extract(slf);
        OffsetDateTime::resolve_system_tz(
            py_api,
            Date::extract(arg),
            time,
            Disambiguate::from_only_kwarg(kwargs, str_disambiguate, "replace_date")?,
            offset_secs,
            exc_repeated,
            exc_skipped,
        )?
        .to_obj(cls)
    } else {
        Err(type_err!("date must be a Date instance"))
    }
}

unsafe fn replace_time(
    slf: *mut PyObject,
    cls: *mut PyTypeObject,
    args: &[*mut PyObject],
    kwargs: &mut KwargIter,
) -> PyReturn {
    let &State {
        time_type,
        py_api,
        str_disambiguate,
        exc_skipped,
        exc_repeated,
        ..
    } = State::for_obj(slf);

    let &[arg] = args else {
        Err(type_err!(
            "replace_time() takes 1 positional argument but {} were given",
            args.len()
        ))?
    };

    if Py_TYPE(arg) == time_type {
        let OffsetDateTime {
            date, offset_secs, ..
        } = OffsetDateTime::extract(slf);
        OffsetDateTime::resolve_system_tz(
            py_api,
            date,
            Time::extract(arg),
            Disambiguate::from_only_kwarg(kwargs, str_disambiguate, "replace_time")?,
            offset_secs,
            exc_repeated,
            exc_skipped,
        )?
        .to_obj(cls)
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
    kwargs: &mut KwargIter,
) -> PyReturn {
    if !args.is_empty() {
        Err(type_err!("replace() takes no positional arguments"))?
    }
    let state = State::for_type(cls);
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
    let mut nanos = time.nanos as _;
    let mut dis = None;

    handle_kwargs("replace", kwargs, |key, value, eq| {
        if eq(key, state.str_disambiguate) {
            dis = Some(Disambiguate::from_py(value)?);
            Ok(true)
        } else {
            set_components_from_kwargs(
                key,
                value,
                &mut year,
                &mut month,
                &mut day,
                &mut hour,
                &mut minute,
                &mut second,
                &mut nanos,
                state,
                eq,
            )
        }
    })?;

    let date = Date::from_longs(year, month, day).ok_or_value_err("Invalid date")?;
    let time = Time::from_longs(hour, minute, second, nanos).ok_or_value_err("Invalid time")?;
    OffsetDateTime::resolve_system_tz(
        state.py_api,
        date,
        time,
        dis,
        offset_secs,
        state.exc_repeated,
        state.exc_skipped,
    )?
    .to_obj(cls)
}

unsafe fn now(cls: *mut PyObject, _: *mut PyObject) -> PyReturn {
    let state = State::for_type(cls.cast());
    let (timestamp, nanos) = state.time_ns()?;
    let utc_dt = Instant::from_timestamp(timestamp)
        .ok_or_value_err("timestamp is out of range")?
        .to_py_ignore_nanos(state.py_api)?;
    defer_decref!(utc_dt);
    let dt = methcall0(utc_dt, "astimezone")?;
    defer_decref!(dt);
    OffsetDateTime::from_py_and_nanos_unchecked(dt, nanos)?.to_obj(cls.cast())
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
    let OffsetDateTime {
        date: Date { year, month, day },
        time:
            Time {
                hour,
                minute,
                second,
                nanos,
                ..
            },
        offset_secs,
    } = OffsetDateTime::extract(slf);
    let data = pack![year, month, day, hour, minute, second, nanos, offset_secs];
    (
        State::for_obj(slf).unpickle_system_datetime,
        steal!((steal!(data.to_py()?),).to_py()?),
    )
        .to_py()
}

unsafe fn from_timestamp(cls: *mut PyObject, arg: *mut PyObject) -> PyReturn {
    match arg.to_i64()? {
        Some(ts) => Instant::from_timestamp(ts),
        None => Instant::from_timestamp_f64(
            arg.to_f64()?
                .ok_or_type_err("Timestamp must be an integer or float")?,
        ),
    }
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

unsafe fn instant(slf: *mut PyObject, _: *mut PyObject) -> PyReturn {
    OffsetDateTime::extract(slf)
        .instant()
        .to_obj(State::for_obj(slf).instant_type)
}

unsafe fn to_fixed_offset(slf_obj: *mut PyObject, args: &[*mut PyObject]) -> PyReturn {
    let slf = OffsetDateTime::extract(slf_obj);
    match *args {
        [] => {
            let &State {
                offset_datetime_type,
                ..
            } = State::for_obj(slf_obj);
            slf.to_obj(offset_datetime_type)
        }
        [arg] => {
            let &State {
                offset_datetime_type,
                time_delta_type,
                ..
            } = State::for_obj(slf_obj);
            let offset_secs = offset_datetime::extract_offset(arg, time_delta_type)?;
            slf.instant()
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
        .instant()
        .to_tz(py_api, zoneinfo)?
        .to_obj(zoned_datetime_type)
}

unsafe fn to_system_tz(slf: *mut PyObject, _: *mut PyObject) -> PyReturn {
    let cls = Py_TYPE(slf);
    OffsetDateTime::extract(slf)
        .to_system_tz(State::for_type(cls).py_api)?
        .to_obj(cls)
}

unsafe fn add(
    slf: *mut PyObject,
    cls: *mut PyTypeObject,
    args: &[*mut PyObject],
    kwargs: &mut KwargIter,
) -> PyReturn {
    _shift_method(slf, cls, args, kwargs, false)
}

unsafe fn subtract(
    slf: *mut PyObject,
    cls: *mut PyTypeObject,
    args: &[*mut PyObject],
    kwargs: &mut KwargIter,
) -> PyReturn {
    _shift_method(slf, cls, args, kwargs, true)
}

#[inline]
unsafe fn _shift_method(
    slf: *mut PyObject,
    cls: *mut PyTypeObject,
    args: &[*mut PyObject],
    kwargs: &mut KwargIter,
    negate: bool,
) -> PyReturn {
    let fname = if negate { "subtract" } else { "add" };
    let state = State::for_type(cls);
    let mut dis = None;
    let mut months = 0;
    let mut days = 0;
    let mut nanos = 0;

    match *args {
        [arg] => {
            match kwargs.next() {
                Some((key, value)) if kwargs.len() == 1 && key.kwarg_eq(state.str_disambiguate) => {
                    dis = Some(Disambiguate::from_py(value)?)
                }
                Some(_) => Err(type_err!(
                    "{}() can't mix positional and keyword arguments",
                    fname
                ))?,
                None => {}
            };
            if Py_TYPE(arg) == state.time_delta_type {
                nanos = TimeDelta::extract(arg).total_nanos();
            } else if Py_TYPE(arg) == state.date_delta_type {
                let dd = DateDelta::extract(arg);
                months = dd.months;
                days = dd.days;
            } else if Py_TYPE(arg) == state.datetime_delta_type {
                let dt = DateTimeDelta::extract(arg);
                months = dt.ddelta.months;
                days = dt.ddelta.days;
                nanos = dt.tdelta.total_nanos();
            } else {
                Err(type_err!("{}() argument must be a delta", fname))?
            }
        }
        [] => {
            handle_kwargs(fname, kwargs, |key, value, eq| {
                if eq(key, state.str_disambiguate) {
                    dis = Some(Disambiguate::from_py(value)?);
                    Ok(true)
                } else {
                    set_units_from_kwargs(key, value, &mut months, &mut days, &mut nanos, state, eq)
                }
            })?;
        }
        _ => Err(type_err!(
            "{}() takes at most 1 positional argument, got {}",
            fname,
            args.len()
        ))?,
    }
    if negate {
        months = -months;
        days = -days;
        nanos = -nanos;
    }
    OffsetDateTime::extract(slf)
        .shift_in_system_tz(
            state.py_api,
            months,
            days,
            nanos,
            dis,
            state.exc_repeated,
            state.exc_skipped,
        )?
        .to_obj(cls)
}

unsafe fn difference(obj_a: *mut PyObject, obj_b: *mut PyObject) -> PyReturn {
    let type_b = Py_TYPE(obj_b);
    let type_a = Py_TYPE(obj_a);
    let state = State::for_type(type_a);
    let inst_a = OffsetDateTime::extract(obj_a).instant();
    let inst_b = if type_b == Py_TYPE(obj_a) {
        OffsetDateTime::extract(obj_b).instant()
    } else if type_b == state.instant_type {
        Instant::extract(obj_b)
    } else if type_b == state.zoned_datetime_type {
        ZonedDateTime::extract(obj_b).instant()
    } else if type_b == state.offset_datetime_type {
        OffsetDateTime::extract(obj_b).instant()
    } else {
        Err(type_err!(
            "difference() argument must be an OffsetDateTime,
             Instant, ZonedDateTime, or SystemDateTime"
        ))?
    };
    TimeDelta::from_nanos_unchecked(inst_a.total_nanos() - inst_b.total_nanos())
        .to_obj(state.time_delta_type)
}

static mut METHODS: &[PyMethodDef] = &[
    // FUTURE: get docstrings from Python implementation
    method!(identity2 named "__copy__", c""),
    method!(identity2 named "__deepcopy__", c"", METH_O),
    method!(__reduce__, c""),
    method!(to_tz, doc::KNOWSINSTANT_TO_TZ, METH_O),
    method!(to_system_tz, doc::KNOWSINSTANT_TO_SYSTEM_TZ),
    method_vararg!(to_fixed_offset, doc::KNOWSINSTANT_TO_FIXED_OFFSET),
    method!(exact_eq, doc::KNOWSINSTANT_EXACT_EQ, METH_O),
    method!(py_datetime, doc::BASICCONVERSIONS_PY_DATETIME),
    method!(instant, doc::KNOWSINSTANTANDLOCAL_INSTANT),
    method!(local, doc::KNOWSINSTANTANDLOCAL_LOCAL),
    method!(date, doc::KNOWSLOCAL_DATE),
    method!(time, doc::KNOWSLOCAL_TIME),
    method!(format_common_iso, doc::OFFSETDATETIME_FORMAT_COMMON_ISO),
    method!(
        parse_common_iso,
        doc::SYSTEMDATETIME_PARSE_COMMON_ISO,
        METH_O | METH_CLASS
    ),
    method!(now, doc::SYSTEMDATETIME_NOW, METH_CLASS | METH_NOARGS),
    method!(
        from_py_datetime,
        doc::SYSTEMDATETIME_FROM_PY_DATETIME,
        METH_O | METH_CLASS
    ),
    method!(timestamp, doc::KNOWSINSTANT_TIMESTAMP),
    method!(timestamp_millis, doc::KNOWSINSTANT_TIMESTAMP_MILLIS),
    method!(timestamp_nanos, doc::KNOWSINSTANT_TIMESTAMP_NANOS),
    method!(
        from_timestamp,
        doc::SYSTEMDATETIME_FROM_TIMESTAMP,
        METH_O | METH_CLASS
    ),
    method!(
        from_timestamp_millis,
        doc::SYSTEMDATETIME_FROM_TIMESTAMP_MILLIS,
        METH_O | METH_CLASS
    ),
    method!(
        from_timestamp_nanos,
        doc::SYSTEMDATETIME_FROM_TIMESTAMP_NANOS,
        METH_O | METH_CLASS
    ),
    method_kwargs!(replace, doc::SYSTEMDATETIME_REPLACE),
    method_kwargs!(replace_date, doc::SYSTEMDATETIME_REPLACE_DATE),
    method_kwargs!(replace_time, doc::SYSTEMDATETIME_REPLACE_TIME),
    method_kwargs!(add, doc::SYSTEMDATETIME_ADD),
    method_kwargs!(subtract, doc::SYSTEMDATETIME_SUBTRACT),
    method!(difference, doc::KNOWSINSTANT_DIFFERENCE, METH_O),
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
    TimeDelta::from_secs_unchecked(OffsetDateTime::extract(slf).offset_secs as i64)
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

type SystemDateTime = OffsetDateTime;
type_spec!(SystemDateTime, SLOTS);
