use core::ffi::{c_char, c_int, c_long, c_void};
use core::{mem, ptr, ptr::null_mut as NULL};
use pyo3_ffi::*;
use std::fmt::{self, Display, Formatter};
use std::time::SystemTime;

use crate::common::*;
use crate::{
    date::{self, Date},
    date_delta::DateDelta,
    local_datetime,
    naive_datetime::{self, DateTime},
    offset_datetime::{self, OffsetDateTime},
    time::{self, Time},
    time_delta::{self, TimeDelta},
    utc_datetime::{self, Instant},
    State,
};

#[derive(Debug, Eq, PartialEq, Ord, PartialOrd, Copy, Clone)]
pub(crate) struct ZonedDateTime {
    pub(crate) date: Date,
    pub(crate) time: Time,
    pub(crate) offset_secs: i32, // the offset is already priced into the date and time
    pub(crate) zoneinfo: *mut PyObject,
}

#[repr(C)]
pub(crate) struct PyZonedDateTime {
    _ob_base: PyObject,
    data: ZonedDateTime,
}

pub(crate) const SINGLETONS: [(&str, ZonedDateTime); 0] = [];

impl ZonedDateTime {
    pub(crate) unsafe fn extract(obj: *mut PyObject) -> Self {
        (*obj.cast::<PyZonedDateTime>()).data
    }

    pub(crate) unsafe fn from_local(
        py_api: &PyDateTime_CAPI,
        date: Date,
        time: Time,
        zoneinfo: *mut PyObject,
        dis: Disambiguate,
    ) -> PyResult<Result<Self, Ambiguity>> {
        use OffsetResult as R;
        Ok(match OffsetResult::for_tz(py_api, date, time, zoneinfo)? {
            R::Unambiguous(offset_secs) => Ok(ZonedDateTime {
                date,
                time,
                offset_secs,
                zoneinfo,
            }),
            R::Fold(offset0, offset1) => match dis {
                Disambiguate::Compatible | Disambiguate::Earlier => Ok(offset0),
                Disambiguate::Later => Ok(offset1),
                Disambiguate::Raise => Err(Ambiguity::Fold),
            }
            .map(|offset_secs| ZonedDateTime {
                date,
                time,
                offset_secs,
                zoneinfo,
            }),
            R::Gap(offset0, offset1) => match dis {
                Disambiguate::Compatible | Disambiguate::Later => Ok((offset1, offset1 - offset0)),
                Disambiguate::Earlier => Ok((offset0, offset0 - offset1)),
                Disambiguate::Raise => Err(Ambiguity::Gap),
            }
            .map(|(offset_secs, shift)| {
                ZonedDateTime {
                    date,
                    time,
                    offset_secs,
                    zoneinfo,
                }
                .small_naive_shift(shift)
            }),
        })
    }

    pub(crate) const fn to_instant(self) -> Instant {
        Instant::from_datetime(self.date, self.time).shift_secs_unchecked(-self.offset_secs as i64)
    }

