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
    data: OffsetDateTime,
}

pub(crate) const SINGLETONS: [(&str, OffsetDateTime); 0] = [];

impl OffsetDateTime {
    pub(crate) unsafe fn extract(obj: *mut PyObject) -> Self {
        (*obj.cast::<PyOffsetDateTime>()).data
    }

    pub(crate) const fn to_instant(self) -> Instant {
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
        self,
        &PyDateTime_CAPI {
            DateTime_FromDateAndTime,
            DateTimeType,
            TimeZone_FromTimeZone,
            Delta_FromDelta,
            DeltaType,
            ..
        }: &PyDateTime_CAPI,
    ) -> PyReturn {
        let OffsetDateTime {
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
        defer_decref!(tz);
        DateTime_FromDateAndTime(
            year.into(),
            month.into(),
            day.into(),
            hour.into(),
            minute.into(),
            second.into(),
            (nanos / 1_000) as _,
            tz,
            DateTimeType,
        )
        .as_result()
    }

    pub(crate) unsafe fn from_py(dt: *mut PyObject, state: &State) -> PyResult<Option<Self>> {
        // TODO: a debug assert that it's already a datetime.datetime
        let tzinfo = PyDateTime_DATE_GET_TZINFO(dt);
        Ok(
            match PyObject_IsInstance(tzinfo, state.timezone_type.cast()) {
                1 => Some(OffsetDateTime {
                    // TODO: this can lead to values that can't be converted to UTC?
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
                    offset_secs: offset_from_py_dt(dt)?,
                }),
                0 => None,
                _ => Err(PyErrOccurred())?,
            },
        )
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

unsafe fn __new__(cls: *mut PyTypeObject, args: *mut PyObject, kwargs: *mut PyObject) -> PyReturn {
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
        Err(PyErrOccurred())?
    }

    let offset_secs = extract_offset(offset, State::for_type(cls).time_delta_type)?;

    // TODO: Stricter date validation due to offset?
    let date = Date::from_longs(year, month, day).ok_or_else(|| value_error!("Invalid date"))?;
    let time = Time::from_longs(hour, minute, second, nanos)
        .ok_or_else(|| value_error!("Invalid time"))?;
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
        Err(type_error!("offset argument is required"))
    } else if PyLong_Check(obj) != 0 {
        let given_int = obj
            .to_i64()?
            // We've checked before that it's a py int
            .unwrap();
        if given_int.abs() >= 24 {
            Err(value_error!("offset must be between -24 and 24 hours"))
        } else {
            Ok((given_int * 3600) as _)
        }
    } else if Py_TYPE(obj) == tdelta_cls {
        let td = TimeDelta::extract(obj);
        if td.subsec_nanos() != 0 {
            Err(value_error!("offset must be a whole number of seconds"))
        } else if td.whole_seconds().abs() >= 24 * 3600 {
            Err(value_error!("offset must be between -24 and 24 hours"))
        } else {
            Ok(td.whole_seconds() as _)
        }
    } else {
        Err(type_error!(
            "offset must be an integer or TimeDelta instance, got %R",
            obj
        ))
    }
}

pub(crate) unsafe fn new_unchecked(type_: *mut PyTypeObject, dt: OffsetDateTime) -> PyReturn {
    let f: allocfunc = (*type_).tp_alloc.expect("tp_alloc is not set");
    let slf = f(type_, 0).cast::<PyOffsetDateTime>();
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
        "OffsetDateTime({} {}{})",
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
    let inst_a = OffsetDateTime::extract(a_obj).to_instant();
    let inst_b = if type_b == type_a {
        OffsetDateTime::extract(b_obj).to_instant()
    } else if type_b == State::for_type(type_a).utc_datetime_type {
        Instant::extract(b_obj)
    } else if type_b == State::for_type(type_a).zoned_datetime_type {
        ZonedDateTime::extract(b_obj).to_instant()
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

pub(crate) unsafe extern "C" fn __hash__(slf: *mut PyObject) -> Py_hash_t {
    OffsetDateTime::extract(slf).to_instant().pyhash()
}

unsafe fn __sub__(obj_a: *mut PyObject, obj_b: *mut PyObject) -> PyReturn {
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
                return Ok(newref(Py_NotImplemented()));
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
    slotmethod!(Py_nb_subtract, __sub__, 2),
    PyType_Slot {
        slot: Py_tp_doc,
        pfunc: "A datetime type with IANA tz ID\0".as_ptr() as *mut c_void,
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

unsafe fn exact_eq(obj_a: *mut PyObject, obj_b: *mut PyObject) -> PyReturn {
    if Py_TYPE(obj_a) == Py_TYPE(obj_b) {
        (OffsetDateTime::extract(obj_a) == OffsetDateTime::extract(obj_b)).to_py()
    } else {
        Err(type_error!("Can't compare different types"))
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
        Err(value_error!("Invalid pickle data"))?;
    }
    let mut packed = args[0]
        .to_bytes()?
        .ok_or_else(|| type_error!("Invalid pickle data"))?;
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
    if !packed.is_empty() {
        Err(value_error!("Invalid pickle data"))?;
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

unsafe fn with_time(slf: *mut PyObject, arg: *mut PyObject) -> PyReturn {
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
        str_offset,
        time_delta_type,
        ..
    } = State::for_type(cls);
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
    let mut offset_secs = offset_secs;

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
        } else if name == str_offset {
            offset_secs = extract_offset(value, time_delta_type)?
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
    new_unchecked(
        cls,
        OffsetDateTime {
            date,
            time,
            offset_secs,
        },
    )
}

unsafe fn now(cls: *mut PyObject, offset: *mut PyObject) -> PyReturn {
    let nanos = match SystemTime::now().duration_since(SystemTime::UNIX_EPOCH) {
        Ok(dur) => dur.as_nanos(),
        _ => Err(py_error!(PyExc_OSError, "SystemTime before UNIX EPOCH"))?,
    };
    let offset_secs = extract_offset(offset, State::for_type(cls.cast()).time_delta_type)?;
    // Technically conversion to i128 can overflow, but only if system
    // time is set to a very very very distant future
    let DateTime { date, time } = Instant::from_timestamp_nanos(nanos as i128)
        .ok_or_else(|| py_error!(PyExc_ValueError, "SystemTime out of range"))?
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

unsafe fn from_py_datetime(cls: *mut PyObject, dt: *mut PyObject) -> PyReturn {
    if PyDateTime_Check(dt) == 0 {
        Err(type_error!("Argument must be a datetime.datetime instance"))?
    }
    new_unchecked(
        cls.cast(),
        match OffsetDateTime::from_py(dt, State::for_type(cls.cast()))? {
            Some(odt) => odt,
            None => Err(value_error!("Argument must have a timezone, got: %R", dt))?,
        },
    )
}

pub(crate) unsafe fn naive(slf: *mut PyObject, _: *mut PyObject) -> PyReturn {
    let OffsetDateTime { date, time, .. } = OffsetDateTime::extract(slf);
    naive_datetime::new_unchecked(
        State::for_obj(slf).naive_datetime_type,
        DateTime { date, time },
    )
}

pub(crate) unsafe fn timestamp(slf: *mut PyObject, _: *mut PyObject) -> PyReturn {
    OffsetDateTime::extract(slf)
        .to_instant()
        .timestamp()
        .to_py()
}

pub(crate) unsafe fn timestamp_millis(slf: *mut PyObject, _: *mut PyObject) -> PyReturn {
    OffsetDateTime::extract(slf)
        .to_instant()
        .timestamp_millis()
        .to_py()
}

pub(crate) unsafe fn timestamp_nanos(slf: *mut PyObject, _: *mut PyObject) -> PyReturn {
    OffsetDateTime::extract(slf)
        .to_instant()
        .timestamp_nanos()
        .to_py()
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
        State::for_obj(slf).unpickle_offset_datetime,
        steal!(PyTuple_Pack(
            1,
            steal!(pack![year, month, day, hour, minute, second, nanos, offset_secs].to_py()?),
        )
        .as_result()?),
    )
    .as_result()
}

// checks the args comply with (ts: ?, /, *, offset: ?)
unsafe fn check_from_timestamp_args_return_offset(
    args: &[*mut PyObject],
    kwargs: &[(*mut PyObject, *mut PyObject)],
    &State {
        str_offset,
        time_delta_type,
        ..
    }: &State,
) -> PyResult<i32> {
    if args.len() != 1 {
        Err(type_error!(
            "from_timestamp() takes 1 positional argument but %lld were given",
            args.len()
        ))
    } else if kwargs.len() != 1 {
        Err(type_error!(
            "from_timestamp() expected 2 arguments, got %lld",
            kwargs.len() + 1
        ))
    } else if kwargs[0].0 == str_offset {
        extract_offset(kwargs[0].1, time_delta_type)
    } else {
        Err(type_error!(
            "from_timestamp() got an unexpected keyword argument %R",
            kwargs[0].0
        ))
    }
}

unsafe fn from_timestamp(
    _: *mut PyObject,
    cls: *mut PyTypeObject,
    args: &[*mut PyObject],
    kwargs: &[(*mut PyObject, *mut PyObject)],
) -> PyReturn {
    let state = State::for_type(cls);
    let offset_secs = check_from_timestamp_args_return_offset(args, kwargs, state)?;
    let DateTime { date, time } = Instant::from_timestamp(
        args[0]
            .to_i64()?
            .ok_or_else(|| value_error!("timestamp must be an integer"))?,
    )
    .ok_or_else(|| value_error!("timestamp is out of range"))?
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

unsafe fn from_timestamp_millis(
    _: *mut PyObject,
    cls: *mut PyTypeObject,
    args: &[*mut PyObject],
    kwargs: &[(*mut PyObject, *mut PyObject)],
) -> PyReturn {
    let state = State::for_type(cls);
    let offset_secs = check_from_timestamp_args_return_offset(args, kwargs, state)?;
    let DateTime { date, time } = Instant::from_timestamp_millis(
        args[0]
            .to_i64()?
            .ok_or_else(|| value_error!("timestamp must be an integer"))?,
    )
    .ok_or_else(|| value_error!("timestamp is out of range"))?
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

unsafe fn from_timestamp_nanos(
    _: *mut PyObject,
    cls: *mut PyTypeObject,
    args: &[*mut PyObject],
    kwargs: &[(*mut PyObject, *mut PyObject)],
) -> PyReturn {
    let state = State::for_type(cls);
    let offset_secs = check_from_timestamp_args_return_offset(args, kwargs, state)?;
    let DateTime { date, time } = Instant::from_timestamp_nanos(
        args[0]
            .to_i128()?
            .ok_or_else(|| value_error!("timestamp must be an integer"))?,
    )
    .ok_or_else(|| value_error!("timestamp is out of range"))?
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
    let sign = match s.first() {
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

unsafe fn from_default_format(cls: *mut PyObject, s_obj: *mut PyObject) -> PyReturn {
    new_unchecked(
        cls.cast(),
        OffsetDateTime::parse(
            s_obj
                .to_utf8()?
                .ok_or_else(|| type_error!("Expected a string"))?,
        )
        .ok_or_else(|| value_error!("Invalid format: %R", s_obj))?,
    )
}

// exactly "+HH:MM" or "Z"
fn parse_hm_offset(s: &[u8]) -> Option<i32> {
    let sign = match s.first() {
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
        None
    }
}

unsafe fn from_rfc3339(cls: *mut PyObject, s_obj: *mut PyObject) -> PyReturn {
    let s = &mut s_obj
        .to_utf8()?
        .ok_or_else(|| type_error!("Expected a string"))?;
    // at least: "YYYY-MM-DDTHH:MM:SSZ"
    if s.len() < 20 {
        Err(value_error!("Invalid RFC3339 format: %R", s_obj))?
    }
    let date =
        Date::parse_partial(s).ok_or_else(|| value_error!("Invalid RFC3339 format: %R", s_obj))?;
    // parse the separator
    if !(s[0] == b'T' || s[0] == b't' || s[0] == b' ' || s[0] == b'_') {
        Err(value_error!("Invalid RFC3339 format: %R", s_obj))?
    }
    *s = &s[1..];
    let time =
        Time::parse_partial(s).ok_or_else(|| value_error!("Invalid RFC3339 format: %R", s_obj))?;
    let offset_secs =
        parse_hm_offset(s).ok_or_else(|| value_error!("Invalid RFC3339 format: %R", s_obj))?;
    new_unchecked(
        cls.cast(),
        OffsetDateTime {
            date,
            time,
            offset_secs,
        },
    )
}

unsafe fn in_fixed_offset(slf_obj: *mut PyObject, args: &[*mut PyObject]) -> PyReturn {
    if args.is_empty() {
        return Ok(newref(slf_obj));
    } else if args.len() > 1 {
        Err(type_error!("in_fixed_offset() takes at most 1 argument"))?;
    }
    let cls = Py_TYPE(slf_obj);
    let slf = OffsetDateTime::extract(slf_obj);
    let offset_secs = extract_offset(args[0], State::for_type(cls).time_delta_type)?;
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

unsafe fn in_local_system(slf: *mut PyObject, _: *mut PyObject) -> PyReturn {
    let &State {
        datetime_api: py_api,
        local_datetime_type,
        ..
    } = State::for_obj(slf);
    local_datetime::new_unchecked(
        local_datetime_type,
        OffsetDateTime::extract(slf).to_local_system(py_api)?,
    )
}

unsafe fn strptime(cls: *mut PyObject, args: &[*mut PyObject]) -> PyReturn {
    let state = State::for_type(cls.cast());
    if args.len() != 2 {
        Err(type_error!("strptime() takes exactly 2 arguments"))?;
    }
    // OPTIMIZE: get this working with vectorcall
    let parsed = PyObject_Call(
        state.strptime,
        steal!(PyTuple_Pack(2, args[0], args[1]).as_result()?),
        NULL(),
    )
    .as_result()?;
    defer_decref!(parsed);

    new_unchecked(
        cls.cast(),
        match OffsetDateTime::from_py(parsed, state)? {
            Some(dt) => dt,
            None => Err(value_error!(
                "parsed datetime must have a timezone, got %R",
                parsed
            ))?,
        },
    )
}

pub(crate) fn offset_fmt_rfc3339(secs: i32) -> String {
    let (sign, secs) = if secs < 0 { ('-', -secs) } else { ('+', secs) };
    format!("{}{:02}:{:02}", sign, secs / 3600, (secs % 3600) / 60)
}

unsafe fn rfc3339(slf: *mut PyObject, _: *mut PyObject) -> PyReturn {
    let OffsetDateTime {
        date,
        time,
        offset_secs,
    } = OffsetDateTime::extract(slf);
    format!("{} {}{}", date, time, offset_fmt_rfc3339(offset_secs)).to_py()
}

unsafe fn common_iso8601(slf: *mut PyObject, _: *mut PyObject) -> PyReturn {
    let OffsetDateTime {
        date,
        time,
        offset_secs,
    } = OffsetDateTime::extract(slf);
    format!("{}T{}{}", date, time, offset_fmt(offset_secs)).to_py()
}

unsafe fn rfc2822(slf: *mut PyObject, _: *mut PyObject) -> PyReturn {
    let &State {
        format_rfc2822,
        datetime_api,
        ..
    } = State::for_obj(slf);
    PyObject_CallOneArg(
        format_rfc2822,
        OffsetDateTime::extract(slf).to_py(datetime_api)?,
    )
    .as_result()
}

unsafe fn from_rfc2822(cls: *mut PyObject, s_obj: *mut PyObject) -> PyReturn {
    let state = State::for_type(cls.cast());
    let py_dt = PyObject_CallOneArg(state.parse_rfc2822, s_obj).as_result()?;
    defer_decref!(py_dt);
    new_unchecked(
        cls.cast(),
        match OffsetDateTime::from_py(py_dt, state)? {
            Some(dt) => dt,
            None => Err(value_error!(
                "parsed datetime must have a timezone, got %R",
                s_obj
            ))?,
        },
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
    method!(in_local_system, "Convert to a datetime in the local system"),
    method!(date, "The date component"),
    method!(time, "The time component"),
    method!(default_format, "Format in the default way"),
    method!(from_default_format, "", METH_O | METH_CLASS),
    method!(rfc3339, "Format according to RFC3339"),
    method!(
        from_rfc3339,
        "Create a new instance from an RFC3339 timestamp",
        METH_O | METH_CLASS
    ),
    method!(rfc2822, "Format according to RFC2822"),
    method!(
        from_rfc2822,
        "Create a new instance from an RFC2822 timestamp",
        METH_O | METH_CLASS
    ),
    method!(
        common_iso8601,
        "Format according to the common ISO8601 style"
    ),
    method!(from_default_format named "from_common_iso8601", "", METH_O | METH_CLASS),
    method!(__reduce__, ""),
    method!(
        now,
        "Create a new instance representing the current time",
        METH_O | METH_CLASS
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
    method_kwargs!(
        from_timestamp,
        "Create a new instance from a UNIX timestamp",
        METH_CLASS
    ),
    method_kwargs!(
        from_timestamp_millis,
        "Create a new instance from a UNIX timestamp in milliseconds",
        METH_CLASS
    ),
    method_kwargs!(
        from_timestamp_nanos,
        "Create a new instance from a UNIX timestamp",
        METH_CLASS
    ),
    method_kwargs!(
        replace,
        "Return a new instance with the specified fields replaced"
    ),
    method_vararg!(
        in_fixed_offset,
        "Convert to a new instance with a different offset"
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
    method_vararg!(strptime, "Parse a string with strptime", METH_CLASS),
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
    name: c_str!("whenever.OffsetDateTime"),
    basicsize: mem::size_of::<PyOffsetDateTime>() as _,
    itemsize: 0,
    flags: Py_TPFLAGS_DEFAULT as _,
    slots: unsafe { SLOTS as *const [_] as *mut _ },
};