    const fn small_naive_shift(&self, secs: i32) -> Self {
        debug_assert!(secs.abs() < 86400 * 2);
        let Self { date, time, .. } = self;
        let day_seconds = time.seconds() + secs;
        let (new_date, new_time) = match day_seconds.div_euclid(86400) {
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
        ZonedDateTime {
            date: new_date,
            time: new_time,
            ..*self
        }
    }

    pub(crate) unsafe fn from_utc(
        &PyDateTime_CAPI {
            DateTime_FromDateAndTime,
            DateTimeType,
            ..
        }: &PyDateTime_CAPI,
        Date { year, month, day }: Date,
        Time {
            hour,
            minute,
            second,
            nanos,
        }: Time,
        zoneinfo: *mut PyObject,
    ) -> PyResult<Self> {
        let dt = PyObject_CallMethodOneArg(
            zoneinfo,
            steal!("fromutc".to_py()?),
            steal!(DateTime_FromDateAndTime(
                year.into(),
                month.into(),
                day.into(),
                hour.into(),
                minute.into(),
                second.into(),
                0, // no sub-second ZoneInfo offsets exist
                zoneinfo,
                DateTimeType,
            )),
        )
        .as_result()?;
        defer_decref!(dt);

        Ok(ZonedDateTime {
            date: Date {
                year: PyDateTime_GET_YEAR(dt) as u16,
                month: PyDateTime_GET_MONTH(dt) as u8,
                day: PyDateTime_GET_DAY(dt) as u8,
            },
            time: Time {
                hour: PyDateTime_DATE_GET_HOUR(dt) as u8,
                minute: PyDateTime_DATE_GET_MINUTE(dt) as u8,
                second: PyDateTime_DATE_GET_SECOND(dt) as u8,
                nanos,
            },
            offset_secs: offset_from_py_dt(dt)?,
            zoneinfo,
        })
    }

    pub(crate) const fn to_offset(self) -> OffsetDateTime {
        OffsetDateTime {
            date: self.date,
            time: self.time,
            offset_secs: self.offset_secs,
        }
    }
}

impl Display for ZonedDateTime {
    fn fmt(&self, f: &mut Formatter<'_>) -> fmt::Result {
        let &ZonedDateTime {
            date,
            time,
            offset_secs,
            zoneinfo,
        } = self;
        write!(
            f,
            "{} {}{}[{}]",
            date,
            time,
            offset_fmt(offset_secs),
            unsafe { zoneinfo_key(zoneinfo).try_except("???") }
        )
    }
}

unsafe fn zoneinfo_key<'a>(zoneinfo: *mut PyObject) -> PyResult<&'a str> {
    let key_obj = PyObject_GetAttrString(zoneinfo, c_str!("key"));
    defer_decref!(key_obj);
    key_obj
        .to_str()?
        .ok_or_else(|| type_error!("zoneinfo key must be a string"))
}

unsafe fn __new__(cls: *mut PyTypeObject, args: *mut PyObject, kwargs: *mut PyObject) -> PyReturn {
    let &State {
        zoneinfo_type,
        datetime_api: api,
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
    let mut tz: *mut PyObject = NULL();
    let mut disambiguate: *mut PyObject = str_raise;

    // OPTIMIZE: parse them manually, which is more efficient
    if PyArg_ParseTupleAndKeywords(
        args,
        kwargs,
        c_str!("lll|llllU$U:ZonedDateTime"),
        vec![
            c_str!("year") as *mut c_char,
            c_str!("month") as *mut c_char,
            c_str!("day") as *mut c_char,
            c_str!("hour") as *mut c_char,
            c_str!("minute") as *mut c_char,
            c_str!("second") as *mut c_char,
            c_str!("nanosecond") as *mut c_char,
            c_str!("tz") as *mut c_char,
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
        &mut tz,
        &mut disambiguate,
    ) == 0
    {
        return Err(py_error!());
    }

    if tz.is_null() {
        return Err(type_error!("tz argument is required"));
    }
    let zoneinfo = PyObject_CallOneArg(zoneinfo_type.cast(), tz).as_result()?;
    defer_decref!(zoneinfo); // a succesful ZonedDT init will Py_INCREF it again

    // TODO: Stricter date validation due to offset?
    let date = Date::from_longs(year, month, day).ok_or_else(|| value_error!("Invalid date"))?;
    let time = Time::from_longs(hour, minute, second, nanos)
        .ok_or_else(|| value_error!("Invalid time"))?;
    let dis = Disambiguate::parse(
        disambiguate
            .to_utf8()?
            .ok_or_else(|| type_error!("disambiguate must be a string"))?,
    )
    .ok_or_else(|| value_error!("Invalid disambiguate value"))?;
    match ZonedDateTime::from_local(api, date, time, zoneinfo, dis)? {
        Ok(dt) => new_unchecked(cls, dt),
        Err(Ambiguity::Fold) => Err(py_error!(
            exc_ambiguous.cast(),
            "%s is ambiguous in timezone %U",
            format!("{} {}\0", date, time).as_ptr().cast::<c_char>(),
            tz
        )),
        Err(Ambiguity::Gap) => Err(py_error!(
            exc_skipped.cast(),
            "%s is skipped in timezone %U",
            format!("{} {}\0", date, time).as_ptr().cast::<c_char>(),
            tz
        )),
    }
}

pub(crate) unsafe fn new_unchecked(type_: *mut PyTypeObject, dt: ZonedDateTime) -> PyReturn {
    let f: allocfunc = (*type_).tp_alloc.expect("tp_alloc is not set");
    let slf = f(type_, 0).cast::<PyZonedDateTime>();
    match slf.cast::<PyObject>().as_mut() {
        Some(r) => {
            ptr::addr_of_mut!((*slf).data).write(dt);
            Py_INCREF(dt.zoneinfo);
            Ok(r)
        }
        None => Err(PyErrOccurred()),
    }
}

unsafe extern "C" fn dealloc(slf: *mut PyObject) {
    Py_DECREF(ZonedDateTime::extract(slf).zoneinfo);
    let tp_free = PyType_GetSlot(Py_TYPE(slf), Py_tp_free);
    debug_assert_ne!(tp_free, NULL());
    let f: freefunc = std::mem::transmute(tp_free);
    f(slf.cast());
}

unsafe fn __repr__(slf: *mut PyObject) -> PyReturn {
    format!("ZonedDateTime({})", ZonedDateTime::extract(slf)).to_py()
}

unsafe fn __str__(slf: *mut PyObject) -> PyReturn {
    format!("{}", ZonedDateTime::extract(slf)).to_py()
}

unsafe fn __richcmp__(a_obj: *mut PyObject, b_obj: *mut PyObject, op: c_int) -> PyReturn {
    // TODO: test reflexivity
    let type_a = Py_TYPE(a_obj);
    let type_b = Py_TYPE(b_obj);
    let inst_a = ZonedDateTime::extract(a_obj).to_instant();
    let inst_b = if type_b == type_a {
        ZonedDateTime::extract(b_obj).to_instant()
    } else if type_b == State::for_type(type_a).utc_datetime_type {
        Instant::extract(b_obj)
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

unsafe fn __hash__(slf: *mut PyObject) -> Py_hash_t {
    ZonedDateTime::extract(slf).to_instant().pyhash()
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
    let zdt = ZonedDateTime::extract(slf);
    if Py_TYPE(delta_obj) == time_delta_type {
        let mut delta = TimeDelta::extract(delta_obj);
        if negate {
            delta = -delta;
        };
        let DateTime { date, time } =
            Instant::from_nanos(zdt.to_instant().total_nanos() + delta.total_nanos())
                .ok_or_else(|| value_error!("Resulting datetime is out of range"))?
                .to_datetime();
        new_unchecked(
            type_,
            ZonedDateTime::from_utc(py_api, date, time, zdt.zoneinfo)?,
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
        let ZonedDateTime {
            date,
            time,
            zoneinfo,
            ..
        } = zdt;
        new_unchecked(
            type_,
            ZonedDateTime::from_local(
                py_api,
                date.shift(0, months, days)
                    .ok_or_else(|| value_error!("Resulting date is out of range"))?,
                time,
                zoneinfo,
                Disambiguate::Compatible,
            )?
            // No error possible in "Compatible" mode
            .unwrap(),
        )
    } else {
        Ok(newref(&mut *Py_NotImplemented()))
    }
}

unsafe fn __add__(slf: *mut PyObject, arg: *mut PyObject) -> PyReturn {
    _shift(slf, arg, false)
}

unsafe fn __sub__(obj_a: *mut PyObject, obj_b: *mut PyObject) -> PyReturn {
    let type_a = Py_TYPE(obj_a);
    let type_b = Py_TYPE(obj_b);

    // Easy case: ZonedDT - ZonedDT
    let (inst_a, inst_b) = if type_a == type_b {
        (
            ZonedDateTime::extract(obj_a).to_instant(),
            ZonedDateTime::extract(obj_b).to_instant(),
        )
    // Other cases are more difficult, as they can be triggered
    // by reflexive operations with arbitrary types.
    // We need to eliminate them carefully.
    } else {
        // TODO: handle failure
        let mod_a = PyType_GetModule(type_a);
        let mod_b = PyType_GetModule(type_b);
        if mod_a == mod_b {
            // at this point we know that `a` is a `ZonedDT`
            let inst_a = ZonedDateTime::extract(obj_a).to_instant();
            let inst_b = if type_b == State::for_mod(mod_a).utc_datetime_type {
                Instant::extract(obj_b)
            } else if type_b == State::for_mod(mod_a).offset_datetime_type
                || type_b == State::for_mod(mod_a).local_datetime_type
            {
                OffsetDateTime::extract(obj_b).to_instant()
            } else {
                return _shift(obj_a, obj_b, true);
            };
            (inst_a, inst_b)
        } else {
            // TODO: type error
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

unsafe fn exact_eq(obj_a: &mut PyObject, obj_b: &mut PyObject) -> PyReturn {
    if Py_TYPE(obj_a) == Py_TYPE(obj_b) {
        (ZonedDateTime::extract(obj_a) == ZonedDateTime::extract(obj_b)).to_py()
    } else {
        Err(type_error!("Argument must be ZonedDateTime, got %R", obj_b))
    }
}

unsafe fn in_tz(slf: &mut PyObject, tz: &mut PyObject) -> PyReturn {
    let cls = Py_TYPE(slf);
    let &State {
        zoneinfo_type,
        datetime_api: py_api,
        ..
    } = State::for_type(cls);
    let new_zoneinfo = PyObject_CallOneArg(zoneinfo_type.cast(), tz).as_result()?;
    defer_decref!(new_zoneinfo);
    let zdt = ZonedDateTime::extract(slf);
    let ZonedDateTime { date, time, .. } = zdt.small_naive_shift(-zdt.offset_secs);
    new_unchecked(
        cls,
        ZonedDateTime::from_utc(py_api, date, time, new_zoneinfo)?,
    )
}

pub(crate) unsafe fn unpickle(module: &mut PyObject, args: &[*mut PyObject]) -> PyReturn {
    if args.len() != 2 {
        return Err(type_error!("Invalid pickle data"));
    }
    let &State {
        zoneinfo_type,
        zoned_datetime_type,
        ..
    } = State::for_mod(module);
    let mut packed = args[0]
        .to_bytes()?
        .ok_or_else(|| type_error!("Invalid pickle data"))?;
    let zoneinfo = PyObject_CallOneArg(zoneinfo_type.cast(), args[1]).as_result()?;
    defer_decref!(zoneinfo);
    let new = new_unchecked(
        zoned_datetime_type,
        ZonedDateTime {
            date: Date {
                // TODO: can unpack_one! be a function?
                // TODO: don't segfault on invalid data?
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
            zoneinfo,
        },
    );
    if !packed.is_empty() {
        return Err(type_error!("Invalid pickle data"));
    }
    new
}

unsafe fn py_datetime(slf: &mut PyObject, _: &mut PyObject) -> PyReturn {
    let ZonedDateTime {
        date: Date { year, month, day },
        time:
            Time {
                hour,
                minute,
                second,
                nanos,
            },
        zoneinfo,
        ..
    } = ZonedDateTime::extract(slf);
    let &State {
        datetime_api:
            &PyDateTime_CAPI {
                DateTime_FromDateAndTimeAndFold,
                DateTimeType,
                ..
            },
        ..
    } = State::for_type(Py_TYPE(slf));
    // TODO: set the fold correctly
    DateTime_FromDateAndTimeAndFold(
        year.into(),
        month.into(),
        day.into(),
        hour.into(),
        minute.into(),
        second.into(),
        (nanos / 1_000) as c_int,
        zoneinfo,
        0,
        DateTimeType,
    )
    .as_result()
}

unsafe fn in_utc(slf: &mut PyObject, _: &mut PyObject) -> PyReturn {
    utc_datetime::new_unchecked(
        State::for_obj(slf).utc_datetime_type,
        ZonedDateTime::extract(slf).to_instant(),
    )
}

unsafe fn in_fixed_offset(slf_obj: &mut PyObject, args: &[*mut PyObject]) -> PyReturn {
    let cls = Py_TYPE(slf_obj);
    let slf = ZonedDateTime::extract(slf_obj);
    let &State {
        offset_datetime_type,
        time_delta_type,
        ..
    } = State::for_type(cls);
    if args.is_empty() {
        offset_datetime::new_unchecked(
            offset_datetime_type,
            OffsetDateTime {
                date: slf.date,
                time: slf.time,
                offset_secs: slf.offset_secs,
            },
        )
    } else if args.len() > 1 {
        Err(type_error!("in_fixed_offset() takes at most 1 argument"))
    } else {
        let offset_secs = offset_datetime::extract_offset(args[0], time_delta_type)?;
        let ZonedDateTime { date, time, .. } = slf.small_naive_shift(offset_secs - slf.offset_secs);
        offset_datetime::new_unchecked(
            offset_datetime_type,
            OffsetDateTime {
                date,
                time,
                offset_secs,
            },
        )
    }
}

unsafe fn in_local_system(slf: *mut PyObject, _: *mut PyObject) -> PyReturn {
    let &State {
        datetime_api: py_api,
        local_datetime_type,
        ..
    } = State::for_obj(slf);
    local_datetime::new_unchecked(
        local_datetime_type,
        ZonedDateTime::extract(slf)
            .to_offset()
            .to_local_system(py_api)?,
    )
}

unsafe fn date(slf: *mut PyObject, _: *mut PyObject) -> PyReturn {
    date::new_unchecked(
        State::for_obj(slf).date_type,
        ZonedDateTime::extract(slf).date,
    )
}

unsafe fn time(slf: *mut PyObject, _: *mut PyObject) -> PyReturn {
    time::new_unchecked(
        State::for_obj(slf).time_type,
        ZonedDateTime::extract(slf).time,
    )
}

unsafe fn with_date(
    slf: *mut PyObject,
    cls: *mut PyTypeObject,
    args: &[*mut PyObject],
    kwargs: &[(*mut PyObject, *mut PyObject)],
) -> PyReturn {
    let &State {
        date_type,
        datetime_api: py_api,
        str_disambiguate,
        exc_skipped,
        exc_ambiguous,
        ..
    } = State::for_obj(slf);

    if args.len() != 1 {
        return Err(type_error!(
            "with_date() takes 1 positional argument but %lld were given",
            args.len()
        ));
    }

    let dis = if kwargs.is_empty() {
        Disambiguate::Raise
    } else if kwargs.len() > 1 {
        return Err(type_error!(
            "with_date() expected at most 2 arguments, got %lld",
            kwargs.len() + 1
        ));
    } else if kwargs[0].0 == str_disambiguate {
        Disambiguate::parse(
            kwargs[0]
                .1
                .to_utf8()?
                .ok_or_else(|| type_error!("disambiguate must be a string"))?,
        )
        .ok_or_else(|| value_error!("Invalid disambiguate value"))?
    } else {
        return Err(type_error!(
            "with_date() got an unexpected keyword argument %R",
            kwargs[0].0
        ));
    };

    let ZonedDateTime { time, zoneinfo, .. } = ZonedDateTime::extract(slf);
    if Py_TYPE(args[0]) == date_type {
        match ZonedDateTime::from_local(py_api, Date::extract(args[0]), time, zoneinfo, dis)? {
            Ok(d) => new_unchecked(cls, d),
            Err(Ambiguity::Fold) => Err(py_error!(
                exc_ambiguous.cast(),
                "The new date is ambiguous in the current timezone"
            )),
            Err(Ambiguity::Gap) => Err(py_error!(
                exc_skipped.cast(),
                "The new date is skipped in the current timezone"
            )),
        }
    } else {
        Err(type_error!("date must be a Date instance"))
    }
}

unsafe fn with_time(
    slf: *mut PyObject,
    cls: *mut PyTypeObject,
    args: &[*mut PyObject],
    kwargs: &[(*mut PyObject, *mut PyObject)],
) -> PyReturn {
    let &State {
        time_type,
        datetime_api: py_api,
        str_disambiguate,
        exc_skipped,
        exc_ambiguous,
        ..
    } = State::for_obj(slf);

    if args.len() != 1 {
        return Err(type_error!(
            "with_time() takes 1 positional argument but %lld were given",
            args.len()
        ));
    }

    let dis = if kwargs.is_empty() {
        Disambiguate::Raise
    } else if kwargs.len() > 1 {
        return Err(type_error!(
            "with_time() expected at most 2 arguments, got %lld",
            kwargs.len() + 1
        ));
    } else if kwargs[0].0 == str_disambiguate {
        Disambiguate::parse(
            kwargs[0]
                .1
                .to_utf8()?
                .ok_or_else(|| type_error!("disambiguate must be a string"))?,
        )
        .ok_or_else(|| value_error!("Invalid disambiguate value"))?
    } else {
        return Err(type_error!(
            "with_time() got an unexpected keyword argument %R",
            kwargs[0].0
        ));
    };

    let ZonedDateTime { date, zoneinfo, .. } = ZonedDateTime::extract(slf);
    if Py_TYPE(args[0]) == time_type {
        match ZonedDateTime::from_local(py_api, date, Time::extract(args[0]), zoneinfo, dis)? {
            Ok(d) => new_unchecked(cls, d),
            Err(Ambiguity::Fold) => Err(py_error!(
                exc_ambiguous.cast(),
                "The new time is ambiguous in the current timezone"
            )),
            Err(Ambiguity::Gap) => Err(py_error!(
                exc_skipped.cast(),
                "The new time is skipped in the current timezone"
            )),
        }
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
        Err(type_error!("replace() takes no positional arguments"))?;
    }
    let &State {
        str_year,
        str_month,
        str_day,
        str_hour,
        str_minute,
        str_second,
        str_nanosecond,
        str_tz,
        str_disambiguate,
        datetime_api: py_api,
        exc_skipped,
        exc_ambiguous,
        zoneinfo_type,
        ..
    } = State::for_type(cls);
    let ZonedDateTime {
        date,
        time,
        mut zoneinfo,
        ..
    } = ZonedDateTime::extract(slf);
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
        } else if name == str_tz {
            zoneinfo = PyObject_CallOneArg(zoneinfo_type.cast(), value).as_result()?;
            defer_decref!(zoneinfo);
        } else if name == str_disambiguate {
            dis = Disambiguate::parse(
                value
                    .to_utf8()?
                    .ok_or_else(|| type_error!("disambiguate must be a string"))?,
            )
            .ok_or_else(|| value_error!("Invalid disambiguate value"))?;
        } else {
            Err(type_error!(
                "replace() got an unexpected keyword argument %R",
                name
            ))?;
        }
    }
    let date = Date::from_longs(year, month, day).ok_or_else(|| value_error!("Invalid date"))?;
    let time = Time::from_longs(hour, minute, second, nanos)
        .ok_or_else(|| value_error!("Invalid time"))?;
    match ZonedDateTime::from_local(py_api, date, time, zoneinfo, dis)? {
        Ok(d) => new_unchecked(cls, d),
        Err(Ambiguity::Fold) => Err(py_error!(
            exc_ambiguous.cast(),
            "%s is ambiguous in timezone %U",
            format!("{} {}\0", date, time).as_ptr().cast::<c_char>(),
            steal!(PyObject_GetAttrString(zoneinfo, c_str!("key")))
        )),
        Err(Ambiguity::Gap) => Err(py_error!(
            exc_skipped.cast(),
            "%s is skipped in timezone %U",
            format!("{} {}\0", date, time).as_ptr().cast::<c_char>(),
            steal!(PyObject_GetAttrString(zoneinfo, c_str!("key")))
        )),
    }
}

unsafe fn now(cls: *mut PyObject, tz: *mut PyObject) -> PyReturn {
    let &State {
        datetime_api:
            &PyDateTime_CAPI {
                DateTime_FromTimestamp,
                DateTimeType,
                ..
            },
        zoneinfo_type,
        ..
    } = State::for_type(cls.cast());
    let zoneinfo = PyObject_CallOneArg(zoneinfo_type.cast(), tz).as_result()? as *mut PyObject;
    defer_decref!(zoneinfo);
    let (timestamp, subsec) = match SystemTime::now().duration_since(SystemTime::UNIX_EPOCH) {
        Ok(dur) => (dur.as_secs() as f64, dur.subsec_nanos()),
        _ => Err(py_error!(PyExc_OSError, "SystemTime before UNIX EPOCH"))?,
    };
    // OPTIMIZE: faster way without fromtimestamp?
    let dt = DateTime_FromTimestamp(
        DateTimeType,
        steal!(PyTuple_Pack(
            2,
            steal!(PyFloat_FromDouble(timestamp)),
            zoneinfo
        )),
        NULL(),
    )
    .as_result()?;
    new_unchecked(
        cls.cast(),
        ZonedDateTime {
            date: Date {
                year: PyDateTime_GET_YEAR(dt) as u16,
                month: PyDateTime_GET_MONTH(dt) as u8,
                day: PyDateTime_GET_DAY(dt) as u8,
            },
            time: Time {
                hour: PyDateTime_DATE_GET_HOUR(dt) as u8,
                minute: PyDateTime_DATE_GET_MINUTE(dt) as u8,
                second: PyDateTime_DATE_GET_SECOND(dt) as u8,
                nanos: subsec,
            },
            offset_secs: offset_from_py_dt(dt)?,
            zoneinfo,
        },
    )
}

// TODO: can remove?
unsafe fn _is_skipped_time(
    &PyDateTime_CAPI {
        DateTimeType,
        DateTime_FromDateAndTimeAndFold,
        ..
    }: &PyDateTime_CAPI,
    dt: *mut PyObject,
) -> PyResult<bool> {
    let fold = PyDateTime_DATE_GET_FOLD(dt);
    let dt_other = DateTime_FromDateAndTimeAndFold(
        PyDateTime_GET_YEAR(dt),
        PyDateTime_GET_MONTH(dt),
        PyDateTime_GET_DAY(dt),
        PyDateTime_DATE_GET_HOUR(dt),
        PyDateTime_DATE_GET_MINUTE(dt),
        PyDateTime_DATE_GET_SECOND(dt),
        0,
        PyDateTime_DATE_GET_TZINFO(dt),
        if fold == 0 { 1 } else { 0 },
        DateTimeType,
    )
    .as_result()? as *mut PyObject;
    defer_decref!(dt_other);
    let (dt_unfolded, dt_folded) = if fold == 0 {
        (dt, dt_other)
    } else {
        (dt_other, dt)
    };
    let off0 = offset_from_py_dt(dt_unfolded)?;
    let off1 = offset_from_py_dt(dt_folded)?;
    Ok(off0 < off1)
}

unsafe fn from_py_datetime(cls: *mut PyObject, dt: *mut PyObject) -> PyReturn {
    let &State {
        datetime_api: py_api,
        zoneinfo_type,
        exc_skipped,
        ..
    } = State::for_type(cls.cast());
    if PyDateTime_Check(dt) == 0 {
        Err(type_error!("Argument must be a datetime.datetime instance"))?;
    }
    let tzinfo = PyDateTime_DATE_GET_TZINFO(dt); // TODO: refcount?
                                                 // TODO: can fail?
    if PyObject_IsInstance(tzinfo, zoneinfo_type.cast()) == 0 {
        Err(value_error!("tzinfo must be a ZoneInfo, got %R", tzinfo))?;
    }

    // OPTIMIZE: we call the offset querying code twice, which is inefficient
    // TODO: simply handle skipped time according to fold
    if _is_skipped_time(py_api, dt)? {
        Err(py_error!(
            exc_skipped.cast(),
            "The datetime %S is skipped in the timezone %R",
            dt, // TODO ???
            steal!(PyObject_GetAttrString(tzinfo, c_str!("key")))
        ))?;
    }

    new_unchecked(
        cls.cast(),
        ZonedDateTime {
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
            zoneinfo: tzinfo,
        },
    )
}

unsafe fn naive(slf: *mut PyObject, _: *mut PyObject) -> PyReturn {
    let ZonedDateTime { date, time, .. } = ZonedDateTime::extract(slf);
    naive_datetime::new_unchecked(
        State::for_obj(slf).naive_datetime_type,
        DateTime { date, time },
    )
}

unsafe fn timestamp(slf: *mut PyObject, _: *mut PyObject) -> PyReturn {
    ZonedDateTime::extract(slf).to_instant().timestamp().to_py()
}

unsafe fn timestamp_millis(slf: *mut PyObject, _: *mut PyObject) -> PyReturn {
    ZonedDateTime::extract(slf)
        .to_instant()
        .timestamp_millis()
        .to_py()
}

unsafe fn timestamp_nanos(slf: *mut PyObject, _: *mut PyObject) -> PyReturn {
    ZonedDateTime::extract(slf)
        .to_instant()
        .timestamp_nanos()
        .to_py()
}

unsafe fn __reduce__(slf: *mut PyObject, _: *mut PyObject) -> PyReturn {
    let ZonedDateTime {
        date: Date { year, month, day },
        time:
            Time {
                hour,
                minute,
                second,
                nanos,
            },
        offset_secs,
        zoneinfo,
    } = ZonedDateTime::extract(slf);
    PyTuple_Pack(
        2,
        State::for_obj(slf).unpickle_zoned_datetime,
        steal!(PyTuple_Pack(
            2,
            steal!(pack![year, month, day, hour, minute, second, nanos, offset_secs].to_py()?),
            steal!(PyObject_GetAttrString(zoneinfo, c_str!("key")).as_result()?),
        )
        .as_result()?),
    )
    .as_result()
}

// checks the args comply with (ts, /, *, tz: str)
unsafe fn check_from_timestamp_args_return_zoneinfo(
    args: &[*mut PyObject],
    kwargs: &[(*mut PyObject, *mut PyObject)],
    &State {
        zoneinfo_type,
        str_tz,
        ..
    }: &State,
) -> PyReturn {
    if args.len() != 1 {
        Err(type_error!(
            "from_timestamp() takes 1 positional argument but %lld were given",
            args.len()
        ))
    } else if kwargs.len() != 1 {
        Err(type_error!(
            "from_timestamp() expected 2 arguments, got %lld",
            args.len() + kwargs.len()
        ))
    } else if kwargs[0].0 == str_tz {
        PyObject_CallOneArg(zoneinfo_type.cast(), kwargs[0].1).as_result()
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
    let zoneinfo = check_from_timestamp_args_return_zoneinfo(args, kwargs, state)?;
    defer_decref!(zoneinfo);
    let DateTime { date, time } = Instant::from_timestamp(
        args[0]
            .to_i64()?
            .ok_or_else(|| type_error!("timestamp must be an integer"))?,
    )
    .ok_or_else(|| value_error!("timestamp is out of range"))?
    .to_datetime();
    new_unchecked(
        cls,
        ZonedDateTime::from_utc(state.datetime_api, date, time, zoneinfo)?,
    )
}

unsafe fn from_timestamp_millis(
    _: *mut PyObject,
    cls: *mut PyTypeObject,
    args: &[*mut PyObject],
    kwargs: &[(*mut PyObject, *mut PyObject)],
) -> PyReturn {
    let state = State::for_type(cls);
    let zoneinfo = check_from_timestamp_args_return_zoneinfo(args, kwargs, state)?;
    defer_decref!(zoneinfo);
    let DateTime { date, time } = Instant::from_timestamp_millis(
        args[0]
            .to_i64()?
            .ok_or_else(|| type_error!("timestamp must be an integer"))?,
    )
    .ok_or_else(|| value_error!("timestamp is out of range"))?
    .to_datetime();
    new_unchecked(
        cls,
        ZonedDateTime::from_utc(state.datetime_api, date, time, zoneinfo)?,
    )
}

unsafe fn from_timestamp_nanos(
    _: *mut PyObject,
    cls: *mut PyTypeObject,
    args: &[*mut PyObject],
    kwargs: &[(*mut PyObject, *mut PyObject)],
) -> PyReturn {
    let state = State::for_type(cls);
    let zoneinfo = check_from_timestamp_args_return_zoneinfo(args, kwargs, state)?;
    defer_decref!(zoneinfo);
    let DateTime { date, time } = Instant::from_timestamp_nanos(
        args[0]
            .to_i128()?
            .ok_or_else(|| type_error!("timestamp must be an integer"))?,
    )
    .ok_or_else(|| value_error!("timestamp is out of range"))?
    .to_datetime();
    new_unchecked(
        cls,
        ZonedDateTime::from_utc(state.datetime_api, date, time, zoneinfo)?,
    )
}

unsafe fn is_ambiguous(slf: *mut PyObject, _: *mut PyObject) -> PyReturn {
    let ZonedDateTime {
        date,
        time,
        zoneinfo,
        ..
    } = ZonedDateTime::extract(slf);
    matches!(
        OffsetResult::for_tz(State::for_obj(slf).datetime_api, date, time, zoneinfo)?,
        OffsetResult::Fold(_, _)
    )
    .to_py()
}

// parse ±HH:MM[:SS] (consuming as much as possible of the input)
fn parse_offset_partial(s: &mut &[u8]) -> Option<i32> {
    debug_assert!(s.len() >= 6);
    if s[3] != b':' {
        return None;
    }
    // the sign (always present)
    let sign = match s[0] {
        b'+' => 1,
        b'-' => -1,
        _ => return None,
    };
    // the HH:MM part
    // FUTURE: technically, this eliminates 2x:00 offsets. There
    // are no such offsets in the IANA database, but they are possible...
    let secs = (get_digit!(s, 1, ..=b'1') * 10 + get_digit!(s, 2)) as i32 * 3600
        + (get_digit!(s, 4, ..=b'5') * 10 + get_digit!(s, 5)) as i32 * 60;
    // the optional seconds part
    match s.get(6) {
        Some(b':') => {
            if s.len() > 8 {
                let result =
                    Some(secs + get_digit!(s, 7, ..=b'5') as i32 * 10 + get_digit!(s, 8) as i32);
                *s = &s[9..];
                result
            } else {
                None
            }
        }
        _ => {
            *s = &s[6..]; // TODO does this work for the empty case?
            Some(secs)
        }
    }
    .map(|s| sign * s)
}

unsafe fn from_default_format(cls: *mut PyObject, s_obj: *mut PyObject) -> PyReturn {
    let s = &mut s_obj
        .to_utf8()?
        .ok_or_else(|| type_error!("Argument must be string"))?;
    let parse_err = || value_error!("Invalid format: %R", s_obj);
    // at least: "YYYY-MM-DD HH:MM:SS+HH:MM[?]"
    if s.len() < 28 || s[10] != b' ' {
        return Err(parse_err());
    }
    let date = Date::parse_partial(s).ok_or_else(parse_err)?;
    *s = &s[1..]; // skip the separator
    let time = Time::parse_partial(s).ok_or_else(parse_err)?;

    // at least "+HH:MM"
    if s.len() < 6 {
        return Err(parse_err());
    }
    let offset_secs = parse_offset_partial(s).ok_or_else(parse_err)?;
    if s.len() < 3 || s[0] != b'[' || s[s.len() - 1] != b']' {
        return Err(parse_err());
    }
    let &State {
        datetime_api: py_api,
        zoneinfo_type,
        exc_invalid_offset,
        ..
    } = State::for_type(cls.cast());
    let zoneinfo = PyObject_CallOneArg(
        zoneinfo_type.cast(),
        steal!(std::str::from_utf8_unchecked(&s[1..s.len() - 1]).to_py()?),
    )
    .as_result()?;
    defer_decref!(zoneinfo);
    let offset_valid = match OffsetResult::for_tz(py_api, date, time, zoneinfo)? {
        OffsetResult::Unambiguous(o) => o == offset_secs,
        OffsetResult::Gap(o1, o2) | OffsetResult::Fold(o1, o2) => {
            o1 == offset_secs || o2 == offset_secs
        }
    };
    if offset_valid {
        new_unchecked(
            cls.cast(),
            ZonedDateTime {
                date,
                time,
                offset_secs,
                zoneinfo,
            },
        )
    } else {
        Err(py_error!(
            exc_invalid_offset.cast(),
            "Invalid offset for timezone %R",
            zoneinfo
        ))
    }
}

static mut METHODS: &[PyMethodDef] = &[
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
    method!(is_ambiguous, "Check if the datetime is ambiguous"),
    method!(from_default_format, "", METH_O | METH_CLASS),
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
        "Create a new instance from a UNIX timestamp in nanoseconds",
        METH_CLASS
    ),
    method_kwargs!(
        replace,
        "Return a new instance with the specified fields replaced"
    ),
    method_kwargs!(with_date, "Return a new instance with the date replaced"),
    method_kwargs!(with_time, "Return a new instance with the time replaced"),
    method_vararg!(in_fixed_offset, "Convert to an equivalent offset datetime"),
    PyMethodDef::zeroed(),
];

unsafe fn get_year(slf: *mut PyObject) -> PyReturn {
    ZonedDateTime::extract(slf).date.year.to_py()
}

unsafe fn get_month(slf: *mut PyObject) -> PyReturn {
    ZonedDateTime::extract(slf).date.month.to_py()
}

unsafe fn get_day(slf: *mut PyObject) -> PyReturn {
    ZonedDateTime::extract(slf).date.day.to_py()
}

unsafe fn get_hour(slf: *mut PyObject) -> PyReturn {
    ZonedDateTime::extract(slf).time.hour.to_py()
}

unsafe fn get_minute(slf: *mut PyObject) -> PyReturn {
    ZonedDateTime::extract(slf).time.minute.to_py()
}

unsafe fn get_second(slf: *mut PyObject) -> PyReturn {
    ZonedDateTime::extract(slf).time.second.to_py()
}

unsafe fn get_nanos(slf: *mut PyObject) -> PyReturn {
    ZonedDateTime::extract(slf).time.nanos.to_py()
}

unsafe fn get_tz(slf: *mut PyObject) -> PyReturn {
    PyObject_GetAttrString(ZonedDateTime::extract(slf).zoneinfo, c_str!("key")).as_result()
}

unsafe fn get_offset(slf: *mut PyObject) -> PyReturn {
    time_delta::new_unchecked(
        State::for_type(Py_TYPE(slf)).time_delta_type,
        time_delta::TimeDelta::from_secs_unchecked(ZonedDateTime::extract(slf).offset_secs as i64),
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
    getter!(get_tz named "tz", "The tz ID"),
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
    name: c_str!("whenever.ZonedDateTime"),
    basicsize: mem::size_of::<PyZonedDateTime>() as _,
    itemsize: 0,
    flags: Py_TPFLAGS_DEFAULT as _,
    slots: unsafe { SLOTS as *const [_] as *mut _ },
};
